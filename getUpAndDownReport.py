#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gap Up & Down Risk Report v7.2 (Stable, Mobile-First, Pro Explanations)
- KOSPI/KOSDAQ 급등/급락 통합 점수 + 근거(Drivers) + 대응전략 + 지표설명
- VIX9D + MOVE + 야간선물(최근 4시간) + 환율/달러 + BTC + 금리(TNX) 반영
- HTML 리포트 자동 생성 + Windows 기본 브라우저 자동 오픈
"""

import os
import io
import base64
import datetime as dt
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib

# ======================================================
# 환경 설정
# ======================================================
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

SEOUL = dt.timezone(dt.timedelta(hours=9))
OUT_DIR = "out"

KOSPI200_TICKER = "KOSPI200.KS"
KOSDAQ150_TICKER = "KQ150.KS"

# 선물 티커 (메인 실패 시 대체)
FUTURES = {
    "ES": {"main": "ES=F", "alt": "MES=F"},   # S&P500 / Micro
    "NQ": {"main": "NQ=F", "alt": "MNQ=F"},   # Nasdaq / Micro
}

# ======================================================
# 유틸
# ======================================================
def now_kr_str():
    return dt.datetime.now(SEOUL).strftime("%Y-%m-%d %H:%M:%S KST")

def safe_float(v):
    try:
        if v is None:
            return np.nan
        return float(v)
    except Exception:
        return np.nan

def pct(a, b):
    """단순 수익률(%)"""
    a = safe_float(a)
    b = safe_float(b)
    if np.isnan(a) or np.isnan(b) or b == 0:
        return np.nan
    return (a / b - 1.0) * 100.0

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
        df.dropna(how="all", inplace=True)
        return df
    except Exception:
        return None

def last_close(df, n=1):
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
    df = safe_fetch(main_ticker, period=period, interval=interval)
    if df is None or len(df) < 2:
        df = safe_fetch(alt_ticker, period=period, interval=interval)
    return df

def fmt(v, nd=3):
    v = safe_float(v)
    if np.isnan(v):
        return "NaN"
    if abs(v) >= 1000:
        return f"{v:.1f}"
    return f"{v:.{nd}f}"

# ======================================================
# 신호 계산
# ======================================================
def compute_global_signals():
    """
    글로벌/공통 신호를 dict로 반환.
    각 항목: key -> {value, unit, desc}
    """
    signals = {}

    # 1) 미국 선물 (일간, 최근 4시간)
    for name, tick in FUTURES.items():
        df_d = fetch_with_fallback(tick["main"], tick["alt"], period="3d", interval="1d")
        ret_d = pct(last_close(df_d), last_close(df_d, 2)) if df_d is not None and len(df_d) >= 2 else np.nan
        signals[f"{name}_ret_d"] = {"value": ret_d, "unit": "%", "desc": f"{name} 선물 일간 변화"}

        # 4시간(1h*4): 메인 티커 먼저, 실패하면 alt 티커로 시도
        df_h = safe_fetch(tick["main"], period="1d", interval="60m")
        if df_h is None or len(df_h) < 4:
            df_h = safe_fetch(tick["alt"], period="1d", interval="60m")
        ret_4h = pct(last_close(df_h), last_close(df_h, 4)) if df_h is not None and len(df_h) >= 4 else np.nan
        signals[f"{name}_ret_4h"] = {"value": ret_4h, "unit": "%", "desc": f"{name} 선물 최근 4시간 변화(야간 프록시)"}

    # 2) BTC (일간 + 3시간)
    btc_d = safe_fetch("BTC-USD", period="5d", interval="1d")
    btc_h = safe_fetch("BTC-USD", period="1d", interval="60m")
    signals["BTC_ret_d"] = {"value": pct(last_close(btc_d), last_close(btc_d, 2)) if btc_d is not None and len(btc_d) >= 2 else np.nan,
                            "unit": "%", "desc": "비트코인 일간 변화"}
    signals["BTC_ret_3h"] = {"value": pct(last_close(btc_h), last_close(btc_h, 3)) if btc_h is not None and len(btc_h) >= 3 else np.nan,
                             "unit": "%", "desc": "비트코인 최근 3시간 변화"}

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

    # 6) 국내 참고: KOSPI200 (전일대비)
    k200 = safe_fetch(KOSPI200_TICKER, period="10d", interval="1d")
    k200_ret = pct(last_close(k200), last_close(k200, 2)) if k200 is not None and len(k200) >= 2 else np.nan
    signals["KOSPI200_ret_d"] = {"value": k200_ret, "unit": "%", "desc": "KOSPI200 일간 수익률(참고)"}

    return signals

def compute_kosdaq_signals():
    """
    코스닥 전용: KOSDAQ150 기반
    - 일간 수익률
    - 5일 ATR% (변동성)
    - 장대 음봉 (하락 + 일중Range가 ATR의 1.5배 이상)
    """
    s = {}
    df = safe_fetch(KOSDAQ150_TICKER, period="30d", interval="1d")

    if df is None or len(df) < 6:
        s["KOSDAQ150_ret_d"] = {"value": np.nan, "unit": "%", "desc": "KOSDAQ150 일간 수익률"}
        s["KOSDAQ150_ATR5_pct"] = {"value": np.nan, "unit": "%", "desc": "KOSDAQ150 5일 ATR% (변동성)"}
        s["KOSDAQ150_long_red"] = {"value": 0.0, "unit": "bool", "desc": "KOSDAQ150 장대 음봉(1=예,0=아니오)"}
        return s

    ret_d = pct(df["Close"].iloc[-1], df["Close"].iloc[-2])

    # TR / ATR
    dfx = df.copy()
    dfx["H-L"] = dfx["High"] - dfx["Low"]
    dfx["H-C"] = (dfx["High"] - dfx["Close"].shift(1)).abs()
    dfx["L-C"] = (dfx["Low"] - dfx["Close"].shift(1)).abs()
    tr = dfx[["H-L", "H-C", "L-C"]].max(axis=1)
    atr5 = float(tr.rolling(5).mean().iloc[-1])
    close_today = float(df["Close"].iloc[-1])
    atr5_pct = (atr5 / close_today) * 100.0 if close_today > 0 else np.nan

    o, h, l, c = last_ohlc(df)
    today_range = safe_float(h) - safe_float(l)
    long_red = int((c < o) and (atr5 > 0) and (today_range >= 1.5 * atr5))

    s["KOSDAQ150_ret_d"] = {"value": ret_d, "unit": "%", "desc": "KOSDAQ150 일간 수익률"}
    s["KOSDAQ150_ATR5_pct"] = {"value": atr5_pct, "unit": "%", "desc": "KOSDAQ150 5일 ATR% (변동성)"}
    s["KOSDAQ150_long_red"] = {"value": float(long_red), "unit": "bool", "desc": "KOSDAQ150 장대 음봉(1=예,0=아니오)"}
    return s

# ======================================================
# 점수 + Drivers (이유 설명)
# ======================================================
def clamp_score(x):
    return int(max(0, min(100, x)))

def level_label(score):
    if score >= 70:
        return "HIGH", "높음"
    if score >= 40:
        return "MEDIUM", "중간"
    return "LOW", "낮음"

def badge_class(level):
    return {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}.get(level, "low")

def duration_hint(score):
    """
    초보자용: 점수에 따른 '영향 지속 가능 기간' 가이드(경험칙)
    """
    if score >= 70:
        return "3~5일", "여러 지표가 동시에 악화/과열된 구간은 보통 3~5일 변동성 확대가 동반될 수 있습니다."
    if score >= 40:
        return "1~3일", "단기 충격/변동성 확대가 1~3일 이어질 가능성이 있습니다."
    return "0~1일", "단기 이슈가 없다면 하루 내 소화되거나, 제한적 변동에 그칠 가능성이 큽니다."

def score_kospi(global_s):
    """
    코스피 급등/급락 점수 + drivers
    """
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
    """
    코스닥은 '성장주/변동성' 민감도를 높게 반영.
    """
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

# ======================================================
# 대응 전략(자동)
# ======================================================
def build_actions(market_name, up_score, down_score):
    """
    초보자용: down_score 중심으로 대응(리스크 관리),
    up_score가 높은 경우 '추격매수 경고'도 함께 표기.
    """
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
            "급등 점수가 높아도 ‘과열·급등 후 급락’ 가능성이 있으니 추격매수는 주의.",
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

# ======================================================
# 게이지 이미지 (듀얼: 급등/급락)
# ======================================================
def create_dual_gauge(up_score, down_score, title):
    fig, ax = plt.subplots(figsize=(7.2, 2.2))  # 모바일에서도 선명
    y_pos = [1, 0]
    labels = ["급등 가능성", "급락 위험"]

    ax.barh(y_pos, [100, 100], height=0.36, color="#1f2937")  # dark base
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

# ======================================================
# 초보자용 지표 설명(Glossary)
# ======================================================
def glossary_blocks():
    return [
        ("야간 선물(최근 4시간)",
         "한국 장 시작 전에 미국 시장 분위기를 반영하는 대표 프록시입니다. "
         "장 마감 후 악재가 나오면 야간 선물이 먼저 반응하고, 한국은 다음날 갭으로 반영될 가능성이 있습니다.",
         "0~1일"),
        ("VIX (30일 변동성)",
         "미국 S&P500 옵션에서 계산되는 30일 기대 변동성입니다. 흔히 ‘공포지수’로 불리며 높을수록 불안 심리를 의미합니다.",
         "1~5일"),
        ("VIX9D (9일 변동성)",
         "매우 단기(9일) 이벤트 리스크에 민감합니다. "
         "VIX9D가 VIX보다 빠르게 튀면 ‘단기 충격(이벤트)’ 가능성을 시사하는 경우가 많습니다.",
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
         "위험자산 선호/회피 심리의 ‘온도계’처럼 움직일 때가 있습니다. 단, 단독 신호는 과신 금지(보조 지표).",
         "0~2일"),
        ("KOSDAQ150 ATR%",
         "코스닥 변동성(진폭)을 나타내는 지표입니다. 변동성이 높은 상태에서 하락까지 겹치면 급락으로 번질 확률이 올라갑니다.",
         "1~3일"),
        ("장대 음봉(코스닥)",
         "하루 변동폭이 크면서 종가가 시가보다 낮게 마감된 ‘공포 캔들’입니다. 단기 조정이 이어질 가능성이 커질 수 있습니다.",
         "1~3일"),
    ]

# ======================================================
# HTML (모바일 하이엔드 + 이유/전략/설명 포함)
# ======================================================
def build_table_rows(sig_dict, prefix=""):
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
    if not drivers:
        return "<li class='muted'>현재 구간에서 점수를 크게 올릴 만한 뚜렷한 요인이 많지 않습니다.</li>"
    return "".join([f"<li>{d}</li>" for d in drivers])

def actions_html(actions):
    return "".join([f"<li>{a}</li>" for a in actions])

def glossary_html():
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

def build_html(report):
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
  <div class="sub">생성 시각: <b>{report["run_time"]}</b> · Mobile-first High-end UI</div>

  <div class="grid">
    <div class="card">
      <div class="kicker">
        <h2>코스피 (KOSPI) 요약</h2>
        <div class="badges">
          <span class="badge {report["kospi_up_badge"]}">급등: {report["kospi_up_label"]}</span>
          <span class="badge {report["kospi_down_badge"]}">급락: {report["kospi_down_label"]}</span>
        </div>
      </div>

      <div class="scoreline">
        <div class="scorebox">
          <div class="label">급등 가능성 점수</div>
          <div class="val up">{report["kospi_up"]}</div>
        </div>
        <div class="scorebox">
          <div class="label">급락 위험 점수</div>
          <div class="val down">{report["kospi_down"]}</div>
        </div>
      </div>

      <img src="data:image/png;base64,{report["kospi_gauge"]}" alt="KOSPI gauge">

      <hr>
      <details open>
        <summary>왜 이런 점수가 나왔나 (Drivers)</summary>
        <div style="margin-top:8px">
          <div class="muted" style="margin-bottom:6px">급등 요인</div>
          <ul>{drivers_html(report["kospi_drivers_up"])}</ul>
          <div class="muted" style="margin:10px 0 6px">급락 요인</div>
          <ul>{drivers_html(report["kospi_drivers_down"])}</ul>
        </div>
      </details>

      <hr>
      <details>
        <summary>대응 전략 (요약)</summary>
        <ul>{actions_html(report["kospi_actions"])}</ul>
      </details>
    </div>

    <div class="card">
      <div class="kicker">
        <h2>코스닥 (KOSDAQ) 요약</h2>
        <div class="badges">
          <span class="badge {report["kosdaq_up_badge"]}">급등: {report["kosdaq_up_label"]}</span>
          <span class="badge {report["kosdaq_down_badge"]}">급락: {report["kosdaq_down_label"]}</span>
        </div>
      </div>

      <div class="scoreline">
        <div class="scorebox">
          <div class="label">급등 가능성 점수</div>
          <div class="val up">{report["kosdaq_up"]}</div>
        </div>
        <div class="scorebox">
          <div class="label">급락 위험 점수</div>
          <div class="val down">{report["kosdaq_down"]}</div>
        </div>
      </div>

      <img src="data:image/png;base64,{report["kosdaq_gauge"]}" alt="KOSDAQ gauge">

      <hr>
      <details open>
        <summary>왜 이런 점수가 나왔나 (Drivers)</summary>
        <div style="margin-top:8px">
          <div class="muted" style="margin-bottom:6px">급등 요인</div>
          <ul>{drivers_html(report["kosdaq_drivers_up"])}</ul>
          <div class="muted" style="margin:10px 0 6px">급락 요인</div>
          <ul>{drivers_html(report["kosdaq_drivers_down"])}</ul>
        </div>
      </details>

      <hr>
      <details>
        <summary>대응 전략 (요약)</summary>
        <ul>{actions_html(report["kosdaq_actions"])}</ul>
      </details>
    </div>
  </div>

  <div class="card" style="margin-top:12px">
    <h2>지표 설명 (초보자용)</h2>
    {glossary_html()}
    <div class="footer">
      * “영향 범위”는 통계적 보장이 아닌 경험적 가이드입니다. 실제 시장은 뉴스/정책/지정학 리스크에 따라 달라질 수 있습니다.
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
            {build_table_rows(report["global_signals"], prefix="G.")}
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
            {build_table_rows(report["kosdaq_signals"], prefix="KQ.")}
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

# ======================================================
# 메인
# ======================================================
def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print("[INFO] 글로벌 신호 계산 중...")
    global_signals = compute_global_signals()

    print("[INFO] 코스닥 전용 신호 계산 중...")
    kosdaq_signals = compute_kosdaq_signals()

    print("[INFO] 점수/Drivers 계산 중...")
    ku, kd, ku_drv, kd_drv = score_kospi(global_signals)
    du, dd, du_drv, dd_drv = score_kosdaq(global_signals, kosdaq_signals)

    ku_level, ku_label = level_label(ku)
    kd_level, kd_label = level_label(kd)
    du_level, du_label = level_label(du)
    dd_level, dd_label = level_label(dd)

    kospi_gauge = create_dual_gauge(ku, kd, "KOSPI 급등/급락 게이지")
    kosdaq_gauge = create_dual_gauge(du, dd, "KOSDAQ 급등/급락 게이지")

    kospi_actions = build_actions("KOSPI", ku, kd)
    kosdaq_actions = build_actions("KOSDAQ", du, dd)

    report = {
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

    html = build_html(report)
    fname = f"gap_updown_risk_report_v7_2_{dt.datetime.now(SEOUL).strftime('%Y%m%d_%H%M')}.html"
    path = os.path.join(OUT_DIR, fname)

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    print("\n=== Gap Up & Down Risk Report v7.2 생성 완료 ===")
    print(f"[INFO] 리포트 파일: {path}")
    print(f"[INFO] KOSPI - 급등 {ku}/100, 급락 {kd}/100")
    print(f"[INFO] KOSDAQ - 급등 {du}/100, 급락 {dd}/100")

    # Windows 자동 열기
    try:
        os.startfile(path)
    except Exception:
        import webbrowser
        webbrowser.open("file://" + os.path.realpath(path))

if __name__ == "__main__":
    main()
