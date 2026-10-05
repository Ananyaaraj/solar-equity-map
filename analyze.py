"""Rooftop solar potential + equity analysis.

Steps
  1. Read the DSM and the building footprints / tracts from the spatial database
  2. Burn building IDs into a raster (label raster)
  3. Slope + aspect from the DSM   -> roof geometry per pixel
  4. Horizon angles from the DSM   -> shading per pixel
  5. Annual irradiance per roof pixel (solar_model)
  6. Filter suitable pixels, convert to panel area, kWp and kWh
  7. Aggregate per building, spatially join to tracts
  8. Equity indices, priority score, programme recommendation
  9. Write results back to the database + CSV / GeoTIFF / JSON outputs
"""
import json

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize

import config
import db
import solar_model


# ---------------------------------------------------------------------------- raster
def load_dsm():
    with rasterio.open(config.DSM_PATH) as src:
        arr = src.read(1).astype("float32")
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
        if np.isnan(arr).any():
            arr = np.where(np.isnan(arr), np.nanmin(arr), arr)
        return arr, src.transform, src.crs, src.profile


def slope_aspect(dsm, res):
    """Slope (rad) and aspect (rad, direction the surface FACES, 0 = north, clockwise)."""
    dz_drow, dz_dcol = np.gradient(dsm, res)
    dz_dx, dz_dn = dz_dcol, -dz_drow            # rows grow southwards
    slope = np.arctan(np.hypot(dz_dx, dz_dn))
    aspect = np.arctan2(-dz_dx, -dz_dn) % (2 * np.pi)
    return slope, aspect


def horizon_angles(dsm, res, rr, cc, n_dirs, max_dist, step):
    """Horizon elevation angle for each roof pixel in n_dirs compass directions.
    Marches outward along each direction and keeps the steepest obstruction angle."""
    pad = int(np.ceil(max_dist / res)) + 2
    padded = np.pad(dsm, pad, mode="edge")
    z0 = dsm[rr, cc]
    out = np.zeros((n_dirs, len(rr)), dtype=np.float32)
    for k in range(n_dirs):
        az = 2 * np.pi * k / n_dirs
        ex, ny = np.sin(az), np.cos(az)
        hmax = np.zeros(len(rr), dtype=np.float32)
        for d in np.arange(step, max_dist + 1e-6, step):
            dc = int(round(ex * d / res))
            dr = int(round(-ny * d / res))
            ang = np.arctan2(padded[rr + pad + dr, cc + pad + dc] - z0, d)
            np.maximum(hmax, ang, out=hmax)
        out[k] = hmax
    return out


# ---------------------------------------------------------------------------- helpers
def minmax(s):
    s = s.astype(float)
    rng = s.max() - s.min()
    return (s - s.min()) / rng if rng > 0 else s * 0.0


PROGRAMS = {
    "owner": "Owner rooftop subsidy",
    "rental": "Landlord incentive / community solar",
    "commercial": "Commercial PPA / RESCO",
    "institutional": "Public-building rooftop programme",
}


def programme(row):
    if row.use_type == "residential":
        return PROGRAMS["owner"] if row.owner_occ == 1 else PROGRAMS["rental"]
    return PROGRAMS[row.use_type]


# ---------------------------------------------------------------------------- pipeline
def run():
    dsm, transform, crs, profile = load_dsm()
    res = abs(transform.a)
    print(f"DSM {dsm.shape[1]}x{dsm.shape[0]} px @ {res} m, CRS {crs}")

    buildings = db.read_layer("buildings").to_crs(crs).reset_index(drop=True)
    tracts = db.read_layer("tracts").to_crs(crs).reset_index(drop=True)
    for col, default in (("use_type", "residential"), ("owner_occ", 1), ("floors", 1)):
        if col not in buildings:
            buildings[col] = default

    cx, cy = rasterio.transform.xy(transform, dsm.shape[0] // 2, dsm.shape[1] // 2)
    lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(cx, cy)
    print(f"Site latitude {lat:.3f}, longitude {lon:.3f}")

    # 1) label raster: pixel -> building (shrunk by setback so walls/eaves are excluded)
    shrunk = buildings.geometry.buffer(-config.SETBACK_M)
    shapes = [(g, i + 1) for i, g in enumerate(shrunk) if not g.is_empty]
    labels = rasterize(shapes, out_shape=dsm.shape, transform=transform, fill=0, dtype="int32")
    rr, cc = np.nonzero(labels)
    lab = labels[rr, cc]
    print(f"{len(shapes)} roofs rasterised, {len(rr):,} roof pixels")

    # 2) roof geometry
    slope, aspect = slope_aspect(dsm, res)
    s_px, a_px = slope[rr, cc], aspect[rr, cc]
    flat = s_px < np.radians(config.FLAT_THRESHOLD_DEG)
    tilt = np.where(flat, np.radians(config.MOUNT_TILT_DEG), s_px)
    asp = np.where(flat, np.radians(config.MOUNT_AZIMUTH_DEG), a_px)

    # 3) shading + irradiance
    print("Computing horizons ...")
    hor = horizon_angles(dsm, res, rr, cc, config.HORIZON_DIRS,
                         config.HORIZON_MAX_DIST_M, config.HORIZON_STEP_M)
    print("Integrating annual irradiance ...")
    irr = solar_model.annual_irradiance(tilt, asp, hor, lat)
    ref = float(solar_model.annual_irradiance(
        np.array([np.radians(abs(lat))]), np.array([np.pi if lat >= 0 else 0.0]),
        np.zeros((config.HORIZON_DIRS, 1)), lat)[0])
    print(f"Reference (ideal unshaded, tilt=latitude, facing equator): {ref:.0f} kWh/m2/yr")

    # 4) suitability -> panel area, kWp, kWh
    north_facing = (~flat) & ((a_px < np.radians(60)) | (a_px > np.radians(300))) if lat >= 0 \
        else (~flat) & (np.abs(a_px - np.pi) < np.radians(60))
    suit = (tilt <= np.radians(config.MAX_TILT_DEG)) & ~north_facing & (irr >= config.MIN_REL_IRRADIANCE * ref)
    area_factor = np.where(flat, config.FLAT_GCR, 1.0 / np.cos(tilt)) * res * res
    panel_area = area_factor * suit * config.USABLE_FRACTION
    kwp = panel_area * config.PANEL_EFF
    kwh = irr * panel_area * config.PANEL_EFF * config.PERFORMANCE_RATIO

    # 5) per-building aggregation
    px = pd.DataFrame({"lab": lab, "irr": irr, "suit": suit, "area": panel_area, "kwp": kwp,
                       "kwh": kwh, "tilt": np.degrees(tilt), "svf": 1 - np.mean(np.sin(hor) ** 2, axis=0)})
    agg = px.groupby("lab").agg(mean_irr_kwh_m2=("irr", "mean"), suitable_px=("suit", "sum"),
                                panel_area_m2=("area", "sum"), capacity_kwp=("kwp", "sum"),
                                annual_kwh=("kwh", "sum"), mean_tilt_deg=("tilt", "mean"),
                                sky_view=("svf", "mean"))
    agg.index = agg.index - 1
    b = buildings.join(agg).fillna({c: 0 for c in agg.columns})
    b["roof_area_m2"] = b.geometry.area
    b["specific_yield"] = np.where(b.capacity_kwp > 0, b.annual_kwh / b.capacity_kwp.replace(0, np.nan), 0)
    b["suitable_pct"] = 100 * b.suitable_px * res * res / b.roof_area_m2.clip(lower=1)

    # 6) spatial join -> tract
    pts = b.copy()
    pts["geometry"] = b.geometry.representative_point()
    joined = gpd.sjoin(pts, tracts[["tract_id", "geometry"]], predicate="within", how="left")
    b["tract_id"] = joined["tract_id"].values

    # 7) tract-level equity + potential
    t = tracts.copy()
    res_b = b[b.use_type == "residential"]
    g_all = b.groupby("tract_id").agg(n_buildings=("building_id", "count"),
                                      capacity_kwp=("capacity_kwp", "sum"), annual_kwh=("annual_kwh", "sum"))
    g_res = res_b.groupby("tract_id").agg(res_kwh=("annual_kwh", "sum"))
    t = t.merge(g_all, on="tract_id", how="left").merge(g_res, on="tract_id", how="left").fillna(0)
    hh = t.households.clip(lower=1)
    t["solar_kwh_per_hh"] = t.res_kwh / hh
    t["demand_met_pct"] = 100 * t.res_kwh / (hh * config.HH_DEMAND_KWH)
    t["need_index"] = 0.5 * minmax(t.energy_burden_pct) + 0.5 * (1 - minmax(t.median_income_inr))
    t["need_tercile"] = pd.qcut(t.need_index.rank(method="first"), 3, labels=False)      # 0 low .. 2 high
    t["pot_tercile"] = pd.qcut(t.solar_kwh_per_hh.rank(method="first"), 3, labels=False)
    pot_high = t.solar_kwh_per_hh >= t.solar_kwh_per_hh.median()
    t["tract_class"] = np.select(
        [(t.need_tercile == 2) & pot_high,
         (t.need_tercile == 2) & ~pot_high,
         (t.need_tercile == 0) & pot_high],
        ["Priority: high need + above-median solar",
         "Constrained: high need + below-median solar",
         "Market-ready: low need + above-median solar"],
        default="Other")

    # 8) building priority
    b = b.merge(t[["tract_id", "need_index", "need_tercile", "pot_tercile", "median_income_inr"]],
                on="tract_id", how="left")
    b = gpd.GeoDataFrame(b, geometry="geometry", crs=crs)
    has_pv = b.capacity_kwp > 0
    pot_score = pd.Series(0.0, index=b.index)
    pot_score[has_pv] = b.loc[has_pv, "annual_kwh"].rank(pct=True)
    b["potential_score"] = pot_score
    b["priority_score"] = np.where(has_pv, 0.5 * b.potential_score + 0.5 * b.need_index.fillna(0), 0.0)
    b["is_priority"] = ((b.capacity_kwp >= config.MIN_PRIORITY_KWP) & (b.need_tercile == 2)
                        & (b.potential_score >= 0.5)).astype(int)
    b["program"] = b.apply(programme, axis=1)
    b["priority_rank"] = b.priority_score.rank(ascending=False, method="first").astype(int)
    b["households_powered"] = np.where(b.use_type == "residential", b.annual_kwh / config.HH_DEMAND_KWH, 0.0)

    prio_by_tract = b.groupby("tract_id").is_priority.sum().rename("n_priority_buildings")
    t = t.merge(prio_by_tract, on="tract_id", how="left").fillna({"n_priority_buildings": 0})

    # 9) persist
    keep = ["building_id", "tract_id", "use_type", "floors", "roof_type", "owner_occ", "program",
            "roof_area_m2", "mean_irr_kwh_m2", "mean_tilt_deg", "sky_view", "suitable_pct",
            "capacity_kwp", "annual_kwh", "specific_yield", "households_powered",
            "median_income_inr", "need_index", "potential_score", "priority_score",
            "priority_rank", "is_priority", "geometry"]
    b_out = b[keep].copy()
    db.write_layer(b_out, "buildings_solar")
    db.write_layer(t.drop(columns=["res_kwh"]), "tracts_solar")

    config.OUT_DIR.mkdir(exist_ok=True)
    t.drop(columns="geometry").to_csv(config.OUT_DIR / "tract_summary.csv", index=False)
    top = b_out[b_out.is_priority == 1].sort_values("priority_rank").drop(columns="geometry")
    top.to_csv(config.OUT_DIR / "priority_buildings.csv", index=False)

    irr_r = np.full(dsm.shape, np.nan, dtype="float32")
    irr_r[rr, cc] = irr
    prof = profile.copy()
    prof.update(dtype="float32", count=1, nodata=np.nan, compress="lzw")
    with rasterio.open(config.OUT_DIR / "annual_irradiance.tif", "w", **prof) as dst:
        dst.write(irr_r, 1)

    hi = t[t.need_tercile == 2]
    summary = {
        "site_lat": round(lat, 4), "site_lon": round(lon, 4),
        "reference_irradiance_kwh_m2": round(ref, 0),
        "n_buildings": int(len(b)), "n_buildings_with_pv": int(has_pv.sum()),
        "total_capacity_mwp": round(b.capacity_kwp.sum() / 1000, 3),
        "annual_gwh": round(b.annual_kwh.sum() / 1e6, 3),
        "avg_specific_yield_kwh_kwp": round(b.annual_kwh.sum() / max(b.capacity_kwp.sum(), 1e-9), 0),
        "households_powered": int(round(b.households_powered.sum())),
        "n_priority_buildings": int(b.is_priority.sum()),
        "priority_capacity_mwp": round(b.loc[b.is_priority == 1, "capacity_kwp"].sum() / 1000, 3),
        "priority_gwh": round(b.loc[b.is_priority == 1, "annual_kwh"].sum() / 1e6, 3),
        "share_potential_in_high_need_tracts_pct": round(
            100 * hi.annual_kwh.sum() / max(t.annual_kwh.sum(), 1e-9), 1),
        "n_priority_tracts": int((t.tract_class.str.startswith("Priority")).sum()),
        "owner_occupied_priority_pct": round(
            100 * b.loc[b.is_priority == 1, "owner_occ"].mean(), 1) if b.is_priority.any() else 0.0,
    }
    (config.OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return b_out, t, summary


if __name__ == "__main__":
    run()
