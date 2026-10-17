import MetaTrader5 as mt5
import time
import os
from datetime import datetime

# 1. Konfigurasi Awal
symbol = "BTCUSD"  # Besok pagi tinggal ganti jadi "XAUUSD"
path_mt5 = r"C:\Program Files\MetaTrader 5\terminal64.exe"

def bersihkan_layar():
    os.system('cls' if os.name == 'nt' else 'clear')

# Hubungkan ke "Jantung" Market
if not mt5.initialize(path=path_mt5):
    print("Gagal inisialisasi MT5!")
    quit()

print(f"🚀 Sniper Aktif! Memantau {symbol} tanpa henti...")
time.sleep(2)

try:
    while True:
        # A. Ambil Data Real-time (Tick)
        tick = mt5.symbol_info_tick(symbol)
        
        if tick:
            bersihkan_layar()
            waktu_skrg = datetime.now().strftime("%H:%M:%S")
            
            # B. Logika Decision (Sederhana tapi Kompleks)
            spread = (tick.ask - tick.bid) * 100 # Itung pips
            
            print("=" * 40)
            print(f" 🟢 ARJUN REAL-TIME DASHBOARD [{waktu_skrg}]")
            print("=" * 40)
            print(f"SYMBOL      : {symbol}")
            print(f"BID (SELL)  : ${tick.bid:,.2f}")
            print(f"ASK (BUY)   : ${tick.ask:,.2f}")
            print(f"SPREAD      : {spread:.2f} pips")
            print("-" * 40)

            # C. Decision Zone
            # Contoh logic: Kalau harga nyentuh angka psikologis
            if tick.bid > 65000:
                print("📢 STATUS: HARGA LAGI TINGGI! (Hati-hati)")
            else:
                print("📢 STATUS: HARGA MASIH SIDEWAYS")
            
            print("-" * 40)
            print("Tekan [Ctrl + C] di keyboard buat stop.")
            
        # D. Jeda Detik (Interval Update)
        # Ganti ke 1 kalau mau beneran tiap detik, atau 60 kalau mau per menit
        time.sleep(2) 

except KeyboardInterrupt:
    print("\n\nSistem dimatikan. Selamat istirahat, Jun!")
    mt5.shutdown()