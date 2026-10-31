"""Démarrage de l'interface : style sombre, fenêtre principale, script éventuel passé en argument."""
import sys

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from . import chemins
from .fenetre import Fenetre


def _palette_sombre():
    p = QPalette()
    for role, couleur in [(QPalette.Window, "#25272e"), (QPalette.WindowText, "#d7dae0"), (QPalette.Base, "#1d1f24"),
                          (QPalette.AlternateBase, "#25272e"), (QPalette.ToolTipBase, "#2b2e36"),
                          (QPalette.ToolTipText, "#d7dae0"), (QPalette.Text, "#d7dae0"), (QPalette.Button, "#2f323a"),
                          (QPalette.ButtonText, "#d7dae0"), (QPalette.Highlight, "#4C9BE8"),
                          (QPalette.HighlightedText, "#ffffff"), (QPalette.PlaceholderText, "#6b7080"),
                          (QPalette.Link, "#4C9BE8")]:
        p.setColor(role, QColor(couleur))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        p.setColor(QPalette.Disabled, role, QColor("#5d6270"))
    return p


STYLE_BULLES = ("QToolTip { color: #e6e8ec; background-color: #2b2e36; border: 1px solid #4a4f5c; "
                "padding: 4px 6px; font-size: 8pt; }")


def principal(argv):
    if sys.platform == "win32":     # la barre des tâches montre l'icône de l'application, pas celle de Python
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("zebruo.ffmontage")
    app = QApplication(sys.argv[:1] + list(argv))
    app.setApplicationName("Table de montage")
    app.setStyle("Fusion")
    app.setPalette(_palette_sombre())
    # les bulles d'aide d'un widget qui a sa propre feuille de style (noms du panneau…) ignorent la palette : sans
    # cette règle, elles sortent en jaune pâle avec le texte clair du widget, illisible
    app.setStyleSheet(STYLE_BULLES)
    app.setWindowIcon(QIcon(str(chemins.dossier_ressources() / "icones" / "application.ico")))
    fenetre = Fenetre(argv[0] if argv else None)
    fenetre.show()
    return app.exec()
