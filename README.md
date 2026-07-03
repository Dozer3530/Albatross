# ALBATROSS — Sentinel-2 Field Console

A local dashboard that watches your fields from orbit. Upload field boundaries
(GeoPackage, Shapefile, GeoJSON, KML, ...), and every time you open the dashboard
it checks the **Copernicus Data Space Ecosystem** for new Sentinel-2 acquisitions
over your fields. Pick a pass, and it downloads *just your field's pixels*,
computes NDVI + statistics, overlays the result on the map, and lets you download
the imagery (float32 NDVI GeoTIFF, NDVI map PNG, true-color PNG, scene-classification TIFF).

## Quick start

**Windows:** just double-click **`run.bat`**. It installs dependencies on first
run, starts the server, and opens the dashboard in your browser. (You still need
Python 3.11+ installed and your Copernicus credentials — see steps 2 below.)

## Setup (manual)

1. **Install dependencies** (Python 3.11+):

   ```
   pip install -r requirements.txt
   ```

2. **Get Copernicus credentials** (free):
   - Register at [dataspace.copernicus.eu](https://dataspace.copernicus.eu) if you haven't.
   - Go to the [Sentinel Hub dashboard](https://shapps.dataspace.copernicus.eu/dashboard/)
     → **User Settings** → **OAuth clients** → **Create new**.
   - Copy the **Client ID** and **Client Secret** (the secret is shown only once).

3. **Run it**:

   ```
   python app.py
   ```

   Then open <http://127.0.0.1:8137>. On first launch the Uplink Config dialog
   opens — paste your Client ID + Secret and hit *Save & Test Uplink*.
   (You can paste a raw access token instead, but those expire after ~10 minutes;
   the Client ID + Secret renews itself automatically.)

## Using it

- **Upload boundaries** — drag any of these onto the drop zone (or the map):
  `.gpkg`, zipped shapefile (`.zip`), loose shapefile set (`.shp`+`.shx`+`.dbf`+…),
  `.geojson` / `.json`, `.kml`, `.fgb`, `.gml`. Every polygon feature becomes a
  tracked field (multi-layer files are read in full).
- **Scan for passes** — happens automatically on page load; the SCAN button
  re-queries on demand. New acquisitions show an amber **NEW** badge, with
  per-scene cloud cover from the catalog.
- **Acquire & analyze** — downloads the field's pixels at 10 m for that date via
  the Sentinel Hub Process API (clipped to the boundary, ~KBs instead of a ~1 GB
  full scene), computes NDVI, cloud-in-field %, and stats.
- **Overlays** — toggle NDVI / RGB overlays on the satellite basemap; opacity
  slider in the map legend.
- **Timeline** — the NDVI chart tracks the field's mean NDVI across every
  processed pass.
- **Downloads** — per pass: NDVI GeoTIFF (float32, -9999 nodata), NDVI colormap
  PNG, true-color PNG, and the SCL scene-classification TIFF.

## Storage

Everything lives in `data/` next to the app: `dashboard.db` (SQLite: fields,
scenes, credentials) and `data/images/<field>/<date>/` (downloaded rasters).
Delete the folder to reset the app.

## Notes

- NDVI = (B08 − B04) / (B08 + B04) from L2A surface reflectance.
- Cloud-in-field % is computed from the SCL band (classes 3, 8, 9, 10).
- Scene stats exclude cloudy pixels; a pass with 100% cloud will show no NDVI.
- Sentinel-2 revisit is 2–5 days depending on latitude; the first scan looks
  back 60 days.
