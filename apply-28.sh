#!/usr/bin/env bash
# Entrega 28: acceso con contraseña guardada y biometria.
#
# Toca dos ficheros que genera `flutter create` y que por eso no viajan
# en el zip. Idempotente: puede ejecutarse varias veces.
set -euo pipefail
cd "$(dirname "$0")"
MANIFEST="app/android/app/src/main/AndroidManifest.xml"
ACTIVITY="app/android/app/src/main/kotlin/org/ashware/moonjules/MainActivity.kt"

[ -f "$MANIFEST" ] || { echo "no encuentro $MANIFEST" >&2; exit 1; }

# 1. Permiso de biometria.
if grep -q 'USE_BIOMETRIC' "$MANIFEST"; then
  echo "el permiso de biometria ya estaba declarado"
else
  sed -i.bak 's|<application|<uses-permission android:name="android.permission.USE_BIOMETRIC"/>\n    <application|' "$MANIFEST"
  rm -f "$MANIFEST".bak
  echo "permiso USE_BIOMETRIC declarado"
fi

# 2. `local_auth` necesita FlutterFragmentActivity: con FlutterActivity
#    la llamada a la biometria falla en tiempo de ejecucion, no al
#    compilar, que es la peor forma de enterarse.
if [ -f "$ACTIVITY" ]; then
  if grep -q 'FlutterFragmentActivity' "$ACTIVITY"; then
    echo "MainActivity ya extiende FlutterFragmentActivity"
  else
    sed -i.bak \
      -e 's|import io.flutter.embedding.android.FlutterActivity|import io.flutter.embedding.android.FlutterFragmentActivity|' \
      -e 's|: FlutterActivity()|: FlutterFragmentActivity()|' \
      "$ACTIVITY"
    rm -f "$ACTIVITY".bak
    echo "MainActivity -> FlutterFragmentActivity"
  fi
else
  echo "aviso: no encuentro $ACTIVITY; si usas otro paquete, cambia" >&2
  echo "       FlutterActivity por FlutterFragmentActivity a mano" >&2
fi

echo
echo 'Ahora: cd app && flutter pub get && flutter build apk --release'
echo 'Ya no hacen falta los --dart-define: la contrasena se teclea una vez.'
rm -- "$0"
