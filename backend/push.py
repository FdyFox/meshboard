"""Push-Benachrichtigungen an ntfy, Telegram oder einen eigenen Webhook – nur Standardbibliothek.

send() blockiert (HTTP) und läuft deshalb per asyncio.to_thread.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

TYPES = ("", "ntfy", "telegram", "webhook")


def _post(url: str, body: dict, headers: dict | None = None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}") from None
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(str(getattr(e, "reason", e))) from None


def send(cfg: dict, title: str, text: str, kind: str, extra: dict | None = None):
    """cfg: {type, url, chat, token}. kind: dm, mention, chan, watch, test."""
    t = cfg.get("type")
    if t == "ntfy":
        # JSON-Veröffentlichung an die Basis-URL: Titel und Text dürfen Umlaute und Emojis enthalten
        u = urllib.parse.urlsplit(cfg["url"])
        topic = u.path.strip("/")
        base = urllib.parse.urlunsplit((u.scheme, u.netloc, "", "", ""))
        tags = {"dm": ["speech_balloon"], "mention": ["bell"], "chan": ["speech_balloon"], "watch": ["eye"]}.get(kind, [])
        _post(base, {"topic": topic, "title": title, "message": text, "tags": tags,
                     "priority": 4 if kind in ("dm", "mention", "watch") else 3},
              {"Authorization": "Bearer " + cfg["token"]} if cfg.get("token") else None)
    elif t == "telegram":
        _post(f"https://api.telegram.org/bot{cfg['token']}/sendMessage", {"chat_id": cfg["chat"], "text": f"{title}\n{text}"})
    elif t == "webhook":
        _post(cfg["url"], {"kind": kind, "title": title, "text": text, **(extra or {})},
              {"Authorization": "Bearer " + cfg["token"]} if cfg.get("token") else None)
