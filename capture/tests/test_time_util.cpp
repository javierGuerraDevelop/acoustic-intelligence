#include "radar/time_util.hpp"

#include <chrono>

#include "test_util.hpp"

namespace {

void formats_utc_with_milliseconds() {
    using namespace std::chrono;
    const sys_days day = 2026y / std::chrono::September / 26;
    const auto base = sys_time<milliseconds>(day) + hours(18);
    RADAR_CHECK(radar::format_utc_rfc3339_ms(base) == "2026-09-26T18:00:00.000Z");
    RADAR_CHECK(radar::format_utc_rfc3339_ms(base + milliseconds(123)) ==
                "2026-09-26T18:00:00.123Z");
    RADAR_CHECK(radar::format_utc_rfc3339_ms(base + milliseconds(999)) ==
                "2026-09-26T18:00:00.999Z");
    RADAR_CHECK(radar::format_utc_rfc3339_ms(base + seconds(61) + milliseconds(7)) ==
                "2026-09-26T18:01:01.007Z");
}

void run_tests() {
    formats_utc_with_milliseconds();
}

}  // namespace

RADAR_TEST_MAIN()
