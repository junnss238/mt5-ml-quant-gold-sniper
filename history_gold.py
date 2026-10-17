import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime

# 1. Koneksi
path_mt5 = r"C:\Program Files\MetaTrader 5\terminal64.exe"
if not mt5.initialize(path=path_mt5):
    print("Gagal inisialisasi!")
    quit()

# 2. Tarik Data Histori (100 Menit terakhir sebelum market tutup)
# TIMEFRAME_M1 = 1 Menit
# 0 = Mulai dari data terbaru (Jumat malam)
# 100 = Ambil 100 bar/lilin
rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M1, 0, 100)

# 3. Ubah jadi DataFrame (Tabel ala Excel)
df = pd.DataFrame(rates)

# Konversi waktu biar enak dibaca manusia (WIB)
df['time'] = pd.to_datetime(df['time'], unit='s')

# 4. Hitung Sesuatu yang Berfaedah (Indikator Manual)
# Karena pandas_ta belum bisa di 3.14, kita hitung manual pake logic pandas:
# Kita hitung Moving Average (Rata-rata harga 10 menit terakhir)
df['SMA_10'] = df['close'].rolling(window=10).mean()

# 5. Tampilkan Hasil
print("-" * 50)
print("📊 DATA 10 MENIT TERAKHIR SEBELUM MARKET TUTUP 📊")
print("-" * 50)
# tampilin 10 baris terakhir aja biar gak kepenuhan
print(df[['time', 'open', 'high', 'low', 'close', 'SMA_10']].tail(10))

mt5.shutdown()