# txt2epub

[English](README.md) | [中文](README.zh.md)

`txt2epub` is a command-line converter for turning TXT novels and other long-form text into EPUB books. It is designed for common Chinese TXT sources as well as English chapter headings, and has no GUI dependency.

## Requirements

- Python 3.10 or newer

## Install

Install the project and its command-line entry point:

```powershell
python -m pip install .
```

Alternatively, install the runtime dependencies for local development:

```powershell
python -m pip install -r requirements.txt
```

## Convert a book

```powershell
txt2epub convert --input .\novel.txt
```

The EPUB is written beside the input file by default. Set its metadata or destination when needed:

```powershell
txt2epub convert `
  --input .\novel.txt `
  --output .\novel.epub `
  --title "My Novel" `
  --author "Author" `
  --language zh `
  --cover .\cover.png
```

When running directly from a cloned checkout without installing the package, use:

```powershell
python -m src convert --input .\novel.txt
```

Run `txt2epub convert --help` for the complete option list. `--encoding` can force a known input encoding; otherwise the converter tries UTF-8, GB18030, GBK, and automatic detection.

## Chapter recognition

The converter recognises common chapter forms, including:

- Chinese headings such as `第一章 标题`, `第二回 标题`, `第 十二 章 标题`, and `012 标题`.
- Numbered headings such as `001 [标题]` and `1. Title`.
- English `Chapter`, `Book`, `Part`, and `Volume` headings.
- Special sections such as `序章`, `楔子`, `前言`, `终章`, `尾声`, `后记`, `附录`, and `番外`.

It also removes repeated title-only tables of contents, converts common scraped HTML paragraph tags, and decodes HTML entities such as `&amp;`. Decimal numbers and timestamps are deliberately not treated as chapter headings.

If no reliable chapter layout is found, the source is kept as one EPUB chapter instead of splitting ordinary paragraphs incorrectly.

## Development checks

Install the development tool and run the available checks:

```powershell
python -m pip install ruff
make check
```

To scan TXT sources for HTML markup, entities, replacement characters, and invalid XML control characters:

```powershell
python scripts\check_txt_compatibility.py tests
```

## License

This project is released under the [MIT License](LICENSE).
