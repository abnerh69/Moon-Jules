# ADR-002 — Detección y escalera de recuperación

```meta
Estado:   Aceptada
Fecha:    2026-08-24
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
| FAILED | inmediata | alerta | alerta (ver nota) |
| COMPLETED + cola pendiente | inmediata | nada | `assign-next` |

Nota sobre FAILED: el Spike 01 **no** verificó si `sendMessage` funciona
sobre una sesión terminal, porque hacerlo exige escribir sobre el
workspace de producción. Hasta que se verifique, FAILED solo alerta.
Cuando se verifique, full-auto podrá crear sesión nueva con reintento
acotado.

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
Mitigación: `moon-jules calibrate` reejecuta el análisis del spike sobre
el histórico y reporta si N sigue en la rodilla.

## Alternativas descartadas

**Umbral por percentil móvil** (N = p99 de las últimas 24 h). Se adapta
solo, pero contamina la referencia con los propios estancamientos, que
es exactamente el error que el spike detectó en el cálculo ingenuo por
máximo.

**Detección por contenido** (leer el texto de los `progressUpdated` para
juzgar si hay avance real). Requiere criterio semántico, es frágil y
choca con el NO 9 del Inception.
