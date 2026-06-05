#!/usr/bin/env python3
"""Generate Codex/GPT iteration handoff Markdown files.

The script intentionally uses only local git/repository state. When a data source
is not present, it writes ``unavailable`` instead of inventing a result.
"""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

UNAVAILABLE = "unavailable"
CODEX_FILENAME = "NEXT_CODEX_TASK.md"
GPT_FILENAME = "NEXT_GPT_REVIEW.md"

CODEX_HEADINGS = [
    "# NEXT_CODEX_TASK",
    "## 本次任務摘要",
    "## 已修改檔案清單",
    "## 已執行測試與結果",
    "## 尚未解決問題",
    "## 下一輪 Codex 可直接執行的指令",
]

GPT_HEADINGS = [
    "# NEXT_GPT_REVIEW",
    "## PR / branch / commit 摘要",
    "## 本次變更目的",
    "## 重要 diff 摘要",
    "## 測試結果",
    "## 風險點",
    "## 請 GPT 審查的問題清單",
    "## 建議是否 merge：YES / NO / NEEDS_MORE_TESTING",
]


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


def run_command(args: Sequence[str], cwd: Path) -> CommandResult:
    """Run a command and return captured output; never raise for command failure."""
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        return CommandResult("", str(exc), 127)
    return CommandResult(completed.stdout.strip(), completed.stderr.strip(), completed.returncode)


def git_output(repo_root: Path, *args: str) -> str:
    result = run_command(["git", *args], repo_root)
    if result.returncode != 0:
        return UNAVAILABLE
    return result.stdout.strip() or UNAVAILABLE


def split_lines(value: str) -> list[str]:
    if not value or value == UNAVAILABLE:
        return []
    return [line for line in value.splitlines() if line.strip()]


def bullet_list(items: Iterable[str], empty: str = UNAVAILABLE) -> str:
    normalized = [item.strip() for item in items if item and item.strip()]
    if not normalized:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in normalized)


def fenced(value: str) -> str:
    if not value or value == UNAVAILABLE:
        value = UNAVAILABLE
    return f"```text\n{value}\n```"


def repo_root_from(start: Path) -> Path:
    result = run_command(["git", "rev-parse", "--show-toplevel"], start)
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return start.resolve()


def default_output_dir(repo_root: Path) -> Path:
    # The repository already uses reports/ and outputs/. Put handoff reports under
    # reports/codex per the requested structure, creating it only when needed.
    return repo_root / "reports" / "codex"


def paths_from_status(status: str) -> list[str]:
    files: list[str] = []
    for line in split_lines(status):
        # Porcelain v1 is usually "XY path"; renames are "XY old -> new".
        if len(line) > 2 and line[2] == " ":
            path = line[3:]
        elif len(line) > 1 and line[1] == " ":
            path = line[2:]
        else:
            path = line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path)
    return sorted(dict.fromkeys(files))


def changed_files(repo_root: Path, status: str | None = None) -> list[str]:
    status_text = status if status is not None else git_output(repo_root, "status", "--short", "--untracked-files=all")
    files = paths_from_status(status_text)
    if files:
        return files
    latest_commit_files = git_output(repo_root, "show", "--name-only", "--format=", "HEAD")
    return split_lines(latest_commit_files)


def latest_files(repo_root: Path, limit: int = 5) -> list[str]:
    candidates: list[Path] = []
    for dirname in ("artifacts", "reports", "outputs"):
        root = repo_root / dirname
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name in {CODEX_FILENAME, GPT_FILENAME}:
                continue
            candidates.append(path)
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [str(path.relative_to(repo_root)) for path in candidates[:limit]]


def pytest_cache_summary(repo_root: Path) -> str:
    cache_dir = repo_root / ".pytest_cache" / "v" / "cache"
    if not cache_dir.exists():
        return UNAVAILABLE

    lastfailed = cache_dir / "lastfailed"
    nodeids = cache_dir / "nodeids"
    parts: list[str] = []
    if lastfailed.exists():
        text = lastfailed.read_text(encoding="utf-8", errors="replace").strip()
        parts.append("lastfailed: none" if text in {"", "{}"} else f"lastfailed: {text[:500]}")
    if nodeids.exists():
        text = nodeids.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            parts.append("pytest cache nodeids available; exact latest pass/fail output unavailable")
    return "; ".join(parts) if parts else UNAVAILABLE


def read_optional_file(path_value: str | None) -> str:
    if not path_value:
        return UNAVAILABLE
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        return UNAVAILABLE
    return path.read_text(encoding="utf-8", errors="replace").strip() or UNAVAILABLE


def build_context(repo_root: Path, pytest_result_file: str | None = None) -> dict[str, str | list[str]]:
    branch = git_output(repo_root, "branch", "--show-current")
    commit = git_output(repo_root, "log", "-1", "--oneline")
    status = git_output(repo_root, "status", "--short", "--untracked-files=all")
    diff_stat = git_output(repo_root, "diff", "--stat", "HEAD")
    staged_diff_stat = git_output(repo_root, "diff", "--cached", "--stat")
    name_status = git_output(repo_root, "diff", "--name-status", "HEAD")
    if diff_stat == UNAVAILABLE and staged_diff_stat == UNAVAILABLE:
        diff_stat = git_output(repo_root, "show", "--stat", "--oneline", "HEAD")
    if name_status == UNAVAILABLE:
        name_status = status if status != UNAVAILABLE else git_output(repo_root, "show", "--name-status", "--format=", "HEAD")

    pytest_file_text = read_optional_file(pytest_result_file)
    pytest_summary = pytest_file_text if pytest_file_text != UNAVAILABLE else pytest_cache_summary(repo_root)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "branch": branch,
        "commit": commit,
        "status": status,
        "changed_files": changed_files(repo_root, status),
        "diff_stat": diff_stat,
        "staged_diff_stat": staged_diff_stat,
        "name_status": name_status,
        "latest_files": latest_files(repo_root),
        "pytest_summary": pytest_summary,
    }


def render_codex(context: dict[str, str | list[str]], args: argparse.Namespace) -> str:
    task_summary = args.task_summary or "Generated from local git status/diff; explicit task summary unavailable."
    unresolved = args.unresolved_issue or [UNAVAILABLE]
    next_commands = args.next_command or (["NO_FOLLOW_UP_REQUIRED"] if args.no_follow_up else [UNAVAILABLE])

    return "\n\n".join(
        [
            CODEX_HEADINGS[0],
            f"Generated at: {context['generated_at']}",
            CODEX_HEADINGS[1],
            f"- {task_summary}",
            f"- Latest local artifacts/reports: {', '.join(context['latest_files']) if context['latest_files'] else UNAVAILABLE}",
            CODEX_HEADINGS[2],
            bullet_list(context["changed_files"]),
            CODEX_HEADINGS[3],
            f"- pytest: {context['pytest_summary']}",
            CODEX_HEADINGS[4],
            bullet_list(unresolved),
            CODEX_HEADINGS[5],
            bullet_list(next_commands),
        ]
    ) + "\n"


def render_gpt(context: dict[str, str | list[str]], args: argparse.Namespace) -> str:
    purpose = args.change_purpose or "Generated from local git status/diff; explicit change purpose unavailable."
    risks = args.risk or [UNAVAILABLE]
    questions = args.review_question or ["請確認 handoff script 的輸出結構、unavailable 標示、以及測試覆蓋是否足以支援後續迭代。"]

    branch_summary = [
        f"branch: {context['branch']}",
        f"commit: {context['commit']}",
        f"status: {context['status']}",
    ]

    diff_parts = []
    if context["diff_stat"] != UNAVAILABLE:
        diff_parts.append(f"working tree diff stat against HEAD:\n{context['diff_stat']}")
    if context["staged_diff_stat"] != UNAVAILABLE:
        diff_parts.append(f"staged diff stat:\n{context['staged_diff_stat']}")
    if context["name_status"] != UNAVAILABLE:
        diff_parts.append(f"name-status:\n{context['name_status']}")
    diff_summary = "\n\n".join(diff_parts) if diff_parts else UNAVAILABLE

    recommendation = args.merge_recommendation
    return "\n\n".join(
        [
            GPT_HEADINGS[0],
            f"Generated at: {context['generated_at']}",
            GPT_HEADINGS[1],
            bullet_list(branch_summary),
            GPT_HEADINGS[2],
            f"- {purpose}",
            GPT_HEADINGS[3],
            fenced(diff_summary),
            GPT_HEADINGS[4],
            f"- pytest: {context['pytest_summary']}",
            GPT_HEADINGS[5],
            bullet_list(risks),
            GPT_HEADINGS[6],
            bullet_list(questions),
            GPT_HEADINGS[7],
            f"- {recommendation}",
        ]
    ) + "\n"


def generate_handoff(
    repo_root: Path,
    output_dir: Path | None = None,
    argv: Sequence[str] | None = None,
) -> tuple[Path, Path]:
    args = parse_args(argv)
    if output_dir is not None:
        output = output_dir
    elif args.output_dir:
        output = Path(args.output_dir)
    else:
        output = default_output_dir(repo_root)
    output.mkdir(parents=True, exist_ok=True)

    context = build_context(repo_root, args.pytest_result_file)
    codex_path = output / CODEX_FILENAME
    gpt_path = output / GPT_FILENAME
    codex_path.write_text(render_codex(context, args), encoding="utf-8")
    gpt_path.write_text(render_gpt(context, args), encoding="utf-8")
    return codex_path, gpt_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Codex/GPT iteration handoff Markdown files.")
    parser.add_argument("--output-dir", help="Output directory. Defaults to reports/codex under the git root.")
    parser.add_argument("--pytest-result-file", help="Optional text file containing a pytest result summary.")
    parser.add_argument("--task-summary", help="Human-provided task summary to include in NEXT_CODEX_TASK.md.")
    parser.add_argument("--change-purpose", help="Human-provided change purpose to include in NEXT_GPT_REVIEW.md.")
    parser.add_argument("--unresolved-issue", action="append", help="Unresolved issue. May be supplied multiple times.")
    parser.add_argument("--next-command", action="append", help="Next Codex command. May be supplied multiple times.")
    parser.add_argument("--no-follow-up", action="store_true", help="Write NO_FOLLOW_UP_REQUIRED as the next Codex instruction.")
    parser.add_argument("--risk", action="append", help="Risk to highlight for GPT review. May be supplied multiple times.")
    parser.add_argument("--review-question", action="append", help="Question for GPT review. May be supplied multiple times.")
    parser.add_argument(
        "--merge-recommendation",
        choices=["YES", "NO", "NEEDS_MORE_TESTING"],
        default="NEEDS_MORE_TESTING",
        help="Suggested merge recommendation for NEXT_GPT_REVIEW.md.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    start = Path.cwd()
    repo_root = repo_root_from(start)
    codex_path, gpt_path = generate_handoff(repo_root, argv=argv)
    print(f"Wrote {codex_path}")
    print(f"Wrote {gpt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
