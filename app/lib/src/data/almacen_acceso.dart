/// Guarda las credenciales y la marca del último acceso.
///
/// Usa el almacén seguro del sistema —Keystore en Android, Keychain en
/// macOS— y no `shared_preferences`, que es texto plano: cualquiera con
/// acceso al dispositivo podría **atrasar la marca de tiempo** y dejar
/// la ventana abierta indefinidamente.
library;

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../model/acceso.dart';

class AlmacenAcceso {
  AlmacenAcceso({FlutterSecureStorage? almacen})
      : _s = almacen ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  static const _correo = 'mj_correo';
  static const _clave = 'mj_clave';
  static const _ultimo = 'mj_ultimo_acceso';

  final FlutterSecureStorage _s;

  Future<Credenciales?> credenciales() async {
    final correo = await _s.read(key: _correo);
    final clave = await _s.read(key: _clave);
    if (correo == null || clave == null) return null;
    final c = Credenciales(correo: correo, clave: clave);
    return c.completas ? c : null;
  }

  Future<void> guardar(Credenciales c) async {
    await _s.write(key: _correo, value: c.correo.trim());
    await _s.write(key: _clave, value: c.clave);
  }

  /// Olvida todo. Se llama al salir a propósito, no al caducar: caducar
  /// solo obliga a validarse otra vez, no a volver a teclear el correo.
  Future<void> olvidar() async {
    await _s.delete(key: _correo);
    await _s.delete(key: _clave);
    await _s.delete(key: _ultimo);
  }

  Future<DateTime?> ultimoAcceso() async {
    final crudo = await _s.read(key: _ultimo);
    if (crudo == null) return null;
    return DateTime.tryParse(crudo)?.toUtc();
  }

  Future<void> marcarAcceso(DateTime cuando) =>
      _s.write(key: _ultimo, value: cuando.toUtc().toIso8601String());
}
