"""Spike 0(d): confirm the DuckDB spatial functions that the operators need."""
import duckdb

FUNCS = [
    "ST_GeomFromText", "ST_GeomFromWKB", "ST_AsWKB", "ST_AsGeoJSON", "ST_Touches", "ST_Intersects",
    "ST_Within", "ST_Contains", "ST_Covers", "ST_DWithin", "ST_Distance", "ST_Buffer",
    "ST_Centroid", "ST_Union", "ST_Union_Agg", "ST_Intersection", "ST_Difference",
    "ST_Transform", "ST_ConvexHull", "ST_Envelope", "ST_XMin", "ST_XMax", "ST_YMin",
    "ST_YMax", "ST_MakeEnvelope", "ST_Area", "ST_ShortestLine", "ST_IsValid", "ST_MakeValid",
    "ST_Simplify", "ST_Collect", "ST_Point", "ST_X", "ST_Y", "ST_Distance_Sphere",
]

con = duckdb.connect()
con.execute("INSTALL spatial; LOAD spatial; SET geometry_always_xy = true;")
print("duckdb", duckdb.__version__)
have = {r[0].lower() for r in con.execute("SELECT DISTINCT function_name FROM duckdb_functions()").fetchall()}
for f in FUNCS:
    print(f"{f:22s} {'ok' if f.lower() in have else 'MISSING'}")

# Check buffer in meters through a UTM transform (zone 43N, Bangalore).
row = con.execute("""
    SELECT ST_Area(ST_Buffer(ST_Transform(ST_Point(77.59, 12.97), 'EPSG:4326', 'EPSG:32643'), 2000)) AS area_m2
""").fetchone()
print("buffer 2 km area m2 (expect about 12.566e6):", round(row[0]))
# Axis order check with geometry_always_xy = true (lon, lat).
row = con.execute("""
    SELECT ST_AsText(ST_Transform(ST_Point(77.59, 12.97), 'EPSG:4326', 'EPSG:32643'))
""").fetchone()
print("Bangalore in UTM 43N:", row[0])
