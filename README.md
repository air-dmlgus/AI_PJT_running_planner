# 러닝 코스 추천 AI Agent

사용자가 원하는 지역, 출발 시각, 거리, 날씨 조건에 맞는 러닝 코스를 추천하는 프로젝트입니다. 5km·10km부터 하프마라톤(21.0975km)까지 다루며, 조건에 맞는 코스가 없으면 사용자가 허용한 지역이나 시간 안에서 대안을 찾도록 설계했습니다.

## 1일차 결과물

| 파일 | 내용 |
| --- | --- |
| [Day1_Running_Planner.md](day1/Day1_Running_Planner.md) | 추천 기준, 대표 시나리오, Tool·Agent·저장 구조, 요구사항 및 검증 기록 |
| [verify_apis.py](day1/verify_apis.py) | 코스·날씨·대기질 API, GMS 연결 및 하프 코스 후보 검증 |
| [env.example](day1/env.example) | API 키와 조회 설정을 입력하기 위한 예시 |
| [.gitignore](.gitignore) | 실제 키 파일과 Python 캐시 제외 |

## 검증 스크립트 실행

Python 3.10 이상이 필요합니다. 검증 스크립트는 Python 표준 라이브러리를 사용합니다.

1. 공공데이터포털에서 두루누비, 기상청 단기예보, 에어코리아 API에 활용 신청합니다. [API별 링크와 이용 조건](day1/Day1_Running_Planner.md#외부-데이터와-이용-조건)
2. 저장소 루트에서 아래 명령을 실행해 설정 파일을 만듭니다.

   **Windows PowerShell**

   ```powershell
   Copy-Item day1/env.example day1/.env
   ```

   **Git Bash 또는 macOS/Linux**

   ```bash
   cp day1/env.example day1/.env
   ```

3. `day1/.env`에 발급받은 공공데이터포털 Decoding 키와 GMS 키를 넣습니다. 공통 공공데이터 키는 `PUBLIC_DATA_KEY`에, 서비스별 키가 있다면 해당 항목에 입력합니다.
4. 저장소 루트에서 점검을 실행합니다.

   ```bash
   python day1/verify_apis.py
   python day1/verify_apis.py half
   ```

   전체 점검은 코스·날씨·대기질 API와 GMS를 확인합니다. 하프 점검은 20~22km 후보 중 목표 거리에 가까운 코스를 최대 3개 출력합니다. 개별 점검은 명령 끝에 `course`, `weather`, `air`, `llm` 중 하나를 붙여 실행합니다.

## 진행 상태

1일차 기획서와 API 검증 스크립트 작성 완료. 하프 코스 필터와 정렬은 샘플 응답으로 확인했으며, 인증이 필요한 실제 API 호출과 시연 지역 확정은 검증 대기 상태입니다.
