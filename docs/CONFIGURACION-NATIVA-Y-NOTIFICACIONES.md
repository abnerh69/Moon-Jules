# Configuración nativa de Android y diagnóstico de notificaciones

```meta
Versión:  1.0
Fecha:    2026-08-26
Cubre:    entregas 27 a 31
```

Este documento existe porque los scripts `apply-NN.sh` **se autoborran
al ejecutarse**. Los ficheros que modifican viven en git, así que el
estado es recuperable; el motivo de cada cambio, no. Y ninguno de estos
ajustes es evidente al leer el fichero después.

Todo lo que sigue vive en `app/android/`, que genera `flutter create` y
por eso nunca viaja en un zip de entrega.

## Qué está configurado y por qué

| Dónde | Qué | Sin ello |
|---|---|---|
| `AndroidManifest.xml` | `android:label="Moon Jules"` | Se lee `moonjules` bajo el icono: el identificador del paquete, no un nombre |
| `AndroidManifest.xml` | `POST_NOTIFICATIONS` | En Android 13+ el sistema nunca pide permiso y `getToken()` no devuelve token |
| `AndroidManifest.xml` | `USE_BIOMETRIC` | La huella no está disponible para desbloquear la app |
| `AndroidManifest.xml` | `default_notification_channel_id` | **Android descarta en silencio** lo que llega con la app cerrada |
| `AndroidManifest.xml` | `default_notification_icon` | El icono a color se pinta como un cuadrado blanco |
| `MainActivity.kt` | `FlutterFragmentActivity` | `local_auth` falla **en ejecución, no al compilar** |
| `build.gradle.kts` | *core library desugaring* + Java 11 | Gradle aborta: `flutter_local_notifications` usa `java.time` |
| `app/android/app/` | `google-services.json` | FCM no registra el dispositivo con Google Play Services |

## El canal de notificaciones

Es el ajuste que más costó encontrar, y merece explicación aparte.

Desde Android 8 **toda notificación necesita un canal**. Con la app en
segundo plano o cerrada, quien la muestra es el SDK nativo de Firebase,
no el código Dart, y usa el canal declarado en el manifiesto. Si ese
canal **no existe en el sistema**, muchos dispositivos —MIUI entre
ellos— descartan el mensaje sin dejar rastro.

El síntoma es especialmente engañoso: FCM responde con éxito, el log de
Moon-Jules dice «notificaciones enviadas», la consola de Firebase no
marca error, y en el teléfono no aparece nada. Todos los indicadores en
verde y el usuario sin avisos.

Hacen falta **las dos mitades**, y con una sola no basta:

1. Declarar el identificador en el manifiesto, para que Firebase sepa
   cuál usar (`apply-29.sh`).
2. Crear el canal al arrancar la app, para que exista de verdad
   (`app/lib/src/data/canal_avisos.dart`).

El identificador es `moonjules_alertas` y **debe coincidir** en ambos
sitios. Si cambia en uno y no en el otro, vuelve el fallo silencioso.

Un detalle operativo que cuesta una hora si no se sabe: **Android no
modifica un canal ya creado**. Cambiar su importancia o su descripción
no tiene efecto sobre una instalación existente. Para que un cambio de
canal surta efecto hay que desinstalar la app, no solo reinstalarla.

## El icono de la barra

Android **ignora el color** del icono pequeño: lo pinta como una silueta
blanca a partir del canal alfa. Un icono a color se ve como un cuadrado
relleno, que es lo que ocurre cuando no se declara uno propio y el
sistema recurre al de la aplicación.

`tools/generar_iconos.py` produce ambos: el del lanzador a color y la
silueta monocroma de la barra, en las cinco densidades.

## Diagnóstico: «no llegan las notificaciones»

En orden, del extremo más barato de comprobar al más caro. Cada paso
descarta el anterior.

**0. ¿Corre el servicio la versión que crees?** `moon-jules doctor` avisa
si no. El servicio lee el código y el config **una sola vez, al
arrancar**: aplicar una entrega sin reiniciar deja una versión vieja en
marcha persiguiendo fallos ya arreglados. `moon-jules service install`
reinicia.

**1. ¿Se envió?** En `~/.local/state/moon-jules/logs/moon-jules.log`
busca `push entregado a N de M dispositivo(s)`. Si `M` es cero, o si
aparece `push omitido: ningun dispositivo registrado`, el backend no
tiene destinatarios. Y si **no aparece ninguna de las dos líneas** pero
sí llegan avisos al escritorio, el envío por FCM ni siquiera se
intentó.

**2. ¿Hay token?** En RTDB, `moonjules/devices/` debe existir con al
menos una entrada. Si el nodo no existe, la app no llegó a registrarse
—y la pantalla debería estar mostrando el motivo real arriba del todo—.

**3. ¿Lo permiten las reglas?** El nodo `devices` tiene que estar en las
reglas publicadas (`docs/RTDB.md`). Una regla ausente rechaza la
escritura y el registro falla aunque el token sea correcto. **Esto pasó**
porque las reglas se publicaron antes de que `devices` existiera en el
contrato.

**4. ¿Concedió el permiso el sistema?** Ajustes → Aplicaciones → Moon
Jules → Notificaciones. Si dice que no ha recibido ninguna notificación,
el mensaje ni siquiera llegó al dispositivo. Ojo: en MIUI las
notificaciones **no aparecen** junto al resto de permisos.

**5. ¿Existe el canal?** Es el sospechoso cuando todo lo demás está en
verde. Desinstalar y reinstalar es la única forma de recrearlo.

**6. ¿Está el teléfono ahorrando batería?** MIUI puede retrasar o
descartar FCM con la app cerrada. Ajustes → Batería → Moon Jules → Sin
restricciones.

Y una causa que no es un fallo: la **supresión de repetidos**. Moon-Jules
no vuelve a avisar del mismo par (sesión, veredicto) dentro de la ventana
configurada, una hora por defecto. Para forzar avisos durante una prueba:

```bash
sqlite3 ~/.local/state/moon-jules/state.db "DELETE FROM notifications"
```

## Compilar

```bash
cd app
flutter clean
flutter build apk --release
flutter install --release
```

Sin `--dart-define`: desde la entrega 28 las credenciales se teclean una
vez y viven en el Keystore.

**Desinstala antes de instalar** si cambió algo del canal, y también al
pasar de `debug` a `release`: las firmas son distintas y Android rechaza
la instalación.

Sin configurar firma propia, Gradle usa la clave de depuración. El APK se
instala pero no es un artefacto firmado para distribuir — irrelevante
mientras la app no se publique, pero conviene saberlo.

## Avisos que persisten y no son un problema

`source value 8 is obsolete` sigue apareciendo tras subir la aplicación a
Java 11. **Viene de la compilación de los plugins**, que traen su propia
configuración, no del código de esta app. Es ruido de terceros.

`Some input files use or override a deprecated API`, lo mismo.

## Deuda conocida

`flutter_local_notifications` está en el proyecto **solo para crear un
canal**. A cambio arrastra `timezone`, interfaces de plataforma para
Linux y Windows, y la exigencia de desugaring de la entrega 31.

Esas quince líneas se escriben en Kotlin dentro de `MainActivity`, y con
ello desaparecen la dependencia y el ajuste de Gradle. No se hizo en su
momento porque el objetivo era que el push funcionara; queda anotado
para cuando la dependencia estorbe.
