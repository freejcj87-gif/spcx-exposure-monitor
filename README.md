# SPCX 익스포저 모니터

미래에셋생명 PI운용팀 · SpaceX(SPCX) 익스포저 라이브 대시보드 (Streamlit + yfinance).
접속할 때마다 시세를 자동으로 받아 항상 최신 상태를 보여줍니다 (15분 캐시).

## 로컬 실행
```bash
pip install -r requirements.txt
streamlit run app.py
```

## 배포 (Streamlit Community Cloud)
1. 이 폴더를 GitHub repo(비공개 권장)로 push
2. https://share.streamlit.io → GitHub 로그인 → New app → repo/branch/`app.py` 선택 → Deploy
3. App settings > **Secrets** 에 아래 입력 (비밀번호 게이트)
   ```toml
   APP_PASSWORD = "원하는-비밀번호"
   ```
4. 발급된 고정 링크를 공유. 수정은 `git push` → 자동 재배포.

## 갱신 포인트 (app.py)
- `CONSTANTS` — 보유주수·매입원가·자기자본 등 포지션 고정값
- `TICKERS` — 추적 종목/지수/환율
- `LOCKUP` / `CATALYSTS` — 락업 일정·촉매 캘린더
- `ANALYST` — 목표가(웹 수동 갱신)

데이터: yfinance(공개 시세). 실패 시 마지막 확인치(FALLBACK, 2026-06-15)로 표시.
정보 제공·교육 목적이며 투자자문이 아닙니다.
