"""DeepSeek API client for novel-to-storyboard parsing.

Uses OpenAI-compatible API format. Set DEEPSEEK_API_KEY environment variable.
"""

import json
import os
import urllib.request
import urllib.error

DEEPSEEK_API = "https://api.deepseek.com/v1/chat/completions"

STORYBOARD_SYSTEM_PROMPT = """你是短视频漫剧剪辑师。从小说段落中选出最具戏剧张力的片段，转为分镜脚本。

核心原则：
- 你不是在"翻译"小说，你是在"剪辑"——只选必须用画面呈现的戏
- 开场第一个镜头必须抓眼：冲突、反转、高情绪、强视觉冲击
- 跳过环境描写、心理独白、过渡段落、平淡叙述
- 每段小说出 3-8 个最关键镜头，宁缺毋滥
- 对话交锋优先，动作冲突优先，情感爆发优先
- 三秒定胜负——前三个镜头决定观众是否划走

输出格式严格为:
{
  "title": "片段标题(中文，吸睛风格)",
  "frames": [
    {
      "frame_id": 1,
      "shot_type": "全景/中景/近景/特写",
      "scene": "场景英文描述(用于AI绘图prompt，简洁但带情绪氛围)",
      "characters": ["角色名", ...],
      "action": "角色动作描述",
      "expression": "表情描述",
      "dialogue": "对话文本或null",
      "camera": "镜头角度描述",
      "duration_sec": 3
    }
  ]
}

要求:
- 角色名使用原文中的名字，characters 列表只列出当前镜头实际出现的角色
- 每个对话轮次对应一个近景/特写镜头
- 场景切换时用全景建立空间
- scene 用英文，适合直接做 AI 绘图 prompt
- 每个镜头 2-5 秒，高潮镜头可多给 1-2 秒"""


def parse_novel_to_storyboard(novel_text: str, api_key: str = None,
                               character_names: list = None) -> dict:
    """Parse a novel segment into storyboard frames via DeepSeek API.

    If character_names is provided, the LLM will use those exact names
    when populating the 'characters' field of each frame.
    """
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY not set")

    user_msg = f"请解析以下小说段落为分镜脚本:\n\n{novel_text}"
    if character_names:
        user_msg += (
            f"\n\n故事中已绑定的角色：{', '.join(character_names)}"
            f"（请在分镜中使用这些确切的名字）"
        )

    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": STORYBOARD_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }).encode()

    req = urllib.request.Request(DEEPSEEK_API, data=body)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            content = data["choices"][0]["message"]["content"]
            content = content.strip()
            if content.startswith("```"):
                content = content[content.find("\n") + 1:]
                if content.endswith("```"):
                    content = content[:-3]
            return json.loads(content)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"DeepSeek API error {e.code}: {e.read().decode()}")
    except json.JSONDecodeError:
        raise RuntimeError(f"Failed to parse LLM response as JSON:\n{content}")


def frames_to_prompts(storyboard: dict) -> list[dict]:
    """Convert storyboard frames to image generation prompts."""
    negative = ("complex shading, gradient, realistic, 3d, detailed background, "
                "hair strands, skin texture, blurry, deformed, high detail, nsfw, "
                "lowres, bad anatomy, bad hands, text, watermark")

    results = []
    for frame in storyboard.get("frames", []):
        chars = ", ".join(frame.get("characters", ["1girl"]))
        prompt = (
            f"{chars}, {frame['scene']}, {frame['action']}, {frame['expression']}, "
            f"{frame['shot_type']}, {frame.get('camera', '')}, "
            f"simple anime, flat colors, cel shading, clean black outlines, "
            f"2D animation, no gradient, solid color fills, cute anime face"
        )
        results.append({
            "frame_id": frame["frame_id"],
            "prompt": prompt,
            "negative": negative,
            "scene": frame["scene"],
            "characters": frame.get("characters", []),
            "shot_type": frame.get("shot_type", ""),
            "dialogue": frame.get("dialogue"),
        })
    return results
