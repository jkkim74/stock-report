@echo off
REM ========================================
REM AI 프리미엄 추천 종목 리포트 자동 실행
REM ========================================

REM UTF-8 코드페이지 설정 (65001 = UTF-8)
chcp 65001 >nul 2>&1

REM Python UTF-8 환경 변수 설정
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

REM 작업 디렉토리로 이동
cd /d "D:\workspace\stockReport"

REM 로그 파일 설정
set LOG_DIR=D:\workspace\stockReport\logs
set TIMESTAMP=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set TIMESTAMP=%TIMESTAMP: =0%
set LOG_FILE=%LOG_DIR%\stock_report_%TIMESTAMP%.log

REM 로그 디렉토리 생성
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM 실행 시작 로그
echo ========================================= >> "%LOG_FILE%"
echo 실행 시작: %date% %time% >> "%LOG_FILE%"
echo 작업 디렉토리: %CD% >> "%LOG_FILE%"
echo ========================================= >> "%LOG_FILE%"

REM Python 스크립트 실행
python stock_report.py >> "%LOG_FILE%" 2>&1

REM 실행 결과 확인
if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] %date% %time% - 리포트 생성 성공 >> "%LOG_FILE%"
    exit /b 0
) else (
    echo [ERROR] %date% %time% - 실행 실패 ^(종료 코드: %ERRORLEVEL%^) >> "%LOG_FILE%"
    exit /b %ERRORLEVEL%
)