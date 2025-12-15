import requests

BOT_TOKEN = "8501237845:AAHAKqCqTPODqpS1NSMcIaUD_Mg3CuAUK9c"  # 새로 발급받은 토큰 사용

def get_group_chat_id():
    print("="*60)
    print("📋 그룹 Chat ID 확인 도구")
    print("="*60)
    print("\n✅ 먼저 다음을 완료하세요:")
    print("   1. 그룹에 봇을 추가")
    print("   2. 그룹에서 /start 또는 아무 메시지 전송")
    print("\n" + "="*60)
    
    input("\n위 단계를 완료했다면 Enter를 눌러주세요...")
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if not data.get("ok"):
            print(f"\n❌ API 오류: {data}")
            return
        
        groups_found = []
        
        for update in data.get("result", []):
            if "message" in update:
                chat = update["message"]["chat"]
                
                # 그룹 타입만 필터링
                if chat["type"] in ["group", "supergroup"]:
                    groups_found.append({
                        "id": chat["id"],
                        "title": chat.get("title", "Unknown"),
                        "type": chat["type"]
                    })
        
        if groups_found:
            print(f"\n✅ {len(groups_found)}개의 그룹을 찾았습니다!\n")
            
            for i, group in enumerate(groups_found, 1):
                print(f"[{i}] 그룹명: {group['title']}")
                print(f"    Chat ID: {group['id']}")
                print(f"    타입: {group['type']}")
                print("-" * 50)
            
            # 가장 최근 그룹 추천
            recommended = groups_found[-1]
            print(f"\n📋 config.py에 추가할 내용:")
            print("```python")
            print("TELEGRAM_CONFIG = {")
            print(f'    "bot_token": "{BOT_TOKEN}",')
            print(f'    "chat_id": "{recommended["id"]}",  # 그룹: {recommended["title"]}')
            print('    "send_preview": True,')
            print('    "send_as_file": True')
            print("}")
            print("```")
            
            return recommended["id"]
        else:
            print("\n⚠️ 그룹을 찾을 수 없습니다.")
            print("봇을 그룹에 추가하고 메시지를 보낸 후 다시 실행하세요.")
            
    except Exception as e:
        print(f"\n❌ 오류 발생: {str(e)}")

if __name__ == "__main__":
    get_group_chat_id()
