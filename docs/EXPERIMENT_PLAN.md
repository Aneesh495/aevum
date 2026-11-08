# Frozen experiment protocol v1

The panel and study frame are fixed in [source receipts](../config/sources.json), the [WPP frame](../config/wpp-cohort.json), and the [run matrix](../config/experiment-v1.json). Comparisons use WPP 2024 retrospective estimates and the same historical outcome definition on every model. A forecast origin cuts the event calendar. Since the complete release was published after every origin, none of these are historical-vintage forecasts.

## Registered hypotheses

1. Aggregating deaths and exposure before division changes rates where single-age exposures are unequal.
2. Published complete tables reconstruct under the same published central rate and a(x) inputs, to source precision.
3. Exposure-offset Poisson can outperform log-rate fitting on sparse synthetic counts when the generator matches its mean model.
4. Coherent factors reduce 20-year dispersion of country gaps, at a possible short-horizon cost.
5. Learned age features and hierarchical pooling improve held-out weighted interval score at some horizons. The primary comparator is the best of four baselines within the same horizon.
6. Intervals calibrated on pre-pandemic windows have lower coverage in 2020–2021 than comparable non-shock years.
7. Unseen regions with no region-specific fit show worse accuracy than the same model under temporal-only splits. Sex pools must be built on training groups.
8. Synchronized block paths widen intervals with horizon and preserve some cross-age dependence. WPP revision and model-selection uncertainty are outside this calculation.

## Workloads and decision rules

Each of the thirteen chronological origins fits four baselines and both learned alternatives with three fixed random seeds. Each fit is one evaluation unit with eligible horizons 1, 5, 10 and 20 years. An origin contributes only when the target year is at most 2023. In particular, the first five origins each support a 20-year evaluation. Forecast inputs contain 20 contiguous exposure-weighted age intervals ending at 90+. Unseen country and region diagnostics use origin 2013, four baselines and one frozen seed per learned architecture. These diagnostics do not support claims about neural seed robustness in transfer.

Structured ablations remove the age basis, hierarchy, fitted temporal component, or shock term, use NB2, or remove block calibration. Compare within origin and seed at the same optimization budget. Shock ablation is tested in the rolling post-shock fit at origin 2022. An ablation that has no effect before the shock was observable is recorded as a chronology control.

Outcomes are point absolute error in period e0, rate log RMSE, weighted interval score, plus 50%, 80%, and 95% interval coverage and width. Countries contribute equally within a stratum. Report calibration by model, horizon, region, sex, shock timing and small-exposure stratum. Resample countries as blocks for paired country-level differences. Origins and sexes for one country stay together. This handles repeated observations within country. The point estimates can still reflect common cross-country shocks.

Residual increments are sampled in synchronized blocks of three years. An endpoint count perturbation uses the three latest training years, and denominator sensitivity uses an assumed 2% log-scale perturbation. The latter is a sensitivity parameter. WPP does not report those cell-level exposure standard errors. The uncertainty path omits source revision and model specification uncertainty. Ensembles of seeds are reported separately.

The synthetic campaign uses 200 panels split equally between stable age-dependent drift and a misspecified regime with a persistent age-specific shock and cohort effects. Forecast recovery uses known future rates; suppression and missingness are retained as reporting masks for diagnostics. The generated table campaign independently checks accounting on 10,000 piecewise-force tables. Reference reconstruction uses the frozen published mx and ax inputs at 1990, 2019, and 2021, with explicit tail and source-rounding checks.

CPU runs limit Torch to two worker threads and DuckDB to four threads with 2 GB working memory. The diagnostic profile uses reduced dimensions and is labeled separately. Report every failed fit, diagnostic, and unsupported slice. Model hypotheses are evaluated on the recorded comparisons even when the results are adverse.
