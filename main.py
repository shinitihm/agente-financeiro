from fastapi import FastAPI,Depends,HTTPException,Header
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
from app.routes.chat import router
import ollama
from app.config import validar_config          # junto dos outros imports
from app.config import FRONTEND_DIR
from app.routes import chat, sessions, monitor
for _problema in validar_config():                 # logo antes de app = FastAPI(...)
    print(f"[config] ATENÇÃO: {_problema}")

app = FastAPI()
app.include_router(router)
load_dotenv()
ENDPOINT = 'generate'
x_api_key = os.getenv("API_KEY")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(monitor.router)

API_KEYS = {x_api_key:  5}

def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API Key")
    
    credits = API_KEYS.get(x_api_key)
    
    if credits <= 0:
        raise HTTPException(status_code=403, detail="Insufficient credits")
    
    return x_api_key

@app.post(f"/{ENDPOINT}")
def generate(prompt: str,api_key: str = Depends(verify_api_key)):
    response = ollama.chat(model='mistral', messages=[#system prompt 
        {"role": "system", "content": "Você é um assistente virtual muito útil. Você DEVE sempre responder em português do Brasil, independente do idioma da pergunta"},
        {"role": "user", "content": prompt}
    ])
    return {"response": response["message"]["content"]}
    


@app.get("/health")
def health() -> dict:
    problemas = validar_config()
    return {
        "status": "ok" if not problemas else "atencao",
        "problemas_de_configuracao": problemas,
    }

if (FRONTEND_DIR /'index.html').exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
else:
    @app.get("/")
    def raiz() -> dict:
        return {"message": "API is running"}
