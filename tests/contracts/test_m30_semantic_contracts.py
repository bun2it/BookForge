from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from bookforge.contracts.classification import (
    SEMANTIC_TAXONOMY_VERSION,
    ClassificationCandidate,
    ClassificationProvenance,
    ClassificationResult,
    ClassificationReview,
    ClassifierIdentity,
    ClassifierKind,
    RationaleCode,
    ReviewStatus,
)
from bookforge.contracts.common import DocumentId, SourceId
from bookforge.contracts.ids import classification_result_id, classification_review_id
from bookforge.contracts.raw import RawParagraph
from bookforge.contracts.semantic import SemanticFragment, SemanticType
from bookforge.contracts.source import SourceTextReference


FP = "a" * 64
SOURCE_ID = SourceId("docx_p000001")


def classifier() -> ClassifierIdentity:
    return ClassifierIdentity(
        name="bookforge.rules",
        kind=ClassifierKind.DETERMINISTIC,
        version="1.0.0",
    )


def result_id(semantic_type: SemanticType = SemanticType.PARAGRAPH) -> str:
    del semantic_type  # Classification is intentionally absent from stable identity inputs.
    return classification_result_id(
        target_source_ids=[SOURCE_ID],
        taxonomy_version=SEMANTIC_TAXONOMY_VERSION,
        classifier_name="bookforge.rules",
        classifier_version="1.0.0",
        configuration_fingerprint=FP,
        input_fingerprint=FP,
        context_fingerprint=FP,
    )


def classification(**updates: Any) -> ClassificationResult:
    data: dict[str, Any] = {
        "id": result_id(),
        "target_source_ids": (SOURCE_ID,),
        "source_references": (SourceTextReference(source_id=SOURCE_ID),),
        "semantic_type": SemanticType.PARAGRAPH,
        "confidence": 0.91,
        "candidates": (ClassificationCandidate(semantic_type=SemanticType.QUOTE, confidence=0.42),),
        "review_status": ReviewStatus.NOT_REQUIRED,
        "rationale_codes": (RationaleCode.SURROUNDED_BY_BODY,),
        "classifier": classifier(),
        "configuration_fingerprint": FP,
        "input_fingerprint": FP,
        "context_fingerprint": FP,
        "taxonomy_version": SEMANTIC_TAXONOMY_VERSION,
        "provenance": ClassificationProvenance(
            document_id=DocumentId("doc_aaaaaaaaaaaaaaaa"),
            source_ids=(SOURCE_ID,),
        ),
    }
    data.update(updates)
    return ClassificationResult(**data)


def test_classification_result_serialization_round_trip() -> None:
    original = classification()
    restored = ClassificationResult.model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.taxonomy_version == SEMANTIC_TAXONOMY_VERSION


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_bounds_are_enforced(confidence: float) -> None:
    with pytest.raises(ValidationError):
        classification(confidence=confidence)


def test_unknown_is_a_valid_semantic_decision_and_not_a_failure_state() -> None:
    value = classification(
        semantic_type=SemanticType.UNKNOWN,
        source_references=(),
        candidates=(),
        review_status=ReviewStatus.NEEDS_REVIEW,
    )
    assert value.semantic_type is SemanticType.UNKNOWN
    assert "failure" not in ClassificationResult.model_fields


def test_duplicate_candidate_semantic_types_are_rejected() -> None:
    duplicate = (
        ClassificationCandidate(semantic_type=SemanticType.QUOTE, confidence=0.7),
        ClassificationCandidate(semantic_type=SemanticType.QUOTE, confidence=0.2),
    )
    with pytest.raises(ValidationError, match="must not repeat"):
        classification(candidates=duplicate)


def test_review_classifier_taxonomy_rationale_and_fingerprints_are_validated() -> None:
    value = classification(review_status=ReviewStatus.NEEDS_REVIEW)
    assert value.classifier.kind is ClassifierKind.DETERMINISTIC
    assert value.rationale_codes == (RationaleCode.SURROUNDED_BY_BODY,)
    with pytest.raises(ValidationError):
        classification(configuration_fingerprint="not-a-sha256")
    with pytest.raises(ValidationError):
        classification(review_status="invented")


def test_text_is_never_persisted_and_textual_results_require_source_references() -> None:
    assert "text" not in ClassificationResult.model_fields
    with pytest.raises(ValidationError, match="authoritative source text reference"):
        classification(source_references=())
    with pytest.raises(ValidationError):
        classification(text="regenerated")


def test_source_references_must_belong_to_the_target() -> None:
    with pytest.raises(ValidationError, match="belong to the classification target"):
        classification(source_references=(SourceTextReference(source_id=SourceId("docx_p000002")),))


def test_reclassification_does_not_mutate_raw_evidence() -> None:
    raw = RawParagraph(
        id=SOURCE_ID,
        document_id=DocumentId("doc_aaaaaaaaaaaaaaaa"),
        order=1,
        text="Authoritative text",
    )
    first = classification()
    second = first.model_copy(update={"semantic_type": SemanticType.QUOTE})
    assert raw.text == "Authoritative text"
    assert first.semantic_type is SemanticType.PARAGRAPH
    assert second.semantic_type is SemanticType.QUOTE
    with pytest.raises(ValidationError):
        ClassificationResult.model_validate({**first.model_dump(), "text": "rewritten"})


def test_classification_id_is_stable_and_independent_of_selected_type() -> None:
    assert result_id(SemanticType.PARAGRAPH) == result_id(SemanticType.QUOTE)
    assert result_id().startswith("cls_")


def test_forbidden_flow_fields_are_absent() -> None:
    forbidden = {
        "page_break_before",
        "chapter_boundary",
        "join_behavior",
        "figure_placement",
        "caption_fragment_id",
        "checkpoint",
    }
    assert forbidden.isdisjoint(ClassificationResult.model_fields)
    with pytest.raises(ValidationError):
        classification(page_break_before=True)


def test_override_is_a_separate_auditable_record() -> None:
    original = classification(review_status=ReviewStatus.NEEDS_REVIEW)
    review_fingerprint = "b" * 64
    review = ClassificationReview(
        id=classification_review_id(
            classification_id=str(original.id),
            reviewer_name="reviewer@example",
            review_fingerprint=review_fingerprint,
        ),
        classification_id=original.id,
        original_semantic_type=original.semantic_type,
        status=ReviewStatus.REVIEWED_OVERRIDDEN,
        accepted_semantic_type=SemanticType.QUOTE,
        reviewer=ClassifierIdentity(
            name="reviewer@example",
            kind=ClassifierKind.HUMAN_REVIEW,
            version="1",
        ),
        review_fingerprint=review_fingerprint,
        rationale_codes=(RationaleCode.MODEL_CLASSIFICATION,),
        provenance=original.provenance,
    )
    assert review.classification_id == original.id
    assert original.semantic_type is SemanticType.PARAGRAPH
    assert review.accepted_semantic_type is SemanticType.QUOTE
    with pytest.raises(ValidationError, match="must change"):
        ClassificationReview.model_validate(
            {**review.model_dump(), "accepted_semantic_type": SemanticType.PARAGRAPH}
        )


def test_semantic_fragment_still_contains_references_not_authoritative_text() -> None:
    assert "text" not in SemanticFragment.model_fields
    assert "source_references" in SemanticFragment.model_fields
