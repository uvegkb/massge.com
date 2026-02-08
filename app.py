import os
import time
import uuid
import hashlib
from typing import Dict, List

from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    UploadFile,
    File,
    HTTPException,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import certifi
from pymongo import MongoClient, ASCENDING

APP_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(APP_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

MONGODB_URI = os.environ.get("MONGODB_URI", "").strip()
MONGODB_DB = os.environ.get("MONGODB_DB", "massg").strip() or "massg"
if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI is required. Set it in your environment.")

mongo = MongoClient(MONGODB_URI, tlsCAFile=certifi.where())
db = mongo[MONGODB_DB]
users = db["users"]
tokens = db["tokens"]
messages = db["messages"]

users.create_index([("username", ASCENDING)], unique=True)
tokens.create_index([("token", ASCENDING)], unique=True)
messages.create_index([("created_at", ASCENDING)])

app = FastAPI()
app.mount(
    "/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static"
)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


class AuthPayload(BaseModel):
    username: str
    password: str


def _pbkdf2_hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000).hex()


def _create_user(username: str, password: str) -> None:
    salt = os.urandom(16)
    hashed = _pbkdf2_hash(password, salt)
    users.insert_one(
        {
            "username": username,
            "salt": salt.hex(),
            "hash": hashed,
            "created_at": int(time.time()),
        }
    )


def _verify_user(username: str, password: str) -> bool:
    row = users.find_one({"username": username})
    if not row:
        return False
    salt = bytes.fromhex(row["salt"])
    expected = row["hash"]
    return _pbkdf2_hash(password, salt) == expected


def _issue_token(username: str) -> str:
    token = uuid.uuid4().hex
    tokens.insert_one(
        {"token": token, "username": username, "created_at": int(time.time())}
    )
    return token


def _auth_username(token: str) -> str:
    row = tokens.find_one({"token": token})
    if not row:
        raise HTTPException(status_code=401, detail="Invalid token")
    return row["username"]


def _store_message(username: str, text: str, image_url: str) -> Dict:
    msg = {
        "id": uuid.uuid4().hex,
        "username": username,
        "text": text,
        "image_url": image_url,
        "created_at": int(time.time()),
    }
    messages.insert_one(msg)
    return msg


@app.get("/")
def index():
    return FileResponse(os.path.join(APP_DIR, "static", "index.html"))


@app.post("/api/register")
def register(payload: AuthPayload):
    username = payload.username.strip()
    if not username or not payload.password:
        raise HTTPException(status_code=400, detail="Missing username or password")
    if users.find_one({"username": username}):
        raise HTTPException(status_code=409, detail="Username already exists")
    _create_user(username, payload.password)
    token = _issue_token(username)
    return {"token": token, "username": username}


@app.post("/api/login")
def login(payload: AuthPayload):
    username = payload.username.strip()
    if not username or not payload.password:
        raise HTTPException(status_code=400, detail="Missing username or password")
    if not _verify_user(username, payload.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = _issue_token(username)
    return {"token": token, "username": username}


@app.post("/api/upload")
def upload_image(token: str, file: UploadFile = File(...)):
    _ = _auth_username(token)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOADS_DIR, name)
    with open(path, "wb") as f:
        f.write(file.file.read())
    return {"image_url": f"/uploads/{name}"}


class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: Dict):
        for ws in list(self.active):
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str):
    try:
        username = _auth_username(token)
    except HTTPException:
        await ws.close(code=1008)
        return

    await manager.connect(ws)

    history = list(messages.find({}, {"_id": 0}).sort("created_at", ASCENDING))
    await ws.send_json({"type": "history", "messages": history})

    try:
        while True:
            data = await ws.receive_json()
            text = (data.get("text") or "").strip()
            image_url = (data.get("image_url") or "").strip()
            client_id = (data.get("client_id") or "").strip()
            if not text and not image_url:
                continue
            msg = _store_message(username, text, image_url)
            if client_id:
                msg["client_id"] = client_id
            await manager.broadcast({"type": "message", "message": msg})
    except WebSocketDisconnect:
        manager.disconnect(ws)
        return
