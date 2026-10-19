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
;
; In-app updates (docs/plans/AUTO_UPDATE.md, section 5.1): the running
; tracker downloads a newer setup.exe, verifies it, starts it detached with
;   /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /NOCANCEL
;   /CLOSEAPPLICATIONS /NORESTARTAPPLICATIONS /LOG="<data>\updates\install-<new>.log"
;   /CURRENTUSER or /ALLUSERS (matching the existing install; never /DIR)
;   /WAITPID=<its pid> /RELAUNCH=1 /UPDATEDFROM=<old version>
;   /RELAUNCHEXE="<its own exe path>"
; and exits. The [Code] below waits for that PID before touching any file,
; then the silent-only [Run] entry relaunches the new version. Older setups
; ignore these switches, so only the version being INSTALLED must carry this
; script; the version doing the updating just passes them.

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
; For in-app updates the tracker has already exited (see /WAITPID below), so
; Restart Manager is only the safety net for stragglers such as a leftover
; overlay or a Deck Finder console. The filter adds *.pyd so it also sees the
; Python extension modules in _internal (the default is *.exe,*.dll,*.chm).
CloseApplications=yes
RestartApplications=no
CloseApplicationsFilter=*.exe,*.dll,*.pyd,*.chm

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; Flags: unchecked

[InstallDelete]
; Upgrades: Inno only adds and replaces files, so anything an earlier version
; shipped and this one no longer does would stay behind. The PyInstaller
; runtime folder is rebuilt from scratch (stale modules and DLLs in it are
; never wanted), and the Deck Finder's former companion executable goes —
; it has been a mode of MTGA Tracker.exe since 0.6.3. Nothing here touches
; user data, which lives in %LOCALAPPDATA%\MTGA Tracker.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\MTGA Deck Downloader.exe"

[Files]
Source: "..\dist\MTGA Tracker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: postinstall nowait skipifsilent
; In-app update: relaunch after a successful SILENT install, only when the
; tracker asked for it with /RELAUNCH=1. runasoriginaluser keeps the tracker
; un-elevated even when an all-users update elevated Setup. Interactive
; installs keep the checkbox entry above (skipifnotsilent skips this one).
Filename: "{app}\{#MyAppExeName}"; Parameters: "--after-update --updated-from ""{param:UPDATEDFROM|unknown}"""; Flags: nowait runasoriginaluser skipifnotsilent; Check: RelaunchRequested

[Code]
{ ---- In-app update hand-off ------------------------------------------------
  Names are prefixed so they can never collide with Inno's built-in
  constants. THandle, DWORD and BOOL are built-in Pascal Script types for
  Windows API calls (ishelp topic_scriptdll). }
const
  TappsSynchronize = $00100000;   { SYNCHRONIZE access right }
  TappsWaitObject0 = 0;           { WAIT_OBJECT_0 }
  TappsWaitPidTimeoutMs = 60000;

function TappsOpenProcess(dwDesiredAccess: DWORD; bInheritHandle: BOOL;
  dwProcessId: DWORD): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function TappsWaitForSingleObject(hHandle: THandle; dwMilliseconds: DWORD): DWORD;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function TappsCloseHandle(hObject: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';

var
  InstallStarted: Boolean;
  InstallSucceeded: Boolean;

{ /RELAUNCH=1: the tracker started this setup and wants to be restarted. }
function RelaunchRequested: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

function InitializeSetup: Boolean;
var
  Pid: Integer;
  ProcessHandle: THandle;
begin
  Result := True;
  { The tracker passes its own PID in /WAITPID and exits. Wait until it is
    really gone (every DLL and .pyd in _internal unmapped) BEFORE
    the InstallDelete section removes _internal: that deletion is not rolled back if
    a locked file later aborts the install. A handle of 0 means the process
    has already exited. Timing out aborts Setup (exit code 1) with nothing
    touched; the still-running tracker reports the failure itself. }
  Pid := StrToIntDef(ExpandConstant('{param:WAITPID|0}'), 0);
  if Pid > 0 then
  begin
    ProcessHandle := TappsOpenProcess(TappsSynchronize, False, Pid);
    if ProcessHandle <> 0 then
    begin
      Log(Format('Waiting up to %d ms for tracker PID %d to exit.', [TappsWaitPidTimeoutMs, Pid]));
      if TappsWaitForSingleObject(ProcessHandle, TappsWaitPidTimeoutMs) <> TappsWaitObject0 then
      begin
        Log(Format('Tracker PID %d is still running; aborting the update.', [Pid]));
        Result := False;
      end
      else
        Log(Format('Tracker PID %d has exited.', [Pid]));
      TappsCloseHandle(ProcessHandle);
    end
    else
      Log(Format('Tracker PID %d is not running (or cannot be opened).', [Pid]));
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    InstallStarted := True;
  if CurStep = ssPostInstall then
  begin
    InstallSucceeded := True;
    Log('In-app update: installation finished.');
  end;
end;

procedure DeinitializeSetup;
var
  RelaunchExe: String;
  ResultCode: Integer;
begin
  { The install began but did not finish: bring the tracker back (with
    --update-failed, so it reads install-<new>.log and tells the user)
    instead of leaving the user without it. The app constant may be
    undefined here, so the tracker passes its own path in /RELAUNCHEXE. A Setup aborted before
    ssInstall (e.g. the PID wait above) changes nothing, so it relaunches
    nothing. Whether ExecAsOriginalUser works this late is unverified; a
    failure is logged and otherwise harmless. }
  if RelaunchRequested and InstallStarted and (not InstallSucceeded) then
  begin
    RelaunchExe := ExpandConstant('{param:RELAUNCHEXE|}');
    if (RelaunchExe <> '') and FileExists(RelaunchExe) then
    begin
      try
        if not ExecAsOriginalUser(RelaunchExe, '--update-failed', '', SW_SHOWNORMAL,
          ewNoWait, ResultCode) then
          Log(Format('Could not relaunch %s after a failed update (code %d).', [RelaunchExe, ResultCode]));
      except
        Log('Relaunch after a failed update raised: ' + GetExceptionMessage);
      end;
    end
    else
      Log('Update failed and there is no tracker executable to relaunch.');
  end;
end;

{ ---- Uninstall ---------------------------------------------------------- }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { The tracked-game database and settings live outside the install dir.
    Default answer is No: nobody should lose their game history to a
    reflexive uninstall (e.g. uninstalling just to reinstall fresh). }
  if CurUninstallStep = usUninstall then
  begin
    { Start with Windows is app-managed and belongs to this installation. }
    RegDeleteValue(HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Run', 'Tapps Tracker');
    if MsgBox('Also delete your tracked game history and settings?'#13#10#13#10 +
              'Choose No to keep them for a future reinstall.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      DelTree(ExpandConstant('{localappdata}\MTGA Tracker'), True, True, True);
    end;
  end;
end;
