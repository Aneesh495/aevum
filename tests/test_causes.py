import unittest

import numpy as np

from aevum.ages import abridged
from aevum.causes import GROUPS, composition, forecast_shares, reconcile_forecast, scenario
from aevum.decomposition import finite_change


class CauseTests(unittest.TestCase):
    def test_unknown_and_residual_are_retained(self):
        causes = composition(30, {"circulatory": 20, "unknown": 3})
        self.assertEqual(causes["unknown"], 3)
        self.assertEqual(causes["residual"], 7)
        with self.assertRaises(ValueError):
            composition(30, {"neoplasms": 31})

    def test_composition_and_scenario(self):
        ages = abridged()
        rates = np.full(len(ages), 0.04)
        counts = np.tile(np.arange(len(GROUPS)), (len(ages), 1))
        shares = forecast_shares(counts, counts + 1)
        hazards = reconcile_forecast(rates, shares)
        np.testing.assert_allclose(hazards.sum(axis=-1), rates)
        original = scenario(ages, hazards, {})
        lower = scenario(ages, hazards, {"circulatory": 0})
        self.assertGreater(lower[0].e, original[0].e)
        with self.assertRaises(ValueError):
            scenario(ages, hazards, {"unknown": 0})

    def test_finite_change_and_equal_total_cause_exchange(self):
        ages = abridged()
        old = np.full((len(ages), 2), 0.02)
        new = old * 1.15
        result = finite_change(ages, old, new)
        self.assertAlmostEqual(result.after - result.before, result.contributions.sum(), places=10)
        swap = old * [0.5, 1.5]
        result = finite_change(ages, old, swap)
        self.assertAlmostEqual(result.contributions.sum(), 0, places=10)
        self.assertGreater(result.contributions[0, 0], 0)
        self.assertLess(result.contributions[0, 1], 0)
