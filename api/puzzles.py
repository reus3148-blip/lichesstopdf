"""Vercel serverless function: return puzzles matching filter criteria.

Reads from the `puzzles` table populated by import_puzzles.py. The database
connection string comes from the DATABASE_URL environment variable, set in the
Vercel project settings.

Request (POST JSON or GET query string):
    themes:        list of Lichess themes, or comma-separated string
    match:         "any" (default) or "all"
    minRating, maxRating, minPopularity: integers
    count:         number of puzzles to return (1-50)
    seed:          optional integer for reproducible sampling

Response JSON:
    {"count": N, "puzzles": [{id, fen, moves, rating, popularity,
                              themes, gameUrl, opening}, ...]}
"""

from __future__ import annotations

import json
import os
import random
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import chess
import psycopg


MAX_COUNT = 50
SELECT_COLUMNS = "id, fen, moves, rating, popularity, themes, game_url, opening_tags"


def to_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_themes(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        parts = []
        for item in raw:
            parts.extend(str(item).split(","))
    else:
        return []
    return [part.strip() for part in parts if part.strip()]


def build_filters(source: dict) -> dict:
    count = to_int(source.get("count")) or 10
    count = max(1, min(MAX_COUNT, count))
    seed = to_int(source.get("seed"))
    if seed is None:
        seed = random.randrange(1_000_000_000)
    match = str(source.get("match") or "any").lower()
    if match not in ("any", "all"):
        match = "any"
    return {
        "themes": normalize_themes(source.get("themes") if "themes" in source else source.get("theme")),
        "match": match,
        "min_rating": to_int(source.get("minRating")),
        "max_rating": to_int(source.get("maxRating")),
        "min_popularity": to_int(source.get("minPopularity")),
        "count": count,
        "seed": seed,
    }


def opening_name(opening_tags: list[str]) -> str:
    if not opening_tags:
        return ""
    return opening_tags[0].replace("_", " ")


def solution_san(fen: str, moves: str) -> list[str] | None:
    """Standard algebraic notation for the solution moves.

    The first UCI move is the opponent's setup move and is not part of the
    solution, so it is played to advance the board but excluded from output.
    Returns None on any parsing failure so the client can fall back to UCI.
    """
    try:
        board = chess.Board(fen)
        san_moves: list[str] = []
        for index, uci in enumerate(moves.split()):
            move = chess.Move.from_uci(uci)
            san = board.san(move)
            board.push(move)
            if index >= 1:
                san_moves.append(san)
        return san_moves
    except Exception:  # noqa: BLE001 - fall back to UCI on any bad data
        return None


def query_puzzles(filters: dict) -> list[dict]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")

    where: list[str] = []
    params: dict = {}
    if filters["min_rating"] is not None:
        where.append("rating >= %(min_rating)s")
        params["min_rating"] = filters["min_rating"]
    if filters["max_rating"] is not None:
        where.append("rating <= %(max_rating)s")
        params["max_rating"] = filters["max_rating"]
    if filters["min_popularity"] is not None:
        where.append("popularity >= %(min_popularity)s")
        params["min_popularity"] = filters["min_popularity"]
    if filters["themes"]:
        operator = "@>" if filters["match"] == "all" else "&&"
        where.append(f"themes {operator} %(themes)s::text[]")
        params["themes"] = filters["themes"]

    where_sql = " AND ".join(where)
    prefix = f"SELECT {SELECT_COLUMNS} FROM puzzles WHERE "
    prefix += (where_sql + " AND ") if where_sql else ""
    anchor = random.Random(filters["seed"]).random()
    count = filters["count"]

    rows: list[tuple] = []
    with psycopg.connect(database_url, connect_timeout=10) as conn:
        first = conn.execute(
            prefix + "rand >= %(anchor)s ORDER BY rand LIMIT %(count)s",
            {**params, "anchor": anchor, "count": count},
        ).fetchall()
        rows.extend(first)
        if len(rows) < count:
            wrap = conn.execute(
                prefix + "rand < %(anchor)s ORDER BY rand LIMIT %(count)s",
                {**params, "anchor": anchor, "count": count - len(rows)},
            ).fetchall()
            rows.extend(wrap)

    puzzles = []
    for row in rows:
        puzzle_id, fen, moves, rating, popularity, themes, game_url, opening_tags = row
        puzzles.append(
            {
                "id": puzzle_id,
                "fen": fen,
                "moves": moves,
                "rating": rating,
                "popularity": popularity,
                "themes": list(themes),
                "gameUrl": game_url,
                "opening": opening_name(list(opening_tags)),
                "san": solution_san(fen, moves),
            }
        )
    return puzzles


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, source: dict) -> None:
        try:
            filters = build_filters(source)
            puzzles = query_puzzles(filters)
            self._send(200, {"count": len(puzzles), "puzzles": puzzles})
        except RuntimeError as exc:
            self._send(500, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - surface DB/parse errors to the client
            self._send(500, {"error": f"Puzzle query failed: {exc}"})

    def do_OPTIONS(self) -> None:
        self._send(204, {})

    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        source = {key: values for key, values in query.items()}
        for key, values in list(source.items()):
            if key not in ("themes", "theme") and len(values) == 1:
                source[key] = values[0]
        self._handle(source)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            source = json.loads(raw or "{}")
            if not isinstance(source, dict):
                raise ValueError("Request body must be a JSON object.")
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": f"Invalid request body: {exc}"})
            return
        self._handle(source)
