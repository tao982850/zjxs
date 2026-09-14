#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# TVBox Python 爬虫 · 策驰影院 (www.liuhaiwenhua.com)
# ------------------------------------------------------------
# 路由: 分类 /vodtype/{slug}/            ← 主路
#       备路 /vodshow/{11段}/page/{n}/
#       详情 /cechi/{slug}/
#       播放 /cechiyingshi/{slug}-{sid}-{nid}/
#       搜索 /vodsearch/-------------/?wd={kw}&page={pg}
# 风控: GoEdge WAF → okhttp/4.9.3 UA 绕过
# 播放: player_aaaa.url 或 var now="m3u8..." 或 iframe src → parse=0
# 海报: _fix_pic() 统一补全相对路径 + 过滤占位图 + 解码实体
# 依赖: 无 (纯 urllib)
# ------------------------------------------------------------
# v1.1 修复「详情页没有数据」:
#   · 旧版用 href="#playlist{n}" + id="playlist{n}" 解析线路，
#     与实际 HTML 完全不符 → vod_play_from/vod_play_url 全空。
#   · 实际结构: 每条线路一个 <div class="stui-pannel-box b playlist">，
#     内含 <h3 class="title">线路名</h3> +
#     <ul class="stui-content__playlist"><li><a href="/cechiyingshi/xxx-1-1/">集名</a></li></ul>
#   · 新增 _parse_play_lines() 按 pannel 块切分，
#     过滤 /rss/button 广告与 javascript: 伪链接。
#   · 播放路径前缀 /cechiyingshi/ 保留原样，_play_url 不再硬拼 /cechi/。
#   · 年份正则补齐: 实际为 <span class="text-muted">年份：</span><a>2026</a>。
# v1.2 修复「主分类不支持翻页」:
#   · 实测: /vodtype/{slug}/page/N/ 服务端忽略 page 参数，返回与 page 1
#     完全相同的 HTML（title 从"第1页"变"第2页"但卡片一字不差）；
#     /vodshow/{11段}/page/N/ 全 404。→ 服务端从架构上不支持分页。
#   · 方案: 顶频道 hub 页内含 ~13 个「最新 X 片」分区，一次抓完整站分类页
#     数据（~146 卡），分类翻页走客户端切片。
#   · 新增 _parse_hub_sections() + _hub_sections/_hub_all_cards/
#     _hub_cards_by_slug，只改 categoryContent 一处，其它不改动。
# v1.3 修复「搜索不可用」:
#   · 旧 _warmup_cookies 一旦有 Cookie 就不再刷新，WAF 换会话即永久失效。
#   · _page 遇 WAF 只在 cookie==0 时预热 → 有 cookie 被拦时不刷新、不重试。
#   · 修复: _warmup_cookies(force=True) 强刷；_page 清 jar 后强制预热重试。
#   · searchContentPage 增加 4 条搜索路径轮询 + 命中判定 + 主动预热。
#   · _cards_search 增加宽松兜底（class 变体时按 /cechi/ + img 抓取）。
# ============================================================
import sys
try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object

import os
import re
import io
import json
import time
import gzip
import ssl
import socket
import threading
import http.cookiejar
import urllib.request
import urllib.parse
import html as _html

UA = "okhttp/4.9.3"
REFERER = "https://www.liuhaiwenhua.com/"
DOMAINS = ["https://www.liuhaiwenhua.com"]
PAGE_SIZE = 24
T_PAGE = 8.0
HTML_TTL = 180
DETAIL_TTL = 300
PLAY_TTL = 600
HOME_TTL = 240
DOMAIN_TTL = 30 * 60
COOLDOWN = 20

socket.setdefaulttimeout(T_PAGE)
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE
_SEMA = threading.BoundedSemaphore(6)

# ★ 模块级 Cookie Jar: WAF 验证码页绕过策略
# 访问 /vodtype/dianying/ 时会返回真实页面 + Set-Cookie(session),
# 后续搜索/详情/分类请求带上该 Cookie 即绕过验证码页面。
_COOKIES = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=_SSL),
    urllib.request.HTTPCookieProcessor(_COOKIES),
)

# ---------------- 分类体系 ----------------
TOP = [("dianying", "电影"), ("lianxuju", "电视剧"), ("zongyi", "综艺"),
       ("dongman", "动漫"), ("duanju", "短剧")]
TOP_IDS = set(t for t, _ in TOP)

SUBS = {
    "dianying": [
        ("dongzuopian", "动作片"), ("aiqingpian", "爱情片"),
        ("kehuanpian", "科幻片"), ("kongbupian", "恐怖片"),
        ("zhanzhengpian", "战争片"), ("xijupian", "喜剧片"),
        ("jilupian", "纪录片"), ("juqingpian", "剧情片"),
        ("xuannianpian", "悬疑片"), ("fanzuipian", "犯罪片"),
    ],
    "lianxuju": [
        ("guochanju", "国产剧"), ("gangju", "港剧"),
        ("oumeiju", "欧美剧"), ("hanju", "韩剧"),
        ("taiwanju", "台湾剧"), ("ribenju", "日本剧"),
        ("haiwaiju", "海外剧"), ("taiju", "泰剧"),
    ],
    "zongyi": [
        ("guochanzongyi", "国产综艺"), ("rihanzongyi", "日韩综艺"),
        ("gangtaizongyi", "港台综艺"), ("oumeizongyi", "欧美综艺"),
    ],
    "dongman": [
        ("guochandongman", "国产动漫"), ("rihandongman", "日韩动漫"),
        ("oumeidongman", "欧美动漫"), ("dongmandianying", "动漫电影"),
        ("gangtaidongman", "港台动漫"), ("haiwaidongman", "海外动漫"),
    ],
    "duanju": [
        ("nvfenailian", "女频恋爱"), ("fanzhuanshuangju", "反转爽剧"),
        ("naodongxuanyi", "脑洞悬疑"), ("niandaichuanyue", "年代穿越"),
        ("guzhuangxianxia", "古装仙侠"), ("xiandaidushi", "现代都市"),
        ("shuangwenduanju", "爽文短剧"),
    ],
}

AREAS = ["大陆", "香港", "台湾", "日本", "韩国", "欧美", "泰国", "其他"]
YEARS = ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019",
         "2018", "2017", "2016", "2015", "2014", "2013"]
ORDERS = [("time", "最新"), ("hits", "最热"), ("score", "评分")]

# ---------------- HTTP 层 ----------------
_HTML_CACHE = {}
_LOCK = threading.Lock()
_BASE = {"url": "", "ok_ts": 0.0}
_BASE_LOCK = threading.Lock()
_FAIL_TS = 0.0
_CACHE_FILE = None


def _pick_cache_file():
    import tempfile
    for d in (tempfile.gettempdir(), os.getcwd(), "/tmp",
              "/storage/emulated/0/Download"):
        try:
            p = os.path.join(d, ".cechi_domains.json")
            with open(p, "a", encoding="utf-8"):
                pass
            return p
        except Exception:
            continue
    return ""


_CACHE_FILE = _pick_cache_file()


def _load_domain_cache():
    try:
        if _CACHE_FILE and os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                j = json.loads(f.read() or "{}")
            base = str(j.get("base") or "")
            ts = float(j.get("ts") or 0)
            extra = [d for d in (j.get("domains") or []) if d not in DOMAINS]
            if extra:
                DOMAINS.extend(extra)
            if base and time.time() - ts < DOMAIN_TTL:
                _BASE["url"] = base
                _BASE["ok_ts"] = ts
    except Exception:
        pass


def _save_domain_cache():
    try:
        if _CACHE_FILE:
            with open(_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"base": _BASE["url"], "ts": _BASE["ok_ts"],
                           "domains": DOMAINS}, f, ensure_ascii=False)
    except Exception:
        pass


_DOM_RE = re.compile(
    r"(?:https?://)?(?:[a-zA-Z0-9-]+\.){1,3}(?:liuhaiwenhua|231727)"
    r"[a-zA-Z0-9.-]*\.[a-zA-Z]{2,6}", re.I)


def _raw_get(url, timeout=T_PAGE):
    H = {"User-Agent": UA,
         "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
         "Accept-Language": "zh-CN,zh;q=0.9",
         "Accept-Encoding": "gzip",
         "Connection": "close",
         "Referer": REFERER}
    with _SEMA:
        req = urllib.request.Request(url, headers=H)
        r = _OPENER.open(req, timeout=timeout)
        raw = r.read()
        try:
            r.close()
        except Exception:
            pass
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        except Exception:
            pass
    return raw.decode("utf-8", "ignore")


def _cookies_count():
    try:
        return len(list(_COOKIES))
    except Exception:
        return 0


def _warmup_cookies(base=None, path="/vodtype/dianying/", force=False):
    """主动访问一个已知真实页面以获取 Set-Cookie(session)，
    后续请求复用该 Cookie 绕过 WAF 验证码页。
    force=True 时即使已有 Cookie 也强制重新获取（清空旧会话）。"""
    try:
        if not force and _cookies_count() > 0:
            return True
        if not base:
            base = _BASE.get("url") or DOMAINS[0]
        if not base:
            return False
        if force:
            try:
                _COOKIES.clear()
            except Exception:
                pass
        _raw_get(base.rstrip("/") + path, timeout=6.0)
        return _cookies_count() > 0
    except Exception:
        return False


def _probe_ok(url):
    try:
        t = _raw_get(url + "/vodtype/dianying/", timeout=3.0)
        return ("策驰影院" in t) or ("cechi" in t) or ("stui-vodlist" in t)
    except Exception:
        return False


def _discover_domains():
    try:
        t = _raw_get(DOMAINS[0] + "/vodtype/dianying/", timeout=3.0)
        found = []
        for m in re.finditer(r'"url"\s*:\s*"([^"]+)"', t):
            d = m.group(1).strip()
            if not d.startswith("http"):
                d = "https://" + d
            d = d.rstrip("/")
            if d not in DOMAINS and d not in found:
                found.append(d)
        for m in _DOM_RE.finditer(t):
            d = m.group(0)
            if not d.startswith("http"):
                d = "https://" + d
            d = d.rstrip("/")
            if d not in DOMAINS and d not in found:
                found.append(d)
        if found:
            with _LOCK:
                for d in found:
                    if len(DOMAINS) < 8:
                        DOMAINS.append(d)
                _save_domain_cache()
    except Exception:
        pass


def _ensure_base(block=True):
    global _FAIL_TS
    now = time.time()
    if _BASE["url"] and now - _BASE["ok_ts"] < DOMAIN_TTL:
        return _BASE["url"]
    if now - _FAIL_TS < COOLDOWN:
        return _BASE["url"] or DOMAINS[0]
    if not block:
        return _BASE["url"] or DOMAINS[0]
    with _BASE_LOCK:
        now = time.time()
        if _BASE["url"] and now - _BASE["ok_ts"] < DOMAIN_TTL:
            return _BASE["url"]
        if now - _FAIL_TS < COOLDOWN:
            return _BASE["url"] or DOMAINS[0]
        for c in list(DOMAINS):
            if _probe_ok(c):
                _BASE["url"] = c
                _BASE["ok_ts"] = time.time()
                _save_domain_cache()
                if len(DOMAINS) < 5:
                    threading.Thread(target=_discover_domains,
                                     daemon=True).start()
                return c
        _FAIL_TS = time.time()
    return _BASE["url"] or DOMAINS[0]


def _is_waf(html):
    if not html:
        return True
    return ("Verify Yourself" in html or "GOEDGE_WAF" in html
            or "身份验证" in html or "captcha-form" in html
            or "Input verify code" in html
            or (len(html) < 3000 and "GOEDGE" in html))


def _page(url, timeout=T_PAGE):
    """请求页面，遇 WAF 验证码页时刷新 Cookie 再重试"""
    for i in range(3):
        base = _ensure_base(block=(i > 0))
        u = url if url.startswith("http") else base + url
        try:
            t = _raw_get(u, timeout=timeout)
            if t and not _is_waf(t):
                return t
            # ★ 命中 WAF 验证码页 → 刷新 Cookie 再重试
            if t and _is_waf(t):
                try:
                    if i == 0 and _cookies_count() == 0:
                        _warmup_cookies(base)
                    else:
                        # 已有 Cookie 仍被拦截 → 清掉重新获取
                        _warmup_cookies(base, force=True)
                except Exception:
                    pass
        except Exception:
            pass
        with _LOCK:
            if _BASE["url"] and u.startswith(_BASE["url"]):
                _BASE["url"] = ""
                _BASE["ok_ts"] = 0.0
        time.sleep(0.05 if i == 0 else 0.1)
    return ""


def _cat_page(url, timeout=T_PAGE):
    """分类页专用：尝试所有已知域名，返回 (html, ok)"""
    for base in ([_BASE["url"] or DOMAINS[0]] if url.startswith("http")
                 else list(DOMAINS)):
        u = url if url.startswith("http") else base + url
        try:
            t = _raw_get(u, timeout=timeout)
        except Exception:
            continue
        if not t:
            continue
        if _is_waf(t):
            continue
        # 分类页判定: 必须命中 stui 模板
        if "stui-vodlist" not in t:
            continue
        # 404 fallback 页面特征: title 是站名 + 出现"电影大全"
        if ("最新电视剧" in t[:2000] and "电影大全" in t[:2000]
                and "vodshow" not in url):
            continue
        return t, True
    return "", False


def _cached_page(url, ttl=HTML_TTL):
    now = time.time()
    with _LOCK:
        c = _HTML_CACHE.get(url)
        if c and now - c[0] < ttl:
            return c[1]
        while len(_HTML_CACHE) > 64:
            old = min(_HTML_CACHE.items(), key=lambda kv: kv[1][0])[0]
            _HTML_CACHE.pop(old, None)
    t = _page(url)
    if t:
        with _LOCK:
            _HTML_CACHE[url] = (time.time(), t)
    return t


# ---------------- 解析层 ----------------
_TAG = re.compile(r"<[^>]+>")


def _strip(s):
    return _html.unescape(_TAG.sub("", s or "")).strip()

def _clean_name(s):
    s = _strip(s).replace("\u00a0", " ").strip()
    while s.endswith("/"):
        s = s[:-1].strip()
    return s


# ★ 海报 URL 统一处理: 补相对路径 / 协议相对 / 过滤占位图 / 解码实体
_PIC_PLACEHOLDER = ("load.png", "load_f", "load.gif", "placeholder",
                    "blank.gif", "nopic", "no_pic", "default.jpg",
                    "loading.", "grey.gif", "0.gif")


def _fix_pic(p):
    """把海报字段标准化为可加载的完整 URL; 无效返回空串"""
    if not p:
        return ""
    p = p.strip()
    p = _html.unescape(p.strip())
    p = p.strip().strip('"').strip("'")
    if not p:
        return ""
    low = p.lower()
    if low.startswith("data:"):
        return ""
    if any(x in low for x in _PIC_PLACEHOLDER):
        return ""
    if p.startswith("//"):
        return "https:" + p
    if low.startswith(("http://", "https://")):
        return p
    base = (_BASE.get("url") or DOMAINS[0]).rstrip("/")
    if p.startswith("/"):
        return base + p
    return base + "/" + p


def _cards_stui(html):
    out, seen = [], set()
    for m in re.finditer(
        r'<a[^>]*class="[^"]*stui-vodlist__thumb[^"]*"[^>]*>(.*?)</a>',
        html, re.S):
        inner = m.group(0)
        hm = re.search(r'href="(/cechi/([^/]+)/?)"', inner)
        if not hm:
            continue
        slug = hm.group(2)
        if not slug or slug in seen:
            continue
        tm = re.search(r'title="([^"]*)"', inner)
        name = _clean_name(tm.group(1)) if tm else ""
        raw_pic = ""
        for pat in (r'data-original="([^"]+)"',
                    r'data-src="([^"]+)"',
                    r'src="([^"]+)"'):
            pm = re.search(pat, inner)
            if pm and pm.group(1).strip():
                raw_pic = pm.group(1)
                if _fix_pic(raw_pic):
                    break
        pic = _fix_pic(raw_pic)
        rm = re.search(r'pic-text[^>]*>([^<]*)</span>', inner)
        remarks = _strip(rm.group(1)) if rm else ""
        seen.add(slug)
        out.append({"vod_id": slug, "vod_name": name,
                    "vod_pic": pic, "vod_remarks": remarks})
    return out


def _cards_search(html):
    """搜索结果解析：优先标准 stui 卡片；匹配不到时启用宽松兜底"""
    if not html:
        return []
    cards = _cards_stui(html)
    if cards:
        return cards
    # 兜底：某些搜索模板 class 不同，按 /cechi/{slug}/ + <img> 宽松抓取
    out, seen = [], set()
    for m in re.finditer(
        r'<a[^>]*href="(?:[^"]*?)/cechi/([^/"?]+)/?"[^>]*>(.*?)</a>',
        html, re.S):
        slug = m.group(1)
        if not slug or slug in seen:
            continue
        full = m.group(0)
        if "<img" not in full:
            continue
        tm = re.search(r'title="([^"]*)"', full)
        name = _clean_name(tm.group(1)) if tm else ""
        if not name:
            name = _clean_name(re.sub(r"<[^>]+>", " ", m.group(2)))
        if not name or len(name) > 80:
            continue
        raw_pic = ""
        for pat in (r'data-original="([^"]+)"',
                    r'data-src="([^"]+)"',
                    r'src="([^"]+)"'):
            pm = re.search(pat, full)
            if pm and pm.group(1).strip():
                raw_pic = pm.group(1)
                if _fix_pic(raw_pic):
                    break
        pic = _fix_pic(raw_pic)
        rm = re.search(r'pic-text[^>]*>([^<]*)</span>', full)
        remarks = _strip(rm.group(1)) if rm else ""
        seen.add(slug)
        out.append({"vod_id": slug, "vod_name": name,
                    "vod_pic": pic, "vod_remarks": remarks})
    return out


def _pagecount_stui(html):
    for m in re.finditer(r'href="([^"]+)"[^>]*>\s*尾页', html):
        u = m.group(1)
        mm = re.search(r'/page/(\d+)/?', u)
        if mm:
            return max(1, int(mm.group(1)))
    nums = re.findall(r'/page/(\d+)/?', html)
    if nums:
        return max(1, max(int(n) for n in nums if n.isdigit()))
    return 1


def _parse_hub_sections(html):
    """顶频道 hub 页分区解析: 用 <h3 class="title">X片</h3> 作分区边界"""
    if not html:
        return []
    marks = []
    for m in re.finditer(
        r'<h3[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h3>', html, re.S):
        nm = _clean_name(re.sub(r"<[^>]+>", " ", m.group(1)))
        if nm:
            marks.append((m.start(), nm))
    if not marks:
        return []
    foot = html.find("<!--footer")
    if foot <= 0:
        foot = html.find("<footer")
    if foot <= 0:
        foot = len(html)
    out = []
    for i, (pos, nm) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else foot
        if pos > foot:
            continue
        end = min(end, foot)
        cards = _cards_stui(html[pos:end])
        if cards:
            out.append((nm, cards))
    return out


def _dedupe_cards(cards):
    out = []
    sid, snm, spic = set(), set(), set()
    for c in cards:
        vid = str(c.get("vod_id") or "")
        if not vid or vid in sid:
            continue
        nm = re.sub(r"[\s/\-·~]+", "", (c.get("vod_name") or "")).lower()
        pic = (c.get("vod_pic") or "").strip()
        if nm and nm in snm:
            continue
        if pic and pic in spic:
            continue
        sid.add(vid)
        if nm:
            snm.add(nm)
        if pic:
            spic.add(pic)
        out.append(c)
    return out


# ★ 播放线路解析: 按 stui-pannel-box b playlist 块切分
# 真实 HTML 结构:
#   <div class="stui-pannel-box b playlist mb">
#     <div class="stui-pannel_hd">
#       <h3 class="title"><img src="..."/>线路名</h3>
#     </div>
#     <div class="stui-pannel_bd">
#       <ul class="stui-content__playlist clearfix">
#         <li><a href="/rss/button?..." rel="nofollow">1❤1播</a></li>    ← 广告
#         <li><a href="/rss/button?..." rel="nofollow">app免费</a></li>   ← 广告
#         <li ><a href="/cechiyingshi/xxx-1-1/">TC中字</a></li>           ← 真实集
#         <li ><a href="/cechiyingshi/xxx-1-2/">第02集</a></li>
#       </ul>
#     </div>
#   </div>
_RE_BOX_START = re.compile(r'<div[^>]*class="stui-pannel-box b playlist[^"]*"')
_RE_H3_TITLE = re.compile(r'<h3[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h3>',
                          re.S)
_RE_PLAY_UL = re.compile(
    r'<ul[^>]*class="[^"]*stui-content__playlist[^"]*"[^>]*>(.*?)</ul>', re.S)
_RE_PLAY_A = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_IMGS = re.compile(r"<img[^>]*>", re.I)

# 需要过滤的伪集名/广告链接
_AD_HREF_KEYS = ("/rss/button", "/rss/", "/topic/", "javascript:",
                 "#", "http://ads", "https://ads")


def _is_ad_play(href):
    h = (href or "").lower().strip()
    if not h or not h.startswith("/"):
        return True
    if any(k in h for k in _AD_HREF_KEYS if k != "#"):
        return True
    if h.startswith("/rss"):
        return True
    return False


def _parse_play_lines(html):
    """返回 [(线路名, [(href, 集名), ...]), ...]"""
    if not html:
        return []
    starts = [m.start() for m in _RE_BOX_START.finditer(html)]
    if not starts:
        return []
    lines = []
    for i, st in enumerate(starts):
        en = starts[i + 1] if i + 1 < len(starts) else len(html)
        # 边界：到 #desc 详情简介块之前
        d = html.find('id="desc"', st)
        if d != -1 and d < en:
            en = d
        seg = html[st:en]

        # 线路名: h3 > title（去掉 img 标签）
        nm = ""
        tm = _RE_H3_TITLE.search(seg)
        if tm:
            nm = _clean_name(_IMGS.sub("", tm.group(1)))
        if not nm:
            nm = "线路%d" % (i + 1)

        # 集列表: ul.stui-content__playlist
        eps = []
        ulm = _RE_PLAY_UL.search(seg)
        scope = ulm.group(1) if ulm else seg
        for am in _RE_PLAY_A.finditer(scope):
            href = (am.group(1) or "").strip()
            name = _clean_name(am.group(2))
            if _is_ad_play(href):
                continue
            eps.append((href, name))
        if eps:
            lines.append((nm, eps))
    return lines


def _parse_detail(html, vid):
    v = {"vod_name": "", "vod_pic": "", "type_name": "", "vod_year": "",
         "vod_area": "", "vod_remarks": "", "vod_actor": "", "vod_director": "",
         "vod_content": "", "vod_score": "", "lines": []}

    # 标题: <h1 class="title">名<span class="score ...">3.0</span></h1>
    m = re.search(r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h1>', html, re.S)
    if m:
        h1raw = re.sub(r'<span[^>]*class="[^"]*score[^"]*"[^>]*>.*?</span>',
                       '', m.group(1), flags=re.S)
        v["vod_name"] = _clean_name(
            re.sub(r"<[^>]+>", " ", h1raw).replace("\u00a0", " ").strip())
    if not v["vod_name"]:
        m = re.search(r'<title>([^<]+)</title>', html)
        if m:
            parts = m.group(1).split("-")
            v["vod_name"] = _clean_name(
                (parts[0] if parts else "").replace("详情介绍", "").strip())

    # 海报: og:image → 详情页 img data-original → data-src → src
    raw_pic = ""
    m = re.search(r'property="og:image"\s+content="([^"]+)"', html)
    if m:
        raw_pic = m.group(1)
    if not _fix_pic(raw_pic):
        # 详情页主图: <div class="stui-content__thumb">...<img class="lazyload" data-original="...">
        m = re.search(r'stui-content__thumb.*?data-original="([^"]+)"',
                      html, re.S)
        if m:
            raw_pic = m.group(1)
    if not _fix_pic(raw_pic):
        m = re.search(r'data-original="([^"]+)"', html)
        if m:
            raw_pic = m.group(1)
    if not _fix_pic(raw_pic):
        m = re.search(r'class="[^"]*pic[^"]*"[^>]*>\s*<img[^>]*src="([^"]+)"',
                      html, re.S)
        if m:
            raw_pic = m.group(1)
    v["vod_pic"] = _fix_pic(raw_pic)

    # 简介: 优先 <p class="desc ...">...</p>；退到 og:description / meta description
    m = re.search(r'<p[^>]*class="[^"]*desc[^"]*"[^>]*>(.*?)</p>', html, re.S)
    if m:
        intro = _strip(m.group(1))
        intro = re.sub(r"详情\s*$", "", intro).strip()
        if intro:
            v["vod_content"] = intro
    if not v["vod_content"]:
        m = re.search(r'property="og:description"\s+content="([^"]+)"', html)
        if not m:
            m = re.search(r'name="description"\s+content="([^"]+)"', html)
        if m:
            v["vod_content"] = _strip(m.group(1))
            v["vod_content"] = re.sub(
                r"^[^:：]*(剧情|简介)[:：]?\s*", "", v["vod_content"]).strip()

    # 类型: <span class="text-muted">类型：</span><a>动作</a>
    m = re.search(r'类型[：:]\s*</span>\s*<a[^>]*>([^<]+)</a>', html)
    if m:
        v["type_name"] = _strip(m.group(1))

    # 地区
    m = re.search(r'地区[：:]\s*</span>\s*<a[^>]*>([^<]+)</a>', html)
    if m:
        v["vod_area"] = _strip(m.group(1))

    # 年份: 首选 <span>年份：</span><a>2026</a>，退到标题里的 (2026)
    m = re.search(r'年份[：:]\s*</span>\s*<a[^>]*>([^<]+)</a>', html)
    if m:
        y = _strip(m.group(1))
        if re.search(r"\d{4}", y):
            v["vod_year"] = re.search(r"\d{4}", y).group(0)
    if not v["vod_year"]:
        m = re.search(r'[（(]\s*(\d{4})\s*[）)]', html)
        if m:
            v["vod_year"] = m.group(1)

    # 主演 / 导演
    m = re.search(r'主演[：:]\s*</span>\s*(.*?)(?:</p>|<br|</li)', html, re.S)
    if m:
        v["vod_actor"] = _strip(m.group(1))
    m = re.search(r'导演[：:]\s*</span>\s*(.*?)(?:</p>|<br|</li)', html, re.S)
    if m:
        v["vod_director"] = _strip(m.group(1))
    if not v["vod_actor"]:
        m = re.search(r'主演[：:]\s*([^<\n]{2,200})', html)
        if m:
            v["vod_actor"] = _strip(m.group(1))
    if not v["vod_director"]:
        m = re.search(r'导演[：:]\s*([^<\n]{2,100})', html)
        if m:
            v["vod_director"] = _strip(m.group(1))

    # 更新备注: <span>更新：</span>2026-09-10
    m = re.search(r'更新[：:]\s*</span>\s*([\d\-]{6,12})', html)
    if m:
        v["vod_remarks"] = m.group(1)
    if not v["vod_remarks"]:
        m = re.search(r'pic-text[^>]*>\s*([^<]+)<', html)
        if m:
            v["vod_remarks"] = _strip(m.group(1))

    # 评分: <span class="score text-red">3.0</span>
    m = re.search(r'class="[^"]*score[^"]*"[^>]*>\s*([\d.]+)', html)
    if m:
        v["vod_score"] = m.group(1)

    # 播放线路
    v["lines"] = _parse_play_lines(html)
    return v


def _norm_play_path(url):
    """把播放页 href 转成可传给 _play_url 的相对路径"""
    if not url:
        return ""
    u = url.strip()
    if u.startswith("http://") or u.startswith("https://"):
        u = urllib.parse.urlparse(u).path
    u = u.lstrip("/")
    return u


def _play_url(path):
    key = "play:" + path
    now = time.time()
    with _LOCK:
        c = _HTML_CACHE.get(key)
        if c and now - c[0] < PLAY_TTL:
            return c[1]
    # 真实前缀 /cechiyingshi/... ；不再硬拼 /cechi/
    rel = "/" + path if not path.startswith("/") else path
    html = _page(rel)
    if not html:
        # 兜底：尝试剥前缀再试
        alt = re.sub(r"^cechiyingshi/", "cechi/", rel.lstrip("/"))
        if alt != rel:
            html = _page(alt)
    if not html:
        return ""
    url = ""
    m = re.search(r'player_aaaa\s*=\s*', html)
    if m:
        seg = html[m.end():m.end()+4000]
        # 主路径：正则直抽 "url":"..."（可穿越 vod_data 嵌套子对象）
        mu = re.search(r'"url"\s*:\s*"([^"]+)"', seg)
        if mu:
            url = mu.group(1).replace("\\/", "/").strip()
        # 兜底：括号配对取最外层 {...} 再 json.loads
        if not url:
            start = seg.find("{")
            if start >= 0:
                depth = 0
                end = -1
                for i in range(start, len(seg)):
                    if seg[i] == "{":
                        depth += 1
                    elif seg[i] == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if end > 0:
                    try:
                        j = json.loads(seg[start:end])
                        url = (j.get("url") or "").strip().replace("\\/", "/")
                    except Exception:
                        pass
    if not url:
        m = re.search(r'var\s+now\s*=\s*"([^"]+)"', html)
        if m:
            url = m.group(1).strip()
    if not url:
        m = re.search(r'var\s+now\s*=\s*' + chr(39) + r'([^"]+)' + chr(39), html)
        if m:
            url = m.group(1).strip()
    if not url:
        m = re.search(r'<iframe[^>]*src="([^"]+)"', html)
        if m:
            url = m.group(1).strip()
    if not url:
        # 常见播放器变量兜底
        for pat in (r'url\s*[:=]\s*"([^"]+\.m3u8[^"]*)"',
                    r'file\s*[:=]\s*"([^"]+)"',
                    r'm3u8Url\s*[:=]\s*"([^"]+)"'):
            m = re.search(pat, html)
            if m:
                url = m.group(1).strip()
                break
    if url:
        with _LOCK:
            _HTML_CACHE[key] = (now, url)
    return url


def _ext_dict(ext):
    if isinstance(ext, dict):
        return ext
    try:
        j = json.loads(ext or "{}")
        return j if isinstance(j, dict) else {}
    except Exception:
        return {}


_cat_seen = {}


def _seen_set(ctx, pg=1):
    """pg=1 重置; pg>1 返回累积的已看 vid 集合"""
    if pg <= 1:
        _cat_seen.pop(ctx, None)
        s = set()
        _cat_seen[ctx] = s
        return s
    s = _cat_seen.get(ctx)
    if s is None:
        s = set()
        _cat_seen[ctx] = s
    return s


def _dedupe_cross_page(ctx, cards, pg, page_size=24):
    """★ 策驰影院服务端不支持分页，_cards_stui 一次返回整页所有卡。
    必须按页码切片再跨页去重，否则 pg=1 一次把全部 vid 记进 seen，
    pg=2 全被过滤 → 空列表 → 翻页失败。

    策略:
    - pg=1: 取 cards[0:page_size]，全部记入 seen，返回这 24 卡
    - pg=2: 从 cards 里跳过已记的 vid，取 page_size 个新卡，继续记
    - pg=N: 同上
    - 若新卡不足 page_size → 返回剩余（壳可判定为末页）
    - 若新卡为 0 → 返回 []
    """
    if not cards:
        return []
    seen = _seen_set(ctx, pg)
    out = []
    for c in cards:
        vid = str(c.get("vod_id") or "")
        if vid and vid in seen:
            continue
        out.append(c)
        if vid:
            seen.add(vid)
        if len(out) >= page_size:
            break
    return out


def _reset_cat(tid):
    """pg=1 时清理该分类所有 ctx 的 seen 记录"""
    for k in list(_cat_seen.keys()):
        if str(k).startswith("cat:%s:" % tid) or str(k) == tid:
            _cat_seen.pop(k, None)


# ---------------- Spider ----------------
class Spider(_BaseSpider):

    def init(self, cfg=""):
        self._home = {"ts": 0.0, "list": []}
        _load_domain_cache()
        # ★ 后台预热: 拿域名 + 访问首页获取 Cookie (绕过搜索验证码)
        threading.Thread(target=lambda: (
            _ensure_base(True),
            _warmup_cookies(),
        ), daemon=True).start()
        return ""

    def getName(self):
        return "策驰影院"

    def getDependence(self):
        return {}

    def homeContent(self, filter):
        classes = [{"type_id": t, "type_name": n} for t, n in TOP]
        for t, _ in TOP:
            for sub_slug, sub_name in SUBS.get(t, []):
                classes.append({"type_id": sub_slug, "type_name": sub_name})
        filters = {}
        for t, _ in TOP:
            fl = []
            subs = SUBS.get(t, [])
            if subs:
                fl.append({"key": "cate", "name": "分类",
                           "value": [{"n": "全部", "v": ""}] +
                                   [{"n": n, "v": s} for s, n in subs]})
            fl.append({"key": "area", "name": "地区",
                       "value": [{"n": "全部", "v": ""}] +
                                [{"n": a, "v": a} for a in AREAS]})
            fl.append({"key": "year", "name": "年份",
                       "value": [{"n": "全部", "v": ""}] +
                                [{"n": y, "v": y} for y in YEARS]})
            fl.append({"key": "order", "name": "排序",
                       "value": [{"n": "默认", "v": ""}] +
                                [{"n": n, "v": o} for o, n in ORDERS]})
            filters[t] = fl
        return {"class": classes, "filters": filters}

    def homeVideoContent(self):
        if self._home["list"] and time.time() - self._home["ts"] < HOME_TTL:
            return {"list": self._home["list"]}
        pools = []
        results = {}
        _tlist = []

        def _one(slug, idx):
            try:
                h = _cached_page("/vodtype/%s/" % slug, ttl=HOME_TTL)
                cards = _cards_stui(h) if h else []
                if not cards:
                    parts = [slug, "", "", "", "", "", "", "", "", "", ""]
                    h2 = _cached_page("/vodshow/%s/" % "-".join(parts),
                                      ttl=HOME_TTL)
                    cards = _cards_stui(h2) if h2 else []
                results[idx] = cards[:8]
            except Exception:
                results[idx] = []

        for i, (slug, _) in enumerate(TOP):
            th = threading.Thread(target=_one, args=(slug, i))
            th.daemon = True
            _tlist.append(th)
            th.start()

        deadline = time.time() + 6.0
        for th in _tlist:
            remain = deadline - time.time()
            if remain <= 0:
                break
            th.join(remain)

        for i in range(len(TOP)):
            pools.append(results.get(i) or [])

        out, seen = [], set()
        i = 0
        while len(out) < 42:
            added = False
            for pool in pools:
                if i < len(pool):
                    vid = pool[i].get("vod_id", "")
                    if vid and vid not in seen:
                        seen.add(vid)
                        out.append(pool[i])
                        added = True
            if not added:
                break
            i += 1
        out = _dedupe_cards(out)
        if out:
            self._home = {"ts": time.time(), "list": out}
        return {"list": out}

    # ---------- v1.2: 客户端切片翻页 ----------
    # 实测: /vodtype/{slug}/page/N/ 服务端忽略 page 参数（返回与 page1 完全相同
    # 的 HTML，标题从"第1页"变"第2页"但卡片一字不差）; /vodshow/{11段}/page/N/
    # 全 404。→ 服务端从架构上不支持服务端分页。
    # 方案: 顶频道 hub 页 /vodtype/{top}/ 内含 ~26 个「最新X片 / X片周榜单」
    # 分区，一次抓完整站分类页数据；分类翻页在客户端切片。
    # sub 分类通过 hub 分区标题（动作片/爱情片/国产剧...）匹配定位。
    _HUB_CACHE = {}
    _HUB_LOCK = threading.Lock()

    def _hub_sections(self, top):
        with self._HUB_LOCK:
            c = self._HUB_CACHE.get(top)
            if c and time.time() - c[0] < HTML_TTL:
                return c[1]
        h = _cached_page("/vodtype/%s/" % top, ttl=HTML_TTL)
        secs = _parse_hub_sections(h) if h else []
        if not secs:
            return []
        with self._HUB_LOCK:
            self._HUB_CACHE[top] = (time.time(), secs)
            return secs

    def _hub_all_cards(self, top):
        """从顶分类 + 所有子分类的 hub 页聚合卡片，增加总卡片数量"""
        out = []
        # 1. 先获取顶分类 hub 页卡片
        secs = self._hub_sections(top)
        for _, cards in secs:
            out.extend(cards)
        # 2. 再获取所有子分类的 hub 页卡片
        for sub_slug, _name in SUBS.get(top, []):
            sub_secs = self._hub_sections(sub_slug)
            for _, cards in sub_secs:
                out.extend(cards)
        return _dedupe_cards(out)

    def _hub_cards_by_slug(self, slug):
        """通过 hub 分区标题（动作片/爱情片/国产剧...）匹配 sub 分类"""
        for t in TOP_IDS:
            for nm, cards in self._hub_sections(t):
                if not nm:
                    continue
                for s, name in SUBS.get(t, []):
                    if s == slug:
                        if (name in nm) or (nm in name) or \
                           (re.sub(r"[^\u4e00-\u9fff]", "", nm) ==
                            re.sub(r"[^\u4e00-\u9fff]", "", name)):
                            return _dedupe_cards(cards)
        return []

    def categoryContent(self, tid, pg, filter1, ext):
        ext = _ext_dict(ext)
        t = str(tid or "dianying")
        try:
            pg = max(1, int(pg or 1))
        except Exception:
            pg = 1

        if pg == 1:
            _reset_cat(t)

        cate = str(ext.get("cate") or "")
        eff_t = cate if cate else t
        area = str(ext.get("area") or "")
        year = str(ext.get("year") or "")
        order = str(ext.get("order") or "")
        # 跨页去重的上下文 key（不含 pg，同一分类+筛选共用一套 seen）
        ctx = "cat:%s:%s:%s:%s" % (t, area, year, order)

        # 主路: /vodtype/{slug}/page/{pg}/
        qs = []
        if area:
            qs.append("area=" + urllib.parse.quote(area))
        if year:
            qs.append("year=" + urllib.parse.quote(year))
        if order:
            qs.append("order=" + urllib.parse.quote(order))
        if pg > 1:
            path1 = "/vodtype/%s/page/%d/" % (eff_t, pg)
        else:
            path1 = "/vodtype/%s/" % eff_t
        if qs:
            path1 += "?" + "&".join(qs)

        html = _cached_page(path1)
        all_cards = _cards_stui(html) if html else []
        total = _pagecount_stui(html) if html else 0
        # ★ openaihot.py 模式: 全量拉卡 → 跨页去重 + 按页切片
        cards = _dedupe_cross_page(ctx, all_cards, pg, PAGE_SIZE)

        # 备路: /vodshow/{11段}/page/{pg}/
        if not all_cards:
            parts = [eff_t, "", "", "", "", "", "", "", "", "", ""]
            if area:
                parts[2] = area
            if year:
                parts[4] = year
            if order:
                parts[5] = order
            slug = "-".join(parts)
            if pg > 1:
                path2 = "/vodshow/%s/page/%d/" % (slug, pg)
            else:
                path2 = "/vodshow/%s/" % slug
            html = _cached_page(path2)
            all_cards = _cards_stui(html) if html else []
            if total <= 0 and html:
                total = _pagecount_stui(html)
            cards = _dedupe_cross_page(ctx, all_cards, pg, PAGE_SIZE)

        # 兜底: hub 页客户端切片（当主+备都失败时）
        if not cards:
            hub_cards = []
            if eff_t in TOP_IDS:
                hub_cards = self._hub_all_cards(eff_t)
            else:
                hub_cards = self._hub_cards_by_slug(eff_t)
            if hub_cards:
                h_total = max(1, (len(hub_cards) + PAGE_SIZE - 1) // PAGE_SIZE)
                start = (pg - 1) * PAGE_SIZE
                page_list = hub_cards[start:start + PAGE_SIZE]
                return {"list": page_list, "limit": PAGE_SIZE,
                        "total": h_total}

        # ★ 服务端没真分页时，按 _cards_stui 返回的卡片数量算页数
        # （策驰影院 hub 页有 156 卡，但 _pagecount_stui 因无 /page/ 链接只给 1，
        #  会让壳以为只有 1 页；这里按实际卡数算出 total，配合 dedup 跨页切片）
        if all_cards and len(all_cards) > PAGE_SIZE and total <= 1:
            total = (len(all_cards) + PAGE_SIZE - 1) // PAGE_SIZE

        videos = _dedupe_cards(cards)
        return {"list": videos, "limit": PAGE_SIZE,
                "total": max(total, pg)}

    def searchContent(self, key, quick, pg="1"):
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick, pg="1"):
        key = (key or "").strip()
        if not key:
            return {"list": [], "limit": PAGE_SIZE, "total": 1}
        try:
            if "%" in key:
                dec = urllib.parse.unquote(key)
                if dec and dec.strip():
                    key = dec.strip()
        except Exception:
            pass
        try:
            pg = max(1, int(pg or 1))
        except Exception:
            pg = 1

        wd = urllib.parse.quote(key)
        limit = PAGE_SIZE

        # ★ AJAX suggest 接口不走 /vodsearch/ 路径，不触发 GoEdge WAF 验证码
        # 接口: /index.php/ajax/suggest?wd=关键词&mid=1&limit=N
        # 返回: JSON {code:1, list:[{id,name,en,pic}], page, pagecount, total}
        api_url = "/index.php/ajax/suggest?wd=%s&mid=1&limit=%d&page=%d" % (
            wd, limit, pg)
        html = _cached_page(api_url, ttl=60)
        if not html or _is_waf(html):
            return {"list": [], "limit": PAGE_SIZE, "total": 1}

        try:
            data = json.loads(html)
        except Exception:
            return {"list": [], "limit": PAGE_SIZE, "total": 1}

        if data.get("code") != 1:
            return {"list": [], "limit": PAGE_SIZE, "total": 1}

        items = data.get("list") or []
        total = data.get("pagecount") or data.get("total") or 1
        if isinstance(total, str):
            try:
                total = int(total)
            except Exception:
                total = 1

        videos = []
        for item in items:
            vid = str(item.get("id") or item.get("en") or "")
            name = str(item.get("name") or "")
            pic = _fix_pic(str(item.get("pic") or ""))
            if vid and name:
                videos.append({
                    "vod_id": vid,
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_remarks": "",
                })

        return {"list": videos, "limit": limit,
                "total": max(total, pg)}

    def detailContent(self, ids):
        vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        if not vid:
            return {}
        html = _cached_page("/cechi/%s/" % vid, ttl=DETAIL_TTL)
        if not html:
            return {}
        d = _parse_detail(html, vid)
        vod = {
            "vod_id": vid,
            "vod_name": d["vod_name"],
            "vod_pic": d["vod_pic"],
            "type_name": d["type_name"],
            "vod_year": d["vod_year"],
            "vod_area": d["vod_area"],
            "vod_remarks": d["vod_remarks"],
            "vod_actor": d["vod_actor"],
            "vod_director": d["vod_director"],
            "vod_content": d["vod_content"],
            "vod_score": d["vod_score"],
            "vod_play_from": "$$$".join(nm for nm, _ in d["lines"]),
            "vod_play_url": "$$$".join(
                "#".join("%s$%s" % (ename or ("第%02d集" % (k + 1)),
                                    _norm_play_path(eurl))
                         for k, (eurl, ename) in enumerate(eps))
                for _, eps in d["lines"]),
        }
        if d["lines"]:
            first_eps = d["lines"][0][1]
            if first_eps:
                play_path = _norm_play_path(first_eps[0][0])
                if not _HTML_CACHE.get("play:" + play_path):
                    threading.Thread(target=lambda p=play_path: _play_url(p),
                                     daemon=True).start()
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        path = str(id or "").strip().rstrip("/")
        url = _play_url(path)
        header = {"User-Agent": UA, "Referer": REFERER}
        return {"parse": 0, "url": url, "header": header}

    def isVideoFormat(self, url):
        return ".m3u8" in url or ".mp4" in url

    def manualVideoResolve(self, url):
        return url

    def localProxy(self, params):
        return None

    def __getattr__(self, name):
        _map = {
            "getHomeContent": "homeContent",
            "getHomeVideoContent": "homeVideoContent",
            "getCategoryContent": "categoryContent",
            "getDetailContent": "detailContent",
            "getSearchContent": "searchContent",
            "getPlayerContent": "playerContent",
            "getName": "getName",
            "getDependence": "getDependence",
        }
        if name in _map:
            return getattr(self, _map[name])
        def _stub(*args, **kwargs):
            if name.startswith("is"):
                return False
            return {}
        return _stub


# ============================================================
# 自测
# ============================================================
def self_test():
    s = Spider()
    s.init({})

    print("=== homeContent ===")
    home = s.homeContent(True)
    print("分类:", [c["type_name"] for c in home["class"][:10]], "...")

    print("\n=== homeVideoContent ===")
    hv = s.homeVideoContent()
    print("推荐:", len(hv["list"]), "条")
    if hv["list"]:
        print("  前5:")
        for v in hv["list"][:5]:
            pic = v["vod_pic"]
            ok = "OK " if pic.startswith(("http://", "https://")) else "×  "
            print("    %s %s | %s" % (ok, v["vod_name"][:16], pic[:70]))

    print("\n=== categoryContent 电影 P1 ===")
    cat = s.categoryContent("dianying", "1", None, {})
    print("  %d 条; 海报样例:" % len(cat["list"]))
    for v in cat["list"][:8]:
        pic = v["vod_pic"]
        ok = "OK " if pic.startswith(("http://", "https://")) else "×  "
        print("    %s %s | %s" % (ok, v["vod_name"][:16], pic[:70]))

    print("\n=== searchContent 希望 ===")
    sr = s.searchContent("希望", False, "1")
    print("  命中 %d 条" % len(sr["list"]))
    for v in sr["list"][:5]:
        pic = v["vod_pic"]
        ok = "OK " if pic.startswith(("http://", "https://")) else "×  "
        print("    %s %s | %s" % (ok, v["vod_name"][:16], pic[:70]))

    if sr["list"]:
        vid = sr["list"][0]["vod_id"]
        print("\n=== detailContent %s ===" % vid)
        det = s.detailContent([vid])
        if det.get("list"):
            vod = det["list"][0]
            pic = vod["vod_pic"]
            ok = "OK " if pic.startswith(("http://", "https://")) else "×  "
            print("  %s %s (%s) [%s]" % (ok, vod["vod_name"], vod["vod_year"],
                                          vod["vod_remarks"]))
            print("  类型: %s | 地区: %s | 评分: %s" % (
                vod["type_name"], vod["vod_area"], vod["vod_score"]))
            print("  主演: %s" % vod["vod_actor"][:60])
            print("  导演: %s" % vod["vod_director"][:60])
            print("  海报: %s" % pic[:90])
            print("  简介: %s" % vod["vod_content"][:80])
            print("  线路: %s" % vod["vod_play_from"])
            for i, p in enumerate(vod["vod_play_url"].split("$$$")):
                if not p:
                    continue
                eps = p.split("#")
                print("  线路%d 集数=%d 首集=%s" % (i + 1, len(eps), eps[0][:60]))
        else:
            print("  [FAIL] 空")

    print("\n=== playerContent 直取 ===")
    if sr["list"]:
        vid = sr["list"][0]["vod_id"]
        det = s.detailContent([vid])
        if det.get("list") and det["list"][0]["vod_play_url"]:
            first = det["list"][0]["vod_play_url"].split("$$$")[0]
            if first:
                first_ep = first.split("#")[0]
                ename, path = first_ep.split("$", 1) if "$" in first_ep else ("", first_ep)
                print("  取: %s → %s" % (ename, path))
                pc = s.playerContent("x", path, "")
                print("  url: %s" % (pc.get("url") or "(空)")[:100])

    print("\n✓ 自测完成")


if __name__ == "__main__":
    self_test()