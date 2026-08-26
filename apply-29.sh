#!/usr/bin/env bash
# Entrega 29: canal de notificaciones e icono de la barra.
#
# Sin `default_notification_channel_id`, Android descarta en silencio lo
# que llega con la app cerrada: FCM informa de entrega correcta y en el
# telefono no aparece nada. Y sin `default_notification_icon`, el icono
# a color se pinta como un cuadrado blanco.
#
# El AndroidManifest lo genera `flutter create`, asi que se parchea aqui.
# Idempotente.
set -euo pipefail
cd "$(dirname "$0")"
MANIFEST="app/android/app/src/main/AndroidManifest.xml"
[ -f "$MANIFEST" ] || { echo "no encuentro $MANIFEST" >&2; exit 1; }

anadir_meta() {
  local clave="$1" valor="$2" tipo="$3"
  if grep -q "$clave" "$MANIFEST"; then
    echo "  $clave ya estaba declarado"
    return
  fi
  # Se inserta dentro de <application>, justo tras su apertura.
  python3 - "$MANIFEST" "$clave" "$valor" "$tipo" <<'PY'
import re, sys
ruta, clave, valor, tipo = sys.argv[1:5]
texto = open(ruta, encoding="utf-8").read()
meta = f'        <meta-data\n            android:name="{clave}"\n            android:{tipo}="{valor}" />\n'
m = re.search(r"<application\b[^>]*>", texto)
if not m:
    sys.exit("no encuentro la etiqueta <application>")
texto = texto[:m.end()] + "\n" + meta + texto[m.end():]
open(ruta, "w", encoding="utf-8").write(texto)
PY
  echo "  $clave declarado"
}

anadir_meta "com.google.firebase.messaging.default_notification_channel_id" \
            "moonjules_alertas" "value"
anadir_meta "com.google.firebase.messaging.default_notification_icon" \
            "@drawable/ic_notificacion" "resource"

echo
echo 'Ahora: cd app && flutter pub get && flutter clean'
echo '       flutter build apk --release && flutter install --release'
echo
echo 'El canal se crea al arrancar la app. Si ya la tenias instalada,'
echo 'desinstalala antes: Android no cambia un canal ya creado.'
rm -- "$0"
