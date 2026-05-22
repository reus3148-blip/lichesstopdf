"""Vercel serverless function: render a Lichess study as a printable HTML sheet.

Request (GET query string or POST JSON):
    study:             Lichess study URL or id (optionally with a chapter id)
    pgn:               raw PGN text (alternative to `study`)
    title:             optional document title
    orientation:       "white" (default) or "black"
    columns:           diagrams per row, 1-5 (default 3)
    mainlineOnly:      "true" to drop every variation
    maxVariationDepth: variation nesting limit (default 4)

Response: a complete printable HTML document (text/html). The shared rendering
core lives in study_core.py at the repo root.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study_core import StudyError, error_page, render_study_from_request


class handler(BaseHTTPRequestHandler):
    def _send_html(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _run(self, source: dict) -> None:
        try:
            self._send_html(200, render_study_from_request(source))
        except StudyError as exc:
            self._send_html(400, error_page(str(exc)))
        except Exception as exc:  # noqa: BLE001 - surface unexpected failures to the client
            self._send_html(500, error_page(f"Unexpected error: {exc}"))

    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        source = {key: values[0] for key, values in query.items() if values}
        self._run(source)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            if "form-urlencoded" in self.headers.get("Content-Type", ""):
                source = {key: values[0] for key, values in parse_qs(raw).items() if values}
            else:
                source = json.loads(raw or "{}")
                if not isinstance(source, dict):
                    raise ValueError("Request body must be a JSON object.")
        except Exception as exc:  # noqa: BLE001
            self._send_html(400, error_page(f"Invalid request body: {exc}"))
            return
        self._run(source)
