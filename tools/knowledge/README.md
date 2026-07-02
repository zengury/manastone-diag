# Per-robot knowledge packs

YAML knowledge lives under one subdirectory per robot platform. Tools resolve paths via `tools/robot_knowledge.py` (`normalize_robot_id`, `knowledge_dir`, `paths_for_robot`).

| Robot | Directory | Primary files |
|-------|-----------|-----------------|
| AgiBot X2 Ultra | `agibot_x2/` | `diagnostic_knowledge.yaml`, `event_patterns.yaml`, `causal_rules.yaml`, plus ontology (`hardware.yaml`, `interfaces.yaml`, …) |
| Unitree G1 | `unitree_g1/` | Same layout; offline log patterns and fault rules ported from mcp-ros-diagnosis |

Add a new robot by creating `tools/knowledge/<robot_id>/` with at least `diagnostic_knowledge.yaml` and `event_patterns.yaml`, then register aliases in `robot_knowledge._ALIASES`.
