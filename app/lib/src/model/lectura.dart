/// Resultado de leer el snapshot de una instancia.
///
/// Vive en el modelo y no junto a Firebase porque **un fallo de lectura
/// es información que la pantalla debe mostrar**, no una excepción que
/// interrumpa: si una de las tres máquinas publica algo que esta
/// versión no entiende, las otras dos deben seguir viéndose.
library;

import 'snapshot.dart';

class LecturaInstancia {
  const LecturaInstancia.ok(this.id, Snapshot this.snapshot) : error = null;

  const LecturaInstancia.fallida(this.id, String this.error) : snapshot = null;

  final String id;
  final Snapshot? snapshot;
  final String? error;

  bool get correcta => snapshot != null;
}
