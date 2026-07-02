# Robot Coverage Maturity Levels (RCML)

Every robot knowledge pack in `tools/knowledge/<robot_id>/` carries a
maturity level, **L0–L3**. The level tells you what quality of diagnosis to
expect *before* you rely on it — and tells contributors exactly what to
build next to level their robot up.

Rules of the game:

- Each level has **reproducible gates**. L0–L2 are computed automatically
  by `scripts/check_maturity.py`; CI fails if the README table claims a
  level the pack doesn't meet.
- Levels are **pinned per release**: a level claim refers to the tagged
  version you installed, not an aspiration.
- Each level states what it does **not** promise. Read that line before
  trusting a diagnosis.

## The levels

### L0 — Experimental / 实验性

**Gates (automatic):**
- Pack YAML parses; fault/keyword/pattern/causal cross-references are
  complete; all regexes compile (`scripts/check_knowledge.py`).

**Does NOT promise:** any diagnostic quality. Keyword lookup only; treat
results as search hints, not diagnosis.

### L1 — Component diagnosis / 部件级诊断

**Gates (automatic), in addition to L0:**
- ≥ 8 fault rules with repair guidance.
- Symptom keywords cover **both Chinese and English**.
- A sample incident exists under `examples/` for this robot.
- ≥ 1 causal rule **actually fires** on the sample incident
  (dead rules that reference event kinds the pack never produces
  don't count — CI runs the ingest and checks).

**Does NOT promise:** scenario-level root cause (e.g. reconstructing a
fall). You get component-level candidates (which joint, which sensor).

### L2 — Scenario diagnosis / 场景级诊断

**Gates (automatic), in addition to L1:**
- Covers the platform's flagship failure scenario. For humanoids this is
  **falls**: fall-related keywords map to at least one rule, and at least
  one causal rule produces or consumes a `falling_event`.
- ≥ 5 causal rules.
- A non-empty `capability_boundary.yaml` documenting known blind spots.

**Does NOT promise:** field-calibrated accuracy statistics.

### L3 — Field-proven / 现场验证

**Gates (manual evidence, reviewed in PR):**
- ≥ 20 field-verified diagnoses recorded in the experience library, with
  the verification feedback loop (`correct` / `partial` / `wrong`) applied.
- Rule confidence weights adjusted from real outcomes.
- Blind-spot list reviewed within the last quarter.

L3 cannot be claimed by CI alone — it requires linked evidence
(anonymized case IDs) in the PR that raises the level.

## Current status

The authoritative, CI-enforced table lives in the
[README](../README.md#robot-coverage). Summary of how each pack got its
level is visible by running:

```bash
python3 scripts/check_maturity.py
```

## Leveling up your robot / 给你的机器人升级

This is the contribution ladder. Every step is a self-contained PR:

1. **New robot → L0**: copy an existing pack directory, replace the rules
   with your robot's (YAML only, no Python needed), make
   `check_knowledge.py` pass.
2. **L0 → L1**: grow to 8 rules, add bilingual keywords, record or
   synthesize a sample incident under `examples/<robot>-sample-incident/`,
   and make sure at least one causal chain fires on it.
3. **L1 → L2**: study real fall (or your platform's flagship failure)
   logs, add the event patterns + causal chain that reconstruct it, write
   down what the pack still can't see in `capability_boundary.yaml`.
4. **L2 → L3**: use the tool in the field, verify diagnoses
   (`experience_manager verify`), and bring the anonymized receipts.

If you have logs but aren't sure how to turn them into rules, open an
issue with the (anonymized) log excerpt — pattern-writing help is the
easiest thing for maintainers to give.
