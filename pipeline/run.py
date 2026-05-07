"""Pipeline: novel + character ref → MP4 comic video.

Usage:
    python pipeline/run.py --novel "小说文本" --char-ref char.png
    python pipeline/run.py --novel-file ch1.txt --char-ref char.png
    python pipeline/run.py --novel-file ch1.txt --char-ref char.png --voice yunxi
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from script_parser.llm_client import parse_novel_to_storyboard, frames_to_prompts

COMFYUI_URL = "http://127.0.0.1:8188"
WORKFLOW_PATH = ROOT / "workflows" / "char2frame.json"
OUTPUT_DIR = ROOT / "output"


def check_comfyui():
    try:
        urllib.request.urlopen(f"{COMFYUI_URL}/api/queue", timeout=5)
    except Exception as e:
        sys.exit(f"Cannot connect to ComfyUI at {COMFYUI_URL}: {e}")


def queue_prompt(workflow):
    body = json.dumps({"prompt": workflow, "client_id": "pipeline-runner"}).encode()
    req = urllib.request.Request(f"{COMFYUI_URL}/api/prompt", data=body)
    resp = json.loads(urllib.request.urlopen(req).read())
    if "error" in resp:
        sys.exit(f"ComfyUI error: {resp['error']}")
    return resp["prompt_id"]


def wait_for_result(prompt_id, timeout=300):
    start = time.time()
    while time.time() - start < timeout:
        with urllib.request.urlopen(f"{COMFYUI_URL}/api/history/{prompt_id}") as r:
            hist = json.loads(r.read())
        if prompt_id in hist:
            entry = hist[prompt_id]
            if entry.get("status", {}).get("status_str") == "error":
                msgs = entry["status"].get("messages", [["unknown"]])
                sys.exit(f"Generation failed: {msgs[0]}")
            if "outputs" in entry:
                images = []
                for nid, out in entry["outputs"].items():
                    for img in out.get("images", []):
                        images.append(img)
                return images
        time.sleep(3)
    sys.exit(f"Timeout ({timeout}s)")


def generate_frame(workflow_template, frame_data, char_ref, output_prefix):
    wf = json.loads(json.dumps(workflow_template))
    wf["2"]["inputs"]["text"] = frame_data["prompt"]
    wf["3"]["inputs"]["text"] = frame_data["negative"]
    wf["8"]["inputs"]["image"] = char_ref
    wf["17"]["inputs"]["filename_prefix"] = output_prefix

    prompt_id = queue_prompt(wf)
    images = wait_for_result(prompt_id)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for img in images:
        fn = img["filename"]
        sub = img.get("subfolder", "")
        url = f"{COMFYUI_URL}/api/view?filename={fn}&subfolder={sub}&type=output"
        dest = OUTPUT_DIR / fn
        urllib.request.urlretrieve(url, dest)
        saved.append(str(dest))
    return saved


def run_pipeline(novel_text, char_ref, api_key=None, voice="xiaoxiao",
                 speed=1.0, output_dir=None, bgm=None):
    global OUTPUT_DIR
    if output_dir:
        OUTPUT_DIR = Path(output_dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1/5: Check ComfyUI
    print("1/5 Checking ComfyUI...")
    check_comfyui()

    # 2/5: LLM storyboard
    print("2/5 Parsing novel to storyboard...")
    storyboard = parse_novel_to_storyboard(novel_text, api_key)
    title = storyboard.get("title", "untitled")
    frames = storyboard.get("frames", [])
    print(f"  Title: {title}  |  Frames: {len(frames)}")
    for f in frames:
        dlg = f.get("dialogue") or "(narration)"
        print(f"    [{f['frame_id']}] {f['shot_type']} | {dlg[:30]}")

    # 3/5: Generate TTS for dialogue lines
    print("3/5 Generating voiceover...")
    from video.tts import speak

    tts_dir = OUTPUT_DIR / "audio"
    tts_dir.mkdir(exist_ok=True)

    # Create silence audio for frames without dialogue
    sil_path = str(tts_dir / "_silence.wav")
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "anullsrc=r=24000:cl=mono",
        "-t", "1", sil_path,
    ], check=True, capture_output=True)

    frame_audio = []
    for frame in frames:
        dialogue = frame.get("dialogue")
        fid = frame["frame_id"]
        if dialogue:
            audio_path = str(tts_dir / f"frame_{fid:03d}.wav")
            dur = speak(dialogue, audio_path, voice=voice, speed=speed)
            frame_audio.append({"frame_id": fid, "audio_path": audio_path,
                                "duration": dur, "dialogue": dialogue})
            print(f"  [{fid}] {dur:.1f}s | {dialogue[:30]}...")
        else:
            frame_audio.append({"frame_id": fid, "audio_path": sil_path,
                                "duration": frame.get("duration_sec", 3.0),
                                "dialogue": None})

    # 4/5: Generate images
    print(f"4/5 Generating {len(frames)} frames...")
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    frame_prompts = frames_to_prompts(storyboard)

    frame_images = []
    for fp in frame_prompts:
        fid = fp["frame_id"]
        prefix = f"frame_{fid:03d}"
        print(f"  Frame {fid}: {fp['shot_type']}")
        saved = generate_frame(workflow, fp, char_ref, prefix)
        frame_images.append({"frame_id": fid, "images": saved})

    # 5/5: Composite MP4
    print("5/5 Compositing MP4...")
    composite_frames = []
    for fi, fa in zip(frame_images, frame_audio):
        subtitle = fa.get("dialogue") or ""
        composite_frames.append({
            "image": fi["images"][0],
            "audio": fa["audio_path"],
            "subtitle": subtitle,
            "duration": fa["duration"],
        })

    from video.composer import compose_video
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_title = title.replace(" ", "_").replace("/", "")[:30]
    video_path = str(OUTPUT_DIR / f"{safe_title}_{timestamp}.mp4")
    compose_video(composite_frames, video_path, bgm_path=bgm)

    print(f"\nDone! Video: {video_path}")
    return video_path


def main():
    parser = argparse.ArgumentParser(description="AI Comic Pipeline (novel to MP4)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--novel", help="Novel text")
    group.add_argument("--novel-file", help="Novel text file")
    parser.add_argument("--char-ref", required=True, help="Character ref image")
    parser.add_argument("--api-key", help="DeepSeek API key")
    parser.add_argument("--voice", default="xiaoxiao",
                        choices=["xiaoxiao", "yunxi", "xiaoyi", "yunyang", "xiaobei"])
    parser.add_argument("--speed", type=float, default=1.1, help="TTS speed")
    parser.add_argument("--bgm", help="Background music path")
    parser.add_argument("--output-dir", help="Output directory")
    args = parser.parse_args()

    if args.novel_file:
        novel_text = Path(args.novel_file).read_text(encoding="utf-8").strip()
    else:
        novel_text = args.novel
    if not novel_text:
        sys.exit("Empty novel text")

    run_pipeline(novel_text, args.char_ref, args.api_key,
                 voice=args.voice, speed=args.speed,
                 output_dir=args.output_dir, bgm=args.bgm)


if __name__ == "__main__":
    main()
