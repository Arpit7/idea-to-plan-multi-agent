#!/usr/bin/env bash
# ============================================================================
# DEMO 13: Idea to Plan — Multi-Phase PRD/Design Workflow (~20–30 min)
# Show how mol-idea-to-plan turns a vague feature idea into a reviewed PRD,
# a design doc, and a beaded execution plan — using parallel review legs
# (mol-review-leg) on the lean polecat-review worker pool.
# ============================================================================
#
# PRESENTER NOTES
#   - Optimized poc-city formula (v3): 10 steps, 9 review legs, mail-driven.
#   - Formulas:  ~/poc-city/formulas/mol-idea-to-plan.toml
#   - Workers:   ~/poc-city/agents/polecat-review/ (not full code polecat)
#   - Pipeline:
#       1. init-run
#       2. draft-prd
#       3. prd-review (3 parallel legs: requirements-and-gaps,
#                       feasibility-and-scope, ambiguity-and-stakeholders)
#       4. human-clarify   <-- the one mandatory human gate
#       5. design-exploration (3 legs: api-and-ux, data-and-scale,
#                              security-and-integration)
#       6. prd-align-1, prd-align-2, prd-align-3 (1 leg each)
#       7. plan-review-1, plan-review-2 (1 leg each)
#       8. create-beads (convoy + tasks + deps)
#   - Shorter IDEA/CONTEXT = fewer tokens. Override with DEMO13_IDEA / DEMO13_CONTEXT.
#   - See docs/demo-13-optimization-plan.md for tuning details.
# ============================================================================

set -euo pipefail

CITY_DIR="${CITY_DIR:-$HOME/poc-city}"
RIG_DIR="${RIG_DIR:-$HOME/poc-project}"
RIG_NAME="$(basename "$RIG_DIR")"
REVIEW_TARGET="${REVIEW_TARGET:-${RIG_NAME}/polecat-review}"

if [ ! -d "$CITY_DIR" ] || [ ! -d "$RIG_DIR" ]; then
  echo "ERROR: Run 01-demo-hello-gascity.sh first."
  exit 1
fi

cd "$CITY_DIR"

# --------------------------------------------------------------------------
# PRE-FLIGHT: Require optimized poc-city formulas (do NOT copy gastown pack)
# --------------------------------------------------------------------------
FORMULA_IDEA="$CITY_DIR/formulas/mol-idea-to-plan.toml"
FORMULA_LEG="$CITY_DIR/formulas/mol-review-leg.toml"

if [ ! -f "$FORMULA_IDEA" ] || [ ! -f "$FORMULA_LEG" ]; then
  echo "ERROR: Missing optimized formulas in $CITY_DIR/formulas/"
  echo "  Expected: mol-idea-to-plan.toml, mol-review-leg.toml"
  echo "  See docs/demo-13-optimization-plan.md — do not copy from gastown pack."
  exit 1
fi

if ! grep -q 'name = "polecat-review"' "$CITY_DIR/city.toml" 2>/dev/null; then
  echo "ERROR: polecat-review agent not in $CITY_DIR/city.toml"
  echo "  Add agents/polecat-review/ and register in city.toml (see optimization plan)."
  exit 1
fi

echo "=== Reloading city (formulas + agents) ==="
gc reload 2>/dev/null || echo "(gc reload skipped — start controller if needed)"

# --------------------------------------------------------------------------
# STEP 1: Inspect the formula before running it
# --------------------------------------------------------------------------
# TALK: "Read the recipe first. v3 is 10 steps and 9 review legs — batch
#        dispatch, mail-driven coordination, no poll loops."

echo ""
echo "=== mol-idea-to-plan steps ==="
gc formula show mol-idea-to-plan 2>/dev/null \
  | grep -E "Steps|[├└]──" | head -40 \
  || echo "(mol-idea-to-plan uses graph.v2 contract — step preview not available)"

echo ""
echo "=== mol-review-leg (worker formula) ==="
gc formula show mol-review-leg 2>/dev/null \
  | grep -E "Steps|[├└]──" | head -10 \
  || true

cat <<'EXPLAIN'

=== The dispatch pattern (optimized) ===

For each fan-out step, the coordinator:

  1. Creates ALL leg beads in one batch (gc bd --rig=... create)
  2. Sets metadata: coordinator, review_id, review_phase, review_leg
  3. Slings each to polecat-review: gc sling <rig>/polecat-review <bead> --on mol-review-leg
  4. Checks gc mail inbox for IDEA_REVIEW completion mails (NO poll/sleep loops)
  5. Reads each report from gc bd show <id> notes and synthesizes artifacts

mol-review-leg (worker): read assignment → report in bead notes → mail mayor → close → drain.

Fan-out/fan-in via beads + mail. Dolt is the queue.
EXPLAIN

# --------------------------------------------------------------------------
# STEP 2: Choose a concrete, well-scoped idea
# --------------------------------------------------------------------------
# TALK: "Scope drives cost — a 'build me a startup' idea produces a 700-line
#        design doc and hours of review. The default below is the same
#        financial-planner theme, trimmed to MVP. Use DEMO13_IDEA / DEMO13_CONTEXT
#        to override; avoid pasting the full unscoped paragraph."

# Scoped MVP — same theme as full financial planner, ~60% fewer tokens.
# Full unscoped version (avoid for demo): see docs/demo-13-optimization-plan.md
IDEA="Local-first AI financial planner for one Indian salaried user. Ingest CSV exports from 5 sources (salary account, broker, MF platform, credit card, EPF). Build a unified balance sheet and cash-flow view. User sets 2–3 goals in plain language (e.g. retirement corpus, house down payment). A deterministic model computes SIP needs, inflation, and allocation; a local LLM narrates recommendations from structured outputs only — never raw transactions. MVP output: Markdown plan with monthly SIP suggestions and goal timelines."

CONTEXT="Target: single user, laptop-only, no cloud sync. MVP stack: Python CLI, Pandas ingestion, DuckDB (encrypted local DB), Ollama 7B–8B optional. v1 formats: 5 CSV templates only; manual entry for anything else. v1 goals: max 3 active goals. Non-goals for v1: React UI, PDF/charts, tax filing, multi-user, cloud LLM default, real-estate/gold/stocks beyond read-only holdings, rebalancing automation, financial coach chat. Defer: scenario what-if, compliance engine, mobile app."


echo ""
echo "=== Problem (${#IDEA} chars) ==="
echo "${IDEA:0:200}$([ ${#IDEA} -gt 200 ] && echo ...)"
echo ""
echo "=== Context (${#CONTEXT} chars) ==="
echo "${CONTEXT:0:160}$([ ${#CONTEXT} -gt 160 ] && echo ...)"
echo ""
echo "=== Review target: $REVIEW_TARGET ==="

# --------------------------------------------------------------------------
# STEP 3: Sling mol-idea-to-plan to mayor
# --------------------------------------------------------------------------
# TALK: "We sling the formula to mayor. It runs 10 steps, dispatching review
#        legs to polecat-review. Attach to mayor for the human-clarify gate."

SLING_OUT=$(gc sling mayor mol-idea-to-plan --formula \
  --var problem="$IDEA" \
  --var context="$CONTEXT" \
  --var review_target="$REVIEW_TARGET" \
  2>&1)
echo "$SLING_OUT"

ROOT_BEAD=$(echo "$SLING_OUT" | awk '/wisp root/{gsub(/\)/,"",$6); print $6; exit}')

# --------------------------------------------------------------------------
# STEP 4: Watch the workflow
# --------------------------------------------------------------------------
cat <<EXPECT

=== Watch the workflow (~20–30 min optimized run) ===

Mayor walks 10 steps. Each fan-out creates 3 (or 1) leg beads, slings them
in batch to polecat-review, checks mail, then synthesizes into artifact files.

Artifacts appear under $CITY_DIR (repo root from init-run):
  .prd-reviews/<review-id>/prd-draft.md
  .prd-reviews/<review-id>/prd-review.md
  .designs/<review-id>/design-doc.md
  .plan-reviews/<review-id>/state.env          (CURRENT_STEP= progress)
  .plan-reviews/<review-id>/beads-created.md   (final step)

=== Monitor progress ===

  # Current formula step (resume marker after compaction)
  grep CURRENT_STEP $CITY_DIR/.plan-reviews/*/state.env 2>/dev/null || true

  # Coordinator + review workers
  gc session list | grep -E 'mayor|polecat-review|polecat'

  # Attach to mayor (answer human-clarify in chat — step 4)
  gc session attach mayor
  # Ctrl+B then D to detach

  # Rig review legs
  gc bd --rig $RIG_NAME list --status open --flat | head -20

  # Do NOT nudge unless legs stay open+unassigned >2 min (optimized run needs 0 nudges)

=== Human gate ===

Step human-clarify: mayor asks numbered questions in chat. Reply in the attached
session (not mail). Formula appends answers to prd-draft.md and continues.
EXPECT

# --------------------------------------------------------------------------
# STEP 5: Inspect deliverables after create-beads
# --------------------------------------------------------------------------
cat <<INSPECT

=== Deliverables after create-beads (step 10) ===

  gc convoy list
  gc bd --rig $RIG_NAME list --status open --flat
  gc graph <convoy-id> --mermaid

  ls -la $CITY_DIR/.prd-reviews/
  ls -la $CITY_DIR/.designs/
  ls -la $CITY_DIR/.plan-reviews/

  cat $CITY_DIR/.designs/*/design-doc.md
  cat $CITY_DIR/.plan-reviews/*/beads-created.md

  source $CITY_DIR/.plan-reviews/*/state.env 2>/dev/null
  echo "CURRENT_STEP=\$CURRENT_STEP"
INSPECT

# --------------------------------------------------------------------------
# STEP 6: Cost / kill switch
# --------------------------------------------------------------------------
cat <<BUDGET

=== Cost control / kill switch ===

Optimized run (~12 LLM rounds):
  - 3 PRD review legs
  - 3 design exploration legs
  - 3 PRD alignment (1 leg each)
  - 2 plan self-review (1 leg each)
  + mayor coordinating 10 steps

Stop early:

  # Close workflow root (from sling output)
  gc bd close ${ROOT_BEAD:-<root-bead-id>} --cascade --force

  # Or find open mol-idea-to-plan root
  gc bd list --status open --flat | grep -i idea-to-plan

  gc session list | grep -E 'polecat-review|polecat' | awk '{print \$1}' | xargs -n1 gc session kill 2>/dev/null || true

For a teaching run, use a minimal IDEA (see DEFAULT_IDEA in this script).
BUDGET

cat <<OUTRO

=== DEMO 13 COMPLETE ===
Key takeaways:
  1. mol-idea-to-plan v3: 10 steps, 9 review legs, mail-driven (no poll loops).
  2. polecat-review is a lean worker for mol-review-leg — not the code polecat.
  3. Fan-out/fan-in via beads + mail; mayor synthesizes into repo artifacts.
  4. ONE human gate (human-clarify). Progress tracked in state.env CURRENT_STEP.
  5. Output is beads + convoy DAG under $CITY_DIR — ready to sling for implementation.

Open 3 terminals for a live demo:
  gc session attach mayor
  watch -n 5 'grep CURRENT_STEP $CITY_DIR/.plan-reviews/*/state.env 2>/dev/null; gc session list | grep polecat'
  gc events --follow
OUTRO

if [ -n "${ROOT_BEAD:-}" ]; then
  echo ""
  echo "Workflow root bead: $ROOT_BEAD"
fi


# What each step does
# prd-align-1 — Requirements & goals
# Focus: requirements-goals-alignment (1 worker)

# Checks: Every goal and requirement in the PRD is actually reflected in design-doc.md (Goals, Non-Goals, Key Components).

# Example findings:

# PRD says “local-only, no cloud” but design mentions optional cloud LLM without opt-in guard → must-fix
# PRD goal “3 active goals max” missing from data model → must-fix
# Output: Mayor updates design-doc.md, writes prd-align-round-1.md.

# prd-align-2 — Constraints & non-goals
# Focus: constraints-and-nongoals (1 worker)

# Checks: Technical/business constraints honored; anything in Non-Goals that crept into the design gets cut or flagged.

# Example findings:

# Non-goal was “no React in v1” but design has a full React UI phase → must-fix or defer explicitly
# Constraint “8 GB RAM minimum” not reflected in model choice → should-fix
# Output: Mayor trims scope in design-doc.md, writes prd-align-round-2.md.

# prd-align-3 — User stories & open questions
# Focus: stories-and-open-questions (1 worker)

# Checks: Walk each user story end-to-end through the design; every open question is answered, deferred with owner, or escalated.

# Example findings:

# Story “user uploads HDFC CSV” has no error path for bad format → must-fix
# Open question “who owns tax rule updates?” still unanswered → flag for human or defer doc
# Output: Mayor updates design, writes prd-align-round-3.md.

# Why 3 rounds, not 1? Each round has a narrow lens. One mega-review tends to miss constraint drift and story gaps in the same pass. Three sequential passes = three chances to tighten the doc without re-litigating everything.

# plan-review-1 — Completeness & sequencing
# Focus: completeness-and-sequencing (1 worker)

# Checks the plan as a plan, not PRD match:

# Missing migrations, tests, docs, rollback, ops steps
# Wrong build order (e.g. UI before API)
# Hidden dependencies, unnecessary serialization
# Example findings:

# Phase 2 needs encrypted DB but Phase 0 doesn’t list KDF header → must-fix
# Phase 4 (UI) before Phase 3 (API) blocks integration testing → reorder
# Output: review-round-1.md + design-doc updates.

# plan-review-2 — Risk & scope creep (final plan review)
# Focus: risk-and-scope-creep (1 worker)

# Checks:

# Technical/rollback risks with mitigations
# Gold-plating, over-engineering, things to defer
# Example findings:

# LangGraph in MVP when a simple script suffices → defer
# No test for atomic re-encrypt failure path → add to Phase 0 done-conditions
# Output: review-round-2.md + final design-doc polish → ready for create-beads.

# Why 2 plan rounds? Round 1 fixes “can we build it in this order?” Round 2 fixes “should we build all of this, and what breaks in production?”