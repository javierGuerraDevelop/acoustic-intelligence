# One executable per test file; each returns 0 only when all checks pass.
set(RADAR_CAPTURE_TESTS
    test_spsc_ring
    test_resampler
    test_chunker
    test_chunk_queue
    test_time_util
)

foreach(test_name IN LISTS RADAR_CAPTURE_TESTS)
    add_executable(${test_name} ${test_name}.cpp)
    target_link_libraries(${test_name} PRIVATE radar_capture_core)
    set_target_properties(${test_name} PROPERTIES
        CXX_EXTENSIONS OFF
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
    )
    radar_apply_warnings(${test_name})
    add_test(NAME capture.${test_name} COMMAND ${test_name})
endforeach()
