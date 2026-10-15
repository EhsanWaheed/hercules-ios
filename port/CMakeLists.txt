cmake_minimum_required(VERSION 3.20)
set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp" CACHE PATH
    "Path to psxrecomp")
if(NOT EXISTS "${PSXRECOMP_ROOT}/runtime/runtime.cmake")
    message(FATAL_ERROR
        "PSXRecomp runtime is missing: ${PSXRECOMP_ROOT}/runtime/runtime.cmake\n"
        "This project expects the psxrecomp framework checkout at ${PSXRECOMP_ROOT}.\n"
        "Run: git submodule update --init --recursive\n"
        "If psxrecomp/ is not a submodule, set -DPSXRECOMP_ROOT=<path-to-psxrecomp>.")
endif()

project(HerculesRecomp LANGUAGES C CXX)

# German version (SCES-00893); the others build from versions/<ID>/:
#   cmake -S versions/SCES-00891 -B build-en ...
set(HERCULES_VERSION "SCES-00893")
set(HERC_ROOT "${CMAKE_CURRENT_SOURCE_DIR}")

include("${HERC_ROOT}/hercules_game.cmake")
