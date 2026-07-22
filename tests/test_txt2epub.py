import io
import os
import pathlib
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from scripts.check_txt_compatibility import read_text as read_text_for_scan
from src import __main__ as cli
from src.txt2epub import (
    Txt2Epub,
    build_table_of_contents,
    count_content_chapters,
    extract_front_matter,
    heading_kind,
    normalize_book_text,
    read_book_text,
    render_chapter_content,
    render_cover_page,
    render_title_page,
    split_chapter_entries,
    split_chapters,
    write_epub_atomically,
)
from src.utils import convert_image_to_jpeg


class TxtCompatibilityTests(unittest.TestCase):
    def test_skips_a_repeated_table_of_contents(self):
        chapters = split_chapters(
            "校注前言\n\n"
            "第一回 桃园结义\n\n第二回 董卓进京\n\n第三回 群雄会盟\n\n"
            "第一回 桃园结义（1）\n正文一\n\n"
            "第二回 董卓进京\n正文二\n\n"
            "第三回 群雄会盟\n正文三"
        )

        self.assertEqual(
            [title for title, _ in chapters],
            ["第一回 桃园结义（1）", "第二回 董卓进京", "第三回 群雄会盟"],
        )

    def test_filters_numeric_footnotes_but_keeps_numbered_chapters(self):
        chapters = split_chapters(
            "第1章 开始\n正文一\n01 脚注一\n02 脚注二\n"
            "第2章 继续\n正文二\n3、结尾\n正文三"
        )

        self.assertEqual(
            [title for title, _ in chapters],
            ["第1章 开始", "第2章 继续", "3、结尾"],
        )

    def test_numeric_footnote_cannot_hide_a_later_real_chapter(self):
        chapters = split_chapters(
            "1. Chapter one\n正文一\n2 note\n脚注内容\n2. Chapter two\n正文二"
        )

        self.assertEqual(
            [title for title, _ in chapters], ["1. Chapter one", "2. Chapter two"]
        )

    def test_numeric_footnote_cannot_hide_a_structured_chapter(self):
        chapters = split_chapters(
            "第1章 Start\n正文\n2 note\n脚注内容\n第2章 Next\n正文"
        )

        self.assertEqual(
            [title for title, _ in chapters], ["第1章 Start", "第2章 Next"]
        )

    def test_detects_a_title_immediately_after_the_chapter_number(self):
        chapters = split_chapters("第134章【黑衣夫人】参观\n正文\n第135章 下一章\n正文")

        self.assertEqual(
            [title for title, _ in chapters],
            ["第134章【黑衣夫人】参观", "第135章 下一章"],
        )

    def test_detects_a_numbered_title_without_the_prefix(self):
        chapters = split_chapters("第460章 前一章\n正文\n461章 下一章\n正文")

        self.assertEqual(
            [title for title, _ in chapters],
            ["第460章 前一章", "461章 下一章"],
        )

    def test_detects_zero_padded_bracketed_numbered_titles(self):
        chapters = split_chapters("001 [标题一]\n正文一\n002 [标题二]\n正文二")

        self.assertEqual(
            [title for title, _ in chapters],
            ["001 [标题一]", "002 [标题二]"],
        )

    def test_starts_a_numeric_chapter_run_after_an_unnumbered_volume(self):
        chapter_entries = split_chapter_entries(
            "第一卷\n001 First\n正文一\n002 Second\n正文二"
        )

        self.assertEqual(
            [(title, volume) for title, _, volume, _ in chapter_entries],
            [("001 First", "第一卷"), ("002 Second", "第一卷")],
        )

    def test_starts_a_numeric_chapter_run_after_a_real_prologue(self):
        chapters = split_chapters("序章\n正文\n001 First\n正文一\n002 Second\n正文二")

        self.assertEqual(
            [title for title, _ in chapters], ["序章", "001 First", "002 Second"]
        )

    def test_starts_a_numeric_chapter_run_after_a_numbered_section(self):
        for section_title in (
            "第1部 开始",
            "第1篇 开始",
            "第1回 开始",
            "第一部 开始",
            "第一篇 开始",
            "第一回 开始",
        ):
            with self.subTest(section_title=section_title):
                chapter_entries = split_chapter_entries(
                    f"{section_title}\n001 First\n正文一\n002 Second\n正文二"
                )

                self.assertEqual(
                    [(title, volume) for title, _, volume, _ in chapter_entries],
                    [("001 First", section_title), ("002 Second", section_title)],
                )

    def test_keeps_ordinary_numbered_episode_headings_as_chapters(self):
        chapters = split_chapters("第1回 开始\n正文一\n第2回 继续\n正文二")

        self.assertEqual([title for title, _ in chapters], ["第1回 开始", "第2回 继续"])

    def test_detects_special_headings_including_extras(self):
        chapters = split_chapters(
            "序章\n正文一\n第1章 开始\n正文二\n番外一：小故事\n正文三\n后记\n正文四"
        )

        self.assertEqual(
            [title for title, _ in chapters],
            ["序章", "第1章 开始", "番外一：小故事", "后记"],
        )

    def test_detects_bracketed_volume_headings(self):
        chapter_entries = split_chapter_entries(
            "【第一卷：重新开始】\n第1章 开始\n正文\n"
            "【第二卷：游戏入侵】\n第2章 继续\n正文"
        )

        self.assertEqual(
            [(title, volume) for title, _, volume, _ in chapter_entries],
            [
                ("第1章 开始", "【第一卷：重新开始】"),
                ("第2章 继续", "【第二卷：游戏入侵】"),
            ],
        )
        self.assertEqual(count_content_chapters(chapter_entries), 2)
        self.assertEqual(heading_kind("卷三：终局"), "structured")
        self.assertEqual(heading_kind("上卷"), "structured")
        self.assertEqual(heading_kind("001卷重新开始"), "structured")
        self.assertEqual(heading_kind("第一卷重新开始"), "structured")

    def test_counts_a_real_preface_heading_as_a_chapter(self):
        chapter_entries = split_chapter_entries("前言\n正文\n第1章 开始\n正文", "前言")

        self.assertEqual(count_content_chapters(chapter_entries), 2)

    def test_links_a_volume_description_from_its_single_navigation_section(self):
        chapter_entries = split_chapter_entries("第一卷\n卷序正文\n第1章 开始\n正文")
        self.assertEqual(
            [(title, volume) for title, _, volume, _ in chapter_entries],
            [("第一卷", "第一卷"), ("第1章 开始", "第一卷")],
        )

        class FakeSection:
            def __init__(self, title, href=None):
                self.title = title
                self.href = href

        class FakeChapter:
            def __init__(self, file_name):
                self.file_name = file_name

        volume_page = FakeChapter("volume.xhtml")
        chapter_page = FakeChapter("chapter.xhtml")
        with patch.object(
            build_table_of_contents.__globals__["epub"], "Section", FakeSection
        ):
            toc = build_table_of_contents(
                [
                    ("第一卷", "第一卷", volume_page),
                    ("第1章 开始", "第一卷", chapter_page),
                ]
            )

        self.assertEqual(len(toc), 1)
        section, children = toc[0]
        self.assertEqual((section.title, section.href), ("第一卷", "volume.xhtml"))
        self.assertEqual(children, (chapter_page,))

    def test_rejects_decimal_numbers_and_timestamps_as_titles(self):
        self.assertIsNone(heading_kind("45.761871"))
        self.assertIsNone(heading_kind("10:20'10 \"记录"))
        self.assertEqual(heading_kind("1. 开始"), "bare_number")

    def test_only_uses_blank_line_chapter_format_with_consistent_titles(self):
        chapters = split_chapters("标题一\n\n正文一\n\n\n标题二\n\n正文二")

        self.assertEqual([title for title, _ in chapters], ["标题一", "标题二"])

    def test_keeps_unstructured_paragraphs_in_one_chapter(self):
        chapters = split_chapters("这是一段普通正文。\n\n\n这还是另一段普通正文。")

        self.assertEqual(
            chapters,
            [("Text", ["这是一段普通正文。", "", "", "这还是另一段普通正文。"])],
        )

    def test_turns_scraped_html_into_text_paragraphs(self):
        chapters = split_chapters(
            "========正文========\n第一回 开始\n<p>第一段</p><p>第二段</p>"
        )

        self.assertEqual(chapters, [("第一回 开始", ["", "第一段", "", "第二段", ""])])

    def test_keeps_angle_bracket_text_when_normalizing_html_blocks(self):
        text = normalize_book_text("<p>A < 2 > B</p>\n<p>Use <example> in prose</p>")

        self.assertIn("A < 2 > B", text)
        self.assertIn("Use <example> in prose", text)

    def test_decodes_html_entities_without_html_tags(self):
        chapters = split_chapters("第1章 开始\n甲&amp;乙\n第2章 继续\n正文")

        self.assertEqual(chapters[0], ("第1章 开始", ["甲&乙"]))

    def test_removes_xml_illegal_control_characters(self):
        self.assertEqual(normalize_book_text("甲\x01乙\n丙"), "甲乙\n丙")

    def test_reflows_wrapped_prose_and_keeps_extra_blank_lines(self):
        content = render_chapter_content(
            ["第一行", "第二行", "", "第三行", "", "", "第四行"]
        )

        self.assertEqual(
            content,
            (
                "<p>第一行第二行</p><p>第三行</p>"
                '<p class="blank">&#160;</p><p>第四行</p>'
            ),
        )

    def test_reflow_inserts_spaces_for_latin_wrapped_prose(self):
        self.assertEqual(
            render_chapter_content(["Line one", "Line two"]),
            "<p>Line one Line two</p>",
        )

    def test_reflow_inserts_spaces_before_latin_continuation_punctuation(self):
        self.assertEqual(
            render_chapter_content(["A sentence", "(continued)", "—still continuing"]),
            "<p>A sentence (continued) —still continuing</p>",
        )

    def test_can_preserve_source_line_breaks(self):
        self.assertEqual(
            render_chapter_content(["第一行", "第二行"], preserve_line_breaks=True),
            "<p>第一行<br/>第二行</p>",
        )

    def test_reads_gb18030_text(self):
        with tempfile.TemporaryDirectory() as directory:
            text_path = pathlib.Path(directory) / "book.txt"
            text_path.write_bytes("第1章 内容".encode("gb18030"))

            self.assertEqual(read_book_text(text_path), "第1章 内容")

    def test_reads_gbk_text(self):
        with tempfile.TemporaryDirectory() as directory:
            text_path = pathlib.Path(directory) / "book.txt"
            text_path.write_bytes("第1章 内容".encode("gbk"))

            self.assertEqual(read_book_text(text_path), "第1章 内容")

    def test_reads_big5_text_without_gb18030_mojibake(self):
        with tempfile.TemporaryDirectory() as directory:
            text_path = pathlib.Path(directory) / "book.txt"
            text_path.write_bytes("第一章 開始\n內容".encode("big5"))

            self.assertEqual(read_book_text(text_path), "第一章 開始\n內容")

    def test_compatibility_scan_reads_big5_without_gb18030_mojibake(self):
        with tempfile.TemporaryDirectory() as directory:
            text_path = pathlib.Path(directory) / "book.txt"
            text_path.write_bytes("第一章 開始\n內容".encode("big5"))

            self.assertEqual(
                read_text_for_scan(text_path), ("第一章 開始\n內容", "big5")
            )

    def test_keeps_readable_text_when_a_gbk_file_has_a_bad_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            text_path = pathlib.Path(directory) / "book.txt"
            text_path.write_bytes("第1章 内容".encode("gbk") + b"\x80")

            self.assertTrue(read_book_text(text_path).startswith("第1章 内容"))

    def test_refuses_to_overwrite_the_input_file(self):
        with tempfile.TemporaryDirectory() as directory:
            text_path = pathlib.Path(directory) / "book.txt"
            text_path.write_text("正文", encoding="utf-8")

            with self.assertRaises(ValueError):
                Txt2Epub.create_epub(text_path, text_path)

    def test_public_api_refuses_existing_output_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = pathlib.Path(directory) / "book.txt"
            output_path = pathlib.Path(directory) / "book.epub"
            source_path.write_text("正文", encoding="utf-8")
            output_path.write_bytes(b"existing epub")

            with self.assertRaises(FileExistsError):
                Txt2Epub.create_epub(source_path, output_path)

    def test_atomic_write_keeps_existing_epub_when_writing_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = pathlib.Path(directory) / "book.epub"
            output_path.write_bytes(b"existing epub")

            with patch.object(
                write_epub_atomically.__globals__["epub"],
                "write_epub",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaises(OSError):
                    write_epub_atomically(output_path, object())

            self.assertEqual(output_path.read_bytes(), b"existing epub")
            self.assertEqual(list(pathlib.Path(directory).glob(".book.*.tmp")), [])

    @unittest.skipIf(os.name == "nt", "POSIX permission preservation")
    def test_atomic_write_preserves_existing_posix_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = pathlib.Path(directory) / "book.epub"
            output_path.write_bytes(b"existing epub")
            output_path.chmod(0o640)

            def write_temporary_epub(path, book):
                pathlib.Path(path).write_bytes(b"new epub")
                return True

            with patch.object(
                write_epub_atomically.__globals__["epub"],
                "write_epub",
                side_effect=write_temporary_epub,
            ):
                self.assertTrue(write_epub_atomically(output_path, object()))

            self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o640)

    def test_uses_a_chinese_title_for_a_chinese_introduction(self):
        chapters = split_chapters("封面\n第1章 正文", introduction_title="前言")

        self.assertEqual(chapters[0][0], "前言")

    def test_uses_a_chinese_title_for_unstructured_chinese_text(self):
        chapters = split_chapters("没有章节的正文", contents_title="正文")

        self.assertEqual(chapters[0][0], "正文")

    def test_extracts_front_matter_description_and_book_metadata(self):
        title, author, description, character_count, chapter_count, body_text = (
            extract_front_matter(
                "书名：游戏入侵 作者：猫不秃 book_id=123\n"
                "状态：完结\n字数：3128935\n章节：1458\n"
                "简介：\n第一段简介\n第二段简介\n========\n"
                "【第一卷：重新开始】"
            )
        )

        self.assertEqual((title, author), ("游戏入侵", "猫不秃"))
        self.assertEqual(description, "第一段简介\n第二段简介")
        self.assertEqual((character_count, chapter_count), (3128935, 1458))
        self.assertEqual(body_text, "【第一卷：重新开始】")

    def test_extracts_description_between_decorated_markers(self):
        title, author, description, character_count, chapter_count, body_text = (
            extract_front_matter(
                "书名：三国演义\n作者：罗贯中\n字数：647773\n章节数：162\n"
                "========简介========\n"
                "《三国演义》反映了丰富的历史内容。\n"
                "========正文========\n"
                "第一回 宴桃园豪杰三结义"
            )
        )

        self.assertEqual((title, author), ("三国演义", "罗贯中"))
        self.assertEqual(description, "《三国演义》反映了丰富的历史内容。")
        self.assertEqual((character_count, chapter_count), (647773, 162))
        self.assertEqual(body_text, "第一回 宴桃园豪杰三结义")

    def test_stops_description_at_an_unbracketed_volume_without_a_separator(self):
        _, _, description, _, _, body_text = extract_front_matter(
            "简介：\n第一段简介\n第二段简介\n001卷重新开始\n第1章 正文"
        )

        self.assertEqual(description, "第一段简介\n第二段简介")
        self.assertEqual(body_text, "001卷重新开始\n第1章 正文")

    def test_strips_detected_header_before_chapter_splitting(self):
        *_, body_text = extract_front_matter(
            "书名：测试书 作者：作者\n简介：\n简介内容\n========\n第1章 正文\n章节内容"
        )

        self.assertEqual(
            [title for title, _ in split_chapters(body_text)], ["第1章 正文"]
        )

    def test_xml_control_characters_are_removed_before_header_extraction(self):
        normalized_text = normalize_book_text(
            "书名：测\x01试 作者：作\x01者\n第1章 正文"
        )
        title, author, _, _, _, _ = extract_front_matter(normalized_text)

        self.assertEqual((title, author), ("测试", "作者"))

    def test_renders_book_metadata_for_a_chinese_title_page(self):
        self.assertEqual(
            render_title_page("游戏入侵", "猫不秃", 3128935, 1458, True),
            (
                '<section epub:type="titlepage"><h1>《游戏入侵》</h1>'
                "<p>作者：猫不秃</p><p>字数：3128935</p><p>章节：1458</p></section>"
            ),
        )

    def test_renders_a_description_in_the_title_page(self):
        title_page = render_title_page(
            "游戏入侵", "猫不秃", 1, 1, True, "第一段\n第二段"
        )

        self.assertIn("<h2>简介：</h2>", title_page)
        self.assertIn("<p>第一段第二段</p>", title_page)

    def test_preserves_line_breaks_in_the_title_page_description(self):
        title_page = render_title_page(
            "游戏入侵", "猫不秃", 1, 1, True, "line one\nline two", True
        )

        self.assertIn("<p>line one<br/>line two</p>", title_page)

    def test_renders_an_escaped_cover_page(self):
        self.assertEqual(
            render_cover_page(),
            '<section epub:type="cover"><img src="cover.jpg" alt="Cover"/></section>',
        )

    def test_applies_exif_orientation_to_a_cover_image(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = pathlib.Path(directory) / "cover.jpg"
            image = Image.new("RGB", (2, 4), "red")
            exif = image.getexif()
            exif[274] = 6
            image.save(image_path, exif=exif)

            with Image.open(io.BytesIO(convert_image_to_jpeg(image_path))) as converted:
                self.assertEqual(converted.size, (4, 2))

    def test_command_line_rejects_an_input_output_path_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            text_path = pathlib.Path(directory) / "book.txt"
            text_path.write_text("正文", encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                [
                    "txt2epub",
                    "convert",
                    "--input",
                    str(text_path),
                    "--output",
                    str(text_path),
                ],
            ):
                with self.assertRaises(SystemExit) as error:
                    cli.main()

            self.assertEqual(error.exception.code, 2)
