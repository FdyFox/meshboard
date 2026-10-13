"""Start: python -m backend [Node] [--port 8080] [--bind 127.0.0.1] [--data ./data]

Node:  tcp:192.168.1.50[:5000] | serial:/dev/ttyUSB0 | ble:AA:BB:CC:DD:EE:FF | 192.168.1.50[:5000]
Alternativ per Umgebungsvariablen: MESHCORE_TARGET oder MESHCORE_HOST/MESHCORE_PORT,
MESHCORE_SERIAL, MESHCORE_BLE; außerdem PORT, BIND, DATA_DIR, PACKET_DAYS.
Ohne Node startet der Server trotzdem – die Verbindung lässt sich dann im Browser einrichten.
"""
import argparse
import logging
import os
import sys
from pathlib import Path

import uvicorn

from . import VERSION
from .api import create_app
from .mesh import parse_target


def env_target() -> str:
    env = os.environ.get
    if env("MESHCORE_TARGET"):
        return env("MESHCORE_TARGET")
    if env("MESHCORE_HOST"):
        host = env("MESHCORE_HOST")
        return f"tcp:{host}" if ":" in host else f"tcp:{host}:{env('MESHCORE_PORT', '5000')}"
    if env("MESHCORE_SERIAL"):
        return "serial:" + env("MESHCORE_SERIAL")
    if env("MESHCORE_BLE"):
        return "ble:" + env("MESHCORE_BLE")
    return ""


def main():
    env = os.environ.get
    ap = argparse.ArgumentParser(prog="python -m backend", description="Meshboard – Station für MeshCore-Companions")
    ap.add_argument("node", nargs="?", default=env_target(),
                    help="Node, z. B. 192.168.1.50:5000, serial:/dev/ttyUSB0 oder ble:AA:BB:…")
    ap.add_argument("--port", type=int, default=int(env("PORT", "8080")), help="HTTP-Port (Standard 8080)")
    ap.add_argument("--bind", default=env("BIND", "127.0.0.1"), help="Bind-Adresse (Standard 127.0.0.1)")
    ap.add_argument("--data", default=env("DATA_DIR", "data"), help="Datenverzeichnis (Standard ./data)")
    ap.add_argument("--days", type=int, default=int(env("PACKET_DAYS", "365")),
                    help="Paketverlauf für die Statistik so viele Tage aufbewahren (Standard 365)")
    ap.add_argument("--debug", action="store_true", help="ausführliches Logging")
    ap.add_argument("--version", action="version", version=f"meshboard {VERSION}")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.debug else logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if not a.debug:
        logging.getLogger("meshcore").setLevel(logging.WARNING)
    data = Path(a.data)
    try:
        data.mkdir(parents=True, exist_ok=True)
        (data / ".schreibtest").touch()
        (data / ".schreibtest").unlink()
    except OSError as e:
        sys.exit(f"Datenverzeichnis {data.resolve()} nicht beschreibbar ({e.strerror}). "
                 f"Läuft der Server als Benutzer {os.getuid()}? Docker-Bind-Mount: Ordner mit 'sudo chown {os.getuid()} <ordner>' freigeben.")
    target = parse_target(a.node)
    shown = "localhost" if a.bind in ("127.0.0.1", "0.0.0.0") else a.bind
    print(f"Meshboard {VERSION}: http://{shown}:{a.port}  (Node {a.node or 'nicht konfiguriert'})", flush=True)
    uvicorn.run(create_app(target, data, max(1, a.days)), host=a.bind, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
