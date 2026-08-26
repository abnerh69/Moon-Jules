/// Pantalla de acceso. Dos modos según lo que haya guardado.
///
/// La contraseña **nunca viaja en el binario**. Antes se inyectaba con
/// `--dart-define` y quedaba compilada dentro del APK, recuperable por
/// cualquiera que lo tuviera. Ahora se teclea una vez y vive en el
/// almacén seguro del sistema.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../acceso_notifier.dart';
import '../model/acceso.dart';

class PantallaAcceso extends ConsumerStatefulWidget {
  const PantallaAcceso({required this.sesion, super.key});

  final SesionApp sesion;

  @override
  ConsumerState<PantallaAcceso> createState() => _PantallaAccesoState();
}

class _PantallaAccesoState extends ConsumerState<PantallaAcceso> {
  late final TextEditingController _correo =
      TextEditingController(text: widget.sesion.correo ?? '');
  final _clave = TextEditingController();
  bool _biometriaDisponible = false;
  bool _ocupado = false;

  @override
  void initState() {
    super.initState();
    _mirarBiometria();
  }

  Future<void> _mirarBiometria() async {
    // Solo tiene sentido ofrecerla si ya hay credenciales guardadas: la
    // huella las desbloquea, no las sustituye.
    if (widget.sesion.estado != EstadoAcceso.caducada) return;
    final hay = await ref.read(accesoProvider.notifier).hayBiometria();
    if (mounted) setState(() => _biometriaDisponible = hay);
  }

  @override
  void dispose() {
    _correo.dispose();
    _clave.dispose();
    super.dispose();
  }

  Future<void> _entrar() async {
    setState(() => _ocupado = true);
    await ref.read(accesoProvider.notifier).entrarCon(
          Credenciales(correo: _correo.text, clave: _clave.text),
        );
    if (mounted) setState(() => _ocupado = false);
  }

  @override
  Widget build(BuildContext context) {
    final caducada = widget.sesion.estado == EstadoAcceso.caducada;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.nightlight_round, size: 56),
                const SizedBox(height: 12),
                Text('Moon Jules',
                    style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 8),
                Text(
                  caducada
                      ? 'Hace días que no entras: vuelve a validarte.'
                      : 'Entra con tu cuenta de Firebase.',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 24),
                if (_biometriaDisponible) ...[
                  FilledButton.icon(
                    onPressed: _ocupado
                        ? null
                        : () => ref
                            .read(accesoProvider.notifier)
                            .desbloquearConBiometria(),
                    icon: const Icon(Icons.fingerprint),
                    label: const Text('Desbloquear'),
                  ),
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 16),
                    child: Text('o con la contraseña'),
                  ),
                ],
                TextField(
                  controller: _correo,
                  enabled: !caducada,
                  keyboardType: TextInputType.emailAddress,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: 'Correo',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _clave,
                  obscureText: true,
                  onSubmitted: (_) => _entrar(),
                  decoration: const InputDecoration(
                    labelText: 'Contraseña',
                    border: OutlineInputBorder(),
                  ),
                ),
                if (widget.sesion.error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(
                      widget.sesion.error!,
                      style: TextStyle(color: Theme.of(context).colorScheme.error),
                      textAlign: TextAlign.center,
                    ),
                  ),
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: _ocupado ? null : _entrar,
                  child: _ocupado
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Entrar'),
                ),
                if (caducada)
                  TextButton(
                    onPressed: () => ref.read(accesoProvider.notifier).salir(),
                    child: const Text('Usar otra cuenta'),
                  ),
                const SizedBox(height: 24),
                Text(
                  'El acceso dura ${kVentanaAcceso.inDays} días y se renueva '
                  'cada vez que entras.',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
