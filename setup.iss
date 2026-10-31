; Installateur Inno Setup 6 de la Table de montage (construit par build.ps1 à partir de dist\TableDeMontage).
#define Nom "Table de montage"
; la version vient de tablemontage\__init__.py (build.ps1 la passe avec /DVersion=…)
#ifndef Version
  #define Version "1.0.0"
#endif

[Setup]
AppName={#Nom}
AppVersion={#Version}
AppPublisher=zebruo
DefaultDirName={autopf}\TableDeMontage
DefaultGroupName={#Nom}
OutputDir=dist
OutputBaseFilename=TableDeMontage-setup-{#Version}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\TableDeMontage.exe
SetupIconFile=icones\application.ico

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "bureau"; Description: "Créer un raccourci sur le Bureau"; Flags: unchecked

[Files]
Source: "dist\TableDeMontage\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#Nom}"; Filename: "{app}\TableDeMontage.exe"
Name: "{group}\Désinstaller {#Nom}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#Nom}"; Filename: "{app}\TableDeMontage.exe"; Tasks: bureau

[Run]
Filename: "{app}\TableDeMontage.exe"; Description: "Lancer {#Nom}"; Flags: nowait postinstall skipifsilent
