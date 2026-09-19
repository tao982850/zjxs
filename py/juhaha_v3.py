# -*- coding: utf-8 -*-
# ============ juha 蜘蛛 v2-diag（诊断优先 · 纯标准库） ============
# 站点: MacCMS 魔改 / www.juhaha.fun | www.juhaha.cc（同一台服务器）
#
# 设计原则（都是为了让壳子"一定能加载进来"）：
#   1) 只用 Python 标准库，绝不 import requests / ddddocr / bs4
#   2) 顶层不执行任何网络/SSL 动作（全部惰性化），避免加载期异常
#   3) 每个入口整段 try/except，出错也不抛异常，改为返回可见文字
#   4) 站点名带版本号（NAME），一眼就能确认壳子加载的是哪一份
#   5) 首页数据解析为空时，插入一条自检项，写明失败原因
#
# 播放直链算法（来自原作者 71us v7.5，已验证）：
#   POST /hhplayer/api.php {vid=密文A} -> data.url(urlmode=2)
#   -> base64 解码 -> 取 [1::3] 中流 -> 'UllRA://' -> 62 字符表 D2T 位移映射 -> 直链
#   （该接口不需要验证码 Cookie；只有网页需要）

import sys
import os
import re
import json
import time
import base64
import random

try:
    import urllib.request as _urlreq
    import urllib.parse as _urlparse
except Exception:
    _urlreq = None
    _urlparse = None

NAME = "剧哈哈 juhaha v3auto"

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass

# ============ CONFIG ============
HOSTS = ["https://www.juhaha.fun", "https://www.juhaha.cc"]
HOST = HOSTS[0]
UA = ("Mozilla/5.0 (Linux; Android 12; SM-G9860) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")
CATEGORIES = [("1", "电影"), ("2", "剧集"), ("3", "综艺"), ("4", "动漫")]
REFERER = HOST + "/"
DEFAULT_COOKIE = (
    "PHPSESSID=8es742hormndpur13du8n0raur; "
    "captcha_login_sign=9607a9274e77fba393b650cdcfebf0b7-92ba0e23ddfee8adb657032a452eba8c1d4eba60e3a5fedd542e0cd3666a4fc1-1789307949; "
    "tips=true"
)
# Cookie 本地缓存（验证码签名约12小时有效；ext > 缓存 > 内置，三级取用）
CK_FILES = ["/sdcard/Download/.juhaha_ck.txt", "/sdcard/.juhaha_ck.txt", "juhaha_ck.txt"]
API_TRY = 24
VIDEO_EXTS = "m3u8|mp4|flv|mkv|avi|ts"

# 62 字符替换表（站方 2026-09 升级后的新表）
D2T = "PXhw7UT1B0a9kQDKZsjIASmOezxYG4CHo5Jyfg2b8FLpEvRr3WtVnlqMidu6cN"
D2M = {}
for _i, _c in enumerate(D2T):
    D2M[_c] = D2T[(_i + 59) % 62]
# 旧 59 双表（兜底）
M2C = "%&-./01456789:=?ABDEFGHIJLMNOPQRSTUVWXY_abcdefiklnopqrstuyz"
M2P = "%&-./T7xCiXgB:=?sU9F2zGZHbnuA6apjwh3Rce_1fdqS5l0tW48VEDrMom"
UMAP = {}
for _i, _c in enumerate(M2C):
    UMAP[_c] = M2P[_i]

_TAG_RE = re.compile(r"<[^>]+>")
_VID_A_RE = re.compile(r'<a[^>]+href="/video/(\d+)\.html"[^>]*>')
_CONTENT_MARK = re.compile(r'href="/(?:video|type)/\d+\.html"|href="/play/\d+-\d+-\d+\.html"|player_aaaa', re.I)

_CTX = None
_CTX_TRIED = False


def _ctx():
    """惰性构建 SSL 上下文（顶层不做，避免加载期异常）。"""
    global _CTX, _CTX_TRIED
    if not _CTX_TRIED:
        _CTX_TRIED = True
        try:
            import ssl
            c = ssl.create_default_context()
            c.check_hostname = False
            c.verify_mode = ssl.CERT_NONE
            _CTX = c
        except Exception:
            _CTX = None
    return _CTX


def _open(req, timeout):
    kw = {"timeout": timeout}
    c = _ctx()
    if c is not None:
        kw["context"] = c
    return _urlreq.urlopen(req, **kw)


def _clean(s):
    try:
        return _TAG_RE.sub("", str(s or "")).strip()
    except Exception:
        return ""


def _unescape(s):
    try:
        import html
        return html.unescape(s)
    except Exception:
        return s


def _split_ck(ck):
    d = {}
    for part in str(ck or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            k, v = k.strip(), v.strip()
            if k:
                d[k] = v
    return d


def _gzip_maybe(raw, enc):
    try:
        if enc and "gzip" in str(enc).lower():
            import gzip
            raw = gzip.decompress(raw)
    except Exception:
        pass
    return raw


def _is_blocked(t):
    if t is None:
        return True
    if "系统安全验证" in t or "访问此数据需要输入验证码" in t:
        return True
    try:
        return _CONTENT_MARK.search(t) is None
    except Exception:
        return False


def _http(url, cookie="", referer=None, data=None, timeout=12, binary=False, retries=2, hosts=True):
    """统一请求。返回 (内容 or None, 错误文字)。hosts=True 时主域名失败自动换备用域名。"""
    if _urlreq is None:
        return (b"" if binary else None), "urllib 不可用"
    cands = [url]
    if hosts and url.startswith(HOSTS[0]):
        cands.append(HOSTS[1] + url[len(HOSTS[0]):])
    last_err = ""
    for cu in cands:
        for attempt in range(max(1, retries)):
            try:
                hd = {
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Referer": referer or REFERER,
                }
                if cookie:
                    hd["Cookie"] = cookie
                body = None
                if data is not None:
                    body = _urlparse.urlencode(data).encode("utf-8")
                    hd["Content-Type"] = "application/x-www-form-urlencoded"
                req = _urlreq.Request(cu, data=body, headers=hd)
                r = _open(req, timeout)
                try:
                    raw = r.read(8_000_000)
                    enc = r.headers.get("Content-Encoding", "")
                finally:
                    try:
                        r.close()
                    except Exception:
                        pass
                raw = _gzip_maybe(raw, enc)
                if binary:
                    return raw, ""
                txt = raw.decode("utf-8", "ignore")
                if not data and _is_blocked(txt):
                    last_err = "被拦(验证码/WAF) len=%d" % len(txt)
                    if attempt < retries - 1:
                        time.sleep(1.0)
                        continue
                    break
                return txt, ""
            except Exception as e:
                last_err = "%s: %s" % (type(e).__name__, str(e)[:90])
                if attempt < retries - 1:
                    time.sleep(0.6)
                    continue
                break
    return (b"" if binary else None), last_err


def _json_loose(text):
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _extract_player_aaaa(h):
    """稳健提取播放页 player_aaaa（兼容带 var 未转义 / 无 var 且引号转义 两种形态）。"""
    if not h:
        return None
    m = re.search(r"player_aaaa\s*=\s*\{", h)
    if not m:
        return None
    start = m.end() - 1
    depth = 0
    end = -1
    limit = min(len(h), start + 300000)
    i = start
    while i < limit:
        c = h[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
        i += 1
    if end < 0:
        return None
    raw = h[start:end + 1]
    for cand in (raw,
                 raw.replace('\\"', '"').replace("\\/", "/").replace("\\\\", "\\"),
                 _unescape(raw)):
        try:
            return json.loads(cand)
        except Exception:
            continue
    return None


def _dec2(b):
    """密文B -> 直链：base64 解码 -> 取 [1::3] -> 62 表位移映射。"""
    if not b:
        return ""
    try:
        pad = "=" * (-len(b) % 4)
        raw = base64.b64decode(b + pad)
        c = raw[1::3].decode("latin-1")
        if not c.startswith("UllRA://"):
            return ""
        for mp in (D2M, UMAP):
            u = "".join(mp.get(ch, ch) for ch in c)
            if not u.startswith("http"):
                continue
            if re.search(r"[\x00-\x20{}|^~]", u):
                continue
            hm = re.match(r"https?://([^/?#]+)", u)
            if hm and re.search(r"[A-Z]", hm.group(1)):
                continue
            return u
    except Exception:
        pass
    return ""


class Spider(BaseSpider):
    host = HOST
    headers = {"User-Agent": UA, "Referer": REFERER}

    def __init__(self):
        self.host = HOST
        self.headers = {"User-Agent": UA, "Referer": REFERER}
        self.cookie = DEFAULT_COOKIE
        self._ex = {}
        self._note = ""

    def init(self, extend=""):
        self.host = HOST
        self.headers = {"User-Agent": UA, "Referer": REFERER}
        self.cookie = DEFAULT_COOKIE
        # 三级取用: ext字段 > 本地缓存 > 内置
        try:
            if extend and isinstance(extend, str) and ("PHPSESSID" in extend or "captcha_login_sign" in extend):
                self.cookie = extend.strip()
            else:
                for p in CK_FILES:
                    try:
                        if os.path.exists(p):
                            t = open(p).read().strip()
                            if "captcha_login_sign" in t:
                                self.cookie = t
                                break
                    except Exception:
                        pass
        except Exception:
            pass
        self._save_ck()

    def _save_ck(self):
        try:
            for p in CK_FILES:
                try:
                    f = open(p, "w")
                    f.write(self.cookie)
                    f.close()
                    return
                except Exception:
                    continue
        except Exception:
            pass

    # ---------------- 通用工具 ----------------
    def _fetch(self, url, binary=False, data=None, timeout=12, retries=2):
        return _http(url, cookie=self.cookie, referer=REFERER,
                     data=data, timeout=timeout, binary=binary, retries=retries)

    def _items(self, h):
        out = []
        seen = {}
        try:
            for m in _VID_A_RE.finditer(h or ""):
                vid = m.group(1)
                if vid in seen:
                    continue
                seen[vid] = 1
                tag = m.group(0)
                seg = (h or "")[m.end():m.end() + 400]
                nm = re.search(r'title="([^"]*)"', tag)
                pic = (re.search(r'data-original="([^"]+)"', tag)
                       or re.search(r'data-original="([^"]+)"', seg)
                       or re.search(r'<img[^>]+src="(https?://[^"]+)"', seg))
                rem = re.search(r"pic-text[^>]*>([\s\S]{0,30}?)</span>", seg)
                p = pic.group(1) if pic else ""
                if p.startswith("//"):
                    p = "https:" + p
                out.append({
                    "vod_id": vid,
                    "vod_name": _clean(nm.group(1)) if nm else "",
                    "vod_pic": p,
                    "vod_remarks": re.sub(r"\s+", " ", rem.group(1)).strip() if rem else "",
                })
        except Exception as e:
            self._note = "解析异常:" + str(e)[:80]
        return out

    def _res(self, videos, pg=1, pgcount=1):
        return {"list": videos, "page": int(pg), "pagecount": int(pgcount),
                "limit": 42, "total": len(videos), "filters": {}}

    def _diag(self, detail):
        return [{"vod_id": "__diag__",
                 "vod_name": "自检 " + NAME,
                 "vod_pic": "",
                 "vod_remarks": detail[:160]}]

    # ---------------- 入口 ----------------
    def homeContent(self, filter=False):
        cls = [{"type_id": k, "type_name": v} for k, v in CATEGORIES]
        items = []
        note = ""
        try:
            h, err = self._fetch(HOST + "/")
            if h:
                if "安全验证" in h or "mac_verify" in h:
                    note = ("⚠️ Cookie已过期(站点验证码门禁)。更新方法: "
                            "手机浏览器打开 www.juhaha.fun → 输图过验证 → "
                            "复制Cookie发给我 或 填到本配置ext字段。播放不受影响。")
                else:
                    items = self._items(h)
                    note = "首页OK len=%d" % len(h)
            else:
                note = "首页失败 " + (err or "无返回")
        except Exception as e:
            note = "首页异常 " + type(e).__name__ + ":" + str(e)[:80]
        if not items:
            items = self._diag(note + " | py" + sys.version.split()[0][:4] +
                               " ck=" + ("有" if self.cookie else "无") +
                               " " + self._note)
        return {"class": cls, "list": items, "filters": {}}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        try:
            pn = max(int(str(pg)), 1)
        except Exception:
            pn = 1
        t = str(tid).split("|")[0]
        cands = []
        if pn <= 1:
            cands = ["/type/%s.html" % t, "/list/%s--------1---.html" % t]
        else:
            cands = ["/type/%s-1-%d.html" % (t, pn), "/list/%s--------%d---.html" % (t, pn)]
        items, last = [], ""
        for u in cands:
            h, err = self._fetch(HOST + u)
            if h:
                items = self._items(h)
                if items:
                    break
            last = err or "空"
        if not items:
            items = self._diag("分类无数据 %s %s" % (tid, last))
        return self._res(items, pn, pn + 1 if len(items) > 1 else pn)

    def detailContent(self, ids):
        try:
            if not ids:
                return {"list": []}
            raw = str(ids[0] if isinstance(ids, list) else ids)
            m = re.search(r"(\d+)", raw)
            vid = m.group(1) if m else ""
            if not vid:
                return {"list": []}
            h, err = self._fetch(HOST + "/video/%s.html" % vid)
            if not h:
                return {"list": [{"vod_id": vid, "vod_name": "详情失败 " + (err or ""),
                                  "vod_pic": "", "vod_play_from": "自检", "vod_play_url": "无$"}]}
            d = {"vod_id": vid, "vod_name": "", "vod_pic": "", "vod_year": "", "vod_area": "",
                 "vod_class": "", "vod_director": "", "vod_actor": "", "vod_content": "",
                 "vod_remarks": "", "vod_play_from": "", "vod_play_url": ""}
            m = re.search(r'class="title">([^<]+)</h3>', h)
            if m:
                d["vod_name"] = _clean(m.group(1))
            m = re.search(r'remarks-bg">([^<]+)</div>', h)
            if m:
                d["vod_remarks"] = _clean(m.group(1))
            m = re.search(r'data-original="([^"]+)"', h)
            if m:
                p = m.group(1)
                d["vod_pic"] = ("https:" + p) if p.startswith("//") else p
            m = re.search(r'<meta name="description" content="([^"]*)"', h)
            if m:
                d["vod_content"] = _unescape(m.group(1)).strip()[:500]
            if not d["vod_name"]:
                d["vod_name"] = "未取到标题"
            pf, pu = [], []
            for idx, nm in re.findall(r'href="#playlist(\d+)"[^>]*>([^<]+)</a>', h):
                i0 = h.find('id="playlist%s"' % idx)
                if i0 < 0:
                    continue
                j0 = h.find('id="playlist', i0 + 12)
                blk = h[i0:j0] if j0 > 0 else h[i0:i0 + 30000]
                eps = re.findall(r'href="(/play/\d+-\d+-\d+\.html)">([^<]+)</a>', blk)
                if not eps:
                    continue
                pf.append(_clean(nm))
                pu.append("#".join(
                    "%s$%s%s" % (ep[1].strip().replace("#", "-").replace("$", "|"), HOST, ep[0])
                    for ep in eps))
            if pf:
                d["vod_play_from"] = "$$$".join(pf)
                d["vod_play_url"] = "$$$".join(pu)
            return {"list": [d]}
        except Exception as e:
            return {"list": [{"vod_id": "0", "vod_name": "详情异常 " + str(e)[:60],
                              "vod_pic": "", "vod_play_from": "自检", "vod_play_url": "无$"}]}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            pn = max(int(str(pg)), 1)
        except Exception:
            pn = 1
        q = _urlparse.quote(key or "")
        cands = ["/search/%s----------%d---.html" % (q, pn),
                 "/search/-------------.html?wd=%s&pg=%d" % (q, pn)]
        items, last = [], ""
        for u in cands:
            h, err = self._fetch(HOST + u)
            if h:
                items = self._items(h)
                if items:
                    break
            last = err or "空"
        if not items:
            items = self._diag("搜索无数据 " + last)
        return self._res(items, pn, pn + 1 if len(items) > 1 else pn)

    def playerContent(self, flag, id, vipFlags=None):
        try:
            url = str(id) if id else str(flag)
            if "$" in url:
                url = url.split("$", 1)[1]
            if url.startswith("http") and re.search(r"\.(%s)(\?|$)" % VIDEO_EXTS, url, re.I):
                return {"parse": 0, "url": url, "header": {"User-Agent": UA, "Referer": REFERER}}
            if not url.startswith("http"):
                url = HOST + "/" + url.lstrip("/")
            c = self._ex.get(url)
            if c and time.time() - c[0] < 3600:
                return c[1]
            vid = ""
            h, err = self._fetch(url)
            if h:
                pa = _extract_player_aaaa(h) or {}
                vid = pa.get("url", "")
            if vid:
                u = self._hh_play(vid)
                if u:
                    res = {"parse": 0, "url": u, "header": {"User-Agent": UA, "Referer": REFERER}}
                    self._ex[url] = (time.time(), res)
                    return res
                # 兜底：hhplayer 页必须放进 iframe（页内有 self==top 自拦截）
                hh = HOST + "/hhplayer/index.php?vid=" + vid
                page = ('<!DOCTYPE html><html><head><meta charset="utf-8">'
                        '<meta name="viewport" content="width=device-width,initial-scale=1">'
                        '<style>html,body{margin:0;padding:0;height:100%;background:#000;overflow:hidden}'
                        'iframe{position:fixed;top:0;left:0;width:100%;height:100%;border:0}</style></head>'
                        '<body><iframe src="' + hh + '" allowfullscreen allow="autoplay; fullscreen">'
                        '</iframe></body></html>')
                res = {"parse": 1,
                       "url": "data:text/html;charset=utf-8," + _urlparse.quote(page, safe=""),
                       "header": {"User-Agent": UA, "Referer": url}}
                self._ex[url] = (time.time(), res)
                return res
            return {"parse": 0, "url": "", "msg": "取播放失败 " + (err or "无player_aaaa")}
        except Exception as e:
            return {"parse": 0, "url": "", "msg": "播放异常 " + str(e)[:80]}

    def _hh_play(self, vid):
        for _ in range(API_TRY):
            t, err = _http(HOST + "/hhplayer/api.php", cookie=self.cookie, referer=REFERER,
                           data={"vid": vid}, timeout=15, retries=1)
            r = _json_loose(t)
            if not r:
                continue
            dat = r.get("data") or {}
            if dat.get("urlmode") == 2 and dat.get("url"):
                u = _dec2(dat["url"])
                if u:
                    return u
        return ""

    def localProxy(self, param):
        try:
            url = param
            if isinstance(param, dict):
                url = param.get("url") or param.get("u") or ""
            url = _urlparse.unquote(str(url or ""))
            if "url=" in url:
                url = url.split("url=", 1)[1]
            if not url.startswith("http"):
                cand = url.replace("-", "+").replace("_", "/")
                cand += "=" * (-len(cand) % 4)
                try:
                    dec = base64.b64decode(cand).decode("utf-8", "ignore")
                    if dec.startswith("http"):
                        url = dec
                except Exception:
                    pass
            if not url.startswith("http"):
                return None
            raw, _ = _http(url, timeout=15, binary=True, retries=1, hosts=False)
            if not raw or len(raw) < 50:
                return None
            if raw[:3] == b"\xff\xd8\xff":
                mime = "image/jpeg"
            elif raw[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "image/png"
            elif raw[:6] in (b"GIF87a", b"GIF89a"):
                mime = "image/gif"
            elif raw[:4] == b"RIFF":
                mime = "image/webp"
            else:
                mime = "application/octet-stream"
            return [200, mime, raw]
        except Exception:
            return None

    def isVideoFormat(self, url):
        return bool(url) and bool(re.search(r"\.(?:%s)(?:\?|$)" % VIDEO_EXTS, str(url), re.I))

    def manualVideoCheck(self):
        return False

    def getDependence(self):
        return ""

    def destroy(self):
        try:
            self._ex.clear()
        except Exception:
            pass


# =================== 模块级入口 ===================
_sp = None


def _g():
    global _sp
    if _sp is None:
        try:
            _sp = Spider()
        except Exception:
            _sp = BaseSpider()
    return _sp


def getName():
    return NAME


def init(extend=""):
    try:
        return _g().init(extend)
    except Exception:
        return None


def homeContent(filter=False):
    try:
        return _g().homeContent(filter)
    except Exception as e:
        return {"class": [{"type_id": k, "type_name": v} for k, v in CATEGORIES],
                "list": [{"vod_id": "__diag__", "vod_name": "自检 " + NAME,
                          "vod_pic": "", "vod_remarks": ("homeContent异常 " + str(e))[:160]}],
                "filters": {}}


def homeVideoContent():
    try:
        return {"list": _g().homeContent(True).get("list", [])}
    except Exception:
        return {"list": []}


def categoryContent(tid, pg, filter=False, extend=""):
    try:
        return _g().categoryContent(tid, pg, filter, extend)
    except Exception as e:
        return {"list": [{"vod_id": "__diag__", "vod_name": "自检",
                          "vod_pic": "", "vod_remarks": ("category异常 " + str(e))[:160]}],
                "page": 1, "pagecount": 1, "total": 1}


def detailContent(ids):
    try:
        return _g().detailContent(ids)
    except Exception:
        return {"list": []}


def searchContent(key, quick=False, pg="1"):
    try:
        return _g().searchContent(key, quick, pg)
    except Exception:
        return {"list": []}


def playerContent(flag, id, vipFlags=None):
    try:
        return _g().playerContent(flag, id, vipFlags)
    except Exception:
        return {"parse": 0, "url": ""}


def localProxy(param):
    try:
        return _g().localProxy(param)
    except Exception:
        return None


def isVideoFormat(url):
    try:
        return _g().isVideoFormat(url)
    except Exception:
        return False


home = homeContent
category = categoryContent
detail = detailContent
search = searchContent
player = playerContent
proxy = localProxy
