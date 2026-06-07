from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.issues import router as issues_router
from app.api.reviews import router as reviews_router
from app.storage import init_db


app = FastAPI(title="Compliance Reviewer API")

# CORS lets the local Next.js frontend at localhost:3000 call this separate
# local FastAPI server in the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reviews_router)
app.include_router(issues_router)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
