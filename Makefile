.PHONY: doctor
doctor:
	python3.13 -c 'import platform, shutil; print(platform.platform()); print(shutil.disk_usage("."))'

.PHONY: build test
build:
	cargo build --locked --release --manifest-path native/Cargo.toml

test: build
	cargo test --locked --manifest-path native/Cargo.toml
	python3.13 -m unittest discover -s tests -v
