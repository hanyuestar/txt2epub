"""Scan TXT files for markup and character sequences that need normalization."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


HTML_ENTITY_PATTERN = re.compile(
    r"&(?:#\d+|#x[0-9a-f]+|[a-z][a-z0-9]+);", re.IGNORECASE
)
HTML_TAG_PATTERN = re.compile(r"</?[a-z][^>]*>", re.IGNORECASE)
INVALID_XML_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def read_text(path: Path) -> tuple[str, str]:
    """Read common UTF and Chinese legacy encodings without dependencies."""
    raw_text = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030", "gbk"):
        try:
            return raw_text.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw_text.decode("gbk", errors="replace"), "gbk (replacement mode)"


def iter_txt_files(paths: list[Path]):
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".txt":
            yield path
        elif path.is_dir():
            yield from path.rglob("*.txt")


def report_matches(
    path: Path,
    text: str,
    pattern: re.Pattern[str],
    category: str,
    max_results: int,
) -> tuple[list[tuple[str, Path, int, int, str]], int]:
    findings = []
    total = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in pattern.finditer(line):
            total += 1
            if len(findings) < max_results:
                findings.append(
                    (category, path, line_number, match.start() + 1, line.strip())
                )
    return findings, total


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")

    parser = argparse.ArgumentParser(
        description="Find TXT markup and character sequences that need EPUB normalization."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path("tests")],
        help="TXT file(s) or directories to scan (default: tests)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=20,
        help="Maximum findings printed per category and file",
    )
    args = parser.parse_args()

    if args.max_results < 1:
        parser.error("--max-results must be at least 1")

    patterns = (
        ("HTML entity", HTML_ENTITY_PATTERN),
        ("HTML tag", HTML_TAG_PATTERN),
        ("replacement character", re.compile("\ufffd")),
        ("invalid XML control character", INVALID_XML_CONTROL_PATTERN),
    )
    totals: Counter[str] = Counter()
    file_count = 0

    for path in sorted(set(iter_txt_files(args.paths))):
        file_count += 1
        text, encoding = read_text(path)
        print(f"\n{path} [{encoding}]")
        for category, pattern in patterns:
            findings, total = report_matches(
                path, text, pattern, category, args.max_results
            )
            totals[category] += total
            for _, _, line_number, column, line in findings:
                print(f"  {category} at {line_number}:{column}: {line[:160]}")

    print(f"\nScanned {file_count} TXT file(s).")
    for category, _ in patterns:
        print(f"{category}: {totals[category]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
