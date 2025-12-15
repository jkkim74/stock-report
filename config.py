# -*- coding: utf-8 -*-
"""
설정 관리 모듈 - 모든 설정값을 중앙에서 관리
"""

# ===== 분석 기준 설정 =====
ANALYSIS_CONFIG = {
    "MIN_CHANGE": 5.0,                   # 등락률 ≥ 5%
    "MIN_VALUE": 100_000_000_000,        # 거래대금 ≥ 1000억 (원)
    "MIN_MCAP": 300_000_000_000,         # 시가총액 ≥ 3000억 (원)
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
SLACK_CONFIG = {
    # Webhook URL (GitHub Pages 알림용)
    "webhook_url": "https://hooks.slack.com/services/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",
    
    # Bot Token (파일 업로드용)
    "bot_token": "xoxb-9745985197379-10123228976753-ahTerLqgVeOoiQCL8gdmsJOL",
    
    # 채널 ID
    "channel_id": "C09MNTRR739"
}

# ===== 발송 방식 선택 =====
# 옵션: "github_pages", "slack_file", "local_only", "composite"
DELIVERY_MODE = "github_pages"

# ===== 복합 발송 설정 =====
COMPOSITE_MODES = ["github_pages", "local_only"]  # 동시 실행할 발송 방식들

# ===== 로컬 파일 저장 설정 =====
LOCAL_FILE_CONFIG = {
    "output_dir": ".",
    "open_browser": True
}
