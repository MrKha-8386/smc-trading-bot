# ═══════════════════════════════════════════════════════════
#  SMC Trading Bot v2.2
#  Stack  : FastAPI + Twelve Data API + APScheduler + Railway
#  Flow   : Fetch XAUUSD → SMC/WR% Agents → Boss → Telegram
# ═══════════════════════════════════════════════════════════

import os
import logging
from datetime import datetime
from contextlib import asynccontextmanager

import httpx
import pandas as pd
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
TWELVE_API_KEY   = os.getenv("TWELVE_API_KEY", "")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SYMBOL           = os.getenv("SYMBOL", "XAU/USD")
MIN_CONFIDENCE   = int(os.getenv("MIN_CONFIDENCE", "60"))
NOTIFY_ON_START  = os.getenv("NOTIFY_ON_START", "false").lower() == "true"

TWELVE_BASE = "https://api.twelvedata.com"

# ─── STATE ──────────────────────────────────────────────────
signal_history = []
last_analysis  = {}
bot_stats      = {"runs": 0, "signals_sent": 0, "errors": 0, "started_at": None}

# ─── FETCH DATA FROM TWELVE DATA ────────────────────────────
async def fetch_ohlcv(interval: str, outputsize: int = 100) -> pd.DataFrame:
    """Fetch OHLCV từ Twelve Data API"""
    url = f"{TWELVE_BASE}/time_series"
    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_API_KEY,
        "format": "JSON",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        data = resp.json()

    if "values" not in data:
        raise Exception(f"Twelve Data error: {data.get('message', data)}")

    df = pd.DataFrame(data["values"])
    df = df.rename(columns={
        "datetime": "datetime",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    })
    # Convert types
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

    # Twelve Data trả về mới nhất trước → đảo lại
    df = df.iloc[::-1].reset_index(drop=True)
    return df

async def fetch_data():
    """Fetch M5 và H1 data"""
    df_m5 = await fetch_ohlcv(interval="5min",  outputsize=100)
    df_h1 = await fetch_ohlcv(interval="1h",    outputsize=100)
    return df_m5, df_h1

# ─── MAIN ANALYSIS LOOP ─────────────────────────────────────
async def run_analysis():
    global last_analysis
    bot_stats["runs"] += 1

    try:
        logger.info(f"🔄 Run #{bot_stats['runs']} — fetching {SYMBOL}...")

        df_m5, df_h1 = await fetch_data()

        if df_m5.empty or df_h1.empty:
            logger.warning("⚠️ Empty data from Twelve Data")
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

        # ── Gửi Telegram nếu có signal ───────────────────────
        if result["signal"] in ["BUY", "SELL"] and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            await send_signal(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, result, SYMBOL)
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

    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID and NOTIFY_ON_START:
        try:
            await send_status(
                TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
                f"🤖 <b>SMC Bot v2.2 Online!</b>\n"
                f"📊 Symbol: {SYMBOL}\n"
                f"📡 Data: Twelve Data API\n"
                f"⏱ Interval: 5 minutes\n"
                f"🎯 Min confidence: {MIN_CONFIDENCE}%"
            )
        except Exception:
            pass

    await run_analysis()
    yield
    scheduler.shutdown()

# ─── APP ────────────────────────────────────────────────────
app = FastAPI(title="SMC Trading Bot v2.2", version="2.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def root():
    return {"status": "SMC Bot Online 🟢", "version": "2.2.0", "symbol": SYMBOL, "stats": bot_stats}

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat(), "stats": bot_stats}

@app.get("/analysis")
async def get_analysis():
    return last_analysis or {"message": "No analysis yet — chờ 1 phút"}

@app.get("/signals")
async def get_signals(limit: int = 10):
    recent = signal_history[-limit:] if signal_history else []
    return {"total": len(signal_history), "signals": list(reversed(recent))}

@app.post("/run")
async def trigger_run():
    await run_analysis()
    return {"status": "done", "result": last_analysis}

# ─── BACKTEST + DASHBOARD ────────────────────────────────────
from backtest import run_backtest
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os as _os
if _os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/dashboard")
async def dashboard():
    return FileResponse("static/dashboard.html")

backtest_cache = {}

@app.get("/backtest")
async def get_backtest():
    """Trả về kết quả backtest cache (nếu có)"""
    return backtest_cache or {"message": "Chưa có backtest — gọi POST /backtest/run"}

@app.post("/backtest/run")
async def trigger_backtest():
    """Chạy backtest 3 tháng (mất ~30-60 giây)"""
    global backtest_cache
    try:
        logger.info("🔬 Starting backtest...")
        backtest_cache = await run_backtest()
        logger.info(f"✅ Backtest done: {backtest_cache.get('total_trades')} trades")
        return backtest_cache
    except Exception as e:
        logger.error(f"❌ Backtest error: {e}")
        return {"error": str(e)}
