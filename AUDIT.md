# stock-report 코드 진단 보고서

작성일: 2026-07-29 · 대상 커밋: `0c98a6b` · 범위: 저장소 전체

---

## 수정 진행 상황 (2026-07-29 기준)

| 단계 | 상태 | 비고 |
|---|---|---|
| 1. 토큰 회전 | ⚠️ **사용자 조치 대기** | 코드에서는 제거 완료. 콘솔 재발급은 사람이 해야 함 |
| 2. 비밀정보 env 이전·매니페스트·위생 | ✅ 완료 | P0-4 부분 해소, P3-2 해소 |
| 3. P0-1·2·3 | ✅ 완료 | 실행 검증 완료 |
| 4. 배포 정상화 | ✅ 완료 (미배포) | P0-5·6·7, P3-1 해소. **푸시 전 GitHub Secrets 등록 필요** |
| 5. 실패 전파 계약 | ⬜ 미착수 | P0-8, P1-5, P2-1~5 |
| 6. 명백한 정확성 버그 | ⬜ 미착수 | P1-1·6·7, P2-7 |
| 7. 판단 필요 항목 | ⬜ 미착수 | P1-2·3·4·8 |

아래 본문은 **진단 시점의 원본 기록**이며 수정 여부와 무관하게 유지한다.

---

## 0. 요약

**이 시스템은 조용히 고장나 있다.** 발견된 문제의 성격이 "느리다"나 "지저분하다"가 아니라, **잘못된 결과를 성공으로 보고한다**는 데 있다.

네 가지가 동시에 성립한다.

1. Gap 리포트의 KOSDAQ 점수는 잘못된 Yahoo 심볼 때문에 **작성 이후 한 번도 반영된 적이 없다**.
2. 수급 조회가 **딱 한 번** 실패하면 프로세스 전체에서 영구 비활성화되어 프리미엄·추천주 섹션이 통째로 빈다.
3. 배포된 GCP VM은 의존성이 설치된 적이 없어 **실행 자체가 불가능**하고, 스케줄러는 아예 기동되지 않는다.
4. 그런데 모든 계층이 실패를 "성공 모양의 빈 결과"로 변환하고 `main.py`는 **항상 exit 0**을 반환한다.

즉 1·2·3 중 무엇이 발생해도 스케줄러 로그에는 `✅ 리포트 생성 성공!`이, GitHub Actions에는 초록색이, 텔레그램에는 "발송 성공"이 남는다. **장애를 감지할 신호가 시스템 어디에도 없다.**

| 심각도 | 건수 | 성격 |
|---|---|---|
| 🔴 P0 — 지금 깨져 있음 | 9 (+1) | 기능 무동작, 보안 노출, 배포 불능 |
| 🟠 P1 — 잘못된 값 산출 | 8 | 필터 우회, 단위·기준 불일치, 무음 영점화 |
| 🟡 P2 — 발송 실패를 성공으로 보고 | 7 | 미도달 리포트가 성공으로 집계 |
| 🟢 P3 — 운영·위생 | 8 | 폰트, 산출물 추적, 로깅, 문서, 성능 |

`검증됨` 표시가 붙은 항목은 감사 도구의 보고와 별개로 해당 파일을 직접 열어 확인했다.

---

## 1. 🔴 지금 깨져 있는 것 (P0)

### P0-1. KOSDAQ 점수가 처음부터 동작하지 않음 `검증됨`

`report_generator.py:704-705`

```python
KOSPI200_TICKER = "KOSPI200.KS"
KOSDAQ150_TICKER = "KQ150.KS"
```

둘 다 존재하지 않는 Yahoo 심볼이다. **같은 파일이 Market Summary에서는 올바른 심볼을 쓰고 있다** — `_ms_load_index("^KS200")` (`:2177`), `_ms_load_index("^KQ11")` (`:2186`).

실패 경로:

1. `safe_fetch`가 예외를 삼키고 `None` 반환 (`:731-732`)
2. `compute_kosdaq_signals`가 `if df is None` 분기를 타서 전량 NaN/0 반환 (`:833-837`)
3. `score_kosdaq`의 "코스닥 전용(핵심)" 입력 3개가 전부 죽어 **최대 36점이 산정에서 빠짐** (`:1024-1039`)
4. `compute_global_signals`의 `KOSPI200_ret_d`도 항상 NaN (`:822-824`)

**결과:** 코스닥 급등/급락 게이지는 미국 글로벌 지표만으로 채점되고, 지표 상세 표에는 `NaN`이 그대로 렌더링된다(`:1153`). 오류는 어디에도 표시되지 않는다.

> 참고: `^KQ11`은 KOSDAQ150이 아니라 코스닥 **종합**지수다. Yahoo에 신뢰할 만한 KOSDAQ150 심볼이 없으므로, 프록시로 수용하고 라벨을 바꾸든지 `fdr.DataReader('KQ150')`로 바꾸든지 선택이 필요하다.

### P0-2. 수급 조회가 1회 실패로 영구 비활성화 `검증됨`

`report_generator.py:444-465`

```python
global _PYKRX_INVESTOR_AVAILABLE
if _PYKRX_INVESTOR_AVAILABLE is False:
    return 0, 0
...
except Exception as e:
    if _PYKRX_INVESTOR_AVAILABLE is None:
        print(f"[WARNING] pykrx 투자자별 순매수 조회 실패, ...: {e}")
    _PYKRX_INVESTOR_AVAILABLE = False
    return 0, 0
```

두 개의 결함이 겹쳐 있다.

- **모듈 전역이라 리셋되지 않는다.** KRX가 한 종목에서 일시적으로 500을 뱉으면 그 실행의 나머지 전 종목이 `(0, 0)`을 받는다. `main()`은 네 리포트를 한 프로세스에서 실행하므로(`main.py:154-169`) 오염이 전체로 퍼진다.
- **경고가 거의 출력되지 않는다.** 1번 종목이 성공해 플래그가 `True`가 된 뒤 2번 종목이 실패하면, `if _PYKRX_INVESTOR_AVAILABLE is None` 조건이 거짓이라 **아무것도 출력되지 않고** 조용히 비활성화된다.

**결과:** `is_premium = (from_low < MAX_FROM_LOW and net_f > 0 and net_i > 0)` (`:1428`)에서 `net_f`, `net_i`가 0이므로 **항상 False**. 프리미엄·추천주 섹션이 "종목이 없습니다"로 렌더링되고, `premium_count: 0`이 메타데이터에 담긴 채 성공 발송된다. 데이터 소스 전면 장애와 "오늘은 조건 충족 종목이 없음"이 **구분 불가능하다.**

추가로 `"외국인순매수(억)": net_f / 1e8` (`:1447`)은 조회 불가를 화면에 **`0.0`(순매수 없음)** 으로 표시한다.

### P0-3. 거래일 조회 무한 루프 `검증됨`

`report_generator.py:2277-2292`

```python
while len(days) < n_days:
    if d.weekday() < 5:
        try:
            if not stock.get_market_ohlcv_by_date(ds, ds, "005930").empty:
                days.append(ds)
        except Exception:
            pass          # ← 전부 삼킴
    d -= timedelta(days=1)
```

반복 상한도, 실패 카운터도 없다. KRX가 차단되거나 레이트리밋에 걸리면 모든 호출이 예외를 던지고 `days`는 영원히 늘지 않으며, **평일 하나당 HTTP 요청 1회씩 과거로 무한히 거슬러 올라간다.** `generate_market_supply_report`의 `try/except`는 예외가 아니라 행(hang)이므로 잡을 수 없다. 레이트리밋 응답이 요청 폭주를 유발하는 유일한 경로이기도 하다.

`stock.get_market_ohlcv_by_date(start, end, "005930").index` **한 번**이면 같은 결과를 얻는다(휴장일 처리도 덤으로 정확해진다).

### P0-4. 라이브 자격증명이 공개 저장소에 커밋됨 `검증됨`

| 자격증명 | 위치 | 비고 |
|---|---|---|
| Slack webhook URL | `config.py:49` | |
| Slack bot token | `config.py:52`, `test_push_notification.py:4` | 2개 파일 중복 |
| Slack channel ID | `config.py:55`, `test_push_notification.py:5` | |
| Telegram bot token | `config.py:61`, `get_chat_id.py:6`, `get_group_chat_id.py:3` | **3개 파일 중복** |
| Telegram chat ID | `config.py:64` | |

가중 요인:

- **`__pycache__/config.cpython-313.pyc`가 git에 추적되고 있다**(`git ls-files`로 확인). 같은 토큰 문자열을 포함한다. `.gitignore:2`에 `__pycache__/`가 있지만 **이미 추적 중인 파일에는 적용되지 않으므로**, `config.py`에서 문자열을 지워도 저장소에서 사라지지 않는다.
- 저장소는 GitHub Pages를 서비스하는 **공개** 저장소다(`jkkim74.github.io/stock-report`).
- 텔레그램 토큰이 3곳에 있어 일부만 수정하면 동작하는 사본이 남는다. `get_chat_id.py:5`("재발급받은 새 토큰"), `get_group_chat_id.py:3`("새로 발급받은 토큰") 주석은 **이미 한 번 회전이 있었고 구 토큰이 이력에 남아 있음**을 보여준다.
- `.env` 메커니즘(`config.py:10-26`)은 존재하지만 KRX 자격증명에만 쓰이고, 발송 자격증명은 전부 우회한다.
- `deploy.yml:25-29`가 `config.py`를 포함한 저장소 전체를 VM으로 rsync하므로 VM에도 평문으로 존재한다.

### P0-5. 배포된 VM에 의존성이 설치되지 않음

`.github/workflows/deploy.yml:35`

```yaml
source venv/bin/activate || python3 -m venv venv
```

두 경우 모두 실패한다.

- **최초 실행:** `venv/`가 없어 `source`가 실패 → `||`가 발동해 `python3 -m venv venv`로 **빈 venv를 생성**. 그러나 활성화하지 않는다(`||` 분기는 생성만 한다). 따라서 `:37`의 `python`은 **시스템 인터프리터**다.
- **이후 모든 실행:** `venv/bin/activate`가 존재하므로 `source`가 성공하고 `||`는 발동하지 않는다. `:37`의 `python`은 **pip와 setuptools밖에 없는 빈 venv**의 인터프리터다.

워크플로 어디에도 `pip install`이 없고, 설치할 `requirements.txt`도 없다. 2회차 배포부터는 `report_generator.py:18`에서 `ModuleNotFoundError: No module named 'numpy'`로 **`main.py` 로직이 한 줄도 실행되지 않는다.**

그런데 `set -e`가 없고 `nohup ... &`로 백그라운드에 던지므로 SSH 세션은 0으로 종료된다. **워크플로는 앱이 실행됐는지와 무관하게 항상 초록색이다.**

부수 문제: `source`는 bashism이다. VM 사용자의 로그인 셸이 `dash`면 `command not found`가 난다. `:37`의 `python`도 Ubuntu 20.04+ 에는 기본 설치되지 않는다(`python3`여야 함).

### P0-6. 스케줄러가 기동되지 않음 — 정해진 시각에 아무것도 실행되지 않음

`.github/workflows/deploy.yml:36-37`

```yaml
pkill -f main.py || true
nohup python main.py > logs/app.log 2>&1 &
```

`main.py`는 **1회성 배치**다(`main.py:220-222` → 리포트 4개 생성 → 요약 출력 → 프로세스 종료). 서버가 아니다.

- `nohup ... &`는 1회성 스크립트를 데몬화하는 의미 없는 처리다.
- `pkill -f main.py`는 대개 죽일 대상이 없고, 매칭될 경우에는 **생성 중인 리포트를 중간에 죽여** 잘린 HTML을 남긴다(`notifiers.py:330`). `-f`는 전체 명령줄을 매칭하므로 `main.py` 문자열을 포함한 무관한 프로세스(에디터, 다른 배포의 ssh)까지 잡는다.
- **실제 데몬인 `stock_report_scheduler.py`는 워크플로에서 실행되지 않는다.** 저장소에 crontab도 systemd 유닛도 없다.

**결과: VM은 git push 할 때마다 한 번씩, 임의의 시각에 리포트를 만들고, 정해진 시각에는 아무것도 하지 않는다.** 장 마감 후 배포라는 제품의 핵심이 프로덕션에서 성립하지 않는다.

### P0-7. `rsync --delete`가 VM 상태를 파괴하고 `.env`가 도달하지 않음

`.github/workflows/deploy.yml:25-27`

```yaml
rsync -avz --delete \
  --exclude 'venv' \
  --exclude '.git' \
```

- `venv`는 제외되어 살아남는다 — 이것이 P0-5의 "빈 venv가 영구히 유지되는" 이유다.
- **`logs/`는 보호되지 않는다.** 저장소가 로그 6개를 추적하므로 `logs/`가 소스 트리에 존재하고 rsync가 진입한다. VM이 만든 `logs/app.log`(`:37`의 유일한 출력)는 "여분 파일"로 **매 배포마다 삭제**된다. 동시에 2025년 12월의 개발 머신 로그가 덮어씌워진다.
- 생성된 리포트도 삭제된다. `LOCAL_FILE_CONFIG["output_dir"] = "."`(`config.py:82`)와 `reports/`(`notifiers.py:93`) 모두 rsync 대상 내부다.
- **`.env`는 gitignore되어 있어 업로드되지 않고, 수동으로 SCP해도 다음 배포에서 `--delete`가 지운다.** 워크플로에 `.env` 프로비저닝 단계가 없다.

`.env` 없을 때의 연쇄:

```
KRX_ID/KRX_PW 미설정 (config.py:14 조기 반환)
  → 익명 세션 반환 (report_generator.py:199-205)
  → KRX가 "LOGOUT" 응답
  → 재시도는 같은 환경변수로 가드되어 건너뜀 (:247)
  → RuntimeError (:250)
  → Naver 폴백 (:305-314)
  → bs4 / lxml 필요 — 어떤 매니페스트에도 없음
  → 전 리포트 None → main.py:79가 "생성 실패" 4번 출력 → exit 0
```

**VM에서의 실패 양상: 시장 데이터 전무, 무음, 종료코드 0.**

### P0-8. 종료코드가 항상 0 — 장애 감지 불가

`main.py` 전체에 `sys.exit` 호출이 없다(`notifiers.py`, `stock_report_scheduler.py`도 마찬가지). `main()`은 `:174`에서 `🏁 전체 작업 완료 - 성공: 0/4`를 출력하고 그대로 끝난다 → **exit 0**.

파급:

- `stock_report_scheduler.py:40-41` — `if result.returncode == 0: logging.info("✅ 리포트 생성 성공!")`. 4개 전부 실패해도 성공으로 기록된다. `:45-47`의 else 분기는 파이썬 레벨 크래시가 아닌 한 도달 불가능하다.
- `run_stock_report.bat:39-45`의 `%ERRORLEVEL%` 검사도 동일하게 무의미하다.
- `main.py:146-148` — notifier 생성 실패 시 출력 후 `return`. 역시 exit 0이고 리포트는 한 개도 시도되지 않는다.
- **"리포트가 나가지 않았다"를 알려주는 신호가 시스템 어디에도 없다.**

또한 `process_and_send_report`(`:61-133`)는 세 가지 서로 다른 상황에 모두 `False`를 반환한다 — 생성기가 `None` 반환(`:78-80`, "조건 미충족 또는 데이터 없음"으로 뭉뚱그림), 발송 실패(`:125-127`), 예외(`:129-133`). 호출부는 불리언만 세므로(`:154-170`) **휴장일과 토큰 만료가 동일한 출력 `성공: 0/4`를 낸다.**

### P0-9. 스케줄이 장중이고 타임존이 없음

`stock_report_scheduler.py:57-60`

```python
# 매일 오후 3시 40분에 실행 (장마감 후)
schedule.every().day.at("14:30").do(run_stock_report)
schedule.every().day.at("20:05").do(run_stock_report)
```

- **주석은 15:40, 코드는 14:30** — KRX 정규장 마감은 15:30이므로 14:30은 **장중**이다. 이 실행은 미완성 일중 데이터로 리포트를 만들어 텔레그램으로 발송한다.
- `:70`의 로그는 `⏰ 실행 시간: 매일 20:05`라고 출력한다 — 잡은 두 개인데 하나만 알린다. 주석 처리된 대안(`:63-67`)은 또 다른 시각(15:40)을 쓴다.
- **타임존이 없다.** `schedule`은 호스트 로컬 시각을 쓰고 이 파일에는 `pytz`/`ZoneInfo`가 없다(`Asia/Seoul`은 `report_generator.py:65`에만 등장). GCP VM 기본값은 **UTC**이므로 14:30 UTC = **23:30 KST**, 20:05 UTC = **익일 05:05 KST**에 발화한다. 후자는 날짜 경계를 넘어 기준일까지 틀어진다.
- **주말·공휴일에도 매일 실행된다.** 거래일 가드가 없어 토·일에 금요일 데이터 사본이 중복 발송된다. 평일 한정 대안은 주석 처리되어 있다.
- 프로세스 감시가 없다. `while True` 단일 스레드(`:79-81`)이고 예외가 루프를 벗어나면 스케줄러가 그대로 죽는다. 재시작 장치가 저장소에 없다.
- `subprocess.run`(`:30-37`)에 `timeout=`이 없어 `main.py` 내부 HTTP 행 하나가 **스케줄러를 영구 정지**시킨다.
- 로그 파일명이 임포트 시점에 고정된다(`:16`). 한 달 띄워두면 모든 날짜의 출력이 시작일 파일 하나에 쌓인다.

---

## 2. 🟠 잘못된 값이 나오는 것 (P1)

### P1-1. NaN이 모든 필터를 우회 — 수정 대비 효과 최대

`report_generator.py:391-405`

```python
close = safe_float(row["종가"]);  mcap = safe_float(row["시가총액(억원)"]) * 1e8
if close <= 0 or mcap <= 0: continue
if np.isnan(value) or np.isnan(change): continue
...
if mcap < ANALYSIS_CONFIG["MIN_MCAP"]: continue
```

`value`와 `change`는 NaN 검사를 하는데 **`close`와 `mcap`은 하지 않는다.** `nan <= 0`은 False, `nan < 5e11`도 False이므로 파싱 실패한 시가총액·종가를 가진 행이 **모든 필터를 통과한다.** 두 폴백 경로 모두 그 자리에서 NaN을 만든다(`:291-292`, `:329-340`).

**결과:** 시총 5000억 미만이나 가격 미상 종목이 리포트에 진입하고, `style_row`(`:541`)가 `f"{nan:,.1f}"`로 **문자열 `"nan"`** 을 렌더링한다. `gap`/`from_low`(`:1421-1422`)를 통해 52주 관련 컬럼 전체로 NaN이 전파된다.

`np.isnan` 검사에 두 변수를 추가하는 한 줄 수정이다.

### P1-2. Naver 폴백의 거래대금이 다른 값

`report_generator.py:330-331`

```python
volume = _naver_to_number(cols[9])          # 거래량 (주)
value  = close * volume if ... else np.nan  # ≈ 거래대금
```

pykrx 경로는 거래소가 산출한 **실제 거래대금**(체결가×수량 총합, 즉 거래량×VWAP)을 쓴다(`:375`). Naver 경로는 **종가**×거래량으로 대체한다. `MIN_CHANGE` 5%를 통과한 종목은 정의상 종가가 당일 고가 근처이므로 **체계적으로 과대평가**된다(통상 1~4%, 상한가 후 반락일에는 훨씬 더). `MIN_VALUE`가 1000억 하드 컷오프(`:402`)이므로 **경계 종목의 진입 여부가 어느 폴백이 발동했는지에 따라 달라지고, 리포트에는 그 사실이 표시되지 않는다.**

같은 블록에서 `cols[9]`는 Naver `sise_market_sum` 테이블의 **하드코딩 위치 인덱스**다. 이 테이블의 컬럼 구성은 사용자 설정으로 바뀐다. Naver가 컬럼 순서를 바꾸면 `volume`이 PER이나 ROE가 되고 거래대금은 무의미해진다. `len(cols) < 10`(`:320`)이 유일한 가드다.

### P1-3. 52주 최고가와 최저가의 기준이 다름

`report_generator.py:423-427`

```python
df = df[(df["종가"] > 0) & (df["저가"] > 0)]
return float(df["종가"].max()), float(df["저가"].min())
```

독스트링은 최고가/최저가라고 하지만 고점은 **종가** 기준, 저점은 **저가** 기준이다. 범위의 양 끝이 서로 다른 기준이라 `52주괴리(%)`(`:1421`, 최대 종가 대비)와 `52주최저대비(%)`(`:1422`, 최저 저가 대비)를 비교할 수 없고, `MAX_FROM_LOW = 300.0` 필터도 어느 한쪽 기준으로 튜닝되었을 것이다. 종가 기준 고점은 `is_52w_high`(`:1420`)를 **장중 52주 신고가를 넘지 않은 날에도** 발동시킨다.

### P1-4. Gap 리포트의 "N시간" 수익률이 전부 한 칸씩 어긋남

`report_generator.py:734-739, 773, 784`

```python
def last_close(df, n=1): return float(df["Close"].iloc[-n])
...
ret_4h = pct(last_close(df_h), last_close(df_h, 4))   # iloc[-1] vs iloc[-4]
ret_3h = pct(last_close(btc_h), last_close(btc_h, 3)) # iloc[-1] vs iloc[-3]
```

`interval="60m"`에서 `iloc[-1]`과 `iloc[-4]` 사이는 **3봉 = 3시간**이지 4시간이 아니다. BTC는 **2시간**이다(일봉 변형인 `last_close(df, 2)`는 1봉 = 1일이므로 정상). 4시간을 원하면 `iloc[-5]`여야 한다.

이 값에 걸린 임계값(`ES_4h >= 0.8`, `NQ_4h >= 1.2`, `BTC_3h >= 4`, `:910-932`)은 더 긴 창을 가정해 잡혀 있으므로 **야간 프록시 드라이버가 체계적으로 덜 발동한다.** 사용자에게 보이는 라벨(`"{name} 선물 최근 4시간 변화"`, `:774`)도 틀렸다.

> **2026-07-29 실측 정정 — 실제로는 신호가 아예 없다.**
> `fetch_with_fallback(..., period="1d", interval="60m")`가 ES·NQ 모두 **2봉**만 반환한다.
> `iloc[-4]`는 존재하지 않아 `last_close`가 예외를 잡고 NaN을 반환하므로, `ES_ret_4h`와
> `NQ_ret_4h`는 **항상 NaN**이고 야간 프록시 드라이버는 P0-1의 KOSDAQ 신호와 마찬가지로
> **한 번도 발동한 적이 없다.** 생성된 HTML에 `NaN` 문자열이 그대로 노출되는 원인이기도 하다.
> 즉 이 항목은 "한 칸 어긋남"이 아니라 **P0급 무동작**이다.
> 수정하려면 `period`를 늘려 봉 수를 확보해야 하는데(`"1d"` → `"5d"` 등), 그러면 창 길이가
> 실제로 바뀌므로 `:910-932`의 임계값 재튜닝이 함께 가야 한다. 그래서 7단계(판단 필요)로 둔다.

### P1-5. Supply 리포트의 수급 실패가 무음으로 전 종목을 0으로 만듦

`report_generator.py:2394-2409`

```python
except Exception:
    vol_raw = pd.DataFrame()
if vol_raw.empty:
    inst = pd.Series([0.0] * len(calendar), index=calendar)
    fore = pd.Series([0.0] * len(calendar), index=calendar)
```

→ `flows = (inst + fore) * closes` = 0 (`:2412`) → `tot_1/3/5` = 0 → 모든 `pct*` = 0 → `strength` = 0 → `premium_flag = bool((last3 > 0).all())` = **False** (`:2432`).

**결과:** 프리미엄 섹션(`_flag_premium` 필요), Fast 섹션(`1일_순매수/거래대금(%) >= 3` 필요), 중장기 관심 섹션(`3일_순매수/시총(%) >= 0.3` 필요)이 **전부 빈다.** 순수 가격 필터인 과열 섹션만 채워진다. 리포트는 `premium_count: 0`으로 성공 발송된다. 두 블록 위의 FDR 실패는 최소한 출력이라도 하는데(`:2375`) 이 `except`는 완전히 무음이다.

또한 **Supply에는 폴백이 아예 없다.** `_SupplyKrxJson.get_all`이 모든 예외를 잡아 빈 프레임을 반환하고(`:2363-2365`) `:2783`에서 `return None`이 된다. 프리미엄의 3단 폴백(pykrx → KRX direct → Naver)과 달리 KRX가 한 번 삐끗하면 리포트 전체가 사라진다.

### P1-6. Gap·Market Summary의 기준일이 데이터 날짜와 다름

`report_generator.py:1573`, `:2209`

```python
trade_date = datetime.now(TZ).strftime("%Y%m%d")
```

두 리포트가 **벽시계 날짜**를 기준일(및 파일명 `:1579`/`:2224`)로 찍는데, 실제 데이터는 yfinance의 `df.iloc[-1]` — 주말·공휴일이나 장 시작 전 실행 시 **직전 세션**이다. Premium과 Supply는 `get_trade_date()`를 올바르게 쓴다. 스케줄러가 KRX 마감 전에 돌면(P0-9의 14:30 잡) 기준일이 데이터가 커버하지 않는 날이 된다.

### P1-7. 우선주 제외가 `우B` 계열을 놓침

`report_generator.py:2352-2354`

```python
out["종목명"].str.contains("ETF|ETN|스팩|SPAC", na=False) |
out["종목명"].str.endswith("우", na=False)
```

`endswith("우")`는 `삼성전자우`는 잡지만 `현대차2우B`, `대신증권우B`, `한화3우B` 등은 놓친다. 이들은 거래가 얇고 변동성이 커 등락률·회전율 필터에 자주 걸리므로 **네 섹션 모두로 새어 들어온다.** `우[0-9]*B?$` 형태의 정규식이 의도한 바다.

### P1-8. 선취매강도점수가 포화되어 정렬과 강조가 무의미

`report_generator.py:2435-2441`

```python
strength_raw = pct3_mcap*40 + pct1_mcap*30 + pct5_mcap*20 + (10 if premium_flag else 0)
strength = round(min(max(strength_raw, 0.0), 100.0), 2)
```

`pct3_mcap`은 통상 0.1~2 범위의 퍼센트값이라, 3일 순매수/시총이 약 1.5%를 넘으면 **정확히 100.0**에 고정되고, 순매도 종목은 **정확히 0.0**에 고정된다. 이 점수가 네 섹션의 **정렬 키**(`:2842`)이고 `head(30)` 절단 기준(`:2476`)이므로, 동점 덩어리 안에서의 "상위 30"은 사실상 행 순서다. `_supply_style_name`(`:2466`)은 `>= 100.0`에서만 빨간색을 칠하므로 **빨강은 "가장 강함"이 아니라 "잘렸음"을 뜻한다.**

---

## 3. 🟡 발송했다는데 실제로는 안 간 것 (P2)

### P2-1. 텔레그램: 미리보기만 성공해도 발송 성공

`notifiers.py:453-462`

```python
success_count = sum(1 for _, result in results if result["success"])
if success_count > 0:
    return {"success": True, "message": f"Telegram 발송 완료 ({success_count}/{total_count} 성공)", ...}
```

`send_preview=True`, `send_as_file=True`(`config.py:67-68`) 상태에서 미리보기 텍스트는 올라가고 `sendDocument`가 실패하면(용량 초과, 429, 네트워크) `success_count == 1`이므로 **`success: True`**. `main.py:120-124`가 "🚀 발송 성공"을 출력한다. 구독자는 **"📎 상세 리포트 파일을 전송합니다..."만 받고 파일은 받지 못하며**, 로그에는 실패로 남지 않는다.

45MB 제한(`:568-575`)은 `TelegramNotifier`에서만 올바르게 검사되고, 그 검사가 **미리보기를 이미 보낸 뒤**에 일어난다. `TelegramChannelNotifier._send_channel_file`(`:722-748`)에는 **용량 검사가 아예 없다.**

### P2-2. 채널 발송: 파일 결과를 계산해서 버림

`notifiers.py:700-706`

```python
file_result = self._send_channel_file(bot_token, channel_id, report_data)
return {"success": True, "message": "Telegram 채널 발송 완료", ...}
```

`file_result`를 한 번도 검사하지 않는다. 그리고 `_send_channel_file` 자신도 HTTP 상태를 확인하지 않는다(`:737` — 응답 객체를 버리고 `return True`). 400/403/413도 성공이다. **두 결함이 합쳐져 파일이 하나도 전달되지 않아도 완전 성공으로 보고된다.**

덧붙여 이 notifier는 현재 설정으로는 애초에 쓸 수 없다 — `:666`이 `-100`으로 시작하지 않는 chat_id를 거부하는데 `config.py:64`는 `"-5059622484"`(일반 그룹 ID)이다.

### P2-3. Composite: 자식 하나만 성공해도 전체 성공

`notifiers.py:387` — `"success": success_count > 0`.

`COMPOSITE_MODES = ["telegram", "local_only"]`(`config.py:78`)에서 텔레그램 발송이 완전히 실패해도 로컬 파일만 써지면 전체 성공이다. `main.py:120`이 "발송 성공"을 출력하고 파이프라인은 초록인데 **구독자는 아무것도 받지 못한다.** 사용자에게 보이는 유일한 채널이 텔레그램인 팬아웃에서 "하나라도"는 잘못된 정족수다.

### P2-4. GitHub Pages: 커밋 실패를 삼키고 push를 건너뛴 뒤 성공 반환

`notifiers.py:124-141`

```python
try:
    subprocess.run(["git","commit","-m",...], check=True, capture_output=True)
except subprocess.CalledProcessError:
    print("[GitHub Pages] 변경사항 없음 - 커밋 생략")
    return          # ← push를 통째로 건너뜀
```

`git commit`은 "변경사항 없음" 외에도 여러 이유로 비정상 종료한다 — `user.email` 미설정(새 VM에서 흔함), 훅 실패, 인덱스 락. **전부 "변경사항 없음"으로 삼켜지고** `return`이 push를 건너뛴다. 그런데 `send()`는 Slack webhook이 성공했으므로 여전히 `success: True`를 반환한다(`:74-78`).

**실패 양상: Slack이 404가 나는 `https://jkkim74.github.io/stock-report/reports/<파일>.html` 버튼을 게시한다.** 게다가 이전 실행이 커밋은 했는데 push에 실패했다면, 이후 어떤 실행도 그것을 push하지 않아 **백로그가 영구히 막힌다.**

부수: `send()`의 성공 여부가 **Slack 알림에만** 좌우된다(`:75`). Pages 업로드 성공은 성공 판정에 기여하지 않으므로 Slack이 죽으면 정상 발행이 실패로 보고된다.

### P2-5. 헤드리스 VM에서 파일 저장 성공이 실패로 뒤집힘

`notifiers.py:335-346`

```python
if LOCAL_FILE_CONFIG["open_browser"]:
    webbrowser.open("file://" + os.path.abspath(file_path))
```

GCP VM에는 브라우저가 없어 `webbrowser.Error`가 발생하고, `:345`의 `except Exception`이 이를 잡아 `{"success": False, "message": "로컬 저장 실패: ..."}`로 만든다. **`:330-331`의 쓰기는 이미 성공했는데도** 실패로 보고된다. composite 모드에서 `local_only`가 서버에서 영구히 "실패"하는 원인이다.

### P2-6. 발송 HTTP 호출 전체에 타임아웃 없음

`notifiers.py:549, 598, 641, 694, 737` 및 Slack webhook(`:207`) — 전부 맨 `requests.post`다. 비교하자면 `report_generator.py:306`은 `timeout=15`를 넘긴다. 연결이 멈추면 `main.py`가 무한 대기하고, 스케줄러의 `subprocess.run`(`stock_report_scheduler.py:30-37`)에도 `timeout=`이 없어 **업로드 하나가 멈추면 스케줄러가 영구 정지하고 이후 모든 잡이 조용히 실행되지 않는다.**

재시도도 없다. 텔레그램은 429 + `retry_after`를 일상적으로 반환하는데, `:604-610`은 이를 영구 실패와 동일하게 처리하고 `retry_after`를 읽지 않는다.

### P2-7. Slack 문구가 실제 기준과 불일치

`notifiers.py:164`, `:283` — `"*분석 기준*\n시가총액 ≥ 3000억"`. 실제 `ANALYSIS_CONFIG["MIN_MCAP"]`은 `500_000_000_000` = **5000억**(`config.py:32`, 커밋 `adda27d`에서 변경). 구독자에게 잘못된 스크리닝 기준을 안내하고 있다.

---

## 4. 🟢 운영·위생 (P3)

### P3-1. Linux에서 차트 한글이 전부 깨짐

`report_generator.py:68` — `matplotlib.rcParams["font.family"] = "Malgun Gothic"`를 무조건 지정한다. Malgun Gothic은 Windows 번들 폰트라 Ubuntu 이미지에 없다. 크래시가 아니라 **한글이 전부 두부(□□□)로 렌더링**되고, 그 이미지가 base64로 HTML에 박제되어(`:1104`, `:1657`) 텔레그램으로 발송된다. 차트에는 한글이 실제로 들어간다 — `ax.set_xlabel("0(낮음)  ←  점수  →  100(매우 높음)")` (`:1092`), `set_yticklabels`(`:1090`), `set_title`(`:1093`). 부수적으로 `findfont` 경고가 텍스트 객체마다 발생해 로그가 폭증한다.

### P3-2. 산출물이 git에 추적됨

| 추적 중 | 개수 |
|---|---|
| `__pycache__/*.pyc` | 3 |
| `logs/*.log` | 6 (2025-12-13/15) |
| `reports/*.html` | 2 |

`.gitignore`는 `out/`을 무시하는데 **프로덕션에서 `out/`에 쓰는 코드가 없다**(`report_generator.py:2876`의 `__main__` 테스트 경로 전용). 실제 산출 경로 3곳은 전부 무시되지 않는다 — `reports/`(`notifiers.py:93`), 저장소 루트 `*.html`(`config.py:82`), `logs/*.log`.

### P3-3. 커밋 이력이 읽을 수 없음

29개 커밋 중 **18개**가 `notifiers.py:126`이 생성한 `"Add AI premium stock report ..."`다. 그런데 그중 실제로 HTML을 추가한 커밋은 3개뿐이고, 나머지 15개는 `git add .`가 로그·`.pyc`·소스 수정을 쓸어담은 것이다. **실제 소스 변경이 동일한 리포트 제목의 커밋에 묻혀 있다.**

### P3-4. 로깅이 사실상 없음

메시지 약 124개가 전부 `print()`다(`report_generator.py` 47, `notifiers.py` 41, `main.py` 36).

`report_generator.py:43-48`은 `logging.basicConfig`를 설정하고 **한 번도 호출하지 않는다** — 2,900줄 전체에서 `logging.info/warning/error` 호출이 0건이다. 더구나 `logging.raiseExceptions = False`는 **프로세스 전역**으로 로깅 내부 오류를 삼킨다(서드파티 라이브러리 포함).

유일한 실제 로깅 설정은 `stock_report_scheduler.py:12-19`인데, 그 모듈은 VM에서 실행되지 않는다(P0-6). 심각도는 이모지로 문자열 안에 인코딩되어 있어 레벨별 필터링이 불가능하고, 회전·보존 정책이 없다.

### P3-5. `run_stock_report.bat`이 완전히 죽어 있음

`:20` `cd /d "D:\workspace\stockReport"` — 존재하지 않는 경로(이 저장소는 `D:\workspace2\stock-report`). `cd` 실패를 검사하지 않아 호출자의 CWD에서 계속 진행한다.
`:36` `python stock_report.py` — 존재하지 않는 파일. **매 실행마다 동일하게 실패**하며 아무도 보지 않는 로그 파일에만 기록된다. Windows 작업 스케줄러에 걸려 있다면 이름 변경 시점부터 계속 무동작이었다.

부수: `:14-16`이 매 실행마다 `git config --global`로 **사용자의 전역 git 설정을 변경**한다.

### P3-6. 죽은 코드 / 중복

- `config.py:41` — `local_repo_path`가 존재하지 않는 Windows 경로. **텔레그램 전용으로 확정했으므로 `github_pages` 모드와 `GitHubPagesNotifier` 자체가 정리 대상이다** (P2-4도 함께 사라진다).
- `notifiers.py:395-407` `EmailNotifier` — 하드코딩 `success: False` 스텁, `create_notifier`에서 도달 불가.
- `get_chat_id.py` / `get_group_chat_id.py` — 거의 동일한 일회성 도구. 둘 다 토큰을 stdout에 출력하고, `get_chat_id.py:63-70`은 실제 메시지를 발송하는 부작용이 있다.
- `test_push_notification.py` — 이름과 달리 테스트가 아니다. 단언문이 없고 임포트만으로 실제 Slack 채널에 `<!channel>` 브로드캐스트를 게시한다.
- `report_generator.py:1595-1604` — `generate_etf_report`/`generate_crypto_report` 둘 다 `pass`.
- `notifiers.py:9`/`:413` `import os` 중복, `:412-414`가 파일 중간에 `# 파일 끝부분에 추가` 주석과 함께 삽입.
- `report_type` 문자열 분기가 `main.py:86-113`과 `notifiers.py:479-539`에 이중으로 존재 — 리포트 추가 시 두 곳을 고쳐야 한다.

### P3-7. README가 26바이트 스텁

`# AI Stock Reports Archive` 한 줄. 실제로는 ~3,900줄 파이프라인이다. 설치 방법(설치할 매니페스트 자체가 없음), `.env` 키, `DELIVERY_MODE` 값, 실행 방법, 스케줄, 배포 구조가 전부 빠져 있다. 유일하게 정확한 문서는 `CLAUDE.md`다 — **기계용 문서는 완비되어 있고 사람용 문서가 비어 있는** 상태다.

`.vscode/settings.json:2-3`은 conda를, `deploy.yml:35`는 venv를, 배치 파일은 시스템 python을 가정한다. **환경 모델이 세 가지이고 어느 것도 문서화되어 있지 않다.**

### P3-8. 성능: 전 실행 순차 HTTP 약 370~1150회

재시도·캐싱·레이트리밋이 전혀 없다.

| 단계 | 순차 요청 수 |
|---|---|
| `get_trade_date` × 2 | 2 |
| 프리미엄 기본 목록 | 4 |
| 프리미엄 종목별 (52주 + 수급 + 최근봉) | **3 × N** (N ≈ 10~100) |
| Gap (yfinance) | ~14 |
| Market Summary (yfinance) | ~8 |
| `_supply_get_recent_trading_dates` | ≥7, 실패 시 무한 (P0-3) |
| Supply 종목별 (FDR + 투자자별) | **2 × M** (M ≈ 150~400) |

낭비 3건:

1. `get_52w_stats`(365일)와 `get_recent_ohlcv`(40일)가 **동일 종목의 동일 시계열을 두 번** 조회한다(`:411-442`). 한 번 받아 두 번 자르면 프리미엄 루프 요청의 1/3이 사라진다.
2. `SUPPLY_LIST_MIN_MCAP`(3000억) 필터가 종목별 루프 **뒤**인 `:2813`에 적용되는데 사전 필터(`:2786`)는 `SUPPLY_MIN_MCAP`(1000억)을 쓴다. 1000억~3000억 구간의 종목은 2회씩 요청하고 **전량 버려진다.** 필터를 위로 올리면 결과가 동일하면서 Supply 루프가 30~50% 줄어든다.
3. `_supply_get_recent_trading_dates`가 삼성전자를 하루씩 7~12회 찔러 만드는 달력을 `get_market_ohlcv_by_date(start, end, "005930").index` **한 번**으로 얻을 수 있다.

---

## 5. 권고 수정 순서

각 단계는 독립적으로 배포 가능하고, 끝난 시점에 시스템이 동작 상태로 남는다.

| 순서 | 내용 | 이유 |
|---|---|---|
| 1 | **토큰 회전** (사람이 직접) | 이미 공개 이력에 있어 코드 수정만으로 닫히지 않음 |
| 2 | 비밀정보 env 이전 + `requirements.txt` + 위생 | 단독 배포 가능. 4번이 이 결과물을 필요로 함 |
| 3 | P0-1·2·3 | 각 1~5줄, 인프라 의존 없음. 언제든 배포 가능 |
| 4 | 배포 정상화 | 5번의 전제 |
| 5 | 실패 전파 계약 | 4번 뒤에 해야 함 |
| 6 | 명백한 정확성 버그 | 독립적 |
| 7 | 판단 필요 항목 | 발표 숫자가 바뀌므로 승인 필요 |

**1. 토큰 회전** — Slack webhook 재발급, Slack bot token 재생성, BotFather `/revoke`. **회전만 하고 히스토리 재작성은 권하지 않는다** — 공개 저장소의 clone을 깨뜨리는 대가에 비해, 이미 스크레이핑되었을 구 토큰을 무력화하는 것은 회전으로 충분하다. 저장소를 비공개로 전환할 경우에만 재작성이 의미가 있다. `__pycache__/*.pyc`는 `git rm --cached`로 인덱스에서 제거해야 한다(`.gitignore` 추가만으로는 안 됨).

**2. 비밀정보·매니페스트·위생** — `config.py`의 토큰을 `os.getenv`로 교체(`load_local_env`가 이미 있음), `.env.example` 확장, `requirements.txt` 생성. **`beautifulsoup4`와 `lxml`을 반드시 포함**해야 한다 — 지연 임포트라 눈에 띄지 않지만 폴백 체인의 마지막 단계이고, KRX 인증이 실패하는 순간 VM이 정확히 그 경로를 탄다. 추적 중인 산출물 제거 시 `logs/` 언트래킹은 배포 스크립트의 `mkdir -p logs`와 함께 가야 한다(현재 `> logs/app.log`가 디렉터리 존재에 의존).

**3. P0-1·2·3** — 심볼 2줄 교체, 전역 플래그를 연속 실패 카운터로 교체하고 실패 시 `(0,0)` 대신 `(None, None)` 반환(0은 정상값이라 실패와 구분되지 않는 것이 이 클래스 버그의 뿌리다), 거래일 루프를 1회 호출로 교체. P0-1 수정 후 KOSDAQ 점수가 크게 움직이는 것은 **회귀가 아니라 수정이 동작하는 증거**다.

**4. 배포 정상화** — `pip install -r requirements.txt` 추가, `set -euo pipefail` + 백그라운드 제거, systemd timer(`OnCalendar=Mon-Fri 15:40`, `Persistent=true`) 도입 후 `pkill`/`nohup` 제거, VM에 `timedatectl set-timezone Asia/Seoul`, `.env`는 GitHub Secrets에서 생성해 stdin으로 전달, rsync에 `--exclude '.env' --exclude 'logs' --exclude 'reports'` 추가, matplotlib 폰트 후보 탐색 + `fonts-nanum` 설치. rsync 방식 자체는 유지해도 된다 — 유일한 실질 결함인 `--delete`가 exclude 몇 줄로 해결된다.

**5. 실패 전파 계약** — 여기서부터 종료코드가 의미를 갖는다. **반드시 4번 뒤여야 한다.** 의존성조차 설치되지 않은 VM에서 exit code를 먼저 도입하면 "조용히 초록"이 "항상 빨강"으로 바뀔 뿐 비교 기준이 없다. 핵심은 **"데이터 없음"과 "데이터 소스 장애"를 구분**하는 것이다 — 조건 충족 종목이 없는 한산한 장은 실패가 아니고, 수급 API 전면 장애는 실패다. 네 생성기를 한꺼번에 고칠 필요는 없다. `ReportData`에 선택적 `health` 필드를 추가하면(기본값 `"ok"`) 기존 생성 지점 4곳이 그대로 동작하고 하나씩 적용할 수 있다. notifier 쪽은 "필수 단계가 성공했는가"로 정족수를 바꾼다 — 미리보기는 전달이 아니고 파일이 전달이다.

**6. 명백한 정확성 버그** — NaN 가드 추가(P1-1, 한 줄), 기준일을 `get_trade_date()`로 통일(P1-6), 우선주 정규식(P1-7), Slack 문구를 `ANALYSIS_CONFIG`에서 보간해 재발 방지(P2-7).

**7. 판단이 필요한 항목** — 발표되는 숫자가 바뀌므로 승인이 필요하다.

- **거래대금(P1-2)**: `cols[9]` 위치 인덱스는 **고친다**(테이블 헤더에서 이름으로 조회). 종가×거래량 근사는 **문서화**하고, 폴백이 발동한 실행분을 추정치로 표시한다.
- **52주 기준(P1-3)**: 양쪽 모두 **종가 기준으로 통일**을 권고한다. 종가 기준 고점 자체는 단일 틱 스파이크를 피하는 타당한 선택이고, 결함은 기준을 섞은 것이다. 병합 전 두 방식으로 같은 거래일을 돌려 종목 집합 차이를 확인할 것.
- **3시간/4시간(P1-4)**: **라벨을 고치는 쪽**을 권고한다. 임계값이 실제로 계산되던 3시간 데이터 기준으로 경험적으로 잡혀 있으므로, 창을 늘리면 모든 임계값이 조용히 재튜닝된다. 진짜 4시간을 원하면 `n=5` + `period` 확대 + 임계값 재튜닝을 **별도의 의도된 변경**으로 다루어야 한다.
- **선취매강도점수(P1-8)**: **백분위 순위로 대체**를 권고한다(`rank(pct=True) * 100`). 자기정규화되어 포화가 없고, 정렬이 항상 유효하며, "상위 N%"로 해석 가능하다.

---

## 부록: 확인 방법

```bash
# 추적 중인 산출물
git ls-files | grep -E "pycache|logs/|\.html$"

# 소스에 남은 자격증명
grep -rE "xoxb-|hooks\.slack|[0-9]{10}:AA" --include="*.py" .

# 자동 생성 커밋 비중
git log --oneline | grep -c "Add AI premium stock report"

# 심볼 불일치 (P0-1)
grep -n "KOSPI200.KS\|KQ150.KS\|\^KS200\|\^KQ11" report_generator.py
```
