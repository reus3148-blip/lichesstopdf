"""Vercel serverless function: list a Lichess study's chapters as JSON.

Used by the chapter-picker UI. Same inputs as /api/study (study URL/id or pgn
text), but returns a JSON list [{index, name, meta}, ...] instead of a rendered
study page so the UI can let the user pick a subset to print.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study_core import StudyError, list_chapters_from_request


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _run(self, source: dict) -> None:
        try:
            chapters = list_chapters_from_request(source)
            self._send_json(200, {"ok": True, "chapters": chapters})
        except StudyError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"ok": False, "error": f"Unexpected error: {exc}"})

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
            self._send_json(400, {"ok": False, "error": f"Invalid request body: {exc}"})
            return
        self._run(source)
