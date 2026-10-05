import os
import re
from fastapi import HTTPException
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

from langchain_tavily import TavilySearch
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain.chat_models import init_chat_model

from common import get_vectorstore

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def make_model():

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY /.env dosyasında bulunamadı."
        )

    return init_chat_model(
        model=os.getenv("ANTHROPIC_MODEL"),
        model_provider="anthropic",
        max_tokens=2500,
        timeout=180,
        max_retries=3,
    )

@tool
def search_kb(query: str) -> str:
    """OlyKube bilgi tabanında sistem konfigürasyonları ve bilinen hatalar için arama yapar."""
    # Artık ChromaDB yerine PGVector üzerinden arama yapıyoruz
    docs = get_vectorstore().similarity_search(query, k=4)
    if not docs:
        return "Yerel bilgi tabanında (KB) ilgili hata/çözüm bulunamadı."
    return "\n\n".join(
        f"[source: {d.metadata.get('source', '?')}]\n{d.page_content}" for d in docs
    )

kb_researcher = {
    "name": "kb-researcher",
    "description": (
        "OlyKube sistem politikalarını ve bilinen hata çözümlerini araştırır. "
        "Ona spesifik bir hata veya konfigürasyon sor; sana kaynağını belirterek cevap versin."
    ),
    "system_prompt": (
        "Sen bilgi tabanında arama yapan bir araştırmacısın. "
        "search_kb aracını kullan, dönen sonuçları oku ve kaynağı belirterek cevap ver. "
        "Asla ezberden cevap verme, her zaman önce arama yap."
    ),
    "tools": [search_kb],
}

@tool
def search_web_for_error(query: str) -> str:
    """KB'de çözüm yoksa StackOverflow, GitHub Issues araması yapar."""
    search = TavilySearch(max_results=2)
    return search.invoke({"query": f"Solution {query} error fix"})

@tool
def fetch_service_logs(service_name: str, tail_lines: int = 50) -> str:
    """
    OlyKube üzerindeki bir servisin son log kayıtlarını getirir.
    DİKKAT KESİN KURAL: Kullanıcı spesifik bir servis adı (örn: fastapi-backend, redis) belirtmediyse 
    ASLA 'your_service_name' gibi değerler uydurma! 
    Eğer kullanıcı servis adı vermediyse BU ARACI ÇALIŞTIRMA ve kullanıcıya 'Hangi servisin loglarına bakmalıyım?' diye sor.
    """
    mock_logs = {
        "fastapi-backend": "ERROR: sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) connection to server at 'postgres' failed.",
        "redis": "WARNING: Memory limit reached. Evicting keys.",
    }
    return mock_logs.get(service_name, f"No active logs found for pod/service: {service_name}.")

@tool
def save_error_solution(error_summary: str, root_cause: str, solution_steps: str) -> str:
    """Yeni bir hata çözüldüğünde bunu PGVector veritabanına kaydeder."""
    content = f"Hata Özeti: {error_summary}\nKök Neden: {root_cause}\nÇözüm Adımları:\n{solution_steps}"
    
    get_vectorstore().add_texts(
        texts=[content],
        metadatas=[{"source": "agent_learned_solutions", "type": "bugfix"}]
    )
    return "Çözüm başarıyla bilgi tabanına eklendi. Artık sistem bu hatayı hatırlıyor."


async def run_agent_chat(model_name: str, system_prompt: str, user_message: str, thread_id: str) -> Dict[str, Any]:
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY bulunamadı!")

    llm = make_model()

    coordinator_tools = [fetch_service_logs, search_web_for_error, save_error_solution, search_kb]

    agent_app = create_deep_agent(
        model=llm,
        tools=coordinator_tools,
        subagents=[kb_researcher],
        skills=[os.path.join(APP_DIR, "skills")], 
        backend=FilesystemBackend(root_dir=APP_DIR, virtual_mode=False),
        system_prompt=system_prompt,
        checkpointer=InMemorySaver()
    )

    config = {"configurable": {"thread_id": thread_id}}
    
    result = await agent_app.ainvoke({"messages": [{"role": "user", "content": user_message}]}, config=config)
    msgs = result["messages"]

    actions = []
    sources = set()
    learned_something = False

    for m in msgs:
        if getattr(m, "tool_calls", None):
            for call in m.tool_calls:
                actions.append({"name": call["name"], "args": call.get("args", {})})
        
        if getattr(m, "type", "") == "tool":
            if isinstance(m.content, str):
                found_sources = re.findall(r"\[source: (.*?)\]", m.content)
                sources.update(found_sources)
                
                md_sources = re.findall(r"\b[\w-]+\.md\b", m.content)
                sources.update(md_sources)

            if m.name == "save_error_solution":
                learned_something = True

    return {
        "reply": msgs[-1].content,
        "actions_taken": actions,
        "cited_sources": list(sources),
        "new_knowledge_saved": learned_something
    }