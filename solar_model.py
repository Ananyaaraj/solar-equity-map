"""Solar position + irradiance model (pure numpy, no pvlib needed).

Pipeline per roof pixel:
  1. sun position for 12 representative days x every daylight hour
  2. Haurwitz clear-sky GHI, scaled by a monthly clearness factor
  3. Erbs split of GHI into beam (DNI) and diffuse (DHI)
  4. beam on the tilted roof (cos of incidence) - zero if the sun is below the pixel's horizon
  5. diffuse (scaled by sky-view factor and tilt) + ground-reflected
  6. integrate over the year -> kWh / m2 / year
"""
import numpy as np

import config

MONTH_DAYS = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
MID_DOY = np.array([17, 47, 75, 105, 135, 162, 198, 228, 258, 288, 318, 344])


def sun_geometry(lat_deg, doy, hours):
    """Sun elevation and azimuth (radians, azimuth clockwise from north)
    at local *solar* time `hours` on day-of-year `doy`."""
    lat = np.radians(lat_deg)
    decl = np.radians(23.45 * np.sin(np.radians(360.0 * (284 + doy) / 365.0)))
    hour_angle = np.radians(15.0 * (np.asarray(hours, dtype=float) - 12.0))
    sin_alt = np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.cos(hour_angle)
    alt = np.arcsin(np.clip(sin_alt, -1.0, 1.0))
    cos_az = (np.sin(decl) - np.sin(alt) * np.sin(lat)) / (np.cos(alt) * np.cos(lat) + 1e-12)
    az = np.arccos(np.clip(cos_az, -1.0, 1.0))
    az = np.where(hour_angle > 0, 2 * np.pi - az, az)  # afternoon = west of south
    return alt, az


def clear_sky_components(alt, doy, clearness):
    """Return (GHI, DHI, DNI) in W/m2 for sun elevation `alt` (radians)."""
    cosz = np.sin(alt)
    ok = cosz > 0.05
    cz = np.where(ok, cosz, 1.0)
    g0 = 1361.0 * (1 + 0.033 * np.cos(2 * np.pi * doy / 365.0))
    ghi = np.where(ok, 1098.0 * cz * np.exp(-0.057 / cz) * clearness, 0.0)
    kt = np.clip(ghi / (g0 * cz), 0.0, 1.0)
    kd = np.where(
        kt <= 0.22, 1 - 0.09 * kt,
        np.where(kt <= 0.80,
                 0.9511 - 0.1604 * kt + 4.388 * kt**2 - 16.638 * kt**3 + 12.336 * kt**4,
                 0.165))
    dhi = kd * ghi
    dni = np.where(ok, (ghi - dhi) / cz, 0.0)
    return ghi, dhi, dni


def annual_irradiance(tilt, aspect, horizon, lat_deg, clearness=None,
                      albedo=None, hour_step=None):
    """Annual plane-of-array irradiation in kWh/m2/year.

    tilt, aspect : (n,) radians. aspect = direction the surface faces (0 = north, clockwise)
    horizon      : (n_dirs, n) horizon elevation angle (radians) in n_dirs compass directions
    """
    clearness = config.MONTHLY_CLEARNESS if clearness is None else clearness
    albedo = config.ALBEDO if albedo is None else albedo
    hour_step = config.HOUR_STEP if hour_step is None else hour_step

    n_dirs = horizon.shape[0]
    cos_t, sin_t = np.cos(tilt), np.sin(tilt)
    svf = 1.0 - np.mean(np.sin(horizon) ** 2, axis=0)          # sky-view factor
    diffuse_scale = svf * (1 + cos_t) / 2.0
    refl_scale = albedo * (1 - cos_t) / 2.0
    total = np.zeros(tilt.shape[0], dtype=np.float64)
    hours = np.arange(5.0, 19.0001, hour_step)

    for m in range(12):
        doy = MID_DOY[m]
        alt, az = sun_geometry(lat_deg, doy, hours)
        ghi, dhi, dni = clear_sky_components(alt, doy, clearness[m])
        weight = MONTH_DAYS[m] * hour_step / 1000.0             # Wh -> kWh over the month
        for i in range(len(hours)):
            if ghi[i] <= 0:
                continue
            f = az[i] / (2 * np.pi / n_dirs)
            i0 = int(np.floor(f)) % n_dirs
            i1 = (i0 + 1) % n_dirs
            w = f - np.floor(f)
            hor = (1 - w) * horizon[i0] + w * horizon[i1]       # interpolated horizon
            lit = alt[i] > hor
            cos_inc = np.sin(alt[i]) * cos_t + np.cos(alt[i]) * sin_t * np.cos(az[i] - aspect)
            beam = dni[i] * np.clip(cos_inc, 0.0, None) * lit
            total += weight * (beam + dhi[i] * diffuse_scale + ghi[i] * refl_scale)
    return total
