import yfinance as yf

def get_us_gdp():
    tmx = yf.Ticker("^TNX")
    yield_ = tmx.history(period="1d")["Close"].iloc[-1]
    return f"อัตราผลตอบแทนพันธบัตรรัฐบาลสหรัฐอายุ 10 ปี: {yield_:.2f}%"

def get_inflation_indicator():
    tip = yf.Ticker("TIP")
    price = tip.history(period="1d")["Close"].iloc[-1]
    return f"ETF TIP (พันธบัตรป้องกันเงินเฟ้อ) ราคา {price:.2f} USD"

def get_interest_rate():
    irx = yf.Ticker("^IRX")
    rate = irx.history(period="1d")["Close"].iloc[-1]
    return f"อัตราดอกเบี้ย T-bill 3 เดือน: {rate:.2f}%"
