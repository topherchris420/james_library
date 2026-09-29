"""Measurements of the citation gate (``citation_corpus.verify_quote``).

``verify_quote`` is the single quote-grounding check used by chat, the
offline demo and the MCP server. Its documented contract: a quote verifies
only when its full whitespace-collapsed, case-folded text occurs in one
corpus file, and quotes shorter than three words never verify.

Ground truth is an independent oracle implementing that contract directly
(substring search over whitespace-collapsed, lowercased text). A perturbed
"fabricated" quote that happens to occur somewhere in the corpus is
relabelled as genuine and counted, never silently scored as a rejection.
"""

from __future__ import annotations

import random
import re
import time
from typing import Any

from james_library.utilities.citation_corpus import (
    MIN_QUOTE_WORDS,
    discover_corpus_files,
    hash_corpus_files,
    verify_quote,
)

from ..provenance import REPO_ROOT
from ..runner import RunContext, RunOutput
from ..schema import ExperimentError

_TOKEN = re.compile(r"\S+")
TYPOGRAPHIC_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"'}
TYPOGRAPHIC_DASHES = {"–": "-", "—": "-"}


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


class _Corpus:
    def __init__(self, directory: str) -> None:
        root = (REPO_ROOT / directory).resolve()
        try:
            root.relative_to(REPO_ROOT.resolve())
        except ValueError as exc:
            raise ExperimentError("corpus_dir must stay inside the repository") from exc
        files = discover_corpus_files(root)
        if not files:
            raise ExperimentError(f"No corpus files found in {directory!r}")
        self.papers = {path.name: path.read_text(encoding="utf-8") for path in files}
        self.names = sorted(self.papers)
        self.normalized = {name: _normalize(text) for name, text in self.papers.items()}
        self.tokens = {name: [(m.start(), m.end()) for m in _TOKEN.finditer(text)]
                       for name, text in self.papers.items()}
        self.inputs = {
            "corpus_dir": directory,
            "corpus_files": hash_corpus_files(files, root),
            "corpus_bytes": sum(len(t.encode("utf-8")) for t in self.papers.values()),
        }

    def oracle(self, quote: str) -> bool:
        """The documented contract, implemented independently of the code under test."""
        normalized = _normalize(quote)
        if len(normalized.split()) < MIN_QUOTE_WORDS:
            return False
        return any(normalized in text for text in self.normalized.values())

    def window(self, name: str, start: int, length: int) -> str:
        spans = self.tokens[name]
        return self.papers[name][spans[start][0]:spans[start + length - 1][1]]

    def words(self, name: str, start: int, length: int) -> list[str]:
        spans = self.tokens[name]
        return [self.papers[name][a:b] for a, b in spans[start:start + length]]


def _timed_verify(papers: dict[str, str], quote: str, latencies: list[float]):
    started = time.perf_counter()
    match = verify_quote(papers, quote)
    latencies.append(round((time.perf_counter() - started) * 1000.0, 3))
    return match


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 9) if total else None


def _int_param(params: dict[str, Any], key: str, low: int, high: int) -> int:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ExperimentError(f"parameter {key!r} must be an integer in [{low}, {high}]")
    return value


def run_citation_discrimination(ctx: RunContext) -> RunOutput:
    """Does the gate accept genuine quotes and reject minimally corrupted ones?"""
    quotes = _int_param(ctx.parameters, "quotes", 1, 10_000)
    min_words = _int_param(ctx.parameters, "min_words", MIN_QUOTE_WORDS + 1, 200)
    max_words = _int_param(ctx.parameters, "max_words", min_words, 200)
    corpus = _Corpus(ctx.parameters.get("corpus_dir", "papers"))
    rng = random.Random(ctx.seed)
    eligible = [n for n in corpus.names if len(corpus.tokens[n]) >= max_words + 2]
    if len(eligible) < 2:
        raise ExperimentError("Need at least two corpus files longer than max_words")

    tallies = {cls: [0, 0] for cls in ("verbatim", "reformatted", "substituted", "swapped", "spliced",
                                       "short_fragment", "relabeled")}  # [accepted, total]
    attributed = 0
    latencies: list[float] = []
    cases: list[dict[str, Any]] = []

    def score(cls: str, quote: str, source: str | None) -> None:
        expected = corpus.oracle(quote)
        if cls in ("substituted", "swapped", "spliced") and expected:
            cls = "relabeled"  # the "fabrication" actually occurs in the corpus
        match = _timed_verify(corpus.papers, quote, latencies)
        tallies[cls][0] += match is not None
        tallies[cls][1] += 1
        cases.append({"class": cls, "quote": quote, "expected_accept": expected, "accepted": match is not None,
                      "matched_source": match.source if match else None, "sampled_source": source})

    for _ in range(quotes):
        name = rng.choice(eligible)
        length = rng.randint(min_words, max_words)
        start = rng.randrange(0, len(corpus.tokens[name]) - length)
        words = corpus.words(name, start, length)
        verbatim = corpus.window(name, start, length)

        before = tallies["verbatim"][0]
        score("verbatim", verbatim, name)
        if tallies["verbatim"][0] > before and cases[-1]["matched_source"] == name:
            attributed += 1

        separators = [rng.choice([" ", "  ", "\n", "\t", " \n "]) for _ in words[1:]]
        cased = [w.upper() if rng.random() < 0.3 else w.lower() if rng.random() < 0.5 else w for w in words]
        reformatted = cased[0] + "".join(sep + w for sep, w in zip(separators, cased[1:]))
        score("reformatted", reformatted, name)

        other = rng.choice([n for n in eligible if n != name])
        position = rng.randrange(1, length - 1)
        donor_spans = corpus.tokens[other]
        replacement = words[position]
        for _attempt in range(50):
            a, b = donor_spans[rng.randrange(len(donor_spans))]
            candidate = corpus.papers[other][a:b]
            if candidate.lower() != words[position].lower():
                replacement = candidate
                break
        substituted = words[:position] + [replacement] + words[position + 1:]
        score("substituted", " ".join(substituted), name)

        swap_at = next((i for i in range(position, length - 1) if words[i].lower() != words[i + 1].lower()),
                       next((i for i in range(1, length - 1) if words[i].lower() != words[i + 1].lower()), None))
        if swap_at is not None:
            swapped = list(words)
            swapped[swap_at], swapped[swap_at + 1] = swapped[swap_at + 1], swapped[swap_at]
            score("swapped", " ".join(swapped), name)

        half = length // 2
        other_start = rng.randrange(0, len(donor_spans) - (length - half))
        spliced = words[:half] + corpus.words(other, other_start, length - half)
        score("spliced", " ".join(spliced), None)

        score("short_fragment", " ".join(words[:MIN_QUOTE_WORDS - 1]), name)

    fabricated_hits = sum(tallies[c][0] for c in ("substituted", "swapped", "spliced"))
    fabricated_total = sum(tallies[c][1] for c in ("substituted", "swapped", "spliced"))
    disagreements = [c for c in cases if c["accepted"] != c["expected_accept"]]
    ctx.add_artifact("cases.json", cases, "case_table")
    median_latency = sorted(latencies)[len(latencies) // 2] if latencies else None
    return RunOutput(
        measurements={
            "verbatim_cases": tallies["verbatim"][1],
            "verbatim_acceptance_rate": _rate(*tallies["verbatim"]),
            "reformatted_acceptance_rate": _rate(*tallies["reformatted"]),
            "fabricated_cases": fabricated_total,
            "fabricated_acceptance_rate": _rate(fabricated_hits, fabricated_total),
            "substituted_acceptance_rate": _rate(*tallies["substituted"]),
            "swapped_acceptance_rate": _rate(*tallies["swapped"]),
            "spliced_acceptance_rate": _rate(*tallies["spliced"]),
            "short_fragment_acceptance_rate": _rate(*tallies["short_fragment"]),
            "relabeled_cases": tallies["relabeled"][1],
            "oracle_disagreements": len(disagreements),
            "source_attribution_rate": _rate(attributed, tallies["verbatim"][0]),
            "median_verify_latency_ms": median_latency,
        },
        series={"verify_latency_ms": latencies},
        inputs=corpus.inputs,
        observations=[f"{len(cases)} verifier calls over {len(corpus.names)} corpus files.",
                      f"{len(disagreements)} case(s) where the verifier disagreed with the contract oracle."],
        limitations=["Latency depends on the host machine and load; it is recorded, not evaluated."],
    )


def run_citation_typography(ctx: RunContext) -> RunOutput:
    """Do genuine quotes survive typographic normalization (curly → straight, dash → hyphen)?"""
    quotes = _int_param(ctx.parameters, "quotes", 1, 10_000)
    min_words = _int_param(ctx.parameters, "min_words", MIN_QUOTE_WORDS + 1, 200)
    max_words = _int_param(ctx.parameters, "max_words", min_words, 200)
    corpus = _Corpus(ctx.parameters.get("corpus_dir", "papers"))
    rng = random.Random(ctx.seed)
    special = set(TYPOGRAPHIC_QUOTES) | set(TYPOGRAPHIC_DASHES)

    anchors = [(name, i) for name in corpus.names for i, (a, b) in enumerate(corpus.tokens[name])
               if any(ch in special for ch in corpus.papers[name][a:b])]
    rng.shuffle(anchors)
    latencies: list[float] = []
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    tallies = {k: [0, 0] for k in ("control", "all_folded", "quotes_folded", "dashes_folded")}
    already_present = 0

    def fold(text: str, table: dict[str, str]) -> str:
        return "".join(table.get(ch, ch) for ch in text)

    for name, anchor in anchors:
        if tallies["control"][1] >= quotes:
            break
        length = rng.randint(min_words, max_words)
        total = len(corpus.tokens[name])
        if total < length:
            continue
        start = max(0, min(anchor - rng.randrange(length), total - length))
        original = corpus.window(name, start, length)
        if original in seen:
            continue
        seen.add(original)
        folded = fold(original, {**TYPOGRAPHIC_QUOTES, **TYPOGRAPHIC_DASHES})
        if corpus.oracle(folded):
            already_present += 1  # the ASCII form exists verbatim somewhere; not a typography test
            continue
        control = _timed_verify(corpus.papers, original, latencies) is not None
        tallies["control"][0] += control
        tallies["control"][1] += 1
        accepted = _timed_verify(corpus.papers, folded, latencies) is not None
        tallies["all_folded"][0] += accepted
        tallies["all_folded"][1] += 1
        case = {"source": name, "original": original, "folded": folded, "control_accepted": control,
                "folded_accepted": accepted}
        for key, table in (("quotes_folded", TYPOGRAPHIC_QUOTES), ("dashes_folded", TYPOGRAPHIC_DASHES)):
            if any(ch in original for ch in table):
                partial = _timed_verify(corpus.papers, fold(original, table), latencies) is not None
                tallies[key][0] += partial
                tallies[key][1] += 1
                case[f"{key}_accepted"] = partial
        cases.append(case)

    ctx.add_artifact("cases.json", cases, "case_table")
    return RunOutput(
        measurements={
            "typographic_cases": tallies["all_folded"][1],
            "control_acceptance_rate": _rate(*tallies["control"]),
            "typographic_variant_acceptance_rate": _rate(*tallies["all_folded"]),
            "quote_mark_variant_acceptance_rate": _rate(*tallies["quotes_folded"]),
            "quote_mark_cases": tallies["quotes_folded"][1],
            "dash_variant_acceptance_rate": _rate(*tallies["dashes_folded"]),
            "dash_cases": tallies["dashes_folded"][1],
            "excluded_ascii_form_present": already_present,
            "median_verify_latency_ms": sorted(latencies)[len(latencies) // 2] if latencies else None,
        },
        series={"verify_latency_ms": latencies},
        inputs=corpus.inputs,
        observations=[f"{len(anchors)} tokens in the corpus contain curly quotes or en/em dashes."],
        limitations=["Only quote-mark and dash folding is tested; ellipses, ligatures and Unicode "
                     "normalization forms are not.",
                     "Latency depends on the host machine and load; it is recorded, not evaluated."],
    )
