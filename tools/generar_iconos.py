#!/usr/bin/env python3
"""Genera el icono de la app.

Un icono se mira a 48 píxeles en una rejilla llena de otros iconos, así
que la única regla que importa es que se distinga de un vistazo. De ahí
las decisiones: una sola forma, un solo acento de color y nada de
detalle que se pierda al reducir.

La luna es por el nombre. El punto verde es el latido —el estado que la
app existe para vigilar— y reutiliza el mismo verde del `vigilando` de
la pantalla, para que quien vea el icono reconozca el color cuando abra.

Se ejecuta a mano cuando cambie el diseño; su salida se versiona:

    python3 tools/generar_iconos.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

#: Semilla del tema de la app (`ColorScheme.fromSeed`).
INDIGO = (48, 60, 130)
INDIGO_CLARO = (79, 95, 190)
LUNA = (238, 240, 250)
LATIDO = (76, 200, 120)

#: Densidades de Android, en píxeles de lado.
DENSIDADES = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}

#: Se dibuja grande y se reduce: el suavizado sale mucho mejor que
#: dibujando directamente a 48 píxeles.
LIENZO = 1024


def dibujar() -> Image.Image:
    img = Image.new("RGBA", (LIENZO, LIENZO), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Fondo redondeado con un degradado vertical sencillo: dos tonos del
    # mismo índigo bastan para que no se vea plano.
    radio = int(LIENZO * 0.22)
    fondo = Image.new("RGBA", (LIENZO, LIENZO), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fondo)
    for y in range(LIENZO):
        t = y / LIENZO
        color = tuple(
            int(INDIGO_CLARO[i] + (INDIGO[i] - INDIGO_CLARO[i]) * t)
            for i in range(3)
        )
        fd.line([(0, y), (LIENZO, y)], fill=(*color, 255))
    mascara = Image.new("L", (LIENZO, LIENZO), 0)
    ImageDraw.Draw(mascara).rounded_rectangle(
        [0, 0, LIENZO - 1, LIENZO - 1], radius=radio, fill=255
    )
    img.paste(fondo, (0, 0), mascara)

    # La luna: un disco al que se le resta otro desplazado. Es la forma
    # más limpia de un creciente y no depende de curvas a mano.
    centro = LIENZO // 2
    r = int(LIENZO * 0.30)
    luna = Image.new("RGBA", (LIENZO, LIENZO), (0, 0, 0, 0))
    ld = ImageDraw.Draw(luna)
    ld.ellipse(
        [centro - r, centro - r - int(LIENZO * 0.02),
         centro + r, centro + r - int(LIENZO * 0.02)],
        fill=(*LUNA, 255),
    )
    recorte = Image.new("L", (LIENZO, LIENZO), 0)
    rd = ImageDraw.Draw(recorte)
    dx = int(r * 0.55)
    rd.ellipse(
        [centro - r + dx, centro - r - int(LIENZO * 0.055),
         centro + r + dx, centro + r - int(LIENZO * 0.055)],
        fill=255,
    )
    luna.putalpha(
        Image.composite(Image.new("L", (LIENZO, LIENZO), 0),
                        luna.getchannel("A"), recorte)
    )
    img.alpha_composite(luna)

    # El latido: un punto y su halo, abajo a la derecha del creciente.
    px, py = centro + int(r * 0.62), centro + int(r * 0.72)
    pr = int(LIENZO * 0.052)
    d = ImageDraw.Draw(img)
    d.ellipse([px - pr * 2, py - pr * 2, px + pr * 2, py + pr * 2],
              fill=(*LATIDO, 70))
    d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(*LATIDO, 255))
    return img


def notificacion() -> Image.Image:
    """Icono monocromo para la barra de notificaciones.

    Android **ignora el color** del icono pequeno: lo pinta como una
    silueta blanca a partir del canal alfa. Un icono a color se ve como
    un cuadrado blanco relleno, que es lo que ocurre cuando no se
    declara uno propio y el sistema recurre al de la app.
    """
    lado = 192
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c, r = lado // 2, int(lado * 0.34)
    d.ellipse([c - r, c - r, c + r, c + r], fill=(255, 255, 255, 255))
    recorte = Image.new("L", (lado, lado), 0)
    dx = int(r * 0.55)
    ImageDraw.Draw(recorte).ellipse(
        [c - r + dx, c - r - int(lado * 0.06), c + r + dx, c + r - int(lado * 0.06)],
        fill=255,
    )
    img.putalpha(
        Image.composite(Image.new("L", (lado, lado), 0),
                        img.getchannel("A"), recorte)
    )
    return img


DRAWABLES = {"mdpi": 24, "hdpi": 36, "xhdpi": 48, "xxhdpi": 72, "xxxhdpi": 96}


def main() -> int:
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "app/android/app/src/main/res"
    )
    maestro = dibujar()
    for nombre, lado in DENSIDADES.items():
        carpeta = destino / f"mipmap-{nombre}"
        carpeta.mkdir(parents=True, exist_ok=True)
        maestro.resize((lado, lado), Image.LANCZOS).save(
            carpeta / "ic_launcher.png"
        )
        print(f"  {carpeta/'ic_launcher.png'} ({lado}px)")
    # Icono de la barra de notificaciones, monocromo.
    silueta = notificacion()
    for nombre, lado in DRAWABLES.items():
        carpeta = destino / f"drawable-{nombre}"
        carpeta.mkdir(parents=True, exist_ok=True)
        silueta.resize((lado, lado), Image.LANCZOS).save(
            carpeta / "ic_notificacion.png"
        )
    print(f"  ic_notificacion.png en {len(DRAWABLES)} densidades")

    # Copia grande, por si hace falta para el escritorio o un README.
    grande = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("app/icono.png")
    grande.parent.mkdir(parents=True, exist_ok=True)
    maestro.resize((512, 512), Image.LANCZOS).save(grande)
    print(f"  {grande} (512px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
