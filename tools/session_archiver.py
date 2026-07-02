"""
session_archiver.py — 诊断结果归档与反馈闭环
================================================

用途: 将完成诊断的 session 结构化归档, 从确认的案例中自动提取
      经验并生成 SKILL.md 草稿, 形成知识库持续增长的闭环。

三分归档产出:
  1. archive/YYYY-MM-DD-<session_id>.json — 结构化案例记录
  2. archive/index.json — 全局案例索引 (可搜索)
  3. .pi/skills/auto-<name>.md (草稿) — 提取的诊断经验, 运维确认后入库

用法:
    # 归档已完成的诊断
    python -m tools.session_archiver archive --session X220028C4Z0079 \\
        --report diagnosis_report.md --root-cause "遥控器误操作触发JOINT_DEFAULT" \\
        --fault-ids X2-FK-302

    # 从确认案例生成技能草稿
    python -m tools.session_archiver extract-skill --session X220028C4Z0079

    # 搜索历史案例
    python -m tools.session_archiver search "关节过热"

    # 列出全部归档案例
    python -m tools.session_archiver list
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import data_dir as _root_data_dir


# ---- 路径工具 ----

def _archive_dir() -> Path:
    return _root_data_dir() / "archive"


def _index_path() -> Path:
    return _archive_dir() / "index.json"


def _skills_dir() -> Path:
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / ".pi" / "skills"
        if candidate.is_dir():
            return candidate
    return _root_data_dir() / "skill_drafts"


# ---- 数据模型 ----

@dataclass
class ArchivedSession:
    session_id: str


# ---- 加载/保存 ----

def load_index() -> dict:
    ip = _index_path()
    if ip.exists():
        return json.loads(ip.read_text(encoding="utf-8"))
    return {"sessions": [], "last_updated": ""}


def save_index(idx: dict):
    _archive_dir().mkdir(parents=True, exist_ok=True)
    idx["last_updated"] = datetime.now().isoformat()
    _index_path().write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- CLI actions ----

def cmd_archive(args):
    """归档一个已完成的诊断 session。"""
    session_id = args.session

    # 从 orchestrator session state 读基本信息
    state_path = Path.home() / ".manastone-diag" / "sessions" / session_id / "state.json"
    robot_id = "agibot_x2"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        robot_id = state.get("robot_id", robot_id)

    # 读诊断报告 (尝试提取关键信息)
    report_path = Path(args.report)
    report_text = ""
    if report_path.exists():
        report_text = report_path.read_text(encoding="utf-8", errors="replace")

    # 从报告中自动提取症状描述 (简单启发式)
    symptoms = _extract_symptoms(report_text)

    # 构建归档记录
    record = ArchivedSession(
        session_id=session_id,
        robot_id=robot_id,
        archived_at=datetime.now().isoformat(),
        fault_time=args.fault_time or "",
        root_cause=args.root_cause or "",
        root_cause_detail=args.root_cause_detail or "",
        fault_ids=args.fault_ids or [],
        severity=args.severity or "WARNING",
        confidence=args.confidence or 0,
        symptoms=symptoms,
        repair_actions=args.repair_actions or [],
        lessons_learned=args.lessons or "",
        capability_blindspots=args.blindspots or [],
        source_report=str(report_path.resolve()),
        tags=args.tags or [],
    )

    # 写出归档文件
    _archive_dir().mkdir(parents=True, exist_ok=True)
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    archive_file = _archive_dir() / f"{date_prefix}-{session_id}.json"
    archive_file.write_text(
        json.dumps(asdict(record), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 更新索引
    idx = load_index()
    idx["sessions"].append({
        "session_id": session_id,
        "archived_at": record.archived_at,
        "robot_id": record.robot_id,
        "root_cause": record.root_cause[:120],
        "fault_ids": record.fault_ids,
        "severity": record.severity,
        "confidence": record.confidence,
        "tags": record.tags,
        "archive_file": str(archive_file),
    })
    save_index(idx)

    print(f"✅ 案例已归档: {archive_file}")
    print(f"   根因: {record.root_cause}")
    print(f"   关联故障: {record.fault_ids}")
    print(f"   ──")
    print(f"   下一步: archiver extract-skill --session {session_id}")


def cmd_extract_skill(args):
    """从归档案例自动生成 SKILL.md 草稿。"""
    session_id = args.session

    # 找归档文件
    idx = load_index()
    entry = None
    for e in idx.get("sessions", []):
        if e["session_id"] == session_id:
            entry = e
            break
    if entry is None:
        print(f"❌ 未找到 session {session_id} 的归档记录")
        sys.exit(1)

    archive_file = Path(entry["archive_file"])
    if not archive_file.exists():
        print(f"❌ 归档文件不存在: {archive_file}")
        sys.exit(1)

    record = json.loads(archive_file.read_text(encoding="utf-8"))

    # 生成技能名
    skill_slug = re.sub(r"[^a-z0-9]+", "-", record["root_cause"][:50].lower()).strip("-")
    if not skill_slug:
        skill_slug = f"case-{session_id.lower()}"

    # 生成 SKILL.md 内容
    root_cause = record.get("root_cause", "未知")
    detail = record.get("root_cause_detail", "")
    symptoms = record.get("symptoms", [])
    fault_ids = record.get("fault_ids", [])
    lessons = record.get("lessons_learned", "")
    repair = record.get("repair_actions", [])

    skill_md = f"""---
id: auto-{skill_slug}
name: {root_cause[:60]}
description: 自动生成的诊断技能 — 来自案例 {session_id}
layer: instance/x2
category: auto-generated
severity: {record.get('severity', 'WARNING').lower()}
version: 0.1.0
author: manastone-diag session archiver
auto_generated: true
source_session: {session_id}
---

# Skill: {root_cause}

> ⚠️ 本技能由 session_archiver 自动生成。请运维工程师审核后移除 `auto_generated: true`。

## 触发条件

"""
    for s in symptoms:
        skill_md += f"- {s}\n"

    skill_md += f"""
## 诊断步骤

1. 检查日志中是否存在模式切换事件 (特别是 JOINT_DEFAULT / SetMcAction)
2. 运行 FaultLibrary 关键词匹配: 关注故障 ID {fault_ids}
3. 检查时序因果: 切换后短时间内是否出现摔倒/异常事件
4. 反向排查: 排除其他并发故障 (如 EtherCAT 崩溃)

## 根因

{root_cause}

"""
    if detail:
        skill_md += f"{detail}\n\n"

    skill_md += f"""## 关联故障规则

"""
    for fid in fault_ids:
        skill_md += f"- `{fid}`\n"

    skill_md += f"""
## 处理方案

"""
    if repair:
        skill_md += "### 立即\n"
        for r in repair[:3]:
            skill_md += f"- {r}\n"
        skill_md += "\n### 长期\n"
        skill_md += "- 定期审查模式切换安全门逻辑\n"

    if lessons:
        skill_md += f"""
## 经验教训

{lessons}
"""

    skill_md += f"""
## 参考

- 诊断报告: {record.get('source_report', '')}
- 归档记录: {archive_file}
- 案例 ID: {session_id}
"""

    # 写出到 skills 目录
    out_dir = _skills_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"auto-{skill_slug}.md"
    out_file.write_text(skill_md, encoding="utf-8")

    print(f"✅ 技能草稿已生成: {out_file}")
    print(f"   请审核后执行:")
    print(f"   1. 检查触发条件是否准确")
    print(f"   2. 补充诊断步骤中的具体命令")
    print(f"   3. 确认后移除 YAML frontmatter 中的 auto_generated: true")


def cmd_search(args):
    """搜索历史归档案例。"""
    idx = load_index()
    query = args.query.lower()
    results = []
    for e in idx.get("sessions", []):
        text = json.dumps(e, ensure_ascii=False).lower()
        if query in text:
            results.append(e)
        elif any(query in t.lower() for t in e.get("tags", [])):
            results.append(e)

    if not results:
        print(f"未找到匹配 '{args.query}' 的案例")
        return

    print(f"找到 {len(results)} 条匹配 '{args.query}':")
    print()
    for r in results:
        print(f"  📋 {r['session_id']}")
        print(f"     根因: {r.get('root_cause', '?')[:100]}")
        print(f"     故障ID: {r.get('fault_ids', [])}")
        print(f"     严重度: {r.get('severity', '?')}  置信度: {r.get('confidence', '?')}/10")
        print(f"     归档: {r.get('archived_at', '?')}")
        print()


def cmd_list(args):
    """列出全部归档案例。"""
    idx = load_index()
    sessions = idx.get("sessions", [])
    if not sessions:
        print("暂无归档案例")
        return

    # 统计验证状态
    verified_count = sum(1 for s in sessions if s.get("verified"))
    unverified_count = len(sessions) - verified_count

    print(f"共 {len(sessions)} 个归档案例 ({verified_count} 已验证, {unverified_count} 待验证):")
    print()
    for e in sorted(sessions, key=lambda x: x.get("archived_at", ""), reverse=True):
        vmark = "✅" if e.get("verified") else "⬜"
        result_tag = ""
        if e.get("was_correct"):
            result_tag = {"correct": "✓正确", "partial": "⚠部分", "wrong": "✗错误"}.get(e.get("was_correct"), "")
        print(f"  {vmark} [{e.get('severity', '?')}] {e['session_id']}  {result_tag}")
        print(f"        {e.get('root_cause', '?')[:90]}")
        print(f"        {e.get('fault_ids', [])}")
        print()


def cmd_pending(args):
    """列出全部未验证的诊断案例，用于跨会话反馈。"""
    idx = load_index()
    sessions = idx.get("sessions", [])
    unverified = [s for s in sessions if not s.get("verified")]

    if not unverified:
        print("✅ 所有诊断案例均已验证，无待处理项。")
        return

    # 按时间倒序，最新的在前（最可能需要验证的）
    unverified.sort(key=lambda x: x.get("archived_at", ""), reverse=True)

    print(f"📋 有 {len(unverified)} 个诊断等待实地验证:")
    print()
    for i, e in enumerate(unverified, 1):
        days_ago = ""
        try:
            archived = datetime.fromisoformat(e.get("archived_at", ""))
            delta = datetime.now() - archived
            if delta.days > 0:
                days_ago = f" ({delta.days}天前)"
            else:
                hours = delta.seconds // 3600
                days_ago = f" ({hours}小时前)" if hours > 0 else " (刚刚)"
        except Exception:
            pass

        print(f"  [{i}] {e['session_id']}{days_ago}")
        print(f"      AI 诊断: {e.get('root_cause', '?')[:100]}")
        print(f"      故障ID:  {e.get('fault_ids', [])}")
        print(f"      置信度:  {e.get('confidence', '?')}/10")
        print()

    print("验证方式（在对话中直接说）:")
    print('  "验证 [序号]，诊断正确"')
    print('  "验证 [序号]，不对，实际是 EtherCAT 线缆松动"')
    print("  或直接说 session ID: X220028C4Z0079 验证结果 correct")


def cmd_sync(args):
    """清理索引中的无效条目（手动删除 .json 文件但索引未更新时使用）。"""
    idx = load_index()
    sessions = idx.get("sessions", [])
    removed = 0
    valid = []
    for s in sessions:
        archive_file = s.get("archive_file", "")
        if archive_file and Path(archive_file).exists():
            valid.append(s)
        else:
            print(f"  🗑 移除无效条目: {s.get('session_id', '?')}")
            removed += 1
    idx["sessions"] = valid
    save_index(idx)
    print(f"✅ 同步完成: 移除 {removed} 条无效记录, 保留 {len(valid)} 条。")


def cmd_stats(args):
    """统计每条故障规则的验证准确率。"""
    idx = load_index()
    sessions = idx.get("sessions", [])
    verified = [s for s in sessions if s.get("verified")]

    if not verified:
        print("暂无已验证的诊断记录，无法统计。")
        return

    rule_stats: dict[str, dict] = {}
    for s in verified:
        for fid in s.get("fault_ids", []):
            if fid not in rule_stats:
                rule_stats[fid] = {"total": 0, "correct": 0, "partial": 0, "wrong": 0, "sessions": []}
            rule_stats[fid]["total"] += 1
            wc = s.get("was_correct", "")
            if wc == "correct":
                rule_stats[fid]["correct"] += 1
            elif wc == "partial":
                rule_stats[fid]["partial"] += 1
            elif wc == "wrong":
                rule_stats[fid]["wrong"] += 1
            rule_stats[fid]["sessions"].append(s["session_id"])

    print(f"📊 故障规则准确率统计 (基于 {len(verified)} 条已验证记录):")
    print()
    for fid in sorted(rule_stats.keys()):
        rs = rule_stats[fid]
        accuracy = rs["correct"] / rs["total"] * 100 if rs["total"] > 0 else 0
        bar = "█" * int(accuracy / 10) + "░" * (10 - int(accuracy / 10))
        status = "🟢 高" if accuracy >= 80 else ("🟡 中" if accuracy >= 50 else "🔴 低")
        print(f"  {fid}: {bar} {accuracy:.0f}% {status}")
        print(f"     正确:{rs['correct']}  部分:{rs['partial']}  错误:{rs['wrong']}  总计:{rs['total']}")
        if rs["wrong"] > 0:
            print(f"     ⚠️ 错误案例: {', '.join(rs['sessions'][-3:])}")
        print()


def cmd_export_conversation(args):
    """保存完整诊断对话记录到 data/records/<SN>.json。

    如果通过 --content 传入了对话内容则直接写入，
    否则创建占位文件提示用户手动填充。
    """
    session_id = args.session
    records_dir = _archive_dir().parent / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    out_path = records_dir / f"{session_id}.json"

    if args.content:
        # 直接写入传入的对话内容
        try:
            conversation = json.loads(args.content)
        except json.JSONDecodeError:
            conversation = {"session_id": session_id, "raw_text": args.content}

        conversation["session_id"] = session_id
        conversation["exported_at"] = datetime.now().isoformat()
        out_path.write_text(json.dumps(conversation, ensure_ascii=False, indent=2), encoding="utf-8")
        msg_count = len(conversation.get("messages", [])) or len(conversation.get("raw_text", "").split("\n")) or 1
        print(f"✅ 对话记录已保存: {out_path}")
        print(f"   约 {msg_count} 条消息")
        return

    # 没有内容时创建占位文件
    if out_path.exists():
        print(f"⚠️ 对话记录已存在: {out_path}")
        return

    placeholder = {
        "session_id": session_id,
        "exported_at": datetime.now().isoformat(),
        "note": "agent 将在下次诊断时自动填充实际对话内容。",
        "messages": [],
    }
    out_path.write_text(json.dumps(placeholder, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📝 对话记录占位已创建: {out_path}")


def cmd_export_skill(args):
    """将 skill draft 导出到指定路径 (用于手动审查后合并)。"""
    session_id = args.session
    idx = load_index()
    # 找对应的 skill draft
    out_dir = _skills_dir()
    for f in out_dir.glob(f"auto-*"):
        text = f.read_text(encoding="utf-8")
        if f"source_session: {session_id}" in text:
            dest = args.output or str(f)
            print(f"Skill draft: {f}")
            print(f"文件大小:   {len(text)} 字符")
            if args.output:
                Path(args.output).write_text(text, encoding="utf-8")
                print(f"已导出到:   {args.output}")
            return
    print(f"❌ 未找到 session {session_id} 的技能草稿")


# ---- dashboard: 归档记录可视化面板 ----

def cmd_dashboard(args):
    """生成归档记录可视化 HTML 面板。"""
    idx = load_index()
    sessions = idx.get("sessions", [])
    if not sessions:
        print("暂无归档案例，无法生成面板。")
        return

    sessions_sorted = sorted(sessions, key=lambda x: x.get("archived_at", ""), reverse=True)

    # 统计
    total = len(sessions_sorted)
    verified = sum(1 for s in sessions_sorted if s.get("verified"))
    correct = sum(1 for s in sessions_sorted if s.get("was_correct") == "correct")
    wrong = sum(1 for s in sessions_sorted if s.get("was_correct") == "wrong")
    partial = sum(1 for s in sessions_sorted if s.get("was_correct") == "partial")
    unverified = total - verified

    rows_html = ""
    for s in sessions_sorted:
        sid = s.get("session_id", "?")
        archived = s.get("archived_at", "")[:16].replace("T", " ")
        root_cause = (s.get("root_cause") or "?")[:80]
        fault_ids = s.get("fault_ids", [])
        sev = s.get("severity", "?")
        conf = s.get("confidence", 0)
        verified_flag = s.get("verified", False)
        was_correct = s.get("was_correct", "")
        actual = (s.get("actual_root_cause") or "")[:80]

        # 状态图标
        if not verified_flag:
            icon = "⬜"
            status_class = "unverified"
            status_text = "待验证"
        elif was_correct == "correct":
            icon = "✅"
            status_class = "correct"
            status_text = "诊断正确"
        elif was_correct == "partial":
            icon = "⚠️"
            status_class = "partial"
            status_text = "部分正确"
        elif was_correct == "wrong":
            icon = "❌"
            status_class = "wrong"
            status_text = "诊断错误"
        else:
            icon = "✅"
            status_class = "verified"
            status_text = "已验证"

        sev_class = "sev-critical" if sev == "CRITICAL" else "sev-warning" if sev == "WARNING" else "sev-notice"

        # 从 session_id 提取 SN（取第一部分）
        sn = sid.split("_")[0] if "_" in sid else sid[:16]

        # 操作按钮 + 对话记录链接
        verify_btn = ""
        record_link = ""
        records_dir = _archive_dir().parent / "records"
        html_file = records_dir / f"{sid}_full.html"
        jsonl_file = records_dir / f"{sid}_full.jsonl"
        json_file = records_dir / f"{sid}.json"
        # 优先 HTML 可读版
        if html_file.exists():
            record_link = f'<a href="file:///{html_file}" class="btn" style="background:#1f6feb;color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:11px;">📄 完整对话</a>'
        elif jsonl_file.exists():
            record_link = f'<a href="file:///{jsonl_file}" class="btn" style="background:#1f6feb;color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:11px;">📄 对话</a>'
        elif json_file.exists():
            record_link = f'<a href="file:///{json_file}" class="btn" style="background:#1f6feb;color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:11px;">📄 对话</a>'

        if not verified_flag:
            verify_btn = f'''
            <button class="btn btn-verify" onclick="copyVerify('{sid}')">✓ 验证</button>
            <button class="btn btn-wrong" onclick="copyWrong('{sid}')">✗ 纠错</button>
            '''

        rows_html += f'''
        <tr class="{status_class}">
            <td class="icon-cell">{icon}</td>
            <td><strong>{sn}</strong></td>
            <td class="desc-cell">{root_cause}</td>
            <td>{archived}</td>
            <td><span class="{sev_class}">{sev}</span></td>
            <td>{conf}/10</td>
            <td><span class="status-{status_class}">{status_text}</span></td>
            <td class="action-cell">{verify_btn} {record_link}</td>
        </tr>
        '''

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Manastone 诊断归档面板</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background:#0d1117; color:#c9d1d9; padding:24px; }}
h1 {{ font-size:24px; margin-bottom:8px; color:#f0f6fc; }}
.subtitle {{ color:#8b949e; margin-bottom:24px; }}
.stats {{ display:flex; gap:16px; margin-bottom:24px; flex-wrap:wrap; }}
.stat {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px 24px; text-align:center; min-width:100px; }}
.stat .num {{ font-size:28px; font-weight:700; }}
.stat .label {{ font-size:12px; color:#8b949e; margin-top:4px; }}
.stat.correct .num {{ color:#3fb950; }}
.stat.wrong .num {{ color:#f85149; }}
.stat.partial .num {{ color:#d29922; }}
.stat.unverified .num {{ color:#8b949e; }}

table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ text-align:left; padding:12px 10px; border-bottom:1px solid #30363d; color:#8b949e; font-weight:600; position:sticky; top:0; background:#0d1117; }}
td {{ padding:10px; border-bottom:1px solid #21262d; }}
tr:hover {{ background:#161b22; }}
tr.correct {{ border-left:3px solid #3fb950; }}
tr.partial {{ border-left:3px solid #d29922; }}
tr.wrong {{ border-left:3px solid #f85149; }}
tr.unverified {{ border-left:3px solid #8b949e; }}
tr.verified {{ border-left:3px solid #58a6ff; }}
.icon-cell {{ font-size:18px; text-align:center; width:40px; }}
.desc-cell {{ max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.action-cell {{ white-space:nowrap; }}

.sev-critical {{ background:#f8514922; color:#f85149; padding:2px 8px; border-radius:4px; font-weight:600; font-size:11px; }}
.sev-warning {{ background:#d2992222; color:#d29922; padding:2px 8px; border-radius:4px; font-weight:600; font-size:11px; }}
.sev-notice {{ background:#58a6ff22; color:#58a6ff; padding:2px 8px; border-radius:4px; font-size:11px; }}

.status-correct {{ color:#3fb950; }}
.status-partial {{ color:#d29922; }}
.status-wrong {{ color:#f85149; }}
.status-unverified {{ color:#8b949e; }}

.btn {{ border:none; border-radius:4px; padding:4px 10px; font-size:11px; cursor:pointer; margin:1px; }}
.btn-verify {{ background:#238636; color:#fff; }}
.btn-verify:hover {{ background:#2ea043; }}
.btn-wrong {{ background:#da3633; color:#fff; }}
.btn-wrong:hover {{ background:#f85149; }}
.toast {{ position:fixed; bottom:20px; right:20px; background:#238636; color:#fff; padding:12px 20px; border-radius:8px; font-size:14px; opacity:0; transition:opacity .3s; z-index:999; }}
.toast.show {{ opacity:1; }}
.filters {{ margin-bottom:16px; display:flex; gap:8px; }}
.filter-btn {{ background:#21262d; border:1px solid #30363d; color:#c9d1d9; padding:6px 14px; border-radius:6px; cursor:pointer; font-size:13px; }}
.filter-btn.active {{ background:#1f6feb; border-color:#1f6feb; }}
</style>
</head>
<body>
<h1>📋 Manastone 诊断归档面板</h1>
<p class="subtitle">共 {total} 条记录 · 最后更新: {idx.get("last_updated", "?")[:16]}</p>

<div class="stats">
    <div class="stat unverified"><div class="num">{unverified}</div><div class="label">待验证</div></div>
    <div class="stat correct"><div class="num">{correct}</div><div class="label">诊断正确</div></div>
    <div class="stat partial"><div class="num">{partial}</div><div class="label">部分正确</div></div>
    <div class="stat wrong"><div class="num">{wrong}</div><div class="label">诊断错误</div></div>
</div>

<div class="filters">
    <button class="filter-btn active" onclick="filterTable('all', this)">全部</button>
    <button class="filter-btn" onclick="filterTable('unverified', this)">待验证</button>
    <button class="filter-btn" onclick="filterTable('correct', this)">已确认</button>
</div>

<table id="archive-table">
<thead>
<tr>
    <th></th><th>SN</th><th>故障描述</th><th>提交时间</th><th>严重度</th><th>置信度</th><th>状态</th><th>操作</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>

<div class="toast" id="toast"></div>

<script>
function copyVerify(sid) {{
    navigator.clipboard.writeText(sid + ' 验证结果 correct').then(() => showToast('✅ 验证命令已复制，在对话框中粘贴即可'));
}}
function copyWrong(sid) {{
    navigator.clipboard.writeText('验证 ' + sid + ' 诊断错了，实际根因是 ').then(() => showToast('📋 纠错命令已复制，补充实际根因后在对话框中输入'));
}}
function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg; t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
}}
function filterTable(type, btn) {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const rows = document.querySelectorAll('#archive-table tbody tr');
    rows.forEach(r => {{
        if (type === 'all') r.style.display = '';
        else if (type === 'unverified') r.style.display = r.classList.contains('unverified') ? '' : 'none';
        else if (type === 'correct') r.style.display = r.classList.contains('correct') || r.classList.contains('verified') ? '' : 'none';
    }});
}}
</script>
</body>
</html>'''

    out_path = _archive_dir() / "dashboard.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"✅ 归档面板已生成: {out_path}")
    print(f"   共 {total} 条记录 ({verified} 已验证, {unverified} 待验证)")

    # 尝试自动在浏览器打开
    try:
        import webbrowser
        webbrowser.open(str(out_path))
        print(f"   已在浏览器中打开。")
    except Exception:
        print(f"   请手动在浏览器中打开: file:///{out_path}")


# ---- verify: 实地验证反馈 ----

def cmd_verify(args):
    """接受用户实地验证结果，更新归档记录并生成经验优化建议。"""
    session_id = args.session

    # 找归档记录
    idx = load_index()
    entry = None
    entry_idx = None
    for i, e in enumerate(idx.get("sessions", [])):
        if e["session_id"] == session_id:
            entry = e
            entry_idx = i
            break

    if entry is None:
        print(f"❌ 未找到 session {session_id} 的归档记录")
        print(f"   请先运行: archiver archive --session {session_id} ...")
        sys.exit(1)

    archive_file = Path(entry["archive_file"])
    if not archive_file.exists():
        print(f"❌ 归档文件不存在: {archive_file}")
        sys.exit(1)

    record = json.loads(archive_file.read_text(encoding="utf-8"))

    # 更新验证字段
    record["verified"] = True
    record["verified_at"] = datetime.now().isoformat()
    record["was_correct"] = args.result
    record["actual_root_cause"] = args.actual_root_cause or ""
    record["actual_repair"] = args.actual_repair or []
    record["verification_notes"] = args.notes or ""

    archive_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    # 更新索引中的状态
    ai_root = record.get("root_cause", "?")
    ai_fault_ids = record.get("fault_ids", [])
    ai_confidence = record.get("confidence", 0)

    idx["sessions"][entry_idx]["verified"] = True
    idx["sessions"][entry_idx]["was_correct"] = args.result
    save_index(idx)

    # 输出验证总结
    print()
    print("=" * 60)
    print(f"  实地验证结果: {session_id}")
    print("=" * 60)
    print(f"  AI 诊断:     {ai_root[:80]}")
    print(f"  关联故障ID:  {ai_fault_ids}")
    print(f"  AI 置信度:   {ai_confidence}/10")
    print(f"  验证结果:    {_result_label(args.result)}")
    if args.actual_root_cause:
        print(f"  实际根因:    {args.actual_root_cause[:80]}")
    if args.actual_repair:
        print(f"  实际修复:    {', '.join(args.actual_repair[:5])}")
    print()

    # 根据验证结果给出不同的后续建议
    if args.result == "correct":
        _handle_correct(record, ai_fault_ids)
    elif args.result == "partial":
        _handle_partial(record, ai_fault_ids, args.actual_root_cause)
    elif args.result == "wrong":
        _handle_wrong(record, ai_fault_ids, args.actual_root_cause, session_id, args)


def _result_label(result: str) -> str:
    return {"correct": "✅ 诊断正确", "partial": "⚠️ 部分正确", "wrong": "❌ 诊断错误"}.get(result, result)


def _handle_correct(record: dict, fault_ids: list[str]):
    """诊断正确：提升关联故障规则的置信度权重。"""
    print("📈 经验优化建议:")
    print(f"   诊断正确。关联的故障规则 {fault_ids} 置信度应提升。")
    print(f"   建议: 在 knowledge/diagnostic_knowledge.yaml 中将以下规则的")
    print(f"   detection.conditions 标记为 high_confidence: true")
    for fid in fault_ids:
        print(f"     - {fid}")
    print()
    print("   已自动更新归档记录。下次遇到类似症状时，这些规则会被优先匹配。")


def _handle_partial(record: dict, fault_ids: list[str], actual: str):
    """部分正确：AI 方向对但细节错，补充到技能。"""
    ai_root = record.get("root_cause", "")
    print("📝 经验优化建议:")
    print(f"   AI 方向正确但不够精确。")
    print(f"   AI 判断: {ai_root[:100]}")
    print(f"   实际根因: {actual[:100]}")
    print()
    print(f"   建议操作:")
    print(f"   1. 运行 archiver extract-skill --session {record['session_id']}")
    print(f"      生成修正后的技能草稿")
    print(f"   2. 手动编辑草稿，补充实际根因的触发条件和诊断步骤")
    print(f"   3. 审核通过后移除 auto_generated: true")


def _handle_wrong(record: dict, fault_ids: list[str], actual: str, session_id: str, args):
    """诊断错误：生成详细纠偏报告，标记故障规则需要复审。"""
    ai_root = record.get("root_cause", "")
    print("🔧 纠偏报告:")
    print(f"   AI 错误判断: {ai_root[:100]}")
    print(f"   实际根因:    {actual[:100]}")
    print()
    print(f"   标记需要复审的故障规则: {fault_ids}")
    print(f"   这些规则可能:")
    print(f"     - 症状关键词过于宽泛，导致误匹配")
    print(f"     - 缺少关键的排除条件")
    print(f"     - 需要增加时序因果规则来区分")
    print()
    print(f"   建议操作:")
    print(f"   1. 审查 knowledge/diagnostic_knowledge.yaml 中的 {fault_ids}")
    print(f"   2. 检查 symptoms 字段是否与实际症状重叠过多")
    print(f"   3. 如本次是全新故障类型，运行:")
    print(f"      archiver extract-skill --session {session_id}")
    print(f"      手动编写新技能，然后放入 .pi/skills/")
    print(f"   4. 考虑在 knowledge/causal_rules.yaml 中增加排除性因果规则")


# ---- 辅助: 从报告中提取症状 ----

def _extract_symptoms(report_text: str) -> list[str]:
    """从 Markdown 报告中简单提取症状描述。"""
    symptoms = []
    # 找描述性的关键信息
    patterns = [
        r'\u300c([^\u300d]{3,60})\u300d',     # 「...」
        r'\u300e([^\u300f]{3,60})\u300f',     # 『...』
        r'报错[：:\s]*[「\u201c"]([^」\u201d"]{3,60})[」\u201d"]',
        r'症状[：:]\s*(.{3,60}?)(?:\n|$)',
    ]
    for pat in patterns:
        try:
            for m in re.finditer(pat, report_text):
                text = m.group(1).strip()
                if len(text) >= 3 and text not in symptoms:
                    symptoms.append(text)
        except re.error:
            continue
    return symptoms[:10]  # 最多 10 条


def cmd_export_html(args):
    """根据诊断报告 + 归档记录生成可读 HTML 对话记录，供归档面板查看。"""
    session_id = args.session
    records_dir = _archive_dir().parent / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    out_path = records_dir / f"{session_id}_full.html"

    # 读取归档记录
    idx = load_index()
    entry = None
    for e in idx.get("sessions", []):
        if e["session_id"] == session_id:
            entry = e
            break

    root_cause = "?"
    fault_ids = []
    confidence = 0
    severity = "WARNING"
    archived_at = datetime.now().isoformat()
    if entry:
        root_cause = entry.get("root_cause", "?")
        fault_ids = entry.get("fault_ids", [])
        confidence = entry.get("confidence", 0)
        severity = entry.get("severity", "WARNING")
        archived_at = entry.get("archived_at", archived_at)

    # 读取诊断报告
    report_text = ""
    if args.report:
        rp = Path(args.report)
        if rp.exists():
            report_text = rp.read_text(encoding="utf-8", errors="replace")

    symptoms = args.symptoms or "未记录"
    conversation = args.conversation or ""

    # 生成对话记录 HTML 内容
    conv_html = ""
    if conversation:
        conv_html = f'<div class="card"><h2>💬 诊断对话记录</h2><div class="conv">{conversation}</div></div>'

    # 生成 HTML
    fid_tags = " ".join(f'<span class="tag">{f}</span>' for f in fault_ids) if fault_ids else "无"
    sev_class = "crit" if severity == "CRITICAL" else "warn" if severity == "WARNING" else "info"

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>诊断对话 — {session_id}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0d1117; color:#c9d1d9; font-family:'Segoe UI',system-ui,sans-serif; padding:20px; max-width:900px; margin:0 auto; }}
h1 {{ font-size:18px; color:#f0f6fc; margin-bottom:4px; }}
.sub {{ color:#8b949e; font-size:12px; margin-bottom:20px; }}
.card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; margin-bottom:16px; }}
.card h2 {{ font-size:14px; color:#58a6ff; margin-bottom:8px; }}
.card p, .card li {{ font-size:13px; line-height:1.7; }}
.tag {{ display:inline-block; background:#1f6feb22; color:#58a6ff; padding:2px 8px; border-radius:4px; font-size:11px; margin:2px; }}
.sev {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; }}
.sev.crit {{ background:#f8514922; color:#f85149; }}
.sev.warn {{ background:#d2992222; color:#d29922; }}
.sev.info {{ background:#58a6ff22; color:#58a6ff; }}
.section {{ margin-top:16px; }}
.btn {{ border:none; border-radius:4px; padding:6px 14px; font-size:13px; cursor:pointer; margin:4px; }}
.btn-verify {{ background:#238636; color:#fff; }}
.btn-verify:hover {{ background:#2ea043; }}
.btn-wrong {{ background:#da3633; color:#fff; }}
.btn-wrong:hover {{ background:#f85149; }}
.toast {{ position:fixed; bottom:20px; right:20px; background:#238636; color:#fff; padding:12px 20px; border-radius:8px; font-size:14px; opacity:0; transition:opacity .3s; z-index:999; }}
.toast.show {{ opacity:1; }}
.conv {{ font-size:13px; line-height:1.8; white-space:pre-wrap; }}
</style>
</head>
<body>

<h1>📋 诊断对话记录</h1>
<p class="sub">Session: {session_id} · 归档时间: {archived_at[:16].replace("T", " ")}</p>

<div class="card">
    <h2>📌 用户描述</h2>
    <p>{symptoms}</p>
</div>

{conv_html}

<div class="card">
    <h2>🔍 诊断结论</h2>
    <p><strong>根因:</strong> {root_cause}</p>
    <p class="section"><strong>关联故障规则:</strong> {fid_tags}</p>
    <p class="section"><strong>严重度:</strong> <span class="sev {sev_class}">{severity}</span> &nbsp; <strong>置信度:</strong> {confidence}/10</p>
</div>

<div class="card">
    <h2>📊 诊断报告</h2>
    <pre>{report_text[:20000] if report_text else "（未提供诊断报告）"}</pre>
</div>

<div class="card" style="text-align:center;">
    <h2>✅ 现场验证</h2>
    <p style="color:#c9d1d9; margin-bottom:8px;">到机器人现场确认诊断结论后：</p>
    <p style="color:#8b949e; font-size:12px; margin-bottom:12px;">👇 点击按钮复制命令 → 回到 pi 对话框粘贴并发送</p>
    <button class="btn btn-verify" onclick="copyVerify('{session_id}')">✓ 验证正确 — 复制命令</button>
    <button class="btn btn-wrong" onclick="copyWrong('{session_id}')">✗ 诊断有误 — 复制命令</button>
</div>

<div class="toast" id="toast"></div>

<script>
function copyVerify(sid) {{
    navigator.clipboard.writeText(sid + ' 验证结果 correct').then(() => showToast('✅ 验证命令已复制，在对话框中粘贴即可'));
}}
function copyWrong(sid) {{
    navigator.clipboard.writeText('验证 ' + sid + ' 诊断错了，实际根因是 ').then(() => showToast('📋 纠错命令已复制，补充实际根因后在对话框中输入'));
}}
function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg; t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
}}
</script>

<hr>
<p class="footer">manastone-diag · 由 session_archiver.py export-html 生成</p>

</body>
</html>'''

    out_path.write_text(html, encoding="utf-8")
    print(f"✅ 对话 HTML 已生成: {out_path}")
    print(f"   面板中点击 📄 完整对话 即可查看")


# ---- CLI entry ----

def main():
    ap = argparse.ArgumentParser(description="manastone-diag 诊断结果归档器")
    sub = ap.add_subparsers(dest="cmd")

    # archive
    p_archive = sub.add_parser("archive", help="归档完成的诊断案例")
    p_archive.add_argument("--session", required=True)
    p_archive.add_argument("--report", default="")
    p_archive.add_argument("--fault-time", default="")
    p_archive.add_argument("--root-cause", default="")
    p_archive.add_argument("--root-cause-detail", default="")
    p_archive.add_argument("--fault-ids", nargs="*", default=[])
    p_archive.add_argument("--severity", default="WARNING")
    p_archive.add_argument("--confidence", type=int, default=0)
    p_archive.add_argument("--repair-actions", nargs="*", default=[])
    p_archive.add_argument("--lessons", default="")
    p_archive.add_argument("--blindspots", nargs="*", default=[])
    p_archive.add_argument("--tags", nargs="*", default=[])

    # extract-skill
    p_skill = sub.add_parser("extract-skill", help="从归档案例生成 SKILL.md 草稿")
    p_skill.add_argument("--session", required=True)

    # search
    p_search = sub.add_parser("search", help="搜索历史案例")
    p_search.add_argument("query")

    # list
    p_list = sub.add_parser("list", help="列出全部归档案例")

    # pending — 列出待验证诊断
    p_pending = sub.add_parser("pending", help="列出所有未验证的诊断，用于跨会话反馈")

    # dashboard — 生成可视化面板
    p_dash = sub.add_parser("dashboard", help="生成归档记录可视化 HTML 面板")

    # sync — 修复索引
    p_sync = sub.add_parser("sync", help="清理索引中的无效条目（文件已被手动删除但索引未更新）")

    # stats — 规则准确率统计
    p_stats = sub.add_parser("stats", help="统计每条故障规则的验证准确率，用于优化诊断权重")

    # export-skill
    p_export = sub.add_parser("export-skill", help="导出技能草稿")
    p_export.add_argument("--session", required=True)
    p_export.add_argument("--output")

    # export-conversation — 保存完整诊断对话记录
    p_conv = sub.add_parser("export-conversation", help="保存完整的诊断对话记录到 data/records/")
    p_conv.add_argument("--session", required=True)
    p_conv.add_argument("--content", help="对话内容 (JSON 字符串)")

    # export-html — 根据诊断报告 + 症状描述生成可读 HTML 对话记录
    p_html = sub.add_parser("export-html", help="根据诊断报告生成可读 HTML 对话记录 (用于面板中查看)")
    p_html.add_argument("--session", required=True, help="诊断 session ID")
    p_html.add_argument("--symptoms", default="", help="用户原始症状描述")
    p_html.add_argument("--report", default="", help="诊断报告文件路径")
    p_html.add_argument("--conversation", default="", help="诊断对话摘要 (用户问题+agent回答)")

    # verify — 实地验证反馈
    p_verify = sub.add_parser("verify", help="提交实地验证结果，优化诊断经验")
    p_verify.add_argument("--session", required=True, help="诊断 session ID")
    p_verify.add_argument("--result", required=True,
                          choices=["correct", "partial", "wrong"],
                          help="验证结果: correct(诊断正确) / partial(部分正确) / wrong(诊断错误)")
    p_verify.add_argument("--actual-root-cause", default="", help="实际确认的根因")
    p_verify.add_argument("--actual-repair", nargs="*", default=[], help="实际执行的修复操作")
    p_verify.add_argument("--notes", default="", help="补充备注")

    args = ap.parse_args()

    if args.cmd == "archive":
        cmd_archive(args)
    elif args.cmd == "extract-skill":
        cmd_extract_skill(args)
    elif args.cmd == "search":
        cmd_search(args)
    elif args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "pending":
        cmd_pending(args)
    elif args.cmd == "dashboard":
        cmd_dashboard(args)
    elif args.cmd == "sync":
        cmd_sync(args)
    elif args.cmd == "stats":
        cmd_stats(args)
    elif args.cmd == "export-skill":
        cmd_export_skill(args)
    elif args.cmd == "export-conversation":
        cmd_export_conversation(args)
    elif args.cmd == "export-html":
        cmd_export_html(args)
    elif args.cmd == "verify":
        cmd_verify(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
