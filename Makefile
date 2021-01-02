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

train: fit-baselines

backtest:
	$(THREADS) $(PY) -m aevum.study --profile $(PROFILE) --out evidence/$(RUN_ID)
