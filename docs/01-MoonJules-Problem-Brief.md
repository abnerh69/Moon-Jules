# Moon-Jules — Problem Brief

```meta
Versión:    v3.0
Fecha:      2026-08-24
Estado:     Borrador para firma
Reemplaza:  v2.0 (2026-05-19)
Motivo:     Spike 01 midió el enjambre real. Tres cifras estructurales
            del brief anterior eran estimaciones y resultaron incorrectas.
            El problema se confirma; su forma y su coste cambian.
Fuente:     docs/spikes/MoonJules-Spike-01-Cadencia-API.md (v1.0)
```

## Contexto

El arquitecto opera **24 repositorios** conectados a Jules, no cinco: 23
bajo la organización `Informatica-ASHware` y uno bajo la cuenta personal
`abnerh69`. Sobre ellos ha ejecutado **562 sesiones** de trabajo delegado.
Esa es la escala real del enjambre, y es casi cinco veces la que asumía el
brief anterior.

Jules es el único ejecutor: el agente que escribe el código de producción.
No hay segundo ejecutor que lo reemplace. La cuota es pre-pagada; el coste
se paga haya o no progreso.

## El problema, medido

Los dos modos de fallo del brief v2.0 existen y quedan confirmados en los
datos, cada uno con firma propia en el registro de actividades:

- **Detención declarada.** La sesión emite `sessionFailed` con una razón y
  se detiene. 11 sesiones en el histórico.
- **Detención silenciosa.** La sesión queda en `PAUSED` con su último
  evento siendo un `progressUpdated` — murió a mitad de trabajo, sin error,
  sin aviso. 24 sesiones en el histórico, seis de ellas inspeccionadas una
  por una para confirmar la firma.

Lo que cambia es la frecuencia. **La cifra de "una de cada tres sesiones"
no se sostiene.** El estado terminal de las 562 sesiones se reparte así:
93.6% COMPLETED, 4.3% PAUSED, 2.0% FAILED, 0.2% esperando respuesta.

Pero ese censo tampoco es la cifra correcta, por la razón opuesta:
**subestima el problema, porque una sesión rescatada a mano termina en
COMPLETED**. El estado final mide las sesiones que quedaron rotas, no las
que se rompieron.

La medición honesta cuenta la intervención, no el resultado. Cada rescate
manual quedó grabado como una actividad `userMessaged` con el texto
literal que el arquitecto escribió. Sobre las 70 sesiones más recientes,
**7 necesitaron al menos un rescate manual (10.0%)**, y otras 25 sesiones
del histórico completo siguen detenidas hoy sin rescate (4.4%).

**Aproximadamente una de cada siete sesiones requirió o requiere
intervención humana.** No una de cada tres. La cifra real es tres veces
menor que la estimada — y sigue siendo suficiente para justificar el
proyecto, por las razones de la sección siguiente.

Dos matices empujan ese 14% hacia arriba y conviene anotarlos: el conteo
de rescates solo reconoce mensajes cortos con verbo imperativo, y no
detecta los casos que el arquitecto resolvió cancelando y relanzando en
vez de insistiendo.

## Cuánto tarda en notarse

Aquí está el dato que da forma al producto. La distancia entre lo que
Jules tarda normalmente y lo que tarda cuando se cuelga es de dos órdenes
de magnitud:

| | Jules trabajando | Jules colgado |
|---|---:|---:|
| Mediana entre eventos | 26 segundos | 52 minutos |
| Percentil 90 | 1.3 minutos | 7.6 horas |
| Peor caso registrado | — | 7.6 horas |

La columna derecha no mide cuánto tarda Jules en colgarse: mide **cuánto
tarda el arquitecto en darse cuenta**. Son los minutos de silencio
acumulados antes de que un humano escribiera "Completa la tarea". La
mediana de 52 minutos es el coste de la ronda manual; el peor caso de 7.6
horas es una jornada perdida en ese repositorio.

Una máquina que vigile ese mismo silencio lo detecta en 15 minutos con
una tasa de falsa alarma del 0.05%. Ese es, exactamente, el valor que
MoonJules entrega.

## El estado actual del enjambre

**No hay ninguna sesión activa. La última se ejecutó el 2026-06-02, hace
83 días.** Quedan 25 sesiones detenidas, la más antigua sin cambios desde
hace 100 días, repartidas entre repositorios cuyas colas siguen congeladas
detrás de ellas.

Este hecho no estaba en el brief anterior y cambia el marco del proyecto.
El enjambre no está goteando dinero ahora mismo: está **parado**. Por qué
lo está es la única pregunta que los datos no responden y que el
arquitecto debe contestar antes de firmar este documento, porque las tres
respuestas posibles llevan a proyectos distintos:

- Si el enjambre se detuvo *por* este problema, MoonJules no es una red de
  seguridad: es la condición para reanudarlo, y su prioridad sube.
- Si se detuvo por atender otros proyectos, MoonJules es lo que evita que
  la reanudación repita el desgaste, y el plan original se sostiene.
- Si se detuvo porque el flujo migró a otro agente, hay que revisar la
  premisa completa antes de invertir 100–200 horas.

## A quién afecta

El arquitecto, en tres facetas:

- **Como desarrollador**, una sesión detenida sin detectar congela la cola
  entera de ese repositorio, no solo la tarea en curso. Con 24
  repositorios, la superficie de congelación es grande.
- **Como operador**, la ronda manual le cuesta la mediana de 52 minutos de
  latencia por incidente, más el tiempo de la propia ronda, y escala con
  cada repositorio nuevo.
- **Como pagador**, las 35 sesiones muertas del histórico consumieron
  cómputo — mediana de 40 actividades y 25–60 minutos de trabajo cada una
  — sin entregar un solo pull request.

## Qué pasa si no se resuelve

El coste tiene tres componentes, y el brief anterior sobrevaloraba el
primero mientras ignoraba el tercero.

**Cuota desperdiciada.** La estimación anterior de ~$250 al mes y ~$2,500
al año era proyección, no medición, y suponía una tasa de fallo tres veces
mayor que la real. Con el enjambre parado, el desperdicio corriente es
cero. La cifra correcta debe recalcularse sobre 35 sesiones muertas
históricas y el precio real del plan, dato que este brief no tiene.
**Pendiente de verificar antes de usarla en cualquier justificación.**

**Tiempo del arquitecto.** Este sí está medido: 52 minutos de mediana
entre el cuelgue y su detección, en cada incidente, más las rondas de
vigilancia que no encuentran nada. Es el componente sólido del caso.

**Techo de escala.** El componente que el brief anterior no cuantificaba y
que ahora resulta ser el principal. Vigilar manualmente cinco repositorios
es tedioso; vigilar 24 no es viable, y son 24 los que hay. La cartera solo
funciona como mecanismo de paralelización si alguien —o algo— sabe en todo
momento cuáles ramas avanzan. Sin eso, el enjambre se convierte en
acumulación invisible de trabajo parado, que es precisamente lo que
describen las 25 sesiones congeladas desde hace meses.

## Qué justifica el proyecto, en una frase

No la frecuencia del fallo, que resultó menor de lo estimado, sino **su
latencia de detección medida en horas sobre una cartera de 24
repositorios que ya no cabe en una ronda manual** — y las 25 colas que
llevan meses congeladas como prueba de qué pasa cuando la ronda no llega.
