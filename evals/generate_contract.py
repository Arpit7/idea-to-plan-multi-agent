#!/usr/bin/env python3
"""
generate_contract.py — Generate a draft contract.json from an input.env file.

Uses an LLM (via Ollama local or any OpenAI-compatible API) to extract
structured eval constraints from the free-text IDEA and CONTEXT.

Usage:
    # With Ollama (default, local)
    python3 generate_contract.py cases/my-case/input.env

    # With OpenAI-compatible API
    LLM_BASE_URL=https://api.openai.com/v1 LLM_API_KEY=sk-... LLM_MODEL=gpt-4o \
      python3 generate_contract.py cases/my-case/input.env

    # Dry-run (just print the prompt, don't call LLM)
    python3 generate_contract.py cases/my-case/input.env --dry-run

Output:
    cases/my-case/contract.json (draft — review before freezing!)

Environment variables:
    LLM_BASE_URL  - API base URL (default: http://127.0.0.1:11434/v1 for Ollama)
    LLM_API_KEY   - API key (default: "ollama" for local)
    LLM_MODEL     - Model name (default: llama3.1:8b)
"""

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

# ─── Prompt template ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a precise requirements extraction engine. Given an IDEA and CONTEXT for a software product, extract a structured eval contract in JSON format.

Rules:
- Extract ONLY what is explicitly stated. Do not infer or add items.
- For non_goals: use the exact terms from "Non-goals" / "Non-goals for v1" section.
- For requirements: extract the capabilities that MUST be present in any valid design.
- For stack: extract named technologies. "forbidden" = things not in the stated stack that would be red flags if used.
- For limits: extract numeric constraints (e.g., "max 3 goals", "5 CSV formats").
- leak_patterns should be regex that detects the non-goal being IMPLEMENTED (not just mentioned).
- safe_patterns should match contexts where the term is OK (e.g., listed as a non-goal).
- match_patterns for requirements should be regex that confirms the requirement IS covered.

Output ONLY valid JSON matching the schema. No markdown fences, no explanation."""

USER_PROMPT_TEMPLATE = """Extract an eval contract from this input:

## IDEA
{idea}

## CONTEXT
{context}

## Required JSON structure:
{{
  "meta": {{
    "case_id": "<short-kebab-case-id>",
    "created_at": "{today}",
    "description": "<one-line summary>"
  }},
  "requirements": [
    {{
      "id": "R1",
      "term": "<short searchable term>",
      "description": "<full requirement>",
      "match_patterns": ["<regex that confirms coverage>"]
    }}
  ],
  "non_goals": [
    {{
      "id": "NG1",
      "term": "<the non-goal feature>",
      "leak_patterns": ["<regex detecting this being IMPLEMENTED>"],
      "safe_patterns": ["(?i)non.?goal", "(?i)not.*v1", "(?i)defer"]
    }}
  ],
  "deferred": [
    {{ "id": "D1", "term": "<deferred item>" }}
  ],
  "stack": {{
    "required": ["<tech that must appear>"],
    "forbidden": ["<tech that must NOT appear as included>"],
    "allow_justified_deviation": true
  }},
  "limits": {{
    "<limit_name>": {{
      "value": <number>,
      "match_pattern": "<regex to find this limit declared>",
      "comparison": "eq"
    }}
  }},
  "artifacts": {{
    "required_files": [
      ".prd-reviews/*/prd-draft.md",
      ".prd-reviews/*/prd-review.md",
      ".designs/*/design-doc.md",
      ".plan-reviews/*/state.env"
    ],
    "required_sections": {{
      ".prd-reviews/*/prd-draft.md": ["Problem Statement", "Goals", "Non-Goals", "Constraints"],
      ".prd-reviews/*/prd-review.md": ["Executive Summary"],
      ".designs/*/design-doc.md": ["Data Model", "Security", "Testing"]
    }}
  }}
}}"""


# ─── Input parsing ────────────────────────────────────────────────────────────

def parse_input_env(path: str) -> tuple[str, str]:
    """Parse IDEA and CONTEXT from an input.env file.

    Handles both:
      IDEA="value on one line"
      IDEA="value spanning
      multiple lines"
    Uses a greedy approach: find IDEA=" then capture until the next
    unescaped quote followed by end-of-line or next variable.
    """
    content = Path(path).read_text()

    idea = ""
    context = ""

    # Strategy: find each variable assignment, capture between first " and
    # the closing " that precedes a newline (possibly followed by blank/comment/next var)
    def extract_var(name: str, text: str) -> str:
        # Match: NAME="...content..." (content may span lines, no unescaped " inside)
        pattern = rf'^{name}="(.*?)"'
        match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        if match:
            return match.group(1).strip()
        # Try single quotes
        pattern = rf"^{name}='(.*?)'"
        match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    idea = extract_var("IDEA", content)
    context = extract_var("CONTEXT", content)

    if not idea:
        print("WARNING: Could not extract IDEA from input.env")
    if not context:
        print("WARNING: Could not extract CONTEXT from input.env")

    return idea, context


# ─── LLM call ────────────────────────────────────────────────────────────────

def call_llm(system: str, user: str) -> str:
    """Call an OpenAI-compatible API (works with Ollama, OpenAI, etc.)."""
    import urllib.request
    import urllib.error

    base_url = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    api_key = os.environ.get("LLM_API_KEY", "ollama")
    model = os.environ.get("LLM_MODEL", "llama3.1:8b")

    url = f"{base_url}/chat/completions"

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,  # Low temp for extraction
        "max_tokens": 4096,
    }).encode()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"]
    except urllib.error.URLError as e:
        print(f"ERROR: LLM API call failed: {e}")
        print(f"  URL: {url}")
        print(f"  Model: {model}")
        print(f"  Hint: Is Ollama running? Try: ollama serve")
        sys.exit(1)


def extract_json_from_response(response: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", response.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse LLM response as JSON: {e}")
        print(f"Response was:\n{response[:500]}")
        sys.exit(1)


# ─── Validation ───────────────────────────────────────────────────────────────

def validate_contract(contract: dict) -> list[str]:
    """Basic validation of the generated contract structure."""
    issues = []

    if "meta" not in contract:
        issues.append("Missing 'meta' section")
    elif "case_id" not in contract.get("meta", {}):
        issues.append("Missing 'meta.case_id'")

    if "requirements" not in contract:
        issues.append("Missing 'requirements' section")
    elif len(contract["requirements"]) == 0:
        issues.append("No requirements extracted — IDEA may be too vague")

    if "non_goals" not in contract:
        issues.append("Missing 'non_goals' section")
    elif len(contract["non_goals"]) == 0:
        issues.append("No non_goals extracted — CONTEXT may lack 'Non-goals' section")

    if "stack" not in contract:
        issues.append("Missing 'stack' section")

    if "limits" not in contract:
        issues.append("Missing 'limits' section")

    # Validate regex patterns compile
    for req in contract.get("requirements", []):
        for p in req.get("match_patterns", []):
            try:
                re.compile(p)
            except re.error as e:
                issues.append(f"Invalid regex in {req['id']}.match_patterns: {p} ({e})")

    for ng in contract.get("non_goals", []):
        for p in ng.get("leak_patterns", []):
            try:
                re.compile(p)
            except re.error as e:
                issues.append(f"Invalid regex in {ng['id']}.leak_patterns: {p} ({e})")

    return issues


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a draft contract.json from input.env using an LLM"
    )
    parser.add_argument("input_env", help="Path to input.env file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the prompt without calling the LLM")
    parser.add_argument("--output", "-o", help="Output path (default: contract.json in same dir as input)")
    args = parser.parse_args()

    input_path = Path(args.input_env)
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        sys.exit(1)

    # Parse input
    idea, context = parse_input_env(str(input_path))
    print(f"Extracted IDEA ({len(idea)} chars) and CONTEXT ({len(context)} chars)")

    # Build prompt
    user_prompt = USER_PROMPT_TEMPLATE.format(
        idea=idea,
        context=context,
        today=date.today().isoformat(),
    )

    if args.dry_run:
        print("\n=== SYSTEM PROMPT ===")
        print(SYSTEM_PROMPT)
        print("\n=== USER PROMPT ===")
        print(user_prompt)
        print("\n(dry-run: no LLM call made)")
        return

    # Call LLM
    print("Calling LLM for contract extraction...")
    model = os.environ.get("LLM_MODEL", "llama3.1:8b")
    base_url = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    print(f"  Model: {model}")
    print(f"  API: {base_url}")

    response = call_llm(SYSTEM_PROMPT, user_prompt)
    contract = extract_json_from_response(response)

    # Validate
    issues = validate_contract(contract)
    if issues:
        print("\n⚠ Validation issues in generated contract:")
        for issue in issues:
            print(f"  - {issue}")
        print("\nContract will still be saved — fix issues before freezing.")

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / "contract.json"

    # Save
    with open(output_path, "w") as f:
        json.dump(contract, f, indent=2)

    print(f"\n✓ Draft contract saved: {output_path}")
    print(f"  Requirements: {len(contract.get('requirements', []))}")
    print(f"  Non-goals:    {len(contract.get('non_goals', []))}")
    print(f"  Deferred:     {len(contract.get('deferred', []))}")
    print(f"  Stack req:    {len(contract.get('stack', {}).get('required', []))}")
    print(f"  Stack banned: {len(contract.get('stack', {}).get('forbidden', []))}")
    print(f"  Limits:       {len(contract.get('limits', {}))}")
    print(f"\n⚠ REVIEW this contract before freezing! It's a draft, not ground truth.")
    print(f"  Open {output_path} and verify each item against your IDEA/CONTEXT.")


if __name__ == "__main__":
    main()
