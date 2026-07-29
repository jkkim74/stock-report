# get_chat_id.py
# Telegram Chat ID 확인용 일회성 도구.
# 토큰은 .env(TELEGRAM_BOT_TOKEN)에서 읽는다 - 소스에 하드코딩하지 말 것.
import requests

from config import TELEGRAM_CONFIG

BOT_TOKEN = TELEGRAM_CONFIG["bot_token"]


def get_chat_id():
    print("=" * 60)
    print("📱 Telegram Chat ID 추출 도구")
    print("=" * 60)

    if not BOT_TOKEN:
        print("\n❌ TELEGRAM_BOT_TOKEN이 설정되지 않았습니다. .env를 확인하세요.")
        return

    print("\n📌 다음 단계를 먼저 완료하세요:")
    print("   1. Telegram에서 본인의 봇 검색")
    print("   2. 봇과 대화 시작 (/start)")
    print("   3. 아무 메시지 전송 (예: 'hello')")
    print("   ※ 그룹 Chat ID가 필요하면 그룹에 봇을 초대한 뒤 그룹에서 메시지를 보내세요.")
    print("\n" + "=" * 60)

    input("\n메시지를 보냈다면 Enter를 눌러주세요...")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

    try:
        response = requests.get(url, timeout=30)
        data = response.json()

        if not data.get("ok"):
            print(f"\n❌ API 오류: {data.get('description', data)}")
            return

        results = data.get("result", [])
        if not results:
            print("\n⚠️ 아직 메시지가 없습니다. 봇에게 메시지를 보낸 후 다시 실행하세요.")
            return

        # 수신된 모든 대화를 중복 없이 출력 (개인/그룹 모두)
        seen = {}
        for item in results:
            message = item.get("message") or item.get("channel_post")
            if not message:
                continue
            chat = message.get("chat", {})
            if chat.get("id") is not None:
                seen[chat["id"]] = chat

        if not seen:
            print("\n⚠️ 메시지에서 chat 정보를 찾지 못했습니다.")
            return

        print(f"\n✅ Chat {len(seen)}개를 찾았습니다.\n")
        for chat_id, chat in seen.items():
            name = chat.get("title") or chat.get("first_name") or "Unknown"
            print("=" * 60)
            print(f"👤 이름     : {name}")
            print(f"📱 채팅 유형: {chat.get('type')}")
            print(f"🆔 Chat ID  : {chat_id}")
        print("=" * 60)

        print("\n📋 .env에 넣을 값:")
        print(f"TELEGRAM_CHAT_ID={list(seen)[-1]}")

    except Exception as e:
        print(f"\n❌ 오류 발생: {str(e)}")


if __name__ == "__main__":
    get_chat_id()
