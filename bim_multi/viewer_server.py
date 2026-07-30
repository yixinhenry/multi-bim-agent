from __future__ import annotations

import atexit
import json
import mimetypes
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import projects, storage
from .domain import Identity, PROFILES


ROOT = Path(__file__).resolve().parent.parent
VIEWER_DIR = ROOT / "viewer"
DIST_DIR = VIEWER_DIR / "dist"
CONVERTER = VIEWER_DIR / "scripts" / "convert-ifc.mjs"
_SERVERS: list[ThreadingHTTPServer] = []


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, db_path: Path):
        super().__init__(address, ViewerHandler)
        self.db_path = db_path
        self.locks: dict[str, threading.Lock] = {}
        self.lock_guard = threading.Lock()

    def model_lock(self, key: str) -> threading.Lock:
        with self.lock_guard:
            return self.locks.setdefault(key, threading.Lock())


class ViewerHandler(BaseHTTPRequestHandler):
    server: ViewerServer

    def do_GET(self) -> None:
        request = urlparse(self.path)
        if request.path in {"/", "/index.html"}:
            self._file(DIST_DIR / "index.html", "text/html; charset=utf-8")
        elif request.path == "/fragment":
            self._fragment(parse_qs(request.query))
        elif request.path == "/fragments-worker.mjs":
            workers = list((DIST_DIR / "assets").glob("worker-*.mjs"))
            if len(workers) != 1:
                self.send_error(503, "Fragments worker is unavailable")
            else:
                self._file(workers[0], "text/javascript")
        else:
            self._static(request.path)

    def do_POST(self) -> None:
        request = urlparse(self.path)
        if request.path != "/selection":
            self.send_error(404)
            return
        self._selection()

    def _model_request(self, query) -> tuple[int, str, Path] | None:
        try:
            project_id = int(query["project_id"][0])
            kind = query["kind"][0].upper()
            _, path = projects.resolve_ifc(
                self.server.db_path, project_id, f"{kind}.ifc"
            )
            return project_id, kind, path
        except (KeyError, ValueError, FileNotFoundError):
            self.send_error(400, "Invalid project model")
            return None

    def _fragment(self, query) -> None:
        request = self._model_request(query)
        if request is None:
            return
        project_id, kind, model_path = request
        try:
            with self.server.model_lock(f"{project_id}:{kind}"):
                fragment = self._ensure_fragment(model_path)
        except Exception as exc:
            self.send_error(503, f"Fragments conversion failed: {exc}")
            return
        self._file(fragment, "application/octet-stream")

    def _ensure_fragment(self, model_path: Path) -> Path:
        fragment = model_path.with_suffix(".frag")
        if (
            fragment.is_file()
            and fragment.stat().st_mtime_ns >= model_path.stat().st_mtime_ns
        ):
            return fragment
        node = os.getenv("BIM_MULTI_NODE_PATH") or shutil.which("node")
        if not node:
            raise RuntimeError("Node.js was not found")
        if not CONVERTER.is_file() or not (VIEWER_DIR / "node_modules").is_dir():
            raise RuntimeError("Viewer dependencies are not installed")
        temporary = fragment.with_suffix(".frag.tmp")
        try:
            result = subprocess.run(
                [node, "--max-old-space-size=8192", str(CONVERTER), str(model_path), str(temporary)],
                cwd=VIEWER_DIR,
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout)[-1000:])
            temporary.replace(fragment)
        finally:
            temporary.unlink(missing_ok=True)
        return fragment

    def _selection(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 8192:
                raise ValueError("Invalid body")
            payload = json.loads(self.rfile.read(length))
            project_id = int(payload["project_id"])
            identity = Identity(payload["identity"])
            kind, model_path = projects.resolve_ifc(
                self.server.db_path, project_id, f"{payload['kind']}.ifc"
            )
            import ifcopenshell

            model = ifcopenshell.open(str(model_path))
            entity = None
            if payload.get("global_id"):
                entity = model.by_guid(str(payload["global_id"]))
            elif payload.get("step_id") is not None:
                entity = model.by_id(int(payload["step_id"]))
            if entity is None:
                raise ValueError("Entity not found")
            info = entity.get_info(recursive=False)
            storage.set_selection(
                self.server.db_path,
                project_id,
                identity,
                kind,
                entity.id(),
                entity.is_a(),
                info.get("GlobalId"),
                info.get("Name"),
            )
            profile = PROFILES[identity]
            storage.add_audit_event(
                self.server.db_path,
                {
                    "project_id": project_id,
                    "conversation_id": storage.ensure_conversation(
                        self.server.db_path, project_id, identity
                    ),
                    "agent_id": profile.agent_id,
                    "declared_role": profile.declared_role,
                    "target_file": f"{kind}.ifc",
                    "operation": "viewer_selection",
                    "tool_parameters": {"step_id": entity.id()},
                    "result_summary": f"{entity.is_a()} #{entity.id()}",
                    "boundary_violation": False,
                    "status": "completed",
                },
            )
            self._json(200, {
                "kind": kind,
                "step_id": entity.id(),
                "ifc_type": entity.is_a(),
                "global_id": info.get("GlobalId"),
                "name": info.get("Name"),
            })
        except Exception:
            self._json(400, {"error": "Invalid IFC selection"})

    def _static(self, request_path: str) -> None:
        path = (DIST_DIR / request_path.lstrip("/")).resolve()
        if not path.is_relative_to(DIST_DIR.resolve()) or not path.is_file():
            self.send_error(404)
            return
        self._file(path, mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    def _file(self, path: Path, content_type: str) -> None:
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            self.send_error(503, "Viewer has not been built")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _json(self, status: int, payload: dict) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args) -> None:
        return


def start_viewer_server(db_path: Path) -> str:
    server = ViewerServer(("127.0.0.1", 0), db_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _SERVERS.append(server)
    return f"http://127.0.0.1:{server.server_port}"


def stop_servers() -> None:
    for server in _SERVERS:
        server.shutdown()
        server.server_close()
    _SERVERS.clear()


atexit.register(stop_servers)
