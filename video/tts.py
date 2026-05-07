"""EdgeTTS wrapper for AI comic voiceover."""

import asyncio
import re

VOICES = {
    'xiaoxiao': 'zh-CN-XiaoxiaoNeural',
    'yunxi': 'zh-CN-YunxiNeural',
    'xiaoyi': 'zh-CN-XiaoyiNeural',
    'yunyang': 'zh-CN-YunyangNeural',
    'xiaobei': 'zh-CN-XiaobeiNeural',
}


async def text_to_speech(text, output_path, voice='xiaoxiao', speed=1.0):
    import edge_tts
    voice_name = VOICES.get(voice, voice)
    rate = f"{'+' if speed >= 1.0 else ''}{int((speed - 1) * 100)}%"
    communicate = edge_tts.Communicate(text, voice_name, rate=rate)
    await communicate.save(output_path)
    proc = await asyncio.create_subprocess_exec(
        'ffmpeg', '-i', str(output_path), '-f', 'null', '-',
        stderr=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
    )
    _, stderr = await proc.communicate()
    match = re.search(r'Duration: (\d+):(\d+):(\d+)\.(\d+)',
                      stderr.decode(errors='replace'))
    if match:
        h, m, s, ms = map(int, match.groups())
        return h * 3600 + m * 60 + s + ms / 100.0
    return 3.0


def speak(text, output_path, voice='xiaoxiao', speed=1.0):
    return asyncio.run(text_to_speech(text, output_path, voice, speed))
