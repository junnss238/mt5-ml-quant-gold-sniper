import MetaTrader5 as mt5
import pandas as pd

# Kasih alamat lengkap biar Python gak nyasar
# Pake 'r' di depan kutip biar backslash (\) dibaca bener ama Python
path_mt5 = r"C:\Program Files\MetaTrader 5\terminal64.exe"

if not mt5.initialize(path=path_mt5):
    print(f"Yah, gagal connect lagi Jun. Error code: {mt5.last_error()}")
    quit()

# Kalau tembus, ambil info akun
account_info = mt5.account_info()
if account_info is not None:
    print("-" * 30)
    print("🔥 KONEKSI BERHASIL, JUN! 🔥")
    print(f"Nama Akun : {account_info.name}")
    print(f"Broker    : {account_info.company}")
    print(f"Balance   : ${account_info.balance}")
    print("-" * 30)

    # Cek harga Gold detik ini
    symbol = "XAUUSD"
    tick = mt5.symbol_info_tick(symbol)
    if tick:
        print(f"Harga {symbol} Real-time:")
        print(f">> BUY  : {tick.ask}")
        print(f">> SELL : {tick.bid}")
else:
    print("Konek sih, tapi info akun gak kebaca. Login dulu di MT5-nya!")

mt5.shutdown()