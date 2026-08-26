/// Orquesta el acceso: credenciales guardadas, ventana y biometría.
///
/// Al caducar **se cierra la sesión de Firebase de verdad**, no solo se
/// tapa la pantalla. Volver a entrar exige red y una validación real, y
/// eso es lo que se pidió.
library;

import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:local_auth/local_auth.dart';

import 'data/almacen_acceso.dart';
import 'model/acceso.dart';

/// Lo que la pantalla necesita saber.
class SesionApp {
  const SesionApp({required this.estado, this.correo, this.error});

  final EstadoAcceso estado;

  /// Correo guardado, para no obligar a teclearlo al desbloquear.
  final String? correo;

  final String? error;

  bool get dentro => estado == EstadoAcceso.vigente && error == null;
}

class AccesoNotifier extends AsyncNotifier<SesionApp> {
  AccesoNotifier({
    AlmacenAcceso? almacen,
    LocalAuthentication? biometria,
    PoliticaAcceso politica = const PoliticaAcceso(),
  })  : _almacen = almacen ?? AlmacenAcceso(),
        _bio = biometria ?? LocalAuthentication(),
        _politica = politica;

  final AlmacenAcceso _almacen;
  final LocalAuthentication _bio;
  final PoliticaAcceso _politica;

  @override
  Future<SesionApp> build() => _evaluar();

  Future<SesionApp> _evaluar() async {
    final cred = await _almacen.credenciales();
    final ultimo = await _almacen.ultimoAcceso();
    final estado = _politica.evaluar(
      hayCredenciales: cred != null,
      ultimoAcceso: ultimo,
      ahora: DateTime.now().toUtc(),
    );

    if (estado == EstadoAcceso.vigente) {
      // La ventana desliza: entrar la renueva.
      await _almacen.marcarAcceso(DateTime.now().toUtc());
      if (FirebaseAuth.instance.currentUser == null && cred != null) {
        return _entrar(cred);
      }
      return SesionApp(estado: estado, correo: cred?.correo);
    }

    // Caducada o sin credenciales: fuera de verdad.
    await FirebaseAuth.instance.signOut();
    return SesionApp(estado: estado, correo: cred?.correo);
  }

  /// Entra con las credenciales dadas y, si sale bien, las guarda.
  Future<void> entrarCon(Credenciales cred) async {
    state = const AsyncValue.loading();
    state = AsyncValue.data(await _entrar(cred, guardar: true));
  }

  Future<SesionApp> _entrar(Credenciales cred, {bool guardar = false}) async {
    try {
      await FirebaseAuth.instance.signInWithEmailAndPassword(
        email: cred.correo.trim(),
        password: cred.clave,
      );
    } on FirebaseAuthException catch (e) {
      return SesionApp(
        estado: EstadoAcceso.caducada,
        correo: cred.correo,
        error: _traducir(e.code),
      );
    }
    if (guardar) await _almacen.guardar(cred);
    await _almacen.marcarAcceso(DateTime.now().toUtc());
    return SesionApp(estado: EstadoAcceso.vigente, correo: cred.correo);
  }

  /// Desbloquea con huella o cara, usando las credenciales guardadas.
  ///
  /// La biometría no sustituye a la contraseña: **la desbloquea**. Como
  /// al caducar se cierra la sesión de Firebase, sigue haciendo falta
  /// autenticarse contra el servidor, y para eso hay que recuperar la
  /// clave del almacén.
  Future<void> desbloquearConBiometria() async {
    final cred = await _almacen.credenciales();
    if (cred == null) {
      state = const AsyncValue.data(
        SesionApp(estado: EstadoAcceso.sinCredenciales),
      );
      return;
    }
    bool ok;
    try {
      ok = await _bio.authenticate(
        localizedReason: 'Desbloquear Moon Jules',
        options: const AuthenticationOptions(stickyAuth: true),
      );
    } on Object {
      // Sin sensor, sin huellas registradas o el usuario canceló. No es
      // un fallo de la app: queda la contraseña.
      ok = false;
    }
    if (!ok) {
      state = AsyncValue.data(SesionApp(
        estado: EstadoAcceso.caducada,
        correo: cred.correo,
        error: 'No se pudo verificar. Usa la contraseña.',
      ));
      return;
    }
    state = const AsyncValue.loading();
    state = AsyncValue.data(await _entrar(cred));
  }

  Future<bool> hayBiometria() async {
    try {
      return await _bio.canCheckBiometrics && await _bio.isDeviceSupported();
    } on Object {
      return false;
    }
  }

  /// Cierra sesión y olvida las credenciales.
  Future<void> salir() async {
    await FirebaseAuth.instance.signOut();
    await _almacen.olvidar();
    state = const AsyncValue.data(
      SesionApp(estado: EstadoAcceso.sinCredenciales),
    );
  }

  static String _traducir(String codigo) => switch (codigo) {
        'invalid-credential' ||
        'wrong-password' ||
        'user-not-found' =>
          'Correo o contraseña incorrectos.',
        'network-request-failed' =>
          'Sin conexión: entrar exige red porque la sesión se cerró.',
        'too-many-requests' => 'Demasiados intentos. Espera un momento.',
        _ => 'No se pudo entrar ($codigo).',
      };
}

final accesoProvider =
    AsyncNotifierProvider<AccesoNotifier, SesionApp>(AccesoNotifier.new);
