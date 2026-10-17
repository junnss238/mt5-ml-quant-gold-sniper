"""
╔══════════════════════════════════════════════════════════════╗
║           GOLD BLITZ — High Frequency Scalper DEMO          ║
║                                                              ║
║  ⚠️  PERINGATAN DARI BACKTEST DATA NYATA:                    ║
║  Blitz 682 trade/hari  → RUGI $3,388/hari @0.1lot           ║
║  Blitz 341 trade/hari  → RUGI $1,318/hari @0.1lot           ║
║  Strategi v3 16t/hari  → PROFIT $52/hari @0.1lot            ║
║                                                              ║
║  Bot ini untuk EKSPERIMEN DEMO saja.                         ║
║  Auto-stop jika balance turun 20%.                           ║
╚══════════════════════════════════════════════════════════════╝

INSTALL: pip install MetaTrader5 pandas numpy colorama
JALANKAN: python gold_blitz.py
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import logging
import sys
from datetime import datetime
from colorama import Fore, init
from dataclasses import dataclass

init(autoreset=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    handlers=[
        logging.FileHandler("gold_blitz.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("Blitz")


# ─────────────────────────────────────────────
#  CONFIG — BLITZ MODE
# ─────────────────────────────────────────────
@dataclass
class Config:
    # ── Koneksi ──────────────────────────────
    MT5_LOGIN:    int   = 0
    MT5_PASSWORD: str   = "password"
    MT5_SERVER:   str   = "ICMarketsSC-Demo"

    SYMBOL: str   = "XAUUSD"
    MAGIC:  int   = 99999
    LOT:    float = 0.10

    # ── BLITZ PARAMETERS ─────────────────────
    # Entry: score sederhana ≥ 2 dari 5 sinyal dasar
    # Close: begitu TP kena ATAU timeout 3 candle
    MIN_SCORE:   int   = 2      # entry hampir setiap candle
    TP_ATR_MULT: float = 0.3    # TP kecil = mudah kena = close cepat
    SL_ATR_MULT: float = 0.5    # SL ketat = loss terbatas per trade
    TIMEOUT_MIN: int   = 3      # force close setelah 3 menit kalau tidak kena TP/SL

    # ── Safety ───────────────────────────────
    MAX_SPREAD:       int   = 50    # longgar
    MAX_POSITIONS:    int   = 3     # max 3 posisi bersamaan
    STOP_LOSS_PCT:    float = 20.0  # auto-stop kalau balance turun 20%
    MAX_DAILY_TRADES: int   = 200   # hampir tidak terbatas
    COOLDOWN_SEC:     int   = 5     # 5 detik antar entry


CFG = Config()


# ─────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────
class State:
    def __init__(self):
        self.start_bal    = 0.0
        self.daily_trades = 0
        self.last_entry   = 0.0
        self.open_times   = {}  # ticket → open_time

S = State()


# ─────────────────────────────────────────────
#  MT5 HELPERS
# ─────────────────────────────────────────────
def connect() -> bool:
    if not mt5.initialize():
        log.error(f"mt5 init gagal: {mt5.last_error()}")
        return False
    if CFG.MT5_LOGIN != 0:
        if not mt5.login(CFG.MT5_LOGIN, CFG.MT5_PASSWORD, CFG.MT5_SERVER):
            log.error(f"Login gagal: {mt5.last_error()}")
            return False
    info = mt5.account_info()
    if info is None:
        return False
    mt5.symbol_select(CFG.SYMBOL, True)
    S.start_bal    = info.balance
    S.daily_trades = 0
    log.info(f"✅ {info.name} | #{info.login} | ${info.balance:.2f}")
    return True


def get_filling():
    """Deteksi mode eksekusi order yang diizinkan broker IC Markets"""
    info = mt5.symbol_info(CFG.SYMBOL)
    if info is None:
        return mt5.ORDER_FILLING_IOC
        
    # Perbaikan: Pakai konstanta yang valid di MT5 Python!
    if info.filling_mode & 1:  # 1 = FOK (Fill Or Kill)
        return mt5.ORDER_FILLING_FOK
    if info.filling_mode & 2:  # 2 = IOC (Immediate Or Cancel)
        return mt5.ORDER_FILLING_IOC
        
    return mt5.ORDER_FILLING_RETURN

def spread_pts() -> float:
    tick = mt5.symbol_info_tick(CFG.SYMBOL)
    info = mt5.symbol_info(CFG.SYMBOL)
    if tick is None or info is None:
        return 999
    return (tick.ask - tick.bid) / info.point


def count_pos() -> int:
    pos = mt5.positions_get(symbol=CFG.SYMBOL)
    if pos is None:
        return 0
    return len([p for p in pos if p.magic == CFG.MAGIC])


def force_close(ticket: int, reason: str):
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return
    p    = pos[0]
    tick = mt5.symbol_info_tick(CFG.SYMBOL)
    info = mt5.symbol_info(CFG.SYMBOL)
    if tick is None or info is None:
        return
    price = tick.bid if p.type == 0 else tick.ask
    tipe  = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
    req   = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       CFG.SYMBOL,
        "volume":       p.volume,
        "type":         tipe,
        "position":     ticket,
        "price":        price,
        "deviation":    20,
        "magic":        CFG.MAGIC,
        "comment":      reason[:15],
        "type_filling": get_filling(),
    }
    r = mt5.order_send(req)
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        pnl_info = f"${p.profit:+.2f}"
        col = Fore.GREEN if p.profit >= 0 else Fore.RED
        print(col + f"  ✂️  Close #{ticket} | {reason} | {pnl_info}")
    S.open_times.pop(ticket, None)


# ─────────────────────────────────────────────
#  TIMEOUT MANAGER — Close setelah N menit
# ─────────────────────────────────────────────
def timeout_manager():
    pos = mt5.positions_get(symbol=CFG.SYMBOL)
    if not pos:
        return
    now = time.time()
    for p in pos:
        if p.magic != CFG.MAGIC:
            continue
        open_t = S.open_times.get(p.ticket, p.time)
        elapsed_min = (now - open_t) / 60
        if elapsed_min >= CFG.TIMEOUT_MIN:
            force_close(p.ticket, f"TIMEOUT_{elapsed_min:.0f}m")


# ─────────────────────────────────────────────
#  SCORING BLITZ — Simple & Cepat
# ─────────────────────────────────────────────
def get_signal():
    rates = mt5.copy_rates_from_pos(CFG.SYMBOL, mt5.TIMEFRAME_M1, 0, 50)
    if rates is None or len(rates) < 10:
        return None, None, 0

    df = pd.DataFrame(rates)
    df["c"] = df["close"]; df["h"] = df["high"]; df["l"] = df["low"]
    df["o"] = df["open"];  df["v"] = df["tick_volume"]

    df["e9"]  = df.c.ewm(span=9,  adjust=False).mean()
    df["e21"] = df.c.ewm(span=21, adjust=False).mean()

    # ATR
    tr = pd.concat([df.h-df.l,
                    (df.h-df.c.shift()).abs(),
                    (df.l-df.c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(span=14, adjust=False).mean()
    df["vol_ma"] = df.v.rolling(20).mean()
    df = df.dropna()
    if len(df) < 5:
        return None, None, 0

    r  = df.iloc[-2]   # candle yang baru close
    p  = df.iloc[-3]
    a  = r.atr

    if a < 1.0:
        return None, None, 0

    body   = max(abs(r.c - r.o), 0.0001)
    ls     = min(r.o, r.c) - r.l
    us     = r.h - max(r.o, r.c)
    vol_r  = r.v / r.vol_ma if r.vol_ma > 0 else 1

    sc_b = sc_s = 0

    if r.e9 > r.e21:  # arah dasar naik
        if r.c > r.o:       sc_b += 1  # candle naik
        if r.e9 > p.e9:     sc_b += 1  # EMA9 naik
        if vol_r >= 1.2:    sc_b += 1  # ada volume
        if r.c > p.c:       sc_b += 1  # close lebih tinggi
        if ls >= body*0.5:  sc_b += 1  # ada lower shadow

    elif r.e9 < r.e21:  # arah dasar turun
        if r.c < r.o:       sc_s += 1
        if r.e9 < p.e9:     sc_s += 1
        if vol_r >= 1.2:    sc_s += 1
        if r.c < p.c:       sc_s += 1
        if us >= body*0.5:  sc_s += 1

    if sc_b >= CFG.MIN_SCORE:
        return "BUY", a, sc_b
    if sc_s >= CFG.MIN_SCORE:
        return "SELL", a, sc_s
    return None, a, 0


# ─────────────────────────────────────────────
#  EKSEKUSI
# ─────────────────────────────────────────────
def entry(signal: str, atr: float, score: int) -> bool:
    tick = mt5.symbol_info_tick(CFG.SYMBOL)
    sym  = mt5.symbol_info(CFG.SYMBOL)
    if tick is None or sym is None:
        return False

    sl_d = atr * CFG.SL_ATR_MULT
    tp_d = atr * CFG.TP_ATR_MULT

    if signal == "BUY":
        price = tick.ask
        sl    = round(price - sl_d, sym.digits)
        tp    = round(price + tp_d, sym.digits)
        tipe  = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid
        sl    = round(price + sl_d, sym.digits)
        tp    = round(price - tp_d, sym.digits)
        tipe  = mt5.ORDER_TYPE_SELL

    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       CFG.SYMBOL,
        "volume":       CFG.LOT,
        "type":         tipe,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    20,
        "magic":        CFG.MAGIC,
        "comment":      f"blitz:{score}",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": get_filling(),
    }

    r = mt5.order_send(req)
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        err = mt5.last_error() if r is None else r.comment
        log.debug(f"Entry gagal: {err}")
        return False

    S.daily_trades   += 1
    S.last_entry      = time.time()
    S.open_times[r.order] = time.time()

    arrow = "🟢" if signal == "BUY" else "🔴"
    print(Fore.CYAN + f"  {arrow} {signal} #{r.order} | sc:{score}/5 "
          f"| TP:{tp:.2f}(+{tp_d:.2f}) SL:{sl:.2f}(-{sl_d:.2f}) | ATR:{atr:.2f}")
    return True


# ─────────────────────────────────────────────
#  DASHBOARD
# ─────────────────────────────────────────────
def dashboard():
    info = mt5.account_info()
    if info is None:
        return
    bal  = info.balance
    loss_pct = (S.start_bal - bal) / S.start_bal * 100 if S.start_bal > 0 else 0
    n_pos    = count_pos()
    sp       = spread_pts()

    bar_col  = Fore.RED if loss_pct > 10 else Fore.YELLOW
    print(Fore.YELLOW + f"\n{'─'*52}")
    print(f"  ⏰ {datetime.now().strftime('%H:%M:%S')} | "
          f"💰 ${bal:.2f} | 📉 -{loss_pct:.1f}% dari start")
    print(bar_col + f"  🔥 Trades: {S.daily_trades} | Posisi: {n_pos} | Spread: {sp:.0f}pt")
    pos = mt5.positions_get(symbol=CFG.SYMBOL)
    if pos:
        for p in pos:
            if p.magic != CFG.MAGIC: continue
            col = Fore.GREEN if p.profit >= 0 else Fore.RED
            d   = "BUY" if p.type == 0 else "SELL"
            print(col + f"  📌 #{p.ticket} {d} @ {p.price_open:.2f} | ${p.profit:+.2f}")
    print(Fore.YELLOW + "─" * 52)


# ─────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────
def main():
    print(Fore.RED + """
╔══════════════════════════════════════════════════════════════╗
║  ⚠️  GOLD BLITZ — HIGH RISK DEMO MODE                        ║
║  Entry cepat, TP kecil, banyak trade                        ║
║  AUTO-STOP jika balance turun 20%                           ║
╚══════════════════════════════════════════════════════════════╝""")

    if not connect():
        sys.exit(1)

    print(Fore.GREEN + f"  ✅ Start balance: ${S.start_bal:.2f}")
    print(Fore.YELLOW + f"  Auto-stop jika turun ke: ${S.start_bal*(1-CFG.STOP_LOSS_PCT/100):.2f}")
    print(Fore.WHITE + "  Ctrl+C untuk stop manual\n")

    last_dash = 0

    while True:
        try:
            now = time.time()

            # ── Dashboard setiap 15 detik ──
            if now - last_dash > 15:
                dashboard()
                last_dash = now

            # ── Safety: auto-stop 20% loss ──
            info = mt5.account_info()
            if info is None:
                connect(); time.sleep(3); continue
            bal = info.balance
            loss_pct = (S.start_bal - bal) / S.start_bal * 100
            if loss_pct >= CFG.STOP_LOSS_PCT:
                print(Fore.RED + f"\n🚨 AUTO-STOP! Balance turun {loss_pct:.1f}% dari start!")
                print(Fore.RED + f"   Start: ${S.start_bal:.2f} → Sekarang: ${bal:.2f}")
                print(Fore.RED + f"   Total trades: {S.daily_trades}")
                # Close semua posisi
                pos = mt5.positions_get(symbol=CFG.SYMBOL)
                if pos:
                    for p in pos:
                        if p.magic == CFG.MAGIC:
                            force_close(p.ticket, "AUTO_STOP")
                break

            # ── Timeout manager ──
            timeout_manager()

            # ── Spread check ──
            sp = spread_pts()
            if sp > CFG.MAX_SPREAD:
                time.sleep(1)
                continue

            # ── Max posisi ──
            if count_pos() >= CFG.MAX_POSITIONS:
                time.sleep(0.5)
                continue

            # ── Cooldown ──
            if now - S.last_entry < CFG.COOLDOWN_SEC:
                time.sleep(0.5)
                continue

            # ── Ambil sinyal ──
            signal, atr, score = get_signal()
            if signal and atr:
                entry(signal, atr, score)

            time.sleep(0.5)

        except KeyboardInterrupt:
            print(Fore.YELLOW + "\n\n  Manual stop...")
            break
        except Exception as e:
            log.error(f"Error: {e}")
            time.sleep(2)

    # Ringkasan akhir
    info = mt5.account_info()
    if info:
        final_pnl = info.balance - S.start_bal
        col = Fore.GREEN if final_pnl >= 0 else Fore.RED
        print(col + f"""
╔═══════════════════════════════╗
║  RINGKASAN BLITZ SESSION      ║
║  Total trades : {S.daily_trades:<15}║
║  Start bal    : ${S.start_bal:<13.2f}║
║  End bal      : ${info.balance:<13.2f}║
║  Net P&L      : {final_pnl:>+14.2f} ║
╚═══════════════════════════════╝""")
    mt5.shutdown()


if __name__ == "__main__":
    main()