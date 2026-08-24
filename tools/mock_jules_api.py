#!/usr/bin/env python3
# Mock del API de Jules (v1alpha) para validar spike_cadence.py sin credenciales.
# Esquemas: discovery doc real (revision 20260821). Envolturas de error: copiadas
# de sondeos reales a jules.googleapis.com (2026-08-24).
# Reloj comprimido: una sesion "sana" dura ~80 s (gaps 3-9 s en vez de minutos).
# Supuestos marcados con [SUPUESTO]: ordenamiento de listas, originator de
# planApproved, respuesta de sendMessage sobre sesion terminal.
import json
import random
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

LOCK = threading.Lock()
ACTIVE = {"QUEUED", "PLANNING", "AWAITING_PLAN_APPROVAL", "AWAITING_USER_FEEDBACK", "IN_PROGRESS"}

ERR_401_MISSING = {  # real: GET sin credencial
    "error": {"code": 401,
              "message": "Request is missing required authentication credential. "
                         "Expected OAuth 2 access token, login cookie or other valid "
                         "authentication credential.",
              "status": "UNAUTHENTICATED",
              "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                           "reason": "CREDENTIALS_MISSING", "domain": "googleapis.com"}]}}

ERR_400_PRECOND = {  # [SUPUESTO] sendMessage sobre sesion terminal: verificar con key real
    "error": {"code": 400, "message": "Session is not active.",
              "status": "FAILED_PRECONDITION"}}


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")


class Sess:
    def __init__(self, sid, title):
        self.d = {"name": f"sessions/{sid}", "id": sid, "title": title,
                  "prompt": f"[mock] {title}", "state": "QUEUED", "archived": False,
                  "url": f"https://jules.google.com/session/{sid}",
                  "sourceContext": {"source": "sources/github-abnerhdz-moonjules-sandbox",
                                    "githubRepoContext": {"startingBranch": "main"}},
                  "createTime": iso(now()), "updateTime": iso(now())}
        self.acts = []
        self.resume = threading.Event()

    def touch(self):
        self.d["updateTime"] = iso(now())

    def act(self, originator, event_key, event_val, desc):
        n = len(self.acts) + 1
        self.acts.append({"name": f"{self.d['name']}/activities/a{n:03d}", "id": f"a{n:03d}",
                          "originator": originator, "description": desc,
                          event_key: event_val, "createTime": iso(now())})
        self.touch()

    def set_state(self, st):
        self.d["state"] = st
        self.touch()


SESSIONS = {}


def plan_common(s):
    time.sleep(2)
    with LOCK:
        s.set_state("PLANNING")
        s.act("agent", "planGenerated",
              {"plan": {"id": "p1", "steps": [
                  {"id": "s1", "index": 0, "title": "Analizar codigo"},
                  {"id": "s2", "index": 1, "title": "Aplicar cambios"}],
                  "createTime": iso(now())}}, "Plan generated")
    time.sleep(2)
    with LOCK:
        s.act("system", "planApproved", {"planId": "p1"}, "Plan approved")  # [SUPUESTO] originator
        s.set_state("IN_PROGRESS")


def run_healthy(s, work_s=70):
    plan_common(s)
    t0, i = time.monotonic(), 0
    while time.monotonic() - t0 < work_s:
        time.sleep(random.uniform(3, 9))
        i += 1
        with LOCK:
            if i % 2:
                s.act("agent", "progressUpdated",
                      {"title": f"Paso {i}", "description": "Trabajando"}, f"Progress {i}")
            else:
                s.act("agent", "agentMessaged",
                      {"agentMessage": f"Avance {i} listo."}, f"Agent message {i}")
    with LOCK:
        s.act("agent", "sessionCompleted", {}, "Session completed")
        s.d["outputs"] = [{"pullRequest": {
            "url": f"https://github.com/abnerhdz/moonjules-sandbox/pull/{random.randint(10, 99)}",
            "title": s.d["title"], "baseRef": "main", "headRef": f"jules-{s.d['id']}"}}]
        s.set_state("COMPLETED")


def run_hung(s):
    plan_common(s)
    for i in range(1, 4):
        time.sleep(random.uniform(3, 7))
        with LOCK:
            s.act("agent", "progressUpdated", {"title": f"Paso {i}"}, f"Progress {i}")
    # silencio permanente: estado queda IN_PROGRESS, updateTime congelado


def run_feedback(s):
    plan_common(s)
    time.sleep(4)
    with LOCK:
        s.act("agent", "agentMessaged",
              {"agentMessage": "Debo actualizar tambien los tests?"}, "Question")
        s.set_state("AWAITING_USER_FEEDBACK")
    s.resume.wait()  # sendMessage lo despierta
    with LOCK:
        s.set_state("IN_PROGRESS")
    for i in range(2):
        time.sleep(random.uniform(3, 6))
        with LOCK:
            s.act("agent", "progressUpdated", {"title": f"Retomado {i+1}"}, "Progress")
    with LOCK:
        s.act("agent", "sessionCompleted", {}, "Session completed")
        s.set_state("COMPLETED")


def run_failed(s):
    plan_common(s)
    for i in range(2):
        time.sleep(random.uniform(3, 6))
        with LOCK:
            s.act("agent", "progressUpdated", {"title": f"Paso {i+1}"}, "Progress")
    with LOCK:
        s.act("agent", "sessionFailed",
              {"reason": "Unable to install dependencies"}, "Session failed")
        s.set_state("FAILED")


SCRIPTS = [("mock-h1", "Sana 1: docstrings", run_healthy),
           ("mock-h2", "Sana 2: renombrar util", run_healthy),
           ("mock-h3", "Sana 3: test unitario", run_healthy),
           ("mock-hung", "Colgada silenciosa", run_hung),
           ("mock-fb", "Pide feedback", run_feedback),
           ("mock-fail", "Falla declarada", run_failed)]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        if not self.headers.get("x-goog-api-key"):
            self._json(401, ERR_401_MISSING)
            return False
        return True

    def _paginate(self, items, q, key, default_ps):
        ps = min(int(q.get("pageSize", [default_ps])[0]), 100)
        off = int(q.get("pageToken", ["0"])[0] or 0)
        page = items[off:off + ps]
        out = {key: page}
        if off + ps < len(items):
            out["nextPageToken"] = str(off + ps)
        return out

    def do_GET(self):
        if not self._auth():
            return
        u = urlparse(self.path)
        q = parse_qs(u.query)
        with LOCK:
            if u.path == "/v1alpha/sources":
                return self._json(200, {"sources": [{
                    "name": "sources/github-abnerhdz-moonjules-sandbox",
                    "id": "github-abnerhdz-moonjules-sandbox",
                    "githubRepo": {"owner": "abnerhdz", "repo": "moonjules-sandbox",
                                   "isPrivate": True}}]})
            if u.path == "/v1alpha/sessions":
                flt = q.get("filter", [""])[0]
                want_archived = "archived = true" in flt and "false" not in flt
                items = [dict(s.d) for s in SESSIONS.values()
                         if s.d["archived"] == want_archived or "OR" in flt]
                items.sort(key=lambda x: x["createTime"], reverse=True)  # [SUPUESTO] orden
                return self._json(200, self._paginate(items, q, "sessions", 30))
            m = re.fullmatch(r"/v1alpha/(sessions/([\w-]+))/activities", u.path)
            if m:
                s = SESSIONS.get(m.group(2))
                if not s:
                    return self._json(404, {"error": {"code": 404, "message": "Not found",
                                                     "status": "NOT_FOUND"}})
                acts = sorted(s.acts, key=lambda a: a["createTime"])  # [SUPUESTO] orden asc
                flt = q.get("filter", [""])[0]
                fm = re.search(r'create_time\s*>\s*"([^"]+)"', flt)
                cursor = fm.group(1) if fm else q.get("createTime", [None])[0]
                if cursor:
                    acts = [a for a in acts if a["createTime"] > cursor]  # exclusivo (AIP-160 >)
                return self._json(200, self._paginate(acts, q, "activities", 50))
            m = re.fullmatch(r"/v1alpha/sessions/([\w-]+)", u.path)
            if m and m.group(1) in SESSIONS:
                return self._json(200, dict(SESSIONS[m.group(1)].d))
        self._json(404, {"error": {"code": 404, "message": "Not found", "status": "NOT_FOUND"}})

    def do_POST(self):
        if not self._auth():
            return
        u = urlparse(self.path)
        m = re.fullmatch(r"/v1alpha/sessions/([\w-]+):(\w+)", u.path)
        if not m or m.group(1) not in SESSIONS:
            return self._json(404, {"error": {"code": 404, "message": "Not found",
                                              "status": "NOT_FOUND"}})
        s, verb = SESSIONS[m.group(1)], m.group(2)
        ln = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(ln) or b"{}") if ln else {}
        with LOCK:
            st = s.d["state"]
            if verb == "sendMessage":
                if st not in ACTIVE:
                    return self._json(400, ERR_400_PRECOND)
                s.act("user", "userMessaged",
                      {"userMessage": body.get("prompt", "")}, "User message")
                if st == "AWAITING_USER_FEEDBACK":
                    s.resume.set()
                return self._json(200, {})
            if verb == "approvePlan":
                return self._json(200, {})
            if verb in ("archive", "unarchive"):
                s.d["archived"] = (verb == "archive")
                s.touch()
                return self._json(200, {})
        self._json(404, {"error": {"code": 404, "message": "Not found", "status": "NOT_FOUND"}})


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8377
    for sid, title, fn in SCRIPTS:
        s = Sess(sid, title)
        SESSIONS[sid] = s
        threading.Thread(target=fn, args=(s,), daemon=True).start()
        time.sleep(0.3)
    print(f"mock Jules API en http://127.0.0.1:{port}/v1alpha", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
