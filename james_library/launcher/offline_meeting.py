"""Offline research meeting: the no-model demo, grounded in verbatim corpus quotes.

The instant demo has to work before any model is installed, but it should still
show what R.A.I.N. Lab does: four agents with different jobs read the same local
papers, the strongest counter-argument lands on the page, and the meeting ends
with a next move. This module builds that meeting deterministically:

* Sentences are extracted from the citation corpus (``papers/`` by default)
  and ranked against the question with BM25. Nothing is paraphrased: every
  quote is a verbatim span of a corpus file.
* Each agent chooses evidence through its own lens (measured results,
  buildability, cross-paper structure, stated limitations).
* Every quote is re-verified with :func:`citation_corpus.verify_quote`, the
  same verifier the live meeting uses, and the corpus is fingerprinted.
* When the library does not cover the question, the room says so instead of
  presenting unrelated passages as evidence.

The reasoning text is scripted. The meeting says so, and the evidence is real.
The module uses only the standard library, so the demo runs on a bare Python
install.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from james_library.utilities.citation_corpus import (
    discover_corpus_files,
    find_quote_span,
    hash_corpus_files,
    verify_quote,
)

DEFAULT_QUESTION = "Can resonance patterns reveal what drives a complex adaptive system?"

MIN_QUOTE_WORDS = 12
MAX_QUOTE_WORDS = 42
CANDIDATE_POOL = 60
EVIDENCE_WINDOW = 12

GROUNDING_STRONG = "strong"
GROUNDING_PARTIAL = "partial"
GROUNDING_NONE = "none"

AGENT_ROLES = {
    "James": "Lead Scientist",
    "Jasmine": "Hardware Architect",
    "Luca": "Field Topographer",
    "Elena": "Quantum Information Theorist",
}

_STOPWORDS = frozenset(
    """
    a about above across actually after again against all also an and any are as at be because been
    before being between both but by can could did do does doing done during each either else even
    ever every few for from further had has have having how however i if in into is it its itself never always
    know tell think
    just like made make many may me might more most much must my need no nor not now of off often on
    once only or other our out over own per rather really same say says should so some such than that
    the their them then there these they this those through thus to too under until up upon us very
    via was we were what when where whether which while who whom why will with within without would
    yet you your
    """.split()
)

# Words too generic to count as a shared structure between two papers.
_GENERIC_TERMS = frozenset(
    """
    paper work result method approach section figure table use used using provide show base based
    present new one two first second claim system model framework general specific different example
    case given single multiple various several overall important key main potential possible simple high
    low large small level form type part point way set number term order direct further
    """.split()
)
_SUFFIXES = tuple("ational ization ations ation ities ity ness ments ment ingly ing edly ed ies es ly s".split())

_WORD_RE = re.compile(r"[^\W\d_][^\W_]*(?:-[^\W_]+)*")
_SENTENCE_END_RE = re.compile(r"[.!?][\"”’)]?\s+(?=[\"“(]?[A-Z])")
_ENUMERATED_HEADING_RE = re.compile(r"^(?:#{1,6}\s*)?(?:[IVXLC]+|[A-Z]|\d+(?:\.\d+)*)[.)]\s+\S")
_BARE_ENUMERATOR_RE = re.compile(r"^(?:[IVXLC]+|[A-Z]|\d+(?:\.\d+)*)[.)]?$")
_REFERENCES_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:[IVXLC]+\.\s*)?(?:references|bibliography)\s*$", re.I | re.M)
_ABSTRACT_RE = re.compile(r"\babstract\b", re.I)
_ABSTRACT_PREFIX_RE = re.compile(r"^abstract\s*[—–\-:.]*\s*", re.I)
_ABBREVIATIONS = frozenset("e.g. i.e. fig. eq. al. vs. u.s. dr. no. approx. cf. etc.".split())
_REJECT_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"[a-z]- [a-z]",  # PDF hyphenation break
        r"\b[A-Z]{6,}\b",  # shouted heading glued to a sentence
        r"[#•@|<>{}=]",
        r"https?:|www\.",
        r"\.\s\d+(?:\.\d+)*\s[A-Z]",  # numbered heading inside the sentence
        r"\s\d+\.$",  # trailing list or claim number
        r"\bet al\b",
        r"\bpp\.",
        r"\[\d",
        r"\bPage \d+\b",
        r"Index Terms",
        r"---",
        r"[´¨ˆ˜]",  # detached accents from PDF extraction
        r"[\u0370-\u03ff][a-z]",  # Greek symbol with a flattened subscript, e.g. "ωloc"
        r"\b(?:Eqs?|Fig|Figs|Table)\.?\s*\(?\d",  # cross-references read badly out of context
    )
)
_TOKEN_RE = re.compile(r"[\"“(]?[A-Za-z][A-Za-z'’\-]*[.,;:)\"”’]*")
_NUMERIC_TOKEN_RE = re.compile(r"[(\[]?[$€£]?\d+(?:[.,/:]\d+)*(?:%|x)?[)\]]?[.,;:]?")
_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w.]*\d)")
_YEAR_RE = re.compile(r"^(?:18|19|20)\d\d$")
_MINOR_WORDS = frozenset({"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "via", "vs"})
_ANAPHORIC_OPENERS = frozenset({"this", "that", "these", "those", "it", "they", "such", "here", "there"})

# Lens lexicons are matched against stemmed terms by prefix.
_RESULT_STEMS = tuple(
    "detect measur yield demonstrat observ reproduc improv recover achiev record extend increas reduc exceed "
    "estimat".split()
)
_BUILD_STEMS = tuple(
    "hardware device sensor actuat power energy thermal heat temperatur material fabricat implement prototyp "
    "circuit voltage noise latenc cost calibrat instrument apparatus laser magnet coil cool microcontroller "
    "electrode toleranc precision hz khz mhz ghz watt".split()
)
_MEASURE_STEMS = tuple(
    "measur data sample estimat metric instrument benchmark observ record signal detect monitor diagnost "
    "calibrat indicator stress".split()
)
_SHAPE_STEMS = tuple(
    "geometr topolog field phase spectr coheren symmetr manifold pattern wave mode modal structur lattice spiral "
    "interferen resonan curvatur holograph attractor oscillat gradient node frequenc".split()
)
_TEST_STEMS = tuple("predict test experiment benchmark falsif validat replicat control comparator".split())
_WEAK_TEST_STEMS = tuple("measur protocol reproduc audit compar".split())
_HEDGES: tuple[tuple[str, float], ...] = (
    ("does not establish", 3.0),
    ("cannot, by itself", 3.0),
    ("cannot by itself", 3.0),
    ("not constitut", 3.0),
    ("independent validation", 3.0),
    ("requires independent", 3.0),
    ("no direct causal", 3.0),
    ("not a proof", 3.0),
    ("does not validate", 3.0),
    ("does not prove", 3.0),
    ("unmeasured", 3.0),
    ("not established", 3.0),
    ("to be tested", 2.0),
    ("untested", 3.0),
    ("limitation", 1.5),
    ("counterexample", 2.5),
    ("does not", 2.0),
    ("cannot", 2.0),
    ("not yet", 2.0),
    ("unverified", 2.0),
    ("speculative", 2.0),
    ("assum", 1.5),
    ("hypothe", 1.5),
    ("uncertain", 1.5),
    ("caveat", 1.5),
    ("preliminary", 1.5),
    ("only if", 1.5),
    ("despite", 1.0),
    ("however", 1.0),
    ("although", 1.0),
    ("rather than", 0.5),
)
_STRONG_HEDGE = 3.0
_COUNTER_HEDGE = 2.0

# Constraint families Jasmine needs before she calls something buildable (hardware topics)
# or measurable (everything else).
_HARDWARE_CONSTRAINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("a power budget", ("power", "energy", "watt", "joule")),
    ("a cost", ("cost", "price", "afford")),
    ("a tolerance", ("toleranc", "precision", "accuracy")),
    ("a noise floor", ("noise", "snr", "signal-to-noise")),
    ("a thermal limit", ("thermal", "heat", "temperatur", "cooling")),
)
_MEASUREMENT_CONSTRAINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("an error bar", ("error bar", "uncertaint", "confidence interval", "standard deviation", "±")),
    ("a baseline", ("baseline", "comparator", "control group", "null model")),
    ("a sample size", ("sample size", "sample of", "observations", "trials", "n =")),
)
_HARDWARE_STEMS = tuple(
    "hardware device sensor actuat power energy thermal heat temperatur voltage circuit magnet laser coil electrode "
    "fabricat prototyp material plasma piezo transducer hz khz mhz ghz watt".split()
)


@dataclass(frozen=True)
class Passage:
    """One verbatim sentence from a corpus file."""

    source: str
    title: str
    text: str
    line: int
    span_start: int
    span_end: int

    @property
    def citation(self) -> str:
        return f"{self.source}:{self.line}"


@dataclass(frozen=True)
class Turn:
    """One agent contribution: a lead-in, optional verbatim quotes, and a coda."""

    speaker: str
    move: str
    lead: str
    quotes: tuple[Passage, ...] = ()
    coda: str = ""

    @property
    def role(self) -> str:
        return AGENT_ROLES[self.speaker]


@dataclass(frozen=True)
class Verdict:
    agreed: str
    contested: str
    next_move: str
    read_next: tuple[str, ...]


@dataclass(frozen=True)
class CitationAudit:
    checked: int
    verified: int
    corpus_files: int
    corpus_sha256: str

    @property
    def passed(self) -> bool:
        return self.checked == self.verified


@dataclass(frozen=True)
class OfflineMeeting:
    question: str
    corpus_root: Path
    corpus_files: int
    quotable_passages: int
    grounding: str
    matched_terms: tuple[str, ...]
    missing_terms: tuple[str, ...]
    turns: tuple[Turn, ...]
    verdict: Verdict
    audit: CitationAudit
    suggestions: tuple[str, ...] = ()

    @property
    def quotes(self) -> tuple[Passage, ...]:
        return tuple(quote for turn in self.turns for quote in turn.quotes)


@dataclass(frozen=True)
class _Sentence:
    source: str
    title: str
    text: str
    terms: tuple[str, ...]


@dataclass
class _Corpus:
    root: Path
    documents: dict[str, str]
    sentences: list[_Sentence]
    postings: dict[str, list[int]]
    idf: dict[str, float]
    average_length: float
    surface: dict[str, str]
    files: list[Path]


@dataclass(frozen=True)
class _Scored:
    index: int
    relevance: float


# ---------------------------------------------------------------------------
# Text processing
# ---------------------------------------------------------------------------


def _stem(word: str) -> str:
    """A deliberately small suffix stripper: enough to match "patterns" to "pattern", nothing clever."""

    for suffix in _SUFFIXES:
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            stem = word[: -len(suffix)]
            if suffix == "ies":
                return stem + "y"
            if suffix in {"ed", "ing"} and len(stem) > 3 and stem[-1] == stem[-2] and stem[-1] not in "lsz":
                return stem[:-1]  # "lagged" -> "lag", "mapping" -> "map"
            return stem
    return word


def _words(text: str) -> list[str]:
    """Lowercase words; a hyphenated compound also contributes its parts ("lead-lag" -> "lead", "lag")."""

    words: list[str] = []
    for word in _WORD_RE.findall(text.lower()):
        words.append(word)
        if "-" in word:
            words.extend(part for part in word.split("-") if part)
    return [word for word in words if len(word) > 2 and word not in _STOPWORDS]


def _terms(text: str) -> list[str]:
    return [_stem(word) for word in _words(text)]


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        # Markdown headings, but also PDF-to-markdown debris like "# This paper formalizes...".
        stripped = stripped.lstrip("#").strip()
        if not stripped:
            return True
    if _BARE_ENUMERATOR_RE.match(stripped):
        return True
    words = stripped.split()
    if len(words) > 9 or stripped[-1] in ".,;:!?":
        return False
    if _ENUMERATED_HEADING_RE.match(stripped):
        return True
    alpha = [word for word in words if word[:1].isalpha()]
    if not alpha:
        return True
    capitalized = sum(1 for word in alpha if word[0].isupper() or word.lower() in _MINOR_WORDS)
    return capitalized == len(alpha) and alpha[0][0].isupper()


def _body_text(content: str) -> str:
    """Drop the byline block before the abstract and the reference list at the end."""

    body = content
    last_reference = None
    for last_reference in _REFERENCES_RE.finditer(body):
        pass
    if last_reference is not None and last_reference.start() > len(body) * 0.4:
        body = body[: last_reference.start()]
    abstract = _ABSTRACT_RE.search(body[:4000])
    if abstract is not None:
        body = body[abstract.start() :]
    return body


def _blocks(body: str) -> list[str]:
    """Join wrapped lines into paragraphs; blank lines and headings end a paragraph."""

    blocks: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        if not line.strip() or _is_heading(line):
            if current:
                blocks.append(" ".join(" ".join(current).split()))
                current = []
            continue
        current.append(line.strip().lstrip("#").strip())
    if current:
        blocks.append(" ".join(" ".join(current).split()))
    return blocks


def _split_sentences(block: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END_RE.finditer(block):
        end = match.start() + 1
        while end < len(block) and block[end] in "\"”’)":
            end += 1
        candidate = block[start:end]
        last_token = candidate.rsplit(" ", 1)[-1].lower()
        if last_token in _ABBREVIATIONS or re.fullmatch(r"(?:[a-z]\.)+", last_token):
            continue
        sentences.append(candidate.strip())
        start = match.end()
    tail = block[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _is_quotable(sentence: str) -> bool:
    words = sentence.split()
    if not MIN_QUOTE_WORDS <= len(words) <= MAX_QUOTE_WORDS:
        return False
    if not sentence[0].isupper() or sentence[-1] not in ".!?":
        return False
    if sentence.count("(") != sentence.count(")"):
        return False
    if any(pattern.search(sentence) for pattern in _REJECT_PATTERNS):
        return False
    # Numbers are welcome (they are James's favourite evidence); stray math symbols are not.
    wordlike = sum(1 for word in words if _TOKEN_RE.fullmatch(word) or _NUMERIC_TOKEN_RE.fullmatch(word))
    return wordlike / len(words) >= 0.85


def _load_corpus(root: Path) -> _Corpus:
    files = discover_corpus_files(root)
    documents: dict[str, str] = {}
    sentences: list[_Sentence] = []
    seen: set[str] = set()
    surface_counts: dict[str, Counter[str]] = {}

    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        source = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.name
        documents[source] = content
        title = path.stem
        for block in _blocks(_body_text(content)):
            for raw in _split_sentences(block):
                text = _ABSTRACT_PREFIX_RE.sub("", raw)
                key = text.lower()
                if key in seen or not _is_quotable(text):
                    continue
                seen.add(key)
                for word in _words(text):
                    surface_counts.setdefault(_stem(word), Counter())[word] += 1
                sentences.append(_Sentence(source, title, text, tuple(_terms(text))))

    postings: dict[str, list[int]] = {}
    for index, sentence in enumerate(sentences):
        for term in set(sentence.terms):
            postings.setdefault(term, []).append(index)
    total = len(sentences)
    idf = {term: math.log(1 + (total - len(hits) + 0.5) / (len(hits) + 0.5)) for term, hits in postings.items()}
    average_length = sum(len(sentence.terms) for sentence in sentences) / total if total else 0.0
    surface = {stem: counts.most_common(1)[0][0] for stem, counts in surface_counts.items()}
    return _Corpus(root, documents, sentences, postings, idf, average_length, surface, files)


# ---------------------------------------------------------------------------
# Retrieval and lenses
# ---------------------------------------------------------------------------


def _paper_coverage(corpus: _Corpus, query: list[str]) -> dict[str, float]:
    """Fraction of the question's terms that each paper uses anywhere in its quotable text."""

    unique = set(query)
    title_terms: dict[str, set[str]] = {}
    for sentence in corpus.sentences:
        title_terms.setdefault(sentence.title, set()).update(sentence.terms)
    if not unique:
        return {title: 0.0 for title in title_terms}
    return {title: len(unique & terms) / len(unique) for title, terms in title_terms.items()}


def _rank(corpus: _Corpus, query: list[str]) -> list[_Scored]:
    """BM25 over sentences, nudged toward papers that cover more of the question."""

    unique = sorted(set(query))
    if not unique or not corpus.sentences:
        return []

    paper_coverage = _paper_coverage(corpus, unique)
    k1, b = 1.4, 0.75
    scores: dict[int, float] = {}
    matches: Counter[int] = Counter()
    for term in unique:
        for index in corpus.postings.get(term, ()):
            terms = corpus.sentences[index].terms
            frequency = terms.count(term)
            norm = k1 * (1 - b + b * len(terms) / corpus.average_length)
            scores[index] = scores.get(index, 0.0) + corpus.idf[term] * frequency * (k1 + 1) / (frequency + norm)
            matches[index] += 1

    ranked: list[_Scored] = []
    for index, score in scores.items():
        sentence = corpus.sentences[index]
        weight = 0.6 + paper_coverage[sentence.title]
        if sentence.text.split(" ", 1)[0].lower() in _ANAPHORIC_OPENERS:
            weight *= 0.7
        ranked.append(_Scored(index, score * weight))
    if not ranked:
        return []
    ranked.sort(key=lambda item: (-item.relevance, item.index))

    # One incidental shared word ("system", "drives") is not relevance. For multi-term
    # questions a passage must match two terms unless it scores close to the best hit.
    needed = 2 if len(unique) >= 3 else 1
    floor = ranked[0].relevance * 0.5
    kept = [item for item in ranked if matches[item.index] >= needed or item.relevance >= floor]
    return kept[:CANDIDATE_POOL]


def _stem_hits(terms: tuple[str, ...], stems: tuple[str, ...]) -> int:
    return sum(1 for term in set(terms) if term.startswith(stems))


def _has_number(text: str) -> bool:
    return any(not _YEAR_RE.match(number) for number in _NUMBER_RE.findall(text))


def _hedge_score(text: str) -> float:
    lowered = text.lower()
    return min(5.0, sum(weight for phrase, weight in _HEDGES if phrase in lowered))


def _test_score(sentence: _Sentence) -> float:
    """How directly a sentence proposes something that could fail. Zero unless a strong test word appears."""

    strong = _stem_hits(sentence.terms, _TEST_STEMS)
    return 2.0 * strong + _stem_hits(sentence.terms, _WEAK_TEST_STEMS) if strong else 0.0


def _build_score(sentence: _Sentence) -> float:
    return float(_stem_hits(sentence.terms, _BUILD_STEMS))


def _measure_score(sentence: _Sentence) -> float:
    return _stem_hits(sentence.terms, _MEASURE_STEMS) + (2.0 if _has_number(sentence.text) else 0.0)


def _quant_score(sentence: _Sentence) -> float:
    return (2.0 if _has_number(sentence.text) else 0.0) + min(2, _stem_hits(sentence.terms, _RESULT_STEMS))


def _pick(
    pool: list[_Scored],
    corpus: _Corpus,
    used: set[int],
    lens: Callable[[_Sentence], float | None],
    *,
    lens_weight: float = 0.5,
    min_lens: float | None = None,
    cited_sources: set[str] | None = None,
    min_relevance: float = 0.3,
) -> _Scored | None:
    """Best candidate under ``lens``, preferring papers no one has cited yet.

    ``min_relevance`` is relative to the best hit: a lens may reorder relevant
    passages, but it must not promote an off-topic one.
    """

    if not pool:
        return None
    top = pool[0].relevance or 1.0
    best: tuple[float, int] | None = None
    choice: _Scored | None = None
    for candidate in pool:
        if candidate.index in used or candidate.relevance < min_relevance * top:
            continue
        sentence = corpus.sentences[candidate.index]
        lens_value = lens(sentence)
        if lens_value is None or (min_lens is not None and lens_value < min_lens):
            continue
        score = (candidate.relevance / top) * (1 + lens_weight * lens_value)
        if cited_sources and sentence.source in cited_sources:
            score *= 0.8
        key = (score, -candidate.index)
        if best is None or key > best:
            best = key
            choice = candidate
    return choice


def _passage(corpus: _Corpus, index: int) -> Passage:
    sentence = corpus.sentences[index]
    content = corpus.documents[sentence.source]
    span = find_quote_span(content, sentence.text)
    if span is None:  # pragma: no cover - extraction only emits verbatim spans
        raise ValueError(f"extracted sentence is not verbatim in {sentence.source}")
    line = content.count("\n", 0, span[0]) + 1
    return Passage(sentence.source, sentence.title, sentence.text, line, span[0], span[1])


def _bridge(
    corpus: _Corpus,
    pool: list[_Scored],
    used: set[int],
    query: set[str],
) -> tuple[_Scored, _Scored, str] | None:
    """Two relevant passages from different papers that share structure beyond the question's words.

    A pair qualifies when it shares a geometric/structural term (Luca's lens) or at least two
    other distinctive terms. One incidental shared word is a coincidence, not a connection.
    """

    top = pool[0].relevance or 1.0
    candidates = [item for item in pool[:24] if item.index not in used and item.relevance >= 0.3 * top]
    if not candidates:
        return None
    max_idf = max(corpus.idf.values()) or 1.0
    best: tuple[float, int, int] | None = None
    result: tuple[_Scored, _Scored, str] | None = None
    for position, first in enumerate(candidates):
        first_sentence = corpus.sentences[first.index]
        first_terms = set(first_sentence.terms)
        for second in candidates[position + 1 :]:
            second_sentence = corpus.sentences[second.index]
            if second_sentence.title == first_sentence.title:
                continue
            shared = [
                term
                for term in first_terms & set(second_sentence.terms)
                if term not in query and term not in _GENERIC_TERMS and len(term) > 3
            ]
            if not any(term.startswith(_SHAPE_STEMS) for term in shared) and len(shared) < 2:
                continue
            # Prefer rare terms, and geometric vocabulary when rarity ties: that is Luca's lens.
            term = max(shared, key=lambda item: (corpus.idf[item] + 0.5 * item.startswith(_SHAPE_STEMS), item))
            score = first.relevance / top + second.relevance / top + corpus.idf[term] / max_idf
            key = (score, -first.index, -second.index)
            if best is None or key > best:
                best = key
                result = (first, second, _surface_in(first_sentence.text, term) or corpus.surface.get(term, term))
    return result


def _surface_in(text: str, stem: str) -> str:
    """The word in ``text`` that stems to ``stem``, so the quoted term appears in the quote."""

    for word in _words(text):
        if _stem(word) == stem:
            return word
    return ""


def _is_hardware_topic(passages: list[_Sentence]) -> bool:
    """True when hardware vocabulary runs through the evidence, not just one stray sentence."""

    hardware = sum(1 for sentence in passages if _stem_hits(sentence.terms, _HARDWARE_STEMS) > 0)
    return hardware >= max(3, len(passages) // 3)


def _missing_constraints(passages: list[_Sentence], *, hardware: bool) -> list[str]:
    stems = {term for sentence in passages for term in sentence.terms}
    lowered = " ".join(sentence.text.lower() for sentence in passages)
    missing: list[str] = []
    for label, markers in _HARDWARE_CONSTRAINTS if hardware else _MEASUREMENT_CONSTRAINTS:
        present = any(term.startswith(markers) for term in stems) or any(marker in lowered for marker in markers)
        if not present:
            missing.append(label)
    return missing


def _variant(key: str, options: tuple[str, ...]) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return options[digest[0] % len(options)]


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def _quoted_terms(items: list[str]) -> str:
    return _join([f"'{item}'" for item in items])


# ---------------------------------------------------------------------------
# Meeting assembly
# ---------------------------------------------------------------------------


def _question_terms(question: str) -> tuple[list[str], dict[str, str]]:
    surfaces: dict[str, str] = {}
    stems: list[str] = []
    for word in _words(question):
        stem = _stem(word)
        if stem not in surfaces:
            surfaces[stem] = word
            stems.append(stem)
    return stems, surfaces


def _grounding(corpus: _Corpus, pool: list[_Scored], query: list[str]) -> tuple[str, list[str], list[str]]:
    window = [corpus.sentences[item.index] for item in pool[:EVIDENCE_WINDOW]]
    seen = {term for sentence in window for term in sentence.terms}
    matched = [term for term in query if term in seen]
    missing = [term for term in query if term not in seen]
    coverage = len(matched) / len(query) if query else 0.0
    if len(pool) >= 3 and coverage >= 0.6:
        return GROUNDING_STRONG, matched, missing
    if len(pool) >= 2 and coverage >= 0.34:
        return GROUNDING_PARTIAL, matched, missing
    return GROUNDING_NONE, matched, missing


def _fingerprint(corpus: _Corpus) -> str:
    rows = hash_corpus_files(corpus.files, corpus.root) if corpus.files else []
    digest = hashlib.sha256()
    for row in rows:
        digest.update(f"{row['path']}\0{row['sha256']}\n".encode())
    return digest.hexdigest()


def _audit(corpus: _Corpus, turns: tuple[Turn, ...]) -> CitationAudit:
    quotes = [quote for turn in turns for quote in turn.quotes]
    verified = 0
    for quote in quotes:
        match = verify_quote(corpus.documents, quote.text)
        if match is not None and match.source == quote.source:
            verified += 1
    return CitationAudit(len(quotes), verified, len(corpus.documents), _fingerprint(corpus))


def _suggest_questions(corpus: _Corpus) -> tuple[str, ...]:
    """Questions the library can actually answer, one per best-covered paper.

    Each question uses the title words that are specific to that paper ("sovereign debt", not
    "resonant dynamics"), so asking it retrieves that paper rather than its neighbours.
    """

    counts = Counter(sentence.title for sentence in corpus.sentences)
    titles = [title for title, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]]
    questions: list[str] = []
    for title in titles:
        specific: list[str] = []
        for word in _words(title):
            hits = corpus.postings.get(_stem(word), [])
            own = sum(1 for index in hits if corpus.sentences[index].title == title)
            if hits and own / len(hits) >= 0.6:
                specific.append(word)
        questions.append(f"What do we really know about {' '.join(specific) or title}?")
    return tuple(questions)


def _default_question(corpus: _Corpus) -> str:
    """The built-in question when the library covers it, otherwise one the library can answer."""

    query, _ = _question_terms(DEFAULT_QUESTION)
    grounding, _, _ = _grounding(corpus, _rank(corpus, query), query)
    if grounding == GROUNDING_STRONG or not corpus.sentences:
        return DEFAULT_QUESTION
    return _suggest_questions(corpus)[0]


def build_offline_meeting(question: str | None, corpus_root: Path) -> OfflineMeeting:
    """Run the four-agent meeting over ``corpus_root`` without a model.

    With no question, the meeting uses :data:`DEFAULT_QUESTION` when the library covers it and
    otherwise a question drawn from the library itself, so a first run always has evidence.
    """

    corpus_root = Path(corpus_root)
    corpus = _load_corpus(corpus_root)
    question = " ".join((question or "").split()) or _default_question(corpus)
    query, surfaces = _question_terms(question)
    pool = _rank(corpus, query)
    grounding, matched, missing = _grounding(corpus, pool, query)
    matched_words = [surfaces[term] for term in matched]
    missing_words = [surfaces[term] for term in missing]

    if grounding == GROUNDING_NONE:
        turns = _ungrounded_turns(corpus, query, surfaces)
        verdict = Verdict(
            agreed="The local library has no evidence on this question, so the room made no claims about it.",
            contested="Nothing yet. A disagreement needs evidence on the table first.",
            next_move=(
                "Add two or three papers on this topic to the library and rerun the same command, "
                "or connect a local model for an open-ended meeting."
            ),
            read_next=(),
        )
        return OfflineMeeting(
            question=question,
            corpus_root=corpus_root,
            corpus_files=len(corpus.documents),
            quotable_passages=len(corpus.sentences),
            grounding=grounding,
            matched_terms=tuple(matched_words),
            missing_terms=tuple(missing_words),
            turns=turns,
            verdict=verdict,
            audit=_audit(corpus, turns),
            suggestions=_suggest_questions(corpus) if corpus.sentences else (),
        )

    turns, verdict = _grounded_turns(corpus, question, pool, query, grounding, matched_words, missing_words)
    return OfflineMeeting(
        question=question,
        corpus_root=corpus_root,
        corpus_files=len(corpus.documents),
        quotable_passages=len(corpus.sentences),
        grounding=grounding,
        matched_terms=tuple(matched_words),
        missing_terms=tuple(missing_words),
        turns=turns,
        verdict=verdict,
        audit=_audit(corpus, turns),
    )


@dataclass(frozen=True)
class _Evidence:
    """What each agent chose to put on the table, plus the retrieval context."""

    question: str
    grounding: str
    matched: list[str]
    missing: list[str]
    window_papers: list[str]
    window_sources: Counter[str]
    hardware: bool
    gaps: list[str]
    anchor: Passage | None
    build: Passage | None
    bridge: tuple[Passage, Passage] | None
    bridge_term: str
    counter: Passage | None
    test: Passage | None


def _select_evidence(
    corpus: _Corpus,
    question: str,
    pool: list[_Scored],
    query: list[str],
    grounding: str,
    matched: list[str],
    missing: list[str],
) -> _Evidence:
    used: set[int] = set()
    taken: set[int] = set()
    cited: set[str] = set()

    def take(choice: _Scored | None) -> Passage | None:
        if choice is None:
            return None
        passage = _passage(corpus, choice.index)
        taken.add(choice.index)
        cited.add(passage.source)
        # Retire near-duplicates too, so two agents never read out the same sentence twice.
        terms = set(corpus.sentences[choice.index].terms)
        for item in pool:
            if item.index == choice.index or _overlap(terms, set(corpus.sentences[item.index].terms)) >= 0.55:
                used.add(item.index)
        used.add(choice.index)
        return passage

    # Caveats are Elena's material: no one else may spend a hedged sentence as supporting evidence.
    top = pool[0].relevance or 1.0
    hedged = {item.index for item in pool if _hedge_score(corpus.sentences[item.index].text) >= _COUNTER_HEDGE}
    used.update(hedged)

    anchor = take(_pick(pool, corpus, used, _quant_score, lens_weight=0.35, min_relevance=0.0))
    bridge: tuple[Passage, Passage] | None = None
    bridge_term = ""
    pair = _bridge(corpus, pool, used, set(query))
    if pair is not None:
        first, second, bridge_term = pair
        first_passage, second_passage = take(first), take(second)
        if first_passage is not None and second_passage is not None:
            bridge = (first_passage, second_passage)
    window = [corpus.sentences[item.index] for item in pool[:EVIDENCE_WINDOW]]
    hardware = _is_hardware_topic(window)
    # A measurement needs a number or two measurement words; one stray "signal" is not an instrument.
    build_lens, build_floor = (_build_score, 1.0) if hardware else (_measure_score, 2.0)
    build = take(_pick(pool, corpus, used, build_lens, min_lens=build_floor, cited_sources=cited))
    test = take(_pick(pool, corpus, used, _test_score, min_lens=1.0))

    # Elena speaks from relevant caveats, or from a caveat a cited paper states about itself even
    # when it does not repeat the question's wording.
    cited_titles = {Path(source).stem for source in cited}
    relevance = {item.index: item.relevance for item in pool}
    relevant = [item for item in pool if item.index in hedged and item.relevance >= 0.25 * top]
    shortlisted = {item.index for item in relevant}
    candidates = relevant + [
        _Scored(index, relevance.get(index, 0.0))
        for index, sentence in enumerate(corpus.sentences)
        if index not in shortlisted
        and index not in taken
        and sentence.title in cited_titles
        and _hedge_score(sentence.text) >= _STRONG_HEDGE
    ]
    counter = take(_best_counter(candidates, corpus, top, anchor_title=anchor.title if anchor else None))

    return _Evidence(
        question=question,
        grounding=grounding,
        matched=matched,
        missing=missing,
        window_papers=sorted({sentence.title for sentence in window}),
        window_sources=Counter(sentence.source for sentence in window),
        hardware=hardware,
        gaps=_missing_constraints(window + [corpus.sentences[index] for index in sorted(used)], hardware=hardware),
        anchor=anchor,
        build=build,
        bridge=bridge,
        bridge_term=bridge_term,
        counter=counter,
        test=test,
    )


def _best_counter(
    candidates: list[_Scored],
    corpus: _Corpus,
    top: float,
    *,
    anchor_title: str | None,
) -> _Scored | None:
    """Elena's pick. A measured counterexample outranks a caveat about James's own source,
    which outranks a general disclaimer: she wants the leak rate, not the warning label."""

    best: tuple[float, int] | None = None
    choice: _Scored | None = None
    for candidate in candidates:
        sentence = corpus.sentences[candidate.index]
        score = _hedge_score(sentence.text) * (0.35 + candidate.relevance / top)
        score += 1.5 if _has_number(sentence.text) else 0.0
        score += 0.75 if sentence.title == anchor_title else 0.0
        key = (score, -candidate.index)
        if best is None or key > best:
            best, choice = key, candidate
    return choice


def _overlap(first: set[str], second: set[str]) -> float:
    """Share of the shorter sentence's terms that the other one repeats."""

    if not first or not second:
        return 0.0
    return len(first & second) / min(len(first), len(second))


def _papers_phrase(count: int) -> str:
    return f"{count} {'paper' if count == 1 else 'papers'}"


def _james_frame(ev: _Evidence) -> Turn:
    passages = sum(ev.window_sources.values())
    lead = (
        f"I pulled {passages} passages from {_papers_phrase(len(ev.window_papers))} "
        f"that speak to {_quoted_terms(ev.matched[:4])}."
    )
    if ev.grounding == GROUNDING_PARTIAL and ev.missing:
        lead += f" Nothing in the library touches {_quoted_terms(ev.missing[:3])}, so I'm scoping to what it covers."
    if ev.anchor is None:
        return Turn("James", "frame", lead, coda="None of it is a measured result, so everything below is a claim.")
    key = ev.question.lower()
    if _has_number(ev.anchor.text):
        coda = _variant(
            key + "james-number",
            (
                "That's a stated number, not a vibe, so that's where I anchor. The question is whether it survives "
                "this room.",
                "A number I can check. I'll anchor there and let the rest of you try to break it.",
            ),
        )
    else:
        coda = _variant(
            key + "james-claim",
            (
                "No number attached, so I'm logging it as a claim, not a result. Let's see if it survives this room.",
                "It's a clear statement, but it isn't a measurement. Treat it as the claim under test.",
            ),
        )
    return Turn("James", "frame", f"{lead} The most concrete line is in {ev.anchor.title}:", (ev.anchor,), coda)


def _jasmine_check(ev: _Evidence) -> Turn:
    if ev.build is None:
        return Turn(
            "Jasmine",
            "reality check",
            "I went looking for anything I could build or measure against: a sensor, a dataset, a number with "
            "units. Nothing in the retrieved passages qualifies.",
            coda="That's a gap, not a green light. I won't sign off on a mechanism nobody can instrument.",
        )
    key = ev.question.lower() + "jasmine-lead"
    if ev.hardware:
        lead = _variant(
            key,
            (
                f"Before we fall in love with it: can anyone build this? The closest thing to a spec is "
                f"in {ev.build.title}:",
                f"Okay, reality check. What would we actually wire up? {ev.build.title} gets closest:",
            ),
        )
        consequence = "and without those I can't spec or price a build"
        satisfied = "Rare case: the papers hand me constraints I can actually build against. I'm cautiously in."
    else:
        lead = _variant(
            key,
            (
                f"Before we fall in love with it: what would we actually measure? The closest thing to an "
                f"instrument is in {ev.build.title}:",
                f"Okay, reality check. What's the measurement here? {ev.build.title} gets closest:",
            ),
        )
        consequence = "and without those a clean-looking signal and a lucky one look identical"
        satisfied = "Rare case: the papers give me a measurement I could actually rerun. I'm cautiously in."
    if ev.gaps:
        coda = (
            f"That's something I can work with. What none of these passages gives me is {_join(ev.gaps[:2])}, "
            f"{consequence}."
        )
    else:
        coda = satisfied
    return Turn("Jasmine", "reality check", lead, (ev.build,), coda)


def _luca_connection(ev: _Evidence) -> Turn:
    if ev.bridge is None:
        if len(ev.window_papers) == 1:
            lead = f"Every strong hit comes from {ev.window_papers[0]}. One paper shows me a point, not a pattern."
        else:
            lead = "I tried to find the same structure in two different papers and couldn't. The hits don't rhyme yet."
        coda = "I'd want a second, independent framing before I call it structure."
        return Turn("Luca", "connection", lead, coda=coda)
    first, second = ev.bridge
    lead = _variant(
        ev.question.lower() + "luca-lead",
        (
            f"Look at the shape of this. {first.title} and {second.title} both reach for '{ev.bridge_term}', "
            "from different directions:",
            f"Here's what nobody said out loud. Two papers, two framings, one shared idea: '{ev.bridge_term}'.",
        ),
    )
    coda = (
        "Same structure, two framings. If it's real, one test should light up in both places, "
        "and that's the connection I'd chase."
    )
    return Turn("Luca", "connection", lead, ev.bridge, coda)


def _concentration_note(ev: _Evidence) -> str:
    total = sum(ev.window_sources.values())
    source, count = ev.window_sources.most_common(1)[0]
    share = round(100 * count / total)
    if share < 50:
        return ""
    return f"And {share}% of what James retrieved comes from a single paper, {Path(source).stem}. "


def _elena_counter(ev: _Evidence) -> Turn:
    note = _concentration_note(ev)
    if ev.counter is None:
        return Turn(
            "Elena",
            "counter-argument",
            "I looked for a stated limitation in what we pulled and found none. "
            "A claim that doesn't state its limits hasn't finished its argument.",
            coda=f"{note}I'd treat every claim here as unreviewed until someone tries to break it.",
        )
    lead = _variant(
        ev.question.lower() + "elena-lead",
        (
            f"Here's the strongest counter-argument, and it's in our own library. {ev.counter.title} says it plainly:",
            f"Before anyone gets attached: the best objection is already written down, in {ev.counter.title}:",
        ),
    )
    measured = (
        "That's a measured counterexample: a strong signal with nothing causal behind it. "
        if _has_number(ev.counter.text)
        else ""
    )
    coda = (
        f"{measured}{note}Until something outside this library reproduces James's anchor, "
        "this is a well-instrumented hypothesis, not a result."
    )
    return Turn("Elena", "counter-argument", lead, (ev.counter,), coda)


def _exchange(ev: _Evidence) -> list[Turn]:
    turns: list[Turn] = []
    if ev.bridge is not None:
        turns.append(
            Turn(
                "Luca",
                "pushback",
                f"Fair, Elena. But '{ev.bridge_term}' holding up in two separate framings is exactly what's worth "
                "testing, not dismissing.",
            )
        )
    turns.append(
        Turn(
            "Jasmine",
            "pushback",
            "Then give me one measurement that could come out the other way. Otherwise we're just admiring the shape.",
        )
    )
    return turns


def _james_close(ev: _Evidence) -> Turn:
    if ev.test is None:
        return Turn(
            "James",
            "next move",
            "Here's where I land. Nothing we pulled proposes a test that could fail, so designing one is the "
            f"next move, before anyone {'builds' if ev.hardware else 'acts on'} anything.",
        )
    return Turn(
        "James",
        "next move",
        f"Here's where I land. We don't need to invent the test; {ev.test.title} already points at one:",
        (ev.test,),
        "That's the next move: run it, and write down in advance the result that would kill the idea.",
    )


def _verdict(ev: _Evidence) -> Verdict:
    agreed = (
        f"The library speaks to this directly: {_papers_phrase(len(ev.window_papers))} "
        f"{'covers' if len(ev.window_papers) == 1 else 'cover'} "
        f"{_quoted_terms(ev.matched[:4])}" + (f", led by {ev.anchor.title}." if ev.anchor is not None else ".")
    )
    if ev.grounding == GROUNDING_PARTIAL and ev.missing:
        agreed += f" It is silent on {_quoted_terms(ev.missing[:3])}."

    if ev.bridge is not None:
        contested = (
            f"Luca reads the shared '{ev.bridge_term}' in {ev.bridge[0].title} and {ev.bridge[1].title} as real "
            "structure; Elena reads it as unreplicated until an outside source reproduces it."
        )
    elif ev.counter is not None:
        contested = f"Whether James's anchor survives the limitation {ev.counter.title} states about its own method."
    else:
        contested = "Whether any of these claims survive a test designed to break them. Nobody has run one yet."

    if ev.test is not None:
        next_move = (
            f"Run the test {ev.test.title} points to ({ev.test.citation}), with the failure condition written "
            "down first."
        )
    else:
        next_move = "Write one falsifiable prediction for this question and the measurement that would refute it."
    if ev.gaps and ev.build is not None:
        if ev.hardware:
            next_move += f" Put a number on {ev.gaps[0]} before building anything."
        else:
            next_move += f" Report it with {_join(ev.gaps[:2])}."

    # Read-next favours breadth: one citation per paper first, then the rest.
    ordered = [p for p in (ev.anchor, ev.counter, *(ev.bridge or ()), ev.test, ev.build) if p is not None]
    read_next: list[str] = []
    seen_sources: set[str] = set()
    for passage in ordered:
        if passage.source not in seen_sources:
            seen_sources.add(passage.source)
            read_next.append(passage.citation)
    for passage in ordered:
        if passage.citation not in read_next:
            read_next.append(passage.citation)
    return Verdict(agreed=agreed, contested=contested, next_move=next_move, read_next=tuple(read_next[:3]))


def _grounded_turns(
    corpus: _Corpus,
    question: str,
    pool: list[_Scored],
    query: list[str],
    grounding: str,
    matched: list[str],
    missing: list[str],
) -> tuple[tuple[Turn, ...], Verdict]:
    ev = _select_evidence(corpus, question, pool, query, grounding, matched, missing)
    turns = [_james_frame(ev), _jasmine_check(ev), _luca_connection(ev), _elena_counter(ev), *_exchange(ev)]
    turns.append(_james_close(ev))
    return tuple(turns), _verdict(ev)


def _ungrounded_turns(corpus: _Corpus, query: list[str], surfaces: dict[str, str]) -> tuple[Turn, ...]:
    searched = _quoted_terms([surfaces[term] for term in query[:5]]) or "this question"
    if corpus.sentences:
        library = (
            f"I searched {_papers_phrase(len(corpus.documents))} and {len(corpus.sentences)} quotable passages for "
            f"{searched}. Nothing speaks to it."
        )
    else:
        library = "There's no paper library here yet, so there is nothing to search."
    return (
        Turn(
            "James",
            "frame",
            library,
            coda="That's not in our active research context, and I won't dress up unrelated passages as evidence.",
        ),
        Turn(
            "Jasmine",
            "reality check",
            "Then let's be useful about what would count. What's the one number we could instrument on day one "
            "that tells us this works?",
        ),
        Turn(
            "Luca",
            "connection",
            "And what would it look like if it didn't work? Knowing the shape of failure tells us where to look first.",
        ),
        Turn(
            "Elena",
            "counter-argument",
            "State the claim so it can fail: what changes, by how much, measured how. Until then there is nothing "
            "for me to verify, and I'd rather say so than pretend.",
        ),
        Turn(
            "James",
            "next move",
            "Agreed. The next move is evidence: put two or three solid papers on this into the library and rerun, "
            "and this room will argue from them.",
        ),
    )
