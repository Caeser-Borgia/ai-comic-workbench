"""分镜脚本 → 图像生成 prompt。"""
STYLE_SUFFIX = ", flat coloring, simple lineart, clean lines, no shading, pastel colors, anime style"
NEGATIVE = "complex shading, realistic, 3d, gradient, detailed shadows, heavy lines, oil painting"


def scene_to_prompt(scene, style_profile=None):
    """将单个分镜转换为图像生成参数。

    Args:
        scene: 分镜 dict，含 characters/location/action/mood/camera
        style_profile: 可选，reference_analyzer.StyleProfile 实例
    """
    char_desc = ", ".join(scene.get("characters", []))
    location = scene.get("location", "")
    action = scene.get("action", "")
    mood = scene.get("mood", "")
    camera = scene.get("camera", "")

    suffix = style_profile.to_prompt_suffix() if style_profile else STYLE_SUFFIX

    parts = [
        "anime style, flat coloring, simple lineart",
        char_desc,
        action,
        f"background: {location}" if location else "",
        f"{mood} atmosphere" if mood else "",
        f"{camera} shot" if camera else "",
        suffix,
    ]

    prompt = ", ".join(p for p in parts if p)

    return {
        "scene_id": scene["scene_id"],
        "prompt": prompt,
        "negative": NEGATIVE,
        "width": 576,
        "height": 1024,
        "dialogue": scene.get("dialogue", ""),
        "characters": scene.get("characters", []),
        "location": location,
    }
