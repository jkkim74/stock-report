# -*- coding: utf-8 -*-
"""
리포트 발송 전략 모음
- 새로운 발송 채널 추가 시 이 파일만 수정
- Strategy 패턴으로 확장 가능하게 설계
"""

from abc import ABC, abstractmethod
import os
import subprocess
import requests
import json
import webbrowser
from config import GITHUB_CONFIG, SLACK_CONFIG, LOCAL_FILE_CONFIG


class BaseNotifier(ABC):
    """발송자 추상 클래스"""
    
    @abstractmethod
    def send(self, report_data):
        """
        리포트 발송
        
        Args:
            report_data: ReportData 객체
            
        Returns:
            dict: {"success": bool, "message": str, "url": str}
        """
        pass


class GitHubPagesNotifier(BaseNotifier):
    """GitHub Pages + Slack Webhook 발송"""
    
    def send(self, report_data):
        """GitHub Pages에 업로드하고 Slack으로 알림"""
        try:
            print("[GitHub Pages] 업로드 시작...")
            
            # 1. 저장소 경로 확인
            repo_path = GITHUB_CONFIG["local_repo_path"]
            if not os.path.exists(repo_path):
                return {"success": False, "message": f"저장소 경로 없음: {repo_path}", "url": ""}
            
            # 2. .nojekyll 파일 생성
            self._create_nojekyll(repo_path)
            
            # 3. HTML 파일 저장
            file_path = self._save_html_file(repo_path, report_data)
            
            # 4. Git 작업
            self._git_operations(repo_path, report_data.metadata["filename"])
            
            # 5. GitHub Pages URL 생성
            web_url = f"https://{GITHUB_CONFIG['username']}.github.io/{GITHUB_CONFIG['repo']}/reports/{report_data.metadata['filename']}"
            
            print(f"[GitHub Pages] 업로드 완료: {web_url}")
            print("[INFO] GitHub Pages 반영까지 1-2분 소요됩니다")
            
            # 6. Slack 알림
            slack_success = self._send_slack_notification(report_data, web_url)
            
            return {
                "success": slack_success,
                "message": "GitHub Pages 업로드 및 Slack 알림 완료" if slack_success else "GitHub Pages 업로드 완료, Slack 알림 실패",
                "url": web_url
            }
            
        except Exception as e:
            return {"success": False, "message": f"오류: {str(e)}", "url": ""}
    
    def _create_nojekyll(self, repo_path):
        """Jekyll 비활성화 파일 생성"""
        nojekyll_path = os.path.join(repo_path, ".nojekyll")
        if not os.path.exists(nojekyll_path):
            with open(nojekyll_path, "w") as f:
                f.write("")
            print("[GitHub Pages] .nojekyll 파일 생성")
    
    def _save_html_file(self, repo_path, report_data):
        """HTML 파일 저장"""
        reports_dir = os.path.join(repo_path, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        
        filename = report_data.metadata["filename"]
        file_path = os.path.join(reports_dir, filename)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(report_data.html_content)
        
        print(f"[GitHub Pages] HTML 파일 저장: reports/{filename}")
        return file_path
    
    def _git_operations(self, repo_path, filename):
        """Git 작업 처리"""
        try:
            # Pull (충돌 방지)
            subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=repo_path,
                capture_output=True,
                check=False
            )
            
            # Add
            subprocess.run(
                ["git", "add", "."],
                cwd=repo_path,
                check=True
            )
            
            # Commit
            try:
                subprocess.run(
                    ["git", "commit", "-m", f"Add AI premium stock report {filename}"],
                    cwd=repo_path,
                    check=True,
                    capture_output=True
                )
                print("[GitHub Pages] 커밋 완료")
            except subprocess.CalledProcessError:
                print("[GitHub Pages] 변경사항 없음 - 커밋 생략")
                return
            
            # Push
            subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=repo_path,
                check=True
            )
            print("[GitHub Pages] 푸시 완료")
            
        except subprocess.CalledProcessError as e:
            print(f"[GitHub Pages] Git 작업 실패: {str(e)}")
            raise
    
    def _send_slack_notification(self, report_data, web_url):
        """Slack 알림 전송"""
        if not SLACK_CONFIG.get("webhook_url"):
            print("[Slack] webhook_url 미설정 - 알림 전송 건너뜀")
            return True

        payload = {
            "text": f"<!channel> 📊 AI 기반 프리미엄 추천 종목 리포트 v4 ({report_data.trade_date}) - 오늘의 리포트가 준비되었습니다!",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"<!channel> 📊 *AI 기반 프리미엄 추천 종목 리포트 v4*\n\n*기준일:* {report_data.trade_date}"
                    }
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": "*분석 기준*\n시가총액 ≥ 3000억"},
                        {"type": "mrkdwn", "text": "*등락률*\n≥ 5%"},
                        {"type": "mrkdwn", "text": "*거래대금*\n≥ 1000억"},
                        {"type": "mrkdwn", "text": "*상태*\n🚀 준비 완료"}
                    ]
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*추천주*\n{report_data.metadata.get('recommend_count', 0)}종목"},
                        {"type": "mrkdwn", "text": f"*프리미엄*\n{report_data.metadata.get('premium_count', 0)}종목"},
                        {"type": "mrkdwn", "text": f"*관심*\n{report_data.metadata.get('watch_count', 0)}종목"},
                        {"type": "mrkdwn", "text": f"*생성시간*\n{report_data.metadata.get('generated_at', 'N/A')}"}
                    ]
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "📄 AI 프리미엄 리포트 보기",
                                "emoji": True
                            },
                            "url": web_url,
                            "style": "primary"
                        }
                    ]
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "💡 버튼을 클릭하면 브라우저에서 완전한 리포트를 확인할 수 있습니다."
                        }
                    ]
                }
            ]
        }
        
        try:
            response = requests.post(SLACK_CONFIG["webhook_url"], data=json.dumps(payload))
            
            if response.status_code == 200:
                print("[Slack] 알림 전송 완료!")
                return True
            else:
                print(f"[Slack] 알림 전송 실패: {response.text}")
                return False
                
        except Exception as e:
            print(f"[Slack] 알림 전송 오류: {str(e)}")
            return False


class SlackFileNotifier(BaseNotifier):
    """Slack 파일 직접 업로드"""
    
    def send(self, report_data):
        """Slack에 HTML 파일 직접 업로드"""
        temp_file = None

        if not SLACK_CONFIG.get("bot_token") or not SLACK_CONFIG.get("channel_id"):
            return {
                "success": False,
                "message": "SLACK_BOT_TOKEN 또는 SLACK_CHANNEL_ID가 설정되지 않았습니다.",
                "url": "",
            }

        try:
            from slack_sdk import WebClient
            from slack_sdk.errors import SlackApiError
        except ImportError:
            return {
                "success": False,
                "message": "slack-sdk 패키지가 설치되지 않았습니다. pip install -r requirements.txt",
                "url": "",
            }

        try:
            print("[Slack] 파일 업로드 시작...")

            # 임시 파일 생성
            temp_file = f"temp_{report_data.metadata['filename']}"
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(report_data.html_content)

            client = WebClient(token=SLACK_CONFIG["bot_token"])

            # 파일 업로드
            response = client.files_upload_v2(
                channel=SLACK_CONFIG["channel_id"],
                file=temp_file,
                title=f"AI 프리미엄 리포트 ({report_data.trade_date})",
                filename=report_data.metadata["filename"],
                initial_comment=self._create_upload_message(report_data)
            )

            # 임시 파일 삭제
            os.remove(temp_file)

            file_url = response.get('files', [{}])[0].get('permalink', 'N/A')
            print(f"[Slack] 파일 업로드 완료: {file_url}")

            return {
                "success": True,
                "message": "Slack 파일 업로드 완료",
                "url": file_url
            }

        except SlackApiError as e:
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
            error_code = e.response['error']
            print(f"[Slack] 업로드 실패: {error_code}")
            self._print_error_solution(error_code)
            return {"success": False, "message": f"Slack 업로드 실패: {error_code}", "url": ""}

        except Exception as e:
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
            print(f"[Slack] 업로드 오류: {str(e)}")
            return {"success": False, "message": f"Slack 업로드 실패: {str(e)}", "url": ""}
    
    def _create_upload_message(self, report_data):
        """업로드 메시지 생성"""
        return f"""📊 **AI 기반 프리미엄 추천 종목 리포트 v4**

📅 **기준일:** {report_data.trade_date}
🎯 **분석 기준:** 시가총액 ≥ 3000억, 등락률 ≥ 5%, 거래대금 ≥ 1000억

📊 **분석 결과:**
    • 추천주: {report_data.metadata.get('recommend_count', 0)}종목
    • 프리미엄: {report_data.metadata.get('premium_count', 0)}종목
    • 관심: {report_data.metadata.get('watch_count', 0)}종목

💡 **첨부된 HTML 파일을 다운로드하여 브라우저에서 확인하세요!**

⚠️ **투자 유의사항:** 데이터 기반 통계적 추천이므로 신중한 판단하에 투자하시기 바랍니다."""
    
    def _print_error_solution(self, error_code):
        """오류별 해결 방법 출력"""
        error_solutions = {
            'invalid_auth': [
                "1. https://api.slack.com/apps 접속",
                "2. 앱 선택 → 'OAuth & Permissions'",
                "3. 'Bot User OAuth Token' (xoxb-로 시작) 다시 복사"
            ],
            'not_in_channel': [
                "1. Slack 채널에서 '/invite @봇이름' 명령어 실행",
                "2. 채널 설정 → 통합 → 앱 추가로 봇 초대"
            ],
            'missing_scope': [
                "1. OAuth & Permissions → Bot Token Scopes",
                "2. 'files:write' 권한 추가",
                "3. 'Reinstall to Workspace' 클릭"
            ]
        }
        
        if error_code in error_solutions:
            print("\n💡 해결 방법:")
            for step in error_solutions[error_code]:
                print(f"   {step}")


class LocalFileNotifier(BaseNotifier):
    """로컬 파일 저장 + 브라우저 열기"""
    
    def send(self, report_data):
        """로컬에 HTML 파일 저장"""
        try:
            print("[로컬] 파일 저장 시작...")
            
            os.makedirs(LOCAL_FILE_CONFIG["output_dir"], exist_ok=True)
            file_path = os.path.join(LOCAL_FILE_CONFIG["output_dir"], report_data.metadata["filename"])
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(report_data.html_content)
            
            print(f"[로컬] 파일 저장 완료: {file_path}")
            
            if LOCAL_FILE_CONFIG["open_browser"]:
                webbrowser.open("file://" + os.path.abspath(file_path))
                print("[로컬] 브라우저에서 리포트 열기")
            
            return {
                "success": True,
                "message": f"로컬 저장 완료: {file_path}",
                "url": f"file://{os.path.abspath(file_path)}"
            }
            
        except Exception as e:
            print(f"[로컬] 저장 실패: {str(e)}")
            return {"success": False, "message": f"로컬 저장 실패: {str(e)}", "url": ""}


class CompositeNotifier(BaseNotifier):
    """여러 발송자를 조합 (예: GitHub + 로컬 파일 동시)"""
    
    def __init__(self, notifiers):
        self.notifiers = notifiers
    
    def send(self, report_data):
        """모든 발송자를 순차 실행"""
        results = []
        
        print(f"\n{'='*60}")
        print(f"복합 발송 시작 ({len(self.notifiers)}개 채널)")
        print(f"{'='*60}\n")
        
        for i, notifier in enumerate(self.notifiers, 1):
            notifier_name = notifier.__class__.__name__
            print(f"[{i}/{len(self.notifiers)}] {notifier_name} 실행 중...")
            
            try:
                result = notifier.send(report_data)
                results.append(result)
                
                status = "✅ 성공" if result["success"] else "❌ 실패"
                print(f"{status}: {result['message']}\n")
                
            except Exception as e:
                error_result = {"success": False, "message": f"오류: {str(e)}", "url": ""}
                results.append(error_result)
                print(f"❌ 오류: {str(e)}\n")
        
        success_count = sum(1 for r in results if r["success"])
        
        print(f"{'='*60}")
        print(f"복합 발송 완료: {success_count}/{len(results)} 성공")
        print(f"{'='*60}\n")
        
        return {
            "success": success_count > 0,
            "message": f"{success_count}/{len(results)} 발송 성공",
            "results": results
        }


# ===== 미래 확장을 위한 예시 =====

class EmailNotifier(BaseNotifier):
    """이메일 발송 (미래 확장)"""
    
    def __init__(self, smtp_config):
        self.smtp_config = smtp_config
    
    def send(self, report_data):
        # TODO: 이메일 발송 로직 구현
        return {
            "success": False,
            "message": "이메일 발송 기능 준비 중",
            "url": ""
        }


# notifiers.py (파일 끝부분에 추가)

import tempfile
import os
from config import TELEGRAM_CONFIG


class TelegramNotifier(BaseNotifier):
    """Telegram Bot을 통한 리포트 발송"""
    
    def send(self, report_data):
        """Telegram으로 리포트 발송 (미리보기 + 파일)"""
        try:
            print("[Telegram] 발송 시작...")
            
            # 설정값 검증
            bot_token = TELEGRAM_CONFIG["bot_token"]
            chat_id = TELEGRAM_CONFIG["chat_id"]
            
            if not bot_token or bot_token.startswith("1234567890"):
                return {
                    "success": False,
                    "message": "Telegram Bot Token이 설정되지 않았습니다. config.py를 확인하세요.",
                    "url": ""
                }
            
            results = []
            
            # 1. 미리보기 메시지 전송
            if TELEGRAM_CONFIG.get("send_preview", True):
                preview_result = self._send_preview_message(bot_token, chat_id, report_data)
                results.append(("미리보기", preview_result))
            
            # 2. HTML 파일 전송
            if TELEGRAM_CONFIG.get("send_as_file", True):
                file_result = self._send_html_file(bot_token, chat_id, report_data)
                results.append(("파일", file_result))
            else:
                # 파일 전송하지 않으면 상세 요약 메시지 전송
                summary_result = self._send_detailed_summary(bot_token, chat_id, report_data)
                results.append(("상세요약", summary_result))
            
            # 결과 종합
            success_count = sum(1 for _, result in results if result["success"])
            total_count = len(results)
            
            if success_count > 0:
                print(f"[Telegram] 발송 완료! ({success_count}/{total_count} 성공)")
                return {
                    "success": True,
                    "message": f"Telegram 발송 완료 ({success_count}/{total_count} 성공)",
                    "url": f"https://t.me/{TELEGRAM_CONFIG.get('bot_username', 'bot')}"
                }
            else:
                failed_messages = [f"{name}: {result['message']}" for name, result in results if not result["success"]]
                return {
                    "success": False,
                    "message": f"Telegram 발송 실패: {'; '.join(failed_messages)}",
                    "url": ""
                }
                
        except Exception as e:
            print(f"[Telegram] 예외 발생: {str(e)}")
            return {"success": False, "message": f"Telegram 발송 오류: {str(e)}", "url": ""}
    
    def _send_preview_message(self, bot_token, chat_id, report_data):
        """간단한 미리보기 메시지 전송 (정렬 문제 해결)"""
        try:
            # 리포트 타입별 메시지 생성
            if report_data.metadata.get('report_type') == 'premium_stock':
                message = (
                    f"🚀 <b>AI 기반 프리미엄 추천 종목 리포트 v4</b>\n\n"
                    f"📅 <b>기준일:</b> {report_data.trade_date}\n\n"
                    f"📊 <b>분석 결과:</b>\n"
                    f"🔥 추천주: {report_data.metadata.get('recommend_count', 0)}종목\n"
                    f"⭐ 프리미엄: {report_data.metadata.get('premium_count', 0)}종목\n"
                    f"👀 관심: {report_data.metadata.get('watch_count', 0)}종목\n\n"
                    f"📎 상세 리포트 파일을 전송합니다..."
                )
                
            elif report_data.metadata.get('report_type') == 'gap_updown_risk':
                kospi_scores = report_data.metadata.get('kospi_scores', {})
                kosdaq_scores = report_data.metadata.get('kosdaq_scores', {})
                
                message = (
                    f"🚀 <b>AI 기반 UP&Down Risk 리포트 v4</b>\n\n"
                    f"📅 <b>기준일:</b> {report_data.trade_date}\n\n"
                    f"📊 <b>리스크 분석:</b>\n"
                    f"📈 KOSPI: 급등 {kospi_scores.get('up', 0)}/급락 {kospi_scores.get('down', 0)}\n"
                    f"📉 KOSDAQ: 급등 {kosdaq_scores.get('up', 0)}/급락 {kosdaq_scores.get('down', 0)}\n\n"
                    f"📎 상세 리포트 파일을 전송합니다..."
                )
             # 기존 elif 블록들 다음에 추가
            elif report_data.metadata.get('report_type') == 'market_summary':
                k_comp = report_data.metadata.get('kospi_composite')
                q_comp = report_data.metadata.get('kosdaq_composite')
                k_band = report_data.metadata.get('kospi_band', 'N/A')
                q_band = report_data.metadata.get('kosdaq_band', 'N/A')
                
                # 🔧 수정된 메시지 생성 (f-string 오류 방지)
                k_str = f"{k_comp:.1f}" if k_comp is not None else "N/A"
                q_str = f"{q_comp:.1f}" if q_comp is not None else "N/A"
                
                message = (
                    f"📊 <b>Market Summary v10.8</b>\n\n"
                    f"📅 <b>기준일:</b> {report_data.trade_date}\n\n"
                    f"📈 <b>시장 컨디션:</b>\n"
                    f"• KOSPI: {k_str} ({k_band})\n"
                    f"• KOSDAQ: {q_str} ({q_band})\n\n"
                    f"📎 상세 리포트 파일을 전송합니다..."
                )
            # 기존 elif 블록들 다음에 추가
            elif report_data.metadata.get('report_type') == 'market_supply':
                message = (
                    f"📊 <b>기관·외국인 수급 리포트 Rev9.1</b>\n\n"
                    f"📅 <b>기준일:</b> {report_data.trade_date}\n\n"
                    f"📈 <b>분석 결과:</b>\n"
                    f"💎 프리미엄: {report_data.metadata.get('premium_count', 0)}종목\n"
                    f"🚀 Fast: {report_data.metadata.get('fast_count', 0)}종목\n"
                    f"🔥 과열: {report_data.metadata.get('overheat_count', 0)}종목\n"
                    f"👀 관심: {report_data.metadata.get('interest_count', 0)}종목\n\n"
                    f"📎 상세 리포트 파일을 전송합니다..."
                )
            else:
                # 기본 메시지 (새로운 리포트 타입 대응)
                message = (
                    f"🚀 <b>AI 리포트</b>\n\n"
                    f"📅 <b>기준일:</b> {report_data.trade_date}\n\n"
                    f"📎 상세 리포트 파일을 전송합니다..."
                )

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": TELEGRAM_CONFIG.get("parse_mode", "HTML"),
                "disable_web_page_preview": True
            }
            
            response = requests.post(url, json=payload)
            
            if response.status_code == 200:
                print("[Telegram] 미리보기 전송 완료")
                return {"success": True, "message": "미리보기 전송 성공"}
            else:
                error_msg = response.json().get("description", response.text)
                print(f"[Telegram] 미리보기 전송 실패: {error_msg}")
                return {"success": False, "message": f"미리보기 실패: {error_msg}"}
                
        except Exception as e:
            return {"success": False, "message": f"미리보기 오류: {str(e)}"}

    
    def _send_html_file(self, bot_token, chat_id, report_data):
        """HTML 파일을 Telegram 문서로 전송"""
        temp_file = None
        try:
            # 파일 크기 체크 (대략적)
            file_size_mb = len(report_data.html_content.encode('utf-8')) / (1024 * 1024)
            limit_mb = TELEGRAM_CONFIG.get("file_size_limit_mb", 45)
            
            if file_size_mb > limit_mb:
                return {
                    "success": False, 
                    "message": f"파일 크기 초과 ({file_size_mb:.1f}MB > {limit_mb}MB)"
                }
            
            # 안전한 임시 파일 생성
            with tempfile.NamedTemporaryFile(
                mode='w', 
                encoding='utf-8', 
                suffix='.html', 
                delete=False
            ) as f:
                f.write(report_data.html_content)
                temp_file = f.name
            
            # Telegram API로 문서 전송
            url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
            
            with open(temp_file, 'rb') as f:
                files = {'document': (report_data.metadata["filename"], f, 'text/html')}
                data = {
                    'chat_id': chat_id,
                    'caption': '',
                    'parse_mode': 'HTML'
                }
                
                response = requests.post(url, files=files, data=data)
            
            # 임시 파일 정리
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
            
            if response.status_code == 200:
                print("[Telegram] 파일 전송 완료")
                return {"success": True, "message": "파일 전송 성공"}
            else:
                error_msg = response.json().get("description", response.text)
                print(f"[Telegram] 파일 전송 실패: {error_msg}")
                return {"success": False, "message": f"파일 전송 실패: {error_msg}"}
                
        except Exception as e:
            # 예외 발생 시 임시 파일 정리
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
            return {"success": False, "message": f"파일 전송 오류: {str(e)}"}
    
    def _send_detailed_summary(self, bot_token, chat_id, report_data):
        """파일 대신 상세 텍스트 요약 전송"""
        try:
            message = (
                f"📊 <b>AI 기반 프리미엄 추천 종목 리포트 v4</b>\n\n"
                f"📅 <b>기준일:</b> {report_data.trade_date}\n\n"
                f"📊 <b>분석 결과:</b>\n"
                f"🔥 추천주: {report_data.metadata.get('recommend_count', 0)}종목\n"
                f"⭐ 프리미엄: {report_data.metadata.get('premium_count', 0)}종목\n"
                f"👀 관심: {report_data.metadata.get('watch_count', 0)}종목\n"
                f"📈 전체: {report_data.metadata.get('total_stocks', 0)}종목\n\n"
                f"⚠️ <b>투자 유의사항:</b>\n"
                f"데이터 기반 통계적 추천이므로 신중한 판단하에 투자하시기 바랍니다."
            )

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            
            response = requests.post(url, json=payload)
            
            if response.status_code == 200:
                return {"success": True, "message": "상세 요약 전송 성공"}
            else:
                error_msg = response.json().get("description", response.text)
                return {"success": False, "message": f"상세 요약 실패: {error_msg}"}
                
        except Exception as e:
            return {"success": False, "message": f"상세 요약 오류: {str(e)}"}



class TelegramChannelNotifier(BaseNotifier):
    """Telegram 채널 발송 (공개 채널용)"""
    
    def send(self, report_data):
        """Telegram 채널로 리포트 발송"""
        try:
            print("[Telegram Channel] 발송 시작...")
            
            bot_token = TELEGRAM_CONFIG["bot_token"]
            channel_id = TELEGRAM_CONFIG.get("channel_id", TELEGRAM_CONFIG["chat_id"])
            
            # 채널 ID 형식 검증
            if not (str(channel_id).startswith("@") or str(channel_id).startswith("-100")):
                return {
                    "success": False,
                    "message": "채널 ID는 @channel_name 또는 -100xxxxxxxxx 형식이어야 합니다",
                    "url": ""
                }
            
            # 채널용 메시지 생성 및 전송
            message = f"""📊 <b>AI 기반 프리미엄 추천 종목 리포트 v4</b>

            📅 기준일: {report_data.trade_date}

            🔥 추천주: {report_data.metadata.get('recommend_count', 0)}종목
            ⭐ 프리미엄: {report_data.metadata.get('premium_count', 0)}종목  
            👀 관심: {report_data.metadata.get('watch_count', 0)}종목

            📎 상세 리포트는 첨부 파일을 확인하세요!

            ⚠️ 투자 유의: 데이터 기반 통계적 추천이므로 신중한 판단 필요"""

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": channel_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            
            response = requests.post(url, json=payload)
            
            if response.status_code == 200:
                print("[Telegram Channel] 메시지 전송 완료")
                
                # 파일도 전송
                file_result = self._send_channel_file(bot_token, channel_id, report_data)
                
                return {
                    "success": True,
                    "message": "Telegram 채널 발송 완료",
                    "url": f"https://t.me/{str(channel_id).lstrip('@')}"
                }
            else:
                error_msg = response.json().get("description", response.text)
                return {
                    "success": False,
                    "message": f"채널 발송 실패: {error_msg}",
                    "url": ""
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"채널 발송 오류: {str(e)}",
                "url": ""
            }
    
    def _send_channel_file(self, bot_token, channel_id, report_data):
        """채널에 파일 전송"""
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', suffix='.html', delete=False
            ) as f:
                f.write(report_data.html_content)
                temp_file = f.name
            
            url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
            
            with open(temp_file, 'rb') as f:
                files = {'document': (report_data.metadata["filename"], f, 'text/html')}
                data = {'chat_id': channel_id}
                requests.post(url, files=files, data=data)
            
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
                
            return True
            
        except Exception as e:
            print(f"[Telegram Channel] 파일 전송 실패: {str(e)}")
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
            return False
