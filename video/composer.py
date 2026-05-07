"""FFmpeg video composer for AI comic frames."""
import subprocess
import os
from pathlib import Path

FONT_PATH = "msyh.ttc"


def frame_to_segment(image_path, audio_path, subtitle, duration, output_path,
                     font_size=28, font_color="white"):
    """Create a video segment from one frame image + audio + subtitle."""
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
    ]
    if subtitle:
        sub_file = Path(output_path).with_suffix(".sub.txt")
        sub_file.write_text(subtitle, encoding="utf-8")
        drawtext = (
            f"drawtext=textfile='{sub_file.as_posix()}':fontfile={FONT_PATH}:"
            f"fontsize={font_size}:fontcolor={font_color}:"
            f"bordercolor=black:borderw=2:"
            f"x=(w-text_w)/2:y=h-60-(text_h)"
        )
        cmd += ["-vf", drawtext]
    cmd += [
        "-c:v", "libx264", "-preset", "fast",
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def compose_video(frames, output_path, bgm_path=None, font_size=28):
    """Compose frames into one MP4 video.

    frames: list of {image, audio, subtitle, duration}
    """
    tmpdir = Path(output_path).parent / "tmp_segments"
    tmpdir.mkdir(parents=True, exist_ok=True)

    segments = []
    for i, frame in enumerate(frames):
        seg_path = tmpdir / f"seg_{i:03d}.mp4"
        frame_to_segment(
            frame["image"], frame["audio"], frame["subtitle"],
            frame.get("duration", 3.0), str(seg_path),
            font_size=font_size,
        )
        segments.append(seg_path)
        print(f"  Segment {i+1}/{len(frames)} done")

    # Write concat file
    concat_file = tmpdir / "concat.txt"
    with open(concat_file, "w", encoding="utf-8") as cf:
        for s in segments:
            cf.write(f"file '{s.name}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    if bgm_path and os.path.exists(bgm_path):
        final = str(output_path).replace(".mp4", "_bgm.mp4")
        _mix_audio(output_path, bgm_path, final)
        output_path = final

    print(f"Video: {output_path}")
    return output_path


def _mix_audio(video_path, bgm_path, output_path, bgm_volume=0.3):
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(bgm_path),
        "-filter_complex",
        f"[1:a]volume={bgm_volume}[bgm];[0:a][bgm]amix=inputs=2:duration=first",
        "-c:v", "copy",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
