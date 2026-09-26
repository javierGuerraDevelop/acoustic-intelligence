#include "radar/supervisor.hpp"

#include <chrono>
#include <cstdio>
#include <thread>

#include "radar/audio_format.hpp"
#include "radar/url_util.hpp"

namespace radar {

namespace {
constexpr int kTickIntervalMs = 50;
constexpr int kStopDrainWaitMs = 250;

HttpSender::Config make_sender_config(const std::string& backend_url, const std::string& token,
                                      const std::string& device_id) {
    const HttpUrl url = parse_http_url(backend_url);
    HttpSender::Config config;
    if (url.valid) {
        config.host = url.host;
        config.port = url.port;
        config.path = url.prefix + "/v1/audio/chunks";
    }
    config.token = token;
    config.device_id = device_id;
    return config;
}
}  // namespace

Supervisor::Supervisor(Options options)
    : options_(std::move(options)),
      ring_(static_cast<std::size_t>(kSourceRingSeconds) *
            static_cast<std::size_t>(kMaxSupportedSourceRateHz)),
      queue_(kSenderQueueMaxChunks),
      pipeline_(
          ring_, queue_, [this] { return device_.consume_discontinuity(); },
          [this] { return device_.dropped_frames(); }),
      sender_(queue_, make_sender_config(options_.backend_url, options_.token, options_.device_id)),
      heartbeat_(options_.backend_url, options_.token) {
    lease_deadline_ = std::chrono::steady_clock::now();  // expired until authorized
}

Supervisor::~Supervisor() {
    request_stop();
}

const char* Supervisor::state_name(State state) {
    switch (state) {
        case State::Stopped:
            return "stopped";
        case State::Starting:
            return "starting";
        case State::Running:
            return "running";
        case State::Error:
            return "error";
    }
    return "error";
}

bool Supervisor::stop_pending() const noexcept {
    if (stop_requested_.load(std::memory_order_acquire)) {
        return true;
    }
    return options_.stop_flag != nullptr &&
           options_.stop_flag->load(std::memory_order_acquire);
}

void Supervisor::send_heartbeat(std::chrono::steady_clock::time_point now) {
    HeartbeatRequest request;
    request.device_id = options_.device_id;
    request.state = state_name(state_);
    if (state_ == State::Running) {
        request.stream_id = pipeline_.stream_id();
        request.native_rate_hz = device_.native_rate();
    }
    request.dropped_frames_total = device_.dropped_frames();
    request.error_code = error_code_;

    const HeartbeatReply reply = heartbeat_.send(request);
    if (reply.ok) {
        if (!ever_authorized_) {
            ever_authorized_ = true;
            std::printf("supervisor: backend reachable, desired_capture=%s\n",
                        reply.desired_capture ? "true" : "false");
        }
        desired_capture_ = reply.desired_capture;
        lease_deadline_ = now + std::chrono::milliseconds(reply.lease_ms);
        settings_revision_ = reply.settings_revision;
        heartbeat_failures_ = 0;
    } else {
        ++heartbeat_failures_;
        if (heartbeat_failures_ == 1 || heartbeat_failures_ % 20 == 0) {
            std::fprintf(stderr, "supervisor: heartbeat failed (%llu): %s\n",
                         static_cast<unsigned long long>(heartbeat_failures_),
                         reply.error.c_str());
        }
    }
}

bool Supervisor::start_capture(std::chrono::steady_clock::time_point now) {
    state_ = State::Starting;
    std::string error;
    if (!device_.start(ring_, &error, options_.null_backend)) {
        state_ = State::Error;
        error_code_ = error;
        next_start_attempt_ = now + std::chrono::milliseconds(kStartRetryIntervalMs);
        std::fprintf(stderr, "supervisor: microphone start failed: %s\n", error.c_str());
        return false;
    }
    const std::string stream_id =
        pipeline_.begin_stream(device_.native_rate(), std::chrono::system_clock::now());
    error_code_.clear();
    state_ = State::Running;
    std::printf("supervisor: capture running device='%s' native_rate=%u stream=%s\n",
                device_.device_name().c_str(), device_.native_rate(), stream_id.c_str());
    return true;
}

void Supervisor::stop_capture() {
    if (state_ == State::Stopped) {
        return;
    }
    device_.stop();  // waits for the callback to finish
    pipeline_.end_stream();
    const auto deadline =
        std::chrono::steady_clock::now() + std::chrono::milliseconds(kStopDrainWaitMs);
    while (pipeline_.stream_active() && std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    queue_.clear();
    state_ = State::Stopped;
    error_code_.clear();
    std::printf("supervisor: capture stopped\n");
}

void Supervisor::tick(std::chrono::steady_clock::time_point now) {
    const bool lease_valid = now < lease_deadline_;
    const bool want_capture = desired_capture_ && lease_valid;

    if (want_capture) {
        if ((state_ == State::Stopped || state_ == State::Error) && now >= next_start_attempt_) {
            start_capture(now);
        }
        return;
    }

    if (state_ != State::Stopped) {
        if (desired_capture_ && !lease_valid) {
            std::fprintf(stderr, "supervisor: lease expired, closing capture\n");
        }
        stop_capture();
    }
}

int Supervisor::run() {
    if (!heartbeat_.valid()) {
        std::fprintf(stderr, "supervisor: invalid backend url: %s\n", options_.backend_url.c_str());
        return 2;
    }
    if (options_.token.empty()) {
        std::fprintf(stderr, "supervisor: CAPTURE_TOKEN is empty; requests will be unauthenticated\n");
    }
    std::printf(
        "supervisor: backend=%s device_id=%s token=%s\n", heartbeat_.base_url().c_str(),
        options_.device_id.c_str(), options_.token.empty() ? "absent" : "present");

    sender_.start();
    pipeline_.start();

    const auto started_at = std::chrono::steady_clock::now();
    auto next_heartbeat = started_at;
    while (!stop_pending()) {
        const auto now = std::chrono::steady_clock::now();
        if (options_.run_seconds > 0 &&
            now - started_at >= std::chrono::seconds(options_.run_seconds)) {
            break;
        }
        if (now >= next_heartbeat) {
            send_heartbeat(now);
            next_heartbeat = now + std::chrono::milliseconds(kHeartbeatIntervalMs);
        }
        tick(now);
        std::this_thread::sleep_for(std::chrono::milliseconds(kTickIntervalMs));
    }

    stop_capture();
    pipeline_.stop();
    sender_.stop();

    std::printf(
        "final: chunks_emitted=%llu stream_rotations=%llu sent=%llu send_failed=%llu "
        "queue_dropped=%llu bytes_sent=%llu dropped_source_frames=%llu settings_revision=%d\n",
        static_cast<unsigned long long>(pipeline_.chunks_emitted()),
        static_cast<unsigned long long>(pipeline_.stream_rotations()),
        static_cast<unsigned long long>(sender_.stats().sent.load(std::memory_order_relaxed)),
        static_cast<unsigned long long>(sender_.stats().failed.load(std::memory_order_relaxed)),
        static_cast<unsigned long long>(queue_.dropped()),
        static_cast<unsigned long long>(sender_.bytes_sent()),
        static_cast<unsigned long long>(device_.dropped_frames()), settings_revision_);
    return 0;
}

}  // namespace radar
