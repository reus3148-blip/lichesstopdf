from __future__ import annotations

import argparse
import csv
import html
import io
import random
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import chess
import chess.svg


CHROME_CANDIDATES = [
    "chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "msedge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


@dataclass(frozen=True)
class Puzzle:
    puzzle_id: str
    fen: str
    moves: str
    rating: int
    rating_deviation: int
    popularity: int
    nb_plays: int
    themes: tuple[str, ...]
    game_url: str
    opening_tags: tuple[str, ...]


@dataclass(frozen=True)
class RenderedMove:
    label: str
    svg: str
    side: str


@dataclass(frozen=True)
class RenderedPuzzle:
    puzzle: Puzzle
    side_to_move: str
    question_svg: str
    opponent_move_label: str
    solution_moves: tuple[RenderedMove, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate printable PDF puzzle sheets from the Lichess puzzle CSV.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Lichess puzzle CSV or .csv.zst file.")
    parser.add_argument("--output", type=Path, default=Path("output/puzzles.pdf"), help="PDF output path.")
    parser.add_argument("--html", type=Path, help="HTML output path. Defaults to the PDF path with .html.")
    parser.add_argument("--html-only", action="store_true", help="Only create HTML, skip PDF generation.")
    parser.add_argument("--title", default="Lichess Puzzle Set", help="Title shown in the generated document.")
    parser.add_argument("--theme", action="append", default=[], help="Filter by Lichess theme. Can be used more than once.")
    parser.add_argument("--match", choices=["any", "all"], default="any", help="How multiple themes should match.")
    parser.add_argument("--min-rating", type=int, help="Minimum puzzle rating.")
    parser.add_argument("--max-rating", type=int, help="Maximum puzzle rating.")
    parser.add_argument("--min-popularity", type=int, help="Minimum popularity score.")
    parser.add_argument("--count", type=int, default=10, help="Number of puzzles to include.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible sampling.")
    parser.add_argument("--chrome-path", type=Path, help="Path to Chrome or Edge executable.")
    parser.add_argument("--solutions-at-end", action="store_true", help="Put all solution pages after all puzzle pages.")
    parser.add_argument(
        "--layout",
        choices=["standard", "print-minimal", "instagram"],
        default="standard",
        help="Visual layout template.",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--questions-only", action="store_true", help="Create only puzzle pages.")
    output_group.add_argument("--answers-only", action="store_true", help="Create only solution pages.")
    return parser.parse_args()


def open_csv_text(path: Path) -> io.TextIOBase:
    if path.suffix == ".zst":
        try:
            import zstandard as zstd
        except ImportError as exc:
            raise SystemExit("Reading .zst files requires zstandard. Run: pip install -r requirements.txt") from exc

        raw = path.open("rb")
        reader = zstd.ZstdDecompressor().stream_reader(raw)
        return io.TextIOWrapper(reader, encoding="utf-8", newline="")

    return path.open("r", encoding="utf-8", newline="")


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def iter_puzzles(path: Path) -> Iterator[Puzzle]:
    with open_csv_text(path) as file:
        reader = csv.DictReader(file)
        required = {"PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation", "Popularity", "NbPlays", "Themes", "GameUrl", "OpeningTags"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"Input CSV is missing required columns: {', '.join(sorted(missing))}")

        for row in reader:
            yield Puzzle(
                puzzle_id=row["PuzzleId"],
                fen=row["FEN"],
                moves=row["Moves"],
                rating=parse_int(row["Rating"]),
                rating_deviation=parse_int(row["RatingDeviation"]),
                popularity=parse_int(row["Popularity"]),
                nb_plays=parse_int(row["NbPlays"]),
                themes=tuple(row["Themes"].split()),
                game_url=row["GameUrl"],
                opening_tags=tuple(tag for tag in row["OpeningTags"].split() if tag),
            )


def puzzle_matches(puzzle: Puzzle, args: argparse.Namespace) -> bool:
    wanted_themes = set(args.theme)
    puzzle_themes = set(puzzle.themes)

    if wanted_themes and args.match == "any" and not wanted_themes.intersection(puzzle_themes):
        return False
    if wanted_themes and args.match == "all" and not wanted_themes.issubset(puzzle_themes):
        return False
    if args.min_rating is not None and puzzle.rating < args.min_rating:
        return False
    if args.max_rating is not None and puzzle.rating > args.max_rating:
        return False
    if args.min_popularity is not None and puzzle.popularity < args.min_popularity:
        return False
    return True


def select_puzzles(path: Path, args: argparse.Namespace) -> list[Puzzle]:
    rng = random.Random(args.seed)
    selected: list[Puzzle] = []
    seen = 0

    for puzzle in iter_puzzles(path):
        if not puzzle_matches(puzzle, args):
            continue

        seen += 1
        if len(selected) < args.count:
            selected.append(puzzle)
            continue

        slot = rng.randrange(seen)
        if slot < args.count:
            selected[slot] = puzzle

    if not selected:
        raise SystemExit("No puzzles matched the selected filters.")

    return selected


def move_label(board: chess.Board, move: chess.Move) -> tuple[str, str]:
    side = "White" if board.turn == chess.WHITE else "Black"
    san = board.san(move)
    if board.turn == chess.WHITE:
        label = f"{board.fullmove_number}. {san}"
    else:
        label = f"{board.fullmove_number}... {san}"
    return label, side


def board_svg(board: chess.Board, last_move: chess.Move | None, size: int) -> str:
    arrows = []
    if last_move is not None:
        arrows = [chess.svg.Arrow(last_move.from_square, last_move.to_square)]

    check_square = None
    if board.is_check():
        check_square = board.king(board.turn)

    return chess.svg.board(
        board,
        size=size,
        lastmove=last_move,
        arrows=arrows,
        check=check_square,
        flipped=board.turn == chess.BLACK,
    )


def render_puzzle(puzzle: Puzzle) -> RenderedPuzzle:
    move_strings = puzzle.moves.split()
    if len(move_strings) < 2:
        raise ValueError(f"Puzzle {puzzle.puzzle_id} does not contain a solution move.")

    board = chess.Board(puzzle.fen)

    opponent_move = board.parse_uci(move_strings[0])
    opponent_label, _ = move_label(board, opponent_move)
    board.push(opponent_move)

    side_to_move = "White" if board.turn == chess.WHITE else "Black"
    question_svg = board_svg(board, opponent_move, size=430)

    solution_moves: list[RenderedMove] = []
    for move_text in move_strings[1:]:
        move = board.parse_uci(move_text)
        label, side = move_label(board, move)
        board.push(move)
        solution_moves.append(
            RenderedMove(
                label=label,
                side=side,
                svg=board_svg(board, move, size=260),
            )
        )

    return RenderedPuzzle(
        puzzle=puzzle,
        side_to_move=side_to_move,
        question_svg=question_svg,
        opponent_move_label=opponent_label,
        solution_moves=tuple(solution_moves),
    )


def text(value: str) -> str:
    return html.escape(value, quote=True)


def theme_list(themes: Iterable[str]) -> str:
    return ", ".join(text(theme) for theme in themes)


def opening_name(tags: tuple[str, ...]) -> str:
    if not tags:
        return "Unknown opening"
    return " / ".join(tag.replace("_", " ") for tag in tags[:2])


def render_print_question_page(title: str, rendered: RenderedPuzzle, index: int, total: int) -> list[str]:
    puzzle = rendered.puzzle
    body = []
    body.append("<section class=\"page print-page\">")
    body.append("<header class=\"print-header\">")
    body.append(f"<div>Puzzle {index:02d}</div>")
    body.append(f"<div>{text(rendered.side_to_move)} to move</div>")
    body.append(f"<div>Rating {puzzle.rating}</div>")
    body.append("</header>")
    body.append(f"<div class=\"print-board\">{rendered.question_svg}</div>")
    body.append("<div class=\"work-area\">")
    body.append("<div class=\"work-block\"><div class=\"work-title\">Candidate moves</div><div class=\"ruled\"></div></div>")
    body.append("<div class=\"work-block\"><div class=\"work-title\">Calculation</div><div class=\"ruled tall\"></div></div>")
    body.append("<div class=\"final-row\"><span>Final move</span><div></div></div>")
    body.append("</div>")
    body.append("</section>")
    return body


def render_instagram_question_page(title: str, rendered: RenderedPuzzle, index: int, total: int) -> list[str]:
    puzzle = rendered.puzzle
    main_theme = next((theme for theme in puzzle.themes if theme not in {"short", "long", "veryLong"}), puzzle.themes[0])
    body = []
    body.append("<section class=\"instagram-page insta-question\">")
    body.append("<div class=\"insta-brand\">BlunderMate</div>")
    body.append(f"<div class=\"insta-kicker\">Puzzle {index:02d} / {total:02d}</div>")
    body.append(f"<div class=\"insta-title\">{text(rendered.side_to_move)} to move</div>")
    body.append(f"<div class=\"insta-board\">{rendered.question_svg}</div>")
    body.append("<div class=\"insta-bottom\">")
    body.append(f"<span>{text(main_theme)}</span>")
    body.append(f"<span>Rating {puzzle.rating}</span>")
    body.append("</div>")
    body.append("</section>")
    return body


def render_question_page(title: str, rendered: RenderedPuzzle, index: int, total: int, layout: str = "standard") -> list[str]:
    if layout == "print-minimal":
        return render_print_question_page(title, rendered, index, total)
    if layout == "instagram":
        return render_instagram_question_page(title, rendered, index, total)

    puzzle = rendered.puzzle
    body = []
    body.append("<section class=\"page\">")
    body.append("<header class=\"topline\">")
    body.append(f"<div class=\"doc-title\">{text(title)}</div>")
    body.append(f"<div class=\"meta\">Puzzle {index} of {total} - {text(puzzle.puzzle_id)}</div>")
    body.append("</header>")
    body.append("<main class=\"question\">")
    body.append("<div>")
    body.append(f"<div class=\"subtle\">After {text(rendered.opponent_move_label)}</div>")
    body.append(f"<div class=\"prompt\">Find the best move for {text(rendered.side_to_move)}.</div>")
    body.append("<table class=\"facts\">")
    body.append(f"<tr><th>Rating</th><td>{puzzle.rating} +/- {puzzle.rating_deviation}</td></tr>")
    body.append(f"<tr><th>Popularity</th><td>{puzzle.popularity} from {puzzle.nb_plays} plays</td></tr>")
    body.append(f"<tr><th>Themes</th><td>{theme_list(puzzle.themes)}</td></tr>")
    body.append(f"<tr><th>Opening</th><td>{text(opening_name(puzzle.opening_tags))}</td></tr>")
    body.append(f"<tr><th>Source</th><td><a href=\"{text(puzzle.game_url)}\">{text(puzzle.game_url)}</a></td></tr>")
    body.append("</table>")
    body.append("</div>")
    body.append(f"<div class=\"board-large\">{rendered.question_svg}</div>")
    body.append("</main>")
    body.append("<div class=\"footer\">Generated from the Lichess puzzle database.</div>")
    body.append("</section>")
    return body


def render_instagram_solution_page(rendered: RenderedPuzzle, index: int, total: int) -> list[str]:
    puzzle = rendered.puzzle
    first_solution = rendered.solution_moves[0].label if rendered.solution_moves else "No move"
    line = " ".join(move.label for move in rendered.solution_moves[:5])
    body = []
    body.append("<section class=\"instagram-page insta-answer\">")
    body.append("<div class=\"insta-brand\">BlunderMate</div>")
    body.append(f"<div class=\"insta-kicker\">Answer {index:02d} / {total:02d}</div>")
    body.append(f"<div class=\"insta-answer-move\">{text(first_solution)}</div>")
    body.append(f"<div class=\"insta-board small\">{rendered.solution_moves[0].svg if rendered.solution_moves else rendered.question_svg}</div>")
    body.append(f"<div class=\"insta-line\">{text(line)}</div>")
    body.append(f"<div class=\"insta-bottom\"><span>{text(puzzle.puzzle_id)}</span><span>blundermate.app</span></div>")
    body.append("</section>")
    return body


def render_solution_page(rendered: RenderedPuzzle, index: int, total: int, layout: str = "standard") -> list[str]:
    if layout == "instagram":
        return render_instagram_solution_page(rendered, index, total)

    puzzle = rendered.puzzle
    body = []
    body.append("<section class=\"page\">")
    body.append("<header class=\"topline\">")
    body.append(f"<div class=\"doc-title\">Solution - {text(puzzle.puzzle_id)}</div>")
    body.append(f"<div class=\"meta\">Puzzle {index} of {total}</div>")
    body.append("</header>")
    first_solution = rendered.solution_moves[0].label if rendered.solution_moves else "No move"
    body.append(f"<div class=\"answer-line\">Best move: {text(first_solution)}</div>")
    body.append("<div class=\"solution-grid\">")
    for move in rendered.solution_moves:
        body.append("<article class=\"move-card\">")
        body.append(f"<div class=\"move-title\">{text(move.label)} <span class=\"subtle\">{text(move.side)}</span></div>")
        body.append(move.svg)
        body.append("</article>")
    body.append("</div>")
    body.append(f"<div class=\"footer\">Themes: {theme_list(puzzle.themes)}</div>")
    body.append("</section>")
    return body


def render_html(
    title: str,
    rendered_puzzles: list[RenderedPuzzle],
    solutions_at_end: bool = False,
    include_questions: bool = True,
    include_solutions: bool = True,
    layout: str = "standard",
) -> str:
    if not include_questions and not include_solutions:
        raise ValueError("At least one of include_questions or include_solutions must be true.")

    body: list[str] = []
    body.append("<!doctype html>")
    body.append("<html lang=\"en\">")
    body.append("<head>")
    body.append("<meta charset=\"utf-8\">")
    body.append(f"<title>{text(title)}</title>")
    page_rule = "@page { size: 1080px 1080px; margin: 0; }" if layout == "instagram" else "@page { size: A4; margin: 10mm; }"
    css = """
<style>
  __PAGE_RULE__
  * {
    box-sizing: border-box;
  }
  body {
    color: #1f2933;
    font-family: Arial, Helvetica, sans-serif;
    font-size: 13px;
    line-height: 1.42;
    margin: 0;
  }
  a {
    color: #1f4f8f;
    text-decoration: none;
  }
  .page {
    break-after: page;
    min-height: 260mm;
    padding: 0;
    position: relative;
  }
  .page:last-child {
    break-after: auto;
  }
  .topline {
    align-items: baseline;
    border-bottom: 1px solid #c9d2dc;
    display: flex;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 10mm;
    padding-bottom: 3mm;
  }
  .doc-title {
    font-size: 18px;
    font-weight: 700;
  }
  .meta {
    color: #52606d;
    font-size: 11px;
  }
  .question {
    align-items: start;
    display: grid;
    grid-template-columns: 1fr 440px;
    gap: 18px;
  }
  .prompt {
    font-size: 28px;
    font-weight: 700;
    line-height: 1.18;
    margin: 10mm 0 6mm;
  }
  .subtle {
    color: #52606d;
  }
  .facts {
    border-collapse: collapse;
    margin-top: 10mm;
    width: 100%;
  }
  .facts th {
    color: #52606d;
    font-weight: 400;
    padding: 2mm 3mm 2mm 0;
    text-align: left;
    width: 30mm;
  }
  .facts td {
    padding: 2mm 0;
  }
  .board-large {
    text-align: center;
  }
  .board-large svg {
    height: auto;
    max-width: 100%;
  }
  .solution-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8mm 10mm;
    margin-top: 7mm;
  }
  .move-card {
    break-inside: avoid;
  }
  .move-title {
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 2mm;
  }
  .move-card svg {
    height: auto;
    width: 100%;
  }
  .answer-line {
    font-size: 18px;
    font-weight: 700;
    margin: 6mm 0 2mm;
  }
  .footer {
    bottom: 0;
    color: #7b8794;
    font-size: 10px;
    left: 0;
    position: absolute;
    right: 0;
  }
  .print-page {
    break-after: page;
    display: flex;
    flex-direction: column;
    height: 277mm;
    min-height: 0;
    overflow: hidden;
  }
  .print-header {
    align-items: center;
    border-bottom: 1px solid #1f2933;
    color: #111827;
    display: grid;
    font-size: 12px;
    font-weight: 700;
    grid-template-columns: 1fr 1fr 1fr;
    letter-spacing: 0;
    padding-bottom: 4mm;
    text-transform: uppercase;
  }
  .print-header div:nth-child(2) {
    font-size: 18px;
    text-align: center;
    text-transform: none;
  }
  .print-header div:nth-child(3) {
    text-align: right;
  }
  .print-board {
    margin: 6mm auto;
    text-align: center;
  }
  .print-board svg {
    height: 128mm;
    width: 128mm;
  }
  .work-area {
    display: grid;
    gap: 5mm;
  }
  .work-title {
    color: #111827;
    font-size: 12px;
    font-weight: 700;
    margin-bottom: 2mm;
    text-transform: uppercase;
  }
  .ruled {
    background-image: repeating-linear-gradient(to bottom, transparent 0, transparent 9mm, #d1d5db 9.2mm);
    border: 1px solid #d1d5db;
    height: 28mm;
  }
  .ruled.tall {
    height: 48mm;
  }
  .final-row {
    align-items: center;
    display: grid;
    gap: 5mm;
    grid-template-columns: 30mm 1fr;
    margin-top: 2mm;
  }
  .final-row span {
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
  }
  .final-row div {
    border-bottom: 2px solid #111827;
    height: 11mm;
  }
  .instagram-page {
    background: #f6f1e8;
    color: #17231f;
    height: 1080px;
    overflow: hidden;
    padding: 64px;
    position: relative;
    width: 1080px;
  }
  .instagram-page::before {
    border: 2px solid #243b35;
    content: "";
    inset: 34px;
    pointer-events: none;
    position: absolute;
  }
  .insta-brand {
    font-size: 34px;
    font-weight: 800;
    letter-spacing: 0;
    text-transform: uppercase;
  }
  .insta-kicker {
    color: #8a4b35;
    font-size: 30px;
    font-weight: 700;
    margin-top: 28px;
  }
  .insta-title {
    font-size: 78px;
    font-weight: 900;
    letter-spacing: 0;
    line-height: 0.95;
    margin-top: 8px;
  }
  .insta-board {
    margin: 32px auto 0;
    text-align: center;
  }
  .insta-board svg {
    height: 620px;
    width: 620px;
  }
  .insta-board.small svg {
    height: 520px;
    width: 520px;
  }
  .insta-bottom {
    align-items: center;
    bottom: 62px;
    display: flex;
    font-size: 28px;
    font-weight: 700;
    justify-content: space-between;
    left: 64px;
    position: absolute;
    right: 64px;
  }
  .insta-answer-move {
    color: #2f6f5e;
    font-size: 96px;
    font-weight: 900;
    letter-spacing: 0;
    line-height: 1;
    margin-top: 30px;
  }
  .insta-line {
    background: rgba(255, 255, 255, 0.62);
    border: 1px solid #d7cfbf;
    font-size: 30px;
    font-weight: 700;
    line-height: 1.25;
    margin-top: 28px;
    padding: 20px 22px;
  }
</style>
""".replace("__PAGE_RULE__", page_rule).strip()
    body.append(css)
    body.append("</head>")
    body.append("<body>")

    total = len(rendered_puzzles)
    if include_questions and include_solutions and solutions_at_end:
        for index, rendered in enumerate(rendered_puzzles, start=1):
            body.extend(render_question_page(title, rendered, index, total, layout))
        for index, rendered in enumerate(rendered_puzzles, start=1):
            body.extend(render_solution_page(rendered, index, total, layout))
    elif include_questions and include_solutions:
        for index, rendered in enumerate(rendered_puzzles, start=1):
            body.extend(render_question_page(title, rendered, index, total, layout))
            body.extend(render_solution_page(rendered, index, total, layout))
    elif include_questions:
        for index, rendered in enumerate(rendered_puzzles, start=1):
            body.extend(render_question_page(title, rendered, index, total, layout))
    else:
        for index, rendered in enumerate(rendered_puzzles, start=1):
            body.extend(render_solution_page(rendered, index, total, layout))

    body.append("</body>")
    body.append("</html>")
    return "\n".join(body)


def find_browser(explicit_path: Path | None) -> str:
    if explicit_path:
        if explicit_path.exists():
            return str(explicit_path)
        raise SystemExit(f"Browser path does not exist: {explicit_path}")

    for candidate in CHROME_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
        path = Path(candidate)
        if path.exists():
            return str(path)

    raise SystemExit("Chrome or Edge was not found. Use --chrome-path to specify the browser executable.")


def print_pdf(html_path: Path, pdf_path: Path, chrome_path: Path | None) -> None:
    browser = find_browser(chrome_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        browser,
        "--headless",
        "--disable-gpu",
        "--print-to-pdf-no-header",
        f"--print-to-pdf={pdf_path.resolve()}",
        html_path.resolve().as_uri(),
    ]
    subprocess.run(command, check=True)


def main() -> int:
    args = parse_args()
    if args.count < 1:
        raise SystemExit("--count must be at least 1.")
    if not args.input.exists():
        raise SystemExit(f"Input file does not exist: {args.input}")

    html_path = args.html or args.output.with_suffix(".html")
    html_path.parent.mkdir(parents=True, exist_ok=True)

    selected = select_puzzles(args.input, args)
    rendered = []
    for puzzle in selected:
        try:
            rendered.append(render_puzzle(puzzle))
        except Exception as exc:
            print(f"Skipping invalid puzzle {puzzle.puzzle_id}: {exc}", file=sys.stderr)

    if not rendered:
        raise SystemExit("No selected puzzles could be rendered.")

    html_path.write_text(
        render_html(
            args.title,
            rendered,
            args.solutions_at_end,
            include_questions=not args.answers_only,
            include_solutions=not args.questions_only,
            layout=args.layout,
        ),
        encoding="utf-8",
    )
    print(f"Wrote HTML: {html_path}")

    if not args.html_only:
        print_pdf(html_path, args.output, args.chrome_path)
        print(f"Wrote PDF: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
