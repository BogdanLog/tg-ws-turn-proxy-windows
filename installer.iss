[Setup]
AppId={{5D2A7B1C-9E3F-4A6D-B8C2-7F1E9A0D4B3E}
AppName=tg-ws-turn-proxy
AppVersion=1.0.0
AppPublisher=BogdanLog Inc.
DefaultDirName={autopf}\tg-ws-turn-proxy
DefaultGroupName=tg-ws-turn-proxy
UninstallDisplayIcon={app}\tg-ws-turn-proxy.exe
SetupIconFile=gui\assets\icon.ico
OutputDir=dist
OutputBaseFilename=tg-ws-turn-proxy-setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\tg-ws-turn-proxy.dist\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\tg-ws-turn-proxy"; Filename: "{app}\tg-ws-turn-proxy.exe"
Name: "{autodesktop}\tg-ws-turn-proxy"; Filename: "{app}\tg-ws-turn-proxy.exe"; Tasks: desktopicon