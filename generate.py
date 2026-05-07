"""generate.py — ComfyUI 动漫图片生成脚本.

用法:
    python generate.py "一只猫在太空"                    # 基础生成
    python generate.py "樱花树下的少女" --style ghibli   # 吉卜力风格
    python generate.py "机甲战士" --style cyberpunk       # 赛博朋克
    python generate.py --style-list                       # 列出所有风格
    python generate.py "..." --model "anything-v5.safetensors"
    python generate.py "..." --steps 30 --cfg 8 --width 768 --height 512
    python generate.py "..." --char ref.png               # 角色锚定生成
    python generate.py "..." --char ref.png --scene play  # 角色+场景
"""

import argparse
import json
import random
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).parent
WORKFLOW_DIR = ROOT / "workflows"
OUTPUT_DIR = ROOT / "output"
COMFYUI_URL = "http://127.0.0.1:8188"

# ── 动漫风格预设 ──────────────────────────────────────────────

ANIME_STYLES = {
    "none": {
        "name": "无（纯提示词）",
        "positive_suffix": "",
        "negative": "low quality, worst quality, deformed, blurry, bad anatomy, watermark, text",
    },
    "anime": {
        "name": "日系动漫",
        "positive_suffix": ", anime style, masterpiece, best quality, vibrant colors, clean lineart, cel shading, 2d animation style, studio quality",
        "negative": "low quality, worst quality, deformed, blurry, bad anatomy, watermark, text, extra fingers, 3d, realistic, photorealistic, western artstyle, sketch",
    },
    "ghibli": {
        "name": "吉卜力风格",
        "positive_suffix": ", Studio Ghibli style, Hayao Miyazaki, soft painterly background, warm lighting, hand-drawn animation, nostalgic atmosphere, detailed environment",
        "negative": "low quality, worst quality, deformed, blurry, photorealistic, 3d render, western cartoon, dark theme, gloomy, oversaturated",
    },
    "shinkai": {
        "name": "新海诚风格",
        "positive_suffix": ", Makoto Shinkai style, cinematic lighting, vivid sky, lens flare, highly detailed background, emotional atmosphere, beautiful clouds, 8k",
        "negative": "low quality, worst quality, deformed, blurry, bad anatomy, sketch, black and white, dark, gloomy",
    },
    "donghua": {
        "name": "国漫风格",
        "positive_suffix": ", Chinese donghua style, ink wash aesthetic, elegant, flowing fabric, martial arts, gufeng, refined colors, painterly background",
        "negative": "low quality, worst quality, deformed, blurry, bad anatomy, japanese anime style, western artstyle, 3d render",
    },
    "chibi": {
        "name": "Q版可爱",
        "positive_suffix": ", chibi style, cute, kawaii, super deformed, big head, small body, pastel colors, simple background, adorable expression",
        "negative": "low quality, worst quality, deformed, realistic, photorealistic, 3d, horror, dark, scary, muscular, tall",
    },
    "cyberpunk": {
        "name": "赛博朋克动漫",
        "positive_suffix": ", cyberpunk anime style, neon lights, futuristic city, holographic displays, mecha, chrome details, night scene, rain, blade runner aesthetic",
        "negative": "low quality, worst quality, deformed, blurry, natural landscape, rural, medieval, daylight, bright sunlight",
    },
    "watercolor": {
        "name": "水彩动漫",
        "positive_suffix": ", watercolor anime style, soft brush strokes, ink bleed effect, pastel tones, dreamy atmosphere, flowing colors, artistic, hand-painted",
        "negative": "low quality, worst quality, deformed, blurry, sharp lines, 3d render, photorealistic, cel shading, thick outlines, dark colors",
    },
}

DEFAULT_NEGATIVE = "low quality, worst quality, deformed, blurry, bad anatomy, watermark, text"

# ── 画面比例预设 ──────────────────────────────────────────────

RATIO_PRESETS = {
    "9:16":  (576, 1024),   # 竖屏短视频（漫剧主用）
    "16:9":  (1024, 576),  # 横屏宽屏
    "1:1":   (640, 640),   # 方形
    "4:3":   (768, 576),   # 横屏标准
    "3:4":   (576, 768),   # 竖屏标准
}


def translate_prompt(text):
    """检测中文并自动翻译为英文。翻译失败则返回原文。"""
    if not re.search(r'[一-鿿]', text):
        return text  # 不含中文，跳过
    try:
        from translate import Translator
        t = Translator(to_lang="en", from_lang="zh")
        result = t.translate(text)
        if result:
            # 修复常见歧义：避免 "a black, short-haired" 被当成黑人
            result = re.sub(r'\ba black,\s*', 'a girl with black hair and ', result, flags=re.I)
            result = re.sub(r'\ba black\b', 'a girl with black hair', result, flags=re.I)
            print(f"  (中文自动翻译: {result})")
            return result
    except Exception as e:
        print(f"  翻译失败，使用原文: {e}")
    return text


def check_comfyui():
    try:
        urllib.request.urlopen(f"{COMFYUI_URL}/api/queue", timeout=5)
    except (urllib.error.URLError, OSError) as e:
        sys.exit(f"无法连接 ComfyUI ({COMFYUI_URL}): {e}\n请确认 ComfyUI 正在运行。")


def load_workflow(name):
    path = WORKFLOW_DIR / f"{name}.json"
    if not path.exists():
        sys.exit(f"工作流文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def queue_prompt(workflow_data):
    body = json.dumps({"prompt": workflow_data, "client_id": "sd-generate"}).encode()
    req = urllib.request.Request(f"{COMFYUI_URL}/api/prompt", data=body)
    resp = json.loads(urllib.request.urlopen(req).read())
    if "error" in resp:
        sys.exit(f"ComfyUI 返回错误: {resp['error']}")
    return resp["prompt_id"]


def get_history(prompt_id):
    with urllib.request.urlopen(f"{COMFYUI_URL}/api/history/{prompt_id}") as resp:
        return json.loads(resp.read())


def wait_for_result(prompt_id, timeout=300):
    start = time.time()
    while time.time() - start < timeout:
        history = get_history(prompt_id)
        if prompt_id in history:
            entry = history[prompt_id]
            if entry.get("status", {}).get("status_str") == "error":
                msg = entry["status"].get("messages", [["未知错误"]])[0]
                sys.exit(f"生成失败: {msg[1] if len(msg) > 1 else msg[0]}")
            if "outputs" in entry:
                return entry["outputs"]
        time.sleep(2)
    sys.exit(f"生成超时（{timeout}秒），请检查 ComfyUI 控制台。")


def download_images(outputs, prefix):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for node_id, node_output in outputs.items():
        for img in node_output.get("images", []):
            filename = img["filename"]
            subfolder = img.get("subfolder", "")
            params = f"filename={filename}&subfolder={subfolder}&type=output"
            url = f"{COMFYUI_URL}/api/view?{params}"
            dest = OUTPUT_DIR / f"{prefix}_{filename}"
            urllib.request.urlretrieve(url, dest)
            saved.append(dest)
    return saved


def build_workflow(template, prompt, negative, seed, steps, cfg, width, height, model):
    data = json.loads(template)
    data["2"]["inputs"]["text"] = prompt
    data["3"]["inputs"]["text"] = negative

    data["5"]["inputs"]["seed"] = seed if seed is not None else random.randint(0, 2**63)
    data["5"]["inputs"]["steps"] = steps
    data["5"]["inputs"]["cfg"] = cfg
    data["4"]["inputs"]["width"] = width
    data["4"]["inputs"]["height"] = height
    if model:
        data["1"]["inputs"]["ckpt_name"] = model

    return data


def upload_image(image_path):
    """Upload an image to ComfyUI's input directory via API."""
    import base64
    path = Path(image_path)
    if not path.exists():
        sys.exit(f"Image not found: {image_path}")
    name = path.name
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()
    body = json.dumps({"image": encoded, "filename": name, "overwrite": True}).encode()
    req = urllib.request.Request(f"{COMFYUI_URL}/api/upload/image", data=body)
    resp = json.loads(urllib.request.urlopen(req).read())
    if "error" in resp:
        sys.exit(f"Upload failed: {resp['error']}")
    return name


def build_char_workflow(template, prompt, negative, seed, steps, cfg,
                        char_ref, width, height, model):
    """Build workflow for character-anchored generation (char2frame)."""
    data = json.loads(template)
    data["2"]["inputs"]["text"] = prompt
    data["3"]["inputs"]["text"] = negative
    data["8"]["inputs"]["image"] = char_ref
    data["14"]["inputs"]["width"] = width
    data["14"]["inputs"]["height"] = height
    data["15"]["inputs"]["seed"] = seed if seed is not None else random.randint(0, 2**63)
    data["15"]["inputs"]["steps"] = steps
    data["15"]["inputs"]["cfg"] = cfg
    if model:
        data["1"]["inputs"]["ckpt_name"] = model
    return data


def save_metadata(image_paths, params):
    """保存生成参数到 JSON 文件"""
    if not image_paths:
        return
    meta = {**params, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
    meta_path = Path(str(image_paths[0]) + ".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def make_output_prefix(prompt, style_key):
    """从 prompt 和风格生成简短的输出文件名前缀."""
    short = prompt[:20].replace(" ", "_").replace("/", "").replace("\\", "")
    if style_key and style_key != "anime":
        short = f"{style_key}_{short}"
    return short


def list_styles():
    print("可用动漫风格:")
    for key, s in ANIME_STYLES.items():
        print(f"  {key:<14} {s['name']}")


def main():
    parser = argparse.ArgumentParser(description="ComfyUI 动漫图片生成")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("prompt", nargs="?", help="正向提示词")
    group.add_argument("--file", "-f", help="从文件读取 prompt")
    group.add_argument("--batch", "-b", help="从文件读取多条 prompt（每行一条）")
    parser.add_argument("--negative", "-n", default=None, help="负面提示词（覆盖风格默认值）")
    parser.add_argument("--style", "-s", default="anime", choices=list(ANIME_STYLES.keys()),
                        help="动漫风格预设（默认 anime）")
    parser.add_argument("--style-list", action="store_true", help="列出所有风格后退出")
    parser.add_argument("--model", "-m", default=None, help="模型文件名（覆盖工作流默认值）")
    parser.add_argument("--seed", type=int, default=None, help="随机种子（默认随机）")
    parser.add_argument("--steps", type=int, default=28, help="采样步数（默认 28）")
    parser.add_argument("--cfg", type=float, default=7.5, help="CFG scale（默认 7.5）")
    parser.add_argument("--width", type=int, default=None, help="图片宽度（默认 512）")
    parser.add_argument("--height", type=int, default=None, help="图片高度（默认 512）")
    parser.add_argument("--ratio", "-r", default=None, choices=list(RATIO_PRESETS.keys()),
                        help="画面比例预设（覆盖 --width/--height）")
    parser.add_argument("--char", "-c", default=None,
                        help="角色定妆照路径（启用角色锚定模式）")
    parser.add_argument("--scene", default=None,
                        help="场景描述（配合 --char 使用，添加到 prompt）")
    parser.add_argument("--count", type=int, default=None, help="每段 prompt 生成 N 张变体（不同种子）")
    parser.add_argument("--output", "-o", default=None, help="输出文件名前缀")
    parser.add_argument("--no-translate", action="store_true", help="禁止中文自动翻译")
    parser.add_argument("--dry-run", action="store_true", help="仅打印工作流，不执行")
    args = parser.parse_args()

    # 应用比例预设
    if args.ratio:
        args.width, args.height = RATIO_PRESETS[args.ratio]
    if args.width is None:
        args.width = 512
    if args.height is None:
        args.height = 512

    if args.style_list:
        list_styles()
        return

    # 获取 prompts
    if args.batch:
        lines = Path(args.batch).read_text(encoding="utf-8").strip().splitlines()
        prompts = [l.strip() for l in lines if l.strip()]
        if not prompts:
            sys.exit(f"批处理文件为空或无效: {args.batch}")
    elif args.file:
        content = Path(args.file).read_text(encoding="utf-8").strip()
        if not content:
            sys.exit(f"文件为空: {args.file}")
        prompts = [content]
    elif args.prompt:
        prompts = [args.prompt]
    else:
        parser.print_help()
        sys.exit(1)

    # 风格预设
    style = ANIME_STYLES.get(args.style, ANIME_STYLES["anime"])
    negative = args.negative if args.negative is not None else style["negative"]

    if args.dry_run:
        print(f"风格: {style['name']}")
        print(f"Negative: {negative}")
        print(f"Steps: {args.steps} | CFG: {args.cfg} | Size: {args.width}x{args.height}")
        if args.model:
            print(f"Model: {args.model}")
        print()
        template = load_workflow("txt2img")
        workflow = build_workflow(template, "{{prompt}}" + style["positive_suffix"],
                                  negative, args.seed, args.steps, args.cfg,
                                  args.width, args.height, args.model)
        print(json.dumps(workflow, indent=2, ensure_ascii=False))
        return

    check_comfyui()

    # Upload char reference if provided
    char_ref_name = None
    if args.char:
        char_ref_name = upload_image(args.char)

    total_tasks = len(prompts) * (args.count or 1)
    task_num = 0

    for prompt in prompts:
        if not args.no_translate:
            prompt = translate_prompt(prompt)
        variants = args.count or 1
        for v in range(variants):
            full_prompt = prompt + style["positive_suffix"]
            if args.scene:
                full_prompt += f", {args.scene}"
            current_seed = args.seed if args.seed is not None else random.randint(0, 2**63)
            task_num += 1

            label_variant = f"  ({v+1}/{variants})" if variants > 1 else ""
            print(f"\n[{task_num}/{total_tasks}] {prompt[:60]}{'...' if len(prompt) > 60 else ''}{label_variant}")
            print(f"  风格: {style['name']} | Seed: {current_seed} | Size: {args.width}x{args.height}")
            if char_ref_name:
                print(f"  角色参考: {args.char}")

            if char_ref_name:
                template = load_workflow("char2frame")
                workflow = build_char_workflow(template, full_prompt, negative,
                                               current_seed, args.steps, args.cfg,
                                               char_ref_name, args.width, args.height,
                                               args.model)
            else:
                template = load_workflow("txt2img")
                workflow = build_workflow(template, full_prompt, negative, current_seed,
                                          args.steps, args.cfg, args.width, args.height,
                                          args.model)

            prompt_id = queue_prompt(workflow)
            print(f"  任务 ID: {prompt_id}")
            outputs = wait_for_result(prompt_id)

            prefix = args.output or make_output_prefix(prompt, args.style)
            if variants > 1:
                prefix = f"{prefix}_v{v+1}"
            saved = download_images(outputs, prefix)

            # 保存元数据
            meta_params = {
                "prompt": prompt,
                "full_prompt": full_prompt,
                "negative": negative,
                "style_name": style["name"],
                "style_key": args.style,
                "seed": current_seed,
                "steps": args.steps,
                "cfg": args.cfg,
                "width": args.width,
                "height": args.height,
                "model": args.model,
                "char_ref": args.char,
                "scene": args.scene,
                "variant": v + 1 if variants > 1 else None,
            }
            save_metadata(saved, meta_params)

            for p in saved:
                print(f"  {p.name}")

    print(f"\n全部完成! 共生成 {total_tasks} 组图片。")


if __name__ == "__main__":
    main()
