# -*- coding: utf-8 -*-
"""HD.Rip 全球电视直播 — https://hd.rip/  TVBox / 影视（FongMi）Python Spider

站点取流实测要点（2026-11 复核）：
  1) /api/play.php 需要会话 Cookie hdrip_s，无会话时直接 403 {"error":"stream_denied"}；
     /api/keepalive.php 可以在没有会话时冷启动并直接返回播放地址。
  2) 播放列表地址带 e(到期时间) / s(HMAC) 签名，有效期约 1 小时，
     且签名与「取地址时的出口 IP」绑定：换一个出口 IP 再请求同一地址会 403。
  3) 播放列表里的分片是相对路径，分片本身不校验签名、也不锁 IP。

为此本插件在本机 127.0.0.1 起一个 HLS 小代理：播放器只访问本地代理，
插件用「同一条连接（同一出口 IP）」去取播放列表、必要时自动重新签名，
再把分片改写成绝对地址。这样签名过期后不必退出频道重进，
也避免播放器与插件出口 IP 不一致时整体 403。
本地端口起不来时自动退回「直连签名地址」模式。
"""
import gzip
import json
import re
import ssl
import threading
import time
from http.client import HTTPSConnection
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

from base.spider import Spider as BaseSpider

try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as _HTTPServer
except Exception:  # 极简运行环境兜底
    _HTTPServer = None
    BaseHTTPRequestHandler = object

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

_SIG_SAFE = 120          # 距到期不足该秒数就重新签名


def _json_of(raw):
    try:
        return json.loads(raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw)
    except Exception:
        return {}


def _expire_of(url):
    m = re.search(r"[?&]e=(\d+)", url or "")
    return int(m.group(1)) if m else int(time.time()) + 600


def _path_of(url):
    u = urlsplit(url)
    path = u.path or "/"
    return path + ("?" + u.query if u.query else "")


def _absolutize(text, base_url):
    """把播放列表里的相对地址改写成绝对地址。"""
    out = []
    for line in (text or "").replace("\r", "").split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            if 'URI="' in s:
                s = re.sub(
                    r'URI="([^"]+)"',
                    lambda m: 'URI="%s"' % urljoin(base_url, m.group(1)),
                    s,
                )
            out.append(s)
            continue
        out.append(urljoin(base_url, s))
    return "\n".join(out) + "\n"


class Spider(BaseSpider):
    def __init__(self):
        try:
            BaseSpider.__init__(self)
        except Exception:
            pass
        self.host = _HOST
        self._inited = False
        self._lock = threading.RLock()
        self._ctx = None
        self._conn = None
        self._conn_key = None
        self._cookie = ""
        self._channels = None
        self._sig = {}          # cid -> {"url":..., "e":...}
        self._srv = None
        self._port = 0
        self._proxy_on = False

    def getName(self):
        return "HDRip"

    def init(self, extend=""):
        self.host = _HOST
        self._proxy_on = _HTTPServer is not None
        port = 0
        if extend:
            try:
                cfg = json.loads(extend) if isinstance(extend, str) else (extend or {})
            except Exception:
                cfg = {}
            if isinstance(cfg, dict):
                if cfg.get("host"):
                    self.host = str(cfg["host"]).rstrip("/")
                if cfg.get("localProxy") is False or cfg.get("local_proxy") is False:
                    self._proxy_on = False
                try:
                    if cfg.get("port"):
                        port = int(cfg["port"])
                except Exception:
                    port = 0
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE
        self._channels = None
        self._sig = {}
        self._drop_conn()
        self._cookie = ""
        if self._proxy_on and self._srv is None:
            self._start_server(port)
        self._inited = True

    def _ensure_init(self):
        if not self._inited:
            self.init("")

    # ------------------------------------------------------------------ 内容
    def homeContent(self, filter):
        classes = [{"type_id": "all", "type_name": "全部"}]
        for tid, name, _ in _REGIONS:
            classes.append({"type_id": tid, "type_name": name})
        classes.append({"type_id": "other", "type_name": "其他"})
        return {"class": classes, "filters": {}}

    def homeVideoContent(self):
        return self.categoryContent("all", 1, False, {})

    def categoryContent(self, tid, pg, filter, extend):
        self._ensure_init()
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
        self._ensure_init()
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
        self._ensure_init()
        vid = str(ids[0]).strip()
        ch = self._find(vid)
        if not ch:
            return {"list": []}
        name = ch.get("name") or vid
        pic = ch.get("logo") or ""
        if pic and pic.startswith("/"):
            pic = self.host + pic
        intro = ch.get("intro") or name
        # 详情不预取播放地址（签名有时效），播放时再取
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
        self._ensure_init()
        cid = str(id).strip()
        if self._proxy_on and self._srv:
            # 先确认能拿到播放列表（同时也把签名地址预热到缓存里）
            if self.playlist_for(cid):
                url = "http://127.0.0.1:%d/hls/%s.m3u8" % (self._port, quote(cid, safe=""))
                return {
                    "parse": 0,
                    "jx": 0,
                    "url": url,
                    "header": json.dumps({"User-Agent": _UA}, ensure_ascii=False),
                }
        # 兜底：本地代理不可用时直连签名地址
        url = self._play_url(cid)
        headers = {"User-Agent": _UA, "Referer": self.host + "/", "Origin": self.host}
        if self._cookie:
            headers["Cookie"] = self._cookie
        return {
            "parse": 0,
            "jx": 0,
            "url": url or "",
            "header": json.dumps(headers, ensure_ascii=False),
        }

    def isVideoFormat(self, url):
        return bool(url) and re.search(r"\.(m3u8|mp4)(\?|$)", str(url), re.I)

    def manualVideoCheck(self):
        return False

    def destroy(self):
        try:
            if self._srv:
                self._srv.shutdown()
        except Exception:
            pass
        self._srv = None
        self._drop_conn()

    # ------------------------------------------------------------- 会话与取流
    def _get_conn(self, url):
        u = urlsplit(url)
        key = (u.scheme, u.hostname, u.port)
        if self._conn is None or self._conn_key != key:
            self._drop_conn()
            self._conn = HTTPSConnection(
                u.hostname, u.port or 443, context=self._ctx, timeout=20
            )
            self._conn_key = key
        return self._conn

    def _drop_conn(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None
        self._conn_key = None

    def _http(self, url, cookie=None, tries=2):
        """请求站点，返回 (status, body)；4xx/5xx 不抛异常。"""
        last = None
        for attempt in range(tries):
            try:
                conn = self._get_conn(url)
                headers = {
                    "User-Agent": _UA,
                    "Accept": "*/*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Accept-Encoding": "gzip, deflate",
                    "Referer": self.host + "/",
                }
                ck = self._cookie if cookie is None else cookie
                if ck:
                    headers["Cookie"] = ck
                conn.request("GET", _path_of(url), headers=headers)
                resp = conn.getresponse()
                raw = resp.read()
                sc = resp.getheader("Set-Cookie") or ""
                if "hdrip_s=" in sc:
                    self._cookie = sc.split(";")[0].strip()
                if raw[:2] == b"\x1f\x8b":
                    try:
                        raw = gzip.decompress(raw)
                    except Exception:
                        pass
                return resp.status, raw
            except Exception as e:
                last = e
                self._drop_conn()
        if last:
            print("[HDRip] http", last)
        return 0, b""

    def _ensure_session(self, force=False):
        if force:
            self._cookie = ""
        if self._cookie:
            return True
        # 首页会下发 hdrip_s；keepalive 也能冷启动会话
        try:
            self._http(self.host + "/", cookie="")
        except Exception as e:
            print("[HDRip] session", e)
        return bool(self._cookie)

    def _play_url(self, cid, force_session=False):
        """取播放地址（带签名），失败返回 ""。"""
        for attempt in range(3):
            self._ensure_session(force_session or attempt > 0)
            try:
                st, raw = self._http("%s/api/keepalive.php?id=%s" % (self.host, quote(str(cid))))
                data = _json_of(raw)
                url = (data.get("url") or "").strip()
                if not url:
                    st, raw = self._http("%s/api/play.php?id=%s" % (self.host, quote(str(cid))))
                    data = _json_of(raw)
                    url = (data.get("url") or "").strip()
                if url:
                    with self._lock:
                        self._sig[str(cid)] = {"url": url, "e": _expire_of(url)}
                    return url
                force_session = True
            except Exception as e:
                print("[HDRip] play", e)
            time.sleep(0.4 * (attempt + 1))
        return ""

    def playlist_for(self, cid):
        """给本地代理用：返回最新播放列表内容（已改写为绝对分片地址）。"""
        with self._lock:
            cid = str(cid).strip()
            now = int(time.time())
            entry = self._sig.get(cid)
            url = ""
            if entry and entry.get("e", 0) - now > _SIG_SAFE:
                url = entry.get("url") or ""
            if not url:
                url = self._play_url(cid)
            if not url:
                return None
            st, raw = self._http(url)
            if st != 200 or b"#EXTM3U" not in raw[:512]:
                # 签名或会话失效（含换 IP），重新签名后重试一次
                url = self._play_url(cid, force_session=True)
                if not url:
                    return None
                st, raw = self._http(url)
            if st != 200 or b"#EXTM3U" not in raw[:512]:
                print("[HDRip] playlist", cid, st)
                return None
            base = url.split("?")[0]
            return _absolutize(raw.decode("utf-8", "ignore"), base)

    # ---------------------------------------------------------------- 本地代理
    def _start_server(self, port):
        sp = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _send(self, code, body, ctype):
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    if body:
                        self.wfile.write(body)
                except Exception:
                    pass

            def do_HEAD(self):
                self.do_GET(head=True)

            def do_GET(self, head=False):
                try:
                    path, _, query = self.path.partition("?")
                    if path.startswith("/hls/"):
                        cid = unquote(path[len("/hls/"):]).split(".")[0]
                        pl = sp.playlist_for(cid)
                        if not pl:
                            self._send(502, b"playlist unavailable", "text/plain")
                            return
                        if head:
                            self._send(200, b"", "application/vnd.apple.mpegurl")
                            return
                        self._send(200, pl.encode("utf-8"), "application/vnd.apple.mpegurl")
                        return
                    if path == "/m":  # 嵌套播放列表（多码率）转发
                        target = unquote((parse_qs(query).get("u") or [""])[0])
                        if not target.startswith(sp.host):
                            self._send(403, b"", "text/plain")
                            return
                        st, raw = sp._http(target)
                        if st != 200:
                            self._send(502, b"", "text/plain")
                            return
                        body = _absolutize(raw.decode("utf-8", "ignore"), target.split("?")[0])
                        self._send(200, body.encode("utf-8"), "application/vnd.apple.mpegurl")
                        return
                    self._send(404, b"not found", "text/plain")
                except Exception:
                    pass

        base = port or 0
        for i in range(6):
            p = base + i if base else 0
            try:
                srv = _HTTPServer(("127.0.0.1", p), _Handler)
                self._srv = srv
                self._port = srv.server_address[1]
                t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.5})
                t.daemon = True
                t.start()
                print("[HDRip] local proxy 127.0.0.1:%d" % self._port)
                return
            except Exception as e:
                print("[HDRip] proxy bind %s %s" % (p, e))
        self._proxy_on = False

    # -------------------------------------------------------------------- 工具
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

    def _get_channels(self):
        if self._channels is not None:
            return self._channels
        self._ensure_session()
        try:
            st, raw = self._http(self.host + "/api/config.php")
            cfg = _json_of(raw)
            offline = set(str(x) for x in (cfg.get("offline_ids") or []))
            chs = []
            for c in (cfg.get("channels") or []):
                if not isinstance(c, dict):
                    continue
                if str(c.get("id")) in offline:
                    continue
                chs.append(c)
            self._channels = chs
        except Exception as e:
            print("[HDRip] config", e)
            self._channels = []
        return self._channels