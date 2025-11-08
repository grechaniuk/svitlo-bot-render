# bot.py
# Svitlo AI — Telegram MVP (one-file)
# NOT medical/diagnostic service. Crisis-safe fallback.

import os
import re
import sqlite3
from datetime import datetime, timedelta

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, Application, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler, ContextTypes, filters
)

# ---------- ENV ----------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
DEFAULT_LANG = os.getenv("DEFAULT_LANG", "en").strip().lower()
DEFAULT_COUNTRY = os.getenv("DEFAULT_COUNTRY", "US").strip().upper()

if not BOT_TOKEN:
    raise SystemExit("ERROR: TELEGRAM_BOT_TOKEN is not set.")

# ---------- I18N (встроено) ----------
TEXT = {
    "en": {
        "start": "Hi! I'm *Svitlo AI* — mental health training (not a medical service).\n"
                 "Commands: /daily /breath /ground /sleep /plan /triggers /report /settings",
        "choose_lang": "Choose language / Оберіть мову",
        "saved": "Saved ✅",
        "unknown": "Try /daily or /breath.",
        "checkin_intro": "Daily check-in. What’s your stress (0–10) now?",
        "checkin_stress_saved": "OK. Stress {val}/10. Any triggers today? (write or 'no')",
        "checkin_triggers_saved": "Noted. How many hours did you sleep last night? (e.g., 6.5)",
        "checkin_sleep_saved": "Thanks. One micro-goal for today?",
        "checkin_done": "Saved. You can try /ground or /breath.",
        "breath_intro": "Box breathing ~2 min. Type *go* when ready.",
        "breath_go": "Inhale 4 — Hold 4 — Exhale 4 — Hold 4. Repeat for ~2 minutes.",
        "ground_intro": "Grounding 5-4-3-2-1. I’ll guide you.",
        "ground_step": "Tell me {count}: {hint}",
        "sleep_tips": "Sleep tips: consistent schedule, dark & cool room, no screens 60m before bed, "
                      "reduce caffeine after noon, short daylight walk.",
        "plan_intro": "Up to 3 micro-goals. Send each as a separate message. Type *done* to save.",
        "plan_saved": "Plan saved.",
        "triggers_intro": "Send triggers to log. Type *done* to finish.",
        "report_intro": "Report period? Reply *7* or *30*.",
        "report_ready": "Report {days}d: avg stress {avg:.1f}, check-ins {n}, avg sleep {sleep:.1f}h, top: {trg}",
        "settings": "Settings. Lang={lang}, Country={country}. Send `lang en/uk` or `country US/UA`.",
        "crisis": "If you’re thinking about self-harm: US 988/911, UA 7333/112. I can’t help here.",
        "ok": "OK.",
    },
    "uk": {
        "start": "Привіт! Я *Svitlo AI* — тренування психстійкості (не медична служба).\n"
                 "Команди: /daily /breath /ground /sleep /plan /triggers /report /settings",
        "choose_lang": "Choose language / Оберіть мову",
        "saved": "Збережено ✅",
        "unknown": "Спробуй /daily або /breath.",
        "checkin_intro": "Щоденний чек-ін. Який зараз рівень стресу (0–10)?",
        "checkin_stress_saved": "Ок. Стрес {val}/10. Були сьогодні тригери? (напиши або 'ні')",
        "checkin_triggers_saved": "Занотував. Скільки годин спав(-ла) вночі? (напр., 6.5)",
        "checkin_sleep_saved": "Дякую. Одна мікроціль на сьогодні?",
        "checkin_done": "Збережено. Можеш спробувати /ground або /breath.",
        "breath_intro": "Дихання «коробка» ~2 хв. Напиши *go*, коли готовий(-а).",
        "breath_go": "Вдих 4 — Пауза 4 — Видих 4 — Пауза 4. Повторюй ~2 хв.",
        "ground_intro": "Ґраундинг 5-4-3-2-1. Я підкажу.",
        "ground_step": "Назви {count}: {hint}",
        "sleep_tips": "Поради для сну: стабільний графік, темна й прохолодна кімната, без екранів 60 хв до сну, "
                      "менше кофеїну після обіду, коротка денна прогулянка.",
        "plan_intro": "До 3 мікроцілей. Надсилай кожну окремо. Напиши *done*, щоб зберегти.",
        "plan_saved": "План збережено.",
        "triggers_intro": "Надсилай тригери для журналу. Напиши *done*, щоб завершити.",
        "report_intro": "Період звіту? Відповідай *7* або *30*.",
        "report_ready": "Звіт {days} дн: сер. стрес {avg:.1f}, чек-іни {n}, сер. сон {sleep:.1f} год, топ: {trg}",
        "settings": "Налаштування. Мова={lang}, Країна={country}. Надішли `lang en/uk` або `country US/UA`.",
        "crisis": "Якщо думаєш про самопошкодження: US 988/911, UA 7333/112. Я не можу допомогти тут.",
        "ok": "Ок.",
    }
}

def T(lang: str, key: str) -> str:
    return TEXT.get(lang, TEXT["en"]).get(key, key)

# ---------- DB (sqlite, один файл) ----------
DB_PATH = os.path.join(os.path.dirname(__file__), "svitlo.sqlite3")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY,
  lang TEXT,
  country TEXT,
  created_at TEXT
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS checkins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  ts TEXT,
  stress REAL,
  triggers TEXT,
  sleep_hours REAL,
  micro_goal TEXT
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS triggers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  ts TEXT,
  note TEXT
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  ts TEXT,
  item TEXT
)""")
conn.commit()

def get_user(u_id: int):
    row = cur.execute("SELECT user_id, lang, country FROM users WHERE user_id=?", (u_id,)).fetchone()
    if row:
        return {"user_id": row[0], "lang": row[1], "country": row[2]}
    cur.execute("INSERT INTO users (user_id, lang, country, created_at) VALUES (?,?,?,?)",
                (u_id, DEFAULT_LANG, DEFAULT_COUNTRY, datetime.utcnow().isoformat()))
    conn.commit()
    return {"user_id": u_id, "lang": DEFAULT_LANG, "country": DEFAULT_COUNTRY}

def set_lang(u_id: int, lang: str):
    cur.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, u_id)); conn.commit()

def set_country(u_id: int, country: str):
    cur.execute("UPDATE users SET country=? WHERE user_id=?", (country, u_id)); conn.commit()

def save_checkin(u_id: int, stress, triggers, sleep_hours, micro_goal):
    cur.execute("INSERT INTO checkins (user_id, ts, stress, triggers, sleep_hours, micro_goal) "
                "VALUES (?,?,?,?,?,?)",
                (u_id, datetime.utcnow().isoformat(), stress, triggers, sleep_hours, micro_goal))
    conn.commit()

def save_trigger(u_id: int, note: str):
    cur.execute("INSERT INTO triggers (user_id, ts, note) VALUES (?,?,?)",
                (u_id, datetime.utcnow().isoformat(), note))
    conn.commit()

def save_plan(u_id: int, item: str):
    cur.execute("INSERT INTO plans (user_id, ts, item) VALUES (?,?,?)",
                (u_id, datetime.utcnow().isoformat(), item))
    conn.commit()

def aggregate(u_id: int, days: int):
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = cur.execute("SELECT stress, sleep_hours, triggers FROM checkins WHERE user_id=? AND ts>=?",
                       (u_id, since)).fetchall()
    if not rows:
        return None
    stresses = [r[0] for r in rows if r[0] is not None]
    sleeps = [r[1] for r in rows if r[1] is not None]
    all_tr = " ".join([(r[2] or "") for r in rows])
    words = re.findall(r"[A-Za-zА-Яа-яЇїІіЄєҐґ']{3,}", all_tr.lower())
    from collections import Counter
    top = ", ".join([w for w, _ in Counter(words).most_common(5)]) or "—"
    return {
        "avg": (sum(stresses) / len(stresses)) if stresses else 0.0,
        "sleep": (sum(sleeps) / len(sleeps)) if sleeps else 0.0,
        "n": len(rows),
        "top": top
    }

# ---------- CRISIS FILTER ----------
SUICIDE = re.compile(
    r"\b(kill myself|suicide|end it|self[- ]?harm|cut myself|want to die|не хочу жити|суїцид|покінчити|зарізатись|"
    r"вкоротити|самопошкодження)\b", re.I)

# ---------- STATES ----------
DAILY_STRESS, DAILY_TRIGGERS, DAILY_SLEEP, DAILY_GOAL = range(4)
BREATH_GO, GROUND_GO, PLAN_GO, TRIG_GO = range(4)  # dummy placeholders for convs

# ---------- HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("EN", callback_data="lang_en"),
          InlineKeyboardButton("UK", callback_data="lang_uk")]]
    )
    await update.message.reply_text(T(u["lang"], "start"), parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text(T(u["lang"], "choose_lang"), reply_markup=kb)

async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    u = get_user(update.effective_user.id)
    if data.startswith("lang_"):
        lang = data.split("_", 1)[1]
        if lang in ("en", "uk"):
            set_lang(u["user_id"], lang)
            await q.answer("OK")
            await q.edit_message_text(T(lang, "saved") + f" Language={lang.upper()}")
            return
    await q.answer("OK")

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    await update.message.reply_text(
        T(u["lang"], "settings").format(lang=u["lang"], country=u["country"]),
        parse_mode=ParseMode.MARKDOWN
    )

async def wildcard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    txt = update.message.text.strip().lower()
    if txt.startswith("lang "):
        lang = txt.split()[-1]
        if lang in ("en", "uk"):
            set_lang(u["user_id"], lang)
            await update.message.reply_text(T(lang, "saved"))
    elif txt.startswith("country "):
        c = txt.split()[-1].upper()
        if c in ("US", "UA"):
            set_country(u["user_id"], c)
            await update.message.reply_text(T(u["lang"], "saved"))

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if SUICIDE.search(update.message.text or ""):
        u = get_user(update.effective_user.id)
        await update.message.reply_text(T(u["lang"], "crisis"))
        return ConversationHandler.END
    u = get_user(update.effective_user.id)
    await update.message.reply_text(T(u["lang"], "checkin_intro"))
    return DAILY_STRESS

async def daily_stress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.replace(",", "."))
        val = max(0.0, min(10.0, val))
        context.user_data["s"] = val
    except Exception:
        await update.message.reply_text("0–10")
        return DAILY_STRESS
    u = get_user(update.effective_user.id)
    await update.message.reply_text(T(u["lang"], "checkin_stress_saved").format(val=context.user_data["s"]))
    return DAILY_TRIGGERS

async def daily_triggers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tr"] = update.message.text.strip()
    u = get_user(update.effective_user.id)
    await update.message.reply_text(T(u["lang"], "checkin_triggers_saved"))
    return DAILY_SLEEP

async def daily_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["sl"] = float(update.message.text.replace(",", "."))
    except Exception:
        await update.message.reply_text("e.g., 6.5")
        return DAILY_SLEEP
    u = get_user(update.effective_user.id)
    await update.message.reply_text(T(u["lang"], "checkin_sleep_saved"))
    return DAILY_GOAL

async def daily_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    g = update.message.text.strip()
    u = get_user(update.effective_user.id)
    save_checkin(u["user_id"], context.user_data.get("s"), context.user_data.get("tr", ""),
                 context.user_data.get("sl"), g)
    await update.message.reply_text(T(u["lang"], "checkin_done"))
    return ConversationHandler.END

async def breath(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    await update.message.reply_text(T(u["lang"], "breath_intro"), parse_mode=ParseMode.MARKDOWN)
    return BREATH_GO

async def breath_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip().lower() != "go":
        await update.message.reply_text("Type 'go'")
        return BREATH_GO
    u = get_user(update.effective_user.id)
    await update.message.reply_text(T(u["lang"], "breath_go"))
    return ConversationHandler.END

async def ground(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    context.user_data["g_step"] = 0
    await update.message.reply_text(T(u["lang"], "ground_intro"))
    return GROUND_GO

async def ground_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    steps_en = [
        ("5 things you see", "around you"),
        ("4 things you feel", "touch/textures"),
        ("3 things you hear", "ambient sounds"),
        ("2 things you smell", "even faint"),
        ("1 thing you taste", "or imagine")
    ]
    steps_uk = [
        ("5 що бачиш", "навколо"),
        ("4 що відчуваєш", "дотик/текстури"),
        ("3 що чуєш", "звуки довкола"),
        ("2 запахи", "навіть ледь"),
        ("1 смак", "або уяви")
    ]
    steps = steps_en if u["lang"] == "en" else steps_uk
    idx = context.user_data.get("g_step", 0)
    if idx >= len(steps):
        await update.message.reply_text("Done.")
        return ConversationHandler.END
    c, h = steps[idx]
    await update.message.reply_text(T(u["lang"], "ground_step").format(count=c, hint=h))
    context.user_data["g_step"] = idx + 1
    return GROUND_GO

async def sleep_tips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    await update.message.reply_text(T(u["lang"], "sleep_tips"))

async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    context.user_data["plan"] = []
    await update.message.reply_text(T(u["lang"], "plan_intro"), parse_mode=ParseMode.MARKDOWN)
    return PLAN_GO

async def plan_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt.lower() == "done":
        u = get_user(update.effective_user.id)
        for it in context.user_data.get("plan", [])[:3]:
            save_plan(u["user_id"], it)
        await update.message.reply_text(T(u["lang"], "plan_saved"))
        return ConversationHandler.END
    context.user_data.setdefault("plan", []).append(txt)
    await update.message.reply_text("Added. Type *done* to save.", parse_mode=ParseMode.MARKDOWN)
    return PLAN_GO

async def trig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    await update.message.reply_text(T(u["lang"], "triggers_intro"), parse_mode=ParseMode.MARKDOWN)
    return TRIG_GO

async def trig_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt.lower() == "done":
        u = get_user(update.effective_user.id)
        await update.message.reply_text(T(u["lang"], "saved"))
        return ConversationHandler.END
    u = get_user(update.effective_user.id)
    save_trigger(u["user_id"], txt)
    await update.message.reply_text("Logged.")
    return TRIG_GO

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    await update.message.reply_text(T(u["lang"], "report_intro"))

async def report_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text.strip())
        assert days in (7, 30)
    except Exception:
        await update.message.reply_text("Reply 7 or 30.")
        return
    u = get_user(update.effective_user.id)
    agg = aggregate(u["user_id"], days)
    if not agg:
        await update.message.reply_text("No data yet.")
        return
    await update.message.reply_text(
        T(u["lang"], "report_ready").format(days=days, avg=agg["avg"],
                                            n=agg["n"], sleep=agg["sleep"], trg=agg["top"])
    )

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    u = get_user(update.effective_user.id)
    if SUICIDE.search(text):
        await update.message.reply_text(T(u["lang"], "crisis"))
        return
    if not OPENAI_KEY:
        await update.message.reply_text(T(u["lang"], "unknown"))
        return
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_KEY)
        system = ("You are Svitlo AI, a mental health *training* assistant for veterans. "
                  "Not a medical or crisis service. Avoid diagnosis/medications/politics/religion/graphic content. "
                  "Keep it short and practical. If self-harm is mentioned -> refuse + show helplines.")
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text[:2000]}
            ],
            temperature=0.4,
            max_tokens=300
        )
        await update.message.reply_text(resp.choices[0].message.content.strip())
    except Exception:
        await update.message.reply_text(T(u["lang"], "unknown"))

def build_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(cb))

    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("sleep", sleep_tips))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("daily", daily)],
        states={
            DAILY_STRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_stress)],
            DAILY_TRIGGERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_triggers)],
            DAILY_SLEEP: [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_sleep)],
            DAILY_GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, daily_goal)],
        },
        fallbacks=[]
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("breath", breath)],
        states={BREATH_GO: [MessageHandler(filters.TEXT & ~filters.COMMAND, breath_flow)]},
        fallbacks=[]
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("ground", ground)],
        states={GROUND_GO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ground_flow)]},
        fallbacks=[]
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("plan", plan)],
        states={PLAN_GO: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_flow)]},
        fallbacks=[]
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("triggers", trig)],
        states={TRIG_GO: [MessageHandler(filters.TEXT & ~filters.COMMAND, trig_flow)]},
        fallbacks=[]
    ))

    app.add_handler(CommandHandler("report", report))
    app.add_handler(MessageHandler(filters.Regex(r"^(7|30)$"), report_value))
    app.add_handler(MessageHandler(filters.Regex(r"^(lang\s+(en|uk)|country\s+(US|UA))$", re.I), wildcard))

    # Fallback чат с OpenAI/подсказками
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    return app


if __name__ == "__main__":
    application = build_app()
    # ВАЖНО: без asyncio.run — это синхронный блокирующий вызов (fix event loop error)
    application.run_polling(drop_pending_updates=True)
