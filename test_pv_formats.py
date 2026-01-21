import re

# 测试三种临时链接格式
test_cases = [
    {
        "name": "格式1: 字母+数字+质量标记",
        "filename": "asfb00192_mhb_w.mp4",
        "expected_cid": "asfb00192",
    },
    {
        "name": "格式2: 数字+字母+数字+后缀",
        "filename": "1start4814k.mp4",
        "expected_cid": "1start4814k",
    },
    {
        "name": "格式3: 带下划线的复杂ID+质量标记",
        "filename": "n_707agvn001_dmb_w.mp4",
        "expected_cid": "n_707agvn001",
    },
]

print("=" * 80)
print("DMM 临时链接格式识别测试")
print("=" * 80)

for test in test_cases:
    print(f"\n{test['name']}")
    print(f"文件名: {test['filename']}")

    filename_base = test["filename"].replace(".mp4", "")
    # 去掉质量标记后缀
    cid = re.sub(r"(_[a-z]+b?_w)?$", "", filename_base)

    # 检查是否包含字母和数字
    has_letter = re.search(r"[a-z]", cid, re.IGNORECASE)
    has_digit = re.search(r"\d", cid)
    can_recognize = bool(has_letter and has_digit)

    print(f"提取的 cid: {cid}")
    print(f"期望的 cid: {test['expected_cid']}")
    print(f"CID 匹配: {'✅' if cid == test['expected_cid'] else '❌'}")
    print(f"包含字母: {'✅' if has_letter else '❌'} ({has_letter.group() if has_letter else 'N/A'})")
    print(f"包含数字: {'✅' if has_digit else '❌'} ({has_digit.group() if has_digit else 'N/A'})")
    print(f"能否识别: {'✅ 可以' if can_recognize else '❌ 不能'}")

    if can_recognize:
        prefix = cid[0]
        three_char = cid[:3]
        converted_url = (
            f"https://cc3001.dmm.co.jp/litevideo/freepv/{prefix}/{three_char}/{cid}/{filename_base}.mp4"
        )
        print(f"转换后的URL: {converted_url}")

print("\n" + "=" * 80)
print("总结: 所有格式均可正常识别 ✅" if all(
    re.search(r"[a-z]", re.sub(r"(_[a-z]+b?_w)?$", "", tc["filename"].replace(".mp4", "")), re.IGNORECASE)
    and re.search(r"\d", re.sub(r"(_[a-z]+b?_w)?$", "", tc["filename"].replace(".mp4", "")))
    for tc in test_cases
) else "总结: 部分格式无法识别 ❌")
print("=" * 80)
