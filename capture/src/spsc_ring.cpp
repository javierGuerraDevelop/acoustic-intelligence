#include "radar/spsc_ring.hpp"

#include <algorithm>

namespace radar {

SpscRing::SpscRing(std::size_t capacity_frames)
    : capacity_(round_up_power_of_two(std::max<std::size_t>(capacity_frames, 2))),
      mask_(capacity_ - 1) {
    buffer_.resize(capacity_);
}

std::size_t SpscRing::round_up_power_of_two(std::size_t value) {
    std::size_t result = 1;
    while (result < value) {
        result <<= 1;
    }
    return result;
}

std::size_t SpscRing::write(const float* frames, std::size_t count) noexcept {
    if (frames == nullptr || count == 0) {
        return 0;
    }
    const std::uint64_t write = write_index_.load(std::memory_order_relaxed);
    const std::uint64_t read = read_index_.load(std::memory_order_acquire);
    const std::uint64_t used = write - read;
    const auto free = static_cast<std::uint64_t>(capacity_) - used;
    const auto accepted = static_cast<std::size_t>(std::min<std::uint64_t>(count, free));

    for (std::size_t i = 0; i < accepted; ++i) {
        buffer_[static_cast<std::size_t>(write + i) & mask_] = frames[i];
    }
    // Release: published frames are visible to a consumer that acquires.
    write_index_.store(write + accepted, std::memory_order_release);
    return accepted;
}

std::size_t SpscRing::read(float* out, std::size_t count) noexcept {
    if (out == nullptr || count == 0) {
        return 0;
    }
    const std::uint64_t read = read_index_.load(std::memory_order_relaxed);
    const std::uint64_t write = write_index_.load(std::memory_order_acquire);
    const auto available = static_cast<std::uint64_t>(write - read);
    const auto accepted = static_cast<std::size_t>(std::min<std::uint64_t>(count, available));

    for (std::size_t i = 0; i < accepted; ++i) {
        out[i] = buffer_[static_cast<std::size_t>(read + i) & mask_];
    }
    // Release: consumed slots are visible as free to the producer.
    read_index_.store(read + accepted, std::memory_order_release);
    return accepted;
}

std::size_t SpscRing::writable() const noexcept {
    const std::uint64_t write = write_index_.load(std::memory_order_acquire);
    const std::uint64_t read = read_index_.load(std::memory_order_acquire);
    return capacity_ - static_cast<std::size_t>(write - read);
}

std::size_t SpscRing::readable() const noexcept {
    const std::uint64_t write = write_index_.load(std::memory_order_acquire);
    const std::uint64_t read = read_index_.load(std::memory_order_acquire);
    return static_cast<std::size_t>(write - read);
}

void SpscRing::reset() noexcept {
    read_index_.store(0, std::memory_order_relaxed);
    write_index_.store(0, std::memory_order_relaxed);
}

void SpscRing::notify() noexcept {
    signal_.fetch_add(1, std::memory_order_release);
    signal_.notify_all();
}

std::uint32_t SpscRing::signal_value() const noexcept {
    return signal_.load(std::memory_order_acquire);
}

void SpscRing::wait_for_data(std::uint32_t seen) const {
    signal_.wait(seen, std::memory_order_acquire);
}

}  // namespace radar
