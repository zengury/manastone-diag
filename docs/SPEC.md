# SPEC — knowledge schemas, event stream, and pipeline

Normative reference for the data formats in this repository. If code and
this document disagree, the code wins — please file an issue.

## Pipeline overview

```
log package (tar → dir with log/ bag/ info/)
        │
        ▼
tools/log_ingestor.py ──► session.summary.json   (structured event stream)
        │                 coverage.report.md     (ontology gap report)
        │                 stats.json
        ▼
tools/fault_library.py ─► keyword matches   (symptoms_index)
        │                 log matches       (event text)
        │                 timeline matches  (causal_rules)
        ▼
tools/diagnostic_orchestrator.py ─► three-round session state + report
        ▼
tools/experience_manager.py ─► experience shards (learning loop)
```

All stages are plain Python (stdlib + PyYAML + optional mcap); an LLM agent
drives them conversationally using the procedure in `AGENTS.md`.

## Event stream (`session.summary.json`)

Produced by `log_ingestor`. Top-level: `{"meta": {...}, "events": [...], ...}`.
Each event:

| Field | Type | Meaning |
|-------|------|---------|
| `ts` | string | Timestamp as found in the source (verbatim) |
| `epoch_ns` | int \| null | Normalized epoch nanoseconds (cross-source alignment) |
| `kind` | string | Event bucket, e.g. `log.mode_transition`, `log.falling_event` |
| `source_file` | string | Originating file |
| `payload` | object | Kind-specific fields; `payload.text` for log lines |
| `ontology_ref` | string \| null | Reference into the knowledge ontology, if resolved |

Privacy: video, point clouds, GPS, and user identifiers are dropped at
ingest (`PRIVACY_DROP_FIELDS` in `log_ingestor.py`).

## Knowledge files (`knowledge/`)

### `diagnostic_knowledge.yaml`

- `meta` — version info.
- `faults[]` — fault rules:
  `id` (e.g. `X2-FK-302`), `name`, `category`, `severity`
  (`CRITICAL|WARNING|NOTICE|INFO`), `symptoms[]`,
  `root_cause_explanation`, `possible_causes[]`,
  `repair_guide.{immediate,short_term,long_term}[]`.
- `symptoms_index.keywords[]` — free-text triage index:
  `pattern` (Python regex, matched case-insensitively; include Chinese and
  English synonyms) → `fault_ids[]`.
- `repair_templates` — named step lists reusable in reports.

ID convention: `X2-FK-<nnn>` with ranges 0xx=joints, 1xx=sensors,
2xx=power, 3xx=communication/motion.

### `event_patterns.yaml`

`patterns[]`: `priority` (higher matched first, one match per line),
`pattern` (regex over raw log lines), `kind` (event bucket), `severity`,
`keep_full` (never truncate). Loaded by `log_ingestor` at startup; if the
file is missing it falls back to built-in defaults, so editing YAML is the
supported way to extend ingest — no Python changes needed.

### `causal_rules.yaml`

`rules[]`: `id` (e.g. `CR-001`), `cause_kind`/`effect_kind` (event kinds),
optional `cause_filter`/`effect_filter` (regex over `payload.text`),
`within_s` (causal window, seconds), `confidence_boost`, `explanation`
(human-readable template), `fault_ids[]`. `FaultLibrary.match_timeline()`
scans the event stream for cause→effect pairs inside the window.

### `capability_boundary.yaml`

Known blind spots of the platform/logging stack, phrased strictly in terms
of externally observable behavior (what a diagnostician will see), plus
`log_sources[]` — where each log family lives on the robot and what it
covers. Used in review round 3 to annotate confidence.

### `hardware.yaml`, `interfaces.yaml`, `actions.yaml`, `events.yaml`

Robot ontology: joint/sensor inventory (from the vendor URDF), observed
ROS2 topic list, action and event vocabularies. See `SOURCES.md` for
provenance.

## Experience shards (`data/experience_shards/`)

`experience_manager` stores one JSON array per shard (≤5 MB each), plus
`experience_index.json` (tag/keyword index; rebuilt automatically if lost)
and a WAL file protecting writes. Each record:

`experience_id`, `session_id`, `symptoms`, `ai_diagnosis`, `ai_fault_ids[]`,
`ai_confidence` (0–10), `verified` (bool), `actual_cause`,
`actual_fault_ids[]`, `repair_actions[]`, `lessons`, `accuracy_score`,
`tags[]`, `created_at`, `updated_at`.

Verification feedback (`verify` command) flips `verified`, records the
actual cause, and adjusts rule weighting for future matches.

Measured on this codebase: in-process search over 5,000 records ≈ 15 ms;
CLI round trip (including interpreter startup) < 100 ms.

## Adding another robot

1. Ontology: new `hardware.yaml` / `interfaces.yaml` for the robot.
2. Ingest: extend `event_patterns.yaml` with its log formats (YAML-only
   change).
3. Rules: author `faults[]` + `symptoms_index` + `causal_rules` with a new
   ID prefix.
4. Validate: `python3 tools/verify_all.py` must stay green; add a sample
   incident under `examples/`.

The pipeline itself contains no X2-specific logic outside the knowledge
files (the `--robot` flag selects the ontology).
