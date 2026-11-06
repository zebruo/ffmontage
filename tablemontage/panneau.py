"""Panneau des réglages : un champ par valeur du bloc « # ── RÉGLAGES ».

Le panneau reste sobre : titres de section courts, et le commentaire du script, les pistes reliées et la valeur
d'aperçu dans la bulle d'aide du nom (pas sous le champ). Un commentaire qui commence par « s · » met « s » dans la
case du nombre.
"""
import ast
import html
import os
import re

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractSlider, QAbstractSpinBox, QApplication, QCheckBox, QColorDialog, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFontComboBox, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSlider, QSpinBox,
                               QToolButton, QWidget)

from .reglages import Section

# rôle de l'étiquette (sans accent dans le code) → texte affiché sous le champ
NOMS_ROLES = {"debut": "début", "fin": "fin", "duree": "durée", "marque": "repère", "marques": "repères",
              "intervalles": "intervalles", "texte": "texte", "police": "police", "taille": "taille",
              "couleur": "couleur", "position": "position"}


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".")
    texte = repr(v) if not isinstance(v, str) else v
    return texte if len(texte) < 120 else texte[:117] + "…"


def _titre_court(titre):
    """« Titre (couleur …) » → « Titre » ; « Musique : le fichier… » → « Musique »."""
    return re.split(r"\s+[(:—–]|\s+-\s", titre, maxsplit=1)[0].strip() or titre


def _en_secondes(r):
    """Un temps : commentaire « s · … », ou valeur reliée au début, à la fin, à la durée d'une piste, à un repère."""
    return bool(r.commentaire and re.match(r"s\s*·", r.commentaire)) or \
        any(role in ("debut", "fin", "duree", "marque") for _, role in r.etiquettes)


def _decimales(source):
    partie = source.split(".")[1] if "." in source else ""
    return max(2, min(6, len(partie.rstrip("0")) or 1))


class PanneauReglages(QScrollArea):
    modifie = Signal(dict)          # {nom: nouvelle valeur}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumWidth(320)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)    # le contenu suit la largeur du panneau
        self._signature = None
        self._poseurs = {}
        self._base = ""
        self._vide("Ouvrez un script de montage (Ctrl+O).")

    def _vide(self, texte):
        etiquette = QLabel(texte)
        etiquette.setAlignment(Qt.AlignCenter)
        etiquette.setWordWrap(True)
        etiquette.setMargin(20)
        self.setWidget(etiquette)
        self._signature, self._poseurs = None, {}

    def afficher(self, bloc, base):
        """Affiche le bloc ; si seules les valeurs ont changé, met à jour les champs sans les reconstruire."""
        self._base = base
        if bloc.erreur:
            self._vide(bloc.erreur)
            return
        if not bloc.trouve:
            self._vide("Ce script n'a pas de bloc « # ── RÉGLAGES ».\nLa convention est décrite dans le README.")
            return
        signature = tuple((type(e).__name__, getattr(e, "nom", getattr(e, "titre", "")),
                           getattr(e, "modifiable", None), type(getattr(e, "valeur", None)).__name__)
                          for e in bloc.elements if not getattr(e, "hors_bloc", False)) + \
            tuple(r.nom for r in bloc.resultats)
        if signature != self._signature:
            self._construire(bloc)
            self._signature = signature
        else:
            for r in bloc.reglages + bloc.resultats:
                if r.nom in self._poseurs:
                    self._poseurs[r.nom](r)

    def _construire(self, bloc):
        conteneur = QWidget()
        grille = QGridLayout(conteneur)
        grille.setColumnStretch(1, 1)
        grille.setVerticalSpacing(6)
        self._poseurs = {}
        ligne = 0
        # les réglages du bloc, puis les valeurs @resultat lues à la fin du script
        resultats = [Section("Résultats du script (valeurs en fin d'exécution)", 0)] + bloc.resultats \
            if bloc.resultats else []
        for e in [e for e in bloc.elements if not getattr(e, "hors_bloc", False)] + resultats:
            if isinstance(e, Section):
                titre = QLabel(_titre_court(e.titre))
                titre.setStyleSheet("font-weight: bold; font-size: 7.5pt; color: #b9c0cc; "
                                    "padding-top: 12px; padding-bottom: 2px;")
                if _titre_court(e.titre) != e.titre:
                    titre.setToolTip(e.titre)
                grille.addWidget(titre, ligne, 0, 1, 2)
                ligne += 1
                continue
            nom = QLabel(e.libelle or e.nom)
            nom.setStyleSheet(("color: #d7dae0;" if e.modifiable else "color: #8a8f9c;") + " font-size: 7.5pt;")
            champ, poser = self._champ(e)
            grille.addWidget(nom, ligne, 0, Qt.AlignVCenter | Qt.AlignLeft)     # au milieu du champ
            grille.addWidget(champ, ligne, 1)
            ligne += 1
            # le commentaire, les pistes et la valeur d'aperçu : dans la bulle d'aide du nom
            commentaire = re.sub(r"^s\s*·\s*", "", e.commentaire or "")
            details = [e.nom] if e.libelle else []          # le nom de la variable dans le script
            details += [commentaire] if commentaire else []
            details += [f"piste {p.replace('_', ' ')} ({NOMS_ROLES.get(role, role)})" for p, role in e.etiquettes]
            if e.apercu:
                details.append(f"aperçu : {e.apercu}")
            if details:
                nom.setToolTip("\n".join(details))
            self._poseurs[e.nom] = poser
        grille.setRowStretch(ligne, 1)
        self.setWidget(conteneur)
        # la molette ne change jamais une valeur (un réglage modifié par mégarde en faisant défiler) : elle fait
        # défiler le panneau ; les curseurs se tirent, les nombres se tapent ou se changent par leurs flèches
        for w in conteneur.findChildren(QWidget):
            if isinstance(w, (QAbstractSpinBox, QAbstractSlider, QComboBox)):
                w.setFocusPolicy(Qt.StrongFocus)        # (pas de focus à la molette)
                w.installEventFilter(self)

    def eventFilter(self, objet, e):
        if e.type() == QEvent.Wheel and isinstance(objet, (QAbstractSpinBox, QAbstractSlider, QComboBox)):
            barre = self.verticalScrollBar()            # le panneau défile à la place
            crans = e.angleDelta().y() / 120
            barre.setValue(barre.value() - round(crans * QApplication.wheelScrollLines() * barre.singleStep()))
            return True
        return super().eventFilter(objet, e)

    def _emettre(self, nom, valeur):
        self.modifie.emit({nom: valeur})

    def _champ(self, r):
        v, nom = r.valeur, r.nom
        if not r.modifiable:
            etiquette = QLabel()
            etiquette.setWordWrap(True)
            etiquette.setTextInteractionFlags(Qt.TextSelectableByMouse)

            def poser(r):
                valeur = html.escape(_fmt(r.valeur)) if r.connu else "?"
                formule = "" if r.resultat else \
                    f"&nbsp;&nbsp;<span style='color:#6b7080'>= {html.escape(r.source)}</span>"   # un résultat : la valeur seule
                etiquette.setText(f"<span style='color:#c8ccd4'>{valeur}</span>{formule}")
            poser(r)
            return etiquette, poser

        if r.choix == "couleur" and isinstance(v, str):
            return self._champ_couleur(r)
        if r.choix == "police" and isinstance(v, str):
            return self._champ_police(r)
        if r.choix == "position" and isinstance(v, (list, tuple)) and len(v) == 2 \
                and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            return self._champ_position(r)

        if isinstance(v, bool):
            case = QCheckBox()
            case.setChecked(v)
            case.toggled.connect(lambda x: self._emettre(nom, x))

            def poser(r):
                case.blockSignals(True)
                case.setChecked(bool(r.valeur))
                case.blockSignals(False)
            return case, poser

        if isinstance(v, (int, float)):
            entier = isinstance(v, int)
            boite = QWidget()
            h = QHBoxLayout(boite)
            h.setContentsMargins(0, 0, 0, 0)
            if entier:
                sp = QSpinBox()
                sp.setRange(int(r.mini) if r.mini is not None else -2_000_000_000,
                            int(r.maxi) if r.maxi is not None else 2_000_000_000)
            else:
                sp = QDoubleSpinBox()
                dec = _decimales(r.source)
                sp.setDecimals(dec)
                sp.setRange(r.mini if r.mini is not None else -1e9, r.maxi if r.maxi is not None else 1e9)
                if r.mini is not None and r.maxi is not None:
                    sp.setSingleStep(max(10 ** -dec, round((r.maxi - r.mini) / 100, dec)))
                else:
                    sp.setSingleStep(0.1 if abs(v) >= 1 else 0.01)
            if _en_secondes(r):
                sp.setSuffix(" s")
            sp.setValue(v)
            sp.setKeyboardTracking(False)
            curseur = None
            if r.mini is not None and r.maxi is not None and r.maxi > r.mini:
                mini, maxi = r.mini, r.maxi
                curseur = QSlider(Qt.Horizontal)
                curseur.setRange(0, 1000)
                vers_curseur = lambda x: int(round((x - mini) / (maxi - mini) * 1000))
                curseur.setValue(vers_curseur(v))
                curseur.valueChanged.connect(lambda k: sp.setValue(mini + (maxi - mini) * k / 1000))

                def suivre(x):
                    curseur.blockSignals(True)
                    curseur.setValue(vers_curseur(x))
                    curseur.blockSignals(False)
                sp.valueChanged.connect(suivre)
                h.addWidget(curseur, 1)
            sp.valueChanged.connect(lambda x: self._emettre(nom, int(x) if entier else round(x, sp.decimals())))
            h.addWidget(sp, 0 if curseur else 1)

            def poser(r):
                if sp.hasFocus() or (curseur and curseur.isSliderDown()):
                    return
                for w in (sp, curseur):
                    if w:
                        w.blockSignals(True)
                sp.setValue(r.valeur)
                if curseur:
                    curseur.setValue(vers_curseur(r.valeur))
                for w in (sp, curseur):
                    if w:
                        w.blockSignals(False)
            return boite, poser

        # texte, ou autre littéral (liste, tuple, dict) écrit en Python
        texte_simple = isinstance(v, str)
        boite = QWidget()
        h = QHBoxLayout(boite)
        h.setContentsMargins(0, 0, 0, 0)
        champ = QLineEdit(v if texte_simple else r.source)
        champ.setCursorPosition(0)
        h.addWidget(champ, 1)
        if not texte_simple:
            champ.setToolTip("Valeur Python (liste, tuple…). Entrée pour valider.")

        def valider():
            if texte_simple:
                if champ.text() != champ.property("valeur"):
                    self._emettre(nom, champ.text())
                return
            try:
                valeur = ast.literal_eval(champ.text())
            except (ValueError, SyntaxError):
                champ.setStyleSheet("border: 1px solid #e06c75;")
                return
            champ.setStyleSheet("")
            if repr(valeur) != champ.property("valeur"):
                self._emettre(nom, valeur)
        champ.setProperty("valeur", v if texte_simple else repr(v))
        champ.editingFinished.connect(valider)

        if r.choix:
            bouton = QToolButton()
            bouton.setText("…")
            bouton.setToolTip("Choisir un dossier" if r.choix == "dossier" else "Choisir un fichier")
            bouton.clicked.connect(lambda: self._choisir(r.choix, champ, nom))
            h.addWidget(bouton)

        def poser(r):
            if champ.hasFocus():
                return
            champ.setProperty("valeur", r.valeur if texte_simple else repr(r.valeur))
            texte = r.valeur if texte_simple else r.source
            if champ.text() != texte:
                champ.setText(texte)
                champ.setCursorPosition(0)
        return boite, poser

    def _champ_couleur(self, r):
        """Une pastille de la couleur et son code ; un clic ouvre le choix de couleur."""
        nom = r.nom
        bouton = QPushButton()
        bouton.setCursor(Qt.PointingHandCursor)

        def poser(r):
            couleur = QColor(r.valeur)
            texte = "#000000" if couleur.isValid() and couleur.lightnessF() > 0.6 else "#ffffff"
            bouton.setText(r.valeur)
            bouton.setStyleSheet(f"QPushButton {{ background: {r.valeur}; color: {texte}; border: 1px solid #4a4f5c;"
                                 f" border-radius: 3px; padding: 4px; font-family: Consolas; }}")
            bouton.setProperty("valeur", r.valeur)

        def choisir():
            couleur = QColorDialog.getColor(QColor(bouton.property("valeur")), self, f"Couleur : {nom}")
            if couleur.isValid():
                self._emettre(nom, couleur.name().upper())
        bouton.clicked.connect(choisir)
        poser(r)
        return bouton, poser

    def _champ_police(self, r):
        """La liste des polices installées."""
        nom = r.nom
        liste = QFontComboBox()
        liste.setCurrentFont(QFont(r.valeur))
        liste.currentFontChanged.connect(lambda f: self._emettre(nom, f.family()))

        def poser(r):
            if liste.hasFocus() or liste.view().isVisible():
                return
            liste.blockSignals(True)
            liste.setCurrentFont(QFont(r.valeur))
            liste.blockSignals(False)
        return liste, poser

    def _champ_position(self, r):
        """X et Y en pixels de l'image (on peut aussi faire glisser la poignée sur l'aperçu)."""
        nom, genre = r.nom, type(r.valeur)
        boite = QWidget()
        h = QHBoxLayout(boite)
        h.setContentsMargins(0, 0, 0, 0)
        champs = []
        for axe in ("x", "y"):
            sp = QSpinBox()
            sp.setRange(-10000, 10000)
            sp.setPrefix(f"{axe} ")
            sp.setKeyboardTracking(False)
            champs.append(sp)
            h.addWidget(sp, 1)

        def emettre():
            self._emettre(nom, genre(sp.value() for sp in champs))

        def poser(r):
            if any(sp.hasFocus() for sp in champs):
                return
            for sp, v in zip(champs, r.valeur):
                sp.blockSignals(True)
                sp.setValue(int(round(v)))
                sp.blockSignals(False)
        poser(r)
        for sp in champs:
            sp.valueChanged.connect(emettre)
        return boite, poser

    def _choisir(self, genre, champ, nom):
        """Fichier ou dossier ; relatif au dossier de base s'il est dedans, sinon chemin complet."""
        actuel = os.path.join(self._base, champ.text())
        depart = actuel if os.path.isdir(actuel) else os.path.dirname(actuel)
        if genre == "dossier":
            choisi = QFileDialog.getExistingDirectory(self, "Choisir un dossier", depart)
        else:
            choisi = QFileDialog.getOpenFileName(self, "Choisir un fichier", depart)[0]
        if not choisi:
            return
        choisi = os.path.normpath(choisi)
        try:
            relatif = os.path.relpath(choisi, self._base)
        except ValueError:          # autre lecteur
            relatif = None
        valeur = relatif if relatif and not relatif.startswith("..") and genre == "fichier" else choisi
        champ.setText(valeur)
        self._emettre(nom, valeur)
