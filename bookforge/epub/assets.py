from __future__ import annotations

from pathlib import Path

from bookforge.contracts.common import SourceId

from .errors import MissingAssetError


class MappingAssetResolver:
    """Explicit asset-reference mapping for synthetic and assembled books."""

    def __init__(self, assets: dict[str, Path]) -> None:
        self._assets = dict(assets)

    def resolve(self, reference: str | SourceId) -> Path:
        try:
            path = self._assets[str(reference)]
        except KeyError as error:
            raise MissingAssetError(f"asset is not mapped: {reference}") from error
        if not path.is_file():
            raise MissingAssetError(f"asset path does not exist or is not a file: {path}")
        return path
