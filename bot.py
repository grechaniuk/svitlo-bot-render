import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import openai

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

openai.api_key = OPENAI_API_KEY

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я готов работать.")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    completion = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content": user_text}]
    )

    answer = completion["choices"][0]["message"]["content"]
    await update.message.reply_text(answer)

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    app.run_polling()

if __name__ == "__main__":
    main()
