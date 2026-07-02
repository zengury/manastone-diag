"""
experience_manager.py — 诊断经验库 (分片版 v2.0)
================================================

v2.0 变更:
  - 单文件 JSON → 分片存储 (每个分片 ≤5MB, 约 500 条经验)
  - 新增轻量索引文件 (fault_id/关键词 → 分片映射, 快速检索)
  - 新增 WAL 写入保护 (先写 .wal, 成功后原子 rename, 防数据损坏)
  - 完全向后兼容: CLI 接口不变, 存储自动升级

存储结构:
  data/experience_shards/
    shard_0001.json      活跃分片 (追加写入)
    shard_0002.json      已满分片 (只读)
    ...
  data/experience_index.json   轻量索引 (experience_id → shard)
  data/experience.wal          写入前日志 (崩溃恢复)

用法不变:
    python tools/experience_manager.py add --session <SN> ...
    python tools/experience_manager.py verify --session <SN> --result correct
    python tools/experience_manager.py search "站立摔倒"
    python tools/experience_manager.py stats
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import data_dir as _root_data_dir, project_root

# ---- 配置 ----

MAX_SHARD_SIZE_BYTES = 5 * 1024 * 1024   # 5MB 轮转
MAX_SHARD_EXPERIENCES = 500               # 或 500 条经验后轮转


# ---- 数据模型 (不变) ----

@dataclass
class Experience:
    experience_id: str
    session_id: str
    symptoms: str = ""
    ai_diagnosis: str = ""
    ai_fault_ids: list[str] = field(default_factory=list)
    ai_confidence: int = 0
    verified: bool = False
    actual_cause: str = ""
    actual_fault_ids: list[str] = field(default_factory=list)
    repair_actions: list[str] = field(default_factory=list)
    lessons: str = ""
    accuracy_score: int = 0
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


# ---- 路径管理 ----

def _shards_dir() -> Path:
    d = _root_data_dir() / "experience_shards"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path() -> Path:
    return _root_data_dir() / "experience_index.json"


def _wal_path() -> Path:
    return _root_data_dir() / "experience.wal"


def _migrate_old_format():
    """从 v1.0 单文件迁移到 v2.0 分片。"""
    old_path = _root_data_dir() / "experience_library.json"
    if not old_path.exists():
        return
    try:
        old = json.loads(old_path.read_text(encoding="utf-8"))
        exps = old.get("experiences", {})
        if not exps:
            return

        # 迁移每条经验到分片
        for eid, exp in exps.items():
            _shard_append(exp)

        # 重建索引
        _rebuild_index()

        # 备份旧文件
        backup = _data_dir() / "experience_library.json.v1.bak"
        shutil.move(str(old_path), str(backup))
        print(f"[migrate] v1.0 经验库已迁移到分片存储 (备份: {backup})")
    except Exception as e:
        print(f"[warn] 迁移失败（旧文件保留）: {e}")


# ---- 分片读写 ----

def _active_shard_path() -> Path:
    """找到或创建当前活跃分片。"""
    shards = sorted(_shards_dir().glob("shard_*.json"))
    if not shards:
        path = _shards_dir() / "shard_0001.json"
        path.write_text("{}", encoding="utf-8")
        return path

    # 最后一个分片
    last = shards[-1]
    try:
        stat = last.stat()
        data = json.loads(last.read_text(encoding="utf-8"))
        count = len(data)
        if stat.st_size >= MAX_SHARD_SIZE_BYTES or count >= MAX_SHARD_EXPERIENCES:
            # 轮转
            next_num = int(last.stem.split("_")[1]) + 1
            path = _shards_dir() / f"shard_{next_num:04d}.json"
            path.write_text("{}", encoding="utf-8")
            return path
    except Exception:
        pass
    return last


def _shard_append(exp_dict: dict):
    """追加一条经验到活跃分片（带 WAL 保护）。"""
    shard_path = _active_shard_path()

    # 1. 读当前分片
    try:
        shard_data = json.loads(shard_path.read_text(encoding="utf-8"))
    except Exception:
        shard_data = {}

    # 2. 添加
    shard_data[exp_dict["experience_id"]] = exp_dict

    # 3. 写 WAL
    wal_entry = {
        "op": "add",
        "shard": str(shard_path),
        "data": exp_dict,
        "timestamp": datetime.now().isoformat(),
    }
    _wal_path().write_text(json.dumps(wal_entry, ensure_ascii=False), encoding="utf-8")

    # 4. 原子写入分片 (先写临时文件, 再 rename)
    tmp = shard_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(shard_data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(shard_path)  # 原子操作

    # 5. 清除 WAL (写入成功)
    _wal_path().unlink(missing_ok=True)


def _shard_update(exp_id: str, updates: dict):
    """更新一条经验。"""
    idx = load_index()
    shard_file = idx.get("experience_map", {}).get(exp_id)
    if not shard_file:
        return False

    shard_path = _shards_dir() / shard_file
    if not shard_path.exists():
        return False

    try:
        shard_data = json.loads(shard_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    if exp_id not in shard_data:
        return False

    shard_data[exp_id].update(updates)
    shard_data[exp_id]["updated_at"] = datetime.now().isoformat()

    tmp = shard_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(shard_data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(shard_path)
    return True


def _iterate_all() -> list[dict]:
    """遍历所有分片中的所有经验。"""
    all_exps = []
    for sf in sorted(_shards_dir().glob("shard_*.json")):
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            all_exps.extend(data.values())
        except Exception:
            continue
    return all_exps


# ---- 索引管理 ----

def load_index() -> dict:
    ip = _index_path()
    if ip.exists():
        return json.loads(ip.read_text(encoding="utf-8"))
    return {"experience_map": {}, "fault_index": {}, "keyword_index": {}, "stats": {"total": 0}}


def save_index(idx: dict):
    ip = _index_path()
    tmp = ip.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ip)


def _update_index(exp_id: str, exp_dict: dict):
    """更新索引：记录经验在哪个分片，以及 fault_id 和关键词映射。"""
    idx = load_index()
    shard_name = _active_shard_path().name
    idx["experience_map"][exp_id] = shard_name

    # fault_id 索引
    for fid in exp_dict.get("ai_fault_ids", []) + exp_dict.get("actual_fault_ids", []):
        if fid not in idx["fault_index"]:
            idx["fault_index"][fid] = []
        if exp_id not in idx["fault_index"][fid]:
            idx["fault_index"][fid].append(exp_id)

    # 关键词索引 (从 tags 提取)
    for tag in exp_dict.get("tags", []):
        if tag not in idx["keyword_index"]:
            idx["keyword_index"][tag] = []
        if exp_id not in idx["keyword_index"][tag]:
            idx["keyword_index"][tag].append(exp_id)

    idx["stats"]["total"] = len(idx["experience_map"])
    save_index(idx)


def _rebuild_index():
    """全量重建索引（迁移或修复时使用）。"""
    idx = {"experience_map": {}, "fault_index": {}, "keyword_index": {}, "stats": {"total": 0}}
    for sf in sorted(_shards_dir().glob("shard_*.json")):
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            for eid, exp in data.items():
                idx["experience_map"][eid] = sf.name
                for fid in exp.get("ai_fault_ids", []) + exp.get("actual_fault_ids", []):
                    idx["fault_index"].setdefault(fid, []).append(eid)
                for tag in exp.get("tags", []):
                    idx["keyword_index"].setdefault(tag, []).append(eid)
        except Exception:
            continue
    idx["stats"]["total"] = len(idx["experience_map"])
    save_index(idx)
    return idx


def _recover_from_wal():
    """WAL 恢复：检查是否有未完成的写入。"""
    wp = _wal_path()
    if not wp.exists():
        return
    try:
        wal = json.loads(wp.read_text(encoding="utf-8"))
        print(f"[recover] 发现未完成的写入, 正在恢复...")
        _shard_append(wal["data"])
        wp.unlink(missing_ok=True)
        print(f"[recover] 恢复完成。")
    except Exception as e:
        print(f"[warn] WAL 恢复失败: {e}")


# ---- 分词和相似度 (不变) ----

def _tokenize(text: str) -> set[str]:
    tokens = set()
    for m in re.finditer(r"[a-zA-Z0-9_]+", text.lower()):
        tokens.add(m.group())
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    for c in chinese_chars:
        tokens.add(c)
    for i in range(len(chinese_chars) - 1):
        tokens.add(chinese_chars[i] + chinese_chars[i + 1])
    return tokens


def _similarity(query: str, exp: dict) -> float:
    query_tokens = _tokenize(query)
    if not query_tokens:
        return 0.0
    exp_text = f"{exp.get('symptoms','')} {exp.get('ai_diagnosis','')} {exp.get('actual_cause','')} {' '.join(exp.get('tags',[]))}"
    exp_tokens = _tokenize(exp_text)
    overlap = query_tokens & exp_tokens
    return len(overlap) / len(query_tokens)


def _extract_tags(symptoms: str, diagnosis: str, fault_ids: list[str]) -> list[str]:
    tags = set()
    text = f"{symptoms} {diagnosis}".lower()
    keyword_map = {
        "摔倒": ["摔倒", "跌落", "倾斜", "倒地", "失稳"],
        "关节": ["关节", "电机", "编码器", "减速器"],
        "过热": ["过热", "温度", "发烫", "过温", "thermal"],
        "通信": ["通信", "ethercat", "can", "断连", "超时", "离线"],
        "电源": ["电池", "电压", "过流", "掉电", "bms", "48v"],
        "传感器": ["imu", "lidar", "摄像头", "漂移", "标定"],
        "模式切换": ["模式", "setmc", "joint_default", "stand_default", "damping"],
        "遥控器": ["遥控", "误触", "误操作"],
    }
    for tag, keywords in keyword_map.items():
        if any(kw in text for kw in keywords):
            tags.add(tag)
    tags.update(fault_ids)
    return sorted(tags)


# ---- CLI 命令 (接口不变) ----

def _ensure_migrated():
    """启动时检查是否需要迁移旧格式。"""
    _recover_from_wal()
    _migrate_old_format()


def cmd_add(args):
    _ensure_migrated()
    exp_id = f"EXP-{args.session}"
    tags = _extract_tags(args.symptoms, args.ai_diagnosis, args.ai_fault_ids)
    exp = Experience(
        experience_id=exp_id, session_id=args.session,
        symptoms=args.symptoms, ai_diagnosis=args.ai_diagnosis,
        ai_fault_ids=args.ai_fault_ids, ai_confidence=args.ai_confidence,
        tags=tags,
        created_at=datetime.now().isoformat(), updated_at=datetime.now().isoformat(),
    )
    _shard_append(asdict(exp))
    _update_index(exp_id, asdict(exp))

    shard_count = len(list(_shards_dir().glob("shard_*.json")))
    print(f"✅ 经验已沉淀: {exp_id}  (分片: {shard_count})")
    print(f"   症状: {args.symptoms[:60]}")
    print(f"   诊断: {args.ai_diagnosis[:60]}")
    print(f"   标签: {tags}")


def cmd_verify(args):
    _ensure_migrated()
    exp_id = f"EXP-{args.session}"
    idx = load_index()
    if exp_id not in idx["experience_map"]:
        print(f"❌ 经验 {exp_id} 不存在。")
        sys.exit(1)

    # 读取经验
    shard_path = _shards_dir() / idx["experience_map"][exp_id]
    shard_data = json.loads(shard_path.read_text(encoding="utf-8"))
    exp = shard_data[exp_id]

    updates = {"verified": True, "updated_at": datetime.now().isoformat()}

    if args.result == "correct":
        updates["accuracy_score"] = 100
        updates["actual_cause"] = exp["ai_diagnosis"]
        updates["actual_fault_ids"] = exp["ai_fault_ids"]
    elif args.result == "partial":
        updates["accuracy_score"] = 50
        updates["actual_cause"] = args.actual_cause or exp["ai_diagnosis"]
        updates["actual_fault_ids"] = args.actual_fault_ids or exp["ai_fault_ids"]
    elif args.result == "wrong":
        updates["accuracy_score"] = 0
        updates["actual_cause"] = args.actual_cause or ""
        updates["actual_fault_ids"] = args.actual_fault_ids or []
        updates["repair_actions"] = args.repair or []

    if args.lessons:
        updates["lessons"] = args.lessons

    _shard_update(exp_id, updates)
    print(f"✅ 经验已纠正: {exp_id}")
    print(f"   AI 诊断: {exp.get('ai_diagnosis','')[:80]}")
    if args.result != "correct":
        print(f"   实际根因: {args.actual_cause[:80]}")


def cmd_search(args):
    _ensure_migrated()
    query = args.query

    # 先用索引缩小范围
    idx = load_index()
    candidate_ids = set()

    # 从关键词索引找候选
    query_tokens = _tokenize(query)
    for tag, eids in idx.get("keyword_index", {}).items():
        if tag in query or any(t in tag for t in query_tokens if len(t) > 1):
            candidate_ids.update(eids[:50])

    # 如果索引没命中，回退到全量扫描
    if not candidate_ids:
        candidate_ids = set(idx.get("experience_map", {}).keys())

    # 只加载候选经验所在的分片
    scored = []
    loaded_shards = {}
    for eid in list(candidate_ids)[:200]:  # 最多查 200 条
        shard_name = idx["experience_map"].get(eid)
        if not shard_name:
            continue
        if shard_name not in loaded_shards:
            try:
                loaded_shards[shard_name] = json.loads((_shards_dir() / shard_name).read_text(encoding="utf-8"))
            except Exception:
                continue
        exp = loaded_shards[shard_name].get(eid)
        if not exp:
            continue
        sim = _similarity(query, exp)
        if sim > 0.05:
            if exp.get("verified"):
                sim *= 1.2
            if exp.get("accuracy_score", 0) >= 80:
                sim *= 1.1
            scored.append((sim, eid, exp))

    scored.sort(key=lambda x: -x[0])
    top = scored[:args.limit]

    if not top:
        print(f"未找到与 '{query}' 相似的经验。")
        return

    print(f"🔍 '{query}' 的相似经验 (共 {len(top)} 条, 扫描 {len(candidate_ids)} 条候选):")
    print()
    for sim, eid, exp in top:
        vmark = "✅" if exp.get("verified") else "⬜"
        acc = exp.get("accuracy_score", 0)
        acc_str = f"准确度:{acc}%" if exp.get("verified") else "未验证"
        print(f"  {vmark} {eid} 相似度:{sim:.0%}  {acc_str}")
        print(f"     症状: {exp.get('symptoms','?')[:80]}")
        print(f"     AI诊断: {exp.get('ai_diagnosis','?')[:80]}")
        if exp.get("verified") and exp.get("actual_cause"):
            print(f"     实际根因: {exp['actual_cause'][:80]}")
        print()


def cmd_stats(args):
    _ensure_migrated()
    all_exps = _iterate_all()
    total = len(all_exps)
    verified = [e for e in all_exps if e.get("verified")]
    correct = sum(1 for e in verified if e.get("accuracy_score", 0) >= 80)
    partial = sum(1 for e in verified if 30 <= e.get("accuracy_score", 0) < 80)
    wrong = sum(1 for e in verified if e.get("accuracy_score", 0) < 30)
    shard_count = len(list(_shards_dir().glob("shard_*.json")))

    # 规则准确率
    ra: dict[str, dict] = {}
    for e in verified:
        for fid in e.get("ai_fault_ids", []):
            ra.setdefault(fid, {"total": 0, "correct": 0})
            ra[fid]["total"] += 1
            if e.get("accuracy_score", 0) >= 80:
                ra[fid]["correct"] += 1

    print(f"📊 诊断经验库统计 (分片存储: {shard_count} 个分片)")
    print(f"   总经验: {total} 条")
    print(f"   已验证: {len(verified)} 条 (正确:{correct} 部分:{partial} 错误:{wrong})")
    print(f"   未验证: {total - len(verified)} 条")
    print()

    if ra:
        print("故障规则实战准确率:")
        for fid in sorted(ra.keys()):
            r = ra[fid]
            acc = r["correct"] / r["total"] * 100 if r["total"] > 0 else 0
            bar = "█" * int(acc / 10) + "░" * (10 - int(acc / 10))
            status = "🟢" if acc >= 80 else ("🟡" if acc >= 50 else "🔴")
            boost = "+0.15" if acc >= 90 else ("+0.05" if acc >= 70 else ("-0.05" if acc <= 50 else ("-0.15" if acc <= 30 else "0")))
            print(f"  {status} {fid}: {bar} {acc:.0f}% ({r['correct']}/{r['total']})  置信度修正:{boost}")


def cmd_list(args):
    _ensure_migrated()
    idx = load_index()
    total = idx["stats"]["total"]
    print(f"📚 经验库 ({total} 条, {len(list(_shards_dir().glob('shard_*.json')))} 个分片)")
    p = _root_data_dir()
    if p != Path.cwd() / "data":
        print(f"   数据目录: {p}")


def cmd_import(args):
    """一键导入其他用户的完整诊断数据。

    导入内容:
      1. experience_shards/   → 经验库分片
      2. archive/             → 归档记录 + 索引
      3. records/             → 对话记录

    重复项自动跳过，不覆盖已有数据。
    """
    _ensure_migrated()
    source = Path(args.source)
    if not source.is_dir():
        print(f"❌ 源目录不存在: {source}")
        sys.exit(1)

    dest = _root_data_dir()
    results = {"experience": 0, "archive": 0, "records": 0, "skipped": 0, "errors": 0}

    # 1. 导入经验库分片
    src_shards = source / "experience_shards"
    if src_shards.is_dir():
        print("📦 导入经验库...")
        idx = load_index()
        for sf in sorted(src_shards.glob("shard_*.json")):
            try:
                data = json.loads(sf.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  ⚠️ 跳过 {sf.name}: {e}")
                results["errors"] += 1
                continue
            for eid, exp in data.items():
                if eid in idx["experience_map"]:
                    results["skipped"] += 1
                    continue
                exp["imported_from"] = str(source)
                _shard_append(exp)
                _update_index(eid, exp)
                results["experience"] += 1
        print(f"  新增 {results['experience']} 条, 跳过 {results['skipped']} 条 (已存在)")

    # 2. 导入归档记录
    src_archive = source / "archive"
    if src_archive.is_dir():
        print("📁 导入归档记录...")
        arch_dir = _root_data_dir() / "archive"
        arch_dir.mkdir(parents=True, exist_ok=True)
        # 合并索引
        src_index = src_archive / "index.json"
        dest_index = arch_dir / "index.json"
        if src_index.exists():
            try:
                si = json.loads(src_index.read_text(encoding="utf-8"))
                if dest_index.exists():
                    di = json.loads(dest_index.read_text(encoding="utf-8"))
                else:
                    di = {"sessions": [], "last_updated": ""}
                existing_ids = {s["session_id"] for s in di.get("sessions", [])}
                for s in si.get("sessions", []):
                    if s["session_id"] not in existing_ids:
                        di["sessions"].append(s)
                        results["archive"] += 1
                    else:
                        results["skipped"] += 1
                di["last_updated"] = datetime.now().isoformat()
                dest_index.write_text(json.dumps(di, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                print(f"  ⚠️ 索引合并失败: {e}")
        # 复制归档 JSON 文件
        for af in src_archive.glob("*.json"):
            if af.name == "index.json":
                continue
            dest_file = arch_dir / af.name
            if not dest_file.exists():
                shutil.copy2(str(af), str(dest_file))
                results["archive"] += 1
        print(f"  导入 {results['archive']} 条归档记录")

    # 3. 导入对话记录
    src_records = source / "records"
    if src_records.is_dir():
        print("💬 导入对话记录...")
        rec_dir = _root_data_dir() / "records"
        rec_dir.mkdir(parents=True, exist_ok=True)
        for rf in src_records.glob("*.json"):
            dest_file = rec_dir / rf.name
            if not dest_file.exists():
                shutil.copy2(str(rf), str(dest_file))
                results["records"] += 1
        print(f"  导入 {results['records']} 条对话记录")

    # 总结
    print()
    print("=" * 50)
    total_new = results["experience"] + results["archive"] + results["records"]
    print(f"✅ 导入完成: 新增 {total_new} 条数据")
    print(f"   经验: +{results['experience']}  归档: +{results['archive']}  对话: +{results['records']}")
    if results["skipped"] > 0:
        print(f"   跳过: {results['skipped']} 条 (已存在)")
    if results["errors"] > 0:
        print(f"   错误: {results['errors']}")
    print(f"   来源: {source}")
    print()

    # 刷新统计
    idx = load_index()
    print(f"当前经验库: {idx['stats']['total']} 条经验, {len(list(_shards_dir().glob('shard_*.json')))} 个分片")


def cmd_merge(args):
    """合并外部经验库（其他用户或来源）。"""
    _ensure_migrated()
    source_dir = Path(args.source)
    if not source_dir.exists():
        print(f"❌ 源目录不存在: {source_dir}")
        sys.exit(1)

    # 查找源分片
    source_shards = sorted(source_dir.glob("shard_*.json"))
    if not source_shards:
        # 也可能是旧格式单文件
        old_lib = source_dir / "experience_library.json"
        if old_lib.exists():
            print("检测到 v1.0 格式，请先在该用户处运行一次 experience_manager.py 自动升级。")
            sys.exit(1)
        print("❌ 源目录中没有经验数据。")
        sys.exit(1)

    idx = load_index()
    merged_count = 0
    skipped_count = 0

    for sf in source_shards:
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ⚠️ 跳过 {sf.name}: {e}")
            continue

        for eid, exp in data.items():
            if eid in idx["experience_map"]:
                skipped_count += 1
                continue
            exp["merged_from"] = str(source_dir)
            _shard_append(exp)
            _update_index(eid, exp)
            merged_count += 1

    print(f"✅ 合并完成: 新增 {merged_count} 条, 跳过 {skipped_count} 条 (已存在)")
    print(f"   来源: {source_dir}")
    print(f"   当前总经验: {len(idx['experience_map']) + merged_count} 条")


def cmd_remove(args):
    _ensure_migrated()
    print("⚠️ 删除操作暂不支持分片模式。请使用数据目录管理。")


# ---- CLI entry ----

def main():
    ap = argparse.ArgumentParser(description="manastone-diag 诊断经验库 (v2.0 分片版)")
    sub = ap.add_subparsers(dest="cmd")

    p_add = sub.add_parser("add", help="沉淀一条诊断经验")
    p_add.add_argument("--session", required=True)
    p_add.add_argument("--symptoms", required=True)
    p_add.add_argument("--ai-diagnosis", required=True)
    p_add.add_argument("--ai-fault-ids", nargs="*", default=[])
    p_add.add_argument("--ai-confidence", type=int, default=0)

    p_verify = sub.add_parser("verify", help="验证/纠正一条经验")
    p_verify.add_argument("--session", required=True)
    p_verify.add_argument("--result", required=True, choices=["correct", "partial", "wrong"])
    p_verify.add_argument("--actual-cause", default="")
    p_verify.add_argument("--actual-fault-ids", nargs="*", default=[])
    p_verify.add_argument("--repair", nargs="*", default=[])
    p_verify.add_argument("--lessons", default="")

    p_search = sub.add_parser("search", help="检索相似经验")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=5)

    sub.add_parser("stats", help="经验库统计")
    sub.add_parser("list", help="列出经验库概况")

    p_merge = sub.add_parser("merge", help="合并其他用户的经验库")
    p_merge.add_argument("source", help="源数据目录路径 (含 experience_shards/ 的 data/ 目录)")

    p_import = sub.add_parser("import", help="一键导入其他用户的完整诊断数据 (经验+归档+对话)")
    p_import.add_argument("source", help="源 data/ 目录路径 (含 experience_shards/ archive/ records/)")

    p_remove = sub.add_parser("remove", help="删除经验")
    p_remove.add_argument("--session", required=True)

    args = ap.parse_args()

    if args.cmd == "add":
        cmd_add(args)
    elif args.cmd == "verify":
        cmd_verify(args)
    elif args.cmd == "search":
        cmd_search(args)
    elif args.cmd == "stats":
        cmd_stats(args)
    elif args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "merge":
        cmd_merge(args)
    elif args.cmd == "import":
        cmd_import(args)
    elif args.cmd == "remove":
        cmd_remove(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
