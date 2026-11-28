# -*- coding: utf-8 -*-
# =============================================================================
# 玩偶哥哥（wogg）Python Spider  ——  TVBox / FongMi（影视、OK影视）py 插件
# =============================================================================
# 站点形态依据：spider-single.jar 内 csp_Wogg 使用 /vodshow/、/voddetail/、
#               /vodsearch/-------------.html 路由，属苹果CMS(maccms) 标准结构，
#               故本插件按 maccms 页面结构解析，并对多种模板差异做了兜底。
#
# !! 重要 !!
# 2026-11-28 实测：www.wogg.net、wogg.net 均 NXDOMAIN（域名已死）；
#   woggpan.888484.xyz 被 Cloudflare 403；wogg.one / wogg.link 为域名停放页；
#   wogg.cn 是站群模板页（50 条假数据，videoFile 全是 /1.mp4~/8.mp4）。
#   因此本文件**没有经过真实页面验证**。域名恢复后请先跑一次「首页 → 搜索」
#   确认选择器是否命中；若模板不同，改 _parse_list / _parse_plays 里的正则即可。
# =============================================================================
#
# ext 支持三种写法（放在站点配置的 ext 字段）：
#   1) "https://www.wogg.net"                    单域名
#   2) "a.com|b.com|c.com"                       竖线分隔，按顺序探测第一个可用
#   3) {"site":["a.com","b.com"],"parse":1}      JSON，可带 parse 开关
#
# 配置示例：
#   {"key":"wogg","name":"玩偶哥哥","type":3,"api":"./py/wogg.py",
#    "searchable":1,"quickSearch":1,"filterable":1,
#    "ext":{"site":["www.wogg.net","woggpan.888484.xyz"]}}
# =============================================================================

import json
import re
import urllib.parse

try:
    from base.spider import Spider as BaseSpider
except Exception:  # 宿主没有 base.spider 时兜底，保证类可加载
    class BaseSpider(object):
        pass

try:
    import requests
    _HAS_REQUESTS = True
except Exception:
    _HAS_REQUESTS = False

UA = ("Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

# 网盘识别顺序：序号即详情页线路排序（与常见盘搜习惯一致）
PAN_LIST = [
    ("baidu", "百度"),
    ("quark", "夸克"),
    ("uc", "UC"),
    ("tianyi", "天翼"),
    ("123", "123"),
    ("ali", "阿里"),
    ("xunlei", "迅雷"),
    ("mobile", "移动"),
    ("guangya", "光鸭"),
]

PAN_RE = re.compile(
    r"https?://(?:pan\.baidu\.com|pan\.quark\.cn|drive\.quark\.cn|drive\.uc\.cn|"
    r"cloud\.189\.cn|www\.123pan\.com|www\.aliyundrive\.com|www\.alipan\.com|"
    r"pan\.xunlei\.com|yun\.139\.com|www\.guangyapan\.com)/[^\s\"'<>]*", re.I)

VIDEO_RE = re.compile(r"\.(m3u8|mp4|flv|mkv)(\?|$)", re.I)


class Spider(BaseSpider):

    def __init__(self):
        self.host = ""
        self.sites = []
        self.parse_flag = 1
        self.ua = UA
        self.timeout = 12

    # ---------------------------------------------------------------- 生命周期
    def getName(self):
        return "玩偶哥哥"

    def init(self, extend=""):
        try:
            self.host, self.sites, self.parse_flag = self._parse_extend(extend)
        except Exception:
            self.host, self.sites, self.parse_flag = "", [], 1
        if not self.host and self.sites:
            self.host = self._probe(self.sites)
        return True

    def isVideoFormat(self, url):
        return bool(url and VIDEO_RE.search(url))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ---------------------------------------------------------------- 基础工具
    def _parse_extend(self, extend):
        """ext 解析：字符串 / 竖线串 / JSON 对象，返回 (host, sites, parse_flag)"""
        sites, flag = [], 1
        if isinstance(extend, dict):
            raw = extend.get("site") or extend.get("sites") or extend.get("host") or ""
            val = extend.get("parse", 1)
            flag = 1 if val is None else int(val)
        elif isinstance(extend, str) and extend.strip().startswith("{"):
            try:
                obj = json.loads(extend)
                raw = obj.get("site") or obj.get("sites") or obj.get("host") or ""
                val = obj.get("parse", 1)
                flag = 1 if val is None else int(val)
            except Exception:
                raw = extend
        else:
            raw = extend or ""
        if isinstance(raw, (list, tuple)):
            items = list(raw)
        else:
            items = re.split(r"[|,\s]+", str(raw))
        for it in items:
            it = str(it).strip().rstrip("/")
            if not it:
                continue
            if not it.startswith("http"):
                it = "https://" + it
            sites.append(it)
        return (sites[0] if sites else ""), sites, flag

    def _http(self, url, referer=None, post=False, data=None):
        headers = {"User-Agent": self.ua, "Accept": "text/html,*/*",
                   "Referer": referer or (self.host + "/")}
        try:
            if _HAS_REQUESTS:
                if post:
                    r = requests.post(url, headers=headers, data=data, timeout=self.timeout)
                else:
                    r = requests.get(url, headers=headers, timeout=self.timeout)
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text or ""
            import urllib.request
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
            return raw.decode("utf-8", "ignore")
        except Exception:
            return ""

    def _probe(self, sites):
        """按顺序探测可用域名：返回第一个能取到 maccms 特征的基址"""
        for s in sites:
            html = self._http(s + "/")
            if not html:
                continue
            if ("/voddetail/" in html) or ("module-poster-item" in html) or ("module-item" in html):
                return s
        return sites[0] if sites else ""

    def _url(self, path):
        if not path:
            return ""
        if path.startswith("http"):
            return path
        if path.startswith("//"):
            return "https:" + path
        return self.host + "/" + path.lstrip("/")

    @staticmethod
    def _pick(text, pattern, idx=1):
        m = re.search(pattern, text or "", re.S | re.I)
        return (m.group(idx) or "").strip() if m else ""

    # ---------------------------------------------------------------- 列表解析
    def _parse_list(self, html):
        items, seen = [], set()
        for m in re.finditer(r'<a[^>]+href="([^"]*/voddetail/[^"]+)"[^>]*>(.*?)</a>', html or "", re.S | re.I):
            href, block = m.group(1), m.group(2)
            vid = self._pick(href, r'/voddetail/([^/.]+)')
            if not vid or vid in seen:
                continue
            title = (self._pick(block, r'title="([^"]{1,80})"')
                     or self._pick(block, r'alt="([^"]{1,80})"')
                     or self._pick(block, r'class="[^"]*module-poster-item-title[^"]*"[^>]*>([^<]{1,80})<')
                     or self._pick(block, r'<div[^>]*>([^<]{2,60})</div>'))
            pic = self._pick(block, r'(?:data-original|data-src|src)="([^"]+)"')
            note = (self._pick(block, r'class="[^"]*module-item-note[^"]*"[^>]*>([^<]{0,40})<')
                    or self._pick(block, r'class="[^"]*module-item-text[^"]*"[^>]*>([^<]{0,40})<'))
            if not title:
                continue
            seen.add(vid)
            items.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": self._url(pic),
                "vod_remarks": note,
            })
        return items

    def _parse_cats(self, html):
        cats, seen = [], set()
        for m in re.finditer(r'<a[^>]+href="[^"]*/(?:vodshow|vodtype)/(\d+)[^"]*"[^>]*>([^<]{1,20})</a>', html or "", re.I):
            tid, name = m.group(1), m.group(2).strip()
            if tid in seen or not name:
                continue
            seen.add(tid)
            cats.append({"type_id": tid, "type_name": name})
        return cats

    # ---------------------------------------------------------------- 首页/分类
    def homeContent(self, filter=False):
        html = self._http(self.host + "/")
        return {
            "class": self._parse_cats(html),
            "filters": {},
            "list": self._parse_list(html)[:60],
        }

    def categoryContent(self, tid, pg, filter, extend=None):
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        url = "%s/vodshow/%s----------%d---.html" % (self.host, tid, pg)
        html = self._http(url)
        items = self._parse_list(html)
        return {
            "page": pg,
            "pagecount": 9999 if items else 0,
            "limit": len(items),
            "total": len(items) * (9999 if items else 1),
            "list": items,
        }

    # ---------------------------------------------------------------- 详情
    def detailContent(self, ids):
        vid = (ids[0] if isinstance(ids, (list, tuple)) else str(ids)).strip()
        if not vid:
            return {"list": []}
        if vid.startswith("http"):
            detail_url = vid
            vid = self._pick(vid, r'/voddetail/([^/.]+)') or vid
        else:
            detail_url = "%s/voddetail/%s.html" % (self.host, vid.split("|")[0])
        html = self._http(detail_url)

        title = (self._pick(html, r'<h1[^>]*>(.*?)</h1>')
                 or self._pick(html, r'<title>([^<]{1,80})</title>'))
        title = re.sub(r"<[^>]+>", "", title).strip()
        pic = self._pick(html, r'(?:og:image"\s+content|data-original|data-src|poster)="([^"]+)"')
        desc = (self._pick(html, r'class="[^"]*(?:module-info-introduction-content|vod_content|module-info-content)[^"]*"[^>]*>(.*?)</div>')
                or self._pick(html, r'<meta\s+name="description"\s+content="([^"]+)"'))
        desc = re.sub(r"<[^>]+>", "", desc or "").strip()

        plays = self._parse_plays(html)
        pans = self._parse_pans(html)

        play_from, play_url = [], []
        for name, eps in plays:
            if not eps:
                continue
            play_from.append(name)
            play_url.append("$".join("%s$%s" % (n, u) for n, u in eps))
        if pans:
            name, eps = self._pans_to_line(pans)
            if eps:
                play_from.append(name)
                play_url.append("$".join("%s$%s" % (n, u) for n, u in eps))

        row = {
            "vod_id": vid,
            "vod_name": title or vid,
            "vod_pic": self._url(pic),
            "vod_content": desc,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }
        return {"list": [row]}

    def _parse_plays(self, html):
        """maccms 播放列表：按每个 module-play-list 块切分，块内取 /vodplay/ 链接"""
        html = html or ""
        names = [re.sub(r"<[^>]+>", "", b).strip()
                 for b in re.findall(r'<div[^>]*class="[^"]*module-tab-item[^"]*"[^>]*>(.*?)</div>', html, re.S)
                 if re.sub(r"<[^>]+>", "", b).strip()]
        marks = [m.start() for m in re.finditer(r'class="[^"]*module-play-list[^"]*"', html)]
        if not marks:
            marks = [m.start() for m in re.finditer(r'class="[^"]*module-playlist[^"]*"', html)]
        bounds = marks + [len(html)]
        out = []
        for i, st in enumerate(marks):
            seg = html[st:bounds[i + 1]]
            for stop in ("module-info", "module-tab"):
                j = seg.find(stop, 10)
                if j > 0:
                    seg = seg[:j]
            eps = []
            for m in re.finditer(r'<a[^>]+href="([^"]*(?:/vodplay/|/play/)[^"]*)"[^>]*>([^<]{1,40})</a>', seg, re.I):
                eps.append((m.group(2).strip(), self._url(m.group(1))))
            if eps:
                out.append((names[i] if i < len(names) else ("线路%d" % (i + 1)), eps))
        return out

    def _parse_pans(self, html):
        """详情页网盘分享链接，按 PAN_LIST 排序去重"""
        found = []
        for m in PAN_RE.finditer(html or ""):
            u = m.group(0).rstrip("\"'<>,.;")
            if u not in found:
                found.append(u)
        res = []
        for key, name in PAN_LIST:
            for u in found:
                if key == "ali" and ("aliyundrive" in u or "alipan" in u):
                    res.append((name, u))
                elif key == "123" and "123pan" in u:
                    res.append((name, u))
                elif key == "tianyi" and "189.cn" in u:
                    res.append((name, u))
                elif key == "guangya" and "guangyapan" in u:
                    res.append((name, u))
                elif key in u:
                    res.append((name, u))
        return res

    def _pans_to_line(self, pans):
        """网盘线路：线路名「网盘」，选集名「网盘名#序号」"""
        eps = [("%s#%d" % (pan, idx + 1), urllib.parse.quote(u, safe=":/?&=%.~-"))
               for idx, (pan, u) in enumerate(pans)]
        return "网盘", eps

    # ---------------------------------------------------------------- 搜索
    def searchContent(self, key, quick=False, pg="1"):
        key = (key or "").strip()
        if not key:
            return {"list": []}
        kw = urllib.parse.quote(key)
        try:
            page = int(pg or 1)
        except Exception:
            page = 1
        html = self._http("%s/vodsearch/%s----------%d---.html" % (self.host, kw, page))
        items = self._parse_list(html)
        if items:
            return {"list": items}
        # 部分模板走参数式搜索接口
        html = self._http("%s/index.php/ajax/suggest?mid=1&wd=%s" % (self.host, kw))
        items = []
        try:
            data = json.loads(html or "{}")
            for it in (data.get("list") or []):
                items.append({
                    "vod_id": str(it.get("id") or it.get("vod_id") or ""),
                    "vod_name": it.get("name") or it.get("vod_name") or "",
                    "vod_pic": self._url(it.get("pic") or ""),
                    "vod_remarks": "",
                })
        except Exception:
            items = []
        return {"list": items}

    # ---------------------------------------------------------------- 播放
    def playerContent(self, flag, id, vipFlags=None):
        url = urllib.parse.unquote(id or "")
        if not url:
            return {"parse": 0, "url": ""}
        # 直链：直接交给播放器
        if VIDEO_RE.search(url):
            return {"parse": 0, "url": url, "header": {"User-Agent": self.ua}}
        # 网盘分享：交给内核嗅探/解析（需 ext.parse=1 或客户端配解析）
        return {"parse": int(self.parse_flag or 1), "url": url, "jx": 0}