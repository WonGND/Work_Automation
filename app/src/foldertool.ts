// 0.7.9: '폴더 바로 열기' 설치 묶음 — workfolder: 링크를 누르면 탐색기로 이슈 폴더를 엶 (PC마다 한 번 설치)
// 0.8.0: PowerShell(켜는 데 수 초) 대신 작은 실행 파일 — 설치할 때 윈도우 기본 C# 컴파일러(.NET Framework csc.exe)로
//        그 PC에서 소스를 빌드 (미리 만든 실행 파일을 보내지 않음 · 소스를 그대로 검토 가능). csc 가 없으면 예전 PowerShell 방식.
//   · 내 계정에만 등록 (HKCU · 관리자 권한 필요 없음) · 지정한 이슈 폴더(UNC) 아래만 열고 그 밖은 거부
//   · 링크 모양: workfolder:<이슈 폴더 기준 상대 경로를 URL 인코딩> (예: workfolder:G8%2F26-012%20...)
//   · 파일 이름은 영문 (압축 프로그램마다 한글 이름이 깨질 수 있어서)
import { zipSync, strToU8 } from "fflate";

const crlf = (s: string) => s.replace(/\r?\n/g, "\r\n");
const psq = (s: string) => s.replace(/'/g, "''");    // PowerShell 작은따옴표 문자열 안
const csq = (s: string) => s.replace(/"/g, '""');    // C# @"..." 문자열 안

// C# 5 문법만 (윈도우에 기본으로 있는 csc.exe v4.0.30319 가 C# 5)
export function handlerCs(unc: string): string {
  return crlf(`// 회로팀 업무관리 - 이슈 폴더 바로 열기 (workfolder: 링크 처리)
// 정해진 이슈 폴더 아래만 탐색기로 엽니다. 다른 경로 · 프로그램 실행 · 파일 읽기/쓰기/삭제는 하지 않습니다.
using System;
using System.Diagnostics;
using System.Windows.Forms;

static class OpenFolder
{
    const string Root = @"${csq(unc)}";

    [STAThread]
    static int Main(string[] args)
    {
        string link = args.Length > 0 ? args[0] : "";
        if (!link.StartsWith("workfolder:", StringComparison.OrdinalIgnoreCase)) return Fail("잘못된 링크입니다.");
        string rel;
        try { rel = Uri.UnescapeDataString(link.Substring(11)); } catch { return Fail("잘못된 링크입니다."); }
        rel = rel.Trim().Trim('/').Replace('/', '\\\\');
        if (rel.Length == 0 || rel.Contains("..") || rel.IndexOfAny(":*?\\"<>|".ToCharArray()) >= 0 || rel.StartsWith("\\\\") || rel.Length > 400)
            return Fail("열 수 없는 경로입니다: " + rel);
        string full = Root + "\\\\" + rel;
        // 0.8.1: 폴더만 연다 (파일 경로면 실행될 수 있으므로 거부)
        if (!System.IO.Directory.Exists(full)) return Fail("폴더를 찾지 못했습니다 (이름이 바뀌었거나 아직 안 만들어졌을 수 있습니다):\\n" + full);
        // 0.8.1: 탐색기 새 프로세스를 띄우지 않고 윈도우 셸에 폴더를 바로 넘김 (이미 떠 있는 탐색기가 열어서 빠름)
        try { ProcessStartInfo psi = new ProcessStartInfo(full); psi.UseShellExecute = true; Process.Start(psi); }
        catch (Exception e) { return Fail("폴더를 열 수 없습니다: " + e.Message); }
        return 0;
    }

    static int Fail(string m)
    {
        MessageBox.Show(m, "업무관리 폴더 열기", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        return 1;
    }
}
`);
}

// 예비: C# 컴파일러가 없는 PC용 (0.7.9 방식)
export function handlerPs1(unc: string): string {
  return crlf(`# 회로팀 업무관리 - 이슈 폴더 바로 열기 (workfolder: 링크 처리 · 예비)
param([string]$Link)
$Root = '${psq(unc)}'
function Fail([string]$m) { Add-Type -AssemblyName System.Windows.Forms | Out-Null; [System.Windows.Forms.MessageBox]::Show($m, '업무관리 폴더 열기') | Out-Null; exit 1 }
if ($Link -notmatch '^workfolder:') { Fail '잘못된 링크입니다.' }
$rel = [uri]::UnescapeDataString($Link.Substring(11)).Trim().Trim('/').Replace('/', '\\')
if ($rel -eq '' -or $rel -match '\\.\\.' -or $rel -match '[:*?"<>|]' -or $rel.StartsWith('\\') -or $rel.Length -gt 400) { Fail ('열 수 없는 경로입니다: ' + $rel) }
$full = Join-Path $Root $rel
if (-not (Test-Path -LiteralPath $full -PathType Container)) { Fail ('폴더를 찾지 못했습니다: ' + $full) }
Invoke-Item -LiteralPath $full
`);
}

const CSC = `set "CSC=%WINDIR%\\Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\\Microsoft.NET\\Framework\\v4.0.30319\\csc.exe"`;

const INSTALL = `@echo off
chcp 65001 >nul
setlocal
set "DIR=%LOCALAPPDATA%\\WorkMgmtFolder"
if not exist "%DIR%" mkdir "%DIR%"
${CSC}
if exist "%DIR%\\open-folder.exe" del "%DIR%\\open-folder.exe" >nul 2>&1
if exist "%CSC%" "%CSC%" /nologo /target:winexe /optimize+ /out:"%DIR%\\open-folder.exe" /r:System.Windows.Forms.dll "%~dp0open-folder.cs" >"%DIR%\\build.log" 2>&1
if exist "%DIR%\\open-folder.exe" goto :fast
copy /Y "%~dp0open-folder.ps1" "%DIR%\\open-folder.ps1" >nul || goto :err
powershell -NoProfile -Command "Unblock-File -LiteralPath '%DIR%\\open-folder.ps1'" >nul 2>&1
set "CMD=powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \\"%DIR%\\open-folder.ps1\\" \\"%%1\\""
set "HOW=ps"
goto :reg
:fast
if exist "%DIR%\\open-folder.ps1" del "%DIR%\\open-folder.ps1" >nul 2>&1
set "CMD=\\"%DIR%\\open-folder.exe\\" \\"%%1\\""
set "HOW=fast"
:reg
reg add "HKCU\\Software\\Classes\\workfolder" /ve /d "URL:WorkMgmt Folder" /f >nul || goto :err
reg add "HKCU\\Software\\Classes\\workfolder" /v "URL Protocol" /d "" /f >nul || goto :err
reg add "HKCU\\Software\\Classes\\workfolder\\shell\\open\\command" /ve /d "%CMD%" /f >nul || goto :err
echo.
type "%~dp0msg_%HOW%.txt"
echo.
pause
exit /b 0
:err
echo.
type "%~dp0msg_fail.txt"
echo.
pause
exit /b 1
`;
const UNINSTALL = `@echo off
chcp 65001 >nul
reg delete "HKCU\\Software\\Classes\\workfolder" /f >nul 2>&1
if exist "%LOCALAPPDATA%\\WorkMgmtFolder" rmdir /S /Q "%LOCALAPPDATA%\\WorkMgmtFolder"
echo.
type "%~dp0msg_removed.txt"
echo.
pause
`;
const README = (unc: string) => `회로팀 업무관리 - 이슈 폴더 바로 열기

이슈 번호 옆 폴더 아이콘을 누르면 탐색기에서 그 이슈 폴더가 바로 열리게 합니다.
PC마다 한 번 설치합니다 (내 계정에만 설치 · 관리자 권한 필요 없음).
이미 설치했던 PC도 다시 설치하면 빠른 방식으로 바뀝니다.

[설치]
1. 이 압축 파일을 풉니다 (압축 풀기 → 모두 추출).
2. install.cmd 를 더블클릭합니다.
   'Windows의 PC 보호' 창이 뜨면 [추가 정보] → [실행].
3. 업무관리 '내 정보' → '폴더 바로 열기'에서 '이 PC에 설치했습니다'를 체크합니다.

[하는 일]
- 설치할 때 open-folder.cs (소스)를 윈도우 기본 C# 컴파일러로 이 PC에서 빌드해 open-folder.exe 를 만듭니다.
- workfolder: 링크를 누르면 아래 폴더 안의 해당 이슈 폴더를 탐색기로 엽니다. 이 폴더 밖은 열지 않습니다.
  ${unc}
- 설치 위치: %LOCALAPPDATA%\\WorkMgmtFolder · 등록: HKEY_CURRENT_USER\\Software\\Classes\\workfolder

[지우기]
uninstall.cmd 를 더블클릭합니다.
`;

// 0.8.1: 한글 안내는 cmd 파일 안에 쓰지 않고 txt 를 type 으로 보여 줌 (UTF-8 cmd 의 echo 한글이 잘려 "'크' is not recognized" 가 뜨던 문제)
const MSG_OK = (how: string) => `  [설치 완료] 업무관리 '폴더 바로 열기' - ${how}

  1) 크롬 / 엣지를 새로고침합니다.
  2) 업무관리 '내 정보'에서 '이 PC에 설치했습니다'를 체크합니다.
  3) 이슈 번호 옆 폴더 아이콘을 누르고, 처음 한 번 묻는 창에서
     '항상 허용' 체크 후 [열기]를 누릅니다.
`;
const MSG_FAIL = `  [설치 실패] 회사 보안 정책으로 막혔을 수 있습니다. 홍길동 주임 또는 IT에 문의하세요.
`;
const MSG_REMOVED = `  [제거 완료] 업무관리 '폴더 바로 열기'를 지웠습니다. '내 정보'의 체크도 꺼 주세요.
`;
export function folderToolZip(unc: string): Uint8Array {
  const u = (s: string, bom = false) => strToU8((bom ? "\uFEFF" : "") + crlf(s));
  return zipSync({
    "install.cmd": u(INSTALL),
    "uninstall.cmd": u(UNINSTALL),
    "open-folder.cs": u(handlerCs(unc), true),       // 한글이 들어 있어 BOM 필요 (csc 가 UTF-8 로 읽음)
    "open-folder.ps1": u(handlerPs1(unc), true),     // 예비 (C# 컴파일러가 없는 PC)
    "README.txt": u(README(unc), true),
    "msg_fast.txt": u(MSG_OK("빠른 방식")),
    "msg_ps.txt": u(MSG_OK("예비 방식 (조금 느림)")),
    "msg_fail.txt": u(MSG_FAIL),
    "msg_removed.txt": u(MSG_REMOVED),
  });
}

// IT 일괄 배포용: 한 번 빌드해서 C:\ProgramData\WorkMgmtFolder 에 두는 방식
export const BUILD_FOR_IT = crlf(`@echo off
chcp 65001 >nul
${CSC}
if not exist "%CSC%" (echo csc.exe not found - .NET Framework 4 is required. & pause & exit /b 1)
"%CSC%" /nologo /target:winexe /optimize+ /out:"%~dp0open-folder.exe" /r:System.Windows.Forms.dll "%~dp0open-folder.cs"
if exist "%~dp0open-folder.exe" (echo OK: open-folder.exe built.) else (echo FAILED: build error)
pause
`);
