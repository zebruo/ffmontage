"""Vue de l'aperçu : la vidéo dans une scène en pixels du film (0..L × 0..H), et par-dessus une poignée par texte
(réglage @Piste.position) qu'on fait glisser à la souris, avec une grille d'accrochage et la zone de sécurité.

Pendant le glissement, un fantôme du texte (sa police, sa taille, sa couleur) suit la poignée, aimantée aux lignes de
la grille (aux tiers, au centre, aux bords de la zone de sécurité) ; au lâcher, la nouvelle position est envoyée
(signal deplace). La vidéo, elle, ne change qu'au prochain aperçu.
"""
from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView

AIMANT = 10          # pixels de l'écran : distance à laquelle la poignée se colle à une ligne de la grille
CASES = (16, 9)      # la grille : 16 colonnes, 9 rangées (des carrés en 16/9)
SECURITE = 0.05      # zone de sécurité des titres : 5 % de marge de chaque côté (EBU R 95)
ACTION = 0.035       # zone de sécurité de l'action : 3,5 %


def lignes_grille(l, h):
    """Les lignes d'accrochage : ([x…], [y…]) — grille, tiers, centre, bords de la zone de sécurité."""
    xs = {l * k / CASES[0] for k in range(CASES[0] + 1)} | {l / 3, l * 2 / 3, l * SECURITE, l * (1 - SECURITE)}
    ys = {h * k / CASES[1] for k in range(CASES[1] + 1)} | {h / 3, h * 2 / 3, h * SECURITE, h * (1 - SECURITE)}
    return sorted(xs), sorted(ys)


class GrilleApercu(QGraphicsItem):
    """La grille d'accrochage et les zones de sécurité, par-dessus la vidéo (traits fins quel que soit le zoom)."""

    def __init__(self, vue):
        super().__init__()
        self.vue = vue
        self.setZValue(8)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def boundingRect(self):
        l, h = self.vue.taille_film()
        return QRectF(0, 0, l, h)

    def paint(self, p, option, widget=None):
        l, h = self.vue.taille_film()

        def trait(couleur, style=Qt.SolidLine):
            stylo = QPen(couleur, 1, style)
            stylo.setCosmetic(True)
            p.setPen(stylo)

        trait(QColor(255, 255, 255, 28))                     # la grille
        for k in range(1, CASES[0]):
            p.drawLine(QPointF(l * k / CASES[0], 0), QPointF(l * k / CASES[0], h))
        for k in range(1, CASES[1]):
            p.drawLine(QPointF(0, h * k / CASES[1]), QPointF(l, h * k / CASES[1]))
        trait(QColor(255, 255, 255, 60))                     # les tiers
        for f in (1 / 3, 2 / 3):
            p.drawLine(QPointF(l * f, 0), QPointF(l * f, h))
            p.drawLine(QPointF(0, h * f), QPointF(l, h * f))
        trait(QColor(255, 255, 255, 90), Qt.DashLine)       # le centre
        p.drawLine(QPointF(l / 2, 0), QPointF(l / 2, h))
        p.drawLine(QPointF(0, h / 2), QPointF(l, h / 2))
        p.setBrush(Qt.NoBrush)
        trait(QColor(255, 215, 94, 80), Qt.DotLine)          # zone de l'action
        p.drawRect(QRectF(l * ACTION, h * ACTION, l * (1 - 2 * ACTION), h * (1 - 2 * ACTION)))
        trait(QColor(255, 215, 94, 170), Qt.DashLine)        # zone de sécurité des titres
        p.drawRect(QRectF(l * SECURITE, h * SECURITE, l * (1 - 2 * SECURITE), h * (1 - 2 * SECURITE)))


class PoigneeTexte(QGraphicsObject):
    """Une poignée : croix + nom ; le fantôme du texte quand on la survole ou la déplace."""
    lachee = Signal(str, QPointF)

    def __init__(self, vue):
        super().__init__()
        self.vue = vue
        self.donnees = {}
        self._survol = self._prise = False
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(10)

    def poser(self, donnees):
        self.prepareGeometryChange()
        self.donnees = donnees
        if not self._prise:
            self.setPos(QPointF(*donnees["position"]))
        # un texte à l'écran au moment de la tête passe devant (deux poignées peuvent se chevaucher)
        actif = donnees.get("actif")
        self.setOpacity(0.4 if actif is False else 1.0)
        self.setZValue(12 if actif else 10 if actif is False else 11)
        self.setToolTip(f"{donnees['nom']} : ({int(self.pos().x())}, {int(self.pos().y())})\n"
                        f"Glisser pour déplacer le texte : il s'accroche à la grille (Maj : sans aimant)")
        self.update()

    def _police(self):
        f = QFont(self.donnees.get("police") or "Arial")
        f.setPixelSize(max(4, int(self.donnees.get("taille") or 48)))
        f.setItalic(bool(self.donnees.get("italique")))
        return f

    def _cadre_texte(self):
        lignes = str(self.donnees.get("texte") or self.donnees.get("nom", "")).split("\n")
        fm = QFontMetricsF(self._police())
        largeur = max(fm.horizontalAdvance(l) for l in lignes)
        hauteur = fm.height() * len(lignes)
        return QRectF(-largeur / 2, -hauteur / 2, largeur, hauteur)

    def boundingRect(self):
        echelle = self.vue.echelle_inverse()
        poignee = QRectF(-10, -10, 20, 20)
        poignee = QRectF(poignee.topLeft() * echelle, poignee.size() * echelle)
        etiquette = QRectF(12 * echelle, -10 * echelle, 260 * echelle, 20 * echelle)
        cadre = poignee.united(etiquette)
        if self.donnees.get("texte"):
            cadre = cadre.united(self._cadre_texte())
        return cadre.adjusted(-4, -4, 4, 4)

    def paint(self, p, option, widget=None):
        echelle = self.vue.echelle_inverse()
        couleur = QColor(self.donnees.get("couleur") or "#ffffff")
        # le fantôme du texte (pas de fantôme sans texte unique : les légendes, par exemple, en ont plusieurs)
        if (self._survol or self._prise) and self.donnees.get("texte"):
            p.setFont(self._police())
            p.setPen(QColor(0, 0, 0, 160))
            cadre = self._cadre_texte()
            p.drawText(cadre.translated(2 * echelle, 2 * echelle), Qt.AlignCenter, str(self.donnees["texte"]))
            couleur.setAlpha(220)
            p.setPen(couleur)
            p.drawText(cadre, Qt.AlignCenter, str(self.donnees["texte"]))
            p.setPen(QPen(QColor(255, 255, 255, 90), 1 * echelle, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(cadre)
        # la poignée : un petit rond transparent et une croix fine (le point exact se voit au croisement)
        actif = self._survol or self._prise
        r = 5 * echelle
        p.setPen(QPen(QColor(255, 255, 255, 220 if actif else 160), 1.2 * echelle))
        p.setBrush(QBrush(QColor(76, 155, 232, 110 if actif else 55)))
        p.drawEllipse(QPointF(0, 0), r, r)
        p.drawLine(QPointF(-r - 3 * echelle, 0), QPointF(r + 3 * echelle, 0))
        p.drawLine(QPointF(0, -r - 3 * echelle), QPointF(0, r + 3 * echelle))
        # le nom
        f = QFont()
        f.setPixelSize(int(11 * echelle))
        f.setBold(True)
        p.setFont(f)
        texte = self.donnees.get("nom", "")
        if self._prise:
            texte += f"  ({int(self.pos().x())}, {int(self.pos().y())})"
        p.setPen(QColor(0, 0, 0, 160))
        p.drawText(QPointF(13 * echelle, 4 * echelle), texte)
        p.setPen(QColor(255, 255, 255, 230))
        p.drawText(QPointF(12 * echelle, 3 * echelle), texte)

    def itemChange(self, changement, valeur):
        if changement == QGraphicsItem.ItemPositionChange and self._prise:
            x, y = valeur.x(), valeur.y()
            gx = gy = None
            if not self.vue.sans_aimant:
                seuil = AIMANT * self.vue.echelle_inverse()
                xs, ys = lignes_grille(*self.vue.taille_film())
                proche = lambda v, lignes: min(lignes, key=lambda c: abs(c - v))
                if abs(proche(x, xs) - x) <= seuil:
                    x = gx = proche(x, xs)
                if abs(proche(y, ys) - y) <= seuil:
                    y = gy = proche(y, ys)
            self.vue.montrer_guides(gx, gy)
            return QPointF(round(x), round(y))
        if changement == QGraphicsItem.ItemPositionHasChanged:
            self.update()
        return super().itemChange(changement, valeur)

    def hoverEnterEvent(self, e):
        self._survol = True
        self.update()

    def hoverLeaveEvent(self, e):
        self._survol = False
        self.update()

    def mousePressEvent(self, e):
        self._prise = True
        self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        self.vue.sans_aimant = bool(e.modifiers() & Qt.ShiftModifier)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self._prise = False
        self.setCursor(Qt.OpenHandCursor)
        self.vue.montrer_guides(None, None)
        if (int(self.pos().x()), int(self.pos().y())) != tuple(int(v) for v in self.donnees["position"]):
            self.lachee.emit(self.donnees["reglage"], self.pos())
        self.update()


class VueApercu(QGraphicsView):
    deplace = Signal(str, tuple)        # réglage de position, nouvelle valeur (x, y)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setBackgroundBrush(QColor("#111317"))
        self.setFocusPolicy(Qt.ClickFocus)
        self.sans_aimant = False
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self._l, self._h = 1920, 1080
        self.fond = self.scene_.addRect(QRectF(0, 0, self._l, self._h), QPen(Qt.NoPen), QBrush(QColor("#0b0c0f")))
        self.video = QGraphicsVideoItem()
        self.video.setSize(QSizeF(self._l, self._h))
        self.scene_.addItem(self.video)
        self.message = self.scene_.addText("Pas d'aperçu.\nF6 pour le calculer.")
        self.message.setDefaultTextColor(QColor("#6b7080"))
        self.grille = GrilleApercu(self)
        self.scene_.addItem(self.grille)
        stylo = QPen(QColor("#ffd75e"), 1.5, Qt.DashLine)
        stylo.setCosmetic(True)
        self._guides = [self.scene_.addLine(0, 0, 0, 0, stylo) for _ in range(2)]
        for g in self._guides:
            g.setZValue(9)
            g.hide()
        self._poignees = {}
        self._poignees_visibles = True
        self._placer_message()

    # ───── géométrie
    def taille_film(self):
        return self._l, self._h

    def set_taille_film(self, largeur, hauteur):
        if (largeur, hauteur) == (self._l, self._h) or largeur <= 0 or hauteur <= 0:
            return
        self._l, self._h = largeur, hauteur
        self.fond.setRect(QRectF(0, 0, largeur, hauteur))
        self.video.setSize(QSizeF(largeur, hauteur))
        self.grille.prepareGeometryChange()
        self._placer_message()
        self._ajuster()

    def echelle_inverse(self):
        """Combien de pixels du film pour un pixel de l'écran (pour dessiner les poignées à taille constante)."""
        m = self.transform().m11()
        return 1 / m if m > 0 else 1.0

    def _placer_message(self):
        f = QFont()
        f.setPixelSize(int(self._h / 22))
        self.message.setFont(f)
        r = self.message.boundingRect()
        self.message.setPos((self._l - r.width()) / 2, (self._h - r.height()) / 2)

    def _ajuster(self):
        self.setSceneRect(QRectF(0, 0, self._l, self._h))
        self.fitInView(QRectF(0, 0, self._l, self._h), Qt.KeepAspectRatio)
        for p in self._poignees.values():
            p.prepareGeometryChange()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._ajuster()

    def showEvent(self, e):
        super().showEvent(e)
        self._ajuster()

    def set_apercu_present(self, oui):
        self.message.setVisible(not oui)
        self.video.setVisible(oui)

    def montrer_guides(self, x, y):
        """Les lignes jaunes de l'aimant : la verticale x et l'horizontale y où la poignée est collée (None : rien)."""
        v, h = self._guides
        if x is not None:
            v.setLine(x, 0, x, self._h)
        if y is not None:
            h.setLine(0, y, self._l, y)
        v.setVisible(x is not None)
        h.setVisible(y is not None)

    # ───── les textes
    def set_poignees_visibles(self, oui):
        """Bouton T : les poignées des textes et la grille d'accrochage."""
        self._poignees_visibles = oui
        self.grille.setVisible(oui)
        for p in self._poignees.values():
            p.setVisible(oui and p.donnees.get("actif") is not False)

    def set_textes(self, textes):
        """textes : [{reglage, nom, position (x, y), texte, police, taille, couleur, italique, actif}].
        Seules les poignées des textes à l'écran au moment de la tête sont montrées (actif vrai, ou inconnu)."""
        vus = set()
        for d in textes:
            vus.add(d["reglage"])
            p = self._poignees.get(d["reglage"])
            if p is None:
                p = PoigneeTexte(self)
                p.lachee.connect(lambda nom, pos: self.deplace.emit(nom, (int(pos.x()), int(pos.y()))))
                self.scene_.addItem(p)
                self._poignees[d["reglage"]] = p
            p.poser(d)
            if not p._prise:
                p.setVisible(self._poignees_visibles and d.get("actif") is not False)
        for nom in list(self._poignees):
            if nom not in vus:
                self.scene_.removeItem(self._poignees.pop(nom))

    def keyPressEvent(self, e):
        # les flèches et Début / Fin pilotent la tête de lecture (fenêtre), pas le défilement de la vue
        if e.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End):
            e.ignore()
            return
        super().keyPressEvent(e)
