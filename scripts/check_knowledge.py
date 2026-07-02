"""check_knowledge.py — 知识库一致性门禁

Per-robot YAML packs under tools/knowledge/<robot_id>/.
CI validates structure, cross-references, and README table claims.

用法: python3 scripts/check_knowledge.py   (退出码 0=通过, 1=失败)
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE = ROOT / "tools" / "knowledge"
errors = []

EXPECTED_FAULTS = {
    "agibot_x2": 11,
    "unitree_g1": 8,
}


def err(msg):
    errors.append(msg)
    print(f"  ❌ {msg}")


def ok(msg):
    print(f"  ✅ {msg}")


def validate_robot_pack(robot_id: str, robot_dir: Path) -> None:
    print(f"\n📚 知识库结构 — {robot_id}")
    yaml_files = sorted(robot_dir.glob("*.yaml"))
    if not yaml_files:
        err(f"{robot_id}: 无 YAML 文件")
        return

    knowledge: dict[str, object] = {}
    for p in yaml_files:
        try:
            knowledge[p.stem] = yaml.safe_load(p.read_text(encoding="utf-8"))
            ok(f"{robot_id}/{p.name} 解析")
        except yaml.YAMLError as e:
            err(f"{robot_id}/{p.name} 解析失败: {e}")
            return

    dk = knowledge.get("diagnostic_knowledge") or {}
    faults = dk.get("faults", []) if isinstance(dk, dict) else []
    keywords = (dk.get("symptoms_index", {}) or {}).get("keywords", []) if isinstance(dk, dict) else []
    patterns = (knowledge.get("event_patterns") or {}).get("patterns", []) if isinstance(knowledge.get("event_patterns"), dict) else []
    causal = (knowledge.get("causal_rules") or {}).get("rules", []) if isinstance(knowledge.get("causal_rules"), dict) else []

    print(f"\n🔗 引用完整性 — {robot_id}")
    fault_ids = {f.get("id") for f in faults}
    expected = EXPECTED_FAULTS.get(robot_id)
    if expected is not None and len(fault_ids) != expected:
        err(f"{robot_id}: fault 数量 {len(fault_ids)} != 期望 {expected}")

    for f in faults:
        for field in ("id", "name", "severity"):
            if not f.get(field):
                err(f"{robot_id} fault 缺少 {field}: {f}")
        if f.get("severity") not in ("CRITICAL", "WARNING", "NOTICE", "INFO"):
            err(f"{robot_id} fault {f.get('id')} severity 非法: {f.get('severity')}")

    for kw in keywords:
        pat = kw.get("pattern", "")
        try:
            re.compile(pat)
        except re.error as e:
            err(f"{robot_id} symptoms_index 正则非法: {pat!r} ({e})")
        for fid in kw.get("fault_ids", []):
            if fid not in fault_ids:
                err(f"{robot_id} symptoms_index 引用不存在的 fault: {fid}")

    for p in patterns:
        try:
            re.compile(p.get("pattern", ""))
        except re.error as e:
            err(f"{robot_id} event_patterns 正则非法: {p.get('pattern')!r} ({e})")
        if not p.get("kind"):
            err(f"{robot_id} event_pattern 缺少 kind: {p}")

    for r in causal:
        for fid in r.get("fault_ids", []):
            if fid not in fault_ids:
                err(f"{robot_id} causal_rules {r.get('id')} 引用不存在的 fault: {fid}")

    if not any(e.startswith(robot_id) for e in errors):
        ok(
            f"{robot_id}: {len(fault_ids)} faults / {len(keywords)} keywords / "
            f"{len(patterns)} patterns / {len(causal)} causal rules 引用完整"
        )


print("📚 知识库根目录")
if not (KNOWLEDGE / "README.md").exists():
    err("tools/knowledge/README.md 缺失")
else:
    ok("tools/knowledge/README.md")

robot_dirs = sorted(d for d in KNOWLEDGE.iterdir() if d.is_dir())
if not robot_dirs:
    err("tools/knowledge 下无 robot 子目录")
for robot_dir in robot_dirs:
    validate_robot_pack(robot_dir.name, robot_dir)

print("\n📄 文档数字核对")
readme = ROOT / "README.md"
if not readme.exists():
    err("README.md 不存在")
else:
    readme_text = readme.read_text(encoding="utf-8")
    table_rows = [
        ("| AgiBot X2 Ultra | `agibot_x2/` | 11 |", "AgiBot X2 table row"),
        ("| Unitree G1 | `unitree_g1/` | 8 |", "Unitree G1 table row"),
    ]
    for needle, label in table_rows:
        if needle in readme_text:
            ok(f"README.md: {label}")
        else:
            err(f"README.md 未找到: {needle!r}")

print()
if errors:
    print(f"❌ 知识库门禁失败: {len(errors)} 项")
    sys.exit(1)
print("✅ 知识库门禁通过")
