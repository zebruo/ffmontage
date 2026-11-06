"""Fenêtre du nouveau projet : ce que contient le dossier, et les premiers choix du film (taille, cadence, photos,
animations, titre, son). Tout reste modifiable ensuite dans le panneau des réglages."""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QLabel, QLineEdit, QSpinBox, QVBoxLayout)

FORMATS = [("1920 × 1080 : Full HD, paysage", (1920, 1080)),
           ("1280 × 720 : HD, plus léger", (1280, 720)),
           ("3840 × 2160 : 4K", (3840, 2160)),
           ("1080 × 1920 : vertical (téléphone)", (1080, 1920)),
           ("1080 × 1080 : carré", (1080, 1080))]
CADENCES = [24, 25, 30, 50, 60]


class _SansMolette(QObject):
    """La molette ne change pas les valeurs (un choix modifié par mégarde)."""
    def eventFilter(self, objet, e):
        return e.type() == QEvent.Wheel


class DialogueProjet(QDialog):
    def __init__(self, nom, inventaire, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Nouveau projet : {nom}")
        videos, photos, sons, animations = inventaire
        self._filtre = _SansMolette(self)

        contenu = (f"Dans le dossier : {videos} vidéo(s), {photos} photo(s), {animations} animation(s) "
                   f"(suites d'images numérotées), {sons} musique(s)."
                   if any(inventaire) else
                   "Le dossier est vide : y mettre vidéos, photos et musique, puis F5 dans la table pour les relire.")
        resume = QLabel(contenu)
        resume.setWordWrap(True)

        # Image
        self.format = QComboBox()
        for texte, taille in FORMATS:
            self.format.addItem(texte, taille)
        self.ips = QComboBox()
        for n in CADENCES:
            self.ips.addItem(f"{n} images/s", n)
        self.ips.setCurrentIndex(CADENCES.index(24 if animations else 30))
        self.ips.setToolTip("24 : cinéma et la plupart des rendus d'animation ; 25 : vidéos européennes ; "
                            "30 : téléphones")
        image = self._groupe("Image", [("Taille", self.format), ("Cadence", self.ips)])

        # Plans
        self.duree_photo = self._nombre(4.0, 0.5, 30, " s")
        self.fondu = self._nombre(1.0, 0.0, 3, " s")
        self.fondu.setToolTip("Fondu enchaîné entre deux plans (0 : coupe franche)")
        self.suites = QCheckBox("Les suites d'images numérotées sont des animations")
        self.suites.setChecked(True)
        self.suites.setToolTip("Au moins 24 images de même nom (rendu_0001.png, rendu_0002.png…), en .png, .tif, "
                               ".bmp ou .webp : un seul plan animé. Décoché : chaque image est une photo.")
        self.suite_ips = QSpinBox()
        self.suite_ips.setRange(1, 60)
        self.suite_ips.setValue(24)
        self.suite_ips.setSuffix(" images/s")
        self.suite_ips.setToolTip("La cadence du rendu de l'animation")
        self.suites.toggled.connect(self.suite_ips.setEnabled)
        plans = self._groupe("Plans", [("Durée d'une photo", self.duree_photo), ("Fondu entre les plans", self.fondu),
                                       (None, self.suites), ("Cadence des animations", self.suite_ips)])

        # Titre
        self.titre = QLineEdit(nom)
        self.titre.setPlaceholderText("vide : pas de titre")
        titre = self._groupe("Titre", [("Texte", self.titre)])

        # Son
        self.son_videos = QCheckBox("Garder le son des vidéos")
        self.son_videos.setChecked(True)
        self.boucle = QCheckBox("Reprendre la musique si elle est plus courte que le film")
        self.boucle.setChecked(True)
        self.sous_videos = QSpinBox()
        self.sous_videos.setRange(0, 100)
        self.sous_videos.setValue(30)
        self.sous_videos.setSuffix(" %")
        self.sous_videos.setToolTip("Volume de la musique pendant le son des vidéos (100 % : inchangé)")
        self.son_videos.toggled.connect(self.sous_videos.setEnabled)
        son = self._groupe("Son", [(None, self.son_videos), ("Musique pendant le son des vidéos", self.sous_videos),
                                   (None, self.boucle)])
        note = QLabel("Les musiques du dossier sont enchaînées par ordre alphabétique. Tout se change ensuite dans le "
                      "panneau des réglages.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #8a8f9c;")

        boutons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        boutons.button(QDialogButtonBox.Ok).setText("Créer le projet")
        boutons.button(QDialogButtonBox.Cancel).setText("Annuler")
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)

        v = QVBoxLayout(self)
        for w in (resume, image, plans, titre, son, note, boutons):
            v.addWidget(w)
        self.setMinimumWidth(460)

    def _groupe(self, titre, lignes):
        boite = QGroupBox(titre)
        f = QFormLayout(boite)
        for etiquette, champ in lignes:
            if isinstance(champ, (QAbstractSpinBox, QComboBox)):
                champ.setFocusPolicy(Qt.StrongFocus)
                champ.installEventFilter(self._filtre)
            if etiquette:
                f.addRow(etiquette, champ)
            else:
                f.addRow(champ)
        return boite

    @staticmethod
    def _nombre(valeur, mini, maxi, suffixe):
        sp = QDoubleSpinBox()
        sp.setRange(mini, maxi)
        sp.setDecimals(1)
        sp.setSingleStep(0.5)
        sp.setValue(valeur)
        sp.setSuffix(suffixe)
        return sp

    def options(self):
        """{nom du réglage du script: valeur}."""
        largeur, hauteur = self.format.currentData()
        return {
            "W": largeur, "H": hauteur, "IPS": self.ips.currentData(),
            "POSITION_TITRE": (largeur // 2, hauteur // 2),
            "TAILLE_TITRE": round(110 * min(largeur, hauteur) / 1080),     # (110 pour une image de 1080)
            "DUREE_PHOTO": round(self.duree_photo.value(), 1), "FONDU": round(self.fondu.value(), 1),
            "SUITES": self.suites.isChecked(), "SUITE_IPS": self.suite_ips.value(),
            "TITRE": self.titre.text().strip(),
            "SON_VIDEOS": self.son_videos.isChecked(), "MUSIQUE_SOUS_VIDEOS": self.sous_videos.value() / 100,
            "MUSIQUE_BOUCLE": self.boucle.isChecked(),
        }
