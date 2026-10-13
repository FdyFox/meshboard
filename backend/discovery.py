"""Hashtag-Räume erkennen und mitlesen, Regionen über Kandidatenlisten finden.

Gruppenkanal-Paket (GRP_TXT): Kanal-Hash (1 Byte) | MAC (2 Byte) | AES-128-ECB-Chiffrat
  Hashtag-Raum:  secret = sha256('#name')[:16]
  Kanal-Hash:    sha256(secret)[0]
  MAC:           HMAC-SHA256(secret, chiffrat)[:2]
  Klartext:      Zeitstempel u32 | Flags (txt_type << 2 | attempt) | 'Absender: Text' (NUL-aufgefüllt)
"""
import hashlib
import hmac
import struct

from Crypto.Cipher import AES

from .candidates import REGION_NAMES, ROOM_NAMES
from .packets import region_key, transport_code

PUBLIC_SECRET = bytes.fromhex("8b3387e9c5cdea6ac9e5edbaa115cd72")


def room_secret(name: str) -> bytes:
    return hashlib.sha256(("#" + name.lstrip("#")).encode()).digest()[:16]


def chan_hash(secret: bytes) -> str:
    return hashlib.sha256(secret).digest()[:1].hex()


def mac_ok(secret: bytes, payload: bytes) -> bool:
    """payload = Kanal-Hash | MAC | Chiffrat"""
    if len(payload) < 3 + 16:
        return False
    return hmac.new(secret, payload[3:], hashlib.sha256).digest()[:2] == payload[1:3]


def decrypt(secret: bytes, payload: bytes) -> dict | None:
    data = payload[3:]
    data = data[:len(data) - len(data) % 16]
    if not data:
        return None
    plain = AES.new(secret, AES.MODE_ECB).decrypt(data)
    ts = struct.unpack_from("<I", plain)[0]
    txt = plain[5:].split(b"\0", 1)[0].decode("utf-8", "replace")
    sender, sep, text = txt.partition(": ")
    return {"ts": ts, "txtType": plain[4] >> 2, "from": sender if sep else "?", "text": text if sep else txt}


def name_variants(name: str) -> list[str]:
    n = name.strip().lstrip("#")
    return list(dict.fromkeys([n, n.lower()])) if n else []


class RoomIndex:
    """Kanal-Hash → mögliche (Name, Secret). Eingebaute Kandidaten plus eigene Namen."""

    def __init__(self):
        self.builtin: dict[str, list] = {}
        for n in ROOM_NAMES:
            self._add(self.builtin, n)
        self._add(self.builtin, "Public", PUBLIC_SECRET)
        self.extra: dict[str, list] = {}

    @staticmethod
    def _add(idx, name, secret=None):
        secret = secret or room_secret(name)
        lst = idx.setdefault(chan_hash(secret), [])
        if all(s != secret for _, s in lst):
            lst.append((name, secret))

    def set_extra(self, names):
        self.extra = {}
        for n in names:
            for v in name_variants(n):
                self._add(self.extra, v)

    def match(self, payload: bytes):
        """(Name, Secret) des Raums, dessen Hash und MAC passen – sonst None."""
        h = payload[:1].hex()
        for name, secret in self.extra.get(h, []) + self.builtin.get(h, []):
            if mac_ok(secret, payload):
                return name, secret
        return None


CANDIDATE_REGIONS = [(n, region_key(n)) for n in REGION_NAMES]


def guess_region(ptype: int, payload: bytes, code: int, skip=()) -> str | None:
    """Region aus der Kandidatenliste suchen (nur wenn die bekannten Regionen nicht passen)."""
    for name, key in CANDIDATE_REGIONS:
        if name not in skip and transport_code(key, ptype, payload) == code:
            return name
    return None
