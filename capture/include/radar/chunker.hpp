#pragma once

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>

#include "radar/audio_format.hpp"

namespace radar {

// One complete one-second wire chunk. The payload is inline so queueing never
// allocates after construction; total memory for one chunk is exactly
// kWireChunkBytes of PCM plus bookkeeping.
struct AudioChunk {
    std::uint64_t seq = 0;
    std::uint64_t start_sample = 0;  // output-rate samples since stream start
    std::chrono::system_clock::time_point captured_at{};  // first sample, UTC
    float rms_dbfs = kRmsFloorDbfs;
    std::uint64_t dropped_frames_total = 0;
    // Canonical 36-character UUID text plus terminator; filled by the pipeline
    // when the chunk is finalized.
    std::array<char, 37> stream_id{};
    std::array<std::uint8_t, kWireChunkBytes> pcm{};
};

// Assembles wire-rate frames into one-second s16le chunks. Worker-thread only.
// push() copies at most frames_until_boundary() frames, so a caller that caps
// its read at that value never loses audio and completes at most one chunk.
class Chunker {
public:
    explicit Chunker(std::uint32_t output_rate = kWireSampleRateHz);

    // Starts a new contiguous stream: resets sequence and RMS accumulation and
    // fixes the UTC time of the stream's first sample.
    void begin_stream(std::chrono::system_clock::time_point stream_start_utc);

    // Discards a partial chunk without changing the stream clock (stop/error).
    void clear();

    // Returns true when `out` received a completed chunk. `out` must be the
    // same object across successive calls until a chunk completes; frames
    // accumulate inside its inline PCM buffer. `frames` is clamped to
    // frames_until_boundary(); callers should size reads accordingly.
    bool push(const float* frames, std::size_t frame_count, std::uint64_t dropped_frames_total,
              AudioChunk& out);

    std::size_t frames_until_boundary() const noexcept { return kWireChunkFrames - fill_; }
    std::uint64_t completed_chunks() const noexcept { return chunk_seq_; }

private:
    std::uint32_t output_rate_ = kWireSampleRateHz;
    std::size_t fill_ = 0;
    std::uint64_t chunk_seq_ = 0;
    double sum_squares_ = 0.0;
    std::chrono::system_clock::time_point stream_start_{};
    bool stream_started_ = false;
};

// Clamp to [-1, 1], scale by 32767 and round; NaN becomes silence.
std::int16_t encode_s16(float sample) noexcept;

}  // namespace radar
