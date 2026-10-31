"""Onglet « Fichiers » : les fichiers que le script lit et écrit (open), et ceux de la commande ffmpeg ; et l'éditeur
d'un fichier texte, ouvert d'un double-clic.

Un fichier lu par le script (un texte, des vers…) se modifie ici ; un fichier écrit par le script (un .ass…) est
montré en lecture seule, puisque le script le réécrit à chaque exécution.
"""
import os
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from . import fichier_texte

EXT_TEXTE = {".txt", ".ass", ".ssa", ".srt", ".vtt", ".json", ".csv", ".md", ".ini", ".cfg", ".xml", ".lrc", ".py"}


def _taille(octets):
    for unite in ("o", "Ko", "Mo", "Go"):
        if octets < 1024 or unite == "Go":
            return f"{octets:.0f} {unite}" if unite == "o" else f"{octets:.1f} {unite}"
        octets /= 1024


class OngletFichiers(QTreeWidget):
    ouvrir = Signal(str, bool)      # chemin, modifiable

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Fichier", "Dossier", "Taille", "Modifié"])
        self.setColumnWidth(0, 260)
        self.setColumnWidth(1, 150)
        self.setColumnWidth(2, 70)
        self.setRootIsDecorated(True)
        self.itemDoubleClicked.connect(self._double_clic)

    def afficher(self, dossier_script, fichiers_script, commande):
        """fichiers_script : [{chemin, acces}] notés pendant la lecture ; commande : la commande ffmpeg analysée."""
        self.clear()
        groupes = [("Lus par le script", "modifiables : double-clic"), ("Écrits par le script", "réécrits à chaque exécution"),
                   ("Lus par ffmpeg", "images, son…"), ("Écrit par ffmpeg", "le film, à l'export")]
        contenus = {nom: [] for nom, _ in groupes}
        for f in fichiers_script:
            contenus["Écrits par le script" if "écrit" in f["acces"] else "Lus par le script"].append(f["chemin"])
        if commande:
            for e in commande.entrees:
                if "lavfi" not in e.options:
                    contenus["Lus par ffmpeg"].append(os.path.normpath(os.path.join(commande.cwd, e.source)))
            if commande.sortie:
                contenus["Écrit par ffmpeg"].append(os.path.normpath(os.path.join(commande.cwd, commande.sortie)))
        for nom, aide in groupes:
            if not contenus[nom]:
                continue
            groupe = QTreeWidgetItem(self, [nom, aide])
            groupe.setFirstColumnSpanned(False)
            f = groupe.font(0)
            f.setBold(True)
            groupe.setFont(0, f)
            for chemin in dict.fromkeys(contenus[nom]):
                self._ligne(groupe, chemin, dossier_script, modifiable=nom == "Lus par le script")
        self.expandAll()

    def _ligne(self, groupe, chemin, dossier_script, modifiable):
        try:
            dossier = os.path.relpath(os.path.dirname(chemin), dossier_script)
        except ValueError:
            dossier = os.path.dirname(chemin)
        dossier = "" if dossier == "." else dossier
        if os.path.exists(chemin):
            info = os.stat(chemin)
            colonnes = [os.path.basename(chemin), dossier, _taille(info.st_size),
                        time.strftime("%d/%m %H:%M", time.localtime(info.st_mtime))]
        else:
            colonnes = [os.path.basename(chemin), dossier, "", "pas encore écrit"]
        item = QTreeWidgetItem(groupe, colonnes)
        item.setData(0, Qt.UserRole, (chemin, modifiable))
        item.setToolTip(0, chemin + ("\nDouble-clic : ouvrir" if os.path.exists(chemin) else ""))

    def _double_clic(self, item, colonne):
        donnees = item.data(0, Qt.UserRole)
        if donnees and os.path.exists(donnees[0]):
            self.ouvrir.emit(donnees[0], donnees[1])


class EditeurFichier(QWidget):
    """Un fichier texte dans un onglet : un bandeau d'explication et le texte (modifiable ou non)."""
    modifie_change = Signal(bool)

    def __init__(self, chemin, modifiable, parent=None):
        super().__init__(parent)
        self.chemin, self.modifiable = chemin, modifiable
        self._forme, self._texte_disque = fichier_texte.Forme(), ""
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.bandeau = QLabel()
        self.bandeau.setWordWrap(True)
        self.bandeau.setStyleSheet("background: #2b2e36; color: #b9c0cc; padding: 5px 8px;")
        v.addWidget(self.bandeau)
        self.texte = QPlainTextEdit()
        police = QFont("Consolas")
        police.setStyleHint(QFont.Monospace)
        police.setPointSizeF(10)
        self.texte.setFont(police)
        self.texte.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.texte.setReadOnly(not modifiable)
        self.texte.setStyleSheet("QPlainTextEdit { background: #1b1d22; color: #d4d4d4; border: none; }")
        v.addWidget(self.texte, 1)
        self.recharger()
        self.texte.document().modificationChanged.connect(self.modifie_change)

    def _lire(self):
        texte, self._forme = fichier_texte.lire(self.chemin)
        return texte

    def recharger(self):
        self._texte_disque = self._lire()
        defilement = self.texte.verticalScrollBar().value()
        self.texte.setPlainText(self._texte_disque)
        self.texte.document().setModified(False)
        self.texte.verticalScrollBar().setValue(defilement)
        if self.modifiable:
            self.bandeau.setText(f"Lu par le script. Ctrl+S enregistre ; le script est alors relu.  ·  {self.chemin}")
        else:
            self.bandeau.setText(f"Écrit par le script : lecture seule, il est réécrit à chaque exécution.  ·  "
                                 f"{self.chemin}")

    def change_sur_disque(self):
        """Le fichier a changé sur le disque : relu s'il n'a pas de modifications ici."""
        try:
            if self._lire() != self._texte_disque and not self.modifie():
                self.recharger()
        except OSError:
            pass

    def modifie(self):
        return self.texte.document().isModified()

    def enregistrer(self):
        texte = self.texte.toPlainText()
        fichier_texte.ecrire(self.chemin, texte, self._forme)
        self._texte_disque = texte
        self.texte.document().setModified(False)
