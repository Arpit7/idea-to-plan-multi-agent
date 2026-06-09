"""
extractors.py — Parse output artifacts and extract structured claims.

These extractors read the markdown files produced by mol-idea-to-plan and
return structured data for comparison against the eval contract.
"""

import re
import glob
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ArtifactClaims:
    """Structured claims extracted from a pipeline run's output artifacts."""

    # All markdown content concatenated (for pattern matching)
    full_text: str = ""

    # Per-file content map: relative_path -> content
    files: dict = field(default_factory=dict)

    # Sections found per file: relative_path -> list of heading texts
    sections: dict = field(default_factory=dict)

    # Lines that appear inside Non-Goals / Deferred sections
    non_goal_lines: list = field(default_factory=list)

    # Lines that appear inside included feature sections (phases, components, schema)
    included_feature_lines: list = field(default_factory=list)

    # state.env values (if found)
    state: dict = field(default_factory=dict)


# Headings that indicate "this content is a declared exclusion, not an inclusion"
_SAFE_SECTION_PATTERNS = [
    re.compile(r"(?i)non.?goal"),
    re.compile(r"(?i)explicit.*non"),
    re.compile(r"(?i)defer"),
    re.compile(r"(?i)out.*of.*scope"),
    re.compile(r"(?i)not.*v1"),
    re.compile(r"(?i)implementation.*deferral"),
]

# Headings that indicate "this content IS an included feature"
_INCLUSION_SECTION_PATTERNS = [
    re.compile(r"(?i)^#+\s*(phase|implementation|component|schema|data model|api|cli|architecture|stack|overview)"),
    re.compile(r"(?i)^#+\s*(ingestion|goal|plan|security|testing|migration)"),
]


def resolve_globs(base_dir: str, patterns: list[str]) -> list[str]:
    """Resolve glob patterns relative to base_dir, return matched file paths."""
    matched = []
    for pattern in patterns:
        full_pattern = os.path.join(base_dir, pattern)
        matched.extend(glob.glob(full_pattern, recursive=True))
    return sorted(set(matched))


def extract_sections(content: str) -> list[str]:
    """Extract all markdown heading texts from content."""
    return re.findall(r"^#{1,4}\s+(.+)$", content, re.MULTILINE)


def classify_lines_by_section(content: str) -> tuple[list[str], list[str]]:
    """
    Split content lines into two buckets:
    - Lines under non-goal/deferral headings (safe context)
    - Lines under included-feature headings (leak-detection context)

    Returns (non_goal_lines, included_lines).
    """
    non_goal_lines = []
    included_lines = []

    current_bucket = None  # None, "safe", or "included"
    current_level = 0

    for line in content.splitlines():
        heading_match = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2)

            # Check if this heading is a safe (non-goal) section
            if any(p.search(heading_text) for p in _SAFE_SECTION_PATTERNS):
                current_bucket = "safe"
                current_level = level
            elif any(p.match(line) for p in _INCLUSION_SECTION_PATTERNS):
                current_bucket = "included"
                current_level = level
            else:
                # A same-level or higher-level heading resets the bucket
                if level <= current_level:
                    current_bucket = None
                # Sub-heading inherits parent bucket
        else:
            if current_bucket == "safe":
                non_goal_lines.append(line)
            elif current_bucket == "included":
                included_lines.append(line)

    return non_goal_lines, included_lines


def extract_from_output_dir(base_dir: str) -> ArtifactClaims:
    """
    Walk the output directory and extract structured claims from all
    pipeline artifacts (.prd-reviews/, .designs/, .plan-reviews/).
    """
    claims = ArtifactClaims()
    base = Path(base_dir)

    # Artifact directories to scan
    artifact_dirs = [
        ".prd-reviews",
        ".designs",
        ".plan-reviews",
    ]

    all_text_parts = []

    for artifact_dir in artifact_dirs:
        dir_path = base / artifact_dir
        if not dir_path.exists():
            continue

        for md_file in sorted(dir_path.rglob("*.md")):
            rel_path = str(md_file.relative_to(base))
            content = md_file.read_text(encoding="utf-8", errors="replace")

            claims.files[rel_path] = content
            claims.sections[rel_path] = extract_sections(content)
            all_text_parts.append(content)

            # Classify lines
            non_goal, included = classify_lines_by_section(content)
            claims.non_goal_lines.extend(non_goal)
            claims.included_feature_lines.extend(included)

        # Also pick up state.env
        for env_file in sorted(dir_path.rglob("state.env")):
            content = env_file.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                if "=" in line and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    claims.state[key.strip()] = value.strip()

    claims.full_text = "\n".join(all_text_parts)
    return claims
