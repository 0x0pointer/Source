Verdict: fail

Blocking findings: `/ingest` accepts browser-simple `text/plain` JSON writes without CSRF guard; `note_path_for_id` replaces suffixes instead of appending `.md`, causing wrong paths and same-batch overwrite collisions.

# Security review

## Summary
Blocking findings: 2. Non-blocking findings: 0. The high-risk area is the new unauthenticated localhost HTTP service, especially `/ingest`, which crosses a new browser/local-client trust boundary and writes into the selected vault before rebuilding the SQLite index.

## Changed files, risk, and blast radius
| File | Risk | Blast radius |
|---|---:|---|
| `README.md` | LOW | Documentation only; endpoint examples and safety warning. |
| `mcp_server.py` | MEDIUM | 1 MCP tool (`search_notes`) now depends on shared formatter. |
| `pyproject.toml` | LOW | Packaging metadata; exposes `source-http` console script. |
| `run_instance.sh` | MEDIUM | New shell launcher used from docs; arguments are passed to `serve_http.py` and were checked for quoting. |
| `serve_http.py` | HIGH | New HTTP server with 4 endpoints; `/ingest` writes vault files and triggers index rebuild/reload. Reachable from local clients and, for simple POSTs, from a visited web page. |
| `source_rag.py` | MEDIUM | Shared instance identity and formatter used by MCP/HTTP; `Index.close()` used by HTTP reload path. |
| `tests/test_chunking.py` | LOW | Tests only. |
| `tests/test_http_service.py` | LOW | Tests only; covers main HTTP happy paths and some validation. |

## Findings
1. **Blocking - browser-origin write to `/ingest`** (`serve_http.py:205`): `do_POST` accepts and parses JSON regardless of `Content-Type`. A malicious web page can issue a `fetch("http://127.0.0.1:7801/ingest", {mode:"no-cors", method:"POST", headers:{"Content-Type":"text/plain"}, body:'{"notes":[...]}'})`; `text/plain` is a simple request, so no CORS preflight is required, and the attacker does not need to read the response to create/overwrite notes and trigger a rebuild. Exploitability: EASY if a user has the documented default service running and visits the page. Impact: arbitrary Markdown writes inside the configured vault under attacker-chosen valid ids. Fix by rejecting non-`application/json` media types (including missing or `text/plain`) before reading the body; this forces browser JSON attempts through a preflight that the server does not allow, while preserving intended local JSON clients.
2. **Blocking - note id path is not `vault/<id>.md` for ids containing suffixes** (`serve_http.py:293`): `Path.with_suffix(".md")` replaces the final suffix instead of appending `.md`. A valid id like `v1.2` writes `v1.md`, and a single batch with ids `foo` and `foo.md` validates as non-duplicate but writes the same `foo.md`, so the second note silently overwrites the first. This violates the acceptance criterion that valid notes are written to `vault/<id>.md` and undermines the duplicate-id/no-partial-write contract. Fix by appending `.md` to the final validated id segment (or rejecting dotted/suffixed ids explicitly) and by checking duplicate resolved target paths before any write.

## Test coverage gaps
- No negative test proves `/ingest` rejects browser-simple content types such as `text/plain` or missing `Content-Type`.
- No ingest test covers ids containing dots/suffixes or duplicate ids that normalize to the same target path.
- The required id-validation edge cases are only partially covered: traversal is tested, but absolute ids, backslash, NUL, bad characters, empty path segments, and too many notes are not directly asserted.

## Not covered
I did not rerun the full suite because protected checks already passed. I reviewed the diff against `origin/main`, checked relevant history/blame for modified existing code, traced one-hop callers/callees and tests, and ran only targeted local snippets to confirm the two reported paths. I did not audit unchanged search/chunking/model code beyond the call paths touched by this change.