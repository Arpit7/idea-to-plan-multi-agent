# Beads Created: financial-planner v1
**Date:** 2026-06-01 | **Convoy:** pc-cw7g (fp-financial-planner-v1) | **Rig:** poc-project

---

## Implementation DAG

```
pp-cuss  Set up test infrastructure              [READY — start here]
pp-ez5g  Implement fp config TOML reader/writer  [READY — start here, parallel with pp-cuss]
    ↓
pp-4cwc  Set up APSW+SQLCipher + db.connect()    [ready after pp-cuss]
    ↓
pp-9jvz  SecurePassphrase wrapper                [ready after pp-4cwc]
pp-i3q1  Alembic schema migrations               [ready after pp-4cwc]
    ↓
pp-9zij  fp init command                         [ready after pp-9jvz + pp-i3q1 + pp-ez5g]
pp-mtad  5 CSV parsers                           [ready after pp-cuss + pp-4cwc]
    ↓
pp-cihf  IngestService + fp ingest               [ready after pp-9zij + pp-i3q1 + pp-mtad]
    ↓
pp-mep0  SQL views + fp balance/cashflow         [ready after pp-cihf]
    ↓
pp-kesy  GoalEngine (NLP parser, SIP math)       [ready after pp-mep0]
    ↓
pp-cpgw  NarrationPayload + OllamaClient + fp plan [ready after pp-kesy]
pp-1vsj  fp doctor                               [ready after pp-4cwc + pp-9jvz]
    ↓
pp-94fp  Full test suite + README                [ready after pp-cpgw + pp-1vsj]
```

## Bead Index

| Bead | Title | Week |
|---|---|---|
| pp-cuss | Set up test infrastructure | 1 |
| pp-ez5g | Implement fp config TOML reader/writer | 1 |
| pp-4cwc | Set up APSW+SQLCipher and db.connect() factory | 1 |
| pp-9jvz | Implement SecurePassphrase wrapper + passphrase resolution chain | 1 |
| pp-i3q1 | Implement Alembic schema migrations + startup version check | 1 |
| pp-9zij | Implement fp init command | 1 |
| pp-mtad | Implement 5 CSV parsers | 2 |
| pp-cihf | Implement IngestService and fp ingest command | 2 |
| pp-mep0 | Implement SQL views and fp balance/fp cashflow commands | 3 |
| pp-kesy | Implement GoalEngine: NLP parser, SIP math, goal store CRUD | 3 |
| pp-cpgw | Implement NarrationPayload, OllamaClient, and fp plan command | 4 |
| pp-1vsj | Implement fp doctor command | 4 |
| pp-94fp | Complete test suite, edge cases, and README | 5-6 |

## Dispatch Order

**First batch (parallel, no blockers):**
1. `gc sling coder pp-cuss` — test infrastructure
2. `gc sling coder pp-ez5g` — fp config

**After both close:**
3. `gc sling coder pp-4cwc` — APSW+SQLCipher factory

**After pp-4cwc:**
4. `gc sling coder pp-9jvz` — SecurePassphrase (parallel)
5. `gc sling coder pp-i3q1` — Alembic migrations (parallel)

**After pp-cuss + pp-4cwc:**
6. `gc sling coder pp-mtad` — CSV parsers (parallel with pp-9jvz, pp-i3q1)

**After pp-9jvz + pp-i3q1 + pp-ez5g:**
7. `gc sling coder pp-9zij` — fp init

**After pp-9zij + pp-i3q1 + pp-mtad:**
8. `gc sling coder pp-cihf` — IngestService

**After pp-cihf:**
9. `gc sling coder pp-mep0` — SQL views + reporting

**After pp-mep0:**
10. `gc sling coder pp-kesy` — GoalEngine

**After pp-kesy:**
11. `gc sling coder pp-cpgw` — narration + fp plan (parallel)
12. `gc sling coder pp-1vsj` — fp doctor (parallel, only needs pp-4cwc + pp-9jvz)

**After pp-cpgw + pp-1vsj:**
13. `gc sling coder pp-94fp` — test suite + README

## Key Artifacts

| Artifact | Path |
|---|---|
| Design Document | `.designs/financial-planner/design-doc.md` |
| PRD Draft | `.prd-reviews/financial-planner/prd-draft.md` |
| PRD Review | `.prd-reviews/financial-planner/prd-review.md` |
| Human Clarifications | `.plan-reviews/financial-planner/human-clarifications.md` |
| PRD Align Round 1 | `.plan-reviews/financial-planner/prd-align-round-1.md` |
| PRD Align Round 2 | `.plan-reviews/financial-planner/prd-align-round-2.md` |
| PRD Align Round 3 | `.plan-reviews/financial-planner/prd-align-round-3.md` |
| Plan Review Round 1 | `.plan-reviews/financial-planner/review-round-1.md` |
| Plan Review Round 2 | `.plan-reviews/financial-planner/review-round-2.md` |
| Beads Created (this file) | `.plan-reviews/financial-planner/beads-created.md` |
