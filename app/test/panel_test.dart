/// Tests de la lógica de presentación.
///
/// Qué se ve primero y qué significa cada estado son decisiones que
/// pueden equivocarse. Viven en Dart puro para poder probarlas sin
/// emulador, y los widgets solo dibujan lo que estas funciones deciden.
library;

import 'package:moonjules/src/model/lectura.dart';
import 'package:moonjules/src/model/panel.dart';
import 'package:moonjules/src/model/snapshot.dart';
import 'package:test/test.dart';

import 'snapshot_test.dart' show snapshotReal, fallidaReal, vivaReal;

final ahora = DateTime.utc(2026, 8, 25, 3, 10);
final publicado = ahora.subtract(const Duration(minutes: 2));
final rancio = ahora.subtract(const Duration(hours: 3));

LecturaInstancia leer(String id,
    {DateTime? cuando, String rol = 'active', List<Object?>? sesiones}) {
  final crudo = snapshotReal(
    latidoMs: (cuando ?? publicado).millisecondsSinceEpoch,
    sesiones: sesiones,
  );
  (crudo['instance']! as Map<String, Object?>)
    ..['id'] = id
    ..['role'] = rol;
  return LecturaInstancia.ok(id, Snapshot.desdeJson(crudo));
}

Control get sinDesignar => Control.desdeJson({'known': true});

void main() {
  group('salud de cada instancia', () {
    test('la que publica y manda está vigilando', () {
      final p = construirPanel([leer('la-dorada')], sinDesignar, ahora);
      expect(p.instancias.single.salud, SaludInstancia.vigilando);
      expect(p.instancias.single.preocupa, isFalse);
    });

    test('la que publica y no manda está en reserva, no caída', () {
      // Distinción que importa: una reserva está viva y disponible para
      // el relevo, y pintarla como problema sería mentir.
      final p = construirPanel(
          [leer('boston', rol: 'standby')], sinDesignar, ahora);
      expect(p.instancias.single.salud, SaludInstancia.enReserva);
      expect(p.instancias.single.preocupa, isFalse);
    });

    test('la que dejó de publicar está callada', () {
      final p = construirPanel([leer('sao-paulo', cuando: rancio)],
          sinDesignar, ahora);
      expect(p.instancias.single.salud, SaludInstancia.callada);
      expect(p.instancias.single.silencio, const Duration(hours: 3));
    });

    test('un snapshot ilegible no tumba a las demás', () {
      // Si una máquina publica una versión que esta app no entiende,
      // las otras dos deben seguir viéndose.
      final p = construirPanel([
        const LecturaInstancia.fallida('rara', 'esquema 99'),
        leer('la-dorada'),
      ], sinDesignar, ahora);
      expect(p.instancias, hasLength(2));
      expect(p.deQuienLeemos?.id, 'la-dorada');
      expect(p.instancias.firstWhere((i) => i.id == 'rara').error,
          contains('99'));
    });
  });

  group('de quién se leen los datos', () {
    test('se prefiere la que vigila', () {
      final p = construirPanel([
        leer('boston', rol: 'standby'),
        leer('la-dorada'),
      ], sinDesignar, ahora);
      expect(p.deQuienLeemos?.id, 'la-dorada');
    });

    test('si la que vigila calló, sirve una reserva viva', () {
      // Todas ven el mismo Jules: quedarse sin datos porque la
      // habilitada se durmió sería absurdo.
      final p = construirPanel([
        leer('la-dorada', cuando: rancio),
        leer('boston', rol: 'standby'),
      ], sinDesignar, ahora);
      expect(p.deQuienLeemos?.id, 'boston');
      expect(p.enjambre, isNotNull);
    });

    test('todas calladas: se muestra la menos rancia, etiquetada', () {
      // Datos viejos y marcados como tales son mejores que una pantalla
      // en blanco, siempre que el aviso de que nadie vigila esté.
      final p = construirPanel([
        leer('vieja', cuando: ahora.subtract(const Duration(hours: 9))),
        leer('menos-vieja', cuando: rancio),
      ], sinDesignar, ahora);
      expect(p.deQuienLeemos?.id, 'menos-vieja');
      expect(p.nadieVigila, isTrue);
    });

    test('sin ninguna instancia, nadie vigila', () {
      final p = construirPanel([], sinDesignar, ahora);
      expect(p.nadieVigila, isTrue);
      expect(p.enjambre, isNull);
      expect(p.sesiones, isEmpty);
    });
  });

  group('orden', () {
    test('lo que preocupa va arriba', () {
      final p = construirPanel([
        leer('sana', rol: 'standby'),
        leer('muda', cuando: rancio),
      ], sinDesignar, ahora);
      expect(p.instancias.first.id, 'muda');
    });

    test('dentro del mismo grupo, por nombre', () {
      // La posición de una instancia no debe bailar entre ciclos.
      final p = construirPanel([
        leer('zulu', rol: 'standby'),
        leer('alfa', rol: 'standby'),
      ], sinDesignar, ahora);
      expect(p.instancias.map((i) => i.id), ['alfa', 'zulu']);
    });

    test('el canario va primero, por encima del más mudo', () {
      // Un nudge sin respuesta significa que el prompt dejó de
      // funcionar, y eso importa más que cualquier sesión suelta.
      final canario = {...fallidaReal, 'verdict': 'nudge_unanswered',
        'silence_s': 60, 'id': 'canario'};
      final muyMuda = {...fallidaReal, 'silence_s': 999999, 'id': 'muda'};
      final orden = ordenarPorUrgencia([
        SesionVista.desdeJson(muyMuda),
        SesionVista.desdeJson(canario),
      ]);
      expect(orden.first.id, 'canario');
    });

    test('a igualdad, la más muda primero', () {
      final a = {...fallidaReal, 'silence_s': 100, 'id': 'poco'};
      final b = {...fallidaReal, 'silence_s': 9000, 'id': 'mucho'};
      final orden = ordenarPorUrgencia(
          [SesionVista.desdeJson(a), SesionVista.desdeJson(b)]);
      expect(orden.first.id, 'mucho');
    });

    test('se agrupan por repositorio', () {
      final grupos = agruparPorRepo([
        SesionVista.desdeJson(fallidaReal),
        SesionVista.desdeJson(vivaReal),
      ]);
      expect(grupos.keys, containsAll(
          ['Informatica-ASHware/3AL-Inventario', 'abnerh69/ppp-n-kits']));
    });
  });

  group('alertas', () {
    test('suma problemas, instancias calladas y relevo sin confirmar', () {
      final p = construirPanel([
        leer('la-dorada'),
        leer('sao-paulo', cuando: rancio),
      ], Control.desdeJson({'desired': 'boston', 'known': true}), ahora);
      // 8 del export real + 1 callada + 1 designación sin recoger.
      expect(p.alertas, 10);
    });

    test('sin nada raro, solo los problemas del enjambre', () {
      final p = construirPanel([leer('la-dorada')], sinDesignar, ahora);
      expect(p.alertas, 8);
      expect(p.relevoSinConfirmar, isFalse);
    });

    test('una designación sin recoger se detecta', () {
      final p = construirPanel([leer('la-dorada')],
          Control.desdeJson({'desired': 'sao-paulo', 'known': true}), ahora);
      expect(p.relevoSinConfirmar, isTrue);
    });
  });

  group('duraciones', () {
    test('se leen a la escala correcta', () {
      expect(humano(null), '—');
      expect(humano(const Duration(seconds: 26)), '26 s');
      expect(humano(const Duration(minutes: 52)), '52 min');
      expect(humano(const Duration(hours: 3)), '3 h');
      expect(humano(const Duration(days: 151)), '151 d');
    });

    test('nada se reporta en miles de minutos', () {
      // La CLI ya cometió ese error: `144270 min` no le dice nada a
      // nadie.
      expect(humano(const Duration(days: 100)), '100 d');
    });
  });

  group('qué tiempo se muestra en la lista', () {
    test('si se sabe cuánto lleva muda, eso', () {
      expect(resumenTiempo(SesionVista.desdeJson(vivaReal)), 'muda 2 min');
    });

    test('si el reloj está congelado, la edad, y etiquetada', () {
      // Encontrado en la primera captura: las fallidas mostraban un
      // guion, que es correcto pero no comunica nada. La edad sí se
      // conoce y para una sesión muerta hace meses es lo que interesa.
      final s = SesionVista.desdeJson(fallidaReal);
      expect(s.silencio, isNull);
      expect(resumenTiempo(s), 'abierta 102 d');
    });

    test('las etiquetas distinguen dos preguntas distintas', () {
      // Una sesión puede llevar tres horas abierta y treinta segundos
      // muda: sin nombre, la misma columna las haría pasar por lo mismo.
      final joven = {...vivaReal, 'silence_s': 30, 'age_s': 10800};
      expect(resumenTiempo(SesionVista.desdeJson(joven)), 'muda 30 s');
    });

    test('sin ninguno de los dos, cadena vacía y no un guion suelto', () {
      final pelada = SesionVista.desdeJson({'id': 'x', 'repo': 'a/b'});
      expect(resumenTiempo(pelada), '');
    });
  });
}
