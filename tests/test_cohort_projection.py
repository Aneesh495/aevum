import unittest

import numpy as np

from aevum.ages import Age
from aevum.closure import fit_tail
from aevum.cohort_forecast import project


class CohortProjectionTests(unittest.TestCase):
    def test_rate_paths_respect_exact_age_and_calendar(self):
        grid = (Age(0, 1), Age(1, 5), Age(5, None))
        years = (2002, 2003, 2004, 2005)
        rate = np.full((4, 3), 0.04)
        outcome = project(
            birth_year=2000, attained_age=0, historical={(0, 2000): 0.04, (1, 2001): 0.04},
            forecast_years=years, bands=grid, forecasts=np.repeat(rate[None], 5, axis=0), point=rate,
        )
        self.assertAlmostEqual(outcome.point_years, 25.0)
        self.assertEqual(outcome.age_year_status[-1], (5, 2005, "aevum_forecast_piecewise_age"))
        self.assertAlmostEqual(outcome.remaining_years[0][1], 25.0)
        outcome = project(
            birth_year=2001, attained_age=0, historical={},
            forecast_years=years, bands=grid, forecasts=np.repeat(rate[None], 5, axis=0), point=rate,
        )
        self.assertEqual(outcome.status, "truncated")
        self.assertIsNone(outcome.point_years)

    def test_tail_recovers_known_logistic_coefficients(self):
        age = np.arange(101)
        exposure = np.full(101, 100_000.0)
        odds = np.exp(-3.5 + 0.115 * (age - 80))
        rate = odds / (1 + odds)
        tail = fit_tail(rate * exposure, exposure)
        self.assertAlmostEqual(tail.intercept, -3.5, places=3)
        self.assertAlmostEqual(tail.slope, 0.115, places=3)
