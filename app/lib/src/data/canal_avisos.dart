/// Canal de notificaciones de Android.
///
/// Desde Android 8 **toda notificación necesita un canal**, y con la app
/// cerrada quien la muestra es el SDK nativo de Firebase, no el código
/// Dart. Si el canal no existe en el sistema, muchos dispositivos
/// —MIUI entre ellos— **descartan el mensaje en silencio**: FCM informa
/// de entrega correcta y en el teléfono no aparece nada.
///
/// Hay que hacer dos cosas, y con una sola no basta: declarar el
/// identificador en el manifiesto, para que Firebase sepa cuál usar, y
/// crear el canal aquí, para que exista de verdad.
library;

import 'package:flutter_local_notifications/flutter_local_notifications.dart';

/// Debe coincidir con `default_notification_channel_id` del manifiesto.
const String kCanalAlertas = 'moonjules_alertas';

const AndroidNotificationChannel canalAlertas = AndroidNotificationChannel(
  kCanalAlertas,
  'Alertas del enjambre',
  description: 'Sesiones atascadas, fallidas o sin respuesta al desatasco.',
  // Alta: una sesión colgada no puede esperar a que se mire el teléfono.
  importance: Importance.high,
);

/// Crea el canal. Idempotente: Android ignora la llamada si ya existe.
Future<void> crearCanalAvisos() async {
  final plugin = FlutterLocalNotificationsPlugin();
  await plugin
      .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>()
      ?.createNotificationChannel(canalAlertas);
}
