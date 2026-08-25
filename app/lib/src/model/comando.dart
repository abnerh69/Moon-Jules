/// Comandos que el teléfono envía a la instancia habilitada.
///
/// Contrato: `docs/SNAPSHOT.md`. Dos reglas gobiernan el formato y las
/// dos existen porque **RTDB no es una cola de mensajes**:
///
/// - Cada orden lleva `id`. La instancia guarda lo que ya ejecutó, así
///   que reenviar el mismo `id` republica el acuse sin repetir la
///   acción. Un `id` nuevo sí vuelve a actuar.
/// - Cada orden lleva `expires_at`. Sin caducidad conocida la instancia
///   la descarta: un "desatasca esta sesión" emitido mientras las tres
///   máquinas dormían no debe ejecutarse seis horas después.
library;

import 'dart:math';

/// Verbos que la instancia acepta. Los que cruzan la NO list de
/// Moon-Jules —crear sesiones, archivar, borrar— no existen aquí porque
/// tampoco existen allí.
enum Verbo {
  nudge('nudge'),
  aprobarPlan('approve_plan'),
  silenciar('ack'),
  desilenciar('unack'),
  pausar('pause'),
  reanudar('resume'),
  refrescar('refresh');

  const Verbo(this.clave);

  final String clave;

  /// Si necesita una sesión concreta sobre la que actuar.
  bool get requiereSesion => const {
        Verbo.nudge,
        Verbo.aprobarPlan,
        Verbo.silenciar,
        Verbo.desilenciar,
      }.contains(this);
}

/// Cuánto vive una orden desde que se emite.
const Duration kVidaComando = Duration(minutes: 10);

class Comando {
  Comando({
    required this.id,
    required this.verbo,
    required this.emitidoEn,
    required this.caducaEn,
    this.args = const {},
  });

  /// Construye una orden con identificador único y caducidad.
  ///
  /// El `id` incluye el instante y un sufijo aleatorio: reintentar la
  /// misma orden reusando su `id` es seguro, y pulsar dos veces genera
  /// dos órdenes distintas, que es lo que el usuario espera.
  factory Comando.nueva(
    Verbo verbo, {
    Map<String, Object?> args = const {},
    DateTime? ahora,
    Duration vida = kVidaComando,
    Random? aleatorio,
  }) {
    final t = (ahora ?? DateTime.now()).toUtc();
    final sufijo = (aleatorio ?? Random())
        .nextInt(1 << 24)
        .toRadixString(16)
        .padLeft(6, '0');
    return Comando(
      id: 'c-${t.millisecondsSinceEpoch}-$sufijo',
      verbo: verbo,
      emitidoEn: t,
      caducaEn: t.add(vida),
      args: args,
    );
  }

  final String id;
  final Verbo verbo;
  final DateTime emitidoEn;
  final DateTime caducaEn;
  final Map<String, Object?> args;

  Map<String, Object?> aJson() => {
        'id': id,
        'verb': verbo.clave,
        'issued_at': _iso(emitidoEn),
        'expires_at': _iso(caducaEn),
        if (args.isNotEmpty) 'args': args,
      };

  static String _iso(DateTime t) =>
      '${t.toUtc().toIso8601String().split('.').first}Z';
}

/// Desenlace de una orden, escrito por la instancia.
enum EstadoComando { pendiente, hecho, fallido, caducado, rechazado }

class Resultado {
  const Resultado({required this.id, required this.estado, this.mensaje,
      this.completadoEn});

  factory Resultado.desdeJson(Map<String, Object?> json) {
    final crudo = json['status'];
    return Resultado(
      id: json['id']?.toString() ?? '',
      estado: switch (crudo) {
        'done' => EstadoComando.hecho,
        'failed' => EstadoComando.fallido,
        'expired' => EstadoComando.caducado,
        'rejected' => EstadoComando.rechazado,
        _ => EstadoComando.pendiente,
      },
      mensaje: json['message']?.toString(),
      completadoEn: json['completed_at']?.toString(),
    );
  }

  final String id;
  final EstadoComando estado;
  final String? mensaje;
  final String? completadoEn;

  /// Una orden está pendiente mientras el acuse no lleve su `id`.
  ///
  /// Se deduce del contraste en vez de mantener un campo de estado
  /// sincronizado entre dos procesos, que se desincronizaría.
  static bool pendiente(Comando enviado, Resultado? acuse) =>
      acuse == null || acuse.id != enviado.id;
}
