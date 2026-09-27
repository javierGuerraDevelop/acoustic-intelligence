#include "radar/chunker.hpp"

#include <algorithm>
#include <cmath>

namespace radar {

namespace {
    constexpr double kMinRms = 1e-6; // floor for log; ~-120 dBFS
}

std::int16_t encode_s16(float sample) noexcept
{
    if (!std::isfinite(sample)) {
        return 0;
    }
    const float clamped = std::clamp(sample, -1.0f, 1.0f);
    const long scaled   = std::lrint(static_cast<double>(clamped) * 32767.0);
    return static_cast<std::int16_t>(std::clamp<long>(scaled, -32767, 32767));
}

Chunker::Chunker(std::uint32_t output_rate)
    : output_rate_(output_rate)
{
    if (output_rate_ == 0) {
        output_rate_ = kWireSampleRateHz;
    }
}

void Chunker::begin_stream(std::chrono::system_clock::time_point stream_start_utc)
{
    stream_start_   = stream_start_utc;
    stream_started_ = true;
    fill_           = 0;
    chunk_seq_      = 0;
    sum_squares_    = 0.0;
}

void Chunker::clear()
{
    fill_        = 0;
    sum_squares_ = 0.0;
}

bool Chunker::push(const float* frames, std::size_t frame_count,
    std::uint64_t dropped_frames_total, AudioChunk& out)
{
    if (frames == nullptr || frame_count == 0 || !stream_started_) {
        return false;
    }
    const std::size_t count  = std::min(frame_count, frames_until_boundary());
    const std::size_t offset = fill_ * kWireBytesPerSample;
    for (std::size_t i = 0; i < count; ++i) {
        const float sample = frames[i];
        sum_squares_ += static_cast<double>(sample) * static_cast<double>(sample);
        const std::int16_t encoded                    = encode_s16(sample);
        out.pcm[offset + i * kWireBytesPerSample]     = static_cast<std::uint8_t>(encoded & 0xFF);
        out.pcm[offset + i * kWireBytesPerSample + 1] = static_cast<std::uint8_t>((encoded >> 8) & 0xFF);
    }
    fill_ += count;
    if (fill_ < kWireChunkFrames) {
        return false;
    }

    const double mean_square = sum_squares_ / static_cast<double>(kWireChunkFrames);
    const double rms         = std::sqrt(std::max(mean_square, 0.0));
    const float dbfs         = rms <= kMinRms ? kRmsFloorDbfs : static_cast<float>(20.0 * std::log10(rms));

    out.seq                  = chunk_seq_;
    out.start_sample         = chunk_seq_ * kWireChunkFrames;
    out.captured_at          = stream_start_ + std::chrono::milliseconds(static_cast<std::int64_t>(out.start_sample) * 1000 / static_cast<std::int64_t>(output_rate_));
    out.rms_dbfs             = std::max(dbfs, kRmsFloorDbfs);
    out.dropped_frames_total = dropped_frames_total;

    ++chunk_seq_;
    fill_        = 0;
    sum_squares_ = 0.0;
    return true;
}

} // namespace radar
