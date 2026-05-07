"""小说文本 → 分镜结构化 JSON。"""
import json
import re
from .llm_client import chat

SYSTEM_PROMPT = """你是一个专业的竖屏短剧动态漫画分镜师。请将用户提供的小说段落拆分为快节奏漫剧分镜脚本。

【剧情规则 — 必须遵守】
1. 开篇第1个分镜必须用冲突/悬念/危机开场，禁止平淡铺垫
2. 全程无冷场，每2-3个分镜一个小钩子（悬念/反转/冲突）
3. 删除所有无效铺垫、无关场景描写、平淡日常对话——只保留服务于冲突/爽点/悬念的内容
4. 角色台词必须短、狠、有情绪，严格控制在10字以内
5. 每个分镜一个独立画面，镜头类型：特写/近景/中景/远景
6. 每集结尾分镜必须留悬念/钩子，引导追更
7. 优先生成打脸、反转、冲突类情节，拒绝平淡日常

【输出格式】
严格的 JSON 格式，不要有任何 markdown 代码块标记或额外文字。"""


def parse_novel(novel_text, style_profile=None):
    """解析小说文本为分镜 JSON。

    Args:
        novel_text: 小说文本
        style_profile: 可选，reference_analyzer.StyleProfile 实例，注入画风约束
    """
    style_context = style_profile.to_storyboard_context() if style_profile else ""
    user_prompt = f"""请将以下小说段落拆分为快节奏漫剧分镜脚本：

{novel_text}

输出 JSON 格式：
{{
  "title": "章节标题",
  "scenes": [
    {{
      "scene_id": 1,
      "characters": ["角色A", "角色B"],
      "location": "地点描述",
      "action": "角色正在做的动作",
      "dialogue": "角色A: 台词（≤10字，如无对话则为空字符串）",
      "camera": "中景",
      "mood": "氛围"
    }}
  ]
}}"""

    system = SYSTEM_PROMPT
    if style_profile:
        system += "\n\n" + style_profile.to_storyboard_context()

    response = chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt}
    ], temperature=0.7)

    json_match = re.search(r'\{[\s\S]*\}', response)
    if json_match:
        return json.loads(json_match.group())
    raise ValueError(f"解析失败，API 返回不是合法 JSON:\n{response[:500]}")
