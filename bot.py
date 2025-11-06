import os
import csv
import uuid
import smtplib
from datetime import datetime, timezone
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# telegram
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

# env
from dotenv import load_dotenv
load_dotenv()

# === CONFIGURAZIONE BASE ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN mancante! Controlla il file .env o le Railway Variables.")

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = os.getenv("CSV_PATH", str(BASE_DIR / "testimonianze.csv"))

# --- Configurazione email (Gmail, ecc.)
EMAIL_HOST = os.getenv("EMAIL_HOST")      # es: smtp.gmail.com
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER")      # la tua Gmail
EMAIL_PASS = os.getenv("EMAIL_PASS")      # password per app
EMAIL_TO   = os.getenv("EMAIL_TO")        # destinatario (anche uguale a EMAIL_USER)

# --- Database opzionale (solo se vuoi salvare su Postgres)
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()   # <— strip!
USE_DB = bool(DATABASE_URL)


if USE_DB:
    import psycopg  # psycopg v3 (funziona su Python 3.13)

    def db_conn():
        return psycopg.connect(DATABASE_URL)

    def ensure_schema():
    if not USE_DB:
        return
    try:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS testimonianze (
                    id UUID PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    user_id BIGINT,
                    username TEXT,
                    ateneo  TEXT,
                    anno    TEXT,
                    esito   TEXT,
                    testo   TEXT,
                    email   TEXT
                );
            """)
    except Exception as e:
        print(f"[DB] ensure_schema fallita: {e}")

else:
    def ensure_schema():
        pass


# === Conversazione ===
CONSENSO, ATENEO, ANNO, ESITO, TESTO, EMAIL_O_SCELTA, EMAIL = range(7)

INTRO = (
    "<b>Raccolta testimonianze – Semestre filtro a Medicina</b>\n\n"
    "Questo bot raccoglie in forma anonima (email facoltativa) esperienze sul semestre filtro "
    "nei corsi di area medica in Italia."
)
SCELTA_CONSENSO = [["Accetto"], ["Non accetto"]]
SCELTA_ESITO = [["Superato"], ["Non superato"], ["Non sostenuto / ritirato"]]
SCELTA_EMAIL = [["Lascia email"], ["Salta"]]


# === Utility CSV ===
def ensure_csv(path: str):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                ["id", "timestamp", "user_id", "username", "ateneo", "anno", "esito", "testo", "email"]
            )

def append_csv(path: str, row: list):
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


# === Utility email ===
def send_email(subject: str, body: str):
    if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASS, EMAIL_TO]):
        print("⚠️ Email non inviata: variabili EMAIL_* mancanti.")
        return

    msg = MIMEMultipart()
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        print(f"📧 Email inviata a {EMAIL_TO}")
    except Exception as e:
        print(f"Errore invio email: {e}")


# === Gestione conversazione ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(INTRO, parse_mode=ParseMode.HTML)
    await update.message.reply_text(
        "Acconsenti al trattamento dei dati?",
        reply_markup=ReplyKeyboardMarkup(SCELTA_CONSENSO, one_time_keyboard=True, resize_keyboard=True),
    )
    return CONSENSO

async def consenso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip().lower()
    if text != "accetto":
        await update.message.reply_text("Capito. Se cambi idea, digita /start per ricominciare.")
        return ConversationHandler.END
    await update.message.reply_text("Indica il tuo Ateneo (es. UniMi).", reply_markup=ReplyKeyboardRemove())
    return ATENEO

async def ateneo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ateneo"] = (update.message.text or "").strip()
    await update.message.reply_text("In che anno di corso ti trovi?")
    return ANNO

async def anno(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["anno"] = (update.message.text or "").strip()
    await update.message.reply_text(
        "Esito del semestre filtro?",
        reply_markup=ReplyKeyboardMarkup(SCELTA_ESITO, one_time_keyboard=True, resize_keyboard=True),
    )
    return ESITO

async def esito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["esito"] = (update.message.text or "").strip()
    await update.message.reply_text("Racconta la tua esperienza:", reply_markup=ReplyKeyboardRemove())
    return TESTO

async def testo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["testo"] = (update.message.text or "").strip()
    await update.message.reply_text(
        "Vuoi lasciare un'email facoltativa?",
        reply_markup=ReplyKeyboardMarkup(SCELTA_EMAIL, one_time_keyboard=True, resize_keyboard=True),
    )
    return EMAIL_O_SCELTA

async def email_o_scelta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").lower()
    if "lascia" in t:
        await update.message.reply_text("Scrivi la tua email (oppure digita /salta).")
        return EMAIL
    context.user_data["email"] = ""
    return await salva(update, context)

async def email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text or ""
    if txt.startswith("/salta"):
        context.user_data["email"] = ""
    else:
        context.user_data["email"] = txt.strip()
    return await salva(update, context)

async def salva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    user = update.effective_user

    ateneo = context.user_data.get("ateneo", "")
    anno   = context.user_data.get("anno", "")
    esito  = context.user_data.get("esito", "")
    testo  = context.user_data.get("testo", "")
    email_ = context.user_data.get("email", "")

    # --- salva su DB o CSV
    if USE_DB:
        ensure_schema()
        try:
            with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO testimonianze
                    (id, user_id, username, ateneo, anno, esito, testo, email)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """, (rid, user.id if user else None, user.username if user else None,
                      ateneo, anno, esito, testo, email_))
            print(f"[DB] Inserita {rid}")
        except Exception as e:
            print(f"[DB] Errore insert: {e}")
            ensure_csv(CSV_PATH)
            append_csv(CSV_PATH, [rid, now, user.id if user else "", user.username if user else "",
                                  ateneo, anno, esito, testo, email_])
            print(f"[CSV fallback] Salvata {rid} su {CSV_PATH}")
    else:
        ensure_csv(CSV_PATH)
        append_csv(CSV_PATH, [rid, now, user.id if user else "", user.username if user else "",
                              ateneo, anno, esito, testo, email_])
        print(f"[CSV] Salvata {rid} su {CSV_PATH}")

    # --- invia email
    body = (
        f"Nuova testimonianza ricevuta:\n\n"
        f"ID: {rid}\n"
        f"Data (UTC): {now}\n"
        f"Utente: {user.id if user else ''} @{user.username if user else ''}\n"
        f"Ateneo: {ateneo}\n"
        f"Anno: {anno}\n"
        f"Esito: {esito}\n"
        f"Email lasciata: {email_ or '—'}\n\n"
        f"Testo:\n{testo}\n"
    )
    send_email("📩 Nuova testimonianza – Semestre filtro", body)

    await update.message.reply_text(f"Grazie! Testimonianza salvata (ID: {rid})")
    context.user_data.clear()
    return ConversationHandler.END

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Conversazione terminata.")
    return ConversationHandler.END


def main():
    ensure_schema()
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
    print(f"Bot in ascolto… (DB={'ON' if USE_DB else 'OFF'}) CSV_PATH={CSV_PATH}")
    app.run_polling()


if __name__ == "__main__":
    main()
