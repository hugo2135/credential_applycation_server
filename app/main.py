from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from app.database import engine, Base
from app.routers import auth, credential, admin

Base.metadata.create_all(bind=engine)

app = FastAPI(title="PBI Credential 申請程式", version="0.1.0")

app.include_router(auth.router)
app.include_router(credential.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok"}
