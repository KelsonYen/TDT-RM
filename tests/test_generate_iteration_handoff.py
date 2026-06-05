from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_iteration_handoff.py"


def load_handoff_module():
    spec = importlib.util.spec_from_file_location("generate_iteration_handoff", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "README.md").write_text("# fixture repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_generate_handoff_creates_both_markdown_files(tmp_path: Path) -> None:
    module = load_handoff_module()
    init_git_repo(tmp_path)

    output_dir = tmp_path / "reports" / "codex"
    codex_path, gpt_path = module.generate_handoff(tmp_path, output_dir=output_dir, argv=[])

    assert codex_path == output_dir / "NEXT_CODEX_TASK.md"
    assert gpt_path == output_dir / "NEXT_GPT_REVIEW.md"
    assert codex_path.exists()
    assert gpt_path.exists()


def test_generate_handoff_includes_required_headings(tmp_path: Path) -> None:
    module = load_handoff_module()
    init_git_repo(tmp_path)

    codex_path, gpt_path = module.generate_handoff(tmp_path, output_dir=tmp_path / "reports" / "codex", argv=[])

    codex_text = codex_path.read_text(encoding="utf-8")
    gpt_text = gpt_path.read_text(encoding="utf-8")
    for heading in module.CODEX_HEADINGS:
        assert heading in codex_text
    for heading in module.GPT_HEADINGS:
        assert heading in gpt_text


def test_generate_handoff_marks_missing_data_unavailable_without_artifacts(tmp_path: Path) -> None:
    module = load_handoff_module()
    init_git_repo(tmp_path)

    codex_path, gpt_path = module.generate_handoff(tmp_path, output_dir=tmp_path / "reports" / "codex", argv=[])

    codex_text = codex_path.read_text(encoding="utf-8")
    gpt_text = gpt_path.read_text(encoding="utf-8")
    assert "Latest local artifacts/reports: unavailable" in codex_text
    assert "- pytest: unavailable" in codex_text
    assert "- unavailable" in codex_text
    assert "- pytest: unavailable" in gpt_text


def test_generate_handoff_does_not_fail_without_artifact_directory(tmp_path: Path) -> None:
    module = load_handoff_module()
    init_git_repo(tmp_path)

    output_dir = tmp_path / "reports" / "codex"
    module.generate_handoff(tmp_path, output_dir=output_dir, argv=["--no-follow-up"])

    codex_text = (output_dir / "NEXT_CODEX_TASK.md").read_text(encoding="utf-8")
    assert "NO_FOLLOW_UP_REQUIRED" in codex_text
