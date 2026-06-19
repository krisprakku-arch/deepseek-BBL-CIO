import os
import re
from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from dotenv import load_dotenv
from specialist_agents import get_agent
from rag_pipeline import search_vector_store, web_search

load_dotenv()

# ---------- State ----------
class AgentState(TypedDict):
    messages: List[Dict[str, str]]
    question: str
    answer: str
    current_agent: str
    agent_type: str
    rag_context: str
    web_context: str

# ---------- LLM ----------
llm = ChatOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
    model="deepseek-chat",
    temperature=0.7,
)

# ---------- Router ----------
def route_question(state: AgentState) -> str:
    question = state.get("question", "").lower()
    
    eco_keywords = [
        "gdp", "cpi", "เงินเฟ้อ", "ดอกเบี้ย", "fed", "เศรษฐกิจ", "pmi",
        "recession", "unemployment", "ว่างงาน", "ตลาด", "ดัชนี", "index",
        "s&p", "sp500", "s&p 500", "nasdaq", "dow jones", "set", "หุ้นสหรัฐ",
        "สหรัฐ", "อเมริกา", "เฟด", "ธนาคารกลาง"
    ]
    invest_keywords = [
        "พอร์ต", "ลงทุน", "หุ้น", "stock", "portfolio", "asset",
        "allocation", "dividend", "pe", "p/e", "risk", "ความเสี่ยง",
        "aapl", "msft", "nvda", "tsla", "googl", "amzn"
    ]
    
    if any(kw in question for kw in eco_keywords):
        return "macro"
    elif any(kw in question for kw in invest_keywords):
        return "portfolio"
    return "general"

# ---------- RAG + Web Search ----------
def rag_search(question: str) -> Dict:
    """ค้นหาเอกสารจาก RAG และ Web"""
    result = {"context": None, "sources": [], "web": None}
    
    # 1. RAG Search
    rag_data = search_vector_store(question, top_k=3)
    if rag_data:
        context = "\n\n".join([d.page_content for d in rag_data])
        sources = list(set([d.metadata.get("source", "ไม่ระบุ") for d in rag_data]))
        result["context"] = context
        result["sources"] = sources
    
    # 2. Web Search (ถ้า RAG ไม่พบ หรือต้องการข้อมูลล่าสุด)
    if not result["context"]:
        web_data = web_search(question)
        if web_data:
            result["web"] = web_data
    
    return result

# ---------- Answer Builder ----------
def build_answer_with_context(question: str, context: str, sources: list, agent_type: str = None) -> str:
    """สร้างคำตอบโดยใช้ context จาก RAG"""
    prompt = f"""คุณคือผู้ช่วยด้านการลงทุนที่เชี่ยวชาญ จงตอบคำถามโดยอ้างอิงจากข้อมูลด้านล่างเท่านั้น

📚 ข้อมูลจากเอกสาร/แหล่งที่มา:
{context}

📌 แหล่งที่มา: {', '.join(sources) if sources else 'ไม่ระบุ'}

❓ คำถาม: {question}

💬 โปรดตอบอย่างละเอียด เป็นภาษาไทย อ้างอิงแหล่งที่มา และบอกว่าข้อมูลนี้มาจากเอกสารหรือแหล่งใด:
"""
    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content

def build_answer_with_web(question: str, web_data: str) -> str:
    """สร้างคำตอบโดยใช้ข้อมูลจาก Web Search"""
    prompt = f"""คุณคือผู้ช่วยด้านการลงทุน จงตอบคำถามโดยอ้างอิงจากข้อมูลจากอินเทอร์เน็ตด้านล่าง

🌐 ข้อมูลจากอินเทอร์เน็ต:
{web_data}

❓ คำถาม: {question}

💬 โปรดตอบอย่างละเอียด เป็นภาษาไทย บอกว่าข้อมูลนี้มาจากการค้นหาทางอินเทอร์เน็ต:
"""
    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content

# ---------- Agent Functions ----------
def general_agent(state: AgentState) -> AgentState:
    """Agent ทั่วไป (ใช้ RAG/Web ก่อน ถ้าไม่มี ค่อยใช้ความรู้เอง)"""
    question = state.get("question", "")
    
    # 1. ลองค้นหาจาก RAG
    rag_result = rag_search(question)
    if rag_result["context"]:
        answer = build_answer_with_context(question, rag_result["context"], rag_result["sources"])
    elif rag_result["web"]:
        answer = build_answer_with_web(question, rag_result["web"])
    else:
        # Fallback ใช้ความรู้ของ LLM
        messages = state.get("messages", [])
        system_prompt = """คุณคือผู้ช่วยด้านการลงทุนทั่วไป ตอบคำถามอย่างมืออาชีพ ใช้ภาษาไทย
        หากมีตัวเลขให้ใส่ตัวเลข ถ้าไม่มีข้อมูลให้บอกว่า "จากข้อมูลที่มี..."
        ไม่แนะนำการซื้อขายเฉพาะเจาะจง"""
        msgs = [SystemMessage(content=system_prompt)]
        for m in messages[-6:]:
            if m["role"] == "user":
                msgs.append(HumanMessage(content=m["content"]))
            elif m["role"] == "assistant":
                msgs.append(AIMessage(content=m["content"]))
        msgs.append(HumanMessage(content=question))
        response = llm.invoke(msgs)
        answer = response.content
    
    state["answer"] = answer
    state["current_agent"] = "general"
    return state

def specialist_agent(state: AgentState) -> AgentState:
    """Specialist Agent (Macro/Portfolio) + RAG/Web"""
    agent_type = state.get("agent_type", "general")
    question = state.get("question", "")
    
    # 1. ลอง RAG ก่อน
    rag_result = rag_search(question)
    if rag_result["context"]:
        answer = build_answer_with_context(question, rag_result["context"], rag_result["sources"])
    elif rag_result["web"]:
        answer = build_answer_with_web(question, rag_result["web"])
    else:
        # ใช้ Specialist Agent
        agent = get_agent(agent_type)
        if agent:
            answer = agent.run(
                question=question,
                history=state.get("messages", [])
            )
        else:
            answer = "ไม่พบ Agent ที่เหมาะสม"
    
    state["answer"] = answer
    state["current_agent"] = agent_type
    return state

# ---------- Build Graph ----------
builder = StateGraph(AgentState)
builder.add_node("general", general_agent)
builder.add_node("macro", specialist_agent)
builder.add_node("portfolio", specialist_agent)

builder.set_entry_point("general")
builder.add_conditional_edges(
    "general",
    route_question,
    {
        "general": "general",
        "macro": "macro",
        "portfolio": "portfolio"
    }
)
builder.add_edge("macro", END)
builder.add_edge("portfolio", END)
builder.add_edge("general", END)

graph = builder.compile()

# ---------- Orchestrator ----------
def run_orchestrator(question: str, history: List[Dict[str, str]] = None) -> str:
    if history is None:
        history = []
    
    q_lower = question.lower()
    eco_keywords = [
        "gdp", "cpi", "เงินเฟ้อ", "ดอกเบี้ย", "fed", "เศรษฐกิจ", "pmi",
        "recession", "unemployment", "ว่างงาน", "ตลาด", "ดัชนี", "index",
        "s&p", "sp500", "s&p 500", "nasdaq", "dow jones", "set", "หุ้นสหรัฐ",
        "สหรัฐ", "อเมริกา", "เฟด", "ธนาคารกลาง"
    ]
    invest_keywords = [
        "พอร์ต", "ลงทุน", "หุ้น", "stock", "portfolio", "asset",
        "allocation", "dividend", "pe", "p/e", "risk", "ความเสี่ยง",
        "aapl", "msft", "nvda", "tsla", "googl", "amzn"
    ]
    
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
        "agent_type": agent_type,
        "rag_context": "",
        "web_context": ""
    }
    
    result = graph.invoke(state)
    return result["answer"]
