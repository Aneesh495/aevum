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
