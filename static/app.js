const authView = document.getElementById("authView");
const chatView = document.getElementById("chatView");
const messagesEl = document.getElementById("messages");
const userBadge = document.getElementById("userBadge");
const authError = document.getElementById("authError");

const tabLogin = document.getElementById("tabLogin");
const tabRegister = document.getElementById("tabRegister");
const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");

const textInput = document.getElementById("textInput");
const imageInput = document.getElementById("imageInput");
const sendBtn = document.getElementById("sendBtn");
const emojiToggle = document.getElementById("emojiToggle");
const emojiPanel = document.getElementById("emojiPanel");

let ws = null;
let token = localStorage.getItem("token") || "";
let username = localStorage.getItem("username") || "";

function showAuth() {
  authView.classList.remove("hidden");
  chatView.classList.add("hidden");
  userBadge.classList.add("hidden");
}

function showChat() {
  authView.classList.add("hidden");
  chatView.classList.remove("hidden");
  userBadge.classList.remove("hidden");
  userBadge.textContent = username;
}

function setError(msg) {
  authError.textContent = msg || "";
}

function addMessage(msg) {
  if (msg.username === "system") return;
  const div = document.createElement("div");
  div.className = "message" + (msg.username === username ? " me" : "");
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = `${msg.username} · ${new Date(msg.created_at * 1000).toLocaleTimeString()}`;
  const body = document.createElement("div");
  body.textContent = msg.text || "";
  div.appendChild(meta);
  div.appendChild(body);
  if (msg.image_url) {
    const img = document.createElement("img");
    img.src = msg.image_url;
    div.appendChild(img);
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function loginOrRegister(endpoint, payload) {
  setError("");
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  if (!res.ok) {
    setError(data.detail || "Request failed");
    return;
  }
  token = data.token;
  username = data.username;
  localStorage.setItem("token", token);
  localStorage.setItem("username", username);
  showChat();
  connectWS();
}

function connectWS() {
  if (ws) ws.close();
  ws = new WebSocket(`${location.origin.replace("http", "ws")}/ws?token=${token}`);
  ws.onmessage = (ev) => {
    const payload = JSON.parse(ev.data);
    if (payload.type === "history") {
      messagesEl.innerHTML = "";
      payload.messages.forEach(addMessage);
    } else if (payload.type === "message") {
      addMessage(payload.message);
    }
  };
}

async function sendMessage() {
  if (!ws || ws.readyState !== 1) return;
  const text = textInput.value.trim();
  let image_url = "";
  if (imageInput.files && imageInput.files[0]) {
    const form = new FormData();
    form.append("file", imageInput.files[0]);
    const res = await fetch(`/api/upload?token=${token}`, { method: "POST", body: form });
    const data = await res.json();
    if (res.ok) {
      image_url = data.image_url;
      imageInput.value = "";
    }
  }
  if (!text && !image_url) return;
  ws.send(JSON.stringify({ text, image_url }));
  textInput.value = "";
}

loginForm.addEventListener("submit", (e) => {
  e.preventDefault();
  loginOrRegister("/api/login", {
    username: document.getElementById("loginUser").value,
    password: document.getElementById("loginPass").value
  });
});

registerForm.addEventListener("submit", (e) => {
  e.preventDefault();
  loginOrRegister("/api/register", {
    username: document.getElementById("regUser").value,
    password: document.getElementById("regPass").value
  });
});

sendBtn.addEventListener("click", sendMessage);
textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

const EMOJI_LIST = [
  "😀","😁","😂","🤣","😃","😄","😅","😆","😉","😊","😍","😘","😗","😙","😚","😋",
  "😛","😜","🤪","🤨","🧐","🤓","😎","🥸","🤩","🥳","😏","😒","😞","😔","😟",
  "😕","🙁","☹️","😣","😖","😫","😩","🥺","😢","😭","😤","😠","😡","🤬","🤯",
  "😳","🥵","🥶","😱","😨","😰","😥","😓","🤗","🤔","🫡","🤭","🤫","🤥","😶",
  "🫥","😐","😑","🙄","😬","🫨","😯","😦","😧","😮","😲","🥱","😴","🤤","😪",
  "😮‍💨","😵","😵‍💫","🤐","🥴","🤢","🤮","🤧","😷","🤒","🤕","🤑","🤠","😈",
  "👻","💀","☠️","👽","🤖","🎃","😺","😸","😹","😻","😼","😽","🙀","😿","😾",
  "👋","🤚","🖐️","✋","🖖","👌","🤌","🤏","✌️","🤞","🫰","🤟","🤘","🤙","👈",
  "👉","👆","🖕","👇","☝️","👍","👎","✊","👊","🤛","🤜","👏","🙌","🫶","👐",
  "🤲","🤝","🙏","💪","🦾","🖤","❤️","🧡","💛","💚","💙","💜","🤎","🤍","💔",
  "❤️‍🔥","❤️‍🩹","❣️","💕","💞","💓","💗","💖","💘","💝","💯","✨","💫","🔥",
  "🌟","⚡","💥","💦","💨","🎉","🎊","🎯","🎮","🎵","🎶","📷","📸","💡","📌"
];

function buildEmojiPanel() {
  emojiPanel.innerHTML = "";
  EMOJI_LIST.forEach((e) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = e;
    btn.addEventListener("click", () => {
      textInput.value += e;
      textInput.focus();
    });
    emojiPanel.appendChild(btn);
  });
}

emojiToggle.addEventListener("click", () => {
  emojiPanel.classList.toggle("hidden");
});

document.addEventListener("click", (e) => {
  if (!emojiPanel.contains(e.target) && e.target !== emojiToggle) {
    emojiPanel.classList.add("hidden");
  }
});

function setupTabs() {
  tabLogin.addEventListener("click", () => {
    tabLogin.classList.add("active");
    tabRegister.classList.remove("active");
    loginForm.classList.remove("hidden");
    registerForm.classList.add("hidden");
    setError("");
  });
  tabRegister.addEventListener("click", () => {
    tabRegister.classList.add("active");
    tabLogin.classList.remove("active");
    registerForm.classList.remove("hidden");
    loginForm.classList.add("hidden");
    setError("");
  });
}

setupTabs();
buildEmojiPanel();

if (token && username) {
  showChat();
  connectWS();
} else {
  showAuth();
}
