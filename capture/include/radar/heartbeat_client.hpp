#pragma once

#include <cstdint>
#include <memory>
#include <string>

namespace httplib {
class Client;
}

namespace radar {

struct HeartbeatRequest {
    std::string device_id;
    std::string stream_id; // empty serializes as null
    std::string state; // stopped|starting|running|error
    std::uint32_t native_rate_hz       = 0; // 0 serializes as null
    std::uint64_t dropped_frames_total = 0;
    std::string error_code; // empty serializes as null
};

struct HeartbeatReply {
    bool ok               = false;
    bool desired_capture  = false;
    int lease_ms          = 0;
    int settings_revision = 0;
    std::string error;
};

// Blocking POST /v1/capture/heartbeat client with a keep-alive connection.
// Used only by the supervisor thread, never by the audio callback or workers.
class HeartbeatClient {
public:
    HeartbeatClient(std::string base_url, std::string token);
    ~HeartbeatClient();

    HeartbeatClient(const HeartbeatClient&)            = delete;
    HeartbeatClient& operator=(const HeartbeatClient&) = delete;

    HeartbeatReply send(const HeartbeatRequest& request);

    const std::string& base_url() const noexcept { return base_url_; }
    bool valid() const noexcept { return valid_; }

private:
    std::string base_url_;
    std::string token_;
    std::string prefix_;
    bool valid_ = false;
    std::unique_ptr<httplib::Client> client_;
};

} // namespace radar
