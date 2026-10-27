"""
M1 XAUUSD Quant Sniper Engine (V5.2 - Adaptive Scalper Edition)
High-Frequency Scalper: Liquidity Sweep, Compression Breakout, Flowing ATR Trailing
0% Lagging Indicators | 100% Price Action, Order Flow & Flowing Trailing Stop
V5.2 Fixes (from V5.1):
  1. ATR in main loop now uses True Range (consistent with signal engine)
  2. Stagnation timer uses bar count instead of wall clock
  3. Trade entry bar tracking for accurate stagnation measurement
Platform: Python 3.12 + MetaTrader 5 on Windows (ZenBook)
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import logging
import time
import os
import csv
import sys
import psutil
from datetime import datetime, timezone, timedelta

# Import configuration
try:
    import m1_config as config
except ImportError:
    import live_bot.m1_config as config

# Setup Logging
os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("M1Sniper")


# ====================================================================
# COMPONENT 1: PURE PRICE ACTION & ORDER FLOW SIGNAL ENGINE (0% EMA)
# ====================================================================
class M1SignalEngine:
    """
    Evaluates Pure Price Action & Order Flow on M1 Candle Close:
    100% Lag-Free: No Moving Averages, No Delayed Filters.
    Mode 1: Liquidity Sweep Reversal (5-bar Stop Hunt Rejection)
    Mode 2: Inside Bar / Compression Breakout (Controlled Squeeze & Ignite)
    Mode 3: Pinbar Rejection at Extremum (Hammer / Shooting Star)
    Anti-Pucuk Guard: Blocks parabolic exhaustion rockets without wick rejection
    """

    @staticmethod
    def evaluate(rates_df: pd.DataFrame) -> dict:
        """
        Input: DataFrame of last 70+ M1 bars, already excluding the unclosed bar.
        Output: dict with buy_score, sell_score, atr14, and reasons.
        """
        if len(rates_df) < 65:
            return {"valid": False, "reason": "Insufficient bars"}

        df = rates_df.copy()
        c = df["close"]
        h = df["high"]
        l = df["low"]
        o = df["open"]
        vol = df["tick_volume"]

        # 1. Price action features
        rng = h - l
        body = (c - o).abs()
        direction = np.where(c > o, 1, np.where(c < o, -1, 0))

        # 2. Volatility & Volume
        prev_close = c.shift(1)
        tr = np.maximum(rng, np.maximum((h - prev_close).abs(), (l - prev_close).abs()))
        atr14 = tr.rolling(14).mean().iloc[-1]
        vol_sma20 = vol.rolling(20).mean().clip(lower=1e-5)
        vol_ratio = (vol / vol_sma20).iloc[-1]

        # Filter: Skip if market is dead (< $1.00 ATR)
        if atr14 < config.MIN_ATR_FILTER:
            return {"valid": False, "reason": f"Dead market (ATR ${atr14:.2f} < ${config.MIN_ATR_FILTER:.2f})"}

        # 3. Extremums for Liquidity Sweeps (5 bars lookback)
        hh5 = h.rolling(5).max().shift(1).iloc[-1]
        ll5 = l.rolling(5).min().shift(1).iloc[-1]

        # 4. Extreme Momentum Guard (RSI7 for parabolic dump/pump)
        delta = c.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        ag7 = gain.ewm(alpha=1/7, min_periods=7).mean()
        al7 = loss.ewm(alpha=1/7, min_periods=7).mean()
        rsi7 = (100.0 - (100.0 / (1.0 + ag7 / al7.clip(lower=1e-10)))).iloc[-1]

        cur_c = c.iloc[-1]
        cur_h = h.iloc[-1]
        cur_l = l.iloc[-1]
        cur_o = o.iloc[-1]
        cur_rng = rng.iloc[-1]
        cur_body = body.iloc[-1]
        cur_dir = direction[-1]

        lower_wick = min(cur_o, cur_c) - cur_l
        upper_wick = cur_h - max(cur_o, cur_c)

        # Prior bar metrics (for Inside Bar & Breakout detection)
        prev_h = h.iloc[-2]
        prev_l = l.iloc[-2]
        prev2_h = h.iloc[-3]
        prev2_l = l.iloc[-3]
        prev_rng = rng.iloc[-2]
        was_inside = (prev_h <= prev2_h) and (prev_l >= prev2_l)
        was_compressed = prev_rng < (atr14 * 0.70)

        buy_score = 0
        sell_score = 0
        buy_reasons = []
        sell_reasons = []

        # =================================================================
        # PATTERN 1: LIQUIDITY SWEEP & WICK REVERSAL (SMART MONEY SCALP)
        # =================================================================
        # BUY: Swept 5-bar low, rejected and closed green above that low!
        if cur_l < ll5 and cur_c > ll5 and cur_dir == 1 and lower_wick >= cur_body * 0.8:
            buy_score += 2
            buy_reasons.append("Sweep Low Reversal")
            if lower_wick > atr14 * 0.30:
                buy_score += 1
                buy_reasons.append("Strong Sweep Wick")

        # SELL: Swept 5-bar high, rejected and closed red below that high!
        if cur_h > hh5 and cur_c < hh5 and cur_dir == -1 and upper_wick >= cur_body * 0.8:
            sell_score += 2
            sell_reasons.append("Sweep High Reversal")
            if upper_wick > atr14 * 0.30:
                sell_score += 1
                sell_reasons.append("Strong Sweep Wick")

        # =================================================================
        # PATTERN 2: COMPRESSION BREAKOUT (ANTI-PUCUK PROTECTED)
        # =================================================================
        max_ext = atr14 * getattr(config, 'COMPRESSION_MAX_EXTENSION_ATR', 0.35)

        # BUY: Prior bar compressed/inside, current breaks high WITHOUT over-extending
        if (was_inside or was_compressed) and cur_c > prev_h and cur_dir == 1:
            dist_past = cur_c - prev_h
            no_upper_rejection = upper_wick <= max(cur_body * 0.50, 0.20)
            healthy_range = (cur_rng <= atr14 * 1.35)

            if dist_past <= max_ext and no_upper_rejection and healthy_range:
                buy_score += 2
                buy_reasons.append("Compression Breakout Bull")
            elif dist_past > max_ext:
                buy_reasons.append(f"BLOCKED: Over-extended Breakout (+${dist_past:.2f})")

        # SELL: Prior bar compressed/inside, current breaks low WITHOUT over-extending
        if (was_inside or was_compressed) and cur_c < prev_l and cur_dir == -1:
            dist_past = prev_l - cur_c
            no_lower_rejection = lower_wick <= max(cur_body * 0.50, 0.20)
            healthy_range = (cur_rng <= atr14 * 1.35)

            if dist_past <= max_ext and no_lower_rejection and healthy_range:
                sell_score += 2
                sell_reasons.append("Compression Breakout Bear")
            elif dist_past > max_ext:
                sell_reasons.append(f"BLOCKED: Over-extended Breakdown (-${dist_past:.2f})")

        # =================================================================
        # PATTERN 3: HAMMER / SHOOTING STAR PINBAR REJECTION
        # =================================================================
        # BUY: Hammer (massive lower wick, tiny upper wick)
        if lower_wick > cur_body * 2.0 and lower_wick > atr14 * 0.35 and upper_wick < cur_body * 0.6:
            buy_score += 2
            buy_reasons.append("Hammer Pinbar Rejection")

        # SELL: Shooting Star (massive upper wick, tiny lower wick)
        if upper_wick > cur_body * 2.0 and upper_wick > atr14 * 0.35 and lower_wick < cur_body * 0.6:
            sell_score += 2
            sell_reasons.append("Shooting Star Rejection")

        # =================================================================
        # VOLUME CONFIRMATION (ORDER FLOW PUSH)
        # =================================================================
        if vol_ratio > 1.2:
            if buy_score > 0:
                buy_score += 1
                buy_reasons.append(f"Volume Push ({vol_ratio:.1f}x)")
            if sell_score > 0:
                sell_score += 1
                sell_reasons.append(f"Volume Push ({vol_ratio:.1f}x)")

        # =================================================================
        # ANTI-PUCUK & CLIMAX EXHAUSTION GUARD
        # =================================================================
        # Block entry if current candle is a giant solid marubozu with zero wick (FOMO rocket)
        if getattr(config, 'CLIMAX_FILTER_ENABLED', True):
            # Exhaustion rocket guard: bar > 1.5x ATR with no wick means buying at the tip of the spear!
            if cur_rng > atr14 * 1.5:
                if cur_dir == 1 and lower_wick < cur_rng * 0.15:
                    buy_score = 0
                    buy_reasons.append("BLOCKED: Marubozu Rocket (Anti-Pucuk)")
                elif cur_dir == -1 and upper_wick < cur_rng * 0.15:
                    sell_score = 0
                    sell_reasons.append("BLOCKED: Marubozu Plunge (Anti-Dasar)")

            # Extreme RSI overbought / oversold
            if rsi7 > getattr(config, 'RSI_OVERBOUGHT_BLOCK', 85.0):
                buy_score = 0
                buy_reasons.append(f"BLOCKED: Extreme Overbought (RSI7 {rsi7:.1f})")
            elif rsi7 < getattr(config, 'RSI_OVERSOLD_BLOCK', 15.0):
                sell_score = 0
                sell_reasons.append(f"BLOCKED: Extreme Oversold (RSI7 {rsi7:.1f})")

        return {
            "valid": True,
            "atr14": float(atr14),
            "close_price": float(cur_c),
            "rsi7": float(rsi7),
            "buy_score": buy_score,
            "sell_score": sell_score,
            "buy_reasons": buy_reasons,
            "sell_reasons": sell_reasons,
        }


# ====================================================================
# COMPONENT 2: RISK & SESSION MANAGER
# ====================================================================
class M1RiskManager:
    """Guards capital: daily circuit breakers, session windows, dynamic sizing, news freeze."""

    def __init__(self):
        self.session_start_equity = None
        self.current_session_date = None
        self.recent_losses = []
        self.win_streak_cooldown_until_bar = None
        self.bar_counter = 0

    def check_session_active(self) -> bool:
        """Verify if current time falls into allowed trading window (WIB)."""
        if not config.ACTIVE_SESSION_ONLY:
            return True

        now_wib = datetime.now(timezone.utc) + timedelta(hours=7)
        now_time = now_wib.time()

        for win in config.SESSION_WINDOWS_WIB:
            st = datetime.strptime(win["start"], "%H:%M").time()
            et = datetime.strptime(win["end"], "%H:%M").time()
            if st <= et:
                if st <= now_time < et:
                    return True
            else:
                if now_time >= st or now_time < et:
                    return True
        return False

    def check_news_freeze(self) -> tuple[bool, str]:
        """Block trading inside the freeze window around configured high-impact USD events."""
        if not getattr(config, 'NEWS_FREEZE_ENABLED', False):
            return True, "OK"

        events = getattr(config, 'NEWS_EVENTS_UTC', [])
        if not events:
            return True, "OK"

        now_utc = datetime.now(timezone.utc)
        before = timedelta(minutes=getattr(config, 'NEWS_FREEZE_MINUTES_BEFORE', 15))
        after = timedelta(minutes=getattr(config, 'NEWS_FREEZE_MINUTES_AFTER', 15))

        for ev in events:
            try:
                ev_time = datetime.strptime(ev["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            except (KeyError, ValueError):
                continue
            if ev_time - before <= now_utc <= ev_time + after:
                return False, f"NEWS FREEZE: {ev.get('label', 'high-impact event')} at {ev_time}"
        return True, "OK"

    def check_win_streak_cooldown(self) -> tuple[bool, str]:
        """Pause N bars after closing a profitable runner."""
        if self.win_streak_cooldown_until_bar is None:
            return True, "OK"
        if self.bar_counter < self.win_streak_cooldown_until_bar:
            return False, f"WIN-STREAK COOLDOWN: {self.win_streak_cooldown_until_bar - self.bar_counter} bars remaining"
        self.win_streak_cooldown_until_bar = None
        return True, "OK"

    def trigger_win_streak_cooldown(self):
        bars = getattr(config, 'COOLDOWN_AFTER_WIN_STREAK_BARS', 0)
        if bars > 0:
            self.win_streak_cooldown_until_bar = self.bar_counter + bars
            logger.info(f"[WIN-STREAK COOLDOWN] Pausing entries for {bars} bars after profitable close")

    def check_safety(self, account_info: dict, current_spread: float) -> tuple[bool, str]:
        """Verify circuit breaker, spread ceiling, news freeze, and anti-whipsaw cooldown."""
        now_utc = datetime.now(timezone.utc)
        today = (now_utc + timedelta(hours=7)).date()

        if self.current_session_date != today:
            self.current_session_date = today
            self.session_start_equity = account_info["equity"]
            self.recent_losses.clear()
            logger.info(f"[SESSION NEW] New session day: {today} | Baseline Equity: {self.session_start_equity}")

        if current_spread > config.MAX_SPREAD_CEILING:
            return False, f"Spread ${current_spread:.2f} > ceiling ${config.MAX_SPREAD_CEILING:.2f}"

        max_allowed_loss = self.session_start_equity * (config.DAILY_LOSS_LIMIT_PCT / 100.0)
        current_loss = self.session_start_equity - account_info["equity"]
        if current_loss >= max_allowed_loss:
            return False, f"CIRCUIT BREAKER: Daily loss -{current_loss:.2f} >= max -{max_allowed_loss:.2f} (HALTED)"

        cutoff = now_utc - timedelta(minutes=config.COOLDOWN_MINUTES)
        self.recent_losses = [t for t in self.recent_losses if t > cutoff]
        if len(self.recent_losses) >= config.ANTI_WHIPSAW_LOSSES:
            return False, f"ANTI-WHIPSAW COOLDOWN: {len(self.recent_losses)} consecutive losses in 15m"

        news_ok, news_reason = self.check_news_freeze()
        if not news_ok:
            return False, news_reason

        streak_ok, streak_reason = self.check_win_streak_cooldown()
        if not streak_ok:
            return False, streak_reason

        return True, "OK"

    def record_loss(self):
        self.recent_losses.append(datetime.now(timezone.utc))

    def calculate_lot(self, equity: float, score: int) -> float:
        """
        Dynamic sizing: Base lot scaled by equity, multiplied by conviction score.
        Score 2 = 1x Base, Score 3 = 2x Base, Score >= 4 = 3x Base.
        """
        if getattr(config, 'FIXED_LOT_MODE', False):
            mult = 1 if score == config.MIN_SCORE_ENTRY else (2 if score == config.HIGH_CONVICTION_SCORE else 3)
            return round(config.TEST_LOT_SIZE * mult, 2)

        base_unit = max(config.MIN_LOT, round((equity / 312.5) * 0.01, 2))

        multiplier = 1
        if score >= config.ULTRA_SCORE:
            multiplier = 3
        elif score >= config.HIGH_CONVICTION_SCORE:
            multiplier = 2

        total_lot = round(base_unit * multiplier, 2)
        total_lot = max(config.MIN_LOT, min(config.MAX_LOT_PER_ORDER, total_lot))
        return total_lot


# ====================================================================
# COMPONENT 3: FLOWING TRAILING STOP & EXECUTION ENGINE (EA RAZOR STYLE)
# ====================================================================
class M1SniperEngine:
    """Core MT5 execution engine managing positions, adaptive SL, and flowing trailing stops."""

    def __init__(self):
        self.signal_engine = M1SignalEngine()
        self.risk_mgr = M1RiskManager()
        self.be_locked_tickets = set()
        self.last_traded_bar_time = None
        self.trade_entry_bar = {}  # ticket -> bar_counter at entry
        self._ensure_trade_log_header()

    # ---------------- Singleton Instance Guard ----------------

    def acquire_process_lock(self) -> bool:
        """Ensure only one instance runs across the entire system."""
        lock_file = getattr(config, 'LOCK_FILE', r"C:\Users\asuszenbook\forex_scalper\m1_sniper.lock")
        my_pid = os.getpid()

        if os.path.exists(lock_file):
            try:
                with open(lock_file, "r") as f:
                    content = f.read().strip()
                if content:
                    old_pid = int(content)
                    if old_pid != my_pid and psutil.pid_exists(old_pid):
                        proc = psutil.Process(old_pid)
                        if "python" in proc.name().lower():
                            logger.error(f"[SINGLETON LOCK] Instance already active with PID {old_pid}! Aborting.")
                            return False
            except Exception as e:
                logger.debug(f"[LOCK] Read lock exception (ignoring): {e}")

        try:
            os.makedirs(os.path.dirname(lock_file), exist_ok=True)
            with open(lock_file, "w") as f:
                f.write(str(my_pid))
            logger.info(f"[SINGLETON LOCK] Acquired lock for PID {my_pid}")
            return True
        except Exception as e:
            logger.error(f"[LOCK] Failed to acquire lock file: {e}")
            return False

    def release_process_lock(self):
        """Release the file lock on exit."""
        lock_file = getattr(config, 'LOCK_FILE', r"C:\Users\asuszenbook\forex_scalper\m1_sniper.lock")
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
                logger.info("[SINGLETON LOCK] Released process lock")
        except OSError:
            pass

    # ---------------- Connection & Reconnection ----------------

    def connect(self) -> bool:
        """Initialize connection to MT5 terminal."""
        if not mt5.initialize(
            path=config.MT5_PATH,
            login=config.MT5_LOGIN,
            password=config.MT5_PASSWORD,
            server=config.MT5_SERVER,
            timeout=30000
        ):
            logger.error(f"MT5 Init failed: {mt5.last_error()}")
            return False

        acc = mt5.account_info()
        sym = mt5.symbol_info(config.SYMBOL)
        if acc is None or sym is None:
            logger.error("MT5 connected but account_info/symbol_info returned None")
            return False
        if not mt5.symbol_select(config.SYMBOL, True):
            logger.error(f"Cannot select {config.SYMBOL}")
            return False

        logger.info(
            f"[MT5 READY] Server: {acc.server} | Login: {acc.login} | "
            f"Balance: {acc.balance} {acc.currency} | Leverage: 1:{acc.leverage} | "
            f"Symbol: {config.SYMBOL} (Bid: {sym.bid}, Ask: {sym.ask})"
        )
        return True

    def ensure_connected(self) -> bool:
        """Check live connection health; attempt bounded reconnection if dropped."""
        acc = mt5.account_info()
        if acc is not None:
            return True

        logger.warning("[CONNECTION LOST] account_info() returned None. Attempting reconnect...")
        mt5.shutdown()

        max_retries = getattr(config, 'RECONNECT_MAX_RETRIES', 5)
        delay = getattr(config, 'RECONNECT_DELAY_SEC', 10)

        for attempt in range(1, max_retries + 1):
            logger.info(f"[RECONNECT] Attempt {attempt}/{max_retries}...")
            if self.connect():
                logger.info("[RECONNECT] Success, resuming engine loop")
                return True
            time.sleep(delay)

        logger.error(f"[RECONNECT] Failed after {max_retries} attempts. Engine halting.")
        return False

    # ---------------- Position Management ----------------

    def get_open_sniper_positions(self) -> list:
        """Retrieve all active positions created by this bot."""
        positions = mt5.positions_get(symbol=config.SYMBOL)
        if positions is None:
            return []
        return [p._asdict() for p in positions if p.magic == config.MAGIC_NUMBER]

    def cleanup_be_locked_tickets(self, open_positions: list):
        """Drop tickets from the BE-locked set that are no longer open."""
        open_tickets = {p["ticket"] for p in open_positions}
        stale = self.be_locked_tickets - open_tickets
        if stale:
            self.be_locked_tickets -= stale
            logger.debug(f"[CLEANUP] Removed {len(stale)} stale ticket(s) from BE-locked set")

    # ---------------- Adaptive Stop Loss Calculation ----------------

    def calculate_adaptive_sl(self, direction: str, tick, df_closed: pd.DataFrame, atr: float) -> tuple[float, float, str]:
        """
        Computes structural + volatility-adapted SL:
        1. Structural anchor: Swing low (BUY) or Swing high (SELL) of last N bars.
        2. Buffer: +0.15x ATR beyond structural point.
        3. Clamped by [SL_MIN_DOLLAR, SL_MAX_DOLLAR] and [0.45x ATR, 0.85x ATR].
        Returns: (sl_price, sl_dist, description)
        """
        if not getattr(config, 'ADAPTIVE_SL_ENABLED', True):
            hard_sl_dist = atr * config.HARD_SL_ATR_MULT
            if direction == "BUY":
                return round(tick.bid - hard_sl_dist, 2), hard_sl_dist, f"Fixed ATR SL (${hard_sl_dist:.2f})"
            else:
                return round(tick.ask + hard_sl_dist, 2), hard_sl_dist, f"Fixed ATR SL (${hard_sl_dist:.2f})"

        lookback = getattr(config, 'SL_SWING_LOOKBACK', 3)
        buf = atr * getattr(config, 'SL_BUFFER_ATR', 0.15)
        min_flr = getattr(config, 'SL_MIN_DOLLAR', 1.10)
        max_cap = getattr(config, 'SL_MAX_DOLLAR', 2.80)

        recent_bars = df_closed.iloc[-lookback:]

        if direction == "BUY":
            swing_low = recent_bars["low"].min()
            structural_dist = tick.bid - (swing_low - buf)
            atr_dist = atr * config.HARD_SL_ATR_MULT

            raw_dist = max(structural_dist, atr_dist)
            clamped_min = max(min_flr, atr * 0.45)
            clamped_max = min(max_cap, atr * 0.85)
            sl_dist = float(np.clip(raw_dist, clamped_min, clamped_max))
            sl_price = round(tick.bid - sl_dist, 2)
            desc = f"Adaptive SL: ${sl_dist:.2f} (SwingL {swing_low:.2f} - buf {buf:.2f})"
        else:
            swing_high = recent_bars["high"].max()
            structural_dist = (swing_high + buf) - tick.ask
            atr_dist = atr * config.HARD_SL_ATR_MULT

            raw_dist = max(structural_dist, atr_dist)
            clamped_min = max(min_flr, atr * 0.45)
            clamped_max = min(max_cap, atr * 0.85)
            sl_dist = float(np.clip(raw_dist, clamped_min, clamped_max))
            sl_price = round(tick.ask + sl_dist, 2)
            desc = f"Adaptive SL: ${sl_dist:.2f} (SwingH {swing_high:.2f} + buf {buf:.2f})"

        return sl_price, sl_dist, desc

    # ---------------- Trend Reversal Profit Exit ----------------

    def check_reversal_exits(self, eval_res: dict, current_atr: float):
        """
        Fast-In Fast-Out: If trade is currently profitable and opposite signal appears,
        cut position immediately at market to secure profits before momentum reverses.
        """
        if not getattr(config, 'REVERSAL_EXIT_ENABLED', True):
            return

        positions = self.get_open_sniper_positions()
        if not positions:
            return

        sym_info = mt5.symbol_info(config.SYMBOL)
        if sym_info is None:
            return

        bid = sym_info.bid
        ask = sym_info.ask
        min_profit_threshold = current_atr * getattr(config, 'REVERSAL_MIN_PROFIT_ATR', 0.20)

        buy_score = eval_res.get("buy_score", 0)
        sell_score = eval_res.get("sell_score", 0)

        for pos in positions:
            ticket = pos["ticket"]
            open_price = pos["price_open"]
            pos_type = pos["type"]

            if pos_type == mt5.ORDER_TYPE_BUY:
                current_profit = bid - open_price
                is_profitable = (current_profit >= min_profit_threshold) or (ticket in self.be_locked_tickets)
                if is_profitable and sell_score >= config.MIN_SCORE_ENTRY:
                    reasons = eval_res.get("sell_reasons", [])
                    logger.info(
                        f"[REVERSAL EXIT] Cutting BUY #{ticket} @ {bid} (Profit: +${current_profit:.2f}) "
                        f"due to opposite SELL signal (Score: {sell_score}, Reasons: {', '.join(reasons)})"
                    )
                    self.close_position(ticket, reason="reversal_exit")

            elif pos_type == mt5.ORDER_TYPE_SELL:
                current_profit = open_price - ask
                is_profitable = (current_profit >= min_profit_threshold) or (ticket in self.be_locked_tickets)
                if is_profitable and buy_score >= config.MIN_SCORE_ENTRY:
                    reasons = eval_res.get("buy_reasons", [])
                    logger.info(
                        f"[REVERSAL EXIT] Cutting SELL #{ticket} @ {ask} (Profit: +${current_profit:.2f}) "
                        f"due to opposite BUY signal (Score: {buy_score}, Reasons: {', '.join(reasons)})"
                    )
                    self.close_position(ticket, reason="reversal_exit")

    # ---------------- Trailing Stop Execution ----------------

    def manage_trailing_stops(self, current_atr: float):
        """
        FLOWING TRAILING ENGINE (EA RAZOR STYLE):
        1. Fast BE Lock: +0.15x ATR + spread move -> immediately lock Entry + Spread + $0.08 (Risk-Free).
        2. Continuous Flowing Trail: SL continuously trails 0.15x ATR behind price.
        3. Profit Choke: If profit > 0.8x ATR, tighten trail to 0.07x ATR to secure mega-cuan.
        4. Fast-In Fast-Out Stagnation: Force close if position stalled > N bars without profit.
        """
        positions = self.get_open_sniper_positions()
        self.cleanup_be_locked_tickets(positions)
        if not positions:
            return

        sym_info = mt5.symbol_info(config.SYMBOL)
        if sym_info is None:
            return

        bid = sym_info.bid
        ask = sym_info.ask
        point = sym_info.point

        spread = round(ask - bid, 2)
        quick_be_dist = (current_atr * config.QUICK_BE_TRIGGER_ATR) + spread
        normal_trail_gap = current_atr * config.TRAILING_DISTANCE_ATR
        choke_trail_gap = current_atr * getattr(config, 'CHOKE_TRAILING_ATR', 0.07)
        choke_threshold = current_atr * getattr(config, 'PROFIT_CHOKE_ATR', 0.80)
        be_pips = config.BE_LOCK_PIPS * point

        for pos in positions:
            ticket = pos["ticket"]
            open_price = pos["price_open"]
            pos_type = pos["type"]
            current_sl = pos["sl"]
            current_tp = pos.get("tp", 0.0)

            # Stagnation exit: Fast-In Fast-Out (bar-count based, not wall clock)
            entry_bar = self.trade_entry_bar.get(ticket)
            if entry_bar is not None:
                bars_held = self.risk_mgr.bar_counter - entry_bar
                if bars_held >= getattr(config, 'STAGNATION_MAX_BARS', 4) and ticket not in self.be_locked_tickets:
                    logger.info(f"[STAGNATION] Fast-Out closing #{ticket} (held {bars_held} bars without BE)")
                    self.close_position(ticket, reason="stagnation")
                    self.trade_entry_bar.pop(ticket, None)
                    continue

            if pos_type == mt5.ORDER_TYPE_BUY:
                current_profit_dist = bid - open_price

                # 1. Quick Break-Even Lock (Risk-Free Instant)
                if current_profit_dist >= quick_be_dist and ticket not in self.be_locked_tickets:
                    be_sl = round(open_price + spread + be_pips, 2)
                    if be_sl > current_sl:
                        if self.modify_sl(ticket, be_sl, tp=current_tp):
                            self.be_locked_tickets.add(ticket)
                            logger.info(f"[BE LOCK] #{ticket} BUY reached +${current_profit_dist:.2f} -> SL locked Risk-Free at {be_sl}")

                # 2. Continuous Flowing Trailing (Unlocks immediately upon BE!)
                if ticket in self.be_locked_tickets:
                    trail_gap = choke_trail_gap if current_profit_dist >= choke_threshold else normal_trail_gap
                    target_sl = round(bid - trail_gap, 2)

                    if target_sl > current_sl and target_sl >= (open_price + be_pips):
                        if self.modify_sl(ticket, target_sl, tp=current_tp):
                            choke_tag = " [CHOKE]" if current_profit_dist >= choke_threshold else ""
                            logger.info(f"[TRAIL{choke_tag}] #{ticket} BUY SL trailed to {target_sl} (Profit: +${current_profit_dist:.2f})")

            elif pos_type == mt5.ORDER_TYPE_SELL:
                current_profit_dist = open_price - ask

                # 1. Quick Break-Even Lock (Risk-Free Instant)
                if current_profit_dist >= quick_be_dist and ticket not in self.be_locked_tickets:
                    be_sl = round(open_price - spread - be_pips, 2)
                    if current_sl == 0.0 or be_sl < current_sl:
                        if self.modify_sl(ticket, be_sl, tp=current_tp):
                            self.be_locked_tickets.add(ticket)
                            logger.info(f"[BE LOCK] #{ticket} SELL reached +${current_profit_dist:.2f} -> SL locked Risk-Free at {be_sl}")

                # 2. Continuous Flowing Trailing (Unlocks immediately upon BE!)
                if ticket in self.be_locked_tickets:
                    trail_gap = choke_trail_gap if current_profit_dist >= choke_threshold else normal_trail_gap
                    target_sl = round(ask + trail_gap, 2)

                    if (current_sl == 0.0 or target_sl < current_sl) and target_sl <= (open_price - be_pips):
                        if self.modify_sl(ticket, target_sl, tp=current_tp):
                            choke_tag = " [CHOKE]" if current_profit_dist >= choke_threshold else ""
                            logger.info(f"[TRAIL{choke_tag}] #{ticket} SELL SL trailed to {target_sl} (Profit: +${current_profit_dist:.2f})")

    def modify_sl(self, ticket: int, new_sl: float, tp: float = 0.0) -> bool:
        """Send robust SL modification request to MT5, preserving existing TP by default."""
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": config.SYMBOL,
            "position": ticket,
            "sl": round(new_sl, 2),
            "tp": round(tp, 2),
            "magic": config.MAGIC_NUMBER
        }
        res = mt5.order_send(req)
        if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        else:
            err_msg = res.comment if res else str(mt5.last_error())
            logger.error(f"[SL FAILED] Could not modify SL for #{ticket} to {new_sl}: {err_msg}")
            return False

    def close_position(self, ticket: int, reason: str = "manual") -> bool:
        """Close an open position at current market price."""
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        pos = positions[0]
        sym = pos.symbol
        lot = pos.volume
        pos_type = pos.type
        open_price = pos.price_open

        tick = mt5.symbol_info_tick(sym)
        close_price = tick.bid if pos_type == mt5.ORDER_TYPE_BUY else tick.ask
        close_action = mt5.ORDER_TYPE_SELL if pos_type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": lot,
            "type": close_action,
            "position": ticket,
            "price": close_price,
            "magic": config.MAGIC_NUMBER,
            "comment": f"M1_V52_{reason[:10]}",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            pnl = (close_price - open_price) if pos_type == mt5.ORDER_TYPE_BUY else (open_price - close_price)
            logger.info(f"[CLOSED] Position #{ticket} closed at {close_price} ({reason}) | PnL dist: {pnl:.2f}")

            if pnl < 0:
                self.risk_mgr.record_loss()
            elif pnl > 0 and ticket in self.be_locked_tickets:
                self.risk_mgr.trigger_win_streak_cooldown()

            self.log_trade_exit(ticket, close_price, pnl, reason)
            self.be_locked_tickets.discard(ticket)
            self.trade_entry_bar.pop(ticket, None)
            return True
        return False

    # ---------------- Trade Journaling ----------------

    def _ensure_trade_log_header(self):
        path = getattr(config, 'TRADE_LOG_CSV', None)
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            try:
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "timestamp_utc", "event", "ticket", "direction", "lot",
                        "price", "sl", "atr", "score", "reasons", "pnl_dist"
                    ])
            except OSError as e:
                logger.error(f"[CSV INIT FAILED] {e}")

    def log_trade_entry(self, ticket, direction, lot, price, sl, atr, score, reasons):
        path = getattr(config, 'TRADE_LOG_CSV', None)
        if not path:
            return
        try:
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now(timezone.utc).isoformat(), "ENTRY", ticket, direction,
                    lot, price, sl, round(atr, 2), score, "; ".join(reasons), ""
                ])
        except OSError as e:
            logger.error(f"[CSV WRITE FAILED] {e}")

    def log_trade_exit(self, ticket, close_price, pnl, reason):
        path = getattr(config, 'TRADE_LOG_CSV', None)
        if not path:
            return
        try:
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now(timezone.utc).isoformat(), f"EXIT:{reason}", ticket, "",
                    "", close_price, "", "", "", "", round(pnl, 2)
                ])
        except OSError as e:
            logger.error(f"[CSV WRITE FAILED] {e}")

    # ---------------- Order Execution ----------------

    def execute_order(self, direction: str, lot: float, df_closed: pd.DataFrame, atr: float, score: int, reasons: list) -> bool:
        """Open a new market order with initial adaptive structural stop loss."""
        tick = mt5.symbol_info_tick(config.SYMBOL)
        if tick is None:
            logger.error("[ORDER FAILED] symbol_info_tick returned None")
            return False

        sl_price, sl_dist, sl_desc = self.calculate_adaptive_sl(direction, tick, df_closed, atr)

        if direction == "BUY":
            price = tick.ask
            order_type = mt5.ORDER_TYPE_BUY
        else:
            price = tick.bid
            order_type = mt5.ORDER_TYPE_SELL

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": config.SYMBOL,
            "volume": lot,
            "type": order_type,
            "price": price,
            "sl": sl_price,
            "deviation": 20,
            "magic": config.MAGIC_NUMBER,
            "comment": f"M1_V52|S{score}",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(
                f"[FIRED] {direction} {lot} {config.SYMBOL} @ {price} | "
                f"SL: {sl_price} ({sl_desc}) | Score: {score} | "
                f"Reasons: {', '.join(reasons)}"
            )
            self.trade_entry_bar[res.order] = self.risk_mgr.bar_counter
            self.log_trade_entry(res.order, direction, lot, price, sl_price, atr, score, reasons)
            return True
        else:
            logger.error(f"[ORDER FAILED] Error: {res.comment if res else mt5.last_error()}")
            return False

    # ---------------- Main Loop ----------------

    def run(self):
        """Main real-time loop synchronizing to M1 candle close."""
        logger.info("[START] M1 XAUUSD Quant Sniper Engine V5.2 (Adaptive Scalper Edition) Initiated")

        # 0. Singleton Lock Check
        if not self.acquire_process_lock():
            return

        if not self.connect():
            self.release_process_lock()
            return

        last_bar_time = None

        try:
            while True:
                try:
                    # 1. Connection health check with bounded reconnection
                    if not self.ensure_connected():
                        logger.error("[HALT] Could not restore MT5 connection. Stopping engine.")
                        break

                    acc_raw = mt5.account_info()
                    sym = mt5.symbol_info(config.SYMBOL)
                    if acc_raw is None or sym is None:
                        time.sleep(2)
                        continue
                    acc = acc_raw._asdict()
                    spread_dollar = round(sym.ask - sym.bid, 2)

                    # 2. Fetch rates for M1 and manage open positions
                    rates = mt5.copy_rates_from_pos(config.SYMBOL, mt5.TIMEFRAME_M1, 0, 80)
                    if rates is None or len(rates) < 65:
                        time.sleep(1)
                        continue

                    df_rates = pd.DataFrame(rates)
                    df_rates["datetime"] = pd.to_datetime(df_rates["time"], unit="s")
                    df_closed = df_rates.iloc[:-1]  # Exclude the still-forming bar
                    latest_closed_bar = df_closed.iloc[-1]
                    bar_time = latest_closed_bar["datetime"]

                    # Continuous trailing stops (True Range = max(H-L, |H-prevC|, |L-prevC|))
                    _prev_c = df_closed["close"].shift(1)
                    _rng = df_closed["high"] - df_closed["low"]
                    _tr = np.maximum(_rng, np.maximum((df_closed["high"] - _prev_c).abs(), (df_closed["low"] - _prev_c).abs()))
                    cur_atr = _tr.rolling(14).mean().iloc[-1]
                    self.manage_trailing_stops(current_atr=cur_atr)

                    # 3. Check for New Bar Event
                    if bar_time != last_bar_time:
                        last_bar_time = bar_time
                        self.risk_mgr.bar_counter += 1

                        time.sleep(config.CANDLE_OPEN_DELAY_SEC)

                        # Evaluate signal for this closed bar
                        eval_res = self.signal_engine.evaluate(df_closed)
                        if not eval_res["valid"]:
                            logger.debug(f"[BAR SKIP] Invalid bar: {eval_res.get('reason')}")
                            continue

                        buy_score = eval_res["buy_score"]
                        sell_score = eval_res["sell_score"]
                        atr14 = eval_res["atr14"]

                        # TELEMETRY HEARTBEAT: Log every single M1 candle close
                        t_str = bar_time.strftime("%H:%M")
                        b_reasons_str = f" [{', '.join(eval_res['buy_reasons'])}]" if eval_res['buy_reasons'] else ""
                        s_reasons_str = f" [{', '.join(eval_res['sell_reasons'])}]" if eval_res['sell_reasons'] else ""
                        logger.info(
                            f"[M1 {t_str}] C={eval_res['close_price']:.2f} | ATR=${atr14:.2f} | "
                            f"Spread=${spread_dollar:.2f} | BuyS={buy_score}{b_reasons_str} | SellS={sell_score}{s_reasons_str}"
                        )

                        # V5.1 UPGRADE: Check Trend Reversal Exit on open positions first!
                        self.check_reversal_exits(eval_res, current_atr=atr14)

                        # 4. Check session active window (gating NEW entries only)
                        if not self.risk_mgr.check_session_active():
                            continue

                        # 5. Check circuit breaker, news freeze, and spread safety
                        safe, reason = self.risk_mgr.check_safety(acc, spread_dollar)
                        if not safe:
                            logger.info(f"[BLOCKED] Safety guard: {reason}")
                            continue

                        # 6. Check concurrency limit
                        open_pos = self.get_open_sniper_positions()
                        if len(open_pos) >= config.MAX_CONCURRENT_POSITIONS:
                            logger.debug(f"[MAX POS] Concurrency ceiling reached ({len(open_pos)} positions)")
                            continue

                        # Pyramiding guard: only pyramid if all existing positions are already Risk-Free (BE locked)
                        if open_pos and config.ALLOW_PYRAMIDING:
                            all_rf = all(p["ticket"] in self.be_locked_tickets for p in open_pos)
                            if not all_rf:
                                logger.debug("[PYRAMID WAIT] Existing position not yet Risk-Free (BE)")
                                continue

                        # 7. Debounce check: Prevent duplicate firing on the same candle
                        if self.last_traded_bar_time == bar_time:
                            logger.debug(f"[DEBOUNCE] Already fired trade for candle {bar_time}")
                            continue

                        # 8. Direction Evaluation & Anti-Conflict Check
                        has_open_buy = any(p["type"] == mt5.ORDER_TYPE_BUY for p in open_pos)
                        has_open_sell = any(p["type"] == mt5.ORDER_TYPE_SELL for p in open_pos)

                        if buy_score >= config.MIN_SCORE_ENTRY and buy_score > sell_score:
                            if getattr(config, 'ANTI_CONFLICT_ENABLED', True) and has_open_sell:
                                logger.info(f"[CONFLICT BLOCKED] Cannot BUY while active SELL position exists")
                                continue

                            lot = self.risk_mgr.calculate_lot(acc["equity"], buy_score)
                            if self.execute_order("BUY", lot, df_closed, atr14, buy_score, eval_res["buy_reasons"]):
                                self.last_traded_bar_time = bar_time

                        elif sell_score >= config.MIN_SCORE_ENTRY and sell_score > buy_score:
                            if getattr(config, 'ANTI_CONFLICT_ENABLED', True) and has_open_buy:
                                logger.info(f"[CONFLICT BLOCKED] Cannot SELL while active BUY position exists")
                                continue

                            lot = self.risk_mgr.calculate_lot(acc["equity"], sell_score)
                            if self.execute_order("SELL", lot, df_closed, atr14, sell_score, eval_res["sell_reasons"]):
                                self.last_traded_bar_time = bar_time

                        elif buy_score >= config.MIN_SCORE_ENTRY and buy_score == sell_score:
                            logger.debug(f"[TIE SKIP] Buy/Sell both scored {buy_score}, ambiguous signal skipped")

                    time.sleep(0.5)

                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    logger.error(f"[ERROR] Engine loop exception: {e}", exc_info=True)
                    time.sleep(5)

        except KeyboardInterrupt:
            logger.info("[STOP] Sniper Engine stopped by user")
        finally:
            self.release_process_lock()
            mt5.shutdown()


if __name__ == "__main__":
    engine = M1SniperEngine()
    engine.run()
