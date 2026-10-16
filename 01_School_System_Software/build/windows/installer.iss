; Inno Setup script - builds SchoolSystemSetup.exe (works on Windows 7 SP1 to Windows 11, 32-bit and 64-bit).
; The program folder comes from PyInstaller (dist\SchoolSystem). Customers do NOT need Python.
#define AppName "School Result and Accounting Management System"
#define AppVer "2.0"

[Setup]
AppId={{7B1E6D0A-5C3E-4C57-9D5A-0E2E7F3B2A10}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=OKV Technology Consults
AppPublisherURL=https://www.okvtechnology.com
AppSupportURL=https://www.okvtechnology.com
DefaultDirName={autopf}\SchoolSystem
DefaultGroupName=School System
OutputDir=..\..\output
OutputBaseFilename=SchoolSystemSetup
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\SchoolSystem.exe
LicenseFile=..\..\assets\EULA.txt
InfoAfterFile=..\..\assets\INSTRUCTIONS.txt
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
DisableProgramGroupPage=yes
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce
Name: "autostart"; Description: "Start the system automatically when this computer starts (recommended)"; Flags: checkedonce

[Dirs]
Name: "{commonappdata}\SchoolSystem"; Permissions: users-modify

[Files]
Source: "..\..\dist\SchoolSystem\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs
Source: "..\..\assets\INSTRUCTIONS.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\School System"; Filename: "{app}\SchoolSystem.exe"
Name: "{group}\Stop School System"; Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM SchoolSystem.exe"; Flags: runminimized
Name: "{group}\Instructions"; Filename: "{app}\INSTRUCTIONS.txt"
Name: "{commondesktop}\School System"; Filename: "{app}\SchoolSystem.exe"; Tasks: desktopicon

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""School System"" dir=in action=allow program=""{app}\SchoolSystem.exe"" enable=yes profile=any"; Flags: runhidden
Filename: "{sys}\schtasks.exe"; Parameters: "/Create /TN ""School System"" /TR ""\""{app}\SchoolSystem.exe\"" --no-browser"" /SC ONSTART /RU SYSTEM /RL HIGHEST /F"; Flags: runhidden; Tasks: autostart
Filename: "{app}\SchoolSystem.exe"; Description: "Start School System now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM SchoolSystem.exe"; Flags: runhidden
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""School System"" /F"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""School System"""; Flags: runhidden
