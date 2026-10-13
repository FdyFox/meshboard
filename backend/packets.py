"""Zerlegen empfangener Funkpakete (RX-Log) und Erkennen der Region (Transport-Code)."""
import hashlib
import hmac
import math
import struct

PT = ["REQ", "RESP", "TXT", "ACK", "ADVERT", "GRP_TXT", "GRP_DATA", "ANON_REQ",
      "PATH", "TRACE", "MULTIPART", "CONTROL", "T12", "T13", "T14", "RAW"]
ROUTES = ["T-FLOOD", "FLOOD", "DIRECT", "T-DIRECT"]


class Reader:
    """Little-Endian-Leser über bytes."""

    def __init__(self, b: bytes):
        self.b, self.o = b, 0

    def left(self):
        return len(self.b) - self.o

    def take(self, n):
        if self.o + n > len(self.b):
            raise ValueError("eof")
        v = self.b[self.o:self.o + n]
        self.o += n
        return v

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def i32(self):
        return struct.unpack("<i", self.take(4))[0]

    def rest(self):
        return self.take(max(0, self.left()))


def has_pos(n) -> bool:
    if not n:
        return False
    lat, lon = n.get("lat"), n.get("lon")
    return (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            and not (lat == 0 and lon == 0) and abs(lat) <= 90 and abs(lon) <= 180)


def hav(a, b, c, d) -> float:
    """Entfernung in km zwischen (a,b) und (c,d)."""
    r = math.pi / 180
    x = math.sin((c - a) * r / 2) ** 2 + math.cos(a * r) * math.cos(c * r) * math.sin((d - b) * r / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(x))


def parse_packet(raw: bytes, chan_by_hash: dict) -> dict:
    """Header, Transport-Codes, Pfad und Nutzdaten eines Pakets zerlegen."""
    p = {"len": len(raw)}
    o = 0
    h = raw[o]
    o += 1
    p["route"] = h & 3
    p["ptype"] = (h >> 2) & 15
    p["ver"] = h >> 6
    p["tc"] = None
    if p["route"] in (0, 3):
        a, b = struct.unpack_from("<HH", raw, o)
        p["tc"] = [a, b]
        o += 4
    pl = raw[o]
    o += 1
    p["plByte"] = pl
    p["hs"] = (pl >> 6) + 1
    p["hopCount"] = pl & 63
    p["path"] = [raw[o + i * p["hs"]:o + (i + 1) * p["hs"]].hex() for i in range(p["hopCount"])]
    o += p["hopCount"] * p["hs"]
    if o > len(raw):
        raise ValueError("kaputt")
    p["_payload"] = raw[o:]
    p["dec"] = decode_payload(p["ptype"], p["_payload"], chan_by_hash)
    return p


def decode_payload(ptype: int, b: bytes, chan_by_hash: dict) -> dict:
    d = {}
    try:
        if ptype == 4:  # ADVERT
            if len(b) < 101:
                return d
            r = Reader(b)
            d["key"] = r.take(32).hex()
            d["ts"] = r.u32()
            r.take(64)
            fl = r.u8()
            d["ntype"] = fl & 15
            if fl & 0x10:
                d["lat"] = r.i32() / 1e6
                d["lon"] = r.i32() / 1e6
            if fl & 0x20:
                r.u16()
            if fl & 0x40:
                r.u16()
            if fl & 0x80:
                d["name"] = r.rest().split(b"\0", 1)[0].decode("utf-8", "replace")
        elif ptype == 3:
            if len(b) >= 4:
                d["ack"] = b[:4].hex()
        elif ptype in (0, 1, 2, 8):
            if len(b) >= 2:
                d["dst"] = b[0:1].hex()
                d["src"] = b[1:2].hex()
        elif ptype == 7:
            if len(b) >= 33:
                d["dst"] = b[0:1].hex()
                d["srcKey"] = b[1:33].hex()
        elif ptype in (5, 6):
            if len(b) >= 1:
                d["ch"] = b[0:1].hex()
                ch = chan_by_hash.get(d["ch"])
                if ch:
                    d["chName"] = ch["name"]
        elif ptype == 9:
            if len(b) >= 9:
                r = Reader(b)
                d["tag"] = format(r.u32(), "x")
                d["auth"] = r.u32()
                d["flags"] = r.u8()
                d["trace"] = r.rest().hex()
    except (ValueError, struct.error):
        pass
    return d


def region_key(name: str) -> bytes:
    """Schlüssel einer Region: SHA-256('#name'), erste 16 Byte."""
    return hashlib.sha256(("#" + name.lstrip("#")).encode()).digest()[:16]


def transport_code(key: bytes, ptype: int, payload: bytes) -> int:
    sig = hmac.new(key, bytes([ptype]) + payload, hashlib.sha256).digest()
    code = sig[0] | (sig[1] << 8)
    if code == 0:
        return 1
    if code == 0xFFFF:
        return 0xFFFE
    return code


def match_region(p: dict, regions: list) -> str | None:
    """Region (Name) zum Transport-Code des Pakets suchen."""
    if not p.get("tc") or not regions:
        return None
    for name, key in regions:
        if transport_code(key, p["ptype"], p["_payload"]) == p["tc"][0]:
            return name
    return None


def public(p: dict) -> dict:
    """Paket ohne interne Felder (für JSON)."""
    return {k: v for k, v in p.items() if not k.startswith("_")}


def packet_hash(ptype: int, payload: bytes) -> str:
    """Gleich für alle Empfänge desselben Pakets (der Pfad wächst unterwegs, die Nutzdaten nicht)."""
    return hashlib.sha256(bytes([ptype]) + payload).digest()[:8].hex()


PREAMBLE = 16  # Präambel-Symbole (Annahme für MeshCore; beeinflusst die Schätzung nur leicht)


def airtime_ms(length: int, sf: int, bw_khz: float, cr: int) -> float | None:
    """Sendezeit eines LoRa-Pakets nach der Semtech-Formel (expliziter Header, CRC an)."""
    if not (sf and bw_khz and cr):
        return None
    cr = cr - 4 if cr >= 5 else cr  # 5..8 (4/5..4/8) oder 1..4
    tsym = (2 ** sf) / (bw_khz * 1000)
    de = 1 if tsym > 0.016 else 0
    n = 8 + max(math.ceil((8 * length - 4 * sf + 28 + 16) / (4 * (sf - 2 * de))) * (cr + 4), 0)
    return round(((PREAMBLE + 4.25) + n) * tsym * 1000, 2)
