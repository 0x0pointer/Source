Implemented the two reviewer-requested fixes in `serve_http.py` and added regression tests.

What I changed
- Added a `/ingest` media-type guard:
  - `POST /ingest` now requires `Content-Type: application/json`
  - Parameters like `; charset=utf-8` are accepted
  - Missing or non-JSON media types return `415` before any body parsing, file writes, or rebuilds
- Fixed ingest note path resolution:
  - `note_path_for_id()` now appends `.md` to the validated id segment instead of replacing an existing suffix
  - Example: `releases/v1.2` now writes to `vault/releases/v1.2.md`
- Added duplicate target detection during validation:
  - `validate_notes()` now tracks resolved destination paths and rejects duplicate targets before any writes

Test coverage for the todo items
- Todo 1: browser-simple-request / CSRF-style media-type issue
  - Covered by `tests/test_http_service.py::test_ingest_requires_application_json_and_avoids_writes_or_rebuild`
- Todo 2: dotted ids and duplicate resolved targets
  - Covered by `tests/test_http_service.py::test_ingest_accepts_dotted_ids_and_rejects_duplicate_targets`

What I ran
- `python3 -m pytest -q tests/test_http_service.py -k 'requires_application_json or dotted_ids'`
- `python3 -m pytest -q tests/test_http_service.py`
- `python3 -m pytest -q`

Observed results
- Focused regression tests: passed
- Full HTTP service test file: passed
- Full test suite: passed

Noticed, not touched
- None

STATUS: DONE