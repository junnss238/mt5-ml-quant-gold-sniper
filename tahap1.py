import MetaTrader5 as mt5
import pandas as pd
import pandas_ta as ta  
from datetime import datetime, timedelta
import time
import requests
import xml.etree.ElementTree as ET 
import pytz 

# ==========================================
# BAGIAN 1: PENGATURAN & FILTER DASAR
# ==========================================

SYMBOL = "XAUUSD"  
SYMBOL_DXY = "USDIndex"
LOT_SIZE = 0.01    
MAX_SPREAD = 30    
BATAS_LOSS_HARIAN = 0.95 
MAGIC_NUMBER = 123456 # ID KTP Bot lu

def cek_jam_trading():
    jam_sekarang = datetime.now().hour
    if 14 <= jam_sekarang <= 22:
        return True
    return True # RETURN TRUE DULU BUAT NGETES

def hitung_spread(symbol):
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None: return 999
    return (tick.ask - tick.bid) / info.point / 10

# ==========================================
# BAGIAN 2: RADAR FUNDAMENTAL & SINKRONISASI
# ==========================================

def bahaya_news_usd():
    """Ngecek jadwal rilis berita High Impact USD radius +/- 30 menit (Anti Daylight Savings)"""
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code != 200: return False 
        
        root = ET.fromstring(response.content)
        waktu_sekarang = datetime.now()
        zona_est = pytz.timezone('US/Eastern')
        zona_wib = pytz.timezone('Asia/Jakarta')
        
        for event in root.findall('event'):
            if event.find('country').text == 'USD' and event.find('impact').text == 'High':
                time_str = event.find('time').text 
                if time_str == "All Day": continue
                
                datetime_str = f"{event.find('date').text} {time_str}"
                waktu_news_naif = datetime.strptime(datetime_str, "%m-%d-%Y %I:%M%p")
                waktu_news_est = zona_est.localize(waktu_news_naif)
                waktu_news_wib = waktu_news_est.astimezone(zona_wib).replace(tzinfo=None)
                
                selisih = waktu_news_wib - waktu_sekarang
                if timedelta(minutes=-30) <= selisih <= timedelta(minutes=30):
                    print(f"\n🚨 AWAS JUN! News '{event.find('title').text}' rilis jam {waktu_news_wib.strftime('%H:%M')} WIB!")
                    return True 
        return False 
    except: return False

def sinkronisasi_ingatan():
    """Fungsi Anti-Amnesia kalau VPS/Laptop restart"""
    posisi_terbuka = mt5.positions_get(symbol=SYMBOL)
    if posisi_terbuka is None or len(posisi_terbuka) == 0:
        return False, None, None, 0.0
    
    for p in posisi_terbuka:
        if p.magic == MAGIC_NUMBER: # Ngecek apakah ini posisi punya bot kita
            print(f"🧠 SINKRONISASI BERHASIL! Bot inget ada posisi {('BUY' if p.type == 0 else 'SELL')} yg belum ditutup.")
            return True, p.ticket, p.type, p.price_open
            
    return False, None, None, 0.0
# ==========================================
# BAGIAN 3: OTAK ANALISIS (V5.1 - BEBAS ERROR TA-LIB)
# ==========================================

def cek_trend_dxy_mt5():
    """Narik DXY langsung dari broker MT5, Super Cepat & Anti Banned!"""
    rates = mt5.copy_rates_from_pos(SYMBOL_DXY, mt5.TIMEFRAME_H1, 0, 2)
    if rates is None or len(rates) < 2: 
        return "FLAT" 
        
    close_now = rates[-1]['close']
    close_prev = rates[-2]['close']
    
    if close_now > close_prev: return "UP"
    elif close_now < close_prev: return "DOWN"
    return "FLAT"
 
def analisis_market(symbol):
    # --- 1. CEK KOMPAS BESAR (TIMEFRAME H1) ---
    rates_h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 250)
    if rates_h1 is None: return None, "WAIT"
    
    df_h1 = pd.DataFrame(rates_h1)
    df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
    df_h1.ta.ema(length=200, append=True) 
    ema200_h1_now = df_h1.iloc[-2]['EMA_200'] 
    ema200_h1_past = df_h1.iloc[-7]['EMA_200'] 

    # --- 2. CEK TIMEFRAME EKSEKUSI (TIMEFRAME M5) ---
    rates_m5 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 100)
    if rates_m5 is None: return None, "WAIT"

    df = pd.DataFrame(rates_m5)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    # Perbaiki nama kolom buat MFI
    df.rename(columns={'tick_volume': 'volume'}, inplace=True) 
    
    # Indikator Teknikal (TANPA CDL_PATTERN)
    df.ta.ema(length=50, append=True)          
    df.ta.rsi(length=14, append=True)          
    df.ta.macd(append=True)                    
    df.ta.bbands(length=20, std=2.0, append=True)                  
    df.ta.atr(length=14, append=True)          
    df.ta.adx(length=14, append=True)
    df.ta.mfi(length=14, append=True) 

    last = df.iloc[-2]  
    prev = df.iloc[-3]
    
    # ----------------------------------------------------
    # 🧠 CUSTOM CANDLE SCANNER (Tanpa TA-Lib!)
    # ----------------------------------------------------
    body = abs(last['open'] - last['close'])
    lower_shadow = min(last['open'], last['close']) - last['low']
    upper_shadow = last['high'] - max(last['open'], last['close'])
    
    is_hammer = (lower_shadow > (2 * body)) and (upper_shadow < (0.5 * body)) and (body > 0)
    is_shooting_star = (upper_shadow > (2 * body)) and (lower_shadow < (0.5 * body)) and (body > 0)
    
    is_bullish_engulfing = (prev['close'] < prev['open']) and (last['close'] > last['open']) and (last['close'] > prev['open']) and (last['open'] < prev['close'])
    is_bearish_engulfing = (prev['close'] > prev['open']) and (last['close'] < last['open']) and (last['close'] < prev['open']) and (last['open'] > prev['close'])
    # ----------------------------------------------------

    # 🕵️‍♂️ CARI NAMA KOLOM OTOMATIS (ANTI KEY-ERROR 100%)
   # 🕵️‍♂️ CARI NAMA KOLOM OTOMATIS (ANTI KEY-ERROR 100%)
    col_macd = [c for c in df.columns if c.startswith('MACD_')][0]
    col_macds = [c for c in df.columns if c.startswith('MACDs_')][0]
    col_bbl = [c for c in df.columns if c.startswith('BBL_')][0]
    col_bbu = [c for c in df.columns if c.startswith('BBU_')][0]
    col_atr = [c for c in df.columns if c.startswith('ATR')][0] 
    
    # Ekstrak nilai buat skoring
    close = last['close']
    ema50 = last['EMA_50']
    rsi = last['RSI_14']
    macd_line = last[col_macd]
    macd_sig = last[col_macds]
    bb_lower = last[col_bbl]
    bb_upper = last[col_bbu]
    atr = last[col_atr] 
    adx = last['ADX_14']
    mfi = last['MFI_14']
    
    # 🧹 CATATAN: Variabel CDL_ENGULFING dkk udah dihapus 
    # karena kita udah pakai is_bullish_engulfing dkk dari custom scanner!

    if adx < 20: return atr, "WAIT" 
        
    trend_dxy = cek_trend_dxy_mt5() 

    buy_score = 0; sell_score = 0

    # Logika BUY 
    if close > ema50 and (ema200_h1_now > ema200_h1_past): buy_score += 1  
    if 30 < rsi < 45 and mfi < 80: buy_score += 1                        
    if macd_line > macd_sig: buy_score += 1                 
    if close <= (bb_lower * 1.002): buy_score += 1          
    if is_bullish_engulfing or is_hammer: buy_score += 1                     
    if trend_dxy != "UP": buy_score += 1

    # Logika SELL 
    if close < ema50 and (ema200_h1_now < ema200_h1_past): sell_score += 1 
    if 55 < rsi < 70 and mfi > 20: sell_score += 1                       
    if macd_line < macd_sig: sell_score += 1                
    if close >= (bb_upper * 0.998): sell_score += 1         
    if is_bearish_engulfing or is_shooting_star: sell_score += 1                   
    if trend_dxy != "DOWN": sell_score += 1

    signal = "WAIT"
    if buy_score >= 5: signal = "BUY"
    elif sell_score >= 5: signal = "SELL"

    return atr, signal

# ==========================================
# BAGIAN 4: EKSEKUSI ORDER
# ==========================================

def eksekusi_order(symbol, tipe_order, atr): 
    try:
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None: return None

        if tipe_order == mt5.ORDER_TYPE_BUY:
            price = tick.ask
            hard_sl = price - (atr * 5.0) 
            hard_tp = price + (atr * 6.0) 
        else:
            price = tick.bid
            hard_sl = price + (atr * 5.0) 
            hard_tp = price - (atr * 6.0) 
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": LOT_SIZE,
            "type": tipe_order,
            "price": price,
            "sl": hard_sl,  
            "tp": hard_tp,  
            "deviation": 20, 
            "magic": MAGIC_NUMBER, 
            "comment": "Bot Copet Arjun V5",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"❌ Order Gagal! Kode: {result.retcode}")
            return None
        
        print(f"✅ ORDER BERHASIL: {'BUY' if tipe_order == 0 else 'SELL'} di harga {price}")
        return result.order
    except: return None

def close_order(ticket, symbol, tipe_order):
    try:
        tick = mt5.symbol_info_tick(symbol)
        price = tick.bid if tipe_order == mt5.ORDER_TYPE_BUY else tick.ask
        tipe_close = mt5.ORDER_TYPE_SELL if tipe_order == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": LOT_SIZE,
            "type": tipe_close,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": MAGIC_NUMBER,
            "comment": "Tutup Cuan/Cutloss",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        mt5.order_send(request)
        print("🔒 Posisi berhasil ditutup dengan selamat!")
    except: pass

# ==========================================
# BAGIAN 5: JANTUNG BOT (MAIN LOOP V5.0)
# ==========================================

def jalankan_bot():
    if not mt5.initialize():
        print("Gagal konek ke MT5!")
        return

    print(f"🚀 ANJAYY! Bot Copet Gold M5 V5.0 siap beraksi pantau {SYMBOL}...")
    
    # --- 🛡️ CIRCUIT BREAKER HARIAN ---
    account_info = mt5.account_info()
    if account_info is None: return
        
    modal_awal = account_info.equity
    batas_loss_harian = modal_awal * BATAS_LOSS_HARIAN
    print(f"💼 Modal Awal: ${modal_awal:.2f} | 🛑 Berhenti Kalau Saldo Nyentuh: ${batas_loss_harian:.2f}")
    
    # --- 🧠 ANTI-AMNESIA (CEK INGATAN) ---
    posisi_aktif, tiket_aktif, tipe_aktif, entry_price = sinkronisasi_ingatan()
    
    # Setup awal ATR buat V-SL/V-TP
    atr_trade = 0.0
    virtual_sl = 0.0
    virtual_tp = 0.0
    
    # Kalau hasil ingatan dia punya posisi aktif, kita pulihin V-SL nya pake ATR terbaru
    if posisi_aktif:
        atr_trade, _ = analisis_market(SYMBOL)
        if atr_trade is not None:
            if tipe_aktif == mt5.ORDER_TYPE_BUY:
                virtual_sl = entry_price - (atr_trade * 1.5)
                virtual_tp = entry_price + (atr_trade * 3.0)
            else:
                virtual_sl = entry_price + (atr_trade * 1.5)
                virtual_tp = entry_price - (atr_trade * 3.0)

    try:
        while True:
            # --- CEK MODAL TERUS-TERUSAN ---
            current_equity = mt5.account_info().equity
            if current_equity < batas_loss_harian:
                print(f"\n☠️ AMPON DAH JUN! Saldo lu nyentuh batas rugi harian (${current_equity:.2f}). Bot Quit!")
                mt5.shutdown()
                quit()

            # --- MODE 1: JAGA LILIN & DYNAMIC ATR TRAILING STOP ---
            if posisi_aktif:
                tick = mt5.symbol_info_tick(SYMBOL)
                if tick is None: continue
                harga_skrg = tick.bid if tipe_aktif == mt5.ORDER_TYPE_BUY else tick.ask
                
                if tipe_aktif == mt5.ORDER_TYPE_BUY:
                    if harga_skrg >= virtual_tp:
                        print(f"💰 CUAN JUN! Kena Virtual TP di {harga_skrg}")
                        close_order(tiket_aktif, SYMBOL, tipe_aktif)
                        posisi_aktif = False
                    elif harga_skrg <= virtual_sl:
                        print(f"🔪 Kena SL / Trailing Stop di {harga_skrg}")
                        close_order(tiket_aktif, SYMBOL, tipe_aktif)
                        posisi_aktif = False
                        
                    # 📈 DYNAMIC ATR TRAILING STOP (BUY)
                    elif harga_skrg >= entry_price + (atr_trade * 1.5): # Kalo udah profit 1.5x ATR
                        titik_aman_baru = harga_skrg - (atr_trade * 1.0) # Jaga jarak 1x ATR dari pucuk
                        if virtual_sl < titik_aman_baru:
                            virtual_sl = round(titik_aman_baru, 2)
                            print(f"📈 Trailing SL Geser NAIK ngikutin ATR di: {virtual_sl:.2f}")

                elif tipe_aktif == mt5.ORDER_TYPE_SELL:
                    if harga_skrg <= virtual_tp:
                        print(f"💰 CUAN JUN! Kena Virtual TP di {harga_skrg}")
                        close_order(tiket_aktif, SYMBOL, tipe_aktif)
                        posisi_aktif = False
                    elif harga_skrg >= virtual_sl:
                        print(f"🔪 Kena SL / Trailing Stop di {harga_skrg}")
                        close_order(tiket_aktif, SYMBOL, tipe_aktif)
                        posisi_aktif = False
                        
                    # 📉 DYNAMIC ATR TRAILING STOP (SELL)
                    elif harga_skrg <= entry_price - (atr_trade * 1.5): 
                        titik_aman_baru = harga_skrg + (atr_trade * 1.0) 
                        if virtual_sl > titik_aman_baru:
                            virtual_sl = round(titik_aman_baru, 2)
                            print(f"📉 Trailing SL Geser TURUN ngikutin ATR di: {virtual_sl:.2f}")

                time.sleep(1) 
                continue 

            # --- MODE 2: CARI PELUANG BARU ---
            if not cek_jam_trading():
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Di luar jam kerja. Zzz...")
                time.sleep(60)
                continue
            
            if bahaya_news_usd():
                time.sleep(300) 
                continue

            spread = hitung_spread(SYMBOL)
            if spread > MAX_SPREAD:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Spread Mekar ({spread:.1f} pips). Tunggu...")
                time.sleep(5)
                continue

            atr, signal = analisis_market(SYMBOL)
            if atr is None or signal == "WAIT": 
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Market sideways atau skor gak lulus. Wait & See...")
                time.sleep(5)
                continue 
            
            tick = mt5.symbol_info_tick(SYMBOL)
            
            if signal == "BUY":
                print(f"\n🚀 Sinyal BUY Ditemukan! Harga: {tick.ask}")
                tiket_aktif = eksekusi_order(SYMBOL, mt5.ORDER_TYPE_BUY, atr)
                if tiket_aktif:
                    posisi_aktif = True
                    tipe_aktif = mt5.ORDER_TYPE_BUY
                    entry_price = tick.ask
                    atr_trade = atr # Simpan memori ATR pas buka posisi
                    virtual_sl = entry_price - (atr * 1.5)
                    virtual_tp = entry_price + (atr * 3.0)
                    print(f"📌 Entry: {entry_price:.2f} | V-SL: {virtual_sl:.2f} | V-TP: {virtual_tp:.2f}")

            elif signal == "SELL":
                print(f"\n🚀 Sinyal SELL Ditemukan! Harga: {tick.bid}")
                tiket_aktif = eksekusi_order(SYMBOL, mt5.ORDER_TYPE_SELL, atr) 
                if tiket_aktif:
                    posisi_aktif = True
                    tipe_aktif = mt5.ORDER_TYPE_SELL
                    entry_price = tick.bid
                    atr_trade = atr # Simpan memori ATR pas buka posisi
                    virtual_sl = entry_price + (atr * 1.5)
                    virtual_tp = entry_price - (atr * 3.0)
                    print(f"📌 Entry: {entry_price:.2f} | V-SL: {virtual_sl:.2f} | V-TP: {virtual_tp:.2f}")

            time.sleep(5) 

    except KeyboardInterrupt:
        print("\nBot dimatikan sama Bos Jun. Mantap!")
        mt5.shutdown()

if __name__ == "__main__":
    jalankan_bot()