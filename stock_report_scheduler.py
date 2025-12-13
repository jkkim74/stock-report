import schedule
import time
import subprocess
import logging
from datetime import datetime
import os

# 로깅 설정
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/scheduler_{datetime.now().strftime("%Y%m%d")}.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def run_stock_report():
    """리포트 생성 작업 실행"""
    try:
        logging.info("=" * 60)
        logging.info("AI 프리미엄 추천 종목 리포트 생성 시작")
        logging.info("=" * 60)
        
        # stock_report.py 실행
        # ✅ 수정된 코드 (즉시 해결)
        result = subprocess.run(
            ["python", "stock_report.py"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',  # 🔥 이 한 줄 추가로 해결!
            cwd=os.getcwd()
        )
        
        # 실행 결과 로깅
        if result.returncode == 0:
            logging.info("✅ 리포트 생성 성공!")
            if result.stdout.strip():
                logging.info(f"출력:\n{result.stdout}")
        else:
            logging.error(f"❌ 리포트 생성 실패! (종료 코드: {result.returncode})")
            if result.stderr.strip():
                logging.error(f"오류:\n{result.stderr}")
        
        logging.info("=" * 60)
        
    except Exception as e:
        logging.error(f"❌ 예외 발생: {str(e)}")

def main():
    """스케줄러 메인 함수"""
    
    # 스케줄 설정 (한국 주식시장 기준)
    # 매일 오후 3시 40분에 실행 (장마감 후)
    schedule.every().day.at("22:15").do(run_stock_report)
    
    # 평일만 실행하고 싶다면 (선택사항):
    # schedule.every().monday.at("15:40").do(run_stock_report)
    # schedule.every().tuesday.at("15:40").do(run_stock_report)
    # schedule.every().wednesday.at("15:40").do(run_stock_report)
    # schedule.every().thursday.at("15:40").do(run_stock_report)
    # schedule.every().friday.at("15:40").do(run_stock_report)
    
    logging.info("🚀 AI 프리미엄 추천 종목 리포트 스케줄러 시작")
    logging.info(f"⏰ 실행 시간: 매일 20:05")
    logging.info(f"📂 작업 디렉토리: {os.getcwd()}")
    
    # 즉시 실행 테스트 (선택사항)
    # logging.info("🧪 즉시 테스트 실행 중...")
    # run_stock_report()
    
    # 스케줄 대기 루프
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # 1분마다 체크
    except KeyboardInterrupt:
        logging.info("\n⏹️  스케줄러 종료됨 (Ctrl+C)")

if __name__ == "__main__":
    main()