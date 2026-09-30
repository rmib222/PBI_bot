import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from bot_engine import QueryEngine

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
logging.basicConfig(level=logging.INFO)

engine = QueryEngine()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hola! Soy el bot de AdventureWorks Sales.\n\n" + engine.help_text()
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(engine.help_text())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = update.message.text
    try:
        answer = engine.answer(question)
        await update.message.reply_text(answer)
    except ValueError:
        await update.message.reply_text(
            "❓ No reconocí esa pregunta.\n\n" + engine.help_text()
        )

def main():
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN no configurado en .env")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot iniciado. Ctrl+C para detener.")
    app.run_polling()

if __name__ == "__main__":
    main()
