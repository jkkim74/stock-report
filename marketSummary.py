# -*- coding: utf-8 -*-
"""
Market Summary v10.8 (Mobile High-end, No Gap Gauge)
----------------------------------------------------
요청 반영:
1) 위험 급등락 게이지(= Gap Risk Gauge) 완전 제거
2) 스마트폰에서도 잘 보이도록 글씨 크게 + 모바일 하이엔드 UI
3) Composite 숫자 구간별 의미 설명 추가
4) 전략 코멘트(대응 가이드) 추가 (시장별 + 종합)

안정성(Fix):
- Macro(환율/금리) 결측이 있어도 Composite가 NaN으로 전염되지 않도록 ffill + fillna(0)
- yfinance MultiIndex 컬럼 평탄화 + normalize
"""

import os
import webbrowser
import datetime as dt
import warnings
import base64
from io import BytesIO

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib

# --------------------------------------------------
# 폰트 / 환경
# --------------------------------------------------
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

SEOUL = dt.timezone(dt.timedelta(hours=9))

# =========================================================
# 공통 유틸
# =========================================================
def now_kr():
    return dt.datetime.now(SEOUL)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
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


def _flatten_yf_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


# =========================================================
# Sparkline + 해석
# =========================================================
def make_sparkline(series: pd.Series) -> str:
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


def sparkline_comment(series: pd.Series) -> str:
    s = series.dropna().tail(15)
    if len(s) < 5:
        return "최근 데이터가 부족해 흐름 판단이 어렵습니다."

    first, lastv = s.iloc[0], s.iloc[-1]
    delta = lastv - first
    slope = delta / max(len(s) - 1, 1)
    vol = s.diff().abs().mean()

    if delta >= 20 and slope > 0:
        return "Composite 흐름이 뚜렷한 상승 추세로 전환된 모습입니다."
    if 5 <= delta < 20 and slope > 0:
        return "Composite는 완만한 상승 기울기를 유지하고 있습니다."
    if -5 < delta < 5 and vol < 10:
        return "Composite가 좁은 박스권에서 횡보하는 모습입니다."
    if delta <= -20 and slope < 0:
        return "Composite가 뚜렷한 하락 방향으로 전환되어 체력이 약해진 상태입니다."
    if -20 < delta <= -5 and slope < 0:
        return "Composite가 조정 구간에 진입한 모습입니다."
    return "단기적으로 상·하방 신호가 섞인 중립적인 흐름입니다."


# =========================================================
# 지수 로딩
# =========================================================
def load_index(ticker: str, days: int = 300) -> pd.DataFrame:
    end = now_kr().date()
    start = end - dt.timedelta(days=days)

    warnings.filterwarnings("ignore", category=FutureWarning)
    q = yf.download(
        ticker,
        start=start,
        end=end + dt.timedelta(days=1),
        progress=False,
        auto_adjust=False,
    )
    q = _flatten_yf_columns(q)
    q = _normalize(q)

    if q is None or q.empty:
        raise ValueError(f"지수({ticker}) 조회 실패")

    df = pd.DataFrame(index=q.index)
    df["Open"] = q["Open"]
    df["Index"] = q["Close"]
    df["Index_ret(%)"] = df["Index"].pct_change() * 100
    return df[["Open", "Index", "Index_ret(%)"]]


# =========================================================
# ETF Flow Proxy
# =========================================================
def load_etf_flow(etfs: dict, days: int = 300) -> pd.DataFrame:
    end = now_kr().date()
    start = end - dt.timedelta(days=days)

    combined = pd.DataFrame()

    for name, info in etfs.items():
        print(f"[ETF] {name} 로딩 중...")
        q = yf.download(
            info["yf"],
            start=start,
            end=end + dt.timedelta(days=1),
            progress=False,
            auto_adjust=False,
        )
        q = _flatten_yf_columns(q)
        q = _normalize(q)

        if q is None or q.empty:
            print(f"[WARN] ETF {name} 데이터 없음")
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

    if combined.empty:
        raise ValueError("ETF Flow Proxy 생성 실패")

    combined = combined.sort_index()
    combined["Flow_Proxy"] = combined.sum(axis=1)
    return combined[["Flow_Proxy"]]


ETF_KOSPI = {
    "KODEX200": {"yf": "069500.KS", "w": 1.0, "sign": +1, "vol_win": 20},
    "KODEX_레버": {"yf": "122630.KS", "w": 1.5, "sign": +1, "vol_win": 20},
    "KODEX_인버": {"yf": "114800.KS", "w": 1.5, "sign": -1, "vol_win": 20},
}

ETF_KOSDAQ = {
    "KQ150": {"yf": "229200.KS", "w": 1.0, "sign": +1, "vol_win": 30},
    "KQ150_레버": {"yf": "233740.KS", "w": 1.7, "sign": +1, "vol_win": 30},
    "KQ150_인버": {"yf": "251340.KS", "w": 1.7, "sign": -1, "vol_win": 30},
}


# =========================================================
# Macro (환율 + 미국 10년 금리)
# =========================================================
def load_macro(days: int = 320) -> pd.DataFrame:
    end = now_kr().date()
    start = end - dt.timedelta(days=days + 60)

    fx = yf.download("KRW=X", start=start, end=end + dt.timedelta(days=1), progress=False, auto_adjust=False)
    rt = yf.download("^TNX", start=start, end=end + dt.timedelta(days=1), progress=False, auto_adjust=False)

    fx = _flatten_yf_columns(fx)
    rt = _flatten_yf_columns(rt)

    fx = _normalize(fx)
    rt = _normalize(rt)

    if fx is None or fx.empty:
        raise ValueError("KRW=X 데이터 없음")

    # TNX는 휴일/월요일 등에서 비는 경우가 있어도 리포트는 돌아가야 함
    if rt is None or rt.empty:
        rt = pd.DataFrame(index=fx.index, data={"Close": np.nan})

    idx = sorted(set(fx.index) | set(rt.index))
    df = pd.DataFrame(index=idx)
    df["FX"] = fx["Close"].reindex(idx)
    df["Rate"] = rt["Close"].reindex(idx)

    df["FX_20d(%)"] = (df["FX"] / df["FX"].shift(20) - 1) * 100
    df["Rate_20d"] = df["Rate"] - df["Rate"].shift(20)

    return df[["FX_20d(%)", "Rate_20d"]].sort_index()


# =========================================================
# Score 계산 (Flow / Trend / Macro / Breadth)
# =========================================================
def compute_scores(df: pd.DataFrame,
                   trend_s: int,
                   trend_l: int,
                   ws: float,
                   wl: float,
                   name: str) -> pd.DataFrame:
    df = df.copy().sort_index()

    # Flow
    base = df["Flow_Proxy"].abs().rolling(20).mean().clip(lower=10)
    df["Flow_score"] = (df["Flow_Proxy"] / base) * 100

    # Trend
    ma_s = df["Index"].rolling(trend_s).mean()
    ma_l = df["Index"].rolling(trend_l).mean()

    df["trend_s"] = (df["Index"] / ma_s - 1) * 100
    df["trend_l"] = (df["Index"] / ma_l - 1) * 100
    df["Trend_score"] = ws * df["trend_s"] + wl * df["trend_l"]

    # Breadth
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

    # Macro (Fix: 결측 보호)
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


# =========================================================
# Composite 의미/전략
# =========================================================
def composite_band(c: float) -> str:
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


def strategy_guide(c: float, market_name: str) -> str:
    """
    투자자 대응 가이드 (과도한 확신 금지, 실행 가능한 원칙 중심)
    """
    if pd.isna(c):
        return (f"{market_name}: 데이터 결측 구간입니다. "
                f"의사결정은 보류하고, 다음 거래일 데이터가 정상 반영된 뒤 다시 확인하는 것이 안전합니다.")

    # 공통 원칙: 구간별 '비중/리스크' 중심
    if c >= 40:
        return (f"{market_name}: 강한 상승 우위 구간입니다. "
                f"추격매수보다는 '눌림 분할매수'와 '수익 구간 분할익절'을 권장합니다. "
                f"손절 기준(예: 직전 스윙 저점/20일선 이탈)을 사전에 고정하고 과열 종목은 비중을 제한하세요.")
    if 20 <= c < 40:
        return (f"{market_name}: 상승 우위 구간입니다. "
                f"우량/주도 섹터 중심으로 분할 진입을 고려할 만하며, 변동성 확대 시 추가매수 대신 비중 관리가 유리합니다. "
                f"종목은 '상승 추세 유지(이평 지지)'를 우선 확인하세요.")
    if 5 <= c < 20:
        return (f"{market_name}: 약한 상승 구간입니다. "
                f"시장은 올라가도 종목 간 편차가 커질 수 있으므로 '선별 매매'가 유리합니다. "
                f"신규 진입은 소액/분할로 제한하고, 수익이 나면 빠른 일부익절로 리스크를 줄이세요.")
    if -5 < c < 5:
        return (f"{market_name}: 중립 구간입니다. "
                f"방향성이 약해 '현금 비중'과 '관망'이 합리적입니다. "
                f"매매를 하더라도 짧은 손절/짧은 목표(스윙 저항선)로 대응하는 것이 안정적입니다.")
    if -20 < c <= -5:
        return (f"{market_name}: 약한 하락 구간입니다. "
                f"신규 매수는 보수적으로 접근하고, 기존 보유는 방어적 손절 기준을 강화하세요. "
                f"리바운드 매매는 '확인(거래량 동반 반등/지지 확인)' 이후에만 소액으로 제한하는 것이 좋습니다.")
    if -40 < c <= -20:
        return (f"{market_name}: 하락 우위 구간입니다. "
                f"비중 축소와 현금 확보가 우선이며, 공격적 매수보다는 '관망/방어'가 유리합니다. "
                f"반등이 나와도 추세 전환 확인 전까지는 단기 대응으로 제한하세요.")
    return (f"{market_name}: 강한 하락 우위 구간입니다. "
            f"리스크 오프 국면으로 보고 현금 비중을 높이는 전략이 합리적입니다. "
            f"손실 확대를 막기 위해 규칙 기반 손절을 우선 적용하고, 시장 안정 신호가 나오기 전까지 공격적 매수는 피하세요.")


def overall_strategy_comment(k: float, q: float) -> str:
    if pd.isna(k) or pd.isna(q):
        return ("일부 데이터 결측이 있어 해석 신뢰도가 낮습니다. "
                "다음 거래일 데이터가 정상 반영된 뒤 다시 확인하는 것을 권장합니다.")

    # 상대 강도 코멘트
    if k >= 20 and q >= 20:
        return ("양 시장 모두 상승 우위입니다. 전반적으로 매수 환경이 우호적이나, "
                "과열 구간에서는 추격매수보다 분할 접근과 이익 실현 규칙이 중요합니다.")
    if k >= 20 > q:
        return ("KOSPI가 상대적으로 강하고 KOSDAQ은 둔화된 상태입니다. "
                "대형주/우량주 중심으로 방어적 상승 전략이 유리하며, 테마/중소형주는 선별이 필요합니다.")
    if q >= 20 > k:
        return ("KOSDAQ이 상대적으로 강한 구간입니다. 중소형 성장주/테마가 유리할 수 있으나 변동성도 커질 수 있어 "
                "분할매수와 손절 규칙을 더 엄격히 적용하는 것이 좋습니다.")
    if k <= -20 and q <= -20:
        return ("양 시장 모두 하락 우위입니다. 비중 축소와 리스크 관리가 최우선이며, "
                "반등은 '기회'보다 '점검' 관점에서 보수적으로 대응하는 것이 안전합니다.")
    return ("시장 방향성이 엇갈리는 혼조 구간입니다. 지수 베팅보다 개별 종목의 추세/수급 확인이 중요하며, "
            "현금 비중을 확보한 상태에서 선별적으로 대응하는 것이 유리합니다.")


# =========================================================
# Summary HTML 생성 (게이지 제거 + 모바일 하이엔드)
# =========================================================
def generate_summary(df_k: pd.DataFrame, df_q: pd.DataFrame):
    df_k = df_k.sort_index()
    df_q = df_q.sort_index()

    last_k = df_k.iloc[-1]
    last_q = df_q.iloc[-1]

    ck = float(last_k["Composite"]) if pd.notna(last_k["Composite"]) else np.nan
    cq = float(last_q["Composite"]) if pd.notna(last_q["Composite"]) else np.nan

    spark_k = make_sparkline(df_k["Composite"])
    spark_q = make_sparkline(df_q["Composite"])
    spark_k_txt = sparkline_comment(df_k["Composite"])
    spark_q_txt = sparkline_comment(df_q["Composite"])

    band_k = composite_band(ck)
    band_q = composite_band(cq)

    overall = overall_strategy_comment(ck, cq)
    guide_k = strategy_guide(ck, "KOSPI")
    guide_q = strategy_guide(cq, "KOSDAQ")

    # 표
    cols = ["Index", "Index_ret(%)", "수급 강도", "추세 강도", "외부 환경 영향", "시장 건강도", "Composite"]
    t1 = df_k[cols].tail(15).sort_index(ascending=False).round(2).to_html(border=0, index=True)
    t2 = df_q[cols].tail(15).sort_index(ascending=False).round(2).to_html(border=0, index=True)

    # 배경톤
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

    # 상단 메타
    gen_time = now_kr().strftime("%Y-%m-%d %H:%M KST")

    # Composite 의미(설명 블록)
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
        Composite는 수급·추세·대외환경·시장건강도를 가중합한 “시장 컨디션 지표”이며, 수익을 보장하지 않습니다.
      </div>
    </div>
    """

    html = f"""
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
      <title>Market Summary v10.8</title>
      <style>
        :root {{
          --bg: #f5f6f8;
          --card: rgba(255,255,255,0.92);
          --text: #111827;
          --muted: #6b7280;
          --accent: #d6286a;
          --shadow: 0 10px 30px rgba(0,0,0,0.10);
          --shadow2: 0 6px 18px rgba(0,0,0,0.08);
          --radius: 22px;
        }}

        body {{
          margin: 0;
          background: radial-gradient(1200px 800px at 15% 10%, #ffe8f1 0%, rgba(255,232,241,0) 55%),
                      radial-gradient(1100px 700px at 85% 18%, #e9f4ff 0%, rgba(233,244,255,0) 55%),
                      var(--bg);
          font-family: "맑은 고딕", system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
          color: var(--text);
        }}

        .wrap {{
          max-width: 1080px;
          margin: 0 auto;
          padding: 18px 16px 40px 16px;
        }}

        .topbar {{
          position: sticky;
          top: 0;
          z-index: 20;
          backdrop-filter: blur(16px);
          background: rgba(15, 23, 42, 0.78);
          color: #fff;
          border-bottom: 1px solid rgba(255,255,255,0.10);
        }}
        .topbar-inner {{
          max-width: 1080px;
          margin: 0 auto;
          padding: 14px 16px;
          display:flex;
          justify-content: space-between;
          align-items: center;
          gap: 10px;
        }}
        .topbar-title {{
          font-weight: 900;
          font-size: 18px;
          letter-spacing: -0.2px;
        }}
        .topbar-meta {{
          font-size: 13px;
          color: rgba(255,255,255,0.85);
          white-space: nowrap;
        }}

        .hero {{
          margin-top: 16px;
          background: linear-gradient(135deg, rgba(0,0,0,0.92), rgba(17,24,39,0.92));
          border-radius: var(--radius);
          padding: 22px 20px;
          box-shadow: var(--shadow);
          color: #fff;
        }}
        .hero .h-title {{
          font-size: 22px;
          font-weight: 900;
          margin-bottom: 10px;
          color: #ffd700;
          letter-spacing: -0.3px;
        }}
        .hero .h-text {{
          font-size: 16px;
          line-height: 1.8;
          font-weight: 650;
          color: rgba(255,255,255,0.95);
        }}
        .hero .h-note {{
          margin-top: 10px;
          font-size: 13px;
          color: rgba(255,255,255,0.75);
          line-height: 1.6;
        }}

        .card {{
          margin-top: 16px;
          background: var(--card);
          border-radius: var(--radius);
          padding: 18px 18px;
          box-shadow: var(--shadow2);
          border: 1px solid rgba(17,24,39,0.06);
        }}

        .card-title {{
          font-size: 18px;
          font-weight: 900;
          letter-spacing: -0.2px;
          margin-bottom: 12px;
        }}

        .market-card {{
          padding: 18px 18px 16px 18px;
        }}

        .market-header {{
          display:flex;
          justify-content: space-between;
          align-items: flex-end;
          gap: 10px;
          flex-wrap: wrap;
          margin-bottom: 10px;
        }}

        .market-name {{
          font-size: 22px;
          font-weight: 950;
          letter-spacing: -0.4px;
          color: var(--accent);
        }}

        .comp-value {{
          font-size: 34px;
          font-weight: 950;
          letter-spacing: -0.6px;
        }}

        .pill {{
          display:inline-flex;
          align-items:center;
          gap:8px;
          padding: 8px 12px;
          border-radius: 999px;
          font-size: 13px;
          font-weight: 800;
          background: rgba(17,24,39,0.06);
          color: #111827;
        }}

        .pill .dot {{
          width: 10px;
          height: 10px;
          border-radius: 999px;
          background: #111827;
          opacity: 0.8;
        }}

        .spark-row {{
          display:flex;
          align-items:center;
          justify-content: space-between;
          gap: 14px;
          flex-wrap: wrap;
          margin-top: 8px;
        }}
        .spark-row img {{
          max-width: 520px;
          width: 100%;
          height: auto;
        }}
        .spark-text {{
          flex: 1;
          min-width: 240px;
          font-size: 15px;
          color: #111827;
          line-height: 1.7;
        }}

        .kpis {{
          margin-top: 12px;
          display:grid;
          grid-template-columns: repeat(2, minmax(0,1fr));
          gap: 10px;
        }}
        .kpi {{
          background: rgba(255,255,255,0.85);
          border: 1px solid rgba(17,24,39,0.06);
          border-radius: 16px;
          padding: 12px 12px;
        }}
        .kpi .k {{
          font-size: 13px;
          color: var(--muted);
          font-weight: 800;
        }}
        .kpi .v {{
          margin-top: 6px;
          font-size: 20px;
          font-weight: 950;
          letter-spacing: -0.3px;
        }}

        .guide {{
          margin-top: 12px;
          background: rgba(17,24,39,0.04);
          border: 1px solid rgba(17,24,39,0.08);
          border-radius: 18px;
          padding: 14px 14px;
          font-size: 15px;
          line-height: 1.8;
          color: #111827;
        }}

        .legend-grid {{
          display: grid;
          grid-template-columns: 1fr;
          gap: 10px;
        }}

        .legend-item {{
          border-radius: 18px;
          padding: 12px 12px;
          border: 1px solid rgba(17,24,39,0.06);
          background: rgba(255,255,255,0.70);
        }}
        .legend-badge {{
          display:inline-block;
          font-size: 13px;
          font-weight: 950;
          padding: 6px 10px;
          border-radius: 999px;
          background: rgba(17,24,39,0.08);
          margin-bottom: 8px;
        }}
        .legend-text {{
          font-size: 15px;
          line-height: 1.7;
          color: #111827;
        }}

        .up-strong {{ background: linear-gradient(135deg, rgba(255,208,229,0.75), rgba(255,255,255,0.70)); }}
        .up        {{ background: linear-gradient(135deg, rgba(255,228,239,0.85), rgba(255,255,255,0.70)); }}
        .up-weak   {{ background: linear-gradient(135deg, rgba(255,245,249,0.95), rgba(255,255,255,0.70)); }}
        .neutral   {{ background: linear-gradient(135deg, rgba(245,246,248,0.95), rgba(255,255,255,0.70)); }}
        .down-weak {{ background: linear-gradient(135deg, rgba(239,246,255,0.95), rgba(255,255,255,0.70)); }}
        .down      {{ background: linear-gradient(135deg, rgba(231,243,255,0.95), rgba(255,255,255,0.70)); }}
        .down-strong{{ background: linear-gradient(135deg, rgba(211,232,255,0.95), rgba(255,255,255,0.70)); }}

        .note {{
          margin-top: 10px;
          font-size: 13px;
          color: var(--muted);
          line-height: 1.7;
        }}

        table {{
          width: 100%;
          border-collapse: collapse;
          font-size: 13px;
        }}
        table thead th {{
          text-align: right;
          background: rgba(17,24,39,0.04);
          padding: 10px 10px;
          border-bottom: 1px solid rgba(17,24,39,0.10);
          font-weight: 900;
        }}
        table tbody td {{
          text-align: right;
          padding: 10px 10px;
          border-bottom: 1px solid rgba(17,24,39,0.08);
          font-weight: 650;
        }}
        table thead th:first-child, table tbody td:first-child {{
          text-align: center;
          font-weight: 900;
        }}

        /* 모바일 최적화 */
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

        <!-- KOSPI -->
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

        <!-- KOSDAQ -->
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
              <li><b>외부 환경 영향</b>: 환율(20일 변화)과 미국 10년물 금리(20일 변화)를 반영합니다. 데이터 결측이 있어도 Composite가 NaN이 되지 않도록 보호 처리합니다.</li>
              <li><b>시장 건강도</b>: 최근 60일 범위 내 위치(ClosePos)와 20일선 괴리(MA_gap)를 조합합니다.</li>
              <li><b>Composite</b>: 위 4개 지수를 시장 특성에 맞게 가중 평균한 “시장 컨디션 지표”입니다.</li>
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

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Market_Summary_v10_8.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print("✅ Market Summary v10.8 생성 완료:", out)
    webbrowser.open("file://" + out)


# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    print("📈 Market Summary v10.8 — 생성 중...")

    # 1) 지수 + Flow
    df_k_idx = load_index("^KS200")
    df_k_flow = load_etf_flow(ETF_KOSPI)
    df_k = df_k_idx.join(df_k_flow, how="inner")

    df_q_idx = load_index("^KQ11")
    df_q_flow = load_etf_flow(ETF_KOSDAQ)
    df_q = df_q_idx.join(df_q_flow, how="inner")

    # 2) Macro
    df_macro = load_macro()
    df_macro = _normalize(df_macro)

    df_k = df_k.join(df_macro, how="left")
    df_q = df_q.join(df_macro, how="left")

    # 3) Score 계산
    df_k = compute_scores(df_k, trend_s=20, trend_l=60, ws=0.5, wl=0.5, name="KOSPI")
    df_q = compute_scores(df_q, trend_s=10, trend_l=30, ws=0.6, wl=0.4, name="KOSDAQ")

    # 4) 리포트 생성
    generate_summary(df_k, df_q)