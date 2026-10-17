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
LOT_SIZE = 0.01    
MAX_SPREAD = 30    
BATAS_LOSS_HARIAN = 0.95 
MAGIC_NUMBER = 123456 

def cek_jam_trading():
    jam_sekarang = datetime.now().hour
    if 14 <= jam_sekarang <= 22:
        return True
    return True 

def hitung_spread(symbol):
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None: return 999
    return (tick.ask - tick.bid) / info.point / 10

# ==========================================
# BAGIAN 2: RADAR FUNDAMENTAL & SINKRONISASI
# ==========================================

def bahaya_news_usd():
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
                    print(f"\n🚨 AWAS JUN! News rilis jam {waktu_news_wib.strftime('%H:%M')} WIB!")
                    return True 
        return False 
    except: return False

def sinkronisasi_ingatan():
    posisi_terbuka = mt5.positions_get(symbol=SYMBOL)
    if posisi_terbuka is None or len(posisi_terbuka) == 0:
        return False, None, None, 0.0
    
    for p in posisi_terbuka:
        if p.magic == MAGIC_NUMBER: 
            print(f"🧠 SINKRONISASI BERHASIL! Ada posisi {('BUY' if p.type == 0 else 'SELL')} aktif.")
            return True, p.ticket, p.type, p.price_open
            
    return False, None, None, 0.0

# ==========================================
# BAGIAN 3: OTAK ANALISIS (V7.2 - MURNI M1 KILAT)
# ==========================================

def analisis_market(symbol):
    # 💥 MURNI AMBIL DATA M1 AJA! GA USAH PUSINGIN M5!
    rates_m1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 100)
    if rates_m1 is None: return None, "WAIT"

    df = pd.DataFrame(rates_m1)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.rename(columns={'tick_volume': 'volume'}, inplace=True) 
    
    df.ta.rsi(length=14, append=True)          
    df.ta.bbands(length=20, std=2.0, append=True)                  
    df.ta.atr(length=14, append=True)          

    # last = candle yg udah fix nutup (1 menit lalu)
    # current = candle yg lagi jalan (diabaikan biar ga kena prank kedap-kedip)
    last = df.iloc[-2]  
    prev = df.iloc[-3]
    
    col_bbl = [c for c in df.columns if c.startswith('BBL_')][0]
    col_bbu = [c for c in df.columns if c.startswith('BBU_')][0]
    col_atr = [c for c in df.columns if c.startswith('ATR')][0] 
    
    bb_lower = last[col_bbl]
    bb_upper = last[col_bbu]
    atr = last[col_atr] 
    
    # --- LOGIKA INSTAN M1 ---
    # 1. Cek warna candle terakhir
    candle_hijau = last['close'] > last['open']
    candle_merah = last['close'] < last['open']
    
    # 2. Cek Momentum RSI (Apakah udah mulai nikung?)
    rsi_sekarang = last['RSI_14']
    rsi_sebelumnya = prev['RSI_14']
    rsi_nikung_naik = (rsi_sekarang > rsi_sebelumnya)
    rsi_nikung_turun = (rsi_sekarang < rsi_sebelumnya)

    signal = "WAIT"

    # 🟢 LOGIKA BUY KILAT M1
    # Jika harga menyentuh/mendekati BB Bawah (toleransi 0.5 ATR biar ga kaku)
    if last['low'] <= (bb_lower + (atr * 0.5)):
        # Kalo candle-nya ditutup Hijau & RSI naik & RSI ga kemahalan (<55) -> HAJAR BUY!
        if candle_hijau and rsi_nikung_naik and rsi_sekarang < 55:
            signal = "BUY"

    # 🔴 LOGIKA SELL KILAT M1
    # Jika harga menyentuh/mendekati BB Atas
    if last['high'] >= (bb_upper - (atr * 0.5)):
        # Kalo candle-nya ditutup Merah & RSI turun & RSI ga kemurahan (>45) -> HAJAR SELL!
        if candle_merah and rsi_nikung_turun and rsi_sekarang > 45:
            signal = "SELL"

    return atr, signal

# ==========================================
# BAGIAN 4: EKSEKUSI ORDER (M1 MODE)
# ==========================================

def eksekusi_order(symbol, tipe_order, atr): 
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None: return None

        # Jarak SL/TP standar M1
        if tipe_order == mt5.ORDER_TYPE_BUY:
            price = tick.ask
            hard_sl = price - (atr * 3.0) 
            hard_tp = price + (atr * 4.0) 
        else:
            price = tick.bid
            hard_sl = price + (atr * 3.0) 
            hard_tp = price - (atr * 4.0) 
        
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
            "comment": "Copet Brutal M1",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"❌ Order Gagal! Kode: {result.retcode}")
            return None
        
        print(f"✅ DOR! ORDER {'BUY' if tipe_order == 0 else 'SELL'} MASUK di {price}")
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
            "comment": "Bungkus Cuan/Cut",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        mt5.order_send(request)
        print("🔒 Posisi berhasil ditutup!")
    except: pass

# ==========================================
# BAGIAN 5: JANTUNG BOT (LOOP CEPAT)
# ==========================================

def jalankan_bot():
    if not mt5.initialize():
        print("Gagal konek ke MT5!")
        return

    print(f"🚀 ANJAYY! Bot PURE M1 BRUTAL V7.2 siap pantau {SYMBOL}...")
    
    account_info = mt5.account_info()
    if account_info is None: return
        
    modal_awal = account_info.equity
    batas_loss_harian = modal_awal * BATAS_LOSS_HARIAN
    print(f"💼 Modal Awal: ${modal_awal:.2f} | 🛑 Stop Loss Harian: ${batas_loss_harian:.2f}")
    
    posisi_aktif, tiket_aktif, tipe_aktif, entry_price = sinkronisasi_ingatan()
    
    atr_trade = 0.0
    virtual_sl = 0.0
    virtual_tp = 0.0
    
    if posisi_aktif:
        atr_trade, _ = analisis_market(SYMBOL)
        if atr_trade is not None:
            if tipe_aktif == mt5.ORDER_TYPE_BUY:
                virtual_sl = entry_price - (atr_trade * 1.0)
                virtual_tp = entry_price + (atr_trade * 2.5)
            else:
                virtual_sl = entry_price + (atr_trade * 1.0)
                virtual_tp = entry_price - (atr_trade * 2.5)

    try:
        while True:
            current_equity = mt5.account_info().equity
            if current_equity < batas_loss_harian:
                print(f"\n☠️ Saldo nyentuh batas bahaya (${current_equity:.2f}). Bot Quit!")
                mt5.shutdown()
                quit()

            if posisi_aktif:
                tick = mt5.symbol_info_tick(SYMBOL)
                if tick is None: continue
                harga_skrg = tick.bid if tipe_aktif == mt5.ORDER_TYPE_BUY else tick.ask
                
                if tipe_aktif == mt5.ORDER_TYPE_BUY:
                    if harga_skrg >= virtual_tp:
                        print(f"💰 DING! Kena TP di {harga_skrg}")
                        close_order(tiket_aktif, SYMBOL, tipe_aktif)
                        posisi_aktif = False
                    elif harga_skrg <= virtual_sl:
                        print(f"🔪 CUT! Kena SL di {harga_skrg}")
                        close_order(tiket_aktif, SYMBOL, tipe_aktif)
                        posisi_aktif = False
                        
                    elif harga_skrg >= entry_price + (atr_trade * 1.0): 
                        titik_aman = harga_skrg - (atr_trade * 0.8) 
                        if virtual_sl < titik_aman:
                            virtual_sl = round(titik_aman, 2)
                            print(f"📈 Trailing SL NAIK ke: {virtual_sl:.2f}")

                elif tipe_aktif == mt5.ORDER_TYPE_SELL:
                    if harga_skrg <= virtual_tp:
                        print(f"💰 DING! Kena TP di {harga_skrg}")
                        close_order(tiket_aktif, SYMBOL, tipe_aktif)
                        posisi_aktif = False
                    elif harga_skrg >= virtual_sl:
                        print(f"🔪 CUT! Kena SL di {harga_skrg}")
                        close_order(tiket_aktif, SYMBOL, tipe_aktif)
                        posisi_aktif = False
                        
                    elif harga_skrg <= entry_price - (atr_trade * 1.0): 
                        titik_aman = harga_skrg + (atr_trade * 0.8) 
                        if virtual_sl > titik_aman:
                            virtual_sl = round(titik_aman, 2)
                            print(f"📉 Trailing SL TURUN ke: {virtual_sl:.2f}")

                time.sleep(1) 
                continue 

            if not cek_jam_trading():
                time.sleep(60)
                continue
            
            if bahaya_news_usd():
                time.sleep(300) 
                continue

            spread = hitung_spread(SYMBOL)
            if spread > MAX_SPREAD:
                time.sleep(2)
                continue

            atr, signal = analisis_market(SYMBOL)
            if atr is None or signal == "WAIT": 
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Radar M1 nyari momentum...")
                time.sleep(2) # Scan tiap 2 detik biar ga telat
                continue 
            
            tick = mt5.symbol_info_tick(SYMBOL)
            
            if signal == "BUY":
                print(f"\n🚀 SIKAT BUY M1! Harga: {tick.ask}")
                tiket_aktif = eksekusi_order(SYMBOL, mt5.ORDER_TYPE_BUY, atr)
                if tiket_aktif:
                    posisi_aktif = True
                    tipe_aktif = mt5.ORDER_TYPE_BUY
                    entry_price = tick.ask
                    atr_trade = atr 
                    virtual_sl = entry_price - (atr * 1.5) 
                    virtual_tp = entry_price + (atr * 3.0) 

            elif signal == "SELL":
                print(f"\n🚀 SIKAT SELL M1! Harga: {tick.bid}")
                tiket_aktif = eksekusi_order(SYMBOL, mt5.ORDER_TYPE_SELL, atr) 
                if tiket_aktif:
                    posisi_aktif = True
                    tipe_aktif = mt5.ORDER_TYPE_SELL
                    entry_price = tick.bid
                    atr_trade = atr 
                    virtual_sl = entry_price + (atr * 1.5)
                    virtual_tp = entry_price - (atr * 3.0)

            time.sleep(2) 

    except KeyboardInterrupt:
        print("\nBot dimatikan. Mantap!")
        mt5.shutdown()

if __name__ == "__main__":
    jalankan_bot()