#include "radar/resampler.hpp"

#include <algorithm>
#include <stdexcept>

namespace radar {

StreamingResampler::StreamingResampler(std::uint32_t input_rate, std::uint32_t output_rate,
    std::uint32_t channels)
    : input_rate_(input_rate)
    , output_rate_(output_rate)
    , channels_(channels)
{
    if (input_rate_ == 0 || output_rate_ == 0 || channels_ == 0) {
        throw std::invalid_argument("resampler rates and channels must be positive");
    }
    ma_resampler_config config = ma_resampler_config_init(ma_format_f32, channels_, input_rate_,
        output_rate_, ma_resample_algorithm_linear);
    if (ma_resampler_init(&config, nullptr, &resampler_) != MA_SUCCESS) {
        throw std::runtime_error("ma_resampler_init failed");
    }
    initialized_ = true;
    scratch_.resize(4096);
}

StreamingResampler::~StreamingResampler()
{
    if (initialized_) {
        ma_resampler_uninit(&resampler_, nullptr);
    }
}

void StreamingResampler::reset()
{
    if (initialized_) {
        ma_resampler_reset(&resampler_);
    }
}

bool StreamingResampler::process(const float* input, std::size_t input_frames,
    std::vector<float>& output)
{
    if (!initialized_ || input == nullptr || input_frames == 0) {
        return initialized_;
    }

    ma_uint64 remaining = static_cast<ma_uint64>(input_frames);
    const float* in_ptr = input;
    while (remaining > 0) {
        ma_uint64 expected = 0;
        if (ma_resampler_get_expected_output_frame_count(&resampler_, remaining, &expected) !=
            MA_SUCCESS) {
            return false;
        }
        if (expected + 64 > scratch_.size()) {
            scratch_.resize(static_cast<std::size_t>(expected) + 64);
        }

        ma_uint64 out_count = static_cast<ma_uint64>(scratch_.size());
        ma_uint64 in_count = remaining;
        if (ma_resampler_process_pcm_frames(&resampler_, in_ptr, &in_count, scratch_.data(),
                                            &out_count) != MA_SUCCESS) {
            return false;
        }
        if (out_count > 0) {
            output.insert(output.end(), scratch_.begin(),
                          scratch_.begin() + static_cast<std::ptrdiff_t>(out_count));
        }
        in_ptr += in_count;
        remaining -= in_count;
        if (in_count == 0 && out_count == 0) {
            return false;  // no forward progress; avoid an infinite loop
        }
    }
    return true;
}

std::uint64_t StreamingResampler::output_latency_frames() const {
    if (!initialized_) {
        return 0;
    }
    return ma_resampler_get_output_latency(&resampler_);
}

}  // namespace radar
