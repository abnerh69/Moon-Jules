# AGENTS.md — contrato de trabajo para Moon-Jules

Este archivo lo lee Jules al empezar cada sesión. Es la fuente de verdad
operativa del repositorio; si algo aquí contradice a un prompt, gana
este archivo salvo que el prompt diga explícitamente lo contrario.

## Qué es este proyecto

Moon-Jules vigila las sesiones de Jules en 24 repositorios, detecta
cuándo se quedan colgadas y las reactiva. Hay una ironía que conviene
tener presente: **este proyecto lo construye Jules, y existe para vigilar
a Jules.** Si una sesión de este repo se cuelga, es material de estudio,
no solo un incidente.

Lectura obligatoria antes de tocar código:

- `docs/01-MoonJules-Problem-Brief.md` — el problema, medido.
- `docs/02-MoonJules-Inception.md` — alcance, y sobre todo la NO list.
- `docs/adr/` — las cinco decisiones tomadas y sus porqués.
- `docs/spikes/MoonJules-Spike-01-Cadencia-API.md` — de dónde salen los
  números que hay en el código.

## Identidad y nomenclatura

| Concepto | Valor |
|---|---|
| Proyecto | `Moon-Jules` |
| Repo | `github.com/abnerh69/Moon-Jules` (privado) |
| Package Python | `moon_jules`, bajo `src/` |
| Comando CLI | `moon-jules` |
| Rutas XDG | `~/.config/moon-jules/`, `~/.local/state/moon-jules/` |

Regla: **guión en todo lo que lee un humano o un shell; guión bajo solo
donde Python lo exige.** No renombres el package a `moonjules` ni el
comando a `moon_jules`.

## Invariantes que no se tocan sin una ADR

Estas cinco reglas salen de mediciones sobre 562 sesiones reales.
Parecen arbitrarias si solo se lee el código; no lo son. Cambiarlas
"para simplificar" reintroduce falsos positivos que costaron trabajo
encontrar.

1. **La frescura solo cuenta actividades con `originator == "agent"`.**
   Si contaran las del usuario, cada nudge que envía Moon-Jules
   reiniciaría su propio reloj y una sesión muerta parecería viva.
2. **El reloj de silencio se congela si el último evento del agente es
   `sessionCompleted` o `sessionFailed`.** `sessionCompleted` no es
   terminal en el flujo de actividades: hay sesiones que cierran y
   reviven horas después.
3. **El cursor de actividades es `filter=create_time > "..."`.** El
   parámetro plano `?createTime=` que aparece en el changelog de Jules
   devuelve 400. El filtro es exclusivo: no le restes un delta.
4. **Los errores se clasifican por código HTTP y `error.status`, nunca
   por el texto del mensaje.** Una API key revocada responde
   literalmente "API keys are not supported by this API", que es falso.
5. **`sendMessage` no se envía nunca a una sesión `FAILED`.** No está
   verificado que el API lo acepte sobre sesiones terminales.

Si crees que una de estas cinco está mal, **no la cambies: abre un issue
con la evidencia.** Son exactamente el tipo de detalle que un refactor
bienintencionado borra.

## La NO list, en corto

Nada de UI web. Nada de servicio en la nube. Nada de multi-usuario. Nada
de otros agentes. Nada de plugins. No se cierran issues, no se mergean
PRs, no se cambian labels. **No se archivan, borran ni pausan sesiones
por decisión propia**, aunque el API lo permita. No se guarda contenido
de código: ni `gitPatch`, ni `bashOutput`, ni `media` — el esquema
SQLite no tiene columnas para eso y así debe seguir.

La versión completa está en `docs/02-MoonJules-Inception.md` §4. Si una
tarea parece pedir algo de esta lista, para y pregunta.

## Cómo trabajar aquí

**Entorno.** Python 3.11+. `pip install -e ".[dev]"`. Sin dependencias
nuevas sin justificarlas en el PR: hoy son `httpx` y nada más en
runtime.

**Antes de abrir el PR**, estos tres comandos tienen que pasar:

```bash
python -m pytest -q
python -m ruff check src tests
python -m mypy src
```

**Tests.** El detector (`src/moon_jules/detector.py`) es el núcleo
calibrado: cualquier cambio ahí necesita un test que demuestre el caso
nuevo, y los existentes deben seguir verdes. Los tests que mencionan el
Spike 01 protegen hallazgos medidos; si uno falla, la respuesta casi
nunca es ajustar el test.

**La redacción de logs no se toca sin un test que la respalde.** Es el
único mecanismo del proyecto cuyo fallo es irreversible: una credencial
escrita en disco ya no se desescribe. Vive en el *formatter* y no en un
filtro a propósito, porque un filtro no ve los tracebacks. Si mueves esa
lógica, `tests/test_guardrails.py` tiene que seguir pasando entero.

**Estilo.** Líneas de 100. Español en comentarios y docstrings, inglés en
identificadores. Los comentarios explican *por qué*, no *qué* — el
código ya dice qué hace. Prefiere código que el arquitecto pueda releer
en seis meses sobre código ingenioso.

**Commits.** Conventional commits (`feat:`, `fix:`, `docs:`, `test:`,
`refactor:`). Un PR por épica del backlog, referenciando su ID.

## Trabajo con el API de Jules

Toda llamada pasa por `src/moon_jules/client.py`. No hagas requests
sueltos con `httpx` en otros módulos: el cliente concentra la
clasificación de errores, los reintentos y la paginación.

Contrato verificado el 2026-08-24 contra el API en vivo:

- `sessions.list` filtra **solo** por `archived`. No hay filtro por
  estado ni por source. Orden descendente por `createTime`.
- `activities.list` va en orden ascendente. Página máxima 100 en ambos.
- No hay webhooks. No hay headers de cuota.
- Estados: `QUEUED`, `PLANNING`, `AWAITING_PLAN_APPROVAL`,
  `AWAITING_USER_FEEDBACK`, `IN_PROGRESS`, `PAUSED`, `FAILED`,
  `COMPLETED`, más `STATE_UNSPECIFIED`.

**La documentación pública de Jules no es fuente confiable de contrato.**
El discovery doc (`https://jules.googleapis.com/$discovery/rest?version=v1alpha`)
sí lo es, y es público. Ante duda, consúltalo.

## Seguridad

La API key **nunca** se escribe en el config, ni se acepta por argumento
de CLI, ni aparece en un log, ni entra en un test. Se referencia (`env:`
o `keychain:`), el valor vive en un `.env` que no se versiona, y se
resuelve en arranque. Ver ADR-004.

**Ningún fixture de test lleva una credencial real, ni siquiera una ya
rotada.** Se construyen por concatenación con `fake()` en
`tests/test_guardrails.py`: tienen la forma de una credencial sin tener
ningún valor real, y así `tests/test_no_secrets.py` puede barrer el
árbol entero sin lista de excepciones. Esa regla existe porque se
incumplió una vez y el secreto llegó a GitHub.

Si necesitas una credencial real para probar algo: **no la pidas ni la
escribas en un archivo.** Prueba contra el mock
(`tools/mock_jules_api.py`) y deja el caso real anotado para que lo
verifique el arquitecto.

## Presupuesto

Plan Jules in Pro: 100 tareas al día, 15 concurrentes. Este proyecto
compite por esa cuota con los otros 23 repositorios del enjambre. Tareas
grandes y bien delimitadas son mejores que muchas pequeñas: cada sesión
cuesta una unidad del presupuesto, falle o no.
