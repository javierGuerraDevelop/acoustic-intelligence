#include "radar/time_util.hpp"

#include <cstdio>
#include <ctime>

namespace radar {

std::string format_utc_rfc3339_ms(std::chrono::system_clock::time_point time_point) {
    using namespace std::chrono;
    const auto millis = duration_cast<milliseconds>(time_point.time_since_epoch());
    const auto seconds = duration_cast<std::chrono::seconds>(millis);
    auto remainder = millis - seconds;
    if (remainder.count() < 0) {
        remainder += std::chrono::seconds(1);
    }

    const std::time_t raw = static_cast<std::time_t>(seconds.count());
    std::tm utc{};
#if defined(_WIN32)
    gmtime_s(&utc, &raw);
#else
    gmtime_r(&raw, &utc);
#endif

    char buffer[32] = {};
    std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%S", &utc);
    char result[48] = {};
    std::snprintf(result, sizeof(result), "%s.%03lldZ", buffer,
                  static_cast<long long>(remainder.count()));
    return result;
}

}  // namespace radar
