"""Tests del coste de un ciclo. Épica E14.

El disparador fue de campo: con 538 sesiones reales, el primer `status`
tardaba tanto que el arquitecto concluyó —razonablemente— que se había
colgado. Al mirarlo aparecieron tres derroches, y cada uno tiene aquí un
test que impide que vuelva.

Los tests cuentan peticiones en vez de medir tiempo: el tiempo depende de
la máquina y de la red, el número de peticiones es una propiedad del
diseño.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from io import StringIO

from moon_jules.cli import SIN_RAZON, Monitor, Progress
from moon_jules.config import Budgets, Config, SourceConfig
from moon_jules.detector import Policy
from moon_jules.models import Activity, AutonomyMode, Session, SessionState
from moon_jules.store import Store

NOW = datetime.now(UTC)
SRC = "sources/github/acme/repo"


def ago(**kw: float) -> datetime:
    return NOW - timedelta(**kw)


class CountingClient:
    """Cuenta peticiones y registra el paralelismo máximo alcanzado."""

    def __init__(self, sessions, activities, *, pages: int = 1, delay: float = 0.0):
        self._s, self._a = sessions, activities
        self.pages = pages
        self.delay = delay
        self.requests = 0
        self.activity_calls: list[str] = []
        self.en_vuelo = 0
        self.pico = 0

    async def sessions(self, *, include_archived: bool = False):
        self.requests += self.pages
        return list(self._s)

    async def activities(self, name, *, after=None, limit=None):
        self.requests += 1
        self.activity_calls.append(name)
        self.en_vuelo += 1
        self.pico = max(self.pico, self.en_vuelo)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            return self._a.get(name, [])
        finally:
            self.en_vuelo -= 1

    async def send_message(self, name, prompt):
        pass

    async def approve_plan(self, name):
        pass


def config(tmp_path, concurrency: int = 5) -> Config:
    return Config(
        api_key="x", default_mode=AutonomyMode.READ_ONLY, policy=Policy(),
        budgets=Budgets(), max_concurrency=concurrency,
        sources={SRC: SourceConfig(name=SRC)}, state_path=tmp_path / "state.db",
    )


def sess(state, name, **kw) -> Session:
    kw.setdefault("update_time", ago(days=10))
    return Session(name=name, state=state, source=SRC,
                   create_time=ago(days=30), **kw)


def run(c):
    return asyncio.run(c)


# --------------------------------------------------------------------
# derroche 1: la razón de fallo se re-descargaba en cada ciclo
# --------------------------------------------------------------------


def test_la_razon_de_fallo_se_consulta_una_sola_vez(tmp_path):
    """FAILED es terminal: la razón no cambia nunca.

    Antes, cada ciclo re-descargaba *todas* las actividades de cada
    sesión fallida. Con 11 fallidas y un ciclo de 5 minutos, eso son
    unas 130 peticiones por hora para releer algo inmutable.
    """
    s = sess(SessionState.FAILED, "sessions/f")
    acts = {s.name: [Activity("a", "sessionFailed", "agent", ago(days=10),
                              text="Unable to install deps")]}
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        client = CountingClient([s], acts)
        mon = Monitor(client, cfg, store)
        primero = run(mon.cycle())
        tras_primero = len(client.activity_calls)
        segundo = run(mon.cycle())
        tercero = run(mon.cycle())

    assert tras_primero == 1
    assert len(client.activity_calls) == 1, "se volvió a consultar una sesión terminal"
    for r in (primero, segundo, tercero):
        assert "Unable to install deps" in r.findings[0].reason


def test_un_fallo_sin_razon_declarada_tampoco_se_reconsulta(tmp_path):
    """El caso que hacía inútil la caché.

    En el enjambre real, 4 de cada 11 sesiones fallidas no emiten
    `sessionFailed`. Sin guardar "ya miré y no había nada", esas cuatro
    se re-consultaban para siempre.
    """
    s = sess(SessionState.FAILED, "sessions/mudo")
    acts = {s.name: [Activity("a", "progressUpdated", "agent", ago(days=10))]}
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        client = CountingClient([s], acts)
        mon = Monitor(client, cfg, store)
        run(mon.cycle())
        run(mon.cycle())
        assert len(client.activity_calls) == 1
        assert store.failure_reasons()[s.name] == SIN_RAZON


def test_las_completadas_nunca_generan_peticiones(tmp_path):
    completadas = [sess(SessionState.COMPLETED, f"sessions/c{i}") for i in range(50)]
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        client = CountingClient(completadas, {})
        run(Monitor(client, cfg, store).cycle())
    assert client.activity_calls == []


def test_el_coste_estable_es_solo_lo_vivo(tmp_path):
    """Un enjambre como el real: 538 sesiones, 9 vivas, 11 fallidas."""
    fallidas = [sess(SessionState.FAILED, f"sessions/f{i}") for i in range(11)]
    vivas = [
        Session(name=f"sessions/a{i}", state=SessionState.IN_PROGRESS, source=SRC,
                create_time=ago(hours=2), update_time=NOW)
        for i in range(9)
    ]
    hechas = [sess(SessionState.COMPLETED, f"sessions/c{i}") for i in range(518)]
    acts = {s.name: [Activity("a", "progressUpdated", "agent", ago(minutes=2))]
            for s in (*fallidas, *vivas)}
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        client = CountingClient([*fallidas, *vivas, *hechas], acts, pages=6)
        mon = Monitor(client, cfg, store)
        run(mon.cycle())
        assert client.requests == 6 + 20   # primer ciclo: paga las fallidas
        client.requests = 0
        run(mon.cycle())
    assert client.requests == 6 + 9, "el ciclo estable debe pagar solo por lo vivo"


# --------------------------------------------------------------------
# derroche 2: todo iba en serie pese a usar asyncio
# --------------------------------------------------------------------


def test_las_consultas_van_en_paralelo(tmp_path):
    vivas = [
        Session(name=f"sessions/a{i}", state=SessionState.IN_PROGRESS, source=SRC,
                create_time=ago(hours=2), update_time=NOW)
        for i in range(9)
    ]
    acts = {s.name: [Activity("a", "progressUpdated", "agent", ago(minutes=2))]
            for s in vivas}
    cfg = config(tmp_path, concurrency=5)
    with Store(cfg.state_path) as store:
        client = CountingClient(vivas, acts, delay=0.02)
        run(Monitor(client, cfg, store).cycle())
    assert client.pico > 1, "sigue siendo secuencial"


def test_el_paralelismo_respeta_el_limite(tmp_path):
    """El API no publica cuota: el límite es autoimpuesto y se respeta."""
    vivas = [
        Session(name=f"sessions/a{i}", state=SessionState.IN_PROGRESS, source=SRC,
                create_time=ago(hours=2), update_time=NOW)
        for i in range(20)
    ]
    acts = {s.name: [Activity("a", "progressUpdated", "agent", ago(minutes=2))]
            for s in vivas}
    cfg = config(tmp_path, concurrency=3)
    with Store(cfg.state_path) as store:
        client = CountingClient(vivas, acts, delay=0.02)
        run(Monitor(client, cfg, store).cycle())
    assert client.pico <= 3


# --------------------------------------------------------------------
# derroche 3: una consulta SQLite por sesión
# --------------------------------------------------------------------


def test_los_nudges_se_leen_en_bloque(tmp_path):
    with Store(tmp_path / "s.db") as store:
        store.record_nudge("sessions/a", "Completa la tarea", NOW - timedelta(hours=1))
        store.record_nudge("sessions/a", "Completa la tarea", NOW)
        store.record_nudge("sessions/b", "Completa la tarea", NOW)
        bloque = store.last_nudges()
        assert bloque["sessions/a"].count == 2
        assert bloque["sessions/a"].sent_at == store.last_nudge("sessions/a").sent_at
        assert bloque["sessions/b"].count == 1
        assert "sessions/c" not in bloque


# --------------------------------------------------------------------
# el silencio no distingue entre trabajar y estar muerto
# --------------------------------------------------------------------


class TTY(StringIO):
    def isatty(self) -> bool:
        return True


def test_el_progreso_escribe_cuando_hay_terminal():
    salida = TTY()
    p = Progress(stream=salida)
    p.step("consultando sesiones")
    assert "consultando sesiones" in salida.getvalue()


def test_el_progreso_calla_en_una_tuberia():
    """A stderr y solo en terminal: no debe ensuciar logs ni pipes."""
    salida = StringIO()  # isatty() es False
    p = Progress(stream=salida)
    p.step("algo")
    p.done()
    assert salida.getvalue() == ""


def test_el_progreso_borra_su_rastro():
    salida = TTY()
    p = Progress(stream=salida)
    p.step("una linea larga de progreso")
    p.done()
    assert "una linea larga" not in salida.getvalue().split("\r")[-1]


def test_un_ciclo_sin_progreso_no_falla(tmp_path):
    """`progress` es opcional: el Monitor se usa también desde tests."""
    s = sess(SessionState.COMPLETED, "sessions/c")
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        run(Monitor(CountingClient([s], {}), cfg, store).cycle())


# --------------------------------------------------------------------
# migración: la primera que altera una tabla
# --------------------------------------------------------------------


def test_la_migracion_v4_v5_conserva_los_datos(tmp_path):
    import sqlite3

    db = tmp_path / "state.db"
    c = sqlite3.connect(db)
    c.executescript(
        "CREATE TABLE sessions(name TEXT PRIMARY KEY, source TEXT, state TEXT NOT NULL,"
        " title TEXT, url TEXT, created_at TEXT, last_agent_at TEXT,"
        " last_agent_kind TEXT, activity_cursor TEXT, seen_at TEXT NOT NULL);"
        "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "INSERT INTO meta VALUES('schema_version','4');"
        "INSERT INTO sessions(name, state, seen_at) VALUES('sessions/vieja','PAUSED','x');"
    )
    c.commit()
    c.close()

    with Store(db) as store:
        version = store.db.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()["value"]
        filas = store.db.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"]
        assert version == "5"
        assert filas == 1
        assert store.failure_reasons() == {}


def test_una_base_nueva_no_intenta_migrar(tmp_path):
    """Aplicar la migración sobre el esquema nuevo daría 'duplicate column'."""
    with Store(tmp_path / "nueva.db") as store:
        assert store.db.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()["value"] == "5"


def test_abrir_dos_veces_es_idempotente(tmp_path):
    db = tmp_path / "state.db"
    with Store(db) as store:
        store.record_nudge("sessions/a", "x", NOW)
    with Store(db) as store:
        assert store.nudge_stats()["total"] == 1
