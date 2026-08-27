/// Vista por repositorio: en qué trabaja cada proyecto.
///
/// Responde a una pregunta distinta que la lista de sesiones. Aquella
/// dice «¿qué tengo que atender?»; esta dice «¿cómo va el enjambre?», y
/// para eso hacen falta también los repositorios que van bien.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../model/panel.dart';
import '../model/snapshot.dart';
import '../providers.dart';
import 'detalle_repositorio.dart';

class VistaProyectos extends ConsumerWidget {
  const VistaProyectos({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final visibles = ref.watch(proyectosProvider);
    final archivados = ref.watch(proyectosArchivadosProvider);

    if (visibles.isEmpty && archivados.isEmpty) {
      return const Center(child: Text('Todavía no hay repositorios'));
    }
    return ListView(
      padding: const EdgeInsets.only(bottom: 24),
      children: [
        for (final p in visibles) FilaProyecto(fuente: p),
        if (archivados.isNotEmpty)
          ExpansionTile(
            leading: const Icon(Icons.inventory_2_outlined, size: 20),
            title: Text('${archivados.length} archivados'),
            subtitle: const Text('Se siguen vigilando; solo no se listan'),
            children: [
              for (final p in archivados) FilaProyecto(fuente: p, archivado: true),
            ],
          ),
      ],
    );
  }
}

class FilaProyecto extends ConsumerWidget {
  const FilaProyecto({required this.fuente, this.archivado = false, super.key});

  final ResumenSource fuente;
  final bool archivado;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final act = fuente.actual;
    final ref_ = referenciaDe(act?.titulo);
    return ListTile(
      dense: true,
      leading: _Semaforo(fuente: fuente, apagado: archivado),
      title: Row(
        children: [
          Expanded(
            child: Text(fuente.repo,
                maxLines: 1, overflow: TextOverflow.ellipsis),
          ),
          if (fuente.sesiones > 0)
            Text(
              '${fuente.hechas}✓'
              '${fuente.rotas > 0 ? '  ${fuente.rotas}✗' : ''}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
        ],
      ),
      subtitle: Text(
        _subtitulo(fuente, ref_),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: IconButton(
        tooltip: archivado ? 'Sacar del archivo' : 'Archivar',
        icon: Icon(
          archivado ? Icons.unarchive_outlined : Icons.archive_outlined,
          size: 20,
        ),
        onPressed: () => ref
            .read(repositorioProvider)
            .archivar(fuente.clave, si: !archivado),
      ),
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => DetalleRepositorio(clave: fuente.clave),
        ),
      ),
    );
  }

  static String _subtitulo(ResumenSource f, String? referencia) {
    // Lo que no se ve por ningún otro sitio va primero.
    if (f.cintaParada) return f.motivoCinta ?? 'la cinta no avanza';
    if (f.callado) return 'sin sesiones';
    final act = f.actual;
    if (act == null) return '${f.sesiones} sesiones';
    // La referencia primero: es lo que identifica la tarea de un
    // vistazo, y el título completo no cabe en una línea.
    final cuerpo = tituloSinReferencia(act.titulo);
    return referencia == null ? cuerpo : '$referencia · $cuerpo';
  }
}

/// Estado del repositorio, de un vistazo.
class _Semaforo extends StatelessWidget {
  const _Semaforo({required this.fuente, this.apagado = false});

  final ResumenSource fuente;
  final bool apagado;

  @override
  Widget build(BuildContext context) {
    final (icono, color) = switch (fuente) {
      final f when f.preocupa => (Icons.error_outline, Colors.redAccent),
      // La cinta parada es el fallo silencioso: algo terminó y no
      // arrancó nada. Sin esto, un proyecto muerto se ve igual que uno
      // que va bien.
      final f when f.cintaParada => (Icons.pause_circle_filled, Colors.amber),
      final f when f.trabajando => (Icons.play_circle_outline, Colors.green),
      // Sin sesiones no es lo mismo que sin problemas: puede ser que la
      // cadena de la Action se haya roto y nadie lo sepa.
      final f when f.callado => (Icons.pause_circle_outline, Colors.orange),
      _ => (Icons.check_circle_outline, Colors.blueGrey),
    };
    return Icon(
      icono,
      color: apagado ? Theme.of(context).disabledColor : color,
    );
  }
}
