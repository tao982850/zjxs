import re, json, time
try:
    import requests as _requests
except Exception:
    _requests = None

try:
    from urllib.parse import quote as _quote, urljoin as _urljoin
except Exception:
    _quote = None
    _urljoin = None


def _q(s):
    if _quote is not None:
        return _quote(str(s))
    try:
        import urllib.parse
        return urllib.parse.quote(str(s))
    except Exception:
        return str(s)


def _uj(base, rel):
    """urljoin 兜底：rel 已 http 开头原样返回；否则拼到 base 目录。"""
    if _urljoin is not None:
        return _urljoin(base, rel)
    if rel.startswith(("http://", "https://")):
        return rel
    if rel.startswith("//"):
        return "https:" + rel
    root = base.split("?", 1)[0]
    dirn = root.rsplit("/", 1)[0] + "/"
    return dirn + rel.lstrip("/")


class Spider:
    """U酷影视 MacCMS10 provide/vod JSON 接口源（2026-10-19 实测 uku.u酷真流站）。"""

    def __init__(self):
        self.site = "https://api.ukuapi.com/api.php/provide/vod/"
        self.name = "U酷影视"
        self.header = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": "https://www.ukuapi.com/",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "application/json, text/plain, */*",
        }
        self.s = self.session = self.sess = _requests.Session() if _requests else None
        self._extend = {}
        self._class_cache = None
        # 有内容的叶子分类 id（2026-10-19 对 29 个分类逐个 ac=videolist&t= 实测；
        # 1/2 是父级聚合 id 返回 0 条，26/27/28/30/31 资讯类实测空；
        # 其余 22 个叶子全部有内容）
        self.leaf_ids = set([3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 20, 21, 22,
                             23, 24, 25, 32, 33, 34])
        # 分类兜底表：实测 ac=type（2026-10-19，共 29 类）
        self.cats_fallback = [
            {"type_id": "1", "type_name": "电影"}, {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "3", "type_name": "综艺"}, {"type_id": "4", "type_name": "动漫"},
            {"type_id": "6", "type_name": "动作片"}, {"type_id": "7", "type_name": "喜剧片"},
            {"type_id": "8", "type_name": "爱情片"}, {"type_id": "9", "type_name": "科幻片"},
            {"type_id": "10", "type_name": "恐怖片"}, {"type_id": "11", "type_name": "剧情片"},
            {"type_id": "12", "type_name": "战争片"}, {"type_id": "13", "type_name": "国产剧"},
            {"type_id": "14", "type_name": "港澳剧"}, {"type_id": "15", "type_name": "日剧"},
            {"type_id": "16", "type_name": "欧美剧"}, {"type_id": "20", "type_name": "动漫电影"},
            {"type_id": "21", "type_name": "台湾剧"}, {"type_id": "22", "type_name": "韩剧"},
            {"type_id": "23", "type_name": "泰剧"}, {"type_id": "24", "type_name": "记录片"},
            {"type_id": "", "type_name": ""}, {"type_id": "26", "type_name": "资讯"},
            {"type_id": "27", "type_name": "新闻资讯"}, {"type_id": "28", "type_name": "预告资讯"},
            {"type_id": "30", "type_name": "影视资讯"}, {"type_id": "31", "type_name": "明星资讯"},
            {"type_id": "32", "type_name": "短剧"}, {"type_id": "33", "type_name": "奇幻片"},
            {"type_id": "34", "type_name": "犯罪片"},
        ]
        self._from_name = {
            "ukm3u8": "U酷m3u8", "ukyun": "U酷云", "no": "U酷备线",
        }

    # ---------------- 壳通用钩子 ----------------
    def getDependence(self):
        return []

    def manualVideoCheck(self):
        return False

    def isVideoFormat(self, url):
        if not url:
            return False
        u = str(url).lower()
        return u.endswith((".m3u8", ".mp4", ".flv", ".mkv", ".ts", ".avi")) or "m3u8" in u

    def destroy(self):
        pass

    def action(self, action):
        return {}

    def init(self, extend=""):
        self._extend = {}
        if isinstance(extend, dict):
            self._extend = extend
        elif isinstance(extend, str) and extend.strip():
            try:
                e = json.loads(extend)
                if isinstance(e, dict):
                    self._extend = e
            except Exception:
                pass

    # ---------------- 网络层（requests -> urllib，含退避重试） ----------------
    def _get(self, url, referer=None, tries=3):
        last = ""
        for i in range(tries):
            h = dict(self.header)
            if referer:
                h["Referer"] = referer
            if self.s is not None:
                try:
                    r = self.s.get(url, headers=h, timeout=15)
                    if r.status_code < 400 and r.text:
                        return r.text
                    last = "http_%s" % r.status_code
                except Exception as e:
                    last = str(e)[:60]
            try:
                import urllib.request
                req = urllib.request.Request(url, headers=h)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = resp.read().decode("utf-8", "ignore")
                    if body:
                        return body
                    last = "empty_body"
            except Exception as e:
                last = str(e)[:60]
            if i < tries - 1:
                time.sleep(0.5 * (i + 1))
        return ""

    def _api(self, query):
        if not query.startswith("?"):
            query = "?" + query
        txt = self._get(self.site + query)
        if not txt:
            return None
        try:
            d = json.loads(txt)
        except Exception:
            return None
        return d if isinstance(d, dict) else None

    def _u(self, u):
        if not u:
            return u
        u = str(u).strip()
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        if u.startswith("/"):
            m = re.match(r"(https?://[^/]+)", self.site)
            return (m.group(1) if m else self.site) + u
        return self.site.rstrip("/") + "/" + u.lstrip("/")

    # ---------------- 分类 ----------------
    def _cats(self):
        if self._class_cache is not None:
            return self._class_cache
        leaf = {str(x) for x in (self.leaf_ids or [])}
        out = []
        d = self._api("ac=type")
        if d and d.get("code") == 1:
            for c in d.get("class") or []:
                tid = str(c.get("type_id") or "").strip()
                nm = str(c.get("type_name") or "").strip()
                if tid and nm and (not leaf or tid in leaf):
                    out.append({"type_id": tid, "type_name": nm})
        if not out:
            out = [dict(x) for x in self.cats_fallback
                   if str(x["type_id"]) in leaf]
        self._class_cache = out
        return out

    # ---------------- 列表 ----------------
    def _pack(self, x):
        x = x or {}
        return {
            "vod_id": str(x.get("vod_id") or ""),
            "vod_name": x.get("vod_name") or "",
            "vod_pic": self._u(x.get("vod_pic") or ""),
            "vod_remarks": x.get("vod_remarks") or "",
        }

    def homeContent(self, filter=None):
        cats = self._cats()
        d = self._api("ac=videolist&pg=1")
        if not d or d.get("code") != 1:
            d = self._api("ac=list&pg=1")
        lst = [self._pack(x) for x in (d or {}).get("list") or []]
        return {"class": cats, "list": lst}

    def homeVideoContent(self):
        d = self._api("ac=videolist&pg=1")
        if not d or d.get("code") != 1:
            d = self._api("ac=list&pg=1")
        return {"list": [self._pack(x) for x in (d or {}).get("list") or []]}

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        d = self._api("ac=videolist&pg=%d&t=%s" % (pg, _q(tid)))
        if not d or d.get("code") != 1:
            d = self._api("ac=list&pg=%d&t=%s" % (pg, _q(tid)))
        if not d or d.get("code") != 1:
            return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}
        lst = d.get("list") or []
        try:
            pc = int(d.get("pagecount") or 1)
        except Exception:
            pc = 1
        try:
            total = int(d.get("total") or len(lst))
        except Exception:
            total = len(lst)
        return {"list": [self._pack(x) for x in lst],
                "page": pg,
                "pagecount": pc if pc > 0 else 1,
                "limit": len(lst) or 20,
                "total": total}

    # ---------------- 详情 ----------------
    def _clean(self, s):
        if not s:
            return ""
        s = re.sub(r"<[^>]+>", "", str(s))
        s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
             .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
        return s.strip()

    def _playable(self, u):
        u = str(u or "").lower()
        return (u.endswith((".m3u8", ".mp4", ".flv", ".mkv", ".ts", ".avi"))
                or "m3u8" in u or "/share/" in u)

    def _fname(self, raw):
        r = str(raw or "").strip().lower()
        return self._from_name.get(r, raw)

    @staticmethod
    def _extract_m3u8(txt):
        """从 /share/ 播放页 HTML 提取内嵌 m3u8 路径（var main → playlist JSON → 任意根相对）。"""
        if not txt:
            return None
        m = re.search(r'var\s+main\s*=\s*"([^"]+\.m3u8)"', txt)
        if m:
            return m.group(1).strip()
        m = re.search(r'"url"\s*:\s*"([^"]+\.m3u8)"', txt)
        if m:
            return m.group(1).strip()
        m = re.search(r'["\'](/[^"\']+\.m3u8)["\']', txt)
        if m:
            return m.group(1).strip()
        return None

    @staticmethod
    def _abs_share(share_url, path):
        """share 页内嵌的是根相对路径（/20261019/xxx/index.m3u8）→ 拼 share 页自身 host。"""
        if path.startswith("http"):
            return path
        if path.startswith("//"):
            return "https:" + path
        m = re.match(r"(https?://[^/]+)", share_url or "")
        host = m.group(1) if m else "https://ukzy.ukubf3.com"
        return host + path

    def _resolve_share(self, share_url):
        """抓 ukyun /share/ 播放页，提取内嵌 m3u8 并绝对化。"""
        txt = self._get(share_url, tries=2)
        if not txt:
            return None
        p = self._extract_m3u8(txt)
        return self._abs_share(share_url, p) if p else None

    def _play(self, e):
        pf = str((e or {}).get("vod_play_from") or "")
        pu = str((e or {}).get("vod_play_url") or "")
        if not pu or "http" not in pu:
            return "", ""
        froms = pf.split("$$$") if pf else []
        groups = pu.split("$$$")
        of, ou = [], []
        for i, g in enumerate(groups):
            segs = []
            for seg in g.split("#"):
                seg = seg.strip()
                if not seg:
                    continue
                if "$" in seg:
                    n, u = seg.split("$", 1)
                else:
                    n, u = "", seg
                u = u.strip()
                if not self._playable(u):
                    continue
                segs.append("%s$%s" % ((n or "正片").strip(), u))
            if not segs:
                continue
            nm = froms[i].strip() if i < len(froms) and froms[i].strip() else ("线路%d" % (i + 1))
            of.append(self._fname(nm))
            ou.append("#".join(segs))
        return "$$$".join(of), "$$$".join(ou)

    def detailContent(self, ids):
        vid = ids
        if isinstance(ids, (list, tuple)):
            vid = ids[0] if ids else ""
        vid = str(vid or "").strip()
        if not vid:
            return {"list": []}
        d = self._api("ac=detail&pg=1&ids=%s" % _q(vid))
        if not d or d.get("code") != 1:
            return {"list": []}
        lst = d.get("list") or []
        if not lst:
            return {"list": []}
        e = lst[0] or {}
        pf, pu = self._play(e)
        return {"list": [{
            "vod_id": vid,
            "vod_name": e.get("vod_name") or "",
            "vod_pic": self._u(e.get("vod_pic") or ""),
            "vod_remarks": e.get("vod_remarks") or "",
            "vod_year": e.get("vod_year") or "",
            "vod_area": e.get("vod_area") or "",
            "vod_actor": e.get("vod_actor") or "",
            "vod_director": e.get("vod_director") or "",
            "vod_content": self._clean(e.get("vod_content") or ""),
            "vod_play_from": pf,
            "vod_play_url": pu,
        }]}

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick=False, pg="1"):
        k = str(key or "").strip()
        if not k:
            return {"list": []}
        d = self._api("ac=videolist&pg=1&wd=%s" % _q(k))
        if not d or d.get("code") != 1:
            d = self._api("ac=detail&wd=%s" % _q(k))
        if not d or d.get("code") != 1:
            return {"list": []}
        return {"list": [self._pack(x) for x in d.get("list") or []]}

    # ---------------- 播放 ----------------
    def playerContent(self, flag, ids, vipFlags=None):
        url = ids
        if isinstance(ids, (list, tuple)):
            url = ids[0] if ids else ""
        url = str(url or "").strip()
        if "$" in url:
            url = url.split("$")[-1].strip()
        if not url:
            return {"parse": 0, "url": "", "header": dict(self.header)}
        if not url.startswith("http"):
            url = self._u(url)
        # ukyun /share/ 播放页：页面内嵌真流 m3u8（var main / playlist JSON），
        # 抓页提取后绝对化到 share 页自身 host
        if "/share/" in url:
            real = self._resolve_share(url)
            if real:
                url = real
            else:
                return {"parse": 0, "url": "", "header": dict(self.header)}
        # 中继模式开关：init(extend) 传 {"play":"proxy"} 时才走壳代理中继；
        # 默认直返远程 m3u8（ukzy 视频 CDN 直连无封锁，播放器按标准 HLS 自行解析根相对分片）
        try:
            if str((self._extend or {}).get("play", "")).lower() in ("proxy", "relay"):
                low = url.lower()
                if low.endswith(".m3u8") or "m3u8" in low:
                    # 双层嵌套母列表（master→子清单→裸分片）且分片为主机根相对路径，
                    # 交给 localProxy 逐层重写为 proxy://do=ts，兼容解析不了基准的壳
                    try:
                        return {"parse": 0,
                                "url": "proxy://do=m3u8&url=%s" % _q(url),
                                "header": dict(self.header)}
                    except Exception:
                        pass
        except Exception:
            pass
        return {"parse": 0, "url": url, "header": dict(self.header)}

    # ---------------- 本地代理（m3u8 重写 + ts 中继 + 图片透传） ----------------
    def _host_candidates(self, url):
        """uku 视频 CDN（ukzy.ukubf3.com）直连无封锁，原 URL 直达即可；
        不再枚举未经验证的备选主机（每次失败要吃满超时）。"""
        return [url]

    def _fetch_fb(self, url, tries=2):
        """按候选主机逐个拉取，返回 (可用URL, bytes, content-type)；全失败 (None, None, None)。"""
        for u in self._host_candidates(url):
            for i in range(tries):
                h = dict(self.header)
                if self.s is not None:
                    try:
                        r = self.s.get(u, headers=h, timeout=15)
                        if r.status_code < 400:
                            return u, r.content, r.headers.get("Content-Type")
                    except Exception:
                        pass
                try:
                    import urllib.request
                    req = urllib.request.Request(u, headers=h)
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        return u, resp.read(), resp.headers.get("Content-Type")
                except Exception:
                    pass
                time.sleep(0.4 * (i + 1))
        return None, None, None

    def _rewrite_m3u8(self, base, text):
        """把 m3u8 内所有 URI 行改写成壳代理 URL（层数不限，支持嵌套母列表）。"""
        out = []
        for line in text.splitlines():
            s = line.strip()
            if not s:
                out.append(line)
                continue
            if s.startswith("#"):
                m = re.search(r'URI="([^"]+)"', line)
                if m:
                    absu = _uj(base, m.group(1).strip())
                    prox = "proxy://do=ts&url=%s" % _q(absu)
                    line = line[:m.start(1)] + prox + line[m.end(1):]
                out.append(line)
                continue
            if s.startswith("http"):
                absu = s
            elif s.startswith("//"):
                absu = "https:" + s
            else:
                absu = _uj(base, s)
            if ".m3u8" in absu.lower().split("?")[0]:
                out.append("proxy://do=m3u8&url=%s" % _q(absu))
            else:
                out.append("proxy://do=ts&url=%s" % _q(absu))
        return "\n".join(out)

    def localProxy(self, param):
        p = param if isinstance(param, dict) else {}
        url = p.get("url") or ""
        do = p.get("do") or ""
        # 兼容个别壳把整串 proxy://... 塞进 url 的情况
        if url.startswith("proxy://"):
            qs = url.split("?", 1)[1] if "?" in url else ""
            kv = {}
            for x in qs.split("&"):
                if "=" in x:
                    k, v = x.split("=", 1)
                    kv[k] = v
            try:
                from urllib.parse import unquote as _uq
                if kv.get("url"):
                    url = _uq(kv["url"])
                if kv.get("do"):
                    do = kv["do"]
            except Exception:
                pass
        if not url:
            return [403, "text/plain", b"", None]
        # 播放列表：多主机兜底拉取 + 全量 URI 重写
        if do == "m3u8" or url.lower().endswith(".m3u8") or "/share/" in url:
            wu, data, ct = self._fetch_fb(url)
            if data is None:
                return [403, "text/plain", b"", None]
            # 兜底：壳可能把 /share/ 播放页 URL 直接喂进来 → 识别 HTML 并提取页内 m3u8
            if not (data[:7] == b"#EXTM3U" or b"#EXT-X-" in data[:512]):
                p = self._extract_m3u8(data.decode("utf-8", "ignore"))
                if p:
                    wu2, data2, ct2 = self._fetch_fb(self._abs_share(wu or url, p))
                    if data2 is not None:
                        wu, data, ct = wu2, data2, ct2
            if not (data[:7] == b"#EXTM3U" or b"#EXT-X-" in data[:512]):
                return [403, "text/plain", b"", None]
            text = data.decode("utf-8", "ignore")
            return [200, "application/vnd.apple.mpegurl",
                    self._rewrite_m3u8(wu, text), None]
        # 分片/密钥/其他：字节中继 + 内容嗅探（.jpeg 伪扩展名 TS → video/mp2t）
        wu, data, ct = self._fetch_fb(url)
        if data is None:
            return [403, "text/plain", b"", None]
        if data[:7] == b"#EXTM3U" or b"#EXT-X-" in data[:512]:
            return [200, "application/vnd.apple.mpegurl",
                    self._rewrite_m3u8(wu, data.decode("utf-8", "ignore")), None]
        if data[:1] == b"\x47":
            return [200, "video/mp2t", data, None]
        if data[:3] == b"\xff\xd8\xff":
            return [200, "image/jpeg", data, None]
        if data[:4] == b"\x89PNG":
            return [200, "image/png", data, None]
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return [200, "image/gif", data, None]
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return [200, "image/webp", data, None]
        return [200, ct or "application/octet-stream", data, None]


def _html_unescape(s):
    import html as _h
    return _h.unescape(s) if s else s
