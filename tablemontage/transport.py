"""Transport sous l'aperçu, en flat design (comme le mixeur) : les afficheurs TEMPS et IMAGE et les boutons début,
recul, stop, lecture/pause, avance, boucle."""
import bisect

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from .icones import icone

STYLE = """
QLabel#titre { color: #8a8f9c; font-size: 7pt; font-weight: bold; letter-spacing: 1px; }
QLabel#temps, QLabel#image { background: #5e5b4f; color: #1a1914; border: 1px solid #3b392f; border-radius: 4px;
                             padding: 1px 10px; }
QToolButton { background: #2f323a; border: 1px solid #3a3e48; border-radius: 3px; }
QToolButton:hover { background: #3a3e48; border-color: #4a4f5c; }
QToolButton:pressed { background: #23252b; }
QToolButton:checked { background: #2c4a6b; border-color: #4C9BE8; }
"""


def _bloc(titre, contenu):
    boite = QWidget()
    v = QVBoxLayout(boite)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    etiquette = QLabel(titre)
    etiquette.setObjectName("titre")
    v.addWidget(etiquette)
    v.addWidget(contenu)
    return boite


class Transport(QWidget):
    debut = Signal()
    recul = Signal()
    stop = Signal()
    lecture = Signal()
    avance = Signal()
    boucle = Signal(bool)
    textes = Signal(bool)       # montrer les poignées des textes sur l'aperçu

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(STYLE)

        self.temps = QLabel("0:00.000")
        self.temps.setObjectName("temps")
        police = QFont("Consolas")
        police.setStyleHint(QFont.Monospace)
        police.setPointSize(17)
        police.setBold(True)
        self.temps.setFont(police)
        self.temps.setAlignment(Qt.AlignCenter)
        self.temps.setMinimumWidth(150)
        self.temps.setFixedHeight(32)

        # le numéro de l'image sous la tête, compté depuis 1 (comme les images rendues : image_0001…) ; rendu de N en N,
        # celui de l'image rendue à l'écran (1, 11, 21…)
        self._ips, self._pas, self._nb, self._numeros, self._t = None, 1, None, [], 0.0
        self.image = QLabel("—")
        self.image.setObjectName("image")
        self.image.setFont(police)
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumWidth(90)
        self.image.setFixedHeight(32)
        self.image.setToolTip("Numéro de l'image sous la tête de lecture, à partir de 1 (IPS du script) ; "
                              "images rendues de N en N (PAS_IMAGES du script) : celle qui est à l'écran ; "
                              "après la dernière image (NB_IMAGES du script), reste sur elle ; portions rendues "
                              "(NUMEROS_IMAGES du script) : leurs vrais numéros, « noir » entre elles")

        boutons = QWidget()
        h = QHBoxLayout(boutons)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self._boutons = {}
        for nom, signal, aide in (("debut", self.debut, "Début (Origine)"),
                                  ("recul", self.recul, "Reculer de 5 s"),
                                  ("stop", self.stop, "Stop : arrête et revient où la lecture a commencé"),
                                  ("lecture", self.lecture, "Lecture / pause (Espace)"),
                                  ("avance", self.avance, "Avancer de 5 s"),
                                  ("boucle", None, "Lecture en boucle de l'aperçu")):
            b = QToolButton()
            b.setIcon(icone(nom))
            b.setIconSize(QSize(16, 16))
            b.setFixedSize(36, 32)          # même hauteur que l'afficheur : les titres restent alignés
            b.setToolTip(aide)
            b.setFocusPolicy(Qt.NoFocus)
            if signal is None:
                b.setCheckable(True)
                b.toggled.connect(self.boucle)
            else:
                b.clicked.connect(signal)
            h.addWidget(b)
            self._boutons[nom] = b
        h.addSpacing(12)
        b = QToolButton()
        b.setIcon(icone("grille"))
        b.setIconSize(QSize(16, 16))
        b.setFixedSize(36, 32)
        b.setCheckable(True)
        b.setChecked(True)
        b.setFocusPolicy(Qt.NoFocus)
        b.setToolTip("Grille d'accrochage, zone de sécurité et poignées des textes sur l'aperçu (ceux qui sont à "
                     "l'écran à ce moment), à faire glisser")
        b.toggled.connect(self.textes)
        h.addWidget(b)
        self._boutons["textes"] = b

        ligne = QHBoxLayout(self)             # centré : un ressort de chaque côté
        ligne.setContentsMargins(6, 4, 6, 4)
        ligne.setSpacing(14)
        ligne.addStretch(1)
        ligne.addWidget(_bloc("TEMPS", self.temps))
        ligne.addWidget(_bloc("IMAGE", self.image))
        ligne.addWidget(_bloc("TRANSPORT", boutons))
        ligne.addStretch(1)

    def set_temps(self, t):
        t = max(0.0, t)
        self._t = t
        self.temps.setText(f"{int(t // 60)}:{t % 60:06.3f}")
        # l'image n commence à (n - 1) / IPS ; la marge (1/20 d'image) absorbe les arrondis : positions du lecteur
        # en millisecondes, pas d'une image cumulé par les flèches
        if not self._ips:
            self.image.setText("—")
            return
        if self._numeros:
            # les images rendues : le montage commence à la première ; chacune reste PAS images, puis noir
            n = int(t * self._ips + 0.05) + self._numeros[0]
            if self._nb:
                n = min(n, self._nb)        # dernière image tenue (fin du film) : le compteur reste sur elle
            rendue = self._numeros[max(0, bisect.bisect_right(self._numeros, n) - 1)]
            self.image.setText(f"{rendue}" if n - rendue < self._pas else "noir")
            return
        n = int(t * self._ips + 0.05)
        if self._nb:
            n = min(n, self._nb - 1)        # dernière image tenue (fin du film) : le compteur reste sur elle
        self.image.setText(f"{n - n % self._pas + 1}")

    def set_ips(self, ips, pas=1, nb=None, numeros=None):
        """Images par seconde du film (variable IPS du script), None si inconnues : l'afficheur IMAGE montre « — » ;
        `pas` : images rendues de pas en pas (variable PAS_IMAGES), l'afficheur montre celle qui est à l'écran ;
        `nb` : numéro de la dernière image du film (variable NB_IMAGES), au-delà l'afficheur reste sur elle ;
        `numeros` : numéros des images rendues (variable NUMEROS_IMAGES), le montage commençant à la première."""
        self._ips, self._pas, self._nb, self._numeros = ips, max(1, pas), nb, sorted(numeros or [])
        self.set_temps(self._t)

    def set_lecture(self, en_cours):
        self._boutons["lecture"].setIcon(icone("pause" if en_cours else "lecture"))

    def set_textes(self, oui):
        self._boutons["textes"].setChecked(oui)
