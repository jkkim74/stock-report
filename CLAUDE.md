# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Korean stock market (KOSPI/KOSDAQ) analysis pipeline. It pulls end-of-day market data, generates four self-contained HTML reports, and delivers them via Telegram. Everything is plain scripts — no package, no test suite.

Comments, log output, report copy, and commit messages are all Korean. Match that when editing.

**Read `AUDIT.md` first.** It is a full diagnostic of this codebase (2026-07-29) with a phased remediation plan and a progress table at the top. Phases 1–4 are done; 5–7 are not. Several known-broken behaviours documented there are still live — do not treat unexplained empty reports as new bugs before checking it.

## Commands

```bash
pip install -r requirements.txt   # bs4/lxml are lazy-imported but required (Naver fallback path)
python main.py                    # generate all 4 reports and send via DELIVERY_MODE
python report_generator.py        # dev/test: build premium + gap-updown reports into out/ (no sending)
python stock_report_scheduler.py  # local (Windows) scheduler, weekdays 15:40 host-local time
```

Single-report runs: `main.py` exposes `main_premium_only()`, `main_updown_only()`, `main_supply_only()`, and `main_custom(delivery_mode=...)`. Call them by editing the `__main__` block at the bottom of `main.py` (the commented examples are already there) or with `python -c "import main; main.main_premium_only()"`.

No tests, no linter config. `run_stock_report.bat` is stale — it `cd`s to `D:\workspace\stockReport` and runs a `stock_report.py`, neither of which exists. It fails on every invocation; do not use it.

Prototype scripts (`getUpAndDownReport.py`, `marketSummary.py`, `marketSuplyReport.py`, `report_generator_20251216.py`) and token-bearing one-off tools (`test_push_notification.py`, `get_group_chat_id.py`) were deleted — recover from git history if needed.

## Architecture

Three layers, deliberately decoupled:

1. **`report_generator.py`** (~2900 lines) — all analysis + HTML rendering. Knows nothing about delivery. Each of the four `generate_*` entry points returns a `ReportData(html_content, trade_date, metadata)` or `None` on failure (it catches its own exceptions and prints a traceback rather than raising).
2. **`notifiers.py`** — `BaseNotifier.send(report_data) -> {"success", "message", "url"}`. Implementations: `TelegramNotifier` (the only one in use), `TelegramChannelNotifier`, `GitHubPagesNotifier`, `SlackFileNotifier`, `LocalFileNotifier`, `CompositeNotifier`.
3. **`main.py`** — assembly only. Maps `DELIVERY_MODE` to a notifier, then runs each generator through `process_and_send_report`. A failing report never aborts the others.

> **Failure reporting is not trustworthy yet (phase 5).** Every layer currently converts failure into a success-shaped empty result: notifiers return `success: True` when only a sub-step succeeded, `CompositeNotifier` succeeds if *any* child did, and `main.py` never calls `sys.exit` so it always exits 0. A green run does not mean anything was delivered. See `AUDIT.md` §3 before relying on any success signal.

### The metadata contract

`metadata` is the integration point between the two layers and is switched on by string in **both** `main.py` (console summary) and `notifiers.py` (Telegram preview text). Adding a report means touching all three places.

| `report_type` | generator | `filename` |
|---|---|---|
| `premium_stock` | `generate_premium_stock_report` | `Premium_AI_Report_v4_{date}.html` |
| `gap_updown_risk` | `getUpAndDownReport` | `Gap_UpDown_Risk_Report_{date}.html` |
| `market_summary` | `generate_market_summary_report` | `Market_Summary_v10_8_{date}.html` |
| `market_supply` | `generate_market_supply_report` | `Market_Supply_Rev9_1_{date}.html` |

`metadata["filename"]` is required by every notifier — it is the on-disk name and the Telegram attachment name.

### Data sources and fallback chains

KRX blocks/changes its endpoints often, so every market-data path is defensive and **silently degrades**. When a report comes out empty or thin, suspect a fallback fired rather than a logic bug — check stdout for the `[WARNING]` lines.

- Trade date: `pykrx` OHLCV for 005930 (Samsung) → `get_nearest_business_day_in_a_week()` → today. Samsung is queried first because pykrx's business-day API returns empty when KRX changes its response shape.
- Universe load (`_load_premium_base_rows`): `pykrx` per market → `_load_krx_market_rows_direct` (raw KRX JSON at `getJsonData.cmd`) → `_load_naver_market_rows` (HTML scrape of finance.naver.com, euc-kr). The three paths do **not** produce identical universes or identical 거래대금 — see `AUDIT.md` P1-2.
- The KRX JSON session (`_build_krx_session`) logs in with `KRX_ID`/`KRX_PW` from `.env` when present, otherwise tries anonymously. Do **not** put placeholder values in `.env` — the code will attempt a login with them and fail, which is worse than the anonymous path. Leave them unset instead.
- Investor flow (`get_net_values`) returns `(None, None)` on failure, never `(0, 0)` — 0원 is a legitimate net flow, so failure must stay distinguishable. Callers guard with `flow_known`; the report renders `조회불가`. A consecutive-failure counter (`_KRX_INVESTOR_FAIL_STREAK`, limit 5) skips the rest of the run after a sustained outage but resets on any success. **This call is currently failing against live KRX** (`KeyError: '거래대금'` from inside pykrx), so premium/recommend sections come back empty — expected, not a regression.
- Macro/global signals (VIX, MOVE, futures, FX, TNX, sector ETFs) come from `yfinance`. Note `ES_ret_4h`/`NQ_ret_4h` are **always NaN**: `period="1d", interval="60m"` yields only 2 bars but the code indexes `iloc[-4]`. Fixing it requires re-tuning thresholds — deferred to phase 7.

### Configuration

All credentials live in `.env` (gitignored, hand-rolled loader `load_local_env()` in `config.py`, no python-dotenv). `config.py` reads them via `os.getenv` — **never hardcode a secret there**; the tokens that used to be in it were exposed in public git history and must stay out. `.env.example` lists every key.

Key knobs:
- `DELIVERY_MODE` — `"telegram"`. Telegram is the only channel in use; `github_pages` / `slack_file` are dead paths kept for now (`GITHUB_CONFIG["local_repo_path"]` points at a checkout that does not exist).
- `ANALYSIS_CONFIG` — the premium report's screen (change ≥5%, value ≥100B KRW, market cap ≥500B KRW, <300% off 52w low). These thresholds are the main tuning surface and get changed often (see commit `adda27d`). The Slack payload text in `notifiers.py` still hardcodes a stale 3000억 and does not track this.
- Market Supply has its own thresholds as module constants in `report_generator.py` (`SUPPLY_*`), not in `config.py`.

### Report HTML

Each report is one self-contained mobile-first HTML string built by an inline-template function (`generate_premium_html`, `build_gap_updown_html`, `_ms_build_html`, `_supply_build_html`). Charts are matplotlib rendered to base64 data URIs — no external assets, since the file has to survive being attached to a Telegram message.

Korean chart labels need a Korean font. `_setup_korean_font()` probes an installed-font list (Malgun Gothic → NanumGothic → …) rather than hardcoding one; hardcoding `Malgun Gothic` silently rendered every label as tofu boxes on Linux. The deploy installs `fonts-nanum` on the VM.

## Deployment

`.github/workflows/deploy.yml` runs on push to `main` (or `workflow_dispatch`). It verifies required secrets, rsyncs the repo, writes `.env` from GitHub Secrets, installs dependencies into a venv, and installs a systemd timer. It does **not** run a report — the timer owns execution.

- **Required secrets**: `VM_HOST`, `VM_USER`, `SSH_PRIVATE_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Optional: `KRX_ID`, `KRX_PW`, `SLACK_*`. The workflow fails fast if a required one is missing, rather than writing an empty `.env` and letting delivery break silently.
- **Schedule**: `deploy/stock-report.timer`, `OnCalendar=Mon-Fri 15:40 Asia/Seoul` (KRX closes 15:30 KST). Timezone is declared in the unit so the VM's system timezone is untouched; the deploy verifies systemd supports the suffix (247+).
- **The service sets `PYTHONIOENCODING=utf-8`.** `report_generator.py`'s UTF-8 stdout reconfiguration is `sys.platform == 'win32'`-gated, so under systemd's C/POSIX locale the ~124 emoji/Korean `print()` calls would raise `UnicodeEncodeError`.
- `rsync --delete` excludes `.env`, `logs`, `reports`, `__pycache__`, `*.html` — without those, each deploy wiped VM state.
- Ops: `sudo systemctl start stock-report.service` (manual run), `journalctl -u stock-report -n 200`, `systemctl list-timers stock-report.timer`.
- Requires passwordless sudo on the VM; the deploy checks `sudo -n` and fails with an explicit message otherwise.

`stock_report_scheduler.py` is the **local Windows** scheduler only. It uses host-local time (the `schedule` library has no timezone concept) and is not used on the VM.

`reports/` and the repo root are the GitHub Pages target (`.nojekyll` present). Pages is no longer a delivery channel, but `reports/*.html` remains tracked and served; generated HTML elsewhere is gitignored build output.
