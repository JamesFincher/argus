from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def read_text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_spec_uses_current_hermes_contract_examples() -> None:
    spec = read_text("argus_spec.md")

    assert '{"action": "block", "message":' in spec
    assert '{"block": True' not in spec
    assert '{"block": true' not in spec
    assert "uvx hermes-sensor-mcp" not in spec
    assert "hermes mcp add argus-sensor" in spec
    assert "--args run argus-sensor-mcp" in spec


def test_readme_points_to_verified_hermes_setup() -> None:
    readme = read_text("README.md")

    assert "docs/hermes-setup.md" in readme
    assert "hermes mcp add argus-sensor" in readme
    assert "hermes plugins list" in readme
    assert "consent-gated one-shot" in readme
    assert "OCR skeleton" not in readme


def test_hermes_setup_doc_has_operator_prompts_and_boundaries() -> None:
    setup = read_text("docs/hermes-setup.md")

    for required in [
        "If Hermes asks whether to add the server, answer `Y`.",
        "hermes mcp test argus-sensor",
        "Safe Hermes Smoke Prompts",
        "Do not reveal raw payloads.",
        '{"action": "block", "message": "..."}',
        "If `argus` does not appear",
        "verifier intentionally checks package entry points and live MCP add/test",
    ]:
        assert required in setup


def test_deep_research_alignment_crosswalk_captures_remaining_deltas() -> None:
    alignment = read_text("docs/deep-research-alignment.md")

    for required in [
        "Hybrid local-first architecture",
        "No prompt firehose",
        "hermes_agent.plugins",
        '{"action": "block", "message": "..."}',
        "Raw data should stay local and audited",
        "Redis-backed live-stack variant",
        "Fresh-install macOS permission verification",
        "plugin package contract is tested",
    ]:
        assert required in alignment


def test_deep_research_report_reflects_current_implementation_state() -> None:
    report = read_text("deep-research-report.md")

    assert "Those compatibility fixes are now implemented" in report
    assert "hermes mcp add argus-sensor" in report
    assert "current live gateway path expects Redis" in report
    assert "Raw Local Events" in report
    assert "Sanitized Hermes Outputs" in report
    assert "plugin package contract is tested" in report
    assert "payload fragment" not in report
