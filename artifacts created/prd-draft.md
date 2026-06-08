# PRD: Local-First AI Financial Planner (India, Single Salaried User)

## Problem Statement

An Indian salaried professional's financial picture is scattered across at least five systems: a salary bank account, a stock broker, a mutual fund platform, a credit card, and EPF. No single tool aggregates these into a coherent balance sheet or cash-flow view without requiring cloud accounts, sharing credentials with third parties, or paying subscription fees. Planning toward goals (retirement, home purchase) requires spreadsheet gymnastics or expensive advisors. Existing tools are either too generic (ignore Indian-specific instruments like EPF, SIP) or too cloud-heavy (privacy risk, vendor lock-in).

## Goals

1. Give the user a single, unified balance sheet and monthly cash-flow view derived from CSV exports—no cloud sync, no credentials shared.
2. Let the user state 2–3 financial goals in plain language (e.g., "retire at 55 with ₹5 Cr corpus", "house down-payment of ₹30 L in 4 years") and receive concrete monthly SIP suggestions and goal timelines.
3. Use a deterministic financial model (compound growth, inflation adjustment, SIP math) as the authoritative computation layer; the local LLM narrates from structured outputs only—never interprets raw transactions.
4. Keep everything on the user's laptop: encrypted local DuckDB, optional Ollama 7B–8B for narration, Python CLI interface.

## Non-Goals (v1)

- React or any GUI frontend
- PDF / chart exports
- Tax filing or ITR assistance
- Multi-user or household budgeting
- Cloud LLM as default (Ollama is optional, plain-text fallback always available)
- Real-estate, gold, or stock *trading* (read-only holdings display only)
- Rebalancing automation
- Scenario what-if analysis (defer to v2)
- Compliance / SEBI advisory engine
- Mobile app
- More than 3 active goals simultaneously
- More than 5 CSV source formats in v1

## User Stories / Scenarios

**US-1 — Weekly import:**  
User exports CSV from each of the 5 sources (salary account, broker, MF platform, credit card, EPF) and runs `fp ingest`. The tool normalises, deduplicates, and appends to the encrypted local DB. Duration: < 2 minutes.

**US-2 — Balance sheet view:**  
User runs `fp balance`. Sees net worth broken down by: liquid assets (savings + FD), equity (stocks + MF NAV), EPF balance, liabilities (credit card outstanding + any loans). All figures as of latest import date.

**US-3 — Cash-flow view:**  
User runs `fp cashflow --month 2025-05`. Sees income vs. expense breakdown by category (salary, rent, groceries, SIPs, EMIs, etc.) for the month.

**US-4 — Goal setup:**  
User runs `fp goal add "Retire at 55 with 5Cr corpus"`. Tool parses age, target corpus, and horizon; stores as structured goal record. Confirms back: "Goal stored: ₹5,00,00,000 by 2046-03 (21 years). Assumed inflation: 6%. Required monthly SIP at 12% CAGR: ₹X."

**US-5 — Monthly plan:**  
User runs `fp plan`. Receives a Markdown report with: current surplus/deficit, recommended SIP per goal, allocation suggestion (equity/debt split per horizon), and LLM-narrated plain-English commentary (if Ollama available) or template-based commentary (fallback).

**US-6 — Goal timeline:**  
User runs `fp goal status`. Sees each goal with: target, current savings toward it, projected timeline at current contribution rate, gap.

## Constraints

- **Privacy:** All data stays local. No network calls except optional Ollama (localhost). No telemetry.
- **Encryption:** DuckDB file encrypted at rest (user-provided passphrase or OS keychain). Passphrase never stored in plaintext.
- **Platform:** macOS and Linux (Python 3.11+). Windows not a v1 target.
- **LLM:** Narration is optional; tool must be fully functional without Ollama. LLM receives only structured JSON (aggregated figures, goal params)—never raw transaction rows.
- **CSV formats:** v1 supports exactly 5 template formats (one per source type). Strict schema validation on import; clear error messages for format mismatches.
- **Performance:** Balance sheet and cashflow queries must complete in < 5 seconds on a 3-year dataset (~10K rows).
- **Indian finance specifics:** EPF interest rate configurable (default 8.15% p.a.). SIP assumed equity-oriented (12% CAGR default, user-overridable). Inflation default 6% p.a.

## Open Questions

1. **Passphrase UX:** How should the passphrase be handled across CLI invocations? OS keychain integration (macOS Keychain / libsecret) vs. env-var vs. prompt-each-time?
2. **CSV format drift:** Bank CSV exports change without notice. What's the versioning/override story when a new column appears or a column is renamed?
3. **Deduplication logic:** For broker and MF CSVs, what is the canonical dedup key? (trade date + ISIN + quantity? Settlement ID?)
4. **Goal parsing:** Natural language goal parsing—rule-based regex vs. small local model vs. structured form input? Risk of misparse for retirement goal with inflation vs. real corpus.
5. **EPF projection:** EPF balance in CSV is historical; should the tool project forward using declared salary + employer contribution rate, or just display last known balance?
6. **Liability ingestion:** Credit card CSV covers outstanding balance but not loans (home/personal). v1 scope: credit card only, or allow manual loan entry?
7. **Allocation logic:** How opinionated should the equity/debt allocation suggestion be? Fixed age-based rule (100 minus age) or configurable?
8. **Multi-instrument MF:** If a user holds 8 MF schemes, how are they aggregated for goal allocation? By category (large-cap, ELSS, etc.) or flat total?

## Rough Approach

```
ingestion layer   →  pandas CSV parsers (one per format)
                      schema validation (pandera or pydantic)
                      dedup + normalise → DuckDB (encrypted)

query layer       →  SQL views: balance_sheet, cashflow_monthly
                      Python dataclasses as typed result objects

goal engine       →  deterministic SIP / FV / PV math (no ML)
                      goal store: DuckDB table (id, description, target, horizon, rate)
                      natural language parsing: regex + fallback to structured form

narration layer   →  structured JSON payload → Ollama (llama3 / mistral 7B)
                      template fallback (jinja2) when Ollama unavailable

CLI               →  Typer (fp ingest / balance / cashflow / goal / plan)
                      rich for formatted terminal output

security          →  DuckDB encryption extension (AES-256)
                      passphrase: OS keychain via keyring library
```

## Clarifications from Human Review

**Q: Encryption backend — DuckDB extension not pip-installable; which fallback?**
A: SQLite + SQLCipher. Use SQLCipher as the encrypted persistence layer in place of DuckDB.

**Q: User profile — how does the goal engine know the user's current age?**
A: Inline flag. User supplies `--age` on each `fp goal add` invocation (e.g., `fp goal add --age 34 "Retire at 55 with 5Cr"`). No separate `fp profile` command in v1.

**Q: CSV deduplication keys per source type?**
A: Confirmed: salary/bank = date + description + amount; credit card = date + merchant + amount; broker = trade date + ISIN + quantity + order ID (fallback: date + ISIN + quantity); MF = transaction date + scheme code + units; EPF = entry date + transaction type + amount.

**Q: Goal input — structured form or NLP with confirmation?**
A: NLP with confirmation. User types natural language; tool parses and always shows parsed params ("Parsed as: ₹5Cr by 2046 at 6% inflation — confirm? [y/n]") before storing.

**Q: Import atomicity — roll back all or commit what succeeded?**
A: Commit what succeeded. Valid files are imported; failed files are reported explicitly and skipped. No all-or-nothing rollback.

**Q: Which exact 5 CSV formats for v1?**
A: HDFC salary/savings account, Zerodha broker (Console trades export), Groww/Kuvera MF transaction statement, ICICI credit card, EPFO passbook (UAN portal export).

---

**Key risks:**
- CSV format variability across banks (medium-high likelihood, mitigated by strict validation + clear error UX)
- Ollama latency on low-RAM machines (mitigated by making it optional)
- Goal NLP misparsing leading to wrong SIP numbers (mitigated by always showing parsed params before storing)
- DuckDB encryption extension availability / cross-platform (needs verification)
