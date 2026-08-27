/// Detalle de un repositorio: sus sesiones y en qué anda.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../model/panel.dart';
import '../model/snapshot.dart';
import '../providers.dart';
import 'detalle_sesion.dart';

class DetalleRepositorio extends ConsumerWidget {
  const DetalleRepositorio({required this.clave, super.key});

  final String clave;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final panel = ref.watch(panelProvider).valueOrNull;
    final fuentes = panel?.enjambre?.fuentes ?? const <ResumenSource>[];
    final fuente = fuentes.where((f) => f.clave == clave).firstOrNull;
    final archivados =
        ref.watch(archivadosProvider).valueOrNull ?? const <String>{};

    if (fuente == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Repositorio')),
        body: const Center(child: Text('Este repositorio ya no está')),
      );
    }

    // Las sesiones publicadas de este repositorio. Solo llegan las
    // problemáticas y las vivas: el resumen de arriba cuenta todas.
    final suyas = (panel?.enjambre?.sesiones ?? const <SesionVista>[])
        .where((s) => s.repo == fuente.repo)
        .toList();
    final estaArchivado = archivados.contains(clave);

    return Scaffold(
      appBar: AppBar(
        title: Text(fuente.repo, style: const TextStyle(fontSize: 16)),
        actions: [
          IconButton(
            tooltip: estaArchivado ? 'Sacar del archivo' : 'Archivar',
            icon: Icon(estaArchivado
                ? Icons.unarchive_outlined
                : Icons.archive_outlined),
            onPressed: () => ref
                .read(repositorioProvider)
                .archivar(clave, si: !estaArchivado),
          ),
        ],
      ),
      body: ListView(
        children: [
          if (estaArchivado)
            const Card(
              margin: EdgeInsets.all(12),
              child: ListTile(
                leading: Icon(Icons.inventory_2_outlined),
                title: Text('Archivado'),
                subtitle: Text('No aparece en la lista, pero Moon-Jules lo '
                    'sigue vigilando y reactivando igual.'),
              ),
            ),
          _Dato('Sesiones', '${fuente.sesiones}'),
          _Dato('Completadas', '${fuente.hechas}'),
          if (fuente.rotas > 0) _Dato('Fallidas', '${fuente.rotas}'),
          _Dato('Trabajando ahora', '${fuente.activas}'),
          _Dato('Requieren atención', '${fuente.atencion}'),
          _Dato('Última señal', fechaCorta(fuente.ultimaSenal)),
          if (fuente.cintaParada)
            Card(
              margin: const EdgeInsets.all(12),
              color: Colors.amber.shade900,
              child: ListTile(
                leading: const Icon(Icons.pause_circle_filled),
                title: const Text('La cinta no avanza'),
                subtitle: Text(
                  '${fuente.motivoCinta ?? ""}\n\n'
                  'Algo terminó y no arrancó nada después. O la Action '
                  'no fusionó, o no quedan issues en la cola.',
                ),
              ),
            ),
          if (fuente.callado)
            const Card(
              margin: EdgeInsets.all(12),
              child: ListTile(
                leading: Icon(Icons.help_outline, color: Colors.orange),
                title: Text('Sin ninguna sesión'),
                subtitle: Text('Puede que la cadena se haya roto: si un PR '
                    'entra en conflicto, la Action aborta y la cola de este '
                    'repositorio se queda parada.'),
              ),
            ),
          if (fuente.actual != null) ...[
            const Divider(),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
              child: Text('Tarea actual',
                  style: Theme.of(context).textTheme.labelLarge),
            ),
            _Tarea(tarea: fuente.actual!),
          ],
          if (suyas.isNotEmpty) ...[
            const Divider(),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
              child: Text('Sesiones publicadas',
                  style: Theme.of(context).textTheme.labelLarge),
            ),
            for (final s in ordenarPorUrgencia(suyas))
              ListTile(
                dense: true,
                title: Text(s.titulo ?? s.id,
                    maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text('${resumenTiempo(s)} · ${s.veredicto.clave}',
                    maxLines: 1, overflow: TextOverflow.ellipsis),
                trailing: const Icon(Icons.chevron_right, size: 18),
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => PantallaSesion(id: s.id),
                  ),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _Tarea extends StatelessWidget {
  const _Tarea({required this.tarea});

  final TareaActual tarea;

  @override
  Widget build(BuildContext context) {
    final referencia = referenciaDe(tarea.titulo);
    return ListTile(
      title: Text(tituloSinReferencia(tarea.titulo)),
      subtitle: Text('${tarea.estado} · ${tarea.veredicto.clave}'),
      leading: referencia == null
          ? const Icon(Icons.task_outlined)
          : Chip(
              label: Text(referencia, style: const TextStyle(fontSize: 11)),
              visualDensity: VisualDensity.compact,
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
