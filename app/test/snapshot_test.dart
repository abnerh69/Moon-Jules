/// Tests del modelo del snapshot.
///
/// Los datos de ejemplo salen del export real de RTDB, no de una
/// invención: eso es lo que hace que estos tests protejan algo. La
/// trampa principal —que Firebase omite los valores nulos y una clave
/// ausente no es un cero— se descubrió mirando precisamente ese export.
library;

import 'package:moonjules_core/src/model/snapshot.dart';
import 'package:test/test.dart';

/// Fragmento fiel del export: una sesión fallida **no trae**
/// `silence_s`, ni `last_nudge_at`, ni `last_nudge_outcome`.
Map<String, Object?> get fallidaReal => {
      'acked': false,
      'age_s': 8882538,
      'id': '8702125925276955183',
      'needs_attention': true,
      'nudges': 0,
      'reason': 'sesion fallida: Jules was unable to complete the task.',
      'repo': 'Informatica-ASHware/3AL-Inventario',
      'started_at': '2026-05-14T07:45:49.028954Z',
      'state': 'FAILED',
      'title': '[E02-017] Validación end-to-end de la épica',
      'url': 'https://jules.google.com/session/8702125925276955183',
      'verdict': 'failed',
    };

Map<String, Object?> get vivaReal => {
      'acked': false,
      'age_s': 2605,
      'id': '4954617217501385202',
      'needs_attention': false,
      'nudges': 0,
      'reason': 'activa, ultimo latido 132s',
      'repo': 'abnerh69/ppp-n-kits',
      'silence_s': 132,
      'started_at': '2026-08-25T02:24:41.746428Z',
      'state': 'IN_PROGRESS',
      'title': 'Ejecuta el sistema de auditorías',
      'verdict': 'healthy',
    };

Map<String, Object?> snapshotReal({
  int latidoMs = 1787627286702,
  Object? control,
  List<Object?>? sesiones,
}) =>
    {
      'schema': 3,
      'instance': {
        'cycle_interval_s': 300,
        'heartbeat_ms': latidoMs,
        'id': 'la-dorada',
        'mode': 'read_only',
        'published_at': '2026-08-25T03:08:06.702617Z',
        'role': 'standby',
        'stale_after_s': 1200,
        'version': '0.13.1',
      },
      // Tal como llega: el resto de claves no existen porque eran nulas.
      'control': control ?? {'known': true},
      'sessions': sesiones ?? [fallidaReal, vivaReal],
      'swarm': {
        'acked': 8,
        'active': 10,
        'attention': 8,
        'max_active': 15,
        'sessions_total': 539,
      },
    };

DateTime enMs(int ms) => DateTime.fromMillisecondsSinceEpoch(ms, isUtc: true);

void main() {
  group('claves ausentes', () {
    test('una clave que no está nunca vale cero', () {
      final s = SesionVista.desdeJson(fallidaReal);
      expect(s.silencio, isNull,
          reason: 'ausente significa reloj congelado, no "muda hace 0 s"');
      expect(s.ultimoNudgeEn, isNull);
      expect(s.ultimoNudgeDesenlace, isNull);
      // La edad sí se conoce: son preguntas distintas.
      expect(s.edad, const Duration(seconds: 8882538));
    });

    test('lo que sí llega se lee bien', () {
      final s = SesionVista.desdeJson(vivaReal);
      expect(s.silencio, const Duration(seconds: 132));
      expect(s.veredicto, Veredicto.healthy);
      expect(s.repo, 'abnerh69/ppp-n-kits');
      expect(s.estaViva, isTrue);
    });

    test('un control sin designar llega solo con known', () {
      final c = Control.desdeJson({'known': true});
      expect(c.designada, isNull);
      expect(c.reclamadaPor, isNull);
      expect(c.designacionSinRecoger, isFalse,
          reason: 'nadie designado no es una designación sin recoger');
    });

    test('un enjambre sin pausas no trae la clave', () {
      final e = Enjambre.desdeJson({'attention': 8, 'active': 10});
      expect(e.pausado, isFalse);
      expect(e.pausas, isEmpty);
    });
  });

  group('esquema', () {
    test('se acepta el que la app entiende', () {
      expect(Snapshot.desdeJson(snapshotReal()).esquema, kEsquemaSoportado);
    });

    test('se rechaza uno desconocido en vez de interpretarlo a medias', () {
      final futuro = snapshotReal()..['schema'] = 99;
      expect(() => Snapshot.desdeJson(futuro),
          throwsA(isA<EsquemaIncompatible>()));
    });

    test('el error dice qué hacer', () {
      expect(const EsquemaIncompatible(99, 3).toString(),
          allOf(contains('99'), contains('Actualiza')));
    });

    test('sin esquema tampoco se adivina', () {
      expect(() => Snapshot.desdeJson({'instance': <String, Object?>{}}),
          throwsA(isA<EsquemaIncompatible>()));
    });
  });

  group('latido', () {
    final publicado = enMs(1787627286702);

    test('recién publicado no está caducado', () {
      final i = Snapshot.desdeJson(snapshotReal()).instancia;
      expect(i.caducada(publicado.add(const Duration(minutes: 5))), isFalse);
    });

    test('pasado el umbral del propio snapshot, caducado', () {
      final i = Snapshot.desdeJson(snapshotReal()).instancia;
      expect(i.caducaTras, const Duration(seconds: 1200));
      expect(i.caducada(publicado.add(const Duration(minutes: 21))), isTrue);
    });

    test('sin latido conocido se da por caída', () {
      // Una máquina muerta no puede avisar de que lo está: solo puede
      // dejar de hablar. Ante la duda, silencio.
      final i = Instancia.desdeJson({'id': 'x'});
      expect(i.caducada(DateTime.now().toUtc()), isTrue);
      expect(i.silencioEn(DateTime.now().toUtc()), isNull);
    });

    test('el umbral viaja en el dato, no codificado aquí', () {
      final otro = snapshotReal();
      (otro['instance']! as Map<String, Object?>)['stale_after_s'] = 3600;
      expect(Snapshot.desdeJson(otro).instancia.caducaTras,
          const Duration(hours: 1));
    });

    test('el papel se lee del snapshot', () {
      expect(Snapshot.desdeJson(snapshotReal()).instancia.esActiva, isFalse,
          reason: 'el export real venía en standby');
    });
  });

  group('veredictos', () {
    test('uno desconocido no tumba la app', () {
      // Moon-Jules puede añadir veredictos; caerse por eso sería peor
      // que mostrar "desconocido".
      expect(Veredicto.desde('algo_del_futuro'), Veredicto.desconocido);
      expect(Veredicto.desde(null), Veredicto.desconocido);
      expect(Veredicto.desde(42), Veredicto.desconocido);
    });

    test('los conocidos se mapean', () {
      expect(Veredicto.desde('paused_done'), Veredicto.pausedDone);
      expect(Veredicto.desde('nudge_unanswered'), Veredicto.nudgeUnanswered);
    });

    test('el canario está identificado', () {
      expect(Veredicto.nudgeUnanswered.esCanario, isTrue);
      expect(Veredicto.stalled.esCanario, isFalse);
    });
  });

  group('relevo', () {
    test('designar una máquina que no recogió el encargo se distingue', () {
      // El caso que justifica separar deseado de real: sin este
      // contraste, una designación se mostraría como hecho consumado
      // aunque ese portátil estuviera dormido.
      final c = Control.desdeJson({'desired': 'sao-paulo', 'known': true});
      expect(c.designacionSinRecoger, isTrue);
    });

    test('recogido por quien tocaba no alarma', () {
      final c = Control.desdeJson(
          {'desired': 'la-dorada', 'claimed_by': 'la-dorada', 'known': true});
      expect(c.designacionSinRecoger, isFalse);
    });

    test('un control ilegible se marca', () {
      expect(Control.desdeJson({'known': false}).conocido, isFalse);
    });
  });

  group('snapshot completo', () {
    test('reproduce el export real', () {
      final s = Snapshot.desdeJson(snapshotReal());
      expect(s.sesiones, hasLength(2));
      expect(s.enjambre.total, 539);
      expect(s.enjambre.atencion, 8);
      expect(s.enjambre.silenciadas, 8);
      expect(s.enjambre.topeAlcanzado, isFalse, reason: '10 de 15');
      expect(s.requierenAtencion, hasLength(1));
      expect(s.vivas.single.repo, 'abnerh69/ppp-n-kits');
    });

    test('sin sesiones no revienta', () {
      final s = Snapshot.desdeJson(snapshotReal(sesiones: []));
      expect(s.sesiones, isEmpty);
      expect(s.requierenAtencion, isEmpty);
    });

    test('el badge suma los problemas y el silencio de la instancia', () {
      final s = Snapshot.desdeJson(snapshotReal());
      final reciente = enMs(1787627286702).add(const Duration(minutes: 1));
      final tarde = enMs(1787627286702).add(const Duration(hours: 2));
      expect(s.alertasEn(reciente), 8);
      expect(s.alertasEn(tarde), 9, reason: 'nadie está mirando cuenta como alerta');
    });

    test('el tope de concurrencia se detecta', () {
      final lleno = snapshotReal();
      (lleno['swarm']! as Map<String, Object?>)['active'] = 15;
      expect(Snapshot.desdeJson(lleno).enjambre.topeAlcanzado, isTrue);
    });
  });
}
