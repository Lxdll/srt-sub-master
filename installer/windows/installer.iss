#define MyAppName "SRT Sub 本机识别器"
#define MyAppVersion "0.1.0"
#ifndef ProjectDir
  #define ProjectDir "..\.."
#endif
#ifndef ArtifactDir
  #define ArtifactDir "..\artifacts"
#endif

[Setup]
AppId={{E84B0EAF-9D1C-4B62-9E3E-D7D43D7F2C39}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\SRTSubAgent
DisableProgramGroupPage=yes
OutputDir={#ArtifactDir}
OutputBaseFilename=srt-sub-agent-windows-x64
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Files]
Source: "{#ProjectDir}\dist\SRTSubAgent.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\SRTSubAgent.exe"
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\SRTSubAgent.exe"

[Run]
Filename: "{app}\SRTSubAgent.exe"; Description: "启动本机识别器"; Flags: nowait postinstall skipifsilent
