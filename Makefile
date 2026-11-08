.PHONY: doctor
doctor:
	$(PY) -m aevum.doctor

.PHONY: build test
build:
	cargo build --locked --release --manifest-path native/Cargo.toml

test: build
	cargo test --locked --manifest-path native/Cargo.toml
	$(PY) -m unittest discover -s tests -v

PY := .venv/bin/python
SOURCE ?= wpp

.PHONY: bootstrap acquire data
bootstrap:
	uv sync --locked

acquire:
	python3.13 -m aevum.acquire $(SOURCE)

data:
	$(PY) -m aevum.wpp

RUN_ID ?= diagnostic
PROFILE ?= diagnostic
THREADS := OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OMP_NUM_THREADS=2

.PHONY: who-data fit-baselines train backtest
who-data:
	$(PY) -m aevum.who

fit-baselines:
	$(THREADS) $(PY) -m aevum.study --profile diagnostic --out evidence/$(RUN_ID)

train:
	$(THREADS) $(PY) -m aevum.forecast fit --checkpoint evidence/$(RUN_ID)-checkpoint.pt

backtest:
	$(THREADS) $(PY) -m aevum.study --profile $(PROFILE) --out evidence/$(RUN_ID)

.PHONY: life-tables stress reference
life-tables: build
	$(PY) -m aevum.table_study tables --out evidence/$(RUN_ID)-life-tables.csv

stress: build
	$(PY) -m aevum.table_study stress --out evidence/$(RUN_ID)-stress.jsonl

reference: build
	$(PY) -m aevum.table_study reference --out evidence/$(RUN_ID)-reference

EVIDENCE ?= evidence/$(RUN_ID)-demo
EXPECTED_COMMIT ?= $(shell git rev-parse HEAD)

.PHONY: demo verify
demo: build
	$(PY) -m aevum.demo evidence/$(RUN_ID)-demo --controls evidence/$(RUN_ID)-negative-controls.json

verify:
	@if test -f "$(EVIDENCE)/ACCEPTANCE.json"; then \
	    $(PY) -m aevum.acceptance verify --out "$(EVIDENCE)" --expected-commit "$(EXPECTED_COMMIT)"; \
	else \
	    $(PY) -m aevum.verify demo "$(EVIDENCE)" --expected-commit "$(EXPECTED_COMMIT)"; \
	fi

CHECKPOINT ?=
PORT ?= 8078

.PHONY: web serve
web:
	cd web && npm run build

serve: build web
	$(THREADS) $(PY) -m aevum.dashboard --port $(PORT) $(if $(CHECKPOINT),--checkpoint $(CHECKPOINT))

.PHONY: forecast synthetic-recovery
forecast: build
	$(THREADS) $(PY) -m aevum.forecast predict --checkpoint $(if $(CHECKPOINT),$(CHECKPOINT),evidence/$(RUN_ID)-checkpoint.pt) --out evidence/$(RUN_ID)-forecast.json

synthetic-recovery:
	$(THREADS) $(PY) -m aevum.recovery --out evidence/$(RUN_ID)-recovery.jsonl

RAW ?= data/raw

.PHONY: acceptance verify-candidate decompose
decompose: build
	$(PY) -m aevum.cause_study --raw $(RAW) --out evidence/$(RUN_ID)-cause-study

acceptance: build
	$(THREADS) $(PY) -m aevum.acceptance run --profile $(PROFILE) --raw $(RAW) --out evidence/$(RUN_ID)

verify-candidate:
	$(THREADS) $(PY) -m aevum.acceptance verify --out $(EVIDENCE) --expected-commit $(EXPECTED_COMMIT) --candidate

.PHONY: vintages
vintages:
	$(THREADS) $(PY) -m aevum.vintages --raw $(RAW) --out evidence/$(RUN_ID)-vintages

.PHONY: bench docs release
bench: web build
	PORT=$(PORT) scripts/browser-bench.sh "$(if $(CHECKPOINT),$(CHECKPOINT),evidence/$(RUN_ID)-checkpoint.pt)" "evidence/$(RUN_ID)-browser"

docs:
	python3.13 scripts/check_docs.py

release: docs test web
	uv lock --check && uv build --wheel
	git diff --check
