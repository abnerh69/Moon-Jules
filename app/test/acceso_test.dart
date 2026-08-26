/// Tests de la política de acceso.
///
/// Decidir si se deja entrar es exactamente lo que conviene poder
/// probar sin emulador, y donde los casos límite importan más que el
/// camino feliz.
library;

import 'package:moonjules/src/model/acceso.dart';
import 'package:test/test.dart';

void main() {
  const politica = PoliticaAcceso();
  final ahora = DateTime.utc(2026, 8, 25, 12, 0);

  EstadoAcceso evaluar({bool hay = true, DateTime? ultimo, DateTime? cuando}) =>
      politica.evaluar(
        hayCredenciales: hay,
        ultimoAcceso: ultimo,
        ahora: cuando ?? ahora,
      );

  group('camino normal', () {
    test('sin credenciales guardadas, hay que introducirlas', () {
      expect(evaluar(hay: false), EstadoAcceso.sinCredenciales);
    });

    test('sin credenciales, la marca de tiempo da igual', () {
      expect(evaluar(hay: false, ultimo: ahora), EstadoAcceso.sinCredenciales);
    });

    test('entrando hace poco, se pasa directo', () {
      expect(evaluar(ultimo: ahora.subtract(const Duration(days: 3))),
          EstadoAcceso.vigente);
    });

    test('pasada la ventana, hay que validarse', () {
      expect(evaluar(ultimo: ahora.subtract(const Duration(days: 8))),
          EstadoAcceso.caducada);
    });

    test('justo en el límite, caducada', () {
      expect(evaluar(ultimo: ahora.subtract(kVentanaAcceso)),
          EstadoAcceso.caducada);
    });

    test('un segundo antes del límite, vigente', () {
      expect(
        evaluar(
          ultimo: ahora.subtract(kVentanaAcceso - const Duration(seconds: 1)),
        ),
        EstadoAcceso.vigente,
      );
    });
  });

  group('la ventana desliza', () {
    test('entrar a los tres días empuja el vencimiento otros siete', () {
      final primerAcceso = ahora;
      final segundo = ahora.add(const Duration(days: 3));
      expect(politica.vencimiento(primerAcceso),
          ahora.add(const Duration(days: 7)));
      expect(politica.vencimiento(segundo), ahora.add(const Duration(days: 10)));
    });

    test('quien entra con regularidad no vuelve a teclear nada', () {
      var ultimo = ahora;
      for (var i = 1; i <= 10; i++) {
        final visita = ahora.add(Duration(days: i * 3));
        expect(evaluar(ultimo: ultimo, cuando: visita), EstadoAcceso.vigente);
        ultimo = visita;
      }
    });

    test('queda saber cuánto falta', () {
      final ultimo = ahora.subtract(const Duration(days: 2));
      expect(politica.restante(ultimo, ahora), const Duration(days: 5));
    });

    test('si ya venció, no queda nada', () {
      expect(politica.restante(ahora.subtract(const Duration(days: 9)), ahora),
          isNull);
    });
  });

  group('casos que abren la puerta si se descuidan', () {
    test('credenciales sin constancia de haber entrado: caducada', () {
      // No saber cuándo fue la última vez no es razón para dejar pasar.
      expect(evaluar(ultimo: null), EstadoAcceso.caducada);
    });

    test('atrasar el reloj no extiende la ventana', () {
      // Sin este caso, retrasar la hora del dispositivo dejaría el
      // acceso abierto indefinidamente.
      final marcaEnElFuturo = ahora.add(const Duration(days: 30));
      expect(evaluar(ultimo: marcaEnElFuturo), EstadoAcceso.caducada);
    });

    test('un desajuste de segundos también se rechaza', () {
      expect(evaluar(ultimo: ahora.add(const Duration(seconds: 5))),
          EstadoAcceso.caducada);
    });
  });

  group('ventana a medida', () {
    test('se puede acortar', () {
      const corta = PoliticaAcceso(ventana: Duration(hours: 1));
      expect(
        corta.evaluar(
          hayCredenciales: true,
          ultimoAcceso: ahora.subtract(const Duration(minutes: 30)),
          ahora: ahora,
        ),
        EstadoAcceso.vigente,
      );
      expect(
        corta.evaluar(
          hayCredenciales: true,
          ultimoAcceso: ahora.subtract(const Duration(hours: 2)),
          ahora: ahora,
        ),
        EstadoAcceso.caducada,
      );
    });
  });

  group('credenciales', () {
    test('se sabe si están completas', () {
      expect(const Credenciales(correo: 'a@b.c', clave: 'x').completas, isTrue);
      expect(const Credenciales(correo: '  ', clave: 'x').completas, isFalse);
      expect(const Credenciales(correo: 'a@b.c', clave: '').completas, isFalse);
    });

    test('la clave nunca se imprime', () {
      // Un toString descuidado acaba en un log, y de ahí no se borra.
      const c = Credenciales(correo: 'a@b.c', clave: 'secreto-real');
      expect(c.toString(), isNot(contains('secreto-real')));
      expect(c.toString(), contains('a@b.c'));
    });
  });
}
