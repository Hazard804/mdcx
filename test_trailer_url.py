#!/usr/bin/env python3
"""
测试 Fanza TV 预告片链接转换逻辑
"""
import re

def convert_trailer_url(trailer_url: str) -> str:
    """
    将 Fanza TV 的预告片链接转换为标准格式
    支持两种格式：
    1. 临时链接: /pv/{temp_key}/{filename}
    2. 标准链接: /hlsvideo/freepv/...playlist.m3u8
    """
    # 替换 hlsvideo 为 litevideo
    trailer_url = trailer_url.replace("hlsvideo", "litevideo")
    
    # 检测是否为临时链接
    if "/pv/" in trailer_url:
        # 从临时链接中提取文件名
        filename_match = re.search(r"/pv/[^/]+/(.+?)(?:\.mp4)?$", trailer_url)
        if filename_match:
            filename_base = filename_match.group(1).replace(".mp4", "")
            # 从文件名中提取号码部分，例如 dasd00648_mhb_w -> dasd00648
            number_match = re.match(r"([a-z]+\d+)", filename_base)
            if number_match:
                cid = number_match.group(1)
                # 构建标准格式的链接
                prefix = cid[0]  # 第一个字母
                three_char = cid[:3]  # 前三个字符
                trailer = f"https://cc3001.dmm.co.jp/litevideo/freepv/{prefix}/{three_char}/{cid}/{filename_base}.mp4"
                return trailer
        return ""
    else:
        # 原有的标准链接处理逻辑
        cid_match = re.search(r"/([^/]+)/playlist.m3u8", trailer_url)
        if cid_match:
            cid = cid_match.group(1)
            return trailer_url.replace("playlist.m3u8", cid + "_sm_w.mp4")
        return ""


# 测试用例
test_cases = [
    {
        "name": "临时链接 (pv 格式)",
        "input": "https://cc3001.dmm.co.jp/pv/Ti5xIgog7i8WYDsiS_N9aJ2XY57cGfkPWzX5azlBE5PH827Q_UJjtavpbli8tS/dasd00648_mhb_w.mp4",
        "expected": "https://cc3001.dmm.co.jp/litevideo/freepv/d/das/dasd00648/dasd00648_mhb_w.mp4",
    },
    {
        "name": "标准链接 (hlsvideo 格式)",
        "input": "https://cc3001.dmm.co.jp/hlsvideo/freepv/s/ssi/ssis00497/playlist.m3u8",
        "expected": "https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00497/ssis00497_sm_w.mp4",
    },
    {
        "name": "临时链接 - 另一个例子",
        "input": "https://cc3001.dmm.co.jp/pv/someRandomKey123456/test00123_abc_w.mp4",
        "expected": "https://cc3001.dmm.co.jp/litevideo/freepv/t/tes/test00123/test00123_abc_w.mp4",
    },
]

print("=" * 80)
print("Fanza TV 预告片链接转换测试")
print("=" * 80)

for i, test in enumerate(test_cases, 1):
    result = convert_trailer_url(test["input"])
    status = "✓ PASS" if result == test["expected"] else "✗ FAIL"
    print(f"\n测试 {i}: {test['name']}")
    print(f"输入:   {test['input']}")
    print(f"期望:   {test['expected']}")
    print(f"结果:   {result}")
    print(f"状态:   {status}")

print("\n" + "=" * 80)
