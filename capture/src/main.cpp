// Live Sound Radar capture process entry point.
//
// Subcommands:
//   list      enumerate capture devices
//   smoke     capture from the default device and print frame/RMS diagnostics
//   run       supervisor: heartbeat-controlled capture + chunk sender
//   fixture   synthetic producer that exercises the same pipeline/transport
//             without a microphone (mock receiver development only)
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include <miniaudio.h>

#include "radar/audio_format.hpp"
#include "radar/capture_pipeline.hpp"
#include "radar/chunk_queue.hpp"
#include "radar/http_sender.hpp"
#include "radar/spsc_ring.hpp"
#include "radar/supervisor.hpp"
#include "radar/url_util.hpp"

namespace {

constexpr const char* kDefaultDeviceId = "70c4af1d-9b7c-4c28-a66c-a87489376e42";
constexpr double kPi                   = 3.14159265358979323846;

std::atomic<bool> g_stop { false };

void handle_signal(int)
{
    g_stop.store(true, std::memory_order_release);
}

std::string env_or(const char* name, const std::string& fallback)
{
    const char* value = std::getenv(name);
    return (value != nullptr && *value != '\0') ? std::string(value) : fallback;
}

std::string backend_url_from_env()
{
    const std::string explicit_url = env_or("CAPTURE_BACKEND_URL", "");
    if (!explicit_url.empty()) {
        return explicit_url;
    }
    const std::string host = env_or("LOCAL_HOST", "127.0.0.1");
    const std::string port = env_or("LOCAL_PORT", "8000");
    return "http://" + host + ":" + port;
}

void print_usage()
{
    std::printf(
        "usage: radar_capture <command> [options]\n"
        "  list                         enumerate capture devices\n"
        "  smoke [--seconds N] [--null-backend]\n"
        "  run [--backend URL] [--device-id UUID] [--token TOKEN] [--null-backend]\n"
        "      [--run-seconds N]\n"
        "  fixture [--seconds N] [--tone-hz HZ] [--backend URL] [--device-id UUID]\n"
        "\n"
        "env: CAPTURE_BACKEND_URL, LOCAL_HOST, LOCAL_PORT, CAPTURE_TOKEN, DEVICE_ID\n");
}

std::string option_value(int argc, char** argv, int& index, const char* name)
{
    if (index + 1 >= argc) {
        std::fprintf(stderr, "missing value for %s\n", name);
        std::exit(2);
    }
    return argv[++index];
}

int run_list()
{
    ma_context context;
    if (ma_context_init(nullptr, 0, nullptr, &context) != MA_SUCCESS) {
        std::fprintf(stderr, "ma_context_init failed\n");
        return 1;
    }
    ma_device_info* playback = nullptr;
    ma_uint32 playback_count = 0;
    ma_device_info* capture  = nullptr;
    ma_uint32 capture_count  = 0;
    if (ma_context_get_devices(&context, &playback, &playback_count, &capture, &capture_count) == MA_SUCCESS) {
        std::printf("capture devices: %u\n", capture_count);
        for (ma_uint32 i = 0; i < capture_count; ++i) {
            std::printf("  [%u] %s%s\n", i, capture[i].name,
                capture[i].isDefault ? " (default)" : "");
        }
    }
    ma_context_uninit(&context);
    return 0;
}

struct SmokeContext {
    std::atomic<std::uint64_t> frames { 0 };
    std::atomic<std::uint64_t> dropped { 0 };
    // callback writes, main thread reads; relaxed is sufficient
    std::atomic<float> peak { 0.0f };
};

void smoke_callback(ma_device* device, void* /*output*/, const void* input,
    ma_uint32 frame_count)
{
    auto* context = static_cast<SmokeContext*>(device->pUserData);
    if (input == nullptr) {
        context->dropped.fetch_add(frame_count, std::memory_order_relaxed);
        return;
    }
    const auto* samples = static_cast<const float*>(input);
    float local_peak    = context->peak.load(std::memory_order_relaxed);
    for (ma_uint32 i = 0; i < frame_count; ++i) {
        local_peak = std::max(local_peak, std::fabs(samples[i]));
    }
    context->peak.store(local_peak, std::memory_order_relaxed);
    context->frames.fetch_add(frame_count, std::memory_order_relaxed);
}

int run_smoke(int seconds, bool null_backend)
{
    ma_context context;
    ma_backend backends[] = { ma_backend_null };
    if (ma_context_init(null_backend ? backends : nullptr, null_backend ? 1 : 0, nullptr,
            &context)
        != MA_SUCCESS) {
        std::fprintf(stderr, "ma_context_init failed\n");
        return 1;
    }

    ma_device_config config         = ma_device_config_init(ma_device_type_capture);
    config.capture.format           = ma_format_f32;
    config.capture.channels         = 1;
    config.sampleRate               = 0; // native rate
    config.periodSizeInMilliseconds = 10;

    SmokeContext smoke;
    config.pUserData    = &smoke;
    config.dataCallback = smoke_callback;

    ma_device device;
    if (ma_device_init(&context, &config, &device) != MA_SUCCESS) {
        std::fprintf(stderr, "microphone unavailable or permission denied\n");
        ma_context_uninit(&context);
        return 2;
    }
    std::printf("device: %s\n", device.capture.name);
    std::printf("native_rate_hz: %u\n", device.sampleRate);
    if (ma_device_start(&device) != MA_SUCCESS) {
        std::fprintf(stderr, "ma_device_start failed\n");
        ma_device_uninit(&device);
        ma_context_uninit(&context);
        return 3;
    }

    std::uint64_t previous_frames = 0;
    for (int elapsed = 1; elapsed <= seconds; ++elapsed) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
        const std::uint64_t frames = smoke.frames.load(std::memory_order_relaxed);
        const std::uint64_t delta  = frames - previous_frames;
        previous_frames            = frames;
        std::printf("t=%ds frames_delta=%llu peak=%.3f dropped=%llu\n", elapsed,
            static_cast<unsigned long long>(delta),
            static_cast<double>(smoke.peak.load(std::memory_order_relaxed)),
            static_cast<unsigned long long>(smoke.dropped.load(std::memory_order_relaxed)));
    }

    ma_device_stop(&device);
    ma_device_uninit(&device);
    ma_context_uninit(&context);
    std::printf("total_frames=%llu dropped=%llu\n",
        static_cast<unsigned long long>(smoke.frames.load(std::memory_order_relaxed)),
        static_cast<unsigned long long>(smoke.dropped.load(std::memory_order_relaxed)));
    return 0;
}

struct RunOptions {
    std::string backend_url;
    std::string device_id;
    std::string token;
    bool null_backend = false;
    int run_seconds   = 0;
};

int run_supervisor(const RunOptions& options)
{
    radar::Supervisor::Options supervisor_options;
    supervisor_options.backend_url  = options.backend_url;
    supervisor_options.device_id    = options.device_id;
    supervisor_options.token        = options.token;
    supervisor_options.stop_flag    = &g_stop;
    supervisor_options.null_backend = options.null_backend;
    supervisor_options.run_seconds  = options.run_seconds;

    radar::Supervisor supervisor(std::move(supervisor_options));
    return supervisor.run();
}

struct FixtureOptions {
    int seconds    = 5;
    double tone_hz = 1000.0;
    std::string backend_url;
    std::string device_id;
    std::string token;
};

int run_fixture(const FixtureOptions& options)
{
    const radar::HttpUrl url = radar::parse_http_url(options.backend_url);
    if (!url.valid) {
        std::fprintf(stderr, "fixture: invalid backend url: %s\n", options.backend_url.c_str());
        return 2;
    }

    radar::SpscRing ring(48000 * radar::kSourceRingSeconds);
    radar::ChunkQueue queue(radar::kSenderQueueMaxChunks);
    radar::CapturePipeline pipeline(ring, queue, [] { return false; }, [] { return 0; });
    radar::HttpSender::Config sender_config;
    sender_config.host      = url.host;
    sender_config.port      = url.port;
    sender_config.path      = url.prefix + "/v1/audio/chunks";
    sender_config.device_id = options.device_id;
    sender_config.token     = options.token;
    radar::HttpSender sender(queue, sender_config);

    sender.start();
    pipeline.start();
    pipeline.begin_stream(48000, std::chrono::system_clock::now());

    constexpr std::size_t kBlockFrames = 480; // 10 ms at 48 kHz
    std::vector<float> block(kBlockFrames);
    const std::size_t total = static_cast<std::size_t>(options.seconds) * 48000;

    std::printf("fixture: sending %d s at 48000 Hz, tone %.1f Hz to %s\n", options.seconds,
        options.tone_hz, options.backend_url.c_str());
    std::size_t position = 0;
    while (position < total && !g_stop.load(std::memory_order_acquire)) {
        if (ring.writable() < kBlockFrames) {
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
            continue;
        }
        for (std::size_t i = 0; i < kBlockFrames; ++i) {
            const double t = static_cast<double>(position + i) / 48000.0;
            block[i]       = static_cast<float>(0.5 * std::sin(2.0 * kPi * options.tone_hz * t));
        }
        ring.write(block.data(), kBlockFrames);
        ring.notify();
        position += kBlockFrames;
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    pipeline.end_stream();
    for (int i = 0; i < 50 && pipeline.stream_active(); ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    pipeline.stop();
    sender.stop();

    std::printf("fixture: chunks=%llu rotations=%llu sent=%llu failed=%llu\n",
        static_cast<unsigned long long>(pipeline.chunks_emitted()),
        static_cast<unsigned long long>(pipeline.stream_rotations()),
        static_cast<unsigned long long>(sender.stats().sent.load()),
        static_cast<unsigned long long>(sender.stats().failed.load()));
    return 0;
}

} // namespace

int main(int argc, char** argv)
{
    std::signal(SIGINT, handle_signal);
#ifdef SIGTERM
    std::signal(SIGTERM, handle_signal);
#endif

    if (argc < 2) {
        print_usage();
        return 2;
    }
    const std::string command = argv[1];

    if (command == "list") {
        return run_list();
    }
    if (command == "smoke") {
        int seconds       = 3;
        bool null_backend = false;
        for (int i = 2; i < argc; ++i) {
            if (std::strcmp(argv[i], "--null-backend") == 0) {
                null_backend = true;
            } else if (std::strcmp(argv[i], "--seconds") == 0) {
                seconds = std::atoi(option_value(argc, argv, i, "--seconds").c_str());
            }
        }
        return run_smoke(seconds, null_backend);
    }
    if (command == "run") {
        RunOptions options;
        options.backend_url = backend_url_from_env();
        options.device_id   = env_or("DEVICE_ID", kDefaultDeviceId);
        options.token       = env_or("CAPTURE_TOKEN", "");
        for (int i = 2; i < argc; ++i) {
            if (std::strcmp(argv[i], "--backend") == 0) {
                options.backend_url = option_value(argc, argv, i, "--backend");
            } else if (std::strcmp(argv[i], "--device-id") == 0) {
                options.device_id = option_value(argc, argv, i, "--device-id");
            } else if (std::strcmp(argv[i], "--token") == 0) {
                options.token = option_value(argc, argv, i, "--token");
            } else if (std::strcmp(argv[i], "--null-backend") == 0) {
                options.null_backend = true;
            } else if (std::strcmp(argv[i], "--run-seconds") == 0) {
                options.run_seconds = std::atoi(option_value(argc, argv, i, "--run-seconds").c_str());
            }
        }
        return run_supervisor(options);
    }
    if (command == "fixture") {
        FixtureOptions options;
        options.backend_url = backend_url_from_env();
        options.device_id   = env_or("DEVICE_ID", kDefaultDeviceId);
        options.token       = env_or("CAPTURE_TOKEN", "");
        for (int i = 2; i < argc; ++i) {
            if (std::strcmp(argv[i], "--seconds") == 0) {
                options.seconds = std::atoi(option_value(argc, argv, i, "--seconds").c_str());
                if (options.seconds <= 0 || options.seconds > 3600) {
                    std::fprintf(stderr, "--seconds must be in 1..3600\n");
                    return 2;
                }
            } else if (std::strcmp(argv[i], "--tone-hz") == 0) {
                options.tone_hz = std::atof(option_value(argc, argv, i, "--tone-hz").c_str());
            } else if (std::strcmp(argv[i], "--backend") == 0) {
                options.backend_url = option_value(argc, argv, i, "--backend");
            } else if (std::strcmp(argv[i], "--device-id") == 0) {
                options.device_id = option_value(argc, argv, i, "--device-id");
            } else if (std::strcmp(argv[i], "--token") == 0) {
                options.token = option_value(argc, argv, i, "--token");
            }
        }
        return run_fixture(options);
    }

    print_usage();
    return 2;
}
