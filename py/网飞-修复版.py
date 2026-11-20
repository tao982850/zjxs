# -*- coding: utf-8 -*-
# ============ 网飞猫影视 (www.fjszjm.com) TVBox/OK影视 Python Spider ============
# 修复要点(2026-11-20):
# 1) 站点前置 Xcdn 机器人验证(HTTP 408 + "Bot detection" 页)，原版所有请求都被拦在验证页，
#    表现为「各分类空白」「点播取不到地址」。本版内置 PoW 自动验证 + cookie 保持 + 失效重解。
# 2) 影视 5.8.8 约定: playerContent 返回键集合恰为 header(dict)/parse(int)/url。
# 3) init 内不联网(5.8.8 上 init 探测易被判「爬虫失败」)，验证与主域探测延后到首次取数。
# 4) destroy 不再引用不存在的成员。
# 兼容 Python 3.8 及以下(不使用 3.9+ API)，网络层使用标准库 urllib + cookiejar。
import sys, re, json, time, base64, hashlib, threading, socket
import urllib.request, urllib.error, http.cookiejar, ssl
from urllib.parse import urljoin, quote, unquote

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider(object):  # 独立加载兜底(宿主无 base.spider)
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = urllib.request.Request(url, headers=headers or {})
            return urllib.request.urlopen(r, timeout=15)

# ============ ★ CONFIG ============
HOSTS = ['https://www.fjszjm.com']  # ★ 多域名轮询(主在前)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
CATEGORIES = {'1': '电影', '2': '电视剧', '3': '综艺', '4': '动漫', '5': '短剧'}  # ★ 一级
PK = ''
REFERER = 'https://www.fjszjm.com/'  # ★ 播放/资源防盗链 Referer
PIC_REFERER = 'https://www.fjszjm.com/'
PROBE = 0  # 详情多线路实测排序 1/0
SITE_KEY = 'fjszjm'
VIDEO_EXTS = 'm3u8|mp4|flv|mkv|avi|ts'
HTTP_TIMEOUT = 15
ORIGIN = re.match(r'(https?://[^/]+)', HOSTS[0]).group(1)


# ============ 带 Xcdn PoW 过验证的 HTTP 会话 ============
class _Http(object):
    """标准库会话: cookiejar 保持 __xcdn_captcha_verified，遇验证页自动解 PoW 重试。"""

    def __init__(self, ua=UA):
        self.ua = ua
        self.lock = threading.RLock()
        self.cj = http.cookiejar.CookieJar()
        self._noverify = False
        self.op = self._make_opener()

    def _make_opener(self):
        # 宿主(如 Android Chaquopy)可能没有可用 CA 根证书，验证失败时降级为不校验并记住
        if self._noverify:
            ctx = ssl._create_unverified_context()
        else:
            ctx = ssl.create_default_context()
            try:
                import certifi
                ctx.load_verify_locations(certifi.where())
            except Exception:
                pass
        handlers = [urllib.request.HTTPCookieProcessor(self.cj),
                    urllib.request.HTTPSHandler(context=ctx)]
        return urllib.request.build_opener(*handlers)

    # ---- 原始请求 ----
    def open(self, url, headers=None, timeout=HTTP_TIMEOUT):
        hd = {
            'User-Agent': self.ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'identity',
        }
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
            try:
                body = resp.read()
            except Exception:
                body = b''
            return resp.getcode(), body, resp.geturl(), dict(resp.headers)
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
        try:
            return body.decode(enc, 'ignore')
        except Exception:
            try:
                return body.decode('utf-8', 'ignore')
            except Exception:
                return ''

    @staticmethod
    def is_wall(code, txt):
        if code == 408:
            return True
        head = (txt or '')[:4000]
        if 'Bot detection' in head or '__xcdn/captcha' in head or 'pow-checkbox' in head:
            return True
        return False

    @staticmethod
    def origin_of(url):
        m = re.match(r'(https?://[^/]+)', url or '')
        return m.group(1) if m else ORIGIN

    # ---- PoW 求解 + 上报 ----
    def solve(self, origin):
        code, body, _, hd = self.open(origin + '/__xcdn/captcha/api/init',
                                      headers={'Accept': 'application/json'}, timeout=10)
        if code != 200:
            return False
        try:
            cfg = json.loads(self.text(body, hd.get('Content-Type', '')))
            challenge = str(cfg.get('challenge') or '')
            diff = int(cfg.get('difficulty') or 4)
        except Exception:
            return False
        if not challenge:
            return False
        diff = max(1, min(diff, 6))
        target = '0' * diff
        nonce, h = 0, ''
        t0 = time.time()
        while time.time() - t0 < 8:
            nonce += 1
            h = hashlib.sha256((challenge + str(nonce)).encode('utf-8')).hexdigest()
            if h[:diff] == target:
                break
        if h[:diff] != target:
            return False
        code2, _, _, _ = self.open(origin + '/__xcdn/captcha/api/verify', headers={
            'X-CDN-VERIFY-NONCE': str(nonce),
            'X-CDN-VERIFY-RESULT': h,
        }, timeout=10)
        return code2 == 200

    # ---- 对外: 取文本(自动过验证) ----
    def get(self, url, referer=None, timeout=HTTP_TIMEOUT):
        with self.lock:
            origin = self.origin_of(url)
            for _ in range(3):
                hd = {}
                if referer:
                    hd['Referer'] = referer
                code, body, final, rh = self.open(url, headers=hd, timeout=timeout)
                txt = self.text(body, rh.get('Content-Type', ''))
                if not self.is_wall(code, txt):
                    return txt if code < 400 else ''
                if not self.solve(origin):
                    time.sleep(0.2)
            return ''

    # ---- 对外: 取字节(流探测/代理) ----
    def get_bytes(self, url, headers=None, timeout=8):
        with self.lock:
            code, body, final, rh = self.open(url, headers=headers, timeout=timeout)
            return code, body, rh


# ============ AES 纯 Python 引擎(站点若启用加密播放可用) ============
SBOX = [99, 124, 119, 123, 242, 107, 111, 197, 48, 1, 103, 43, 254, 215, 171, 118, 202, 130, 201, 125, 250, 89, 71, 240, 173, 212, 162, 175, 156, 164, 114, 192, 183, 253, 147, 38, 54, 63, 247, 204, 52, 165, 229, 241, 113, 216, 49, 21, 4, 199, 35, 195, 24, 150, 5, 154, 7, 18, 128, 226, 235, 39, 178, 117, 9, 131, 44, 26, 27, 110, 90, 160, 82, 59, 214, 179, 41, 227, 47, 132, 83, 209, 0, 237, 32, 252, 177, 91, 106, 203, 190, 57, 74, 76, 88, 207, 208, 239, 170, 251, 67, 77, 51, 133, 69, 249, 2, 127, 80, 60, 159, 168, 81, 163, 64, 143, 146, 157, 56, 245, 188, 182, 218, 33, 16, 255, 243, 210, 205, 12, 19, 236, 95, 151, 68, 23, 196, 167, 126, 61, 100, 93, 25, 115, 96, 129, 79, 220, 34, 42, 144, 136, 70, 238, 184, 20, 222, 94, 11, 219, 224, 50, 58, 10, 73, 6, 36, 92, 194, 211, 172, 98, 145, 149, 228, 121, 231, 200, 55, 109, 141, 213, 78, 169, 108, 86, 244, 234, 101, 122, 174, 8, 186, 120, 37, 46, 28, 166, 180, 198, 232, 221, 116, 31, 75, 189, 139, 138, 112, 62, 181, 102, 72, 3, 246, 14, 97, 53, 87, 185, 134, 193, 29, 158, 225, 248, 152, 17, 105, 217, 142, 148, 155, 30, 135, 233, 206, 85, 40, 223, 140, 161, 137, 13, 191, 230, 66, 104, 65, 153, 45, 15, 176, 84, 187, 22]
IS = [0] * 256
for _i, _v in enumerate(SBOX):
    IS[_v] = _i
RCON = [1, 2, 4, 8, 16, 32, 64, 128, 27, 54, 108, 216, 171, 77]
G2 = [0] * 256
G3 = [0] * 256
for _i in range(256):
    _t = _i << 1
    if _i & 128:
        _t ^= 0x11b
    G2[_i] = _t
    G3[_i] = G2[_i] ^ _i


def _ke(k):
    nk = len(k) // 4
    nr = nk + 6
    w = [list(k[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        t = w[i - 1][:]
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            t = [SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w


def _enc(b, w):
    s = [[b[r + 4 * c] for c in range(4)] for r in range(4)]

    def add(r):
        for i in range(4):
            for j in range(4):
                s[i][j] ^= w[r * 4 + j][i]

    def sub():
        for i in range(4):
            for j in range(4):
                s[i][j] = SBOX[s[i][j]]

    def sh():
        for r in range(1, 4):
            s[r] = s[r][r:] + s[r][:r]

    def mx():
        for c in range(4):
            a = [s[r][c] for r in range(4)]
            s[0][c] = G2[a[0]] ^ G3[a[1]] ^ a[2] ^ a[3]
            s[1][c] = a[0] ^ G2[a[1]] ^ G3[a[2]] ^ a[3]
            s[2][c] = a[0] ^ a[1] ^ G2[a[2]] ^ G3[a[3]]
            s[3][c] = G3[a[0]] ^ a[1] ^ a[2] ^ G2[a[3]]

    add(0)
    nr = len(w) // 4 - 1
    for rnd in range(1, nr):
        sub()
        sh()
        mx()
        add(rnd)
    sub()
    sh()
    add(nr)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _dec(b, w):
    s = [[b[r + 4 * c] for c in range(4)] for r in range(4)]

    def add(r):
        for i in range(4):
            for j in range(4):
                s[i][j] ^= w[r * 4 + j][i]

    def isub():
        for i in range(4):
            for j in range(4):
                s[i][j] = IS[s[i][j]]

    def ish():
        for r in range(1, 4):
            s[r] = s[r][-r:] + s[r][:-r]

    def imx():
        for c in range(4):
            a = [s[r][c] for r in range(4)]
            s[0][c] = _gm(a[0], 14) ^ _gm(a[1], 11) ^ _gm(a[2], 13) ^ _gm(a[3], 9)
            s[1][c] = _gm(a[0], 9) ^ _gm(a[1], 14) ^ _gm(a[2], 11) ^ _gm(a[3], 13)
            s[2][c] = _gm(a[0], 13) ^ _gm(a[1], 9) ^ _gm(a[2], 14) ^ _gm(a[3], 11)
            s[3][c] = _gm(a[0], 11) ^ _gm(a[1], 13) ^ _gm(a[2], 9) ^ _gm(a[3], 14)

    nr = len(w) // 4 - 1
    add(nr)
    for rnd in range(nr - 1, 0, -1):
        ish()
        isub()
        add(rnd)
        imx()
    ish()
    isub()
    add(0)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _gm(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        a = (a << 1) ^ 0x11b if a & 0x80 else a << 1
        b >>= 1
    return p & 0xff


def aes_ecb(data, key, mode=1):
    w = _ke(key)
    out = b''
    if mode:
        pad = 16 - len(data) % 16
        data += bytes([pad]) * pad
        for i in range(0, len(data), 16):
            out += _enc(data[i:i + 16], w)
    else:
        for i in range(0, len(data), 16):
            out += _dec(data[i:i + 16], w)
        if out and 0 < out[-1] <= 16:
            out = out[:-out[-1]]
    return out


def aes_cbc(data, key, iv, enc=1):
    w = _ke(key)
    out = b''
    prev = iv
    if enc:
        pad = 16 - len(data) % 16
        data += bytes([pad]) * pad
        for i in range(0, len(data), 16):
            blk = bytes(data[i + j] ^ prev[j] for j in range(16))
            ct = _enc(blk, w)
            out += ct
            prev = ct
    else:
        for i in range(0, len(data), 16):
            blk = _dec(data[i:i + 16], w)
            out += bytes(blk[j] ^ prev[j] for j in range(16))
            prev = data[i:i + 16]
        if out and 0 < out[-1] <= 16:
            out = out[:-out[-1]]
    return out


class Spider(Spider):
    def init(self, extend=''):
        self.base = HOSTS[0].rstrip('/')
        self.ua = UA
        self.pk = PK
        self.ref = REFERER or (self.base + '/')
        self.types = dict(CATEGORIES)
        self._pc = {}
        self._srv = None
        self._http = _Http(self.ua)  # 不联网，仅建会话
        try:
            if extend and isinstance(extend, str):
                e = json.loads(extend)
                h = e.get('host') or e.get('base')
                if h:
                    self.base = str(h).rstrip('/')
                    self.ref = REFERER or (self.base + '/')
        except Exception:
            pass

    # ========== 取页 ==========
    def _get(self, url, referer=None, timeout=HTTP_TIMEOUT):
        if not url:
            return ''
        if not url.startswith('http'):
            url = urljoin(self.base, url)
        try:
            return self._http.get(url, referer or self.ref, timeout)
        except Exception:
            return ''

    def _pic(self, u):
        if not u:
            return ''
        if u.startswith('//'):
            u = 'https:' + u
        if not u.startswith('http'):
            u = urljoin(self.base + '/', u)
        return u

    def _hdr(self):
        h = {'User-Agent': self.ua}
        if self.ref:
            h['Referer'] = self.ref
        h['Origin'] = ORIGIN
        return h

    def _pagecount(self, h, cur=1):
        mx = cur
        m = re.search(r'href="([^"]*)"[^>]*>\s*尾页', h)
        if m:
            n = re.findall(r'-+(\d+)---\.html', m.group(1))
            if n:
                try:
                    mx = max(mx, int(n[-1]))
                except Exception:
                    pass
        for mm in re.finditer(r'/wfmwusw/[^"\']*?-+(\d+)---\.html', h):
            try:
                mx = max(mx, int(mm.group(1)))
            except Exception:
                pass
        if re.search(r'下一页|class="[^"]*next[^"]*"', h):
            mx = max(mx, cur + 1)
        return mx

    # ========== 首页 ==========
    def homeContent(self, filter=False):
        r = {'class': [{'type_id': k, 'type_name': v} for k, v in self.types.items()]}
        try:
            r['list'] = self.homeVideoContent().get('list', [])
        except Exception:
            r['list'] = []
        return r

    def homeVideoContent(self):
        h = self._get(self.base + '/')
        return {'list': self._items(h) if h else []}

    def homeVod(self):
        return self.homeVideoContent()

    # ========== 分类 ==========
    def categoryContent(self, tid, pg=1, filter=False, extend=''):
        try:
            pn = max(int(str(pg)), 1)
        except Exception:
            pn = 1
        t = str(tid)
        cls = ''
        if '|' in t:
            p = t.split('|')
            t = p[0]
            cls = p[1] if len(p) > 1 else ''
        h = self._get(self._cat_url(t, pn, cls))
        if not h:
            return {'page': pn, 'pagecount': 1, 'limit': 42, 'total': 0, 'list': []}
        items = self._items(h)
        return {'page': pn, 'pagecount': self._pagecount(h, pn), 'limit': 42, 'total': len(items), 'list': items}

    def _cat_url(self, t, pn, cls=''):
        if cls:  # 二级分类: /wfmwusw/{tid}---{class}-----{pg}---.html
            return '%s/wfmwusw/%s---%s-----%d---.html' % (self.base, t, quote(str(cls)), pn)
        return '%s/wfmwusw/%s--------%d---.html' % (self.base, t, pn)

    # ========== 详情 ==========
    def detailContent(self, ids, quick='1', *args, **kwargs):
        vid = ''
        try:
            vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids or '')
        except Exception:
            vid = str(ids or '')
        m = re.search(r'(\d+)', vid)
        vid = m.group(1) if m else ''
        if not vid:
            return {'list': []}
        h = self._get('%s/wfmwudt/%s.html' % (self.base, vid))
        if not h:
            return {'list': []}
        d = {'vod_id': vid, 'vod_name': '', 'vod_pic': '', 'vod_year': '', 'vod_area': '',
             'vod_class': '', 'vod_director': '', 'vod_actor': '', 'vod_content': '',
             'vod_remarks': '', 'vod_play_from': '', 'vod_play_url': ''}
        tn = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', h) or re.search(r'<title>([\s\S]*?)</title>', h)
        if tn:
            d['vod_name'] = re.sub(r'<[^>]+>', '', tn.group(1)).split('-')[0].replace('免费在线观看', '').replace('高清完整版', '').strip()
        p = re.search(r'data-original="([^"]+\.(?:jpg|jpeg|png|webp|gif))"', h, re.I)
        if not p:
            p = re.search(r'<img[^>]*(?:data-original|src)="([^"]+\.(?:jpg|jpeg|png|webp|gif))"', h, re.I)
        if p:
            d['vod_pic'] = self._pic(p.group(1))
        dm = re.search(r'class="detail-content"[^>]*>([\s\S]*?)</span>', h) or \
            re.search(r'class="[^"]*(?:vod-content|detail-sketch|detail-content)[^"]*"[^>]*>([\s\S]*?)</(?:span|div)>', h)
        if dm:
            d['vod_content'] = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', dm.group(1))).strip()[:500]
        for k, pat in (('vod_year', r'年份[：:]?\s*(\d{4})'),
                       ('vod_area', r'地区[：:]?\s*([^<\n]+?)(?:\s|</)'),
                       ('vod_class', r'(?:类型|分类)[：:]?\s*([^<\n]+?)(?:\s|</)'),
                       ('vod_remarks', r'更新[：:]</span>\s*([^<\n]+?)(?:\s|</)'),
                       ('vod_remarks', r'状态[：:]?\s*<[^>]*>([^<\n]+?)(?:</|\s|&)')):
            if d[k] == '':
                m2 = re.search(pat, h)
                if m2:
                    d[k] = re.sub(r'<[^>]+>', '', m2.group(1)).strip().replace('&nbsp;', ' ').replace('&amp;', '&').rstrip('，').strip()
        dm2 = re.search(r'导演[：:]\s*([\s\S]*?)(?:</p>|</div>|<div)', h)
        if dm2:
            d['vod_director'] = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', dm2.group(1))).strip().replace('&nbsp;', ' ').replace('&amp;', '&').rstrip('，').strip()
        ac = re.search(r'主演[：:]\s*([\s\S]*?)(?:</p>|</div>|<div)', h)
        if ac:
            d['vod_actor'] = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', ac.group(1))).strip().replace('&nbsp;', ' ').replace('&amp;', '&').rstrip('，').strip()
        pf, pu = self._play_sources(h)
        if pf:
            if PROBE and len(pf) > 1:
                pf, pu = self._sort_lines(pf, pu)
            d['vod_play_from'] = '$$$'.join(pf)
            d['vod_play_url'] = '$$$'.join(pu)
        return {'list': [d]}

    def _play_sources(self, h):
        pf, pu = [], []
        tab_names = {}
        for m in re.finditer(r'<a[^>]*href="#(playlist\d+)"[^>]*>([^<]+)</a>', h):
            n = m.group(2).strip()
            if n and len(n) < 20:
                tab_names[m.group(1)] = n
        parts = re.split(r'<div[^>]+id="(playlist\d+)"', h)
        for i in range(1, len(parts) - 1, 2):
            pid, seg = parts[i], parts[i + 1]
            cut = seg.find('</ul>')
            if cut > 0:
                seg = seg[:cut]
            links = re.findall(r'href="(/wfmwupy/\d+-\d+-\d+\.html)"[^>]*>([^<]*)</a>', seg)
            links = [x for x in links if 'app2' not in x[0] and 'zstv' not in x[0] and x[1].strip()]
            if not links:
                continue
            eps, seen = [], set()
            for href, ep in links:
                nm = ep.strip().replace('#', '-').replace('$', '|')
                if href in seen:
                    continue
                seen.add(href)
                eps.append('%s$%s' % (nm, urljoin(self.base + '/', href)))
            if not eps:
                continue
            pf.append(tab_names.get(pid, '线路%d' % (len(pf) + 1)))
            pu.append('#'.join(eps))
        if not pf:  # 兜底: 全局按线路号分组
            routes = {}
            for href, route, ep in re.findall(r'href="(/wfmwupy/\d+-(\d+)-\d+\.html)"[^>]*>([^<]*)</a>', h):
                if 'app2' in href or 'zstv' in href or not ep.strip():
                    continue
                nm = ep.strip().replace('#', '-').replace('$', '|')
                routes.setdefault(route, []).append('%s$%s' % (nm, urljoin(self.base + '/', href)))
            for i, route in enumerate(sorted(routes.keys(), key=lambda x: int(x) if x.isdigit() else 999)):
                pf.append(tab_names.get('playlist' + route, '线路%d' % (i + 1)))
                pu.append('#'.join(routes[route]))
        return pf, pu

    def _sort_lines(self, froms, urls):
        key = hashlib.md5('|'.join(froms).encode('utf-8')).hexdigest()
        c = self._pc.get(key)
        if c and time.time() - c[0] < 300:
            return c[1], c[2]

        def probe(i):
            u = urls[i].split('#')[0].rsplit('$', 1)[-1]
            try:
                return 0 if self._stream_ok(u, timeout=4) else 1
            except Exception:
                return 1

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(froms), 8)) as ex:
            res = list(ex.map(probe, range(len(froms))))
        pairs = sorted(list(zip(froms, urls, res)), key=lambda x: x[2])
        out = ([p[0] for p in pairs], [p[1] for p in pairs])
        self._pc[key] = [time.time()] + list(out)
        return out

    # ========== 搜索 ==========
    def searchContent(self, key, quick=False, pg='1', *args, **kwargs):
        try:
            pn = max(int(str(pg)), 1)
        except Exception:
            pn = 1
        k = quote(str(key or ''))
        h = self._get('%s/wfmwusc/%s----------%d---.html' % (self.base, k, pn))
        if not h:
            return {'list': [], 'page': pn, 'pagecount': 1, 'limit': 42, 'total': 0}
        items = self._items(h)
        mx = pn
        for mm in re.finditer(r'/wfmwusc/[^"\']*?-+(\d+)---\.html', h):
            try:
                mx = max(mx, int(mm.group(1)))
            except Exception:
                pass
        return {'list': items, 'page': pn, 'pagecount': max(mx, 1), 'limit': 42, 'total': len(items)}

    # ========== 播放 ==========
    def playerContent(self, flag, id, vipFlags=None, *args, **kwargs):
        page = str(id if id else flag or '')
        if not page:
            return {'header': self._hdr(), 'parse': 0, 'url': ''}
        if re.search(r'\.(m3u8|mp4|flv)(\?|$)', page, re.I):
            if not page.startswith('http'):
                page = urljoin(self.base + '/', page)
            return {'header': self._hdr(), 'parse': 0, 'url': page}
        full = page if page.startswith('http') else urljoin(self.base + '/', page)
        h = self._get(full)
        if not h:
            return {'header': self._hdr(), 'parse': 1, 'url': full}
        cands = self._cands(h, full, 0)
        for c in cands:
            if self._stream_ok(c, 5):
                return {'header': self._hdr(), 'parse': 0, 'url': c}
        if cands:
            return {'header': self._hdr(), 'parse': 0, 'url': cands[0]}
        return {'header': self._hdr(), 'parse': 1, 'url': full}

    def _cands(self, h, page_url, depth):
        out, seen = [], set()

        def add(u):
            if not u:
                return
            u = u.strip()
            if u.startswith('//'):
                u = 'https:' + u
            if u.startswith('/'):
                u = urljoin(page_url, u)
            if u.startswith('http') and u not in seen:
                seen.add(u)
                out.append(u)

        # 1) var player_xxxx = {...}
        for m in re.finditer(r'var\s+player_\w+\s*=\s*\{', h):
            j = self._json_at(h, m.end() - 1)
            if not j:
                continue
            u = j.get('url') or ''
            if u:
                add(self._dec(u))
            if j.get('url_next'):
                add(self._dec(j.get('url_next')))
            if u and not re.search(r'\.(m3u8|mp4|flv)(\?|$)', u, re.I) and j.get('encrypt'):
                add(self._dec(u, page_url))
        # 2) 页面内嵌直链
        for m in re.finditer(r'(https?://[^\s"\'<>]+\.(?:m3u8|mp4|flv)(?:\?[^\s"\'<>]*)?)', h):
            add(m.group(1))
        # 3) iframe 一层
        if depth < 1:
            for m in re.finditer(r'<iframe[^>]+src="([^"]+)"', h, re.I):
                u = m.group(1)
                if not u.startswith('http'):
                    u = urljoin(page_url, u)
                h2 = self._get(u)
                if h2:
                    for c in self._cands(h2, u, depth + 1):
                        add(c)
        return out

    @staticmethod
    def _json_at(h, start):
        depth, i, n = 0, start, len(h)
        in_str, esc = False, False
        while i < n:
            ch = h[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(h[start:i + 1])
                        except Exception:
                            return None
            i += 1
        return None

    def _dec(self, u):
        u = (u or '').strip().replace('\\/', '/')
        if re.search(r'\.(m3u8|mp4|flv)(\?|$)', u, re.I):
            return u
        if u.startswith('http'):
            return u
        try:
            s = u.encode('utf-8')
            s2 = base64.b64decode(s + b'=' * (-len(s) % 4))
            t = s2.decode('utf-8', 'ignore')
            if re.search(r'\.(m3u8|mp4|flv)', t, re.I) or t.startswith('http'):
                return t
        except Exception:
            pass
        return u

    def _stream_ok(self, u, timeout=5):
        if not u or not u.startswith('http'):
            return False
        code, body, rh = self._http.get_bytes(u, headers={'Referer': self.ref, 'Range': 'bytes=0-2047'}, timeout=timeout)
        if code not in (200, 206):
            return False
        ct = (rh.get('Content-Type', '') or '').lower()
        if 'image/' in ct or 'text/html' in ct or 'application/json' in ct:
            return False
        head = body[:2048]
        if head.startswith(b'#EXTM3U') or b'#EXT-X-' in head[:200]:
            return True
        if b'ftyp' in head[:64]:
            return True
        if 'mpegurl' in ct or ct.startswith('video/'):
            return True
        return False

    # ========== 四壳扩展钩子 ==========
    def isVideoFormat(self, url):
        if not url:
            return False
        if '.m3u8' in url:
            return True
        return bool(re.search(r'\.(?:%s)(?:\?|$)' % (VIDEO_EXTS or 'm3u8|mp4|flv'), url, re.I))

    def manualVideoCheck(self):
        return False

    def getDependence(self):
        return ''

    def destroy(self):
        try:
            self._pc.clear()
        except Exception:
            pass
        self._srv = None

    def progressVideo(self, speed, time_, end):
        return False

    def setVideoFlags(self, siteKey, flags):
        try:
            self._siteKey = siteKey or SITE_KEY
            self._vflags = flags or {}
        except Exception:
            pass

    # ========== 本地代理(m3u8 KEY/分片重写，直连失败时兜底) ==========
    def localProxy(self, param):
        p = param.split('url=', 1)[-1] if 'url=' in str(param) else str(param)
        p = unquote(p) if '%' in p else p
        if not p.startswith('http'):
            return {'code': 404, 'content': b'', 'headers': {}}
        if '.m3u8' in p:
            return self._rewrite_m3u8(p)
        code, body, rh = self._http.get_bytes(p, headers={'Referer': self.ref, 'User-Agent': self.ua}, timeout=20)
        if code != 200:
            return {'code': code or 404, 'content': b'', 'headers': {}}
        return {'code': 200, 'content': body, 'headers': {'Content-Type': rh.get('Content-Type', 'application/octet-stream')}}

    def _rewrite_m3u8(self, url):
        code, body, rh = self._http.get_bytes(url, headers={'Referer': self.ref, 'User-Agent': self.ua}, timeout=20)
        if code != 200:
            return {'code': code or 404, 'content': b'', 'headers': {}}
        try:
            txt = body.decode('utf-8', 'ignore')
        except Exception:
            txt = ''
        base = url.rsplit('/', 1)[0] + '/'
        m = re.match(r'https?://[^/]+', url)
        origin = m.group(0) if m else ''
        out = []
        for ln in txt.splitlines():
            if ln.startswith('#EXT-X-KEY'):
                mm = re.search(r'URI="([^"]+)"', ln)
                if mm:
                    ku = mm.group(1)
                    if ku.startswith('/'):
                        ku = origin + ku
                    elif not ku.startswith('http'):
                        ku = base + ku
                    ln = ln.replace('URI="%s"' % mm.group(1), 'URI="%s"' % ('proxy?url=' + quote(ku, safe='')))
            elif ln.startswith('http'):
                ln = 'proxy?url=' + quote(ln, safe='')
            elif ln.startswith('/') and not ln.startswith('//'):
                ln = 'proxy?url=' + quote(origin + ln, safe='')
            out.append(ln)
        return {'code': 200, 'content': '\n'.join(out),
                'headers': {'Content-Type': 'application/vnd.apple.mpegurl'}}

    # ========== 列表解析 ==========
    def _items(self, h):
        if not h:
            return []
        items, seen = [], set()
        pats = [r'href="/(?:voddetail|movie/index|detail|n|wfmwudt)/(\d+)\.html"[^>]*title="([^"]*)"',
                r'href="/(?:voddetail|movie/index|detail|n|wfmwudt)/(\d+)\.html"[^>]*>([\s\S]{0,200}?)</a>']
        for pat in pats:
            for m in re.finditer(pat, h):
                vid, name = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
                if not name or len(name) > 100:
                    continue
                after = h[m.end():m.end() + 900]
                cover = re.search(r'(?:data-original|data-src|original|src)="([^"]+\.(?:jpg|jpeg|png|webp|gif))"', after, re.I)
                remark = re.search(r'class="pic-text text-right"[^>]*>\s*<b>([^<]+)</b>', after)
                if not remark:
                    remark = re.search(r'class="(?:module-item-note|public-list-prb|remarks|status|pic-text1)[^"]*"[^>]*>([^<]+)<', after)
                if not remark:
                    remark = re.search(r'<div[^>]*class="[^"]*(?:note|text|remark)[^"]*"[^>]*>([^<]+)<', after, re.I)
                if vid not in seen:
                    seen.add(vid)
                    items.append({'vod_id': vid, 'vod_name': name[:50],
                                  'vod_pic': self._pic(cover.group(1)) if cover else '',
                                  'vod_remarks': remark.group(1).strip() if remark else ''})
            if items:
                break
        return items