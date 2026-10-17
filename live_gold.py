import MetaTrader5 as mt5
import time
import os

# 1. Konekin dulu
path_mt5 = r"C:\Program Files\MetaTrader 5\terminal64.exe"
if not mt5.initialize(path=path_mt5):
    print("Gagal inisialisasi!")
    quit()

symbol = "XAUUSD" # Sesuaikan kalau di HFM namanya 'GOLD' atau 'XAUUSD.v'

print(f"--- MENGAMATI PERGERAKAN {symbol} ---")
print("Tekan Ctrl+C buat berhenti ya, Jun!\n")

try:
    while True:
        # Ambil data tick terakhir (harga paling update)
        tick = mt5.symbol_info_tick(symbol)
        
        if tick:
            # Clear terminal biar gak numpuk (Windows)
            # os.system('cls') 
            
            print(f"🕒 Waktu: {time.ctime(tick.time)}")
            print(f"💰 BID (Sell): {tick.bid}")
            print(f"💰 ASK (Buy) : {tick.ask}")
            print(f"📊 Spread    : {round((tick.ask - tick.bid)*100, 2)} pips")
            print("-" * 20)
        else:
            print(f"Simbol {symbol} gak ketemu, Jun. Cek lagi di Market Watch!")
        
        # Delay 1 detik biar gak panas laptopnya
        time.sleep(1)

except KeyboardInterrupt:
    print("\n\nPengamatan selesai. Sampai jumpa besok pagi pas market buka!")
    mt5.shutdown()