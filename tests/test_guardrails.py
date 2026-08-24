"""Tests de los guardarraíles: redaccion, lock de instancia y notificaciones.

La redaccion es el unico mecanismo del proyecto cuyo fallo es
irreversible: una credencial escrita en un log ya no se desescribe. Se
prueba por eso con mas saña que el resto.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
from datetime import UTC, datetime, timedelta

import pytest

from moon_jules.detector import Action as Act
from moon_jules.detector import Finding, Verdict
from moon_jules.lock import AlreadyRunningError, InstanceLock
from moon_jules.logs import MASK, RedactingFormatter, configure, redact
from moon_jules.models import Session, SessionState
from moon_jules.notify import (
    LinuxBackend,
    MacBackend,
    Notifier,
    NullBackend,
    _applescript_literal,
)
from moon_jules.store import Store

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def fake(prefix: str, n: int = 32) -> str:
    """Credencial sintetica: la forma de una real, ningun valor real.

    Se construye por concatenacion a proposito. Asi el literal completo
    nunca aparece escrito en el fuente y `test_no_secrets.py` puede
    barrer el repo entero sin necesidad de una lista de excepciones —
    que es justo por donde se cuela un secreto de verdad.

    Nunca uses aqui una credencial real, ni siquiera una ya rotada.
    """
    return prefix + ("NOTAREALSECRET" * 4)[:n]


KEY = fake("AQ.")


# --------------------------------------------------------------------
# redaccion (E03, ADR-004)
# --------------------------------------------------------------------


def test_redacta_por_valor_exacto():
    assert KEY not in redact(f"llamando con key={KEY}", (KEY,))


def test_redacta_por_forma_aunque_no_conozca_el_valor():
    """Segunda linea de defensa: un secreto que llega por un camino nuevo."""
    for muestra in (
        fake("AIza"),
        fake("AQ."),
        fake("ghp_"),
        fake("github_pat_"),
    ):
        assert muestra not in redact(f"token: {muestra}")


def test_no_redacta_cadenas_cortas():
    """Un secreto de test ('x') no puede enmascarar medio log."""
    assert redact("xxx marca el punto", ("x",)) == "xxx marca el punto"


def test_redaccion_alcanza_al_traceback():
    """El caso que un filtro de logging se pierde.

    Una excepcion que arrastre la credencial en su repr se formatea
    aparte del mensaje. Por eso la redaccion vive en el formatter.
    """
    fmt = RedactingFormatter("%(message)s", (KEY,))
    try:
        raise ValueError(f"fallo autenticando con {KEY}")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "t", logging.ERROR, __file__, 1, "algo fallo", None, sys.exc_info()
        )
    salida = fmt.format(record)
    assert KEY not in salida
    assert MASK in salida


def test_redaccion_alcanza_a_los_argumentos_interpolados():
    fmt = RedactingFormatter("%(message)s", (KEY,))
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "header=%s", (KEY,), None)
    assert KEY not in fmt.format(record)


def test_el_log_en_disco_no_contiene_la_credencial(tmp_path):
    """La prueba que de verdad importa: leer el archivo escrito."""
    log = configure(secrets=(KEY,), log_dir=tmp_path, console=False)
    log.info("autenticando con %s", KEY)
    log.error("respuesta: {'error': {'message': 'key %s rechazada'}}", KEY)
    for h in log.handlers:
        h.flush()
    contenido = (tmp_path / "moon-jules.log").read_text(encoding="utf-8")
    assert KEY not in contenido
    assert contenido.count(MASK) >= 2


def test_configure_es_idempotente(tmp_path):
    a = configure(secrets=(KEY,), log_dir=tmp_path, console=False)
    n = len(a.handlers)
    b = configure(secrets=(KEY,), log_dir=tmp_path, console=False)
    assert len(b.handlers) == n


# --------------------------------------------------------------------
# lock de instancia (E04)
# --------------------------------------------------------------------


def test_segunda_instancia_falla_con_mensaje_util(tmp_path):
    path = tmp_path / "watch.lock"
    with InstanceLock(path), pytest.raises(AlreadyRunningError) as exc:
        InstanceLock(path).acquire()
    assert "watch" in str(exc.value)
    assert str(path) in str(exc.value)


def test_el_lock_se_libera_al_salir(tmp_path):
    path = tmp_path / "watch.lock"
    with InstanceLock(path):
        pass
    InstanceLock(path).acquire().release()  # no debe levantar


def test_el_lock_guarda_el_pid(tmp_path):
    import os

    path = tmp_path / "watch.lock"
    with InstanceLock(path):
        assert path.read_text().strip() == str(os.getpid())


def _hold(path: str, ready, done):
    with InstanceLock(__import__("pathlib").Path(path)):
        ready.set()
        done.wait(10)


def test_el_lock_cruza_procesos(tmp_path):
    """flock lo lleva el kernel: otro proceso tambien debe rebotar."""
    ctx = mp.get_context("fork")
    ready, done = ctx.Event(), ctx.Event()
    path = tmp_path / "watch.lock"
    proc = ctx.Process(target=_hold, args=(str(path), ready, done))
    proc.start()
    try:
        assert ready.wait(10)
        with pytest.raises(AlreadyRunningError):
            InstanceLock(path).acquire()
    finally:
        done.set()
        proc.join(10)


# --------------------------------------------------------------------
# notificaciones (E02)
# --------------------------------------------------------------------


class SpyBackend(NullBackend):
    name = "spy"

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.sent: list[tuple[str, str]] = []

    def send(self, title: str, body: str) -> bool:
        self.sent.append((title, body))
        return self.ok


def finding(verdict: Verdict, name="sessions/1", title="tarea") -> Finding:
    s = Session(name=name, state=SessionState.IN_PROGRESS,
                source="sources/github/acme/repo", title=title)
    return Finding(s, verdict, Act.ALERT, 3600.0, "muda 60 min")


def test_notifica_solo_lo_que_requiere_atencion(tmp_path):
    spy = SpyBackend()
    with Store(tmp_path / "s.db") as st:
        n = Notifier(st, enabled=True, backend=spy)
        sano = Finding(finding(Verdict.HEALTHY).session, Verdict.HEALTHY,
                       Act.NONE, 10.0, "ok")
        assert n.notify_findings([sano, finding(Verdict.STALLED)], NOW) == 1
    assert len(spy.sent) == 1


def test_no_repite_la_misma_alerta_dentro_del_cooldown(tmp_path):
    """Doce avisos por hora de lo mismo hacen que se silencien todos."""
    spy = SpyBackend()
    with Store(tmp_path / "s.db") as st:
        n = Notifier(st, enabled=True, cooldown_s=3600, backend=spy)
        n.notify_findings([finding(Verdict.STALLED)], NOW)
        n.notify_findings([finding(Verdict.STALLED)], NOW + timedelta(minutes=5))
        n.notify_findings([finding(Verdict.STALLED)], NOW + timedelta(minutes=30))
    assert len(spy.sent) == 1


def test_vuelve_a_avisar_pasado_el_cooldown(tmp_path):
    spy = SpyBackend()
    with Store(tmp_path / "s.db") as st:
        n = Notifier(st, enabled=True, cooldown_s=3600, backend=spy)
        n.notify_findings([finding(Verdict.STALLED)], NOW)
        n.notify_findings([finding(Verdict.STALLED)], NOW + timedelta(hours=2))
    assert len(spy.sent) == 2


def test_un_veredicto_nuevo_si_es_noticia(tmp_path):
    """STALLED -> NUDGE_UNANSWERED es informacion nueva, no repeticion."""
    spy = SpyBackend()
    with Store(tmp_path / "s.db") as st:
        n = Notifier(st, enabled=True, backend=spy)
        n.notify_findings([finding(Verdict.STALLED)], NOW)
        n.notify_findings(
            [finding(Verdict.NUDGE_UNANSWERED)], NOW + timedelta(minutes=10)
        )
    assert len(spy.sent) == 2


def test_si_el_backend_falla_no_se_marca_como_notificado(tmp_path):
    """Asi el siguiente ciclo lo reintenta en vez de darlo por avisado."""
    spy = SpyBackend(ok=False)
    with Store(tmp_path / "s.db") as st:
        n = Notifier(st, enabled=True, backend=spy)
        assert n.notify_findings([finding(Verdict.STALLED)], NOW) == 0
        assert st.should_notify("sessions/1", "stalled", NOW, 3600) is True


def test_desactivado_no_hace_nada(tmp_path):
    spy = SpyBackend()
    with Store(tmp_path / "s.db") as st:
        assert Notifier(st, enabled=False, backend=spy).notify_findings(
            [finding(Verdict.STALLED)], NOW
        ) == 0
    assert spy.sent == []


def test_sin_backend_nativo_degrada_en_silencio(tmp_path):
    with Store(tmp_path / "s.db") as st:
        n = Notifier(st, enabled=True, backend=NullBackend())
        assert n.notify_findings([finding(Verdict.STALLED)], NOW) == 0


@pytest.mark.parametrize(
    "peligroso",
    ['título con "comillas"', "con \\backslash", '"; rm -rf /; echo "'],
)
def test_titulos_hostiles_se_escapan(peligroso: str):
    """Los titulos vienen del API: no se confia en ellos.

    notify-send recibe argv, asi que es seguro por construccion.
    osascript recibe un literal de AppleScript y hay que escaparlo.
    """
    lit = _applescript_literal(peligroso)
    assert lit.count('"') == 0 or all(
        lit[i - 1] == "\\" for i, ch in enumerate(lit) if ch == '"' and i > 0
    )


def test_deteccion_de_backend_no_revienta_fuera_de_plataforma():
    assert isinstance(MacBackend.available(), bool)
    assert isinstance(LinuxBackend.available(), bool)


# --------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [["-v", "status"], ["status", "-v"], ["--config", "x", "-v", "watch"]],
)
def test_verbose_se_acepta_en_las_dos_posiciones(argv: list[str]):
    from moon_jules.cli import build_parser

    assert getattr(build_parser().parse_args(argv), "verbose", False) is True


def test_verbose_por_defecto_esta_apagado():
    from moon_jules.cli import build_parser

    assert getattr(build_parser().parse_args(["status"]), "verbose", False) is False


# --------------------------------------------------------------------
# carga de .env (ADR-004)
# --------------------------------------------------------------------


def test_dotenv_parsea_las_formas_habituales():
    from moon_jules.config import _parse_dotenv

    got = _parse_dotenv(
        '# comentario\n'
        'SIMPLE=valor\n'
        'export CON_EXPORT=otro\n'
        'ENTRECOMILLADA="con espacios"\n'
        "SIMPLES='comillas simples'\n"
        '\n'
        'SIN_IGUAL\n'
        'VACIA=\n'
    )
    assert got == {
        "SIMPLE": "valor",
        "CON_EXPORT": "otro",
        "ENTRECOMILLADA": "con espacios",
        "SIMPLES": "comillas simples",
        "VACIA": "",
    }


def test_el_entorno_real_gana_sobre_el_dotenv(tmp_path, monkeypatch):
    """Para poder sobrescribir en una ejecución sin editar ficheros."""
    from moon_jules.config import load_dotenv

    (tmp_path / ".env").write_text("MJ_TEST_VAR=del_fichero\n")
    monkeypatch.setenv("MJ_TEST_VAR", "del_entorno")
    monkeypatch.chdir(tmp_path)
    load_dotenv()
    assert os.environ["MJ_TEST_VAR"] == "del_entorno"


def test_el_dotenv_rellena_lo_que_falta(tmp_path, monkeypatch):
    from moon_jules.config import load_dotenv

    (tmp_path / ".env").write_text("MJ_OTRA_VAR=del_fichero\n")
    monkeypatch.delenv("MJ_OTRA_VAR", raising=False)
    monkeypatch.chdir(tmp_path)
    load_dotenv()
    assert os.environ["MJ_OTRA_VAR"] == "del_fichero"


def test_un_secreto_literal_en_el_config_es_error_de_arranque(tmp_path):
    """La regla que este incidente demostró que hace falta de verdad."""
    from moon_jules.config import ConfigError, load

    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[jules]\napi_key = "{fake("AQ.")}"\n')
    with pytest.raises(ConfigError, match="secreto literal"):
        load(cfg)
