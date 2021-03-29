# Claim and evidence ledger

The primary results come from the clean-checkout WPP experiment at `5787c4a`, run `wpp-rolling-v1`. Raw evaluation units are saved under each task ID in `result.json`. Each contains exact country, sex, origin, target year, age grid, exposure, forecast rates, life expectancy draws, and interval scores. The staged panel's identity appears in `STUDY.json`. Figure data preserve the support and the metric, including each seed where applicable.

| Claim | Raw or derived evidence | Decision |
| --- | --- | --- |
| H1 Exposure alignment changes inference | `wpp-01-life-tables.csv`, `results-v1/age_assumptions.csv` | Supported, with small sign-sensitive changes |
| H2 Published rate and a(x) arithmetic reproduces tables | `wpp-02-reference/published.csv`, `comparison.jsonl`, [v2 protocol](../REFERENCE_PROTOCOL_V2.md) | Supported for 249 eligible schedules |
| H3 Count offset improves sparse synthetic forecasts | `synthetic-v1-recovery.jsonl`, [known truth scores](figures/synthetic.csv) | Not supported in the stable regime at this budget |
| H4 Coherence improves forecast stability | [Stratified scores](figures/strata.csv), coherent fit records | Short-horizon WIS improved. Long-run gap bounded by construction |
| H5 Learned models improve on best baseline | [Forecast WIS](figures/forecast-wis.svg), [strata](figures/strata.csv) | Not supported on the frozen matrix |
| H6 Shock coverage is worse | [Shock strata](figures/strata.csv), rolling origins 2019 and 2020 | Supported for coherent and Lee-Carter at one year |
| H7 Unseen regions are harder | [Transfer strata](figures/strata.csv), `region.2013.*` raw runs | Generally supported, with pooling variation |
| H8 Path width grows with horizon | [Interval figure](figures/interval-width.svg), [strata](figures/strata.csv) | Width grows, with persistent undercoverage |
| Cause counts reconcile | `who-study-v1/share_forecast.csv`, `conditional_scenarios.csv` | 21 quality-screened countries and 22 scenario pairs |
| Historical revisions matter | `revision-v1-vintages/revisions.csv`, `as-of-2022.csv` | Mixed effect on forecast error |
| Cached dashboard comparison latency | `browser-v1/browser.json`, trace and PNGs | 34.5 ms p95 for 40 cached switches on the measured host |
| Verifier rejects semantic mutation | `demography-v1-negative-controls.json`, `replay-control-v1.json` | Four rehashed demographic controls and one rehashed model control rejected |

## Integrated reproduction

The full candidate was rerun from executable commit `215584642c90eecfb62b51372bc05ca718e9fd2b` cloned from GitHub. Candidate identity is `research-candidate-v1`. Manifest SHA-256 is `a90a89bc1d9154b421cfc1cc6a8548ed0e3c884f92b5afbe07c3190258370e91`. All 18 commands executed successfully. Independent verification recomputed 10,000 generated tables, 249 eligible published references, 200 synthetic panels, 58,400 coherent WHO rows, 38,520 forecast strata, and 135 checkpoint replays. Cached comparison p95 on the candidate was 34.7 ms across 40 samples.

The 129 distinct learned fits include 121 that improve held-out MAE over initialization. The eight degraded transfer fits remain in the raw campaign. The strict full-profile verdict is incomplete. The source and artifact execution checks can be rerun independently.
