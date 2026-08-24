"""Tests de la calibración. Épica E09.

Se construyen historiales sintéticos con las cadencias que el Spike 01
midió de verdad —mediana sana de 26 s, estancamiento de 52 min— y se
comprueba que el análisis las recupera. Si algún día el análisis deja de
reconocer sus propios datos de origen, este test lo dice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from moon_jules.calibrate import (
    CANDIDATOS,
    Muestra,
    analizar,
    es_rescate,
    percentil,
    tabla,
    veredicto,
)
from moon_jules.models import Activity

T0 = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def a(kind: str, who: str, seg: float, texto: str | None = None) -> Activity:
    return Activity(f"a{seg}", kind, who, T0 + timedelta(seconds=seg), text=texto)


#: Cadencia sana reconstruida del Spike 01 (3.749 huecos reales):
#: p50 26 s, p90 77 s, p99 ~400 s, y una cola fina por encima.
#:
#: La cola es lo que hace útil el fixture. Sin ella, todo umbral por
#: encima de la mediana daría cero falsos positivos y el análisis
#: elegiría siempre el más bajo, que es exactamente el error que este
#: test debe poder detectar.
CADENCIA_REAL = (
    [26.0] * 500      # el grueso: latido normal
    + [77.0] * 400    # trabajo algo más lento
    + [150.0] * 85
    + [400.0] * 10    # p99: operaciones largas legítimas
    + [700.0] * 3     # por encima de 10 min pero no de 15
    + [1200.0] * 2    # el residuo que ningún umbral razonable evita
)


def sesion_sana(huecos: list[float] | None = None) -> list[Activity]:
    """Sesión que late con la distribución real y cierra limpiamente."""
    huecos = huecos if huecos is not None else CADENCIA_REAL
    t, acts = 0.0, [a("progressUpdated", "agent", 0.0)]
    for h in huecos:
        t += h
        acts.append(a("progressUpdated", "agent", t))
    acts.append(a("sessionCompleted", "agent", t + 30))
    return acts


def sesion_rescatada(silencio: float = 52 * 60) -> list[Activity]:
    """Trabaja, se calla, el arquitecto insiste, revive y termina."""
    return [
        a("progressUpdated", "agent", 0),
        a("progressUpdated", "agent", 30),
        a("userMessaged", "user", 30 + silencio, "Completa la tarea"),
        a("progressUpdated", "agent", 30 + silencio + 70),
        a("sessionCompleted", "agent", 30 + silencio + 200),
    ]


# --------------------------------------------------------------------
# clasificación de rescates
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto", ["Completa la tarea", "Continúa", "continua por favor", "sigue", "?"]
)
def test_reconoce_un_rescate(texto: str):
    assert es_rescate(texto)


@pytest.mark.parametrize(
    "texto",
    [
        None,
        "",
        "Añade tests de integración para el flujo de login y documenta el "
        "contrato del endpoint en el README, siguiendo el estilo del resto "
        "del repositorio y sin tocar la configuración de CI",
    ],
)
def test_no_confunde_instrucciones_con_rescates(texto):
    """Un mensaje largo es trabajo nuevo, no un intento de desatascar.

    Contarlo como rescate contaminaría la etiqueta con la que se calibra
    todo lo demás.
    """
    assert not es_rescate(texto)


# --------------------------------------------------------------------
# separación de las dos poblaciones
# --------------------------------------------------------------------


def test_recupera_la_cadencia_sana():
    """Los percentiles que midió el Spike 01, reconstruidos."""
    m = analizar({"s": sesion_sana()})
    assert percentil(m.sanos, 50) == pytest.approx(26, abs=2)
    assert percentil(m.sanos, 90) == pytest.approx(77, abs=5)
    assert m.rescatadas == 0


def test_la_cola_larga_produce_falsos_positivos_en_umbrales_bajos():
    """Sin cola, cualquier umbral parecería perfecto y el fixture mentiría."""
    m = analizar({f"s{i}": sesion_sana() for i in range(3)})
    filas = {f.n_s: f for f in tabla(m, (300, 600, 900))}
    assert filas[300].falsos > filas[600].falsos > filas[900].falsos > 0


def test_recupera_el_silencio_del_estancamiento():
    m = analizar({f"s{i}": sesion_rescatada() for i in range(4)})
    assert percentil(m.estancados, 50) == pytest.approx(52 * 60, abs=1)
    assert m.rescatadas == 4


def test_el_hueco_del_estancamiento_no_entra_en_la_cadencia_sana():
    """El error que inflaría la referencia con justo lo que se detecta.

    El hueco que abarca el rescate (52 min) es el estancamiento, no
    cadencia. Los otros dos —antes de callarse y tras revivir— sí son
    sanos y deben quedarse.
    """
    m = analizar({"s": sesion_rescatada(52 * 60)})
    assert m.estancados == [pytest.approx(52 * 60)]
    assert not any(g > 10 * 60 for g in m.sanos), (
        f"el hueco del rescate se coló en los sanos: {m.sanos}"
    )
    assert len(m.sanos) == 2


def test_el_reposo_tras_cerrar_no_cuenta_como_silencio():
    """`sessionCompleted` no es terminal en el flujo: hay sesiones que
    cierran y reviven horas después. Ese tiempo es ocio."""
    acts = [
        a("progressUpdated", "agent", 0),
        a("sessionCompleted", "agent", 30),
        a("progressUpdated", "agent", 30 + 4 * 3600),   # revive 4 h después
        a("sessionCompleted", "agent", 30 + 4 * 3600 + 60),
    ]
    m = analizar({"s": acts})
    assert m.ocio_descartado == 1
    assert max(m.sanos) < 120


def test_mide_la_respuesta_al_rescate():
    m = analizar({f"s{i}": sesion_rescatada() for i in range(3)})
    assert percentil(m.respuestas, 50) == pytest.approx(70, abs=1)
    assert m.sin_responder == 0


def test_cuenta_los_rescates_que_nadie_contesto():
    """El canario: el día que el prompt mágico deje de funcionar."""
    acts = [
        a("progressUpdated", "agent", 0),
        a("userMessaged", "user", 3600, "Completa la tarea"),
    ]
    m = analizar({"s": acts})
    assert m.sin_responder == 1
    assert m.respuestas == []


# --------------------------------------------------------------------
# la tabla y el veredicto
# --------------------------------------------------------------------


#: Los nueve silencios previos a un rescate que midió el Spike 01, en
#: minutos: mediana 52, p75 95, máximo 458, y un caso de 0.33 que no era
#: un rescate sino una instrucción añadida. La distribución importa
#: entera: es la de 18 min la que hace caer la cobertura al subir de 15 a
#: 20, y por tanto la que sostiene el umbral vigente.
SILENCIOS_REALES = (0.33, 18, 30, 45, 52, 60, 95, 200, 458)


def muestra_realista() -> Muestra:
    """Las dos poblaciones del Spike 01, con su separación real."""
    por_sesion = {f"sana{i}": sesion_sana() for i in range(20)}
    for i, minutos in enumerate(SILENCIOS_REALES):
        por_sesion[f"mala{i}"] = sesion_rescatada(minutos * 60)
    return analizar(por_sesion)


def test_la_tabla_ordena_falsos_frente_a_cobertura():
    filas = tabla(muestra_realista(), CANDIDATOS)
    # Subir el umbral nunca puede aumentar los falsos ni la cobertura.
    for previa, siguiente in zip(filas, filas[1:], strict=False):
        assert siguiente.falsos <= previa.falsos
        assert siguiente.detectados <= previa.detectados


def test_quince_minutos_se_sostiene_con_los_datos_del_spike():
    """La comprobación de fondo: el análisis reconoce su propio origen.

    Si con las distribuciones que produjeron N = 15 min el veredicto
    propusiera otro umbral, el análisis estaría roto.
    """
    texto, sugerido = veredicto(muestra_realista(), 900)
    assert sugerido is None, f"propuso cambiar N sin motivo: {texto}"
    assert "se sostiene" in texto


def test_a_igualdad_de_resultado_gana_el_umbral_que_detecta_antes():
    """Sin desempate, un umbral alto de más se quedaría para siempre por
    no ser estrictamente peor. Detectar antes es el valor del producto.

    Se construye un empate exacto: ningún hueco sano ni estancamiento
    cae entre 15 y 30 minutos, así que ambos umbrales dan el mismo
    resultado y solo los separa la latencia de detección.
    """
    # Huecos sanos de 700 s: hacen que 5 y 10 min tengan falsos, para que
    # el empate quede acotado entre 15 y 30 y el test mida lo que dice.
    por_sesion = {
        f"sana{i}": sesion_sana([26.0] * 200 + [700.0] * 3) for i in range(3)
    }
    for i, sil in enumerate((60 * 60, 90 * 60, 120 * 60, 200 * 60)):
        por_sesion[f"mala{i}"] = sesion_rescatada(sil)
    m = analizar(por_sesion)

    filas = {f.n_s: f for f in tabla(m, (300, 600, 900, 1800))}
    assert filas[300].falsos > 0 and filas[600].falsos > 0, "el empate no está acotado"
    assert filas[900].falsos == filas[1800].falsos == 0
    assert filas[900].detectados == filas[1800].detectados
    assert veredicto(m, 1800)[1] == 900


def test_detecta_que_un_umbral_absurdo_esta_mal():
    texto, sugerido = veredicto(muestra_realista(), 7200)
    assert sugerido is not None and sugerido < 7200
    assert "domina" in texto


def test_una_muestra_pobre_no_recomienda_nada():
    """Sin datos suficientes, callar es mejor que inventar un número."""
    m = analizar({"s": sesion_rescatada()})
    texto, sugerido = veredicto(m, 900)
    assert sugerido is None
    assert "insuficiente" in texto


def test_sin_rescates_no_hay_veredicto():
    m = analizar({f"s{i}": sesion_sana() for i in range(10)})
    assert not m.suficiente
    assert veredicto(m, 900)[1] is None


def test_dominar_exige_no_empeorar_ningun_eje():
    from moon_jules.calibrate import Fila

    base = Fila(900, 10, 0.5, 8, 80.0)
    mejor = Fila(600, 8, 0.4, 9, 90.0)
    peor_en_uno = Fila(1200, 5, 0.2, 6, 60.0)
    igual = Fila(1000, 10, 0.5, 8, 80.0)
    assert mejor.domina_a(base)
    assert not peor_en_uno.domina_a(base)
    assert not igual.domina_a(base)
