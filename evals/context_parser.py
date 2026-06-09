#!/usr/bin/env python3
"""
context_parser.py — Parse semi-structured CONTEXT into an eval contract.

No LLM needed. Expects labeled sections in the CONTEXT string:

Required labels:
  Non-goals:   (semicolon or comma separated list)
  Stack:       (semicolon or comma separated list)

Optional labels:
  Target:      (free text description)
  Formats:     (e.g., "5 CSV templates only")
  Limits:      (e.g., "max 3 active goals")
  Defer:       (semicolon or comma separated list)

Usage:
    # As a library
    from context_parser import parse_context, build_contract, validate_context

    errors = validate_context(context_string)
    if errors:
        print("Fix these:", errors)
    else:
        contract = build_contract(idea, context_string, case_id="my-case")

    # As a CLI
    python3 context_parser.py cases/my-case/input.env
    python3 context_parser.py --context "Non-goals: X; Y; Z. Stack: Python, Pandas."
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path


# ─── Label definitions ────────────────────────────────────────────────────────

# Required labels — validation fails without these
REQUIRED_LABELS = ["non-goals", "stack"]

# All recognized labels (order doesn't matter in input)
KNOWN_LABELS = {
    "target": ["target"],
    "stack": ["stack", "mvp stack", "tech stack", "technology"],
    "formats": ["formats", "v1 formats", "input formats"],
    "limits": ["limits", "v1 goals", "constraints", "scope"],
    "non-goals": ["non-goals", "non-goals for v1", "non goals", "nongoals", "not in v1"],
    "defer": ["defer", "deferred", "later", "v2"],
}

# Build reverse lookup: alias → canonical name
_ALIAS_MAP = {}
for canonical, aliases in KNOWN_LABELS.items():
    for alias in aliases:
        _ALIAS_MAP[alias.lower()] = canonical


# ─── Parsing ──────────────────────────────────────────────────────────────────

def _split_items(text: str) -> list[str]:
    """Split a label's value into individual items.

    Handles:
      - Semicolons: "React UI; PDF/charts; tax filing"
      - Commas: "React UI, PDF/charts, tax filing"
      - Mixed: "React UI; PDF/charts, tax filing"

    Prefers semicolons if present (commas may appear inside items like "real-estate/gold beyond read-only holdings").
    """
    text = text.strip().rstrip(".")

    if ";" in text:
        items = [i.strip() for i in text.split(";")]
    else:
        items = [i.strip() for i in text.split(",")]

    return [i for i in items if i]


def _extract_number(text: str) -> int | None:
    """Extract the first integer from a text string."""
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else None


def parse_context(context: str) -> dict[str, str]:
    """
    Parse labeled sections from a CONTEXT string.

    Returns a dict mapping canonical label names to their raw text values.
    Example: {"non-goals": "React UI; PDF/charts; ...", "stack": "Python CLI, Pandas, ..."}
    """
    sections = {}

    # Build regex that matches any known label at start of a segment
    # Labels can appear as "Label:" at the start or after a period/newline
    all_aliases = sorted(_ALIAS_MAP.keys(), key=len, reverse=True)
    label_pattern = "|".join(re.escape(a) for a in all_aliases)

    # Find all label positions
    pattern = re.compile(
        rf"(?:^|(?<=\.\s)|(?<=\.\s\s)|(?<=\n))({label_pattern})\s*:\s*",
        re.IGNORECASE | re.MULTILINE,
    )

    matches = list(pattern.finditer(context))

    for i, match in enumerate(matches):
        label_text = match.group(1).lower().strip()
        canonical = _ALIAS_MAP.get(label_text, label_text)

        # Value extends from end of label to start of next label (or end of string)
        value_start = match.end()
        value_end = matches[i + 1].start() if i + 1 < len(matches) else len(context)
        value = context[value_start:value_end].strip().rstrip(".")

        sections[canonical] = value

    return sections


def validate_context(context: str) -> list[str]:
    """
    Validate that a CONTEXT string has all required labeled sections.

    Returns a list of error messages (empty = valid).
    """
    errors = []
    sections = parse_context(context)

    for required in REQUIRED_LABELS:
        if required not in sections:
            aliases = KNOWN_LABELS[required]
            hint = " or ".join(f'"{a}:"' for a in aliases[:3])
            errors.append(
                f"Missing required section '{required}'. "
                f"Add a label like {hint} followed by a semicolon-separated list."
            )
        elif not sections[required].strip():
            errors.append(f"Section '{required}' is empty — list at least one item.")

    return errors


# ─── Contract building ────────────────────────────────────────────────────────

def _make_leak_patterns(term: str) -> list[str]:
    """Generate leak detection regex for a non-goal term.

    Strategy: use the most distinctive word(s) from the term near
    implementation verbs. Multi-word terms are harder to match, so we
    pick the word least likely to appear generically.
    """
    words = term.split()

    # Filter out very generic words that cause false positives
    generic_words = {"the", "a", "an", "for", "in", "of", "to", "and", "or",
                     "beyond", "read-only", "default", "only", "based",
                     "cloud", "financial", "real", "active"}
    distinctive_words = [w for w in words if w.lower() not in generic_words and len(w) > 2]

    if not distinctive_words:
        distinctive_words = words[:1]  # fallback to first word

    # Use the longest distinctive word as anchor
    anchor = max(distinctive_words, key=len)
    escaped_anchor = re.escape(anchor)

    # For compound terms like "React UI" or "PDF/charts", match the specific thing
    # being implemented, not just mentioned
    impl_verbs = r"(?:implement|phase|build|component|create|route|endpoint|schema|module)"

    return [
        rf"(?i){escaped_anchor}.*{impl_verbs}",
        rf"(?i){impl_verbs}.*{escaped_anchor}",
    ]


_DEFAULT_SAFE_PATTERNS = [
    "(?i)non.?goal",
    "(?i)not.*v1",
    "(?i)defer",
    "(?i)explicit.*non",
    "(?i)out.*of.*scope",
]


def build_contract(idea: str, context: str, case_id: str = "auto") -> dict:
    """
    Build a complete eval contract from IDEA + semi-structured CONTEXT.

    No LLM involved — pure parsing.
    """
    sections = parse_context(context)

    # ── Meta ──
    if case_id == "auto":
        # Derive from first few words of idea
        words = re.sub(r"[^a-z0-9\s]", "", idea.lower()).split()[:4]
        case_id = "-".join(words)

    contract = {
        "meta": {
            "case_id": case_id,
            "created_at": date.today().isoformat(),
            "description": idea[:120],
        },
        "requirements": [],
        "non_goals": [],
        "deferred": [],
        "stack": {
            "required": [],
            "forbidden": [],
            "allow_justified_deviation": True,
        },
        "limits": {},
        "artifacts": {
            "required_files": [
                ".prd-reviews/*/prd-draft.md",
                ".prd-reviews/*/prd-review.md",
                ".designs/*/design-doc.md",
                ".plan-reviews/*/state.env",
            ],
            "required_sections": {
                ".prd-reviews/*/prd-draft.md": [
                    "Problem Statement",
                    "Goals",
                    "Non-Goals",
                    "Constraints",
                ],
                ".prd-reviews/*/prd-review.md": ["Executive Summary"],
                ".designs/*/design-doc.md": ["Data Model", "Security"],
            },
        },
    }

    # ── Non-goals ──
    if "non-goals" in sections:
        items = _split_items(sections["non-goals"])
        for i, item in enumerate(items, 1):
            contract["non_goals"].append({
                "id": f"NG{i}",
                "term": item,
                "leak_patterns": _make_leak_patterns(item),
                "safe_patterns": _DEFAULT_SAFE_PATTERNS,
            })

    # ── Stack ──
    if "stack" in sections:
        items = _split_items(sections["stack"])
        # Normalize: extract the core technology name (strip qualifiers in parens, "optional", etc.)
        normalized = []
        for item in items:
            # Remove parenthetical qualifiers: "DuckDB (encrypted local DB)" → "DuckDB"
            core = re.sub(r"\s*\(.*?\)\s*", "", item).strip()
            # Remove trailing qualifiers: "Ollama 7B-8B optional" → "Ollama"
            core = re.split(r"\s+(?:optional|required|encrypted|local)\b", core, flags=re.IGNORECASE)[0].strip()
            # Remove version strings: "7B-8B", "3.11+"
            core = re.sub(r"\s+\d+[\w.–-]*$", "", core).strip()
            # Remove role suffixes: "Pandas ingestion" → "Pandas"
            core = re.split(r"\s+(?:ingestion|processing|storage|backend|frontend|layer)\b", core, flags=re.IGNORECASE)[0].strip()
            if core:
                normalized.append(core)
        contract["stack"]["required"] = normalized

    # ── Deferred ──
    if "defer" in sections:
        items = _split_items(sections["defer"])
        for i, item in enumerate(items, 1):
            contract["deferred"].append({"id": f"D{i}", "term": item})

    # ── Limits ──
    if "limits" in sections:
        text = sections["limits"]
        # Try to extract "max N <thing>" patterns
        limit_matches = re.finditer(r"(?i)(max|limit|up to|at most)\s+(\d+)\s+(.+?)(?:[;,.]|$)", text)
        for match in limit_matches:
            value = int(match.group(2))
            thing = match.group(3).strip()
            key = re.sub(r"\s+", "_", thing.lower())[:30]
            contract["limits"][key] = {
                "value": value,
                "match_pattern": rf"(?i)(max|limit|cap).*{value}.*{re.escape(thing[:15])}",
                "comparison": "eq",
            }

    # Also scan formats section for numbers
    if "formats" in sections:
        num = _extract_number(sections["formats"])
        if num:
            contract["limits"]["formats"] = {
                "value": num,
                "match_pattern": rf"(?i)(exact|support|v1).*{num}.*(csv|format|source|template)",
                "comparison": "eq",
            }

    # ── Requirements (derived from IDEA) ──
    # Extract key noun phrases from IDEA as basic requirement terms
    # This is intentionally conservative — only obvious, stated capabilities
    idea_requirements = _extract_requirements_from_idea(idea)
    contract["requirements"] = idea_requirements

    return contract


def _extract_requirements_from_idea(idea: str) -> list[str]:
    """
    Extract obvious requirements from the IDEA string.

    Uses keyword patterns to identify stated capabilities.
    Returns a list of requirement dicts.
    """
    requirements = []
    req_id = 1

    # Pattern: "Ingest/Import/Consume X from Y sources"
    ingest_match = re.search(r"(?i)(ingest|import|consume|read|parse).*?(\d+)\s*(source|csv|format|file)", idea)
    if ingest_match:
        num = ingest_match.group(2)
        requirements.append({
            "id": f"R{req_id}",
            "term": f"{num} sources ingestion",
            "description": f"Ingest data from {num} sources",
            "match_patterns": [rf"(?i){num}\s*(csv|source|format)", rf"(?i)(ingest|import|parse).*{num}"],
        })
        req_id += 1

    # Pattern: "Build/Create/Provide a X view/report/output"
    view_matches = re.finditer(r"(?i)(build|create|provide|generate|produce|output).*?([\w\s-]{3,30}?)(?:view|report|output|plan)", idea)
    for match in view_matches:
        term = match.group(2).strip()
        if len(term) > 3:
            requirements.append({
                "id": f"R{req_id}",
                "term": term,
                "description": f"Provide {term} capability",
                "match_patterns": [rf"(?i){re.escape(term)}"],
            })
            req_id += 1

    # Pattern: explicit output format
    if re.search(r"(?i)markdown", idea):
        requirements.append({
            "id": f"R{req_id}",
            "term": "markdown output",
            "description": "Output in Markdown format",
            "match_patterns": [r"(?i)markdown"],
        })
        req_id += 1

    # Pattern: "deterministic model/engine/computation"
    if re.search(r"(?i)deterministic", idea):
        requirements.append({
            "id": f"R{req_id}",
            "term": "deterministic model",
            "description": "Uses deterministic computation (not probabilistic/LLM-driven)",
            "match_patterns": [r"(?i)deterministic.*(model|comput|engine|math|calcul)"],
        })
        req_id += 1

    # Pattern: "local LLM / LLM narrates / LLM from structured"
    if re.search(r"(?i)llm.*narrat|llm.*structured|local.*llm", idea):
        requirements.append({
            "id": f"R{req_id}",
            "term": "LLM narration from structured only",
            "description": "LLM narrates from structured outputs only, never raw data",
            "match_patterns": [r"(?i)llm.*narrat", r"(?i)structured.*out.*only", r"(?i)never.*raw"],
        })
        req_id += 1

    # Pattern: "local-first / local only / no cloud"
    if re.search(r"(?i)local.?first|no cloud|laptop.?only", idea):
        requirements.append({
            "id": f"R{req_id}",
            "term": "local-first",
            "description": "All processing is local, no cloud dependency",
            "match_patterns": [r"(?i)local.?(first|only)", r"(?i)no.*cloud"],
        })
        req_id += 1

    # Pattern: goals in plain/natural language
    if re.search(r"(?i)(plain|natural).?language.*goal|goal.*(plain|natural)", idea):
        requirements.append({
            "id": f"R{req_id}",
            "term": "plain language goals",
            "description": "Users set goals in plain/natural language",
            "match_patterns": [r"(?i)(plain|natural).?language.*goal", r"(?i)goal.*(plain|natural|text)"],
        })
        req_id += 1

    # Pattern: encrypted / encryption
    if re.search(r"(?i)encrypt", idea):
        requirements.append({
            "id": f"R{req_id}",
            "term": "encrypted storage",
            "description": "Data encrypted at rest",
            "match_patterns": [r"(?i)encrypt.*(db|storage|local|rest)", r"(?i)(AES|cipher|SQLCipher)"],
        })
        req_id += 1

    return requirements


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Parse semi-structured CONTEXT into an eval contract (no LLM)"
    )
    parser.add_argument("input_env", nargs="?", help="Path to input.env file")
    parser.add_argument("--context", help="Inline CONTEXT string (alternative to file)")
    parser.add_argument("--idea", help="Inline IDEA string (alternative to file)")
    parser.add_argument("--case-id", default="auto", help="Case ID (default: auto-derived)")
    parser.add_argument("--output", "-o", help="Output path (default: contract.json in same dir)")
    parser.add_argument("--validate-only", action="store_true", help="Only validate, don't generate")
    args = parser.parse_args()

    # Get IDEA and CONTEXT
    if args.input_env:
        input_path = Path(args.input_env)
        if not input_path.exists():
            print(f"ERROR: File not found: {input_path}")
            sys.exit(1)
        content = input_path.read_text()

        # Parse from file
        idea_match = re.search(r'^IDEA="(.*?)"', content, re.MULTILINE | re.DOTALL)
        context_match = re.search(r'^CONTEXT="(.*?)"', content, re.MULTILINE | re.DOTALL)

        idea = idea_match.group(1) if idea_match else ""
        context = context_match.group(1) if context_match else ""
    else:
        idea = args.idea or ""
        context = args.context or ""

    if not context:
        print("ERROR: No CONTEXT provided. Use --context or pass an input.env file.")
        sys.exit(1)

    # Validate
    errors = validate_context(context)
    if errors:
        print("✗ CONTEXT validation failed:\n")
        for err in errors:
            print(f"  • {err}")
        print(f"\n  Your CONTEXT:\n  {context[:200]}...")
        print("\n  Expected format:")
        print('  "Non-goals: item1; item2; item3. Stack: tech1; tech2. Defer: x; y."')
        sys.exit(1)

    if args.validate_only:
        print("✓ CONTEXT is valid (all required labels present)")
        sections = parse_context(context)
        for label, value in sections.items():
            items = _split_items(value)
            print(f"  {label}: {len(items)} items → {items[:5]}")
        return

    # Build contract
    contract = build_contract(idea, context, case_id=args.case_id)

    # Output
    if args.output:
        output_path = Path(args.output)
    elif args.input_env:
        output_path = Path(args.input_env).parent / "contract.json"
    else:
        output_path = Path("contract.json")

    with open(output_path, "w") as f:
        json.dump(contract, f, indent=2)

    print(f"✓ Contract generated: {output_path}")
    print(f"  Requirements: {len(contract['requirements'])}")
    print(f"  Non-goals:    {len(contract['non_goals'])}")
    print(f"  Deferred:     {len(contract['deferred'])}")
    print(f"  Stack req:    {len(contract['stack']['required'])}")
    print(f"  Limits:       {len(contract['limits'])}")

    if not contract["requirements"]:
        print("\n  ⚠ No requirements auto-extracted from IDEA.")
        print("    Consider adding match_patterns manually for key capabilities.")


if __name__ == "__main__":
    main()
