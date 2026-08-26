/// Acceso a Firebase. **La única capa de la app que toca la red.**
///
/// Todo lo que puede equivocarse de verdad —parsear el snapshot,
/// decidir si el latido caducó, construir una orden— vive en
/// `src/model/` como Dart puro y está cubierto por tests que corren sin
/// emulador. Aquí solo queda el pegamento con los SDK, que no se puede
/// probar sin dispositivo. Esa frontera es deliberada: cuanto más fina
/// sea esta capa, menos código queda sin verificar.
library;

import 'package:firebase_database/firebase_database.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

import '../model/comando.dart';
import '../model/lectura.dart';
import '../model/snapshot.dart';

/// Rutas del árbol. Deben coincidir con `publish.rtdb.root` del config
/// de Moon-Jules y con las reglas de seguridad de `docs/RTDB.md`.
class Rutas {
  const Rutas({this.raiz = 'moonjules'});

  final String raiz;

  String instancias() => '$raiz/instances';
  String snapshot(String instancia) => '$raiz/instances/$instancia/snapshot';
  String acuse(String instancia) => '$raiz/instances/$instancia/command_result';
  String control() => '$raiz/control';
  String designada() => '$raiz/control/desired';
  String comando() => '$raiz/command';
  String dispositivo(String token) => '$raiz/devices/$token';
}

/// Resultado de registrar el teléfono para recibir avisos.
///
/// Se devuelve el motivo del fallo en vez de un `null` mudo: la primera
/// versión decía «comprueba el permiso de notificaciones» pasara lo que
/// pasara, y eso mandó a revisar el sitio equivocado cuando el problema
/// estaba en las reglas de RTDB.
class RegistroAvisos {
  const RegistroAvisos.ok(String this.token) : error = null;

  const RegistroAvisos.fallido(String this.error) : token = null;

  final String? token;
  final String? error;

  bool get activo => token != null;
}


class RepositorioMoonJules {
  RepositorioMoonJules({
    FirebaseDatabase? db,
    FirebaseMessaging? messaging,
    this.rutas = const Rutas(),
  })  : _db = db ?? FirebaseDatabase.instance,
        _messaging = messaging ?? FirebaseMessaging.instance;

  final FirebaseDatabase _db;
  final FirebaseMessaging _messaging;
  final Rutas rutas;

  /// Todas las instancias, en tiempo real.
  ///
  /// Se escucha el nodo padre y no cada máquina por separado: así una
  /// instancia nueva aparece sola, sin tener que saber de antemano
  /// cuántos portátiles hay.
  Stream<List<LecturaInstancia>> instancias() {
    return _db.ref(rutas.instancias()).onValue.map((evento) {
      final crudo = evento.snapshot.value;
      if (crudo is! Map) return const <LecturaInstancia>[];
      final salida = <LecturaInstancia>[];
      crudo.forEach((clave, valor) {
        final id = clave.toString();
        final nodo = valor is Map ? valor['snapshot'] : null;
        if (nodo == null) return;
        try {
          salida.add(
            LecturaInstancia.ok(id, Snapshot.desdeJson(_mapa(nodo))),
          );
        } on EsquemaIncompatible catch (e) {
          salida.add(LecturaInstancia.fallida(id, e.toString()));
        } catch (e) {
          salida.add(LecturaInstancia.fallida(id, 'no se pudo leer: $e'));
        }
      });
      salida.sort((a, b) => a.id.compareTo(b.id));
      return salida;
    });
  }

  /// Si el socket con Firebase está vivo.
  ///
  /// `.info/connected` es estado **local del SDK**: no viaja por la red,
  /// así que responde al instante incluso sin conexión, que es
  /// exactamente cuando hace falta saberlo. Cuelga de la raíz de la
  /// base, no de `root`.
  Stream<bool> conectado() => _db.ref('.info/connected').onValue.map(
        (e) => e.snapshot.value == true,
      );

  /// Desfase entre el reloj del teléfono y el del servidor.
  ///
  /// La caducidad del latido se calcula contra la hora local, así que un
  /// móvil desajustado daría por caídas máquinas sanas, o al revés.
  Stream<Duration> desfaseServidor() =>
      _db.ref('.info/serverTimeOffset').onValue.map((e) {
        final ms = e.snapshot.value;
        return Duration(milliseconds: ms is num ? ms.toInt() : 0);
      });

  Stream<Control> control() => _db.ref(rutas.control()).onValue.map(
        (e) => Control.desdeJson(_mapa(e.snapshot.value)),
      );

  /// Designa qué instancia debe vigilar.
  ///
  /// Es una **propuesta, no una orden cumplida**: la instancia elegida
  /// confirma escribiendo su reclamación, y hasta entonces la pantalla
  /// debe mostrar deseado y real por separado. Las reglas rechazan
  /// designar una máquina cuyo latido esté caducado, así que este método
  /// puede fallar con permiso denegado y eso significa "esa está caída".
  Future<void> designar(String? instancia) =>
      _db.ref(rutas.designada()).set(instancia);

  /// Envía una orden y devuelve el acuse cuando llega.
  ///
  /// La espera compara identificadores: la orden sigue pendiente
  /// mientras el acuse no lleve el suyo. No hay campo de estado que
  /// mantener sincronizado entre dos procesos.
  Future<Resultado?> enviar(
    Comando comando,
    String instancia, {
    Duration espera = const Duration(minutes: 2),
  }) async {
    await _db.ref(rutas.comando()).set(comando.aJson());
    try {
      return await _db
          .ref(rutas.acuse(instancia))
          .onValue
          .map((e) => Resultado.desdeJson(_mapa(e.snapshot.value)))
          .firstWhere((r) => !Resultado.pendiente(comando, r))
          .timeout(espera);
    } catch (_) {
      // Ni error ni éxito: nadie ha recogido todavía. Puede ser que la
      // instancia esté dormida, y la pantalla debe poder decirlo.
      return null;
    }
  }

  /// Registra este teléfono para recibir avisos push.
  ///
  /// Se llama en cada arranque: el token de FCM rota, y uno viejo deja
  /// de recibir sin avisar. Moon-Jules retira solo los que FCM declara
  /// muertos.
  Future<RegistroAvisos> registrarDispositivo() async {
    final permiso = await _messaging.requestPermission();
    final concedido =
        permiso.authorizationStatus == AuthorizationStatus.authorized ||
            permiso.authorizationStatus == AuthorizationStatus.provisional;
    if (!concedido) {
      return RegistroAvisos.fallido(
        'El sistema no concedió permiso para notificar '
        '(${permiso.authorizationStatus.name}).',
      );
    }
    String? token;
    try {
      token = await _messaging.getToken();
    } on Object catch (e) {
      // El motivo real, no una conjetura. Perder esta cadena costó una
      // noche de buscar en el sitio equivocado.
      return RegistroAvisos.fallido('No se pudo obtener el token: $e');
    }
    if (token == null) {
      return RegistroAvisos.fallido(
        'Sin token de FCM. Suele faltar google-services.json o el '
        'registro de la app Android en el proyecto de Firebase.',
      );
    }
    try {
      await _db.ref(rutas.dispositivo(token)).set(true);
    } on Object catch (e) {
      return RegistroAvisos.fallido('No se pudo registrar en RTDB: $e');
    }
    return RegistroAvisos.ok(token);
  }

  /// Los tokens rotan; hay que seguir el cambio o se dejan de recibir.
  Stream<String> tokensRenovados() =>
      _messaging.onTokenRefresh.asyncMap((token) async {
        await _db.ref(rutas.dispositivo(token)).set(true);
        return token;
      });

  static Map<String, Object?> _mapa(Object? valor) {
    if (valor is Map) {
      return valor.map((k, v) => MapEntry(k.toString(), v as Object?));
    }
    return const {};
  }
}
