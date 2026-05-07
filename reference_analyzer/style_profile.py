"""风格画像数据结构 — 序列化为 JSON，供分镜解析模块消费。"""
from dataclasses import dataclass, field, asdict
from typing import List, Tuple


@dataclass
class StyleProfile:
    """从参考图提取的风格画像。"""

    # 色调
    dominant_colors: List[Tuple[int, int, int]] = field(default_factory=list)
    avg_saturation: float = 0.0
    avg_brightness: float = 0.0
    warm_cool: str = "neutral"  # warm / cool / neutral

    # 线条
    line_density: float = 0.0  # 0=纯色块, 1=密集线稿
    edge_strength: str = "medium"  # soft / medium / strong
    is_flat_coloring: bool = True

    # 构图
    aspect_ratio: str = "9:16"
    camera_distance: str = "medium"  # close / medium / far

    # 氛围
    mood_tags: List[str] = field(default_factory=list)
    brightness_level: str = "medium"  # dark / medium / bright
    contrast_level: str = "medium"  # low / medium / high

    # CLIP 语义
    clip_tags: List[str] = field(default_factory=list)

    def to_prompt_suffix(self) -> str:
        """生成注入到 SD prompt 的风格关键词。"""
        parts = []
        if self.is_flat_coloring:
            parts.append("flat coloring, no shading")
        if self.line_density > 0.3:
            parts.append("clean lineart, black outline")
        elif self.line_density > 0.1:
            parts.append("soft lineart")
        if self.avg_saturation < 0.3:
            parts.append("pastel colors, low saturation")
        elif self.avg_saturation > 0.6:
            parts.append("vivid colors, high saturation")
        if self.warm_cool == "warm":
            parts.append("warm tone")
        elif self.warm_cool == "cool":
            parts.append("cool tone")
        if self.mood_tags:
            parts.append(", ".join(self.mood_tags[:3]))
        if self.clip_tags:
            parts.append(", ".join(self.clip_tags[:3]))
        return ", ".join(parts)

    def to_storyboard_context(self) -> str:
        """生成注入到 LLM 分镜 prompt 的风格约束文本。"""
        lines = ["【参考画风约束 — 所有分镜必须遵守以下视觉风格】"]
        if self.mood_tags:
            lines.append(f"整体氛围：{', '.join(self.mood_tags)}")
        lines.append(f"色调倾向：{'暖色调' if self.warm_cool == 'warm' else '冷色调' if self.warm_cool == 'cool' else '中性'}")
        lines.append(f"上色方式：{'纯平涂，完全无阴影无渐变' if self.is_flat_coloring else '有明暗层次和体积感'}")
        lines.append(f"线条风格：{'清晰黑色描边，线稿感强' if self.line_density > 0.3 else '柔和边缘，无线稿感'}")
        lines.append(f"画面亮度：{'暗沉低调' if self.brightness_level == 'dark' else '明亮高调' if self.brightness_level == 'bright' else '中等亮度'}")
        lines.append(f"色彩饱和度：{'低饱和柔和色调' if self.avg_saturation < 0.3 else '高饱和鲜艳色调' if self.avg_saturation > 0.6 else '中等饱和度'}")
        lines.append(f"镜头偏好：{'特写近景为主' if self.camera_distance == 'close' else '远景全景为主' if self.camera_distance == 'far' else '中景为主'}")
        if self.clip_tags:
            lines.append(f"风格标签：{', '.join(self.clip_tags[:5])}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)
