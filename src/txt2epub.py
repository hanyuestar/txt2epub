"""TXT-to-EPUB conversion utilities."""

import html
import pathlib
import re
import uuid

import langdetect
from charset_normalizer import from_bytes
from ebooklib import epub

from .utils import convert_image_to_jpeg


# Chapter headings from Chinese web novels and common English ebook formats.
CHINESE_HEADING_PATTERN = re.compile(
    r"^\s*第\s*[0-9零〇一二三四五六七八九十百千万兩两]+\s*[章节回篇卷部集]"
    r"(?=\s|[、，,:：.。!！?？\-—【（(]|$).*$"
)
BARE_NUMBER_HEADING_PATTERN = re.compile(
    r"^\s*0*(\d{1,4})(?:"
    r"\s*[章节回篇卷部集](?=\s|[、，,:：.。!！?？\-—【（(]|$).*"
    # A dot or colon is a heading separator only when it is not the start of
    # a decimal number or a timestamp (for example, ``45.761871`` / ``10:20``).
    r"|(?:[.．、，,:：\-—])(?=\s|[^\d]).+"
    r"|[\t ]+\S+.*"
    r")$"
)
SPECIAL_HEADING_PATTERN = re.compile(
    r"^\s*(?:序章|楔子|引子|前言|终章|尾声|结语|后记|跋|附录|番外(?:[篇卷集]|[0-9零〇一二三四五六七八九十百千万兩两]+)?)"
    r"(?=\s|[、，,:：.。!！?？\-—【（(]|$).*$",
    re.IGNORECASE,
)
ENGLISH_HEADING_PATTERN = re.compile(
    r"^\s*(?:(?:chapter|chap\.?)\s*(?:\d+|[ivxlcdm]+)"
    r"|(?:volume|book|part)\s*(?:\d+|[ivxlcdm]+))\b.*$",
    re.IGNORECASE,
)
MAIN_TEXT_MARKER_PATTERN = re.compile(
    r"^\s*[=－—\-_*#]{3,}\s*(?:正文|开始正文|main\s+text|text)\s*[=－—\-_*#]{3,}\s*$",
    re.IGNORECASE,
)
HTML_BLOCK_TAG_PATTERN = re.compile(r"</?(?:p|br|div|h[1-6]|li)\b[^>]*>", re.IGNORECASE)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
HTML_ENTITY_PATTERN = re.compile(
    r"&(?:#\d+|#x[0-9a-f]+|[a-z][a-z0-9]+);", re.IGNORECASE
)


def normalize_book_text(book_text: str) -> str:
    """Normalize newlines and turn common scraped HTML paragraphs into text."""
    normalized_text = book_text.replace("\r\n", "\n").replace("\r", "\n")
    if HTML_BLOCK_TAG_PATTERN.search(normalized_text):
        normalized_text = HTML_BLOCK_TAG_PATTERN.sub("\n", normalized_text)
        normalized_text = HTML_TAG_PATTERN.sub("", normalized_text)
    if HTML_ENTITY_PATTERN.search(normalized_text):
        normalized_text = html.unescape(normalized_text)
    return normalized_text


def heading_kind(line: str) -> str | None:
    if CHINESE_HEADING_PATTERN.match(line):
        return "structured"
    if SPECIAL_HEADING_PATTERN.match(line):
        return "structured"
    if ENGLISH_HEADING_PATTERN.match(line):
        return "structured"
    if BARE_NUMBER_HEADING_PATTERN.match(line):
        return "bare_number"
    return None


def heading_number(line: str) -> int | None:
    """Return an Arabic chapter number when it can be unambiguously read."""
    chinese_match = re.match(r"^\s*第\s*(\d+)\s*[章节回篇卷部集]", line)
    if chinese_match:
        return int(chinese_match.group(1))

    bare_number_match = BARE_NUMBER_HEADING_PATTERN.match(line)
    if bare_number_match:
        return int(bare_number_match.group(1))
    return None


def canonical_heading(line: str) -> str:
    """Normalize a title for comparing a table of contents with body headings."""
    title = re.sub(r"(?:[（(]\d+[）)])+$", "", line.strip())
    return re.sub(r"\s+", "", title)


def remove_table_of_contents(
    lines: list[str], heading_indexes: list[int]
) -> tuple[list[str], list[int]]:
    """Discard an initial title-only table of contents when the body repeats it."""
    if len(heading_indexes) < 4:
        return lines, heading_indexes

    first_title = canonical_heading(lines[heading_indexes[0]])
    for position, heading_index in enumerate(heading_indexes[1:], start=1):
        if canonical_heading(lines[heading_index]) != first_title:
            continue

        toc_indexes = heading_indexes[:position]
        entries_have_no_body = all(
            not any(line.strip() for line in lines[start + 1 : end])
            for start, end in zip(toc_indexes, toc_indexes[1:])
        )
        if position >= 3 and entries_have_no_body:
            body_lines = lines[heading_index:]
            return body_lines, [
                index - heading_index for index in heading_indexes[position:]
            ]
    return lines, heading_indexes


def select_heading_indexes(lines: list[str], heading_indexes: list[int]) -> list[int]:
    """Keep real chapter headings and reject standalone numeric footnotes."""
    kinds = [heading_kind(lines[index]) for index in heading_indexes]
    has_structured_heading = any(kind == "structured" for kind in kinds)
    selected_indexes: list[int] = []
    last_selected_index: int | None = None
    last_number: int | None = None

    for position, (heading_index, kind) in enumerate(zip(heading_indexes, kinds)):
        if kind == "structured":
            selected_indexes.append(heading_index)
            last_selected_index = heading_index
            last_number = heading_number(lines[heading_index])
            continue

        number = heading_number(lines[heading_index])
        previous_index = heading_indexes[position - 1] if position else None
        follows_selected_heading = previous_index == last_selected_index
        is_numeric_continuation = (
            number is not None
            and last_number is not None
            and number == last_number + 1
            and follows_selected_heading
        )
        starts_numeric_book = (
            not has_structured_heading
            and position + 1 < len(heading_indexes)
            and number is not None
            and heading_number(lines[heading_indexes[position + 1]]) == number + 1
        )
        if is_numeric_continuation or starts_numeric_book:
            selected_indexes.append(heading_index)
            last_selected_index = heading_index
            last_number = number

    return selected_indexes


def build_chapters(
    lines: list[str], heading_indexes: list[int]
) -> list[tuple[str, list[str]]]:
    chapters: list[tuple[str, list[str]]] = []
    introduction = lines[: heading_indexes[0]]
    introduction_text = [line for line in introduction if line.strip()]
    is_title_page = len(introduction_text) <= 2 and all(
        line.strip().startswith("《") and line.strip().endswith("》")
        for line in introduction_text
    )
    if introduction_text and not is_title_page:
        chapters.append(("Introduction", introduction))

    for position, start_index in enumerate(heading_indexes):
        end_index = (
            heading_indexes[position + 1]
            if position + 1 < len(heading_indexes)
            else len(lines)
        )
        chapters.append(
            (lines[start_index].strip(), lines[start_index + 1 : end_index])
        )
    return chapters


def looks_like_standard_title(line: str) -> bool:
    """Return whether a first line plausibly labels a blank-line chapter."""
    title = line.strip()
    if not title or len(title) > 100:
        return False
    if re.fullmatch(r"[0-9.:：'\- /]+", title):
        return False
    return not title.endswith(("。", "！", "？", "；", ".", "!", "?", ";"))


def split_standard_chapters(normalized_text: str) -> list[tuple[str, list[str]]] | None:
    """Recognise the old three-blank-line format only when it has title lines.

    Many ordinary TXT books use multiple blank lines between paragraphs.  The
    legacy fallback therefore applies only to consistently formatted blocks:
    every block starts with a short title followed by a blank line.
    """
    raw_chapters = [
        chapter
        for chapter in re.split(r"\n[\t ]*\n[\t ]*\n+", normalized_text)
        if chapter.strip()
    ]
    if len(raw_chapters) < 2:
        return None

    chapter_groups = [chapter.strip().split("\n") for chapter in raw_chapters]
    if not all(
        len(group) >= 3 and not group[1].strip() and looks_like_standard_title(group[0])
        for group in chapter_groups
    ):
        return None
    return [(group[0].strip(), group[2:]) for group in chapter_groups]


def read_book_text(input_file: pathlib.Path, encoding: str | None = None) -> str:
    """Read a TXT file while accommodating common encodings."""
    raw_text = input_file.read_bytes()
    if not raw_text:
        return ""

    if encoding is not None:
        return raw_text.decode(encoding)

    try:
        return raw_text.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass

    # GB18030 is the most common legacy encoding for Chinese TXT books.  Try it
    # before automatic detection, which can misidentify short Chinese excerpts.
    try:
        return raw_text.decode("gb18030")
    except UnicodeDecodeError:
        pass

    detected_text = from_bytes(raw_text).best()
    if detected_text is not None:
        return str(detected_text)

    # These encodings provide a final deterministic fallback when automatic
    # detection cannot make a confident choice.
    try:
        return raw_text.decode("gbk")
    except UnicodeDecodeError:
        pass

    # Some downloaded GBK files contain isolated invalid bytes.  Preserve the
    # readable text instead of letting a different legacy codec misdecode it.
    return raw_text.decode("gbk", errors="replace")


def split_chapters(book_text: str) -> list[tuple[str, list[str]]]:
    """Split text into titled chapters without discarding unrecognised text."""
    normalized_text = normalize_book_text(book_text)
    lines = normalized_text.split("\n")
    main_text_marker_index = next(
        (
            index
            for index, line in enumerate(lines)
            if MAIN_TEXT_MARKER_PATTERN.match(line)
        ),
        None,
    )
    if main_text_marker_index is not None:
        lines = lines[main_text_marker_index + 1 :]
        normalized_text = "\n".join(lines)

    heading_indexes = [index for index, line in enumerate(lines) if heading_kind(line)]
    lines, heading_indexes = remove_table_of_contents(lines, heading_indexes)
    heading_indexes = select_heading_indexes(lines, heading_indexes)
    # Explicit headings are more reliable than blank-line counts in scraped
    # books, where paragraph spacing often looks like a chapter separator.
    if len(heading_indexes) > 1 or (
        main_text_marker_index is not None and heading_indexes
    ):
        return build_chapters(lines, heading_indexes)

    standard_chapters = split_standard_chapters(normalized_text)
    if standard_chapters is not None:
        return standard_chapters

    if heading_indexes:
        return build_chapters(lines, heading_indexes)

    # A TXT file with no detectable chapter structure is still a valid book.
    return [("Contents", lines)]


class Txt2Epub:
    @staticmethod
    def create_epub(
        input_file: pathlib.Path,
        output_file: pathlib.Path | None = None,
        book_identifier: str | None = None,
        book_title: str | None = None,
        book_author: str | None = None,
        book_language: str | None = None,
        book_cover: pathlib.Path | None = None,
        text_encoding: str | None = None,
    ) -> bool:
        # Generate fields if not specified
        book_identifier = book_identifier or str(uuid.uuid4())
        book_title = book_title or input_file.stem
        book_author = book_author or "Unknown"

        # Read text from file
        book_text = read_book_text(input_file, text_encoding)

        # Detect book language if not specified
        if book_language is None:
            try:
                book_language = langdetect.detect(book_text)
            except langdetect.lang_detect_exception.LangDetectException:
                book_language = "en"

        chapters = split_chapters(book_text)

        # Convert cover image to JPEG
        book_cover_jpeg = None
        if book_cover is not None:
            book_cover_jpeg = convert_image_to_jpeg(book_cover)

        # Create new EPUB book
        book = epub.EpubBook()

        # Set book metadata
        book.set_identifier(book_identifier)
        book.set_title(book_title)
        book.add_author(book_author)
        book.set_language(book_language)
        if book_cover_jpeg is not None:
            book.set_cover("cover.jpg", book_cover_jpeg)
        # Create chapters
        spine: list[str | epub.EpubHtml] = ["nav"]
        toc = []
        for chapter_id, (chapter_title, chapter_content) in enumerate(chapters):
            # Write chapter title and contents
            chapter = epub.EpubHtml(
                title=chapter_title,
                file_name="chap_{:02d}.xhtml".format(chapter_id + 1),
                lang=book_language,
            )
            chapter.content = "<h1>{}</h1>{}".format(
                html.escape(chapter_title),
                "".join(
                    "<p>{}</p>".format(html.escape(line))
                    for line in chapter_content
                    if line.strip()
                ),
            )

            # Add chapter to the book and TOC
            book.add_item(chapter)
            spine.append(chapter)
            toc.append(chapter)

        # Update book spine and TOC
        book.spine = spine
        book.toc = toc

        # Add navigation files
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        # Generate new file path if not specified
        if output_file is None:
            output_file = input_file.with_suffix(".epub")

        # Create EPUB file
        return epub.write_epub(output_file, book)
