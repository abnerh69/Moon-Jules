# Contrato del snapshot

```meta
Esquema:  4
Desde:    Moon-Jules v0.18.0 (entrega 25)
Historia: 1 — entrega 13. 2 — añade `control` y `instance.role`.
          3 — añade `instance.heartbeat_ms` y el canal de comandos.
          4 — añade `sessions[].last_agent_message`.
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

Con `publish.target = "rtdb"`, bajo la raíz configurada. Credenciales y
reglas en `docs/RTDB.md`:

```
{root}/control                              ← quién debe vigilar
{root}/instances/{instance_id}/snapshot     ← este documento
{root}/instances/{instance_id}/decisions    ← copia de seguridad
```

Con `target = "file"`, un JSON en `publish.path`, escrito de forma
atómica: un lector nunca ve medio snapshot.

## Una clave ausente no es un cero

**Firebase RTDB no almacena valores nulos: los omite.** Verificado sobre
datos reales. Una sesión fallida llega sin `silence_s`, sin
`last_nudge_at` y sin `last_nudge_outcome`; un `control` sin designar
llega solo con `known`.

Moon-Jules poda los nulos antes de publicar, de modo que **fichero y
RTDB producen exactamente la misma forma**. La regla para la app es una
sola:

> Una clave ausente significa **desconocida o no aplicable**. Nunca
> cero, nunca cadena vacía, nunca falso.

Donde más duele es en `silence_s`. Si la app hace `silence_s ?? 0`
mostrará "muda hace 0 s" sobre una sesión que entregó su trabajo y está
en reposo. Ausente ahí significa que el reloj está congelado, que es
justo lo contrario de una alarma.

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
    "heartbeat_ms": 1787670245000,
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
| `published_at` | El latido, legible. Se reescribe siempre. |
| `heartbeat_ms` | El mismo instante en milisegundos. Lo usan las reglas de RTDB, que comparan números contra `now`. Gracias a él, Firebase **rechaza** designar una instancia que lleva rato callada. |
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
| `silence_s` | Segundos sin señal del agente. **Ausente no significa cero**: significa que el reloj está congelado porque la sesión cerró, y ese tiempo es reposo, no silencio. |
| `age_s` | Segundos desde que se abrió la sesión. Es "cuánto lleva trabajando", pregunta distinta de `silence_s`. |
| `nudges` | Cuántas veces se le envió el prompt de continuación. |
| `last_agent_message` | Lo último que dijo Jules, recortado a 400 caracteres. **Solo para lo que requiere atención.** Es donde está la información: `reason` repite siempre "unable to complete the task", mientras el agente suele explicar qué hizo o qué preguntó. |
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

## Notificaciones push

RTDB en tiempo real solo despierta a la app en primer plano. Para que
una alerta llegue con el teléfono en el bolsillo, Moon-Jules envía por
FCM con la misma cuenta de servicio que publica el snapshot.

La app registra su token en `{root}/devices/{token}` con valor `true`.
Moon-Jules los relee en cada ciclo —un teléfono recién instalado debe
funcionar sin reiniciar el servicio— y retira los que FCM da por
muertos, para no insistir eternamente contra un móvil reinstalado.

Se suprimen los repetidos por (sesión, veredicto): una sesión colgada
avisaría doce veces por hora y acabarías silenciando la app.

**Una alerta no puede salir de aquí: la de instancia caída.** La máquina
que se cayó es precisamente la que tendría que avisar. Esa la detecta la
app vigilando `heartbeat_ms` contra `stale_after_s`.

## Comandos

El teléfono puede ordenar acciones concretas. **Un comando no es
autonomía, es mando a distancia**: se ejecuta aunque el source esté en
`read_only` o la autonomía pausada. Los modos gobiernan lo que
Moon-Jules decide por su cuenta, no lo que se le ordena.

La app escribe en `{root}/command`:

```json
{
  "id": "c-1787670245-a3f",
  "verb": "nudge",
  "args": { "session": "12713370538437788130" },
  "issued_at": "2026-08-24T21:04:05Z",
  "expires_at": "2026-08-24T21:14:05Z"
}
```

La instancia habilitada responde en `{root}/instances/{id}/command_result`:

```json
{
  "id": "c-1787670245-a3f",
  "status": "done",
  "message": "nudge enviado a Informatica-ASHware/CryptBot-V3",
  "completed_at": "2026-08-24T21:05:12Z"
}
```

**El comando está pendiente mientras `command.id` no coincida con
`command_result.id`.** Así lo deduce la app, sin campo de estado que
mantener sincronizado.

| `verb` | `args` | Qué hace |
|---|---|---|
| `nudge` | `session` | Envía el prompt de continuación. El que más se usará. |
| `approve_plan` | `session` | Aprueba un plan pendiente. |
| `ack` | `session`, `note` | Silencia el veredicto vigente de esa sesión. |
| `unack` | `session` | Retira el silenciamiento. |
| `pause` | `scope`, `for`, `reason` | Corta la autonomía. `for` acepta `30m`, `2h`, `1d`. |
| `resume` | `scope` | La reanuda. |
| `refresh` | — | Fuerza un ciclo sin esperar. |

| `status` | Qué pasó |
|---|---|
| `done` | Ejecutado. |
| `failed` | Se intentó y falló; `message` dice por qué. |
| `expired` | Llegó tarde. No se ejecutó. |
| `rejected` | Verbo desconocido, falta un argumento, o la sesión no está en el último ciclo. |

### Tres reglas que la app debe respetar

**Un `id` único por orden**, y estable si reintentas. La instancia guarda
en SQLite lo que ya ejecutó: reenviar el mismo `id` republica el acuse
sin repetir la acción. Reenviar con `id` nuevo **sí** vuelve a actuar.

**Siempre `expires_at`.** Sin caducidad conocida, la orden se descarta:
no poder razonar sobre su frescura basta para no ejecutarla. Un
`nudge` emitido mientras las tres máquinas dormían no debe ejecutarse
seis horas después.

**Un comando a la vez.** El nodo es único; escribir otro sobrescribe el
anterior. La app debería esperar al acuse antes de permitir el
siguiente.

Los verbos que cruzan la NO list no existen y nunca existirán por aquí:
crear sesiones o asignar tareas es trabajo de la GitHub Action, y
archivar o borrar es escritura sobre el workspace del arquitecto.

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

El teléfono escribe exactamente dos nodos: `control/desired` y
`command`. Nada más. Y las reglas de seguridad lo imponen: no puede
falsificar una reclamación ni escribir en el snapshot de una instancia.
