#include "radar/capture_pipeline.hpp"

#include <algorithm>
#include <cstdio>
#include <iterator>

#include "radar/audio_format.hpp"
#include "radar/resampler.hpp"
#include "radar/uuid_util.hpp"

namespace radar {

namespace {
constexpr std::size_t kStageFrames = 4096;
constexpr std::size_t kConvertedReserve = kStageFrames * 4 + 64;
}  // namespace

CapturePipeline::CapturePipeline(SpscRing& ring, ChunkQueue& queue,
                                 DiscontinuityFn consume_discontinuity,
                                 DroppedFramesFn dropped_frames)
    : ring_(ring),
      queue_(queue),
      consume_discontinuity_(std::move(consume_discontinuity)),
      dropped_frames_(std::move(dropped_frames)),
      stage_(kStageFrames) {
    converted_.reserve(kConvertedReserve);
}

CapturePipeline::~CapturePipeline() {
    stop();
}

void CapturePipeline::start() {
    if (thread_.joinable()) {
        return;
    }
    stop_.store(false, std::memory_order_release);
    thread_ = std::thread([this] { run(); });
}

void CapturePipeline::stop() {
    stop_.store(true, std::memory_order_release);
    ring_.notify();
    if (thread_.joinable()) {
        thread_.join();
    }
}

std::string CapturePipeline::begin_stream(std::uint32_t native_rate,
                                          std::chrono::system_clock::time_point start_utc) {
    PendingBegin begin;
    begin.native_rate = native_rate;
    begin.start_utc = start_utc;
    begin.stream_id = make_uuid_v4();
    {
        std::lock_guard<std::mutex> lock(state_mutex_);
        pending_begin_ = begin;
        pending_end_ = false;
        stream_id_ = begin.stream_id;
    }
    ring_.notify();
    return begin.stream_id;
}

void CapturePipeline::end_stream() {
    {
        std::lock_guard<std::mutex> lock(state_mutex_);
        pending_begin_.reset();
        pending_end_ = true;
    }
    ring_.notify();
}

std::string CapturePipeline::stream_id() const {
    std::lock_guard<std::mutex> lock(state_mutex_);
    return stream_id_;
}

void CapturePipeline::drain_ring() noexcept {
    float discard[512];
    while (ring_.read(discard, std::size(discard)) > 0) {
    }
}

void CapturePipeline::apply_begin(const PendingBegin& begin) {
    if (!resampler_ || resampler_->input_rate() != begin.native_rate) {
        resampler_ = std::make_unique<StreamingResampler>(begin.native_rate, kWireSampleRateHz,
                                                          static_cast<std::uint32_t>(kWireChannels));
    } else {
        resampler_->reset();
    }
    chunker_.begin_stream(begin.start_utc);
    current_ = AudioChunk{};
    {
        std::lock_guard<std::mutex> lock(state_mutex_);
        stream_id_ = begin.stream_id;
    }
    stream_active_.store(true, std::memory_order_release);
}

void CapturePipeline::rotate_stream(const char* /*reason*/) {
    drain_ring();
    if (resampler_) {
        resampler_->reset();
    }
    const auto now = std::chrono::system_clock::now();
    chunker_.begin_stream(now);
    current_ = AudioChunk{};
    {
        std::lock_guard<std::mutex> lock(state_mutex_);
        stream_id_ = make_uuid_v4();
    }
    stream_rotations_.fetch_add(1, std::memory_order_relaxed);
}

void CapturePipeline::run() {
    std::uint32_t seen = ring_.signal_value();
    while (!stop_.load(std::memory_order_acquire)) {
        // Control requests are handled before audio so a paused stream never
        // processes frames from before the pause.
        bool end_requested = false;
        std::optional<PendingBegin> begin_requested;
        {
            std::lock_guard<std::mutex> lock(state_mutex_);
            if (pending_end_) {
                end_requested = true;
                pending_end_ = false;
            }
            if (pending_begin_) {
                begin_requested = pending_begin_;
                pending_begin_.reset();
            }
        }

        if (end_requested) {
            drain_ring();
            chunker_.clear();
            if (resampler_) {
                resampler_->reset();
            }
            current_ = AudioChunk{};
            stream_active_.store(false, std::memory_order_release);
        }
        if (begin_requested.has_value()) {
            apply_begin(*begin_requested);
        }
        if (!stream_active_.load(std::memory_order_acquire)) {
            ring_.wait_for_data(seen);
            seen = ring_.signal_value();
            continue;
        }
        if (consume_discontinuity_ && consume_discontinuity_()) {
            rotate_stream("discontinuity");
        }

        const std::size_t readable = ring_.readable();
        if (readable == 0) {
            ring_.wait_for_data(seen);
            seen = ring_.signal_value();
            continue;
        }

        const std::size_t want = std::min({readable, stage_.size(), chunker_.frames_until_boundary()});
        const std::size_t got = ring_.read(stage_.data(), want);
        if (got == 0) {
            continue;
        }

        converted_.clear();
        if (!resampler_ || !resampler_->process(stage_.data(), got, converted_)) {
            rotate_stream("resampler_failure");
            continue;
        }

        const std::uint64_t dropped = dropped_frames_ ? dropped_frames_() : 0;
        std::size_t offset = 0;
        while (offset < converted_.size()) {
            const std::size_t count =
                std::min(converted_.size() - offset, chunker_.frames_until_boundary());
            if (chunker_.push(converted_.data() + offset, count, dropped, current_)) {
                {
                    std::lock_guard<std::mutex> lock(state_mutex_);
                    std::snprintf(current_.stream_id.data(), current_.stream_id.size(), "%s",
                                  stream_id_.c_str());
                }
                queue_.push(std::make_shared<AudioChunk>(current_));
                chunks_emitted_.fetch_add(1, std::memory_order_relaxed);
                current_ = AudioChunk{};
            }
            offset += count;
        }
    }
}

}  // namespace radar
