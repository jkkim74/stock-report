# -*- coding: utf-8 -*-
"""
리포트 생성 핵심 로직 (완전 통합 버전)
- 발송 방법에 대해 전혀 알지 못함
- 순수하게 데이터 분석과 HTML 생성만 담당

제공 기능:
1. generate_premium_stock_report(): 프리미엄 주식 추천 리포트
2. getUpAndDownReport(): Gap Up & Down 리스크 분석 리포트
"""

import sys
import io
import base64
import os
import traceback
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import datetime as dt

# 시각화 및 글로벌 데이터 수집 라이브러리
import matplotlib
matplotlib.use('Agg')  # 서버 환경에서 GUI 없이 차트 생성
import matplotlib.pyplot as plt
import yfinance as yf

from pykrx import stock
from tqdm import tqdm
from pytz import timezone
from config import ANALYSIS_CONFIG

import warnings
from io import BytesIO

# matplotlib 설정은 이미 존재하므로 추가 설정 불필요

import logging
import requests
import FinanceDataReader as fdr

# Market Supply용 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# Windows 콘솔 UTF-8 인코딩 설정
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        import io
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True
        )

TZ = timezone("Asia/Seoul")

# matplotlib 한글 폰트 설정
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False


class ReportData:
    """리포트 데이터를 담는 컨테이너"""
    
    def __init__(self, html_content, trade_date, metadata):
        self.html_content = html_content
        self.trade_date = trade_date
        self.metadata = metadata
    
    def __repr__(self):
        return f"ReportData(trade_date={self.trade_date}, type={self.metadata.get('report_type')})"


# ===== 공통 유틸리티 함수들 =====

def now_kr_str():
    """한국 시간 문자열 반환"""
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S KST")

def safe_float(v):
    """안전한 float 변환"""
    try:
        if v is None:
            return np.nan
        return float(v)
    except Exception:
        return np.nan

def pct(a, b):
    """수익률(%) 계산"""
    a = safe_float(a)
    b = safe_float(b)
    if np.isnan(a) or np.isnan(b) or b == 0:
        return np.nan
    return (a / b - 1.0) * 100.0

def fmt(v, nd=3):
    """숫자 포맷팅"""
    v = safe_float(v)
    if np.isnan(v):
        return "NaN"
    if abs(v) >= 1000:
        return f"{v:.1f}"
    return f"{v:.{nd}f}"


# ===== 프리미엄 주식 리포트 헬퍼 함수들 =====

def get_trade_date():
    """거래일 조회"""
    d = stock.get_nearest_business_day_in_a_week()
    return d if isinstance(d, str) else d.strftime("%Y%m%d")

def get_52w_stats(ticker, end_date):
    """52주 최고가/최저가 조회"""
    start = (datetime.strptime(end_date, "%Y%m%d") - 
             timedelta(days=ANALYSIS_CONFIG["LOOKBACK_52W_DAYS"])).strftime("%Y%m%d")
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

def get_recent_ohlcv(ticker, end_date):
    """최근 OHLCV 데이터 조회"""
    start = (datetime.strptime(end_date, "%Y%m%d") - 
             timedelta(days=ANALYSIS_CONFIG["LOOKBACK_PATTERN_DAYS"])).strftime("%Y%m%d")
    try:
        df = stock.get_market_ohlcv_by_date(start, end_date, ticker)
    except:
        return None
    
    if df is None or df.empty:
        return None
    
    df = df[(df["종가"] > 0) & (df["거래량"] > 0)]
    return df if not df.empty else None

def get_net_values(ticker, date):
    """외국인/기관 순매수 조회"""
    try:
        df = stock.get_market_trading_value_by_investor(date, date, ticker)
        if df is None or df.empty:
            return 0, 0
        
        idx = df.index.astype(str)
        col = df.columns[-1]
        net_f = int(df.loc[idx.str.contains("외국인"), col].sum())
        net_i = int(df.loc[idx.str.contains("기관"), col].sum())
        return net_f, net_i
    except:
        return 0, 0

def classify_breakout_pattern(df_recent, is_52w_high):
    """신고가 패턴 분류"""
    if (not is_52w_high) or df_recent is None or len(df_recent) < 5:
        return ""

    df_recent = df_recent.sort_index()
    today = df_recent.iloc[-1]
    prev = df_recent.iloc[-2]

    close_today = float(today["종가"])
    close_prev = float(prev["종가"])
    high_today = float(today["고가"])
    low_today = float(today["저가"])
    open_today = float(today["시가"])
    volume_today = float(today["거래량"])

    total_range = max(high_today - low_today, 1e-6)
    upper_shadow_ratio = (high_today - max(open_today, close_today)) / total_range
    change_today = (close_today / close_prev) - 1.0

    vol_ma = (float(df_recent["거래량"].tail(20).mean()) if len(df_recent) >= 20 
              else float(df_recent["거래량"].mean()))

    # 패턴 분류
    if change_today >= 0.03 and volume_today >= 1.5 * vol_ma:
        return "강한 돌파"
    elif change_today > 0 and volume_today >= vol_ma:
        return "완만한 돌파"
    elif change_today <= 0 and upper_shadow_ratio > 0.6:
        return "가짜 돌파(위꼬리)"
    elif change_today <= -0.03:
        return "돌파 후 급락"
    else:
        return "중립"

def make_strategy_text(pattern):
    """패턴별 AI 대응 전략 텍스트 생성"""
    strategies = {
        "강한 돌파": "<b style='color:#d00000'>강한 추세 구간입니다. 시초가 또는 눌림목 매수 가능. 전일 저가 이탈 시 손절 대응이 필요합니다.</b>",
        "완만한 돌파": "<b style='color:#f97316'>안정적인 돌파입니다. 당일 추격매수보다는 1~2일 조정 후 재돌파 시 분할 매수를 고려하세요.</b>",
        "가짜 돌파(위꼬리)": "<b style='color:#2563eb'>위험 신호입니다. 신규 매수는 피하고, 보유 중이라면 반등 시 비중 축소를 우선 고려하세요.</b>",
        "돌파 후 급락": "<b style='color:#1d4ed8'>돌파 실패 패턴입니다. 추가 하락 위험이 크므로 매수 금지, 보유 시 손절 또는 빠른 회수 전략이 필요합니다.</b>",
        "중립": "<b style='color:#6b7280'>방향성이 아직 뚜렷하지 않습니다. 다음 거래일 고가 돌파 시 분할 매수, 전고점 이탈 시 관망하는 보수적인 접근이 유리합니다.</b>"
    }
    return strategies.get(pattern, "")

def calc_ai_prob(pattern, is_premium, change_pct, from_low, net_f, net_i):
    """AI 예상 상승 확률 계산"""
    base_scores = {
        "강한 돌파": 78, "완만한 돌파": 68, "가짜 돌파(위꼬리)": 42,
        "돌파 후 급락": 30, "중립": 55
    }
    
    base = base_scores.get(pattern, 50)
    
    # 조건별 보정
    if is_premium:
        base += 5
    if net_f > 0 and net_i > 0:
        base += 3
    if from_low < 150:
        base += 2
    if change_pct >= 10:
        base -= 3

    return float(max(10, min(95, base)))

def style_row(row):
    """테이블 행 스타일링"""
    r = row.copy()
    
    # 숫자 포맷팅
    r["등락률(%)"] = f"{row['등락률(%)']:,.1f}"
    r["거래대금(억원)"] = f"{row['거래대금(억원)']:,.1f}"
    r["시가총액(억원)"] = f"{row['시가총액(억원)']:,.1f}"
    r["외국인순매수(억)"] = f"{row['외국인순매수(억)']:,.1f}"
    r["기관순매수(억)"] = f"{row['기관순매수(억)']:,.1f}"
    r["52주최저대비(%)"] = f"{row['52주최저대비(%)']:,.1f}"
    r["AI예상상승확률(%)"] = f"{row['AI예상상승확률(%)']:,.0f}"

    # 조건부 스타일링
    if row["52주신고가"] == "Yes":
        r["52주신고가"] = "<b style='color:#d00000'>Yes</b>"
        r["52주괴리(%)"] = ""
    else:
        r["52주신고가"] = ""
        r["52주괴리(%)"] = f"{row['52주괴리(%)']:,.2f}"

    if row["52주최저대비(%)"] < ANALYSIS_CONFIG["MAX_FROM_LOW"]:
        r["52주최저대비(%)"] = f"<b style='color:#d00000'>{r['52주최저대비(%)']}</b>"

    if row["외국인순매수(억)"] > 0:
        r["외국인순매수(억)"] = f"<b style='color:#d00000'>{r['외국인순매수(억)']}</b>"
    if row["기관순매수(억)"] > 0:
        r["기관순매수(억)"] = f"<b style='color:#d00000'>{r['기관순매수(억)']}</b>"

    # 패턴 스타일링
    if row["신고가패턴"] == "강한 돌파":
        r["신고가패턴"] = f"<b style='color:#d00000'>{row['신고가패턴']}</b>"
    elif row["신고가패턴"] == "완만한 돌파":
        r["신고가패턴"] = f"<b style='color:#f97316'>{row['신고가패턴']}</b>"

    return r

def generate_premium_html(recommend, premium_main, watch_df, trade_date):
    """프리미엄 주식 리포트 HTML 생성"""
    
    warning_text = """
※ 이 종목은 데이터에 기반한 통계적인 추천일 뿐이며 100% 확실한 보장이 아닙니다.<br>
시장 전체의 갑작스러운 급변이나 개별 종목의 악재 뉴스로 인한 갑작스러운 변동이 있을 수 있으니,<br>
투자 결정은 반드시 본인의 판단 하에 신중하게 진행하시기 바랍니다.
"""

    # 스타일링 적용
    rec_html = recommend.apply(style_row, axis=1) if not recommend.empty else pd.DataFrame()
    prem_html = premium_main.apply(style_row, axis=1) if not premium_main.empty else pd.DataFrame()
    watch_html = watch_df.apply(style_row, axis=1) if not watch_df.empty else pd.DataFrame()

    # 내부 컬럼 제거
    drop_cols = ["티커", "is_premium"]
    def drop_internal(df_html):
        cols = [c for c in df_html.columns if c not in drop_cols]
        return df_html[cols]

    rec_html = drop_internal(rec_html) if not rec_html.empty else rec_html
    prem_html = drop_internal(prem_html) if not prem_html.empty else prem_html
    watch_html = drop_internal(watch_html) if not watch_html.empty else watch_html

    # HTML 템플릿
    html = f"""
<html>
<head>
<meta charset="utf-8">
<title>Premium + Pattern + AI Strategy v4</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<style>
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Malgun Gothic';
  margin: 0; padding: 16px;
  background: linear-gradient(135deg, #eef2f7 0%, #e2e5ec 100%);
  color: #111827;
}}
.container {{ max-width: 1100px; margin: 0 auto; }}
h1 {{ font-size: 22px; margin: 4px 0 6px 0; }}
.subtitle {{ font-size: 12px; color: #4b5563; margin-bottom: 10px; }}
.warning-box {{
  font-size: 11px; color: #7f1d1d; background: #fef2f2;
  border: 1px solid #fecaca; padding: 8px 10px; border-radius: 8px;
  margin-bottom: 14px; line-height: 1.5;
}}
.section-title {{
  font-size: 15px; margin-top: 18px; margin-bottom: 6px; font-weight: 700;
}}
.table-wrapper {{
  width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch;
  margin-bottom: 16px;
}}
table {{
  width: 100%; border-collapse: collapse; min-width: 720px;
  font-size: 12px; background: #ffffff; border-radius: 10px;
  overflow: hidden; box-shadow: 0 8px 22px rgba(15,23,42,0.12);
}}
th {{
  background: #111827; color: #e5e7eb; padding: 7px 8px;
  text-align: right; font-size: 11px; white-space: nowrap;
}}
td {{
  padding: 6px 8px; border-bottom: 1px solid #e5e7eb;
  text-align: right; white-space: nowrap;
}}
td:first-child, th:first-child {{ text-align: center; }}
td:nth-child(2) {{ text-align: left; }}
tbody tr:nth-child(even) {{ background: #f9fafb; }}
tbody tr:hover {{ background: #eef2ff; }}
.legend {{
  font-size: 11px; margin-top: 16px; background: #f9fafb;
  border-radius: 10px; padding: 10px 12px; border: 1px solid #e5e7eb;
  line-height: 1.6;
}}
@media (max-width: 768px) {{
  body {{ padding: 10px; }}
  h1 {{ font-size: 18px; }}
  .section-title {{ font-size: 14px; }}
  table {{ font-size: 11px; min-width: 640px; }}
  th, td {{ padding: 5px 6px; }}
}}
</style>
</head>
<body>
<div class="container">
<h1>AI 기반 프리미엄 추천 종목 리포트 v4</h1>
<div class="subtitle">
  기준일: {trade_date} · (시가총액 ≥ 5000억, 등락률 ≥ 5%, 거래대금 ≥ 1000억 종목만 분석합니다.)
</div>
<div class="warning-box">{warning_text}</div>
"""

    # 섹션별 내용 추가
    html += "<div class='section-title'>🔥 오늘의 추천주 (프리미엄 + 강한/완만 돌파, AI 예상 상승 확률 순)</div>"
    if not rec_html.empty:
        html += "<div class='table-wrapper'>" + rec_html.to_html(index=False, escape=False) + "</div>"
    else:
        html += "<p>추천 대상 종목이 없습니다.</p>"

    html += "<div class='section-title'>★ 프리미엄 추천 종목 (프리미엄 조건 충족, 추천주 제외 · AI 예상 상승 확률 순)</div>"
    if not prem_html.empty:
        html += "<div class='table-wrapper'>" + prem_html.to_html(index=False, escape=False) + "</div>"
    else:
        html += "<p>프리미엄 추천 종목이 없습니다.</p>"

    html += "<div class='section-title'>👀 관심 종목 (기본 조건 충족, 프리미엄 조건 일부 부족 · AI 예상 상승 확률 순)</div>"
    if not watch_html.empty:
        html += "<div class='table-wrapper'>" + watch_html.to_html(index=False, escape=False) + "</div>"
    else:
        html += "<p>관심 종목이 없습니다.</p>"

    # 설명 추가
    html += """
<div class="legend">
  <b>※ 항목 설명 (주린이용 간단 해설)</b><br>
  · <b>등락률(%)</b>: 오늘 주가가 전일 종가 대비 몇 % 올랐는지(또는 내렸는지)를 의미합니다.<br>
  · <b>거래대금(억원)</b>: 오늘 하루 동안 해당 종목에 실제로 매매된 금액의 합계입니다.<br>
  · <b>시가총액(억원)</b>: 회사 전체의 몸값(=현재 주가 × 상장 주식 수)입니다.<br>
  · <b>52주신고가</b>: 최근 1년(52주) 동안의 가격 중에서 오늘이 가장 높은 가격에 해당하는지 여부입니다.<br>
  · <b>AI예상상승확률(%)</b>: 패턴·수급·저점 대비 위치 등을 조합해 계산한 통계적 참고 지표입니다.<br>
    &nbsp;&nbsp;이 값은 실제 결과를 보장하지 않습니다.
</div>
</div>
</body>
</html>
"""
    return html


# ===== Gap Up & Down Risk Report 전용 함수들 =====

# 상수 정의
KOSPI200_TICKER = "KOSPI200.KS"
KOSDAQ150_TICKER = "KQ150.KS"
FUTURES = {
    "ES": {"main": "ES=F", "alt": "MES=F"},
    "NQ": {"main": "NQ=F", "alt": "MNQ=F"},
}

def safe_fetch(ticker, period="10d", interval="1d"):
    """yfinance 안정 래퍼: 실패/빈 데이터면 None"""
    try:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if df is None or df.empty:
            return None
        
        # MultiIndex 컬럼 처리 (yfinance 최신 버전 대응)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df.dropna(how="all", inplace=True)
        return df
    except Exception:
        return None

def last_close(df, n=1):
    """n번째 이전 종가 반환"""
    try:
        return float(df["Close"].iloc[-n])
    except Exception:
        return np.nan

def last_ohlc(df):
    """오늘(마지막 봉) OHLC float tuple"""
    try:
        o = float(df["Open"].iloc[-1])
        h = float(df["High"].iloc[-1])
        l = float(df["Low"].iloc[-1])
        c = float(df["Close"].iloc[-1])
        return o, h, l, c
    except Exception:
        return np.nan, np.nan, np.nan, np.nan

def fetch_with_fallback(main_ticker, alt_ticker, period="10d", interval="1d"):
    """메인 티커 실패 시 대체 티커로 재시도"""
    df = safe_fetch(main_ticker, period=period, interval=interval)
    if df is None or len(df) < 2:
        df = safe_fetch(alt_ticker, period=period, interval=interval)
    return df

def compute_global_signals():
    """글로벌/공통 신호를 dict로 반환"""
    signals = {}

    # 1) 미국 선물 (일간, 최근 4시간)
    for name, tick in FUTURES.items():
        df_d = fetch_with_fallback(tick["main"], tick["alt"], period="3d", interval="1d")
        ret_d = pct(last_close(df_d), last_close(df_d, 2)) if df_d is not None and len(df_d) >= 2 else np.nan
        signals[f"{name}_ret_d"] = {"value": ret_d, "unit": "%", "desc": f"{name} 선물 일간 변화"}

        # 4시간 변화 (야간 프록시)
        df_h = safe_fetch(tick["main"], period="1d", interval="60m")
        if df_h is None or len(df_h) < 4:
            df_h = safe_fetch(tick["alt"], period="1d", interval="60m")
        ret_4h = pct(last_close(df_h), last_close(df_h, 4)) if df_h is not None and len(df_h) >= 4 else np.nan
        signals[f"{name}_ret_4h"] = {"value": ret_4h, "unit": "%", "desc": f"{name} 선물 최근 4시간 변화(야간 프록시)"}

    # 2) BTC (일간 + 3시간)
    btc_d = safe_fetch("BTC-USD", period="5d", interval="1d")
    btc_h = safe_fetch("BTC-USD", period="1d", interval="60m")
    signals["BTC_ret_d"] = {
        "value": pct(last_close(btc_d), last_close(btc_d, 2)) if btc_d is not None and len(btc_d) >= 2 else np.nan,
        "unit": "%", "desc": "비트코인 일간 변화"
    }
    signals["BTC_ret_3h"] = {
        "value": pct(last_close(btc_h), last_close(btc_h, 3)) if btc_h is not None and len(btc_h) >= 3 else np.nan,
        "unit": "%", "desc": "비트코인 최근 3시간 변화"
    }

    # 3) 금리: TNX (bp 변화)
    tnx = safe_fetch("^TNX", period="10d", interval="1d")
    tnx_chg = (last_close(tnx) - last_close(tnx, 2)) if tnx is not None and len(tnx) >= 2 else np.nan
    signals["TNX_chg_bps"] = {"value": tnx_chg, "unit": "bp", "desc": "미 10년물 금리 변화(bp)"}

    # 4) 변동성: VIX / VIX9D / MOVE
    vix = safe_fetch("^VIX", period="10d", interval="1d")
    v9 = safe_fetch("^VIX9D", period="10d", interval="1d")
    move = safe_fetch("^MOVE", period="10d", interval="1d")

    vix_lvl = last_close(vix) if vix is not None else np.nan
    v9_lvl = last_close(v9) if v9 is not None else np.nan
    vix_dd = pct(last_close(vix), last_close(vix, 2)) if vix is not None and len(vix) >= 2 else np.nan
    v9_dd = pct(last_close(v9), last_close(v9, 2)) if v9 is not None and len(v9) >= 2 else np.nan
    spread = (safe_float(v9_lvl) - safe_float(vix_lvl)) if (not np.isnan(v9_lvl) and not np.isnan(vix_lvl)) else np.nan

    signals["VIX_lvl"] = {"value": vix_lvl, "unit": "", "desc": "VIX (30일 변동성, 공포지수)"}
    signals["VIX_dd"] = {"value": vix_dd, "unit": "%", "desc": "VIX 일간 변화율"}
    signals["VIX9D_lvl"] = {"value": v9_lvl, "unit": "", "desc": "VIX9D (9일 단기 변동성)"}
    signals["VIX9D_dd"] = {"value": v9_dd, "unit": "%", "desc": "VIX9D 일간 변화율"}
    signals["VIX_spread"] = {"value": spread, "unit": "pt", "desc": "VIX9D - VIX (단기 이벤트 리스크 프록시)"}
    signals["MOVE_lvl"] = {"value": last_close(move) if move is not None else np.nan, "unit": "", "desc": "MOVE (미국 채권 변동성)"}

    # 5) 환율 / 달러인덱스
    krw = safe_fetch("KRW=X", period="10d", interval="1d")
    dxy = safe_fetch("DX-Y.NYB", period="10d", interval="1d")

    usdkrw_diff = (last_close(krw) - last_close(krw, 2)) if krw is not None and len(krw) >= 2 else np.nan
    dxy_dd = pct(last_close(dxy), last_close(dxy, 2)) if dxy is not None and len(dxy) >= 2 else np.nan

    signals["USDKRW_diff"] = {"value": usdkrw_diff, "unit": "KRW", "desc": "USD/KRW 전일 대비(원화 약세=+)"}
    signals["DXY_dd"] = {"value": dxy_dd, "unit": "%", "desc": "달러인덱스(DXY) 일간 변화율"}

    # 6) 국내 참고: KOSPI200
    k200 = safe_fetch(KOSPI200_TICKER, period="10d", interval="1d")
    k200_ret = pct(last_close(k200), last_close(k200, 2)) if k200 is not None and len(k200) >= 2 else np.nan
    signals["KOSPI200_ret_d"] = {"value": k200_ret, "unit": "%", "desc": "KOSPI200 일간 수익률(참고)"}

    return signals

def compute_kosdaq_signals():
    """코스닥 전용 신호 계산"""
    s = {}
    df = safe_fetch(KOSDAQ150_TICKER, period="30d", interval="1d")

    if df is None or len(df) < 6:
        s["KOSDAQ150_ret_d"] = {"value": np.nan, "unit": "%", "desc": "KOSDAQ150 일간 수익률"}
        s["KOSDAQ150_ATR5_pct"] = {"value": np.nan, "unit": "%", "desc": "KOSDAQ150 5일 ATR% (변동성)"}
        s["KOSDAQ150_long_red"] = {"value": 0.0, "unit": "bool", "desc": "KOSDAQ150 장대 음봉(1=예,0=아니오)"}
        return s

    ret_d = pct(df["Close"].iloc[-1], df["Close"].iloc[-2])

    # TR / ATR 계산
    dfx = df.copy()
    dfx["H-L"] = dfx["High"] - dfx["Low"]
    dfx["H-C"] = (dfx["High"] - dfx["Close"].shift(1)).abs()
    dfx["L-C"] = (dfx["Low"] - dfx["Close"].shift(1)).abs()
    tr = dfx[["H-L", "H-C", "L-C"]].max(axis=1)
    atr5 = float(tr.rolling(5).mean().iloc[-1])
    close_today = float(df["Close"].iloc[-1])
    atr5_pct = (atr5 / close_today) * 100.0 if close_today > 0 else np.nan

    # 장대 음봉 판단
    o, h, l, c = last_ohlc(df)
    today_range = safe_float(h) - safe_float(l)
    long_red = int((c < o) and (atr5 > 0) and (today_range >= 1.5 * atr5))

    s["KOSDAQ150_ret_d"] = {"value": ret_d, "unit": "%", "desc": "KOSDAQ150 일간 수익률"}
    s["KOSDAQ150_ATR5_pct"] = {"value": atr5_pct, "unit": "%", "desc": "KOSDAQ150 5일 ATR% (변동성)"}
    s["KOSDAQ150_long_red"] = {"value": float(long_red), "unit": "bool", "desc": "KOSDAQ150 장대 음봉(1=예,0=아니오)"}
    return s

def clamp_score(x):
    """점수를 0-100 범위로 제한"""
    return int(max(0, min(100, x)))

def level_label(score):
    """점수에 따른 레벨 라벨 반환"""
    if score >= 70:
        return "HIGH", "높음"
    if score >= 40:
        return "MEDIUM", "중간"
    return "LOW", "낮음"

def badge_class(level):
    """레벨에 따른 CSS 클래스 반환"""
    return {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}.get(level, "low")

def duration_hint(score):
    """초보자용: 점수에 따른 '영향 지속 가능 기간' 가이드"""
    if score >= 70:
        return "3~5일", "여러 지표가 동시에 악화/과열된 구간은 보통 3~5일 변동성 확대가 동반될 수 있습니다."
    if score >= 40:
        return "1~3일", "단기 충격/변동성 확대가 1~3일 이어질 가능성이 있습니다."
    return "0~1일", "단기 이슈가 없다면 하루 내 소화되거나, 제한적 변동에 그칠 가능성이 큽니다."

def score_kospi(global_s):
    """코스피 급등/급락 점수 + drivers 계산"""
    up = 0
    down = 0
    du, dd = [], []

    ES_d = safe_float(global_s["ES_ret_d"]["value"])
    NQ_d = safe_float(global_s["NQ_ret_d"]["value"])
    ES_4h = safe_float(global_s["ES_ret_4h"]["value"])
    NQ_4h = safe_float(global_s["NQ_ret_4h"]["value"])

    # 선물 (일간)
    if not np.isnan(ES_d):
        if ES_d >= 1.0:
            up += 12; du.append(f"S&P500 선물 일간 강세 ({fmt(ES_d)}%)")
        elif ES_d <= -1.0:
            down += 12; dd.append(f"S&P500 선물 일간 약세 ({fmt(ES_d)}%)")
    if not np.isnan(NQ_d):
        if NQ_d >= 1.5:
            up += 15; du.append(f"나스닥 선물 일간 강세 ({fmt(NQ_d)}%)")
        elif NQ_d <= -1.5:
            down += 15; dd.append(f"나스닥 선물 일간 급락 ({fmt(NQ_d)}%)")

    # 야간(4h)
    if not np.isnan(ES_4h):
        if ES_4h >= 0.8:
            up += 8; du.append(f"S&P500 선물 야간(4h) 강세 ({fmt(ES_4h)}%)")
        elif ES_4h <= -0.8:
            down += 8; dd.append(f"S&P500 선물 야간(4h) 급락 ({fmt(ES_4h)}%)")
    if not np.isnan(NQ_4h):
        if NQ_4h >= 1.2:
            up += 10; du.append(f"나스닥 선물 야간(4h) 강세 ({fmt(NQ_4h)}%)")
        elif NQ_4h <= -1.2:
            down += 10; dd.append(f"나스닥 선물 야간(4h) 급락 ({fmt(NQ_4h)}%)")

    # BTC
    BTC_d = safe_float(global_s["BTC_ret_d"]["value"])
    BTC_3h = safe_float(global_s["BTC_ret_3h"]["value"])
    if not np.isnan(BTC_d):
        if BTC_d >= 7:
            up += 6; du.append(f"BTC 일간 급등 → 위험선호 ({fmt(BTC_d)}%)")
        elif BTC_d <= -7:
            down += 6; dd.append(f"BTC 일간 급락 → 위험회피 ({fmt(BTC_d)}%)")
    if not np.isnan(BTC_3h):
        if BTC_3h >= 4:
            up += 3; du.append(f"BTC 단기(3h) 급등 ({fmt(BTC_3h)}%)")
        elif BTC_3h <= -4:
            down += 3; dd.append(f"BTC 단기(3h) 급락 ({fmt(BTC_3h)}%)")

    # 금리
    TNX = safe_float(global_s["TNX_chg_bps"]["value"])
    if not np.isnan(TNX):
        if TNX >= 10:
            down += 10; dd.append(f"미 10년물 금리 급등 (Δ {fmt(TNX,2)}bp)")
        elif TNX <= -8:
            up += 6; du.append(f"미 10년물 금리 하락 (Δ {fmt(TNX,2)}bp)")

    # 변동성: VIX / VIX9D / SPREAD / MOVE
    VIX = safe_float(global_s["VIX_lvl"]["value"])
    V9 = safe_float(global_s["VIX9D_lvl"]["value"])
    SP = safe_float(global_s["VIX_spread"]["value"])
    MOVE = safe_float(global_s["MOVE_lvl"]["value"])

    if not np.isnan(VIX):
        if VIX >= 22:
            down += 8; dd.append(f"VIX 높은 수준 (VIX={fmt(VIX,2)})")
        elif VIX <= 14:
            up += 3; du.append(f"VIX 낮은 수준 (VIX={fmt(VIX,2)})")
    if not np.isnan(V9):
        if V9 >= 25:
            down += 10; dd.append(f"VIX9D 상승 → 단기 이벤트 리스크 (VIX9D={fmt(V9,2)})")
        elif V9 <= 15:
            up += 3; du.append(f"VIX9D 안정 (VIX9D={fmt(V9,2)})")
    if not np.isnan(SP) and SP >= 3:
        down += 5; dd.append(f"단기 변동성 스프레드 확대 (VIX9D-VIX={fmt(SP,2)}pt)")
    if not np.isnan(MOVE):
        if MOVE >= 130:
            down += 10; dd.append(f"MOVE 매우 높음 → 채권/금리 불안 (MOVE={fmt(MOVE,1)})")
        elif MOVE <= 90:
            up += 3; du.append(f"MOVE 낮음 → 채권 변동성 안정 (MOVE={fmt(MOVE,1)})")

    # 환율/달러
    USDKRW = safe_float(global_s["USDKRW_diff"]["value"])
    DXY = safe_float(global_s["DXY_dd"]["value"])
    if not np.isnan(USDKRW):
        if USDKRW >= 8:
            down += 8; dd.append(f"원화 급약세 → 외국인 매도압력 (Δ {fmt(USDKRW,2)}원)")
        elif USDKRW <= -8:
            up += 5; du.append(f"원화 강세 → 위험선호 여지 (Δ {fmt(USDKRW,2)}원)")
    if not np.isnan(DXY):
        if DXY >= 0.7:
            down += 6; dd.append(f"DXY 급등 → 글로벌 위험회피 (DXY {fmt(DXY,2)}%)")
        elif DXY <= -0.7:
            up += 6; du.append(f"DXY 하락 → 위험자산 선호 (DXY {fmt(DXY,2)}%)")

    # 국내 참고: KOSPI200 자체
    K200 = safe_float(global_s["KOSPI200_ret_d"]["value"])
    if not np.isnan(K200):
        if K200 >= 1.5:
            up += 6; du.append(f"KOSPI200 단기 강세 ({fmt(K200)}%)")
        elif K200 <= -1.5:
            down += 6; dd.append(f"KOSPI200 단기 약세 ({fmt(K200)}%)")

    return clamp_score(up), clamp_score(down), du, dd

def score_kosdaq(global_s, kosdaq_s):
    """코스닥 급등/급락 점수 + drivers 계산"""
    up = 0
    down = 0
    du, dd = [], []

    # 나스닥/야간 선물 영향 가중
    NQ_d = safe_float(global_s["NQ_ret_d"]["value"])
    NQ_4h = safe_float(global_s["NQ_ret_4h"]["value"])
    if not np.isnan(NQ_d):
        if NQ_d >= 1.5:
            up += 14; du.append(f"나스닥 선물 강세 → 성장주 우호 ({fmt(NQ_d)}%)")
        elif NQ_d <= -1.5:
            down += 14; dd.append(f"나스닥 선물 급락 → 성장주 타격 ({fmt(NQ_d)}%)")
    if not np.isnan(NQ_4h):
        if NQ_4h >= 1.2:
            up += 8; du.append(f"나스닥 야간(4h) 강세 ({fmt(NQ_4h)}%)")
        elif NQ_4h <= -1.2:
            down += 8; dd.append(f"나스닥 야간(4h) 급락 ({fmt(NQ_4h)}%)")

    # 변동성(단기 공포) 영향 확대
    V9 = safe_float(global_s["VIX9D_lvl"]["value"])
    MOVE = safe_float(global_s["MOVE_lvl"]["value"])
    if not np.isnan(V9) and V9 >= 25:
        down += 10; dd.append(f"VIX9D 상승 → 단기 충격에 취약 (VIX9D={fmt(V9,2)})")
    if not np.isnan(MOVE) and MOVE >= 130:
        down += 8; dd.append(f"MOVE 높음 → 매크로 불안 (MOVE={fmt(MOVE,1)})")

    # 환율
    USDKRW = safe_float(global_s["USDKRW_diff"]["value"])
    if not np.isnan(USDKRW) and USDKRW >= 8:
        down += 6; dd.append(f"원화 급약세 → 코스닥 회피 가능성 (Δ {fmt(USDKRW,2)}원)")

    # 코스닥 전용(핵심)
    KQ_ret = safe_float(kosdaq_s["KOSDAQ150_ret_d"]["value"])
    ATR = safe_float(kosdaq_s["KOSDAQ150_ATR5_pct"]["value"])
    long_red = (safe_float(kosdaq_s["KOSDAQ150_long_red"]["value"]) == 1.0)

    if not np.isnan(KQ_ret):
        if KQ_ret >= 2.0:
            up += 14; du.append(f"KOSDAQ150 강세 → 코스닥 모멘텀 (+{fmt(KQ_ret)}%)")
        elif KQ_ret <= -2.0:
            down += 14; dd.append(f"KOSDAQ150 급락 → 코스닥 모멘텀 약화 ({fmt(KQ_ret)}%)")
    if not np.isnan(ATR):
        if ATR >= 3.5 and (not np.isnan(KQ_ret)) and KQ_ret <= -1.0:
            down += 12; dd.append(f"변동성(ATR%) 높고 하락 동반 → 급락 확대 위험 (ATR={fmt(ATR,2)}%)")
        elif ATR >= 3.5 and (not np.isnan(KQ_ret)) and KQ_ret >= 1.0:
            up += 10; du.append(f"변동성(ATR%) 높고 상승 동반 → 돌파형 강세 가능 (ATR={fmt(ATR,2)}%)")
    if long_red:
        down += 12; dd.append("장대 음봉 출현 → 단기 조정/공포 확산 가능성")

    return clamp_score(up), clamp_score(down), du, dd

def build_actions(market_name, up_score, down_score):
    """초보자용 대응 전략 생성"""
    dur_label, dur_text = duration_hint(down_score)

    actions = []
    if down_score >= 70:
        actions += [
            f"[{market_name}] 급락 경보 대응: 레버리지·고변동성 종목 비중 축소, 현금 비중 확대.",
            "갭다운 발생 시 '추가 하락'을 감당할 손절 기준(가격)을 사전에 확정.",
            "무리한 물타기 금지. 분할 진입은 '하락 진정' 확인 후.",
            "가능하다면 인버스/헷지(부분)로 포트폴리오 변동성 완화 고려.",
        ]
    elif down_score >= 40:
        actions += [
            f"[{market_name}] 주의 대응: 신규매수는 보수적으로, 추격매수 자제.",
            "보유 종목의 손절·익절 라인을 재점검하고 포지션 크기를 줄여 변동성 관리.",
            "상승 신호가 있어도 장중 변동이 커질 수 있으니 분할 접근 권장.",
        ]
    else:
        actions += [
            f"[{market_name}] 안정 대응: 급락 리스크는 낮지만, 기본 손절 기준/현금 여유는 유지.",
            "급등 점수가 높아도 '과열·급등 후 급락' 가능성이 있으니 추격매수는 주의.",
        ]

    if up_score >= 70:
        actions += [
            f"[{market_name}] 급등 가능성이 높음: 눌림/분할 접근을 우선, 갭상승 종목 추격은 리스크.",
            "급등 후 1~2일 내 변동성이 커질 수 있어 분할익절/리스크 관리 병행.",
        ]
    elif up_score >= 40:
        actions += [
            f"[{market_name}] 상방 시도 가능: 지지 확인 후 분할매수, 급등 시 일부 이익실현 전략 병행.",
        ]

    actions += [f"[영향 지속 가이드] {dur_label} 예상 — {dur_text}"]
    return actions

def create_dual_gauge_base64(up_score, down_score, title):
    """듀얼 게이지 이미지를 base64로 생성"""
    fig, ax = plt.subplots(figsize=(7.2, 2.2))
    y_pos = [1, 0]
    labels = ["급등 가능성", "급락 위험"]

    ax.barh(y_pos, [100, 100], height=0.36, color="#1f2937")
    ax.barh(1, up_score, height=0.36, color="#3b82f6")
    ax.barh(0, down_score, height=0.36, color="#ef4444")

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=10)
    ax.set_xlim(0, 100)
    ax.set_xlabel("0(낮음)  ←  점수  →  100(매우 높음)", fontsize=9)
    ax.set_title(title, fontsize=12, fontweight="bold")

    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)

    ax.text(min(up_score + 2, 96), 1, f"{up_score}", va="center", fontsize=10, color="white")
    ax.text(min(down_score + 2, 96), 0, f"{down_score}", va="center", fontsize=10, color="white")

    buf = io.BytesIO()
    plt.tight_layout()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()

def glossary_blocks():
    """초보자용 지표 설명 데이터"""
    return [
        ("야간 선물(최근 4시간)",
         "한국 장 시작 전에 미국 시장 분위기를 반영하는 대표 프록시입니다. "
         "장 마감 후 악재가 나오면 야간 선물이 먼저 반응하고, 한국은 다음날 갭으로 반영될 가능성이 있습니다.",
         "0~1일"),
        ("VIX (30일 변동성)",
         "미국 S&P500 옵션에서 계산되는 30일 기대 변동성입니다. 흔히 '공포지수'로 불리며 높을수록 불안 심리를 의미합니다.",
         "1~5일"),
        ("VIX9D (9일 변동성)",
         "매우 단기(9일) 이벤트 리스크에 민감합니다. "
         "VIX9D가 VIX보다 빠르게 튀면 '단기 충격(이벤트)' 가능성을 시사하는 경우가 많습니다.",
         "1~3일"),
        ("MOVE (채권 변동성)",
         "미국 국채 시장의 변동성 지수입니다. 금리/채권이 불안하면 주식에도 부담이 되기 쉽습니다.",
         "2~7일"),
        ("미 10년물 금리(TNX)",
         "금리가 급등하면 성장주/고PER 주식에 압박이 커지고, 외국인 자금 흐름에도 영향을 줄 수 있습니다.",
         "2~7일"),
        ("USD/KRW",
         "원화가 급격히 약해지면 외국인 매도 압력이 커질 수 있고, 특히 변동성 높은 시장(코스닥)에 불리하게 작용할 수 있습니다.",
         "1~5일"),
        ("BTC",
         "위험자산 선호/회피 심리의 '온도계'처럼 움직일 때가 있습니다. 단, 단독 신호는 과신 금지(보조 지표).",
         "0~2일"),
        ("KOSDAQ150 ATR%",
         "코스닥 변동성(진폭)을 나타내는 지표입니다. 변동성이 높은 상태에서 하락까지 겹치면 급락으로 번질 확률이 올라갑니다.",
         "1~3일"),
        ("장대 음봉(코스닥)",
         "하루 변동폭이 크면서 종가가 시가보다 낮게 마감된 '공포 캔들'입니다. 단기 조정이 이어질 가능성이 커질 수 있습니다.",
         "1~3일"),
    ]

def build_table_rows(sig_dict, prefix=""):
    """신호 딕셔너리를 HTML 테이블 행으로 변환"""
    rows = ""
    for k, s in sig_dict.items():
        v = s.get("value", np.nan)
        desc = s.get("desc", "")
        unit = s.get("unit", "")
        rows += f"""
          <tr>
            <td class="mono">{prefix}{k}</td>
            <td>{desc}</td>
            <td class="num">{fmt(v)}</td>
            <td class="unit">{unit}</td>
          </tr>
        """
    return rows

def drivers_html(drivers):
    """Drivers 리스트를 HTML로 변환"""
    if not drivers:
        return "<li class='muted'>현재 구간에서 점수를 크게 올릴 만한 뚜렷한 요인이 많지 않습니다.</li>"
    return "".join([f"<li>{d}</li>" for d in drivers])

def actions_html(actions):
    """대응 전략 리스트를 HTML로 변환"""
    return "".join([f"<li>{a}</li>" for a in actions])

def glossary_html():
    """지표 설명을 HTML로 변환"""
    items = glossary_blocks()
    out = ""
    for title, desc, horizon in items:
        out += f"""
        <div class="g-item">
          <div class="g-title">{title}</div>
          <div class="g-desc">{desc}</div>
          <div class="g-hz">영향 범위(가이드): {horizon}</div>
        </div>
        """
    return out

def build_gap_updown_html(report_dict):
    """Gap Up & Down 리포트 HTML 생성"""
    
    html = f"""
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gap Up & Down Risk Report v7.2</title>
<style>
:root {{
  --bg:#020617; --card:#0b1220; --card2:#0f172a; --text:#e5e7eb;
  --muted:#94a3b8; --line:rgba(148,163,184,.18);
  --blue:#3b82f6; --red:#ef4444; --amber:#f59e0b; --green:#22c55e;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:radial-gradient(1200px 600px at 20% 0%, rgba(59,130,246,.18), transparent 60%),
            radial-gradient(1000px 500px at 80% 10%, rgba(239,68,68,.14), transparent 55%),
            var(--bg);
      color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif;}}
.container{{max-width:980px;margin:0 auto;padding:18px 14px 40px}}
h1{{font-size:20px;margin:6px 0 2px}}
.sub{{color:var(--muted);font-size:12px;margin-bottom:14px}}
.grid{{display:grid;grid-template-columns:1fr;gap:12px}}
@media (min-width:900px){{ .grid{{grid-template-columns:1fr 1fr}} }}
.card{{background:linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.02));
      border:1px solid var(--line); border-radius:18px; padding:14px 14px; box-shadow:0 8px 30px rgba(0,0,0,.25)}}
.card h2{{font-size:14px;margin:0 0 10px;color:#f8fafc}}
.kicker{{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}}
.badges{{display:flex;gap:6px;flex-wrap:wrap}}
.badge{{font-size:11px;padding:5px 8px;border-radius:999px;border:1px solid var(--line);color:#e2e8f0;background:rgba(255,255,255,.03)}}
.badge.low{{border-color:rgba(34,197,94,.35);background:rgba(34,197,94,.10)}}
.badge.medium{{border-color:rgba(245,158,11,.35);background:rgba(245,158,11,.10)}}
.badge.high{{border-color:rgba(239,68,68,.35);background:rgba(239,68,68,.10)}}
.scoreline{{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 10px}}
.scorebox{{flex:1;min-width:140px;background:rgba(255,255,255,.03);border:1px solid var(--line);border-radius:14px;padding:10px 12px}}
.scorebox .label{{font-size:12px;color:var(--muted)}}
.scorebox .val{{font-size:22px;font-weight:800;margin-top:3px}}
.val.up{{color:var(--blue)}} .val.down{{color:var(--red)}}
hr{{border:none;border-top:1px solid var(--line);margin:12px 0}}
img{{width:100%;height:auto;border-radius:14px;border:1px solid var(--line);background:#050a14}}
ul{{margin:8px 0 0 18px;padding:0}}
li{{margin:6px 0}}
.muted{{color:var(--muted)}}
small{{color:var(--muted)}}
details{{border:1px solid var(--line);border-radius:14px;padding:10px 12px;background:rgba(255,255,255,.02)}}
details summary{{cursor:pointer;font-weight:700;color:#f8fafc;outline:none}}
.tablewrap{{overflow:auto;border-radius:14px;border:1px solid var(--line);background:rgba(255,255,255,.02)}}
table{{width:100%;border-collapse:collapse;font-size:12px;min-width:720px}}
th,td{{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{text-align:left;color:#f8fafc;background:rgba(255,255,255,.03)}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
td.unit{{color:var(--muted);width:70px}}
.mono{{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}}
.footer{{margin-top:14px;color:var(--muted);font-size:12px;line-height:1.5}}
.g-item{{padding:10px 0;border-bottom:1px dashed var(--line)}}
.g-item:last-child{{border-bottom:none}}
.g-title{{font-weight:800}}
.g-desc{{color:#cbd5e1;margin-top:3px}}
.g-hz{{color:var(--muted);margin-top:4px;font-size:12px}}
</style>
</head>
<body>
<div class="container">
  <h1>Gap Up & Down Risk Report v7.2</h1>
  <div class="sub">생성 시각: <b>{report_dict["run_time"]}</b> · Mobile-first High-end UI</div>

  <div class="grid">
    <div class="card">
      <div class="kicker">
        <h2>코스피 (KOSPI) 요약</h2>
        <div class="badges">
          <span class="badge {report_dict["kospi_up_badge"]}">급등: {report_dict["kospi_up_label"]}</span>
          <span class="badge {report_dict["kospi_down_badge"]}">급락: {report_dict["kospi_down_label"]}</span>
        </div>
      </div>

      <div class="scoreline">
        <div class="scorebox">
          <div class="label">급등 가능성 점수</div>
          <div class="val up">{report_dict["kospi_up"]}</div>
        </div>
        <div class="scorebox">
          <div class="label">급락 위험 점수</div>
          <div class="val down">{report_dict["kospi_down"]}</div>
        </div>
      </div>

      <img src="data:image/png;base64,{report_dict["kospi_gauge"]}" alt="KOSPI gauge">

      <hr>
      <details open>
        <summary>왜 이런 점수가 나왔나 (Drivers)</summary>
        <div style="margin-top:8px">
          <div class="muted" style="margin-bottom:6px">급등 요인</div>
          <ul>{drivers_html(report_dict["kospi_drivers_up"])}</ul>
          <div class="muted" style="margin:10px 0 6px">급락 요인</div>
          <ul>{drivers_html(report_dict["kospi_drivers_down"])}</ul>
        </div>
      </details>

      <hr>
      <details>
        <summary>대응 전략 (요약)</summary>
        <ul>{actions_html(report_dict["kospi_actions"])}</ul>
      </details>
    </div>

    <div class="card">
      <div class="kicker">
        <h2>코스닥 (KOSDAQ) 요약</h2>
        <div class="badges">
          <span class="badge {report_dict["kosdaq_up_badge"]}">급등: {report_dict["kosdaq_up_label"]}</span>
          <span class="badge {report_dict["kosdaq_down_badge"]}">급락: {report_dict["kosdaq_down_label"]}</span>
        </div>
      </div>

      <div class="scoreline">
        <div class="scorebox">
          <div class="label">급등 가능성 점수</div>
          <div class="val up">{report_dict["kosdaq_up"]}</div>
        </div>
        <div class="scorebox">
          <div class="label">급락 위험 점수</div>
          <div class="val down">{report_dict["kosdaq_down"]}</div>
        </div>
      </div>

      <img src="data:image/png;base64,{report_dict["kosdaq_gauge"]}" alt="KOSDAQ gauge">

      <hr>
      <details open>
        <summary>왜 이런 점수가 나왔나 (Drivers)</summary>
        <div style="margin-top:8px">
          <div class="muted" style="margin-bottom:6px">급등 요인</div>
          <ul>{drivers_html(report_dict["kosdaq_drivers_up"])}</ul>
          <div class="muted" style="margin:10px 0 6px">급락 요인</div>
          <ul>{drivers_html(report_dict["kosdaq_drivers_down"])}</ul>
        </div>
      </details>

      <hr>
      <details>
        <summary>대응 전략 (요약)</summary>
        <ul>{actions_html(report_dict["kosdaq_actions"])}</ul>
      </details>
    </div>
  </div>

  <div class="card" style="margin-top:12px">
    <h2>지표 설명 (초보자용)</h2>
    {glossary_html()}
    <div class="footer">
      * "영향 범위"는 통계적 보장이 아닌 경험적 가이드입니다. 실제 시장은 뉴스/정책/지정학 리스크에 따라 달라질 수 있습니다.
    </div>
  </div>

  <div class="card">
    <h2>지표 상세 (전문가/관심자용)</h2>

    <details open>
      <summary>글로벌 공통 지표</summary>
      <div class="tablewrap" style="margin-top:10px">
        <table>
          <thead><tr><th>키</th><th>설명</th><th class="num">값</th><th>단위</th></tr></thead>
          <tbody>
            {build_table_rows(report_dict["global_signals"], prefix="G.")}
          </tbody>
        </table>
      </div>
    </details>

    <div style="height:10px"></div>

    <details>
      <summary>코스닥 전용 지표</summary>
      <div class="tablewrap" style="margin-top:10px">
        <table>
          <thead><tr><th>키</th><th>설명</th><th class="num">값</th><th>단위</th></tr></thead>
          <tbody>
            {build_table_rows(report_dict["kosdaq_signals"], prefix="KQ.")}
          </tbody>
        </table>
      </div>
    </details>

    <div class="footer" style="margin-top:12px">
      ※ 이 리포트는 데이터에 기반한 통계적/정성적 지표이며 100% 확실한 보장이 아닙니다.<br>
      시장 전체의 급변 또는 개별 악재 뉴스로 변동성이 급격히 커질 수 있습니다. 투자 결정은 반드시 본인 판단 하에 신중히 진행하십시오.
    </div>
  </div>

</div>
</body>
</html>
"""
    return html


# ===== 메인 리포트 생성 함수들 =====

def generate_premium_stock_report():
    """
    프리미엄 주식 리포트 생성
    
    Returns:
        ReportData: HTML 콘텐츠와 메타데이터를 담은 객체
        None: 생성 실패 시
    """
    try:
        trade_date = get_trade_date()
        print(f"[INFO] Premium 기준일: {trade_date}")

        base_rows = []

        # 1. 기본 필터 (리포트 포함 종목)
        for market in ["KOSPI", "KOSDAQ"]:
            ohlcv = stock.get_market_ohlcv_by_ticker(trade_date, market)
            cap = stock.get_market_cap(trade_date, market)

            if "시가총액" in ohlcv.columns:
                ohlcv = ohlcv.drop(columns=["시가총액"])
            df = ohlcv.join(cap[["시가총액"]], how="left")

            if "등락률" not in df.columns:
                raise RuntimeError("등락률 컬럼이 없습니다. pykrx 버전을 확인하세요.")

            for ticker in tqdm(df.index.tolist(), desc=f"{market} 기본 필터"):
                row = df.loc[ticker]
                close = float(row["종가"])
                value = float(row["거래대금"])
                mcap = float(row["시가총액"])
                change = float(row["등락률"])

                # 필터링 조건
                if close <= 0 or mcap <= 0:
                    continue
                if change < ANALYSIS_CONFIG["MIN_CHANGE"]:
                    continue
                if value < ANALYSIS_CONFIG["MIN_VALUE"]:
                    continue
                if mcap < ANALYSIS_CONFIG["MIN_MCAP"]:
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
            return None

        df_base = pd.DataFrame(base_rows)

        # 2. 상세 분석
        enriched = []

        for _, row in tqdm(df_base.iterrows(), total=len(df_base), desc="상세 분석"):
            ticker = row["티커"]
            name = row["종목명"]
            close = float(row["종가"])
            change = float(row["등락률(%)"])

            # 52주 통계 조회
            high52, low52 = get_52w_stats(ticker, trade_date)
            if np.isnan(high52) or np.isnan(low52) or high52 <= 0 or low52 <= 0:
                continue

            is_52w_high = close >= high52 - ANALYSIS_CONFIG["EPS"]
            gap = 0.0 if is_52w_high else (high52 - close) / high52 * 100.0
            from_low = (close / low52 - 1.0) * 100.0

            # 수급 정보 조회
            net_f, net_i = get_net_values(ticker, trade_date)

            # 프리미엄 조건 판단
            is_premium = (from_low < ANALYSIS_CONFIG["MAX_FROM_LOW"] and net_f > 0 and net_i > 0)

            # 패턴 분석
            df_recent = get_recent_ohlcv(ticker, trade_date)
            pattern = classify_breakout_pattern(df_recent, is_52w_high)
            ai_strategy = make_strategy_text(pattern)
            ai_prob = calc_ai_prob(pattern, is_premium, change, from_low, net_f, net_i)

            enriched.append({
                "시장": row["시장"],
                "티커": ticker,
                "종목명": name,
                "종가": close,
                "등락률(%)": change,
                "거래대금(억원)": row["거래대금(억원)"],
                "시가총액(억원)": row["시가총액(억원)"],
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
            return None

        df_all = pd.DataFrame(enriched)

        # 3. 프리미엄 / 관심 종목 분리
        premium_df = df_all[df_all["is_premium"]].copy()
        watch_df = df_all[~df_all["is_premium"]].copy()

        # 4. 오늘의 추천주 (프리미엄 + 강한/완만 돌파)
        recommend = premium_df[premium_df["신고가패턴"].isin(["강한 돌파", "완만한 돌파"])].copy()
        recommend = recommend.sort_values(by=["AI예상상승확률(%)"], ascending=False).reset_index(drop=True)

        # 5. 프리미엄 섹션에서 추천주 중복 제거
        if not recommend.empty:
            premium_main = premium_df[~premium_df["티커"].isin(recommend["티커"])].copy()
        else:
            premium_main = premium_df.copy()

        # 6. AI 확률 순으로 정렬
        premium_main = premium_main.sort_values(by=["AI예상상승확률(%)"], ascending=False).reset_index(drop=True)
        watch_df = watch_df.sort_values(by=["AI예상상승확률(%)"], ascending=False).reset_index(drop=True)

        # 7. HTML 생성
        html = generate_premium_html(recommend, premium_main, watch_df, trade_date)

        # 8. 메타데이터 생성
        metadata = {
            "report_type": "premium_stock",
            "total_stocks": len(df_all),
            "recommend_count": len(recommend),
            "premium_count": len(premium_main),
            "watch_count": len(watch_df),
            "generated_at": now_kr_str(),
            "filename": f"Premium_AI_Report_v4_{trade_date}.html"
        }

        print(f"[INFO] Premium 리포트 생성 완료 - 추천:{len(recommend)}, 프리미엄:{len(premium_main)}, 관심:{len(watch_df)}")

        return ReportData(html, trade_date, metadata)

    except Exception as e:
        print(f"[ERROR] Premium 리포트 생성 실패: {e}")
        traceback.print_exc()
        return None


def getUpAndDownReport():
    """
    Gap Up & Down Risk 리포트 생성 (요청된 정확한 함수명)
    
    Returns:
        ReportData: HTML 콘텐츠와 메타데이터를 담은 객체
        None: 생성 실패 시
    """
    try:
        print("[INFO] Gap Up & Down Risk 리포트 생성 시작...")

        # 1. 신호 계산
        global_signals = compute_global_signals()
        kosdaq_signals = compute_kosdaq_signals()

        # 2. 점수 및 Drivers 계산
        ku, kd, ku_drv, kd_drv = score_kospi(global_signals)
        du, dd, du_drv, dd_drv = score_kosdaq(global_signals, kosdaq_signals)

        # 3. 레벨 라벨 생성
        ku_level, ku_label = level_label(ku)
        kd_level, kd_label = level_label(kd)
        du_level, du_label = level_label(du)
        dd_level, dd_label = level_label(dd)

        # 4. 게이지 이미지 생성
        kospi_gauge = create_dual_gauge_base64(ku, kd, "KOSPI 급등/급락 게이지")
        kosdaq_gauge = create_dual_gauge_base64(du, dd, "KOSDAQ 급등/급락 게이지")

        # 5. 대응 전략 생성
        kospi_actions = build_actions("KOSPI", ku, kd)
        kosdaq_actions = build_actions("KOSDAQ", du, dd)

        # 6. 리포트 데이터 구성
        report_dict = {
            "run_time": now_kr_str(),
            "global_signals": global_signals,
            "kosdaq_signals": kosdaq_signals,

            "kospi_up": ku,
            "kospi_down": kd,
            "kosdaq_up": du,
            "kosdaq_down": dd,

            "kospi_up_label": ku_label,
            "kospi_down_label": kd_label,
            "kosdaq_up_label": du_label,
            "kosdaq_down_label": dd_label,

            "kospi_up_badge": badge_class(ku_level),
            "kospi_down_badge": badge_class(kd_level),
            "kosdaq_up_badge": badge_class(du_level),
            "kosdaq_down_badge": badge_class(dd_level),

            "kospi_gauge": kospi_gauge,
            "kosdaq_gauge": kosdaq_gauge,

            "kospi_drivers_up": ku_drv,
            "kospi_drivers_down": kd_drv,
            "kosdaq_drivers_up": du_drv,
            "kosdaq_drivers_down": dd_drv,

            "kospi_actions": kospi_actions,
            "kosdaq_actions": kosdaq_actions,
        }

        # 7. HTML 생성
        html_content = build_gap_updown_html(report_dict)

        # 8. 메타데이터 생성
        trade_date = datetime.now(TZ).strftime("%Y%m%d")
        metadata = {
            "report_type": "gap_updown_risk",
            "kospi_scores": {"up": ku, "down": kd},
            "kosdaq_scores": {"up": du, "down": dd},
            "generated_at": now_kr_str(),
            "filename": f"Gap_UpDown_Risk_Report_{trade_date}.html"
        }

        print(f"[INFO] Gap Up & Down 리포트 생성 완료")
        print(f"       KOSPI - 급등:{ku}/급락:{kd}, KOSDAQ - 급등:{du}/급락:{dd}")

        return ReportData(html_content, trade_date, metadata)

    except Exception as e:
        print(f"[ERROR] Gap Up & Down 리포트 생성 실패: {e}")
        traceback.print_exc()
        return None


# ===== 미래 확장을 위한 예시 =====

def generate_etf_report():
    """ETF 리포트 생성 (미래 확장 예시)"""
    # TODO: ETF 분석 로직 구현
    pass


def generate_crypto_report():
    """암호화폐 리포트 생성 (미래 확장 예시)"""
    # TODO: 암호화폐 분석 로직 구현
    pass


# ===== Market Summary Report 전용 함수들 =====

# ETF 설정 상수
ETF_KOSPI_MS = {
    "KODEX200": {"yf": "069500.KS", "w": 1.0, "sign": +1, "vol_win": 20},
    "KODEX_레버": {"yf": "122630.KS", "w": 1.5, "sign": +1, "vol_win": 20},
    "KODEX_인버": {"yf": "114800.KS", "w": 1.5, "sign": -1, "vol_win": 20},
}

ETF_KOSDAQ_MS = {
    "KQ150": {"yf": "229200.KS", "w": 1.0, "sign": +1, "vol_win": 30},
    "KQ150_레버": {"yf": "233740.KS", "w": 1.7, "sign": +1, "vol_win": 30},
    "KQ150_인버": {"yf": "251340.KS", "w": 1.7, "sign": -1, "vol_win": 30},
}

def _ms_normalize(df):
    """Market Summary용 DataFrame 인덱스 정규화"""
    if df is None or df.empty:
        return df
    idx = pd.to_datetime(df.index)
    try:
        idx = idx.tz_localize(None)
    except Exception:
        pass
    df = df.copy()
    df.index = idx.normalize()
    return df

def _ms_flatten_yf_columns(df):
    """Market Summary용 yfinance MultiIndex 컬럼 평탄화"""
    if df is None or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df

def _ms_make_sparkline(series):
    """Sparkline 이미지를 base64로 생성"""
    s = series.dropna().tail(15)
    if len(s) < 2:
        return ""

    fig, ax = plt.subplots(figsize=(9, 2.2))
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    ax.plot(s.values, linewidth=4, color="#d6286a")
    ax.axis("off")

    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.1, transparent=True)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()

def _ms_sparkline_comment(series):
    """Sparkline 해석 텍스트 생성"""
    s = series.dropna().tail(15)
    if len(s) < 5:
        return "최근 데이터가 부족해 흐름 판단이 어렵습니다."

    first, lastv = s.iloc[0], s.iloc[-1]
    delta = lastv - first
    slope = delta / max(len(s) - 1, 1)

    if delta >= 20 and slope > 0:
        return "Composite 흐름이 뚜렷한 상승 추세로 전환된 모습입니다."
    if 5 <= delta < 20 and slope > 0:
        return "Composite는 완만한 상승 기울기를 유지하고 있습니다."
    if -5 < delta < 5:
        return "Composite가 좁은 박스권에서 횡보하는 모습입니다."
    if delta <= -20 and slope < 0:
        return "Composite가 뚜렷한 하락 방향으로 전환되어 체력이 약해진 상태입니다."
    if -20 < delta <= -5 and slope < 0:
        return "Composite가 조정 구간에 진입한 모습입니다."
    return "단기적으로 상·하방 신호가 섞인 중립적인 흐름입니다."

def _ms_load_index(ticker, days=300):
    """Market Summary용 지수 데이터 로딩"""
    end = datetime.now(TZ).date()
    start = end - timedelta(days=days)

    try:
        warnings.filterwarnings("ignore", category=FutureWarning)
        q = yf.download(
            ticker,
            start=start,
            end=end + timedelta(days=1),
            progress=False,
            auto_adjust=False,
        )
        q = _ms_flatten_yf_columns(q)
        q = _ms_normalize(q)

        if q is None or q.empty:
            return None

        df = pd.DataFrame(index=q.index)
        df["Open"] = q["Open"]
        df["Index"] = q["Close"]
        df["Index_ret(%)"] = df["Index"].pct_change() * 100
        return df[["Open", "Index", "Index_ret(%)"]]
    except Exception as e:
        print(f"[WARNING] 지수 {ticker} 로딩 실패: {e}")
        return None

def _ms_load_etf_flow(etfs, days=300):
    """Market Summary용 ETF Flow Proxy 계산"""
    end = datetime.now(TZ).date()
    start = end - timedelta(days=days)
    combined = pd.DataFrame()

    for name, info in etfs.items():
        try:
            print(f"[Market Summary] ETF {name} 로딩 중...")
            q = yf.download(
                info["yf"],
                start=start,
                end=end + timedelta(days=1),
                progress=False,
                auto_adjust=False,
            )
            q = _ms_flatten_yf_columns(q)
            q = _ms_normalize(q)

            if q is None or q.empty:
                print(f"[WARNING] ETF {name} 데이터 없음")
                continue

            df = pd.DataFrame(index=q.index)
            df["Close"] = q["Close"]
            df["Volume"] = q["Volume"]

            ma5 = df["Close"].rolling(5).mean()
            df["price_strength"] = (df["Close"] / ma5 - 1) * 100

            vol_ma = df["Volume"].rolling(info["vol_win"]).mean()
            df["vol_ratio"] = (df["Volume"] / vol_ma).clip(0, 10)

            df[name] = info["sign"] * info["w"] * (df["price_strength"] * df["vol_ratio"])
            combined = df[[name]] if combined.empty else combined.join(df[[name]], how="outer")
        except Exception as e:
            print(f"[WARNING] ETF {name} 처리 실패: {e}")
            continue

    if combined.empty:
        return None

    combined = combined.sort_index()
    combined["Flow_Proxy"] = combined.sum(axis=1)
    return combined[["Flow_Proxy"]]

def _ms_load_macro(days=320):
    """Market Summary용 매크로 데이터 (환율 + 금리) 로딩"""
    end = datetime.now(TZ).date()
    start = end - timedelta(days=days + 60)

    try:
        fx = yf.download("KRW=X", start=start, end=end + timedelta(days=1), progress=False, auto_adjust=False)
        rt = yf.download("^TNX", start=start, end=end + timedelta(days=1), progress=False, auto_adjust=False)

        fx = _ms_normalize(_ms_flatten_yf_columns(fx))
        rt = _ms_normalize(_ms_flatten_yf_columns(rt))

        if fx is None or fx.empty:
            return None

        # TNX는 휴일에 비는 경우가 있어도 리포트는 돌아가야 함
        if rt is None or rt.empty:
            rt = pd.DataFrame(index=fx.index, data={"Close": np.nan})

        idx = sorted(set(fx.index) | set(rt.index))
        df = pd.DataFrame(index=idx)
        df["FX"] = fx["Close"].reindex(idx)
        df["Rate"] = rt["Close"].reindex(idx)

        df["FX_20d(%)"] = (df["FX"] / df["FX"].shift(20) - 1) * 100
        df["Rate_20d"] = df["Rate"] - df["Rate"].shift(20)

        return df[["FX_20d(%)", "Rate_20d"]].sort_index()
    except Exception as e:
        print(f"[WARNING] 매크로 데이터 로딩 실패: {e}")
        return None

def _ms_compute_scores(df, trend_s, trend_l, ws, wl, name):
    """Market Summary용 점수 계산 (Flow/Trend/Macro/Breadth)"""
    df = df.copy().sort_index()

    # Flow 점수
    base = df["Flow_Proxy"].abs().rolling(20).mean().clip(lower=10)
    df["Flow_score"] = (df["Flow_Proxy"] / base) * 100

    # Trend 점수
    ma_s = df["Index"].rolling(trend_s).mean()
    ma_l = df["Index"].rolling(trend_l).mean()
    df["trend_s"] = (df["Index"] / ma_s - 1) * 100
    df["trend_l"] = (df["Index"] / ma_l - 1) * 100
    df["Trend_score"] = ws * df["trend_s"] + wl * df["trend_l"]

    # Breadth 점수
    low = df["Index"].rolling(60).min()
    high = df["Index"].rolling(60).max()
    rng = (high - low).replace(0, np.nan)
    df["ClosePos"] = (df["Index"] - low) / rng * 100
    ma20 = df["Index"].rolling(20).mean()
    df["MA_gap"] = (df["Index"] / ma20 - 1) * 100
    df["Breadth_score"] = (
        0.7 * ((df["ClosePos"] - 50) / 50 * 100) +
        0.3 * (df["MA_gap"].clip(-10, 10) / 10 * 100)
    )

    # Macro 점수 (결측 보호)
    if "FX_20d(%)" in df.columns and "Rate_20d" in df.columns:
        df[["FX_20d(%)", "Rate_20d"]] = df[["FX_20d(%)", "Rate_20d"]].ffill()
        fx = df["FX_20d(%)"].fillna(0)
        rt = df["Rate_20d"].fillna(0)
        df["Macro_score"] = -(0.6 * fx + 0.4 * rt)
    else:
        df["Macro_score"] = 0.0

    # 한국어 친화 지수
    df["수급 강도"] = df["Flow_score"].clip(-60, 60) / 60 * 100
    df["추세 강도"] = df["Trend_score"].clip(-20, 20) / 20 * 100
    df["외부 환경 영향"] = df["Macro_score"].clip(-5, 5) / 5 * 100
    df["시장 건강도"] = df["Breadth_score"]

    # Composite 가중치
    if name == "KOSPI":
        w = (0.35, 0.25, 0.25, 0.15)
    else:
        w = (0.40, 0.20, 0.15, 0.25)

    df["Composite"] = (
        w[0] * df["수급 강도"] +
        w[1] * df["추세 강도"] +
        w[2] * df["외부 환경 영향"] +
        w[3] * df["시장 건강도"]
    )
    return df

def _ms_composite_band(c):
    """Composite 구간 판정"""
    if pd.isna(c):
        return "데이터 부족"
    if c >= 40:
        return "강한 상승 우위"
    if c >= 20:
        return "상승 우위"
    if c >= 5:
        return "약한 상승"
    if c <= -40:
        return "강한 하락 우위"
    if c <= -20:
        return "하락 우위"
    if c <= -5:
        return "약한 하락"
    return "중립"

def _ms_strategy_guide(c, market_name):
    """전략 가이드 텍스트 생성"""
    if pd.isna(c):
        return f"{market_name}: 데이터 결측 구간입니다. 의사결정은 보류하고, 다음 거래일 데이터 확인을 권장합니다."

    if c >= 40:
        return f"{market_name}: 강한 상승 우위 구간입니다. 추격매수보다는 '눌림 분할매수'와 '수익 구간 분할익절'을 권장합니다. 손절 기준을 사전에 고정하고 과열 종목은 비중을 제한하세요."
    if 20 <= c < 40:
        return f"{market_name}: 상승 우위 구간입니다. 우량/주도 섹터 중심으로 분할 진입을 고려할 만하며, 변동성 확대 시 추가매수 대신 비중 관리가 유리합니다."
    if 5 <= c < 20:
        return f"{market_name}: 약한 상승 구간입니다. 시장은 올라가도 종목 간 편차가 커질 수 있으므로 '선별 매매'가 유리합니다. 신규 진입은 소액/분할로 제한하고, 수익이 나면 빠른 일부익절로 리스크를 줄이세요."
    if -5 < c < 5:
        return f"{market_name}: 중립 구간입니다. 방향성이 약해 '현금 비중'과 '관망'이 합리적입니다. 매매를 하더라도 짧은 손절/짧은 목표로 대응하는 것이 안정적입니다."
    if -20 < c <= -5:
        return f"{market_name}: 약한 하락 구간입니다. 신규 매수는 보수적으로 접근하고, 기존 보유는 방어적 손절 기준을 강화하세요. 리바운드 매매는 '확인' 이후에만 소액으로 제한하는 것이 좋습니다."
    if -40 < c <= -20:
        return f"{market_name}: 하락 우위 구간입니다. 비중 축소와 현금 확보가 우선이며, 공격적 매수보다는 '관망/방어'가 유리합니다."
    return f"{market_name}: 강한 하락 우위 구간입니다. 리스크 오프 국면으로 보고 현금 비중을 높이는 전략이 합리적입니다."

def _ms_overall_strategy_comment(k, q):
    """종합 전략 코멘트"""
    if pd.isna(k) or pd.isna(q):
        return "일부 데이터 결측이 있어 해석 신뢰도가 낮습니다. 다음 거래일 데이터가 정상 반영된 뒤 다시 확인하는 것을 권장합니다."

    if k >= 20 and q >= 20:
        return "양 시장 모두 상승 우위입니다. 전반적으로 매수 환경이 우호적이나, 과열 구간에서는 추격매수보다 분할 접근과 이익 실현 규칙이 중요합니다."
    if k >= 20 > q:
        return "KOSPI가 상대적으로 강하고 KOSDAQ은 둔화된 상태입니다. 대형주/우량주 중심으로 방어적 상승 전략이 유리하며, 테마/중소형주는 선별이 필요합니다."
    if q >= 20 > k:
        return "KOSDAQ이 상대적으로 강한 구간입니다. 중소형 성장주/테마가 유리할 수 있으나 변동성도 커질 수 있어 분할매수와 손절 규칙을 더 엄격히 적용하는 것이 좋습니다."
    if k <= -20 and q <= -20:
        return "양 시장 모두 하락 우위입니다. 비중 축소와 리스크 관리가 최우선이며, 반등은 '기회'보다 '점검' 관점에서 보수적으로 대응하는 것이 안전합니다."
    return "시장 방향성이 엇갈리는 혼조 구간입니다. 지수 베팅보다 개별 종목의 추세/수급 확인이 중요하며, 현금 비중을 확보한 상태에서 선별적으로 대응하는 것이 유리합니다."

def _ms_build_html(df_k, df_q):
    """Market Summary HTML 생성 (파일 저장 없이 문자열만 반환)"""
    df_k = df_k.sort_index()
    df_q = df_q.sort_index()

    last_k = df_k.iloc[-1]
    last_q = df_q.iloc[-1]

    ck = float(last_k["Composite"]) if pd.notna(last_k["Composite"]) else np.nan
    cq = float(last_q["Composite"]) if pd.notna(last_q["Composite"]) else np.nan

    spark_k = _ms_make_sparkline(df_k["Composite"])
    spark_q = _ms_make_sparkline(df_q["Composite"])
    spark_k_txt = _ms_sparkline_comment(df_k["Composite"])
    spark_q_txt = _ms_sparkline_comment(df_q["Composite"])

    band_k = _ms_composite_band(ck)
    band_q = _ms_composite_band(cq)

    overall = _ms_overall_strategy_comment(ck, cq)
    guide_k = _ms_strategy_guide(ck, "KOSPI")
    guide_q = _ms_strategy_guide(cq, "KOSDAQ")

    # 표 생성
    cols = ["Index", "Index_ret(%)", "수급 강도", "추세 강도", "외부 환경 영향", "시장 건강도", "Composite"]
    t1 = df_k[cols].tail(15).sort_index(ascending=False).round(2).to_html(border=0, index=True)
    t2 = df_q[cols].tail(15).sort_index(ascending=False).round(2).to_html(border=0, index=True)

    # 배경색 결정
    def comp_bg(c):
        if pd.isna(c):
            return "linear-gradient(135deg, #ffffff, #ffffff)"
        if c >= 20:
            return "linear-gradient(135deg, #ffe4ef, #ffffff)"
        if c <= -20:
            return "linear-gradient(135deg, #e7f3ff, #ffffff)"
        return "linear-gradient(135deg, #ffffff, #ffffff)"

    bg_k = comp_bg(ck)
    bg_q = comp_bg(cq)
    gen_time = now_kr_str()

    # Composite 설명 블록
    composite_legend_html = """
    <div class="card">
      <div class="card-title">Composite 지수 해석 (숫자별 의미)</div>
      <div class="legend-grid">
        <div class="legend-item up-strong">
          <div class="legend-badge">+40 이상</div>
          <div class="legend-text">강한 상승 우위. 주도주/우량주 중심으로 눌림 분할 대응이 유리.</div>
        </div>
        <div class="legend-item up">
          <div class="legend-badge">+20 ~ +40</div>
          <div class="legend-text">상승 우위. 선별 매수 가능 구간. 과열 시 비중 관리 필요.</div>
        </div>
        <div class="legend-item up-weak">
          <div class="legend-badge">+5 ~ +20</div>
          <div class="legend-text">약한 상승. 종목 간 편차 확대 가능. 신규 진입은 보수적으로.</div>
        </div>
        <div class="legend-item neutral">
          <div class="legend-badge">-5 ~ +5</div>
          <div class="legend-text">중립. 방향성 약함. 관망/현금 비중 유지가 합리적.</div>
        </div>
        <div class="legend-item down-weak">
          <div class="legend-badge">-20 ~ -5</div>
          <div class="legend-text">약한 하락. 신규 매수 제한. 손절/방어 기준 강화.</div>
        </div>
        <div class="legend-item down">
          <div class="legend-badge">-40 ~ -20</div>
          <div class="legend-text">하락 우위. 비중 축소·현금 확보 우선.</div>
        </div>
        <div class="legend-item down-strong">
          <div class="legend-badge">-40 이하</div>
          <div class="legend-text">강한 하락 우위. 리스크 오프. 공격적 매수 자제.</div>
        </div>
      </div>
      <div class="note">
        Composite는 수급·추세·대외환경·시장건강도를 가중합한 "시장 컨디션 지표"이며, 수익을 보장하지 않습니다.
      </div>
    </div>
    """

    html = f"""
    <!doctype html>
    <html lang="ko">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
      <title>Market Summary v10.8</title>
      <style>
        :root {{
          --bg: #f5f6f8; --card: rgba(255,255,255,0.92); --text: #111827; --muted: #6b7280; 
          --accent: #d6286a; --shadow: 0 10px 30px rgba(0,0,0,0.10); --shadow2: 0 6px 18px rgba(0,0,0,0.08); 
          --radius: 22px;
        }}
        body {{
          margin: 0; background: radial-gradient(1200px 800px at 15% 10%, #ffe8f1 0%, rgba(255,232,241,0) 55%),
                      radial-gradient(1100px 700px at 85% 18%, #e9f4ff 0%, rgba(233,244,255,0) 55%), var(--bg);
          font-family: "맑은 고딕", system-ui, -apple-system, Segoe UI, Roboto, sans-serif; color: var(--text);
        }}
        .wrap {{ max-width: 1080px; margin: 0 auto; padding: 18px 16px 40px 16px; }}
        .topbar {{ position: sticky; top: 0; z-index: 20; backdrop-filter: blur(16px); 
                   background: rgba(15, 23, 42, 0.78); color: #fff; border-bottom: 1px solid rgba(255,255,255,0.10); }}
        .topbar-inner {{ max-width: 1080px; margin: 0 auto; padding: 14px 16px; display:flex; 
                        justify-content: space-between; align-items: center; gap: 10px; }}
        .topbar-title {{ font-weight: 900; font-size: 18px; letter-spacing: -0.2px; }}
        .topbar-meta {{ font-size: 13px; color: rgba(255,255,255,0.85); white-space: nowrap; }}
        .hero {{ margin-top: 16px; background: linear-gradient(135deg, rgba(0,0,0,0.92), rgba(17,24,39,0.92)); 
                 border-radius: var(--radius); padding: 22px 20px; box-shadow: var(--shadow); color: #fff; }}
        .hero .h-title {{ font-size: 22px; font-weight: 900; margin-bottom: 10px; color: #ffd700; letter-spacing: -0.3px; }}
        .hero .h-text {{ font-size: 16px; line-height: 1.8; font-weight: 650; color: rgba(255,255,255,0.95); }}
        .hero .h-note {{ margin-top: 10px; font-size: 13px; color: rgba(255,255,255,0.75); line-height: 1.6; }}
        .card {{ margin-top: 16px; background: var(--card); border-radius: var(--radius); padding: 18px 18px; 
                 box-shadow: var(--shadow2); border: 1px solid rgba(17,24,39,0.06); }}
        .card-title {{ font-size: 18px; font-weight: 900; letter-spacing: -0.2px; margin-bottom: 12px; }}
        .market-card {{ padding: 18px 18px 16px 18px; }}
        .market-header {{ display:flex; justify-content: space-between; align-items: flex-end; gap: 10px; 
                         flex-wrap: wrap; margin-bottom: 10px; }}
        .market-name {{ font-size: 22px; font-weight: 950; letter-spacing: -0.4px; color: var(--accent); }}
        .comp-value {{ font-size: 34px; font-weight: 950; letter-spacing: -0.6px; }}
        .pill {{ display:inline-flex; align-items:center; gap:8px; padding: 8px 12px; border-radius: 999px; 
                 font-size: 13px; font-weight: 800; background: rgba(17,24,39,0.06); color: #111827; }}
        .pill .dot {{ width: 10px; height: 10px; border-radius: 999px; background: #111827; opacity: 0.8; }}
        .spark-row {{ display:flex; align-items:center; justify-content: space-between; gap: 14px; 
                     flex-wrap: wrap; margin-top: 8px; }}
        .spark-row img {{ max-width: 520px; width: 100%; height: auto; }}
        .spark-text {{ flex: 1; min-width: 240px; font-size: 15px; color: #111827; line-height: 1.7; }}
        .kpis {{ margin-top: 12px; display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 10px; }}
        .kpi {{ background: rgba(255,255,255,0.85); border: 1px solid rgba(17,24,39,0.06); 
               border-radius: 16px; padding: 12px 12px; }}
        .kpi .k {{ font-size: 13px; color: var(--muted); font-weight: 800; }}
        .kpi .v {{ margin-top: 6px; font-size: 20px; font-weight: 950; letter-spacing: -0.3px; }}
        .guide {{ margin-top: 12px; background: rgba(17,24,39,0.04); border: 1px solid rgba(17,24,39,0.08); 
                 border-radius: 18px; padding: 14px 14px; font-size: 15px; line-height: 1.8; color: #111827; }}
        .legend-grid {{ display: grid; grid-template-columns: 1fr; gap: 10px; }}
        .legend-item {{ border-radius: 18px; padding: 12px 12px; border: 1px solid rgba(17,24,39,0.06); 
                       background: rgba(255,255,255,0.70); }}
        .legend-badge {{ display:inline-block; font-size: 13px; font-weight: 950; padding: 6px 10px; 
                        border-radius: 999px; background: rgba(17,24,39,0.08); margin-bottom: 8px; }}
        .legend-text {{ font-size: 15px; line-height: 1.7; color: #111827; }}
        .up-strong {{ background: linear-gradient(135deg, rgba(255,208,229,0.75), rgba(255,255,255,0.70)); }}
        .up {{ background: linear-gradient(135deg, rgba(255,228,239,0.85), rgba(255,255,255,0.70)); }}
        .up-weak {{ background: linear-gradient(135deg, rgba(255,245,249,0.95), rgba(255,255,255,0.70)); }}
        .neutral {{ background: linear-gradient(135deg, rgba(245,246,248,0.95), rgba(255,255,255,0.70)); }}
        .down-weak {{ background: linear-gradient(135deg, rgba(239,246,255,0.95), rgba(255,255,255,0.70)); }}
        .down {{ background: linear-gradient(135deg, rgba(231,243,255,0.95), rgba(255,255,255,0.70)); }}
        .down-strong {{ background: linear-gradient(135deg, rgba(211,232,255,0.95), rgba(255,255,255,0.70)); }}
        .note {{ margin-top: 10px; font-size: 13px; color: var(--muted); line-height: 1.7; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        table thead th {{ text-align: right; background: rgba(17,24,39,0.04); padding: 10px 10px; 
                         border-bottom: 1px solid rgba(17,24,39,0.10); font-weight: 900; }}
        table tbody td {{ text-align: right; padding: 10px 10px; border-bottom: 1px solid rgba(17,24,39,0.08); 
                         font-weight: 650; }}
        table thead th:first-child, table tbody td:first-child {{ text-align: center; font-weight: 900; }}
        @media (max-width: 768px) {{
          .wrap {{ padding: 14px 12px 34px 12px; }}
          .hero {{ padding: 18px 14px; }}
          .hero .h-title {{ font-size: 20px; }}
          .hero .h-text {{ font-size: 16px; }}
          .market-name {{ font-size: 21px; }}
          .comp-value {{ font-size: 32px; }}
          .spark-text {{ font-size: 15px; }}
          .kpis {{ grid-template-columns: 1fr; }}
          table {{ font-size: 12px; }}
        }}
      </style>
    </head>
    <body>
      <div class="topbar">
        <div class="topbar-inner">
          <div class="topbar-title">Market Summary v10.8</div>
          <div class="topbar-meta">생성: {gen_time}</div>
        </div>
      </div>

      <div class="wrap">
        <div class="hero">
          <div class="h-title">한국 주식시장 전략 코멘트</div>
          <div class="h-text">{overall}</div>
          <div class="h-note">
            본 리포트는 과거 데이터 기반의 확률적 가이드이며 미래 수익을 보장하지 않습니다. 최종 투자 판단과 책임은 투자자 본인에게 있습니다.
          </div>
        </div>

        <div class="card market-card" style="background:{bg_k};">
          <div class="market-header">
            <div>
              <div class="market-name">KOSPI</div>
              <div class="pill"><span class="dot"></span>Composite 구간: {band_k}</div>
            </div>
            <div class="comp-value">{("—" if pd.isna(ck) else f"{ck:.1f}")}</div>
          </div>

          <div class="spark-row">
            {"<img src='data:image/png;base64," + spark_k + "'>" if spark_k else ""}
            <div class="spark-text"><b>최근 흐름 해석:</b> {spark_k_txt}</div>
          </div>

          <div class="kpis">
            <div class="kpi"><div class="k">수급 강도</div><div class="v">{float(last_k["수급 강도"]):.1f}%</div></div>
            <div class="kpi"><div class="k">추세 강도</div><div class="v">{float(last_k["추세 강도"]):.1f}%</div></div>
            <div class="kpi"><div class="k">외부 환경 영향</div><div class="v">{float(last_k["외부 환경 영향"]):.1f}%</div></div>
            <div class="kpi"><div class="k">시장 건강도</div><div class="v">{float(last_k["시장 건강도"]):.1f}%</div></div>
          </div>

          <div class="guide"><b>대응 가이드:</b> {guide_k}</div>
        </div>

        <div class="card market-card" style="background:{bg_q};">
          <div class="market-header">
            <div>
              <div class="market-name">KOSDAQ</div>
              <div class="pill"><span class="dot"></span>Composite 구간: {band_q}</div>
            </div>
            <div class="comp-value">{("—" if pd.isna(cq) else f"{cq:.1f}")}</div>
          </div>

          <div class="spark-row">
            {"<img src='data:image/png;base64," + spark_q + "'>" if spark_q else ""}
            <div class="spark-text"><b>최근 흐름 해석:</b> {spark_q_txt}</div>
          </div>

          <div class="kpis">
            <div class="kpi"><div class="k">수급 강도</div><div class="v">{float(last_q["수급 강도"]):.1f}%</div></div>
            <div class="kpi"><div class="k">추세 강도</div><div class="v">{float(last_q["추세 강도"]):.1f}%</div></div>
            <div class="kpi"><div class="k">외부 환경 영향</div><div class="v">{float(last_q["외부 환경 영향"]):.1f}%</div></div>
            <div class="kpi"><div class="k">시장 건강도</div><div class="v">{float(last_q["시장 건강도"]):.1f}%</div></div>
          </div>

          <div class="guide"><b>대응 가이드:</b> {guide_q}</div>
        </div>

        {composite_legend_html}

        <div class="card">
          <div class="card-title">최근 15일 KOSPI 지표 흐름</div>
          {t1}
          <div class="note">지표는 거래일 기준이며, 휴일/주말 데이터 결측은 자동 보정 처리됩니다.</div>
        </div>

        <div class="card">
          <div class="card-title">최근 15일 KOSDAQ 지표 흐름</div>
          {t2}
          <div class="note">지표는 거래일 기준이며, 휴일/주말 데이터 결측은 자동 보정 처리됩니다.</div>
        </div>

        <div class="card">
          <div class="card-title">이 리포트가 계산되는 방식</div>
          <div style="font-size:15px; line-height:1.9; color:#111827;">
            <ul style="margin:0; padding-left:18px;">
              <li><b>수급 강도</b>: 대표 ETF의 가격·거래량 기반 Flow Proxy로 매수/매도 힘을 수치화합니다.</li>
              <li><b>추세 강도</b>: 지수의 단기/중기 이동평균 대비 괴리를 조합해 추세의 힘을 반영합니다.</li>
              <li><b>외부 환경 영향</b>: 환율(20일 변화)과 미국 10년물 금리(20일 변화)를 반영합니다.</li>
              <li><b>시장 건강도</b>: 최근 60일 범위 내 위치와 20일선 괴리를 조합합니다.</li>
              <li><b>Composite</b>: 위 4개 지수를 시장 특성에 맞게 가중 평균한 "시장 컨디션 지표"입니다.</li>
            </ul>
          </div>
          <div class="note">
            ※ 본 자료는 교육/정보 제공 목적이며, 투자 손익은 본인 책임입니다.
          </div>
        </div>
      </div>
    </body>
    </html>
    """
    return html

def generate_market_summary_report():
    """
    Market Summary v10.8 리포트 생성
    
    Returns:
        ReportData: HTML 콘텐츠와 메타데이터를 담은 객체
        None: 생성 실패 시
    """
    try:
        print("[INFO] Market Summary v10.8 리포트 생성 시작...")

        # 1) KOSPI 데이터 로딩
        df_k_idx = _ms_load_index("^KS200")
        df_k_flow = _ms_load_etf_flow(ETF_KOSPI_MS)
        
        if df_k_idx is None or df_k_flow is None:
            raise ValueError("KOSPI 데이터 로딩 실패")
        
        df_k = df_k_idx.join(df_k_flow, how="inner")

        # 2) KOSDAQ 데이터 로딩
        df_q_idx = _ms_load_index("^KQ11")
        df_q_flow = _ms_load_etf_flow(ETF_KOSDAQ_MS)
        
        if df_q_idx is None or df_q_flow is None:
            raise ValueError("KOSDAQ 데이터 로딩 실패")
        
        df_q = df_q_idx.join(df_q_flow, how="inner")

        # 3) 매크로 데이터 로딩 (실패해도 진행)
        df_macro = _ms_load_macro()
        if df_macro is not None:
            df_k = df_k.join(df_macro, how="left")
            df_q = df_q.join(df_macro, how="left")

        # 4) 점수 계산
        df_k = _ms_compute_scores(df_k, trend_s=20, trend_l=60, ws=0.5, wl=0.5, name="KOSPI")
        df_q = _ms_compute_scores(df_q, trend_s=10, trend_l=30, ws=0.6, wl=0.4, name="KOSDAQ")

        # 5) HTML 생성
        html_content = _ms_build_html(df_k, df_q)

        # 6) 메타데이터 생성
        # 6) 메타데이터 생성
        trade_date = datetime.now(TZ).strftime("%Y%m%d")
        
        last_k = df_k.iloc[-1]
        last_q = df_q.iloc[-1]
        
        ck = float(last_k["Composite"]) if pd.notna(last_k["Composite"]) else None
        cq = float(last_q["Composite"]) if pd.notna(last_q["Composite"]) else None
        
        metadata = {
            "report_type": "market_summary",
            "kospi_composite": ck,
            "kosdaq_composite": cq,
            "kospi_band": _ms_composite_band(ck),
            "kosdaq_band": _ms_composite_band(cq),
            "generated_at": now_kr_str(),
            "filename": f"Market_Summary_v10_8_{trade_date}.html"
        }

        # 🔧 수정된 출력 부분 (오류 해결)
        ck_str = f"{ck:.1f}" if ck is not None else "N/A"
        cq_str = f"{cq:.1f}" if cq is not None else "N/A"

        print(f"[INFO] Market Summary 리포트 생성 완료")
        print(f"       KOSPI Composite: {ck_str} ({metadata['kospi_band']})")
        print(f"       KOSDAQ Composite: {cq_str} ({metadata['kosdaq_band']})")

        return ReportData(html_content, trade_date, metadata)

    except Exception as e:
        print(f"[ERROR] Market Summary 리포트 생성 실패: {e}")
        traceback.print_exc()
        return None
# ===== Market Supply Report 전용 함수들 =====

# 상수 정의
SUPPLY_FLOW_WINDOW_DAYS = 7
SUPPLY_LIST_MIN_MCAP = 300_000_000_000
SUPPLY_MIN_MCAP = 100_000_000_000
SUPPLY_MIN_TV = 50_000_000_000
SUPPLY_MIN_TURNOVER = 1.0
SUPPLY_PREMIUM_MAX_R3 = 10.0
SUPPLY_FAST_MIN_RETURN_1D = 10.0
SUPPLY_FAST_MIN_FLOW1D_TV = 3.0
SUPPLY_OVERHEAT_3D = 20.0
SUPPLY_OVERHEAT_5D = 30.0
SUPPLY_INTEREST_MIN_FLOW_3D_MCAP = 0.3
SUPPLY_INTEREST_MAX_RISE_3D = 10.0
SUPPLY_TOP_PER_SECTION = 30

def _supply_to_number(x):
    """숫자 변환 헬퍼"""
    if isinstance(x, (int, float)):
        return float(x)
    try:
        s = str(x).strip()
        if s in ("", "-", "None", "nan"):
            return 0.0
        return float(s.replace(",", ""))
    except Exception:
        return 0.0

def _supply_pick_col(df, names):
    """컬럼 선택 헬퍼"""
    for c in names:
        if c in df.columns:
            return c
    raise KeyError(f"필요 컬럼을 찾지 못했습니다: {names}")

def _supply_get_recent_trading_dates(last_date_str, n_days):
    """최근 N개 거래일 목록 조회"""
    last_dt = datetime.strptime(last_date_str, "%Y%m%d")
    days = []
    d = last_dt
    while len(days) < n_days:
        if d.weekday() < 5:  # 평일만
            ds = d.strftime("%Y%m%d")
            try:
                # 실제 거래일인지 확인 (삼성전자로 테스트)
                if not stock.get_market_ohlcv_by_date(ds, ds, "005930").empty:
                    days.append(ds)
            except Exception:
                pass
        d -= timedelta(days=1)
    return sorted(days)

def _supply_safe_return(closes, days):
    """안전한 수익률 계산"""
    if len(closes) <= days:
        return 0.0
    try:
        base = closes.iloc[-(days + 1)]
        last = closes.iloc[-1]
        if base == 0 or pd.isna(base) or pd.isna(last):
            return 0.0
        return (last / base - 1.0) * 100.0
    except Exception:
        return 0.0

class _SupplyKrxJson:
    """KRX JSON API 래퍼 (Market Supply 전용)"""
    
    URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://data.krx.co.kr"
        })

    def get_all(self, date):
        """전체 종목 데이터 조회"""
        payload = {
            "bld": "dbms/MDC/STAT/standard/MDCSTAT01501",
            "mktId": "ALL",
            "trdDd": date,
            "share": "1",
            "money": "1"
        }
        
        try:
            r = self.s.post(self.URL, data=payload, timeout=25)
            r.raise_for_status()
            j = r.json()
            rows = j.get("OutBlock_1", j.get("output", []))
            df = pd.DataFrame(rows)
            
            if df.empty:
                return df

            # 필수 컬럼 확인 및 매핑
            code = _supply_pick_col(df, ["ISU_SRT_CD"])
            name = _supply_pick_col(df, ["ISU_ABBRV"])
            mkt = _supply_pick_col(df, ["MKT_NM"])
            close = _supply_pick_col(df, ["TDD_CLSPRC"])
            tv = _supply_pick_col(df, ["ACC_TRDVAL"])
            mcap = _supply_pick_col(df, ["MKTCAP"])
            fluc = _supply_pick_col(df, ["FLUC_RT"])

            out = pd.DataFrame({
                "티커": df[code].astype(str),
                "종목명": df[name].astype(str),
                "시장": df[mkt].astype(str),
                "종가": df[close].map(_supply_to_number),
                "거래대금": df[tv].map(_supply_to_number),
                "시가총액": df[mcap].map(_supply_to_number),
                "등락률_당일(%)": df[fluc].map(_supply_to_number),
            })

            # ETF/ETN/스팩/우선주 제외
            mask = (
                out["종목명"].str.contains("ETF|ETN|스팩|SPAC", na=False) |
                out["종목명"].str.endswith("우", na=False)
            )
            out = out[~mask].copy()

            # 유효 데이터 필터링
            out = out[(out["거래대금"] > 0) & (out["시가총액"] > 0)].reset_index(drop=True)
            out["시총대비_거래대금(%)"] = out["거래대금"] / out["시가총액"] * 100.0
            
            return out
            
        except Exception as e:
            print(f"[ERROR] KRX API 호출 실패: {e}")
            return pd.DataFrame()

def _supply_fetch_detail(row, trade_dates, calendar, fdr_start, fdr_end):
    """개별 종목 상세 분석"""
    t = row["티커"]

    try:
        # FinanceDataReader로 가격 데이터 조회
        price_all = fdr.DataReader(t, fdr_start, fdr_end)
    except Exception as e:
        print(f"[WARNING] FDR 조회 실패 {t}: {e}")
        return None

    if price_all is None or price_all.empty or "Close" not in price_all.columns:
        return None

    # 캘린더 기간으로 슬라이싱
    price_slice = price_all.loc[calendar.min(): calendar.max()]
    price_win = price_slice.reindex(calendar)
    closes = price_win["Close"]

    if closes.notna().sum() < 6:
        return None

    closes = closes.ffill()
    if closes.isna().any():
        return None

    # 기관/외국인 순매수 데이터 (pykrx 사용)
    try:
        vol_raw = stock.get_market_trading_volume_by_date(
            trade_dates[0], trade_dates[-1], t
        )
    except Exception:
        vol_raw = pd.DataFrame()

    if vol_raw.empty:
        inst = pd.Series([0.0] * len(calendar), index=calendar)
        fore = pd.Series([0.0] * len(calendar), index=calendar)
    else:
        vol = vol_raw.reindex(calendar).fillna(0.0)
        if "기관합계" not in vol.columns or "외국인합계" not in vol.columns:
            return None
        inst = vol["기관합계"]
        fore = vol["외국인합계"]

    # Flow 계산 (순매수 * 주가)
    flows = (inst + fore) * closes

    tot_1 = float(flows.iloc[-1])
    tot_3 = float(flows.iloc[-3:].sum())
    tot_5 = float(flows.iloc[-5:].sum())

    mcap = float(row["시가총액"])
    tv = float(row["거래대금"])

    # 비율 계산
    pct1_mcap = (tot_1 / mcap * 100.0) if mcap else 0.0
    pct3_mcap = (tot_3 / mcap * 100.0) if mcap else 0.0
    pct5_mcap = (tot_5 / mcap * 100.0) if mcap else 0.0
    pct1_tv = (tot_1 / tv * 100.0) if tv else 0.0

    r3 = _supply_safe_return(closes, 3)
    r5 = _supply_safe_return(closes, 5)

    # 프리미엄 플래그 (최근 3일 연속 순매수)
    last3 = flows.iloc[-3:]
    premium_flag = bool((last3 > 0).all())

    # 선취매 강도 점수 계산 (0~100)
    strength_raw = (
        pct3_mcap * 40.0 +
        pct1_mcap * 30.0 +
        pct5_mcap * 20.0 +
        (10.0 if premium_flag else 0.0)
    )
    strength = round(min(max(strength_raw, 0.0), 100.0), 2)

    return {
        "티커": t,
        "원본종목명": row["종목명"],
        "종목명": row["종목명"],
        "종가(원)": f"{int(row['종가']):,}",
        "등락률_당일(%)": round(float(row["등락률_당일(%)"]), 2),
        "시가총액(억)": round(mcap / 1e8, 1),
        "거래대금(억)": round(tv / 1e8, 1),
        "시총대비_거래대금(%)": round(float(row["시총대비_거래대금(%)"]), 2),
        "3일수익률(%)": round(r3, 2),
        "5일수익률(%)": round(r5, 2),
        "합산_1일(억)": round(tot_1 / 1e8, 2),
        "합산_3일(억)": round(tot_3 / 1e8, 2),
        "합산_5일(억)": round(tot_5 / 1e8, 2),
        "1일_순매수/거래대금(%)": round(pct1_tv, 2),
        "3일_순매수/시총(%)": round(pct3_mcap, 3),
        "5일_순매수/시총(%)": round(pct5_mcap, 3),
        "선취매강도점수": strength,
        "_flag_premium": premium_flag,
        "_mcap": mcap
    }

def _supply_style_name(name, score):
    """종목명 스타일링 (선취매 강도 100점만 빨강)"""
    if round(score, 2) >= 100.0:
        return f"<span class='name red'>{name}</span>"
    return f"<span class='name'>{name}</span>"

def _supply_render_table(df):
    """테이블 HTML 렌더링"""
    if df.empty:
        return "<div class='empty'>조건에 맞는 종목이 없습니다.</div>"

    show = df.head(SUPPLY_TOP_PER_SECTION).copy()
    show["종목명"] = show.apply(
        lambda r: _supply_style_name(r["원본종목명"], float(r["선취매강도점수"])), axis=1
    )

    cols = [
        "종목명", "종가(원)", "등락률_당일(%)", "3일수익률(%)", "5일수익률(%)",
        "시가총액(억)", "거래대금(억)", "시총대비_거래대금(%)",
        "합산_1일(억)", "합산_3일(억)", "합산_5일(억)",
        "1일_순매수/거래대금(%)", "3일_순매수/시총(%)", "5일_순매수/시총(%)",
        "선취매강도점수",
    ]
    show = show[cols].copy()

    # 모바일에서 숨길 컬럼
    mobile_hide_cols = {"합산_5일(억)", "5일_순매수/시총(%)", "3일_순매수/시총(%)"}

    # 테이블 헤더
    ths = []
    for c in show.columns:
        cls = "m-hide" if c in mobile_hide_cols else ""
        ths.append(f"<th class='{cls}'>{c}</th>")

    # 테이블 본문
    trs = []
    for _, row in show.iterrows():
        tds = []
        for c in show.columns:
            cls = "m-hide" if c in mobile_hide_cols else ""
            tds.append(f"<td class='{cls}'>{row[c]}</td>")
        trs.append("<tr>" + "".join(tds) + "</tr>")

    return f"""
    <div class="table-wrap">
      <table>
        <thead><tr>{''.join(ths)}</tr></thead>
        <tbody>{''.join(trs)}</tbody>
      </table>
    </div>
    """

def _supply_build_html(trade_date, premium, fast, overheat, interest):
    """Market Supply Report HTML 생성 (파일 저장 없이 문자열만 반환)"""
    
    date_fmt = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d (%A)")
    
    warning_text = """
    ※ 이 종목은 데이터에 기반한 통계적인 추천일 뿐이며 100% 확실한 보장이 아닙니다.<br>
    시장 전체의 갑작스러운 급변이나 개별 종목의 악재 뉴스로 인한 갑작스러운 변동이 있을 수 있으니,
    투자 결정은 반드시 본인의 판단 하에 신중하게 진행하시기 바랍니다.
    """

    # 요약 카드 생성
    def best_row(df):
        return None if df.empty else df.iloc[0]

    b_p = best_row(premium)
    b_f = best_row(fast)
    b_i = best_row(interest)

    summary_lines = []
    if b_p is not None:
        summary_lines.append(
            f"• 프리미엄 1순위: <b>{b_p['원본종목명']}</b> (선취매 {b_p['선취매강도점수']}점) — 3일 연속 매수 + 3일 수익률 제한 구간"
        )
    if b_f is not None:
        summary_lines.append(
            f"• Fast(스윙): <b>{b_f['원본종목명']}</b> — 당일 모멘텀 강함, 분할 매매 권장"
        )
    if b_i is not None:
        summary_lines.append(
            f"• 중장기 관심: <b>{b_i['원본종목명']}</b> — 관심 편입 후 분할 관찰"
        )
    if not summary_lines:
        summary_lines.append("• 오늘은 강한 후보가 제한적입니다. 지수/변동성 확인 후 보수적으로 접근하세요.")

    summary_html = f"""
    <div class="card summary">
      <div class="summary-title">요약 전략 코멘트</div>
      <div class="summary-body">{'<br>'.join(summary_lines)}</div>
    </div>
    """

    # 섹션별 설명
    premium_desc = f"""
    <div class="desc">
      • '프리미엄 추천 종목'은 최근 <b>3거래일 연속</b> 기관+외국인 순매수이며,
        <b>3일 수익률이 {SUPPLY_PREMIUM_MAX_R3}% 이하</b>인 종목입니다.<br>
      • "수급은 들어오지만 가격은 아직 덜 오른" 후보를 우선적으로 포착합니다.
    </div>
    """
    
    fast_desc = """
    <div class="desc">
      • Fast(스윙)은 당일 강한 모멘텀과 수급이 함께 나타난 종목입니다.<br>
      • 분할 진입·분할 매도로 변동성을 관리하는 접근이 안정적입니다.
    </div>
    """
    
    overheat_desc = """
    <div class="desc">
      • 과열 구간은 최근 3~5거래일 급등한 종목입니다.<br>
      • 신규 진입보다 차익실현/관망 관점이 우선입니다.
    </div>
    """
    
    interest_desc = """
    <div class="desc">
      • 중장기 관심 종목은 수급 대비 주가 상승이 제한적인 후보입니다.<br>
      • 관심 편입 후 눌림/조정 구간에서 분할 접근을 고려할 수 있습니다.
    </div>
    """

    # 선취매 강도 설명
    strength_explain = f"""
    <div class="card legend">
      <div class="legend-title">선취매 강도 점수 계산 및 해석</div>
      <div class="legend-body">
        <b>계산 공식 (0~100점)</b><br>
        • 3일 순매수/시총(%) × 40<br>
        • 1일 순매수/시총(%) × 30<br>
        • 5일 순매수/시총(%) × 20<br>
        • 최근 3거래일 연속 순매수이면 +10점<br><br>

        <b>해석</b><br>
        • "기관·외국인이 시가총액 대비 얼마나 강하게, 그리고 연속으로 담는가"를 0~100점으로 단순화한 지표입니다.<br>
        • 점수가 높을수록 '매집 강도'가 높다고 해석할 수 있으나, 급변 시장/악재 등으로 결과가 달라질 수 있습니다.<br><br>

        <b>표시 규칙</b><br>
        • 본 리포트에서는 선취매 강도 점수가 <b>100점인 종목만</b> 종목명을 붉게 표시합니다.
      </div>
    </div>
    """

    # 스타일 (모바일 최적화)
    style = """
    <style>
      :root{
        --bg:#ffffff; --ink:#0b0b0b; --muted:#4b4b4b; --line:#111111;
        --line-soft:#d7d7d7; --card:#fafafa; --red:#b30000;
      }
      *{box-sizing:border-box}
      body{
        margin:0; background:var(--bg); color:var(--ink);
        font-family: "Pretendard","Segoe UI",system-ui,-apple-system,"Malgun Gothic",sans-serif;
      }
      .wrap{max-width:1200px; margin:0 auto; padding:24px 14px 60px;}
      .header{
        display:flex; justify-content:space-between; align-items:flex-end;
        border-bottom:2px solid var(--line); padding-bottom:12px; gap:12px; flex-wrap:wrap;
      }
      .header h1{margin:0; font-size:28px; letter-spacing:-0.02em;}
      .header .date{color:var(--muted); font-size:14px; margin-top:6px;}
      .badge{
        font-size:12px; padding:7px 12px; border:1px solid var(--line);
        border-radius:999px; background:#fff; color:var(--ink);
        letter-spacing:0.08em; text-transform:uppercase;
      }
      .warn{
        margin-top:14px; padding:14px 14px; border:1px solid var(--line-soft); background:#fff;
        border-radius:14px; color:var(--muted); font-size:14px; line-height:1.65;
      }
      .card{
        margin-top:16px; padding:16px 16px; border:1px solid var(--line-soft);
        border-radius:16px; background:var(--card);
      }
      .summary-title{font-weight:900; font-size:16px; margin-bottom:10px;}
      .summary-body{font-size:14px; color:var(--muted); line-height:1.75;}
      .section{margin-top:26px;}
      .section h2{
        margin:0; font-size:20px; padding-bottom:10px; border-bottom:2px solid var(--line);
        display:flex; align-items:baseline; justify-content:space-between; gap:10px; flex-wrap:wrap;
      }
      .pill{
        font-size:12px; border:1px solid var(--line-soft); background:#fff;
        padding:6px 10px; border-radius:999px; color:var(--muted); white-space:nowrap;
      }
      .desc{margin-top:12px; color:var(--muted); font-size:14px; line-height:1.75;}
      .table-wrap{
        margin-top:14px; overflow-x:auto; -webkit-overflow-scrolling:touch;
        border:1px solid var(--line); border-radius:14px; background:#fff;
      }
      table{width:100%; border-collapse:collapse; min-width:980px; font-size:14px;}
      th{
        background:#000; color:#fff; padding:12px 10px; border-bottom:1px solid #000;
        position:sticky; top:0; white-space:nowrap;
      }
      td{
        padding:12px 10px; border-bottom:1px solid var(--line-soft);
        text-align:center; white-space:nowrap;
      }
      tr:nth-child(even) td{background:#fbfbfb;}
      tr:hover td{background:#f2f2f2;}
      .empty{margin-top:12px; padding:10px 2px; font-size:14px; color:var(--muted);}
      .name{font-weight:700; color:var(--ink); font-size:inherit;}
      .name.red{color:var(--red); font-weight:800;}
      .legend-title{font-weight:900; font-size:16px; margin-bottom:10px;}
      .legend-body{font-size:14px; color:var(--muted); line-height:1.75;}
      @media (max-width: 640px){
        .wrap{padding:18px 12px 60px;}
        .header h1{font-size:24px;}
        .badge{font-size:11px;}
        .warn{font-size:13px;}
        .summary-body{font-size:13px;}
        .desc{font-size:13px;}
        table{min-width:820px; font-size:13px;}
        th,td{padding:10px 8px;}
        .m-hide{display:none;}
      }
    </style>
    """

    html = f"""
    <!doctype html>
    <html lang="ko">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      {style}
    </head>
    <body>
      <div class="wrap">
        <div class="header">
          <div>
            <h1>기관·외국인 수급 리포트 Rev9.1</h1>
            <div class="date">기준일: {date_fmt}</div>
          </div>
          <div class="badge">MOBILE FRIENDLY</div>
        </div>

        <div class="warn">{warning_text}</div>

        {summary_html}

        <div class="section">
          <h2>
            <span>프리미엄 추천 종목 (선취매 기반)</span>
            <span class="pill">정렬: 선취매 강도 내림차순</span>
          </h2>
          {premium_desc}
          {_supply_render_table(premium)}
        </div>

        <div class="section">
          <h2>
            <span>Fast 종목 (스윙 관점)</span>
            <span class="pill">정렬: 선취매 강도 내림차순</span>
          </h2>
          {fast_desc}
          {_supply_render_table(fast)}
        </div>

        <div class="section">
          <h2>
            <span>과열 종목 (단타 위험 구간)</span>
            <span class="pill">정렬: 선취매 강도 내림차순</span>
          </h2>
          {overheat_desc}
          {_supply_render_table(overheat)}
        </div>

        <div class="section">
          <h2>
            <span>중장기 관심 종목</span>
            <span class="pill">정렬: 선취매 강도 내림차순</span>
          </h2>
          {interest_desc}
          {_supply_render_table(interest)}
        </div>

        {strength_explain}

      </div>
    </body>
    </html>
    """
    return html

def generate_market_supply_report():
    """
    Market Supply (수급) 리포트 생성
    
    Returns:
        ReportData: HTML 콘텐츠와 메타데이터를 담은 객체
        None: 생성 실패 시
    """
    try:
        print("[INFO] Market Supply 리포트 생성 시작...")

        # 1. 거래일 설정
        trade_date = get_trade_date()  # 기존 공통 함수 사용
        trade_dates = _supply_get_recent_trading_dates(trade_date, SUPPLY_FLOW_WINDOW_DAYS)
        calendar = pd.to_datetime(trade_dates)

        fdr_start_dt = calendar[0] - pd.Timedelta(days=7)
        fdr_start = fdr_start_dt.strftime("%Y-%m-%d")
        fdr_end = calendar[-1].strftime("%Y-%m-%d")

        print(f"[Supply] 기준일: {trade_date}")
        print(f"[Supply] 분석 기간: {trade_dates[0]} ~ {trade_dates[-1]}")

        # 2. KRX API로 기본 종목 목록 로딩
        krx = _SupplyKrxJson()
        base = krx.get_all(trade_date)
        
        if base.empty:
            print("[INFO] Supply: KRX 데이터 조회 실패 또는 데이터 없음")
            return None

        # 기본 필터 적용
        cond = (
            (base["시가총액"] >= SUPPLY_MIN_MCAP) &
            (base["거래대금"] >= SUPPLY_MIN_TV) &
            (base["시총대비_거래대금(%)"] >= SUPPLY_MIN_TURNOVER)
        )
        base = base[cond].copy()
        print(f"[Supply] 1차 필터 통과 종목 수: {len(base)}")

        if base.empty:
            print("[INFO] Supply: 기본 조건을 만족하는 종목이 없습니다.")
            return None

        # 3. 상세 분석
        rows = []
        for _, r in tqdm(base.iterrows(), total=len(base), desc="[Supply] 상세 분석"):
            x = _supply_fetch_detail(r, trade_dates, calendar, fdr_start, fdr_end)
            if x:
                rows.append(x)

        if not rows:
            print("[INFO] Supply: 상세 분석 결과가 없습니다.")
            return None

        df = pd.DataFrame(rows)
        print(f"[Supply] 상세 계산 완료 종목 수: {len(df)}")

        # 4. 리스트 표시 최소 시총 필터
        df = df[df["_mcap"] >= SUPPLY_LIST_MIN_MCAP].copy()

        # 5. 4개 섹션 분류
        premium = df[
            (df["_flag_premium"] == True) & 
            (df["3일수익률(%)"] <= SUPPLY_PREMIUM_MAX_R3)
        ].copy()
        
        fast = df[
            (df["등락률_당일(%)"] >= SUPPLY_FAST_MIN_RETURN_1D) &
            (df["1일_순매수/거래대금(%)"] >= SUPPLY_FAST_MIN_FLOW1D_TV) &
            (df["3일수익률(%)"] < SUPPLY_OVERHEAT_3D)
        ].copy()
        
        overheat = df[
            (df["3일수익률(%)"] >= SUPPLY_OVERHEAT_3D) | 
            (df["5일수익률(%)"] >= SUPPLY_OVERHEAT_5D)
        ].copy()
        
        interest = df[
            (df["3일_순매수/시총(%)"] >= SUPPLY_INTEREST_MIN_FLOW_3D_MCAP) &
            (df["3일수익률(%)"] <= SUPPLY_INTEREST_MAX_RISE_3D)
        ].copy()
        # 프리미엄과 중복 제거
        interest = interest[~interest["티커"].isin(premium["티커"])].copy()

        # 6. 선취매 강도 점수 순 정렬
        for t in [premium, fast, overheat, interest]:
            if not t.empty:
                t.sort_values("선취매강도점수", ascending=False, inplace=True)

        # 7. HTML 생성
        html_content = _supply_build_html(trade_date, premium, fast, overheat, interest)

        # 8. 메타데이터 생성
        metadata = {
            "report_type": "market_supply",
            "premium_count": len(premium),
            "fast_count": len(fast),
            "overheat_count": len(overheat),
            "interest_count": len(interest),
            "total_analyzed": len(df),
            "generated_at": now_kr_str(),
            "filename": f"Market_Supply_Rev9_1_{trade_date}.html"
        }

        print(f"[INFO] Market Supply 리포트 생성 완료")
        print(f"       프리미엄: {len(premium)}, Fast: {len(fast)}, 과열: {len(overheat)}, 관심: {len(interest)}")

        return ReportData(html_content, trade_date, metadata)

    except Exception as e:
        print(f"[ERROR] Market Supply 리포트 생성 실패: {e}")
        traceback.print_exc()
        return None
    

# ===== 테스트용 메인 함수 =====

if __name__ == "__main__":
    """
    이 모듈을 직접 실행했을 때 테스트용 리포트 생성
    """
    os.makedirs("out", exist_ok=True)

    print("=== 리포트 생성 테스트 시작 ===")

    # 프리미엄 주식 리포트 테스트
    premium = generate_premium_stock_report()
    if premium:
        path1 = os.path.join("out", premium.metadata["filename"])
        with open(path1, "w", encoding="utf-8") as f:
            f.write(premium.html_content)
        print(f"[TEST] Premium report saved: {path1}")

    # Gap Up & Down 리포트 테스트
    updown = getUpAndDownReport()
    if updown:
        path2 = os.path.join("out", updown.metadata["filename"])
        with open(path2, "w", encoding="utf-8") as f:
            f.write(updown.html_content)
        print(f"[TEST] GapUpDown report saved: {path2}")

    print("=== 테스트 완료 ===")
