# PRD Review: Local-First AI Financial Planner (India, Single Salaried User)

**Review ID:** financial-planner  
**Review Date:** 2026-06-01  
**Legs Completed:** requirements-and-gaps, feasibility-and-scope, ambiguity-and-stakeholders

---

## Executive Summary

The PRD describes a coherent, well-scoped product with a sound technical stack (DuckDB + pandas + Typer + optional Ollama). The problem statement is clear, non-goals are admirably specific, and local-first architecture is the right call for this domain. The PRD is **buildable** but not yet **sprint-ready**: engineers will be forced to make ~20–30% of implementation decisions without explicit guidance.

**Three cross-cutting blockers emerged independently across all review legs:**
1. **DuckDB encryption extension availability** — not bundled with standard pip; requires verification or a pivot to an alternative in week 1
2. **Missing user-profile concept** — the goal engine implicitly requires current age/DOB, but no `fp profile` or equivalent command exists in the PRD
3. **Deduplication keys undefined** — for all five CSV source types, double-import silently corrupts the financial model

These three must be resolved before implementation begins.

---

## Before You Build: Critical Questions

### Blockers — resolve before design phase

**B-1: DuckDB encryption extension** *(feasibility + ambiguity legs)*
The PRD assumes AES-256 via DuckDB's encryption extension, but as of DuckDB 0.10.x this is NOT bundled in the standard `duckdb` pip package. This is a critical-path prerequisite. Either verify the extension is installable in the target environment, or pivot to an alternative (SQLite + SQLCipher, SQLCipher via APSW, or file-level encryption via `age`/`gpg` wrapping the DuckDB file).

**B-2: User profile concept is missing** *(ambiguity leg)*
US-4 parses age from `"Retire at 55"` and computes timeline — but the system has no `fp profile` or equivalent. The goal engine needs the user's current age (and ideally salary + employer EPF contribution rate for forward projection). Define the profile model and a setup/update command before designing the goal engine.

**B-3: Deduplication keys undefined for all five source types** *(requirements + ambiguity legs)*
The open question covers only broker and MF CSVs. Salary account and credit card CSVs (highest weekly import frequency) have no dedup story. Without canonical dedup keys per source, any re-import double-counts income or spending. Decide before building the ingestion layer.

**B-4: Schema migration story missing** *(requirements leg)*
No mention of how the encrypted DuckDB schema evolves when features land (v1.1 adds a new column). Local-first apps without migration strategy become unupgradable. Specify: schema versioning via Alembic, manual SQL scripts, or explicit "re-ingest from CSVs is the upgrade path."

**B-5: Natural-language goal parsing contradicts the determinism principle** *(feasibility + ambiguity legs)*
Goal 3 states "local LLM narrates from structured outputs only — never interprets raw transactions." But OQ-4 raises using a local model for goal parsing. Using an LLM for goal parsing IS interpretation. Recommendation: invert the default — **make structured form input the primary path, NLP parsing an enhancement.** Show parsed params for confirmation before storing.

**B-6: Import atomicity undefined** *(requirements leg)*
If a 5-file import partially fails (files 1–3 succeed, file 4 fails schema validation), is the partial write rolled back or committed? A partially-committed import produces a silently wrong balance sheet. Specify: all-or-nothing transaction per import run, or per-file, or best-effort with explicit status report.

---

## Important But Non-Blocking

**I-1: Passphrase UX decision** *(all three legs)*
Passphrase handling (OQ-1) is on the critical path for usability and security. Prompt-each-time is safest but breaks daily workflow. OS keychain via `keyring` is right but needs platform testing (macOS Keychain stable; Linux backing stores vary). Also: specify the KDF (PBKDF2, Argon2, or scrypt) — this is a security decision, not an implementation detail. Add passphrase recovery guidance or explicit acknowledgment that data is unrecoverable on passphrase loss, plus a `fp export-plain` backup command.

**I-2: First-run initialization missing** *(requirements leg)*
The user stories assume the tool is already initialized. There is no `fp init` command or setup flow. Specify the first-run experience: DB creation, passphrase setup, source configuration.

**I-3: Goal lifecycle (edit/delete) absent** *(requirements leg)*
US-4 adds goals. No story covers editing a goal (target changed) or deleting an abandoned goal. The 3-goal max implies goals can be completed or removed; the mechanism is unspecified. Also: define the 4th-goal-attempt behavior (hard error vs. warning vs. override prompt).

**I-4: Allocation logic (OQ-7) blocks fp plan** *(ambiguity leg)*
US-5 outputs an equity/debt allocation suggestion. OQ-7 is entirely unresolved. This must be decided (even "fixed 100-minus-age rule for v1") before the plan command can be built.

**I-5: Stale data and mixed-freshness balance sheet** *(ambiguity leg)*
US-2 says "all figures as of latest import date" but different source types have different import cadences (EPF monthly, credit card weekly). Define: (a) whether each line item shows its own source date, (b) whether a staleness warning surfaces if any source is older than N days.

**I-6: Ollama binding must be hardened** *(ambiguity leg)*
Constraint says "no network calls except optional Ollama (localhost)" — but Ollama's default listen address is `0.0.0.0:11434` on some installations. The tool must call `127.0.0.1` explicitly, not trust the user's Ollama config. Specify this as a hard constraint in code.

**I-7: The five CSV formats must be named** *(feasibility leg)*
"Exactly 5 CSV source formats" is the v1 constraint, but the formats aren't named. Pin them early (e.g., HDFC salary, Zerodha broker, Groww/Kuvera MF, ICICI credit card, EPFO passbook export). Unnamed formats become a negotiation point during implementation.

**I-8: Inflation-adjusted vs. nominal corpus convention** *(feasibility leg)*
US-4 shows `"Retire at 55 with 5Cr corpus"` but doesn't specify if this is today's rupees or future rupees. This materially affects SIP calculations. Specify the convention (recommend: nominal, clearly labeled) and require display in the goal confirmation output.

---

## Observations

- The 3-goal limit is reasonable MVP scope but must surface a clear CLI error on the 4th attempt, not silent truncation.
- "LLM receives only structured JSON — never raw transaction rows" should be enforced at a typed code boundary, not only documented.
- `fp cashflow --month 2025-05` should document the date format (YYYY-MM) and the default behavior when `--month` is omitted.
- The performance constraint (< 5s / 3-year / 10K rows) is achievable; DuckDB handles this trivially. The 10K row estimate is generous (~3K is more realistic); document accurately to avoid false confidence at scale.
- Ollama narration should document a minimum RAM threshold (7B–8B models need ~8GB) and confirm automatic fallback to template mode below threshold.
- Multiple accounts of the same format type (e.g., two HDFC savings accounts) need a disambiguation story — user-supplied label or filename-based differentiation.
- Error messages for format mismatches should include expected columns, actual columns found, first offending line number, and suggested fix.
- Goal horizon edge cases: negative horizon (user already past target age), corpus already reached (show "goal met" not negative SIP).
- CSV encoding: several Indian bank portals export Windows-1252; specify per-format encoding or auto-detection.

---

## Confidence Assessment

| Dimension | Rating | Notes |
|---|---|---|
| Problem fit | **High** | Target user, pain point, local-first rationale well-articulated |
| Scope tightness | **High** | Non-goals are specific and defensible |
| Core feasibility | **High** | Stack is battle-tested; deterministic math is straightforward |
| Implementation readiness | **Medium** | ~20–30% of decisions undocumented; 3 blockers unresolved |
| Security posture | **Medium-Low** | Encryption approach named but KDF, passphrase UX, Ollama binding underspecified |
| MVP timeline | **4–6 weeks** after blockers resolved |

---

## Next Steps

1. **Resolve B-1 (encryption)** — run a spike to verify DuckDB encryption extension installs cleanly via pip on both macOS and Linux; decide on fallback before any persistence code.
2. **Add `fp profile` to PRD** — define the user profile model and setup UX; this unblocks goal engine design.
3. **Define dedup keys** — for all five source types, document the canonical dedup key in the PRD constraints.
4. **Decide NLP vs. structured form default** (B-5) — strong recommendation: structured form as default, NLP as opt-in enhancement.
5. **Answer OQ-1, OQ-3, OQ-7** — passphrase strategy, dedup for broker/MF, and allocation logic are all on the implementation critical path.
6. **Add `fp init` and goal lifecycle commands** (add/edit/delete/list) to the user stories.
