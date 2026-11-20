# -*- coding: utf-8 -*-
# ============ POMO 4K (pomo.mom) TVBox/OK影视 Python Spider ============
# 修复要点(2026-11-20)：
# 1) 「线路加载播放失败」根因：站点近期影片的 route1Data/route2Data 基本为空(hasDbContent=false)，
#    站内播放器改为「自动搜索」链路取线路；原插件只读 routeData，详情页无任何线路。
#    本版在 routeData 为空时调用 api.php?type=auto_search 按标题匹配，展开各源选集作为线路。
# 2) play_url 内同时含 share/play 页面地址与直链 m3u8；parse 接口对页面地址常返回 500，
#    因此优先取 m3u8 线路，页面地址仅在无直链时透传给客户端并尝试 parse 兜底。
# 3) playerContent 按 5.8.8 约定返回 header(dict)/parse(int)/url，并带 Referer。
# 4) init 不联网；网络层用标准库 urllib+cookiejar，保持站点 cookie(X_CACHE_KEY/server_session)。
# 兼容 Python 3.8 及以下。
import sys, re, json, time, threading
import urllib.request, urllib.error, http.cookiejar, ssl
from urllib.parse import quote, unquote

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider(object):
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = urllib.request.Request(url, headers=headers or {})
            return urllib.request.urlopen(r, timeout=15)

# ============ ★ CONFIG ============
HOST = 'https://pomo.mom'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
CATEGORIES = {'huayurm': '华语热门', 'jiating': '家庭影院', 'donghuadadiany': '动画大电影',
              'lengmenjiapian': '冷门佳片', 'paihangbang': 'TOP250', 'sort/12': '蓝光原盘',
              'dianshiju': '剧集'}
API = HOST + '/content/plugins/plyr_player/api.php'
PLAYER = HOST + '/?plugin=plyr_player&gid=%s'
REFERER = HOST + '/'
MAX_LINES = 12
TIMEOUT = 20


class _Http(object):
    def __init__(self, ua=UA):
        self.ua = ua
        self.lock = threading.RLock()
        self.cj = http.cookiejar.CookieJar()
        self._noverify = False
        self.op = self._make_opener()

    def _make_opener(self):
        if self._noverify:
            ctx = ssl._create_unverified_context()
        else:
            ctx = ssl.create_default_context()
            try:
                import certifi
                ctx.load_verify_locations(certifi.where())
            except Exception:
                pass
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj),
                                           urllib.request.HTTPSHandler(context=ctx))

    def open(self, url, headers=None, timeout=TIMEOUT):
        hd = {'User-Agent': self.ua,
              'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
              'Accept-Language': 'zh-CN,zh;q=0.9',
              'Accept-Encoding': 'identity'}
        if headers:
            for k, v in headers.items():
                hd[k] = v
        req = urllib.request.Request(url, headers=hd)
        try:
            try:
                resp = self.op.open(req, timeout=timeout)
            except Exception as e1:
                if (not self._noverify) and ('CERTIFICATE_VERIFY_FAILED' in str(e1) or isinstance(e1, ssl.SSLError)):
                    self._noverify = True
                    self.op = self._make_opener()
                    resp = self.op.open(req, timeout=timeout)
                else:
                    raise
            body = resp.read()
            try:
                hh = dict(resp.headers)
            except Exception:
                hh = {}
            return resp.getcode(), body, resp.geturl(), hh
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b''
            try:
                hh = dict(e.headers or {})
            except Exception:
                hh = {}
            return e.code, body, url, hh
        except Exception:
            return 0, b'', url, {}

    @staticmethod
    def text(body, ctype=''):
        enc = 'utf-8'
        m = re.search(r'charset=([\w\-]+)', ctype or '')
        if m:
            enc = m.group(1)
        for e in (enc, 'utf-8', 'gbk'):
            try:
                return body.decode(e, 'ignore')
            except Exception:
                continue
        return ''

    def get(self, url, referer=REFERER, timeout=TIMEOUT):
        with self.lock:
            hd = {}
            if referer:
                hd['Referer'] = referer
            code, body, final, rh = self.open(url, headers=hd, timeout=timeout)
            if code >= 400 and code != 0:
                return ''
            return self.text(body, rh.get('Content-Type', ''))


class Spider(Spider):
    def init(self, extend=''):
        self.base = HOST.rstrip('/')
        self.ua = UA
        self.ref = REFERER
        self.types = dict(CATEGORIES)
        self._http = _Http(self.ua)   # 只建会话，不联网
        self._cache = {}              # vid -> (ts, pf, pu)
        self._search_cache = {}       # kw -> (ts, data)
        try:
            if extend and isinstance(extend, str) and '{' in extend:
                j = json.loads(extend)
                h = j.get('host') or j.get('base')
                if h:
                    self.base = str(h).rstrip('/')
        except Exception:
            pass

    # ========== 基础 ==========
    def _get(self, url, referer=None):
        if not url:
            return ''
        if not url.startswith('http'):
            url = self.base + '/' + url.lstrip('/')
        try:
            return self._http.get(url, referer or self.ref)
        except Exception:
            return ''

    def _api(self, params, referer=None):
        q = '&'.join(['%s=%s' % (k, v) for k, v in params.items()])
        txt = self._get(API + '?' + q, referer or self.ref)
        if not txt:
            return None
        try:
            return json.loads(txt)
        except Exception:
            try:
                return json.loads(txt[txt.find('{'):txt.rfind('}') + 1])
            except Exception:
                return None

    def _hdr(self):
        return {'User-Agent': self.ua, 'Referer': self.ref}

    @staticmethod
    def _u(s):
        if not s:
            return ''
        return re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)

    @staticmethod
    def _norm(s):
        s = (s or '').lower()
        s = re.sub(r'\(\d{4}\)|（\d{4}）', '', s)
        s = re.sub(r'[\s\-_·:：,，。.！!？?、/|]+', '', s)
        return s

    # ========== 列表 ==========
    def _items(self, html):
        if not html:
            return []
        items, seen = [], set()
        patterns = [
            r'<a href="https?://pomo\.mom/(\d+)(?:\.html)?" class="block h-full flex flex-col">([\s\S]*?)</a>',
            r'<a href="https?://pomo\.mom/(\d+)(?:\.html)?"[^>]*>([\s\S]*?)</a>',
            r'<a href="https?://pomo\.mom/(\d+)" class="hover:text-accent transition">([^<]+)</a>',
        ]
        for idx, pat in enumerate(patterns):
            for m in re.finditer(pat, html):
                vid = m.group(1)
                if vid in seen:
                    continue
                body = m.group(2)
                nm = re.search(r'<h3[^>]*>([\s\S]*?)</h3>', body) or re.search(r'<h2[^>]*>([\s\S]*?)</h2>', body)
                name = re.sub(r'<[^>]+>', '', nm.group(1)).strip() if nm else ''
                im = re.search(r'<img[^>]*src="(https?://[^"]+)"[^>]*alt="([^"]*)"', body)
                if not im:
                    im = re.search(r'<img[^>]*alt="([^"]*)"[^>]*src="(https?://[^"]+)"', body)
                if not name and im:
                    name = im.group(2).strip()
                if not name:
                    name = re.sub(r'<[^>]+>', '', body).strip()
                if not name or len(name) > 120:
                    continue
                if not im and idx == 2:
                    i0 = html.rfind('<img', 0, m.start())
                    im2 = re.search(r'src="(https?://[^"]+)"', html[i0:m.start()]) if i0 >= 0 else None
                    pic = im2.group(1) if im2 else ''
                else:
                    pic = im.group(1) if im else ''
                tags = re.findall(r'<div class="tag">(?:IMDB)?<span[^>]*>([^<]+)</span>|class="tag">([^<]+)<', body)
                seen.add(vid)
                items.append({'vod_id': vid, 'vod_name': name[:80], 'vod_pic': pic,
                              'vod_remarks': ''.join([x[0] or x[1] for x in tags])[:60]})
            if items:
                break
        return items

    def homeContent(self, filter=False):
        return {'class': [{'type_id': k, 'type_name': v} for k, v in self.types.items()],
                'list': self.homeVideoContent().get('list', [])}

    def homeVideoContent(self):
        return {'list': self._items(self._get(self.base + '/'))[:50]}

    def categoryContent(self, tid, pg=1, filter=False, extend=''):
        try:
            pn = max(int(str(pg)), 1)
        except Exception:
            pn = 1
        cat = str(tid)
        if cat not in self.types:
            cat = 'dianshiju'
        url = '%s/%s/page/%d' % (self.base, cat, pn) if pn > 1 else '%s/%s' % (self.base, cat)
        html = self._get(url)
        items = self._items(html)
        return {'page': pn, 'pagecount': self._pagecount(html, pn), 'limit': 24,
                'total': len(items), 'list': items}

    def _pagecount(self, html, cur=1):
        mx = cur
        for m in re.finditer(r'/page/(\d+)', html):
            try:
                mx = max(mx, int(m.group(1)))
            except Exception:
                pass
        return max(mx, cur)

    # ========== 详情 ==========
    def detailContent(self, ids, *args, **kwargs):
        vid = ''
        try:
            vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids or '')
        except Exception:
            vid = str(ids or '')
        m = re.search(r'(\d+)', vid)
        if not m:
            return {'list': []}
        vid = m.group(1)
        html = self._get('%s/%s' % (self.base, vid))
        if not html:
            return {'list': []}
        d = {'vod_id': vid, 'vod_name': '', 'vod_pic': '', 'vod_year': '', 'vod_area': '',
             'vod_class': '', 'vod_director': '', 'vod_actor': '', 'vod_content': '',
             'vod_remarks': '', 'vod_play_from': '', 'vod_play_url': ''}
        tn = re.search(r'<h2[^>]*x-dbjs-title[^>]*>([\s\S]*?)</h2>', html)
        raw_name = re.sub(r'<[^>]+>', '', tn.group(1)).strip() if tn else ''
        if not raw_name:
            t = re.search(r'<title>(.*?)</title>', html)
            raw_name = re.sub(r'\s*-\s*4K原盘免费下载\s*$', '', t.group(1)).strip() if t else ''
        ym = re.search(r'[（(]\s*(\d{4})\s*[）)]', raw_name)
        if ym:
            d['vod_year'] = ym.group(1)
        d['vod_name'] = re.sub(r'\s*[（(]\s*\d{4}\s*[）)]\s*', ' ', raw_name).strip()
        pm = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', html)
        if pm:
            d['vod_content'] = pm.group(1).strip()[:500]
        pi = re.search(r'src="(https?://[^"]*poster_[^"]+\.(?:jpg|jpeg|webp))"', html)
        if not pi:
            pi = re.search(r'src="(https?://[^"]+\.(?:jpg|jpeg|webp|png))"', html)
        if pi:
            d['vod_pic'] = pi.group(1)
        for key, pat in (('vod_director', r'导演：</span>([^<]+)<'), ('vod_area', r'国家：</span>([^<]+)<'),
                         ('vod_class', r'类型：</span>([^<]+)<')):
            mm = re.search(pat, html)
            if mm:
                d[key] = mm.group(1).strip()
        mags = re.findall(r'data-url="(magnet:[^"]+)"', html)
        if mags:
            d['vod_remarks'] = '%d个磁力源' % len(mags)

        # 1) 站内 DB 线路
        ph = self._get(PLAYER % vid)
        pf, pu = self._lines_from_page(ph, vid)
        # 2) 自动搜索线路：DB 为空时是唯一来源；DB 有线路时作为可切换备份(站点线路常失效)
        kw = ''
        sm = re.search(r'const\s+searchKeyword\s*=\s*"([^"]*)"', ph or '')
        if sm:
            kw = self._u(sm.group(1)).strip()
        if not kw:
            kw = self._keyword_of(d['vod_name'])
        apf, apu = self._lines_from_search(kw, d['vod_name'], d['vod_year'], vid)
        for _p, _u in zip(apf, apu):
            if _p in pf:
                continue
            pf.append(_p)
            pu.append(_u)
        if pf:
            d['vod_play_from'] = '$$$'.join(pf[:MAX_LINES])
            d['vod_play_url'] = '$$$'.join(pu[:MAX_LINES])
        return {'list': [d]}

    @staticmethod
    def _keyword_of(name):
        s = (name or '').strip()
        m = re.match(r'^([\u4e00-\u9fa5\u3000-\u303f\uff00-\uffef0-9！？：·]+)', s)
        if m and m.group(1).strip():
            return m.group(1).strip()
        return s.split(' ')[0] if ' ' in s else s

    # ---- DB 线路 ----
    def _routes(self, html):
        out = []
        if not html:
            return out
        has = dict(re.findall(r'const\s+hasRoute(\d+)\s*=\s*(true|false)', html))
        for num, data in re.findall(r'const\s+route(\d+)Data\s*=\s*(\[[\s\S]*?\]);', html):
            n = int(num)
            if n > 1 and has.get(str(n), 'true') != 'true':
                continue
            try:
                arr = json.loads(data)
            except Exception:
                try:
                    arr = json.loads(data.replace('\\/', '/'))
                except Exception:
                    arr = []
            if arr:
                out.append((n, arr))
        return out

    def _lines_from_page(self, html, vid):
        pf, pu = [], []
        for n, arr in self._routes(html):
            eps = self._eps_from_items(arr)
            if not eps:
                continue
            pf.append('线路%d' % n)
            pu.append('#'.join(['%s$%s' % (e[0], e[1]) for e in eps]))
        return pf, pu

    def _eps_from_items(self, arr):
        eps = []
        for item in arr:
            item = str(item)
            if '$' in item:
                nm, u = item.split('$', 1)
            else:
                nm, u = '播放', item
            nm = nm.strip() or '播放'
            u = u.strip()
            if not u:
                continue
            eps.append((nm.replace('#', '-').replace('$', '|'), u.replace(' ', '')))
        return eps

    # ---- 自动搜索线路 ----
    def _auto_search(self, wd):
        if not wd:
            return {}
        c = self._search_cache.get(wd)
        if c and time.time() - c[0] < 600:
            return c[1]
        res = self._api({'type': 'auto_search', 'wd': quote(wd)})
        data = (res or {}).get('data') or {}
        if data:
            self._search_cache[wd] = (time.time(), data)
        return data

    def _pick(self, arr, kw, name, year):
        kw_n, name_n = self._norm(kw), self._norm(name)
        best, best_score = None, -1
        for it in arr or []:
            n = self._norm(it.get('name'))
            if not n:
                continue
            score = 0
            if kw_n and n == kw_n:
                score = 4
            elif name_n and n == name_n:
                score = 3.5
            elif kw_n and n.startswith(kw_n):
                score = 2
            elif kw_n and kw_n in n:
                score = 1
            elif name_n and name_n in n:
                score = 0.8
            if score <= 0:
                continue
            if year and str(it.get('year') or '') == str(year):
                score += 0.6
            elif year and it.get('year'):
                score -= 1.2
            if score > best_score:
                best, best_score = it, score
        return best

    def _best_route(self, play_url):
        """从 play_url 的多条线路里优选 m3u8 直链线路。"""
        routes = [r for r in str(play_url or '').split('$$$') if r.strip()]
        cands = []
        for r in routes:
            eps = self._eps_from_items(r.split('#'))
            if not eps:
                continue
            m3u8 = sum(1 for e in eps if '.m3u8' in e[1].lower())
            cands.append((m3u8, len(eps), eps))
        if not cands:
            return []
        cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return cands[0][2]

    def _lines_from_search(self, kw, name, year, vid):
        data = self._auto_search(kw)
        if not data:
            return [], []
        pf, pu, used = [], [], set()
        order = list(data.keys())
        for src in order:
            it = self._pick(data.get(src), kw, name, year)
            if not it:
                continue
            eps = self._best_route(it.get('play_url'))
            if not eps:
                continue
            label = str(src).strip() or '源'
            base = label
            i = 2
            while label in used:
                label = '%s%d' % (base, i)
                i += 1
            used.add(label)
            pf.append(label)
            pu.append('#'.join(['%s$%s' % (e[0], e[1]) for e in eps]))
            if len(pf) >= MAX_LINES:
                break
        return pf, pu

    # ========== 搜索(站点搜索入口不稳定，仍保留) ==========
    def searchContent(self, key, quick=False, pg='1', *args, **kwargs):
        try:
            pn = max(int(str(pg)), 1)
        except Exception:
            pn = 1
        url = '%s/?keyword=%s' % (self.base, quote(str(key or '')))
        if pn > 1:
            url += '&page=%d' % pn
        html = self._get(url)
        items = self._items(html)
        return {'list': items, 'page': pn, 'pagecount': pn, 'limit': 24, 'total': len(items)}

    # ========== 播放 ==========
    def playerContent(self, flag, id, vipFlags=None, *args, **kwargs):
        u = str(id if id else flag or '').strip()
        if not u:
            return {'header': self._hdr(), 'parse': 0, 'url': ''}
        # 老格式 vid-线路-集数 兼容
        if not u.lower().startswith('http'):
            m = re.search(r'(\d+)-(\d+)-(\d+)', u)
            if m:
                pu = self._resolve_legacy(m.group(1), int(m.group(2)), int(m.group(3)))
                if pu:
                    return {'header': self._hdr(), 'parse': 0, 'url': pu}
            return {'header': self._hdr(), 'parse': 0, 'url': ''}
        if '.m3u8' in u.lower() or re.search(r'\.(mp4|flv)(\?|$)', u, re.I):
            return {'header': self._hdr(), 'parse': 0, 'url': u}
        # 页面地址: 先试站点 parse 接口，失败则交客户端嗅探
        j = self._api({'type': 'parse', 'url': quote(u, safe='')})
        real = (j or {}).get('data') if isinstance((j or {}).get('data'), str) else ''
        if real and real.startswith('http'):
            return {'header': self._hdr(), 'parse': 0, 'url': real}
        return {'header': self._hdr(), 'parse': 1, 'url': u}

    def _resolve_legacy(self, vid, rn, ei):
        html = self._get(PLAYER % vid)
        for n, arr in self._routes(html):
            if n != rn:
                continue
            eps = self._eps_from_items(arr)
            if 0 <= ei < len(eps):
                return eps[ei][1]
        return ''

    # ========== 扩展钩子 ==========
    def getName(self):
        return 'POMO4K'

    def isVideoFormat(self, url):
        return bool(url) and ('.m3u8' in url or bool(re.search(r'\.(mp4|flv)(\?|$)', url, re.I)))

    def manualVideoCheck(self):
        return False

    def getDependence(self):
        return ''

    def localProxy(self, param):
        p = str(param)
        if 'url=' in p:
            p = p.split('url=', 1)[1]
        p = unquote(p)
        if not p.startswith('http'):
            return {'code': 404, 'content': b'', 'headers': {}}
        code, body, final, rh = self._http.open(p, headers={'Referer': self.ref, 'User-Agent': self.ua})
        if code not in (200, 206):
            return {'code': code or 404, 'content': b'', 'headers': {}}
        return {'code': 200, 'content': body,
                'headers': {'Content-Type': rh.get('Content-Type', 'application/octet-stream')}}

    def destroy(self):
        self._cache.clear()
        self._search_cache.clear()