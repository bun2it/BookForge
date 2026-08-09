from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import ContractModel, FragmentId
from .semantic import SemanticFigure, SemanticFragment, SemanticTable, SemanticType


class BookMetadata(ContractModel):
    title_fragment_id: FragmentId
    author_fragment_ids: list[FragmentId] = Field(default_factory=list)
    language: str
    identifier: str
    publisher: str | None = None
    description: str | None = None
    cover_reference: str | None = None


class Section(ContractModel):
    id: str
    title_fragment_id: FragmentId | None = None
    content_fragment_ids: list[FragmentId] = Field(default_factory=list)
    subsections: list[Section] = Field(default_factory=list)


class Chapter(ContractModel):
    id: str
    title_fragment_id: FragmentId | None = None
    content_fragment_ids: list[FragmentId] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)


class FrontMatter(ContractModel):
    content_fragment_ids: list[FragmentId] = Field(default_factory=list)


class BackMatter(ContractModel):
    content_fragment_ids: list[FragmentId] = Field(default_factory=list)


class BookContentCatalog(ContractModel):
    schema_version: Literal[2] = 2
    fragments: dict[FragmentId, SemanticFragment]
    figures: dict[FragmentId, SemanticFigure] = Field(default_factory=dict)
    tables: dict[FragmentId, SemanticTable] = Field(default_factory=dict)


class BookModel(ContractModel):
    schema_version: Literal[2] = 2
    revision: str
    metadata: BookMetadata
    front_matter: FrontMatter = Field(default_factory=FrontMatter)
    chapters: list[Chapter]
    back_matter: BackMatter = Field(default_factory=BackMatter)
    content: BookContentCatalog

    @model_validator(mode="after")
    def validate_content_integrity(self) -> "BookModel":
        catalog = self.content.fragments
        fragment_value_ids = [fragment.id for fragment in catalog.values()]
        if len(fragment_value_ids) != len(set(fragment_value_ids)):
            raise ValueError("content catalog contains duplicate fragment IDs")
        for key, fragment in catalog.items():
            if key != fragment.id:
                raise ValueError(f"fragment catalog key {key!r} does not match fragment ID {fragment.id!r}")

        logical_ids = self._logical_fragment_ids()
        missing = sorted(str(fragment_id) for fragment_id in logical_ids if fragment_id not in catalog)
        if missing:
            raise ValueError(f"BookModel references missing fragments: {', '.join(missing)}")

        for key, figure in self.content.figures.items():
            figure_fragment = catalog.get(key)
            if key != figure.fragment_id:
                raise ValueError(f"figure catalog key {key!r} does not match figure fragment ID")
            if figure_fragment is None or figure_fragment.semantic_type is not SemanticType.FIGURE:
                raise ValueError(f"figure {key!r} must correspond to a FIGURE semantic fragment")
            if key not in logical_ids:
                raise ValueError(f"orphan figure entry: {key}")
            if figure.caption_fragment_id is not None:
                caption = catalog.get(figure.caption_fragment_id)
                if caption is None:
                    raise ValueError(f"figure {key!r} references missing caption {figure.caption_fragment_id!r}")
                if caption.semantic_type is not SemanticType.CAPTION:
                    raise ValueError(f"figure {key!r} caption must reference a CAPTION fragment")

        for key, table in self.content.tables.items():
            table_fragment = catalog.get(key)
            if key != table.fragment_id:
                raise ValueError(f"table catalog key {key!r} does not match table fragment ID")
            if table_fragment is None or table_fragment.semantic_type is not SemanticType.TABLE:
                raise ValueError(f"table {key!r} must correspond to a TABLE semantic fragment")
            if key not in logical_ids:
                raise ValueError(f"orphan table entry: {key}")

        for fragment_id in logical_ids:
            fragment = catalog[fragment_id]
            if fragment.semantic_type is SemanticType.FIGURE and fragment_id not in self.content.figures:
                raise ValueError(f"logical FIGURE fragment has no figure entry: {fragment_id}")
            if fragment.semantic_type is SemanticType.TABLE and fragment_id not in self.content.tables:
                raise ValueError(f"logical TABLE fragment has no table entry: {fragment_id}")
        return self

    def _logical_fragment_ids(self) -> set[FragmentId]:
        result = {
            self.metadata.title_fragment_id,
            *self.metadata.author_fragment_ids,
            *self.front_matter.content_fragment_ids,
            *self.back_matter.content_fragment_ids,
        }
        for chapter in self.chapters:
            if chapter.title_fragment_id is not None:
                result.add(chapter.title_fragment_id)
            result.update(chapter.content_fragment_ids)
            self._collect_section_ids(chapter.sections, result)
        return result

    @classmethod
    def _collect_section_ids(cls, sections: list[Section], result: set[FragmentId]) -> None:
        for section in sections:
            if section.title_fragment_id is not None:
                result.add(section.title_fragment_id)
            result.update(section.content_fragment_ids)
            cls._collect_section_ids(section.subsections, result)
