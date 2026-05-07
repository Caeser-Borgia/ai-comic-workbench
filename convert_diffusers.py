"""将 Diffusers 格式模型合并为 ComfyUI 单文件 checkpoint."""
import os
import json
import torch
from safetensors.torch import load_file, save_file

SRC = r"C:\Users\ASUS\.cache\modelscope\hub\models\stablediffusionapi\anything-v5"
DST = r"C:\Users\ASUS\ComfyUI\models\checkpoints\anything-v5.safetensors"


def convert():
    print("Loading components...")

    unet = load_file(os.path.join(SRC, "unet", "diffusion_pytorch_model.safetensors"))
    vae = load_file(os.path.join(SRC, "vae", "diffusion_pytorch_model.safetensors"))
    text_encoder = load_file(os.path.join(SRC, "text_encoder", "model.safetensors"))

    checkpoint = {}

    # UNet -> "model.diffusion_model." prefix
    for k, v in unet.items():
        checkpoint[f"model.diffusion_model.{k}"] = v

    # VAE
    for k, v in vae.items():
        if k.startswith("decoder."):
            checkpoint[f"first_stage_model.{k}"] = v
        elif k.startswith("encoder."):
            checkpoint[f"first_stage_model.{k}"] = v
        else:
            checkpoint[f"first_stage_model.{k}"] = v

    # Text encoder -> "cond_stage_model.transformer."
    for k, v in text_encoder.items():
        checkpoint[f"cond_stage_model.transformer.{k}"] = v

    print(f"Saving checkpoint ({len(checkpoint)} keys)...")
    save_file(checkpoint, DST)

    size_mb = os.path.getsize(DST) / 1024**2
    print(f"Done: {DST} ({size_mb:.0f} MB)")


if __name__ == "__main__":
    convert()
