# Demo 13 — Idea-to-Plan Eval Framework (Tier 1)

Deterministic checks for `mol-idea-to-plan` outputs. Two modes of operation:

- **User mode** — runs automatically as the final pipeline step; validates every run against the user's own IDEA/CONTEXT.
- **Developer mode** — runs in CI against a fixed golden set; catches formula/prompt regressions.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    mol-idea-to-plan pipeline                     │
│                                                                 │
│  ┌──────────┐    ┌──────────┐         ┌──────────────────────┐  │
│  │ init-run │───▶│ ...steps │────────▶│ create-beads         │  │
│  │          │    │          │         │                      │  │
│  │ validate │    │ draft /  │         │                      │  │
│  │ CONTEXT  │    │ review / │         │                      │  │
│  │          │    │ design   │         │                      │  │
│  │ generate │    │          │         │                      │  │
│  │ contract │    │          │         │                      │  │
│  └──────────┘    └──────────┘         └──────────┬───────────┘  │
│       │                                          │              │
│       ▼                                          ▼              │
│  eval-contract.json                        ┌───────────┐        │
│  (deterministic,                           │eval-output│        │
│   no LLM)                                  │           │        │
│       │                                    │ compare   │        │
│       └───────────────────────────────────▶│ contract  │        │
│                                            │ vs output │        │
│                                            └─────┬─────┘        │
│                                                  │              │
│                                            PASS / FAIL          │
└─────────────────────────────────────────────────────────────────┘
```

---

## User Mode (per-run, automatic)

Every `mol-idea-to-plan` run validates itself. No manual steps required.

### What happens

1. **`init-run`** validates the user's CONTEXT has required labels (`Non-goals:`, `Stack:`).
   If missing, the run stops immediately with a clear error — zero LLM tokens spent.
2. **`init-run`** generates `eval-contract.json` deterministically from the CONTEXT (no LLM).
3. Pipeline runs normally (steps 2–11).
4. **`eval-output`** (final step) runs `eval_runner.py` against the auto-generated contract.
5. Results reported to the user in chat: PASS or itemized failures with evidence.

### CONTEXT format (required for users)

The CONTEXT string must include labeled sections. Minimum required:

```
Non-goals: item1; item2; item3
Stack: tech1; tech2; tech3
```

Optional (parsed if present):

```
Target: who and what environment
Formats: 5 CSV templates only
Limits: max 3 active goals
Defer: item1; item2; item3
```

Full example:

```
Target: single user, laptop-only, no cloud sync.
Stack: Python CLI; Pandas; DuckDB (encrypted); Ollama 7B-8B optional.
Formats: 5 CSV templates only; manual entry for anything else.
Limits: max 3 active goals.
Non-goals: React UI; PDF/charts; tax filing; multi-user; cloud LLM default; rebalancing.
Defer: scenario what-if; compliance engine; mobile app.
```

### What gets validated per-run

| Check | What it catches |
|---|---|
| Non-goal leakage | React UI built despite being listed in Non-goals |
| Requirement coverage | A stated IDEA capability absent from design |
| Stack compliance | Forbidden tech introduced without justification |
| Limit enforcement | "max 3 goals" not reflected in data model |
| Artifact completeness | Expected files missing (PRD, design doc, state.env) |
| Section presence | PRD missing "Non-Goals", design missing "Security" |
| Pipeline completion | Run didn't reach final step |

### Output location

```
.plan-reviews/<review-id>/eval-contract.json    # Auto-generated contract
.plan-reviews/<review-id>/eval-reports/          # JSON report per run
```

---

## Developer Mode (CI, golden set)

Fixed eval cases run on every formula/prompt change to catch regressions.

### Setup

```bash
cd evals

# Golden cases live here — each has a frozen contract
cases/
├── financial-planner/
│   ├── input.env           # The IDEA/CONTEXT fed to the pipeline
│   └── contract.json       # Frozen, human-reviewed contract
├── code-review-bot/
│   ├── input.env
│   └── contract.json
└── inventory-tracker/
    ├── input.env
    └── contract.json
```

### Running in CI

```bash
# Run all golden cases against their last pipeline output
cd evals
for case_dir in cases/*/; do
  contract="$case_dir/contract.json"
  output_dir="/path/to/pipeline/output/for/$(basename $case_dir)"
  python3 eval_runner.py "$contract" "$output_dir" --report-dir reports/
done
```

Exit code is non-zero on any failure — wire into CI as a gate.

### Adding a new golden case

```bash
# 1. Create the case directory
mkdir -p cases/my-new-idea

# 2. Write your input.env (the exact IDEA/CONTEXT for this test)
cat > cases/my-new-idea/input.env << 'EOF'
IDEA="Your product idea here..."
CONTEXT="Target: ... Stack: Python; FastAPI. Non-goals: mobile app; GraphQL. Defer: analytics."
EOF

# 3. Generate draft contract
#    Option A: Deterministic (recommended — no LLM, same as user mode)
python3 context_parser.py cases/my-new-idea/input.env

#    Option B: LLM-assisted (richer patterns, requires review)
python3 generate_contract.py cases/my-new-idea/input.env

# 4. Human reviews and freezes the contract
#    Open cases/my-new-idea/contract.json
#    Verify: requirements, non-goals, leak_patterns, stack, limits
#    Fix any bad regex or missing items
#    Commit

# 5. Run the pipeline with this IDEA/CONTEXT, save output

# 6. Run eval to verify it passes
python3 eval_runner.py cases/my-new-idea/contract.json /path/to/output
```

### Contract generation options

```bash
# Deterministic (no LLM — parses labeled CONTEXT sections)
python3 context_parser.py cases/my-case/input.env

# LLM-assisted (Ollama local, default)
python3 generate_contract.py cases/my-case/input.env

# LLM-assisted (OpenAI)
LLM_BASE_URL=https://api.openai.com/v1 LLM_API_KEY=sk-... LLM_MODEL=gpt-4o \
  python3 generate_contract.py cases/my-case/input.env

# LLM-assisted (Anthropic via proxy)
LLM_BASE_URL=https://your-proxy/v1 LLM_API_KEY=... LLM_MODEL=claude-sonnet-4-20250514 \
  python3 generate_contract.py cases/my-case/input.env

# Dry-run (inspect prompt, no LLM call)
python3 generate_contract.py cases/my-case/input.env --dry-run
```

---

## Directory layout

```
evals/
├── README.md                   # This file
├── eval_runner.py              # Generic Tier 1 checker (deterministic)
├── context_parser.py           # Deterministic CONTEXT → contract (no LLM)
├── generate_contract.py        # LLM-assisted contract generator (richer patterns)
├── extractors.py               # Output artifact section classifiers
├── contract_schema.json        # JSON Schema for contract files
├── .gitignore
├── cases/                      # Golden eval cases (developer mode)
│   └── financial-planner/
│       ├── contract.json       # Frozen, human-reviewed
│       └── input.env           # IDEA + CONTEXT
└── reports/                    # Generated reports (git-ignored)
```

---

## Key differences between modes

| Aspect | User mode | Developer mode |
|---|---|---|
| When it runs | Every pipeline run (step 9) | CI on formula/prompt changes |
| Contract source | Auto-generated from CONTEXT (deterministic) | Hand-authored + frozen |
| Human review of contract | None needed (derived from user's own words) | Required before commit |
| Purpose | Validate THIS run respected THIS user's constraints | Catch regressions across formula versions |
| Failure action | Report to user in chat, ask for decision | Fail CI gate |
| Contract location | `.plan-reviews/<id>/eval-contract.json` | `evals/cases/<name>/contract.json` |

---

## How validation works (both modes)

### Non-goal leakage detection

The checker classifies every line in the output by its section heading:
- Lines under `## Non-Goals`, `## Deferred`, `## Out of Scope` → **safe context**
- Lines under `## Phase`, `## Implementation`, `## Data Model`, `## CLI` → **included features**

A non-goal term matching a `leak_pattern` in the included-features zone = **FAIL**.
The same term appearing in the safe zone = fine (it's being explicitly excluded).

### Requirement coverage

Each requirement has `match_patterns` (regex). If any pattern matches anywhere in the
output, the requirement is considered covered. Fallback: the `term` itself appearing
in the text counts as covered.

### Stack compliance

- `required` items: must appear in the output text. If absent, check for "justified deviation"
  language (pivot, replaced, not available). If `allow_justified_deviation: true`, this is a
  WARN instead of FAIL.
- `forbidden` items: must NOT appear in included-feature sections. Appearing in non-goals
  sections is fine.

---

## Tips for writing good CONTEXT

1. **Always include `Non-goals:`** — this is the highest-value constraint for eval.
   Without it, scope drift can't be detected.
2. **Use semicolons as separators** — commas can appear inside items (e.g., "real-estate/gold beyond read-only holdings").
3. **Be specific in non-goals** — "React UI" is better than "no frontend" (more precise matching).
4. **Name your stack** — "Python CLI; Pandas; DuckDB" not "use Python with some DB."
5. **State limits explicitly** — "max 3 active goals" not "keep goals small."
6. **Separate Defer from Non-goals** — non-goals are permanent exclusions for this version;
   deferred items will come in a future version.
