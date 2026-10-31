# PyInstaller : deux exécutables dans le même dossier dist\TableDeMontage\
#   TableDeMontage.exe   l'interface (sans console)
#   lanceur.exe          exécute les scripts de montage (console, cachée par l'interface) ; il embarque Python, numpy,
#                        mido et les modules de tablemontage/modules_scripts.py, dont les scripts peuvent avoir besoin
# Construire avec build.ps1.

interface = Analysis(["TableDeMontage.py"], pathex=["."], datas=[("icones", "icones"), ("modeles", "modeles")], excludes=["tkinter"])
lanceur = Analysis(["lanceur.py"], pathex=["."], hiddenimports=["mido", "mido.backends"],
                   excludes=["tkinter", "PySide6", "shiboken6"])

exe_interface = EXE(PYZ(interface.pure), interface.scripts, [], exclude_binaries=True, name="TableDeMontage",
                    console=False, upx=False, icon="icones/application.ico")
exe_lanceur = EXE(PYZ(lanceur.pure), lanceur.scripts, [], exclude_binaries=True, name="lanceur",
                  console=True, upx=False, icon="icones/application.ico")

COLLECT(exe_interface, interface.binaries, interface.datas,
        exe_lanceur, lanceur.binaries, lanceur.datas,
        name="TableDeMontage", upx=False)
