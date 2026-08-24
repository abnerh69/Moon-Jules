# ADR-001 — Topología de polling

```meta
Estado:   Aceptada
Fecha:    2026-08-24
Contexto: Spike 01 (v1.0), Inception v3.0 §6
```

## Contexto

Moon-Jules debe conocer el estado de las sesiones de Jules repartidas
entre 24 sources. El Inception v2.0 asumía "un loop asíncrono por
source, un scheduler central".

El Spike 01 midió el contrato real del API y esa suposición no se
sostiene: **`sessions.list` no acepta filtro por source ni por estado.**
Su único filtro es `archived`. Un loop por source tendría que traer la
lista completa 24 veces por ciclo y descartar el 96% de cada respuesta.

## Decisión

**Un poll global de sesiones por ciclo, más un poll incremental de
actividades por cada sesión no terminal.** El source deja de ser unidad
de ejecución y pasa a ser dimensión de agrupación y de política: define
el modo de autonomía y los umbrales, no un loop propio.

Parámetros:

- Intervalo por ciclo: **300 s** (default). Con N=15 min (ADR-002) un
  ciclo de 60 s es quince veces más fino de lo necesario.
- `sessions.list` con `pageSize=100`, sin filtro (default = solo no
  archivadas), paginando hasta agotar.
- `activities.list` con `filter=create_time > "<cursor>"` y
  `pageSize=100`, solo para sesiones en estado no terminal.
- Cursor persistido por sesión (ADR-003).

Coste por ciclo: `paginas_de_sesiones + sesiones_no_terminales`. Con 538
sesiones son 6 paginas, y con el tope de 15 concurrentes del plan Pro,
hasta 21 requests cada 5 minutos: unos 250 por hora.

**Nota de campo (entrega 06).** La primera ejecucion real contra 538
sesiones tardaba tanto que parecia colgada. Tres correcciones, todas con
test que las fija:

- Las peticiones de actividades van **en paralelo**, con el paralelismo
  acotado por `max_concurrency` (default 5). Se usaba `asyncio` sin
  aprovechar nada de su concurrencia.
- La razon de fallo de una sesion `FAILED` **se cachea en SQLite**. Es
  terminal: no cambia nunca, y se re-descargaban todas sus actividades
  en cada ciclo. Se guarda un centinela cuando no hay razon declarada,
  porque si no las 4 de cada 11 que no la declaran se reconsultaban para
  siempre.
- Los ultimos nudges se leen **en una sola consulta** en vez de una por
  sesion.

Efecto medido con latencia de 350 ms por peticion sobre un enjambre como
el real: ciclo estable de 26 a 15 peticiones, y de 9.3 a 2.9 segundos.

**Segunda nota de campo (entrega 08).** Las correcciones anteriores no
bastaron: un `status` seguia tardando 60 segundos. La causa no era el
numero de peticiones sino **el peso de cada respuesta**.

`activities.list` devuelve los `artifacts` de cada actividad, y ahi
viajan los diffs completos (`changeSet.gitPatch.unidiffPatch`) y las
capturas de pantalla en base64 (`media.data`) que Jules genera al
verificar front-ends. Se descargaban megabytes de codigo para leer un
`createTime`.

Dos correcciones:

- **Respuesta parcial.** Las APIs de Google aceptan `fields` como
  parametro de sistema, confirmado en el discovery doc. Se pide solo lo
  que el detector usa. Como la mascara no se pudo verificar contra el
  API real antes de publicarla, el cliente la reintenta sin ella si
  recibe `INVALID_ARGUMENT`, y la desactiva para el resto de la sesion.
- **Arranque acotado.** En la primera vista de una sesion no hay cursor,
  y se paginaba su historia entera. Solo interesa la cola, asi que se
  pide una ventana reciente (`bootstrap_lookback_s`, 24 h por defecto,
  96 veces N). Si esta vacia, la propia `updateTime` ya dice que la
  sesion lleva mas tiempo callada que la ventana.

Efecto colateral que conviene anotar: el codigo de los repositorios ya
ni siquiera viaja por el cable. El NO 10 del Inception decia que no se
guarda; ahora tampoco se descarga.

El suelo restante son las paginas de `sessions.list`, que son
inevitablemente secuenciales: cada pagina necesita el token de la
anterior.

## Consecuencias

Positivas: coste predecible y acotado por el propio plan; una sola
fuente de verdad por ciclo, sin condiciones de carrera entre loops;
añadir un source número 25 no añade requests.

Negativas: la latencia de detección es uniforme para todos los sources —
no se puede vigilar uno más de cerca sin subir la frecuencia global. Se
acepta: el spike no encontró ningún caso donde eso importe.

## Alternativas descartadas

**Un loop por source.** Descartada por el contrato del API, no por
preferencia de diseño.

**Webhooks.** El API no los expone (verificado 2026-08-24). La ingestión
de eventos queda detrás de una interfaz pequeña para que un futuro push
sustituya al poll sin tocar el detector.

**Polling adaptativo** (más frecuente cuando algo parece raro). Añade
estado y modos de fallo para ahorrar requests que no son escasos.
Descartada por complejidad injustificada.
