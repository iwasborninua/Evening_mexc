import re
import pprint
from telethon import TelegramClient, events
from parser.signal_parser import parse_signal_message


async def listen_selected_topics(
        client: TelegramClient,
        chat_id: int,
        topic_ids: list[int],
        logger,
) -> None:
    topic_ids = set(topic_ids)

    @client.on(events.NewMessage(chats=chat_id))
    async def handler(event):
        try:
            message = event.message
            text = message.text or ""
            message_id = getattr(message, "id", None)

            asset = re.search(r"\$([A-Z0-9]+)", text)

            if not text.strip():
                print("STOP: empty text")
                logger.info("STOP: empty text | message_id=%s", message_id)
                return

            reply_to = getattr(message, "reply_to", None)

            if reply_to:
                reply_to_msg_id = getattr(reply_to, "reply_to_msg_id", None)
            else:
                reply_to_msg_id = None

            print(
                f"New message | message_id={message_id} | "
                f"reply_to_msg_id={reply_to_msg_id} | text={text}"
            )
            logger.info(
                "New message | message_id=%s | reply_to_msg_id=%s | text=%s",
                message_id,
                reply_to_msg_id,
                text.replace("\n", " ")[:500],
            )

            if asset is not None or reply_to_msg_id in topic_ids:
                result = parse_signal_message(text)

                print("Parsed result:")
                pprint.pprint(result)

                logger.info(
                    "Parsed message | message_id=%s | result=%s",
                    message_id,
                    result,
                )
            else:
                print("SKIP: not target topic and no asset")
                logger.info(
                    "Message skipped | message_id=%s | reason=not_target_topic_or_no_asset",
                    message_id,
                )

        except Exception:
            print("ERROR: exception while processing message")
            logger.exception("Error while processing Telegram message")

    print("Listening selected topics...")
    logger.info("Listening selected topics...")
    await client.run_until_disconnected()