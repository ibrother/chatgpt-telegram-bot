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
from collections import defaultdict

import openai
import tiktoken
from telegram import Update
from telegram.ext import filters, MessageHandler, ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

openai.api_key = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("MODEL", "gpt-3.5-turbo-0301")

# Define a dictionary to store messages for each user
user_conversation = defaultdict(list)

# Define the tokens limit
MAX_TOKENS_PER_MESSAGE = 4096

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
    """Returns the number of tokens used by a list of messages."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    if model == "gpt-3.5-turbo-0301":  # note: future models may deviate from this
        num_tokens = 0
        for message in messages:
            num_tokens += 4  # every message follows <im_start>{role/name}\n{content}<im_end>\n
            for key, value in message.items():
                num_tokens += len(encoding.encode(value))
                if key == "name":  # if there's a name, the role is omitted
                    num_tokens += -1  # role is always required and always 1 token
        num_tokens += 2  # every reply is primed with <im_start>assistant
        return num_tokens
    else:
        raise NotImplementedError(f"""num_tokens_from_messages() is not presently implemented for model {model}.""")


# Define the handler for the /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello, I'm your bot!")


# Define the async function to call the ChatGPT API
async def call_openai_chatgpt(message):
    resp = await openai.ChatCompletion.acreate(
        model=MODEL,
        messages=message
    )
    return resp['choices'][0]['message']


# Define the handler for incoming messages
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if the message is sent in a private chat or in a group chat with the bot
    chat_id = update.message.chat.id
    if (update.message.chat.type == 'private' and chat_id in authorized_user_ids) or (
            update.message.chat.type == 'supergroup' and chat_id in authorized_group_ids and '@{}'.format(
            context.bot.username) in update.message.text):
        # Get the user ID
        user_id = update.message.from_user.id

        new_message = [{"role": "user", "content": update.message.text}]

        if num_tokens_from_messages(new_message) > MAX_TOKENS_PER_MESSAGE:
            reply_message = "Sorry, your message is too long to process!"
        else:
            # Append the message to the user's list
            user_conversation[user_id].append(new_message[0])

            # Check if the total number of tokens in the conversation exceeds the limit
            while num_tokens_from_messages(user_conversation[user_id]) > MAX_TOKENS_PER_MESSAGE:
                # Remove the first two elements from the list
                if len(user_conversation[user_id]) >= 2:
                    user_conversation[user_id] = user_conversation[user_id][2:]

            # Call the API endpoint and send the response back to the user
            api_response = await call_openai_chatgpt(user_conversation[user_id])
            reply_message = api_response['content']

            # Append the response to the user's list
            user_conversation[user_id].append(api_response)

        await context.bot.send_message(chat_id=chat_id, text=reply_message,
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
