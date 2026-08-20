#include "cognitive_engine.h"

#include <cstring>
#include <string>

namespace {
thread_local std::string result;
}

const char* rp_engine_version() {
    return "reality-patch-cognitive/0.1";
}

const char* rp_analyze_json(const char* text, const char*) {
    const std::size_t length = text == nullptr ? 0 : std::strlen(text);
    result = "{\"char_count\":" + std::to_string(length) + "}";
    return result.c_str();
}

double rp_score_feedback(const char* event_json, const char*) {
    if (event_json == nullptr) return 0.0;
    const std::string event(event_json);
    if (event.find("confirm") != std::string::npos) return 0.1;
    if (event.find("reject") != std::string::npos || event.find("forget") != std::string::npos) return -0.2;
    return 0.0;
}
