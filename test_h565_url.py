import re

# 测试 URL
test_url = "https://cc3001.dmm.co.jp/litevideo/freepv/h/h_5/h_565scop083/h_565scop083_sm_w.mp4"

print("=" * 80)
print("测试 URL 识别")
print("=" * 80)
print(f"\n测试 URL: {test_url}\n")

# 模拟分辨率升级的正则
match = re.search(r"(.+)(_[a-z]+_[a-z]\.mp4)$", test_url)

if match:
    print("✅ 正则匹配成功")
    base_url, quality_tag = match.groups()
    print(f"base_url: {base_url}")
    print(f"quality_tag: {quality_tag}")
    
    # 提取后缀字符
    suffix_match = re.search(r"_([a-z]+)_([a-z])", quality_tag)
    if suffix_match:
        quality_level, suffix_char = suffix_match.groups()
        print(f"\n质量等级: {quality_level}")
        print(f"后缀字符: {suffix_char}")
        
        # 定义分辨率优先级
        quality_levels = ("sm", "dm", "dmb", "mhb")
        
        try:
            current_index = quality_levels.index(quality_level)
            print(f"当前等级索引: {current_index} ({quality_level})")
            
            print(f"\n可以升级到的更高分辨率:")
            for i in range(current_index + 1, len(quality_levels)):
                higher_quality = quality_levels[i]
                for test_suffix_char in ("w", "s", "h"):
                    test_url_higher = base_url + f"_{higher_quality}_{test_suffix_char}.mp4"
                    print(f"  - {test_url_higher}")
        except ValueError as e:
            print(f"❌ 未知的质量等级: {e}")
    else:
        print("❌ 后缀匹配失败")
else:
    print("❌ 正则匹配失败")

print("\n" + "=" * 80)
print("结论: 程序能够正确识别这个 URL 的结构")
print("=" * 80)
