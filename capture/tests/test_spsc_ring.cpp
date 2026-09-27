#include "radar/spsc_ring.hpp"

#include <vector>

#include "test_util.hpp"

namespace {

void capacity_rounds_up() {
    RADAR_CHECK(radar::SpscRing(1).capacity() == 2);
    RADAR_CHECK(radar::SpscRing(3).capacity() == 4);
    RADAR_CHECK(radar::SpscRing(4).capacity() == 4);
    RADAR_CHECK(radar::SpscRing(5000).capacity() == 8192);
}

void roundtrip_and_wraparound() {
    radar::SpscRing ring(4);
    std::vector<float> out(4, 0.0f);

    const float first[] = {1.0f, 2.0f, 3.0f};
    RADAR_CHECK(ring.write(first, 3) == 3);
    RADAR_CHECK(ring.readable() == 3);
    RADAR_CHECK(ring.read(out.data(), 3) == 3);
    RADAR_CHECK(out[0] == 1.0f && out[1] == 2.0f && out[2] == 3.0f);

    // Write index is now 3, so this write wraps through the buffer end.
    const float second[] = {4.0f, 5.0f, 6.0f, 7.0f};
    RADAR_CHECK(ring.write(second, 4) == 4);
    RADAR_CHECK(ring.read(out.data(), 4) == 4);
    RADAR_CHECK(out[0] == 4.0f && out[1] == 5.0f && out[2] == 6.0f && out[3] == 7.0f);
    RADAR_CHECK(ring.writable() == 4);
}

void overflow_drops_new_frames() {
    radar::SpscRing ring(4);
    const float full[] = {1.0f, 2.0f, 3.0f, 4.0f};
    RADAR_CHECK(ring.write(full, 4) == 4);
    RADAR_CHECK(ring.writable() == 0);

    const float extra[] = {9.0f, 9.0f};
    RADAR_CHECK(ring.write(extra, 2) == 0);
    RADAR_CHECK(ring.readable() == 4);

    std::vector<float> out(4, 0.0f);
    RADAR_CHECK(ring.read(out.data(), 4) == 4);
    RADAR_CHECK(out[0] == 1.0f && out[3] == 4.0f);
}

void partial_write_reports_accepted_count() {
    radar::SpscRing ring(4);
    const float six[] = {1, 2, 3, 4, 5, 6};
    RADAR_CHECK(ring.write(six, 6) == 4);
    RADAR_CHECK(ring.readable() == 4);
}

void read_never_reads_past_write() {
    radar::SpscRing ring(4);
    const float value[] = {42.0f};
    RADAR_CHECK(ring.write(value, 1) == 1);
    float out[4] = {};
    RADAR_CHECK(ring.read(out, 4) == 1);
    RADAR_CHECK(out[0] == 42.0f);
}

void reset_clears_both_indices() {
    radar::SpscRing ring(4);
    const float value[] = {1.0f, 2.0f};
    ring.write(value, 2);
    ring.reset();
    RADAR_CHECK(ring.readable() == 0);
    RADAR_CHECK(ring.writable() == 4);
}

void run_tests() {
    capacity_rounds_up();
    roundtrip_and_wraparound();
    overflow_drops_new_frames();
    partial_write_reports_accepted_count();
    read_never_reads_past_write();
    reset_clears_both_indices();
}

}  // namespace

RADAR_TEST_MAIN()
