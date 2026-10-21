"""Paketverlauf: speichern, nach Neustart laden, Statistik."""
from backend.mesh import Mesh, now_ms
from backend.store import Store
from tests.test_packets import advert


def make(tmp_path):
    return Mesh(Store(tmp_path / "t.db"))


def test_packets_persist_and_reload(tmp_path):
    m = make(tmp_path)
    for i in range(5):
        m.on_raw_packet(advert(name=b"Rep"), 8.0 + i, -90)
    m.on_raw_packet(advert(key=b"\xcd" * 32, name=b"Other", hops=b""), -3.0, -110)
    m._flush()
    m2 = make(tmp_path)  # „Neustart“
    assert len(m2.packets) == 6 and m2.stats["total"] == 6
    assert m2.packets[-1]["dec"]["name"] == "Other" and m2.packets[0]["_payload"]
    assert m2.pkt_seq == 6
    m2.on_raw_packet(advert(), 1.0, -100)
    assert m2.packets[-1]["id"] == 7


def test_packet_stats(tmp_path):
    m = make(tmp_path)
    for i in range(4):
        m.on_raw_packet(advert(name=b"Rep"), 8.0, -90)  # dasselbe Paket viermal gehört
    m.on_raw_packet(advert(key=b"\xcd" * 32, name=b"Other", hops=b""), -3.0, -110)
    m._flush()
    st = m.packet_stats(24)
    cur = st["cur"]
    assert (cur["total"], cur["unique"], cur["nodes"]) == (5, 2, 2)
    assert st["types"] == [["ADVERT", 5]] and st["routes"] == [["FLOOD", 5]]
    assert sum(b["count"] for b in st["timeline"]) == 5 and sum(b["unique"] for b in st["timeline"]) == 2
    assert st["bucketMs"] == 3600000 and st["prev"] is None  # kein vollständiger Vorzeitraum
    assert dict(st["hops"]) == {1: 4, 0: 1}
    assert dict(st["snr"]) == {7.5: 4, -5.0: 1}
    rep = next(n for n in st["nodesTop"] if n["name"] == "Rep")
    assert (rep["adverts"], rep["count"]) == (1, 4)  # ein Advert, viermal gehört
    assert dict(st["hashSize"]) == {1: 1} and st["timeline"][-1]["snr"] is not None
    assert {n["hash"]: n["count"] for n in st["neighbors"]} == {"5c": 4, "cd": 1}
    assert st["repeaters"] == [{"hash": "5c", "count": 1, "name": None, "guess": False, "type": None}]  # eindeutig gezählt
    assert {n["name"] for n in st["newNodes"]} == {"Rep", "Other"}
    assert sum(c for _, c in st["hourly"]) == 5
    assert m.packet_stats(24 * 7)["bucketMs"] == 6 * 3600000
    assert m.packet_stats(24 * 30)["bucketMs"] == 86400000
    assert m.packet_stats(24 * 365)["bucketMs"] == 7 * 86400000


def test_airtime():
    from backend.packets import airtime_ms
    # SF8, 62,5 kHz, CR 4/8, 50 Byte: ~0,5 s (bekannte Größenordnung für MeshCore EU)
    assert 400 < airtime_ms(50, 8, 62.5, 8) < 700
    assert airtime_ms(50, 8, 62.5, 8) == airtime_ms(50, 8, 62.5, 4)
    assert airtime_ms(100, 8, 62.5, 5) > airtime_ms(50, 8, 62.5, 5)
    assert airtime_ms(50, None, 62.5, 5) is None


def test_old_database_migrated(tmp_path):
    import sqlite3
    db = sqlite3.connect(tmp_path / "t.db")
    db.execute("CREATE TABLE packets (id INTEGER PRIMARY KEY, t INTEGER NOT NULL, ptype INTEGER, route INTEGER, hops INTEGER, "
               "hs INTEGER, snr REAL, rssi INTEGER, len INTEGER, region TEXT, chan TEXT, src TEXT, name TEXT, nb TEXT, data TEXT NOT NULL)")
    db.commit()
    db.close()
    m = make(tmp_path)
    m.on_raw_packet(advert(), 8.0, -90)
    m._flush()
    assert m.packet_stats(24)["cur"]["unique"] == 1


def test_clear_keeps_history(tmp_path):
    m = make(tmp_path)
    m.on_raw_packet(advert(), 8.0, -90)
    m._flush()
    m.clear_packets()
    assert make(tmp_path).packets == []           # Live-Ansicht bleibt leer
    assert make(tmp_path).packet_stats(24)["cur"]["total"] == 1  # Statistik behält den Verlauf
    m.wipe()
    assert make(tmp_path).packet_stats(24)["cur"]["total"] == 0


def test_msg_stats(tmp_path):
    s = Store(tmp_path / "t.db")
    now = 1_800_000_000_000
    msgs = [("ch:0", {"id": "a", "dir": "in", "rx": now}), ("ch:0", {"id": "b", "dir": "out", "rx": now}),
            ("c:aa", {"id": "c", "dir": "out", "rx": now, "status": "ok"}),
            ("c:aa", {"id": "d", "dir": "out", "rx": now, "status": "noack"}),
            ("c:aa", {"id": "e", "dir": "in", "rx": now - 10 ** 9})]  # außerhalb des Zeitraums
    s.save_msgs("dev", msgs)
    st = s.msg_stats("dev", now - 1000)
    assert st["dm"] == {"ok": 1, "noack": 1, "fail": 0, "sent": 0}
    assert {c["conv"]: (c["in"], c["out"]) for c in st["convs"]} == {"ch:0": (1, 1), "c:aa": (0, 2)}


def test_backfill_old_packets(tmp_path):
    m = make(tmp_path)
    for _ in range(3):
        m.on_raw_packet(advert(), 8.0, -90)  # dasselbe Paket dreimal
    m._flush()
    m.store.db.execute("UPDATE packets SET ph=NULL, air=NULL, path=NULL")  # Stand vor den neuen Spalten
    m.self = {"sf": 8, "bw": 62.5, "cr": 8}
    m._backfill_packets()
    cur = m.packet_stats(24)["cur"]
    assert cur["unique"] == 1 and cur["air"] > 0 and m.store.packets_missing() == []


def test_device_stats_and_duty(tmp_path):
    from backend.mesh import duty_limit
    s = Store(tmp_path / "t.db")
    t0 = 1_800_000_000_000
    base = {"batt": 4000, "noise": -110, "tx_air": 100, "rx_air": 50, "recv": 10, "sent": 5, "uptime": 1000}
    s.save_device_sample("dev", t0, base)
    s.save_device_sample("dev", t0 + 300000, {**base, "tx_air": 130, "noise": -100, "uptime": 1300})
    s.save_device_sample("dev", t0 + 600000, {**base, "tx_air": 5, "uptime": 10})  # Gerät neu gestartet
    s.save_device_sample("dev", t0 + 900000, {**base, "tx_air": 25, "uptime": 310})
    d = s.device_stats("dev", t0, t0, 3600000, 1)
    assert d["total"]["tx_air"] == 30 + 20 and d["samples"] == 4
    assert d["buckets"][0]["noise"] == -107.5
    assert duty_limit(869.618) == 10.0 and duty_limit(868.3) == 1.0 and duty_limit(433.0) is None


def test_node_stats(tmp_path):
    m = make(tmp_path)
    rep = b"\xab" * 32
    for _ in range(3):
        m.on_raw_packet(advert(key=rep, name=b"Rep", hops=b"\x5c"), 6.0, -95)  # ein Advert, dreimal gehört
    m.on_raw_packet(advert(key=b"\xcd" * 32, name=b"Other", hops=b"\xab"), 4.0, -100)  # über Rep weitergeleitet
    m.on_raw_packet(advert(key=b"\xce" * 32, name=b"Third", hops=b"\x11\xab"), 2.0, -101)  # Rep als letzter Hop
    m._flush()
    st = m.node_stats(rep.hex(), None, 24)
    assert (st["adverts"], st["relayed"], st["direct"]) == (1, 2, 2)
    assert st["node"]["name"] == "Rep" and st["paths"][0]["path"] == "5c" and st["paths"][0]["count"] == 3
    assert st["recent"][0]["hops"] == 1 and st["snr"] == 3.0
    assert sum(b["adverts"] for b in st["buckets"]) == 1
    # Nachbarn im Netz: 5c hat das Advert gehört, 11 hat Third an Rep übergeben
    assert [(p["hash"], p["out"], p["in"]) for p in st["peers"]] == [("5c", 1, 0), ("11", 0, 1)]
    assert [(v["hash"], v["count"]) for v in st["via"]] == [("5c", 3)] and st["via"][0]["snr"] == 6.0
    assert sum(c for _, c in st["hourly"]) == 5 and dict(st["snrDist"]) == {2.5: 1, 0.0: 1}
    # nur Hash bekannt (mehrdeutig/unbekannt): Weiterleitungen trotzdem
    st = m.node_stats(None, "11", 24)
    assert st["key"] is None and st["relayed"] == 1 and st["adverts"] == 0


def test_notify_setting(tmp_path):
    m = make(tmp_path)
    m.set_notify("chan:Public:8b3387e9", "mention")
    m.set_notify("c:aabbccddeeff", "off")
    m.set_notify("c:aabbccddeeff", "all")  # Standard: Eintrag entfällt
    assert make(tmp_path).settings()["notify"] == {"chan:Public:8b3387e9": "mention"}
    import pytest
    from backend.mesh import MeshError
    with pytest.raises(MeshError):
        m.set_notify("x", "laut")


def test_node_path_points(tmp_path):
    m = make(tmp_path)
    m.self = {"name": "Ich", "lat": 49.2, "lon": 7.0}
    m.on_raw_packet(advert(key=b"\x5c" * 32, name=b"Hop", lat=49.3, lon=7.05, hops=b""), 5.0, -90)  # Repeater 5c mit Position
    m.on_raw_packet(advert(key=b"\xab" * 32, name=b"Rep", lat=49.4, lon=7.1, hops=b"\x5c\x77"), 3.0, -99)
    m._flush()
    p = m.node_stats((b"\xab" * 32).hex(), None, 24)["paths"][0]
    assert [x[2] for x in p["points"]] == ["Rep", "Hop", "Ich"] and p["unresolved"] == 1  # 77 unbekannt


def test_ack_template(tmp_path):
    import pytest
    from backend.mesh import DEFAULT_ACK, MeshError
    m = make(tmp_path)
    assert m.settings()["ackTemplate"] == DEFAULT_ACK
    m.set_ack_template("@[{name}] ack in 66346 mit SNR {snr} 🐇")
    assert make(tmp_path).settings()["ackTemplate"] == "@[{name}] ack in 66346 mit SNR {snr} 🐇"
    m.set_ack_template("  ")
    assert m.ack_template == DEFAULT_ACK
    with pytest.raises(MeshError):
        m.set_ack_template("x" * 200)


def test_route_distance(tmp_path):
    m = make(tmp_path)
    m.self = {"name": "Ich", "lat": 49.0, "lon": 7.0}
    m.nodes = {"aa" * 32: {"key": "aa" * 32, "name": "Alice", "lat": 49.2, "lon": 7.0},
               "5c" * 32: {"key": "5c" * 32, "name": "Hop", "lat": 49.1, "lon": 7.0}}
    msg = {"from": "Alice", "hops": 2, "path": ["5c", "77"]}
    m._route(msg, m._node_by_name("Alice"))
    # Alice → Hop → Ich: 2 Abschnitte à ~11,1 km, Hop 77 ohne Position
    assert msg["segs"] == 2 and msg["noloc"] == 1 and 22.0 < msg["km"] < 22.5
    direct = {"from": "?", "hops": 0}
    m._route(direct, None)  # Absender unbekannt: keine Strecke
    assert direct["km"] is None and direct["noloc"] == 1


def _node(key, name, lat=None, lon=None, typ=2, heard=None):
    n = {"key": key, "name": name, "type": typ, "heard": heard or now_ms()}
    if lat is not None:
        n.update(lat=lat, lon=lon)
    return n


def test_resolve_path_ambiguous(tmp_path):
    m = make(tmp_path)
    m.self = {"name": "Ich", "lat": 49.0, "lon": 7.0}
    m.nodes = {n["key"]: n for n in [
        _node("5c" + "11" * 31, "Nah", 49.05, 7.0), _node("5c" + "22" * 31, "Fern", 52.5, 13.4),  # zwei Repeater auf 5c
        _node("5c" + "33" * 31, "Handy", 49.0, 7.0, typ=1),  # Companion leitet nicht weiter
        _node("77" + "11" * 31, "Mitte", 49.2, 7.0), _node("77" + "22" * 31, "Weg", 48.0, 9.0),
        _node("aa" * 32, "Alice", 49.4, 7.0, typ=1)]}
    r = m.resolve_path(["77", "5c"], m.nodes["aa" * 32], m.self)
    assert [(x["name"], x["n"], x["guess"]) for x in r] == [("Mitte", 2, True), ("Nah", 2, True)]
    assert m.resolve_path(["99"])[0] == {"h": "99", "key": None, "n": 0, "guess": False, "name": None}
    # ohne Positionen bleibt der Hop offen
    m.nodes = {n["key"]: n for n in [_node("5c" + "11" * 31, "A"), _node("5c" + "22" * 31, "B")]}
    assert m.resolve_path(["5c"])[0]["name"] == "A / B" and m.resolve_path(["5c"])[0]["key"] is None


def test_hash_collisions(tmp_path):
    m = make(tmp_path)
    m.dev = {"pathHashMode": 0}
    m.nodes = {n["key"]: n for n in [
        _node("5c11" + "00" * 30, "R1"), _node("5c11" + "ff" * 30, "R2"), _node("5c22" + "00" * 30, "R3"),
        _node("5c33" + "00" * 30, "Handy", typ=1), _node("5c44" + "00" * 30, "Alt", heard=1)]}
    c = m.hash_collisions(now_ms() - 86400000)
    assert c["active"] == 3 and c["mode"] == 0
    assert [(g["hash"], sorted(n["name"] for n in g["nodes"])) for g in c["b1"]] == [("5c", ["R1", "R2", "R3"])]
    assert [g["hash"] for g in c["b2"]] == ["5c11"] and c["b3"] == []


def test_watch_nodes(tmp_path):
    import pytest
    from backend.mesh import MeshError
    m = make(tmp_path)
    events = []
    m.emit = lambda t, **d: events.append((t, d))
    key = "ab" * 32
    m.on_raw_packet(advert(name=b"Rep"), 5.0, -90)
    with pytest.raises(MeshError):
        m.set_watch("cd" * 32, 12)
    m.up_since = now_ms() - 48 * 3600000
    m.set_watch(key, 12)
    assert not m.watch[key]["down"]
    m.nodes[key]["heard"] = now_ms() - 13 * 3600000
    m.check_watch()
    assert m.watch[key]["down"] and ("watch_alert", {"key": key, "name": "Rep", "down": True,
                                                    "last": m.nodes[key]["heard"]}) in events
    assert make(tmp_path).watch[key]["down"]  # gespeichert
    m.on_raw_packet(advert(name=b"Rep", lat=49.31), 5.0, -90)  # wieder gehört
    assert not m.watch[key]["down"] and [d["down"] for t, d in events if t == "watch_alert"] == [True, False]
    # gerade erst verbunden: noch keine Meldung
    m.up_since = now_ms()
    m.nodes[key]["heard"] = 1
    m.check_watch()
    assert not m.watch[key]["down"]
    m.set_watch(key, 0)
    assert key not in m.watch


def test_route_stats(tmp_path):
    m = make(tmp_path)
    m.self = {"name": "Ich", "key": "ee" * 32, "lat": 49.2, "lon": 7.0}
    m.on_raw_packet(advert(key=b"\x5c" * 32, name=b"Hop", lat=49.3, lon=7.05, hops=b""), 5.0, -90)
    for _ in range(2):
        m.on_raw_packet(advert(key=b"\xab" * 32, name=b"Rep", lat=49.5, lon=7.1, hops=b"\x5c"), 3.0, -99)
    m._flush()
    r = m.route_stats(0)
    assert [(p["path"], p["count"], p["recv"], p["names"]) for p in r["topPaths"]] == [("5c", 1, 2, ["Hop"])]
    pairs = {tuple(sorted((l["a"]["name"], l["b"]["name"]))): l for l in r["links"]}
    assert set(pairs) == {("Hop", "Rep"), ("Hop", "Ich")} and not pairs[("Hop", "Rep")]["guess"]
    assert r["longest"][0]["km"] == max(l["km"] for l in r["links"])


def test_fill_template():
    m = {"from": "Alice", "hops": 3, "path": ["e6", "07", "78", "11", "22"], "km": 48.24, "segs": 4, "noloc": 0,
         "snr": 5.25, "region": "saarland", "ts": 1_700_000_000_000, "rx": 1_700_000_002_400}
    t = Mesh.fill_template(m, "@[{name}] {hops} ({pfad}) {km} km {snr} dB {laufzeit} s {region} {latency} {foo}")
    assert t == "@[Alice] 3 (e6,07,78,11,22) 48.2 km 5.2 dB 2.4 s #saarland 2.4 {foo}"
    assert Mesh.fill_template(m, "{path}", short=True) == "e6,07,…,11,22"
    assert Mesh.fill_template({"hops": "direkt", "path": [], "region": "-"}, "{hops} {path} {region} {km}") == "? direct no region ?"


def test_auto_reply_rules(tmp_path):
    import asyncio
    import pytest
    from backend.mesh import MeshError

    async def run():
        m = make(tmp_path)
        m.self, m.connected = {"name": "Ich"}, True
        m.channels = [{"idx": 0, "name": "Public", "secret": "8b3387e9c5cdea6a", "hash": "11"}]
        sent = []

        async def fake_send(conv, text, auto=False):
            sent.append((conv, text, auto))
        m.send_msg = fake_send
        key = "chan:Public:8b3387e9"
        with pytest.raises(MeshError):
            m.set_auto_reply(key, True, "", "", 300)
        m.set_auto_reply(key, True, "test, !ping", "pong {name} {hops}", 300)
        assert m.settings()["autoReply"][key]["words"] == ["test", "!ping"]

        def msg(frm, text, age=0):
            return {"dir": "in", "from": frm, "text": text, "ts": now_ms() - age, "rx": now_ms(), "hops": 2}
        m._auto_check("ch:0", msg("Bob", "Ist das ein Test?"))      # passt
        m._auto_check("ch:0", msg("Bob", "test"))                   # Sperrzeit je Absender
        m._auto_check("ch:0", msg("Eve", "!ping"))                  # Mindestabstand je Kanal
        m._auto_last.clear()
        m._auto_check("ch:0", msg("Eve", "@[Bob] test"))            # an jemand anderen gerichtet
        m._auto_check("ch:0", msg("Eve", "testen"))                 # kein ganzes Wort
        m._auto_check("ch:0", msg("Eve", "test", age=3600_000))     # nachgeholte alte Nachricht
        m._auto_check("ch:0", msg("Ich", "test"))                   # eigene
        m._auto_check("ch:0", msg("Eve", "@[ich] !ping"))           # an mich gerichtet
        await asyncio.sleep(5.5)
        assert sorted(sent) == [("ch:0", "pong Bob 2", True), ("ch:0", "pong Eve 2", True)]  # Verzögerung zufällig
    asyncio.run(run())


def test_push_events(tmp_path, monkeypatch):
    import asyncio
    from backend import push
    calls = []
    monkeypatch.setattr(push, "send", lambda cfg, title, text, kind, extra=None: calls.append((kind, title, text)))

    async def run():
        m = make(tmp_path)
        m.self = {"name": "Ich"}
        m.contacts = {"c0ffee" + "11" * 29: {"key": "c0ffee" + "11" * 29, "name": "Bob"}}
        m.set_push({"type": "ntfy", "url": "https://ntfy.sh/meshboard-test", "token": "geheim",
                    "events": {"dm": True, "mention": True, "watch": False, "chan": False}})
        assert "token" not in m.settings()["push"] and m.settings()["push"]["tokenSet"]
        m.set_push(m.settings()["push"] | {"token": None})  # Token bleibt erhalten
        assert m.push_cfg["token"] == "geheim"
        base = {"dir": "in", "ts": now_ms(), "rx": now_ms()}
        m.add_msg("c:c0ffee111111", base | {"from": "Bob", "text": "Hallo"})
        m.add_msg("ch:0", base | {"from": "Eve", "text": "Moin"})              # Kanal: aus
        m.add_msg("ch:0", base | {"from": "Eve", "text": "Hi @[ich]!"})        # Erwähnung
        m.add_msg("c:c0ffee111111", base | {"from": "Bob", "text": "ver", "cli": True})
        await asyncio.sleep(0.1)
        assert calls == [("dm", "Bob", "Bob: Hallo"), ("mention", "Kanal 0", "Eve: Hi @[ich]!")]
    asyncio.run(run())
    import pytest
    from backend.mesh import MeshError
    m = make(tmp_path)
    for bad in ({"type": "ntfy", "url": "ntfy.sh/x"}, {"type": "ntfy", "url": "https://ntfy.sh"}, {"type": "telegram"}, {"type": "x"}):
        with pytest.raises(MeshError):
            m.set_push(bad)


def test_node_stats_merges_hash_sizes(tmp_path):
    """Derselbe Repeater als 1-, 2- und 3-Byte-Hop erscheint in den Knoten-Details nur einmal."""
    m = make(tmp_path)
    rep = b"\x5c\x3d\x7e" + b"\x11" * 29
    m.on_raw_packet(advert(key=rep, name=b"Rep-R", hops=b""), 5.0, -90)
    for i, hs in enumerate((1, 2, 3)):
        raw = bytearray(advert(key=b"\xcd" * 32, name=b"X%d" % i, hops=rep[:hs]))
        raw[1] = (hs - 1) << 6 | 1  # ein Hop mit hs Byte
        m.on_raw_packet(bytes(raw), 2.0 + i, -100)
    m._flush()
    st = m.node_stats("cd" * 32, None, 24)
    assert [(p["hash"], p["out"], p["name"]) for p in st["peers"]] == [("5c3d7e", 3, "Rep-R")]
    assert [(v["hash"], v["count"], v["snr"], v["name"]) for v in st["via"]] == [("5c3d7e", 3, 3.0, "Rep-R")]


def test_rescan_regions(tmp_path):
    """Neuer Regionsname: Pakete im Verlauf und Nachrichten mit „Region ?code“ werden nachträglich zugeordnet."""
    import struct
    from tests.fake_companion import region_code
    m = make(tmp_path)
    pl = bytes([0x99]) + b"geheim"
    code = region_code("xyz-gibts-nicht", 5, pl)
    m.on_raw_packet(bytes([5 << 2]) + struct.pack("<HH", code, 0) + b"\x00" + pl, 4.0, -95)
    t = m.packets[-1]["t"]
    assert m.packets[-1]["region"] is None and m.region_stats["?"]["count"] == 1
    m.dev_key = "dev"
    m.add_msg("ch:0", {"dir": "in", "from": "X", "text": "hi", "ts": t, "rx": t + 500, "regionCode": format(code, "04x")})
    m._flush()
    m.set_extra_regions("xyz-gibts-nicht")
    assert m.packets[-1]["region"] == "xyz-gibts-nicht" and "?" not in m.region_stats
    assert m.store.unknown_region_packets() == []
    assert m.msgs["ch:0"][-1]["region"] == "xyz-gibts-nicht"
    m._flush()
    m2 = make(tmp_path)  # „Neustart“: Verlauf trägt die Region
    assert m2.packets[-1]["region"] == "xyz-gibts-nicht"


def test_corescope_region_names():
    """Regionsnamen aus dem Scope-Audit von CoreScope (klein, ohne '#', ohne Doppelte und Unsinn)."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from backend import lookup

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = {"repeaters": [{"declaredRegions": ["de-sl", "#SaarLorLux"]}, {"declaredRegions": ["de-sl", "<script>"]}, {}]}
            self.send_response(200 if self.path == "/api/scope-audit" else 404)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert lookup.region_names(f"http://127.0.0.1:{srv.server_port}/") == ["de-sl", "saarlorlux"]
    finally:
        srv.shutdown()
