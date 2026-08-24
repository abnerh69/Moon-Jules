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
| `full_auto` | además asigna el siguiente issue de la cola |

Moon-Jules nunca cierra issues, ni mergea PRs, ni cambia labels, ni
archiva sesiones. La lista completa de lo que no hará está en
`docs/02-MoonJules-Inception.md` §4.

## Estado

**v0.4.0 — `watch` desatendido, triable y con freno.** Funcionan `doctor`, `sources`, `status`
y `watch`, con detector calibrado, notificaciones nativas, logging con
redacción de credenciales, carga desde `.env`, lock de instancia única,
triaje de hallazgos, historial local e interruptor de autonomía. 136
tests, incluido un barrido de secretos sobre todo el árbol.

`moon-jules doctor` mide la latencia real de tu API y proyecta el coste
de un ciclo, que es el dato que dice si un ciclo lento es culpa del
servidor o del cliente.

`watch` ya se puede dejar corriendo en una pestaña y olvidarse: avisa por
notificación del sistema, deja rastro en disco y no se pisa consigo mismo.

Pendiente: `assign-next`, `calibrate` e integración con GitHub Issues.
Ver `docs/BACKLOG.md`.

## Documentación

| Documento | Qué contiene |
|---|---|
| `docs/01-MoonJules-Problem-Brief.md` | el problema, medido |
| `docs/02-MoonJules-Inception.md` | alcance y la NO list |
| `docs/adr/` | las cinco decisiones y sus porqués |
| `docs/spikes/` | de dónde salen los números |
| `AGENTS.md` | contrato de trabajo para agentes en este repo |
