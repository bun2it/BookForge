class PdfLayoutRuntimeError(RuntimeError):
    """Base M6A runtime failure."""


class PdfOpenError(PdfLayoutRuntimeError):
    pass


class PdfEncryptedError(PdfOpenError):
    pass


class PdfRenderError(PdfLayoutRuntimeError):
    pass


class PdfScannerOutputError(PdfLayoutRuntimeError):
    pass


class PdfLayoutWorkspaceError(PdfLayoutRuntimeError):
    pass


class PdfCatalogError(PdfLayoutRuntimeError):
    """Base deterministic M6B catalog build failure."""


class PdfMarkerConflictError(PdfCatalogError):
    pass


class PdfMarkerReferenceError(PdfCatalogError):
    pass


class PdfStaleScannerResultError(PdfCatalogError):
    pass
