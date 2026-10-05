"""Central configuration for Solar Equity Map & MongoDB Atlas Integration."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
OUT_DIR = BASE_DIR / "outputs"
DATA_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

# ----------------------------------------------------------------------------
# Spatial database backend:  "mongodb" (MongoDB Atlas) or "gpkg" (GeoPackage)
# ----------------------------------------------------------------------------
DB_BACKEND = os.getenv("DB_BACKEND", "mongodb").lower()
MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "solar_equity_db")
GPKG_PATH = DATA_DIR / "solar_equity.gpkg"

# ----------------------------------------------------------------------------
# Input data & Coordinates
# ----------------------------------------------------------------------------
DSM_PATH = DATA_DIR / "dsm.tif"          # Digital Surface Model (LiDAR-derived)
PROJECTED_CRS = "EPSG:32643"              # UTM zone 43N (Coimbatore). Must be metric.

# Centre of the demo city (lat, lon) - near Coimbatore / PSG Tech area
DEMO_CENTER_LATLON = (11.0245, 77.0028)
PSG_TECH_LATLON = (11.0245, 77.0028)

# ----------------------------------------------------------------------------
# Solar model parameters
# ----------------------------------------------------------------------------
SETBACK_M = 1.5                 # shrink footprints so eaves/walls don't pollute slope
FLAT_THRESHOLD_DEG = 6.0        # roofs flatter than this get tilted mounting frames
MOUNT_TILT_DEG = 10.0           # tilt of frames on flat roofs
MOUNT_AZIMUTH_DEG = 180.0       # frames face south (northern hemisphere)
FLAT_GCR = 0.5                  # ground-cover ratio for frames on flat roofs (row spacing)
MAX_TILT_DEG = 45.0             # steeper roof pixels are unusable
MIN_REL_IRRADIANCE = 0.75       # pixel must receive >= 75 % of an ideal unshaded surface
USABLE_FRACTION = 0.65          # tanks, stair-heads, walkways, safety clearances
PANEL_EFF = 0.20                # module efficiency (kWp per m2 of panel)
PERFORMANCE_RATIO = 0.78        # inverter, wiring, temperature, soiling losses
ALBEDO = 0.20
HOUR_STEP = 1.0                 # sun-position time step (hours)

# Monthly clear-sky multipliers (monsoon-affected, Coimbatore-like), Jan..Dec
MONTHLY_CLEARNESS = [0.88, 0.90, 0.88, 0.80, 0.72, 0.62,
                     0.60, 0.64, 0.72, 0.66, 0.66, 0.78]

# Horizon (shading) search
HORIZON_DIRS = 16
HORIZON_MAX_DIST_M = 80.0
HORIZON_STEP_M = 2.0

# ----------------------------------------------------------------------------
# Equity model parameters
# ----------------------------------------------------------------------------
HH_DEMAND_KWH = 1800            # annual electricity use of an average household
MIN_PRIORITY_KWP = 3.0          # smaller systems are not worth a programme visit
