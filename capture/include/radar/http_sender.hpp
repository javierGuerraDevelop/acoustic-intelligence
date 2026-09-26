#pragma once

#include <atomic>
#include <cstdint>
#include <string>
#include <thread>

#include "radar/chunk_queue.hpp"

namespace radar {

// One sender thread, one request in flight, keep-alive, bounded deadlines.
// Uses its own client socket; an uncertain response or error discards the
// chunk and advances (no audio retransmission).
class HttpSender {
public:
    struct Config {
        std::string host = "127.0.0.1";
        int port = 8000;
        std::string token;      // bearer token, empty disables the header
        std::string device_id;  // X-Device-Id
        std::string path = "/v1/audio/chunks";
    };

    struct Stats {
        std::atomic<std::uint64_t> sent{0};
        std::atomic<std::uint64_t> failed{0};
    };

    HttpSender(ChunkQueue& queue, Config config);
    ~HttpSender();

    HttpSender(const HttpSender&) = delete;
    HttpSender& operator=(const HttpSender&) = delete;

    void start();
    void stop();

    std::uint64_t bytes_sent() const noexcept {
        return bytes_sent_.load(std::memory_order_relaxed);
    }
    Stats& stats() noexcept { return stats_; }

private:
    void run();

    ChunkQueue& queue_;
    Config config_;
    Stats stats_;
    std::atomic<std::uint64_t> bytes_sent_{0};
    std::atomic<bool> stop_{false};
    std::thread thread_;
};

}  // namespace radar
