from __future__ import annotations

import argparse
from pathlib import Path

from make_puzzle_pdf import print_pdf
from study_core import (
    StudyError,
    StudyOptions,
    fetch_study,
    prepare_study,
    render_book_html,
    render_game_html,
    render_study_html,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a printable PDF from a Lichess study (per-move diagrams).",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--study", help="Lichess study URL or id. A chapter id may be included.")
    source.add_argument("--input", type=Path, help="Local PGN file exported from a study.")

    parser.add_argument("--output", type=Path, default=Path("output/study.pdf"), help="PDF output path.")
    parser.add_argument("--html", type=Path, help="HTML output path. Defaults to the PDF path with .html.")
    parser.add_argument("--html-only", action="store_true", help="Only create HTML, skip PDF generation.")
    parser.add_argument("--title", help="Document title. Defaults to the study name from the PGN.")
    parser.add_argument(
        "--columns",
        type=int,
        default=2,
        help="Grid size N (1-5): every page is split into an N x N set of cells.",
    )
    parser.add_argument(
        "--orientation",
        choices=["white", "black"],
        default="white",
        help="Board orientation for every diagram.",
    )
    parser.add_argument(
        "--max-variation-depth",
        type=int,
        default=4,
        help="How deeply nested variations may go. 0 keeps only the main line.",
    )
    parser.add_argument("--mainline-only", action="store_true", help="Skip every variation, keep only main lines.")
    parser.add_argument(
        "--layout",
        choices=["study", "game", "book"],
        default="study",
        help=(
            "study: per-move grid with comments. game: compact sheet of 8 diagrams "
            "per page. book: prose-like SAN runs with diagrams only at commented moves."
        ),
    )
    parser.add_argument(
        "--max-moves-without-diagram",
        type=int,
        default=6,
        help=(
            "book layout only: force a diagram after this many consecutive moves "
            "without one, so the reader never has to track too many plies in their head."
        ),
    )
    parser.add_argument(
        "--page-break-per-chapter",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Start each chapter on a new page. Use --no-page-break-per-chapter for continuous flow.",
    )
    parser.add_argument("--chrome-path", type=Path, help="Path to Chrome or Edge executable.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    options = StudyOptions(
        title=args.title,
        columns=args.columns,
        orientation=args.orientation,
        mainline_only=args.mainline_only,
        max_variation_depth=args.max_variation_depth,
        page_break_per_chapter=args.page_break_per_chapter,
        layout=args.layout,
        book_max_run=max(1, args.max_moves_without_diagram),
    )

    try:
        if args.study:
            pgn_text, source_note = fetch_study(args.study)
        else:
            if not args.input.exists():
                raise StudyError(f"PGN file does not exist: {args.input}")
            pgn_text = args.input.read_text(encoding="utf-8")
            source_note = args.input.name
        result = prepare_study(pgn_text, source_note, options)
    except StudyError as exc:
        raise SystemExit(str(exc))

    if options.layout == "game":
        html_doc = render_game_html(result, options)
    elif options.layout == "book":
        html_doc = render_book_html(result, options)
    else:
        html_doc = render_study_html(result, options)
    html_path = args.html or args.output.with_suffix(".html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_doc, encoding="utf-8")
    print(f"Wrote HTML: {html_path}")

    if not args.html_only:
        print_pdf(html_path, args.output, args.chrome_path)
        print(f"Wrote PDF: {args.output}")

    print(f"Chapters: {len(result.chapters)}  Diagrams: {result.diagram_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
