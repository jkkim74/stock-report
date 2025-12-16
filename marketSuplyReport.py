#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import warnings
warnings.filterwarnings("ignore")

import logging
import os
import webbrowser
from datetime import datetime, timedelta

import pandas as pd
import requests
from pykrx import stock
import FinanceDataReader as fdr

# ======================================================
# 설정값
# ======================================================
FLOW_WINDOW_DAYS = 7
LIST_MIN_MCAP = 300_000_000_000

MIN_MCAP = 100_000_000_000
MIN_TV = 50_000_000_000
MIN_TURNOVER = 1.0

PREMIUM_MAX_R3 = 10.0

FAST_MIN_RETURN_1D = 10.0
FAST_MIN_FLOW1D_TV = 3.0

OVERHEAT_3D = 20.0
OVERHEAT_5D = 30.0

INTEREST_MIN_FLOW_3D_MCAP = 0.3
INTEREST_MAX_RISE_3D = 10.0

TOP_PER_SECTION = 30

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("FlowRev9_1M2")


# ======================================================
# 유틸
# ======================================================
def to_number(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    try:
        s = str(x).strip()
        if s in ("", "-", "None", "nan"):
            return 0.0
        return float(s.replace(",", ""))
    except Exception:
        return 0.0


def pick_col(df: pd.DataFrame, names: list[str]) -> str:
    for c in names:
        if c in df.columns:
            return c
    raise KeyError(f"필요 컬럼을 찾지 못했습니다: {names} / 현재 컬럼={list(df.columns)}")


def get_last_trading_day() -> str:
    today = datetime.now()
    for i in range(15):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y%m%d")
        try:
            if not stock.get_market_ohlcv_by_date(ds, ds, "005930").empty:
                return ds
        except Exception:
            pass
    return today.strftime("%Y%m%d")


def get_recent_trading_dates(last_date_str: str, n_days: int) -> list[str]:
    last_dt = datetime.strptime(last_date_str, "%Y%m%d")
    days = []
    d = last_dt
    while len(days) < n_days:
        if d.weekday() < 5:
            ds = d.strftime("%Y%m%d")
            try:
                if not stock.get_market_ohlcv_by_date(ds, ds, "005930").empty:
                    days.append(ds)
            except Exception:
                pass
        d -= timedelta(days=1)
    return sorted(days)


def safe_return(closes: pd.Series, days: int) -> float:
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


# ======================================================
# KRX JSON
# ======================================================
class KrxJson:
    URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://data.krx.co.kr"
        })

    def get_all(self, date: str) -> pd.DataFrame:
        payload = {
            "bld": "dbms/MDC/STAT/standard/MDCSTAT01501",
            "mktId": "ALL",
            "trdDd": date,
            "share": "1",
            "money": "1"
        }
        r = self.s.post(self.URL, data=payload, timeout=25)
        j = r.json()
        rows = j.get("OutBlock_1", j.get("output", []))
        df = pd.DataFrame(rows)
        if df.empty:
            return df

        code = pick_col(df, ["ISU_SRT_CD"])
        name = pick_col(df, ["ISU_ABBRV"])
        mkt = pick_col(df, ["MKT_NM"])
        close = pick_col(df, ["TDD_CLSPRC"])
        tv = pick_col(df, ["ACC_TRDVAL"])
        mcap = pick_col(df, ["MKTCAP"])
        fluc = pick_col(df, ["FLUC_RT"])

        out = pd.DataFrame({
            "티커": df[code].astype(str),
            "종목명": df[name].astype(str),
            "시장": df[mkt].astype(str),
            "종가": df[close].map(to_number),
            "거래대금": df[tv].map(to_number),
            "시가총액": df[mcap].map(to_number),
            "등락률_당일(%)": df[fluc].map(to_number),
        })

        mask = (
            out["종목명"].str.contains("ETF|ETN|스팩|SPAC", na=False) |
            out["종목명"].str.endswith("우", na=False)
        )
        out = out[~mask].copy()

        out = out[(out["거래대금"] > 0) & (out["시가총액"] > 0)].reset_index(drop=True)
        out["시총대비_거래대금(%)"] = out["거래대금"] / out["시가총액"] * 100.0
        return out


# ======================================================
# 모델
# ======================================================
class FlowRev9_1M2:

    def __init__(self):
        self.trade_date = get_last_trading_day()
        self.trade_dates = get_recent_trading_dates(self.trade_date, FLOW_WINDOW_DAYS)
        self.calendar = pd.to_datetime(self.trade_dates)

        fdr_start_dt = self.calendar[0] - pd.Timedelta(days=7)
        self.fdr_start = fdr_start_dt.strftime("%Y-%m-%d")
        self.fdr_end = self.calendar[-1].strftime("%Y-%m-%d")

        self.krx = KrxJson()

        logger.info(f"기준일: {self.trade_date}")
        logger.info(f"최근 {FLOW_WINDOW_DAYS} 거래일: {self.trade_dates[0]} ~ {self.trade_dates[-1]}")

    def load_base(self) -> pd.DataFrame:
        base = self.krx.get_all(self.trade_date)
        if base.empty:
            return base

        cond = (
            (base["시가총액"] >= MIN_MCAP) &
            (base["거래대금"] >= MIN_TV) &
            (base["시총대비_거래대금(%)"] >= MIN_TURNOVER)
        )
        base = base[cond].copy()
        logger.info(f"1차 필터 통과 종목 수: {len(base)}")
        return base

    def fetch_detail(self, row: pd.Series) -> dict | None:
        t = row["티커"]

        try:
            price_all = fdr.DataReader(t, self.fdr_start, self.fdr_end)
        except Exception:
            return None

        if price_all is None or price_all.empty or "Close" not in price_all.columns:
            return None

        price_slice = price_all.loc[self.calendar.min(): self.calendar.max()]
        price_win = price_slice.reindex(self.calendar)
        closes = price_win["Close"]

        if closes.notna().sum() < 6:
            return None

        closes = closes.ffill()
        if closes.isna().any():
            return None

        try:
            vol_raw = stock.get_market_trading_volume_by_date(
                self.trade_dates[0], self.trade_dates[-1], t
            )
        except Exception:
            vol_raw = pd.DataFrame()

        if vol_raw.empty:
            inst = pd.Series([0.0] * len(self.calendar), index=self.calendar)
            fore = pd.Series([0.0] * len(self.calendar), index=self.calendar)
        else:
            vol = vol_raw.reindex(self.calendar).fillna(0.0)
            if "기관합계" not in vol.columns or "외국인합계" not in vol.columns:
                return None
            inst = vol["기관합계"]
            fore = vol["외국인합계"]

        flows = (inst + fore) * closes

        tot_1 = float(flows.iloc[-1])
        tot_3 = float(flows.iloc[-3:].sum())
        tot_5 = float(flows.iloc[-5:].sum())

        mcap = float(row["시가총액"])
        tv = float(row["거래대금"])

        pct1_mcap = (tot_1 / mcap * 100.0) if mcap else 0.0
        pct3_mcap = (tot_3 / mcap * 100.0) if mcap else 0.0
        pct5_mcap = (tot_5 / mcap * 100.0) if mcap else 0.0
        pct1_tv = (tot_1 / tv * 100.0) if tv else 0.0

        r3 = safe_return(closes, 3)
        r5 = safe_return(closes, 5)

        last3 = flows.iloc[-3:]
        premium_flag = bool((last3 > 0).all())

        # 선취매 강도 점수(0~100)
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

    def run(self):
        base = self.load_base()
        if base.empty:
            return (pd.DataFrame(),) * 4

        rows = []
        for _, r in base.iterrows():
            x = self.fetch_detail(r)
            if x:
                rows.append(x)

        df = pd.DataFrame(rows)
        logger.info(f"상세 계산 완료 종목 수: {len(df)}")
        if df.empty:
            return (pd.DataFrame(),) * 4

        df = df[df["_mcap"] >= LIST_MIN_MCAP].copy()

        premium = df[(df["_flag_premium"] == True) & (df["3일수익률(%)"] <= PREMIUM_MAX_R3)].copy()
        fast = df[
            (df["등락률_당일(%)"] >= FAST_MIN_RETURN_1D) &
            (df["1일_순매수/거래대금(%)"] >= FAST_MIN_FLOW1D_TV) &
            (df["3일수익률(%)"] < OVERHEAT_3D)
        ].copy()
        overheat = df[(df["3일수익률(%)"] >= OVERHEAT_3D) | (df["5일수익률(%)"] >= OVERHEAT_5D)].copy()
        interest = df[
            (df["3일_순매수/시총(%)"] >= INTEREST_MIN_FLOW_3D_MCAP) &
            (df["3일수익률(%)"] <= INTEREST_MAX_RISE_3D)
        ].copy()
        interest = interest[~interest["티커"].isin(premium["티커"])].copy()

        for t in [premium, fast, overheat, interest]:
            if not t.empty:
                t.sort_values("선취매강도점수", ascending=False, inplace=True)

        return premium, fast, overheat, interest


# ======================================================
# HTML (모바일 최적화 + 요청 반영)
# ======================================================
def generate_html(trade_date: str,
                  premium: pd.DataFrame,
                  fast: pd.DataFrame,
                  overheat: pd.DataFrame,
                  interest: pd.DataFrame):

    date_fmt = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d (%A)")
    out_name = f"수급리포트_Rev9.1M2_{trade_date}.html"

    warning_text = """
    ※ 이 종목은 데이터에 기반한 통계적인 추천일 뿐이며 100% 확실한 보장이 아닙니다.<br>
    시장 전체의 갑작스러운 급변이나 개별 종목의 악재 뉴스로 인한 갑작스러운 변동이 있을 수 있으니,
    투자 결정은 반드시 본인의 판단 하에 신중하게 진행하시기 바랍니다.
    """

    # 모바일에서는 일부 열 숨김 (필요 시 제거 가능)
    MOBILE_HIDE_COLS = {
        "합산_5일(억)",
        "5일_순매수/시총(%)",
        "3일_순매수/시총(%)",
    }

    def style_name(name: str, score: float) -> str:
        # 요구사항: "선취매 강도 100인 종목만 붉은 글씨"
        # 종목명 크기는 기본 표 글씨와 동일하게(= inherit)
        if round(score, 2) >= 100.0:
            return f"<span class='name red'>{name}</span>"
        return f"<span class='name'>{name}</span>"

    def render_table(df: pd.DataFrame):
        if df.empty:
            return "<div class='empty'>조건에 맞는 종목이 없습니다.</div>"

        show = df.head(TOP_PER_SECTION).copy()
        show["종목명"] = show.apply(
            lambda r: style_name(r["원본종목명"], float(r["선취매강도점수"])), axis=1
        )

        cols = [
            "종목명",
            "종가(원)",
            "등락률_당일(%)",
            "3일수익률(%)",
            "5일수익률(%)",
            "시가총액(억)",
            "거래대금(억)",
            "시총대비_거래대금(%)",
            "합산_1일(억)",
            "합산_3일(억)",
            "합산_5일(억)",
            "1일_순매수/거래대금(%)",
            "3일_순매수/시총(%)",
            "5일_순매수/시총(%)",
            "선취매강도점수",
        ]
        show = show[cols].copy()

        ths = []
        for c in show.columns:
            cls = "m-hide" if c in MOBILE_HIDE_COLS else ""
            ths.append(f"<th class='{cls}'>{c}</th>")

        trs = []
        for _, row in show.iterrows():
            tds = []
            for c in show.columns:
                cls = "m-hide" if c in MOBILE_HIDE_COLS else ""
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

    # 요약 카드 (문구에서 "(초보자용)" 제거)
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

    # 섹션별 전략(문구에 '(초보자용)' 제거)
    premium_desc = f"""
    <div class="desc">
      • ‘프리미엄 추천 종목’은 최근 <b>3거래일 연속</b> 기관+외국인 순매수이며,
        <b>3일 수익률이 {PREMIUM_MAX_R3}% 이하</b>인 종목입니다.<br>
      • “수급은 들어오지만 가격은 아직 덜 오른” 후보를 우선적으로 포착합니다.
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

    # ✅ 선취매 강도 계산법은 "제일 밑"으로 이동 (요청 반영)
    strength_explain = f"""
    <div class="card legend">
      <div class="legend-title">선취매 강도 점수 계산 및 해석</div>
      <div class="legend-body">
        <b>계산(0~100)</b><br>
        • 3일 순매수/시총(%) × 40<br>
        • 1일 순매수/시총(%) × 30<br>
        • 5일 순매수/시총(%) × 20<br>
        • 최근 3거래일 연속 순매수이면 +10점<br><br>

        <b>의미</b><br>
        • “기관·외국인이 시가총액 대비 얼마나 강하게, 그리고 연속으로 담는가”를 0~100점으로 단순화한 지표입니다.<br>
        • 점수가 높을수록 ‘매집 강도’가 높다고 해석할 수 있으나, 급변 시장/악재 등으로 결과가 달라질 수 있습니다.<br><br>

        <b>표시 규칙</b><br>
        • 본 리포트에서는 선취매 강도 점수가 <b>100점인 종목만</b> 종목명을 붉게 표시합니다.
      </div>
    </div>
    """

    # 모바일 최적화 스타일 + 요청 반영(종목명 크기 표와 동일)
    style = """
    <style>
      :root{
        --bg:#ffffff;
        --ink:#0b0b0b;
        --muted:#4b4b4b;
        --line:#111111;
        --line-soft:#d7d7d7;
        --card:#fafafa;
        --red:#b30000;
      }
      *{box-sizing:border-box}
      body{
        margin:0; background:var(--bg); color:var(--ink);
        font-family: "Pretendard","Segoe UI",system-ui,-apple-system,sans-serif;
      }
      .wrap{max-width:1200px; margin:0 auto; padding:24px 14px 60px;}
      .header{
        display:flex; justify-content:space-between; align-items:flex-end;
        border-bottom:2px solid var(--line);
        padding-bottom:12px;
        gap:12px;
        flex-wrap:wrap;
      }
      .header h1{margin:0; font-size:28px; letter-spacing:-0.02em;}
      .header .date{color:var(--muted); font-size:14px; margin-top:6px;}
      .badge{
        font-size:12px; padding:7px 12px; border:1px solid var(--line);
        border-radius:999px; background:#fff; color:var(--ink);
        letter-spacing:0.08em; text-transform:uppercase;
      }

      .warn{
        margin-top:14px; padding:14px 14px;
        border:1px solid var(--line-soft); background:#fff;
        border-radius:14px; color:var(--muted);
        font-size:14px; line-height:1.65;
      }

      .card{
        margin-top:16px;
        padding:16px 16px;
        border:1px solid var(--line-soft);
        border-radius:16px;
        background:var(--card);
      }
      .summary-title{font-weight:900; font-size:16px; margin-bottom:10px;}
      .summary-body{font-size:14px; color:var(--muted); line-height:1.75;}

      .section{margin-top:26px;}
      .section h2{
        margin:0;
        font-size:20px;
        padding-bottom:10px;
        border-bottom:2px solid var(--line);
        display:flex;
        align-items:baseline;
        justify-content:space-between;
        gap:10px;
        flex-wrap:wrap;
      }
      .pill{
        font-size:12px;
        border:1px solid var(--line-soft);
        background:#fff;
        padding:6px 10px;
        border-radius:999px;
        color:var(--muted);
        white-space:nowrap;
      }
      .desc{
        margin-top:12px;
        color:var(--muted);
        font-size:14px;
        line-height:1.75;
      }

      .table-wrap{
        margin-top:14px;
        overflow-x:auto;
        -webkit-overflow-scrolling:touch;
        border:1px solid var(--line);
        border-radius:14px;
        background:#fff;
      }
      table{
        width:100%;
        border-collapse:collapse;
        min-width:980px;
        font-size:14px;
      }
      th{
        background:#000; color:#fff;
        padding:12px 10px;
        border-bottom:1px solid #000;
        position:sticky; top:0;
        white-space:nowrap;
      }
      td{
        padding:12px 10px;
        border-bottom:1px solid var(--line-soft);
        text-align:center;
        white-space:nowrap;
      }
      tr:nth-child(even) td{background:#fbfbfb;}
      tr:hover td{background:#f2f2f2;}

      .empty{
        margin-top:12px;
        padding:10px 2px;
        font-size:14px;
        color:var(--muted);
      }

      /* ✅ 종목명 크기: 표 기본 글씨 크기와 동일 (inherit) */
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
    <html>
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
          {render_table(premium)}
        </div>

        <div class="section">
          <h2>
            <span>Fast 종목 (스윙 관점)</span>
            <span class="pill">정렬: 선취매 강도 내림차순</span>
          </h2>
          {fast_desc}
          {render_table(fast)}
        </div>

        <div class="section">
          <h2>
            <span>과열 종목 (단타 위험 구간)</span>
            <span class="pill">정렬: 선취매 강도 내림차순</span>
          </h2>
          {overheat_desc}
          {render_table(overheat)}
        </div>

        <div class="section">
          <h2>
            <span>중장기 관심 종목</span>
            <span class="pill">정렬: 선취매 강도 내림차순</span>
          </h2>
          {interest_desc}
          {render_table(interest)}
        </div>

        {strength_explain}

      </div>
    </body>
    </html>
    """

    with open(out_name, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"HTML 저장 완료: {out_name}")
    webbrowser.open("file://" + os.path.abspath(out_name))


# ======================================================
def main():
    model = FlowRev9_1M2()
    premium, fast, overheat, interest = model.run()
    generate_html(model.trade_date, premium, fast, overheat, interest)


if __name__ == "__main__":
    main()