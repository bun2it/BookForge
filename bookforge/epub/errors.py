class EpubBuildError(Exception):
    """Base error for deterministic EPUB construction failures."""


class InvalidBookModelError(EpubBuildError):
    """The logical book cannot be rendered without guessing."""


class MissingAssetError(EpubBuildError):
    """A BookModel-referenced asset cannot be resolved."""


class InvalidInternalReferenceError(EpubBuildError):
    """An asset or package reference is unsafe or escapes the EPUB root."""


class EpubPackagingError(EpubBuildError):
    """The EPUB ZIP package could not be constructed or validated."""


class InvalidContinuityError(InvalidBookModelError):
    """Accepted continuity cannot be executed safely by the renderer."""


class UnsupportedV3ContentError(InvalidBookModelError):
    """A V3 node lacks a deterministic supported EPUB representation."""
