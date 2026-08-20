cmake_minimum_required(VERSION 3.15)
project(reality_patch_cognitive LANGUAGES CXX)

add_library(reality_patch_cognitive SHARED cognitive_engine.cpp)
target_compile_features(reality_patch_cognitive PRIVATE cxx_std_17)
