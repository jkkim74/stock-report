# -*- coding: utf-8 -*-
"""
메인 실행 스크립트 v5
- 리포트 생성 + 발송 채널 조립
- 핵심 로직과 발송 로직을 연결하는 조립 계층
- 복수 리포트 지원 (Premium Stock + Gap Up & Down Risk)
"""

from report_generator import ( 
                              generate_premium_stock_report, 
                              getUpAndDownReport, 
                              generate_market_summary_report,  # 추가
                              generate_market_supply_report  # 추가
)
from notifiers import (
    GitHubPagesNotifier,
    SlackFileNotifier,
    LocalFileNotifier,
    CompositeNotifier,
    TelegramNotifier,
    TelegramChannelNotifier
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
    
    elif mode == "telegram":
        return TelegramNotifier()
    
    elif mode == "telegram_channel":
        return TelegramChannelNotifier()
    
    elif mode == "local_only":
        return LocalFileNotifier()
    
    elif mode == "composite":
        # 복합 발송: 여러 채널에 동시 발송
        notifiers = [create_notifier(m) for m in COMPOSITE_MODES]
        return CompositeNotifier(notifiers)
    
    else:
        raise ValueError(f"지원하지 않는 발송 방식: {mode}")


def process_and_send_report(generator_func, report_name, notifier):
    """
    개별 리포트 생성 및 발송 처리
    
    Args:
        generator_func: 리포트 생성 함수
        report_name: 리포트 이름 (로깅용)
        notifier: 발송자 객체
        
    Returns:
        bool: 성공 여부
    """
    print(f"\n📊 {report_name} 생성 중...")
    
    try:
        report_data = generator_func()
        
        if report_data is None:
            print(f"⚠️ {report_name}: 생성 실패 (조건 미충족 또는 데이터 없음)")
            return False
            
        # 리포트 타입별 상세 정보 출력
        print(f"✅ {report_name} 생성 완료!")
        print(f"   - 기준일: {report_data.trade_date}")
        
        if report_data.metadata.get('report_type') == 'premium_stock':
            print(f"   - 추천주: {report_data.metadata.get('recommend_count', 0)}종목")
            print(f"   - 프리미엄: {report_data.metadata.get('premium_count', 0)}종목")
            print(f"   - 관심: {report_data.metadata.get('watch_count', 0)}종목")
        elif report_data.metadata.get('report_type') == 'gap_updown_risk':
            kospi = report_data.metadata.get('kospi_scores', {})
            kosdaq = report_data.metadata.get('kosdaq_scores', {})
            print(f"   - KOSPI: 급등 {kospi.get('up', 0)}/급락 {kospi.get('down', 0)}")
            print(f"   - KOSDAQ: 급등 {kosdaq.get('up', 0)}/급락 {kosdaq.get('down', 0)}")
        # 기존 elif 블록들 다음에 추가
        elif report_data.metadata.get('report_type') == 'market_summary':
            k_comp = report_data.metadata.get('kospi_composite')
            q_comp = report_data.metadata.get('kosdaq_composite')
            k_band = report_data.metadata.get('kospi_band', 'N/A')
            q_band = report_data.metadata.get('kosdaq_band', 'N/A')
            
            # 🔧 수정된 출력 방식 (f-string 오류 방지)
            k_str = f"{k_comp:.1f}" if k_comp is not None else "N/A"
            q_str = f"{q_comp:.1f}" if q_comp is not None else "N/A"
            
            print(f"   - KOSPI: {k_str} ({k_band})")
            print(f"   - KOSDAQ: {q_str} ({q_band})")
        elif report_data.metadata.get('report_type') == 'market_supply':
            print(f"   - 프리미엄: {report_data.metadata.get('premium_count', 0)}종목")
            print(f"   - Fast: {report_data.metadata.get('fast_count', 0)}종목")
            print(f"   - 과열: {report_data.metadata.get('overheat_count', 0)}종목")
            print(f"   - 관심: {report_data.metadata.get('interest_count', 0)}종목")
            print(f"   - 총 분석: {report_data.metadata.get('total_analyzed', 0)}종목")

        
        # 발송
        print(f"📤 {report_name} 발송 중...")
        result = notifier.send(report_data)
        
        if result["success"]:
            print(f"🚀 {report_name} 발송 성공: {result['message']}")
            if result.get("url"):
                print(f"🔗 URL: {result['url']}")
            return True
        else:
            print(f"❌ {report_name} 발송 실패: {result['message']}")
            return False
            
    except Exception as e:
        print(f"❌ {report_name} 처리 중 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """메인 실행 함수"""
    
    print("\n" + "="*70)
    print("🚀 통합 AI 리포트 시스템 v7 - 실행 시작")  # 버전 업
    print("="*70)
    print(f"📤 발송 모드: {DELIVERY_MODE}\n")
    
    try:
        notifier = create_notifier(DELIVERY_MODE)
    except Exception as e:
        print(f"❌ 발송자 생성 실패: {str(e)}")
        return

    success_count = 0
    
    # 1. 프리미엄 주식 리포트
    print("-" * 70)
    if process_and_send_report(generate_premium_stock_report, "프리미엄 주식 리포트", notifier):
        success_count += 1

    # 2. Gap Up & Down 리스크 리포트  
    print("-" * 70)
    if process_and_send_report(getUpAndDownReport, "Gap Up & Down 리스크 리포트", notifier):
        success_count += 1
    
    # 3. Market Summary 리포트
    print("-" * 70)
    if process_and_send_report(generate_market_summary_report, "Market Summary 리포트", notifier):
        success_count += 1
    
    # 4. Market Supply 리포트 (신규 추가)
    print("-" * 70)
    if process_and_send_report(generate_market_supply_report, "Market Supply 리포트", notifier):
        success_count += 1
    
    # 최종 요약 (4개로 변경)
    print("\n" + "="*70)
    print(f"🏁 전체 작업 완료 - 성공: {success_count}/4")
    print("="*70 + "\n")


def main_supply_only():
    """Market Supply 리포트만 실행"""
    notifier = create_notifier(DELIVERY_MODE)
    process_and_send_report(generate_market_supply_report, "Market Supply 리포트", notifier)

def main_custom(delivery_mode=None):
    """커스텀 실행 함수 수정 (4개 리포트 지원)"""
    mode = delivery_mode or DELIVERY_MODE
    try:
        notifier = create_notifier(mode)
    except Exception as e:
        print(f"❌ Notifier 생성 실패: {str(e)}")
        return
    
    print(f"📤 커스텀 발송 모드: {mode}")
    
    results = []
    if process_and_send_report(generate_premium_stock_report, "프리미엄 주식", notifier):
        results.append("프리미엄 주식")
    if process_and_send_report(getUpAndDownReport, "Gap Up & Down", notifier):
        results.append("Gap Up & Down")
    if process_and_send_report(generate_market_summary_report, "Market Summary", notifier):
        results.append("Market Summary")
    if process_and_send_report(generate_market_supply_report, "Market Supply", notifier):
        results.append("Market Supply")
    
    print(f"\n✅ 커스텀 실행 완료 - 성공: {len(results)}/4")


# 개별 실행 함수들 (선택적 사용)
def main_premium_only():
    """프리미엄 주식 리포트만 실행"""
    notifier = create_notifier(DELIVERY_MODE)
    process_and_send_report(generate_premium_stock_report, "프리미엄 주식 리포트", notifier)


def main_updown_only():
    """Gap Up & Down 리포트만 실행"""
    notifier = create_notifier(DELIVERY_MODE)
    process_and_send_report(getUpAndDownReport, "Gap Up & Down 리스크 리포트", notifier)


if __name__ == "__main__":
    # ===== 기본 실행 (두 리포트 모두 생성) =====
    main()
    
    # ===== 개별 실행 예시 (주석 해제하여 사용) =====
    
    # 프리미엄 주식 리포트만
    # main_premium_only()
    
    # Gap Up & Down 리포트만
    # main_updown_only()
    
    # 커스텀 발송 방식
    # main_custom(delivery_mode="composite")  # 복합 발송
    # main_custom(delivery_mode="local_only")  # 로컬 저장만
    # main_custom(delivery_mode="telegram")   # 텔레그램만
