AI漫剧工作台 — 输入小说文本+角色定妆照，全自动生成竖屏漫剧视频。

  一条管线走到底：粘贴小说段落 →
  LLM智能剪辑（自动跳过平淡叙述，只留冲突/反转/高情绪片段）→ 英文分镜prompt →
  ComfyUI批量出图（anything-v5底模+双LoRA线稿平涂+IP-Adapter锁角色外貌+ControlNet
  Canny锁构图）→ EdgeTTS中文配音 → FFmpeg字幕叠加+分镜拼接 → 输出9:16竖屏MP4。

  Web界面三个Tab：基础文生图、单角色定妆照+场景出图、多角色绑定+小说→全自动MP4。纯Pytho
  n单文件HTTP服务，零框架依赖。LLM走DeepSeek
  API（国内可用无需VPN），出图走本地ComfyUI。CLI和WebUI都支持。

  适合做短视频平台的漫剧/动态漫内容，一条龙从文本到成片
