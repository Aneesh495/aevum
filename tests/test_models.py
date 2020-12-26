from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import torch

from aevum.baselines import FAMILIES, lee_carter, predict
from aevum.learned import TrainingSpec, fit, load, nb_loss, poisson_loss, predict as forecast
from aevum.lifetable import life_table
from aevum.simulate import generate
from aevum.uncertainty import Calibration, expectancy, interval_score


class ModelTests(unittest.TestCase):
    def test_offset_and_overdispersion(self):
        rate = torch.tensor([0.01, 0.01]).log()
        e = torch.tensor([100.0, 200.0])
        d = torch.zeros(2)
        torch.testing.assert_close(poisson_loss(rate, d, e), torch.tensor([1.0, 2.0]))
        loss = nb_loss(rate, d, e, torch.tensor(0.5))
        torch.testing.assert_close(loss, 2 * torch.log1p(torch.tensor([0.5, 1.0])))

    def test_lc_constraints_and_rank_one(self):
        alpha = np.array([-5.0, -8.0, -2.0])
        beta = np.array([0.5, 0.2, 0.3])
        time = np.arange(-4, 5)
        rates = alpha + np.outer(time, beta)
        a, b, k, explained = lee_carter(rates)
        np.testing.assert_allclose(a + np.outer(k, b), rates)
        self.assertAlmostEqual(b.sum(), 1.0)
        self.assertAlmostEqual(k.mean(), 0.0)
        self.assertAlmostEqual(explained, 1.0)

    def test_baselines_and_transfer_support(self):
        cube = generate(144, countries=3, years=22).panel
        train = cube.training(1997, cube.groups[:4])
        for family in FAMILIES:
            with self.subTest(family=family):
                result = predict(family, train, cube.groups, 3)
                self.assertEqual(result.log_rates.shape, (6, 3, len(cube.ages)))
                self.assertTrue(np.isfinite(result.log_rates).all())
                self.assertEqual(result.support[-1], "unseen_country_same_sex_pool")
                if family == "apc":
                    self.assertLess(result.diagnostics[0]["linear_null_max"], 1e-12)

    def test_frozen_models_replay_and_do_not_fit_targets(self):
        cube = generate(31, countries=2, years=18).panel
        train = cube.training(1995)
        with TemporaryDirectory() as folder:
            for family in ("structured", "state_space"):
                checkpoint = Path(folder) / (family + ".pt")
                result = fit(train, TrainingSpec(family, 102, steps=8), checkpoint, "a" * 64)
                self.assertLess(result["final_objective"], result["initial_objective"])
                model = load(checkpoint, "a" * 64)
                self.assertEqual(forecast(model, train.groups, (1996, 1997)).shape, (4, 2, len(cube.ages)))
                with self.assertRaisesRegex(ValueError, "identity"):
                    load(checkpoint, "b" * 64)

    def test_path_reproducibility_and_native_agreement(self):
        cube = generate(76, countries=2, years=16).panel
        train = cube.training(1993)
        fit_result = predict("lee_carter", train, cube.groups, 2)
        calibration = Calibration.from_fit(fit_result.fitted_log_rates, train.deaths, train.exposure)
        rates = calibration.paths(fit_result.log_rates, draws=12, seed=42)
        np.testing.assert_array_equal(rates, calibration.paths(fit_result.log_rates, draws=12, seed=42))
        e = expectancy(cube.ages, rates)
        self.assertAlmostEqual(e[0, 0, 0], life_table(cube.ages, rates[0, 0, 0])[0].e)
        score = interval_score(np.array([1.0, 1.0]), np.array([3.0, 3.0]), np.array([2.0, 4.0]), 0.5)
        np.testing.assert_allclose(score, [2.0, 6.0])
