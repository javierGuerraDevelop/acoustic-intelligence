#include "radar/url_util.hpp"

namespace radar {

HttpUrl parse_http_url(const std::string& url) {
    HttpUrl parsed;
    const std::string scheme = "http://";
    if (url.rfind(scheme, 0) != 0) {
        return parsed;
    }
    std::string rest = url.substr(scheme.size());
    const std::size_t slash = rest.find('/');
    if (slash == std::string::npos) {
        parsed.prefix.clear();
    } else {
        parsed.prefix = rest.substr(slash);
        while (!parsed.prefix.empty() && parsed.prefix.back() == '/') {
            parsed.prefix.pop_back();
        }
        rest = rest.substr(0, slash);
    }
    const std::size_t colon = rest.rfind(':');
    if (colon == std::string::npos) {
        parsed.host = rest;
        parsed.port = 80;
    } else {
        parsed.host = rest.substr(0, colon);
        try {
            parsed.port = std::stoi(rest.substr(colon + 1));
        } catch (const std::exception&) {
            return parsed;
        }
    }
    parsed.valid = !parsed.host.empty() && parsed.port > 0 && parsed.port <= 65535;
    return parsed;
}

}  // namespace radar
