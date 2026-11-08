.PHONY: doctor
doctor:
	python3.13 -c 'import platform, shutil; print(platform.platform()); print(shutil.disk_usage("."))'

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
	$(PY) -m aevum.verify demo $(EVIDENCE) --expected-commit $(EXPECTED_COMMIT)

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
