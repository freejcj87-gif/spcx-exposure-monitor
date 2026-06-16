# SPCX 익스포저 모니터

미래에셋생명 PI운용팀 · SpaceX(SPCX) 익스포저 라이브 대시보드 (Streamlit + yfinance).
접속할 때마다 시세를 자동으로 받아 항상 최신 상태를 보여줍니다 (15분 캐시).

> 🔒 당사 데이터가 포함되므로 이 repo 는 **비공개(private)** 로 유지합니다.

## 당사 데이터 관리 (중요)
모든 당사 데이터는 **`config.toml` 한 파일**에서 관리합니다 — 포지션·자기자본·목표가·환오픈 등.
값을 바꾸거나 항목을 추가하려면 `config.toml` 을 편집하고 `git push` 하면 배포본에 자동 반영됩니다.
(코드 `app.py` 는 건드릴 필요 없음.)

## 로컬 실행
```bash
pip install -r requirements.txt
streamlit run app.py
```

## 배포 (Streamlit Community Cloud, 비공개 repo)
1. https://share.streamlit.io → GitHub 로그인
2. 비공개 repo 접근 권한 부여: 우상단 아바타 → **Settings → Linked accounts** 에서
   GitHub 재인증 시 **private repositories** 접근을 허용 (이 단계가 없으면 repo 가 안 보임)
3. **Create app** → Repository=이 repo / Branch=`main` / Main file path=`app.py`
4. (선택) **Advanced settings → Secrets** 에 접근 비밀번호:
   ```toml
   APP_PASSWORD = "원하는비밀번호"
   ```
5. **Deploy** → 발급된 고정 링크 공유. 수정은 `git push` → 자동 재배포.

## 갱신 포인트
- `config.toml` — 당사 데이터 전부 (포지션·자기자본·목표가·환오픈)
- `app.py` 의 `LOCKUP` / `CATALYSTS` / `TICKERS` — 락업 일정·촉매·추적 종목

데이터: yfinance(공개 시세). 실패 시 마지막 확인치(FALLBACK)로 표시.
정보 제공·교육 목적이며 투자자문이 아닙니다.
