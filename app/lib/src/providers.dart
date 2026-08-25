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

/// Todo lo que la pantalla principal necesita, ya resuelto.
final panelProvider = Provider<AsyncValue<VistaPanel>>((ref) {
  final instancias = ref.watch(instanciasProvider);
  final control = ref.watch(controlProvider);
  final ahora = ref.watch(relojProvider);

  return instancias.when(
    loading: () => const AsyncValue.loading(),
    error: AsyncValue.error,
    data: (lecturas) => AsyncValue.data(
      construirPanel(
        lecturas,
        control.valueOrNull ?? const Control(),
        ahora.valueOrNull ?? DateTime.now().toUtc(),
      ),
    ),
  );
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
