# Demographic contract

The unit of analysis is one territory definition, published sex, calendar year, age interval, source release, and cause stratum. Closed age intervals use inclusive lower and exclusive upper age boundaries. An open age interval has no upper boundary and is the final row of a complete table. Count and exposure records can join only at the same territory, calendar, sex, age, coverage, and dataset vintage. Person-years and midyear headcounts have distinct units.

Registration observations, modeled historical estimates, official projections, and simulated data have distinct provenance. A retrospective evaluation on a recent revision measures prediction of that revision's historical values. A historical-vintage evaluation requires input available by the forecast origin. Official projections are excluded from historical outcomes. Missing and suppressed cells cannot be filled with zero.

The central death rate is deaths divided by person-years. In the fixed a(x) method, a closed interval of width n has q(x) = n m(x) / (1 + (n - a(x)) m(x)). Impossible probabilities require a different supported assumption or an explicit input error. An open interval requires positive mortality for a finite tail. Cohort extraction follows age and calendar year together and records missing diagonal cells.
