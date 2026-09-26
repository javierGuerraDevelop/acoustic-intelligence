// Temporary smoke-test entry point (replaced by the full supervisor CLI in a
// later commit). Captures from the default input device, prints native format
// and one-second RMS values, and exits after --seconds.
#include <miniaudio.h>

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

namespace {

struct SmokeContext {
    std::atomic<uint64_t> frames{0};
    std::atomic<uint64_t> dropped{0};
    float peak{0.0f};
};

void data_callback(ma_device* device, void* /*output*/, const void* input, ma_uint32 frame_count) {
    auto* ctx = static_cast<SmokeContext*>(device->pUserData);
    if (input == nullptr) {
        ctx->dropped.fetch_add(frame_count, std::memory_order_relaxed);
        return;
    }
    const auto* samples = static_cast<const float*>(input);
    float local_peak = ctx->peak;
    for (ma_uint32 i = 0; i < frame_count; ++i) {
        const float magnitude = std::fabs(samples[i]);
        if (magnitude > local_peak) {
            local_peak = magnitude;
        }
    }
    ctx->peak = local_peak;
    ctx->frames.fetch_add(frame_count, std::memory_order_relaxed);
}

void list_devices() {
    ma_context context;
    if (ma_context_init(nullptr, 0, nullptr, &context) != MA_SUCCESS) {
        std::fprintf(stderr, "ma_context_init failed\n");
        return;
    }
    ma_device_info* playback = nullptr;
    ma_uint32 playback_count = 0;
    ma_device_info* capture = nullptr;
    ma_uint32 capture_count = 0;
    if (ma_context_get_devices(&context, &playback, &playback_count, &capture, &capture_count) ==
        MA_SUCCESS) {
        std::printf("capture devices: %u\n", capture_count);
        for (ma_uint32 i = 0; i < capture_count; ++i) {
            std::printf("  [%u] %s%s\n", i, capture[i].name,
                        capture[i].isDefault ? " (default)" : "");
        }
    }
    ma_context_uninit(&context);
}

}  // namespace

int main(int argc, char** argv) {
    int seconds = 3;
    bool null_backend = false;
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--list") == 0) {
            list_devices();
            return 0;
        }
        if (std::strcmp(argv[i], "--null-backend") == 0) {
            null_backend = true;
        }
        if (std::strcmp(argv[i], "--seconds") == 0 && i + 1 < argc) {
            seconds = std::atoi(argv[++i]);
        }
    }

    ma_context context;
    ma_backend backends[] = {ma_backend_null};
    if (ma_context_init(null_backend ? backends : nullptr, null_backend ? 1 : 0, nullptr, &context) !=
        MA_SUCCESS) {
        std::fprintf(stderr, "ma_context_init failed\n");
        return 1;
    }

    ma_device_config config = ma_device_config_init(ma_device_type_capture);
    config.capture.format = ma_format_f32;
    config.capture.channels = 1;
    config.sampleRate = 0;  // native rate
    config.dataCallback = data_callback;
    config.periodSizeInMilliseconds = 10;

    SmokeContext ctx;
    config.pUserData = &ctx;

    ma_device device;
    if (ma_device_init(&context, &config, &device) != MA_SUCCESS) {
        std::fprintf(stderr, "ma_device_init failed (no microphone or permission denied)\n");
        ma_context_uninit(&context);
        return 2;
    }

    std::printf("device: %s\n", device.capture.name);
    std::printf("native_rate_hz: %u\n", device.sampleRate);
    std::printf("channels: %u\n", device.capture.channels);
    std::printf("period_frames: %u\n", device.capture.internalPeriodSizeInFrames);

    if (ma_device_start(&device) != MA_SUCCESS) {
        std::fprintf(stderr, "ma_device_start failed\n");
        ma_device_uninit(&device);
        ma_context_uninit(&context);
        return 3;
    }

    uint64_t previous_frames = 0;
    for (int elapsed = 1; elapsed <= seconds; ++elapsed) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
        const uint64_t frames = ctx.frames.load(std::memory_order_relaxed);
        const uint64_t delta = frames - previous_frames;
        previous_frames = frames;
        const double measured_rate = static_cast<double>(delta);
        const double peak = static_cast<double>(ctx.peak);
        std::printf("t=%ds frames_delta=%llu measured_rate=%.1f Hz peak=%.3f dropped=%llu\n", elapsed,
                    static_cast<unsigned long long>(delta), measured_rate, peak,
                    static_cast<unsigned long long>(ctx.dropped.load(std::memory_order_relaxed)));
    }

    ma_device_stop(&device);
    ma_device_uninit(&device);
    ma_context_uninit(&context);

    const uint64_t total = ctx.frames.load(std::memory_order_relaxed);
    std::printf("total_frames=%llu dropped=%llu\n", static_cast<unsigned long long>(total),
                static_cast<unsigned long long>(ctx.dropped.load(std::memory_order_relaxed)));
    return 0;
}
