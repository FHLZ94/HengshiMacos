#define MyAppName "衡势"
#define MyAppVersion "1.3.2"
#define MyAppPublisher "范光旭"
#define MyAppExeName "衡势-1.3.2.exe"
#define PreviousAppExeName "衡势-1.3.1-UI2.exe"

[Setup]
AppId={{9D6EB670-3356-4335-8CD4-B4274C4DE8B6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Hengshi-UI2
DefaultGroupName={#MyAppName}
OutputDir=installer
OutputBaseFilename=衡势-1.3.2-Windows-安装包
SetupIconFile=nexus.ico
WizardImageFile=assets\wizard.bmp
WizardSmallImageFile=assets\wizard-small.bmp
WizardStyle=modern
WizardSizePercent=110
DefaultDialogFontName=Microsoft YaHei UI
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
CloseApplicationsFilter=衡势*.exe
RestartApplications=no
DisableWelcomePage=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "assets\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
Source: "dist\release\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
Type: files; Name: "{app}\{#PreviousAppExeName}"
Type: files; Name: "{app}\衡势.exe"
Type: files; Name: "{userprograms}\衡势 1.3.1-UI2\衡势 1.3.1-UI2.lnk"
Type: files; Name: "{userprograms}\衡势 1.3.1-UI2\卸载衡势 1.3.1-UI2.lnk"
Type: dirifempty; Name: "{userprograms}\衡势 1.3.1-UI2"
Type: files; Name: "{autodesktop}\衡势 1.3.1-UI2.lnk"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动衡势"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /IM ""{#MyAppExeName}"""; Flags: runhidden waituntilterminated; RunOnceId: "StopHengshi"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /IM ""{#PreviousAppExeName}"""; Flags: runhidden waituntilterminated; RunOnceId: "StopHengshiPrevious"

[UninstallDelete]
Type: filesAndOrDirs; Name: "{app}"

[Code]
var
  PurgeSharedData: Boolean;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  PurgeSharedData := False;
  if not UninstallSilent then
    PurgeSharedData := MsgBox(
      '是否同时删除本机投研数据？' + #13#10 + #13#10 +
      '包含持仓、观察列表、缓存和设置。' + #13#10 +
      '选择“否”仅卸载程序并保留数据；选择“是”会永久删除这些数据。',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and PurgeSharedData then
    DelTree(ExpandConstant('{userappdata}\AIMarketIntelligence'), True, True, True);
end;

