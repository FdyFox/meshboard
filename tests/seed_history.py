"""Künstlichen Paketverlauf erzeugen – für Entwicklung und Screenshots der Statistik.

    python -m tests.seed_history data-dev/meshcore.db [--days 7]
    python -m backend --data data-dev            # ohne Node, nur Statistik ansehen

Erzeugt Adverts von 30 Knoten, Gruppen- und Direktnachrichten mit Tagesgang,
Mehrfachempfang über verschiedene Repeater, Regionen und schwankendes SNR.
"""
import argparse
import json
import random
import time
from pathlib import Path

from backend.packets import airtime_ms
from backend.store import Store

TYPES = [(4, 0.15), (5, 0.35), (2, 0.2), (3, 0.15), (0, 0.05), (1, 0.05), (8, 0.05)]
REGIONS = ["saarland", "saarland", "saarland", "pfalz", "?", None, None, None]
CHANS = ["Public", "#saarland", "#test", "#technik", "3f"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()
    rnd = random.Random(42)
    store = Store(Path(a.db))
    nodes = [(f"{i:02x}" + "".join(rnd.choice("0123456789abcdef") for _ in range(62)),
              rnd.choice(["Rep-", "Node-", "Mobil-"]) + str(i), rnd.uniform(49.1, 49.6), rnd.uniform(6.6, 7.4)) for i in range(30)]
    repeaters = [n[0][:2] for n in nodes[:8]]
    now = int(time.time() * 1000)
    t = now - a.days * 86400000
    pid, rows = store.max_packet_id(), []
    while t < now:
        hour = time.localtime(t / 1000).tm_hour
        rate = 0.25 + 0.75 * (1 if 7 <= hour <= 22 else 0.2)          # Tagesgang
        t += int(rnd.expovariate(rate / 30000))                         # ~2/min am Tag
        ptype = rnd.choices([x for x, _ in TYPES], [w for _, w in TYPES])[0]
        flood = ptype in (4, 5) or rnd.random() < 0.3
        n = rnd.choice(nodes)
        ph = f"{rnd.getrandbits(64):016x}"
        length = rnd.randint(30, 140) if ptype != 3 else 12
        for _ in range(rnd.choices([1, 2, 3, 4], [5, 3, 2, 1])[0] if flood else 1):  # Mehrfachempfang
            pid += 1
            hops = rnd.choices(range(6), [3, 4, 3, 2, 1, 1])[0] if flood else rnd.randint(0, 2)
            path = rnd.sample(repeaters, min(hops, len(repeaters)))
            snr = round(rnd.gauss(4, 5), 2)
            region = rnd.choice(REGIONS) if flood else None
            p = {"id": pid, "t": t, "ptype": ptype, "route": 1 if flood else 2, "ver": 0, "len": length, "hs": 1,
                 "hopCount": len(path), "path": path, "snr": snr, "rssi": int(-120 + snr * 3), "raw": "",
                 "tc": [1, 0] if region else None, "region": region if region != "?" else None,
                 "dec": {"key": n[0], "name": n[1], "ntype": 2 if n[1].startswith("Rep") else 1, "lat": n[2], "lon": n[3]}
                 if ptype == 4 else {}}
            nb = path[-1] if path else (n[0][:2] if ptype == 4 else None)
            rows.append((pid, t, ptype, p["route"], len(path), 1, snr, p["rssi"], length, region,
                         rnd.choice(CHANS) if ptype == 5 else None, n[0] if ptype == 4 else None,
                         n[1] if ptype == 4 else None, nb, ph, airtime_ms(length, 8, 62.5, 8), " ".join(path), json.dumps(p)))
            t += rnd.randint(200, 3000)
    store.save_packets(rows)
    # Gerätewerte alle 5 Minuten: Rauschen mit Tagesgang, Solarbatterie, steigende Zähler
    dev = store.get("lastDev") or "seed000000000000"
    store.set("lastDev", dev)
    tx = rx = recv = sent = 0
    for t5 in range(now - a.days * 86400000, now, 300000):
        h = time.localtime(t5 / 1000).tm_hour
        day = 7 <= h <= 22
        tx += rnd.randint(0, 6 if day else 2)
        rx += rnd.randint(10, 40 if day else 15)
        recv += rnd.randint(5, 20)
        sent += rnd.randint(0, 3)
        store.save_device_sample(dev, t5, {"batt": int(3900 + 250 * max(0, 1 - abs(h - 13) / 6) + rnd.gauss(0, 15)),
                                           "noise": int(-114 + (3 if day else 0) + rnd.gauss(0, 1.5)), "tx_air": tx, "rx_air": rx,
                                           "recv": recv, "sent": sent, "flood_tx": sent // 2, "direct_tx": sent - sent // 2,
                                           "flood_rx": recv * 3 // 4, "direct_rx": recv // 4, "rx_err": recv // 50, "uptime": (t5 - now) // 1000 + 10 ** 7})
    msgs = []
    for i in range(300):
        tm = now - rnd.randint(0, a.days * 86400000)
        conv = rnd.choice(["ch:0", "ch:0", "ch:1", "ch:2", "c:" + nodes[3][0][:12]])
        out = rnd.random() < 0.25
        m = {"id": f"seed{i}", "dir": "out" if out else "in", "from": "Ich" if out else rnd.choice(nodes[:12])[1],
             "text": "Test", "ts": tm, "rx": tm}
        if out and conv.startswith("c:"):
            m["status"] = rnd.choices(["ok", "noack", "fail"], [8, 2, 1])[0]
            m["rtt"] = rnd.randint(1500, 9000)
        msgs.append((conv, m))
    store.save_msgs(dev, msgs)
    store.save_nodes([{"key": k, "name": nm, "type": 2 if nm.startswith("Rep") else 1, "lat": la, "lon": lo} for k, nm, la, lo in nodes])
    print(f"{len(rows)} Pakete über {a.days} Tage in {a.db} geschrieben")


if __name__ == "__main__":
    main()
