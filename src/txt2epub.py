"""TXT-to-EPUB conversion utilities."""

import html
import os
import pathlib
import re
import stat
import tempfile
import unicodedata
import uuid

import langdetect
from charset_normalizer import from_bytes
from ebooklib import epub

from .utils import convert_image_to_jpeg

try:
    langdetect.DetectorFactory.seed = 0
except AttributeError:
    # Kept for minimal test doubles and older langdetect releases.
    pass

# Chapter headings from Chinese web novels and common English ebook formats.
CHINESE_HEADING_PATTERN = re.compile(
    r"^\s*(?:[【\[]\s*)?第\s*[0-9零〇一二三四五六七八九十百千万兩两]+\s*[章节回篇卷部集]"
    r"(?=\s|[、】【\]，,:：.。!！?？\-—（(]|$).*$"
)
VOLUME_HEADING_PATTERN = re.compile(
    r"^\s*(?:[【\[]\s*)?(?:"
    r"第\s*[0-9零〇一二三四五六七八九十百千万兩两]+\s*卷"
    r"|0*\d{1,4}\s*卷"
    r"|卷\s*[0-9零〇一二三四五六七八九十百千万兩两]+"
    r"|[上中下]\s*卷"
    r").{0,100}$"
)
NUMERIC_SECTION_HEADING_PATTERN = re.compile(
    r"^\s*(?:[【\[]\s*)?第\s*(?:\d+|[零〇一二三四五六七八九十百千万兩两]+)\s*[部篇回]"
    r"(?=\s|[、】【\]，,:：.。!！?？\-—（(]|$).*$"
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
HTML_ENTITY_PATTERN = re.compile(
    r"&(?:#\d+|#x[0-9a-f]+|[a-z][a-z0-9]+);", re.IGNORECASE
)
DESCRIPTION_MARKER_PATTERN = re.compile(
    r"^\s*(?:[=－—\-_*#]{3,}\s*)?"
    r"(?:简介|内容简介|作品简介|书籍简介|文案|内容提要|内容梗概)"
    r"\s*(?:[=－—\-_*#]{3,})?\s*[:：]?\s*(.*)$"
)
FRONT_MATTER_SEPARATOR_PATTERN = re.compile(r"^\s*[=－—\-_*#]{3,}\s*$")
TITLE_FIELD_PATTERN = re.compile(
    r"(?:^|\s)(?:书名|书籍名称)\s*[:：]\s*(.+?)(?=\s*(?:作者|book_id|状态|评分|字数|章节|分类|标签)\s*[:：=]|$)",
    re.IGNORECASE,
)
AUTHOR_FIELD_PATTERN = re.compile(
    r"(?:^|\s)作者\s*[:：]\s*(.+?)(?=\s*(?:book_id|状态|评分|字数|章节|分类|标签)\s*[:：=]|$)",
    re.IGNORECASE,
)
CHARACTER_COUNT_FIELD_PATTERN = re.compile(r"(?:字数|总字数)\s*[:：]\s*([0-9,，]+)")
CHAPTER_COUNT_FIELD_PATTERN = re.compile(r"(?:章节数|章节)\s*[:：]\s*([0-9,，]+)")
# EPUB chapter files are XHTML. XML 1.0 forbids most control characters even
# after they have been HTML-escaped.
INVALID_XML_CHARACTER_PATTERN = re.compile(
    r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]"
)


def normalize_book_text(book_text: str) -> str:
    """Normalize newlines and turn common scraped HTML paragraphs into text."""
    normalized_text = book_text.replace("\r\n", "\n").replace("\r", "\n")
    if HTML_BLOCK_TAG_PATTERN.search(normalized_text):
        normalized_text = HTML_BLOCK_TAG_PATTERN.sub("\n", normalized_text)
    if HTML_ENTITY_PATTERN.search(normalized_text):
        normalized_text = html.unescape(normalized_text)
    return INVALID_XML_CHARACTER_PATTERN.sub("", normalized_text)


def heading_kind(line: str) -> str | None:
    if CHINESE_HEADING_PATTERN.match(line):
        return "structured"
    if VOLUME_HEADING_PATTERN.match(line):
        return "structured"
    if SPECIAL_HEADING_PATTERN.match(line):
        return "structured"
    if ENGLISH_HEADING_PATTERN.match(line):
        return "structured"
    if BARE_NUMBER_HEADING_PATTERN.match(line):
        return "bare_number"
    return None


def is_volume_heading(line: str) -> bool:
    """Return whether a heading introduces a volume rather than a chapter."""
    return bool(VOLUME_HEADING_PATTERN.match(line))


def is_numeric_section_heading(line: str) -> bool:
    """Return whether a numbered part, section, or episode can group chapters."""
    return bool(NUMERIC_SECTION_HEADING_PATTERN.match(line))


def heading_number(line: str) -> int | None:
    """Return an Arabic chapter number when it can be unambiguously read."""
    chinese_match = re.match(r"^\s*(?:[【\[]\s*)?第\s*(\d+)\s*[章节回篇卷部集]", line)
    if chinese_match:
        return int(chinese_match.group(1))

    volume_match = re.match(r"^\s*(?:[【\[]\s*)?(?:0*(\d+)\s*卷|卷\s*(\d+))", line)
    if volume_match:
        return int(volume_match.group(1) or volume_match.group(2))

    bare_number_match = BARE_NUMBER_HEADING_PATTERN.match(line)
    if bare_number_match:
        return int(bare_number_match.group(1))
    return None


def is_weak_bare_number_heading(line: str) -> bool:
    """Identify space-separated numeric lines, which can also be footnotes."""
    if not BARE_NUMBER_HEADING_PATTERN.match(line):
        return False
    return bool(re.match(r"^\s*0*\d{1,4}[\t ]+(?![章节回篇卷部集\[【(（])\S+", line))


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
    # A weak line such as ``2 note`` is often a footnote. When a proper
    # heading with the same number follows, discard it before evaluating the
    # number sequence so it cannot hide the real chapter.
    strong_numbers_after: set[int] = set()
    filtered_indexes_reversed: list[int] = []
    for heading_index in reversed(heading_indexes):
        line = lines[heading_index]
        kind = heading_kind(line)
        number = heading_number(line)
        if (
            kind == "bare_number"
            and number is not None
            and is_weak_bare_number_heading(line)
            and number in strong_numbers_after
        ):
            continue
        filtered_indexes_reversed.append(heading_index)
        if kind == "structured" and number is not None:
            strong_numbers_after.add(number)
        elif (
            kind == "bare_number"
            and number is not None
            and not is_weak_bare_number_heading(line)
        ):
            strong_numbers_after.add(number)
    heading_indexes = list(reversed(filtered_indexes_reversed))

    kinds = [heading_kind(lines[index]) for index in heading_indexes]
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
        previous_is_unnumbered_structure = (
            previous_index is not None
            and heading_kind(lines[previous_index]) == "structured"
            and (
                is_volume_heading(lines[previous_index])
                or is_numeric_section_heading(lines[previous_index])
                or heading_number(lines[previous_index]) is None
            )
        )
        starts_numeric_run = (
            position + 1 < len(heading_indexes)
            and number is not None
            and heading_number(lines[heading_indexes[position + 1]]) == number + 1
            and (position == 0 or previous_is_unnumbered_structure)
        )
        if is_numeric_continuation or starts_numeric_run:
            selected_indexes.append(heading_index)
            last_selected_index = heading_index
            last_number = number

    return selected_indexes


def build_chapter_entries(
    lines: list[str],
    heading_indexes: list[int],
    introduction_title: str = "Introduction",
) -> list[tuple[str, list[str], str | None, bool]]:
    """Build chapters and retain each chapter's optional parent volume."""
    chapters: list[tuple[str, list[str], str | None, bool]] = []
    introduction = lines[: heading_indexes[0]]
    introduction_text = [line for line in introduction if line.strip()]
    is_title_page = len(introduction_text) <= 2 and all(
        line.strip().startswith("《") and line.strip().endswith("》")
        for line in introduction_text
    )
    if introduction_text and not is_title_page:
        chapters.append((introduction_title, introduction, None, True))

    active_volume: str | None = None
    for position, start_index in enumerate(heading_indexes):
        end_index = (
            heading_indexes[position + 1]
            if position + 1 < len(heading_indexes)
            else len(lines)
        )
        title = lines[start_index].strip()
        content = lines[start_index + 1 : end_index]
        next_is_numeric_chapter = (
            position + 1 < len(heading_indexes)
            and heading_kind(lines[heading_indexes[position + 1]]) == "bare_number"
        )
        if is_volume_heading(title) or (
            is_numeric_section_heading(title) and next_is_numeric_chapter
        ):
            active_volume = title
            # A volume heading is navigation structure, not a blank reading
            # page. Preserve it as a chapter only if the source gives it prose.
            if any(line.strip() for line in content):
                chapters.append((title, content, active_volume, False))
            continue
        chapters.append((title, content, active_volume, False))
    return chapters


def build_chapters(
    lines: list[str],
    heading_indexes: list[int],
    introduction_title: str = "Introduction",
) -> list[tuple[str, list[str]]]:
    """Build reader-facing chapters without empty volume pages."""
    return [
        (title, content)
        for title, content, _, _ in build_chapter_entries(
            lines, heading_indexes, introduction_title
        )
    ]


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


def join_wrapped_lines(lines: list[str]) -> str:
    """Reflow visual line wraps while preserving spaces in Latin-script text."""
    reflowed_text = ""
    for line in lines:
        stripped_line = line.strip()
        if not reflowed_text:
            reflowed_text = stripped_line
        elif (
            re.match(r"[A-Za-z0-9\"'“‘([{—-]", stripped_line)
            and re.search(r"[A-Za-z0-9][A-Za-z0-9\s,.;:!?\"'\)\]]*$", reflowed_text)
            and not reflowed_text.endswith("-")
        ):
            reflowed_text += f" {stripped_line}"
        else:
            reflowed_text += stripped_line
    return reflowed_text


def render_chapter_content(lines: list[str], preserve_line_breaks: bool = False) -> str:
    """Render TXT lines as XHTML while retaining paragraph structure.

    TXT files commonly wrap ordinary prose to a fixed screen width. Those
    visual wraps are reflowed by default; callers can preserve every source
    line break for poetry or preformatted text.
    """
    paragraphs: list[str] = []
    text_lines: list[str] = []
    blank_line_count = 0

    def flush_paragraph() -> None:
        nonlocal text_lines
        if text_lines:
            if preserve_line_breaks:
                paragraph_text = "<br/>".join(html.escape(line) for line in text_lines)
            else:
                paragraph_text = html.escape(join_wrapped_lines(text_lines))
            paragraphs.append(f"<p>{paragraph_text}</p>")
            text_lines = []

    for line in lines:
        if line.strip():
            if blank_line_count > 1:
                paragraphs.extend(
                    '<p class="blank">&#160;</p>' for _ in range(blank_line_count - 1)
                )
            blank_line_count = 0
            text_lines.append(line)
            continue

        flush_paragraph()
        blank_line_count += 1

    flush_paragraph()
    return "".join(paragraphs)


def render_title_page(
    book_title: str,
    book_author: str,
    character_count: int,
    chapter_count: int,
    is_chinese_book: bool,
    book_description: str | None = None,
    preserve_line_breaks: bool = False,
) -> str:
    """Render a front title page without adding it to the navigation table."""
    if is_chinese_book:
        display_title = book_title
        if not (display_title.startswith("《") and display_title.endswith("》")):
            display_title = f"《{display_title}》"
        metadata = (
            f"<p>作者：{html.escape(book_author)}</p>"
            f"<p>字数：{character_count}</p>"
            f"<p>章节：{chapter_count}</p>"
        )
    else:
        display_title = book_title
        metadata = (
            f"<p>Author: {html.escape(book_author)}</p>"
            f"<p>Characters: {character_count}</p>"
            f"<p>Chapters: {chapter_count}</p>"
        )
    description = book_description.strip() if book_description else ""
    description_html = ""
    if description:
        description_label = "简介：" if is_chinese_book else "Description:"
        description_html = (
            f"<h2>{description_label}</h2>"
            f"{render_chapter_content(description.splitlines(), preserve_line_breaks)}"
        )
    return (
        '<section epub:type="titlepage">'
        f"<h1>{html.escape(display_title)}</h1>"
        f"{metadata}"
        f"{description_html}"
        "</section>"
    )


def render_cover_page() -> str:
    """Render the optional cover as the first page in the reading order."""
    return '<section epub:type="cover"><img src="cover.jpg" alt="Cover"/></section>'


def extract_front_matter(
    book_text: str,
) -> tuple[str | None, str | None, str | None, int | None, int | None, str]:
    """Extract common TXT header metadata and return the remaining body text."""
    title: str | None = None
    author: str | None = None
    description: str | None = None
    character_count: int | None = None
    chapter_count: int | None = None
    all_lines = book_text.splitlines()
    lines = all_lines[:200]
    body_start_index: int | None = None

    for line in lines:
        if title is None:
            title_match = TITLE_FIELD_PATTERN.search(line)
            if title_match:
                title = title_match.group(1).strip()
        if author is None:
            author_match = AUTHOR_FIELD_PATTERN.search(line)
            if author_match:
                author = author_match.group(1).strip()
        if character_count is None:
            character_count_match = CHARACTER_COUNT_FIELD_PATTERN.search(line)
            if character_count_match:
                character_count = int(
                    character_count_match.group(1).replace(",", "").replace("，", "")
                )
        if chapter_count is None:
            chapter_count_match = CHAPTER_COUNT_FIELD_PATTERN.search(line)
            if chapter_count_match:
                chapter_count = int(
                    chapter_count_match.group(1).replace(",", "").replace("，", "")
                )

    for start_index, line in enumerate(lines):
        marker_match = DESCRIPTION_MARKER_PATTERN.match(line)
        if not marker_match:
            continue

        description_lines = [marker_match.group(1).strip()]
        for next_index, next_line in enumerate(
            lines[start_index + 1 :], start_index + 1
        ):
            if FRONT_MATTER_SEPARATOR_PATTERN.match(next_line):
                body_start_index = next_index + 1
                break
            if heading_kind(next_line):
                body_start_index = next_index
                break
            if MAIN_TEXT_MARKER_PATTERN.match(next_line):
                body_start_index = next_index + 1
                break
            description_lines.append(next_line.rstrip())
        description = "\n".join(description_lines).strip() or None
        break

    has_front_matter = any(
        value is not None
        for value in (title, author, description, character_count, chapter_count)
    )
    if has_front_matter and body_start_index is None:
        for index, line in enumerate(lines):
            if FRONT_MATTER_SEPARATOR_PATTERN.match(line):
                body_start_index = index + 1
                break
            if heading_kind(line):
                body_start_index = index
                break
            if MAIN_TEXT_MARKER_PATTERN.match(line):
                body_start_index = index + 1
                break

    if body_start_index is None:
        body_text = book_text
    else:
        while (
            body_start_index < len(all_lines)
            and not all_lines[body_start_index].strip()
        ):
            body_start_index += 1
        body_text = "\n".join(all_lines[body_start_index:])

    return (
        title or None,
        author or None,
        description,
        character_count,
        chapter_count,
        body_text,
    )


def _cjk_ideograph_ratio(text: str) -> float:
    """Return the fraction of ``text`` made of CJK Unified Ideographs."""
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if "CJK UNIFIED IDEOGRAPH" in unicodedata.name(ch, ""))
    return cjk / len(text)


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

    # charset_normalizer frequently ranks the Korean/Japanese encodings
    # (cp949, cp932, euc-kr, ...) ahead of GBK for Simplified Chinese sources
    # because they share large portions of the byte space. That produces Korean
    # mojibake instead of the intended Chinese text. We re-rank its candidates by
    # the proportion of decoded CJK ideographs and give a small preference to
    # Chinese-capable encodings, then accept the detection only when a Chinese
    # encoding actually wins.
    matches = list(from_bytes(raw_text))
    if matches:
        chinese_encodings = {"gb18030", "gbk", "gb2312", "big5"}

        ranked = []
        for match in matches:
            try:
                decoded = str(match)
            except UnicodeDecodeError:
                continue
            enc = (match.encoding or "").lower()
            score = _cjk_ideograph_ratio(decoded) + (
                0.1 if enc in chinese_encodings else 0.0
            )
            ranked.append((score, enc, decoded))
        ranked.sort(reverse=True)

        if ranked and ranked[0][1] in chinese_encodings:
            return ranked[0][2]

    # No confident Chinese decoding from detection: fall back to deterministic
    # legacy codecs. Chinese encodings are tried first because this converter
    # targets Chinese novels; the trailing gbk-with-replace guarantees readable
    # text even for files that contain isolated invalid bytes.
    for fallback_encoding in ("gb18030", "gbk"):
        try:
            return raw_text.decode(fallback_encoding)
        except UnicodeDecodeError:
            continue
    try:
        return raw_text.decode("big5")
    except UnicodeDecodeError:
        pass

    # Some downloaded GBK files contain isolated invalid bytes.  Preserve the
    # readable text instead of letting a different legacy codec misdecode it.
    return raw_text.decode("gbk", errors="replace")


def split_chapter_entries(
    book_text: str,
    introduction_title: str = "Introduction",
    contents_title: str = "Text",
) -> list[tuple[str, list[str], str | None, bool]]:
    """Split text into chapters while retaining optional volume membership."""
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
        return build_chapter_entries(lines, heading_indexes, introduction_title)

    standard_chapters = split_standard_chapters(normalized_text)
    if standard_chapters is not None:
        return [(title, content, None, False) for title, content in standard_chapters]

    if heading_indexes:
        return build_chapter_entries(lines, heading_indexes, introduction_title)

    # A TXT file with no detectable chapter structure is still a valid book.
    return [(contents_title, lines, None, False)]


def split_chapters(
    book_text: str,
    introduction_title: str = "Introduction",
    contents_title: str = "Text",
) -> list[tuple[str, list[str]]]:
    """Split text into reader-facing chapters without empty volume pages."""
    return [
        (title, content)
        for title, content, _, _ in split_chapter_entries(
            book_text, introduction_title, contents_title
        )
    ]


def count_content_chapters(
    chapter_entries: list[tuple[str, list[str], str | None, bool]],
) -> int:
    """Count reader chapters while excluding a generated introduction."""
    return sum(
        not is_generated_introduction
        for _, _, _, is_generated_introduction in chapter_entries
    )


def build_table_of_contents(
    toc_items: list[tuple[str, str | None, epub.EpubHtml]],
) -> list[
    epub.EpubHtml | tuple[epub.Section, tuple[epub.EpubHtml, ...]] | epub.Section
]:
    """Build a flat or volume-grouped navigation tree without duplicate volumes."""
    toc: list[
        epub.EpubHtml | tuple[epub.Section, tuple[epub.EpubHtml, ...]] | epub.Section
    ] = []
    current_volume: str | None = None
    volume_intro: epub.EpubHtml | None = None
    volume_chapters: list[epub.EpubHtml] = []

    def flush_volume() -> None:
        if current_volume is None:
            toc.extend(volume_chapters)
            return
        section = epub.Section(
            current_volume,
            href=volume_intro.file_name if volume_intro is not None else None,
        )
        if volume_chapters:
            toc.append((section, tuple(volume_chapters)))
        else:
            toc.append(section)

    for title, volume_title, chapter in toc_items:
        if volume_title != current_volume:
            flush_volume()
            current_volume = volume_title
            volume_intro = None
            volume_chapters = []
        if volume_title is not None and title == volume_title and volume_intro is None:
            volume_intro = chapter
        else:
            volume_chapters.append(chapter)
    flush_volume()
    return toc


def write_epub_atomically(output_file: pathlib.Path, book: epub.EpubBook) -> bool:
    """Write an EPUB to a sibling temporary file before replacing the target."""
    existing_mode = (
        stat.S_IMODE(output_file.stat().st_mode) if output_file.exists() else None
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_file.stem}.", suffix=".tmp", dir=output_file.parent
    )
    os.close(descriptor)
    temporary_file = pathlib.Path(temporary_name)
    try:
        if epub.write_epub(temporary_file, book) is False:
            return False
        os.replace(temporary_file, output_file)
        if existing_mode is not None and os.name != "nt":
            os.chmod(output_file, existing_mode)
        return True
    finally:
        temporary_file.unlink(missing_ok=True)


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
        overwrite: bool = False,
        preserve_line_breaks: bool = False,
        book_description: str | None = None,
    ) -> bool:
        # Generate fields if not specified
        book_identifier = INVALID_XML_CHARACTER_PATTERN.sub(
            "", book_identifier or str(uuid.uuid4())
        )
        if output_file is None:
            output_file = input_file.with_suffix(".epub")
        if input_file.resolve() == output_file.resolve():
            raise ValueError("Output file must not be the same as the input file")
        if output_file.exists() and not overwrite:
            raise FileExistsError(
                f"Output file already exists: {output_file}; "
                "pass overwrite=True to replace it"
            )

        # Normalize before extracting header metadata so both content and EPUB
        # metadata obey the same XML character rules.
        book_text = normalize_book_text(read_book_text(input_file, text_encoding))
        (
            detected_title,
            detected_author,
            detected_description,
            detected_character_count,
            detected_chapter_count,
            body_text,
        ) = extract_front_matter(book_text)
        book_title = INVALID_XML_CHARACTER_PATTERN.sub(
            "", book_title or detected_title or input_file.stem
        ).strip()
        book_author = INVALID_XML_CHARACTER_PATTERN.sub(
            "", book_author or detected_author or "Unknown"
        ).strip()
        book_description = book_description or detected_description
        if book_description is not None:
            book_description = (
                INVALID_XML_CHARACTER_PATTERN.sub("", book_description).strip() or None
            )

        # Detect book language if not specified
        if book_language is None:
            try:
                book_language = langdetect.detect(body_text)
            except langdetect.lang_detect_exception.LangDetectException:
                book_language = "en"

        is_chinese_book = book_language.lower().startswith("zh")
        introduction_title = "前言" if is_chinese_book else "Introduction"
        contents_title = "正文" if is_chinese_book else "Text"
        chapter_entries = split_chapter_entries(
            body_text, introduction_title, contents_title
        )

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
        if book_description and book_description.strip():
            book.add_metadata("DC", "description", book_description.strip())

        # A supplied cover is the first page; omit it entirely when no cover
        # file was requested.
        spine: list[str | epub.EpubHtml] = []
        if book_cover_jpeg is not None:
            book.set_cover("cover.jpg", book_cover_jpeg, create_page=False)
            cover_page = epub.EpubHtml(
                title="Cover", file_name="cover.xhtml", lang=book_language
            )
            cover_page.content = render_cover_page()
            book.add_item(cover_page)
            spine.append(cover_page)

        # The book information page follows the optional cover and does not
        # appear in the navigation table.
        character_count = detected_character_count or sum(
            not character.isspace() for character in body_text
        )
        chapter_count = detected_chapter_count or count_content_chapters(
            chapter_entries
        )
        title_page = epub.EpubHtml(
            title="Title Page", file_name="title.xhtml", lang=book_language
        )
        title_page.content = render_title_page(
            book_title,
            book_author,
            character_count,
            chapter_count,
            is_chinese_book,
            book_description,
            preserve_line_breaks,
        )
        book.add_item(title_page)
        spine.append(title_page)

        # The navigation document is included in the EPUB package but is not a
        # reading-order page, so readers do not open to a visible directory.
        toc_items: list[tuple[str, str | None, epub.EpubHtml]] = []
        for chapter_id, (chapter_title, chapter_content, volume_title, _) in enumerate(
            chapter_entries
        ):
            # Write chapter title and contents
            chapter = epub.EpubHtml(
                title=chapter_title,
                file_name=f"chap_{chapter_id + 1:02d}.xhtml",
                lang=book_language,
            )
            chapter_html = render_chapter_content(
                chapter_content, preserve_line_breaks=preserve_line_breaks
            )
            chapter.content = f"<h1>{html.escape(chapter_title)}</h1>{chapter_html}"

            # Add chapter to the book and TOC
            book.add_item(chapter)
            spine.append(chapter)
            toc_items.append((chapter_title, volume_title, chapter))

        toc = build_table_of_contents(toc_items)

        # Update book spine and TOC
        book.spine = spine
        book.toc = toc

        # Add navigation files
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        # Create EPUB file without exposing an existing target to partial writes.
        return write_epub_atomically(output_file, book)
