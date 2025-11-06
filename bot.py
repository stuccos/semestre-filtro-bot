import asyncio
import csv
import os
import uuid
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv

# === CONFIGURAZIONE ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN mancante! Controlla il file .env")

CSV_PATH = "testimonianze.csv"

CONSENSO, ATENEO, ANNO, ESITO, TESTO, EMAIL_O_SCELTA, EMAIL = range(7)

INTRO = (
    "<b>Raccolta testimonianze – Semestre filtro a Medicina</b>\n\n"
    "Questo bot raccoglie in forma anonima (email facoltativa) esperienze sul semestre filtro "
    "nei corsi di area medica in Italia."
)
SCELTA_CONSENSO = [["Accetto"], ["Non accetto"]]
SCELTA_ESITO = [["Superato"], ["Non superato"], ["Non sostenuto / ritirato"]]
SCELTA_EMAIL = [["Lascia email"], ["Salta"]]

def ensure_csv():
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                ["id", "timestamp", "user_id", "username", "ateneo", "anno", "esito", "testo", "email"]
            )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(INTRO, parse_mode=ParseMode.HTML)
    await update.message.reply_text(
        "Acconsenti al trattamento dei dati?",
        reply_markup=ReplyKeyboardMarkup(SCELTA_CONSENSO, one_time_keyboard=True, resize_keyboard=True),
    )
    return CONSENSO

async def consenso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text != "accetto":
        await update.message.reply_text("Capito. Se cambi idea, digita /start per ricominciare.")
        return ConversationHandler.END
    await update.message.reply_text("Indica il tuo Ateneo (es. UniMi).", reply_markup=ReplyKeyboardRemove())
    return ATENEO

async def ateneo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ateneo"] = update.message.text.strip()
    await update.message.reply_text("In che anno di corso ti trovi?")
    return ANNO

async def anno(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["anno"] = update.message.text.strip()
    await update.message.reply_text(
        "Esito del semestre filtro?",
        reply_markup=ReplyKeyboardMarkup(SCELTA_ESITO, one_time_keyboard=True, resize_keyboard=True),
    )
    return ESITO

async def esito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["esito"] = update.message.text.strip()
    await update.message.reply_text("Racconta la tua esperienza:", reply_markup=ReplyKeyboardRemove())
    return TESTO

async def testo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["testo"] = update.message.text.strip()
    await update.message.reply_text(
        "Vuoi lasciare un'email facoltativa?",
        reply_markup=ReplyKeyboardMarkup(SCELTA_EMAIL, one_time_keyboard=True, resize_keyboard=True),
    )
    return EMAIL_O_SCELTA

async def email_o_scelta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.lower()
    if "lascia" in t:
        await update.message.reply_text("Scrivi la tua email (oppure digita /salta).")
        return EMAIL
    context.user_data["email"] = ""
    return await salva(update, context)

async def email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.startswith("/salta"):
        context.user_data["email"] = ""
    else:
        context.user_data["email"] = update.message.text.strip()
    return await salva(update, context)

async def salva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_csv()
    rid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    user = update.effective_user
    row = [
        rid,
        now,
        user.id if user else "",
        user.username if user else "",
        context.user_data.get("ateneo", ""),
        context.user_data.get("anno", ""),
        context.user_data.get("esito", ""),
        context.user_data.get("testo", ""),
        context.user_data.get("email", ""),
    ]
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)
    await update.message.reply_text(f"Grazie! Testimonianza salvata (ID: {rid})")
    context.user_data.clear()
    return ConversationHandler.END

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Conversazione terminata.")
    return ConversationHandler.END

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CONSENSO: [MessageHandler(filters.TEXT & ~filters.COMMAND, consenso)],
            ATENEO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ateneo)],
            ANNO: [MessageHandler(filters.TEXT & ~filters.COMMAND, anno)],
            ESITO: [MessageHandler(filters.TEXT & ~filters.COMMAND, esito)],
            TESTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, testo)],
            EMAIL_O_SCELTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, email_o_scelta)],
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, email)],
        },
        fallbacks=[CommandHandler("stop", stop)],
    )
    app.add_handler(conv)
    print("Bot in ascolto…")
    app.run_polling()

if __name__ == "__main__":
    main()
