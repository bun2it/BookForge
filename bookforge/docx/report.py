"""Human and JSON diagnostics over already-serialized DOCX raw evidence."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from bookforge.contracts.raw import (
    RawDocument,
    RawDrawing,
    RawImage,
    RawObject,
    RawParagraph,
    RawTable,
)

PREVIEW_LENGTH = 100


def _preview(text: str, limit: int = PREVIEW_LENGTH) -> str:
    compact = text.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    if len(compact) > limit:
        compact = compact[: max(0, limit - 1)] + "…"
    return compact


def _quoted_preview(text: str) -> str:
    return json.dumps(_preview(text), ensure_ascii=False)


def _story(item: RawObject) -> str:
    metadata = getattr(item, "source_metadata", {})
    explicit = metadata.get("story")
    if isinstance(explicit, str):
        return explicit
    part_name = metadata.get("part_name")
    if isinstance(part_name, str):
        if "/header" in part_name:
            return "header"
        if "/footer" in part_name:
            return "footer"
    return "body"


def _object_summary(item: RawObject) -> dict[str, Any]:
    base: dict[str, Any] = {"id": item.id, "kind": item.kind, "story": _story(item)}
    if isinstance(item, RawParagraph):
        base.update(
            {
                "type": "PARAGRAPH",
                "text_preview": _preview(item.text),
                "run_count": len(item.runs),
                "anchored_object_ids": list(item.source_metadata.get("anchored_object_ids", [])),
            }
        )
    elif isinstance(item, RawTable):
        base.update(
            {
                "type": "TABLE",
                "rows": len(item.rows),
                "columns": max((len(row.cells) for row in item.rows), default=0),
            }
        )
    elif isinstance(item, RawImage):
        base.update(
            {
                "type": "IMAGE",
                "anchor": item.source_metadata.get("containing_paragraph_id"),
                "placement": item.source_metadata.get("placement", "unknown"),
            }
        )
    elif isinstance(item, RawDrawing):
        base.update(
            {
                "type": "DRAWING",
                "anchor": item.source_metadata.get("containing_paragraph_id"),
                "drawing_type": item.drawing_type,
            }
        )
    else:
        base["type"] = item.kind.upper()
    return base


def _paragraph_context(paragraph: RawParagraph | None) -> dict[str, Any] | None:
    if paragraph is None:
        return None
    return {"id": paragraph.id, "text_preview": _preview(paragraph.text)}


def _surrounding_paragraphs(
    objects: list[RawObject], anchor_id: str, story: str
) -> tuple[RawParagraph | None, RawParagraph | None]:
    anchor_index = next((index for index, item in enumerate(objects) if item.id == anchor_id), None)
    if anchor_index is None:
        return None, None
    before = next(
        (
            item
            for item in reversed(objects[:anchor_index])
            if isinstance(item, RawParagraph) and _story(item) == story
        ),
        None,
    )
    after = next(
        (
            item
            for item in objects[anchor_index + 1 :]
            if isinstance(item, RawParagraph) and _story(item) == story
        ),
        None,
    )
    return before, after


def _load_warning_data(raw_path: Path) -> list[dict[str, Any]]:
    warning_path = raw_path.with_name("warnings.json")
    if not warning_path.is_file():
        return []
    loaded = json.loads(warning_path.read_text(encoding="utf-8"))
    return [item for item in loaded if isinstance(item, dict)] if isinstance(loaded, list) else []


def build_report(raw_document: RawDocument, warnings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    objects = list(raw_document.objects)
    paragraphs = [item for item in objects if isinstance(item, RawParagraph)]
    tables = [item for item in objects if isinstance(item, RawTable)]
    images = [item for item in objects if isinstance(item, RawImage)]
    drawings = [item for item in objects if isinstance(item, RawDrawing)]
    runs = [run for paragraph in paragraphs for run in paragraph.runs]
    rows = [row for table in tables for row in table.rows]
    cells = [cell for row in rows for cell in row.cells]
    warning_data = warnings or []

    story_paragraphs = {
        story: [paragraph for paragraph in paragraphs if _story(paragraph) == story]
        for story in ("body", "header", "footer")
    }
    image_anchor_ids = {
        str(image.source_metadata.get("containing_paragraph_id")) for image in images
    }
    image_only = [paragraph for paragraph in paragraphs if not paragraph.text and paragraph.id in image_anchor_ids]
    text_and_image = [paragraph for paragraph in paragraphs if paragraph.text and paragraph.id in image_anchor_ids]
    non_empty = [paragraph for paragraph in paragraphs if paragraph.text]
    fields = [field for paragraph in paragraphs for field in paragraph.source_metadata.get("fields", [])]
    hyperlinks = [
        hyperlink for paragraph in paragraphs for hyperlink in paragraph.source_metadata.get("hyperlinks", [])
    ]

    consecutive_groups: list[list[str]] = []
    for story in ("body", "header", "footer"):
        current: list[str] = []
        for paragraph in story_paragraphs[story]:
            if not paragraph.text:
                current.append(paragraph.id)
            else:
                if len(current) > 1:
                    consecutive_groups.append(current)
                current = []
        if len(current) > 1:
            consecutive_groups.append(current)

    fragmentation: dict[str, Any] = {
        "paragraphs_over_10_runs": [paragraph.id for paragraph in paragraphs if len(paragraph.runs) > 10],
        "paragraphs_over_20_runs": [paragraph.id for paragraph in paragraphs if len(paragraph.runs) > 20],
        "whitespace_only_run_ids": [run.id for run in runs if run.text != "" and run.text.isspace()],
        "consecutive_empty_paragraph_groups": consecutive_groups,
        "extremely_short_paragraph_ids": [
            paragraph.id for paragraph in paragraphs if 1 <= len(paragraph.text.strip()) <= 3
        ],
        "paragraphs_with_images": sorted(image_anchor_ids),
    }
    fragmentation["counts"] = {
        "paragraphs_over_10_runs": len(fragmentation["paragraphs_over_10_runs"]),
        "paragraphs_over_20_runs": len(fragmentation["paragraphs_over_20_runs"]),
        "whitespace_only_runs": len(fragmentation["whitespace_only_run_ids"]),
        "consecutive_empty_groups": len(consecutive_groups),
        "consecutive_empty_pairs": sum(len(group) - 1 for group in consecutive_groups),
        "extremely_short_non_empty_paragraphs": len(fragmentation["extremely_short_paragraph_ids"]),
        "paragraphs_with_images": len(image_anchor_ids),
    }

    body_objects = [item for item in objects if _story(item) == "body"]
    body_flow = [
        {"sequence": sequence, **_object_summary(item)}
        for sequence, item in enumerate(body_objects, start=1)
    ]

    image_contexts: list[dict[str, Any]] = []
    for image in images:
        story = _story(image)
        anchor_id = str(image.source_metadata.get("containing_paragraph_id", ""))
        anchor = next(
            (item for item in paragraphs if item.id == anchor_id and _story(item) == story), None
        )
        before, after = _surrounding_paragraphs(objects, anchor_id, story)
        image_contexts.append(
            {
                "id": image.id,
                "story": story,
                "before": _paragraph_context(before),
                "anchor": {
                    "id": anchor_id or None,
                    "text_preview": _preview(anchor.text) if anchor is not None else None,
                    "run": image.source_metadata.get("run_order"),
                    "placement": image.source_metadata.get("placement", "unknown"),
                },
                "after": _paragraph_context(after),
            }
        )

    table_contexts: list[dict[str, Any]] = []
    for table in tables:
        index = objects.index(table)
        previous = objects[index - 1] if index > 0 else None
        following = objects[index + 1] if index + 1 < len(objects) else None
        table_cells = [cell for row in table.rows for cell in row.cells]
        table_contexts.append(
            {
                "id": table.id,
                "story": _story(table),
                "rows": len(table.rows),
                "columns": max((len(row.cells) for row in table.rows), default=0),
                "style": table.source_metadata.get("table_style"),
                "previous": _object_summary(previous) if previous is not None else None,
                "next": _object_summary(following) if following is not None else None,
                "cell_previews": [
                    {"id": cell.id, "text_preview": _preview(cell.text)} for cell in table_cells[:8]
                ],
                "has_grid_span": any(cell.column_span not in (None, 1) for cell in table_cells),
                "has_vertical_merge": any(
                    cell.source_metadata.get("vertical_merge") is not None for cell in table_cells
                ),
            }
        )

    stories: dict[str, Any] = {}
    for story in ("body", "header", "footer"):
        story_items = [item for item in objects if _story(item) == story]
        story_fields = [
            field
            for paragraph in story_paragraphs[story]
            for field in paragraph.source_metadata.get("fields", [])
        ]
        stories[story] = {
            "object_count": len(story_items),
            "paragraph_count": len(story_paragraphs[story]),
            "table_count": sum(isinstance(item, RawTable) for item in story_items),
            "image_count": sum(isinstance(item, RawImage) for item in story_items),
            "drawing_count": sum(isinstance(item, RawDrawing) for item in story_items),
            "text_characters": sum(len(item.text) for item in story_paragraphs[story]),
            "paragraph_previews": [
                {
                    "id": paragraph.id,
                    "text_preview": _preview(paragraph.text),
                    "fields": paragraph.source_metadata.get("fields", []),
                }
                for paragraph in story_paragraphs[story]
            ],
            "field_count": len(story_fields),
        }

    summary = {
        "document_id": raw_document.id,
        "original_name": raw_document.original_name,
        "body_paragraphs": len(story_paragraphs["body"]),
        "header_paragraphs": len(story_paragraphs["header"]),
        "footer_paragraphs": len(story_paragraphs["footer"]),
        "runs": len(runs),
        "tables": len(tables),
        "rows": len(rows),
        "cells": len(cells),
        "images": len(images),
        "drawings": len(drawings),
        "fields": len(fields),
        "hyperlinks": len(hyperlinks),
        "warnings": len(warning_data),
        "warning_codes": dict(sorted(Counter(str(item.get("code", "UNKNOWN")) for item in warning_data).items())),
        "total_authoritative_text_characters": sum(len(item.text) for item in paragraphs)
        + sum(len(cell.text) for cell in cells),
        "empty_paragraphs": sum(not paragraph.text for paragraph in paragraphs),
        "image_only_paragraphs": len(image_only),
        "text_and_image_paragraphs": len(text_and_image),
        "maximum_runs_in_one_paragraph": max((len(paragraph.runs) for paragraph in paragraphs), default=0),
        "average_runs_per_non_empty_paragraph": round(
            (sum(len(paragraph.runs) for paragraph in non_empty) / len(non_empty))
            if non_empty
            else 0.0,
            3,
        ),
    }
    return {
        "schema_version": 1,
        "summary": summary,
        "fragmentation": fragmentation,
        "body_flow": body_flow,
        "image_contexts": image_contexts,
        "table_contexts": table_contexts,
        "stories": stories,
    }


def load_report(raw_path: Path) -> dict[str, Any]:
    raw_document = RawDocument.model_validate_json(raw_path.read_text(encoding="utf-8"))
    return build_report(raw_document, _load_warning_data(raw_path))


def _flow_line(item: dict[str, Any]) -> str:
    prefix = f"{item['sequence']:06d}  {item['type']:<10} {item['id']}"
    if item["type"] == "PARAGRAPH":
        return f"{prefix}  {_quoted_preview(str(item['text_preview']))}"
    if item["type"] == "TABLE":
        return f"{prefix}  {item['rows']}x{item['columns']}"
    if item["type"] in {"IMAGE", "DRAWING"}:
        return f"{prefix}  anchor={item.get('anchor')}"
    return prefix


def _context_line(value: dict[str, Any] | None) -> str:
    if value is None:
        return "  —"
    return f"  {value['id']} {_quoted_preview(str(value.get('text_preview') or ''))}"


def render_human(report: dict[str, Any]) -> str:
    summary = report["summary"]
    fragmentation = report["fragmentation"]
    lines = [
        "BOOKFORGE DOCX EXTRACTION REPORT",
        f"Document: {summary['original_name']} ({summary['document_id']})",
        "",
        "SUMMARY",
    ]
    for key, value in summary.items():
        if key not in {"document_id", "original_name", "warning_codes"}:
            lines.append(f"  {key}: {value}")
    lines.append(f"  warning_codes: {summary['warning_codes']}")
    lines.extend(["", "STORY SUMMARY"])
    for story in ("body", "header", "footer"):
        data = report["stories"][story]
        lines.append(
            f"  {story.upper()}: paragraphs={data['paragraph_count']} tables={data['table_count']} "
            f"images={data['image_count']} drawings={data['drawing_count']} fields={data['field_count']} "
            f"text_chars={data['text_characters']}"
        )
    lines.extend(["", "TEXT FRAGMENTATION"])
    for key, value in fragmentation["counts"].items():
        lines.append(f"  {key}: {value}")
    lines.extend(["", "BODY FLOW"])
    lines.extend(_flow_line(item) for item in report["body_flow"])

    lines.extend(["", "IMAGE CONTEXTS"])
    for context in report["image_contexts"]:
        lines.extend(
            [
                f"IMAGE {context['id']} story={context['story']}",
                "BEFORE:",
                _context_line(context["before"]),
                "ANCHOR:",
                f"  {context['anchor']['id']} run={context['anchor']['run']} "
                f"placement={context['anchor']['placement']} "
                f"{_quoted_preview(str(context['anchor'].get('text_preview') or ''))}",
                "AFTER:",
                _context_line(context["after"]),
                "",
            ]
        )

    lines.append("TABLE CONTEXTS")
    for table in report["table_contexts"]:
        lines.append(
            f"TABLE {table['id']} story={table['story']} dimensions={table['rows']}x{table['columns']} "
            f"style={table['style']} gridSpan={table['has_grid_span']} vMerge={table['has_vertical_merge']}"
        )
        lines.append(f"  PREVIOUS: {table['previous']}")
        lines.append(f"  NEXT: {table['next']}")
        lines.append(f"  CELLS: {table['cell_previews']}")

    lines.extend(["", "HEADER / FOOTER EVIDENCE"])
    for story in ("header", "footer"):
        lines.append(story.upper())
        previews = report["stories"][story]["paragraph_previews"]
        if not previews:
            lines.append("  —")
        for paragraph in previews:
            lines.append(
                f"  {paragraph['id']} {_quoted_preview(str(paragraph['text_preview']))} "
                f"fields={paragraph['fields']}"
            )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report DOCX raw-evidence extraction quality")
    parser.add_argument("raw_document", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = load_report(args.raw_document)
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_human(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
