import hashlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

import source_rag as R


class FakeEmbedder:
    model_name = "fake"
    dim = 16

    def _vec(self, text: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        v = np.random.default_rng(seed).standard_normal(self.dim).astype(np.float32)
        return v / (np.linalg.norm(v) or 1.0)

    def passages(self, texts):
        return (np.vstack([self._vec(t) for t in texts]) if texts
                else np.zeros((0, self.dim), dtype=np.float32))

    def query(self, text):
        return self._vec(text)


@pytest.fixture
def serve_http_module():
    import serve_http

    return serve_http


@contextmanager
def running_server(serve_http_module, state):
    server = serve_http_module.make_server(state, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        state.close()


class RecordingIndex:
    def __init__(self):
        self.meta = {"built_at": "2026-01-01 00:00:00", "files": 1, "chunks": 1}
        self.calls = []

    def search(self, query, k, mode, path_filter=None, rerank=True, tags=None):
        self.calls.append({
            "query": query,
            "k": k,
            "mode": mode,
            "path_filter": path_filter,
            "rerank": rerank,
            "tags": tags,
        })
        if query == "miss":
            return []
        return [{"path": "guide.md", "heading": "Guide", "score": 7.5, "text": "Matched text", "tags": "alpha beta"}]

    def list_notes(self):
        return [{"path": "guide.md", "chunks": 1}]

    def close(self):
        pass


def request_json(url, *, method="GET", payload=None, expect_status=200):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {} if payload is None else {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read()
            assert resp.status == expect_status
            return resp.status, json.loads(body.decode())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        assert exc.code == expect_status, body.decode()
        return exc.code, json.loads(body.decode())


def build_service_state(serve_http_module, vault: Path, db: Path, *, fake=None, instance="source", builder=None):
    fake = fake or FakeEmbedder()

    def build_index(selected_vault, selected_db, model, exts, cache_dir, *, log, reranker, full=False):
        return R.build(selected_vault, selected_db, model, exts, cache_dir,
                       log=log, reranker="none", full=full, embedder=fake)

    return serve_http_module.ServiceState(
        vault=vault,
        db_path=db,
        instance=instance,
        builder=builder or build_index,
        index_factory=lambda path: R.Index(path, embedder=fake),
        reranker="none",
    )


def seed_index(vault: Path, db: Path, *, fake=None):
    fake = fake or FakeEmbedder()
    return R.build(vault, db, "fake", {".md"}, vault / "models",
                   log=lambda *args: None, reranker="none", embedder=fake)


def test_health_and_list_return_instance_and_index_state(tmp_path, serve_http_module):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "guide.md").write_text("# Guide\n\nAlpha note body with locale guidance.\n")
    db = tmp_path / "idx.sqlite"
    seed_index(vault, db)

    state = build_service_state(serve_http_module, vault, db, instance="eng-a")
    with running_server(serve_http_module, state) as base_url:
        _, health = request_json(f"{base_url}/health")
        assert health["ready"] is True
        assert health["instance"] == "eng-a"
        assert health["vault"] == str(vault.resolve())
        assert health["db"] == str(db.resolve())
        assert health["meta"]["files"] == 1

        _, listing = request_json(f"{base_url}/list")
        assert listing["ready"] is True
        assert listing["instance"] == "eng-a"
        assert listing["notes"] == [{"path": "guide.md", "chunks": 1}]
        assert listing["meta"]["chunks"] == 1


def test_search_endpoint_formats_filters_and_validates_params(tmp_path, serve_http_module):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "idx.sqlite"
    index = RecordingIndex()
    state = serve_http_module.ServiceState(vault=vault, db_path=db, instance="eng-a")
    state.set_index(index)

    with running_server(serve_http_module, state) as base_url:
        _, body = request_json(
            f"{base_url}/search?q=needle&k=99&mode=keyword&path=refs&tags=alpha,beta"
        )
        assert index.calls[-1] == {
            "query": "needle",
            "k": 20,
            "mode": "keyword",
            "path_filter": "refs",
            "rerank": True,
            "tags": ["alpha", "beta"],
        }
        assert body["display"] == R.format_search_hits(body["results"])
        assert body["results"][0]["rank"] == 1
        assert body["results"][0]["display"].startswith("### [1] guide.md › Guide")

        _, miss = request_json(f"{base_url}/search?q=miss")
        assert miss == {"results": [], "display": "no matches"}

        request_json(f"{base_url}/search", expect_status=400)
        request_json(f"{base_url}/search?q=   ", expect_status=400)
        request_json(f"{base_url}/search?q=x&k=abc", expect_status=400)
        request_json(f"{base_url}/search?q=x&mode=nope", expect_status=400)


def test_ingest_writes_markdown_rebuilds_reloads_and_searches(tmp_path, serve_http_module):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "idx.sqlite"
    build_calls = []
    fake = FakeEmbedder()

    def builder(selected_vault, selected_db, model, exts, cache_dir, *, log, reranker, full=False):
        build_calls.append({
            "vault": selected_vault,
            "db": selected_db,
            "model": model,
            "exts": exts,
            "cache_dir": cache_dir,
            "reranker": reranker,
            "full": full,
        })
        return R.build(selected_vault, selected_db, model, exts, cache_dir,
                       log=log, reranker="none", full=full, embedder=fake)

    state = serve_http_module.ServiceState(
        vault=vault,
        db_path=db,
        builder=builder,
        index_factory=lambda path: R.Index(path, embedder=fake),
        reranker="none",
    )

    with running_server(serve_http_module, state) as base_url:
        _, body = request_json(
            f"{base_url}/ingest",
            method="POST",
            payload={
                "notes": [{
                    "id": "findings/host-1",
                    "title": "Host 1",
                    "tags": ["finding", "critical"],
                    "text": "SSRF on the admin endpoint.",
                }],
            },
        )
        assert body["ingested"] == 1
        note_path = vault / "findings" / "host-1.md"
        assert note_path.read_text() == (
            "---\n"
            "tags: [finding, critical]\n"
            "---\n"
            "# Host 1\n\n"
            "SSRF on the admin endpoint.\n"
        )
        assert len(build_calls) == 1
        assert build_calls[0]["vault"] == vault
        assert build_calls[0]["db"] == db

        _, search = request_json(f"{base_url}/search?q=SSRF&mode=keyword")
        assert search["results"][0]["path"] == "findings/host-1.md"

        _, listing = request_json(f"{base_url}/list")
        assert listing["notes"] == [{"path": "findings/host-1.md", "chunks": 1}]


def test_ingest_is_idempotent_upsert_and_isolated_by_vault(tmp_path, serve_http_module):
    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    vault_a.mkdir()
    vault_b.mkdir()
    db_a = tmp_path / "a.sqlite"
    db_b = tmp_path / "b.sqlite"

    state_a = build_service_state(serve_http_module, vault_a, db_a, instance="eng-a")
    state_b = build_service_state(serve_http_module, vault_b, db_b, instance="eng-b")

    with running_server(serve_http_module, state_a) as url_a, running_server(serve_http_module, state_b) as url_b:
        note = {
            "id": "memories/entry",
            "title": "Entry",
            "tags": ["memory"],
            "text": "Original content.",
        }
        request_json(f"{url_a}/ingest", method="POST", payload={"notes": [note]})

        note["text"] = "Updated content only in vault A."
        request_json(f"{url_a}/ingest", method="POST", payload={"notes": [note]})

        _, list_a = request_json(f"{url_a}/list")
        assert list_a["notes"] == [{"path": "memories/entry.md", "chunks": 1}]
        assert (vault_a / "memories" / "entry.md").read_text().endswith("Updated content only in vault A.\n")

        _, search_a = request_json(f"{url_a}/search?q=Updated&mode=keyword")
        assert search_a["results"][0]["text"] == "Updated content only in vault A."

        _, list_b = request_json(f"{url_b}/health")
        assert list_b["ready"] is False
        request_json(f"{url_b}/search?q=Updated", expect_status=503)


def test_ingest_requires_application_json_and_avoids_writes_or_rebuild(tmp_path, serve_http_module):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "idx.sqlite"
    build_calls = []

    def builder(*args, **kwargs):
        build_calls.append((args, kwargs))
        return {"files": 0, "chunks": 0}

    state = serve_http_module.ServiceState(vault=vault, db_path=db, builder=builder)

    with running_server(serve_http_module, state) as base_url:
        body = json.dumps({
            "notes": [{"id": "plain", "title": "Plain", "text": "browser simple request"}]
        }).encode()
        for headers in ({}, {"Content-Type": "text/plain; charset=utf-8"}):
            req = urllib.request.Request(
                f"{base_url}/ingest",
                data=body,
                headers=headers,
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                urllib.request.urlopen(req, timeout=5)
            assert excinfo.value.code == 415

    assert build_calls == []
    assert list(vault.rglob("*.md")) == []


def test_ingest_accepts_dotted_ids_and_rejects_duplicate_targets(tmp_path, serve_http_module):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "real").mkdir()
    (vault / "alias").symlink_to(vault / "real", target_is_directory=True)
    db = tmp_path / "idx.sqlite"
    build_calls = []

    def builder(selected_vault, selected_db, model, exts, cache_dir, *, log, reranker, full=False):
        build_calls.append(selected_vault)
        return R.build(selected_vault, selected_db, model, exts, cache_dir,
                       log=log, reranker="none", full=full, embedder=FakeEmbedder())

    state = serve_http_module.ServiceState(
        vault=vault,
        db_path=db,
        builder=builder,
        index_factory=lambda path: R.Index(path, embedder=FakeEmbedder()),
        reranker="none",
    )

    with running_server(serve_http_module, state) as base_url:
        request_json(
            f"{base_url}/ingest",
            method="POST",
            payload={"notes": [{"id": "releases/v1.2", "title": "Version 1.2", "text": "Dotted id works."}]},
        )
        assert (vault / "releases" / "v1.2.md").read_text().endswith("Dotted id works.\n")
        assert not (vault / "releases" / "v1.md").exists()

        request_json(
            f"{base_url}/ingest",
            method="POST",
            payload={
                "notes": [
                    {"id": "real/note", "title": "First", "text": "one"},
                    {"id": "alias/note", "title": "Second", "text": "two"},
                ]
            },
            expect_status=400,
        )

    assert len(build_calls) == 1
    assert not (vault / "real" / "note.md").exists()


def test_ingest_rejects_malformed_duplicate_traversal_and_oversize_without_writes(tmp_path, serve_http_module):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "idx.sqlite"
    state = build_service_state(serve_http_module, vault, db)

    with running_server(serve_http_module, state) as base_url:
        bad_json_req = urllib.request.Request(
            f"{base_url}/ingest",
            data=b"{not-json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(bad_json_req, timeout=5)
        assert excinfo.value.code == 400

        request_json(f"{base_url}/ingest", method="POST", payload={"notes": []}, expect_status=400)
        request_json(
            f"{base_url}/ingest",
            method="POST",
            payload={"notes": [{"id": "dup", "title": "A", "text": "x"}, {"id": "dup", "title": "B", "text": "y"}]},
            expect_status=400,
        )
        request_json(
            f"{base_url}/ingest",
            method="POST",
            payload={"notes": [{"id": "../escape", "title": "Oops", "text": "x"}]},
            expect_status=400,
        )

        oversized = b"x" * (serve_http_module.MAX_BODY_BYTES + 1)
        req = urllib.request.Request(
            f"{base_url}/ingest",
            data=oversized,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=5)
        assert excinfo.value.code == 413

    assert list(vault.rglob("*.md")) == []


def test_rebuild_failure_returns_500_and_keeps_old_index(tmp_path, serve_http_module):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "guide.md").write_text("# Guide\n\nExisting indexed note.\n")
    db = tmp_path / "idx.sqlite"
    fake = FakeEmbedder()
    seed_index(vault, db, fake=fake)

    def failing_builder(*args, **kwargs):
        raise RuntimeError("boom")

    state = serve_http_module.ServiceState(
        vault=vault,
        db_path=db,
        builder=failing_builder,
        index_factory=lambda path: R.Index(path, embedder=fake),
        reranker="none",
    )

    with running_server(serve_http_module, state) as base_url:
        request_json(
            f"{base_url}/ingest",
            method="POST",
            payload={"notes": [{"id": "new", "title": "New", "text": "fresh content"}]},
            expect_status=500,
        )

        _, search = request_json(f"{base_url}/search?q=Existing&mode=keyword")
        assert search["results"][0]["path"] == "guide.md"

        _, miss = request_json(f"{base_url}/search?q=fresh&mode=keyword")
        assert miss == {"results": [], "display": "no matches"}

        _, listing = request_json(f"{base_url}/list")
        assert listing["notes"] == [{"path": "guide.md", "chunks": 1}]
