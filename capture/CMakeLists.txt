cmake_minimum_required(VERSION 3.24)
project(radar_capture LANGUAGES C CXX)

include(FetchContent)
find_package(Threads REQUIRED)

# Build miniaudio's own implementation once; application code should just
# include <miniaudio.h>, without defining MINIAUDIO_IMPLEMENTATION.
set(MINIAUDIO_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(MINIAUDIO_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(MINIAUDIO_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(MINIAUDIO_NO_EXTRA_NODES ON CACHE BOOL "" FORCE)
set(MINIAUDIO_NO_LIBVORBIS ON CACHE BOOL "" FORCE)
set(MINIAUDIO_NO_LIBOPUS ON CACHE BOOL "" FORCE)
set(MINIAUDIO_INSTALL OFF CACHE BOOL "" FORCE)
FetchContent_Declare(miniaudio
    URL https://codeload.github.com/mackron/miniaudio/tar.gz/refs/tags/0.11.25
    URL_HASH SHA256=b900edcffe979816e2560a0580b9b1216d674b4f17fbadeca8f777a7f8ab0274
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)

# This component sends plain HTTP only to loopback. HTTPS cloud calls belong
# to Python, so optional TLS/compression dependencies are unnecessary here.
set(HTTPLIB_USE_OPENSSL_IF_AVAILABLE OFF CACHE BOOL "" FORCE)
set(HTTPLIB_USE_ZLIB_IF_AVAILABLE OFF CACHE BOOL "" FORCE)
set(HTTPLIB_USE_BROTLI_IF_AVAILABLE OFF CACHE BOOL "" FORCE)
set(HTTPLIB_USE_ZSTD_IF_AVAILABLE OFF CACHE BOOL "" FORCE)
set(HTTPLIB_COMPILE OFF CACHE BOOL "" FORCE)
set(HTTPLIB_INSTALL OFF CACHE BOOL "" FORCE)
set(HTTPLIB_TEST OFF CACHE BOOL "" FORCE)
FetchContent_Declare(httplib
    URL https://codeload.github.com/yhirose/cpp-httplib/tar.gz/refs/tags/v0.20.0
    URL_HASH SHA256=18064587e0cc6a0d5d56d619f4cbbcaba47aa5d84d86013abbd45d95c6653866
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
FetchContent_MakeAvailable(miniaudio httplib)

# Application sources are listed explicitly here; add new .cpp files to this
# list when they land (see capture/AGENTS.md).
set(RADAR_CAPTURE_SOURCES
    src/main.cpp
)

add_executable(radar_capture ${RADAR_CAPTURE_SOURCES})
target_compile_features(radar_capture PRIVATE cxx_std_20)
set_target_properties(radar_capture PROPERTIES
    CXX_EXTENSIONS OFF
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)
target_include_directories(radar_capture PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_include_directories(radar_capture SYSTEM PRIVATE "${miniaudio_SOURCE_DIR}")
# miniaudio_common_options supplies its upstream platform link dependencies.
target_link_libraries(radar_capture PRIVATE
    miniaudio
    miniaudio_common_options
    httplib::httplib
    Threads::Threads
)

# Warnings affect application code; no global -Werror or vendor flag changes.
if(MSVC)
    target_compile_options(radar_capture PRIVATE /W4 /permissive- /Zc:__cplusplus)
    target_compile_definitions(radar_capture PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
elseif(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(radar_capture PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Add tests in capture/tests/CMakeLists.txt when actual tests exist.
include(CTest)
if(BUILD_TESTING AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/tests/CMakeLists.txt")
    add_subdirectory(tests)
endif()
