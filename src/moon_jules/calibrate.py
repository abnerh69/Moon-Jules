"""Calibración del umbral N. Épica E09.

Reejecuta sobre el histórico actual el análisis que produjo N = 15 min en
el Spike 01, y responde una sola pregunta: **¿sigue siendo esa la
elección correcta?**

El método no es una heurística: usa los rescates manuales del arquitecto
como etiqueta. Cada vez que alguien escribió "Completa la tarea" a una
sesión, dejó constancia del instante exacto en que un humano decidió que
estaba colgada. Eso separa dos poblaciones —silencio normal y
estancamiento— sin tener que suponer nada.

La calibración caduca: si Jules cambia su cadencia de latidos, N deja de
ser válido y el detector empieza a fallar en silencio. Por eso existe
este comando.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .detector import CLOCK_FREEZING
from .models import Activity

#: Un rescate es un mensaje corto e imperativo. Los mensajes largos son
#: instrucciones nuevas, no intentos de desatascar, y contarlos como
#: rescates contaminaría la etiqueta.
RESCATE = (
    "completa", "continu", "continú", "sigue", "termina", "prosigue",
    "retoma", "adelante", "procede", "avanza", "?",
)
RESCATE_MAX_CHARS = 120

#: Candidatos de N que se evalúan, en segundos.
CANDIDATOS = (300, 600, 900, 1200, 1800, 2700, 3600, 7200)


def es_rescate(texto: str | None) -> bool:
    t = (texto or "").strip().lower()
    return bool(t) and len(t) <= RESCATE_MAX_CHARS and any(k in t for k in RESCATE)


def percentil(valores: list[float], p: int) -> float | None:
    if not valores:
        return None
    o = sorted(valores)
    idx = max(0, min(len(o) - 1, round(p / 100 * len(o)) - 1))
    return o[idx]


@dataclass
class Muestra:
    """Las dos poblaciones que el umbral tiene que separar."""

    #: Huecos entre eventos consecutivos del agente en marcha normal.
    sanos: list[float] = field(default_factory=list)
    #: Silencio acumulado antes de que un humano decidiera rescatar.
    estancados: list[float] = field(default_factory=list)
    #: Cuánto tardó el agente en responder al rescate.
    respuestas: list[float] = field(default_factory=list)
    sesiones: int = 0
    rescatadas: int = 0
    sin_responder: int = 0
    #: Huecos descartados por caer tras un cierre de sesión: son ocio.
    ocio_descartado: int = 0

    @property
    def suficiente(self) -> bool:
        """Bajo esto, cualquier recomendación sería ruido con formato."""
        return len(self.estancados) >= 3 and len(self.sanos) >= 100


def analizar(por_sesion: dict[str, list[Activity]]) -> Muestra:
    """Separa las dos poblaciones aplicando las invariantes de ADR-002."""
    m = Muestra(sesiones=len(por_sesion))
    for acts in por_sesion.values():
        ev = sorted(
            (a for a in acts if a.create_time), key=lambda a: a.create_time
        )
        rescatada = False
        anterior_agente: Activity | None = None
        for i, a in enumerate(ev):
            if a.originator == "agent":
                if anterior_agente is not None:
                    hueco = (a.create_time - anterior_agente.create_time).total_seconds()
                    if anterior_agente.kind in CLOCK_FREEZING:
                        # La sesión cerró y revivió después. Ese tiempo es
                        # ocio, no silencio: contarlo fue el error que el
                        # Spike 01 detectó en el cálculo ingenuo por máximo.
                        m.ocio_descartado += 1
                    elif not _hubo_rescate(ev, anterior_agente, a):
                        m.sanos.append(hueco)
                anterior_agente = a
                continue

            if a.kind != "userMessaged" or i == 0 or not es_rescate(a.text):
                continue
            previo = anterior_agente
            if previo is None:
                continue
            m.estancados.append((a.create_time - previo.create_time).total_seconds())
            rescatada = True
            siguiente = next(
                (x for x in ev[i + 1:] if x.originator == "agent"), None
            )
            if siguiente is None:
                m.sin_responder += 1
            else:
                m.respuestas.append(
                    (siguiente.create_time - a.create_time).total_seconds()
                )
        if rescatada:
            m.rescatadas += 1
    return m


def _hubo_rescate(ev: list[Activity], desde: Activity, hasta: Activity) -> bool:
    """True si entre dos eventos del agente medió un rescate manual.

    Ese hueco no es cadencia sana: es el estancamiento que provocó el
    rescate, y ya se contabiliza aparte. Meterlo en `sanos` inflaría la
    referencia con justo lo que se quiere detectar.
    """
    return any(
        a.originator != "agent"
        and a.kind == "userMessaged"
        and es_rescate(a.text)
        and desde.create_time < a.create_time < hasta.create_time
        for a in ev
    )


@dataclass(frozen=True)
class Fila:
    n_s: int
    falsos: int
    falsos_pct: float
    detectados: int
    cobertura_pct: float

    def domina_a(self, otra: Fila) -> bool:
        """Mejor en ambos ejes, y estrictamente mejor en alguno.

        A igualdad de falsos y cobertura gana el umbral menor: detecta
        antes, y reducir la latencia de deteccion es el valor entero del
        producto. Sin este desempate, un umbral innecesariamente alto se
        quedaria para siempre por no ser estrictamente peor.
        """
        no_peor = self.falsos <= otra.falsos and self.detectados >= otra.detectados
        if not no_peor:
            return False
        if self.falsos < otra.falsos or self.detectados > otra.detectados:
            return True
        return self.n_s < otra.n_s


def candidatos_con(n_actual: int) -> tuple[int, ...]:
    """Los candidatos mas el umbral vigente, sin duplicarlo ni desordenar."""
    return tuple(sorted({*CANDIDATOS, n_actual}))


def tabla(m: Muestra, candidatos: tuple[int, ...] = CANDIDATOS) -> list[Fila]:
    filas = []
    for n in candidatos:
        falsos = sum(1 for g in m.sanos if g > n)
        detectados = sum(1 for g in m.estancados if g > n)
        filas.append(
            Fila(
                n_s=n,
                falsos=falsos,
                falsos_pct=100 * falsos / len(m.sanos) if m.sanos else 0.0,
                detectados=detectados,
                cobertura_pct=(
                    100 * detectados / len(m.estancados) if m.estancados else 0.0
                ),
            )
        )
    return filas


def veredicto(m: Muestra, n_actual: int) -> tuple[str, int | None]:
    """¿Sigue siendo `n_actual` una buena elección?

    No se inventa una función de puntuación: se busca si algún candidato
    **domina** al actual, es decir, si lo mejora en un eje sin empeorar
    el otro. Si ninguno lo hace, el umbral actual se sostiene y la
    decisión final sigue siendo del arquitecto, que es quien conoce el
    coste de un falso positivo.
    """
    if not m.suficiente:
        return (
            "muestra insuficiente: hacen falta al menos 3 rescates manuales "
            "y 100 huecos sanos para decir algo con fundamento",
            None,
        )
    filas = {f.n_s: f for f in tabla(m, candidatos_con(n_actual))}
    actual = filas[n_actual]
    mejores = [f for f in filas.values() if f.n_s != n_actual and f.domina_a(actual)]
    if not mejores:
        return (
            f"N = {n_actual // 60} min se sostiene: ningún otro umbral "
            "lo mejora sin empeorar el otro lado",
            None,
        )
    ganador = min(mejores, key=lambda f: (f.falsos, -f.detectados))
    return (
        f"N = {ganador.n_s // 60} min domina al actual "
        f"({ganador.falsos_pct:.2f}% de falsos frente a {actual.falsos_pct:.2f}%, "
        f"{ganador.cobertura_pct:.0f}% de cobertura frente a "
        f"{actual.cobertura_pct:.0f}%)",
        ganador.n_s,
    )
