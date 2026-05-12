#!/usr/bin/env python3
"""Verify the bounded Argus spec scaffold exists."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


REQUIRED_PATHS = (
    "argus_spec.md",
    "docs/implementation-plan.md",
    "docs/spec-checklist.md",
    "scripts/verify_spec.py",
    "tests/spec",
    "tests/spec/test_verify_spec.py",
)


REQUIRED_TEXT = {
    "docs/implementation-plan.md": (
        "Argus Core",
        "Argus Sensor",
        "Argus Mesh",
        "ArgusOS",
        "Hermes integration",
    ),
    "docs/spec-checklist.md": (
        "Deliverable",
        "Required artifact",
        "Test gate",
        "schema migration test",
        "redaction regression suite",
        "MCP discovery test",
        "Redis replay test",
        "sensitive-surface suppression test",
    ),
}


@dataclass(frozen=True)
class CheckResult:
    path: str
    ok: bool
    detail: str


def check_required_paths(root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    for relative in REQUIRED_PATHS:
        target = root / relative
        if target.exists():
            results.append(CheckResult(relative, True, "exists"))
        else:
            results.append(CheckResult(relative, False, "missing"))
    return results


def check_required_text(root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    for relative, required_terms in REQUIRED_TEXT.items():
        target = root / relative
        if not target.is_file():
            results.append(CheckResult(relative, False, "not a file"))
            continue

        content = target.read_text(encoding="utf-8")
        missing = [term for term in required_terms if term not in content]
        if missing:
            results.append(
                CheckResult(relative, False, "missing text: " + ", ".join(missing))
            )
        else:
            results.append(CheckResult(relative, True, "required text present"))
    return results


def run_checks(root: Path) -> list[CheckResult]:
    return check_required_paths(root) + check_required_text(root)


def print_report(results: list[CheckResult]) -> None:
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"{status} {result.path} - {result.detail}")

    if all(result.ok for result in results):
        print("PASS Argus spec scaffold verification complete")
    else:
        print("FAIL Argus spec scaffold verification incomplete")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to verify. Defaults to this script's repository.",
    )
    args = parser.parse_args(argv)

    results = run_checks(args.root.resolve())
    print_report(results)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
