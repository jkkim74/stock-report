# -*- coding: utf-8 -*-
"""
설정 관리 모듈 - 모든 설정값을 중앙에서 관리
"""

import os
from pathlib import Path


def load_local_env(path=".env"):
    """Load local .env values without adding a runtime dependency."""
    env_path = Path(__file__).resolve().parent / path
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_local_env()

# ===== 분석 기준 설정 =====
ANALYSIS_CONFIG = {
    "MIN_CHANGE": 5.0,                   # 등락률 ≥ 5%
    "MIN_VALUE": 100_000_000_000,        # 거래대금 ≥ 1000억 (원)
    "MIN_MCAP": 500_000_000_000,         # 시가총액 ≥ 5000억 (원)
    "MAX_FROM_LOW": 300.0,               # 52주최저대비 < 300%
    "EPS": 1e-6,
    "LOOKBACK_52W_DAYS": 365,
    "LOOKBACK_PATTERN_DAYS": 40
}

# ===== GitHub Pages 설정 =====
GITHUB_CONFIG = {
    "local_repo_path": r"D:\workspace\stockReport",
    "username": "jkkim74",
    "repo": "stock-report"
}

# ===== Slack 설정 =====
# 모든 자격증명은 .env에서 읽는다 (.env는 gitignore 대상).
# 소스에 하드코딩하지 말 것 - 과거 커밋된 토큰은 전량 폐기되었다.
SLACK_CONFIG = {
    # Webhook URL (GitHub Pages 알림용)
    "webhook_url": os.getenv("SLACK_WEBHOOK_URL", ""),

    # Bot Token (파일 업로드용)
    "bot_token": os.getenv("SLACK_BOT_TOKEN", ""),

    # 채널 ID
    "channel_id": os.getenv("SLACK_CHANNEL_ID", "")
}

# ===== Telegram 설정 =====
TELEGRAM_CONFIG = {
    # BotFather에서 받은 Bot Token
    "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),

    # Chat ID (개인: 숫자, 채널: @channel_name 또는 -100xxx)
    "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),

    # 발송 옵션
    "send_preview": True,       # 미리보기 메시지 포함 여부
    "send_as_file": True,       # HTML 파일 첨부 여부
    "parse_mode": "HTML",       # 메시지 형식 (HTML 또는 Markdown)
    "file_size_limit_mb": 45    # 파일 크기 제한 (Telegram 최대 50MB)
}

# ===== 발송 방식 선택 =====
# 옵션: "github_pages", "slack_file", "local_only", "composite"
DELIVERY_MODE = "telegram"#"github_pages"

# ===== 복합 발송 설정 =====
COMPOSITE_MODES = ["telegram", "local_only"]#["github_pages", "local_only"]  # 동시 실행할 발송 방식들

# ===== 로컬 파일 저장 설정 =====
LOCAL_FILE_CONFIG = {
    "output_dir": ".",
    "open_browser": True
}
