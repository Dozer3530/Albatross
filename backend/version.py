"""App version + a lightweight GitHub update check.

The check compares APP_VERSION against the latest published GitHub Release tag.
Cut a new release with a bumped tag (e.g. v1.1.0) and bump APP_VERSION to match,
and every running copy will notice on next startup.
"""
import time

import requests

APP_VERSION = "1.2.0"
REPO = "Dozer3530/Albatross"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
REPO_URL = f"https://github.com/{REPO}"

_CACHE_TTL = 3600  # re-check GitHub at most once an hour
_cache = {"at": 0.0, "result": None}


def _parse(tag: str) -> tuple:
    """'v1.2.3' -> (1, 2, 3); tolerant of junk so a bad tag never crashes."""
    nums = []
    for part in tag.lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        nums.append(int(digits) if digits else 0)
    return tuple(nums) or (0,)


def check_for_update(force: bool = False) -> dict:
    """Return {current, latest, update_available, url, checked, error?}.

    Never raises: any network/parse problem returns update_available=False so
    startup is never blocked or noisy when offline.
    """
    now = time.time()
    if not force and _cache["result"] and now - _cache["at"] < _CACHE_TTL:
        return _cache["result"]

    result = {
        "current": APP_VERSION,
        "latest": None,
        "update_available": False,
        "url": REPO_URL,
        "checked": True,
    }
    try:
        resp = requests.get(
            RELEASES_API,
            headers={"Accept": "application/vnd.github+json"},
            timeout=4,
        )
        if resp.status_code == 200:
            data = resp.json()
            tag = (data.get("tag_name") or "").strip()
            if tag:
                result["latest"] = tag.lstrip("vV")
                result["url"] = data.get("html_url") or REPO_URL
                result["update_available"] = _parse(tag) > _parse(APP_VERSION)
        elif resp.status_code == 404:
            # no releases published yet — nothing to update to, not an error
            pass
        else:
            result["error"] = f"GitHub returned {resp.status_code}"
    except requests.RequestException as exc:
        result["error"] = str(exc)
        result["checked"] = False

    _cache.update(at=now, result=result)
    return result
