from __future__ import annotations

import hashlib
from pathlib import Path

from bookforge.assembly import BookAssembler
from bookforge.contracts.assembly import (
    AcceptedClassificationCatalog, AssemblyInput, BookContentCatalogV3,
)
from bookforge.docx import DocxExtractor
from bookforge.epub import EpubCheckValidator, EpubV3Builder, MappingAssetResolver, StructuralEpubValidator
from bookforge.flow import DeterministicFlowResolver
from bookforge.flow.models import FlowResolverInput, FlowSourceFeatures
from bookforge.semantic.pipeline import SemanticPipeline, generate_work_units, materialize_flow_node
from bookforge.semantic.workspace import SemanticWorkspace

from .models import PipelineInput, PipelineResult, PipelineStage, PipelineStageStatus


class PipelineIntegrationError(RuntimeError):
    pass


def _source_state_digest(extraction: object) -> str:
    workspace = extraction.workspace  # type: ignore[attr-defined]
    digest = hashlib.sha256()
    for name in ("source.json", "raw_document.json", "warnings.json"):
        path = workspace / name
        digest.update(name.encode())
        digest.update(path.read_bytes())
    for asset in extraction.assets:  # type: ignore[attr-defined]
        digest.update(asset.relative_path.encode())
        digest.update((workspace / asset.relative_path).read_bytes())
    return digest.hexdigest()


class PipelineRunner:
    """Coordinate deterministic stage owners without making content decisions."""

    def run(self, value: PipelineInput) -> PipelineResult:
        statuses = {stage: PipelineStageStatus.NOT_STARTED for stage in PipelineStage}
        extraction = DocxExtractor().extract(value.source_docx, value.workspace_root)
        statuses[PipelineStage.EXTRACTION] = PipelineStageStatus.COMPLETED
        before = _source_state_digest(extraction)

        semantic_report = SemanticPipeline().run(
            extraction.raw_document,
            extraction.evidence_registry,
            value.semantic_classifier,
            extraction.workspace,
        )
        if semantic_report.failed:
            raise PipelineIntegrationError("semantic stage contains failed work units")
        units = generate_work_units(extraction.raw_document)
        semantic_workspace = SemanticWorkspace(extraction.workspace)
        nodes = []
        classifications = {}
        for unit in units:
            result = semantic_workspace.load_result(unit.work_unit_id)
            if result is None:
                raise PipelineIntegrationError(f"semantic result is missing: {unit.work_unit_id}")
            node = materialize_flow_node(result, unit, extraction.raw_document)
            if node is None:
                raise PipelineIntegrationError(f"semantic truth remains unresolved: {unit.work_unit_id}")
            nodes.append(node)
            classifications[node.id] = result
        statuses[PipelineStage.SEMANTIC] = PipelineStageStatus.COMPLETED

        catalog = BookContentCatalogV3(nodes={node.id: node for node in nodes})
        accepted = AcceptedClassificationCatalog(
            document_id=extraction.document_id, by_fragment_id=classifications
        )
        features = value.source_features or {
            node.id: FlowSourceFeatures(source_order=index)
            for index, node in enumerate(nodes)
        }
        flow_input = FlowResolverInput(
            document_id=extraction.document_id,
            ordered_fragments=tuple(nodes),
            accepted_classifications=classifications,
            evidence_registry=extraction.evidence_registry,
            source_features=features,
            semantic_taxonomy_version=next(iter(classifications.values())).taxonomy_version,
            accepted_logical_lists=value.logical_lists,
            structural_regions=value.structural_regions,
            accepted_flow_reviews=value.flow_reviews,
        )
        flow_report = DeterministicFlowResolver(value.flow_policy).run(
            flow_input, extraction.workspace
        )
        flow = flow_report.resolved_flow
        if flow is None:
            raise PipelineIntegrationError("flow stage did not produce resolved content flow")
        statuses[PipelineStage.FLOW] = PipelineStageStatus.COMPLETED

        assembly_input = AssemblyInput(
            metadata=value.metadata,
            semantic_catalog=catalog,
            resolved_flow=flow,
            accepted_classifications=accepted,
            classification_reviews=value.classification_reviews,
            replacement_decisions=flow.replacement_decisions,
            policy=value.assembly_policy,
        )
        assembler = BookAssembler()
        readiness = assembler.preflight(assembly_input)
        if not readiness.ready:
            statuses[PipelineStage.ASSEMBLY] = PipelineStageStatus.BLOCKED
            assembler.assemble(assembly_input)
            raise AssertionError("unreachable")
        book = assembler.assemble(assembly_input)
        statuses[PipelineStage.ASSEMBLY] = PipelineStageStatus.COMPLETED

        asset_paths = {
            asset.relative_path: extraction.workspace / asset.relative_path
            for asset in extraction.assets
        }
        artifact = EpubV3Builder().build(
            book,
            extraction.evidence_registry,
            MappingAssetResolver(asset_paths),
            value.output_epub,
        )
        statuses[PipelineStage.RENDER] = PipelineStageStatus.COMPLETED
        structural = StructuralEpubValidator().validate(artifact, value.output_epub)
        epubcheck = EpubCheckValidator().validate(artifact, value.output_epub)
        statuses[PipelineStage.VALIDATION] = PipelineStageStatus.COMPLETED
        after = _source_state_digest(extraction)
        if before != after:
            raise PipelineIntegrationError("downstream stages mutated extracted source evidence")
        return PipelineResult(
            extraction=extraction,
            semantic_report=semantic_report,
            flow_report=flow_report,
            assembly_readiness=readiness,
            resolved_flow=flow,
            book=book,
            artifact=artifact,
            structural_validation=structural,
            epubcheck_validation=epubcheck,
            stage_statuses=statuses,
            source_state_sha256_before=before,
            source_state_sha256_after=after,
        )
