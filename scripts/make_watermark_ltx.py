"""生成 LTX 破解水印图标。

与 resources/Img 下已有的 youma/umr/leak/wuma/sub 保持同一套视觉规范：
画布 1000x600 透明、胶囊圆角矩形、白色粗体文字、居中柔和投影。
仅用于产出静态 PNG 资源，不在运行时被程序调用。

用法：
    python scripts/make_watermark_ltx.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CANVAS_SIZE = (1000, 600)
# 与 umr.png 实测几何一致：胶囊 x 62..938、y 84..516，圆角为半高形成全胶囊。
PILL_BOX = (62, 84, 938, 516)
PILL_RADIUS = 216
# LTX 为独立新型破解方式，取用现有五款（橙/红/黄/紫/绿）未占用的深青色相。
PILL_COLOR = (14, 116, 144, 255)
SHADOW_BLUR = 10
SHADOW_ALPHA = 90
TEXT_MAIN = "LTX"
TEXT_SUB = "破解"
FONT_PATH = "C:/Windows/Fonts/msyhbd.ttc"
FONT_MAIN_SIZE = 262
FONT_SUB_SIZE = 104
MAIN_CENTER_Y = 225
SUB_CENTER_Y = 425
MAIN_TEXT_COLOR = (255, 255, 255, 255)
SUB_TEXT_COLOR = (255, 255, 255, 242)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, font, center_y: int, fill):
    """按实际墨迹外框水平/垂直居中，避免不同字形的留白差异导致视觉偏移。"""
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = (CANVAS_SIZE[0] - (right - left)) / 2 - left
    y = center_y - (bottom - top) / 2 - top
    draw.text((x, y), text, font=font, fill=fill)
    return bottom - top


def build_watermark(output_path: Path) -> None:
    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))

    # 投影层：先铺一层半透明黑胶囊再高斯模糊，复刻原图边缘 alpha 约 40 的柔和外扩。
    shadow = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(PILL_BOX, radius=PILL_RADIUS, fill=(0, 0, 0, SHADOW_ALPHA))
    shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    canvas = Image.alpha_composite(canvas, shadow)

    pill = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    ImageDraw.Draw(pill).rounded_rectangle(PILL_BOX, radius=PILL_RADIUS, fill=PILL_COLOR)
    canvas = Image.alpha_composite(canvas, pill)

    text_layer = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)
    # 主副文字整体垂直居中于胶囊中心 y=300，间距压紧以适配胶囊直边区域宽度。
    _draw_centered(draw, TEXT_MAIN, _load_font(FONT_MAIN_SIZE), MAIN_CENTER_Y, MAIN_TEXT_COLOR)
    _draw_centered(draw, TEXT_SUB, _load_font(FONT_SUB_SIZE), SUB_CENTER_Y, SUB_TEXT_COLOR)
    canvas = Image.alpha_composite(canvas, text_layer)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    print(f"saved: {output_path} {canvas.size}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    build_watermark(project_root / "resources" / "Img" / "ltx.png")
