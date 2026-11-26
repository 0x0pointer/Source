Verdict: pass

Blocking findings: none

# Security review

## Summary
No security findings were identified in the re-review; blocking findings by severity: blocking 0, non-blocking 0. The two previous blocking findings were rechecked against `/tmp/fabro/since-review.diff`: `/ingest` now requires `application/json` before reading the body, and dotted IDs now append `.md` while duplicate resolved targets are rejected before writes.

## Changed files triage
| File | Risk | Blast radius |
|---|---:|---|
| `serve_http.py` | HIGH | New localhost HTTP surface. `make_server` is called by `main`/tests; `/ingest` reaches `validate_notes`, `note_path_for_id`, `render_markdown`, `source_rag.build`, and `Index` reload. Concrete attacker considered: a local unauthenticated process or malicious web page attempting browser-simple POSTs to `127.0.0.1` to write vault files; the Content-Type guard makes the browser-simple JSON path unreachable, while same-host non-browser clients remain in-scope by design. |
| `source_rag.py` | MEDIUM | `MCP_NAME` used by `mcp_server`; formatter called by MCP and HTTP; `Index.close` called by HTTP state reload/close. |
| `mcp_server.py` | MEDIUM | One MCP tool output path (`search_notes`) now delegates to shared formatter; 2 production formatter callers total. |
| `run_instance.sh` | MEDIUM | New launcher/entry point, no repository callers outside documentation; reviewed quoting and localhost-only delegation. |
| `pyproject.toml` | LOW | Packaging entry points only. |
| `README.md` | LOW | Documentation only. |
| `tests/test_chunking.py` | LOW | Tests only. |
| `tests/test_http_service.py` | LOW | Tests only. |

## Findings
None.

## Test coverage gaps
No blocking gaps found. Targeted tests for the prior findings were run: `tests/test_http_service.py::test_ingest_requires_application_json_and_avoids_writes_or_rebuild` and `tests/test_http_service.py::test_ingest_accepts_dotted_ids_and_rejects_duplicate_targets` both passed. I did not rerun the whole suite because the review instructions said automated checks already passed.

## What I did not cover
This was a re-review, so I focused on `/tmp/fabro/since-review.diff` and verified the two earlier findings plus the newly changed validation paths. I did not perform a fresh audit of unchanged HTTP request parsing, SQLite internals, model loading, or benchmark code.