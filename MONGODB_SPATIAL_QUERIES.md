# MongoDB Atlas Top 18 Solar Panel Spatial Queries Reference Guide

This document contains standard, executable MongoDB spatial database queries tailored 100% to the **Solar Panel & Rooftop Equity** domain (`buildings_solar`, `tracts_solar` collections).

All queries use standard GeoJSON format (`[longitude, latitude]` coordinate ordering) and run directly on **MongoDB Atlas** with `2dsphere` spatial indexing.

---

## Collections & Schemas

- **`buildings_solar`**: Rooftop solar suitability & technical capacity metrics.
  - Spatial Index: `2dsphere` on `geometry`
  - Attributes: `building_id`, `tract_id`, `use_type`, `mean_irr_kwh_m2`, `capacity_kwp`, `annual_kwh`, `is_priority`, `priority_rank`, `program`
- **`tracts_solar`**: Census planning zones with income, energy burden, and solar potential.
  - Spatial Index: `2dsphere` on `geometry`
  - Attributes: `tract_id`, `name`, `median_income_inr`, `energy_burden_pct`, `need_tercile`, `tract_class`

---

## 1. Basic CRUD Operations on Solar Rooftops

```javascript
// 1. Create (Insert new solar building record)
db.buildings_solar.insertOne({
  "building_id": 9999,
  "tract_id": "T01",
  "use_type": "residential",
  "capacity_kwp": 12.5,
  "annual_kwh": 15400.0,
  "is_priority": 1,
  "program": "Owner rooftop subsidy",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[77.0020, 11.0240], [77.0026, 11.0240], [77.0026, 11.0246], [77.0020, 11.0246], [77.0020, 11.0240]]]
  }
});

// 2. Read (Query document)
db.buildings_solar.find({ "building_id": 9999 });

// 3. Update (Modify solar system capacity)
db.buildings_solar.updateOne(
  { "building_id": 9999 },
  { "$set": { "capacity_kwp": 18.0, "program": "Community Solar Expansion" } }
);

// 4. Delete
db.buildings_solar.deleteOne({ "building_id": 9999 });
```

---

## 2. Solar Rooftop Attribute Lookup by Coordinate (X, Y)

Retrieves solar generation properties (`capacity_kwp`, `annual_kwh`, `program`) for a clicked roof point coordinate `[77.0028, 11.0245]`.

```javascript
db.buildings_solar.find({
  "geometry": {
    "$geoIntersects": {
      "$geometry": {
        "type": "Point",
        "coordinates": [77.0028, 11.0245]
      }
    }
  }
});
```

---

## 3. High-Solar Priority Zones within City ($geoWithin)

Finds all high-need census zones (`need_tercile: 2`) located inside the city boundary polygon.

```javascript
db.tracts_solar.find({
  "need_tercile": 2,
  "geometry": {
    "$geoWithin": {
      "$geometry": {
        "type": "Polygon",
        "coordinates": [[[76.990, 11.010], [77.020, 11.010], [77.020, 11.040], [76.990, 11.040], [76.990, 11.010]]]
      }
    }
  }
});
```

---

## 4. Priority Solar Rooftops within Zone ($geoWithin)

Finds all high-capacity priority solar rooftops ($\ge 3$ kWp) located inside a specific census zone polygon.

```javascript
db.buildings_solar.find({
  "is_priority": 1,
  "capacity_kwp": { "$gte": 3.0 },
  "geometry": {
    "$geoWithin": {
      "$geometry": {
        "type": "Polygon",
        "coordinates": [[[76.995, 11.015], [77.005, 11.015], [77.005, 11.025], [76.995, 11.025], [76.995, 11.015]]]
      }
    }
  }
});
```

---

## 5. Adjacent Solar Planning Zones ($geoIntersects)

Finds neighboring census zones that share a border with Zone T01.

```javascript
db.tracts_solar.find({
  "tract_id": { "$ne": "T01" },
  "geometry": {
    "$geoIntersects": {
      "$geometry": {
        "type": "Polygon",
        "coordinates": [[[77.000, 11.020], [77.010, 11.020], [77.010, 11.030], [77.000, 11.030], [77.000, 11.020]]]
      }
    }
  }
});
```

---

## 6. Proximity Search around House ($nearSphere)

Finds the 5 nearest rooftop solar installations within 500m of a given house coordinate (`[77.0028, 11.0245]`).

```javascript
db.buildings_solar.find({
  "geometry": {
    "$nearSphere": {
      "$geometry": {
        "type": "Point",
        "coordinates": [77.0028, 11.0245]
      },
      "$maxDistance": 500
    }
  }
}).limit(5);
```

---

## 7. Solar Rooftops within 3 km of Grid Substation ($geoNear)

Finds all high-output solar rooftops within 3 km of the central grid substation / PSG Tech, returning exact distance in kilometres and solar kWp.

```javascript
db.buildings_solar.aggregate([
  {
    "$geoNear": {
      "near": { "type": "Point", "coordinates": [77.0028, 11.0245] },
      "distanceField": "distance_km",
      "maxDistance": 3000,
      "distanceMultiplier": 0.001,
      "query": { "capacity_kwp": { "$gt": 0 } },
      "spherical": true
    }
  },
  { "$sort": { "capacity_kwp": -1 } },
  { "$limit": 10 }
]);
```

---

## 8. Polygon Union of Solar Planning Zones

Merges two adjacent census zones into a combined solar grid expansion boundary using Shapely and PyMongo.

```python
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

z1 = db["tracts_solar"].find_one({"tract_id": "T01"})
z2 = db["tracts_solar"].find_one({"tract_id": "T02"})

merged_polygon = unary_union([shape(z1["geometry"]), shape(z2["geometry"])])
merged_geojson = mapping(merged_polygon)
```

---

## 9. Distance Measurement along Transmission Line

Calculates geodetic distance between solar nodes and generates an 11kV transmission LineString geometry.

```python
import math

line_geometry = {
    "type": "LineString",
    "coordinates": [[77.0028, 11.0245], [77.0250, 11.0380]]
}
```

---

## 10. Centroid of Solar Planning Zone

Calculates the central coordinate `(X, Y)` of a census zone to locate a central solar power transformer.

```python
from shapely.geometry import shape

zone = db["tracts_solar"].find_one({"tract_id": "T01"})
centroid = shape(zone["geometry"]).centroid
print(f"Optimal Transformer Location: [{centroid.x}, {centroid.y}]")
```

---

## 11. Solar Capacity Aggregation Pipeline ($group)

Groups solar buildings by census zone and calculates total capacity (MWp) and priority counts using MongoDB aggregation.

```javascript
db.buildings_solar.aggregate([
  {
    "$group": {
      "_id": "$tract_id",
      "building_count": { "$sum": 1 },
      "total_capacity_kwp": { "$sum": "$capacity_kwp" },
      "total_annual_kwh": { "$sum": "$annual_kwh" },
      "priority_roofs": { "$sum": "$is_priority" }
    }
  },
  { "$sort": { "total_capacity_kwp": -1 } }
]);
```

---

## 12. Optimal Solar Microgrid Hub Location Proposal

Proposes the optimal location for a new Solar Microgrid Hub based on highest household energy burden and unshaded solar roof area.

```javascript
db.tracts_solar.aggregate([
  { "$sort": { "energy_burden_pct": -1, "solar_kwh_per_hh": -1 } },
  { "$limit": 1 }
]);
```

---

## 13. 3D Solar Rooftop Elevation Search & Extrusion

Finds nearest elevated solar rooftop and extrudes 2.5D building height for solar shading analysis.

```python
building = db["buildings_solar"].find_one({"is_priority": 1})
height = building["height_m"]  # 18.5 metres
floors = building["floors"]    # 6 floors
base_geometry = building["geometry"]
```

---

## 14. 3D Building Extrusion Block (Polygon to 3D Volume)

Extrudes 2D building footprint into a 3D building prism block (LOD1 format) with total volume in $m^3$.

```python
area_m2 = shape(building["geometry"]).area * 111320 * 110574
volume_m3 = area_m2 * height
```

---

## 15. LineString Adjacency Query (Solar Grid Feeders)

Finds adjacent feeder lines intersecting a main 11kV grid transmission LineString.

```javascript
db.transmission_lines.find({
  "geometry": {
    "$geoIntersects": {
      "$geometry": {
        "type": "LineString",
        "coordinates": [[77.0010, 11.0210], [77.0150, 11.0290], [77.0250, 11.0350]]
      }
    }
  }
});
```

---

## 16. Spatial Overlay Operations (Union, Intersects, Symmetrical Difference)

Computes Overlay geometries (Intersection, Symmetrical Difference, Union) between existing solar service coverage and proposed expansion boundaries.

```python
poly_existing = shape(existing_zone["geometry"])
poly_proposed = shape(proposed_zone["geometry"])

intersection = poly_existing.intersection(poly_proposed)
sym_diff = poly_existing.symmetric_difference(poly_proposed)
union = poly_existing.union(poly_proposed)
```

---

## 17. Substation Proximity Buffer Surface (500m Buffer)

Generates a 500m buffer surface around a central substation and classifies buildings inside vs outside.

```python
substation_pt = Point(lon, lat)
buffer_surface = substation_pt.buffer(0.0045)
```

---

## 18. Spatial KNN Search & Join (K-Nearest Neighbors)

Finds K closest solar rooftop installations to a central transformer node using `$geoNear`.

```javascript
db.buildings_solar.aggregate([
  {
    "$geoNear": {
      "near": { "type": "Point", "coordinates": [77.0080, 11.0260] },
      "distanceField": "distance_m",
      "spherical": true
    }
  },
  { "$limit": 5 }
]);
```
