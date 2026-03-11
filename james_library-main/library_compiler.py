"""Compile markdown notes into executable research artifacts.

This module implements a local-first "Compile Library" step that builds:
- TF-IDF index
- lightweight hashed embeddings
- entity graph
- equation index
- grounded quote span index
- contradiction candidates
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
BLOCK_EQ_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
INLINE_EQ_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", re.DOTALL)


@dataclass
class SourceDoc:
    path: Path
    text: str


def _should_include(path: Path) -> bool:
    name = path.name.upper()
    return path.suffix.lower() == ".md" and "SOUL" not in name and "LOG" not in name


def _read_docs(library_path: Path) -> list[SourceDoc]:
    docs: list[SourceDoc] = []
    for path in sorted(library_path.glob("*.md")):
        if not _should_include(path):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if text.strip():
            docs.append(SourceDoc(path=path, text=text))
    return docs


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in TOKEN_RE.finditer(text)]


def _hashed_embedding(tokens: list[str], dims: int = 128) -> list[float]:
    vec = [0.0] * dims
    if not tokens:
        return vec
    for tok in tokens:
        idx = int(hashlib.sha256(tok.encode("utf-8")).hexdigest(), 16) % dims
        vec[idx] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _build_tfidf(doc_tokens: dict[str, list[str]]) -> dict[str, Any]:
    n_docs = len(doc_tokens)
    df: Counter[str] = Counter()
    for toks in doc_tokens.values():
        df.update(set(toks))

    index: dict[str, dict[str, float]] = {}
    for doc, toks in doc_tokens.items():
        tf = Counter(toks)
        denom = max(len(toks), 1)
        scores: dict[str, float] = {}
        for term, cnt in tf.items():
            idf = math.log((1 + n_docs) / (1 + df[term])) + 1.0
            scores[term] = (cnt / denom) * idf
        # keep top 100 terms to control artifact size
        top_terms = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:100]
        index[doc] = {k: round(v, 6) for k, v in top_terms}
    return {"doc_count": n_docs, "index": index}


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    line_start = text.rfind("\n", 0, offset)
    col = offset + 1 if line_start == -1 else offset - line_start
    return line, col


def _extract_equations(doc: SourceDoc) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for kind, regex in (("block", BLOCK_EQ_RE), ("inline", INLINE_EQ_RE)):
        for m in regex.finditer(doc.text):
            start, end = m.span()
            line, col = _line_col(doc.text, start)
            out.append(
                {
                    "source": doc.path.name,
                    "type": kind,
                    "equation": m.group(1).strip(),
                    "span": {"start": start, "end": end, "line": line, "col": col},
                }
            )
    return out


def _extract_quote_spans(doc: SourceDoc) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for m in re.finditer(r"[^\n]{40,}", doc.text):
        quote = m.group(0).strip()
        if len(quote) < 40:
            continue
        start, end = m.span()
        line, col = _line_col(doc.text, start)
        spans.append(
            {
                "source": doc.path.name,
                "quote": quote[:280],
                "span": {"start": start, "end": end, "line": line, "col": col},
            }
        )
    return spans[:500]


def _extract_entities(doc: SourceDoc) -> set[str]:
    entities = set(re.findall(r"\b[A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,})*", doc.text))
    return {e.strip() for e in entities if len(e.strip()) > 2}


def _build_entity_graph(doc_entities: dict[str, set[str]]) -> dict[str, Any]:
    edges: Counter[tuple[str, str]] = Counter()
    nodes: Counter[str] = Counter()
    for entities in doc_entities.values():
        ent_list = sorted(entities)
        for e in ent_list:
            nodes[e] += 1
        for i, a in enumerate(ent_list):
            for b in ent_list[i + 1 :]:
                edges[(a, b)] += 1
    return {
        "nodes": [{"name": n, "count": c} for n, c in nodes.most_common(300)],
        "edges": [
            {"source": a, "target": b, "weight": w}
            for (a, b), w in edges.most_common(600)
        ],
    }


def _sentence_claims(doc: SourceDoc) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for sentence in SENTENCE_RE.split(doc.text):
        s = sentence.strip()
        if len(s) < 40:
            continue
        low = s.lower()
        if not any(x in low for x in (" is ", " are ", " must ", " cannot ", " never ", " always ")):
            continue
        subject = " ".join(_tokenize(s)[:5])
        claims.append({"source": doc.path.name, "subject": subject, "text": s, "negated": any(x in low for x in (" not ", " never ", " cannot "))})
    return claims


def _find_contradictions(all_claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_subject: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in all_claims:
        if c["subject"]:
            by_subject[c["subject"]].append(c)

    candidates: list[dict[str, Any]] = []
    for subject, claims in by_subject.items():
        for i, a in enumerate(claims):
            for b in claims[i + 1 :]:
                if a["negated"] == b["negated"]:
                    continue
                candidates.append(
                    {
                        "subject": subject,
                        "claim_a": {"source": a["source"], "text": a["text"][:220]},
                        "claim_b": {"source": b["source"], "text": b["text"][:220]},
                    }
                )
    return candidates[:300]


def compile_library(library_path: str, output_dir: str | None = None) -> dict[str, Any]:
    root = Path(library_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Library path does not exist: {root}")

    out = Path(output_dir).expanduser().resolve() if output_dir else (root / ".rain_compile")
    out.mkdir(parents=True, exist_ok=True)

    docs = _read_docs(root)
    doc_tokens = {d.path.name: _tokenize(d.text) for d in docs}
    embeddings = {name: _hashed_embedding(tokens) for name, tokens in doc_tokens.items()}

    doc_entities = {d.path.name: _extract_entities(d) for d in docs}
    equations = [eq for d in docs for eq in _extract_equations(d)]
    quote_spans = [q for d in docs for q in _extract_quote_spans(d)]
    claims = [c for d in docs for c in _sentence_claims(d)]
    contradictions = _find_contradictions(claims)

    artifacts = {
        "manifest": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "library_path": str(root),
            "file_count": len(docs),
            "files": [d.path.name for d in docs],
            "repro_steps": [
                "read markdown files from library root",
                "tokenize and compute tf-idf + hashed embeddings",
                "extract equations and quote spans with exact offsets",
                "derive entity co-occurrence graph",
                "detect contradiction candidates from claim polarity",
            ],
        },
        "tfidf_index": _build_tfidf(doc_tokens),
        "embeddings_index": {"dims": 128, "vectors": embeddings},
        "entity_graph": _build_entity_graph(doc_entities),
        "equation_index": equations,
        "grounded_quote_spans": quote_spans,
        "contradiction_candidates": contradictions,
    }

    paths = {
        "manifest": out / "manifest.json",
        "tfidf": out / "tfidf_index.json",
        "embeddings": out / "embeddings_index.json",
        "entity_graph": out / "entity_graph.json",
        "equations": out / "equation_index.json",
        "quotes": out / "grounded_quote_spans.json",
        "contradictions": out / "contradiction_candidates.json",
    }

    for key, path in paths.items():
        payload = artifacts["manifest"] if key == "manifest" else artifacts[f"{key}_index"] if key in {"tfidf", "embeddings"} else artifacts["entity_graph"] if key == "entity_graph" else artifacts["equation_index"] if key == "equations" else artifacts["grounded_quote_spans"] if key == "quotes" else artifacts["contradiction_candidates"]
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return {
        "output_dir": str(out),
        "file_count": len(docs),
        "equation_count": len(equations),
        "quote_span_count": len(quote_spans),
        "contradiction_candidate_count": len(contradictions),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Compile markdown library into research artifacts")
    parser.add_argument("--library", required=True, help="Path to markdown corpus")
    parser.add_argument("--output", default=None, help="Artifact output directory (default: <library>/.rain_compile)")
    args = parser.parse_args()

    result = compile_library(args.library, args.output)
    print(json.dumps(result, indent=2))
