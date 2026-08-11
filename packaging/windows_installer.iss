; Inno Setup script for the MTGA Tracker Windows installer.
;
; Built by scripts/build_windows_app.ps1 (or CI) AFTER PyInstaller has produced
; "dist\MTGA Tracker\". Compile with:
;   ISCC /DMyAppVersion=x.y.z packaging\windows_installer.iss
;
; Install-location model: per-user by default (%LOCALAPPDATA%\Programs\MTGA
; Tracker, no admin prompt), with an "Install for all users" choice that goes
; to Program Files under UAC. The app never writes to its install directory —
; all data lives in %LOCALAPPDATA%\MTGA Tracker — so Program Files' read-only
; permissions are safe.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "MTGA Tracker"
#define MyAppExeName "MTGA Tracker.exe"

[Setup]
; NEVER change this AppId: it is what makes a newer setup.exe upgrade the
; existing install in place instead of creating a second Apps & Features entry.
AppId={{1F54E322-28D9-4929-8292-F5AAAA12CB5F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Travis Patton
AppPublisherURL=https://github.com/pattont/MTGA-Tapps
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=MTGA-Tracker-{#MyAppVersion}-setup
SetupIconFile=assets\MTGATracker.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
; Upgrades: ask a running tracker to close instead of failing on locked files.
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; Flags: unchecked

[Files]
Source: "..\dist\MTGA Tracker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: postinstall nowait skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { The tracked-game database and settings live outside the install dir.
    Default answer is No: nobody should lose their game history to a
    reflexive uninstall (e.g. uninstalling just to reinstall fresh). }
  if CurUninstallStep = usUninstall then
  begin
    if MsgBox('Also delete your tracked game history and settings?'#13#10#13#10 +
              'Choose No to keep them for a future reinstall.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      DelTree(ExpandConstant('{localappdata}\MTGA Tracker'), True, True, True);
    end;
  end;
end;
