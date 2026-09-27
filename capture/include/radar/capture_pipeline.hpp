#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include "radar/chunk_queue.hpp"
#include "radar/chunker.hpp"
#include "radar/spsc_ring.hpp"

namespace radar {

class StreamingResampler;

// Processing worker: drains the SPSC ring, resamples to 16 kHz with a
// persistent converter, assembles one-second chunks and pushes them to the
// bounded sender queue. Owns stream identity: pause/resume and discontinuities
// rotate the UUID and restart chunk sequence at zero.
class CapturePipeline {
public:
    using DiscontinuityFn = std::function<bool()>;
    using DroppedFramesFn = std::function<std::uint64_t()>;

    CapturePipeline(SpscRing& ring, ChunkQueue& queue, DiscontinuityFn consume_discontinuity,
        DroppedFramesFn dropped_frames);
    ~CapturePipeline();

    CapturePipeline(const CapturePipeline&)            = delete;
    CapturePipeline& operator=(const CapturePipeline&) = delete;

    void start();
    void stop();

    // Called by the supervisor after the device starts. The worker rebuilds
    // its converter for native_rate and anchors the stream clock at start_utc.
    // Returns the freshly generated stream UUID, which becomes visible to
    // heartbeats immediately.
    std::string begin_stream(std::uint32_t native_rate,
        std::chrono::system_clock::time_point start_utc);

    // Called by the supervisor after the device stops: the worker discards
    // queued frames, clears the partial chunk and marks the stream inactive.
    void end_stream();

    bool stream_active() const noexcept { return stream_active_.load(std::memory_order_acquire); }
    std::string stream_id() const;
    std::uint64_t chunks_emitted() const noexcept
    {
        return chunks_emitted_.load(std::memory_order_relaxed);
    }
    std::uint64_t stream_rotations() const noexcept
    {
        return stream_rotations_.load(std::memory_order_relaxed);
    }

private:
    struct PendingBegin {
        std::uint32_t native_rate = 0;
        std::chrono::system_clock::time_point start_utc { };
        std::string stream_id;
    };

    void run();
    void apply_begin(const PendingBegin& begin);
    void rotate_stream(const char* reason);
    void drain_ring() noexcept;

    SpscRing& ring_;
    ChunkQueue& queue_;
    DiscontinuityFn consume_discontinuity_;
    DroppedFramesFn dropped_frames_;

    std::unique_ptr<StreamingResampler> resampler_;
    Chunker chunker_;
    AudioChunk current_;
    std::vector<float> stage_;
    std::vector<float> converted_;

    mutable std::mutex state_mutex_;
    std::string stream_id_;
    std::optional<PendingBegin> pending_begin_;
    bool pending_end_ = false;

    std::atomic<bool> stop_ { false };
    std::atomic<bool> stream_active_ { false };
    std::atomic<std::uint64_t> chunks_emitted_ { 0 };
    std::atomic<std::uint64_t> stream_rotations_ { 0 };
    std::thread thread_;
};

} // namespace radar
