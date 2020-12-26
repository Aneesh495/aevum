# Forecast models

Every model operates on an age-period surface. The forecast target is a positive central mortality rate. Period expectancy is derived by applying one forecast period to the life-table kernel. Held-out years are never used to normalize inputs or set an extrapolation endpoint.

| Model | Rate representation | Forecast |
| --- | --- | --- |
| Lee-Carter | Leading SVD component of age-centered log rates | Random walk with historical mean drift |
| Count trend | Age-specific log-linear Poisson mean with a log exposure offset | Continue the fitted drift, with ridge on slopes |
| Age-period-cohort | Age intercepts, period drift and residualized cohort basis | Hold the raw cohort basis fixed beyond its training support |
| Coherent factor | Same-sex reference factor and age-specific country gaps | Continue the reference drift and mean-revert the gaps |
| Structured | Age basis, sex curve, shrunk country and sex residuals, time MLP | Continue drift and hold learned nonlinear effects at the origin |
| State-space | Age basis, hierarchy, recurrent latent transition and penalized innovations | Roll forward the transition without new fitted innovations |

Lee-Carter centers the period score and scales the age loading to unit sum when the signed sum is numerically supported. Near-zero signed sums fall back to signed unit norm. Zero counts use a half-death proxy only in log-rate regressions. The count models fit zeros directly.

APC features use approximate birth cohort at the age-band midpoint. Age and period design columns absorb the fitted cohort basis projections. The linear transform (-delta age, +delta period, -delta cohort) leaves fitted rates unchanged. Continuing the basis beyond its last cohort is a separate extrapolation assumption and is scored as a sensitivity.

The learned models optimize an exposure-weighted mean count loss within population, then average over populations. WPP modeled counts give a quasi-likelihood objective. A Poisson sampling interpretation on WPP is inappropriate because the release is already smoothed and modeled. A negative-binomial alternative estimates age-specific NB2 dispersion. Country embeddings are shrunk towards zero. Unseen countries use the sex curve with a zero country embedding or a same-sex training pool for baselines.

The pandemic indicator is active only for 2020 and 2021 when those years are already in the training window. That design estimates the retrospective shock and does not assume an analogous future shock is known in advance.
