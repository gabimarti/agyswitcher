; SPDX-License-Identifier: GPL-3.0-or-later
; Copyright (C) 2026 Gabriel Marti
; Instalador de AgySwitcher (Inno Setup 6).
; Lo compila packaging/build.ps1, que define AppVersion, FileVersion, SourceDir, RepoRoot y
; OutputDir con /D. Instala solo para el usuario actual (sin administrador), añade la
; carpeta al PATH del usuario y crea un desinstalador. Los datos del usuario
; (%USERPROFILE%\.agyswitcher) no se borran al desinstalar.

#ifndef AppVersion
  #error "Compila con packaging/build.ps1 (falta /DAppVersion)"
#endif

[Setup]
AppId={{6F0B7C2E-3D4A-4E8B-9C51-2A7D9E4F1B36}
AppName=AgySwitcher
AppVersion={#AppVersion}
AppVerName=AgySwitcher {#AppVersion}
AppPublisher=Gabriel Marti
AppPublisherURL=https://gabimarti.github.io/
AppSupportURL=https://github.com/gabimarti/agyswitcher
AppComments=Switch accounts. Keep coding.
VersionInfoVersion={#FileVersion}
VersionInfoProductName=AgySwitcher
VersionInfoDescription=Instalador de AgySwitcher
DefaultDirName={autopf}\AgySwitcher
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
LicenseFile={#RepoRoot}\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=AgySwitcher-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#RepoRoot}\packaging\agyswitcher.ico
WizardImageFile={#RepoRoot}\packaging\wizard-164.bmp,{#RepoRoot}\packaging\wizard-328.bmp
WizardSmallImageFile={#RepoRoot}\packaging\wizard-small-55.bmp,{#RepoRoot}\packaging\wizard-small-110.bmp
UninstallDisplayName=AgySwitcher
UninstallDisplayIcon={app}\agyswitcher.exe

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Messages]
spanish.FinishedLabel=Switch accounts. Keep coding.%n%nAgySwitcher se ha instalado en el equipo.%n%nAbre una consola NUEVA (PowerShell o Windows Terminal) y ejecuta:%n%n    agyswitcher --help%n%nEl manual está en la carpeta docs de la instalación.

[Files]
; SourceDir ya incluye README.md, LICENSE, CHANGELOG.md y docs\ (los copia build.ps1).
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\AgySwitcher\Manual de AgySwitcher"; Filename: "{app}\docs\manual\index.md"
Name: "{autoprograms}\AgySwitcher\Carpeta de AgySwitcher"; Filename: "{app}"
Name: "{autoprograms}\AgySwitcher\Desinstalar AgySwitcher"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

[Code]
function NeedsAddPath(Dir: string): Boolean;
var
  Paths: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') = 0;
end;

procedure RemoveFromPath(Dir: string);
var
  Paths: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths) then
    exit;
  Paths := ';' + Paths + ';';
  P := Pos(';' + Uppercase(Dir) + ';', Uppercase(Paths));
  if P = 0 then
    exit;
  Delete(Paths, P, Length(Dir) + 1);
  Paths := Copy(Paths, 2, Length(Paths) - 2);
  RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromPath(ExpandConstant('{app}'));
end;
