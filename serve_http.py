#!/usr/bin/env python3
"""Local JSON HTTP service for one Source vault/index pair.

Endpoints:
  GET  /health
  GET  /list
  GET  /search?q=...&k=...&mode=...&path=...&tags=a,b
  POST /ingest   {"notes": [{"id", "title", "tags", "text"}, ...]}
"""
from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import source_rag as R

HOST = "127.0.0.1"
MAX_BODY_BYTES = 1_000_000
MAX_NOTES = 100
ALLOWED_MODES = {"hybrid", "vector", "keyword"}
SEGMENT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
TAG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


class ServiceState:
    def __init__(self, vault: Path, db_path: Path, *, instance: str = R.INSTANCE,
                 model: str = R.DEFAULT_MODEL, reranker: str = R.DEFAULT_RERANKER,
                 exts: set[str] | None = None, cache_dir: Path = R.DEFAULT_MODELS,
                 builder=R.build, index_factory=R.Index, log=None):
        self.vault = Path(vault).expanduser().resolve()
        self.db_path = Path(db_path).expanduser().resolve()
        self.instance = instance
        self.model = model
        self.reranker = reranker
        self.exts = exts or set(R.DEFAULT_EXTS)
        self.cache_dir = Path(cache_dir).expanduser().resolve()
        self.builder = builder
        self.index_factory = index_factory
        self.log = log or (lambda *args: None)
        self.index = None
        self.meta = None
        if self.db_path.exists():
            self.reload_index()

    @property
    def ready(self) -> bool:
        return self.index is not None

    def close(self):
        if self.index is not None:
            self.index.close()
            self.index = None

    def set_index(self, index):
        old = self.index
        self.index = index
        self.meta = getattr(index, "meta", None)
        if old is not None and old is not index:
            old.close()

    def reload_index(self):
        new_index = self.index_factory(self.db_path)
        self.set_index(new_index)

    def rebuild_and_reload(self):
        meta = self.builder(self.vault, self.db_path, self.model, self.exts, self.cache_dir,
                            log=self.log, reranker=self.reranker, full=False)
        self.reload_index()
        self.meta = meta
        return meta

    def status_payload(self) -> dict:
        payload = {
            "ready": self.ready,
            "instance": self.instance,
            "vault": str(self.vault),
            "db": str(self.db_path),
        }
        if self.meta is not None:
            payload["meta"] = self.meta
        return payload


def make_server(state: ServiceState, *, host: str = HOST, port: int = 8000) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "SourceHTTP/0.1"

        def log_message(self, format, *args):
            return

        @property
        def state(self) -> ServiceState:
            return self.server.source_state

        def _send_json(self, status: int, payload: dict):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str):
            self._send_json(status, {"error": message})

        def _read_json(self):
            raw_len = self.headers.get("Content-Length")
            if raw_len is not None:
                try:
                    content_length = int(raw_len)
                except ValueError:
                    raise ValueError("invalid Content-Length")
                if content_length > MAX_BODY_BYTES:
                    remaining = content_length
                    while remaining > 0:
                        chunk = self.rfile.read(min(65536, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                    raise OverflowError("request body too large")
                raw = self.rfile.read(content_length)
            else:
                raw = self.rfile.read(MAX_BODY_BYTES + 1)
                if len(raw) > MAX_BODY_BYTES:
                    raise OverflowError("request body too large")
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("malformed JSON") from exc
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        def _require_ready(self) -> bool:
            if self.state.ready:
                return True
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, "index not ready")
            return False

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json(HTTPStatus.OK, self.state.status_payload())
                return
            if parsed.path == "/list":
                if not self._require_ready():
                    return
                payload = self.state.status_payload()
                payload["notes"] = self.state.index.list_notes()
                self._send_json(HTTPStatus.OK, payload)
                return
            if parsed.path == "/search":
                if not self._require_ready():
                    return
                self._handle_search(parsed.query)
                return
            self._error(HTTPStatus.NOT_FOUND, "not found")

        def _handle_search(self, query_string: str):
            params = parse_qs(query_string, keep_blank_values=True)
            query = (params.get("q", [""])[0] or "").strip()
            if not query:
                self._error(HTTPStatus.BAD_REQUEST, "q is required")
                return

            raw_k = params.get("k", [None])[0]
            if raw_k in (None, ""):
                k = 3
            else:
                try:
                    k = int(raw_k)
                except ValueError:
                    self._error(HTTPStatus.BAD_REQUEST, "k must be an integer")
                    return
                k = max(1, min(k, 20))

            mode = (params.get("mode", ["hybrid"])[0] or "hybrid").strip()
            if mode not in ALLOWED_MODES:
                self._error(HTTPStatus.BAD_REQUEST, "mode must be hybrid, vector, or keyword")
                return

            path_filter = params.get("path", [None])[0]
            tags = []
            for raw in params.get("tags", []):
                tags.extend(tag.strip() for tag in raw.split(",") if tag.strip())
            tags = tags or None

            hits = self.state.index.search(query, k, mode, path_filter, rerank=True, tags=tags)
            results = []
            for rank, hit in enumerate(hits, 1):
                item = {"rank": rank, **hit, "display": R.format_search_hit(hit, rank)}
                results.append(item)
            self._send_json(HTTPStatus.OK, {"results": results, "display": R.format_search_hits(results)})

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path != "/ingest":
                self._error(HTTPStatus.NOT_FOUND, "not found")
                return
            try:
                payload = self._read_json()
            except OverflowError as exc:
                self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, str(exc))
                return
            except ValueError as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
                return

            notes = payload.get("notes")
            if not isinstance(notes, list):
                self._error(HTTPStatus.BAD_REQUEST, "notes must be a list")
                return
            if not notes:
                self._error(HTTPStatus.BAD_REQUEST, "notes must not be empty")
                return
            if len(notes) > MAX_NOTES:
                self._error(HTTPStatus.BAD_REQUEST, f"too many notes; max {MAX_NOTES}")
                return

            try:
                validated = validate_notes(notes, self.state.vault)
            except ValueError as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
                return

            try:
                for note_path, note in validated:
                    note_path.parent.mkdir(parents=True, exist_ok=True)
                    note_path.write_text(render_markdown(note), encoding="utf-8")
                meta = self.state.rebuild_and_reload()
            except Exception:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "rebuild failed")
                return

            response = self.state.status_payload()
            response.update({"ingested": len(validated), "meta": meta})
            self._send_json(HTTPStatus.OK, response)

    server = HTTPServer((host, port), Handler)
    server.source_state = state
    return server


def validate_notes(notes: list[dict], vault: Path) -> list[tuple[Path, dict]]:
    seen_ids = set()
    out = []
    for note in notes:
        if not isinstance(note, dict):
            raise ValueError("each note must be an object")
        note_id = note.get("id")
        title = note.get("title")
        text = note.get("text")
        tags = note.get("tags", [])
        if not isinstance(note_id, str) or not note_id:
            raise ValueError("note id must be a non-empty string")
        if note_id in seen_ids:
            raise ValueError("duplicate note ids")
        seen_ids.add(note_id)
        if not isinstance(title, str) or not title.strip():
            raise ValueError("note title must be a non-empty string")
        if not isinstance(text, str):
            raise ValueError("note text must be a string")
        if tags is None:
            tags = []
        if not isinstance(tags, list) or not all(isinstance(tag, str) and valid_tag(tag) for tag in tags):
            raise ValueError("note tags must be slug strings")
        note_path = note_path_for_id(vault, note_id)
        out.append((note_path, {"id": note_id, "title": title.strip(), "text": text, "tags": tags}))
    return out


def valid_tag(tag: str) -> bool:
    return bool(tag) and all(ch in TAG_CHARS for ch in tag)


def note_path_for_id(vault: Path, note_id: str) -> Path:
    if "\\" in note_id or "\x00" in note_id:
        raise ValueError("invalid note id")
    rel = Path(note_id)
    if rel.is_absolute():
        raise ValueError("invalid note id")
    parts = rel.parts
    if not parts:
        raise ValueError("invalid note id")
    for part in parts:
        if part in {"", ".", ".."} or part.startswith(".") or any(ch not in SEGMENT_CHARS for ch in part):
            raise ValueError("invalid note id")
    note_path = (vault / rel).with_suffix(".md").resolve()
    try:
        note_path.relative_to(vault)
    except ValueError as exc:
        raise ValueError("invalid note id") from exc
    return note_path


def render_markdown(note: dict) -> str:
    lines = []
    if note["tags"]:
        lines.extend(["---", f"tags: [{', '.join(note['tags'])}]", "---"])
    lines.extend([f"# {note['title']}", "", note["text"]])
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault", default=os.environ.get(R.VAULT_ENV, str(R.DEFAULT_VAULT)))
    ap.add_argument("--db", default=os.environ.get(R.DB_ENV, str(R.DEFAULT_DB)))
    ap.add_argument("--port", type=int, default=7801)
    ap.add_argument("--model", default=R.DEFAULT_MODEL)
    ap.add_argument("--reranker", default=R.DEFAULT_RERANKER)
    ap.add_argument("--ext", default=",".join(sorted(R.DEFAULT_EXTS)))
    a = ap.parse_args(argv)

    exts = {e if e.startswith(".") else f".{e}" for e in a.ext.lower().split(",") if e}
    state = ServiceState(
        vault=Path(a.vault),
        db_path=Path(a.db),
        instance=R.INSTANCE,
        model=a.model,
        reranker=a.reranker,
        exts=exts,
    )
    server = make_server(state, port=a.port)
    print(f"serving {state.instance} on http://{HOST}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        state.close()


if __name__ == "__main__":
    main()
