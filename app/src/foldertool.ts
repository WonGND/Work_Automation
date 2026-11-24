// 0.7.9: '폴더 바로 열기' 설치 묶음 — workfolder: 링크를 누르면 탐색기로 이슈 폴더를 엶 (PC마다 한 번 설치)
//   · 내 계정에만 등록 (HKCU · 관리자 권한 필요 없음) · 지정한 이슈 폴더(UNC) 아래만 열고 그 밖은 거부
//   · 링크 모양: workfolder:<이슈 폴더 기준 상대 경로를 URL 인코딩> (예: workfolder:G8%2F26-012%20...)
//   · 파일 이름은 영문 (압축 프로그램마다 한글 이름이 깨질 수 있어서)
import { zipSync, strToU8 } from "fflate";

const crlf = (s: string) => s.replace(/\r?\n/g, "\r\n");
const psq = (s: string) => s.replace(/'/g, "''");   // PowerShell 작은따옴표 문자열 안

export function handlerPs1(unc: string): string {
  return crlf(`# 회로팀 업무관리 - 이슈 폴더 바로 열기 (workfolder: 링크 처리)
# 정해진 이슈 폴더 아래만 탐색기로 엽니다. 다른 경로 · 프로그램 실행은 하지 않습니다.
param([string]$Link)
$Root = '${psq(unc)}'
Add-Type -AssemblyName System.Windows.Forms | Out-Null
function Fail([string]$m) { [System.Windows.Forms.MessageBox]::Show($m, '업무관리 폴더 열기') | Out-Null; exit 1 }
if ($Link -notmatch '^workfolder:') { Fail '잘못된 링크입니다.' }
$rel = [uri]::UnescapeDataString($Link.Substring(11)).Trim().Trim('/').Replace('/', '\\')
if ($rel -eq '' -or $rel -match '\\.\\.' -or $rel -match '[:*?"<>|]' -or $rel.StartsWith('\\') -or $rel.Length -gt 400) { Fail ('열 수 없는 경로입니다: ' + $rel) }
$full = Join-Path $Root $rel
if (-not (Test-Path -LiteralPath $full -PathType Container)) {
  if (Test-Path -LiteralPath $Root -PathType Container) { Fail ("폴더를 찾을 수 없습니다.\`n" + $full + "\`n\`n이름이 바뀌었거나 아직 만들어지지 않았을 수 있습니다. 업무관리를 새로고침(F5)한 뒤 다시 눌러 보세요."); }
  else { Fail ("파일 서버에 연결할 수 없습니다.\`n" + $Root + "\`n\`n사내망 연결 · 파일 서버 권한을 확인하세요.") }
}
Start-Process -FilePath 'explorer.exe' -ArgumentList ('"' + $full + '"')
`);
}

// 설치: %LOCALAPPDATA%\\WorkMgmtFolder 에 처리 스크립트를 두고, workfolder: 링크를 그 스크립트로 연결
const INSTALL = `@echo off
chcp 65001 >nul
setlocal
set "DIR=%LOCALAPPDATA%\\WorkMgmtFolder"
if not exist "%DIR%" mkdir "%DIR%"
copy /Y "%~dp0open-folder.ps1" "%DIR%\\open-folder.ps1" >nul || goto :err
powershell -NoProfile -Command "Unblock-File -LiteralPath '%DIR%\\open-folder.ps1'" >nul 2>&1
set "CMD=powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \\"%DIR%\\open-folder.ps1\\" \\"%%1\\""
reg add "HKCU\\Software\\Classes\\workfolder" /ve /d "URL:WorkMgmt Folder" /f >nul || goto :err
reg add "HKCU\\Software\\Classes\\workfolder" /v "URL Protocol" /d "" /f >nul || goto :err
reg add "HKCU\\Software\\Classes\\workfolder\\shell\\open\\command" /ve /d "%CMD%" /f >nul || goto :err
echo.
echo  [설치 완료] 업무관리 '폴더 바로 열기'
echo.
echo  1) 크롬 / 엣지를 새로고침합니다.
echo  2) 업무관리 '내 정보'에서 '이 PC에 설치했습니다'를 체크합니다.
echo  3) 이슈 번호 옆 폴더 아이콘을 누르고, 처음 한 번 묻는 창에서
echo     '항상 허용' 체크 후 [열기]를 누릅니다.
echo.
pause
exit /b 0
:err
echo.
echo  [설치 실패] 회사 보안 정책으로 막혔을 수 있습니다. 곽원용 주임 또는 IT에 문의하세요.
echo.
pause
exit /b 1
`;
const UNINSTALL = `@echo off
chcp 65001 >nul
reg delete "HKCU\\Software\\Classes\\workfolder" /f >nul 2>&1
if exist "%LOCALAPPDATA%\\WorkMgmtFolder" rmdir /S /Q "%LOCALAPPDATA%\\WorkMgmtFolder"
echo.
echo  [제거 완료] 업무관리 '폴더 바로 열기'를 지웠습니다. '내 정보'의 체크도 꺼 주세요.
echo.
pause
`;
const README = (unc: string) => `회로팀 업무관리 - 이슈 폴더 바로 열기

이슈 번호 옆 폴더 아이콘을 누르면 탐색기에서 그 이슈 폴더가 바로 열리게 합니다.
PC마다 한 번 설치합니다 (내 계정에만 설치 · 관리자 권한 필요 없음).

[설치]
1. 이 압축 파일을 풉니다 (압축 풀기 → 모두 추출).
2. install.cmd 를 더블클릭합니다.
   'Windows의 PC 보호' 창이 뜨면 [추가 정보] → [실행].
3. 업무관리 '내 정보' → '폴더 바로 열기'에서 '이 PC에 설치했습니다'를 체크합니다.
4. 이슈 번호 옆 폴더 아이콘을 누릅니다. 처음 한 번 브라우저가
   '열까요?'를 물으면 '항상 허용' 체크 후 [열기].

[하는 일]
- workfolder: 로 시작하는 링크를 누르면 아래 폴더 안의 해당 이슈 폴더를 탐색기로 엽니다.
  ${unc}
- 이 폴더 밖의 경로나 다른 프로그램은 열지 않습니다.
- 설치 위치: %LOCALAPPDATA%\\WorkMgmtFolder\\open-folder.ps1
  등록: HKEY_CURRENT_USER\\Software\\Classes\\workfolder

[지우기]
uninstall.cmd 를 더블클릭합니다.
`;

export function folderToolZip(unc: string): Uint8Array {
  const u = (s: string, bom = false) => strToU8((bom ? "﻿" : "") + crlf(s));
  return zipSync({
    "install.cmd": u(INSTALL),
    "uninstall.cmd": u(UNINSTALL),
    "open-folder.ps1": u(handlerPs1(unc), true),     // 한글이 들어 있어 BOM 필요 (Windows PowerShell 5.1)
    "README.txt": u(README(unc), true),
  });
}
