# Common tasks. `make install` then `make build`, then `make query Q="your question"`.
VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.PHONY: help venv install install-dev build rebuild watch query list test eval clean

help:
	@echo "make install       create .venv and install runtime deps"
	@echo "make install-dev   also install test deps (pytest)"
	@echo "make build         build/refresh the index (incremental)"
	@echo "make rebuild       full rebuild (ignore the cache)"
	@echo "make watch         rebuild automatically on file change"
	@echo 'make query Q="…"   search the index'
	@echo "make test          run the unit tests (no model download needed)"
	@echo "make eval          run the retrieval benchmark"
	@echo "make clean         remove index/, models/ and caches"

venv:
	python3 -m venv $(VENV)

install: venv
	$(PIP) install -q -r requirements.txt

install-dev: venv
	$(PIP) install -q -r requirements-dev.txt

build:
	$(PY) build_index.py

rebuild:
	$(PY) build_index.py --full

watch:
	$(PY) build_index.py --watch

query:
	$(PY) query.py $(Q)

list:
	$(PY) query.py --list

test:
	$(PY) -m pytest

eval:
	$(PY) eval_retrieval.py -v

clean:
	rm -rf index models __pycache__ */__pycache__ .pytest_cache *.egg-info
