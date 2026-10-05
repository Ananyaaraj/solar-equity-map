"""Spatial-database abstraction layer.

Supported Backends:
- "mongodb" (default, MongoDB Atlas cloud database with 2dsphere spatial indexing)
- "gpkg"    (GeoPackage SQLite spatial database)
- "postgis" (PostgreSQL / PostGIS spatial database)

Exposes write_layer, read_layer, query, and reset functions so application logic remains clean.
"""
import json
import sqlite3
import pandas as pd
import geopandas as gpd
import pymongo

import config

_mongo_client = None
_mongo_tested = False
_mongo_available = False


def is_mongo_configured() -> bool:
    """Check if a valid MongoDB connection string is provided in .env."""
    uri = config.MONGODB_URI.strip()
    return bool(uri and "<username>" not in uri and "<YOUR_MONGODB_ATLAS_CONNECTION_STRING>" not in uri)


def get_mongo_client():
    """Retrieve or initialize the MongoDB Atlas PyMongo client."""
    global _mongo_client, _mongo_tested, _mongo_available
    if _mongo_client is not None:
        return _mongo_client
    if _mongo_tested and not _mongo_available:
        raise ConnectionError("MongoDB Atlas is offline or unreachable.")

    if not is_mongo_configured():
        _mongo_tested = True
        _mongo_available = False
        raise ValueError(
            "MongoDB Atlas connection string is missing or unconfigured.\n"
            "Please update MONGODB_URI in your .env file with your actual MongoDB Atlas connection string."
        )

    connection_attempts = [
        {"serverSelectionTimeoutMS": 1500, "tls": True, "tlsAllowInvalidCertificates": True},
        {"serverSelectionTimeoutMS": 1500}
    ]

    last_err = None
    for opts in connection_attempts:
        try:
            client = pymongo.MongoClient(config.MONGODB_URI, **opts)
            client.admin.command("ping")
            _mongo_client = client
            _mongo_tested = True
            _mongo_available = True
            return _mongo_client
        except Exception as err:
            last_err = err

    _mongo_tested = True
    _mongo_available = False
    raise ConnectionError(
        f"Failed to connect to MongoDB Atlas: {last_err}\n"
        "Please check your network connection, username, password, and Atlas IP access list."
    )


def get_mongo_db():
    """Get the active MongoDB database instance."""
    client = get_mongo_client()
    return client[config.MONGODB_DB_NAME]


def _engine():
    from sqlalchemy import create_engine
    return create_engine(config.POSTGRES_URL)


def write_layer(gdf: gpd.GeoDataFrame, name: str) -> None:
    """Create or overwrite a database table/collection containing spatial geometry."""
    # Always save a GeoPackage fallback copy so local operations work offline
    try:
        gdf.to_file(config.GPKG_PATH, layer=name, driver="GPKG")
    except Exception:
        pass

    if config.DB_BACKEND == "mongodb" and is_mongo_configured():
        try:
            db_inst = get_mongo_db()
            coll = db_inst[name]
            coll.drop()

            # Convert GeoDataFrame to WGS84 GeoJSON features
            g_wgs84 = gdf.to_crs(4326).copy()
            geojson_data = json.loads(g_wgs84.to_json(drop_id=True))
            features = geojson_data.get("features", [])

            docs = []
            for feat in features:
                doc = feat.get("properties", {})
                doc["geometry"] = feat.get("geometry")
                docs.append(doc)

            if docs:
                coll.insert_many(docs)
                # Create 2dsphere index for GeoJSON spatial queries
                coll.create_index([("geometry", pymongo.GEOSPHERE)])
        except Exception as err:
            print(f"[WARNING] MongoDB Atlas write failed ({err}). Saved to local GeoPackage layer '{name}'.")
    elif config.DB_BACKEND == "postgis":
        try:
            eng = _engine()
            gdf.to_postgis(name, eng, if_exists="replace", index=False)
            with eng.begin() as con:
                from sqlalchemy import text
                con.execute(text(f'CREATE INDEX IF NOT EXISTS "{name}_gix" ON "{name}" USING GIST (geometry)'))
        except Exception as err:
            print(f"[WARNING] PostGIS write failed ({err}).")


def read_layer(name: str) -> gpd.GeoDataFrame:
    """Read a spatial layer from the database as a GeoDataFrame."""
    if config.DB_BACKEND == "mongodb" and is_mongo_configured():
        try:
            db_inst = get_mongo_db()
            coll = db_inst[name]
            docs = list(coll.find({}, {"_id": 0}))
            if docs:
                features = []
                for d in docs:
                    geom = d.get("geometry")
                    props = {k: v for k, v in d.items() if k != "geometry"}
                    features.append({"type": "Feature", "geometry": geom, "properties": props})
                return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        except Exception as err:
            print(f"[WARNING] MongoDB Atlas read failed ({err}). Reading from local GeoPackage layer '{name}'.")

    if config.DB_BACKEND == "postgis":
        try:
            return gpd.read_postgis(f'SELECT * FROM "{name}"', _engine(), geom_col="geometry")
        except Exception:
            pass

    if config.GPKG_PATH.exists():
        gdf = gpd.read_file(config.GPKG_PATH, layer=name)
        if gdf.crs is not None and str(gdf.crs).lower() != "epsg:4326":
            gdf = gdf.to_crs(4326)
        return gdf
    return gpd.GeoDataFrame()


def query(query_input) -> pd.DataFrame:
    """Run spatial/attribute query on the active database backend."""
    if config.DB_BACKEND == "mongodb" and is_mongo_configured():
        try:
            db_inst = get_mongo_db()
            if isinstance(query_input, str):
                coll_name = query_input
                docs = list(db_inst[coll_name].find({}, {"_id": 0}))
                return pd.DataFrame(docs)
            elif isinstance(query_input, dict):
                coll_name = query_input.get("collection", "buildings_solar")
                filter_spec = query_input.get("filter", {})
                docs = list(db_inst[coll_name].find(filter_spec, {"_id": 0}))
                return pd.DataFrame(docs)
            elif isinstance(query_input, list):
                coll_name = "buildings_solar"
                docs = list(db_inst[coll_name].aggregate(query_input))
                for d in docs:
                    if "_id" in d:
                        del d["_id"]
                return pd.DataFrame(docs)
        except Exception as err:
            print(f"[WARNING] MongoDB Atlas query failed ({err}). Falling back to GeoPackage.")

    if config.DB_BACKEND == "postgis":
        try:
            sql = query_input if isinstance(query_input, str) else "SELECT * FROM buildings_solar"
            return pd.read_sql(sql, _engine())
        except Exception:
            pass

    if config.GPKG_PATH.exists():
        con = sqlite3.connect(config.GPKG_PATH)
        try:
            sql = query_input if isinstance(query_input, str) else "SELECT * FROM buildings_solar"
            return pd.read_sql_query(sql, con)
        finally:
            con.close()
    return pd.DataFrame()


def reset() -> None:
    """Delete or drop database collections for a fresh run."""
    if config.DB_BACKEND == "mongodb" and is_mongo_configured():
        try:
            db_inst = get_mongo_db()
            for name in ["buildings", "tracts", "buildings_solar", "tracts_solar"]:
                db_inst[name].drop()
        except Exception:
            pass
    if config.GPKG_PATH.exists():
        config.GPKG_PATH.unlink()
