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

### E28 — Notificaciones push *(entrega 20)*
FCM con la misma cuenta de servicio que publica el snapshot. Sin esto,
"recibo una alerta" es "veo la alerta cuando abro la app". Reutiliza la
supresión de repetidos del `Notifier` y retira los tokens que FCM da por
muertos. La alerta de instancia caída **no** puede salir de aquí: la
detecta el teléfono contra `heartbeat_ms`.

### E29 — Las claves nulas no viajan *(entrega 20)*
Descubierto en datos reales: RTDB omite los nulos, así que el mismo
snapshot tenía dos formas según el destino. Ahora se podan antes de
publicar y el contrato es uno solo: **clave ausente significa
desconocida, nunca cero**.

### E30 — Capa de datos de la app *(entrega 21)*
`app/lib/src/model/` en Dart puro —sin Flutter— con el modelo del
esquema 3, la caducidad del latido y las órdenes. **36 tests
verificados** con el SDK de Dart. `app/lib/src/data/` es el pegamento
con Firebase y la única capa sin cubrir, a propósito: cuanto más fina,
menos código sin verificar. Falta el andamiaje de Flutter y la pantalla.

### E31 — Las dos vías de aviso se separan *(entrega 21)*
`notify.local` y `notify.fcm` son cosas distintas: la primera avisa a la
máquina que vigila, la segunda a donde está el arquitecto. Con la
vigilante en otro país se quiere la segunda sin la primera. Además,
`fcm = true` con `enabled = false` era una contradicción silenciosa y
ahora es error de arranque.

### E32 — Los tests de la app no compilaban *(entrega 22, correctivo)*
Los imports apuntaban a `moonjules_core`, el nombre del paquete de
andamio usado para verificarlos, no al real. Verificar en un paquete con
otro nombre invalida justo lo que la verificación debía garantizar. Se
corrigen y se revalidan en un andamio llamado igual que el paquete
entregado. Incluye la retirada de la plantilla de `flutter create`, que
en el canal `master` genera sintaxis experimental.

### E33 — Pantalla en modo lectura *(entrega 23)*
Una pantalla y dos ventanas de detalle. La lógica de presentación
—qué se ve primero, qué significa cada estado, de qué instancia leer
cuando la habilitada calló— vive en `model/panel.dart` como Dart puro:
**54 tests verificados**. Los widgets solo dibujan. Sin botones de
acción: se ganan, no se asumen.

### E34 — Las dos vías de aviso funcionan a la vez *(entrega 23)*
Encontrado en campo: activar el push apagaba el aviso local aunque
`local = true`, y el config no lo anunciaba. El resultado fue quedarse
sin ninguna alerta efectiva, porque el push no tenía destinatario. Ahora
avisan las dos y se deja constancia en el log cuando ninguna entrega.

### E35 — Pulido de la lista *(entrega 24)*
De la primera captura en el móvil. Faltaba `uses-material-design`, así
que los iconos salían como cuadraditos. Las sesiones fallidas mostraban
un guion en la columna de tiempo —correcto, porque su reloj está
congelado, pero mudo—: ahora muestran la edad, etiquetada, porque muda
y abierta son preguntas distintas. Y cada fila cabe en dos líneas: con
nueve entradas, un título de dos empujaba el motivo fuera de pantalla.

### E36 — El mensaje del agente viaja *(entrega 25)*
Una sesión murió con una pregunta dentro —"¿intento A6 y A9 manualmente?"—
y el snapshot solo publicaba el `reason` del API, que repite siempre el
mismo texto inútil. Ahora el último `agentMessaged` se persiste y se
publica para lo que requiere atención. Esquema 3 → 4.

### E37 — Designar es cosa de la app *(entrega 25)*
`moon-jules relay <instancia>` intentaba escribir `control/desired` y
siempre fallaba: las reglas lo reservan al arquitecto porque una máquina
no puede autodesignarse. Dos entregas contradiciéndose. El comando queda
solo consultando y el botón vive en la app, que es donde estás cuando
una máquina cae.

### E38 — No mentir sobre por qué no se ve algo *(entrega 26)*
Cuatro cosas de la misma familia. El botón de designar solo se ofrece
cuando puede funcionar, con el motivo al lado. Si ninguna sirve, se dice
—todos los botones apagados y sin explicación parecerían una app rota—.
Sin conexión, la app avisa y **no atribuye el silencio a las máquinas**:
el SDK sirve de caché y mostraría latidos rancios como si el enjambre
hubiera muerto. Y el reloj se corrige con `.info/serverTimeOffset`,
porque un móvil adelantado daría por caídas máquinas sanas.

### E39 — Avisos push e identidad visual *(entrega 27)*
La app registra su token FCM al abrirse y sigue las rotaciones —un token
viejo deja de recibir sin avisar—. Si el registro falla, la pantalla lo
dice: sin push solo hay alertas con la app abierta. Nombre visible
«Moon Jules» en vez del identificador del paquete, e icono propio
generado por `tools/generar_iconos.py`.

### E40 — Acceso sin credenciales en el binario *(entrega 28)*
Con `--dart-define` el correo y la contraseña quedaban compilados dentro
del APK. Ahora se teclean una vez y viven en el Keystore. Ventana
deslizante de siete días que se renueva al entrar; al vencer se cierra
la sesión de Firebase de verdad y se puede desbloquear con biometría,
que **desbloquea** la contraseña guardada en vez de sustituirla. Una
marca de acceso en el futuro se trata como vencida: sin eso, atrasar el
reloj del dispositivo abriría la ventana para siempre.

### E41 — El canal que faltaba *(entrega 29)*
Las notificaciones se enviaban, FCM las aceptaba y el teléfono las
descartaba en silencio: faltaba el canal de Android. Se declara en el
manifiesto y se crea al arrancar; con una sola de las dos no basta.
Incluye icono monocromo para la barra, que Android pinta como silueta.

Y lo que hizo que costara una noche: la app mostraba una conjetura
—«comprueba el permiso»— en vez del error real, `ack --list` no decía
qué sesión era cuál, y el log decía «1 notificación enviada» sin
mencionar a cuántos dispositivos. Las tres cosas eran información que el
sistema tenía y no enseñaba.

### E42 — La capa de UI también se verifica *(entrega 30)*
`_Contenido.avisos` quedó declarado `AsyncValue<String?>` y usado como
`AsyncValue<RegistroAvisos>`: la app no compilaba. Se entregó así porque
la verificación cubría solo el modelo —Dart puro— y la capa de Flutter
iba a ciegas. Ahora el SDK de Flutter está instalado en el entorno de
desarrollo y **toda entrega pasa por `flutter analyze` y `flutter
test`** antes de empaquetarse. Es el segundo fallo de esta clase: el
primero fueron los imports de la entrega 21.

### E43 — Desugaring para el canal *(entrega 31)*
`flutter_local_notifications` usa `java.time` y Gradle aborta sin *core
library desugaring*. Se activa junto con Java 11, que las bibliotecas de
desugar 2.x exigen —y de paso desaparece el aviso de «source value 8 is
obsolete»—. Anotado en `app/README.md`: es mucha maquinaria para crear
un canal, y el día que estorbe se sustituye por quince líneas de Kotlin
en `MainActivity`.

### E44 — La memoria de lo nativo *(entrega 32)*
`docs/CONFIGURACION-NATIVA-Y-NOTIFICACIONES.md`. Los `apply-NN.sh` se autoborran: el estado queda en
git, el motivo no, y ninguno de esos ajustes es evidente al leer el
fichero después. Recoge las ocho cosas configuradas en `app/android/`,
qué falla sin cada una, y el árbol de diagnóstico de «no llegan las
notificaciones» en el orden en que salió caro descubrirlo.

### E45 — El push se quedaba sin destinatarios *(entrega 34)*
`refrescar_dispositivos` miraba `notifier.backend`, que devuelve el
primero de la lista. Con el aviso local en primera posición —lo normal—
el backend de FCM nunca recibía tokens y `send` salía en silencio por
una rama en `debug`. Síntoma: notificaciones en el escritorio, ninguna
en el móvil, y ni una línea de log que lo explicara. Introducido en la
entrega 23 al pasar de un backend a varios; los tests no lo vieron
porque probaban el `Notifier` con backends puestos a mano, nunca el
cableado real.

Incluye un aviso en `doctor` cuando el servicio corre una versión
distinta de la instalada: no reiniciar tras aplicar una entrega costó
varias vueltas persiguiendo fallos ya arreglados.

### E46 — La pantalla también se prueba *(entrega 35)*
Diecinueve tests de widget que montan el panel con providers fijos, sin
Firebase ni dispositivo. Cubren lo que el modelo no puede: que lo
decidido se pinte, y la maraña de avisos de la cabecera —sin conexión,
nadie vigilando, relevo sin confirmar, estado del push— que se excluyen
o se acumulan y nunca se habían ejercitado. Incluye el arreglo de
`ack --stale-before`, que filtraba por `updateTime` y dejaba fuera a las
sesiones `FAILED`, que son la mayor parte de la deuda: silenció 3 de 9.

### E47 — La antigüedad se mide por `createTime` *(entrega 36)*
Segundo intento sobre `ack --stale-before`. El primero cayó en
`update_time or create_time` y seguía fallando: el API devuelve
`updateTime` de hoy para sesiones fallidas en mayo, así que las daba por
actuales. «Deuda vieja» significa que el trabajo empezó hace mucho, y
eso lo responde `createTime`, que además es inmutable. Corregir el
síntoma sin revisar si el dato era el correcto costó una entrega de más.

Incluye en la app la sección plegada de sesiones silenciadas: pintarlas
idénticas y en rojo junto a un problema real vaciaba de significado el
color.

### E48 — Cuándo habló Jules por última vez *(entrega 37)*
El detalle mostraba «lleva abierta 104 d» sin una sola fecha, y el único
candidato publicable —`updateTime`— resultó no medir nada: el API lo
mueve a hoy para sesiones muertas en mayo.

El dato bueno estaba guardado desde la entrega 01 (`last_agent_at`) y
nunca se publicaba. Pero también estaba mal para sesiones terminales:
`_offline_freshness` lo rellenaba con ese mismo `updateTime`. Al
detector le daba igual —su reloj está congelado— pero como dato
publicable era falso. El instante real vivía en el `createTime` de la
actividad `sessionFailed`, que se leía para sacar la razón y se tiraba.

Esquema 4 → 5. El detalle muestra ahora tres fechas rotuladas y traduce
el tipo de evento: `sessionFailed` no es para leerse en una pantalla.

### E49 — Las fallidas se reactivan *(entrega 38)*
La razón de ser del proyecto, ausente hasta ahora. Nueve de las diez
sesiones problemáticas del enjambre están en `FAILED`, y la escalera las
excluía por una suposición nunca comprobada. Ahora reciben un intento;
si no reviven, se alerta y no se insiste.

Incluye el veredicto `failed_asking` para las que mueren con una
pregunta sin responder, verificado contra la sesión real de
`ppp-n-kits`. La ventana para contestar a tiempo era de **32 segundos**,
así que el valor está en el diagnóstico, no en la velocidad.

### E50 — La regla del abandono *(entrega 39)*
Consecuencia de la 38: al habilitar la reactivación, ocho sesiones
muertas en mayo pasaron a ser candidatas a revivir solas. Nunca se actúa
sobre una sesión que nadie ha mirado en 48 horas —medido desde el último
contacto de cualquiera, no desde la apertura—. Se aplica en el único
punto por el que pasan todos los dictámenes.

Incluye `{root}/settings` en RTDB con el plazo y el prompt, con
precedencia sobre el config local; un valor absurdo o ilegible se ignora
y gana el `config.toml`, que no depende de la red.

### E51 — Un solo paso para desplegar *(entrega 40)*
`tools/desplegar.sh`. Activa el entorno virtual antes de tocar el
servicio, comprueba que haya un Android conectado antes de gastar dos
minutos compilando, e instala release y no debug. `--limpio` para cuando
cambie el canal de notificaciones, con el aviso de que borra las
credenciales guardadas.

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

### E11 — Verificación de `sendMessage` sobre sesión terminal *(entrega 38)*
**Resuelta, y la respuesta era que sí.** El API acepta escribir sobre
una sesión `FAILED` y la sesión revive. Estuvo bloqueada veinte
entregas, y mientras tanto la suposición prudente se fue repitiendo
hasta convertirse en regla implementada, probada y documentada. Ver la
enmienda de ADR-002.

### E12 — Arranque persistente *(entrega 17)*
`moon-jules service install` genera e instala el agente de usuario:
`launchd` en macOS, `systemd --user` en Linux. Rutas absolutas y PATH
explícito —launchd no expande `~` ni hereda entorno—, y `ThrottleInterval`
para que un error de configuración no produzca un bucle de reinicio.
`service status` separa "cargado" de "publicando", que no es lo mismo.
Sigue sin ser obligatorio: `watch` a mano funciona igual (Inception §6).
