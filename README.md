# manastone-diag

> Offline fault diagnosis assistant for humanoid robots (AgiBot X2 Ultra and Unitree G1) —
> drop in a log package, describe the symptom, and get a three-round reviewed
> diagnosis report. Every verified case feeds an experience library that makes
> the next diagnosis better.

[![CI](https://github.com/zengury/manastone-diag/actions/workflows/ci.yml/badge.svg)](https://github.com/zengury/manastone-diag/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

**Docs**: [Quickstart](docs/QUICKSTART.md) · [Spec](docs/SPEC.md) ·
[中文文档](docs/zh/README.md) · [Changelog](CHANGELOG.md) · [Sources](SOURCES.md)

---

## What it does

A humanoid robot falls over in the field. Someone hands you a 1&nbsp;GB tar of
logs. `manastone-diag` turns that into a diagnosis:

1. **Ingest** — `log_ingestor` streams `.log` / `.yaml` / `.json` / `.mcap` /
   `.atop` files into a compact structured event stream (privacy-stripped,
   >1&nbsp;GB safe).
2. **Match** — `fault_library` matches symptoms and log keywords against
   per-robot fault rules (Chinese + English), and runs temporal causal inference
   over the event timeline.
3. **Review** — an LLM agent walks you through a three-round review
   (data collection → analysis → report), pausing for your confirmation
   at each round.
4. **Learn** — every diagnosis is archived; field verification feedback
   updates the experience library (sharded storage, WAL-protected;
   measured: 15&nbsp;ms in-process search over 5,000 entries).

The heavy lifting is deterministic Python — the LLM orchestrates and
explains. Everything runs locally; no network access is required for
diagnosis.

## Quick start

Install from PyPI (tools only — no bundled examples or agent assets):

```bash
pip install manastone-diag
manastone-diag-verify   # optional: run bundled verification
```

For the full repository (sample incidents, `examples/`, and `.pi/` agent setup):

```bash
git clone https://github.com/zengury/manastone-diag.git
cd manastone-diag
pip install -r requirements.txt

# Sanity check (should end with all green)
python3 tools/verify_all.py

# Try the bundled sample incident (a stand-mode fall)
python3 tools/log_ingestor.py examples/sample-incident --robot agibot_x2 --output /tmp/diag-out
```

Five-minute walkthrough with the sample incident: [docs/QUICKSTART.md](docs/QUICKSTART.md).

### Running with an LLM agent

The project is agent-framework-agnostic: the assets are the knowledge base
(`knowledge/`), the tool chain (`tools/`), and the diagnosis playbook
(`AGENTS.md`). Any coding-agent framework that reads project instructions and
can run shell commands works:

- **pi** — `./install.sh` installs
  [pi](https://www.npmjs.com/package/@mariozechner/pi-coding-agent)
  and a `manastone-diag` launcher; `.pi/` ships skill files and the system
  prompt.
- **Others (Hermes, Claude Code, …)** — point the agent at the repo root;
  `AGENTS.md` contains the full three-round diagnosis procedure.

## Data sources

| Source | Formats | Notes |
|--------|---------|-------|
| Text logs | `.log` (incl. sliced `.log_N`), `.txt` | fall detection, mode switches, fault codes |
| ROS2 bags | `.mcap` | sensor/joint time series; joint asymmetry analysis |
| Config / state dumps | `.yaml`, `.json` | status snapshots, hardware config |
| System monitor | `.atop` | CPU/memory (requires atop, via WSL on Windows) |

## Knowledge base

Per-robot YAML packs under `tools/knowledge/`:

| Robot | Pack | Fault rules |
|-------|------|-------------|
| AgiBot X2 Ultra | `agibot_x2/` | 11 |
| Unitree G1 | `unitree_g1/` | 8 |

Each pack includes `diagnostic_knowledge.yaml`, `event_patterns.yaml`, `causal_rules.yaml`, and ontology stubs. CI validates each pack and the table above via `scripts/check_knowledge.py`.


## Multi-user / shared experience

Set `MANASTONE_DATA_DIR` to a shared folder to pool the experience library
across a team, or import a colleague's data folder with
`python3 tools/experience_manager.py import <path>` (GUI: `tools/import_tool.py`).

## Scope and boundaries

- **Offline by design.** Diagnosis consumes exported log packages only. The
  tool does not connect to robots, and it contains no code from the
  (private) Manastone runtime kernel. The only sanctioned online interface
  is the runtime's public ledger read API — unused in this version. See
  [SOURCES.md](SOURCES.md).
- Robot-specific knowledge currently targets the **AgiBot X2 Ultra**. The
  schema and pipeline are robot-agnostic; see [docs/SPEC.md](docs/SPEC.md)
  to add another robot.

## License

Licensed under the [Apache License, Version 2.0](LICENSE) (Apache-2.0).

Copyright 2026 zengury. Modifications in v2.x (MCAP joint parsing,
experience shards, archive dashboard) by
[thomastang237](https://github.com/thomastang237).
