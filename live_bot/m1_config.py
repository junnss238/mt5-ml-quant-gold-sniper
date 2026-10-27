"""
M1 XAUUSD Quant Sniper (V5.2 - Adaptive Scalper Edition)
Master Parameters for Cent & Standard Accounts on MetaTrader 5
0% Lagging Indicators | 100% Price Action, Order Flow & Flowing Trailing Stop
Adaptive SL | Reversal Profit-Cut | Anti-Whipsaw Filter | Singleton Engine Guard
"""
import os

# === BROKER & ACCOUNT ===
MT5_PATH = os.environ.get("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
MT5_LOGIN = int(os.environ.get("MT5_LOGIN", "0"))
MT5_SERVER = os.environ.get("MT5_SERVER", "")
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MAGIC_NUMBER = 20261027

# === INSTRUMENT & TIMEFRAME ===
SYMBOL = "XAUUSD"
TIMEFRAME = "M1"
HTF_TIMEFRAME = "H1"

# === VOLATILITY-GATED HUNTING (DYNAMIC SESSIONS) ===
ACTIVE_SESSION_ONLY = False
SESSION_WINDOWS_WIB = [
    {"name": "LONDON_OPEN", "start": "14:00", "end": "18:00"},
    {"name": "US_PEAK", "start": "19:00", "end": "01:00"},
    {"name": "ASIAN", "start": "07:00", "end": "12:00"},
]

# === SIGNAL SCORING THRESHOLDS ===
MIN_SCORE_ENTRY = 2
HIGH_CONVICTION_SCORE = 3
ULTRA_SCORE = 4

# === RISK & SIZING (CENT ACCOUNT RP 100RB / 625 USC BASE) ===
EQUITY_PER_LOT_UNIT = 50000.0
MIN_LOT = 0.01
MAX_LOT_PER_ORDER = 0.50

# Concurrency & Pyramiding
MAX_CONCURRENT_POSITIONS = 2 # Max 2 concurrent pyramid positions
ALLOW_PYRAMIDING = True      # Only add position if previous position is Risk-Free (BE-locked)

# === ADAPTIVE STOP LOSS (V5.1 UPGRADE) ===
ADAPTIVE_SL_ENABLED = True
SL_MIN_DOLLAR = 1.10             # Minimum SL floor ($1.10 to clear spread + micro-noise)
SL_MAX_DOLLAR = 2.80             # Maximum SL ceiling ($2.80 cap)
SL_SWING_LOOKBACK = 3            # Lookback bars for structural swing low/high
SL_BUFFER_ATR = 0.15             # Buffer beyond swing low/high in ATR units
HARD_SL_ATR_MULT = 0.60          # Baseline ATR multiplier if structural swing is flat

# === FAST-IN FAST-OUT & REVERSAL EXIT (V5.1 UPGRADE) ===
REVERSAL_EXIT_ENABLED = True     # Cut trade immediately if trend/momentum flips while in profit
REVERSAL_MIN_PROFIT_ATR = 0.20   # Must have at least +0.20x ATR profit before reversal cut triggers
STAGNATION_MAX_BARS = 4          # Close if held 4 bars (4 min) without hitting BE

# === FLOWING TRAILING STOP ENGINE (EA RAZOR STYLE) ===
QUICK_BE_TRIGGER_ATR = 0.15      # Move SL to Entry + Spread + $0.08 once profit reaches 0.15x ATR (~+$0.45)
BE_LOCK_PIPS = 8                 # Lock +$0.08 profit once BE triggers (Risk-Free)
TRAILING_DISTANCE_ATR = 0.15     # Continuous flowing trailing gap = 0.15x ATR (~$0.50 behind peak)
PROFIT_CHOKE_ATR = 0.80          # Tighten trailing gap to CHOKE earlier (at 0.8x ATR ~+$2.50)
CHOKE_TRAILING_ATR = 0.07        # Tight 0.07x ATR gap on runners to lock maximum profit

# === ANTI-CONFLICT & OVER-TRADING GUARDS (V5.1 UPGRADE) ===
ANTI_CONFLICT_ENABLED = True     # Never allow opposite directional entries simultaneously
COMPRESSION_MAX_EXTENSION_ATR = 0.35 # Anti-pucuk: reject breakout if bar closed > 0.35x ATR past level
LOCK_FILE = r"C:\Users\asuszenbook\forex_scalper\m1_sniper.lock"

# === SAFETY GUARDS & CIRCUIT BREAKERS ===
MIN_ATR_FILTER = 1.00            # Skip entry if M1 ATR14 < $1.00 (dead/choppy market)
MAX_SPREAD_CEILING = 0.65        # Skip entry if spread > $0.65 per oz (spread spike protection)
CANDLE_OPEN_DELAY_SEC = 2        # Wait 2 seconds after bar open to avoid tick 00 spread spike
DAILY_LOSS_LIMIT_PCT = 25.0      # Halt bot for the session if equity drops >= 25% from day start
ANTI_WHIPSAW_LOSSES = 3          # If 3 consecutive losses happen within 15 mins -> 15 min cooldown
COOLDOWN_MINUTES = 15

# === NEWS FREEZE (High-Impact USD Events) ===
NEWS_FREEZE_ENABLED = True
NEWS_FREEZE_MINUTES_BEFORE = 15
NEWS_FREEZE_MINUTES_AFTER = 15
NEWS_EVENTS_UTC = []

# === LOGGING & DATABASE ===
LOG_FILE = r"C:\Users\asuszenbook\forex_scalper\data\logs\m1_sniper.log"
TRADE_LOG_CSV = r"C:\Users\asuszenbook\forex_scalper\data\logs\m1_trades.csv"

# === TEST MODE LOT OVERRIDE ===
FIXED_LOT_MODE = True
TEST_LOT_SIZE = 0.05

# === CLIMAX EXHAUSTION & OVER-EXTENSION GUARDS ===
CLIMAX_FILTER_ENABLED = True
RSI_OVERSOLD_BLOCK = 15.0        # Don't SELL if RSI7 < 15 (extreme parabolic dump)
RSI_OVERBOUGHT_BLOCK = 85.0      # Don't BUY if RSI7 > 85 (extreme parabolic pump)
COOLDOWN_AFTER_WIN_STREAK_BARS = 2 # Pause 2 bars after closing a profitable runner

# === MT5 RECONNECTION ===
RECONNECT_MAX_RETRIES = 5
RECONNECT_DELAY_SEC = 10
