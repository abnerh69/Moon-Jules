# Tests de la app

`snapshot_test.dart` y `comando_test.dart` son **Dart puro**: no
importan Flutter y cubren todo lo que puede equivocarse de verdad —el
parseo del snapshot, la caducidad del latido, el formato de las
órdenes—. Corren sin emulador y sin dispositivo.

```bash
flutter test
```

Los datos de ejemplo salen de un export real de RTDB, no de una
invención. Por eso protegen algo: la trampa principal —que Firebase
omite los nulos y una clave ausente no es un cero— se descubrió mirando
ese export.

`lib/src/data/` no tiene tests a propósito: es el pegamento con los SDK
de Firebase y no se puede ejercitar sin dispositivo. La contrapartida es
mantenerlo lo más fino posible.

La plantilla `widget_test.dart` de `flutter create` se eliminó: probaba
un contador que no existe.
