import os
import requests
import yfinance as yf
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from dotenv import load_dotenv

load_dotenv()

# ---------- LLM ----------
llm = ChatOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
    model="deepseek-chat",
    temperature=0.7,
)

# ---------- API Keys ----------
FRED_API_KEY = os.getenv("FRED_API_KEY")

# ---------- MacroAgent ----------
class MacroAgent:
    def __init__(self):
        self.system_prompt = """คุณคือ MacroAgent นักวิเคราะห์เศรษฐกิจมหภาคระดับโลก
        คุณมีความเชี่ยวชาญใน GDP, CPI, อัตราเงินเฟ้อ, อัตราดอกเบี้ย, นโยบายการเงิน
        ตอบอย่างมืออาชีพ ใช้ตัวเลขและแหล่งที่มา"""

    def get_fred_data(self, series_id):
        if not FRED_API_KEY:
            return None
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                obs = data.get("observations", [])
                return obs[0].get("value") if obs else None
        except Exception:
            return None
        return None

    def get_economic_indicators(self):
        indicators = {}
        gdp = self.get_fred_data("GDPC1")
        if gdp:
            indicators["GDP"] = f"{float(gdp):.2f} พันล้าน USD"
        cpi = self.get_fred_data("CPIAUCSL")
        if cpi:
            indicators["CPI"] = f"{float(cpi):.1f}"
        fed = self.get_fred_data("DFF")
        if fed:
            indicators["Fed Funds Rate"] = f"{float(fed):.2f}%"
        unemp = self.get_fred_data("UNRATE")
        if unemp:
            indicators["Unemployment"] = f"{float(unemp):.1f}%"
        return indicators

    def get_market_summary(self):
        indices = {"S&P500": "^GSPC", "NASDAQ": "^IXIC", "Dow Jones": "^DJI"}
        summary = ""
        for name, sym in indices.items():
            try:
                ticker = yf.Ticker(sym)
                hist = ticker.history(period="2d")
                if not hist.empty:
                    price = hist['Close'].iloc[-1]
                    prev = hist['Close'].iloc[-2] if len(hist) > 1 else price
                    change = (price - prev) / prev * 100
                    summary += f"{name}: {price:.2f} ({change:+.2f}%)\n"
            except Exception:
                summary += f"{name}: N/A\n"
        return summary

    def run(self, question: str, history: list = None):
        eco_data = self.get_economic_indicators()
        eco_text = "\n".join([f"- {k}: {v}" for k, v in eco_data.items()])
        market_text = self.get_market_summary()
        system = self.system_prompt + f"""
        ข้อมูลเศรษฐกิจล่าสุด (FRED):
        {eco_text}
        ข้อมูลตลาดล่าสุด:
        {market_text}
        """
        messages = [SystemMessage(content=system)]
        if history:
            for m in history[-6:]:
                if m["role"] == "user":
                    messages.append(HumanMessage(content=m["content"]))
                elif m["role"] == "assistant":
                    messages.append(AIMessage(content=m["content"]))
        messages.append(HumanMessage(content=question))
        response = llm.invoke(messages)
        return response.content

# ---------- PortfolioAgent ----------
class PortfolioAgent:
    def __init__(self):
        self.system_prompt = """คุณคือ PortfolioAgent ผู้เชี่ยวชาญด้านการลงทุนและการจัดพอร์ต
        คุณมีความเชี่ยวชาญใน Modern Portfolio Theory, Asset Allocation,
        การวิเคราะห์หุ้น (P/E, EPS), Risk Management"""

    def get_stock_data(self, symbol):
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            return {
                "price": info.get("regularMarketPrice"),
                "pe": info.get("trailingPE"),
                "eps": info.get("trailingEps"),
                "change": info.get("regularMarketChangePercent")
            }
        except Exception:
            return None

    def run(self, question: str, history: list = None):
        symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL"]
        stock_text = ""
        for sym in symbols[:2]:
            data = self.get_stock_data(sym)
            if data and data.get("price"):
                stock_text += f"- {sym}: ${data['price']:.2f} (P/E: {data.get('pe', 'N/A')})\n"
        system = self.system_prompt + f"""
        ข้อมูลหุ้นตัวอย่าง (ล่าสุด):
        {stock_text if stock_text else 'ไม่สามารถดึงข้อมูลหุ้นได้'}
        """
        messages = [SystemMessage(content=system)]
        if history:
            for m in history[-6:]:
                if m["role"] == "user":
                    messages.append(HumanMessage(content=m["content"]))
                elif m["role"] == "assistant":
                    messages.append(AIMessage(content=m["content"]))
        messages.append(HumanMessage(content=question))
        response = llm.invoke(messages)
        return response.content

# ---------- Agent Factory ----------
def get_agent(agent_type: str):
    if agent_type == "macro":
        return MacroAgent()
    elif agent_type == "portfolio":
        return PortfolioAgent()
    return None
