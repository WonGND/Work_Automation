# 업무관리 웹 (work-mgmt-web)

팀원이 매일 업무 · 이슈별 투입 시간을 입력하고, 팀장 · PL이 사람별 업무 로드와 이슈 진행을 한눈에 보는 사내용 웹 프로그램입니다.
엑셀(VBA) 기반으로 운영하던 팀 업무관리를 웹으로 옮긴 것으로, 사내 NAS 한 대에서 도커로 돌아갑니다.

> 이 저장소의 데이터(`sample/seed.json`)는 구조만 실제와 같고 이름 · 모델 · 업무 내용은 모두 만든 값입니다.

## 주요 기능

- **시간 입력**: 주간 · 월간 표에 0.5시간 단위로 입력하면 바로 저장. 날짜별 '그날 한 일', 하루 합계 색(미입력 · 8h 초과), 입력 즉시 근무 시간율 갱신
- **업무**: 통상 · 기타 업무 추가(날짜별 시간 함께 입력), 진행률 · 마감일 · 완료, 끌어서 순서 바꾸기, PL의 업무 지정
- **이슈**: PL이 등록하고 정 · 부1 · 부2 담당 지정, 단계 · 일정(지연 · 임박) 관리, 이슈 정리(파트 · 모델별 보기)
- **이슈 진행 현황 4칸**: 현상 · 원인 분석 · 개선검토 · 검증 및 적용 (PL · 팀장 · 마스터가 씀, 칸별 마지막 수정 표시), 이슈당 첨부 이미지 한 장(붙여넣기 · 끌어다 놓기 · DB 밖 폴더에 저장)
- **업무로드**: 파트 · 개인별 근무 시간율, 등급 배율을 반영한 업무 로드, 판정(과부하 · 적정 · 여유), 모델별 투입
- **권한**: 팀원 · PL · 팀장 · 마스터 (우리 파트 · 내가 담당인 이슈만 보기 등)
- **알림 · 요청**: 🔔 알림, PL · 팀장에게 요청 보내기
- **엑셀 가져오기**: 기존 엑셀에서 뽑은 seed를 기간을 골라 반영(미리보기 · 되돌릴 수 있는 자동 백업 · 여러 번 해도 같은 결과)
- **화면**: 화면 A · B · C 세 가지 모양 + 각각 다크 모드, 사람별 저장
- **입사 · 퇴사**: 입사일 · 퇴사일 (퇴사 다음 날부터 로그인 막힘 · 목록에서 숨김 · 기록은 남음), 미입력 알림(전 근무일 · 주간 요약)
- **운영**: 매일 자동 백업(90개 보관), 변경 기록, 메일로 비밀번호 찾기(SMTP), 내부 인증 기관으로 HTTPS

## 구조

```
app/
  src/        서버 (Bun + TypeScript, 하나의 실행 파일로 컴파일)
    server.ts   HTTP/HTTPS 서버 · 보안 헤더 · 정적 파일
    api.ts      REST API (로그인 · 업무 · 시간 · 이슈 · 관리)
    db.ts       SQLite(WAL) 스키마 · 마이그레이션 · 백업
    calc.ts     근무 시간율 · 업무 로드 · 판정 계산
    seed.ts     처음 설정 · 엑셀 가져오기(기간 반영 · 웹 우선)
    remind.ts   미입력 알림
    selfsign.ts 내부 인증 기관(CA) · 서버 인증서 생성 (외부 라이브러리 없이 DER 직접 작성)
    secret.ts   메일 비밀번호 암호화(AES-256-GCM) · 임시 비밀번호
    mail.ts     SMTP 발송
  public/     화면 (프레임워크 없는 단일 페이지: app.js · style.css)
  guide/      인증서 설치 안내 그림 원본(steps.html)과 캡처
tools/        시험 · 빌드 도구 (Python)
sample/       샘플 seed (가짜 데이터)
deploy/       도커 compose 예시
```

## 빠르게 실행해 보기

필요한 것: [Bun](https://bun.sh) 1.4 이상, Python 3

```bash
cd app && bun install && cd ..
python3 tools/mk_guide.py                 # 안내 그림 → app/src/guide_img.ts
mkdir -p run && cp sample/seed.json run/
cd app && bun build --compile src/server.ts --outfile ../run/workmgmt && cd ../run
./workmgmt --port 8000                    # http://localhost:8000
```

처음 켜면 콘솔에 **설정 코드(8자리)** 가 나옵니다. 브라우저에서 그 코드와 마스터 아이디(샘플: `홍길동`)로 마스터 비밀번호를 정하고, 나머지 계정은 관리 → 계정에서 처음 비밀번호를 만들어 전달합니다.

HTTPS(내부 인증서)로 실행:

```bash
./workmgmt --port 8443 --self-signed --cert-hosts 192.168.0.10 --http-port 8000
```

각 PC는 로그인 화면의 '인증서 설치' 안내를 따라 CA 인증서를 한 번 설치하면 경고 없이 접속됩니다.

## 시험

```bash
# 서버를 띄운 뒤 (데이터 폴더가 비어 있는 상태)
python3 tools/bootstrap.py http://127.0.0.1:8000 <서버 로그 파일> acc.txt   # 처음 설정 · 계정 (10건)
python3 tools/api_test.py   http://127.0.0.1:8000 acc.txt                     # API 권한 · 계산 · 입력 검사 (137건)
python3 tools/import_test.py http://127.0.0.1:8000 acc.txt sample/seed.json <데이터>/업무관리.db   # 엑셀 가져오기 (19건)
python3 tools/v056_test.py  http://127.0.0.1:8000 acc.txt sample/seed.json <데이터>/업무관리.db   # 웹 우선 가져오기 · 입사 · 퇴사 (24건)
python3 tools/v057_test.py  http://127.0.0.1:8000 acc.txt sample/seed.json <데이터>/업무관리.db   # 미입력 알림 · 화면 갱신 번호 · 가져오기 권한 (14건)
python3 tools/v060_test.py  http://127.0.0.1:8000 acc.txt sample/seed.json <데이터>/업무관리.db   # 이슈 4칸 · 첨부 이미지 · 월간 표 · 모델 여러 줄/숨김 (74건)
python3 tools/mail_test.py  http://127.0.0.1:8000 <비밀번호> 홍길동           # 메일 · 비밀번호 찾기 (15건, aiosmtpd 필요)
```

## 도커 이미지 (NAS 배포)

도커 없이 이미지 tar를 만듭니다. 오래된 CPU(AVX 없음)도 돌도록 baseline으로 빌드합니다.

```bash
cd app && bun build --compile --target=bun-linux-x64-baseline src/server.ts --outfile ../wl_base && cd ..
python3 tools/mk_image.py wl_base sample/seed.json workmgmt-0.6.0.tar workmgmt:0.6.0
```

NAS에서 `docker load -i workmgmt-0.6.0.tar` 후 `deploy/docker-compose.yml`로 실행합니다. `data`(DB · 백업)와 `keys`(암호화 열쇠 · 인증서)는 컨테이너 밖 폴더라 이미지를 바꿔도 그대로 남습니다.

## 설정 (환경 변수)

| 변수 | 뜻 |
| --- | --- |
| `WL_DATA` | 데이터 폴더 (DB · 백업) |
| `WL_KEY_FILE` | 암호화 열쇠 파일 (데이터 폴더 밖에 두기) |
| `WL_SELF_SIGNED=1` · `WL_CERT_HOSTS` | 내부 인증서로 HTTPS · 인증서에 넣을 주소 |
| `WL_HTTP_PORT` | HTTP → HTTPS 넘김 포트 |
| `WL_MASTER` | 처음 설정 때 마스터로 만들 이름 (seed의 `master`가 우선) |

## 보안 메모

- 비밀번호는 argon2id 해시, 세션 쿠키는 HttpOnly · SameSite=Lax · (HTTPS면) Secure, 변경 요청은 `x-req` 헤더 검사
- 계정 비밀번호를 파일로 남기지 않음, 처음 설정 코드는 콘솔 · 로그에만
- SMTP 비밀번호는 데이터 폴더 밖 열쇠로 암호화해 저장
- 보안 헤더(nosniff · no-referrer · CSP · HTTPS면 HSTS)

## 실제 데이터를 쓸 때

`tools/extract_seed.py`로 팀 엑셀 파일에서 seed를 뽑습니다(엑셀 양식 기준). 실제 seed · DB · 열쇠 폴더는 `.gitignore`로 저장소에 올라가지 않게 해 두었습니다.
