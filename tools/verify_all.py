"""verify_all.py — 诊断助手全功能验证"""
import json
import sys
from pathlib import Path

PROJECT = Path(r"D:\manastone-diag")
sys.path.insert(0, str(PROJECT / "tools"))

errors = []

def check(label, condition, detail=""):
    ok = "✅" if condition else "❌"
    print(f"  {ok} {label} {detail}")
    if not condition:
        errors.append(f"{label}: {detail}")

print("=" * 60)
print("  Manastone 诊断助手 v1.0 — 全功能验证")
print("=" * 60)

# ---- 1. 项目结构 ----
print("\n📁 项目结构")
check("AGENTS.md", (PROJECT / "AGENTS.md").exists())
check("knowledge/ (YAML知识库)", (PROJECT / "knowledge").is_dir())
check("tools/ (诊断工具)", (PROJECT / "tools").is_dir())
check("robot-logs/ (日志目录)", (PROJECT / "robot-logs").is_dir())
check("data/ (数据目录)", (PROJECT / "data").is_dir())
check("manage.bat (面板入口)", (PROJECT / "manage.bat").exists())

# ---- 2. 工具编译 ----
print("\n🔧 工具编译")
for f in ["config", "log_ingestor", "fault_library", "mcap_reader",
           "atop_reader", "diagnostic_orchestrator", "session_archiver",
           "experience_manager", "import_tool"]:
    try:
        compile((PROJECT / "tools" / f"{f}.py").read_text(), f"{f}.py", "exec")
        check(f"{f}.py", True)
    except Exception as e:
        check(f"{f}.py", False, str(e))

# ---- 3. 工具导入 ----
print("\n📦 工具导入")
try:
    from config import data_dir
    print(f"  数据目录: {data_dir()}")
    check("config.data_dir()", True)
except Exception as e:
    check("config.data_dir()", False, str(e))

try:
    from fault_library import FaultLibrary
    fl = FaultLibrary()
    check(f"FaultLibrary ({len(fl.faults)} faults, {len(fl.causal_rules)} causal)", True)
except Exception as e:
    check("FaultLibrary", False, str(e))

try:
    from log_ingestor import _resolve_patterns
    patterns = _resolve_patterns(PROJECT / "knowledge")
    kinds = {p["kind"] for p in patterns}
    check(f"LogIngestor patterns ({len(patterns)} kinds: {sorted(kinds)[:5]}...)", len(patterns) >= 9)
except Exception as e:
    check("LogIngestor patterns", False, str(e))

# ---- 4. 数据文件 ----
print("\n💾 数据文件")
arch_dir = data_dir() / "archive"
shards_dir = data_dir() / "experience_shards"
records_dir = data_dir() / "records"
idx_path = data_dir() / "experience_index.json"

check("archive/ (归档)", arch_dir.is_dir())
check("experience_shards/ (经验分片)", shards_dir.is_dir())
check("records/ (对话记录)", records_dir.is_dir())
check("experience_index.json", idx_path.exists())

# 统计
if idx_path.exists():
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    total = idx["stats"]["total"]
    shards = list(shards_dir.glob("shard_*.json"))
    print(f"  经验库: {total} 条经验, {len(shards)} 个分片")

if arch_dir.exists():
    arch_files = [f for f in arch_dir.glob("*.json") if f.name != "index.json"]
    print(f"  归档: {len(arch_files)} 条记录")

if records_dir.exists():
    rec_files = list(records_dir.glob("*.json"))
    print(f"  对话: {len(rec_files)} 条记录")

# robot-logs
rl = PROJECT / "robot-logs"
if rl.exists():
    tars = list(rl.glob("*.tar")) + list(rl.glob("*.tar.gz"))
    print(f"  日志包: {len(tars)} 个 tar 文件")

# ---- 5. 端到端流程测试 ----
print("\n🔄 端到端流程")

# 用实际数据跑 FaultLibrary
if fl and fl.faults:
    result = fl.match_keywords("站立状态下突然摔倒 JOINT_DEFAULT 位控模式")
    if result:
        check(f"FaultLibrary.match_keywords('站立摔倒') → {result[0].rule.id}", True)
    else:
        check("FaultLibrary.match_keywords", False, "未匹配")

    # 时序因果
    fake_events = [
        {"kind": "log.mode_transition", "epoch_ns": 1714819102588000000,
         "payload": {"text": "JOINT_DEFAULT"}, "source_file": "test", "ts": "10:38:22"},
        {"kind": "log.falling_event", "epoch_ns": 1714819103778000000,
         "payload": {"text": "Detect Falling"}, "source_file": "test", "ts": "10:38:23.778"},
    ]
    timeline = fl.match_timeline(fake_events)
    check(f"FaultLibrary.match_timeline() → {len(timeline)} causal chains", len(timeline) >= 1)

# ---- 6. 经验库功能 ----
print("\n📊 经验库功能")
try:
    import subprocess
    r = subprocess.run(["python", str(PROJECT / "tools" / "experience_manager.py"), "stats"],
                       capture_output=True, text=True, timeout=10, cwd=str(PROJECT))
    check("experience_manager stats", r.returncode == 0)
except Exception as e:
    check("experience_manager stats", False, str(e))

try:
    r = subprocess.run(["python", str(PROJECT / "tools" / "experience_manager.py"), "search", "摔倒"],
                       capture_output=True, text=True, timeout=10, cwd=str(PROJECT))
    check("experience_manager search '摔倒'", r.returncode == 0)
except Exception as e:
    check("experience_manager search", False, str(e))

# ---- 7. 归档面板 ----
print("\n📋 归档面板")
try:
    r = subprocess.run(["python", str(PROJECT / "tools" / "session_archiver.py"), "dashboard"],
                       capture_output=True, text=True, timeout=15, cwd=str(PROJECT))
    check("session_archiver dashboard", r.returncode == 0)
except Exception as e:
    check("session_archiver dashboard", False, str(e))

# ---- 8. 导入工具 ----
print("\n📥 导入工具")
check("import_tool.py (GUI)", (PROJECT / "tools" / "import_tool.py").exists())
check("manage.bat (双击面板)", (PROJECT / "manage.bat").exists())

# ---- 总结 ----
print("\n" + "=" * 60)
if errors:
    print(f"❌ {len(errors)} 项失败:")
    for e in errors:
        print(f"   - {e}")
else:
    print("✅ 全部验证通过！诊断助手 v1.0 就绪。")
print("=" * 60)
