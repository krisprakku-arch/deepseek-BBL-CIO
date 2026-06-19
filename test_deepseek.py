import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
)

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[
        {"role": "system", "content": "คุณคือผู้ช่วยนักลงทุน"},
        {"role": "user", "content": "สวัสดีครับ ทดสอบ"}
    ]
)

print(response.choices[0].message.content)
