# Moon-Jules — Inception

```meta
Versión:    v3.0
Fecha:      2026-08-24
Estado:     Borrador para firma
Reemplaza:  v2.0 (2026-05-19)
Motivo:     Incorpora las mediciones del Spike 01 y fija la identidad
            definitiva del proyecto. La NO list y los trade-offs
            sobreviven intactos; cambian escala, umbrales y contrato
            del API.
Fuentes:    docs/01-MoonJules-Problem-Brief.md (v3.0)
            docs/spikes/MoonJules-Spike-01-Cadencia-API.md (v1.0)
```

## 1. Por qué estamos aquí

El arquitecto opera un enjambre de agentes de IA sobre **24 repositorios**
en paralelo. Jules, el único ejecutor del enjambre, se detiene en
aproximadamente **una de cada siete sesiones**, a veces con error
declarado, a veces en silencio aparentando estar activo. Lo grave no es la
frecuencia sino la latencia: la mediana entre el cuelgue y su detección
manual es de **52 minutos**, y el peor caso registrado es de 7.6 horas.
Cada uno de esos intervalos congela la cola entera del repositorio.

Hoy hay 25 sesiones detenidas, la más antigua desde hace 100 días, y el
enjambre lleva 83 días sin ejecutar nada. Moon-Jules es la red de
seguridad que hace vigilable una cartera de 24 repositorios: detecta el
estancamiento en 15 minutos, lo señala al arquitecto y lo recupera con el
mínimo esfuerzo humano posible.

Detalle completo en `docs/01-MoonJules-Problem-Brief.md` (v3.0).

## 2. Elevator pitch

Para **el arquitecto operador del enjambre**, que **necesita confiar en
que sus 24 repositorios siguen avanzando sin inspeccionarlos uno a uno**,
Moon-Jules es una **herramienta de monitoreo y reactivación** que **vigila
las sesiones de Jules, detecta estancamientos en 15 minutos en vez de 52,
y ejecuta acciones de recuperación con o sin intervención humana**. A
diferencia de **abrir manualmente cada sesión varias veces al día**,
Moon-Jules **convierte el polling humano en polling automático, recupera
lo recuperable solo, y reserva la atención del arquitecto para los casos
que sí lo necesitan**.

## 3. Product packaging

- **Nombre comercial**: *Moon-Jules — el monitor de tu enjambre.*
- **Subtítulo**: *Para que Jules no se duerma sin que te enteres.*
- **Las tres viñetas de la parte de atrás**:
  - **Sabes en todo momento qué sources están vivos, cuáles bloqueados y
    cuáles colgados — sin abrir un solo navegador.**
  - **Reactiva sesiones detenidas con el prompt correcto, sin intervención
    humana, y solo te avisa cuando no puede sola.**
  - **Alimenta tus repos con la siguiente tarea apenas terminan la
    anterior, manteniendo el flujo del enjambre lleno.**

Lo que no cabe en esa caja queda fuera del producto principal: ni
dashboards web, ni Slack, ni métricas históricas elaboradas.

## 4. La NO list

La sección más importante del Inception. Lo que Moon-Jules **no va a
hacer** en esta primera fase. Las diez entradas de v2.0 se mantienen sin
cambios de fondo; se añaden dos nacidas del spike.

1. **NO va a tener UI web.** Solo CLI y, opcionalmente, notificaciones
   nativas del sistema operativo.
2. **NO va a soportar Windows como primer ciudadano.** macOS y Linux sí.
3. **NO va a ser multi-usuario.** Un arquitecto, una máquina, una
   configuración.
4. **NO va a ser servicio en la nube.** Proceso local, sin servidor, sin
   URL pública.
5. **NO va a integrar otros agentes** (Claude Code, Cursor, Aider) en esta
   fase. Solo Jules.
6. **NO va a tomar decisiones que requieran criterio del arquitecto sin
   pedírselo.** No cierra issues, no mergea PRs, no cambia labels de
   governance. Su autonomía se acota a: reactivar sesiones detenidas,
   asignar tareas de la cola existente, y avisar.
7. **NO va a ser tiempo real estricto.** Polling con intervalos de
   minutos. El API sigue sin exponer webhooks (verificado 2026-08-24).
8. **NO va a implementar plugins ni extensiones.** El código vive en un
   repo y evoluciona como software, no como plataforma.
9. **NO va a sustituir las revisiones de épica.** Detecta estancamiento
   operativo; no juzga la calidad del trabajo entregado.
10. **NO va a guardar datos sensibles del código.** Solo metadatos de
    estado: id, estado, timestamps, último prompt enviado.
11. *(nueva, 2026-08-24)* **NO va a archivar, borrar ni pausar sesiones
    por decisión propia.** El spike descubrió que el API expone
    `sessions:archive`, `sessions:unarchive` y `DELETE /sessions`. Archivar
    es tentador para acotar el conjunto de sesiones a pollar, pero es una
    escritura sobre el workspace del arquitecto. Si se implementa, será
    como comando manual explícito, nunca como acción del loop automático.
12. *(nueva, 2026-08-24)* **NO va a inferir el estado de una sesión a
    partir del texto de los mensajes de error.** Clasificación por código
    HTTP y `error.status` únicamente. El API devuelve mensajes engañosos
    —una API key revocada dice literalmente "API keys are not supported by
    this API"— y una alerta que repita ese texto mandaría al arquitecto a
    depurar el problema equivocado.

Cuando una sesión con cualquier LLM intente derivar hacia algo de esta
lista, el redirector es esta NO list, literalmente.

## 5. Vecinos del proyecto

**API de Jules (Google)** — `https://jules.googleapis.com/v1alpha/`.
Servicio externo en alpha, con riesgo de breaking changes. Moon-Jules es
cliente, no acopla con sus internals. Contrato verificado el 2026-08-24
contra el discovery doc (revision `20260821`) y contra el API en vivo:

- Endpoints: `sources.list/get`, `sessions.list/get/create/delete`,
  `sessions:sendMessage`, `sessions:approvePlan`, `sessions:archive`,
  `sessions:unarchive`, `sessions.activities.list/get`.
- Auth: API key en header `x-goog-api-key`.
- `sessions.list` filtra **solo** por `archived`; no hay filtro por estado
  ni por source. Orden descendente por `createTime`. Página máxima 100.
- `activities.list` filtra por `create_time` con sintaxis AIP-160. Orden
  ascendente. Página máxima 100. **El parámetro plano `?createTime=` que
  aparece en el changelog de enero devuelve 400**; la forma válida es
  `filter=create_time > "…"`, y es exclusiva (no repite el pivote).
- No expone headers de cuota ni de rate limit. El presupuesto de requests
  debe ser autoimpuesto.

**GitHub** — vía CLI `gh` o API REST. Moon-Jules lee issues abiertos para
conocer la cola pendiente. Auth: PAT ya configurado en `gh`.

**El sistema operativo local** — notificaciones nativas (`osascript` en
macOS, `notify-send` en Linux). Opcional y desactivable.

**El propio arquitecto** — interactúa por CLI.

**El sistema de archivos local** — configuración en
`~/.config/moon-jules/config.toml`, persistencia en
`~/.local/state/moon-jules/state.db`, logs en
`~/.local/state/moon-jules/logs/`.

**No es vecino** ningún servicio cloud, BD remota ni telemetría externa.
Tampoco lo es el CLI oficial de Jules (`@google/jules`): `jules remote
list` enumera sesiones, pero no detecta estancamiento ni reactiva, así que
no sustituye a este proyecto. Se anota explícitamente para cerrar la
pregunta recurrente.

## 6. Solution intent

**Moon-Jules es un proceso local en Python que polla periódicamente el API
de Jules y los Issues de GitHub, mantiene en SQLite un modelo del estado
de cada sesión del enjambre, aplica reglas de detección calibradas contra
datos reales, y ejecuta acciones automáticas acotadas o emite alertas
cuando lo automático no aplica.**

Decisiones gruesas, cada una destinada a una ADR:

- **Lenguaje: Python.** Coherente con el resto del tooling del arquitecto.
- **Topología: un poll global de sesiones, no un loop por source.** El API
  no permite filtrar sesiones por source, así que la unidad natural de
  polling es la lista completa. El source pasa a ser dimensión de
  agrupación y de política —modo de autonomía, umbrales— no unidad de
  ejecución. Coste por ciclo: 1 request más uno por sesión no terminal.
- **Detección: estado más frescura, dos señales ortogonales.** El estado
  por sí solo no basta: las sesiones colgadas en silencio quedan en
  `PAUSED` o `IN_PROGRESS` con apariencia normal.
- **Umbral N = 15 minutos** de silencio del agente. Calibrado sobre 3.749
  huecos reales: 0.05% de falsos positivos y 88.9% de cobertura de los
  estancamientos que el arquitecto rescató a mano. Parametrizable por
  source, con ese default.
- **El reloj de silencio se congela tras `sessionCompleted` o
  `sessionFailed`.** Hallazgo del spike: `sessionCompleted` **no** es
  terminal en el flujo de actividades — hay sesiones que terminan y
  reviven horas después con trabajo sobre el PR. Contar ese ocio como
  silencio dispararía alertas sobre trabajo ya entregado.
- **La frescura se calcula solo sobre actividades con
  `originator == "agent"`.** Si se contaran también las del usuario, cada
  nudge que envía Moon-Jules reiniciaría su propio reloj y una sesión
  muerta parecería viva.
- **Intervalo de polling: 300 segundos** (antes 60). Con N=15 minutos, un
  ciclo de 60 s es quince veces más fino de lo necesario; 300 s entrega la
  misma detección con un quinto de los requests.
- **Cursor incremental por `create_time`**, persistido por sesión en
  SQLite. Verificado exclusivo contra el API real.
- **Persistencia: SQLite, un archivo.**
- **Distribución: CLI con sub-comandos.** `moon-jules status`, `watch`,
  `assign-next`, `pause`. Sin demonio obligatorio.
- **Configuración: un solo archivo TOML**, con la credencial **por
  referencia** (`env:JULES_API_KEY` o keychain), nunca literal.
- **Concurrencia interna: `asyncio` con `httpx`**, sin threads explícitos.
- **Autonomía graduable por source**: *read-only*, *unblock-only*,
  *full-auto*.

### Escalera de recuperación

Derivada del enum de estados verificado y de las firmas observadas:

| Estado | Señal | Acción (unblock-only / full-auto) |
|---|---|---|
| QUEUED | tiempo en cola > umbral | alerta: probable tope de concurrencia del plan |
| PLANNING | silencio > N | esperar; alerta a 2N |
| AWAITING_PLAN_APPROVAL | inmediata | `approvePlan` si la sesión la creó Moon-Jules; si no, alerta |
| AWAITING_USER_FEEDBACK | inmediata | `sendMessage` con el prompt de continuación |
| IN_PROGRESS | silencio del agente > N | `sendMessage`, presupuesto acotado, luego alerta |
| PAUSED | silencio > N | alerta (el API no expone resume) |
| FAILED | inmediata, con `reason` | alerta; en full-auto, sesión nueva con reintento acotado |
| COMPLETED con cola pendiente | inmediata | full-auto: asignar siguiente issue |

**Verificación del nudge**: si tras enviar el prompt no aparece un evento
del agente en 10 minutos, el nudge falló y se escala a alerta en vez de
reintentar. El dato: los nueve rescates históricos respondieron en 9 de 9
casos, con mediana de 70 segundos y peor caso de 8 minutos. Esa ventana de
10 minutos es el canario que avisará el día que Jules deje de obedecer.

## 7. Lo que me preocupa

Riesgos, actualizados con lo que el spike resolvió y lo que dejó abierto.
Se expanden en `docs/10-MoonJules-Risk-Register.md`.

1. **El API de Jules está en alpha.** Cambios breaking sin aviso.
   *Probabilidad alta a 12 meses; impacto alto.* Mitigación nueva: el
   discovery doc es público y versionado (`revision`), así que un chequeo
   periódico de esa revisión detecta cambios de contrato temprano.
2. ~~**Semántica desconocida del `state`.**~~ **Resuelto.** Enum de nueve
   valores verificado, firmas de cada modo de fallo documentadas.
3. **Quota y rate limits desconocidos.** *Parcialmente abierto.* 30
   requests en 30 segundos pasan limpios, pero el API no publica headers
   de cuota, así que no hay señal para saber qué tan cerca está el techo.
   Mitigación: presupuesto autoimpuesto y conservador.
4. ~~**Detecciones falsas.**~~ **Cuantificado.** 0.05% con N=15 min tras
   excluir el ocio post-`sessionCompleted`. Los dos casos residuales son
   trabajo legítimo de larga duración. Riesgo aceptable con presupuesto de
   nudges acotado.
5. **El prompt mágico puede dejar de funcionar.** *Validado hoy,
   monitoreado en adelante.* 9 de 9 rescates respondieron. La ventana de
   verificación de 10 minutos convierte este riesgo en algo detectable en
   vez de silencioso.
6. **Recursión bootstrap.** Moon-Jules se construye usando Jules, el
   agente del que protege. Sin cambios respecto a v2.0.
7. **Secret leakage.** *Elevado a prioridad uno.* La API key de Jules y el
   PAT de GitHub son credenciales sensibles. Ya ocurrió un incidente
   durante el propio spike: la key viajó por un chat y hubo que rotarla.
   La config referencia la credencial, nunca la contiene, y el logger
   necesita filtro de redacción desde el primer commit.
8. *(nuevo)* **Deriva entre el changelog y el API real.** El parámetro
   `?createTime=` documentado en enero devuelve 400 hoy. La documentación
   pública de Jules no es fuente confiable de contrato; el discovery doc
   sí. Cualquier implementación copiada del changelog nace rota.

## 8. Tamaño aproximado

**Proyecto de 4–7 semanas de trabajo dedicado**, ligeramente menos que la
estimación anterior porque el spike eliminó la incógnita más cara: la
heurística de detección ya no hay que descubrirla, está calibrada.

- Primera versión usable (detección más alerta, sin acciones automáticas):
  1–2 semanas dedicadas.
- Reactivación automática y asignación de siguiente issue: 2–3 semanas.
- Pulido, observabilidad histórica y robustez: 1–2 semanas.

Sigue sin ser proyecto de fin de semana ni de muchos meses. Justifica la
inversión documental completa del paradigma y un Threat Model honesto. No
justifica microservicios, ni base de datos servida, ni infraestructura
cloud.

## 9. Trade-offs explícitos

Sin cambios respecto a v2.0. Plazo flexible, sin deadline. Alcance acotado
y completo antes que amplio y débil. Calidad alta donde duele
equivocarse — los puntos donde Moon-Jules decide solo: enviar prompt,
asignar issue.

En conflictos concretos: gana robustecer detección sobre añadir feature;
gana exponer mejor sobre automatizar más; gana legible sobre elegante.

## 10. Coste estimado y duración aproximada

**Tiempo del arquitecto**: 100–200 horas a lo largo del proyecto.

**Recursos cloud**: cero.

**Coste de operación de Jules durante el desarrollo**: no incremental
respecto al gasto base del enjambre.

**Coste de oportunidad**: la justificación por desperdicio de cuota que
usaba v2.0 (~$2,500 anuales) **queda retirada hasta recalcularla**. Se
basaba en una tasa de fallo tres veces mayor que la real, y hoy el
enjambre está parado, así que el desperdicio corriente es cero. La
justificación que sí se sostiene, y no necesita cifras nuevas: 52 minutos
de latencia mediana por incidente, 24 repositorios que no caben en una
ronda manual, y 25 colas congeladas desde hace meses.

## 11. Identidad del proyecto

**Este proyecto NO declara módulos.** Moon-Jules es lo bastante chico —un
CLI con persistencia local— para que el Backlog opere con épicas planas
(`E01`, `E02`, …) sin agrupación.

| Concepto | Valor |
|---|---|
| Nombre del proyecto | `Moon-Jules` |
| Repositorio canónico | `github.com/abnerh69/Moon-Jules` (privado) |
| Owner GitHub | `@abnerh69` |
| Package Python (import) | `moon_jules`, bajo `src/` |
| Comando CLI | `moon-jules` |
| Directorio de configuración | `~/.config/moon-jules/` |
| Directorio de estado | `~/.local/state/moon-jules/` |
| Reverse-DNS organization | por definir; no aplica hoy |

Regla de nomenclatura: **guión en todo lo que lee un humano o un shell**
(repo, comando, rutas XDG); **guión bajo solo donde Python lo exige**
(nombre de import). Los documentos y el título del proyecto usan
`Moon-Jules` con mayúsculas.

---

## Apéndice: cómo se mantiene este documento

Snapshot al firmar. Las secciones (1)–(3) y (8) son las más estables. La
NO list (4) puede crecer si emergen tentaciones nuevas de scope creep;
cada incorporación se anota con fecha, como las entradas 11 y 12. Los
riesgos (7) migran a `docs/10-MoonJules-Risk-Register.md` cuando exista.

Bumps: v3.1, v3.2… si alguna sección se refina sin cambiar la sustancia.
v4.0 solo si se replantea la fundación del proyecto.
