import re

test_cases = [
    "asfb00192_mhb_w",
    "1start4814k",
    "n_707agvn001_dmb_w",
]

patterns = [
    r"(_[sd]mb?_w)?$",
    r"_[a-z]mb?_w$",
    r"_[a-z]+mb?_w$",
    r"_[a-z]+b?_w$",
    r"_\w+_w$",
    r"(_\w+_w)?$",
]

for test in test_cases:
    print(f"\nTest: {test}")
    for pattern in patterns:
        result = re.sub(pattern, "", test)
        print(f"  Pattern {pattern!r}: {result}")
