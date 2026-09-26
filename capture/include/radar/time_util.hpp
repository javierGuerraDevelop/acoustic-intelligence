#pragma once

#include <chrono>
#include <string>

namespace radar {

// UTC RFC 3339 with exactly three fractional digits and a trailing Z, as
// required by the audio contract's X-Captured-At header.
std::string format_utc_rfc3339_ms(std::chrono::system_clock::time_point time_point);

}  // namespace radar
