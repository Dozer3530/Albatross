"""Turn a catalog scene into stored imagery + NDVI statistics."""
import io
import math

import numpy as np
import tifffile
from shapely.geometry import shape

from . import copernicus, db

RESOLUTION_M = 10.0          # Sentinel-2 native resolution for the bands we use
MAX_DIMENSION = 2500         # Process API hard limit
# Scene classification (SCL) classes counted as cloud contamination:
# 3 = cloud shadow, 8 = cloud medium prob., 9 = cloud high prob., 10 = thin cirrus
CLOUD_CLASSES = [3, 8, 9, 10]


def compute_dimensions(geometry: dict) -> tuple:
    """Output size in pixels so one pixel ~= 10 m at the field's latitude."""
    minx, miny, maxx, maxy = shape(geometry).bounds
    mid_lat = math.radians((miny + maxy) / 2.0)
    width_m = (maxx - minx) * 111_320.0 * math.cos(mid_lat)
    height_m = (maxy - miny) * 110_540.0
    width = int(max(8, min(MAX_DIMENSION, math.ceil(width_m / RESOLUTION_M))))
    height = int(max(8, min(MAX_DIMENSION, math.ceil(height_m / RESOLUTION_M))))
    return width, height


def analyze(field: dict, scene: dict) -> dict:
    """Download clipped pixels for the scene, store artifacts, compute stats."""
    geometry = field["geometry"]
    width, height = compute_dimensions(geometry)
    files = copernicus.process_scene(geometry, scene["date"], width, height)

    out_dir = db.IMAGES_DIR / str(field["id"]) / scene["date"]
    out_dir.mkdir(parents=True, exist_ok=True)
    for filename, blob in files.items():
        (out_dir / filename).write_bytes(blob)

    stats = _ndvi_stats(files["ndvi_raw.tif"], files["scl.tif"])
    return {"dir": str(out_dir), **stats}


def _ndvi_stats(ndvi_bytes: bytes, scl_bytes: bytes) -> dict:
    ndvi = np.asarray(tifffile.imread(io.BytesIO(ndvi_bytes)), dtype="float64").squeeze()
    scl = np.asarray(tifffile.imread(io.BytesIO(scl_bytes))).squeeze()

    valid = (scl > 0) & (ndvi > -2.0)          # inside the polygon, real data
    cloudy = valid & np.isin(scl, CLOUD_CLASSES)
    clear = valid & ~cloudy

    result = {
        "ndvi_mean": None, "ndvi_min": None, "ndvi_max": None, "ndvi_std": None,
        "clear_pct": None, "cloud_pct": None,
    }
    valid_count = int(valid.sum())
    if valid_count == 0:
        return result

    result["cloud_pct"] = round(100.0 * float(cloudy.sum()) / valid_count, 1)
    result["clear_pct"] = round(100.0 * float(clear.sum()) / valid_count, 1)

    if clear.any():
        values = ndvi[clear]
        result["ndvi_mean"] = round(float(values.mean()), 4)
        result["ndvi_min"] = round(float(values.min()), 4)
        result["ndvi_max"] = round(float(values.max()), 4)
        result["ndvi_std"] = round(float(values.std()), 4)
    return result
