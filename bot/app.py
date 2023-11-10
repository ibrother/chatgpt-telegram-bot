#!/usr/bin/env python3
"""
@Time: 2/25/2023 5:46 PM
@Author: cloud
@File: app.py
@Project: chatgpt-telegram-bot
@Ide: PyCharm
"""
import logging
import os
from collections import defaultdict, deque

from openai import AsyncOpenAI
import tiktoken
from telegram import Update
from telegram.ext import filters, MessageHandler, ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

client = AsyncOpenAI(base_url=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"))
MODEL = os.getenv("MODEL", "gpt-3.5-turbo")

# Define a dictionary to store messages for each user
user_conversation = defaultdict(lambda: {'messages': deque(), 'tokens': 0})

# Define the tokens limit
MAX_TOKENS_PER_MESSAGE = int(os.getenv("MAX_TOKENS", 4096))

# Define your bot
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
WEBHOOK_ADDR = os.getenv("WEBHOOK_ADDR", "0.0.0.0")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Define the authorized user IDs and group chat IDs
authorized_user_ids = [int(x) for x in os.getenv("USER_IDS").split(",")]
authorized_group_ids = [int(x) for x in os.getenv("GROUP_IDS").split(",")]


def num_tokens_from_messages(messages, model=MODEL):
    """Return the number of tokens used by a list of messages."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        print("Warning: model not found. Using cl100k_base encoding.")
        encoding = tiktoken.get_encoding("cl100k_base")
    if model in {
        "gpt-3.5-turbo-0613",
        "gpt-3.5-turbo-16k-0613",
        "gpt-4-0314",
        "gpt-4-32k-0314",
        "gpt-4-0613",
        "gpt-4-32k-0613",
        "gpt-4-1106-preview",
        }:
        tokens_per_message = 3
        tokens_per_name = 1
    elif model == "gpt-3.5-turbo-0301":
        tokens_per_message = 4  # every message follows <|start|>{role/name}\n{content}<|end|>\n
        tokens_per_name = -1  # if there's a name, the role is omitted
    elif "gpt-3.5-turbo" in model:
        print("Warning: gpt-3.5-turbo may update over time. Returning num tokens assuming gpt-3.5-turbo-0613.")
        return num_tokens_from_messages(messages, model="gpt-3.5-turbo-0613")
    elif "gpt-4" in model:
        print("Warning: gpt-4 may update over time. Returning num tokens assuming gpt-4-0613.")
        return num_tokens_from_messages(messages, model="gpt-4-0613")
    else:
        raise NotImplementedError(
            f"""num_tokens_from_messages() is not implemented for model {model}. See https://github.com/openai/openai-python/blob/main/chatml.md for information on how messages are converted to tokens."""
        )
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            num_tokens += len(encoding.encode(value))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
    return num_tokens


# Define the handler for the /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello, I'm your bot!")


# Define the async function to call the ChatGPT API
async def call_openai_chatgpt(message):
    resp = await client.chat.completions.create(
        model=MODEL,
        messages=message
    )
    return resp


# Define the handler for incoming messages
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if the message is sent in a private chat or in a group chat with the bot
    chat_id = update.message.chat.id
    if (update.message.chat.type == 'private' and chat_id in authorized_user_ids) or (
            update.message.chat.type == 'supergroup' and chat_id in authorized_group_ids and '@{}'.format(
            context.bot.username) in update.message.text):
        # Get the user ID
        user_id = update.message.from_user.id

        new_message = {"role": "user", "content": update.message.text}
        new_message_tokens = num_tokens_from_messages([new_message])

        if new_message_tokens > MAX_TOKENS_PER_MESSAGE:
            reply_content = "Sorry, your message is too long to process!"
        else:
            conversation_data = user_conversation[user_id]
            conversation_data['messages'].append(new_message)
            conversation_data['tokens'] += new_message_tokens

            # 如果超出tokens限制，则移除旧消息直至满足限制
            while conversation_data['tokens'] > MAX_TOKENS_PER_MESSAGE:
                # 移除最旧的消息，并更新tokens计数
                oldest_message = conversation_data['messages'].popleft()
                oldest_message_tokens = num_tokens_from_messages([oldest_message])
                conversation_data['tokens'] -= oldest_message_tokens

            # Call the API endpoint and send the response back to the user
            api_response = await call_openai_chatgpt(list(conversation_data['messages']))
            reply_message = api_response.choices[0].message
            reply_content = reply_message.content

            # Append the response to the user's list
            conversation_data['messages'].append(reply_message)
            conversation_data['tokens'] += api_response.usage.completion_tokens

        await context.bot.send_message(chat_id=chat_id, text=reply_content,
                                       reply_to_message_id=update.message.message_id)


# Create the Telegram bot and add the handlers
if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    start_handler = CommandHandler('start', start)
    msg_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler)
    application.add_handler(start_handler)
    application.add_handler(msg_handler)

    if WEBHOOK_URL:
        application.run_webhook(listen=WEBHOOK_ADDR, port=80, url_path=WEBHOOK_PATH, webhook_url=WEBHOOK_URL,
                                secret_token=SECRET_TOKEN)
    else:
        application.run_polling()
