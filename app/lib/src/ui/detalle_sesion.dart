/// Detalle de una sesión. Solo mira: los botones de acción llegan
/// cuando la app lleve unos días funcionando, con el mismo criterio que
/// se aplicó a la autonomía de Moon-Jules — se gana, no se asume.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../model/panel.dart';
import '../providers.dart';

class PantallaSesion extends ConsumerWidget {
  const PantallaSesion({required this.id, super.key});

  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sesion = ref.watch(sesionProvider(id));
    return Scaffold(
      appBar: AppBar(title: const Text('Sesión')),
      body: sesion == null
          // Pasa de verdad: la sesión salió del snapshot entre que se
          // tocó la fila y se abrió la ventana.
          ? const Center(child: Text('Esta sesión ya no está en el panel'))
          : ListView(
              children: [
                ListTile(
                  title: Text(sesion.titulo ?? sesion.id),
                  subtitle: Text(sesion.repo),
                ),
                const Divider(),
                _Dato('Estado', sesion.estado),
                _Dato('Veredicto', sesion.veredicto.clave),
                _Dato('Diagnóstico', sesion.razon),
                // Dos preguntas distintas, y confundirlas es el error
                // fácil: cuánto lleva callada y cuánto lleva abierta.
                // Cuando el reloj esta congelado no hay silencio que
                // medir, y decirlo es mas util que un guion.
                _Dato(
                  'Sin señal del agente',
                  sesion.silencio == null
                      ? 'el reloj está detenido: la sesión cerró'
                      : humano(sesion.silencio),
                ),
                _Dato('Lleva abierta', humano(sesion.edad)),
                if (sesion.nudges > 0) ...[
                  const Divider(),
                  _Dato('Intentos de desatasco', '${sesion.nudges}'),
                  if (sesion.ultimoNudgeDesenlace != null)
                    _Dato('Último intento', sesion.ultimoNudgeDesenlace!),
                  if (sesion.nudgeSinRespuesta)
                    const ListTile(
                      leading: Icon(Icons.warning_amber, color: Colors.amber),
                      title: Text('El prompt de continuación no obtuvo '
                          'respuesta'),
                      subtitle: Text('Si se repite, Jules dejó de obedecerlo.'),
                    ),
                ],
                if (sesion.silenciada)
                  const ListTile(
                    leading: Icon(Icons.notifications_off),
                    title: Text('Silenciada'),
                    subtitle: Text('Sigue mal, pero ya se dio por vista.'),
                  ),
                if (sesion.url != null)
                  ListTile(
                    leading: const Icon(Icons.open_in_new),
                    title: const Text('Abrir en Jules'),
                    subtitle: Text(sesion.url!),
                  ),
              ],
            ),
    );
  }
}

class _Dato extends StatelessWidget {
  const _Dato(this.etiqueta, this.valor);

  final String etiqueta;
  final String valor;

  @override
  Widget build(BuildContext context) => ListTile(
        dense: true,
        title: Text(etiqueta, style: Theme.of(context).textTheme.labelMedium),
        subtitle: Text(valor),
      );
}
