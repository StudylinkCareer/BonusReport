from fastapi import FastAPI

app = FastAPI(title="BonusReport API")

@app.get("/health")
def health():
    return {"status": "ok"}    