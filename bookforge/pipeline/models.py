from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping

from bookforge.contracts.artifact import ImmutableEpubArtifact
from bookforge.contracts.assembly import (
    AssemblyPolicy, AssemblyReadinessReport, BookMetadataV3, BookModelV3,
)
from bookforge.contracts.classification import ClassificationReview
from bookforge.contracts.common import FragmentId
from bookforge.contracts.flow import LogicalListV3, ResolvedContentFlow, StructuralRegionAssignment
from bookforge.contracts.validation import ValidationRecord
from bookforge.docx.models import DocxExtractionResult
from bookforge.flow.models import AcceptedFlowReviewInput, FlowResolverPolicy, FlowResolverReport, FlowSourceFeatures
from bookforge.semantic.models import PipelineReport, SemanticClassifier


class PipelineStage(StrEnum):
    EXTRACTION = "extraction"
    SEMANTIC = "semantic"
    FLOW = "flow"
    ASSEMBLY = "assembly"
    RENDER = "render"
    VALIDATION = "validation"


class PipelineStageStatus(StrEnum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PipelineInput:
    source_docx: Path
    workspace_root: Path
    output_epub: Path
    metadata: BookMetadataV3
    semantic_classifier: SemanticClassifier
    structural_regions: StructuralRegionAssignment
    logical_lists: tuple[LogicalListV3, ...] = ()
    classification_reviews: tuple[ClassificationReview, ...] = ()
    flow_reviews: tuple[AcceptedFlowReviewInput, ...] = ()
    source_features: Mapping[FragmentId, FlowSourceFeatures] | None = None
    flow_policy: FlowResolverPolicy = FlowResolverPolicy()
    assembly_policy: AssemblyPolicy = AssemblyPolicy()


@dataclass(frozen=True, slots=True)
class PipelineResult:
    extraction: DocxExtractionResult
    semantic_report: PipelineReport
    flow_report: FlowResolverReport
    assembly_readiness: AssemblyReadinessReport
    resolved_flow: ResolvedContentFlow
    book: BookModelV3
    artifact: ImmutableEpubArtifact
    structural_validation: ValidationRecord
    epubcheck_validation: ValidationRecord
    stage_statuses: Mapping[PipelineStage, PipelineStageStatus]
    source_state_sha256_before: str
    source_state_sha256_after: str
