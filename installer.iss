#define MyAppName "衡势"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "范光旭"
#define MyAppExeName "衡势.exe"

[Setup]
AppId={{B32F0E6A-24A2-4C1C-9D20-92C82E1F03C8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion} 正式版
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\衡势
DefaultGroupName={#MyAppName}
OutputDir=installer
OutputBaseFilename=衡势-安装包
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
RestartApplications=no
DisableWelcomePage=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "assets\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
Source: "dist\release\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动衡势"; Flags: postinstall nowait skipifsilent
