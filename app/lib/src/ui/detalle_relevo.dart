/// Detalle del relevo. En esta versión solo mira.
///
/// La pantalla muestra **deseado y real por separado** a propósito. Es
/// la distinción que sostiene todo el mecanismo: designar es proponer, y
/// hasta que la instancia elegida escribe su reclamación no ha recogido
/// nada. Mostrar solo la designación haría pasar por vigilante a una
/// máquina dormida.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../model/panel.dart';
import '../providers.dart';

class PantallaRelevo extends ConsumerWidget {
  const PantallaRelevo({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final panel = ref.watch(panelProvider).valueOrNull;
    final control = panel?.control;
    return Scaffold(
      appBar: AppBar(title: const Text('Relevo')),
      body: panel == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              children: [
                ListTile(
                  title: const Text('Designada'),
                  subtitle: Text(control?.designada ?? '(ninguna)'),
                ),
                ListTile(
                  title: const Text('Ha reclamado'),
                  subtitle: Text(control?.reclamadaPor ?? '(nadie)'),
                ),
                if (control?.designacionSinRecoger ?? false)
                  const Card(
                    margin: EdgeInsets.all(12),
                    child: ListTile(
                      leading: Icon(Icons.pending, color: Colors.orange),
                      title: Text('Nadie ha recogido el encargo'),
                      subtitle: Text('Si no lo hace en un par de ciclos, esa '
                          'máquina está apagada.'),
                    ),
                  ),
                if (!(control?.conocido ?? true))
                  const Card(
                    margin: EdgeInsets.all(12),
                    child: ListTile(
                      leading: Icon(Icons.help_outline),
                      title: Text('La instancia no pudo leer el control'),
                      subtitle: Text('Pasa a reserva por seguridad: prefiere '
                          'no actuar antes que actuar de más.'),
                    ),
                  ),
                const Divider(),
                for (final i in panel.instancias)
                  ListTile(
                    leading: Icon(
                      i.salud == SaludInstancia.callada
                          ? Icons.cloud_off
                          : Icons.computer,
                    ),
                    title: Text(i.id),
                    subtitle: Text(
                      i.salud == SaludInstancia.callada
                          ? 'callada hace ${humano(i.silencio)} — no se puede '
                              'designar'
                          : 'latido hace ${humano(i.silencio)}',
                    ),
                  ),
                const Padding(
                  padding: EdgeInsets.all(16),
                  child: Text(
                    'Cambiar la instancia habilitada llegará en la siguiente '
                    'versión. Por ahora, desde la terminal: '
                    'moon-jules relay <instancia>',
                  ),
                ),
              ],
            ),
    );
  }
}
