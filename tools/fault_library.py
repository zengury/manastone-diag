"""Fault library loader and matcher for X2 diagnostic knowledge base."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

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


class FaultLibrary:
    """Loads the X2 diagnostic knowledge base and matches against symptoms."""

    SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "NOTICE": 2, "INFO": 3}

    def __init__(self, knowledge_path: Path | None = None) -> None:
        self.knowledge_path = knowledge_path or self._default_path()
        self.meta: dict[str, Any] = {}
        self.faults: list[FaultRule] = []
        self.keywords: list[dict[str, Any]] = []
        self.repair_templates: dict[str, Any] = {}
        self._load()

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
        return here.parents[3] / "roboonto/robots/agibot_x2/diagnostic_knowledge.yaml"

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
