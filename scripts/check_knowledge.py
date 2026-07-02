"""check_knowledge.py — 知识库一致性门禁

CI 质量底线之一: 知识库必须结构合法、引用完整,且文档里声称的数字
必须与 YAML 实际内容一致 (防止"文档超前主张"回归)。

用法: python3 scripts/check_knowledge.py   (退出码 0=通过, 1=失败)
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
errors = []


def err(msg):
    errors.append(msg)
    print(f"  ❌ {msg}")


def ok(msg):
    print(f"  ✅ {msg}")


# ---- 1. YAML 解析 ----
print("📚 知识库结构")
knowledge = {}
yaml_files = sorted((ROOT / "tools" / "knowledge").glob("*.yaml"))
for p in yaml_files:
    try:
        knowledge[p.stem] = yaml.safe_load(p.read_text(encoding="utf-8"))
        ok(f"{p.name} 解析")
    except yaml.YAMLError as e:
        err(f"{p.name} 解析失败: {e}")

dk = knowledge.get("diagnostic_knowledge") or {}
faults = dk.get("faults", [])
keywords = dk.get("symptoms_index", {}).get("keywords", [])
patterns = (knowledge.get("event_patterns") or {}).get("patterns", [])
causal = (knowledge.get("causal_rules") or {}).get("rules", [])

# ---- 2. 结构与引用完整性 ----
print("\n🔗 引用完整性")
fault_ids = {f.get("id") for f in faults}
for f in faults:
    for field in ("id", "name", "severity"):
        if not f.get(field):
            err(f"fault 缺少 {field}: {f}")
    if f.get("severity") not in ("CRITICAL", "WARNING", "NOTICE", "INFO"):
        err(f"fault {f.get('id')} severity 非法: {f.get('severity')}")

for kw in keywords:
    pat = kw.get("pattern", "")
    try:
        re.compile(pat)
    except re.error as e:
        err(f"symptoms_index 正则非法: {pat!r} ({e})")
    for fid in kw.get("fault_ids", []):
        if fid not in fault_ids:
            err(f"symptoms_index 引用不存在的 fault: {fid}")

for p in patterns:
    try:
        re.compile(p.get("pattern", ""))
    except re.error as e:
        err(f"event_patterns 正则非法: {p.get('pattern')!r} ({e})")
    if not p.get("kind"):
        err(f"event_pattern 缺少 kind: {p}")

for r in causal:
    for fid in r.get("fault_ids", []):
        if fid not in fault_ids:
            err(f"causal_rules {r.get('id')} 引用不存在的 fault: {fid}")

if not errors:
    ok(f"{len(fault_ids)} faults / {len(keywords)} keywords / "
       f"{len(patterns)} patterns / {len(causal)} causal rules 引用完整")

# ---- 3. 文档数字 vs 实际内容 ----
print("\n📄 文档数字核对")
claims = [
    (ROOT / "README.md", f"{len(faults)} fault rules"),
    (ROOT / "README.md", f"{len(keywords)} keyword-match entries"),
    (ROOT / "README.md", f"{len(patterns)} log event patterns"),
    (ROOT / "README.md", f"{len(causal)} temporal causal rules"),
    (ROOT / "README.md", f"{len(yaml_files)} YAML files"),
    (ROOT / "docs/zh/README.md", f"{len(faults)} 条故障规则"),
    (ROOT / "docs/zh/README.md", f"{len(keywords)} 条中英文关键词索引"),
    (ROOT / "docs/zh/README.md", f"{len(patterns)} 种日志事件匹配规则"),
    (ROOT / "docs/zh/README.md", f"{len(causal)} 条时序因果规则"),
    (ROOT / "AGENTS.md", f"{len(faults)} 条故障规则"),
]
for path, needle in claims:
    if not path.exists():
        err(f"{path.name} 不存在")
        continue
    if needle in path.read_text(encoding="utf-8"):
        ok(f"{path.relative_to(ROOT)}: '{needle}'")
    else:
        err(f"{path.relative_to(ROOT)} 未找到与实际一致的表述: '{needle}' "
            f"(文档数字与 YAML 内容不符?)")

# ---- 总结 ----
print()
if errors:
    print(f"❌ 知识库门禁失败: {len(errors)} 项")
    sys.exit(1)
print("✅ 知识库门禁通过")
