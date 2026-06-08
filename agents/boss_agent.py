# ═══════════════════════════════════════════════════════════
#  Boss Agent — Tổng hợp signal từ SMC + WR% Agents
# ═══════════════════════════════════════════════════════════
import pandas as pd
import numpy as np
from typing import Optional


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Tính ATR"""
    if len(df) < period + 1:
        return 2.0
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return round(tr.tail(period).mean(), 3)


def calculate_confidence(smc: dict, wr: dict) -> int:
    """
    Tính confidence score 0-100 từ kết quả các agents
    """
    score = 0

    # H1 Bias rõ ràng (+20)
    if wr["bias"] in ["BULLISH", "BEARISH"]:
        score += 20
    elif wr["bias"] in ["BULLISH_WEAK", "BEARISH_WEAK"]:
        score += 10

    # BOS xác nhận (+25)
    if smc["bos"]:
        score += 25

    # Giá trong OB (+30)
    if smc["in_ob"]:
        score += 30

    # FVG hiện diện (+15)
    if smc["fvg_bull"] or smc["fvg_bear"]:
        score += 15

    # WR% ở vùng extreme (+10)
    if wr["wr_zone"] in ["OVERSOLD", "OVERBOUGHT"]:
        score += 10

    return min(score, 100)


def generate_signal(
    smc: dict,
    wr: dict,
    close: float,
    atr: float,
    min_confidence: int = 60,
) -> dict:
    """
    Boss Agent: tổng hợp → ra tín hiệu cuối cùng
    """
    confidence = calculate_confidence(smc, wr)
    bias = wr["bias"]

    # ── BUY condition ─────────────────────────────────────
    buy_signal = (
        bias in ["BULLISH", "BULLISH_WEAK"]
        and smc["in_ob"]
        and (smc["bos_direction"] == "BULL" or smc["fvg_bull"])
        and wr["wr_m5"] < -60
        and confidence >= min_confidence
    )

    # ── SELL condition ────────────────────────────────────
    sell_signal = (
        bias in ["BEARISH", "BEARISH_WEAK"]
        and smc["in_ob"]
        and (smc["bos_direction"] == "BEAR" or smc["fvg_bear"])
        and wr["wr_m5"] > -40
        and confidence >= min_confidence
    )

    signal = "BUY" if buy_signal else "SELL" if sell_signal else "WAIT"

    # ── SL / TP tính từ OB + ATR ─────────────────────────
    sl = tp1 = tp2 = rr = None

    if buy_signal:
        ob_low = smc.get("bull_ob_low") or smc.get("ob_low")
        sl = round((ob_low - atr * 0.3) if ob_low else (close - atr * 2), 2)
        tp1 = round(close + atr * 2, 2)
        tp2 = round(close + atr * 4, 2)

    elif sell_signal:
        ob_high = smc.get("bear_ob_high") or smc.get("ob_high")
        sl = round((ob_high + atr * 0.3) if ob_high else (close + atr * 2), 2)
        tp1 = round(close - atr * 2, 2)
        tp2 = round(close - atr * 4, 2)

    if sl and tp1:
        risk = abs(close - sl)
        reward = abs(tp1 - close)
        rr = round(reward / risk, 2) if risk > 0 else 0

    return {
        "signal": signal,
        "confidence": confidence,
        "bias": bias,
        "wr_m5": wr["wr_m5"],
        "wr_h1": wr["wr_h1"],
        "wr_zone": wr["wr_zone"],
        "structure": wr["structure"],
        "bos": smc["bos"],
        "bos_direction": smc["bos_direction"],
        "in_ob": smc["in_ob"],
        "ob_high": smc["ob_high"],
        "ob_low": smc["ob_low"],
        "fvg_high": smc["fvg_high"],
        "fvg_low": smc["fvg_low"],
        "close": round(close, 2),
        "atr": atr,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "rr": rr,
    }
