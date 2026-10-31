"""Exécute un script de montage dans un processus séparé (appelé par la table de montage, pas à la main).

    lanceur capture <script> <fichier.json> [--apercu]
                                              lance le script sans exécuter ffmpeg ; écrit dans le fichier JSON les
                                              commandes ffmpeg qu'il aurait lancées (arguments et dossier) et la valeur
                                              finale de ses variables en MAJUSCULES ; avec --apercu, les réglages
                                              marqués @apercu=… prennent cette valeur
    lanceur execute <script>                  lance le script pour de vrai ; ffmpeg écrit sa progression sur stdout

Option --source <fichier> : le code est lu dans ce fichier (la version modifiée, pas encore enregistrée), mais le
script s'exécute comme s'il était <script> (__file__, dossier courant).
Options de execute --remplace <sortie du script> --sortie <fichier> --format <clé> : l'appel à ffmpeg qui écrit
<sortie du script> écrit à la place <fichier>, encodé selon le format (voir ffmpeg_analyse.FORMATS).

En capture, les fichiers que le script ouvre avec open() sont notés (lus ou écrits) dans le JSON.
On remplace subprocess.Popen, par lequel passent aussi run, call, check_call et check_output.
Les appels à ffmpeg faits autrement (os.system…) ne sont pas vus.
"""
import builtins
import io
import json
import os
import re
import subprocess
import sys
import traceback

_VRAI_POPEN = subprocess.Popen


def _est_ffmpeg(cmd):
    if isinstance(cmd, (str, bytes)):
        cmd = os.fsdecode(cmd).split()
    if not cmd:
        return False
    return os.path.splitext(os.path.basename(os.fsdecode(cmd[0])))[0].lower() == "ffmpeg"


def _arguments(cmd):
    if isinstance(cmd, (str, bytes)):
        import shlex
        return [a.strip('"') for a in shlex.split(os.fsdecode(cmd), posix=False)]
    return [os.fsdecode(a) if isinstance(a, (bytes, os.PathLike)) else str(a) for a in cmd]


def _popen_capture(captures):
    class PopenCapture(_VRAI_POPEN):
        def __init__(self, args, *a, **kw):
            self._faux = _est_ffmpeg(args)
            if not self._faux:
                super().__init__(args, *a, **kw)
                return
            captures.append({"args": _arguments(args), "cwd": os.path.abspath(kw.get("cwd") or os.getcwd())})
            self.args, self.returncode, self.pid, self._child_created = args, 0, 0, False
            self.stdin = self.stdout = self.stderr = None
            texte = kw.get("text") or kw.get("universal_newlines") or kw.get("encoding") or kw.get("errors")
            self._vide = "" if texte else b""
            self._capture_sortie = kw.get("stdout") is not None, kw.get("stderr") is not None

        def communicate(self, input=None, timeout=None):
            if not self._faux:
                return super().communicate(input, timeout)
            return tuple(self._vide if c else None for c in self._capture_sortie)

        def wait(self, timeout=None):
            return 0 if self._faux else super().wait(timeout)

        def poll(self):
            return 0 if self._faux else super().poll()

        def kill(self):
            if not self._faux:
                super().kill()

        terminate = kill

    return PopenCapture


_SORTIE = {"remplace": None, "sortie": None, "format": "script", "trouvee": False}


def _meme_fichier(chemin, cwd, autre):
    norme = lambda c: os.path.normcase(os.path.abspath(c))
    return norme(os.path.join(cwd or os.getcwd(), chemin)) == norme(autre)


class _PopenProgression(_VRAI_POPEN):
    """Ajoute « -progress pipe:1 » aux appels de ffmpeg dont le script ne lit pas lui-même la sortie ; remplace le
    fichier de sortie et le format si demandé."""

    def __init__(self, args, *a, **kw):
        if _est_ffmpeg(args) and not isinstance(args, (str, bytes)):
            args = _arguments(args)
            if _SORTIE["remplace"] and _meme_fichier(args[-1], kw.get("cwd"), _SORTIE["remplace"]):
                from tablemontage.ffmpeg_analyse import adapter_sortie
                args = adapter_sortie(args, _SORTIE["sortie"], _SORTIE["format"])
                _SORTIE["trouvee"] = True
            if kw.get("stdout") is None and len(a) < 3:
                args = [args[0], "-progress", "pipe:1", "-nostats", *(x for x in args[1:] if x != "-stats")]
        super().__init__(args, *a, **kw)


def _executer(script, variables, apercu=False, code_source=None):
    """Exécute le script comme « python script.py », ses variables globales dans le dictionnaire donné."""
    script = os.path.abspath(script)
    dossier = os.path.dirname(script)
    sys.argv = [script]
    sys.path.insert(0, dossier)
    os.chdir(dossier)
    variables.update(__name__="__main__", __file__=script, __builtins__=builtins)
    try:
        with open(code_source or script, "rb") as f:
            source = f.read()
        if apercu:
            from tablemontage.reglages import texte_apercu
            source = texte_apercu(source.decode("utf-8-sig"))
        exec(compile(source, script, "exec"), variables)
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:
        traceback.print_exc()
        return 1


def _suivre_fichiers(fichiers, a_ignorer):
    """Remplace open() pour noter {chemin: {"lu", "écrit"}} ; les fichiers de Python et a_ignorer ne sont pas notés."""
    vrai_open = builtins.open
    dossiers_python = tuple(os.path.normcase(os.path.abspath(d)) for d in {sys.prefix, sys.base_prefix, sys.exec_prefix})
    ignores = {os.path.normcase(os.path.abspath(c)) for c in a_ignorer if c}

    def open_suivi(fichier, mode="r", *a, **kw):
        if isinstance(fichier, (str, bytes, os.PathLike)):
            try:
                chemin = os.path.abspath(os.fsdecode(fichier))
                norme = os.path.normcase(chemin)
                if norme not in ignores and not norme.startswith(dossiers_python):
                    fichiers.setdefault(chemin, set()).add("écrit" if any(c in mode for c in "wax+") else "lu")
            except (TypeError, ValueError):
                pass
        return vrai_open(fichier, mode, *a, **kw)
    builtins.open = io.open = open_suivi
    return vrai_open


def _valeurs(variables):
    """Les variables en MAJUSCULES qu'on peut écrire en JSON (nombres, textes, listes de nombres…)."""
    sortie = {}
    for nom, v in variables.items():
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", nom) and not callable(v):
            try:
                json.dumps(v, allow_nan=False)
                sortie[nom] = v
            except (TypeError, ValueError):
                pass
    return sortie


def principal(argv):
    for flux in (sys.stdout, sys.stderr):
        if flux:
            flux.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    argv = list(argv)
    code_source = None
    if "--source" in argv and argv.index("--source") + 1 < len(argv):
        i = argv.index("--source")
        code_source = argv[i + 1]
        del argv[i:i + 2]
    for option in ("--remplace", "--sortie", "--format"):
        if option in argv and argv.index(option) + 1 < len(argv):
            i = argv.index(option)
            _SORTIE[option[2:]] = argv[i + 1]
            del argv[i:i + 2]
    apercu = "--apercu" in argv
    argv = [a for a in argv if a != "--apercu"]
    if len(argv) < 2 or argv[0] not in ("capture", "execute") or (argv[0] == "capture" and len(argv) < 3):
        print(__doc__, file=sys.stderr)
        return 2
    mode, script, variables = argv[0], argv[1], {}
    if mode == "execute":
        subprocess.Popen = _PopenProgression
        code = _executer(script, variables, code_source=code_source)
        if _SORTIE["remplace"] and not _SORTIE["trouvee"]:
            print(f"Attention : le script n'a pas écrit {_SORTIE['remplace']} ; le film est là où le script l'a "
                  f"prévu, pas dans {_SORTIE['sortie']}.", file=sys.stderr)
        return code
    captures, fichiers = [], {}
    subprocess.Popen = _popen_capture(captures)
    vrai_open = _suivre_fichiers(fichiers, [script, code_source, argv[2]])
    try:
        code = _executer(script, variables, apercu, code_source)
    finally:
        builtins.open = io.open = vrai_open
    with open(argv[2], "w", encoding="utf-8") as f:
        json.dump({"code": code, "commandes": captures, "valeurs": _valeurs(variables),
                   "fichiers": [{"chemin": c, "acces": sorted(a)} for c, a in fichiers.items()]},
                  f, ensure_ascii=False, indent=1)
    return code
