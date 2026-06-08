# ═══════════════════════════════════════════════════════════
#  WR% + Bias Agent — Williams %R & H1 Structure Bias
# ═══════════════════════════════════════════════════════════
import pandas as pd
import numpy as np


def williams_r(df: pd.DataFrame, period: int = 14) -> float:
    """Tính Williams %R"""
    if len(df) < period:
        return -50.0
    highest = df["high"].tail(period).max()
    lowest = df["low"].tail(period).min()
    close = df["close"].iloc[-1]
    if highest == lowest:
        return -50.0
    return round((highest - close) / (highest - lowest) * -100, 2)


def detect_h1_bias(df_h1: pd.DataFrame, swing_length: int = 5) -> dict:
    """
    Xác định bias H1 dựa trên HH/HL (Bullish) hoặc LH/LL (Bearish)
    """
    if len(df_h1) < swing_length * 3:
        return {"bias": "NEUTRAL", "structure": "N/A", "wr_h1": -50.0}

    highs = []
    lows = []

    for i in range(swing_length, len(df_h1) - swing_length):
        if df_h1["high"].iloc[i] == df_h1["high"].iloc[i - swing_length:i + swing_length + 1].max():
            highs.append(df_h1["high"].iloc[i])
        if df_h1["low"].iloc[i] == df_h1["low"].iloc[i - swing_length:i + swing_length + 1].min():
            lows.append(df_h1["low"].iloc[i])

    bias = "NEUTRAL"
    structure = "N/A"

    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1] > highs[-2]
        hl = lows[-1] > lows[-2]
        lh = highs[-1] < highs[-2]
        ll = lows[-1] < lows[-2]

        if hh and hl:
            bias = "BULLISH"
            structure = "HH+HL"
        elif lh and ll:
            bias = "BEARISH"
            structure = "LH+LL"
        elif hh and ll:
            bias = "NEUTRAL"
            structure = "HH+LL (choppy)"
        elif lh and hl:
            bias = "NEUTRAL"
            structure = "LH+HL (choppy)"

    wr_h1 = williams_r(df_h1)

    # Confirm bias bằng WR%
    if bias == "BULLISH" and wr_h1 > -20:
        bias = "BULLISH_WEAK"
    if bias == "BEARISH" and wr_h1 < -80:
        bias = "BEARISH_WEAK"

    return {
        "bias": bias,
        "structure": structure,
        "wr_h1": wr_h1,
        "last_sh": round(highs[-1], 2) if highs else None,
        "last_sl": round(lows[-1], 2) if lows else None,
    }


def analyze(df_m5: pd.DataFrame, df_h1: pd.DataFrame) -> dict:
    """
    Chạy toàn bộ WR% + Bias analysis
    """
    wr_m5 = williams_r(df_m5)
    h1_result = detect_h1_bias(df_h1)

    # Trạng thái WR%
    wr_zone = "NEUTRAL"
    if wr_m5 <= -80:
        wr_zone = "OVERSOLD"
    elif wr_m5 >= -20:
        wr_zone = "OVERBOUGHT"

    return {
        "wr_m5": wr_m5,
        "wr_zone": wr_zone,
        **h1_result,
    }
