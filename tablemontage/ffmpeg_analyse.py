"""Analyse d'une commande ffmpeg capturée : entrées, graphe de filtres, repères de temps, commande d'aperçu."""
import math
import os
import re
from dataclasses import dataclass, field

# options sans valeur (les autres en prennent une)
DRAPEAUX = {"-y", "-n", "-hide_banner", "-nostdin", "-stats", "-nostats", "-re", "-shortest", "-an", "-vn", "-sn",
            "-dn", "-copyts", "-start_at_zero", "-benchmark", "-xerror", "-ignore_unknown", "-autorotate",
            "-noautorotate", "-accurate_seek", "-noaccurate_seek", "-dump", "-hex", "-reinit_filter", "-debug_ts"}


@dataclass
class Entree:
    index: int
    source: str
    options: list


@dataclass
class Filtre:
    nom: str
    args: list            # [(clé ou None, valeur)]
    texte: str


@dataclass
class Chaine:
    entrees: list
    sorties: list
    filtres: list
    texte: str


@dataclass
class Intervalle:
    ligne: str            # la chaîne de filtres d'où vient le repère
    debut: float
    fin: float            # fin == debut : un repère ponctuel
    texte: str


@dataclass
class Commande:
    args: list
    cwd: str
    entrees: list = field(default_factory=list)
    graphe: str | None = None
    chaines: list = field(default_factory=list)
    options_sortie: list = field(default_factory=list)
    sortie: str | None = None
    duree: float | None = None

    def intervalles(self):
        return [iv for c in self.chaines for iv in _intervalles(c, self.cwd)]


# ───── découpage du graphe de filtres (guillemets ' et échappements \ respectés)
def _scinder(texte, sep):
    morceaux, courant, guillemet, i = [], [], False, 0
    while i < len(texte):
        c = texte[i]
        if c == "\\" and i + 1 < len(texte):
            courant.append(texte[i:i + 2])
            i += 2
            continue
        if c == "'":
            guillemet = not guillemet
        elif c == sep and not guillemet:
            morceaux.append("".join(courant))
            courant = []
            i += 1
            continue
        courant.append(c)
        i += 1
    morceaux.append("".join(courant))
    return morceaux


def _sans_guillemets(v):
    sortie, i = [], 0
    while i < len(v):
        if v[i] == "\\" and i + 1 < len(v):
            sortie.append(v[i + 1])
            i += 2
            continue
        if v[i] != "'":
            sortie.append(v[i])
        i += 1
    return "".join(sortie)


def _chaine(texte):
    entrees, sorties, filtres = [], [], []
    for k, ft in enumerate(_scinder(texte, ",")):
        ft = ft.strip()
        m = re.match(r"(?:\s*\[[^\]]*\])*", ft)
        entrees.extend(re.findall(r"\[([^\]]*)\]", m.group(0)))
        ft = ft[m.end():]
        m = re.search(r"(?:\[[^\]]*\]\s*)*$", ft)
        sorties.extend(re.findall(r"\[([^\]]*)\]", m.group(0)))
        ft = ft[:m.start()].strip()
        nom, _, reste = ft.partition("=")
        args = []
        if reste:
            for morceau in _scinder(reste, ":"):
                cle, egal, valeur = morceau.partition("=")
                if egal and re.fullmatch(r"\w+", cle):
                    args.append((cle, _sans_guillemets(valeur)))
                else:
                    args.append((None, _sans_guillemets(morceau)))
        filtres.append(Filtre(nom.strip(), args, ft))
    return Chaine(entrees, sorties, filtres, texte.strip())


def decouper_graphe(graphe):
    return [_chaine(t) for t in _scinder(graphe, ";") if t.strip()]


# ───── repères de temps trouvés dans les filtres
def _nombre(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _temps_ass(s):
    h, m, sec = s.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


def _dialogues_ass(chemin):
    sortie = []
    try:
        with open(chemin, encoding="utf-8-sig", errors="replace") as f:
            for l in f:
                if l.startswith("Dialogue:"):
                    parts = l.split(":", 1)[1].split(",", 9)
                    texte = re.sub(r"\{[^}]*\}", "", parts[9]).replace("\\N", " ").strip()
                    sortie.append((_temps_ass(parts[1]), _temps_ass(parts[2]), texte))
    except (OSError, IndexError, ValueError):
        pass
    return sortie


def _intervalles(chaine, cwd):
    ligne = " ".join(f"[{s}]" for s in chaine.sorties) or (chaine.filtres[0].nom if chaine.filtres else "?")
    sortie = []

    def ajouter(debut, fin, texte):
        if debut is not None and fin is not None:
            sortie.append(Intervalle(ligne, debut, max(debut, fin), texte))

    for f in chaine.filtres:
        a = {k: v for k, v in f.args if k}
        pos = [v for k, v in f.args if not k]
        if f.nom == "xfade":
            o, d = _nombre(a.get("offset", 0)), _nombre(a.get("duration", 1))
            ajouter(o, (o or 0) + (d or 0), f"xfade {a.get('transition', 'fade')}")
        elif f.nom in ("fade", "afade") and ("st" in a or "start_time" in a):
            sens = a.get("t", a.get("type", pos[0] if pos else "in"))
            st, d = _nombre(a.get("st", a.get("start_time"))), _nombre(a.get("d", a.get("duration", 1)))
            ajouter(st, (st or 0) + (d or 0), f"{f.nom} {sens}")
        elif f.nom == "adelay":
            premier = re.split(r"[|]", a.get("delays", pos[0] if pos else ""))[0].strip()
            if premier.endswith("s"):
                t = _nombre(premier[:-1])
            elif premier.endswith("S"):
                t = None
            else:
                t = _nombre(premier.rstrip("ms"))
                t = t / 1000 if t is not None else None
            ajouter(t, t, "adelay")
        elif f.nom in ("trim", "atrim"):
            debut = _nombre(a.get("start", pos[0] if pos else 0)) or 0.0
            fin = _nombre(a.get("end", pos[1] if len(pos) > 1 else None))
            if fin is None and (du := _nombre(a.get("duration"))) is not None:
                fin = debut + du
            ajouter(debut, fin, f"{f.nom} (temps de la source)")
        elif f.nom in ("ass", "subtitles"):
            fichier = a.get("filename", a.get("f", pos[0] if pos else None))
            if fichier:
                for debut, fin, texte in _dialogues_ass(os.path.join(cwd or "", fichier)):
                    ajouter(debut, fin, f"{f.nom} « {texte} »")
        for cle, v in f.args:
            for m in re.finditer(r"between\(\s*t\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)", v):
                ajouter(float(m.group(1)), float(m.group(2)), f"{f.nom} actif")
            for m in re.finditer(r"\b(lt|lte|gt|gte)\(\s*t\s*,\s*([\d.]+)\s*\)", v):
                t = float(m.group(2))
                ajouter(t, t, f"{f.nom} : point de l'expression à {t:g} s")
    return sortie


# ───── la commande
def analyser(args, cwd=None):
    c = Commande(list(args), cwd or os.getcwd())
    options, i, fin = [], 1, len(args) - 1        # le dernier argument est la sortie
    while i < fin:
        a = args[i]
        if a == "-i" and i + 1 <= fin:
            c.entrees.append(Entree(len(c.entrees), args[i + 1], options))
            options = []
            i += 2
            continue
        if a in ("-filter_complex", "-lavfi") and i + 1 < fin:
            c.graphe = args[i + 1]
            i += 2
            continue
        if a == "-filter_complex_script" and i + 1 < fin:
            try:
                with open(os.path.join(c.cwd, args[i + 1]), encoding="utf-8") as f:
                    c.graphe = f.read()
            except OSError:
                pass
            i += 2
            continue
        if a.startswith("-") and a not in DRAPEAUX and i + 1 < fin:
            options += [a, args[i + 1]]
            i += 2
            continue
        options.append(a)
        i += 1
    c.options_sortie = options
    c.sortie = args[-1] if len(args) > 1 and not args[-1].startswith("-") else None
    if c.graphe:
        c.chaines = decouper_graphe(c.graphe)
    else:
        for opt, nom in (("-vf", "vidéo"), ("-filter:v", "vidéo"), ("-af", "audio"), ("-filter:a", "audio")):
            if opt in options:
                ch = _chaine(options[options.index(opt) + 1])
                ch.sorties = ch.sorties or [nom]
                c.chaines.append(ch)
    for opt in ("-t", "-to"):
        if opt in options and (d := _nombre(options[options.index(opt) + 1])) is not None:
            c.duree = d
            break
    return c


SOURCES_VIDEO = {"color", "gradients", "testsrc", "testsrc2", "nullsrc", "smptebars", "smptehdbars", "rgbtestsrc",
                 "yuvtestsrc", "mandelbrot", "cellauto", "life", "allrgb", "allyuv", "colorspectrum", "colorchart",
                 "pal75bars", "pal100bars", "haldclutsrc", "sierpinski", "zoneplate"}
# filtres qui comptent depuis la première image (et pas en secondes) : un extrait qui ne commence pas à 0 les fausse
FILTRES_SENSIBLES = {"xfade", "concat", "loop", "select", "framestep", "fps", "blackframe", "framepack", "interleave"}


def _debut_rapide(c, debut):
    """Arguments d'entrée et graphe pour un extrait qui commence à « debut » sans calculer ce qui précède :
    les entrées fichier démarrent à debut (-ss en entrée, puis setpts pour garder les vrais temps t), les sources
    vidéo calculées (lavfi, color…) sont coupées (trim) avant les filtres. Renvoie (args, raison) ; args None si le
    graphe contient un filtre que ce découpage fausserait (raison dit lequel)."""
    if not c.graphe or debut <= 0:
        return None, "pas de graphe de filtres"
    for ch in c.chaines:
        for f in ch.filtres:
            a = {k: v for k, v in f.args if k}
            if f.nom in FILTRES_SENSIBLES:
                return None, f"filtre « {f.nom} »"
            if f.nom in ("fade", "afade") and "st" not in a and "start_time" not in a:
                return None, f"« {f.nom} » réglé en images"
            if f.nom in ("tpad", "apad") and any(k.startswith("start") for k in a):
                return None, f"« {f.nom} » au début"
            if f.nom in ("setpts", "asetpts") and re.search(r"\bN\b", f.texte):
                return None, f"« {f.nom} » compté en images"
    # les entrées utilisées seulement comme vidéo dans le graphe ([n:v]), et jamais directement par -map
    usages = {}
    for ch in c.chaines:
        for etiquette in ch.entrees:
            if m := re.fullmatch(r"(\d+)(?::(\w))?.*", etiquette):
                usages.setdefault(int(m.group(1)), set()).add(m.group(2) or "?")
    mappees = {int(m.group(1)) for k, v in enumerate(c.options_sortie[:-1])
               if v == "-map" and (m := re.match(r"(\d+)", c.options_sortie[k + 1]))}
    lavfi = {e.index for e in c.entrees if "lavfi" in e.options}
    video = {n for n, u in usages.items() if u == {"v"} and n not in mappees}
    fichiers = video - lavfi

    chaines = []
    for ch in _scinder(c.graphe, ";"):          # sources calculées dans le graphe (color=…) : coupées tout de suite
        texte = ch.strip()
        if texte and not texte.startswith("[") and texte.split("=", 1)[0].split(",", 1)[0].strip() in SOURCES_VIDEO:
            premier = _scinder(texte, ",")[0]
            texte = premier + f",trim=start={debut:.3f}" + texte[len(premier):]
        if texte:
            chaines.append(texte)
    # chaque usage d'une entrée vidéo [n:v] passe d'abord par une petite chaîne qui la recale (ou la coupe)
    prefixes = []

    def recaler(m):
        n = int(m.group(1))
        if n not in video:
            return m.group(0)
        etiquette = f"tm{n}_{len(prefixes)}"
        ajout = f"setpts=PTS+{debut:.3f}/TB" if n in fichiers else f"trim=start={debut:.3f}"
        prefixes.append(f"[{n}:v]{ajout}[{etiquette}]")
        return f"[{etiquette}]"
    graphe = re.sub(r"\[(\d+):v\]", recaler, ";".join(chaines))

    args, n, k = list(c.args), 0, 1
    while k < len(args) - 1:
        if args[k] == "-filter_complex":
            args[k + 1] = ";".join(prefixes + [graphe])
            k += 2
            continue
        if args[k] == "-i":
            if n in fichiers:
                args[k:k] = ["-ss", f"{debut:.3f}"]
                k += 2
            n += 1
            k += 2
            continue
        k += 1
    return args, f"{len(fichiers)} entrée(s) fichier démarrées à {debut:.1f} s"


def commande_apercu(args, sortie, ffmpeg=None, debut=0.0, duree=None, commande=None):
    """La même commande, encodée vite (ultrafast), avec la progression sur stdout, vers un fichier d'aperçu.
    Avec debut / duree : un extrait ; si la commande analysée est donnée, il démarre vite quand c'est sûr.
    Renvoie (args, note) — note dit si l'extrait a pu démarrer vite."""
    note = ""
    if commande is not None and debut > 0:
        rapides, raison = _debut_rapide(commande, debut)
        if rapides:
            args, note = rapides, f"démarrage rapide ({raison})"
        else:
            note = f"démarrage complet : tout ce qui précède {debut:.1f} s est calculé ({raison})"
    corps, a, i = list(args[1:-1]), [], 0
    remplacees = {"-preset": "ultrafast", "-crf": "28"}
    while i < len(corps):
        x = corps[i]
        if x in ("-loglevel", "-v", "-progress", "-stats_period"):
            i += 2
        elif x in ("-y", "-n", "-stats", "-nostats", "-hide_banner"):
            i += 1
        elif x in remplacees:
            a += [x, remplacees[x]]
            i += 2
        else:
            a.append(x)
            i += 1
    if debut > 0 or duree:
        a += ["-ss", f"{debut:.3f}"] if debut > 0 else []
        a += ["-t", f"{duree:.3f}"] if duree else []
    return [ffmpeg or args[0], "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y", *a,
            sortie], note


# ───── médias, courbes et transitions (pour la timeline)
EXT_IMAGES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}
EXT_VIDEOS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg"}
_FONCTIONS_EXPR = {
    "_si": lambda c, a, b=0: a if c else b, "lt": lambda a, b: float(a < b), "lte": lambda a, b: float(a <= b),
    "gt": lambda a, b: float(a > b), "gte": lambda a, b: float(a >= b), "eq": lambda a, b: float(a == b),
    "between": lambda x, a, b: float(a <= x <= b), "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "exp": math.exp, "log": math.log, "sqrt": math.sqrt, "abs": abs, "min": min, "max": max, "pow": pow,
    "mod": math.fmod, "floor": math.floor, "ceil": math.ceil, "trunc": math.trunc, "round": round,
    "clip": lambda x, a, b: max(a, min(b, x)), "_pi": math.pi,
}


def expression_temps(texte):
    """Une expression ffmpeg en t (if, lt, between, sin…) → fonction Python de t, ou None si elle utilise autre
    chose que t (variables de pixel, d'image…) ou n'est pas comprise."""
    if not re.search(r"(?<![\w.])t(?![\w(])", texte):
        return None
    py = re.sub(r"(?<![\w.])if\(", "_si(", texte.replace("^", "**"))
    py = re.sub(r"(?<![\w.])PI(?!\w)", "_pi", py)
    if set(re.findall(r"(?<![\w.])[A-Za-z_]\w*", py)) - set(_FONCTIONS_EXPR) - {"t"}:
        return None
    try:
        code = compile(py, "<expression ffmpeg>", "eval")
    except SyntaxError:
        return None
    return lambda t: eval(code, {"__builtins__": {}}, {**_FONCTIONS_EXPR, "t": t})    # noqa: S307 (opérations seules)


def _paires_options(options):
    """Les options d'une entrée en {option: valeur} (les drapeaux sans valeur valent True)."""
    sortie, k = {}, 0
    while k < len(options):
        if options[k] in DRAPEAUX or k + 1 >= len(options):
            sortie[options[k]] = True
            k += 1
        else:
            sortie[options[k]] = options[k + 1]
            k += 2
    return sortie


def _entree_de(c, etiquette, profondeur=0):
    """L'entrée (#n) d'où vient une étiquette du graphe, en remontant les chaînes à une seule entrée."""
    if m := re.fullmatch(r"(\d+)(?::\w)?", etiquette):
        return int(m.group(1))
    if profondeur > 20:
        return None
    for ch in c.chaines:
        if etiquette in ch.sorties and len(ch.entrees) == 1:
            return _entree_de(c, ch.entrees[0], profondeur + 1)
    return None


def medias(c, duree_film):
    """Les entrées vidéo : [{index, nom, vignette (image ou None), debut, fin, genre}]. Le début vaut l'offset d'un
    xfade quand l'entrée y arrive en second, 0 sinon."""
    decalages = {}
    for ch in c.chaines:
        for f in ch.filtres:
            if f.nom == "xfade" and len(ch.entrees) >= 2:
                offset = _nombre(dict((k, v) for k, v in f.args if k).get("offset"))
                n = _entree_de(c, ch.entrees[1])
                if n is not None and offset is not None:
                    decalages[n] = offset
    sortie = []
    for e in c.entrees:
        o = _paires_options(e.options)
        debut = decalages.get(e.index, 0.0)
        if o.get("-f") == "lavfi":
            source = e.source.split("=", 1)[0].strip()
            if source not in SOURCES_VIDEO:
                continue
            d = re.search(r"(?:^|[:=])d(?:uration)?=([\d.]+)", e.source)
            fin = debut + float(d.group(1)) if d else duree_film
            sortie.append({"index": e.index, "nom": source, "vignette": None, "debut": debut, "fin": fin,
                           "genre": "source calculée"})
            continue
        chemin = os.path.join(c.cwd, e.source)
        ext = os.path.splitext(e.source)[1].lower()
        if ext in EXT_IMAGES:
            if "%" in e.source:             # séquence d'images : image_%04d.png
                debut_n = int(o.get("-start_number", 0) or 0) if o.get("-start_number") not in (None, True) else 0
                try:
                    premier = chemin % debut_n
                    if not os.path.exists(premier):
                        debut_n, premier = 1, chemin % 1
                    n = 0
                    while n < 200000 and os.path.exists(chemin % (debut_n + n)):
                        n += 1
                except TypeError:
                    premier, n = None, 0
                ips = _nombre(o.get("-framerate")) or _nombre(o.get("-r")) or 25.0
                fin = debut + (n / ips if n else 0)
                sortie.append({"index": e.index, "nom": os.path.basename(e.source), "vignette": premier if n else None,
                               "debut": debut, "fin": fin,
                               "genre": f"séquence de {n} images à {ips:g} i/s" if n else "séquence introuvable"})
            else:
                fin = debut + (_nombre(o.get("-t")) or (duree_film - debut if o.get("-loop") else 0.04))
                sortie.append({"index": e.index, "nom": os.path.basename(e.source), "vignette": chemin,
                               "debut": debut, "fin": fin, "genre": "image"})
        elif ext in EXT_VIDEOS:
            fin = debut + (_nombre(o.get("-t")) or duree_film - debut)
            sortie.append({"index": e.index, "nom": os.path.basename(e.source), "vignette": None,
                           "debut": debut, "fin": fin, "genre": "vidéo"})
    return sortie


def courbes(c, duree_film, points=480):
    """Les paramètres qui varient avec t (eq : luminosité, contraste, saturation, gamma ; volume) :
    [{nom, ligne, entree, points [(t, v)], mini, maxi}]. « entree » : l'image que la courbe module (l'autre entrée du
    filtre qui reçoit la courbe, par exemple un blend), ou None."""
    sortie = []
    for ch in c.chaines:
        etiquette = ch.sorties[0] if ch.sorties else None
        for f in ch.filtres:
            a = {k: v for k, v in f.args if k}
            pos = [v for k, v in f.args if not k]
            params = []
            if f.nom == "eq":
                params = [(k, a[k]) for k in ("brightness", "contrast", "saturation", "gamma") if k in a]
            elif f.nom == "volume":
                params = [("volume", a.get("volume", pos[0] if pos else ""))]
            for nom_param, texte in params:
                fonction = expression_temps(texte)
                if fonction is None:
                    continue
                try:
                    pts = [(t, float(fonction(t))) for t in (duree_film * i / (points - 1) for i in range(points))]
                except (ArithmeticError, TypeError, ValueError, OverflowError):
                    continue
                valeurs = [v for _, v in pts]
                if max(valeurs) - min(valeurs) < 1e-9:
                    continue
                entree = None
                if etiquette and f.nom == "eq":     # le mélange d'images qui reçoit cette courbe, et son autre entrée
                    for autre in c.chaines:
                        if etiquette in autre.entrees and len(autre.entrees) >= 2 and autre.filtres \
                                and autre.filtres[0].nom in ("blend", "overlay", "maskedmerge", "alphamerge"):
                            for e in autre.entrees:
                                if e != etiquette and (n := _entree_de(c, e)) is not None:
                                    entree = n
                                    break
                if entree is None and len(ch.entrees) == 1 and f.nom == "eq":
                    entree = _entree_de(c, ch.entrees[0])
                sortie.append({"nom": f"{f.nom} {nom_param}", "ligne": f"[{etiquette}]" if etiquette else f.nom,
                               "entree": entree, "points": pts, "mini": min(valeurs), "maxi": max(valeurs)})
    return sortie


FILTRES_SON = {"amix", "amerge", "afade", "adelay", "aresample", "aformat", "apad", "atrim", "alimiter", "volume", "pan",
               "highpass", "lowpass", "bandpass", "tremolo", "aecho", "loudnorm", "acompressor", "equalizer"}


def noms_lignes(c, liste_courbes=()):
    """Un nom parlant pour chaque rangée de repères (étiquette de sortie d'une chaîne) : « Image finale » ou
    « Son final » pour ce qui est envoyé à la sortie (-map), « Intensité de brume.png » pour une courbe."""
    mappees = {c.options_sortie[k + 1].strip("[]") for k, v in enumerate(c.options_sortie[:-1]) if v == "-map"}
    noms = {}
    for ch in c.chaines:
        for s in ch.sorties:
            if s in mappees:
                son = ch.filtres and all(f.nom in FILTRES_SON for f in ch.filtres)
                noms[f"[{s}]"] = "Son final" if son else "Image finale"
    images = {e.index: os.path.basename(e.source) for e in c.entrees}
    for k in liste_courbes:
        if k["entree"] is not None and k["ligne"] not in noms:
            noms[k["ligne"]] = f"Intensité de {images.get(k['entree'], '#' + str(k['entree']))}"
    return noms


def transitions(c):
    """Fondus et fondus enchaînés : [{genre (entree, sortie, enchaine), debut, fin, texte, son}]."""
    sortie = []
    for iv in c.intervalles():
        if iv.fin <= iv.debut:
            continue
        son = iv.texte.startswith("afade")
        if iv.texte.endswith(" in"):
            genre = "entree"
        elif iv.texte.endswith(" out"):
            genre = "sortie"
        elif iv.texte.startswith("xfade"):
            genre = "enchaine"
        else:
            continue
        nom = {"entree": "fondu d'ouverture", "sortie": "fondu de fermeture", "enchaine": "fondu enchaîné"}[genre]
        sortie.append({"genre": genre, "debut": iv.debut, "fin": iv.fin, "son": son,
                       "texte": f"{nom}{' du son' if son else ''} ({iv.texte}) : {iv.debut:.2f} → {iv.fin:.2f} s"})
    return sortie


FORMATS = {    # clé : (libellé, extension, options d'encodage ; None = celles du script)
    "script": ("MP4 – comme le script", ".mp4", None),
    "h265": ("MP4 – H.265, environ deux fois plus léger", ".mp4",
             ["-c:v", "libx265", "-preset", "medium", "-crf", "24", "-tag:v", "hvc1", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]),
    "prores": ("MOV – ProRes 422 HQ, pour un autre logiciel de montage", ".mov",
               ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-c:a", "pcm_s16le"]),
    "mkv": ("MKV – H.264", ".mkv",
            ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]),
    "webm": ("WebM – VP9, pour le web", ".webm",
             ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1", "-pix_fmt", "yuv420p",
              "-c:a", "libopus", "-b:a", "160k"]),
}
OPTIONS_CODAGE = {"-c", "-codec", "-c:v", "-vcodec", "-codec:v", "-c:a", "-acodec", "-codec:a", "-preset", "-crf", "-tune",
                  "-profile:v", "-pix_fmt", "-b:v", "-b:a", "-movflags", "-tag:v", "-x264-params", "-x265-params",
                  "-level", "-qscale:v", "-q:v"}


def adapter_sortie(args, sortie, format_):
    """La commande avec un autre fichier de sortie et, sauf format « script », d'autres options d'encodage
    (celles du script, après la dernière entrée, sont retirées ; entrées et filtres ne changent pas)."""
    a = list(args[:-1])
    options = FORMATS.get(format_, FORMATS["script"])[2]
    if options:
        entrees = [k for k, x in enumerate(a) if x == "-i"]
        coupe = entrees[-1] + 2 if entrees else 1
        tete, queue, garde, k = a[:coupe], a[coupe:], [], 0
        while k < len(queue):
            if queue[k] in OPTIONS_CODAGE and k + 1 < len(queue):
                k += 2
                continue
            garde.append(queue[k])
            k += 1
        a = tete + garde + options
    return a + [sortie]


def formater_commande(c):
    """La commande sur plusieurs lignes, une chaîne de filtres par ligne, pour la lire."""
    lignes, courant = [], [os.path.basename(c.args[0])]
    i = 1
    while i < len(c.args):
        x = c.args[i]
        if x.startswith("-") and len(x) > 1 and _nombre(x) is None:
            lignes.append(" ".join(courant))
            courant = [x]
            if x in ("-filter_complex", "-lavfi") and i + 1 < len(c.args):
                lignes.append(" ".join(courant))
                lignes += [f"    {ch.texte};" for ch in c.chaines]
                courant = []
                i += 2
                continue
        else:
            courant.append(f'"{x}"' if " " in x else x)
        i += 1
    lignes.append(" ".join(courant))
    return "\n".join(l for l in lignes if l)
