#pragma once

#include <string>

namespace radar {

// Minimal parser for the loopback HTTP origin the launcher provides, e.g.
// "http://127.0.0.1:8000" or "http://127.0.0.1:8000/prefix". HTTPS and cloud
// origins are out of scope: this component only talks to the local service.
struct HttpUrl {
    bool valid = false;
    std::string host;
    int port = 80;
    std::string prefix; // no trailing slash; may be empty
};

HttpUrl parse_http_url(const std::string& url);

} // namespace radar
