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
make fit-baselines RUN_ID=baselines
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

The campaign reports nonzero on open full acceptance gates. `verify-candidate` checks the evidence and reports each gate. Full verification succeeds only when all 15 gates pass. The verifier replays each saved learned model and its seeded initialization across the held-out cells before scoring G06. A run manifest covers staged panels, nested checkpoint files, command exits, benchmark samples, and retained failures. Use `EXPECTED_COMMIT=<git-sha>` when verifying from a later checkout.

The G15 release review comes from outside the candidate. Pass its path as `RELEASE_REVIEW` and its independently trusted SHA-256 as `RELEASE_REVIEW_SHA256`. The JSON must identify `source_commit`, `manifest_sha256`, `reviewer`, and `report`. Its `checks` object must record `capability_audit`, `private_requirements`, `clean_checkout_demo`, and `hosted_publication` as `passed` or `failed`. Candidate metadata alone cannot supply an external review.

## Export the reviewed manuscript

From the repository root, set `EVIDENCE` to the extracted `research-candidate-v1` directory.

```sh
make thesis RUN_ID=published-thesis EVIDENCE=research-candidate-v1
```

The export includes the manuscript, focused notes, plot data, and [publication receipt](research/PUBLICATION.json). It requires the exact archived manifest. For a different campaign, use the result summarizer to inspect its results before revising the manuscript. The figure builder regenerates the focused figures and their source receipts from campaign artifacts, including the cohort forecast replay.

```sh
.venv/bin/python -m scripts.research_figures research-candidate-v1 evidence/regenerated-figures
```

## Restart and failure policy

- An acquisition mismatch keeps the destination unchanged. Move aside the mismatching file and retry from the pinned source. Record a new source identity if the publisher revised the bytes.
- Each model task publishes its result atomically. Resume interrupted model work with `python -m aevum.study --profile full --panel <panel> --out <study-directory> --resume` after checking that the source, input and protocol IDs match.
- Campaigns take a new evidence directory. Preserve prior outputs and logs. A protocol change needs its own run identity.
- A checkpoint is replayed with `weights_only` loading and an exact dataset identity. A changed data panel requires fitting or explicitly restoring a matching checkpoint.
- The default work bound is a local CPU campaign with four DuckDB workers and two Torch threads. Check disk availability before acquiring archives. Hosted CI uses the diagnostic and packaging checks.

## Artifact format

`SOURCE_INPUTS.json` identifies Git blobs and executable commit. `DATASETS.json` carries release URLs, vintage and SHA-256. `COMMANDS.jsonl` records actual process exits, elapsed time and child resource high-water marks. `MANIFEST.json` binds membership and bytes. `ACCEPTANCE.json` distinguishes passed, failed and open gates. The verifier recomputes life tables, cause partitions, interval scores, recovery summaries, and frozen checkpoint probes independently of the result writer.

Raw input archives and restricted WHO records remain local. The source receipts and commands allow independent acquisition and verification. Figures are derived from run-linked scores retained with the research notes. The preview runs from a source checkout, where the Rust kernel and dashboard assets are built alongside the Python package.
