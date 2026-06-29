"""Fault library loader and matcher for X2 diagnostic knowledge base.

v1.1 — 新增 match_timeline() 时序因果推理。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence, Optional

import yaml


@dataclass(frozen=True)
class RepairGuide:
    immediate: list[str] = field(default_factory=list)
    short_term: list[str] = field(default_factory=list)
    long_term: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FaultRule:
    id: str
    name: str
    category: str
    severity: str
    symptoms: list[str] = field(default_factory=list)
    root_cause_explanation: str = ""
    possible_causes: list[str] = field(default_factory=list)
    repair_guide: RepairGuide = field(default_factory=RepairGuide)
    detection: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MatchedFault:
    rule: FaultRule
    matched_keywords: list[str]
    confidence: float  # 0.0 - 1.0
    matched_log_lines: list[str] = field(default_factory=list)


# ---- 时序因果推理 ----

@dataclass(frozen=True)
class CausalRule:
    """一条已知的因果链规则。"""
    id: str
    cause_kind: str        # 前因事件 kind, 如 "log.mode_transition"
    effect_kind: str       # 后果事件 kind
    cause_filter: str = ""  # 可选: cause payload 文本过滤 regex
    effect_filter: str = "" # 可选: effect payload 文本过滤 regex
    within_s: float = 5.0   # 因果窗口(秒)
    confidence_boost: float = 0.0  # 匹配后对 fault confidence 的加成
    explanation: str = ""   # 人类可读解释模板 (支持 {delta_s} 占位符)
    fault_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TimelineMatch:
    """一条匹配到的因果链。"""
    causal_rule: CausalRule
    cause_event: dict       # 前因事件 (来自 summary.json 的 events)
    effect_event: dict      # 后果事件
    delta_s: float          # 时间差(秒)
    confidence: float       # 该因果链的整体置信度


class FaultLibrary:
    """Loads the X2 diagnostic knowledge base and matches against symptoms.

    v1.1 — 支持 match_timeline() 时序因果推理。
    """

    SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "NOTICE": 2, "INFO": 3}

    def __init__(self, knowledge_path: Path | None = None,
                 causal_rules_path: Path | None = None) -> None:
        self.knowledge_path = knowledge_path or self._default_path()
        self.meta: dict[str, Any] = {}
        self.faults: list[FaultRule] = []
        self.keywords: list[dict[str, Any]] = []
        self.repair_templates: dict[str, Any] = {}
        self._load()

        # 加载因果规则 (可选, 不存在不报错)
        self.causal_rules: list[CausalRule] = []
        self._load_causal_rules(causal_rules_path)

    @staticmethod
    def _default_path() -> Path:
        # Find repo root via pyproject.toml or .git
        here = Path(__file__).resolve()
        for parent in here.parents:
            if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
                candidate = parent / "roboonto/robots/agibot_x2/diagnostic_knowledge.yaml"
                if candidate.exists():
                    return candidate
        # Fallback relative to this file
        return here.parent.parent / "knowledge" / "diagnostic_knowledge.yaml"

    def _load(self) -> None:
        if not self.knowledge_path.exists():
            raise FileNotFoundError(f"Diagnostic knowledge base not found: {self.knowledge_path}")
        raw = yaml.safe_load(self.knowledge_path.read_text(encoding="utf-8"))
        self.meta = raw.get("meta", {})
        self.repair_templates = raw.get("repair_templates", {})
        self.keywords = raw.get("symptoms_index", {}).get("keywords", [])

        for f in raw.get("faults", []):
            rg = f.get("repair_guide", {})
            self.faults.append(
                FaultRule(
                    id=f["id"],
                    name=f["name"],
                    category=f.get("category", "unknown"),
                    severity=f.get("severity", "INFO"),
                    symptoms=f.get("symptoms", []),
                    root_cause_explanation=f.get("root_cause_explanation", "").strip(),
                    possible_causes=f.get("possible_causes", []),
                    repair_guide=RepairGuide(
                        immediate=rg.get("immediate", []),
                        short_term=rg.get("short_term", []),
                        long_term=rg.get("long_term", []),
                    ),
                    detection=f.get("detection", {}),
                )
            )

    # ------------------------------------------------------------------
    # Causal rules loading
    # ------------------------------------------------------------------

    def _load_causal_rules(self, path: Path | None = None) -> None:
        """从 YAML 加载因果规则。路径不存在静默跳过。"""
        if path is None:
            # 默认: knowledge/causal_rules.yaml
            path = Path(__file__).resolve().parent.parent / "knowledge" / "causal_rules.yaml"
        if not path.exists():
            return
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            for r in doc.get("rules", []) if isinstance(doc, dict) else []:
                cause = r.get("cause", {})
                effect = r.get("effect", {})
                self.causal_rules.append(CausalRule(
                    id=r.get("id", "?"),
                    cause_kind=cause.get("kind", ""),
                    cause_filter=cause.get("filter", ""),
                    effect_kind=effect.get("kind", ""),
                    effect_filter=effect.get("filter", ""),
                    within_s=float(r.get("within_s", 5.0)),
                    confidence_boost=float(r.get("confidence_boost", 0.0)),
                    explanation=r.get("explanation", ""),
                    fault_ids=r.get("fault_ids", []),
                ))
        except Exception:
            pass  # 因果规则加载失败不阻塞诊断

    # ------------------------------------------------------------------
    # Timeline causal matching
    # ------------------------------------------------------------------

    def match_timeline(self, events: Sequence[dict]) -> list[TimelineMatch]:
        """时序因果推理: 在事件时间线上匹配已知的因果链。

        Args:
            events: summary.json 中的 events 列表, 每条 event 必须有:
                    - kind: str  (如 "log.mode_transition")
                    - epoch_ns: int | None (纳秒时间戳)
                    - payload: dict (含 text 等字段)

        Returns:
            匹配到的因果链列表, 按置信度降序。
        """
        if not self.causal_rules:
            return []

        matches: list[TimelineMatch] = []

        # 将事件按 causal rule 分组: 对每条 rule, 找所有 cause 和 effect 的事件对
        for rule in self.causal_rules:
            # 收集 cause 候选
            causes = []
            effects = []
            for ev in events:
                kind = ev.get("kind", "")
                # 获取事件文本 (用于 filter 匹配)
                text = self._event_text(ev)
                ts = ev.get("epoch_ns")
                if ts is None:
                    continue
                if kind == rule.cause_kind and self._filter_match(rule.cause_filter, text):
                    causes.append((ts, ev))
                elif kind == rule.effect_kind and self._filter_match(rule.effect_filter, text):
                    effects.append((ts, ev))

            # 找最近的 cause → effect 对 (在 within_s 窗口内)
            for c_ts, c_ev in causes:
                for e_ts, e_ev in effects:
                    if e_ts <= c_ts:
                        continue  # effect 必须在 cause 之后
                    delta_ns = e_ts - c_ts
                    delta_s = delta_ns / 1e9
                    if delta_s <= rule.within_s:
                        # 时间差越小, 置信度越高
                        time_factor = max(0, 1.0 - delta_s / rule.within_s)
                        confidence = 0.5 + 0.4 * time_factor + rule.confidence_boost
                        confidence = min(confidence, 1.0)
                        matches.append(TimelineMatch(
                            causal_rule=rule,
                            cause_event=c_ev,
                            effect_event=e_ev,
                            delta_s=delta_s,
                            confidence=confidence,
                        ))

        # 去重: 同一条 rule 匹配多次时保留置信度最高的
        seen: dict[str, TimelineMatch] = {}
        for m in matches:
            key = f"{m.causal_rule.id}::{m.cause_event.get('source_file','')}::{m.cause_event.get('ts','')}"
            if key not in seen or m.confidence > seen[key].confidence:
                seen[key] = m

        return sorted(seen.values(), key=lambda x: -x.confidence)

    @staticmethod
    def _event_text(event: dict) -> str:
        """从 event dict 中提取可供 filter 匹配的文本。"""
        payload = event.get("payload", {})
        if isinstance(payload, dict):
            return str(payload.get("text", payload.get("value", "")))
        return str(payload)

    @staticmethod
    def _filter_match(filter_pat: str, text: str) -> bool:
        """检查 filter regex 是否匹配 text。空 filter 始终匹配。"""
        if not filter_pat:
            return True
        try:
            return bool(re.search(filter_pat, text, re.IGNORECASE))
        except re.error:
            return False

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def match_keywords(self, text: str) -> list[MatchedFault]:
        """Match a free-text symptom description against keyword index."""
        text_lower = text.lower()
        results: list[MatchedFault] = []
        for kw in self.keywords:
            pat = kw.get("pattern", "")
            if not pat:
                continue
            try:
                if re.search(pat, text_lower):
                    for fid in kw.get("fault_ids", []):
                        rule = self._by_id(fid)
                        if rule:
                            results.append(
                                MatchedFault(
                                    rule=rule,
                                    matched_keywords=[pat],
                                    confidence=0.7,
                                )
                            )
            except re.error:
                continue
        return self._dedup(results)

    def match_logs(self, log_lines: Sequence[str]) -> list[MatchedFault]:
        """Match log lines against keyword patterns."""
        results: list[MatchedFault] = []
        for line in log_lines:
            line_lower = line.lower()
            for kw in self.keywords:
                pat = kw.get("pattern", "")
                if not pat:
                    continue
                try:
                    if re.search(pat, line_lower):
                        for fid in kw.get("fault_ids", []):
                            rule = self._by_id(fid)
                            if rule:
                                results.append(
                                    MatchedFault(
                                        rule=rule,
                                        matched_keywords=[pat],
                                        confidence=0.8,
                                        matched_log_lines=[line.strip()],
                                    )
                                )
                except re.error:
                    continue
        return self._dedup(results)

    def match_metrics(self, metrics: dict[str, float]) -> list[MatchedFault]:
        """Match numeric metrics against rule conditions."""
        results: list[MatchedFault] = []
        for rule in self.faults:
            det = rule.detection
            if not det:
                continue
            conds = det.get("conditions", [])
            logic = det.get("logic", "AND")
            matched = 0
            matched_keys: list[str] = []
            for c in conds:
                metric_key = c.get("metric", "")
                op = c.get("operator", "==")
                val = c.get("value")
                duration = c.get("duration")
                if metric_key == "":
                    continue
                # Allow wildcard matching (joint.*.motor_temp)
                for mk, mv in metrics.items():
                    if self._key_match(metric_key, mk):
                        if self._compare(mv, op, val):
                            matched += 1
                            matched_keys.append(mk)
                            break

            threshold = 1 if logic == "OR" else len(conds)
            if matched >= threshold and threshold > 0:
                confidence = min(0.5 + 0.25 * matched, 0.95)
                results.append(
                    MatchedFault(
                        rule=rule,
                        matched_keywords=matched_keys,
                        confidence=confidence,
                    )
                )
        return self._dedup(results)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _by_id(self, fid: str) -> FaultRule | None:
        for r in self.faults:
            if r.id == fid:
                return r
        return None

    def _dedup(self, matches: list[MatchedFault]) -> list[MatchedFault]:
        seen: dict[str, MatchedFault] = {}
        for m in matches:
            existing = seen.get(m.rule.id)
            if existing is None:
                seen[m.rule.id] = m
            else:
                # Merge keywords and log lines, boost confidence
                kw = list(set(existing.matched_keywords + m.matched_keywords))
                ll = existing.matched_log_lines + m.matched_log_lines
                conf = min(max(existing.confidence, m.confidence) + 0.05, 1.0)
                seen[m.rule.id] = MatchedFault(
                    rule=m.rule,
                    matched_keywords=kw,
                    confidence=conf,
                    matched_log_lines=ll,
                )
        # Sort by severity then confidence
        return sorted(
            seen.values(),
            key=lambda x: (
                self.SEVERITY_ORDER.get(x.rule.severity, 99),
                -x.confidence,
            ),
        )

    @staticmethod
    def _key_match(pattern: str, actual: str) -> bool:
        """Support simple wildcard: joint.*.motor_temp matches joint.knee_pitch.motor_temp"""
        if "*" not in pattern:
            return pattern == actual
        regex = "^" + pattern.replace(".", r"\.").replace("*", r"[^.]+") + "$"
        return bool(re.match(regex, actual))

    @staticmethod
    def _compare(actual: float, op: str, expected: Any) -> bool:
        if expected is None:
            return False
        if op == "==":
            return actual == expected
        if op == "!=":
            return actual != expected
        if op == ">":
            return actual > expected
        if op == "<":
            return actual < expected
        if op == ">=":
            return actual >= expected
        if op == "<=":
            return actual <= expected
        return False

    # ------------------------------------------------------------------
    # OTA helpers
    # ------------------------------------------------------------------

    @property
    def version(self) -> str:
        return str(self.meta.get("version", "0.0.0"))

    @property
    def ota_source(self) -> str:
        return str(self.meta.get("ota_source", ""))

    def export(self) -> dict[str, Any]:
        return {
            "meta": self.meta,
            "faults": [
                {
                    "id": f.id,
                    "name": f.name,
                    "category": f.category,
                    "severity": f.severity,
                    "symptoms": f.symptoms,
                    "root_cause_explanation": f.root_cause_explanation,
                    "possible_causes": f.possible_causes,
                    "repair_guide": {
                        "immediate": f.repair_guide.immediate,
                        "short_term": f.repair_guide.short_term,
                        "long_term": f.repair_guide.long_term,
                    },
                }
                for f in self.faults
            ],
        }
