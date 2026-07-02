"""
log_ingestor — 机器人日志摄入
============================

把机器人 session 的 log 目录(bag/ + info/ + log/,可达 GB 级)处理成:

1. session.summary.json     — 精简版语义事件流(几十 KB,可丢回对话给 agent 分析)
2. coverage.report.md       — ontology 缺口报告(给 ontology 维护者看)
3. stats.json               — 整体统计

设计目标:
- 本地运行,零网络,零外部依赖(只用 Python stdlib + PyYAML)
- streaming 处理,>1GB 不爆内存
- 隐私默认严格:剥离视频、点云、GPS、用户 ID
- schema-driven:由 ontology 决定关心什么字段,自动随 ontology 演进

用法:
    python3 tools/log_ingestor.py <log_dir> --robot agibot_x2 \\
        --output ./output

    log_dir 必须包含三个子目录的至少一个:
        bag/    ROS bag 数据(通常是 yaml 转储或类似格式)
        info/   状态快照、配置、PMU/BMS 轮询
        log/    节点 stdout/stderr 或 systemd journal 文本

诚实声明:
- 支持 .yaml/.yml、.log(含切片 .log_N)、.json、.mcap(需 mcap 库)、.atop(需 WSL/atop)。
  其他二进制格式(.bag .db3 等)跳过并 warning。
- streaming 解析失败的文件 graceful skip,不中断整体流程。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterator, Optional, Any

# 可选依赖:yaml(强烈建议安装,但允许 fallback)
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    print("[warn] PyYAML not installed, yaml files will be skipped. "
          "Install with: pip install pyyaml --break-system-packages",
          file=sys.stderr)


# ---- 事件匹配规则加载 ----
def _hardcoded_patterns() -> list[dict]:
    """内置默认规则。当 event_patterns.yaml 不可用时 fallback。"""
    return [
        {"priority": 100, "pattern": r"(?i)\bdetect\s+falling|Falling Action|auto transition to DAMPING",
         "kind": "falling_event", "severity": "critical", "keep_full": True},
        {"priority": 99, "pattern": r"(?i)(?:SetMcAction|SetAction|设置ACTION切换|Current Action|目标Action|Auto set|Need transition|action_manager|JOINT_DEFAULT|LOCOMOTION_STEP)",
         "kind": "mode_transition", "severity": "critical", "keep_full": True},
        {"priority": 90, "pattern": r"(?i)\b(overcurrent|overvoltage|over[_\s-]?temperature|overtemp)\b",
         "kind": "protection_event", "severity": "critical", "keep_full": True},
        {"priority": 89, "pattern": r"(?i)\b(short[_\s-]?circuit|emergency[_\s-]?stop|estop|e[_\s-]stop)\b",
         "kind": "safety_event", "severity": "critical", "keep_full": True},
        {"priority": 88, "pattern": r"(?i)\bbattery\b\s+(low|critical|dead|empty)",
         "kind": "battery_event", "severity": "warning", "keep_full": True},
        {"priority": 87, "pattern": r"(?i)\b(fault|failure)\b\s*[: ]",
         "kind": "fault", "severity": "error", "keep_full": True},
        {"priority": 86, "pattern": r"(?i)\bconnection\s+(lost|timeout|reset|failed)\b",
         "kind": "communication_event", "severity": "warning", "keep_full": True},
        {"priority": 50, "pattern": r"(?i)(?:^|\s|\[|\|)(error|err)\s*[\]:|]",
         "kind": "error", "severity": "error", "keep_full": True},
        {"priority": 40, "pattern": r"(?i)(?:^|\s|\[|\|)(warning|warn)\s*[\]:|]",
         "kind": "warning", "severity": "warning", "keep_full": True},
    ]


def _load_patterns_from_yaml(yaml_path: Path) -> list[dict]:
    """从 YAML 文件加载事件匹配规则。失败返回空列表。"""
    if not HAS_YAML or not yaml_path.exists():
        return []
    try:
        doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        patterns = doc.get("patterns", []) if isinstance(doc, dict) else []
        # 按 priority 降序排列
        patterns.sort(key=lambda p: p.get("priority", 0), reverse=True)
        return patterns
    except Exception as e:
        print(f"[warn] failed to load event patterns from {yaml_path}: {e}", file=sys.stderr)
        return []


def _resolve_patterns(ontology_dir: Path | None = None) -> list[dict]:
    """解析事件匹配规则: 优先 YAML, fallback 到内置。"""
    # 1. 先尝试 ontology_dir 下的 event_patterns.yaml
    if ontology_dir is not None:
        candidate = ontology_dir / "event_patterns.yaml"
        patterns = _load_patterns_from_yaml(candidate)
        if patterns:
            print(f"[patterns] loaded {len(patterns)} from {candidate}", file=sys.stderr)
            return patterns

    # 2. 尝试 knowledge/ 目录 (与 diagnostic_knowledge.yaml 同目录)
    repo_knowledge = Path(__file__).resolve().parent / "knowledge" / "event_patterns.yaml"
    patterns = _load_patterns_from_yaml(repo_knowledge)
    if patterns:
        print(f"[patterns] loaded {len(patterns)} from {repo_knowledge}", file=sys.stderr)
        return patterns

    # 3. fallback 到内置
    print("[patterns] using hardcoded defaults (no event_patterns.yaml found)", file=sys.stderr)
    return _hardcoded_patterns()


# ============================================================
# 配置:隐私过滤、采样、关键事件
# ============================================================

# 这些字段一旦在数据里出现,直接 drop(隐私 + 大数据)
PRIVACY_DROP_FIELDS = {
    "image", "image_raw", "compressed_image", "depth_image",
    "point_cloud", "pointcloud", "lidar_data",
    "audio", "audio_raw",
    "gps", "latitude", "longitude", "altitude",
    "user_id", "username", "operator_id",
    "face_embedding", "biometric",
}

# 高频 scalar topic 降采样目标频率(Hz)
DOWNSAMPLE_TARGET_HZ = 1.0

# 注意: LOG_EVENT_PATTERNS 已废弃,替换为 LogIngestor._resolve_patterns() 动态加载。
# 旧常量仅作 fallback/deprecated 参考,不再被 LogIngestor 直接使用。
# 新规则定义在 knowledge/event_patterns.yaml。
LOG_EVENT_PATTERNS_DEPRECATED = _hardcoded_patterns()  # 兼容性保留


# Severity 优先级(高 → 低)。决定事件被挤占的顺序。
# critical/error 不会被挤;warning 能挤 notice/info;notice 能挤 info。
_SEVERITY_RANK = {
    "critical": 5,
    "error": 4,
    "warning": 3,
    "notice": 2,
    "info": 1,
    "nominal": 1,
    "unknown": 0,
}

# Timestamp 识别(几种常见格式)
TIMESTAMP_PATTERNS = [
    re.compile(r"\[(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)\]"),
    re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)"),
    re.compile(r"\[(\d+\.\d+)\]"),  # ros2 时间戳浮点秒
]

# Linux syslog 风格:Mar  4 10:15:08 / Feb 28 09:00:00
SYSLOG_TIMESTAMP_PATTERN = re.compile(
    r"^([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})"
)


def _ts_to_epoch_ns(ts_str: str, default_year: int = 2026) -> Optional[int]:
    """把多种时间戳格式归一化为 epoch nanoseconds。失败返回 None。

    支持:
    - "2026-04-08T15:34:51"           ISO 8601
    - "2026-04-08 15:34:51.123456"    带毫秒
    - "1775633691"                    epoch seconds
    - "1775633691.123"                epoch float seconds
    - "Mar  4 10:15:08"               syslog 风格(用 default_year)
    """
    if not ts_str:
        return None
    import datetime

    # 尝试 epoch float
    try:
        if "." in ts_str and ts_str.replace(".", "").isdigit():
            return int(float(ts_str) * 1e9)
        if ts_str.isdigit():
            v = int(ts_str)
            if v > 1e15:  # 已是 ns
                return v
            if v > 1e12:  # 是 ms
                return v * 1_000_000
            return v * 1_000_000_000  # epoch seconds
    except (ValueError, OverflowError):
        pass

    # 尝试 ISO 8601
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            dt = datetime.datetime.strptime(ts_str, fmt)
            return int(dt.timestamp() * 1e9)
        except ValueError:
            continue

    # 尝试 syslog 风格
    m = SYSLOG_TIMESTAMP_PATTERN.match(ts_str)
    if m:
        try:
            dt = datetime.datetime.strptime(
                f"{default_year} {m.group(1)}", "%Y %b %d %H:%M:%S"
            )
            return int(dt.timestamp() * 1e9)
        except ValueError:
            pass

    return None


# ============================================================
# Output dataclasses
# ============================================================

@dataclass
class SessionEvent:
    ts: str                     # 时间戳字符串(原样保留)
    kind: str                   # mode_transition / status_bit / action / fault / scalar / log_text
    source_file: str            # 哪个文件抽出来的
    payload: dict = field(default_factory=dict)
    ontology_ref: Optional[str] = None
    severity: Optional[str] = None
    epoch_ns: Optional[int] = None    # 归一化时间戳(epoch ns),用于跨源对齐


@dataclass
class CoverageEntry:
    item: str                   # 比如 "/some/topic" 或 "field battery_temp"
    kind: str                   # topic / field / msg_type
    count: int
    first_seen: Optional[str] = None
    note: str = ""


@dataclass
class IngestStats:
    files_scanned: int = 0
    files_parsed_ok: int = 0
    files_skipped: int = 0
    bytes_read: int = 0
    events_extracted: int = 0
    yaml_docs_parsed: int = 0
    log_lines_scanned: int = 0
    elapsed_seconds: float = 0.0
    by_directory: dict = field(default_factory=lambda: defaultdict(int))
    # mcap stats
    mcap_files_read: int = 0
    mcap_messages_total: int = 0
    mcap_messages_kept: int = 0


# ============================================================
# 主 Ingestor
# ============================================================

class LogIngestor:
    """处理一个 session 目录,产出三件交付物。"""

    def __init__(
        self,
        log_dir: Path,
        robot_id: str,
        output_dir: Path,
        ontology_dir: Optional[Path] = None,
        max_events: int = 10000,
        verbose: bool = False,
    ):
        self.log_dir = log_dir
        self.robot_id = robot_id
        self.output_dir = output_dir
        self.ontology_dir = ontology_dir
        self.max_events = max_events
        self.verbose = verbose

        # 加载 ontology(可选,用于 ground 事件)
        self.known_topics: set[str] = set()
        self.known_msg_types: set[str] = set()
        self.known_actions: set[str] = set()
        self.known_status_bits: dict[tuple[str, int], str] = {}  # (field, bit) -> id
        self.known_status_bit_severity: dict[tuple[str, int], str] = {}  # (field, bit) -> severity
        self.nominal_bit_counter: Counter = Counter()  # 常态 bit 的累计计数(代替进 events)

        if ontology_dir is not None:
            self._load_ontology()

        # 加载事件匹配规则 (优先 YAML, fallback 内置)
        self._event_patterns = _resolve_patterns(ontology_dir)

        # 输出累加器
        self.events: list[SessionEvent] = []
        self.coverage_topics: Counter = Counter()
        self.coverage_fields: Counter = Counter()
        self.coverage_msg_types: Counter = Counter()
        self.scalar_timeseries: dict[str, list] = defaultdict(list)
        self.log_event_counters: Counter = Counter()
        self.warnings: list[str] = []
        self.atop_summaries: list[dict] = []
        self.atop_unavailable_warned: bool = False
        self.joint_asymmetry: dict | None = None  # mcap 关节对称性分析结果
        self.max_msg_per_topic: int = 200
        self._displaced_count: int = 0   # 被高优先级事件挤掉的低 severity 事件数

        self.stats = IngestStats()

    # ----- ontology 集成(轻量,不依赖完整 engine 也能跑) -----
    def _load_ontology(self):
        """从 ontology yaml 抽取 topic/msg_type/action/status_bit 名字。
        失败不致命,只是无法做 grounding。"""
        if not HAS_YAML:
            self.warnings.append("yaml not available, ontology grounding skipped")
            return

        try:
            for p in self.ontology_dir.glob("*.yaml"):
                doc = yaml.safe_load(p.read_text(encoding="utf-8"))
                if not isinstance(doc, dict):
                    continue
                for obj in doc.get("objects", []) or []:
                    t = obj.get("type")
                    props = obj.get("properties") or {}
                    oid = obj.get("id", "")
                    if t == "Topic":
                        name = props.get("name") or oid
                        self.known_topics.add(name)
                        if "msg_type" in props:
                            self.known_msg_types.add(props["msg_type"])
                    elif t == "MsgSchema":
                        name = props.get("name")
                        if name:
                            self.known_msg_types.add(name)
                    elif t == "StatusBit":
                        field_name = props.get("carrier_field")
                        bit_idx = props.get("bit_index")
                        if field_name is not None and bit_idx is not None:
                            self.known_status_bits[(field_name, bit_idx)] = oid
                            sev = props.get("severity", "unknown")
                            self.known_status_bit_severity[(field_name, bit_idx)] = sev
                for act in doc.get("actions", []) or []:
                    aid = act.get("type_id")
                    if aid:
                        self.known_actions.add(aid)
            self._log(f"[ontology] loaded {len(self.known_topics)} topics, "
                      f"{len(self.known_msg_types)} msg_types, "
                      f"{len(self.known_actions)} actions, "
                      f"{len(self.known_status_bits)} status_bits")
        except Exception as e:
            self.warnings.append(f"ontology load partial fail: {e}")

    def _log(self, msg: str):
        if self.verbose:
            print(msg, file=sys.stderr)

    # ----- 主入口 -----
    def run(self):
        t0 = time.time()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 三个子目录顺序:info(小,先建立 ontology 上下文)→ log → bag(大)
        for subdir_name in ("info", "log", "bag"):
            subdir = self.log_dir / subdir_name
            if not subdir.is_dir():
                self._log(f"[skip] no {subdir_name}/ subdir")
                continue
            self._log(f"[scan] {subdir}")
            self._process_directory(subdir, subdir_name)

        # 即使 max_events 触发了截断,也产出
        if len(self.events) >= self.max_events:
            self.warnings.append(
                f"events truncated to {self.max_events} for output size"
            )

        self.stats.elapsed_seconds = round(time.time() - t0, 2)
        self.stats.events_extracted = len(self.events)

        # 写出
        self._write_summary()
        self._write_coverage()
        self._write_stats()

        # 控制台总结
        self._print_summary()

    # ----- 目录扫描 -----
    def _process_directory(self, subdir: Path, kind: str):
        """递归处理子目录,按文件扩展名分发到 yaml/log handler。"""
        files = sorted([p for p in subdir.rglob("*") if p.is_file()])
        for f in files:
            self.stats.files_scanned += 1
            self.stats.by_directory[kind] += 1
            try:
                self.stats.bytes_read += f.stat().st_size
            except OSError:
                pass

            # 太大单文件(>500MB)给个进度提示,但不阻止
            try:
                size_mb = f.stat().st_size / (1024 * 1024)
                if size_mb > 500:
                    self._log(f"  [big] {f.name}: {size_mb:.0f} MB,可能耗时")
            except OSError:
                pass

            # 分发
            ext = f.suffix.lower()
            # 切片日志识别:hal_imu.log_4, runtime.log_3 等
            is_sliced_log = bool(re.match(r"^\.log(_\d+)?$", ext)) or \
                             bool(re.search(r"\.log(_\d+)?$", f.name, re.IGNORECASE))
            try:
                if ext in (".yaml", ".yml"):
                    self._process_yaml_streaming(f, kind)
                elif ext in (".log", ".txt") or is_sliced_log:
                    self._process_log_streaming(f, kind)
                elif ext in (".json", ".jsonl"):
                    self._process_json_streaming(f, kind)
                elif ext == ".mcap":
                    self._process_mcap_streaming(f, kind)
                elif ext == ".atop":
                    self._process_atop_summary(f, kind)
                else:
                    self._log(f"  [skip] {f.name}: unsupported extension {ext}")
                    self.stats.files_skipped += 1
                    continue
                self.stats.files_parsed_ok += 1
            except Exception as e:
                self.warnings.append(f"file parse fail {f.name}: {e}")
                self.stats.files_skipped += 1

            # 截断:如果事件已到上限,可以跳过后续解析(但仍要扫描以做 coverage)
            # 这里我们仍解析但不再 append events
            if len(self.events) >= self.max_events and self.verbose:
                self._log(f"  [trunc] events @ max, still scanning for coverage")

    # ----- YAML 文件 streaming 处理 -----
    def _process_yaml_streaming(self, fpath: Path, kind: str):
        """yaml 文件流式解析,支持 multi-doc。对每个 doc 跑事件抽取。"""
        if not HAS_YAML:
            self.stats.files_skipped += 1
            return

        with fpath.open("r", encoding="utf-8", errors="replace") as f:
            try:
                docs_iter = yaml.safe_load_all(f)
                for doc in docs_iter:
                    self.stats.yaml_docs_parsed += 1
                    if doc is None:
                        continue
                    self._extract_from_doc(doc, fpath.name, kind)
            except yaml.YAMLError as e:
                self.warnings.append(f"yaml parse error in {fpath.name}: {str(e)[:120]}")

    # ----- JSON / JSONL -----
    def _process_json_streaming(self, fpath: Path, kind: str):
        # JSONL 行式
        if fpath.suffix.lower() == ".jsonl":
            with fpath.open("r", encoding="utf-8", errors="replace") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        doc = json.loads(ln)
                        self._extract_from_doc(doc, fpath.name, kind)
                    except json.JSONDecodeError:
                        continue
        else:
            try:
                doc = json.loads(fpath.read_text(encoding="utf-8", errors="replace"))
                if isinstance(doc, list):
                    for d in doc:
                        self._extract_from_doc(d, fpath.name, kind)
                else:
                    self._extract_from_doc(doc, fpath.name, kind)
            except json.JSONDecodeError as e:
                self.warnings.append(f"json parse error in {fpath.name}: {str(e)[:120]}")

    # ----- LOG 文本 streaming -----
    def _process_log_streaming(self, fpath: Path, kind: str):
        """行式 log 文件。提取错误/警告/模式切换/电源/通信事件。

        事件匹配规则来自 self._event_patterns (YAML 或内置 fallback)。
        YAML 中的 pattern 是正则字符串,在此处编译为 compiled regex 缓存。

        事件分级保留策略:
        - critical/error 级别:永远保留(优先占用 max_events 配额)
        - warning/info 级别:max_events 满了后丢弃
        - keep_full=True 的事件:保留完整 text(不截断)
        """
        # 缓存编译后的正则 (第一次调用时编译)
        if not hasattr(self, '_compiled_patterns'):
            self._compiled_patterns = []
            for ep in self._event_patterns:
                try:
                    self._compiled_patterns.append((
                        re.compile(ep["pattern"]),
                        ep["kind"],
                        ep.get("severity", "warning"),
                        ep.get("keep_full", True),
                    ))
                except re.error as e:
                    self.warnings.append(
                        f"bad regex pattern '{ep.get('kind','?')}': {e}"
                    )

        for line_num, ln in self._read_log_lines(fpath):
            self.stats.log_lines_scanned += 1

            ts = self._extract_timestamp(ln)

            for pat, event_kind, severity, keep_full in self._compiled_patterns:
                m = pat.search(ln)
                if not m:
                    continue
                self.log_event_counters[event_kind] += 1

                # 决定是否保留这个事件
                should_keep = self._should_keep_event(severity)
                if should_keep:
                    # critical/error 不截断,完整保留
                    # warning/info 仍可适度截短(但比之前的 200 宽容,4000 字符)
                    if keep_full:
                        content = ln if len(ln) < 8000 else ln[:7997] + "..."
                    else:
                        content = ln if len(ln) < 2000 else ln[:1997] + "..."

                    self.events.append(SessionEvent(
                        ts=ts or "",
                        kind=f"log.{event_kind}",
                        source_file=fpath.name,
                        payload={"line": line_num, "text": content},
                        severity=severity,
                        epoch_ns=_ts_to_epoch_ns(ts) if ts else None,
                    ))
                break  # 一行只匹配第一个 kind

    def _read_log_lines(self, fpath: Path) -> Iterator[tuple[int, str]]:
        """流式读 log 行,yield (line_num, line)。"""
        with fpath.open("r", encoding="utf-8", errors="replace") as f:
            for line_num, ln in enumerate(f, 1):
                ln = ln.rstrip("\n")
                if ln:
                    yield line_num, ln

    def _should_keep_event(self, severity: str) -> bool:
        """根据 severity 决定是否保留事件。

        Severity 优先级(从高到低):
            critical > error > warning > notice > info > unknown

        规则:
        - critical 类:永远接受(关键证据不丢)
        - 配额未满:全部接受
        - 配额满了:新事件能挤掉队列里 severity 严格低于自己的事件
        - 不能挤掉时,丢弃新事件
        """
        # critical 类永远接受 — 不让"日志风暴"挤掉关键安全证据
        if severity == "critical":
            return True

        if len(self.events) < self.max_events:
            return True

        my_rank = _SEVERITY_RANK.get(severity, 0)
        if my_rank == 0:
            return False  # unknown 不挤

        # 找一个 severity 严格低于当前事件的,挤掉它
        # 5000 量级线性扫描可接受;生产版应换 sortedcontainers
        lowest_idx = -1
        lowest_rank = my_rank
        for i, e in enumerate(self.events):
            r = _SEVERITY_RANK.get(e.severity, 0)
            if r < lowest_rank:
                lowest_idx = i
                lowest_rank = r
                if r == 1:  # info 已是最低,不必继续找
                    break
        if lowest_idx >= 0:
            self.events.pop(lowest_idx)
            self._displaced_count += 1
            return True
        return False

    # ----- MCAP 文件处理 -----
    def _process_mcap_streaming(self, fpath: Path, kind: str):
        """流式读 MCAP bag。CDR 解码 + 二进制扫描双通道,包含关节对称性分析。"""
        # 检查 mcap 基础库
        try:
            from mcap.reader import make_reader as _mcap_make_reader
        except ImportError:
            self.warnings.append(
                "mcap library not installed, run: pip install mcap"
            )
            self.stats.files_skipped += 1
            return

        # ── 通道 1: CDR 解码 (需要 mcap-ros2-support) ──
        cdr_ok = False
        try:
            from mcap_reader import McapReader, HAS_MCAP
            cdr_ok = HAS_MCAP
        except ImportError:
            pass

        if cdr_ok:
            reader = McapReader(max_per_topic=self.max_msg_per_topic)
            try:
                for msg in reader.read_messages(fpath):
                    self.coverage_topics[msg["topic"]] += 1
                    if msg.get("msg_type"):
                        self.coverage_msg_types[msg["msg_type"]] += 1
                    ts = f"{msg['log_time_ns'] / 1e9:.3f}"
                    if isinstance(msg.get("payload"), dict):
                        self._extract_message_payload(
                            msg["topic"], msg["payload"], fpath.name, kind
                        )
                stats = reader.get_stats()
                self.stats.mcap_files_read += 1
                self.stats.mcap_messages_total += stats["messages_total"]
                self.stats.mcap_messages_kept += stats["messages_kept"]
            except Exception as e:
                self.warnings.append(
                    f"mcap CDR decode failed {fpath.name}: {str(e)[:200]}"
                )
                cdr_ok = False  # 回退到二进制扫描

        # ── 通道 2: 二进制扫描关节对称性 (始终执行,补充 CDR 解码) ──
        self._analyze_mcap_joint_asymmetry(fpath)

        if not cdr_ok:
            # CDR 不可用时至少登记 topic 信息
            try:
                with open(fpath, "rb") as f:
                    reader = _mcap_make_reader(f)
                    summary = reader.get_summary()
                    if summary:
                        for ch_id, channel in summary.channels.items():
                            self.coverage_topics[channel.topic] += 0  # 标记存在
                            if hasattr(channel, 'schema_id') and channel.schema_id:
                                schema = summary.schemas.get(channel.schema_id)
                                if schema:
                                    self.coverage_msg_types[schema.name] += 0
                self.stats.mcap_files_read += 1
            except Exception as e:
                self.warnings.append(f"mcap scan error {fpath.name}: {str(e)[:200]}")
                self.stats.files_skipped += 1

    def _analyze_mcap_joint_asymmetry(self, fpath: Path):
        """二进制扫描 mcap 中的关节状态数据,计算左右对称性。
        只处理 rt_control_link 目录下的 mcap (包含 /aima/hal/joint/leg/state)。
        """
        # 只分析 rt_control_link 的 mcap (包含关节状态 topic)
        if "rt_control_link" not in str(fpath):
            return

        import struct
        import math

        JOINT_NAMES = [
            "left_hip_pitch_joint", "left_hip_roll_joint", "left_hip_yaw_joint",
            "left_knee_joint", "left_ankle_pitch_joint", "left_ankle_roll_joint",
            "right_hip_pitch_joint", "right_hip_roll_joint", "right_hip_yaw_joint",
            "right_knee_joint", "right_ankle_pitch_joint", "right_ankle_roll_joint",
        ]
        PAIR_MAP = {
            "left_hip_pitch_joint": "right_hip_pitch_joint",
            "left_hip_roll_joint": "right_hip_roll_joint",
            "left_hip_yaw_joint": "right_hip_yaw_joint",
            "left_knee_joint": "right_knee_joint",
            "left_ankle_pitch_joint": "right_ankle_pitch_joint",
            "left_ankle_roll_joint": "right_ankle_roll_joint",
        }

        try:
            from mcap.reader import make_reader as _mcap_make_reader
        except ImportError:
            return

        # 累加器
        l_eff = {j: 0.0 for j in JOINT_NAMES if j.startswith("left_")}
        r_eff = {j: 0.0 for j in JOINT_NAMES if j.startswith("right_")}
        l_pos = {j: 0.0 for j in JOINT_NAMES if j.startswith("left_")}
        r_pos = {j: 0.0 for j in JOINT_NAMES if j.startswith("right_")}
        sample_count = 0

        try:
            with open(fpath, "rb") as f:
                reader = _mcap_make_reader(f)
                for schema, channel, msg in reader.iter_messages():
                    if "/joint/leg/state" not in channel.topic:
                        continue
                    data = msg.data
                    joints_found = 0
                    for jn in JOINT_NAMES:
                        jb = jn.encode()
                        idx = data.find(jb)
                        if idx < 0:
                            continue
                        val_start = (idx + len(jb) + 3) & ~3
                        if val_start + 24 > len(data):
                            continue
                        try:
                            pos = struct.unpack_from("<d", data, val_start)[0]
                            vel = struct.unpack_from("<d", data, val_start + 8)[0]
                            eff = struct.unpack_from("<d", data, val_start + 16)[0]
                            if not (math.isfinite(pos) and math.isfinite(eff)):
                                continue
                            if abs(pos) > 100 or abs(eff) > 10000:
                                continue
                            joints_found += 1
                            if jn.startswith("left_"):
                                l_eff[jn] += abs(eff)
                                l_pos[jn] += pos
                            else:
                                r_eff[jn] += abs(eff)
                                r_pos[jn] += pos
                        except struct.error:
                            continue
                    if joints_found >= 8:
                        sample_count += 1
        except Exception as e:
            self.warnings.append(f"joint asymmetry scan error {fpath.name}: {str(e)[:200]}")
            return

        if sample_count < 10:
            return  # 样本量不足

        # 计算不对称指标
        pairs = []
        total_score = 0.0
        for ln in sorted(l_eff.keys()):
            rn = PAIR_MAP[ln]
            le = l_eff[ln] / sample_count
            re = r_eff[rn] / sample_count
            lp = l_pos[ln] / sample_count
            rp = r_pos[rn] / sample_count
            pos_diff_deg = (rp - lp) * 180 / math.pi
            eff_ratio = re / le if le > 0.01 else (999.0 if re > 0.01 else 1.0)
            asymmetry_score = abs(pos_diff_deg) + abs(math.log2(max(eff_ratio, 1 / eff_ratio)) if eff_ratio > 0 else 0)
            total_score += asymmetry_score
            pairs.append({
                "left_joint": ln,
                "right_joint": rn,
                "left_effort_mean": round(le, 4),
                "right_effort_mean": round(re, 4),
                "effort_ratio_r_over_l": round(eff_ratio, 2),
                "left_position_mean_deg": round(lp * 180 / math.pi, 2),
                "right_position_mean_deg": round(rp * 180 / math.pi, 2),
                "position_diff_deg": round(pos_diff_deg, 2),
                "asymmetry_score": round(asymmetry_score, 2),
            })

        severity = "CRITICAL" if total_score > 30 else "WARNING" if total_score > 10 else "NORMAL"

        self.joint_asymmetry = {
            "mcap_file": fpath.name,
            "sample_count": sample_count,
            "total_asymmetry_score": round(total_score, 2),
            "severity": severity,
            "pairs": pairs,
        }
        self._log(f"[joint-asymmetry] {fpath.name}: {sample_count} samples, "
                  f"score={total_score:.1f} → {severity}")

    # ----- atop 文件处理 -----
    def _process_atop_summary(self, fpath: Path, kind: str):
        """读 atop 文件,提取系统状态摘要。需要系统装 atop 命令。"""
        try:
            from atop_reader import AtopReader
        except ImportError:
            self.warnings.append(f"atop reader module not available")
            self.stats.files_skipped += 1
            return

        reader = AtopReader()
        if not reader.is_atop_available():
            # 第一次发现 atop 不可用就 warn,后续静默跳过
            if not self.atop_unavailable_warned:
                self.warnings.append(
                    "atop binary not on this system. atop files require Linux + atop installed. "
                    "Tip: copy .atop files to a Linux box and run there."
                )
                self.atop_unavailable_warned = True
            self.stats.files_skipped += 1
            return

        summary = reader.read_summary(fpath)
        # 累积 atop 摘要
        self.atop_summaries.append(summary)


    # ----- 通用文档抽取(yaml / json 共用) -----
    def _extract_from_doc(self, doc: Any, source_file: str, kind: str):
        """从已解析的 dict/list 中识别 topic、msg_type、status_bit、action 调用等。"""
        if isinstance(doc, dict):
            # topic 名往往作为 dict key 出现(ros bag yaml dump 风格)
            for key, value in doc.items():
                if isinstance(key, str):
                    # 形如 "/aima/hal/pmu/state" 的字段名识别为 topic
                    if key.startswith("/") and "/" in key[1:]:
                        self.coverage_topics[key] += 1
                        if value is not None:
                            self._extract_message_payload(key, value, source_file, kind)
                    # msg_type 识别(包含 / 和 msg)
                    elif "msg/" in key.lower() or "/msg/" in key.lower():
                        self.coverage_msg_types[key] += 1
                # 递归
                if isinstance(value, (dict, list)):
                    self._extract_from_doc(value, source_file, kind)
                else:
                    # 标量字段:看名字是否值得记录
                    self._note_field(key, value)

        elif isinstance(doc, list):
            for item in doc:
                self._extract_from_doc(item, source_file, kind)

    def _extract_message_payload(self, topic: str, value: Any, source_file: str, kind: str):
        """对 topic 的负载做事件抽取。支持嵌套字段(如 joint state 里每个关节的 dict)。"""
        if not isinstance(value, dict):
            return

        ts = self._guess_timestamp_from_payload(value)
        # 第一层抽取
        self._scan_for_signals(topic, value, ts, source_file, "")
        # 嵌套抽取(joint state 里 left_shoulder_pitch.motor_temperature 这种)
        for sub_name, sub_val in value.items():
            if isinstance(sub_val, dict):
                self._scan_for_signals(topic, sub_val, ts, source_file, sub_name)

    def _scan_for_signals(self, topic: str, payload: dict, ts: str,
                           source_file: str, sub_path: str):
        """扫一层 dict,识别 status_bit / mode / scalar 时序信号。"""
        for fname, fval in payload.items():
            if not isinstance(fname, str):
                continue
            full_field = f"{sub_path}.{fname}" if sub_path else fname

            # 隐私 drop
            if any(p in fname.lower() for p in PRIVACY_DROP_FIELDS):
                continue

            # bitmap 字段
            if (fname.endswith("_bits") or fname.endswith("_status_bits")
                    or fname == "pmu_bool_status" or fname.endswith("_bitmap")):
                if isinstance(fval, int) and fval > 0:
                    for bit_idx in range(64):
                        if fval & (1 << bit_idx):
                            ontology_ref = self.known_status_bits.get((fname, bit_idx))
                            # 用 ontology 的 severity 决定是 anomaly 还是 nominal
                            bit_severity = self.known_status_bit_severity.get(
                                (fname, bit_idx), "unknown"
                            )
                            # 常态信号(nominal/info)不进 events,只在 stats 里计数
                            if bit_severity in ("nominal", "info"):
                                self.nominal_bit_counter[(fname, bit_idx)] += 1
                                continue
                            # 异常或未知 severity 进 events
                            if self._should_keep_event(
                                bit_severity if bit_severity != "unknown" else "warning"
                            ):
                                self.events.append(SessionEvent(
                                    ts=ts or "",
                                    kind="status_bit_active",
                                    source_file=source_file,
                                    payload={
                                        "topic": topic,
                                        "field": fname,
                                        "bit": bit_idx,
                                    },
                                    ontology_ref=ontology_ref,
                                    severity=bit_severity,
                                ))
                            else:
                                break

            # 模式
            elif fname in ("mc_action", "mode", "current_mode"):
                if isinstance(fval, str) and fval:
                    if len(self.events) < self.max_events:
                        self.events.append(SessionEvent(
                            ts=ts or "",
                            kind="mode_observed",
                            source_file=source_file,
                            payload={"topic": topic, "value": fval},
                        ))

            # 标量时序
            elif (isinstance(fval, (int, float))
                  and not isinstance(fval, bool)
                  and any(k in fname.lower() for k in
                          ("temp", "voltage", "current", "velocity",
                           "speed", "rpm", "force", "torque", "battery",
                           "position"))):
                series_key = f"{topic}.{full_field}"
                series = self.scalar_timeseries[series_key]
                if len(series) < 200:
                    series.append([ts or "", float(fval)])
                else:
                    if (len(series) % 5) == 0:
                        series.append([ts or "", float(fval)])

            self.coverage_fields[full_field] += 1

    def _note_field(self, key: str, value: Any):
        """看到一个字段名,在 coverage 里登记。"""
        if isinstance(key, str) and not key.startswith("/"):
            # 过滤一些过于常见的 key 不计数
            if key in ("type", "id", "name", "value", "data", "header", "stamp",
                       "sec", "nsec", "frame_id", "seq"):
                return
            if not any(p in key.lower() for p in PRIVACY_DROP_FIELDS):
                self.coverage_fields[key] += 1

    def _extract_timestamp(self, line: str) -> str:
        for pat in TIMESTAMP_PATTERNS:
            m = pat.search(line)
            if m:
                return m.group(1)
        return ""

    def _guess_timestamp_from_payload(self, payload: dict) -> str:
        """从消息负载里找时间戳(常见字段)。"""
        for k in ("timestamp", "stamp", "time", "ts"):
            if k in payload:
                v = payload[k]
                if isinstance(v, (str, int, float)):
                    return str(v)
                if isinstance(v, dict):
                    # ros2 header.stamp { sec, nanosec }
                    if "sec" in v:
                        return f"{v.get('sec', 0)}.{v.get('nanosec', v.get('nsec', 0))}"
        return ""

    # ----- 写出 -----
    def _write_summary(self):
        out_path = self.output_dir / "session.summary.json"
        # 只保留高频 series 的降采样版
        scalar_out = {}
        for key, series in self.scalar_timeseries.items():
            scalar_out[key] = {
                "samples_count": len(series),
                "samples": series[:200],  # 最多 200 点
                "downsampled": len(series) >= 200,
            }

        summary = {
            "schema_version": "0.2",
            "robot_id": self.robot_id,
            "session": {
                "log_dir": str(self.log_dir),
                "ingestor_version": "0.2",
            },
            "events": [asdict(e) for e in self.events],
            "scalars_timeseries": scalar_out,
            "log_event_counts": dict(self.log_event_counters),
            "atop_summaries": self.atop_summaries,
            "joint_asymmetry": self.joint_asymmetry,
            "warnings": self.warnings,
        }
        out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        self._log(f"[write] {out_path} ({out_path.stat().st_size // 1024} KB)")

    def _write_coverage(self):
        out_path = self.output_dir / "coverage.report.md"
        lines = []
        lines.append("# Coverage Report")
        lines.append("")
        lines.append(f"- Robot: `{self.robot_id}`")
        lines.append(f"- Log dir: `{self.log_dir}`")
        lines.append(f"- Generated: manastone-diag log_ingestor")
        lines.append("")

        # Topics
        in_onto, out_of_onto = [], []
        for topic, count in self.coverage_topics.most_common():
            if topic in self.known_topics:
                in_onto.append((topic, count))
            else:
                out_of_onto.append((topic, count))

        lines.append("## Topics observed")
        lines.append("")
        lines.append(f"- ✓ in ontology: **{len(in_onto)}**")
        lines.append(f"- ✗ NOT in ontology: **{len(out_of_onto)}**")
        lines.append("")

        if out_of_onto:
            lines.append("### Topics in log but NOT registered in ontology")
            lines.append("")
            lines.append("| Topic | Occurrences |")
            lines.append("|---|---|")
            for topic, count in out_of_onto[:50]:
                lines.append(f"| `{topic}` | {count} |")
            if len(out_of_onto) > 50:
                lines.append(f"| ... ({len(out_of_onto) - 50} more) | |")
            lines.append("")

        # Topics 在 ontology 但 log 没出现
        unobserved = self.known_topics - set(self.coverage_topics.keys())
        if unobserved:
            lines.append("### Topics in ontology but NOT observed in this session")
            lines.append("")
            lines.append(f"({len(unobserved)} topics — could mean unused this session, "
                         "or topic name changed)")
            lines.append("")
            for topic in sorted(unobserved)[:20]:
                lines.append(f"- `{topic}`")
            if len(unobserved) > 20:
                lines.append(f"- ... ({len(unobserved) - 20} more)")
            lines.append("")

        # MsgType
        if self.coverage_msg_types:
            lines.append("## Message types observed")
            lines.append("")
            for mt, c in self.coverage_msg_types.most_common(20):
                in_onto_mark = "✓" if mt in self.known_msg_types else "✗"
                lines.append(f"- {in_onto_mark} `{mt}` × {c}")
            lines.append("")

        # 错误事件统计
        if self.log_event_counters:
            lines.append("## Log event categories")
            lines.append("")
            for kind, c in self.log_event_counters.most_common():
                lines.append(f"- `{kind}`: {c}")
            lines.append("")

        # Warnings
        if self.warnings:
            lines.append("## Ingestor warnings")
            lines.append("")
            for w in self.warnings[:50]:
                lines.append(f"- {w}")
            lines.append("")

        out_path.write_text("\n".join(lines), encoding="utf-8")
        self._log(f"[write] {out_path}")

    def _write_stats(self):
        out_path = self.output_dir / "stats.json"
        # by_directory 是 defaultdict,先转成 dict 再调 asdict
        self.stats.by_directory = dict(self.stats.by_directory)
        stats_dict = asdict(self.stats)
        # 加额外汇总
        stats_dict.update({
            "topics_total": len(self.coverage_topics),
            "topics_in_ontology": len(self.coverage_topics.keys() & self.known_topics),
            "topics_out_of_ontology": len(self.coverage_topics.keys() - self.known_topics),
            "fields_observed": len(self.coverage_fields),
            "scalar_series": len(self.scalar_timeseries),
            "warnings_count": len(self.warnings),
            "bytes_read_human": _human_size(self.stats.bytes_read),
        })
        out_path.write_text(json.dumps(stats_dict, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        self._log(f"[write] {out_path}")

    def _print_summary(self):
        print()
        print("=" * 64)
        print(f"  log_ingestor finished in {self.stats.elapsed_seconds}s")
        print("=" * 64)
        print(f"  files scanned : {self.stats.files_scanned}")
        print(f"  files parsed  : {self.stats.files_parsed_ok}")
        print(f"  files skipped : {self.stats.files_skipped}")
        print(f"  bytes read    : {_human_size(self.stats.bytes_read)}")
        print(f"  yaml docs     : {self.stats.yaml_docs_parsed}")
        print(f"  log lines     : {self.stats.log_lines_scanned}")
        print(f"  mcap files    : {self.stats.mcap_files_read} "
              f"(messages: {self.stats.mcap_messages_total} total, "
              f"{self.stats.mcap_messages_kept} kept)")
        print(f"  atop summaries: {len(self.atop_summaries)}")
        print(f"  events kept   : {len(self.events)} / max {self.max_events}")
        print(f"  topics seen   : {len(self.coverage_topics)} "
              f"({len(self.coverage_topics.keys() & self.known_topics)} in ontology)")
        print(f"  warnings      : {len(self.warnings)}")
        print()
        print(f"  → {self.output_dir / 'session.summary.json'}")
        print(f"  → {self.output_dir / 'coverage.report.md'}")
        print(f"  → {self.output_dir / 'stats.json'}")
        print()


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ============================================================
# CLI entry
# ============================================================

def main():
    ap = argparse.ArgumentParser(
        description="Ingest a robot session log directory into ontology-grounded summary."
    )
    ap.add_argument("log_dir", type=Path,
                    help="目录,应包含 bag/ info/ log/ 子目录")
    ap.add_argument("--robot", required=True,
                    help="机器人 id,如 agibot_x2 / g1")
    ap.add_argument("--ontology-dir", type=Path, default=None,
                    help="ontology 目录(可选),用于 grounding 事件到 ontology")
    ap.add_argument("--output", type=Path, default=Path("./diag-output"),
                    help="输出目录(默认 ./diag-output)")
    ap.add_argument("--max-events", type=int, default=10000,
                    help="summary.json 最多保留多少 events(默认 10000,critical 类不占用此配额)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if not args.log_dir.is_dir():
        print(f"error: {args.log_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    # ontology dir 默认推断
    onto_dir = args.ontology_dir
    if onto_dir is None:
        # 尝试 ./robots/<robot>/
        candidate = Path(__file__).resolve().parent.parent.parent / "robots" / args.robot
        if candidate.is_dir():
            onto_dir = candidate
            print(f"[auto] using ontology dir: {onto_dir}", file=sys.stderr)

    ing = LogIngestor(
        log_dir=args.log_dir,
        robot_id=args.robot,
        output_dir=args.output,
        ontology_dir=onto_dir,
        max_events=args.max_events,
        verbose=args.verbose,
    )
    ing.run()


if __name__ == "__main__":
    main()
