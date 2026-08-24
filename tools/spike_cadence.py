#!/usr/bin/env python3
# Spike 01 MoonJules — instrumento de medicion contra el API de Jules (v1alpha).
# Comandos: snapshot | observe | analyze | probe {auth,cursor,terminal-send,rate,order}
# Credencial: env JULES_API_KEY (https://jules.google.com/settings#api). Nunca se loguea.
# Dry-run local: python3 mock_jules_api.py &  y  --base-url http://127.0.0.1:8377/v1alpha
import argparse
import asyncio
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE_DEFAULT = "https://jules.googleapis.com/v1alpha"
TERMINAL = {"COMPLETED", "FAILED"}
ACT_TYPES = ("planGenerated", "planApproved", "userMessaged", "agentMessaged",
             "progressUpdated", "sessionCompleted", "sessionFailed")


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def trunc(s, n=120):
    s = s or ""
    return s[:n] + "…" if len(s) > n else s


def act_type(a):
    return next((k for k in ACT_TYPES if k in a), "otro")


def qtile(vals, p):
    if not vals:
        return None
    v = sorted(vals)
    return v[min(len(v) - 1, max(0, math.ceil(p / 100 * len(v)) - 1))]


def fnum(x, w=8):
    return f"{x:>{w}.1f}" if isinstance(x, (int, float)) else f"{'—':>{w}}"


class Recorder:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(path, "a", buffering=1, encoding="utf-8")

    def write(self, obj):
        self.f.write(json.dumps(obj, ensure_ascii=False) + "\n")


class Api:
    def __init__(self, base, key, rec=None):
        self.rec = rec
        self.http = httpx.AsyncClient(base_url=base, timeout=30.0,
                                      headers={"x-goog-api-key": key})

    async def req(self, method, path, **kw):
        t0 = time.monotonic()
        r = await self.http.request(method, path, **kw)
        ms = round((time.monotonic() - t0) * 1000)
        if self.rec:
            hdr = {k.lower(): v for k, v in r.headers.items()
                   if k.lower() == "retry-after" or "ratelimit" in k.lower()
                   or "quota" in k.lower()}
            row = {"kind": "http", "t": iso(utcnow()), "path": path,
                   "status": r.status_code, "ms": ms}
            if hdr:
                row["headers"] = hdr
            self.rec.write(row)
        return r

    async def get_json(self, path, params=None):
        r = await self.req("GET", path, params=params or {})
        r.raise_for_status()
        return r.json()

    async def paged(self, path, key, page_size, max_pages, extra=None):
        out, token = [], None
        for _ in range(max_pages):
            params = dict(extra or {})
            params["pageSize"] = page_size
            if token:
                params["pageToken"] = token
            data = await self.get_json(path, params)
            out += data.get(key, [])
            token = data.get("nextPageToken")
            if not token:
                break
        return out

    async def sessions_all(self):
        return await self.paged("/sessions", "sessions", 100, 5)

    async def activities(self, session_name, cursor=None, max_pages=3):
        extra = {"filter": f'create_time > "{cursor}"'} if cursor else None
        return await self.paged(f"/{session_name}/activities", "activities",
                                100, max_pages, extra)

    async def aclose(self):
        await self.http.aclose()


def norm_session(x):
    x = x.strip()
    return x if x.startswith("sessions/") else f"sessions/{x}"


# ---------- snapshot ----------
async def cmd_snapshot(args):
    api = Api(args.base_url, args.key)
    try:
        src = (await api.get_json("/sources", {"pageSize": 50})).get("sources", [])
        print(f"sources ({len(src)}):")
        for s in src:
            gh = s.get("githubRepo") or {}
            print(f"  {s.get('name'):55} {gh.get('owner', '')}/{gh.get('repo', '')}")
        ses = await api.sessions_all()
        print(f"\nsessions no archivadas ({len(ses)}):")
        for s in ses:
            print(f"  {s.get('name'):22} {s.get('state', '?'):24} "
                  f"upd={s.get('updateTime', '')}  {trunc(s.get('title'), 44)}")
    finally:
        await api.aclose()


# ---------- observe ----------
async def cmd_observe(args):
    out = Path(args.out)
    rec = Recorder(out / "observaciones.jsonl")
    api = Api(args.base_url, args.key, rec)
    rec.write({"kind": "meta", "t": iso(utcnow()), "base": args.base_url,
               "interval": args.interval, "duration_min": args.duration})
    want = {norm_session(x) for x in args.sessions.split(",") if x.strip()} \
        if args.sessions else None
    known, last_state, closed = {}, {}, set()
    cursors = {}
    t_end = time.monotonic() + args.duration * 60
    cycle = 0
    try:
        while time.monotonic() < t_end:
            cycle += 1
            t0 = time.monotonic()
            t_cyc = utcnow()
            for s in await api.sessions_all():
                name, st = s.get("name"), s.get("state", "?")
                if want and name not in want:
                    continue
                rec.write({"kind": "session", "t": iso(t_cyc), "name": name,
                           "state": st, "updateTime": s.get("updateTime"),
                           "title": trunc(s.get("title"), 80)})
                prev = last_state.get(name)
                if prev is not None and prev != st:
                    rec.write({"kind": "transition", "t": iso(t_cyc), "name": name,
                               "from": prev, "to": st})
                last_state[name] = st
                # seguimos: no-terminales; y una pasada final al cerrar
                if st in TERMINAL and (name in closed or (name not in known and not want)):
                    continue
                cur = cursors.get(name) if args.incremental else None
                acts = await api.activities(name, cursor=cur)
                bag = known.setdefault(name, {})
                for a in sorted(acts, key=lambda x: x.get("createTime") or ""):
                    an = a.get("name")
                    if an in bag:
                        continue
                    bag[an] = a
                    rec.write({"kind": "activity", "t": iso(t_cyc), "session": name,
                               "name": an, "createTime": a.get("createTime"),
                               "originator": a.get("originator"),
                               "type": act_type(a),
                               "desc": trunc(a.get("description"), 120)})
                if bag:
                    cursors[name] = max(a.get("createTime") or "" for a in bag.values())
                if st in TERMINAL:
                    closed.add(name)
                if st == "IN_PROGRESS":
                    ag = [parse_ts(a["createTime"]) for a in bag.values()
                          if a.get("originator") == "agent" and a.get("createTime")]
                    if ag:
                        rec.write({"kind": "staleness", "t": iso(t_cyc),
                                   "session": name,
                                   "sec": round((t_cyc - max(ag)).total_seconds(), 1)})
            print(f"[ciclo {cycle}] sesiones seguidas={len(known)} "
                  f"acts={sum(len(v) for v in known.values())}", file=sys.stderr)
            await asyncio.sleep(max(0.0, args.interval - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        await api.aclose()
    print(f"observaciones en {out / 'observaciones.jsonl'}", file=sys.stderr)


# ---------- analyze ----------
def cmd_analyze(args):
    path = Path(args.out) / "observaciones.jsonl"
    acts, stal, final, trans = {}, {}, {}, {}
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        k = r.get("kind")
        if k == "activity":
            acts.setdefault(r["session"], {})[r["name"]] = r
        elif k == "staleness":
            stal.setdefault(r["session"], []).append(r["sec"])
        elif k == "session":
            final[r["name"]] = r["state"]
        elif k == "transition":
            trans.setdefault(r["name"], []).append(f"{r['from']}→{r['to']}")
    rows = []
    for s in sorted(set(acts) | set(stal)):
        a = sorted(acts.get(s, {}).values(), key=lambda x: x.get("createTime") or "")
        ag = [parse_ts(x["createTime"]) for x in a
              if x.get("originator") == "agent" and x.get("createTime")]
        gaps = [(b - c).total_seconds() for c, b in zip(ag, ag[1:])]
        st = stal.get(s, [])
        rows.append({"sesion": s, "final": final.get(s, "?"), "acts": len(a),
                     "agente": len(ag), "gap_med": qtile(gaps, 50),
                     "gap_p90": qtile(gaps, 90), "gap_max": max(gaps) if gaps else None,
                     "stal_p95": qtile(st, 95), "stal_max": max(st) if st else None,
                     "trans": " ".join(trans.get(s, []))})
    hdr = (f"{'sesion':<24} {'final':<22} {'acts':>4} {'ag':>3} {'gap_med':>8} "
           f"{'gap_p90':>8} {'gap_max':>8} {'stal_p95':>8} {'stal_max':>8}")
    lines = [hdr, "-" * len(hdr)]
    for r in rows:
        lines.append(f"{r['sesion'].removeprefix('sessions/'):<24} {r['final']:<22} "
                     f"{r['acts']:>4} {r['agente']:>3} {fnum(r['gap_med'])} "
                     f"{fnum(r['gap_p90'])} {fnum(r['gap_max'])} "
                     f"{fnum(r['stal_p95'])} {fnum(r['stal_max'])}")
    sane = [r for r in rows if r["final"] == "COMPLETED" and r["gap_max"]]
    if sane:
        peak = max(max(r["gap_max"], r["stal_max"] or 0) for r in sane)
        n = math.ceil(peak * 1.5)
        lines += ["", f"pico observado en sesiones sanas: {peak:.1f} s",
                  f"umbral N sugerido (pico x 1.5): {n} s"]
    else:
        lines += ["", "sin sesiones COMPLETED con gaps: no hay base para sugerir N"]
    report = "\n".join(lines)
    print(report)
    (Path(args.out) / "resumen.txt").write_text(report + "\n", encoding="utf-8")
    with open(Path(args.out) / "resumen.csv", "w", encoding="utf-8") as f:
        cols = ["sesion", "final", "acts", "agente", "gap_med", "gap_p90",
                "gap_max", "stal_p95", "stal_max", "trans"]
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join("" if r[c] is None else str(r[c]) for c in cols) + "\n")


# ---------- backfill: cadencia retrospectiva ----------
async def cmd_backfill(args):
    out = Path(args.out)
    rec = Recorder(out / "backfill.jsonl")
    api = Api(args.base_url, args.key, rec)
    try:
        ses = await api.paged("/sessions", "sessions", 100, 40,
                              {"filter": "archived = true OR archived = false"})
        census = {}
        for s in ses:
            census[s.get("state", "?")] = census.get(s.get("state", "?"), 0) + 1
        total = len(ses)
        print(f"censo de {total} sesiones:")
        for st, n in sorted(census.items(), key=lambda kv: -kv[1]):
            print(f"  {st:24} {n:5}  {100*n/total:5.1f}%")
        no_ok = total - census.get("COMPLETED", 0)
        print(f"\nno-COMPLETED: {no_ok} ({100*no_ok/total:.1f}%)  "
              f"— el Brief estima 1 de cada 3")
        rec.write({"kind": "census", "t": iso(utcnow()), "total": total,
                   "by_state": census})
        if args.census_only:
            return
        wanted = [s.strip() for s in args.states.split(",") if s.strip()]
        sample = []
        for st in wanted:
            pool = [s for s in ses if s.get("state") == st]
            pool.sort(key=lambda s: s.get("createTime") or "", reverse=True)
            sample += pool[:args.per_state]
        print(f"\nmuestreando {len(sample)} sesiones…", file=sys.stderr)
        rows = []
        for s in sample:
            name, st = s["name"], s.get("state", "?")
            try:
                acts = await api.activities(name, max_pages=10)
            except httpx.HTTPStatusError as e:
                print(f"  {name}: HTTP {e.response.status_code}", file=sys.stderr)
                continue
            acts.sort(key=lambda a: a.get("createTime") or "")
            if not acts:
                continue
            ag = [parse_ts(a["createTime"]) for a in acts
                  if a.get("originator") == "agent" and a.get("createTime")]
            gaps = [(b - c).total_seconds() for c, b in zip(ag, ag[1:])]
            t0, t1 = parse_ts(acts[0]["createTime"]), parse_ts(acts[-1]["createTime"])
            tail = act_type(acts[-1])
            # cola: del ultimo evento del agente al ultimo latido de la sesion
            upd = parse_ts(s["updateTime"]) if s.get("updateTime") else t1
            row = {"name": name, "state": st, "n_act": len(acts), "n_agent": len(ag),
                   "dur_s": (t1 - t0).total_seconds(),
                   "gap_med": qtile(gaps, 50), "gap_p90": qtile(gaps, 90),
                   "gap_p99": qtile(gaps, 99), "gap_max": max(gaps) if gaps else None,
                   "tail_type": tail,
                   "tail_orig": acts[-1].get("originator"),
                   "silencio_final_s": (upd - ag[-1]).total_seconds() if ag else None,
                   "createTime": s.get("createTime"), "gaps": gaps}
            rows.append(row)
            rec.write({k: v for k, v in row.items() if k != "gaps"} |
                      {"kind": "session_backfill", "t": iso(utcnow())})
        by = {}
        for r in rows:
            by.setdefault(r["state"], []).append(r)
        print(f"\n{'estado':<24} {'n':>3} {'acts_med':>8} {'gap_med':>8} {'gap_p90':>8} "
              f"{'gap_p99':>8} {'gap_max':>9} {'dur_med_m':>9}")
        print("-" * 90)
        for st in wanted:
            rs = by.get(st, [])
            if not rs:
                continue
            allg = [g for r in rs for g in r["gaps"]]
            print(f"{st:<24} {len(rs):>3} "
                  f"{qtile([r['n_act'] for r in rs], 50):>8} "
                  f"{fnum(qtile(allg, 50))} {fnum(qtile(allg, 90))} "
                  f"{fnum(qtile(allg, 99))} {fnum(max(allg) if allg else None, 9)} "
                  f"{fnum(qtile([r['dur_s'] for r in rs], 50) / 60 if rs else None, 9)}")
        okg = [g for r in rows if r["state"] == "COMPLETED" for g in r["gaps"]]
        if okg:
            p50, p90, p99 = qtile(okg, 50), qtile(okg, 90), qtile(okg, 99)
            mx = max(okg)
            print(f"\nsesiones COMPLETED — distribucion de huecos entre eventos del agente")
            print(f"  n={len(okg)}  p50={p50:.0f}s  p90={p90:.0f}s  p99={p99:.0f}s  "
                  f"max={mx:.0f}s ({mx/60:.1f} min)")
            for mult, etq in ((1.5, "agresivo"), (2.0, "equilibrado"), (3.0, "conservador")):
                n = mx * mult
                fp = sum(1 for g in okg if g > n)
                print(f"  N = max x{mult} = {n/60:6.1f} min -> {etq:12} "
                       f"huecos sanos por encima: {fp}")
        # cola de silencio: separa terminales de estancadas
        print(f"\nsilencio final (ultimo evento del agente -> updateTime), por estado:")
        for st in wanted:
            v = [r["silencio_final_s"] for r in by.get(st, [])
                 if r["silencio_final_s"] is not None]
            if v:
                print(f"  {st:<24} n={len(v):>3}  p50={qtile(v,50):9.1f}s  "
                      f"max={max(v):11.1f}s")
        print(f"\ntipo del ultimo evento, por estado:")
        for st in wanted:
            tt = {}
            for r in by.get(st, []):
                k = f"{r['tail_type']}/{r['tail_orig']}"
                tt[k] = tt.get(k, 0) + 1
            if tt:
                print(f"  {st:<24} " + ", ".join(f"{k}×{v}" for k, v in
                                                 sorted(tt.items(), key=lambda x: -x[1])))
    finally:
        await api.aclose()


# ---------- nudges: separa hueco sano de estancamiento ----------
RESCUE = ("completa", "continu", "contin\u00fa", "sigue", "termina", "prosigue",
          "retoma", "adelante", "procede", "avanza", "?")


def is_rescue(txt):
    t = (txt or "").strip().lower()
    return len(t) <= 120 and any(k in t for k in RESCUE)


async def cmd_nudges(args):
    out = Path(args.out)
    rec = Recorder(out / "nudges.jsonl")
    api = Api(args.base_url, args.key, rec)
    try:
        ses = await api.paged("/sessions", "sessions", 100, 40,
                              {"filter": "archived = true OR archived = false"})
        pool = [s for s in ses if s.get("state") in args.states.split(",")]
        pool.sort(key=lambda s: s.get("createTime") or "", reverse=True)
        pool = pool[:args.n]
        print(f"analizando {len(pool)} sesiones…", file=sys.stderr)
        clean, stall, resp, per_ses, ejemplos = [], [], [], [], []
        n_rescatadas = n_sin_resp = 0
        for i, s in enumerate(pool):
            try:
                acts = await api.activities(s["name"], max_pages=10)
            except httpx.HTTPStatusError:
                continue
            acts.sort(key=lambda a: a.get("createTime") or "")
            ev = [(parse_ts(a["createTime"]), a.get("originator"), act_type(a), a)
                  for a in acts if a.get("createTime")]
            rescates = 0
            for j, (t, orig, typ, a) in enumerate(ev):
                if orig == "agent" and j and ev[j - 1][1] == "agent":
                    clean.append((t - ev[j - 1][0]).total_seconds())  # agente->agente
                if typ != "userMessaged" or j == 0:
                    continue
                txt = (a.get("userMessaged") or {}).get("userMessage", "")
                if not is_rescue(txt):
                    continue
                prev = next((e for e in reversed(ev[:j]) if e[1] == "agent"), None)
                nxt = next((e for e in ev[j + 1:] if e[1] == "agent"), None)
                if not prev:
                    continue
                sil = (t - prev[0]).total_seconds()
                stall.append(sil)
                rescates += 1
                if nxt:
                    resp.append((nxt[0] - t).total_seconds())
                else:
                    n_sin_resp += 1
                if len(ejemplos) < 6:
                    ejemplos.append((sil, trunc(txt.replace("\n", " "), 64)))
            if rescates:
                n_rescatadas += 1
            per_ses.append((s["name"], s.get("state"), rescates))
            if (i + 1) % 25 == 0:
                print(f"  {i+1}/{len(pool)}", file=sys.stderr)
        rec.write({"kind": "nudge_summary", "t": iso(utcnow()),
                   "sesiones": len(per_ses), "rescatadas": n_rescatadas,
                   "n_clean": len(clean), "n_stall": len(stall)})
        n = len(per_ses)
        print(f"\nsesiones analizadas: {n}")
        print(f"sesiones con >=1 rescate manual: {n_rescatadas} "
              f"({100*n_rescatadas/max(n,1):.1f}%)")
        print(f"rescates totales: {len(stall)}  |  sin respuesta del agente: {n_sin_resp}")

        def dist(v, etq):
            if not v:
                return
            print(f"\n{etq}  n={len(v)}")
            for p in (50, 75, 90, 95, 99):
                print(f"  p{p:<3} {qtile(v,p)/60:9.2f} min")
            print(f"  max  {max(v)/60:9.2f} min   min {min(v)/60:9.2f} min")

        dist(clean, "HUECOS SANOS (agente->agente, sin rescate de por medio)")
        dist(stall, "SILENCIO ANTES DE UN RESCATE MANUAL (= estancamiento real)")
        dist(resp, "LATENCIA DE RESPUESTA AL RESCATE (mide el prompt magico)")
        if clean and stall:
            print("\nseparabilidad — falsos positivos vs cobertura:")
            print(f"  {'N (min)':>8} {'sanos>N':>9} {'FP %':>7} {'estanc>N':>9} {'cobertura':>10}")
            for n_min in (5, 10, 15, 20, 30, 45, 60, 90, 120):
                sec = n_min * 60
                fp = sum(1 for g in clean if g > sec)
                tp = sum(1 for g in stall if g > sec)
                print(f"  {n_min:>8} {fp:>9} {100*fp/len(clean):>6.2f}% "
                      f"{tp:>9} {100*tp/len(stall):>9.1f}%")
        if ejemplos:
            print("\nejemplos de rescate (silencio previo -> texto):")
            for sil, txt in sorted(ejemplos, reverse=True):
                print(f"  {sil/60:7.1f} min  \"{txt}\"")
    finally:
        await api.aclose()


# ---------- probes ----------
async def probe_auth(api, args):
    r = await api.req("GET", "/sources", params={"pageSize": 1})
    print("status:", r.status_code)
    if r.status_code != 200:
        e = r.json().get("error", {})
        det = (e.get("details") or [{}])[0]
        print("error.status:", e.get("status"), "| reason:", det.get("reason"))
        print("mensaje:", trunc(e.get("message"), 160))
    else:
        print("credencial valida; sources visibles:",
              len(r.json().get("sources", [])))


async def probe_order(api, args):
    ses = (await api.get_json("/sessions", {"pageSize": 10})).get("sessions", [])
    if ses:
        print("sessions.list pagina 1 — createTime primero/ultimo:")
        print("  ", ses[0].get("createTime"), "…", ses[-1].get("createTime"))
    tgt = norm_session(args.session) if args.session else (ses and ses[0]["name"])
    if tgt:
        acts = (await api.get_json(f"/{tgt}/activities",
                                   {"pageSize": 20})).get("activities", [])
        if acts:
            print(f"{tgt} activities pagina 1 — createTime primero/ultimo:")
            print("  ", acts[0].get("createTime"), "…", acts[-1].get("createTime"))


async def probe_cursor(api, args):
    tgt = norm_session(args.session)
    acts = sorted((await api.activities(tgt)),
                  key=lambda a: a.get("createTime") or "")
    if len(acts) < 3:
        print("se requieren >=3 actividades en la sesion")
        return
    pivot = acts[len(acts) // 2]
    t = pivot["createTime"]
    print(f"pivot: {pivot['name']} @ {t}")
    r1 = await api.req("GET", f"/{tgt}/activities",
                       params={"filter": f'create_time > "{t}"', "pageSize": 100})
    print(f'filter=create_time > "…" -> {r1.status_code}')
    if r1.status_code == 200:
        names = [a["name"] for a in r1.json().get("activities", [])]
        earlier = [a for a in acts if a["createTime"] < t and a["name"] in names]
        print("  pivot incluido:", pivot["name"] in names,
              "| anteriores colados:", len(earlier),
              "| n:", len(names), "->",
              "EXCLUSIVO (cursor seguro con >)" if pivot["name"] not in names
              and not earlier else "REVISAR")
    r2 = await api.req("GET", f"/{tgt}/activities",
                       params={"createTime": t, "pageSize": 100})
    inc = None
    if r2.status_code == 200:
        names2 = [a["name"] for a in r2.json().get("activities", [])]
        inc = pivot["name"] in names2
    print(f"param legado createTime=… -> {r2.status_code}"
          + (f" | pivot incluido: {inc}" if inc is not None else ""))


async def probe_terminal(api, args):
    tgt = norm_session(args.session)
    s = await api.get_json(f"/{tgt}")
    st = s.get("state")
    print("estado actual:", st)
    if st not in TERMINAL and not args.force:
        print("la sesion no es terminal; abortando (usa --force bajo tu criterio)")
        return
    if not args.yes:
        print("agrega --yes para enviar realmente el mensaje de prueba")
        return
    r = await api.req("POST", f"/{tgt}:sendMessage",
                      json={"prompt": "[spike] ping benigno, ignorar"})
    print("sendMessage ->", r.status_code)
    print(trunc(r.text, 400))


async def probe_rate(api, args):
    statuses, seen = {}, {}
    step = args.window / max(args.n, 1)
    for i in range(args.n):
        r = await api.req("GET", "/sources", params={"pageSize": 1})
        statuses[r.status_code] = statuses.get(r.status_code, 0) + 1
        for k, v in r.headers.items():
            if k.lower() == "retry-after" or "ratelimit" in k.lower():
                seen[k] = v
        if r.status_code == 429:
            print("429 en request", i + 1, "| retry-after:",
                  r.headers.get("retry-after"))
            break
        await asyncio.sleep(step)
    print("statuses:", statuses)
    print("headers de cuota vistos:", seen or "ninguno")


async def cmd_probe(args):
    rec = Recorder(Path(args.out) / "probes.jsonl")
    api = Api(args.base_url, args.key, rec)
    try:
        await {"auth": probe_auth, "cursor": probe_cursor, "order": probe_order,
               "terminal-send": probe_terminal, "rate": probe_rate}[args.which](api, args)
    finally:
        await api.aclose()


def main():
    p = argparse.ArgumentParser(description="Spike 01 MoonJules — cadencia API Jules")
    p.add_argument("--base-url", default=BASE_DEFAULT)
    p.add_argument("--out", default="./spike_out")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot")
    ob = sub.add_parser("observe")
    ob.add_argument("--interval", type=float, default=60.0, help="segundos entre ciclos")
    ob.add_argument("--duration", type=float, default=240.0, help="minutos totales")
    ob.add_argument("--sessions", default="", help="ids separados por coma (opcional)")
    ob.add_argument("--incremental", action="store_true",
                    help="usar cursor create_time (validar antes con probe cursor)")
    sub.add_parser("analyze")
    bf = sub.add_parser("backfill", help="reconstruye cadencia desde sesiones historicas")
    bf.add_argument("--per-state", type=int, default=12,
                    help="sesiones a muestrear por estado")
    bf.add_argument("--states", default="COMPLETED,FAILED,PAUSED,IN_PROGRESS,"
                                        "AWAITING_USER_FEEDBACK,AWAITING_PLAN_APPROVAL,QUEUED")
    bf.add_argument("--census-only", action="store_true")
    nu = sub.add_parser("nudges", help="separa hueco sano de estancamiento via rescates")
    nu.add_argument("--n", type=int, default=60)
    nu.add_argument("--states", default="COMPLETED")
    pr = sub.add_parser("probe")
    pr.add_argument("which", choices=["auth", "cursor", "order", "terminal-send", "rate"])
    pr.add_argument("--session", default="")
    pr.add_argument("--yes", action="store_true")
    pr.add_argument("--force", action="store_true")
    pr.add_argument("--n", type=int, default=30)
    pr.add_argument("--window", type=float, default=30.0)
    args = p.parse_args()
    args.key = os.environ.get("JULES_API_KEY", "")
    if not args.key:
        sys.exit("falta JULES_API_KEY en el entorno "
                 "(se obtiene en https://jules.google.com/settings#api)")
    if args.cmd == "analyze":
        cmd_analyze(args)
    else:
        asyncio.run({"snapshot": cmd_snapshot, "observe": cmd_observe, "backfill": cmd_backfill, "nudges": cmd_nudges,
                     "probe": cmd_probe}[args.cmd](args))


if __name__ == "__main__":
    main()
