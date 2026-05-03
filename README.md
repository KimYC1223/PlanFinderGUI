# PlanFinder GUI

Claude AI를 활용해 코드베이스를 자동 분석하고 개선 계획(Plan)을 생성하는 크로스플랫폼 데스크톱 앱입니다.

## 주요 기능

- **자동 분석**: 프로젝트 디렉터리를 지정하면 Claude가 반복적으로 코드를 탐색해 버그, 개선점, 리팩터링 대상을 찾아냅니다
- **리포트 브라우저**: 생성된 플랜을 `pending / working / reviewed / reject` 폴더 트리로 관리하고 내장 마크다운 뷰어로 바로 확인합니다
- **플랜 실행**: 체크박스로 플랜을 선택하고 Resolve 버튼을 누르면 Claude가 실제 코드 변경을 수행합니다
- **번역 지원**: Google Translate API 또는 Claude를 이용해 리포트를 자동 번역(한국어 등)합니다
- **세션 제어**: 예산 제한, 최대 반복 횟수, 중단 시각(Stop at) 설정을 지원합니다
- **마크다운 렌더링**: D2Coding 폰트 기반 다크테마 뷰어, 코드 블록 하이라이팅 포함

## 요구사항

- Python 3.11 이상 (개발 환경: 3.14)
- [uv](https://github.com/astral-sh/uv) 패키지 관리자
- [Claude Code CLI](https://github.com/anthropics/claude-code) (`claude` 명령어가 PATH에 있어야 합니다)
- (선택) [ccusage](https://github.com/ryoppippi/ccusage) — 예산 Throttle 기능 사용 시 필요
- (선택) Google Cloud 서비스 계정 JSON — Google Translate 기능 사용 시 필요

## 설치 및 실행

```bash
# 의존성 설치
uv sync

# 실행
uv run plan-finder-gui
```

## 빌드 (PyInstaller)

macOS `.app` 또는 Windows `.exe`로 패키징합니다.

```bash
bash build.sh
```

빌드 결과물:
- macOS: `dist/PlanFinder.app`
- Windows: `dist/PlanFinder/PlanFinder.exe`

## 리포트 구조

플랜은 `~/claude-reports/<프로젝트명>/` 아래에 저장됩니다.

```
~/claude-reports/<project>/
├── pending/    # 생성된 플랜 (검토 대기)
├── working/    # Resolve 진행 중인 플랜
├── reviewed/   # 실행 완료된 플랜
└── reject/     # 거절된 플랜
```

번역 파일은 원본 파일과 같은 폴더에 `<원본명>.ko.md` 형식으로 저장됩니다.

## 사용 방법

1. **Directory**: 분석할 프로젝트 폴더를 선택합니다
2. **Prompt**: Claude에게 줄 분석 지침을 입력합니다 (예: `버그를 찾고 에러 처리를 개선해줘`)
3. **Start** 버튼을 클릭하면 자동 분석이 시작됩니다
4. 생성된 플랜은 리포트 브라우저의 `pending` 폴더에 나타납니다
5. 플랜을 체크 후 **Resolve** → Claude가 실제 코드를 수정합니다
6. 불필요한 플랜은 **Reject**, 다시 시도하려면 **Restart**를 사용합니다

## 설정 옵션

| 항목 | 설명 |
|---|---|
| Model | 사용할 Claude 모델 |
| Budget | 세션 최대 비용 (ccusage 필요) |
| Max iter | 최대 반복 횟수 (0 = 무제한) |
| Max turns | Claude 대화 최대 턴 수 |
| Stop at | 지정 시각에 자동 중단 |
| Throttle | ccusage 기반 사용량 제한 활성화 |
| Fresh session | 매 반복마다 새 세션으로 시작 |
| Auto-translate | 리포트 자동 번역 (Google / Claude) |
