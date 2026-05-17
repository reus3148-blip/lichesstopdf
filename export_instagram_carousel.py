from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from make_puzzle_pdf import (
    find_browser,
    render_html,
    render_puzzle,
    select_puzzles,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export square Instagram carousel PNGs from Lichess puzzles.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("output/instagram"))
    parser.add_argument("--title", default="BlunderMate")
    parser.add_argument("--theme", action="append", default=[])
    parser.add_argument("--match", choices=["any", "all"], default="any")
    parser.add_argument("--min-rating", type=int)
    parser.add_argument("--max-rating", type=int)
    parser.add_argument("--min-popularity", type=int)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--answers", action="store_true", help="Also export answer cards.")
    parser.add_argument("--chrome-path", type=Path)
    return parser.parse_args()


def screenshot(html_path: Path, png_path: Path, chrome_path: Path | None) -> None:
    browser = find_browser(chrome_path)
    command = [
        browser,
        "--headless",
        "--disable-gpu",
        "--hide-scrollbars",
        "--window-size=1080,1080",
        f"--screenshot={png_path.resolve()}",
        html_path.resolve().as_uri(),
    ]
    subprocess.run(command, check=True)


def write_card(
    path: Path,
    title: str,
    rendered,
    include_questions: bool,
    include_solutions: bool,
    index: int,
    total: int,
) -> None:
    html = render_html(
        title,
        [rendered],
        include_questions=include_questions,
        include_solutions=include_solutions,
        layout="instagram",
    )
    html = html.replace("Puzzle 01 / 01", f"Puzzle {index:02d} / {total:02d}")
    html = html.replace("Answer 01 / 01", f"Answer {index:02d} / {total:02d}")
    path.write_text(html, encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected = select_puzzles(args.input, args)
    rendered = [render_puzzle(puzzle) for puzzle in selected]

    for index, item in enumerate(rendered, start=1):
        question_html = args.output_dir / f"{index:02d}_question.html"
        question_png = args.output_dir / f"{index:02d}_question.png"
        write_card(question_html, args.title, item, True, False, index, len(rendered))
        screenshot(question_html, question_png, args.chrome_path)
        print(f"Wrote {question_png}")

        if args.answers:
            answer_html = args.output_dir / f"{index:02d}_answer.html"
            answer_png = args.output_dir / f"{index:02d}_answer.png"
            write_card(answer_html, f"{args.title} Answer", item, False, True, index, len(rendered))
            screenshot(answer_html, answer_png, args.chrome_path)
            print(f"Wrote {answer_png}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
