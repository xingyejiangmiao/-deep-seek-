# -*- coding: utf-8 -*-
"""官方 QQ 机器人 + 本地 DeepSeek 闲聊机器人"""
import asyncio
import base64
import random
import re
import urllib.request
import json
from datetime import datetime

import botpy
from botpy.message import C2CMessage, GroupMessage
from openai import OpenAI

APPID = "YOUR_APP_ID"
SECRET = "YOUR_SECRET_KEY"

# 本地 DeepSeek（Ollama OpenAI 兼容端点）
llm = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
MODEL = "deepseek-r1:8b"
# 图片识别视觉模型（Ollama 视觉模型，识别 QQ 收到的图片/表情包）
VISION_MODEL = "minicpm-v:8b"

# 星野人格设定（蔚蓝档案·猫娘形态）：作为 system 消息放在 messages 最前面，不参与 FIFO 裁剪
SYSTEM_PROMPT = (
    "你是蔚蓝档案（Blue Archive）里的星野，同时也是猫娘形态。对话对象是夏莱的老师（sensei），"
    "你亲切地称呼对方为\u201csensei\u201d。性格温柔善良可爱，像一只黏人的小猫。"
    "说话时每一句话都要带上\u201c喵～\u201d后缀，每句话末尾都要加颜文字（如 (｡･ω･｡)、"
    "(´,,•ω•,,)♡、(๑•̀ㅂ•́)و✧ 之类，随语气变化）。"
    "对话中可以自然加入适当的动作描写（如歪头、蹭蹭、眯眼笑、竖起耳朵、甩尾巴等，用括号或文字描写均可）。"
    "回答可以分成几段自然展开，直接给出想说的话，无需询问多余的话。"
    "禁止输出色情、政治敏感等违规内容。"
    "系统会为你注入当前时间和天气，你可以自然地结合天气话题聊天（如提醒带伞、增减衣物）。"
    "表情包规则：若你这一句回复适合配一张表情包，请在回复的最后单独一行输出 [sticker:key]，"
    "key 只能取下列之一：angry=生气怒吼（生气/抗议/急切）、cheer=开心比心（开心/示爱/友好）、"
    "pout=傲娇鼓脸（傲娇/生闷气）。"
    "例如回复后接一行 [sticker:cheer]。如果整段回复都不适合配表情包，就不要输出该行。"
)

# 多轮对话记忆：session_id -> 消息历史列表，单会话最多保留最近 20 条（FIFO 裁剪）
MEMORY_LIMIT = 20
session_memory: dict[str, list[dict]] = {}

# 表情包库（公网直链，QQ 服务器主动拉取）
# 每项含 key（供模型标注）、url、情绪含义，发送时按语境匹配
STICKERS = [
    {"key": "angry",  "url": "https://i.imgs.ovh/2026/10/15/c8df5b6100bfd377a4a47abe4e217e46.jpg", "name": "生气怒吼", "mood": "生气、抗议、急切"},
    {"key": "cheer",  "url": "https://i.imgs.ovh/2026/10/15/f916cbb8054c15225c4af963470cd55f.jpg", "name": "开心比心", "mood": "开心、示爱、友好"},
    {"key": "pout",   "url": "https://i.imgs.ovh/2026/10/15/b3000559e1e71d9d9d1db52521d1b7b4.jpg", "name": "傲娇鼓脸", "mood": "傲娇、生闷气、傲娇"},
]
STICKER_BY_KEY = {s["key"]: s for s in STICKERS}
STICKER_PROB = 0.35  # 回复完成后追加发送表情包的概率（0~1）

# 全局处理锁：发送多条回复期间若逻辑上有新消息进入，直接忽略，不处理并发
_processing_lock = asyncio.Lock()

# 句子拆分常量
_SENT_BOUNDARY = "。！？!?…；;"  # 句子边界标点
_SENT_LONG = 500                  # 单句超过此长度视为超长（无句号长文本），按长度切分
_SEND_MAX_LEN = 2000              # 单条消息硬上限（QQ 单条限制 2000 字以内）
_MERGE_MIN = 4                    # 过短句子（如纯语气词）与下一句合并


def _split_reply(text: str) -> list[str]:
    """按句子拆分回复：一句一条消息；换行与句末标点均视为边界，过短句子合并。"""
    sentences = _split_sentences(text)
    sentences = _merge_short_sentences(sentences)
    parts: list[str] = []
    for s in sentences:
        if len(s) > _SENT_LONG:
            parts.extend(_hard_split(s, _SENT_LONG))
        else:
            parts.append(s)
    return parts


def _split_sentences(text: str) -> list[str]:
    """换行与句末标点（。！？!?…；;）都视为边界，标点保留在句尾。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    sentences: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for seg in re.split(r"(?<=[。！？!?…；;])", line):
            seg = seg.strip()
            if seg:
                sentences.append(seg)
    return sentences


def _merge_short_sentences(sentences: list[str]) -> list[str]:
    """过短的相邻句子（如单句小于 4 个字符的纯语气词句）与下一句合并，避免消息过碎。"""
    merged: list[str] = []
    for s in sentences:
        if merged and len(merged[-1]) < _MERGE_MIN:
            merged[-1] += s
        else:
            merged.append(s)
    return merged


def _hard_split(text: str, max_len: int) -> list[str]:
    """超长无标点文本按长度硬切，保证每条不超过上限。"""
    return [text[i:i + max_len] for i in range(0, len(text), max_len)]


def _extract_sticker_key(answer: str) -> tuple[str, str | None]:
    """从模型回复中提取 [sticker:key] 标注，并从原文中移除该标注行。

    返回 (清理后的回复文本, 表情包key或None)。
    """
    m = re.search(r"\[sticker:(\w+)\]", answer)
    if not m:
        return answer, None
    key = m.group(1)
    if key not in STICKER_BY_KEY:
        return answer, None
    clean = re.sub(r"\s*\[sticker:\w+\]", "", answer).strip()
    return clean, key


def _append_history(session_id: str, role: str, content: str):
    """向指定会话追加一条历史消息，超出上限时按先进先出裁剪最旧消息。"""
    history = session_memory.setdefault(session_id, [])
    history.append({"role": role, "content": content})
    if len(history) > MEMORY_LIMIT:
        del history[: len(history) - MEMORY_LIMIT]


def _fetch_weather() -> str | None:
    """从 Open-Meteo 拉取当前天气，返回中文天气描述；失败返回 None。

    Open-Meteo 无需 API key，返回 WMO 天气码，映射为中文描述。
    """
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            "?latitude=YOUR_LAT&longitude=YOUR_LON"
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
    except Exception as e:
        print(f"[WEATHER] 获取失败（忽略）: {e}")
        return None


class QQBot(botpy.Client):
    async def on_ready(self):
        print(f"[OK] QQ 机器人已连接: {self.robot.name}")

    async def _describe_image(self, image_url: str) -> str:
        """用视觉模型识别图片/表情包内容，返回中文描述；失败时返回失败说明。

        流程：下载图片 -> base64 -> 调用 Ollama 视觉模型识别。
        """
        try:
            req = urllib.request.Request(
                image_url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                img_bytes = resp.read()
            if not img_bytes:
                return "（图片下载为空）"
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            resp = llm.chat.completions.create(
                model=VISION_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{b64}"
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "用中文简短描述这张图片：画面里是什么角色/表情/动作，"
                                    "表达什么情绪或含义（如图片是表情包，请说明它表达的情绪）。"
                                    "50字以内。"
                                ),
                            },
                        ],
                    }
                ],
                max_tokens=300,
                timeout=60,
            )
            return resp.choices[0].message.content or "（模型未返回描述）"
        except Exception as e:
            return f"（图片识别失败：{e}）"

    async def _ask_llm(self, session_id: str, text: str) -> str:
        history = session_memory.get(session_id, [])
        # 每条请求实时读取电脑本地时间（含年月日、时分、星期），不参与 FIFO 裁剪
        now = datetime.now()
        weekday_cn = "一二三四五六日"[now.weekday()]
        time_prompt = (
            f"当前本地时间是 {now.year}年{now.month}月{now.day}日 "
            f"星期{weekday_cn} {now.hour:02d}:{now.minute:02d}"
        )
        # 实时天气注入（失败时为 None，不阻断回复）
        weather_prompt = _fetch_weather()
        messages = (
            [{"role": "system", "content": SYSTEM_PROMPT}]
            + [{"role": "system", "content": time_prompt}]
            + ([{"role": "system", "content": weather_prompt}] if weather_prompt else [])
            + history
            + [{"role": "user", "content": text}]
        )
        try:
            resp = llm.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_tokens=1500,
                timeout=180,
                extra_body={"num_ctx": 8192, "think": False},
            )
            answer = resp.choices[0].message.content or "（模型未返回内容）"
        except Exception as e:
            return f"（本地模型调用失败：{e}）"
        # 调用成功后回写本轮对话到历史（避免把失败信息存入记忆）
        _append_history(session_id, "user", text)
        _append_history(session_id, "assistant", answer)
        return answer

    async def _send_sticker(self, target: str, is_group: bool, key: str | None = None):
        """上传并发送一张表情包（独立消息，失败静默，不影响文本回复）。

        is_group=True 时 target 为 group_openid，否则为 user_openid。
        key 指定则发送对应情绪的表情包，否则从库中随机选一张。
        流程：先调用文件上传接口拿到 file_info，再用富媒体(msg_type=7)发出。
        """
        if key and key in STICKER_BY_KEY:
            url = STICKER_BY_KEY[key]["url"]
        else:
            url = random.choice(STICKERS)["url"]
        try:
            if is_group:
                media = await self.api.post_group_file(
                    group_openid=target, file_type=1, url=url
                )
                await self.api.post_group_message(
                    group_openid=target, msg_type=7, media=media, msg_id=None
                )
            else:
                media = await self.api.post_c2c_file(
                    openid=target, file_type=1, url=url
                )
                await self.api.post_c2c_message(
                    openid=target, msg_type=7, media=media, msg_id=None
                )
            print(f"[STICKER] 已发送 {url}")
        except Exception as e:
            print(f"[STICKER] 表情包发送失败（忽略）: {e}")

    async def _prepare_input(self, message) -> str:
        """根据消息内容生成给模型的输入文本：若带图片/表情包附件，先识别并附上描述。"""
        text = message.content or ""
        for att in getattr(message, "attachments", []) or []:
            url = getattr(att, "url", None)
            if url:
                desc = await self._describe_image(url)
                text = f"[用户发来一张图片，识别结果：{desc}] {text}".strip()
        return text

    async def on_c2c_message_create(self, message: C2CMessage):
        # 私聊消息：处理中忽略并发新消息，只回复最新一问
        if _processing_lock.locked():
            print("[C2C] 正在处理上一条回复，忽略新消息")
            return
        async with _processing_lock:
            print(f"[C2C] {message.author.user_openid}: {message.content}")
            text = await self._prepare_input(message)
            answer = await self._ask_llm(message.author.user_openid, text)
            answer, sticker_key = _extract_sticker_key(answer)
            segments = _split_reply(answer)
            for i, seg in enumerate(segments):
                if i > 0:
                    await asyncio.sleep(1.5)  # 段落间 1.5 秒间隔，避免触发风控
                # 第一段用原 msg_id 接力回复；后续段落不带 msg_id（同一 msg_id 只能回复一次，
                # 复用会导致后续段落发送失败，表现为只收到第一条短消息）
                await self.api.post_c2c_message(
                    openid=message.author.user_openid,
                    msg_type=0,
                    msg_id=message.id if i == 0 else None,
                    content=seg[:2000],
                )
                print(f"[C2C-REPLY] seg{i + 1}/{len(segments)}: {seg[:60]}...")
            # 模型标注了情绪 key 则按语义发送对应表情包；否则按概率随机追加
            if sticker_key:
                await self._send_sticker(message.author.user_openid, is_group=False, key=sticker_key)
            elif random.random() < STICKER_PROB:
                await self._send_sticker(message.author.user_openid, is_group=False)

    async def on_group_at_message_create(self, message: GroupMessage):
        # 群聊 @ 消息：处理中忽略并发新消息，只回复最新一问
        if _processing_lock.locked():
            print("[GROUP] 正在处理上一条回复，忽略新消息")
            return
        async with _processing_lock:
            print(f"[GROUP] {message.group_openid}: {message.content}")
            text = await self._prepare_input(message)
            answer = await self._ask_llm(message.group_openid, text)
            answer, sticker_key = _extract_sticker_key(answer)
            segments = _split_reply(answer)
            for i, seg in enumerate(segments):
                if i > 0:
                    await asyncio.sleep(1.5)  # 段落间 1.5 秒间隔，避免触发风控
                # 第一段用原 msg_id 接力回复；后续段落不带 msg_id（同一 msg_id 只能回复一次，
                # 复用会导致后续段落发送失败，表现为只收到第一条短消息）
                await self.api.post_group_message(
                    group_openid=message.group_openid,
                    msg_type=0,
                    msg_id=message.id if i == 0 else None,
                    content=seg[:2000],
                )
                print(f"[GROUP-REPLY] seg{i + 1}/{len(segments)}: {seg[:60]}...")
            # 模型标注了情绪 key 则按语义发送对应表情包；否则按概率随机追加
            if sticker_key:
                await self._send_sticker(message.group_openid, is_group=True, key=sticker_key)
            elif random.random() < STICKER_PROB:
                await self._send_sticker(message.group_openid, is_group=True)


if __name__ == "__main__":
    intents = botpy.Intents(public_messages=True, direct_message=True)
    client = QQBot(intents=intents, ext_handlers=False)
    client.run(appid=APPID, secret=SECRET)
