#include "radar/http_sender.hpp"

#include <chrono>
#include <cstdio>

#include <httplib.h>

#include "radar/audio_format.hpp"
#include "radar/time_util.hpp"

namespace radar {

namespace {
    constexpr long kConnectTimeoutUsec = 200000; // 200 ms
    constexpr long kRequestTimeoutUsec = 750000; // 750 ms total per attempt
} // namespace

HttpSender::HttpSender(ChunkQueue& queue, Config config)
    : queue_(queue)
    , config_(std::move(config))
{
}

HttpSender::~HttpSender()
{
    stop();
}

void HttpSender::start()
{
    if (thread_.joinable()) {
        return;
    }
    stop_.store(false, std::memory_order_release);
    thread_ = std::thread([this] { run(); });
}

void HttpSender::stop()
{
    stop_.store(true, std::memory_order_release);
    queue_.close();
    if (thread_.joinable()) {
        thread_.join();
    }
}

void HttpSender::run()
{
    httplib::Client client(config_.host, config_.port);
    client.set_keep_alive(true);
    client.set_connection_timeout(0, kConnectTimeoutUsec);
    client.set_read_timeout(0, kRequestTimeoutUsec);
    client.set_write_timeout(0, kRequestTimeoutUsec);

    while (!stop_.load(std::memory_order_acquire)) {
        auto chunk = queue_.pop(std::chrono::milliseconds(100));
        if (chunk == nullptr) {
            continue;
        }

        const std::string captured_at = format_utc_rfc3339_ms(chunk->captured_at);
        char rms[32]                  = { };
        std::snprintf(rms, sizeof(rms), "%.1f", static_cast<double>(chunk->rms_dbfs));

        httplib::Headers headers = {
            { "X-Schema-Version", "1" },
            { "X-Device-Id", config_.device_id },
            { "X-Stream-Id", std::string(chunk->stream_id.data()) },
            { "X-Chunk-Seq", std::to_string(chunk->seq) },
            { "X-Start-Sample", std::to_string(chunk->start_sample) },
            { "X-Captured-At", captured_at },
            { "X-Sample-Rate", std::to_string(kWireSampleRateHz) },
            { "X-Channels", std::to_string(kWireChannels) },
            { "X-Encoding", "pcm_s16le" },
            { "X-Rms-Dbfs", rms },
            { "X-Dropped-Frames-Total", std::to_string(chunk->dropped_frames_total) },
        };
        if (!config_.token.empty()) {
            headers.emplace("Authorization", "Bearer " + config_.token);
        }

        const auto* body = reinterpret_cast<const char*>(chunk->pcm.data());
        auto response    = client.Post(config_.path, headers, body,
            static_cast<std::size_t>(chunk->pcm.size()),
            "application/octet-stream");
        if (response && (response->status == 202 || response->status == 200)) {
            stats_.sent.fetch_add(1, std::memory_order_relaxed);
            bytes_sent_.fetch_add(chunk->pcm.size(), std::memory_order_relaxed);
        } else {
            const std::uint64_t failures = stats_.failed.fetch_add(1, std::memory_order_relaxed) + 1;
            if (failures == 1 || failures % 50 == 0) {
                const int status         = response ? response->status : 0;
                const std::string reason = response ? std::string("http") : httplib::to_string(response.error());
                std::fprintf(stderr,
                    "sender: chunk %llu discarded (http_status=%d, reason=%s, failures=%llu)\n",
                    static_cast<unsigned long long>(chunk->seq), status, reason.c_str(),
                    static_cast<unsigned long long>(failures));
            }
        }
    }
}

} // namespace radar
