"""Fabrique icones/application.ico (16 à 256 px) à partir de icones/application.svg.

Lancer après avoir modifié le SVG : .venv\\Scripts\\python outils\\faire_icone.py
L'.ico sert à l'exécutable (PyInstaller), à l'installateur et au raccourci du Bureau.
"""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

TAILLES = (16, 24, 32, 48, 64, 128, 256)
ICONES = Path(__file__).resolve().parent.parent / "icones"


def png(rendu, taille):
    image = QImage(taille, taille, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    rendu.render(p)
    p.end()
    tampon = QBuffer()
    tampon.open(QIODevice.WriteOnly)
    image.save(tampon, "PNG")
    return bytes(tampon.data())


def principal():
    app = QGuiApplication(sys.argv[:1])     # nécessaire au rendu
    rendu = QSvgRenderer(QByteArray((ICONES / "application.svg").read_bytes()))
    images = [png(rendu, t) for t in TAILLES]
    # format ICO : un en-tête, une entrée par taille, puis les images PNG
    entete = struct.pack("<HHH", 0, 1, len(images))
    position = 6 + 16 * len(images)
    entrees = b""
    for taille, donnees in zip(TAILLES, images):
        cote = 0 if taille >= 256 else taille
        entrees += struct.pack("<BBBBHHII", cote, cote, 0, 0, 1, 32, len(donnees), position)
        position += len(donnees)
    (ICONES / "application.ico").write_bytes(entete + entrees + b"".join(images))
    (ICONES / "application.png").write_bytes(images[-1])
    print("écrit :", ICONES / "application.ico")
    app.quit()


if __name__ == "__main__":
    principal()
