"""Éditeur du script : coloration Python, numéros de ligne, marques de couleur des pistes dans la marge, et
surlignage des réglages actifs sous la tête de lecture.

Le document de l'éditeur est la version de travail du script : les changements faits depuis le panneau ou la
timeline y sont écrits comme une frappe (remplacer_valeurs), si bien qu'un seul historique sert à tout annuler.
"""
import re

from PySide6.QtCore import QRect, QRegularExpression, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from . import reglages


def _u16(texte):
    """Longueur en unités UTF-16 (celles de Qt) d'un texte Python."""
    return len(texte.encode("utf-16-le")) // 2


def _format(couleur, gras=False, italique=False):
    f = QTextCharFormat()
    f.setForeground(QColor(couleur))
    if gras:
        f.setFontWeight(QFont.Bold)
    if italique:
        f.setFontItalic(True)
    return f


class ColorationPython(QSyntaxHighlighter):
    MOTS = ("and as assert async await break class continue def del elif else except finally for from global if "
            "import in is lambda nonlocal not or pass raise return try while with yield match case").split()
    CONSTANTES = ("True", "False", "None", "self")
    FONCTIONS = ("print len range enumerate zip map filter sorted reversed min max sum abs round int float str list "
                 "dict set tuple open isinstance next any all repr format").split()

    def __init__(self, document):
        super().__init__(document)
        self.couleurs_pistes = {}
        self.f_mot = _format("#c586c0")
        self.f_constante = _format("#569cd6")
        self.f_fonction = _format("#dcdcaa")
        self.f_nombre = _format("#b5cea8")
        self.f_texte = _format("#ce9178")
        self.f_commentaire = _format("#6a9955", italique=True)
        self.f_majuscules = _format("#9cdcfe")
        self.f_bloc = _format("#4C9BE8", gras=True)
        self.f_bornes = _format("#d19a66")
        self.f_etiquette = _format("#e5c07b", gras=True)
        self.regles = [
            (QRegularExpression(r"\b(" + "|".join(self.MOTS) + r")\b"), self.f_mot),
            (QRegularExpression(r"\b(" + "|".join(self.CONSTANTES) + r")\b"), self.f_constante),
            (QRegularExpression(r"\b(" + "|".join(self.FONCTIONS) + r")(?=\()"), self.f_fonction),
            (QRegularExpression(r"\b[A-Z][A-Z0-9_]{1,}\b"), self.f_majuscules),
            (QRegularExpression(r"\b\d+(\.\d*)?([eE][-+]?\d+)?\b|\.\d+\b"), self.f_nombre),
        ]
        self.chaine = QRegularExpression(r"""[rRbBuUfF]{0,2}("([^"\\]|\\.)*"|'([^'\\]|\\.)*')""")

    def highlightBlock(self, texte):
        for regex, fmt in self.regles:
            it = regex.globalMatch(texte)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)
        # chaînes, puis commentaires (un # dans une chaîne n'est pas un commentaire)
        chaines = []
        it = self.chaine.globalMatch(texte)
        while it.hasNext():
            m = it.next()
            chaines.append((m.capturedStart(), m.capturedEnd()))
            self.setFormat(m.capturedStart(), m.capturedLength(), self.f_texte)
        diese = next((i for i, c in enumerate(texte) if c == "#" and not any(a <= i < b for a, b in chaines)), -1)
        if diese >= 0:
            commentaire = texte[diese:]
            fmt = self.f_bloc if reglages.DEBUT_BLOC.match(commentaire) or reglages.FIN_BLOC.match(commentaire) \
                or reglages.SECTION.match(commentaire) else self.f_commentaire
            self.setFormat(diese, len(texte) - diese, fmt)
            for m in reglages.BORNES.finditer(commentaire):
                self.setFormat(diese + m.start(), m.end() - m.start(), self.f_bornes)
            for m in re.finditer(r"@[\w.=,çÇ]+", commentaire):
                piste = m.group(0)[1:].split(".")[0]
                f = QTextCharFormat(self.f_etiquette)
                if piste in self.couleurs_pistes:
                    f.setForeground(self.couleurs_pistes[piste])
                self.setFormat(diese + m.start(), m.end() - m.start(), f)
        self._triples(texte)

    def _triples(self, texte):
        """Chaînes sur plusieurs lignes (docstrings) : état 1 dans « \"\"\" », 2 dans « ''' »."""
        self.setCurrentBlockState(0)
        debut = 0
        etat = self.previousBlockState()
        while True:
            if etat in (1, 2):
                fin = texte.find('"""' if etat == 1 else "'''", debut)
                if fin < 0:
                    self.setFormat(debut, len(texte) - debut, self.f_texte)
                    self.setCurrentBlockState(etat)
                    return
                self.setFormat(debut, fin + 3 - debut, self.f_texte)
                debut, etat = fin + 3, 0
            positions = [(texte.find(q, debut), e) for q, e in (('"""', 1), ("'''", 2)) if texte.find(q, debut) >= 0]
            if not positions:
                return
            p, etat = min(positions)
            diese = texte.find("#", debut)
            if 0 <= diese < p:
                return
            debut = p + 3
            self.setFormat(p, 3, self.f_texte)


class _Marge(QWidget):
    def __init__(self, editeur):
        super().__init__(editeur)
        self.editeur = editeur

    def sizeHint(self):
        return QSize(self.editeur.largeur_marge(), 0)

    def paintEvent(self, ev):
        self.editeur.peindre_marge(ev)


class EditeurScript(QPlainTextEdit):
    reglage_sous_curseur = Signal(str)      # nom du réglage où se trouve le curseur ("" : aucun)

    def __init__(self, parent=None):
        super().__init__(parent)
        police = QFont("Consolas")
        police.setStyleHint(QFont.Monospace)
        police.setPointSizeF(10)
        self.setFont(police)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setStyleSheet("QPlainTextEdit { background: #1b1d22; color: #d4d4d4; border: none; "
                           "selection-background-color: #264f78; }")
        self.coloration = ColorationPython(self.document())
        self._marge = _Marge(self)
        self._marques = {}              # {numéro de ligne: QColor}
        self._suivi = []                # surlignage des réglages sous la tête : [(début, fin, QColor)]
        self._ligne_erreur = None
        self._reglages = []
        self.blockCountChanged.connect(lambda _: self._maj_largeur())
        self.updateRequest.connect(self._defiler_marge)
        self.cursorPositionChanged.connect(self._curseur)
        self._maj_largeur()

    # ───── texte
    def charger(self, texte):
        """Nouveau texte (ouverture, rechargement) : l'historique d'annulation repart de zéro."""
        defilement = self.verticalScrollBar().value()
        self.setPlainText(texte)
        self.document().setModified(False)
        self.verticalScrollBar().setValue(defilement)

    def texte(self):
        return self.toPlainText()

    def _position(self, ligne, colonne):
        bloc = self.document().findBlockByNumber(ligne - 1)
        return bloc.position() + _u16(bloc.text()[:colonne]) if bloc.isValid() else None

    def remplacer_valeurs(self, changements, fusionner=False):
        """Écrit {nom: texte Python} à la place des valeurs du bloc de réglages, en une seule étape d'annulation
        (fusionnée avec la précédente si demandé). Lève ValueError si le script deviendrait invalide."""
        texte = self.texte()
        reglages.remplacer(texte, changements)          # vérifie que le résultat reste du Python valide
        bloc = reglages.lire(texte)
        cibles = sorted(((r.position, changements[r.nom]) for r in bloc.reglages
                         if r.nom in changements and r.modifiable and r.position), reverse=True)
        if not cibles:
            return
        defilement = self.verticalScrollBar().value(), self.horizontalScrollBar().value()
        curseur = QTextCursor(self.document())
        curseur.joinPreviousEditBlock() if fusionner else curseur.beginEditBlock()
        for (l, c, lf, cf), source in cibles:
            curseur.setPosition(self._position(l, c))
            curseur.setPosition(self._position(lf, cf), QTextCursor.KeepAnchor)
            curseur.insertText(source)
        curseur.endEditBlock()
        self.verticalScrollBar().setValue(defilement[0])
        self.horizontalScrollBar().setValue(defilement[1])

    # ───── liens avec les réglages et la timeline
    def set_reglages(self, bloc, couleurs):
        """couleurs : {nom de réglage: QColor de sa piste} ; colore la marge et les étiquettes @Piste."""
        self._reglages = bloc.tous
        self._marques = {}
        for r in bloc.tous:
            if r.nom in couleurs:
                for ligne in range(r.ligne, (r.position[2] if r.position else r.ligne) + 1):
                    self._marques[ligne] = couleurs[r.nom]
        pistes = {p: couleurs[r.nom] for r in bloc.tous for p, _ in r.etiquettes if r.nom in couleurs}
        if pistes != self.coloration.couleurs_pistes:
            self.coloration.couleurs_pistes = pistes
            self.coloration.rehighlight()
        self._marge.update()

    def set_erreur(self, ligne):
        if ligne != self._ligne_erreur:
            self._ligne_erreur = ligne
            self._maj_selections()

    def suivre(self, zones):
        """zones : [(réglage, index dans la liste ou -1, QColor)] actifs sous la tête de lecture."""
        suivi = []
        for r, k, couleur in zones:
            pos = r.elements[k] if 0 <= k < len(r.elements) else r.position
            if not pos:
                continue
            a, b = self._position(pos[0], pos[1]), self._position(pos[2], pos[3])
            if a is not None and b is not None:
                suivi.append((a, b, couleur))
        if suivi != self._suivi:
            self._suivi = suivi
            self._maj_selections()

    def aller_a(self, r, k=-1):
        """Amène la vue sur la valeur d'un réglage (ou l'élément k d'une liste) et la sélectionne."""
        pos = r.elements[k] if 0 <= k < len(r.elements) else r.position
        if not pos:
            return
        curseur = self.textCursor()
        curseur.setPosition(self._position(pos[0], pos[1]))
        curseur.setPosition(self._position(pos[2], pos[3]), QTextCursor.KeepAnchor)
        self.setTextCursor(curseur)
        self.centerCursor()

    def _curseur(self):
        self._maj_selections()
        ligne = self.textCursor().blockNumber() + 1
        nom = next((r.nom for r in self._reglages if r.position and r.ligne <= ligne <= r.position[2]), "")
        self.reglage_sous_curseur.emit(nom)

    def _maj_selections(self):
        selections = []
        ligne = QTextEdit.ExtraSelection()
        ligne.format.setBackground(QColor(255, 255, 255, 10))
        ligne.format.setProperty(QTextFormat.FullWidthSelection, True)
        ligne.cursor = self.textCursor()
        ligne.cursor.clearSelection()
        selections.append(ligne)
        for a, b, couleur in self._suivi:
            pleine = QTextEdit.ExtraSelection()
            fond = QColor(couleur)
            fond.setAlpha(38)
            pleine.format.setBackground(fond)
            pleine.format.setProperty(QTextFormat.FullWidthSelection, True)
            pleine.cursor = QTextCursor(self.document())
            pleine.cursor.setPosition(a)
            selections.append(pleine)
            valeur = QTextEdit.ExtraSelection()
            fond = QColor(couleur)
            fond.setAlpha(120)
            valeur.format.setBackground(fond)
            valeur.format.setForeground(QColor("#ffffff"))
            valeur.cursor = QTextCursor(self.document())
            valeur.cursor.setPosition(a)
            valeur.cursor.setPosition(b, QTextCursor.KeepAnchor)
            selections.append(valeur)
        if self._ligne_erreur:
            erreur = QTextEdit.ExtraSelection()
            erreur.format.setBackground(QColor(224, 108, 117, 60))
            erreur.format.setProperty(QTextFormat.FullWidthSelection, True)
            erreur.cursor = QTextCursor(self.document().findBlockByNumber(self._ligne_erreur - 1))
            selections.append(erreur)
        self.setExtraSelections(selections)

    # ───── saisie : indentation
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Tab and not e.modifiers():
            self.insertPlainText("    ")
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers():
            ligne = self.textCursor().block().text()[:self.textCursor().positionInBlock()]
            retrait = re.match(r"\s*", ligne).group(0)
            if ligne.rstrip().endswith(":"):
                retrait += "    "
            self.insertPlainText("\n" + retrait)
            self.ensureCursorVisible()
            return
        super().keyPressEvent(e)

    # ───── marge
    def largeur_marge(self):
        return 14 + self.fontMetrics().horizontalAdvance("9") * max(3, len(str(self.blockCount())))

    def _maj_largeur(self):
        self.setViewportMargins(self.largeur_marge(), 0, 0, 0)

    def _defiler_marge(self, rect, dy):
        if dy:
            self._marge.scroll(0, dy)
        else:
            self._marge.update(0, rect.y(), self._marge.width(), rect.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        r = self.contentsRect()
        self._marge.setGeometry(QRect(r.left(), r.top(), self.largeur_marge(), r.height()))

    def peindre_marge(self, ev):
        p = QPainter(self._marge)
        p.fillRect(ev.rect(), QColor("#1b1d22"))
        bloc = self.firstVisibleBlock()
        n = bloc.blockNumber()
        haut = round(self.blockBoundingGeometry(bloc).translated(self.contentOffset()).top())
        hauteur = round(self.blockBoundingRect(bloc).height())
        courante = self.textCursor().blockNumber()
        largeur = self._marge.width()
        while bloc.isValid() and haut <= ev.rect().bottom():
            if bloc.isVisible() and haut + hauteur >= ev.rect().top():
                if (couleur := self._marques.get(n + 1)) is not None:
                    p.fillRect(QRect(largeur - 5, haut, 3, hauteur), couleur)
                p.setPen(QColor("#c8ccd4") if n == courante else QColor("#5d6270"))
                p.drawText(QRect(0, haut, largeur - 9, hauteur), Qt.AlignRight | Qt.AlignVCenter, str(n + 1))
            bloc = bloc.next()
            haut += hauteur
            hauteur = round(self.blockBoundingRect(bloc).height())
            n += 1
        p.end()
