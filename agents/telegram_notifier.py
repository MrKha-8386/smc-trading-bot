# ═══════════════════════════════════════════════════════════
#  Telegram Notifier
# ═══════════════════════════════════════════════════════════
import httpx
import logging
from datetime import datetime

logger = logging.getLogger("telegram")


async def send_signal(token: str, chat_id: str, result: dict, symbol: str = "XAUUSD"):
    """
    Gửi tín hiệu trading lên Telegram
    """
    signal = result["signal"]
    confidence = result["confidence"]
    close = result["close"]

    # Emoji theo signal
    if signal == "BUY":
        emoji = "🟢"
        direction = "BUY  ▲"
    elif signal == "SELL":
        emoji = "🔴"
        direction = "SELL ▼"
    else:
        return  # Không gửi WAIT

    now = datetime.utcnow().strftime("%H:%M UTC")

    msg = (
        f"{emoji} <b>SMC SIGNAL — {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Direction :</b> {direction}\n"
        f"💰 <b>Entry     :</b> {close}\n"
        f"🛑 <b>Stop Loss :</b> {result['sl']}\n"
        f"🎯 <b>TP1       :</b> {result['tp1']}\n"
        f"🎯 <b>TP2       :</b> {result['tp2']}\n"
        f"📊 <b>RR        :</b> 1 : {result['rr']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 <b>Bias H1   :</b> {result['bias']} ({result['structure']})\n"
        f"📉 <b>WR% M5    :</b> {result['wr_m5']} ({result['wr_zone']})\n"
        f"📉 <b>WR% H1    :</b> {result['wr_h1']}\n"
        f"💡 <b>BOS       :</b> {'✅ ' + result['bos_direction'] if result['bos'] else '❌'}\n"
        f"📦 <b>In OB     :</b> {'✅' if result['in_ob'] else '❌'} "
        f"({result['ob_low']} – {result['ob_high']})\n"
        f"⚡ <b>FVG       :</b> {result['fvg_low']} – {result['fvg_high']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 <b>Confidence:</b> {confidence}%\n"
        f"🕐 <b>Time      :</b> {now}\n"
        f"\n⚠️ <i>DYOR — Not financial advice</i>"
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json={
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
        }, timeout=10)

        if resp.status_code == 200:
            logger.info(f"✅ Telegram sent: {signal} @ {close}")
        else:
            logger.error(f"❌ Telegram error: {resp.text}")


async def send_status(token: str, chat_id: str, message: str):
    """Gửi thông báo status đơn giản"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=10)
