import MetaTrader5 as mt5
import pandas as pd
import pandas_ta as ta  
from datetime import datetime, timedelta
import time
import requests
import xml.etree.ElementTree as ET 
import pytz 

# ==========================================
# BAGIAN 1: PENGATURAN MODE LIQUIDITY HUNTER
# ==========================================

SYMBOL = "XAUUSD"  
SYMBOL_DXY = "USDIndex"
LOT_SIZE = 0.01    
MAX_SPREAD = 30    
BATAS_LOSS_HARIAN = 0.95 
MAGIC_NUMBER = 123456 

# 🔥 SETTINGAN SCALPER LUWES
MAX_LAYER = 2              
CUAN_KILAT_USD = 1.50      
CUTLOSS_KILAT_USD = -0.50  
COOLDOWN_ENTRY = 60        

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
# BAGIAN 2: RADAR FUNDAMENTAL
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

# ==========================================
# BAGIAN 3: OTAK ANALISIS (M1 LUWES + H1 LIQUIDITY)
# ==========================================

def cek_trend_dxy_mt5():
    rates = mt5.copy_rates_from_pos(SYMBOL_DXY, mt5.TIMEFRAME_M15, 0, 2)
    if rates is None or len(rates) < 2: return "FLAT" 
    close_now = rates[-1]['close']
    close_prev = rates[-2]['close']
    if close_now > close_prev: return "UP"
    elif close_now < close_prev: return "DOWN"
    return "FLAT"

def analisis_market(symbol):
    # --- 1. RADAR LIQUIDITY H1 (Saran Temen Lu!) ---
    rates_h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 24) # Tarik data 24 jam terakhir
    if rates_h1 is None: return None, "WAIT"
    df_h1 = pd.DataFrame(rates_h1)
    liquidity_atas = df_h1['high'].max() # Pucuk tertinggi hari ini (Resisten kuat)
    liquidity_bawah = df_h1['low'].min() # Lembah terendah hari ini (Support kuat)

    # --- 2. RADAR MENENGAH M15 (Gak kaku, cuma buat nambah wawasan) ---
    rates_m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 20)
    if rates_m15 is None: return None, "WAIT"
    df_m15 = pd.DataFrame(rates_m15)
    df_m15.ta.ema(length=10, append=True) 
    ema_m15_now = df_m15.iloc[-2]['EMA_10']
    ema_m15_past = df_m15.iloc[-3]['EMA_10']

    # --- 3. MEDAN TEMPUR UTAMA M1 ---
    rates_m1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 100)
    if rates_m1 is None: return None, "WAIT"

    df = pd.DataFrame(rates_m1)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.rename(columns={'tick_volume': 'volume'}, inplace=True) 
    
    df.ta.ema(length=50, append=True)          
    df.ta.rsi(length=14, append=True)          
    df.ta.macd(append=True)                    
    df.ta.bbands(length=20, std=2.0, append=True)                  
    df.ta.atr(length=14, append=True)          
    df.ta.mfi(length=14, append=True) 

    last = df.iloc[-2]  
    prev = df.iloc[-3]
    
    # ----------------------------------------------------
    # 🧠 CUSTOM CANDLE SCANNER (DILONGGARIN PARAH!)
    # ----------------------------------------------------
    body = abs(last['open'] - last['close'])
    lower_shadow = min(last['open'], last['close']) - last['low']
    upper_shadow = last['high'] - max(last['open'], last['close'])
    candle_range = last['high'] - last['low']
    body = body if body > 0 else 0.0001 
    
    col_atr = [c for c in df.columns if c.startswith('ATR')][0] 
    atr = last[col_atr]
    
    # Syarat diturunin drastis: Ekor cukup 1.5x body (ga usah 3x lagi)
    is_hammer = (lower_shadow >= 1.5 * body) and (upper_shadow <= 0.8 * body)
    is_shooting_star = (upper_shadow >= 1.5 * body) and (lower_shadow <= 0.8 * body)
    
    # Engulfing cukup ngalahin body sebelumnya dikit aja
    prev_body = abs(prev['open'] - prev['close'])
    is_bullish_engulfing = (prev['close'] < prev['open']) and (last['close'] > last['open']) and (body >= 1.05 * prev_body)
    is_bearish_engulfing = (prev['close'] > prev['open']) and (last['close'] < last['open']) and (body >= 1.05 * prev_body)
    # ----------------------------------------------------

    col_macd = [c for c in df.columns if c.startswith('MACD_')][0]
    col_macds = [c for c in df.columns if c.startswith('MACDs_')][0]
    col_bbl = [c for c in df.columns if c.startswith('BBL_')][0]
    col_bbu = [c for c in df.columns if c.startswith('BBU_')][0]
    
    macd_line = last[col_macd]
    macd_sig = last[col_macds]
    bb_lower = last[col_bbl]
    bb_upper = last[col_bbu]
    rsi = last['RSI_14']
    mfi = last['MFI_14']
    
    trend_dxy = cek_trend_dxy_mt5() 

    buy_score = 0; sell_score = 0

    # 🟢 LOGIKA BUY M1 (Luwes & Siap Hajar)
    if last['low'] <= (bb_lower + (atr * 0.5)): buy_score += 1 # Toleransi BB dilonggarin     
    if rsi < 45: buy_score += 1                                # RSI lebih santai
    if mfi < 40: buy_score += 1                                
    if is_bullish_engulfing or is_hammer: buy_score += 1       
    if macd_line > macd_sig: buy_score += 1                    
    if (ema_m15_now > ema_m15_past): buy_score += 1            
    
    # 🔥 THE HOLY GRAIL: Nangkep Liquidity Bawah H1
    if last['low'] <= (liquidity_bawah + (atr * 1.5)): 
        buy_score += 2  # Skor langsung lompat +2 karena ini area mantul paling gacor!
        print(f"🌊 [RADAR H1] Harga deket Liquidity Support! Siap-siap BUY!")

    # 🔴 LOGIKA SELL M1 (Luwes & Siap Hajar)
    if last['high'] >= (bb_upper - (atr * 0.5)): sell_score += 1 
    if rsi > 55: sell_score += 1                               
    if mfi > 60: sell_score += 1                               
    if is_bearish_engulfing or is_shooting_star: sell_score += 1 
    if macd_line < macd_sig: sell_score += 1                   
    if (ema_m15_now < ema_m15_past): sell_score += 1           

    # 🔥 THE HOLY GRAIL: Nangkep Liquidity Atas H1
    if last['high'] >= (liquidity_atas - (atr * 1.5)): 
        sell_score += 2 # Skor langsung lompat +2
        print(f"🌊 [RADAR H1] Harga deket Liquidity Resisten! Siap-siap SELL!")

    signal = "WAIT"
    # 🔥 SYARAT LULUS DITURUNIN JADI 4 POIN AJA! (Biar gatel OP)
    if buy_score >= 4: signal = "BUY" 
    elif sell_score >= 4: signal = "SELL"

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
            hard_sl = price - (atr * 2.0) 
            hard_tp = price + (atr * 6.0) 
        else:
            price = tick.bid
            hard_sl = price + (atr * 2.0) 
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
            "comment": "Liquidity Hunter V8.4",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK, 
        }
        
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"❌ Order Gagal! Kode: {result.retcode}")
            return None
        
        print(f"✅ DOR! Peluru {'BUY' if tipe_order == 0 else 'SELL'} dilesatkan di {price}")
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
            "comment": "Cuan/Cut Kilat",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK, 
        }
        mt5.order_send(request)
    except: pass

# ==========================================
# BAGIAN 5: JANTUNG BOT (LOOP HYPER SPEED)
# ==========================================

def jalankan_bot():
    if not mt5.initialize():
        print("Gagal konek ke MT5!")
        return

    print(f"🚀 ANJAYY! Bot LIQUIDITY HUNTER V8.4 siap tempur di {SYMBOL}...")
    print(f"🎯 Target Cuan: ${CUAN_KILAT_USD} | 🔪 Max Minus: ${CUTLOSS_KILAT_USD}")
    
    account_info = mt5.account_info()
    if account_info is None: return
        
    modal_awal = account_info.equity
    batas_loss_harian = modal_awal * BATAS_LOSS_HARIAN
    print(f"💼 Modal Awal: ${modal_awal:.2f} | 🛑 Nyentuh ${batas_loss_harian:.2f} Bot Mati!")
    
    last_entry_time = 0

    try:
        while True:
            current_equity = mt5.account_info().equity
            if current_equity < batas_loss_harian:
                print(f"\n☠️ AMPON DAH JUN! Saldo lu nyentuh batas rugi harian (${current_equity:.2f}). Bot Quit!")
                mt5.shutdown()
                quit()

            posisi_terbuka = mt5.positions_get(symbol=SYMBOL)
            posisi_bot = [p for p in posisi_terbuka if p.magic == MAGIC_NUMBER] if posisi_terbuka else []
            
            for p in posisi_bot:
                if p.profit >= CUAN_KILAT_USD:
                    print(f"💰 DING! Tiket {p.ticket} Cuan ${p.profit:.2f}. BUNGKUS JUN!")
                    close_order(p.ticket, SYMBOL, p.type)
                elif p.profit <= CUTLOSS_KILAT_USD:
                    print(f"🔪 CUTLOSS TEGAS! Tiket {p.ticket} minus ${p.profit:.2f}. Relakan aja!")
                    close_order(p.ticket, SYMBOL, p.type)

            if len(posisi_bot) < MAX_LAYER:
                
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
                    time.sleep(2)
                    continue

                if time.time() - last_entry_time > COOLDOWN_ENTRY:
                    atr, signal = analisis_market(SYMBOL)
                    
                    if atr is None or signal == "WAIT": 
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] M1 Patroli (Aktif: {len(posisi_bot)}/{MAX_LAYER})...")
                    else:
                        tick = mt5.symbol_info_tick(SYMBOL)
                        if signal == "BUY":
                            print(f"\n🚀 MOMEN BUY M1 DAPET! Harga: {tick.ask}")
                            if eksekusi_order(SYMBOL, mt5.ORDER_TYPE_BUY, atr):
                                last_entry_time = time.time()
                                
                        elif signal == "SELL":
                            print(f"\n🚀 MOMEN SELL M1 DAPET! Harga: {tick.bid}")
                            if eksekusi_order(SYMBOL, mt5.ORDER_TYPE_SELL, atr):
                                last_entry_time = time.time()

            time.sleep(1) 

    except KeyboardInterrupt:
        print("\nBot dimatikan sama Bos Jun. Mantap!")
        mt5.shutdown()

if __name__ == "__main__":
    jalankan_bot()