# Full-body sprites (style B)

Put one transparent-background PNG here per character. The office picks it up
automatically (no code change) and shows it standing at the desk, ~128px tall.

File name = the original portrait name, always with a `.png` extension:

| Save as                | Reference image to attach        |
|------------------------|----------------------------------|
| `sec_white_blouse.png` | `assets/sec_white_blouse.png`    |
| `sec_purple_hair.png`  | `assets/sec_purple_hair.png`     |
| `sec_blonde_suit.png`  | `assets/sec_blonde_suit.png`     |
| `sec_dark_glasses.png` | `assets/sec_dark_glasses.jpg`    |
| `sec_double_slit.png`  | `assets/sec_double_slit.png`     |
| `sec_trio_couch.png`   | `assets/sec_trio_couch.jpg`      |

## Prompt (attach the reference image, keep the same face/hair/outfit)

> Full-body 3D render of the same woman as in the reference image, standing
> in a relaxed confident pose, same hairstyle, hair colour and outfit as the
> reference, high-quality stylized 3D character render (Unreal Engine / Pixar
> look), soft studio lighting, front-facing, entire body visible from head to
> shoes, plain solid white background.

Tips:
- Aspect ratio about 1:2 (portrait). The sprite is scaled to a fixed height.
- Remove the background so it is transparent (remove.bg, Photoshop, etc.).
- Midjourney: add the reference with `--cref <url>`. Stable Diffusion: use
  IP-Adapter / FaceID with the reference.
- Characters without a file here fall back to `assets/cutout/` and then to the
  cropped portrait.
