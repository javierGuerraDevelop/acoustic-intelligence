#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <string>

#include "radar/capture_device.hpp"
#include "radar/capture_pipeline.hpp"
#include "radar/chunk_queue.hpp"
#include "radar/heartbeat_client.hpp"
#include "radar/http_sender.hpp"
#include "radar/spsc_ring.hpp"

namespace radar {

// Superintendent thread: heartbeats the local Python service every 500 ms,
// honors the capture lease and desired_capture flag, and owns device
// start/stop. Capture defaults off until a successful heartbeat authorizes it.
class Supervisor {
public:
    struct Options {
        std::string backend_url = "http://127.0.0.1:8000";
        std::string token;
        std::string device_id;
        std::atomic<bool>* stop_flag = nullptr;  // optional external stop signal
        bool null_backend = false;               // headless lifecycle tests only
        int run_seconds = 0;                     // 0 = run until stopped
    };

    explicit Supervisor(Options options);
    ~Supervisor();

    Supervisor(const Supervisor&) = delete;
    Supervisor& operator=(const Supervisor&) = delete;

    // Blocking run loop; returns process exit code.
    int run();
    void request_stop() noexcept { stop_requested_.store(true, std::memory_order_release); }

private:
    enum class State { Stopped, Starting, Running, Error };

    static const char* state_name(State state);
    bool stop_pending() const noexcept;
    void send_heartbeat(std::chrono::steady_clock::time_point now);
    void tick(std::chrono::steady_clock::time_point now);
    bool start_capture(std::chrono::steady_clock::time_point now);
    void stop_capture();

    Options options_;
    // Four seconds at the maximum supported native rate; bounded 1.5 MiB.
    SpscRing ring_;
    ChunkQueue queue_;
    CaptureDevice device_;
    CapturePipeline pipeline_;
    HttpSender sender_;
    HeartbeatClient heartbeat_;

    State state_ = State::Stopped;
    bool desired_capture_ = false;
    bool ever_authorized_ = false;
    int settings_revision_ = 0;
    std::string error_code_;
    std::chrono::steady_clock::time_point lease_deadline_{};
    std::chrono::steady_clock::time_point next_start_attempt_{};
    std::uint64_t heartbeat_failures_ = 0;
    std::atomic<bool> stop_requested_{false};
};

}  // namespace radar
