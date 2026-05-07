"""webui.py — AI漫剧 Web 界面: 图片生成 + 角色锚定 + 小说→MP4"""

import html as _html
import json
import os
import random
import re
import sys
import time
import urllib.request
import urllib.error
import base64
import threading
import webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


ROOT = Path(__file__).parent
WORKFLOW_DIR = ROOT / "workflows"
OUTPUT_DIR = ROOT / "output"
COMFYUI_URL = "http://127.0.0.1:8188"
PORT = 8080

STYLES = {
    "anime": ("日系", ", anime style, vibrant colors, cel shading, clean lineart",
              "low quality, worst quality, deformed, 3d, realistic"),
    "ghibli": ("吉卜力", ", Studio Ghibli style, Miyazaki, soft painterly, warm lighting",
              "low quality, photorealistic, 3d render, dark, gloomy"),
    "donghua": ("国漫", ", Chinese donghua style, ink wash aesthetic, elegant, gufeng",
              "low quality, japanese anime style, western artstyle, 3d"),
    "flat": ("平涂简笔", ", simple anime, flat colors, clean black outlines, cel shading, 2D animation, no gradient, solid color fills",
             "complex shading, gradient, realistic, 3d, detailed background, blurry, bad anatomy"),
}
VOICES = {"xiaoxiao": "活泼女声", "yunxi": "少年男声", "xiaoyi": "温柔女声",
          "yunyang": "新闻男声", "xiaobei": "可爱女声"}
RATIOS = {"9:16": (576, 1024), "16:9": (1024, 576), "1:1": (640, 640)}

_pipeline_status = {}
_pipeline_lock = threading.Lock()


def translate(text):
    if not re.search(r'[一-鿿]', text):
        return text
    try:
        from translate import Translator
        return Translator(to_lang="en", from_lang="zh").translate(text)
    except Exception:
        return text


def do_generate(prompt, negative, seed, steps, cfg, width, height,
                style="anime", model=None, char_ref=None):
    """Generate a single image. If char_ref is provided, uses char2frame workflow."""
    name, suffix, style_neg = STYLES.get(style, STYLES["anime"])
    full_prompt = prompt + suffix
    final_negative = negative or style_neg

    wf_name = "char2frame" if char_ref else "txt2img"
    data = json.loads((WORKFLOW_DIR / f"{wf_name}.json").read_text("utf-8"))

    if char_ref:
        data["2"]["inputs"]["text"] = full_prompt
        data["3"]["inputs"]["text"] = final_negative
        data["8"]["inputs"]["image"] = char_ref
        data["15"]["inputs"]["seed"] = seed if seed else random.randint(0, 2**63)
        data["15"]["inputs"]["steps"] = int(steps)
        data["15"]["inputs"]["cfg"] = float(cfg)
        data["14"]["inputs"]["width"] = int(width)
        data["14"]["inputs"]["height"] = int(height)
        if model:
            data["1"]["inputs"]["ckpt_name"] = model
    else:
        data["2"]["inputs"]["text"] = full_prompt
        data["3"]["inputs"]["text"] = final_negative
        data["5"]["inputs"]["seed"] = seed if seed else random.randint(0, 2**63)
        data["5"]["inputs"]["steps"] = int(steps)
        data["5"]["inputs"]["cfg"] = float(cfg)
        data["4"]["inputs"]["width"] = int(width)
        data["4"]["inputs"]["height"] = int(height)
        if model:
            data["1"]["inputs"]["ckpt_name"] = model

    return _submit_and_wait(data)


def _submit_and_wait(data):
    body = json.dumps({"prompt": data, "client_id": "webui"}).encode()
    try:
        req = urllib.request.Request(f"{COMFYUI_URL}/api/prompt", data=body)
        resp = json.loads(urllib.request.urlopen(req).read())
    except urllib.error.URLError:
        return None, "无法连接 ComfyUI — 请确认 ComfyUI 已启动"
    if "error" in resp:
        return None, f"错误: {resp['error']}"
    pid = resp["prompt_id"]

    start = time.time()
    while time.time() - start < 300:
        with urllib.request.urlopen(f"{COMFYUI_URL}/api/history/{pid}") as r:
            history = json.loads(r.read())
        if pid in history:
            e = history[pid]
            if e.get("status", {}).get("status_str") == "error":
                m = e["status"].get("messages", [["unknown"]])
                detail = m[-1][1] if len(m[-1]) > 1 else str(m[-1])
                return None, f"生成失败: {detail}"
            if "outputs" in e:
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                saved = []
                for out in e["outputs"].values():
                    for img in out.get("images", []):
                        fn = img["filename"]
                        sf = img.get("subfolder", "")
                        url = f"{COMFYUI_URL}/api/view?filename={fn}&subfolder={sf}&type=output"
                        urllib.request.urlretrieve(url, OUTPUT_DIR / fn)
                        saved.append(fn)
                return saved, None
        time.sleep(2)
    return None, "超时（300秒）"


def run_pipeline_bg(task_id, novel_text, character_map, voice, speed, api_key):
    """Run full pipeline in background thread, updating _pipeline_status.
    character_map: {name: ref_image_filename} — one entry per bound character.
    """
    global _pipeline_status
    try:
        _pipeline_status[task_id] = {"step": "parsing", "msg": "正在解析分镜..."}
        from script_parser.llm_client import parse_novel_to_storyboard, frames_to_prompts
        char_names = list(character_map.keys())
        storyboard = parse_novel_to_storyboard(novel_text, api_key,
                                                character_names=char_names)
        title = storyboard.get("title", "untitled")
        frames = storyboard.get("frames", [])

        _pipeline_status[task_id] = {"step": "tts", "msg": f"生成配音 ({len(frames)} 分镜)...",
                                     "total": len(frames), "current": 0}
        from video.tts import speak
        import subprocess
        tts_dir = OUTPUT_DIR / f"audio_{task_id}"
        tts_dir.mkdir(exist_ok=True)
        sil_path = str(tts_dir / "_silence.wav")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        "anullsrc=r=24000:cl=mono", "-t", "1", sil_path],
                       check=True, capture_output=True)
        frame_audio = []
        for i, f in enumerate(frames):
            dlg = f.get("dialogue")
            if dlg:
                ap = str(tts_dir / f"f{i:03d}.wav")
                dur = speak(dlg, ap, voice=voice, speed=speed)
                frame_audio.append({"audio_path": ap, "duration": dur, "dialogue": dlg})
            else:
                frame_audio.append({"audio_path": sil_path,
                                    "duration": f.get("duration_sec", 3.0),
                                    "dialogue": None})
            _pipeline_status[task_id] = {"step": "tts", "msg": f"配音 {i+1}/{len(frames)}",
                                         "total": len(frames), "current": i+1}

        _pipeline_status[task_id] = {"step": "generate", "msg": f"生成画面 ({len(frames)} 张)...",
                                     "total": len(frames), "current": 0}
        wf = json.loads((WORKFLOW_DIR / "char2frame.json").read_text("utf-8"))
        fps = frames_to_prompts(storyboard)
        frame_images = []
        for i, fp in enumerate(fps):
            _pipeline_status[task_id] = {"step": "generate", "total": len(frames),
                                         "current": i+1, "msg": f"出图 {i+1}/{len(frames)}"}
            fc = fp.get("characters", [])
            ref = next((character_map[c] for c in fc if c in character_map), None)
            if ref is None:
                ref = next(iter(character_map.values()))
            imgs, err = _submit_and_wait(_build_char_wf(wf, fp["prompt"], fp["negative"],
                                                         ref, f"pipe_{task_id}_f{i:03d}"))
            if err:
                _pipeline_status[task_id] = {"step": "error", "msg": f"出图失败: {err}"}
                return
            frame_images.append({"images": imgs or []})

        _pipeline_status[task_id] = {"step": "compose", "msg": "合成 MP4...",
                                     "total": len(frames), "current": len(frames)}
        composite = []
        for fi, fa in zip(frame_images, frame_audio):
            composite.append({"image": str(OUTPUT_DIR / fi["images"][0]),
                              "audio": fa["audio_path"],
                              "subtitle": fa.get("dialogue") or "",
                              "duration": fa["duration"]})
        from video.composer import compose_video
        ts = time.strftime("%Y%m%d_%H%M%S")
        vp = str(OUTPUT_DIR / f"{title}_{ts}.mp4")
        compose_video(composite, vp)
        _pipeline_status[task_id] = {"step": "done", "msg": "完成!",
                                     "video": os.path.basename(vp)}
    except Exception as e:
        import traceback
        _pipeline_status[task_id] = {"step": "error",
                                     "msg": f"管线失败: {e}\n{traceback.format_exc()}"}


def _build_char_wf(wf, prompt, negative, char_ref, prefix):
    wf = json.loads(json.dumps(wf))
    wf["2"]["inputs"]["text"] = prompt
    wf["3"]["inputs"]["text"] = negative
    wf["8"]["inputs"]["image"] = char_ref
    wf["17"]["inputs"]["filename_prefix"] = prefix
    return wf


def upload_image(file_data, filename):
    """Upload image to ComfyUI input directory."""
    b64 = base64.b64encode(file_data).decode()
    body = json.dumps({"image": b64, "filename": filename, "overwrite": True}).encode()
    req = urllib.request.Request(f"{COMFYUI_URL}/api/upload/image", data=body)
    resp = json.loads(urllib.request.urlopen(req).read())
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return filename


# ── HTML ──────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 漫剧工作台</title>
<style>
body { font-family: system-ui; max-width: 800px; margin: 2em auto; padding: 0 1em;
       background: #111; color: #eee; }
h1 { margin-bottom: 0; }
h2 { border-bottom: 1px solid #333; padding-bottom: 4px; margin-top: 2em; }
.tabs { display: flex; gap: 4px; margin: 1em 0; }
.tab { padding: 8px 20px; background: #222; border: 1px solid #444; border-radius: 6px 6px 0 0;
       cursor: pointer; color: #aaa; }
.tab.active { background: #333; color: #fff; border-bottom-color: #333; }
.panel { display: none; }
.panel.active { display: block; }
label { display: block; margin: 10px 0 4px; font-size: 14px; color: #aaa; }
textarea, input, select { width: 100%; box-sizing: border-box; padding: 8px; margin: 2px 0;
    background: #1a1a1a; color: #eee; border: 1px solid #444; border-radius: 4px; font-size: 14px; }
textarea { height: 100px; resize: vertical; }
.row { display: flex; gap: 8px; flex-wrap: wrap; }
.row > div { flex: 1; min-width: 100px; }
button { padding: 10px 32px; cursor: pointer; background: #3a8; color: #fff; border: none;
         border-radius: 4px; font-size: 1em; margin: 10px 0; }
button:hover { background: #4b9; }
button.purple { background: #6a3fa0; } button.purple:hover { background: #8b5fc0; }
img { max-width: 100%; margin-top: 1em; border-radius: 4px; }
.error { color: #f99; padding: 1em; background: #411; border-radius: 4px; margin-top: 1em; }
.success { color: #9f9; padding: 1em; background: #141; border-radius: 4px; margin-top: 1em; }
.card { border: 1px solid #333; padding: 12px; margin: 8px 0; border-radius: 4px; background: #1a1a1a; }
.card h3 { margin-top: 0; }
.progress { padding: 8px 16px; background: #223; border-radius: 4px; margin: 8px 0; }
.progress .bar { height: 6px; background: #333; border-radius: 3px; margin-top: 6px; overflow: hidden; }
.progress .bar div { height: 100%; background: #3a8; border-radius: 3px; transition: width 0.5s; }
.file-upload { border: 2px dashed #555; padding: 20px; text-align: center; border-radius: 8px;
               cursor: pointer; margin: 8px 0; }
.file-upload:hover { border-color: #3a8; }
.file-upload.has-file { border-style: solid; border-color: #3a8; }
a { color: #3a8; }
video { max-width: 100%; margin-top: 1em; border-radius: 4px; }
</style>
</head>
<body>
<h1>AI 漫剧工作台</h1>
<a href="/history" style="font-size:14px;color:#6a3fa0">📁 历史画廊</a>

<div class="tabs">
  <div class="tab active" onclick="switchTab(0)">🎨 基础生成</div>
  <div class="tab" onclick="switchTab(1)">👤 角色锚定</div>
  <div class="tab" onclick="switchTab(2)">🎬 小说→MP4</div>
</div>

<!-- Panel 0: Basic Generate -->
<div class="panel active" id="panel0">
  <form method="post" action="/generate" enctype="multipart/form-data">
    <label>正向提示词</label>
    <textarea name="prompt" placeholder="描述你想要的画面..."></textarea>
    <label>负向提示词 （留空使用风格默认）</label>
    <textarea name="negative">__NEG__</textarea>
    <div class="row">
      <div><label>风格</label><select name="style">__STYLE_OPTIONS__</select></div>
      <div><label>比例</label><select name="ratio">
        <option value="">自定义</option><option value="9:16">9:16</option>
        <option value="16:9">16:9</option><option value="1:1">1:1</option>
      </select></div>
      <div><label>Steps</label><input name="steps" value="20" type="number" min="1" max="100"></div>
      <div><label>CFG</label><input name="cfg" value="8" step="0.5" type="number"></div>
      <div><label>Width</label><input name="width" value="512" type="number"></div>
      <div><label>Height</label><input name="height" value="512" type="number"></div>
    </div>
    <button type="submit">生成</button>
  </form>
</div>

<!-- Panel 1: Character Mode -->
<div class="panel" id="panel1">
  <form method="post" action="/generate-char" enctype="multipart/form-data">
    <label>角色定妆照</label>
    <div class="file-upload" id="char-drop" onclick="document.getElementById('char-file').click()">
      <span id="char-drop-text">点击上传角色定妆照 (PNG/JPG)</span>
    </div>
    <input type="file" id="char-file" name="char_file" accept="image/*"
           style="display:none" onchange="showCharPreview(this)">
    <img id="char-preview" style="display:none;max-height:150px;margin:8px 0">

    <label>角色名字 （如: 洛溪）</label>
    <input name="char_name" placeholder="角色在书中的名字">

    <label>场景 / 动作描述</label>
    <textarea name="prompt" placeholder="坐在长椅上看书，樱花飘落，午后阳光..."></textarea>

    <label>负向提示词</label>
    <textarea name="negative">complex shading, gradient, realistic, 3d, blurry, bad anatomy, watermark</textarea>

    <div class="row">
      <div><label>风格</label><select name="style">__STYLE_OPTIONS__</select></div>
      <div><label>比例</label><select name="ratio">
        <option value="9:16" selected>9:16 竖屏</option>
        <option value="16:9">16:9</option><option value="1:1">1:1</option>
      </select></div>
      <div><label>Steps</label><input name="steps" value="20" type="number"></div>
      <div><label>CFG</label><input name="cfg" value="8" step="0.5" type="number"></div>
    </div>
    <button type="submit">生成此分镜</button>
  </form>
</div>

<!-- Panel 2: Pipeline -->
<div class="panel" id="panel2">
  <form onsubmit="startPipeline(event)" enctype="multipart/form-data">
    <label>角色绑定</label>
    <div id="char-entries">
      <div class="char-entry card" style="margin-bottom:8px">
        <div style="display:flex;gap:8px;align-items:end;flex-wrap:wrap">
          <div style="flex:1;min-width:150px">
            <label style="margin-top:0">定妆照</label>
            <div class="file-upload" onclick="this.parentElement.querySelector('input[type=file]').click()" style="padding:12px">
              <span class="char-drop-text">点击上传</span>
            </div>
            <input type="file" name="char_file_0" accept="image/*" style="display:none"
                   onchange="charFileChanged(this)">
            <img class="char-preview" style="display:none;max-height:100px;margin-top:4px">
          </div>
          <div style="flex:1;min-width:120px">
            <label style="margin-top:0">角色名字</label>
            <input name="char_name_0" placeholder="对应书中角色名">
          </div>
          <button type="button" class="char-remove" onclick="removeChar(this)"
                  style="background:#a33;padding:4px 10px;font-size:12px;border-radius:4px;color:#fff;border:none;cursor:pointer;margin-bottom:2px">x</button>
        </div>
      </div>
    </div>
    <button type="button" onclick="addChar()" style="background:#444;font-size:12px;padding:4px 14px;margin-bottom:10px">+ 添加角色</button>

    <label>小说段落</label>
    <textarea id="pipe-novel" name="novel_text"
              placeholder="粘贴小说段落 （200-2000字）..."></textarea>
    <label>或上传小说文件: <input type="file" accept=".txt" onchange="loadNovelFile(this)"></label>

    <div class="row">
      <div><label>配音声线</label><select id="pipe-voice">__VOICE_OPTIONS__</select></div>
      <div><label>语速</label><select id="pipe-speed">
        <option value="0.9">0.9x 慢速</option><option value="1.1" selected>1.1x 正常</option>
        <option value="1.3">1.3x 快速</option>
      </select></div>
      <div><label>API Key （或用环境变量 DEEPSEEK_API_KEY）</label>
        <input id="pipe-apikey" placeholder="留空使用环境变量"></div>
    </div>
    <button type="submit" class="purple" id="pipe-btn" style="font-size:1.1em;padding:14px 48px">
      ▶ 开始生成漫剧
    </button>
  </form>
  <div id="pipe-progress"></div>
</div>

__RESULT__

<script>
function switchTab(n) {
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active', i===n));
  document.querySelectorAll('.panel').forEach((p,i) => p.classList.toggle('active', i===n));
}
function showCharPreview(input) {
  const f = input.files[0]; if (!f) return;
  document.getElementById('char-drop-text').textContent = f.name;
  document.getElementById('char-drop').classList.add('has-file');
  const r = new FileReader();
  r.onload = e => { const p = document.getElementById('char-preview');
                    p.src = e.target.result; p.style.display = 'block'; };
  r.readAsDataURL(f);
}
function showCharPreview(input) {
  const f = input.files[0]; if (!f) return;
  document.getElementById('char-drop-text').textContent = f.name;
  document.getElementById('char-drop').classList.add('has-file');
  const r = new FileReader();
  r.onload = e => { const p = document.getElementById('char-preview');
                    p.src = e.target.result; p.style.display = 'block'; };
  r.readAsDataURL(f);
}
let _charIdx = 1;
function addChar() {
  const container = document.getElementById('char-entries');
  const t = container.querySelector('.char-entry').cloneNode(true);
  const i = _charIdx++;
  t.querySelector('input[type=file]').name = 'char_file_' + i;
  t.querySelector('input[type=file]').value = '';
  t.querySelector('input[name^="char_name"]').name = 'char_name_' + i;
  t.querySelector('input[name^="char_name"]').value = '';
  t.querySelector('.char-drop-text').textContent = '点击上传';
  t.querySelector('.char-preview').style.display = 'none';
  t.querySelector('.file-upload').classList.remove('has-file');
  container.appendChild(t);
}
function removeChar(btn) {
  const entries = document.querySelectorAll('#char-entries .char-entry');
  if (entries.length <= 1) { return; }
  btn.closest('.char-entry').remove();
}
function charFileChanged(input) {
  const f = input.files[0]; if (!f) return;
  const entry = input.closest('.char-entry');
  entry.querySelector('.char-drop-text').textContent = f.name;
  entry.querySelector('.file-upload').classList.add('has-file');
  const r = new FileReader();
  r.onload = e => { const p = entry.querySelector('.char-preview');
                    p.src = e.target.result; p.style.display = 'block'; };
  r.readAsDataURL(f);
}
function loadNovelFile(input) {
  const f = input.files[0]; if (!f) return;
  const r = new FileReader();
  r.onload = e => document.getElementById('pipe-novel').value = e.target.result;
  r.readAsText(f);
}

async function startPipeline(e) {
  e.preventDefault();
  const entries = document.querySelectorAll('#char-entries .char-entry');
  const chars = [];
  for (const entry of entries) {
    const fi = entry.querySelector('input[type=file]');
    const ni = entry.querySelector('input[name^="char_name"]');
    if (fi.files[0] && ni.value.trim()) {
      chars.push({file: fi.files[0], name: ni.value.trim()});
    }
  }
  if (chars.length === 0) { alert('请至少上传一个角色定妆照并填写名字'); return; }
  const novelText = document.getElementById('pipe-novel').value.trim();
  if (!novelText) { alert('请输入小说段落'); return; }

  const form = new FormData();
  chars.forEach((c, i) => {
    form.append('char_file_' + i, c.file);
    form.append('char_name_' + i, c.name);
  });
  form.append('char_count', chars.length);
  form.append('novel_text', novelText);
  form.append('voice', document.getElementById('pipe-voice').value);
  form.append('speed', document.getElementById('pipe-speed').value);
  form.append('api_key', document.getElementById('pipe-apikey').value);

  document.getElementById('pipe-btn').disabled = true;
  document.getElementById('pipe-btn').textContent = '提交中...';

  const resp = await fetch('/start-pipeline', {method:'POST', body: form});
  const data = await resp.json();
  if (data.error) {
    document.getElementById('pipe-progress').innerHTML =
      '<div class="error">'+data.error+'</div>';
    document.getElementById('pipe-btn').disabled = false;
    document.getElementById('pipe-btn').textContent = '▶ 开始生成漫剧';
    return;
  }
  pollProgress(data.task_id);
}

async function pollProgress(taskId) {
  const div = document.getElementById('pipe-progress');
  const btn = document.getElementById('pipe-btn');
  while (true) {
    const resp = await fetch('/pipeline-status?task_id='+taskId);
    const s = await resp.json();
    let pct = s.total ? Math.round((s.current||0)*100/s.total) : 0;
    div.innerHTML = '<div class="progress"><strong>'+s.step+'</strong>: '+s.msg+
      (s.total ? ' ('+(s.current||0)+'/'+s.total+')' : '')+
      (s.total ? '<div class="bar"><div style="width:'+pct+'%"></div></div>' : '')+
      '</div>';
    if (s.step === 'done') {
      div.innerHTML += '<div class="success">生成完成! '+
        '<a href="/output/'+s.video+'" download>下载 MP4</a> | '+
        '<a href="/output/'+s.video+'" target="_blank">在线播放</a></div>';
      btn.disabled = false;
      btn.textContent = '▶ 开始生成漫剧';
      return;
    }
    if (s.step === 'error') {
      div.innerHTML += '<div class="error">'+s.msg+'</div>';
      btn.disabled = false;
      btn.textContent = '▶ 开始生成漫剧';
      return;
    }
    await new Promise(r => setTimeout(r, 2000));
  }
}
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path == "/":
                self._page()
            elif self.path == "/history":
                self._history()
            elif self.path.startswith("/output/"):
                self._file()
            elif self.path.startswith("/pipeline-status"):
                self._pipe_status()
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_POST(self):
        try:
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" in content_type:
                self._handle_multipart()
            else:
                self._handle_post()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            try:
                self._page(f'<div class="error">错误: {e}</div>')
            except Exception:
                pass

    def _parse_multipart(self):
        """Parse multipart/form-data, return dict of {field_name: (filename, data)}."""
        content_type = self.headers.get("Content-Type", "")
        boundary = content_type.split("boundary=")[1].strip()
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        parts = raw.split(b"--" + boundary.encode())
        result = {}
        for part in parts:
            if b"Content-Disposition" not in part:
                continue
            header_end = part.find(b"\r\n\r\n")
            if header_end == -1:
                continue
            header = part[:header_end].decode(errors="replace")
            body = part[header_end + 4:]
            if body.endswith(b"\r\n"):
                body = body[:-2]
            name_match = re.search(r'name="([^"]+)"', header)
            if not name_match:
                continue
            name = name_match.group(1)
            filename_match = re.search(r'filename="([^"]+)"', header)
            if filename_match:
                result[name] = (filename_match.group(1), body)
            else:
                result[name] = (None, body.decode(errors="replace"))
        return result

    def _handle_multipart(self):
        parsed = self._parse_multipart()

        if self.path == "/start-pipeline":
            novel_text = parsed.get("novel_text", (None, ""))[1]
            voice = parsed.get("voice", (None, "xiaoxiao"))[1]
            speed = float(parsed.get("speed", (None, "1.1"))[1])
            api_key = parsed.get("api_key", (None, ""))[1]
            char_count = int(parsed.get("char_count", (None, "0"))[1])

            if not novel_text.strip():
                return self._json({"error": "请输入小说段落"})

            character_map = {}
            for i in range(char_count):
                key_file = f"char_file_{i}"
                key_name = f"char_name_{i}"
                if key_file in parsed and key_name in parsed:
                    char_data = parsed[key_file][1]
                    char_name = parsed[key_name][1].strip()
                    if char_data and char_name:
                        try:
                            fn = upload_image(char_data, f"char_{int(time.time())}_{i}.png")
                            character_map[char_name] = fn
                        except Exception as e:
                            return self._json({"error": f"上传 {char_name} 定妆照失败: {e}"})

            if not character_map:
                return self._json({"error": "请至少上传一个角色定妆照并填写名字"})

            task_id = str(int(time.time() * 1000))
            threading.Thread(target=run_pipeline_bg, daemon=True,
                             args=(task_id, novel_text.strip(), character_map,
                                   voice, speed, api_key or None)).start()
            return self._json({"task_id": task_id})

        elif self.path == "/generate-char":
            char_data = parsed.get("char_file", (None, b""))
            prompt = (parsed.get("prompt", (None, ""))[1] or "").strip()
            negative = (parsed.get("negative", (None, ""))[1] or "")
            char_name = (parsed.get("char_name", (None, ""))[1] or "").strip()
            style = (parsed.get("style", (None, "flat"))[1] or "flat")
            steps = int(parsed.get("steps", (None, "20"))[1] or 20)
            cfg = float(parsed.get("cfg", (None, "8"))[1] or 8)
            ratio = (parsed.get("ratio", (None, "9:16"))[1] or "9:16")
            width, height = RATIOS.get(ratio, (512, 912))

            if not prompt:
                return self._page('<div class="error">请输入场景/动作描述</div>')
            if not char_data[1]:
                return self._page('<div class="error">请上传角色定妆照</div>')

            try:
                fn = upload_image(char_data[1], f"char_{int(time.time())}.png")
            except Exception as e:
                return self._page(f'<div class="error">上传失败: {e}</div>')

            if char_name:
                prompt = f"{char_name}, {prompt}"

            saved, err = do_generate(prompt, negative, None, steps, cfg, width, height,
                                     style=style, char_ref=fn)
            if err:
                self._page(f'<div class="error">{err}</div>')
            else:
                imgs = "".join(f'<img src="/output/{s}" alt="{s}">' for s in saved)
                self._page(f'<p class="success">生成完成 ({len(saved)} 张) — 角色: {char_name or "未命名"}</p>{imgs}')

        elif self.path == "/generate":
            prompt = (parsed.get("prompt", (None, ""))[1] or "").strip()
            negative = (parsed.get("negative", (None, ""))[1] or "")
            style = (parsed.get("style", (None, "anime"))[1] or "anime")
            steps = int(parsed.get("steps", (None, "20"))[1] or 20)
            cfg = float(parsed.get("cfg", (None, "8"))[1] or 8)
            width = int(parsed.get("width", (None, "512"))[1] or 512)
            height = int(parsed.get("height", (None, "512"))[1] or 512)
            ratio = parsed.get("ratio", (None, ""))[1]
            if ratio and ratio in RATIOS:
                width, height = RATIOS[ratio]
            if not prompt:
                return self._page('<div class="error">请输入提示词</div>')

            saved, err = do_generate(prompt, negative, None, steps, cfg, width, height, style=style)
            if err:
                self._page(f'<div class="error">{err}</div>')
            else:
                imgs = "".join(f'<img src="/output/{s}" alt="{s}">' for s in saved)
                self._page(f'<p class="success">生成完成 ({len(saved)} 张)</p>{imgs}')

        else:
            self.send_error(404)

    def _handle_post(self):
        """Handle URL-encoded POST (legacy /generate)."""
        if self.path != "/generate":
            return self.send_error(404)

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        params = parse_qs(body)
        prompt = (params.get("prompt", [""])[0] or "").strip()
        if not prompt:
            return self._page('<div class="error">请输入提示词</div>')

        prompt = translate(prompt)
        negative = params.get("negative", [""])[0]
        style = params.get("style", ["anime"])[0]
        seed_val = params.get("seed", [""])[0]
        seed = int(seed_val) if seed_val else None
        steps = int(params.get("steps", ["20"])[0])
        cfg = float(params.get("cfg", ["8"])[0])
        width = int(params.get("width", ["512"])[0])
        height = int(params.get("height", ["512"])[0])
        ratio = params.get("ratio", [""])[0]
        if ratio and ratio in RATIOS:
            width, height = RATIOS[ratio]

        saved, err = do_generate(prompt, negative, seed, steps, cfg, width, height,
                                 style=style)
        if err:
            self._page(f'<div class="error">{err}</div>', negative)
        else:
            imgs = "".join(f'<img src="/output/{s}" alt="{s}">' for s in saved)
            self._page(f'<p class="success">生成完成 ({len(saved)} 张)</p>{imgs}', negative)

    def _page(self, result="", negative=""):
        style_opts = "".join(f'<option value="{k}">{v[0]}</option>'
                             for k, v in STYLES.items())
        voice_opts = "".join(f'<option value="{k}">{v}</option>'
                             for k, v in VOICES.items())
        html = HTML.replace("__NEG__", negative or "")
        html = html.replace("__STYLE_OPTIONS__", style_opts)
        html = html.replace("__VOICE_OPTIONS__", voice_opts)
        html = html.replace("__RESULT__", result)
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _pipe_status(self):
        task_id = self.path.split("task_id=")[-1] if "task_id=" in self.path else ""
        with _pipeline_lock:
            status = _pipeline_status.get(task_id, {"step": "unknown", "msg": "任务不存在"})
        self._json(status)

    def _history(self):
        imgs = sorted(OUTPUT_DIR.glob("*.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm"}
        imgs = [p for p in imgs if p.suffix.lower() in exts]

        cards = []
        for f in imgs[:50]:
            is_vid = f.suffix.lower() in {".mp4", ".webm"}
            tag = (f'<video src="/output/{f.name}" controls style="max-width:100%"></video>'
                   if is_vid else
                   f'<a href="/output/{f.name}" target="_blank">'
                   f'<img src="/output/{f.name}" style="max-width:100%"></a>')
            cards.append(f'<div style="margin-bottom:1.5em">{tag}'
                         f'<div style="font-size:12px;color:#888;margin-top:4px">{f.name}</div>'
                         f'</div>')

        gallery = ("<div style='column-count:2;column-gap:1em'>" + "".join(cards) + "</div>"
                   if cards else "<p>暂无作品</p>")
        html = f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>历史画廊</title>
<style>
body{{font-family:system-ui;max-width:900px;margin:2em auto;padding:0 1em;background:#111;color:#eee}}
a{{color:#3a8}} h1{{display:inline-block;margin-right:1em}}
</style></head>
<body><h1>历史画廊</h1><a href="/" style="font-size:14px">&larr; 返回工作台</a>
<hr>{gallery}</body></html>"""
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _file(self):
        fn = self.path.split("/")[-1]
        # Also serve audio and video files
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir() and d.name.startswith("audio_"):
                candidate = d / fn
                if candidate.exists():
                    path = candidate
                    break
        else:
            path = OUTPUT_DIR / fn
        if not path.exists():
            return self.send_error(404)
        ext = path.suffix.lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif", "mp4": "video/mp4",
                "webm": "video/webm", "wav": "audio/wav"}.get(ext.lstrip("."), "application/octet-stream")
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # suppress noisy logs


def main():
    print(f"AI 漫剧工作台 → http://localhost:{PORT}")
    webbrowser.open(f"http://localhost:{PORT}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
