"""HTTP-API (FastAPI): REST-Befehle, WebSocket mit Live-Events, Auslieferung des Frontends."""
import asyncio
import contextlib
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import VERSION
from .mesh import Mesh, MeshError, parse_target
from .packets import packet_layout
from .store import Store

log = logging.getLogger("mcw")
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


class Target(BaseModel):
    transport: str
    address: str = ""


class Flood(BaseModel):
    flood: bool = False


class SendMsg(BaseModel):
    conv: str
    text: str


class Retry(BaseModel):
    conv: str
    id: str


class Text(BaseModel):
    value: str = ""


class Remote(BaseModel):
    key: str
    password: str | None = None
    remember: bool | None = None
    cmd: str = ""


class Push(BaseModel):
    type: str = ""
    url: str = ""
    chat: str = ""
    token: str | None = None  # None: gespeicherten Token behalten
    events: dict = {}


class Lookup(BaseModel):
    on: bool = False
    url: str = ""


class AutoReply(BaseModel):
    on: bool = False
    words: list[str] | str = []
    tpl: str = ""
    cooldown: float = 300


class Watch(BaseModel):
    key: str
    hours: float = 0


class Position(BaseModel):
    lat: float
    lon: float


class Number(BaseModel):
    value: int


class Other(BaseModel):
    autoAdd: bool | None = None
    locAdv: bool | None = None


class Switch(BaseModel):
    on: bool


def create_app(target: dict | None, data_dir: Path, packet_days: int = 365) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        mesh = Mesh(Store(data_dir / "meshcore.db"), target, packet_days)
        app.state.mesh = mesh
        await mesh.start()
        yield
        await mesh.shutdown()

    app = FastAPI(title="Meshboard", version=VERSION, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.exception_handler(MeshError)
    async def mesh_error(request: Request, e: MeshError):
        return JSONResponse({"detail": str(e)}, status_code=400)

    def M(request: Request) -> Mesh:
        return request.app.state.mesh

    ok = {"ok": True}

    # ---- Zustand & Live-Events ----
    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz():
        return "ok"

    @app.get("/api/version")
    async def version():
        return {"name": "meshboard", "version": VERSION}

    @app.get("/api/state")
    async def state(request: Request):
        return M(request).snapshot()

    @app.websocket("/api/ws")
    async def ws(sock: WebSocket):
        mesh: Mesh = sock.app.state.mesh
        await sock.accept()
        q: asyncio.Queue = asyncio.Queue()
        # Snapshot und Registrierung ohne await dazwischen: kein Event geht verloren oder doppelt
        mesh.clients.add(q)
        q.put_nowait({"t": "snapshot", "state": mesh.snapshot()})

        async def sender():
            while True:
                await sock.send_json(await q.get())

        task = asyncio.create_task(sender())
        try:
            while True:
                await sock.receive_text()  # nur zum Erkennen des Verbindungsendes
        except WebSocketDisconnect:
            pass
        finally:
            mesh.clients.discard(q)
            task.cancel()

    # ---- Verbindung ----
    @app.post("/api/connect")
    async def connect(request: Request, t: Target | None = None):
        tg = None
        if t:
            tg = parse_target(f"{t.transport}:{t.address}")
            if tg["transport"] == "tcp" and not tg["address"]:
                raise MeshError("Adresse der Node fehlt")
            if tg["transport"] == "serial" and not tg["address"]:
                raise MeshError("Serielle Schnittstelle fehlt")
        await M(request).connect(tg)
        return ok

    @app.post("/api/disconnect")
    async def disconnect(request: Request):
        await M(request).disconnect()
        return ok

    @app.get("/api/serial-ports")
    async def serial_ports():
        from serial.tools import list_ports
        # Ports ohne Hardware-Kennung (z. B. virtuelle /dev/ttyS*) weglassen
        return [{"device": p.device, "description": p.description} for p in list_ports.comports() if p.hwid != "n/a"]

    @app.post("/api/ble-scan")
    async def ble_scan():
        try:
            from bleak import BleakScanner
            devs = await BleakScanner.discover(timeout=5)
        except Exception as e:
            raise MeshError(f"Bluetooth nicht verfügbar: {e}")
        return [{"address": d.address, "name": d.name} for d in devs if d.name and d.name.startswith("MeshCore")]

    # ---- Nachrichten ----
    @app.post("/api/messages/send")
    async def send_msg(request: Request, b: SendMsg):
        await M(request).send_msg(b.conv, b.text)
        return ok

    @app.post("/api/messages/ack")
    async def send_ack(request: Request, b: Retry):
        """Schnellantwort auf eine Nachricht (Vorlage füllt der Server)."""
        await M(request).send_ack(b.conv, b.id)
        return ok

    @app.post("/api/messages/retry")
    async def retry(request: Request, b: Retry):
        await M(request).retry_msg(b.conv, b.id)
        return ok

    @app.post("/api/messages/sync")
    async def sync(request: Request):
        await M(request).sync_messages()
        return ok

    # ---- Kontakte ----
    @app.post("/api/contacts/reload")
    async def reload_contacts(request: Request):
        m = M(request)
        await m.load_contacts()
        return {"count": len(m.contacts)}

    @app.post("/api/contacts/dm")
    async def dm_contact(request: Request, b: Text):
        return await M(request).dm_contact(b.value)

    @app.post("/api/contacts/{key}/{action}")
    async def contact_action(request: Request, key: str, action: str):
        m = M(request)
        fn = {"reset-path": m.reset_path, "share": m.share_contact, "add": m.add_contact}.get(action)
        if not fn:
            return JSONResponse({"detail": "Unbekannte Aktion"}, status_code=404)
        await fn(key)
        return ok

    @app.delete("/api/contacts/{key}")
    async def remove_contact(request: Request, key: str):
        await M(request).remove_contact(key)
        return ok

    # ---- Kanäle & Regionen ----
    @app.put("/api/channels/{idx}/region")
    async def chan_region(request: Request, idx: int, b: Text):
        name = M(request).set_chan_region(idx, b.value)
        return {"name": name}

    @app.post("/api/region")
    async def region(request: Request, b: Text):
        await M(request).set_scope(b.value)
        return ok

    @app.post("/api/hash-mode")
    async def hash_mode(request: Request, b: Number):
        if b.value not in (0, 1, 2):
            raise MeshError("ungültiger Wert")
        await M(request).set_hash_mode(b.value)
        return ok

    @app.post("/api/regions/save")
    async def save_region(request: Request, b: Text):
        M(request).save_region(b.value)
        return ok

    @app.put("/api/settings/ack-template")
    async def ack_template(request: Request, b: Text):
        M(request).set_ack_template(b.value)
        return ok

    @app.put("/api/settings/notify")
    async def set_notify(request: Request, b: Text, key: str):
        M(request).set_notify(key, b.value)
        return ok

    # ---- Repeater verwalten & Trace ----
    @app.get("/api/remote")
    async def remote_info(request: Request, key: str):
        return M(request).remote_info(key)

    @app.post("/api/remote/login")
    async def remote_login(request: Request, b: Remote):
        return await M(request).remote_login(b.key, b.password, b.remember)

    @app.post("/api/remote/status")
    async def remote_status(request: Request, b: Remote):
        return await M(request).remote_status(b.key)

    @app.post("/api/remote/neighbours")
    async def remote_neighbours(request: Request, b: Remote):
        return await M(request).remote_neighbours(b.key)

    @app.post("/api/remote/cli")
    async def remote_cli(request: Request, b: Remote):
        await M(request).remote_cli(b.key, b.cmd)
        return ok

    @app.post("/api/trace")
    async def trace(request: Request, b: Text):
        return await M(request).trace(b.value)

    @app.put("/api/watch")
    async def set_watch(request: Request, b: Watch):
        M(request).set_watch(b.key, b.hours)
        return ok

    @app.post("/api/settings/ack-preview")
    async def ack_preview(request: Request, b: Text):
        return M(request).ack_preview(b.value)

    @app.put("/api/settings/auto-reply")
    async def auto_reply(request: Request, b: AutoReply, key: str):
        M(request).set_auto_reply(key, b.on, b.words, b.tpl, b.cooldown)
        return ok

    @app.put("/api/settings/push")
    async def set_push(request: Request, b: Push):
        M(request).set_push(b.model_dump())
        return ok

    @app.post("/api/push/test")
    async def test_push(request: Request):
        await M(request).test_push()
        return ok

    @app.put("/api/settings/lookup")
    async def set_lookup(request: Request, b: Lookup):
        M(request).set_lookup(b.on, b.url)
        return ok

    @app.get("/api/lookup")
    async def lookup(request: Request, q: str):
        mesh = M(request)
        if not mesh.lookup_cfg["on"]:
            raise MeshError("Suche auf CoreScope ist aus (Gerät › Einstellungen)")
        q = q.strip()
        if len(q) < 2:
            return []
        return await mesh.lookup(q)

    @app.put("/api/settings/extra-regions")
    async def extra_regions(request: Request, b: Text):
        M(request).set_extra_regions(b.value)
        return ok

    # ---- Hashtag-Räume ----
    @app.post("/api/rooms/probe")
    async def probe_room(request: Request, b: Text):
        return {"found": M(request).probe_room(b.value)}

    @app.post("/api/rooms/{name}/subscribe")
    async def subscribe_room(request: Request, name: str):
        await M(request).subscribe_room(name)
        return ok

    @app.delete("/api/rooms/{name}")
    async def forget_room(request: Request, name: str):
        M(request).forget_room(name)
        return ok

    # ---- Live-Traffic ----
    @app.post("/api/packets/clear")
    async def clear(request: Request):
        M(request).clear_packets()
        return ok

    @app.get("/api/stats")
    async def stats_(request: Request, hours: float = 24):
        return M(request).packet_stats(hours)

    @app.get("/api/stats/node")
    async def node_stats(request: Request, key: str = "", hash: str = "", name: str = "", ext: bool = False, hours: float = 24):
        if name and not key and not hash:  # Klick auf einen Absendernamen im Chat; ext: auch auf CoreScope suchen
            n = await M(request).node_by_name(name, ext=ext)
            if not n:
                raise M(request).unknown_name(name, ext)
            key = n["key"]
        await M(request).ensure_node(key, hash)
        return M(request).node_stats(key, hash, hours)

    @app.get("/api/packets/export")
    async def export(request: Request, fmt: str = "csv"):
        data, mime = M(request).export_packets("json" if fmt == "json" else "csv")
        name = "meshboard-traffic-" + datetime.now().strftime("%Y-%m-%dT%H%M%S") + (".json" if fmt == "json" else ".csv")
        return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/packets/replay")
    async def replay(request: Request, hours: float = 24):
        return M(request).replay(hours)

    @app.get("/api/packets/layout")
    async def layout(raw: str):
        """Abschnitte eines Rohpakets (Hex) für die Byte-Ansicht."""
        try:
            return packet_layout(bytes.fromhex(raw[:1024]))
        except ValueError:
            raise MeshError("ungültige Rohdaten")

    @app.get("/api/packets/{pid:int}")
    async def get_packet(request: Request, pid: int):
        return M(request).get_packet(pid)

    # ---- Gerät ----
    @app.post("/api/advert")
    async def advert(request: Request, b: Flood):
        await M(request).advert(b.flood)
        return ok

    @app.post("/api/device/stats")
    async def stats(request: Request):
        await M(request).refresh_stats()
        return ok

    @app.post("/api/device/name")
    async def name(request: Request, b: Text):
        await M(request).set_name(b.value)
        return ok

    @app.post("/api/device/position")
    async def position(request: Request, b: Position):
        await M(request).set_position(b.lat, b.lon)
        return ok

    @app.post("/api/device/tx")
    async def tx(request: Request, b: Number):
        await M(request).set_tx(b.value)
        return ok

    @app.post("/api/device/other")
    async def other(request: Request, b: Other):
        await M(request).set_other(b.autoAdd, b.locAdv)
        return ok

    @app.post("/api/device/time")
    async def set_time(request: Request):
        await M(request).set_time()
        return ok

    @app.post("/api/device/reboot")
    async def reboot(request: Request):
        await M(request).reboot()
        return ok

    @app.post("/api/log")
    async def set_log(request: Request, b: Switch):
        M(request).set_log(b.on)
        return ok

    @app.post("/api/wipe")
    async def wipe(request: Request):
        M(request).wipe()
        return ok

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():  # Browser fragen teils direkt danach
        return RedirectResponse("favicon.svg", status_code=301)

    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
    return app
