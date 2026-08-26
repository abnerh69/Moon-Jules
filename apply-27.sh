#!/usr/bin/env bash
# Entrega 27: nombre visible y permiso de notificaciones.
#
# El AndroidManifest.xml lo genera `flutter create` en la maquina del
# arquitecto, asi que no viaja en el zip: se parchea aqui. El script es
# idempotente — puede ejecutarse varias veces sin duplicar nada.
set -euo pipefail
cd "$(dirname "$0")"
MANIFEST="app/android/app/src/main/AndroidManifest.xml"

if [ ! -f "$MANIFEST" ]; then
  echo "no encuentro $MANIFEST; ejecuta esto desde la raiz del repositorio" >&2
  exit 1
fi

# 1. Nombre visible: "moonjules" es el identificador del paquete, no algo
#    que deba leerse bajo un icono.
if grep -q 'android:label="moonjules"' "$MANIFEST"; then
  sed -i.bak 's/android:label="moonjules"/android:label="Moon Jules"/' "$MANIFEST"
  echo "nombre visible -> Moon Jules"
elif grep -q 'android:label="Moon Jules"' "$MANIFEST"; then
  echo "el nombre visible ya estaba puesto"
else
  echo "aviso: no reconoci el android:label; revisalo a mano" >&2
fi

# 2. Android 13+ exige pedir permiso en tiempo de ejecucion para
#    notificar. Sin esta linea, el push se registra pero nunca se ve.
if grep -q 'POST_NOTIFICATIONS' "$MANIFEST"; then
  echo "el permiso de notificaciones ya estaba declarado"
else
  sed -i.bak2 's|<application|<uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>\n    <application|' "$MANIFEST"
  echo "permiso POST_NOTIFICATIONS declarado"
fi

rm -f "$MANIFEST".bak "$MANIFEST".bak2
echo
echo "Recompila con: cd app && flutter run --dart-define=..."
rm -- "$0"
