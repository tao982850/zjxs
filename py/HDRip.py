# -*- coding: utf-8 -*-
"""HD.Rip 全球电视直播 — https://hd.rip/
分类按地区粗分；播放需会话 Cookie hdrip_s
"""
import gzip
import json
import re
import ssl
from http.cookiejar import CookieJar
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

from base.spider import Spider as BaseSpider

_HOST = "https://hd.rip"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 地区关键词（名称匹配）
_REGIONS = [
    ("hk", "香港", r"翡翠|明珠|无线|TVB|Viu|港台|RTHK|香港|凤凰|有线|HOY|Now|J2|珠江"),
    ("tw", "台湾", r"台视|中视|华视|民视|东森|三立|TVBS|纬来|中天|公视|台湾|年代|非凡|八大|卫视中文|ELTA|MOMO"),
    ("cn", "大陆", r"CCTV|中央|卫视|中国|央视|东方|湖南|浙江|江苏|北京|广东|深圳|四川"),
    ("jp", "日本", r"日本|NHK|日剧|富士|朝日|TBS|东京|大阪|MX|BS11"),
    ("kr", "韩国", r"韩国|阿里郎|KBS|SBS|MBC|tvN|朝鲜|EBS"),
    ("sea", "东南亚", r"Astro|马来|新加|泰国|越南|印尼|菲律宾|TV3|Bernama|Channel\s*5|Channel\s*8"),
    ("us", "欧美", r"BBC|CNN|HBO|Fox|Discovery|ESPN|France|Sky|ABC|NBC|CBS|USA|Nat\s*Geo|History"),
]


class Spider(BaseSpider):
    def getName(self):
        return "HDRip"

    def init(self, extend=""):
        self.host = _HOST
        if extend:
            try:
                cfg = json.loads(extend) if isinstance(extend, str) else (extend or {})
                if cfg.get("host"):
                    self.host = str(cfg["host"]).rstrip("/")
            except Exception:
                pass
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE
        self._cj = CookieJar()
        self._opener = build_opener(
            HTTPSHandler(context=self._ctx),
            HTTPCookieProcessor(self._cj),
        )
        self._channels = None  # cached list
        self._session_ok = False

    def homeContent(self, filter):
        classes = [{"type_id": "all", "type_name": "全部"}]
        for tid, name, _ in _REGIONS:
            classes.append({"type_id": tid, "type_name": name})
        classes.append({"type_id": "other", "type_name": "其他"})
        return {"class": classes, "filters": {}}

    def homeVideoContent(self):
        return self.categoryContent("all", 1, False, {})

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        tid = str(tid or "all")
        chs = self._get_channels()
        if tid != "all":
            chs = [c for c in chs if self._region_of(c) == tid]
        # 直播列表一次给齐，分页切片
        limit = 50
        start = (pg - 1) * limit
        chunk = chs[start: start + limit]
        pagecount = max(1, (len(chs) + limit - 1) // limit)
        return {
            "list": [self._item(c) for c in chunk],
            "page": pg,
            "pagecount": pagecount,
            "limit": limit,
            "total": len(chs),
        }

    def searchContent(self, key, quick, pg="1"):
        key = str(key or "").strip().lower()
        chs = self._get_channels()
        if key:
            chs = [
                c for c in chs
                if key in (c.get("name") or "").lower()
                or key in (c.get("intro") or "").lower()
            ]
        return {
            "list": [self._item(c) for c in chs[:100]],
            "page": 1,
            "pagecount": 1,
            "limit": 100,
            "total": len(chs),
        }

    def detailContent(self, ids):
        vid = str(ids[0]).strip()
        ch = self._find(vid)
        if not ch:
            return {"list": []}
        name = ch.get("name") or vid
        pic = ch.get("logo") or ""
        if pic and pic.startswith("/"):
            pic = self.host + pic
        intro = ch.get("intro") or name
        # 详情不预取播放地址（签名有时效），播放时再拉
        return {
            "list": [{
                "vod_id": str(ch.get("id")),
                "vod_name": name,
                "vod_pic": pic,
                "vod_content": intro,
                "vod_remarks": "直播",
                "vod_play_from": "HD.Rip",
                "vod_play_url": "直播$%s" % ch.get("id"),
            }]
        }

    def playerContent(self, flag, id, vipFlags):
        headers = {
            "User-Agent": _UA,
            "Referer": self.host + "/",
            "Origin": self.host,
        }
        hstr = json.dumps(headers, ensure_ascii=False)
        cid = str(id).strip()
        url = self._play_url(cid)
        return {
            "parse": 0,
            "jx": 0,
            "url": url or "",
            "header": hstr,
        }

    def isVideoFormat(self, url):
        return bool(url) and re.search(r"\.(m3u8|mp4)(\?|$)", str(url), re.I)

    def manualVideoCheck(self):
        return False

    # ------------------------------------------------------------------
    def _item(self, c):
        pic = c.get("logo") or ""
        if pic.startswith("/"):
            pic = self.host + pic
        return {
            "vod_id": str(c.get("id")),
            "vod_name": c.get("name") or str(c.get("id")),
            "vod_pic": pic,
            "vod_remarks": "直播" if c.get("ok") else "",
        }

    def _region_of(self, c):
        name = c.get("name") or ""
        for tid, _n, pat in _REGIONS:
            if re.search(pat, name, re.I):
                return tid
        return "other"

    def _find(self, vid):
        for c in self._get_channels():
            if str(c.get("id")) == str(vid):
                return c
        return None

    def _ensure_session(self):
        if self._session_ok:
            return
        try:
            self._get("/")
            self._session_ok = True
        except Exception as e:
            print("[HDRip] session", e)

    def _get_channels(self):
        if self._channels is not None:
            return self._channels
        self._ensure_session()
        try:
            raw = self._get("/api/config.php")
            cfg = json.loads(raw)
            offline = set(str(x) for x in (cfg.get("offline_ids") or []))
            chs = []
            for c in (cfg.get("channels") or []):
                if not isinstance(c, dict):
                    continue
                if str(c.get("id")) in offline:
                    continue
                if c.get("ok") not in (1, "1", True, None):
                    # ok=0 仍展示，备注即可
                    pass
                chs.append(c)
            self._channels = chs
        except Exception as e:
            print("[HDRip] config", e)
            self._channels = []
        return self._channels

    def _play_url(self, cid):
        self._ensure_session()
        try:
            raw = self._get("/api/play.php?id=" + quote(str(cid)))
            data = json.loads(raw)
            if data.get("error"):
                # 会话失效，刷新后再试一次
                self._session_ok = False
                self._cj.clear()
                self._ensure_session()
                raw = self._get("/api/play.php?id=" + quote(str(cid)))
                data = json.loads(raw)
            return (data.get("url") or "").strip()
        except Exception as e:
            print("[HDRip] play", e)
            return ""

    def _get(self, path):
        url = path if str(path).startswith("http") else (self.host + path)
        headers = {
            "User-Agent": _UA,
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Referer": self.host + "/",
            "Origin": self.host,
        }
        req = Request(url, headers=headers)
        with self._opener.open(req, timeout=20) as r:
            raw = r.read()
            if len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B:
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", "ignore")
