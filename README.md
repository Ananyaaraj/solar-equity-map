# Building-level rooftop solar potential and equity map

For every roof in a city this project estimates how much electricity it could generate (from a LiDAR-style elevation model), then overlays income, energy bills and home ownership to find **high-potential roofs in high-need areas** for targeted solar programmes. Results are stored in a spatial database and shown on an interactive web map.

The demo runs on a **synthetic city placed over Coimbatore** (322 buildings, 25 zones, a 1 m surface model), so nothing has to be downloaded. A loader for real data is included.

## 1. What to install

| Item | Version | Notes |
|---|---|---|
| Python | 3.10 to 3.12 | python.org. On Windows tick "Add Python to PATH" |
| Python packages | see `requirements.txt` | numpy, pandas, shapely, pyproj, geopandas, rasterio, flask |
| Internet while viewing the map | - | Leaflet, fonts and OpenStreetMap/Esri tiles load online. No API key is needed |
| Docker (optional) | any | Only for the PostGIS backend |

## 2. How to run

```bash
# 1. unzip, then open a terminal inside the folder
cd solar-equity-map

# 2. (recommended) virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. install
pip install -r requirements.txt

# 4. generate demo data, run the analysis, start the map
python run_all.py
```

Open **http://127.0.0.1:5000**. Stop with Ctrl+C.

If you only want to view the map again later: `python app.py`.
To run the checks: `python -m unittest discover -s tests -v` (16 tests).

Step by step instead of `run_all.py`:

```bash
python generate_data.py     # writes data/dsm.tif and the buildings/tracts tables
python analyze.py           # solar model + equity overlay -> database + outputs/
python app.py               # web map
```

## 3. Folder layout

| Path | Purpose |
|---|---|
| `config.py` | Every tunable number: panel efficiency, thresholds, paths, database backend |
| `db.py` | Spatial database layer (GeoPackage or PostGIS) |
| `generate_data.py` | Builds the synthetic DSM, footprints and zones |
| `ingest_real_data.py` | Loads your own DSM, footprints and zone data |
| `solar_model.py` | Sun position, clear-sky irradiance, tilted-roof model |
| `analyze.py` | Full pipeline from DSM to priority roofs |
| `app.py`, `templates/`, `static/` | Flask server and Leaflet map |
| `sql/` | Example spatial SQL (PostGIS) and attribute SQL (GeoPackage) |
| `tests/test_smoke.py` | Unit and end-to-end tests |
| `outputs/` | `summary.json`, `tract_summary.csv`, `priority_buildings.csv`, `annual_irradiance.tif` (opens in QGIS) |

## 4. How it works

| Step | Method |
|---|---|
| 1. Roof pixels | Footprints are shrunk 1.5 m and rasterised onto the DSM grid |
| 2. Roof shape | Slope and aspect per pixel from the DSM gradient. Flat roofs get south-facing frames at 10 degrees |
| 3. Shading | For 16 compass directions, march 80 m outward and keep the highest obstruction angle (horizon). Trees, neighbours and stair-heads all count |
| 4. Sunlight | 12 representative days, hourly sun positions, Haurwitz clear-sky model, monthly clearness for the monsoon, Erbs beam/diffuse split |
| 5. Roof irradiance | Beam on the tilted pixel (zero when the sun is below the horizon), plus diffuse scaled by sky view, plus ground reflection |
| 6. Usable area | Slope up to 45 degrees, not north-facing, at least 75 % of an ideal unshaded surface, then 65 % usable fraction for tanks and walkways |
| 7. Energy | kWp = panel area x 0.20. kWh = irradiance x panel area x 0.20 x performance ratio 0.78 |
| 8. Zone join | Each building's representative point is matched to its zone |
| 9. Need index | 50 % energy bills as share of income + 50 % low income (both scaled 0 to 1) |
| 10. Priority roof | System of at least 3 kWp, in the top third of zones by need, and above the median output of all roofs |
| 11. Programme | Owner-occupied home: subsidy. Rented home: landlord incentive or community solar. Commercial: PPA. Institutional: public-building programme |

Sample result on the demo city: about 8.3 MWp and 12.4 GWh a year, around 1,480 kWh per kWp, and 50 priority roofs worth 2.7 GWh a year.

### GeoPackage vs PostGIS

| | GeoPackage (default) | PostGIS |
|---|---|---|
| Install | Nothing | Docker or a Postgres server |
| Spatial SQL (`ST_Within`, `ST_DWithin`) | Not in plain SQLite | Full |
| Multi-user | No | Yes |
| Opens in QGIS | Yes | Yes |
| Best for | Demos, single laptop | Large cities, teams |

To use PostGIS:

```bash
docker compose up -d
pip install -r requirements-postgis.txt
export DB_BACKEND=postgis          # Windows PowerShell: $env:DB_BACKEND="postgis"
python generate_data.py && python analyze.py && python app.py
```

Then run the queries in `sql/postgis_queries.sql`. The PostGIS path is written but I could not run it in my build environment (no Docker), so treat it as untested. The GeoPackage path was tested end to end.

## 5. Using real data

1. **Elevation (DSM)**: airborne LiDAR rasterised to a surface model at 1 m or finer. Photogrammetry from a drone (OpenDroneMap) also works. Free global 30 m models are too coarse for individual roofs.
2. **Footprints**: OpenStreetMap, or the Google and Microsoft open building datasets.
3. **Zone data**: census wards or tracts with income, owner share, households and, if available, energy-bill share.

```bash
python ingest_real_data.py --dsm city_dsm.tif --buildings footprints.geojson --tracts wards.geojson \
   --tract-id-col WARD_NO --income-col MED_INCOME --owner-col OWNER_PCT --households-col HH \
   --avg-annual-bill 18000 --use-col TYPE
python analyze.py
python app.py
```

The DSM must use a metric projected CRS (such as UTM). Check which datasets exist for your city before committing to a topic.

## 6. Limitations to state in your report

* Clear-sky model with a monthly clearness multiplier, not measured weather files. Swap in TMY data for more accuracy.
* Horizon search stops at 80 m and uses 16 directions, so very long shadows from tall towers are underestimated.
* Obstructions on real roofs (tanks, dishes) only appear if the LiDAR is dense enough.
* The demo data is synthetic, so the findings describe the method, not Coimbatore.
* On the demo, high-need zones have fewer roofs per household, which mirrors a real equity issue: rooftop schemes alone under-serve dense low-income areas, hence the community solar route.

## 7. Quick-fire questions for your viva

1. **Why a DSM and not a DEM?** A DSM includes roofs, trees and tanks, which is what shades and shapes a roof. A DEM is bare ground.
2. **How is shading computed?** Horizon angle per pixel in 16 directions. A sun position is blocked when its elevation is below the horizon in that direction.
3. **Why is sky-view factor needed?** It reduces diffuse light for pixels that see less sky.
4. **Why use `representative_point` for the join?** A centroid of an L-shaped footprint can fall outside it. A representative point always lies inside.
5. **Why a projected CRS?** Areas, slopes and distances need metres. Degrees distort them.
6. **Why does ownership matter?** Renters cannot install panels, so a different programme route is needed.
7. **Why no hard accuracy claim?** The model is a screening tool. A site survey is needed before installation.
8. **Name two ways to validate it.** Compare with measured output from rooftop systems, and with an established tool such as PVGIS or pvlib at the same site.
