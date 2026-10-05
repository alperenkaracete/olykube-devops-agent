import glob
import os
from contextlib import asynccontextmanager  # YENİ EKLENDİ
from typing import List

from fastapi import FastAPI, HTTPException, UploadFile, File, status, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlmodel import Session, SQLModel, select  # YENİ EKLENDİ: SQLModel

from common import engine, Agent
from services import ingest_service
from services.agents_service import run_agent_chat

KB_DIR = os.getenv("KB_DIR", "data/kb")

@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    yield

app = FastAPI(
    title="OlyKube AIOps API",
    description="PostgreSQL (PGVector) ve Hiyerarşik Ajan Mimarili DevOps Asistanı",
    version="1.0.0",
    lifespan=lifespan,  
)

class AgentCreate(BaseModel):
    name: str
    model_name: str
    system_prompt: str

class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"

def get_session():
    with Session(engine) as session:
        yield session


@app.get("/", tags=["General"])
def read_root():
    return {"message": "OlyKube API çalışıyor!", "status": "active"}

@app.get("/health", tags=["General"])
def health_check():
    return {'message': 'healthy'}

@app.post("/agents/", tags=["Agents"])
def create_agent(agent: AgentCreate, session: Session = Depends(get_session)):
    """Sisteme yeni bir hiyerarşik DevOps ajanı ekler."""
    db_agent = Agent(name=agent.name, model_name=agent.model_name, system_prompt=agent.system_prompt)
    session.add(db_agent)
    session.commit()
    session.refresh(db_agent)
    return db_agent

@app.post("/agents/{agent_id}/chat", tags=["Agents"])
async def chat_with_agent(agent_id: int, req: ChatRequest, session: Session = Depends(get_session)):
    """Belirtilen ajan ile sohbet başlatır ve iz (trace) kayıtlarını döndürür."""
    agent = session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent bulunamadı")
    
    response = await run_agent_chat(
        model_name=agent.model_name,
        system_prompt=agent.system_prompt,
        user_message=req.message,
        thread_id=req.thread_id
    )
    return response

@app.post("/ingest/upload", tags=["Ingestion"])
async def ingest_upload(file: UploadFile = File(...)):
    """Markdown (.md) dosyasını bilgi tabanına yükler ve PGVector'e kaydeder."""
    os.makedirs(KB_DIR, exist_ok=True)

    name = os.path.basename(file.filename or "")
    if not name.lower().endswith(".md"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sadece .md dosyalarına izin verilir: {file.filename!r}",
        )
    
    content = await file.read()
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} geçerli bir UTF-8 metni değil.",
        )
    
    with open(os.path.join(KB_DIR, name), "wb") as out:
        out.write(content)

    await run_in_threadpool(ingest_service.main)

    kb_files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(KB_DIR, "*.md")))
    return {"uploaded": [name], "kb_files": kb_files, "kb_count": len(kb_files)}

@app.get("/agents", tags=["Agents"])
async def get_all_agents():
    with Session(engine) as session:
        statement = select(Agent)
        db_agents = session.exec(statement).all()
        
        # Sadece Agent ID'lerini string'e çevirip liste olarak dönüyoruz
        return [str(agent.id) for agent in db_agents]