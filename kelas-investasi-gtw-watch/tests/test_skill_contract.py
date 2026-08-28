from __future__ import annotations

from pathlib import Path


def test_skill_requires_wrapper_submission_instead_of_a_json_response() -> None:
    skill = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")

    assert '"$HOME/.hermes/scripts/kelas-investasi-gtw-watch.sh" --submit-analysis' in skill
    assert "Do not return the JSON as your final response." in skill
