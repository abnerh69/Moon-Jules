# Moon-Jules — Backlog

Épicas planas, sin módulos (Inception §11). Cada una está dimensionada
para caber en **una sesión de Jules**: el plan Pro da 100 al día y este
repo compite por esa cuota con los otros 23.

`E01` está entregada. El orden del resto refleja el trade-off del
Inception §9: gana robustecer detección sobre añadir features, y gana
exponer mejor sobre automatizar más.

## Entregado

### E01 — Núcleo de detección
Cliente del API, modelos, detector calibrado, persistencia SQLite,
config con secretos por referencia, y los comandos `doctor`, `sources`,
`status`, `watch`. 42 tests.

## Siguiente ola — observabilidad antes que autonomía

### E02 — Notificaciones nativas
`osascript` en macOS, `notify-send` en Linux, detección de plataforma y
degradación silenciosa si no hay ninguna. Solo para hallazgos que
requieren atención, con supresión de repetidos: la misma sesión colgada
no debe notificar cada 5 minutos.
*Depende de: E01. Toca: `notify.py`, `cli.py`.*

### E03 — Logging con redacción
Logger a `~/.local/state/moon-jules/logs/` con rotación. **Filtro de
redacción obligatorio** (ADR-004): cualquier cadena que contenga una
credencial resuelta se sustituye antes de escribir, incluidas URLs y
volcados de error del cliente. Test que lo demuestre.
*Depende de: E01. Toca: `logging.py`, `client.py`.*

### E04 — Lock de instancia única
`watch` toma un lock de archivo al arrancar y falla con mensaje claro si
ya hay otro corriendo. Sin esto, dos `watch` simultáneos duplican nudges
y corrompen contadores (ADR-003).
*Depende de: E01. Toca: `store.py`, `cli.py`.*

### E05 — `moon-jules history`
Consulta del histórico local: sesiones vistas, nudges enviados y su
resultado, tiempo medio de recuperación. Sale directo de SQLite.
*Depende de: E01, E03.*

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

### E08 — `moon-jules pause` / `resume`
Interruptor general que conmuta todos los sources a `read_only` sin
editar el config. Debe poder pararse la autonomía en un comando.
*Depende de: E01.*

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
