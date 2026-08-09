from __future__ import annotations

import hashlib
import html
import io
import mimetypes
import posixpath
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from bookforge.contracts.artifact import ImmutableEpubArtifact, MetadataSnapshot
from bookforge.contracts.book import BookModel, Chapter, Section
from bookforge.contracts.common import ArtifactId, FragmentId, SourceId
from bookforge.contracts.evidence import EvidenceRegistry, EvidenceRegistryError
from bookforge.contracts.interfaces import AssetResolver
from bookforge.contracts.raw import RawRun
from bookforge.contracts.semantic import (
    RelationshipType,
    SemanticFragment,
    SemanticTable,
    SemanticType,
)
from bookforge.contracts.source import SourceTextReference, TextJoinBehavior
from bookforge.contracts.validation import ValidationStatus

from .errors import (
    EpubPackagingError,
    InvalidBookModelError,
    InvalidInternalReferenceError,
    MissingAssetError,
)
from .validation import StructuralEpubValidator

EPUB_MIMETYPE = b"application/epub+zip"
EPOCH = datetime(1980, 1, 1, tzinfo=timezone.utc)
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
MODIFIED = "1980-01-01T00:00:00Z"

CSS = """body {
  line-height: 1.5;
  margin: 5%;
}
h1, h2, h3, h4, h5, h6 {
  break-after: avoid;
}
img {
  display: block;
  height: auto;
  margin: 1em auto;
  max-width: 100%;
}
figure {
  margin: 1em 0;
}
figcaption {
  font-size: 0.9em;
  text-align: center;
}
table {
  border-collapse: collapse;
  display: block;
  max-width: 100%;
  overflow-x: auto;
}
td, th {
  border: 1px solid currentColor;
  padding: 0.25em 0.5em;
  vertical-align: top;
}
.underline {
  text-decoration: underline;
}
.note, .tip {
  border-inline-start: 0.2em solid currentColor;
  padding-inline-start: 0.8em;
}
"""


@dataclass(frozen=True, slots=True)
class _PackagedAsset:
    reference: str
    internal_path: str
    media_type: str
    data: bytes
    manifest_id: str


class _AssetPackager:
    def __init__(self, resolver: AssetResolver) -> None:
        self._resolver = resolver
        self._assets: dict[str, _PackagedAsset] = {}

    @property
    def assets(self) -> tuple[_PackagedAsset, ...]:
        return tuple(self._assets.values())

    def add(self, reference: str | SourceId) -> _PackagedAsset:
        key = str(reference)
        self._validate_reference(key)
        existing = self._assets.get(key)
        if existing is not None:
            return existing
        try:
            path = self._resolver.resolve(reference)
        except MissingAssetError:
            raise
        except (KeyError, OSError) as error:
            raise MissingAssetError(f"cannot resolve asset: {key}") from error
        if not path.is_file():
            raise MissingAssetError(f"asset is missing or not a file: {path}")
        suffix = path.suffix.lower()
        media_type = mimetypes.guess_type(path.name)[0]
        if media_type is None or not media_type.startswith("image/"):
            raise MissingAssetError(f"unsupported or unknown image media type: {path.name}")
        if not suffix or any(character not in ".abcdefghijklmnopqrstuvwxyz0123456789" for character in suffix):
            raise InvalidInternalReferenceError(f"unsafe image extension: {suffix!r}")
        sequence = len(self._assets) + 1
        packaged = _PackagedAsset(
            reference=key,
            internal_path=f"EPUB/images/image_{sequence:06d}{suffix}",
            media_type=media_type,
            data=path.read_bytes(),
            manifest_id=f"image_{sequence:06d}",
        )
        self._assets[key] = packaged
        return packaged

    @staticmethod
    def _validate_reference(reference: str) -> None:
        normalized = reference.replace("\\", "/")
        pure = PurePosixPath(normalized)
        if not reference or pure.is_absolute() or ".." in pure.parts:
            raise InvalidInternalReferenceError(f"unsafe asset reference: {reference!r}")


class EpubBuilder:
    """BookModel V2-only deterministic reflowable EPUB 3 renderer."""

    def __init__(self) -> None:
        self._structural_validator = StructuralEpubValidator()

    def build(
        self,
        book: BookModel,
        evidence_registry: EvidenceRegistry,
        asset_resolver: AssetResolver,
        output_path: Path,
    ) -> ImmutableEpubArtifact:
        if book.schema_version != 2:
            raise InvalidBookModelError("EPUB builder requires BookModel schema version 2")
        assets = _AssetPackager(asset_resolver)
        renderer = _Renderer(book, evidence_registry, assets)
        cover_asset = assets.add(book.metadata.cover_reference) if book.metadata.cover_reference else None
        documents, spine, nav_entries = renderer.render_documents()
        if cover_asset is not None:
            documents = {"EPUB/text/cover.xhtml": renderer.cover_document(cover_asset), **documents}
            spine = [("cover", "text/cover.xhtml"), *spine]
        package_entries = self._package_entries(book, renderer, assets, documents, spine, nav_entries, cover_asset)
        epub_bytes = self._zip_bytes(package_entries)
        sha256 = hashlib.sha256(epub_bytes).hexdigest()
        artifact_id = ArtifactId(f"epub_{sha256[:16]}")
        validation_id = f"structural_{sha256[:16]}"
        artifact = ImmutableEpubArtifact(
            id=artifact_id,
            relative_path=output_path.name,
            size_bytes=len(epub_bytes),
            sha256=sha256,
            created_at=EPOCH,
            book_model_revision=book.revision,
            metadata_snapshot=MetadataSnapshot(
                title=renderer.title_text,
                authors=tuple(renderer.author_texts),
                language=book.metadata.language,
                identifier=book.metadata.identifier,
                cover_reference=cover_asset.internal_path if cover_asset else None,
                toc_reference="EPUB/nav.xhtml",
            ),
            validation_record_id=validation_id,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(epub_bytes)
        validation = self._structural_validator.validate(artifact, output_path)
        if validation.status is ValidationStatus.FAIL:
            try:
                output_path.unlink()
            except OSError:
                pass
            messages = "; ".join(f"{finding.code}: {finding.message}" for finding in validation.findings)
            raise EpubPackagingError(f"internal structural validation failed: {messages}")
        return artifact

    def _package_entries(
        self,
        book: BookModel,
        renderer: "_Renderer",
        assets: _AssetPackager,
        documents: dict[str, str],
        spine: list[tuple[str, str]],
        nav_entries: list[tuple[str, str, list[tuple[str, str, list[Any]]]]],
        cover_asset: _PackagedAsset | None,
    ) -> list[tuple[str, bytes, int]]:
        container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""
        nav = renderer.navigation_document(nav_entries)
        manifest: list[tuple[str, str, str, str | None]] = [
            ("nav", "nav.xhtml", "application/xhtml+xml", "nav"),
            ("css", "styles.css", "text/css", None),
        ]
        for manifest_id, href in spine:
            manifest.append((manifest_id, href, "application/xhtml+xml", None))
        for asset in assets.assets:
            properties = "cover-image" if cover_asset and asset.reference == cover_asset.reference else None
            manifest.append(
                (asset.manifest_id, asset.internal_path.removeprefix("EPUB/"), asset.media_type, properties)
            )
        package = renderer.package_document(manifest, spine)
        entries: list[tuple[str, bytes, int]] = [
            ("mimetype", EPUB_MIMETYPE, zipfile.ZIP_STORED),
            ("META-INF/container.xml", container.encode("utf-8"), zipfile.ZIP_DEFLATED),
            ("EPUB/package.opf", package.encode("utf-8"), zipfile.ZIP_DEFLATED),
            ("EPUB/nav.xhtml", nav.encode("utf-8"), zipfile.ZIP_DEFLATED),
            ("EPUB/styles.css", CSS.encode("utf-8"), zipfile.ZIP_DEFLATED),
        ]
        entries.extend(
            (path, content.encode("utf-8"), zipfile.ZIP_DEFLATED)
            for path, content in documents.items()
        )
        entries.extend(
            (asset.internal_path, asset.data, zipfile.ZIP_DEFLATED) for asset in assets.assets
        )
        return entries

    @staticmethod
    def _zip_bytes(entries: list[tuple[str, bytes, int]]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as package:
            for name, data, compression in entries:
                info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
                info.compress_type = compression
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                package.writestr(info, data, compress_type=compression, compresslevel=9)
        return buffer.getvalue()


class _Renderer:
    def __init__(self, book: BookModel, registry: EvidenceRegistry, assets: _AssetPackager) -> None:
        self.book = book
        self.registry = registry
        self.assets = assets
        self.title_text = self._plain_fragment(book.metadata.title_fragment_id)
        self.author_texts = [self._plain_fragment(item) for item in book.metadata.author_fragment_ids]

    def render_documents(
        self,
    ) -> tuple[
        dict[str, str],
        list[tuple[str, str]],
        list[tuple[str, str, list[tuple[str, str, list[Any]]]]],
    ]:
        documents: dict[str, str] = {}
        spine: list[tuple[str, str]] = []
        nav_entries: list[tuple[str, str, list[tuple[str, str, list[Any]]]]] = []
        documents["EPUB/text/title.xhtml"] = self._xhtml_document(
            self.title_text,
            "<section epub:type=\"titlepage\">"
            f"<h1>{self._fragment_xhtml(self.book.metadata.title_fragment_id)}</h1>"
            + "".join(
                f'<p class="author">{self._fragment_xhtml(author_id)}</p>'
                for author_id in self.book.metadata.author_fragment_ids
            )
            + "</section>",
        )
        spine.append(("title", "text/title.xhtml"))
        if self.book.front_matter.content_fragment_ids:
            documents["EPUB/text/front_matter.xhtml"] = self._xhtml_document(
                self.title_text,
                '<section epub:type="frontmatter">'
                + self._render_sequence(self.book.front_matter.content_fragment_ids)
                + "</section>",
            )
            spine.append(("front_matter", "text/front_matter.xhtml"))
        for index, chapter in enumerate(self.book.chapters, start=1):
            filename = f"chapter_{index:03d}.xhtml"
            manifest_id = f"chapter_{index:03d}"
            chapter_title = (
                self._plain_fragment(chapter.title_fragment_id)
                if chapter.title_fragment_id is not None
                else self.title_text
            )
            documents[f"EPUB/text/{filename}"] = self._chapter_document(chapter, chapter_title)
            spine.append((manifest_id, f"text/{filename}"))
            if chapter.title_fragment_id is not None:
                section_entries = self._section_nav(chapter.sections, filename)
                nav_entries.append((chapter_title, f"text/{filename}", section_entries))
        if self.book.back_matter.content_fragment_ids:
            documents["EPUB/text/back_matter.xhtml"] = self._xhtml_document(
                self.title_text,
                '<section epub:type="backmatter">'
                + self._render_sequence(self.book.back_matter.content_fragment_ids)
                + "</section>",
            )
            spine.append(("back_matter", "text/back_matter.xhtml"))
        return documents, spine, nav_entries

    def cover_document(self, asset: _PackagedAsset) -> str:
        source = posixpath.relpath(asset.internal_path, "EPUB/text")
        body = (
            '<section epub:type="cover"><figure class="cover">'
            f'<img src="{html.escape(source, quote=True)}" alt=""/>'
            "</figure></section>"
        )
        return self._xhtml_document(self.title_text, body)

    def _chapter_document(self, chapter: Chapter, title: str) -> str:
        body = '<section epub:type="chapter">'
        if chapter.title_fragment_id is not None:
            body += f'<h1 id="{chapter.id}">{self._fragment_xhtml(chapter.title_fragment_id)}</h1>'
        body += self._render_sequence(chapter.content_fragment_ids)
        body += "".join(self._render_section(section, 2) for section in chapter.sections)
        body += "</section>"
        return self._xhtml_document(title, body)

    def _render_section(self, section: Section, level: int) -> str:
        safe_level = min(max(level, 2), 6)
        content = f'<section id="{html.escape(section.id, quote=True)}">'
        if section.title_fragment_id is not None:
            content += f"<h{safe_level}>{self._fragment_xhtml(section.title_fragment_id)}</h{safe_level}>"
        content += self._render_sequence(section.content_fragment_ids)
        content += "".join(self._render_section(child, safe_level + 1) for child in section.subsections)
        return content + "</section>"

    def _render_sequence(self, fragment_ids: list[FragmentId]) -> str:
        linked_captions = {
            figure.caption_fragment_id
            for figure in self.book.content.figures.values()
            if figure.caption_fragment_id is not None
        }
        list_item_ids: set[FragmentId] = set()
        output: list[str] = []
        for fragment_index, fragment_id in enumerate(fragment_ids):
            if fragment_id in linked_captions or fragment_id in list_item_ids:
                continue
            fragment = self.book.content.fragments[fragment_id]
            kind = fragment.semantic_type
            if kind is SemanticType.PARAGRAPH:
                output.append(f"<p>{self._fragment_xhtml(fragment_id)}</p>")
            elif kind in {SemanticType.TITLE, SemanticType.CHAPTER_TITLE}:
                output.append(f"<h1>{self._fragment_xhtml(fragment_id)}</h1>")
            elif kind in {SemanticType.CHAPTER_NUMBER, SemanticType.AUTHOR}:
                output.append(f'<p class="{kind.value}">{self._fragment_xhtml(fragment_id)}</p>')
            elif kind is SemanticType.HEADING:
                output.append(f"<h2>{self._fragment_xhtml(fragment_id)}</h2>")
            elif kind is SemanticType.QUOTE:
                output.append(f"<blockquote>{self._fragment_xhtml(fragment_id)}</blockquote>")
            elif kind in {SemanticType.NOTE, SemanticType.TIP, SemanticType.FOOTNOTE}:
                output.append(
                    f'<aside class="{kind.value}">{self._fragment_xhtml(fragment_id)}</aside>'
                )
            elif kind is SemanticType.LIST:
                items = self._list_items(fragment_id, fragment_ids, fragment_index)
                list_item_ids.update(item.id for item in items)
                tag = "ol" if fragment.metadata.get("ordered") is True else "ul"
                output.append(
                    f"<{tag}>"
                    + "".join(f"<li>{self._fragment_xhtml(item.id)}</li>" for item in items)
                    + f"</{tag}>"
                )
            elif kind is SemanticType.LIST_ITEM:
                raise InvalidBookModelError(f"orphan list item in logical flow: {fragment_id}")
            elif kind is SemanticType.FIGURE:
                caption_id = self.book.content.figures[fragment_id].caption_fragment_id
                if caption_id is not None and (
                    fragment_index + 1 >= len(fragment_ids)
                    or fragment_ids[fragment_index + 1] != caption_id
                ):
                    raise InvalidBookModelError(
                        f"figure caption must immediately follow its figure in logical order: {fragment_id}"
                    )
                output.append(self._render_figure(fragment_id))
            elif kind is SemanticType.CAPTION:
                output.append(f'<p class="caption">{self._fragment_xhtml(fragment_id)}</p>')
            elif kind is SemanticType.TABLE:
                output.append(self._render_table(self.book.content.tables[fragment_id]))
            else:
                raise InvalidBookModelError(f"unsupported logical fragment type: {kind.value}")
        return "".join(output)

    def _list_items(
        self, list_id: FragmentId, logical_ids: list[FragmentId], list_index: int
    ) -> list[SemanticFragment]:
        result: list[SemanticFragment] = []
        for candidate_id in logical_ids[list_index + 1 :]:
            candidate = self.book.content.fragments[candidate_id]
            if candidate.semantic_type is not SemanticType.LIST_ITEM:
                break
            belongs = any(
                relationship.relationship_type is RelationshipType.MEMBER_OF
                and relationship.target_fragment_id == list_id
                for relationship in candidate.relationships
            )
            if not belongs:
                break
            result.append(candidate)
        if not result:
            raise InvalidBookModelError(f"list has no related LIST_ITEM fragments: {list_id}")
        related_ids = {
            candidate_id
            for candidate_id in logical_ids
            if self.book.content.fragments[candidate_id].semantic_type is SemanticType.LIST_ITEM
            and any(
                relationship.relationship_type is RelationshipType.MEMBER_OF
                and relationship.target_fragment_id == list_id
                for relationship in self.book.content.fragments[candidate_id].relationships
            )
        }
        if related_ids != {item.id for item in result}:
            raise InvalidBookModelError(
                f"list items must immediately follow their list in logical order: {list_id}"
            )
        return result

    def _render_figure(self, fragment_id: FragmentId) -> str:
        figure = self.book.content.figures[fragment_id]
        asset = self.assets.add(figure.source_image_id)
        source = posixpath.relpath(asset.internal_path, "EPUB/text")
        fragment = self.book.content.fragments[fragment_id]
        alt_value = fragment.metadata.get("alt_text")
        alt = alt_value if isinstance(alt_value, str) else ""
        result = (
            "<figure>"
            f'<img src="{html.escape(source, quote=True)}" alt="{html.escape(alt, quote=True)}"/>'
        )
        if figure.caption_fragment_id is not None:
            result += f"<figcaption>{self._fragment_xhtml(figure.caption_fragment_id)}</figcaption>"
        return result + "</figure>"

    def _render_table(self, table: SemanticTable) -> str:
        rows: list[str] = []
        for row in table.rows:
            cells: list[str] = []
            for cell in row.cells:
                tag = "th" if cell.is_header is True else "td"
                attributes = ""
                if cell.row_span not in (None, 1):
                    attributes += f' rowspan="{cell.row_span}"'
                if cell.column_span not in (None, 1):
                    attributes += f' colspan="{cell.column_span}"'
                cells.append(f"<{tag}{attributes}>{self._references_xhtml(cell.source_references)}</{tag}>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return '<div class="table-wrap"><table>' + "".join(rows) + "</table></div>"

    def _plain_fragment(self, fragment_id: FragmentId) -> str:
        fragment = self.book.content.fragments[fragment_id]
        return self._resolve_segments(fragment.source_references)[0]

    def _fragment_xhtml(self, fragment_id: FragmentId) -> str:
        fragment = self.book.content.fragments[fragment_id]
        return self._resolve_segments(fragment.source_references)[1]

    def _references_xhtml(self, references: list[SourceTextReference]) -> str:
        return self._resolve_segments(references)[1]

    def _resolve_segments(self, references: list[SourceTextReference]) -> tuple[str, str]:
        if not references:
            return "", ""
        segments: list[tuple[str, str, Any]] = []
        for index, reference in enumerate(references):
            if reference.join_behavior is TextJoinBehavior.DEFER:
                raise InvalidBookModelError(
                    f"unresolved DEFER join reached EPUB builder for source {reference.source_id}"
                )
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
                    previous_separator, previous_text, previous_evidence = segments[-1]
                    if previous_text.endswith(("-", "\u00ad")):
                        segments[-1] = (previous_separator, previous_text[:-1], previous_evidence)
                    else:
                        raise InvalidBookModelError(
                            "REMOVE_TRAILING_HYPHEN requested but previous source segment has no trailing hyphen"
                        )
            segments.append((separator, text, evidence))
        plain = "".join(separator + text for separator, text, _evidence in segments)
        rendered = "".join(
            html.escape(separator).replace("\n", "<br/>") + self._formatted_text(text, evidence)
            for separator, text, evidence in segments
        )
        return plain, rendered

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

    def _section_nav(
        self, sections: list[Section], filename: str
    ) -> list[tuple[str, str, list[tuple[str, str, list[Any]]]]]:
        entries: list[tuple[str, str, list[tuple[str, str, list[Any]]]]] = []
        for section in sections:
            if section.title_fragment_id is None:
                continue
            entries.append(
                (
                    self._plain_fragment(section.title_fragment_id),
                    f"text/{filename}#{section.id}",
                    self._section_nav(section.subsections, filename),
                )
            )
        return entries

    def navigation_document(
        self, entries: list[tuple[str, str, list[tuple[str, str, list[Any]]]]]
    ) -> str:
        def render(items: list[tuple[str, str, list[tuple[str, str, list[Any]]]]]) -> str:
            return "<ol>" + "".join(
                "<li>"
                f'<a href="{html.escape(href, quote=True)}">{html.escape(label)}</a>'
                + (render(children) if children else "")
                + "</li>"
                for label, href, children in items
            ) + "</ol>"

        body = f'<nav epub:type="toc" id="toc"><h1>Contents</h1>{render(entries)}</nav>'
        return self._xhtml_document("Contents", body)

    def package_document(
        self,
        manifest: list[tuple[str, str, str, str | None]],
        spine: list[tuple[str, str]],
    ) -> str:
        metadata = [
            f'<dc:identifier id="book-id">{html.escape(self.book.metadata.identifier)}</dc:identifier>',
            f"<dc:title>{html.escape(self.title_text)}</dc:title>",
            f"<dc:language>{html.escape(self.book.metadata.language)}</dc:language>",
            *[f"<dc:creator>{html.escape(author)}</dc:creator>" for author in self.author_texts],
        ]
        if self.book.metadata.publisher is not None:
            metadata.append(f"<dc:publisher>{html.escape(self.book.metadata.publisher)}</dc:publisher>")
        if self.book.metadata.description is not None:
            metadata.append(f"<dc:description>{html.escape(self.book.metadata.description)}</dc:description>")
        metadata.append(f'<meta property="dcterms:modified">{MODIFIED}</meta>')
        manifest_xml = "".join(
            f'<item id="{item_id}" href="{html.escape(href, quote=True)}" media-type="{media_type}"'
            + (f' properties="{properties}"' if properties else "")
            + "/>"
            for item_id, href, media_type, properties in manifest
        )
        spine_xml = "".join(f'<itemref idref="{item_id}"/>' for item_id, _href in spine)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" '
            'xml:lang="' + html.escape(self.book.metadata.language, quote=True) + '">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            + "".join(metadata)
            + "</metadata><manifest>"
            + manifest_xml
            + "</manifest><spine>"
            + spine_xml
            + "</spine></package>"
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
