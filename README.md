# DeepSeek-R1 QQ 机器人

基于本地部署的 DeepSeek-R1 大模型 + 官方 QQ 机器人 SDK 构建的 AI 闲聊机器人，支持私聊与群聊 @ 回复。

## 功能特性

| 功能 | 说明 |
|------|------|
| **多轮对话** | 按会话维度缓存最近 20 条消息，支持私聊和群聊独立上下文 |
| **固定人格** | 蔚蓝档案·星野猫娘形态，每条回复自动注入人设 |
| **天气感知** | 自动获取实时天气并融入对话（需配置坐标） |
| **图片识别** | 收到图片附件时调用视觉模型识别内容 |
| **表情包匹配** | 根据回复情绪自动发送对应表情包（生气/开心/傲娇） |
| **消息拆分防风控** | 长回复按句子拆分，段落间间隔 1.5 秒发送 |

## 使用环境

### 硬件要求

| 组件 | 最低配置 | 推荐配置 |
|------|----------|----------|
| CPU | Intel i5 / AMD Ryzen 5 | Intel i7 / AMD Ryzen 7 |
| GPU | NVIDIA RTX 4060 (6GB) | NVIDIA RTX 4060 Ti (8GB) |
| 内存 | 16GB DDR4 | 16GB DDR5 |
| 磁盘 | 20GB 可用空间 | 50GB SSD |

### 软件依赖

| 软件 | 版本 | 用途 |
|------|------|------|
| Python | 3.10+ | 运行 bot.py |
| Ollama | 0.40+ | 本地模型推理服务 |
| Windows | 10/11 | 操作系统 |

### 模型列表

| 模型 | 参数量 | 显存占用 | 用途 |
|------|--------|----------|------|
| deepseek-r1:8b | 8B | ~5.2GB | 对话回复 |
| minicpm-v:8b | 8B | ~5.5GB | 图片识别 |

## 安装步骤

### 1. 安装 Ollama

```bash
# 下载并安装 Ollama（Windows）
# https://ollama.com/download/windows
```

### 2. 拉取模型

```bash
ollama pull deepseek-r1:8b
ollama pull minicpm-v:8b
```

### 3. 克隆仓库

```bash
git clone https://github.com/xingyejiangmiao/-deep-seek-.git
cd -deep-seek-
```

### 4. 创建虚拟环境

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

> 如果没有 `requirements.txt`，手动安装：
> ```bash
> pip install botpy openai aiohttp
> ```

### 5. 配置机器人

编辑 `bot.py`，修改以下参数：

```python
APPID = "你的QQ机器人AppID"      # 从QQ开放平台获取
SECRET = "你的QQ机器人Secret"    # 从QQ开放平台获取
```

如需自定义天气坐标，修改 `_fetch_weather()` 函数中的经纬度：

```python
url = "https://api.open-meteo.com/v1/forecast?latitude=YOUR_LAT&longitude=YOUR_LON&..."
```

## 使用方法

### 启动机器人

```bash
# 激活虚拟环境后运行
python bot.py
```

### 启动流程说明

1. 机器人连接 QQ 官方服务器
2. 加载本地 DeepSeek 模型
3. 等待用户私聊或群聊 @ 触发回复

### 停止机器人

按 `Ctrl+C` 或关闭终端窗口即可。

## 配置说明

### 环境变量（可选）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| MEMORY_LIMIT | 20 | 单会话最大缓存消息数 |
| MODEL | deepseek-r1:8b | 对话模型名称 |
| VISION_MODEL | minicpm-v:8b | 视觉模型名称 |
| STICKER_PROB | 0.35 | 随机发送表情包概率 |

### 表情包配置

当前内置三张表情包，位于 `bot.py` 的 `STICKERS` 列表中：

| key | 情绪 | 适用场景 |
|-----|------|----------|
| angry | 生气怒吼 | 生气、抗议、急切 |
| cheer | 开心比心 | 开心、示爱、友好 |
| pout | 傲娇鼓脸 | 傲娇、生闷气 |

## 注意事项

1. **API Key 安全**：上传代码前务必替换 APPID 和 SECRET 为占位符
2. **SSL 证书问题**：如遇到 SSL 证书验证失败，临时设置 `http.sslVerify=false`
3. **内存占用**：两个 8B 模型同时加载约占用 10.7GB 显存，确保显卡显存充足
4. **网络要求**：天气 API 需要访问 Open-Meteo，图片识别需要访问公网图床

## 开源协议

本项目采用 MIT 协议开源，详见 [LICENSE](LICENSE)。

---

Copyright (c) 2026 小星野酱喵
