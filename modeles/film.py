"""Film du dossier : les vidéos, les photos et les animations (suites d'images numérotées) du dossier et de ses
sous-dossiers, dans l'ordre alphabétique de leur nom, enchaînées par un fondu ; un titre au début ; le son des
vidéos ; les musiques du dossier dessous, enchaînées, baissées pendant le son des vidéos.

Script de départ créé par la table de montage : à adapter librement. Le bloc « # ── RÉGLAGES » est lu et modifié
par la table ; les étiquettes @Piste placent les temps sur sa timeline.
- Numéroter les fichiers (01 plage.mp4, 02 photo.jpg…) pour choisir l'ordre.
- Une suite d'au moins SUITE_MIN images de même nom numérotées (rendu_0001.png, rendu_0002.png…) est une animation :
  un seul plan, à SUITE_IPS images par seconde ; s'il manque des images, chacune dure jusqu'à la suivante. Les .jpg
  restent des photos (les appareils photo numérotent aussi leurs photos).
- Écrit « titre.ass » (le titre) et « <NOM>_film.mp4 » (jamais d'écrasement : _2, _3…).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")
ICI = os.path.dirname(os.path.abspath(__file__))

# ── RÉGLAGES ─────────────────────────────────────────────────────────────────────────────────────────────────────
NOM = __NOM__                           # le film s'appellera « NOM_film.mp4 » @nom=Nom_du_fichier
W, H = 1920, 1080                       # taille de l'image @nom=Largeur,Hauteur
IPS = 30                                # images par seconde (10 pour les aperçus : plus rapide) [1..60] @apercu=10 @nom=Images_par_seconde
# ── Plans
DUREE_PHOTO = 4.0                       # s · temps d'une photo à l'écran [0.5..30]
DUREE_MAX_VIDEO = 0.0                   # s · une vidéo plus longue est coupée (0 : vidéos entières) [0..600]
FONDU = 1.0                             # s · fondu enchaîné entre deux plans [0..3]
COULEUR_FOND = "#000000"                # autour des plans qui n'ont pas la forme de l'image @couleur
FONDU_ENTREE = 1.0                      # s · fondu depuis le noir au début [0..10]
FONDU_SORTIE = 2.0                      # s · fondu au noir à la fin [0..10]
# ── Animations (suites d'images numérotées : rendus d'un logiciel 3D, d'animation…)
SUITES = True                           # une suite numérotée est une animation (False : chaque image est une photo)
SUITE_MIN = 24                          # images, au moins, pour faire une animation [2..1000]
SUITE_IPS = 24                          # images par seconde de l'animation (celles du rendu) [1..60]
# ── Titre (couleur « #RRGGBB » ; position (x, y) : le centre du texte, en pixels de l'image)
TITRE = __NOM__                         # vide : pas de titre @Titre.texte
POLICE = "Arial"                        # @Titre.police
TAILLE_TITRE = 110                      # [20..300] @Titre.taille
COULEUR_TITRE = "#FFFFFF"               # @Titre.couleur
POSITION_TITRE = (960, 540)             # @Titre.position
TITRE_DEBUT = 1.0                       # le titre apparaît @Titre.debut
TITRE_FIN = 5.0                         # le titre a disparu @Titre.fin
TITRE_FONDU = 0.8                       # s · le titre naît et s'efface en fondu [0..3]
# ── Son des vidéos
SON_VIDEOS = True                       # garder le son des vidéos
VOLUME_VIDEOS = 1.0                     # [0..2]
# ── Musique
MUSIQUE = ""                            # vide : toutes les musiques du dossier, enchaînées par ordre alphabétique @fichier
VOLUME = 1.0                            # [0..2]
MUSIQUE_DEBUT = 0.0                     # la musique commence @Musique.debut
MUSIQUE_BOUCLE = True                   # reprendre la musique au début si elle est plus courte que le film
FONDU_ENTRE_MUSIQUES = 2.0              # s · fondu enchaîné d'une musique à la suivante (0 : bout à bout) [0..10]
MUSIQUE_SOUS_VIDEOS = 0.3               # volume de la musique pendant le son des vidéos (1 : inchangé) [0..1]
FONDU_MUSIQUE = 3.0                     # s · le son s'éteint à la fin du film [0..10]
# ── FIN RÉGLAGES ─────────────────────────────────────────────────────────────────────────────────────────────────

VIDEOS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".webm", ".wmv"}
PHOTOS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
SONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
EXT_SUITES = {".png", ".webp", ".bmp", ".tif", ".tiff"}     # (pas les .jpg : voir en tête)
FORMAT_SON = "aformat=sample_rates=48000:channel_layouts=stereo"


def erreur(message):
    print("Erreur :", message)
    sys.exit(1)


for outil in ("ffmpeg", "ffprobe"):
    if not shutil.which(outil):
        erreur(f"{outil} introuvable : l'installer et l'ajouter au PATH (ou l'indiquer dans la table de montage)")


def fichiers(extensions):
    """Les fichiers du dossier et de ses sous-dossiers qui ont ces extensions, dans l'ordre alphabétique (chemins
    relatifs au dossier du script) ; les films faits par ce script ne sont pas repris."""
    trouves = []
    for dossier, sous_dossiers, noms in os.walk(ICI):
        sous_dossiers[:] = sorted(d for d in sous_dossiers if not d.startswith((".", "_")))
        for nom in noms:
            if os.path.splitext(nom)[1].lower() in extensions and not nom.startswith(NOM + "_film"):
                trouves.append(os.path.relpath(os.path.join(dossier, nom), ICI))
    return sorted(trouves, key=lambda c: (os.path.basename(c).lower(), c.lower()))   # par nom, sous-dossiers mêlés


def sonde(fichier, *options):
    return subprocess.run(["ffprobe", "-v", "error", *options, "-of", "csv=p=0", fichier],
                          cwd=ICI, capture_output=True, text=True).stdout.strip()


def duree(fichier):
    try:
        return float(sonde(fichier, "-show_entries", "format=duration"))
    except ValueError:
        return 0.0


def a_du_son(fichier):
    return bool(sonde(fichier, "-select_streams", "a", "-show_entries", "stream=index"))


def elements_visuels():
    """Dans l'ordre : ("video", chemin), ("photo", chemin) ou ("suite", [(numéro, chemin)…]) ; une suite prend la
    place de sa première image."""
    tous = fichiers(VIDEOS | PHOTOS)
    groupes = {}
    for c in tous:
        base, ext = os.path.splitext(c)
        m = re.fullmatch(r"(.*?)(\d+)", base)
        if SUITES and m and ext.lower() in EXT_SUITES:
            groupes.setdefault((m.group(1), ext.lower()), []).append((int(m.group(2)), c))
    suites = {cle: sorted(v) for cle, v in groupes.items() if len(v) >= SUITE_MIN}
    suite_de = {c: cle for cle, v in suites.items() for _, c in v}
    sortie, places = [], set()
    for c in tous:
        if c in suite_de:
            if suite_de[c] not in places:
                places.add(suite_de[c])
                sortie.append(("suite", suites[suite_de[c]]))
        elif os.path.splitext(c)[1].lower() in PHOTOS:
            sortie.append(("photo", c))
        else:
            sortie.append(("video", c))
    return sortie


def entree_suite(suite, k):
    """Les options d'entrée d'une animation, et sa durée. Suite complète : le motif (rendu_%04d.png) ; avec des
    trous : une liste où chaque image dure jusqu'à la suivante."""
    numeros = [n for n, _ in suite]
    largeurs = {len(re.search(r"(\d+)$", os.path.splitext(c)[0]).group(1)) for _, c in suite}
    d = (numeros[-1] - numeros[0] + 1) / SUITE_IPS
    if numeros == list(range(numeros[0], numeros[0] + len(numeros))) and len(largeurs) == 1:
        base, ext = os.path.splitext(suite[0][1])
        prefixe = re.sub(r"\d+$", "", base).replace("%", "%%")
        return ["-framerate", str(SUITE_IPS), "-start_number", str(numeros[0]),
                "-i", f"{prefixe}%0{largeurs.pop()}d{ext}"], d
    liste = os.path.join(tempfile.gettempdir(), f"{NOM}_animation_{k}.txt")
    chemin = lambda c: os.path.join(ICI, c).replace("\\", "/").replace("'", "'\\''")
    with open(liste, "w", encoding="utf-8") as f:
        for (n, c), suivante in zip(suite, numeros[1:] + [numeros[-1] + 1]):
            f.write(f"file '{chemin(c)}'\nduration {(suivante - n) / SUITE_IPS:.6f}\n")
        f.write(f"file '{chemin(suite[-1][1])}'\n")         # (ffmpeg ignore la durée de la dernière)
    return ["-f", "concat", "-safe", "0", "-i", liste], d


# ───── 1. les plans : une entrée ffmpeg chacun, et leur durée
entrees, plans = [], []                 # plans : (numéro d'entrée, durée, avec son)
compte = {"video": 0, "photo": 0, "suite": 0}
premiere_suite = None
for genre, quoi in elements_visuels():
    son = False
    if genre == "photo":
        d = DUREE_PHOTO
        entrees += ["-loop", "1", "-framerate", str(IPS), "-t", f"{d:.3f}", "-i", quoi]
    elif genre == "suite":
        options, d = entree_suite(quoi, compte["suite"])
        entrees += options
        if not plans:
            premiere_suite = [n for n, _ in quoi]
    else:
        d = duree(quoi)
        if DUREE_MAX_VIDEO > 0:
            d = min(d, DUREE_MAX_VIDEO)
        if d <= 0:
            print("illisible, laissé de côté :", quoi)
            continue
        entrees += ["-t", f"{d:.3f}", "-i", quoi]
        son = SON_VIDEOS and a_du_son(quoi)
    compte[genre] += 1
    plans.append((entrees.count("-i") - 1, d, son))
if not plans:                           # dossier encore vide : un fond, pour voir le titre
    entrees += ["-f", "lavfi", "-t", "10", "-i", f"color=c={COULEUR_FOND.replace('#', '0x')}:s={W}x{H}:r={IPS}"]
    plans.append((0, 10.0, False))

# le fondu ne peut pas dépasser la moitié du plus court des plans
fondu = min(FONDU, min(d for _, d, _ in plans) / 2) if len(plans) > 1 else 0.0
debuts = [0.0]                         # chaque plan commence pendant le fondu qui termine le précédent
for _, d, _ in plans[:-1]:
    debuts.append(debuts[-1] + d - fondu)
PLANS = [(round(a, 3), round(a + d, 3)) for a, (_, d, _) in zip(debuts, plans)]   # (début, fin) de chaque plan @Plans.intervalles
FIN = PLANS[-1][1]                      # durée du film ; le son est coupé là @Film.fin @Musique.fin @resultat @nom=Durée_du_film
PLANS_TROUVES = f"{compte['video']} vidéo(s), {compte['photo']} photo(s), {compte['suite']} animation(s)"  # @resultat @nom=Plans
# Le compteur IMAGE de la table : les numéros de l'animation, si le film commence par elle (et à sa cadence)
if premiere_suite and IPS == SUITE_IPS:
    NUMEROS_IMAGES = premiere_suite
    NB_IMAGES = premiere_suite[-1]
    PAS_IMAGES = max([b - a for a, b in zip(premiere_suite, premiere_suite[1:])], default=1)

# ───── 2. l'image : chaque plan à la taille du film, puis les fondus enchaînés
fond = COULEUR_FOND.replace("#", "0x")
graphe = []
for k, (n, d, _) in enumerate(plans):
    graphe.append(f"[{n}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                  f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={fond},setsar=1,fps={IPS},format=yuv420p,settb=AVTB[p{k}]")
courant = "p0"
for k in range(1, len(plans)):
    graphe.append(f"[{courant}][p{k}]xfade=transition=fade:duration={fondu:.3f}:offset={PLANS[k][0]:.3f}[x{k}]")
    courant = f"x{k}"

# ───── 3. le titre (sous-titres .ass : police, couleur, position)
fondus_image = f"fade=t=in:st=0:d={FONDU_ENTREE},fade=t=out:st={max(0.0, FIN - FONDU_SORTIE):.3f}:d={FONDU_SORTIE}"
if TITRE.strip():
    hms = lambda s: f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"
    ass = lambda c: f"&H00{c[5:7]}{c[3:5]}{c[1:3]}".upper()    # « #RRGGBB » → couleur ASS « &H00BBGGRR »
    ASS = "titre.ass"
    lignes = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Titre,{POLICE},{TAILLE_TITRE},{ass(COULEUR_TITRE)},{ass(COULEUR_TITRE)},&H80000000,&H00000000,0,0,0,0,100,100,2,0,1,2,0,5,60,60,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    fad = int(TITRE_FONDU * 1000)
    lignes.append(f"Dialogue: 0,{hms(TITRE_DEBUT)},{hms(TITRE_FIN)},Titre,,0,0,0,,"
                  f"{{\\pos({POSITION_TITRE[0]},{POSITION_TITRE[1]})\\fad({fad},{fad})}}" + TITRE.replace("\n", "\\N"))
    with open(os.path.join(ICI, ASS), "w", encoding="utf-8") as f:
        f.write("\n".join(lignes) + "\n")
    graphe.append(f"[{courant}]subtitles={ASS},{fondus_image}[v]")
else:
    graphe.append(f"[{courant}]{fondus_image}[v]")

# ───── 4. le son des vidéos, chacun à la place de sa vidéo, en fondu avec elle
sons = []                               # les étiquettes à mélanger
avec_son = []                           # (début, fin) des plans qui ont du son
for k, (n, d, son) in enumerate(plans):
    if not son:
        continue
    filtres = [f"atrim=0:{d:.3f}", "asetpts=PTS-STARTPTS", FORMAT_SON, f"volume={VOLUME_VIDEOS}"]
    if k > 0 and fondu:
        filtres.append(f"afade=t=in:d={fondu:.3f}")
    if k < len(plans) - 1 and fondu:
        filtres.append(f"afade=t=out:st={d - fondu:.3f}:d={fondu:.3f}")
    filtres.append(f"adelay={round(PLANS[k][0] * 1000)}:all=1")
    graphe.append(f"[{n}:a]{','.join(filtres)}[s{k}]")
    sons.append(f"[s{k}]")
    avec_son.append(PLANS[k])
VIDEOS_SONORES = len(avec_son)          # vidéos dont le son est gardé @resultat @nom=Vidéos_avec_son

# ───── 5. la musique : les morceaux bout à bout (en fondu), repris s'il le faut jusqu'à la fin du film
if MUSIQUE:
    if not os.path.isfile(os.path.join(ICI, MUSIQUE)):
        erreur(f"musique introuvable : {MUSIQUE}")
    disponibles = [MUSIQUE]
else:
    disponibles = fichiers(SONS)
disponibles = [(m, duree(m)) for m in disponibles]
for m, d in disponibles:
    if d <= 0:
        print("musique illisible, laissée de côté :", m)
disponibles = [(m, d) for m, d in disponibles if d > 0]
morceaux, t = [], MUSIQUE_DEBUT         # (fichier, début, durée)
while disponibles and t < FIN and (MUSIQUE_BOUCLE or len(morceaux) < len(disponibles)):
    m, d = disponibles[len(morceaux) % len(disponibles)]
    morceaux.append((m, t, d))
    t += d - min(FONDU_ENTRE_MUSIQUES, d / 2)
MUSIQUES_UTILISEES = ", ".join(dict.fromkeys(os.path.basename(m) for m, _, _ in morceaux)) or "aucune"  # @resultat @nom=Musiques
if morceaux:
    etiquettes = []
    for k, (m, debut, d) in enumerate(morceaux):
        entrees += ["-i", m]
        n = entrees.count("-i") - 1
        filtres = [FORMAT_SON]
        if k > 0 and FONDU_ENTRE_MUSIQUES:
            filtres.append(f"afade=t=in:d={min(FONDU_ENTRE_MUSIQUES, d / 2):.3f}")
        if k < len(morceaux) - 1 and FONDU_ENTRE_MUSIQUES:
            x = min(FONDU_ENTRE_MUSIQUES, d / 2)
            filtres.append(f"afade=t=out:st={d - x:.3f}:d={x:.3f}")
        filtres.append(f"adelay={round(debut * 1000)}:all=1")
        graphe.append(f"[{n}:a]{','.join(filtres)}[m{k}]")
        etiquettes.append(f"[m{k}]")
    melange = f"amix=inputs={len(etiquettes)}:normalize=0:duration=longest," if len(etiquettes) > 1 else ""
    volume = str(VOLUME)
    if avec_son and MUSIQUE_SOUS_VIDEOS < 1:
        # baissée pendant le son des vidéos, avec une rampe d'une demi-seconde de part et d'autre
        r = 0.5
        dedans = [f"clip(min((t-{a - r:.3f})/{r},({b + r:.3f}-t)/{r}),0,1)" for a, b in avec_son]
        while len(dedans) > 1:
            dedans = [f"max({dedans[0]},{dedans[1]})"] + dedans[2:]
        volume = f"'{VOLUME}*(1-{1 - MUSIQUE_SOUS_VIDEOS:.3f}*{dedans[0]})':eval=frame"
    graphe.append(f"{''.join(etiquettes)}{melange}volume={volume}[musique]")
    sons.insert(0, "[musique]")

# ───── 6. le film
cartes = ["-map", "[v]"]
if sons:
    melange = f"amix=inputs={len(sons)}:normalize=0:duration=longest" if len(sons) > 1 else "anull"
    graphe.append(f"{''.join(sons)}{melange},apad,atrim=0:{FIN:.3f},"
                  f"afade=t=out:st={max(0.0, FIN - FONDU_MUSIQUE):.3f}:d={FONDU_MUSIQUE}[a]")
    cartes += ["-map", "[a]"]
base = os.path.join(ICI, NOM + "_film")
SORTIE = next(n for n in [base + ".mp4"] + [f"{base}_{k}.mp4" for k in range(2, 100)] if not os.path.exists(n))
subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y", *entrees,
                "-filter_complex", ";".join(graphe), *cartes,
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
                "-t", f"{FIN:.3f}", "-movflags", "+faststart", SORTIE], cwd=ICI, check=True)
print("film :", SORTIE)
