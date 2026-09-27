#include "radar/chunk_queue.hpp"

#include <chrono>
#include <memory>

#include "test_util.hpp"

namespace {

std::shared_ptr<radar::AudioChunk> make_chunk(std::uint64_t seq) {
    auto chunk = std::make_shared<radar::AudioChunk>();
    chunk->seq = seq;
    return chunk;
}

void drops_oldest_when_full() {
    radar::ChunkQueue queue(2);
    queue.push(make_chunk(0));
    queue.push(make_chunk(1));
    queue.push(make_chunk(2));  // drops seq 0

    RADAR_CHECK(queue.size() == 2);
    RADAR_CHECK(queue.dropped() == 1);

    auto first = queue.pop(std::chrono::milliseconds(10));
    auto second = queue.pop(std::chrono::milliseconds(10));
    RADAR_CHECK(first != nullptr && first->seq == 1);
    RADAR_CHECK(second != nullptr && second->seq == 2);
    RADAR_CHECK(queue.pop(std::chrono::milliseconds(1)) == nullptr);
}

void pop_times_out_on_empty_queue() {
    radar::ChunkQueue queue(2);
    const auto start = std::chrono::steady_clock::now();
    RADAR_CHECK(queue.pop(std::chrono::milliseconds(20)) == nullptr);
    const auto elapsed = std::chrono::steady_clock::now() - start;
    RADAR_CHECK(elapsed >= std::chrono::milliseconds(15));
}

void close_wakes_consumer_and_blocks_push() {
    radar::ChunkQueue queue(2);
    queue.close();
    RADAR_CHECK(queue.pop(std::chrono::milliseconds(100)) == nullptr);
    queue.push(make_chunk(7));
    RADAR_CHECK(queue.size() == 0);
}

void clear_empties_pending_chunks() {
    radar::ChunkQueue queue(2);
    queue.push(make_chunk(0));
    queue.push(make_chunk(1));
    queue.clear();
    RADAR_CHECK(queue.size() == 0);
    RADAR_CHECK(queue.dropped() == 0);
}

void run_tests() {
    drops_oldest_when_full();
    pop_times_out_on_empty_queue();
    close_wakes_consumer_and_blocks_push();
    clear_empties_pending_chunks();
}

}  // namespace

RADAR_TEST_MAIN()
