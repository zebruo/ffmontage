"""Timeline : une piste par nom d'étiquette @Piste.role des réglages ; dessous, en gris, les repères de temps trouvés
dans la commande ffmpeg (lecture seule).

Glisser un bord ou un bloc modifie les réglages correspondants (pas de 0,1 s ; Alt : 0,01 s). Près de la tête de
lecture, d'un autre bord ou d'un repère, il s'y colle (aimant ; Maj : sans aimant). Ctrl+molette : zoom.
Un clic ailleurs déplace la tête de lecture.
"""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QScrollArea, QToolTip, QWidget

from .reglages import ROLES_TEMPS

COULEURS = ["#4C9BE8", "#E8A33D", "#5BBF7A", "#C46BD6", "#E26D6D", "#3FC1C0", "#D9C84A", "#8A8FE8"]
ENTETE, REGLE, H_PISTE, H_SON, H_ANALYSE, ESPACE = 130, 26, 30, 44, 16, 22
H_MEDIA, H_COURBE, H_TRANSITION = 46, 30, 26
COULEUR_SON = "#3FC1C0"
COULEUR_COURBE = "#ffd75e"
PRISE = 6        # tolérance en pixels pour attraper un bord
AIMANT = 8       # distance en pixels à laquelle un bord glissé se colle à la tête ou à un repère


def _nombre(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _mobile(r):
    return r is not None and r.modifiable and _nombre(r.valeur) is not None


def _liste_mobile(r):
    return r is not None and r.modifiable and isinstance(r.valeur, (list, tuple))


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    return str(v)


class Timeline(QWidget):
    modifie = Signal(dict)          # {nom: nouvelle valeur}
    deplacement = Signal(float)     # la tête de lecture demandée (s)
    choisi = Signal(str, int)       # clic sur un bloc ou un repère : nom du réglage, index dans sa liste (-1)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)     # un clic lui donne le clavier : les flèches déplacent la tête (fenetre.py)
        self._pistes = []           # [{"nom", "debut", "fin", "duree", "marques", "intervalles", "listes"}]
        self._par_nom = {}
        self._valeurs = {}          # valeurs affichées (modifiées en direct pendant un glissement)
        self._analyse = []          # [(ligne, [Intervalle])]
        self._sons = []             # [(nom, décalage, pas, niveaux)] : formes d'onde des fichiers audio
        self._medias = []           # images et vidéos d'entrée (ffmpeg_analyse.medias)
        self._courbes_medias = {}   # {index d'entrée: [courbes]} : l'intensité de chaque image
        self._courbes_libres = []   # les autres courbes (volume…)
        self._transitions = []      # fondus (ffmpeg_analyse.transitions)
        self._vignettes = {}        # {chemin: QPixmap}
        self._calcul = None         # (début, fin, fraction) de l'aperçu en cours de calcul
        self._duree_cmd = None
        self._tete = 0.0
        self._apercu = None         # (début, fin) de l'extrait d'aperçu chargé
        self._zoom = 1.0
        self.pas_image = 0.04       # durée d'une image du film (1/IPS), pour les flèches
        self._surbrillance = set()  # réglages mis en évidence (celui sous le curseur de l'éditeur)
        self._textes_pistes = {}    # {piste: texte}
        self._prise = None
        self._recalcul = None
        self._ajuster_hauteur()

    # ───── données
    def set_recalcul(self, fonction):
        """fonction(remplacements) → toutes les valeurs, pour suivre en direct les valeurs calculées."""
        self._recalcul = fonction

    def set_bloc(self, bloc):
        if self._prise:
            return
        pistes = {}
        for r in bloc.tous:
            for nom, role in r.etiquettes:
                if role not in ROLES_TEMPS:     # texte, police, couleur… : l'apparence, pas le temps
                    continue
                p = pistes.setdefault(nom, {"nom": nom, "debut": None, "fin": None, "duree": None,
                                            "marques": [], "intervalles": [], "listes": []})
                if role == "marque":
                    p["marques"].append(r)
                elif role == "intervalles":
                    p["intervalles"].append(r)
                elif role == "marques":
                    p["listes"].append(r)
                else:
                    p[role] = r
        self._pistes = list(pistes.values())
        self._par_nom = {r.nom: r for r in bloc.tous}
        # le texte d'une piste (@Piste.texte), écrit dans son bloc
        self._textes_pistes = {nom: str(r.valeur) for r in bloc.tous if r.connu
                               for nom, role in r.etiquettes if role == "texte"}
        self._valeurs = {r.nom: r.valeur for r in bloc.tous if r.connu}
        self._ajuster_hauteur()
        self.update()

    def set_analyse(self, intervalles, duree, noms=None):
        """Les repères trouvés dans la commande ffmpeg, une rangée par chaîne ; noms : {étiquette: nom parlant}."""
        lignes = {}
        for iv in intervalles:
            lignes.setdefault(iv.ligne, []).append(iv)
        self._analyse = [((noms or {}).get(ligne, ligne), ivs) for ligne, ivs in lignes.items()]
        self._duree_cmd = duree
        self._ajuster_hauteur()
        self.update()

    def set_tete(self, t):
        self._tete = t
        self.update()

    def tete(self):
        return self._tete

    def set_apercu(self, debut, fin):
        self._apercu = (debut, fin) if fin is not None else None
        self.update()

    def set_calcul(self, debut, fin, fraction, libelle="Aperçu"):
        """Calcul en cours sur [debut, fin] (aperçu ou export) : fraction faite (0 à 1), ou debut None quand c'est
        fini."""
        self._calcul = (debut, fin, max(0.0, min(1.0, fraction or 0.0)), libelle) if debut is not None else None
        self.update()

    def set_sons(self, sons):
        self._sons = sons
        self._ajuster_hauteur()
        self.update()

    def set_medias(self, medias, courbes, transitions):
        """Les images d'entrée (avec leur vignette et la courbe d'intensité qui les module), les autres courbes et
        les fondus, lus dans la commande ffmpeg."""
        indexes = {m["index"] for m in medias}
        self._medias = medias
        self._courbes_medias = {}
        self._courbes_libres = []
        for c in courbes:
            if c["entree"] in indexes:
                self._courbes_medias.setdefault(c["entree"], []).append(c)
            else:
                self._courbes_libres.append(c)
        self._transitions = transitions
        for m in medias:
            if m["vignette"] and m["vignette"] not in self._vignettes:
                image = QPixmap(m["vignette"])
                self._vignettes[m["vignette"]] = image.scaledToHeight(H_MEDIA - 10, Qt.SmoothTransformation) \
                    if not image.isNull() else None
        self._ajuster_hauteur()
        self.update()

    def duree(self):
        return self._total() / 1.04

    def set_surbrillance(self, noms):
        noms = set(noms)
        if noms != self._surbrillance:
            self._surbrillance = noms
            self.update()

    def couleurs_reglages(self):
        """{nom de réglage: QColor} : la couleur de la (première) piste de chaque réglage étiqueté."""
        couleurs = {}
        for i, p in enumerate(self._pistes):
            c = QColor(COULEURS[i % len(COULEURS)])
            for r in (p["debut"], p["fin"], p["duree"], *p["marques"], *p["intervalles"], *p["listes"]):
                if r:
                    couleurs.setdefault(r.nom, c)
        return couleurs

    def piste_active(self, nom, t):
        """La piste « nom » contient-elle le temps t ? None si elle n'a pas de temps sur la timeline."""
        p = next((p for p in self._pistes if p["nom"] == nom), None)
        if p is None:
            return None
        d, f = self._bornes(p)
        if d is not None:
            return d <= t <= (f if f is not None else self.duree())
        paires = [ab for r in p["intervalles"] for ab in self._paires(r)]
        return any(a <= t <= b for a, b in paires) if paires else None

    def actifs(self, t):
        """[(réglage, index ou -1, QColor)] : les blocs qui contiennent le temps t et les repères tout proches."""
        proche = 3 / self._echelle()
        sortie = []
        for i, p in enumerate(self._pistes):
            c = QColor(COULEURS[i % len(COULEURS)])
            d, f = self._bornes(p)
            if d is not None and d <= t <= (f if f is not None else self.duree()):
                sortie += [(r, -1, c) for r in (p["debut"], p["fin"], p["duree"]) if r]
            for m in p["marques"]:
                if (v := self._val(m)) is not None and abs(v - t) <= proche:
                    sortie.append((m, -1, c))
            for r in p["intervalles"]:
                sortie += [(r, k, c) for k, (a, b) in enumerate(self._paires(r)) if a <= t <= b]
            for r in p["listes"]:
                sortie += [(r, k, c) for k, v in enumerate(self._liste(r)) if abs(v - t) <= proche]
        return sortie

    # ───── géométrie
    def _total(self):
        fins = [self._duree_cmd or 0.0]
        for p in self._pistes:
            fins += [x for x in self._bornes(p) if x is not None]
            fins += [v for m in p["marques"] if (v := self._val(m)) is not None]
            fins += [b for r in p["intervalles"] for _, b in self._paires(r)]
            fins += [x for r in p["listes"] for x in self._liste(r)]
        fins += [iv.fin for _, ivs in self._analyse for iv in ivs]
        fins += [decalage + len(niveaux) * pas for _, decalage, pas, niveaux in self._sons]
        fins += [m["fin"] for m in self._medias] + [t["fin"] for t in self._transitions]
        return max(max(fins), 1.0) * 1.04

    def _duree_vue(self):
        return self._prise["total"] if self._prise and "total" in self._prise else self._total()

    def _echelle(self):
        return max(1e-6, (self.width() - ENTETE - 14) / self._duree_vue())

    def _x(self, t):
        return ENTETE + t * self._echelle()

    def _t(self, x):
        return (x - ENTETE) / self._echelle()

    def _val(self, r):
        return _nombre(self._valeurs.get(r.nom)) if r else None

    def _paires(self, r):
        v = self._valeurs.get(r.nom)
        if not isinstance(v, (list, tuple)):
            return []
        return [(float(e[0]), float(e[1])) for e in v
                if isinstance(e, (list, tuple)) and len(e) >= 2 and _nombre(e[0]) is not None and _nombre(e[1]) is not None]

    def _liste(self, r):
        v = self._valeurs.get(r.nom)
        return [float(x) for x in v if _nombre(x) is not None] if isinstance(v, (list, tuple)) else []

    def _bornes(self, p):
        d = self._val(p["debut"]) if p["debut"] else (0.0 if p["duree"] else None)    # sans début : depuis 0
        if p["fin"]:
            f = self._val(p["fin"])
        elif p["duree"] and d is not None:
            du = self._val(p["duree"])
            f = d + du if du is not None else None
        else:
            f = None
        if p["debut"] is None and f is not None:
            d = 0.0
        return d, f

    def _y_piste(self, i):
        return REGLE + i * H_PISTE

    def _y_son(self, i):
        return REGLE + len(self._pistes) * H_PISTE + i * H_SON

    def _y_media(self, i):
        return self._y_son(len(self._sons)) + i * H_MEDIA

    def _y_courbe(self, i):
        return self._y_media(len(self._medias)) + i * H_COURBE

    def _y_transitions(self):
        return self._y_courbe(len(self._courbes_libres))

    def _y_analyse(self):
        return self._y_transitions() + (H_TRANSITION if self._transitions else 0) + (ESPACE if self._analyse else 0)

    def _ajuster_hauteur(self):
        self.setMinimumHeight(max(120, int(self._y_analyse() + len(self._analyse) * H_ANALYSE + 10)))

    def _gauche_visible(self):
        return self.visibleRegion().boundingRect().left()

    # ───── zoom
    def _zone(self):
        w = self.parent()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parent()
        return w

    def wheelEvent(self, e):
        zone = self._zone()
        if not (e.modifiers() & Qt.ControlModifier) or zone is None:
            return super().wheelEvent(e)
        x = e.position().x()
        t = self._t(x)
        decalage = x - zone.horizontalScrollBar().value()
        self._zoom = min(80.0, max(1.0, self._zoom * (1.25 if e.angleDelta().y() > 0 else 0.8)))
        self.setMinimumWidth(0 if self._zoom == 1 else int(zone.viewport().width() * self._zoom))
        self.resize(max(zone.viewport().width(), self.minimumWidth()), self.height())
        zone.horizontalScrollBar().setValue(int(self._x(t) - decalage))
        e.accept()

    # ───── clavier
    def touche_tete(self, e):
        """Flèches : une image (Maj : 1 s, Ctrl : 10 s) ; Début / Fin. Renvoie False si la touche n'est pas pour la tête."""
        touche, mods = e.key(), e.modifiers()
        if touche in (Qt.Key_Left, Qt.Key_Right):
            pas = 10.0 if mods & Qt.ControlModifier else 1.0 if mods & Qt.ShiftModifier else self.pas_image
            t = self._tete + (pas if touche == Qt.Key_Right else -pas)
        elif touche in (Qt.Key_Home, Qt.Key_End):
            t = 0.0 if touche == Qt.Key_Home else self.duree()
        else:
            return False
        t = round(max(0.0, min(t, self.duree())), 4)
        self.set_tete(t)
        self.deplacement.emit(t)
        e.accept()
        return True

    def keyPressEvent(self, e):
        if not self.touche_tete(e):
            super().keyPressEvent(e)

    # ───── ce qui est sous la souris
    def _cible(self, pos):
        x, y = pos.x(), pos.y()
        if y < REGLE:
            return ("regle",)
        i = int((y - REGLE) // H_PISTE)
        if 0 <= i < len(self._pistes):
            p = self._pistes[i]
            for m in p["marques"]:
                if (v := self._val(m)) is not None and abs(x - self._x(v)) <= PRISE - 1:
                    return ("marque", p, m)
            for r in p["listes"]:
                for k, v in enumerate(self._liste(r)):
                    if abs(x - self._x(v)) <= PRISE - 1:
                        return ("lmarque", p, r, k)
            for r in p["intervalles"]:
                for k, (a, b) in enumerate(self._paires(r)):
                    if abs(x - self._x(a)) <= PRISE:
                        return ("iv_debut", p, r, k)
                    if abs(x - self._x(b)) <= PRISE:
                        return ("iv_fin", p, r, k)
                    if self._x(a) < x < self._x(b):
                        return ("iv_corps", p, r, k)
            d, f = self._bornes(p)
            if p["debut"] and d is not None and abs(x - self._x(d)) <= PRISE:
                return ("debut", p)
            if (p["fin"] or p["duree"]) and f is not None and abs(x - self._x(f)) <= PRISE:
                return ("fin", p)
            if d is not None and f is not None and self._x(d) < x < self._x(f):
                return ("corps", p)
            return ("piste", p)
        j = int((y - self._y_son(0)) // H_SON) if y >= self._y_son(0) else -1
        if 0 <= j < len(self._sons):
            return ("son", self._sons[j])
        j = int((y - self._y_media(0)) // H_MEDIA) if y >= self._y_media(0) else -1
        if 0 <= j < len(self._medias):
            return ("media", self._medias[j], self._t(x))
        j = int((y - self._y_courbe(0)) // H_COURBE) if y >= self._y_courbe(0) else -1
        if 0 <= j < len(self._courbes_libres):
            return ("courbe", self._courbes_libres[j], self._t(x))
        if self._transitions and self._y_transitions() <= y < self._y_transitions() + H_TRANSITION:
            t = self._t(x)
            return ("transition", [tr for tr in self._transitions if tr["debut"] - 0.3 <= t <= tr["fin"] + 0.3])
        ya = self._y_analyse()
        j = int((y - ya) // H_ANALYSE) if y >= ya else -1
        if 0 <= j < len(self._analyse):
            ligne, ivs = self._analyse[j]
            t, tol = self._t(x), 4 / self._echelle()
            return ("analyse", ligne, [iv for iv in ivs if iv.debut - tol <= t <= iv.fin + tol])
        return None

    def _mobilite(self, c):
        genre = c[0]
        if genre == "marque":
            return _mobile(c[2])
        if genre in ("lmarque", "iv_debut", "iv_fin", "iv_corps"):
            return _liste_mobile(c[2])
        if genre == "debut":
            return _mobile(c[1]["debut"])
        if genre == "fin":
            return _mobile(c[1]["fin"]) if c[1]["fin"] else _mobile(c[1]["duree"])
        if genre == "corps":
            p = c[1]
            return _mobile(p["debut"]) and (p["fin"] is None or _mobile(p["fin"]))
        return False

    def _reglages_de(self, c):
        genre = c[0]
        if genre in ("marque", "lmarque", "iv_debut", "iv_fin", "iv_corps"):
            return [c[2]]
        if genre == "debut":
            return [c[1]["debut"]]
        if genre == "fin":
            return [c[1]["fin"] or c[1]["duree"]]
        if genre in ("corps", "piste"):
            p = c[1]
            return [r for r in (p["debut"], p["fin"], p["duree"], *p["marques"], *p["intervalles"], *p["listes"]) if r]
        return []

    @staticmethod
    def _valeur_courbe(courbe, t):
        pts = courbe["points"]
        k = min(len(pts) - 1, max(0, round(t / pts[-1][0] * (len(pts) - 1)))) if pts[-1][0] else 0
        return pts[k][1]

    def _info(self, c):
        if c[0] == "media":
            m, t = c[1], c[2]
            lignes = [f"{m['nom']} ({m['genre']}, entrée #{m['index']})", f"{m['debut']:.2f} → {m['fin']:.2f} s"]
            for k in self._courbes_medias.get(m["index"], []):
                v = self._valeur_courbe(k, t)
                part = (v - k["mini"]) / (k["maxi"] - k["mini"])
                lignes.append(f"intensité à {t:.1f} s : {part * 100:.0f} %   ({k['nom']} {k['ligne']} = {v:.3f})")
            return "\n".join(lignes)
        if c[0] == "courbe":
            k, t = c[1], c[2]
            return f"{k['nom']} {k['ligne']}\nà {t:.1f} s : {self._valeur_courbe(k, t):.3f}   " \
                   f"(de {k['mini']:.3f} à {k['maxi']:.3f})"
        if c[0] == "transition":
            return "\n".join(tr["texte"] for tr in c[1]) or None
        if c[0] == "son":
            nom, decalage, pas, niveaux = c[1]
            return f"Son : {nom}\n{decalage:.2f} → {decalage + len(niveaux) * pas:.2f} s (forme d'onde, lecture seule)"
        if c[0] == "analyse":
            return "\n".join(f"{iv.texte} : {iv.debut:.2f} → {iv.fin:.2f} s" if iv.fin > iv.debut
                             else f"{iv.texte} : {iv.debut:.2f} s" for iv in c[2][:12]) or None
        lignes = []
        for r in self._reglages_de(c):
            v = self._valeurs.get(r.nom)
            if c[0] in ("lmarque", "iv_debut", "iv_fin", "iv_corps") and isinstance(v, (list, tuple)) and c[3] < len(v):
                texte = f"{r.nom}[{c[3]}] = {_fmt(v[c[3]])}"
            else:
                texte = f"{r.nom} = {_fmt(v) if r.nom in self._valeurs else '?'}"
            if r.hors_bloc:
                texte += "   (valeur à la fin du script)"
            elif not r.modifiable:
                texte += f"   (calculé : {r.source})"
            if r.commentaire:
                texte += f"\n    {r.commentaire}"
            lignes.append(texte)
        return "\n".join(lignes) or None

    # ───── souris
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        c = self._cible(e.position())
        if c and c[0] in ("marque", "lmarque", "iv_debut", "iv_fin", "iv_corps", "debut", "fin", "corps"):
            regs = self._reglages_de(c)
            index = c[3] if c[0] in ("lmarque", "iv_debut", "iv_fin", "iv_corps") else -1
            if c[0] == "corps":
                regs = [c[1]["debut"] or c[1]["fin"] or c[1]["duree"]]
            if regs and regs[0]:
                self.choisi.emit(regs[0].nom, index)
        if c and self._mobilite(c):
            self._prise = {"cible": c, "x0": e.position().x(), "total": self._total(),
                           "depart": dict(self._valeurs), "rempl": {},
                           "bords": self._bords_mobiles(c), "points": self._points_aimants(c), "aimant": None}
            self.setCursor(Qt.ClosedHandCursor if c[0] in ("corps", "iv_corps") else Qt.SizeHorCursor)
        else:
            self._prise = {"tete": True}
            self._chercher(e.position().x())

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self._prise:
            if self._prise.get("tete"):
                self._chercher(x)
            else:
                self._glisser(x, e)
            return
        c = self._cible(e.position())
        if c and self._mobilite(c):
            self.setCursor(Qt.OpenHandCursor if c[0] in ("corps", "iv_corps") else Qt.SizeHorCursor)
        else:
            self.unsetCursor()
        info = self._info(c) if c and c[0] not in ("regle",) else None
        if info:
            QToolTip.showText(e.globalPosition().toPoint(), info, self)
        else:
            QToolTip.hideText()

    def mouseReleaseEvent(self, e):
        prise, self._prise = self._prise, None
        self.unsetCursor()
        if prise and prise.get("rempl"):
            changements = {n: v for n, v in prise["rempl"].items() if v != prise["depart"].get(n)}
            if changements:
                self.modifie.emit(changements)
        self.update()

    def _chercher(self, x):
        t = max(0.0, min(self._t(x), self.duree()))
        self.set_tete(t)
        self.deplacement.emit(t)

    def _bords_mobiles(self, c):
        """Les temps (au départ) des bords qui bougent avec la cible."""
        genre = c[0]
        if genre == "marque":
            return [self._val(c[2])]
        if genre == "lmarque":
            return [self._liste(c[2])[c[3]]]
        if genre.startswith("iv_"):
            a, b = self._paires(c[2])[c[3]]
            return {"iv_debut": [a], "iv_fin": [b], "iv_corps": [a, b]}[genre]
        d, f = self._bornes(c[1])
        return [x for x in {"debut": [d], "fin": [f], "corps": [d, f]}[genre] if x is not None]

    def _points_aimants(self, c):
        """[(temps, nom)] : la tête de lecture, les bords des blocs et les repères, sauf ce qui est glissé."""
        points = [(self._tete, "tête de lecture")]
        for p in self._pistes:
            nom = p["nom"].replace("_", " ")
            if not (c[0] in ("debut", "fin", "corps") and c[1] is p):
                points += [(x, nom) for x in self._bornes(p) if x is not None]
            points += [(v, nom) for m in p["marques"] if m is not (c[2] if c[0] == "marque" else None)
                       and (v := self._val(m)) is not None]
            for r in p["intervalles"]:
                for k, (a, b) in enumerate(self._paires(r)):
                    if not (c[0].startswith("iv_") and c[2] is r and c[3] == k):
                        points += [(a, f"{nom} {k + 1}"), (b, f"{nom} {k + 1}")]
            for r in p["listes"]:
                points += [(v, nom) for k, v in enumerate(self._liste(r))
                           if not (c[0] == "lmarque" and c[2] is r and c[3] == k)]
        return points

    def _glisser(self, x, e):
        prise, c = self._prise, self._prise["cible"]
        depart = prise["depart"]
        dt = (x - prise["x0"]) / self._echelle()
        pas = 0.01 if e.modifiers() & Qt.AltModifier else 0.1

        # aimant : le bord glissé le plus proche d'un point (à moins de AIMANT pixels) s'y colle exactement
        aimant = None
        if not e.modifiers() & Qt.ShiftModifier:
            seuil, meilleur = AIMANT / self._echelle(), None
            for bord in prise["bords"]:
                for t, nom in prise["points"]:
                    ecart = abs(bord + dt - t)
                    if ecart <= seuil and (meilleur is None or ecart < meilleur[0]):
                        meilleur = (ecart, t - bord, t, nom)
            if meilleur:
                dt, aimant = meilleur[1], meilleur[2:]
        prise["aimant"] = aimant

        def cale(v):
            return round(v, 3) if aimant else round(round(v / pas) * pas, 2)

        rempl, genre = {}, c[0]
        if genre == "marque":
            rempl[c[2].nom] = max(0.0, cale(depart[c[2].nom] + dt))
        elif genre in ("lmarque", "iv_debut", "iv_fin", "iv_corps"):
            r, k = c[2], c[3]
            liste = list(depart[r.nom])
            if genre == "lmarque":
                liste[k] = max(0.0, cale(liste[k] + dt))
            else:
                a, b = float(liste[k][0]), float(liste[k][1])
                if genre == "iv_debut":
                    a = min(b, max(0.0, cale(a + dt)))
                elif genre == "iv_fin":
                    b = max(a, cale(b + dt))
                else:
                    na = max(0.0, cale(a + dt))
                    a, b = na, round(b + na - a, 3)
                liste[k] = (a, b) if isinstance(liste[k], tuple) else [a, b]
            rempl[r.nom] = type(depart[r.nom])(liste)
        else:
            p = c[1]
            d0 = _nombre(depart.get(p["debut"].nom)) if p["debut"] else 0.0
            if genre in ("debut", "corps"):
                nd = max(0.0, cale(d0 + dt))
                if genre == "debut" and p["fin"] and _nombre(depart.get(p["fin"].nom)) is not None:
                    nd = min(nd, _nombre(depart[p["fin"].nom]))
                rempl[p["debut"].nom] = nd
                if genre == "debut" and p["duree"] and not p["fin"] and _mobile(p["duree"]):
                    rempl[p["duree"].nom] = max(0.0, round(depart[p["duree"].nom] - (nd - d0), 3))
                if genre == "corps" and p["fin"]:
                    rempl[p["fin"].nom] = round(depart[p["fin"].nom] + nd - d0, 3)
            else:
                r = p["fin"] or p["duree"]
                nv = max(0.0, cale(depart[r.nom] + dt))
                if p["fin"] and p["debut"]:
                    nv = max(nv, d0)
                rempl[r.nom] = nv
        for nom, v in rempl.items():        # un entier reste un entier
            if isinstance(depart.get(nom), int) and not isinstance(depart.get(nom), bool):
                rempl[nom] = int(round(v))
        prise["rempl"] = rempl
        self._valeurs = {**depart, **(self._recalcul(rempl) if self._recalcul else rempl)}
        self.update()
        info = self._info(c) or ""
        if aimant:
            info += f"\n⇥ collé à : {aimant[1]} ({aimant[0]:.3f} s)"
        QToolTip.showText(e.globalPosition().toPoint(), info, self)

    # ───── dessin
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        g = self._gauche_visible()
        p.fillRect(self.rect(), QColor("#1d1f24"))
        p.fillRect(QRectF(0, 0, W, REGLE), QColor("#2b2e36"))
        petite = self.font()
        petite.setPointSizeF(8)
        normale = self.font()
        normale.setPointSizeF(9)

        # l'extrait d'aperçu chargé
        if self._apercu:
            a, b = self._apercu
            p.fillRect(QRectF(self._x(a), 0, self._x(b) - self._x(a), REGLE), QColor(90, 160, 255, 50))

        # graduations
        ech, total = self._echelle(), self._duree_vue()
        pas = next((s for s in (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300) if s * ech >= 60), 600)
        p.setFont(petite)
        for k in range(int(total / (pas / 5)) + 1):
            t = round(k * pas / 5, 3)
            x = self._x(t)
            if k % 5 == 0:
                p.setPen(QColor("#8a8f9c"))
                p.drawLine(QPointF(x, REGLE - 9), QPointF(x, REGLE))
                etiquette = f"{int(t // 60)}:{t % 60:04.1f}" if pas < 1 else f"{int(t // 60)}:{int(round(t % 60)):02d}"
                p.drawText(QPointF(x + 3, REGLE - 11), etiquette)
                p.setPen(QColor(255, 255, 255, 14))
                p.drawLine(QPointF(x, REGLE), QPointF(x, H))
            else:
                p.setPen(QColor("#5d6270"))
                p.drawLine(QPointF(x, REGLE - 4), QPointF(x, REGLE))

        # l'aperçu en cours de calcul : la bande se remplit, avec le pourcentage
        if self._calcul:
            a, b, fraction, libelle = self._calcul
            xa, xb = self._x(a), self._x(b)
            p.fillRect(QRectF(xa, 2, xb - xa, REGLE - 4), QColor(108, 176, 245, 55))
            p.fillRect(QRectF(xa, 2, (xb - xa) * fraction, REGLE - 4), QColor("#6cb0f5"))
            texte = f"{libelle} {fraction * 100:.0f} %"
            p.setFont(petite)
            largeur = QFontMetrics(petite).horizontalAdvance(texte) + 10
            zone = QRectF(xa, 0, xb - xa, REGLE) if xb - xa >= largeur else QRectF(xb + 4, 0, largeur, REGLE)
            p.setPen(QColor("#0d1b2a") if xb - xa >= largeur and fraction > 0.5 else QColor("#ffffff"))
            p.drawText(zone, Qt.AlignCenter, texte)

        # pistes
        fm = QFontMetrics(petite)
        for i, piste in enumerate(self._pistes):
            y = self._y_piste(i)
            coul = QColor(COULEURS[i % len(COULEURS)])
            if i % 2:
                p.fillRect(QRectF(0, y, W, H_PISTE), QColor(255, 255, 255, 7))
            d, f = self._bornes(piste)
            if d is not None:
                fin = f if f is not None else total
                r = QRectF(self._x(d), y + 5, max(2.0, self._x(fin) - self._x(d)), H_PISTE - 10)
                vif = any(x and x.nom in self._surbrillance for x in (piste["debut"], piste["fin"], piste["duree"]))
                temps = f"{d:.2f} → {f:.2f} s" if f is not None else f"dès {d:.2f} s"
                self._bloc(p, r, coul, f is None, _mobile(piste["debut"]),
                           f is not None and _mobile(piste["fin"] or piste["duree"]),
                           self._textes_pistes.get(piste["nom"], temps), fm, vif)
            for rv in piste["intervalles"]:
                for k, (a, b) in enumerate(self._paires(rv)):
                    r = QRectF(self._x(a), y + 5, max(2.0, self._x(b) - self._x(a)), H_PISTE - 10)
                    self._bloc(p, r, coul, False, _liste_mobile(rv), _liste_mobile(rv), f"{k + 1}", fm,
                               rv.nom in self._surbrillance)
            for m in piste["marques"]:
                if (v := self._val(m)) is not None:
                    self._marque(p, self._x(v), y, coul, _mobile(m))
            for rl in piste["listes"]:
                for v in self._liste(rl):
                    self._marque(p, self._x(v), y, coul, _liste_mobile(rl))

        # sons : la forme d'onde, symétrique, seulement sur la partie visible
        visible = self.visibleRegion().boundingRect()
        for j, (nom, decalage, pas, niveaux) in enumerate(self._sons):
            y = self._y_son(j)
            milieu, demi = y + H_SON / 2, H_SON / 2 - 4
            p.fillRect(QRectF(0, y, W, H_SON), QColor(63, 193, 192, 12))
            p.setPen(QPen(QColor(COULEUR_SON), 1))
            x0 = max(int(self._x(decalage)), visible.left(), ENTETE)
            x1 = min(int(self._x(decalage + len(niveaux) * pas)), visible.right())
            for x in range(x0, x1 + 1):
                a = int((self._t(x) - decalage) / pas)
                b = max(a + 1, int((self._t(x + 1) - decalage) / pas))
                if 0 <= a < len(niveaux):
                    h = max(0.5, max(niveaux[a:b]) * demi)
                    p.drawLine(QPointF(x + 0.5, milieu - h), QPointF(x + 0.5, milieu + h))

        # images d'entrée : une barre, la vignette au début, la courbe d'intensité par-dessus
        for j, m in enumerate(self._medias):
            y = self._y_media(j)
            p.fillRect(QRectF(0, y, W, H_MEDIA), QColor(255, 255, 255, 6 if j % 2 else 0))
            r = QRectF(self._x(m["debut"]), y + 4, max(2.0, self._x(m["fin"]) - self._x(m["debut"])), H_MEDIA - 8)
            p.setPen(QPen(QColor("#5d6270"), 1))
            p.setBrush(QColor(90, 96, 112, 120))
            p.drawRoundedRect(r, 3, 3)
            vignette = self._vignettes.get(m["vignette"]) if m["vignette"] else None
            if vignette is not None:
                p.save()
                p.setClipRect(r)
                p.drawPixmap(QPointF(r.left() + 1, r.top() + 1), vignette)
                p.restore()
            for k in self._courbes_medias.get(m["index"], []):
                self._courbe(p, k, r)

        # courbes sans image (volume…)
        for j, k in enumerate(self._courbes_libres):
            y = self._y_courbe(j)
            self._courbe(p, k, QRectF(self._x(0), y + 3, self._x(k["points"][-1][0]) - self._x(0), H_COURBE - 6))

        # fondus : des rampes (ouverture qui monte, fermeture qui descend, fondu enchaîné en croix)
        if self._transitions:
            y0 = self._y_transitions()
            haut, bas = y0 + 4, y0 + H_TRANSITION - 4
            for tr in self._transitions:
                xa, xb = self._x(tr["debut"]), self._x(tr["fin"])
                couleur = QColor(COULEUR_SON if tr["son"] else "#c8ccd4")
                couleur.setAlpha(150)
                p.setPen(QPen(couleur.lighter(120), 1))
                p.setBrush(couleur)
                if tr["genre"] == "entree":
                    p.drawPolygon(QPolygonF([QPointF(xa, bas), QPointF(xb, haut), QPointF(xb, bas)]))
                elif tr["genre"] == "sortie":
                    p.drawPolygon(QPolygonF([QPointF(xa, haut), QPointF(xb, bas), QPointF(xa, bas)]))
                else:
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(couleur.lighter(130), 2))
                    p.drawLine(QPointF(xa, haut), QPointF(xb, bas))
                    p.drawLine(QPointF(xa, bas), QPointF(xb, haut))

        # analyse de la commande ffmpeg
        if self._analyse:
            ya = self._y_analyse()
            p.setPen(QColor(255, 255, 255, 30))
            p.drawLine(QPointF(0, ya - ESPACE / 2), QPointF(W, ya - ESPACE / 2))
            for j, (ligne, ivs) in enumerate(self._analyse):
                y = ya + j * H_ANALYSE
                for iv in ivs:
                    x0 = self._x(iv.debut)
                    if iv.fin > iv.debut:
                        p.setPen(Qt.NoPen)
                        p.setBrush(QColor(140, 148, 165, 110))
                        p.drawRoundedRect(QRectF(x0, y + 3, max(1.5, self._x(iv.fin) - x0), H_ANALYSE - 6), 2, 2)
                    else:
                        p.setPen(QPen(QColor(170, 176, 190, 170), 1))
                        p.drawLine(QPointF(x0, y + 2), QPointF(x0, y + H_ANALYSE - 2))

        # fin de la commande (-t)
        if self._duree_cmd:
            x = self._x(self._duree_cmd)
            p.setPen(QPen(QColor("#9aa0ad"), 1, Qt.DashLine))
            p.drawLine(QPointF(x, REGLE), QPointF(x, H))

        # en-têtes (fixes quand on fait défiler)
        p.fillRect(QRectF(g, 0, ENTETE, H), QColor("#25272e"))
        p.fillRect(QRectF(g, 0, ENTETE, REGLE), QColor("#2b2e36"))
        p.setFont(normale)
        fmn = QFontMetrics(normale)
        for i, piste in enumerate(self._pistes):
            y = self._y_piste(i)
            coul = QColor(COULEURS[i % len(COULEURS)])
            p.setPen(Qt.NoPen)
            p.setBrush(coul)
            p.drawRoundedRect(QRectF(g + 10, y + H_PISTE / 2 - 5, 10, 10), 2, 2)
            p.setPen(QColor("#d7dae0"))
            p.drawText(QRectF(g + 26, y, ENTETE - 30, H_PISTE), Qt.AlignVCenter | Qt.AlignLeft,
                       fmn.elidedText(piste["nom"].replace("_", " "), Qt.ElideRight, ENTETE - 32))
        for j, (nom, *_) in enumerate(self._sons):
            y = self._y_son(j)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(COULEUR_SON))
            p.drawRoundedRect(QRectF(g + 10, y + H_SON / 2 - 5, 10, 10), 5, 5)
            p.setPen(QColor("#d7dae0"))
            p.setFont(normale)
            p.drawText(QRectF(g + 26, y, ENTETE - 30, H_SON / 2), Qt.AlignBottom | Qt.AlignLeft, "Son")
            p.setFont(petite)
            p.setPen(QColor("#8a8f9c"))
            p.drawText(QRectF(g + 26, y + H_SON / 2, ENTETE - 30, H_SON / 2), Qt.AlignTop | Qt.AlignLeft,
                       fm.elidedText(nom, Qt.ElideMiddle, ENTETE - 32))
        def entete(y, hauteur, titre, sous_titre, couleur, rond=False):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(couleur))
            p.drawRoundedRect(QRectF(g + 10, y + hauteur / 2 - 5, 10, 10), 5 if rond else 2, 5 if rond else 2)
            p.setFont(normale)
            p.setPen(QColor("#d7dae0"))
            if sous_titre:
                p.drawText(QRectF(g + 26, y, ENTETE - 30, hauteur / 2), Qt.AlignBottom | Qt.AlignLeft,
                           fmn.elidedText(titre, Qt.ElideRight, ENTETE - 32))
                p.setFont(petite)
                p.setPen(QColor("#8a8f9c"))
                p.drawText(QRectF(g + 26, y + hauteur / 2, ENTETE - 30, hauteur / 2), Qt.AlignTop | Qt.AlignLeft,
                           fm.elidedText(sous_titre, Qt.ElideMiddle, ENTETE - 32))
            else:
                p.drawText(QRectF(g + 26, y, ENTETE - 30, hauteur), Qt.AlignVCenter | Qt.AlignLeft,
                           fmn.elidedText(titre, Qt.ElideRight, ENTETE - 32))

        for j, m in enumerate(self._medias):
            titre = "Fond" if m["genre"] == "image" else "Images" if m["genre"].startswith("séquence") else \
                "Vidéo" if m["genre"] == "vidéo" else "Calculé"
            entete(self._y_media(j), H_MEDIA, titre, m["nom"], "#8a8f9c")
        for j, k in enumerate(self._courbes_libres):
            entete(self._y_courbe(j), H_COURBE, k["nom"], k["ligne"], COULEUR_COURBE, True)
        if self._transitions:
            entete(self._y_transitions(), H_TRANSITION, "Transitions", "", "#c8ccd4")
        if self._analyse:
            ya = self._y_analyse()
            p.setFont(petite)
            p.setPen(QColor("#6b7080"))
            p.drawText(QRectF(g + 10, ya - ESPACE, ENTETE - 14, ESPACE), Qt.AlignVCenter,
                       fm.elidedText("Commande ffmpeg", Qt.ElideRight, ENTETE - 14))
            for j, (ligne, _) in enumerate(self._analyse):
                p.drawText(QRectF(g + 10, ya + j * H_ANALYSE, ENTETE - 14, H_ANALYSE), Qt.AlignVCenter | Qt.AlignLeft,
                           fm.elidedText(ligne, Qt.ElideRight, ENTETE - 14))
        if not self._pistes and not self._analyse:
            p.setPen(QColor("#6b7080"))
            p.drawText(QRectF(ENTETE, REGLE, W - ENTETE, H - REGLE), Qt.AlignCenter,
                       "Aucune piste : ajoutez des étiquettes @Piste.debut / .fin aux réglages du script.")

        # le point où l'aimant colle le bord glissé
        if self._prise and self._prise.get("aimant"):
            x = self._x(self._prise["aimant"][0])
            p.setPen(QPen(QColor("#ffd75e"), 1.5, Qt.DashLine))
            p.drawLine(QPointF(x, REGLE), QPointF(x, H))

        # tête de lecture
        x = self._x(self._tete)
        p.setPen(QPen(QColor("#ff5c5c"), 1.5))
        p.drawLine(QPointF(x, 0), QPointF(x, H))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ff5c5c"))
        p.drawPolygon(QPolygonF([QPointF(x - 6, 0), QPointF(x + 6, 0), QPointF(x, 9)]))
        p.end()

    def _bloc(self, p, r, coul, ouvert, bord_gauche, bord_droit, texte, fm, vif=False):
        fond = QColor(coul)
        fond.setAlpha(70 if ouvert else 150)
        p.setBrush(fond)
        p.setPen(QPen(QColor("#ffffff"), 2) if vif else QPen(coul.lighter(130), 1))
        p.drawRoundedRect(r, 4, 4)
        poignee = QColor(255, 255, 255, 200)
        if bord_gauche:
            p.fillRect(QRectF(r.left() + 1, r.top() + 4, 3, r.height() - 8), poignee)
        if bord_droit and not ouvert:
            p.fillRect(QRectF(r.right() - 4, r.top() + 4, 3, r.height() - 8), poignee)
        court = fm.elidedText(texte, Qt.ElideRight, int(r.width()) - 14)     # raccourci avec « … » s'il ne tient pas
        if court and court != "…":
            p.setPen(QColor("#ffffff"))
            p.drawText(r.adjusted(7, 0, -7, 0), Qt.AlignVCenter | Qt.AlignLeft, court)

    def _courbe(self, p, courbe, r):
        """Une courbe ramenée à la hauteur de r (de son minimum à son maximum), aire remplie, sur la partie visible."""
        visible = self.visibleRegion().boundingRect()
        etendue = (courbe["maxi"] - courbe["mini"]) or 1.0
        points = [QPointF(self._x(t), r.bottom() - (v - courbe["mini"]) / etendue * r.height())
                  for t, v in courbe["points"] if visible.left() - 20 <= self._x(t) <= visible.right() + 20]
        if len(points) < 2:
            return
        fond = QColor(COULEUR_COURBE)
        fond.setAlpha(45)
        p.setPen(Qt.NoPen)
        p.setBrush(fond)
        p.drawPolygon(QPolygonF([QPointF(points[0].x(), r.bottom()), *points, QPointF(points[-1].x(), r.bottom())]))
        p.setPen(QPen(QColor(COULEUR_COURBE), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(points))

    def _marque(self, p, x, y, coul, mobile):
        p.setPen(QPen(coul.lighter(150), 1.5))
        p.drawLine(QPointF(x, y + 4), QPointF(x, y + H_PISTE - 3))
        p.setPen(QPen(coul.lighter(150), 1))
        p.setBrush(QColor("#ffffff") if mobile else coul)
        p.drawPolygon(QPolygonF([QPointF(x, y + 2), QPointF(x + 5, y + 7), QPointF(x, y + 12), QPointF(x - 5, y + 7)]))
