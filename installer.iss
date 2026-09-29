
[Setup]
AppName=桌面日历
AppVersion=3.0.0
AppPublisher=YourName
AppCopyright=Copyright (C) 2026 YourName
; 64位用 {autopf}，32位程序改为 {pf}
DefaultDirName={autopf}\LunarCalendar
DefaultGroupName=桌面日历
OutputDir=.\installer_output
OutputBaseFilename=LunarCalendar_Setup
Compression=lzma2
SolidCompression=yes
; 使用相对路径，不要写E盘绝对路径
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\LunarCalendar.exe

; 附加配置
PrivilegesRequired=admin
DirExistsWarning=no
UsePreviousAppDir=yes
CreateAppDir=yes
WizardImageFile=
WizardSmallImageFile=

[Files]
Source: "dist\LunarCalendar\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\桌面日历"; Filename: "{app}\LunarCalendar.exe"
Name: "{commondesktop}\桌面日历"; Filename: "{app}\LunarCalendar.exe"; Flags: createonlyiffileexists

[Run]
Filename:"{app}\LunarCalendar.exe"; Description:"启动桌面日历"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; 卸载尝试关闭程序，避免文件占用
Filename: taskkill; Parameters: "/f /im LunarCalendar.exe"; Flags: runhidden

[UninstallDelete]
; 如果你的程序会在app目录生成缓存配置，可以开启下面，谨慎！会删除全部
; Type: filesandordirs; Name: "{app}"
