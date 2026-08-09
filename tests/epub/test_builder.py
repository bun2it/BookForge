from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from bookforge.contracts.book import BookContentCatalog, BookMetadata, BookModel, Chapter
from bookforge.contracts.common import ProcessingProvenance, TransformationStage
from bookforge.contracts.evidence import EvidenceRegistry
from bookforge.contracts.raw import RawRun, RawTextBlock
from bookforge.contracts.semantic import (
    FragmentRelationship,
    RelationshipType,
    SemanticFigure,
    SemanticFragment,
    SemanticTable,
    SemanticTableCell,
    SemanticTableRow,
    SemanticType,
)
from bookforge.contracts.source import SourceTextReference, TextJoinBehavior
from bookforge.contracts.validation import ValidationStatus
from bookforge.epub import (
    EpubBuilder,
    EpubCheckValidator,
    InvalidBookModelError,
    InvalidInternalReferenceError,
    MappingAssetResolver,
    StructuralEpubValidator,
)


class SyntheticBook:
    def __init__(self) -> None:
        self.registry = EvidenceRegistry()
        self.fragments: dict[str, SemanticFragment] = {}
        self._source_order = 0
        self._fragment_order = 0

    def source(self, text: str, *, run: bool = False, **formatting: bool) -> str:
        self._source_order += 1
        source_id = f"p0001_b{self._source_order:04d}"
        if run:
            evidence = RawRun(
                id=f"docx_p000001_r{self._source_order:04d}",
                document_id="doc_1111111111111111",
                text=text,
                order=self._source_order,
                **formatting,
            )
            source_id = evidence.id
        else:
            evidence = RawTextBlock(
                id=source_id,
                document_id="doc_1111111111111111",
                text=text,
                order=self._source_order,
            )
        self.registry.register(evidence)
        return source_id

    def fragment(
        self,
        kind: SemanticType,
        text: str = "",
        *,
        references: list[SourceTextReference] | None = None,
        metadata: dict[str, object] | None = None,
        relationships: list[FragmentRelationship] | None = None,
    ) -> str:
        self._fragment_order += 1
        fragment_id = f"sem_f{self._fragment_order:06d}"
        refs = references or [
            SourceTextReference(
                source_id=self.source(text), join_behavior=TextJoinBehavior.DIRECT
            )
        ]
        self.fragments[fragment_id] = SemanticFragment(
            id=fragment_id,
            semantic_type=kind,
            source_references=refs,
            metadata=metadata or {},
            relationships=relationships or [],
            provenance=ProcessingProvenance(
                document_id="doc_1111111111111111",
                source_ids=[reference.source_id for reference in refs],
                stage=TransformationStage.SEMANTIC,
                processor="synthetic-test",
                processor_version="2",
            ),
        )
        return fragment_id


def rich_fixture(tmp_path: Path, *, cover: bool = False) -> tuple[BookModel, EvidenceRegistry, MappingAssetResolver, bytes]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    synthetic = SyntheticBook()
    title = synthetic.fragment(SemanticType.TITLE, "Cà phê và Triết đạo")
    author = synthetic.fragment(SemanticType.AUTHOR, "Tác giả Việt Nam")
    chapter_title = synthetic.fragment(SemanticType.CHAPTER_TITLE, "Chương Một")
    paragraph_a = synthetic.fragment(SemanticType.PARAGRAPH, "Paragraph A")
    figure_id = synthetic.fragment(SemanticType.FIGURE, "", metadata={"alt_text": "A diagram"})
    caption_id = synthetic.fragment(SemanticType.CAPTION, "Chú thích hình — cà phê")
    paragraph_b = synthetic.fragment(SemanticType.PARAGRAPH, "Paragraph B")
    table_id = synthetic.fragment(SemanticType.TABLE, "")
    paragraph_c = synthetic.fragment(
        SemanticType.PARAGRAPH, "Cà phê là một phần của văn hóa Việt Nam."
    )
    heading = synthetic.fragment(SemanticType.HEADING, "Một đề mục")
    quote = synthetic.fragment(SemanticType.QUOTE, "“Một câu trích dẫn.”")
    note = synthetic.fragment(SemanticType.NOTE, "Ghi chú")
    tip = synthetic.fragment(SemanticType.TIP, "Mẹo đọc")
    list_id = synthetic.fragment(SemanticType.LIST, "", metadata={"ordered": True})
    list_item_1 = synthetic.fragment(
        SemanticType.LIST_ITEM,
        "Mục một",
        relationships=[
            FragmentRelationship(
                relationship_type=RelationshipType.MEMBER_OF,
                target_fragment_id=list_id,
            )
        ],
    )
    list_item_2 = synthetic.fragment(
        SemanticType.LIST_ITEM,
        "Mục hai",
        relationships=[
            FragmentRelationship(
                relationship_type=RelationshipType.MEMBER_OF,
                target_fragment_id=list_id,
            )
        ],
    )

    image_bytes = b"\x89PNG\r\n\x1a\nsynthetic-image-bytes"
    image_path = tmp_path / "figure.png"
    image_path.write_bytes(image_bytes)
    assets = {"docx_img000001": image_path}
    cover_reference = None
    if cover:
        cover_path = tmp_path / "cover.jpg"
        cover_path.write_bytes(b"\xff\xd8\xffsynthetic-cover\xff\xd9")
        assets["cover_asset"] = cover_path
        cover_reference = "cover_asset"

    figure = SemanticFigure(
        fragment_id=figure_id,
        source_image_id="docx_img000001",
        caption_fragment_id=caption_id,
    )
    cell_values = [
        (0, 0, "Product", True),
        (0, 1, "Capacity", True),
        (1, 0, "A", False),
        (1, 1, "100", False),
        (2, 0, "B", False),
        (2, 1, "200", False),
    ]
    rows: list[SemanticTableRow] = []
    for row_index in range(3):
        cells: list[SemanticTableCell] = []
        for _, column_index, value, is_header in [item for item in cell_values if item[0] == row_index]:
            cells.append(
                SemanticTableCell(
                    row_index=row_index,
                    column_index=column_index,
                    source_references=[
                        SourceTextReference(
                            source_id=synthetic.source(value), join_behavior=TextJoinBehavior.DIRECT
                        )
                    ],
                    is_header=is_header,
                )
            )
        rows.append(SemanticTableRow(index=row_index, cells=cells))
    table = SemanticTable(fragment_id=table_id, source_ids=["docx_tbl000001"], rows=rows)
    logical_order = [
        paragraph_a,
        figure_id,
        caption_id,
        paragraph_b,
        table_id,
        paragraph_c,
        heading,
        quote,
        note,
        tip,
        list_id,
        list_item_1,
        list_item_2,
    ]
    book = BookModel(
        revision="synthetic-v2",
        metadata=BookMetadata(
            title_fragment_id=title,
            author_fragment_ids=[author],
            language="vi",
            identifier="urn:bookforge:test",
            publisher="Nhà xuất bản thử nghiệm",
            description="Sách Unicode — kiểm thử.",
            cover_reference=cover_reference,
        ),
        chapters=[
            Chapter(
                id="chapter-one",
                title_fragment_id=chapter_title,
                content_fragment_ids=logical_order,
            )
        ],
        content=BookContentCatalog(
            fragments=synthetic.fragments,
            figures={figure_id: figure},
            tables={table_id: table},
        ),
    )
    return book, synthetic.registry, MappingAssetResolver(assets), image_bytes


def read_entry(epub: Path, name: str) -> str:
    with zipfile.ZipFile(epub) as package:
        return package.read(name).decode("utf-8")


def test_critical_reflow_unicode_figure_caption_and_table(tmp_path: Path) -> None:
    book, registry, assets, image_bytes = rich_fixture(tmp_path)
    output = tmp_path / "rich.epub"
    artifact = EpubBuilder().build(book, registry, assets, output)
    chapter = read_entry(output, "EPUB/text/chapter_001.xhtml")

    ordered_tokens = [
        "<p>Paragraph A</p>",
        "<figure>",
        "<figcaption>Chú thích hình — cà phê</figcaption>",
        "<p>Paragraph B</p>",
        '<div class="table-wrap"><table>',
        "<p>Cà phê là một phần của văn hóa Việt Nam.</p>",
    ]
    positions = [chapter.index(token) for token in ordered_tokens]
    assert positions == sorted(positions)
    assert "<th>Product</th><th>Capacity</th>" in chapter
    assert "<td>A</td><td>100</td>" in chapter
    assert "<td>B</td><td>200</td>" in chapter
    assert "<ol><li>Mục một</li><li>Mục hai</li></ol>" in chapter
    assert "position: absolute" not in chapter
    assert artifact.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    with zipfile.ZipFile(output) as package:
        image_names = [name for name in package.namelist() if name.startswith("EPUB/images/")]
        assert image_names == ["EPUB/images/image_000001.png"]
        assert package.read(image_names[0]) == image_bytes


def test_critical_package_structure_and_internal_validation(tmp_path: Path) -> None:
    book, registry, assets, _ = rich_fixture(tmp_path)
    output = tmp_path / "package.epub"
    artifact = EpubBuilder().build(book, registry, assets, output)

    with zipfile.ZipFile(output) as package:
        infos = package.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert package.read("mimetype") == b"application/epub+zip"
        expected = {
            "META-INF/container.xml",
            "EPUB/package.opf",
            "EPUB/nav.xhtml",
            "EPUB/styles.css",
            "EPUB/text/title.xhtml",
            "EPUB/text/chapter_001.xhtml",
        }
        assert expected.issubset(package.namelist())
        ElementTree.fromstring(package.read("META-INF/container.xml"))
        ElementTree.fromstring(package.read("EPUB/package.opf"))
        ElementTree.fromstring(package.read("EPUB/nav.xhtml"))
    validation = StructuralEpubValidator().validate(artifact, output)
    assert validation.status is ValidationStatus.PASS
    assert validation.findings == []


def test_deterministic_byte_identical_build(tmp_path: Path) -> None:
    book, registry, assets, _ = rich_fixture(tmp_path)
    first = EpubBuilder().build(book, registry, assets, tmp_path / "first.epub")
    second = EpubBuilder().build(book, registry, assets, tmp_path / "second.epub")
    assert first.sha256 == second.sha256
    assert (tmp_path / "first.epub").read_bytes() == (tmp_path / "second.epub").read_bytes()


def test_multi_chapter_navigation_and_spine_follow_book_order(tmp_path: Path) -> None:
    book, registry, assets, _ = rich_fixture(tmp_path)
    original = book.chapters[0]
    chapters = [
        Chapter(
            id=f"chapter-{index}",
            title_fragment_id=original.title_fragment_id,
            content_fragment_ids=original.content_fragment_ids,
        )
        for index in range(1, 4)
    ]
    multi = BookModel.model_validate({**book.model_dump(), "chapters": chapters})
    output = tmp_path / "multi-chapter.epub"
    EpubBuilder().build(multi, registry, assets, output)
    with zipfile.ZipFile(output) as package:
        assert all(f"EPUB/text/chapter_{index:03d}.xhtml" in package.namelist() for index in range(1, 4))
        opf = package.read("EPUB/package.opf").decode()
        assert opf.index('idref="chapter_001"') < opf.index('idref="chapter_002"') < opf.index('idref="chapter_003"')
        nav = package.read("EPUB/nav.xhtml").decode()
        assert nav.count("Chương Một") == 3


def test_cover_and_no_cover_behavior(tmp_path: Path) -> None:
    no_cover_book, registry, assets, _ = rich_fixture(tmp_path / "without")
    no_cover_output = tmp_path / "no-cover.epub"
    EpubBuilder().build(no_cover_book, registry, assets, no_cover_output)
    with zipfile.ZipFile(no_cover_output) as package:
        assert "EPUB/text/cover.xhtml" not in package.namelist()
        assert b"cover-image" not in package.read("EPUB/package.opf")

    cover_dir = tmp_path / "with"
    cover_dir.mkdir()
    cover_book, cover_registry, cover_assets, _ = rich_fixture(cover_dir, cover=True)
    cover_output = tmp_path / "cover.epub"
    artifact = EpubBuilder().build(cover_book, cover_registry, cover_assets, cover_output)
    with zipfile.ZipFile(cover_output) as package:
        assert "EPUB/text/cover.xhtml" in package.namelist()
        assert b'properties="cover-image"' in package.read("EPUB/package.opf")
        assert package.read("EPUB/images/image_000001.jpg").startswith(b"\xff\xd8\xff")
    assert artifact.metadata_snapshot.cover_reference == "EPUB/images/image_000001.jpg"


def test_multiple_source_references_and_classification_do_not_change_text(tmp_path: Path) -> None:
    synthetic = SyntheticBook()
    title = synthetic.fragment(SemanticType.TITLE, "Title")
    author = synthetic.fragment(SemanticType.AUTHOR, "Author")
    chapter_title = synthetic.fragment(SemanticType.CHAPTER_TITLE, "Chapter")
    first = synthetic.source("The company developed a ")
    second = synthetic.source("comprehensive strategy.")
    references = [
        SourceTextReference(source_id=first, join_behavior=TextJoinBehavior.DIRECT),
        SourceTextReference(source_id=second, join_behavior=TextJoinBehavior.DIRECT),
    ]
    paragraph = synthetic.fragment(SemanticType.PARAGRAPH, references=references)
    book = BookModel(
        revision="multi-source",
        metadata=BookMetadata(
            title_fragment_id=title, author_fragment_ids=[author], language="en", identifier="multi"
        ),
        chapters=[Chapter(id="chapter", title_fragment_id=chapter_title, content_fragment_ids=[paragraph])],
        content=BookContentCatalog(fragments=synthetic.fragments),
    )
    output = tmp_path / "multi.epub"
    EpubBuilder().build(book, synthetic.registry, MappingAssetResolver({}), output)
    assert "The company developed a comprehensive strategy." in read_entry(
        output, "EPUB/text/chapter_001.xhtml"
    )
    book.content.fragments[paragraph].semantic_type = SemanticType.QUOTE
    second_output = tmp_path / "quote.epub"
    EpubBuilder().build(book, synthetic.registry, MappingAssetResolver({}), second_output)
    assert "The company developed a comprehensive strategy." in read_entry(
        second_output, "EPUB/text/chapter_001.xhtml"
    )


def test_explicit_join_behaviors_are_applied_without_inference(tmp_path: Path) -> None:
    synthetic = SyntheticBook()
    title = synthetic.fragment(SemanticType.TITLE, "Title")
    author = synthetic.fragment(SemanticType.AUTHOR, "Author")
    chapter_title = synthetic.fragment(SemanticType.CHAPTER_TITLE, "Chapter")
    first = synthetic.source("well-")
    second = synthetic.source("formed")
    third = synthetic.source("next line")
    paragraph = synthetic.fragment(
        SemanticType.PARAGRAPH,
        references=[
            SourceTextReference(source_id=first, join_behavior=TextJoinBehavior.DIRECT),
            SourceTextReference(source_id=second, join_behavior=TextJoinBehavior.REMOVE_TRAILING_HYPHEN),
            SourceTextReference(source_id=third, join_behavior=TextJoinBehavior.NEWLINE),
        ],
    )
    book = BookModel(
        revision="joins",
        metadata=BookMetadata(
            title_fragment_id=title, author_fragment_ids=[author], language="en", identifier="joins"
        ),
        chapters=[Chapter(id="chapter", title_fragment_id=chapter_title, content_fragment_ids=[paragraph])],
        content=BookContentCatalog(fragments=synthetic.fragments),
    )
    output = tmp_path / "joins.epub"
    EpubBuilder().build(book, synthetic.registry, MappingAssetResolver({}), output)
    assert "<p>wellformed<br/>next line</p>" in read_entry(output, "EPUB/text/chapter_001.xhtml")


def test_inline_formatting_and_xml_escaping(tmp_path: Path) -> None:
    synthetic = SyntheticBook()
    title = synthetic.fragment(SemanticType.TITLE, "T & <T>")
    author = synthetic.fragment(SemanticType.AUTHOR, "Author")
    chapter_title = synthetic.fragment(SemanticType.CHAPTER_TITLE, "Chapter")
    bold = synthetic.source("Bold & <safe>", run=True, bold=True)
    italic = synthetic.source("italic", run=True, italic=True)
    paragraph = synthetic.fragment(
        SemanticType.PARAGRAPH,
        references=[
            SourceTextReference(source_id=bold, join_behavior=TextJoinBehavior.DIRECT),
            SourceTextReference(source_id=italic, join_behavior=TextJoinBehavior.SPACE),
        ],
    )
    book = BookModel(
        revision="format",
        metadata=BookMetadata(
            title_fragment_id=title, author_fragment_ids=[author], language="en", identifier="format"
        ),
        chapters=[Chapter(id="chapter", title_fragment_id=chapter_title, content_fragment_ids=[paragraph])],
        content=BookContentCatalog(fragments=synthetic.fragments),
    )
    output = tmp_path / "format.epub"
    EpubBuilder().build(book, synthetic.registry, MappingAssetResolver({}), output)
    chapter = read_entry(output, "EPUB/text/chapter_001.xhtml")
    assert "<strong>Bold &amp; &lt;safe&gt;</strong> <em>italic</em>" in chapter
    ElementTree.fromstring(chapter)


def test_defer_join_and_unsafe_asset_are_rejected(tmp_path: Path) -> None:
    synthetic = SyntheticBook()
    title = synthetic.fragment(SemanticType.TITLE, "Title")
    author = synthetic.fragment(SemanticType.AUTHOR, "Author")
    chapter_title = synthetic.fragment(SemanticType.CHAPTER_TITLE, "Chapter")
    source = synthetic.source("Deferred")
    paragraph = synthetic.fragment(
        SemanticType.PARAGRAPH,
        references=[SourceTextReference(source_id=source, join_behavior=TextJoinBehavior.DEFER)],
    )
    book = BookModel(
        revision="defer",
        metadata=BookMetadata(
            title_fragment_id=title, author_fragment_ids=[author], language="en", identifier="defer"
        ),
        chapters=[Chapter(id="chapter", title_fragment_id=chapter_title, content_fragment_ids=[paragraph])],
        content=BookContentCatalog(fragments=synthetic.fragments),
    )
    with pytest.raises(InvalidBookModelError, match="DEFER"):
        EpubBuilder().build(book, synthetic.registry, MappingAssetResolver({}), tmp_path / "defer.epub")

    figure_source = synthetic.fragment(SemanticType.FIGURE, "")
    unsafe = SemanticFigure(fragment_id=figure_source, source_image_id="../outside.png")
    unsafe_book = book.model_copy(
        update={
            "chapters": [Chapter(id="chapter", title_fragment_id=chapter_title, content_fragment_ids=[figure_source])],
            "content": BookContentCatalog(
                fragments=synthetic.fragments, figures={figure_source: unsafe}
            ),
        }
    )
    unsafe_book = BookModel.model_validate(unsafe_book.model_dump())
    with pytest.raises(InvalidInternalReferenceError):
        EpubBuilder().build(
            unsafe_book,
            synthetic.registry,
            MappingAssetResolver({"../outside.png": tmp_path / "outside.png"}),
            tmp_path / "unsafe.epub",
        )


def test_epubcheck_unavailable_or_unexecutable_never_passes(tmp_path: Path) -> None:
    book, registry, assets, _ = rich_fixture(tmp_path)
    output = tmp_path / "check.epub"
    artifact = EpubBuilder().build(book, registry, assets, output)
    record = EpubCheckValidator("/definitely/missing/epubcheck").validate(artifact, output)
    assert record.status is ValidationStatus.FAIL
    assert record.findings[0].code == "VALIDATOR_EXECUTION_FAILED"


def test_epubcheck_unavailable_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    book, registry, assets, _ = rich_fixture(tmp_path)
    output = tmp_path / "unavailable.epub"
    artifact = EpubBuilder().build(book, registry, assets, output)
    monkeypatch.setattr("bookforge.epub.epubcheck.shutil.which", lambda _name: None)
    validator = EpubCheckValidator()
    record = validator.validate(artifact, output)
    assert validator.available is False
    assert record.status is ValidationStatus.FAIL
    assert record.findings[0].code == "VALIDATOR_UNAVAILABLE"
