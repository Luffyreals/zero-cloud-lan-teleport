; Script Inno Setup cho bộ cài Windows của Teleport (bản GUI). Lệnh build (chạy từ gốc repo, sau khi đã
; build dist/teleport-gui bằng packaging/pyinstaller/teleport-gui.spec) ở mục "Bộ cài Windows (Inno
; Setup)" của docs/CONTRIBUTING.md; workflow: .github/workflows/build-gui.yml.
;
; Ghim Inno Setup 6.7.3 (bản Unicode). Nâng bản thì đọc lại giấy phép, thay
; licenses/InnoSetup-<bản>-license.txt và languages/Vietnamese.isl (đúng tag mới của jrsoftware/issrc),
; sửa INNO_VERSION, INNO_URL, INNO_SHA256 trong .github/workflows/build-gui.yml; giấy phép đổi thì rà
; lại docs/ke_hoach.md mục 1 (Giấy phép) và 4.1.
;
; Ba tham số bắt buộc từ dòng lệnh ISCC (không viết cứng phiên bản ở đây; nguồn duy nhất là
; teleport.__version__):
;   /DAppVersion=<teleport.__version__>      ví dụ 0.1.0a0, giữ nguyên chuỗi gốc
;   /DAppVersionNumeric=<a.b.c.d>            Version(v).release đệm đủ 4 số, ví dụ 0.1.0.0
;   /DSourceDir=<đường dẫn tuyệt đối tới dist\teleport-gui>
;
; Giấy phép (docs/ke_hoach.md mục 1, Giấy phép): stub cài đặt và unins000.exe của Inno Setup theo giấy
; phép Inno Setup (kiểu zlib), là chương trình riêng gộp cùng Teleport, không liên kết với mã Teleport;
; văn bản giấy phép được cài vào {app}\licenses\. Thư mục dist\teleport-gui giữ nguyên bố cục --onedir
; (DLL Qt/PySide6 và zeroconf là file riêng người dùng thay được), kèm LICENSE, THIRD-PARTY-NOTICES.txt,
; SOURCE.txt; DOC-TRUOC.txt chỉ dành cho bản zip nên không cài.
;
; Hai chế độ cài (docs/architecture.md mục 4, "Bộ cài Windows"):
; - Mặc định: cho cả máy, cần quyền quản trị, vào {autopf}\Teleport, tạo hai rule tường lửa chỉ ở hồ sơ
;   Private.
; - /CURRENTUSER: chỉ cho người đang đăng nhập, không UAC, vào %LOCALAPPDATA%\Programs\Teleport, không
;   tạo rule (Windows tự hỏi khi app mở cổng lần đầu; trang kết thúc nhắc một câu).

#ifndef AppVersion
  #error Thiếu /DAppVersion=<teleport.__version__>
#endif
#ifndef AppVersionNumeric
  #error Thiếu /DAppVersionNumeric=<a.b.c.d>
#endif
#ifndef SourceDir
  #error Thiếu /DSourceDir=<đường dẫn tuyệt đối tới dist\teleport-gui>
#endif

[Setup]
; AppId cố định: KHÔNG BAO GIỜ ĐỔI. Bộ cài bản sau tìm bản đã cài (cài đè, gỡ, khóa
; ...\Uninstall\{AppId}_is1) theo đúng giá trị này. Dấu "{{" là cách viết "{" trong Inno.
AppId={{A82B1EF5-F24A-4DA0-841B-09F4E2F6D4C1}
; Tên hiển thị là “ZCL Teleport” (tên ngắn của sản phẩm); thư mục cài, tên exe, giá trị Run, tên rule
; tường lửa và thư mục dữ liệu vẫn là “Teleport” để bản cũ cài đè và gỡ đúng.
AppName=ZCL Teleport
AppVersion={#AppVersion}
AppVerName=ZCL Teleport {#AppVersion}
AppPublisher=Nha-Cong-Dong
AppPublisherURL=https://github.com/Nha-Cong-Dong/zero-cloud-lan-teleport
AppSupportURL=https://github.com/Nha-Cong-Dong/zero-cloud-lan-teleport
; Chủ bản quyền khớp dòng "Bản quyền" của README.md và authors trong pyproject.toml.
AppCopyright=Copyright (C) 2026 Nguyễn Hoàng Tùng. GPL-3.0-or-later
VersionInfoVersion={#AppVersionNumeric}
VersionInfoProductName=Zero-Cloud LAN Teleport
VersionInfoProductTextVersion={#AppVersion}
VersionInfoDescription=Bộ cài ZCL Teleport

; Cài cho cả máy là mặc định; /CURRENTUSER (hay /ALLUSERS) chỉ đổi được từ dòng lệnh, không có hộp
; thoại chọn chế độ.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
; Gỡ bản admin dọn dữ liệu {userappdata}\Teleport và giá trị Run trong HKCU của tài khoản đang chạy bộ
; gỡ (có chủ đích, docs/architecture.md mục 4), nên tắt cảnh báo lúc biên dịch về vùng của người dùng
; trong chế độ admin.
UsedUserAreasWarning=no
DefaultDirName={autopf}\Teleport
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

; Restart Manager đóng Teleport khi cài đè (dự phòng khi kiểm tiến trình bằng WMI ở [Code] lỗi); không
; mở lại app sau khi cài, không bao giờ đòi khởi động lại máy.
CloseApplications=force
RestartApplications=no

LicenseFile={#SourceDir}\LICENSE
SetupIconFile=..\pyinstaller\teleport.ico
UninstallDisplayIcon={app}\Teleport.exe
UninstallDisplayName=ZCL Teleport
WizardStyle=modern
ShowLanguageDialog=no

Compression=lzma2/max
SolidCompression=yes
OutputBaseFilename=teleport-setup-{#AppVersion}-x64

[Languages]
Name: "vi"; MessagesFile: "languages\Vietnamese.isl"
; TODO E1: app đã có English (src/teleport/ui/i18n/teleport_en.qm, mvp F11) nhưng bộ cài vẫn chỉ
; tiếng Việt; dịch bộ cài để sau buổi demo (đóng băng, ke_hoach mục 5.5): bỏ comment dòng "en" dưới
; đây và khối "en." ở [CustomMessages]. Giữ ShowLanguageDialog=no thì Inno tự chọn theo ngôn ngữ
; giao diện Windows.
; Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
vi.AppRunning=Teleport đang chạy. Hãy thoát Teleport (chuột phải biểu tượng ở khay → Thoát) rồi bấm Thử lại.
vi.AppRunningAborted=Teleport vẫn đang chạy. Hãy thoát Teleport (chuột phải biểu tượng ở khay → Thoát) rồi chạy lại bộ cài.
vi.AppRunningOtherSession=Teleport có thể đang chạy ở một tài khoản khác trên máy này.
vi.FirewallCurrentUser=Windows sẽ hỏi quyền tường lửa khi Teleport mở lần đầu; hãy chọn Cho phép trên mạng Riêng tư.
vi.DeleteUserData=Xóa luôn cài đặt, danh tính máy và danh sách thiết bị đã ghép đôi của Teleport (thư mục %1)?%n%nCác máy đã ghép đôi sẽ phải ghép đôi lại nếu bạn cài lại Teleport. File đã nhận không bị xóa.
vi.DeleteUserDataFailed=Không xóa hết được thư mục %1. Bạn có thể tự xóa phần còn lại.
vi.UserDataInUse=Teleport vẫn đang chạy trên máy này (bản cài khác hoặc bản zip) nên chưa xóa thư mục %1. Hãy thoát Teleport rồi tự xóa thư mục này nếu muốn.
vi.UserDataCheckFailed=Không kiểm được Teleport còn chạy hay không nên chưa xóa thư mục %1. Hãy thoát Teleport rồi tự xóa thư mục này nếu muốn.
; TODO E1 (sau buổi demo): bản tiếng Anh của các message trên, bỏ comment khi bật ngôn ngữ "en".
; en.AppRunning=Teleport is running. Quit Teleport (right-click the tray icon → Quit), then click Retry.
; en.AppRunningAborted=Teleport is still running. Quit Teleport (right-click the tray icon → Quit), then run the installer again.
; en.AppRunningOtherSession=Teleport may be running in another account on this computer.
; en.FirewallCurrentUser=Windows will ask for firewall permission when Teleport first opens; choose Allow on Private networks.
; en.DeleteUserData=Also delete Teleport's settings, device identity and paired devices (folder %1)?%n%nPaired devices will have to pair again if you reinstall Teleport. Received files are not deleted.
; en.DeleteUserDataFailed=Could not delete all of %1. You can delete the rest yourself.
; en.UserDataInUse=Teleport is still running on this computer (another installed copy or the zip version), so folder %1 was not deleted. Quit Teleport, then delete the folder yourself if you want.
; en.UserDataCheckFailed=Could not check whether Teleport is still running, so folder %1 was not deleted. Quit Teleport, then delete the folder yourself if you want.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Cài đè: bỏ hẳn thư viện của bản cũ để không sót DLL/module bản mới không còn dùng. Chỉ xóa khi {app}
; đúng là chỗ bộ cài này đã cài Teleport (IsOwnInstallDir ở [Code]): cài lần đầu vào thư mục sẵn có
; _internal của app khác (ví dụ /DIR=D:\Apps) thì không đụng.
Type: filesandordirs; Name: "{app}\_internal"; Check: IsOwnInstallDir
; Lối tắt tên cũ “Teleport” của bản trước khi đổi tên hiển thị (cùng điều kiện như trên).
Type: files; Name: "{autoprograms}\Teleport.lnk"; Check: IsOwnInstallDir
Type: files; Name: "{autodesktop}\Teleport.lnk"; Check: IsOwnInstallDir

[Files]
; Cả thư mục --onedir trừ DOC-TRUOC.txt (hướng dẫn cho bản zip: giải nén, tự cho qua tường lửa).
Source: "{#SourceDir}\*"; Excludes: "\DOC-TRUOC.txt"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "licenses\InnoSetup-6.7.3-license.txt"; DestDir: "{app}\licenses"; DestName: "InnoSetup-license.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\ZCL Teleport"; Filename: "{app}\Teleport.exe"
Name: "{autodesktop}\ZCL Teleport"; Filename: "{app}\Teleport.exe"; Tasks: desktopicon

[Run]
; runasoriginaluser: bản cài admin vẫn mở app bằng tài khoản người dùng, không chạy app với quyền admin.
Filename: "{app}\Teleport.exe"; Description: "{cm:LaunchProgram,ZCL Teleport}"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallDelete]
Type: dirifempty; Name: "{app}"

[Code]
const
  // Giá trị tự khởi động cùng Windows mà app ghi (hợp đồng ở docs/architecture.md mục 4).
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  StartupApprovedRunKey = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run';
  RunValueName = 'Teleport';
  // Hai rule tường lửa của bản cài admin (docs/architecture.md mục 4).
  RuleTcp = 'Teleport (TCP-In)';
  RuleUdp = 'Teleport (UDP-In)';
  // Khóa gỡ cài đặt Inno ghi cho AppId này (thêm '{AppId}_is1'); giá trị dưới đây là thư mục đã cài.
  UninstallKeyPrefix = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\';
  UninstallAppPathValue = 'Inno Setup: App Path';

function GetCurrentProcessId: Cardinal;
  external 'GetCurrentProcessId@kernel32.dll stdcall';
function ProcessIdToSessionId(ProcessId: Cardinal; var SessionId: Cardinal): BOOL;
  external 'ProcessIdToSessionId@kernel32.dll stdcall';

// Số tiến trình Teleport.exe chạy từ AppDir (so đường dẫn không phân biệt hoa thường); OtherSession
// = có tiến trình như vậy ở phiên đăng nhập khác. WMI lỗi thì trả 0, không chặn: Restart Manager
// (CloseApplications=force) vẫn đóng app khi cài đè.
function CountRunning(const AppDir: String; var OtherSession: Boolean): Integer;
var
  Locator, Service, Items, Item, Value: Variant;
  Prefix, Path: String;
  I: Integer;
  MySession, Session: Cardinal;
begin
  Result := 0;
  OtherSession := False;
  if not ProcessIdToSessionId(GetCurrentProcessId, MySession) then
    MySession := $FFFFFFFF;
  Prefix := AnsiLowercase(AddBackslash(AppDir));
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Items := Service.ExecQuery('SELECT ProcessId, ExecutablePath, SessionId FROM Win32_Process WHERE Name=''Teleport.exe''');
    for I := 0 to Items.Count - 1 do
    begin
      Item := Items.ItemIndex(I);
      Value := Item.ExecutablePath;
      // Tiến trình của tài khoản khác: bộ cài không có quyền admin thì không đọc được đường dẫn.
      if VarIsNull(Value) or VarIsEmpty(Value) then
        Continue;
      Path := AnsiLowercase(Value);
      if Pos(Prefix, Path) = 1 then
      begin
        Result := Result + 1;
        Session := Item.SessionId;
        if Session <> MySession then
          OtherSession := True;
      end;
    end;
  except
    Log('Không kiểm được tiến trình Teleport qua WMI: ' + GetExceptionMessage);
    Result := 0;
  end;
end;

// Số tiến trình Teleport.exe trong phiên đăng nhập này, chạy từ bất kỳ đâu (bản cài khác, bản zip đều
// có thể dùng chung thư mục cấu hình mặc định). Ok = False khi không kiểm được (WMI lỗi).
function CountRunningInMySession(var Ok: Boolean): Integer;
var
  Locator, Service, Items, Item: Variant;
  I: Integer;
  MySession, Session: Cardinal;
begin
  Result := 0;
  Ok := False;
  if not ProcessIdToSessionId(GetCurrentProcessId, MySession) then
  begin
    Log('Không đọc được phiên đăng nhập của bộ gỡ');
    Exit;
  end;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Items := Service.ExecQuery('SELECT ProcessId, SessionId FROM Win32_Process WHERE Name=''Teleport.exe''');
    for I := 0 to Items.Count - 1 do
    begin
      Item := Items.ItemIndex(I);
      Session := Item.SessionId;
      if Session = MySession then
        Result := Result + 1;
    end;
    Ok := True;
  except
    Log('Không kiểm được tiến trình Teleport qua WMI: ' + GetExceptionMessage);
    Result := 0;
  end;
end;

// Check của [InstallDelete]: True khi {app} đúng là chỗ bộ cài này đã cài Teleport, tức khóa gỡ cài đặt
// của AppId này (HKA: HKLM khi cài cho cả máy, HKCU khi /CURRENTUSER) ghi đúng thư mục này và
// Teleport.exe còn ở đó. Dựa vào khóa chứ không chỉ vào Teleport.exe để không nhầm thư mục của app
// khác tình cờ có file cùng tên.
function IsOwnInstallDir: Boolean;
var
  Key, Recorded, AppDir: String;
begin
  Result := False;
  AppDir := ExpandConstant('{app}');
  // SetupSetting("AppId") là "{{GUID}"; ExpandConstant đổi "{{" thành "{".
  Key := UninstallKeyPrefix + ExpandConstant('{#SetupSetting("AppId")}') + '_is1';
  if RegQueryStringValue(HKA, Key, UninstallAppPathValue, Recorded) then
    Result := (CompareText(RemoveBackslashUnlessRoot(Recorded), RemoveBackslashUnlessRoot(AppDir)) = 0) and
      FileExists(AddBackslash(AppDir) + 'Teleport.exe');
  if not Result then
    Log('Thư mục cài chưa phải chỗ Teleport đã cài, không xóa _internal: ' + AppDir);
end;

// True khi không còn Teleport chạy từ AppDir. Còn thì hỏi Thử lại / Hủy; Silent thì không hỏi mà trả
// False ngay (bộ cài/gỡ thoát với mã lỗi, không hẹn xóa file sau khi khởi động lại).
function WaitAppClosed(const AppDir: String; Silent: Boolean; var OtherSession: Boolean): Boolean;
var
  Msg: String;
begin
  Result := True;
  while CountRunning(AppDir, OtherSession) > 0 do
  begin
    Msg := CustomMessage('AppRunning');
    if OtherSession then
      Msg := Msg + #13#10#13#10 + CustomMessage('AppRunningOtherSession');
    Log('Teleport đang chạy từ ' + AppDir);
    if Silent or (SuppressibleMsgBox(Msg, mbError, MB_RETRYCANCEL, IDCANCEL) = IDCANCEL) then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

procedure Netsh(const Params: String);
var
  Code: Integer;
begin
  if Exec(ExpandConstant('{sys}\netsh.exe'), Params, '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Log('netsh ' + Params + ' -> ' + IntToStr(Code))
  else
    Log('Không chạy được netsh ' + Params + ': ' + SysErrorMessage(Code));
end;

// Mọi lệnh xóa rule đều kèm program= để không xóa rule cùng tên của chương trình khác.
function ProgramArg: String;
begin
  Result := 'program="' + ExpandConstant('{app}\Teleport.exe') + '"';
end;

// Chỉ gọi khi IsAdminInstallMode. Lỗi netsh chỉ ghi log, không hủy cài.
procedure AddFirewallRules;
begin
  Netsh('advfirewall firewall delete rule name="' + RuleTcp + '" dir=in ' + ProgramArg);
  Netsh('advfirewall firewall delete rule name="' + RuleUdp + '" dir=in ' + ProgramArg);
  // Không ghim localport: TCP có cổng dự phòng khi 47474 bận, UDP cần cho mDNS (5353) qua zeroconf.
  Netsh('advfirewall firewall add rule name="' + RuleTcp + '" dir=in action=allow ' + ProgramArg +
    ' profile=private remoteip=localsubnet edge=no enable=yes protocol=TCP');
  Netsh('advfirewall firewall add rule name="' + RuleUdp + '" dir=in action=allow ' + ProgramArg +
    ' profile=private remoteip=localsubnet edge=no enable=yes protocol=UDP');
end;

// Gỡ (admin): xóa hai rule của bộ cài, rồi mọi rule vào của đúng Teleport.exe này (kể cả rule chặn do
// Windows tự sinh khi người dùng bấm Cancel ở hộp thoại tường lửa).
procedure RemoveFirewallRules;
begin
  Netsh('advfirewall firewall delete rule name="' + RuleTcp + '" dir=in ' + ProgramArg);
  Netsh('advfirewall firewall delete rule name="' + RuleUdp + '" dir=in ' + ProgramArg);
  Netsh('advfirewall firewall delete rule name=all dir=in ' + ProgramArg);
end;

// Xóa giá trị Run của tài khoản đang chạy bộ gỡ, chỉ khi nó trỏ tới {app}\Teleport.exe của bản này
// (không đụng bản cài khác, ví dụ bản cài /CURRENTUSER cạnh bản cài cho cả máy). Xóa được thì xóa luôn
// trạng thái bật/tắt mà Task Manager lưu ở StartupApproved\Run.
procedure RemoveAutostart;
var
  Data, Exe: String;
begin
  if not RegQueryStringValue(HKCU, RunKey, RunValueName, Data) then
    Exit;
  StringChangeEx(Data, '"', '', True);
  Exe := AnsiLowercase(ExpandConstant('{app}\Teleport.exe'));
  if Pos(Exe, AnsiLowercase(Data)) = 0 then
  begin
    Log('Giá trị Run\Teleport không trỏ tới bản này, giữ nguyên');
    Exit;
  end;
  if RegDeleteValue(HKCU, RunKey, RunValueName) then
    RegDeleteValue(HKCU, StartupApprovedRunKey, RunValueName)
  else
    Log('Không xóa được giá trị Run\Teleport');
end;

// Hỏi xóa thư mục cấu hình mặc định {userappdata}\Teleport (mặc định Không; gỡ silent luôn giữ).
// Không bao giờ đụng thư mục nhận (kể cả <thư mục nhận>\.teleport\) hay TELEPORT_HOME tùy chỉnh.
// Còn Teleport.exe nào chạy trong phiên này (bản cài khác, bản zip) thì không xóa vì nó có thể đang
// dùng chính thư mục này; không kiểm được (WMI lỗi) cũng không xóa. Cả hai trường hợp báo một câu.
procedure AskDeleteUserData;
var
  Dir: String;
  Ok: Boolean;
begin
  Dir := ExpandConstant('{userappdata}\Teleport');
  if UninstallSilent or not DirExists(Dir) then
    Exit;
  if MsgBox(FmtMessage(CustomMessage('DeleteUserData'), [Dir]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
    Exit;
  if CountRunningInMySession(Ok) > 0 then
  begin
    Log('Còn Teleport chạy trong phiên này, giữ ' + Dir);
    MsgBox(FmtMessage(CustomMessage('UserDataInUse'), [Dir]), mbInformation, MB_OK);
    Exit;
  end;
  if not Ok then
  begin
    MsgBox(FmtMessage(CustomMessage('UserDataCheckFailed'), [Dir]), mbInformation, MB_OK);
    Exit;
  end;
  DelTree(Dir, True, True, True);
  if DirExists(Dir) then
    MsgBox(FmtMessage(CustomMessage('DeleteUserDataFailed'), [Dir]), mbError, MB_OK);
end;

// Cài đè khi Teleport đang chạy từ thư mục cài: hỏi người dùng thoát app. Cài lần đầu (chưa có {app})
// thì bỏ qua. Trả chuỗi khác rỗng = dừng ở trang "Chuẩn bị cài đặt" (silent: thoát với mã lỗi); trang
// đó không có nút Thử lại nên dùng câu riêng AppRunningAborted.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  AppDir: String;
  OtherSession: Boolean;
begin
  Result := '';
  AppDir := ExpandConstant('{app}');
  if not DirExists(AppDir) then
    Exit;
  if not WaitAppClosed(AppDir, WizardSilent, OtherSession) then
  begin
    Result := CustomMessage('AppRunningAborted');
    if OtherSession then
      Result := Result + #13#10#13#10 + CustomMessage('AppRunningOtherSession');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and IsAdminInstallMode then
    AddFirewallRules;
end;

// /CURRENTUSER không tạo rule: nhắc người dùng chọn Cho phép trên mạng Riêng tư khi Windows hỏi.
procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and not IsAdminInstallMode then
  begin
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 +
      CustomMessage('FirewallCurrentUser');
    WizardForm.AdjustLabelHeight(WizardForm.FinishedLabel);
    WizardForm.RunList.Top := WizardForm.FinishedLabel.Top + WizardForm.FinishedLabel.Height + ScaleY(12);
  end;
end;

// Gỡ khi Teleport đang chạy từ thư mục cài: hỏi thoát app; silent hay bấm Hủy thì không gỡ gì.
function InitializeUninstall: Boolean;
var
  OtherSession: Boolean;
begin
  Result := WaitAppClosed(ExpandConstant('{app}'), UninstallSilent, OtherSession);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if IsAdminInstallMode then
      RemoveFirewallRules;
    RemoveAutostart;
  end
  else if CurUninstallStep = usPostUninstall then
    AskDeleteUserData;
end;
