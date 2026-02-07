import os
import time
import uuid
import hashlib
from typing import Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from tinydb import TinyDB, Query

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
UPLOADS_DIR = os.path.join(APP_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "db.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

db = TinyDB(DB_PATH)
users = db.table("users")
tokens = db.table("tokens")
messages = db.table("messages")

app = FastAPI()

app.mount("/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

class AuthPayload(BaseModel):
    username: str
    password: str

class SendPayload(BaseModel):
    text: str = ""
    image_url: str = ""


def _pbkdf2_hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000).hex()


def _create_user(username: str, password: str) -> None:
    salt = os.urandom(16)
    hashed = _pbkdf2_hash(password, salt)
    users.insert({
        "username": username,
        "salt": salt.hex(),
        "hash": hashed,
        "created_at": int(time.time())
    })


def _verify_user(username: str, password: str) -> bool:
    User = Query()
    row = users.get(User.username == username)
    if not row:
        return False
    salt = bytes.fromhex(row["salt"])
    expected = row["hash"]
    return _pbkdf2_hash(password, salt) == expected


def _issue_token(username: str) -> str:
    token = uuid.uuid4().hex
    tokens.insert({
        "token": token,
        "username": username,
        "created_at": int(time.time())
    })
    return token


def _auth_username(token: str) -> str:
    T = Query()
    row = tokens.get(T.token == token)
    if not row:
        raise HTTPException(status_code=401, detail="Invalid token")
    return row["username"]


def _store_message(username: str, text: str, image_url: str) -> Dict:
    msg = {
        "id": uuid.uuid4().hex,
        "username": username,
        "text": text,
        "image_url": image_url,
        "created_at": int(time.time())
    }
    messages.insert(msg)
    return msg


@app.get("/")
def index():
    return FileResponse(os.path.join(APP_DIR, "static", "index.html"))


@app.post("/api/register")
def register(payload: AuthPayload):
    username = payload.username.strip()
    if not username or not payload.password:
        raise HTTPException(status_code=400, detail="Missing username or password")
    User = Query()
    if users.get(User.username == username):
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
    username = _auth_username(token)
    _ = username
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

    history = messages.all()
    history.sort(key=lambda m: m["created_at"])
    await ws.send_json({"type": "history", "messages": history})

    try:
        while True:
            data = await ws.receive_json()
            text = (data.get("text") or "").strip()
            image_url = (data.get("image_url") or "").strip()
            if not text and not image_url:
                continue
            msg = _store_message(username, text, image_url)
            await manager.broadcast({"type": "message", "message": msg})
    except WebSocketDisconnect:
        manager.disconnect(ws)
        return

