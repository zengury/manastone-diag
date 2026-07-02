"""
diagnostic_orchestrator.py — 三轮审查诊断法流程编排器
========================================================

用途: 状态机管控 X2 故障诊断的三轮流程, 确保每轮不跳步、上下文不溢出、
      中间产物可查验、支持中断恢复。

设计:
  - 不作为主控, 而是 LLM 各轮调用的"流程辅助"。
  - 每轮调用:
      1) 验证上轮门禁 (gate check)
      2) 输出本轮检查清单 (checklist)
      3) 验证本轮产出 (validate)
      4) 保存 checkpoint (中断恢复)

用法 (被 LLM 通过 pi 调用):
    # 第一轮前: 初始化 session
    python -m tools.diagnostic_orchestrator init --session X2EXAMPLE00001

    # 每轮开始: 检查门禁 + 获取检查清单
    python -m tools.diagnostic_orchestrator round 1 --session X2EXAMPLE00001

    # 每轮结束: 验证产出 + 写入 checkpoint
    python -m tools.diagnostic_orchestrator validate 1 --session X2EXAMPLE00001

    # 查看状态
    python -m tools.diagnostic_orchestrator status --session X2EXAMPLE00001
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import data_dir as _root_data_dir

# ---- 三轮定义 ----

ROUNDS = {
    1: {
        "name": "数据采集",
        "description": "运行 LogIngestor + McapReader, 产出结构化事件流",
        "gate_requires": [],  # 无前置门禁
        "checklist": [
            "解压日志包 (tar xf)",
            "运行 LogIngestor: python3 -m tools.log_ingestor <log_dir> --robot agibot_x2 --output <out_dir>",
            "读取 session.summary.json 确认事件数 > 0",
            "如 joint.* 数据不足, 运行 McapReader 回放 MCAP bag",
            "读取 coverage.report.md 确认 topic 覆盖度",
            "输出数据报告 (列出发现 + 缺口)",
        ],
        "deliverables": [
            "{output_dir}/session.summary.json",
            "{output_dir}/coverage.report.md",
            "{output_dir}/stats.json",
        ],
        "validate_hint": "确认 summary.json 有 falling_event / mode_transition 等关键事件",
    },
    2: {
        "name": "诊断分析",
        "description": "FaultLibrary 匹配 + 领域技能参考 + 证据链推导",
        "gate_requires": [
            "{output_dir}/session.summary.json",  # 必须存在
        ],
        "checklist": [
            "用 FaultLibrary.match_keywords() 做用户描述的症状关键词匹配",
            "用 FaultLibrary.match_logs() 对 summary.json 中的 log_text 事件做匹配",
            "用 FaultLibrary.match_timeline() 做时序因果推理",
            "参考 .pi/skills/ 中相关技能的诊断方法",
            "对每条候选故障, 建立证据链: 症状 → 日志证据 → 因果链 → 置信度",
            "标注不确定项 (哪些环节证据不足)",
            "输出诊断草案 (含置信度、证据链、不确定项)",
        ],
        "deliverables": [
            "{output_dir}/diagnosis_draft.json",
        ],
        "validate_hint": "确认诊断草案至少包含 1 条候选故障 + 每条有置信度和证据链",
    },
    3: {
        "name": "审核报告",
        "description": "反向审查 + 盲区检查 + 现场反馈对照",
        "gate_requires": [
            "{output_dir}/diagnosis_draft.json",
        ],
        "checklist": [
            "反向审查: 每个结论如果错了最可能漏了什么？",
            "读取 knowledge/capability_boundary.yaml 标注盲区",
            "如有可能, 对照现场工程师反馈逐条确认",
            "用 FaultLibrary 查每个候选故障的 repair_guide",
            "生成最终诊断报告 (Markdown)",
        ],
        "deliverables": [
            "{output_dir}/diagnosis_report.md",
        ],
        "validate_hint": "确认报告包含诊断结论/时间线/证据明细/安全建议/审核备注",
    },
}


# ---- Session 数据模型 ----

@dataclass
class SessionState:
    session_id: str
    current_round: int = 0
    rounds_completed: list[int] = field(default_factory=list)
    log_dir: str = ""
    output_dir: str = ""
    robot_id: str = "agibot_x2"
    created_at: str = ""
    updated_at: str = ""
    checkpoints: dict = field(default_factory=dict)


# ---- 状态持久化 ----

def _state_path(session_id: str) -> Path:
    return _root_data_dir() / "sessions" / session_id / "state.json"


def load_state(session_id: str) -> SessionState:
    sp = _state_path(session_id)
    if sp.exists():
        raw = json.loads(sp.read_text(encoding="utf-8"))
        return SessionState(**raw)
    return SessionState(session_id=session_id)


def save_state(state: SessionState) -> None:
    sp = _state_path(state.session_id)
    sp.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = datetime.now().isoformat()
    sp.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2),
                  encoding="utf-8")


# ---- CLI actions ----

def cmd_init(args):
    """初始化诊断 session。"""
    state = SessionState(
        session_id=args.session,
        current_round=0,
        log_dir=args.log_dir or "",
        output_dir=args.output or str(_root_data_dir() / "sessions" / args.session / "output"),
        robot_id=args.robot or "agibot_x2",
        created_at=datetime.now().isoformat(),
    )
    save_state(state)

    # 创建输出目录
    Path(state.output_dir).mkdir(parents=True, exist_ok=True)

    print(f"✅ Session {args.session} 已初始化")
    print(f"   输出目录: {state.output_dir}")
    print(f"   机器人:   {state.robot_id}")
    print(f"   ──")
    print(f"   下一步:   orchestrator round 1 --session {args.session}")


def cmd_round(args):
    """进入指定轮: 检查门禁, 输出检查清单。"""
    state = load_state(args.session)
    round_num = args.round_num

    round_def = ROUNDS.get(round_num)
    if round_def is None:
        print(f"❌ 无效的轮次: {round_num} (支持 1-3)")
        sys.exit(1)

    # ---- 门禁检查 ----
    output_dir = state.output_dir
    for req_pattern in round_def["gate_requires"]:
        req = req_pattern.format(output_dir=output_dir)
        if not Path(req).exists():
            print(f"🚫 门禁未通过: 缺少 {req}")
            completed = state.rounds_completed
            print(f"   已完成轮次: {completed}")
            print(f"   提示: 先完成第 {round_num - 1} 轮再尝试")
            sys.exit(1)

    # ---- 输出检查清单 ----
    print(f"━━━ 第 {round_num} 轮: {round_def['name']} ━━━")
    print(f"描述: {round_def['description']}")
    print()
    print("检查清单:")
    for i, item in enumerate(round_def["checklist"], 1):
        print(f"  [{i}] {item}")
    print()
    print(f"产出物:")
    for d in round_def["deliverables"]:
        print(f"  → {d.format(output_dir=output_dir)}")
    print()
    print(f"验证提示: {round_def['validate_hint']}")
    print()
    print(f"完成后运行: orchestrator validate {round_num} --session {args.session}")

    # 更新状态
    state.current_round = round_num
    save_state(state)


def cmd_validate(args):
    """验证本轮产出, 写入 checkpoint, 标记完成。"""
    state = load_state(args.session)
    round_num = args.round_num

    round_def = ROUNDS.get(round_num)
    if round_def is None:
        print(f"❌ 无效的轮次: {round_num}")
        sys.exit(1)

    output_dir = state.output_dir
    missing = []
    present = []
    for d in round_def["deliverables"]:
        dp = d.format(output_dir=output_dir)
        if Path(dp).exists():
            present.append(dp)
        else:
            missing.append(dp)

    if missing:
        print(f"⚠️  第 {round_num} 轮产出不全:")
        for m in missing:
            print(f"   ✗ {m}")
        print()
        print(f"已存在的产出:")
        for p in present:
            print(f"   ✓ {p}")
        print()
        print("提示: 完成上述文件后重新运行 validate")
        sys.exit(1)

    # 全部产出存在 → 通过
    checkpoint = {
        "round": round_num,
        "validated_at": datetime.now().isoformat(),
        "deliverables": present,
        "notes": args.note or "",
    }
    if round_num not in state.rounds_completed:
        state.rounds_completed.append(round_num)
    state.checkpoints[str(round_num)] = checkpoint
    save_state(state)

    print(f"✅ 第 {round_num} 轮验证通过!")
    for p in present:
        print(f"   ✓ {p}")

    if round_num < 3:
        print(f"   ──")
        print(f"   下一步: orchestrator round {round_num + 1} --session {args.session}")
    else:
        print(f"   ──")
        print(f"   🎉 三轮诊断完成! 最终报告: {output_dir}/diagnosis_report.md")


def cmd_status(args):
    """查看当前 session 诊断进度。"""
    state = load_state(args.session)

    print(f"Session: {state.session_id}")
    print(f"机器人:  {state.robot_id}")
    print(f"创建于:  {state.created_at}")
    print(f"当前轮:  {state.current_round or '未开始'}")
    print(f"已完成:  {state.rounds_completed or '无'}")
    print(f"输出目录: {state.output_dir}")
    print()

    for r in [1, 2, 3]:
        rd = ROUNDS[r]
        marker = "✅" if r in state.rounds_completed else ("⏳" if r == state.current_round else "⬜")
        print(f"  {marker} 第{r}轮: {rd['name']}")
        cp = state.checkpoints.get(str(r))
        if cp:
            for d in cp.get("deliverables", []):
                print(f"       ✓ {d}")


# ---- CLI entry ----

def main():
    ap = argparse.ArgumentParser(description="manastone-diag 诊断流程编排器")
    sub = ap.add_subparsers(dest="cmd")

    # init
    p_init = sub.add_parser("init", help="初始化诊断 session")
    p_init.add_argument("--session", required=True)
    p_init.add_argument("--log-dir")
    p_init.add_argument("--output")
    p_init.add_argument("--robot", default="agibot_x2")

    # round
    p_round = sub.add_parser("round", help="进入诊断轮次")
    p_round.add_argument("round_num", type=int, choices=[1, 2, 3])
    p_round.add_argument("--session", required=True)

    # validate
    p_val = sub.add_parser("validate", help="验证本轮产出")
    p_val.add_argument("round_num", type=int, choices=[1, 2, 3])
    p_val.add_argument("--session", required=True)
    p_val.add_argument("--note")

    # status
    p_status = sub.add_parser("status", help="查看诊断进度")
    p_status.add_argument("--session", required=True)

    args = ap.parse_args()

    if args.cmd == "init":
        cmd_init(args)
    elif args.cmd == "round":
        cmd_round(args)
    elif args.cmd == "validate":
        cmd_validate(args)
    elif args.cmd == "status":
        cmd_status(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
