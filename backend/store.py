"""Persistenz in SQLite: Knoten, Chatverläufe und Einstellungen."""
import json
import sqlite3
from pathlib import Path

MAX_MSGS = 500  # pro Unterhaltung

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (key TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
  dev TEXT NOT NULL, conv TEXT NOT NULL, id TEXT NOT NULL, rx INTEGER NOT NULL, data TEXT NOT NULL,
  PRIMARY KEY (dev, id));
CREATE INDEX IF NOT EXISTS messages_conv ON messages (dev, conv, rx);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS packets (
  id INTEGER PRIMARY KEY, t INTEGER NOT NULL, ptype INTEGER, route INTEGER, hops INTEGER, hs INTEGER,
  snr REAL, rssi INTEGER, len INTEGER,
  region TEXT,     -- Name, '?' (Region unbekannt) oder NULL (ohne Region)
  chan TEXT,       -- Kanal-/Raumname oder Kanal-Hash (Gruppenpakete)
  src TEXT,        -- Public Key des Absenders (Adverts)
  name TEXT,       -- Name aus dem Advert
  nb TEXT,         -- direkter Nachbar (zuletzt sendende Station)
  data TEXT NOT NULL,
  ph TEXT,         -- Paket-Hash (Typ + Nutzdaten): gleich für alle Empfänge desselben Pakets
  air REAL,        -- geschätzte Sendezeit in ms
  path TEXT);      -- Hop-Hashes, durch Leerzeichen getrennt
CREATE INDEX IF NOT EXISTS packets_t ON packets (t);
-- Gerätewerte alle paar Minuten (Zähler steigen seit dem Gerätestart, Sendezeit in Sekunden)
CREATE TABLE IF NOT EXISTS device_stats (
  dev TEXT NOT NULL, t INTEGER NOT NULL, batt INTEGER, noise INTEGER, tx_air INTEGER, rx_air INTEGER,
  recv INTEGER, sent INTEGER, flood_tx INTEGER, direct_tx INTEGER, flood_rx INTEGER, direct_rx INTEGER, rx_err INTEGER,
  uptime INTEGER, PRIMARY KEY (dev, t));
"""
DEV_COLS = ("batt", "noise", "tx_air", "rx_air", "recv", "sent", "flood_tx", "direct_tx", "flood_rx", "direct_rx", "rx_err", "uptime")
COUNTERS = ("tx_air", "rx_air", "recv", "sent", "flood_tx", "direct_tx", "flood_rx", "direct_rx", "rx_err")

# Zeitraster der Statistik: bis 2 Tage stündlich, bis 14 Tage 6-stündlich, bis 120 Tage täglich, sonst wöchentlich
def bucket_ms(hours):
    return 3600000 if hours <= 48 else 6 * 3600000 if hours <= 336 else 86400000 if hours <= 2880 else 7 * 86400000


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        # Migration: Spalten, die ältere Datenbanken noch nicht haben
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(packets)")}
        for col, typ in (("ph", "TEXT"), ("air", "REAL"), ("path", "TEXT")):
            if col not in cols:
                self.db.execute(f"ALTER TABLE packets ADD COLUMN {col} {typ}")
        self.db.commit()

    # Einstellungen
    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))
        self.db.commit()

    # Knoten
    def load_nodes(self) -> dict:
        return {k: json.loads(d) for k, d in self.db.execute("SELECT key, data FROM nodes")}

    def save_nodes(self, nodes: list):
        self.db.executemany("INSERT OR REPLACE INTO nodes VALUES (?,?)", [(n["key"], json.dumps(n)) for n in nodes])
        self.db.commit()

    # Nachrichten
    def load_msgs(self, dev: str) -> dict:
        out = {}
        for conv, d in self.db.execute("SELECT conv, data FROM messages WHERE dev=? ORDER BY rx", (dev,)):
            out.setdefault(conv, []).append(json.loads(d))
        return {c: a[-MAX_MSGS:] for c, a in out.items()}

    def save_msgs(self, dev: str, items: list):
        """items: Liste von (conv, msg)."""
        self.db.executemany(
            "INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?)",
            [(dev, conv, m["id"], m.get("rx") or 0, json.dumps(m)) for conv, m in items],
        )
        for conv in {c for c, _ in items}:
            self.db.execute(
                "DELETE FROM messages WHERE dev=? AND conv=? AND id NOT IN "
                "(SELECT id FROM messages WHERE dev=? AND conv=? ORDER BY rx DESC LIMIT ?)",
                (dev, conv, dev, conv, MAX_MSGS),
            )
        self.db.commit()

    # Pakete (Live-Traffic-Verlauf für die Statistik)
    COLS = ("id", "t", "ptype", "route", "hops", "hs", "snr", "rssi", "len", "region", "chan", "src", "name", "nb",
            "ph", "air", "path", "data")

    def save_packets(self, rows: list):
        """rows: Tupel in der Reihenfolge von COLS"""
        self.db.executemany(f"INSERT OR REPLACE INTO packets ({','.join(self.COLS)}) VALUES ({','.join('?' * len(self.COLS))})", rows)
        self.db.commit()

    def load_packets(self, since: int, limit: int) -> list:
        rows = self.db.execute("SELECT data FROM packets WHERE t>=? ORDER BY id DESC LIMIT ?", (since, limit)).fetchall()
        return [json.loads(d) for (d,) in reversed(rows)]

    def get_packet(self, pid: int) -> dict | None:
        row = self.db.execute("SELECT data FROM packets WHERE id=?", (pid,)).fetchone()
        return json.loads(row[0]) if row else None

    def packets_missing(self, limit=5000) -> list:
        """Pakete ohne Paket-Hash oder Sendezeit (aus der Zeit vor diesen Spalten)."""
        return self.db.execute("SELECT id, len, data FROM packets WHERE ph IS NULL OR air IS NULL LIMIT ?", (limit,)).fetchall()

    def update_packets(self, rows: list):
        """rows: (ph, air, path, id)"""
        self.db.executemany("UPDATE packets SET ph=COALESCE(ph, ?), air=COALESCE(air, ?), path=COALESCE(path, ?) WHERE id=?", rows)
        self.db.commit()

    def unknown_region_packets(self) -> list:
        """Pakete, deren Region (noch) unbekannt ist: (id, data)."""
        return self.db.execute("SELECT id, data FROM packets WHERE region='?'").fetchall()

    def set_packet_regions(self, rows: list):
        """rows: (region, data, id)"""
        self.db.executemany("UPDATE packets SET region=?, data=? WHERE id=?", rows)
        self.db.commit()

    def replay_rows(self, since: int, until: int, limit: int) -> list:
        """Empfänge mit Pfad (oder Adverts) im Zeitraum, für die Wiedergabe auf der Karte."""
        return self.db.execute(
            "SELECT t, ptype, src, path FROM packets WHERE t >= ? AND t < ? AND ptype != 9 "
            "AND (hops > 0 OR ptype = 4) ORDER BY t LIMIT ?", (since, until, limit)).fetchall()

    def route_rows(self, since: int) -> list:
        """Je Absender (nur Adverts) und Pfad: eindeutige Pakete, Empfänge, Ø SNR, zuletzt."""
        return self.db.execute(
            "SELECT CASE WHEN ptype=4 THEN src END, path, COUNT(DISTINCT COALESCE(ph, id)), COUNT(*), AVG(snr), MAX(t) "
            "FROM packets WHERE t>=? AND ptype<>9 AND (hops>0 OR ptype=4) GROUP BY 1, 2", (since,)).fetchall()

    def max_packet_id(self) -> int:
        return self.db.execute("SELECT COALESCE(MAX(id), 0) FROM packets").fetchone()[0]

    def prune_packets(self, before: int) -> int:
        n = self.db.execute("DELETE FROM packets WHERE t<?", (before,)).rowcount
        self.db.commit()
        return n

    def _summary(self, since: int, until: int) -> dict:
        r = self.db.execute(
            "SELECT COUNT(*), COUNT(DISTINCT COALESCE(ph, id)), COUNT(DISTINCT src), AVG(snr), AVG(rssi), SUM(air), MIN(t) "
            "FROM packets WHERE t>=? AND t<?", (since, until)).fetchone()
        return dict(zip(("total", "unique", "nodes", "avgSnr", "avgRssi", "air", "first"), r))

    def packet_stats(self, since: int, now: int) -> dict:
        q = lambda sql, *a: self.db.execute(sql, (since, *a)).fetchall()
        span = now - since
        size = bucket_ms(span / 3600000)
        start = since - since % size
        tl = {b: r for b, *r in self.db.execute(
            "SELECT (t-?)/? AS b, COUNT(*), COUNT(DISTINCT COALESCE(ph, id)), SUM(ptype=4), COALESCE(SUM(air), 0), "
            "COUNT(DISTINCT src), AVG(CASE WHEN nb IS NOT NULL THEN snr END) FROM packets WHERE t>=? GROUP BY b",
            (start, size, since))}
        empty = (0, 0, 0, 0, 0, None)
        first_ever = self.db.execute("SELECT MIN(t) FROM packets").fetchone()[0]
        st = {
            "cur": self._summary(since, now + 1),
            # Vergleich nur, wenn der Vorzeitraum vollständig aufgezeichnet ist
            "prev": self._summary(since - span, since) if first_ever is not None and first_ever <= since - span else None,
            "bucketMs": size,
            "timeline": [dict(zip(("t", "count", "unique", "adverts", "air", "nodes", "snr"), (start + i * size, *tl.get(i, empty))))
                         for i in range((now - start) // size + 1)],
            # Stundenwerte (UTC) – der Browser rechnet sie in Wochentag × Uhrzeit seiner Zeitzone um
            "hourly": q("SELECT t/3600000, COUNT(*) FROM packets WHERE t>=? GROUP BY 1"),
            "types": q("SELECT ptype, COUNT(*) FROM packets WHERE t>=? GROUP BY ptype ORDER BY 2 DESC"),
            "routes": q("SELECT route, COUNT(*) FROM packets WHERE t>=? GROUP BY route ORDER BY 2 DESC"),
            "regions": q("SELECT region, COUNT(*) FROM packets WHERE t>=? AND region IS NOT NULL GROUP BY region ORDER BY 2 DESC LIMIT 15"),
            "hops": q("SELECT MIN(hops, 10), COUNT(*) FROM packets WHERE t>=? AND route IN (0, 1) GROUP BY 1 ORDER BY 1"),
            # Pfad-Hash-Größe nur bei Paketen mit Pfad aussagekräftig
            "hashSize": q("SELECT hs, COUNT(DISTINCT COALESCE(ph, id)) FROM packets WHERE t>=? AND hops>0 AND ptype<>9 GROUP BY hs ORDER BY hs"),
            "snr": q("SELECT CAST((snr + 100) / 2.5 AS INTEGER) * 2.5 - 100 AS b, COUNT(*) FROM packets WHERE t>=? GROUP BY b ORDER BY b"),
            "channels": q("SELECT chan, COUNT(*), COUNT(DISTINCT COALESCE(ph, id)) FROM packets WHERE t>=? AND chan IS NOT NULL "
                          "GROUP BY chan ORDER BY 3 DESC LIMIT 15"),
            # eindeutige Adverts je Knoten (ein geflutetes Advert zählt einmal, egal wie oft gehört)
            "nodesTop": [dict(zip(("key", "name", "adverts", "count", "snr", "last", "hops"), r)) for r in q(
                "SELECT src, MAX(name), COUNT(DISTINCT COALESCE(ph, id)), COUNT(*), AVG(snr), MAX(t), MIN(hops) FROM packets "
                "WHERE t>=? AND src IS NOT NULL GROUP BY src ORDER BY 3 DESC LIMIT 40")],
            "neighbors": [dict(zip(("hash", "count", "snr", "rssi", "last"), r)) for r in q(
                "SELECT nb, COUNT(*), AVG(snr), AVG(rssi), MAX(t) FROM packets WHERE t>=? AND nb IS NOT NULL "
                "GROUP BY nb ORDER BY 2 DESC LIMIT 30")],
            # erstmals gehört im Zeitraum (innerhalb der Aufbewahrung)
            "srcs": [r[0] for r in q("SELECT DISTINCT src FROM packets WHERE t>=? AND src IS NOT NULL")],
            "newNodes": [dict(zip(("key", "name", "first"), r)) for r in self.db.execute(
                "SELECT src, MAX(name), MIN(t) FROM packets WHERE src IS NOT NULL GROUP BY src HAVING MIN(t)>=? "
                "ORDER BY 3 DESC LIMIT 50", (since,))],
        }
        # Repeater-Last: jeder Hop eines eindeutigen Pakets zählt einmal
        hops: dict = {}
        for (path,) in self.db.execute(
                "SELECT MAX(path) FROM packets WHERE t>=? AND path IS NOT NULL AND path<>'' GROUP BY COALESCE(ph, id)", (since,)):
            for h in set(path.split()):
                hops[h] = hops.get(h, 0) + 1
        st["repeaters"] = sorted(hops.items(), key=lambda x: -x[1])[:30]
        return st

    def node_stats(self, key: str | None, hashes: list, since: int, start: int, size: int, n: int) -> dict:
        """Details zu einem Knoten: Adverts (per Schlüssel), direkter Empfang und Weiterleitungen (per Hop-Hash)."""
        hs = set(hashes)
        b = [{"adverts": 0, "direct": 0, "relayed": 0, "snr": []} for _ in range(n)]
        idx = lambda t: (t - start) // size
        adverts, paths, seen = [], {}, set()
        hours: dict = {}   # Aktivität je Stunde (Adverts, direkter Empfang, Weiterleitungen)
        peers: dict = {}   # Hop-Hashes, die im Netz direkt neben dem Knoten liegen
        via: dict = {}     # direkte Nachbarn, über die seine Adverts bei uns ankommen
        snrs = []

        def act(t):
            hours[t // 3600000] = hours.get(t // 3600000, 0) + 1

        def peer(h, side):
            e = peers.setdefault(h, [0, 0])  # [vom Knoten weg, zum Knoten hin]
            e[side] += 1
        if key:
            for t, hops, path, snr, rssi, ph, region in self.db.execute(
                    "SELECT t, hops, path, snr, rssi, ph, region FROM packets WHERE src=? AND t>=? ORDER BY t DESC", (key, since)):
                if ph not in seen or ph is None:  # jedes Advert einmal (beim ersten = jüngsten Empfang)
                    seen.add(ph)
                    if 0 <= idx(t) < n:
                        b[idx(t)]["adverts"] += 1
                    if len(adverts) < 25:
                        adverts.append({"t": t, "hops": hops, "path": path, "snr": snr, "rssi": rssi, "region": region})
                    act(t)
                    if path:
                        peer(path.split()[0], 0)  # erster Repeater hat das Advert direkt gehört
                v = via.setdefault(path.split()[-1] if path else "", [0, 0.0])
                v[0] += 1
                v[1] += snr or 0
                p = paths.setdefault(path or "", {"path": path or "", "count": 0, "snr": 0.0})
                p["count"] += 1
                p["snr"] += snr or 0
        q = ",".join("?" * len(hs)) or "''"
        direct = self.db.execute(f"SELECT t, snr, rssi FROM packets WHERE t>=? AND nb IN ({q})", (since, *hs)).fetchall()
        for t, snr, _ in direct:
            act(t)
            if snr is not None:
                snrs.append(snr)
            if 0 <= idx(t) < n:
                b[idx(t)]["direct"] += 1
                b[idx(t)]["snr"].append(snr)
        relayed, rel_seen = 0, set()
        like = " OR ".join("instr(path, ?) > 0" for _ in hs) or "0"
        for t, ph, path in self.db.execute(
                f"SELECT t, ph, path FROM packets WHERE t>=? AND path IS NOT NULL AND path<>'' AND ({like})", (since, *hs)):
            if hs & set(path.split()) and (ph is None or ph not in rel_seen):
                rel_seen.add(ph)
                relayed += 1
                act(t)
                p = path.split()
                i = next(i for i, h in enumerate(p) if h in hs)
                if i > 0:
                    peer(p[i - 1], 1)  # hat das Paket an den Knoten weitergegeben
                if i + 1 < len(p):
                    peer(p[i + 1], 0)  # hat es vom Knoten bekommen
                if 0 <= idx(t) < n:
                    b[idx(t)]["relayed"] += 1
        avg = lambda l: sum(l) / len(l) if l else None
        dist: dict = {}  # SNR direkter Empfänge in Stufen zu 2,5 dB (wie in packet_stats)
        for s in snrs:
            k = int((s + 100) // 2.5) * 2.5 - 100
            dist[k] = dist.get(k, 0) + 1
        span = self.db.execute(f"SELECT MIN(t), MAX(t) FROM packets WHERE src=? OR nb IN ({q})", (key or "", *hs)).fetchone()
        return {
            "adverts": len(seen), "direct": len(direct), "relayed": relayed,
            "snr": avg([r[1] for r in direct if r[1] is not None]), "rssi": avg([r[2] for r in direct if r[2] is not None]),
            "firstSeen": span[0], "lastSeen": span[1],
            "buckets": [{"adverts": x["adverts"], "direct": x["direct"], "relayed": x["relayed"], "snr": avg(x["snr"])} for x in b],
            "paths": sorted(({"path": p["path"], "count": p["count"], "snr": p["snr"] / p["count"]} for p in paths.values()),
                            key=lambda p: -p["count"])[:10],
            "recent": adverts,
            "hourly": sorted(hours.items()),
            "snrDist": sorted(dist.items()),
            "peers": sorted(([h, a, b] for h, (a, b) in peers.items() if h not in hs), key=lambda x: -(x[1] + x[2]))[:60],  # Mesh.node_stats fasst nach Knoten zusammen und kürzt
            "via": sorted(([h, c, s / c] for h, (c, s) in via.items()), key=lambda x: -x[1])[:40],
        }

    def msg_stats(self, dev: str, since: int) -> dict:
        convs: dict = {}
        senders: dict = {}
        dm = {"ok": 0, "noack": 0, "fail": 0, "sent": 0}
        rtts = []
        for conv, d in self.db.execute("SELECT conv, data FROM messages WHERE dev=? AND rx>=?", (dev, since)):
            m = json.loads(d)
            c = convs.setdefault(conv, {"conv": conv, "in": 0, "out": 0, "last": 0, "senders": set()})
            c[m["dir"]] += 1
            c["last"] = max(c["last"], m.get("rx") or 0)
            if m["dir"] == "in" and not conv.startswith("c:"):
                c["senders"].add(m.get("from"))
                k = m.get("from") or "?"
                senders[k] = senders.get(k, 0) + 1
            if m["dir"] == "out" and conv.startswith("c:") and m.get("status") in dm:
                dm[m["status"]] += 1
                if m.get("status") == "ok" and m.get("rtt"):
                    rtts.append(m["rtt"])
        for c in convs.values():
            c["senders"] = len(c["senders"])
        return {"convs": sorted(convs.values(), key=lambda c: -(c["in"] + c["out"])), "dm": dm,
                "rttAvg": sum(rtts) / len(rtts) if rtts else None,
                "senders": sorted(senders.items(), key=lambda x: -x[1])[:15]}

    # Gerätewerte
    def save_device_sample(self, dev: str, t: int, vals: dict):
        self.db.execute(f"INSERT OR REPLACE INTO device_stats (dev, t, {','.join(DEV_COLS)}) VALUES (?,?,{','.join('?' * len(DEV_COLS))})",
                        (dev, t, *[vals.get(c) for c in DEV_COLS]))
        self.db.commit()

    def prune_device_stats(self, before: int):
        self.db.execute("DELETE FROM device_stats WHERE t<?", (before,))
        self.db.commit()

    def device_stats(self, dev: str, since: int, start: int, size: int, n: int) -> dict:
        """Gerätewerte im Zeitraster: Mittelwerte (Rauschen, Batterie) und Zuwächse der Zähler."""
        rows = self.db.execute(f"SELECT t, {','.join(DEV_COLS)} FROM device_stats WHERE dev=? AND t>=? ORDER BY t",
                               (dev, since - 3600000)).fetchall()
        b = [{"noise": [], "batt": [], **{c: 0 for c in COUNTERS}} for _ in range(n)]
        tot = {c: 0 for c in COUNTERS}
        prev = None
        for r in rows:
            cur = dict(zip(("t", *DEV_COLS), r))
            i = (cur["t"] - start) // size
            if cur["t"] >= since and 0 <= i < n:
                for k in ("noise", "batt"):
                    if cur[k] is not None:
                        b[i][k].append(cur[k])
                # Zuwachs seit dem letzten Wert; nach einem Neustart des Geräts (Zähler kleiner) überspringen
                if prev and cur["t"] - prev["t"] < 1800000 and (cur["uptime"] or 0) >= (prev["uptime"] or 0):
                    for c in COUNTERS:
                        if cur[c] is not None and prev[c] is not None and cur[c] >= prev[c]:
                            b[i][c] += cur[c] - prev[c]
                            tot[c] += cur[c] - prev[c]
            prev = cur
        avg = lambda l: sum(l) / len(l) if l else None
        last = dict(zip(("t", *DEV_COLS), rows[-1])) if rows else None
        return {"buckets": [{"noise": avg(x["noise"]), "batt": avg(x["batt"]), **{c: x[c] for c in COUNTERS}} for x in b],
                "total": tot, "samples": sum(1 for r in rows if r[0] >= since), "last": last}

    def wipe(self):
        """Knoten, Chatverläufe und Paketverlauf löschen (Einstellungen bleiben)."""
        self.db.execute("DELETE FROM nodes")
        self.db.execute("DELETE FROM messages")
        self.db.execute("DELETE FROM packets")
        self.db.execute("DELETE FROM device_stats")
        self.db.commit()

    def delete_conv(self, dev: str, conv: str):
        self.db.execute("DELETE FROM messages WHERE dev=? AND conv=?", (dev, conv))
        self.db.commit()
