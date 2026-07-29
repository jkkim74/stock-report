"""로컬(주로 Windows) 실행용 스케줄러.

⚠️ 이 모듈은 **호스트의 로컬 시각**을 쓴다 (schedule 라이브러리에 타임존 개념이 없음).
    따라서 KST로 설정된 머신에서만 의도한 시각에 동작한다.
    GCP VM에서는 이 파일을 쓰지 않는다 - 배포된 서버의 실행 주기는
    deploy/stock-report.timer (systemd, Asia/Seoul 명시)가 소유한다.
"""

import schedule
import time
import subprocess
import logging
import sys
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
        
        # sys.executable을 쓴다. "python"은 PATH에 잡히는 아무 인터프리터를 가리키고
        # Ubuntu 20.04+ 에는 python 바이너리 자체가 없다.
        result = subprocess.run(
            [sys.executable, "main.py"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=os.path.dirname(os.path.abspath(__file__)),
            # 타임아웃이 없으면 main.py 안의 HTTP 호출 하나가 멈췄을 때
            # 이 단일 스레드 스케줄러가 영구 정지하고 이후 잡이 전부 실행되지 않는다.
            timeout=3600,
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
        
    except subprocess.TimeoutExpired:
        logging.error("❌ 실행 시간 초과(1시간) - 프로세스를 종료했습니다.")
    except Exception as e:
        logging.error(f"❌ 예외 발생: {str(e)}")

def main():
    """스케줄러 메인 함수"""
    
    # KRX 정규장 마감은 15:30 KST. 마감 후인 15:40에 평일만 실행한다.
    # (과거에는 every().day 로 14:30 - 즉 장중 - 과 20:05를 등록했다. 14:30 실행은
    #  미완성 일중 데이터로 리포트를 만들었고, 주말에는 금요일 데이터가 중복 발송됐다.)
    RUN_AT = "15:40"
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        getattr(schedule.every(), day).at(RUN_AT).do(run_stock_report)

    logging.info("🚀 AI 프리미엄 추천 종목 리포트 스케줄러 시작")
    logging.info(f"⏰ 실행 시간: 평일 {RUN_AT} (호스트 로컬 시각 - KST 머신에서만 유효)")
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