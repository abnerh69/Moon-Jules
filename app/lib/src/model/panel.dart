/// Lógica de presentación, en Dart puro.
///
/// Decidir qué se ve primero, cómo se agrupa y qué significa cada
/// estado son decisiones que pueden equivocarse, así que viven aquí y no
/// dentro de un widget: se prueban sin emulador, en un segundo.
///
/// Los widgets se limitan a dibujar lo que este fichero decide.
library;

import 'lectura.dart';
import 'snapshot.dart';

/// Qué le pasa a una instancia, resumido para la pantalla.
enum SaludInstancia {
  /// Publica y está vigilando de verdad.
  vigilando,

  /// Publica, pero otra es la habilitada. Disponible para el relevo.
  enReserva,

  /// Lleva más de `stale_after_s` sin publicar. Probablemente dormida.
  callada,

  /// Publicó algo que esta versión de la app no entiende.
  ilegible,
}

/// Una instancia tal como se pinta en la lista de arriba.
class TarjetaInstancia {
  const TarjetaInstancia({
    required this.id,
    required this.salud,
    this.snapshot,
    this.silencio,
    this.error,
  });

  final String id;
  final SaludInstancia salud;
  final Snapshot? snapshot;

  /// Cuánto lleva sin publicar. `null` si nunca publicó.
  final Duration? silencio;

  final String? error;

  bool get preocupa =>
      salud == SaludInstancia.callada || salud == SaludInstancia.ilegible;
}

/// Estado completo de la pantalla principal.
class VistaPanel {
  const VistaPanel({
    required this.instancias,
    required this.control,
    this.deQuienLeemos,
    this.conectado = true,
  });

  final List<TarjetaInstancia> instancias;
  final Control control;

  /// Si el teléfono tiene conexión con Firebase.
  ///
  /// Es la distinción que evita la peor confusión posible en esta app.
  /// El SDK sirve de **caché sin conexión**: sigue entregando el último
  /// snapshot conocido, con latidos de hace horas. Sin este dato, la
  /// pantalla acusaría a las tres máquinas de haber muerto cuando lo
  /// que pasa es que el móvil está en un ascensor — el mismo engaño que
  /// motiva el proyecto entero, una capa más arriba.
  final bool conectado;

  /// Instancia cuyo snapshot se usa para el detalle del enjambre.
  ///
  /// Todas ven el mismo Jules, así que da igual cuál se lea mientras
  /// esté fresca. Se prefiere la que vigila; si esa calló, cualquier
  /// otra viva sirve, y eso es mejor que quedarse sin datos.
  final TarjetaInstancia? deQuienLeemos;

  Snapshot? get enjambre => deQuienLeemos?.snapshot;

  List<SesionVista> get sesiones => enjambre?.requierenAtencion ?? const [];

  List<TarjetaInstancia> get calladas =>
      instancias.where((i) => i.salud == SaludInstancia.callada).toList();

  /// Nadie está publicando: la vigilancia está caída entera.
  ///
  /// Es la alerta más importante que la app puede dar, porque es la
  /// única que Moon-Jules **no puede** dar de sí mismo: la máquina que
  /// se cayó no avisa de que se cayó.
  ///
  /// Sin conexión no se afirma: no hay forma de saberlo, y acusar a las
  /// máquinas de algo que quizá sea culpa del móvil sería mentir con la
  /// misma autoridad que se pretende evitar.
  bool get nadieVigila =>
      conectado &&
      (instancias.isEmpty ||
          instancias.every((i) => i.salud != SaludInstancia.vigilando &&
              i.salud != SaludInstancia.enReserva));

  /// Antigüedad del dato más fresco disponible.
  ///
  /// Lo que hay que enseñar cuando no hay conexión, en lugar de fingir
  /// que el panel está al día.
  Duration? get antiguedad {
    Duration? mejor;
    for (final i in instancias) {
      final s = i.silencio;
      if (s == null) continue;
      if (mejor == null || s < mejor) mejor = s;
    }
    return mejor;
  }

  /// Si se puede designar esa instancia, y si no, por qué.
  ///
  /// Se devuelve el motivo en vez de un simple `false` para que la
  /// pantalla no tenga que adivinarlo: un botón gris sin explicación es
  /// tan confuso como uno que falla al pulsarlo.
  String? motivoNoDesignable(TarjetaInstancia t) {
    if (!conectado) return 'sin conexión';
    if (t.salud == SaludInstancia.ilegible) return 'publica algo ilegible';
    if (t.salud == SaludInstancia.callada) {
      return 'callada hace ${humano(t.silencio)}';
    }
    if (control.designada == t.id) return 'ya está designada';
    return null;
  }

  bool designable(TarjetaInstancia t) => motivoNoDesignable(t) == null;

  /// Ninguna se puede designar. Merece decirse: si no, la pantalla
  /// parecería rota, con todos los botones apagados y sin motivo.
  bool get ningunaDesignable => !instancias.any(designable);

  /// Se designó una máquina y no recogió el encargo.
  bool get relevoSinConfirmar => control.designacionSinRecoger;

  /// Lo que debe ir en el contador de la pantalla.
  int get alertas {
    final problemas = enjambre?.enjambre.atencion ?? 0;
    // Las calladas solo cuentan con conexión: sin ella, su silencio
    // puede ser el del propio teléfono.
    return problemas +
        (conectado ? calladas.length : 0) +
        (relevoSinConfirmar ? 1 : 0);
  }
}

/// Construye la vista a partir de lo leído.
///
/// Función pura: recibe lo que dio Firebase y el instante actual, y
/// devuelve exactamente lo que hay que pintar.
VistaPanel construirPanel(
  List<LecturaInstancia> lecturas,
  Control control,
  DateTime ahora, {
  bool conectado = true,
}) {
  final tarjetas = <TarjetaInstancia>[];
  for (final l in lecturas) {
    if (!l.correcta) {
      tarjetas.add(TarjetaInstancia(
        id: l.id,
        salud: SaludInstancia.ilegible,
        error: l.error,
      ));
      continue;
    }
    final s = l.snapshot!;
    final callada = s.instancia.caducada(ahora);
    tarjetas.add(TarjetaInstancia(
      id: l.id,
      salud: callada
          ? SaludInstancia.callada
          : (s.instancia.esActiva
              ? SaludInstancia.vigilando
              : SaludInstancia.enReserva),
      snapshot: s,
      silencio: s.instancia.silencioEn(ahora),
    ));
  }

  // Lo que preocupa arriba, y dentro de cada grupo por nombre: la
  // posición de una instancia en la lista no debe bailar entre ciclos.
  //
  // El orden del enum va de mejor a peor, así que se compara al revés.
  // Escrito al derecho ponía las sanas primero, que es justo lo
  // contrario de lo que el comentario prometía.
  tarjetas.sort((a, b) {
    final porSalud = b.salud.index.compareTo(a.salud.index);
    return porSalud != 0 ? porSalud : a.id.compareTo(b.id);
  });

  return VistaPanel(
    instancias: tarjetas,
    control: control,
    deQuienLeemos: _mejorFuente(tarjetas),
    conectado: conectado,
  );
}

/// La instancia de la que conviene leer el estado del enjambre.
TarjetaInstancia? _mejorFuente(List<TarjetaInstancia> tarjetas) {
  for (final salud in [SaludInstancia.vigilando, SaludInstancia.enReserva]) {
    for (final t in tarjetas) {
      if (t.salud == salud && t.snapshot != null) return t;
    }
  }
  // Todas calladas: se muestra la más reciente aunque esté rancia, con
  // el aviso de que nadie vigila. Datos viejos y etiquetados son mejores
  // que una pantalla en blanco.
  TarjetaInstancia? masFresca;
  for (final t in tarjetas) {
    if (t.snapshot == null || t.silencio == null) continue;
    if (masFresca?.silencio == null || t.silencio! < masFresca!.silencio!) {
      masFresca = t;
    }
  }
  return masFresca;
}

/// Corrige el reloj del teléfono con el desfase que informa Firebase.
///
/// La caducidad del latido se calcula contra la hora local. Un móvil
/// cinco minutos adelantado daría por caídas máquinas que están
/// publicando cada cinco, y uno atrasado ocultaría una caída real. El
/// desfase lo mide el propio SDK contra el servidor.
DateTime corregirReloj(DateTime local, Duration desfase) =>
    local.toUtc().add(desfase);

/// Orden en que se muestran las sesiones con problema.
///
/// Primero el canario —un nudge sin respuesta significa que el prompt
/// dejó de funcionar, y eso importa más que cualquier sesión suelta—,
/// después lo que lleva más tiempo mudo.
List<SesionVista> ordenarPorUrgencia(List<SesionVista> sesiones) {
  final copia = [...sesiones];
  copia.sort((a, b) {
    if (a.veredicto.esCanario != b.veredicto.esCanario) {
      return a.veredicto.esCanario ? -1 : 1;
    }
    final sa = a.silencio?.inSeconds ?? -1;
    final sb = b.silencio?.inSeconds ?? -1;
    if (sa != sb) return sb.compareTo(sa);
    return a.repo.compareTo(b.repo);
  });
  return copia;
}

/// Agrupa por repositorio, conservando el orden de urgencia.
Map<String, List<SesionVista>> agruparPorRepo(List<SesionVista> sesiones) {
  final salida = <String, List<SesionVista>>{};
  for (final s in ordenarPorUrgencia(sesiones)) {
    salida.putIfAbsent(s.repo, () => []).add(s);
  }
  return salida;
}

/// Qué motivo mostrar en la lista.
///
/// Se prefiere lo que dijo el agente. El `reason` del API es siempre el
/// mismo texto —"unable to complete the task"— repetido en cada fila:
/// ocupa media pantalla para no decir nada, mientras que el mensaje del
/// agente suele explicar qué hizo o qué preguntó.
String resumenMotivo(SesionVista s) {
  final dicho = s.mensajeAgente;
  if (dicho != null && dicho.isNotEmpty) return dicho;
  return s.razon;
}

/// Cuánto tiempo mostrar de una sesión en la lista, ya etiquetado.
///
/// Un guion no comunica nada, y era lo que salía en las sesiones
/// fallidas: su `silence_s` viene ausente porque el reloj está
/// congelado. Pero la edad sí se conoce, y para una sesión muerta hace
/// meses es justo el dato que interesa.
///
/// Se etiqueta a propósito. **Muda y abierta son preguntas distintas**,
/// y presentarlas sin nombre en la misma columna las haría pasar por lo
/// mismo: una sesión puede llevar tres horas abierta y treinta segundos
/// muda, o al revés.
String resumenTiempo(SesionVista s) {
  if (s.silencio != null) return 'muda ${humano(s.silencio)}';
  if (s.edad != null) return 'abierta ${humano(s.edad)}';
  return '';
}

/// Duración legible. Misma escala que la CLI: `144270 min` no dice nada.
String humano(Duration? d) {
  if (d == null) return '—';
  final s = d.inSeconds;
  if (s < 90) return '$s s';
  final m = d.inMinutes;
  if (m < 90) return '$m min';
  final h = d.inHours;
  if (h < 48) return '$h h';
  return '${d.inDays} d';
}
