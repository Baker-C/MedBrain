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

FINAL_K = 5  # RetrievalConfig.final_limit: the chunks generation actually sees

LENSES: list[tuple[Strictness, Granularity]] = [
    ("strict", "document"),
    ("strict", "section"),
    ("lenient", "document"),
    ("lenient", "section"),
]

# The comparison shows section granularity under both strictnesses: document
# granularity is the easier question and the four configurations barely differ on it.
COMPARED_LENSES: list[tuple[Strictness, Granularity]] = [
    ("strict", "section"),
    ("lenient", "section"),
]

# Per-query charts read the strictest lens — the one a configuration can actually fail.
HIT_LENS: tuple[Strictness, Granularity] = ("strict", "section")

BAR_WIDTH = 24
BANDS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]

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


def behavior_counts(pairs: list[tuple[EvalCase, CaseTrace]]) -> list[tuple[str, str]]:
    """The pass/fail behaviors as (check, passed/total), for either table that shows them."""
    advice = [(c, t) for c, t in pairs if c.kind == "advice"]
    unanswerable = [(c, t) for c, t in pairs if c.kind == "unanswerable"]
    traps = [(c, t) for c, t in pairs if c.forbidden_drugs]
    refused = sum(1 for _, t in advice if advice_refused(t))
    declined = sum(1 for _, t in unanswerable if declined_unanswerable(t))
    clean_traps = sum(1 for c, t in traps if not forbidden_drugs_served(t, c.forbidden_drugs))
    clean_tags = sum(1 for _, t in pairs if not unresolved_tags(t.tags, t.sources))
    return [
        ("advice refused", ratio(refused, len(advice))),
        ("unanswerable declined", ratio(declined, len(unanswerable))),
        ("discrimination clean", ratio(clean_traps, len(traps))),
        ("grounding clean", ratio(clean_tags, len(pairs))),
    ]


def judge_counts(
    pairs: list[tuple[EvalCase, CaseTrace]], name: str, verdicts: Verdicts
) -> list[tuple[str, str]]:
    """The judge's counts; unjudged cases are surfaced, never silently dropped."""
    judged = [verdicts.get((case.id, name)) for case, _ in pairs]
    present = [v for v in judged if v is not None]
    return [
        ("correct", ratio(sum(1 for v in present if v.correct), len(present))),
        ("grounded", ratio(sum(1 for v in present if v.grounded), len(present))),
        ("unjudged", str(len(judged) - len(present))),
    ]


def two_column_table(header: tuple[str, str], rows: list[tuple[str, str]]) -> str:
    lines = [f"| {header[0]} | {header[1]} |", "|---|---|"]
    lines += [f"| {label} | {value} |" for label, value in rows]
    return "\n".join(lines)


def behavior_table(pairs: list[tuple[EvalCase, CaseTrace]]) -> str:
    return two_column_table(("check", "passed"), behavior_counts(pairs))


def judge_table(pairs: list[tuple[EvalCase, CaseTrace]], name: str, verdicts: Verdicts) -> str:
    return two_column_table(("judge", "count"), judge_counts(pairs, name, verdicts))


def hit_rate(case: EvalCase, trace: CaseTrace) -> float:
    """The share of the served chunks that hit an expected source — Precision@K under
    the strictest lens. Read per query it says how much of what generation saw was
    actually on target; averaged it is the Precision@K already in the metrics table."""
    return precision_at_k(trace.chunks, case.expected, FINAL_K, *HIT_LENS)


def bar(value: float, width: int = BAR_WIDTH) -> str:
    """A 0.0–1.0 value as an ASCII bar. ASCII so the report survives any console."""
    filled = round(value * width)
    return "#" * filled + "." * (width - filled)


def hit_rate_chart(pairs: list[tuple[EvalCase, CaseTrace]]) -> str:
    """Chunk hit rate per query, one bar each. Fenced so markdown keeps the columns."""
    rates = [(case.id, hit_rate(case, trace)) for case, trace in pairs if case.expected]
    if not rates:
        return "_no cases with expected sources_"
    width = max(len(case_id) for case_id, _ in rates)
    lines = [f"{case_id:<{width}}  {rate:.2f}  {bar(rate)}" for case_id, rate in rates]
    return "```\n" + "\n".join(lines) + "\n```"


def band_label(index: int) -> str:
    low, high = BANDS[index]
    return f"{low:.1f}-{high:.1f}"


def band_of(rate: float) -> int:
    """Which distribution band a hit rate falls in; the top band closes at 1.0."""
    return min(int(rate * len(BANDS)), len(BANDS) - 1)


def hit_rate_histogram(cases: dict[str, EvalCase], run: EvalRun) -> str:
    """How each configuration's per-query hit rates are distributed. The leftmost band
    holds the total misses, so a configuration's failures are visible as mass on the
    left rather than only as a lower mean."""
    blocks = []
    for name in config_names(run):
        rates = [hit_rate(c, t) for c, t in paired(cases, run, name) if c.expected]
        counts = [0] * len(BANDS)
        for rate in rates:
            counts[band_of(rate)] += 1
        rows = [f"  {band_label(i):<8} {'#' * count:<20} {count:>2}" for i, count in
                enumerate(counts)]
        blocks.append(f"{name}\n" + "\n".join(rows))
    return "```\n" + "\n\n".join(blocks) + "\n```"


def metric_values(pairs: list[tuple[EvalCase, CaseTrace]]) -> dict[str, float]:
    """This configuration's rank metrics, keyed by the label the comparison shows."""
    scored = [(case, trace) for case, trace in pairs if case.expected]
    values: dict[str, float] = {}
    for strictness, granularity in COMPARED_LENSES:
        lens = f"{strictness}/{granularity}"
        values[f"Recall@{FINAL_K} ({lens})"] = mean(
            [recall_at_k(t.chunks, c.expected, FINAL_K, strictness, granularity) for c, t in scored]
        )
        values[f"MRR ({lens})"] = mean(
            [reciprocal_rank(t.chunks, c.expected, strictness, granularity) for c, t in scored]
        )
        values[f"Precision@{FINAL_K} ({lens})"] = mean(
            [
                precision_at_k(t.chunks, c.expected, FINAL_K, strictness, granularity)
                for c, t in scored
            ]
        )
    return values


def wide_table(corner: str, columns: list[str], rows: list[tuple[str, list[str]]]) -> str:
    """One row label plus a cell per configuration."""
    lines = [
        "| " + " | ".join([corner, *columns]) + " |",
        "|" + "---|" * (len(columns) + 1),
    ]
    lines += ["| " + " | ".join([label, *cells]) + " |" for label, cells in rows]
    return "\n".join(lines)


def metric_comparison(cases: dict[str, EvalCase], run: EvalRun) -> str:
    """Rank metrics side by side, the best configuration per metric in bold."""
    names = config_names(run)
    by_config = {name: metric_values(paired(cases, run, name)) for name in names}
    labels = list(next(iter(by_config.values())))
    rows = []
    for label in labels:
        best = max(by_config[name][label] for name in names)
        cells = [
            f"**{by_config[name][label]:.2f}**"
            if by_config[name][label] == best
            else f"{by_config[name][label]:.2f}"
            for name in names
        ]
        rows.append((label, cells))
    return wide_table("metric", names, rows)


def outcome_comparison(cases: dict[str, EvalCase], run: EvalRun, verdicts: Verdicts) -> str:
    """Behavior checks and judge counts side by side."""
    names = config_names(run)
    by_config = {
        name: behavior_counts(paired(cases, run, name))
        + judge_counts(paired(cases, run, name), name, verdicts)
        for name in names
    }
    labels = [label for label, _ in next(iter(by_config.values()))]
    rows = [
        (label, [dict(by_config[name])[label] for name in names]) for label in labels
    ]
    return wide_table("check", names, rows)


def comparison_section(cases: dict[str, EvalCase], run: EvalRun, verdicts: Verdicts) -> str:
    """The whole cross-configuration comparison, after the per-configuration sections."""
    lens = f"{HIT_LENS[0]}/{HIT_LENS[1]}"
    return "\n".join(
        [
            "\n## Comparison\n",
            metric_comparison(cases, run),
            "",
            outcome_comparison(cases, run, verdicts),
            f"\n### Chunk hit-rate distribution ({lens}, queries per band)\n",
            hit_rate_histogram(cases, run),
        ]
    )


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
        parts.append("\n### Chunk hit rate by query\n")
        parts.append(hit_rate_chart(pairs))
        parts.append("\n### Failures\n")
        parts.append(failures_section(pairs, name, verdicts))
    parts.append(comparison_section(by_id, run, verdicts))
    return "\n".join(parts) + "\n"
