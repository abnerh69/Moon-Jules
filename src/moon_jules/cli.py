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
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .client import JulesClient
from .config import CONFIG_PATH, Config, load
from .detector import Action, Finding, Freshness, Policy, Report, assess, freshness
from .errors import ConfigError, MoonJulesError
from .models import Session, SessionState

TERMINAL = {SessionState.COMPLETED, SessionState.FAILED}

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


@dataclass
class Monitor:
    """Un ciclo de vigilancia. ADR-001: poll global + actividades incrementales."""

    client: JulesClient
    config: Config
    store: object | None = None  # Store, opcional para `status` en seco

    async def cycle(self, *, execute: bool = False) -> Report:
        at = now()
        report = Report(at=at)
        sessions = await self.client.sessions()
        for s in sessions:
            fresh, cursor = await self._freshness(s)
            if s.state is SessionState.FAILED and not s.failure_reason:
                s = s.with_failure(await self._failure_reason(s))
            src = self.config.for_source(s.source)
            nudge = self.store.last_nudge(s.name) if self.store else None
            finding = assess(
                s, fresh, at, policy=src.policy, mode=src.mode, nudge=nudge
            )
            report.findings.append(finding)
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
        return report

    async def _freshness(self, s: Session) -> tuple[Freshness, str | None]:
        """Frescura de una sesion. Las terminales no se consultan.

        Sobre COMPLETED/FAILED el reloj estaria congelado igualmente
        (ADR-002), asi que pedir sus actividades seria gastar cuota para
        no cambiar nada.
        """
        if s.state in TERMINAL:
            kind = "sessionCompleted" if s.state is SessionState.COMPLETED else "sessionFailed"
            return Freshness(s.update_time, kind), None
        cursor = self.store.cursor_for(s.name) if self.store else None
        acts = await self.client.activities(s.name, after=cursor)
        fresh = freshness(acts)
        if not fresh.last_agent_at and self.store:
            # El cursor ya consumio las actividades viejas: usa lo guardado.
            prev_at, prev_kind = self.store.known_freshness(s.name)
            fresh = Freshness(prev_at, prev_kind)
        newest = max((a.create_time for a in acts if a.create_time), default=None)
        return fresh, newest.isoformat().replace("+00:00", "Z") if newest else cursor

    async def _failure_reason(self, s: Session) -> str | None:
        acts = await self.client.activities(s.name, limit=None)
        for a in reversed(acts):
            if a.kind == "sessionFailed":
                return a.text
        return None

    async def _act(self, f: Finding, policy: Policy, at: datetime) -> None:
        if f.action is Action.NUDGE:
            await self.client.send_message(f.session.name, policy.nudge_prompt)
            if self.store:
                self.store.record_nudge(f.session.name, policy.nudge_prompt, at)
        elif f.action is Action.APPROVE_PLAN:
            await self.client.approve_plan(f.session.name)


# ---------- presentacion ----------


def render(report: Report, *, only_attention: bool = False) -> str:
    rows = report.attention if only_attention else report.findings
    if not rows:
        return "sin sesiones que reportar."
    rows = sorted(rows, key=lambda f: (not f.needs_attention, f.session.repo))
    width = min(34, max((len(f.session.repo) for f in rows), default=10))
    out = []
    for f in rows:
        sil = f"{f.silence_s/60:5.0f}m" if f.silence_s is not None else "    -"
        title = (f.session.title or "")[:30]
        out.append(
            f"{GLYPH.get(f.verdict.value, '  ')} {f.session.repo:<{width}} "
            f"{f.session.state.value:<22} {sil}  {title:<30}  {f.reason}"
        )
    counts = report.by_verdict()
    summary = "  ".join(
        f"{k.value}={v}" for k, v in sorted(counts.items(), key=lambda x: x[0].value)
    )
    out.append("")
    out.append(f"{len(report.findings)} sesiones | {summary}")
    if report.attention:
        out.append(f"{len(report.attention)} requieren atencion.")
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
    async with JulesClient(cfg.api_key) as c:
        src = await c.sources()
        ses = await c.sessions()
        activas = [s for s in ses if s.state not in TERMINAL]
        print(f"\nAPI         OK: {len(src)} sources, {len(ses)} sesiones, "
              f"{len(activas)} no terminales")
        if len(activas) >= cfg.budgets.max_active_sessions:
            print(f"aviso       tope de concurrencia alcanzado ({len(activas)}/"
                  f"{cfg.budgets.max_active_sessions})")
    return 0


async def cmd_sources(cfg: Config, args: argparse.Namespace) -> int:
    async with JulesClient(cfg.api_key) as c:
        for s in sorted(await c.sources(), key=lambda x: x.get("id", "")):
            gh = s.get("githubRepo") or {}
            mode = cfg.for_source(s.get("name")).mode.value
            priv = "privado" if gh.get("isPrivate") else "publico"
            print(f"{gh.get('owner','?')}/{gh.get('repo','?'):<32} {mode:<12} {priv}")
    return 0


async def cmd_status(cfg: Config, args: argparse.Namespace) -> int:
    from .store import Store

    async with JulesClient(cfg.api_key) as c:
        with Store(cfg.state_path) as store:
            report = await Monitor(c, cfg, store).cycle(execute=False)
    print(render(report, only_attention=args.attention))
    return 1 if report.attention else 0


async def cmd_watch(cfg: Config, args: argparse.Namespace) -> int:
    from .store import Store

    execute = not args.dry_run
    print(
        f"vigilando cada {cfg.poll_interval_s}s | N={cfg.policy.stall_after_s}s | "
        f"{'ejecutando acciones' if execute else 'simulacion, sin escrituras'}\n"
        "Ctrl+C para detener."
    )
    async with JulesClient(cfg.api_key) as c:
        with Store(cfg.state_path) as store:
            mon = Monitor(c, cfg, store)
            try:
                while True:
                    started = asyncio.get_event_loop().time()
                    try:
                        report = await mon.cycle(execute=execute)
                        stamp = report.at.strftime("%H:%M:%S")
                        att = render(report, only_attention=True)
                        if report.attention:
                            print(f"\n[{stamp}]\n{att}")
                        else:
                            print(f"[{stamp}] {len(report.findings)} sesiones, todo en orden")
                    except MoonJulesError as exc:
                        print(f"[{now():%H:%M:%S}] error de ciclo: {exc}", file=sys.stderr)
                    elapsed = asyncio.get_event_loop().time() - started
                    await asyncio.sleep(max(0.0, cfg.poll_interval_s - elapsed))
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\ndetenido.")
    return 0


COMMANDS = {
    "doctor": cmd_doctor,
    "sources": cmd_sources,
    "status": cmd_status,
    "watch": cmd_watch,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="moon-jules", description="Monitor de tu enjambre de Jules.")
    p.add_argument("--version", action="version", version=f"moon-jules {__version__}")
    p.add_argument("--config", type=Path, default=None, help="ruta a config.toml")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="verifica credencial, config y conectividad")
    sub.add_parser("sources", help="lista repositorios conectados")
    st = sub.add_parser("status", help="una pasada de diagnostico")
    st.add_argument("-a", "--attention", action="store_true",
                    help="muestra solo lo que requiere atencion")
    w = sub.add_parser("watch", help="bucle de vigilancia")
    w.add_argument("--dry-run", action="store_true",
                   help="dictamina sin ejecutar ninguna accion")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load(args.config)
    except ConfigError as exc:
        print(f"configuracion: {exc}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(COMMANDS[args.cmd](cfg, args))
    except KeyboardInterrupt:
        return 130
    except MoonJulesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
