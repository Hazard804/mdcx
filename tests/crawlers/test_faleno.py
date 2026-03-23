from lxml import etree

from mdcx.crawlers.faleno import get_actor, get_release, get_runtime, get_trailer, get_year


def _build_current_detail_html():
    html = """
    <html>
      <body>
        <div class="box_works01_img">
          <a class="pop_sample" href="https://faleno.jp/top/wp-content/uploads/2026/03/FNS-165_PR.mp4">
            <img src="https://faleno.jp/top/wp-content/uploads/2026/03/FNS-165_1200.jpg?output-quality=60">
          </a>
        </div>
        <div class="box_works01_list clearfix">
          <ul>
            <li class="clearfix"><span>出演女優</span><p>吉高寧々</p></li>
            <li class="clearfix"><span>収録時間</span><p>115分</p></li>
          </ul>
          <ul>
            <li class="clearfix"><span>配信日</span><p>2026/3/19</p></li>
            <li class="clearfix"><span>発売日</span><p>2026/04/09</p></li>
          </ul>
        </div>
      </body>
    </html>
    """
    return etree.fromstring(html, etree.HTMLParser())


def _build_legacy_detail_html():
    html = """
    <html>
      <body>
        <div class="view_timer">
          <div class="btn04">2025/7/24 発売開始</div>
        </div>
      </body>
    </html>
    """
    return etree.fromstring(html, etree.HTMLParser())


def test_get_release_prefers_sale_date_from_detail_list():
    html = _build_current_detail_html()
    release = get_release(html)
    assert get_actor(html) == "吉高寧々"
    assert get_runtime(html) == "115"
    assert get_trailer(html) == "https://faleno.jp/top/wp-content/uploads/2026/03/FNS-165_PR.mp4"
    assert release == "2026-04-09"
    assert get_year(release) == "2026"


def test_get_release_falls_back_to_timer_text():
    html = _build_legacy_detail_html()
    assert get_release(html) == "2025-07-24"
