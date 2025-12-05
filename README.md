# Trading Case Study Portfolio — Banu Surya Ganea Wijaya

_A real trade journal designed to showcase structured decision-making, not only P&L._

This portfolio demonstrates how I approach financial markets with:
- clear trade thesis,
- disciplined risk management,
- post-trade review & reflection,
- and continuous tactical improvement.

The interface separates:
- **Public Case Studies** → shows only structured decision & outcomes (for HR)
- **Private Workspace** → includes emotional review & internal notes (only visible to owner)

---

## 🚀 Live Deployment
Available online (production):  
👉 https://banu-trading-portfolio-production.up.railway.app
---

## 💡 Core Features

| Category | Description |
|--------|-------------|
| 📈 Market Case Studies | Each trade includes thesis, risk, narrative, and result scoring |
| 🔐 Owner Mode (Admin) | Add, edit, delete trades — includes private notes |
| 🧮 Risk Discipline Metrics | R multiple tracking, discipline score, performance summary |
| 📊 Equity Curve | Calculated automatically from closed R outcomes |
| 🌎 Live Market Data | TradingView Ticker Tape + Market Overview + Economic Calendar |
| 🖼 Screenshots | Before & After trade execution upload |

---

## 🧠 Data Model

| Field | Example | Purpose |
|------|---------|---------|
| Symbol | BTCUSDT | What market traded |
| Direction | BUY / SELL | Position direction |
| R:R Ratio | 2.5R | Reward vs risk efficiency |
| Result R | +2.5R / -1R / 0R | Performance consistency |
| Discipline Score | % compliance to rules | Behavioral alpha tracking |

---

## 🛠 Tech Stack

| Layer | Tools |
|------|------|
| Backend | Python, Flask, SQLite |
| Frontend | HTML5 + Liquid Glass UI |
| Deployment | Render Cloud Platform |
| Analytics | Custom Python functions (R score, win rate, equity curve) |

---

## 🧪 Local Development

```bash
git clone https://github.com/banuwij/trading-portfolio.git
cd trading-portfolio
pip install -r requirements.txt
python app.py
