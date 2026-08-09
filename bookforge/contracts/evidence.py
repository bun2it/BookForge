"""In-memory contract service resolving semantic references to raw source text."""

from __future__ import annotations

from typing import TypeAlias

from .common import SourceId
from .raw import RawParagraph, RawRun, RawTableCell, RawTextBlock
from .source import SourceTextReference

TextEvidence: TypeAlias = RawTextBlock | RawParagraph | RawRun | RawTableCell


class EvidenceRegistryError(LookupError):
    """Base class for typed evidence registry failures."""


class DuplicateEvidenceIdError(EvidenceRegistryError):
    def __init__(self, source_id: SourceId) -> None:
        super().__init__(f"evidence ID is already registered: {source_id}")
        self.source_id = source_id


class UnknownEvidenceIdError(EvidenceRegistryError):
    def __init__(self, source_id: SourceId) -> None:
        super().__init__(f"evidence ID is not registered: {source_id}")
        self.source_id = source_id


class InvalidSourceTextRangeError(EvidenceRegistryError):
    def __init__(self, source_id: SourceId, start: int, end: int, text_length: int) -> None:
        super().__init__(
            f"invalid half-open range [{start}, {end}) for {source_id}; source length is {text_length}"
        )
        self.source_id = source_id
        self.start = start
        self.end = end
        self.text_length = text_length


class EvidenceRegistry:
    """Unique SourceId index over immutable authoritative textual evidence."""

    def __init__(self) -> None:
        self._evidence: dict[SourceId, TextEvidence] = {}

    def register(self, evidence: TextEvidence) -> None:
        if evidence.id in self._evidence:
            raise DuplicateEvidenceIdError(evidence.id)
        self._evidence[evidence.id] = evidence

    def contains(self, source_id: SourceId) -> bool:
        return source_id in self._evidence

    def get(self, source_id: SourceId) -> TextEvidence:
        try:
            return self._evidence[source_id]
        except KeyError as error:
            raise UnknownEvidenceIdError(source_id) from error

    def resolve_text(self, reference: SourceTextReference) -> str:
        text = self.get(reference.source_id).text
        if reference.start_offset is None:
            return text
        assert reference.end_offset is not None
        if reference.end_offset > len(text):
            raise InvalidSourceTextRangeError(
                reference.source_id, reference.start_offset, reference.end_offset, len(text)
            )
        return text[reference.start_offset : reference.end_offset]

    def resolve_many(self, references: list[SourceTextReference]) -> tuple[str, ...]:
        """Resolve ordered segments without imposing any joining/merging policy."""
        return tuple(self.resolve_text(reference) for reference in references)
