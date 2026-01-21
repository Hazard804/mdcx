#!/usr/bin/env python3
"""
测试预告片链接转换的正则表达式
"""
import re

def convert_trailer_url(trailer_url: str) -> str:
    """
    将 Fanza TV 的预告片链接转换为标准格式
    支持多种临时链接格式
    """
    # 检测是否为临时链接
    if "/pv/" in trailer_url:
        # 从临时链接中提取文件名
        filename_match = re.search(r"/pv/[^/]+/(.+?)(?:\.mp4)?$", trailer_url)
        if filename_match:
            filename_base = filename_match.group(1).replace(".mp4", "")
            # 去掉质量标记后缀（_*b_w 格式，如 _mhb_w, _dmb_w, _sm_w, _dm_w 等）
            cid = re.sub(r"(_[a-z]+b?_w)?$", "", filename_base)
            # 确保提取到的是有效的产品ID（包含字母和数字）
            if re.search(r"[a-z]", cid, re.IGNORECASE) and re.search(r"\d", cid):
                prefix = cid[0]
                three_char = cid[:3]
                # 使用去掉质量标记后的 cid 作为文件夹，保留原始 filename_base
                trailer = (
                    f"https://cc3001.dmm.co.jp/litevideo/freepv/{prefix}/{three_char}/{cid}/{filename_base}.mp4"
                )
                return trailer
    
    return trailer_url


# 测试用例
test_cases = [
    {
        "name": "标准格式：字母+数字+质量标记",
        "input": "https://cc3001.dmm.co.jp/pv/OjcAEBpVCpIeI1m3nJvGC3vRVbVLBGu6lG64-bdtYznLH1xOMvupdveK2Iw-w6/asfb00192_mhb_w.mp4",
        "expected": "https://cc3001.dmm.co.jp/litevideo/freepv/a/asf/asfb00192/asfb00192_mhb_w.mp4",
    },
    {
        "name": "格式：数字+字母+数字+后缀",
        "input": "https://cc3001.dmm.co.jp/pv/OjcAEBpVCpIeI1m3nJvGC3vRVbVLBGu6lG64-bdtYznLH1xOMvupdveK2Iw-w6/1start4814k.mp4",
        "expected": "https://cc3001.dmm.co.jp/litevideo/freepv/1/1st/1start4814k/1start4814k.mp4",
    },
    {
        "name": "格式：带下划线的复杂ID+质量标记",
        "input": "https://cc3001.dmm.co.jp/pv/OjcAEBpVCpIeI1m3nJvGC3vRVbVLBGu6lG64-bdtYznLH1xOMvupdveK2Iw-w6/n_707agvn001_dmb_w.mp4",
        "expected": "https://cc3001.dmm.co.jp/litevideo/freepv/n/n_7/n_707agvn001/n_707agvn001_dmb_w.mp4",
    },
    {
        "name": "已经是标准格式，不需要转换",
        "input": "https://cc3001.dmm.co.jp/litevideo/freepv/d/das/dasd00648/dasd00648_dmb_w.mp4",
        "expected": "https://cc3001.dmm.co.jp/litevideo/freepv/d/das/dasd00648/dasd00648_dmb_w.mp4",
    },
]

print("=" * 100)
print("预告片链接转换正则表达式测试")
print("=" * 100)

passed = 0
failed = 0

for i, test in enumerate(test_cases, 1):
    result = convert_trailer_url(test["input"])
    status = "✓ PASS" if result == test["expected"] else "✗ FAIL"
    
    if result == test["expected"]:
        passed += 1
    else:
        failed += 1
    
    print(f"\n测试 {i}: {test['name']}")
    print(f"输入:   {test['input']}")
    print(f"期望:   {test['expected']}")
    print(f"结果:   {result}")
    print(f"状态:   {status}")

print("\n" + "=" * 100)
print(f"总结: 通过 {passed}/{len(test_cases)} 个测试")
print("=" * 100)
