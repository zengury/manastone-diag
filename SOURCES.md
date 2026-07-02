# SOURCES — Data & Content Provenance / 数据与内容溯源

This project ships knowledge files distilled from third-party materials and
sibling projects. This document lists each source, its license, and the
nature of what was extracted. To request a correction or removal, open a
GitHub issue titled `[SOURCES]` or email zengury@gmail.com.

如需更正或下架某项内容,请提 GitHub issue(标题加 `[SOURCES]` 前缀)或邮件联系。

## Knowledge files / 知识库

| File | Source | Original license | Nature of extraction |
|------|--------|------------------|----------------------|
| `knowledge/hardware.yaml` | AgiBot X2 URDF model (vendor material), imported via the roboonto URDF importer | Vendor documentation | Factual hardware specs: joint names, kinematic structure, limits. No creative content. |
| `knowledge/interfaces.yaml` | Runtime observation of a physical AgiBot X2 Ultra (2026-05 hardware probes) | N/A (first-party observation) | Factual ROS2 topic/interface inventory as observed on-device. |
| `knowledge/diagnostic_knowledge.yaml` | Original work, distilled from real diagnostic cases on AgiBot X2 units | N/A (first-party) | Fault rules, symptoms, repair guidance written for this project. Vendor error-code strings (e.g. "Motor OverTemp") are factual identifiers. |
| `knowledge/event_patterns.yaml`, `knowledge/causal_rules.yaml` | Original work, derived from log analysis of real incidents | N/A (first-party) | Regex patterns over vendor log formats (factual) and causal rules authored for this project. |
| `knowledge/capability_boundary.yaml` | First-party test-day and crash-diagnosis observations | N/A (first-party) | Observed platform limitations, described in terms of externally visible behavior only. |
| `knowledge/actions.yaml`, `knowledge/events.yaml` | Original work | N/A (first-party) | Action/event ontology authored for this project. |

## Skills / 诊断技能 (`.pi/skills/`)

Authored by the roboonto skills effort (`author: roboonto-skills team` in
frontmatter) and adapted for this project. See the
[zengury/roboonto](https://github.com/zengury/roboonto) repository for its
license terms. Content is technical/diagnostic guidance; robot-specific
thresholds come from vendor documentation (factual specs) and first-party
measurements.

## Tools / 工具 (`tools/`)

`log_ingestor.py`, `mcap_reader.py`, `atop_reader.py` originated as modules
of [zengury/roboonto](https://github.com/zengury/roboonto) (same author) and
were forked into this repository. Remaining tools are original to this
project. v2.x additions (MCAP joint parsing, experience shards, archive
dashboard) were contributed by thomastang237 — see LICENSE for the
modification notice.

## Third-party runtime dependencies / 第三方运行时依赖

| Dependency | License | Use |
|------------|---------|-----|
| [PyYAML](https://pypi.org/project/PyYAML/) | MIT | Knowledge base parsing |
| [mcap](https://pypi.org/project/mcap/), [mcap-ros2-support](https://pypi.org/project/mcap-ros2-support/) | MIT | ROS2 bag reading |
| [atop](https://www.atoptool.nl/) (optional, invoked as external binary via WSL) | GPL-2.0 | System monitor file parsing. Invoked as a separate process only; no code linked or included. |

## Explicit non-inclusions / 明确不包含

- No source code from the Manastone runtime kernel (private) is included.
  This project only consumes offline log packages; the only sanctioned
  online interface is the ledger read API, which this version does not use.
- No vendor SDK code is included.
- Real robot serial numbers and factory feedback have been removed or
  anonymized in examples.
