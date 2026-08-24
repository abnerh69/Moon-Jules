"""CLI de Moon-Jules.

Comandos implementados en esta entrega:
  doctor   verifica credencial, config y conectividad
  sources  lista los repositorios conectados a Jules
  status   una pasada: dictamina cada sesion y muestra el veredicto
  watch    el bucle de vigilancia (ADR-001)

Pendientes de epica (ver docs/BACKLOG.md): assign-next, pause, calibrate.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import __version__
from .client import JulesClient
from .config import CONFIG_PATH, Config, load
from .detector import (
    Action,
    Finding,
    Freshness,
    Policy,
    Report,
    Verdict,
    assess,
    freshness,
    humano,
)
from .errors import ConfigError, MoonJulesError, NotFoundError
from .lock import AlreadyRunningError, InstanceLock
from .logs import configure as configure_logs
from .logs import get as get_logger
from .models import AutonomyMode, Session, SessionState
from .notify import Notifier
from .store import GLOBAL_SCOPE, Store

TERMINAL = {SessionState.COMPLETED, SessionState.FAILED}

log = get_logger("cli")

#: Se guarda cuando ya se busco la razon de un fallo y no habia ninguna.
#: Sin este centinela, una sesion FAILED sin actividad `sessionFailed`
#: se re-consultaria en cada ciclo para siempre: en el enjambre real,
#: 4 de cada 11 fallidas no declaran razon.
SIN_RAZON = "(sin razon declarada)"

GLYPH = {
    "healthy": "ok",
    "done": "--",
    "stalled": "!!",
    "blocked_feedback": "??",
    "blocked_plan": "??",
    "queued_slow": "..",
    "paused_stale": "!!",
    "failed": "XX",
    "nudge_unanswered": "!!",
    "nudge_budget_spent": "!!",
}


def now() -> datetime:
    return datetime.now(UTC)


DURACION = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
UNIDADES = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duracion(texto: str) -> timedelta:
    """`30m`, `2h`, `1d`. Explicito a proposito: un numero suelto es ambiguo."""
    m = DURACION.match(texto)
    if not m:
        raise ValueError(
            f"duracion invalida: {texto!r}. Usa un numero y una unidad: 30m, 2h, 1d."
        )
    return timedelta(seconds=int(m.group(1)) * UNIDADES[m.group(2).lower()])


def columna(segundos: float | None) -> str:
    """`humano()` alineado a la anchura de la columna."""
    return f"{humano(segundos).replace(' ', ''):>5}"


class Progress:
    """Avisa por stderr de que el ciclo sigue vivo.

    Con 538 sesiones el primer `status` tarda decenas de segundos, y sin
    señal de vida el usuario concluye —razonablemente— que se colgó. Es
    la misma lección del proyecto entero: el silencio no distingue entre
    trabajar y estar muerto.

    Va a stderr y solo si es una terminal, para no ensuciar tuberias ni
    logs. Se borra la linea al terminar: es andamio, no salida.
    """

    def __init__(self, *, enabled: bool = True, stream: object | None = None) -> None:
        self.stream = stream or sys.stderr
        self.enabled = enabled and bool(getattr(self.stream, "isatty", lambda: False)())
        self._ancho = 0

    def step(self, texto: str) -> None:
        if not self.enabled:
            return
        linea = f"  {texto}…"
        self.stream.write("\r" + linea.ljust(self._ancho))
        self.stream.flush()
        self._ancho = max(self._ancho, len(linea))

    def done(self) -> None:
        if not self.enabled:
            return
        self.stream.write("\r" + " " * self._ancho + "\r")
        self.stream.flush()
        self._ancho = 0


@dataclass
class Monitor:
    """Un ciclo de vigilancia. ADR-001: poll global + actividades incrementales."""

    client: JulesClient
    config: Config
    store: object | None = None  # Store, opcional para `status` en seco
    _reasons: dict[str, str | None] = field(default_factory=dict)

    async def cycle(
        self,
        *,
        execute: bool = False,
        progress: Progress | None = None,
        full: bool = False,
    ) -> Report:
        at = now()
        report = Report(at=at)
        prog = progress or Progress(enabled=False)

        sessions = await self._collect(full=full, prog=prog)

        acked = self.store.acked_pairs() if self.store else set()
        nudges = self.store.last_nudges() if self.store else {}
        conocidas = self.store.failure_reasons() if self.store else {}
        pausas = self.store.active_pauses(at) if self.store else {}
        report.paused = {k: (r["reason"] or "") for k, r in pausas.items()}

        # Solo las no terminales necesitan red: sobre COMPLETED y FAILED
        # el reloj estaria congelado igualmente (ADR-002), y la razon de
        # fallo, si hace falta, se busca una sola vez y se cachea.
        pendientes = [
            s
            for s in sessions
            if s.state not in TERMINAL
            or (s.state is SessionState.FAILED and s.name not in conocidas)
        ]
        prog.step(f"{len(sessions)} sesiones, consultando {len(pendientes)}")
        datos = await self._gather(pendientes, prog)

        for s in sessions:
            fresh, cursor = datos.get(s.name) or self._offline_freshness(s)
            if s.state is SessionState.FAILED:
                s = s.with_failure(conocidas.get(s.name) or self._reasons.get(s.name))
            src = self.config.for_source(s.source)
            if pausas and (GLOBAL_SCOPE in pausas or s.source in pausas):
                # La pausa degrada a read_only por el mismo camino que el
                # modo configurado: ninguna escritura sale de aqui.
                src = replace(src, mode=AutonomyMode.READ_ONLY)
            nudge = nudges.get(s.name)
            finding = assess(
                s, fresh, at, policy=src.policy, mode=src.mode, nudge=nudge
            )
            if (s.name, finding.verdict.value) in acked:
                finding = replace(finding, acked=True)
            report.findings.append(finding)
            if self.store and nudge is not None:
                self._close_nudge(finding, nudge, fresh, at)
            if self.store:
                self.store.upsert_session(
                    s,
                    last_agent_at=fresh.last_agent_at,
                    last_agent_kind=fresh.last_agent_kind,
                    cursor=cursor,
                    now=at,
                )
            if execute:
                await self._act(finding, src.policy, at)
        prog.done()
        return report

    async def _collect(self, *, full: bool, prog: Progress) -> list[Session]:
        """Lista de sesiones, completa o incremental. ADR-001.

        La completa pagina las 6+ paginas del historial y su coste crece
        con el. La incremental pide una pagina y relee individualmente
        solo las sesiones que no habian terminado, que son las unicas
        cuyo estado puede haber cambiado sin salir al principio.

        El precio es que una sesion ya terminada que reviva pasa
        inadvertida hasta el siguiente refresco completo. Ocurre —el
        Spike 01 vio 5 de 70—, y por eso `watch` hace uno periodico.
        """
        marca = self.store.newest_created() if self.store else None
        if full or not self.store or not marca:
            prog.step("consultando el historial completo")
            return await self.client.sessions()

        prog.step("consultando sesiones nuevas")
        nuevas = await self.client.sessions_since(marca)
        frescas = {s.name: s for s in nuevas}

        seguidas = [n for n in self.store.tracked_non_terminal() if n not in frescas]
        if seguidas:
            prog.step(f"{len(nuevas)} nuevas, releyendo {len(seguidas)} en curso")
            sem = asyncio.Semaphore(self.config.max_concurrency)

            async def una(name: str) -> Session | None:
                async with sem:
                    try:
                        return await self.client.session(name)
                    except NotFoundError:
                        # Borrada desde el API: deja de existir para el ciclo.
                        return None

            for s in await asyncio.gather(*(una(n) for n in seguidas)):
                if s is not None:
                    frescas[s.name] = s

        # Las terminales conocidas se reponen desde SQLite para que el
        # resumen siga contando el enjambre entero, sin coste de red.
        return list(frescas.values()) + [
            s for s in self.store.cached_sessions() if s.name not in frescas
        ]

    async def _gather(
        self, sesiones: list[Session], prog: Progress
    ) -> dict[str, tuple[Freshness, str | None]]:
        """Consulta actividades en paralelo, con el paralelismo acotado.

        El API no publica cuota (ADR-001), asi que el limite es
        autoimpuesto y conservador. Secuencial era peor de lo necesario:
        con nueve sesiones activas, nueve viajes de ida y vuelta en fila.
        """
        self._reasons = {}
        if not sesiones:
            return {}
        sem = asyncio.Semaphore(self.config.max_concurrency)
        hechas = 0
        total = len(sesiones)

        async def una(s: Session) -> tuple[str, tuple[Freshness, str | None]]:
            nonlocal hechas
            async with sem:
                if s.state is SessionState.FAILED:
                    self._reasons[s.name] = await self._failure_reason(s)
                    resultado = (s.name, self._offline_freshness(s))
                else:
                    resultado = (s.name, await self._freshness(s))
                hechas += 1
                prog.step(f"actividades {hechas}/{total}")
                return resultado

        return dict(await asyncio.gather(*(una(s) for s in sesiones)))

    def _offline_freshness(self, s: Session) -> tuple[Freshness, str | None]:
        """Frescura sin red, para sesiones terminales y ya cacheadas."""
        if s.state in TERMINAL:
            kind = (
                "sessionCompleted" if s.state is SessionState.COMPLETED else "sessionFailed"
            )
            return Freshness(s.update_time, kind), None
        if self.store:
            prev_at, prev_kind = self.store.known_freshness(s.name)
            return Freshness(prev_at, prev_kind), None
        return Freshness(), None

    def _close_nudge(self, f: Finding, nudge, fresh: Freshness, at: datetime) -> None:
        """Cierra el registro del ultimo nudge cuando ya se sabe si sirvio.

        Sin esto los nudges se quedaban en 'pending' para siempre y
        `history` no podia decir si el prompt magico sigue funcionando —
        que es justo el canario del riesgo 5.
        """
        if fresh.last_agent_at is not None and fresh.last_agent_at > nudge.sent_at:
            self.store.resolve_nudge(f.session.name, "answered", fresh.last_agent_at)
        elif f.verdict is Verdict.NUDGE_UNANSWERED:
            self.store.resolve_nudge(f.session.name, "unanswered", at)

    async def _freshness(self, s: Session) -> tuple[Freshness, str | None]:
        """Frescura de una sesion no terminal, leyendo solo lo nuevo.

        En la primera vista no hay cursor, y sin acotar se paginaba la
        historia entera de la sesion — cientos de actividades para
        averiguar cuando fue la ultima. Solo interesa la cola: se pide
        una ventana reciente, muy superior al umbral N, y si esta vacia
        la propia `updateTime` de la sesion ya dice que lleva mas tiempo
        callada que la ventana, que es cuanto hace falta saber.
        """
        cursor = self.store.cursor_for(s.name) if self.store else None
        arranque = None
        if cursor is None:
            desde = now() - timedelta(seconds=self.config.bootstrap_lookback_s)
            arranque = desde.isoformat().replace("+00:00", "Z")
        acts = await self.client.activities(s.name, after=cursor or arranque)
        fresh = freshness(acts)
        if not fresh.last_agent_at and self.store:
            # El cursor ya consumio las actividades viejas: usa lo guardado.
            prev_at, prev_kind = self.store.known_freshness(s.name)
            fresh = Freshness(prev_at, prev_kind)
        if not fresh.last_agent_at:
            # Nada guardado y nada en la ventana: la sesion lleva callada
            # al menos ese tiempo. Se ancla en `updateTime`, y si tampoco
            # lo hay, en `createTime`: sin ancla el reloj no corre y una
            # sesion muerta se reportaria como sana, que es el peor error
            # posible en esta herramienta.
            fresh = Freshness(s.update_time or s.create_time, None)
        newest = max((a.create_time for a in acts if a.create_time), default=None)
        if newest:
            return fresh, newest.isoformat().replace("+00:00", "Z")
        return fresh, cursor or arranque

    async def _failure_reason(self, s: Session) -> str:
        acts = await self.client.activities(s.name, limit=None)
        for a in reversed(acts):
            if a.kind == "sessionFailed" and a.text:
                return a.text
        return SIN_RAZON

    async def _act(self, f: Finding, policy: Policy, at: datetime) -> None:
        if f.action is Action.NUDGE:
            log.info("nudge -> %s (%s): %s", f.session.repo, f.session.id, f.reason)
            await self.client.send_message(f.session.name, policy.nudge_prompt)
            if self.store:
                self.store.record_nudge(f.session.name, policy.nudge_prompt, at)
        elif f.action is Action.APPROVE_PLAN:
            log.info("aprobando plan de %s (%s)", f.session.repo, f.session.id)
            await self.client.approve_plan(f.session.name)


# ---------- presentacion ----------


def banner_pausa(report: Report) -> list[str]:
    """Una pausa silenciosa es peor que no tenerla: se avisa siempre."""
    if not report.paused:
        return []
    if GLOBAL_SCOPE in report.paused:
        motivo = report.paused[GLOBAL_SCOPE]
        return [f"** AUTONOMIA PAUSADA (global){f': {motivo}' if motivo else ''} **", ""]
    nombres = [k.removeprefix("sources/").removeprefix("github/") for k in report.paused]
    return [f"** AUTONOMIA PAUSADA en {len(nombres)}: {', '.join(nombres)} **", ""]


def render(report: Report, *, only_attention: bool = False) -> str:
    rows = report.attention if only_attention else report.findings
    if not rows:
        return "\n".join([*banner_pausa(report), "sin sesiones que reportar."])
    rows = sorted(rows, key=lambda f: (not f.needs_attention, f.session.repo))
    width = min(34, max((len(f.session.repo) for f in rows), default=10))
    out = []
    for f in rows:
        sil = columna(f.silence_s)
        title = (f.session.title or "")[:30]
        marca = "~~" if f.acked else GLYPH.get(f.verdict.value, "  ")
        out.append(
            f"{marca} {f.session.repo:<{width}} "
            f"{f.session.state.value:<22} {sil}  {title:<30}  {f.reason}"
        )
    out = [*banner_pausa(report), *out]
    counts = report.by_verdict()
    summary = "  ".join(
        f"{k.value}={v}" for k, v in sorted(counts.items(), key=lambda x: x[0].value)
    )
    out.append("")
    out.append(f"{len(report.findings)} sesiones | {summary}")
    if report.attention:
        out.append(f"{len(report.attention)} requieren atencion.")
    if report.acked:
        out.append(f"{len(report.acked)} silenciadas (~~). `moon-jules ack --list` para verlas.")
    return "\n".join(out)


# ---------- comandos ----------


async def cmd_doctor(cfg: Config, args: argparse.Namespace) -> int:
    print(f"config      {CONFIG_PATH if not args.config else args.config}")
    print(f"credencial  resuelta ({len(cfg.api_key)} caracteres, no se muestra)")
    print(f"intervalo   {cfg.poll_interval_s}s")
    print(f"umbral N    {cfg.policy.stall_after_s}s")
    print(f"modo        {cfg.default_mode.value}")
    print(f"topes       {cfg.budgets.max_active_sessions} concurrentes, "
          f"{cfg.budgets.usable_daily} sesiones/dia utilizables")
    print(f"estado      {cfg.state_path}")
    with Store(cfg.state_path) as store:
        pausas = store.active_pauses(now())
    if pausas:
        for scope, row in pausas.items():
            donde = "global" if scope == GLOBAL_SCOPE else scope
            hasta = f" hasta {row['until'][:16]}" if row["until"] else " indefinida"
            print(f"PAUSA       {donde}{hasta}  {row['reason'] or ''}")
    async with JulesClient(cfg.api_key, base_url=cfg.base_url) as c:
        prog = Progress()
        prog.step("consultando el API")
        src = await c.sources()
        ses = await c.sessions()
        prog.done()
        activas = [s for s in ses if s.state not in TERMINAL]
        paginas = max(1, -(-len(ses) // 100))
        print(f"\nAPI         OK: {len(src)} sources, {len(ses)} sesiones, "
              f"{len(activas)} no terminales")
        if len(activas) >= cfg.budgets.max_active_sessions:
            print(f"aviso       tope de concurrencia alcanzado ({len(activas)}/"
                  f"{cfg.budgets.max_active_sessions})")

        # Sin esta medida no hay forma de saber si un ciclo lento es
        # culpa del API o del cliente, que es justo la duda que provoco
        # la entrega 06.
        lat = sorted(c.latencies)
        if lat:
            p50 = lat[len(lat) // 2] / 1000
            p90 = lat[min(len(lat) - 1, int(len(lat) * 0.9))] / 1000
            print(f"\nlatencia    {len(lat)} peticiones: "
                  f"p50 {p50:.2f}s  p90 {p90:.2f}s  max {max(lat)/1000:.2f}s")
            reqs = paginas + len(activas)
            serie = paginas * p50
            paralelo = -(-len(activas) // cfg.max_concurrency) * p50
            print(f"ciclo       {reqs} peticiones "
                  f"({paginas} paginas + {len(activas)} activas)")
            print(f"            ~{serie + paralelo:.0f}s con paralelismo "
                  f"{cfg.max_concurrency}")
            if p50 > 1.0:
                print("            el API responde lento; el suelo son las "
                      "paginas, que van en serie")
    return 0


async def cmd_sources(cfg: Config, args: argparse.Namespace) -> int:
    async with JulesClient(cfg.api_key, base_url=cfg.base_url) as c:
        for s in sorted(await c.sources(), key=lambda x: x.get("id", "")):
            gh = s.get("githubRepo") or {}
            mode = cfg.for_source(s.get("name")).mode.value
            priv = "privado" if gh.get("isPrivate") else "publico"
            print(f"{gh.get('owner','?')}/{gh.get('repo','?'):<32} {mode:<12} {priv}")
    return 0


async def cmd_status(cfg: Config, args: argparse.Namespace) -> int:
    async with JulesClient(cfg.api_key, base_url=cfg.base_url) as c:
        with Store(cfg.state_path) as store:
            report = await Monitor(c, cfg, store).cycle(
                execute=False, progress=Progress(), full=args.full
            )
    if args.all:
        print(render(report))
    else:
        print(render(report, only_attention=args.attention))
    return 1 if report.attention else 0


async def cmd_ack(cfg: Config, args: argparse.Namespace) -> int:
    """Silencia hallazgos ya vistos. No arregla nada: los saca del radar."""
    with Store(cfg.state_path) as store:
        if args.list:
            filas = store.list_acks()
            if not filas:
                print("nada silenciado.")
                return 0
            for r in filas:
                repo = (r["source"] or "").removeprefix("sources/").removeprefix("github/")
                nota = f"  ({r['note']})" if r["note"] else ""
                print(f"{r['verdict']:<20} {repo:<40} {r['acked_at'][:10]}{nota}")
            return 0

        if args.session:
            async with JulesClient(cfg.api_key, base_url=cfg.base_url) as c:
                report = await Monitor(c, cfg, store).cycle(execute=False)
            objetivo = _norm_session(args.session)
            match = [f for f in report.problems if f.session.name == objetivo]
            if not match:
                print(f"{objetivo} no tiene ningun hallazgo que silenciar.", file=sys.stderr)
                return 1
            f = match[0]
            store.ack(f.session.name, f.verdict.value, now(), args.note)
            print(f"silenciado {f.verdict.value} en {f.session.repo}")
            return 0

        # --stale-before: el caso de uso real, la deuda acumulada
        corte = datetime.fromisoformat(args.stale_before).replace(tzinfo=UTC)
        async with JulesClient(cfg.api_key, base_url=cfg.base_url) as c:
            report = await Monitor(c, cfg, store).cycle(execute=False)
        candidatas = [
            f
            for f in report.problems
            if not f.acked
            and f.session.update_time is not None
            and f.session.update_time < corte
        ]
        if not candidatas:
            print(f"nada sin tocar desde {args.stale_before}.")
            return 0
        print(f"{len(candidatas)} sesion(es) sin actividad desde {args.stale_before}:\n")
        for f in candidatas:
            print(f"  {f.verdict.value:<20} {f.session.repo:<38} {f.session.title or ''}"[:110])
        if not args.yes:
            print("\nAnade --yes para silenciarlas.")
            return 0
        for f in candidatas:
            store.ack(f.session.name, f.verdict.value, now(), args.note or "deuda historica")
        print(f"\n{len(candidatas)} silenciadas. Reaparecen si su veredicto cambia.")
        return 0


async def cmd_unack(cfg: Config, args: argparse.Namespace) -> int:
    with Store(cfg.state_path) as store:
        n = store.unack(_norm_session(args.session))
    print(f"{n} silenciamiento(s) retirado(s).")
    return 0


async def cmd_pause(cfg: Config, args: argparse.Namespace) -> int:
    """Corta la autonomia sin abrir un editor. ADR-005."""
    hasta = None
    if args.for_:
        try:
            hasta = now() + parse_duracion(args.for_)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    scope = _norm_source(args.source) if args.source else GLOBAL_SCOPE
    with Store(cfg.state_path) as store:
        store.pause(scope, now(), hasta, args.reason)
    donde = "toda la autonomia" if scope == GLOBAL_SCOPE else scope
    cuando = f" hasta {hasta:%Y-%m-%d %H:%M UTC}" if hasta else " indefinidamente"
    print(f"pausado: {donde}{cuando}.")
    if not hasta:
        print("Recuerda `moon-jules resume`. Con --for se levanta sola.")
    return 0


async def cmd_resume(cfg: Config, args: argparse.Namespace) -> int:
    scope = _norm_source(args.source) if args.source else GLOBAL_SCOPE
    with Store(cfg.state_path) as store:
        n = store.resume(scope)
        restantes = store.active_pauses(now())
    if not n:
        print(f"{'la autonomia global' if scope == GLOBAL_SCOPE else scope} no estaba pausada.")
    else:
        print(f"reanudado: {'toda la autonomia' if scope == GLOBAL_SCOPE else scope}.")
    if restantes:
        nombres = ", ".join(
            k.removeprefix("sources/").removeprefix("github/") for k in restantes
        )
        print(f"siguen pausados: {nombres}")
    return 0


def _norm_source(x: str) -> str:
    return x if x.startswith("sources/") else f"sources/github/{x}"


async def cmd_history(cfg: Config, args: argparse.Namespace) -> int:
    with Store(cfg.state_path) as store:
        st = store.nudge_stats()
        filas = store.session_rows()
        print(f"sesiones conocidas      {len(filas)}")
        print(f"nudges enviados         {st['total']}")
        if st["total"]:
            print(f"  respondidos           {st['answered']}")
            print(f"  sin respuesta         {st['unanswered']}")
            print(f"  pendientes            {st['pending']}")
        if st["median_recovery_s"] is not None:
            print(f"recuperacion mediana    {st['median_recovery_s']/60:.1f} min")
        log = store.nudge_log(
            _norm_session(args.session) if args.session else None, args.limit
        )
        if log:
            print("\nultimos nudges:")
            for r in log:
                repo = (r["source"] or "").removeprefix("sources/").removeprefix("github/")
                print(f"  {r['sent_at'][:16]}  {r['outcome']:<11} {repo:<38} "
                      f"{(r['title'] or '')[:30]}")
    return 0


def _norm_session(x: str) -> str:
    return x if x.startswith("sessions/") else f"sessions/{x}"


async def cmd_watch(cfg: Config, args: argparse.Namespace) -> int:
    execute = not args.dry_run
    try:
        lock = InstanceLock(cfg.lock_path).acquire()
    except AlreadyRunningError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    print(
        f"vigilando cada {cfg.poll_interval_s}s | N={cfg.policy.stall_after_s}s | "
        f"{'ejecutando acciones' if execute else 'simulacion, sin escrituras'}\n"
        f"logs en {cfg.log_dir}\nCtrl+C para detener."
    )
    try:
        async with JulesClient(cfg.api_key, base_url=cfg.base_url) as c:
            with Store(cfg.state_path) as store:
                mon = Monitor(c, cfg, store)
                ciclo = 0
                notifier = Notifier(
                    store,
                    enabled=cfg.notify.enabled,
                    cooldown_s=cfg.notify.cooldown_s,
                )
                log.info(
                    "watch iniciado: intervalo=%ss N=%ss modo=%s notificaciones=%s",
                    cfg.poll_interval_s,
                    cfg.policy.stall_after_s,
                    cfg.default_mode.value,
                    notifier.backend.name if cfg.notify.enabled else "off",
                )
                try:
                    while True:
                        started = asyncio.get_event_loop().time()
                        try:
                            # El incremental no ve revivir una sesion ya
                            # terminada; un repaso completo periodico acota
                            # cuanto puede tardarse en notarlo.
                            completo = ciclo % cfg.full_refresh_every == 0
                            report = await mon.cycle(
                                execute=execute, progress=Progress(), full=completo
                            )
                            ciclo += 1
                            _emit(report, notifier)
                        except MoonJulesError as exc:
                            log.error("error de ciclo: %s", exc)
                            print(f"[{now():%H:%M:%S}] error de ciclo: {exc}", file=sys.stderr)
                        elapsed = asyncio.get_event_loop().time() - started
                        await asyncio.sleep(max(0.0, cfg.poll_interval_s - elapsed))
                except (KeyboardInterrupt, asyncio.CancelledError):
                    log.info("watch detenido por el usuario")
                    print("\ndetenido.")
    finally:
        lock.release()
    return 0


def _emit(report: Report, notifier: Notifier) -> None:
    stamp = report.at.strftime("%H:%M:%S")
    if report.attention:
        print(f"\n[{stamp}]\n{render(report, only_attention=True)}")
        for f in report.attention:
            log.warning(
                "%s %s (%s): %s",
                f.verdict.value,
                f.session.repo,
                f.session.id,
                f.reason,
            )
        n = notifier.notify_findings(report.attention, report.at)
        if n:
            log.info("%d notificacion(es) enviada(s)", n)
    else:
        print(f"[{stamp}] {len(report.findings)} sesiones, todo en orden")
        log.info("ciclo limpio: %d sesiones", len(report.findings))


COMMANDS = {
    "doctor": cmd_doctor,
    "sources": cmd_sources,
    "status": cmd_status,
    "watch": cmd_watch,
    "ack": cmd_ack,
    "unack": cmd_unack,
    "history": cmd_history,
    "pause": cmd_pause,
    "resume": cmd_resume,
}


def build_parser() -> argparse.ArgumentParser:
    # `-v` se declara en el padre y se repite en cada subcomando con
    # SUPPRESS para que funcione en las dos posiciones: `moon-jules -v
    # watch` y `moon-jules watch -v`. Sin SUPPRESS, el default del
    # subparser sobrescribiria el valor puesto antes del subcomando.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-v", "--verbose", action="store_true", default=argparse.SUPPRESS,
        help="logging en detalle por consola",
    )
    p = argparse.ArgumentParser(
        prog="moon-jules", description="Monitor de tu enjambre de Jules.", parents=[common]
    )
    p.add_argument("--version", action="version", version=f"moon-jules {__version__}")
    p.add_argument("--config", type=Path, default=None, help="ruta a config.toml")
    # Nada de set_defaults sobre `verbose`: `parents=` comparte el objeto
    # accion entre padre y subcomandos, y set_defaults lo mutaria,
    # anulando el SUPPRESS. El default se aplica al leerlo, en main().
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", parents=[common], help="verifica credencial, config y conectividad")
    sub.add_parser("sources", parents=[common], help="lista repositorios conectados")
    st = sub.add_parser("status", parents=[common], help="una pasada de diagnostico")
    st.add_argument("-a", "--attention", action="store_true",
                    help="muestra solo lo que requiere atencion")
    st.add_argument("--all", action="store_true",
                    help="incluye tambien lo silenciado")
    st.add_argument("--full", action="store_true",
                    help="repagina el historial completo en vez de solo lo nuevo")

    ak = sub.add_parser("ack", parents=[common],
                        help="silencia hallazgos ya vistos (no los arregla)")
    g = ak.add_mutually_exclusive_group(required=True)
    g.add_argument("session", nargs="?", help="id de sesion a silenciar")
    g.add_argument("--stale-before", metavar="YYYY-MM-DD",
                   help="silencia todo lo sin actividad desde esa fecha")
    g.add_argument("--list", action="store_true", help="lista lo ya silenciado")
    ak.add_argument("--note", help="por que se silencia")
    ak.add_argument("--yes", action="store_true", help="confirma el silenciado masivo")

    ua = sub.add_parser("unack", parents=[common], help="revierte un silenciado")
    ua.add_argument("session")

    pa = sub.add_parser("pause", parents=[common],
                        help="corta la autonomia; todo pasa a read_only")
    pa.add_argument("source", nargs="?",
                    help="un source concreto; sin argumento, todos")
    pa.add_argument("--for", dest="for_", metavar="DURACION",
                    help="se levanta sola: 30m, 2h, 1d")
    pa.add_argument("--reason", help="por que se pausa")

    re_ = sub.add_parser("resume", parents=[common], help="reanuda la autonomia")
    re_.add_argument("source", nargs="?")

    hi = sub.add_parser("history", parents=[common], help="historial local de nudges")
    hi.add_argument("--session", help="filtra por sesion")
    hi.add_argument("--limit", type=int, default=20)
    w = sub.add_parser("watch", parents=[common], help="bucle de vigilancia")
    w.add_argument("--dry-run", action="store_true",
                   help="dictamina sin ejecutar ninguna accion")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    verbose = getattr(args, "verbose", False)
    try:
        cfg = load(args.config)
    except ConfigError as exc:
        print(f"configuracion: {exc}", file=sys.stderr)
        return 2
    configure_logs(
        secrets=cfg.secrets,
        log_dir=cfg.log_dir if args.cmd == "watch" else None,
        level=logging.DEBUG if verbose else logging.INFO,
        console=verbose,
    )
    try:
        return asyncio.run(COMMANDS[args.cmd](cfg, args))
    except KeyboardInterrupt:
        return 130
    except MoonJulesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
