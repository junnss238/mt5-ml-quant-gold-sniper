import MetaTrader5 as mt5
import pandas as pd
import pandas_ta as ta  
from datetime import datetime, timedelta
import time
import requests
import xml.etree.ElementTree as ET 
import pytz 
from sklearn.ensemble import RandomForestClassifier # 👈 INI OTAK AI-NYA!
import numpy as np

# ==========================================
# 1. PENGATURAN MODE MACHINE LEARNING
# ==========================================
SYMBOL = "XAUUSD"  
LOT_SIZE = 0.01    
MAX_SPREAD = 30    
BATAS_LOSS_HARIAN = 0.95 
MAGIC_NUMBER = 999111 # ID Khusus Bot AI
MAX_LAYER = 1         # 1 posisi aja buat ngetes akurasi AI
CUAN_KILAT_USD = 1.00      
CUTLOSS_KILAT_USD = -0.50  

# ==========================================
# 2. PROSES "SEKOLAH" (TRAINING MODEL AI)
# ==========================================
def latih_otak_ai(symbol):
    print("🧠 Sedang menyedot 3000 data masa lalu untuk melatih AI...")
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 3000)
    if rates is None: return None
    
    df = pd.DataFrame(rates)
    df.rename(columns={'tick_volume': 'volume'}, inplace=True) 
    
    # Bikin Kolom Indikator (Features / Bahan Belajar)
    df.ta.ema(length=50, append=True)          
    df.ta.rsi(length=14, append=True)          
    df.ta.macd(append=True)                    
    df.ta.mfi(length=14, append=True)
    df.ta.atr(length=14, append=True)
    
    # Bikin Kolom Fitur Custom (Matematika Candle)
    df['body_size'] = abs(df['open'] - df['close'])
    df['lower_shadow'] = df[['open', 'close']].min(axis=1) - df['low']
    df['upper_shadow'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['jarak_ema'] = df['close'] - df['EMA_50'] # Jarak harga ke EMA

    # Cari nama kolom dinamis buat jaga-jaga
    col_macd = [c for c in df.columns if c.startswith('MACD_')][0]
    
    # 🎯 BIKIN KUNCI JAWABAN (TARGET Y)
    # 1 = Harga naik di candle berikutnya, 0 = Harga turun
    df['target'] = (df['close'].shift(-1) > df['close']).astype(int)
    
    # Hapus data kosong (NaN) gara-gara indikator lagging
    df.dropna(inplace=True)
    
    # Pilih bahan belajar
    fitur = ['RSI_14', 'MFI_14', col_macd, 'body_size', 'lower_shadow', 'upper_shadow', 'jarak_ema']
    X = df[fitur]
    y = df['target']
    
    # 🎓 PROSES TRAINING (Membangun Pohon Keputusan)
    print("⚙️ AI sedang belajar pola rahasia Emas...")
    model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
    model.fit(X, y)
    print("✅ AI Selesai Belajar! Akurasi masa lalu siap diuji.")
    
    return model, fitur, df.iloc[-1] # Balikin modelnya biar bisa dipake nebak

# ==========================================
# 3. OTAK PREDIKSI LIVE (INFERENCE)
# ==========================================
def prediksi_live_ai(symbol, model, fitur):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 100)
    if rates is None: return None, "WAIT"
    
    df = pd.DataFrame(rates)
    df.rename(columns={'tick_volume': 'volume'}, inplace=True) 
    
    df.ta.ema(length=50, append=True)          
    df.ta.rsi(length=14, append=True)          
    df.ta.macd(append=True)                    
    df.ta.mfi(length=14, append=True)
    df.ta.atr(length=14, append=True)
    
    df['body_size'] = abs(df['open'] - df['close'])
    df['lower_shadow'] = df[['open', 'close']].min(axis=1) - df['low']
    df['upper_shadow'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['jarak_ema'] = df['close'] - df['EMA_50']
    
    df.dropna(inplace=True)
    
    # Ambil data candle TERBARU yang udah fix tutup
    data_sekarang = df.iloc[-1][fitur].to_frame().T 
    
    # 🔮 MINTA AI MENEBAK
    probabilitas = model.predict_proba(data_sekarang)[0]
    prob_turun = probabilitas[0] * 100
    prob_naik = probabilitas[1] * 100
    
    col_atr = [c for c in df.columns if c.startswith('ATR')][0] 
    atr_skrg = df.iloc[-1][col_atr]

    signal = "WAIT"
    # 🔥 Kalo AI YAKIN BANGET (> 65% probabilitas), BARU SIKAT!
    if prob_naik > 65.0:
        print(f"🤖 AI Yakin {prob_naik:.1f}% Harga M1 BAKAL NAIK!")
        signal = "BUY"
    elif prob_turun > 65.0:
        print(f"🤖 AI Yakin {prob_turun:.1f}% Harga M1 BAKAL TURUN!")
        signal = "SELL"
        
    return atr_skrg, signal

# ==========================================
# 4. EKSEKUSI & CLOSE ORDER (SAMA KAYA V8.3)
# ==========================================
def eksekusi_order(symbol, tipe_order, atr): 
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None: return None
        price = tick.ask if tipe_order == 0 else tick.bid
        hard_sl = price - (atr * 3.0) if tipe_order == 0 else price + (atr * 3.0)
        hard_tp = price + (atr * 6.0) if tipe_order == 0 else price - (atr * 6.0)
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol, "volume": LOT_SIZE, "type": tipe_order,
            "price": price, "sl": hard_sl, "tp": hard_tp, "deviation": 20, 
            "magic": MAGIC_NUMBER, "comment": "Skynet ML V1",
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_FOK, 
        }
        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"✅ AI MENEMBAK {'BUY' if tipe_order == 0 else 'SELL'} di {price}")
            return result.order
    except: pass
    return None

def close_order(ticket, symbol, tipe_order):
    try:
        tick = mt5.symbol_info_tick(symbol)
        price = tick.bid if tipe_order == 0 else tick.ask
        tipe_close = 1 if tipe_order == 0 else 0
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": LOT_SIZE,
            "type": tipe_close, "position": ticket, "price": price, "deviation": 20,
            "magic": MAGIC_NUMBER, "comment": "AI Close",
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_FOK, 
        }
        mt5.order_send(request)
    except: pass

# ==========================================
# 5. JANTUNG BOT (LOOP)
# ==========================================
def jalankan_bot():
    if not mt5.initialize(): return

    print(f"🚀 ANJAYY! BOT AI MACHINE LEARNING V1 SIAP...")
    
    # 🧠 Waktu Pertama Jalan, Latih Dulu AI-nya!
    otak_ai, list_fitur, _ = latih_otak_ai(SYMBOL)
    if otak_ai is None: return
    
    account_info = mt5.account_info()
    batas_loss = account_info.equity * BATAS_LOSS_HARIAN
    last_entry_time = 0

    try:
        while True:
            if mt5.account_info().equity < batas_loss:
                mt5.shutdown(); quit()

            posisi_bot = [p for p in mt5.positions_get(symbol=SYMBOL) if p.magic == MAGIC_NUMBER] if mt5.positions_get(symbol=SYMBOL) else []
            
            for p in posisi_bot:
                if p.profit >= CUAN_KILAT_USD or p.profit <= CUTLOSS_KILAT_USD:
                    close_order(p.ticket, SYMBOL, p.type)

            if len(posisi_bot) < MAX_LAYER:
                if time.time() - last_entry_time > 60: # Cek per 1 candle
                    atr, signal = prediksi_live_ai(SYMBOL, otak_ai, list_fitur)
                    
                    if signal == "WAIT": 
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] AI masih meramal masa depan...")
                    else:
                        tipe = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
                        if eksekusi_order(SYMBOL, tipe, atr):
                            last_entry_time = time.time()

            time.sleep(1) 

    except KeyboardInterrupt:
        mt5.shutdown()

if __name__ == "__main__":
    jalankan_bot()