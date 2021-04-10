# Build status

Aevum is a runnable research preview. The published repository supports a clean synthetic demo, real demographic acquisition, life-table and cohort analysis, statistical and learned forecasts, a local interactive atlas, and independent verification. Full project acceptance remains open.

## Research gates

| Gate | Current evidence | Status |
| --- | --- | --- |
| G01 Data | 42 UN countries, 1970–2023, two sexes, 101 published ages. 21 WHO countries pass the 15-year cause screen. Adult quality benchmarks are country-specific and cross-sectional. | Passed under declared source screen |
| G02 Identities | 10,000 independently verified force tables and analytic constant and piecewise cases. | Passed |
| G03 Reconstruction | 249 eligible published schedules. Three exclusions for incompatible capped rates, with the duplicated Lx field recorded separately. | Passed |
| G04 Likelihood | Poisson offsets, NB2 variance, reported zero and suppressed/missing distinctions exercised by analytic unit tests. | Passed |
| G05 Identifiability | APC tilt invariance and sensitivity of the forecast extrapolation convention measured. | Passed |
| G06 Original training | Replay checks the saved and seed-initialized models. Of 129 distinct learned fits, 121 improve held-out MAE, including all 78 rolling fits. Eight geographic transfer fits regress. | Failed the all-fits held-out improvement criterion |
| G07 Forecast matrix | 229 distinct fits, 235 comparisons, 38,520 held-out strata, and 135 model replays. | Passed |
| G08 Calibration | 50%, 80%, 95% interval coverage, width, and proper scores. Empirical coverage is below nominal in many strata. | Passed reporting gate |
| G09 Cause coherence | Registered counts reconcile with explicit residuals. Cause profiles are forecast conditional on registered totals in the WHO study. | Passed for declared composition |
| G10 Finite change | Age and cause contributions reconcile across 22 eligible 2019 scenario pairs. | Passed |
| G11 Synthetic recovery | 200 independent seeded panels split across stable and misspecified regimes. | Passed |
| G12 Atlas | Real WPP and WHO panels, frozen checkpoint forecasts, and browser benchmark. | Passed on the measured host |
| G13 Research | Thesis, 14 focused notes, plot data, and hypothesis ledger match the archived campaign by manifest and source checksums. | Passed for the archived campaign |
| G14 Semantic verification | Rehashed projection status, denominator units, impossible survival, cause sum, and model replay mutations rejected. | Passed |
| G15 Full release | The preview has source-bound candidate evidence. Full release still requires the capability and completion audits. | Unverified |

The verifier reports each open gate and returns nonzero for full acceptance while any mandatory gate remains open. The candidate verifier can succeed for a valid bundle that contains adverse research results. See the [evidence ledger](research/CLAIMS.md) and [reproduction commands](REPRODUCING.md).
