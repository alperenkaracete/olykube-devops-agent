import os
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_postgres import PGVector
from sqlmodel import Field, SQLModel, create_engine
from dotenv import load_dotenv

load_dotenv()

PG_DSN = os.getenv("PG_DSN", "postgresql://postgres:postgres@postgres:5432/olykube")
COLLECTION = "olykube_kb"
EMBED_DIMS = 768

def sqlalchemy_dsn() -> str:
    """langchain-postgres psycopg sürücüsüne ihtiyaç duyar."""
    return PG_DSN.replace("postgresql://", "postgresql+psycopg://", 1)


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model="gemini-embedding-001",
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        output_dimensionality=EMBED_DIMS,
    )


def get_vectorstore() -> PGVector:
    return PGVector(
        embeddings=get_embeddings(),
        collection_name=COLLECTION,
        connection=sqlalchemy_dsn(),
        use_jsonb=True,
    )

class Agent(SQLModel, table=True):
    """Sistemdeki ajanlar"""
    __tablename__ = "agents"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    model_name: str
    system_prompt: str


engine = create_engine(sqlalchemy_dsn())