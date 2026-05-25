"""Shared core for turning a Lichess study (PGN) into a printable HTML sheet.

Used by the make_study_pdf.py CLI, the api/study.py serverless function, and the
local_app.py dev server, so all three render studies identically.
"""

from __future__ import annotations

import html
import io
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import chess
import chess.pgn
import chess.svg


NAG_SYMBOLS = {
    chess.pgn.NAG_GOOD_MOVE: "!",
    chess.pgn.NAG_MISTAKE: "?",
    chess.pgn.NAG_BRILLIANT_MOVE: "!!",
    chess.pgn.NAG_BLUNDER: "??",
    chess.pgn.NAG_SPECULATIVE_MOVE: "!?",
    chess.pgn.NAG_DUBIOUS_MOVE: "?!",
}

ANNOTATION_RE = re.compile(r"\[%[^\]]*\]")

# Upper bound for request-driven rendering (web). The CLI is not capped.
MAX_REQUEST_DIAGRAMS = 800


class StudyError(Exception):
    """Raised for any user-facing problem while building a study sheet."""


@dataclass
class StudyOptions:
    title: str | None = None
    columns: int = 2
    orientation: str = "white"
    mainline_only: bool = False
    max_variation_depth: int = 4
    page_break_per_chapter: bool = True
    layout: str = "study"
    # Book layout safety net: how many consecutive mainline moves may pass
    # without a diagram before one is forced in. Ignored by other layouts.
    book_max_run: int = 6
    # 1-based indices of chapters to keep. Empty/None means keep all.
    chapter_indices: list[int] | None = None
    # Study layout: drop cards that carry no comment so the sheet only shows
    # the moves worth pausing on. Ignored by book/game layouts.
    skip_uncommented: bool = False

    @property
    def flipped(self) -> bool:
        return self.orientation == "black"

    @property
    def depth_limit(self) -> int:
        return 0 if self.mainline_only else max(0, self.max_variation_depth)


@dataclass
class MoveCard:
    label: str
    svg: str
    comment: str
    depth: int
    fullmove_number: int = 0
    is_white_move: bool = True
    san: str = ""


@dataclass
class Chapter:
    title: str
    meta: str
    site: str
    intro: str = ""
    cards: list[MoveCard] = field(default_factory=list)


@dataclass
class StudyResult:
    title: str
    source_note: str
    chapters: list[Chapter]

    @property
    def diagram_count(self) -> int:
        return sum(len(chapter.cards) for chapter in self.chapters)


def parse_study_ref(value: str) -> tuple[str, str | None]:
    value = value.strip()
    match = re.search(r"lichess\.org/study/([A-Za-z0-9]{8})(?:/([A-Za-z0-9]{8}))?", value)
    if not match:
        match = re.fullmatch(r"([A-Za-z0-9]{8})(?:/([A-Za-z0-9]{8}))?", value)
    if not match:
        raise StudyError(f"Could not read a Lichess study id from: {value}")
    return match.group(1), match.group(2)


def fetch_study_pgn(study_id: str, chapter_id: str | None) -> str:
    if chapter_id:
        url = f"https://lichess.org/study/{study_id}/{chapter_id}.pgn"
    else:
        url = f"https://lichess.org/study/{study_id}.pgn"
    url += "?source=true&comments=true&variations=true&clocks=false"

    request = urllib.request.Request(url, headers={"User-Agent": "lichess-pdf-maker/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise StudyError(
            f"Lichess returned HTTP {exc.code} for study {study_id}. "
            "Make sure the study exists and is public."
        ) from exc
    except urllib.error.URLError as exc:
        raise StudyError(f"Could not reach Lichess: {exc.reason}") from exc


def fetch_study(ref: str) -> tuple[str, str]:
    """Fetch a study by URL or id. Returns (pgn_text, source_note)."""
    study_id, chapter_id = parse_study_ref(ref)
    pgn_text = fetch_study_pgn(study_id, chapter_id)
    return pgn_text, f"lichess.org/study/{study_id}"


def read_games(pgn_text: str) -> list[chess.pgn.Game]:
    stream = io.StringIO(pgn_text)
    games: list[chess.pgn.Game] = []
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        games.append(game)
    return games


def clean_comment(*parts: str) -> str:
    text = " ".join(part for part in parts if part)
    text = ANNOTATION_RE.sub("", text)
    return " ".join(text.split())


def move_prefix(board: chess.Board) -> str:
    if board.turn == chess.WHITE:
        return f"{board.fullmove_number}."
    return f"{board.fullmove_number}..."


def render_board(
    board: chess.Board,
    last_move: chess.Move | None,
    arrows: list,
    flipped: bool,
) -> str:
    check_square = board.king(board.turn) if board.is_check() else None
    return chess.svg.board(
        board,
        size=320,
        lastmove=last_move,
        arrows=arrows,
        check=check_square,
        flipped=flipped,
        coordinates=True,
    )


def build_cards(game: chess.pgn.Game, flipped: bool, max_depth: int) -> list[MoveCard]:
    cards: list[MoveCard] = []
    start_board = game.board()

    def make_card(before: chess.Board, node: chess.pgn.ChildNode, depth: int) -> MoveCard:
        san = before.san(node.move)
        symbol = "".join(NAG_SYMBOLS.get(nag, "") for nag in sorted(node.nags))
        after = before.copy()
        after.push(node.move)
        return MoveCard(
            label=f"{move_prefix(before)} {san}{symbol}",
            svg=render_board(after, node.move, node.arrows(), flipped),
            comment=clean_comment(node.starting_comment, node.comment),
            depth=depth,
            fullmove_number=before.fullmove_number,
            is_white_move=before.turn == chess.WHITE,
            san=f"{san}{symbol}",
        )

    def walk(node: chess.pgn.GameNode, board: chess.Board, depth: int) -> None:
        if not node.variations:
            return
        main = node.variations[0]
        cards.append(make_card(board, main, depth))

        for side in node.variations[1:]:
            if depth + 1 > max_depth:
                continue
            cards.append(make_card(board, side, depth + 1))
            side_board = board.copy()
            side_board.push(side.move)
            walk(side, side_board, depth + 1)

        main_board = board.copy()
        main_board.push(main.move)
        walk(main, main_board, depth)

    walk(game, start_board, 0)
    return cards


def chapter_from_game(
    game: chess.pgn.Game, index: int, flipped: bool, max_depth: int
) -> tuple[str, Chapter]:
    event = game.headers.get("Event", "").strip()
    if ": " in event:
        study_name, chapter_name = event.split(": ", 1)
    else:
        study_name, chapter_name = "", event
    chapter_name = chapter_name.strip() or f"Chapter {index}"

    meta_bits = []
    eco = game.headers.get("ECO", "").strip()
    opening = game.headers.get("Opening", "").strip()
    if eco and eco != "?":
        meta_bits.append(eco)
    if opening and opening != "?":
        meta_bits.append(opening)

    site = game.headers.get("Site", "").strip()
    if not site.startswith("http"):
        site = ""

    chapter = Chapter(
        title=chapter_name,
        meta=" - ".join(meta_bits),
        site=site,
        intro=clean_comment(game.comment),
        cards=build_cards(game, flipped, max_depth),
    )
    return study_name.strip(), chapter


def game_chapter_from_game(
    game: chess.pgn.Game, index: int, flipped: bool, max_depth: int
) -> Chapter:
    """Build a Chapter for the game layout: heading taken from the player tags."""

    def tag(name: str) -> str:
        value = game.headers.get(name, "").strip()
        return "" if value in ("", "?") else value

    white, black = tag("White"), tag("Black")
    event, result = tag("Event"), tag("Result")
    if result == "*":
        result = ""

    # PGN dates use "?" for unknown parts (e.g. "1858.??.??"). Keep the known
    # leading components so the heading shows "1858" rather than "1858.??.??".
    date_parts: list[str] = []
    for part in tag("Date").split("."):
        if "?" in part:
            break
        date_parts.append(part)
    date = ".".join(date_parts)

    if white and black:
        title = f"{white} – {black}"
        meta_bits = [event, date, result]
    else:
        title = white or black or event or f"Game {index}"
        meta_bits = [date, result]

    site = game.headers.get("Site", "").strip()
    if not site.startswith("http"):
        site = ""

    return Chapter(
        title=title,
        meta=" · ".join(bit for bit in meta_bits if bit),
        site=site,
        cards=build_cards(game, flipped, max_depth),
    )


def _filter_games(
    games: list[chess.pgn.Game], indices: list[int] | None
) -> list[chess.pgn.Game]:
    """Keep only the chapters at the given 1-based indices (preserving order).

    Out-of-range indices are silently dropped. An empty/None list keeps all games
    so callers don't have to special-case the "no filter" path.
    """
    if not indices:
        return games
    keep = {i for i in indices if 1 <= i <= len(games)}
    if not keep:
        raise StudyError(
            "None of the selected chapter numbers exist in this study."
        )
    return [game for index, game in enumerate(games, start=1) if index in keep]


def list_chapters(pgn_text: str) -> list[dict]:
    """Extract chapter metadata for a chapter-picker UI.

    Returns one dict per game: {index, name, meta}. `index` is 1-based.
    """
    games = read_games(pgn_text)
    out: list[dict] = []
    for index, game in enumerate(games, start=1):
        event = game.headers.get("Event", "").strip()
        if ": " in event:
            _, chapter_name = event.split(": ", 1)
        else:
            chapter_name = event
        chapter_name = chapter_name.strip() or f"Chapter {index}"

        # Meta line: prefer player names for game-style PGNs, else ECO/Opening.
        white = game.headers.get("White", "").strip()
        black = game.headers.get("Black", "").strip()
        if white and black and white != "?" and black != "?":
            meta = f"{white} – {black}"
        else:
            meta_bits: list[str] = []
            for tag in ("ECO", "Opening"):
                value = game.headers.get(tag, "").strip()
                if value and value != "?":
                    meta_bits.append(value)
            meta = " - ".join(meta_bits)

        out.append({"index": index, "name": chapter_name, "meta": meta})
    return out


def prepare_study(pgn_text: str, source_note: str, options: StudyOptions) -> StudyResult:
    games = read_games(pgn_text)
    if not games:
        raise StudyError("No chapters were found in the PGN.")
    games = _filter_games(games, options.chapter_indices)

    if options.layout == "game":
        chapters = [
            game_chapter_from_game(game, index, options.flipped, options.depth_limit)
            for index, game in enumerate(games, start=1)
        ]
        if options.title and len(chapters) == 1:
            chapters[0].title = options.title
        default_title = chapters[0].title if len(chapters) == 1 else "Chess Games"
        return StudyResult(
            title=options.title or default_title,
            source_note=source_note,
            chapters=chapters,
        )

    study_name = ""
    chapters = []
    for index, game in enumerate(games, start=1):
        name, chapter = chapter_from_game(game, index, options.flipped, options.depth_limit)
        study_name = study_name or name
        chapters.append(chapter)

    title = options.title or study_name or "Lichess Study"
    return StudyResult(title=title, source_note=source_note, chapters=chapters)


def text(value: str) -> str:
    return html.escape(value, quote=True)


def render_study_html(result: StudyResult, options: StudyOptions) -> str:
    body: list[str] = []
    body.append("<!doctype html>")
    body.append("<html lang=\"en\">")
    body.append("<head>")
    body.append("<meta charset=\"utf-8\">")
    body.append("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
    body.append(f"<title>{text(result.title)}</title>")
    body.append(_style(options.columns))
    body.append("</head>")
    body.append("<body>")

    body.append("<div class=\"print-bar\">")
    body.append("<button type=\"button\" onclick=\"window.print()\">인쇄 / PDF로 저장</button>")
    body.append("</div>")

    body.append("<header class=\"study-head\">")
    body.append(f"<div class=\"study-title\">{text(result.title)}</div>")
    sub = f"{len(result.chapters)} chapter(s)"
    if result.source_note:
        sub += f" - {result.source_note}"
    body.append(f"<div class=\"study-sub\">{text(sub)}</div>")
    body.append("</header>")

    for index, chapter in enumerate(result.chapters):
        # Drop uncommented cards before measuring length so the "is-short"
        # heuristic sees the layout the reader will actually get.
        cards = (
            [card for card in chapter.cards if card.comment]
            if options.skip_uncommented
            else chapter.cards
        )
        classes = ["study-section"]
        # Short chapters after the first are kept whole so a heading is never
        # stranded at a page bottom. The first chapter must NOT do this: it
        # follows the study header, and keeping it whole would shove the whole
        # chapter onto page 2 and leave page 1 blank below the title.
        if index > 0 and len(cards) <= 2 * options.columns:
            classes.append("is-short")
        if options.page_break_per_chapter and index > 0:
            classes.append("page-start")
        body.append(f"<section class=\"{' '.join(classes)}\">")
        body.append("<div class=\"chapter-head\">")
        body.append(f"<div class=\"chapter-title\">{text(chapter.title)}</div>")
        meta_line = chapter.meta
        if chapter.site:
            link = f"<a href=\"{text(chapter.site)}\">{text(chapter.site)}</a>"
            meta_line = f"{meta_line} - {link}" if meta_line else link
        if meta_line:
            body.append(f"<div class=\"chapter-meta\">{meta_line}</div>")
        body.append("</div>")

        if chapter.intro:
            body.append(f"<p class=\"chapter-intro\">{text(chapter.intro)}</p>")

        body.append("<div class=\"move-grid\">")
        for card in cards:
            classes = f"move-card depth-{min(card.depth, 3)}"
            body.append(f"<article class=\"{classes}\">")
            body.append(f"<div class=\"mv-label\">{text(card.label)}</div>")
            body.append(card.svg)
            if card.comment:
                body.append(f"<div class=\"mv-comment\">{text(card.comment)}</div>")
            body.append("</article>")
        body.append("</div>")
        body.append("</section>")

    body.append("</body>")
    body.append("</html>")
    return "\n".join(body)


def _style(columns: int) -> str:
    columns = max(1, min(columns, 5))
    # The A4 content box is 273mm tall (297 - 2x12mm margins). Cards have a
    # fixed height so every page tiles into the same columns x columns grid.
    # ~32mm is reserved so a chapter heading can share a page with a full set
    # of rows instead of pushing the rows onto the next page.
    card_height = round((273 - 32 - (columns - 1) * 6) / columns, 2)
    return f"""<style>
  @page {{ size: A4; margin: 12mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    color: #1f2933;
    font-family: Arial, Helvetica, sans-serif;
    font-size: 12px;
    margin: 0;
  }}
  a {{ color: #1f4f8f; text-decoration: none; }}
  .print-bar {{ position: fixed; right: 12px; top: 12px; z-index: 50; }}
  .print-bar button {{
    background: #176b66;
    border: 0;
    border-radius: 6px;
    color: #fff;
    cursor: pointer;
    font: inherit;
    font-weight: 700;
    padding: 8px 14px;
  }}
  .study-head {{
    border-bottom: 2px solid #1f2933;
    margin-bottom: 6mm;
    padding-bottom: 3mm;
  }}
  .study-title {{ font-size: 22px; font-weight: 800; }}
  .study-sub {{ color: #52606d; font-size: 11px; margin-top: 1mm; }}
  .study-section {{ margin-top: 9mm; }}
  .study-section:first-of-type {{ margin-top: 0; }}
  .study-section.is-short {{ break-inside: avoid; }}
  .study-section.page-start {{ break-before: page; margin-top: 0; }}
  .chapter-head {{
    border-bottom: 1px solid #c9d2dc;
    break-after: avoid;
    margin-bottom: 4mm;
    padding-bottom: 2mm;
  }}
  .chapter-title {{ font-size: 16px; font-weight: 700; }}
  .chapter-meta {{ color: #52606d; font-size: 10px; margin-top: 1mm; }}
  .chapter-intro {{
    color: #3a4754;
    font-size: 11px;
    line-height: 1.5;
    margin: 0 0 5mm;
    max-width: 165mm;
  }}
  .move-grid {{
    display: grid;
    grid-template-columns: repeat({columns}, 1fr);
    gap: 6mm;
  }}
  /* Depth is shown with border weight, border style and a grey shade so it
     survives black-and-white printing, not with hue alone. */
  .move-card {{
    border: 1px solid #c4ccd4;
    break-inside: avoid;
    height: {card_height}mm;
    /* min-height:0 overrides the grid item default (auto) so a long comment
       cannot stretch the card past its fixed height; overflow then clips it. */
    min-height: 0;
    overflow: hidden;
    padding: 2mm;
  }}
  .move-card.depth-0 {{ border-left: 5px solid #1f2933; }}
  .move-card.depth-1 {{ background: #f2f3f4; border-left: 4px solid #8b95a1; }}
  .move-card.depth-2 {{ background: #eaebed; border-left: 4px dashed #6b7480; }}
  .move-card.depth-3 {{ background: #e2e4e7; border-left: 4px dotted #6b7480; }}
  .mv-label {{ font-size: 12px; font-weight: 700; margin-bottom: 1.5mm; }}
  .move-card svg {{ display: block; height: auto; width: 100%; }}
  .mv-comment {{
    color: #3a4754;
    font-size: 10px;
    line-height: 1.35;
    margin-top: 1.5mm;
  }}
  @media print {{ .print-bar {{ display: none; }} }}
  /* On-screen the page is not paginated, so the print-tile heights leave
     either too much empty space (wide screens) or clip the SVG (narrow ones).
     Drop the fixed card height, mimic an A4 paper for context, and collapse
     to one column on phones so boards stay legible. */
  @media screen {{
    html {{ background: #e8e9ed; min-height: 100vh; }}
    body {{
      background: #fff;
      box-shadow: 0 8px 32px rgba(0,0,0,0.08);
      margin: 24px auto;
      max-width: 186mm;
      padding: 12mm;
    }}
    .move-card {{ height: auto; overflow: visible; }}
    .move-card svg {{ max-width: 100%; }}
  }}
  @media screen and (max-width: 720px) {{
    body {{ box-shadow: none; margin: 0; max-width: none; padding: 12px 14px 32px; }}
    .move-grid {{ grid-template-columns: 1fr; }}
    .move-card {{ max-width: 360px; margin-inline: auto; }}
  }}
</style>"""


@dataclass
class BookBlock:
    """A unit of the book layout: either an inline SAN run or a diagram card."""
    kind: str  # "run" or "diagram"
    cards: list[MoveCard] = field(default_factory=list)  # populated when kind == "run"
    card: MoveCard | None = None  # populated when kind == "diagram"


def build_book_blocks(cards: list[MoveCard], max_run: int) -> list[BookBlock]:
    """Group consecutive mainline moves with no comment into SAN runs.

    A card becomes a diagram block when it has a comment, sits in a variation
    (depth > 0), or follows a full run (safety net so the reader is never asked
    to track more than `max_run` moves in their head before seeing the board).
    """
    blocks: list[BookBlock] = []
    run: list[MoveCard] = []

    def flush_run() -> None:
        if run:
            blocks.append(BookBlock(kind="run", cards=run.copy()))
            run.clear()

    for card in cards:
        must_diagram = bool(card.comment) or card.depth > 0 or len(run) >= max(1, max_run)
        if must_diagram:
            flush_run()
            blocks.append(BookBlock(kind="diagram", card=card))
        else:
            run.append(card)
    flush_run()
    return blocks


def format_san_run(cards: list[MoveCard]) -> str:
    """Render a list of mainline cards as compact PGN-style text.

    Collapses paired white/black plies so the move number appears once per pair:
    "4. Ba4 Nf6 5. O-O Be7". A black ply that opens a run gets the "N..." prefix.
    """
    pieces: list[str] = []
    prev_white_number: int | None = None
    for card in cards:
        if card.is_white_move:
            pieces.append(f"{card.fullmove_number}. {card.san}")
            prev_white_number = card.fullmove_number
        else:
            if prev_white_number == card.fullmove_number:
                pieces.append(card.san)
            else:
                pieces.append(f"{card.fullmove_number}... {card.san}")
            prev_white_number = None
    return " ".join(pieces)


def format_san_run_html(cards: list[MoveCard]) -> str:
    """Same as format_san_run but wraps move numbers in <span class="mn">.

    Bolded move numbers visually separate move pairs in dense book prose,
    matching how printed chess books typeset notation.
    """
    pieces: list[str] = []
    prev_white_number: int | None = None
    for card in cards:
        san = text(card.san)
        if card.is_white_move:
            pieces.append(
                f"<span class=\"mn\">{card.fullmove_number}.</span> {san}"
            )
            prev_white_number = card.fullmove_number
        else:
            if prev_white_number == card.fullmove_number:
                pieces.append(san)
            else:
                pieces.append(
                    f"<span class=\"mn\">{card.fullmove_number}…</span> {san}"
                )
            prev_white_number = None
    return " ".join(pieces)


def render_book_html(result: StudyResult, options: StudyOptions) -> str:
    """Render a study as a book: prose SAN runs with diagrams only where useful."""
    body: list[str] = []
    body.append("<!doctype html>")
    body.append("<html lang=\"en\">")
    body.append("<head>")
    body.append("<meta charset=\"utf-8\">")
    body.append("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
    body.append(f"<title>{text(result.title)}</title>")
    body.append(_book_style())
    body.append("</head>")
    body.append("<body>")

    body.append("<div class=\"print-bar\">")
    body.append("<button type=\"button\" onclick=\"window.print()\">인쇄 / PDF로 저장</button>")
    body.append("</div>")

    body.append("<header class=\"book-head\">")
    body.append(f"<div class=\"book-title\">{text(result.title)}</div>")
    sub = f"{len(result.chapters)} chapter(s)"
    if result.source_note:
        sub += f" - {result.source_note}"
    body.append(f"<div class=\"book-sub\">{text(sub)}</div>")
    body.append("</header>")

    for index, chapter in enumerate(result.chapters):
        classes = ["book-section"]
        if options.page_break_per_chapter and index > 0:
            classes.append("page-start")
        body.append(f"<section class=\"{' '.join(classes)}\">")

        # Each chapter is its own block with a full-width heading and an
        # independent 2-column body. Putting the multi-column container on
        # the chapter (not the body) keeps the heading and its content
        # together naturally and avoids the `column-span: all` orphan trap.
        body.append("<div class=\"chapter-head\">")
        body.append(f"<div class=\"chapter-title\">{text(chapter.title)}</div>")
        meta_line = chapter.meta
        if chapter.site:
            link = f"<a href=\"{text(chapter.site)}\">{text(chapter.site)}</a>"
            meta_line = f"{meta_line} - {link}" if meta_line else link
        if meta_line:
            body.append(f"<div class=\"chapter-meta\">{meta_line}</div>")
        body.append("</div>")

        # Chapter intro is full-width prose; render it *before* the grid so
        # it doesn't reserve a whole 78mm grid row for one or two lines.
        if chapter.intro:
            body.append(f"<p class=\"chapter-intro\">{text(chapter.intro)}</p>")

        body.append("<div class=\"chapter-body\">")
        # Lay the body out as a CSS Grid of 2 columns. Each cell bundles
        # "preceding SAN run + diagram + caption" so a column never starts
        # with a stray SAN run that pushes its boards down out of alignment
        # with the other column. Rows use `minmax(78mm, auto)` so a row
        # with a long caption can grow without pushing the next row out of
        # rhythm — both cells in a row share the row's height, so the
        # boards in that row stay top-aligned with each other.
        blocks = build_book_blocks(chapter.cards, options.book_max_run)
        pending_runs: list[str] = []
        for block in blocks:
            if block.kind == "run":
                pending_runs.append(format_san_run_html(block.cards))
                continue
            card = block.card
            depth_class = f"depth-{min(card.depth, 3)}"
            cell_classes = ["diagram-cell", depth_class]
            body.append(f"<div class=\"{' '.join(cell_classes)}\">")
            for run_html in pending_runs:
                body.append(f"<p class=\"preceding-run\">{run_html}</p>")
            pending_runs = []
            body.append("<figure class=\"book-diagram\">")
            body.append(f"<div class=\"bd-board\">{card.svg}</div>")
            body.append("<figcaption class=\"bd-caption\">")
            body.append(f"<span class=\"bd-label\">{text(card.label)}</span>")
            if card.comment:
                body.append(f"<span class=\"bd-comment\">{text(card.comment)}</span>")
            body.append("</figcaption>")
            body.append("</figure>")
            body.append("</div>")

        # Anything still pending is a trailing SAN run after the last
        # diagram; it spans both grid columns at the bottom of the chapter.
        if pending_runs:
            body.append("<div class=\"trailing-runs\">")
            for run_html in pending_runs:
                body.append(f"<p class=\"book-run\">{run_html}</p>")
            body.append("</div>")
        body.append("</div>")
        body.append("</section>")

    body.append("</body>")
    body.append("</html>")
    return "\n".join(body)


def _book_style() -> str:
    # Tuned for a classic chess-book feel: justified serif prose flowing in
    # two newspaper columns, centred diagrams that sit inside a column with
    # an italic caption beneath, bold move numbers so the eye finds move
    # pairs quickly, and chapter headings that span both columns.
    return """<style>
  @page { size: A4; margin: 14mm 16mm 16mm; }
  * { box-sizing: border-box; }
  body {
    color: #15181b;
    font-family: "Georgia", "Source Serif Pro", "Times New Roman", serif;
    font-size: 11px;
    line-height: 1.55;
    margin: 0;
    max-width: 178mm;
    /* Hyphenation lets the justified prose break cleanly in narrow columns. */
    hyphens: auto;
  }
  /* The chapter body is a CSS Grid of 2 columns. Rows use minmax so a
     short cell uses the 78mm "standard" (six boards per page) but a long
     comment can stretch its row downward. Both cells in a row share the
     row's height, so the left and right boards in any row stay
     top-aligned with each other; subsequent rows reset to 78mm. */
  .chapter-body {
    display: grid;
    gap: 4mm 7mm;
    grid-auto-rows: minmax(78mm, auto);
    grid-template-columns: 1fr 1fr;
  }
  a { color: #1f4f8f; text-decoration: none; }
  .print-bar { position: fixed; right: 12px; top: 12px; z-index: 50; }
  .print-bar button {
    background: #176b66;
    border: 0;
    border-radius: 6px;
    color: #fff;
    cursor: pointer;
    font: inherit;
    font-weight: 700;
    padding: 8px 14px;
  }
  /* The book title sits above any chapter so it's already full width. */
  .book-head {
    margin-bottom: 6mm;
    padding-bottom: 3mm;
    text-align: center;
  }
  .book-head::after {
    background: #15181b;
    content: "";
    display: block;
    height: 1px;
    margin: 3mm auto 0;
    width: 26mm;
  }
  .book-title {
    font-family: "Georgia", "Source Serif Pro", serif;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 0.005em;
    line-height: 1.2;
  }
  .book-sub {
    color: #6a6f76;
    font-size: 10px;
    font-style: italic;
    margin-top: 1.5mm;
  }
  /* In the book layout every chapter starts on a new page. We tried packing
     chapters continuously (honoring the `pageBreakPerChapter: false` toggle)
     but column-flow + `column-span: all` + padding hacks all failed to
     stop chromium from stranding a chapter title at the bottom of a page
     with one line of content under it. A clean per-chapter page break is
     the only reliable way to keep the layout pretty. */
  .book-section + .book-section { break-before: page; }
  .chapter-head {
    break-after: avoid;
    break-inside: avoid;
    margin: 0 0 4mm;
    text-align: center;
  }
  .chapter-title {
    font-family: "Georgia", "Source Serif Pro", serif;
    font-size: 15px;
    font-variant: small-caps;
    font-weight: 700;
    letter-spacing: 0.06em;
  }
  .chapter-meta {
    color: #6a6f76;
    font-size: 10px;
    font-style: italic;
    margin-top: 1mm;
  }
  .chapter-intro {
    color: #15181b;
    font-size: 11px;
    line-height: 1.55;
    margin: 0 0 4mm;
    text-align: justify;
  }
  /* SAN runs read as justified book prose. Bold move numbers (via .mn)
     give the eye an anchor for each move pair without resorting to a
     monospaced font, which would clash with the serif body. */
  .book-run {
    font-family: inherit;
    font-size: 11px;
    hyphens: none;
    margin: 0 0 2mm;
    text-align: justify;
    text-indent: 4mm;
  }
  /* First paragraph after a heading or diagram follows book convention and
     drops the indent. */
  .chapter-intro + .book-run,
  .chapter-body > .book-run:first-child,
  .book-diagram + .book-run { text-indent: 0; }
  .book-run + .book-run { margin-top: -0.5mm; text-indent: 4mm; }
  .book-run .mn {
    font-feature-settings: "lnum" 1;
    font-weight: 700;
    white-space: nowrap;
  }
  /* A diagram-cell fills one grid slot. Its height is the row's height
     (78mm minimum, growing if the caption is long). `overflow: hidden`
     would clip long comments, so we deliberately leave it visible — the
     row simply gets taller for that row only. */
  .diagram-cell {
    align-items: center;
    break-inside: avoid;
    display: flex;
    flex-direction: column;
  }
  .preceding-run {
    color: #15181b;
    font-size: 10px;
    hyphens: none;
    line-height: 1.35;
    margin: 0 0 1mm;
    text-align: justify;
    width: 100%;
  }
  .preceding-run .mn { font-weight: 700; white-space: nowrap; }
  .book-diagram {
    align-items: center;
    break-inside: avoid;
    display: flex;
    flex-direction: column;
    margin: 0;
    text-align: center;
    width: 100%;
  }
  .bd-board {
    display: block;
    flex: 0 0 auto;
    max-width: 100%;
    width: 55mm;
  }
  .bd-board svg { display: block; height: auto; width: 100%; }
  .bd-caption {
    display: block;
    flex: 1 1 auto;
    margin: 1.5mm 0 0;
    max-width: 100%;
    overflow: hidden;
    width: 100%;
  }
  .bd-label {
    color: #15181b;
    display: block;
    font-size: 10px;
    font-style: italic;
    font-weight: 600;
    letter-spacing: 0.02em;
    margin-bottom: 0.5mm;
    text-align: center;
  }
  .bd-comment {
    color: #15181b;
    display: block;
    font-size: 10px;
    hyphens: none;
    line-height: 1.4;
    /* Justify in a narrow column produces ugly word gaps; left-align reads
       cleaner and matches how chess books typeset diagram captions. */
    text-align: left;
  }
  .diagram-cell.depth-1 .bd-comment,
  .diagram-cell.depth-2 .bd-comment,
  .diagram-cell.depth-3 .bd-comment {
    color: #2a2e33;
    font-style: italic;
  }
  /* Trailing SAN runs (after the last diagram in a chapter) span both
     grid columns so the moves don't end with awkward whitespace. */
  .trailing-runs {
    grid-column: 1 / -1;
  }
  .trailing-runs .book-run {
    font-size: 10.5px;
    margin: 0 0 2mm;
    text-align: justify;
    text-indent: 5mm;
  }
  @media print { .print-bar { display: none; } }
  /* See the study layout for why this exists: simulate a paper sheet on
     screen so the print-tuned mm sizes don't render against a raw browser
     viewport, and collapse the diagram row to a stack on phones. */
  @media screen {
    html { background: #e8e9ed; min-height: 100vh; }
    body {
      background: #fff;
      box-shadow: 0 8px 32px rgba(0,0,0,0.08);
      margin: 24px auto;
      max-width: 210mm;
      padding: 14mm 16mm 16mm;
    }
  }
  /* On phones a 2-cell grid would shrink each board too far, so fall back
     to a single-column flow with auto-height cells. */
  @media screen and (max-width: 720px) {
    body {
      box-shadow: none;
      margin: 0;
      max-width: none;
      padding: 16px 18px 32px;
    }
    .chapter-body {
      grid-auto-rows: auto;
      grid-template-columns: 1fr;
    }
    .bd-board { max-width: 280px; width: 70%; }
  }
</style>"""


def render_game_html(result: StudyResult, options: StudyOptions) -> str:
    """Render a game PGN as a compact diagram sheet: 8 boards per A4 page."""
    body: list[str] = []
    body.append("<!doctype html>")
    body.append("<html lang=\"en\">")
    body.append("<head>")
    body.append("<meta charset=\"utf-8\">")
    body.append("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
    body.append(f"<title>{text(result.title)}</title>")
    body.append(_game_style())
    body.append("</head>")
    body.append("<body>")

    body.append("<div class=\"print-bar\">")
    body.append("<button type=\"button\" onclick=\"window.print()\">인쇄 / PDF로 저장</button>")
    body.append("</div>")

    for index, chapter in enumerate(result.chapters):
        classes = ["game-section"]
        if index > 0:
            classes.append("page-start")
        body.append(f"<section class=\"{' '.join(classes)}\">")

        body.append("<div class=\"game-head\">")
        body.append(f"<div class=\"game-title\">{text(chapter.title)}</div>")
        meta_line = chapter.meta
        if chapter.site:
            link = f"<a href=\"{text(chapter.site)}\">{text(chapter.site)}</a>"
            meta_line = f"{meta_line} · {link}" if meta_line else link
        if meta_line:
            body.append(f"<div class=\"game-meta\">{meta_line}</div>")
        body.append("</div>")

        body.append("<div class=\"diagram-grid\">")
        for card in chapter.cards:
            body.append(f"<article class=\"diagram depth-{min(card.depth, 3)}\">")
            body.append(f"<div class=\"dg-label\">{text(card.label)}</div>")
            body.append(card.svg)
            body.append("</article>")
        body.append("</div>")
        body.append("</section>")

    body.append("</body>")
    body.append("</html>")
    return "\n".join(body)


def _game_style() -> str:
    # The A4 content box is 273mm tall. ~18mm is reserved for the game heading
    # (plus a 2mm print-rounding cushion) so the heading shares its page with
    # four rows of diagrams. Cards have a fixed height so every page tiles into
    # a 2 x 4 grid -> 8 diagrams per page, heading page included.
    card_height = round((273 - 2 - 18 - 3 * 5) / 4, 2)
    return f"""<style>
  @page {{ size: A4; margin: 12mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    color: #1f2933;
    font-family: Arial, Helvetica, sans-serif;
    font-size: 12px;
    margin: 0;
  }}
  a {{ color: #1f4f8f; text-decoration: none; }}
  .print-bar {{ position: fixed; right: 12px; top: 12px; z-index: 50; }}
  .print-bar button {{
    background: #176b66;
    border: 0;
    border-radius: 6px;
    color: #fff;
    cursor: pointer;
    font: inherit;
    font-weight: 700;
    padding: 8px 14px;
  }}
  .game-section {{ margin-top: 9mm; }}
  .game-section:first-of-type {{ margin-top: 0; }}
  .game-section.page-start {{ break-before: page; margin-top: 0; }}
  .game-head {{
    border-bottom: 2px solid #1f2933;
    break-after: avoid;
    margin-bottom: 4mm;
    padding-bottom: 2mm;
  }}
  .game-title {{ font-size: 17px; font-weight: 800; }}
  .game-meta {{ color: #52606d; font-size: 10px; margin-top: 1mm; }}
  .diagram-grid {{
    display: grid;
    grid-template-columns: repeat(2, 53mm);
    gap: 5mm 16mm;
    justify-content: center;
  }}
  /* Variation depth is shown with a grey shade so it survives mono printing. */
  .diagram {{
    border: 1px solid #c4ccd4;
    break-inside: avoid;
    height: {card_height}mm;
    min-height: 0;
    overflow: hidden;
    padding: 2mm;
    text-align: center;
  }}
  .diagram.depth-1 {{ background: #f2f3f4; }}
  .diagram.depth-2 {{ background: #eaebed; }}
  .diagram.depth-3 {{ background: #e2e4e7; }}
  .dg-label {{ font-size: 12px; font-weight: 700; margin-bottom: 1mm; }}
  .diagram svg {{ display: block; height: auto; margin: 0 auto; width: 100%; }}
  @media print {{ .print-bar {{ display: none; }} }}
  /* See the study layout: the print 2x4 grid uses fixed mm tile sizes that
     waste space (or clip) when rendered against a browser viewport instead
     of an A4 page. Wrap the body in a paper sheet on screen, stack on phones. */
  @media screen {{
    html {{ background: #e8e9ed; min-height: 100vh; }}
    body {{
      background: #fff;
      box-shadow: 0 8px 32px rgba(0,0,0,0.08);
      margin: 24px auto;
      max-width: 186mm;
      padding: 12mm;
    }}
    .diagram {{ height: auto; overflow: visible; }}
  }}
  @media screen and (max-width: 720px) {{
    body {{ box-shadow: none; margin: 0; max-width: none; padding: 12px 14px 32px; }}
    .diagram-grid {{ grid-template-columns: minmax(0, 320px); gap: 4mm; }}
    .diagram {{ width: 100%; }}
  }}
</style>"""


def study_options_from_request(source: dict) -> StudyOptions:
    def as_int(value: object, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def as_bool(value: object) -> bool:
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    raw_title = str(source.get("title") or "").strip()
    orientation = "black" if str(source.get("orientation") or "white").lower() == "black" else "white"
    raw_page_break = source.get("pageBreakPerChapter")
    page_break = True if raw_page_break is None else as_bool(raw_page_break)
    layout_raw = str(source.get("layout") or "study").lower()
    layout = layout_raw if layout_raw in ("study", "game", "book") else "study"
    return StudyOptions(
        title=raw_title or None,
        columns=max(1, min(5, as_int(source.get("columns"), 2))),
        orientation=orientation,
        mainline_only=as_bool(source.get("mainlineOnly")),
        max_variation_depth=max(0, as_int(source.get("maxVariationDepth"), 4)),
        page_break_per_chapter=page_break,
        layout=layout,
        book_max_run=max(1, as_int(source.get("maxMovesWithoutDiagram"), 6)),
        chapter_indices=parse_chapter_selection(source.get("chapters")),
        skip_uncommented=as_bool(source.get("skipUncommented")),
    )


def parse_chapter_selection(value: object) -> list[int] | None:
    """Parse a chapter selection like '1,3,5-7' into a sorted list of indices.

    Accepts the value as a string ('1,3'), a list (['1','3']) or None.
    Returns None when nothing is selected so the caller treats it as "all".
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        tokens = [str(v) for v in value]
    else:
        tokens = str(value).replace(";", ",").split(",")
    out: set[int] = set()
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            lo_s, hi_s = token.split("-", 1)
            try:
                lo, hi = int(lo_s), int(hi_s)
            except ValueError:
                continue
            if lo > hi:
                lo, hi = hi, lo
            out.update(range(max(1, lo), hi + 1))
        else:
            try:
                index = int(token)
            except ValueError:
                continue
            if index >= 1:
                out.add(index)
    return sorted(out) or None


def list_chapters_from_request(source: dict) -> list[dict]:
    """Fetch + parse a study's chapter list, for the chapter-picker UI.

    Accepts the same {study, pgn} inputs as render_study_from_request.
    """
    pgn_text = str(source.get("pgn") or "").strip()
    if not pgn_text:
        ref = str(source.get("study") or "").strip()
        if not ref:
            raise StudyError("Provide a Lichess study URL/id or PGN text.")
        pgn_text, _ = fetch_study(ref)
    return list_chapters(pgn_text)


def render_study_from_request(source: dict) -> str:
    """Build the printable study HTML from a web request dict (query or JSON).

    Accepts either a `study` URL/id or pasted `pgn` text. Raises StudyError for
    any user-facing problem.
    """
    options = study_options_from_request(source)

    pgn_text = str(source.get("pgn") or "").strip()
    if pgn_text:
        source_note = "pasted PGN"
    else:
        ref = str(source.get("study") or "").strip()
        if not ref:
            raise StudyError("Provide a Lichess study URL/id or PGN text.")
        pgn_text, source_note = fetch_study(ref)

    result = prepare_study(pgn_text, source_note, options)
    if result.diagram_count > MAX_REQUEST_DIAGRAMS:
        raise StudyError(
            f"This study renders {result.diagram_count} diagrams, over the "
            f"{MAX_REQUEST_DIAGRAMS} limit. Turn on main-line-only or pick a single chapter."
        )
    if options.layout == "game":
        return render_game_html(result, options)
    if options.layout == "book":
        return render_book_html(result, options)
    return render_study_html(result, options)


def error_page(message: str) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Study error</title></head>"
        "<body style=\"font-family:Arial,Helvetica,sans-serif;color:#1f2933;"
        "max-width:520px;margin:80px auto;padding:0 24px;line-height:1.5\">"
        "<h1 style=\"font-size:19px\">스터디를 만들 수 없습니다</h1>"
        f"<p>{text(message)}</p>"
        "<p><a href=\"/\" style=\"color:#176b66;font-weight:700\">← 도구 목록</a></p>"
        "</body></html>"
    )
