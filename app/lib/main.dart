/// Punto de entrada de la app.
library;

import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'firebase_options.dart';
import 'src/acceso_notifier.dart';
import 'src/data/canal_avisos.dart';
import 'src/ui/pantalla_acceso.dart';
import 'src/ui/pantalla_panel.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );
  // Antes de nada: sin canal, Android descarta en silencio lo que
  // llegue con la app cerrada, y FCM informa de entrega correcta.
  await crearCanalAvisos();
  runApp(const ProviderScope(child: MoonJulesApp()));
}

class MoonJulesApp extends StatelessWidget {
  const MoonJulesApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Moon Jules',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF3F51B5),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const _Raiz(),
    );
  }
}

/// Decide qué pantalla toca según el estado del acceso.
class _Raiz extends ConsumerWidget {
  const _Raiz();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ref.watch(accesoProvider).when(
          loading: () => const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          ),
          error: (e, _) => Scaffold(
            body: Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text('No se pudo comprobar el acceso: $e'),
              ),
            ),
          ),
          data: (s) =>
              s.dentro ? const PantallaPanel() : PantallaAcceso(sesion: s),
        );
  }
}
