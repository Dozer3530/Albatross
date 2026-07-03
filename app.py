"""Albatross — Sentinel-2 field monitoring dashboard (FastAPI backend)."""
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import copernicus, db, geo, processing, version

app = FastAPI(title="Albatross", version=version.APP_VERSION,
              docs_url="/api/docs", openapi_url="/api/openapi.json")
db.init_db()

STATIC_DIR = Path(__file__).resolve().parent / "static"
FIRST_CHECK_LOOKBACK_DAYS = 60
RECHECK_OVERLAP_DAYS = 3

FILE_KINDS = {
    "ndvi": ("ndvi_vis.png", "image/png", ".png"),
    "truecolor": ("truecolor.png", "image/png", ".png"),
    "ndvi_raw": ("ndvi_raw.tif", "image/tiff", ".tif"),
    "scl": ("scl.tif", "image/tiff", ".tif"),
}


class SettingsIn(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    access_token: Optional[str] = None
    clear: bool = False


# ----------------------------------------------------------------- version

@app.get("/api/version")
def get_version():
    return {"version": version.APP_VERSION}


@app.get("/api/update-check")
def update_check(force: bool = False):
    return version.check_for_update(force=force)


# ---------------------------------------------------------------- settings

@app.get("/api/settings")
def get_settings():
    s = db.get_settings()
    return {
        "client_id": s.get("client_id", ""),
        "has_client_secret": bool(s.get("client_secret")),
        "has_access_token": bool(s.get("access_token")),
        "configured": copernicus.has_credentials(s),
    }


@app.post("/api/settings")
def save_settings(body: SettingsIn):
    if body.clear:
        db.clear_settings()
        return {"ok": True, "configured": False, "message": "Credentials cleared."}

    updates = {}
    if body.client_id is not None:
        updates["client_id"] = body.client_id.strip()
    if body.client_secret:  # empty secret means "keep the stored one"
        updates["client_secret"] = body.client_secret.strip()
    if body.access_token is not None:
        updates["access_token"] = body.access_token.strip()
    db.save_settings(updates)

    if not copernicus.has_credentials():
        return {"ok": False, "configured": False,
                "message": "Enter a Client ID + Secret, or an access token."}
    ok, message = copernicus.test_connection()
    return {"ok": ok, "configured": True, "message": message}


# ------------------------------------------------------------------ fields

@app.get("/api/fields")
def list_fields():
    return {"fields": db.list_fields()}


@app.post("/api/fields/upload")
async def upload_fields(files: List[UploadFile] = File(...)):
    tmp_dir = Path(tempfile.mkdtemp(prefix="upload_"))
    try:
        paths = []
        for upload in files:
            name = Path(upload.filename or "upload.bin").name
            destination = tmp_dir / name
            destination.write_bytes(await upload.read())
            paths.append(destination)
        try:
            parsed = geo.load_fields_from_files(paths)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        created = [db.insert_field(**field) for field in parsed]
        return {"fields": created}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.delete("/api/fields/{field_id}")
def delete_field(field_id: int):
    field = db.get_field(field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    db.delete_field(field_id)
    shutil.rmtree(db.IMAGES_DIR / str(field_id), ignore_errors=True)
    return {"ok": True}


@app.post("/api/fields/{field_id}/seen")
def mark_seen(field_id: int):
    db.mark_scenes_seen(field_id)
    return {"ok": True}


# ------------------------------------------------------- scene discovery

def _check_field(field: dict) -> int:
    """Search the catalog for acquisitions over this field; returns # new."""
    today = datetime.now(timezone.utc).date()
    if field.get("last_checked"):
        last = datetime.strptime(field["last_checked"][:10], "%Y-%m-%d").date()
        date_from = last - timedelta(days=RECHECK_OVERLAP_DAYS)
    else:
        date_from = today - timedelta(days=FIRST_CHECK_LOOKBACK_DAYS)

    items = copernicus.search_scenes(
        field["geometry"], date_from.isoformat(), today.isoformat()
    )
    groups = copernicus.group_by_date(items)
    new_count = 0
    for group in groups.values():
        if db.upsert_scene(
            field_id=field["id"],
            date=group["date"],
            datetime_str=group["datetime_str"],
            cloud_cover=group["cloud_cover"],
            tile_ids=group["tile_ids"],
        ):
            new_count += 1
    db.touch_field_checked(field["id"])
    return new_count


@app.post("/api/fields/{field_id}/check")
def check_field(field_id: int):
    field = db.get_field(field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    try:
        new_count = _check_field(field)
    except copernicus.CopernicusError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"field_id": field_id, "new": new_count, "scenes": db.list_scenes(field_id)}


@app.post("/api/check-all")
def check_all():
    fields = db.list_fields()
    results = []
    try:
        for field in fields:
            results.append({"field_id": field["id"], "new": _check_field(field)})
    except copernicus.CopernicusError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"results": results, "total_new": sum(r["new"] for r in results)}


@app.get("/api/fields/{field_id}/scenes")
def field_scenes(field_id: int):
    if not db.get_field(field_id):
        raise HTTPException(status_code=404, detail="Field not found")
    return {"scenes": db.list_scenes(field_id)}


@app.get("/api/fields/{field_id}/timeseries")
def field_timeseries(field_id: int):
    return {"points": db.timeseries(field_id)}


# ------------------------------------------------------------- processing

@app.post("/api/scenes/{scene_id}/process")
def process_scene(scene_id: int):
    scene = db.get_scene(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    field = db.get_field(scene["field_id"])
    try:
        result = processing.analyze(field, scene)
    except copernicus.CopernicusError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.update_scene_processed(scene_id, result)
    return {"scene": db.get_scene(scene_id)}


@app.get("/api/scenes/{scene_id}/files/{kind}")
def scene_file(scene_id: int, kind: str, download: bool = False):
    if kind not in FILE_KINDS:
        raise HTTPException(status_code=404, detail="Unknown file kind")
    scene = db.get_scene(scene_id)
    if not scene or not scene.get("dir"):
        raise HTTPException(status_code=404, detail="Scene has not been processed yet")
    filename, media_type, ext = FILE_KINDS[kind]
    path = Path(scene["dir"]) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    if download:
        field = db.get_field(scene["field_id"]) or {"name": "field"}
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", field["name"]).strip("_") or "field"
        return FileResponse(path, media_type=media_type,
                            filename=f"{slug}_{scene['date']}_{kind}{ext}")
    return FileResponse(path, media_type=media_type)


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8137)
