"""Retrieval abstractions for policy-safe Argus notes."""

from __future__ import annotations

from dataclasses import dataclass, field

from .events import EventEnvelope


@dataclass(frozen=True)
class RetrievalNote:
    note_id: str
    source_event_ids: list[str]
    summary: str
    sensitivity: str
    redactions_applied: list[str]


@dataclass
class InMemoryNoteIndex:
    notes: list[RetrievalNote] = field(default_factory=list)

    def add_event(self, note_event: EventEnvelope) -> RetrievalNote | None:
        if note_event.event_type != "perception.note" or note_event.sensitivity == "blocked":
            return None

        payload = note_event.payload
        summary = payload.get("summary")
        source_event_ids = payload.get("evidence_event_ids", [])
        redactions = payload.get("redactions_applied", [])
        if not isinstance(summary, str):
            return None

        note = RetrievalNote(
            note_id=note_event.event_id,
            source_event_ids=source_event_ids if isinstance(source_event_ids, list) else [],
            summary=summary,
            sensitivity=note_event.sensitivity,
            redactions_applied=redactions if isinstance(redactions, list) else [],
        )
        self.notes.append(note)
        return note

    def search(self, query: str, top_k: int = 5) -> list[RetrievalNote]:
        terms = [term.lower() for term in query.split() if term.strip()]
        if not terms:
            return self.notes[-top_k:]

        scored: list[tuple[int, RetrievalNote]] = []
        for note in self.notes:
            haystack = note.summary.lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, note))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [note for _, note in scored[:top_k]]
