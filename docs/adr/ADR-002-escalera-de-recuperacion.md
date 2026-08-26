# ADR-002 — Detección y escalera de recuperación

```meta
Estado:   Aceptada
Fecha:    2026-08-24
Enmienda: 2026-08-26 (entrega 38) — las sesiones FAILED se reactivan
Contexto: Spike 01 (v1.0) §4, Inception v3.0 §6
```

## Contexto

Hay que decidir cuándo una sesión está estancada y qué hacer entonces.
El Spike 01 reconstruyó 3.749 huecos entre eventos del agente sobre 70
sesiones reales y, usando los 9 rescates manuales del arquitecto como
etiqueta, separó dos poblaciones: sano con mediana de 26 s, estancado
con mediana de 52 min.

## Decisión

### Señal

Dos señales ortogonales: **estado de la sesión** y **frescura del último
evento del agente**. El estado por sí solo no basta — las sesiones
colgadas en silencio quedan en `PAUSED` o `IN_PROGRESS` con apariencia
normal.

Tres invariantes del cálculo de frescura, cada uno con su razón medida:

1. **Solo cuentan actividades con `originator == "agent"`.** Si contaran
   las del usuario, cada nudge que envía Moon-Jules reiniciaría su propio
   reloj y una sesión muerta parecería viva.
2. **El reloj se congela si el último evento del agente es
   `sessionCompleted` o `sessionFailed`.** `sessionCompleted` no es
   terminal en el flujo de actividades: cinco de los siete falsos
   positivos del spike eran sesiones que terminaron y revivieron horas
   después. Ese tiempo es ocio, no estancamiento.
3. **Se usa `createTime` de la actividad, no `updateTime` de la sesión.**
   El segundo se mueve por causas ajenas al progreso del agente.

### Umbral

**N = 900 s (15 minutos)**, parametrizable por source.

| N | Falsos positivos | Cobertura |
|---:|---:|---:|
| 10 min | 0.37% | 88.9% |
| **15 min** | **0.05%** | **88.9%** |
| 20 min | 0.13%* | 77.8% |

(*) sin excluir el ocio post-`sessionCompleted`; con la exclusión, 15 min
baja a 2 casos en 3.749.

15 min es la rodilla: bajar a 10 no gana cobertura y multiplica los
falsos positivos; subir a 20 pierde uno de cada cuatro estancamientos.

### Escalera

| Estado | Señal | unblock-only | full-auto |
|---|---|---|---|
| QUEUED | en cola > 30 min | alerta | alerta |
| PLANNING | silencio > N | esperar; alerta a 2N | ídem |
| AWAITING_PLAN_APPROVAL | inmediata | `approvePlan` si la sesión es nuestra, si no alerta | ídem |
| AWAITING_USER_FEEDBACK | inmediata | `sendMessage` | ídem |
| IN_PROGRESS | silencio > N | `sendMessage` | ídem |
| PAUSED | silencio > N | alerta (no hay resume en el API) | ídem |
| FAILED | inmediata | `sendMessage` | `sendMessage` |
| COMPLETED + cola pendiente | inmediata | nada | `assign-next` |

### Enmienda (entrega 38): una sesión fallida se reactiva

**Verificado contra el API el 2026-08-26.** `sendMessage` sobre una
sesión en `FAILED` devuelve 200, y la sesión vuelve a `IN_PROGRESS`. Se
comprobó sobre una fallida real de hace 39 horas: revivió y siguió
trabajando.

La versión original decía lo contrario. El Spike 01 dejó esa pregunta
abierta —comprobarla exigía escribir sobre el workspace del arquitecto—
y la suposición prudente se repitió durante veinte entregas como si
fuera un hecho establecido. **Esa regla dejaba fuera nueve de cada diez
sesiones problemáticas del enjambre**, que es tanto como decir que
dejaba fuera el motivo de existir del proyecto.

La lección no es que la suposición fuera errónea, sino que una pregunta
sin responder se convirtió en respuesta por repetición. Lo que estaba
marcado como «pendiente de verificar» en un documento acabó
implementado, probado y documentado como si estuviera cerrado.

Reglas de la reactivación:

- Una fallida recibe **un** intento. Si no revive pasado el plazo de
  verificación, se alerta y **no se insiste**: un segundo prompt
  idéntico no la levantará y cada intento cuesta cuota.
- Mientras está dentro del plazo no se toca: `reactivandose`.
- El presupuesto de nudges sigue aplicando.

### Murió preguntando

Una sesión que falla con una pregunta del agente sin responder es
diagnósticamente distinta de una que falla por dependencias, y hasta
ahora se veían idénticas. Se reconoce mirando hacia atrás desde el
`sessionFailed`: si el evento anterior del agente fue `agentMessaged` y
nadie contestó entre medias, murió preguntando.

Se reactiva igual —muerta es peor que mal contestada— pero el veredicto
propio permite que la alerta lleve la pregunta.

**La ventana para responder a tiempo no existe.** Medida en un caso
real: Jules preguntó a las 03:52:06 y se rindió a las 03:52:38.
Treinta y dos segundos. Ningún intervalo de polling llega a eso, y por
eso se descartó el polling adaptativo: el valor no está en correr más,
sino en poder rescatarla después.

### Verificación del nudge

Tras enviar un prompt de continuación, **si no aparece un evento del
agente en 600 s (10 min), el nudge falló** y se escala a alerta en vez de
reintentar.

El dato: los nueve rescates históricos respondieron 9 de 9, con mediana
de 70 s y peor caso de 8 min. Los 10 minutos son ese peor caso más
margen. Esta ventana es el canario que avisará el día que Jules deje de
obedecer "Completa la tarea" — riesgo 5 del Inception, convertido de
silencioso en detectable.

### Presupuesto de nudges

Máximo **3 por sesión**. Agotado, se escala a alerta y no se insiste. Un
falso positivo no debe repetirse cada ciclo contaminando el contexto de
la sesión.

## Consecuencias

El umbral queda calibrado contra el juicio real del operador, no contra
una heurística inventada. La contrapartida es que la calibración
caduca: si Jules cambia su cadencia de latidos, N deja de ser válido.
Mitigación: `moon-jules calibrate` (entrega 11) reejecuta el análisis
sobre el histórico y dice si N sigue siendo la elección correcta. No
inventa una puntuación: busca si algún candidato domina al vigente, y a
igualdad prefiere el que detecta antes.

## Alternativas descartadas

**Umbral por percentil móvil** (N = p99 de las últimas 24 h). Se adapta
solo, pero contamina la referencia con los propios estancamientos, que
es exactamente el error que el spike detectó en el cálculo ingenuo por
máximo.

**Detección por contenido** (leer el texto de los `progressUpdated` para
juzgar si hay avance real). Requiere criterio semántico, es frágil y
choca con el NO 9 del Inception.
