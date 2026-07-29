# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Korean stock market (KOSPI/KOSDAQ) analysis pipeline. It pulls end-of-day market data, generates four self-contained HTML reports, and pushes them to a delivery channel (Telegram / GitHub Pages+Slack / local file). Everything is plain scripts — no package, no test suite, no dependency manifest.

Comments, log output, report copy, and commit messages are all Korean. Match that when editing.

## Commands

```bash
python main.py                    # generate all 4 reports and send via DELIVERY_MODE
python report_generator.py        # dev/test: build premium + gap-updown reports into out/ (no sending)
python stock_report_scheduler.py  # long-running scheduler (14:30 / 20:05 daily) that shells out to main.py
```

Single-report runs: `main.py` exposes `main_premium_only()`, `main_updown_only()`, `main_supply_only()`, and `main_custom(delivery_mode=...)`. Call them by editing the `__main__` block at the bottom of `main.py` (the commented examples are already there) or with `python -c "import main; main.main_premium_only()"`.

The prototype scripts these reports grew out of (`getUpAndDownReport.py`, `marketSummary.py`, `marketSuplyReport.py`, `report_generator_20251216.py`) were deleted — their logic lives in `report_generator.py` under `_ms_*` / `_supply_*` prefixes. Recover them from git history if you need the original standalone versions.

There are no tests, no linter config, and no `requirements.txt`. Deps in use: `pandas numpy matplotlib pykrx yfinance FinanceDataReader requests beautifulsoup4 lxml tqdm pytz schedule slack_sdk`.

Windows console needs UTF-8 (`chcp 65001`, `PYTHONUTF8=1`) — `run_stock_report.bat` sets this up, but note it `cd`s to `D:\workspace\stockReport` and runs a `stock_report.py` that no longer exists; it is stale.

## Architecture

Three layers, deliberately decoupled:

1. **`report_generator.py`** (~2900 lines) — all analysis + HTML rendering. Knows nothing about delivery. Each of the four `generate_*` entry points returns a `ReportData(html_content, trade_date, metadata)` or `None` on failure (it catches its own exceptions and prints a traceback rather than raising).
2. **`notifiers.py`** — `BaseNotifier.send(report_data) -> {"success", "message", "url"}`. Implementations: `GitHubPagesNotifier` (writes into a *separate* local repo and git-pushes, then Slack webhook), `SlackFileNotifier`, `TelegramNotifier`, `TelegramChannelNotifier`, `LocalFileNotifier`, `CompositeNotifier` (fan-out; succeeds if any child succeeds).
3. **`main.py`** — assembly only. Maps `DELIVERY_MODE` to a notifier, then runs each generator through `process_and_send_report`. A failing report never aborts the others.

### The metadata contract

`metadata` is the integration point between the two layers and is switched on by string in **both** `main.py` (console summary) and `notifiers.py` (Telegram preview text). Adding a report means touching all three places.

| `report_type` | generator | `filename` |
|---|---|---|
| `premium_stock` | `generate_premium_stock_report` | `Premium_AI_Report_v4_{date}.html` |
| `gap_updown_risk` | `getUpAndDownReport` | `Gap_UpDown_Risk_Report_{date}.html` |
| `market_summary` | `generate_market_summary_report` | `Market_Summary_v10_8_{date}.html` |
| `market_supply` | `generate_market_supply_report` | `Market_Supply_Rev9_1_{date}.html` |

`metadata["filename"]` is required by every notifier — it is the on-disk name, the GitHub Pages URL segment, and the Telegram attachment name.

### Data sources and fallback chains

KRX blocks/changes its endpoints often, so every market-data path is defensive and **silently degrades**. When a report comes out empty or thin, suspect a fallback fired rather than a logic bug — check stdout for the `[WARNING]` lines.

- Trade date: `pykrx` OHLCV for 005930 (Samsung) → `get_nearest_business_day_in_a_week()` → today. Samsung is queried first because pykrx's business-day API returns empty when KRX changes its response shape.
- Universe load (`_load_premium_base_rows`): `pykrx` per market → `_load_krx_market_rows_direct` (raw KRX JSON at `getJsonData.cmd`) → `_load_naver_market_rows` (HTML scrape of finance.naver.com, euc-kr).
- The KRX JSON session (`_build_krx_session`) logs in with `KRX_ID`/`KRX_PW` from `.env` when present, otherwise tries anonymously. A `LOGOUT` response body triggers one session rebuild + retry. `.env` is loaded by `config.py`'s hand-rolled `load_local_env()` (no python-dotenv), and is gitignored — see `.env.example`.
- Macro/global signals (VIX, MOVE, futures, FX, TNX, sector ETFs) come from `yfinance`, sector/flow data from `FinanceDataReader` + `pykrx`.

### Configuration

`config.py` holds everything and is **committed with live secrets in it** (Slack bot token/webhook, Telegram bot token) — only KRX credentials were moved to `.env`. Do not add more secrets to `config.py`; put them in `.env` and read via `os.getenv`.

Key knobs:
- `DELIVERY_MODE` — currently `"telegram"`. `"composite"` fans out to `COMPOSITE_MODES`.
- `ANALYSIS_CONFIG` — the premium report's screen (change ≥5%, value ≥100B KRW, market cap ≥500B KRW, <300% off 52w low). These thresholds are the main tuning surface and get changed often (see commit `adda27d`).
- `GITHUB_CONFIG["local_repo_path"]` points at `D:\workspace\stockReport`, a different checkout than this one; `GitHubPagesNotifier` fails fast if that path is absent.
- Market Supply has its own thresholds as module constants in `report_generator.py` (`SUPPLY_*`, around line 2244), not in `config.py`.

### Report HTML

Each report is one self-contained mobile-first HTML string built by an inline-template function (`generate_premium_html`, `build_gap_updown_html`, `_ms_build_html`, `_supply_build_html`). Charts are matplotlib rendered to base64 data URIs (Malgun Gothic font is set globally for Korean labels) — no external assets, since the file has to survive being emailed/attached/served from Pages.

## Deployment

`.github/workflows/deploy.yml` rsyncs the repo to a GCP VM on push to `main` and restarts `main.py` under `nohup` (`pkill -f main.py`). Note this launches `main.py` as a persistent process, but `main.py` runs once and exits — recurring execution on the VM depends on cron or `stock_report_scheduler.py` being set up there separately.

`reports/` and the repo root also serve as the GitHub Pages target (`.nojekyll` is present); generated HTML at the root is a build artifact, not source.
