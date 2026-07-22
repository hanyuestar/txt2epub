import pathlib
import tempfile
import unittest

from src.txt2epub import heading_kind, read_book_text, split_chapters


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

    def test_detects_special_headings_including_extras(self):
        chapters = split_chapters(
            "序章\n正文一\n第1章 开始\n正文二\n番外一：小故事\n正文三\n后记\n正文四"
        )

        self.assertEqual(
            [title for title, _ in chapters],
            ["序章", "第1章 开始", "番外一：小故事", "后记"],
        )

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
            [("Contents", ["这是一段普通正文。", "", "", "这还是另一段普通正文。"])],
        )

    def test_turns_scraped_html_into_text_paragraphs(self):
        chapters = split_chapters(
            "========正文========\n第一回 开始\n<p>第一段</p><p>第二段</p>"
        )

        self.assertEqual(chapters, [("第一回 开始", ["", "第一段", "", "第二段", ""])])

    def test_decodes_html_entities_without_html_tags(self):
        chapters = split_chapters("第1章 开始\n甲&amp;乙\n第2章 继续\n正文")

        self.assertEqual(chapters[0], ("第1章 开始", ["甲&乙"]))

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

    def test_keeps_readable_text_when_a_gbk_file_has_a_bad_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            text_path = pathlib.Path(directory) / "book.txt"
            text_path.write_bytes("第1章 内容".encode("gbk") + b"\x80")

            self.assertTrue(read_book_text(text_path).startswith("第1章 内容"))
