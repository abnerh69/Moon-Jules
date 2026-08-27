# Firebase RTDB: montaje y reglas

Moon-Jules publica su estado en Realtime Database para que la app de
Android lo lea. Este documento cubre las credenciales y las reglas.

Contrato de datos: `docs/SNAPSHOT.md`.

## Cómo se conecta

Por REST puro, sin SDK. RTDB expone cada nodo del árbol como una URL
terminada en `.json`:

```
PUT  {url}/{root}/instances/{instancia}/snapshot.json   ← publicar
GET  {url}/{root}/control.json                          ← leer el relevo
```

Cuatro rutas, dos verbos. Sin dependencias de Firebase salvo
`google-auth` para firmar la credencial.

## Dos credenciales, y no dan lo mismo

### Cuenta de servicio *(recomendada)*

Firma un JWT, lo canjea por un token OAuth2 de una hora y lo renueva
sola. Va en la cabecera `Authorization`, no en la URL, así que no acaba
en logs de proxies ni en historiales.

Lo importante es otra cosa: usa `auth_variable_override`, de modo que
**la petición se evalúa bajo una identidad acotada** (`moonjules-writer`
por defecto). Las reglas de seguridad se aplican también a los Mac.

### Database secret *(legado)*

Una cadena fija que va en la query. No caduca, no se rota y **salta
todas las reglas**. Con él, la promesa de que "el teléfono solo escribe
`control/desired`" la sostiene el buen comportamiento de este código, no
la base de datos. Google lo tiene obsoleto desde hace años.

Sirve para una prueba rápida. No para dejarlo puesto.

## Montaje

**1. Crear el proyecto** en la consola de Firebase y habilitar Realtime
Database. Anota la URL: `https://TU-PROYECTO-default-rtdb.firebaseio.com`.

**2. Descargar la clave de servicio** en *Configuración del proyecto →
Cuentas de servicio → Generar nueva clave privada*. Guárdala **fuera del
repositorio**:

```bash
mkdir -p ~/.config/moon-jules
mv ~/Downloads/tu-proyecto-*.json ~/.config/moon-jules/firebase-sa.json
chmod 600 ~/.config/moon-jules/firebase-sa.json
```

**3. Configurar** en `~/.config/moon-jules/config.toml`:

```toml
[publish]
enabled     = true
target      = "rtdb"
instance_id = "la-dorada"

[publish.rtdb]
url             = "https://TU-PROYECTO-default-rtdb.firebaseio.com"
root            = "moonjules"
service_account = "~/.config/moon-jules/firebase-sa.json"
uid             = "moonjules-writer"

[relay]
enabled           = true
active_by_default = false
```

**4. Publicar las reglas** (abajo), sustituyendo `UID_ARQUITECTO` por el
UID de tu usuario en Firebase Authentication — el que usará la app.

**5. Comprobar**:

```bash
moon-jules publish       # debe escribir sin error
moon-jules relay         # debe leer el control
```

## Reglas de seguridad

```json
{
  "rules": {
    "moonjules": {
      ".read": "auth != null && (auth.uid === 'moonjules-writer' || auth.uid === 'UID_ARQUITECTO')",
      ".write": false,

      "instances": {
        "$instancia": {
          ".write": "auth.uid === 'moonjules-writer'"
        }
      },

      "control": {
        "desired": {
          ".write": "auth.uid === 'UID_ARQUITECTO' && (newData.val() === null || root.child('moonjules/instances').child(newData.val()).child('snapshot/instance/heartbeat_ms').val() > now - 1200000)",
          ".validate": "newData.isString() || newData.val() === null"
        },
        "claimed_by": {
          ".write": "auth.uid === 'moonjules-writer'"
        },
        "claimed_at": {
          ".write": "auth.uid === 'moonjules-writer'"
        }
      },

      "devices": {
        "$token": {
          ".write": "auth.uid === 'UID_ARQUITECTO'",
          ".validate": "newData.isBoolean() || newData.val() === null"
        }
      },

      "archived": {
        "$repo": {
          ".write": "auth.uid === 'UID_ARQUITECTO'",
          ".validate": "newData.isBoolean() || newData.val() === null"
        }
      },

      "command": {
        ".write": "auth.uid === 'UID_ARQUITECTO'",
        ".validate": "newData.val() === null || newData.hasChildren(['id', 'verb', 'issued_at', 'expires_at'])"
      }
    }
  }
}
```

### La regla que impide designar una máquina muerta

Esa condición larga en `control/desired` es la pieza importante:

```
root.child('moonjules/instances').child(newData.val())
    .child('snapshot/instance/heartbeat_ms').val() > now - 1200000
```

Antes de aceptar la designación, Firebase mira el latido de esa
instancia y rechaza la escritura si lleva más de veinte minutos callada.
Que la app no ofrezca designar a una máquina caída está bien; que **no
pueda hacerlo** aunque tenga un fallo, o aunque alguien toque los datos a
mano, es mejor. Por eso el snapshot publica `heartbeat_ms` además de
`published_at`: las reglas comparan números contra `now`, no cadenas
ISO.

Ajusta los 1.200.000 ms si cambias `poll_interval_s`: conviene que sea
el mismo `stale_after_s` que viaja en el snapshot.

Esto impone el contrato en la base de datos, no en el código:

- Las instancias escriben su snapshot y su reclamación. **No pueden
  escribir `desired`**: una máquina no puede autodesignarse.
- El teléfono escribe **solo** `desired`. No puede falsificar una
  reclamación, que es lo que haría que la app mostrase como vigilante
  una máquina dormida.
- Todo lo demás está cerrado.

Dos apuntes sobre cómo funcionan las reglas de RTDB, porque son
contraintuitivas. Se evalúan de la raíz hacia abajo y **el primer
`true` concede**: un `.write: false` en un nodo padre no bloquea un
`.write: true` en un hijo, así que el de arriba es documentación, no
candado. Y una regla que concede acceso a un nodo lo concede **a todo su
subárbol**: por eso `instances/$instancia` da permiso sobre el snapshot
entero sin enumerar campos.

## Notificaciones push

La misma cuenta de servicio envía por FCM: mismo proyecto, ámbito
`firebase.messaging`, sin Cloud Functions ni plan de pago. Se activa con
`fcm = true` en `[notify]`.

La app escribe su token en `{root}/devices/{token}` con valor `true`.

## Repositorios archivados

`{root}/archived/{owner__repo}` guarda qué repositorios no quiere ver el
arquitecto en la lista. **Lo escribe y lo lee solo la app**: archivar es
un filtro de vista y Moon-Jules ni se entera. Un repositorio archivado
que falle sigue alertando y reactivándose igual.

La clave usa `__` en lugar de `/` porque las claves de RTDB no admiten
barras, y se deriva del repositorio y no del `id` del API para que se
lea en la consola.
Moon-Jules lo lee y retira solo los que FCM declara muertos.

## Coste

Un snapshot ronda los 3 KB, unos 15 KB en el peor caso. A un ciclo cada
cinco minutos son 288 escrituras diarias: ~4 MB al día de subida. El
plan Spark gratuito da 1 GB de almacenamiento y 10 GB de descarga al
mes, así que sobra con holgura para una instancia y un teléfono.

## Si algo falla

**HTTP 401 con cuenta de servicio.** El token no se pudo renovar.
Comprueba que la clave siga activa en la consola y que el proyecto tenga
habilitada la API de Realtime Database.

**HTTP 403.** Las reglas no permiten escribir bajo esa identidad. El
mensaje de error dice con qué `uid` se intentó; compáralo con `uid` del
config y con las reglas publicadas.

**Nada llega y no hay error.** Comprueba que `watch` esté corriendo:
`publish` solo escribe una foto suelta. Sin `watch`, el latido se congela
y la app alertará —correctamente— de que nadie está mirando.
