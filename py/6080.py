# -*- coding: utf-8 -*-
"""
66191999 (6080影视) Spider — 增强版
站点: https://www.66191999.com/
模板: 苹果CMS + mytheme (t01)

修复:
  - 分类页多URL格式尝试 + 多正则兜底解析
  - 详情页5层提取，确保有数据
  - 全链路预编译正则，速度快
"""

import sys
import json
import re
import time
import base64
import threading
from urllib.parse import quote, urlencode

sys.path.append('..')

try:
    from base.spider import Spider
except ImportError:
    import requests as _rq
    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:
        pass

    class Spider:
        def fetch(self, url, headers=None, **kw):
            timeout = kw.pop('timeout', 15)
            r = _rq.get(url, headers=headers, timeout=timeout, verify=False, **kw)
            r.encoding = 'utf-8'
            return r


HOST = "https://www.66191999.com"

UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")
UA2 = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
       "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
UA3 = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

LINE_NAMES = {
    # 6080影视真实线路（按sid对应）
    "1": "夸克云高清", "2": "腾讯云高清", "3": "优酷云4K", "4": "索尼云蓝光",
    "夸克云高清": "夸克云高清", "腾讯云高清": "腾讯云高清",
    "优酷云4K": "优酷云4K", "索尼云蓝光": "索尼云蓝光",
    # from字段标识
    "dyttm3u8": "电影天堂", "dytt": "电影天堂",
    "m3u8": "极速云", "mgtv": "芒果",
    "mjzy": "4K蓝光", "qq": "腾讯", "qiyi": "爱奇艺",
    "youku": "优酷", "bilibili": "B站", "zuidam3u8": "最大资源",
    "ffzy": "非凡资源", "snm3u8": "索尼资源", "wjm3u8": "无尽资源",
    "wolong": "卧龙资源", "xlm3u8": "新浪资源", "tpm3u8": "淘片资源",
    "dbm3u8": "百度资源", "ckm3u8": "酷云资源", "gsm3u8": "光速资源",
    "gjm3u8": "国际资源", "jinyingm3u8": "金鹰资源", "kuyun": "酷播云",
    "okm3u8": "OK资源", "hnyun": "华南云", "baidu": "百度",
}

# ===== 预编译正则 =====
# 视频卡片匹配（多套正则，按优先级尝试）
RE_VOD_PATTERNS = [
    # 模式1: 标准 mytheme — class在前, href在后, data-original
    re.compile(
        r'<a[^>]*class="[^"]*myui-vodlist__thumb[^"]*"[^>]*'
        r'href="(/6080detail/(\d+)\.html)"[^>]*'
        r'(?:title="([^"]*)")?[^>]*'
        r'(?:data-original|src)="([^"]*)"',
        re.I,
    ),
    # 模式2: href在前, class在后
    re.compile(
        r'<a[^>]*href="(/6080detail/(\d+)\.html)"[^>]*'
        r'class="[^"]*myui-vodlist__thumb[^"]*"[^>]*'
        r'(?:title="([^"]*)")?[^>]*'
        r'(?:data-original|src)="([^"]*)"',
        re.I,
    ),
    # 模式3: 宽松匹配 — 只要有 detail 链接和图片
    re.compile(
        r'<a[^>]*href="(/6080detail/(\d+)\.html)"[^>]*'
        r'(?:title="([^"]*)")?[^>]*>'
        r'(?:[^<]*<img[^>]*?(?:data-original|src)="([^"]*)")?',
        re.I,
    ),
]

# 状态/集数提取
RE_REMARK_TEXT = re.compile(r'pic-text[^>]*>([^<]+)</span>', re.I)
RE_PIC_TAG = re.compile(r'pic-tag[^>]*>([^<]+)</span>', re.I)

# 详情页
RE_H1 = re.compile(r'<h1[^>]*>([^<]+)</h1>', re.I)
RE_TITLE_TAG = re.compile(r'<title>([^|<]+)', re.I)
RE_DATA_ORIG = re.compile(r'data-original="([^"]+)"', re.I)
RE_IMG_SRC = re.compile(r'<img[^>]*src="([^"]+)"', re.I)
# 分类/年份/地区 - 从 meta 或 p.data 中提取
RE_TYPE = re.compile(r'分类[：:]\s*<[^>]*>[^<]*<a[^>]*>([^<]+)</a>', re.I)
RE_YEAR = re.compile(r'年份[：:]\s*<[^>]*>[^<]*<a[^>]*>([^<]+)</a>', re.I)
RE_AREA = re.compile(r'地区[：:]\s*<[^>]*>[^<]*<a[^>]*>([^<]+)</a>', re.I)
# 导演/主演 - 从 p.data 中提取（包含多个a标签）
RE_DIRECTOR = re.compile(r'导演[：:]\s*</span>(.*?)</p>', re.I | re.S)
RE_ACTOR = re.compile(r'主演[：:]\s*</span>(.*?)</p>', re.I | re.S)
# 简介 - 从 p.data 或 JS 中提取
RE_CONTENT_BRIEF = re.compile(r'简介[：:]\s*</span>(.*?)<a[^>]*>剧情介绍', re.I | re.S)
RE_CONTENT_JS = re.compile(r"MyTheme\.Layer\.Text\(['\"]剧情简介['\"],\s*['\"](.+?)['\"],", re.I | re.S)
# og meta 兜底
RE_OG_DIRECTOR = re.compile(r'og:video:director"\s+content="([^"]*)"', re.I)
RE_OG_ACTOR = re.compile(r'og:video:actor"\s+content="([^"]*)"', re.I)
RE_META_DESC = re.compile(r'<meta[^>]*name="description"\s+content="([^"]*)"', re.I)

# 播放地址JS变量（多模式）
RE_PLAY_FROM = re.compile(r'vod_play_from["\s:=]+["\']([^"\']+)["\']', re.I)
RE_PLAY_URL = re.compile(r'vod_play_url["\s:=]+["\']([^"\']+)["\']', re.I)
RE_PLAYER_URL = re.compile(r'player_?url["\s:=]+["\']([^"\']+)["\']', re.I)
RE_VIDEO_URL_VAR = re.compile(r'video_?url["\s:=]+["\']([^"\']+)["\']', re.I)
# MacCMS加密变量
RE_MAC_URL = re.compile(r'mac_url["\s:=]+["\']([^"\']+)["\']', re.I)
RE_MAC_FROM = re.compile(r'mac_from["\s:=]+["\']([^"\']+)["\']', re.I)
# 加密/编码
RE_ENCRYPT_DATA = re.compile(r'(?:encrypt|encoded|enc_data|strEncode)["\s:=]+["\']([^"\']+)["\']', re.I)
RE_BASE64_DATA = re.compile(r'["\']([A-Za-z0-9+/]{20,}={0,2})["\']')
# eval 解码后常见格式
RE_EVAL_URL = re.compile(r'unescape\(["\']([^"\']+)["\']\)', re.I)
# 播放列表通用
RE_PLAY_LIST_A = re.compile(
    r'<ul[^>]*class="[^"]*playlist[^"]*"[^>]*>(.*?)</ul>', re.I | re.S)
RE_PLAY_ITEM = re.compile(
    r'<a[^>]*href="([^"]*play[^"]*\.html[^"]*)"[^>]*>([^<]+)</a>', re.I)

# 播放列表（6080影视真实格式：/6080play/{vid}/{sid}/{nid}.html）
RE_PLAY_LINKS = re.compile(
    r'<a[^>]*href="(/6080play/(\d+)/(\d+)/(\d+)\.html)"[^>]*>([^<]+)</a>', re.I)
RE_SID = re.compile(r'data-sid="(\d+)"', re.I)
RE_FROM = re.compile(r'data-from="([^"]*)"', re.I)
# 线路tab名称（真实线路从tab提取）
RE_PLAY_TABS = re.compile(
    r'<a[^>]*href="#playlist(\d+)"[^>]*data-toggle="tab"[^>]*>([^<]+)</a>', re.I)
# 播放页 player_aaaa JSON（含直链）
RE_PLAYER_AAAA = re.compile(
    r'player_aaaa\s*=\s*(\{.*?\})\s*</script>', re.I | re.S)
RE_PLAYER_URL_JSON = re.compile(
    r'"url"\s*:\s*"([^"]+)"', re.I)
RE_PLAYER_FROM_JSON = re.compile(
    r'"from"\s*:\s*"([^"]+)"', re.I)
RE_PLAYER_ENCRYPT = re.compile(
    r'"encrypt"\s*:\s*(\d+)', re.I)

# 直链提取
RE_M3U8 = re.compile(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', re.I)
RE_MP4 = re.compile(r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)', re.I)
RE_URL_VAR = re.compile(
    r'(?:url|src)\s*[:=]\s*["\']([^"\']+\.(?:m3u8|mp4|flv)[^"\']*)["\']', re.I)

# iframe
RE_IFRAME = re.compile(r'<iframe[^>]*src="([^"]+)"', re.I)

# 分页
RE_PAGE_END = re.compile(r'/vodshow/id/\d+-page-(\d+)\.html[^>]*>[^<]*尾页', re.I)
RE_PAGE_TOTAL = re.compile(r'共(\d+)页', re.I)
RE_TOTAL_NUM = re.compile(r'共\s*(\d+)\s*条', re.I)

# ===== 分类 =====
CLASSES = [
    {"type_name": "电影", "type_id": "1"},
    {"type_name": "电视剧", "type_id": "2"},
    {"type_name": "综艺片", "type_id": "3"},
    {"type_name": "动漫", "type_id": "4"},
    {"type_name": "短剧", "type_id": "24"},
]

CLASS_TYPES = {
    "1": [
        {"n": "全部", "v": ""},
        {"n": "动作", "v": "动作"}, {"n": "喜剧", "v": "喜剧"},
        {"n": "爱情", "v": "爱情"}, {"n": "科幻", "v": "科幻"},
        {"n": "剧情", "v": "剧情"}, {"n": "战争", "v": "战争"},
        {"n": "恐怖", "v": "恐怖"}, {"n": "动画", "v": "动画"},
        {"n": "纪录", "v": "纪录"}, {"n": "悬疑", "v": "悬疑"},
    ],
    "2": [
        {"n": "全部", "v": ""},
        {"n": "国产", "v": "国产"}, {"n": "香港", "v": "香港"},
        {"n": "韩国", "v": "韩国"}, {"n": "欧美", "v": "欧美"},
        {"n": "台湾", "v": "台湾"}, {"n": "日本", "v": "日本"},
        {"n": "泰国", "v": "泰国"}, {"n": "古装", "v": "古装"},
        {"n": "都市", "v": "都市"}, {"n": "言情", "v": "言情"},
    ],
    "3": [
        {"n": "全部", "v": ""},
        {"n": "大陆", "v": "大陆"}, {"n": "日韩", "v": "日韩"},
        {"n": "港台", "v": "港台"}, {"n": "欧美", "v": "欧美"},
        {"n": "真人秀", "v": "真人秀"},
    ],
    "4": [
        {"n": "全部", "v": ""},
        {"n": "国产", "v": "国产"}, {"n": "日本", "v": "日本"},
        {"n": "港台", "v": "港台"}, {"n": "欧美", "v": "欧美"},
        {"n": "热血", "v": "热血"}, {"n": "搞笑", "v": "搞笑"},
    ],
    "24": [
        {"n": "全部", "v": ""},
        {"n": "穿越重生", "v": "穿越"}, {"n": "反转爽剧", "v": "反转"},
        {"n": "言情总裁", "v": "言情"}, {"n": "现代都市", "v": "都市"},
        {"n": "古装仙侠", "v": "古装"}, {"n": "悬疑烧脑", "v": "悬疑"},
    ],
}

YEAR_FILTER = {"key": "year", "name": "年份", "value": [
    {"n": "全部", "v": ""},
    {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
    {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"},
    {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"},
    {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"},
    {"n": "更早", "v": "更早"},
]}

AREA_FILTER = {"key": "area", "name": "地区", "value": [
    {"n": "全部", "v": ""},
    {"n": "内地", "v": "内地"}, {"n": "香港", "v": "香港"},
    {"n": "台湾", "v": "台湾"}, {"n": "日本", "v": "日本"},
    {"n": "韩国", "v": "韩国"}, {"n": "美国", "v": "美国"},
    {"n": "英国", "v": "英国"}, {"n": "泰国", "v": "泰国"},
]}

BY_FILTER = {"key": "by", "name": "排序", "value": [
    {"n": "最新", "v": "time"},
    {"n": "最热", "v": "hits"},
    {"n": "评分", "v": "score"},
]}

FILTERS = {}
for c in CLASSES:
    tid = c["type_id"]
    FILTERS[tid] = [
        {"key": "class", "name": "类型", "value": CLASS_TYPES.get(tid, [{"n": "全部", "v": ""}])},
        AREA_FILTER,
        YEAR_FILTER,
        BY_FILTER,
    ]


class Spider(Spider):

    def getName(self):
        return "66191999影视"

    def init(self, extend=""):
        if isinstance(extend, list):
            self.extend = ""
        else:
            self.extend = extend or ""

        self.header = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        # 用session保持cookie，提高Cloudflare通过率
        try:
            import requests
            self._session = requests.Session()
            self._session.verify = False
        except Exception:
            self._session = None

        self._home_cache = None
        self._home_time = 0
        self._cat_cache = {}
        self._cat_lock = threading.Lock()
        self._detail_cache = {}
        self._detail_lock = threading.Lock()
        # 播放地址缓存（详情页预解析时存）
        self._play_cache = {}
        self._play_lock = threading.Lock()

    # ===== 网络 =====
    def _get(self, url, timeout=10, referer=None):
        """带重试和Session的请求，referer为None则用默认"""
        hdr = dict(self.header)
        if referer:
            hdr["Referer"] = referer

        uas = [hdr["User-Agent"], UA2, UA3]

        for attempt in range(4):  # 最多4次尝试（3个UA+1次额外重试）
            try:
                # 轮换UA
                hdr["User-Agent"] = uas[attempt % len(uas)]

                if self._session:
                    rsp = self._session.get(url, headers=hdr, timeout=timeout)
                else:
                    rsp = self.fetch(url, headers=hdr, timeout=timeout)

                if rsp.status_code == 200:
                    try:
                        return rsp.text
                    except Exception:
                        try:
                            return rsp.content.decode('utf-8', 'ignore')
                        except Exception:
                            return ""

                # 520/503/403 等错误，重试
                if rsp.status_code in (520, 503, 403, 521, 429, 502):
                    time.sleep(1.0 + attempt * 0.6)
                    continue

                return ""
            except Exception:
                time.sleep(0.6 + attempt * 0.4)

        return ""

    # ===== 工具 =====
    def _strip(self, s):
        s = re.sub(r'<[^>]+>', '', s or '').strip()
        return self._unescape(s)

    def _unescape(self, s):
        return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))

    def _fixpic(self, p):
        if not p:
            return ""
        if p.startswith("//"):
            return "https:" + p
        return p

    def _is_direct(self, u):
        u = (u or "").lower()
        return ".m3u8" in u or ".mp4" in u or ".flv" in u or ".mkv" in u

    def _is_official(self, u):
        u = (u or "").lower()
        keys = ("mgtv.com", "youku.com", "iqiyi.com", "qiyi.com",
                "v.qq.com", "bilibili.com", "le.com", "sohu.com")
        return any(k in u for k in keys) and not self._is_direct(u)

    def _is_dytt(self, u):
        u = (u or "").lower()
        return ("dytt" in u or "dy2018" in u) and "/share/" in u and not self._is_direct(u)

    def _ref(self, url):
        try:
            if "://" in url:
                s = url.split("://")[0]
                h = url.split("://")[1].split("/")[0]
                return s + "://" + h + "/"
        except Exception:
            pass
        return HOST + "/"

    # ===== 列表解析（多正则兜底）=====
    def _parse_list(self, html):
        if not html:
            return []

        items = []
        seen = set()

        for pattern in RE_VOD_PATTERNS:
            for m in pattern.finditer(html):
                href = m.group(1)
                vid = m.group(2)
                if vid in seen:
                    continue

                name = ""
                pic = ""
                try:
                    name = (m.group(3) or "").strip()
                except Exception:
                    pass
                try:
                    pic = m.group(4) or ""
                except Exception:
                    pass

                # 如果没拿到name，从附近找
                if not name:
                    # 从 href 位置往前找 title
                    pos = html.find(href)
                    if pos > 0:
                        snippet = html[max(0, pos-300):pos+500]
                        tm = re.search(r'title="([^"]*)"', snippet)
                        if tm:
                            name = tm.group(1).strip()

                # 如果没拿到pic，从附近找
                if not pic:
                    pos = html.find(href)
                    if pos > 0:
                        snippet = html[max(0, pos-100):pos+800]
                        pm = re.search(r'(?:data-original|src)="([^"]+)"', snippet)
                        if pm:
                            pic = pm.group(1)

                # 集数/状态
                remark = ""
                pos = html.find(href)
                if pos > 0:
                    snippet = html[pos:pos+800]
                    rm = RE_PIC_TAG.search(snippet)
                    if rm:
                        remark = self._strip(rm.group(1))
                    if not remark:
                        rm = RE_REMARK_TEXT.search(snippet)
                        if rm:
                            remark = self._strip(rm.group(1))

                if vid and name:
                    seen.add(vid)
                    items.append({
                        "vod_id": vid,
                        "vod_name": name,
                        "vod_pic": self._fixpic(pic),
                        "vod_remarks": remark or "HD",
                    })

            if items:
                break  # 第一个匹配到就够了

        return items

    # ===== 分页 =====
    def _pagecount(self, html):
        m = RE_PAGE_END.search(html)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        m = RE_PAGE_TOTAL.search(html)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        return 1

    def _total(self, html):
        m = RE_TOTAL_NUM.search(html)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        return 0

    # ===== 详情解析 =====
    def _parse_detail(self, html, vid):
        info = {"vod_id": str(vid)}

        # 片名（多模式）
        m = RE_H1.search(html)
        info["vod_name"] = m.group(1).strip() if m else ""
        if not info["vod_name"]:
            m = RE_TITLE_TAG.search(html)
            info["vod_name"] = m.group(1).strip() if m else ""
        if not info["vod_name"]:
            m = re.search(r'<h[1-3][^>]*class="[^"]*(?:title|name)[^"]*"[^>]*>(.*?)</h', html, re.I | re.S)
            if m:
                info["vod_name"] = self._strip(m.group(1))
        if not info["vod_name"]:
            # 从title标签取
            tm = re.search(r'<title>([^-|_]+)', html, re.I)
            if tm:
                info["vod_name"] = tm.group(1).strip()

        # 海报（多模式）
        m = RE_DATA_ORIG.search(html)
        info["vod_pic"] = self._fixpic(m.group(1)) if m else ""
        if not info["vod_pic"]:
            m = RE_IMG_SRC.search(html)
            info["vod_pic"] = self._fixpic(m.group(1)) if m else ""
        if not info["vod_pic"]:
            m = re.search(r'vod_pic["\s:=]+["\']([^"\']+)["\']', html, re.I)
            if m:
                info["vod_pic"] = self._fixpic(m.group(1))
        if not info["vod_pic"]:
            # 详情页大图区域
            im = re.search(r'<div[^>]*class="[^"]*(?:detail-img|detail_pic|detailpic|pic-box|img-wrap)[^"]*"[^>]*>.*?<img[^>]*src="([^"]+)"', html, re.I | re.S)
            if im:
                info["vod_pic"] = self._fixpic(im.group(1))

        # 分类/年份/地区
        m = RE_TYPE.search(html)
        info["type_name"] = self._strip(m.group(1)) if m else ""
        if not info["type_name"]:
            m = re.search(r'类型[：:]\s*<[^>]*>([^<]+)', html, re.I)
            if m:
                info["type_name"] = self._strip(m.group(1))
        m = RE_YEAR.search(html)
        info["vod_year"] = self._strip(m.group(1)) if m else ""
        if not info["vod_year"]:
            m = re.search(r'年份[：:]\s*<[^>]*>([^<]+)', html, re.I)
            if m:
                info["vod_year"] = self._strip(m.group(1))
        m = RE_AREA.search(html)
        info["vod_area"] = self._strip(m.group(1)) if m else ""
        if not info["vod_area"]:
            m = re.search(r'地区[：:]\s*<[^>]*>([^<]+)', html, re.I)
            if m:
                info["vod_area"] = self._strip(m.group(1))

        # 导演（多模式 - 从a标签提取）
        m = RE_DIRECTOR.search(html)
        info["vod_director"] = self._strip(m.group(1)) if m else ""
        if not info["vod_director"]:
            m = RE_OG_DIRECTOR.search(html)
            if m:
                info["vod_director"] = self._unescape(m.group(1)).strip()
        if not info["vod_director"]:
            m = re.search(r'导演[：:]\s*<[^>]*>([^<]+)', html, re.I)
            if m:
                info["vod_director"] = self._strip(m.group(1))

        # 主演（多模式 - 从a标签提取）
        m = RE_ACTOR.search(html)
        info["vod_actor"] = self._strip(m.group(1)) if m else ""
        if not info["vod_actor"]:
            m = RE_OG_ACTOR.search(html)
            if m:
                info["vod_actor"] = self._unescape(m.group(1)).strip()
        if not info["vod_actor"]:
            m = re.search(r'主演[：:]\s*<[^>]*>([^<]+)', html, re.I)
            if m:
                info["vod_actor"] = self._strip(m.group(1))

        # 简介（多模式：简短版 > JS全文 > meta description）
        info["vod_content"] = ""
        # 优先简短版（最可靠）
        m = RE_CONTENT_BRIEF.search(html)
        if m:
            info["vod_content"] = self._strip(m.group(1))[:500]
        if not info["vod_content"] or len(info["vod_content"]) < 20:
            # JS弹窗里的完整剧情（如果有的话）
            m = RE_CONTENT_JS.search(html)
            if m:
                js_content = self._unescape(m.group(1).replace("\\'", "'")).strip()
                if len(js_content) > 10:  # 过滤掉"..."之类的占位符
                    info["vod_content"] = js_content[:500]
        if not info["vod_content"]:
            # meta description 兜底
            m = RE_META_DESC.search(html)
            if m:
                info["vod_content"] = self._unescape(m.group(1)).strip()[:500]

        # 状态
        m = RE_PIC_TAG.search(html)
        info["vod_remarks"] = self._strip(m.group(1)) if m else "HD"
        if not info["vod_remarks"] or info["vod_remarks"] == "HD":
            rm = re.search(r'状态[：:]\s*<[^>]*>([^<]+)', html, re.I)
            if rm:
                info["vod_remarks"] = self._strip(rm.group(1)) or "HD"

        # ===== 播放地址：7层兜底 =====
        play_from = []
        play_url = []

        # 第1层: JS变量 vod_play_from/url (标准苹果CMS)
        pf = RE_PLAY_FROM.search(html)
        pu = RE_PLAY_URL.search(html)
        if pf and pu:
            f_raw = self._unescape(pf.group(1))
            u_raw = self._unescape(pu.group(1))
            f_list, u_list = self._split_play(f_raw, u_raw)
            if f_list:
                play_from, play_url = f_list, u_list

        # 第1.5层: MacCMS mac_url/mac_from
        if not play_url:
            mf = RE_MAC_FROM.search(html)
            mu = RE_MAC_URL.search(html)
            if mf and mu:
                f_raw = self._unescape(mf.group(1))
                u_raw = self._unescape(mu.group(1))
                f_list, u_list = self._split_play(f_raw, u_raw)
                if f_list:
                    play_from, play_url = f_list, u_list

        # 第2层: player_url / video_url / 单个直链
        if not play_url:
            pu2 = RE_PLAYER_URL.search(html)
            if not pu2:
                pu2 = RE_VIDEO_URL_VAR.search(html)
            if pu2:
                u = self._unescape(pu2.group(1))
                if self._is_direct(u):
                    play_from = ["播放源"]
                    play_url = ["正片$" + u]

        # 第2.5层: 尝试解码 base64 / 加密数据
        if not play_url:
            enc = RE_ENCRYPT_DATA.search(html)
            if enc:
                try:
                    import base64
                    enc_str = enc.group(1)
                    if len(enc_str) > 20:
                        dec = base64.b64decode(enc_str).decode('utf-8', errors='ignore')
                        if 'http' in dec or '.m3u8' in dec or '.mp4' in dec:
                            if self._is_direct(dec):
                                play_from = ["播放源"]
                                play_url = ["正片$" + dec]
                except Exception:
                    pass

        # 第3层: 播放列表HTML - 从tab提取真实线路名，按sid分组（6080影视真实结构）
        if not play_url:
            eps = RE_PLAY_LINKS.findall(html)
            if eps:
                # 先从tab提取真实线路名
                tab_names = {}
                for tm in RE_PLAY_TABS.finditer(html):
                    tab_sid = tm.group(1)
                    tab_name = tm.group(2).strip()
                    tab_names[tab_sid] = tab_name

                # 按sid分组
                from collections import OrderedDict
                groups = OrderedDict()
                for href, vid, sid, nid, ep_name in eps:
                    sid = str(sid)
                    ep_name = ep_name.strip()
                    full = HOST + href
                    if sid not in groups:
                        disp_name = tab_names.get(sid) or LINE_NAMES.get(sid, "线路" + sid)
                        groups[sid] = {"name": disp_name, "eps": []}
                    groups[sid]["eps"].append("%s$%s" % (ep_name, full))

                if groups:
                    play_from = [g["name"] for g in groups.values()]
                    play_url = ["#".join(g["eps"]) for g in groups.values()]

        # 第3.5层: 通用播放列表ul>li>a（兜底）
        if not play_url:
            ul_m = RE_PLAY_LIST_A.search(html)
            if ul_m:
                ul_html = ul_m.group(1)
                eps2 = RE_PLAY_ITEM.findall(ul_html)
                if eps2:
                    ep_list = []
                    for href, ep_name in eps2:
                        ep_name = ep_name.strip()
                        if href.startswith("/"):
                            full = HOST + href
                        elif href.startswith("http"):
                            full = href
                        else:
                            continue
                        ep_list.append("%s$%s" % (ep_name, full))
                    if ep_list:
                        play_from = ["播放源"]
                        play_url = ["#".join(ep_list)]

        # 第4层: 全文扫描直链
        if not play_url:
            m3u8 = RE_M3U8.search(html)
            if m3u8 and self._is_direct(m3u8.group(1)):
                play_from = ["直链"]
                play_url = ["正片$" + m3u8.group(1)]
            else:
                mp4 = RE_MP4.search(html)
                if mp4:
                    play_from = ["直链"]
                    play_url = ["正片$" + mp4.group(1)]

        # 第4.5层: 扫描 iframe / video 标签的 src
        if not play_url:
            vm = re.search(r'<video[^>]*src="([^"]+)"', html, re.I)
            if vm:
                src = vm.group(1)
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = HOST + src
                if "http" in src and self._is_direct(src):
                    play_from = ["直链"]
                    play_url = ["正片$" + src]

        # 第5层: iframe
        if not play_url:
            im = RE_IFRAME.search(html)
            if im:
                src = im.group(1)
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = HOST + src
                if "http" in src:
                    play_from = ["播放源"]
                    play_url = ["正片$" + src]

        # 第6层: 扫描所有 data-src / data-url
        if not play_url:
            dm = re.search(r'data-(?:src|url|video)="([^"]+)"', html, re.I)
            if dm:
                src = dm.group(1)
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = HOST + src
                if "http" in src and (".m3u8" in src or ".mp4" in src):
                    play_from = ["播放源"]
                    play_url = ["正片$" + src]

        # 第7层: BFQ/BFQ+ 加密（AES-CBC）
        if not play_url:
            try:
                bfq_m = re.search(r'var\s+(?:bfq_data|bfqurl|bfq_url|enc_data)\s*=\s*["\']([^"\']+)["\']', html, re.I)
                if bfq_m:
                    enc_str = bfq_m.group(1)
                    dec = self._try_bfq_decrypt(enc_str)
                    if dec and ("http" in dec or ".m3u8" in dec):
                        play_from = ["播放源"]
                        play_url = ["正片$" + dec]
            except Exception:
                pass

        info["_pf"] = play_from
        info["_pu"] = play_url
        return info

    # ===== play拆分 =====
    def _split_play(self, from_raw, url_raw):
        if not from_raw or not url_raw:
            return [], []

        from_list = from_raw.split("$$$")
        url_groups = url_raw.split("$$$")
        pf = []
        pu = []

        for i, fn in enumerate(from_list):
            if i >= len(url_groups):
                break
            ug = url_groups[i].strip()
            if not ug:
                continue

            eps = ug.split("#")
            ep_list = []
            for ep in eps:
                ep = ep.strip()
                if not ep:
                    continue
                if "$" in ep:
                    en, eu = ep.split("$", 1)
                    eu = eu.strip()
                    if eu.startswith("//"):
                        eu = "https:" + eu
                    ep_list.append("%s$%s" % (en.strip(), eu))
                else:
                    ep_list.append("第%s集$%s" % (len(ep_list) + 1, ep))

            if ep_list:
                disp = LINE_NAMES.get(fn.strip(), fn.strip())
                pf.append(disp)
                pu.append("#".join(ep_list))

        return pf, pu

    # ===== 线路排序 =====
    def _sort_lines(self, pf, pu):
        d_f, d_u = [], []
        y_f, y_u = [], []
        o_f, o_u = [], []
        g_f, g_u = [], []

        for f, u in zip(pf, pu):
            first = u.split("#")[0]
            first_url = first.split("$", 1)[1] if "$" in first else ""

            if self._is_direct(first_url):
                d_f.append(f); d_u.append(u)
            elif self._is_dytt(first_url):
                y_f.append(f); y_u.append(u)
            elif self._is_official(first_url):
                g_f.append(f); g_u.append(u)
            else:
                o_f.append(f); o_u.append(u)

        return (d_f + y_f + o_f + g_f), (d_u + y_u + o_u + g_u)

    # ===== 播放页解析 =====
    def _resolve_play_page(self, url):
        # 缓存检查
        with self._play_lock:
            cached = self._play_cache.get(url)
            if cached:
                return cached

        # 从播放URL提取详情页URL作为Referer
        referer = HOST + "/"
        m = re.search(r'/6080play/(\d+)/', url)
        if m:
            referer = HOST + "/6080detail/%s.html" % m.group(1)

        html = self._get(url, timeout=15, referer=referer)
        if not html:
            return ""

        result = ""

        # 第1优先：player_aaaa JSON（6080影视标准格式）
        pm = RE_PLAYER_AAAA.search(html)
        if pm:
            json_str = pm.group(1)
            try:
                import json
                data = json.loads(json_str)
                u = data.get("url", "") or ""
                u = u.replace("\\/", "/")
                if u and self._is_direct(u):
                    result = u
                # 加密的话尝试解密
                if not result and data.get("encrypt", 0) == 1 and u:
                    dec = self._try_bfq_decrypt(u)
                    if dec and self._is_direct(dec):
                        result = dec
            except Exception:
                # JSON解析失败，用正则兜底
                um = RE_PLAYER_URL_JSON.search(json_str)
                if um:
                    u = um.group(1).replace("\\/", "/")
                    if self._is_direct(u):
                        result = u

        # 第2优先：正则匹配m3u8直链
        if not result:
            m = RE_M3U8.search(html)
            if m and self._is_direct(m.group(1)):
                result = m.group(1)

        if not result:
            m = RE_MP4.search(html)
            if m:
                result = m.group(1)

        if not result:
            m = RE_URL_VAR.search(html)
            if m:
                u = m.group(1)
                if u.startswith("//"):
                    u = "https:" + u
                elif u.startswith("/"):
                    u = HOST + u
                if self._is_direct(u):
                    result = u

        m = RE_IFRAME.search(html)
        if not result and m and "http" in m.group(1):
            result = m.group(1)

        # 存入缓存
        if result:
            with self._play_lock:
                self._play_cache[url] = result

        return result

    # ===== dytt =====
    def _resolve_dytt(self, url):
        for _ in range(2):
            html = self._get(url, timeout=7)
            if not html:
                time.sleep(0.3)
                continue
            for pat in [
                r'const\s+url\s*=\s*"([^"]+)"',
                r'var\s+url\s*=\s*"([^"]+)"',
                r'url\s*[:=]\s*"([^"]+\.m3u8[^"]*)"',
            ]:
                m = re.search(pat, html)
                if m and ".m3u8" in m.group(1):
                    u = m.group(1)
                    if u.startswith("http"):
                        return u
                    return self._ref(url).rstrip("/") + u
            time.sleep(0.3)
        return ""

    # ===== BFQ =====
    def _aes_dec(self, ct):
        try:
            from Crypto.Cipher import AES
            key = ct[-32:-16].encode()
            iv = ct[-16:].encode()
            data = base64.b64decode(ct[:-32])
            raw = AES.new(key, AES.MODE_CBC, iv).decrypt(data)
            pad = raw[-1] if raw else 0
            if 0 < pad <= 16:
                raw = raw[:-pad]
            return raw.decode("utf-8", "ignore")
        except Exception:
            return ""

    def _resolve_bfq(self, src_url):
        if not src_url or not self._is_official(src_url):
            return ""
        try:
            page = "https://bfq.txnp.cn/player?url=" + quote(src_url, safe="")
            ref = "https://bfq.txnp.cn/excessive?url=" + quote(src_url, safe="")
            hdr = dict(self.header)
            hdr["Referer"] = ref
            rsp = self.fetch(page, headers=hdr, timeout=8)
            html = ""
            try:
                html = rsp.text
            except Exception:
                html = rsp.content.decode("utf-8", "ignore")
            result = re.search(r'let\s+result\s*=\s*"([^"]+)"', html, re.S)
            if not result:
                return ""
            text = self._aes_dec(result.group(1))
            if not text:
                return ""
            data = json.loads(text)
            media = ((data.get("video_info") or {}).get("video") or {}).get("url", "")
            media = media.replace("\\/", "/")
            if media and self._is_direct(media):
                return media
        except Exception:
            pass
        return ""

    def _try_bfq_decrypt(self, enc_str):
        """尝试BFQ AES-CBC解密，返回解密后的字符串或空"""
        if not enc_str:
            return ""
        try:
            dec = self._aes_dec(enc_str)
            if dec and ("http" in dec or ".m3u8" in dec or ".mp4" in dec):
                return dec
        except Exception:
            pass
        # 尝试其他常见密钥
        try:
            import base64
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import unpad
            raw = base64.b64decode(enc_str)
            keys_to_try = [
                b"bfqplaybfqplaybfqplaybfqplay12",
                b"wwwbfqyuncomwwwbfqyuncom123456",
                b"BFQPLAYERBFQPLAYERBFQPLAYERBF",
                b"0123456789abcdef0123456789abcdef",
                b"abcdefghijklmnopqrstuvwxyz0123",
            ]
            ivs_to_try = [
                b"0123456789abcdef",
                b"bfqplayeriv12345",
                b"abcdefghijklmnop",
                b"",  # 无IV
            ]
            for key in keys_to_try:
                for iv in ivs_to_try:
                    try:
                        if iv:
                            cipher = AES.new(key, AES.MODE_CBC, iv)
                        else:
                            cipher = AES.new(key, AES.MODE_ECB)
                        dec = unpad(cipher.decrypt(raw), AES.block_size).decode('utf-8', errors='ignore')
                        if dec and ("http" in dec or ".m3u8" in dec):
                            return dec
                    except Exception:
                        continue
        except Exception:
            pass
        return ""

    def _build_detail_urls(self, vid):
        """构建多种详情页URL"""
        urls = [
            HOST + "/6080detail/%s.html" % vid,
            HOST + "/voddetail/id/%s.html" % vid,
            HOST + "/index.php/vod/detail/id/%s.html" % vid,
            HOST + "/detail/%s.html" % vid,
            HOST + "/movie/%s.html" % vid,
            HOST + "/vod/detail/id/%s.html" % vid,
        ]
        return urls

    # ============================================================
    # 首页
    # ============================================================

    def homeContent(self, filter):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        now = int(time.time())
        if self._home_cache and now - self._home_time < 300:
            return {"list": list(self._home_cache)}

        html = self._get(HOST + "/", timeout=8)
        videos = self._parse_list(html) if html else []

        self._home_cache = videos[:72]
        self._home_time = now
        return {"list": list(self._home_cache)}

    # ============================================================
    # 分类列表（多URL尝试）
    # ============================================================

    def _cat_key(self, tid, pg, ext):
        return "%s_%s_%s" % (tid, pg, json.dumps(ext, sort_keys=True) if ext else "")

    def _cat_get(self, key):
        with self._cat_lock:
            e = self._cat_cache.get(key)
            if e and int(time.time()) - e["time"] < 180:
                return e["data"]
        return None

    def _cat_set(self, key, data):
        with self._cat_lock:
            self._cat_cache[key] = {"time": int(time.time()), "data": data}
            if len(self._cat_cache) > 40:
                ks = sorted(self._cat_cache.keys(), key=lambda k: self._cat_cache[k]["time"])
                for k in ks[:20]:
                    del self._cat_cache[k]

    def _build_cat_urls(self, tid, page, ext):
        """构建多种可能的分类页URL，按优先级返回列表"""
        urls = []
        params = {}
        if ext.get("class"):
            params["class"] = ext["class"]
        if ext.get("area"):
            params["area"] = ext["area"]
        if ext.get("year") and ext["year"] != "更早":
            params["year"] = ext["year"]
        if ext.get("by"):
            params["by"] = ext["by"]

        qs = ("?" + urlencode(params)) if params else ""

        # URL格式1: /vodshow/id/{id}-page-{pg}.html (标准苹果CMS)
        if page > 1:
            urls.append(HOST + "/vodshow/id/%s-page-%d.html%s" % (tid, page, qs))
        else:
            urls.append(HOST + "/vodshow/id/%s.html%s" % (tid, qs))

        # URL格式2: /movie-genres/{id}.html (mytheme分类页)
        if page > 1:
            urls.append(HOST + "/movie-genres/%s-page-%d.html%s" % (tid, page, qs))
        else:
            urls.append(HOST + "/movie-genres/%s.html%s" % (tid, qs))

        # URL格式3: /index.php/vod/show/id/{id}.html
        if page > 1:
            urls.append(HOST + "/index.php/vod/show/id/%s/pg/%d.html%s" % (tid, page, qs))
        else:
            urls.append(HOST + "/index.php/vod/show/id/%s.html%s" % (tid, qs))

        # URL格式4: /vodshow/id-{id}.html (变体)
        if page > 1:
            urls.append(HOST + "/vodshow/id-%s-page-%d.html%s" % (tid, page, qs))
        else:
            urls.append(HOST + "/vodshow/id-%s.html%s" % (tid, qs))

        return urls

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1

            ext = {}
            if extend:
                if isinstance(extend, dict):
                    ext = extend
                elif isinstance(extend, str):
                    try:
                        ext = json.loads(extend)
                    except Exception:
                        ext = {}

            key = self._cat_key(tid, page, ext)
            cached = self._cat_get(key)
            if cached:
                return cached

            # 多URL尝试
            urls = self._build_cat_urls(tid, page, ext)
            videos = []
            pagecount = 1
            total = 0
            html = ""

            for url in urls:
                html = self._get(url, timeout=9)
                if not html:
                    continue
                videos = self._parse_list(html)
                if videos:
                    pagecount = self._pagecount(html)
                    total = self._total(html)
                    break

            if total == 0 and videos:
                total = len(videos) * max(pagecount, 1)

            result = {
                "list": videos,
                "page": page,
                "pagecount": pagecount,
                "limit": 20,
                "total": total,
            }
            self._cat_set(key, result)
            return result
        except Exception:
            return {"page": 1, "pagecount": 1, "limit": 20, "total": 0, "list": []}

    # ============================================================
    # 详情页
    # ============================================================

    def _detail_get(self, vid):
        with self._detail_lock:
            e = self._detail_cache.get(vid)
            if e and int(time.time()) - e["time"] < 120:
                return e["data"]
        return None

    def _detail_set(self, vid, data):
        with self._detail_lock:
            self._detail_cache[vid] = {"time": int(time.time()), "data": data}
            if len(self._detail_cache) > 30:
                ks = sorted(self._detail_cache.keys(), key=lambda k: self._detail_cache[k]["time"])
                for k in ks[:15]:
                    del self._detail_cache[k]

    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        vid = str(ids[0])

        cached = self._detail_get(vid)
        if cached:
            return {"list": [cached]}

        # 多URL尝试
        urls = self._build_detail_urls(vid)
        html = ""
        best_url = ""

        for url in urls:
            for i in range(2):
                h = self._get(url, timeout=10)
                if h and len(h) > 2000:
                    html = h
                    best_url = url
                    break
                time.sleep(0.3)
            if html:
                break

        if not html:
            return {"list": []}

        info = self._parse_detail(html, vid)

        if not info.get("vod_name"):
            return {"list": []}

        pf = info.pop("_pf", [])
        pu = info.pop("_pu", [])

        # 即使没有播放地址，也返回详情（保证详情页能打开）
        if not pu:
            pf = ["暂无播放源"]
            pu = ["正片$about:blank"]
        else:
            pf, pu = self._sort_lines(pf, pu)

        info["vod_play_from"] = "$$$".join(pf)
        info["vod_play_url"] = "$$$".join(pu)

        self._detail_set(vid, info)
        return {"list": [info]}

    # ============================================================
    # 搜索
    # ============================================================

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1

            urls = [
                HOST + "/moviesearch/wd/" + quote(key, safe="") +
                ("-page-%d" % page if page > 1 else "") + ".html",
                HOST + "/index.php/vod/search/wd/" + quote(key, safe="") +
                ("/pg/%d" % page if page > 1 else "") + ".html",
                HOST + "/search?wd=" + quote(key, safe="") +
                ("&pg=%d" % page if page > 1 else ""),
            ]

            for url in urls:
                html = self._get(url, timeout=8)
                if not html:
                    continue
                videos = self._parse_list(html)
                if videos:
                    return {"list": videos}

            return {"list": []}
        except Exception:
            return {"list": []}

    # ============================================================
    # 播放
    # ============================================================

    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {"parse": 0, "playUrl": "", "url": ""}

        url = str(id).replace("\\/", "/")

        # 1. 直链 → 秒开
        if self._is_direct(url):
            is_m3u8 = ".m3u8" in url.lower()
            ref = self._ref(url)
            return {
                "parse": 0, "playUrl": "", "url": url,
                "header": {"User-Agent": UA, "Referer": ref},
                "format": "application/x-mpegURL" if is_m3u8 else "",
                "contentType": "application/x-mpegURL" if is_m3u8 else "",
            }

        # 2. dytt share
        if self._is_dytt(url):
            r = self._resolve_dytt(url)
            if r and self._is_direct(r):
                ref = self._ref(r)
                return {
                    "parse": 0, "playUrl": "", "url": r,
                    "header": {"User-Agent": UA, "Referer": ref},
                    "format": "application/x-mpegURL",
                    "contentType": "application/x-mpegURL",
                }
            return {"parse": 1, "playUrl": "", "url": url,
                    "header": {"User-Agent": UA, "Referer": HOST + "/"}}

        # 3. 官源 BFQ
        if self._is_official(url):
            r = self._resolve_bfq(url)
            if r and self._is_direct(r):
                is_m3u8 = ".m3u8" in r.lower()
                return {
                    "parse": 0, "playUrl": "", "url": r,
                    "header": {"User-Agent": UA, "Referer": "https://bfq.txnp.cn/"},
                    "format": "application/x-mpegURL" if is_m3u8 else "",
                    "contentType": "application/x-mpegURL" if is_m3u8 else "",
                }
            return {"parse": 1, "playUrl": "", "url": url,
                    "header": {"User-Agent": UA, "Referer": HOST + "/"}}

        # 4. 本站播放页
        if "/6080play/" in url or "66191999.com" in url:
            r = self._resolve_play_page(url)
            if r and self._is_direct(r):
                is_m3u8 = ".m3u8" in r.lower()
                ref = self._ref(r)
                return {
                    "parse": 0, "playUrl": "", "url": r,
                    "header": {"User-Agent": UA, "Referer": ref},
                    "format": "application/x-mpegURL" if is_m3u8 else "",
                    "contentType": "application/x-mpegURL" if is_m3u8 else "",
                }
            return {"parse": 1, "playUrl": "", "url": url,
                    "header": {"User-Agent": UA, "Referer": HOST + "/"}}

        # 5. 其他 → 壳子
        return {"parse": 1, "playUrl": "", "url": url,
                "header": {"User-Agent": UA, "Referer": HOST + "/"}}

    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]

    def destroy(self):
        pass

    def close(self):
        self.destroy()
