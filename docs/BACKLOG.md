# Moon-Jules — Backlog

Épicas planas, sin módulos (Inception §11). Cada una está dimensionada
para caber en **una sesión de Jules**: el plan Pro da 100 al día y este
repo compite por esa cuota con los otros 23.

`E01` está entregada. El orden del resto refleja el trade-off del
Inception §9: gana robustecer detección sobre añadir features, y gana
exponer mejor sobre automatizar más.

## Entregado

### E01 — Núcleo de detección *(entrega 01)*
Cliente del API, modelos, detector calibrado, persistencia SQLite,
config con secretos por referencia, y los comandos `doctor`, `sources`,
`status`, `watch`. 42 tests.

### E02 — Notificaciones nativas *(entrega 02)*
`osascript` en macOS, `notify-send` en Linux, backend nulo en el resto
con degradación silenciosa. Supresión de repetidos por (sesión,
veredicto) con ventana configurable: sin ella, una sesión colgada
avisaría doce veces por hora y el arquitecto silenciaría todo.

### E03 — Logging con redacción *(entrega 02)*
Logger con rotación a `~/.local/state/moon-jules/logs/`. La redacción
vive en el *formatter*, no en un filtro, para alcanzar también los
tracebacks. Doble defensa: por valor exacto y por forma conocida de
credencial.

### E04 — Lock de instancia única *(entrega 02)*
`flock` sobre `watch.lock`. Un segundo `watch` falla con mensaje claro
en vez de duplicar nudges y gastar el presupuesto al doble de velocidad.

### E03b — Secreto en `.env` y barrido automático *(entrega 03)*
Carga de `.env` desde el directorio de configuración y el actual, con el
entorno real ganando. `tests/test_no_secrets.py` barre el árbol entero
en cada `pytest` con los mismos patrones que redactan los logs.
Correctivo de un incidente: ver ADR-004.

### E05 — `moon-jules history` *(entrega 04)*
Sesiones conocidas, nudges enviados y su desenlace, recuperación
mediana. Incluye el cierre del registro de nudges, que existía como
método pero nunca se invocaba: se quedaban en `pending` para siempre y
el canario del riesgo 5 no podía leerse.

### E13 — Triaje de la deuda acumulada *(entrega 04)*
`ack` / `unack` / `status --all`. Épica añadida fuera del orden del
backlog porque los datos la exigían: el enjambre tiene 25 sesiones
muertas y sin triaje `watch` alertaría de las 25 en cada ciclo, para
siempre. El triaje silencia el par (sesión, veredicto), no la sesión: si
el veredicto cambia, reaparece.

### E08 — `moon-jules pause` / `resume` *(entrega 05)*
Interruptor de autonomía, global o por source, con plazo opcional
(`--for 2h`) que se levanta solo. El estado pausado se anuncia en cada
salida. Pausar no apaga la detección: sigue vigilando, deja de actuar.
Ver la enmienda de ADR-005.

### E14 — Coste del ciclo *(entrega 06)*
Correctivo nacido de la primera ejecución real contra 538 sesiones, que
parecía colgada. Paralelismo acotado, caché de razones de fallo,
lectura de nudges en bloque e indicador de progreso. Ver la nota de
campo en ADR-001.

### E15 — Diagnóstico de latencia *(entrega 07)*
`doctor` mide la latencia real por petición y proyecta el coste de un
ciclo. Nace de una duda que no se podía resolver: un `status` de 60
segundos podía ser culpa del API o del cliente, y no había dato. Incluye
`base_url` configurable, sin la cual el mock no servía para probar la
CLI, y unifica el formato de duraciones entre columna y motivo.

### E16 — Peso de las respuestas *(entrega 08)*
Respuesta parcial con `fields` para no descargar diffs ni capturas de
pantalla, y arranque acotado para no paginar la historia entera de cada
sesión. Segunda nota de campo en ADR-001.

### E17 — Listado incremental *(entrega 09)*
El coste del ciclo dejaba de estar en el número de peticiones y pasaba a
estar en repaginar un historial que solo crece. Ahora se pide una página
de novedades y se releen solo las sesiones en curso, con refresco
completo periódico. Tercera nota de campo en ADR-001.

## Siguiente ola

## Ola de autonomía

### E06 — Cola de GitHub Issues
Lectura de issues abiertos por repositorio vía `gh` (fallback a API
REST). Mapeo repo↔source. Ordenación de la cola. **No toca labels**
(NO 6).
*Depende de: E01. Toca: `github.py`.*

### E07 — `moon-jules assign-next`
Crea sesión por API para el siguiente issue de la cola. Idempotencia vía
la tabla `assignments`. Respeta los tres presupuestos de ADR-005: 15
concurrentes, 100/día menos reserva, y verificación de que el source
está en `full_auto`.
*Depende de: E06. Riesgo alto: es la acción más consecuente del sistema.*

## Ola de robustez

### E09 — `moon-jules calibrate`
Reejecuta el análisis del Spike 01 sobre el histórico y reporta si N
sigue en la rodilla de la curva. La calibración caduca si Jules cambia
su cadencia; esto lo detecta.
*Depende de: E01, E05. Base: `tools/spike_cadence.py`.*

### E10 — Vigilancia del contrato del API
Chequeo periódico de la `revision` del discovery doc. Si cambia, avisa.
Es la mitigación del riesgo 1 del Inception (API en alpha).
*Depende de: E01.*

### E11 — Verificación de `sendMessage` sobre sesión terminal
La única pregunta que el Spike 01 dejó abierta. Requiere una sesión
prescindible y decisión del arquitecto. Si el API lo acepta, habilita
el reintento automático de sesiones `FAILED` en `full_auto`.
*Bloqueada por: decisión del arquitecto.*

### E12 — Empaquetado y arranque
`pipx install`, unidad `systemd --user` y `launchd` de ejemplo, con
`watch` como servicio opcional. Sin demonio obligatorio (Inception §6).
*Depende de: E02, E04.*
