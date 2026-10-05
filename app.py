"""Web server: serves the interactive map and the JSON/GeoJSON API backed by MongoDB Atlas.

    python app.py            ->  http://127.0.0.1:5000
"""
import json

import pandas as pd
from flask import Flask, Response, jsonify, render_template, request

import config
import db
import spatial_lab_operations

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
_cache = {}


def _geojson(gdf, round_cols=2):
    if gdf.empty:
        return json.dumps({"type": "FeatureCollection", "features": []})
    g = gdf.to_crs(4326).copy()
    for c in g.columns:
        if c == "geometry":
            continue
        if pd.api.types.is_float_dtype(g[c]):
            g[c] = g[c].fillna(0).round(round_cols)
    return g.to_json(drop_id=True)


def load():
    """Load result layers from the spatial database once and keep them in memory."""
    if _cache:
        return _cache
    b = db.read_layer("buildings_solar")
    t = db.read_layer("tracts_solar")
    path = config.OUT_DIR / "summary.json"
    if not t.empty:
        minx, miny, maxx, maxy = t.to_crs(4326).total_bounds
        bounds = [[miny, minx], [maxy, maxx]]
    else:
        bounds = [[11.015, 76.995], [11.035, 77.015]]

    data = {
        "b_df": b,
        "t_df": t,
        "b_json": _geojson(b),
        "t_json": _geojson(t),
        "summary": json.loads(path.read_text()) if path.exists() else {},
        "bounds": bounds,
    }
    _cache.update(data)
    return _cache


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/meta")
def meta():
    c = load()
    b = c["b_df"]
    if b.empty:
        return jsonify(summary=c["summary"], bounds=c["bounds"], irr_min=0, irr_max=0, programs=[])
    return jsonify(
        summary=c["summary"],
        bounds=c["bounds"],
        irr_min=float(b.loc[b.capacity_kwp > 0, "mean_irr_kwh_m2"].min()) if (b.capacity_kwp > 0).any() else 0.0,
        irr_max=float(b.loc[b.capacity_kwp > 0, "mean_irr_kwh_m2"].max()) if (b.capacity_kwp > 0).any() else 0.0,
        programs=sorted(b.program.unique().tolist()) if "program" in b.columns else [],
    )


@app.route("/api/tracts")
def tracts():
    return Response(load()["t_json"], mimetype="application/json")


@app.route("/api/buildings")
def buildings():
    return Response(load()["b_json"], mimetype="application/json")


@app.route("/api/priority")
def priority():
    limit = min(int(request.args.get("limit", 15)), 200)
    b = load()["b_df"]
    if b.empty:
        return jsonify([])
    top = b[b.is_priority == 1].sort_values("priority_rank").head(limit)
    c = top.geometry.to_crs(4326).representative_point()
    rows = top.drop(columns="geometry").round(2).assign(lat=c.y.values, lon=c.x.values)
    return jsonify(rows.to_dict(orient="records"))


@app.route("/api/export/priority.csv")
def export_priority():
    b = load()["b_df"]
    if b.empty:
        return Response("", mimetype="text/csv")
    csv = b[b.is_priority == 1].sort_values("priority_rank").drop(columns="geometry").to_csv(index=False)
    return Response(csv, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=priority_buildings.csv"})


# ----------------------------------------------------------------------------
# Top 18 Solar Spatial Lab API Endpoints
# ----------------------------------------------------------------------------
@app.route("/api/lab/operations")
def lab_operations_list():
    """List Top 18 Solar Spatial Database Operations."""
    ops = [
        {"id": "1", "title": "1. Basic CRUD Operations on Solar Rooftops", "desc": "Create, Read, Update, Delete solar installation records in Atlas."},
        {"id": "2", "title": "2. Solar Rooftop Attribute Lookup by Coordinate (X, Y)", "desc": "Identify solar capacity (kWp), annual kWh, and tilt for clicked point (X, Y)."},
        {"id": "3", "title": "3. High-Solar Priority Zones within City ($geoWithin)", "desc": "Find all high-need census zones inside Coimbatore boundary polygon."},
        {"id": "4", "title": "4. Priority Solar Rooftops within Zone ($geoWithin)", "desc": "Find high-capacity solar rooftops (>= 3 kWp) inside a specific zone."},
        {"id": "5", "title": "5. Adjacent Solar Planning Zones ($geoIntersects)", "desc": "Find neighboring census zones sharing borders with Zone T01."},
        {"id": "6", "title": "6. Proximity Search around House ($nearSphere)", "desc": "Find nearest rooftop solar installations within 500m of a house location."},
        {"id": "7", "title": "7. Solar Rooftops within 3 km of Substation ($geoNear)", "desc": "Find high-output solar roofs within 3 km of Grid Substation / PSG Tech."},
        {"id": "8", "title": "8. Polygon Union of Solar Planning Zones", "desc": "Merge two adjacent census zones into a combined solar grid expansion boundary."},
        {"id": "9", "title": "9. Distance Measurement along Transmission Line", "desc": "Calculate distance between solar nodes and display grid LineString."},
        {"id": "10", "title": "10. Centroid of Solar Planning Zone", "desc": "Calculate central coordinate (X, Y) of zone for locating central transformer."},
        {"id": "11", "title": "11. Solar Capacity Aggregation Pipeline ($group)", "desc": "Group buildings by zone and calculate total solar capacity (MWp) on Atlas."},
        {"id": "12", "title": "12. Optimal Solar Microgrid Site Selection", "desc": "Propose optimal location for new Solar Microgrid Hub based on energy burden & solar yield."},
        {"id": "13", "title": "13. 3D Solar Rooftop Elevation & Extrusion", "desc": "3D elevation search and 2.5D building height extrusion for shading analysis."},
        {"id": "14", "title": "14. 3D Building Extrusion Block (Polygon to 3D Volume)", "desc": "Extrude rooftop polygon into 3D building prism block (height, floors, volume m³)."},
        {"id": "15", "title": "15. LineString Adjacency Query (Solar Grid Feeders)", "desc": "Find adjacent grid transmission lines intersecting main feeder LineString ($geoIntersects)."},
        {"id": "16", "title": "16. Spatial Overlay Operations (Union, Intersects, SymDiff)", "desc": "Compute spatial overlay (Union, Intersection, Symmetrical Difference) of solar zones."},
        {"id": "17", "title": "17. Substation Proximity Buffer Surface (500m Buffer)", "desc": "Create a 500m buffer surface around substation and classify roofs inside vs outside."},
        {"id": "18", "title": "18. Spatial KNN Search & Spatial Join (K-Nearest Neighbors)", "desc": "Find K closest solar rooftops to transformer nodes using spatial aggregation $geoNear."}
    ]
    return jsonify(ops)


@app.route("/api/lab/execute")
def lab_execute():
    """Execute a selected Top 18 Solar Spatial Query live on MongoDB Atlas."""
    op_id = str(request.args.get("op", "7"))
    func = spatial_lab_operations.TOP_18_SOLAR_QUERIES.get(op_id)
    if not func:
        return jsonify(error="Invalid solar operation ID"), 400

    try:
        res = func()
        return jsonify(res)
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/locations/nearby")
def nearby_locations():
    """Find spatial building records near a specified [longitude, latitude] point using MongoDB $geoNear."""
    try:
        lon = float(request.args.get("longitude", config.DEMO_CENTER_LATLON[1]))
        lat = float(request.args.get("latitude", config.DEMO_CENTER_LATLON[0]))
        distance_m = float(request.args.get("distance", 500))
        limit = min(int(request.args.get("limit", 20)), 100)

        mongo_db = db.get_mongo_db()
        pipeline = [
            {
                "$geoNear": {
                    "near": {"type": "Point", "coordinates": [lon, lat]},
                    "distanceField": "distance_m",
                    "maxDistance": distance_m,
                    "spherical": True,
                }
            },
            {"$limit": limit},
        ]
        results = list(mongo_db["buildings_solar"].aggregate(pipeline))
        for r in results:
            if "_id" in r:
                del r["_id"]
        return jsonify(count=len(results), search_point=[lon, lat], max_distance_m=distance_m, results=results)
    except Exception as e:
        return jsonify(error=str(e)), 400


@app.route("/api/locations/within")
def locations_within():
    """Find spatial records inside a bounding box polygon using MongoDB $geoWithin."""
    try:
        min_lon = float(request.args.get("min_lon", 76.995))
        min_lat = float(request.args.get("min_lat", 11.015))
        max_lon = float(request.args.get("max_lon", 77.015))
        max_lat = float(request.args.get("max_lat", 11.035))

        mongo_db = db.get_mongo_db()
        query_filter = {
            "geometry": {
                "$geoWithin": {
                    "$geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [min_lon, min_lat],
                                [max_lon, min_lat],
                                [max_lon, max_lat],
                                [min_lon, max_lat],
                                [min_lon, min_lat],
                            ]
                        ],
                    }
                }
            }
        }
        results = list(mongo_db["buildings_solar"].find(query_filter, {"_id": 0}))
        return jsonify(count=len(results), bbox=[min_lon, min_lat, max_lon, max_lat], results=results)
    except Exception as e:
        return jsonify(error=str(e)), 400


@app.route("/api/locations/intersect")
def locations_intersect():
    """Find spatial records intersecting a given geometry using MongoDB $geoIntersects."""
    try:
        min_lon = float(request.args.get("min_lon", 77.000))
        min_lat = float(request.args.get("min_lat", 11.020))
        max_lon = float(request.args.get("max_lon", 77.010))
        max_lat = float(request.args.get("max_lat", 11.030))

        mongo_db = db.get_mongo_db()
        query_filter = {
            "geometry": {
                "$geoIntersects": {
                    "$geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [min_lon, min_lat],
                                [max_lon, min_lat],
                                [max_lon, max_lat],
                                [min_lon, max_lat],
                                [min_lon, min_lat],
                            ]
                        ],
                    }
                }
            }
        }
        results = list(mongo_db["buildings_solar"].find(query_filter, {"_id": 0}))
        return jsonify(count=len(results), polygon=[min_lon, min_lat, max_lon, max_lat], results=results)
    except Exception as e:
        return jsonify(error=str(e)), 400


if __name__ == "__main__":
    load()
    print("Open http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)
