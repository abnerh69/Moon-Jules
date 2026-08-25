# Moon-Jules App

Panel de Android para ver el enjambre desde el móvil. Una pantalla, dos
ventanas de detalle. Uso personal, sin publicar.

Consume lo que Moon-Jules publica en Firebase RTDB. El contrato es
`../docs/SNAPSHOT.md` (esquema 3) y **no se negocia desde aquí**: si un
campo hace falta, se añade allí y se sube la versión del esquema.

## La frontera que importa

`lib/src/model/` es **Dart puro**, sin una sola importación de Flutter.
Ahí vive todo lo que puede equivocarse: parsear el snapshot, decidir si
el latido caducó, construir una orden con su caducidad. Se prueba sin
emulador y sin dispositivo:

```bash
cd app && flutter test
```

`lib/src/data/` es el pegamento con los SDK de Firebase, y es la única
capa que toca la red. Cuanto más fina sea, menos código queda sin
verificar.

## Tres reglas del contrato

**Una clave ausente no es un cero.** Firebase omite los valores nulos,
así que `silence_s` llega ausente cuando el reloj está congelado. Un
`?? 0` mostraría "muda hace 0 s" sobre trabajo ya entregado, que es
justo lo contrario de la verdad.

**Un esquema desconocido se rechaza**, no se interpreta a medias. Un
panel que muestra datos mal leídos es peor que uno que dice "no entiendo
esta versión".

**Designar es proponer.** La instancia elegida confirma escribiendo su
reclamación; hasta entonces la pantalla muestra deseado y real por
separado. Una designación sin recoger significa máquina dormida.

## Lo que la app no hace

No crea sesiones ni asigna tareas: eso lo resuelve una GitHub Action.
No archiva ni borra nada. Escribe exactamente dos nodos —`control/desired`
y `command`— y las reglas de seguridad lo imponen, no la buena conducta
de este código.

Y hay una alerta que **no puede venir de Moon-Jules**: la de instancia
caída. La máquina que se cayó es la que tendría que avisar. Esa la
detecta esta app comparando `heartbeat_ms` con `stale_after_s`.

## Puesta en marcha

```bash
flutter create --org org.ashware --project-name moonjules \
  --platforms android .
flutter pub get
flutterfire configure     # genera firebase_options.dart y google-services.json
flutter test              # 36 en verde
```

`firebase_options.dart` y `google-services.json` están en `.gitignore`:
llevan identificadores del proyecto de Firebase y no van al repositorio.

**`flutter create` sobrescribe `lib/main.dart` y crea
`test/widget_test.dart`.** Si vuelves a ejecutarlo, restaura el
`main.dart` de este repositorio y borra el `widget_test.dart` generado:
prueba un contador que no existe. En el canal `master`, además, la
plantilla usa sintaxis experimental (*dot-shorthands*) que no compila
con una restricción de SDK estable.

Falta la pantalla y el registro de FCM. Lo que hay hoy es la capa de
datos, verificada.
