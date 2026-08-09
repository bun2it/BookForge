from __future__ import annotations

import hashlib
import json
import mimetypes
import posixpath
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, cast

from lxml import etree

from bookforge.contracts.common import DocumentId, ProcessingProvenance, SourceId, SourceType, TransformationStage
from bookforge.contracts.evidence import EvidenceRegistry
from bookforge.contracts.ids import (
    SourceObjectKind,
    document_id,
    docx_object_id,
    run_id,
    table_cell_id,
    table_row_id,
)
from bookforge.contracts.raw import (
    RawDocument,
    RawDrawing,
    RawImage,
    RawObject,
    RawParagraph,
    RawRun,
    RawStyle,
    RawTable,
    RawTableCell,
    RawTableRow,
)

from .errors import InvalidDocxError, MissingDocumentPartError
from .models import DocxExtractionResult, DocxExtractionWarning, ExtractedAsset

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
NS = {"w": W, "r": R, "a": A, "wp": WP, "pr": PR, "ct": CT}
DOCUMENT_PART = "word/document.xml"
DOCUMENT_RELS = "word/_rels/document.xml.rels"
CONTENT_TYPES = "[Content_Types].xml"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _qn(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


class _Counters:
    def __init__(self) -> None:
        self.paragraph = 0
        self.table = 0
        self.image = 0
        self.drawing = 0
        self.object_order = 0

    def next_paragraph(self) -> int:
        self.paragraph += 1
        return self.paragraph

    def next_table(self) -> int:
        self.table += 1
        return self.table

    def next_image(self) -> int:
        self.image += 1
        return self.image

    def next_drawing(self) -> int:
        self.drawing += 1
        return self.drawing

    def next_object_order(self) -> int:
        self.object_order += 1
        return self.object_order


class DocxExtractor:
    """Deterministically extracts DOCX source evidence without semantics."""

    def extract(self, path: Path | str, output_dir: Path | str) -> DocxExtractionResult:
        source_path = Path(path)
        target_root = Path(output_dir)
        try:
            source_bytes = source_path.read_bytes()
        except OSError as error:
            raise InvalidDocxError(f"cannot read DOCX source: {source_path}") from error
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        doc_id = document_id(source_sha256)
        workspace = target_root / doc_id
        assets_dir = workspace / "assets"

        try:
            package = zipfile.ZipFile(source_path)
        except (OSError, zipfile.BadZipFile) as error:
            raise InvalidDocxError("input is not a valid DOCX ZIP package") from error

        with package:
            names = set(package.namelist())
            if DOCUMENT_PART not in names:
                raise MissingDocumentPartError(f"missing required part: {DOCUMENT_PART}")
            try:
                document_root = self._parse_xml(self._read_part(package, DOCUMENT_PART), DOCUMENT_PART)
                relationships = self._relationships(package, DOCUMENT_RELS)
                content_types = self._content_types(package)
            except KeyError as error:
                raise MissingDocumentPartError(f"missing required DOCX part: {error.args[0]}") from error

            registry = EvidenceRegistry()
            warnings: list[DocxExtractionWarning] = []
            assets: list[ExtractedAsset] = []
            objects: list[RawObject] = []
            counters = _Counters()
            assets_dir.mkdir(parents=True, exist_ok=True)

            body = document_root.find("w:body", NS)
            if body is None:
                raise InvalidDocxError("word/document.xml has no w:body")
            self._extract_story(
                package,
                body,
                DOCUMENT_PART,
                "body",
                doc_id,
                relationships,
                content_types,
                assets_dir,
                counters,
                objects,
                registry,
                assets,
                warnings,
            )
            self._extract_headers_and_footers(
                package,
                document_root,
                doc_id,
                relationships,
                content_types,
                assets_dir,
                counters,
                objects,
                registry,
                assets,
                warnings,
            )

        provenance = ProcessingProvenance(
            document_id=DocumentId(doc_id),
            source_ids=[],
            stage=TransformationStage.EXTRACTION,
            processor="bookforge.docx",
            processor_version="1",
            created_at=EPOCH,
            metadata={"source_sha256": source_sha256},
        )
        raw_document = RawDocument(
            id=doc_id,
            source_type=SourceType.DOCX,
            original_name=source_path.name,
            objects=tuple(objects),
            provenance=provenance,
            source_metadata={
                "main_part": DOCUMENT_PART,
                "body_order_source": "direct w:body child order",
                "header_footer_order": "first relationship appearance in section properties",
            },
        )
        result = DocxExtractionResult(
            raw_document=raw_document,
            evidence_registry=registry,
            assets=tuple(assets),
            warnings=tuple(warnings),
            source_sha256=source_sha256,
            document_id=DocumentId(doc_id),
            workspace=workspace,
        )
        self.write_debug_output(result)
        return result

    def write_debug_output(self, result: DocxExtractionResult) -> None:
        result.workspace.mkdir(parents=True, exist_ok=True)
        source_payload = {
            "schema_version": 1,
            "document_id": result.document_id,
            "source_sha256": result.source_sha256,
            "source_type": "docx",
            "assets": [asset.to_dict() for asset in result.assets],
        }
        self._write_json(result.workspace / "source.json", source_payload)
        (result.workspace / "raw_document.json").write_text(
            result.raw_document.model_dump_json(indent=2), encoding="utf-8"
        )
        self._write_json(
            result.workspace / "warnings.json",
            [warning.to_dict() for warning in result.warnings],
        )

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _parse_xml(data: bytes, part_name: str) -> etree._Element:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        try:
            return etree.fromstring(data, parser=parser)
        except etree.XMLSyntaxError as error:
            raise InvalidDocxError(f"invalid XML in DOCX part: {part_name}") from error

    def _relationships(self, package: zipfile.ZipFile, rels_name: str) -> dict[str, dict[str, str]]:
        if rels_name not in package.namelist():
            return {}
        root = self._parse_xml(self._read_part(package, rels_name), rels_name)
        result: dict[str, dict[str, str]] = {}
        for rel in root.findall("pr:Relationship", NS):
            rel_id = rel.get("Id")
            target = rel.get("Target")
            if rel_id and target:
                result[rel_id] = {
                    "target": target,
                    "type": rel.get("Type", ""),
                    "target_mode": rel.get("TargetMode", "Internal"),
                }
        return result

    def _content_types(self, package: zipfile.ZipFile) -> dict[str, str]:
        if CONTENT_TYPES not in package.namelist():
            return {}
        root = self._parse_xml(self._read_part(package, CONTENT_TYPES), CONTENT_TYPES)
        result: dict[str, str] = {}
        for default in root.findall("ct:Default", NS):
            extension = default.get("Extension")
            content_type = default.get("ContentType")
            if extension and content_type:
                result[f"*.{extension.lower()}"] = content_type
        for override in root.findall("ct:Override", NS):
            name = override.get("PartName")
            content_type = override.get("ContentType")
            if name and content_type:
                result[name.lstrip("/")] = content_type
        return result

    def _extract_story(
        self,
        package: zipfile.ZipFile,
        container: etree._Element,
        part_name: str,
        story: str,
        doc_id: str,
        relationships: dict[str, dict[str, str]],
        content_types: dict[str, str],
        assets_dir: Path,
        counters: _Counters,
        objects: list[RawObject],
        registry: EvidenceRegistry,
        assets: list[ExtractedAsset],
        warnings: list[DocxExtractionWarning],
    ) -> None:
        story_order = 0
        for child in container:
            local = etree.QName(child).localname
            if local not in {"p", "tbl"}:
                if local != "sectPr":
                    warnings.append(
                        DocxExtractionWarning(
                            code="UNSUPPORTED_STORY_CHILD",
                            message=f"unsupported {story} child: {local}",
                            part_name=part_name,
                        )
                    )
                continue
            story_order += 1
            object_order = counters.next_object_order()
            if local == "p":
                paragraph, anchored = self._extract_paragraph(
                    package,
                    child,
                    part_name,
                    story,
                    story_order,
                    object_order,
                    doc_id,
                    relationships,
                    content_types,
                    assets_dir,
                    counters,
                    registry,
                    assets,
                    warnings,
                )
                objects.append(paragraph)
                objects.extend(anchored)
            else:
                table = self._extract_table(
                    child,
                    part_name,
                    story,
                    story_order,
                    object_order,
                    doc_id,
                    counters,
                    registry,
                    warnings,
                )
                objects.append(table)

    def _extract_paragraph(
        self,
        package: zipfile.ZipFile,
        element: etree._Element,
        part_name: str,
        story: str,
        story_order: int,
        object_order: int,
        doc_id: str,
        relationships: dict[str, dict[str, str]],
        content_types: dict[str, str],
        assets_dir: Path,
        counters: _Counters,
        registry: EvidenceRegistry,
        assets: list[ExtractedAsset],
        warnings: list[DocxExtractionWarning],
    ) -> tuple[RawParagraph, list[RawImage | RawDrawing]]:
        paragraph_id = docx_object_id(SourceObjectKind.PARAGRAPH, counters.next_paragraph())
        style_element = element.find("w:pPr/w:pStyle", NS)
        style_id = style_element.get(_qn(W, "val")) if style_element is not None else None
        alignment_element = element.find("w:pPr/w:jc", NS)
        alignment = alignment_element.get(_qn(W, "val")) if alignment_element is not None else None
        runs: list[RawRun] = []
        anchored: list[RawImage | RawDrawing] = []
        hyperlinks: list[dict[str, Any]] = []
        fields: list[dict[str, Any]] = []
        run_elements = cast(list[etree._Element], element.xpath(".//w:r", namespaces=NS))
        for run_order, run_element in enumerate(run_elements, start=1):
            text, run_metadata = self._run_text_and_metadata(run_element)
            hyperlink = self._hyperlink_metadata(run_element, relationships)
            if hyperlink:
                run_metadata["hyperlink"] = hyperlink
                hyperlinks.append(hyperlink)
            field_metadata = self._field_metadata(run_element)
            if field_metadata:
                run_metadata["field"] = field_metadata
                fields.append(field_metadata)
            raw_run = RawRun(
                id=run_id(paragraph_id, run_order),
                document_id=doc_id,
                text=text,
                order=run_order,
                bold=self._on_off(run_element, "b"),
                italic=self._on_off(run_element, "i"),
                underline=self._underline(run_element),
                superscript=self._vertical_align(run_element, "superscript"),
                subscript=self._vertical_align(run_element, "subscript"),
                source_metadata=run_metadata,
            )
            runs.append(raw_run)
            registry.register(raw_run)
            anchored.extend(
                self._extract_run_drawings(
                    package,
                    run_element,
                    part_name,
                    paragraph_id,
                    run_order,
                    object_order,
                    doc_id,
                    relationships,
                    content_types,
                    assets_dir,
                    counters,
                    assets,
                    warnings,
                )
            )
        if fields:
            warnings.append(
                DocxExtractionWarning(
                    code="FIELD_PRESERVED_NOT_RESOLVED",
                    message="Word field instructions/results are preserved but dynamic fields are not evaluated",
                    source_id=SourceId(paragraph_id),
                    part_name=part_name,
                )
            )
        legacy_drawings = cast(
            list[etree._Element], element.xpath(".//w:pict | .//w:object", namespaces=NS)
        )
        for legacy_order, _legacy in enumerate(legacy_drawings, start=1):
            drawing_id = docx_object_id(SourceObjectKind.DRAWING, counters.next_drawing())
            anchored.append(
                RawDrawing(
                    id=drawing_id,
                    document_id=doc_id,
                    order=object_order,
                    drawing_type="unsupported_legacy_drawing",
                    source_metadata={
                        "part_name": part_name,
                        "containing_paragraph_id": paragraph_id,
                        "legacy_drawing_order": legacy_order,
                    },
                )
            )
            warnings.append(
                DocxExtractionWarning(
                    code="UNSUPPORTED_LEGACY_DRAWING",
                    message="legacy VML/OLE drawing is retained as unsupported drawing evidence",
                    source_id=SourceId(drawing_id),
                    part_name=part_name,
                )
            )
        paragraph = RawParagraph(
            id=paragraph_id,
            document_id=doc_id,
            text="".join(run.text for run in runs),
            order=object_order,
            runs=tuple(runs),
            style=RawStyle(name=style_id, alignment=alignment),
            source_metadata={
                "part_name": part_name,
                "story": story,
                "story_order": story_order,
                "hyperlinks": hyperlinks,
                "fields": fields,
                "anchored_object_ids": [item.id for item in anchored],
            },
        )
        registry.register(paragraph)
        return paragraph, anchored

    def _run_text_and_metadata(self, run: etree._Element) -> tuple[str, dict[str, Any]]:
        text_parts: list[str] = []
        mappings: list[str] = []
        for descendant in run.iterdescendants():
            local = etree.QName(descendant).localname
            if local in {"t", "delText"} and descendant.text:
                text_parts.append(descendant.text)
            elif local == "tab":
                text_parts.append("\t")
                mappings.append("w:tab -> U+0009")
            elif local in {"br", "cr"}:
                text_parts.append("\n")
                mappings.append(f"w:{local} -> U+000A")
            elif local == "noBreakHyphen":
                text_parts.append("\u2011")
                mappings.append("w:noBreakHyphen -> U+2011")
            elif local == "softHyphen":
                text_parts.append("\u00ad")
                mappings.append("w:softHyphen -> U+00AD")
        return "".join(text_parts), {"character_mappings": mappings}

    def _hyperlink_metadata(
        self, run: etree._Element, relationships: dict[str, dict[str, str]]
    ) -> dict[str, Any] | None:
        parent = run.getparent()
        while parent is not None and etree.QName(parent).localname != "p":
            if etree.QName(parent).localname == "hyperlink":
                rel_id = parent.get(_qn(R, "id"))
                anchor = parent.get(_qn(W, "anchor"))
                relation = relationships.get(rel_id or "", {})
                return {
                    "relationship_id": rel_id,
                    "target": relation.get("target"),
                    "target_mode": relation.get("target_mode"),
                    "anchor": anchor,
                }
            parent = parent.getparent()
        return None

    def _field_metadata(self, run: etree._Element) -> dict[str, Any] | None:
        instructions = [
            str(text)
            for text in cast(list[str], run.xpath(".//w:instrText/text()", namespaces=NS))
            if text
        ]
        field_chars = [
            str(value)
            for value in cast(list[str], run.xpath(".//w:fldChar/@w:fldCharType", namespaces=NS))
            if value
        ]
        parent = run.getparent()
        simple_instruction: str | None = None
        if parent is not None and etree.QName(parent).localname == "fldSimple":
            simple_instruction = parent.get(_qn(W, "instr"))
        if not (instructions or field_chars or simple_instruction):
            return None
        return {
            "instructions": instructions,
            "field_char_types": field_chars,
            "simple_instruction": simple_instruction,
            "resolved": False,
        }

    def _extract_run_drawings(
        self,
        package: zipfile.ZipFile,
        run: etree._Element,
        part_name: str,
        paragraph_id: str,
        run_order: int,
        object_order: int,
        doc_id: str,
        relationships: dict[str, dict[str, str]],
        content_types: dict[str, str],
        assets_dir: Path,
        counters: _Counters,
        assets: list[ExtractedAsset],
        warnings: list[DocxExtractionWarning],
    ) -> list[RawImage | RawDrawing]:
        result: list[RawImage | RawDrawing] = []
        drawings = cast(list[etree._Element], run.xpath(".//w:drawing", namespaces=NS))
        for drawing_index, drawing in enumerate(drawings, start=1):
            blips = cast(list[etree._Element], drawing.xpath(".//a:blip", namespaces=NS))
            if not blips:
                drawing_id = docx_object_id(SourceObjectKind.DRAWING, counters.next_drawing())
                result.append(
                    RawDrawing(
                        id=drawing_id,
                        document_id=doc_id,
                        order=object_order,
                        drawing_type="unsupported_shape",
                        source_metadata={
                            "part_name": part_name,
                            "containing_paragraph_id": paragraph_id,
                            "run_order": run_order,
                            "drawing_order_in_run": drawing_index,
                        },
                    )
                )
                warnings.append(
                    DocxExtractionWarning(
                        code="UNSUPPORTED_DRAWING",
                        message="drawing has no embedded image relationship",
                        source_id=SourceId(drawing_id),
                        part_name=part_name,
                    )
                )
                continue
            for blip_order, blip in enumerate(blips, start=1):
                rel_id = blip.get(_qn(R, "embed")) or blip.get(_qn(R, "link"))
                relation = relationships.get(rel_id or "")
                if not rel_id or relation is None or relation.get("target_mode") == "External":
                    drawing_id = docx_object_id(SourceObjectKind.DRAWING, counters.next_drawing())
                    result.append(
                        RawDrawing(
                            id=drawing_id,
                            document_id=doc_id,
                            order=object_order,
                            drawing_type="unresolved_image_reference",
                            source_metadata={
                                "relationship_id": rel_id,
                                "containing_paragraph_id": paragraph_id,
                                "run_order": run_order,
                            },
                        )
                    )
                    warnings.append(
                        DocxExtractionWarning(
                            code="UNRESOLVED_IMAGE_RELATIONSHIP",
                            message="image relationship is missing, linked, or external",
                            source_id=SourceId(drawing_id),
                            part_name=part_name,
                        )
                    )
                    continue
                media_part = self._resolve_part(part_name, relation["target"])
                if media_part not in package.namelist():
                    warnings.append(
                        DocxExtractionWarning(
                            code="MISSING_IMAGE_PART",
                            message=f"embedded image part is missing: {media_part}",
                            part_name=part_name,
                        )
                    )
                    continue
                image_bytes = self._read_part(package, media_part)
                image_id = docx_object_id(SourceObjectKind.IMAGE, counters.next_image())
                suffix = PurePosixPath(media_part).suffix.lower() or self._extension_for_type(
                    self._content_type(media_part, content_types)
                )
                filename = f"{image_id}{suffix}"
                relative_path = f"assets/{filename}"
                (assets_dir / filename).write_bytes(image_bytes)
                content_type = self._content_type(media_part, content_types)
                width, height, extent_metadata = self._drawing_extent(drawing)
                placement = self._drawing_placement(drawing)
                image = RawImage(
                    id=image_id,
                    document_id=doc_id,
                    order=object_order,
                    asset_reference=relative_path,
                    width=width,
                    height=height,
                    source_metadata={
                        "part_name": part_name,
                        "media_part": media_part,
                        "original_filename": PurePosixPath(media_part).name,
                        "relationship_id": rel_id,
                        "content_type": content_type,
                        "byte_size": len(image_bytes),
                        "sha256": hashlib.sha256(image_bytes).hexdigest(),
                        "containing_paragraph_id": paragraph_id,
                        "run_order": run_order,
                        "drawing_order_in_run": drawing_index,
                        "blip_order": blip_order,
                        "placement": placement,
                        **extent_metadata,
                    },
                )
                result.append(image)
                assets.append(
                    ExtractedAsset(
                        source_id=SourceId(image_id),
                        relative_path=relative_path,
                        content_type=content_type,
                        size_bytes=len(image_bytes),
                        sha256=hashlib.sha256(image_bytes).hexdigest(),
                    )
                )
        return result

    def _extract_table(
        self,
        element: etree._Element,
        part_name: str,
        story: str,
        story_order: int,
        object_order: int,
        doc_id: str,
        counters: _Counters,
        registry: EvidenceRegistry,
        warnings: list[DocxExtractionWarning],
    ) -> RawTable:
        table_id = docx_object_id(SourceObjectKind.TABLE, counters.next_table())
        rows: list[RawTableRow] = []
        header_row_indices: list[int] = []
        nested_tables = cast(list[etree._Element], element.xpath(".//w:tc/w:tbl", namespaces=NS))
        nested_count = len(nested_tables)
        if nested_count:
            warnings.append(
                DocxExtractionWarning(
                    code="NESTED_TABLE_PRESERVED_AS_WARNING",
                    message=f"table contains {nested_count} nested table(s); nested structure is not expanded",
                    source_id=SourceId(table_id),
                    part_name=part_name,
                )
            )
        for row_number, row_element in enumerate(element.findall("w:tr", NS), start=1):
            if row_element.find("w:trPr/w:tblHeader", NS) is not None:
                header_row_indices.append(row_number - 1)
            row_id = table_row_id(table_id, row_number)
            cells: list[RawTableCell] = []
            column_index = 0
            for cell_number, cell_element in enumerate(row_element.findall("w:tc", NS), start=1):
                cell_id = table_cell_id(row_id, cell_number)
                paragraphs = cell_element.findall("w:p", NS)
                paragraph_texts = [self._plain_paragraph_text(paragraph) for paragraph in paragraphs]
                text = "\n".join(paragraph_texts)
                grid_span_element = cell_element.find("w:tcPr/w:gridSpan", NS)
                grid_span = self._positive_int_attr(grid_span_element, "val")
                vertical_merge_element = cell_element.find("w:tcPr/w:vMerge", NS)
                vertical_merge = (
                    vertical_merge_element.get(_qn(W, "val"), "continue")
                    if vertical_merge_element is not None
                    else None
                )
                cell = RawTableCell(
                    id=cell_id,
                    document_id=doc_id,
                    row_index=row_number - 1,
                    column_index=column_index,
                    text=text,
                    column_span=grid_span,
                    source_metadata={
                        "part_name": part_name,
                        "paragraph_texts": paragraph_texts,
                        "vertical_merge": vertical_merge,
                        "contains_nested_table": bool(cell_element.findall("w:tbl", NS)),
                        "contains_drawing": cell_element.find(".//w:drawing", NS) is not None,
                    },
                )
                cells.append(cell)
                registry.register(cell)
                if cell.source_metadata["contains_drawing"]:
                    warnings.append(
                        DocxExtractionWarning(
                            code="TABLE_CELL_DRAWING_NOT_EXTRACTED",
                            message="drawing inside table cell is preserved as metadata only in M1A",
                            source_id=SourceId(cell_id),
                            part_name=part_name,
                        )
                    )
                column_index += grid_span or 1
            rows.append(RawTableRow(id=row_id, document_id=doc_id, index=row_number - 1, cells=tuple(cells)))
        style_element = element.find("w:tblPr/w:tblStyle", NS)
        table_style = style_element.get(_qn(W, "val")) if style_element is not None else None
        return RawTable(
            id=table_id,
            document_id=doc_id,
            order=object_order,
            rows=tuple(rows),
            source_metadata={
                "part_name": part_name,
                "story": story,
                "story_order": story_order,
                "table_style": table_style,
                "header_row_indices": header_row_indices,
                "nested_table_count": nested_count,
            },
        )

    def _extract_headers_and_footers(
        self,
        package: zipfile.ZipFile,
        document_root: etree._Element,
        doc_id: str,
        document_relationships: dict[str, dict[str, str]],
        content_types: dict[str, str],
        assets_dir: Path,
        counters: _Counters,
        objects: list[RawObject],
        registry: EvidenceRegistry,
        assets: list[ExtractedAsset],
        warnings: list[DocxExtractionWarning],
    ) -> None:
        seen: set[str] = set()
        references = cast(
            list[etree._Element],
            document_root.xpath(
                ".//w:sectPr/w:headerReference | .//w:sectPr/w:footerReference", namespaces=NS
            ),
        )
        for reference in references:
            rel_id = reference.get(_qn(R, "id"))
            relation = document_relationships.get(rel_id or "")
            if relation is None:
                warnings.append(
                    DocxExtractionWarning(
                        code="UNRESOLVED_HEADER_FOOTER",
                        message=f"missing relationship for header/footer reference {rel_id}",
                        part_name=DOCUMENT_PART,
                    )
                )
                continue
            part_name = self._resolve_part(DOCUMENT_PART, relation["target"])
            if part_name in seen:
                continue
            seen.add(part_name)
            if part_name not in package.namelist():
                warnings.append(
                    DocxExtractionWarning(
                        code="MISSING_HEADER_FOOTER_PART",
                        message=f"referenced story part is missing: {part_name}",
                        part_name=part_name,
                    )
                )
                continue
            root = self._parse_xml(self._read_part(package, part_name), part_name)
            rels_name = self._rels_name(part_name)
            relationships = self._relationships(package, rels_name)
            story = "header" if etree.QName(reference).localname == "headerReference" else "footer"
            self._extract_story(
                package,
                root,
                part_name,
                story,
                doc_id,
                relationships,
                content_types,
                assets_dir,
                counters,
                objects,
                registry,
                assets,
                warnings,
            )

    def _plain_paragraph_text(self, paragraph: etree._Element) -> str:
        runs = cast(list[etree._Element], paragraph.xpath(".//w:r", namespaces=NS))
        return "".join(self._run_text_and_metadata(run)[0] for run in runs)

    @staticmethod
    def _on_off(run: etree._Element, local: str) -> bool | None:
        element = run.find(f"w:rPr/w:{local}", NS)
        if element is None:
            return None
        value = element.get(_qn(W, "val"), "true").lower()
        return value not in {"false", "0", "off", "none"}

    @staticmethod
    def _underline(run: etree._Element) -> bool | None:
        element = run.find("w:rPr/w:u", NS)
        if element is None:
            return None
        return element.get(_qn(W, "val"), "single").lower() not in {"false", "0", "off", "none"}

    @staticmethod
    def _vertical_align(run: etree._Element, expected: str) -> bool | None:
        element = run.find("w:rPr/w:vertAlign", NS)
        if element is None:
            return None
        return bool(element.get(_qn(W, "val")) == expected)

    @staticmethod
    def _positive_int_attr(element: etree._Element | None, local: str) -> int | None:
        if element is None:
            return None
        value = element.get(_qn(W, local))
        try:
            parsed = int(value or "")
        except ValueError:
            return None
        return parsed if parsed >= 1 else None

    @staticmethod
    def _resolve_part(source_part: str, target: str) -> str:
        return posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target))

    @staticmethod
    def _read_part(package: zipfile.ZipFile, part_name: str) -> bytes:
        try:
            return package.read(part_name)
        except KeyError:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile) as error:
            raise InvalidDocxError(f"cannot read DOCX package part: {part_name}") from error

    @staticmethod
    def _rels_name(part_name: str) -> str:
        path = PurePosixPath(part_name)
        return str(path.parent / "_rels" / f"{path.name}.rels")

    @staticmethod
    def _content_type(part_name: str, content_types: dict[str, str]) -> str:
        return content_types.get(part_name) or content_types.get(f"*{PurePosixPath(part_name).suffix.lower()}") or mimetypes.guess_type(part_name)[0] or "application/octet-stream"

    @staticmethod
    def _extension_for_type(content_type: str) -> str:
        return mimetypes.guess_extension(content_type) or ".bin"

    @staticmethod
    def _drawing_placement(drawing: etree._Element) -> str:
        if drawing.find("wp:inline", NS) is not None:
            return "inline"
        if drawing.find("wp:anchor", NS) is not None:
            return "floating"
        return "unknown"

    @staticmethod
    def _drawing_extent(drawing: etree._Element) -> tuple[float | None, float | None, dict[str, Any]]:
        extent = drawing.find(".//wp:extent", NS)
        if extent is None:
            return None, None, {}
        try:
            cx = int(extent.get("cx", ""))
            cy = int(extent.get("cy", ""))
        except ValueError:
            return None, None, {}
        return cx / 12700, cy / 12700, {"extent_emu": {"cx": cx, "cy": cy}, "dimension_unit": "pt"}
