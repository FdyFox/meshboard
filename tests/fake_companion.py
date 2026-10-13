"""Simulierter MeshCore-Companion mit TCP-Firmware – für Tests und Entwicklung ohne Hardware.

    python tests/fake_companion.py [--port 5099]
    python -m backend 127.0.0.1:5099

Beantwortet die Befehle, die das Backend nutzt, und sendet laufend Funkpakete (RX-Log):
ein Advert eines Repeaters über einen Hop, nach dem zweiten Advert eine Kanalnachricht mit
Region #saarland und eine Direktnachricht; alle drei Sekunden Nachrichten aus zwei Hashtag-Räumen.
"""
import argparse
import asyncio
import hashlib
import hmac
import os
import struct
import time

from Crypto.Cipher import AES

SELF_KEY = bytes.fromhex("aa" * 32)
CONTACT_KEY = bytes.fromhex("c0ffee" + "11" * 29)  # Companion „Bob“
REP_KEY = bytes.fromhex("ab" + "22" * 31)           # Repeater „Rep-Saar“
SECRET = bytes.fromhex("8b3387e9c5cdea6ac9e5edbaa115cd72")  # Kanal „Public“
CH_HASH = hashlib.sha256(SECRET).digest()[0]
REGION = "saarland"
ACK = b"\x01\x02\x03\x04"
CAND_ROOM, CAND_REGION = "technik", "trier"  # nur über die eingebaute Namensliste erkennbar
SECRET_ROOM = "geheimraum"                     # nur über „#Raum suchen“ erkennbar


def frame(p: bytes) -> bytes:
    return b">" + struct.pack("<H", len(p)) + p


def room_payload(room: str, text: str, secret: bytes = None, ts: int = None) -> bytes:
    """Verschlüsselte Nachricht eines Hashtag-Raums (Kanal-Hash | MAC | AES-ECB)."""
    secret = secret or hashlib.sha256(("#" + room).encode()).digest()[:16]
    plain = struct.pack("<I", ts or int(time.time())) + b"\0" + text.encode()
    plain += bytes(-len(plain) % 16)
    cipher = AES.new(secret, AES.MODE_ECB).encrypt(plain)
    mac = hmac.new(secret, cipher, hashlib.sha256).digest()[:2]
    return hashlib.sha256(secret).digest()[:1] + mac + cipher


def region_code(name: str, ptype: int, payload: bytes) -> int:
    key = hashlib.sha256(("#" + name).encode()).digest()[:16]
    s = hmac.new(key, bytes([ptype]) + payload, hashlib.sha256).digest()
    return s[0] | s[1] << 8


class Companion:
    def __init__(self):
        self.name = "FakeNode"
        self.contacts = {CONTACT_KEY: ("Bob", 1), REP_KEY: ("Rep-Saar", 2)}
        self.pending: list[bytes] = []
        self.channels = {0: (b"Public", SECRET)}

    def self_info(self) -> bytes:
        return (bytes([5, 1, 22, 22]) + SELF_KEY + struct.pack("<ii", 49230000, 6990000) + bytes([0, 1, 0, 0])
                + struct.pack("<II", 869618, 62500) + bytes([8, 8]) + self.name.encode())

    def contact(self, k: bytes) -> bytes:
        n, typ = self.contacts[k]
        return (bytes([3]) + k + bytes([typ, 0, 0xFF]) + bytes(64) + n.encode().ljust(32, b"\0")
                + struct.pack("<IiiI", int(time.time()) - 60, 49250000, 7000000, 1))

    def reply(self, p: bytes) -> list[bytes]:
        c = p[0]
        if c == 0x01:  # APP_START
            return [self.self_info()]
        if c == 0x16:  # DEVICE_QUERY
            return [bytes([13, 10, 175, 8]) + struct.pack("<I", 123456) + b"01-Jan-2026".ljust(12, b"\0")
                    + b"Fake Board".ljust(40, b"\0") + b"v1.15.0".ljust(20, b"\0") + bytes([0, 0])]
        if c == 0x04:  # GET_CONTACTS
            return ([bytes([2]) + struct.pack("<I", len(self.contacts))] + [self.contact(k) for k in self.contacts]
                    + [bytes([4]) + struct.pack("<I", 1)])
        if c == 0x1F:  # GET_CHANNEL
            ch = self.channels.get(p[1])
            return [bytes([18, p[1]]) + ch[0].ljust(32, b"\0") + ch[1]] if ch else [bytes([1, 2])]
        if c == 0x40:  # GET_DEFAULT_FLOOD_SCOPE
            return [bytes([28]) + REGION.encode().ljust(31, b"\0") + hashlib.sha256(b"#" + REGION.encode()).digest()[:16]]
        if c == 0x0A:  # SYNC_NEXT_MESSAGE
            return [self.pending.pop(0)] if self.pending else [bytes([10])]
        if c == 0x14:  # GET_BATT
            return [bytes([12]) + struct.pack("<HII", 4012, 10, 100)]
        if c == 0x38:  # GET_STATS
            if p[1] == 0:
                return [bytes([24, 0]) + struct.pack("<HIHB", 4012, 3600, 0, 0)]
            if p[1] == 1:
                return [bytes([24, 1]) + struct.pack("<hbbII", -112, -90, 32, 12, 34)]
            return [bytes([24, 2]) + struct.pack("<IIIIIII", 10, 5, 3, 2, 8, 2, 0)]
        if c == 0x02:  # SEND_TXT → SENT, ACK folgt
            return [bytes([6, 0]) + ACK + struct.pack("<I", 3000)]
        if c == 0x1E:  # GET_CONTACT_BY_KEY
            k = p[1:33]
            return [self.contact(k)] if k in self.contacts else [bytes([1, 2])]
        if c == 0x08:  # SET_NAME
            self.name = p[1:].decode()
            return [bytes([0])]
        if c == 0x0F:  # REMOVE_CONTACT
            self.contacts.pop(p[1:33], None)
            return [bytes([0])]
        if c == 0x20:  # SET_CHANNEL
            self.channels[p[1]] = (p[2:34].split(b"\0", 1)[0], p[34:50])
            return [bytes([0])]
        if c in (0x03, 0x06, 0x07, 0x09, 0x0C, 0x0D, 0x0E, 0x10, 0x26, 0x36, 0x3D, 0x3F):
            return [bytes([0])]
        return [bytes([1, 1])]  # Befehl nicht unterstützt

    async def pushes(self, w):
        n = 0
        while True:
            await asyncio.sleep(1)
            n += 1
            payload = (REP_KEY + struct.pack("<I", int(time.time())) + bytes(64) + bytes([0x80 | 0x10 | 2])
                       + struct.pack("<ii", 49300000, 7100000) + b"Rep-Saar")
            raw = bytes([(4 << 2) | 1, 0x01, 0x5C]) + payload  # ADVERT, FLOOD, 1 Hop über 5c
            w.write(frame(bytes([0x88, 8 * 4, (-90) & 255]) + raw))
            if n == 2:
                pl = bytes([CH_HASH]) + os.urandom(20)
                raw = bytes([5 << 2]) + struct.pack("<HH", region_code(REGION, 5, pl), 0) + bytes([0]) + pl
                w.write(frame(bytes([0x88, 5 * 4, (-100) & 255]) + raw))
                ts = struct.pack("<I", int(time.time()))
                self.pending.append(bytes([17, 5 * 4, 0, 0, 0, 0, 0]) + ts + b"Alice: Hallo Welt")
                self.pending.append(bytes([16, 6 * 4, 0, 0]) + CONTACT_KEY[:6] + bytes([0xFF, 0]) + ts + b"Hi direkt")
                w.write(frame(bytes([0x83])))  # MSG_WAITING
            if n % 3 == 0:  # regelmäßig wiederholen
                # Raum aus der Kandidatenliste, mit Region aus der Kandidatenliste (T-FLOOD, 2 Hops)
                pl = room_payload(CAND_ROOM, "Carl: Moin aus Trier")
                raw = bytes([5 << 2]) + struct.pack("<HH", region_code(CAND_REGION, 5, pl), 0) + bytes([2, 0x5C, 0x7A]) + pl
                w.write(frame(bytes([0x88, 4 * 4, (-95) & 255]) + raw))
                # Raum, den nur „#Raum suchen“ findet (FLOOD ohne Region)
                raw = bytes([(5 << 2) | 1, 0]) + room_payload(SECRET_ROOM, "Dora: psst")
                w.write(frame(bytes([0x88, 3 * 4, (-97) & 255]) + raw))
            await w.drain()

    def echo(self, w, p):
        """Gesendete Nachricht von Repeatern weitergeleitet hören: 5c direkt (doppelt), 7a über 2 Hops."""
        if p[0] == 0x03 and p[2] in self.channels:  # Kanal: [3, Typ, Index, ts, Text]
            pl = room_payload("", self.name + ": " + p[7:].decode(), self.channels[p[2]][1], struct.unpack_from("<I", p, 3)[0])
            typ = 5
        elif p[0] == 0x02:  # Direkt: Ziel- und Absender-Byte, Rest verschlüsselt
            pl, typ = CONTACT_KEY[:1] + SELF_KEY[:1] + os.urandom(18), 2
        else:
            return
        loop = asyncio.get_running_loop()
        for dt, path in [(0.3, b"\x5c"), (0.6, b"\x5c\x7a"), (0.9, b"\x5c")]:
            raw = bytes([(typ << 2) | 1, len(path)]) + path + pl
            loop.call_later(dt, lambda raw=raw: w.write(frame(bytes([0x88, 6 * 4, (-92) & 255]) + raw)))

    async def handle(self, r, w):
        task = asyncio.create_task(self.pushes(w))
        buf = b""
        try:
            while d := await r.read(1024):
                buf += d
                while len(buf) >= 3 and buf[0] == 0x3C:
                    ln = buf[1] | buf[2] << 8
                    if len(buf) < 3 + ln:
                        break
                    p, buf = buf[3:3 + ln], buf[3 + ln:]
                    for out in self.reply(p):
                        w.write(frame(out))
                    await w.drain()
                    self.echo(w, p)
                    if p[0] == 0x02:
                        asyncio.get_running_loop().call_later(
                            1, lambda: w.write(frame(bytes([0x82]) + ACK + struct.pack("<I", 1234))))
        except ConnectionError:
            pass
        finally:
            task.cancel()


async def main(port: int):
    s = await asyncio.start_server(lambda r, w: Companion().handle(r, w), "127.0.0.1", port)
    print(f"Fake-Companion auf 127.0.0.1:{port}", flush=True)
    async with s:
        await s.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5099)
    asyncio.run(main(ap.parse_args().port))
