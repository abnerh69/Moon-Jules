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
  /// Es una **propuesta**: las reglas rechazan designar una máquina cuyo
  /// latido esté caducado, así que un permiso denegado aquí significa
  /// "esa está caída", no "no tienes acceso". Merece decirse con esas
  /// palabras: el mensaje crudo de Firebase mandaría a revisar las
  /// credenciales, que es el sitio equivocado.
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
                    trailing: _trabajando == i.id
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : (control?.designada == i.id
                            ? const Icon(Icons.check, color: Colors.green)
                            : TextButton(
                                // Se deja pulsable aunque esté callada:
                                // el rechazo viene de las reglas y su
                                // mensaje explica el motivo mejor que un
                                // botón gris sin explicación.
                                onPressed: _trabajando != null
                                    ? null
                                    : () => _designar(i),
                                child: const Text('Designar'),
                              )),
                  ),
                const Padding(
                  padding: EdgeInsets.all(16),
                  child: Text(
                    'Designar es proponer: la instancia elegida confirma '
                    'escribiendo su reclamación en el siguiente ciclo. '
                    'Firebase rechaza designar una máquina cuyo latido haya '
                    'caducado.',
                  ),
                ),
              ],
            ),
    );
  }
}
