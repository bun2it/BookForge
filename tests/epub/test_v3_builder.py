from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from bookforge.contracts.assembly import (
    AssemblyProvenance,
    BookContentCatalogV3,
    BookMetadataV3,
    BookModelV3,
    ChapterV3,
    EvidenceKind,
    EvidenceReference,
    FigureDataV3,
    FigureSemanticNode,
    LogicalContinuityV3,
    MatterV3,
    PartV3,
    SectionLevel,
    SectionV3,
    TableCellV3,
    TableDataV3,
    TableRowV3,
    TableSemanticNode,
    TextSemanticNode,
    UnsupportedContentKind,
    UnsupportedSemanticNode,
)
from bookforge.contracts.common import FragmentId, SourceId
from bookforge.contracts.evidence import EvidenceRegistry
from bookforge.contracts.flow import (
    ContinuityType,
    LogicalBreakIntent,
    LogicalListId,
    LogicalListKind,
    LogicalListV3,
)
from bookforge.contracts.ids import flow_decision_id, flow_group_id, logical_list_id
from bookforge.contracts.raw import RawRun, RawTextBlock
from bookforge.contracts.semantic import SemanticType
from bookforge.contracts.source import SourceTextReference
from bookforge.contracts.validation import ValidationStatus
from bookforge.epub import (
    EpubV3Builder,
    InvalidBookModelError,
    InvalidContinuityError,
    MappingAssetResolver,
    MissingAssetError,
    StructuralEpubValidator,
    UnsupportedV3ContentError,
)

HASH = "a" * 64


class SyntheticV3:
    def __init__(self) -> None:
        self.registry = EvidenceRegistry()
        self.nodes: dict[FragmentId, object] = {}
        self._order = 0

    def text(self, semantic_type: SemanticType, value: str, *, page_number: int | None = None) -> FragmentId:
        self._order += 1
        fragment_id = FragmentId(f"sem_f{self._order:06d}")
        source_id = SourceId(f"p0001_b{self._order:04d}")
        self.registry.register(
            RawTextBlock(
                id=source_id, document_id="doc_1111111111111111", text=value,
                order=self._order, page_number=page_number,
            )
        )
        self.nodes[fragment_id] = TextSemanticNode(
            id=fragment_id,
            semantic_type=semantic_type,
            source_references=(SourceTextReference(source_id=source_id),),
            source_evidence=(EvidenceReference(source_id=source_id, kind=EvidenceKind.TEXT),),
        )
        return fragment_id

    def model(
        self,
        title: FragmentId,
        chapter_title: FragmentId,
        content: tuple[FragmentId, ...],
        *,
        continuity: tuple[LogicalContinuityV3, ...] = (),
        break_intent: LogicalBreakIntent = LogicalBreakIntent.NEW_PAGE,
        cover_reference: str | None = None,
        logical_lists: tuple[LogicalListV3, ...] = (),
    ) -> BookModelV3:
        return BookModelV3(
            revision="asm_1234567890abcdef1234",
            metadata=BookMetadataV3(
                title_fragment_id=title, language="vi", identifier="urn:v3-test",
                publisher="BookForge & Co", cover_reference=cover_reference,
            ),
            body=(
                ChapterV3(
                    id=flow_group_id("chapter", 1), break_intent=break_intent,
                    opening_fragment_ids=(chapter_title,), content_fragment_ids=content,
                ),
            ),
            content=BookContentCatalogV3(nodes=self.nodes),
            continuity=continuity,
            logical_lists=logical_lists,
            provenance=AssemblyProvenance(
                document_id="doc_1111111111111111",
                semantic_catalog_fingerprint=HASH,
                accepted_classification_fingerprint=HASH,
                resolved_flow_fingerprint=HASH,
                assembly_policy_fingerprint=HASH,
            ),
        )


def edge(left: FragmentId, right: FragmentId, operation: ContinuityType) -> LogicalContinuityV3:
    return LogicalContinuityV3(
        left_node_id=left,
        right_node_id=right,
        operation=operation,
        source_decision_id=flow_decision_id(
            decision_kind=operation.value,
            fragment_ids=[str(left), str(right)],
            input_fingerprint=HASH,
            configuration_fingerprint=HASH,
            policy_version="v1",
        ),
    )


def list_truth(
    members: tuple[FragmentId, ...],
    *,
    kind: LogicalListKind = LogicalListKind.UNORDERED,
    start_value: int | None = None,
    parent: LogicalListV3 | None = None,
    parent_item: FragmentId | None = None,
) -> LogicalListV3:
    list_id = LogicalListId(
        logical_list_id(
            kind=kind.value,
            member_fragment_ids=[str(item) for item in members],
            parent_list_id=str(parent.list_id) if parent else None,
            parent_item_fragment_id=str(parent_item) if parent_item else None,
            start_value=start_value,
        )
    )
    return LogicalListV3(
        list_id=list_id,
        kind=kind,
        member_fragment_ids=members,
        parent_list_id=parent.list_id if parent else None,
        parent_item_fragment_id=parent_item,
        start_value=start_value,
    )


def read(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as package:
        return package.read(name).decode()


def basic() -> tuple[SyntheticV3, FragmentId, FragmentId]:
    value = SyntheticV3()
    return value, value.text(SemanticType.BOOK_TITLE, "Cà phê & Triết đạo"), value.text(
        SemanticType.CHAPTER_TITLE, "CHƯƠNG II — CON ĐƯỜNG TỈNH THỨC"
    )


def test_minimal_v3_unicode_xml_package_and_internal_validation(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    paragraph = value.text(SemanticType.PARAGRAPH, "Cà phê là một phần của văn hóa Việt Nam.")
    book = value.model(title, chapter_title, (paragraph,))
    before = book.model_dump_json()
    output = tmp_path / "minimal.epub"
    artifact = EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    xhtml = read(output, "EPUB/text/segment_001.xhtml")
    assert "CHƯƠNG II — CON ĐƯỜNG TỈNH THỨC" in xhtml
    assert "Cà phê là một phần của văn hóa Việt Nam." in xhtml
    assert "BookForge &amp; Co" in read(output, "EPUB/package.opf")
    assert artifact.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    assert StructuralEpubValidator().validate(artifact, output).status is ValidationStatus.PASS
    assert book.model_dump_json() == before


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (ContinuityType.JOIN_DIRECT, "coffeehouse"),
        (ContinuityType.JOIN_WITH_SPACE, "coffee house"),
        (ContinuityType.JOIN_WITH_NEWLINE, "coffee<br/>house"),
        (ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN, "comprehensive"),
    ],
)
def test_v3_text_continuity_executes_only_in_rendered_xhtml(
    tmp_path: Path, operation: ContinuityType, expected: str
) -> None:
    value, title, chapter_title = basic()
    left_text = "compre-" if operation is ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN else "coffee"
    right_text = "hensive" if operation is ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN else "house"
    left = value.text(SemanticType.PARAGRAPH, left_text, page_number=10)
    right = value.text(SemanticType.PARAGRAPH, right_text, page_number=11)
    book = value.model(
        title, chapter_title, (left, right), continuity=(edge(left, right, operation),),
        break_intent=LogicalBreakIntent.NONE,
    )
    source_before = value.registry.resolve_text(value.nodes[left].source_references[0])  # type: ignore[union-attr]
    output = tmp_path / f"{operation.value}.epub"
    EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    xhtml = read(output, "EPUB/text/segment_001.xhtml")
    assert expected in xhtml
    assert xhtml.count("<p>") == 1
    assert value.registry.resolve_text(value.nodes[left].source_references[0]) == source_before  # type: ignore[union-attr]
    assert expected not in book.model_dump_json()
    assert "logical-break-page" not in xhtml


def test_continuity_chain_renders_each_source_once(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    first = value.text(SemanticType.PARAGRAPH, "Văn hóa")
    second = value.text(SemanticType.PARAGRAPH, "cà")
    third = value.text(SemanticType.PARAGRAPH, "phê Việt Nam")
    book = value.model(
        title, chapter_title, (first, second, third),
        continuity=(
            edge(first, second, ContinuityType.JOIN_WITH_SPACE),
            edge(second, third, ContinuityType.JOIN_WITH_SPACE),
        ),
    )
    output = tmp_path / "chain.epub"
    EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    xhtml = read(output, "EPUB/text/segment_001.xhtml")
    assert "Văn hóa cà phê Việt Nam" in xhtml
    assert xhtml.count("Văn hóa") == 1


def test_invalid_remove_hyphen_fails_visibly(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    left = value.text(SemanticType.PARAGRAPH, "compre")
    right = value.text(SemanticType.PARAGRAPH, "hensive")
    book = value.model(
        title, chapter_title, (left, right),
        continuity=(edge(left, right, ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN),),
    )
    with pytest.raises(InvalidContinuityError, match="trailing hyphen"):
        EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), tmp_path / "bad.epub")


def test_new_page_partitions_resources_but_none_keeps_chapters_together(tmp_path: Path) -> None:
    value, title, first_title = basic()
    first_text = value.text(SemanticType.PARAGRAPH, "First")
    second_title = value.text(SemanticType.CHAPTER_TITLE, "Second")
    second_text = value.text(SemanticType.PARAGRAPH, "Second body")
    first = ChapterV3(
        id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE,
        opening_fragment_ids=(first_title,), content_fragment_ids=(first_text,),
    )
    second_none = ChapterV3(
        id=flow_group_id("chapter", 2), break_intent=LogicalBreakIntent.NONE,
        opening_fragment_ids=(second_title,), content_fragment_ids=(second_text,),
    )
    book = BookModelV3(
        revision="asm_1234567890abcdef1234",
        metadata=BookMetadataV3(title_fragment_id=title, language="en", identifier="breaks"),
        body=(first, second_none), content=BookContentCatalogV3(nodes=value.nodes),
        provenance=AssemblyProvenance(
            document_id="doc_1111111111111111", semantic_catalog_fingerprint=HASH,
            accepted_classification_fingerprint=HASH, resolved_flow_fingerprint=HASH,
            assembly_policy_fingerprint=HASH,
        ),
    )
    output = tmp_path / "none.epub"
    EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    with zipfile.ZipFile(output) as package:
        segments = [name for name in package.namelist() if name.startswith("EPUB/text/segment_")]
    assert segments == ["EPUB/text/segment_001.xhtml"]
    xhtml = read(output, segments[0])
    assert xhtml.index("First") < xhtml.index("Second body")
    changed = book.model_copy(update={"body": (first, second_none.model_copy(update={"break_intent": LogicalBreakIntent.NEW_PAGE}))})
    changed_output = tmp_path / "new-page.epub"
    EpubV3Builder().build(changed, value.registry, MappingAssetResolver({}), changed_output)
    with zipfile.ZipFile(changed_output) as package:
        changed_segments = [name for name in package.namelist() if name.startswith("EPUB/text/segment_")]
    assert changed_segments == ["EPUB/text/segment_001.xhtml", "EPUB/text/segment_002.xhtml"]


def test_part_navigation_and_spine_follow_v3_hierarchy(tmp_path: Path) -> None:
    value = SyntheticV3()
    title = value.text(SemanticType.BOOK_TITLE, "Book")
    part_title = value.text(SemanticType.PART_TITLE, "PART I")
    chapter_title = value.text(SemanticType.CHAPTER_TITLE, "Chapter One")
    paragraph = value.text(SemanticType.PARAGRAPH, "Body")
    chapter = ChapterV3(
        id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE,
        opening_fragment_ids=(chapter_title,), content_fragment_ids=(paragraph,),
    )
    part = PartV3(
        id=flow_group_id("part", 1), break_intent=LogicalBreakIntent.NEW_PAGE,
        opening_fragment_ids=(part_title,), chapters=(chapter,),
    )
    book = BookModelV3(
        revision="asm_1234567890abcdef1234",
        metadata=BookMetadataV3(title_fragment_id=title, language="en", identifier="part"),
        body=(part,), content=BookContentCatalogV3(nodes=value.nodes),
        provenance=AssemblyProvenance(
            document_id="doc_1111111111111111", semantic_catalog_fingerprint=HASH,
            accepted_classification_fingerprint=HASH, resolved_flow_fingerprint=HASH,
            assembly_policy_fingerprint=HASH,
        ),
    )
    output = tmp_path / "part.epub"
    EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    nav = read(output, "EPUB/nav.xhtml")
    assert nav.index("PART I") < nav.index("Chapter One")
    assert "<ol><li>" in nav and nav.count("<ol>") >= 2
    opf = read(output, "EPUB/package.opf")
    assert opf.index('idref="segment_001"') < opf.index('idref="segment_002"')


def test_section_none_stays_continuous_and_section_new_page_splits(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    paragraph = value.text(SemanticType.PARAGRAPH, "Chapter body")
    section_title = value.text(SemanticType.SECTION_HEADING, "Section A")
    section_text = value.text(SemanticType.PARAGRAPH, "Section body")
    section = SectionV3(
        id=flow_group_id("section", 1), level=SectionLevel.SECTION,
        break_intent=LogicalBreakIntent.NONE, opening_fragment_ids=(section_title,),
        content_fragment_ids=(section_text,),
    )
    chapter = ChapterV3(
        id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE,
        opening_fragment_ids=(chapter_title,), content_fragment_ids=(paragraph,), sections=(section,),
    )
    base = value.model(title, chapter_title, (paragraph,))
    book = base.model_copy(update={"body": (chapter,)})
    output = tmp_path / "section-none.epub"
    EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    with zipfile.ZipFile(output) as package:
        segments = [name for name in package.namelist() if name.startswith("EPUB/text/segment_")]
    assert len(segments) == 1
    assert "logical-break-page" not in read(output, segments[0]).split("Section A", 1)[1]
    new_section = section.model_copy(update={"break_intent": LogicalBreakIntent.NEW_PAGE})
    changed = book.model_copy(update={"body": (chapter.model_copy(update={"sections": (new_section,)}),)})
    changed_output = tmp_path / "section-new.epub"
    EpubV3Builder().build(changed, value.registry, MappingAssetResolver({}), changed_output)
    with zipfile.ZipFile(changed_output) as package:
        assert "EPUB/text/segment_002.xhtml" in package.namelist()


def test_figure_uses_explicit_asset_reference_and_logical_caption_order(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    caption = value.text(SemanticType.CAPTION, "Chú thích nguồn")
    image_source = SourceId("docx_img000001")
    figure_id = FragmentId(f"sem_f{value._order + 1:06d}")
    value._order += 1
    value.nodes[figure_id] = FigureSemanticNode(
        id=figure_id,
        evidence=(EvidenceReference(source_id=image_source, kind=EvidenceKind.IMAGE, asset_reference="asset-key"),),
        figure=FigureDataV3(fragment_id=figure_id, source_image_id=image_source, caption_fragment_id=caption),
    )
    image = tmp_path / "source.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\noriginal")
    book = value.model(title, chapter_title, (caption, figure_id))
    output = tmp_path / "figure.epub"
    EpubV3Builder().build(book, value.registry, MappingAssetResolver({"asset-key": image}), output)
    xhtml = read(output, "EPUB/text/segment_001.xhtml")
    assert xhtml.index("<figcaption>") < xhtml.index("<img")
    assert 'alt=""' in xhtml
    with zipfile.ZipFile(output) as package:
        assert package.read("EPUB/images/image_000001.png") == image.read_bytes()


def test_explicit_cover_only_and_missing_figure_asset_are_typed(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    paragraph = value.text(SemanticType.PARAGRAPH, "Body")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xffcover\xff\xd9")
    book = value.model(title, chapter_title, (paragraph,), cover_reference="cover-key")
    output = tmp_path / "cover.epub"
    artifact = EpubV3Builder().build(
        book, value.registry, MappingAssetResolver({"cover-key": cover}), output
    )
    assert artifact.metadata_snapshot.cover_reference == "EPUB/images/image_000001.jpg"
    assert "EPUB/text/cover.xhtml" in zipfile.ZipFile(output).namelist()
    with pytest.raises(MissingAssetError, match="not mapped"):
        EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), tmp_path / "missing-cover.epub")


def test_table_renders_explicit_cells_without_reconstruction(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    refs: list[SourceTextReference] = []
    for text in ("Product", "100"):
        node_id = value.text(SemanticType.PARAGRAPH, text)
        node = value.nodes.pop(node_id)
        refs.append(node.source_references[0])  # type: ignore[union-attr]
    table_id = FragmentId(f"sem_f{value._order + 1:06d}")
    value._order += 1
    table_source = SourceId("docx_tbl000001")
    value.nodes[table_id] = TableSemanticNode(
        id=table_id,
        evidence=(EvidenceReference(source_id=table_source, kind=EvidenceKind.TABLE),),
        table=TableDataV3(
            fragment_id=table_id, source_ids=(table_source,),
            rows=(TableRowV3(index=0, cells=(
                TableCellV3(row_index=0, column_index=0, source_references=(refs[0],), is_header=True),
                TableCellV3(row_index=0, column_index=1, source_references=(refs[1],), column_span=2),
            )),),
        ),
    )
    output = tmp_path / "table.epub"
    EpubV3Builder().build(
        value.model(title, chapter_title, (table_id,)), value.registry,
        MappingAssetResolver({}), output,
    )
    xhtml = read(output, "EPUB/text/segment_001.xhtml")
    assert "<th>Product</th>" in xhtml
    assert '<td colspan="2">100</td>' in xhtml


def test_continue_table_combines_only_explicit_rows(tmp_path: Path) -> None:
    value, title, chapter_title = basic()

    def add_table(number: int, cell_text: str) -> FragmentId:
        text_id = value.text(SemanticType.PARAGRAPH, cell_text)
        text_node = value.nodes.pop(text_id)
        reference = text_node.source_references[0]  # type: ignore[union-attr]
        table_id = FragmentId(f"sem_f{value._order + 1:06d}")
        value._order += 1
        source_id = SourceId(f"docx_tbl{number:06d}")
        value.nodes[table_id] = TableSemanticNode(
            id=table_id,
            evidence=(EvidenceReference(source_id=source_id, kind=EvidenceKind.TABLE),),
            table=TableDataV3(
                fragment_id=table_id, source_ids=(source_id,),
                rows=(TableRowV3(index=0, cells=(
                    TableCellV3(row_index=0, column_index=0, source_references=(reference,)),
                )),),
            ),
        )
        return table_id

    first = add_table(1, "Row A")
    second = add_table(2, "Row B")
    book = value.model(
        title, chapter_title, (first, second),
        continuity=(edge(first, second, ContinuityType.CONTINUE_TABLE),),
    )
    output = tmp_path / "continued-table.epub"
    EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    xhtml = read(output, "EPUB/text/segment_001.xhtml")
    assert xhtml.count("<table>") == 1
    assert xhtml.count("<tr>") == 2
    assert xhtml.index("Row A") < xhtml.index("Row B")


@pytest.mark.parametrize(
    ("kind", "start_value", "opening"),
    [
        (LogicalListKind.UNORDERED, None, "<ul>"),
        (LogicalListKind.ORDERED, None, "<ol>"),
        (LogicalListKind.ORDERED, 3, '<ol start="3">'),
    ],
)
def test_logical_list_renders_native_html_in_exact_order_without_duplicates(
    tmp_path: Path,
    kind: LogicalListKind,
    start_value: int | None,
    opening: str,
) -> None:
    value, title, chapter_title = basic()
    intro = value.text(SemanticType.PARAGRAPH, "Mở đầu")
    items = (
        value.text(SemanticType.LIST_ITEM, "Cà phê & sáng tạo"),
        value.text(SemanticType.LIST_ITEM, "Văn hóa cà phê"),
        value.text(SemanticType.LIST_ITEM, "Xã hội Việt Nam"),
    )
    closing = value.text(SemanticType.PARAGRAPH, "Kết luận")
    logical_list = list_truth(items, kind=kind, start_value=start_value)
    book = value.model(
        title, chapter_title, (intro, *items, closing), logical_lists=(logical_list,)
    )
    output = tmp_path / f"list-{kind.value}-{start_value}.epub"
    artifact = EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    xhtml = read(output, "EPUB/text/segment_001.xhtml")
    assert opening in xhtml
    if start_value is None:
        assert "<ol start=" not in xhtml
    assert xhtml.index("Mở đầu") < xhtml.index("Cà phê &amp; sáng tạo")
    assert xhtml.index("Cà phê &amp; sáng tạo") < xhtml.index("Văn hóa cà phê") < xhtml.index("Xã hội Việt Nam")
    assert xhtml.index("Xã hội Việt Nam") < xhtml.index("Kết luận")
    assert xhtml.count("<li>") == 3
    assert xhtml.count("Văn hóa cà phê") == 1
    assert StructuralEpubValidator().validate(artifact, output).status is ValidationStatus.PASS


def test_realistic_mixed_nested_list_and_arbitrary_depth_four(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    intro = value.text(SemanticType.PARAGRAPH, "Intro paragraph")
    item1 = value.text(SemanticType.LIST_ITEM, "Cà phê là nguồn năng lượng sáng tạo.")
    item2 = value.text(SemanticType.LIST_ITEM, "Văn hóa cà phê hình thành qua nhiều thế kỷ.")
    item21 = value.text(SemanticType.LIST_ITEM, "Triết học")
    item211 = value.text(SemanticType.LIST_ITEM, "Hiện sinh")
    item2111 = value.text(SemanticType.LIST_ITEM, "Con người")
    item2112 = value.text(SemanticType.LIST_ITEM, "Tự do")
    item212 = value.text(SemanticType.LIST_ITEM, "Khắc kỷ")
    item22 = value.text(SemanticType.LIST_ITEM, "Nghệ thuật")
    item23 = value.text(SemanticType.LIST_ITEM, "Xã hội")
    item3 = value.text(SemanticType.LIST_ITEM, "Cà phê tiếp tục phát triển.")
    closing = value.text(SemanticType.PARAGRAPH, "Closing paragraph")
    root = list_truth((item1, item2, item3), kind=LogicalListKind.ORDERED)
    level2 = list_truth(
        (item21, item22, item23), parent=root, parent_item=item2,
        kind=LogicalListKind.UNORDERED,
    )
    level3 = list_truth(
        (item211, item212), parent=level2, parent_item=item21,
        kind=LogicalListKind.ORDERED,
    )
    level4 = list_truth(
        (item2111, item2112), parent=level3, parent_item=item211,
        kind=LogicalListKind.UNORDERED,
    )
    logical_order = (
        intro, item1, item2, item21, item211, item2111, item2112,
        item212, item22, item23, item3, closing,
    )
    book = value.model(
        title, chapter_title, logical_order,
        logical_lists=(root, level2, level3, level4),
    )
    output = tmp_path / "nested.epub"
    EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    xhtml = read(output, "EPUB/text/segment_001.xhtml")
    assert xhtml.count("<ol>") == 2
    assert xhtml.count("<ul>") == 2
    assert "Văn hóa cà phê hình thành qua nhiều thế kỷ.<ul>" in xhtml
    assert "Triết học<ol>" in xhtml
    assert "Hiện sinh<ul>" in xhtml
    for token in (
        "Cà phê là nguồn năng lượng sáng tạo.", "Văn hóa cà phê", "Triết học",
        "Hiện sinh", "Con người", "Tự do", "Khắc kỷ", "Nghệ thuật", "Xã hội",
        "Cà phê tiếp tục phát triển.",
    ):
        assert xhtml.count(token) == 1
    assert xhtml.index("Intro paragraph") < xhtml.index("<ol>") < xhtml.index("Closing paragraph")


def test_two_independent_lists_render_only_from_catalog(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    first_items = (
        value.text(SemanticType.LIST_ITEM, "First A"),
        value.text(SemanticType.LIST_ITEM, "First B"),
    )
    middle = value.text(SemanticType.PARAGRAPH, "Between")
    second_items = (
        value.text(SemanticType.LIST_ITEM, "Second A"),
        value.text(SemanticType.LIST_ITEM, "Second B"),
    )
    book = value.model(
        title, chapter_title, (*first_items, middle, *second_items),
        logical_lists=(
            list_truth(first_items),
            list_truth(second_items, kind=LogicalListKind.ORDERED),
        ),
    )
    output = tmp_path / "two.epub"
    EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    xhtml = read(output, "EPUB/text/segment_001.xhtml")
    assert xhtml.count("<ul>") == 1 and xhtml.count("<ol>") == 1
    assert xhtml.index("First B") < xhtml.index("Between") < xhtml.index("Second A")


def test_list_item_reuses_raw_run_inline_formatting(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    source_id = SourceId("docx_p000001_r0001")
    value.registry.register(
        RawRun(
            id=source_id, document_id="doc_1111111111111111", text="Đậm & nghiêng",
            order=1, bold=True, italic=True, underline=True,
        )
    )
    value._order += 1
    item_id = FragmentId(f"sem_f{value._order:06d}")
    value.nodes[item_id] = TextSemanticNode(
        id=item_id, semantic_type=SemanticType.LIST_ITEM,
        source_references=(SourceTextReference(source_id=source_id),),
        source_evidence=(EvidenceReference(source_id=source_id, kind=EvidenceKind.TEXT),),
    )
    book = value.model(
        title, chapter_title, (item_id,), logical_lists=(list_truth((item_id,)),)
    )
    output = tmp_path / "formatted-list.epub"
    EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    xhtml = read(output, "EPUB/text/segment_001.xhtml")
    assert '<li><span class="underline"><em><strong>Đậm &amp; nghiêng</strong></em></span></li>' in xhtml


def test_continue_list_is_audit_only_and_does_not_duplicate_items(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    first = value.text(SemanticType.LIST_ITEM, "One")
    second = value.text(SemanticType.LIST_ITEM, "Two")
    logical_list = list_truth((first, second))
    book = value.model(
        title, chapter_title, (first, second),
        logical_lists=(logical_list,),
        continuity=(edge(first, second, ContinuityType.CONTINUE_LIST),),
    )
    output = tmp_path / "continued-list.epub"
    EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    xhtml = read(output, "EPUB/text/segment_001.xhtml")
    assert xhtml.count("<ul>") == 1
    assert xhtml.count("One") == 1 and xhtml.count("Two") == 1
    assert book.continuity[0].source_decision_id


def test_text_join_between_distinct_list_items_fails_visibly(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    first = value.text(SemanticType.LIST_ITEM, "One")
    second = value.text(SemanticType.LIST_ITEM, "Two")
    book = value.model(
        title, chapter_title, (first, second),
        logical_lists=(list_truth((first, second)),),
        continuity=(edge(first, second, ContinuityType.JOIN_WITH_SPACE),),
    )
    with pytest.raises(InvalidContinuityError, match="one-fragment"):
        EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), tmp_path / "bad-join.epub")


def test_lists_render_in_front_body_and_back_without_changing_break_ownership(tmp_path: Path) -> None:
    value = SyntheticV3()
    title = value.text(SemanticType.BOOK_TITLE, "Book")
    front_items = (
        value.text(SemanticType.LIST_ITEM, "Front A"),
        value.text(SemanticType.LIST_ITEM, "Front B"),
    )
    chapter_title = value.text(SemanticType.CHAPTER_TITLE, "Chapter")
    body_items = (
        value.text(SemanticType.LIST_ITEM, "Body A"),
        value.text(SemanticType.LIST_ITEM, "Body B"),
    )
    back_items = (
        value.text(SemanticType.LIST_ITEM, "Back A"),
        value.text(SemanticType.LIST_ITEM, "Back B"),
    )
    base = value.model(title, chapter_title, body_items)
    model = base.model_copy(
        update={
            "front_matter": MatterV3(content_fragment_ids=front_items),
            "back_matter": MatterV3(content_fragment_ids=back_items),
            "logical_lists": (
                list_truth(front_items),
                list_truth(body_items, kind=LogicalListKind.ORDERED),
                list_truth(back_items),
            ),
        }
    )
    output = tmp_path / "matter-lists.epub"
    EpubV3Builder().build(model, value.registry, MappingAssetResolver({}), output)
    first = read(output, "EPUB/text/segment_001.xhtml")
    second = read(output, "EPUB/text/segment_002.xhtml")
    assert "Front A" in first and "Body A" not in first
    assert second.index("Body A") < second.index("Back A")


def test_list_inside_section_none_stays_in_current_resource(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    chapter_text = value.text(SemanticType.PARAGRAPH, "Before section")
    section_title = value.text(SemanticType.SECTION_HEADING, "Continuous section")
    items = (
        value.text(SemanticType.LIST_ITEM, "Section item A"),
        value.text(SemanticType.LIST_ITEM, "Section item B"),
    )
    section = SectionV3(
        id=flow_group_id("section", 1), level=SectionLevel.SECTION,
        break_intent=LogicalBreakIntent.NONE,
        opening_fragment_ids=(section_title,), content_fragment_ids=items,
    )
    chapter = ChapterV3(
        id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE,
        opening_fragment_ids=(chapter_title,), content_fragment_ids=(chapter_text,),
        sections=(section,),
    )
    base = value.model(title, chapter_title, (chapter_text,))
    book = base.model_copy(update={"body": (chapter,), "logical_lists": (list_truth(items),)})
    output = tmp_path / "section-list.epub"
    EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    with zipfile.ZipFile(output) as package:
        segments = [name for name in package.namelist() if name.startswith("EPUB/text/segment_")]
    assert segments == ["EPUB/text/segment_001.xhtml"]
    xhtml = read(output, segments[0])
    assert xhtml.index("Before section") < xhtml.index("Continuous section") < xhtml.index("<ul>")


def test_list_source_segment_triggers_catalog_list_but_is_not_rendered_as_item(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    segment = value.text(SemanticType.LIST, "source-list-segment-marker")
    first = value.text(SemanticType.LIST_ITEM, "Item A")
    second = value.text(SemanticType.LIST_ITEM, "Item B")
    logical_list = list_truth((first, second)).model_copy(
        update={"source_segment_fragment_ids": (segment,)}
    )
    book = value.model(
        title, chapter_title, (segment, first, second), logical_lists=(logical_list,)
    )
    output = tmp_path / "segment-list.epub"
    EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), output)
    xhtml = read(output, "EPUB/text/segment_001.xhtml")
    assert "<ul><li>Item A</li><li>Item B</li></ul>" in xhtml
    assert "source-list-segment-marker" not in xhtml


def test_list_epub_bytes_and_sha_are_deterministic(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    items = (
        value.text(SemanticType.LIST_ITEM, "Một"),
        value.text(SemanticType.LIST_ITEM, "Hai"),
    )
    book = value.model(
        title, chapter_title, items,
        logical_lists=(list_truth(items, kind=LogicalListKind.ORDERED, start_value=3),),
    )
    first = EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), tmp_path / "list-a.epub")
    second = EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), tmp_path / "list-b.epub")
    assert first.sha256 == second.sha256
    assert (tmp_path / "list-a.epub").read_bytes() == (tmp_path / "list-b.epub").read_bytes()


def test_renderer_defensively_blocks_forced_nesting_cycle(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    first = value.text(SemanticType.LIST_ITEM, "One")
    second = value.text(SemanticType.LIST_ITEM, "Two")
    first_list = list_truth((first,))
    second_list = list_truth((second,))
    cyclic_first = first_list.model_copy(
        update={"parent_list_id": second_list.list_id, "parent_item_fragment_id": second}
    )
    cyclic_second = second_list.model_copy(
        update={"parent_list_id": first_list.list_id, "parent_item_fragment_id": first}
    )
    base = value.model(title, chapter_title, (first, second))
    forced = base.model_copy(update={"logical_lists": (cyclic_first, cyclic_second)})
    with pytest.raises(InvalidBookModelError, match="nested list|cycle"):
        EpubV3Builder().build(forced, value.registry, MappingAssetResolver({}), tmp_path / "cycle.epub")


def test_list_contract_blocker_is_typed_and_not_faked(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    item = value.text(SemanticType.LIST_ITEM, "Item")
    with pytest.raises(UnsupportedV3ContentError, match="list structure"):
        EpubV3Builder().build(
            value.model(title, chapter_title, (item,)), value.registry,
            MappingAssetResolver({}), tmp_path / "list.epub",
        )


def test_bad_source_reference_and_forced_unsupported_node_fail(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    paragraph = value.text(SemanticType.PARAGRAPH, "Body")
    book = value.model(title, chapter_title, (paragraph,))
    with pytest.raises(InvalidBookModelError, match="not registered"):
        EpubV3Builder().build(book, EvidenceRegistry(), MappingAssetResolver({}), tmp_path / "missing.epub")
    unsupported = UnsupportedSemanticNode(
        id=paragraph, content_kind=UnsupportedContentKind.DRAWING,
        evidence=(EvidenceReference(source_id=SourceId("docx_drw000001"), kind=EvidenceKind.DRAWING),),
        reason_code="forced-test",
    )
    invalid_catalog = book.content.model_copy(update={"nodes": {**book.content.nodes, paragraph: unsupported}})
    forced = book.model_copy(update={"content": invalid_catalog})
    with pytest.raises(UnsupportedV3ContentError):
        EpubV3Builder().build(forced, value.registry, MappingAssetResolver({}), tmp_path / "unsupported.epub")


def test_v3_epub_is_byte_deterministic_and_v2_builder_remains_separate(tmp_path: Path) -> None:
    value, title, chapter_title = basic()
    paragraph = value.text(SemanticType.PARAGRAPH, "Stable")
    book = value.model(title, chapter_title, (paragraph,))
    first = EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), tmp_path / "a.epub")
    second = EpubV3Builder().build(book, value.registry, MappingAssetResolver({}), tmp_path / "b.epub")
    assert first.sha256 == second.sha256
    assert (tmp_path / "a.epub").read_bytes() == (tmp_path / "b.epub").read_bytes()
