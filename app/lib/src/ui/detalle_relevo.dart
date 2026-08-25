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

class PantallaRelevo extends ConsumerStatefulWidget {
  const PantallaRelevo({super.key});

  @override
  ConsumerState<PantallaRelevo> createState() => _PantallaRelevoState();
}

class _PantallaRelevoState extends ConsumerState<PantallaRelevo> {
  String? _trabajando;

  /// Designa una instancia.
  ///
  /// Es una **propuesta**: la elegida confirma en su siguiente ciclo. El
  /// botón solo se ofrece cuando puede funcionar, pero las reglas de
  /// Firebase siguen validando por su cuenta —que la app no lo ofrezca
  /// está bien; que no pueda aunque tenga un fallo, es mejor—, así que
  /// el rechazo también se traduce.
  Future<void> _designar(TarjetaInstancia destino) async {
    setState(() => _trabajando = destino.id);
    String? error;
    try {
      await ref.read(repositorioProvider).designar(destino.id);
    } on Object catch (e) {
      error = destino.salud == SaludInstancia.callada
          ? '${destino.id} lleva sin publicar ${humano(destino.silencio)}: '
              'Firebase no deja designar una máquina caída.'
          : 'No se pudo designar: $e';
    }
    if (!mounted) return;
    setState(() => _trabajando = null);
    if (error != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error)));
    }
  }

  /// Qué se ofrece a la derecha de cada instancia.
  ///
  /// No se ofrece lo que no puede funcionar: pulsar y recibir un rechazo
  /// es una acción fallida que la interfaz permitió. El motivo va justo
  /// debajo, en el subtítulo, para que el botón apagado no quede mudo.
  Widget _accion(VistaPanel panel, TarjetaInstancia i) {
    if (_trabajando == i.id) {
      return const SizedBox(
        width: 20,
        height: 20,
        child: CircularProgressIndicator(strokeWidth: 2),
      );
    }
    if (panel.control.designada == i.id) {
      return const Icon(Icons.check, color: Colors.green);
    }
    return TextButton(
      onPressed: (_trabajando != null || !panel.designable(i))
          ? null
          : () => _designar(i),
      child: const Text('Designar'),
    );
  }

  @override
  Widget build(BuildContext context) {
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
                if (panel.ningunaDesignable)
                  Card(
                    margin: const EdgeInsets.all(12),
                    child: ListTile(
                      leading: const Icon(Icons.block),
                      title: const Text('No hay a quién designar'),
                      subtitle: Text(
                        panel.conectado
                            ? 'Ninguna instancia está publicando. Hasta que '
                                'alguna vuelva, no se puede cambiar el relevo.'
                            : 'Sin conexión no se puede cambiar el relevo.',
                      ),
                    ),
                  ),
                for (final i in panel.instancias)
                  ListTile(
                    leading: Icon(
                      i.salud == SaludInstancia.callada
                          ? Icons.cloud_off
                          : Icons.computer,
                    ),
                    title: Text(i.id),
                    subtitle: Text(
                      panel.motivoNoDesignable(i) == null
                          ? 'latido hace ${humano(i.silencio)}'
                          : '${panel.motivoNoDesignable(i)} — no se puede '
                              'designar',
                    ),
                    trailing: _accion(panel, i),
                  ),
                const Padding(
                  padding: EdgeInsets.all(16),
                  child: Text(
                    'Designar es proponer: la instancia elegida confirma '
                    'escribiendo su reclamación en el siguiente ciclo. Solo '
                    'se ofrece designar a las que están publicando, y '
                    'Firebase lo valida además por su cuenta.',
                  ),
                ),
              ],
            ),
    );
  }
}
