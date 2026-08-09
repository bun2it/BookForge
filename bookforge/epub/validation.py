from __future__ import annotations

import posixpath
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from bookforge.contracts.artifact import ImmutableEpubArtifact
from bookforge.contracts.common import ArtifactId
from bookforge.contracts.validation import (
    FindingSeverity,
    ValidationFinding,
    ValidationRecord,
    ValidationStatus,
)

EPOCH = datetime(1980, 1, 1, tzinfo=timezone.utc)
OPF_NS = "http://www.idpf.org/2007/opf"
XHTML_NS = "http://www.w3.org/1999/xhtml"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"


class StructuralEpubValidator:
    """Lightweight package consistency checks; this is not EPUBCheck."""

    def validate(self, artifact: ImmutableEpubArtifact, path: Path | None = None) -> ValidationRecord:
        epub_path = path or Path(artifact.relative_path)
        findings: list[ValidationFinding] = []
        try:
            with zipfile.ZipFile(epub_path) as package:
                self._validate_package(package, findings)
        except (OSError, zipfile.BadZipFile) as error:
            findings.append(
                ValidationFinding(
                    code="INVALID_EPUB_ZIP",
                    severity=FindingSeverity.ERROR,
                    message=str(error),
                    affected_reference=str(epub_path),
                )
            )
        status = ValidationStatus.FAIL if any(
            finding.severity is FindingSeverity.ERROR for finding in findings
        ) else (ValidationStatus.PASS_WITH_WARNINGS if findings else ValidationStatus.PASS)
        return ValidationRecord(
            id=f"structural_{artifact.sha256[:16]}",
            artifact_id=artifact.id,
            validator="bookforge-structural",
            validator_version="1",
            status=status,
            findings=findings,
            created_at=EPOCH,
        )

    def _validate_package(
        self, package: zipfile.ZipFile, findings: list[ValidationFinding]
    ) -> None:
        infos = package.infolist()
        names = [info.filename for info in infos]
        if not infos or infos[0].filename != "mimetype":
            self._error(findings, "MIMETYPE_NOT_FIRST", "mimetype must be the first ZIP entry")
        elif infos[0].compress_type != zipfile.ZIP_STORED:
            self._error(findings, "MIMETYPE_COMPRESSED", "mimetype must be stored without compression")
        elif package.read("mimetype") != b"application/epub+zip":
            self._error(findings, "INVALID_MIMETYPE", "mimetype content is invalid")
        if "META-INF/container.xml" not in names:
            self._error(findings, "MISSING_CONTAINER", "META-INF/container.xml is missing")
            return
        try:
            container = ElementTree.fromstring(package.read("META-INF/container.xml"))
        except ElementTree.ParseError as error:
            self._error(findings, "INVALID_CONTAINER_XML", str(error))
            return
        rootfile = container.find(f".//{{{CONTAINER_NS}}}rootfile")
        opf_path = rootfile.get("full-path") if rootfile is not None else None
        if not opf_path or opf_path not in names:
            self._error(findings, "MISSING_OPF", "container rootfile does not resolve")
            return
        if not self._safe_internal_path(opf_path):
            self._error(findings, "UNSAFE_OPF_PATH", f"unsafe OPF path: {opf_path}")
            return
        try:
            opf = ElementTree.fromstring(package.read(opf_path))
        except ElementTree.ParseError as error:
            self._error(findings, "INVALID_OPF_XML", str(error), opf_path)
            return
        manifest_items = opf.findall(f".//{{{OPF_NS}}}manifest/{{{OPF_NS}}}item")
        manifest: dict[str, str] = {}
        for item in manifest_items:
            item_id = item.get("id")
            href = item.get("href")
            if not item_id or not href:
                self._error(findings, "INVALID_MANIFEST_ITEM", "manifest item lacks id or href")
                continue
            if item_id in manifest:
                self._error(findings, "DUPLICATE_MANIFEST_ID", f"duplicate manifest ID: {item_id}")
            manifest[item_id] = href
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href))
            if not self._safe_internal_path(resolved):
                self._error(findings, "UNSAFE_MANIFEST_PATH", f"unsafe manifest path: {href}")
            elif resolved not in names:
                self._error(findings, "MISSING_MANIFEST_ASSET", f"manifest path is missing: {resolved}")
        nav_items = [item for item in manifest_items if "nav" in (item.get("properties") or "").split()]
        if not nav_items:
            self._error(findings, "MISSING_NAV_ITEM", "manifest has no EPUB navigation item")
        for itemref in opf.findall(f".//{{{OPF_NS}}}spine/{{{OPF_NS}}}itemref"):
            idref = itemref.get("idref")
            if not idref or idref not in manifest:
                self._error(findings, "INVALID_SPINE_IDREF", f"spine idref is invalid: {idref}")
        for item_id, href in manifest.items():
            if not href.endswith((".xhtml", ".html")):
                continue
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href))
            if resolved not in names:
                continue
            try:
                xhtml = ElementTree.fromstring(package.read(resolved))
            except ElementTree.ParseError as error:
                self._error(findings, "INVALID_XHTML", str(error), resolved)
                continue
            for image in xhtml.findall(f".//{{{XHTML_NS}}}img"):
                source = image.get("src")
                if not source:
                    self._error(findings, "IMAGE_WITHOUT_SOURCE", "img element has no src", resolved)
                    continue
                target = posixpath.normpath(posixpath.join(posixpath.dirname(resolved), source))
                if not self._safe_internal_path(target):
                    self._error(findings, "UNSAFE_IMAGE_REFERENCE", source, resolved)
                elif target not in names:
                    self._error(findings, "MISSING_IMAGE_REFERENCE", target, resolved)

    @staticmethod
    def _safe_internal_path(path: str) -> bool:
        pure = PurePosixPath(path)
        return not pure.is_absolute() and ".." not in pure.parts

    @staticmethod
    def _error(
        findings: list[ValidationFinding], code: str, message: str, affected: str | None = None
    ) -> None:
        findings.append(
            ValidationFinding(
                code=code,
                severity=FindingSeverity.ERROR,
                message=message,
                affected_reference=affected,
            )
        )
