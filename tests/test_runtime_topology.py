from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI is required")
def test_compose_exposes_only_supported_runtime_services() -> None:
    result = subprocess.run(
        ["docker", "compose", "config", "--services"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert set(result.stdout.splitlines()) == {
        "api",
        "analysis-worker",
        "ui",
        "postgres",
        "redis",
    }
