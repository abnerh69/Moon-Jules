# ADR-003 — Persistencia local

```meta
Estado:   Aceptada
Fecha:    2026-08-24
Contexto: Inception v3.0 §6, NO list §4.10
```

## Contexto

Moon-Jules necesita recordar entre ciclos y entre reinicios: hasta dónde
leyó las actividades de cada sesión, qué nudges envió y si fueron
respondidos, y qué issue asignó a qué sesión para no asignarlo dos
veces.

## Decisión

**SQLite, un archivo, en `~/.local/state/moon-jules/state.db`.**

Cuatro tablas:

- `sessions` — espejo del estado observado: `name` (PK), `source`,
  `state`, `title`, `url`, `created_at`, `last_agent_at`,
  `last_agent_kind`, `activity_cursor`, `seen_at`.
- `nudges` — auditoría de cada acción autónoma: `id`, `session`,
  `sent_at`, `prompt`, `verified_at`, `outcome`
  (`answered` / `unanswered` / `pending`).
- `assignments` — idempotencia de `assign-next`: `issue_url` (PK),
  `session`, `assigned_at`. Sin esta tabla, un reinicio de `watch`
  reasignaría issues ya en curso.
- `meta` — versión de esquema y contadores del presupuesto diario.

**Solo metadatos.** Ningún contenido de código, ningún `gitPatch`,
ningún `bashOutput`. El NO 10 del Inception es una regla de esquema, no
una intención: las columnas para guardar eso no existen.

`activity_cursor` guarda el `createTime` máximo visto. El Spike 01
verificó que `filter=create_time > "<cursor>"` es **exclusivo**, así que
el cursor se usa tal cual, sin restarle un delta.

## Consecuencias

Consultas ad-hoc desde la CLI sin dependencias. Backup por copia de
archivo. Sin operaciones de despliegue.

El riesgo es la corrupción por escritura concurrente si el arquitecto
lanza dos `watch` a la vez. Mitigación: lock de archivo al arrancar
`watch`, con mensaje claro en vez de esperar.

## Alternativas descartadas

**JSON en disco.** Sin transacciones ni consultas; la idempotencia de
`assignments` se vuelve frágil.

**Postgres o cualquier BD servida.** Contradice el NO 4 y añade
operaciones a un proyecto de un solo usuario.
