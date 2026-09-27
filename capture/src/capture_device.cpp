#include "radar/capture_device.hpp"

namespace radar {

CaptureDevice::~CaptureDevice()
{
    stop();
    if (context_ready_) {
        ma_context_uninit(&context_);
        context_ready_ = false;
    }
}

void CaptureDevice::data_callback(ma_device* device, void* /*output*/, const void* input,
    ma_uint32 frame_count)
{
    auto* self = static_cast<CaptureDevice*>(device->pUserData);
    if (self != nullptr) {
        self->on_frames(static_cast<const float*>(input), frame_count);
    }
}

void CaptureDevice::on_frames(const float* input, std::uint32_t frame_count) noexcept
{
    if (ring_ == nullptr || frame_count == 0) {
        return;
    }
    if (input == nullptr) {
        dropped_frames_.fetch_add(frame_count, std::memory_order_relaxed);
        discontinuity_.store(true, std::memory_order_release);
        ring_->notify();
        return;
    }
    const std::size_t written = ring_->write(input, frame_count);
    if (written < frame_count) {
        // Producer overflow: drop the unwritten frames, never the consumer's.
        dropped_frames_.fetch_add(static_cast<std::uint64_t>(frame_count - written),
            std::memory_order_relaxed);
        discontinuity_.store(true, std::memory_order_release);
    }
    frames_captured_.fetch_add(static_cast<std::uint64_t>(written), std::memory_order_relaxed);
    ring_->notify();
}

bool CaptureDevice::start(SpscRing& ring, std::string* error, bool null_backend)
{
    if (running_) {
        return true;
    }
    if (!context_ready_) {
        ma_backend backends[]          = { ma_backend_null };
        const ma_result context_result = null_backend ? ma_context_init(backends, 1, nullptr, &context_)
                                                      : ma_context_init(nullptr, 0, nullptr, &context_);
        if (context_result != MA_SUCCESS) {
            if (error != nullptr) {
                *error = "ma_context_init failed";
            }
            return false;
        }
        context_ready_ = true;
    }

    ma_device_config config         = ma_device_config_init(ma_device_type_capture);
    config.capture.format           = ma_format_f32;
    config.capture.channels         = 1;
    config.sampleRate               = 0; // native device rate; worker resamples to 16 kHz
    config.periodSizeInMilliseconds = 10;
    config.dataCallback             = &CaptureDevice::data_callback;
    config.pUserData                = this;

    const ma_result init_result = ma_device_init(&context_, &config, &device_);
    if (init_result != MA_SUCCESS) {
        if (error != nullptr) {
            *error = ma_result_description(init_result);
        }
        return false;
    }
    device_ready_ = true;
    native_rate_  = device_.sampleRate;
    ring_         = &ring;

    const ma_result start_result = ma_device_start(&device_);
    if (start_result != MA_SUCCESS) {
        if (error != nullptr) {
            *error = ma_result_description(start_result);
        }
        ma_device_uninit(&device_);
        device_ready_ = false;
        ring_         = nullptr;
        return false;
    }
    running_ = true;
    discontinuity_.store(false, std::memory_order_release);
    frames_captured_.store(0, std::memory_order_relaxed);
    return true;
}

void CaptureDevice::stop()
{
    if (!device_ready_) {
        running_ = false;
        return;
    }
    if (running_) {
        ma_device_stop(&device_); // blocks until the callback has returned
        running_ = false;
    }
    ma_device_uninit(&device_);
    device_ready_ = false;
    ring_         = nullptr;
}

std::string CaptureDevice::device_name() const
{
    if (!device_ready_) {
        return { };
    }
    return device_.capture.name;
}

} // namespace radar
