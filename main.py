# ═══════════════════════════════════════════════════════════
#  SMC Trading Bot v2.0
#  Stack  : FastAPI + tvdatafeed + APScheduler + Railway
#  Flow   : Fetch TV data → SMC/WR% Agents → Boss → Telegram
# ═══════════════════════════════════════════════════════════

import os
import logging
from datetime import datetime
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from tvdatafeed import TvDatafeed, Interval

from agents import smc_agent, wr_bias_agent, boss_agent
from agents.telegram_notifier import send_signal, send_status

# ─── LOGGING ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("smc_bot")

# ─── CONFIG TỪ ENVIRONMENT VARIABLES ────────────────────────
TV_USERNAME      = os.getenv("TV_USERNAME", "")
TV_PASSWORD      = os.getenv("TV_PASSWORD", "")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SYMBOL           = os.getenv("SYMBOL", "XAUUSD")
EXCHANGE         = os.getenv("EXCHANGE", "OANDA")
MIN_CONFIDENCE   = int(os.getenv("MIN_CONFIDENCE", "60"))

# ─── STATE ──────────────────────────────────────────────────
signal_history = []
last_analysis  = {}
bot_stats      = {"runs": 0, "signals_sent": 0, "errors": 0, "started_at": None}

# ─── TVDATAFEED ─────────────────────────────────────────────
def get_tv():
    if TV_USERNAME and TV_PASSWORD:
        return TvDatafeed(TV_USERNAME, TV_PASSWORD)
    return TvDatafeed()  # anonymous mode

def fetch_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch M5 và H1 data từ TradingView"""
    tv = get_tv()
    df_m5 = tv.get_hist(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        interval=Interval.in_5_minute,
        n_bars=100
    )
    df_h1 = tv.get_hist(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        interval=Interval.in_1_hour,
        n_bars=100
    )
    # Chuẩn hoá tên cột
    for df in [df_m5, df_h1]:
        df.columns = [c.lower() for c in df.columns]
    return df_m5, df_h1

# ─── MAIN ANALYSIS LOOP ─────────────────────────────────────
async def run_analysis():
    """Chạy mỗi 5 phút — fetch data → agents → boss → telegram"""
    global last_analysis
    bot_stats["runs"] += 1

    try:
        logger.info(f"🔄 Run #{bot_stats['runs']} — fetching {SYMBOL} data...")

        df_m5, df_h1 = fetch_data()

        if df_m5 is None or df_h1 is None or df_m5.empty or df_h1.empty:
            logger.warning("⚠️ Empty data from tvdatafeed")
            bot_stats["errors"] += 1
            return

        close = df_m5["close"].iloc[-1]
        atr   = boss_agent.calculate_atr(df_m5)

        # ── Chạy các Agents ──────────────────────────────────
        wr_result  = wr_bias_agent.analyze(df_m5, df_h1)
        smc_result = smc_agent.analyze(df_m5, bias=wr_result["bias"])

        # ── Boss Agent tổng hợp ───────────────────────────────
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

        # ── Gửi Telegram nếu có signal ───────────────────────
        if result["signal"] in ["BUY", "SELL"] and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            await send_signal(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, result, SYMBOL)
            bot_stats["signals_sent"] += 1

            # Lưu history
            signal_history.append({**result, "timestamp": datetime.utcnow().isoformat()})
            if len(signal_history) > 100:
                signal_history.pop(0)

    except Exception as e:
        bot_stats["errors"] += 1
        logger.error(f"❌ Analysis error: {e}", exc_info=True)

# ─── LIFESPAN (startup / shutdown) ──────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    bot_stats["started_at"] = datetime.utcnow().isoformat()

    # Scheduler chạy mỗi 5 phút
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_analysis, "interval", minutes=5, id="analysis")
    scheduler.start()
    logger.info("✅ Scheduler started — running every 5 minutes")

    # Notify Telegram bot đã online
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            await send_status(
                TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
                f"🤖 <b>SMC Bot v2.0 Online!</b>\n"
                f"📊 Symbol: {SYMBOL}\n"
                f"⏱ Interval: 5 minutes\n"
                f"🎯 Min confidence: {MIN_CONFIDENCE}%"
            )
        except Exception:
            pass

    # Chạy ngay lần đầu khi khởi động
    await run_analysis()

    yield

    scheduler.shutdown()
    logger.info("Bot shutdown")

# ─── FASTAPI APP ─────────────────────────────────────────────
app = FastAPI(
    title="SMC Trading Bot v2.0",
    description="XAUUSD SMC + WR% Multi-Agent System",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── ENDPOINTS ──────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "status": "SMC Bot Online 🟢",
        "version": "2.0.0",
        "symbol": SYMBOL,
        "stats": bot_stats,
    }

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "stats": bot_stats,
    }

@app.get("/analysis")
async def get_analysis():
    """Xem kết quả analysis gần nhất"""
    return last_analysis or {"message": "No analysis yet"}

@app.get("/signals")
async def get_signals(limit: int = 10):
    """Xem signals BUY/SELL gần nhất"""
    recent = signal_history[-limit:] if signal_history else []
    return {
        "total": len(signal_history),
        "signals": list(reversed(recent))
    }

@app.post("/run")
async def trigger_run():
    """Trigger analysis thủ công"""
    await run_analysis()
    return {"status": "done", "result": last_analysis}
