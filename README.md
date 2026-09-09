# Work_Automation

업무 자동화 도구 모음 저장소. 각 프로젝트는 독립된 브랜치로 관리됩니다.

## Branches

| Branch | Project | Description |
|--------|---------|-------------|
| `main` | (index) | README 및 공통 설정 |
| `one-click-tool` | One_Click_정리_Tool | 원클릭 데이터 정리 도구 |
| `bu-lotid-merge` | BU_LotID_merge | BU LotID 병합 및 GUI 도구 |
| `cpk-analyzer` | CpkAnalyzer | Cpk 분석 도구 |

## Usage

특정 프로젝트만 clone 하려면:

```bash
git clone -b <branch-name> --single-branch <repo-url>
```

전체 브랜치를 받으려면:

```bash
git clone <repo-url>
git branch -a  # 모든 브랜치 확인
git checkout <branch-name>
```
