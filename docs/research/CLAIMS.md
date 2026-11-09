# Claim and evidence ledger

The published manuscript and focused notes use `research-candidate-v1`, produced from executable commit `215584642c90eecfb62b51372bc05ca718e9fd2b`. Its manifest SHA-256 is `a90a89bc1d9154b421cfc1cc6a8548ed0e3c884f92b5afbe07c3190258370e91`. The [publication receipt](PUBLICATION.json) maps each figure to hashed inputs inside that campaign. Study outcomes retain country, sex, origin, target year, age grid, exposure, forecast rates, expectancy draws and interval scores.

| Claim | Archived artifact and figure | Decision |
| --- | --- | --- |
| H1 Exposure alignment changes inference | `life-tables.csv`, [Norway contrast](figures/01-exposure.svg) | Supported, with small sign-sensitive changes |
| H2 Published rate and a(x) arithmetic reproduces tables | `reference/published.csv`, `reference/comparison.jsonl`, [reconstruction error](figures/02-reconstruction.svg) | Supported for 249 eligible schedules |
| H3 Count offset improves sparse synthetic forecasts | `recovery.jsonl`, [known-truth errors](figures/05-counts.svg) | Lee-Carter had lower error under stable drift. The count trend had lower error under shock and cohort effects |
| H4 Coherence improves forecast stability | `study/rolling.*.coherent/result.json`, [short- and long-horizon scores](figures/07-coherence.svg) | Coherence led at one year. The count trend led at 20 years |
| H5 Learned models improve on best baseline | `study/rolling.*/result.json`, [forecast WIS](figures/forecast-wis.svg), [all seed strata](figures/strata.csv) | Best baseline led at all four horizons |
| H6 Shock coverage is worse | `study/rolling.*.coherent/result.json`, [pandemic coverage](figures/09-shocks.svg) | Supported for one-year coherent intervals |
| H7 Unseen regions are harder | `study/region.2013.*/result.json`, `study/country.2013.*/result.json`, [failed transfer fits](figures/10-transfer.svg) | Transfer varied by geography and model. Eight fits regressed from initialization |
| H8 Path width grows with horizon | `study/rolling.*/result.json`, [interval width](figures/interval-width.svg), [coherent coverage](figures/14-calibration.svg) | The coherent factor had wider intervals and lower coverage at 20 years than at one year |
| Cause counts reconcile | `cause/share_forecast.csv`, `cause/conditional_scenarios.csv`, [cause share error](figures/12-causes.svg), [scenario changes](figures/13-scenarios.svg) | 21 quality-screened countries and 22 scenario pairs |
| Historical revisions matter | `vintages/revisions.csv`, `vintages/as-of-2022.csv`, [error changes](figures/11-vintage.svg) | Revised inputs helped some models and hurt others |
| Cached dashboard comparison latency | `browser/browser.json`, `browser/trace.zip` | 34.7 ms p95 for 40 cached switches on the measured host |
| Verifier rejects semantic mutation | `NEGATIVE_CONTROLS.json`, `REPLAY_CONTROL.json` | Four rehashed demographic controls and one rehashed model control rejected |

All 18 campaign commands completed. Independent verification recomputed 10,000 generated tables, 249 published references, 200 synthetic panels, 58,400 coherent WHO rows, and 38,520 forecast strata. Replay compared the 135 stored model checkpoints against the original forecasts and their seeded initialization controls. Of the 129 distinct learned fits, 121 improved held-out MAE. Six additional comparisons reused checkpoints for calibration ablations.

The evidence supports this preview. Full acceptance remains open. [Build status](../BUILD_STATUS.md) · [Reproduction](../REPRODUCING.md)
