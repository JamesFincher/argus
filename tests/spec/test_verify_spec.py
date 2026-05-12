from pathlib import Path

import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import verify_spec  # noqa: E402


def write_file(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def create_valid_scaffold(root: Path) -> None:
    write_file(root / "argus_spec.md", "# Spec\n")
    write_file(
        root / "docs/implementation-plan.md",
        "\n".join(
            [
                "Argus Core",
                "Argus Sensor",
                "Argus Mesh",
                "ArgusOS",
                "Hermes integration",
            ]
        ),
    )
    write_file(
        root / "docs/spec-checklist.md",
        "\n".join(
            [
                "Deliverable",
                "Required artifact",
                "Test gate",
                "schema migration test",
                "redaction regression suite",
                "MCP discovery test",
                "Redis replay test",
                "sensitive-surface suppression test",
            ]
        ),
    )
    write_file(root / "scripts/verify_spec.py", "# verifier\n")
    write_file(root / "tests/spec/test_verify_spec.py", "# tests\n")


def test_run_checks_passes_for_complete_scaffold(tmp_path: Path) -> None:
    create_valid_scaffold(tmp_path)

    results = verify_spec.run_checks(tmp_path)

    assert results
    assert all(result.ok for result in results)


def test_run_checks_reports_missing_required_path(tmp_path: Path) -> None:
    create_valid_scaffold(tmp_path)
    (tmp_path / "docs/spec-checklist.md").unlink()

    results = verify_spec.run_checks(tmp_path)

    failures = {result.path: result.detail for result in results if not result.ok}
    assert failures["docs/spec-checklist.md"] == "not a file"


def test_main_returns_failure_when_required_text_is_missing(tmp_path: Path) -> None:
    create_valid_scaffold(tmp_path)
    (tmp_path / "docs/implementation-plan.md").write_text(
        "Argus Core only\n", encoding="utf-8"
    )

    exit_code = verify_spec.main(["--root", str(tmp_path)])

    assert exit_code == 1
