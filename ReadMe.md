# Idea to Plan — Multi-Agent Planning Pipeline

**Turn a vague feature idea into a reviewed PRD, a design doc, and a ready-to-build task graph — automatically, using a team of AI agents that coordinate like a real engineering org.**

Framework Used : https://github.com/gastownhall/gascity

## Demo

[Watch the live demo](https://drive.google.com/file/d/11CTR0VIX7xUfrCbzKg6mEDtC6MPG54JF/view?usp=drive_link) — agent coordination trace, parallel review dispatch, artifact synthesis, and convoy DAG export (~20–30 min end-to-end).

## Features

| Capability | Description |
|------------|-------------|
| **Multi-agent coordination** | Coordinator (`mayor`) decomposes planning into 9 focused review legs |
| **Parallel review dispatch** | Fan-out to `polecat-review` workers — 3 legs run simultaneously per phase |
| **Mail-driven sync** | No poll/sleep loops; reviewers signal completion via async mail |
| **PRD generation** | Drafts, critiques from 3 angles, then refines with human clarification |
| **Design exploration** | 3 parallel lenses: API/UX, data/scale, security/integration |
| **PRD–design alignment** | 3 sequential passes catch constraint drift, non-goal leakage, story gaps |
| **Plan self-review** | 2 passes: completeness/sequencing, then risk/scope creep |
| **Executable output** | Convoy DAG of task beads with dependencies — ready for implementation agents |
| **Self-validating pipeline** | Deterministic eval checks output against user's stated constraints (0 LLM tokens) |
| **Single human gate** | Exactly one clarification checkpoint where judgment actually matters |

## Architecture

Refer : 
- [System Architecture](./System%20Design/Architecture.jpg) — High-level architecture diagram
- [Sequence Diagram](./System%20Design/Sequence%20Diagram.png) — Pipeline sequence diagram

Orchestration: **GasCity** with fan-out/fan-in via **beads** (task queue) + **mail** (signal) + **Dolt** (versioned SQL backbone).

## Tech Stack

| Layer | Technology |
|-------|------------|
| Orchestration | GasCity (`gc` CLI) |
| Coordination | Mail-driven async (no polling) |
| Task queue | Beads (issue tracker via `bd`) |
| State store | Dolt (versioned SQL database) |
| Workflow definitions | TOML formulas (`mol-idea-to-plan`, `mol-review-leg`) |
| Agents | `mayor` (coordinator), `polecat-review` (lean reviewer) |
| Eval framework | Python (`eval_runner.py`, deterministic — no LLM) |
| Sessions | tmux-backed agent sessions |

## Setup

```bash
# Ensure GasCity city + rig are initialized
cd ~/poc-city
gc reload                      # load formulas + agents

# Verify prerequisites
ls formulas/mol-idea-to-plan.toml formulas/mol-review-leg.toml
grep 'name = "polecat-review"' city.toml
```

### Prerequisites

- GasCity CLI (`gc`) installed and on PATH
- City initialized at `~/poc-city` with `city.toml`
- Rig initialized at `~/poc-project`
- `polecat-review` agent registered in `city.toml`
- Formulas: `mol-idea-to-plan.toml`, `mol-review-leg.toml` in `~/poc-city/formulas/`
- Run `01-demo-hello-gascity.sh` first if starting fresh

## Quick Start

**Run with defaults (scoped financial planner MVP):**

```bash
./demo-idea-to-plan.sh
```

**Run with a custom idea:**

```bash
DEMO13_IDEA="Your idea here" DEMO13_CONTEXT="Your constraints here" \
  ./demo-idea-to-plan.sh
```

**Watch it work (3 terminals):**

```bash
# Terminal 1 — attach to coordinator (answer the human-clarify gate here)
gc session attach mayor          # Ctrl+B then D to detach

# Terminal 2 — follow progress
watch -n 5 'grep CURRENT_STEP ~/poc-city/.plan-reviews/*/state.env; gc session list | grep polecat'

# Terminal 3 — live event stream
gc events --follow
```

## Pipeline Steps

```
Step              Legs   Pattern        What happens
─────────────────────────────────────────────────────────────────────
1. init-run        —     validate       Validate CONTEXT; generate eval-contract.json
2. draft-prd       —     generate       Write first PRD draft
3. prd-review      3     fan-out        requirements-and-gaps │ feasibility-and-scope │ ambiguity-and-stakeholders
4. human-clarify   —     human gate     Mayor asks PM-quality questions; user answers in session
5. design-explore  3     fan-out        api-and-ux │ data-and-scale │ security-and-integration
6. prd-align       3     sequential     requirements & goals → constraints & non-goals → user stories
7. plan-review     2     sequential     completeness & sequencing → risk & scope creep
8. create-beads    —     generate       Emit convoy + task beads + dependency graph
9. eval-output     —     validate       Run eval_runner.py against contract (deterministic)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CITY_DIR` | `~/poc-city` | Path to the GasCity city directory |
| `RIG_DIR` | `~/poc-project` | Path to the rig (project workspace) |
| `REVIEW_TARGET` | `<rig>/polecat-review` | Agent target for review leg dispatch |
| `DEMO13_IDEA` | *(built-in financial planner)* | Override the problem statement |
| `DEMO13_CONTEXT` | *(built-in constraints)* | Override the CONTEXT (must include `Non-goals:` and `Stack:`) |

### CONTEXT format (required for eval)

```
Target: single user, laptop-only, no cloud sync.
Stack: Python CLI; Pandas; DuckDB (encrypted); Ollama 7B-8B optional.
Limits: max 3 active goals.
Non-goals: React UI; PDF/charts; tax filing; multi-user; rebalancing.
Defer: scenario what-if; compliance engine; mobile app.
```

Minimum required labels: `Non-goals:` and `Stack:`. Everything else improves eval coverage.

## Output Artifacts

All written under `~/poc-city`:

```
.prd-reviews/<review-id>/prd-draft.md          PRD first draft
.prd-reviews/<review-id>/prd-review.md         Synthesized PRD critique
.designs/<review-id>/design-doc.md             Design document (evolves across passes)
.plan-reviews/<review-id>/state.env            Progress marker (CURRENT_STEP=)
.plan-reviews/<review-id>/eval-contract.json   Auto-generated eval contract
.plan-reviews/<review-id>/eval-reports/        Eval results (JSON)
.plan-reviews/<review-id>/beads-created.md     Final task list + convoy
```

Inspect the convoy DAG:

```bash
gc convoy list
gc graph <convoy-id> --mermaid
```

## Eval Framework

```
evals/
├── eval_runner.py          # Tier 1 deterministic checker
├── context_parser.py       # CONTEXT → contract (no LLM)
├── generate_contract.py    # LLM-assisted contract generator (richer patterns)
├── extractors.py           # Classifies output lines as "included" vs "non-goal"
├── contract_schema.json    # JSON Schema for contract validation
└── cases/                  # Golden eval cases (frozen contracts)
    └── financial-planner/
        ├── contract.json   # Hand-reviewed, committed
        └── input.env       # The IDEA + CONTEXT for this case
```

**Two modes:**

| | User mode (per-run) | Developer mode (CI) |
|---|---|---|
| When | Every pipeline run (step 9) | On formula/prompt changes |
| Contract | Auto-generated from CONTEXT | Hand-authored + frozen |
| Purpose | Validate THIS run | Catch regressions |
| Failure action | Report to user | Fail CI gate |

**What it checks:**
- Non-goal leakage (context-aware classification)
- Requirement coverage (regex matching against output)
- Stack compliance (required present, forbidden absent)
- Limit enforcement (numeric constraints in data model)
- Artifact completeness and section presence
- Pipeline completion (`state.env` reached final step)

**Run manually:**

```bash
cd evals
python3 eval_runner.py cases/financial-planner/contract.json ~/poc-city
```

## Performance

| Metric | Before (v1) | After (v3) | After (v4 + eval) |
|--------|-------------|------------|-------------------|
| Wall clock | ~4 h | ~20–30 min | ~20–30 min (+10s for eval) |
| Total tokens | ~992K | ~220K | ~220K (eval is 0 tokens) |
| Manual nudges | ~21 | 0 | 0 |
| Review sessions | ~24 | ~9 | ~9 |
| Workflow steps | 12 | 10 | 9 (compressed) |
| Scope drift detected | never | never | automatically |

Key optimizations: removed poll loops (mail-driven), kept reviewer agents always-on, cut review legs 24→9, slimmed reviewer prompt, scoped coordinator re-reads per step.

## Cost Control / Kill Switch

```bash
# Close workflow root (cascades to all child beads)
gc bd close <root-bead-id> --cascade --force

# Kill reviewer sessions
gc session list | grep -E 'polecat-review|polecat' | awk '{print $1}' | xargs -n1 gc session kill
```

## Key Concepts

| Term | What it is |
|------|------------|
| `gc` | GasCity CLI — the control surface for the agent city |
| **City** (`poc-city`) | Environment hosting agents, formulas, and shared state |
| **Rig** (`poc-project`) | Project/workspace the city operates on |
| **Agent** | Long-lived LLM worker with a role (`mayor`, `polecat-review`) |
| **Formula** | Workflow definition (`.toml`) describing steps an agent walks through |
| **Sling** | Dispatch a formula or task to an agent |
| **Bead** | Single task/issue ticket (this system uses beads, not TODO lists) |
| **Convoy** | Group of beads wired as a dependency graph (DAG) |
| **Dolt** | Versioned SQL database — shared state + message queue |
| **Mail** | Async messages between agents — how reviewers signal "done" |

## Documentation

- [System Architecture](./System%20Design/Architecture.jpg) — High-level architecture diagram
- [Sequence Diagram](./System%20Design/Sequence%20Diagram.png) — Pipeline sequence diagram
- [Mental Model](./Mental%20Model%20.png) — Conceptual mental model
- [Reason for 3 Parallel Legs](./Reason%20for%203%20parallel%20legs.png) — Why 3 parallel review legs

## Project Status

Multi-agent planning pipeline — GasCity Demo 13. **v4 (with eval)**

| Phase | Status | Scope |
|-------|--------|-------|
| v1 | Complete | Basic polling coordination (~4h, ~992K tokens) |
| v2 | Complete | Reduced review legs, leaner prompts |
| v3 | Complete | Mail-driven coordination (~20–30 min, ~220K tokens, 0 nudges) |
| v4 | Complete | Deterministic eval bookends (scope drift detection) |
| Future | Planned | CI golden-case regression gates, multi-idea batch runs |
