# ═══════════════════════════════════════════════════════════
#  SMC Bot - Webhook Receiver (Bước 2 preview)
#  Stack  : FastAPI + Railway
#  Purpose: Nhận JSON từ TradingView Pine Script
# ═══════════════════════════════════════════════════════════

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import json
import logging
from datetime import datetime

# ─── LOGGING ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("smc_bot")

app = FastAPI(
    title="SMC Webhook Bot",
    description="Nhận tín hiệu từ TradingView → xử lý → Telegram",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── PAYLOAD MODEL ──────────────────────────────────────────
class TVPayload(BaseModel):
    symbol: str
    timeframe: str
    timestamp: str
    close: float
    high: float
    low: float
    open: float
    volume: Optional[float] = None
    atr: Optional[float] = None
    williams_r: float
    h1_williams_r: float
    bias_h1: str                     # BULLISH | BEARISH | NEUTRAL
    ob_high: Optional[float] = None
    ob_low: Optional[float] = None
    fvg_high: Optional[float] = None
    fvg_low: Optional[float] = None
    bos: bool
    bos_direction: str               # BULL | BEAR | NONE
    signal: str                      # BUY | SELL | WAIT
    confidence: int                  # 0-100
    sl: float
    tp1: float
    tp2: float
    rr: float
    source: Optional[str] = "tradingview"

# ─── STORAGE TẠM (sẽ thay bằng DB sau) ─────────────────────
signal_history = []

# ─── ENDPOINTS ──────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "status": "SMC Bot Online 🟢",
        "version": "1.0.0",
        "endpoints": ["/webhook", "/health", "/signals"]
    }

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "signals_received": len(signal_history)
    }

@app.post("/webhook")
async def receive_webhook(payload: TVPayload):
    """
    Nhận tín hiệu từ TradingView Pine Script
    """
    try:
        logger.info(f"📨 Webhook nhận được: {payload.symbol} | {payload.signal} | conf={payload.confidence}%")

        # Lưu vào history
        signal_data = payload.dict()
        signal_data["received_at"] = datetime.utcnow().isoformat()
        signal_history.append(signal_data)

        # Giữ tối đa 100 signals gần nhất
        if len(signal_history) > 100:
            signal_history.pop(0)

        # Log chi tiết
        logger.info(
            f"  → Bias H1: {payload.bias_h1} | "
            f"WR%: {payload.williams_r:.1f} | "
            f"BOS: {payload.bos} | "
            f"OB: {payload.ob_low}-{payload.ob_high}"
        )

        if payload.signal in ["BUY", "SELL"]:
            logger.info(
                f"  🎯 SIGNAL: {payload.signal} @ {payload.close} | "
                f"SL: {payload.sl} | TP1: {payload.tp1} | RR: {payload.rr:.2f}"
            )
            # TODO Bước 4: gửi Telegram ở đây
            # await send_telegram(payload)

        return {
            "status": "received",
            "signal": payload.signal,
            "confidence": payload.confidence,
            "processed_at": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ Lỗi xử lý webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signals")
async def get_signals(limit: int = 10):
    """
    Xem các tín hiệu gần nhất
    """
    recent = signal_history[-limit:] if signal_history else []
    return {
        "total": len(signal_history),
        "signals": list(reversed(recent))
    }


@app.post("/webhook/test")
async def test_webhook():
    """
    Test endpoint - gửi payload mẫu để kiểm tra
    """
    sample = TVPayload(
        symbol="XAUUSD",
        timeframe="5",
        timestamp="2026-06-08T10:30:00Z",
        close=3320.50,
        high=3322.00,
        low=3318.00,
        open=3319.00,
        volume=1234.5,
        atr=2.850,
        williams_r=-82.5,
        h1_williams_r=-75.3,
        bias_h1="BEARISH",
        ob_high=3325.00,
        ob_low=3322.50,
        fvg_high=3321.00,
        fvg_low=3319.50,
        bos=True,
        bos_direction="BEAR",
        signal="SELL",
        confidence=85,
        sl=3326.20,
        tp1=3308.50,
        tp2=3296.00,
        rr=2.1,
        source="test"
    )
    return await receive_webhook(sample)
