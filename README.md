# ⚡ Gold Sniper Pro: MT5 ML-Powered Algorithmic Trading Engine

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MetaTrader 5](https://img.shields.io/badge/MetaTrader_5-Direct_IPC_Bridge-blue)](https://www.mql5.com/)
[![Scikit-Learn](https://img.shields.io/badge/ML-Scikit--Learn_Random_Forest-F7931E?logo=scikit-learn&logoColor=white)](https://scikit-learn.org/)
[![Pandas TA](https://img.shields.io/badge/Technical_Analysis-Pandas_TA-38B2AC)](https://github.com/twopirllc/pandas-ta)
[![Asset Class](https://img.shields.io/badge/Asset-XAUUSD%20%7C%20Gold-FFD700)](https://en.wikipedia.org/wiki/Gold_as_an_investment)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**Gold Sniper Pro** is an institutional-grade, multi-strategy quantitative algorithmic trading engine built for high-frequency M1 scalping on **XAUUSD (Spot Gold)** and cryptocurrency markets. The system synthesizes statistical arbitrage, institutional price action (Fair Value Gaps / Liquidity Imbalances), and ensemble Machine Learning (`RandomForestClassifier`) directly interfaced via MetaTrader 5 (MT5) IPC API.

---

## 🔬 Mathematical & Algorithmic Architecture

The engine operates on a multi-tier confluence decision tree, executing market orders only when strict statistical thresholds are satisfied.

```plaintext
                   ┌───────────────────────────────────┐
                   │    Live Market Ingestion (M1)    │
                   │    MetaTrader 5 Real-Time Feed    │
                   └─────────────────┬─────────────────┘
                                     │
                   ┌─────────────────▼─────────────────┐
                   │     Pre-Trade Risk & Spread       │
                   │   Filter (Spread ≤ Threshold)     │
                   └─────────────────┬─────────────────┘
                                     │
         ┌───────────────────────────┴───────────────────────────┐
         │                                                       │
┌────────▼──────────────────────────┐   ┌────────────────────────▼──────────────────────────┐
│      Institutional ICT Engine     │   │         Machine Learning Inference Engine         │
│  - Fair Value Gap (FVG) Detection │   │  - 3,000 Bar Rolling Training Window              │
│  - Volume Imbalance & Spikes      │   │  - RandomForestClassifier Probability Scoring     │
│  - Dynamic ATR Expansion Bounds   │   │  - Feature Space: RSI, MACD, Bollinger Bands, ATR │
└────────────────┬──────────────────┘   └────────────────────────┬──────────────────────────┘
                 │                                               │
                 └───────────────────────────┬───────────────────┘
                                             │
                                ┌────────────▼────────────┐
                                │ Multi-Timeframe Filter  │
                                │   (M5 Trend Validator)  │
                                └────────────┬────────────┘
                                             │
                                ┌────────────▼────────────┐
                                │   Confluence Score ≥ 3  │
                                └────────────┬────────────┘
                                             │
                        ┌────────────────────┴────────────────────┐
                        │                                         │
              [Confluence Met]                         [Confluence Failed]
                        │                                         │
            ┌───────────▼───────────┐                        ┌────▼────┐
            │ Position Execution &  │                        │ Discard │
            │ Dynamic Breakeven SL  │                        │  Tick   │
            └───────────────────────┘                        └─────────┘
```

---

## 🚀 Key Technological Modules

### 1. 🤖 Ensemble Machine Learning Inference (`MachineLearning.py`)
* **Rolling Re-Training:** Continuously trains an ensemble `RandomForestClassifier` (100 estimators) over a dynamic window of 3,000 M1 bars.
* **Engineered Feature Space:**
  * Relative Strength Index ($RSI_{14}$)
  * Moving Average Convergence Divergence ($MACD$ histogram & signal divergence)
  * Normalized ATR Volatility ($ATR_{14}$)
  * Multi-EMA trend orientation ($EMA_{9}, EMA_{21}, EMA_{50}$)
  * Bollinger Bands %b dynamic volatility expansion.
* **Confidence Gating:** Trades are rejected unless model directional confidence satisfies $P(Direction) \ge \tau_{confidence}$.

### 2. 🏛️ Institutional Price Action & Liquidity Confluence
* **Fair Value Gap (FVG):** Detects 3-bar institutional displacement imbalances:
  $$\text{Bullish FVG} = \text{Low}_{i} > \text{High}_{i-2}$$
  $$\text{Bearish FVG} = \text{High}_{i} < \text{Low}_{i-2}$$
* **Multi-Timeframe Trend Confirmation:** M1 scalping triggers must align with the broader M5 directional bias ($EMA_{50}$ slope) to prevent false breakouts.
* **Dynamic Spread Guard:** Live spread evaluation against dynamic thresholds to prevent slippage during rollover or news releases.

### 3. 🛡️ Risk Management & Capital Preservation
* **Dynamic Breakeven Trailing:** Position stop-loss auto-shifts to Breakeven $+ \delta$ immediately once profit targets ($1.5 \times ATR$) are reached.
* **Daily Equity Drawdown Cutoff:** Hard-coded circuit breaker terminating bot execution if account equity drops below daily drawdown thresholds (e.g. 95% of initial balance).
* **Idempotent Magic Number Isolation:** All orders tagged with unique Magic Numbers for isolated multi-strategy operation on single accounts.

---

## 📂 Codebase Structure

```plaintext
mt5-ml-quant-gold-sniper/
├── botpintar.py          # Primary Multi-Factor Confluence Production Engine (v3.0)
├── GoldBlitz.py          # High-Frequency Low-Latency Execution Strategy
├── MachineLearning.py    # Random Forest Model Training, Inference, and Feature Pipeline
├── RadaAgresif.py        # Volatility-Breakout Adaptive Scalper
├── supercuri.py          # Momentum & Micro-Order Book Imbalance Strategy
├── sniper_realtime_btc.py# Dedicated Real-Time BTC/USD Crypto Scalper
├── history_gold.py       # Historical Tick & Bar Data Ingestion Engine
├── live_gold.py          # High-Frequency Real-Time WebSocket/IPC Streamer
├── probabilitas_gold.py  # Statistical Probability & Win-Rate Distribution Analyzer
├── tes_koneksi.py        # Broker Handshake & Network Latency Benchmark
├── requirements.txt      # Python Dependencies
├── LICENSE               # MIT License
└── README.md
```

---

## ⚙️ Setup & Execution

### Prerequisites
* Windows 10/11 or Windows Server (Native MetaTrader 5 Desktop client installed).
* Python 3.10+ (64-bit).
* MetaTrader 5 Broker Account (Demo or Live with Algo Trading enabled).

### 1. Installation
```bash
git clone https://github.com/junnss238/mt5-ml-quant-gold-sniper.git
cd mt5-ml-quant-gold-sniper
pip install -r requirements.txt
```

### 2. Configuration
Open `botpintar.py` (or set environment variables) with your MT5 terminal credentials:
```python
class CFG:
    SYMBOL:       str   = "XAUUSD"
    TIMEFRAME           = mt5.TIMEFRAME_M1
    LOT_SIZE:     float = 0.01
    MAX_SPREAD:   int   = 30
    MT5_LOGIN:    int   = 0            # Enter MT5 Account ID (or 0 for active terminal)
    MT5_PASSWORD: str   = ""           # Enter MT5 Password
    MT5_SERVER:   str   = "ICMarkets"  # Broker Server Name
```

### 3. Broker Connection Benchmark
```bash
python tes_koneksi.py
```

### 4. Running the Quantitative Engine
```bash
python botpintar.py
```

---

## ⚠️ Disclaimer
*This repository is created for educational and quantitative research purposes. Algorithmic trading and leveraged derivatives involve substantial financial risk. Past statistical performance does not guarantee future profitability.*

## 👤 Author
* **M Arjun Nabila** — [GitHub (@junnss238)](https://github.com/junnss238)
* Undergraduate Student in Informatics (TI) at UPN "Veteran" Yogyakarta & Sharia Economic Law (HES).

## 📄 License
This project is licensed under the [MIT License](LICENSE).
