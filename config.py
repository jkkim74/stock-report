# -*- coding: utf-8 -*-
"""
설정 관리 모듈 - 모든 설정값을 중앙에서 관리
환경변수 우선 로딩으로 로컬/서버/CI 환경을 모두 지원
"""

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


# ===== 분석 기준 설정 =====
ANALYSIS_CONFIG = {
    "MIN_CHANGE": float(os.getenv("ANALYSIS_MIN_CHANGE", "5.0")),
    "MIN_VALUE": int(os.getenv("ANALYSIS_MIN_VALUE", "100000000000")),
    "MIN_MCAP": int(os.getenv("ANALYSIS_MIN_MCAP", "500000000000")),
    "MAX_FROM_LOW": float(os.getenv("ANALYSIS_MAX_FROM_LOW", "300.0")),
    "EPS": float(os.getenv("ANALYSIS_EPS", "1e-6")),
    "LOOKBACK_52W_DAYS": int(os.getenv("ANALYSIS_LOOKBACK_52W_DAYS", "365")),
    "LOOKBACK_PATTERN_DAYS": int(os.getenv("ANALYSIS_LOOKBACK_PATTERN_DAYS", "40")),
}

# ===== GitHub Pages 설정 =====
# 기본값은 현재 프로젝트 경로로 설정 (OS 독립)
GITHUB_CONFIG = {
    "local_repo_path": os.getenv("GITHUB_LOCAL_REPO_PATH", str(BASE_DIR)),
    "username": os.getenv("GITHUB_USERNAME", ""),
    "repo": os.getenv("GITHUB_REPO", ""),
}

# ===== Slack 설정 =====
SLACK_CONFIG = {
    "webhook_url": os.getenv("SLACK_WEBHOOK_URL", ""),
    "bot_token": os.getenv("SLACK_BOT_TOKEN", ""),
    "channel_id": os.getenv("SLACK_CHANNEL_ID", ""),
}

# ===== Telegram 설정 =====
TELEGRAM_CONFIG = {
    "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
    "bot_username": os.getenv("TELEGRAM_BOT_USERNAME", "bot"),
    "send_preview": _get_bool("TELEGRAM_SEND_PREVIEW", True),
    "send_as_file": _get_bool("TELEGRAM_SEND_AS_FILE", True),
    "parse_mode": os.getenv("TELEGRAM_PARSE_MODE", "HTML"),
    "file_size_limit_mb": _get_int("TELEGRAM_FILE_SIZE_LIMIT_MB", 45),
}

# ===== 발송 방식 선택 =====
# 옵션: "github_pages", "slack_file", "telegram", "telegram_channel", "local_only", "composite"
DELIVERY_MODE = os.getenv("DELIVERY_MODE", "local_only")

# ===== 복합 발송 설정 =====
COMPOSITE_MODES = _get_list("COMPOSITE_MODES", ["local_only"])

# ===== 로컬 파일 저장 설정 =====
LOCAL_FILE_CONFIG = {
    "output_dir": os.getenv("LOCAL_OUTPUT_DIR", "."),
    "open_browser": _get_bool("LOCAL_OPEN_BROWSER", True),
}
