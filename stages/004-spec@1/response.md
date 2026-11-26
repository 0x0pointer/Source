DECISION NEEDED: `/search` could be MCP text, structured JSON, or both; choose structured JSON plus a `display` string from the same formatter as MCP, preserving compact rendering while making HTTP parseable.

1. Intent
Add a stdlib-only localhost HTTP service for one Source `{vault, db}` instance. It must search/list an already built index, ingest mechanical-memory notes as Markdown, refresh the existing incremental SQLite index, and reload it. Add `INSTANCE` identity, default `source`, for service self-reporting without breaking existing CLI/MCP defaults.

2. Acceptance criteria
1. `INSTANCE` unset keeps existing `source` behavior; `INSTANCE=eng-a` makes `GET /health` return `instance: "eng-a"`.
2. `serve_http.py --vault V --db D --port P` and `run_instance.sh NAME --vault V --db D --port P` serve only on `127.0.0.1:P` and use that vault/db.
3. `GET /search?q=...&k=&mode=&path=&tags=` returns `200 application/json` with `results` entries containing rank/path/heading/score/text/tags/display and top-level `display`; display text matches MCP `path › heading` snippets, and no hits returns `results: []`, `display: "no matches"`.
4. `GET /list` returns indexed notes plus metadata; `GET /health` returns readiness, instance, vault, db, and metadata when present.
5. `POST /ingest` `{notes:[{id,title,tags,text}]}` writes valid notes to `vault/<id>.md`, creates id subdirectories, calls incremental `source_rag.build(...)`, reloads the index, and makes notes searchable/listed.
6. Reposting the same `id` overwrites one file/index entry; two services with different vault/db/ports remain isolated.
7. Existing `build_index.py`, `query.py`, and `mcp_server.py` behavior remains, including incremental reuse, path/tag filtering, and MCP output text.
8. README documents multi-instance agent-smith usage and endpoint shapes; no new runtime dependency is added.

3. Boundaries
Always: use stdlib `http.server`/`json`; use `R.VAULT_ENV`, `R.DB_ENV`, `R.DEFAULT_*`, `R.build`, `R.Index.search`, `R.Index.list_notes`; share search display formatting through `source_rag.py`.
Never: add HTTP framework/deps, bind beyond localhost, change CI/deployment, remove/limit CLI or MCP, or write/index outside the selected vault.

4. Code map
- `source_rag.py`: add `INSTANCE_ENV`, `INSTANCE`, `format_search_hits(hits: list[dict]) -> str`; make `MCP_NAME` default to `source` and honor `INSTANCE`. Existing tests: `tests/test_chunking.py` build/search.
- `mcp_server.py`: replace inline search formatting with `R.format_search_hits(...)` without changing output.
- `serve_http.py` (new): `main(argv=None)`, localhost `HTTPServer`, JSON helpers, `/health`, `/list`, `/search`, `/ingest`, safe ingest validation/writes, rebuild/reload.
- `run_instance.sh` (new): parse `<name> --vault <dir> --db <file> --port <n>`, export `INSTANCE`/`SOURCE_VAULT`/`SOURCE_DB`, run `.venv/bin/python serve_http.py ...`.
- `README.md`: add multi-instance agent-smith section and endpoint examples.
- `pyproject.toml`: include `serve_http` in `py-modules`; add `source-http` script only if consistent with existing scripts.
- Tests: add `tests/test_http_service.py`; update `tests/test_chunking.py` for formatter/instance tests.

5. Edge cases
| Input/state | Expected behaviour |
|---|---|
| Missing/blank `/search` `q` | `400` JSON error. |
| `k` absent, non-integer, outside range | default 3; non-integer `400`; integer clamped to 1..20. |
| Invalid `mode` | `400`; only `hybrid`, `vector`, `keyword`. |
| No ready index | health `200` with not-ready; search/list `503`; ingest may create the first index. |
| Malformed JSON or missing `notes` list | `400`; no writes/rebuild. |
| Oversized body | `413` before writes. |
| Empty batch, too many notes, or duplicate ids | `400`; no writes. |
| Absolute id, `..`, empty segments, backslash, NUL, bad chars | `400`; no write outside vault. |
| Concurrent requests | Single-threaded serialization; no half-swapped db observed. |
| Rebuild failure after writes | `500`; previous db/index keeps serving if it existed. |

6. Security considerations
Unauthenticated local JSON is the new trust boundary. Bind only to `127.0.0.1` and document not to expose it. Validate ids and resolved paths to stop traversal. Use no shell from HTTP; quote paths in `run_instance.sh`. Keep SQL parameterized via existing Index methods. Limit body/batch size to reduce local resource abuse. Do not log note bodies/secrets. No auth is added because scope is offline localhost.

7. Test plan
- `tests/test_chunking.py::test_instance_defaults_to_source_and_honors_env_on_reload`: default and env override.
- `tests/test_chunking.py::test_format_search_hits_matches_existing_mcp_shape`: formatted hit text and `no matches`.
- `tests/test_http_service.py::test_health_and_list_return_instance_and_index_state`: fake index health/list JSON.
- `tests/test_http_service.py::test_search_endpoint_formats_filters_and_validates_params`: q/k/mode/path/tags passed through, k clamped, display returned, bad params rejected.
- `tests/test_http_service.py::test_ingest_writes_markdown_rebuilds_reloads_and_searches`: file path/content, incremental build call, reload, search visibility.
- `tests/test_http_service.py::test_ingest_is_idempotent_upsert_and_isolated_by_vault`: same id overwrites; two temp vaults do not leak results.
- `tests/test_http_service.py::test_ingest_rejects_malformed_duplicate_traversal_and_oversize_without_writes`: malformed JSON, duplicate ids, traversal ids, 413, no files.
- `tests/test_http_service.py::test_rebuild_failure_returns_500_and_keeps_old_index`: old search/list still works after simulated build error.
Existing `tests/test_chunking.py` must keep passing.
Tests required: yes

8. Review focus
- Accidental MCP rename or output drift.
- `/search` JSON shape compatibility with agent-smith.
- Ingest id/tag validation too strict or too loose.
- SQLite connection leaks or stale index after repeated ingest.
- Docs overstating safety of an unauthenticated service.

9. Assumptions
- `id` is a slash-separated relative stem such as `findings/host-1`; service appends `.md`.
- `title` and `text` are required strings; `tags` is optional simple slug strings.
- Markdown output is frontmatter `tags: [..]`, `# title`, blank line, then text; no YAML dependency.
- Request limits are fixed constants in `serve_http.py`.

10. Suspicious content
none

Size: standard
Risk level: medium
Reason: unauthenticated localhost clients can write files into a vault and trigger index rebuilds; bad validation could corrupt data or allow path traversal, though exposure is localhost-only.