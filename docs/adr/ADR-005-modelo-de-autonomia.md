# ADR-005 — Modelo de autonomía y presupuestos

```meta
Estado:   Aceptada
Fecha:    2026-08-24
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

### Tres modos, por source

- **`read_only`** — observa y alerta. Ninguna escritura al API.
- **`unblock_only`** — además envía el prompt de continuación y aprueba
  planes de sesiones propias. No crea sesiones.
- **`full_auto`** — además asigna el siguiente issue de la cola.

Default: **`read_only`**. Un source solo sube de modo por decisión
explícita en el `config.toml`. La primera versión útil de Moon-Jules es
un observador; la autonomía se gana source por source cuando el
arquitecto confía en lo que ve.

### Tres presupuestos, todos duros

- **`max_active_sessions = 15`** (tope del plan). `assign-next` no crea
  una sesión si ya hay 15 no terminales. Sin esto, full-auto recrea la
  cola congelada en forma de sesiones `QUEUED`, que es el problema
  original con otro nombre.
- **`daily_session_budget = 100`**, contado sobre ventana móvil de 24 h
  en la tabla `meta`. Al agotarse, `assign-next` se detiene y avisa.
  Reserva configurable (`reserve_for_manual`, default 20) que Moon-Jules
  nunca toca, para que la automatización no deje al arquitecto sin
  cuota para trabajo manual.
- **`max_nudges_per_session = 3`** (ADR-002).

### Creación de sesiones sin tocar labels

`assign-next` crea la sesión **por API**, con el mapeo issue→sesión en
la tabla `assignments`. No usa el mecanismo nativo de Jules de poner la
etiqueta `jules` al issue, porque cambiar labels choca con el NO 6.

Parámetros de creación: `automationMode = "AUTO_CREATE_PR"`,
`requirePlanApproval = false`, `startingBranch` de la config del source.

### Interruptor general

`moon-jules pause` conmuta todos los sources a `read_only` sin editar
la config. Debe poder pararse la autonomía en un comando, sin editor.

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

**Etiqueta `jules` en el issue.** Es el camino nativo y sería menos
código, pero viola el NO 6. Si alguna vez se adopta, será con una
etiqueta propia (`moon-jules:assigned`) y como excepción anotada con
fecha en la NO list.
