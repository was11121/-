# Optional C++ Cognitive Engine

Python remains the default implementation. This directory defines a small,
stable C ABI for a future high-frequency feature extractor. The C++ layer must
not own LLM calls, user data persistence, or business side effects.

Expected contract:

```text
analyze(text, user_state) -> JSON feature object
score_feedback(event, memory) -> floating-point delta
detect_direction_shift(context) -> JSON decision
update_relationship(state, event) -> JSON state
```

The Python adapter currently probes `COGNITIVE_ENGINE_LIBRARY` and falls back
to `PythonCognitiveEngine` when the library is absent or incompatible.
