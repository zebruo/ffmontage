"""Icônes de l'interface : les SVG du dossier « icones » (16×16, dessinés en currentColor), colorés selon l'état."""
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import chemins

COULEURS = {QIcon.Normal: "#d7dae0", QIcon.Active: "#ffffff", QIcon.Disabled: "#5d6270"}
_cache = {}


def icone(nom):
    if nom in _cache:
        return _cache[nom]
    resultat = QIcon()
    try:
        texte = (chemins.dossier_ressources() / "icones" / f"{nom}.svg").read_text(encoding="utf-8")
    except OSError:
        return resultat
    for mode, couleur in COULEURS.items():
        rendu = QSvgRenderer(QByteArray(texte.replace("currentColor", couleur).encode("utf-8")))
        for taille in (16, 20, 24, 32, 48):
            image = QPixmap(taille, taille)
            image.fill(Qt.transparent)
            p = QPainter(image)
            rendu.render(p)
            p.end()
            resultat.addPixmap(image, mode)
    _cache[nom] = resultat
    return resultat
