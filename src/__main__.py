"""Command-line entry point."""

import argparse
import pathlib
import sys

from .txt2epub import Txt2Epub, read_book_text


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="txt2epub",
        description="TXT to EPUB converter.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    subparsers = parser.add_subparsers(
        help="Use [subcommand] -h to print help for each subcommand", dest="command"
    )

    convert_parser = subparsers.add_parser(
        "convert", help="Convert a TXT file to an EPUB file"
    )
    convert_parser.add_argument(
        "-i",
        "--input",
        type=pathlib.Path,
        help="Path to the input txt file",
        required=True,
    )
    convert_parser.add_argument(
        "-o",
        "--output",
        type=pathlib.Path,
        help="Path to the output EPUB file",
    )
    convert_parser.add_argument("-t", "--title", help="Title of the book")
    convert_parser.add_argument("-a", "--author", help="Author of the book")
    convert_parser.add_argument("-l", "--language", help="Language of the book")
    convert_parser.add_argument(
        "--encoding",
        help="Text encoding of the input file; auto-detected by default",
    )
    convert_parser.add_argument("--identifier", help="Identifier of the book")
    convert_parser.add_argument(
        "-c",
        "--cover",
        type=pathlib.Path,
        help="Path to the cover image of the book",
    )
    description_group = convert_parser.add_mutually_exclusive_group()
    description_group.add_argument(
        "--description",
        help="Description shown on the title page and stored in EPUB metadata",
    )
    description_group.add_argument(
        "--description-file",
        type=pathlib.Path,
        help="Path to a TXT file containing the book description",
    )
    convert_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing output EPUB file",
    )
    convert_parser.add_argument(
        "--preserve-line-breaks",
        action="store_true",
        help="Keep every source line break instead of reflowing wrapped prose",
    )

    args = parser.parse_args()

    if args.command == "convert":
        if not args.input.is_file():
            parser.error(f"Input file does not exist or is not a file: {args.input}")
        if args.input.suffix.lower() != ".txt":
            parser.error(f"Input file must have a .txt extension: {args.input}")

        output_file = args.output or args.input.with_suffix(".epub")
        if args.input.resolve() == output_file.resolve():
            parser.error("Output file must not be the same as the input file")
        if not output_file.parent.is_dir():
            parser.error(f"Output directory does not exist: {output_file.parent}")
        if output_file.exists() and not args.overwrite:
            parser.error(
                f"Output file already exists: {output_file} "
                "(use --overwrite to replace it)"
            )
        if args.cover is not None and not args.cover.is_file():
            parser.error(f"Cover file does not exist or is not a file: {args.cover}")
        if args.description_file is not None and not args.description_file.is_file():
            parser.error(
                "Description file does not exist or is not a file: "
                f"{args.description_file}"
            )

        book_description = args.description
        if args.description_file is not None:
            try:
                book_description = read_book_text(args.description_file)
            except (OSError, UnicodeError) as error:
                parser.error(f"Cannot read description file: {error}")

        try:
            created = Txt2Epub.create_epub(
                input_file=args.input,
                output_file=output_file,
                book_identifier=args.identifier,
                book_title=args.title,
                book_author=args.author,
                book_language=args.language,
                book_cover=args.cover,
                text_encoding=args.encoding,
                overwrite=args.overwrite,
                preserve_line_breaks=args.preserve_line_breaks,
                book_description=book_description,
            )
        except (OSError, UnicodeError, ValueError) as error:
            print(f"Conversion failed: {error}", file=sys.stderr)
            return 1
        if not created:
            print(
                "Conversion failed: EPUB writer did not produce an output file.",
                file=sys.stderr,
            )
            return 1
        print(f"Created EPUB: {output_file}")
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
