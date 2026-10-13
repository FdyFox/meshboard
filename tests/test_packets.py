"""Unit-Tests für Paket-Parser und Regionserkennung."""
import struct

from backend.mesh import parse_target
from backend.packets import match_region, parse_packet, region_key, transport_code
from tests.fake_companion import REGION, region_code


def advert(key=b"\xab" * 32, name=b"Rep", lat=49.3, lon=7.1, hops=b"\x5c"):
    payload = key + struct.pack("<I", 1700000000) + bytes(64) + bytes([0x80 | 0x10 | 2]) + struct.pack("<ii", int(lat * 1e6), int(lon * 1e6)) + name
    return bytes([(4 << 2) | 1, len(hops)]) + hops + payload


def test_advert():
    p = parse_packet(advert(), {})
    assert (p["ptype"], p["route"], p["hopCount"], p["path"], p["hs"]) == (4, 1, 1, ["5c"], 1)
    assert p["dec"] == {"key": "ab" * 32, "ts": 1700000000, "ntype": 2, "lat": 49.3, "lon": 7.1, "name": "Rep"}


def test_path_hash_size():
    raw = bytes([(2 << 2) | 2, (1 << 6) | 2]) + bytes.fromhex("aabbccdd") + b"\x01\x02xx"
    p = parse_packet(raw, {})
    assert (p["hs"], p["path"], p["dec"]) == (2, ["aabb", "ccdd"], {"dst": "01", "src": "02"})


def test_channel_and_region():
    pl = bytes([0x11]) + b"geheim"
    raw = bytes([5 << 2]) + struct.pack("<HH", region_code(REGION, 5, pl), 0) + b"\x00" + pl
    p = parse_packet(raw, {"11": {"name": "Public"}})
    assert p["dec"] == {"ch": "11", "chName": "Public"}
    assert match_region(p, [("andere", region_key("andere")), (REGION, region_key(REGION))]) == REGION
    assert match_region(p, [("andere", region_key("andere"))]) is None


def test_transport_code_reserved_values():
    assert transport_code(region_key("x"), 5, b"") not in (0, 0xFFFF)


def test_truncated_packet_raises():
    try:
        parse_packet(bytes([(4 << 2) | 1, 5, 1]), {})
    except ValueError:
        return
    raise AssertionError("kaputtes Paket nicht erkannt")


def test_parse_target():
    assert parse_target("192.168.1.5") == {"transport": "tcp", "address": "192.168.1.5"}
    assert parse_target("tcp:host:5003") == {"transport": "tcp", "address": "host:5003"}
    assert parse_target("/dev/ttyUSB0") == {"transport": "serial", "address": "/dev/ttyUSB0"}
    assert parse_target("ble:AA:BB") == {"transport": "ble", "address": "AA:BB"}
    assert parse_target("") is None


def test_room_roundtrip():
    from backend.discovery import RoomIndex, decrypt, room_secret
    from tests.fake_companion import room_payload
    pl = room_payload("technik", "Carl: Moin")
    idx = RoomIndex()
    name, secret = idx.match(pl)
    assert name == "technik" and secret == room_secret("technik")
    d = decrypt(secret, pl)
    assert (d["from"], d["text"]) == ("Carl", "Moin")
    # Unbekannter Raum: erst nach set_extra erkennbar, falscher MAC wird abgelehnt
    pl = room_payload("geheimraum", "Dora: psst")
    assert idx.match(pl) is None
    idx.set_extra(["#Geheimraum"])
    assert idx.match(pl)[0] == "geheimraum"
    assert idx.match(pl[:1] + b"\x00\x00" + pl[3:]) is None


def test_guess_region():
    from backend.discovery import guess_region
    pl = b"\x11" + bytes(20)
    code = region_code("trier", 5, pl)
    assert guess_region(5, pl, code) == "trier"
    assert guess_region(5, pl, code, skip={"trier"}) is None
