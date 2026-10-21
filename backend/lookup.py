"""Unbekannte Knoten in einer CoreScope-Instanz nachschlagen (z. B. https://live.saarmesh.de) – nur Standardbibliothek.

search() blockiert (HTTP) und läuft deshalb per asyncio.to_thread.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from . import VERSION
from .packets import has_pos

DEFAULT_URL = "https://live.saarmesh.de"
ROLES = {"companion": 1, "repeater": 2, "room": 3, "sensor": 4}
MAX_HITS = 20


def host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc or url


def _ms(s) -> int | None:
    try:
        return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def norm(n: dict, url: str) -> dict | None:
    """Knoten aus CoreScope ins eigene Format; `ext` = Quelle, `extSeen` = dort zuletzt gesehen (ms)."""
    key = str(n.get("public_key") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        return None
    out = {"key": key, "name": str(n.get("name") or "")[:32] or None, "type": ROLES.get(n.get("role"), 0),
           "ext": url, "extSeen": _ms(n.get("last_seen") or n.get("last_heard"))}
    pos = {"lat": n.get("lat"), "lon": n.get("lon")}
    if all(isinstance(v, (int, float)) for v in pos.values()) and has_pos(pos):
        out.update(pos)
    return out


def search(url: str, q: str) -> list:
    """Knoten nach Name oder Schlüssel-Präfix (auch Hop-Hash) suchen."""
    req = urllib.request.Request(url.rstrip("/") + "/api/nodes/search?" + urllib.parse.urlencode({"q": q}),
                                 headers={"Accept": "application/json", "User-Agent": f"meshboard/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read(2_000_000))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(str(getattr(e, "reason", e))) from None
    except ValueError:
        raise RuntimeError("keine gültige Antwort (kein CoreScope?)") from None
    nodes = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(nodes, list):
        raise RuntimeError("keine gültige Antwort (kein CoreScope?)")
    return [x for x in (norm(n, url.rstrip("/")) for n in nodes[:MAX_HITS] if isinstance(n, dict)) if x]
