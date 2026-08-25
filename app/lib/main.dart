/// Punto de entrada de la app.
///
/// Sustituye a la plantilla de `flutter create`, que en el canal master
/// genera sintaxis experimental (*dot-shorthands*) y no compila con una
/// restricción de SDK estable.
library;

import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'firebase_options.dart';
import 'src/ui/pantalla_panel.dart';

/// Credenciales inyectadas al compilar, nunca escritas en el código.
///
/// Mismo criterio que la ADR-004 del lado de Python: el secreto se
/// referencia, no se escribe. Aquí la referencia es `--dart-define`.
///
/// **No sirve una cuenta anónima.** Las reglas exigen un UID concreto
/// —el del arquitecto— y el anónimo cambia en cada instalación, así que
/// Firebase rechazaría cada lectura.
const String _correo = String.fromEnvironment('MJ_EMAIL');
const String _clave = String.fromEnvironment('MJ_PASSWORD');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );
  final error = await _entrar();
  runApp(ProviderScope(child: MoonJulesApp(errorDeEntrada: error)));
}

/// Devuelve el motivo si no se pudo entrar, o `null` si todo fue bien.
///
/// No se lanza: una app que muere en el arranque no puede explicar por
/// qué, y este fallo tiene causas concretas que conviene poder leer.
Future<String?> _entrar() async {
  if (_correo.isEmpty || _clave.isEmpty) {
    return 'Faltan las credenciales. Compila con:\n'
        'flutter run --dart-define=MJ_EMAIL=... '
        '--dart-define=MJ_PASSWORD=...';
  }
  try {
    final auth = FirebaseAuth.instance;
    if (auth.currentUser == null) {
      await auth.signInWithEmailAndPassword(email: _correo, password: _clave);
    }
    return null;
  } on FirebaseAuthException catch (e) {
    return 'No se pudo entrar en Firebase: ${e.code}.\n'
        'Comprueba la cuenta en Authentication y que su UID sea el que '
        'aparece en las reglas.';
  }
}

class MoonJulesApp extends StatelessWidget {
  const MoonJulesApp({this.errorDeEntrada, super.key});

  final String? errorDeEntrada;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Moon-Jules',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF3F51B5),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: errorDeEntrada == null
          ? const PantallaPanel()
          : _SinEntrar(motivo: errorDeEntrada!),
    );
  }
}

class _SinEntrar extends StatelessWidget {
  const _SinEntrar({required this.motivo});

  final String motivo;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Moon-Jules')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.lock_outline, size: 48),
            const SizedBox(height: 16),
            Text(motivo, textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}
