# AGENTS.md

Hinweise für KI-Coding-Agents (Claude Code, Codex, Cursor, …) zur Arbeit in diesem Repository.

## Projekt

**Meshboard** – Web-App zur Steuerung von MeshCore-Companions (inoffizielles Community-Projekt). Das Backend (Python, FastAPI) verbindet sich mit der Node per TCP/WiFi, USB (seriell) oder BLE. Das Frontend im Browser zeigt nur an und schickt Befehle an das Backend.

Sprache: UI-Texte, Fehlermeldungen, Kommentare, Commit-Messages und README auf **Deutsch**.

## Struktur

| Pfad | Inhalt |
|---|---|
| `backend/mesh.py` | Klasse `Mesh`: Verbindung über die Bibliothek `meshcore`, gesamter Zustand (Kontakte, Knoten, Kanäle, Pakete, Nachrichten, Nachbarn, Statistik), Chat-Logik (ACKs, Region pro Kanal), Auto-Reconnect, Protokoll-Log |
| `backend/packets.py` | Funkpakete aus dem RX-Log zerlegen (`parse_packet`), Region per HMAC-Transport-Code erkennen |
| `backend/discovery.py` | Hashtag-Räume: `RoomIndex` (Kanal-Hash → Kandidaten, MAC-Prüfung), `decrypt` (AES-128-ECB), `guess_region` (Regions-Code gegen Namensliste) |
| `backend/candidates.py` | Namenslisten für Regionen und Räume (klein, ohne `#`) |
| `backend/store.py` | SQLite (stdlib `sqlite3`): Knoten, Nachrichten (pro Gerät, max. 500 pro Unterhaltung), Einstellungen, Paketverlauf (`packets`, Aufbewahrung `PACKET_DAYS`) samt Statistik-Abfragen (`packet_stats`) |
| `backend/api.py` | FastAPI: REST unter `/api/…`, WebSocket `/api/ws`, statische Auslieferung von `frontend/` |
| `backend/__main__.py` | Start mit `python -m backend [node]`, Konfiguration über CLI und Umgebungsvariablen |
| `frontend/index.html`, `css/app.css` | Oberfläche |
| `frontend/js/` | ES-Module ohne Build: `main.js` (Events→Zustand, Verdrahtung), `state.js` (Client-Zustand `S`, Render-Steuerung, `actions`), `api.js` (REST/WebSocket), `util.js`, je ein Modul pro Tab (`live`, `stats`, `chat`, `map`, `contacts`, `device`), `search.js` (globale Suche) |
| `tests/` | pytest: `test_packets.py` (Unit), `test_e2e.py` (Server gegen Simulator), `fake_companion.py` (simulierter TCP-Companion) |

## Architektur und Datenfluss

- Der **Server ist der einzige Client der Node.** Er bleibt verbunden, auch ohne offenen Browser, und verbindet nach einem Abbruch automatisch neu (`Mesh._supervisor`).
- **Logik gehört ins Backend:** Protokoll, Parsing, Zustand, Persistenz und Entscheidungen. Das Frontend formatiert und zeigt an. Nur browserlokale Dinge bleiben im Frontend: aktiver Chat, ungelesene Zähler, Pause/Filter im Live-Traffic, Desktop-Benachrichtigungen, Kartenstil (`localStorage`, Präfix `mcw.`).
- **Server→Browser:** Beim Verbinden schickt der WebSocket ein `snapshot`-Event, danach Events wie `status`, `packet`, `msg`, `contact`, `contact_del`, `node`, `nodes`, `contacts`, `channels`, `settings`, `packets`, `packets_clear`, `msgs`, `toast`, `log`, `watch_alert`. Erzeugt werden sie in `Mesh.emit()`, verarbeitet in `frontend/js/main.js` (`handlers`). Ein neues Event braucht beide Seiten.
- **Browser→Server:** REST-Aufrufe über `run(path, body, okMsg, method)` in `api.js`. Fehler kommen als HTTP 400 mit `{"detail": "deutsche Meldung"}` (Exception `MeshError`) und erscheinen als Toast.
- **Gerätebefehle** laufen immer über `Mesh._lib(name, …)` (Methode der meshcore-Bibliothek) oder `Mesh._cmd(bytes, expect)` (roher Befehl). Beide serialisieren über `self.lock`, und es läuft immer nur ein Befehl. Fehlercodes werden zu deutschen Meldungen (`ERRS`).
- **Event-Handler der Bibliothek** (`Mesh._subscribe`) sind bewusst **synchron**. Nur so bleibt die Reihenfolge erhalten (Funkpaket vor der zugehörigen Nachricht, nötig für die Region-Zuordnung in `_find_rx_packet`). Wer aus einem Handler einen Gerätebefehl braucht, startet ihn mit `self.spawn(...)`. Ein `await` im Handler ist verboten.
- **Regionen und Räume** lassen sich nicht zurückrechnen, nur gegen Namen prüfen. Der Regions-Code ist ein HMAC über den Paketinhalt und darum bei jedem Paket anders. Statistiken deshalb pro Region, nicht pro Code. Gehörte Räume (nicht auf dem Gerät) laufen als Unterhaltung `room:<name>`. Beim Abonnieren bzw. wenn der Kanal auf dem Gerät auftaucht, verschiebt `Mesh._merge_room` den Verlauf nach `ch:<idx>`.
- Die Protokoll-Konstanten stammen aus MeshCore `examples/companion_radio`. Was die Bibliothek nicht passend anbietet, wird roh gesendet (Scope/Region, Hash-Modus, Nachrichten senden, `SET_OTHER`). Das Format muss zum bisherigen Verhalten passen: Regionsname ohne `#` und Schlüssel `sha256('#'+name)[:16]`.
- **Hop-Hashes** ordnet `Mesh.resolve_path` Knoten zu (Repeater bevorzugt, bei Mehrdeutigkeit kürzester plausibler Weg). Pakete tragen das Ergebnis als `res` (`[Schlüssel|null, Kandidaten]` je Hop), im Frontend über `hopInfo(p, i)`. Keine eigene Auflösung per Hash im Frontend bauen.
- Buttons in generiertem HTML nutzen `data-act="name"` plus `data-…`-Attribute. Die Funktion liegt in `actions` (`state.js`), ein globaler Klick-Handler ruft sie auf. Keine Inline-`onclick`, denn ES-Module haben keine globalen Funktionen.

## Code-Stil

- **Frontend:** kompakter, dichter Stil wie im Bestand (Einzeiler, kurze Namen wie `$`, `S`, `esc`). Kein Framework, kein npm, kein Bundler. Alle Fremddaten (Namen, Nachrichten, Kanäle) beim Einfügen per `innerHTML` mit `esc()` escapen. Datum und Zeit mit `de-DE`.
- **Backend:** Python ≥ 3.10, asyncio, Typ-Hinweise sparsam. Logausgaben mit `[+]`, `[-]`, `[!]`. Listen im Speicher begrenzen (`MAX_PKTS`, `MAX_LOG`, `MAX_MSGS`).
- Feldnamen im JSON sind camelCase, wie im Frontend erwartet (`outPathLen`, `hopCount`, `lastAdvert`, …).
- Abhängigkeiten stehen in `requirements.txt` (Laufzeit) und `requirements-dev.txt` (Tests). Neue Pakete nur nach Rücksprache.

## Ausführen und Prüfen

Das venv liegt in `.venv/`. Alle Python-Befehle laufen darüber.

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest                          # alle Tests (ca. 15 s, keine Hardware nötig)
.venv/bin/python tests/fake_companion.py --port 5099  # Simulator zum Entwickeln
.venv/bin/python -m backend 127.0.0.1:5099 --port 8080
for f in frontend/js/*.js; do node --check --input-type=module < "$f"; done   # JS-Syntax
```

Nach Änderungen mindestens die Tests laufen lassen. Bei Backend-Änderungen neue Fälle in `tests/test_e2e.py` ergänzen und den Simulator bei Bedarf erweitern (`Companion.reply`, `Companion.pushes`). Tests und Hilfsskripte gehören ins Repo unter `tests/`, nicht nach `/tmp`.

Hinweis für Shell-Befehle: `pkill -f <muster>` trifft auch die eigene Shell, wenn das Muster in der Befehlszeile vorkommt. Prozesse besser per PID beenden.

Echte Hardware steht dem Agent in der Regel nicht zur Verfügung. Bei Protokolländerungen gegen Firmware und Bibliothek prüfen (`.venv/lib/python3*/site-packages/meshcore/`) und dem Nutzer sagen, dass ein Test am Gerät noch aussteht.

## Docker

`Dockerfile` (python:3.12-slim) kopiert nur `requirements.txt`, `backend/` und `frontend/`. `.dockerignore` ist eine Whitelist: Neue Laufzeit-Dateien dort **und** im Dockerfile ergänzen. Die Daten liegen im Volume `/data`.

## Hinweise

- Keine Authentifizierung. Ohne Rücksprache nichts ändern, was den Server öffentlich erreichbar macht. Der Standard-Bind ist `127.0.0.1`.
- Wenn sich Funktionen ändern, die README (Deutsch) aktuell halten.

## Karten

Grundkarten zentral in `frontend/js/basemaps.js` (`baseLayers()`, `defaultBase()`), genutzt von der Hauptkarte und der Mini-Karte im Detailfenster. Vektorkarten von OpenFreeMap über `L.maplibreGL` (Plugin maplibre-gl-leaflet); die Beschriftung wird beim Laden auf `name:de` umgestellt. Namensnennungen sind Pflicht und stehen dort. Keine Kartendienste mit API-Schlüssel oder unklaren Nutzungsbedingungen einbauen.

## Diagramme (Statistik-Tab)

Tabs sind per Adresse erreichbar (`/#stats`, `/#chat` …). Zum Prüfen des Layouts: Verlauf mit `python -m tests.seed_history <db> --days 7` erzeugen, Server mit `--data` darauf starten und Screenshots machen, breit (1400 px) und Handy (390 px). Es darf keinen seitlichen Scrollbalken geben: Raster mit `minmax(min(100%, …), 1fr)`, Karten mit `min-width:0`, Tabellen in `.tblwrap`.

Selbst gebautes SVG ohne Bibliothek (`frontend/js/stats.js`). Unterseiten liegen im Objekt `PAGES` (je `render` für HTML und `after` für Diagramme, die die Breite ihres Containers brauchen); erreichbar per `#stats/<seite>`. Gerätewerte speichert der Server in `device_stats`, Mittelwerte und Zähler-Zuwächse berechnet `Store.device_stats`. Säulen für Mengen, Linien für Verläufe. Detailfenster zu Knoten: `GET /api/stats/node?key=|hash=` (`Mesh.node_stats`, Wege mit Koordinaten aus `_path_points`), Zeilen mit `data-act="nodeDetail"`. Jede Kennzahl ist eine einzelne Datenreihe in `--accent2`, also ohne Legende. Säulen höchstens 24 px breit, oben mit 4 px abgerundet, Gitterlinien 1 px in `--border`. Werte stehen am Balkenende oder im Tooltip (Inhalt nur per `textContent`). Neue Diagramme in diesem Stil, keine zweite y-Achse.

## Version, CI und Releases

Version in `backend/__init__.py` (`__version__`); Images aus der CI setzen `MESHBOARD_VERSION`, `--version` gibt `meshboard <version>` aus. Der Workflow `.github/workflows/container.yml` testet jeden Push/PR und veröffentlicht Images für amd64 und arm64 auf GHCR (`ghcr.io/fdyfox/meshboard`). Release: `__version__` erhöhen, Abschnitt `## <Version>` in `CHANGELOG.md`, GitHub-Release mit Tag `v<Version>`. Das Dockerfile nutzt `ENTRYPOINT`, damit Argumente von `docker run IMAGE …` beim Server ankommen.
