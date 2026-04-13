from telethon import TelegramClient

async def ensure_authorized(client: TelegramClient, phone: str) -> None:
    await client.connect()

    if await client.is_user_authorized():
        return

    await client.send_code_request(phone)
    code = input("Enter Telegram code: ").strip()
    await client.sign_in(phone=phone, code=code)