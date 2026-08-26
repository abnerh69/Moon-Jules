/// Providers de Riverpod. Pegamento entre el repositorio y la pantalla.
///
/// Deliberadamente delgado: aquí no se decide nada. Lo que hay que
/// mostrar, en qué orden y qué significa cada estado lo resuelve
/// `model/panel.dart`, que es Dart puro y está cubierto por tests.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'data/repositorio.dart';
import 'model/lectura.dart';
import 'model/panel.dart';
import 'model/snapshot.dart';

final repositorioProvider = Provider<RepositorioMoonJules>(
  (ref) => RepositorioMoonJules(),
);

final instanciasProvider = StreamProvider<List<LecturaInstancia>>(
  (ref) => ref.watch(repositorioProvider).instancias(),
);

final controlProvider = StreamProvider<Control>(
  (ref) => ref.watch(repositorioProvider).control(),
);

/// Reloj que avanza sin depender de que Firebase envíe nada.
///
/// Es imprescindible: la caducidad del latido se calcula contra la hora
/// actual, y si una instancia deja de publicar **no llega ningún evento
/// nuevo**. Sin este tic, la pantalla se quedaría mostrando "hace 2 min"
/// para siempre, que es exactamente el engaño que la app existe para
/// evitar.
final relojProvider = StreamProvider<DateTime>((ref) async* {
  yield DateTime.now().toUtc();
  yield* Stream.periodic(
    const Duration(seconds: 20),
    (_) => DateTime.now().toUtc(),
  );
});

final conexionProvider = StreamProvider<bool>(
  (ref) => ref.watch(repositorioProvider).conectado(),
);

final desfaseProvider = StreamProvider<Duration>(
  (ref) => ref.watch(repositorioProvider).desfaseServidor(),
);

/// Todo lo que la pantalla principal necesita, ya resuelto.
final panelProvider = Provider<AsyncValue<VistaPanel>>((ref) {
  final instancias = ref.watch(instanciasProvider);
  final control = ref.watch(controlProvider);
  final ahora = ref.watch(relojProvider);
  final conectado = ref.watch(conexionProvider);
  final desfase = ref.watch(desfaseProvider);

  return instancias.when(
    loading: () => const AsyncValue.loading(),
    error: AsyncValue.error,
    data: (lecturas) => AsyncValue.data(
      construirPanel(
        lecturas,
        control.valueOrNull ?? const Control(),
        corregirReloj(
          ahora.valueOrNull ?? DateTime.now().toUtc(),
          desfase.valueOrNull ?? Duration.zero,
        ),
        // Mientras no se sepa, se asume conectado: decir "sin conexión"
        // en el arranque, antes de que el SDK responda, seria un susto
        // gratuito en cada apertura.
        conectado: conectado.valueOrNull ?? true,
      ),
    ),
  );
});

/// Registra este teléfono para recibir avisos y sigue las rotaciones.
///
/// Un solo flujo para las dos cosas: el primer valor es el registro
/// inicial y los siguientes son los tokens renovados. **Los tokens
/// rotan**, y uno viejo deja de recibir sin avisar de nada — que es
/// justo el modo de fallo que esta app existe para no repetir.
final avisosProvider = StreamProvider<RegistroAvisos>((ref) async* {
  final repo = ref.watch(repositorioProvider);
  yield await repo.registrarDispositivo();
  yield* repo.tokensRenovados().map(RegistroAvisos.ok);
});

/// Sesión concreta, para la ventana de detalle.
final sesionProvider = Provider.family<SesionVista?, String>((ref, id) {
  final panel = ref.watch(panelProvider).valueOrNull;
  final todas = panel?.enjambre?.sesiones ?? const <SesionVista>[];
  for (final s in todas) {
    if (s.id == id) return s;
  }
  return null;
});
