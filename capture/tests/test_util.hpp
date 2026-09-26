#pragma once

// Minimal assertion harness for capture tests (no external test dependency).
// Each test is one executable returning 0 only when every check passed.

#include <cmath>
#include <cstdio>

namespace radar_test {
inline int g_failures = 0;

inline void report(bool ok, const char* expression, const char* file, int line) {
    if (!ok) {
        std::printf("FAIL %s:%d: %s\n", file, line, expression);
        ++g_failures;
    }
}
}  // namespace radar_test

#define RADAR_CHECK(expression) ::radar_test::report((expression), #expression, __FILE__, __LINE__)

#define RADAR_CHECK_NEAR(actual, expected, tolerance)                                             \
    do {                                                                                          \
        const double a_ = static_cast<double>(actual);                                            \
        const double e_ = static_cast<double>(expected);                                          \
        if (!(std::fabs(a_ - e_) <= static_cast<double>(tolerance))) {                            \
            std::printf("FAIL %s:%d: %s=%.6f not within %.6f of %s=%.6f\n", __FILE__, __LINE__,   \
                        #actual, a_, static_cast<double>(tolerance), #expected, e_);              \
            ++radar_test::g_failures;                                                             \
        }                                                                                         \
    } while (false)

#define RADAR_TEST_MAIN()                       \
    int main() {                                \
        run_tests();                            \
        if (radar_test::g_failures == 0) {      \
            std::printf("ok\n");                \
            return 0;                           \
        }                                       \
        std::printf("%d check(s) failed\n", radar_test::g_failures); \
        return 1;                               \
    }
