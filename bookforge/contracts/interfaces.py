from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .artifact import ImmutableEpubArtifact
from .book import BookModel
from .common import SourceId
from .delivery import DeliveryAttempt, DeliveryProfile, PreflightReport
from .flow import ContentFlow
from .raw import RawDocument
from .semantic import BookState, BoundaryOperation, PageFragment
from .source import SourceDocumentReference
from .validation import ValidationRecord
from .evidence import EvidenceRegistry


class AssetResolver(Protocol):
    def resolve(self, reference: str | SourceId) -> Path: ...


class SourceExtractor(Protocol):
    def extract(self, source: SourceDocumentReference, path: Path) -> RawDocument: ...


class SemanticAnalyzer(Protocol):
    def analyze(self, raw: RawDocument, state: BookState | None = None) -> list[PageFragment]: ...


class BoundaryResolver(Protocol):
    def resolve(self, previous: PageFragment, current: PageFragment) -> list[BoundaryOperation]: ...


class FlowNormalizer(Protocol):
    def normalize(self, pages: list[PageFragment], operations: list[BoundaryOperation]) -> ContentFlow: ...


class BookAssembler(Protocol):
    def assemble(self, flow: ContentFlow) -> BookModel: ...


class EpubBuilder(Protocol):
    def build(
        self,
        book: BookModel,
        evidence_registry: EvidenceRegistry,
        asset_resolver: AssetResolver,
        output_path: Path,
    ) -> ImmutableEpubArtifact: ...


class BookValidator(Protocol):
    def validate(self, artifact: ImmutableEpubArtifact) -> ValidationRecord: ...


class DeliveryProvider(Protocol):
    provider_id: str

    def preflight(self, artifact: ImmutableEpubArtifact, profile: DeliveryProfile) -> PreflightReport: ...
    def send(self, artifact: ImmutableEpubArtifact, profile: DeliveryProfile, preflight: PreflightReport) -> DeliveryAttempt: ...
