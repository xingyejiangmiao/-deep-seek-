# -*- coding: utf-8 -*-
"""星野猫娘机器人 Web 前端后端（FastAPI）

功能：
- 聊天：复用 bot.py 的星野人格（自动从 bot.py 提取 SYSTEM_PROMPT/MODEL），
  调用本地 Ollama（deepseek-r1:8b），独立会话 webui，不污染 QQ 机器人记忆。
- 状态与日志：查询 bot.py 进程状态、读取 bot_out/bot_err 日志。
- 控制面板：启动/停止 bot.py 进程、清空记忆、切换聊天天气注入。
- 展示页：纯静态介绍。

运行：venv\Scripts\python.exe -u server.py  → http://127.0.0.1:8888
"""
import json
import os
import re
import sqlite3
import subprocess
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

# ===== 路径 =====
BASE_DIR = Path(__file__).resolve().parent          # webui 目录
ROBOT_DIR = BASE_DIR.parent                         # QQ 机器人根目录
BOT_PY = ROBOT_DIR / "bot.py"
DB_PATH = ROBOT_DIR / "bot.db"
OUT_LOG = ROBOT_DIR / "bot_out.log"
ERR_LOG = ROBOT_DIR / "bot_err.log"
INDEX_HTML = BASE_DIR / "index.html"
CONFIG_FILE = BASE_DIR / "webui_config.json"

# ===== 从 bot.py 提取星野人格与模型（正则解析，bot.py 改动后自动同步）=====
def _extract_bot_const(name: str) -> str | None:
    """从 bot.py 提取顶层字符串常量：支持单行 'X = "..."' 或多行括号拼接。"""
    try:
        src = BOT_PY.read_text(encoding="utf-8")
    except Exception:
        return None
    # 多行括号拼接：SYSTEM_PROMPT = (\n "..." \n "..." \n)
    m = re.search(rf"{name}\s*=\s*\(\s*(.*?)\s*\)\s*\n", src, re.S)
    if m:
        parts = re.findall(r'"([^"]*)"', m.group(1))
        return "".join(parts)
    # 单行赋值
    m = re.search(rf'{name}\s*=\s*"([^"]*)"', src)
    return m.group(1) if m else None


PERSONALITY_FILE = BASE_DIR / "webui_personality.json"


def _load_personality() -> str:
    """加载持久化人格；不存在则回退到 bot.py 提取的默认人格。"""
    try:
        if PERSONALITY_FILE.exists():
            return PERSONALITY_FILE.read_text(encoding="utf-8")
    except Exception:
        pass
    return _extract_bot_const("SYSTEM_PROMPT") or "你是星野猫娘。"


def _save_personality(text: str) -> bool:
    """保存人格到持久化文件。"""
    try:
        PERSONALITY_FILE.write_text(text, encoding="utf-8")
        return True
    except Exception:
        return False


SYSTEM_PROMPT = _load_personality()
MODEL = _extract_bot_const("MODEL") or "deepseek-r1:8b"

# ===== 前端聊天记忆（进程内，session 固定为 webui）=====
MEMORY_LIMIT = 60
session_memory: dict[str, list[dict]] = {}
_db_lock = threading.Lock()


def _db_load_history(session_id: str) -> list[dict]:
    """从 SQLite 加载会话历史（最近 MEMORY_LIMIT 条）。"""
    try:
        with _db_lock:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id=? "
                "ORDER BY id DESC LIMIT ?",
                (session_id, MEMORY_LIMIT),
            ).fetchall()
            conn.close()
        hist = [{"role": r, "content": c} for r, c in reversed(rows)]
        return hist
    except Exception:
        return []


def _db_save_messages(session_id: str, msgs: list[dict]) -> None:
    """把消息写入 SQLite（webui 会话，与 QQ 机器人会话隔离）。"""
    try:
        with _db_lock:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,?)",
                (session_id, msgs[0]["role"], msgs[0]["content"], datetime.now().isoformat()),
            )
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,?)",
                (session_id, msgs[1]["role"], msgs[1]["content"], datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()
    except Exception:
        pass


# ===== 天气（与 bot.py 同逻辑的轻量副本，仅用于前端聊天注入）=====
def _fetch_weather() -> str | None:
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            "?latitude=YOUR_LATITUDE&longitude=YOUR_LONGITUDE"
            "&current_weather=true&timezone=Asia%2FShanghai"
        )
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        cur = data.get("current_weather", {})
        code = cur.get("weathercode")
        temp = cur.get("temperature")
        wmo = {
            0: "晴朗", 1: "大致晴朗", 2: "多云", 3: "阴天",
            45: "有雾", 48: "雾凇", 51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
            61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
            71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒", 80: "小阵雨",
            81: "中阵雨", 82: "强阵雨", 85: "小阵雪", 86: "大阵雪",
            95: "雷雨", 96: "雷雨伴冰雹", 99: "强雷雨伴冰雹",
        }
        desc = wmo.get(code, f"天气码{code}")
        return f"当前天气：{desc}，气温 {temp}℃"
    except Exception:
        return None


# ===== WebUI 配置（控制面板读写，不修改 bot.py）=====
def _load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return {"weather_in_chat": bool(cfg.get("weather_in_chat", True))}
    except Exception:
        return {"weather_in_chat": True}


def _save_config(cfg: dict) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ===== 进程管理（bot.py 启停）=====
def _bot_processes():
    """返回运行中匹配 bot.py 的进程列表（含 PID/启动时间/解释器）。"""
    try:
        ps = (
            subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'bot\\.py' } "
                    "| Select-Object ProcessId, CreationDate, ExecutablePath, CommandLine | ConvertTo-Json -Compress",
                ],
                capture_output=True, text=True, timeout=20,
            ).stdout
        )
        if not ps.strip():
            return []
        data = json.loads(ps)
        if isinstance(data, dict):
            data = [data]
        return [
            {
                "pid": d.get("ProcessId"),
                "created": d.get("CreationDate"),
                "exe": d.get("ExecutablePath", ""),
                "cmd": d.get("CommandLine", ""),
            }
            for d in data
        ]
    except Exception:
        return []


def _start_bot() -> str:
    """后台启动 bot.py（venv python，重定向日志），返回结果说明。"""
    if _bot_processes():
        return "bot.py 已在运行，无需重复启动"
    try:
        out_f = open(OUT_LOG, "a", encoding="utf-8", errors="replace")
        err_f = open(ERR_LOG, "a", encoding="utf-8", errors="replace")
        subprocess.Popen(
            [str(ROBOT_DIR / "venv" / "Scripts" / "python.exe"), "-u", "bot.py"],
            cwd=str(ROBOT_DIR),
            stdout=out_f,
            stderr=err_f,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "已发出启动指令，约 8 秒后可在状态页确认连接"
    except Exception as e:
        return f"启动失败：{e}"


def _stop_bot() -> str:
    """停止所有匹配 bot.py 的进程（含 Marvis runtime 子进程）。"""
    procs = _bot_processes()
    if not procs:
        return "没有运行中的 bot.py 进程"
    for p in procs:
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Stop-Process -Id {p['pid']} -Force -ErrorAction SilentlyContinue"],
                capture_output=True, timeout=15,
            )
        except Exception:
            pass
    return f"已停止 {len(procs)} 个进程"


# ===== FastAPI =====
app = FastAPI(title="星野猫娘机器人 Web 前端", version="1.0.4bat")
llm = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


class ChatReq(BaseModel):
    message: str
    session_id: str = "webui"


class ConfigReq(BaseModel):
    weather_in_chat: bool | None = None
    personality: str | None = None


@app.get("/")
def index():
    return FileResponse(INDEX_HTML)


@app.get("/api/status")
def status():
    procs = _bot_processes()
    # Ollama 可用性探测
    ollama_ok = False
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            ollama_ok = r.status == 200
    except Exception:
        ollama_ok = False
    main = procs[0] if procs else None
    return {
        "bot_running": bool(procs),
        "bot_pid": main["pid"] if main else None,
        "bot_started": main["created"] if main else None,
        "bot_count": len(procs),
        "ollama_ok": ollama_ok,
        "model": MODEL,
        "weather_in_chat": _load_config().get("weather_in_chat", True),
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/api/logs")
def logs(kind: str = "out", lines: int = 200):
    path = OUT_LOG if kind == "out" else ERR_LOG
    try:
        raw = path.read_bytes()[-8192:]
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        arr = text.splitlines()
        return {"ok": True, "lines": arr[-lines:]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/sessions")
def sessions():
    """bot.db 中的会话概览（按 session_id 分组）。"""
    try:
        with _db_lock:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute(
                "SELECT session_id, COUNT(*) AS cnt, MAX(timestamp) AS last "
                "FROM messages GROUP BY session_id ORDER BY last DESC"
            ).fetchall()
            conn.close()
        return {
            "ok": True,
            "sessions": [
                {"session_id": s, "count": c, "last": t} for s, c, t in rows
            ],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/session/{session_id}")
def session_detail(session_id: str, limit: int = 50):
    try:
        with _db_lock:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute(
                "SELECT role, content, timestamp FROM messages WHERE session_id=? "
                "ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            conn.close()
        return {"ok": True, "messages": [{"role": r, "content": c, "time": t} for r, c, t in reversed(rows)]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/chat")
def chat(req: ChatReq):
    sid = req.session_id or "webui"
    text = (req.message or "").strip()
    if not text:
        return {"ok": False, "error": "消息不能为空"}

    history = session_memory.get(sid)
    if history is None:
        history = _db_load_history(sid)
        session_memory[sid] = history

    now = datetime.now()
    weekday_cn = "一二三四五六日"[now.weekday()]
    time_prompt = (
        f"当前本地时间是 {now.year}年{now.month}月{now.day}日 "
        f"星期{weekday_cn} {now.hour:02d}:{now.minute:02d}"
    )
    weather_prompt = _fetch_weather() if _load_config().get("weather_in_chat", True) else None

    messages = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + [{"role": "system", "content": time_prompt}]
        + ([{"role": "system", "content": weather_prompt}] if weather_prompt else [])
        + history[-MEMORY_LIMIT:]
        + [{"role": "user", "content": text}]
    )
    try:
        resp = llm.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=1500,
            timeout=180,
            extra_body={"num_ctx": 16384, "think": False},
        )
        answer = resp.choices[0].message.content or "（模型未返回内容）"
    except Exception as e:
        return {"ok": False, "error": f"本地模型调用失败：{e}"}

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": answer})
    if len(history) > MEMORY_LIMIT:
        session_memory[sid] = history[-MEMORY_LIMIT:]
    try:
        _db_save_messages(sid, [
            {"role": "user", "content": text},
            {"role": "assistant", "content": answer},
        ])
    except Exception:
        pass
    return {"ok": True, "reply": answer}


@app.post("/api/bot/start")
def bot_start():
    return {"ok": True, "msg": _start_bot()}


@app.post("/api/bot/stop")
def bot_stop():
    return {"ok": True, "msg": _stop_bot()}


@app.post("/api/memory/clear")
def memory_clear(session_id: str = "webui", all_sessions: bool = False):
    """清空记忆。默认只清前端聊天会话 webui；all_sessions=true 清空全部（危险）。"""
    try:
        with _db_lock:
            conn = sqlite3.connect(DB_PATH)
            if all_sessions:
                conn.execute("DELETE FROM messages")
                session_memory.clear()
            else:
                conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
                session_memory.pop(session_id, None)
            conn.commit()
            conn.close()
        if all_sessions:
            return {"ok": True, "msg": "已清空全部会话记忆"}
        return {"ok": True, "msg": f"已清空会话 {session_id} 的记忆"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/config")
def config_get():
    return {"ok": True, "config": _load_config()}


@app.post("/api/config")
def config_set(req: ConfigReq):
    cfg = _load_config()
    if req.weather_in_chat is not None:
        cfg["weather_in_chat"] = req.weather_in_chat
    _save_config(cfg)
    return {"ok": True, "config": cfg}


@app.get("/api/personality")
def personality_get():
    return {"ok": True, "personality": _load_personality()}


@app.post("/api/personality")
def personality_set(req: ConfigReq):
    text = req.personality or ""
    if not text.strip():
        return {"ok": False, "error": "人格文本不能为空"}
    ok = _save_personality(text)
    global SYSTEM_PROMPT
    SYSTEM_PROMPT = _load_personality()
    return {"ok": ok, "message": "人格已保存" if ok else "保存失败"}


@app.get("/api/about")
def about():
    return {
        "ok": True,
        "name": "星野猫娘",
        "version": "1.0.4bat",
        "model": MODEL,
        "system_prompt_head": SYSTEM_PROMPT[:120],
    }


if __name__ == "__main__":
    import uvicorn
    # 静态资源挂载需在 API 路由之后，避免覆盖 /api/* 接口
    app.mount("/", StaticFiles(directory=BASE_DIR), name="static")
    uvicorn.run(app, host="127.0.0.1", port=8888, log_level="warning")
