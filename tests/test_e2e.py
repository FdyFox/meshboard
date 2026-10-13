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
