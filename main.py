# -*- coding: utf-8 -*-
"""
메인 실행 스크립트
- 리포트 생성 + 발송 채널 조립
- 핵심 로직과 발송 로직을 연결하는 조립 계층
"""

from report_generator import generate_premium_stock_report
from notifiers import (
    GitHubPagesNotifier,
    SlackFileNotifier,
    LocalFileNotifier,
    CompositeNotifier,
    TelegramNotifier,           # 추가
    TelegramChannelNotifier     # 추가
)
from config import DELIVERY_MODE, COMPOSITE_MODES


def create_notifier(mode):
    """
    발송 방식에 따른 Notifier 생성
    
    Args:
        mode: 발송 방식 문자열
        
    Returns:
        BaseNotifier: 발송자 객체
    """
    
    if mode == "github_pages":
        return GitHubPagesNotifier()
    
    elif mode == "slack_file":
        return SlackFileNotifier()
    
    elif mode == "telegram":              # 신규 추가
        return TelegramNotifier()
    
    elif mode == "telegram_channel":      # 신규 추가 (채널용)
        return TelegramChannelNotifier()
    
    elif mode == "local_only":
        return LocalFileNotifier()
    
    elif mode == "composite":
        # 복합 발송: 여러 채널에 동시 발송
        notifiers = [create_notifier(m) for m in COMPOSITE_MODES]
        return CompositeNotifier(notifiers)
    
    else:
        raise ValueError(f"지원하지 않는 발송 방식: {mode}")


def main():
    """메인 실행 함수"""
    
    print("\n" + "="*70)
    print("🚀 AI 기반 프리미엄 추천 종목 리포트 v4 - 생성 시작")
    print("="*70 + "\n")
    
    # ===== 1. 리포트 생성 (핵심 로직 - 절대 수정 금지!) =====
    print("📊 리포트 데이터 분석 중...\n")
    
    try:
        report_data = generate_premium_stock_report()
    except Exception as e:
        print(f"\n❌ 리포트 생성 중 오류 발생: {str(e)}")
        return
    
    if report_data is None:
        print("\n❌ 리포트 생성 실패 - 조건을 만족하는 종목이 없습니다")
        return
    
    print(f"\n✅ 리포트 생성 완료!")
    print(f"   - 기준일: {report_data.trade_date}")
    print(f"   - 추천주: {report_data.metadata.get('recommend_count', 0)}종목")
    print(f"   - 프리미엄: {report_data.metadata.get('premium_count', 0)}종목")
    print(f"   - 관심: {report_data.metadata.get('watch_count', 0)}종목")
    
    # ===== 2. 발송자 생성 및 발송 (이 부분만 수정하면 됨!) =====
    print(f"\n📤 발송 모드: {DELIVERY_MODE}")
    print("-" * 70 + "\n")
    
    try:
        notifier = create_notifier(DELIVERY_MODE)
        result = notifier.send(report_data)
        
        print("\n" + "="*70)
        if result["success"]:
            print(f"✅ 발송 완료: {result['message']}")
            if result.get("url"):
                print(f"🔗 URL: {result['url']}")
        else:
            print(f"⚠️ 발송 실패: {result['message']}")
        print("="*70 + "\n")
            
    except Exception as e:
        print(f"\n❌ 발송 오류: {str(e)}\n")


def main_custom(delivery_mode=None):
    """
    커스텀 실행 함수 (특정 발송 방식 지정)
    
    Args:
        delivery_mode: 발송 방식 (None이면 config.py의 설정 사용)
    """
    
    # 리포트 생성
    report_data = generate_premium_stock_report()
    
    if report_data is None:
        print("❌ 리포트 생성 실패")
        return
    
    # 발송
    mode = delivery_mode or DELIVERY_MODE
    notifier = create_notifier(mode)
    result = notifier.send(report_data)
    
    if result["success"]:
        print(f"✅ 리포트 발송 완료: {result.get('url', '')}")
    else:
        print(f"⚠️ 리포트 발송 실패: {result['message']}")


if __name__ == "__main__":
    # 기본 실행
    main()
    
    # 커스텀 실행 예시 (주석 해제하여 사용)
    # main_custom(delivery_mode="composite")  # 복합 발송
    # main_custom(delivery_mode="local_only")  # 로컬 저장만
