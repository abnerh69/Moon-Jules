/// Tests de las órdenes que el teléfono envía.
///
/// Las dos reglas del formato existen porque RTDB no es una cola: sin
/// `id` no hay idempotencia y una orden puede ejecutarse dos veces; sin
/// `expires_at` una orden vieja se ejecuta cuando ya no toca.
library;

import 'dart:math';

import 'package:moonjules_core/src/model/comando.dart';
import 'package:test/test.dart';

void main() {
  final ahora = DateTime.utc(2026, 8, 25, 3, 0);

  group('formato', () {
    test('toda orden lleva id y caducidad', () {
      final json = Comando.nueva(Verbo.refrescar, ahora: ahora).aJson();
      expect(json['id'], isNotNull);
      expect(json['expires_at'], isNotNull,
          reason: 'sin caducidad la instancia la descarta');
      expect(json['verb'], 'refresh');
    });

    test('las fechas van en ISO con Z', () {
      final json = Comando.nueva(Verbo.refrescar, ahora: ahora).aJson();
      expect(json['issued_at'], '2026-08-25T03:00:00Z');
      expect(json['expires_at'], '2026-08-25T03:10:00Z');
    });

    test('sin argumentos no se manda la clave', () {
      expect(Comando.nueva(Verbo.refrescar, ahora: ahora).aJson()['args'],
          isNull);
    });

    test('con argumentos sí', () {
      final json = Comando.nueva(Verbo.nudge,
          args: {'session': '123'}, ahora: ahora).aJson();
      expect(json['args'], {'session': '123'});
    });

    test('la vida por defecto es corta', () {
      expect(kVidaComando.inMinutes, lessThanOrEqualTo(15),
          reason: 'una orden de mando a distancia envejece mal');
    });
  });

  group('identificadores', () {
    test('dos pulsaciones producen órdenes distintas', () {
      // Pulsar dos veces debe actuar dos veces: es lo que el usuario
      // espera, y el mismo id significaría lo contrario.
      final a = Comando.nueva(Verbo.nudge, ahora: ahora, aleatorio: Random(1));
      final b = Comando.nueva(Verbo.nudge, ahora: ahora, aleatorio: Random(2));
      expect(a.id, isNot(b.id));
    });

    test('el id lleva el instante, para poder ordenarlos', () {
      final c = Comando.nueva(Verbo.nudge, ahora: ahora);
      expect(c.id, startsWith('c-${ahora.millisecondsSinceEpoch}-'));
    });
  });

  group('verbos', () {
    test('los que actúan sobre una sesión la exigen', () {
      expect(Verbo.nudge.requiereSesion, isTrue);
      expect(Verbo.silenciar.requiereSesion, isTrue);
      expect(Verbo.pausar.requiereSesion, isFalse);
      expect(Verbo.refrescar.requiereSesion, isFalse);
    });

    test('no existen los verbos que cruzan la NO list', () {
      // Crear sesiones es trabajo de la GitHub Action; archivar y
      // borrar son escrituras sobre el workspace del arquitecto.
      final claves = Verbo.values.map((v) => v.clave).toSet();
      expect(claves, isNot(contains('assign_next')));
      expect(claves, isNot(contains('archive')));
      expect(claves, isNot(contains('delete')));
    });
  });

  group('acuse', () {
    test('está pendiente mientras el acuse no lleve su id', () {
      // Se deduce del contraste en vez de mantener un campo de estado
      // sincronizado entre dos procesos.
      final c = Comando.nueva(Verbo.nudge, ahora: ahora);
      expect(Resultado.pendiente(c, null), isTrue);
      final viejo = Resultado.desdeJson({'id': 'c-otro', 'status': 'done'});
      expect(Resultado.pendiente(c, viejo), isTrue);
      final suyo = Resultado.desdeJson({'id': c.id, 'status': 'done'});
      expect(Resultado.pendiente(c, suyo), isFalse);
    });

    test('los desenlaces se mapean', () {
      EstadoComando leer(String s) =>
          Resultado.desdeJson({'id': 'x', 'status': s}).estado;
      expect(leer('done'), EstadoComando.hecho);
      expect(leer('failed'), EstadoComando.fallido);
      expect(leer('expired'), EstadoComando.caducado);
      expect(leer('rejected'), EstadoComando.rechazado);
    });

    test('un desenlace desconocido queda como pendiente', () {
      expect(Resultado.desdeJson({'id': 'x', 'status': 'raro'}).estado,
          EstadoComando.pendiente);
    });

    test('el mensaje llega para poder mostrarlo', () {
      final r = Resultado.desdeJson(
          {'id': 'x', 'status': 'done', 'message': 'nudge enviado a CryptBot'});
      expect(r.mensaje, contains('CryptBot'));
    });
  });
}
