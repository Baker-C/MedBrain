"""Renders a run into the report: metric tables per configuration, then failures.

Pure — traces and verdicts in, markdown out — so the report's shape is testable
without a database or a model call. Rank metrics are computed at K = FINAL_K, the
generation budget: what the app answers from is what retrieval is graded on.
"""

from eval.cases import EvalCase
from eval.judge import JudgeVerdict
from eval.scoring.behavior import advice_refused, declined_unanswerable, forbidden_drugs_served
from eval.scoring.grounding import unresolved_tags
from eval.scoring.retrieval import (
    Granularity,
    Strictness,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from eval.trace import CaseTrace, EvalRun

FINAL_K = 8  # RetrievalConfig.final_limit: the chunks generation actually sees

LENSES: list[tuple[Strictness, Granularity]] = [
    ("strict", "document"),
    ("strict", "section"),
    ("lenient", "document"),
    ("lenient", "section"),
]

# (case_id, config_name) → verdict; None when the judge call failed.
Verdicts = dict[tuple[str, str], JudgeVerdict | None]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def config_names(run: EvalRun) -> list[str]:
    """Configuration names in first-seen order."""
    return list(dict.fromkeys(trace.config_name for trace in run.traces))


def paired(cases: dict[str, EvalCase], run: EvalRun, name: str) -> list[tuple[EvalCase, CaseTrace]]:
    """This configuration's traces, each beside its authored case."""
    return [(cases[t.case_id], t) for t in run.traces if t.config_name == name]


def retrieval_table(pairs: list[tuple[EvalCase, CaseTrace]]) -> str:
    """Rank metrics over the cases with expected sources, one row per lens."""
    scored = [(case, trace) for case, trace in pairs if case.expected]
    lines = [
        f"| lens | Recall@{FINAL_K} | MRR | Precision@{FINAL_K} |",
        "|---|---|---|---|",
    ]
    for strictness, granularity in LENSES:
        recall = mean(
            [recall_at_k(t.chunks, c.expected, FINAL_K, strictness, granularity) for c, t in scored]
        )
        mrr = mean(
            [reciprocal_rank(t.chunks, c.expected, strictness, granularity) for c, t in scored]
        )
        precision = mean(
            [
                precision_at_k(t.chunks, c.expected, FINAL_K, strictness, granularity)
                for c, t in scored
            ]
        )
        lines.append(
            f"| {strictness}/{granularity} | {recall:.2f} | {mrr:.2f} | {precision:.2f} |"
        )
    return "\n".join(lines)


def ratio(passed: int, total: int) -> str:
    return f"{passed}/{total}" if total else "n/a"


def behavior_table(pairs: list[tuple[EvalCase, CaseTrace]]) -> str:
    """The pass/fail behaviors, counted."""
    advice = [(c, t) for c, t in pairs if c.kind == "advice"]
    unanswerable = [(c, t) for c, t in pairs if c.kind == "unanswerable"]
    traps = [(c, t) for c, t in pairs if c.forbidden_drugs]
    refused = sum(1 for _, t in advice if advice_refused(t))
    declined = sum(1 for _, t in unanswerable if declined_unanswerable(t))
    clean_traps = sum(1 for c, t in traps if not forbidden_drugs_served(t, c.forbidden_drugs))
    clean_tags = sum(1 for _, t in pairs if not unresolved_tags(t.tags, t.sources))
    lines = [
        "| check | passed |",
        "|---|---|",
        f"| advice refused | {ratio(refused, len(advice))} |",
        f"| unanswerable declined | {ratio(declined, len(unanswerable))} |",
        f"| discrimination clean | {ratio(clean_traps, len(traps))} |",
        f"| grounding clean | {ratio(clean_tags, len(pairs))} |",
    ]
    return "\n".join(lines)


def judge_table(pairs: list[tuple[EvalCase, CaseTrace]], name: str, verdicts: Verdicts) -> str:
    """The judge's counts; unjudged cases are surfaced, never silently dropped."""
    judged = [verdicts.get((case.id, name)) for case, _ in pairs]
    present = [v for v in judged if v is not None]
    lines = [
        "| judge | count |",
        "|---|---|",
        f"| correct | {ratio(sum(1 for v in present if v.correct), len(present))} |",
        f"| grounded | {ratio(sum(1 for v in present if v.grounded), len(present))} |",
        f"| unjudged | {len(judged) - len(present)} |",
    ]
    return "\n".join(lines)


def case_failures(case: EvalCase, trace: CaseTrace, verdict: JudgeVerdict | None) -> list[str]:
    """Everything wrong with this case under this configuration, one line each."""
    failures: list[str] = []
    if trace.error:
        failures.append(f"stream error: {trace.error}")
    if case.kind == "advice" and not advice_refused(trace):
        failures.append("advice question was not gate-refused")
    if case.kind == "unanswerable" and not declined_unanswerable(trace):
        failures.append("did not decline an unanswerable question")
    if case.forbidden_drugs:
        served = forbidden_drugs_served(trace, case.forbidden_drugs)
        if served:
            failures.append(f"served look-alike drug(s): {', '.join(served)}")
    if case.expected:
        recall = recall_at_k(trace.chunks, case.expected, FINAL_K, "strict", "section")
        if recall == 0.0:
            failures.append("no expected source in the served set (strict/section)")
    hallucinated = unresolved_tags(trace.tags, trace.sources)
    if hallucinated:
        failures.append(f"hallucinated citation tags: {', '.join(hallucinated)}")
    if verdict is None:
        failures.append("unjudged: the judge call failed")
    elif not verdict.correct or not verdict.grounded:
        what = "incorrect" if not verdict.correct else "ungrounded"
        failures.append(f"judge: {what} — {verdict.reason}")
    return failures


def failures_section(
    pairs: list[tuple[EvalCase, CaseTrace]], name: str, verdicts: Verdicts
) -> str:
    """Every failing case under this configuration; 'none' when the config is clean."""
    lines: list[str] = []
    for case, trace in pairs:
        for failure in case_failures(case, trace, verdicts.get((case.id, name))):
            lines.append(f"- `{case.id}`: {failure}")
    return "\n".join(lines) if lines else "none"


def render_report(cases: list[EvalCase], run: EvalRun, verdicts: Verdicts) -> str:
    """The whole report: per configuration, metrics then behaviors then failures."""
    by_id = {case.id: case for case in cases}
    parts = [f"# MedBrain eval report — {run.started_at}"]
    for name in config_names(run):
        pairs = paired(by_id, run, name)
        parts.append(f"\n## {name}\n")
        parts.append(retrieval_table(pairs))
        parts.append("")
        parts.append(behavior_table(pairs))
        parts.append("")
        parts.append(judge_table(pairs, name, verdicts))
        parts.append("\n### Failures\n")
        parts.append(failures_section(pairs, name, verdicts))
    return "\n".join(parts) + "\n"
