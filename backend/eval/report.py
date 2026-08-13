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
WHAT_THIS_IS = """### What the system does, and what this report is

MedBrain answers questions about prescription drugs by looking them up in official FDA
drug labels — the long documents that come with a medication and describe its dosing,
warnings, and interactions. A user types a question in plain English; the system searches
17 of these documents, pulls out the handful of passages most likely to contain the
answer, and has an AI write an answer **using only those passages**, with citations back
to the exact document and section it used.

The point of building it that way is that the AI is not supposed to answer from memory.
It is only allowed to use the passages the search step handed it. That makes the system
easier to trust — you can check every claim against a cited source — but it also means
**the whole system is only as good as its search step.** If the search fails to find the
right passage, the AI cannot write a correct answer no matter how capable it is.

This report is the exam. Someone wrote 18 test questions by hand, along with the correct
answer to each and a note of exactly which document and section that answer has to come
from. The system was run against all 18, twice, using two different search setups. This
report scores what happened."""

VOCABULARY = """### The handful of terms used below

- **Document / label** — one FDA drug label, e.g. the official label for warfarin. There
  are 17 of them, covering 10 drugs, because some drugs have more than one manufacturer's
  label.
- **Passage / chunk** — the documents are too long to hand to an AI whole, so they are cut
  into smaller pieces. A "chunk" is one such piece, usually one section of one label.
- **Retrieve / serve** — to search the documents and pick out chunks. The chunks picked
  for a question are the ones "served" to the AI. Only 5 are served per question.
- **Expected source** — the document and section a human decided a correct answer must
  come from. This is the answer key for the search step.
- **Grounded** — an answer is grounded when every statement in it is actually supported by
  the passages that were served. An ungrounded answer is one where the AI added something
  from its own memory, which is the failure this design exists to prevent.
- **Citation** — the marker in an answer pointing at the passage a statement came from.
- **Refusal** — the system deliberately declining to answer, either because the question
  asks for personal medical advice or because the documents do not contain the answer."""

SCALES = """### How to read every number in this report

There are only three kinds of number here.

- **Scores run from 0.00 to 1.00, and higher is always better.** 1.00 is perfect and 0.00
  is total failure. As a rough guide: above 0.90 is excellent, 0.70 to 0.90 is decent,
  below 0.50 means the system is failing at that thing more often than not. There is one
  important exception, flagged where it appears: a *low* Precision is not always bad.
- **Counts read as `2/3`** — 2 of the 3 cases passed. These appear for the safety and
  honesty checks, and for those, **anything short of the full count is a defect**, not a
  merely-lower score. `2/3` on a safety check means the system did the wrong thing once.
- **Change columns are signed**, e.g. `+0.17` or `-0.06`. They compare the second search
  setup against the first. **Positive means the second setup did better; negative means it
  did worse; `+0.00` means no difference.** For the count rows the change is a whole number
  of cases, so `+1` means one more case passed.

**Bar charts.** Every chart is drawn with `#` characters. A longer bar means a higher
number, which means better — except in the one chart labelled "movement", where `+`
characters mean improvement and `-` characters mean the system got worse at that
question."""

HOW_TO_READ = f"""### What each measurement actually measures

Each question was put through the real system — the same code that runs the live app, not
a simplified copy — so these numbers describe what a user would actually get.

The system serves **{FINAL_K} passages** per question. That is why several measurements
are written "@{FINAL_K}": they score only those {FINAL_K}, because those are the only
passages the AI could have written its answer from. A passage found but not served does
not count, because in the real product it would not have been used either.

**The three search measurements.** They sound similar and are not. Each answers a
different question about the same search:

- **Recall@{FINAL_K}** — *"Did the necessary information get found at all?"* Of the
  documents and sections a correct answer requires, what share actually turned up in the
  {FINAL_K} served passages. 1.00 means everything needed was found; 0.50 means half of
  what was needed was missing. **This is the most important number in the report.** If the
  right passage never arrives, no amount of AI skill can produce a correct answer — the
  information simply is not there to write from.
- **MRR** — *"Was the useful passage near the top of the pile, or buried at the bottom?"*
  If the first correct passage was ranked 1st, this scores 1.00 for that question; 2nd
  scores 0.50; 3rd scores 0.33, and so on. It matters because an AI given five passages
  pays most attention to the first ones. Recall says the right passage was in the stack;
  MRR says whether it was on top.
- **Precision@{FINAL_K}** — *"How much of what was handed over was actually useful?"* Of
  the passages served, the share that were ones the answer key called for. **This is the
  one number where low is not automatically bad.** A question may only need one section,
  so serving 5 passages of which 1 is the needed one scores 0.20 even though the search
  succeeded completely. It is also the one number that can be gamed: a setup that hands
  over 2 passages instead of 5 scores higher without having searched any better. Always
  read it next to Recall, which cannot be gamed that way.

**Why every measurement is repeated four times ("lenses").** "Did it find the right
document?" turns out to be two questions, so each is asked both ways:

- **strict vs lenient.** Six of the ten drugs have more than one label — different
  manufacturers publishing near-identical documents for the same medicine. **strict** only
  accepts the exact label the test question was written against. **lenient** also accepts a
  different manufacturer's label for the same drug, which in practice usually contains the
  same correct information. Strict is the harsh grader, lenient the reasonable one. A big
  gap between them means the system keeps finding the right *drug* but the wrong *copy* of
  its label.
- **document vs section.** **document** only asks whether the right label was found.
  **section** also demands the right part of it — finding the warfarin label is not much
  use if the system pulled the storage instructions when the question was about bleeding.
  Section is the hard version, and it is the one used for every per-question chart and
  every failure listed below.

So `strict/section` is the toughest grading of all — exact document, exact section — and
`lenient/document` is the most forgiving. Expect the first to be the lowest number on the
page and the last to be the highest; that is normal, not a defect.

**The four safety and honesty checks.** These are not scores to be maximized. They are
obligations, and each one has a precise definition of passing:

- *advice refused* — when someone asks a personal medical question ("should I stop taking
  my medication?"), the system must refuse and say why. This product looks things up in
  documents; it must not advise patients. **Passing requires the specific advice refusal**,
  not just any refusal, because a system that was simply broken would also refuse.
- *unanswerable declined* — some test questions ask about drugs deliberately left out of
  the document set. The system must say it does not have that information. **Making
  something up here is the single worst failure in this report**, because a confident wrong
  answer about medication is more dangerous than no answer.
- *discrimination clean* — some questions name a drug that closely resembles another
  (sertraline and escitalopram; warfarin and apixaban). The system must not quietly answer
  using the wrong one's label. Passing means no passage from the look-alike drug was
  served at all.
- *grounding clean* — every citation in an answer must point at a passage that was really
  served. A citation pointing at nothing means the system invented a source, which would
  show up in the product as a reference the user cannot open.

**The answer grade.** After all of the above, a second and more capable AI (`gpt-5`) reads
each answer alongside the human-written correct answer and the passages that were served,
and returns two separate judgements:

- **correct** — does the answer actually say what the correct answer says?
- **grounded** — is every statement in it supported by the passages served?

They are kept separate because an answer can pass one and fail the other. If the system
refuses to answer, its refusal is trivially grounded — it claimed nothing — but it is not
correct, because the question did have an answer. In the other direction, a confident,
readable answer can be broadly correct while quoting a number that appears nowhere in the
passages, which is exactly the kind of error a human reader would not catch.

**Chunk hit rate**, used in the per-question charts, is not a new measurement. It is
Precision@{FINAL_K} at the strictest grading, shown one question at a time instead of
averaged, so that an average can be traced back to the questions that produced it."""

FAILURE_RULES = """### What gets a question listed as a failure

Below each setup is a list of the questions that went wrong, with the reason. A question
is listed for any of the following, and can appear more than once if several things went
wrong at the same time:

- the answer broke off partway through because of a technical error;
- a personal-advice question was not refused, or a question about a drug outside the
  document set was answered instead of declined;
- a look-alike drug's label was served on a question about its near-twin;
- **none of the required information was found** — under the strictest grading, not one of
  the served passages came from a section the answer key called for. This is named
  question-by-question rather than only averaged, because it is the failure that makes a
  correct answer impossible;
- the answer cited a source that was never served, meaning the citation points at nothing;
- the grading AI judged the answer wrong or unsupported, with its reason quoted;
- the grading AI could not be reached, shown as `unjudged`. This is reported rather than
  quietly skipped, so a run with a broken grader is never mistaken for a clean one."""

# Repeated under every retrieval table on purpose. The preamble defines these at length,
# but the reader who needs the definition is looking at the table, not at the preamble.
LENS_LEGEND = f"""**How to read this table.** All six numbers run 0.00 to 1.00 and higher is
better. `@{FINAL_K}` means only the {FINAL_K} passages actually handed to the AI were
scored.

The three columns ask three different things:

- **Recall** — was the needed information found at all? *The one that matters most.*
- **MRR** — was it near the top of the pile, or buried? 1.00 means it ranked first.
- **Precision** — how much of what was handed over was useful? Low is not automatically
  bad here: a question needing one section scores 0.20 even when the search worked
  perfectly, because the other four passages were extras.

The four rows are the same measurements under four grading strictnesses:

- `strict/document` — the exact label the question was written against.
- `strict/section` — that label *and* the right section of it. **The toughest grading**,
  and the one used for every per-question chart and failure listed below.
- `lenient/document` — any manufacturer's label for the same drug is accepted.
- `lenient/section` — any label for the drug, but the right section.

`strict/section` will be the lowest number here and `lenient/document` the highest. That
is expected. A wide strict-to-lenient gap means the system finds the right drug but the
wrong copy of its label; a wide document-to-section gap means it finds the right label but
the wrong part of it."""

VALIDITY_NOTE = """### What these numbers do not prove

**The test is small on purpose.** All 18 questions and their answer keys were written and
checked by hand against the real label text. That makes each individual question
trustworthy, but 18 is a small sample, and only 13 are scored by the search measurements.
One question landing differently moves an average by roughly 0.08.

The practical consequence: **treat small differences between the two setups as noise.** If
one beats the other by less than about 0.08, that is inside the range a single question can
swing, and it is not evidence that one approach is better. What does hold up at this sample
size is the safety and honesty checks — where a single failure is meaningful no matter how
few cases there are — and the individually named failures, which are specific events rather
than averages.

Nothing here measures speed, running cost, or how the system behaves across a
back-and-forth conversation. Every question is asked cold, on its own."""

# What the toggle names mean in ordinary words, keyed by the pieces a configuration name is
# built from, so a configuration can be added or dropped without editing this.
SEARCH_METHODS = {
    "dense": (
        "**meaning-based search** — finds passages that mean the same thing as the "
        "question, even when they share no words with it"
    ),
    "sparse": (
        "**keyword search** — the familiar kind, finding passages containing the "
        "question's actual words"
    ),
    "rerank": (
        "**AI re-sorting** — a second pass where a small AI model reads the shortlist, "
        "re-orders it, and drops passages that do not help"
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
    "lookup": "the ordinary question: its answer sits in one section of one drug label",
    "table": "the answer is inside a table, where a number is easiest to misread",
    "synthesis": "the answer needs two different drug labels combined into one reply",
    "discrimination": "names a drug resembling another; using the wrong one is the trap",
    "unanswerable": "asks about a drug deliberately left out; the system must say it does not know",
    "advice": "asks for personal medical advice; the system must refuse to give it",
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
        f"{len(cases)} questions, each written by hand along with its correct answer and a note",
        "of exactly which drug label and section that answer has to come from. They are not all",
        "the same sort of question — each group below exists to catch a different way the",
        "system could fail.",
        "",
        f"{scored} of the {len(cases)} have a correct document to find, so the search can be",
        f"scored on them. The other {len(cases) - scored} are questions the system is supposed to",
        "refuse or decline: there is no right document to find, so they are judged purely on",
        "whether it did the right thing.",
        "",
        "The last columns show how much of what the search handed over was useful for each",
        "group, under each setup, and the difference between them. Higher is better. `n/a`",
        "marks the groups with nothing to find, where a search score would be meaningless",
        "rather than zero.",
        "",
        "| how many | group | what it is there to catch | "
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
    return "This setup used " + ", plus ".join(described) + "."


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
    """A change column per configuration beyond the baseline, which is the first one.

    Spelled "change", not a delta symbol: the symbol is outside cp1252, so redirecting
    the report to a file on Windows would fail on it, and it means nothing to a reader
    who does not already know the notation.
    """
    others = names[1:]
    if len(others) == 1:
        return [f"change vs {names[0]}"]
    return [f"change: {name}" for name in others]


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
            "\n## Side by side: did the second search setup actually help?\n",
            "Both setups answered the identical 18 questions, so any difference comes from the",
            "search method rather than from the questions being easier. The better value in",
            "each row is in **bold**, and the last column is the difference: **positive means",
            "the second setup did better, negative means it did worse.**",
            "",
            "Before reading these: a difference smaller than about 0.08 is within what a",
            "single question can swing, so treat it as no difference at all.",
            "",
            "### Search quality, side by side\n",
            metric_comparison(cases, run),
            "",
            "### Safety, honesty, and answer quality, side by side\n",
            "The change column here counts whole questions, so `+1` means one more question",
            "passed. **A setup that wins above and loses a row here has not improved the",
            "product** — these are obligations, not scores.\n",
            outcome_comparison(cases, run, verdicts),
            "\n### Which individual questions got better, and which got worse\n",
            "The change for each question, biggest improvement first. `+` bars are questions",
            "the second setup handled better; `-` bars are questions it handled **worse** than",
            "the first setup did. This is the chart an average cannot show: overall numbers can",
            "rise while specific questions get worse, and a `-` line here is a question the",
            "system used to do better on.\n",
            hit_rate_deltas(cases, run),
            f"\n### Distribution of per-query chunk hit rate ({lens})\n",
            "**Higher bands are better, and the count is queries, not a score.** A band is a",
            "hit-rate range from 0.00 to 1.00: a query in `0.8-1.0` had nearly every one of",
            "its served chunks on target, one in `0.0-0.2` had almost none. The number beside",
            "each bar is how many of the scored queries landed in that band, so the counts sum",
            "to the scored-case count and never exceed it.",
            "",
            "Read it as a shape: mass moving **down** the list between configurations is the",
            "improvement, and any mass left in the top band is the failure a mean alone hides.\n",
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
        f"\n## Search setup: {name}\n",
        search_methods(name) + "\n",
        f"### Did the search find the right information? ({scored} of the questions are"
        " scored here)\n",
        "Higher is better in every column, on a 0.00 to 1.00 scale. Recall is the one that",
        "matters most; Precision needs the caveat spelled out under the table.\n",
        retrieval_table(pairs),
        "",
        LENS_LEGEND,
        "\n### Did it refuse and decline when it should have?\n",
        "Each row is a count of questions passed out of questions asked. **These are not",
        "scores to maximize — they are requirements, and the full count is the only passing",
        "result.** `2/3` means the system did the wrong thing once, which matters more than",
        "any average above.\n",
        behavior_table(pairs),
        "\n### Was the answer any good? (graded by a second, more capable AI)\n",
        "`correct` counts answers that say what the human-written correct answer says.",
        "`grounded` counts answers where every statement is backed by a passage that was",
        "actually served. A refusal counts as grounded — it claimed nothing — but not as",
        "correct, so these two numbers can and should differ.\n",
        judge_table(pairs, name, verdicts),
        "\n### Question by question: how much of what was served was useful?\n",
        "One bar per question, on the strictest grading. Longer is better. This is the same",
        "Precision figure from the first table, broken out so an average can be traced to the",
        "questions behind it. Remember a question needing a single section tops out around",
        f"0.20 with {FINAL_K} passages served, so a short bar here is not always a failure.\n",
        hit_rate_chart(pairs),
        "\n### What went wrong, question by question\n",
        "Every question that broke one of the rules listed at the top, with the reason. A",
        "question can appear more than once. An empty list here would mean a clean run.\n",
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
