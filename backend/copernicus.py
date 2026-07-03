"""Client for the Copernicus Data Space Ecosystem (Sentinel Hub APIs).

Auth:    https://identity.dataspace.copernicus.eu  (OAuth2 client credentials)
Catalog: https://sh.dataspace.copernicus.eu/api/v1/catalog  (STAC search)
Process: https://sh.dataspace.copernicus.eu/api/v1/process  (pixel extraction)
"""
import io
import tarfile
import time
from pathlib import Path

import requests

from . import db

AUTH_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SH_BASE = "https://sh.dataspace.copernicus.eu"
CATALOG_URL = f"{SH_BASE}/api/v1/catalog/1.0.0/search"
PROCESS_URL = f"{SH_BASE}/api/v1/process"
COLLECTION = "sentinel-2-l2a"


class CopernicusError(Exception):
    """User-facing error talking to Copernicus."""


_token_cache = {"token": None, "expires_at": 0.0, "key": None}


def has_credentials(settings=None) -> bool:
    s = settings if settings is not None else db.get_settings()
    return bool((s.get("client_id") and s.get("client_secret")) or s.get("access_token"))


def get_access_token(force: bool = False) -> str:
    s = db.get_settings()
    client_id = (s.get("client_id") or "").strip()
    client_secret = (s.get("client_secret") or "").strip()

    if client_id and client_secret:
        cache_key = f"{client_id}:{client_secret}"
        if (not force and _token_cache["token"] and _token_cache["key"] == cache_key
                and time.time() < _token_cache["expires_at"]):
            return _token_cache["token"]
        try:
            resp = requests.post(
                AUTH_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise CopernicusError(f"Could not reach the Copernicus identity service: {exc}")
        if resp.status_code != 200:
            try:
                body = resp.json()
                detail = body.get("error_description") or body.get("error") or ""
            except ValueError:
                detail = resp.text[:200]
            raise CopernicusError(
                f"Authentication failed ({resp.status_code}): "
                f"{detail or 'check your Client ID and Client Secret'}"
            )
        payload = resp.json()
        _token_cache.update(
            token=payload["access_token"],
            expires_at=time.time() + int(payload.get("expires_in", 600)) - 60,
            key=cache_key,
        )
        return _token_cache["token"]

    token = (s.get("access_token") or "").strip()
    if token:
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        return token

    raise CopernicusError(
        "No Copernicus credentials configured. Open Uplink Config and enter your "
        "OAuth Client ID + Secret (or paste an access token)."
    )


def _request(method: str, url: str, **kwargs) -> requests.Response:
    timeout = kwargs.pop("timeout", 120)
    base_headers = kwargs.pop("headers", {}) or {}
    resp = None
    for attempt in (1, 2):
        token = get_access_token(force=(attempt == 2))
        headers = dict(base_headers)
        headers["Authorization"] = f"Bearer {token}"
        try:
            resp = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            raise CopernicusError(f"Copernicus request failed: {exc}")
        if resp.status_code != 401:
            break
    if resp.status_code == 401:
        raise CopernicusError(
            "Copernicus rejected the credentials (401). If you pasted a raw access token "
            "it has likely expired (they last ~10 minutes) — a Client ID + Secret renews "
            "itself automatically."
        )
    if resp.status_code == 403:
        raise CopernicusError(
            "Access denied (403). The account may lack Sentinel Hub API access or its "
            "monthly quota is exhausted."
        )
    if resp.status_code >= 400:
        try:
            detail = str(resp.json())
        except ValueError:
            detail = resp.text
        raise CopernicusError(f"Copernicus API error {resp.status_code}: {detail[:300]}")
    return resp


# ------------------------------------------------------------------ catalog

def search_scenes(geometry: dict, date_from: str, date_to: str) -> list:
    """STAC search for Sentinel-2 L2A acquisitions intersecting the field."""
    features = []
    next_token = None
    for _ in range(10):  # pagination safety cap
        payload = {
            "collections": [COLLECTION],
            "intersects": geometry,
            "datetime": f"{date_from}T00:00:00Z/{date_to}T23:59:59Z",
            "limit": 100,
            "fields": {
                "include": ["id", "properties.datetime", "properties.eo:cloud_cover"],
                "exclude": ["geometry", "assets", "links", "bbox"],
            },
        }
        if next_token is not None:
            payload["next"] = next_token
        body = _request("POST", CATALOG_URL, json=payload, timeout=60).json()
        features.extend(body.get("features", []))
        next_token = (body.get("context") or {}).get("next")
        if next_token is None:
            break

    scenes = []
    for feat in features:
        props = feat.get("properties", {})
        scenes.append({
            "id": feat.get("id"),
            "datetime": props.get("datetime"),
            "cloud_cover": props.get("eo:cloud_cover"),
        })
    return scenes


def group_by_date(items: list) -> dict:
    """Collapse per-tile catalog items into one entry per acquisition date."""
    groups = {}
    for item in items:
        dt = item.get("datetime") or ""
        date = dt[:10]
        if not date:
            continue
        group = groups.setdefault(date, {
            "date": date,
            "datetime_str": dt,
            "cloud_cover": item.get("cloud_cover"),
            "tile_ids": [],
        })
        group["tile_ids"].append(item.get("id"))
        cc = item.get("cloud_cover")
        if cc is not None and (group["cloud_cover"] is None or cc < group["cloud_cover"]):
            group["cloud_cover"] = cc
    return groups


# ------------------------------------------------------------------ process

# Four outputs in one request: display PNGs, raw float NDVI, and the scene
# classification (SCL) band for cloud statistics. Pixels outside the field
# polygon have dataMask 0 -> transparent / nodata.
EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B02", "B03", "B04", "B08", "SCL", "dataMask"] }],
    output: [
      { id: "truecolor", bands: 4, sampleType: "UINT8" },
      { id: "ndvi_vis", bands: 4, sampleType: "UINT8" },
      { id: "ndvi_raw", bands: 1, sampleType: "FLOAT32" },
      { id: "scl", bands: 1, sampleType: "UINT8" }
    ]
  };
}

var RAMP_POS = [-0.5, 0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9];
var RAMP_COL = [
  [64, 78, 90],
  [173, 129, 96],
  [214, 178, 102],
  [227, 223, 112],
  [158, 199, 84],
  [95, 168, 62],
  [42, 126, 45],
  [14, 84, 34]
];

function rampColor(v) {
  if (v <= RAMP_POS[0]) return RAMP_COL[0];
  for (var i = 1; i < RAMP_POS.length; i++) {
    if (v <= RAMP_POS[i]) {
      var t = (v - RAMP_POS[i - 1]) / (RAMP_POS[i] - RAMP_POS[i - 1]);
      var c0 = RAMP_COL[i - 1];
      var c1 = RAMP_COL[i];
      return [
        Math.round(c0[0] + (c1[0] - c0[0]) * t),
        Math.round(c0[1] + (c1[1] - c0[1]) * t),
        Math.round(c0[2] + (c1[2] - c0[2]) * t)
      ];
    }
  }
  return RAMP_COL[RAMP_COL.length - 1];
}

function toByte(v) {
  return Math.max(0, Math.min(255, Math.round(v * 255)));
}

function evaluatePixel(s) {
  var alpha = s.dataMask === 1 ? 255 : 0;
  var denom = s.B08 + s.B04;
  var ndvi = denom > 0 ? (s.B08 - s.B04) / denom : 0;
  var c = rampColor(ndvi);
  return {
    truecolor: [toByte(2.5 * s.B04), toByte(2.5 * s.B03), toByte(2.5 * s.B02), alpha],
    ndvi_vis: [c[0], c[1], c[2], alpha],
    ndvi_raw: [s.dataMask === 1 ? ndvi : -9999],
    scl: [s.dataMask === 1 ? s.SCL : 0]
  };
}
"""

EXPECTED_OUTPUTS = {"truecolor.png", "ndvi_vis.png", "ndvi_raw.tif", "scl.tif"}


def process_scene(geometry: dict, date: str, width: int, height: int) -> dict:
    """Fetch clipped field pixels for one acquisition date. Returns {filename: bytes}."""
    request_body = {
        "input": {
            "bounds": {
                "geometry": geometry,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [{
                "type": COLLECTION,
                "dataFilter": {
                    "timeRange": {
                        "from": f"{date}T00:00:00Z",
                        "to": f"{date}T23:59:59Z",
                    },
                    "mosaickingOrder": "leastCC",
                },
            }],
        },
        "output": {
            "width": width,
            "height": height,
            "responses": [
                {"identifier": "truecolor", "format": {"type": "image/png"}},
                {"identifier": "ndvi_vis", "format": {"type": "image/png"}},
                {"identifier": "ndvi_raw", "format": {"type": "image/tiff"}},
                {"identifier": "scl", "format": {"type": "image/tiff"}},
            ],
        },
        "evalscript": EVALSCRIPT,
    }
    resp = _request(
        "POST", PROCESS_URL,
        json=request_body,
        headers={"Accept": "application/tar"},
        timeout=180,
    )

    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(resp.content)) as tar:
            for member in tar.getmembers():
                handle = tar.extractfile(member)
                if handle:
                    files[Path(member.name).name] = handle.read()
    except tarfile.TarError as exc:
        raise CopernicusError(f"Could not unpack the Copernicus response: {exc}")

    missing = EXPECTED_OUTPUTS - set(files)
    if missing:
        raise CopernicusError(
            f"Copernicus response was missing outputs: {', '.join(sorted(missing))}"
        )
    return files


def test_connection() -> tuple:
    """Validate credentials with a minimal catalog query. Returns (ok, message)."""
    probe = {
        "type": "Polygon",
        "coordinates": [[
            [13.35, 52.50], [13.36, 52.50], [13.36, 52.51],
            [13.35, 52.51], [13.35, 52.50],
        ]],
    }
    try:
        payload = {
            "collections": [COLLECTION],
            "intersects": probe,
            "datetime": "2024-01-01T00:00:00Z/2024-01-31T23:59:59Z",
            "limit": 1,
        }
        _request("POST", CATALOG_URL, json=payload, timeout=30)
        return True, "Uplink established — Sentinel Hub catalog reachable."
    except CopernicusError as exc:
        return False, str(exc)
