"""Paketverlauf: speichern, nach Neustart laden, Statistik."""
from backend.mesh import Mesh
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
    assert st["repeaters"] == [{"hash": "5c", "count": 1, "name": None, "type": None}]  # eindeutig gezählt
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
