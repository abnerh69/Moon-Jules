/// Tests de la vista por repositorio.
///
/// Los formatos de referencia salen de los títulos reales del enjambre,
/// que es lo que hace que estos tests protejan algo.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:moonjules/src/model/lectura.dart';
import 'package:moonjules/src/model/panel.dart';
import 'package:moonjules/src/model/snapshot.dart';
import 'package:moonjules/src/providers.dart';
import 'package:moonjules/src/ui/vista_proyectos.dart';

import 'snapshot_test.dart' show snapshotReal;

Map<String, Object?> fuente(
  String repo, {
  int activas = 0,
  int atencion = 0,
  int sesiones = 0,
  String? titulo,
  String veredicto = 'healthy',
  int hechas = 0,
  int rotas = 0,
  String? cinta,
  String? motivo,
}) =>
    {
      'id': 'sources/github/$repo',
      'repo': repo,
      'active': activas,
      'attention': atencion,
      'sessions': sesiones,
      'done': hechas,
      'failed': rotas,
      if (cinta != null) 'belt': cinta,
      if (motivo != null) 'belt_reason': motivo,
      if (titulo != null)
        'current': <String, Object?>{
          'id': 's1',
          'title': titulo,
          'state': 'IN_PROGRESS',
          'verdict': veredicto,
        },
    };

Snapshot conFuentes(List<Map<String, Object?>> fuentes) {
  final crudo = snapshotReal();
  crudo['sources'] = fuentes;
  return Snapshot.desdeJson(crudo);
}

Future<void> montarProyectos(
  WidgetTester tester, {
  required List<Map<String, Object?>> fuentes,
  Set<String> archivados = const {},
}) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        instanciasProvider.overrideWith((ref) => Stream.value([
              LecturaInstancia.ok('la-dorada', conFuentes(fuentes)),
            ])),
        controlProvider.overrideWith(
            (ref) => Stream.value(Control.desdeJson({'known': true}))),
        conexionProvider.overrideWith((ref) => Stream.value(true)),
        desfaseProvider.overrideWith((ref) => Stream.value(Duration.zero)),
        relojProvider.overrideWith(
            (ref) => Stream.value(DateTime.utc(2026, 8, 26, 12))),
        archivadosProvider.overrideWith((ref) => Stream.value(archivados)),
      ],
      child: const MaterialApp(home: Scaffold(body: VistaProyectos())),
    ),
  );
  await tester.pump();
}

void main() {
  group('referencia al issue', () {
    test('se extrae de los formatos reales del enjambre', () {
      // No es dato del API: es convención del arquitecto.
      expect(referenciaDe('[E02-017] Validación end-to-end'), 'E02-017');
      expect(referenciaDe('[TASK-1.12] Configurar CI/CD base'), 'TASK-1.12');
      expect(referenciaDe('[US 7.01] Herramientas de Dibujo'), 'US 7.01');
      expect(referenciaDe('[E12-S04] Health endpoints'), 'E12-S04');
    });

    test('con dos corchetes se toma el primero', () {
      expect(referenciaDe('[SP7] [Bug] Error persistente de ruta'), 'SP7');
    });

    test('sin referencia no se inventa ninguna', () {
      // Estos títulos existen en el enjambre y no llevan prefijo.
      expect(referenciaDe('Corregir issues detectados por `melos analyze`.'),
          isNull);
      expect(referenciaDe('Ejecuta el sistema de auditorías'), isNull);
      expect(referenciaDe(null), isNull);
      expect(referenciaDe(''), isNull);
    });

    test('un corchete desmesurado no es una referencia', () {
      // Evita tomar por referencia un título que empieza con corchetes
      // por casualidad.
      final largo = '[${'x' * 40}] algo';
      expect(referenciaDe(largo), isNull);
    });

    test('el título se puede mostrar sin repetir la referencia', () {
      expect(tituloSinReferencia('[E02-017] Validación end-to-end'),
          'Validación end-to-end');
      expect(tituloSinReferencia('Sin prefijo'), 'Sin prefijo');
      expect(tituloSinReferencia(null), '');
    });
  });

  group('modelo del repositorio', () {
    test('la clave sirve para RTDB', () {
      // Las claves de RTDB no admiten `/`.
      final f = ResumenSource.desdeJson(fuente('abnerh69/ppp-n-kits'));
      expect(f.clave, 'abnerh69__ppp-n-kits');
      expect(f.clave.contains('/'), isFalse);
    });

    test('sin sesiones no es lo mismo que sin problemas', () {
      // Puede significar que la cadena de la Action se rompió.
      final callado = ResumenSource.desdeJson(fuente('a/b'));
      expect(callado.callado, isTrue);
      expect(callado.preocupa, isFalse);
      expect(callado.trabajando, isFalse);
    });

    test('un repositorio que trabaja se distingue', () {
      final f = ResumenSource.desdeJson(
          fuente('a/b', activas: 2, sesiones: 5, titulo: '[E1] algo'));
      expect(f.trabajando, isTrue);
      expect(f.actual?.titulo, '[E1] algo');
    });

    test('un esquema sin sources no revienta', () {
      // Las versiones anteriores a la 6 no lo traían.
      final s = Snapshot.desdeJson(snapshotReal());
      expect(s.fuentes, isEmpty);
    });
  });

  group('la lista', () {
    testWidgets('muestra el repositorio y su tarea actual', (tester) async {
      await montarProyectos(tester, fuentes: [
        fuente('abnerh69/ppp-n-kits',
            activas: 1, sesiones: 3, titulo: '[E02-017] Validación end-to-end'),
      ]);
      expect(find.text('abnerh69/ppp-n-kits'), findsOneWidget);
      expect(find.textContaining('E02-017'), findsOneWidget);
      expect(find.textContaining('Validación end-to-end'), findsOneWidget);
    });

    testWidgets('un repositorio sin sesiones lo dice', (tester) async {
      await montarProyectos(tester, fuentes: [fuente('a/callado')]);
      expect(find.text('sin sesiones'), findsOneWidget);
    });

    testWidgets('los archivados no salen en la lista', (tester) async {
      await montarProyectos(
        tester,
        fuentes: [fuente('a/visible', sesiones: 1), fuente('a/oculto', sesiones: 1)],
        archivados: {'a__oculto'},
      );
      expect(find.text('a/visible'), findsOneWidget);
      expect(find.text('a/oculto'), findsNothing);
    });

    testWidgets('pero se pueden ver desplegando el archivo', (tester) async {
      await montarProyectos(
        tester,
        fuentes: [fuente('a/oculto', sesiones: 1)],
        archivados: {'a__oculto'},
      );
      expect(find.text('1 archivados'), findsOneWidget);
      await tester.tap(find.text('1 archivados'));
      await tester.pumpAndSettle();
      expect(find.text('a/oculto'), findsOneWidget);
    });

    testWidgets('el archivo aclara que se sigue vigilando', (tester) async {
      // Archivar es un filtro de vista, no un cambio de comportamiento.
      await montarProyectos(
        tester,
        fuentes: [fuente('a/oculto', sesiones: 1)],
        archivados: {'a__oculto'},
      );
      expect(find.textContaining('Se siguen vigilando'), findsOneWidget);
    });

    testWidgets('sin archivados no aparece la sección', (tester) async {
      await montarProyectos(tester, fuentes: [fuente('a/b', sesiones: 1)]);
      expect(find.textContaining('archivados'), findsNothing);
    });

    testWidgets('sin repositorios lo dice en vez de quedarse en blanco',
        (tester) async {
      await montarProyectos(tester, fuentes: []);
      expect(find.text('Todavía no hay repositorios'), findsOneWidget);
    });
  });

  group('la cinta transportadora', () {
    test('los tres caminos se distinguen', () {
      EstadoCinta leer(String? v) =>
          ResumenSource.desdeJson(fuente('a/b', cinta: v)).cinta;
      expect(leer('moving'), EstadoCinta.enMovimiento);
      expect(leer('belt_stopped'), EstadoCinta.parada);
      expect(leer('idle'), EstadoCinta.sinTrabajo);
    });

    test('un estado que esta app no conozca no la tumba', () {
      expect(ResumenSource.desdeJson(fuente('a/b', cinta: 'del_futuro')).cinta,
          EstadoCinta.desconocido);
      expect(ResumenSource.desdeJson(fuente('a/b')).cinta,
          EstadoCinta.desconocido);
    });

    testWidgets('una cinta parada lo dice, y en primer lugar', (tester) async {
      // Es el fallo silencioso: algo terminó y no arrancó nada. Sin
      // esto, un proyecto muerto se ve igual que uno que va bien.
      await montarProyectos(tester, fuentes: [
        fuente('a/parado',
            sesiones: 12, hechas: 12, cinta: 'belt_stopped',
            motivo: 'nada nuevo desde hace 3 h'),
      ]);
      expect(find.text('nada nuevo desde hace 3 h'), findsOneWidget);
    });

    testWidgets('una cinta en movimiento no alarma', (tester) async {
      await montarProyectos(tester, fuentes: [
        fuente('a/vivo',
            activas: 1, sesiones: 8, hechas: 7, titulo: '[E1] algo',
            cinta: 'moving'),
      ]);
      expect(find.textContaining('cinta'), findsNothing);
      expect(find.textContaining('E1'), findsOneWidget);
    });
  });

  group('el contador', () {
    testWidgets('muestra de dónde viene el proyecto', (tester) async {
      await montarProyectos(tester, fuentes: [
        fuente('a/b', sesiones: 50, hechas: 47, rotas: 3, activas: 1,
            titulo: '[E5] tarea'),
      ]);
      expect(find.textContaining('47'), findsOneWidget);
      expect(find.textContaining('3'), findsWidgets);
    });

    testWidgets('sin sesiones no se muestra un contador vacío',
        (tester) async {
      await montarProyectos(tester, fuentes: [fuente('a/nuevo')]);
      expect(find.textContaining('0✓'), findsNothing);
    });
  });
}