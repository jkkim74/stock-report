# -*- coding: utf-8 -*-
"""
리포트 생성 핵심 로직
- 발송 방법에 대해 전혀 알지 못함
- 순수하게 데이터 분석과 HTML 생성만 담당
"""

import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pykrx import stock
from tqdm import tqdm
from pytz import timezone
from config import ANALYSIS_CONFIG

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


class ReportData:
    """리포트 데이터를 담는 컨테이너"""
    
    def __init__(self, html_content, trade_date, metadata):
        self.html_content = html_content
        self.trade_date = trade_date
        self.metadata = metadata
    
    def __repr__(self):
        return f"ReportData(trade_date={self.trade_date}, metadata={self.metadata})"


# ===== 헬퍼 함수들 =====

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


def generate_html_report(recommend, premium_main, watch_df, trade_date):
    """HTML 리포트 생성"""
    
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
  기준일: {trade_date} · (시가총액 ≥ 3000억, 등락률 ≥ 5%, 거래대금 ≥ 1000억 종목만 분석합니다.)
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


# ===== 메인 리포트 생성 함수 =====

def generate_premium_stock_report():
    """
    프리미엄 주식 리포트 생성
    
    Returns:
        ReportData: HTML 콘텐츠와 메타데이터를 담은 객체
        None: 생성 실패 시
    """
    trade_date = get_trade_date()
    print(f"[INFO] 기준일: {trade_date}")

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
    html = generate_html_report(recommend, premium_main, watch_df, trade_date)

    # 8. 메타데이터 생성
    metadata = {
        "report_type": "premium_stock",
        "total_stocks": len(df_all),
        "recommend_count": len(recommend),
        "premium_count": len(premium_main),
        "watch_count": len(watch_df),
        "generated_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "filename": f"Premium_AI_Report_v4_{trade_date}.html"
    }

    print(f"[INFO] 리포트 생성 완료 - 추천:{len(recommend)}, 프리미엄:{len(premium_main)}, 관심:{len(watch_df)}")

    return ReportData(html, trade_date, metadata)


# ===== 미래 확장을 위한 예시 =====

def generate_etf_report():
    """ETF 리포트 생성 (미래 확장 예시)"""
    # TODO: ETF 분석 로직 구현
    pass


def generate_crypto_report():
    """암호화폐 리포트 생성 (미래 확장 예시)"""
    # TODO: 암호화폐 분석 로직 구현
    pass
