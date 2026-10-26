#coding=utf-8
#!/usr/bin/python

# ============================================================
# CONFIG
# ============================================================
ENABLE_LOG_FILE       = False
ENABLE_HTML_DUMP      = False
ENABLE_CONSOLE_LOG    = True
LOG_DIR               = "/storage/emulated/0/Download/pgdj_debug"
MAX_HTML_DUMPS        = 100
ENABLE_URL_NORMALIZE  = True
STAR_MAX_PAGES        = 3   # jumlah halaman search yang di-fetch untuk artis (star)

# ==================== PIC PROXY CONFIG ====================
PIC_PROXY = True
PIC_HOSTS = ('https://tp.pgdjz.fun',)   # host gambar tambahan
_BAD_PIC = (
    '/packs/', 'logo', 'index.png', 'nopic', 'noimg',
    'placeholder', 'default.jpg', 'default.png',
    'loading.gif', 'grey.gif', 'avatar', 'blank.gif',
)
# ============================================================

import re
import os
import json
import time
import requests
import traceback
from datetime import datetime
from urllib.parse import quote, unquote, quote_plus
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import sys
sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    def getName(self):
        return "皮狗DJ站"

    DETAIL_PATH_MAP = {
        'dance':   '/dance/{sid}.html',
        'video':   '/video/{sid}.html',
        'ring':    '/ls/{sid}.html',
        'star':    '/star/{sid}.html',
        'topic':   '/topic/show-{sid}-1.html',
    }
    IMAGE_CATEGORIES = {'star'}

    def init(self, extend):
        self.console_log = False
        self._log_file = None
        self.dump_html = False
        self._dump_count = 0
        self.debug_enabled = False
        self.max_dumps = MAX_HTML_DUMPS
        self.log_dir = LOG_DIR
        self.proxies = {}
        self.proxy_str = None
        self.extendDict = {}
        self._pid_referer = {}
        self._cid_cache = {}

        try:
            self.extendDict = json.loads(extend) if extend else {}
        except:
            self.extendDict = {}

        self.debug_enabled = self._as_bool(
            self.extendDict.get('enable_debug', ENABLE_LOG_FILE)
        )
        self.dump_html = self._as_bool(
            self.extendDict.get('dump_html', ENABLE_HTML_DUMP)
        )
        self.console_log = self._as_bool(
            self.extendDict.get('console_log', ENABLE_CONSOLE_LOG)
        )
        self.max_dumps = int(
            self.extendDict.get('max_dumps', MAX_HTML_DUMPS)
        )
        self.log_dir = self.extendDict.get('log_dir') or LOG_DIR
        self.enable_url_normalize = self._as_bool(
            self.extendDict.get('normalize_url', ENABLE_URL_NORMALIZE)
        )
        self.star_max_pages = int(
            self.extendDict.get('star_max_pages', STAR_MAX_PAGES)
        )

        if self.debug_enabled or self.dump_html:
            if not self._ensure_log_dir():
                fallback = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), 'pgdj_debug'
                )
                print(f"[PGDJ] Fallback LOG_DIR -> {fallback}")
                self.log_dir = fallback
                self._ensure_log_dir()

            if self.debug_enabled:
                log_name = f"pgdj_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
                self._log_file = os.path.join(self.log_dir, log_name)
                self._log_raw(f"=== Spider v7.8 (Optimized) initiated at {datetime.now().isoformat()} ===")
                self._log_raw(f"debug_dir: {self.log_dir}")
                self._log_raw(f"dump_html: {self.dump_html}")
                self._log_raw(f"normalize_url: {self.enable_url_normalize}")
                self._log_raw(f"star_max_pages: {self.star_max_pages}")
                self._log_raw(f"pic_proxy: {PIC_PROXY}")
                self._log_raw(f"extendDict: {json.dumps(self.extendDict, ensure_ascii=False)}")
                print(f"[PGDJ] Log file  : {self._log_file}")
                print(f"[PGDJ] HTML dump : {self.log_dir}")

        if self.extendDict.get('proxy'):
            pv = self.extendDict['proxy']
            if isinstance(pv, dict):
                self.proxies = pv
            elif isinstance(pv, str):
                self.proxy_str = pv
                p = pv if '://' in pv else f'http://{pv}'
                self.proxies = {'http': p, 'https': p}

        self.session = requests.Session()
        # OPTIMASI: Perbesar koneksi pool untuk mendukung banyak request gambar paralel
        adapter = HTTPAdapter(
            pool_connections=10, pool_maxsize=20,
            max_retries=Retry(total=1, backoff_factor=0.2)
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        if self.proxies:
            self.session.proxies.update(self.proxies)

        ua_mobile = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 "
            "Mobile/15E148 Safari/604.1"
        )

        self.header = {
            "User-Agent": ua_mobile,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://wap.pgdjz.com/",
            # OPTIMASI: "Connection: close" DIHAPUS agar TCP Keep-Alive bisa berjalan
        }
        self.ajax_header = {
            "User-Agent": ua_mobile,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://wap.pgdjz.com/",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        self.audio_header = {
            "User-Agent": ua_mobile,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "identity",
            "Referer": "https://wap.pgdjz.com/",
            "Origin": "https://wap.pgdjz.com",
        }

        self.base_url = "https://wap.pgdjz.com"
        self.items_per_page = 20

        self.categories = [
            {'type_id': 'dance',   'type_name': '车载音乐'},
            {'type_id': 'video',   'type_name': '车载视频'},
            {'type_id': 'ring',    'type_name': '手机铃声'},
            {'type_id': 'star',    'type_name': '名人简介'},
            {'type_id': 'topic',   'type_name': '音乐专辑'},
        ]

        self.sub_categories = {
            'dance': [
                {'n': '全部',         'v': '/dance/lists/all/1.html'},
                {'n': '最新舞曲',     'v': '/dance/lists.html'},
                {'n': '推荐舞曲',     'v': '/dance/lists/reco.html'},
                {'n': '热门舞曲',     'v': '/dance/lists/hits.html'},
                {'n': '下载排行',     'v': '/dance/lists/down.html'},
                {'n': '国内舞曲',     'v': '/dance/lists/4.html'},
                {'n': '国外舞曲',     'v': '/dance/lists/2.html'},
                {'n': '国外串烧',     'v': '/dance/lists/6.html'},
                {'n': '8倍音乐',      'v': '/dance/lists/136.html'},
                {'n': '无损舞曲',     'v': '/dance/lists/1.html'},
                {'n': '环绕舞曲',     'v': '/dance/lists/109.html'},
                {'n': '交谊舞曲',     'v': '/dance/lists/24.html'},
                {'n': '伴奏舞曲',     'v': '/dance/lists/111.html'},
                {'n': 'Disco的士高',  'v': '/dance/lists/115.html'},
                {'n': '抖音歌曲',     'v': '/dance/lists/145.html'},
            ],
            'video': [
                {'n': '全部',         'v': '/video/lists/all/1.html'},
                {'n': '最新视频',     'v': '/video/lists.html'},
                {'n': '推荐视频',     'v': '/video/lists/reco.html'},
                {'n': '热门视频',     'v': '/video/lists/hits.html'},
                {'n': '下载排行',     'v': '/video/lists/down.html'},
                {'n': '超清MV',       'v': '/video/lists/12.html'},
                {'n': '车载MV',       'v': '/video/lists/123.html'},
                {'n': '跳舞MV',       'v': '/video/lists/112.html'},
                {'n': '国内夜店',     'v': '/video/lists/158.html'},
                {'n': '派对MV',       'v': '/video/lists/90.html'},
                {'n': '发烧MV',       'v': '/video/lists/125.html'},
                {'n': '国外夜店',     'v': '/video/lists/21.html'},
                {'n': '抒情MV',       'v': '/video/lists/20.html'},
                {'n': '泳装MV',       'v': '/video/lists/56.html'},
                {'n': '车模MV',       'v': '/video/lists/58.html'},
                {'n': '粤语MV',       'v': '/video/lists/114.html'},
            ],
            'ring': [
                {'n': '全部分类',     'v': '/ring/lists.html'},
                {'n': '铃声大全',     'v': '/ring/lists/1.html'},
                {'n': '短信铃声',     'v': '/ring/lists/2.html'},
                {'n': '舞曲铃声',     'v': '/ring/lists/3.html'},
            ],
            'star': [
                {'n': '全部分类',     'v': '/star/lists.html'},
                {'n': '歌手明星',     'v': '/star/lists/3.html'},
                {'n': '社会行业',     'v': '/star/lists/4.html'},
                {'n': '著名科学',     'v': '/star/lists/73.html'},
            ],
            'topic': [
                {'n': '音乐专辑',     'v': '/topic/dance.html'},
            ],
        }

    # ==================== DEBUG HELPERS ====================
    def _as_bool(self, v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ('1', 'true', 'yes', 'on')
        return bool(v)

    def _ensure_log_dir(self):
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            test_file = os.path.join(self.log_dir, '.write_test')
            with open(test_file, 'w') as f:
                f.write('ok')
            os.remove(test_file)
            return True
        except Exception as e:
            print(f"[PGDJ] Tidak bisa akses {self.log_dir}: {e}")
            return False

    def _log_raw(self, msg):
        if not self._log_file:
            return
        try:
            with open(self._log_file, 'a', encoding='utf-8') as f:
                f.write(msg + '\n')
        except:
            pass

    def _log(self, msg, level="INFO"):
        line = f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] [{level}] {msg}"
        if self.console_log:
            print(f"[PGDJ] {msg}")
        if self._log_file:
            try:
                with open(self._log_file, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
            except:
                pass

    def _log_exc(self, context=""):
        tb = traceback.format_exc()
        self._log(f"EXCEPTION {context}:\n{tb}", "ERROR")

    def _dump(self, name, content):
        if not self.dump_html:
            return None
        if self._dump_count >= self.max_dumps:
            self._log(f"Dump limit reached ({self.max_dumps}), skip {name}", "WARN")
            return None
        try:
            safe = re.sub(r'[^\w\-\.]', '_', name)[:80]
            ts = datetime.now().strftime('%H%M%S')
            fname = f"{ts}_{safe}.html"
            path = os.path.join(self.log_dir, fname)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            self._dump_count += 1
            self._log(f"Dumped HTML -> {fname} ({len(content)} bytes)")
            return path
        except Exception as e:
            self._log(f"Dump gagal {name}: {e}", "WARN")
            return None

    # ==================== HTTP retry ====================
    def _http(self, method, url, session=None, **kwargs):
        session = session or self.session
        max_attempts = 2 # OPTIMASI: Turunkan dari 3 ke 2 untuk cepat
        last_exc = None
        for attempt in range(max_attempts):
            t0 = time.time()
            try:
                if method.upper() == 'POST':
                    r = session.post(url, **kwargs)
                else:
                    r = session.get(url, **kwargs)
                elapsed = (time.time() - t0) * 1000
                body_len = len(r.content) if r.content else 0
                self._log(f"{method.upper()} {url} -> {r.status_code} "
                          f"({body_len}b, {elapsed:.0f}ms)")
                return r
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.ReadTimeout) as e:
                last_exc = e
                elapsed = (time.time() - t0) * 1000
                self._log(
                    f"{method.upper()} {url} -> RETRY {attempt+1}/{max_attempts} "
                    f"({elapsed:.0f}ms): {e}", "WARN"
                )
                if attempt < max_attempts - 1:
                    time.sleep(0.5) # OPTIMASI: tidur lebih singkat sebelum retry
                    continue
                raise
            except Exception as e:
                elapsed = (time.time() - t0) * 1000
                self._log(f"{method.upper()} {url} -> EXCEPTION ({elapsed:.0f}ms): {e}", "ERROR")
                raise
        if last_exc:
            raise last_exc

    # ==================== HELPER ====================
    def _new_session(self):
        s = requests.Session()
        a = HTTPAdapter(pool_connections=5, pool_maxsize=10)
        s.mount('http://', a)
        s.mount('https://', a)
        if self.proxies:
            s.proxies.update(self.proxies)
        return s

    def _fix_url(self, u):
        if not u:
            return ""
        if u.startswith('//'):
            return 'https:' + u
        if u.startswith('/'):
            return 'https://wap.pgdjz.com' + u
        u = re.sub(r'^(https?://[^/]+)//+', r'\1/', u)
        return u

    def _pic_fix(self, u):
        u = str(u or '').strip().strip('"\'')
        if not u:
            return ''
        low = u.lower()
        for b in _BAD_PIC:
            if b in low:
                return ''
        if u.startswith('//'):
            u = 'https:' + u
        if u.startswith('http'):
            return u
        if u.startswith('/'):
            if u.startswith('/teheyi/') or u.startswith('/qupu/') or u.startswith('/jp/'):
                return 'https://tp.pgdjz.fun' + u
            return self.base_url.rstrip('/') + u
        return ''

    def _px(self, u):
        u = str(u or '').strip()
        if not u or not PIC_PROXY:
            return u
        if 'tp.pgdjz.fun' not in u:
            return u
        if u.startswith('http://127.0.0.1'):
            return u
        b = ''
        try:
            b = str(self.getProxyUrl() or '').strip()
        except Exception:
            b = ''
        if not b:
            b = 'http://127.0.0.1:9978/proxy?do=py'
        return b + ('&' if '?' in b else '?') + 'type=pic&url=' + quote(u, safe='')

    def _normalize_media_url(self, url):
        if not url or not self.enable_url_normalize:
            return url
        try:
            return re.sub(r'^(https?://[^/]+)//+', r'\1/', url)
        except Exception as e:
            self._log(f"normalize_media_url error: {e}", "WARN")
            return url

    def _build_page_url(self, path, page):
        path = path.split('?')[0]
        if page <= 1:
            return f"{self.base_url}{path}"
        m = re.match(r'^/(dance|video)/lists\.html$', path)
        if m:
            return f"{self.base_url}/{m.group(1)}/lists/all/{page}.html"
        m = re.match(r'^/(dance|video)/lists/all/\d+\.html$', path)
        if m:
            return f"{self.base_url}/{m.group(1)}/lists/all/{page}.html"
        m = re.match(r'^/(dance|video)/lists/(reco|hits|down)\.html$', path)
        if m:
            return f"{self.base_url}{path}?page={page}"
        m = re.match(r'^/(dance|video)/lists/\d+\.html$', path)
        if m:
            return f"{self.base_url}{path}?page={page}"
        m = re.match(r'^/topic/dance\.html$', path)
        if m:
            return f"{self.base_url}/topic/dance/{page}.html"
        return f"{self.base_url}{path}?page={page}"

    def _clean_name(self, html_fragment):
        if not html_fragment:
            return ""
        name = re.sub(r'<font[^>]*>.*?</font>', '', html_fragment, flags=re.I | re.DOTALL)
        name = re.sub(r'<span[^>]*>(推|顶|荐|热|新|超清|高清)</span>', '', name)
        name = re.sub(r'<[^>]+>', '', name)
        name = re.sub(r'&nbsp;', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        name = re.sub(r'^(推|顶|荐|热|新|超清|高清)\s*', '', name)
        name = re.sub(r'^\d{3,4}P[-:：]\s*', '', name)
        return name.strip()

    def _extract_quality_tag(self, raw_name):
        res_m = re.match(r'^(\d{3,4}P)[-:：]\s*', raw_name)
        if res_m:
            return res_m.group(1)
        qual_m = re.match(r'^(高清|超清|蓝光|4K)', raw_name)
        if qual_m:
            return qual_m.group(1)
        return ''

    # ==================== OPTIMIZED PARSER ====================
    def _extract_items(self, html, cat_name="", cid=""):
        items = []
        seen = set()
        counts = {'p1': 0, 'p2': 0, 'p3': 0, 'p4': 0, 'p7': 0, 'p9': 0, 'p10': 0}

        def add_item(sid, name, img, remarks):
            if sid in seen:
                return False
            seen.add(sid)
            items.append({
                "vod_id": sid,
                "vod_name": name[:120] if name else f"ID {sid}",
                "vod_pic": self._px(self._pic_fix(img)),
                "vod_remarks": remarks,
            })
            return True

        # === POLA 1 & 2: DANCE / VIDEO / INDEX ===
        if cid in ('index', 'dance', 'video'):
            # Pola 1: List biasa
            dance_pattern = re.compile(
                r'<a\s+href="https?://wap\.pgdjz\.com/(?:dance|video)/(\d+)\.html"[^>]*>\s*'
                r'<div\s+class="img">\s*<img\s+src="([^"]+)"[^>]*>\s*</div>\s*'
                r'<div\s+class="neirong">\s*'
                r'<div\s+class="name">(.*?)</div>\s*'
                r'<div\s+class="arguments">(.*?)</div>',
                re.DOTALL
            )
            for m in dance_pattern.finditer(html):
                sid, img, name_html, args_html = m.groups()
                raw_name = re.sub(r'<[^>]+>', '', name_html).strip()
                raw_for_quality = re.sub(r'^(推|顶|荐|热|新)\s*', '', raw_name).strip()
                quality_tag = self._extract_quality_tag(raw_for_quality)
                name = self._clean_name(name_html)
                fmt = ""
                upd = ""
                fm = re.search(r'格式[:：]\s*([A-Z0-9]+)', args_html)
                if fm:
                    fmt = fm.group(1)
                um = re.search(r'更新[:：]\s*([\d\-]+)', args_html)
                if um:
                    upd = um.group(1)
                remark_parts = [p for p in [cat_name, quality_tag, fmt, upd] if p]
                if add_item(sid, name, img, " · ".join(remark_parts)):
                    counts['p1'] += 1

            # Pola 2: Widget Video
            video_pattern = re.compile(
                r'<a\s+href="https?://wap\.pgdjz\.com/(?:dance|video)/(\d+)\.html"[^>]*>\s*'
                r'<div\s+class="imgbox">\s*'
                r'<div\s+class="img">\s*<img\s+src="([^"]+)"[^>]*>\s*</div>\s*'
                r'<div\s+class="widget">'
                r'.*?<div\s+class="click">[^<]*<i[^>]*></i>([^<]*)</div>\s*'
                r'<div\s+class="item">([\d\-]+)</div>',
                re.DOTALL
            )
            for m in video_pattern.finditer(html):
                sid, img, hits, date = m.groups()
                tail = html[m.end():m.end() + 600]
                next_a = tail.find('<a ')
                if next_a != -1:
                    tail = tail[:next_a]
                nm = re.search(
                    r'</div>\s*</div>\s*<div\s+class="name">\s*'
                    r'(?:<span[^>]*>[^<]*</span>\s*)?(.*?)</div>',
                    tail, re.DOTALL
                )
                name_html = nm.group(1) if nm else f"Video {sid}"
                raw_name = re.sub(r'<[^>]+>', '', name_html).strip()
                quality_tag = self._extract_quality_tag(raw_name)
                name = self._clean_name(name_html)
                hits_clean = hits.strip() if hits else ''
                remark_parts = [p for p in [cat_name, quality_tag, hits_clean, date] if p]
                if add_item(sid, name, img, " · ".join(remark_parts)):
                    counts['p2'] += 1
            
            self._log(f"  extract counts: {counts}")
            return items

        # === POLA 3 & 4: RING ===
        if cid == 'ring':
            ring_pattern = re.compile(
                r'<a\s+href="https?://wap\.pgdjz\.com/ls/(\d+)\.html"[^>]*>\s*'
                r'<div\s+class="name">(.*?)</div>\s*'
                r'<div\s+class="type">\s*'
                r'<div\s+class="tags">格式[:：]?\s*([A-Z0-9]+)</div>\s*'
                r'<div\s+class="tags">时长[:：]?\s*([\d:]+)</div>\s*'
                r'<div\s+class="tags">更新[:：]?\s*([\d\-]+)</div>',
                re.DOTALL
            )
            for m in ring_pattern.finditer(html):
                sid, name_html, fmt, dur, upd = m.groups()
                name = self._clean_name(name_html)
                remark_parts = [p for p in [cat_name, fmt, dur, upd] if p]
                if add_item(sid, name, "", " · ".join(remark_parts)):
                    counts['p3'] += 1

            ring2_pattern = re.compile(
                r'<a\s+href="https?://wap\.pgdjz\.com/ls/(\d+)\.html"[^>]*>\s*'
                r'<div\s+class="img">\s*<img\s+src="([^"]+)"[^>]*>\s*</div>\s*'
                r'<div\s+class="neirong">\s*'
                r'<div\s+class="name">(.*?)</div>\s*'
                r'</div>',
                re.DOTALL
            )
            for m in ring2_pattern.finditer(html):
                sid, img, name_html = m.groups()
                name = self._clean_name(name_html)
                name = re.sub(r'^\[[A-Z0-9]+\]', '', name).strip()
                name = re.sub(r'铃声$', '', name).strip()
                if add_item(sid, name, img, cat_name):
                    counts['p4'] += 1

            self._log(f"  extract counts: {counts}")
            return items

        # === POLA 7 & 10: STAR ===
        if cid == 'star':
            star_pattern = re.compile(
                r'<a\s+href="https?://wap\.pgdjz\.com/star/(\d+)\.html"[^>]*>\s*'
                r'<div\s+class="imgbox">\s*'
                r'<div\s+class="img">\s*<img\s+src="([^"]+)"[^>]*>\s*</div>\s*'
                r'</div>\s*<div\s+class="name">(.*?)</div>',
                re.DOTALL
            )
            for m in star_pattern.finditer(html):
                sid, img, name_html = m.groups()
                name = self._clean_name(name_html)
                if add_item(sid, name, img, cat_name):
                    counts['p7'] += 1

            star2_pattern = re.compile(
                r'<a\s+href="https?://wap\.pgdjz\.com/star/(\d+)\.html"[^>]*>\s*'
                r'<div\s+class="img">\s*<img\s+src="([^"]+)"[^>]*>\s*</div>\s*'
                r'<div\s+class="neirong">\s*'
                r'<div\s+class="name">(.*?)</div>\s*'
                r'<div\s+class="intro">(.*?)</div>',
                re.DOTALL
            )
            for m in star2_pattern.finditer(html):
                sid, img, name_html, intro = m.groups()
                name = self._clean_name(name_html)
                intro_clean = self._clean_name(intro)[:80]
                remark_parts = [p for p in [cat_name, intro_clean] if p]
                if add_item(sid, name, img, " · ".join(remark_parts)):
                    counts['p10'] += 1

            self._log(f"  extract counts: {counts}")
            return items

        # === POLA 9: TOPIC ===
        if cid == 'topic':
            topic_pattern = re.compile(
                r'<a\s+href="https?://wap\.pgdjz\.com/topic/show-(\d+)-1\.html"[^>]*>\s*'
                r'<div\s+class="imgbox">\s*'
                r'(?:<div\s+class="imgbj">[^<]*</div>\s*)?'
                r'<div\s+class="img">\s*<img\s+src="([^"]+)"[^>]*>\s*</div>\s*'
                r'</div>\s*'
                r'<div\s+class="neirong">\s*'
                r'<div\s+class="name">(.*?)</div>\s*'
                r'<div\s+class="type">\s*'
                r'<div\s+class="tags">人气[:：]?\s*([^<]*)</div>\s*'
                r'<div\s+class="tags">时间[:：]?\s*([^<]*)</div>\s*'
                r'</div>\s*'
                r'<div\s+class="text">(.*?)</div>',
                re.DOTALL
            )
            for m in topic_pattern.finditer(html):
                sid, img, name_html, hits, date, desc = m.groups()
                name = self._clean_name(name_html)
                hits_clean = self._clean_name(hits)
                date_clean = self._clean_name(date)
                remark_parts = [p for p in [cat_name, hits_clean, date_clean] if p]
                if add_item(sid, name, img, " · ".join(remark_parts)):
                    counts['p9'] += 1

            self._log(f"  extract counts: {counts}")
            return items

        return items

    def _extract_search_items(self, html, keyword=""):
        items = []
        seen = set()
        pattern = re.compile(
            r'<li>\s*<div data-id="(\d+)"[^>]*>.*?</div>\s*'
            r'<a\s+href="https?://wap\.pgdjz\.com/dance/(\d+)\.html"[^>]*>\s*'
            r'<div\s+class="img">\s*<img\s+src="([^"]+)"[^>]*>\s*</div>\s*'
            r'<div\s+class="neirong">\s*'
            r'<div\s+class="name">(.*?)</div>\s*'
            r'<div\s+class="arguments">(.*?)</div>',
            re.DOTALL
        )
        for m in pattern.finditer(html):
            data_id, sid, img, name_html, args_html = m.groups()
            if sid in seen:
                continue
            seen.add(sid)
            name = self._clean_name(name_html)
            if not name:
                continue
            fmt = ""
            upd = ""
            fm = re.search(r'格式[:：]\s*([A-Z0-9]+)', args_html)
            if fm:
                fmt = fm.group(1)
            um = re.search(r'更新[:：]\s*([\d\-]+)', args_html)
            if um:
                upd = um.group(1)
            remarks = " · ".join([p for p in ['搜索', fmt, upd] if p])
            items.append({
                "vod_id": sid,
                "vod_name": name[:120],
                "vod_pic": self._px(self._pic_fix(img)),
                "vod_remarks": remarks,
            })
        return items

    def _has_next(self, html, page):
        m = re.search(r'data-pagejs="(\d+)"', html)
        if m:
            total = int(m.group(1))
            if total > 0:
                return page < total
        if re.search(rf'href="[^"]*[?&]page={page + 1}(?:[&"]|$)', html):
            return True
        if re.search(r'>\s*下一页\s*<', html):
            return True
        return False

    # ==================== MEDIA ====================
    def _detect_media_type(self, html, cid=""):
        if cid in self.IMAGE_CATEGORIES:
            return 'image'
        if cid == 'video':
            return 'video'
        if re.search(r'class="vodplaybox', html):
            return 'video'
        if re.search(r'class="mp3playbox', html):
            return 'audio'
        m = re.search(r'格式[:：]\s*([A-Z0-9]+)', html)
        if m and 'MP4' in m.group(1).upper():
            return 'video'
        return 'audio'

    def _fetch_media_url(self, song_id, media_type, session, referer=None):
        if media_type == 'image':
            return None
        referer = referer or f"{self.base_url}/dance/{song_id}.html"
        if media_type == 'video':
            endpoints = [
                ('POST', '/ajax/videoplay', {'id': str(song_id), 'ids': str(song_id)}),
                ('POST', '/ajax/danceplayer', {'id': str(song_id), 'ids': str(song_id)}),
            ]
        else:
            endpoints = [
                ('POST', '/ajax/danceplayer', {'id': str(song_id), 'ids': str(song_id)}),
                ('POST', '/ajax/videoplay', {'id': str(song_id), 'ids': str(song_id)}),
            ]

        for method, path, payload in endpoints:
            data = None
            try:
                url = f"{self.base_url}{path}"
                headers = dict(self.ajax_header)
                headers['Referer'] = referer
                if method == 'POST':
                    r = self._http('POST', url, session=session,
                                   data=payload, headers=headers,
                                   timeout=8, proxies=self.proxies) # OPTIMASI: timeout dari 12s ke 8s
                else:
                    r = self._http('GET', url, session=session,
                                   headers=headers,
                                   timeout=8, proxies=self.proxies)
                if r.status_code != 200 or not r.text.strip():
                    continue
                pu = None
                try:
                    data = r.json()
                    if isinstance(data, dict) and data.get('code') == 1:
                        for key in ('playurl', 'url', 'play_url', 'src'):
                            pu = data.get(key)
                            if pu:
                                break
                except Exception:
                    m = re.search(r'"playurl"\s*:\s*"([^"]+)"', r.text)
                    if m:
                        pu = m.group(1)
                if pu:
                    pu = self._fix_url(pu)
                    raw_pu = pu
                    pu = self._normalize_media_url(pu)
                    self._log(f"  -> {media_type} via {method} {path}")
                    return pu
            except Exception as e:
                self._log(f"  -> error {path}: {e}", "WARN")
        self._log(f"X Semua endpoint gagal untuk {song_id} ({media_type})", "ERROR")
        return None

    def _fetch_ring_media_url(self, sid, session):
        referer = f"{self.base_url}/ls/{sid}.html"
        url = f"{self.base_url}/ring/down/{sid}.html"
        s_quick = self._new_session()
        try:
            r = s_quick.get(
                url,
                headers={**self.header, 'Referer': referer},
                timeout=6,
                allow_redirects=True,
                stream=True,
            )
            final_url = r.url
            status = r.status_code
            try:
                r.close()
            except:
                pass
            if not final_url.endswith('.html') and re.search(
                r'\.(mp3|m4a|wav|aac|flac|ogg)', final_url, re.I
            ):
                return self._fix_url(final_url)
            if status == 200:
                try:
                    r2 = s_quick.get(
                        url,
                        headers={**self.header, 'Referer': referer},
                        timeout=6,
                        allow_redirects=True,
                    )
                    if r2.status_code == 200:
                        m = re.search(
                            r'href="([^"]+\.(?:mp3|m4a|wav|aac|flac|ogg))"',
                            r2.text, re.IGNORECASE
                        )
                        if m:
                            return self._fix_url(m.group(1))
                        m = re.search(r'<audio[^>]+src="([^"]+)"', r2.text, re.IGNORECASE)
                        if m:
                            return self._fix_url(m.group(1))
                        m = re.search(r'<source[^>]+src="([^"]+)"', r2.text, re.IGNORECASE)
                        if m:
                            return self._fix_url(m.group(1))
                except requests.exceptions.Timeout:
                    pass
            return None
        except Exception:
            return None
        finally:
            try:
                s_quick.close()
            except:
                pass

    # ==================== STAR HELPERS ====================
    def _fetch_artist_songs(self, search_url, session, max_pages=3):
        episodes = []
        seen_songs = set()
        if not search_url:
            return episodes
        search_url = search_url.replace('&amp;', '&')
        search_url = re.sub(r'^https?://(?:www\.)?pgdjz\.com', 'https://wap.pgdjz.com', search_url)
        if search_url.startswith('/'):
            search_url = self.base_url + search_url
        try:
            r = self._http('GET', search_url, session=session,
                           headers=self.header, timeout=15,
                           proxies=self.proxies)
            r.encoding = 'utf-8'
            songs = self._extract_search_items(r.text)
            for s in songs:
                if s['vod_id'] not in seen_songs:
                    seen_songs.add(s['vod_id'])
                    episodes.append((s['vod_id'], s['vod_name']))
            pagecount = 1
            m = re.search(r'data-pagejs="(\d+)"', r.text)
            if m:
                pagecount = int(m.group(1))
            total_pages = min(pagecount, max_pages)
            for pg in range(2, total_pages + 1):
                if 'page=' in search_url:
                    page_url = re.sub(r'page=\d+', f'page={pg}', search_url)
                else:
                    page_url = f"{search_url}&page={pg}"
                try:
                    rp = self._http('GET', page_url, session=session,
                                    headers=self.header, timeout=15,
                                    proxies=self.proxies)
                    rp.encoding = 'utf-8'
                    page_songs = self._extract_search_items(rp.text)
                    for s in page_songs:
                        if s['vod_id'] not in seen_songs:
                            seen_songs.add(s['vod_id'])
                            episodes.append((s['vod_id'], s['vod_name']))
                except Exception:
                    break
        except Exception:
            pass
        return episodes

    # ==================== PATH DETECTION ====================
    def _detect_cid_from_sid(self, sid):
        return self._cid_cache.get(str(sid), 'dance')

    def _build_detail_url(self, sid):
        cid = self._detect_cid_from_sid(sid)
        if cid in self.DETAIL_PATH_MAP:
            path = self.DETAIL_PATH_MAP[cid].format(sid=sid)
        else:
            path = f"/dance/{sid}.html"
        return f"{self.base_url}{path}"

    # ==================== OK影视 INTERFACE ====================
    def homeContent(self, filter):
        self._log(f"homeContent(filter={filter})")
        result = {'class': self.categories, 'filters': {}}
        if filter:
            for cid, subs in self.sub_categories.items():
                result['filters'][cid] = [{
                    'key': 'sub',
                    'name': '分类',
                    'value': subs,
                }]
        return result

    def homeVideoContent(self):
        return self.categoryContent('index', 1, False, {})

    def categoryContent(self, cid, page, filter, ext):
        page = int(page)
        self._log(f"categoryContent(cid={cid}, page={page}, filter={filter}, ext={ext})")
        result = {'list': [], 'page': page, 'pagecount': page, 'limit': 0, 'total': 0}
        url = None
        cat_name = next((c['type_name'] for c in self.categories if c['type_id'] == cid), "DJ")
        if ext and ext.get('sub'):
            sub_val = ext['sub']
            for s in self.sub_categories.get(cid, []):
                if s['v'] == sub_val or s['n'] == sub_val:
                    url = self._build_page_url(s['v'], page)
                    cat_name = s['n']
                    break
        if not url:
            if cid == 'index':
                url = f"{self.base_url}/"
            elif cid == 'dance':
                url = f"{self.base_url}/dance/lists/all/{page}.html"
            elif cid == 'video':
                url = f"{self.base_url}/video/lists/all/{page}.html"
            elif cid in ('ring', 'star'):
                if page == 1:
                    url = f"{self.base_url}/{cid}/lists.html"
                else:
                    url = f"{self.base_url}/{cid}/lists/all/{page}.html"
            elif cid == 'topic':
                if page == 1:
                    url = f"{self.base_url}/topic/dance.html"
                else:
                    url = f"{self.base_url}/topic/dance/{page}.html"
            else:
                url = f"{self.base_url}/"

        session = self._new_session()
        try:
            r = self._http('GET', url, session=session,
                           headers=self.header, timeout=10, proxies=self.proxies) # OPTIMASI: timeout 15 ke 10
            r.encoding = 'utf-8'
            html = r.text
            self._dump(f"list_{cid}_p{page}", html)
            items = self._extract_items(html, cat_name, cid)
            for it in items:
                self._cid_cache[str(it['vod_id'])] = cid
            m_total = re.search(r'data-pagejs="(\d+)"', html)
            if not items:
                result['pagecount'] = page
            elif m_total and int(m_total.group(1)) > 0:
                result['pagecount'] = int(m_total.group(1))
            elif re.search(r'>\s*下一页\s*<', html):
                result['pagecount'] = page + 1
            else:
                result['pagecount'] = page
            result['list'] = items[:self.items_per_page]
            result['limit'] = len(result['list'])
        except Exception as e:
            self._log(f"categoryContent error: {e}", "ERROR")
        finally:
            session.close()
        return result

    def detailContent(self, did):
        sid = did[0] if isinstance(did, (list, tuple)) else did
        sid = str(sid)
        cid = self._detect_cid_from_sid(sid)
        result = {'list': []}
        session = self._new_session()
        try:
            url = self._build_detail_url(sid)
            r = self._http('GET', url, session=session,
                           headers=self.header, timeout=10, proxies=self.proxies)
            r.encoding = 'utf-8'
            html = r.text
            if r.status_code == 404:
                for cid_try, path_tmpl in self.DETAIL_PATH_MAP.items():
                    alt_path = path_tmpl.format(sid=sid)
                    alt_url = f"{self.base_url}{alt_path}"
                    if alt_url == url:
                        continue
                    try:
                        r = self._http('GET', alt_url, session=session,
                                       headers=self.header, timeout=10, proxies=self.proxies)
                        r.encoding = 'utf-8'
                        if r.status_code == 200 and len(r.text) > 1000:
                            html = r.text
                            cid = cid_try
                            self._cid_cache[str(sid)] = cid
                            break
                    except:
                        continue
            self._dump(f"detail_{cid}_{sid}", html)
            if cid == 'topic':
                vod = self._parse_detail_topic(sid, html)
            elif cid == 'star':
                vod = self._parse_detail_image(sid, cid, html, session)
            elif cid == 'ring':
                vod = self._parse_detail_ring(sid, html, session)
            else:
                vod = self._parse_detail_media(sid, cid, html, session)
            if vod:
                result['list'] = [vod]
        except Exception as e:
            self._log(f"detailContent error: {e}", "ERROR")
        finally:
            session.close()
        return result

    # ---------- DETAIL PARSERS ----------
    def _parse_detail_media(self, sid, cid, html, session):
        title = self._extract_title(html, sid)
        cover = self._extract_cover(html, sid)
        duration = self._extract_meta(html, '时长')
        filesize = self._extract_meta(html, '大小')
        fmt = self._extract_meta(html, '格式')
        category = self._extract_category(html)
        quality = self._extract_quality(html)
        media_type = self._detect_media_type(html, cid)
        media_url = self._fetch_media_url(sid, media_type, session)
        if not media_url:
            return None
        referer = self._build_detail_url(sid)
        self._pid_referer[media_url] = referer
        remark_parts = [p for p in [quality, duration, filesize, fmt] if p]
        play_from = "皮狗DJ站·视频" if media_type == 'video' else "皮狗DJ站·音乐"
        return {
            "vod_id": sid,
            "vod_name": title[:120],
            "vod_pic": cover,
            "vod_content": f"{title}\n分类: {category}\n画质: {quality}\n时长: {duration}\n大小: {filesize}\n格式: {fmt}",
            "vod_play_from": play_from,
            "vod_play_url": f"播放${media_url}",
            "vod_remarks": " · ".join(remark_parts),
        }

    def _parse_detail_ring(self, sid, html, session):
        title = self._extract_title(html, sid)
        cover = self._extract_cover(html, sid)
        duration = self._extract_meta(html, '时长')
        filesize = self._extract_meta(html, '大小')
        fmt = self._extract_meta(html, '格式') or 'MP3'
        media_url = self._fetch_ring_media_url(sid, session)
        if media_url:
            self._pid_referer[media_url] = self._build_detail_url(sid)
        remark_parts = [p for p in ['铃声', fmt, duration, filesize] if p]
        return {
            "vod_id": sid,
            "vod_name": title[:120],
            "vod_pic": cover,
            "vod_content": f"{title}\n类型: 手机铃声\n格式: {fmt}\n时长: {duration}\n大小: {filesize}",
            "vod_play_from": "皮狗DJ站·铃声",
            "vod_play_url": f"播放${media_url}" if media_url else "",
            "vod_remarks": " · ".join(remark_parts),
        }

    def _parse_detail_image(self, sid, cid, html, session=None):
        title = self._extract_title(html, sid)
        cover = self._extract_cover(html, sid)
        content = self._extract_article_content(html)
        episodes = []
        search_url = None
        if cid == 'star' and session:
            m = re.search(r'href="([^"]*?/dance/search\.html\?key=[^"]+)"', html)
            if m:
                search_url = m.group(1)
            else:
                if title and title.strip():
                    encoded = quote_plus(title.strip())
                    search_url = f"{self.base_url}/dance/search.html?key={encoded}"
            if search_url:
                episodes = self._fetch_artist_songs(search_url, session, max_pages=self.star_max_pages)
        if episodes:
            play_lines = [f"{name}${song_id}" for song_id, name in episodes]
            play_url = "#".join(play_lines)
            play_from = "皮狗DJ站·音乐作品"
            remarks = f"名人 · {len(episodes)} 首作品"
        else:
            play_url = ""
            play_from = "无"
            remarks = " · ".join([p for p in [cid, title[:60]] if p])
        return {
            "vod_id": sid,
            "vod_name": title[:120],
            "vod_pic": cover,
            "vod_content": content[:3000] if content else title,
            "vod_play_from": play_from,
            "vod_play_url": play_url,
            "vod_remarks": remarks,
        }

    def _parse_detail_topic(self, sid, html):
        title = self._extract_title(html, sid)
        cover = self._extract_cover(html, sid)
        content = self._extract_article_content(html)
        episodes = []
        seen_songs = set()
        m_list = re.search(r'<ul\s+class="musiclist[^"]*"[^>]*>(.*?)</ul>', html, re.DOTALL)
        if m_list:
            song_pattern = re.compile(
                r'<a\s+href="https?://wap\.pgdjz\.com/dance/(\d+)\.html"[^>]*>.*?'
                r'<div\s+class="name">(.*?)</div>',
                re.DOTALL
            )
            for sm in song_pattern.finditer(m_list.group(1)):
                song_id, song_name = sm.groups()
                if song_id in seen_songs:
                    continue
                seen_songs.add(song_id)
                name = self._clean_name(song_name)
                if name:
                    episodes.append((song_id, name))
        if episodes:
            play_lines = [f"{name}${song_id}" for song_id, name in episodes]
            play_url = "#".join(play_lines)
            play_from = "皮狗DJ站·专辑歌曲"
            remarks = f"专辑 · {len(episodes)} 首"
        else:
            play_url = ""
            play_from = "无"
            remarks = "专辑 (无歌曲)"
        return {
            "vod_id": sid,
            "vod_name": title[:120],
            "vod_pic": cover,
            "vod_content": content[:3000] if content else title,
            "vod_play_from": play_from,
            "vod_play_url": play_url,
            "vod_remarks": remarks,
        }

    # ==================== SEARCH ====================
    def searchContent(self, key, quick, pg=1):
        return self._search_by_keyword(key, pg)

    def _search_by_keyword(self, key, page=1):
        page = int(page)
        result = {'list': [], 'page': page, 'pagecount': page, 'limit': 0, 'total': 0}
        encoded = quote_plus((key or '').strip())
        if not encoded:
            return result
        if page <= 1:
            url = f"{self.base_url}/dance/search.html?key={encoded}"
        else:
            url = f"{self.base_url}/dance/search.html?key={encoded}&page={page}"
        session = self._new_session()
        try:
            r = self._http('GET', url, session=session, headers=self.header,
                           timeout=10, proxies=self.proxies)
            r.encoding = 'utf-8'
            html = r.text
            self._dump(f"search_{encoded[:20]}_p{page}", html)
            items = self._extract_search_items(html, key)
            m = re.search(r'data-pagejs="(\d+)"', html)
            if m:
                result['pagecount'] = int(m.group(1))
            else:
                result['pagecount'] = page
            result['list'] = items[:self.items_per_page]
            result['limit'] = len(result['list'])
            for it in items:
                self._cid_cache[str(it['vod_id'])] = 'dance'
        except Exception as e:
            self._log(f"search error: {e}", "ERROR")
        finally:
            session.close()
        return result

    # ==================== EXTRACTORS ====================
    def _extract_title(self, html, sid):
        m = re.search(
            r'<h1[^>]*>\s*<i[^>]*>\s*</i>\s*(?:<span[^>]*>[^<]*</span>\s*)?(.*?)</h1>',
            html, re.DOTALL
        )
        if m:
            t = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if t:
                return re.sub(r'\s+', ' ', t)
        m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
        if m:
            t = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if t:
                return re.sub(r'\s+', ' ', t)
        m = re.search(r'<title>([^<]+)</title>', html)
        if m:
            t = re.sub(r'\s*[-_|].*?(皮狗|DJ站|pgdjz).*$', '', m.group(1), flags=re.I)
            return t.strip()
        return f"DJ {sid}"

    def _extract_quality(self, html):
        m = re.search(r'<h1[^>]*>.*?<span[^>]*>(高清|超清|蓝光|4K)</span>', html, re.DOTALL)
        if m:
            return m.group(1)
        m = re.search(r'<div\s+class="type">\s*<span[^>]*>(高清|超清|蓝光|4K)</span>', html, re.DOTALL)
        if m:
            return m.group(1)
        return ""

    def _extract_cover(self, html, sid):
        m = re.search(r'<div\s+class="info">.*?<div\s+class="img">\s*<img\s+src="([^"]+)"', html, re.DOTALL)
        if m:
            return self._px(self._pic_fix(m.group(1)))
        m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
        if m:
            return self._px(self._pic_fix(m.group(1)))
        m = re.search(r'<div\s+class="img">\s*<img\s+src="([^"]+)"', html, re.DOTALL)
        if m:
            return self._px(self._pic_fix(m.group(1)))
        return ""

    def _extract_meta(self, html, key):
        m = re.search(rf'{re.escape(key)}[:：]\s*([^<]+)', html)
        if m:
            return self.removeHtmlTags(m.group(1)).strip()
        return ""

    def _extract_category(self, html):
        m = re.search(r'分类[:：]\s*<a[^>]*>([^<]+)</a>', html)
        if m:
            return m.group(1).strip()
        return ""

    def _extract_article_content(self, html):
        m = re.search(
            r'<div\s+class="stavetextbox"[^>]*>.*?'
            r'<div\s+class="txt"[^>]*>(.*?)</div>\s*</div>',
            html, re.DOTALL
        )
        if m:
            txt = re.sub(r'<br\s*/?>', '\n', m.group(1))
            txt = re.sub(r'<[^>]+>', '', txt)
            return re.sub(r'\n{3,}', '\n\n', txt).strip()
        m = re.search(
            r'<div\s+class="text">\s*<div\s+class="title">.*?</div>\s*'
            r'<div\s+class="txt">(.*?)<div\s+class="item">',
            html, re.DOTALL
        )
        if not m:
            m = re.search(
                r'<div\s+class="text">\s*<div\s+class="title">.*?</div>\s*'
                r'<div\s+class="txt">(.*?)</div>\s*</div>\s*</div>',
                html, re.DOTALL
            )
        if m:
            txt = re.sub(r'<br\s*/?>', '\n', m.group(1))
            txt = re.sub(r'<[^>]+>', '', txt)
            return re.sub(r'\n{3,}', '\n\n', txt).strip()
        m = re.search(
            r'<div\s+class="neirong">\s*.*?<div\s+class="text">(.*?)</div>\s*</div>\s*</div>',
            html, re.DOTALL
        )
        if m:
            txt = re.sub(r'<br\s*/?>', '\n', m.group(1))
            txt = re.sub(r'<[^>]+>', '', txt)
            return re.sub(r'\n{3,}', '\n\n', txt).strip()
        for cls in ('article-content', 'content', 'text', 'news-content', 'intro'):
            m = re.search(rf'<div\s+class="[^"]*{cls}[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
            if m:
                txt = re.sub(r'<br\s*/?>', '\n', m.group(1))
                txt = re.sub(r'<[^>]+>', '', txt)
                txt = re.sub(r'\n{3,}', '\n\n', txt)
                return txt.strip()
        return ""

    # ==================== PLAYER ====================
    def playerContent(self, flag, pid, vipFlags):
        if pid and pid.isdigit() and any(k in (flag or '') for k in ('专辑', '歌曲', '作品', '音乐')):
            session = self._new_session()
            try:
                referer = f"{self.base_url}/dance/{pid}.html"
                media_url = self._fetch_media_url(pid, 'audio', session, referer=referer)
                if media_url:
                    self._pid_referer[media_url] = referer
                    pid = media_url
                else:
                    return {"parse": 0, "url": "", "header": {}}
            finally:
                session.close()
        if pid and re.search(r'\.(jpg|jpeg|png|gif|webp)(\?|$)', pid, re.I):
            return {"parse": 0, "url": pid, "header": {"User-Agent": self.header["User-Agent"], "Referer": self.base_url + "/"}}
        if pid and 'wap.pgdjz.com' in pid and not re.search(r'\.(mp4|mp3|m4a|wav|flac)', pid, re.I):
            return {"parse": 0, "url": "", "header": {}}
        pid_lower = (pid or '').lower()
        is_video = ('视频' in (flag or '') or '.mp4' in pid_lower or 'zwmtv' in pid_lower or '%2fvideo' in pid_lower or '%2fmp4' in pid_lower)
        referer = self._pid_referer.get(pid, "https://wap.pgdjz.com/")
        if is_video:
            header = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": referer,
                "Origin": "https://wap.pgdjz.com",
                "Range": "bytes=0-",
            }
        else:
            header = self.audio_header.copy()
            header["Referer"] = referer
        result = {"parse": 0, "url": pid, "header": header}
        if self.proxy_str:
            result["proxy"] = self.proxy_str
        return result

    # ==================== LOCAL PROXY (POSTER) ====================
    def localProxy(self, param):
        p = param if isinstance(param, dict) else {}
        u = str(p.get('url') or '')
        if not u:
            return [403, 'text/plain', b'', None]
        try:
            u = unquote(u)
        except Exception:
            pass
        if u.startswith('//'):
            u = 'https:' + u

        # OPTIMASI: Local proxy session dengan pool besar & tanpa header berlebih
        s = self._new_session()
        h = {
            "User-Agent": self.header["User-Agent"],
            "Referer": self.base_url + '/',
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
        }
        try:
            r = s.get(u, headers=h, timeout=5) # Timeout dipersingkat 5 detik agar cepat menyerah kalau link mati
            if r.status_code < 400 and r.content:
                return [200, r.headers.get('Content-Type', 'image/jpeg'), r.content, None]
        except Exception as e:
            pass
        finally:
            try:
                s.close()
            except:
                pass
        return [403, 'text/plain', b'', None]

    def removeHtmlTags(self, src):
        return re.sub(r'<[^>]+>', '', src)

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        try:
            self.session.close()
        except:
            pass