/// Punto de entrada de la app.
///
/// Mínimo a propósito: la pantalla llega en la siguiente entrega. Lo que
/// hay aquí existe para que `flutter test` y `flutter run` compilen sobre
/// la capa de datos ya verificada.
///
/// Sustituye a la plantilla de `flutter create`, que en el canal master
/// genera sintaxis experimental (*dot-shorthands*) y no compila con una
/// restricción de SDK estable.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

void main() {
  runApp(const ProviderScope(child: MoonJulesApp()));
}

class MoonJulesApp extends StatelessWidget {
  const MoonJulesApp({super.key});

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
      home: const _Pendiente(),
    );
  }
}

class _Pendiente extends StatelessWidget {
  const _Pendiente();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(child: Text('Moon-Jules')),
    );
  }
}
