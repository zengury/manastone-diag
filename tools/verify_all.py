"""verify_all.py — 诊断助手全功能验证

在任意干净 clone 上运行:
    python3 tools/verify_all.py

退出码: 0 = 全部通过, 1 = 有失败项 (供 CI 作为质量门禁)。
"""
import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "tools"))

errors = []

def check(label, condition, detail=""):
    ok = "✅" if condition else "❌"
    print(f"  {ok} {label} {detail}")
    if not condition:
        errors.append(f"{label}: {detail}")

def run():
    print("=" * 60)
    print("  manastone-diag — 全功能验证")
    print("=" * 60)
    print(f"  项目目录: {PROJECT}")

    # ---- 0. 运行时目录引导 (幂等; robot-logs/ 与 data/ 不入库) ----
    (PROJECT / "robot-logs").mkdir(exist_ok=True)

    # ---- 1. 项目结构 ----
    print("\n📁 项目结构")
    check("AGENTS.md", (PROJECT / "AGENTS.md").exists())
    check("tools/knowledge/ (YAML知识库)", (PROJECT / "tools" / "knowledge").is_dir())
    check("tools/ (诊断工具)", (PROJECT / "tools").is_dir())
    check("robot-logs/ (日志目录)", (PROJECT / "robot-logs").is_dir())
    check("manage.sh / manage.bat (面板入口)",
          (PROJECT / "manage.sh").exists() and (PROJECT / "manage.bat").exists())

    # ---- 2. 工具编译 ----
    print("\n🔧 工具编译")
    for f in ["config", "log_ingestor", "fault_library", "mcap_reader",
               "atop_reader", "diagnostic_orchestrator", "session_archiver",
               "experience_manager", "import_tool", "mcap_joint_parser"]:
        try:
            compile((PROJECT / "tools" / f"{f}.py").read_text(encoding="utf-8"),
                    f"{f}.py", "exec")
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

    fl = None
    try:
        from fault_library import FaultLibrary
        fl = FaultLibrary()
        check(f"FaultLibrary ({len(fl.faults)} faults, {len(fl.causal_rules)} causal)", True)
    except Exception as e:
        check("FaultLibrary", False, str(e))

    try:
        from log_ingestor import _resolve_patterns
        patterns = _resolve_patterns(PROJECT / "tools" / "knowledge")
        kinds = {p["kind"] for p in patterns}
        check(f"LogIngestor patterns ({len(patterns)} kinds: {sorted(kinds)[:5]}...)", len(patterns) >= 9)
    except Exception as e:
        check("LogIngestor patterns", False, str(e))

    # ---- 4. 端到端流程测试 ----
    print("\n🔄 端到端流程")

    if fl and fl.faults:
        # 主打场景: 模式切换致摔倒 (中英文混合描述)
        result = fl.match_keywords("站立状态下突然摔倒 JOINT_DEFAULT 位控模式")
        if result:
            check(f"FaultLibrary.match_keywords('站立摔倒') → {result[0].rule.id}", True)
        else:
            check("FaultLibrary.match_keywords", False, "未匹配")

        # 英文日志关键词
        result_en = fl.match_keywords("motor overtemp warning, joint thermal shutdown")
        if result_en:
            check(f"FaultLibrary.match_keywords(EN overtemp) → {result_en[0].rule.id}", True)
        else:
            check("FaultLibrary.match_keywords (EN)", False, "未匹配")

        # 时序因果
        fake_events = [
            {"kind": "log.mode_transition", "epoch_ns": 1714819102588000000,
             "payload": {"text": "JOINT_DEFAULT"}, "source_file": "test", "ts": "10:38:22"},
            {"kind": "log.falling_event", "epoch_ns": 1714819103778000000,
             "payload": {"text": "Detect Falling"}, "source_file": "test", "ts": "10:38:23.778"},
        ]
        timeline = fl.match_timeline(fake_events)
        check(f"FaultLibrary.match_timeline() → {len(timeline)} causal chains", len(timeline) >= 1)

    # ---- 5. 经验库功能 (子进程会初始化 data/ 下的分片与索引) ----
    print("\n📊 经验库功能")
    try:
        r = subprocess.run([sys.executable, str(PROJECT / "tools" / "experience_manager.py"), "stats"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT))
        check("experience_manager stats", r.returncode == 0, r.stderr.strip()[:120])
    except Exception as e:
        check("experience_manager stats", False, str(e))

    try:
        r = subprocess.run([sys.executable, str(PROJECT / "tools" / "experience_manager.py"), "search", "摔倒"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT))
        check("experience_manager search '摔倒'", r.returncode == 0, r.stderr.strip()[:120])
    except Exception as e:
        check("experience_manager search", False, str(e))

    # ---- 6. 归档面板 ----
    print("\n📋 归档面板")
    try:
        r = subprocess.run([sys.executable, str(PROJECT / "tools" / "session_archiver.py"), "dashboard"],
                           capture_output=True, text=True, timeout=30, cwd=str(PROJECT))
        check("session_archiver dashboard", r.returncode == 0, r.stderr.strip()[:120])
    except Exception as e:
        check("session_archiver dashboard", False, str(e))

    # ---- 7. 数据文件 (经过上面的功能调用后应已初始化) ----
    print("\n💾 数据文件")
    arch_dir = data_dir() / "archive"
    shards_dir = data_dir() / "experience_shards"

    if (data_dir() / "experience_index.json").exists():
        idx = json.loads((data_dir() / "experience_index.json").read_text(encoding="utf-8"))
        total = idx.get("stats", {}).get("total", 0)
        shards = list(shards_dir.glob("shard_*.json")) if shards_dir.exists() else []
        print(f"  经验库: {total} 条经验, {len(shards)} 个分片")
    if arch_dir.exists():
        arch_files = [f for f in arch_dir.glob("*.json") if f.name != "index.json"]
        print(f"  归档: {len(arch_files)} 条记录")

    # ---- 8. 导入工具 ----
    print("\n📥 导入工具")
    check("import_tool.py (GUI)", (PROJECT / "tools" / "import_tool.py").exists())

    # ---- 总结 ----
    print("\n" + "=" * 60)
    if errors:
        print(f"❌ {len(errors)} 项失败:")
        for e in errors:
            print(f"   - {e}")
    else:
        print("✅ 全部验证通过！诊断助手就绪。")
    print("=" * 60)

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    run()
