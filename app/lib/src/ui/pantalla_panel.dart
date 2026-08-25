/// Pantalla principal. Una sola, como se acordó.
///
/// Arriba las instancias: cuál vigila, cuál está en reserva, cuál calló.
/// Debajo lo que requiere atención, agrupado por repositorio.
///
/// Los widgets no deciden nada: preguntan a `panelProvider`, que resuelve
/// con la lógica de `model/panel.dart`. Si algo se ve mal aquí, el fallo
/// casi siempre está allí, donde hay tests.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../model/panel.dart';
import '../model/snapshot.dart';
import '../providers.dart';
import 'detalle_sesion.dart';
import 'detalle_relevo.dart';

class PantallaPanel extends ConsumerWidget {
  const PantallaPanel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final panel = ref.watch(panelProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Moon-Jules'),
        actions: [
          IconButton(
            tooltip: 'Relevo',
            icon: const Icon(Icons.swap_horiz),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => const PantallaRelevo(),
              ),
            ),
          ),
        ],
      ),
      body: panel.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => _Aviso(
          icono: Icons.cloud_off,
          titulo: 'No se pudo leer Firebase',
          detalle: '$e',
        ),
        data: (v) => _Contenido(vista: v),
      ),
    );
  }
}

class _Contenido extends StatelessWidget {
  const _Contenido({required this.vista});

  final VistaPanel vista;

  @override
  Widget build(BuildContext context) {
    final grupos = agruparPorRepo(vista.sesiones);
    return ListView(
      padding: const EdgeInsets.only(bottom: 24),
      children: [
        // La alerta que Moon-Jules no puede dar de sí mismo va primero.
        if (vista.nadieVigila)
          const _Aviso(
            icono: Icons.visibility_off,
            titulo: 'Nadie está vigilando',
            detalle: 'Ninguna instancia ha publicado hace rato. Los datos '
                'de abajo pueden estar rancios.',
            grave: true,
          ),
        if (vista.relevoSinConfirmar)
          _Aviso(
            icono: Icons.pending,
            titulo: 'Relevo sin confirmar',
            detalle: '${vista.control.designada} fue designada pero no ha '
                'reclamado. Probablemente esté dormida.',
          ),
        for (final i in vista.instancias) _FilaInstancia(tarjeta: i),
        const Divider(height: 24),
        if (vista.enjambre != null) _Resumen(enjambre: vista.enjambre!.enjambre),
        if (grupos.isEmpty)
          const _Aviso(
            icono: Icons.check_circle_outline,
            titulo: 'Nada que atender',
            detalle: 'Ninguna sesión requiere atención ahora mismo.',
          ),
        for (final entrada in grupos.entries) ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
            child: Text(
              entrada.key,
              style: Theme.of(context).textTheme.labelLarge,
            ),
          ),
          for (final s in entrada.value) _FilaSesion(sesion: s),
        ],
      ],
    );
  }
}

class _FilaInstancia extends StatelessWidget {
  const _FilaInstancia({required this.tarjeta});

  final TarjetaInstancia tarjeta;

  @override
  Widget build(BuildContext context) {
    final (icono, color, texto) = switch (tarjeta.salud) {
      SaludInstancia.vigilando => (
          Icons.visibility,
          Colors.green,
          'vigilando · latido hace ${humano(tarjeta.silencio)}',
        ),
      SaludInstancia.enReserva => (
          Icons.pause_circle_outline,
          Colors.blueGrey,
          'en reserva · latido hace ${humano(tarjeta.silencio)}',
        ),
      SaludInstancia.callada => (
          Icons.cloud_off,
          Colors.orange,
          'sin publicar hace ${humano(tarjeta.silencio)}',
        ),
      SaludInstancia.ilegible => (
          Icons.help_outline,
          Colors.red,
          tarjeta.error ?? 'no se pudo leer',
        ),
    };
    return ListTile(
      dense: true,
      leading: Icon(icono, color: color),
      title: Text(tarjeta.id),
      subtitle: Text(texto),
    );
  }
}

class _Resumen extends StatelessWidget {
  const _Resumen({required this.enjambre});

  final Enjambre enjambre;

  @override
  Widget build(BuildContext context) {
    final partes = <String>[
      '${enjambre.activas}/${enjambre.maxActivas} activas',
      '${enjambre.atencion} requieren atención',
      if (enjambre.silenciadas > 0) '${enjambre.silenciadas} silenciadas',
    ];
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(partes.join(' · '),
              style: Theme.of(context).textTheme.bodyMedium),
          if (enjambre.topeAlcanzado)
            const Text(
              'Tope de concurrencia alcanzado: lo nuevo se quedará en cola.',
              style: TextStyle(color: Colors.orange),
            ),
          if (enjambre.pausado)
            Text(
              'Autonomía pausada: ${enjambre.pausas.values.join(", ")}',
              style: const TextStyle(color: Colors.orange),
            ),
        ],
      ),
    );
  }
}

class _FilaSesion extends StatelessWidget {
  const _FilaSesion({required this.sesion});

  final SesionVista sesion;

  @override
  Widget build(BuildContext context) {
    final tiempo = resumenTiempo(sesion);
    return ListTile(
      dense: true,
      visualDensity: VisualDensity.compact,
      leading: Icon(
        sesion.veredicto.esCanario ? Icons.warning_amber : Icons.error_outline,
        color: sesion.veredicto.esCanario ? Colors.amber : Colors.redAccent,
      ),
      // Una linea. Con nueve entradas, un titulo de dos empuja el motivo
      // fuera de la pantalla y obliga a desplazarse para leer poco.
      title: Text(
        sesion.titulo ?? sesion.id,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      // El tiempo va aqui y no en una columna aparte: etiquetado cabe, y
      // sin etiqueta se confundiria "muda" con "abierta".
      subtitle: Text(
        tiempo.isEmpty
            ? resumenMotivo(sesion)
            : '$tiempo · ${resumenMotivo(sesion)}',
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: const Icon(Icons.chevron_right, size: 18),
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => PantallaSesion(id: sesion.id),
        ),
      ),
    );
  }
}

class _Aviso extends StatelessWidget {
  const _Aviso({
    required this.icono,
    required this.titulo,
    required this.detalle,
    this.grave = false,
  });

  final IconData icono;
  final String titulo;
  final String detalle;
  final bool grave;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.fromLTRB(12, 12, 12, 0),
      color: grave ? Colors.red.shade900 : null,
      child: ListTile(
        leading: Icon(icono),
        title: Text(titulo),
        subtitle: Text(detalle),
      ),
    );
  }
}
