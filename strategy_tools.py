import yfinance as yf

def get_stock_info(symbol):
    ticker = yf.Ticker(symbol)
    info = ticker.info
    price = info.get("regularMarketPrice")
    pe = info.get("trailingPE")
    market_cap = info.get("marketCap")
    return f"""
หุ้น {symbol.upper()}
ราคา: {price} USD
P/E: {pe}
มูลค่าตลาด: {market_cap:,} USD
"""

def simple_asset_allocation(risk="ปานกลาง"):
    if risk == "เสี่ยงต่ำ":
        return "หุ้น 30% / พันธบัตร 50% / เงินสด 20%"
    elif risk == "ปานกลาง":
        return "หุ้น 60% / พันธบัตร 30% / ทองคำ 5% / เงินสด 5%"
    elif risk == "เสี่ยงสูง":
        return "หุ้น 80% / พันธบัตร 10% / สกุลเงินดิจิทัล 5% / ทองคำ 5%"
    else:
        return "หุ้น 60% / พันธบัตร 30% / เงินสด 10%"
