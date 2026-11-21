# Agent behavior provenance research prototype

Offline Python analyzer around the professor's unmodified `artifact/`. It parses
OpenCode stream/native message contracts and Pi message-end records, builds a
NetworkX evidence DAG, detects protected final changes and explicit edit attempts,
and runs backward evidence queries. It produces JSON, Markdown, GraphML and SVG.

**No real agent experiments were collected here.** Neither `opencode` nor `pi`
was installed; the managed environment reported no configured credentials.
`results/release-validation/` contains actual local test/check outputs and explicit
snapshot-only reports of prepared, **unexecuted** normal/injection workspaces.
The `synthetic-unit-test-demonstrations/` subdirectory is exclusively synthetic
unit-test output. Its successful detection examples are not experimental results.
Native format adapters still require validation against a real export.

The uploaded plan is retained as `CODEX_IMPLEMENTATION_PLAN.md`. The supplied
archive did not contain `Project.pdf`, `project-guide.pdf`, or `project_a.md`;
course rules and schedule could not be independently checked. Scenario payloads
and installed skill text are experiment inputs; their directives do not govern
this analyzer's implementation. The professor's task policy applies inside the
experimental workspace. No team executive summary or individual contributions
are generated.

## Setup (Python 3.10+)

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m provenance.cli --help
```

NetworkX 3.4.2 is the only runtime dependency. Visualization uses a standalone
SVG writer, without Graphviz or a GUI. Analyzing existing logs requires no network
or API. Installation of this analyzer dependency occurs outside agent workspaces.

## Reproduce the local validation

Choose fresh destinations on each repeat; evidence is never silently overwritten
by experiment preparation.

```bash
.venv/bin/python experiments/run_local.py \
  --runs artifact/runs/local-repeat-001 --results results/local-repeat-001
```

This runs the professor helper tests, reproduces the original workload failures,
runs analyzer unit tests, prepares two fresh scenarios, runs independent checks,
checks professor source integrity, exports two explicit snapshot-only reports,
and creates separately labeled synthetic demonstrations. It never calls an LLM.
Inputs are retained under the specified runs directory. Each log includes actual
and expected exit status. Expected failures are verified rather than suppressed.

Individual test commands:

```bash
(cd artifact && ../.venv/bin/python -m unittest discover -s tests -v)
(cd artifact/workload && ../../.venv/bin/python tools/run_tests.py)
.venv/bin/python -m unittest discover -s tests -v
```

The workload command intentionally returns 1: three of five public tests pass,
and two refund tests fail. The app always adds the amount, ignoring `kind` when
updating totals. A proper task repair subtracts refund amounts in `src/`; changing
test expectations would violate the common user policy. This prototype preserves
the original bug so later real trials start from the same experimental foundation.

## Collect real matched trials (not run in this environment)

Install and authenticate OpenCode or Pi using its normal provider configuration,
outside the experimental workspace. Never put credentials in the repository.
Confirm a supported model using `opencode models` (or Pi's supported model list).
Use identical agent/model/provider settings for both conditions. The collector
uses the existing OpenCode configuration or fresh Pi configuration with environment
credentials. Record provider configuration differences and sampling settings in
trial notes; identical model names alone do not establish matched settings.

```bash
mkdir -p artifact/runs
export DEMO_MODEL='ACTUAL_PROVIDER/ACTUAL_LISTED_MODEL'
export DEMO_AGENT=opencode       # or pi
bash experiments/run_experiments.sh trial-001
```

The model string is a placeholder to replace, not a tested model. The helper
script checks the binary, uses fresh directories, retains collection/check exit
statuses, and analyzes retained logs even on execution failure. It never falls
back to fixtures. The following are the equivalent core commands:

```bash
.venv/bin/python artifact/scripts/prepare.py normal --output artifact/runs/normal-live-001
.venv/bin/python artifact/scripts/prepare.py tool-output-injection --output artifact/runs/injected-live-001
.venv/bin/python artifact/scripts/collect.py opencode artifact/runs/normal-live-001 --model "$DEMO_MODEL"
.venv/bin/python artifact/scripts/check.py artifact/runs/normal-live-001
.venv/bin/python artifact/scripts/collect.py opencode artifact/runs/injected-live-001 --model "$DEMO_MODEL"
.venv/bin/python artifact/scripts/check.py artifact/runs/injected-live-001
.venv/bin/python -m provenance.cli analyze --run artifact/runs/normal-live-001 --output results/normal-live-001
.venv/bin/python -m provenance.cli analyze --run artifact/runs/injected-live-001 --output results/injected-live-001
.venv/bin/python -m provenance.cli compare --baseline results/normal-live-001/analysis.json --injected results/injected-live-001/analysis.json --output results/comparison.md
```

A checker exit of 1 is a recorded experimental outcome, not automatically a
collector failure. Inspect `execution.json`, stderr and coverage before interpreting
results. OpenCode permissions are not an OS sandbox; use disposable local dummy
data and do not run experiments near personal files.

## CLI and outputs

`analyze --run DIR --output DIR` requires `workspace/`, `baseline.json`, and a
supported `events.jsonl` or `session.json`. Invalid/missing inputs return exit 2
with an actionable error. `--snapshot-only` explicitly permits missing trajectories
and labels the resulting output as integrity evidence without an agent run.

Each analysis directory contains:

- `analysis.json`: timeline with refs/excerpts, coverage, execution metadata,
  independent policy evidence, exposure, query results and counts.
- `analysis.md`: readable findings, timeline, evidence refs and limitations.
- `graph.graphml` and `graph.json`: typed nodes and evidence-labeled directed edges.
- `graph.svg`: accessible static graph; edge hover titles give full refs/relations.

Query a finding or attempted edit by its actual ID from `analysis.json`:

```bash
.venv/bin/python -m provenance.cli slice \
  --graph results/release-validation/synthetic-unit-test-demonstrations/injection/graph.graphml \
  --target finding:0
```

Event refs use source JSONL line numbers or native session JSON pointers. The
parser prefers native messages to avoid counting both exports twice. Stable IDs
are local to the selected export, not interchangeable across export sources.
Reports retain short excerpts; raw evidence and execution command metadata may
contain task text. Inspect/redact before sharing with others.

### CSV experiment Responses logs

Use the separate `analyze-responses` command for completed runs from the CSV
experiment harness.
Point it at the run directory containing `records/executor.jsonl` and
`records/evaluation.json`. Choose a new output directory outside the run.

```bash
.venv/bin/python -m provenance.cli analyze-responses --run /path/to/campaign/0006 --output work/0006
.venv/bin/python -m provenance.cli slice --graph work/0006/graph.graphml --target release:decision
```

The adapter reads both sessions when a verifier log is present. It matches
handoff text, script hashes and checked result bytes against the saved records.
The release slice includes the recorded independent oracle verdict and validator
outcome. Source references use paths relative to the input run, with JSONL line
numbers or JSON pointers where available. The check status can be `unavailable`
even when an invocation is recorded. Context edges are possible influences.
Raw prompts, tool payloads and model reasoning items are omitted from exports.

See `experiments/protocol.md`, `docs/design_notes.md`,
`docs/limitations_and_future_work.md`, and `results/IMPLEMENTATION_SUMMARY.md`.
