"""参考图风格分析 — CLIP 语义 + 规则分析（色调/线条/构图）。"""
from pathlib import Path
from PIL import Image
import numpy as np

from .style_profile import StyleProfile

_clip_model = None
_clip_processor = None


def _load_clip():
    global _clip_model, _clip_processor
    if _clip_model is not None:
        return True
    try:
        from transformers import CLIPModel, CLIPProcessor
        model_name = "openai/clip-vit-large-patch14"
        _clip_model = CLIPModel.from_pretrained(model_name)
        _clip_processor = CLIPProcessor.from_pretrained(model_name)
        return True
    except Exception:
        return False


def _extract_colors(img: Image.Image) -> dict:
    """色调分析：主色、饱和度、亮度、冷暖倾向。"""
    arr = np.array(img.convert("RGB"))
    hsv = np.array(img.convert("HSV"))

    saturation = float(hsv[:, :, 1].mean() / 255)
    brightness = float(hsv[:, :, 2].mean())

    r_mean = float(arr[:, :, 0].mean())
    b_mean = float(arr[:, :, 2].mean())
    if r_mean > b_mean * 1.1:
        warm_cool = "warm"
    elif b_mean > r_mean * 1.1:
        warm_cool = "cool"
    else:
        warm_cool = "neutral"

    pixels = arr.reshape(-1, 3)
    quantized = (pixels // 64).astype(int)
    color_bins = {}
    for q in quantized:
        key = tuple(q)
        color_bins[key] = color_bins.get(key, 0) + 1
    top = sorted(color_bins.items(), key=lambda x: x[1], reverse=True)[:5]
    dominant_colors = [(int(r * 64 + 32), int(g * 64 + 32), int(b * 64 + 32)) for (r, g, b), _ in top]

    brightness_level = "dark" if brightness < 85 else "bright" if brightness > 170 else "medium"

    return {
        "dominant_colors": dominant_colors,
        "avg_saturation": round(saturation, 3),
        "avg_brightness": round(brightness, 1),
        "warm_cool": warm_cool,
        "brightness_level": brightness_level,
    }


def _extract_lines(img: Image.Image) -> dict:
    """线条分析：边缘密度 → 线稿程度。"""
    from PIL import ImageFilter
    edges = np.array(img.convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    edge_ratio = float(edges.mean() / 255)
    line_density = round(min(edge_ratio * 5, 1.0), 3)

    if line_density > 0.5:
        edge_strength = "strong"
    elif line_density > 0.2:
        edge_strength = "medium"
    else:
        edge_strength = "soft"

    return {
        "line_density": line_density,
        "edge_strength": edge_strength,
        "is_flat_coloring": line_density > 0.15,
    }


def _extract_composition(img: Image.Image) -> dict:
    """构图分析：画幅比、景别推测。"""
    w, h = img.size
    ratio = w / h
    if ratio > 1.5:
        aspect = "16:9"
    elif ratio < 0.7:
        aspect = "9:16"
    elif ratio < 1.1:
        aspect = "1:1"
    else:
        aspect = "4:3"

    arr = np.array(img.convert("L"))
    h_h, w_w = arr.shape
    center = arr[h_h // 4:3 * h_h // 4, w_w // 4:3 * w_w // 4]
    center_detail = float(center.std())
    if center_detail > 60:
        camera = "close"
    elif center_detail > 30:
        camera = "medium"
    else:
        camera = "far"

    return {"aspect_ratio": aspect, "camera_distance": camera}


def _clip_analyze(img: Image.Image) -> dict:
    """CLIP 视觉模型语义分析。不可用时返回空。"""
    if not _load_clip():
        return {"clip_tags": [], "mood_tags": []}

    mood_candidates = [
        "bright cheerful anime scene",
        "dark tense dramatic scene",
        "romantic warm scene",
        "mysterious eerie scene",
        "peaceful calm slice of life",
        "action dynamic battle scene",
        "nostalgic emotional scene",
    ]
    style_candidates = [
        "flat coloring simple anime style",
        "detailed painted illustration",
        "clean lineart cartoon",
        "sketchy rough drawing",
        "watercolor soft illustration",
        "graphic bold pop art",
    ]

    try:
        texts = mood_candidates + style_candidates
        inputs = _clip_processor(text=texts, images=img, return_tensors="pt", padding=True)
        outputs = _clip_model(**inputs)
        probs = outputs.logits_per_image[0].softmax(dim=0)

        mood_scores = list(zip(mood_candidates, probs[:len(mood_candidates)].tolist()))
        style_scores = list(zip(style_candidates, probs[len(mood_candidates):].tolist()))
        mood_scores.sort(key=lambda x: x[1], reverse=True)
        style_scores.sort(key=lambda x: x[1], reverse=True)

        clip_tags = [s.split(" style")[0].replace(" anime", "").strip()
                     for s, p in style_scores if p > 0.1][:5]
        mood_tags = [s.split(" scene")[0].strip()
                     for s, p in mood_scores if p > 0.1][:3]

        return {"clip_tags": clip_tags, "mood_tags": mood_tags}
    except Exception:
        return {"clip_tags": [], "mood_tags": []}


def analyze_image(image_path: str) -> StyleProfile:
    """分析参考图片，返回完整 StyleProfile。

    Args:
        image_path: 参考图片路径

    Returns:
        StyleProfile，包含色调/线条/构图/氛围/CLIP标签。
    """
    img = Image.open(image_path).convert("RGB")

    color_info = _extract_colors(img)
    line_info = _extract_lines(img)
    comp_info = _extract_composition(img)
    clip_info = _clip_analyze(img)

    return StyleProfile(
        dominant_colors=color_info["dominant_colors"],
        avg_saturation=color_info["avg_saturation"],
        avg_brightness=color_info["avg_brightness"],
        warm_cool=color_info["warm_cool"],
        line_density=line_info["line_density"],
        edge_strength=line_info["edge_strength"],
        is_flat_coloring=line_info["is_flat_coloring"],
        aspect_ratio=comp_info["aspect_ratio"],
        camera_distance=comp_info["camera_distance"],
        mood_tags=clip_info["mood_tags"],
        brightness_level=color_info["brightness_level"],
        contrast_level="medium",
        clip_tags=clip_info["clip_tags"],
    )
