#ifndef AppVersion
  #define AppVersion "0.1.2"
#endif
#ifndef BuildDir
  #define BuildDir SourcePath + "..\build\windows\main.dist"
#endif

[Setup]
AppId={{C454D975-D23F-4E76-AC76-B054505C4768}
AppName=Ounce-bt
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Ounce-bt
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=Ounce-bt-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\Ounce-bt.exe
CloseApplications=yes

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Excludes: "config,config.json,pro_controller.json,macros,rtl8761bu_fw.bin,rtl8761bu_config.bin"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{code:FirmwareSource}"; DestDir: "{app}"; DestName: "rtl8761bu_fw.bin"; Flags: external ignoreversion skipifsourcedoesntexist uninsneveruninstall; Check: HasFirmware
Source: "{code:ConfigBinarySource}"; DestDir: "{app}"; DestName: "rtl8761bu_config.bin"; Flags: external ignoreversion skipifsourcedoesntexist uninsneveruninstall; Check: HasConfigBinary

[Icons]
Name: "{autoprograms}\Ounce-bt"; Filename: "{app}\Ounce-bt.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\Ounce-bt.exe"; WorkingDir: "{app}"; Description: "Launch Ounce-bt"; Flags: nowait postinstall skipifsilent

[Code]
var
  FoldersPage: TInputDirWizardPage;
  FirmwarePage: TInputFileWizardPage;

function ConfigFile: String;
begin
  Result := ExpandConstant('{app}\config\config.json');
end;

function JsonString(Value: String): String;
var
  I, C: Integer;
begin
  Result := '"';
  for I := 1 to Length(Value) do begin
    C := Ord(Value[I]);
    // ASCII JSON also handles Unicode paths without depending on the file encoding.
    if (C < 32) or (C > 126) or (Value[I] = '"') or (Value[I] = '\') then
      Result := Result + '\u' + Format('%.4x', [C])
    else
      Result := Result + Value[I];
  end;
  Result := Result + '"';
end;

procedure InitializeWizard;
begin
  FoldersPage := CreateInputDirPage(wpSelectDir, 'Presets and macros',
    'Optionally change where Ounce-bt stores your preset and macro files.',
    'Existing application settings are preserved when upgrading.', False, '');
  FoldersPage.Add('Presets folder:');
  FoldersPage.Add('Macros folder:');
  FoldersPage.Values[0] := ExpandConstant('{userdocs}\Ounce-bt\presets');
  FoldersPage.Values[1] := ExpandConstant('{userdocs}\Ounce-bt\macros');

  FirmwarePage := CreateInputFilePage(FoldersPage.ID, 'Bluetooth files',
    'Optionally supply the required Realtek RTL8761BU firmware and config binaries.',
    'Skip, if you want to add them later.');
  FirmwarePage.Add('rtl8761bu_fw.bin:', 'Binary files (*.bin)|*.bin|All files (*.*)|*.*', '.bin');
  FirmwarePage.Add('rtl8761bu_config.bin:', 'Binary files (*.bin)|*.bin|All files (*.*)|*.*', '.bin');
end;

function NonemptyFile(Path: String): Boolean;
var
  FileInfo: TFindRec;
begin
  Result := FileExists(Path) and FindFirst(Path, FileInfo);
  if Result then begin
    Result := (FileInfo.SizeHigh <> 0) or (FileInfo.SizeLow <> 0);
    FindClose(FileInfo);
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = FoldersPage.ID) and FileExists(ConfigFile);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = FoldersPage.ID then begin
    Result := (Trim(FoldersPage.Values[0]) <> '') and (Trim(FoldersPage.Values[1]) <> '');
    if not Result then MsgBox('Choose both a presets folder and a macros folder.', mbError, MB_OK);
  end;
  if CurPageID = FirmwarePage.ID then begin
    if FirmwarePage.Values[0] <> '' then
      Result := NonemptyFile(FirmwarePage.Values[0])
    else
      Result := NonemptyFile(ExpandConstant('{app}\rtl8761bu_fw.bin'));
    if not Result then begin
      MsgBox('Select a nonempty rtl8761bu_fw.bin file.', mbError, MB_OK);
      Exit;
    end;
    if FirmwarePage.Values[1] <> '' then
      Result := NonemptyFile(FirmwarePage.Values[1])
    else
      Result := NonemptyFile(ExpandConstant('{app}\rtl8761bu_config.bin'));
    if not Result then MsgBox('Select a nonempty rtl8761bu_config.bin file.', mbError, MB_OK);
  end;
end;

function FirmwareSource(Param: String): String;
begin
  Result := FirmwarePage.Values[0];
end;

function HasFirmware: Boolean;
begin
  Result := FirmwarePage.Values[0] <> '';
end;

function ConfigBinarySource(Param: String): String;
begin
  Result := FirmwarePage.Values[1];
end;

function HasConfigBinary: Boolean;
begin
  Result := FirmwarePage.Values[1] <> '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigDir, DeviceFile, Settings: String;
begin
  if CurStep <> ssPostInstall then Exit;
  ConfigDir := ExpandConstant('{app}\config');
  if not ForceDirectories(ConfigDir) then
    RaiseException('Could not create the application config folder.');
  DeviceFile := ConfigDir + '\pro_controller.json';
  if not FileExists(DeviceFile) then
    if not SaveStringToFile(DeviceFile,
      '{"name":"Pro Controller","class_of_device":9480,"keystore":"JsonKeyStore"}', False) then
      RaiseException('Could not write the Bluetooth device configuration.');

  if FileExists(ConfigFile) then Exit;
  if not ForceDirectories(FoldersPage.Values[0]) then
    RaiseException('Could not create the presets folder.');
  if not ForceDirectories(FoldersPage.Values[1]) then
    RaiseException('Could not create the macros folder.');
  // All other settings use the defaults in lib/config.py, including a fresh BT identity.
  Settings := '{' + #13#10 +
    '  "presets_dir": ' + JsonString(FoldersPage.Values[0]) + ',' + #13#10 +
    '  "macros_dir": ' + JsonString(FoldersPage.Values[1]) + ',' + #13#10 +
    '  "device_config": "pro_controller.json"' + #13#10 + '}';
  if not SaveStringToFile(ConfigFile, Settings, False) then
    RaiseException('Could not write config.json.');
end;
