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
    columns: int = 3
    orientation: str = "white"
    mainline_only: bool = False
    max_variation_depth: int = 4
    page_break_per_chapter: bool = True

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


def prepare_study(pgn_text: str, source_note: str, options: StudyOptions) -> StudyResult:
    games = read_games(pgn_text)
    if not games:
        raise StudyError("No chapters were found in the PGN.")

    study_name = ""
    chapters: list[Chapter] = []
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
        classes = ["study-section"]
        # Short chapters are kept whole so a heading is never stranded at a
        # page bottom; long ones flow so they are not clipped.
        if len(chapter.cards) <= 2 * options.columns:
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
        for card in chapter.cards:
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
  .move-card {{
    border: 1px solid #d1d5db;
    border-left-width: 4px;
    break-inside: avoid;
    padding: 2mm;
  }}
  .move-card.depth-0 {{ border-left-color: #1f2933; }}
  .move-card.depth-1 {{ border-left-color: #2563eb; background: #f3f7ff; }}
  .move-card.depth-2 {{ border-left-color: #7c3aed; background: #f7f3ff; }}
  .move-card.depth-3 {{ border-left-color: #d97706; background: #fff7ed; }}
  .mv-label {{ font-size: 12px; font-weight: 700; margin-bottom: 1.5mm; }}
  .move-card svg {{ display: block; height: auto; width: 100%; }}
  .mv-comment {{
    color: #3a4754;
    font-size: 10px;
    line-height: 1.35;
    margin-top: 1.5mm;
  }}
  @media print {{ .print-bar {{ display: none; }} }}
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
    return StudyOptions(
        title=raw_title or None,
        columns=max(1, min(5, as_int(source.get("columns"), 3))),
        orientation=orientation,
        mainline_only=as_bool(source.get("mainlineOnly")),
        max_variation_depth=max(0, as_int(source.get("maxVariationDepth"), 4)),
        page_break_per_chapter=page_break,
    )


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
    return render_study_html(result, options)


def error_page(message: str) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Study error</title></head>"
        "<body style=\"font-family:Arial,Helvetica,sans-serif;color:#1f2933;"
        "max-width:520px;margin:80px auto;padding:0 24px;line-height:1.5\">"
        "<h1 style=\"font-size:19px\">스터디를 만들 수 없습니다</h1>"
        f"<p>{text(message)}</p>"
        "<p><a href=\"/opening\" style=\"color:#176b66;font-weight:700\">← 다시 시도</a></p>"
        "</body></html>"
    )
