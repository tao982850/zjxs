#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《遮天法》TVBox / 影视仓 爬虫源 —— 4K电影网（4kdyw.com）

【站点信息】
  名称：4K电影网（站点自称「4K影视站」）
  域名：https://www.4kdyw.com
  类型：影视聚合站（电影 / 电视剧 / 动漫 / 综艺），Nuxt3 前端 + 服务端渲染，
        页面为 .html 伪静态路由（/vodcate/{id}.html、/voddetail/{id}.html、
        /vodplay/{id}-{sid}-{nid}.html、/vodtype/{id}/{page}、/vodsearch/{wd}）

【判站】
  前端是 Nuxt3，SSR 把整页内容渲染进 HTML，同时前端自身调用站点公开的 JSON
  接口 /api/show/v2/*（无鉴权、无签名、无验证码、无登录）。已实测这些接口直连
  可用，返回 code=0 的标准 JSON。按判据属防御等级 1，归「轮海·苦海」境，选
  Python 源形态。HTMX 伪头部、TLS 指纹伪装、盾绕过一概未用。

【六接口】
  homeContent / homeVideoContent / categoryContent / detailContent /
  searchContent / playerContent（另附 localProxy，供 m3u8 分片清洗走本地代理）

【实测与推断分界】
  实测（真实请求已验证）：
    · /api/show/v2/index 返回 4 个一级分类（电影/电视剧/动漫/综艺）及 24 个二级
      分类（typeId 1~24）与各分类最新条目
    · /api/show/v2/type/{typeId}/{page} 列表接口可用，per_page=18，带 total /
      total_page
    · /api/show/v2/vod/{vodId} 详情接口可用，vod_play 为数组，每项含
      collectSource.webName（线路名）与 vodPlayUrl（"剧集名$直链"，用 # 串联）
    · /api/show/v2/search/{wd}/{page} 搜索接口可用（"无间道"实测 19 条）
    · 网页端 /voddetail/{id}.html、/vodplay/{id}-{sid}-{nid}.html 可达；sid =
      vod_play 原始下标 + 1（站点自己的播放组件即 vod_play[Number(sid)-1]），
      nid = 剧集序号 + 1，二者按站点前端源码核对
    · 抽出的 m3u8 直链实测 HTTP 200 且为标准 HLS 清单
  推断（未在真机壳内跑过）：
    · 影视仓 / TVBox 对 24 个二级分类的展示与筛选交互效果
    · 搜索接口对部分片名返回 0 条（站点自身行为），未逐片名穷举
    · m3u8 分片是否含广告需在真机播放时确认，默认不开本地代理
"""

import re
import json
import time
import base64
from urllib import parse as _parse
from urllib import request as _request
from urllib import error as _error

# TVBox / 影视仓 壳内基类；不在壳里时用 object 兜底，保证本文件可独立导入
try:
    from base.spider import Spider as _ShellSpider
except Exception:
    _ShellSpider = object


# ══════════════════════════════════════════════════════════════
# 覆盖配置（接口路径、头部、分类、字段名、播放提取层全部来自这里，
# 代码内不写死路径；不硬编码任何密钥、口令、签名）
# ══════════════════════════════════════════════════════════════
DEFAULT_CONFIG = {
    "name": "4K电影网",
    "host": "https://www.4kdyw.com",
    "backup_hosts": ["https://4kdyw.com"],
    "headers": {
        "User-Agent": ("Mozilla/5.0 (Linux; Android 12; V2304A) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.4kdyw.com/",
        "Origin": "https://www.4kdyw.com",
    },
    # 全部路径集中在此，代码里不写死
    "endpoints": {
        # JSON 接口（站点前端自用，实测公开无鉴权）
        "index": "/api/show/v2/index",
        "cate": "/api/show/v2/cate/{cate_id}",
        "type": "/api/show/v2/type/{type_id}/{page}",
        "vod": "/api/show/v2/vod/{vod_id}",
        "search": "/api/show/v2/search/{wd}/{page}",
        "vodhot": "/api/show/v2/vodhot",
        "uptoday": "/api/show/v2/uptoday",
        # 网页端路由（解析失败时的回退）
        "category": "/vodcate/{cate_id}.html",
        "category_type": "/vodtype/{type_id}/{page}",
        "detail": "/voddetail/{vod_id}.html",
        "play": "/vodplay/{vod_id}-{sid}-{nid}.html",
        "search_page": "/vodsearch/{wd}/{page}",
    },
    # 一级分类（cateId）与二级分类（typeId），站点实测值；运行时会被
    # /api/show/v2/index 的真实数据刷新覆盖，这里只作离线兜底
    "classes": [
        {"type_id": "1", "type_name": "电影", "subtypes": [
            {"type_id": "1", "type_name": "动作片"},
            {"type_id": "2", "type_name": "喜剧片"},
            {"type_id": "3", "type_name": "爱情片"},
            {"type_id": "4", "type_name": "科幻片"},
            {"type_id": "5", "type_name": "恐怖片"},
            {"type_id": "6", "type_name": "剧情片"},
            {"type_id": "7", "type_name": "战争片"},
        ]},
        {"type_id": "2", "type_name": "电视剧", "subtypes": [
            {"type_id": "8", "type_name": "国产剧"},
            {"type_id": "9", "type_name": "香港剧"},
            {"type_id": "10", "type_name": "韩国剧"},
            {"type_id": "11", "type_name": "欧美剧"},
            {"type_id": "12", "type_name": "台湾剧"},
            {"type_id": "13", "type_name": "日本剧"},
            {"type_id": "14", "type_name": "海外剧"},
            {"type_id": "15", "type_name": "泰国剧"},
        ]},
        {"type_id": "3", "type_name": "动漫", "subtypes": [
            {"type_id": "16", "type_name": "国产动漫"},
            {"type_id": "17", "type_name": "日韩动漫"},
            {"type_id": "18", "type_name": "欧美动漫"},
            {"type_id": "19", "type_name": "港台动漫"},
            {"type_id": "20", "type_name": "海外动漫"},
        ]},
        {"type_id": "4", "type_name": "综艺", "subtypes": [
            {"type_id": "21", "type_name": "大陆综艺"},
            {"type_id": "22", "type_name": "港台综艺"},
            {"type_id": "23", "type_name": "日韩综艺"},
            {"type_id": "24", "type_name": "欧美综艺"},
        ]},
    ],
    # 筛选分组名：extend 里用这个 key 带回用户选中的二级分类 typeId
    "filter": {"type_key": "类型"},
    # 字段映射（接口返回的键名全部来自这里）
    "fields": {
        "list": "vod_recent",
        "search_list": "vods",
        "id": "vodId",
        "name": "vodName",
        "pic": "vodPic",
        "remarks": "vodLastRemarks",
        "year": "vodYear",
        "area": "vodArea",
        "lang": "vodLang",
        "class": "vodClass",
        "actor": "vodActor",
        "director": "vodDirector",
        "content": "vodContent",
        "blurb": "vodBlurb",
        "play_list": "vod_play",
        "play_url": "vodPlayUrl",
        "line_name": "webName",
    },
    # 网页端回退用的选择器与正则（不绑 class 名）
    "list": {
        "detail_pattern": r'<a\b[^>]*href=["\']([^"\']*/voddetail/(\d+)\.html)["\']',
        "title_attrs": ["title", "alt"],
        "pic_attrs": ["data-original", "data-src", "data-echo", "src"],
        "remarks_pattern": r'class=["\'][^"\']*pic-text[^"\']*["\'][^>]*>\s*([\s\S]{0,40}?)</',
        "skip_pic": ["/static/", "/template/", "/upload/logo", "/img/icon"],
    },
    "detail": {
        "title_patterns": [
            r'<h1[^>]*>\s*([\s\S]{0,120}?)\s*</h1>',
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
            r'<title>\s*([\s\S]{0,80}?)\s*[-–|]\s*4K影视站',
        ],
        "pic_patterns": [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'class=["\'][^"\']*stui-vodlist__thumb[^"\']*["\'][^>]*>[\s\S]{0,300}?'
            r'(?:data-original|data-src)=["\']([^"\']+)',
        ],
        "content_keys": ["剧情简介", "剧情介绍", "簡介", "简介"],
        "episode_pattern": r'<a\b[^>]*href=["\']([^"\']*/vodplay/(\d+)-(\d+)-(\d+)\.html)["\'][^>]*>([\s\S]{0,80}?)</a>',
        "line_pattern": r'<a\b[^>]*href=["\']#?playlist(\d+)["\'][^>]*>([\s\S]{0,40}?)</a>',
    },
    "play": {
        # 播放 ID 采用站点网页端同款三段式：{vod_id}-{sid}-{nid}
        #   sid = 接口 vod_play 数组原始下标 + 1；nid = 剧集序号 + 1
        "id_pattern": r'^(\d+)-(\d+)-(\d+)$',
        "fallback_line": "线路%d",
        "ep_sep": "#",
        "ep_kv": "$",
    },
    "player_extract": {
        "13_layers": [
            {"name": "正则_m3u8", "pattern": r'["\'](https?://[^"\']+?\.m3u8[^"\']*)["\']'},
            {"name": "正则_mp4", "pattern": r'["\'](https?://[^"\']+?\.mp4[^"\']*)["\']'},
            {"name": "video标签", "pattern": r'<video[^>]+src=["\']([^"\']+)["\']'},
            {"name": "iframe嵌套", "pattern": r'<iframe[^>]+src=["\']([^"\']+)["\']'},
            {"name": "JSON_url字段", "pattern": r'"url"\s*:\s*"([^"]+)"'},
            {"name": "JSON_src字段", "pattern": r'"src"\s*:\s*"([^"]+)"'},
            {"name": "JSON_video字段", "pattern": r'"video"\s*:\s*"([^"]+)"'},
            {"name": "JS变量_player_data", "pattern": r'var\s+player_data\s*=\s*["\']([^"\']+)["\']'},
            {"name": "JS变量_player_aaaa", "pattern": r'player_aaaa\s*=\s*["\']([^"\']+)["\']'},
            {"name": "atob解码", "pattern": r'atob\(["\']([^"\']+)["\']\)'},
            {"name": "base64编码", "pattern": r'data:(video/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]+)'},
            {"name": "自定义函数", "pattern": r'getVideoUrl\(["\']([^"\']+)["\']\)'},
            {"name": "裸m3u8", "pattern": r'(https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*)'},
        ]
    },
    "m3u8": {
        "ad_keywords": ["/ad/", "advert", "gg.", "promo", "guanggao"],
        "ad_line_patterns": [r'#EXT-X-DATERANGE', r'#EXT-X-CUE-OUT', r'#EXT-X-CUE-IN'],
    },
    "player": {
        "use_local_proxy": False,
        "referer_on_play": True,
    },
    "net": {
        "timeout": 15,
        "retry": 2,
        "delay": 0.4,
        "delay_agg": 0.35,
    },
}


class _Resp(object):
    """urllib 兜底请求的最小响应对象，字段与壳内响应对齐。"""

    def __init__(self, content, status=200):
        self.content = content or b""
        self.status_code = status

    @property
    def text(self):
        return self.content.decode("utf-8", "ignore")


def _urllib_fetch(url, headers, timeout):
    """壳外兜底请求：只用标准库，含 gzip 解压。"""
    req = _request.Request(url, headers=headers or {})
    try:
        with _request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                import gzip
                body = gzip.decompress(body)
            return _Resp(body, getattr(r, "status", 200))
    except _error.HTTPError as e:
        return _Resp(b"", getattr(e, "code", 0))
    except Exception as e:
        raise e


class JieJingBase(_ShellSpider):
    """境界基类——六接口契约 + 统一取页（串行、限速、超时、退避重试）。"""

    realm_name = "轮海·苦海"
    realm_level = 1
    defense_level = 1

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.cfg = DEFAULT_CONFIG
        self.siteUrl = self.cfg["host"]
        self.name = self.cfg["name"]
        self.headers = dict(self.cfg["headers"])
        self._index_cache = None
        self._vod_cache = {}

    # ───── 日志（分级，不静默吞异常）─────
    def log(self, msg, level="INFO"):
        try:
            print("[4K电影网][%s] %s" % (level, msg))
        except Exception:
            print("[4K电影网][ERROR] 日志输出失败")

    # ───── 取页 ─────
    def fetch(self, url, headers=None, timeout=None, **kwargs):
        h = dict(self.headers)
        h.update(headers or {})
        timeout = timeout or self.cfg["net"]["timeout"]
        shell_fetch = getattr(super(), "fetch", None)
        if callable(shell_fetch):
            try:
                return shell_fetch(url, headers=h, timeout=timeout, **kwargs)
            except Exception as e:
                self.log("壳内 fetch 失败，回退标准库：%s" % e, "WARN")
        return _urllib_fetch(url, h, timeout)

    def _text(self, resp):
        if resp is None:
            return ""
        content = getattr(resp, "content", None)
        if isinstance(content, (bytes, bytearray)):
            return bytes(content).decode("utf-8", "ignore")
        text = getattr(resp, "text", None)
        return text if isinstance(text, str) else ""

    def _url(self, key, **kw):
        path = self.cfg["endpoints"][key].format(**kw)
        if path.startswith("http"):
            return path
        return self.siteUrl.rstrip("/") + path

    def _get(self, url, referer=None):
        """带重试与退避的取页，失败返回空串而不是抛裸异常。"""
        if not url:
            return ""
        headers = {}
        if referer:
            headers["Referer"] = referer
        retry = max(1, int(self.cfg["net"]["retry"]))
        for i in range(retry):
            try:
                resp = self.fetch(url, headers=headers)
                status = getattr(resp, "status_code", 200)
                text = self._text(resp)
                if status and status >= 400:
                    self.log("HTTP %s %s" % (status, url), "WARN")
                if text:
                    return text
            except Exception as e:
                self.log("请求第 %d 次失败 %s：%s" % (i + 1, url, e), "WARN")
            if i + 1 < retry:
                time.sleep(float(self.cfg["net"]["delay"]))
        return ""

    def _get_json(self, key, **kw):
        """取 JSON 接口；失败返回空字典，不抛异常。"""
        url = self._url(key, **kw)
        text = self._get(url, referer=self.siteUrl.rstrip("/") + "/")
        if not text:
            return {}
        try:
            obj = json.loads(text)
        except ValueError as e:
            self.log("JSON 解析失败 %s：%s" % (url, e), "WARN")
            return {}
        if not isinstance(obj, dict):
            self.log("JSON 结构异常 %s：%s" % (url, type(obj).__name__), "WARN")
            return {}
        if obj.get("code") not in (0, None):
            self.log("接口返回非 0 code %s：%s" % (url, obj.get("msg")), "WARN")
        return obj.get("data") or {}

    # ───── 分类元数据（运行时以接口数据刷新，配置仅作兜底）─────
    def _class_meta(self):
        if self._index_cache:
            return self._index_cache
        data = self._get_json("index")
        metas = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                subs = []
                for t in (item.get("type") or []):
                    if isinstance(t, dict) and t.get("typeId") is not None:
                        subs.append({"type_id": str(t.get("typeId")),
                                     "type_name": str(t.get("typeName") or "")})
                metas.append({
                    "type_id": str(item.get("cateId")),
                    "type_name": str(item.get("cateName") or ""),
                    "subtypes": subs,
                    "recent": item.get(self.cfg["fields"]["list"]) or [],
                })
        if metas:
            self._index_cache = metas
            return metas
        self.log("分类元数据取不到，退回内置配置", "WARN")
        return [{"type_id": c["type_id"], "type_name": c["type_name"],
                 "subtypes": list(c.get("subtypes") or []), "recent": []}
                for c in self.cfg["classes"]]

    def _subtypes(self, cate_id):
        for meta in self._class_meta():
            if meta["type_id"] == str(cate_id):
                return meta.get("subtypes") or []
        return []


class DouZiMi(object):
    """斗字秘·吞天魔罐（解析：清洗、图片修复、正则抽取、列表与详情）"""

    @staticmethod
    def clean_text(raw):
        if raw is None:
            return ""
        s = str(raw)
        try:
            import html as _html
            s = _html.unescape(s)
        except Exception as e:
            print("[4K电影网][WARN] 实体解码失败：%s" % e)
        s = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", s, flags=re.I)
        s = re.sub(r"<br\s*/?>|</p>", " ", s, flags=re.I)
        s = re.sub(r"<[^>]+>", " ", s)
        s = s.replace("\u3000", " ").replace("&nbsp;", " ")
        return re.sub(r"\s+", " ", s).strip()

    @staticmethod
    def fix_pic(url, host="", skip=None):
        """图片地址修复：补协议、补域名、滤掉模板图。"""
        u = (url or "").strip().replace("\\/", "/")
        if not u or u.startswith("data:"):
            return ""
        for bad in (skip or []):
            if bad and bad in u:
                return ""
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        if u.startswith("/"):
            return (host or "").rstrip("/") + u
        return (host or "").rstrip("/") + "/" + u.lstrip("./")

    @staticmethod
    def extract_by_regex(html, patterns):
        """按给定 pattern 列表逐个试，命中即返回首个分组。"""
        for item in patterns or []:
            pattern = item.get("pattern") if isinstance(item, dict) else item
            if not pattern:
                continue
            try:
                m = re.search(pattern, html or "", re.S | re.I)
                if m:
                    val = m.group(1) if m.groups() else m.group(0)
                    if val:
                        return val.strip()
            except Exception as e:
                print("[4K电影网][WARN] 规则 %s 执行失败：%s" % (pattern[:24], e))
        return ""

    @staticmethod
    def vods_from_api(items, config=None):
        """接口列表项 → TVBox 列表项（字段名全部取自配置）。"""
        cfg = config or DEFAULT_CONFIG
        f = cfg["fields"]
        out = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            vid = it.get(f["id"])
            if vid is None:
                continue
            try:
                out.append({
                    "vod_id": str(vid),
                    "vod_name": DouZiMi.clean_text(it.get(f["name"])),
                    "vod_pic": DouZiMi.fix_pic(it.get(f["pic"]), cfg["host"],
                                               cfg["list"]["skip_pic"]),
                    "vod_remarks": DouZiMi.clean_text(it.get(f["remarks"])),
                })
            except Exception as e:
                print("[4K电影网][WARN] 列表项转换失败：%s" % e)
                continue
        return out

    @staticmethod
    def parse_video_list(html, config=None):
        """网页回退解析：以 /voddetail/{id}.html 链接为锚点，在锚标签与其后窗口取值，
        不依赖具体 class 名，模板改版不至于整段失效。"""
        cfg = config or DEFAULT_CONFIG
        lcfg = cfg["list"]
        vods = []
        seen = set()
        if not html:
            return vods
        try:
            matches = list(re.finditer(lcfg["detail_pattern"], html, re.I))
        except Exception as e:
            print("[4K电影网][WARN] 列表锚点匹配失败：%s" % e)
            return vods
        for idx, m in enumerate(matches):
            try:
                vod_url = m.group(1)
                vid = m.group(2)
                if vid in seen:
                    continue
                tag_end = html.find(">", m.start())
                tag = html[m.start():tag_end + 1] if tag_end > 0 else m.group(0)
                nxt = matches[idx + 1].start() if idx + 1 < len(matches) else min(len(html), m.start() + 2000)
                window = html[m.start():nxt]
                title = ""
                for attr in lcfg["title_attrs"]:
                    tm = re.search(r'%s=["\']([^"\']+)["\']' % attr, tag, re.I)
                    if tm:
                        title = DouZiMi.clean_text(tm.group(1))
                        break
                if not title:
                    hm = re.search(r"<h[1-6][^>]*>([\s\S]{0,80}?)</h[1-6]>", window, re.I)
                    title = DouZiMi.clean_text(hm.group(1)) if hm else ""
                if not title:
                    continue
                pic = ""
                for attr in lcfg["pic_attrs"]:
                    pm = re.search(r'%s=["\']([^"\']+)["\']' % re.escape(attr), window, re.I)
                    if pm:
                        pic = DouZiMi.fix_pic(pm.group(1), cfg["host"], lcfg["skip_pic"])
                        if pic:
                            break
                remarks = ""
                rm = re.search(lcfg["remarks_pattern"], window, re.I)
                if rm:
                    remarks = DouZiMi.clean_text(rm.group(1))
                seen.add(vid)
                vods.append({
                    "vod_id": DouZiMi.fix_pic(vod_url, cfg["host"]),
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": remarks,
                })
            except Exception as e:
                print("[4K电影网][WARN] 列表单条解析失败：%s" % e)
                continue
        return vods



    @staticmethod
    def vods_from_api(items, config=None):
        """接口列表项 → TVBox 列表项（字段名全部取自配置）。"""
        cfg = config or DEFAULT_CONFIG
        f = cfg["fields"]
        out = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            vid = it.get(f["id"])
            if vid is None:
                continue
            try:
                out.append({
                    "vod_id": str(vid),
                    "vod_name": DouZiMi.clean_text(it.get(f["name"])),
                    "vod_pic": DouZiMi.fix_pic(it.get(f["pic"]), cfg["host"],
                                               cfg["list"]["skip_pic"]),
                    "vod_remarks": DouZiMi.clean_text(it.get(f["remarks"])),
                })
            except Exception as e:
                print("[4K电影网][WARN] 列表项转换失败：%s" % e)
                continue
        return out


class QianZiMi(object):
    """乾字秘·开天眼（播放解析：13 层策略 + macCMS 式 encrypt 解码 + 线路聚合）"""

    @staticmethod
    def decode_mac(value, encrypt=1):
        """兼容 macCMS player 参数解码：1=urlencode，2=base64+urlencode，3=原串。"""
        v = value or ""
        try:
            if int(encrypt) == 1:
                return _parse.unquote(v)
            if int(encrypt) == 2:
                raw = v.split("|", 1)[0]
                pad = raw + "=" * (-len(raw) % 4)
                return _parse.unquote(base64.b64decode(pad).decode("utf-8", "ignore"))
            if int(encrypt) == 3:
                return v
        except Exception as e:
            print("[4K电影网][WARN] player 参数解码失败(encrypt=%s)：%s" % (encrypt, e))
        return v

    @staticmethod
    def extract_player_url(html, config=None):
        """13 层播放直链提取；取不到返回空串，交由上层回退，不伪造直链。"""
        cfg = config or DEFAULT_CONFIG
        for layer in cfg["player_extract"]["13_layers"]:
            pattern = layer.get("pattern")
            if not pattern:
                continue
            try:
                m = re.search(pattern, html or "", re.S | re.I)
            except Exception as e:
                print("[4K电影网][WARN] 播放层 %s 规则执行失败：%s"
                      % (layer.get("name"), e))
                continue
            if not m:
                continue
            url = (m.group(1) if m.groups() else m.group(0)).strip()
            if not url:
                continue
            if layer.get("name") == "atob解码":
                try:
                    url = base64.b64decode(url + "=" * (-len(url) % 4)).decode("utf-8", "ignore")
                except Exception as e:
                    print("[4K电影网][WARN] atob 解码失败：%s" % e)
                    continue
            if url.startswith("http"):
                return url
        return ""

    @staticmethod
    def split_episodes(play_url, config=None):
        """把 "剧集名$直链#剧集名$直链" 拆成 [(剧集名, 直链)]。"""
        cfg = config or DEFAULT_CONFIG
        sep = cfg["play"]["ep_sep"]
        kv = cfg["play"]["ep_kv"]
        eps = []
        for chunk in (play_url or "").split(sep):
            chunk = (chunk or "").strip()
            if not chunk:
                continue
            if kv in chunk:
                name, _, url = chunk.partition(kv)
            else:
                name, url = "", chunk
            eps.append((name.strip(), url.strip()))
        return eps


    @staticmethod
    def is_media(url):
        """判断是否为可直放的媒体地址。"""
        return bool(re.search(r"\.(?:m3u8|mp4|flv|mkv|avi|ts)(?:\?|#|$)", url or "", re.I))


class JieZiMi(object):
    """界字秘·镇渊印（m3u8 绝对化 + 广告分片清洗）"""

    @staticmethod
    def absolute(url, host=""):
        u = (url or "").strip().replace("\\/", "/")
        if not u:
            return ""
        if u.startswith("http"):
            return u
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("/"):
            return (host or "").rstrip("/") + u
        return u

    @staticmethod
    def clean_m3u8(content, config=None):
        """清洗 m3u8：去掉含广告特征的片段行与广告关键字域名。"""
        cfg = config or DEFAULT_CONFIG
        m = cfg["m3u8"]
        ads = [k.lower() for k in m.get("ad_keywords") or []]
        keep = []
        for line in (content or "").splitlines():
            low = line.lower()
            if any(k and k in low for k in ads):
                continue
            drop = False
            for pat in m.get("ad_line_patterns") or []:
                try:
                    if re.search(pat, line, re.I):
                        drop = True
                        break
                except Exception as e:
                    print("[4K电影网][WARN] 广告规则 %s 执行失败：%s" % (pat, e))
            if drop:
                continue
            keep.append(line)
        return "\n".join(keep)


class Spider(JieJingBase):
    """TVBox / 影视仓 源：六接口 + localProxy。"""

    def getName(self):
        return self.cfg["name"]

    # ───── 壳契约：init 等（壳的 base.spider.Spider 是抽象类，缺 init 无法实例化）─────
    def init(self, extend=""):
        """壳内初始化入口：可用 extend 覆盖域名与请求头；不做网络请求、不抛异常。"""
        try:
            cfg = getattr(self, "cfg", None) or DEFAULT_CONFIG
            headers = getattr(self, "headers", None)
            if not isinstance(headers, dict):
                headers = dict(cfg["headers"])
                self.headers = headers
            site = getattr(self, "siteUrl", None) or cfg["host"]
            conf = {}
            if isinstance(extend, dict):
                conf = extend
            elif isinstance(extend, str) and extend.strip().startswith("{"):
                conf = json.loads(extend)
            elif isinstance(extend, str) and extend.strip().startswith("http"):
                site = extend.strip()
            host = str(conf.get("host") or "").strip()
            if host.startswith("http"):
                site = host
            site = str(site).rstrip("/")
            self.siteUrl = site
            headers["Referer"] = site + "/"
            extra = conf.get("headers")
            if isinstance(extra, dict):
                headers.update(dict((str(k), str(v)) for k, v in extra.items()))
        except Exception as e:
            self.log("init 扩展参数解析失败：%s" % e, "WARN")
        self.log("初始化完成 host=%s realm=%s" % (self.siteUrl, self.realm_name))

    def isVideoFormat(self, url):
        return QianZiMi.is_media(url)

    def manualVideoCheck(self):
        return True

    def action(self, action):
        self.log("action=%s 未使用" % action)
        return None

    def destroy(self):
        return None

    def liveContent(self, url):
        return {"list": [], "url": url}

    # ───── 首页分类 ─────
    def homeContent(self, filter=False):
        try:
            classes = []
            for meta in self._class_meta():
                classes.append({
                    "type_id": meta["type_id"],
                    "type_name": meta["type_name"],
                    "filters": {
                        self.cfg["filter"]["type_key"]: [
                            {"name": s["type_name"], "value": s["type_id"]}
                            for s in (meta.get("subtypes") or [])
                        ],
                    },
                })
            result = {"class": classes}
            if filter:
                result["filters"] = dict((c["type_id"], c["filters"]) for c in classes)
            return result
        except Exception as e:
            self.log("homeContent 异常：%s" % e, "ERROR")
            return {"class": []}

    # ───── 首页推荐 ─────
    def homeVideoContent(self):
        try:
            items = []
            for meta in self._class_meta():
                items.extend(meta.get("recent") or [])
            vods = DouZiMi.vods_from_api(items, self.cfg)
            return {"list": vods}
        except Exception as e:
            self.log("homeVideoContent 异常：%s" % e, "ERROR")
            return {"list": []}

    # ───── 分类列表 ─────
    def categoryContent(self, tid, pg="1", filter=False, extend=None):
        try:
            cate_id = str(tid)
            page = str(pg or "1")
            ext = extend if isinstance(extend, dict) else {}
            key = self.cfg["filter"]["type_key"]
            selected = str(ext.get(key) or "").strip()
            subs = self._subtypes(cate_id)
            f = self.cfg["fields"]

            # 用户在筛选里选中了二级分类：直接走该 typeId，一次请求
            if selected and any(s["type_id"] == selected for s in subs):
                if filter:
                    self.log("分类 %s 使用二级分类 %s" % (cate_id, selected))
                data = self._get_json("type", type_id=selected, page=page)
                vods = DouZiMi.vods_from_api(data.get(f["list"]), self.cfg)
                return {
                    "list": vods,
                    "page": int(data.get("page") or page),
                    "limit": int(data.get("per_page") or 18),
                    "total": int(data.get("total") or len(vods)),
                }

            # 未选二级分类：合并该一级分类下各二级分类
            if not subs:
                self.log("分类 %s 无二级分类，已退回网页端" % cate_id, "WARN")
                html = self._get(self._url("category", cate_id=cate_id))
                vods = DouZiMi.parse_video_list(html, self.cfg)
                return {"list": vods, "page": int(page), "limit": 18, "total": len(vods)}

            merged = []
            total = 0
            for sub in subs:
                if page != "1":
                    time.sleep(float(self.cfg["net"]["delay_agg"]))
                data = self._get_json("type", type_id=sub["type_id"], page=page)
                merged.extend(data.get(f["list"]) or [])
                total += int(data.get("total") or 0)
            vods = DouZiMi.vods_from_api(merged, self.cfg)
            return {
                "list": vods,
                "page": int(page),
                "limit": 18 * max(1, len(subs)),
                "total": total or len(vods),
            }
        except Exception as e:
            self.log("categoryContent 异常：%s" % e, "ERROR")
            return {"list": [], "page": 1, "limit": 18, "total": 0}

    # ───── 详情与播放源 ─────
    def detailContent(self, ids=None):
        try:
            raw = ids[0] if ids else ""
            vid = str(raw).split("#")[0].strip()
            if not vid.isdigit():
                self.log("详情 id 非数字：%s" % raw, "WARN")
                return {"vod": {}}
            data = self._vod_detail(vid)
            if not data:
                return {"vod": {}}
            f = self.cfg["fields"]
            play_from = []
            play_url = []
            for idx, line in enumerate(data.get(f["play_list"]) or []):
                if not isinstance(line, dict):
                    continue
                sid = idx + 1
                eps = QianZiMi.split_episodes(line.get(f["play_url"]), self.cfg)
                if not eps:
                    continue
                name = ""
                src = line.get("collectSource") or {}
                if isinstance(src, dict):
                    name = str(src.get(f["line_name"]) or "")
                if not name:
                    name = self.cfg["play"]["fallback_line"] % sid
                items = []
                for nidx, pair in enumerate(eps):
                    label = pair[0] or ("%02d" % (nidx + 1))
                    items.append("%s$%d-%d-%d" % (label, int(vid), sid, nidx + 1))
                play_from.append(name)
                play_url.append("#".join(items))
            vod = {
                "vod_id": vid,
                "vod_name": DouZiMi.clean_text(data.get(f["name"])),
                "vod_pic": DouZiMi.fix_pic(data.get(f["pic"]), self.cfg["host"],
                                           self.cfg["list"]["skip_pic"]),
                "vod_remarks": DouZiMi.clean_text(data.get(f["remarks"])),
                "vod_year": str(data.get(f["year"]) or ""),
                "vod_area": DouZiMi.clean_text(data.get(f["area"])),
                "vod_lang": DouZiMi.clean_text(data.get(f["lang"])),
                "vod_class": DouZiMi.clean_text(data.get(f["class"])),
                "vod_actor": DouZiMi.clean_text(data.get(f["actor"])),
                "vod_director": DouZiMi.clean_text(data.get(f["director"])),
                "vod_content": DouZiMi.clean_text(data.get(f["content"])
                                                  or data.get(f["blurb"])),
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url),
            }
            return {"vod": vod}
        except Exception as e:
            self.log("detailContent 异常：%s" % e, "ERROR")
            return {"vod": {}}

    def _vod_detail(self, vid):
        """取详情数据：优先接口，失败回退网页端解析。"""
        if vid in self._vod_cache:
            return self._vod_cache[vid]
        data = self._get_json("vod", vod_id=vid)
        if data:
            self._vod_cache[vid] = data
            return data
        self.log("详情接口无数据，回退网页端：%s" % vid, "WARN")
        html = self._get(self._url("detail", vod_id=vid))
        return self._detail_from_html(html, vid)

    def _detail_from_html(self, html, vid):
        """网页端详情回退解析（接口失效时使用）。"""
        try:
            if not html:
                return {}
            d = self.cfg["detail"]
            title = DouZiMi.extract_by_regex(html, d["title_patterns"])
            pic = DouZiMi.extract_by_regex(html, d["pic_patterns"])
            content = ""
            for key in d["content_keys"]:
                idx = html.find(key)
                if idx < 0:
                    continue
                tail = html[idx + len(key):idx + len(key) + 3000]
                stop = re.search(r"猜你喜欢|相关推荐|同类推荐|<div[^>]+class=[\"'][^\"']*"
                                 r"(?:nav|playlist)[^\"']*", tail, re.I)
                if stop:
                    tail = tail[:stop.start()]
                text = DouZiMi.clean_text(tail).lstrip("：:，,、 　-—")
                if len(text) >= 6:
                    content = text
                    break
            eps = {}
            for m in re.finditer(d["episode_pattern"], html, re.I):
                key = "%s-%s" % (m.group(3), m.group(4))
                eps.setdefault(key, []).append(m.group(5))
            return {
                "vodId": vid,
                "vodName": title,
                "vodPic": pic,
                "vodContent": content,
                "vod_play": [],
                "_html_eps": eps,
            }
        except Exception as e:
            self.log("网页详情解析异常：%s" % e, "ERROR")
            return {}

    # ───── 搜索 ─────
    def searchContent(self, key, quick=False, pg="1"):
        try:
            word = (key or "").strip()
            if not word:
                return {"list": [], "page": 1, "limit": 18, "total": 0}
            page = str(pg or "1")
            data = self._get_json("search", wd=_parse.quote(word), page=page)
            f = self.cfg["fields"]
            items = data.get(f["search_list"]) or []
            vods = DouZiMi.vods_from_api(items, self.cfg)
            if quick:
                for v in vods:
                    v.pop("vod_content", None)
            return {
                "list": vods,
                "page": int(data.get("page") or page),
                "limit": int(data.get("page_size") or 18),
                "total": int(data.get("total") or len(vods)),
            }
        except Exception as e:
            self.log("searchContent 异常：%s" % e, "ERROR")
            return {"list": [], "page": 1, "limit": 18, "total": 0}

    # ───── 播放 ─────
    def playerContent(self, flag, id, vipFlags=None):
        try:
            raw = str(id or "").strip()
            m = re.match(self.cfg["play"]["id_pattern"], raw)
            if not m:
                self.log("播放 id 格式不合法：%s" % raw, "WARN")
                return {"parse": 1, "url": raw, "header": self._play_header()}
            vid, sid, nid = int(m.group(1)), int(m.group(2)), int(m.group(3))
            data = self._vod_detail(str(vid))
            f = self.cfg["fields"]
            lines = data.get(f["play_list"]) or []
            url = ""
            if 0 < sid <= len(lines) and isinstance(lines[sid - 1], dict):
                eps = QianZiMi.split_episodes(lines[sid - 1].get(f["play_url"]), self.cfg)
                if 0 < nid <= len(eps):
                    url = JieZiMi.absolute(eps[nid - 1][1], self.cfg["host"])
            if url and url.startswith("http"):
                if vipFlags:
                    self.log("VIP 标记命中，直接返回直链")
                return {"parse": 0, "url": url, "header": self._play_header()}
            # 接口没给直链：回退网页播放页 + 13 层正则
            page_url = self._url("play", vod_id=vid, sid=sid, nid=nid)
            html = self._get(page_url)
            url = QianZiMi.extract_player_url(html, self.cfg)
            if url:
                return {"parse": 0, "url": JieZiMi.absolute(url, self.cfg["host"]),
                        "header": self._play_header()}
            # 交回壳解析，绝不把播放页冒充直链
            self.log("未能取到直链，交回壳解析：%s" % page_url, "WARN")
            return {"parse": 1, "url": page_url, "header": self._play_header()}
        except Exception as e:
            self.log("playerContent 异常：%s" % e, "ERROR")
            return {"parse": 1, "url": str(id or ""), "header": self._play_header()}

    def _play_header(self):
        header = {"User-Agent": self.headers.get("User-Agent", "")}
        if self.cfg["player"].get("referer_on_play"):
            header["Referer"] = self.siteUrl.rstrip("/") + "/"
        return header

    # ───── 本地代理（m3u8 广告清洗用；默认不开）─────
    def localProxy(self, param=""):
        try:
            raw = str(param or "")
            if raw.startswith("http"):
                url = raw
            else:
                qs = _parse.parse_qs(raw)
                url = (qs.get("url") or [""])[0]
            if not url:
                return _Resp(b"", 404)
            if self.cfg["player"].get("use_local_proxy"):
                url = (self.siteUrl.rstrip("/") + "/proxy?do=other&type=m3u8&url="
                       + _parse.quote(url, safe=""))
            resp = self.fetch(url, headers=self._play_header())
            status = getattr(resp, "status_code", 200)
            body = getattr(resp, "content", b"") or b""
            if b"#EXTM3U" in body[:200]:
                text = JieZiMi.clean_m3u8(body.decode("utf-8", "ignore"), self.cfg)
                return _Resp(text.encode("utf-8"), status)
            return _Resp(body, status)
        except Exception as e:
            self.log("localProxy 异常：%s" % e, "ERROR")
            return _Resp(b"", 500)


# ── 壳兼容性兜底：若壳的基类还声明了我们没实现的抽象方法，补一个最小可用实现，
#    避免「Can't instantiate abstract class」导致整个源加载失败；不覆盖已有实现。
def _patch_abstract_gaps(cls):
    try:
        missing = sorted(getattr(cls, "__abstractmethods__", frozenset()) or [])
    except Exception as e:
        print("[4K电影网][WARN] 抽象方法检查失败：%s" % e)
        return
    for name in missing:
        def _stub(self, *args, _name=name, **kwargs):
            try:
                self.log("壳抽象方法 %s 未实现，返回空结果" % _name, "WARN")
            except Exception:
                pass
            if _name in ("homeContent", "homeVideoContent", "categoryContent",
                         "detailContent", "searchContent", "playerContent",
                         "liveContent"):
                return {"list": []}
            if _name == "isVideoFormat":
                return False
            if _name == "manualVideoCheck":
                return True
            return None
        _stub.__name__ = name
        setattr(cls, name, _stub)
    if missing:
        try:
            cls.__abstractmethods__ = frozenset(
                x for x in cls.__abstractmethods__ if x not in missing)
        except Exception as e:
            print("[4K电影网][WARN] 抽象方法清理失败：%s" % e)
        print("[4K电影网][WARN] 已为未实现的壳抽象方法补最小实现：%s" % "、".join(missing))


_patch_abstract_gaps(Spider)


if __name__ == "__main__":
    spider = Spider()
    spider.siteUrl = "https://www.4kdyw.com"
    print("=== homeContent ===")
    print(json.dumps(spider.homeContent(), ensure_ascii=False, indent=2))
    print("=== categoryContent ===")
    print(json.dumps(spider.categoryContent("1", "1", False, {}), ensure_ascii=False, indent=2))
