"""Native deterministic Contracts V3 EPUB renderer."""

from __future__ import annotations

import hashlib
import html
import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bookforge.contracts.artifact import ImmutableEpubArtifact, MetadataSnapshot
from bookforge.contracts.assembly import (
    BookModelV3,
    ChapterV3,
    FigureSemanticNode,
    PartV3,
    SectionV3,
    TableDataV3,
    TableSemanticNode,
    TextSemanticNode,
    UnsupportedSemanticNode,
)
from bookforge.contracts.common import ArtifactId, FragmentId
from bookforge.contracts.evidence import EvidenceRegistry, EvidenceRegistryError
from bookforge.contracts.flow import (
    ContinuityType,
    LogicalBreakIntent,
    LogicalListId,
    LogicalListKind,
    LogicalListV3,
)
from bookforge.contracts.interfaces import AssetResolver
from bookforge.contracts.raw import RawRun
from bookforge.contracts.semantic import SemanticType
from bookforge.contracts.source import SourceTextReference, TextJoinBehavior
from bookforge.contracts.validation import ValidationStatus

from .builder import CSS, EPOCH, EPUB_MIMETYPE, MODIFIED, _AssetPackager, EpubBuilder
from .errors import (
    EpubPackagingError,
    InvalidBookModelError,
    InvalidContinuityError,
    UnsupportedV3ContentError,
)
from .validation import StructuralEpubValidator

V3_CSS = CSS + """.logical-break-page {
  break-before: page;
  page-break-before: always;
}
"""


@dataclass(slots=True)
class _Segment:
    number: int
    blocks: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return f"segment_{self.number:03d}.xhtml"

    @property
    def manifest_id(self) -> str:
        return f"segment_{self.number:03d}"


@dataclass(frozen=True, slots=True)
class _NavEntry:
    label: str
    anchor: str
    children: tuple["_NavEntry", ...] = ()


@dataclass(slots=True)
class _TextChunk:
    separator: str
    text: str
    evidence: Any


class EpubV3Builder:
    """Render BookModelV3 directly; historical ``EpubBuilder`` remains V2-only."""

    def __init__(self) -> None:
        self._structural_validator = StructuralEpubValidator()

    def build(
        self,
        book: BookModelV3,
        evidence_registry: EvidenceRegistry,
        asset_resolver: AssetResolver,
        output_path: Path,
    ) -> ImmutableEpubArtifact:
        if book.schema_version != 3:
            raise InvalidBookModelError("V3 EPUB builder requires BookModelV3 schema version 3")
        assets = _AssetPackager(asset_resolver)
        renderer = _V3Renderer(book, evidence_registry, assets)
        cover_asset = assets.add(book.metadata.cover_reference) if book.metadata.cover_reference else None
        documents, spine, nav_entries = renderer.render_documents()
        if cover_asset is not None:
            documents = {"EPUB/text/cover.xhtml": renderer.cover_document(cover_asset), **documents}
            spine = [("cover", "text/cover.xhtml"), *spine]
        entries = self._package_entries(renderer, assets, documents, spine, nav_entries, cover_asset)
        epub_bytes = EpubBuilder._zip_bytes(entries)
        sha256 = hashlib.sha256(epub_bytes).hexdigest()
        artifact = ImmutableEpubArtifact(
            id=ArtifactId(f"epub_{sha256[:16]}"),
            relative_path=output_path.name,
            size_bytes=len(epub_bytes),
            sha256=sha256,
            created_at=EPOCH,
            book_model_revision=book.revision,
            metadata_snapshot=MetadataSnapshot(
                title=renderer.title_text,
                authors=renderer.author_texts,
                language=book.metadata.language,
                identifier=book.metadata.identifier,
                cover_reference=cover_asset.internal_path if cover_asset else None,
                toc_reference="EPUB/nav.xhtml",
            ),
            validation_record_id=f"structural_{sha256[:16]}",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(epub_bytes)
        validation = self._structural_validator.validate(artifact, output_path)
        if validation.status is ValidationStatus.FAIL:
            output_path.unlink(missing_ok=True)
            messages = "; ".join(f"{item.code}: {item.message}" for item in validation.findings)
            raise EpubPackagingError(f"internal structural validation failed: {messages}")
        return artifact

    @staticmethod
    def _package_entries(
        renderer: "_V3Renderer",
        assets: _AssetPackager,
        documents: dict[str, str],
        spine: list[tuple[str, str]],
        nav_entries: tuple[_NavEntry, ...],
        cover_asset: Any | None,
    ) -> list[tuple[str, bytes, int]]:
        container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""
        manifest: list[tuple[str, str, str, str | None]] = [
            ("nav", "nav.xhtml", "application/xhtml+xml", "nav"),
            ("css", "styles.css", "text/css", None),
        ]
        manifest.extend((item_id, href, "application/xhtml+xml", None) for item_id, href in spine)
        for asset in assets.assets:
            properties = "cover-image" if cover_asset and asset.reference == cover_asset.reference else None
            manifest.append((asset.manifest_id, asset.internal_path.removeprefix("EPUB/"), asset.media_type, properties))
        entries: list[tuple[str, bytes, int]] = [
            ("mimetype", EPUB_MIMETYPE, zipfile.ZIP_STORED),
            ("META-INF/container.xml", container.encode(), zipfile.ZIP_DEFLATED),
            ("EPUB/package.opf", renderer.package_document(manifest, spine).encode(), zipfile.ZIP_DEFLATED),
            ("EPUB/nav.xhtml", renderer.navigation_document(nav_entries).encode(), zipfile.ZIP_DEFLATED),
            ("EPUB/styles.css", V3_CSS.encode(), zipfile.ZIP_DEFLATED),
        ]
        entries.extend((path, value.encode(), zipfile.ZIP_DEFLATED) for path, value in documents.items())
        entries.extend((asset.internal_path, asset.data, zipfile.ZIP_DEFLATED) for asset in assets.assets)
        return entries


class _V3Renderer:
    def __init__(self, book: BookModelV3, registry: EvidenceRegistry, assets: _AssetPackager) -> None:
        self.book = book
        self.registry = registry
        self.assets = assets
        self.title_text = self._plain_node(book.metadata.title_fragment_id)
        self.author_texts = tuple(self._plain_node(item) for item in book.metadata.author_fragment_ids)
        self._continuity = {edge.left_node_id: edge for edge in book.continuity}
        self._lists = {item.list_id: item for item in book.logical_lists}
        self._member_list = {
            member_id: logical_list.list_id
            for logical_list in book.logical_lists
            for member_id in logical_list.member_fragment_ids
        }
        self._segment_list = {
            segment_id: logical_list.list_id
            for logical_list in book.logical_lists
            for segment_id in logical_list.source_segment_fragment_ids
        }
        children: dict[FragmentId, list[LogicalListId]] = {}
        for logical_list in book.logical_lists:
            if logical_list.parent_item_fragment_id is not None:
                children.setdefault(logical_list.parent_item_fragment_id, []).append(logical_list.list_id)
        self._child_lists = {key: tuple(value) for key, value in children.items()}
        self._rendered_lists: set[LogicalListId] = set()
        self._caption_figures = {
            node.figure.caption_fragment_id: node
            for node in book.content.nodes.values()
            if isinstance(node, FigureSemanticNode) and node.figure.caption_fragment_id is not None
        }
        self._validate_continuity()
        self._segments: list[_Segment] = []
        self._anchor_resources: dict[str, str] = {}

    def _validate_continuity(self) -> None:
        incoming: set[FragmentId] = set()
        for edge in self.book.continuity:
            if edge.operation in {
                ContinuityType.JOIN_DIRECT,
                ContinuityType.JOIN_WITH_SPACE,
                ContinuityType.JOIN_WITH_NEWLINE,
                ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN,
            } and (edge.left_node_id in self._member_list or edge.right_node_id in self._member_list):
                raise InvalidContinuityError(
                    "text continuity cannot combine distinct one-fragment logical list items"
                )
            if edge.operation is not ContinuityType.KEEP_SEPARATE and edge.right_node_id in incoming:
                raise InvalidContinuityError("continuity node has multiple incoming joining edges")
            if edge.operation is not ContinuityType.KEEP_SEPARATE:
                incoming.add(edge.right_node_id)
        for start in self._continuity:
            seen: set[FragmentId] = set()
            current = start
            while current in self._continuity:
                if current in seen:
                    raise InvalidContinuityError("continuity graph contains a cycle")
                seen.add(current)
                current = self._continuity[current].right_node_id
        positions = {item: index for index, item in enumerate(self._ordered_fragment_ids())}
        for logical_list in self.book.logical_lists:
            if logical_list.parent_list_id is None:
                continue
            assert logical_list.parent_item_fragment_id is not None
            parent = self._lists.get(logical_list.parent_list_id)
            if parent is None:
                raise InvalidBookModelError("nested list references a missing parent")
            parent_position = positions[logical_list.parent_item_fragment_id]
            child_positions = [positions[item] for item in logical_list.member_fragment_ids]
            if any(item <= parent_position for item in child_positions):
                raise InvalidBookModelError("nested list members must follow their explicit parent item")
            parent_index = parent.member_fragment_ids.index(logical_list.parent_item_fragment_id)
            if parent_index + 1 < len(parent.member_fragment_ids):
                next_position = positions[parent.member_fragment_ids[parent_index + 1]]
                if any(item >= next_position for item in child_positions):
                    raise InvalidBookModelError("nested list members must remain inside their parent item")

    def _ordered_fragment_ids(self) -> tuple[FragmentId, ...]:
        result: list[FragmentId] = list(self.book.front_matter.content_fragment_ids)

        def add_section(section: SectionV3) -> None:
            result.extend(section.opening_fragment_ids)
            result.extend(section.content_fragment_ids)
            for child in section.subsections:
                add_section(child)

        def add_chapter(chapter: ChapterV3) -> None:
            result.extend(chapter.opening_fragment_ids)
            result.extend(chapter.content_fragment_ids)
            for section in chapter.sections:
                add_section(section)

        for entry in self.book.body:
            if isinstance(entry, PartV3):
                result.extend(entry.opening_fragment_ids)
                result.extend(entry.content_fragment_ids)
                for chapter in entry.chapters:
                    add_chapter(chapter)
            else:
                add_chapter(entry)
        result.extend(self.book.back_matter.content_fragment_ids)
        return tuple(result)

    def render_documents(self) -> tuple[dict[str, str], list[tuple[str, str]], tuple[_NavEntry, ...]]:
        nav: list[_NavEntry] = []
        if self.book.front_matter.content_fragment_ids:
            self._component("front-matter", self.book.front_matter.content_fragment_ids, LogicalBreakIntent.NONE)
        for entry in self.book.body:
            if isinstance(entry, PartV3):
                part_label = self._label(entry.opening_fragment_ids, {SemanticType.PART_TITLE})
                part_anchor = self._safe_id(entry.id)
                if entry.opening_fragment_ids or entry.content_fragment_ids:
                    self._component(part_anchor, (*entry.opening_fragment_ids, *entry.content_fragment_ids), entry.break_intent)
                else:
                    self._ensure_break(entry.break_intent)
                chapter_results = tuple(self._render_chapter(chapter) for chapter in entry.chapters)
                chapter_nav: tuple[_NavEntry, ...] = tuple(
                    item for item in chapter_results if item is not None
                )
                if part_label is not None:
                    nav.append(_NavEntry(part_label, part_anchor, chapter_nav))
                else:
                    nav.extend(chapter_nav)
            else:
                item = self._render_chapter(entry)
                if item is not None:
                    nav.append(item)
        if self.book.back_matter.content_fragment_ids:
            self._component("back-matter", self.book.back_matter.content_fragment_ids, LogicalBreakIntent.NONE)
        if not self._segments:
            raise InvalidBookModelError("BookModelV3 has no renderable logical reading content")
        documents = {
            f"EPUB/text/{segment.filename}": self._xhtml_document(self.title_text, "".join(segment.blocks))
            for segment in self._segments
        }
        spine = [(segment.manifest_id, f"text/{segment.filename}") for segment in self._segments]
        return documents, spine, tuple(nav)

    def _render_chapter(self, chapter: ChapterV3) -> _NavEntry | None:
        anchor = self._safe_id(chapter.id)
        self._component(anchor, (*chapter.opening_fragment_ids, *chapter.content_fragment_ids), chapter.break_intent)
        section_nav = tuple(self._render_section(item, 2) for item in chapter.sections)
        label = self._label(
            chapter.opening_fragment_ids,
            {SemanticType.CHAPTER_HEADING, SemanticType.CHAPTER_NUMBER, SemanticType.CHAPTER_TITLE},
        )
        return _NavEntry(label, anchor, section_nav) if label is not None else None

    def _render_section(self, section: SectionV3, level: int) -> _NavEntry:
        anchor = self._safe_id(section.id)
        self._component(anchor, (*section.opening_fragment_ids, *section.content_fragment_ids), section.break_intent, level)
        children = tuple(self._render_section(item, level + 1) for item in section.subsections)
        label = self._label(
            section.opening_fragment_ids,
            {SemanticType.SECTION_HEADING, SemanticType.SUBSECTION_HEADING, SemanticType.HEADING},
        )
        return _NavEntry(label, anchor, children) if label is not None else _NavEntry("", anchor, children)

    def _ensure_break(self, intent: LogicalBreakIntent) -> None:
        if intent is LogicalBreakIntent.NEW_PAGE and self._segments and self._segments[-1].blocks:
            self._segments.append(_Segment(len(self._segments) + 1))

    def _component(
        self,
        anchor: str,
        fragment_ids: tuple[FragmentId, ...],
        intent: LogicalBreakIntent,
        heading_level: int = 1,
    ) -> None:
        if not fragment_ids:
            self._ensure_break(intent)
            return
        if not self._segments:
            self._segments.append(_Segment(1))
        elif intent is LogicalBreakIntent.NEW_PAGE and self._segments[-1].blocks:
            self._segments.append(_Segment(len(self._segments) + 1))
        segment = self._segments[-1]
        css = ' class="logical-break-page"' if intent is LogicalBreakIntent.NEW_PAGE else ""
        body = self._render_sequence(fragment_ids, heading_level)
        segment.blocks.append(f'<section id="{html.escape(anchor, quote=True)}"{css}>{body}</section>')
        self._anchor_resources[anchor] = segment.filename

    def _render_sequence(self, ids: tuple[FragmentId, ...], heading_level: int) -> str:
        output: list[str] = []
        index = 0
        while index < len(ids):
            fragment_id = ids[index]
            list_id = self._member_list.get(fragment_id) or self._segment_list.get(fragment_id)
            if list_id is not None:
                root_id = self._root_list_id(list_id)
                if root_id not in self._rendered_lists:
                    output.append(self._render_list(root_id, set()))
                index += 1
                continue
            node = self.book.content.nodes[fragment_id]
            if isinstance(node, UnsupportedSemanticNode):
                raise UnsupportedV3ContentError(f"unsupported node reached renderer: {fragment_id}")
            if isinstance(node, TextSemanticNode):
                if node.semantic_type in {SemanticType.LIST, SemanticType.LIST_ITEM}:
                    raise UnsupportedV3ContentError("Contracts V3 list nodes lack deterministic list structure")
                caption_figure = self._figure_for_caption(fragment_id)
                if caption_figure is not None:
                    if index + 1 >= len(ids) or ids[index + 1] != caption_figure.id:
                        raise InvalidBookModelError("caption-before-figure must be adjacent in logical order")
                    output.append(self._render_figure(caption_figure, fragment_id, caption_first=True))
                    index += 2
                    continue
                group = [fragment_id]
                while group[-1] in self._continuity:
                    edge = self._continuity[group[-1]]
                    if edge.operation not in {
                        ContinuityType.JOIN_DIRECT,
                        ContinuityType.JOIN_WITH_SPACE,
                        ContinuityType.JOIN_WITH_NEWLINE,
                        ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN,
                    }:
                        break
                    if index + len(group) >= len(ids) or ids[index + len(group)] != edge.right_node_id:
                        raise InvalidContinuityError("text continuity contradicts local logical order")
                    right = self.book.content.nodes[edge.right_node_id]
                    if not isinstance(right, TextSemanticNode) or right.semantic_type != node.semantic_type:
                        raise InvalidContinuityError("joined text nodes require one semantic block type")
                    group.append(edge.right_node_id)
                output.append(self._render_text_group(tuple(group), heading_level))
                index += len(group)
                continue
            if isinstance(node, FigureSemanticNode):
                caption_id = node.figure.caption_fragment_id
                if caption_id is not None:
                    if index + 1 >= len(ids) or ids[index + 1] != caption_id:
                        raise InvalidBookModelError("figure/caption must be adjacent in accepted logical order")
                    output.append(self._render_figure(node, caption_id, caption_first=False))
                    index += 2
                else:
                    output.append(self._render_figure(node, None, caption_first=False))
                    index += 1
                continue
            if isinstance(node, TableSemanticNode):
                tables = [node.table]
                while tables[-1].fragment_id in self._continuity:
                    edge = self._continuity[tables[-1].fragment_id]
                    if edge.operation is not ContinuityType.CONTINUE_TABLE:
                        break
                    if index + len(tables) >= len(ids) or ids[index + len(tables)] != edge.right_node_id:
                        raise InvalidContinuityError("table continuity contradicts local logical order")
                    right = self.book.content.nodes[edge.right_node_id]
                    if not isinstance(right, TableSemanticNode):
                        raise InvalidContinuityError("CONTINUE_TABLE target is not a table")
                    tables.append(right.table)
                output.append(self._render_tables(tuple(tables)))
                index += len(tables)
                continue
            raise UnsupportedV3ContentError(f"unknown V3 node family: {fragment_id}")
        return "".join(output)

    def _root_list_id(self, list_id: LogicalListId) -> LogicalListId:
        seen: set[LogicalListId] = set()
        current = self._lists[list_id]
        while current.parent_list_id is not None:
            if current.list_id in seen:
                raise InvalidBookModelError("logical list nesting cycle reached renderer")
            seen.add(current.list_id)
            current = self._lists[current.parent_list_id]
        return current.list_id

    def _render_list(self, list_id: LogicalListId, stack: set[LogicalListId]) -> str:
        if list_id in stack:
            raise InvalidBookModelError("logical list nesting cycle reached renderer")
        logical_list = self._lists.get(list_id)
        if logical_list is None:
            raise InvalidBookModelError(f"logical list is missing: {list_id}")
        stack.add(list_id)
        tag = "ol" if logical_list.kind is LogicalListKind.ORDERED else "ul"
        start = (
            f' start="{logical_list.start_value}"'
            if logical_list.kind is LogicalListKind.ORDERED and logical_list.start_value is not None
            else ""
        )
        items: list[str] = []
        for member_id in logical_list.member_fragment_ids:
            node = self.book.content.nodes.get(member_id)
            if not isinstance(node, TextSemanticNode) or node.semantic_type is not SemanticType.LIST_ITEM:
                raise UnsupportedV3ContentError("logical list member is not a LIST_ITEM text node")
            item = self._references_xhtml(node.source_references)
            item += "".join(self._render_list(child_id, stack) for child_id in self._child_lists.get(member_id, ()))
            items.append(f"<li>{item}</li>")
        stack.remove(list_id)
        self._rendered_lists.add(list_id)
        self._rendered_lists.update(self._descendant_list_ids(list_id))
        return f"<{tag}{start}>" + "".join(items) + f"</{tag}>"

    def _descendant_list_ids(self, list_id: LogicalListId) -> set[LogicalListId]:
        descendants: set[LogicalListId] = set()
        pending = [list_id]
        while pending:
            parent_id = pending.pop()
            parent = self._lists[parent_id]
            for member_id in parent.member_fragment_ids:
                for child_id in self._child_lists.get(member_id, ()):
                    if child_id not in descendants:
                        descendants.add(child_id)
                        pending.append(child_id)
        return descendants

    def _render_text_group(self, ids: tuple[FragmentId, ...], level: int) -> str:
        first = self.book.content.nodes[ids[0]]
        assert isinstance(first, TextSemanticNode)
        chunks: list[_TextChunk] = []
        for node_index, fragment_id in enumerate(ids):
            node = self.book.content.nodes[fragment_id]
            assert isinstance(node, TextSemanticNode)
            if node_index:
                operation = self._continuity[ids[node_index - 1]].operation
                self._apply_join(chunks, operation)
            self._append_references(chunks, node.source_references, preserve_first_separator=node_index > 0)
        rendered = "".join(
            html.escape(chunk.separator).replace("\n", "<br/>") + self._formatted_text(chunk.text, chunk.evidence)
            for chunk in chunks
        )
        kind = first.semantic_type
        if kind in {
            SemanticType.BOOK_TITLE, SemanticType.TITLE, SemanticType.PART_TITLE,
            SemanticType.CHAPTER_HEADING, SemanticType.CHAPTER_NUMBER, SemanticType.CHAPTER_TITLE,
        }:
            tag = f"h{min(max(level, 1), 6)}"
            return f"<{tag}>{rendered}</{tag}>"
        if kind in {SemanticType.SECTION_HEADING, SemanticType.SUBSECTION_HEADING, SemanticType.HEADING}:
            tag = f"h{min(max(level, 2), 6)}"
            return f"<{tag}>{rendered}</{tag}>"
        if kind is SemanticType.QUOTE:
            return f"<blockquote>{rendered}</blockquote>"
        if kind in {SemanticType.NOTE, SemanticType.TIP, SemanticType.FOOTNOTE}:
            return f'<aside class="{kind.value}">{rendered}</aside>'
        if kind is SemanticType.CAPTION:
            return f'<p class="caption">{rendered}</p>'
        if kind in {
            SemanticType.PARAGRAPH, SemanticType.AUTHOR, SemanticType.SUBTITLE,
            SemanticType.FRONT_MATTER_TITLE, SemanticType.FRONT_MATTER_TEXT,
        }:
            return f"<p>{rendered}</p>"
        raise UnsupportedV3ContentError(f"text semantic type is not renderable: {kind.value}")

    def _append_references(
        self, chunks: list[_TextChunk], references: tuple[SourceTextReference, ...], *, preserve_first_separator: bool
    ) -> None:
        for index, reference in enumerate(references):
            try:
                evidence = self.registry.get(reference.source_id)
                text = self.registry.resolve_text(reference)
            except EvidenceRegistryError as error:
                raise InvalidBookModelError(str(error)) from error
            separator = ""
            if index > 0:
                if reference.join_behavior is TextJoinBehavior.SPACE:
                    separator = " "
                elif reference.join_behavior is TextJoinBehavior.NEWLINE:
                    separator = "\n"
                elif reference.join_behavior is TextJoinBehavior.REMOVE_TRAILING_HYPHEN:
                    self._remove_trailing_hyphen(chunks)
                elif reference.join_behavior is TextJoinBehavior.DEFER:
                    raise InvalidContinuityError("unresolved source-reference DEFER reached renderer")
            chunks.append(_TextChunk(separator, text, evidence))

    def _apply_join(self, chunks: list[_TextChunk], operation: ContinuityType) -> None:
        if operation is ContinuityType.JOIN_WITH_SPACE:
            chunks.append(_TextChunk(" ", "", None))
        elif operation is ContinuityType.JOIN_WITH_NEWLINE:
            chunks.append(_TextChunk("\n", "", None))
        elif operation is ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN:
            self._remove_trailing_hyphen(chunks)
        elif operation is not ContinuityType.JOIN_DIRECT:
            raise InvalidContinuityError(f"invalid text join operation: {operation.value}")

    @staticmethod
    def _remove_trailing_hyphen(chunks: list[_TextChunk]) -> None:
        for chunk in reversed(chunks):
            if chunk.text:
                if not chunk.text.endswith(("-", "\u00ad")):
                    raise InvalidContinuityError("REMOVE_TRAILING_HYPHEN requires an actual trailing hyphen")
                chunk.text = chunk.text[:-1]
                return
        raise InvalidContinuityError("REMOVE_TRAILING_HYPHEN has no preceding text")

    @staticmethod
    def _formatted_text(text: str, evidence: Any) -> str:
        rendered = html.escape(text).replace("\n", "<br/>")
        if not isinstance(evidence, RawRun):
            return rendered
        if evidence.bold is True:
            rendered = f"<strong>{rendered}</strong>"
        if evidence.italic is True:
            rendered = f"<em>{rendered}</em>"
        if evidence.superscript is True:
            rendered = f"<sup>{rendered}</sup>"
        if evidence.subscript is True:
            rendered = f"<sub>{rendered}</sub>"
        if evidence.underline is True:
            rendered = f'<span class="underline">{rendered}</span>'
        return rendered

    def _render_figure(
        self, node: FigureSemanticNode, caption_id: FragmentId | None, *, caption_first: bool
    ) -> str:
        image_evidence = next(
            item for item in node.evidence
            if item.source_id == node.figure.source_image_id and item.asset_reference is not None
        )
        assert image_evidence.asset_reference is not None
        asset = self.assets.add(image_evidence.asset_reference)
        source = posixpath.relpath(asset.internal_path, "EPUB/text")
        image = f'<img src="{html.escape(source, quote=True)}" alt=""/>'
        caption = f"<figcaption>{self._text_node_xhtml(caption_id)}</figcaption>" if caption_id else ""
        return "<figure>" + (caption + image if caption_first else image + caption) + "</figure>"

    def _figure_for_caption(self, caption_id: FragmentId) -> FigureSemanticNode | None:
        return self._caption_figures.get(caption_id)

    def _render_tables(self, tables: tuple[TableDataV3, ...]) -> str:
        widths = {
            max((cell.column_index + (cell.column_span or 1) for row in table.rows for cell in row.cells), default=0)
            for table in tables
        }
        if len(widths) > 1:
            raise InvalidContinuityError("continued tables have incompatible explicit column extents")
        rows: list[str] = []
        for table in tables:
            for row in table.rows:
                cells: list[str] = []
                for cell in row.cells:
                    tag = "th" if cell.is_header is True else "td"
                    attrs = ""
                    if cell.row_span not in (None, 1):
                        attrs += f' rowspan="{cell.row_span}"'
                    if cell.column_span not in (None, 1):
                        attrs += f' colspan="{cell.column_span}"'
                    cells.append(f"<{tag}{attrs}>{self._references_xhtml(cell.source_references)}</{tag}>")
                rows.append("<tr>" + "".join(cells) + "</tr>")
        return '<div class="table-wrap"><table>' + "".join(rows) + "</table></div>"

    def _references_xhtml(self, references: tuple[SourceTextReference, ...]) -> str:
        chunks: list[_TextChunk] = []
        self._append_references(chunks, references, preserve_first_separator=False)
        return "".join(
            html.escape(chunk.separator).replace("\n", "<br/>") + self._formatted_text(chunk.text, chunk.evidence)
            for chunk in chunks
        )

    def _text_node_xhtml(self, fragment_id: FragmentId) -> str:
        node = self.book.content.nodes[fragment_id]
        if not isinstance(node, TextSemanticNode):
            raise InvalidBookModelError("caption/title reference is not a text node")
        return self._references_xhtml(node.source_references)

    def _plain_node(self, fragment_id: FragmentId) -> str:
        node = self.book.content.nodes[fragment_id]
        if not isinstance(node, TextSemanticNode):
            raise InvalidBookModelError("metadata text reference is not a text node")
        try:
            return "".join(self.registry.resolve_text(item) for item in node.source_references)
        except EvidenceRegistryError as error:
            raise InvalidBookModelError(str(error)) from error

    def _label(self, ids: tuple[FragmentId, ...], kinds: set[SemanticType]) -> str | None:
        for fragment_id in ids:
            node = self.book.content.nodes[fragment_id]
            if isinstance(node, TextSemanticNode) and node.semantic_type in kinds:
                return self._plain_node(fragment_id)
        return None

    @staticmethod
    def _safe_id(value: str) -> str:
        return "bf-" + "".join(character if character.isalnum() else "-" for character in value)

    def navigation_document(self, entries: tuple[_NavEntry, ...]) -> str:
        def render(items: tuple[_NavEntry, ...]) -> str:
            visible = tuple(item for item in items if item.label)
            return "<ol>" + "".join(
                "<li>" + f'<a href="{html.escape(self._nav_href(item), quote=True)}">{html.escape(item.label)}</a>'
                + (render(item.children) if item.children else "") + "</li>"
                for item in visible
            ) + "</ol>"
        return self._xhtml_document("Contents", f'<nav epub:type="toc" id="toc"><h1>Contents</h1>{render(entries)}</nav>')

    def _nav_href(self, entry: _NavEntry) -> str:
        filename = self._anchor_resources.get(entry.anchor)
        if filename is None:
            if entry.children:
                return self._nav_href(entry.children[0])
            raise InvalidBookModelError(f"navigation target has no resource: {entry.anchor}")
        return f"text/{filename}#{entry.anchor}"

    def package_document(
        self, manifest: list[tuple[str, str, str, str | None]], spine: list[tuple[str, str]]
    ) -> str:
        metadata = [
            f'<dc:identifier id="book-id">{html.escape(self.book.metadata.identifier)}</dc:identifier>',
            f"<dc:title>{html.escape(self.title_text)}</dc:title>",
            f"<dc:language>{html.escape(self.book.metadata.language)}</dc:language>",
            *(f"<dc:creator>{html.escape(author)}</dc:creator>" for author in self.author_texts),
        ]
        if self.book.metadata.publisher is not None:
            metadata.append(f"<dc:publisher>{html.escape(self.book.metadata.publisher)}</dc:publisher>")
        if self.book.metadata.description is not None:
            metadata.append(f"<dc:description>{html.escape(self.book.metadata.description)}</dc:description>")
        metadata.append(f'<meta property="dcterms:modified">{MODIFIED}</meta>')
        manifest_xml = "".join(
            f'<item id="{item_id}" href="{html.escape(href, quote=True)}" media-type="{media_type}"'
            + (f' properties="{properties}"' if properties else "") + "/>"
            for item_id, href, media_type, properties in manifest
        )
        spine_xml = "".join(f'<itemref idref="{item_id}"/>' for item_id, _ in spine)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" '
            f'xml:lang="{html.escape(self.book.metadata.language, quote=True)}">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">' + "".join(metadata)
            + "</metadata><manifest>" + manifest_xml + "</manifest><spine>" + spine_xml
            + "</spine></package>"
        )

    def cover_document(self, asset: Any) -> str:
        source = posixpath.relpath(asset.internal_path, "EPUB/text")
        return self._xhtml_document(
            self.title_text,
            '<section epub:type="cover"><figure class="cover">'
            f'<img src="{html.escape(source, quote=True)}" alt=""/></figure></section>',
        )

    def _xhtml_document(self, title: str, body: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" '
            f'xml:lang="{html.escape(self.book.metadata.language, quote=True)}">'
            f"<head><title>{html.escape(title)}</title>"
            '<link rel="stylesheet" type="text/css" href="../styles.css"/></head>'
            f"<body>{body}</body></html>"
        )
