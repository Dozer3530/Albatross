"""Parse uploaded boundary files (GeoPackage, Shapefile, GeoJSON, KML, ...) into fields."""
import warnings
from pathlib import Path

import geopandas as gpd
import shapely
from shapely.geometry import mapping

# Order also expresses preference when several candidate files are uploaded together.
PRIMARY_EXTS = [".gpkg", ".geojson", ".json", ".kml", ".kmz", ".zip", ".shp", ".fgb", ".gml"]
NAME_COLUMNS = [
    "name", "field_name", "fieldname", "field", "label", "title",
    "description", "descriptio", "id", "fid",
]
MAX_VERTICES = 600
SIMPLIFY_TOLERANCES = [0.00002, 0.00005, 0.0001, 0.0005]


def _read_layers(path: Path) -> list:
    """Read every vector layer in a file; returns a list of GeoDataFrames."""
    src = str(path)
    layers = [None]
    try:
        import pyogrio
        listed = [l[0] for l in pyogrio.list_layers(src)]
        if listed:
            layers = listed
    except Exception:
        layers = [None]

    frames = []
    for layer in layers:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                gdf = gpd.read_file(src, layer=layer) if layer else gpd.read_file(src)
        except Exception:
            continue
        if gdf is not None and not gdf.empty:
            frames.append(gdf)
    return frames


def _detect_name_column(gdf) -> str:
    lower = {c.lower(): c for c in gdf.columns if c != gdf.geometry.name}
    for candidate in NAME_COLUMNS:
        if candidate in lower:
            return lower[candidate]
    return ""


def _simplify(geom):
    if shapely.get_coordinates(geom).shape[0] <= MAX_VERTICES:
        return geom
    for tol in SIMPLIFY_TOLERANCES:
        simplified = geom.simplify(tol, preserve_topology=True)
        if shapely.get_coordinates(simplified).shape[0] <= MAX_VERTICES:
            return simplified
    return simplified


def load_fields_from_files(paths: list) -> list:
    """Extract polygon fields from an uploaded batch of files.

    Returns dicts ready for db.insert_field:
    {name, geometry (GeoJSON dict, EPSG:4326), area_ha, source_file}
    """
    primaries = [p for p in paths if p.suffix.lower() in PRIMARY_EXTS]
    if not primaries:
        raise ValueError(
            "No supported boundary file found. Upload a GeoPackage (.gpkg), zipped or "
            "complete Shapefile (.shp + .shx + .dbf), GeoJSON, KML, FlatGeobuf or GML."
        )
    primaries.sort(key=lambda p: PRIMARY_EXTS.index(p.suffix.lower()))

    fields = []
    for path in primaries:
        for gdf in _read_layers(path):
            gdf = gdf[gdf.geometry.notna()]
            gdf = gdf[gdf.geom_type.isin(["Polygon", "MultiPolygon"])]
            if gdf.empty:
                continue
            if gdf.crs is None:
                gdf = gdf.set_crs(4326)
            gdf = gdf.to_crs(4326)
            areas_ha = gdf.geometry.to_crs(6933).area / 10_000.0
            name_col = _detect_name_column(gdf)
            counter = 0
            for idx, row in gdf.iterrows():
                counter += 1
                name = ""
                if name_col and row[name_col] is not None:
                    name = str(row[name_col]).strip()
                if not name:
                    name = path.stem if len(gdf) == 1 else f"{path.stem} {counter}"
                fields.append({
                    "name": name[:60],
                    "geometry": mapping(_simplify(row.geometry)),
                    "area_ha": round(float(areas_ha.loc[idx]), 2),
                    "source_file": path.name,
                })

    if not fields:
        raise ValueError(
            "The uploaded file was readable but contained no polygon features. "
            "Field boundaries must be polygons (points/lines are ignored)."
        )
    return fields
