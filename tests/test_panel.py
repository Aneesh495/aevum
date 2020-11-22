from dataclasses import replace
import unittest

from aevum.ages import Age
from aevum.cohort import diagonal
from aevum.panel import (
    Availability, Cell, Deaths, Exposure, Observation, Quality, Release, Sex,
    Status, Unit, eligible_outcome, join_counts,
)


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.release = Release("example", "v1", 2024, 2023, "a" * 64)
        self.cell = Cell("EXA", "v1", "example", 2000, Sex.FEMALE, Age(0, 1), "national")
        self.count = Deaths(
            self.cell, self.release, Status.OBSERVED, Quality.COMPLETE, Availability.REPORTED, 0,
        )
        self.exposure = Exposure(self.cell, self.release, Unit.PERSON_YEARS, 80.0)

    def test_zero_is_distinct_from_missing_and_suppression(self):
        self.assertEqual(Observation(self.count, self.exposure).rate(), 0)
        for availability in (Availability.MISSING, Availability.SUPPRESSED):
            row = Observation(replace(self.count, availability=availability, count=None), self.exposure)
            self.assertEqual(row.exclusion(), availability.value)

    def test_key_join_rejects_incompatible_territory_and_units(self):
        wrong = replace(self.exposure, cell=replace(self.cell, geography="v2"))
        self.assertIsNone(next(iter(join_counts([self.count], [wrong]))).exposure)
        with self.assertRaisesRegex(ValueError, "differ"):
            Observation(self.count, wrong)
        approx = Observation(self.count, replace(self.exposure, unit=Unit.MIDYEAR_POPULATION))
        self.assertEqual(approx.exclusion(), "midyear_approximation_disallowed")
        self.assertEqual(approx.rate(permit_approximate=True), 0)

    def test_projection_cannot_become_historical_by_relabeling(self):
        projected_cell = replace(self.cell, year=2024)
        with self.assertRaisesRegex(ValueError, "boundary"):
            replace(self.count, cell=projected_cell)
        row = Observation(
            replace(self.count, cell=projected_cell, status=Status.PROJECTED, quality=Quality.MODELED),
            replace(self.exposure, cell=projected_cell),
        )
        self.assertFalse(eligible_outcome(row, data_status=Status.ESTIMATED))
        with self.assertRaisesRegex(ValueError, "ineligible"):
            eligible_outcome(row, data_status=Status.PROJECTED)

    def test_truncated_cohort_never_returns_lifetime_expectancy(self):
        trace = diagonal(
            [Observation(self.count, self.exposure)], territory="EXA", geography="v1",
            coverage="national", sex=Sex.FEMALE, release=self.release, birth_year=2000, terminal_age=2,
        )
        self.assertEqual([(step.year, step.rate) for step in trace.steps], [(2000, 0), (2001, None), (2002, None)])
        with self.assertRaisesRegex(ValueError, "unbroken"):
            trace.table()
