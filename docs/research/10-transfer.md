# Out-of-support geography

Every leave-region and leave-country split removes all sex and age cells of the selected geography before fitting or calibration. Baselines fall back to pooled same-sex schedules and the neural models use zero for unseen country embeddings. No region-specific support or normalization is learned on the excluded group. Origin 2013 has historical follow-up for 1, 5 and 10 years.

Europe provides a mixed example. The state-space model's ten-year WIS is 5.21, compared with 6.80 for the coherent baseline in the Europe holdout, yet its mean absolute point e0 error there is worse than the untrained architecture. In the rolling one-year stratum with local training, coherent WIS is best in Europe and every other study region. Diagnostics use a single learned seed per holdout and do not identify the effect of seed uncertainty on the transfer ranking. [Transfer strata](figures/strata.csv)
