/// Tests de la pantalla principal.
///
/// La lógica de qué mostrar vive en `model/panel.dart` y ya tiene sus
/// propios tests. Lo que se comprueba aquí es lo otro: que la pantalla
/// **pinte** lo que esa lógica decide. Son cosas distintas, y hasta
/// ahora solo estaba cubierta la primera.
///
/// Los providers se sustituyen por valores fijos, así que no hace falta
/// Firebase ni red. Nada de esto toca un dispositivo.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:moonjules/src/data/repositorio.dart';
import 'package:moonjules/src/model/lectura.dart';
import 'package:moonjules/src/model/snapshot.dart';
import 'package:moonjules/src/providers.dart';
import 'package:moonjules/src/ui/pantalla_panel.dart';

import 'snapshot_test.dart' show fallidaReal, snapshotReal, vivaReal;

final ahora = DateTime.utc(2026, 8, 26, 12, 0);
final reciente = ahora.subtract(const Duration(minutes: 2));
final rancio = ahora.subtract(const Duration(hours: 3));

LecturaInstancia instancia(
  String id, {
  DateTime? latido,
  String rol = 'active',
  List<Object?>? sesiones,
}) {
  final crudo = snapshotReal(
    latidoMs: (latido ?? reciente).millisecondsSinceEpoch,
    sesiones: sesiones,
  );
  (crudo['instance']! as Map<String, Object?>)
    ..['id'] = id
    ..['role'] = rol;
  return LecturaInstancia.ok(id, Snapshot.desdeJson(crudo));
}

/// Monta el panel con los providers sustituidos por valores fijos.
Future<void> montar(
  WidgetTester tester, {
  List<LecturaInstancia>? instancias,
  Control? control,
  bool conectado = true,
  RegistroAvisos? avisos,
}) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        instanciasProvider.overrideWith(
          (ref) => Stream.value(instancias ?? [instancia('la-dorada')]),
        ),
        controlProvider.overrideWith(
          (ref) => Stream.value(control ?? Control.desdeJson({'known': true})),
        ),
        conexionProvider.overrideWith((ref) => Stream.value(conectado)),
        desfaseProvider.overrideWith((ref) => Stream.value(Duration.zero)),
        relojProvider.overrideWith((ref) => Stream.value(ahora)),
        avisosProvider.overrideWith(
          (ref) => Stream.value(avisos ?? const RegistroAvisos.ok('tok')),
        ),
      ],
      child: const MaterialApp(home: PantallaPanel()),
    ),
  );
  await tester.pump();
}

void main() {
  group('instancias', () {
    testWidgets('la que vigila se distingue de la que está en reserva',
        (tester) async {
      await montar(tester, instancias: [
        instancia('la-dorada'),
        instancia('boston', rol: 'standby'),
      ]);
      expect(find.text('la-dorada'), findsOneWidget);
      expect(find.textContaining('vigilando'), findsOneWidget);
      expect(find.textContaining('en reserva'), findsOneWidget);
    });

    testWidgets('una callada dice cuánto lleva sin publicar', (tester) async {
      await montar(tester,
          instancias: [instancia('sao-paulo', latido: rancio)]);
      expect(find.textContaining('sin publicar hace 3 h'), findsOneWidget);
    });

    testWidgets('una ilegible no impide ver las demás', (tester) async {
      await montar(tester, instancias: [
        const LecturaInstancia.fallida('rara', 'esquema 99'),
        instancia('la-dorada'),
      ]);
      expect(find.text('rara'), findsOneWidget);
      expect(find.text('la-dorada'), findsOneWidget);
      expect(find.textContaining('esquema 99'), findsOneWidget);
    });
  });

  group('avisos de la parte de arriba', () {
    testWidgets('sin conexión no se acusa a las máquinas', (tester) async {
      // El SDK sirve de caché: sin este aviso, latidos rancios harían
      // creer que las tres murieron cuando el móvil está sin red.
      await montar(tester,
          conectado: false,
          instancias: [instancia('la-dorada', latido: rancio)]);
      expect(find.text('Sin conexión'), findsOneWidget);
      expect(find.text('Nadie está vigilando'), findsNothing);
    });

    testWidgets('con conexión y todas calladas, sí se dice', (tester) async {
      await montar(tester,
          instancias: [instancia('la-dorada', latido: rancio)]);
      expect(find.text('Nadie está vigilando'), findsOneWidget);
    });

    testWidgets('un relevo sin recoger se avisa', (tester) async {
      await montar(
        tester,
        control: Control.desdeJson({'desired': 'boston', 'known': true}),
      );
      expect(find.text('Relevo sin confirmar'), findsOneWidget);
      expect(find.textContaining('boston'), findsWidgets);
    });

    testWidgets('con todo en orden no hay avisos', (tester) async {
      await montar(tester);
      expect(find.text('Sin conexión'), findsNothing);
      expect(find.text('Nadie está vigilando'), findsNothing);
      expect(find.text('Relevo sin confirmar'), findsNothing);
    });
  });

  group('estado del push', () {
    testWidgets('cuando va bien se dice, no solo cuando falla',
        (tester) async {
      await montar(tester);
      expect(find.text('Avisos en segundo plano activos'), findsOneWidget);
    });

    testWidgets('cuando falla se muestra el motivo real', (tester) async {
      // Una conjetura manda a revisar el sitio equivocado; eso ya costó
      // una noche entera.
      await montar(
        tester,
        avisos: const RegistroAvisos.fallido('No se pudo registrar en RTDB: '
            'permission-denied'),
      );
      expect(find.text('Sin avisos en segundo plano'), findsOneWidget);
      expect(find.textContaining('permission-denied'), findsOneWidget);
      expect(find.text('Avisos en segundo plano activos'), findsNothing);
    });
  });

  group('sesiones', () {
    testWidgets('se agrupan por repositorio', (tester) async {
      await montar(tester);
      expect(find.text('Informatica-ASHware/3AL-Inventario'), findsOneWidget);
    });

    testWidgets('una fallida muestra la edad, no un guion', (tester) async {
      // Su reloj está congelado, así que no hay silencio que medir; la
      // edad sí se conoce y es lo que interesa.
      await montar(tester);
      expect(find.textContaining('abierta'), findsWidgets);
    });

    testWidgets('lo sano no aparece en la lista de problemas',
        (tester) async {
      await montar(tester);
      // `vivaReal` es healthy: su título no debe estar entre los
      // hallazgos que requieren atención.
      expect(find.textContaining('Ejecuta el sistema de auditorías'),
          findsNothing);
    });

    testWidgets('sin nada que atender se dice explícitamente',
        (tester) async {
      final limpia = snapshotReal(sesiones: [vivaReal]);
      (limpia['swarm']! as Map<String, Object?>)['attention'] = 0;
      await montar(tester, instancias: [
        LecturaInstancia.ok('la-dorada', Snapshot.desdeJson(limpia)),
      ]);
      expect(find.text('Nada que atender'), findsOneWidget);
    });

    testWidgets('tocar una sesión abre su detalle', (tester) async {
      await montar(tester);
      await tester.tap(find.textContaining('[E02-017]').first);
      await tester.pumpAndSettle();
      expect(find.text('Sesión'), findsOneWidget);
      expect(find.text('Diagnóstico'), findsOneWidget);
    });
  });

  group('resumen del enjambre', () {
    testWidgets('muestra activas, atención y silenciadas', (tester) async {
      await montar(tester);
      expect(find.textContaining('10/15 activas'), findsOneWidget);
      expect(find.textContaining('8 requieren atención'), findsOneWidget);
    });

    testWidgets('avisa si se alcanzó el tope de concurrencia',
        (tester) async {
      final lleno = snapshotReal(sesiones: [fallidaReal]);
      (lleno['swarm']! as Map<String, Object?>)['active'] = 15;
      await montar(tester, instancias: [
        LecturaInstancia.ok('la-dorada', Snapshot.desdeJson(lleno)),
      ]);
      expect(find.textContaining('Tope de concurrencia'), findsOneWidget);
    });

    testWidgets('avisa si la autonomía está pausada', (tester) async {
      final pausado = snapshotReal(sesiones: [fallidaReal]);
      (pausado['swarm']! as Map<String, Object?>)['paused'] = {
        '*': 'revisando',
      };
      await montar(tester, instancias: [
        LecturaInstancia.ok('la-dorada', Snapshot.desdeJson(pausado)),
      ]);
      expect(find.textContaining('Autonomía pausada'), findsOneWidget);
    });
  });

  group('carga y error', () {
    testWidgets('mientras carga no se pinta un panel vacío engañoso',
        (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            instanciasProvider.overrideWith(
              (ref) => const Stream<List<LecturaInstancia>>.empty(),
            ),
          ],
          child: const MaterialApp(home: PantallaPanel()),
        ),
      );
      await tester.pump();
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });

    testWidgets('un fallo de Firebase se muestra, no se traga',
        (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            instanciasProvider.overrideWith(
              (ref) => Stream<List<LecturaInstancia>>.error('permiso denegado'),
            ),
          ],
          child: const MaterialApp(home: PantallaPanel()),
        ),
      );
      await tester.pump();
      expect(find.text('No se pudo leer Firebase'), findsOneWidget);
      expect(find.textContaining('permiso denegado'), findsOneWidget);
    });
  });
}
