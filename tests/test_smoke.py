"""Smoke tests.  Run from the project folder:  python -m unittest discover -s tests -v"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import analyze
import config
import db
import generate_data
import solar_model


class SolarMath(unittest.TestCase):
    def test_equinox_noon_sun_is_overhead_at_equator(self):
        alt, _ = solar_model.sun_geometry(0.0, 80, [12.0])
        self.assertAlmostEqual(math.degrees(alt[0]), 90.0, delta=2.0)

    def test_sun_in_south_at_noon_northern_hemisphere(self):
        _, az = solar_model.sun_geometry(11.0, 355, [12.0])     # winter
        self.assertAlmostEqual(math.degrees(az[0]), 180.0, delta=2.0)

    def test_south_facing_beats_north_facing(self):
        hor = np.zeros((16, 2))
        irr = solar_model.annual_irradiance(np.radians([30.0, 30.0]), np.radians([180.0, 0.0]), hor, 30.0)
        self.assertGreater(irr[0], irr[1])

    def test_shaded_pixel_gets_less(self):
        clear = np.zeros((16, 1))
        shaded = np.full((16, 1), math.radians(40))
        a = solar_model.annual_irradiance(np.array([0.2]), np.array([math.pi]), clear, 11.0)[0]
        b = solar_model.annual_irradiance(np.array([0.2]), np.array([math.pi]), shaded, 11.0)[0]
        self.assertLess(b, 0.8 * a)   # high midday sun at 11 N, so a 40 deg horizon costs ~1/3

    def test_slope_aspect_of_east_facing_plane(self):
        x = np.arange(50, dtype=float)
        dsm = np.tile(-0.5 * x, (50, 1))                         # falls towards east
        slope, aspect = analyze.slope_aspect(dsm, 1.0)
        self.assertAlmostEqual(math.degrees(slope[25, 25]), math.degrees(math.atan(0.5)), places=3)
        self.assertAlmostEqual(math.degrees(aspect[25, 25]), 90.0, places=3)


class KnownAnswer(unittest.TestCase):
    """Hand-calculable cases: the expected number is worked out on paper."""

    def test_horizon_angle_of_a_wall(self):
        # 10 m wall, 20 m east of the pixel  ->  horizon = atan(10/20) = 26.57 deg towards east
        dsm = np.zeros((200, 200), dtype="float32")
        dsm[:, 120:] = 10.0
        rr, cc = np.array([100]), np.array([100])
        hor = analyze.horizon_angles(dsm, 1.0, rr, cc, n_dirs=16, max_dist=80, step=1)
        east, north = hor[4, 0], hor[0, 0]            # direction index 4 of 16 = 90 deg = east
        self.assertAlmostEqual(math.degrees(east), math.degrees(math.atan(10 / 20)), delta=0.5)
        self.assertAlmostEqual(north, 0.0, places=6)

    def test_flat_open_ground_has_zero_horizon(self):
        dsm = np.zeros((100, 100), dtype="float32")
        hor = analyze.horizon_angles(dsm, 1.0, np.array([50]), np.array([50]), 16, 40, 2)
        self.assertTrue(np.allclose(hor, 0))

    def test_minmax_scaling(self):
        import pandas as pd
        s = analyze.minmax(pd.Series([10, 20, 30]))
        self.assertEqual(list(s), [0.0, 0.5, 1.0])

    def test_programme_routing(self):
        import pandas as pd
        row = lambda use, own: pd.Series({"use_type": use, "owner_occ": own})
        self.assertEqual(analyze.programme(row("residential", 1)), "Owner rooftop subsidy")
        self.assertEqual(analyze.programme(row("residential", 0)), "Landlord incentive / community solar")
        self.assertEqual(analyze.programme(row("commercial", 1)), "Commercial PPA / RESCO")

    def test_capacity_formula(self):
        # 100 m2 usable flat-roof plan area: 100 x 0.5 (row spacing) x 0.65 (usable) x 0.20 (kWp/m2) = 6.5 kWp
        kwp = 100 * config.FLAT_GCR * config.USABLE_FRACTION * config.PANEL_EFF
        self.assertAlmostEqual(kwp, 6.5, places=6)


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        generate_data.generate(seed=7)
        cls.b, cls.t, cls.summary = analyze.run()

    def test_outputs_exist(self):
        for name in ("summary.json", "tract_summary.csv", "priority_buildings.csv", "annual_irradiance.tif"):
            self.assertTrue((config.OUT_DIR / name).exists(), name)

    def test_reference_irradiance_is_plausible_for_south_india(self):
        self.assertTrue(1600 < self.summary["reference_irradiance_kwh_m2"] < 2300)

    def test_specific_yield_is_plausible(self):
        self.assertTrue(1100 < self.summary["avg_specific_yield_kwh_kwp"] < 1800)

    def test_every_building_has_a_tract(self):
        self.assertFalse(self.b.tract_id.isna().any())

    def test_database_tables_and_sql(self):
        if config.DB_BACKEND == "mongodb":
            df = db.query({"collection": "buildings_solar", "filter": {"capacity_kwp": {"$gt": 0}}})
            self.assertGreater(len(df), 100)
        else:
            df = db.query("SELECT COUNT(*) AS n FROM buildings_solar WHERE capacity_kwp > 0")
            self.assertGreater(int(df.n[0]), 100)


    def test_priority_roofs_are_only_in_high_need_zones(self):
        pri = self.b[self.b.is_priority == 1]
        self.assertTrue(len(pri) > 0)
        ids = set(self.t[self.t.need_tercile == 2].tract_id)
        self.assertTrue(set(pri.tract_id).issubset(ids))


if __name__ == "__main__":
    unittest.main()
