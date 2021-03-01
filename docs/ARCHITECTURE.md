# Architecture

The source register pins the downloaded bytes and an explicit authority, edition, and historical boundary. DuckDB streams raw CSVs into a keyed compatibility join, then stages sorted Parquet. Arrow moves complete grouped cells into the in-memory population × year × age cube. NumPy represents the model inputs, SciPy solves bounded baseline fits, and PyTorch owns model parameters and optimizer state. The Rust library calculates complete and abridged life tables in double precision.

The service starts with one immutable staged panel and optionally one frozen checkpoint. It binds to loopback and admits eight concurrent HTTP requests with bounded pending work. An HTTP request can filter or render a selected population and apply a bounded scenario. Checkpoint prediction and uncertainty paths are prepared at startup. The TypeScript dashboard uses cancellation tokens and an explicit no-data state. The application keeps the saved view in browser storage.

Study work is independent of serving. Each forecast fit publishes its own atomic checkpoint and result. A failed experiment retains its error and actual command exit. The verifier derives the workload from the frozen protocol, reads the trusted checkout and panel, recomputes numerical outcomes, and replays selected rates from saved parameters.

## Diagrams

- [System context](diagrams/context.svg) ([source](diagrams/context.dot))
- [Runtime components](diagrams/components.svg) ([source](diagrams/components.dot))
- [Numerical ownership](diagrams/ownership.svg) ([source](diagrams/ownership.dot))
- [Exposure compatibility](diagrams/compatibility.svg) ([source](diagrams/compatibility.dot))
- [HTTP concurrency](diagrams/concurrency.svg) ([source](diagrams/concurrency.dot))
- [Run lifecycle](diagrams/lifecycle.svg) ([source](diagrams/lifecycle.dot))
- [Persistence](diagrams/persistence.svg) ([source](diagrams/persistence.dot))
- [Life-table accounting](diagrams/life-table.svg) ([source](diagrams/life-table.dot))
- [Evidence lineage](diagrams/lineage.svg) ([source](diagrams/lineage.dot))
- [Failure and recovery](diagrams/recovery.svg) ([source](diagrams/recovery.dot))
- [Local deployment](diagrams/deployment.svg) ([source](diagrams/deployment.dot))
- [Testing boundaries](diagrams/testing.svg) ([source](diagrams/testing.dot))
- [Lexis indexing](diagrams/lexis.svg) ([source](diagrams/lexis.dot))
- [Vintage availability](diagrams/vintages.svg) ([source](diagrams/vintages.dot))
- [Count model](diagrams/count-model.svg) ([source](diagrams/count-model.dot))
- [Uncertainty paths](diagrams/uncertainty.svg) ([source](diagrams/uncertainty.dot))

## Walkthroughs

1. [Acquisition](../aevum/acquire.py) checks digest and limits before publishing a local source file. [WPP staging](../aevum/wpp.py) joins by location, time and age format, flags rounded zeros, then writes a typed file. [Cube loading](../aevum/cube.py) rechecks provenance before aggregating age bands.
2. [Life-table binding](../aevum/lifetable.py) checks contiguous ages and constructs caller-owned buffers. [Rust](../native/src/lib.rs) applies one age assumption per row, computes remaining years by reverse accumulation, and returns an error before output is exposed on invalid input.
3. [Rolling splits](../aevum/study.py) separate geography and event-time support, [optimization](../aevum/learned.py) saves parameters and training state, and [verification](../aevum/verify.py) recomputes the eligible endpoint grid and checks model probes against archived rates.
4. [WHO composition](../aevum/who.py) keeps count residuals and unknown age. [Scenario serving](../aevum/dashboard.py) requires positive matched denominators and opt-in to the approximation. [Decomposition](../aevum/decomposition.py) traces the same conditional change through the age profile.
5. [Recovery](../aevum/study.py) resumes finished work only when the original source, input identity and protocol still match. [Replay control](../aevum/replay_control.py) mutates a real saved model, rebuilds the ordinary manifest, and verifies the original forecast records against the changed inference path.
