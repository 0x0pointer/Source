Changed:
- Added `INSTANCE` support and shared search-hit formatting in `source_rag.py`; `mcp_server.py` now uses the shared formatter without changing MCP output.
- Added stdlib-only `serve_http.py` with localhost-only `/health`, `/list`, `/search`, and `/ingest`, including safe note-id validation, incremental rebuild/reload, readiness handling, and old-index preservation on rebuild failure.
- Added `run_instance.sh`, plus packaging/docs updates in `pyproject.toml` and `README.md`.

Acceptance criteria / coverage:
1. `INSTANCE` default + override: `tests/test_chunking.py::test_instance_defaults_to_source_and_honors_env_on_reload`
2. Localhost service using selected vault/db; isolated instances: `tests/test_http_service.py::test_health_and_list_return_instance_and_index_state`, `tests/test_http_service.py::test_ingest_is_idempotent_upsert_and_isolated_by_vault`
3. `/search` JSON shape, formatting, validation, no-match behavior: `tests/test_chunking.py::test_format_search_hits_matches_existing_mcp_shape`, `tests/test_http_service.py::test_search_endpoint_formats_filters_and_validates_params`
4. `/health` and `/list` metadata/readiness: `tests/test_http_service.py::test_health_and_list_return_instance_and_index_state`
5. `/ingest` writes Markdown, rebuilds, reloads, becomes searchable: `tests/test_http_service.py::test_ingest_writes_markdown_rebuilds_reloads_and_searches`
6. Idempotent upsert + instance isolation: `tests/test_http_service.py::test_ingest_is_idempotent_upsert_and_isolated_by_vault`
7. Existing incremental/search behavior preserved: existing `tests/test_chunking.py` suite still passes; full `python3 -m pytest -q` passed
8. README multi-instance and endpoint docs: documented in `README.md`

Tests run and passed in this session:
- `python3 -m pytest tests/test_chunking.py -q -k 'instance_defaults_to_source or format_search_hits_matches_existing_mcp_shape or build_and_search or path_and_tag_filters'`
- `python3 -m pytest tests/test_http_service.py -q -k 'rejects_malformed or rebuild_failure or search_endpoint'`
- `python3 -m pytest tests/test_http_service.py -q`
- `python3 -m pytest tests/test_chunking.py tests/test_http_service.py -q`
- `python3 -m pytest -q`

Noticed, not touched:
- none

STATUS: DONE