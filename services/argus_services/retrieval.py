"""Retrieval abstractions for policy-safe Argus notes."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .events import EventEnvelope
from .purge import normalize_scope, normalize_value


@dataclass(frozen=True)
class RetrievalNote:
    note_id: str
    source_event_ids: list[str]
    summary: str
    sensitivity: str
    redactions_applied: list[str]
    observed_at: str = ""
    embedding: list[float] = field(default_factory=list)


class EmbeddingModel(Protocol):
    dimension: int

    def embed(self, text: str) -> list[float]:
        ...


@dataclass(frozen=True)
class HashEmbeddingModel:
    """Deterministic local embedding fallback used until a model worker is configured."""

    dimension: int = 768

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = [token for token in text.lower().split() if token.strip()]
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


@dataclass
class InMemoryNoteIndex:
    notes: list[RetrievalNote] = field(default_factory=list)
    embedding_model: EmbeddingModel = field(default_factory=HashEmbeddingModel)

    def add_event(self, note_event: EventEnvelope) -> RetrievalNote | None:
        note = note_from_event(note_event, self.embedding_model)
        if note is None:
            return None
        self.notes.append(note)
        return note

    def search(self, query: str, top_k: int = 5) -> list[RetrievalNote]:
        terms = [term.lower() for term in query.split() if term.strip()]
        if not terms:
            return self.notes[-top_k:]

        query_embedding = self.embedding_model.embed(query)
        scored: list[tuple[float, RetrievalNote]] = []
        for note in self.notes:
            lexical_score = lexical_match_score(note, terms)
            vector_score = cosine_similarity(query_embedding, note.embedding)
            score = lexical_score * 2.0 + vector_score
            if lexical_score > 0 or vector_score > 0:
                scored.append((score, note))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [note for _, note in scored[:top_k]]

    def forget_scope(self, scope: str) -> int:
        remaining = []
        removed = 0
        for note in self.notes:
            if note_matches_scope(note, scope):
                removed += 1
            else:
                remaining.append(note)
        self.notes = remaining
        return removed


@dataclass
class LanceDBNoteIndex:
    """Policy-safe LanceDB-backed note index.

    The import is intentionally lazy so the rest of Argus can run without the
    optional LanceDB package installed.
    """

    path: str | Path
    table_name: str = "argus_notes"
    embedding_model: EmbeddingModel = field(default_factory=HashEmbeddingModel)
    database: Any | None = None
    table: Any | None = None

    def __post_init__(self) -> None:
        if self.database is None:
            import lancedb  # type: ignore[import-not-found]

            path = Path(self.path).expanduser()
            path.mkdir(parents=True, exist_ok=True)
            self.database = lancedb.connect(str(path))
        if self.table is None and self.database is not None:
            table_names = set(self.database.table_names())
            if self.table_name in table_names:
                self.table = self.database.open_table(self.table_name)

    def add_event(self, note_event: EventEnvelope) -> RetrievalNote | None:
        note = note_from_event(note_event, self.embedding_model)
        if note is None:
            return None
        record = note_to_record(note)
        if self.table is None:
            self.table = self.database.create_table(self.table_name, data=[record])
        else:
            self.table.add([record])
        return note

    def search(self, query: str, top_k: int = 5) -> list[RetrievalNote]:
        if self.table is None:
            return []
        rows = self.table.search(self.embedding_model.embed(query)).limit(top_k).to_list()
        return [
            note_from_record(row)
            for row in rows
            if row.get("sensitivity") != "blocked"
        ]

    def forget_scope(self, scope: str) -> int:
        if self.table is None:
            return 0
        rows = table_rows(self.table)
        note_ids = [
            str(row["note_id"])
            for row in rows
            if "note_id" in row and note_matches_scope(note_from_record(row), scope)
        ]
        if not note_ids:
            return 0
        if hasattr(self.table, "delete_note_ids"):
            self.table.delete_note_ids(note_ids)
        elif hasattr(self.table, "delete"):
            quoted = ", ".join(sql_quote(note_id) for note_id in note_ids)
            self.table.delete(f"note_id IN ({quoted})")
        return len(note_ids)


def note_from_event(
    note_event: EventEnvelope,
    embedding_model: EmbeddingModel,
) -> RetrievalNote | None:
    if note_event.event_type != "perception.note" or note_event.sensitivity == "blocked":
        return None

    payload = note_event.payload
    summary = payload.get("summary")
    source_event_ids = payload.get("evidence_event_ids", [])
    redactions = payload.get("redactions_applied", [])
    if not isinstance(summary, str):
        return None

    return RetrievalNote(
        note_id=note_event.event_id,
        source_event_ids=source_event_ids if isinstance(source_event_ids, list) else [],
        summary=summary,
        sensitivity=note_event.sensitivity,
        redactions_applied=redactions if isinstance(redactions, list) else [],
        observed_at=note_event.observed_at,
        embedding=embedding_model.embed(summary),
    )


def note_to_record(note: RetrievalNote) -> dict[str, Any]:
    return {
        "note_id": note.note_id,
        "source_event_ids": note.source_event_ids,
        "summary": note.summary,
        "sensitivity": note.sensitivity,
        "redactions_applied": note.redactions_applied,
        "observed_at": note.observed_at,
        "embedding": note.embedding,
    }


def note_from_record(row: dict[str, Any]) -> RetrievalNote:
    return RetrievalNote(
        note_id=str(row["note_id"]),
        source_event_ids=list(row.get("source_event_ids") or []),
        summary=str(row["summary"]),
        sensitivity=str(row["sensitivity"]),
        redactions_applied=list(row.get("redactions_applied") or []),
        observed_at=str(row.get("observed_at") or ""),
        embedding=list(row.get("embedding") or []),
    )


def note_matches_scope(note: RetrievalNote, scope: str) -> bool:
    normalized_scope = normalize_scope(scope)
    if normalized_scope == "all":
        return True
    values = {
        note.note_id,
        note.summary,
        note.sensitivity,
        *note.source_event_ids,
        *note.redactions_applied,
    }
    for value in values:
        normalized = normalize_value(value)
        if normalized == normalized_scope:
            return True
        if len(normalized_scope) >= 4 and normalized_scope in normalized:
            return True
    return False


def lexical_match_score(note: RetrievalNote, terms: list[str]) -> int:
    haystack = note.summary.lower()
    return sum(1 for term in terms if term in haystack)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(left_value * right_value for left_value, right_value in zip(left, right))


def table_rows(table: Any) -> list[dict[str, Any]]:
    if hasattr(table, "to_list"):
        return list(table.to_list())
    if hasattr(table, "to_pandas"):
        return table.to_pandas().to_dict("records")
    return []


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
