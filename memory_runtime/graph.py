"""基于扁平记忆数据合成 3D 图谱所需的 nodes/links 结构。

不做实体/关系抽取，只利用现有 MemoryRow 字段：
- evidence 边：同一段证据文本衍生出的多条记忆天然关联（与级联遗忘同源语义）。
- category 边：同类目记忆之间的弱关联，按置信度链式连接并限流，避免大类目下 O(n^2) 连接数。
- related 保底边：跨类目/证据的记忆之间不一定有共同类目或证据，为避免图谱出现完全孤立、毫无连线的散点，
  按置信度把所有记忆串成一条链，仅为已经存在 evidence/category 边的相邻节点对跳过，保证整张图连通。
"""
from __future__ import annotations

from typing import Any

_CATEGORY_EDGE_CAP = 40


def build_memory_graph(memories: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = [
        {
            "id": m["id"],
            "label": (m.get("content") or "")[:40],
            "category": m.get("category"),
            "confidence": m.get("confidence"),
            "occurrence_count": m.get("occurrence_count"),
            "status": m.get("status"),
            "created_at": m.get("created_at"),
        }
        for m in memories
    ]

    links: list[dict[str, Any]] = []

    by_evidence: dict[str, list[dict[str, Any]]] = {}
    for m in memories:
        evidence = m.get("evidence")
        if evidence:
            by_evidence.setdefault(evidence, []).append(m)
    for group in by_evidence.values():
        if len(group) < 2:
            continue
        hub = max(group, key=lambda m: (m.get("confidence") or 0, m.get("created_at") or ""))
        for m in group:
            if m["id"] != hub["id"]:
                links.append({"source": hub["id"], "target": m["id"], "type": "evidence"})

    by_category: dict[str, list[dict[str, Any]]] = {}
    for m in memories:
        category = m.get("category")
        if category:
            by_category.setdefault(category, []).append(m)
    for group in by_category.values():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda m: m.get("confidence") or 0, reverse=True)
        cap = min(len(ordered) - 1, _CATEGORY_EDGE_CAP)
        for i in range(cap):
            links.append({
                "source": ordered[i]["id"],
                "target": ordered[i + 1]["id"],
                "type": "category",
                "value": 0.3,
            })

    connected_pairs = {frozenset((l["source"], l["target"])) for l in links}
    ordered_all = sorted(memories, key=lambda m: m.get("confidence") or 0, reverse=True)
    for i in range(len(ordered_all) - 1):
        a, b = ordered_all[i]["id"], ordered_all[i + 1]["id"]
        if frozenset((a, b)) not in connected_pairs:
            links.append({"source": a, "target": b, "type": "related", "value": 0.1})
            connected_pairs.add(frozenset((a, b)))

    return {"nodes": nodes, "links": links}
