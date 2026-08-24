# MoonJules — Spike 01: Cadencia y comportamiento del API de Jules

```meta
Versión:    v1.0
Fecha:      2026-08-24
Estado:     Cerrado. Q1–Q4, Q6, Q7 respondidas con datos reales.
            Q5 (sendMessage sobre terminal) pendiente: requiere escritura
            sobre el workspace de producción; no se ejecutó sin visto bueno.
Muestra:    562 sesiones históricas, 24 sources, 3.749 huecos entre eventos
            del agente, 9 rescates manuales reconstruidos.
Alimenta:   umbral N, ADR de topología de polling, ADR de escalera de
            recuperación, Risk Register (R2–R5), §1 del Problem Brief.
```

## 1. Resultado en una línea

**N = 15 minutos de silencio del agente, con el reloj congelado cuando el
último evento es `sessionCompleted`.** Ese umbral produce 0.05% de falsos
positivos sobre huecos sanos reales y captura 88.9% de los estancamientos
que el arquitecto rescató a mano. La separación entre ambas poblaciones es
de dos órdenes de magnitud: mediana sana de 26 segundos contra mediana de
estancamiento de 52 minutos.

## 2. Cómo se obtuvo sin esperar cuatro horas

El plan original pedía observar tres sesiones vivas durante una ventana
larga. Al conectar apareció el obstáculo y su solución: el enjambre lleva
detenido desde el 2026-06-02, no hay nada vivo que mirar. Pero las
actividades son inmutables y llevan `createTime`, así que el historial
completo es una grabación de alta resolución de todo lo que ya pasó. La
cadencia se reconstruyó hacia atrás sobre 70 sesiones recientes.

Mejor todavía: **cada rescate manual del arquitecto quedó grabado como una
actividad `userMessaged`**. Eso da la etiqueta que ningún experimento
sintético habría dado — el momento exacto en que un humano decidió que la
sesión estaba colgada. El umbral no se deduce de una heurística: se calibra
contra el juicio real del operador, repetido nueve veces.

## 3. Censo del enjambre

562 sesiones sobre 24 sources conectados (el Inception decía "cinco o más";
la escala real es cinco veces mayor y refuerza el caso del proyecto).

| Estado | Sesiones | % |
|---|---:|---:|
| COMPLETED | 526 | 93.6 |
| PAUSED | 24 | 4.3 |
| FAILED | 11 | 2.0 |
| AWAITING_USER_FEEDBACK | 1 | 0.2 |

A primera vista contradice el Problem Brief, que estima fallo en una de cada
tres sesiones. No lo contradice: **el estado terminal no cuenta los
estancamientos, porque una sesión rescatada termina en COMPLETED.** El censo
mide sesiones que quedaron rotas, no sesiones que se rompieron.

La cuenta honesta, midiendo la intervención en vez del resultado: 10.0% de
las sesiones (7 de 70) necesitaron al menos un rescate manual, y otro 4.4%
(25 de 562) sigue detenido hoy sin rescate. Aproximadamente **14% del
trabajo requirió o requiere intervención humana** — un tercio de lo que
estimaba el Brief, y el número que debería sustituirlo, con dos matices que
lo empujan hacia arriba: el clasificador de rescates solo cuenta mensajes
cortos con verbo imperativo, y el conteo excluye lo que el arquitecto
resolvió cancelando y relanzando en vez de insistiendo.

Deuda parada hoy mismo: 25 sesiones, la más antigua con 100 días sin
cambios. Es exactamente el inventario que MoonJules habría reportado la
primera mañana.

## 4. La medición central

### 4.1 Dos poblaciones, dos órdenes de magnitud

Huecos entre eventos consecutivos del agente, n=3.749, y silencio previo a
cada rescate manual, n=9:

| Percentil | Hueco sano | Silencio antes del rescate |
|---|---:|---:|
| p50 | 0.44 min | 52.5 min |
| p75 | 0.83 min | 95.0 min |
| p90 | 1.28 min | 458.3 min |
| p99 | 7.58 min | 458.3 min |
| máx | 235.2 min | 458.3 min |

Jules sano late cada 26 segundos y el 95% de sus huecos cabe en menos de dos
minutos. Cuando se cuelga, el arquitecto lo nota cuando ya lleva una hora
parado — y en el peor caso registrado, siete horas y media.

### 4.2 El máximo es una trampa

La versión ingenua del umbral era «pico sano × 1.5». Con el pico sano de
235 minutos eso daría un umbral de seis horas, inútil. La inspección de esos
huecos largos explica por qué, y produce el segundo hallazgo del spike:

```
   min   evento previo      -> siguiente
 235.2   sessionCompleted   -> progressUpdated
 219.6   sessionCompleted   -> progressUpdated
  47.7   sessionCompleted   -> progressUpdated
  36.0   progressUpdated    -> progressUpdated
  23.3   sessionCompleted   -> progressUpdated
  17.7   progressUpdated    -> progressUpdated
  17.3   sessionCompleted   -> progressUpdated
```

**`sessionCompleted` no es terminal en el flujo de actividades.** Cinco de
los siete huecos largos son sesiones que terminaron y revivieron horas
después — trabajo posterior sobre el PR, seguimiento del arquitecto. Ese
tiempo es ocio, no estancamiento, y contarlo como silencio del agente
envenena la estadística y dispararía alertas sobre sesiones que ya
entregaron.

Regla derivada, obligatoria en el detector: **el reloj de silencio corre
solo mientras el último evento del agente no sea `sessionCompleted` ni
`sessionFailed`.** Con esa exclusión quedan dos huecos sanos por encima de
15 minutos en 3.749 — trabajo legítimo de larga duración, ambos
`progressUpdated → progressUpdated`.

### 4.3 Elección del umbral

| N (min) | Sanos > N | Falsos positivos | Estancamientos > N | Cobertura |
|---:|---:|---:|---:|---:|
| 5 | 50 | 1.33% | 8 | 88.9% |
| 10 | 14 | 0.37% | 8 | 88.9% |
| **15** | **7 (2 tras excluir ocio)** | **0.19% (0.05%)** | **8** | **88.9%** |
| 20 | 5 | 0.13% | 7 | 77.8% |
| 30 | 4 | 0.11% | 7 | 77.8% |
| 60 | 2 | 0.05% | 4 | 44.4% |

15 minutos es la rodilla de la curva: bajar a 10 no gana cobertura y triplica
los falsos positivos; subir a 20 pierde un estancamiento de cada cuatro. El
único caso que ningún umbral captura es un rescate con 0.33 min de silencio
previo — el arquitecto agregando instrucciones, no rescatando; es ruido del
clasificador, no un fallo de detección.

Con N=15 min, el intervalo de polling de 60 s del Inception resulta quince
veces más fino de lo necesario. **Cinco minutos entrega la misma detección
con una quinta parte de los requests** y deja margen de sobra frente a
cualquier cuota. Recomendación para la ADR de polling: default 300 s.

### 4.4 El prompt mágico sobrevive al escrutinio

Los nueve rescates recibieron respuesta del agente: 9 de 9, latencia mediana
de 1.17 min, peor caso 7.96 min. El texto es literalmente «Completa la
tarea» en cinco de los seis casos inspeccionados, «Continúa» en el otro.

El riesgo 5 del Inception queda confirmado como supuesto válido *hoy* y
cuantificado: la rama de recuperación automática puede asumir respuesta en
menos de 8 minutos. Corolario operativo: **si tras enviar el prompt no hay
evento del agente en 10 minutos, el nudge falló** y corresponde escalar a
alerta en vez de reintentar. Ese es el canario que avisará el día que Jules
deje de obedecer la frase.

## 5. Contrato del API, verificado en vivo

El cursor incremental funciona como exclusivo: `filter=create_time > "…"`
no devuelve la actividad pivote ni ninguna anterior. Confirmado sobre datos
reales, no solo sobre el discovery doc.

**El parámetro plano `?createTime=` que muestra el changelog de enero
devuelve 400 INVALID_ARGUMENT.** La forma canónica es `filter`. Cualquier
implementación copiada del changelog está rota.

Orden de las listas: `sessions.list` desciende por `createTime`;
`activities.list` asciende. La primera página de sesiones trae las más
recientes, que es lo que el poll global necesita.

Tasa: 30 requests en 30 segundos, treinta 200 limpios, **ningún header de
cuota o rate-limit expuesto**. No hay señal del lado del cliente para saber
qué tan cerca está el techo, así que el presupuesto de requests debe ser
autoimpuesto y conservador. Con 25 sesiones vivas y polling de 5 min, el
gasto es de unos 300 requests por hora.

Mapa de errores para el cliente:

| Situación | HTTP | `error.status` | Señal fiable |
|---|---:|---|---|
| Sin credencial | 401 | UNAUTHENTICATED | `details[].reason = CREDENTIALS_MISSING` |
| Key inválida o revocada | 401 | UNAUTHENTICATED | idéntico al anterior |
| Sesión inexistente | 404 | NOT_FOUND | — |
| Filtro mal formado | 400 | INVALID_ARGUMENT | — |

La key inválida devuelve el mensaje «API keys are not supported by this
API», que es falso y mandaría al arquitecto a depurar el problema
equivocado. **Clasificar por `status` y `reason`, nunca por el texto.**

## 6. Firma de cada modo de fallo

Del muestreo por estado, el último evento antes de detenerse:

| Estado | Cola observada | Lectura |
|---|---|---|
| COMPLETED | `sessionCompleted`/agent ×14 | cierre limpio |
| FAILED | `sessionFailed`/agent ×7, `userMessaged`/user ×4 | los 4 casos con cola de usuario son nudges que nunca obtuvieron respuesta: muerte silenciosa confirmada |
| PAUSED | `progressUpdated`/agent ×6, `userMessaged`/user ×2 | murió a mitad de trabajo; PAUSED no es siempre acción deliberada del arquitecto |
| AWAITING_USER_FEEDBACK | `agentMessaged`/agent ×1 | pregunta pendiente, detectable de inmediato por estado |

Los seis PAUSED con cola `progressUpdated` son la colgada silenciosa que
motiva el proyecto, y llevan meses ahí. Confirma que el estado por sí solo
no basta: hay que cruzarlo con frescura.

## 7. Q5 sin ejecutar, y por qué

`sendMessage` sobre una sesión terminal es la única pregunta abierta.
Contestarla exige escribir sobre el workspace real: si el API acepta el
mensaje, Jules podría despertar y tocar un repositorio de producción. No
corresponde decidir eso unilateralmente con la credencial prestada.

Cuesta un comando cuando haya una sesión prescindible identificada:

```bash
python3 spike_cadence.py probe terminal-send --session <id COMPLETED> --yes
```

Mientras tanto, la escalera de recuperación asume el caso pesimista: sobre
FAILED no se envía mensaje, se alerta.

## 8. Cambios que este spike impone al diseño

Umbral N de 15 minutos y polling default de 300 s, ambos con base empírica.
Reloj de silencio congelado tras `sessionCompleted`. Ventana de 10 minutos
para verificar que un nudge surtió efecto. Clasificación de errores por
código y no por mensaje. Presupuesto de requests autoimpuesto, porque el API
no publica cuota. Y una corrección al Problem Brief: la tasa de intervención
real es ~14%, no una de cada tres — el proyecto sigue justificado por las 25
sesiones muertas y los 24 repositorios, no por la frecuencia estimada.

## 9. Higiene de la credencial

La key se usó solo desde variable de entorno, nunca se escribió en logs ni
en los artefactos generados. **Aun así conviene rotarla**: viajó por un chat
y quedó en el historial de esta conversación. Se revoca y se regenera en
`https://jules.google.com/settings#api`.

## Apéndice — Comandos que produjeron este informe

```bash
export JULES_API_KEY=…                       # nunca en el history: usar read -rs
python3 spike_cadence.py probe auth
python3 spike_cadence.py backfill --per-state 14   # censo + cadencia por estado
python3 spike_cadence.py nudges --n 70             # separa sano de estancado
python3 spike_cadence.py probe order
python3 spike_cadence.py probe cursor --session <id>
python3 spike_cadence.py probe rate --n 30 --window 30
```

Datos crudos en `real_out/`: `backfill.jsonl`, `nudges.jsonl`, `probes.jsonl`.
El mock (`mock_jules_api.py`) queda como suite de regresión del instrumento,
ejecutable sin credencial.
