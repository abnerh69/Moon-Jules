#!/usr/bin/env bash
#
# Reinicia el servicio y reinstala la app en el telefono.
#
#   tools/desplegar.sh              las dos cosas
#   tools/desplegar.sh servicio     solo el servicio
#   tools/desplegar.sh app          solo la app
#   tools/desplegar.sh --limpio     desinstala la app antes de instalar
#
# El `--limpio` hace falta cuando cambia el canal de notificaciones:
# Android no modifica un canal ya creado. Ojo, borra las credenciales
# guardadas y habra que teclearlas otra vez.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

LIMPIO=0
QUE="todo"
for arg in "$@"; do
  case "$arg" in
    --limpio) LIMPIO=1 ;;
    servicio|app|todo) QUE="$arg" ;;
    -h|--help) sed -n '3,12p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "argumento desconocido: $arg" >&2; exit 2 ;;
  esac
done

titulo() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
aviso()  { printf '\033[33m%s\033[0m\n' "$1"; }

# ---------- servicio ----------
if [ "$QUE" != "app" ]; then
  titulo "servicio"

  # El entorno virtual importa: `service install` deja el servicio
  # apuntando a un ejecutable concreto y para siempre. Instalarlo con el
  # entorno desactivado lo haria apuntar a otra instalacion.
  if [ -z "${VIRTUAL_ENV:-}" ] && [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
    echo "entorno virtual activado"
  fi

  moon-jules service install
  echo
  moon-jules doctor | sed -n '1,12p'
fi

# ---------- app ----------
if [ "$QUE" != "servicio" ]; then
  titulo "app"

  if ! command -v flutter >/dev/null; then
    aviso "flutter no esta en el PATH; se omite la app."
    exit 0
  fi

  # Sin dispositivo no hay nada que instalar, y es mejor decirlo antes
  # de gastar dos minutos compilando.
  if ! flutter devices 2>/dev/null | grep -qi android; then
    aviso "no veo ningun Android conectado."
    aviso "Conectalo con depuracion USB activada y repite."
    exit 1
  fi

  cd app

  if [ "$LIMPIO" = 1 ]; then
    aviso "desinstalando la version anterior (se pierden las credenciales)"
    adb uninstall org.ashware.moonjules >/dev/null 2>&1 || true
    flutter clean >/dev/null
  fi

  # Release, no debug: es lo que queda instalado de verdad en el
  # telefono cuando se desconecta el cable.
  flutter build apk --release
  flutter install --release
fi

titulo "listo"
echo "Si el push no llega, el arbol de diagnostico esta en"
echo "docs/CONFIGURACION-NATIVA-Y-NOTIFICACIONES.md"
