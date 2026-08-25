from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_deploy_creates_component_runtime_directory_before_copy() -> None:
    script = (ROOT / "deploy.sh").read_text()

    assert "install -d -m 700" in script
    assert ".agents/skills/$cron/bin" in script
