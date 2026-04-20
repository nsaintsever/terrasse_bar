import math
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import geopandas as gpd
import osmnx as ox
from shapely.geometry import Point, LineString
from shapely.strtree import STRtree
import pvlib

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

CITIES = {
    "Paris (Place de Clichy)": {
        "center": (48.8837, 2.3275),
        "radius": 1500,
        "slug": "paris_clichy",
    },
    "Lyon (Bellecour)": {
        "center": (45.7578, 4.8320),
        "radius": 1500,
        "slug": "lyon_bellecour",
    },
    "Marseille (Vieux-Port)": {
        "center": (43.2951, 5.3740),
        "radius": 1500,
        "slug": "marseille_vieuxport",
    },
    "Bordeaux (Pey-Berland)": {
        "center": (44.8378, -0.5792),
        "radius": 1500,
        "slug": "bordeaux_peyberland",
    },
}

DEFAULT_BUILDING_HEIGHT = 12.0  # m, fallback
METERS_CRS = "EPSG:2154"  # Lambert-93, OK pour la France métropolitaine


# ---------- Fetch OSM ----------

def fetch_bars(lat, lon, radius):
    tags = {"amenity": ["bar", "pub", "cafe", "restaurant"]}
    gdf = ox.features_from_point((lat, lon), tags=tags, dist=radius)
    if gdf.empty:
        return gpd.GeoDataFrame(columns=["name", "amenity", "geometry"], geometry="geometry", crs="EPSG:4326")
    # Garder uniquement les points (certains sont des polygones → centroid)
    gdf = gdf.to_crs("EPSG:4326").copy()
    gdf["geometry"] = gdf.geometry.apply(lambda g: g if g.geom_type == "Point" else g.centroid)
    if "name" not in gdf.columns:
        gdf["name"] = None
    return gdf[["name", "amenity", "geometry"]].reset_index(drop=True)


def _parse_height(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    try:
        return float(str(val).replace("m", "").strip())
    except Exception:
        return None


def fetch_buildings(lat, lon, radius):
    tags = {"building": True}
    gdf = ox.features_from_point((lat, lon), tags=tags, dist=radius)
    if gdf.empty:
        return gpd.GeoDataFrame(columns=["height", "geometry"], geometry="geometry", crs="EPSG:4326")
    gdf = gdf.to_crs("EPSG:4326").copy()
    gdf = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])]

    h = None
    if "height" in gdf.columns:
        h = gdf["height"].apply(_parse_height)
    if "building:levels" in gdf.columns:
        levels = pd.to_numeric(gdf["building:levels"], errors="coerce") * 3.0
        h = levels if h is None else h.fillna(levels)
    if h is None:
        h = pd.Series([None] * len(gdf), index=gdf.index)
    gdf["height"] = h.fillna(DEFAULT_BUILDING_HEIGHT)
    return gdf[["height", "geometry"]].reset_index(drop=True)


# ---------- Cache disque ----------

def _bars_path(slug):
    return DATA_DIR / f"{slug}_bars.parquet"


def _buildings_path(slug):
    return DATA_DIR / f"{slug}_buildings.parquet"


def load_or_fetch_bars(lat, lon, radius, slug):
    path = _bars_path(slug)
    if path.exists():
        return gpd.read_parquet(path)
    gdf = fetch_bars(lat, lon, radius)
    if not gdf.empty:
        gdf.to_parquet(path)
    return gdf


def load_or_fetch_buildings(lat, lon, radius, slug):
    path = _buildings_path(slug)
    if path.exists():
        return gpd.read_parquet(path)
    gdf = fetch_buildings(lat, lon, radius)
    if not gdf.empty:
        gdf.to_parquet(path)
    return gdf


# ---------- Soleil ----------

def solar_position(lat, lon, dt):
    times = pd.DatetimeIndex([dt])
    sp = pvlib.solarposition.get_solarposition(times, lat, lon)
    return {
        "elevation": float(sp["elevation"].iloc[0]),
        "azimuth": float(sp["azimuth"].iloc[0]),  # 0=N, 90=E, 180=S, 270=W
    }


# ---------- Ombres ----------

def is_sunlit(bar_pt_m, buildings_m, tree, geoms_list, azimuth_deg, elevation_deg, max_dist=200.0):
    """Lance un rayon du bar vers le soleil; si un bâtiment assez haut le croise, ombre."""
    if elevation_deg <= 0:
        return False

    # Direction vers le soleil (azimut 0=N, sens horaire)
    az_rad = math.radians(azimuth_deg)
    dx = math.sin(az_rad)
    dy = math.cos(az_rad)

    end_x = bar_pt_m.x + dx * max_dist
    end_y = bar_pt_m.y + dy * max_dist
    ray = LineString([(bar_pt_m.x, bar_pt_m.y), (end_x, end_y)])

    tan_elev = math.tan(math.radians(elevation_deg))

    candidate_idxs = tree.query(ray)
    for idx in candidate_idxs:
        geom = geoms_list[idx]
        if not geom.intersects(ray):
            continue
        inter = geom.intersection(ray)
        # distance min du bar au bâtiment le long du rayon
        d = bar_pt_m.distance(geom)
        if d < 0.1:
            continue  # le bar est collé/dans le bâtiment, on ignore
        building_height = float(buildings_m.iloc[idx]["height"])
        # Hauteur d'ombre projetée à la distance d
        shadow_height_needed = d * tan_elev
        if building_height > shadow_height_needed:
            return False
    return True


def get_bars_sunlight_status(lat, lon, radius, dt, slug=None):
    sun = solar_position(lat, lon, dt)

    if slug:
        bars = load_or_fetch_bars(lat, lon, radius, slug)
        buildings = load_or_fetch_buildings(lat, lon, radius, slug)
    else:
        bars = fetch_bars(lat, lon, radius)
        buildings = fetch_buildings(lat, lon, radius)

    if bars.empty:
        return pd.DataFrame(columns=["name", "amenity", "lat", "lon", "sunlit"]), sun

    bars_m = bars.to_crs(METERS_CRS).reset_index(drop=True)

    if buildings.empty or sun["elevation"] <= 0:
        bars_out = bars.copy()
        bars_out["lat"] = bars.geometry.y
        bars_out["lon"] = bars.geometry.x
        bars_out["sunlit"] = sun["elevation"] > 0 and buildings.empty
        return bars_out[["name", "amenity", "lat", "lon", "sunlit"]].reset_index(drop=True), sun

    buildings_m = buildings.to_crs(METERS_CRS).reset_index(drop=True)
    geoms_list = list(buildings_m.geometry.values)
    tree = STRtree(geoms_list)

    sunlit_list = [
        is_sunlit(pt, buildings_m, tree, geoms_list, sun["azimuth"], sun["elevation"])
        for pt in bars_m.geometry
    ]

    bars_out = bars.copy()
    bars_out["lat"] = bars.geometry.y
    bars_out["lon"] = bars.geometry.x
    bars_out["sunlit"] = sunlit_list
    return bars_out[["name", "amenity", "lat", "lon", "sunlit"]].reset_index(drop=True), sun
