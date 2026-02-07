import re

# https://www.compart.com/en/unicode/plane/U+0000
# 暂不考虑扩展假名
KANA = re.compile(r"[\u3040-\u30FF]")
CJK = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\u3040-\u30FF\uAC00-\uD7AF]")
EN_LETTER = re.compile(r"[A-Za-z]")
EN_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
LANG_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\u3040-\u30FF\uAC00-\uD7AF]")

# 仅包含英文字母, 数字, 常用标点符号和空格
MAYBE_EN = re.compile(r"^[a-zA-Z0-9\s.,;:!?()\-\"'`~@#$%^&*+=_/\\|<>]+$")


def is_japanese(s: str) -> bool:
    return bool(KANA.search(s))


def is_english(s: str) -> bool:
    return bool(MAYBE_EN.match(s))


def is_probably_english_for_translation(s: str) -> bool:
    text = s.strip()
    if not text:
        return False
    if is_japanese(text):
        return False

    english_letters = len(EN_LETTER.findall(text))
    if english_letters == 0:
        return False

    cjk_letters = len(CJK.findall(text))
    total_script_letters = english_letters + cjk_letters
    english_letter_ratio = english_letters / total_script_letters if total_script_letters else 0.0

    if cjk_letters > 0 and english_letter_ratio < 0.85:
        return False

    english_words = EN_WORD.findall(text)
    token_count = len(LANG_TOKEN.findall(text))
    english_word_ratio = len(english_words) / token_count if token_count else 0.0

    score = 0
    if english_letter_ratio >= 0.6:
        score += 1
    if english_word_ratio >= 0.5:
        score += 1
    if english_letters >= 20 or len(english_words) >= 5:
        score += 1
    if len(text) <= 80 and english_letters >= 3 and len(english_words) >= 1:
        score += 1

    return score >= 2
