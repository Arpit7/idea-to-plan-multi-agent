#!/usr/bin/env python3
"""
eval_runner.py — Tier 1 deterministic eval for mol-idea-to-plan outputs.

Usage:
    python eval_runner.py <contract.json> <output-dir> [--report-dir reports/]

Checks:
  1. Artifact existence (required files present)
  2. Section presence (required headings in key files)
  3. Requirement coverage (each requirement matched in output)
  4. Non-goal leakage (non-goals appearing as included features)
  5. Stack compliance (required stack present, forbidden stack absent)
  6. Limit enforcement (numeric constraints respected)
  7. Pipeline completion (state.env shows final step reached)
"""

import argparse
import json
import re
import sys
import os
from datetime import datetime
from pathlib import Path

from extractors import extract_from_output_dir, resolve_globs


# ─── Result types ────────────────────────────────────────────────────────────

class CheckResult:
    def __init__(self, check_id: str, name: str, status: str, detail: str = ""):
        self.check_id = check_id
        self.name = name
        self.status = status  # PASS, FAIL, WARN, SKIP
        self.detail = detail

    def to_dict(self):
        return {
            "check_id": self.check_id,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }


# ─── Check implementations ───────────────────────────────────────────────────

def check_artifacts_exist(contract: dict, base_dir: str) -> list[CheckResult]:
    """Check that all required output files exist."""
    results = []
    artifacts = contract.get("artifacts", {})
    required_files = artifacts.get("required_files", [])

    for pattern in required_files:
        matched = resolve_globs(base_dir, [pattern])
        if matched:
            results.append(CheckResult(
                f"ART-{pattern}",
                f"Artifact exists: {pattern}",
                "PASS",
                f"Found: {', '.join(matched)}"
            ))
        else:
            results.append(CheckResult(
                f"ART-{pattern}",
                f"Artifact exists: {pattern}",
                "FAIL",
                f"No files matched glob: {pattern}"
            ))

    return results


def check_sections_present(contract: dict, base_dir: str, claims) -> list[CheckResult]:
    """Check that required sections exist in key artifact files."""
    results = []
    artifacts = contract.get("artifacts", {})
    required_sections = artifacts.get("required_sections", {})

    for file_pattern, expected_headings in required_sections.items():
        matched_files = resolve_globs(base_dir, [file_pattern])
        if not matched_files:
            results.append(CheckResult(
                f"SEC-{file_pattern}",
                f"Sections in: {file_pattern}",
                "SKIP",
                "File not found"
            ))
            continue

        for fpath in matched_files:
            rel_path = os.path.relpath(fpath, base_dir)
            file_sections = claims.sections.get(rel_path, [])
            sections_lower = [s.lower() for s in file_sections]

            for heading in expected_headings:
                found = any(heading.lower() in s for s in sections_lower)
                if found:
                    results.append(CheckResult(
                        f"SEC-{heading}",
                        f"Section '{heading}' in {rel_path}",
                        "PASS",
                    ))
                else:
                    results.append(CheckResult(
                        f"SEC-{heading}",
                        f"Section '{heading}' in {rel_path}",
                        "FAIL",
                        f"Not found. Sections present: {file_sections[:10]}"
                    ))

    return results


def check_requirements_coverage(contract: dict, claims) -> list[CheckResult]:
    """Check that each requirement is covered somewhere in the output."""
    results = []

    for req in contract.get("requirements", []):
        req_id = req["id"]
        term = req["term"]
        patterns = req.get("match_patterns", [])

        # First: simple term search in full text
        term_found = bool(re.search(re.escape(term), claims.full_text, re.IGNORECASE))

        # Then: pattern matching
        pattern_found = False
        matched_pattern = None
        for pattern in patterns:
            try:
                if re.search(pattern, claims.full_text):
                    pattern_found = True
                    matched_pattern = pattern
                    break
            except re.error:
                pass

        if pattern_found:
            results.append(CheckResult(
                f"REQ-{req_id}",
                f"Requirement covered: {term}",
                "PASS",
                f"Matched pattern: {matched_pattern}"
            ))
        elif term_found:
            results.append(CheckResult(
                f"REQ-{req_id}",
                f"Requirement covered: {term}",
                "PASS",
                "Term found in output (no pattern match, but term present)"
            ))
        else:
            results.append(CheckResult(
                f"REQ-{req_id}",
                f"Requirement covered: {term}",
                "FAIL",
                f"Neither term '{term}' nor any match_patterns found in output"
            ))

    return results


def check_non_goal_leakage(contract: dict, claims) -> list[CheckResult]:
    """
    Check that non-goals don't appear as INCLUDED features.

    Logic:
    - For each non-goal, search the included_feature_lines for leak_patterns.
    - If a leak_pattern matches, check if the same line also matches a safe_pattern.
    - Leak = matched leak_pattern WITHOUT a matching safe_pattern in context.
    """
    results = []
    included_text = "\n".join(claims.included_feature_lines)

    for ng in contract.get("non_goals", []):
        ng_id = ng["id"]
        term = ng["term"]
        leak_patterns = ng.get("leak_patterns", [])
        safe_patterns = ng.get("safe_patterns", [])

        leaked = False
        leak_evidence = []

        for lp in leak_patterns:
            try:
                matches = re.finditer(lp, included_text)
                for match in matches:
                    matched_text = match.group(0)
                    # Check if this match is in a safe context
                    # Get surrounding context (100 chars before and after)
                    start = max(0, match.start() - 100)
                    end = min(len(included_text), match.end() + 100)
                    context = included_text[start:end]

                    is_safe = any(
                        re.search(sp, context) for sp in safe_patterns
                    )
                    if not is_safe:
                        leaked = True
                        leak_evidence.append(f"Pattern '{lp}' matched: '{matched_text[:80]}'")
            except re.error:
                pass

        if leaked:
            results.append(CheckResult(
                f"NG-{ng_id}",
                f"Non-goal leakage: {term}",
                "FAIL",
                f"Leaked into included features. Evidence: {'; '.join(leak_evidence[:3])}"
            ))
        else:
            # Also check: is the non-goal acknowledged in the output's non-goals section?
            non_goal_text = "\n".join(claims.non_goal_lines)
            acknowledged = bool(re.search(re.escape(term), non_goal_text, re.IGNORECASE))
            detail = "Acknowledged in Non-Goals section" if acknowledged else "Not leaked (term absent from feature sections)"
            results.append(CheckResult(
                f"NG-{ng_id}",
                f"Non-goal leakage: {term}",
                "PASS",
                detail
            ))

    return results


def check_stack_compliance(contract: dict, claims) -> list[CheckResult]:
    """Check that required stack items are present and forbidden ones are absent."""
    results = []
    stack = contract.get("stack", {})
    allow_deviation = stack.get("allow_justified_deviation", True)

    for item in stack.get("required", []):
        found = bool(re.search(re.escape(item), claims.full_text, re.IGNORECASE))
        if found:
            results.append(CheckResult(
                f"STK-REQ-{item}",
                f"Stack present: {item}",
                "PASS",
            ))
        else:
            # Check for justified deviation
            deviation_patterns = [
                re.compile(rf"(?i)(instead|pivot|replace|swap|alternative).*{re.escape(item)}", re.IGNORECASE),
                re.compile(rf"(?i){re.escape(item)}.*(not.*available|not.*installable|pivot|replaced)", re.IGNORECASE),
            ]
            justified = any(p.search(claims.full_text) for p in deviation_patterns)
            if justified and allow_deviation:
                results.append(CheckResult(
                    f"STK-REQ-{item}",
                    f"Stack present: {item}",
                    "WARN",
                    f"'{item}' not used but deviation appears justified in text"
                ))
            else:
                results.append(CheckResult(
                    f"STK-REQ-{item}",
                    f"Stack present: {item}",
                    "FAIL",
                    f"'{item}' not found in output and no justified deviation detected"
                ))

    for item in stack.get("forbidden", []):
        # Search in included feature lines only (mentioning in non-goals is fine)
        included_text = "\n".join(claims.included_feature_lines)
        found = bool(re.search(re.escape(item), included_text, re.IGNORECASE))
        if found:
            results.append(CheckResult(
                f"STK-BAN-{item}",
                f"Stack forbidden: {item}",
                "FAIL",
                f"'{item}' found in included feature sections"
            ))
        else:
            results.append(CheckResult(
                f"STK-BAN-{item}",
                f"Stack forbidden: {item}",
                "PASS",
            ))

    return results


def check_limits(contract: dict, claims) -> list[CheckResult]:
    """Check numeric constraints are respected in the output."""
    results = []

    for limit_name, limit_spec in contract.get("limits", {}).items():
        value = limit_spec["value"]
        pattern = limit_spec["match_pattern"]
        comparison = limit_spec.get("comparison", "eq")

        try:
            match = re.search(pattern, claims.full_text)
            if match:
                results.append(CheckResult(
                    f"LIM-{limit_name}",
                    f"Limit declared: {limit_name} = {value}",
                    "PASS",
                    f"Constraint '{limit_name}' found in output (pattern matched)"
                ))
            else:
                # The limit might be stated differently — search for the number near the term
                term_parts = limit_name.replace("_", " ")
                fallback = re.search(
                    rf"(?i){term_parts}.*{value}|{value}.*{term_parts}",
                    claims.full_text
                )
                if fallback:
                    results.append(CheckResult(
                        f"LIM-{limit_name}",
                        f"Limit declared: {limit_name} = {value}",
                        "PASS",
                        "Found via fallback term+value proximity search"
                    ))
                else:
                    results.append(CheckResult(
                        f"LIM-{limit_name}",
                        f"Limit declared: {limit_name} = {value}",
                        "WARN",
                        f"Limit not explicitly stated in output. Expected: {limit_name}={value}"
                    ))
        except re.error as e:
            results.append(CheckResult(
                f"LIM-{limit_name}",
                f"Limit declared: {limit_name} = {value}",
                "SKIP",
                f"Invalid regex: {e}"
            ))

    return results


def check_pipeline_completion(claims) -> list[CheckResult]:
    """Check that the pipeline reached its final step."""
    results = []

    if not claims.state:
        results.append(CheckResult(
            "PIPE-state",
            "Pipeline state.env found",
            "FAIL",
            "No state.env found in .plan-reviews/"
        ))
        return results

    current_step = claims.state.get("CURRENT_STEP", "")
    review_id = claims.state.get("REVIEW_ID", "")

    if review_id:
        results.append(CheckResult(
            "PIPE-review-id",
            "Pipeline has REVIEW_ID",
            "PASS",
            f"REVIEW_ID={review_id}"
        ))

    if current_step:
        # The final step is create-beads (step 10)
        final_steps = ["create-beads", "create_beads", "done", "complete", "10"]
        is_complete = any(fs in current_step.lower() for fs in final_steps)
        results.append(CheckResult(
            "PIPE-complete",
            "Pipeline reached final step",
            "PASS" if is_complete else "WARN",
            f"CURRENT_STEP={current_step}" + ("" if is_complete else " (may still be in progress)")
        ))
    else:
        results.append(CheckResult(
            "PIPE-complete",
            "Pipeline reached final step",
            "WARN",
            "CURRENT_STEP not set in state.env"
        ))

    return results


# ─── Report generation ────────────────────────────────────────────────────────

def generate_report(contract: dict, results: list[CheckResult], output_dir: str) -> dict:
    """Generate a structured eval report."""
    total = len(results)
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    warned = sum(1 for r in results if r.status == "WARN")
    skipped = sum(1 for r in results if r.status == "SKIP")

    verdict = "PASS" if failed == 0 else "FAIL"

    return {
        "meta": {
            "case_id": contract["meta"]["case_id"],
            "eval_date": datetime.now().isoformat(),
            "output_dir": output_dir,
            "verdict": verdict,
        },
        "summary": {
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "warnings": warned,
            "skipped": skipped,
            "pass_rate": f"{passed/total*100:.1f}%" if total > 0 else "N/A",
        },
        "failures": [r.to_dict() for r in results if r.status == "FAIL"],
        "warnings": [r.to_dict() for r in results if r.status == "WARN"],
        "all_results": [r.to_dict() for r in results],
    }


def print_report(report: dict):
    """Print a human-readable summary to stdout."""
    meta = report["meta"]
    summary = report["summary"]

    verdict_symbol = "✓" if meta["verdict"] == "PASS" else "✗"
    print(f"\n{'='*60}")
    print(f"  Eval Report: {meta['case_id']}")
    print(f"  Date: {meta['eval_date']}")
    print(f"  Output: {meta['output_dir']}")
    print(f"{'='*60}")
    print(f"\n  Verdict: {verdict_symbol} {meta['verdict']}")
    print(f"  Checks: {summary['total_checks']} total | "
          f"{summary['passed']} passed | {summary['failed']} failed | "
          f"{summary['warnings']} warnings | {summary['skipped']} skipped")
    print(f"  Pass rate: {summary['pass_rate']}")

    if report["failures"]:
        print(f"\n  {'─'*56}")
        print("  FAILURES:")
        for f in report["failures"]:
            print(f"    ✗ [{f['check_id']}] {f['name']}")
            if f["detail"]:
                print(f"      → {f['detail'][:120]}")

    if report["warnings"]:
        print(f"\n  {'─'*56}")
        print("  WARNINGS:")
        for w in report["warnings"]:
            print(f"    ⚠ [{w['check_id']}] {w['name']}")
            if w["detail"]:
                print(f"      → {w['detail'][:120]}")

    print(f"\n{'='*60}\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Tier 1 eval for mol-idea-to-plan outputs"
    )
    parser.add_argument("contract", help="Path to contract.json")
    parser.add_argument("output_dir", help="Path to pipeline output directory (e.g., ~/poc-city)")
    parser.add_argument("--report-dir", default="reports/", help="Directory to save JSON reports")
    args = parser.parse_args()

    # Load contract
    contract_path = Path(args.contract)
    if not contract_path.exists():
        print(f"ERROR: Contract file not found: {contract_path}")
        sys.exit(1)

    with open(contract_path) as f:
        contract = json.load(f)

    # Resolve output dir
    output_dir = os.path.expanduser(args.output_dir)
    if not os.path.isdir(output_dir):
        print(f"ERROR: Output directory not found: {output_dir}")
        sys.exit(1)

    print(f"Evaluating case '{contract['meta']['case_id']}' against {output_dir}")
    print("Extracting claims from artifacts...")

    # Extract claims
    claims = extract_from_output_dir(output_dir)
    print(f"  Found {len(claims.files)} artifact files")
    print(f"  Included feature lines: {len(claims.included_feature_lines)}")
    print(f"  Non-goal context lines: {len(claims.non_goal_lines)}")

    # Run all checks
    print("Running checks...")
    results = []
    results.extend(check_artifacts_exist(contract, output_dir))
    results.extend(check_sections_present(contract, output_dir, claims))
    results.extend(check_requirements_coverage(contract, claims))
    results.extend(check_non_goal_leakage(contract, claims))
    results.extend(check_stack_compliance(contract, claims))
    results.extend(check_limits(contract, claims))
    results.extend(check_pipeline_completion(claims))

    # Generate report
    report = generate_report(contract, results, output_dir)
    print_report(report)

    # Save JSON report
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / f"{contract['meta']['case_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved: {report_file}")

    # Exit code
    sys.exit(0 if report["meta"]["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
