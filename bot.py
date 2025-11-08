import asyncio, os, re, json
from datetime import datetime, timedelta
import aiosqlite
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler, filters, ContextTypes

load_dotenv()
BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
DEFAULT_LANG=os.getenv("DEFAULT_LANG","en")
DEFAULT_COUNTRY=os.getenv("DEFAULT_COUNTRY","US").upper()
OPENAI_API_KEY=os.getenv("OPENAI_API_KEY","").strip()

def t(lang):
    here=os.path.dirname(__file__); p=os.path.join(here,"i18n",f"{lang}.json")
    if not os.path.exists(p): p=os.path.join(here,"i18n","en.json")
    return json.load(open(p,"r",encoding="utf-8"))

DB=os.path.join(os.path.dirname(__file__),"svitlo.sqlite3")

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, lang TEXT, country TEXT, created_at TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS checkins (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, ts TEXT, stress REAL, triggers TEXT, sleep_hours REAL, micro_goal TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS triggers (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, ts TEXT, note TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS plans (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, ts TEXT, item TEXT)")
        await db.commit()

SUICIDE=re.compile(r"\b(kill myself|suicide|end it|self-harm|cut myself|want to die|не хочу жити|суїцид|покінчити|зарізатись|вкоротити|самопошкодження)\b", re.I)

async def get_user(uid:int):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT user_id,lang,country FROM users WHERE user_id=?",(uid,)) as cur:
            row=await cur.fetchone()
            if row: return {"user_id":row[0],"lang":row[1],"country":row[2]}
        await db.execute("INSERT INTO users (user_id,lang,country,created_at) VALUES (?,?,?,?)",(uid,DEFAULT_LANG,DEFAULT_COUNTRY,datetime.utcnow().isoformat()))
        await db.commit(); return {"user_id":uid,"lang":DEFAULT_LANG,"country":DEFAULT_COUNTRY}

async def set_lang(uid:int, lang:str):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET lang=? WHERE user_id=?",(lang,uid)); await db.commit()

async def set_country(uid:int, country:str):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET country=? WHERE user_id=?",(country,uid)); await db.commit()

async def save_checkin(uid:int, stress:float, triggers:str, sleep:float, goal:str):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO checkins (user_id,ts,stress,triggers,sleep_hours,micro_goal) VALUES (?,?,?,?,?,?)",(uid,datetime.utcnow().isoformat(),stress,triggers,sleep,goal)); await db.commit()

async def save_trigger(uid:int, note:str):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO triggers (user_id,ts,note) VALUES (?,?,?)",(uid,datetime.utcnow().isoformat(),note)); await db.commit()

async def save_plan(uid:int, item:str):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO plans (user_id,ts,item) VALUES (?,?,?)",(uid,datetime.utcnow().isoformat(),item)); await db.commit()

async def agg(uid:int, days:int):
    since=datetime.utcnow()-timedelta(days=days)
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT stress,sleep_hours,triggers FROM checkins WHERE user_id=? AND ts>=?",(uid,since.isoformat())) as cur:
            rows=await cur.fetchall()
    if not rows: return None
    stresses=[r[0] for r in rows if r[0] is not None]
    sleeps=[r[1] for r in rows if r[1] is not None]
    import re, collections
    words=re.findall(r"[A-Za-zА-Яа-яЇїІіЄєҐґ']{3,}", " ".join([r[2] or "" for r in rows]))
    top=", ".join([w for w,_ in collections.Counter([w.lower() for w in words]).most_common(5)]) or "—"
    return {"avg": (sum(stresses)/len(stresses)) if stresses else 0.0,
            "sleep": (sum(sleeps)/len(sleeps)) if sleeps else 0.0,
            "n": len(rows),
            "top": top}

async def crisis(update:Update):
    txt=(update.message.text if update.message else "") or ""
    if SUICIDE.search(txt):
        u=await get_user(update.effective_user.id); T=t(u["lang"])
        await update.message.reply_text(T["crisis_detected"]); return True
    return False

# States
DAILY_STRESS, DAILY_TRIGGERS, DAILY_SLEEP, DAILY_GOAL = range(4)

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=await get_user(update.effective_user.id); T=t(u["lang"])
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("EN",callback_data="lang_en"),InlineKeyboardButton("UK",callback_data="lang_uk")]])
    await update.message.reply_text(T["start"], parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text(T["choose_lang"], reply_markup=kb)

async def cb(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; data=q.data; u=await get_user(update.effective_user.id)
    if data.startswith("lang_"):
        lang=data.split("_")[1]; await set_lang(u["user_id"],lang); T=t(lang)
        await q.answer("OK"); await q.edit_message_text(f"{T['saved']} Language set to {lang.upper()}.")
    else: await q.answer("OK")

async def settings(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=await get_user(update.effective_user.id); T=t(u["lang"])
    await update.message.reply_text(T["settings"].format(lang=u["lang"], country=u["country"]))

async def wildcard(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=await get_user(update.effective_user.id); T=t(u["lang"]); text=update.message.text.strip().lower()
    if text.startswith("lang "):
        lang=text.split()[-1]; 
        if lang in ("en","uk"): await set_lang(u["user_id"],lang); await update.message.reply_text(T["saved"])
    elif text.startswith("country "):
        c=text.split()[-1].upper(); 
        if c in ("US","UA"): await set_country(u["user_id"],c); await update.message.reply_text(T["saved"])

async def daily(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if await crisis(update): return ConversationHandler.END
    u=await get_user(update.effective_user.id); T=t(u["lang"]); await update.message.reply_text(T["checkin_intro"]); return DAILY_STRESS
async def daily_stress(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if await crisis(update): return ConversationHandler.END
    try: val=float(update.message.text.replace(",",".")); val=max(0.0,min(10.0,val)); context.user_data["s"]=val
    except: await update.message.reply_text("0–10"); return DAILY_STRESS
    u=await get_user(update.effective_user.id); T=t(u["lang"]); await update.message.reply_text(T["checkin_stress_saved"].format(val=val)); return DAILY_TRIGGERS
async def daily_triggers(update:Update, context:ContextTypes.DEFAULT_TYPE):
    context.user_data["tr"]=update.message.text.strip(); u=await get_user(update.effective_user.id); T=t(u["lang"]); await update.message.reply_text(T["checkin_triggers_saved"]); return DAILY_SLEEP
async def daily_sleep(update:Update, context:ContextTypes.DEFAULT_TYPE):
    try: context.user_data["sl"]=float(update.message.text.replace(",","."))
    except: await update.message.reply_text("e.g., 6.5"); return DAILY_SLEEP
    u=await get_user(update.effective_user.id); T=t(u["lang"]); await update.message.reply_text(T["checkin_sleep_saved"]); return DAILY_GOAL
async def daily_goal(update:Update, context:ContextTypes.DEFAULT_TYPE):
    g=update.message.text.strip(); u=await get_user(update.effective_user.id); T=t(u["lang"])
    await save_checkin(u["user_id"], context.user_data.get("s"), context.user_data.get("tr",""), context.user_data.get("sl"), g)
    await update.message.reply_text(T["checkin_done"]); return ConversationHandler.END

async def breath(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=await get_user(update.effective_user.id); T=t(u["lang"]); await update.message.reply_text(T["breath_intro"]); return 0
async def breath_flow(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip().lower()!="go": await update.message.reply_text("Type 'go'"); return 0
    u=await get_user(update.effective_user.id); T=t(u["lang"]); await update.message.reply_text(T["breath_go"]); return ConversationHandler.END

async def ground(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=await get_user(update.effective_user.id); T=t(u["lang"]); context.user_data["g"]=0; await update.message.reply_text(T["ground_intro"]); return 0
async def ground_flow(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=await get_user(update.effective_user.id); T=t(u["lang"]); idx=context.user_data.get("g",0)
    steps_en=[("5 things you see","around you"),("4 you touch","textures"),("3 you hear","ambient"),("2 you smell","scents"),("1 you taste","or imagine")]
    steps_uk=[("5 що бачиш","навколо"),("4 що торкаєшся","текстури"),("3 що чуєш","довкола"),("2 запах","навіть ледь"),("1 смак","або уяви")]
    steps=steps_en if u["lang"]=="en" else steps_uk
    if idx==0: context.user_data["g"]=1; c,h=steps[0]; await update.message.reply_text(T["ground_step"].format(count=c,hint=h)); return 0
    if idx<len(steps): context.user_data["g"]=idx+1; c,h=steps[idx]; await update.message.reply_text(T["ok"]+"\n"+T["ground_step"].format(count=c,hint=h)); return 0
    await update.message.reply_text("Done."); return ConversationHandler.END

async def plan(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=await get_user(update.effective_user.id); T=t(u["lang"]); context.user_data["p"]=[]; await update.message.reply_text(T["plan_intro"]); return 0
async def plan_flow(update:Update, context:ContextTypes.DEFAULT_TYPE):
    txt=update.message.text.strip()
    if txt.lower()=="done": u=await get_user(update.effective_user.id); [await save_plan(u["user_id"],it) for it in context.user_data.get("p",[])[:3]]; T=t(u["lang"]); await update.message.reply_text(T["plan_saved"]); return ConversationHandler.END
    context.user_data.setdefault("p",[]).append(txt); await update.message.reply_text("Added. 'done' to save"); return 0

async def trig(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=await get_user(update.effective_user.id); T=t(u["lang"]); await update.message.reply_text(T["triggers_intro"]); return 0
async def trig_flow(update:Update, context:ContextTypes.DEFAULT_TYPE):
    txt=update.message.text.strip()
    if txt.lower()=="done": u=await get_user(update.effective_user.id); T=t(u["lang"]); await update.message.reply_text(T["saved"]); return ConversationHandler.END
    u=await get_user(update.effective_user.id); await save_trigger(u["user_id"], txt); await update.message.reply_text("Logged."); return 0

async def report(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=await get_user(update.effective_user.id); T=t(u["lang"]); await update.message.reply_text(T["report_intro"])
async def report_value(update:Update, context:ContextTypes.DEFAULT_TYPE):
    try: days=int(update.message.text.strip()); assert days in (7,30)
    except: await update.message.reply_text("Reply 7 or 30."); return
    u=await get_user(update.effective_user.id); T=t(u["lang"]); A=await agg(u["user_id"], days)
    if not A: await update.message.reply_text("No data yet."); return
    await update.message.reply_text(T["report_ready"].format(days=days, avg=A["avg"], n=A["n"], sleep=A["sleep"], trg=A["top"]))

async def chat(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if await crisis(update): return
    if not OPENAI_API_KEY: u=await get_user(update.effective_user.id); T=t(u["lang"]); await update.message.reply_text(T["unknown"]); return
    from openai import OpenAI
    client=OpenAI(api_key=OPENAI_API_KEY)
    system=("You are Svitlo AI, a mental health training assistant for veterans. NOT medical or crisis. Avoid diagnosis/meds/politics/religion/graphic. Be brief/practical. If self-harm -> refuse + helplines.")
    r=client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"system","content":system},{"role":"user","content":update.message.text[:2000]}], temperature=0.4, max_tokens=300)
    await update.message.reply_text(r.choices[0].message.content.strip())

def build()->Application:
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(ConversationHandler(entry_points=[CommandHandler("daily", daily)], states={0:[MessageHandler(filters.TEXT & ~filters.COMMAND, daily_stress)],1:[MessageHandler(filters.TEXT & ~filters.COMMAND, daily_triggers)],2:[MessageHandler(filters.TEXT & ~filters.COMMAND, daily_sleep)],3:[MessageHandler(filters.TEXT & ~filters.COMMAND, daily_goal)]}, fallbacks=[]))
    app.add_handler(ConversationHandler(entry_points=[CommandHandler("breath", breath)], states={0:[MessageHandler(filters.TEXT & ~filters.COMMAND, breath_flow)]}, fallbacks=[]))
    app.add_handler(ConversationHandler(entry_points=[CommandHandler("ground", ground)], states={0:[MessageHandler(filters.TEXT & ~filters.COMMAND, ground_flow)]}, fallbacks=[]))
    app.add_handler(ConversationHandler(entry_points=[CommandHandler("plan", plan)], states={0:[MessageHandler(filters.TEXT & ~filters.COMMAND, plan_flow)]}, fallbacks=[]))
    app.add_handler(ConversationHandler(entry_points=[CommandHandler("triggers", trig)], states={0:[MessageHandler(filters.TEXT & ~filters.COMMAND, trig_flow)]}, fallbacks=[]))
    app.add_handler(CommandHandler("sleep", lambda u,c: u.message.reply_text(t("en")["sleep_tips"])))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(MessageHandler(filters.Regex(r"^(7|30)$"), report_value))
    app.add_handler(MessageHandler(filters.Regex(r"^(lang\\s+(en|uk)|country\\s+(US|UA))$"), wildcard))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    return app

async def main():
    if not BOT_TOKEN: print("No TELEGRAM_BOT_TOKEN set"); return
    await init_db(); app=build(); print("Svitlo AI running…"); await app.run_polling()

if __name__=="__main__":
    asyncio.run(main())
