# AI 动态漫工具链

将动漫图片生成器改造为一套 AI 动态漫生产工具链，产出竖屏 9:16 动态漫剧，适配抖音/快手。

## 完整管线

```
小说文本输入
    ↓
① 剧本与分镜解析（LLM 驱动） → 角色/场景/对话拆分
    ↓
② 角色/场景资产生成 → IP-Adapter + LoRA 保持画风一致
    ↓
③ 分镜图像生成 → 扁平简笔画风格
    ↓
④ 动画+音频合成 → AnimateDiff + EdgeTTS + 字幕
    ↓
⑤ 视频导出 → MP4
```

## 当前命令行用法

```bash
# 基础生成（中文自动翻译）
python generate.py "一个校服少女站在樱花树下" --ratio 9:16 --style anime

# 批量生成
python generate.py --batch prompts.txt --ratio 9:16

# 多变体（同一 prompt 出 4 张不同种子）
python generate.py "角色概念设计" --count 4

# 不自动翻译
python generate.py "girl with black hair" --no-translate

# 启动 WebUI
python webui.py
```

## 风格关键词

- 扁平卡通，国漫/二次元动态漫
- 简约线稿，低饱和度，平涂上色
- 9:16 竖屏，对话框叙事
- 现代校园/都市，写实向二次元人物

## 关键约定

- 加功能/改代码/下载前必须先问用户
- 中文 prompt 自动翻译成英文
- 默认模型: anything-v5, 采样器: DPM++ 2M Karras, 步数: 28, CFG: 7.5

## 文件结构

```
D:\project\
├── generate.py          # CLI 入口
├── webui.py             # Web 界面
├── comic_start.bat      # 一键启动
├── workflows/txt2img.json
├── characters/templates.json   # (待建) 角色预设库
├── scenes/templates.json       # (待建) 场景预设库
├── script_parser/              # (待建) LLM 剧本解析
├── pipeline/                   # (待建) 全自动管线
└── video/                      # (待建) 视频合成
```
