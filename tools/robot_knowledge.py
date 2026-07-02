"""Resolve per-robot knowledge directories under tools/knowledge/."""
from pathlib import Path

_ALIASES = {
    "g1": "unitree_g1",
    "unitree_g1": "unitree_g1",
    "unitree-g1": "unitree_g1",
    "agibot_x2": "agibot_x2",
    "x2": "agibot_x2",
}


def normalize_robot_id(robot_id: str) -> str:
    key = (robot_id or "").strip().lower().replace("-", "_")
    return _ALIASES.get(key, key)


def knowledge_root() -> Path:
    return Path(__file__).resolve().parent / "knowledge"


def knowledge_dir(robot_id: str) -> Path:
    return knowledge_root() / normalize_robot_id(robot_id)


def paths_for_robot(robot_id: str) -> dict[str, Path]:
    d = knowledge_dir(robot_id)
    return {
        "dir": d,
        "diagnostic_knowledge": d / "diagnostic_knowledge.yaml",
        "causal_rules": d / "causal_rules.yaml",
        "event_patterns": d / "event_patterns.yaml",
    }
