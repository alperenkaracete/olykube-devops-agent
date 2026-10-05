import streamlit as st
import requests
import uuid
import os
import ast

st.set_page_config(page_title="OlyKube DevOps Chat", page_icon="🤖")

@st.cache_data(ttl=60) 
def fetch_agent_ids():
    api_base = os.getenv("API_BASE_URL", "http://api:8000")
    try:
        response = requests.get(f"{api_base}/agents", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            
            if isinstance(data, list):
                if len(data) == 0:
                    return [] 
                
                if isinstance(data[0], str):
                    return data
                
                elif isinstance(data[0], dict):
                    return [str(item.get("id", item.get("agent_id", "Bilinmeyen"))) for item in data]
                    
    except Exception as e:
        print(f"Agent ID'leri çekilemedi: {e}")
        
    return []

with st.sidebar:
    dynamic_agent_ids = fetch_agent_ids()
        
    if dynamic_agent_ids:
        agent_id = st.selectbox("Agent ID Seçin", options=dynamic_agent_ids)
    else:
        st.warning("Veritabanında kayıtlı ajan bulunamadı!")
        agent_id = None
    
    st.divider()
    
    st.header("Veri Yükleme (Ingest)")
    uploaded_file = st.file_uploader("Bilgi tabanı için .md dosyası seçin", type=["md"])
    
    if uploaded_file is not None:
        if st.button("Dosyayı Yükle"):
            kb_dir = os.getenv("KB_DIR", "data/kb")
            os.makedirs(kb_dir, exist_ok=True)
            
            file_path = os.path.join(kb_dir, uploaded_file.name)
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
                
            st.success(f"'{uploaded_file.name}' başarıyla kaydedildi!")
            st.info("Değişikliklerin veritabanına yansıması için backend üzerinden ingest scriptini tetiklemeyi unutmayın.")

st.title("OlyKube DevOps Asistanı")

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# EĞER GEÇERLİ BİR AJAN SEÇİLİYSE SOHBETE İZİN VER
if agent_id:
    if prompt := st.chat_input("Hata özetini veya log mesajını buraya yazın..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Ajan logları inceliyor ve KB'de arama yapıyor..."):
                try:
                    api_base = os.getenv("API_BASE_URL", "http://api:8000")
                    api_url = f"{api_base}/agents/{agent_id}/chat"
                    
                    payload = {
                        "message": prompt,
                        "thread_id": st.session_state.thread_id
                    }
                    
                    response = requests.post(api_url, json=payload)
                    
                    if response.status_code == 200:
                        data = response.json()
                        reply = data.get("reply", "Backend'den boş cevap döndü.")
                        
                        if isinstance(reply, str) and reply.strip().startswith("[{"):
                            try:
                                parsed_list = ast.literal_eval(reply)
                                if isinstance(parsed_list, list):
                                    text_blocks = [b.get("text", "") for b in parsed_list if isinstance(b, dict) and b.get("type") == "text"]
                                    if text_blocks:
                                        reply = "\n\n".join(text_blocks)
                            except Exception:
                                pass 
                        elif isinstance(reply, list):
                            text_blocks = [b.get("text", "") for b in reply if isinstance(b, dict) and b.get("type") == "text"]
                            if text_blocks:
                                reply = "\n\n".join(text_blocks)
                        
                        st.markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                        
                        actions = data.get("actions_taken", [])
                        if actions:
                            st.caption(f"Kullanılan Araçlar: {[a['name'] for a in actions]}")
                            
                except requests.exceptions.ConnectionError:
                    st.error("Backend'e ulaşılamadı. FastAPI sunucusunun çalıştığından emin olun.")
else:
    st.info("Sohbete başlamak için lütfen sisteme bir ajan ekleyin.")