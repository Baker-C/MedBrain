"""One command runs the whole harness: the suite through the real pipeline under every
configuration, traces saved, answers judged, report printed.

    python -m eval                     # full run — needs backend/.env and ingested data
    python -m eval --score-only PATH   # re-score a saved run: zero pipeline calls

Run from `backend/`. The report prints to stdout and lands beside the traces as
`eval/runs/<stamp>.report.md`; progress goes to stderr so the report stays pipeable.
"""

import argparse
import sys
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
from typing import cast

import psycopg

from clients import build_clients
from config import Settings, load_settings
from eval.cases import EvalCase
from eval.configs import EVAL_CONFIGS
from eval.driver import run_case, shared_rewrite
from eval.judge import build_judge, judge_answer
from eval.report import Verdicts, render_report
from eval.suite import SUITE
from eval.trace import CaseTrace, EvalRun

RUNS_DIR = Path(__file__).parent / "runs"

BAR_WIDTH = 32
LABEL_WIDTH = 42


def unfinished(case: EvalCase) -> bool:
    """A case still carrying authoring placeholders must not spend API calls."""
    return "TODO" in case.question or "TODO" in case.expected_answer


def progress_line(phase: str, done: int, total: int, label: str) -> str:
    """One rewritable line: how far along, and what was just finished.

    ASCII only and fixed width, so it overwrites cleanly on every console and does
    not depend on the terminal's encoding.
    """
    filled = round(BAR_WIDTH * done / total) if total else BAR_WIDTH
    bar = "#" * filled + "." * (BAR_WIDTH - filled)
    percent = round(100 * done / total) if total else 100
    padded = f"{label:<{LABEL_WIDTH}.{LABEL_WIDTH}}"
    return f"\r{phase:<8} [{bar}] {percent:>3}% {done:>3}/{total}  {padded}"


def show_progress(phase: str, done: int, total: int, label: str) -> None:
    """Draw the bar on stderr, so stdout stays a clean pipeable report."""
    print(progress_line(phase, done, total, label), end="", file=sys.stderr, flush=True)
    if done == total:
        print(file=sys.stderr)


def collect_traces(settings: Settings) -> EvalRun:
    """Every case under every configuration, through the real pipeline.

    The rewrite happens once per case, before the configuration loop, so the
    configurations differ only in the toggle under test (see `shared_rewrite`).
    """
    clients = build_clients(settings)
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    traces: list[CaseTrace] = []
    total = len(SUITE) * len(EVAL_CONFIGS)
    with psycopg.connect(settings.database_url) as conn:
        for case in SUITE:
            rewritten_query = shared_rewrite(clients, case)
            for name, config in EVAL_CONFIGS.items():
                show_progress("running", len(traces), total, f"{case.id} x {name}")
                traces.append(run_case(clients, conn, case, name, config, rewritten_query))
    show_progress("running", total, total, "done")
    return EvalRun(started_at=started_at, traces=traces)


def save_run(run: EvalRun) -> Path:
    RUNS_DIR.mkdir(exist_ok=True)
    stamp = run.started_at.replace(":", "").replace("-", "").replace("+", "-")
    path = RUNS_DIR / f"{stamp}.json"
    path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    return path


def judge_run(run: EvalRun, settings: Settings) -> Verdicts:
    """One verdict per trace; a failed judge call lands as None and is reported."""
    by_id = {case.id: case for case in SUITE}
    judge = build_judge(settings.openai_api_key)
    verdicts: Verdicts = {}
    for trace in run.traces:
        label = f"{trace.case_id} x {trace.config_name}"
        show_progress("judging", len(verdicts), len(run.traces), label)
        verdicts[(trace.case_id, trace.config_name)] = judge_answer(
            judge, by_id[trace.case_id], trace
        )
    show_progress("judging", len(run.traces), len(run.traces), "done")
    return verdicts


def main() -> None:
    # The report is UTF-8 and is written as UTF-8; a redirected stdout would otherwise
    # fall back to the console codepage and fail on the first character outside it.
    cast(TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m eval")
    parser.add_argument(
        "--score-only",
        metavar="RUN_JSON",
        help="re-score a saved run instead of driving the pipeline",
    )
    args = parser.parse_args()
    settings = load_settings()

    if args.score_only:
        run_path = Path(args.score_only)
        run = EvalRun.model_validate_json(run_path.read_text(encoding="utf-8"))
    else:
        if any(unfinished(case) for case in SUITE):
            sys.exit("The suite still has TODO placeholders — fill backend/eval/suite.py first.")
        run = collect_traces(settings)
        run_path = save_run(run)
        print(f"traces saved to {run_path}", file=sys.stderr)

    report = render_report(SUITE, run, judge_run(run, settings))
    report_path = run_path.with_suffix(".report.md")
    report_path.write_text(report, encoding="utf-8")
    print(f"report saved to {report_path}", file=sys.stderr)
    print(report)


if __name__ == "__main__":
    main()
