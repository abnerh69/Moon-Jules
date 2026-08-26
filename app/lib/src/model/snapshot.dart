/// Modelo del snapshot que publica Moon-Jules.
///
/// Contrato: `docs/SNAPSHOT.md`, esquema 3.
///
/// Dart puro a propósito, sin nada de Flutter: así se ejecuta con `dart
/// test` sin emulador ni dispositivo, y toda la lógica que puede
/// equivocarse —el parseo, la caducidad del latido, los veredictos—
/// queda cubierta por tests que corren en un segundo.
library;

/// Versión del esquema que esta app entiende.
const int kEsquemaSoportado = 5;

/// Lanzada cuando el snapshot viene en una versión desconocida.
///
/// Se rechaza en vez de interpretarse a medias: un panel que muestra
/// datos mal leídos es peor que uno que dice "no entiendo esta versión".
class EsquemaIncompatible implements Exception {
  const EsquemaIncompatible(this.encontrado, this.soportado);

  final int encontrado;
  final int soportado;

  @override
  String toString() =>
      'Snapshot con esquema $encontrado; esta app entiende el $soportado. '
      'Actualiza la app o Moon-Jules.';
}

/// Lee un entero tolerando que llegue como `num` o como texto.
///
/// **Una clave ausente devuelve `null`, nunca cero.** Firebase omite los
/// valores nulos, así que la ausencia es información: significa
/// "desconocido o no aplicable". Confundirla con cero es el error más
/// fácil de cometer aquí y el más difícil de ver.
int? leerEntero(Object? valor) {
  if (valor is int) return valor;
  if (valor is num) return valor.toInt();
  if (valor is String) return int.tryParse(valor);
  return null;
}

String? leerTexto(Object? valor) {
  if (valor is String && valor.isNotEmpty) return valor;
  return null;
}

bool leerBool(Object? valor, {bool porDefecto = false}) {
  if (valor is bool) return valor;
  return porDefecto;
}

Map<String, Object?> leerMapa(Object? valor) {
  if (valor is Map) {
    return valor.map((k, v) => MapEntry(k.toString(), v as Object?));
  }
  return const {};
}

/// Dictamen de Moon-Jules sobre una sesión.
enum Veredicto {
  healthy('healthy'),
  done('done'),
  pausedDone('paused_done'),
  stalled('stalled'),
  blockedFeedback('blocked_feedback'),
  blockedPlan('blocked_plan'),
  queuedSlow('queued_slow'),
  pausedStale('paused_stale'),
  failed('failed'),
  nudgeUnanswered('nudge_unanswered'),
  nudgeBudgetSpent('nudge_budget_spent'),
  /// Veredicto que esta versión de la app no conoce.
  desconocido('desconocido');

  const Veredicto(this.clave);

  final String clave;

  /// Nunca lanza: Moon-Jules puede añadir veredictos y la app no debe
  /// caerse por eso. Se muestra lo que se sabe y el resto queda como
  /// desconocido, que es honesto.
  static Veredicto desde(Object? valor) {
    final texto = leerTexto(valor);
    for (final v in Veredicto.values) {
      if (v.clave == texto) return v;
    }
    return Veredicto.desconocido;
  }

  /// Si alguno de estos se repite, el prompt de continuación dejó de
  /// funcionar, y eso importa más que cualquier sesión concreta.
  bool get esCanario => this == Veredicto.nudgeUnanswered;
}

/// Una sesión tal como la ve el móvil.
class SesionVista {
  const SesionVista({
    required this.id,
    required this.repo,
    required this.estado,
    required this.veredicto,
    required this.razon,
    required this.silenciada,
    required this.requiereAtencion,
    this.titulo,
    this.silencio,
    this.edad,
    this.url,
    this.inicioCrudo,
    this.nudges = 0,
    this.ultimoNudgeEn,
    this.ultimoNudgeDesenlace,
    this.mensajeAgente,
    this.ultimoEvento,
    this.tipoUltimoEvento,
  });

  factory SesionVista.desdeJson(Map<String, Object?> json) {
    return SesionVista(
      id: leerTexto(json['id']) ?? '',
      repo: leerTexto(json['repo']) ?? '(sin repo)',
      titulo: leerTexto(json['title']),
      estado: leerTexto(json['state']) ?? 'STATE_UNSPECIFIED',
      veredicto: Veredicto.desde(json['verdict']),
      razon: leerTexto(json['reason']) ?? '',
      silenciada: leerBool(json['acked']),
      requiereAtencion: leerBool(json['needs_attention']),
      // Ausente NO es cero: significa reloj congelado porque la sesión
      // cerró. Mostrar "muda hace 0 s" sobre trabajo entregado sería
      // exactamente al revés de la verdad.
      silencio: _segundos(json['silence_s']),
      edad: _segundos(json['age_s']),
      url: leerTexto(json['url']),
      inicioCrudo: leerTexto(json['started_at']),
      nudges: leerEntero(json['nudges']) ?? 0,
      ultimoNudgeEn: leerTexto(json['last_nudge_at']),
      ultimoNudgeDesenlace: leerTexto(json['last_nudge_outcome']),
      mensajeAgente: leerTexto(json['last_agent_message']),
      ultimoEvento: DateTime.tryParse(leerTexto(json['last_agent_at']) ?? '')
          ?.toUtc(),
      tipoUltimoEvento: leerTexto(json['last_agent_kind']),
    );
  }

  final String id;
  final String repo;
  final String? titulo;
  final String estado;
  final Veredicto veredicto;
  final String razon;
  final bool silenciada;
  final bool requiereAtencion;

  /// Cuánto lleva muda. `null` si el reloj está congelado.
  final Duration? silencio;

  /// Cuánto lleva abierta. Pregunta distinta de [silencio].
  final Duration? edad;

  final String? url;

  /// Cuándo empezó la sesión. Inmutable, a diferencia de `updateTime`.
  DateTime? get inicio =>
      inicioCrudo == null ? null : DateTime.tryParse(inicioCrudo!)?.toUtc();

  final int nudges;
  final String? ultimoNudgeEn;
  final String? ultimoNudgeDesenlace;

  /// Cuándo ocurrió el último evento **del agente**.
  ///
  /// No es «cuándo se actualizó»: el API mueve `updateTime` a la fecha
  /// de hoy para sesiones muertas hace meses, y confundir «el sistema la
  /// miró» con «aquí pasó algo» ya costó dos entregas.
  final String? inicioCrudo;

  final DateTime? ultimoEvento;

  /// De qué fue: `sessionFailed`, `agentMessaged`, `progressUpdated`…
  final String? tipoUltimoEvento;

  /// Lo último que dijo Jules, si dijo algo.
  ///
  /// Es donde está la información: `reason` repite siempre "unable to
  /// complete the task", mientras que el agente suele explicar qué hizo
  /// o qué necesita. Solo viaja para lo que requiere atención.
  final String? mensajeAgente;

  bool get estaViva => estado == 'IN_PROGRESS' || estado == 'PLANNING';

  bool get nudgeSinRespuesta => ultimoNudgeDesenlace == 'unanswered';

  static Duration? _segundos(Object? valor) {
    final n = leerEntero(valor);
    return n == null ? null : Duration(seconds: n);
  }
}

/// Quién publicó, cuándo y con qué papel.
class Instancia {
  const Instancia({
    required this.id,
    required this.latido,
    required this.caducaTras,
    required this.intervalo,
    this.version,
    this.modo,
    this.papel = 'active',
  });

  factory Instancia.desdeJson(Map<String, Object?> json) {
    final ms = leerEntero(json['heartbeat_ms']);
    return Instancia(
      id: leerTexto(json['id']) ?? '(sin nombre)',
      latido: ms == null
          ? null
          : DateTime.fromMillisecondsSinceEpoch(ms, isUtc: true),
      // El umbral viaja en el snapshot para no codificarlo aquí.
      caducaTras: Duration(seconds: leerEntero(json['stale_after_s']) ?? 1200),
      intervalo: Duration(seconds: leerEntero(json['cycle_interval_s']) ?? 300),
      version: leerTexto(json['version']),
      modo: leerTexto(json['mode']),
      papel: leerTexto(json['role']) ?? 'active',
    );
  }

  final String id;

  /// Cuándo publicó por última vez. `null` si nunca se supo.
  final DateTime? latido;

  final Duration caducaTras;
  final Duration intervalo;
  final String? version;
  final String? modo;
  final String papel;

  bool get esActiva => papel == 'active';

  Duration? silencioEn(DateTime ahora) =>
      latido == null ? null : ahora.toUtc().difference(latido!);

  /// **Sin latido conocido se considera caída.**
  ///
  /// Es el lado prudente: una máquina muerta no puede avisar de que lo
  /// está, solo dejar de hablar. Ante la duda, tratarla como silencio.
  bool caducada(DateTime ahora) {
    final s = silencioEn(ahora);
    return s == null || s >= caducaTras;
  }
}

/// Cifras del enjambre.
class Enjambre {
  const Enjambre({
    this.total = 0,
    this.activas = 0,
    this.maxActivas = 0,
    this.atencion = 0,
    this.silenciadas = 0,
    this.pausas = const {},
  });

  factory Enjambre.desdeJson(Map<String, Object?> json) {
    final pausado = json['paused'];
    return Enjambre(
      total: leerEntero(json['sessions_total']) ?? 0,
      activas: leerEntero(json['active']) ?? 0,
      maxActivas: leerEntero(json['max_active']) ?? 0,
      atencion: leerEntero(json['attention']) ?? 0,
      silenciadas: leerEntero(json['acked']) ?? 0,
      pausas: pausado == null
          ? const {}
          : leerMapa(pausado)
              .map((k, v) => MapEntry(k, leerTexto(v) ?? '')),
    );
  }

  final int total;
  final int activas;
  final int maxActivas;
  final int atencion;
  final int silenciadas;

  /// Ámbitos con la autonomía pausada. Vacío si está activa.
  final Map<String, String> pausas;

  bool get pausado => pausas.isNotEmpty;

  bool get topeAlcanzado => maxActivas > 0 && activas >= maxActivas;
}

/// Estado del relevo, tal como lo leyó esta instancia.
class Control {
  const Control({this.designada, this.reclamadaPor, this.reclamadaEn,
      this.conocido = true});

  factory Control.desdeJson(Map<String, Object?> json) => Control(
        designada: leerTexto(json['desired']),
        reclamadaPor: leerTexto(json['claimed_by']),
        reclamadaEn: leerTexto(json['claimed_at']),
        conocido: leerBool(json['known'], porDefecto: true),
      );

  final String? designada;
  final String? reclamadaPor;
  final String? reclamadaEn;

  /// `false` si esta instancia no pudo leer el control.
  final bool conocido;

  /// Se designó una máquina y nadie recogió el encargo.
  ///
  /// Suele significar que ese portátil está dormido, y es una alerta por
  /// derecho propio: sin este contraste, una designación se mostraría
  /// como un hecho consumado.
  bool get designacionSinRecoger =>
      designada != null && reclamadaPor != designada;
}

/// El documento completo.
class Snapshot {
  const Snapshot({
    required this.esquema,
    required this.instancia,
    required this.enjambre,
    required this.control,
    required this.sesiones,
  });

  /// Lanza [EsquemaIncompatible] si la versión no se reconoce.
  factory Snapshot.desdeJson(Map<String, Object?> json) {
    final esquema = leerEntero(json['schema']) ?? 0;
    if (esquema != kEsquemaSoportado) {
      throw EsquemaIncompatible(esquema, kEsquemaSoportado);
    }
    final crudas = json['sessions'];
    return Snapshot(
      esquema: esquema,
      instancia: Instancia.desdeJson(leerMapa(json['instance'])),
      enjambre: Enjambre.desdeJson(leerMapa(json['swarm'])),
      control: Control.desdeJson(leerMapa(json['control'])),
      sesiones: crudas is List
          ? crudas
              .whereType<Object>()
              .map((s) => SesionVista.desdeJson(leerMapa(s)))
              .toList(growable: false)
          : const [],
    );
  }

  final int esquema;
  final Instancia instancia;
  final Enjambre enjambre;
  final Control control;
  final List<SesionVista> sesiones;

  List<SesionVista> get requierenAtencion =>
      sesiones.where((s) => s.requiereAtencion).toList(growable: false);

  /// Problemas ya triados. Siguen mal; solo se dieron por vistos.
  List<SesionVista> get silenciadas =>
      sesiones.where((s) => s.silenciada).toList(growable: false);

  List<SesionVista> get vivas =>
      sesiones.where((s) => s.estaViva).toList(growable: false);

  /// Lo que debe empujar el badge: problemas sin triar, más el aviso de
  /// que nadie está mirando.
  int alertasEn(DateTime ahora) =>
      enjambre.atencion + (instancia.caducada(ahora) ? 1 : 0);
}
