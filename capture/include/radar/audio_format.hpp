#pragma once

// Wire and queue constants from the audio contract (architecture plan 5.2).
// These values are shared with the Python consumer; changes require an
// owner-reviewed contract update.

#include <cstddef>
#include <cstdint>

namespace radar {

inline constexpr int kWireSampleRateHz           = 16000;
inline constexpr std::size_t kWireChannels       = 1;
inline constexpr std::size_t kWireBytesPerSample = 2;
inline constexpr std::size_t kWireChunkFrames    = static_cast<std::size_t>(kWireSampleRateHz);
inline constexpr std::size_t kWireChunkBytes     = kWireChunkFrames * kWireBytesPerSample;

// Ring holds four seconds at the actual capture rate (set by the device).
// The ring is preallocated for the highest supported source rate, so any
// device at or below that rate still gets its full four seconds.
inline constexpr int kSourceRingSeconds        = 4;
inline constexpr int kMaxSupportedSourceRateHz = 96000;
// Sender queue holds at most two completed chunks; oldest pending drops.
inline constexpr std::size_t kSenderQueueMaxChunks = 2;

inline constexpr int kHeartbeatIntervalMs  = 500;
inline constexpr int kDefaultLeaseMs       = 2000;
inline constexpr int kStartRetryIntervalMs = 2000;

// Consumer-side stale rule; the C++ side never retransmits a chunk.
inline constexpr int kStaleChunkMs   = 3000;
inline constexpr float kRmsFloorDbfs = -120.0f;

} // namespace radar
