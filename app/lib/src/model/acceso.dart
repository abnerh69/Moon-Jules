/// Política de acceso a la app.
///
/// Firebase Auth mantiene la sesión indefinidamente: guarda un token de
/// refresco y lo renueva solo. Lo que hay aquí es una **capa propia
/// encima**, no un cambio en ese comportamiento: pasados unos días sin
/// entrar, la app cierra la sesión de verdad y vuelve a pedir
/// credenciales.
///
/// La ventana es deslizante. Entrar a los tres días empuja el
/// vencimiento otros siete desde ese momento, así que quien usa la app
/// con regularidad no vuelve a teclear nada.
///
/// Dart puro: la decisión de dejar entrar o no es exactamente el tipo de
/// cosa que conviene poder probar sin emulador.
library;

/// Cuánto dura el acceso sin volver a validarse.
const Duration kVentanaAcceso = Duration(days: 7);

enum EstadoAcceso {
  /// Nunca se han guardado credenciales en este dispositivo.
  sinCredenciales,

  /// Se entró hace poco: se pasa directo.
  vigente,

  /// Hay credenciales pero la ventana venció: hay que validarse.
  caducada,
}

class PoliticaAcceso {
  const PoliticaAcceso({this.ventana = kVentanaAcceso});

  final Duration ventana;

  /// Decide qué toca al abrir la app.
  EstadoAcceso evaluar({
    required bool hayCredenciales,
    required DateTime ahora,
    DateTime? ultimoAcceso,
  }) {
    if (!hayCredenciales) return EstadoAcceso.sinCredenciales;

    // Credenciales guardadas pero sin constancia de haber entrado: se
    // trata como vencida. No saber cuándo fue la última vez no es razón
    // para dejar pasar.
    if (ultimoAcceso == null) return EstadoAcceso.caducada;

    final transcurrido = ahora.difference(ultimoAcceso);

    // Marca en el futuro: o el reloj se movió hacia atrás, o alguien lo
    // atrasó a propósito. Sin este caso, retrasar el reloj del
    // dispositivo extendería la ventana indefinidamente.
    if (transcurrido.isNegative) return EstadoAcceso.caducada;

    return transcurrido >= ventana
        ? EstadoAcceso.caducada
        : EstadoAcceso.vigente;
  }

  /// Cuándo vencerá si no se vuelve a entrar.
  DateTime vencimiento(DateTime ultimoAcceso) => ultimoAcceso.add(ventana);

  /// Cuánto queda. `null` si ya venció.
  Duration? restante(DateTime ultimoAcceso, DateTime ahora) {
    final queda = vencimiento(ultimoAcceso).difference(ahora);
    return queda.isNegative ? null : queda;
  }
}

/// Credenciales guardadas en el dispositivo.
///
/// Viven en el almacén seguro del sistema, nunca en el binario ni en el
/// repositorio. Con `--dart-define` acababan compiladas dentro del APK y
/// eran recuperables por cualquiera que lo tuviera.
class Credenciales {
  const Credenciales({required this.correo, required this.clave});

  final String correo;
  final String clave;

  bool get completas => correo.trim().isNotEmpty && clave.isNotEmpty;

  /// Nunca se imprimen: un `toString` descuidado acaba en un log.
  @override
  String toString() => 'Credenciales($correo, «oculta»)';
}
