import re
import pprint
from telethon import TelegramClient, events
from parser.signal_parser import parse_signal_message

async def listen_selected_topics(
        client: TelegramClient,
        chat_id: int,
        topic_ids: list[int],
) -> None:
    topic_ids = set(topic_ids)

    @client.on(events.NewMessage(chats=chat_id))
    async def handler(event):
        message = event.message
        text = message.text or ""

        asset = re.search(r"\$([A-Z0-9]+)", text)

        if not text.strip():
            print("STOP: empty text")
            return

        reply_to = getattr(message, "reply_to", None)

        if reply_to:
            reply_to_msg_id = getattr(reply_to, 'reply_to_msg_id', None)
        else:
            reply_to_msg_id = None

        if asset is not None or reply_to_msg_id in topic_ids:
            result = parse_signal_message(text)
            print(result)

    print("Listening selected topics...")
    await client.run_until_disconnected()