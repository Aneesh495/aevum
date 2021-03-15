# Reproduction and recovery

## Local setup

Use CPython 3.13, Rust 1.88 or later, uv, Node 24, npm, Poppler and Chromium for the full profile. Linux installs the CPU build of PyTorch. Apple Silicon uses the locked macOS wheel. Training selects CPU float32. Life-table, scoring and sampling arithmetic use float64. Run `make doctor` after bootstrap to inspect the active host.

```sh
make bootstrap
npm --prefix web ci
npx --prefix web playwright install chromium
make test web docs
make demo RUN_ID=first-demo
make verify EVIDENCE=evidence/first-demo-demo
```

The quick demo exercises seeded counts, exposure, a coherent cause partition, native survival accounting, and the independent negative controls without downloading archives. The pinned `data/raw` files are needed for the research atlas and campaign.

```sh
make acquire
make acquire SOURCE=who
make acquire SOURCE=quality
make acquire SOURCE=wpp2022
make data who-data
make train RUN_ID=serving
make forecast RUN_ID=serving
make serve CHECKPOINT=evidence/serving-checkpoint.pt
```

Open http://127.0.0.1:8078. WPP is required for the period atlas. The WHO source enables the cause lab. The browser's saved view persists in the same origin. The WPP 2022 archive is approximately 3.3 GiB and needed only for the vintage comparison and full research profile.

## Run and verify research evidence

Use a clean checkout of the executable source and a new run ID. Pass `RAW` if the frozen archives already live outside that checkout.

```sh
make acceptance RUN_ID=local-campaign PROFILE=full
make verify-candidate EVIDENCE=evidence/local-campaign
make verify EVIDENCE=evidence/local-campaign
```

The campaign reports nonzero on open full acceptance gates. `verify-candidate` independently checks the available workload, while full verification also requires the research acceptance audit. A run manifest covers the staged panels and all emitted evidence, including nested checkpoint files, command exits, separate benchmark samples, and retained failures. Verify against a trusted source commit. Use `EXPECTED_COMMIT=<git-sha>` when viewing reports from a subsequent documentation checkout.

## Restart and failure policy

- An acquisition mismatch keeps the destination unchanged. Move aside the mismatching file and retry from the pinned source. Record a new source identity if the publisher revised the bytes.
- Each model task publishes its result atomically. Resume interrupted model work with `python -m aevum.study --profile full --panel <panel> --out <study-directory> --resume` after checking that the source, input and protocol IDs match.
- Campaigns take a new evidence directory. Preserve prior outputs and logs. A protocol change needs its own run identity.
- A checkpoint is replayed with `weights_only` loading and an exact dataset identity. A changed data panel requires fitting or explicitly restoring a matching checkpoint.
- The default work bound is a local CPU campaign with four DuckDB workers and two Torch threads. Check disk availability before acquiring archives. Hosted CI uses the diagnostic and packaging checks.

## Artifact format

`SOURCE_INPUTS.json` identifies Git blobs and executable commit. `DATASETS.json` carries release URLs, vintage and SHA-256. `COMMANDS.jsonl` records actual process exits, elapsed time and child resource high-water marks. `MANIFEST.json` binds membership and bytes. `ACCEPTANCE.json` distinguishes passed, failed and open gates. The verifier recomputes life tables, cause partitions, interval scores, recovery summaries, and frozen checkpoint probes independently of the result writer.

Raw input archives and restricted WHO records remain local. The source receipts and commands allow independent acquisition and verification. Figures are derived from run-linked scores retained with the research notes.
