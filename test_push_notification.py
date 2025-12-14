# test_bot_push.py
from slack_sdk import WebClient

SLACK_TOKEN = "xoxb-9745985197379-10123228976753-ahTerLqgVeOoiQCL8gdmsJOL"
CHANNEL_ID = "C09MNTRR739"

client = WebClient(token=SLACK_TOKEN)

try:
    # 채널 전체 멘션 테스트
    response = client.chat_postMessage(
        channel=CHANNEL_ID,
        text="<!channel> 🧪 Bot API 푸시 알림 테스트입니다. 모든 분들에게 알림이 가나요?",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "<!channel> 🧪 *Bot API 푸시 알림 테스트*"
                }
            }
        ]
    )
    
    print(f"✅ 테스트 전송 성공: {response['ok']}")
    print("📱 스마트폰에 푸시 알림이 왔는지 확인하세요!")
    
except Exception as e:
    print(f"❌ 테스트 실패: {str(e)}")
