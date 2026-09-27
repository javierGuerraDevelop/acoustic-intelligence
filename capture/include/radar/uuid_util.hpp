#pragma once

#include <string>

namespace radar {

// Random RFC 4122 version 4 UUID text (lowercase, hyphenated). Worker or
// supervisor threads only; never called from the audio callback.
std::string make_uuid_v4();

} // namespace radar
