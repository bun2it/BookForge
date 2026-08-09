from __future__ import annotations

import argparse
from pathlib import Path

from .errors import DocxExtractionError
from .extractor import DocxExtractor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect deterministic DOCX raw evidence")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = DocxExtractor().extract(args.source, args.output)
    except DocxExtractionError as error:
        print(f"DOCX extraction failed: {error}")
        return 2
    print(result.workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
