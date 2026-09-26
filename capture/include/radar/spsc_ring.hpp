#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace radar {

// Preallocated single-producer/single-consumer ring of mono float frames.
//
// Ownership: the producer owns write_index_ and only reads read_index_; the
// consumer owns read_index_ and only reads write_index_. Indexes are monotonic
// 64-bit counts masked to the power-of-two capacity, so wraparound is handled
// by unsigned arithmetic. Publication uses release stores and acquire loads:
// data written before write_index_ is visible to a consumer that observes the
// new write_index_.
//
// Overflow policy: write() drops the new frames (it never moves the consumer
// index) and returns the number written; the caller counts the gap and asks
// for a new stream. reset() is only valid when neither side is active.
class SpscRing {
public:
    explicit SpscRing(std::size_t capacity_frames);

    SpscRing(const SpscRing&) = delete;
    SpscRing& operator=(const SpscRing&) = delete;

    std::size_t capacity() const noexcept { return capacity_; }

    // Producer side. Returns how many frames were written.
    std::size_t write(const float* frames, std::size_t count) noexcept;

    // Consumer side. Returns how many frames were read.
    std::size_t read(float* out, std::size_t count) noexcept;

    // Producer-side estimate of space available without touching read_index_.
    std::size_t writable() const noexcept;

    // Either side; reads both indices.
    std::size_t readable() const noexcept;

    // Not thread-safe: call only while producer and consumer are stopped.
    void reset() noexcept;

    // Wake-up signal for a sleeping consumer. The producer calls notify()
    // (lock-free, safe from the audio callback); the consumer snapshots
    // signal_value() and passes it to wait_for_data(). A notification racing
    // between the snapshot and the wait is not lost because wait observes the
    // changed value and returns immediately.
    void notify() noexcept;
    std::uint32_t signal_value() const noexcept;
    void wait_for_data(std::uint32_t seen) const;

private:
    static std::size_t round_up_power_of_two(std::size_t value);

    std::vector<float> buffer_;
    std::size_t capacity_ = 0;
    std::size_t mask_ = 0;
    alignas(64) std::atomic<std::uint64_t> write_index_{0};
    alignas(64) std::atomic<std::uint64_t> read_index_{0};
    alignas(64) mutable std::atomic<std::uint32_t> signal_{0};
};

}  // namespace radar
