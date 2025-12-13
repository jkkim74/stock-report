# -*- coding: utf-8 -*-
"""
Master Premium + Pattern + AI Strategy v4
-----------------------------------------
1) 리포트 포함 기본 조건
   - 시가총액 3000억 이상
   - 당일 등락률 5% 이상
   - 당일 거래대금 1000억 이상

2) 프리미엄 추천 종목
   - 52주최저대비(%) < 300%
   - 외국인순매수(억) > 0
   - 기관순매수(억) > 0

3) 관심 종목
   - 기본 조건은 충족, 프리미엄 조건 중 하나 이상 미달

4) 신고가 패턴 (오늘이 52주 신고가인 종목에 대해)
   - 강한 돌파 / 완만한 돌파 / 가짜 돌파(위꼬리) / 돌파 후 급락 / 중립

5) AI 대응 전략 + AI 예상 상승 확률(%)
   - 상단: 오늘의 추천주(프리미엄 + 강한/완만 돌파)
   - 프리미엄 섹션에서는 추천주와 중복되는 종목 제거
   - 각 섹션(추천주/프리미엄/관심) 모두 AI예상상승확률(%) 내림차순 정렬

6) 모바일(스마트폰)에서도 보기 좋은 반응형 디자인 적용
"""
import sys

# Windows 콘솔 UTF-8 인코딩 강제 설정
if sys.platform == 'win32':
    try:
        # Python 3.7+ 방법 (권장)
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        # Python 3.6 이하 호환성
        import io
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer,
            encoding='utf-8',
            errors='replace',
            line_buffering=True
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer,
            encoding='utf-8',
            errors='replace',
            line_buffering=True
        )

import os
import webbrowser
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from pykrx import stock
from tqdm import tqdm
from pytz import timezone

import requests
import json

TZ = timezone("Asia/Seoul")

# 기본 조건 (리포트 포함 기준)
MIN_CHANGE = 5.0                     # 등락률 ≥ 5%
MIN_VALUE  = 100_000_000_000         # 거래대금 ≥ 1000억 (원)
MIN_MCAP   = 300_000_000_000         # 시가총액 ≥ 3000억 (원)

# 프리미엄 조건
MAX_FROM_LOW = 300.0                 # 52주최저대비 < 300%
EPS = 1e-6

# 52주 및 패턴용 기간
LOOKBACK_52W_DAYS = 365
LOOKBACK_PATTERN_DAYS = 40

OUTPUT_DIR = "."

import pdfkit
from slack_sdk import WebClient
import os



import subprocess
import requests
import json
from datetime import datetime
def upload_to_github_and_notify(html_content, trade_date):
    """완전 인코딩 안전 버전"""
    
    # 안전한 출력 함수
    def safe_print(message):
        """인코딩 오류 없이 출력"""
        try:
            print(message)
        except UnicodeEncodeError:
            # 이모지 제거 후 재시도
            ascii_message = message.encode('ascii', errors='ignore').decode('ascii')
            print(f"[SAFE] {ascii_message}")
    
    LOCAL_REPO_PATH = r"D:\workspace\stockReport"
    GITHUB_USERNAME = "jkkim74"
    GITHUB_REPO = "stock-report"
    WEBHOOK_URL = "https://hooks.slack.com/services/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"
    
    try:
        # 1. 경로 확인
        if not os.path.exists(LOCAL_REPO_PATH):
            safe_print(f"[ERROR] 저장소 경로를 찾을 수 없습니다: {LOCAL_REPO_PATH}")
            return False
        
        # 2. .nojekyll 파일 생성
        nojekyll_path = os.path.join(LOCAL_REPO_PATH, ".nojekyll")
        if not os.path.exists(nojekyll_path):
            with open(nojekyll_path, "w") as f:
                f.write("")
            safe_print("[SUCCESS] .nojekyll 파일 생성")
        
        # 3. HTML 파일 저장
        reports_dir = os.path.join(LOCAL_REPO_PATH, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        
        filename = f"report_{trade_date}.html"
        file_path = os.path.join(reports_dir, filename)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        safe_print(f"[SUCCESS] HTML 파일 생성: reports/{filename}")
        
        # 4. Git 작업 (인코딩 안전 처리)
        safe_print("[INFO] GitHub에 업로드 중...")
        
        # Pull (충돌 방지)
        subprocess.run(
            ["git", "pull", "origin", "main"], 
            cwd=LOCAL_REPO_PATH,
            capture_output=True,
            check=False
        )
        
        # Add
        subprocess.run(
            ["git", "add", "."], 
            cwd=LOCAL_REPO_PATH,
            check=True
        )
        
        # Commit (nothing to commit 안전 처리)
        try:
            subprocess.run(
                ["git", "commit", "-m", f"Add AI premium stock report {trade_date}"], 
                cwd=LOCAL_REPO_PATH,
                check=True,
                capture_output=True
            )
            safe_print("[SUCCESS] 커밋 완료")
            
            # Push
            subprocess.run(
                ["git", "push", "origin", "main"], 
                cwd=LOCAL_REPO_PATH,
                check=True
            )
            safe_print("[SUCCESS] GitHub 푸시 완료")
            
        except subprocess.CalledProcessError:
            safe_print("[INFO] 변경사항이 없어 커밋을 건너뜁니다")
        
        # 5. GitHub Pages URL
        web_url = f"https://{GITHUB_USERNAME}.github.io/{GITHUB_REPO}/reports/{filename}"
        safe_print(f"[WEB] 리포트 URL: {web_url}")
        safe_print("[INFO] GitHub Pages 반영까지 1-2분 소요")
        
        # 6. Slack 알림 (채널 전체 푸시 알림 - 완전 수정 버전)
        payload = {
            # 🔥 핵심 1: text 필드에 <!channel> 추가 (푸시 알림의 핵심!)
            "text": f"<!channel> 📊 AI 기반 프리미엄 추천 종목 리포트 v4 ({trade_date}) - 오늘의 리포트가 준비되었습니다!",
            
            "blocks": [
                # 🔥 핵심 2: header 대신 section + mrkdwn 사용
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",  # ✅ plain_text가 아닌 mrkdwn 사용!
                        "text": f"<!channel> 📊 *AI 기반 프리미엄 추천 종목 리포트 v4*\n\n*기준일:* {trade_date}"
                    }
                },
                {
                    "type": "divider"  # 시각적 구분선
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": "*분석 기준*\n시가총액 ≥ 3000억"
                        },
                        {
                            "type": "mrkdwn",
                            "text": "*등락률*\n≥ 5%"
                        },
                        {
                            "type": "mrkdwn",
                            "text": "*거래대금*\n≥ 1000억"
                        },
                        {
                            "type": "mrkdwn",
                            "text": "*상태*\n🚀 준비 완료"
                        }
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "🚀 *오늘의 리포트가 준비되었습니다!*"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "📄 AI 프리미엄 리포트 보기",
                                "emoji": True
                            },
                            "url": web_url,
                            "style": "primary"
                        }
                    ]
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "💡 버튼을 클릭하면 브라우저에서 완전한 리포트를 확인할 수 있습니다."
                        }
                    ]
                }
            ]
        }

        
        response = requests.post(WEBHOOK_URL, data=json.dumps(payload))
        
        if response.status_code == 200:
            safe_print("[SUCCESS] Slack 알림 전송 완료!")
            return True
        else:
            safe_print(f"[WARNING] Slack 전송 실패: {response.text}")
            return False
            
    except Exception as e:
        safe_print(f"[ERROR] 예외 발생: {str(e)}")
        return False


def send_report_to_slack(file_path, trade_date):
    """깔끔한 메시지 + HTML 파일 업로드"""
    
    # Slack 설정
    SLACK_TOKEN = "xoxb-9745985197379-10123228976753-ahTerLqgVeOoiQCL8gdmsJOL"  # 발급받은 Bot Token
    CHANNEL_ID = "C09MNTRR739"  # 전송할 채널명
    
    if not SLACK_TOKEN.startswith('xoxb-'):
        print("올바른 Bot Token이 필요합니다.")
        return False
    
    if not os.path.exists(file_path):
        print(f"파일을 찾을 수 없습니다: {file_path}")
        return False
    
    client = WebClient(token=SLACK_TOKEN)
    
    try:
        # 1. 먼저 예쁜 알림 메시지 전송
        print("리포트 알림 메시지 전송 중...")
        message_response = client.chat_postMessage(
            channel=CHANNEL_ID,
            blocks=[
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"AI 기반 프리미엄 추천 종목 리포트 v4",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*기준일:* {trade_date}\n*분석 기준:* 시가총액 ≥ 3000억, 등락률 ≥ 5%, 거래대금 ≥ 1000억\n\n🚀 **오늘의 리포트가 출시되었습니다!**\n아래 HTML 파일을 다운로드하여 브라우저에서 확인하세요."
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "투자 유의사항: 데이터 기반 통계적 추천이므로 신중한 판단하에 투자하시기 바랍니다."
                        }
                    ]
                }
            ]
        )
        
        # 2. HTML 파일 업로드 (깔끔하게)
        print("📎 HTML 파일 업로드 중...")
        file_response = client.files_upload_v2(
            channel=CHANNEL_ID,
            file=file_path,
            title=f"AI 프리미엄 추천 종목 리포트 ({trade_date})",
            filename=f"premium_stock_report_{trade_date}.html",
            initial_comment="💡 이 파일을 다운로드하여 브라우저에서 열어보세요!"
        )
        
        print("리포트 전송 완료!")
        
        # 파일 링크 출력
        if file_response.get('files'):
            file_url = file_response['files'][0].get('permalink', 'N/A')
            print(f"📎 Slack 파일 링크: {file_url}")
        
        return True
        
    except SlackApiError as e:
        error_code = e.response['error']
        print(f"전송 실패: {error_code}")
        
        # 오류별 해결 방법
        if error_code == 'invalid_auth':
            print("Bot Token을 확인하세요 (xoxb-로 시작해야 함)")
        elif error_code == 'not_in_channel':
            print("채널에서 '/invite @봇이름' 명령어로 봇을 초대하세요")
        elif error_code == 'missing_scope':
            print("OAuth & Permissions에서 'files:write' 권한을 추가하세요")
        
        return False
        
    except Exception as e:
        print(f"예외 발생: {str(e)}")
        return False


def upload_html_to_slack(file_path, trade_date):
    """slack_sdk를 사용한 HTML 파일 업로드"""
    
    # Slack 설정
    SLACK_TOKEN = "xoxb-9745985197379-10123228976753-ahTerLqgVeOoiQCL8gdmsJOL"  # 발급받은 Bot Token
    CHANNEL_ID = "C09MNTRR739"  # 전송할 채널명
    
    # 토큰 유효성 검사
    if not SLACK_TOKEN.startswith('xoxb-'):
        print("Slack Bot Token이 올바르지 않습니다.")
        print("'xoxb-'로 시작하는 Bot User OAuth Token을 사용해야 합니다.")
        return False
    
    # 파일 존재 확인
    if not os.path.exists(file_path):
        print(f"파일을 찾을 수 없습니다: {file_path}")
        return False
    
    client = WebClient(token=SLACK_TOKEN)
    
    try:
        print("HTML 파일을 Slack에 업로드 중...")
        
        # 미리보기 메시지
        preview_message = f"""**AI 기반 프리미엄 추천 종목 리포트 v4**

📅 **기준일:** {trade_date}
🎯 **분석 기준:** 시가총액 ≥ 3000억, 등락률 ≥ 5%, 거래대금 ≥ 1000억

💡 **첨부된 HTML 파일을 다운로드하여 브라우저에서 확인하세요!**
    • 오늘의 추천주 (프리미엄 + 강한/완만 돌파)
    • 프리미엄 추천 종목  
    • 관심 종목 (AI 예상 상승 확률 포함)

⚠️ **투자 유의사항:** 데이터 기반 통계적 추천이므로 신중한 판단하에 투자하시기 바랍니다."""

        # files_upload_v2가 새로운 API를 자동으로 처리
        response = client.files_upload_v2(
            channel=CHANNEL_ID,
            file=file_path,
            title=f"AI 프리미엄 추천 종목 리포트 ({trade_date})",
            initial_comment=preview_message,
            filename=f"premium_stock_report_{trade_date}.html"
        )
        
        print("✅ HTML 파일 업로드 성공!")
        
        # 파일 링크 출력
        if response.get('files'):
            file_url = response['files'][0].get('permalink', 'N/A')
            print(f"📎 Slack 파일 링크: {file_url}")
        
        return True
        
    except SlackApiError as e:
        error_code = e.response['error']
        print(f"❌ 업로드 실패: {error_code}")
        
        # 상세한 오류별 해결 방법
        error_solutions = {
            'invalid_auth': [
                "1. https://api.slack.com/apps 접속",
                "2. 앱 선택 → 'OAuth & Permissions'",
                "3. 'Bot User OAuth Token' (xoxb-로 시작) 다시 복사"
            ],
            'not_in_channel': [
                "1. Slack 채널에서 '/invite @봇이름' 명령어 실행",
                "2. 채널 설정 → 통합 → 앱 추가로 봇 초대"
            ],
            'missing_scope': [
                "1. OAuth & Permissions → Bot Token Scopes",
                "2. 'files:write' 권한 추가",
                "3. 'Reinstall to Workspace' 클릭"
            ]
        }
        
        if error_code in error_solutions:
            print("\n💡 해결 방법:")
            for step in error_solutions[error_code]:
                print(f"   {step}")
        
        return False
    
    except Exception as e:
        print(f"❌ 예외 발생: {str(e)}")
        return False



# ------------------ 날짜 ------------------
def get_trade_date():
    d = stock.get_nearest_business_day_in_a_week()
    return d if isinstance(d, str) else d.strftime("%Y%m%d")


# ------------------ 52주 통계 ------------------
def get_52w_stats(ticker, end_date):
    start = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=LOOKBACK_52W_DAYS)).strftime("%Y%m%d")
    try:
        df = stock.get_market_ohlcv_by_date(start, end_date, ticker)
    except:
        return np.nan, np.nan
    if df is None or df.empty:
        return np.nan, np.nan

    df = df[(df["종가"] > 0) & (df["저가"] > 0)]
    if df.empty:
        return np.nan, np.nan

    return float(df["종가"].max()), float(df["저가"].min())


# ------------------ 최근 OHLCV ------------------
def get_recent_ohlcv(ticker, end_date, days=LOOKBACK_PATTERN_DAYS):
    start = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")
    try:
        df = stock.get_market_ohlcv_by_date(start, end_date, ticker)
    except:
        return None
    if df is None or df.empty:
        return None
    df = df[(df["종가"] > 0) & (df["거래량"] > 0)]
    return df if not df.empty else None


# ------------------ 수급 ------------------
def get_net_values(ticker, date):
    try:
        df = stock.get_market_trading_value_by_investor(date, date, ticker)
        if df is None or df.empty:
            return 0, 0
        idx = df.index.astype(str)
        col = df.columns[-1]
        net_f = int(df.loc[idx.str.contains("외국인"), col].sum())
        net_i = int(df.loc[idx.str.contains("기관"),   col].sum())
        return net_f, net_i
    except:
        return 0, 0


# ------------------ 신고가 패턴 분류 ------------------
def classify_breakout_pattern(df_recent, is_52w_high):
    if (not is_52w_high) or df_recent is None or len(df_recent) < 5:
        return ""

    df_recent = df_recent.sort_index()
    today = df_recent.iloc[-1]
    prev = df_recent.iloc[-2]

    close_today = float(today["종가"])
    close_prev  = float(prev["종가"])
    high_today  = float(today["고가"])
    low_today   = float(today["저가"])
    open_today  = float(today["시가"])
    volume_today = float(today["거래량"])

    total_range = max(high_today - low_today, 1e-6)
    upper_shadow_ratio = (high_today - max(open_today, close_today)) / total_range

    change_today = (close_today / close_prev) - 1.0

    if len(df_recent) >= 20:
        vol_ma = float(df_recent["거래량"].tail(20).mean())
    else:
        vol_ma = float(df_recent["거래량"].mean())

    # 강한 돌파
    if change_today >= 0.03 and volume_today >= 1.5 * vol_ma:
        return "강한 돌파"

    # 완만한 돌파
    if change_today > 0 and volume_today >= vol_ma:
        return "완만한 돌파"

    # 가짜 돌파 (위꼬리 길고 종가가 밀린 경우)
    if change_today <= 0 and upper_shadow_ratio > 0.6:
        return "가짜 돌파(위꼬리)"

    # 돌파 후 급락
    if change_today <= -0.03:
        return "돌파 후 급락"

    # 중립
    return "중립"


# ------------------ 패턴별 AI 대응 전략 ------------------
def make_strategy_text(pattern):
    if pattern == "강한 돌파":
        return "<b style='color:#d00000'>강한 추세 구간입니다. 시초가 또는 눌림목 매수 가능. 전일 저가 이탈 시 손절 대응이 필요합니다.</b>"
    if pattern == "완만한 돌파":
        return "<b style='color:#f97316'>안정적인 돌파입니다. 당일 추격매수보다는 1~2일 조정 후 재돌파 시 분할 매수를 고려하세요.</b>"
    if pattern == "가짜 돌파(위꼬리)":
        return "<b style='color:#2563eb'>위험 신호입니다. 신규 매수는 피하고, 보유 중이라면 반등 시 비중 축소를 우선 고려하세요.</b>"
    if pattern == "돌파 후 급락":
        return "<b style='color:#1d4ed8'>돌파 실패 패턴입니다. 추가 하락 위험이 크므로 매수 금지, 보유 시 손절 또는 빠른 회수 전략이 필요합니다.</b>"
    if pattern == "중립":
        return "<b style='color:#6b7280'>방향성이 아직 뚜렷하지 않습니다. 다음 거래일 고가 돌파 시 분할 매수, 전고점 이탈 시 관망하는 보수적인 접근이 유리합니다.</b>"
    return ""


# ------------------ AI 예상 상승 확률 계산 ------------------
def calc_ai_prob(pattern, is_premium, change_pct, from_low, net_f, net_i):
    if pattern == "강한 돌파":
        base = 78
    elif pattern == "완만한 돌파":
        base = 68
    elif pattern == "가짜 돌파(위꼬리)":
        base = 42
    elif pattern == "돌파 후 급락":
        base = 30
    elif pattern == "중립":
        base = 55
    else:
        base = 50

    if is_premium:
        base += 5

    if net_f > 0 and net_i > 0:
        base += 3

    if from_low < 150:
        base += 2

    if change_pct >= 10:
        base -= 3

    base = max(10, min(95, base))
    return float(base)


# ======================= MAIN =======================
def generate_report():
    trade_date = get_trade_date()
    print(f"[INFO] 기준일: {trade_date}")

    base_rows = []

    # ----- 1. 기본 필터 (리포트 포함 종목) -----
    for market in ["KOSPI", "KOSDAQ"]:
        ohlcv = stock.get_market_ohlcv_by_ticker(trade_date, market)
        cap   = stock.get_market_cap(trade_date, market)

        if "시가총액" in ohlcv.columns:
            ohlcv = ohlcv.drop(columns=["시가총액"])
        df = ohlcv.join(cap[["시가총액"]], how="left")

        if "등락률" not in df.columns:
            raise RuntimeError("등락률 컬럼이 없습니다. pykrx 버전을 확인하세요.")

        for ticker in tqdm(df.index.tolist(), desc=f"{market} 기본 필터"):
            row = df.loc[ticker]
            close  = float(row["종가"])
            value  = float(row["거래대금"])
            mcap   = float(row["시가총액"])
            change = float(row["등락률"])

            if close <= 0 or mcap <= 0:
                continue
            if change < MIN_CHANGE:
                continue
            if value  < MIN_VALUE:
                continue
            if mcap   < MIN_MCAP:
                continue

            base_rows.append({
                "시장": market,
                "티커": ticker,
                "종목명": stock.get_market_ticker_name(ticker),
                "종가": close,
                "등락률(%)": change,
                "거래대금(억원)": value / 1e8,
                "시가총액(억원)": mcap / 1e8,
            })

    if not base_rows:
        print("[INFO] 기본 조건을 만족하는 종목이 없습니다.")
        return

    df_base = pd.DataFrame(base_rows)

    # ----- 2. 상세 분석 -----
    enriched = []

    for _, row in tqdm(df_base.iterrows(), total=len(df_base), desc="상세 분석"):
        ticker = row["티커"]
        name   = row["종목명"]
        close  = float(row["종가"])
        change = float(row["등락률(%)"])
        value  = float(row["거래대금(억원)"]) * 1e8
        mcap   = float(row["시가총액(억원)"]) * 1e8

        high52, low52 = get_52w_stats(ticker, trade_date)
        if np.isnan(high52) or np.isnan(low52) or high52 <= 0 or low52 <= 0:
            continue

        is_52w_high = close >= high52 - EPS
        gap = 0.0 if is_52w_high else (high52 - close) / high52 * 100.0
        from_low = (close / low52 - 1.0) * 100.0

        net_f, net_i = get_net_values(ticker, trade_date)

        is_premium = (from_low < MAX_FROM_LOW and net_f > 0 and net_i > 0)

        df_recent = get_recent_ohlcv(ticker, trade_date, LOOKBACK_PATTERN_DAYS)
        pattern = classify_breakout_pattern(df_recent, is_52w_high)
        ai_strategy = make_strategy_text(pattern)

        ai_prob = calc_ai_prob(pattern, is_premium, change, from_low, net_f, net_i)

        enriched.append({
            "시장": row["시장"],
            "티커": ticker,
            "종목명": name,
            "종가": close,
            "등락률(%)": change,
            "거래대금(억원)": value / 1e8,
            "시가총액(억원)": mcap / 1e8,
            "52주신고가": "Yes" if is_52w_high else "",
            "52주괴리(%)": gap,
            "52주최저대비(%)": from_low,
            "외국인순매수(억)": net_f / 1e8,
            "기관순매수(억)": net_i / 1e8,
            "신고가패턴": pattern,
            "AI전략": ai_strategy,
            "AI예상상승확률(%)": ai_prob,
            "is_premium": is_premium,
        })

    if not enriched:
        print("[INFO] 상세 분석 결과가 없습니다.")
        return

    df_all = pd.DataFrame(enriched)

    # ===== 프리미엄 / 관심 종목 분리 =====
    premium_df = df_all[df_all["is_premium"]].copy()
    watch_df   = df_all[~df_all["is_premium"]].copy()

    # ===== 오늘의 추천주 (프리미엄 + 강한/완만 돌파) =====
    recommend = premium_df[premium_df["신고가패턴"].isin(["강한 돌파", "완만한 돌파"])].copy()
    recommend = recommend.sort_values(
        by=["AI예상상승확률(%)"],
        ascending=False
    ).reset_index(drop=True)

    # ===== 프리미엄 섹션에서 추천주 중복 제거 =====
    if not recommend.empty:
        premium_main = premium_df[~premium_df["티커"].isin(recommend["티커"])].copy()
    else:
        premium_main = premium_df.copy()

    # ===== 프리미엄 / 관심 종목도 AI 확률 순으로 정렬 =====
    premium_main = premium_main.sort_values(
        by=["AI예상상승확률(%)"],
        ascending=False
    ).reset_index(drop=True)

    watch_df = watch_df.sort_values(
        by=["AI예상상승확률(%)"],
        ascending=False
    ).reset_index(drop=True)

    # ===== 숫자/스타일 포맷 =====
    def red(text):    return f"<b style='color:#d00000'>{text}</b>"
    def orange(text): return f"<b style='color:#f97316'>{text}</b>"

    def style_row(row):
        r = row.copy()

        r["등락률(%)"]       = f"{row['등락률(%)']:,.1f}"
        r["거래대금(억원)"]  = f"{row['거래대금(억원)']:,.1f}"
        r["시가총액(억원)"]  = f"{row['시가총액(억원)']:,.1f}"
        r["외국인순매수(억)"] = f"{row['외국인순매수(억)']:,.1f}"
        r["기관순매수(억)"]   = f"{row['기관순매수(억)']:,.1f}"
        r["52주최저대비(%)"] = f"{row['52주최저대비(%)']:,.1f}"
        r["AI예상상승확률(%)"] = f"{row['AI예상상승확률(%)']:,.0f}"

        if row["52주신고가"] == "Yes":
            r["52주신고가"] = red("Yes")
            r["52주괴리(%)"] = ""
        else:
            r["52주신고가"] = ""
            r["52주괴리(%)"] = f"{row['52주괴리(%)']:,.2f}"

        if row["52주최저대비(%)"] < MAX_FROM_LOW:
            r["52주최저대비(%)"] = red(r["52주최저대비(%)"])

        if row["외국인순매수(억)"] > 0:
            r["외국인순매수(억)"] = red(r["외국인순매수(억)"])
        if row["기관순매수(억)"] > 0:
            r["기관순매수(억)"] = red(r["기관순매수(억)"])

        pat = row["신고가패턴"]
        if pat == "강한 돌파":
            r["신고가패턴"] = red(pat)
        elif pat == "완만한 돌파":
            r["신고가패턴"] = orange(pat)

        return r

    rec_html   = recommend.apply(style_row, axis=1) if not recommend.empty   else pd.DataFrame()
    prem_html  = premium_main.apply(style_row, axis=1) if not premium_main.empty else pd.DataFrame()
    watch_html = watch_df.apply(style_row, axis=1) if not watch_df.empty else pd.DataFrame()

    # 내부 컬럼 제거
    drop_cols = ["티커", "is_premium"]
    def drop_internal(df_html):
        cols = [c for c in df_html.columns if c not in drop_cols]
        return df_html[cols]

    rec_html   = drop_internal(rec_html)   if not rec_html.empty   else rec_html
    prem_html  = drop_internal(prem_html)  if not prem_html.empty  else prem_html
    watch_html = drop_internal(watch_html) if not watch_html.empty else watch_html

    # ===== High-End + 모바일 대응 HTML =====
    warning_text = """
※ 이 종목은 데이터에 기반한 통계적인 추천일 뿐이며 100% 확실한 보장이 아닙니다.<br>
시장 전체의 갑작스러운 급변이나 개별 종목의 악재 뉴스로 인한 갑작스러운 변동이 있을 수 있으니,<br>
투자 결정은 반드시 본인의 판단 하에 신중하게 진행하시기 바랍니다.
"""

    html = f"""
<html>
<head>
<meta charset="utf-8">
<title>Premium + Pattern + AI Strategy v4</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<style>
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Malgun Gothic';
  margin: 0;
  padding: 16px;
  background: linear-gradient(135deg, #eef2f7 0%, #e2e5ec 100%);
  color: #111827;
}}
.container {{
  max-width: 1100px;
  margin: 0 auto;
}}
h1 {{
  font-size: 22px;
  margin: 4px 0 6px 0;
}}
.subtitle {{
  font-size: 12px;
  color: #4b5563;
  margin-bottom: 10px;
}}
.warning-box {{
  font-size: 11px;
  color: #7f1d1d;
  background: #fef2f2;
  border: 1px solid #fecaca;
  padding: 8px 10px;
  border-radius: 8px;
  margin-bottom: 14px;
  line-height: 1.5;
}}
.section-title {{
  font-size: 15px;
  margin-top: 18px;
  margin-bottom: 6px;
  font-weight: 700;
}}
.table-wrapper {{
  width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin-bottom: 16px;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  min-width: 720px;
  font-size: 12px;
  background: #ffffff;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 8px 22px rgba(15,23,42,0.12);
}}
th {{
  background: #111827;
  color: #e5e7eb;
  padding: 7px 8px;
  text-align: right;
  font-size: 11px;
  white-space: nowrap;
}}
td {{
  padding: 6px 8px;
  border-bottom: 1px solid #e5e7eb;
  text-align: right;
  white-space: nowrap;
}}
td:first-child, th:first-child {{
  text-align: center;
}}
td:nth-child(2) {{
  text-align: left;
}}
tbody tr:nth-child(even) {{ background: #f9fafb; }}
tbody tr:hover {{ background: #eef2ff; }}

.legend {{
  font-size: 11px;
  margin-top: 16px;
  background: #f9fafb;
  border-radius: 10px;
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  line-height: 1.6;
}}

@media (max-width: 768px) {{
  body {{
    padding: 10px;
  }}
  h1 {{
    font-size: 18px;
  }}
  .section-title {{
    font-size: 14px;
  }}
  table {{
    font-size: 11px;
    min-width: 640px;
  }}
  th, td {{
    padding: 5px 6px;
  }}
}}
</style>
</head>
<body>
<div class="container">

<h1>AI 기반 프리미엄 추천 종목 리포트 v4</h1>
<div class="subtitle">
  기준일: {trade_date} · (시가총액 ≥ 3000억, 등락률 ≥ 5%, 거래대금 ≥ 1000억 종목만 분석합니다.)
</div>
<div class="warning-box">
  {warning_text}
</div>
"""

    # 오늘의 추천주
    html += "<div class='section-title'>🔥 오늘의 추천주 (프리미엄 + 강한/완만 돌파, AI 예상 상승 확률 순)</div>"
    if not rec_html.empty:
        html += "<div class='table-wrapper'>" + rec_html.to_html(index=False, escape=False) + "</div>"
    else:
        html += "<p>추천 대상 종목이 없습니다.</p>"

    # 프리미엄 추천 종목
    html += "<div class='section-title'>★ 프리미엄 추천 종목 (프리미엄 조건 충족, 추천주 제외 · AI 예상 상승 확률 순)</div>"
    if not prem_html.empty:
        html += "<div class='table-wrapper'>" + prem_html.to_html(index=False, escape=False) + "</div>"
    else:
        html += "<p>프리미엄 추천 종목이 없습니다.</p>"

    # 관심 종목
    html += "<div class='section-title'>👀 관심 종목 (기본 조건 충족, 프리미엄 조건 일부 부족 · AI 예상 상승 확률 순)</div>"
    if not watch_html.empty:
        html += "<div class='table-wrapper'>" + watch_html.to_html(index=False, escape=False) + "</div>"
    else:
        html += "<p>관심 종목이 없습니다.</p>"

    # 하단 설명
    html += """
<div class="legend">
  <b>※ 항목 설명 (주린이용 간단 해설)</b><br>
  · <b>등락률(%)</b>: 오늘 주가가 전일 종가 대비 몇 % 올랐는지(또는 내렸는지)를 의미합니다.<br>
  · <b>거래대금(억원)</b>: 오늘 하루 동안 해당 종목에 실제로 매매된 금액의 합계입니다. 숫자가 클수록 많은 돈이 오간 종목입니다.<br>
  · <b>시가총액(억원)</b>: 회사 전체의 몸값(=현재 주가 × 상장 주식 수)입니다. 규모가 큰 회사일수록 시가총액이 큽니다.<br>
  · <b>52주신고가</b>: 최근 1년(52주) 동안의 가격 중에서 오늘이 가장 높은 가격에 해당하는지 여부입니다.<br>
  · <b>52주괴리(%)</b>: 최근 1년 최고가 대비 현재 주가가 얼마나 떨어져 있는지 비율입니다. 숫자가 작을수록 신고가에 가까운 종목입니다.<br>
  · <b>52주최저대비(%)</b>: 최근 1년 최저가 대비 현재 주가가 얼마나 오른 상태인지 백분율입니다. 예를 들어 200%이면 최저가 대비 3배 수준입니다.<br>
  · <b>외국인순매수(억) / 기관순매수(억)</b>: 오늘 외국인·기관 투자자가 해당 종목을 얼마만큼 ‘순매수(+)/순매도(-)’했는지 보여줍니다. 빨간색이면 순매수(매수 우위)입니다.<br>
  · <b>신고가패턴</b>: 오늘이 52주 신고가인 종목 중에서 캔들 모양과 거래량을 기준으로<br>
    &nbsp;&nbsp;- <b>강한 돌파</b>: 거래대금과 가격이 함께 강하게 터진 구간 (추세가 강할 가능성 높음)<br>
    &nbsp;&nbsp;- <b>완만한 돌파</b>: 비교적 안정적인 돌파, 눌림목 매수 관점에 적합<br>
    &nbsp;&nbsp;- <b>가짜 돌파(위꼬리)</b>: 장중 고점을 찍고 눌린 형태로, 단기 고점 가능성이 있어 주의 필요<br>
    &nbsp;&nbsp;- <b>돌파 후 급락</b>: 돌파 시도 후 바로 큰 폭으로 밀린 형태로, 리스크가 매우 높은 패턴<br>
    &nbsp;&nbsp;- <b>중립</b>: 뚜렷한 강세·약세 패턴이 아직 보이지 않는 상태입니다.<br>
  · <b>AI전략</b>: 위 패턴과 수급을 바탕으로, 단기 트레이딩 시 어떤 식으로 대응할지에 대한 참고용 코멘트입니다.<br>
  · <b>AI예상상승확률(%)</b>: 패턴·수급·저점 대비 위치 등을 조합해 계산한 ‘단기적으로 추가 상승할 가능성’을 AI가 추정한 값입니다.<br>
    &nbsp;&nbsp;이 값은 통계적인 참고 지표일 뿐이며, 실제 결과를 보장하지 않습니다.
</div>
</div> <!-- container -->
</body>
</html>
"""

    # os.makedirs(OUTPUT_DIR, exist_ok=True)
    # html_path = os.path.join(OUTPUT_DIR, f"Premium_AI_Report_v4_{trade_date}.html")
    # with open(html_path, "w", encoding="utf-8") as f:
    #     f.write(html)

    # print(f"[INFO] HTML 저장 완료: {html_path}")
    # webbrowser.open("file://" + os.path.abspath(html_path))
    # WEBHOOK_URL = "https://hooks.slack.com/services/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"
    # payload = {
    #     "text": f"```html\n{html}\n```"  # Slack 코드 블록 + HTML 하이라이팅
    # }

    # response = requests.post(WEBHOOK_URL, data=json.dumps(payload))

    # if response.status_code == 200:
    #     print("✅ 메시지 전송 성공!")
    # else:
    #     print("❌ 메시지 전송 실패:", response.text)
        
     # ===== 파일 저장 =====
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html_path = os.path.join(OUTPUT_DIR, f"Premium_AI_Report_v4_{trade_date}.html")
    
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"[INFO] HTML 저장 완료: {html_path}")
    
    # 로컬 브라우저에서 열기 (선택사항)
    webbrowser.open("file://" + os.path.abspath(html_path))
    
    # ===== 파일 저장 =====
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html_path = os.path.join(OUTPUT_DIR, f"Premium_AI_Report_v4_{trade_date}.html")
    
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"[INFO] HTML 저장 완료: {html_path}")
    
    # 로컬 브라우저에서 열기 (선택사항)
    webbrowser.open("file://" + os.path.abspath(html_path))
    
    # ===== Slack 전송 (방법 선택) =====
    
    # 방법 1: PDF 변환 (추천 - Slack에서 바로 보기)
    # convert_to_pdf_and_send(html_path, trade_date)
    
    # 방법 2: GitHub Pages (최고의 UX - 설정 필요)
    upload_to_github_and_notify(html, trade_date)
    
    # 방법 3: 현재 방식 개선 (가장 간단)
    # send_html_with_clear_guide(html_path, trade_date)

if __name__ == "__main__":
    generate_report()
