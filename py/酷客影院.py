# -*- coding: utf-8 -*-
"""酷客影院（www.8886m.com）TVBox / OK影视（FongMi/影视系）Python 插件。

本次修复的"无法播放"根因：
    详情页的线路顺序里，第一条"优酷视频"线路返回的 m3u8 是一个**占位清单**——
    它拿到的是 /cache/xiuluo_m3u8/<片名>.m3u8，里面的分片根本不是视频，
    而是图片 CDN 上的 png（picasso-static.xiaohongshu.com/file/xxx.png）
    或空文件名的 qpic.cn 地址（https://mmcomm.qpic.cn/cross_fb/0/hf_..._0/）。
    这种清单播放器能下载、却解码不出画面，表现就是"点了没反应 / 无法播放"。
    上一版把它当成"中文路径未编码"处理，编码后照样拉不到流，所以问题依旧。

本次做法：
    1. 播放时先解析被点击线路；若判定为占位清单（图片/空分片），
       自动按线路顺序换到同片同一集的下一条线路，直到拿到真实含 .ts 分片的流；
       全部都不行时再退回 parse=1 交给客户端嗅探。
    2. 只在被点击线路确实不可播时才做上述探测，正常线路不做额外请求。
    3. 保留上一版修复：首页分类空元组崩溃、中文直链百分号编码。

注意：站点侧部分线路（如 ppvod*.blbtgg.com、ppvod*.kqgfbs.com）对机房/代理 IP
      返回 403，属站点/CDN 侧限制，脚本无法绕过；换线路逻辑会自动避开它们。
"""
import re, json, base64
try:
    import requests as _requests
except Exception:
    _requests = None

MEDIA_SUFFIX = (".m3u8", ".mp4", ".flv", ".mkv", ".ts", ".avi", ".mp3", ".m4a")


class Spider:
    def __init__(self):
        self.site = "https://www.8886m.com"
        self.name = "酷客影院"
        self.header = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": self.site,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self.s = self.session = self.sess = _requests.Session() if _requests else None
        self._extend = {}
        self._home = None
        self.cats = [(1, "电影"), (2, "电视剧"), (3, "动漫"), (4, "综艺")]
        self.areas = ["大陆", "中国大陆", "香港", "台湾", "日本", "韩国", "美国", "英国", "泰国", "德国", "法国", "印度", "俄罗斯", "西班牙", "意大利", "加拿大", "澳大利亚", "新加坡", "中国香港", "欧美"]
        self.years = [str(y) for y in range(2026, 1999, -1)]

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

    def _get(self, url, referer=None, timeout=12):
        h = dict(self.header)
        if referer:
            h["Referer"] = referer
        if self.s is not None:
            try:
                r = self.s.get(url, headers=h, timeout=timeout, allow_redirects=True)
                if r.status_code < 400:
                    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
                        r.encoding = "utf-8"
                    return r.text
            except Exception:
                pass
        try:
            import urllib.request
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception:
            return ""

    def _post(self, url, data):
        h = dict(self.header)
        h["Content-Type"] = "application/x-www-form-urlencoded"
        if self.s is not None:
            try:
                r = self.s.post(url, headers=h, data=data, timeout=12, allow_redirects=True)
                if r.status_code < 400:
                    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
                        r.encoding = "utf-8"
                    return r.text
            except Exception:
                pass
        try:
            import urllib.request
            import urllib.parse
            body = urllib.parse.urlencode(data).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=h)
            with urllib.request.urlopen(req, timeout=12) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception:
            return ""

    def _u(self, u):
        if not u:
            return u
        u = u.strip()
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        if u.startswith("/"):
            m = re.match(r"(https?://[^/]+)", self.site)
            return (m.group(1) if m else self.site) + u
        return self.site.rstrip("/") + "/" + u.lstrip("/")

    def _absolute(self, base, u):
        """把可能的相对地址补成绝对地址（用于 m3u8 里的子清单/分片）。"""
        u = str(u or "").strip()
        if not u:
            return u
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        try:
            import urllib.parse
            return urllib.parse.urljoin(base, u)
        except Exception:
            return self._u(u)

    def _encode(self, u):
        # 站点部分线路的 m3u8 直链路径含中文（如 /cache/xiuluo_m3u8/谷雨EP01.m3u8），
        # 未编码时部分 TVBox 播放内核无法请求，表现为点播无反应/无法播放；
        # 这里仅对非 ASCII 字符做百分号编码，保留 URL 原有结构。
        if not u:
            return u
        try:
            import urllib.parse
            return urllib.parse.quote(str(u), safe=":/?#[]@!$&'()*+,;=%")
        except Exception:
            return u

    def _clean(self, s):
        if not s:
            return ""
        s = re.sub(r"<[^>]+>", "", s)
        import html as _h
        return _h.unescape(s).strip()

    # ---------- 列表解析 ----------
    def _items(self, html):
        out, seen = [], set()
        for bm in re.finditer(r"<li[^>]*>([\s\S]{0,3000}?)</li>", html):
            block = bm.group(1)
            hm = re.search(r'href="(/edu-\d+\.html)"', block)
            if not hm:
                continue
            vid = self._u(hm.group(1))
            if vid in seen:
                continue
            im = re.search(r'data-original="([^"]+)"', block)
            if not im:
                im = re.search(r"background:\s*url\(([^)]+)\)", block)
            if not im:
                continue
            nm = re.search(r'<h[34][^>]*>\s*<a[^>]*>([^<]{1,60})</a>', block)
            if nm:
                title = self._clean(nm.group(1))
            else:
                tm = re.search(r'title="([^"]+)"', block)
                title = self._clean(tm.group(1)) if tm else ""
            if not title:
                continue
            seen.add(vid)
            rm = re.search(r'<span class="pic-text[^"]*">([^<]{1,30})</span>', block)
            item = {"vod_id": vid, "vod_name": title,
                    "vod_pic": self._u(im.group(1)) if im else "",
                    "vod_remarks": rm.group(1).strip() if rm else ""}
            tm = re.search(r"类型：</span>\s*<a[^>]+href=\"/list/(\d+)\.html\"", block)
            if tm:
                item["_tid"] = int(tm.group(1))
            ym = re.search(r"年份：</span>\s*<a[^>]+href=\"/year\.php\?searchword=(\d+)\"", block)
            if ym:
                item["_year"] = ym.group(1)
            am = re.search(r"地区：</span>\s*<a[^>]+href=\"/area\.php\?searchword=([^\"]+)\"", block)
            if am:
                import urllib.parse
                item["_area"] = urllib.parse.unquote(am.group(1))
            out.append(item)
        for am in re.finditer(r'<a[^>]+href="(/edu-\d+\.html)"[^>]*>', html):
            tag = am.group(0)
            if "stui-vodlist__thumb" not in tag:
                continue
            vid = self._u(am.group(1))
            if vid in seen:
                continue
            im = re.search(r'data-original="([^"]+)"', tag)
            if not im:
                im = re.search(r"background:\s*url\(([^)]+)\)", tag)
            if not im:
                continue
            tm = re.search(r'title="([^"]+)"', tag)
            title = self._clean(tm.group(1)) if tm else ""
            if not title:
                continue
            seen.add(vid)
            seg = html[am.end():am.end() + 300]
            rm = re.search(r'<span class="pic-text[^"]*">([^<]{1,30})</span>', seg)
            remarks = rm.group(1).strip() if rm else ""
            if remarks == title:
                remarks = ""
            out.append({"vod_id": vid, "vod_name": title,
                        "vod_pic": self._u(im.group(1)),
                        "vod_remarks": remarks})
        return out

    def _pagecount(self, html, tid):
        m = re.search(r'href="/list/%d_(\d+)\.html"[^>]*>尾页' % tid, html)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
        nums = [int(n) for n in re.findall(r'href="/list/%d_(\d+)\.html"' % tid, html)]
        if nums:
            return max(nums)
        return 1

    def _home_html(self):
        if self._home is None:
            self._home = self._get(self.site)
        return self._home or ""

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

    def homeContent(self, filter=None):
        cats = [{"type_id": str(c), "type_name": n} for c, n in self.cats]
        filters = {}
        for c, n in self.cats:
            filters[str(c)] = [
                {"key": "area", "name": "地区", "value": [{"n": "全部", "v": ""}] + [{"n": a, "v": a} for a in self.areas]},
                {"key": "year", "name": "年份", "value": [{"n": "全部", "v": ""}] + [{"n": y, "v": y} for y in self.years]},
            ]
        vod_list = self._items(self._home_html())
        return {"class": cats, "filters": filters, "list": vod_list}

    def homeVideoContent(self):
        return {"list": self._items(self._home_html())}

    def _media_list(self, tid, area, year):
        import urllib.parse
        if area:
            url = self.site + "/area.php?searchword=" + urllib.parse.quote(area)
        else:
            url = self.site + "/year.php?searchword=" + urllib.parse.quote(year)
        html = self._get(url)
        if not html:
            return []
        out = []
        for it in self._items(html):
            if it.get("_tid") is not None and it["_tid"] != tid:
                continue
            if area and year and it.get("_year") is not None and it["_year"] != year:
                continue
            it.pop("_tid", None)
            it.pop("_year", None)
            it.pop("_area", None)
            out.append(it)
        return out

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        try:
            tid = int(tid)
        except Exception:
            tid = 1
        ext = extend if isinstance(extend, dict) else {}
        area = str(ext.get("area") or "")
        year = str(ext.get("year") or "")
        if area or year:
            if pg > 1:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 26, "total": 0}
            items = self._media_list(tid, area, year)
            return {"list": items, "page": 1, "pagecount": 1, "limit": 26, "total": 0}
        if pg <= 1:
            url = self.site + "/list/%d.html" % tid
        else:
            url = self.site + "/list/%d_%d.html" % (tid, pg)
        html = self._get(url)
        if not html:
            return {"list": [], "page": pg, "pagecount": 1, "limit": 26, "total": 0}
        items = self._items(html)
        return {"list": items, "page": pg, "pagecount": self._pagecount(html, tid), "limit": 26, "total": 0}

    def _playlines(self, html):
        """从详情页解析线路：返回 [(线路名, [(集名, 播放页地址), ...]), ...]"""
        sources = []
        tm = re.search(r'<ul class="nav nav-tabs[^>]*>([\s\S]{0,1500}?)</ul>', html)
        if tm:
            for a in re.finditer(r'href="#down(\d+)"[^>]*>([^<]{1,30})</a>', tm.group(1)):
                sources.append((int(a.group(1)) - 1, self._clean(a.group(2))))
        eps = {}
        seen_ep = set()
        for em in re.finditer(r'href="(/gov-(\d+)-(\d+)-(\d+)\.html)"[^>]*>([^<]{1,20})</a>', html):
            href, _vid, frm, _ep, name = em.group(1), em.group(2), int(em.group(3)), int(em.group(4)), self._clean(em.group(5))
            if name in ("立即播放", ""):
                continue
            if href in seen_ep:
                continue
            seen_ep.add(href)
            eps.setdefault(frm, []).append((name, self._u(href)))
        if not sources:
            sources = [(f, "线路%d" % (f + 1)) for f in sorted(eps)]
        out = []
        for frm, name in sources:
            if frm in eps and eps[frm]:
                out.append((name, eps[frm]))
        return out

    def detailContent(self, ids):
        vid = ids
        if isinstance(ids, (list, tuple)):
            vid = ids[0] if ids else ""
        vid = str(vid or "").strip()
        if not vid:
            return {"list": []}
        url = vid if vid.startswith("http") else self._u(vid)
        html = self._get(url)
        if not html:
            return {"list": []}
        title = ""
        tm = re.search(r'<h1[^>]*>([^<]{1,80})</h1>', html)
        if tm:
            title = self._clean(tm.group(1))
        if not title:
            tm = re.search(r"<title>([^<]{1,80})</title>", html)
            if tm:
                title = self._clean(tm.group(1)).split("_")[0].split("《")[-1].replace("》", "").strip()
        im = re.search(r'<img[^>]+data-original="([^"]+)"', html)
        if not im:
            im = re.search(r'property="og:image" content="([^"]+)"', html)
        pic = self._u(im.group(1)) if im else ""
        desc = ""
        dm = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.){10,2000})"', html)
        if dm:
            desc = self._clean(dm.group(1).replace("\\/", "/"))
        if not desc:
            dm = re.search(r'<p class="desc[^"]*"[^>]*>([\s\S]{10,2000}?)</p>', html)
            if dm:
                desc = self._clean(dm.group(1))
        director = ""
        dm = re.search(r"导演：</span>([\s\S]{0,200}?)</p>", html)
        if dm:
            director = self._clean(dm.group(1))
        actor = ""
        am = re.search(r"主演：</span>([\s\S]{0,3000}?)</p>", html)
        if am:
            actor = ", ".join([self._clean(a) for a in re.findall(r"<a[^>]*>([^<]{1,20})</a>", am.group(1)) if self._clean(a)])
        year = ""
        ym = re.search(r"年份：</span><a[^>]*>([^<]{1,10})</a>", html)
        if ym:
            year = ym.group(1).strip()
        area = ""
        rm = re.search(r"地区：</span><a[^>]*>([^<]{1,10})</a>", html)
        if rm:
            area = rm.group(1).strip()
        remarks = ""
        pm = re.search(r'<span class="pic-text[^"]*">([^<]{1,30})</span>', html)
        if pm:
            remarks = pm.group(1).strip()
        play_from, play_url = [], []
        for name, eps in self._playlines(html):
            play_from.append(name)
            play_url.append("#".join("%s$%s" % (en, eu) for en, eu in eps))
        return {"list": [{"vod_id": vid, "vod_name": title, "vod_pic": pic,
                          "vod_actor": actor, "vod_director": director,
                          "vod_year": year, "vod_area": area,
                          "vod_remarks": remarks, "vod_content": desc,
                          "vod_play_from": "$$$".join(play_from),
                          "vod_play_url": "$$$".join(play_url)}]}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        data = {"searchword": str(key)}
        if pg > 1:
            data["page"] = str(pg)
        html = self._post(self.site + "/search.php", data)
        if not html:
            return {"list": [], "page": pg, "pagecount": 1, "limit": 26, "total": 0}
        items = self._items(html)
        pc = 1
        m = re.search(r"共\s*(\d+)\s*页", html)
        if m:
            try:
                pc = int(m.group(1))
            except Exception:
                pass
        return {"list": items, "page": pg, "pagecount": pc, "limit": 26, "total": 0}

    # ---------- 播放 ----------
    def _resolve_page(self, playurl):
        """把播放页解析成直链：返回 (kind, media_url, referer)。
        kind: 'media'（拿到直链）/ 'page'（没有直链，可能要靠客户端嗅探）/ 'none'"""
        if not playurl:
            return ("none", "", self.site)
        if not playurl.startswith("http"):
            playurl = self._u(playurl)
        u = playurl.lower()
        if u.endswith(MEDIA_SUFFIX) or "m3u8" in u or ".mp4" in u:
            return ("media", playurl, self.site)
        html = self._get(playurl, referer=self.site)
        if not html:
            return ("page", playurl, self.site)
        ref = playurl
        im = re.search(r'<iframe[^>]+src="([^"]+)"', html)
        if im:
            iframe = self._u(im.group(1))
            phtml = self._get(iframe, referer=playurl)
            if phtml:
                html = phtml
                ref = iframe
        found = ""
        for pat in (r'id:\s*"([^"]+\.m3u8[^"]*)"',
                    r'url\s*[:=]\s*[\'"]([^\'"]+\.m3u8[^\'"]*)[\'"]',
                    r'(https?://[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*)'):
            mm = re.search(pat, html)
            if mm:
                found = mm.group(1)
                break
        if not found:
            return ("page", playurl, self.site)
        found = found.strip().rstrip('";,')
        found = self._absolute(ref, found)
        return ("media", found, ref)

    def _segment_lines(self, text):
        out = []
        for ln in (text or "").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                out.append(ln)
        return out

    def _looks_media(self, u):
        """分片是否像真正的视频分片（站点占位清单的分片是图片 / 空文件名）。"""
        ul = str(u).lower()
        if re.search(r"\.(ts|mp4|m4s|m4v|m4a|aac|flv|mkv|avi|mp3|fmp4)(\?|$|~|[#])", ul):
            return True
        if "/hls/" in ul or "/hls_" in ul:
            return True
        if u.rstrip("/") != u:          # 空文件名（如 https://mmcomm.qpic.cn/cross_fb/0/hf_xxx_0/）
            return False
        return False

    def _classify(self, media, ref=None):
        """判定直链是否真能出画面：'real' / 'decoy' / 'unknown'。

        站点第一条"优酷视频"线路的 /cache/xiuluo_m3u8/*.m3u8 是占位清单，
        分片指向图片 CDN（xiaohongshu 的 .png、qpic 的空文件名、抖音图床的 .image），
        播放器能下载清单却解码不出画面。这里只要清单里没有任何像视频的分片，
        就判为占位。
        """
        if not media:
            return "unknown"
        ul = media.lower()
        if ul.endswith((".mp4", ".flv", ".mkv", ".ts", ".avi", ".mp3", ".m4a")) and "m3u8" not in ul:
            return "real"
        if "m3u8" not in ul:
            return "unknown"
        text = self._get(media, referer=ref, timeout=8)
        if not text or "#EXTM3U" not in text:
            return "unknown"
        segs = self._segment_lines(text)
        if "EXT-X-STREAM-INF" in text and segs:
            sub = self._absolute(media, segs[0])
            t2 = self._get(sub, referer=ref, timeout=8)
            if t2 and "#EXTM3U" in t2:
                s2 = self._segment_lines(t2)
                if not s2:
                    return "unknown"
                return "real" if any(self._looks_media(self._absolute(sub, s)) for s in s2) else "decoy"
            return "unknown"
        if not segs:
            return "decoy"
        return "real" if any(self._looks_media(self._absolute(media, s)) for s in segs) else "decoy"

    def _fallback(self, playurl, flag):
        """当前线路不可播时，按线路顺序换到同片同一集的下一条线路。"""
        m = re.search(r"/gov-(\d+)-(\d+)-(\d+)\.html", str(playurl))
        if not m:
            return None
        vid = m.group(1)
        html = self._get(self.site.rstrip("/") + "/edu-%s.html" % vid)
        if not html:
            return None
        lines = self._playlines(html)
        if not lines:
            return None
        cur, cur_ep = None, 0
        for i, (_name, eps) in enumerate(lines):
            for j, (_en, eu) in enumerate(eps):
                if eu == playurl or eu.rstrip("/") == str(playurl).rstrip("/"):
                    cur, cur_ep = i, j
                    break
            if cur is not None:
                break
        best = None
        tried = 0
        for i, (name, eps) in enumerate(lines):
            if i == cur:
                continue
            if cur is None and name == flag:
                continue
            if not eps:
                continue
            tried += 1
            if tried > 4:
                break
            eu = eps[cur_ep if cur_ep < len(eps) else 0][1]
            kind, media, ref = self._resolve_page(eu)
            if kind != "media":
                continue
            cls = self._classify(media, ref)
            h = dict(self.header)
            h["Referer"] = ref
            cand = {"parse": 0, "url": self._encode(media), "header": h}
            if cls == "real":
                return cand
            if cls == "unknown" and best is None:
                best = cand
        return best

    def playerContent(self, flag, ids, vipFlags=None):
        url = ids
        if isinstance(ids, (list, tuple)):
            url = ids[0] if ids else ""
        url = str(url or "").strip()
        if not url:
            return {"parse": 0, "url": "", "header": dict(self.header)}
        if not url.startswith("http"):
            url = self._u(url)
        u = url.lower()
        if u.endswith(MEDIA_SUFFIX) or "m3u8" in u:
            return {"parse": 0, "url": self._encode(url), "header": dict(self.header)}
        kind, media, ref = self._resolve_page(url)
        if kind == "media":
            cls = self._classify(media, ref)
            if cls == "real":
                h = dict(self.header)
                h["Referer"] = ref
                return {"parse": 0, "url": self._encode(media), "header": h}
            # 占位清单（图片 / 空分片）或取数失败（线路被 CDN 拦 403/超时）→ 自动换线路
            alt = self._fallback(url, flag)
            if alt:
                return alt
            if cls == "decoy":
                return {"parse": 1, "url": self._encode(url), "header": dict(self.header)}
            h = dict(self.header)
            h["Referer"] = ref
            return {"parse": 0, "url": self._encode(media), "header": h}
        alt = self._fallback(url, flag)
        if alt:
            return alt
        return {"parse": 1, "url": self._encode(url), "header": dict(self.header)}

    def localProxy(self, param):
        u = param.get("url", "") if isinstance(param, dict) else ""
        if not u:
            return [403, "text/plain", b"", None]
        h = dict(self.header)
        if self.s is not None:
            try:
                r = self.s.get(u, headers=h, timeout=15)
                return [200, r.headers.get("Content-Type", "application/octet-stream"), r.content, None]
            except Exception:
                pass
        try:
            import urllib.request
            req = urllib.request.Request(u, headers=h)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return [200, resp.headers.get("Content-Type", "application/octet-stream"), resp.read(), None]
        except Exception:
            return [403, "text/plain", b"", None]