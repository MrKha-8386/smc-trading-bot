# ═══════════════════════════════════════════════════════════
#  SMC Agent — Order Block, BOS, FVG Detection
# ═══════════════════════════════════════════════════════════
import pandas as pd
import numpy as np


def find_swing_highs_lows(df: pd.DataFrame, length: int = 5):
    """Tìm swing high/low từ OHLCV dataframe"""
    highs = []
    lows = []
    for i in range(length, len(df) - length):
        if df["high"].iloc[i] == df["high"].iloc[i - length:i + length + 1].max():
            highs.append((i, df["high"].iloc[i]))
        if df["low"].iloc[i] == df["low"].iloc[i - length:i + length + 1].min():
            lows.append((i, df["low"].iloc[i]))
    return highs, lows


def detect_bos(df: pd.DataFrame, swing_length: int = 5):
    """
    Phát hiện Break of Structure
    Returns: dict {bos: bool, direction: BULL/BEAR/NONE, level: float}
    """
    highs, lows = find_swing_highs_lows(df, swing_length)
    close = df["close"].iloc[-1]
    prev_close = df["close"].iloc[-2]

    bos_bull = False
    bos_bear = False
    bos_level = None

    if highs:
        last_sh = highs[-1][1]
        if prev_close <= last_sh and close > last_sh:
            bos_bull = True
            bos_level = last_sh

    if lows:
        last_sl = lows[-1][1]
        if prev_close >= last_sl and close < last_sl:
            bos_bear = True
            bos_level = last_sl

    return {
        "bos": bos_bull or bos_bear,
        "bos_direction": "BULL" if bos_bull else "BEAR" if bos_bear else "NONE",
        "bos_level": bos_level,
        "last_swing_high": highs[-1][1] if highs else None,
        "last_swing_low": lows[-1][1] if lows else None,
    }


def detect_order_blocks(df: pd.DataFrame, lookback: int = 10, bias: str = "NEUTRAL"):
    """
    Phát hiện Order Block gần nhất
    Bullish OB: nến đỏ trước khi BOS lên
    Bearish OB: nến xanh trước khi BOS xuống
    """
    bull_ob_high = None
    bull_ob_low = None
    bear_ob_high = None
    bear_ob_low = None

    recent = df.tail(lookback + 1).reset_index(drop=True)

    for i in range(len(recent) - 2, 0, -1):
        candle = recent.iloc[i]
        # Bullish OB: nến đỏ (close < open)
        if candle["close"] < candle["open"] and bull_ob_high is None:
            bull_ob_high = candle["open"]
            bull_ob_low = candle["close"]

        # Bearish OB: nến xanh (close > open)
        if candle["close"] > candle["open"] and bear_ob_high is None:
            bear_ob_high = candle["close"]
            bear_ob_low = candle["open"]

        if bull_ob_high and bear_ob_high:
            break

    ob_high = bull_ob_high if bias == "BULLISH" else bear_ob_high
    ob_low = bull_ob_low if bias == "BULLISH" else bear_ob_low

    return {
        "ob_high": round(ob_high, 2) if ob_high else None,
        "ob_low": round(ob_low, 2) if ob_low else None,
        "bull_ob_high": round(bull_ob_high, 2) if bull_ob_high else None,
        "bull_ob_low": round(bull_ob_low, 2) if bull_ob_low else None,
        "bear_ob_high": round(bear_ob_high, 2) if bear_ob_high else None,
        "bear_ob_low": round(bear_ob_low, 2) if bear_ob_low else None,
        "in_ob": _check_in_ob(df["close"].iloc[-1], ob_high, ob_low),
    }


def _check_in_ob(price: float, ob_high, ob_low) -> bool:
    if ob_high is None or ob_low is None:
        return False
    return ob_low <= price <= ob_high


def detect_fvg(df: pd.DataFrame, min_size: float = 0.5):
    """
    Phát hiện Fair Value Gap (imbalance)
    Bull FVG: low[0] > high[2]
    Bear FVG: high[0] < low[2]
    """
    if len(df) < 3:
        return {"fvg_bull": False, "fvg_bear": False, "fvg_high": None, "fvg_low": None}

    c0 = df.iloc[-1]
    c2 = df.iloc[-3]

    bull_fvg = c0["low"] > c2["high"] and (c0["low"] - c2["high"]) >= min_size
    bear_fvg = c0["high"] < c2["low"] and (c2["low"] - c0["high"]) >= min_size

    fvg_high = None
    fvg_low = None

    if bull_fvg:
        fvg_high = round(c0["low"], 2)
        fvg_low = round(c2["high"], 2)
    elif bear_fvg:
        fvg_high = round(c2["low"], 2)
        fvg_low = round(c0["high"], 2)

    return {
        "fvg_bull": bull_fvg,
        "fvg_bear": bear_fvg,
        "fvg_high": fvg_high,
        "fvg_low": fvg_low,
    }


def analyze(df_m5: pd.DataFrame, bias: str = "NEUTRAL") -> dict:
    """
    Chạy toàn bộ SMC analysis trên M5 data
    """
    bos = detect_bos(df_m5)
    ob = detect_order_blocks(df_m5, bias=bias)
    fvg = detect_fvg(df_m5)

    return {
        **bos,
        **ob,
        **fvg,
    }
