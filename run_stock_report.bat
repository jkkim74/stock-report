@echo off
setlocal EnableDelayedExpansion

REM ========================================
REM UTF-8 인코딩 환경 설정 (최우선)
REM ========================================
chcp 65001 >nul 2>&1

REM Python UTF-8 환경 변수
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PYTHONLEGACYWINDOWSSTDIO=utf-8

REM Git 한글 처리 설정
git config --global core.quotepath false
git config --global i18n.commitencoding utf-8
git config --global i18n.logoutputencoding utf-8

REM 작업 디렉토리로 이동
cd /d "D:\workspace\stockReport"

REM 로그 설정
set LOG_DIR=logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set TIMESTAMP=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set TIMESTAMP=%TIMESTAMP: =0%
set LOG_FILE=%LOG_DIR%\stock_report_%TIMESTAMP%.log

REM 실행 및 로깅
echo ========================================= >> "%LOG_FILE%"
echo 실행 시작: %date% %time% >> "%LOG_FILE%"
echo 인코딩 설정: UTF-8 >> "%LOG_FILE%"
echo ========================================= >> "%LOG_FILE%"

python stock_report.py >> "%LOG_FILE%" 2>&1

REM 결과 확인
if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] %date% %time% - 리포트 생성 완료 >> "%LOG_FILE%"
    exit /b 0
) else (
    echo [ERROR] %date% %time% - 실행 실패 (종료코드: %ERRORLEVEL%) >> "%LOG_FILE%"
    exit /b %ERRORLEVEL%
)