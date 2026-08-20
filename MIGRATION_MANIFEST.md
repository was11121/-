# Source extraction manifest

The new project is intentionally independent of the source tree. These are the
source capabilities represented by the new modules:

| New module | Original source capability |
|---|---|
| `memory_runtime` | `memory_service.py`, `user_space.py`, `user_profile.py` |
| `cognitive_engine` | `relationship_engine.py`, `psych_analyzer/` |
| `library_runtime` | `knowledge_collector.py`, `rag.py`, `rag_service/`, `naosi_sync.py`, `frontier_sync.py` |
| `secretary_runtime` | `bridge/group_secretary.py` state machine |
| `unified_agent` | `agent/runner.py`, `agent/graph.py`, `agent/context.py` concepts |
| `adapters` | `server.py`, `bridge/routes.py`, `bridge/message_handler.py` entrypoint concepts |

No source file in `MyAgent重构` is edited by this migration.
