; SPDX-License-Identifier: GPL-3.0-or-later
; Copyright (C) 2026 Gabriel Marti
; Instalador de AgySwitcher (Inno Setup 6).
; Lo compila packaging/build.ps1, que define AppVersion, FileVersion, SourceDir, RepoRoot y
; OutputDir con /D. Instala solo para el usuario actual (sin administrador), añade la
; carpeta al PATH del usuario y crea un desinstalador. Los datos del usuario
; (%USERPROFILE%\.agyswitcher) no se borran al desinstalar.
; También localiza agy.exe y guarda su ruta en la variable de usuario AGYSWITCHER_AGY, para
; que AgySwitcher no tenga que buscarlo (y nunca use un agy de la carpeta del proyecto).
; Una AGYSWITCHER_AGY puesta por el usuario no se toca; la del instalador se borra al
; desinstalar.

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

const
  AgyEnvName = 'AGYSWITCHER_AGY';
  MarkerKey = 'Software\AgySwitcher';
  MarkerValue = 'InstallerAgyPath';

var
  AgyStatusMessage: string;

{ Carpeta absoluta ('C:\...' o '\\servidor\...'): las relativas se ignoran como en AgySwitcher. }
function IsAbsoluteDir(Dir: string): Boolean;
begin
  Result := ((Length(Dir) >= 3) and (Dir[2] = ':') and ((Dir[3] = '\') or (Dir[3] = '/')))
    or ((Length(Dir) >= 2) and (Copy(Dir, 1, 2) = '\\'));
end;

{ Primer agy.exe en las carpetas absolutas de PathValue (no admite agy.cmd ni agy.bat). }
function FindAgyInPath(PathValue: string): string;
var
  Entry, Candidate: string;
  P: Integer;
begin
  Result := '';
  PathValue := PathValue + ';';
  while Length(PathValue) > 0 do
  begin
    P := Pos(';', PathValue);
    Entry := Trim(Copy(PathValue, 1, P - 1));
    Delete(PathValue, 1, P);
    StringChangeEx(Entry, '"', '', True);
    if (Entry <> '') and IsAbsoluteDir(Entry) then
    begin
      Candidate := AddBackslash(Entry) + 'agy.exe';
      if FileExists(Candidate) then
      begin
        Result := Candidate;
        exit;
      end;
    end;
  end;
end;

{ Ruta de instalación oficial de agy y, si no está, el PATH. Cadena vacía si no se encuentra. }
function FindAgy(): string;
begin
  Result := ExpandConstant('{localappdata}\agy\bin\agy.exe');
  if FileExists(Result) then
    exit;
  Result := FindAgyInPath(GetEnv('PATH'));
end;

function GetInstallerMarker(): string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, MarkerKey, MarkerValue, Result) then
    Result := '';
end;

{ Fija AGYSWITCHER_AGY si no existe o la puso este instalador; respeta la del usuario. }
procedure ConfigureAgyVariable();
var
  Current, Marker, Found: string;
  HasCurrent, Owned: Boolean;
begin
  HasCurrent := RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', AgyEnvName, Current)
    and (Current <> '');
  Marker := GetInstallerMarker();
  Owned := (not HasCurrent) or ((Marker <> '') and (CompareText(Current, Marker) = 0));
  if not Owned then
  begin
    AgyStatusMessage := 'Se mantiene tu variable ' + AgyEnvName + ' (' + Current + ').';
    exit;
  end;

  Found := FindAgy();
  if Found <> '' then
  begin
    RegWriteStringValue(HKEY_CURRENT_USER, 'Environment', AgyEnvName, Found);
    RegWriteStringValue(HKEY_CURRENT_USER, MarkerKey, MarkerValue, Found);
    AgyStatusMessage := 'Antigravity CLI encontrado en ' + Found + '.';
  end
  else
  begin
    if HasCurrent then
      RegDeleteValue(HKEY_CURRENT_USER, 'Environment', AgyEnvName);
    RegDeleteValue(HKEY_CURRENT_USER, MarkerKey, MarkerValue);
    AgyStatusMessage := 'No se encontró Antigravity CLI (agy.exe). Instálalo y AgySwitcher '
      + 'lo buscará en el PATH; también puedes reinstalar AgySwitcher después.';
  end;
end;

{ Borra AGYSWITCHER_AGY solo si sigue teniendo el valor que puso el instalador. }
procedure RemoveAgyVariable();
var
  Current, Marker: string;
begin
  Marker := GetInstallerMarker();
  if (Marker <> '')
    and RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', AgyEnvName, Current)
    and (CompareText(Current, Marker) = 0) then
    RegDeleteValue(HKEY_CURRENT_USER, 'Environment', AgyEnvName);
  RegDeleteValue(HKEY_CURRENT_USER, MarkerKey, MarkerValue);
  RegDeleteKeyIfEmpty(HKEY_CURRENT_USER, MarkerKey);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    ConfigureAgyVariable();
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and (AgyStatusMessage <> '') then
  begin
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10
      + AgyStatusMessage;
    WizardForm.AdjustLabelHeight(WizardForm.FinishedLabel);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RemoveFromPath(ExpandConstant('{app}'));
    RemoveAgyVariable();
  end;
end;
