# QQ 机器人 · 星野猫娘

基于 **QQ 官方机器人框架（botpy）** + **本地 DeepSeek（Ollama）** 的 AI 闲聊机器人。内置蔚蓝档案「星野」的猫娘人格，支持多轮记忆、按句表情包配发、主动问候、天气注入、云端识图与 WebUI 控制面板。

## 功能特性

- **本地推理**：通过 Ollama 运行 `deepseek-r1:8b`，全程本地推理，聊天数据不出本机。
- **星野猫娘人格**：蔚蓝档案（Blue Archive）星野的猫娘形态，说话带「喵～」与颜文字，含动作描写；人格设定支持在 WebUI 中实时编辑并同步到 QQ 端。
- **多轮记忆持久化**：对话历史写入 SQLite，单会话保留最近 60 条，机器人重启后仍能记住上下文。
- **按句表情包配发**：内置 25 种本地表情包，模型按回复语义自动匹配情绪并配发对应表情。
- **主动问候**：随机时间主动找主人聊天，每天最多 3 次；天气问候一天最多 1 次。
- **天气注入**：回复前可注入实时天气信息（通过 Open-Meteo 公共接口，可在控制面板开关）。
- **云端识图**：QQ 私聊图片走智谱 GLM-4V-Flash 免费视觉识别，带超时与降级兜底。
- **文件解析**：QQ 端支持解析 txt / pdf / docx / xlsx / pptx 等文件并作答。
- **WebUI 控制面板**：FastAPI + 静态前端（127.0.0.1:8888），提供聊天、进程状态与日志、启停控制、记忆清空、人格编辑等功能。

## 目录结构

```
.
├── bot.py                      # QQ 机器人主程序（消息处理、记忆、天气、识图、表情包）
├── README.md
├── LICENSE
└── webui/
    ├── server.py               # FastAPI 后端（聊天 / 状态 / 控制 / 人格编辑）
    ├── index.html              # 控制面板前端
    ├── avatar.jpg              # WebUI 头像
    └── webui_personality.json  # 可编辑的人格设定（WebUI 保存后实时生效）
```

运行时会按需生成 `bot.db`（记忆库）、`bot_out.log` / `bot_err.log` / `bot.log`（运行日志）、`active_users.json`（活跃用户缓存）等运行时文件，不随仓库分发。

## 环境要求

- Windows / Linux / macOS（支持 Python 3.10+ 的环境均可）
- Python 3.10+
- [Ollama](https://ollama.com/) 已安装并拉取模型：`ollama pull deepseek-r1:8b`
- QQ 开放平台机器人账号（用于获取 AppID 与 Secret）

## 安装配置

1. 克隆或下载本仓库：

   ```bash
   git clone https://github.com/xingyejiangmiao/qq-robot.git
   cd qq-robot
   ```

2. 创建虚拟环境并安装依赖：

   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\pip install -r requirements.txt
   # Linux / macOS
   venv/bin/pip install -r requirements.txt
   ```

   主要依赖：`botpy`、`openai`、`aiohttp`、`fastapi`、`uvicorn`、`pydantic`（按需补充 `requirements.txt`）。

3. 填写机器人凭据：编辑 `bot.py` 顶部

   ```python
   APPID = "YOUR_APP_ID"        # 替换为你的 QQ 机器人 AppID
   SECRET = "YOUR_SECRET_KEY"   # 替换为你的 QQ 机器人 Secret
   ```

4. 确认 Ollama 服务已启动并监听 `localhost:11434`，模型名与 `bot.py` 中 `MODEL` 一致（默认 `deepseek-r1:8b`）。

5. （可选）表情包目录：默认读取 `stickers/` 目录（相对 `bot.py` 所在位置），按 `key` 命名文件（如 `cheer.png`），不提供则仅跳过表情包配发。

6. （可选）云端识图：如需图片识别，配置 `bot.py` 中的视觉模型 `base_url`、`api_key`、`model` 为你的智谱开放平台凭据；未配置时图片识别自动降级为「已收到图片，识别暂不可用」。

## 使用方法 / 启动步骤

1. 启动机器人主程序：

   ```bash
   # Windows
   venv\Scripts\python.exe -u bot.py
   # Linux / macOS
   venv/bin/python -u bot.py
   ```

2. （可选）启动 WebUI 控制面板：

   ```bash
   venv\Scripts\python.exe -u webui\server.py
   ```

   浏览器打开 `http://127.0.0.1:8888` 即可使用聊天 / 状态查看 / 启停控制 / 人格编辑等功能。

3. 在 QQ 中私聊机器人即可开始对话；发送图片或文件可触发识图 / 文件解析。

## 注意事项

- `APPID` / `SECRET` 是 QQ 开放平台的敏感凭据，请务必替换为你自己的值，切勿把真实凭据提交到公开仓库。
- 本项目的天气预报使用公共接口 Open-Meteo，需联网；坐标在代码中以占位符给出，请按需修改为你的城市坐标，或在控制面板关闭天气注入。
- 本地推理依赖 Ollama，模型加载与推理速度受本机硬件影响；`num_ctx` 已按 16384 配置，显存/内存不足时可适当调低。
- 私聊消息处理采用并发锁，同一会话同时只回复最新一问；批量操作时注意 QQ 频控，发送间隔约 1.5s。
- 主动问候与消息推送仅向授权用户发送，需在 `bot.py` 中维护可接收主动消息的用户列表。
- 本项目仅供学习交流使用，请遵守 QQ 开放平台运营规范与当地法律法规。
