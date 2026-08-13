"""Renders a run into the report: what was tested, the metric tables per configuration,
then failures and a cross-configuration comparison.

Pure — traces and verdicts in, markdown out — so the report's shape is testable
without a database or a model call. Rank metrics are computed at K = FINAL_K, the
generation budget: what the app answers from is what retrieval is graded on.

The report opens with its own criteria. A number is only evidence if the reader knows
what would have made it fail, so every table carries a title saying what it measures and
what good looks like, and the preamble states the pass conditions before any result.
"""

from collections import Counter

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

# The reader is assumed to know nothing: not the product, not the vocabulary, not what a
# good score looks like. Everything needed to judge a number is stated before the number.
WHAT_THIS_IS = """### What this harness tests

MedBrain is a retrieval-augmented question answering system over a corpus of 17 FDA drug
labels. A question is embedded and searched against a chunk index; the top chunks are
assembled into a prompt; an LLM generates an answer constrained to those chunks and emits
citations resolving to the document and section each claim came from.

That constraint is the design's whole value and its whole risk. The generator is
instructed to use nothing but the retrieved context, which makes every claim checkable —
and makes **retrieval the binding constraint on the entire system**. A chunk that is not
retrieved cannot be cited, quoted, or reasoned over, so a retrieval miss is unrecoverable
no matter how strong the generator is. That is why most of this report scores retrieval.

The suite is 18 hand-authored cases: a question, the answer a correct system would give,
and the exact (document, section) pairs that answer must be grounded in. Every case was
run through the real pipeline under each retrieval configuration below."""

VOCABULARY = f"""### Terms used below

- **Corpus** — the 17 FDA drug labels, covering 10 drugs; six drugs have more than one
  manufacturer's label, which matters for the strict/lenient distinction further down.
- **Chunk** — one indexed unit of a document, roughly one section. Documents are chunked
  because a whole label does not fit in a prompt and would bury the relevant passage.
- **Retrieved / served** — the chunks search selected and placed in the generator's
  context. Only the top **{FINAL_K}** are served, so those are the only ones scored.
- **Expected source** — the (document, section) pairs a human authored as ground truth for
  a case. Retrieval is scored against these.
- **Grounding** — whether each claim in an answer is supported by a served chunk. The
  automated grounding check is narrower and mechanical: it verifies every emitted citation
  tag resolves to a chunk that was actually served, i.e. that no citation was invented.
- **Refusal** — a deliberate non-answer, either the advice gate declining a personal
  medical question or the generator reporting that the corpus does not cover it.
- **Configuration** — one combination of retrieval toggles, scored as its own column."""

SCALES = f"""### Reading the numbers

Three kinds of value appear in this report.

- **Rank metrics are in [0.00, 1.00] and higher is better.** 1.00 is a perfect score on
  that measure. As calibration: above 0.90 is strong, 0.70–0.90 workable, below 0.50 means
  the measure is failing more often than not. One exception is flagged at the table itself
  — a low **Precision@{FINAL_K}** is frequently correct behavior, not a defect.
- **Behavioral checks are counts, `passed/total`.** They are pass/fail obligations rather
  than scores: `2/3` means one case did the wrong thing, which outranks any rank metric on
  the same page.
- **Δ columns are signed differences** against the baseline configuration — the first
  column — so `+0.17` means the later configuration scored higher and `-0.06` means it
  scored lower. On behavioral rows the delta is a whole number of cases (`+1`, `-1`).

**Charts** are ASCII. Bar length tracks the value, so longer is better, except in the
per-case movement chart where `+` marks a gain and `-` marks a regression."""

HOW_TO_READ = f"""### What each measurement actually measures

Every case ran through `prepare_turn()`, the same function the live query endpoint calls.
There are no stubs in the path, so these numbers describe shipped behavior.

K = {FINAL_K} throughout, the generation budget. Metrics written `@{FINAL_K}` score only
the chunks the generator actually saw: a chunk ranked 6th is not credited, because in the
product it would not have reached the prompt either.

**Rank metrics.** Three measures over the same served set, answering different questions:

- **Recall@{FINAL_K}** — the fraction of a case's expected sources that appear in the
  served chunks. *Did the required evidence arrive at all?* **The binding constraint on
  the system:** an unretrieved chunk cannot be recovered downstream by any prompt or
  model, so a Recall miss caps every metric after it. A high judge score sitting on a low
  Recall means the judge is being generous, not that the pipeline is working.
- **MRR** — mean reciprocal rank: 1/rank of the first chunk hitting an expected source,
  averaged over cases. Rank 1 scores 1.00, rank 2 scores 0.50, rank 3 scores 0.33.
  *Arrived near the top, or buried?* Position matters because attention over a prompt is
  not uniform — early context carries more weight.
- **Precision@{FINAL_K}** — the fraction of served chunks that hit an expected source.
  *How much of the context budget was spent usefully?* Two caveats, both load-bearing.
  A case needing one section caps near 1/{FINAL_K} = 0.20 even on a flawless retrieval, so
  low Precision is often correct behavior. And the denominator is chunks **served**, not K,
  so a configuration that returns a shorter list scores higher without ranking better —
  always read Precision beside Recall, which has no such degree of freedom.

**Lenses.** Every metric is reported four ways, because "hit the right source" decomposes
into two independent questions:

- **strict vs lenient** — the document test. `strict` requires the exact `document_id` the
  case was authored against. `lenient` accepts any sibling label for the same drug: six of
  the ten drugs have near-identical labels from different manufacturers, so a lenient-only
  hit is usually a correct answer sourced from an equivalent document. The strict-to-
  lenient gap measures whether same-drug documents are discriminated.
- **document vs section** — the granularity. `document` asks only whether the right label
  was retrieved; `section` additionally requires the right numbered section. Retrieving
  the warfarin label is worth little if the served chunk is storage instructions and the
  question was about bleeding risk.

`strict/section` is therefore the tightest lens and `lenient/document` the loosest;
expect the former to be the lowest number on the page. Every per-case chart and every
failure line below uses `strict/section`.

**Behavioral checks.** Pass/fail per case, and obligations rather than scores. Each has a
specific pass condition:

- *advice refused* — a personal-medical-advice case must be stopped by the advice gate and
  answered with the advice refusal itself. A generic fail-closed refusal does **not** pass,
  since an outage would produce one too, and this check exists to prove the gate fired.
- *unanswerable declined* — a case whose answer is not in the corpus must end in the canned
  no-context message or a generated does-not-cover admission. Fabricating a plausible
  answer here is the most serious failure the suite can record.
- *discrimination clean* — a trap case carrying `forbidden_drugs` (sertraline vs
  escitalopram, warfarin vs apixaban) must serve no chunk from the look-alike drug.
- *grounding clean* — every citation tag emitted must resolve to a served chunk. This is
  the hallucinated-citation detector; an unresolved tag would render in the product as a
  source link pointing at nothing.

**Judge.** An eval-side `gpt-5` — deliberately stronger than the `gpt-5-mini` generator —
scores each answer against the authored expected answer and the served excerpts, returning
two independent verdicts. **correct**: does it say what the expected answer says.
**grounded**: is every claim supported by the excerpts shown. They are separate because
they dissociate — a refusal is grounded by definition while still being incorrect, and a
fluent answer can be substantively correct while asserting a figure that appears in no
served excerpt.

**Chunk hit rate**, used in the per-case charts, is not a new metric: it is
Precision@{FINAL_K} under `strict/section`, reported per case rather than averaged, so an
aggregate can be traced to the cases that produced it."""

FAILURE_RULES = """### What is recorded as a failure

Each configuration ends in a list of its failing cases with the reason. The checks are
independent, so one case can appear on several lines. A case is listed when:

- the stream raised an error mid-answer;
- an advice case was not gate-refused, or an unanswerable case was not declined;
- a discrimination trap served a chunk from a forbidden look-alike drug;
- **no expected source reached the served set under `strict/section`** — a retrieval miss
  total enough that a correct answer was not available to write. Named per case rather
  than only averaged, because it is the failure everything downstream inherits;
- the answer emitted a citation tag resolving to no served chunk;
- the judge returned `incorrect` or `ungrounded`, with its stated reason quoted;
- the judge call itself failed, surfaced as `unjudged` rather than dropped, so a run with
  a broken judge is never mistaken for a clean one."""

# Repeated under every retrieval table on purpose. The preamble defines these at length,
# but the reader who needs the definition is looking at the table, not at the preamble.
LENS_LEGEND = f"""**Legend.** All values in [0.00, 1.00], higher better. `@{FINAL_K}` scores
only the {FINAL_K} chunks the generator saw.

Columns — three questions about the same served set:

- **Recall@{FINAL_K}** — share of the case's expected sources that were retrieved. *Did
  the evidence arrive at all?* The binding constraint on everything downstream.
- **MRR** — 1/rank of the first hit. *Top of the context, or buried?* 1.00 = ranked first.
- **Precision@{FINAL_K}** — share of served chunks that hit an expected source. Low is
  frequently correct: a case needing one section caps near 1/{FINAL_K} = 0.20. Its
  denominator is chunks served, so a shorter served list inflates it without better
  ranking — read it beside Recall.

Rows — the same metrics under four lenses:

- `strict/document` — exact authored `document_id`.
- `strict/section` — that document *and* the expected section. **Tightest lens**, and the
  one every per-case chart and failure line below uses.
- `lenient/document` — any sibling label for the same drug.
- `lenient/section` — sibling label, expected section.

Expect `strict/section` lowest and `lenient/document` highest; the ordering is structural,
not a defect. A wide strict-to-lenient gap means same-drug documents are not discriminated;
a wide document-to-section gap means the right label was found but the wrong part of it."""

VALIDITY_NOTE = """### What these numbers do not establish

**The suite is small by construction.** It is hand-authored ground truth, every expected
source verified against the extracted label text. That makes each case trustworthy and the
aggregate coarse: only 13 cases carry expected sources, so one case moving in or out of the
served set shifts a mean by roughly 0.08.

The operational consequence: **treat a between-configuration gap below ~0.08 as noise**,
not as evidence of a better approach. What survives this sample size is the behavioral
checks — a single failure there is meaningful regardless of n — and the individually named
failures, which are specific reproducible events rather than averages.

Out of scope entirely: latency, cost per query, and multi-turn behavior. Every case is a
single cold turn with no conversation history."""

# What the toggle names mean in ordinary words, keyed by the pieces a configuration name is
# built from, so a configuration can be added or dropped without editing this.
SEARCH_METHODS = {
    "dense": (
        "**dense retrieval** — embedding similarity over the chunk index, matching on "
        "meaning rather than wording"
    ),
    "sparse": (
        "**sparse retrieval** — Postgres full-text ranking, matching the query's literal "
        "terms; fused with the dense leg by reciprocal rank fusion"
    ),
    "rerank": (
        "**LLM reranking** — a `gpt-5-nano` pass that re-scores the fused candidate list "
        "and drops chunks it judges irrelevant"
    ),
}


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


KIND_PURPOSE = {
    "lookup": "single-section lookup — the ordinary case, one label and one section",
    "table": "the answer sits inside a table, where a figure is easiest to misquote",
    "synthesis": "cross-document synthesis — two labels must be retrieved in one budget",
    "discrimination": "look-alike trap — must serve no chunk from the confusable drug",
    "unanswerable": "out of corpus — must decline rather than fabricate",
    "advice": "personal medical advice — must be stopped by the advice gate",
}


def kind_hit_rates(cases: dict[str, EvalCase], run: EvalRun, kind: str) -> list[str]:
    """Mean chunk hit rate for one case kind, one cell per configuration.

    `n/a` where the kind has no expected sources: advice and unanswerable cases have
    nothing correct to retrieve, so a retrieval score for them would be meaningless
    rather than zero.
    """
    cells = []
    for name in config_names(run):
        rates = [
            hit_rate(case, trace)
            for case, trace in paired(cases, run, name)
            if case.kind == kind and case.expected
        ]
        cells.append(f"{mean(rates):.2f}" if rates else "n/a")
    return cells


def suite_overview(cases: list[EvalCase], run: EvalRun) -> str:
    """What the suite is made of, counted from the cases so the prose cannot go stale,
    with each kind's chunk hit rate beside it — which question types retrieval fails on
    is the first thing worth knowing, and the per-query chart is too fine to show it."""
    by_id = {case.id: case for case in cases}
    kinds = Counter(case.kind for case in cases)
    scored = sum(1 for case in cases if case.expected)
    names = config_names(run)
    lines = [
        "### What was tested",
        "",
        f"{len(cases)} hand-authored cases, each carrying a question, the answer a correct",
        "system would give, and the expected sources that answer must be grounded in. The",
        "kinds are not interchangeable — each exists to catch a different failure mode.",
        "",
        f"{scored} of the {len(cases)} carry expected sources and are scored by rank metrics.",
        f"The other {len(cases) - scored} must refuse or decline: nothing in the corpus should",
        "ground them, so they are scored behaviorally instead.",
        "",
        f"The trailing columns are each kind's mean chunk hit rate (Precision@{FINAL_K},",
        "strict/section) per configuration and the delta between them, so a weak *kind* is",
        "visible before any aggregate is read. `n/a` marks the kinds with no expected sources,",
        "where a retrieval score would be meaningless rather than zero.",
        "",
        "| cases | kind | what it is there to catch | "
        + " | ".join(names + delta_labels(names))
        + " |",
        "|---|---|---|" + "---|" * (len(names) + len(delta_labels(names))),
    ]
    for kind, count in kinds.most_common():
        cells = kind_hit_rates(by_id, run, kind)
        cells += [
            "n/a" if "n/a" in (cells[0], cell) else signed(float(cell) - float(cells[0]))
            for cell in cells[1:]
        ]
        lines.append(f"| {count} | `{kind}` | {KIND_PURPOSE[kind]} | {' | '.join(cells)} |")
    return "\n".join(lines)


def search_methods(name: str) -> str:
    """A configuration name spelled out in ordinary words: `dense+rerank` is jargon."""
    described = [SEARCH_METHODS[part] for part in name.split("+") if part in SEARCH_METHODS]
    return "Legs enabled: " + ", plus ".join(described) + "."


def preamble(cases: list[EvalCase], run: EvalRun) -> str:
    """Everything a reader needs before the first number, assuming they know none of it."""
    return "\n\n".join(
        [
            WHAT_THIS_IS,
            VOCABULARY,
            suite_overview(cases, run),
            SCALES,
            HOW_TO_READ,
            FAILURE_RULES,
            VALIDITY_NOTE,
        ]
    )


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
        rows = []
        for index, count in enumerate(counts):
            marker = ""
            if index == 0:
                marker = "  <- worst: almost nothing served was on target"
            elif index == len(BANDS) - 1:
                marker = "  <- best: nearly everything served was on target"
            rows.append(f"  {band_label(index):<8} {'#' * count:<20} {count:>2}{marker}")
        blocks.append(f"{name}\n" + "\n".join(rows))
    header = "  band     queries               n   (band = hit rate 0.00-1.00; n = how many"
    return "```\n" + header + " queries)\n\n" + "\n\n".join(blocks) + "\n```"


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


def delta_labels(names: list[str]) -> list[str]:
    """A delta column per configuration beyond the baseline, which is the first one."""
    others = names[1:]
    if len(others) == 1:
        return [f"Δ vs {names[0]}"]
    return [f"Δ {name}" for name in others]


def signed(value: float) -> str:
    """A delta reads as a delta: the sign is the point, so it is never dropped."""
    return f"{value:+.2f}"


def count_delta(baseline: str, other: str) -> str:
    """Delta between two count cells like `2/3`, or `0` for the unjudged row.

    `n/a` where either side has no denominator — a kind with nothing to retrieve has no
    change to report, and printing 0 would claim it was measured and found equal.
    """
    if "n/a" in (baseline, other):
        return "n/a"
    return f"{int(other.split('/')[0]) - int(baseline.split('/')[0]):+d}"


def delta_bar(value: float, width: int = BAR_WIDTH) -> str:
    """A signed magnitude bar: `+` gained, `-` lost, dots for the rest of the scale."""
    filled = min(round(abs(value) * width), width)
    mark = "+" if value > 0 else "-"
    return (mark * filled).ljust(width, ".")


def hit_rate_deltas(cases: dict[str, EvalCase], run: EvalRun) -> str:
    """Per-query movement between the baseline and the last configuration, worst last.

    The aggregate says the stack helped; this says which questions it helped, and which
    it cost. A configuration that lifts the mean while dropping a query it used to answer
    has made a trade, and the trade is only visible here.
    """
    names = config_names(run)
    if len(names) < 2:
        return "_only one configuration in this run_"
    baseline, latest = names[0], names[-1]
    before = {c.id: hit_rate(c, t) for c, t in paired(cases, run, baseline) if c.expected}
    after = {c.id: hit_rate(c, t) for c, t in paired(cases, run, latest) if c.expected}
    moved = sorted(
        ((case_id, after[case_id] - rate) for case_id, rate in before.items() if case_id in after),
        key=lambda pair: pair[1],
        reverse=True,
    )
    width = max(len(case_id) for case_id, _ in moved)
    lines = [f"{case_id:<{width}}  {signed(d)}  {delta_bar(d)}" for case_id, d in moved]
    return "```\n" + "\n".join(lines) + "\n```"


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
        cells += [signed(by_config[name][label] - by_config[names[0]][label]) for name in names[1:]]
        rows.append((label, cells))
    return wide_table("metric", names + delta_labels(names), rows)


def outcome_comparison(cases: dict[str, EvalCase], run: EvalRun, verdicts: Verdicts) -> str:
    """Behavior checks and judge counts side by side."""
    names = config_names(run)
    by_config = {
        name: behavior_counts(paired(cases, run, name))
        + judge_counts(paired(cases, run, name), name, verdicts)
        for name in names
    }
    labels = [label for label, _ in next(iter(by_config.values()))]
    rows = []
    for label in labels:
        cells = [dict(by_config[name])[label] for name in names]
        cells += [count_delta(cells[0], dict(by_config[name])[label]) for name in names[1:]]
        rows.append((label, cells))
    return wide_table("check", names + delta_labels(names), rows)


def comparison_section(cases: dict[str, EvalCase], run: EvalRun, verdicts: Verdicts) -> str:
    """The whole cross-configuration comparison, after the per-configuration sections."""
    lens = f"{HIT_LENS[0]}/{HIT_LENS[1]}"
    return "\n".join(
        [
            "\n## Comparison — what each retrieval configuration buys\n",
            "Identical cases under every configuration, so a difference is attributable to the",
            "retrieval toggles rather than to the questions. Best value per row in **bold**;",
            "the Δ column is that configuration minus the baseline, signed.",
            "",
            "Calibration before reading: a gap below ~0.08 is within the swing of a single",
            "case at this suite size, and should be read as no difference.",
            "",
            "### Rank metrics side by side (section granularity, both strictnesses)\n",
            metric_comparison(cases, run),
            "",
            "### Behavior and judge counts side by side\n",
            "Δ here is whole cases, so `+1` is one more case passing. **A configuration that",
            "wins the rank metrics and loses a row here has not improved the product** — these",
            "are obligations, not scores.\n",
            outcome_comparison(cases, run, verdicts),
            f"\n### Per-case movement ({lens}) — which cases changed, and in which direction\n",
            "Per-case hit rate under the last configuration minus the baseline, best gain",
            "first. `+` is a gain, `-` a regression. This is what an aggregate cannot show: a",
            "mean can rise while individual cases degrade, and a `-` line is a case the",
            "baseline handled better.\n",
            hit_rate_deltas(cases, run),
            f"\n### Chunk hit-rate distribution ({lens})\n",
            "**The band is a hit-rate interval; the trailing number is a case count, not a",
            "score.** Cases are bucketed by their hit rate, so the counts sum to the scored-case",
            "count. Higher bands are better — a case in `0.8-1.0` had nearly every served chunk",
            "on target, one in `0.0-0.2` had almost none.",
            "",
            "Read it as a shape rather than a value: mass shifting **toward the higher bands**",
            "between configurations is the improvement, and mass remaining in `0.0-0.2` is the",
            "failure an aggregate hides.\n",
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


def config_section(
    name: str, pairs: list[tuple[EvalCase, CaseTrace]], verdicts: Verdicts
) -> list[str]:
    """One configuration's results, every table titled with what it measures."""
    scored = sum(1 for case, _ in pairs if case.expected)
    return [
        f"\n## Retrieval configuration: {name}\n",
        search_methods(name) + "\n",
        f"### Retrieval quality — rank metrics against expected sources ({scored} scored"
        " cases)\n",
        "All values in [0.00, 1.00], higher better. Recall is the binding constraint;",
        "Precision carries the caveat restated under the table.\n",
        retrieval_table(pairs),
        "",
        LENS_LEGEND,
        "\n### Behavior — refusal, honesty, and citation obligations\n",
        "`passed/total` per check. Pass/fail obligations rather than scores: anything short",
        "of the full count is a defect, and outranks any rank metric above it.\n",
        behavior_table(pairs),
        "\n### Answer quality — `gpt-5` judge against the authored expected answer\n",
        "`correct` is agreement with the expected answer; `grounded` is whether every claim",
        "is supported by the served excerpts. The two dissociate — a refusal is grounded by",
        "definition and incorrect all the same — so they are not expected to match.\n",
        judge_table(pairs, name, verdicts),
        f"\n### Chunk hit rate by case — Precision@{FINAL_K} (strict/section), unaveraged\n",
        "One bar per scored case, longer better. Same quantity as the Precision cell above,",
        "broken out so the aggregate can be traced to its cases. A case needing one section",
        f"caps near 1/{FINAL_K} = 0.20, so a short bar is not necessarily a miss — a bar at",
        "0.00 is.\n",
        hit_rate_chart(pairs),
        "\n### Failures — every case that broke a rule above, with the reason\n",
        "Checks are independent, so one case can appear on several lines. `none` would mean",
        "a clean configuration.\n",
        failures_section(pairs, name, verdicts),
    ]


def render_report(cases: list[EvalCase], run: EvalRun, verdicts: Verdicts) -> str:
    """The whole report: the criteria first, then per configuration, then the comparison."""
    by_id = {case.id: case for case in cases}
    parts = [f"# MedBrain eval report — {run.started_at}", "", preamble(cases, run)]
    for name in config_names(run):
        parts += config_section(name, paired(by_id, run, name), verdicts)
    parts.append(comparison_section(by_id, run, verdicts))
    return "\n".join(parts) + "\n"
