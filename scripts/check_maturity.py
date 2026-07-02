"""check_maturity.py — 机型覆盖成熟度自动判级 (RCML, 见 docs/MATURITY.md)

对每个知识包计算 L0-L2 (L3 需人工证据, CI 只按 L2 封顶校验),
并强制 README 成熟度表与实际判级一致 —— 声称的等级必须可复现。

用法: python3 scripts/check_maturity.py   (退出码 0=通过, 1=失败)
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE = ROOT / "tools" / "knowledge"
sys.path.insert(0, str(ROOT / "tools"))

# 每个机型的样例事故目录 (L1 门槛之一)
SAMPLE_DIRS = {
    "agibot_x2": ROOT / "examples" / "sample-incident",
    "unitree_g1": ROOT / "examples" / "g1-sample-incident",
}

errors = []


def err(msg):
    errors.append(msg)
    print(f"  ❌ {msg}")


def has_cjk(s: str) -> bool:
    return bool(re.search(r"[一-鿿]", s))


def causal_fires_on_sample(robot_id: str, sample_dir: Path) -> int:
    """跑真实 ingest + match_timeline, 返回触发的因果链数。死规则不算数。"""
    from fault_library import FaultLibrary
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "log_ingestor.py"),
             str(sample_dir), "--robot", robot_id, "--output", td],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            return -1
        summary = Path(td) / "session.summary.json"
        if not summary.exists():
            return -1
        events = json.loads(summary.read_text(encoding="utf-8")).get("events", [])
    fl = FaultLibrary.for_robot(robot_id)
    return len(fl.match_timeline(events))


def assess(robot_id: str, pack: Path) -> tuple[int, list[str]]:
    """返回 (level, 判级说明)。"""
    notes = []
    dk = yaml.safe_load((pack / "diagnostic_knowledge.yaml").read_text(encoding="utf-8"))
    faults = dk.get("faults", [])
    keywords = dk.get("symptoms_index", {}).get("keywords", [])
    causal_doc = yaml.safe_load((pack / "causal_rules.yaml").read_text(encoding="utf-8")) or {}
    causal = causal_doc.get("rules", [])
    ep = yaml.safe_load((pack / "event_patterns.yaml").read_text(encoding="utf-8")) or {}
    patterns = ep.get("patterns", [])
    cb_path = pack / "capability_boundary.yaml"

    # L0: 结构合法 (check_knowledge 已把关, 这里能解析即视为通过)
    level = 0
    notes.append(f"L0 ✓ 结构合法 ({len(faults)} faults / {len(keywords)} keywords / "
                 f"{len(patterns)} patterns / {len(causal)} causal)")

    # L1 门槛
    kw_text = " ".join(k.get("pattern", "") for k in keywords)
    l1_checks = {
        "≥8 条故障规则": len(faults) >= 8,
        "中英文关键词": has_cjk(kw_text) and bool(re.search(r"[a-zA-Z]", kw_text)),
        "examples/ 样例事故": SAMPLE_DIRS.get(robot_id, Path("/nonexistent")).is_dir(),
    }
    fired = 0
    if all(l1_checks.values()):
        fired = causal_fires_on_sample(robot_id, SAMPLE_DIRS[robot_id])
        l1_checks["因果链在样例上触发"] = fired >= 1
    if all(l1_checks.values()):
        level = 1
        notes.append(f"L1 ✓ ({fired} 条因果链在样例上触发)")
    else:
        failed = [k for k, v in l1_checks.items() if not v]
        notes.append(f"L1 ✗ 缺: {', '.join(failed)}")
        return level, notes

    # L2 门槛
    fall_kw = any(re.search(r"摔倒|falling|fall", k.get("pattern", ""), re.IGNORECASE)
                  and k.get("fault_ids") for k in keywords)
    fall_causal = "falling_event" in yaml.dump(causal_doc, allow_unicode=True)
    cb_ok = False
    if cb_path.exists():
        cb = yaml.safe_load(cb_path.read_text(encoding="utf-8")) or {}
        cb_ok = bool(cb.get("blind_spots") or cb.get("capability_gaps") or
                     (isinstance(cb, dict) and len(cb) > 2))
    l2_checks = {
        "摔倒(主打场景)关键词映射": fall_kw,
        "falling_event 因果规则": fall_causal,
        "≥5 条因果规则": len(causal) >= 5,
        "capability_boundary 非空": cb_ok,
    }
    if all(l2_checks.values()):
        level = 2
        notes.append("L2 ✓ 场景级 (摔倒链路 + 盲区清单)")
    else:
        failed = [k for k, v in l2_checks.items() if not v]
        notes.append(f"L2 ✗ 缺: {', '.join(failed)}")
    return level, notes


def main() -> int:
    print("=" * 60)
    print("  机型覆盖成熟度判级 (RCML)")
    print("=" * 60)
    levels = {}
    for pack in sorted(p for p in KNOWLEDGE.iterdir() if p.is_dir()):
        robot_id = pack.name
        print(f"\n🤖 {robot_id}")
        try:
            level, notes = assess(robot_id, pack)
        except Exception as e:
            err(f"{robot_id}: 判级失败 {e}")
            continue
        for n in notes:
            print(f"  {n}")
        levels[robot_id] = level
        print(f"  → 判级: L{level}")

    # README 成熟度表核对 (中英双份): 声称等级必须与实际判级一致
    print("\n📄 README 成熟度表核对")
    dk_counts = {
        rid: len((yaml.safe_load((KNOWLEDGE / rid / "diagnostic_knowledge.yaml")
                                 .read_text(encoding="utf-8")) or {}).get("faults", []))
        for rid in levels
    }
    for md in (ROOT / "README.md", ROOT / "docs" / "zh" / "README.md"):
        text = md.read_text(encoding="utf-8")
        for rid, level in levels.items():
            needle = f"`{rid}/` | {dk_counts[rid]} | **L{level}**"
            if needle in text:
                print(f"  ✅ {md.relative_to(ROOT)}: '{needle}'")
            else:
                err(f"{md.relative_to(ROOT)} 成熟度表与实际判级不符, 应含: '{needle}'")

    print()
    if errors:
        print(f"❌ 成熟度门禁失败: {len(errors)} 项")
        return 1
    print("✅ 成熟度门禁通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
