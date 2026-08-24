# Contrato del snapshot

```meta
Esquema:  2
Desde:    Moon-Jules v0.10.0 (entrega 14)
Historia: 1 — entrega 13. 2 — añade `control` y `instance.role`.
Estado:   Estable
```

Este documento es la **frontera entre Moon-Jules y la app**. Moon-Jules
escribe; la app lee. Ninguno de los dos conoce las tripas del otro.

Cambiarlo cuesta, así que se versiona. `schema` sube de número al añadir
campos, y de forma incompatible al quitar uno o cambiar su significado.
**La app debe rechazar un `schema` que no reconozca** en vez de
interpretarlo a medias: un panel que muestra datos mal leídos es peor
que uno que dice "no entiendo esta versión".

## Dónde vive

Con `publish.target = "rtdb"`, bajo la raíz configurada:

```
{root}/control                              ← quién debe vigilar
{root}/instances/{instance_id}/snapshot     ← este documento
{root}/instances/{instance_id}/decisions    ← copia de seguridad
```

Con `target = "file"`, un JSON en `publish.path`, escrito de forma
atómica: un lector nunca ve medio snapshot.

## El latido es el campo más importante

`instance.published_at` se reescribe **en cada ciclo**, cambie o no el
estado del enjambre. Esa es la razón de ser del campo.

Un MacBook dormido no publica. Y una máquina muerta no puede avisar de
que está muerta: solo puede dejar de hablar. Por eso el detector de
ausencia vive en la app, no aquí.

`instance.stale_after_s` trae el umbral recomendado —cuatro ciclos, y
nunca menos de 20 minutos—, para que el criterio esté en un sitio y no
codificado en la app. Pasado ese tiempo sin que cambie `published_at`,
**la app alerta**: no de que Jules esté mal, sino de que nadie está
mirando.

Un snapshot fresco que dice "todo en orden" y uno de hace tres horas que
dice lo mismo son afirmaciones muy distintas. Solo la marca de tiempo las
separa.

## Estructura

```json
{
  "schema": 2,
  "instance": {
    "id": "la-dorada",
    "version": "0.10.0",
    "published_at": "2026-08-24T15:04:05Z",
    "cycle_interval_s": 300,
    "stale_after_s": 1200,
    "mode": "unblock_only",
    "role": "active"
  },
  "control": {
    "desired": "la-dorada",
    "claimed_by": "la-dorada",
    "claimed_at": "2026-08-24T15:00:02Z",
    "known": true
  },
  "swarm": {
    "sessions_total": 538,
    "active": 9,
    "max_active": 15,
    "attention": 15,
    "acked": 0,
    "paused": null
  },
  "sessions": [
    {
      "id": "12713370538437788130",
      "repo": "Informatica-ASHware/CryptBot-V3",
      "title": "[E12-S04] Health endpoints + señales",
      "state": "IN_PROGRESS",
      "verdict": "stalled",
      "reason": "muda desde hace 52 min",
      "acked": false,
      "needs_attention": true,
      "silence_s": 3120,
      "age_s": 10800,
      "started_at": "2026-08-24T12:04:05Z",
      "url": "https://jules.google.com/session/...",
      "nudges": 1,
      "last_nudge_at": "2026-08-24T14:58:00Z",
      "last_nudge_outcome": "answered"
    }
  ]
}
```

### `instance`

| Campo | Significado |
|---|---|
| `id` | Qué máquina publicó. Con tres portátiles, un latido muerto no sirve de nada sin saber cuál calló. |
| `version` | Versión de Moon-Jules que escribió esto. |
| `published_at` | El latido. Se reescribe siempre. |
| `cycle_interval_s` | Cada cuánto se espera el siguiente. |
| `stale_after_s` | Umbral recomendado de caducidad. |
| `mode` | Modo de autonomía por defecto: `read_only` o `unblock_only`. |
| `role` | `active` si esta máquina está vigilando de verdad; `standby` si observa pero no actúa. |

### `control` — el relevo entre instancias

Con tres portátiles y uno solo vigilando a la vez, el teléfono elige
cuál. Y lo hace por **reclamación, no por asignación**.

| Campo | Significado |
|---|---|
| `desired` | Quién *debería* vigilar. Lo escribe el teléfono. |
| `claimed_by` | Quién *ha recogido* el encargo. Lo escribe la instancia. |
| `claimed_at` | Cuándo lo recogió. |
| `known` | `false` si esta instancia no pudo leer el control. No significa que no haya nadie designado. |

**La app debe mostrar los dos, y alertar si difieren.** Escribir "ahora
manda São Paulo" y darlo por hecho sería mostrar como vigilante una
máquina que quizá está dormida y nunca leyó nada — la misma clase de
mentira con autoridad que motiva este proyecto. Si `desired` no coincide
con `claimed_by` pasados un par de ciclos, esa máquina está apagada y
hay que elegir otra.

Cuando `known` es `false`, esta instancia pasa a `standby` por
seguridad. El presupuesto de nudges es por sesión, no por máquina: si
tres actuaran a la vez lo agotarían en una sola pasada y la sesión
recibiría el prompt triplicado. Ante la duda, callar.

Una instancia en `standby` **sigue vigilando y publicando**: su latido
dice que está viva y disponible para el relevo. Lo único que no hace es
tocar Jules.

No hay conmutación automática. Si la máquina activa muere, nadie la
sustituye solo: la app lo muestra —latido caducado— y el arquitecto
elige. Es una decisión deliberada; la elección automática es elección de
líder, y eso trae arrendamientos y particiones que no caben en la v1.

### `swarm`

| Campo | Significado |
|---|---|
| `sessions_total` | Todas las sesiones conocidas, incluidas las terminadas. |
| `active` | No terminales. Es el número que compite con `max_active`. |
| `max_active` | Tope de concurrencia del plan. Si `active` lo alcanza, las nuevas se quedan en `QUEUED`. |
| `attention` | Cuántas requieren atención y no están silenciadas. **El número del badge.** |
| `acked` | Problemas silenciados: siguen mal, pero ya se vieron. |
| `paused` | `null` si la autonomía está activa. Si no, un objeto con los ámbitos pausados y su motivo. |

### `sessions`

Como mucho 40 entradas, ordenadas por urgencia: primero lo que requiere
atención, dentro de eso lo que lleva más tiempo mudo. Incluye lo activo
y lo problemático; las completadas sin novedad no viajan.

| Campo | Significado |
|---|---|
| `id` | Identificador de la sesión en Jules. |
| `repo` | `owner/repo`, para agrupar por proyecto. |
| `title` | Título de la tarea, tal como lo puso el arquitecto. |
| `state` | Estado del API: `QUEUED`, `PLANNING`, `AWAITING_PLAN_APPROVAL`, `AWAITING_USER_FEEDBACK`, `IN_PROGRESS`, `PAUSED`, `FAILED`, `COMPLETED`. |
| `verdict` | Dictamen de Moon-Jules (ver abajo). |
| `reason` | El dictamen en una frase, ya redactada para leerse. |
| `acked` | Silenciada por el arquitecto. |
| `needs_attention` | `is_problem and not acked`. Lo que hay que mirar. |
| `silence_s` | Segundos sin señal del agente. **`null` no significa cero**: significa que el reloj está congelado porque la sesión cerró, y ese tiempo es reposo, no silencio. |
| `age_s` | Segundos desde que se abrió la sesión. Es "cuánto lleva trabajando", pregunta distinta de `silence_s`. |
| `nudges` | Cuántas veces se le envió el prompt de continuación. |
| `last_nudge_outcome` | `answered`, `unanswered` o `pending`. **Si aparecen varios `unanswered`, el prompt dejó de funcionar** — eso importa más que cualquier sesión concreta. |

### Veredictos

| `verdict` | Qué pasa |
|---|---|
| `healthy` | Avanza con normalidad. |
| `done` | Terminada limpiamente. |
| `stalled` | Muda más allá del umbral. Se le enviará el prompt. |
| `blocked_feedback` | El agente hizo una pregunta y espera respuesta. |
| `blocked_plan` | Hay un plan pendiente de aprobar. |
| `queued_slow` | Lleva demasiado en cola: probable tope de concurrencia. |
| `paused_stale` | Pausada y muda a media faena. El API no ofrece forma de reanudarla. |
| `paused_done` | Pausada después de entregar el trabajo. Informativo, no urgente. |
| `failed` | Falló. `reason` trae lo que declaró Jules. |
| `nudge_unanswered` | Se le envió el prompt y no respondió. **El canario.** |
| `nudge_budget_spent` | Se agotaron los intentos y se dejó de insistir. |

## `decisions`

Copia de seguridad de lo que decidió el arquitecto: triajes, pausas y los
últimos 200 nudges. Se publica en una rama aparte porque **no es estado
observado sino decisión humana**: si se pierde, vuelven a aparecer las
alertas ya silenciadas y no hay forma de reconstruirlas.

La tabla `sessions` de SQLite **no** se sincroniza. Es caché: se rehace
entera con un poll completo, y subirla cada ciclo serían cientos de KB
diarios para no ganar nada.

## Lo que este contrato no incluye

No hay canal de comandos. La app **lee**; no nudgea, no aprueba planes,
no silencia. Abrir esa vía trae autenticación, idempotencia y órdenes que
pueden ejecutarse dos veces, y no cabe en la primera versión.

El teléfono sí escribe una cosa, y solo una: `control/desired`. Ese es
el alcance entero del canal de escritura, y conviene que siga siéndolo.
