#include "radar/chunker.hpp"

#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

#include "test_util.hpp"

namespace {

constexpr float kHalf = 0.5f;

std::int16_t decode_le(const std::uint8_t* pcm, std::size_t index) {
    const std::uint16_t raw = static_cast<std::uint16_t>(pcm[index * 2]) |
                              static_cast<std::uint16_t>(pcm[index * 2 + 1] << 8);
    return static_cast<std::int16_t>(raw);
}

void encodes_sign_and_endianness() {
    RADAR_CHECK(radar::encode_s16(0.0f) == 0);
    RADAR_CHECK(radar::encode_s16(2.0f) == 32767);
    RADAR_CHECK(radar::encode_s16(-2.0f) == -32767);
    RADAR_CHECK(radar::encode_s16(std::numeric_limits<float>::quiet_NaN()) == 0);

    const std::int16_t positive = radar::encode_s16(kHalf);
    RADAR_CHECK(positive == 16383 || positive == 16384);
    const std::int16_t negative = radar::encode_s16(-kHalf);
    RADAR_CHECK(negative == -16383 || negative == -16384);
}

void assembles_three_chunks_with_correct_metadata() {
    const auto stream_start =
        std::chrono::system_clock::time_point{} + std::chrono::seconds(1790380800);
    radar::Chunker chunker;
    chunker.begin_stream(stream_start);

    radar::AudioChunk chunk;

    std::vector<float> positive(radar::kWireChunkFrames, kHalf);
    std::vector<float> negative(radar::kWireChunkFrames, -kHalf);
    std::vector<float> silence(radar::kWireChunkFrames, 0.0f);

    // A partial push must not complete a chunk.
    RADAR_CHECK(!chunker.push(positive.data(), 100, 0, chunk));
    RADAR_CHECK(chunker.frames_until_boundary() == radar::kWireChunkFrames - 100);
    RADAR_CHECK(chunker.push(positive.data(), radar::kWireChunkFrames - 100, 0, chunk));
    RADAR_CHECK(chunk.seq == 0);
    RADAR_CHECK(chunk.start_sample == 0);
    RADAR_CHECK(chunk.captured_at == stream_start);
    RADAR_CHECK_NEAR(chunk.rms_dbfs, -6.0206, 0.05);
    const std::int16_t first = decode_le(chunk.pcm.data(), 0);
    RADAR_CHECK(first == 16383 || first == 16384);

    RADAR_CHECK(chunker.push(negative.data(), radar::kWireChunkFrames, 3, chunk));
    RADAR_CHECK(chunk.seq == 1);
    RADAR_CHECK(chunk.start_sample == 16000);
    RADAR_CHECK(chunk.dropped_frames_total == 3);
    const std::int16_t second = decode_le(chunk.pcm.data(), 0);
    RADAR_CHECK(second == -16383 || second == -16384);
    RADAR_CHECK(chunk.pcm[1] == 0xC0);  // high byte of a negative sample, little-endian

    RADAR_CHECK(chunker.push(silence.data(), radar::kWireChunkFrames, 3, chunk));
    RADAR_CHECK(chunk.seq == 2);
    RADAR_CHECK(chunk.start_sample == 32000);
    RADAR_CHECK(chunk.rms_dbfs == radar::kRmsFloorDbfs);
    RADAR_CHECK(chunk.captured_at - stream_start == std::chrono::seconds(2));
    RADAR_CHECK(chunker.completed_chunks() == 3);
}

void payload_is_exactly_wire_size() {
    radar::AudioChunk chunk;
    RADAR_CHECK(chunk.pcm.size() == 32000);
    RADAR_CHECK(radar::kWireChunkBytes == 32000);
    RADAR_CHECK(radar::kWireChunkFrames == 16000);
}

void push_before_begin_stream_is_ignored() {
    radar::Chunker chunker;
    radar::AudioChunk chunk;
    std::vector<float> frames(16000, 0.0f);
    RADAR_CHECK(!chunker.push(frames.data(), frames.size(), 0, chunk));
    RADAR_CHECK(chunker.completed_chunks() == 0);
}

void clear_discards_partial_chunk() {
    radar::Chunker chunker;
    chunker.begin_stream(std::chrono::system_clock::time_point{});
    radar::AudioChunk chunk;
    std::vector<float> frames(8000, 0.0f);
    RADAR_CHECK(!chunker.push(frames.data(), frames.size(), 0, chunk));
    chunker.clear();
    RADAR_CHECK(chunker.frames_until_boundary() == radar::kWireChunkFrames);
}

void run_tests() {
    encodes_sign_and_endianness();
    assembles_three_chunks_with_correct_metadata();
    payload_is_exactly_wire_size();
    push_before_begin_stream_is_ignored();
    clear_discards_partial_chunk();
}

}  // namespace

RADAR_TEST_MAIN()
