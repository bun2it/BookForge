from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bookforge.contracts.common import DocumentId, SourceId
from bookforge.contracts.evidence import EvidenceRegistry
from bookforge.contracts.raw import RawDocument


@dataclass(frozen=True, slots=True)
class DocxExtractionWarning:
    code: str
    message: str
    source_id: SourceId | None = None
    part_name: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "source_id": self.source_id,
            "part_name": self.part_name,
        }


@dataclass(frozen=True, slots=True)
class ExtractedAsset:
    source_id: SourceId
    relative_path: str
    content_type: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "source_id": self.source_id,
            "relative_path": self.relative_path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class DocxExtractionResult:
    raw_document: RawDocument
    evidence_registry: EvidenceRegistry
    assets: tuple[ExtractedAsset, ...]
    warnings: tuple[DocxExtractionWarning, ...]
    source_sha256: str
    document_id: DocumentId
    workspace: Path
