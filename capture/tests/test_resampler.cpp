#include "radar/resampler.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <vector>

#include "test_util.hpp"

namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kToneHz = 1000.0;
constexpr std::uint32_t kOutRate = 16000;

struct ToneResult {
    std::size_t frames = 0;
    double frequency_hz = 0.0;
};

// Feeds `seconds` of a 1 kHz tone in 10 ms blocks and estimates the output
// frequency by counting positive zero crossings in the middle section.
ToneResult run_tone(std::uint32_t in_rate, double seconds) {
    radar::StreamingResampler resampler(in_rate, kOutRate, 1);
    std::vector<float> output;
    output.reserve(static_cast<std::size_t>(seconds * kOutRate) + 1024);

    const std::size_t total = static_cast<std::size_t>(in_rate * seconds);
    const std::size_t block = static_cast<std::size_t>(in_rate / 100);
    std::vector<float> input(block);
    for (std::size_t position = 0; position < total; position += block) {
        const std::size_t count = std::min(block, total - position);
        for (std::size_t i = 0; i < count; ++i) {
            input[i] = static_cast<float>(
                std::sin(2.0 * kPi * kToneHz *
                         static_cast<double>(position + i) / static_cast<double>(in_rate)));
        }
        RADAR_CHECK(resampler.process(input.data(), count, output));
    }

    ToneResult result;
    result.frames = output.size();
    const std::size_t skip = output.size() / 4;
    const std::size_t end = output.size() - skip;
    std::size_t crossings = 0;
    for (std::size_t i = skip + 1; i < end; ++i) {
        if (output[i - 1] < 0.0f && output[i] >= 0.0f) {
            ++crossings;
        }
    }
    const double duration = static_cast<double>(end - skip) / kOutRate;
    result.frequency_hz = duration > 0.0 ? static_cast<double>(crossings) / duration : 0.0;
    return result;
}

void preserves_duration_and_frequency_at_48k() {
    const ToneResult result = run_tone(48000, 3.0);
    RADAR_CHECK_NEAR(result.frames, 48000, 480);  // within 1%
    RADAR_CHECK_NEAR(result.frequency_hz, kToneHz, 20.0);
}

void preserves_duration_and_frequency_at_44k1() {
    const ToneResult result = run_tone(44100, 2.0);
    RADAR_CHECK_NEAR(result.frames, 32000, 480);
    RADAR_CHECK_NEAR(result.frequency_hz, kToneHz, 20.0);
}

void passthrough_rate_produces_same_count() {
    radar::StreamingResampler resampler(16000, 16000, 1);
    std::vector<float> input(1600, 0.25f);
    std::vector<float> output;
    RADAR_CHECK(resampler.process(input.data(), input.size(), output));
    // Latency delays a few frames, so allow a small deficit.
    RADAR_CHECK(output.size() >= 1500);
    RADAR_CHECK(output.size() <= 1700);
}

void reset_clears_state() {
    radar::StreamingResampler resampler(48000, 16000, 1);
    std::vector<float> input(4800, 1.0f);
    std::vector<float> output;
    RADAR_CHECK(resampler.process(input.data(), input.size(), output));
    RADAR_CHECK(!output.empty());

    resampler.reset();
    output.clear();
    std::vector<float> silence(4800, 0.0f);
    RADAR_CHECK(resampler.process(silence.data(), silence.size(), output));
    for (const float sample : output) {
        RADAR_CHECK_NEAR(sample, 0.0f, 1e-6f);
    }
}

void run_tests() {
    preserves_duration_and_frequency_at_48k();
    preserves_duration_and_frequency_at_44k1();
    passthrough_rate_produces_same_count();
    reset_clears_state();
}

}  // namespace

RADAR_TEST_MAIN()
