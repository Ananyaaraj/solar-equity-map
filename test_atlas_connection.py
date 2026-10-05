"""MongoDB Atlas Connection and Geospatial Verification Script.

Usage:
    python test_atlas_connection.py
"""
import os
import sys
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import config
import db
import pymongo


def verify():
    print("=" * 60)
    print("MongoDB Atlas & Geospatial Verification")
    print("=" * 60)

    uri = config.MONGODB_URI.strip()
    print(f"Backend configured in config: {config.DB_BACKEND}")
    if not uri or "<username>" in uri or "<YOUR_MONGODB_ATLAS_CONNECTION_STRING>" in uri:
        print("[INFO] MONGODB_URI in .env is currently a placeholder or empty.")
        print("       To connect to your live MongoDB Atlas cluster, update .env with your connection string:")
        print("       MONGODB_URI=mongodb+srv://<username>:<password>@<cluster>.mongodb.net/solar_equity?retryWrites=true&w=majority")
        print("=" * 60)
        return False

    print("Attempting connection to MongoDB Atlas...")
    try:
        client = db.get_mongo_client()
        server_info = client.server_info()
        print(f"[SUCCESS] Connected to MongoDB Atlas! (Version: {server_info.get('version')})")
    except Exception as err:
        print(f"[ERROR] Could not connect to MongoDB Atlas: {err}")
        return False

    mongo_db = db.get_mongo_db()
    collections = mongo_db.list_collection_names()
    print(f"[INFO] Active collections in '{config.MONGODB_DB_NAME}': {collections}")

    # Check 2dsphere indexes
    for coll_name in ["buildings_solar", "tracts_solar", "buildings", "tracts"]:
        if coll_name in collections:
            indexes = list(mongo_db[coll_name].list_indexes())
            has_2dsphere = any(
                idx.get("key", {}).get("geometry") == "2dsphere" or idx.get("key", {}).get("geometry") == pymongo.GEOSPHERE
                for idx in indexes
            )
            count = mongo_db[coll_name].count_documents({})
            print(f"  - Collection '{coll_name}': {count} documents | 2dsphere index: {'PRESENT' if has_2dsphere else 'MISSING'}")

    # Test geospatial query if buildings_solar exists and has data
    if "buildings_solar" in collections and mongo_db["buildings_solar"].count_documents({}) > 0:
        print("\nTesting $geoNear spatial query on MongoDB Atlas...")
        sample_doc = mongo_db["buildings_solar"].find_one({"geometry": {"$ne": None}})
        if sample_doc and "geometry" in sample_doc and "coordinates" in sample_doc["geometry"]:
            coords = sample_doc["geometry"]["coordinates"]
            # Extract point from polygon or point
            if sample_doc["geometry"]["type"] == "Point":
                lon, lat = coords[0], coords[1]
            elif sample_doc["geometry"]["type"] in ["Polygon", "MultiPolygon"]:
                lon, lat = coords[0][0][0], coords[0][0][1]

            pipeline = [
                {
                    "$geoNear": {
                        "near": {"type": "Point", "coordinates": [lon, lat]},
                        "distanceField": "distance_m",
                        "maxDistance": 1000,
                        "spherical": True,
                    }
                },
                {"$limit": 5},
            ]
            results = list(mongo_db["buildings_solar"].aggregate(pipeline))
            print(f"[SUCCESS] $geoNear query returned {len(results)} nearby spatial records.")
            for i, r in enumerate(results, 1):
                print(f"   {i}. Building #{r.get('building_id')} - Distance: {r.get('distance_m', 0):.1f} m")

    print("\n" + "=" * 60)
    print("Verification complete.")
    print("=" * 60)
    return True


if __name__ == "__main__":
    verify()
