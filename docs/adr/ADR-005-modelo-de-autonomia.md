# ADR-005 — Modelo de autonomía y presupuestos

```meta
Estado:   Aceptada
Fecha:    2026-08-24
Enmienda: 2026-08-24 (entrega 05) — pausa por source y con plazo
Enmienda: 2026-08-24 (entrega 12) — se retira `assign-next`
Contexto: Inception v3.0 §4 NO 6, §6; límites del plan Jules in Pro
```

## Contexto

El NO 6 del Inception acota la autonomía a tres acciones: reactivar
sesiones detenidas, asignar tareas de la cola existente, y avisar. Falta
decidir cómo se gradúa esa autonomía y cómo se evita que la propia
automatización agote la cuota.

Datos del plan **Jules in Pro**: 100 tareas por día (ventana móvil de 24
horas) y **15 sesiones concurrentes**.

## Decisión

### Enmienda (entrega 12): dos modos, no tres

La decisión original daba por sentado que Moon-Jules asignaría la
siguiente tarea de la cola. **No le corresponde.** Esa decisión ya está
resuelta aguas arriba: una GitHub Action se dispara al fusionar el PR,
cierra el issue completado y etiqueta el siguiente con `jules`, que es
el disparador nativo del agente.

Consecuencias, todas de resta:

- `full_auto` desaparece. Su única acción distintiva era `assign-next`;
  sin ella era idéntico a `unblock_only`, y un modo que promete algo que
  no hace es peor que no tenerlo. Se sigue aceptando en el config para
  no romper instalaciones, resolviéndose a `unblock_only`.
- El presupuesto diario (`daily_session_budget`, `reserve_for_manual`)
  se retira: existía para acotar cuántas sesiones creaba Moon-Jules, y
  ya no crea ninguna. Sobrevive `max_active_sessions`, pero no como
  límite propio sino como contexto que explica por qué una sesión lleva
  rato en `QUEUED`.
- La tabla `assignments` se elimina (esquema v6). Garantizaba
  idempotencia al asignar issues; sin asignación no tiene destinatario.
- El conflicto con el NO 6 sobre cambiar etiquetas se disuelve solo: la
  Action las cambia, Moon-Jules no.

Lo que queda es un proyecto más pequeño y más honesto: **observa,
diagnostica y desatasca; no reparte trabajo.**

### Los modos, por source

- **`read_only`** — observa y alerta. Ninguna escritura al API.
- **`unblock_only`** — además envía el prompt de continuación y aprueba
  planes de sesiones propias. No crea sesiones.
Default: **`read_only`**. Un source solo sube de modo por decisión
explícita en el `config.toml`. La primera versión útil de Moon-Jules es
un observador; la autonomía se gana source por source cuando el
arquitecto confía en lo que ve.

### Tres presupuestos, todos duros

- **`max_nudges_per_session = 3`** (ADR-002). El único presupuesto que
  sigue siendo de Moon-Jules, porque el único acto que ejecuta es el
  nudge.
- **`max_active_sessions = 15`** (tope del plan) queda como contexto,
  no como límite: sirve para explicar en la alerta por qué una sesión
  lleva rato en `QUEUED`.

### Interruptor general

`moon-jules pause` conmuta todos los sources a `read_only` sin editar
la config. Debe poder pararse la autonomía en un comando, sin editor.

**Enmienda (entrega 05).** La decisión original hablaba solo de una
pausa global. Al implementarla aparecieron dos necesidades que no
estaban previstas y que se incorporan:

- **Pausa por source.** Con 24 repositorios, un source que se porta mal
  no debe obligar a apagar la autonomía de los otros 23. `pause
  <source>` afecta a uno; sin argumento, a todos.
- **Pausa con plazo.** `pause --for 2h` se levanta sola. El modo de
  fallo que preocupa no es olvidarse de pausar: es **olvidarse de
  reanudar** y creer que la autonomía está encendida cuando lleva días
  apagada. Es la misma clase de problema que motiva el proyecto entero
  —alguien convencido de que algo avanza cuando está parado— y sería
  irónico reintroducirlo aquí.

Por la misma razón, el estado pausado **se anuncia en cada salida**:
banner en `status` y en cada ciclo de `watch`, y línea en `doctor`. Una
pausa silenciosa es peor que no tenerla.

La pausa degrada a `read_only` por el mismo camino que el modo
configurado, así que reutiliza un mecanismo ya probado en vez de añadir
una segunda vía por la que una escritura podría escaparse. **Pausar no
apaga la detección**: sigue vigilando y avisando, solo deja de actuar.

## Consecuencias

El default conservador retrasa el valor de la automatización, a cambio
de que ningún source actúe solo antes de que el arquitecto lo haya visto
observar correctamente.

Los presupuestos duros pueden dejar trabajo sin asignar aunque haya
cuota disponible si la reserva está mal calibrada. Es el error barato de
los dos.

## Alternativas descartadas

**Autonomía global en vez de por source.** El enjambre tiene 24 sources
con niveles de madurez distintos; un interruptor único obliga al mínimo
común.

**Que Moon-Jules asigne la siguiente tarea.** Descartada en la entrega
12: ya lo hace una GitHub Action al fusionar el PR. Construirlo habría
sido duplicar un mecanismo existente y quedarse con su acción más
peligrosa sin necesidad.
