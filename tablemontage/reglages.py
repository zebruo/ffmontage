"""Lecture et réécriture du bloc « # ── RÉGLAGES » d'un script de montage.

Convention (voir README.md) :

    # ── RÉGLAGES ──────────────
    TITRE = "Un chemin tranquille"   # le texte du titre
    VOLUME = 0.5                     # volume de la musique [0..2]
    T_TITRE = 3.8                    # fin du titre @Titre.fin
    DEBUT = T_TITRE - 0.8            # valeur calculée : affichée, non modifiable @Animation.debut
    # ── FIN RÉGLAGES ──────────

Dans le commentaire d'une ligne :
    [min..max]                         bornes du champ (curseur si les deux sont données)
    @Piste.debut / .fin / .duree       place la valeur sur la timeline (secondes depuis le début du film)
    @Piste.marque                      un repère sur la piste
    @Piste.intervalles                 une liste de paires (début, fin) : un bloc par paire
    @Piste.marques                     une liste de temps : un repère par valeur
    @Piste.texte / .police / .taille / .couleur / .position
                                       l'apparence d'un texte du film (couleur "#RRGGBB", position (x, y) en pixels
                                       de l'image) : choix de couleur, de police, et poignée à déplacer sur l'aperçu
    @fichier / @dossier                bouton de choix de fichier ou de dossier
    @couleur / @police / @position     les mêmes outils, pour une valeur qui n'appartient pas à une piste
    @apercu=valeur                     valeur utilisée pour les aperçus (ex. IPS = 30  # @apercu=10 : plus rapide)
    @nom=Nom_affiché                   le nom du réglage dans le panneau (les _ deviennent des espaces) ; pour
                                       « W, H = … » : @nom=Largeur,Hauteur
Une ligne « # ── Titre » à l'intérieur du bloc ouvre une section dans le panneau.
Seules les valeurs littérales (nombre, texte, booléen, liste…) sont modifiables ; le reste est calculé à partir
des réglages précédents (opérations, round/min/max…) et seulement affiché.
Les étiquettes @Piste.role marchent aussi sur les lignes hors du bloc (en MAJUSCULES, au premier niveau du script) :
leur valeur, inconnue avant l'exécution, est celle qu'avait la variable à la fin du script ; elle n'est pas modifiable.
"""
import ast
import io
import operator
import re
import tokenize
from dataclasses import dataclass, field

DEBUT_BLOC = re.compile(r"^\s*#\s*[─━—=-]+\s*R[ÉE]GLAGES\b", re.I)
FIN_BLOC = re.compile(r"^\s*#\s*[─━—=-]+\s*FIN\b", re.I)
SECTION = re.compile(r"^\s*#\s*[─━—=-]{2,}\s*(.*?)\s*[─━—=-]*\s*$")
BORNES = re.compile(r"\[\s*(-?\d+(?:\.\d*)?)\s*\.\.\s*(-?\d+(?:\.\d*)?)\s*\]")
ETIQUETTE = re.compile(r"@(\w+)(?:\.(\w+))?")
APERCU = re.compile(r"@aper[çc]u=(\S+)", re.I)
NOM_AFFICHE = re.compile(r"@nom=(\S+)", re.I)
ROLES = {"debut": "debut", "début": "debut", "fin": "fin", "duree": "duree", "durée": "duree", "marque": "marque",
         "intervalles": "intervalles", "marques": "marques",
         "texte": "texte", "police": "police", "taille": "taille", "couleur": "couleur", "position": "position"}
ROLES_TEMPS = {"debut", "fin", "duree", "marque", "intervalles", "marques"}      # ceux de la timeline
CHOIX = {"fichier", "dossier", "couleur", "police", "position"}                    # un outil dans le panneau
MAJUSCULES = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass
class Reglage:
    nom: str
    ligne: int
    source: str                     # le texte de la valeur dans le script
    noeud: ast.expr | None
    modifiable: bool                # valeur littérale : on peut la réécrire
    position: tuple = ()            # (ligne, colonne, ligne de fin, colonne de fin), en caractères
    valeur: object = None
    connu: bool = False             # valeur calculable sans lancer le script
    commentaire: str = ""
    mini: float | None = None
    maxi: float | None = None
    etiquettes: list = field(default_factory=list)   # [(piste, role)]
    choix: str | None = None        # "fichier", "dossier", "couleur", "police" ou "position"
    hors_bloc: bool = False         # ligne étiquetée hors du bloc : valeur connue seulement après exécution
    apercu: str | None = None       # texte de la valeur à utiliser pour les aperçus
    libelle: str | None = None      # nom affiché dans le panneau (@nom=…), sinon le nom de la variable
    elements: list = field(default_factory=list)     # positions des éléments d'une liste ou d'un tuple


@dataclass
class Section:
    titre: str
    ligne: int


@dataclass
class Bloc:
    elements: list = field(default_factory=list)     # Reglage et Section, dans l'ordre du fichier
    trouve: bool = False
    erreur: str | None = None

    @property
    def reglages(self):
        """Les réglages du bloc (ceux du panneau)."""
        return [e for e in self.elements if isinstance(e, Reglage) and not e.hors_bloc]

    @property
    def tous(self):
        """Les réglages du bloc puis les lignes étiquetées hors du bloc (ceux de la timeline)."""
        return [e for e in self.elements if isinstance(e, Reglage)]

    def appliquer_execution(self, valeurs):
        """Complète les valeurs inconnues avec celles qu'avaient les variables à la fin du script."""
        for r in self.tous:
            if not r.connu and r.nom in valeurs:
                r.valeur, r.connu = valeurs[r.nom], True


# ───── évaluation des valeurs calculées (sans exécuter le script)
class _Inconnu(Exception):
    pass


_OPERATEURS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
               ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_FONCTIONS = {"round": round, "min": min, "max": max, "abs": abs, "int": int, "float": float, "str": str, "len": len}


def _evaluer(n, env):
    if isinstance(n, ast.Constant):
        return n.value
    if isinstance(n, ast.Name):
        if n.id in env:
            return env[n.id]
        raise _Inconnu(n.id)
    if isinstance(n, ast.BinOp) and type(n.op) in _OPERATEURS:
        return _OPERATEURS[type(n.op)](_evaluer(n.left, env), _evaluer(n.right, env))
    if isinstance(n, ast.UnaryOp):
        v = _evaluer(n.operand, env)
        if isinstance(n.op, ast.USub):
            return -v
        if isinstance(n.op, ast.UAdd):
            return +v
        if isinstance(n.op, ast.Not):
            return not v
    if isinstance(n, (ast.Tuple, ast.List)):
        elements = [_evaluer(e, env) for e in n.elts]
        return tuple(elements) if isinstance(n, ast.Tuple) else elements
    if isinstance(n, ast.Dict) and None not in n.keys:
        return {_evaluer(k, env): _evaluer(v, env) for k, v in zip(n.keys, n.values)}
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FONCTIONS and not n.keywords:
        return _FONCTIONS[n.func.id](*[_evaluer(a, env) for a in n.args])
    if isinstance(n, ast.JoinedStr):
        morceaux = []
        for v in n.values:
            if isinstance(v, ast.Constant):
                morceaux.append(str(v.value))
            else:
                x = _evaluer(v.value, env)
                x = {115: str, 114: repr, 97: ascii}.get(v.conversion, lambda y: y)(x)
                morceaux.append(format(x, _evaluer(v.format_spec, env) if v.format_spec else ""))
        return "".join(morceaux)
    raise _Inconnu(type(n).__name__)


def _litteral(n):
    if n is None:
        return False
    if isinstance(n, ast.Constant):
        return isinstance(n.value, (bool, int, float, str))
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)) and isinstance(n.operand, ast.Constant):
        return isinstance(n.operand.value, (int, float)) and not isinstance(n.operand.value, bool)
    if isinstance(n, (ast.Tuple, ast.List, ast.Dict, ast.Set)):
        try:
            ast.literal_eval(n)
            return True
        except ValueError:
            return False
    return False


# ───── lecture
def lire(texte):
    """Analyse le texte d'un script et renvoie son bloc de réglages."""
    lignes = texte.split("\n")
    try:
        arbre = ast.parse(texte)
    except SyntaxError as e:
        return Bloc(erreur=f"Erreur de syntaxe ligne {e.lineno} : {e.msg}")
    debut = next((i + 1 for i, l in enumerate(lignes) if DEBUT_BLOC.match(l)), None)
    if debut is None:
        debut = fin = 0
    else:
        fin = next((i + 1 for i in range(debut, len(lignes)) if FIN_BLOC.match(lignes[i])), None)
    if fin is None:      # sans « FIN RÉGLAGES » : le bloc s'arrête à la première instruction qui n'est pas une affectation
        fin = next((n.lineno for n in arbre.body if n.lineno > debut and not isinstance(n, (ast.Assign, ast.AnnAssign))),
                   len(lignes) + 1)

    commentaires = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(texte).readline):
            if tok.type == tokenize.COMMENT:
                commentaires.setdefault(tok.start[0], tok.string[1:].strip())
    except (tokenize.TokenError, SyntaxError):
        pass

    def colonne(ligne, octets):      # ast donne des positions en octets UTF-8
        return len(lignes[ligne - 1].encode("utf-8")[:octets].decode("utf-8", "replace"))

    def commentaire_de(n):           # les lignes de commentaire juste au-dessus, puis ceux de l'affectation elle-même
        dessus, k = [], n.lineno - 1
        while k in commentaires and lignes[k - 1].lstrip().startswith("#") and not SECTION.match(lignes[k - 1]) \
                and not DEBUT_BLOC.match(lignes[k - 1]):
            dessus.insert(0, commentaires[k])
            k -= 1
        return " ".join(dessus + [commentaires[k] for k in range(n.lineno, n.end_lineno + 1) if k in commentaires])

    elements, occupees = [], set()
    for n in arbre.body:
        if not isinstance(n, (ast.Assign, ast.AnnAssign)):
            continue
        hors_bloc = not debut < n.lineno < fin
        com = commentaire_de(n)
        if hors_bloc and not ETIQUETTE.search(com):
            continue
        occupees.update(range(n.lineno, n.end_lineno + 1))
        cible = n.targets[0] if isinstance(n, ast.Assign) and len(n.targets) == 1 else getattr(n, "target", None)
        if isinstance(cible, ast.Name):
            paires = [(cible.id, n.value)]
        elif isinstance(cible, ast.Tuple) and all(isinstance(e, ast.Name) for e in cible.elts):
            if isinstance(n.value, ast.Tuple) and len(n.value.elts) == len(cible.elts):
                paires = [(e.id, v) for e, v in zip(cible.elts, n.value.elts)]
            else:
                paires = [(e.id, None) for e in cible.elts]
        else:
            continue
        mini = maxi = choix = apercu = None
        etiquettes = []
        if m := APERCU.search(com):
            apercu = m.group(1)
            com = APERCU.sub("", com)
        libelles = []
        if m := NOM_AFFICHE.search(com):
            libelles = [x.replace("_", " ").strip() for x in m.group(1).split(",")]
            com = NOM_AFFICHE.sub("", com)
        if m := BORNES.search(com):
            mini, maxi = float(m.group(1)), float(m.group(2))
        for m in ETIQUETTE.finditer(com):
            if m.group(1).lower() in CHOIX and not m.group(2):
                choix = m.group(1).lower()
            elif m.group(2) and m.group(2).lower() in ROLES:
                role = ROLES[m.group(2).lower()]
                etiquettes.append((m.group(1), role))
                if role in CHOIX:
                    choix = role
        propre = re.sub(r"\s{2,}", " ", ETIQUETTE.sub("", BORNES.sub("", com))).strip(" ·")
        for k, (nom, valeur) in enumerate(paires):
            libelle = (libelles[k] if k < len(libelles) else None) if len(libelles) > 1 else \
                (libelles[0] if libelles else None)
            if hors_bloc and not (MAJUSCULES.match(nom) and etiquettes):
                continue
            if valeur is None:
                source, position = ast.get_source_segment(texte, n.value) or "", ()
            else:
                source = ast.get_source_segment(texte, valeur) or ""
                position = (valeur.lineno, colonne(valeur.lineno, valeur.col_offset),
                            valeur.end_lineno, colonne(valeur.end_lineno, valeur.end_col_offset))
            elements_pos = [(e.lineno, colonne(e.lineno, e.col_offset), e.end_lineno, colonne(e.end_lineno, e.end_col_offset))
                            for e in getattr(valeur, "elts", [])] if isinstance(valeur, (ast.List, ast.Tuple)) else []
            elements.append(Reglage(nom, n.lineno, source, valeur, _litteral(valeur) and not hors_bloc, position,
                                    commentaire=propre, mini=mini, maxi=maxi, etiquettes=list(etiquettes), choix=choix,
                                    hors_bloc=hors_bloc, apercu=apercu, libelle=libelle or None,
                                    elements=elements_pos))
    for i in range(debut + 1, fin):
        if i not in occupees and (m := SECTION.match(lignes[i - 1])) and m.group(1):
            elements.append(Section(m.group(1), i))
    elements.sort(key=lambda e: e.ligne)

    bloc = Bloc(elements, debut > 0)
    par_nom = {r.nom: r for r in bloc.reglages}
    for nom, v in recalculer(bloc).items():
        par_nom[nom].valeur, par_nom[nom].connu = v, True
    return bloc


def recalculer(bloc, remplacements=None):
    """Valeurs de tous les réglages calculables, en remplaçant certaines valeurs (pendant un glissement sur la timeline)."""
    remplacements = remplacements or {}
    env = {}
    for r in bloc.reglages:
        if r.nom in remplacements:
            env[r.nom] = remplacements[r.nom]
            continue
        try:
            env[r.nom] = _evaluer(r.noeud, env) if r.noeud is not None else _inconnu()
        except (_Inconnu, ArithmeticError, TypeError, ValueError, KeyError, IndexError):
            env.pop(r.nom, None)
    return env


def _inconnu():
    raise _Inconnu()


# ───── écriture
def formater(valeur, ancienne_source=""):
    """Texte Python d'une nouvelle valeur, dans le style de l'ancienne (guillemets, chaîne brute r"…")."""
    if isinstance(valeur, bool):
        return "True" if valeur else "False"
    if isinstance(valeur, int):
        return str(valeur)
    if isinstance(valeur, float):
        return repr(round(valeur, 6))
    if isinstance(valeur, str):
        m = re.match(r"^([rRuU]*)('|\")", ancienne_source or "")
        prefixe, guillemet = (m.group(1), m.group(2)) if m else ("", '"')
        if "r" in prefixe.lower() and guillemet not in valeur and "\n" not in valeur and not valeur.endswith("\\"):
            return f"{prefixe}{guillemet}{valeur}{guillemet}"
        if guillemet == '"':
            return '"' + valeur.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
        return repr(valeur)
    if isinstance(valeur, (list, tuple)) and "\n" in (ancienne_source or "") and valeur:   # une ligne par élément
        ouvre, ferme = ("[", "]") if isinstance(valeur, list) else ("(", ")")
        return ouvre + "\n" + "".join(f"    {formater(v)},\n" for v in valeur) + ferme
    if isinstance(valeur, (list, tuple)):
        elements = ", ".join(formater(v) for v in valeur)
        if isinstance(valeur, list):
            return f"[{elements}]"
        return f"({elements},)" if len(valeur) == 1 else f"({elements})"
    return repr(valeur)


def remplacer(texte, changements):
    """Remplace dans le texte les valeurs données ({nom: texte Python}) ; le reste du fichier ne bouge pas."""
    bloc = lire(texte)
    if bloc.erreur:
        raise ValueError(bloc.erreur)
    cibles = sorted(((r.position, changements[r.nom]) for r in bloc.reglages
                     if r.nom in changements and r.modifiable and r.position), reverse=True)
    lignes = texte.split("\n")
    for (l, c, lf, cf), source in cibles:
        lignes[l - 1] = lignes[l - 1][:c] + source + lignes[lf - 1][cf:]
        del lignes[l:lf]
    nouveau = "\n".join(lignes)
    try:
        ast.parse(nouveau)
    except SyntaxError as e:
        raise ValueError(f"valeur refusée (le script deviendrait invalide) : {e.msg}") from None
    return nouveau


def texte_apercu(texte):
    """Le texte du script avec les valeurs @apercu=… à la place des vraies (pour calculer un aperçu plus vite)."""
    bloc = lire(texte)
    changements = {r.nom: r.apercu for r in bloc.reglages if r.apercu is not None}
    return remplacer(texte, changements) if changements else texte
