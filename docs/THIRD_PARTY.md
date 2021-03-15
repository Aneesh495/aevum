# Third-party provenance

| Dependency | Role | License information |
| --- | --- | --- |
| Python | Runtime | [PSF license](https://docs.python.org/3/license.html) |
| Rust | Life-table compiler and standard library | [Rust licensing](https://www.rust-lang.org/policies/licenses) |
| NumPy | Array math | [BSD-3-Clause](https://numpy.org/doc/stable/license.html) |
| SciPy | Optimizers and linear algebra | [BSD-3-Clause](https://scipy.org/about/) |
| PyTorch | Automatic differentiation and CPU execution | [Upstream license](https://github.com/pytorch/pytorch/blob/main/LICENSE) |
| Apache Arrow | Columnar exchange | [Apache-2.0](https://github.com/apache/arrow/blob/main/LICENSE.txt) |
| DuckDB | Local SQL and Parquet | [MIT](https://github.com/duckdb/duckdb/blob/main/LICENSE) |
| TypeScript | Dashboard compilation | [Apache-2.0](https://github.com/microsoft/TypeScript/blob/main/LICENSE.txt) |
| Playwright | Browser integration verification | [Apache-2.0](https://github.com/microsoft/playwright/blob/main/LICENSE) |
| Poppler | Extract text from official quality documents | [Upstream repository and license](https://gitlab.freedesktop.org/poppler/poppler) |

Exact versions and wheel hashes are in [uv.lock](../uv.lock) and [the dashboard lock](../web/package-lock.json). The Rust library has no third-party crate dependencies. The release distributes source and derived documentation. Refer to the [data card](DATA.md) for separate UN and WHO data terms.

Method references include [Lee and Carter 1992](https://doi.org/10.1080/01621459.1992.10475265), [HMD Methods Protocol v6](https://www.mortality.org/File/GetDocument/Public/Docs/MethodsProtocolV6.pdf), and the [UN WPP methodology](https://population.un.org/wpp/assets/Files/WPP2024_Methodology.pdf).
