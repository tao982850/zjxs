# -*- coding: utf-8 -*-
"""
Wogg（玩偶）站点 TVBox Python Spider
站点：https://woggpan.888484.xyz （及 ext.site 中的备用镜像）

用法（配置 json 的 site 条目）：
    {"key": "玩偶", "name": "玩偶｜4K", "type": 3, "api": "./py/wogg.py",
     "searchable": 1, "quickSearch": 1, "filterable": 0,
     "ext": {"site": ["https://woggpan.888484.xyz"],
             "cookie": "",
             "parse": ""}}

ext 说明：
    site   ：域名列表，插件按顺序探测，取第一个能返回 200 的作为基址
    cookie ：可选，整串 Cookie。站点被 Cloudflare 挑战时，需填含 cf_clearance 的 Cookie
    parse  ：可选，第三方网盘解析接口前缀；留空时 playerContent 直接返回网盘分享链接

线路命名规则（与 jar 内 csp_Wogg 一致）：
    playFrom 由详情页网盘链接类型自动展开，格式  {网盘}{画质}#{序号}
    例如：百度原画#1$$$夸克原画#2$$$夸克普画#2$$$UC原画#3
    序号 = 该网盘链接在排序后列表中的位置，从 1 开始
"""

import json
import re
import ssl
import gzip
import io
import time
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
import urllib.request
import urllib.error

# 宿主内核的 Python 引擎要求主类名为 Spider 并继承 base.spider.Spider，
# 缺了这一步客户端只会提示「爬虫加载失败」。缺失时回退到 object，保证本地可测。
try:
    from base.spider import Spider as SpiderBase
except Exception:
    class SpiderBase(object):
        def __init__(self):
            pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")

DEFAULT_SITES = ["https://woggpan.888484.xyz"]

# 与 jar 内 homeContent 一致的分类
CATEGORIES = [
    ("44", "臻彩视觉"), ("1", "玩偶电影"), ("2", "玩偶剧集"),
    ("3", "动漫"), ("4", "综艺"), ("5", "音乐"), ("6", "短剧"),
]

# 各网盘链路正则（来源：csp_Wogg 父类 Pan 中的匹配规则）
PAN_RULES = [
    ("阿里", re.compile(r"(?:www\.)?ali(?:yundrive|pan)\.com/s/([^/\s?#]+)")),
    ("夸克", re.compile(r"pan\.quark\.cn/s/([^/\s?#]+)")),
    ("UC", re.compile(r"drive\.uc\.cn/s/([0-9a-fA-F]{8,20})")),
    ("天翼", re.compile(r"cloud\.189\.cn/t/([^/\s?#]+)")),
    ("123", re.compile(r"(?:www\.)?123[a-zA-Z0-9]{3}\.com/s/([^/\s?#]+)")),
    ("百度", re.compile(r"pan\.baidu\.com/(?:s/1([^?\s]+)|share/init\?surl=([^&\s]+))")),
    ("移动", re.compile(r"caiyun\.139\.com/(?:w/i/|m/i\?linkID=)([0-9A-Za-z]+)")),
]

# 各网盘"线路"候选画质（来源：Config.get*Options()）
QUALITY = {
    "阿里": ["阿里原画", "阿里普画"],
    "夸克": ["夸克原画", "夸克普画", "夸克智能"],
    "UC": ["UC原画", "UC普画"],
    "天翼": ["天翼原画"],
    "123": ["123原画"],
    "百度": ["百度原画"],
    "移动": ["移动普画"],
}

# 网盘排序（与面板 panOrder 默认值一致）
PAN_ORDER = ["百度", "夸克", "UC", "天翼", "123", "阿里", "移动"]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Spider(SpiderBase):
    def __init__(self):
        try:
            super(Spider, self).__init__()
        except Exception:
            pass
        self.base = ""
        self.cookie = ""
        self.parse_api = ""
        self.ext = {}

    # 宿主会调用的元信息方法，缺了部分内核会判定爬虫不合法
    def getName(self):
        return "玩偶｜4K"

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ---------- 基础 ----------

    def init(self, extend=""):
        try:
            if extend:
                ext = json.loads(extend) if extend.strip().startswith("{") else {}
            else:
                ext = {}
        except Exception:
            ext = {}
        self.ext = ext
        sites = ext.get("site") or DEFAULT_SITES
        if isinstance(sites, str):
            sites = [sites]
        self.cookie = (ext.get("cookie") or "").strip()
        self.parse_api = (ext.get("parse") or "").strip()
        self.base = self._pick_base(sites) or sites[0].rstrip("/")
        return True

    def _headers(self):
        h = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": (self.base or "") + "/",
        }
        if self.cookie:
            h["Cookie"] = self.cookie
        return h

    def _pick_base(self, sites):
        """按顺序探测，取第一个 200 且确实是影视站的地址。
        注意：域名停放页（parklogic 等）也会返回 200，必须靠内容特征排除。"""
        for s in sites:
            s = (s or "").strip().rstrip("/")
            if not s.startswith("http"):
                continue
            try:
                r = self._request(s + "/", timeout=8)
                if r and r[0] == 200 and self._looks_like_site(r[1]):
                    return s
            except Exception:
                continue
        return ""

    @staticmethod
    def _looks_like_site(html):
        """停放页/挑战页没有这些标记，只有真实 maccms 站点才有。"""
        if not html or len(html) < 2000:
            return False
        marks = ("module-item", "voddetail", "vodshow", "vodsearch")
        return any(m in html for m in marks)

    def _request(self, url, timeout=15):
        """返回 (状态码, 文本)；不解压的不走，直接读。"""
        try:
            req = Request(url, headers=self._headers())
            ctx = ssl._create_unverified_context()
            opener = build_opener(urllib.request.HTTPSHandler(context=ctx))
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                code = resp.getcode()
                enc = resp.headers.get("Content-Encoding", "")
                if "gzip" in enc:
                    try:
                        raw = gzip.decompress(raw)
                    except Exception:
                        pass
                charset = "utf-8"
                ctype = resp.headers.get("Content-Type", "")
                m = re.search(r"charset=([\w-]+)", ctype, re.I)
                if m:
                    charset = m.group(1)
                return code, raw.decode(charset, "replace")
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
                if e.headers.get("Content-Encoding", "") == "gzip":
                    body = gzip.decompress(body)
            except Exception:
                body = b""
            return e.code, body.decode("utf-8", "replace")
        except Exception:
            return 0, ""

    @staticmethod
    def _clean(s):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()

    # ---------- 列表解析 ----------

    def _parse_list(self, html):
        vods, seen = [], set()
        # maccms 模板：<a class="module-item-pic" href="..." title="..."> 或 <div class="module-item">
        pattern = re.compile(
            r'<a[^>]+class="[^"]*module-item-pic[^"]*"[^>]*>', re.I)
        for block in re.split(r'(?=<a[^>]+class="[^"]*module-item)', html):
            if "module-item" not in block:
                continue
            m = re.search(r'href="([^"]+)"', block)
            if not m:
                continue
            href = m.group(1)
            if "/voddetail/" not in href:
                continue
            if href in seen:
                continue
            seen.add(href)
            title = self._attr(block, "title") or self._attr(block, "alt")
            pic = ""
            pm = re.search(r'<img[^>]+(?:data-src|data-original|src)="([^"]+)"', block)
            if pm:
                pic = pm.group(1)
                if pic.startswith("//"):
                    pic = "https:" + pic
                elif pic.startswith("/"):
                    pic = urljoin(self.base + "/", pic)
            note = ""
            nm = re.search(r'class="[^"]*module-item-text[^"]*"[^>]*>(.*?)</', block, re.S)
            if nm:
                note = self._clean(nm.group(1))
            vods.append({
                "vod_id": href,
                "vod_name": title or self._clean(block)[:40],
                "vod_pic": pic,
                "vod_remarks": note,
            })
        return vods

    @staticmethod
    def _attr(block, name):
        m = re.search(name + r'="([^"]*)"', block)
        return m.group(1) if m else ""

    # ---------- 接口 ----------

    def homeContent(self, filter=False):
        classes = [{"type_id": t, "type_name": n} for t, n in CATEGORIES]
        videos = self._parse_list((self._request(self.base + "/", 15) or (0, ""))[1])[:12]
        return {"class": classes, "list": videos}

    def homeVod(self):
        return {"list": self._parse_list((self._request(self.base + "/", 15) or (0, ""))[1])[:12]}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        pg = str(pg or "1")
        extend = extend or {}
        url = "%s/index.php/vodshow/%s--------%s---.html" % (self.base, tid, pg)
        html = (self._request(url, 15) or (0, ""))[1]
        videos = self._parse_list(html)
        return {
            "list": videos,
            "page": pg,
            "pagecount": 1 if len(videos) < 20 else int(pg) + 1,
            "limit": 20,
            "total": len(videos),
        }

    def searchContent(self, key, quick=False, pg="1"):
        kw = quote(key or "")
        url = "%s/index.php/vodsearch/%s----------%s---.html" % (self.base, kw, pg)
        html = (self._request(url, 15) or (0, ""))[1]
        videos = self._parse_list(html)
        # 搜索页是另一套模板，兜底抓一次通用标题块
        if not videos:
            videos = self._parse_search_fallback(html)
        return {"list": videos}

    def _parse_search_fallback(self, html):
        vods, seen = [], set()
        for m in re.finditer(
                r'href="(/index\.php/voddetail/[^"]+)"[^>]*title="([^"]*)"', html):
            href, title = m.group(1), m.group(2)
            if href in seen:
                continue
            seen.add(href)
            vods.append({"vod_id": href, "vod_name": title, "vod_pic": "",
                         "vod_remarks": ""})
        return vods

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) else ids
        if not str(vid).startswith("/"):
            vid = "/index.php/voddetail/%s.html" % vid
        html = (self._request(self.base + vid, 15) or (0, ""))[1]
        if not html:
            return {"list": []}

        title = self._meta(html, "page-title") or self._meta(html, "video-info-header")
        links = self._extract_pan_links(html)
        ordered = self._sort_links(links)
        play_from = self._build_play_from(ordered)
        play_url = self._build_play_url(ordered)

        vod = {
            "vod_id": vid,
            "vod_name": title or "",
            "vod_pic": self._first_pic(html),
            "vod_year": self._label(html, "年份"),
            "vod_area": self._label(html, "地区"),
            "vod_type": self._label(html, "类型"),
            "vod_director": self._label(html, "导演"),
            "vod_actor": self._label(html, "演员"),
            "vod_content": self._desc(html),
            "vod_play_from": play_from,
            "vod_play_url": play_url,
        }
        return {"list": [vod]}

    def playerContent(self, flag, vid, vipFlags=None):
        """flag 是线路名（如 夸克原画#2），vid 是该线路对应的网盘分享链接。"""
        if not vid or not str(vid).startswith("http"):
            return {"parse": 1, "url": "", "header": {}}
        if self.parse_api:
            target = self.parse_api
            if "{url}" in target:
                target = target.replace("{url}", quote(vid, safe=""))
            else:
                target = target.rstrip("/") + "/" + quote(vid, safe="")
            return {"parse": 1, "url": target, "header": {"User-Agent": UA}}
        # 未配置解析接口：把网盘分享链接交给客户端/外部播放器
        return {"parse": 0, "playUrl": "", "url": vid, "header": {"User-Agent": UA}}

    # ---------- 详情辅助 ----------

    def _extract_pan_links(self, html):
        """详情页网盘链接在 .module-row-text 的 data-clipboard-text 属性里。"""
        links = []
        for m in re.finditer(r'data-clipboard-text="([^"]+)"', html):
            u = m.group(1)
            if any(r.search(u) for _, r in PAN_RULES):
                links.append(u)
        if not links:
            # 兜底：全文扫一遍网盘链接
            for m in re.finditer(r'https?://[^\s"\'<>]+', html):
                u = m.group(0)
                if any(r.search(u) for _, r in PAN_RULES):
                    links.append(u)
        out, seen = [], set()
        for u in links:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    @staticmethod
    def _pan_type(url):
        for name, rule in PAN_RULES:
            if rule.search(url):
                return name
        return ""

    def _sort_links(self, links):
        """按 panOrder 排序；百度链接多于一条时倒序（对应 jar 的 PanOrder.sort）。"""
        baidus = [u for u in links if self._pan_type(u) == "百度"]
        if len(baidus) > 1:
            baidus = list(reversed(baidus))
        pool = [u for u in links if self._pan_type(u) != "百度"] + baidus
        ranked = []
        for name in PAN_ORDER:
            for u in pool:
                if self._pan_type(u) == name and u not in ranked:
                    ranked.append(u)
        for u in pool:  # 未识别类型放最后
            if u not in ranked:
                ranked.append(u)
        return ranked

    def _build_play_from(self, links):
        """线路 = 该链接网盘的全部画质 + #序号。"""
        froms = []
        for idx, u in enumerate(links, 1):
            ptype = self._pan_type(u)
            if not ptype:
                continue
            for q in QUALITY.get(ptype, [ptype + "原画"]):
                froms.append("%s#%d" % (q, idx))
        return "$$$".join(froms)

    def _build_play_url(self, links):
        """每条线路对应的选集：单个网盘分享链接只有一项，用画质名做选集名。"""
        urls = []
        for idx, u in enumerate(links, 1):
            ptype = self._pan_type(u)
            if not ptype:
                continue
            for q in QUALITY.get(ptype, [ptype + "原画"]):
                urls.append("%s$%s" % (q, u))
        return "$$$".join(urls)

    def _meta(self, html, cls):
        m = re.search(r'class="[^"]*' + cls + r'[^"]*"[^>]*>(.*?)</', html, re.S)
        return self._clean(m.group(1)) if m else ""

    def _label(self, html, name):
        m = re.search(name + r'\s*[：:]\s*(?:<[^>]+>)*\s*([^<\n]{1,40})', html)
        return self._clean(m.group(1)) if m else ""

    def _desc(self, html):
        m = re.search(r'class="[^"]*(?:sqjj_a|video-info-content|desc)[^"]*"[^>]*>(.*?)</', html, re.S)
        return self._clean(m.group(1)) if m else ""

    def _first_pic(self, html):
        m = re.search(r'<img[^>]+(?:data-src|data-original)="([^"]+)"', html)
        if not m:
            return ""
        u = m.group(1)
        return ("https:" + u) if u.startswith("//") else (urljoin(self.base + "/", u) if u.startswith("/") else u)