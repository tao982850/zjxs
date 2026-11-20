# -*- coding: utf-8 -*-
# ============ 剧踪影院 (juzong01.me) TVBox/OK影视 Python Spider ============
# 站点性质：苹果CMS(maccms10) + stui 主题，但站方**关闭了标准 JSON 采集接口**：
#   - api.php/provide/vod 一律 301 重写回首页
#   - index.php/ajax/data 可用，但忽略 wd/search/keyword 等任何搜索参数，也不支持 ac=detail
#   - 站内搜索(index.php/vod/search)被 tncode 人机验证拦截，联想接口已关闭
# 因此本插件的数据入口为：
#   列表：index.php/ajax/data?mid=1&tid=<分类>&limit=&page=      (可用，含名称/封面/年份/地区)
#   详情：/voddetail/<vod_id>/                                   (可用，含 11 条线路 × 各集)
#   播放：/vodplay/<vid>-<sid>-<nid>/ 页内的 player_data.url(加密串)
#         → GET https://jzpic.ok1333.cn/?<query> 拿 WGART_PARSE_TOKEN
#         → GET https://jzpic.ok1333.cn/wgart/api.php?action=try_json_api&video_url=<加密串>&parse_token=<token>
#         → 返回 data.url 为真实直链(实测 206 video/mp4，ftypisom 可播)
# 注意：播放页对非中国大陆网络会显示"国内专线资源，仅支持中国大陆网络访问"，
#       解析接口本身仍可返回地址；播放器网页侧的提示不影响本插件取流。
# 兼容 Python 3.8 及以下。
import sys, re, json, time, threading
import urllib.request, urllib.error, http.cookiejar, ssl
from urllib.parse import quote

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider(object):
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = urllib.request.Request(url, headers=headers or {})
            return urllib.request.urlopen(r, timeout=20)

# ============ ★ CONFIG ============
HOST = 'https://www.juzong01.me'
PIC_HOST = 'https://jzpic.ok1333.cn'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
# 一级分类：type_id 与名称（实测 1=电影 29653 条、2=剧集 20901 条、3=动漫 12006 条；
# 站点无综艺数据，tid=5 返回 0 条，故不列出，需要时改这里即可）
CATS = [('1', '电影'), ('2', '剧集'), ('3', '动漫')]
API = HOST + '/index.php/ajax/data'
TIMEOUT = 15
MAX_LINES = 12          # 线路最多展示条数（该站详情页常见 11 条）
DETAIL_TTL = 600        # 详情缓存(秒)
SCAN_PAGES = 4          # 搜索时每类扫描页数（站内搜索被墙，只能扫描最新页）

SID_SEASON = {'': 0}


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
              'Accept': 'text/html,application/json,application/xhtml+xml,*/*;q=0.8',
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

    def get(self, url, referer=HOST + '/', timeout=TIMEOUT):
        with self.lock:
            hd = {}
            if referer:
                hd['Referer'] = referer
            code, body, final, rh = self.open(url, headers=hd, timeout=timeout)
            if code >= 400 or code == 0:
                return ''
            return self.text(body, rh.get('Content-Type', ''))

    def get_json(self, url, referer=HOST + '/', timeout=TIMEOUT):
        txt = self.get(url, referer=referer, timeout=timeout)
        if not txt:
            return {}
        try:
            return json.loads(txt)
        except Exception:
            try:
                return json.loads(txt[txt.find('{'):txt.rfind('}') + 1])
            except Exception:
                return {}


class Spider(Spider):
    def init(self, extend=''):
        self.host = HOST.rstrip('/')
        self.pic_host = PIC_HOST.rstrip('/')
        self.ua = UA
        self.http = _Http(self.ua)
        self.cats = list(CATS)
        self._detail_cache = {}
        self._tok_cache = {}
        try:
            if extend and str(extend).strip().startswith('{'):
                cfg = json.loads(extend)
                if cfg.get('host'):
                    self.host = str(cfg['host']).rstrip('/')
                cm = cfg.get('cats')
                if isinstance(cm, list) and cm:
                    self.cats = [(str(x[0]), str(x[1])) for x in cm
                                 if isinstance(x, (list, tuple)) and len(x) >= 2]
        except Exception:
            pass

    # ============ 工具 ============
    @staticmethod
    def _norm(s):
        s = str(s or '').lower()
        s = re.sub(r'\(\d{4}\)|（\d{4}）', '', s)
        s = re.sub(r'[\s\-_·:：,，。.！!？?、/|]+', '', s)
        return s

    @staticmethod
    def _clean(s):
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', str(s or ''))).strip()

    def _abs(self, u):
        if not u:
            return ''
        u = str(u).strip()
        if u.startswith('//'):
            return 'https:' + u
        if u.startswith('/'):
            return self.host + u
        return u

    def _api_list(self, tid, page, limit=20, mid=1):
        url = '%s?mid=%s&tid=%s&limit=%d&page=%d' % (API, mid, quote(str(tid)), limit, page)
        return self.http.get_json(url, referer=self.host + '/')

    def _api_list_nolock(self, tid, page, limit=30, mid=1):
        """不带会话锁的列表请求：_Http.get() 内部有锁会把并发压成串行，搜索并发走这里。"""
        url = '%s?mid=%s&tid=%s&limit=%d&page=%d' % (API, mid, quote(str(tid)), limit, page)
        try:
            code, body, final, rh = self.http.open(
                url, headers={'Referer': self.host + '/'}, timeout=12)
            if code >= 400 or not body:
                return {}
            txt = self.http.text(body, rh.get('Content-Type', ''))
            try:
                return json.loads(txt)
            except Exception:
                return json.loads(txt[txt.find('{'):txt.rfind('}') + 1])
        except Exception:
            return {}

    def _items_from_api(self, j):
        out = []
        for it in (j.get('list') or []):
            if not isinstance(it, dict):
                continue
            vid = str(it.get('vod_id') or '').strip()
            nm = str(it.get('vod_name') or '').strip()
            if not vid or not nm:
                continue
            pic = it.get('vod_pic') or it.get('vod_pic_thumb') or ''
            out.append({
                'vod_id': vid,
                'vod_name': nm,
                'vod_pic': self._abs(pic),
                'vod_remarks': str(it.get('vod_remarks') or '')[:60],
            })
        return out

    # ============ 首页 / 分类 ============
    def homeContent(self, filter=False):
        clazz = [{'type_id': k, 'type_name': v} for k, v in self.cats]
        return {'class': clazz, 'list': self.homeVideoContent().get('list', [])}

    def homeVideoContent(self):
        tid = self.cats[0][0] if self.cats else '1'
        j = self._api_list(tid, 1, 20)
        items = self._items_from_api(j)
        if items:
            return {'list': items[:40]}
        # 兜底：换第一个分类再取一次
        for t, _n in self.cats[1:]:
            j = self._api_list(t, 1, 20)
            items = self._items_from_api(j)
            if items:
                return {'list': items[:40]}
        return {'list': []}

    def categoryContent(self, tid, pg=1, filter=False, extend=''):
        try:
            pn = max(int(str(pg)), 1)
        except Exception:
            pn = 1
        t = str(tid or '1')
        if t not in [k for k, _ in self.cats]:
            # 兼容传分类名
            for k, n in self.cats:
                if self._norm(n) == self._norm(t):
                    t = k
                    break
            else:
                t = self.cats[0][0] if self.cats else '1'
        j = self._api_list(t, pn, 20)
        items = self._items_from_api(j)
        total = 0
        try:
            total = int(j.get('total') or 0)
        except Exception:
            total = 0
        pages = 0
        try:
            pages = int(j.get('pagecount') or 0)
        except Exception:
            pages = 0
        if pages <= 0 and total > 0:
            pages = (total + 19) // 20
        return {'page': pn, 'pagecount': max(pages, pn), 'limit': 20,
                'total': total or len(items), 'list': items}

    # ============ 详情 ============
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

        cached = self._detail_cache.get(vid)
        if cached and time.time() - cached[0] < DETAIL_TTL:
            return {'list': [cached[1]]}

        html = self.http.get('%s/voddetail/%s/' % (self.host, vid), referer=self.host + '/')
        if not html:
            return {'list': []}

        d = {'vod_id': vid, 'vod_name': '', 'vod_pic': '', 'vod_year': '', 'vod_area': '',
             'vod_class': '', 'vod_director': '', 'vod_actor': '', 'vod_content': '',
             'vod_remarks': '', 'vod_play_from': '', 'vod_play_url': ''}

        h1 = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', html)
        if h1:
            d['vod_name'] = self._clean(h1.group(1))[:80]
        if not d['vod_name']:
            t = re.search(r'<title>(.*?)</title>', html, re.S)
            if t:
                d['vod_name'] = re.sub(r'\s*-\s*[^-]*$', '', self._clean(t.group(1))).strip()[:80]

        pi = re.search(r'<img[^>]+class="[^"]*lazyload[^"]*"[^>]+src="([^"]+)"', html)
        if not pi:
            pi = re.search(r'<img[^>]+class="[^"]*lazyload[^"]*"[^>]+data-original="([^"]+)"', html)
        if not pi:
            pi = re.search(r'<img[^>]+data-original="([^"]+)"', html)
        if pi:
            d['vod_pic'] = self._abs(pi.group(1))

        pm = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', html)
        if pm:
            d['vod_content'] = self._clean(pm.group(1))[:500]
        if not d['vod_content']:
            pc = re.search(r'<span class="detail-content"[^>]*>([\s\S]{0,1500}?)</span>', html)
            if pc:
                d['vod_content'] = self._clean(pc.group(1))[:500]

        def _info(label):
            # 只取到下一个标签为止，避免把「地区…年份…」串在一起
            mm = re.search(label + r'：?</span>([^<]{1,40})', html)
            if not mm:
                mm = re.search(label + r'：?\s*([^<\s]{1,40})', html)
            if not mm:
                return ''
            return self._clean(mm.group(1))[:40]

        d['vod_area'] = _info('地区')
        y = _info('年份')
        d['vod_year'] = y[:4] if re.match(r'^\d{4}', y) else ''
        ty = re.search(r"类型：?</span><a[^>]*>([^<]+)</a>", html)
        if ty:
            d['vod_class'] = self._clean(ty.group(1))[:40]
        dr = re.search(r'导演：?</span>([\s\S]{0,200}?)</p>', html)
        if dr:
            d['vod_director'] = self._clean(dr.group(1))[:60]
        ac = re.search(r'主演：?</span>([\s\S]{0,900}?)</p>', html)
        if ac:
            names = re.findall(r'>([^<>]{1,20})</a>', ac.group(1))
            d['vod_actor'] = ','.join([n.strip() for n in names if n.strip()])[:120]

        # 播放页链接：/vodplay/<vid>-<sid>-<nid>/  —— 每条 sid 是一路，nid 是集
        links = re.findall(r'href="(/vodplay/%s-(\d+)-(\d+)/)"' % re.escape(vid), html)
        eps = {}
        for _path, sid, nid in links:
            try:
                si, ni = int(sid), int(nid)
            except Exception:
                continue
            eps.setdefault(si, {})[ni] = (ni, '%s-%d-%d' % (vid, si, ni))
        if eps:
            pf, pu = [], []
            for si in sorted(eps.keys())[:MAX_LINES]:
                items = eps[si]
                nm = '第%d集' % 1
                pl = []
                for ni in sorted(items.keys()):
                    ep = items[ni]
                    nm = ('第%d集' % ni) if len(items) > 1 else '正片'
                    pl.append('%s$%s' % (nm, ep[1]))
                pf.append('线路%d' % si)
                pu.append('#'.join(pl))
            if pf:
                d['vod_play_from'] = '$$$'.join(pf)
                d['vod_play_url'] = '$$$'.join(pu)
                d['vod_remarks'] = '%d条线路' % len(pf)

        self._detail_cache[vid] = (time.time(), d)
        return {'list': [d]}

    # ============ 播放 ============
    def _token_of(self, enc, vid, nid, name, year):
        """取 jzpic 播放器页里的 WGART_PARSE_TOKEN（按加密串缓存）。"""
        key = enc[:60]
        c = self._tok_cache.get(key)
        if c and time.time() - c[0] < 300:
            return c[1]
        q = '&'.join([
            'url=' + quote(enc),
            'name=' + quote(name or ''),
            'id=' + quote(str(vid)),
            'ep=' + quote(str(nid)),
            'source_index=' + quote(str(nid)),
            'episode_title=' + quote('正片'),
            'year=' + quote(str(year or '')),
        ])
        page = self.http.get(self.pic_host + '/?' + q,
                             referer='%s/vodplay/%s-1-%s/' % (self.host, vid, nid), timeout=12)
        if not page:
            return ''
        m = re.search(r'WGART_PARSE_TOKEN\s*=\s*"([^"]+)"', page)
        if not m:
            return ''
        tok = m.group(1)
        self._tok_cache[key] = (time.time(), tok)
        return tok

    def _resolve(self, enc, vid, nid, name, year):
        tok = self._token_of(enc, vid, nid, name, year)
        url = '%s/wgart/api.php?action=try_json_api&video_url=%s' % (self.pic_host, quote(enc))
        if tok:
            url += '&parse_token=' + quote(tok)
        j = self.http.get_json(url, referer=self.pic_host + '/', timeout=15)
        if isinstance(j, dict):
            data = j.get('data') or {}
            if isinstance(data, dict) and data.get('url'):
                return str(data['url'])
        return ''

    def playerContent(self, flag, id, vipFlags=None, *args, **kwargs):
        raw = str(id or '')
        m = re.search(r'(\d+)-(\d+)-(\d+)', raw)
        if not m:
            if re.match(r'^https?://', raw):
                return {'header': {'User-Agent': self.ua}, 'parse': 0, 'url': raw}
            return {'header': {'User-Agent': self.ua}, 'parse': 0, 'url': ''}
        vid, sid, nid = m.group(1), m.group(2), m.group(3)

        page = self.http.get('%s/vodplay/%s-%s-%s/' % (self.host, vid, sid, nid),
                             referer='%s/voddetail/%s/' % (self.host, vid), timeout=15)
        if not page:
            return {'header': {'User-Agent': self.ua}, 'parse': 0, 'url': ''}
        pd = {}
        mm = re.search(r'player_data\s*=\s*(\{[\s\S]*?\})\s*</script>', page)
        if not mm:
            mm = re.search(r'player_data\s*=\s*(\{[\s\S]*?\})\s*;', page)
        if mm:
            try:
                pd = json.loads(mm.group(1))
            except Exception:
                pd = {}
        enc = str(pd.get('url') or '')

        # 详情页信息（片名/年份）用于解析接口，缺失不影响主流程
        info = self._detail_cache.get(vid)
        name = year = ''
        if info:
            name = info[1].get('vod_name') or ''
            year = info[1].get('vod_year') or ''

        real = ''
        if enc:
            real = self._resolve(enc, vid, nid, name, year)
        if not real:
            # 兜底：把播放页交给客户端解析
            return {'header': {'User-Agent': self.ua, 'Referer': self.host + '/'},
                    'parse': 1, 'url': '%s/vodplay/%s-%s-%s/' % (self.host, vid, sid, nid)}

        hd = {'User-Agent': self.ua}
        if self.host and self.host in real:
            hd['Referer'] = self.host + '/'
        return {'header': hd, 'parse': 0, 'url': real}

    # ============ 搜索（站内搜索被 tncode 拦截，改为扫描最新页） ============
    def searchContent(self, key, quick=False, pg='1', *args, **kwargs):
        kw = str(key or '').strip()
        if not kw:
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 20, 'total': 0}
        try:
            pn = max(int(str(pg)), 1)
        except Exception:
            pn = 1
        kn = self._norm(kw)
        found, seen = [], set()

        def _collect(j):
            for it in self._items_from_api(j):
                nm = self._norm(it['vod_name'])
                if not nm or it['vod_id'] in seen:
                    continue
                if kn and (kn in nm or nm in kn):
                    seen.add(it['vod_id'])
                    found.append(it)

        if quick:
            # 站内搜索被 tncode 拦截，只能扫描最新页；并发取各分类首页，既快也不漏
            res, ths = {}, []
            for t, _n in self.cats:
                def w(t=t):
                    res[t] = self._api_list_nolock(t, 1, 30)
                th = threading.Thread(target=w)
                th.setDaemon(True)
                th.start()
                ths.append(th)
            for th in ths:
                try:
                    th.join(6)
                except Exception:
                    pass
            for t, _n in self.cats:
                _collect(res.get(t) or {})
        else:
            for t, _n in self.cats:
                for p in range(1, SCAN_PAGES + 1):
                    _collect(self._api_list(t, p, 30))
                    if len(found) >= 60:
                        break
                if len(found) >= 60:
                    break
        return {'list': found, 'page': pn, 'pagecount': max(pn, 1),
                'limit': 20, 'total': len(found)}

    def getName(self):
        return '剧踪影院'

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv)(\?|$)', str(url or ''), re.I))

    def manualVideoCheck(self):
        return False