#pragma once

#ifdef _WIN32
#define RP_EXPORT __declspec(dllexport)
#else
#define RP_EXPORT
#endif

extern "C" {
RP_EXPORT const char* rp_engine_version();
RP_EXPORT const char* rp_analyze_json(const char* text, const char* user_state_json);
RP_EXPORT double rp_score_feedback(const char* event_json, const char* memory_json);
}
