# get_chat_id.py
import requests
import time

# ⚠️ 재발급받은 새 토큰을 여기에 입력
BOT_TOKEN = "8501237845:AAHAKqCqTPODqpS1NSMcIaUD_Mg3CuAUK9c"

def get_chat_id():
    print("="*60)
    print("📱 Telegram Chat ID 자동 추출 도구")
    print("="*60)
    print("\n📌 다음 단계를 먼저 완료하세요:")
    print("   1. Telegram에서 본인의 봇 검색")
    print("   2. 봇과 대화 시작 (/start)")
    print("   3. 아무 메시지 전송 (예: 'hello')")
    print("\n" + "="*60)
    
    input("\n메시지를 보냈다면 Enter를 눌러주세요...")
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if not data.get("ok"):
            print(f"\n❌ API 오류: {data}")
            return
        
        results = data.get("result", [])
        
        if not results:
            print("\n⚠️ 아직 메시지가 없습니다!")
            print("봇에게 메시지를 보낸 후 다시 실행하세요.")
            return
        
        print("\n✅ Chat ID를 찾았습니다!\n")
        
        # 최근 메시지에서 Chat ID 추출
        latest_message = results[-1]["message"]
        chat_id = latest_message["chat"]["id"]
        chat_type = latest_message["chat"]["type"]
        user_name = latest_message["chat"].get("first_name", "Unknown")
        
        print("="*60)
        print(f"👤 사용자: {user_name}")
        print(f"📱 채팅 유형: {chat_type}")
        print(f"🆔 Chat ID: {chat_id}")
        print("="*60)
        
        print("\n📋 config.py에 추가할 내용:")
        print("```python")
        print("TELEGRAM_CONFIG = {")
        print(f'    "bot_token": "{BOT_TOKEN}",')
        print(f'    "chat_id": "{chat_id}",')
        print("}")
        print("```")
        
        # 즉시 테스트 메시지 전송
        test_message = f"✅ Chat ID 확인 완료!\n\n🆔 Chat ID: {chat_id}\n\n이제 주식 리포트를 받을 수 있습니다! 🚀"
        
        send_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        test_response = requests.post(send_url, json={
            "chat_id": chat_id,
            "text": test_message
        })
        
        if test_response.json().get("ok"):
            print("\n🎉 테스트 메시지 전송 성공!")
            print("Telegram에서 봇의 응답을 확인하세요.")
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {str(e)}")

if __name__ == "__main__":
    get_chat_id()
