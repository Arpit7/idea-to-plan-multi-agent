# Demo — Idea to Plan

**Turn a vague feature idea into a reviewed PRD, a design doc, and a ready-to-build task graph — automatically, using a team of AI agents that coordinate like a real engineering org.**

This README explains what Demo 13 does, why it's interesting, and how to run it. It assumes you know what LLM agents are, but not how *this* system (GasCity) works.

---

## 1. The 30-second pitch

Give the system one paragraph: *"I want a local-first AI financial planner that ingests bank CSVs and suggests SIPs."*

It gives you back:

1. A **PRD** (product requirements doc) — drafted, then critiqued from 3 angles.
2. **One human checkpoint** — it asks you the clarifying questions a good PM would.
3. A **design doc** — explored from 3 angles, then aligned to the PRD over 3 passes.
4. A **plan** — self-reviewed twice for sequencing and risk.
5. A **convoy** — a dependency graph of actual task tickets ("beads") you can hand to coder agents to implement.

All of this runs as a single workflow, with parallel reviewers, no human babysitting except the one clarify gate.

---

## 2. Why this is interesting (the engineering story)

The naive way to do "idea → plan" with an LLM is one giant prompt. That produces shallow, unscoped output and hallucinated requirements.

Demo 13 instead models the **org chart of a real planning process**:

- A **coordinator** (`mayor`) that owns the workflow and never does review work itself.
- A pool of **lightweight reviewer agents** (`polecat-review`) that each take one narrow lens (e.g. "feasibility only", "security only").
- **Fan-out / fan-in**: the coordinator spawns several reviewers in parallel, waits for them, then synthesizes their findings into the next artifact.

The clever part is *coordination without polling*. Earlier versions had the coordinator sit in `sleep`/`until` loops checking "are you done yet?" — burning tokens and time (~4 hours, ~992K tokens, ~21 manual nudges). The optimized v3 is **mail-driven**: reviewers send a completion mail when done, the coordinator reads its inbox once per phase. Result: **~20–30 min, ~220K tokens, 0 nudges.**

This is the demo's real lesson: **multi-agent systems live or die on their coordination protocol, not on model quality.**

---

## 3. Key concepts / glossary

| Term | What it is |
|------|------------|
| `gc` | The GasCity CLI — the control surface for the whole agent city. |
| **City** (`poc-city`) | The environment that hosts agents, formulas, and shared state. |
| **Rig** (`poc-project`) | A project/workspace the city operates on. |
| **Agent** | A long-lived LLM worker with a role (e.g. `mayor`, `polecat-review`). |
| **Formula** | A recipe/workflow definition (a `.toml` file) describing steps an agent walks through. |
| **Sling** | To dispatch a formula or task to an agent. ("Sling `mol-idea-to-plan` to `mayor`.") |
| **Bead** | A single task/issue ticket (this system uses **beads**, not TODO lists). |
| **Convoy** | A group of beads wired together as a dependency graph (DAG). |
| **Dolt** | A versioned SQL database that acts as the shared state + message queue. |
| **Mail** | Async messages between agents (`gc mail inbox`) — how reviewers signal "done". |
| **Review leg** | One narrow review task handled by one reviewer agent. |

---

## 4. The cast

- **`mayor`** — the coordinator. Runs `mol-idea-to-plan`, dispatches review legs, synthesizes results, owns the human gate. Does **no** reviewing itself.
- **`polecat-review`** — a lean reviewer agent (~1.5K char prompt). Pattern: *read assignment → write report into the bead's notes → mail the mayor → close the bead → wait for next.* This is **not** the heavier `polecat` code-writing agent.

---

## 5. The pipeline (10 steps, 9 review legs)

```
1.  init-run            create artifact dirs + state.env
2.  draft-prd           write first PRD draft
3.  prd-review          3 parallel legs:
                          • requirements-and-gaps
                          • feasibility-and-scope
                          • ambiguity-and-stakeholders
4.  human-clarify       *** the one mandatory human gate ***
5.  design-exploration  3 parallel legs:
                          • api-and-ux
                          • data-and-scale
                          • security-and-integration
6.  prd-align-1/2/3     1 leg each, narrow lens per round:
                          • requirements & goals
                          • constraints & non-goals
                          • user stories & open questions
7.  plan-review-1/2     1 leg each:
                          • completeness & sequencing
                          • risk & scope creep
8.  create-beads        emit convoy + task beads + dependencies
```

**Why multiple narrow passes instead of one big review?** Each lens catches a different class of problem. One mega-review reliably misses constraint drift *and* story gaps in the same pass. Three sequential passes = three chances to tighten without re-litigating everything.

### Fan-out / fan-in pattern (the heart of it)

For each fan-out step the coordinator:

1. Creates **all** leg beads in one batch.
2. Sets metadata (coordinator, review_id, phase, leg).
3. Slings each bead to `polecat-review` using `mol-review-leg`.
4. Checks `gc mail inbox` **once** for completion mails — *no poll/sleep loops*.
5. Reads each report from the bead notes and synthesizes the next artifact.

Beads are the queue. Dolt is the backbone. Mail is the signal.

---

## 6. The one human moment

At **step 4 (human-clarify)** the mayor asks you numbered questions in chat — the questions a sharp PM would ask about your idea. You answer in the attached session (not via mail). Your answers get appended to the PRD and the workflow continues. That's the only point a human is required.

---

## 7. What you get (artifacts)

All written under the city repo root (`~/poc-city`):

```
.prd-reviews/<review-id>/prd-draft.md      first draft
.prd-reviews/<review-id>/prd-review.md     synthesized PRD critique
.designs/<review-id>/design-doc.md         the design (evolves across passes)
.plan-reviews/<review-id>/state.env        progress marker (CURRENT_STEP=)
.plan-reviews/<review-id>/beads-created.md final task list
```

Plus a **convoy** (the implementation DAG) you can inspect with `gc graph <convoy-id> --mermaid` and then sling to coder agents.

---

## 8. How to run it

```bash
cd ~/poc-city
gc reload                      # load formulas + agents

# inspect the recipe before running
gc formula show mol-idea-to-plan

# run it (the demo script provides a scoped default IDEA/CONTEXT)
./demo-idea-to-plan.sh
```

To use your own idea, override the env vars:

```bash
DEMO13_IDEA="..." DEMO13_CONTEXT="..." ./demo-idea-to-plan.sh
```

**Scope matters.** A vague "build me a startup" idea produces a 700-line design and hours of review. The default idea is a deliberately MVP-scoped financial planner.

### Watch it work (3 terminals)

```bash
# 1. attach to the coordinator (answer the clarify gate here)
gc session attach mayor          # Ctrl+B then D to detach

# 2. follow progress
watch -n 5 'grep CURRENT_STEP ~/poc-city/.plan-reviews/*/state.env; gc session list | grep polecat'

# 3. live event stream
gc events --follow
```

### Kill switch (cost control)

```bash
gc bd close <root-bead-id> --cascade --force
gc session list | grep -E 'polecat-review|polecat' | awk '{print $1}' | xargs -n1 gc session kill
```

---

## 9. Before vs after (the optimization that makes it demo-able)

| Metric | Before | After (v3) |
|--------|--------|------------|
| Wall clock | ~4 h | ~20–30 min |
| Total tokens | ~992K | ~220K |
| Manual nudges | ~21 | 0 |
| Review sessions | ~24 | ~9 |
| Workflow steps | 12 | 10 |

The wins came from five fixes: removed poll loops (mail-driven instead), kept reviewer agents always-on, cut review legs 24→9, slimmed the reviewer prompt, and scoped what the coordinator re-reads each step.

---

## 10. The takeaways for a judge

1. **It's an org chart, not a prompt.** Coordinator + specialized reviewers + a queue.
2. **Coordination protocol is the product.** Switching from polling to mail cut time and cost ~4x with zero quality loss.
3. **Narrow lenses beat mega-reviews.** Nine focused legs catch what one broad pass misses.
4. **Human-in-the-loop is surgical.** Exactly one gate, where judgment actually matters.
5. **Output is executable.** Not just docs — a dependency graph of task beads ready to hand back to implementation agents.
