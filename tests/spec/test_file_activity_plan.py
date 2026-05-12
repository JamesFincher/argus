from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_fsevents_file_activity_plan_is_metadata_only_and_scoped():
    text = (ROOT / "docs/macos-file-activity.md").read_text(
        encoding="utf-8"
    )

    assert "FSEvents" in text
    assert "metadata-level" in text
    assert "should not read file contents by default" in text
    assert "User chooses watched roots" in text
    assert "Raw file contents require explicit policy-gated expansion" in text
    assert "Pause/forget controls" in text
