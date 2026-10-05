"""Load REAL data into the spatial database (replaces the synthetic demo).

Example
  python ingest_real_data.py \
      --dsm my_lidar_dsm.tif \
      --buildings footprints.geojson \
      --tracts wards.geojson \
      --tract-id-col WARD_NO --income-col MED_INCOME --owner-col OWNER_PCT \
      --burden-col BILL_PCT --households-col HH

Requirements
  * DSM must be in a METRIC projected CRS (e.g. UTM). Re-project with gdalwarp if not.
  * Buildings/tracts may use any CRS; they are re-projected to the DSM CRS.
  * owner-col may be 0-1 or 0-100 (auto-detected).
  * If you have no energy-burden column, pass --avg-annual-bill (INR) and it is
    estimated as bill / income.
Then run:  python analyze.py
"""
import argparse
import shutil

import geopandas as gpd
import numpy as np
import rasterio

import config
import db


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsm", required=True)
    ap.add_argument("--buildings", required=True)
    ap.add_argument("--tracts", required=True)
    ap.add_argument("--tract-id-col", required=True)
    ap.add_argument("--income-col", required=True)
    ap.add_argument("--owner-col", required=True)
    ap.add_argument("--households-col", required=True)
    ap.add_argument("--burden-col")
    ap.add_argument("--avg-annual-bill", type=float, default=18000.0)
    ap.add_argument("--building-id-col")
    ap.add_argument("--use-col", help="column with residential / commercial / institutional")
    ap.add_argument("--owner-occ-col", help="1 = owner-occupied, 0 = rented (optional)")
    ap.add_argument("--floors-col")
    a = ap.parse_args()

    with rasterio.open(a.dsm) as src:
        crs = src.crs
        if crs is None or not crs.is_projected:
            raise SystemExit("DSM must have a projected (metric) CRS, e.g. UTM. Re-project it first.")
    shutil.copyfile(a.dsm, config.DSM_PATH)
    config.PROJECTED_CRS = str(crs)

    b = gpd.read_file(a.buildings).to_crs(crs)
    b = b[b.geometry.type.isin(["Polygon", "MultiPolygon"])].explode(index_parts=False).reset_index(drop=True)
    out_b = gpd.GeoDataFrame({
        "building_id": b[a.building_id_col] if a.building_id_col else np.arange(1, len(b) + 1),
        "use_type": b[a.use_col].str.lower() if a.use_col else "residential",
        "owner_occ": b[a.owner_occ_col].astype(int) if a.owner_occ_col else 1,
        "floors": b[a.floors_col].astype(int) if a.floors_col else 1,
    }, geometry=b.geometry, crs=crs)
    out_b["use_type"] = out_b.use_type.where(out_b.use_type.isin(["residential", "commercial", "institutional"]),
                                             "residential")

    t = gpd.read_file(a.tracts).to_crs(crs)
    owner = t[a.owner_col].astype(float)
    income = t[a.income_col].astype(float)
    burden = t[a.burden_col].astype(float) if a.burden_col else 100.0 * a.avg_annual_bill / income
    out_t = gpd.GeoDataFrame({
        "tract_id": t[a.tract_id_col].astype(str),
        "name": t[a.tract_id_col].astype(str),
        "median_income_inr": income,
        "owner_rate": np.where(owner > 1.5, owner / 100.0, owner),
        "energy_burden_pct": burden,
        "households": t[a.households_col].astype(int),
    }, geometry=t.geometry, crs=crs)

    db.reset()
    db.write_layer(out_b, "buildings")
    db.write_layer(out_t, "tracts")
    print(f"Loaded {len(out_b)} buildings and {len(out_t)} tracts. Now run: python analyze.py")


if __name__ == "__main__":
    main()
