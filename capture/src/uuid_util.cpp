#include "radar/uuid_util.hpp"

#include <array>
#include <cstdint>
#include <cstdio>
#include <random>

namespace radar {

std::string make_uuid_v4() {
    thread_local std::mt19937_64 generator(std::random_device{}());
    std::uniform_int_distribution<std::uint64_t> distribution;

    const std::uint64_t high = distribution(generator);
    std::uint64_t low = distribution(generator);

    std::array<unsigned char, 16> bytes{};
    for (int i = 0; i < 8; ++i) {
        bytes[static_cast<std::size_t>(i)] =
            static_cast<unsigned char>((high >> (8 * (7 - i))) & 0xFF);
        bytes[static_cast<std::size_t>(i + 8)] =
            static_cast<unsigned char>((low >> (8 * (7 - i))) & 0xFF);
    }
    bytes[6] = static_cast<unsigned char>((bytes[6] & 0x0F) | 0x40);
    bytes[8] = static_cast<unsigned char>((bytes[8] & 0x3F) | 0x80);

    char text[37] = {};
    std::snprintf(text, sizeof(text),
                  "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
                  bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5], bytes[6], bytes[7],
                  bytes[8], bytes[9], bytes[10], bytes[11], bytes[12], bytes[13], bytes[14],
                  bytes[15]);
    return std::string(text);
}

}  // namespace radar
