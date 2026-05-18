from __future__ import annotations

import argparse
import csv
import io
import json
import re
import time
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse

from make_puzzle_pdf import print_pdf, render_html, render_puzzle, select_puzzles


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
WEB_DIR = ROOT / "web"
LOCAL_WEB_DIR = ROOT / "local_web"

THEME_PRESETS = [
    "fork",
    "pin",
    "skewer",
    "mateIn1",
    "mateIn2",
    "mateIn3",
    "backRankMate",
    "smotheredMate",
    "sacrifice",
    "discoveredAttack",
    "doubleCheck",
    "deflection",
    "attraction",
    "hangingPiece",
    "trappedPiece",
    "endgame",
    "middlegame",
    "opening",
    "rookEndgame",
    "pawnEndgame",
    "promotion",
    "underPromotion",
    "advantage",
    "crushing",
    "equality",
    "short",
    "long",
    "veryLong",
]

PUZZLE_COLUMNS = [
    "PuzzleId",
    "FEN",
    "Moves",
    "Rating",
    "RatingDeviation",
    "Popularity",
    "NbPlays",
    "Themes",
    "GameUrl",
    "OpeningTags",
]


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return slug[:80] or "puzzles"


def json_response(handler: SimpleHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def data_files() -> list[dict[str, str | int]]:
    DATA_DIR.mkdir(exist_ok=True)
    files = []
    for path in sorted(DATA_DIR.iterdir()):
        if path.suffix == ".csv" or path.name.endswith(".csv.zst"):
            files.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size": path.stat().st_size,
                }
            )
    return files


def output_files() -> list[dict[str, str | int]]:
    OUTPUT_DIR.mkdir(exist_ok=True)
    files = []
    for path in sorted(OUTPUT_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        if path.suffix.lower() not in {".pdf", ".html"}:
            continue
        files.append(
            {
                "name": path.name,
                "url": f"/output/{path.name}",
                "size": path.stat().st_size,
            }
        )
    return files


def resolve_input_path(value: str) -> Path:
    if not value:
        raise ValueError("Choose a puzzle CSV file first.")

    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = DATA_DIR / value

    resolved = candidate.resolve()
    if not resolved.exists():
        raise ValueError(f"Input file does not exist: {resolved}")
    if resolved.suffix != ".csv" and not resolved.name.endswith(".csv.zst"):
        raise ValueError("Input must be a .csv or .csv.zst file.")
    return resolved


def safe_data_csv_path(value: str) -> Path:
    filename = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(value or "").name).strip("-")
    if not filename:
        filename = "local_workspace.csv"
    if not filename.lower().endswith(".csv"):
        filename += ".csv"

    target = (DATA_DIR / filename).resolve()
    if DATA_DIR.resolve() not in target.parents:
        raise ValueError("CSV workspace must be saved inside the data folder.")
    return target


def optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def payload_themes(payload: dict) -> list[str]:
    themes = [str(theme).strip() for theme in payload.get("themes", []) if str(theme).strip()]
    custom_theme = str(payload.get("customTheme", "")).strip()
    if custom_theme:
        themes.extend(part.strip() for part in custom_theme.split(",") if part.strip())
    return themes


def selection_args(payload: dict, input_path: Path, max_count: int = 200) -> SimpleNamespace:
    count = int(payload.get("count") or 10)
    if count < 1 or count > max_count:
        raise ValueError(f"Count must be between 1 and {max_count}.")

    return SimpleNamespace(
        input=input_path,
        theme=payload_themes(payload),
        match=str(payload.get("match") or "any"),
        min_rating=optional_int(payload.get("minRating")),
        max_rating=optional_int(payload.get("maxRating")),
        min_popularity=optional_int(payload.get("minPopularity")),
        count=count,
        seed=int(payload.get("seed") or 42),
    )


def puzzle_row(puzzle: object) -> dict[str, str | int]:
    return {
        "PuzzleId": puzzle.puzzle_id,
        "FEN": puzzle.fen,
        "Moves": puzzle.moves,
        "Rating": puzzle.rating,
        "RatingDeviation": puzzle.rating_deviation,
        "Popularity": puzzle.popularity,
        "NbPlays": puzzle.nb_plays,
        "Themes": " ".join(puzzle.themes),
        "GameUrl": puzzle.game_url,
        "OpeningTags": " ".join(puzzle.opening_tags),
    }


def puzzles_csv(puzzles: list[object]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=PUZZLE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for puzzle in puzzles:
        writer.writerow(puzzle_row(puzzle))
    return output.getvalue()


def preview_puzzles(payload: dict) -> dict:
    input_path = resolve_input_path(str(payload.get("input", "")))
    args = selection_args(payload, input_path, max_count=500)
    selected = select_puzzles(input_path, args)
    rows = [puzzle_row(puzzle) for puzzle in selected]
    return {
        "count": len(rows),
        "input": input_path.name,
        "puzzles": rows,
        "csvText": puzzles_csv(selected),
    }


def save_workspace_csv(payload: dict) -> dict:
    csv_text = str(payload.get("csvText") or "").strip()
    if not csv_text:
        raise ValueError("CSV text is empty.")

    reader = csv.DictReader(io.StringIO(csv_text))
    missing = set(PUZZLE_COLUMNS) - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")

    rows = list(reader)
    if not rows:
        raise ValueError("CSV must contain at least one puzzle row.")

    target = safe_data_csv_path(str(payload.get("filename") or "local_workspace.csv"))
    target.write_text(csv_text + "\n", encoding="utf-8")
    return {
        "name": target.name,
        "path": str(target),
        "size": target.stat().st_size,
        "rows": len(rows),
    }


def build_pdf(payload: dict) -> dict:
    themes = payload_themes(payload)
    title = str(payload.get("title") or "Lichess Puzzle Set").strip()
    input_path = resolve_input_path(str(payload.get("input", "")))
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    label = slugify("-".join(themes) if themes else title)
    pdf_path = OUTPUT_DIR / f"{timestamp}-{label}.pdf"
    html_path = pdf_path.with_suffix(".html")
    args = selection_args(payload, input_path)
    selected = select_puzzles(input_path, args)
    rendered = []
    skipped = []
    for puzzle in selected:
        try:
            rendered.append(render_puzzle(puzzle))
        except Exception as exc:
            skipped.append({"puzzleId": puzzle.puzzle_id, "reason": str(exc)})

    if not rendered:
        raise ValueError("No selected puzzles could be rendered.")

    html_only = bool(payload.get("htmlOnly"))
    solutions_at_end = bool(payload.get("solutionsAtEnd"))
    split_output = bool(payload.get("splitOutput"))
    layout = str(payload.get("layout") or "print-minimal")

    result = {"count": len(rendered), "skipped": skipped}
    if split_output:
        questions_html = OUTPUT_DIR / f"{timestamp}-{label}-questions.html"
        answers_html = OUTPUT_DIR / f"{timestamp}-{label}-answers.html"
        questions_pdf = questions_html.with_suffix(".pdf")
        answers_pdf = answers_html.with_suffix(".pdf")

        questions_html.write_text(
            render_html(title, rendered, include_questions=True, include_solutions=False, layout=layout),
            encoding="utf-8",
        )
        answers_html.write_text(
            render_html(
                f"{title} - Answers",
                rendered,
                include_questions=False,
                include_solutions=True,
                layout="instagram" if layout == "instagram" else "standard",
            ),
            encoding="utf-8",
        )
        result["questionsHtmlUrl"] = f"/output/{questions_html.name}"
        result["answersHtmlUrl"] = f"/output/{answers_html.name}"
        result["questionsHtmlPath"] = str(questions_html)
        result["answersHtmlPath"] = str(answers_html)
        if not html_only:
            print_pdf(questions_html, questions_pdf, None)
            print_pdf(answers_html, answers_pdf, None)
            result["questionsPdfUrl"] = f"/output/{questions_pdf.name}"
            result["answersPdfUrl"] = f"/output/{answers_pdf.name}"
            result["questionsPdfPath"] = str(questions_pdf)
            result["answersPdfPath"] = str(answers_pdf)
    else:
        html_path.write_text(render_html(title, rendered, solutions_at_end, layout=layout), encoding="utf-8")
        result["htmlUrl"] = f"/output/{html_path.name}"
        result["htmlPath"] = str(html_path)
        if not html_only:
            print_pdf(html_path, pdf_path, None)
            result["pdfUrl"] = f"/output/{pdf_path.name}"
            result["pdfPath"] = str(pdf_path)
    return result


class LocalAppHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path in {"/", "/local.html"}:
            self.serve_file(LOCAL_WEB_DIR / "local.html", "text/html; charset=utf-8")
            return

        if path == "/index.html":
            self.serve_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
            return

        if path == "/api/status":
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "dataFiles": data_files(),
                    "outputFiles": output_files(),
                    "themePresets": THEME_PRESETS,
                },
            )
            return

        if path == "/api/sample-command":
            query = parse_qs(parsed.query)
            theme = query.get("theme", ["fork"])[0]
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "command": (
                        ".\\.venv\\Scripts\\python.exe .\\make_puzzle_pdf.py "
                        f"--input .\\data\\sample_puzzles.csv --theme {theme} --count 2 "
                        f"--output .\\output\\{slugify(theme)}_sample.pdf"
                    )
                },
            )
            return

        if path.startswith("/output/"):
            target = (OUTPUT_DIR / path.removeprefix("/output/")).resolve()
            if OUTPUT_DIR.resolve() not in target.parents and target != OUTPUT_DIR.resolve():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not target.exists() or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = "application/pdf" if target.suffix.lower() == ".pdf" else "text/html; charset=utf-8"
            self.serve_file(target, content_type)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/generate", "/api/preview", "/api/save-csv"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")

            if parsed.path == "/api/preview":
                result = preview_puzzles(payload)
                json_response(self, HTTPStatus.OK, {"ok": True, **result})
                return

            if parsed.path == "/api/save-csv":
                result = save_workspace_csv(payload)
                json_response(self, HTTPStatus.OK, {"ok": True, **result, "dataFiles": data_files()})
                return

            result = build_pdf(payload)
            result["outputFiles"] = output_files()
            json_response(self, HTTPStatus.OK, {"ok": True, **result})
        except SystemExit as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except Exception as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def serve_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[local-app] {self.address_string()} - {format % args}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Lichess PDF Maker web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    LOCAL_WEB_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), LocalAppHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Lichess PDF Maker local UI: {url}")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping local UI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
