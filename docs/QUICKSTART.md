# Quickstart — five minutes to a diagnosis

This walkthrough uses the bundled synthetic incident in
`examples/sample-incident/` (an anonymized reconstruction of a real case:
an operator accidentally switched a standing robot into position-control
mode, and it fell). No robot required.

## 1. Install

```bash
git clone https://github.com/zengury/manastone-diag.git
cd manastone-diag
pip install -r requirements.txt
python3 tools/verify_all.py   # all checks should be green, exit code 0
```

Requires Python 3.10+. `.mcap` parsing needs the `mcap` packages (installed
above); `.atop` parsing is optional and needs the `atop` binary.

## 2. Ingest the sample logs

```bash
python3 tools/log_ingestor.py examples/sample-incident --robot agibot_x2 --output /tmp/diag-out
```

You get three artifacts:

- `/tmp/diag-out/session.summary.json` — the structured event stream
  (10 events for the sample: mode transitions, a tilt warning, fall events)
- `/tmp/diag-out/coverage.report.md` — which log fields the ontology
  did/didn't recognize
- `/tmp/diag-out/stats.json` — ingest statistics

## 3. Match faults and causal chains

```bash
python3 - <<'EOF'
import json, sys
sys.path.insert(0, 'tools')
from fault_library import FaultLibrary

events = json.load(open('/tmp/diag-out/session.summary.json'))['events']
fl = FaultLibrary()

# Keyword match on the operator's symptom description
for m in fl.match_keywords("站立状态下突然摔倒 JOINT_DEFAULT"):
    print(f"fault {m.rule.id}: {m.rule.name} (confidence {m.confidence})")

# Temporal causal inference over the event timeline
for t in fl.match_timeline(events):
    print(f"causal chain {t.causal_rule.id} (+{t.delta_s:.2f}s, "
          f"confidence {t.confidence}): {t.causal_rule.explanation}")
EOF
```

Expected output: faults `X2-FK-302` (mode switch) / `X2-FK-103` (IMU/balance)
from the symptom text, and causal rule `CR-001` firing on the timeline —
a mode transition followed ~1.2 s later by a fall, which is the sample
incident's root cause.

## 4. Run the full agent loop (optional)

With an LLM agent framework on top you get the conversational three-round
review instead of raw tool calls:

```bash
./install.sh        # installs the pi agent + a `manastone-diag` launcher
manastone-diag      # start a diagnosis session in this repo
```

Then drop a real log tar into `robot-logs/`, describe the symptom in
Chinese or English, and confirm each round. `AGENTS.md` documents the exact
procedure the agent follows — it works with any agent framework that reads
project instructions (pi, Hermes, Claude Code, …).

## 5. Where results go

- Reports and session state: `data/archive/`
- Experience library (grows with each verified diagnosis):
  `data/experience_shards/` — search it with
  `python3 tools/experience_manager.py search "<symptom>"`
- Archive dashboard: `./manage.sh` (Linux/macOS) or `manage.bat` (Windows)
