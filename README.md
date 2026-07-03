# ALBATROSS — Sentinel-2 Field Console

A local dashboard that watches your fields from orbit. Upload field boundaries
(GeoPackage, Shapefile, GeoJSON, KML, ...), and every time you open the dashboard
it checks the **Copernicus Data Space Ecosystem** for new Sentinel-2 acquisitions
over your fields. Pick a pass, and it downloads *just your field's pixels*,
computes NDVI + statistics, overlays the result on the map, and lets you download
the imagery (float32 NDVI GeoTIFF, NDVI map PNG, true-color PNG, scene-classification TIFF).

## Get it running (Windows — the easy way)

You need two things once: **Python** and a **free Copernicus account**.

1. **Install Python 3.11+** — get it from [python.org/downloads](https://www.python.org/downloads/).
   On the first installer screen, **tick "Add Python to PATH"**, then click Install.

2. **Download Albatross** — on the [GitHub page](https://github.com/Dozer3530/Albatross),
   grab the latest [**Release**](https://github.com/Dozer3530/Albatross/releases/latest)
   (the `Source code (zip)`), or click the green **Code ▾ → Download ZIP** button.

3. **Extract the ZIP first — this step is required.** Right-click the downloaded
   `.zip` → **Extract All…** → **Extract**. Then open the extracted folder.
   ⚠️ **Do not double-click `run.bat` while still inside the ZIP preview** — Windows
   only unpacks that one file to a temp folder, so it can't find the rest of the app
   and you'll get a *"could not open requirements file"* error.

4. **Double-click `run.bat`** in the extracted folder. The first launch installs
   everything it needs (a minute or two), then opens the dashboard in your browser
   at <http://127.0.0.1:8137>. Every launch after that is instant. Close the black
   console window (or press Ctrl+C in it) to stop the server.

5. **Connect your account** — the first time, the *Uplink Config* dialog opens.
   Paste your Copernicus **Client ID + Secret** (see below) and hit
   *Save & Test Uplink*. That's it — your fields and imagery are stored locally on
   your own machine.

> **Staying up to date:** Albatross checks GitHub for a newer version each time it
> starts. If one exists, a pink **UPDATE** tag appears in the top bar — click it to
> download the new release. (If you cloned with `git`, `run.bat` pulls the update
> for you automatically.)

## Setup (manual / macOS / Linux)

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
  per-scene cloud cover from the catalog. Use the **lookback dropdown** next to
  SCAN (6 months / 1 year / 2 years / 5 years / all) to pull in older passes
  from the archive.
- **Acquire & analyze** — downloads the field's pixels at 10 m for that date via
  the Sentinel Hub Process API (clipped to the boundary, ~KBs instead of a ~1 GB
  full scene), computes NDVI, cloud-in-field %, and stats.
- **Overlays** — toggle NDVI / RGB overlays on the satellite basemap; opacity
  slider in the map legend.
- **Timeline** — the NDVI chart tracks the field's mean NDVI across every
  processed pass. Each processed pass has an **IN NDVI TREND** toggle — click it
  to drop a cloudy or off outlier from the trend line (the image itself is kept,
  just excluded from the graph), and click again to add it back.
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
