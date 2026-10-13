"""Ende-zu-Ende-Tests: Backend gegen den simulierten Companion (tests/fake_companion.py)."""
import asyncio
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import websockets

ROOT = Path(__file__).resolve().parent.parent
BOB = "c0ffee" + "11" * 29


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Client:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.port = port

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def json(self, method, path, body=None):
        status, raw = self.call(method, path, body)
        return status, json.loads(raw)

    def state(self):
        return self.json("GET", "/api/state")[1]

    def wait(self, cond, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            s = self.state()
            if cond(s):
                return s
            time.sleep(0.3)
        raise AssertionError("Bedingung nicht erfüllt")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    node_port, http_port = free_port(), free_port()
    procs = [subprocess.Popen([sys.executable, str(ROOT / "tests" / "fake_companion.py"), "--port", str(node_port)])]
    time.sleep(0.5)
    procs.append(subprocess.Popen([sys.executable, "-m", "backend", f"127.0.0.1:{node_port}", "--port", str(http_port),
                                   "--data", str(tmp_path_factory.mktemp("data"))], cwd=ROOT))
    c = Client(http_port)
    try:
        end = time.time() + 15
        while True:
            try:
                c.state()
                break
            except OSError:
                if time.time() > end:
                    raise
                time.sleep(0.2)
        c.wait(lambda s: s["status"]["connected"] and s["channels"] and s["msgs"].get("ch:0"))
        yield c
    finally:
        for p in procs:
            p.terminate()
            p.wait(5)


def test_frontend_served(app):
    for path in ("/", "/css/app.css", "/js/main.js", "/healthz"):
        assert app.call("GET", path)[0] == 200, path


def test_session_loaded(app):
    s = app.state()
    st = s["status"]
    assert st["self"]["name"] == "FakeNode" and st["dev"]["model"] == "Fake Board"
    assert st["scope"]["name"] == "saarland" and "saarland" in st["regions"]
    assert st["radio"]["batt"] == 4012 and st["radio"]["noise"] == -112
    assert {c["name"] for c in s["contacts"]} == {"Bob", "Rep-Saar"}
    assert s["channels"][0]["name"] == "Public"


def test_packets_nodes_neighbors(app):
    s = app.state()
    adverts = [p for p in s["packets"] if p["ptype"] == 4]
    assert adverts and adverts[0]["dec"]["name"] == "Rep-Saar"
    assert s["neighbors"]["5c"]["n"] >= 1
    node = next(n for n in s["nodes"] if n["key"].startswith("ab22"))
    assert node["heard"] and node["lat"] == 49.3


def test_incoming_messages_linked_to_region(app):
    s = app.state()
    ch = s["msgs"]["ch:0"][0]
    assert (ch["from"], ch["text"], ch["region"], ch["snr"]) == ("Alice", "Hallo Welt", "saarland", 5.0)
    dm = s["msgs"]["c:c0ffee111111"][0]
    assert (dm["from"], dm["text"], dm["hops"]) == ("Bob", "Hi direkt", "direkt")


def test_send_direct_gets_ack(app):
    assert app.json("POST", "/api/messages/send", {"conv": "c:c0ffee111111", "text": "Test DM"})[0] == 200
    s = app.wait(lambda s: any(m["text"] == "Test DM" and m.get("status") == "ok" for m in s["msgs"]["c:c0ffee111111"]))
    m = next(m for m in s["msgs"]["c:c0ffee111111"] if m["text"] == "Test DM")
    assert m["rtt"] == 1234


def test_send_channel_and_validation(app):
    assert app.json("POST", "/api/messages/send", {"conv": "ch:0", "text": "Test Kanal"})[0] == 200
    assert any(m["text"] == "Test Kanal" and m["status"] == "sent" for m in app.state()["msgs"]["ch:0"])
    status, body = app.json("POST", "/api/messages/send", {"conv": "ch:0", "text": "x" * 200})
    assert status == 400 and body["detail"] == "Nachricht zu lang"


def test_repeats_counted(app):
    """Weiterleitungen der eigenen Nachricht durch Repeater zählen (je Repeater einmal)."""
    assert app.json("POST", "/api/messages/send", {"conv": "ch:0", "text": "Echo Kanal"})[0] == 200
    s = app.wait(lambda s: any(m["text"] == "Echo Kanal" and len(m.get("repeats", [])) == 2 for m in s["msgs"]["ch:0"]))
    m = next(m for m in s["msgs"]["ch:0"] if m["text"] == "Echo Kanal")
    assert [r["h"] for r in m["repeats"]] == ["5c", "7a"] and m["repeats"][1]["hops"] == 2
    time.sleep(1)
    m = next(m for m in app.state()["msgs"]["ch:0"] if m["text"] == "Echo Kanal")
    assert len(m["repeats"]) == 2  # Duplikat von 5c nicht doppelt gezählt
    # Wiederholen: neuer Zeitstempel, Zählung beginnt neu
    ts = m["ts"]
    assert app.json("POST", "/api/messages/retry", {"conv": "ch:0", "id": m["id"]})[0] == 200
    s = app.wait(lambda s: any(x["id"] == m["id"] and x["ts"] > ts and len(x["repeats"]) == 2 for x in s["msgs"]["ch:0"]))
    # Direktnachricht
    assert app.json("POST", "/api/messages/send", {"conv": "c:c0ffee111111", "text": "Echo DM"})[0] == 200
    app.wait(lambda s: any(m["text"] == "Echo DM" and len(m.get("repeats", [])) == 2 for m in s["msgs"]["c:c0ffee111111"]))


def test_device_commands(app):
    for path, body in [("/api/advert", {"flood": True}), ("/api/device/position", {"lat": 49.1, "lon": 7.2}),
                       ("/api/device/other", {"locAdv": False}), ("/api/device/tx", {"value": 20}),
                       ("/api/device/time", None), ("/api/hash-mode", {"value": 1}),
                       (f"/api/contacts/{BOB}/reset-path", None), (f"/api/contacts/{BOB}/share", None)]:
        assert app.call("POST", path, body)[0] == 200, path
    assert app.json("POST", "/api/device/name", {"value": "Neu"})[0] == 200
    s = app.state()
    assert s["status"]["self"]["name"] == "Neu" and s["status"]["dev"]["pathHashMode"] == 1
    assert app.call("POST", "/api/device/position", {"lat": 99, "lon": 0})[0] == 400


def test_regions_settings(app):
    assert app.call("PUT", "/api/channels/0/region", {"value": "pfalz"})[0] == 200
    assert app.call("PUT", "/api/settings/extra-regions", {"value": "lux, #lothringen"})[0] == 200
    s = app.state()
    assert s["settings"]["chanRegion"] == {"Public:8b3387e9": "pfalz"}
    assert set(s["status"]["regions"]) >= {"saarland", "lux", "lothringen", "pfalz"}
    assert app.call("PUT", "/api/channels/0/region", {"value": ""})[0] == 200


def test_export(app):
    status, raw = app.call("GET", "/api/packets/export?fmt=csv")
    assert status == 200 and raw.decode().startswith("zeit;typ;route")
    status, raw = app.call("GET", "/api/packets/export?fmt=json")
    assert status == 200 and json.loads(raw)[0]["typ"]


def test_websocket_events_and_reconnect(app):
    async def run():
        async with websockets.connect(f"ws://127.0.0.1:{app.port}/api/ws") as ws:
            first = json.loads(await ws.recv())
            assert first["t"] == "snapshot"

            async def collect(seconds):
                """Alle Events einer festen Zeitspanne sammeln (der Companion sendet laufend Pakete)."""
                seen, end = [], time.monotonic() + seconds
                try:
                    while (left := end - time.monotonic()) > 0:
                        seen.append(json.loads(await asyncio.wait_for(ws.recv(), left)))
                except asyncio.TimeoutError:
                    pass
                return seen

            seen = await collect(2.5)
            assert any(m["t"] == "packet" for m in seen)
            await asyncio.to_thread(app.call, "POST", "/api/disconnect")
            seen = await collect(1.5)
            assert any(m["t"] == "status" and not m["status"]["connected"] for m in seen)
            await asyncio.to_thread(app.call, "POST", "/api/connect")
            seen = await collect(3)
            types = {m["t"] for m in seen}
            assert {"status", "contacts", "channels"} <= types
    asyncio.run(run())
    assert app.state()["status"]["connected"]


def test_wipe_keeps_contacts(app):
    t0 = int(time.time() * 1000)
    assert app.call("POST", "/api/wipe")[0] == 200
    s = app.state()
    # Der Simulator sendet laufend weiter – nur Nachrichten von vor dem Löschen dürfen fehlen
    assert all(m["rx"] >= t0 for a in s["msgs"].values() for m in a)
    assert {n["key"] for n in s["nodes"]} >= {BOB}


def test_rooms_and_candidate_region(app):
    s = app.wait(lambda s: s["msgs"].get("room:technik") and any(r["name"] == "technik" for r in s["rooms"]))
    m = s["msgs"]["room:technik"][0]
    assert (m["from"], m["text"], m["region"], m["hops"]) == ("Carl", "Moin aus Trier", "trier", 2)
    assert m["path"] == ["5c", "7a"] and "km" in m
    assert s["regionStats"]["trier"]["count"] >= 1
    assert any(c.get("name") == "technik" for c in s["chanStats"].values())
    pkt = next(p for p in s["packets"] if p["dec"].get("room") == "technik")
    assert pkt["region"] == "trier"


def test_probe_subscribe_forget_room(app):
    status, body = app.json("POST", "/api/rooms/probe", {"value": "#Geheimraum"})
    assert status == 200 and body["found"] >= 1
    s = app.state()
    assert s["watchRooms"] == ["Geheimraum"] and s["msgs"]["room:geheimraum"][0]["text"] == "psst"
    # Abonnieren: Kanal auf dem Gerät, Verlauf wandert in den Kanal
    assert app.call("POST", "/api/rooms/technik/subscribe")[0] == 200
    s = app.state()
    ch = next(c for c in s["channels"] if c["name"] == "#technik")
    assert "technik" not in {r["name"] for r in s["rooms"]} and "room:technik" not in s["msgs"]
    assert any(m["text"] == "Moin aus Trier" for m in s["msgs"][f"ch:{ch['idx']}"])
    # Vergessen
    assert app.call("DELETE", "/api/rooms/Geheimraum")[0] == 200
    assert app.call("DELETE", "/api/rooms/geheimraum")[0] == 200
    s = app.state()
    assert s["watchRooms"] == [] and "room:geheimraum" not in s["msgs"]


def test_save_region(app):
    assert app.call("POST", "/api/regions/save", {"value": "#trier"})[0] == 200
    assert app.call("POST", "/api/regions/save", {"value": "trier"})[0] == 200  # doppelt: keine Änderung
    s = app.state()
    assert s["settings"]["extraRegions"].split(", ").count("trier") == 1 and "trier" in s["status"]["regions"]
    assert app.call("POST", "/api/regions/save", {"value": " "})[0] == 400


def test_stats_endpoint(app):
    end = time.time() + 10  # Pakete werden alle 2 s gespeichert
    while True:
        status, st = app.json("GET", "/api/stats?hours=24")
        if st["cur"]["total"] or time.time() > end:
            break
        time.sleep(0.5)
    assert status == 200 and st["cur"]["total"] > 0 and st["retentionDays"] == 365
    assert st["cur"]["air"] > 0 and st["radio"]["sf"] == 8
    assert set(st["msgs"]) == {"convs", "dm", "rttAvg", "senders"}
    assert st["duty"]["limit"] == 10.0 and "buckets" in st["device"]  # Werte selbst: test_store
    assert st["nodeTypes"]
    assert any(t == "ADVERT" for t, _ in st["types"]) and len(st["timeline"]) >= 24
    assert st["collisions"]["active"] >= 1 and st["collisions"]["b1"] == []


def test_watch_api_and_resolved_hops(app):
    rep = "ab" + "22" * 31  # Repeater „Rep-Saar“ aus dem Simulator
    assert app.json("PUT", "/api/watch", {"key": rep, "hours": 6})[0] == 200
    assert app.state()["settings"]["watch"][rep]["hours"] == 6
    assert app.json("PUT", "/api/watch", {"key": "00" * 32, "hours": 6})[1]["detail"] == "Knoten unbekannt"
    assert app.json("PUT", "/api/watch", {"key": rep, "hours": 0})[0] == 200
    assert rep not in app.state()["settings"]["watch"]
    # Pakete tragen die Zuordnung ihrer Hops (5c ist im Simulator kein bekannter Knoten)
    assert any(p.get("res") == [[None, 0]] for p in app.state()["packets"] if p["path"] == ["5c"])


def test_replay_and_layout(app):
    st = app.json("GET", "/api/packets/replay?hours=1")[1]
    # Adverts von Rep-Saar: Start mit Position → (Hop 5c unbekannt) → eigene Node
    assert st["items"] and all(len(i[2]) >= 2 for i in st["items"]) and any(i[1] == 4 for i in st["items"])
    assert st["items"][0][2][0] == [49.3, 7.1] and not st["truncated"]
    segs = app.json("GET", "/api/packets/layout?raw=" + app.state()["packets"][-1]["raw"])[1]
    assert segs[0][0].startswith("Header:")
    assert app.json("GET", "/api/packets/layout?raw=zz")[0] == 400


def test_packet_link(app):
    p = app.state()["packets"][-1]
    assert app.json("GET", f"/api/packets/{p['id']}")[1]["raw"] == p["raw"]
    assert app.json("GET", "/api/packets/999999999")[0] == 400
    assert app.call("GET", "/api/packets/export?fmt=json")[0] == 200  # feste Pfade gehen weiter vor


def test_remote_admin_and_trace(app):
    rep = "ab" + "22" * 31
    st, body = app.json("POST", "/api/remote/login", {"key": rep, "password": "falsch"})
    assert st == 400 and "abgelehnt" in body["detail"]
    st, body = app.json("POST", "/api/remote/login", {"key": rep, "password": "Rep#Pw42", "remember": True})
    assert st == 200 and body["admin"] and body["remembered"]
    assert app.json("GET", f"/api/remote?key={rep}")[1]["remembered"]
    assert "Rep#Pw42" not in json.dumps(app.state())  # Passwörter gehen nie an den Browser
    s = app.json("POST", "/api/remote/status", {"key": rep})[1]
    assert (s["batt"], s["noise"], s["uptime"], s["lastSnr"], s["recvErrors"]) == (4105, -112, 86400, 6.5, 2)
    nb = app.json("POST", "/api/remote/neighbours", {"key": rep})[1]
    assert [(n["name"], n["snr"], n["secsAgo"]) for n in nb] == [(None, 7.0, 60), ("Bob", -2.5, 600)]
    assert app.json("POST", "/api/remote/cli", {"key": rep, "cmd": "ver"})[0] == 200
    conv = "c:" + rep[:12]
    app.wait(lambda s: any(m["dir"] == "in" and m.get("cli") and m["text"] == "> ver ok" for m in s["msgs"].get(conv, [])))
    assert app.json("POST", "/api/remote/status", {"key": "00" * 32})[0] == 400  # kein Kontakt
    tr = app.json("POST", "/api/trace", {"value": "ab,5c,ab"})[1]
    assert [h["snr"] for h in tr["hops"]] == [6.0, 5.0, 4.0] and tr["final"] == 7.0 and tr["hops"][0]["name"] == "Rep-Saar"
    assert app.json("POST", "/api/trace", {"value": "xyz"})[0] == 400


def test_push_webhook_and_ntfy(app):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    got = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            got.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    try:
        ev = {"dm": True, "mention": True, "watch": True, "chan": False}
        assert app.json("PUT", "/api/settings/push", {"type": "webhook", "url": url + "/hook", "token": "t0k", "events": ev})[0] == 200
        assert app.json("POST", "/api/push/test")[0] == 200
        assert got[-1][0] == "/hook" and got[-1][1] == "Bearer t0k" and got[-1][2]["kind"] == "test"
        assert app.state()["settings"]["push"]["tokenSet"] and "t0k" not in json.dumps(app.state())
        assert app.json("PUT", "/api/settings/push", {"type": "ntfy", "url": url + "/mein-thema", "token": "", "events": ev})[0] == 200
        assert app.json("POST", "/api/push/test")[0] == 200
        assert got[-1][0] == "/" and got[-1][1] is None and got[-1][2]["topic"] == "mein-thema" and "✓" in got[-1][2]["message"]
    finally:
        app.json("PUT", "/api/settings/push", {"type": ""})
        srv.shutdown()
    status, body = app.json("POST", "/api/push/test")
    assert status == 400 and body["detail"] == "Kein Dienst eingestellt"


def test_ack_preview_and_send(app):
    p = app.json("POST", "/api/settings/ack-preview", {"value": "@[{name}] {hops} hops"})[1]
    assert p == {"text": "@[Alice] 3 hops", "bytes": 15}
    assert app.json("POST", "/api/messages/ack", {"conv": "ch:0", "id": "gibtsnicht"})[1]["detail"] == "Nachricht nicht gefunden"
    assert app.json("POST", "/api/messages/send", {"conv": "room:technik", "text": "x"})[0] == 400


def test_add_heard_node_as_contact(app):
    rep = "ab" + "22" * 31  # Repeater „Rep-Saar“, kommt laufend per Advert
    assert app.call("DELETE", f"/api/contacts/{rep}")[0] == 200
    s = app.state()
    assert all(c["key"] != rep for c in s["contacts"]) and any(n["key"] == rep for n in s["nodes"])
    # Nur gehört: Kontakt wird aus den Advert-Daten gebaut, Pfad unbekannt
    assert app.call("POST", f"/api/contacts/{rep}/add")[0] == 200
    c = next(c for c in app.state()["contacts"] if c["key"] == rep)
    assert (c["name"], c["type"], c["saved"], c["flood"]) == ("Rep-Saar", 2, True, True)
    status, body = app.json("POST", f"/api/contacts/{'ee' * 32}/add")
    assert status == 400 and "unbekannt" in body["detail"]
