# Meshboard

**Meshboard** ist eine Web-App für **MeshCore-Companions**. Ein kleiner Python-Server verbindet sich per **TCP/WiFi**, **USB (seriell)** oder **Bluetooth LE** mit der Node und hält die Verbindung dauerhaft. Die Oberfläche läuft im Browser, auf beliebig vielen Geräten gleichzeitig.

## Funktionen

- **Live-Traffic** – alle empfangenen Pakete mit Typ, Route, Hop-Pfad (Pfad-Hash-Größe 1/2/3 Byte), SNR/RSSI und Region. Dazu Filter, Detailansicht mit farbig aufgeschlüsselten Rohdaten (Header, Pfad, Schlüssel, MAC …), Direktlink auf jedes Paket (`#live/<id>`), CSV/JSON-Export und Pakete pro Minute.
- **Statistik** – Der Server speichert alle empfangenen Pakete und alle 5 Minuten die Gerätewerte, standardmäßig ein Jahr lang. Zeiträume: die letzten 24 Stunden, 7, 30 oder 90 Tage oder das letzte Jahr. Unterseiten:
  - **Übersicht:** Kennzahlen mit Vergleich zum Vorzeitraum und automatische Hinweise, etwa zu hoher Kanalbelegung, Duty-Cycle, steigendem Rauschen oder Knoten mit zu vielen Adverts.
  - **Funk & Gerät:** Rauschpegel, eigene Sendezeit mit dem gesetzlichen Duty-Cycle-Grenzwert, Empfangs-SNR, Batterie und Gerätezähler.
  - **Netz:** Kanalbelegung, Empfänge je Paket, Routen, Pakettypen, Hops, Pfad-Hash-Größe, Regionen und Aktivität nach Wochentag × Uhrzeit.
  - **Knoten:** aktive Knoten, Knotentypen, direkte Nachbarn mit Entfernung, Repeater-Last, beobachtete Knoten, Hash-Kollisionen (Repeater mit gleichem Hop-Hash bei 1, 2 und 3 Byte), neue Knoten und Advert-Häufigkeit. Ein Klick auf einen Knoten öffnet Details: Empfangsqualität, Weiterleitungen, Adverts, die Wege seiner Adverts auf einer Karte, über welche Nachbarn er bei dir ankommt, seine Nachbarn im Netz, Aktivität nach Wochentag × Uhrzeit, SNR-Verteilung und die letzten Adverts. Direktlink: `#stats/nodes?node=<Schlüssel>`.
  - **Routen:** alle Funkverbindungen zwischen Knoten auf einer Karte, häufigste Pfade und weiteste Verbindungen.
  - **Nachrichten:** Kanalverkehr, Unterhaltungen, aktivste Absender, Zustellquote und Laufzeit der Direktnachrichten.

  Nach einem Neustart ist der Live-Traffic wieder da.
- **Chat** – Kanäle und Direktnachrichten, Zustellbestätigung mit Laufzeit, Repeater-Zähler für gesendete Nachrichten (grauer Haken = gesendet, grün mit Zahl = so viele Repeater haben weitergeleitet), erneut senden ohne Bestätigung, Antworten per `@[Name]`, Direktnachricht an den Absender.
  - **Schnellantwort ✓** an empfangenen Nachrichten, mit eigener Vorlage und Vorschau unter Gerät › App, z. B. `@[{name}] | received in 66346 at {time} | {hops} hops ({path}) | {km} km`. Zahlen mit Dezimalpunkt, Platzhalter auch englisch (`{time} {path} {segs} {noloc} {latency}`). Platzhalter: `{name}`, `{zeit}`, `{hops}` (Zahl), `{pfad}` (Hop-Hashes, bei Platzmangel gekürzt), `{km}` (Strecke entlang des Weges über Knoten mit bekannter Position), `{abschnitte}`, `{ohne_pos}`, `{snr}`, `{laufzeit}` (Sekunden seit dem Absenden laut Absender-Uhr), `{region}`.
  - **Klick auf den Absendernamen** öffnet das Detailfenster des Knotens (Zuordnung per Name wie beim privaten Antworten). Ist der Name unbekannt und das Nachschlagen aus, sucht „🔎 Auf live.saarmesh.de suchen“ einmalig dort.
  - **Privat antworten ✉** an Kanalnachrichten: öffnet den Direktchat mit dem Absender. Ist er noch kein Kontakt, sucht der Server ihn per Name unter den gehörten Knoten (bei gleichem Namen der zuletzt gehörte, sonst auf CoreScope, falls eingeschaltet) und speichert ihn im Gerät.
  - **Ungelesen-Badges** an jeder Unterhaltung. Die **Benachrichtigung** (Badge am Tab „Chat“, Desktop-Meldung) ist pro Kanal oder Kontakt einstellbar: alle Nachrichten, nur Erwähnungen (`@[Name]`) oder aus. Gehörte, nicht abonnierte Räume benachrichtigen nie.
- **Repeater verwalten** – im Detailfenster eines Repeaters oder Room-Servers („🛠 Verwalten“) bzw. in den Kontakten: Anmeldung (Passwort optional auf dem Server gemerkt, nie an den Browser), Status (Batterie, Laufzeit, Rauschen, Sendezeit, Zähler), Nachbarliste des Repeaters mit SNR und eine CLI-Konsole.
- **Trace** – Weg zu einem Knoten hin und zurück testen, mit SNR je Abschnitt. Der Pfad wird aus dem gespeicherten Kontaktpfad vorgeschlagen und lässt sich anpassen.
- **Auto-Antwort pro Kanal** – im Chat-Kopf („🤖“): Auslösewörter (z. B. `test, !ping`), eigene Vorlage oder die Schnellantwort-Vorlage, Sperrzeit je Absender. Der Server antwortet auch ohne offenen Browser, aber nur auf ganze Wörter, nicht auf Nachrichten an andere (`@[Name]`), nicht auf nachgeholte ältere Nachrichten und höchstens alle 10 s pro Kanal.
- **Push aufs Handy** – ntfy, Telegram oder eigener Webhook (Gerät › App): Direktnachrichten, Erwähnungen, Kanäle mit Benachrichtigung „Alle“ und beobachtete Knoten. Höchstens 30 Meldungen in 10 Minuten. Docker-Images nutzen `TZ=Europe/Berlin` (für `{zeit}` in Antworten), änderbar per `-e TZ=…`.
- **Knoten beobachten** – im Detailfenster eines Knotens oder auf der Karte („👁 Beobachten“) mit Schwelle in Stunden. Der Server meldet, wenn der Knoten so lange nicht gehört wurde (eigenes Advert oder eindeutig als Hop im Pfad) und wenn er wieder da ist, als Hinweis und Desktop-Meldung.
- **Hops zuordnen** – Teilen sich mehrere Knoten einen Hop-Hash, bevorzugt der Server Repeater und Room-Server und wählt die Kombination mit dem kürzesten plausiblen Weg (Absender → Hops → eigene Node). Vermutete Zuordnungen sind mit „?“ bzw. gestricheltem Rahmen markiert.
- **Unbekannte Knoten nachschlagen** – optional (Gerät › App, standardmäßig aus) auf einer [CoreScope](https://github.com/Kpa-clawbot/corescope)-Instanz wie [live.saarmesh.de](https://live.saarmesh.de/). Hop-Hashes und Nachbar-Präfixe ohne bekannten Knoten schlägt der Server im Hintergrund nach (gedrosselt, je Hash höchstens einmal am Tag, nur Repeater und Room-Server). Die globale Suche fragt dort nur, wenn lokal kein Knoten und kein Kontakt passt; ein Klick auf einen Treffer öffnet die Details. Abgefragt wird nur, wenn eigene Daten fehlen. Gefundene Knoten sind mit ihrer Quelle markiert, helfen beim Zuordnen von Hops, lassen sich im Gerät speichern und werden durch ein eigenes Advert ersetzt. Dabei gehen Hashes und Suchbegriffe an den eingestellten Server.
- **Regionen** – Standard-Region des Geräts und Region **pro Kanal**. Empfangene Nachrichten zeigen ihre Region und Hash-Größe. Unbekannte Regionen erkennt der Server über eine eingebaute Namensliste (SaarLorLux, Länder, Großstädte).
- **Hashtag-Räume entdecken** – Räume wie `#technik`, die im Netz gehört werden, aber nicht auf dem Gerät eingerichtet sind, erkennt der Server über die Namensliste oder über eigene Namen („#Raum suchen“ im Chat). Er liest sie mit. Mit einem Klick richtest du einen Raum auf dem Gerät ein, der Verlauf wird übernommen.
- **Im Netz gehört** – Übersicht, welche Regionen und Kanäle wie oft und von welchen Knoten gehört wurden.
- **Karte** – Companions, Repeater, Room-Server und Sensoren mit Standort aus Adverts. Dazu Nachbar-Linien nach SNR, Paketpfad auf der Karte und eigene Position per Klick. Neue Pakete können live als Linie entlang ihres Weges laufen; die **Wiedergabe** spielt die letzten 1 h bis 3 Tage im Zeitraffer ab.
- **Suche** – `Strg+K` oder `/`: Knoten (auch per Hash), Kontakte, Kanäle, Räume und Nachrichten.
- **Adverts** – Zero-Hop und Flood.
- **Kontakte** – speichern, löschen, teilen, Pfad zurücksetzen, Entfernung. Auch nur gehörte Knoten lassen sich im Gerät speichern (in den Kontakten oder im Karten-Popup), der Kontakt entsteht dann aus dem letzten Advert, mit unbekanntem Pfad.
- **Gerät** – Verbindung, Name, Position, TX-Leistung, Pfad-Hash-Größe, Batterie, Rauschpegel, Airtime, Paketstatistik, Neustart, Protokoll-Log.

Der Server zeichnet rund um die Uhr auf, auch wenn kein Browser offen ist. Knoten, Chatverläufe, Paketverlauf und Einstellungen liegen in einer SQLite-Datenbank. „Leeren“ im Live-Traffic leert nur die Anzeige, der Verlauf für die Statistik bleibt erhalten.

## Aufbau

```
backend/     Python (FastAPI + meshcore): Verbindung zur Node, Zustand, Paket-Parser, Regionen, Speicher
  mesh.py      Verbindung und gesamte Logik
  packets.py   Funkpakete zerlegen, Region erkennen
  discovery.py Hashtag-Räume erkennen und entschlüsseln, Regionen über Namensliste finden
  candidates.py Namensliste für Regionen und Räume (erweiterbar)
  lookup.py    Unbekannte Knoten auf CoreScope nachschlagen
  store.py     SQLite (Knoten, Nachrichten, Einstellungen)
  api.py       REST-Befehle, WebSocket /api/ws, Auslieferung des Frontends
frontend/    Browser-Oberfläche: index.html, css/app.css, js/*.js (ES-Module, kein Build-Schritt)
tests/       pytest-Suite und simulierter Companion (tests/fake_companion.py)
```

Der Browser bekommt beim Öffnen einen Snapshot des Zustands und danach Live-Events über den WebSocket. Befehle wie Nachricht senden oder Name setzen gehen per REST an den Server. Die API-Dokumentation steht unter `/api/docs`.

## Installation

Voraussetzung: Python 3.10 oder neuer.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m backend 192.168.1.50          # TCP-Node (Port 5000)
```

Die App ist dann unter http://localhost:8080 erreichbar.

Weitere Varianten:

```sh
.venv/bin/python -m backend 192.168.1.50:5003     # TCP mit anderem Port
.venv/bin/python -m backend /dev/ttyUSB0          # USB / seriell
.venv/bin/python -m backend ble:AA:BB:CC:DD:EE:FF # Bluetooth LE
.venv/bin/python -m backend --bind 0.0.0.0        # im LAN erreichbar
.venv/bin/python -m backend                       # ohne Node – Verbindung im Browser unter „Gerät“ einrichten
```

Die zuletzt gewählte Node merkt sich der Server. Nach einem Verbindungsabbruch verbindet er sich automatisch neu.

## Docker

### Fertiges Image

Für amd64 und arm64 (z. B. Raspberry Pi) liegen fertige Images auf GHCR:

```sh
docker run -d --name meshboard -p 8080:8080 -v ./data:/data \
  -e MESHCORE_HOST=192.168.1.50 ghcr.io/fdyfox/meshboard:latest
```

| Tag | Inhalt |
|---|---|
| `latest`, `<version>`, `<major>.<minor>` | veröffentlichte Releases |
| `test` | aktueller Stand von `main` |
| `sha-<commit>` | ein bestimmter Commit |

In der `docker-compose.yml` lässt sich statt `build: .` auch `image: ghcr.io/fdyfox/meshboard:latest` eintragen. Argumente nach dem Image-Namen gehen an den Server, zum Beispiel `--version` oder `--days 90`.

### Selbst bauen

In `docker-compose.yml` die Adresse der Node eintragen und starten:

```sh
docker compose up -d --build
```

Die App läuft dann unter `http://<server>:8080`. Die Daten liegen in `./data`, demselben Ordner, den der Server auch ohne Docker nutzt. Du kannst also zwischen beiden Startarten wechseln und behältst alle Daten. Aber nie beide gleichzeitig: Eine TCP-Node bedient nur einen Client, und beide würden in dieselbe Datenbank schreiben.

```sh
docker compose stop                               # Docker anhalten …
.venv/bin/python -m backend 192.168.1.24:5003     # … und ohne Docker mit denselben Daten starten
```

Der Ordner `data` muss dem Container-Benutzer (UID 1000) gehören, sonst startet der Server nicht. Docker legt fehlende Ordner als root an. Deshalb den Ordner vor dem ersten Start anlegen: `mkdir -p data` (bei Bedarf `sudo chown 1000 data`).

Für USB `MESHCORE_SERIAL` setzen und das Gerät unter `devices:` freigeben (Beispiel in der Compose-Datei). Bluetooth im Container braucht zusätzlich Zugriff auf D-Bus/BlueZ des Hosts. Einfacher ist es, den Server für BLE direkt auf dem Host zu starten.

## Konfiguration

| Variable | Standard | Bedeutung |
|---|---|---|
| `MESHCORE_TARGET` | – | Node als `tcp:host[:port]`, `serial:/dev/…` oder `ble:adresse` |
| `MESHCORE_HOST` / `MESHCORE_PORT` | – / `5000` | TCP-Node (Alternative zu `MESHCORE_TARGET`) |
| `MESHCORE_SERIAL` | – | Serielle Schnittstelle, z. B. `/dev/ttyUSB0` |
| `MESHCORE_BLE` | – | BLE-Adresse der Node |
| `PORT` | `8080` | HTTP-Port |
| `BIND` | `127.0.0.1` (Docker: `0.0.0.0`) | Bind-Adresse |
| `PACKET_DAYS` | `365` | Paketverlauf für die Statistik so viele Tage aufbewahren |
| `DATA_DIR` | `./data` (Docker: `/data`) | Verzeichnis für die SQLite-Datenbank |

Die Kommandozeilen-Argumente (`node`, `--port`, `--bind`, `--data`, `--days`, `--debug`) haben Vorrang vor den Umgebungsvariablen.

## Entwicklung und Tests

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Die Tests starten den Server gegen einen simulierten Companion und brauchen keine Hardware. Für die Statistik erzeugt `.venv/bin/python -m tests.seed_history data-dev/meshcore.db --days 7` künstlichen Verlauf, anzusehen mit `.venv/bin/python -m backend --data data-dev`. Den Simulator kannst du auch zum Entwickeln nutzen:

```sh
.venv/bin/python tests/fake_companion.py --port 5099
.venv/bin/python -m backend 127.0.0.1:5099
```


### Releases

Jeder Push auf `main` testet den Stand und veröffentlicht das Image `:test` (Workflow `.github/workflows/container.yml`). Danach schickt die CI einen POST an einen Komodo-Webhook (z. B. `https://komodo.example.de/listener/github/stack/meshboard/deploy`), wenn die Repository-Secrets `KOMODO_WEBHOOK_URL` und `KOMODO_WEBHOOK_SECRET` (Webhook-Secret aus Komodo) gesetzt sind. Für ein Release:

1. Version in `backend/__init__.py` (`__version__`) erhöhen und einen Abschnitt `## <Version>` in `CHANGELOG.md` anlegen.
2. Auf GitHub ein Release mit dem Tag `v<Version>` veröffentlichen, z. B. `v0.2.0`.

Der Workflow prüft, dass Tag, Code und Changelog zusammenpassen, und veröffentlicht `:<version>`, `:<major>.<minor>` und `:latest` (bei Pre-Releases ohne `latest`).
## Hinweise

- **Keine Authentifizierung:** Jeder, der den Port erreicht, kann die Node steuern. Betreibe den Server nur im eigenen Netz oder hinter einem Reverse-Proxy mit Anmeldung.
- Die Oberfläche funktioniert in allen aktuellen Browsern, auch auf dem Handy. Web Serial oder Web Bluetooth braucht der Browser nicht mehr.
- Karte: [Leaflet](https://leafletjs.com/). Standard sind Vektorkarten von [OpenFreeMap](https://openfreemap.org/), eingebunden über MapLibre GL und maplibre-gl-leaflet: frei, ohne API-Schlüssel, mit deutscher Beschriftung, Stile Hell, Dunkel, Straße und Bunt. Zur Auswahl stehen außerdem OpenStreetMap, OpenTopoMap und ein Esri-Satellitenbild. Ohne MapLibre (z. B. offline) fällt die Karte auf OpenStreetMap zurück.
- Das Protokoll setzt die Bibliothek [meshcore](https://github.com/meshcore-dev/meshcore_py) um, gemäß [MeshCore companion_radio](https://github.com/meshcore-dev/MeshCore/tree/main/examples/companion_radio).

## Lizenz

Meshboard ist ein inoffizielles Community-Projekt und nicht mit dem [MeshCore-Projekt](https://github.com/meshcore-dev/MeshCore) verbunden.


MIT – siehe [LICENSE](LICENSE).
