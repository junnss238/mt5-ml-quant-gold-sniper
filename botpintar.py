"""
╔══════════════════════════════════════════════════════════════════════╗
║          GOLD SNIPER PRO v3.0 — XAUUSD M1 Scalping Bot             ║
║                                                                      ║
║  PERBAIKAN dari v2.0:                                                ║
║  ✅ Scoring lebih longgar (EMA50 bukan hard filter lagi)             ║
║  ✅ Partial FVG — tidak perlu gap sempurna                           ║
║  ✅ Volume Spike sebagai konfirmasi (+1 poin)                        ║
║  ✅ MACD Histogram konfirmasi momentum (+1 poin)                     ║
║  ✅ Bollinger Bands untuk deteksi breakout                           ║
║  ✅ Multi-timeframe: M5 sebagai filter arah utama                    ║
║  ✅ Skip entry saat SIDEWAYS (kecuali score sangat tinggi)           ║
║  ✅ MAX SCORE = 10 | MIN_SCORE = 4 (lebih banyak kesempatan entry)   ║
╚══════════════════════════════════════════════════════════════════════╝

INSTALL:
    pip install MetaTrader5 pandas numpy pandas-ta colorama

CARA PAKAI:
    Live    : python gold_sniper_v3.py
    Backtest: python gold_sniper_v3.py --backtest --file data.csv
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import pandas_ta as ta
import time
import logging
import argparse
import sys
import os
from datetime import datetime, timedelta
from colorama import Fore, Style, init
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict

init(autoreset=True)

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("gold_sniper_v3.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("GoldSniperV3")


# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
@dataclass
class Config:
    # ── Koneksi IC Markets ───────────────────
    MT5_LOGIN:    int   = 0                   # ← isi nomor akun
    MT5_PASSWORD: str   = "password"          # ← isi password
    MT5_SERVER:   str   = "ICMarketsSC-Demo"  # ← server IC Markets

    # ── Instrumen ────────────────────────────
    SYMBOL: str = "XAUUSD"
    MAGIC:  int = 77777

    # ── Lot ──────────────────────────────────
    LOT: float = 0.10  # 0.10 lot — raw spread IC Markets

    # ── SCORING SYSTEM v3.0 ──────────────────
    # MAX SCORE = 10 poin
    # ─────────────────────────────────────────
    # +2  Partial FVG (gap > 30% ATR)
    # +1  Pullback ke EMA9 atau VWAP
    # +1  Candle pattern (hammer/engulfing)
    # +1  RSI momentum zona sehat (42-62)
    # +1  EMA9 cross EMA21 baru
    # +1  Volume spike (> 1.5x rata-rata)
    # +1  MACD histogram konfirmasi
    # +1  Bollinger Band squeeze/breakout
    # +1  Close > EMA50 (bonus, bukan syarat)
    # ─────────────────────────────────────────
    # MODE AGRESIF — entry lebih sering, ambil profit walau kecil
    # sc≥5 → ~115 trades/8hari, lebih banyak kesempatan
    # sc≥7 → ~131 trades/8hari, lebih selektif (default lama)
    MIN_SCORE:     int   = 7    # 7/10 = 70% indikator setuju — terbukti profit
    SIDEWAYS_SCORE: int  = 7    # ← Sideways tetap butuh lebih, tapi tidak terlalu ketat
    ATR_MIN:       float = 1.5  # Skip candle terlalu kecil

    # ── TP / SL ──────────────────────────────
    SL_ATR_MULT: float = 1.5   # SL lebar — beri napas M1
    TP_ATR_MULT: float = 0.5   # TP cepat — WR tinggi

    # ── Session (GMT) ─────────────────────────
    SESSION_START: int = 1
    SESSION_END:   int = 24

    # ── Risk Management ───────────────────────
    MAX_SPREAD:         int   = 50    # Dilonggarkan — jangan halangi entry saat posisi bagus
    MAX_DAILY_LOSS_PCT: float = 10.0  # Demo — longgar untuk observasi
    MAX_DAILY_TRADES:   int   = 50    # Agresif — banyak entry dalam sehari
    MAX_POSITIONS:      int   = 5     # Lebih banyak posisi boleh jalan bersamaan
    CIRCUIT_BREAKER_N:  int   = 4     # Stop setelah 4 SL beruntun
    CIRCUIT_SLEEP_SEC:  int   = 1800  # Istirahat 30 menit
    SLIPPAGE:           int   = 10

    # ── Cooldown ──────────────────────────────
    ENTRY_COOLDOWN_SEC: int = 10  # Pendek — jangan lewatkan peluang beruntun

    # ── Indikator ────────────────────────────
    VOL_SPIKE_MULT: float = 1.5   # Volume dianggap spike jika > 1.5x rata-rata
    BB_PERIOD:      int   = 20    # Bollinger Bands period
    BB_STD:         float = 2.0   # Bollinger Bands std dev
    MACD_FAST:      int   = 12
    MACD_SLOW:      int   = 26
    MACD_SIGNAL:    int   = 9


CFG = Config()


# ─────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────
@dataclass
class State:
    is_running:       bool  = True
    daily_start_bal:  float = 0.0
    daily_trades:     int   = 0
    last_entry_time:  float = 0.0
    circuit_until:    float = 0.0
    last_day:         int   = -1

    def reset_daily(self, bal: float):
        self.daily_start_bal = bal
        self.daily_trades    = 0
        self.last_day        = datetime.now().day
        log.info(f"📅 Hari baru — Balance: ${bal:.2f}")

    def check_new_day(self, bal: float):
        if datetime.now().day != self.last_day:
            self.reset_daily(bal)


S = State()

# Registry posisi aktif
REGISTRY: Dict[int, dict] = {}


# ─────────────────────────────────────────────
#  DETEKSI REGIME PASAR
# ─────────────────────────────────────────────
def detect_regime(df: pd.DataFrame) -> dict:
    """
    Deteksi TRENDING / MIXED / SIDEWAYS menggunakan:
    - Choppiness Index (CI): >61 sideways, <45 trending
    - ATR ratio vs median 50 candle
    - EMA21 slope
    """
    df = df.copy().dropna()
    if len(df) < 20:
        return {"regime": "MIXED", "label": "❓ MIXED", "ci": 50,
                "atr_ratio": 1.0, "min_score_override": CFG.MIN_SCORE}

    n = 14
    atr_sum   = df["atr"].rolling(n).sum()
    hi_roll   = df["high"].rolling(n).max()
    lo_roll   = df["low"].rolling(n).min()
    range_rol = (hi_roll - lo_roll).replace(0, np.nan)
    ci        = 100 * np.log10(atr_sum / range_rol) / np.log10(n)
    ci_now    = ci.iloc[-1] if not np.isnan(ci.iloc[-1]) else 50

    atr_now    = df["atr"].iloc[-1]
    atr_median = df["atr"].rolling(50).median().iloc[-1]
    atr_ratio  = atr_now / atr_median if atr_median > 0 else 1.0

    ema21_slope = (df["ema21"].iloc[-1] - df["ema21"].iloc[-5]) / (atr_now * 5) if atr_now > 0 else 0
    slope_abs   = abs(ema21_slope)

    trend_score = 0
    if ci_now    < 45:    trend_score += 3
    elif ci_now  < 55:    trend_score += 2
    elif ci_now  < 61:    trend_score += 1
    if atr_ratio > 1.4:   trend_score += 2
    elif atr_ratio > 1.1: trend_score += 1
    if slope_abs > 0.15:  trend_score += 2
    elif slope_abs > 0.08:trend_score += 1

    if trend_score >= 5:
        return {"regime": "TREND",    "label": f"📈 TREND   (CI:{ci_now:.0f})",
                "ci": ci_now, "atr_ratio": atr_ratio,
                "min_score_override": CFG.MIN_SCORE}          # normal threshold
    elif trend_score >= 2:
        return {"regime": "MIXED",    "label": f"〰️ MIXED   (CI:{ci_now:.0f})",
                "ci": ci_now, "atr_ratio": atr_ratio,
                "min_score_override": CFG.MIN_SCORE}          # normal threshold
    else:
        return {"regime": "SIDEWAYS", "label": f"↔️ SIDEWAYS(CI:{ci_now:.0f})",
                "ci": ci_now, "atr_ratio": atr_ratio,
                "min_score_override": CFG.SIDEWAYS_SCORE}     # butuh score lebih tinggi


# ─────────────────────────────────────────────
#  ANALISA UTAMA — SCORING v3.0
# ─────────────────────────────────────────────
def analisa(df_m1: pd.DataFrame, df_m5: Optional[pd.DataFrame] = None) -> Tuple:
    """
    Sistem scoring 0–10.
    df_m1: data M1 (wajib)
    df_m5: data M5 untuk konfirmasi arah (opsional, jika None dikira netral)
    Return: (atr, signal, score, detail, regime)
    """
    df = df_m1.copy()

    # ── Hitung semua indikator ──
    df["ema9"]  = ta.ema(df["close"], length=9)
    df["ema21"] = ta.ema(df["close"], length=21)
    df["ema50"] = ta.ema(df["close"], length=50)
    df["rsi"]   = ta.rsi(df["close"], length=14)
    df["atr"]   = ta.atr(df["high"], df["low"], df["close"], length=14)
    df["vol_ma"]= df["volume"].rolling(20).mean()

    # VWAP
    try:
        df["vwap"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
    except Exception:
        df["vwap"] = df["close"].rolling(14).mean()

    # Bollinger Bands
    bb = ta.bbands(df["close"], length=CFG.BB_PERIOD, std=CFG.BB_STD)
    if bb is not None and not bb.empty:
        bb.columns = ["BBL", "BBM", "BBU", "BBB", "BBP"]
        df = pd.concat([df, bb], axis=1)
    else:
        df["BBL"] = df["close"].rolling(CFG.BB_PERIOD).mean() - 2 * df["close"].rolling(CFG.BB_PERIOD).std()
        df["BBU"] = df["close"].rolling(CFG.BB_PERIOD).mean() + 2 * df["close"].rolling(CFG.BB_PERIOD).std()
        df["BBB"] = (df["BBU"] - df["BBL"]) / df["close"].rolling(CFG.BB_PERIOD).mean()

    # MACD
    macd = ta.macd(df["close"], fast=CFG.MACD_FAST, slow=CFG.MACD_SLOW, signal=CFG.MACD_SIGNAL)
    if macd is not None and not macd.empty:
        df["macd_hist"] = macd.iloc[:, 2]  # histogram
    else:
        df["macd_hist"] = 0.0

    df = df.dropna()
    if len(df) < 10:
        return 0, "WAIT", 0, {}, {"regime": "UNKNOWN", "label": "❓"}

    c  = df.iloc[-2]   # candle yang baru close
    p  = df.iloc[-3]   # candle sebelumnya
    p2 = df.iloc[-4]   # 2 candle sebelumnya

    atr   = c["atr"]
    if atr < CFG.ATR_MIN:
        return atr, "WAIT", 0, {"skip": f"ATR kecil ({atr:.2f})"}, {}

    ema9  = c["ema9"];  ema21 = c["ema21"];  ema50 = c["ema50"]
    rsi   = c["rsi"];   vwap  = c["vwap"]
    vol_r = c["volume"] / c["vol_ma"] if c["vol_ma"] > 0 else 1.0

    # ── Pola Candle ──
    body         = max(abs(c["close"] - c["open"]), 0.0001)
    lower_shadow = min(c["open"], c["close"]) - c["low"]
    upper_shadow = c["high"] - max(c["open"], c["close"])
    is_hammer        = (lower_shadow >= 1.5 * body) and (upper_shadow <= body)
    is_shooting_star = (upper_shadow >= 1.5 * body) and (lower_shadow <= body)
    is_bull_engulf   = (c["close"] > c["open"]) and (c["open"] < p["close"]) and (c["close"] > p["open"])
    is_bear_engulf   = (c["close"] < c["open"]) and (c["open"] > p["close"]) and (c["close"] < p["open"])

    # ── PARTIAL FVG (v3 fix) ──
    # Tidak perlu gap sempurna, cukup ada gap > 30% ATR antara p2 dan c
    fvg_bull_gap = c["low"] - p2["high"]    # positif = ada gap naik
    fvg_bear_gap = p2["low"] - c["high"]    # positif = ada gap turun
    fvg_bullish  = fvg_bull_gap > (atr * 0.3)   # partial: gap > 30% ATR
    fvg_bearish  = fvg_bear_gap > (atr * 0.3)

    # ── M5 Trend Filter ──
    # BUY: +1 kalau M5 juga bullish, -1 kalau berlawanan
    # SELL: sebaliknya
    m5_bias_bull = 0   # +1 mendukung, -1 melawan, 0 netral
    m5_bias_bear = 0
    if df_m5 is not None and len(df_m5) >= 5:
        try:
            m5e9  = ta.ema(df_m5["close"], length=9).iloc[-1]
            m5e21 = ta.ema(df_m5["close"], length=21).iloc[-1]
            if m5e9 > m5e21:
                m5_bias_bull = 1   # M5 bullish → dukung BUY
                m5_bias_bear = -1  # M5 bullish → kurangi SELL
            elif m5e9 < m5e21:
                m5_bias_bull = -1
                m5_bias_bear = 1
        except Exception:
            pass

    # ── Deteksi regime sebelum scoring ──
    regime = detect_regime(df)
    required_score = regime["min_score_override"]

    detail = {"Regime": regime["label"]}
    score_buy = score_sell = 0

    # ══════════════════════════════════════════
    # SCORING BUY (max 10 poin)
    # Hard requirement: EMA9 > EMA21 (arah dasar)
    # ══════════════════════════════════════════
    if ema9 > ema21:

        # +2 Partial FVG bullish
        if fvg_bullish:
            score_buy += 2
            detail["FVG"] = f"✅ +2 (gap {fvg_bull_gap:.2f})"

        # +1 Pullback ke zona EMA9 atau VWAP
        if c["low"] <= ema9 + (atr * 0.5) or c["low"] <= vwap + (atr * 0.5):
            score_buy += 1
            detail["Pullback"] = "✅ +1"

        # +1 Candle pattern reversal bullish
        if is_hammer or is_bull_engulf:
            score_buy += 1
            detail["Candle"] = f"✅ +1 ({'Hammer' if is_hammer else 'Engulf'})"

        # +1 RSI zona sehat & momentum naik
        if 42 <= rsi <= 62 and p["rsi"] < rsi:
            score_buy += 1
            detail["RSI"] = f"✅ +1 ({rsi:.0f}↑)"

        # +1 EMA cross baru (sinyal kuat)
        if p["ema9"] <= p["ema21"] and ema9 > ema21:
            score_buy += 1
            detail["CrossUp"] = "✅ +1 Fresh Cross"

        # +1 Volume spike (volume konfirmasi momentum)
        if vol_r >= CFG.VOL_SPIKE_MULT:
            score_buy += 1
            detail["Volume"] = f"✅ +1 ({vol_r:.1f}x avg)"

        # +1 MACD histogram positif & membesar
        if c["macd_hist"] > 0 and c["macd_hist"] > p["macd_hist"]:
            score_buy += 1
            detail["MACD"] = f"✅ +1 hist:{c['macd_hist']:.3f}↑"

        # +1 Bollinger Band: harga di lower band atau squeeze breakout naik
        bb_squeeze    = c["BBB"] < 0.03 if "BBB" in c.index else False
        bb_lower_touch = c["close"] <= c["BBL"] * 1.001 if "BBL" in c.index else False
        if bb_lower_touch or bb_squeeze:
            score_buy += 1
            detail["BB"] = f"✅ +1 ({'Squeeze' if bb_squeeze else 'LowerBand'})"

        # +1 Close di atas EMA50 (konfirmasi trend lebih besar)
        if c["close"] > ema50:
            score_buy += 1
            detail["EMA50"] = "✅ +1 Close>EMA50"

        # M5 modifier (soft — bisa negatif)
        score_buy = max(0, score_buy + m5_bias_bull)
        if m5_bias_bull == 1:
            detail["M5"] = "✅ M5 Bullish"
        elif m5_bias_bull == -1:
            detail["M5"] = "⚠️ M5 Berlawanan"

        detail["SCORE_BUY"] = f"{score_buy}/10"

    # ══════════════════════════════════════════
    # SCORING SELL (max 10 poin)
    # ══════════════════════════════════════════
    elif ema9 < ema21:

        if fvg_bearish:
            score_sell += 2
            detail["FVG"] = f"✅ +2 (gap {fvg_bear_gap:.2f})"

        if c["high"] >= ema9 - (atr * 0.5) or c["high"] >= vwap - (atr * 0.5):
            score_sell += 1
            detail["Pullback"] = "✅ +1"

        if is_shooting_star or is_bear_engulf:
            score_sell += 1
            detail["Candle"] = f"✅ +1 ({'ShootStar' if is_shooting_star else 'Engulf'})"

        if 42 <= rsi <= 62 and p["rsi"] > rsi:
            score_sell += 1
            detail["RSI"] = f"✅ +1 ({rsi:.0f}↓)"

        if p["ema9"] >= p["ema21"] and ema9 < ema21:
            score_sell += 1
            detail["CrossDown"] = "✅ +1 Fresh Cross"

        if vol_r >= CFG.VOL_SPIKE_MULT:
            score_sell += 1
            detail["Volume"] = f"✅ +1 ({vol_r:.1f}x avg)"

        if c["macd_hist"] < 0 and c["macd_hist"] < p["macd_hist"]:
            score_sell += 1
            detail["MACD"] = f"✅ +1 hist:{c['macd_hist']:.3f}↓"

        bb_upper_touch = c["close"] >= c["BBU"] * 0.999 if "BBU" in c.index else False
        bb_squeeze     = c["BBB"] < 0.03 if "BBB" in c.index else False
        if bb_upper_touch or bb_squeeze:
            score_sell += 1
            detail["BB"] = f"✅ +1 ({'Squeeze' if bb_squeeze else 'UpperBand'})"

        if c["close"] < ema50:
            score_sell += 1
            detail["EMA50"] = "✅ +1 Close<EMA50"

        score_sell = max(0, score_sell + m5_bias_bear)
        if m5_bias_bear == 1:
            detail["M5"] = "✅ M5 Bearish"
        elif m5_bias_bear == -1:
            detail["M5"] = "⚠️ M5 Berlawanan"

        detail["SCORE_SELL"] = f"{score_sell}/10"

    # ── Final signal ──
    signal    = "WAIT"
    top_score = max(score_buy, score_sell)

    if score_buy  >= required_score and score_buy  > score_sell:
        signal = "BUY"
    elif score_sell >= required_score and score_sell > score_buy:
        signal = "SELL"

    # Tambahan info sideways di detail
    if regime["regime"] == "SIDEWAYS" and top_score < required_score:
        detail["Skip"] = f"⚠️ Sideways: butuh score≥{required_score} (dapat {top_score})"

    return atr, signal, top_score, detail, regime


# ─────────────────────────────────────────────
#  MT5 HELPERS
# ─────────────────────────────────────────────
def get_filling_mode(symbol: str) -> int:
    info = mt5.symbol_info(symbol)
    if info is None:
        return mt5.ORDER_FILLING_IOC
    filling = info.filling_mode
    if filling & mt5.SYMBOL_FILLING_FOK:
        return mt5.ORDER_FILLING_FOK
    if filling & mt5.SYMBOL_FILLING_IOC:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def connect_mt5() -> bool:
    if not mt5.initialize():
        log.error(f"❌ mt5.initialize() gagal: {mt5.last_error()}")
        return False
    if CFG.MT5_LOGIN != 0:
        if not mt5.login(CFG.MT5_LOGIN, CFG.MT5_PASSWORD, CFG.MT5_SERVER):
            log.error(f"❌ Login gagal: {mt5.last_error()}")
            return False
    info = mt5.account_info()
    if info is None:
        log.error("❌ account_info() None")
        return False
    mt5.symbol_select(CFG.SYMBOL, True)
    sym = mt5.symbol_info(CFG.SYMBOL)
    if sym is None:
        log.error(f"❌ Symbol {CFG.SYMBOL} tidak tersedia")
        return False
    S.reset_daily(info.balance)
    log.info(f"✅ Connected: {info.name} | #{info.login} | ${info.balance:.2f}")
    return True


def get_candles(timeframe: int, count: int = 200) -> Optional[pd.DataFrame]:
    rates = mt5.copy_rates_from_pos(CFG.SYMBOL, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"open": "open", "high": "high", "low": "low",
                             "close": "close", "tick_volume": "volume"})
    df.set_index("time", inplace=True)
    return df


def get_spread_pts() -> float:
    tick = mt5.symbol_info_tick(CFG.SYMBOL)
    info = mt5.symbol_info(CFG.SYMBOL)
    if tick is None or info is None:
        return 999
    return (tick.ask - tick.bid) / info.point


def count_positions() -> int:
    pos = mt5.positions_get(symbol=CFG.SYMBOL)
    if pos is None:
        return 0
    return len([p for p in pos if p.magic == CFG.MAGIC])


def check_margin_ok(price: float, atr: float) -> bool:
    info = mt5.account_info()
    sym  = mt5.symbol_info(CFG.SYMBOL)
    if info is None or sym is None:
        return False
    leverage        = info.leverage if info.leverage > 0 else 100
    contract_size   = sym.trade_contract_size
    margin_per_lot  = (contract_size * CFG.LOT * price) / leverage
    sl_reserve      = atr * CFG.SL_ATR_MULT * contract_size * CFG.LOT * 2
    needed          = margin_per_lot + sl_reserve
    return info.margin_free >= needed


def check_circuit_breaker() -> bool:
    if time.time() < S.circuit_until:
        remaining = int(S.circuit_until - time.time()) // 60
        log.debug(f"⏸ Circuit breaker aktif {remaining} menit lagi")
        return True
    from_date = datetime.now() - timedelta(hours=2)
    deals     = mt5.history_deals_get(from_date, datetime.now(), group=CFG.SYMBOL)
    if deals is None:
        return False
    recent_loss = 0
    for deal in reversed(deals):
        if deal.magic != CFG.MAGIC or deal.entry != 1:
            continue
        if deal.profit < 0:
            recent_loss += 1
        else:
            break
    if recent_loss >= CFG.CIRCUIT_BREAKER_N:
        log.warning(f"☠️ {CFG.CIRCUIT_BREAKER_N}x SL beruntun! Tidur 30 menit...")
        S.circuit_until = time.time() + CFG.CIRCUIT_SLEEP_SEC
        return True
    return False


def is_session() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    return CFG.SESSION_START <= now.hour < CFG.SESSION_END


# ─────────────────────────────────────────────
#  EKSEKUSI ORDER
# ─────────────────────────────────────────────
def eksekusi(signal: str, atr: float, score: int, regime: dict) -> bool:
    tick     = mt5.symbol_info_tick(CFG.SYMBOL)
    sym_info = mt5.symbol_info(CFG.SYMBOL)
    if tick is None or sym_info is None:
        return False

    sl_dist = atr * CFG.SL_ATR_MULT
    tp_dist = atr * CFG.TP_ATR_MULT

    if signal == "BUY":
        price  = tick.ask
        sl     = round(price - sl_dist, sym_info.digits)
        tp     = round(price + tp_dist, sym_info.digits)
        tipe   = mt5.ORDER_TYPE_BUY
        arrow  = "🟢 BUY"
    else:
        price  = tick.bid
        sl     = round(price + sl_dist, sym_info.digits)
        tp     = round(price - tp_dist, sym_info.digits)
        tipe   = mt5.ORDER_TYPE_SELL
        arrow  = "🔴 SELL"

    if sl <= 0 or tp <= 0:
        log.error(f"❌ SL/TP invalid: SL={sl} TP={tp}")
        return False

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       CFG.SYMBOL,
        "volume":       CFG.LOT,
        "type":         tipe,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    CFG.SLIPPAGE,
        "magic":        CFG.MAGIC,
        "comment":      f"v3:{score}",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": get_filling_mode(CFG.SYMBOL),
    }

    result = mt5.order_send(request)
    if result is None:
        log.error(f"❌ order_send None | {mt5.last_error()}")
        return False
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"❌ Gagal Code:{result.retcode} | {result.comment}")
        return False

    S.daily_trades    += 1
    S.last_entry_time  = time.time()

    # Simpan ke registry untuk monitoring
    REGISTRY[result.order] = {
        "direction": signal,
        "entry":     price,
        "atr":       atr,
        "sl":        sl,
        "tp":        tp,
        "open_time": time.time(),
        "score":     score,
        "regime":    regime["regime"],
    }

    print(Fore.CYAN + f"""
┌─────────────────────────────────────────────┐
│  {arrow} | Score:{score}/10 | {regime.get('label',''):<22}│
│  Entry : {price:.2f}                                   │
│  TP    : {tp:.2f} (+{tp_dist:.2f} = {tp_dist/atr:.1f}x ATR)          │
│  SL    : {sl:.2f} (-{sl_dist:.2f} = {sl_dist/atr:.1f}x ATR)          │
│  ATR   : {atr:.2f} | Lot: {CFG.LOT}                      │
└─────────────────────────────────────────────┘""")
    log.info(f"{signal} #{result.order} @ {price:.2f} | TP:{tp:.2f} SL:{sl:.2f} | Score:{score} | ATR:{atr:.2f}")
    return True


# ─────────────────────────────────────────────
#  MONITOR POSISI AKTIF
# ─────────────────────────────────────────────
def monitor_positions():
    """
    Monitor posisi yang sudah ada.
    Broker sudah pegang TP/SL — kita hanya log status dan
    bersihkan registry kalau posisi sudah ditutup.
    """
    if not REGISTRY:
        return
    active = set()
    pos = mt5.positions_get(symbol=CFG.SYMBOL)
    if pos:
        active = {p.ticket for p in pos}
    stale = [t for t in REGISTRY if t not in active]
    for t in stale:
        info = REGISTRY.pop(t, None)
        if info:
            log.info(f"📋 Posisi #{t} sudah tutup | {info['regime']} | Score:{info['score']}")


# ─────────────────────────────────────────────
#  DASHBOARD
# ─────────────────────────────────────────────
def print_dashboard(score: int = 0, detail: dict = None):
    info = mt5.account_info()
    if info is None:
        return
    daily_pnl = info.balance - S.daily_start_bal
    spread    = get_spread_pts()
    n_pos     = count_positions()

    pnl_c  = Fore.GREEN if daily_pnl >= 0 else Fore.RED
    spr_c  = Fore.GREEN if spread <= 8 else (Fore.YELLOW if spread <= 15 else Fore.RED)
    sess_c = Fore.GREEN if is_session() else Fore.RED

    print(Fore.YELLOW + f"\n{'─'*54}")
    print(Fore.WHITE  + f"  ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  💰 Balance: ${info.balance:.2f} | Equity: ${info.equity:.2f}")
    print(pnl_c       + f"  📊 Daily P&L: {daily_pnl:+.2f} | Trades: {S.daily_trades}/{CFG.MAX_DAILY_TRADES}")
    print(spr_c       + f"  📡 Spread: {spread:.0f}pt | Posisi: {n_pos}/{CFG.MAX_POSITIONS}")
    print(sess_c      + f"  🕐 Session: {'AKTIF' if is_session() else 'TUTUP'}")

    if score > 0:
        bar = "█" * score + "░" * (10 - score)
        print(Fore.CYAN + f"  🧠 Score: [{bar}] {score}/10")
    if detail:
        for k, v in detail.items():
            if k not in ("SCORE_BUY", "SCORE_SELL", "Regime"):
                print(Fore.CYAN + f"     {k}: {v}")

    positions = mt5.positions_get(symbol=CFG.SYMBOL)
    if positions:
        for p in positions:
            pc = Fore.GREEN if p.profit >= 0 else Fore.RED
            dir_ = "BUY" if p.type == 0 else "SELL"
            print(pc + f"  📌 #{p.ticket} {dir_} @ {p.price_open:.2f} | P&L: ${p.profit:+.2f}")
    print(Fore.YELLOW + "─" * 54)


# ─────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────
def bot_loop():
    last_print = 0
    log.info("🚀 Gold Sniper v3.0 — loop dimulai")

    while S.is_running:
        try:
            now = time.time()

            # Dashboard setiap 30 detik
            if now - last_print > 30:
                monitor_positions()
                print_dashboard()
                last_print = now
            else:
                monitor_positions()

            # Cek koneksi
            if mt5.account_info() is None:
                log.warning("⚠️ Disconnect, reconnect...")
                connect_mt5()
                time.sleep(5)
                continue

            # Daily state
            bal = mt5.account_info().balance
            S.check_new_day(bal)

            # Daily loss limit
            pnl_pct = ((bal - S.daily_start_bal) / S.daily_start_bal) * 100 if S.daily_start_bal > 0 else 0
            if pnl_pct <= -CFG.MAX_DAILY_LOSS_PCT:
                log.warning(f"🛑 Daily loss {pnl_pct:.1f}% — stop hari ini.")
                time.sleep(60)
                continue

            if S.daily_trades >= CFG.MAX_DAILY_TRADES:
                time.sleep(30)
                continue

            if not is_session():
                time.sleep(10)
                continue

            if check_circuit_breaker():
                time.sleep(30)
                continue

            # Spread check
            spread = get_spread_pts()
            if spread > CFG.MAX_SPREAD:
                time.sleep(1)
                continue

            # Max posisi
            if count_positions() >= CFG.MAX_POSITIONS:
                time.sleep(0.5)
                continue

            # Cooldown
            if now - S.last_entry_time < CFG.ENTRY_COOLDOWN_SEC:
                time.sleep(1)
                continue

            # Margin check
            tick_pre = mt5.symbol_info_tick(CFG.SYMBOL)
            if tick_pre is None or not check_margin_ok(tick_pre.ask, CFG.ATR_MIN * 2):
                time.sleep(10)
                continue

            # ── Ambil data M1 dan M5 ──
            df_m1 = get_candles(mt5.TIMEFRAME_M1, 200)
            df_m5 = get_candles(mt5.TIMEFRAME_M5, 60)   # M5 untuk filter trend
            if df_m1 is None:
                time.sleep(1)
                continue

            # ── Analisa ──
            atr, signal, score, detail, regime = analisa(df_m1, df_m5)

            # Tampilkan dashboard kalau ada kandidat sinyal
            if score >= 3:
                print_dashboard(score, detail)

            if signal in ("BUY", "SELL"):
                log.info(f"🔥 {signal} | Score:{score}/10 | {regime['label']} | ATR:{atr:.2f}")
                eksekusi(signal, atr, score, regime)

            time.sleep(0.5)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error(f"❌ Error: {e}", exc_info=True)
            time.sleep(5)


# ─────────────────────────────────────────────
#  BACKTEST ENGINE v3.0
# ─────────────────────────────────────────────
def _simulate(df: pd.DataFrame, spread_pts: float) -> list:
    """Backtest engine — cocok dengan logika live v3.0"""
    SP     = spread_pts * 0.01
    trades = []
    cd     = 0

    # Pre-hitung volume MA
    df = df.copy()
    df["vol_ma"] = df["volume"].rolling(20).mean()

    # MACD histogram
    macd = ta.macd(df["close"], fast=CFG.MACD_FAST, slow=CFG.MACD_SLOW, signal=CFG.MACD_SIGNAL)
    if macd is not None and not macd.empty:
        df["macd_hist"] = macd.iloc[:, 2]
    else:
        df["macd_hist"] = 0.0

    # Bollinger Bands bandwidth
    bb = ta.bbands(df["close"], length=CFG.BB_PERIOD, std=CFG.BB_STD)
    if bb is not None and not bb.empty:
        bb.columns = ["BBL", "BBM", "BBU", "BBB", "BBP"]
        df = pd.concat([df, bb], axis=1)
        df["BBB"] = df.get("BBB", pd.Series(0.05, index=df.index))
    else:
        df["BBL"] = df["close"].rolling(CFG.BB_PERIOD).mean() - 2 * df["close"].rolling(CFG.BB_PERIOD).std()
        df["BBU"] = df["close"].rolling(CFG.BB_PERIOD).mean() + 2 * df["close"].rolling(CFG.BB_PERIOD).std()
        df["BBB"] = 0.05

    df = df.dropna()

    for i in range(5, len(df)):
        row = df.iloc[i]
        p   = df.iloc[i-1]
        p2  = df.iloc[i-2]

        if cd > 0:
            cd -= 1
            continue

        a = row["atr"]
        if a < CFG.ATR_MIN:
            continue

        # Choppiness regime check (cepat)
        n_ci   = 14
        recent = df.iloc[max(0,i-n_ci):i+1]
        hl     = recent["high"].max() - recent["low"].min()
        ci_val = 100 * np.log10(recent["atr"].sum()/hl) / np.log10(n_ci) if hl > 0 and n_ci > 1 else 50
        req_score = CFG.SIDEWAYS_SCORE if ci_val > 61 else CFG.MIN_SCORE

        # ── Scoring ──
        body = max(abs(row["close"] - row["open"]), 0.0001)
        ls   = min(row["open"], row["close"]) - row["low"]
        us   = row["high"] - max(row["open"], row["close"])
        is_hammer = ls >= 1.5*body and us <= body
        is_ss     = us >= 1.5*body and ls <= body
        is_be     = (row["close"]>row["open"]) and (row["open"]<p["close"]) and (row["close"]>p["open"])
        is_bea    = (row["close"]<row["open"]) and (row["open"]>p["close"]) and (row["close"]<p["open"])

        fvg_b = (row["low"]  - p2["high"]) > (a * 0.3)
        fvg_s = (p2["low"]   - row["high"]) > (a * 0.3)
        vol_r = row["volume"] / row["vol_ma"] if row["vol_ma"] > 0 else 1.0
        rsi_ok = 42 <= row["rsi"] <= 62

        sc_b = sc_s = 0
        sig  = "W"

        if row["ema9"] > row["ema21"]:
            if fvg_b:                                              sc_b += 2
            if row["low"] <= row["ema9"]+(a*0.5) or row["low"] <= row["vwap"]+(a*0.5): sc_b += 1
            if is_hammer or is_be:                                 sc_b += 1
            if rsi_ok and p["rsi"] < row["rsi"]:                   sc_b += 1
            if p["ema9"] <= p["ema21"] and row["ema9"] > row["ema21"]: sc_b += 1
            if vol_r >= CFG.VOL_SPIKE_MULT:                        sc_b += 1
            if row["macd_hist"] > 0 and row["macd_hist"] > p["macd_hist"]: sc_b += 1
            if row["BBB"] < 0.03 or row["close"] <= row["BBL"]*1.001:      sc_b += 1
            if row["close"] > row["ema50"]:                        sc_b += 1
            if sc_b >= req_score: sig = "B"

        elif row["ema9"] < row["ema21"]:
            if fvg_s:                                              sc_s += 2
            if row["high"] >= row["ema9"]-(a*0.5) or row["high"] >= row["vwap"]-(a*0.5): sc_s += 1
            if is_ss or is_bea:                                    sc_s += 1
            if rsi_ok and p["rsi"] > row["rsi"]:                   sc_s += 1
            if p["ema9"] >= p["ema21"] and row["ema9"] < row["ema21"]: sc_s += 1
            if vol_r >= CFG.VOL_SPIKE_MULT:                        sc_s += 1
            if row["macd_hist"] < 0 and row["macd_hist"] < p["macd_hist"]: sc_s += 1
            if row["BBB"] < 0.03 or row["close"] >= row["BBU"]*0.999:      sc_s += 1
            if row["close"] < row["ema50"]:                        sc_s += 1
            if sc_s >= req_score: sig = "S"

        if sig == "W":
            continue

        tp_d = a * CFG.TP_ATR_MULT
        sl_d = a * CFG.SL_ATR_MULT
        en   = (row["close"] + SP) if sig == "B" else (row["close"] - SP)
        sl_p = (en - sl_d) if sig == "B" else (en + sl_d)
        tp_p = (en + tp_d) if sig == "B" else (en - tp_d)

        out = "TO"; pnl = 0
        for j in range(i+1, min(i+21, len(df))):
            fr = df.iloc[j]
            if sig == "B":
                if fr["low"]  <= sl_p: pnl = -sl_d; out = "SL"; break
                if fr["high"] >= tp_p: pnl =  tp_d; out = "TP"; break
            else:
                if fr["high"] >= sl_p: pnl = -sl_d; out = "SL"; break
                if fr["low"]  <= tp_p: pnl =  tp_d; out = "TP"; break
        if out == "TO":
            fc  = df.iloc[min(i+20, len(df)-1)]["close"]
            pnl = (fc - en) if sig == "B" else (en - fc)

        trades.append({"pnl": pnl, "outcome": out, "sig": sig,
                       "score": max(sc_b, sc_s), "atr": a})
        cd = 2  # cooldown lebih pendek dari v2 (3→2)

    return trades


def run_backtest(csv_path: str):
    print(Fore.YELLOW + "\n" + "═"*62)
    print("  GOLD SNIPER v3.0 — BACKTEST")
    print("═"*62)

    df = pd.read_csv(csv_path, sep="\t")
    df.columns = [c.strip("<>") for c in df.columns]
    df["DATETIME"] = pd.to_datetime(df["DATE"] + " " + df["TIME"])
    df = df.rename(columns={"OPEN":"open","HIGH":"high","LOW":"low",
                             "CLOSE":"close","TICKVOL":"volume"})
    df.set_index("DATETIME", inplace=True)
    df = df.sort_index()

    print(f"  Data  : {df.index[0]} → {df.index[-1]}")
    print(f"  Candle: {len(df)} bars M1\n")

    # Indikator
    df["ema9"]  = ta.ema(df["close"], length=9)
    df["ema21"] = ta.ema(df["close"], length=21)
    df["ema50"] = ta.ema(df["close"], length=50)
    df["rsi"]   = ta.rsi(df["close"], length=14)
    df["atr"]   = ta.atr(df["high"], df["low"], df["close"], length=14)
    try:
        df["vwap"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
    except Exception:
        df["vwap"] = df["close"].rolling(14).mean()
    df = df.dropna()

    scenarios = [
        ( 3, "🏆 Raw Spread (IC Markets)"),
        ( 5, "✅ HFM Zero / Exness Raw  "),
        (10, "⚠️  Mid Spread             "),
        (20, "🟠 Spread Sedang           "),
        (34, "❌ HFM Demo (sekarang)    "),
    ]

    print(Fore.CYAN + f"  {'Spread':>6}  {'Label':<28} {'N':>5} {'WR%':>5} {'PnL pts':>9} {'$@0.1lot':>9} {'PF':>5}")
    print("  " + "─"*72)

    best_trades = None
    for sp, label in scenarios:
        trades = _simulate(df, sp)
        if not trades:
            continue
        t     = pd.DataFrame(trades)
        n     = len(t)
        wins  = len(t[t.outcome=="TP"])
        wr    = wins/n*100
        pnl   = t.pnl.sum()
        ls    = abs(t[t.outcome=="SL"].pnl.sum())
        ws    = t[t.outcome=="TP"].pnl.sum()
        pf    = ws/ls if ls > 0 else 99
        dol   = pnl * (CFG.LOT / 0.01)   # $@current lot setting
        col   = Fore.GREEN if pnl > 0 else Fore.RED
        print(col + f"  {sp:>5}pt  {label:<28} {n:>5} {wr:>4.0f}% {pnl:>+9.2f} {dol:>+9.2f} {pf:>5.2f}")
        if sp == 3:
            best_trades = t

    print("  " + "─"*72)

    if best_trades is not None:
        n  = len(best_trades)
        wr = len(best_trades[best_trades.outcome=="TP"])/n*100
        avg_score = best_trades["score"].mean()
        print(Fore.YELLOW + f"""
  📊 DETAIL Raw Spread (3pt):
     Total trades  : {n} ({n/8:.1f}/hari)
     Win Rate      : {wr:.1f}%
     Avg score/10  : {avg_score:.1f}
     Lot sekarang  : {CFG.LOT}
     Proyeksi/hari : ${best_trades.pnl.sum()/8*(CFG.LOT/0.01):+.2f}
     Proyeksi/bulan: ${best_trades.pnl.sum()/8*22*(CFG.LOT/0.01):+.0f}""")
        best_trades.to_csv("backtest_v3_results.csv", index=False)
        print(Fore.GREEN + "  📄 Tersimpan: backtest_v3_results.csv")


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Gold Sniper v3.0")
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--file", type=str,
                        default="XAUUSD_M1_202603020100_202603092029.csv")
    args = parser.parse_args()

    print(Fore.YELLOW + """
╔══════════════════════════════════════════════════════════╗
║   ⚡ GOLD SNIPER v3.0 — Smarter | Faster | Profitable   ║
║   Score 0-10 | M5 Filter | Volume | MACD | BB           ║
╚══════════════════════════════════════════════════════════╝""")

    if args.backtest:
        if not os.path.exists(args.file):
            print(Fore.RED + f"❌ File tidak ditemukan: {args.file}")
            sys.exit(1)
        run_backtest(args.file)
        return

    if not connect_mt5():
        sys.exit(1)

    print(Fore.GREEN + "  ✅ Bot aktif! Ctrl+C untuk stop.\n")
    try:
        bot_loop()
    except KeyboardInterrupt:
        pass
    finally:
        mt5.shutdown()
        print(Fore.GREEN + "\n  👋 Bot dimatikan. Log: gold_sniper_v3.log")


if __name__ == "__main__":
    main()