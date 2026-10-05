# OlyKube DevOps Asistanı

Hata mesajlarını ve servis loglarını analiz eden, çözümü önce kurum içi bilgi tabanında (RAG) arayıp bulamazsa web'de araştıran ve yeni öğrendiği çözümleri bilgi tabanına geri kaydeden bir DevOps triage ajanı.

Backend FastAPI, ajan [deepagents](https://github.com/langchain-ai/deepagents) (LangGraph) üzerinde çalışır. LLM olarak Anthropic Claude kullanılır, vektör arama PostgreSQL + pgvector ile yapılır. Arayüz Streamlit'tir.

## Teknoloji Yığını

| Katman | Teknoloji |
|---|---|
| API | FastAPI, SQLModel (Python 3.12) |
| Ajan | deepagents, LangGraph, LangChain |
| LLM | Anthropic Claude (`ANTHROPIC_MODEL`) |
| Embedding | Google Gemini `gemini-embedding-001` (768 boyut) |
| Vektör DB + ilişkisel DB | PostgreSQL 15 + pgvector (`langchain-postgres`) |
| Web araması | Tavily |
| Arayüz | Streamlit |
| Paketleme | Docker, Docker Compose, uv |

## Mimari

```mermaid
flowchart LR
    U[Kullanıcı] --> F[frontend<br/>Streamlit :8501]
    F -->|HTTP| A[api<br/>FastAPI :8000]
    A -->|agents tablosu + pgvector| D[(db<br/>Postgres 15 + pgvector :5432)]
    A -->|LLM| C[Anthropic API]
    A -->|embedding| G[Google Gemini API]
    A -->|web araması| T[Tavily API]
```

Docker Compose üç servis çalıştırır; hepsi `olykube-network` bridge ağındadır:

1. **`db`** (`olykube-db`): Ajan tanımlarını (`agents` tablosu) ve bilgi tabanı vektörlerini (`olykube_kb` koleksiyonu) tutar. Veri `postgres_data` volume'ünde kalıcıdır.
2. **`api`** (`olykube-api`): Ajan ve ingest endpoint'leri. `/health` üzerinden healthcheck tanımlıdır.
3. **`frontend`**: Ajan seçimi ve sohbet için Streamlit arayüzü.

## Ajan Nasıl Çalışır?

Her `/agents/{id}/chat` isteğinde, veritabanındaki ajanın `system_prompt`'u ile bir deep agent oluşturulur. Ajanın kullanabildiği araçlar:

| Araç | Ne yapar |
|---|---|
| `search_kb` | pgvector bilgi tabanında benzerlik araması yapar (k=4) |
| `search_web_for_error` | KB'de çözüm yoksa Tavily ile web'de arar |
| `fetch_service_logs` | Servis loglarını getirir (**şu an sahte/mock veri döner**) |
| `save_error_solution` | Bulunan çözümü bilgi tabanına kaydeder |
| `kb-researcher` (alt ajan) | Yalnızca KB'de arama yapıp kaynak göstererek cevap verir |

Ajanın izleyeceği operasyon prosedürü [skills/devops_triage.md](skills/devops_triage.md) dosyasındadır: bilgi sorgularında doğrudan KB araması, canlı arızalarda log → KB → web → kaydet sırası.

## Kurulum

### Gereksinimler

- Docker ve Docker Compose
- API anahtarları: **Anthropic**, **Google AI (Gemini)**, **Tavily**

### Ortam değişkenleri

```bash
cp .env.example .env
```

| Değişken | Açıklama |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API anahtarı |
| `ANTHROPIC_MODEL` | Kullanılacak Claude modeli (ör. `claude-sonnet-5-5`) |
| `GOOGLE_API_KEY` | Gemini embedding için |
| `TAVILY_API_KEY` | Web araması için |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `db` container'ının oluşturacağı kullanıcı ve veritabanı |
| `PG_DSN` | API'nin bağlanacağı adres. Docker'da host `db`, yerelde `localhost` olmalı |
| `KB_DIR` | (Opsiyonel) Bilgi tabanı `.md` dosyalarının klasörü, varsayılan `data/kb` |

### Yöntem 1: Docker Compose (önerilen)

```bash
docker compose up -d --build
```

- API: http://localhost:8000 (Swagger: http://localhost:8000/docs)
- Arayüz: http://localhost:8501

İlk açılışta arayüzde ajan görünmez; önce bir ajan oluşturun (bkz. [Hızlı Başlangıç](#hızlı-başlangıç)).

### Yöntem 2: Yerel geliştirme

Veritabanını yine Docker ile çalıştırmak en kolayıdır (pgvector eklentisi hazır gelir):

```bash
docker compose up -d db

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# .env içinde PG_DSN host'unu localhost yapın:
# PG_DSN=postgresql://olykube:change-me@localhost:5432/olykube

uvicorn main:app --reload
```

Arayüzü ayrı bir terminalde:

```bash
pip install streamlit requests
API_BASE_URL=http://localhost:8000 streamlit run frontend.py
```

## Hızlı Başlangıç

```bash
# 1. Ajan oluştur
curl -X POST http://localhost:8000/agents/ \
  -H "Content-Type: application/json" \
  -d '{"name": "triage", "model_name": "claude", "system_prompt": "Sen OlyKube DevOps asistanısın."}'

# 2. Bilgi tabanına bir runbook yükle
curl -X POST http://localhost:8000/ingest/upload -F "file=@runbook.md"

# 3. Ajana soru sor
curl -X POST http://localhost:8000/agents/1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "fastapi-backend servisi postgres bağlantı hatası veriyor", "thread_id": "demo"}'
```

Sohbet cevabı şu alanları döner: `reply`, `actions_taken` (çağrılan araçlar), `cited_sources` (kullanılan KB kaynakları), `new_knowledge_saved`.

## API Endpoint'leri

| Method | Endpoint | Açıklama |
|---|---|---|
| GET | `/` | Servis durumu |
| GET | `/health` | Sağlık kontrolü (Docker healthcheck bunu kullanır) |
| POST | `/agents/` | Yeni ajan oluştur (`name`, `model_name`, `system_prompt`) |
| GET | `/agents` | Kayıtlı ajanların ID listesini döner |
| POST | `/agents/{agent_id}/chat` | Ajanla sohbet (`message`, `thread_id`) |
| POST | `/ingest/upload` | `.md` dosyasını `KB_DIR`'e kaydeder ve bilgi tabanını baştan oluşturur |

Endpoint'lerde kimlik doğrulama yoktur.

Bilgi tabanını elle yeniden oluşturmak için (`KB_DIR` içindeki tüm `.md` dosyaları):

```bash
python -m services.ingest_service
```

## Kubernetes

[api-deployment.yaml](api-deployment.yaml) API için bir Deployment (2 replika) ve ClusterIP Service içerir. Ortam değişkenlerini `olykube-env` secret'ından okur:

```bash
docker build -t olykube-api:v3 .
kubectl create secret generic olykube-env --from-env-file=.env
kubectl apply -f api-deployment.yaml
```

Manifest yalnızca API'yi kapsar; PostgreSQL + pgvector ve frontend için manifest henüz yoktur. `PG_DSN` küme içindeki bir veritabanını göstermelidir.

## Bilinen Kısıtlar

- **Sohbet hafızası kalıcı değil:** Her istekte yeni bir `InMemorySaver` oluşturulduğu için aynı `thread_id` ile gelen istekler önceki mesajları görmez.
- **`model_name` kullanılmıyor:** Ajan kaydındaki `model_name` alanı yok sayılır; her zaman `ANTHROPIC_MODEL` kullanılır.
- **`fetch_service_logs` sahte veri döner:** Gerçek bir log kaynağına (Kubernetes, Loki vb.) bağlı değildir.
- **Arayüzden dosya yükleme API'ye ulaşmıyor:** Streamlit'teki yükleme dosyayı frontend container'ına yazar. Bilgi tabanına eklemek için `POST /ingest/upload` kullanın.
- **Ajan dosya sistemine erişebilir:** `FilesystemBackend` uygulama dizinine gerçek erişimle çalışır.
- Kimlik doğrulama, rate limiting ve otomatik testler yoktur.

## Yol Haritası

- Kalıcı sohbet hafızası (PostgreSQL checkpointer) ve geçmiş endpoint'i
- Gerçek log kaynağı entegrasyonu
- Kimlik doğrulama ve rate limiting
- Prometheus metrikleri
- Testler ve CI
- Kubernetes üzerinde kaynak-farkındalıklı, ajan başına Pod (Agent-per-Pod) çalıştırma

---
*Bu proje, otonom ajan mimarileri ve kaynak-farkındalıklı (resource-aware) Kubernetes deployment tez çalışmaları kapsamında geliştirilmektedir.*
