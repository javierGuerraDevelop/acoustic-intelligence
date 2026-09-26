#include "radar/heartbeat_client.hpp"

#include <algorithm>

#include <httplib.h>
#include <nlohmann/json.hpp>

#include "radar/audio_format.hpp"
#include "radar/url_util.hpp"

namespace radar {

namespace {

nlohmann::json heartbeat_body(const HeartbeatRequest& request) {
    nlohmann::json body = {
        {"schema_version", 1},
        {"device_id", request.device_id},
        {"state", request.state},
        {"dropped_frames_total", request.dropped_frames_total},
    };
    body["stream_id"] = request.stream_id.empty() ? nlohmann::json(nullptr)
                                                  : nlohmann::json(request.stream_id);
    body["native_rate_hz"] = request.native_rate_hz == 0
                                 ? nlohmann::json(nullptr)
                                 : nlohmann::json(request.native_rate_hz);
    body["error_code"] = request.error_code.empty() ? nlohmann::json(nullptr)
                                                    : nlohmann::json(request.error_code);
    return body;
}

}  // namespace

HeartbeatClient::HeartbeatClient(std::string base_url, std::string token)
    : base_url_(std::move(base_url)), token_(std::move(token)) {
    const HttpUrl parsed = parse_http_url(base_url_);
    valid_ = parsed.valid;
    if (!parsed.valid) {
        return;
    }
    prefix_ = parsed.prefix;
    client_ = std::make_unique<httplib::Client>(parsed.host, parsed.port);
    client_->set_keep_alive(true);
    client_->set_connection_timeout(0, 200000);  // 200 ms
    client_->set_read_timeout(0, 500000);        // 500 ms
    client_->set_write_timeout(0, 500000);
}

HeartbeatClient::~HeartbeatClient() = default;

HeartbeatReply HeartbeatClient::send(const HeartbeatRequest& request) {
    HeartbeatReply reply;
    if (!valid_ || client_ == nullptr) {
        reply.error = "invalid backend url";
        return reply;
    }

    httplib::Headers headers = {{"X-Schema-Version", "1"}};
    if (!token_.empty()) {
        headers.emplace("Authorization", "Bearer " + token_);
    }

    const std::string path = prefix_ + "/v1/capture/heartbeat";
    const std::string body = heartbeat_body(request).dump();
    auto response = client_->Post(path, headers, body, "application/json");
    if (!response) {
        reply.error = "heartbeat request failed";
        return reply;
    }
    if (response->status != 200) {
        reply.error = "heartbeat status " + std::to_string(response->status);
        return reply;
    }

    try {
        const nlohmann::json parsed = nlohmann::json::parse(response->body);
        if (parsed.value("schema_version", 0) != 1) {
            reply.error = "heartbeat schema mismatch";
            return reply;
        }
        if (!parsed.contains("desired_capture") || !parsed["desired_capture"].is_boolean()) {
            reply.error = "heartbeat missing desired_capture";
            return reply;
        }
        reply.desired_capture = parsed["desired_capture"].get<bool>();
        reply.lease_ms = std::clamp(parsed.value("lease_ms", kDefaultLeaseMs), 250, 10000);
        reply.settings_revision = parsed.value("settings_revision", 0);
        reply.ok = true;
    } catch (const nlohmann::json::exception&) {
        reply.error = "heartbeat response not valid json";
    }
    return reply;
}

}  // namespace radar
