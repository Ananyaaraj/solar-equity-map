"""Generate a realistic *synthetic* demo city so the project runs with zero downloads.

Creates
  data/dsm.tif                  1 m Digital Surface Model (roofs with pitch, stair-heads, trees)
  buildings   (spatial DB)      footprints with use type, floors, roof type, owner-occupancy
  tracts      (spatial DB)      25 census-style zones with income, ownership, energy burden

To use REAL data instead, run  `python ingest_real_data.py --help`.
"""
import argparse

import numpy as np
import geopandas as gpd
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely import STRtree
from shapely.affinity import rotate, translate
from shapely.geometry import Point, box

import config
import db

RES = 1.0          # metres per pixel
GRID = 5           # 5 x 5 tracts
TRACT = 200.0      # metres
EXT = GRID * TRACT
LOT = 50.0         # 4 x 4 lots per tract


def _origin():
    lat, lon = config.DEMO_CENTER_LATLON
    x, y = Transformer.from_crs("EPSG:4326", config.PROJECTED_CRS, always_xy=True).transform(lon, lat)
    return x - EXT / 2, y - EXT / 2


def _window(poly, n):
    minx, miny, maxx, maxy = poly.bounds
    c0, c1 = max(int(minx / RES) - 1, 0), min(int(maxx / RES) + 2, n)
    r0, r1 = max(int((EXT - maxy) / RES) - 1, 0), min(int((EXT - miny) / RES) + 2, n)
    tr = from_origin(c0 * RES, EXT - r0 * RES, RES, RES)
    return r0, r1, c0, c1, tr


def _pixel_xy(mask, r0, c0):
    rows, cols = np.nonzero(mask)
    x = (c0 + cols + 0.5) * RES
    y = EXT - (r0 + rows + 0.5) * RES
    return rows, cols, x, y


def generate(seed: int = 42):
    rng = np.random.default_rng(seed)
    n = int(EXT / RES)
    X0, Y0 = _origin()

    # --- terrain: a very gentle plane (Coimbatore sits ~410 m a.s.l.) -------------
    xs = (np.arange(n) + 0.5) * RES
    ys = EXT - (np.arange(n) + 0.5) * RES
    gx, gy = np.meshgrid(xs, ys)
    ground = 410.0 + 0.0006 * gx + 0.0004 * gy
    dsm = ground.copy()

    # --- tracts with a NE-rich / SW-poor pattern plus noise -------------------------
    tracts, tract_geoms = [], []
    for i in range(GRID):
        for j in range(GRID):
            wn = np.clip(((i + j) / (2 * (GRID - 1))) + rng.normal(0, 0.12), 0, 1)
            income = float(np.clip(150_000 + wn * 650_000 + rng.normal(0, 50_000), 110_000, 900_000))
            burden = float(np.clip(11.5 - 8.5 * wn + rng.normal(0, 1.0), 2.0, 14.0))
            owner = float(np.clip(0.30 + 0.55 * wn + rng.normal(0, 0.08), 0.12, 0.95))
            tracts.append(dict(
                tract_id=f"T{len(tracts) + 1:02d}", name=f"Zone {chr(65 + j)}{i + 1}",
                median_income_inr=round(income, -2), owner_rate=round(owner, 3),
                energy_burden_pct=round(burden, 2),
                wealth=wn, tree_density=float(rng.uniform(0.1, 0.9)),
                fill=float(rng.uniform(0.70, 0.95)), x0=i * TRACT, y0=j * TRACT))
            tract_geoms.append(box(i * TRACT, j * TRACT, (i + 1) * TRACT, (j + 1) * TRACT))

    # --- buildings -------------------------------------------------------------------
    blds = []
    for t, tg in zip(tracts, tract_geoms):
        wn = t["wealth"]
        for a in range(int(TRACT / LOT)):
            for b in range(int(TRACT / LOT)):
                if rng.random() > t["fill"]:
                    continue
                lot = box(t["x0"] + a * LOT + 3, t["y0"] + b * LOT + 3,
                          t["x0"] + (a + 1) * LOT - 3, t["y0"] + (b + 1) * LOT - 3)
                r = rng.random()
                use = "residential" if r < 0.82 else ("commercial" if r < 0.94 else "institutional")
                big = use != "residential"
                scale = rng.uniform(0.55, 0.9) if big else rng.uniform(0.30, 0.55 + 0.30 * wn)
                w = (LOT - 6) * scale * rng.uniform(0.8, 1.0)
                d = (LOT - 6) * scale * rng.uniform(0.8, 1.0)
                cx = (lot.bounds[0] + lot.bounds[2]) / 2 + rng.uniform(-1.5, 1.5)
                cy = (lot.bounds[1] + lot.bounds[3]) / 2 + rng.uniform(-1.5, 1.5)
                poly = box(cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2)
                ang = float(rng.choice([0, 0, 0, 15, -15, 20]))
                rpoly = rotate(poly, ang, origin="center")
                if tg.contains(rpoly) and lot.buffer(2).contains(rpoly):
                    poly = rpoly
                else:
                    ang = 0.0
                if use == "residential":
                    floors = int(rng.integers(1, 3 + int(4 * wn * rng.random()) + 1))
                else:
                    floors = int(rng.integers(2, 6))
                roof = str(rng.choice(["flat", "mono", "gable"], p=[0.60, 0.20, 0.20])) \
                    if use == "residential" else "flat"
                if use == "residential":
                    owner_occ = int(rng.random() < t["owner_rate"])
                else:
                    owner_occ = int(rng.random() < (0.6 if use == "commercial" else 1.0))
                blds.append(dict(
                    tract=t["tract_id"], use_type=use, floors=floors, height_m=floors * 3.0,
                    roof_type=roof, owner_occ=owner_occ, geometry=poly, angle=ang))

    # --- burn roofs into the DSM -----------------------------------------------------
    for k, bd in enumerate(blds):
        poly = bd["geometry"]
        r0, r1, c0, c1, tr = _window(poly, n)
        mask = rasterize([(poly, 1)], out_shape=(r1 - r0, c1 - c0), transform=tr,
                         fill=0, dtype="uint8").astype(bool)
        if not mask.any():
            continue
        rows, cols, x, y = _pixel_xy(mask, r0, c0)
        cxy = poly.centroid
        base = ground[min(int(r0 + rows.mean()), n - 1), min(int(c0 + cols.mean()), n - 1)]
        z = np.full(len(x), base + bd["height_m"])
        if bd["roof_type"] != "flat":
            tilt = np.radians(rng.uniform(10, 25))
            az = np.radians(bd["angle"] + rng.choice([0, 90, 180, 270]))
            t = (x - cxy.x) * np.sin(az) + (y - cxy.y) * np.cos(az)   # + = downslope
            tmax = np.abs(t).max() + 1e-6
            z += np.tan(tilt) * ((tmax - t) if bd["roof_type"] == "mono" else (tmax - np.abs(t)))
            bd["roof_tilt_deg"] = round(float(np.degrees(tilt)), 1)
        else:
            bd["roof_tilt_deg"] = 0.0
        sub = dsm[r0:r1, c0:c1]
        sub[rows, cols] = z
        # stair-head / water-tank block on flat roofs = obstruction
        if bd["roof_type"] == "flat":
            inner = poly.buffer(-3.0)
            if not inner.is_empty:
                px, py = inner.centroid.x + rng.uniform(-2, 2), inner.centroid.y + rng.uniform(-2, 2)
                s = rng.uniform(1.5, 2.2)
                blk = box(px - s, py - s, px + s, py + s).intersection(poly)
                if not blk.is_empty:
                    m2 = rasterize([(blk, 1)], out_shape=(r1 - r0, c1 - c0), transform=tr,
                                   fill=0, dtype="uint8").astype(bool)
                    sub[m2] += rng.uniform(2.2, 3.0)

    # --- trees (obstructions that shade neighbouring roofs) ----------------------------
    str_tree = STRtree([b["geometry"] for b in blds])
    for t in tracts:
        for _ in range(int(t["tree_density"] * 45)):
            tx = t["x0"] + rng.uniform(2, TRACT - 2)
            ty = t["y0"] + rng.uniform(2, TRACT - 2)
            rad, h = rng.uniform(2.5, 5.5), rng.uniform(5, 13)
            if len(str_tree.query(Point(tx, ty).buffer(rad * 0.7), predicate="intersects")):
                continue
            r0, r1, c0, c1, tr = _window(Point(tx, ty).buffer(rad), n)
            xs_w = (np.arange(c0, c1) + 0.5) * RES
            ys_w = EXT - (np.arange(r0, r1) + 0.5) * RES
            wx, wy = np.meshgrid(xs_w, ys_w)
            rr = np.hypot(wx - tx, wy - ty)
            dome = np.where(rr < rad, ground[r0:r1, c0:c1] + h * np.sqrt(np.clip(1 - (rr / rad) ** 2, 0, 1)),
                            -np.inf)
            dsm[r0:r1, c0:c1] = np.maximum(dsm[r0:r1, c0:c1], dome)

    dsm = (dsm + rng.normal(0, 0.02, dsm.shape)).astype("float32")   # LiDAR-like noise

    # --- write outputs ------------------------------------------------------------------
    transform = from_origin(X0, Y0 + EXT, RES, RES)
    with rasterio.open(config.DSM_PATH, "w", driver="GTiff", height=n, width=n, count=1,
                       dtype="float32", crs=config.PROJECTED_CRS, transform=transform,
                       nodata=-9999.0, compress="lzw") as dst:
        dst.write(dsm, 1)

    bgdf = gpd.GeoDataFrame(blds, crs=config.PROJECTED_CRS)
    bgdf["geometry"] = bgdf.geometry.apply(lambda g: translate(g, X0, Y0))
    bgdf.insert(0, "building_id", np.arange(1, len(bgdf) + 1))
    bgdf = bgdf.drop(columns=["tract", "angle"])

    # households: residential units
    # dwelling units = floor area / typical flat size (small flats in poorer tracts)
    units = {t["tract_id"]: 0 for t in tracts}
    wealth = {t["tract_id"]: t["wealth"] for t in tracts}
    for b in blds:
        if b["use_type"] == "residential":
            flat_m2 = 40.0 if wealth[b["tract"]] < 0.4 else 70.0
            units[b["tract"]] += max(1, int(round(b["floors"] * b["geometry"].area / flat_m2)))
    tgdf = gpd.GeoDataFrame(
        [{k: t[k] for k in ("tract_id", "name", "median_income_inr", "owner_rate", "energy_burden_pct")}
         | {"households": int(units[t["tract_id"]])} for t in tracts],
        geometry=[translate(g, X0, Y0) for g in tract_geoms], crs=config.PROJECTED_CRS)

    db.reset()
    db.write_layer(bgdf, "buildings")
    db.write_layer(tgdf, "tracts")
    print(f"Synthetic city created: {len(bgdf)} buildings, {len(tgdf)} tracts, DSM {n}x{n} @ {RES} m")
    return bgdf, tgdf


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=42)
    generate(ap.parse_args().seed)
