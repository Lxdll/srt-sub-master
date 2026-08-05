from server.app.chinese import to_simplified_chinese


def test_recognized_chinese_is_normalized_to_simplified():
    assert to_simplified_chinese("寶寶問你什麼軟件，一輩子不會卸載") == (
        "宝宝问你什么软件，一辈子不会卸载"
    )
