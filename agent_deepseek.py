import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from secretary_tools import add_event, get_today_events
from economics_tools import get_us_gdp, get_inflation_indicator, get_interest_rate
from strategy_tools import get_stock_info, simple_asset_allocation

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
)

tools = [
    {
        "type": "function",
        "function": {
            "name": "add_event",
            "description": "เพิ่มนัดหมายลงในปฏิทิน",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "date_str": {"type": "string", "description": "YYYY-MM-DD"},
                    "time_str": {"type": "string", "description": "HH:MM (optional)"}
                },
                "required": ["title", "date_str"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_today_events",
            "description": "ดูนัดหมายของวันนี้"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_us_gdp",
            "description": "ดูตัวชี้วัดเศรษฐกิจสหรัฐ (อัตราผลตอบแทนพันธบัตร 10 ปี)"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_inflation_indicator",
            "description": "ดูความคาดหวังเงินเฟ้อจาก ETF TIP"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_interest_rate",
            "description": "ดูอัตราดอกเบี้ยระยะสั้น (T-bill 3 เดือน)"
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_info",
            "description": "ดูข้อมูลพื้นฐานของหุ้น (ราคา, P/E, มูลค่าตลาด)",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"}
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "simple_asset_allocation",
            "description": "แนะนำสัดส่วนการลงทุนตามระดับความเสี่ยง",
            "parameters": {
                "type": "object",
                "properties": {
                    "risk": {"type": "string", "enum": ["เสี่ยงต่ำ", "ปานกลาง", "เสี่ยงสูง"]}
                },
                "required": []
            }
        }
    }
]

available_functions = {
    "add_event": add_event,
    "get_today_events": get_today_events,
    "get_us_gdp": get_us_gdp,
    "get_inflation_indicator": get_inflation_indicator,
    "get_interest_rate": get_interest_rate,
    "get_stock_info": get_stock_info,
    "simple_asset_allocation": simple_asset_allocation
}

def run_agent(user_input):
    messages = [
        {"role": "system", "content": "คุณคือผู้ช่วยอัจฉริยะที่มีสามบทบาท: 1. เลขา 2. นักเศรษฐศาสตร์ 3. นักกลยุทธ์การลงทุน ตอบอย่างมืออาชีพ กระชับ และเป็นประโยชน์"},
        {"role": "user", "content": user_input}
    ]

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )

    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls

    if tool_calls:
        # เปลี่ยนเป็น dict เพื่อ append
        messages.append(response_message.model_dump())
        
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            function_to_call = available_functions[function_name]
            result = function_to_call(**function_args)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(result)
            })
        
        final_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages
        )
        return final_response.choices[0].message.content
    else:
        return response_message.content

if __name__ == "__main__":
    print("🤖 DeepSeek Agent (เลขา+เศรษฐศาสตร์+กลยุทธ์) พร้อมทำงาน")
    print("พิมพ์ 'exit' เพื่อออก\n")
    while True:
        user = input("คุณ: ")
        if user.lower() == "exit":
            break
        reply = run_agent(user)
        print(f"\nAgent: {reply}\n")
