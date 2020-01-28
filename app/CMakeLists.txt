cmake_minimum_required(VERSION 3.5)

project(RecastBlenderAddon LANGUAGES CXX)

set(BUILD_TEST_APP_EXE OFF CACHE BOOL "Build test app exe file")
set(BUILD_DLL ON CACHE BOOL "Build dll file")
set(RECAST_LIB "" CACHE PATH "Path to recast.lib file.")
set(RECAST_ROOT_DIR "" CACHE PATH "Path to recast root directory.")
set(VERBOSE_LOGS OFF CACHE BOOL "Print entry and result values of arrays")

set(CMAKE_INCLUDE_CURRENT_DIR ON)
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include_directories(${RECAST_ROOT_DIR}/Recast/Include)

#set(SOURCES main.cpp recast-capi.cpp)

add_definitions(-DRECASTBLENDERADDON_LIBRARY)

if(VERBOSE_LOGS)
    add_definitions(-DVERBOSE_LOGS)
endif(VERBOSE_LOGS)

if(BUILD_DLL)
    add_library(RecastBlenderAddon SHARED recast-capi.cpp mesh_navmesh.cpp)
    target_link_libraries(RecastBlenderAddon ${RECAST_LIB})
endif(BUILD_DLL)
if(BUILD_TEST_APP_EXE)
    add_executable(RecastBlenderAddonTestApp main.cpp recast-capi.cpp mesh_navmesh.cpp)
    target_link_libraries(RecastBlenderAddonTestApp ${RECAST_LIB})
endif(BUILD_TEST_APP_EXE)
