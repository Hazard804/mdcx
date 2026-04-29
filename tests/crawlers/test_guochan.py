from mdcx.crawlers.guochan import get_extra_info, get_number_list


def test_get_number_list_extracts_guochan_number_candidates():
    numbers, titles = get_number_list(
        "91CM-081",
        file_path="91CM-081.田恬.李琼.继母与女儿.三.爸爸不在家先上妹妹再玩弄母亲.果冻传媒.mp4",
    )

    assert numbers[:3] == ["91CM081", "91CM-081", "91CM 081"]
    assert "爸爸不在家先上妹妹再玩弄母亲" in titles


def test_get_number_list_handles_traditional_chinese_filename():
    numbers, titles = get_number_list(
        "mini06",
        file_path="mini06.全裸家政.只為弟弟的學費打工.被玩弄的淫亂家政小妹.mini傳媒.ts",
    )

    assert numbers == ["MINI06", "MINI-06", "MINI006", "MINI-006"]
    assert "只為弟弟的學費打工" in titles


def test_get_extra_info_matches_guochan_actor_and_tag():
    title = "HongKongDoll 玩偶姐姐 夏日回忆 麻豆传媒"

    assert get_extra_info(title, "", "actor") == "HongKongDoll,玩偶姐姐"
    assert get_extra_info(title, "", "tag") == "麻豆传媒,HongKongDoll,麻豆"
