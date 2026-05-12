import re

from ...utils import nfd2c


def cleanup_rendered_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", str(text or ""))
    return text.strip()


def sanitize_name(text: str, *, allow_path_separator: bool) -> str:
    text = cleanup_rendered_text(text)
    if allow_path_separator:
        text = re.sub(r'[\\:*?"<>|\r\n]+', "", text).strip(" /")
        text = re.sub(r"/{2,}", "/", text)
        text = text.replace(" /", "/").replace("/ ", "/")
    else:
        text = re.sub(r'[\\/:*?"<>|\r\n]+', "", text).strip()
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.replace("--", "-").strip("- .")
    return nfd2c(text)
