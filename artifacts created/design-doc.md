# Design Document: Local-First AI Financial Planner

**Review ID:** financial-planner
**Date:** 2026-06-01
**Phase:** design-exploration (synthesis)
**Legs synthesized:** api-and-ux, data-and-scale, security-and-integration

---

## Overview

A CLI-first, local-only financial planner for a single Indian salaried user. Aggregates 5 CSV sources (HDFC bank, Zerodha broker, Groww/Kuvera MF, ICICI credit card, EPFO passbook) into a unified balance sheet and cash-flow view. Goal math is deterministic; an optional local Ollama LLM narrates from structured outputs only.

**Stack confirmed:** Python 3.11+, Typer + rich, SQLite + SQLCipher (APSW), Alembic, optional Ollama at localhost.

---

## 1. CLI Surface

Adopted: **Hybrid minimal-gap design** — flat commands for single-operation tasks; subcommand groups for lifecycle entities.

```
fp init                             # First-run: create DB, set passphrase, configure age
fp ingest [file...]                 # Import CSVs; commit-what-succeeded; print per-file table
fp balance                          # Net worth view; warns if any source > 7 days stale
fp cashflow [--month YYYY-MM]       # Monthly income/expense breakdown (default: prior month)
fp goal add [--age N] "..."        # NLP parse + confirmation; structured flag fallback
fp goal list                        # List goals with auto-integer stable IDs
fp goal delete <id>                 # Remove a goal; max-3 enforced with slot-freeing message
fp goal status [id]                 # Detailed view; all goals if no id
fp plan [--month YYYY-MM]           # Monthly planning report; Jinja2 fallback if Ollama absent
fp config set <key> <value>         # Set age, epf-rate, sip-cagr, inflation, ingest-dir
fp config show                      # Display all config values
fp doctor                           # Health check: SQLCipher version, keyring, Ollama, DB integrity
```

**Universal flags:** `--no-color`, `--quiet`, `--json` (on balance, cashflow).

### Key CLI Decisions

| Decision | Choice | Reason |
|---|---|---|
| Age storage | `fp init` sets it in config; `--age` overrides per-call | Prevents SIP calculation inconsistency across goals set months apart |
| Goal IDs | Auto-integer, stable (not renumbered on delete) | Safe for scripting; intuitive in `fp goal delete 2` |
| NLP parse failure | Structured flag fallback with one-line explanation | Keeps primary path ergonomic without interactive readline |
| `fp ingest` discovery | Both modes: no args → configured ingest-dir; with args → explicit paths | Reduces daily friction without breaking automation |
| `fp balance` staleness | Yellow warning line before table if source > 7 days old | Exit 0 (not 1); stale ≠ broken |
| `fp plan` offline | Jinja2 template fallback; one-line notice at top of output | Ollama absence must not break the core planning loop |
| Multiple HDFC accounts | `fp ingest --source hdfc --label "main"` required if >1 account | Unlabeled ingest rejected when ambiguous |

### First-Run Flow

`fp init` → creates SQLCipher DB → prompts passphrase → offers keyring save → prompts age → writes `fp config` → prints "Run `fp ingest` to load your first CSV."

Any other command that finds no DB prints: `DB not found. Run 'fp init' to get started.` and exits cleanly.

### `fp ingest` Output Format

```
✓ hdfc.csv      → 342 rows imported, 0 skipped
✗ zerodha.csv   → Failed: unexpected column 'OrderNo' on row 1
✓ groww.csv     → 89 rows imported, 3 duplicates skipped
```

Exit 0 if ≥1 file succeeded; exit 1 if all files failed.

---

## 2. Data Model

### Amount Representation

All monetary amounts stored as **INTEGER paise** (multiply rupees × 100). Display layer divides by 100 and formats with `locale.format_string`. This eliminates IEEE-754 drift in SUM aggregations.

Exception: broker quantities stored as REAL (3 decimal places for fractional ETF units); dedup uses `order_id` as tiebreaker, removing the floating-point dedup hazard.

### Schema

```sql
accounts(id PK, source_type, label, currency)

import_runs(id PK, created_at, source_type, file_hash_sha256, 
            rows_imported, rows_skipped, status)  -- status: pending|complete|partial

transactions(id PK, account_id FK, import_run_id FK, txn_date DATE,
             amount_paise INTEGER, direction CHECK('credit'|'debit'),
             category, description, raw_json,
             UNIQUE per-source composite constraint)

broker_trades(id PK, transaction_id FK, isin, quantity REAL, order_id, price_paise)

mf_transactions(id PK, transaction_id FK, scheme_code, units REAL, nav_paise)

epf_entries(id PK, transaction_id FK, entry_date DATE, txn_type)

goals(id PK, description, target_paise, target_date DATE,
      monthly_contribution_paise, assumed_cagr, assumed_inflation,
      created_at, status CHECK('active'|'deleted'))
```

The `raw_json` column on `transactions` is the schema-drift escape hatch — avoids a migration for every bank format change.

### Dedup Keys (DB UNIQUE Constraints)

| Source | Constraint columns |
|---|---|
| Bank (HDFC) | account_id, txn_date, description, amount_paise |
| Credit Card (ICICI) | account_id, txn_date, merchant, amount_paise |
| Broker (Zerodha) | account_id, trade_date, isin, quantity, order_id |
| MF (Groww/Kuvera) | account_id, txn_date, scheme_code, units_purchased |
| EPF (EPFO) | account_id, entry_date, txn_type, amount_paise |

All dedup is enforced at DB level via `INSERT OR IGNORE` — not in Python. Re-imports are safe.

File-level SHA-256 hash in `import_runs` prevents re-importing an identical file (skip silently on hash collision).

### Indexes

- `transactions(account_id, txn_date)` — range scans for cashflow
- `goals(status)` — filter active goals

### Caching

No query cache. At 10K rows, SQLite aggregations run < 100ms. Cache only the structured NarrationPayload, keyed by `(max_import_run_id, goal_hash)`.

### Migrations

Alembic with a custom SQLCipher `env.py` using the `db.connect()` factory — never a plain `sqlite:///path` URL. Forward-only migrations (no downgrade). Schema version checked on every startup; `fp doctor` surfaces stale schema with `fp migrate` suggestion.

---

## 3. Storage & Encryption

### SQLCipher Configuration

```python
# Every DB open sequence — non-negotiable
PRAGMA key = '<passphrase>';
PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;
PRAGMA cipher_iter = 256000;
PRAGMA journal_mode = WAL;
PRAGMA page_size = 4096;
```

SQLCipher 4.x defaults (PBKDF2-SHA512/256K) are pinned explicitly in code — do not rely on library defaults drifting between versions.

### Connection Factory

Single `db.connect(passphrase, path=None)` factory used by all callers (CLI commands, Alembic env.py, test suite). Test suite uses `path=":memory:"`. No PRAGMA key appears anywhere except inside this factory.

Library: **APSW** (not pysqlcipher3) — tracks upstream SQLite faster, no ctypes fragility.

### Passphrase Handling

```python
class SecurePassphrase:
    """Wrapper that prevents passphrase appearing in logs/tracebacks."""
    def __repr__(self): return '<redacted>'
    def __str__(self): return '<redacted>'
    def __format__(self, spec): return '<redacted>'
```

Passphrase stored via `keyring` (namespaced: `fp-local/db-key`). `FP_PASSPHRASE` env var as scripting escape hatch. Fallback to prompt-each-time on headless Linux (keyring.errors.NoKeyringError caught, warning emitted).

---

## 4. LLM Boundary (Ollama)

### Network Isolation

Ollama hardcoded to `http://127.0.0.1:11434` (not `localhost` — avoids IPv6 ::1 resolution edge cases). If a config override is ever added, it must validate the URL is a loopback address (`ConfigurationError` on non-loopback, not silent fallback).

Additional constraints:
- 60s timeout enforced; surface template fallback on timeout, not hang
- 4KB max payload to Ollama
- Model availability checked via `/api/tags` at startup; clear error if absent
- No automatic `ollama pull` — that triggers external network calls

### NarrationPayload (Typed Boundary)

```python
class NarrationPayload(BaseModel):  # Pydantic v2
    balance_summary: dict  # totals by category: liquid, equity, EPF, liabilities
    cashflow_summary: dict  # income total, expense totals by category, surplus/deficit
    goal_params: list[GoalParam]  # (goal_id, target_paise, horizon_months, required_sip_paise)
    # EXCLUDED: individual transactions, merchant names, account numbers, raw CSV content
```

The Ollama-calling function signature: `def narrate(payload: NarrationPayload) -> str`. No other path to Ollama exists.

### NLP Goal Parsing

Goal `add` NLP runs **regex-only** — not Ollama. Keeps Ollama strictly in the narration layer (consistent with PRD's determinism principle). On parse failure: one-line explanation + structured flag form:
```
Could not parse goal. Try: fp goal add --target 50000000 --by-year 2046 --label "Retirement"
```

---

## 5. CSV Parsers

One class per source with explicit class attributes:

```python
class HdfcParser(BaseParser):
    ENCODING = 'windows-1252'
    DATE_FORMAT = '%d/%m/%Y'
    REQUIRED_COLUMNS = ['Date', 'Narration', 'Withdrawal Amt.', 'Deposit Amt.', 'Closing Balance']
    DEDUP_KEY_FIELDS = ['txn_date', 'description', 'amount_paise']
```

| Source | Encoding | Date Format |
|---|---|---|
| HDFC Bank | Windows-1252 | DD/MM/YYYY |
| ICICI Credit Card | Windows-1252 | DD/MM/YYYY |
| Zerodha Broker | UTF-8 | YYYY-MM-DD |
| Groww/Kuvera MF | UTF-8 | DD-MMM-YYYY |
| EPFO Passbook | UTF-8 | DD/MM/YYYY or DD-MM-YYYY |

**Cross-format normalization (all parsers):**
- Amounts: strip Indian commas (`1,00,000` → `100000`), then × 100 → paise
- Dates: normalize to ISO 8601 (YYYY-MM-DD) in DB
- Strings: strip whitespace, NFC Unicode normalization
- Formula injection: strip leading `=`, `+`, `-`, `@` from string fields before storing
- Encoding fallback: charset-normalizer as optional fallback when explicit encoding fails (logged as warning)

**File guards:** Reject files > 10MB before parsing. Warn (not error) if single file > 5,000 rows.

---

## 6. Testing Strategy

### Unit Tests (per parser)
- Happy path: canonical CSV → expected normalized rows
- Encoding: Windows-1252 with rupee symbol → correct decode
- Dedup idempotency: import same file twice → row count unchanged
- Formula injection: cell with `=SUM(A1:A10)` → stored as literal string
- Missing required column → clear error naming the column
- Extra unknown column → accepted without error

### Integration Tests
- Full ingest → balance sheet query pipeline (all 5 formats)
- Multi-account same format: two HDFC accounts → separate line items in balance sheet
- Passphrase round-trip: create → close → reopen correct passphrase (success) / wrong passphrase (clear error)
- Ollama unavailable: `fp plan` completes with template fallback, no crash, no hang past timeout

### Security Tests
- Assert Ollama is called with `127.0.0.1` in URL (mock HTTP layer)
- Assert NarrationPayload contains no individual transaction rows
- Assert passphrase absent from all log output and exception messages
- Assert files > 10MB rejected before parsing

### Property Tests (hypothesis)
- Dedup key uniqueness: any two distinct rows → distinct dedup keys
- Amount normalization: any Indian comma-number string → correct paise value

---

## 7. Open Questions (Carry to Plan)

| ID | Question | Recommendation |
|---|---|---|
| OQ-1 | Two HDFC accounts during ingest | Require `--label` when >1 account of same type exists; reject unlabeled |
| OQ-2 | `fp goal status` horizon display | Show both: `₹5Cr by 2046-03 (21 years remaining)` |
| OQ-3 | `fp cashflow` default month | Prior month (complete data is safer for review) |
| OQ-4 | Broker quantity precision | REAL with 3 decimal places; order_id is dedup anchor |
| OQ-5 | `fp ingest` auto-discovery | Both: no args → `ingest-dir` from config; with args → explicit |
| OQ-6 | EPFO format backward compat | `raw_json` escape hatch; minimum required field set defined per parser version |

---

## 8. Confirmed Architectural Constraints

1. All computation is deterministic Python — Ollama narrates only from structured summaries
2. Ollama receives no individual transactions, merchant names, or account numbers — ever
3. SQLCipher 4 with pinned KDF — DB format must be stable before first real import
4. All amounts in INTEGER paise at storage — display layer converts
5. Dedup enforced at DB level — parsers use `INSERT OR IGNORE`
6. Forward-only Alembic migrations — no downgrade paths
7. `fp plan` always produces output — Jinja2 fallback when Ollama absent or slow
8. APSW + SQLCipher, not pysqlcipher3 — C extension, not ctypes
