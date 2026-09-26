#pragma once

#include <cstdint>
#include <vector>

#include <miniaudio.h>

namespace radar {

// Persistent streaming miniaudio resampler. One instance per capture stream;
// reset() when the stream is rebuilt after a discontinuity. Worker-thread only:
// construction and processing may allocate, the audio callback never uses it.
class StreamingResampler {
public:
    StreamingResampler(std::uint32_t input_rate, std::uint32_t output_rate,
                       std::uint32_t channels = 1);
    ~StreamingResampler();

    StreamingResampler(const StreamingResampler&) = delete;
    StreamingResampler& operator=(const StreamingResampler&) = delete;

    // Restarts the conversion state for a new contiguous stream. The plan
    // warns against resetting per callback; this is only for stream rebuilds.
    void reset();

    // Converts exactly input_frames frames, appending output-rate frames to
    // output. Returns false on converter failure (caller starts a new stream).
    bool process(const float* input, std::size_t input_frames, std::vector<float>& output);

    std::uint32_t input_rate() const noexcept { return input_rate_; }
    std::uint32_t output_rate() const noexcept { return output_rate_; }

    // Resampler delay in output-rate frames (diagnostics only).
    std::uint64_t output_latency_frames() const;

private:
    ma_resampler resampler_{};
    bool initialized_ = false;
    std::uint32_t input_rate_ = 0;
    std::uint32_t output_rate_ = 0;
    std::uint32_t channels_ = 0;
    std::vector<float> scratch_;
};

}  // namespace radar
