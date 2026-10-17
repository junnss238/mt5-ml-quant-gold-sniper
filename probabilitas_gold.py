import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# 1. Tarik data histori Gold (XAUUSD) 1 tahun terakhir
print("Lagi narik data dari Yahoo Finance... Sabar ya Jun!")
gold = yf.download("GC=F", period="1y", interval="1d") # GC=F itu Gold Futures

# 2. Hitung 'Range' harian (Selisih High - Low) dalam Pips
# Rumus: (High - Low) * 10 (asumsi 1 point = 10 pips)
gold['Range_Pips'] = (gold['High'] - gold['Low']) * 10

# 3. Hitung Probabilitas Sederhana
rata_rata = gold['Range_Pips'].mean()
di_atas_200 = gold[gold['Range_Pips'] > 200].shape[0]
total_hari = gold.shape[0]
prob_brutal = (di_atas_200 / total_hari) * 100

print(f"\n--- HASIL ANALISIS PROBABILITAS JUN ---")
print(f"Total data: {total_hari} hari")
print(f"Rata-rata pergerakan harian: {rata_rata:.2f} Pips")
print(f"Hari dengan gerak > 200 Pips: {di_atas_200} hari")
print(f"Probabilitas Gold gerak BRUTAL (>200 pips): {prob_brutal:.2f}%")

# 4. Visualisasi pake Matplotlib (Histogram)
plt.figure(figsize=(10, 6))
plt.hist(gold['Range_Pips'], bins=30, color='gold', edgecolor='black', alpha=0.7)

# Tambahin garis rata-rata
plt.axvline(rata_rata, color='red', linestyle='dashed', linewidth=2, label=f'Rata-rata: {rata_rata:.0f} pips')

plt.title("Distribusi Probabilitas Pergerakan Harian Gold (1 Tahun Terakhir)")
plt.xlabel("Besar Pergerakan (Pips)")
plt.ylabel("Frekuensi (Jumlah Hari)")
plt.legend()
plt.grid(axis='y', alpha=0.3)

print("\nGrafik lagi dibuat... Cek layarmu!")
plt.show()