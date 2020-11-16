import math
import unittest

from aevum.ages import Age, abridged, complete
from aevum.lifetable import infant_ax, life_table


class LifeTableTests(unittest.TestCase):
    def test_piecewise_hazard_matches_integrated_survival(self):
        grid = (Age(0, 1), Age(1, 5), Age(5, None))
        rates = (0.1, 0.02, 0.14)
        expected = (
            (1 - math.exp(-0.1)) / 0.1
            + (math.exp(-0.1) - math.exp(-0.18)) / 0.02
            + math.exp(-0.18) / 0.14
        )
        self.assertAlmostEqual(life_table(grid, rates)[0].e, expected, places=12)

    def test_constant_force_independent_of_age_resolution(self):
        for grid in (complete(100), abridged()):
            with self.subTest(ages=len(grid)):
                table = life_table(grid, [0.125] * len(grid))
                for row in table:
                    self.assertAlmostEqual(row.e, 8.0, places=10)

    def test_zero_deaths_and_extinction(self):
        table = life_table(complete(2), [0, 2, 0.2], method="custom", ax=[0.5, 0.5])
        self.assertEqual(table[0].q, 0)
        self.assertEqual(table[1].q, 1)
        self.assertIsNone(table[-1].e)

    def test_infancy_formula(self):
        self.assertAlmostEqual(infant_ax(0.004, "female"), 0.14080892)
        self.assertAlmostEqual(infant_ax(0.1, "male"), 0.29915)
        table = life_table(complete(1), [0.01, 0.2], method="hmd_infant", sex="male")
        self.assertAlmostEqual(table[0].q, 0.01 / (1 + (1 - table[0].ax) * 0.01))

    def test_invalid_tail_and_grid(self):
        with self.assertRaisesRegex(ValueError, "open-age"):
            life_table(complete(1), [0.01, 0])
        with self.assertRaisesRegex(ValueError, "contiguous"):
            life_table((Age(0, 1), Age(2, None)), [0.01, 0.1])

    def test_lower_hazard_increases_survival(self):
        grid = abridged()
        high = life_table(grid, [0.055] * len(grid))
        low = life_table(grid, [0.025] * len(grid))
        self.assertTrue(all(a.l <= b.l for a, b in zip(high, low)))
