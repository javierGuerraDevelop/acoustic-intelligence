#pragma once

#include <atomic>
#include <cstdint>
#include <string>

#include <miniaudio.h>

#include "radar/spsc_ring.hpp"

namespace radar {

// Owns the miniaudio capture device. The callback only copies f32 mono frames
// into the ring and updates atomics; start/stop happen on the supervisor
// thread, and ma_device_stop() blocks until the callback has finished.
class CaptureDevice {
public:
    CaptureDevice() = default;
    ~CaptureDevice();

    CaptureDevice(const CaptureDevice&)            = delete;
    CaptureDevice& operator=(const CaptureDevice&) = delete;

    // Initializes the default capture device at its native rate and starts it.
    // Returns false with a short diagnostic on missing/denied devices.
    // null_backend selects miniaudio's silent null device for headless tests;
    // live demo runs always use the real default device.
    bool start(SpscRing& ring, std::string* error, bool null_backend = false);

    // Stops and uninitializes the device; safe to call when already stopped.
    void stop();

    bool running() const noexcept { return running_; }
    std::uint32_t native_rate() const noexcept { return native_rate_; }
    std::string device_name() const;
    std::uint64_t frames_captured() const noexcept
    {
        return frames_captured_.load(std::memory_order_relaxed);
    }
    std::uint64_t dropped_frames() const noexcept
    {
        return dropped_frames_.load(std::memory_order_relaxed);
    }

    // True when the ring overflowed or the backend delivered no input since
    // the last call. The processing worker rebuilds the stream on this signal.
    bool consume_discontinuity() noexcept
    {
        return discontinuity_.exchange(false, std::memory_order_acq_rel);
    }

private:
    static void data_callback(ma_device* device, void* output, const void* input,
        ma_uint32 frame_count);
    void on_frames(const float* input, std::uint32_t frame_count) noexcept;

    ma_context context_ { };
    ma_device device_ { };
    bool context_ready_        = false;
    bool device_ready_         = false;
    bool running_              = false;
    SpscRing* ring_            = nullptr;
    std::uint32_t native_rate_ = 0;
    std::atomic<std::uint64_t> frames_captured_ { 0 };
    std::atomic<std::uint64_t> dropped_frames_ { 0 };
    std::atomic<bool> discontinuity_ { false };
};

} // namespace radar
