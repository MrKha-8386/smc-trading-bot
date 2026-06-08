# ═══════════════════════════════════════════════════════════
#  SMC Trading Bot v2.1
#  Stack  : FastAPI + yfinance + APScheduler + Railway
#  Flow   : Fetch XAUUSD data → SMC/WR% Agents → Boss → Telegram
# ═══════════════════════════════════════════════════════════

import os
import logging
from datetime import datetime
from contextlib import asynccontextmanager

import pandas as pd
import yfinance as yf
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agents import smc_agent, wr_bias_agent, boss_agent
from agents.telegram_notifier import send_signal, send_status

# ─── LOGGING ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("smc_bot")

# ─── CONFIG ─────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SYMBOL_YF        = os.getenv("SYMBOL_YF", "GC=F")   # XAUUSD trên yfinance
MIN_CONFIDENCE   = int(os.getenv("MIN_CONFIDENCE", "60"))

# ─── STATE ──────────────────────────────────────────────────
signal_history = []
last_analysis  = {}
bot_stats      = {"runs": 0, "signals_sent": 0, "errors": 0, "started_at": None}

# ─── FETCH DATA ─────────────────────────────────────────────
def fetch_data() -> tuple:
    """
    Fetch XAUUSD M5 và H1 từ yfinance
    GC=F = Gold Futures (tương đương XAUUSD)
    """
    ticker = yf.Ticker(SYMBOL_YF)

    # M5 data — lấy 5 ngày gần nhất
    df_m5 = ticker.history(period="5d", interval="5m")
    # H1 data — lấy 60 ngày gần nhất
    df_h1 = ticker.history(period="60d", interval="1h")

    # Chuẩn hoá tên cột
    for df in [df_m5, df_h1]:
        df.columns = [c.lower() for c in df.columns]
        df.rename(columns={"stock splits": "stock_splits"}, inplace=True, errors="ignore")

    # Giữ đúng các cột cần thiết
    cols = ["open", "high", "low", "close", "volume"]
    df_m5 = df_m5[[c for c in cols if c in df_m5.columns]].dropna()
    df_h1 = df_h1[[c for c in cols if c in df_h1.columns]].dropna()

    return df_m5, df_h1

# ─── MAIN ANALYSIS LOOP ─────────────────────────────────────
async def run_analysis():
    global last_analysis
    bot_stats["runs"] += 1

    try:
        logger.info(f"🔄 Run #{bot_stats['runs']} — fetching {SYMBOL_YF}...")

        df_m5, df_h1 = fetch_data()

        if df_m5.empty or df_h1.empty:
            logger.warning("⚠️ Empty data")
            bot_stats["errors"] += 1
            return

        close = df_m5["close"].iloc[-1]
        atr   = boss_agent.calculate_atr(df_m5)

        # ── Agents ───────────────────────────────────────────
        wr_result  = wr_bias_agent.analyze(df_m5, df_h1)
        smc_result = smc_agent.analyze(df_m5, bias=wr_result["bias"])

        # ── Boss Agent ────────────────────────────────────────
        result = boss_agent.generate_signal(
            smc=smc_result,
            wr=wr_result,
            close=close,
            atr=atr,
            min_confidence=MIN_CONFIDENCE,
        )

        last_analysis = {**result, "timestamp": datetime.utcnow().isoformat()}

        logger.info(
            f"  → Bias: {result['bias']} | WR%: {result['wr_m5']} | "
            f"Signal: {result['signal']} | Conf: {result['confidence']}%"
        )

        # ── Gửi Telegram ─────────────────────────────────────
        if result["signal"] in ["BUY", "SELL"] and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            await send_signal(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, result, "XAUUSD")
            bot_stats["signals_sent"] += 1
            signal_history.append({**result, "timestamp": datetime.utcnow().isoformat()})
            if len(signal_history) > 100:
                signal_history.pop(0)

    except Exception as e:
        bot_stats["errors"] += 1
        logger.error(f"❌ Error: {e}", exc_info=True)

# ─── LIFESPAN ───────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    bot_stats["started_at"] = datetime.utcnow().isoformat()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_analysis, "interval", minutes=5, id="analysis")
    scheduler.start()
    logger.info("✅ Scheduler started — every 5 min")

    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            await send_status(
                TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
                f"🤖 <b>SMC Bot v2.1 Online!</b>\n"
                f"📊 Symbol: XAUUSD (GC=F)\n"
                f"⏱ Interval: 5 minutes\n"
                f"🎯 Min confidence: {MIN_CONFIDENCE}%"
            )
        except Exception:
            pass

    await run_analysis()
    yield
    scheduler.shutdown()

# ─── APP ────────────────────────────────────────────────────
app = FastAPI(title="SMC Trading Bot v2.1", version="2.1.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def root():
    return {"status": "SMC Bot Online 🟢", "version": "2.1.0", "stats": bot_stats}

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat(), "stats": bot_stats}

@app.get("/analysis")
async def get_analysis():
    return last_analysis or {"message": "No analysis yet — chờ 5 phút"}

@app.get("/signals")
async def get_signals(limit: int = 10):
    recent = signal_history[-limit:] if signal_history else []
    return {"total": len(signal_history), "signals": list(reversed(recent))}

@app.post("/run")
async def trigger_run():
    await run_analysis()
    return {"status": "done", "result": last_analysis}
