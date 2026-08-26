# Moon-Jules

*El monitor de tu enjambre. Para que Jules no se duerma sin que te enteres.*

Moon-Jules vigila tus sesiones de [Jules](https://jules.google.com) en
todos tus repositorios, detecta cuándo se quedan colgadas y las reactiva.
Corre en tu máquina, en una pestaña de terminal. No hay servidor, no hay
nube, no hay UI web.

## El problema, en dos números

Jules sano emite un evento cada **26 segundos**. Cuando se cuelga, la
mediana hasta que un humano lo nota es de **52 minutos**, y el peor caso
medido fue de 7.6 horas. Cada uno de esos intervalos congela la cola
entera del repositorio.

Moon-Jules lo detecta en **15 minutos**, con una tasa de falsa alarma del
0.05%. Esos números salen de medir 3.749 huecos reales entre eventos y
los 9 rescates manuales que el arquitecto hizo a mano
(`docs/spikes/`), no de una heurística de pizarra.

## Instalación

```bash
git clone git@github.com:abnerh69/Moon-Jules.git
cd Moon-Jules
pip install -e ".[dev]"

mkdir -p ~/.config/moon-jules
cp config.example.toml ~/.config/moon-jules/config.toml
```

La API key se obtiene en https://jules.google.com/settings#api y **nunca
se escribe en el config**: se referencia. El valor vive en un `.env` que
no se versiona.

```bash
cp .env.example ~/.config/moon-jules/.env
chmod 600 ~/.config/moon-jules/.env
$EDITOR ~/.config/moon-jules/.env      # rellenar JULES_API_KEY

moon-jules doctor
```

Alternativa sin fichero, para una sola sesión de shell:

```bash
read -rs JULES_API_KEY && export JULES_API_KEY
```

El entorno real siempre gana sobre el `.env`, así que puedes sobrescribir
para una ejecución sin tocar nada.

## Uso

```bash
moon-jules doctor          # verifica credencial, config y conectividad
moon-jules sources         # repositorios conectados y su modo de autonomía
moon-jules status          # una pasada: qué está vivo, bloqueado o colgado
moon-jules status -a       # solo lo que requiere atención
moon-jules watch           # el bucle de vigilancia, Ctrl+C para salir
moon-jules watch --dry-run # dictamina sin ejecutar ninguna acción
moon-jules -v status       # con logging en detalle por consola
```

### Triaje de la deuda acumulada

Si el enjambre lleva tiempo funcionando, el primer `status -a` mostrará
todo lo que se quedó por el camino — y ese ruido enterrará lo que sí es
accionable. Se silencia una vez:

```bash
moon-jules ack --stale-before 2026-07-01        # muestra qué silenciaría
moon-jules ack --stale-before 2026-07-01 --yes  # lo silencia
moon-jules ack --list                           # ver lo silenciado
moon-jules unack <session-id>                   # devolverlo al radar
moon-jules status --all                         # incluir lo silenciado
```

`--stale-before` mide cuándo **empezó** la sesión, no cuándo se tocó por
última vez: el API devuelve fechas recientes para sesiones muertas hace
meses.

Silenciar no arregla nada: saca el hallazgo del radar. Se silencia el par
(sesión, veredicto), así que **si el veredicto cambia, reaparece**: una
sesión silenciada como `paused_stale` que pase a `failed` vuelve a
avisar.

### Cortar la autonomía

```bash
moon-jules pause                          # todo a read_only, indefinido
moon-jules pause --for 2h --reason "revisando PRs"
moon-jules pause CryptBot-V3              # solo un repositorio
moon-jules resume                         # o `resume CryptBot-V3`
```

Pausar **no apaga la detección**: sigue vigilando y avisando, solo deja
de actuar. El estado pausado se anuncia en cada salida — una pausa
silenciosa es peor que no tenerla. Con `--for` se levanta sola, que es
el remedio contra el fallo real: olvidarse de reanudar.

### ¿Sigue siendo correcto el umbral?

```bash
moon-jules calibrate                    # analiza las 70 sesiones más recientes
moon-jules calibrate --sessions 150
moon-jules calibrate --json cal.json    # guarda los datos crudos
```

Reejecuta sobre tu histórico el análisis que fijó N = 15 min, usando tus
propios rescates manuales como etiqueta: cada vez que escribiste
"Completa la tarea" dejaste constancia del instante en que decidiste que
una sesión estaba colgada.

La calibración caduca. Si Jules cambia su cadencia, N deja de valer y el
detector empieza a fallar en silencio. Conviene reejecutarlo cada
tantas semanas, o cuando `history` muestre nudges sin respuesta.

### Publicar el estado

```bash
moon-jules publish --stdout     # ver el snapshot sin publicarlo
moon-jules publish              # segun [publish] del config
```

`watch` publica en cada ciclo cuando `publish.enabled = true`. El
snapshot lleva un **latido** que se reescribe siempre, cambie o no el
estado: así un lector puede distinguir "todo en orden" de "nadie está
mirando". Contrato completo en `docs/SNAPSHOT.md`; montaje de Firebase y reglas de
seguridad en `docs/RTDB.md`.

### Dejarlo corriendo

`watch` en una pestaña de terminal muere al cerrarla, al cerrar sesión y
al dormirse la máquina. Para que sobreviva:

**Instálalo desde el mismo entorno virtual donde está Moon-Jules.** El
servicio queda apuntando a un ejecutable concreto y para siempre; si lo
instalas con el entorno desactivado, apuntaría a otra instalación. Se
comprueba antes de instalar y se rechaza si no coincide.

```bash
moon-jules service install               # launchd (macOS) o systemd --user
                                         # nunca con sudo: es de usuario
moon-jules service install --caffeinate  # además, evita el sueño por inactividad
moon-jules service status                # ¿cargado? ¿y publicando?
moon-jules service show                  # ver la definición sin instalar
moon-jules service uninstall
```

`service status` distingue dos cosas que se confunden: si el sistema
tiene el servicio **cargado**, y si de verdad ha completado un ciclo
hace poco. Lo primero puede ser cierto y lo segundo falso —un error de
configuración, por ejemplo—, y entonces avisa.

**Cerrar la tapa duerme el portátil y ningún servicio lo impide.**
`--caffeinate` evita el sueño por inactividad, no el de la tapa. Si esta
máquina debe vigilar sin supervisión, déjala abierta y conectada, o
cuenta con que el relevo se disparará.

### Varias máquinas, una vigilando

```bash
moon-jules relay                  # quién está designado y quién reclamó
```

Con `relay.enabled = true` y `publish.target = "rtdb"`, varias máquinas
pueden ejecutar `watch` a la vez pero solo una actúa. Las demás siguen
vigilando y publicando su latido —están vivas y disponibles—, sin tocar
Jules.

**Designar se hace desde la app**, no desde aquí: las reglas reservan esa
escritura al arquitecto, porque una máquina no puede autodesignarse. Y
el momento de necesitarlo es justo cuando una cayó y tú estás en otro
sitio.

Designar es **proponer**: la instancia elegida confirma escribiendo su
reclamación. Firebase rechaza designar una máquina cuyo latido haya
caducado.

Desde la app también se pueden ordenar acciones concretas —desatascar
una sesión, silenciar, pausar— con caducidad e idempotencia. Contrato en
`docs/SNAPSHOT.md`.

### Historial

```bash
moon-jules history                 # nudges enviados y su desenlace
moon-jules history --session <id>
```

Los logs de `watch` van a `~/.local/state/moon-jules/logs/`, con rotación
y **redacción de credenciales**: ninguna API key llega al disco.

`status` devuelve código 1 si algo requiere atención, así que sirve en un
`cron` o en el prompt del shell.

## Autonomía

Tres modos, configurables **por repositorio**. El default es el más
conservador; la autonomía se gana repo por repo cuando confías en lo que
ves.

| Modo | Qué hace |
|---|---|
| `read_only` | observa y avisa. Ninguna escritura. **Default.** |
| `unblock_only` | además envía el prompt de continuación y aprueba planes propios |

Moon-Jules **no reparte trabajo**: no decide ni asigna la siguiente
tarea. Eso lo resuelve una GitHub Action al fusionar el PR. Tampoco
cierra issues, ni mergea PRs, ni cambia labels, ni archiva sesiones. La lista completa de lo que no hará está en
`docs/02-MoonJules-Inception.md` §4.

## Estado

**v0.4.0 — `watch` desatendido, triable y con freno.** Funcionan `doctor`, `sources`, `status`
y `watch`, con detector calibrado, notificaciones nativas, logging con
redacción de credenciales, carga desde `.env`, lock de instancia única,
triaje de hallazgos, historial local, interruptor de autonomía y
recalibración del umbral. 300
tests, incluido un barrido de secretos sobre todo el árbol.

`moon-jules doctor` mide la latencia real de tu API y proyecta el coste
de un ciclo, que es el dato que dice si un ciclo lento es culpa del
servidor o del cliente.

Moon-Jules pide respuestas parciales: no descarga los diffs ni las
capturas de pantalla que Jules adjunta a cada actividad. El código de
tus repositorios no se guarda **y tampoco se descarga**.

`watch` ya se puede dejar corriendo en una pestaña y olvidarse: avisa por
notificación del sistema, deja rastro en disco y no se pisa consigo mismo.

Publica su estado para lectores externos (`docs/SNAPSHOT.md`).

Pendiente: vigilancia del contrato del API y verificación de
`sendMessage` sobre sesión terminal. Ver `docs/BACKLOG.md`.

## La app

`app/` contiene el panel que consume lo publicado. Su capa de datos y su
lógica de presentación son Dart puro y se prueban sin emulador: `cd app
&& flutter test` (112 tests). Ver `app/README.md`.

## Documentación

| Documento | Qué contiene |
|---|---|
| `docs/01-MoonJules-Problem-Brief.md` | el problema, medido |
| `docs/02-MoonJules-Inception.md` | alcance y la NO list |
| `docs/adr/` | las cinco decisiones y sus porqués |
| `docs/spikes/` | de dónde salen los números |
| `docs/CONFIGURACION-NATIVA-Y-NOTIFICACIONES.md` | qué se tocó en `app/android/`, por qué, y cómo diagnosticar un aviso que no llega |
| `AGENTS.md` | contrato de trabajo para agentes en este repo |
