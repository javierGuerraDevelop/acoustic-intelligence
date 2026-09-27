#pragma once

#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <deque>
#include <memory>
#include <mutex>

#include "radar/chunker.hpp"

namespace radar {

// Bounded worker->sender queue. This queue may synchronize (mutex/condvar)
// because it is never touched by the audio callback. When full, push() drops
// the oldest pending chunk and counts it; audio processing is never blocked by
// a slow receiver.
class ChunkQueue {
public:
    explicit ChunkQueue(std::size_t max_chunks);

    ChunkQueue(const ChunkQueue&)            = delete;
    ChunkQueue& operator=(const ChunkQueue&) = delete;

    // Producer (processing worker). Drops and counts the oldest chunk when full.
    void push(std::shared_ptr<const AudioChunk> chunk);

    // Consumer (sender worker). Returns nullptr on timeout or after close.
    std::shared_ptr<const AudioChunk> pop(std::chrono::milliseconds timeout);

    // Wakes consumers; further pushes are ignored.
    void close();

    void clear();

    std::size_t size() const;
    std::size_t dropped() const;

private:
    mutable std::mutex mutex_;
    std::condition_variable ready_;
    std::deque<std::shared_ptr<const AudioChunk>> queue_;
    std::size_t max_chunks_ = 1;
    std::size_t dropped_    = 0;
    bool closed_            = false;
};

} // namespace radar
