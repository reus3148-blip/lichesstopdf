"""Load a sampled subset of the Lichess puzzle CSV into a Postgres database.

The full Lichess puzzle database has millions of rows and does not fit in a
small managed Postgres instance. This script streams the CSV once, keeps a
uniform random sample of the rows that pass the rating/popularity filters
(reservoir sampling), and bulk-loads that sample into a `puzzles` table.

Run it locally once after creating the database:

    .\\.venv\\Scripts\\python.exe .\\import_puzzles.py

The connection string is read from the DATABASE_URL environment variable or a
local .env file.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import random
import sys
import time
from pathlib import Path

import psycopg


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "lichess_db_puzzle.csv.zst"
ENV_FILE = ROOT / ".env"

CSV_COLUMNS = {
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
}

COPY_COLUMNS = (
    "id",
    "fen",
    "moves",
    "rating",
    "rating_deviation",
    "popularity",
    "nb_plays",
    "themes",
    "game_url",
    "opening_tags",
    "rand",
)

COPY_TYPES = (
    "text",
    "text",
    "text",
    "int4",
    "int4",
    "int4",
    "int4",
    "text[]",
    "text",
    "text[]",
    "float8",
)


def load_database_url(explicit: str | None) -> str:
    if explicit:
        return explicit

    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "DATABASE_URL":
                return value.strip().strip('"').strip("'")

    raise SystemExit(
        "No database URL found. Set DATABASE_URL in the environment or in a .env file."
    )


def open_csv_text(path: Path) -> io.TextIOBase:
    if path.name.endswith(".zst"):
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load sampled Lichess puzzles into Postgres.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Lichess puzzle CSV or .csv.zst file.")
    parser.add_argument("--limit", type=int, default=200000, help="Number of puzzles to keep. Use 0 to keep all matching rows.")
    parser.add_argument("--min-popularity", type=int, default=80, help="Skip puzzles below this popularity score.")
    parser.add_argument("--min-rating", type=int, help="Skip puzzles below this rating.")
    parser.add_argument("--max-rating", type=int, help="Skip puzzles above this rating.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible sampling.")
    parser.add_argument("--database-url", help="Override the DATABASE_URL connection string.")
    return parser.parse_args()


def sample_rows(args: argparse.Namespace) -> list[tuple]:
    if not args.input.exists():
        raise SystemExit(f"Input file does not exist: {args.input}")

    rng = random.Random(args.seed)
    reservoir: list[tuple] = []
    scanned = 0
    matched = 0
    started = time.time()

    with open_csv_text(args.input) as file:
        reader = csv.DictReader(file)
        missing = CSV_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"Input CSV is missing required columns: {', '.join(sorted(missing))}")

        for row in reader:
            scanned += 1
            if scanned % 500000 == 0:
                print(f"  scanned {scanned:,} rows, kept {len(reservoir):,}")

            popularity = parse_int(row["Popularity"])
            if popularity < args.min_popularity:
                continue
            rating = parse_int(row["Rating"])
            if args.min_rating is not None and rating < args.min_rating:
                continue
            if args.max_rating is not None and rating > args.max_rating:
                continue

            record = (
                row["PuzzleId"],
                row["FEN"],
                row["Moves"],
                rating,
                parse_int(row["RatingDeviation"]),
                popularity,
                parse_int(row["NbPlays"]),
                row["Themes"].split(),
                row["GameUrl"],
                [tag for tag in row["OpeningTags"].split() if tag],
                rng.random(),
            )

            if args.limit <= 0 or len(reservoir) < args.limit:
                reservoir.append(record)
            else:
                slot = rng.randint(0, matched)
                if slot < args.limit:
                    reservoir[slot] = record
            matched += 1

    elapsed = time.time() - started
    print(f"Scanned {scanned:,} rows, {matched:,} matched filters, kept {len(reservoir):,} ({elapsed:.1f}s).")
    return reservoir


def create_schema(conn: psycopg.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS puzzles")
    conn.execute(
        """
        CREATE TABLE puzzles (
            id               text PRIMARY KEY,
            fen              text NOT NULL,
            moves            text NOT NULL,
            rating           integer NOT NULL,
            rating_deviation integer NOT NULL,
            popularity       integer NOT NULL,
            nb_plays         integer NOT NULL,
            themes           text[] NOT NULL,
            game_url         text NOT NULL,
            opening_tags     text[] NOT NULL,
            rand             double precision NOT NULL
        )
        """
    )


def load_rows(conn: psycopg.Connection, rows: list[tuple]) -> None:
    columns = ", ".join(COPY_COLUMNS)
    with conn.cursor() as cur:
        with cur.copy(f"COPY puzzles ({columns}) FROM STDIN") as copy:
            copy.set_types(COPY_TYPES)
            for row in rows:
                copy.write_row(row)


def create_indexes(conn: psycopg.Connection) -> None:
    conn.execute("CREATE INDEX puzzles_rating_idx ON puzzles (rating)")
    conn.execute("CREATE INDEX puzzles_popularity_idx ON puzzles (popularity)")
    conn.execute("CREATE INDEX puzzles_themes_idx ON puzzles USING gin (themes)")
    conn.execute("CREATE INDEX puzzles_rand_idx ON puzzles (rand)")


def main() -> int:
    args = parse_args()
    database_url = load_database_url(args.database_url)

    print(f"Reading {args.input}")
    rows = sample_rows(args)
    if not rows:
        raise SystemExit("No puzzles matched the filters. Nothing to import.")

    print("Connecting to the database...")
    with psycopg.connect(database_url) as conn:
        print("Creating the puzzles table...")
        create_schema(conn)
        print(f"Loading {len(rows):,} puzzles...")
        load_rows(conn, rows)
        print("Creating indexes...")
        create_indexes(conn)
        conn.commit()
        count = conn.execute("SELECT count(*) FROM puzzles").fetchone()[0]

    print(f"Done. {count:,} puzzles are now in the database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
