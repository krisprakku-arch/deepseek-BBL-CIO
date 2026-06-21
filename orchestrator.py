import os
import re
from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from dotenv import load_dotenv
from specialist_agents import get_agent

load_dotenv()

class AgentState(TypedDict):
    messages: List[Dict[str, str]]
    question: str
    answer: str
    current_agent: str
    agent_type: str

llm = ChatOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
    model="deepseek-chat",
    temperature=0.7,
)

def route_question(state: AgentState) -> str:
    question = state.get("question", "").lower()
    eco_keywords = ["gdp","cpi","เงินเฟ้อ","ดอกเบี้ย","fed","เศรษฐกิจ","pmi","recession","unemployment","ว่างงาน","ตลาด","ดัชนี","index","s&p","sp500","nasdaq","dow jones","set","หุ้นสหรัฐ"]
    invest_keywords = ["พอร์ต","ลงทุน","หุ้น","stock","portfolio","asset","allocation","dividend","pe","p/e","risk","ความเสี่ยง","aapl","msft","nvda","tsla","googl","amzn"]
    if any(kw in question for kw in eco_keywords):
        return "macro"
    elif any(kw in question for kw in invest_keywords):
        return "portfolio"
    return "general"

def general_agent(state: AgentState) -> AgentState:
    messages = state.get("messages", [])
    question = state.get("question", "")
    system_prompt = "คุณคือผู้ช่วยด้านการลงทุนทั่วไป ตอบคำถามอย่างมืออาชีพ ใช้ภาษาไทย"
    msgs = [SystemMessage(content=system_prompt)]
    for m in messages[-6:]:
        if m["role"] == "user":
            msgs.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            msgs.append(AIMessage(content=m["content"]))
    msgs.append(HumanMessage(content=question))
    response = llm.invoke(msgs)
    state["answer"] = response.content
    state["current_agent"] = "general"
    return state

def specialist_agent(state: AgentState) -> AgentState:
    agent_type = state.get("agent_type", "general")
    agent = get_agent(agent_type)
    if agent:
        answer = agent.run(question=state["question"], history=state.get("messages", []))
    else:
        answer = "ไม่พบ Agent ที่เหมาะสม"
    state["answer"] = answer
    state["current_agent"] = agent_type
    return state

builder = StateGraph(AgentState)
builder.add_node("general", general_agent)
builder.add_node("macro", specialist_agent)
builder.add_node("portfolio", specialist_agent)
builder.set_entry_point("general")
builder.add_conditional_edges(
    "general",
    route_question,
    {"general": "general", "macro": "macro", "portfolio": "portfolio"}
)
builder.add_edge("macro", END)
builder.add_edge("portfolio", END)
builder.add_edge("general", END)
graph = builder.compile()

def run_orchestrator(question: str, history: List[Dict[str, str]] = None) -> str:
    if history is None:
        history = []
    q_lower = question.lower()
    eco_keywords = ["gdp","cpi","เงินเฟ้อ","ดอกเบี้ย","fed","เศรษฐกิจ","pmi","recession","unemployment","ว่างงาน","ตลาด","ดัชนี","index","s&p","sp500","nasdaq","dow jones","set","หุ้นสหรัฐ"]
    invest_keywords = ["พอร์ต","ลงทุน","หุ้น","stock","portfolio","asset","allocation","dividend","pe","p/e","risk","ความเสี่ยง","aapl","msft","nvda","tsla","googl","amzn"]
    agent_type = "general"
    if any(kw in q_lower for kw in eco_keywords):
        agent_type = "macro"
    elif any(kw in q_lower for kw in invest_keywords):
        agent_type = "portfolio"
    state = {
        "messages": history,
        "question": question,
        "answer": "",
        "current_agent": "",
        "agent_type": agent_type
    }
    result = graph.invoke(state)
    return result["answer"]
