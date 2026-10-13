"""Verbindung zum MeshCore-Companion und gesamter App-Zustand.

Der Server ist der einzige Client der Node. Browser bekommen den Zustand als
Snapshot und danach Live-Events über den WebSocket (siehe api.py).
"""
import asyncio
import csv
import io
import json
import logging
import re
import struct
import time
import uuid
from datetime import datetime, timezone

from meshcore import EventType, MeshCore

from .discovery import PUBLIC_SECRET, RoomIndex, decrypt, guess_region, mac_ok, name_variants, room_secret
from .packets import PT, ROUTES, airtime_ms, has_pos, hav, match_region, packet_hash, parse_packet, public, region_key
from .store import MAX_MSGS, Store, bucket_ms

log = logging.getLogger("mcw")

ERRS = {1: "Befehl nicht unterstützt", 2: "nicht gefunden", 3: "Tabelle voll",
        4: "falscher Zustand", 5: "Dateifehler", 6: "ungültiger Wert"}
MAX_PKTS = 3000      # Pakete im Speicher
SNAPSHOT_PKTS = 1000  # Pakete im Snapshot für neue Browser
MAX_TXT = 150        # Byte pro Nachricht
MAX_LOG = 300        # Zeilen Protokoll-Log
DEFAULT_ACK = "@[{name}] | received in DE-66346 | {hops} 🐇 ({path}) | {km} km"  # Vorlage für die Schnellantwort
RETRY_S = 15         # Wartezeit nach fehlgeschlagenem Verbindungsversuch
SAMPLE_S = 300       # Gerätewerte (Rauschen, Batterie, Sendezeit) alle 5 Minuten speichern

# Duty-Cycle-Grenzen im EU-868-Band (ETSI EN 300 220 / ERC REC 70-03), Frequenzen in MHz
DUTY_BANDS = [(863.0, 865.0, 0.1), (865.0, 868.0, 1.0), (868.0, 868.6, 1.0), (868.7, 869.2, 0.1),
              (869.4, 869.65, 10.0), (869.7, 870.0, 1.0)]


def duty_limit(freq):
    return next((lim for lo, hi, lim in DUTY_BANDS if freq and lo <= freq <= hi), None)


class MeshError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


def now_ms():
    return int(time.time() * 1000)


def parse_target(s: str) -> dict | None:
    """'tcp:host[:port]', 'serial:/dev/ttyUSB0', 'ble:AA:BB:…' oder nur 'host[:port]'."""
    s = (s or "").strip()
    if not s:
        return None
    kind, sep, rest = s.partition(":")
    if sep and kind.lower() in ("tcp", "serial", "ble"):
        return {"transport": kind.lower(), "address": rest.strip()}
    if s.startswith("/dev/") or re.fullmatch(r"COM\d+", s, re.I):
        return {"transport": "serial", "address": s}
    return {"transport": "tcp", "address": s}


def target_str(t: dict | None) -> str:
    return f"{t['transport']}:{t['address']}" if t else ""


def _pl(p: dict) -> int:
    """Pfadlängen-Byte aus den Feldern der meshcore-Bibliothek rekonstruieren."""
    if p.get("path_len") == 255 or p.get("path_hash_mode", 0) < 0:
        return 255
    return ((p.get("path_hash_mode") or 0) << 6) | (p.get("path_len") or 0)


def norm_self(p: dict) -> dict:
    tx = p["tx_power"]
    return {
        "name": p["name"], "key": p["public_key"], "lat": p["adv_lat"], "lon": p["adv_lon"],
        "tx": tx - 256 if tx > 127 else tx, "maxTx": p["max_tx_power"], "advType": p["adv_type"],
        "multiAcks": p["multi_acks"], "locPolicy": p["adv_loc_policy"],
        "telem": p["telemetry_mode_base"] | (p["telemetry_mode_loc"] << 2) | (p["telemetry_mode_env"] << 4),
        "manualAdd": 1 if p["manual_add_contacts"] else 0,
        "freq": p["radio_freq"], "bw": p["radio_bw"], "sf": p["radio_sf"], "cr": p["radio_cr"],
    }


def norm_dev(p: dict) -> dict:
    return {"fw": p.get("fw ver"), "maxContacts": p.get("max_contacts"), "maxChannels": p.get("max_channels"),
            "build": p.get("fw_build"), "model": p.get("model"), "version": p.get("ver"),
            "pathHashMode": p.get("path_hash_mode"), "repeat": p.get("repeat")}


def norm_contact(c: dict, saved: bool) -> dict:
    flood = c["out_path_len"] < 0
    mode = 0 if flood else c["out_path_hash_mode"]
    hs = 2 * (mode + 1)
    path = c.get("out_path") or ""
    return {
        "key": c["public_key"], "name": c["adv_name"], "type": c["type"], "flags": c["flags"],
        "outPathLen": 255 if flood else (mode << 6) | c["out_path_len"], "flood": flood,
        "hops": [] if flood else [path[i:i + hs] for i in range(0, len(path), hs)],
        "lat": c["adv_lat"], "lon": c["adv_lon"], "lastAdvert": c["last_advert"], "saved": saved,
    }


class Mesh:
    def __init__(self, store: Store, target: dict | None = None, packet_days: int = 365):
        self.store = store
        self.clients: set[asyncio.Queue] = set()
        self.mc: MeshCore | None = None
        self.lock: asyncio.Lock | None = None
        self.target = target or store.get("target")
        self.want = bool(self.target)  # Verbindung gewünscht (automatisch wiederherstellen)
        self.connected = self.connecting = False
        self.error = self.label = ""
        self.self: dict | None = None
        self.dev: dict | None = None
        self.radio: dict = {}
        self.scope: dict | None = None
        self.contacts: dict = {}
        self.raw_contacts: dict = {}  # Kontakte im Format der Bibliothek (für add_contact)
        self.nodes: dict = store.load_nodes()
        self.channels: list = store.get("channels", [])  # zuletzt vom Gerät gelesen (Namen auch ohne Verbindung)
        self.packets: list = []
        self.pkt_seq = 0
        self.neighbors: dict = {}
        self.stats = {"total": 0, "byType": {}, "minutes": {}}
        self.acks: dict = {}
        self.dev_key = store.get("lastDev")
        self.msgs: dict = store.load_msgs(self.dev_key) if self.dev_key else {}
        self.chan_region: dict = store.get("chanRegion", {})
        self.extra_regions: str = store.get("extraRegions", "")
        # Benachrichtigung (ungelesen-Markierung und Desktop-Meldung) pro Unterhaltung: 'mention' oder 'off' (Standard: alle Nachrichten)
        self.notify: dict = store.get("notify", {})
        self.ack_template: str = store.get("ackTemplate", DEFAULT_ACK)
        self.regions: list = []
        self.log_on = False
        self.log: list = []
        # Gehörte Hashtag-Räume (nicht auf dem Gerät), eigene Raumnamen, Statistik pro Kanal-Hash und Region
        self.rooms: dict = store.get("rooms", {})
        self.watch_rooms: list = store.get("watchRooms", [])
        self.room_index = RoomIndex()
        self.room_index.set_extra(self.watch_rooms)
        self.chan_stats: dict = {}
        self.region_stats: dict = {}
        self._rooms_dirty = False
        # Paketverlauf in SQLite (Statistik); Live-Traffic nach Neustart wiederherstellen
        self.packet_days = packet_days
        self._new_packets: list = []
        self._last_prune = 0
        self._last_sample = 0
        self._load_packets()
        self._dirty_nodes: set = set()
        self._dirty_msgs: dict = {}
        self._syncing = False
        self._tasks: set = set()

    # ================= Infrastruktur =================
    def spawn(self, coro):
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    def emit(self, t: str, **data):
        msg = {"t": t, **data}
        for q in self.clients:
            q.put_nowait(msg)

    def toast(self, msg: str, kind: str = ""):
        self.emit("toast", msg=msg, kind=kind)

    def status(self) -> dict:
        return {
            "connected": self.connected, "connecting": self.connecting, "error": self.error,
            "label": self.label, "target": self.target, "want": self.want,
            "self": self.self, "dev": self.dev, "radio": self.radio, "scope": self.scope,
            "regions": [n for n, _ in self.regions],
        }

    def emit_status(self):
        self.emit("status", status=self.status())

    def snapshot(self) -> dict:
        return {
            "status": self.status(),
            "contacts": list(self.contacts.values()),
            "nodes": list(self.nodes.values()),
            "channels": self.channels,
            "packets": [public(p) for p in self.packets[-SNAPSHOT_PKTS:]],
            "neighbors": self.neighbors,
            "stats": self.stats,
            "msgs": self.msgs,
            "settings": self.settings(),
            "rooms": list(self.rooms.values()),
            "watchRooms": self.watch_rooms,
            "chanStats": self.chan_stats,
            "regionStats": self.region_stats,
            "log": self.log if self.log_on else [],
            "logOn": self.log_on,
            "maxTxt": MAX_TXT,
        }

    def settings(self) -> dict:
        return {"chanRegion": self.chan_region, "extraRegions": self.extra_regions, "notify": self.notify,
                "ackTemplate": self.ack_template, "ackDefault": DEFAULT_ACK}

    def set_ack_template(self, s: str):
        """Vorlage der Schnellantwort; leer = Standard."""
        s = (s or "").strip() or DEFAULT_ACK
        if len(s.encode()) > MAX_TXT:
            raise MeshError(f"Vorlage zu lang (max. {MAX_TXT} Byte)")
        self.ack_template = s
        self.store.set("ackTemplate", s)
        self.emit("settings", settings=self.settings())

    def set_notify(self, key: str, mode: str):
        """Wann eine Unterhaltung benachrichtigt (ungelesen-Markierung, Desktop-Meldung): 'all', 'mention' oder 'off'."""
        if mode not in ("all", "mention", "off") or not key:
            raise MeshError("ungültiger Wert")
        if mode == "all":
            self.notify.pop(key, None)
        else:
            self.notify[key] = mode
        self.store.set("notify", self.notify)
        self.emit("settings", settings=self.settings())

    async def start(self):
        self.lock = asyncio.Lock()
        self.build_regions()
        self.spawn(self._saver())
        self.spawn(self._supervisor())
        self.spawn(self._stat_loop())

    async def shutdown(self):
        self.want = False
        await self._close()
        self._flush()

    async def _saver(self):
        while True:
            await asyncio.sleep(2)
            try:
                self._flush()
            except Exception:
                log.exception("Speichern fehlgeschlagen")

    def _flush(self):
        if self._dirty_nodes:
            keys, self._dirty_nodes = self._dirty_nodes, set()
            self.store.save_nodes([self.nodes[k] for k in keys if k in self.nodes])
        if self._rooms_dirty:
            self._rooms_dirty = False
            self.store.set("rooms", self.rooms)
        if self._new_packets:
            rows, self._new_packets = self._new_packets, []
            self.store.save_packets(rows)
        if time.time() - self._last_prune > 3600:
            self._last_prune = time.time()
            self.store.prune_device_stats(now_ms() - self.packet_days * 86400000)
            n = self.store.prune_packets(now_ms() - self.packet_days * 86400000)
            if n:
                log.info("%d Pakete älter als %d Tage gelöscht", n, self.packet_days)
        if self._dirty_msgs and self.dev_key:
            items, self._dirty_msgs = list(self._dirty_msgs.values()), {}
            self.store.save_msgs(self.dev_key, items)

    async def _supervisor(self):
        """Verbindung herstellen und nach Abbruch automatisch wiederherstellen."""
        while True:
            if self.want and self.target and not self.connected and not self.connecting:
                try:
                    await self.connect()
                except MeshError:
                    await asyncio.sleep(RETRY_S)
            await asyncio.sleep(3)

    async def _stat_loop(self):
        while True:
            await asyncio.sleep(30)
            if self.connected:
                await self.refresh_stats()

    # ================= Befehle =================
    def _mc(self) -> MeshCore:
        if not self.mc or not self.connected and not self.connecting:
            raise MeshError("nicht verbunden")
        return self.mc

    @staticmethod
    def _check(ev):
        if ev is None:
            raise MeshError("keine Antwort")
        if ev.type == EventType.ERROR:
            p = ev.payload or {}
            code = p.get("error_code")
            if code:
                raise MeshError(ERRS.get(code, f"Fehler {code}"), code)
            reason = p.get("reason") or p.get("error") or "Fehler"
            raise MeshError("Zeitüberschreitung" if reason in ("timeout", "no_event_received") else str(reason))
        return ev

    async def _cmd(self, data: bytes, expect=(EventType.OK, EventType.DISABLED), timeout=None):
        """Rohen Befehl senden (ein Befehl gleichzeitig) und auf die Antwort warten."""
        mc = self._mc()
        async with self.lock:
            ev = await mc.commands.send(bytes(data), [*expect, EventType.ERROR], timeout=timeout)
        return self._check(ev)

    async def _lib(self, name: str, *args, **kw):
        """Befehl der meshcore-Bibliothek aufrufen (ein Befehl gleichzeitig)."""
        mc = self._mc()
        async with self.lock:
            ev = await getattr(mc.commands, name)(*args, **kw)
        return self._check(ev)

    # ================= Verbindung =================
    async def connect(self, target: dict | None = None):
        if target:
            if self.connected or self.connecting:
                await self.disconnect()
            self.target = target
            self.store.set("target", target)
        if not self.target:
            raise MeshError("Keine Node konfiguriert")
        if self.connected or self.connecting:
            return
        self.want = True
        self.connecting = True
        self.error = ""
        self.emit_status()
        try:
            self_info = await self._open()
            dq = await self._lib("send_device_query")
            self.dev = norm_dev(dq.payload)
            self.self = norm_self(self_info)
        except Exception as e:
            msg = str(e) if isinstance(e, MeshError) else f"Verbinden fehlgeschlagen: {e}"
            log.warning("[!] %s", msg)
            await self._close()
            self.error = msg
            self.connecting = False
            self.emit_status()
            raise MeshError(msg)
        self.connected = True
        self.connecting = False
        log.info("[+] verbunden mit %s (%s)", self.self["name"], self.label)
        dev_key = self.self["key"][:16]
        if dev_key != self.dev_key:
            self._flush()
            self.dev_key = dev_key
            self.store.set("lastDev", dev_key)
            self.msgs = self.store.load_msgs(dev_key)
            self.emit("msgs", msgs=self.msgs)
        self.emit_status()
        self.toast("Verbunden mit " + self.self["name"], "ok")
        self.spawn(self._init_session())

    def _backfill_packets(self):
        """Paket-Hash, Sendezeit und Pfad für ältere gespeicherte Pakete nachtragen."""
        s, total = self.self or {}, 0
        while rows := self.store.packets_missing():
            upd = []
            for pid, length, data in rows:
                p = json.loads(data)
                try:
                    payload = parse_packet(bytes.fromhex(p.get("raw", "")), {})["_payload"]
                except (IndexError, ValueError, struct.error):
                    payload = bytes.fromhex(p.get("raw", ""))
                air = airtime_ms(length or 0, s.get("sf"), s.get("bw"), s.get("cr")) or 0.0
                upd.append((packet_hash(p.get("ptype", 15), payload), air, " ".join(p.get("path") or []), pid))
            self.store.update_packets(upd)
            total += len(upd)
        if total:
            log.info("%d ältere Pakete für die Statistik ergänzt", total)

    async def _init_session(self):
        try:
            await self._lib("set_time", int(time.time()))
        except MeshError:
            pass
        self._flush()
        self._backfill_packets()
        for step in (self.load_contacts, self.load_channels, self.load_scope, self.sync_messages, self.refresh_stats):
            if not self.connected:
                return
            try:
                await step()
            except MeshError as e:
                log.warning("[!] %s: %s", step.__name__, e)

    async def _open(self) -> dict:
        t = self.target
        tr, addr = t["transport"], t["address"]
        try:
            if tr == "tcp":
                host, _, port = addr.rpartition(":") if ":" in addr else (addr, "", "")
                mc = await asyncio.wait_for(MeshCore.create_tcp(host, int(port or 5000), default_timeout=8), 20)
                self.label = "TCP " + addr
            elif tr == "serial":
                mc = await asyncio.wait_for(MeshCore.create_serial(addr, 115200, default_timeout=8), 20)
                self.label = "USB " + addr
            elif tr == "ble":
                mc = await asyncio.wait_for(MeshCore.create_ble(addr or None, default_timeout=8), 40)
                self.label = "BLE " + (addr or "")
            else:
                raise MeshError(f"Unbekannte Verbindungsart: {tr}")
        except (OSError, asyncio.TimeoutError, ConnectionError) as e:
            raise MeshError(f"Node {addr} nicht erreichbar ({e or type(e).__name__})")
        if mc is None:
            raise MeshError("Gerät antwortet nicht wie ein MeshCore-Companion. Passende Companion-Firmware (USB/BLE/WiFi) geflasht?")
        self.mc = mc
        self._hook_log(mc)
        self._subscribe(mc)
        return mc.self_info

    async def disconnect(self):
        """Vom Nutzer getrennt: nicht automatisch wiederverbinden."""
        self.want = False
        await self._close()
        self.emit_status()

    async def _close(self):
        mc, self.mc = self.mc, None
        was = self.connected
        self.connected = self.connecting = False
        self.acks.clear()
        if mc:
            try:
                await asyncio.wait_for(mc.disconnect(), 5)
            except Exception as e:
                log.debug("disconnect: %r", e)
        if was:
            log.info("[-] getrennt")

    async def _lost(self, msg="Verbindung verloren"):
        if not self.connected:
            return
        await self._close()
        self.error = msg
        self.emit_status()
        self.toast(msg, "err")

    def _hook_log(self, mc: MeshCore):
        """Rohe Frames für das Protokoll-Log mitschneiden."""
        reader, cm = mc._reader, mc.connection_manager
        orig_rx, orig_tx = reader.handle_rx, cm.send

        async def rx(data):
            self._log_frame("RX", data)
            return await orig_rx(data)

        async def tx(data):
            self._log_frame("TX", data)
            return await orig_tx(data)

        reader.handle_rx, cm.send = rx, tx

    def _log_frame(self, d, data):
        if not self.log_on:
            return
        line = f"{datetime.now().strftime('%H:%M:%S')} {d} {bytes(data).hex()}"
        self.log.append(line)
        del self.log[:-MAX_LOG]
        self.emit("log", line=line)

    def set_log(self, on: bool):
        self.log_on = on
        if not on:
            self.log = []

    # ================= Events der Bibliothek =================
    def _subscribe(self, mc: MeshCore):
        # Synchrone Handler: laufen in Empfangsreihenfolge (Funkpaket vor zugehöriger Nachricht).
        h = {
            EventType.RX_LOG_DATA: self._on_rx_log,
            EventType.CONTACT_MSG_RECV: self._on_contact_msg,
            EventType.CHANNEL_MSG_RECV: self._on_channel_msg,
            EventType.MESSAGES_WAITING: lambda ev: self.spawn(self.sync_messages()),
            EventType.ADVERTISEMENT: lambda ev: self.spawn(self.refresh_contact(ev.payload["public_key"])),
            EventType.PATH_UPDATE: lambda ev: self.spawn(self.refresh_contact(ev.payload["public_key"])),
            EventType.NEW_CONTACT: lambda ev: self._upsert_contact(ev.payload, False),
            EventType.NEXT_CONTACT: lambda ev: self._upsert_contact(ev.payload, True),
            EventType.ACK: self._on_ack,
            EventType.CONTACT_DELETED: lambda ev: self._contact_gone(ev.payload.get("pubkey", "")),
            EventType.CONTACTS_FULL: lambda ev: self.toast("Kontaktspeicher des Geräts ist voll", "err"),
            EventType.DISCONNECTED: lambda ev: self.spawn(self._lost()) if self.mc is mc else None,
        }
        for et, fn in h.items():
            mc.subscribe(et, self._safe(fn))

    @staticmethod
    def _safe(fn):
        def wrap(ev):
            try:
                fn(ev)
            except Exception:
                log.exception("Fehler bei %s", ev.type)
        return wrap

    # ================= Kontakte & Knoten =================
    async def load_contacts(self):
        ev = await self._lib("get_contacts", timeout=10)
        keys = set(ev.payload.keys())
        for k in [k for k in self.contacts if k not in keys]:
            self.contacts.pop(k, None)
            self.raw_contacts.pop(k, None)
        for c in ev.payload.values():
            self._upsert_contact(c, True, emit=False)
        self.emit("contacts", contacts=list(self.contacts.values()))
        self.emit("nodes", nodes=[self.nodes[k] for k in keys if k in self.nodes])

    def _upsert_contact(self, c: dict, saved: bool, emit=True):
        key = c["public_key"]
        old = self.contacts.get(key)
        nc = norm_contact(c, saved or bool(old and old.get("saved")))
        self.contacts[key] = nc
        self.raw_contacts[key] = c
        n = self.nodes.get(key) or {"key": key}
        n["name"] = nc["name"] or n.get("name")
        n["type"] = nc["type"]
        n["inContacts"] = True
        if has_pos(nc):
            n["lat"], n["lon"] = nc["lat"], nc["lon"]
        if nc["lastAdvert"] and nc["lastAdvert"] > (n.get("advTs") or 0):
            n["advTs"] = nc["lastAdvert"]
        self.nodes[key] = n
        self._dirty_nodes.add(key)
        if emit:
            self.emit("contact", c=nc)
            self.emit("node", n=n)

    def _contact_gone(self, key: str):
        self.contacts.pop(key, None)
        self.raw_contacts.pop(key, None)
        n = self.nodes.get(key)
        if n:
            n["inContacts"] = False
            self._dirty_nodes.add(key)
        self.emit("contact_del", key=key)

    async def refresh_contact(self, key: str):
        try:
            await self._lib("get_contact_by_key", bytes.fromhex(key))  # Antwort kommt als NEXT_CONTACT
        except (MeshError, ValueError):
            pass

    def _contact_by_prefix(self, p: str):
        return next((c for c in self.contacts.values() if c["key"].startswith(p)), None)

    def _node_name(self, h: str):
        names = [n.get("name") or "?" for n in self.nodes.values() if n["key"].startswith(h)]
        return names[0] if len(names) == 1 else " / ".join(names) if names else None

    async def reset_path(self, key):
        await self._lib("reset_path", bytes.fromhex(key))
        await self.refresh_contact(key)

    async def share_contact(self, key):
        await self._lib("share_contact", bytes.fromhex(key))

    async def remove_contact(self, key):
        await self._lib("remove_contact", bytes.fromhex(key))
        self._contact_gone(key)

    async def add_contact(self, key):
        c = self.raw_contacts.get(key)
        if not c:
            raise MeshError("Kontakt unbekannt")
        await self._lib("add_contact", c)
        self.contacts[key]["saved"] = True
        self.emit("contact", c=self.contacts[key])

    # ================= Kanäle =================
    async def load_channels(self):
        chans = []
        mx = (self.dev or {}).get("maxChannels") or 8
        for i in range(mx):
            try:
                ev = await self._lib("get_channel", i)
            except MeshError as e:
                if e.code == 2 and i > 0:
                    break
                continue
            p = ev.payload
            sec = bytes(p["channel_secret"])
            if not p["channel_name"] and not any(sec):
                continue
            chans.append({"idx": p["channel_idx"], "name": p["channel_name"] or f"Kanal {p['channel_idx']}",
                          "secret": sec.hex(), "hash": p["channel_hash"]})
        self.channels = chans
        self.store.set("channels", chans)
        self.emit("channels", channels=chans)
        # Gehörte Räume, die jetzt auf dem Gerät sind, samt Verlauf in den Kanal übernehmen
        for c in chans:
            for name in [n for n in self.rooms if self._room_secret(n).hex() == c["secret"]]:
                self._merge_room(name, c["idx"])

    def _chan(self, idx: int):
        return next((c for c in self.channels if c["idx"] == idx), None)

    @staticmethod
    def _chan_id(ch):
        return f"{ch['name']}:{ch['secret'][:8]}" if ch else ""

    def chan_region_of(self, ch) -> str:
        return self.chan_region.get(self._chan_id(ch), "") if ch else ""

    # ================= Region / Flood-Scope =================
    def known_region_names(self) -> list:
        names = []
        if self.scope and self.scope.get("name"):
            names.append(self.scope["name"])
        names += [x.strip().lstrip("#") for x in self.extra_regions.split(",") if x.strip().lstrip("#")]
        names += [v for v in self.chan_region.values() if v and v != "-"]
        return list(dict.fromkeys(names))

    def build_regions(self):
        out = []
        for n in self.known_region_names():
            sc = self.scope
            key = bytes.fromhex(sc["key"]) if sc and sc.get("name") == n and sc.get("key") else region_key(n)
            out.append((n, key))
        self.regions = out

    async def apply_scope(self, v: str):
        """Sende-Region für die nächsten Flood-Pakete ('' = Gerätestandard, '-' = ohne Region, sonst Name)."""
        if not v:
            return await self._cmd(bytes([54, 0]))
        if v == "-":
            return await self._cmd(bytes([54, 1]))
        return await self._cmd(bytes([54, 0]) + region_key(v))

    async def load_scope(self):
        try:
            ev = await self._cmd(bytes([64]), (EventType.DEFAULT_FLOOD_SCOPE,))
            p = ev.payload
            self.scope = {"name": p.get("scope_name", "").lstrip("#"), "key": p.get("scope_key")}
        except MeshError:
            self.scope = None
        self.build_regions()
        self.emit_status()

    async def set_scope(self, name: str):
        name = (name or "").strip().lstrip("#")
        try:
            if not name:
                await self._cmd(bytes([63]))
            else:
                nb = name.encode()
                if len(nb) > 30:
                    raise MeshError("Name zu lang (max. 30 Zeichen)")
                await self._cmd(bytes([63]) + nb.ljust(31, b"\0") + region_key(name))
        except MeshError as e:
            raise MeshError(f"Region setzen fehlgeschlagen: {e}" + (" (Firmware zu alt?)" if e.code == 1 else ""), e.code)
        await self.load_scope()

    async def set_hash_mode(self, m: int):
        try:
            await self._cmd(bytes([61, 0, m]))
        except MeshError as e:
            raise MeshError(f"Fehlgeschlagen: {e}" + (" (Firmware zu alt?)" if e.code == 1 else ""), e.code)
        if self.dev:
            self.dev["pathHashMode"] = m
        self.emit_status()

    def set_chan_region(self, idx: int, v: str) -> str:
        ch = self._chan(idx)
        if not ch:
            raise MeshError("Kanal unbekannt")
        v = (v or "").strip().lstrip("#") if v != "-" else v
        if v:
            self.chan_region[self._chan_id(ch)] = v
        else:
            self.chan_region.pop(self._chan_id(ch), None)
        self.store.set("chanRegion", self.chan_region)
        self._regions_changed()
        return ch["name"]

    def set_extra_regions(self, s: str):
        self.extra_regions = s or ""
        self.store.set("extraRegions", self.extra_regions)
        self._regions_changed()

    def save_region(self, name: str):
        """Gehörte Region dauerhaft zu den bekannten Regionen („Weitere Regionen“) hinzufügen."""
        name = (name or "").strip().lstrip("#")
        if not name:
            raise MeshError("Regionsnamen eingeben")
        if name in self.known_region_names():
            return
        self.set_extra_regions(", ".join(x for x in [self.extra_regions.strip(" ,"), name] if x))

    def _regions_changed(self):
        self.build_regions()
        for p in self.packets:
            if p.get("tc") and not p.get("region"):
                p["region"] = self._find_region(p)
        self.emit("settings", settings=self.settings())
        self.emit_status()
        self.emit("packets", packets=[public(p) for p in self.packets[-SNAPSHOT_PKTS:]])

    def _find_region(self, p) -> str | None:
        """Erst bekannte Regionen, dann die Kandidatenliste."""
        return match_region(p, self.regions) or guess_region(
            p["ptype"], p["_payload"], p["tc"][0], skip={n for n, _ in self.regions})

    def _region_stat(self, p) -> list:
        name = p.get("region") or "?"
        e = self.region_stats.setdefault(name, {"count": 0, "nodes": []})
        e["count"] += 1
        e["last"] = p["t"]
        d = p["dec"]
        label = d.get("name") or (self._node_name(p["path"][-1]) or p["path"][-1] if p["path"] else None)
        if label:
            e["nodes"] = ([label] + [x for x in e["nodes"] if x != label])[:5]
        return [name, e]

    # ================= Hashtag-Räume =================
    @staticmethod
    def _room_secret(name: str) -> bytes:
        return PUBLIC_SECRET if name == "Public" else room_secret(name)

    def _on_group_packet(self, p, rescan=False):
        """Gruppenpaket einem Kanal des Geräts oder einem gehörten Hashtag-Raum zuordnen."""
        pl, d = p["_payload"], p["dec"]
        h = pl[:1].hex()
        dev = next((c for c in self.channels if c["hash"] == h and mac_ok(bytes.fromhex(c["secret"]), pl)), None)
        d.pop("chName", None)
        name = secret = None
        if dev:
            d["chName"] = dev["name"]
        else:
            m = self.room_index.match(pl)
            if m:
                name, secret = m
                d["chName"] = name
                d["room"] = name
        cs = None
        if not rescan:
            cs = self.chan_stats.setdefault(h, {"hash": h, "count": 0})
            cs["count"] += 1
            cs["last"] = p["t"]
            if d.get("chName"):
                cs["name"] = d["chName"]
        if name and p["ptype"] == 5:
            self._room_msg(p, name, secret)
        return cs

    def _room_msg(self, p, name, secret):
        dec = decrypt(secret, p["_payload"])
        if not dec:
            return
        room = self.rooms.setdefault(name, {"name": name, "hash": p["_payload"][:1].hex(), "count": 0, "first": p["t"]})
        room["count"] += 1
        room["last"] = max(room.get("last") or 0, p["t"])
        self._rooms_dirty = True
        m = {"dir": "in", "from": dec["from"], "text": dec["text"], "ts": dec["ts"] * 1000, "rx": p["t"], "snr": p["snr"],
             "hops": p["hopCount"], "hashBytes": p["hs"], "cli": dec["txtType"] == 1}
        if p.get("tc"):
            m["regionCode"] = format(p["tc"][0], "04x")
            if p.get("region"):
                m["region"] = p["region"]
        else:
            m["region"] = "-"
        m["path"] = p["path"]
        self._route(m, self._node_by_name(m["from"]))
        self.add_msg("room:" + name, m)
        self.emit("room", room=room)

    def probe_room(self, name: str) -> int:
        """Eigenen Raumnamen beobachten und die bisher gehörten Pakete danach durchsuchen."""
        variants = name_variants(name)
        if not variants:
            raise MeshError("Raumnamen eingeben")
        if variants[0] not in self.watch_rooms:
            self.watch_rooms.append(variants[0])
            self.store.set("watchRooms", self.watch_rooms)
            self.room_index.set_extra(self.watch_rooms)
        found = 0
        for p in self.packets:
            if p["ptype"] == 5 and p.get("_payload") and not p["dec"].get("chName"):
                self._on_group_packet(p, rescan=True)
                if p["dec"].get("room"):
                    found += 1
        self.emit("rooms", rooms=list(self.rooms.values()), watch=self.watch_rooms)
        if found:
            self.emit("packets", packets=[public(p) for p in self.packets[-SNAPSHOT_PKTS:]])
        return found

    def forget_room(self, name: str):
        self.rooms.pop(name, None)
        self._rooms_dirty = True
        if name in self.watch_rooms:
            self.watch_rooms.remove(name)
            self.store.set("watchRooms", self.watch_rooms)
            self.room_index.set_extra(self.watch_rooms)
        self.msgs.pop("room:" + name, None)
        if self.dev_key:
            self.store.delete_conv(self.dev_key, "room:" + name)
        self.emit("rooms", rooms=list(self.rooms.values()), watch=self.watch_rooms)
        self.emit("msgs", msgs=self.msgs)

    async def subscribe_room(self, name: str):
        """Raum auf dem Gerät einrichten (freie Kanal-Position); der Verlauf wandert in den Kanal."""
        used = {c["idx"] for c in self.channels}
        mx = (self.dev or {}).get("maxChannels") or 8
        idx = next((i for i in range(mx) if i not in used), None)
        if idx is None:
            raise MeshError("Keine freie Kanal-Position auf dem Gerät")
        if name == "Public":
            await self._lib("set_channel", idx, "Public", PUBLIC_SECRET)
        else:
            await self._lib("set_channel", idx, "#" + name)
        await self.load_channels()

    def _merge_room(self, name: str, idx: int):
        self.rooms.pop(name, None)
        self._rooms_dirty = True
        old = self.msgs.pop("room:" + name, [])
        if old:
            conv = f"ch:{idx}"
            arr = self.msgs.setdefault(conv, [])
            arr.extend(old)
            arr.sort(key=lambda m: m.get("rx") or 0)
            del arr[:-MAX_MSGS]
            for m in old:
                self._dirty_msgs[m["id"]] = (conv, m)
        self.emit("rooms", rooms=list(self.rooms.values()), watch=self.watch_rooms)
        self.emit("msgs", msgs=self.msgs)

    # ================= Nachrichten =================
    async def sync_messages(self):
        if self._syncing or not self.connected:
            return
        self._syncing = True
        try:
            for _ in range(200):
                ev = await self._lib("get_msg")  # Nachricht selbst kommt über den Event-Handler
                if ev.type == EventType.NO_MORE_MSGS:
                    break
        except MeshError as e:
            log.debug("Sync: %s", e)
        finally:
            self._syncing = False

    def _find_rx_packet(self, types, pl, snr, check):
        """Passendes empfangenes Funkpaket zu einer Nachricht suchen (für Region-Anzeige)."""
        t = now_ms()
        for p in reversed(self.packets):
            if t - p["t"] > 180000:
                break
            if p.get("_used") or p["ptype"] not in types:
                continue
            if pl == 255:
                if p["route"] not in (2, 3):
                    continue
            elif p.get("plByte") != pl:
                continue
            if snr is not None and abs(p["snr"] - snr) > 0.01:
                continue
            if check and not check(p):
                continue
            p["_used"] = True
            return p
        return None

    @staticmethod
    def _link_packet(m, p, pl):
        if pl != 255:
            m["hashBytes"] = (pl >> 6) + 1
        if not p:
            return
        m["matched"] = True
        if p["ptype"] != 9:
            m["path"] = p["path"]
        if not p.get("tc"):
            m["region"] = "-"
            return
        m["regionCode"] = format(p["tc"][0], "04x")
        if p.get("region"):
            m["region"] = p["region"]

    def _on_contact_msg(self, ev):
        p = ev.payload
        prefix, pl, tt = p["pubkey_prefix"], _pl(p), p.get("txt_type", 0)
        snr = p.get("SNR")
        author = p.get("signature") if tt == 2 else None
        ct = self._contact_by_prefix(prefix)
        frm = ct["name"] if ct else prefix
        if author:
            frm = (self._node_name(author) or author) + (" @ " + ct["name"] if ct else "")
        m = {"dir": "in", "from": frm, "text": p.get("text", ""), "ts": p["sender_timestamp"] * 1000, "rx": now_ms(),
             "snr": snr, "hops": "direkt" if pl == 255 else pl & 63, "cli": tt == 1}
        pk = self._find_rx_packet([2], pl, snr, lambda q: not q["dec"].get("src") or prefix.startswith(q["dec"]["src"]))
        self._link_packet(m, pk, pl)
        self._route(m, self.nodes.get(ct["key"]) if ct else None)
        self.add_msg("c:" + prefix, m)

    def _on_channel_msg(self, ev):
        p = ev.payload
        idx, pl, snr = p["channel_idx"], _pl(p), p.get("SNR")
        raw = p.get("text", "")
        mt = re.match(r"^([^:]{1,40}): (.*)$", raw, re.S)
        m = {"dir": "in", "from": mt[1] if mt else "?", "text": mt[2] if mt else raw,
             "ts": p["sender_timestamp"] * 1000, "rx": now_ms(), "snr": snr, "hops": "direkt" if pl == 255 else pl & 63}
        ch = self._chan(idx)
        pk = self._find_rx_packet([5], pl, snr, lambda q: not ch or not ch.get("hash") or q["dec"].get("ch") == ch["hash"])
        self._link_packet(m, pk, pl)
        self._route(m, self._node_by_name(m["from"]))
        self.add_msg(f"ch:{idx}", m)

    def _node_by_name(self, name: str):
        l = [n for n in self.nodes.values() if n.get("name") == name]
        return l[0] if len(l) == 1 else None

    def _route(self, m: dict, sender: dict | None):
        """Strecke entlang des Weges (Absender → Repeater mit Position → eigene Node) für die Schnellantwort."""
        path = m.get("path")
        if path is None and m.get("hops") == 0:
            path = []  # direkt gehört
        if path is None:
            return
        me = self.self if has_pos(self.self) else None
        pts, unres = self._path_points(sender or {}, " ".join(path), me)
        m["segs"] = max(0, len(pts) - 1)
        m["noloc"] = unres + (0 if has_pos(sender) else 1) + (0 if me else 1)
        m["km"] = round(sum(hav(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:])), 1) if m["segs"] else None

    def add_msg(self, conv: str, m: dict):
        m.setdefault("id", uuid.uuid4().hex[:12])
        arr = self.msgs.setdefault(conv, [])
        if m["dir"] == "in" and any(x["dir"] == "in" and x["ts"] == m["ts"] and x["text"] == m["text"]
                                    and x["from"] == m["from"] for x in arr):
            return
        arr.append(m)
        del arr[:-MAX_MSGS]
        self._dirty_msgs[m["id"]] = (conv, m)
        self.emit("msg", conv=conv, m=m, new=True)

    def update_msg(self, conv: str, m: dict):
        self._dirty_msgs[m["id"]] = (conv, m)
        self.emit("msg", conv=conv, m=m, new=False)

    def max_len(self, conv: str) -> int:
        if conv.startswith("ch:"):
            return MAX_TXT - len(((self.self or {}).get("name") or "").encode()) - 2
        return MAX_TXT

    async def send_msg(self, conv: str, text: str):
        text = (text or "").strip()
        if not text or not conv:
            raise MeshError("Keine Nachricht")
        if not self.connected:
            raise MeshError("nicht verbunden")
        if len(text.encode()) > self.max_len(conv):
            raise MeshError("Nachricht zu lang")
        ts = int(time.time())
        m = {"dir": "out", "from": self.self["name"], "text": text, "ts": ts * 1000, "rx": now_ms(), "status": "sending"}
        if conv.startswith("ch:"):
            idx = int(conv[3:])
            rg = self.chan_region_of(self._chan(idx))
            m["region"] = rg
            self.add_msg(conv, m)
            try:
                try:
                    await self.apply_scope(rg)
                except MeshError as e:
                    if rg:
                        raise MeshError(f"Region konnte nicht gesetzt werden ({e})")
                await self._cmd(bytes([3, 0, idx]) + struct.pack("<I", ts) + text.encode())
                m["status"] = "sent"
            except MeshError as e:
                m["status"], m["err"] = "fail", str(e)
            self.update_msg(conv, m)
        else:
            m["attempt"] = 0
            self.add_msg(conv, m)
            await self.send_direct(conv, m)

    async def send_direct(self, conv: str, m: dict):
        prefix = bytes.fromhex(conv[2:])
        m["status"] = "sending"
        self.update_msg(conv, m)
        try:
            await self.apply_scope("")
        except MeshError:
            pass
        try:
            ev = await self._cmd(
                bytes([2, 0, m.get("attempt", 0) & 255]) + struct.pack("<I", m["ts"] // 1000) + prefix + m["text"].encode(),
                (EventType.MSG_SENT,))
            p = ev.payload
            m["flood"] = bool(p["type"])
            m["status"] = "sent"
            self.acks[bytes(p["expected_ack"]).hex()] = (conv, m)
            est = p.get("suggested_timeout") or 0
            asyncio.get_running_loop().call_later(max(est * 1.5, 8000) / 1000, self._ack_timeout, conv, m)
        except MeshError as e:
            m["status"], m["err"] = "fail", str(e)
        self.update_msg(conv, m)

    def _ack_timeout(self, conv, m):
        if m.get("status") == "sent":
            m["status"] = "noack"
            self.update_msg(conv, m)

    def _on_ack(self, ev):
        entry = self.acks.pop(ev.payload.get("code", ""), None)
        if entry:
            conv, m = entry
            m["status"] = "ok"
            m["rtt"] = ev.payload.get("trip_time")
            self.update_msg(conv, m)

    async def retry_msg(self, conv: str, mid: str):
        m = next((x for x in self.msgs.get(conv, []) if x["id"] == mid), None)
        if not m:
            raise MeshError("Nachricht nicht gefunden")
        m["attempt"] = (m.get("attempt") or 0) + 1
        await self.send_direct(conv, m)

    # ================= Live-Traffic =================
    def _on_rx_log(self, ev):
        p = ev.payload
        if p.get("payload"):
            self.on_raw_packet(bytes.fromhex(p["payload"]), p.get("snr", 0.0), p.get("rssi", 0))

    def on_raw_packet(self, raw: bytes, snr: float, rssi: int):
        chan_by_hash = {c["hash"]: c for c in self.channels}
        try:
            p = parse_packet(raw, chan_by_hash)
        except (IndexError, ValueError, struct.error):
            p = {"len": len(raw), "ptype": 15, "route": 1, "path": [], "hopCount": 0, "hs": 1, "dec": {}, "bad": True,
                 "tc": None, "ver": 0, "_payload": raw}
        self.pkt_seq += 1
        p.update(t=now_ms(), snr=snr, rssi=rssi, id=self.pkt_seq, raw=raw.hex())
        self._count(p)
        own = (self.self or {}).get("key")
        d = p["dec"]
        node = None
        # Knoten aus Adverts
        if p["ptype"] == 4 and d.get("key") and d["key"] != own:
            node = self.nodes.get(d["key"]) or {"key": d["key"]}
            if d.get("name"):
                node["name"] = d["name"]
            node["type"] = d.get("ntype")
            if has_pos(d):
                node["lat"], node["lon"] = d["lat"], d["lon"]
            node.update(heard=p["t"], snr=snr, rssi=rssi, hops=p["hopCount"], path=p["path"],
                        advTs=max(node.get("advTs") or 0, d.get("ts") or 0))
            self.nodes[d["key"]] = node
            self._dirty_nodes.add(d["key"])
        # Direkte Nachbarn (zuletzt gehörte Sendestation)
        nb = None
        if p["ptype"] != 9 and p["route"] in (0, 1):
            nk = None
            if p["hopCount"] > 0:
                nk = p["path"][-1]
            elif p["ptype"] == 4 and d.get("key"):
                nk = d["key"][:2 * max(1, p["hs"])]
            if nk and not (own and own.startswith(nk)):
                e = self.neighbors.get(nk) or {"n": 0, "snrSum": 0}
                e["n"] += 1
                e["snrSum"] += snr
                e.update(snr=snr, rssi=rssi, t=p["t"])
                self.neighbors[nk] = e
                nb = [nk, e]
        rs = cs = None
        if p.get("tc"):
            p["region"] = self._find_region(p)
            rs = self._region_stat(p)
        if p["ptype"] in (5, 6) and p.get("_payload"):
            cs = self._on_group_packet(p)
        self.packets.append(p)
        del self.packets[:-MAX_PKTS]
        self._new_packets.append(self._packet_row(p, nb[0] if nb else None))
        self.emit("packet", p=public(p), node=node, nb=nb, rs=rs, cs=cs)

    def _count(self, p):
        st = self.stats
        st["total"] += 1
        ty = PT[p["ptype"]]
        st["byType"][ty] = st["byType"].get(ty, 0) + 1
        minute = p["t"] // 60000
        st["minutes"][minute] = st["minutes"].get(minute, 0) + 1
        for k in [k for k in st["minutes"] if k < minute - 60]:
            del st["minutes"][k]

    def _packet_row(self, p, nb):
        """Zeile für die Tabelle packets (Reihenfolge wie Store.COLS)."""
        d = p["dec"]
        region = p.get("region") or ("?" if p.get("tc") else None)
        chan = (d.get("chName") or d.get("ch")) if p["ptype"] in (5, 6) else None
        s = self.self or {}
        air = airtime_ms(p["len"], s.get("sf"), s.get("bw"), s.get("cr"))
        return (p["id"], p["t"], p["ptype"], p["route"], p["hopCount"], p["hs"], p["snr"], p["rssi"], p["len"],
                region, chan, d.get("key") if p["ptype"] == 4 else None, d.get("name"), nb,
                packet_hash(p["ptype"], p.get("_payload") or b""), air, " ".join(p["path"]) if p["ptype"] != 9 else "",
                json.dumps(public(p), ensure_ascii=False))

    def _load_packets(self):
        since = max(now_ms() - self.packet_days * 86400000, self.store.get("liveSince", 0))
        for p in self.store.load_packets(since, MAX_PKTS):
            raw = bytes.fromhex(p.get("raw", ""))
            try:
                p["_payload"] = parse_packet(raw, {})["_payload"]
            except (IndexError, ValueError, struct.error):
                p["_payload"] = raw
            self.packets.append(p)
            self._count(p)
            if p.get("tc"):
                self._region_stat(p)
            d = p["dec"]
            if p["ptype"] in (5, 6) and d.get("ch"):
                cs = self.chan_stats.setdefault(d["ch"], {"hash": d["ch"], "count": 0})
                cs["count"] += 1
                cs["last"] = p["t"]
                if d.get("chName"):
                    cs["name"] = d["chName"]
        self.pkt_seq = self.store.max_packet_id()
        if self.packets:
            log.info("%d Pakete aus dem Verlauf geladen", len(self.packets))

    def packet_stats(self, hours: float) -> dict:
        now = now_ms()
        hours = max(1.0, min(hours, self.packet_days * 24))
        since = now - int(hours * 3600000)
        st = self.store.packet_stats(since, now)
        st["types"] = [[PT[t], n] for t, n in st["types"]]
        st["routes"] = [[ROUTES[r], n] for r, n in st["routes"]]
        me = self.self if has_pos(self.self) else None

        def km(n):
            return round(hav(me["lat"], me["lon"], n["lat"], n["lon"]), 1) if me and has_pos(n) else None

        def by_hash(h):
            """Knoten zu einem Hop-Hash – nur wenn eindeutig."""
            l = [n for n in self.nodes.values() if n["key"].startswith(h)]
            return l[0] if len(l) == 1 else None

        for n in st["neighbors"]:
            nd = by_hash(n["hash"])
            n["name"] = self._node_name(n["hash"])
            n["km"] = km(nd) if nd else None
            n["type"] = nd.get("type") if nd else None
        for n in st["nodesTop"]:
            n["km"] = km(self.nodes.get(n["key"]) or {})
            n["type"] = (self.nodes.get(n["key"]) or {}).get("type")
        st["repeaters"] = [{"hash": h, "count": c, "name": self._node_name(h),
                            "type": (by_hash(h) or {}).get("type")} for h, c in st["repeaters"]]
        types: dict = {}
        for k in st.pop("srcs"):
            t = (self.nodes.get(k) or {}).get("type")
            types[t] = types.get(t, 0) + 1
        st["nodeTypes"] = sorted(([t, n] for t, n in types.items()), key=lambda x: -x[1])
        tl = st["timeline"]
        dev = self.dev_key
        st["device"] = self.store.device_stats(dev, since, tl[0]["t"], st["bucketMs"], len(tl)) if dev and tl else None
        hour = self.store.device_stats(dev, now - 3600000, now - 3600000, 3600000, 1) if dev else None
        freq = (self.self or {}).get("freq")
        st["duty"] = {"limit": duty_limit(freq), "freq": freq,
                      "hour": hour["total"]["tx_air"] / 36 if hour and hour["samples"] >= 2 else None}
        st["msgs"] = self.store.msg_stats(dev, since) if dev else {"convs": [], "dm": {}, "rttAvg": None, "senders": []}
        for c in st["msgs"]["convs"]:
            c["title"] = self._conv_title(c["conv"])
        st.update(hours=hours, since=since, retentionDays=self.packet_days, radio=self.self and
                  {k: self.self.get(k) for k in ("sf", "bw", "cr", "freq")})
        return st

    def node_stats(self, key: str | None, hash_: str | None, hours: float) -> dict:
        """Details zu einem Knoten (Schlüssel bekannt) oder nur zu einem Hop-Hash."""
        key = (key or "").lower() or None
        if not key and hash_:
            l = [n for n in self.nodes.values() if n["key"].startswith(hash_.lower())]
            key = l[0]["key"] if len(l) == 1 else None
        if not key and not hash_:
            raise MeshError("Knoten fehlt")
        now = now_ms()
        hours = max(1.0, min(hours, self.packet_days * 24))
        since = now - int(hours * 3600000)
        size = bucket_ms(hours)
        start = since - since % size
        n = (now - start) // size + 1
        hashes = [key[:2], key[:4], key[:6]] if key else [hash_.lower()]
        st = self.store.node_stats(key, hashes, since, start, size, n)
        node = dict(self.nodes.get(key) or {}) if key else {}
        me = self.self if has_pos(self.self) else None
        st.update(key=key, hash=hashes[0], node=node, contact=self.contacts.get(key) if key else None,
                  km=round(hav(me["lat"], me["lon"], node["lat"], node["lon"]), 1) if me and has_pos(node) else None,
                  names=self._node_name(hashes[0]), bucketMs=size, start=start, since=since, hours=hours)
        for p in st["paths"]:
            p["names"] = [self._node_name(h) or h for h in p["path"].split()]
            p["points"], p["unresolved"] = self._path_points(node, p["path"], me)
        st["me"] = [me["lat"], me["lon"], me.get("name") or "ich"] if me else None
        return st

    def _path_points(self, start: dict, path: str, me: dict | None):
        """Koordinaten eines Weges: Start-Knoten → Hops (über ihre Hashes) → eigene Node.
        Mehrdeutige Hashes: der Kandidat, der dem vorigen Punkt am nächsten liegt."""
        pts, unres = [], 0
        if has_pos(start):
            pts.append([start["lat"], start["lon"], start.get("name") or "?"])
        for h in path.split():
            cands = [n for n in self.nodes.values() if n["key"].startswith(h) and has_pos(n)]
            if len(cands) > 1 and pts:
                cands.sort(key=lambda n: hav(pts[-1][0], pts[-1][1], n["lat"], n["lon"]))
            if cands and (len(cands) == 1 or pts):
                n = cands[0]
                pts.append([n["lat"], n["lon"], (n.get("name") or h) + (" (mehrdeutig)" if len(cands) > 1 else "")])
            else:
                unres += 1
        if me:
            pts.append([me["lat"], me["lon"], me.get("name") or "ich"])
        return pts, unres

    def _conv_title(self, conv: str) -> str:
        if conv.startswith("ch:"):
            ch = self._chan(int(conv[3:]))
            return ch["name"] if ch else f"Kanal {conv[3:]}"
        if conv.startswith("room:"):
            return "#" + conv[5:] + " (gehört)"
        c = self._contact_by_prefix(conv[2:])
        return c["name"] if c else self._node_name(conv[2:]) or conv[2:]

    def clear_packets(self):
        """Live-Ansicht leeren; der gespeicherte Verlauf für die Statistik bleibt."""
        self.store.set("liveSince", now_ms())
        self.packets = []
        self.stats = {"total": 0, "byType": {}, "minutes": {}}
        self.emit("packets_clear")

    def export_packets(self, fmt: str):
        rows = [{
            "zeit": datetime.fromtimestamp(p["t"] / 1000, timezone.utc).isoformat(), "typ": PT[p["ptype"]],
            "route": ROUTES[p["route"]], "hops": p["hopCount"], "pfad": " ".join(p["path"]), "snr": p["snr"],
            "rssi": p["rssi"], "laenge": p["len"], "name": p["dec"].get("name", ""), "key": p["dec"].get("key", ""),
            "lat": p["dec"].get("lat", ""), "lon": p["dec"].get("lon", ""), "hex": p["raw"]} for p in self.packets]
        if fmt == "json":
            return json.dumps(rows, indent=1, ensure_ascii=False), "application/json"
        buf = io.StringIO()
        fields = list(rows[0].keys()) if rows else ["zeit"]
        w = csv.DictWriter(buf, fields, delimiter=";", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue(), "text/csv"

    # ================= Gerät =================
    async def refresh_stats(self):
        if not self.connected:
            return
        r = self.radio
        try:
            p = (await self._lib("get_bat")).payload
            r["batt"] = p.get("level")
            if "used_kb" in p:
                r["used"], r["total"] = p["used_kb"], p["total_kb"]
        except MeshError:
            pass
        try:
            p = (await self._lib("get_stats_core")).payload
            r["uptime"], r["queue"] = p["uptime_secs"], p["queue_len"]
        except (MeshError, KeyError):
            pass
        try:
            p = (await self._lib("get_stats_radio")).payload
            r.update(noise=p["noise_floor"], lastRssi=p["last_rssi"], lastSnr=p["last_snr"],
                     txAir=p["tx_air_secs"], rxAir=p["rx_air_secs"])
        except (MeshError, KeyError):
            pass
        try:
            p = (await self._lib("get_stats_packets")).payload
            r.update(recv=p["recv"], sent=p["sent"], sFlood=p["flood_tx"], sDirect=p["direct_tx"],
                     rFlood=p["flood_rx"], rDirect=p["direct_rx"], rErr=p.get("recv_errors"))
        except (MeshError, KeyError):
            pass
        if self.dev_key and time.time() - self._last_sample >= SAMPLE_S - 5:
            self._last_sample = time.time()
            self.store.save_device_sample(self.dev_key, now_ms(), {
                "batt": r.get("batt"), "noise": r.get("noise"), "tx_air": r.get("txAir"), "rx_air": r.get("rxAir"),
                "recv": r.get("recv"), "sent": r.get("sent"), "flood_tx": r.get("sFlood"), "direct_tx": r.get("sDirect"),
                "flood_rx": r.get("rFlood"), "direct_rx": r.get("rDirect"), "rx_err": r.get("rErr"), "uptime": r.get("uptime")})
        self.emit_status()

    async def reload_self(self):
        ev = await self._lib("send_appstart")
        self.self = norm_self(ev.payload)
        self.emit_status()

    async def advert(self, flood: bool):
        await self._lib("send_advert", flood=flood)

    async def set_name(self, name: str):
        name = (name or "").strip()
        if not name:
            raise MeshError("Name fehlt")
        await self._lib("set_name", name.encode()[:31].decode("utf-8", "ignore"))
        await self.reload_self()

    async def set_position(self, lat: float, lon: float):
        if not (abs(lat) <= 90 and abs(lon) <= 180):
            raise MeshError("Ungültige Koordinaten")
        await self._lib("set_coords", lat, lon)
        await self.reload_self()

    async def set_tx(self, v: int):
        await self._lib("set_tx_power", v)
        await self.reload_self()

    async def set_other(self, auto_add: bool | None = None, loc_adv: bool | None = None):
        s = self._self()
        manual = s["manualAdd"]
        if auto_add is not None:
            manual = manual & ~1 if auto_add else manual | 1
        loc = s["locPolicy"] if loc_adv is None else int(loc_adv)
        await self._cmd(bytes([38, manual, s["telem"], loc, s["multiAcks"]]))
        await self.reload_self()

    async def set_time(self):
        await self._lib("set_time", int(time.time()))

    async def reboot(self):
        mc = self._mc()
        async with self.lock:
            await mc.commands.send(b"\x13reboot")
        await asyncio.sleep(0.5)
        await self._lost("Neustart ausgelöst – verbinde neu, sobald das Gerät wieder da ist")

    def _self(self) -> dict:
        if not self.self:
            raise MeshError("nicht verbunden")
        return self.self

    def wipe(self):
        """Gespeicherte Knoten, Chatverläufe, gehörte Räume und Paketverlauf löschen (auf dem Gerät bleibt alles)."""
        self.store.wipe()
        self._dirty_nodes.clear()
        self._dirty_msgs.clear()
        self.nodes = {}
        self.msgs = {}
        self.rooms = {}  # gehörte Räume samt Verlauf; beobachtete Namen (Einstellung) bleiben
        self._rooms_dirty = True
        self.packets, self._new_packets = [], []
        self.stats = {"total": 0, "byType": {}, "minutes": {}}
        self.region_stats, self.chan_stats = {}, {}
        for c in list(self.raw_contacts.values()):
            self._upsert_contact(c, self.contacts.get(c["public_key"], {}).get("saved", True), emit=False)
        self.emit("snapshot", state=self.snapshot())
