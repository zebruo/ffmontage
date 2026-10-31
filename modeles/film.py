"""Film du dossier : les vidéos et les photos du dossier (et de ses sous-dossiers), dans l'ordre alphabétique de leur
nom, enchaînées par un fondu ; un titre au début ; la musique du dossier dessous.

Script de départ créé par la table de montage : à adapter librement. Le bloc « # ── RÉGLAGES » est lu et modifié
par la table ; les étiquettes @Piste placent les temps sur sa timeline.
- Numéroter les fichiers (01 plage.mp4, 02 photo.jpg…) pour choisir l'ordre.
- Écrit « titre.ass » (le titre) et « <NOM>_film.mp4 » (jamais d'écrasement : _2, _3…).
"""
import os
import subprocess
import sys

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
# ── Titre (couleur « #RRGGBB » ; position (x, y) : le centre du texte, en pixels de l'image)
TITRE = __NOM__                         # @Titre.texte
POLICE = "Arial"                        # @Titre.police
TAILLE_TITRE = 110                      # [20..300] @Titre.taille
COULEUR_TITRE = "#FFFFFF"               # @Titre.couleur
POSITION_TITRE = (960, 540)             # @Titre.position
TITRE_DEBUT = 1.0                       # le titre apparaît @Titre.debut
TITRE_FIN = 5.0                         # le titre a disparu @Titre.fin
TITRE_FONDU = 0.8                       # s · le titre naît et s'efface en fondu [0..3]
# ── Musique
MUSIQUE = ""                            # vide : la première musique du dossier @fichier
VOLUME = 1.0                            # [0..2]
MUSIQUE_DEBUT = 0.0                     # la musique commence @Musique.debut
FONDU_MUSIQUE = 3.0                     # s · la musique s'éteint à la fin du film [0..10]
# ── FIN RÉGLAGES ─────────────────────────────────────────────────────────────────────────────────────────────────

VIDEOS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".webm", ".wmv"}
PHOTOS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
SONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


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


def duree(fichier):
    sortie = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", fichier],
                            cwd=ICI, capture_output=True, text=True).stdout.strip()
    try:
        return float(sortie)
    except ValueError:
        return 0.0


# ───── 1. les plans : une entrée ffmpeg chacun, et leur durée
entrees, plans = [], []                 # plans : (numéro d'entrée, durée)
for fichier in fichiers(VIDEOS | PHOTOS):
    if os.path.splitext(fichier)[1].lower() in PHOTOS:
        d = DUREE_PHOTO
        entrees += ["-loop", "1", "-framerate", str(IPS), "-t", f"{d:.3f}", "-i", fichier]
    else:
        d = duree(fichier)
        if DUREE_MAX_VIDEO > 0:
            d = min(d, DUREE_MAX_VIDEO)
        if d <= 0:
            print("illisible, laissé de côté :", fichier)
            continue
        entrees += ["-t", f"{d:.3f}", "-i", fichier]
    plans.append((entrees.count("-i") - 1, d))
if not plans:                           # dossier encore vide : un fond, pour voir le titre
    entrees += ["-f", "lavfi", "-t", "10", "-i", f"color=c={COULEUR_FOND.replace('#', '0x')}:s={W}x{H}:r={IPS}"]
    plans.append((0, 10.0))

# le fondu ne peut pas dépasser la moitié du plus court des plans
fondu = min(FONDU, min(d for _, d in plans) / 2) if len(plans) > 1 else 0.0
debuts = [0.0]                         # chaque plan commence pendant le fondu qui termine le précédent
for _, d in plans[:-1]:
    debuts.append(debuts[-1] + d - fondu)
PLANS = [(round(a, 3), round(a + d, 3)) for a, (_, d) in zip(debuts, plans)]   # (début, fin) de chaque plan @Plans.intervalles
FIN = PLANS[-1][1]                      # durée du film ; la musique est coupée là @Film.fin @Musique.fin

# ───── 2. l'image : chaque plan à la taille du film, puis les fondus enchaînés
fond = COULEUR_FOND.replace("#", "0x")
graphe = []
for k, (n, d) in enumerate(plans):
    graphe.append(f"[{n}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                  f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={fond},setsar=1,fps={IPS},format=yuv420p,settb=AVTB[p{k}]")
courant = "p0"
for k in range(1, len(plans)):
    graphe.append(f"[{courant}][p{k}]xfade=transition=fade:duration={fondu:.3f}:offset={PLANS[k][0]:.3f}[x{k}]")
    courant = f"x{k}"

# ───── 3. le titre (sous-titres .ass : police, couleur, position)
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
graphe.append(f"[{courant}]subtitles={ASS},fade=t=in:st=0:d={FONDU_ENTREE},"
              f"fade=t=out:st={max(0.0, FIN - FONDU_SORTIE):.3f}:d={FONDU_SORTIE}[v]")

# ───── 4. la musique
musiques = [MUSIQUE] if MUSIQUE else fichiers(SONS)
cartes = ["-map", "[v]"]
if musiques:
    entrees += ["-i", musiques[0]]
    n = entrees.count("-i") - 1
    retard = int(MUSIQUE_DEBUT * 1000)
    graphe.append(f"[{n}:a]adelay={retard}:all=1,volume={VOLUME},"
                  f"afade=t=out:st={max(0.0, FIN - FONDU_MUSIQUE):.3f}:d={FONDU_MUSIQUE},atrim=0:{FIN:.3f}[a]")
    cartes += ["-map", "[a]"]

# ───── 5. le film
base = os.path.join(ICI, NOM + "_film")
SORTIE = next(n for n in [base + ".mp4"] + [f"{base}_{k}.mp4" for k in range(2, 100)] if not os.path.exists(n))
subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y", *entrees,
                "-filter_complex", ";".join(graphe), *cartes,
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
                "-t", f"{FIN:.3f}", "-movflags", "+faststart", SORTIE], cwd=ICI, check=True)
print("film :", SORTIE)
