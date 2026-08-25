# Moon-Jules — Backlog

Épicas planas, sin módulos (Inception §11). Cada una está dimensionada
para caber en **una sesión de Jules**: el plan Pro da 100 al día y este
repo compite por esa cuota con los otros 23.

`E01` está entregada. El orden del resto refleja el trade-off del
Inception §9: gana robustecer detección sobre añadir features, y gana
exponer mejor sobre automatizar más.

## Entregado

### E01 — Núcleo de detección *(entrega 01)*
Cliente del API, modelos, detector calibrado, persistencia SQLite,
config con secretos por referencia, y los comandos `doctor`, `sources`,
`status`, `watch`. 42 tests.

### E02 — Notificaciones nativas *(entrega 02)*
`osascript` en macOS, `notify-send` en Linux, backend nulo en el resto
con degradación silenciosa. Supresión de repetidos por (sesión,
veredicto) con ventana configurable: sin ella, una sesión colgada
avisaría doce veces por hora y el arquitecto silenciaría todo.

### E03 — Logging con redacción *(entrega 02)*
Logger con rotación a `~/.local/state/moon-jules/logs/`. La redacción
vive en el *formatter*, no en un filtro, para alcanzar también los
tracebacks. Doble defensa: por valor exacto y por forma conocida de
credencial.

### E04 — Lock de instancia única *(entrega 02)*
`flock` sobre `watch.lock`. Un segundo `watch` falla con mensaje claro
en vez de duplicar nudges y gastar el presupuesto al doble de velocidad.

### E03b — Secreto en `.env` y barrido automático *(entrega 03)*
Carga de `.env` desde el directorio de configuración y el actual, con el
entorno real ganando. `tests/test_no_secrets.py` barre el árbol entero
en cada `pytest` con los mismos patrones que redactan los logs.
Correctivo de un incidente: ver ADR-004.

### E05 — `moon-jules history` *(entrega 04)*
Sesiones conocidas, nudges enviados y su desenlace, recuperación
mediana. Incluye el cierre del registro de nudges, que existía como
método pero nunca se invocaba: se quedaban en `pending` para siempre y
el canario del riesgo 5 no podía leerse.

### E13 — Triaje de la deuda acumulada *(entrega 04)*
`ack` / `unack` / `status --all`. Épica añadida fuera del orden del
backlog porque los datos la exigían: el enjambre tiene 25 sesiones
muertas y sin triaje `watch` alertaría de las 25 en cada ciclo, para
siempre. El triaje silencia el par (sesión, veredicto), no la sesión: si
el veredicto cambia, reaparece.

### E08 — `moon-jules pause` / `resume` *(entrega 05)*
Interruptor de autonomía, global o por source, con plazo opcional
(`--for 2h`) que se levanta solo. El estado pausado se anuncia en cada
salida. Pausar no apaga la detección: sigue vigilando, deja de actuar.
Ver la enmienda de ADR-005.

### E14 — Coste del ciclo *(entrega 06)*
Correctivo nacido de la primera ejecución real contra 538 sesiones, que
parecía colgada. Paralelismo acotado, caché de razones de fallo,
lectura de nudges en bloque e indicador de progreso. Ver la nota de
campo en ADR-001.

### E15 — Diagnóstico de latencia *(entrega 07)*
`doctor` mide la latencia real por petición y proyecta el coste de un
ciclo. Nace de una duda que no se podía resolver: un `status` de 60
segundos podía ser culpa del API o del cliente, y no había dato. Incluye
`base_url` configurable, sin la cual el mock no servía para probar la
CLI, y unifica el formato de duraciones entre columna y motivo.

### E16 — Peso de las respuestas *(entrega 08)*
Respuesta parcial con `fields` para no descargar diffs ni capturas de
pantalla, y arranque acotado para no paginar la historia entera de cada
sesión. Segunda nota de campo en ADR-001.

### E17 — Listado incremental *(entrega 09)*
El coste del ciclo dejaba de estar en el número de peticiones y pasaba a
estar en repaginar un historial que solo crece. Ahora se pide una página
de novedades y se releen solo las sesiones en curso, con refresco
completo periódico. Tercera nota de campo en ADR-001.

### E18 — Diagnóstico fiel y compatibilidad *(entrega 10)*
`doctor` proyectaba el coste con el modelo anterior al incremental, y
medía la latencia solo sobre páginas de sesiones —que nunca llevaron
artefactos—, así que no decía nada del ahorro real. Ahora mide también
una consulta de actividades y reporta si la máscara de campos sigue
activa. Incluye un gate de compatibilidad con la versión mínima de
Python declarada.

### E20 — Publicación del estado *(entrega 13)*
`moon-jules publish` y publicación en cada ciclo de `watch`. El snapshot
es la frontera con la app de Android: esquema versionado y documentado
en `docs/SNAPSHOT.md`. El latido (`published_at`, reescrito siempre) es
el campo que permite detectar que el MacBook está dormido — una máquina
muerta no puede avisar de que lo está, solo dejar de hablar. Destinos
detrás de una interfaz pequeña: stdout, fichero o RTDB por REST.

### E21 — Relevo entre instancias *(entrega 14)*
El teléfono escribe `control/desired`; la instancia designada confirma
escribiendo `claimed_by`. La app muestra ambos y alerta si difieren: una
designación sin recoger significa máquina dormida. Quien no está
designado pasa a `standby` —sigue vigilando y publicando, no actúa— y lo
mismo ocurre si no puede leer el control, porque tres instancias
actuando agotarían el presupuesto de nudges de una sesión en una sola
pasada. Sin conmutación automática: eso es elección de líder y no cabe
en la v1.

### E22 — Sesión pausada reportada como sana *(entrega 14, correctivo)*
Encontrado en datos reales. La congelación del reloj se evaluaba antes
que el estado, así que una sesión `PAUSED` cuyo último evento fue
`sessionCompleted` salía etiquetada `healthy`. Veredicto propio
`paused_done`: informa sin alarmar, pero no miente.

### E23 — Autenticación con cuenta de servicio *(entrega 15)*
El database secret entra como administrador y salta las reglas: con él,
"el teléfono solo escribe `control/desired`" lo sostenía este código y
no la base de datos. Con cuenta de servicio y `auth_variable_override`,
las instancias escriben bajo una identidad acotada y las reglas se les
aplican. El token va en cabecera, se renueva solo y no viaja en la URL.
Guía y reglas en `docs/RTDB.md`.

### E24 — Canal de comandos *(entrega 16)*
La app ordena acciones concretas: `nudge`, `approve_plan`, `ack`,
`unack`, `pause`, `resume`, `refresh`. RTDB no es una cola, así que cada
orden lleva `id` —idempotencia en SQLite— y `expires_at` —una orden
vieja ejecutada tarde es peor que una perdida—, y solo la instancia
habilitada obedece. Un comando es mando a distancia, no autonomía: se
ejecuta aunque haya pausa. Contrato en `docs/SNAPSHOT.md`.

### E25 — Latido verificable por reglas *(entrega 16)*
`heartbeat_ms` en el snapshot permite que las reglas de RTDB **rechacen**
designar una instancia caída. Que la app no lo ofrezca está bien; que no
pueda hacerlo aunque tenga un fallo, es mejor.

### E26 — El servicio apuntaba al binario equivocado *(entrega 18)*
Encontrado en campo. `detectar()` resolvía por `PATH`: instalado desde
un shell sin el virtualenv activo, apuntaba a otra instalación y el
servicio quedaba ejecutando código distinto de forma permanente y
silenciosa. Ahora se resuelve desde el intérprete que ejecuta el
proceso, y se rechaza instalar un binario que reporte otra versión.

### E27 — Diagnóstico de lo que costó una tarde *(entrega 19)*
Cuatro cosas que el propio proyecto debería haber respondido y no
respondía. `doctor` ahora dice si publica y con qué credencial —"¿por
qué no llega nada a la app?" no debe deducirse de un `grep` al config—.
El 401 de RTDB distingue reglas de credencial: Firebase devuelve 401 en
ambos casos y confundirlos manda a revisar el sitio equivocado.
`service install` se niega bajo `sudo` y descarga antes de reescribir el
plist. Y se avisa si hay un entorno virtual activo pero el binario cae
fuera: el punto ciego de la comprobación de versión, porque un shim de
pyenv responde con la versión del entorno activo aunque apunte a otro
paquete.

## Siguiente ola

## Retirado

### E06 y E07 — Cola de issues y `assign-next` *(descartadas, entrega 12)*
Moon-Jules no decide ni asigna la siguiente tarea: lo resuelve una
GitHub Action al fusionar el PR. Se retiran del alcance junto con el
modo `full_auto`, el presupuesto diario y la tabla `assignments`. Ver la
enmienda de ADR-005 y el NO 13 del Inception.

## Ola de autonomía

### E09 — `moon-jules calibrate` *(entrega 11)*
Reejecuta el análisis del Spike 01 sobre el histórico actual y dice si N
sigue siendo la elección correcta. Usa los rescates manuales del
arquitecto como etiqueta, igual que el spike. El veredicto no inventa
una función de puntuación: busca si algún candidato **domina** al actual
—mejor en un eje sin empeorar el otro—, y a igualdad gana el que detecta
antes.

### E10 — Vigilancia del contrato del API
Chequeo periódico de la `revision` del discovery doc. Si cambia, avisa.
Es la mitigación del riesgo 1 del Inception (API en alpha).
*Depende de: E01.*

### E11 — Verificación de `sendMessage` sobre sesión terminal
La única pregunta que el Spike 01 dejó abierta. Requiere una sesión
prescindible y decisión del arquitecto. Si el API lo acepta, habilita
el reintento automático de sesiones `FAILED` en `full_auto`.
*Bloqueada por: decisión del arquitecto.*

### E12 — Arranque persistente *(entrega 17)*
`moon-jules service install` genera e instala el agente de usuario:
`launchd` en macOS, `systemd --user` en Linux. Rutas absolutas y PATH
explícito —launchd no expande `~` ni hereda entorno—, y `ThrottleInterval`
para que un error de configuración no produzca un bucle de reinicio.
`service status` separa "cargado" de "publicando", que no es lo mismo.
Sigue sin ser obligatorio: `watch` a mano funciona igual (Inception §6).
