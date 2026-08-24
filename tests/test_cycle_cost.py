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

from .fakes import FakeJules

NOW = datetime.now(UTC)
SRC = "sources/github/acme/repo"


def ago(**kw: float) -> datetime:
    return NOW - timedelta(**kw)


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
        client = FakeJules([s], acts)
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
        client = FakeJules([s], acts)
        mon = Monitor(client, cfg, store)
        run(mon.cycle())
        run(mon.cycle())
        assert len(client.activity_calls) == 1
        assert store.failure_reasons()[s.name] == SIN_RAZON


def test_las_completadas_nunca_generan_peticiones(tmp_path):
    completadas = [sess(SessionState.COMPLETED, f"sessions/c{i}") for i in range(50)]
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        client = FakeJules(completadas, {})
        run(Monitor(client, cfg, store).cycle())
    assert client.activity_calls == []


def test_el_coste_estable_es_solo_lo_vivo(tmp_path):
    """Un enjambre como el real: 538 sesiones, 9 vivas, 11 fallidas.

    El primer ciclo paga el historial completo. Los siguientes piden una
    página de novedades y releen solo lo que seguía en curso, así que el
    coste deja de crecer con el tamaño del historial.
    """
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
        client = FakeJules([*fallidas, *vivas, *hechas], acts, pages=6)
        mon = Monitor(client, cfg, store)
        run(mon.cycle())
        assert client.requests == 6 + 20   # primer ciclo: paga el historial
        client.requests = 0
        run(mon.cycle())
        # 1 pagina de novedades + 9 relecturas + 9 actividades
        assert client.requests == 1 + 9 + 9
        assert len(client.since_calls) == 1, "no debe repaginar el historial"


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
        client = FakeJules(vivas, acts, delay=0.02)
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
        client = FakeJules(vivas, acts, delay=0.02)
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
        run(Monitor(FakeJules([s], {}), cfg, store).cycle())


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


# --------------------------------------------------------------------
# medir antes de optimizar
# --------------------------------------------------------------------


def test_el_cliente_registra_la_latencia_de_cada_peticion():
    """Sin esta medida no se distingue un API lento de un cliente torpe.

    Es la duda exacta que dejó la entrega 06: 60 segundos podían ser
    culpa del código o del servidor, y no había forma de saberlo.
    """
    import httpx

    from moon_jules.client import JulesClient

    transporte = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"sources": []})
    )
    cliente = JulesClient(
        "k", client=httpx.AsyncClient(base_url="http://x/v1alpha", transport=transporte,
                                      headers={"x-goog-api-key": "k"})
    )
    run(cliente.sources())
    run(cliente.sources())
    assert len(cliente.latencies) == 2
    assert all(ms >= 0 for ms in cliente.latencies)
    run(cliente.aclose())


def test_la_url_base_es_configurable(tmp_path):
    """Sin esto el mock no sirve para probar la CLI: BASE_URL quedaba
    fijado como valor por defecto al definir la clase."""
    from moon_jules.config import load

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[jules]\napi_key = "env:MJ_K"\nbase_url = "http://127.0.0.1:9/v1alpha"\n'
    )
    import os

    os.environ["MJ_K"] = "x"
    try:
        assert load(cfg).base_url == "http://127.0.0.1:9/v1alpha"
    finally:
        del os.environ["MJ_K"]


def test_la_url_base_tiene_default_de_produccion(tmp_path):
    import os

    from moon_jules.config import load

    cfg = tmp_path / "config.toml"
    cfg.write_text('[jules]\napi_key = "env:MJ_K2"\n')
    os.environ["MJ_K2"] = "x"
    try:
        assert load(cfg).base_url == "https://jules.googleapis.com/v1alpha"
    finally:
        del os.environ["MJ_K2"]


# --------------------------------------------------------------------
# lo que de verdad costaba: el peso de cada respuesta
# --------------------------------------------------------------------


def test_las_actividades_se_piden_sin_artefactos():
    """Sin máscara, cada actividad arrastra sus `artifacts`.

    Ahí viajan los diffs completos (`changeSet.gitPatch.unidiffPatch`) y
    las capturas de pantalla en base64 (`media.data`) que Jules genera al
    verificar front-ends. Se descargaban megabytes de código para leer un
    timestamp. Además de lento, contradecía el espíritu del NO 10: ahora
    el código del repositorio ni siquiera viaja por el cable.
    """
    import httpx

    from moon_jules.client import JulesClient

    vistos: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistos.append(req.url.params.get("fields", ""))
        return httpx.Response(200, json={"activities": []})

    c = JulesClient("k", client=httpx.AsyncClient(
        base_url="http://x/v1alpha", transport=httpx.MockTransport(handler)))
    run(c.activities("sessions/1"))
    run(c.aclose())
    assert vistos and "artifacts" not in vistos[0]
    assert "createTime" in vistos[0]
    assert "originator" in vistos[0]


def test_si_el_api_rechaza_la_mascara_se_sigue_sin_ella():
    """La máscara no se pudo verificar contra el API real antes de
    publicarla, así que degradar es preferible a romper el ciclo."""
    import httpx

    from moon_jules.client import JulesClient

    intentos: list[bool] = []

    def handler(req: httpx.Request) -> httpx.Response:
        con_mascara = "fields" in req.url.params
        intentos.append(con_mascara)
        if con_mascara:
            return httpx.Response(400, json={"error": {
                "code": 400, "status": "INVALID_ARGUMENT", "message": "bad mask"}})
        return httpx.Response(200, json={"activities": []})

    c = JulesClient("k", client=httpx.AsyncClient(
        base_url="http://x/v1alpha", transport=httpx.MockTransport(handler)))
    run(c.activities("sessions/1"))
    assert intentos == [True, False]
    run(c.activities("sessions/2"))       # ya no vuelve a intentarla
    assert intentos == [True, False, False]
    run(c.aclose())


def test_el_incremental_compara_fechas_y_no_texto(tmp_path):
    """El bug que hacía inútil la optimización sin dar la cara.

    El API escribe la zona horaria como "Z" y el store como "+00:00".
    Lexicográficamente "Z" > "+", así que comparar cadenas daba siempre
    verdadero: se paginaba el historial entero creyendo que se pedían
    solo las novedades.
    """
    vieja = Session(name="sessions/vieja", state=SessionState.COMPLETED, source=SRC,
                    create_time=ago(days=30), update_time=ago(days=30))
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        client = FakeJules([vieja], {})
        mon = Monitor(client, cfg, store)
        run(mon.cycle())
        marca = store.newest_created()
        assert isinstance(marca, datetime), "la marca debe ser un datetime"
        run(mon.cycle())
    # nada nuevo: la segunda pasada no debe traerse la sesión otra vez
    assert client.since_calls and client.session_gets == []


def test_la_primera_vista_no_pide_la_historia_entera(tmp_path):
    """Sin acotar, una sesión con cientos de actividades cuesta páginas.

    Solo interesa la cola: la última actividad del agente.
    """
    s = Session(name="sessions/vieja", state=SessionState.IN_PROGRESS, source=SRC,
                create_time=ago(days=200), update_time=ago(days=100))
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        client = FakeJules([s], {})
        run(Monitor(client, cfg, store).cycle())
    assert len(client.activity_calls) == 1


def test_sin_ancla_una_sesion_muerta_no_pasa_por_sana(tmp_path):
    """El peor error posible: reportar viva una sesión parada.

    Si no hay actividades en la ventana, ni dato guardado, ni
    `updateTime`, el reloj se ancla en `createTime` antes que quedarse
    sin correr.
    """
    s = Session(name="sessions/x", state=SessionState.IN_PROGRESS, source=SRC,
                create_time=ago(days=120), update_time=None)
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        report = run(Monitor(FakeJules([s], {}), cfg, store).cycle())
    assert report.attention, "una sesión sin señal de vida no puede salir sana"


def test_el_refresco_completo_recupera_una_sesion_revivida(tmp_path):
    """El precio del incremental, y su antídoto.

    Una sesión ya terminada que revive no sale en la página de novedades
    —su `createTime` es viejo— ni se relee, porque constaba terminada.
    El Spike 01 vio 5 revivales en 70 sesiones, así que no es teórico:
    por eso `watch` repagina el historial cada tantos ciclos.
    """
    s = Session(name="sessions/z", state=SessionState.COMPLETED, source=SRC,
                create_time=ago(days=30), update_time=ago(days=1))
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        client = FakeJules([s], {})
        mon = Monitor(client, cfg, store)
        run(mon.cycle())

        revivida = Session(name=s.name, state=SessionState.IN_PROGRESS, source=SRC,
                           create_time=ago(days=30), update_time=ago(hours=5))
        client.replace_sessions([revivida])
        client.set_activities(
            s.name, [Activity("a", "progressUpdated", "agent", ago(hours=5))]
        )

        incremental = run(mon.cycle())
        assert incremental.findings[0].session.state is SessionState.COMPLETED

        completo = run(mon.cycle(full=True))
    assert completo.findings[0].session.state is SessionState.IN_PROGRESS
    assert completo.attention, "revivió y lleva 5 h muda: debe alertar"
