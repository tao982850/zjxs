# coding=utf-8
# !/usr/bin/python
"""
埋堆堆 · 影视 / 蜂蜜影视（FongMi 内核）Python Spider 插件

[适配说明 · 2026-11] 本文件是「埋堆堆_fongmi.js」的 Python 等价实现：
  1) 入口改为 FongMi 内核识别的 Python 蜘蛛：类名 Spider，方法为
     homeContent / homeVideoContent / categoryContent / detailContent / searchContent / playerContent，
     各方法直接返回 dict（由内核负责序列化）。
  2) 网络层不再走 QuickJS 的 net.req，改用 requests（缺失时回退 urllib），
     签名改用 hashlib.md5，节流用 time.sleep。
  3) 站点解析、签名算法、WAF 规避、分页并发/节流、分类规则、搜索打分、取流等业务逻辑
     与原 JS 版本逐项对齐，改点均在原位置以 [FIX-2026-11*] 标注。

[修复记录 · 2026-11] 源「分类 / 搜索 / 首页列表全空」的根因与修复：
  1) 列表接口 /api/vod/classify/word/search.action 被腾讯云 WAF 按「精确路径」拦截，
     无尾斜杠一律返回 403 拦截页 => 所有列表请求都拿不到数据。
     修复：请求路径追加尾斜杠 .../word/search.action/，命中同一后端路由并绕过该条规则。
  2) 该接口对 rows 有硬上限：rows<=12 才返回数据，>=13 一律「获取到0行记录」。
     原实现 PAGE_ROWS=36、搜索语料 rows=100，因此全部返回空。
     修复：统一 PAGE_ROWS=12；搜索不再单独拉语料，直接复用分类扫描结果。
  3) 接口另带 WAF 突发频控：短时间密集请求会被整段 403。原实现并发 8 一次拉 240 页，
     极易被拦且「一页失败即整体停」。修复：并发降到 2 + 波间节流 + 单页重试，
     并把「一次性拉全库」改为「按需分批 + 实例态累积 + 单次调用时间预算」。
  4) 播放探测（Range 请求）失败时，回退使用已拿到的首个直链，避免退化成无法播放的 vid:num。
  5) 空页不永久锁死：连续 5 次空页进入 3 分钟冷却，冷却结束自动恢复扫描。
  6) 首页列表 5 分钟缓存 + 失败回退旧缓存，避免偶发 WAF 拦截导致首页刷新即空。
"""

import sys

sys.path.append('..')

import json
import re
import ssl
import time
import random
import hashlib
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor

try:
    from base.spider import Spider as _BaseSpider
except Exception:  # 独立运行（沙箱自测）时没有宿主 base 包，用最小桩代替
    class _BaseSpider(object):
        def log(self, msg):
            pass

try:
    import requests as _requests
    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:
        pass
except Exception:
    _requests = None


# ============================================================
# 常量
# ============================================================
SITE = 'https://m.mddcloud.com.cn'
API_BASE = 'https://activity.mddcloud.com.cn'
HOST_CANDIDATES = [
    'https://m.mddcloud.com.cn',
    'https://www.mddcloud.com.cn',
    'https://mddcloud.com.cn',
]

# 从站点前端 JS 逆向得到的私钥（原样照搬，不要改）
PRIVATE_KEY = '8a4af424bd714be5b2baacbe3cf5bbbe0131effeb92e99356ef1662884558f28'

UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
      'Mobile/15E148 Safari/604.1')

BASE_HEADERS = {
    'User-Agent': UA,
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh-Hans;q=0.9,zh;q=0.8',
    'Referer': SITE + '/',
    'Origin': SITE,
    'X-Requested-With': 'XMLHttpRequest',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
}

TIMEOUT_API = 10000       # 单次 API 超时(ms)（拉长一点避免慢网被误判失败）
TIMEOUT_PROBE = 5000      # 播放地址探测超时(ms)
API_MAX_RETRY = 4         # 单次 API 请求最大重试次数（WAF 频控场景）
API_RETRY_BASE = 1200     # API 重试退避基数(ms)（WAF 冷却通常需要 1s+）

# 缓存 TTL (ms)
TTL_WORDS = 24 * 3600 * 1000   # 分类词表
TTL_LIST = 600 * 1000          # 列表 / 分桶
TTL_DETAIL_OK = 300 * 1000
TTL_PLAY = 300 * 1000          # F19: 直链带 exper=360s，取有效期一半
TTL_SEARCH = 180 * 1000
TTL_CORPUS = 1800 * 1000       # 搜索语料 30min
TTL_DOMAIN = 1800 * 1000

# 分页 / 扫描
# [FIX-2026-11] 服务端 classify/word/search 接口现对 rows 做硬上限：rows<=12 才返回数据，
# rows>=13 一律返回 0 行(msgType=0,"获取到0行记录")。故单页固定 12。
PAGE_ROWS = 12
# 全库约 2900 条 => 2900/12 ≈ 242 页，留足余量后再停。
MAX_PAGES_SCAN = 260
# 该接口同时挂着腾讯云 WAF 的突发频控：短时间请求过密会整段 403。
# 因此并发压到 2、波间留 500ms 间隔，给 WAF 留冷却时间；单页重试 4 次，空页判定放宽到连续 5 次。
SCAN_CONCURRENCY = 2
SCAN_WAVE_GAP = 500    # 每波扫描之间的间隔(ms)
SCAN_PAGE_RETRY = 4    # 单页最多重试次数
SCAN_RETRY_GAP = 1000  # 重试退避基数(ms)
# [FIX-2026-11·3] 页面推进计划：先顺序覆盖前段（剧集等常规内容密集区），
# 再按步长跳扫深层。实测电影(vt=1)/综艺(vt=2,6) 集中在 startRow 1400+ 的列表后半段，
# 纯顺序扫描（受时间预算限制）永远到不了那里 —— 这正是「电影」分类为空的原因。
SCAN_SEQ_PAGES = 30    # 顺序覆盖的页数上限
SCAN_JUMP_FROM = 38    # 跳扫起点(页)
SCAN_JUMP_STEP = 8     # 跳扫步长(页)
# 单次调用最多花在「扫描推进」上的时间预算(ms)：
# 避免稀疏分类/全库搜索把一次调用拖成几分钟（接口有频控，越急越慢）。
CAT_TIME_BUDGET = 8000
SEARCH_TIME_BUDGET = 12000

# 搜索
# [FIX-2026-11] 原实现用 rows=100 拉“搜索语料”，但接口 rows 上限仅 12，全部返回 0 行。
# 改为复用分类扫描的累积进度（同一实例态，无筛选即全库），不再单独发请求。
SEARCH_MAX_RESULTS = 100

# 播放字段优先级（F27/F28: 恢复 m3u8 优先，探测不过再降级）
PLAY_FIELD_PRIORITY = ['tryM3u8Url', 'tryUrl', 'tryMp4Url']
MAX_EPISODES = 300             # 超长剧只取最近 300 集

# 一级分类（官网 5 大类）
ALL_CLASSES = [
    {'type_id': 'tv', 'type_name': '剧集'},
    {'type_id': 'movie', 'type_name': '电影'},
    {'type_id': 'variety', 'type_name': '综艺'},
    {'type_id': 'anime', 'type_name': '动画'},
    {'type_id': 'documentary', 'type_name': '纪录片'},
]
CATEGORIES = ['tv', 'movie', 'variety', 'anime', 'documentary']
VALID_TIDS = ['tv', 'movie', 'variety', 'anime', 'documentary']

VARIETY_LABELS = [
    '综艺', '真人秀', '访谈', '美食', '游戏娱乐', '旅行',
    '音乐', '大型晚会', '资讯', '儿童', '其他',
]

ANIME_NAME_RE = re.compile(r'(动画|动漫|卡通)')
NAME_NOISE = re.compile(r'[()（）【】\[\]、，,。.·\-—~&/\\|:：!？?"\'“”‘’\s]+')
TOKEN_SPLIT = re.compile(r'[()\[\]{}<>《》【】「」『』、，,。.·\-—/\\|:：!？?"\'\s]+')


# ============================================================
# 小工具
# ============================================================
def _now_ms():
    return int(time.time() * 1000)


def _num(v, default=0):
    try:
        return int(float(str(v).strip()))
    except Exception:
        try:
            return int(v)
        except Exception:
            return default


def _text_of(r):
    """把 requests.Response / base.Spider.fetch 返回值统一成文本。"""
    if r is None:
        return ''
    if isinstance(r, (str, bytes)):
        if isinstance(r, bytes):
            try:
                return r.decode('utf-8', 'ignore')
            except Exception:
                return ''
        return r
    for attr in ('content', 'text'):
        try:
            v = getattr(r, attr, None)
            if v is None:
                continue
            if isinstance(v, bytes):
                return v.decode('utf-8', 'ignore')
            if isinstance(v, str):
                return v
        except Exception:
            continue
    try:
        return str(r)
    except Exception:
        return ''


# 图片直链 http -> https
def _fix_pic(u):
    s = '' if u is None else str(u).strip()
    if not s:
        return ''
    if s.startswith('//'):
        return 'https:' + s
    if s.startswith('http://'):
        return 'https://' + s[7:]
    return s


def _first_year(s):
    if not s:
        return ''
    m = re.search(r'(\d{4})', str(s))
    return m.group(1) if m else ''


# 有界 TTL 缓存（以 dict 插入序近似 LRU）
class _Cache(object):
    def __init__(self):
        self._d = {}
        self._lock = threading.RLock()

    def get(self, key, ttl):
        with self._lock:
            e = self._d.get(key)
            if not e:
                return None
            if (_now_ms() - e[0]) >= ttl:
                self._d.pop(key, None)
                return None
            return e[1]

    def set(self, key, val, cap=256):
        with self._lock:
            self._d.pop(key, None)
            self._d[key] = (_now_ms(), val)
            while len(self._d) > (cap or 256):
                try:
                    k = next(iter(self._d))
                except StopIteration:
                    break
                self._d.pop(k, None)

    # 忽略 TTL 的原始读取（首页兜底用）
    def raw(self, key):
        with self._lock:
            e = self._d.get(key)
            return e[1] if e else None


# extend 解析：兼容「已解析 dict」/「JSON 字符串」/「a=b&c=d」
def _parse_extend(extend):
    if not extend:
        return {}
    if isinstance(extend, dict):
        return extend
    if isinstance(extend, (list, tuple)):
        out = {}
        for item in extend:
            if isinstance(item, dict):
                for k, v in item.items():
                    out[str(k)] = v
        return out
    s = str(extend).strip()
    if not s:
        return {}
    if s.startswith('{'):
        try:
            o = json.loads(s)
            return o if isinstance(o, dict) else {}
        except Exception:
            return {}
    # 纯字符串形如 k=v&k2=v2：仅作为兜底补充
    if '=' in s and '&' in s:
        out = {}
        for kv in s.split('&'):
            if '=' not in kv:
                continue
            k, v = kv.split('=', 1)
            out[k.strip()] = v.strip()
        return out
    return {}


# 列表项对外只暴露标准字段
def _clean_vod(v):
    return {
        'vod_id': v.get('vod_id'),
        'vod_name': v.get('vod_name'),
        'vod_pic': v.get('vod_pic'),
        'vod_remarks': v.get('vod_remarks'),
    }


# ============================================================
# 签名（与前端 JS / py 完全一致）
#   - key 升序
#   - dict/list 用紧凑 JSON（等价 json.dumps(separators=(',', ':'))）
#   - 标量直接字符串化
# ============================================================
def _scalar_str(v):
    if v is True:
        return 'true'
    if v is False:
        return 'false'
    if v is None:
        return 'null'
    return str(v)


def _sign_string(data):
    parts = []
    for k in sorted(data.keys()):
        v = data[k]
        if isinstance(v, (dict, list)):
            parts.append('%s=%s&' % (k, json.dumps(v, ensure_ascii=False, separators=(',', ':'))))
        else:
            parts.append('%s=%s&' % (k, _scalar_str(v)))
    return ''.join(parts)


def _md5_hex(s):
    try:
        return hashlib.md5(s.encode('utf-8')).hexdigest()
    except Exception:
        return hashlib.md5(str(s).encode('utf-8', 'ignore')).hexdigest()


def _build_signed_body(data, now):
    msg = 'time:%d|privateKey:%s|data:%s' % (now, PRIVATE_KEY, _sign_string(data))
    return {'time': now, 'sign': _md5_hex(msg), 'data': data}


# ============================================================
# 蜘蛛本体
# ============================================================
class Spider(_BaseSpider):

    def __init__(self, *args, **kwargs):
        try:
            super(Spider, self).__init__(*args, **kwargs)
        except Exception:
            pass
        self._state = None
        self._st_lock = threading.RLock()

    # ---------------- 基础设施 ----------------
    def _log(self, msg):
        try:
            fn = getattr(self, 'log', None)
            if callable(fn):
                fn(msg)
        except Exception:
            pass

    def _sleep(self, ms):
        d = _num(ms, 0)
        if d <= 0:
            return
        try:
            time.sleep(d / 1000.0)
        except Exception:
            pass

    def _state_of(self):
        st = self._state
        if st is not None:
            return st
        with self._st_lock:
            if self._state is None:
                self._state = {
                    'words': _Cache(),
                    'pages': _Cache(),
                    'cats': {},
                    'detail': _Cache(),
                    'play': _Cache(),
                    'listMeta': _Cache(),
                    'search': _Cache(),
                    'corpus': None,
                    'corpusTime': 0,
                    'host': HOST_CANDIDATES[0],
                    'api': API_BASE,
                    'hostChecked': 0,
                }
            return self._state

    # ---------------- 网络层 ----------------
    def _http(self, url, method='GET', headers=None, data=None, timeout=None):
        """统一 HTTP 入口：requests -> base.Spider.fetch -> urllib，返回 (code, text)。"""
        headers = dict(headers or {})
        to_ms = TIMEOUT_API if timeout is None else _num(timeout, TIMEOUT_API)
        timeout_s = max(1.0, to_ms / 1000.0)

        if _requests is not None:
            try:
                if method == 'POST':
                    r = _requests.post(url, data=data, headers=headers, timeout=timeout_s, verify=False)
                else:
                    r = _requests.get(url, headers=headers, timeout=timeout_s, verify=False)
                return (r.status_code, _text_of(r))
            except Exception as e:
                self._log('http %s %s error: %s' % (method, url, e))

        # 宿主内置 fetch 兜底（仅 GET，可走宿主代理/网络策略）
        if method == 'GET':
            try:
                fn = getattr(self, 'fetch', None)
                if callable(fn):
                    return (200, _text_of(fn(url, headers=headers, timeout=timeout_s)))
            except Exception as e:
                self._log('fetch %s error: %s' % (url, e))

        try:
            body = None
            if data is not None:
                body = data.encode('utf-8') if isinstance(data, str) else data
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as resp:
                return (getattr(resp, 'status', 200), resp.read().decode('utf-8', 'ignore'))
        except Exception as e:
            self._log('urllib %s %s error: %s' % (method, url, e))
            return (0, '')

    @staticmethod
    def _to_json_obj(text):
        if text is None:
            return None
        s = str(text).strip()
        if not s:
            return None
        if s[0] not in ('{', '['):
            return None
        try:
            return json.loads(s)
        except Exception:
            return None

    def _post_json(self, url, body_str, headers):
        """
        多种 POST 形态依次尝试，只认「像本 API 的 JSON 响应」。

        [FIX-2026-11·3] 真机「无数据」的关键修复：POST 体必须是「已序列化好的 JSON 字符串」，
        原样发出（不要交给宿主再序列化一次），否则实际发出的体变成 "{\\"time\\":...}"
        （外层多了一层引号与转义）→ 签名体错位 → 服务端一律回 {"msgType":-1,...}
        → 首页 / 分类 / 搜索 / 详情全部为空。
        """
        last_api = None   # 见过的最像「本 API」的响应（msgType 存在），留作兜底

        def _judge(text):
            obj = self._to_json_obj(text)
            return obj

        # 形态 1：字符串直发（标准）
        code, text = self._http(url, 'POST', headers, body_str, TIMEOUT_API)
        obj = _judge(text)
        if isinstance(obj, dict) and 'msgType' in obj:
            if _num(obj.get('msgType'), -1) == 0:
                return obj
            last_api = obj
        else:
            bad = '' if text is None else str(text)
            if len(re.sub(r'\s', '', bad)) > 200:
                # 内容偏长说明已到服务器但被 WAF 拦截：换形态结果也一样
                return None

        # 形态 2：宿主自带 post（老版本 base 提供，体仍是字符串）
        if last_api is None:
            try:
                fn = getattr(self, 'post', None)
                if callable(fn):
                    r = fn(url, body_str, headers=headers, timeout=max(1.0, TIMEOUT_API / 1000.0))
                    text2 = _text_of(r)
                    obj2 = self._to_json_obj(text2)
                    if isinstance(obj2, dict) and 'msgType' in obj2:
                        if _num(obj2.get('msgType'), -1) == 0:
                            return obj2
                        last_api = obj2
            except Exception:
                pass

        return last_api

    def _api_post(self, st, path, data):
        url = st['api'] + path
        # 优先从域名跟随预热拿到的 host，避免 Referer/Origin 与实际请求 host 不一致触发反爬
        req_host = st.get('host') or HOST_CANDIDATES[0]
        last_resp = None
        for attempt in range(API_MAX_RETRY):
            if attempt > 0:
                # 退避等待：被 WAF 拦后不能马上重发，越急越被拦，间隔随次数递增
                self._sleep(API_RETRY_BASE * (1 + attempt // 2) + random.randint(0, 500))
            # 每次重试都重新生成签名和时间戳，避免 sign 过期/重复
            body = _build_signed_body(data, _now_ms())
            body_str = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
            headers = dict(BASE_HEADERS)
            headers['Content-Type'] = 'application/json;charset=UTF-8'
            headers['Referer'] = req_host + '/'
            headers['Origin'] = req_host
            try:
                resp = self._post_json(url, body_str, headers)
            except Exception as e:
                self._log('api_post %s error: %s' % (path, e))
                resp = None
            if isinstance(resp, dict) and _num(resp.get('msgType'), -1) == 0:
                return resp
            if isinstance(resp, dict) and 'msgType' in resp:
                last_resp = resp
                # 明确业务错误（非 -1）不是 WAF 问题，不用重试
                if _num(resp.get('msgType'), -1) != -1:
                    break
        return last_resp

    # 域名跟随（best-effort，失败不阻塞）+ API 预热取 Cookie
    def _follow_host(self, st):
        checked = _num(st.get('hostChecked'), 0)
        if checked and (_now_ms() - checked < TTL_DOMAIN):
            return
        st['hostChecked'] = _now_ms()
        for h in HOST_CANDIDATES:
            try:
                code, html = self._http(
                    h + '/',
                    'GET',
                    {'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml'},
                    None,
                    5000,
                )
                html = (html or '')[:200000]
                if '埋堆堆' in html or 'mddcloud' in html:
                    st['host'] = h
                    # 额外访问一次静态 JS 路径，让 WAF 放行后续 API 请求
                    try:
                        self._http(h + '/static/js/', 'GET', {'User-Agent': UA}, None, 3000)
                    except Exception:
                        pass
                    return
            except Exception:
                continue

    # ---------------- 数据层 ----------------
    @staticmethod
    def _to_vod(v):
        if not isinstance(v, dict):
            return None
        vid = str(v.get('uuid') or v.get('vodUuid') or '').strip()
        name = str(v.get('name') or '').strip()
        if not vid or not name:
            return None
        return {
            'vod_id': vid,
            'vod_name': name,
            'vod_pic': _fix_pic(v.get('coverImage') or v.get('sideImage') or v.get('downImage')),
            'vod_remarks': '',
            # 内部字段，仅用于本地分类/回填，交付前由 _clean_vod 剥掉
            '_material': str(v.get('materialName') or ''),
            '_year': str(v.get('yearName') or ''),
            '_vod_type': _num(v.get('vodType'), 0),
            '_total_num': _num(v.get('totalNum'), 0),
        }

    def _fetch_list(self, st, uuid_list, rows, start_row, is_vip, order):
        # [FIX-2026-11] 该路径被腾讯云 WAF 按“精确路径”规则拦截（无尾斜杠 => 403 WAF 页）。
        # 追加一个尾斜杠即可命中同一后端路由并绕过该条 WAF 规则，响应仍为正常 JSON。
        resp = self._api_post(st, '/api/vod/classify/word/search.action/', {
            'uuidList': uuid_list or [],
            'rows': rows,
            'startRow': start_row,
            'isVip': str(is_vip),
            'orderType': str(order),
        })
        if not resp or _num(resp.get('msgType'), -1) != 0:
            return []
        arr = resp.get('data') or []
        out = []
        for raw in arr:
            item = self._to_vod(raw)
            if not item:
                continue
            out.append(item)
            # 回填详情元信息（getVodInfo 的 year/material 可能为空）
            try:
                if len(st['listMeta']._d) < 8000:
                    st['listMeta'].set(item['vod_id'], {'_material': item['_material'], '_year': item['_year']}, 9000)
            except Exception:
                pass
        return out

    # 单页（带缓存）
    def _get_page(self, st, uuid_list, is_vip, order, p):
        key = json.dumps(uuid_list or [], ensure_ascii=False) + '|' + str(is_vip) + '|' + str(order) + '|' + str(p)
        cached = st['pages'].get(key, TTL_LIST)
        if cached is not None:
            return cached
        lst = self._fetch_list(st, uuid_list, PAGE_ROWS, (p - 1) * PAGE_ROWS, is_vip, order)
        if lst:
            st['pages'].set(key, lst, 512)
        return lst

    # 分类词表
    def _classify_words(self, st):
        cached = st['words'].get('__w__', TTL_WORDS)
        if cached is not None:
            return cached
        data = self._api_post(st, '/api/vod/classify/list.action/', {})
        words = {}
        if data and _num(data.get('msgType'), -1) == 0 and data.get('data'):
            for item in data.get('data') or []:
                if not isinstance(item, dict):
                    continue
                fc = item.get('fieldCode') or ''
                ws = []
                for w in item.get('words') or []:
                    if not isinstance(w, dict):
                        continue
                    uuid = str(w.get('uuid') or '')
                    name = str(w.get('word') or '').strip()
                    if name and name != '全部' and uuid:
                        ws.append({'word': name, 'uuid': uuid})
                if fc and ws:
                    words[fc] = ws
        if words:
            st['words'].set('__w__', words, 4)
            return words
        return {}

    # 把「词名」或「uuid」统一解析为 uuid（F18: 彻底放弃格式启发式）
    @staticmethod
    def _resolve_uuid(words, field, raw):
        r = '' if raw is None else str(raw).strip()
        if not r:
            return ''
        arr = words.get(field) or []
        for it in arr:
            if it.get('word') == r:
                return it.get('uuid') or ''
        for it in arr:
            if it.get('uuid') == r:
                return r
        return ''

    @staticmethod
    def _build_filters(words):
        def mk(fc, name):
            value = [{'n': '全部', 'v': ''}]
            for it in words.get(fc) or []:
                value.append({'n': it.get('word'), 'v': it.get('uuid')})
            return {'key': fc, 'name': name, 'value': value}

        return [
            mk('material', '题材'),
            mk('lang', '语言'),
            mk('region', '地区'),
            mk('year', '年份'),
            {
                'key': 'isvip', 'name': '收费', 'value': [
                    {'n': '全部', 'v': '-1'},
                    {'n': '限免', 'v': '0'},
                    {'n': 'VIP', 'v': '1'},
                ],
            },
            {
                'key': 'order', 'name': '排序', 'value': [
                    {'n': '默认', 'v': '0'},
                    {'n': '最新', 'v': '1'},
                    {'n': '好评', 'v': '2'},
                ],
            },
        ]

    # ============================================================
    # 本地分类规则（后端不支持按 vodType/material 过滤）
    # 优先级: 纪录片 > 动画 > 电影 > 综艺 > 剧集
    # ============================================================
    @staticmethod
    def _match_category(vod, tid):
        mats = {}
        for x in str(vod.get('_material') or '').split(','):
            x = x.strip()
            if x:
                mats[x] = 1
        # [FIX-2026-11·3] 站点 vodType 口径（取自详情页前端 filterVodType 映射）：
        #   0=剧集  1=电影  2=综艺  7=直播
        # 旧实现用「vt==1 && tn==1」判电影，而列表接口的 vodType 实测几乎恒为 0，
        # 该判定永远不成立 => 电影分类永远为空。现按站点原口径用 vodType 直接分型。
        vt = _num(vod.get('_vod_type'), 0)
        name = str(vod.get('vod_name') or '')

        if vt == 7:
            return False

        is_doc = bool(mats.get('纪录片'))
        is_anime = bool(mats.get('动漫')) or (bool(mats.get('儿童')) and ANIME_NAME_RE.search(name) is not None)
        is_movie = (vt == 1)
        # 实测：material=综艺 的条目 vodType=6；无筛选深层里 vodType=2/6 均为综艺类。
        is_var = (vt == 2 or vt == 6)
        if not is_var:
            # 兜底：个别条目 vodType 缺失时，用 material 的综艺类标签补判
            for label in VARIETY_LABELS:
                if mats.get(label):
                    is_var = True
                    break

        if tid == 'documentary':
            return is_doc
        if tid == 'anime':
            return is_anime
        if tid == 'movie':
            return is_movie
        if tid == 'variety':
            return is_var and not is_doc and not is_anime
        if tid == 'tv':
            return (not is_doc) and (not is_anime) and (not is_movie) and (not is_var)
        return False

    # 单页带重试获取：接口有突发频控，偶发 403/空页要重试，而不是直接判“到底了”
    def _get_page_stable(self, st, uuid_list, is_vip, order, p):
        for t in range(SCAN_PAGE_RETRY):
            try:
                lst = self._get_page(st, uuid_list, is_vip, order, p)
            except Exception:
                lst = None
            if lst:
                return lst
            if t < SCAN_PAGE_RETRY - 1:
                self._sleep(SCAN_RETRY_GAP * (t + 1))
        return []

    # ---- 增量扫描：接口有 WAF 突发频控，240 页一次性拉完极易被整段拦截，
    #      改为「按需分批 + 实例态累积 + 时间预算」，兼顾速度与覆盖。----
    @staticmethod
    def _cat_state(st, key):
        with _CAT_LOCK:
            cats = st.get('cats')
            if cats is None:
                cats = {}
                st['cats'] = cats
            if len(cats) > 6:            # 简单防膨胀
                cats = {}
                st['cats'] = cats
            cs = cats.get(key)
            if (not cs) or ((_now_ms() - cs.get('time', 0)) > TTL_LIST):
                cs = {
                    'key': key,
                    'time': _now_ms(),
                    'seen': {},
                    'buckets': {'tv': [], 'movie': [], 'variety': [], 'anime': [], 'documentary': []},
                    'cursor': 1,
                    'jump': 0,
                    'done': False,
                    'doneTime': 0,
                    'emptyStreak': 0,
                    'cooldownUntil': 0,
                }
                cats[key] = cs
            return cs

    # 页面推进计划 [FIX-2026-11·3]：前段顺序 + 深层按步长跳扫
    @staticmethod
    def _next_batch(cs, n):
        out = []
        while len(out) < n:
            if cs['cursor'] <= SCAN_SEQ_PAGES:
                out.append(cs['cursor'])
                cs['cursor'] += 1
                continue
            if not cs['jump']:
                cs['jump'] = SCAN_JUMP_FROM
            if cs['jump'] > MAX_PAGES_SCAN:
                cs['done'] = True
                break
            out.append(cs['jump'])
            cs['jump'] += SCAN_JUMP_STEP
        return out

    # 扫一批（SCAN_CONCURRENCY 页）并入累积桶；返回本批是否拿到数据
    def _scan_once(self, st, uuid_list, is_vip, order, cs):
        if cs.get('done'):
            return False
        # [FIX-2026-11·6] 冷却期间不发请求，等 WAF 解封后再扫，避免持续触发反爬
        cd = _num(cs.get('cooldownUntil'), 0)
        if cd and _now_ms() < cd:
            return False
        # 冷却到点自动重置状态，允许恢复扫描
        if cd and _now_ms() >= cd:
            cs['cooldownUntil'] = 0
            cs['emptyStreak'] = 0

        batch = self._next_batch(cs, SCAN_CONCURRENCY)
        if not batch:
            cs['done'] = True
            return False

        results = []
        try:
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures = [pool.submit(self._get_page_stable, st, uuid_list, is_vip, order, p) for p in batch]
                for f in futures:
                    try:
                        results.append(f.result())
                    except Exception:
                        results.append([])
        except Exception:
            # 线程池不可用时退化为顺序执行
            results = [self._get_page_stable(st, uuid_list, is_vip, order, p) for p in batch]

        got = 0
        tail = False
        for i, lst in enumerate(results):
            lst = lst or []
            if not lst:
                continue
            got += len(lst)
            for v in lst:
                vid = v['vod_id']
                if cs['seen'].get(vid):
                    continue
                cs['seen'][vid] = 1
                for tid in CATEGORIES:
                    if self._match_category(v, tid):
                        cs['buckets'][tid].append(v)
                        break
            # 只把「顺序段」的短页当尾页；跳扫段命中空页属于正常采样
            if len(lst) < PAGE_ROWS and batch[i] <= SCAN_SEQ_PAGES:
                tail = True

        if tail:
            # 真的到尾页才永久结束
            cs['done'] = True
            cs['doneTime'] = _now_ms()
        if got == 0:
            cs['emptyStreak'] = _num(cs.get('emptyStreak'), 0) + 1
            # [FIX-2026-11·6] 空页判定从 3 次放宽到 5 次，避免偶发 WAF 拦截误判扫到底；
            # 达到阈值后不永久锁死，冷却 3 分钟后允许重新尝试，WAF 恢复后自动恢复数据
            if cs['emptyStreak'] >= 5:
                cs['cooldownUntil'] = _now_ms() + 3 * 60 * 1000
        else:
            cs['emptyStreak'] = 0
            cs['cooldownUntil'] = 0
        return got > 0

    # 累积桶的全部条目（去重后）
    @staticmethod
    def _cat_all_items(cs):
        out = []
        for k in CATEGORIES:
            out.extend((cs.get('buckets') or {}).get(k) or [])
        return out

    # ============================================================
    # 搜索匹配（token / 缩写 / 字符重叠 / 长度惩罚）
    # ============================================================
    @staticmethod
    def _normalize_name(name):
        return NAME_NOISE.sub('', str(name or '')).lower()

    @staticmethod
    def _tokenize(name):
        s = str(name or '')
        toks = [t for t in TOKEN_SPLIT.split(s) if t]
        if toks:
            return toks
        return [Spider._normalize_name(s)] if s else []

    @staticmethod
    def _initials_of(tokens):
        s = ''
        for t in tokens:
            if t:
                s += t[0]
        return s.lower()

    @staticmethod
    def _match_score(kw_norm, kw_tokens, kw_initials, title_norm, title_tokens, title_initials):
        best = 0
        if not kw_norm or not title_norm:
            return 0

        if kw_norm == title_norm:
            best = 100

        if (kw_norm in title_tokens) or (title_norm in kw_tokens):
            best = max(best, 85)

        if kw_norm and (kw_norm in title_norm):
            best = max(best, 65)

        if kw_tokens and title_tokens:
            if all(t in title_tokens for t in kw_tokens):
                best = max(best, 55)
            elif any(t in title_tokens for t in kw_tokens):
                best = max(best, 40)

        if kw_initials and title_initials and len(kw_initials) >= 2:
            if kw_initials in title_initials:
                best = max(best, 30)

        if best == 0 and len(kw_norm) >= 2:
            tset = set(title_norm)
            kset = set(kw_norm)
            overlap = len(kset & tset)
            if overlap >= max(2, int(round(len(kset) * 0.6))):
                best = max(best, min(20, overlap * 3))
        return best

    # 全库语料：复用分类扫描的累积进度（同一 key 即全库），按时间预算推进
    def _search_corpus(self, st):
        cp = st.get('corpus')
        if cp is not None and (_now_ms() - _num(st.get('corpusTime'), 0) < TTL_CORPUS):
            return cp

        cs = self._cat_state(st, FULL_SCAN_KEY)
        t0 = _now_ms()
        while (not cs['done']) and (_now_ms() - t0) < SEARCH_TIME_BUDGET:
            self._scan_once(st, [], '-1', '0', cs)
            if not cs['done']:
                self._sleep(SCAN_WAVE_GAP)

        collected = {}
        for item in self._cat_all_items(cs):
            if item['vod_id'] not in collected:
                collected[item['vod_id']] = item
        st['corpus'] = collected
        st['corpusTime'] = _now_ms()
        return collected

    # ============================================================
    # 播放解析
    # ============================================================
    def _probe_play_url(self, url):
        if not url:
            return False
        headers = dict(BASE_HEADERS)
        headers['Range'] = 'bytes=0-0'
        try:
            code, text = self._http(url, 'GET', headers, None, TIMEOUT_PROBE)
            if not code:
                return False
            return len(text or '') > 0
        except Exception:
            return False

    def _resolve_play(self, st, play_key):
        cached = st['play'].get(play_key, TTL_PLAY)
        if cached is not None:
            return cached

        real = ''
        first_cand = ''
        try:
            idx = play_key.find(':')
            vid = play_key[:idx].strip()
            num = _num(play_key[idx + 1:], 0)
            resp = self._api_post(st, '/api/vod/getTrySaction.action/', {'vodUuid': vid, 'num': num})
            if resp and _num(resp.get('msgType'), -1) == 0 and isinstance(resp.get('data'), dict):
                d = resp['data']
                for field in PLAY_FIELD_PRIORITY:
                    u = str(d.get(field) or '').strip()
                    if not u:
                        continue
                    cand = _fix_pic(u)
                    if not first_cand:
                        first_cand = cand
                    if self._probe_play_url(cand):
                        real = cand
                        break
        except Exception:
            real = ''
        # [FIX-2026-11] 探测(Range 请求)可能因 CDN/频控失败；此时不要丢弃已拿到的直链，
        # 回退用首个候选地址，仍按直链(parse:0)交给播放器，避免退化成无法播放的 vid:num。
        if not real:
            real = first_cand
        if real:
            st['play'].set(play_key, real, 256)
        return real

    @staticmethod
    def _play_payload(st, url):
        return {
            'parse': 0,
            'jx': 0,
            'url': url,
            'header': {
                'User-Agent': UA,
                'Referer': st['host'] + '/',
                'Origin': st['host'],
            },
        }

    # ============================================================
    # 详情
    # ============================================================
    def _fetch_detail(self, st, vid):
        # [FIX-2026-11·4] 详情接口同样追加尾斜杠，与列表接口保持一致，规避真机 WAF 拦截
        resp = self._api_post(st, '/api/vod/getVodInfo.action/', {'vodUuid': vid, 'num': 1})
        if not resp or _num(resp.get('msgType'), -1) != 0 or not isinstance(resp.get('data'), dict):
            return {'list': []}
        v = resp['data']

        raw_list = [s for s in (v.get('vodSactionList') or []) if isinstance(s, dict) and s.get('num') is not None]
        if not raw_list:
            return {'list': []}

        sl = sorted(raw_list, key=lambda a: _num(a.get('num'), 0))
        if len(sl) > 200:
            sl = sl[-MAX_EPISODES:]
            sl.reverse()          # 超长剧最新集在前

        eps = []
        for s in sl:
            ep_name = str(s.get('name') or '').strip() or ('第%s集' % s.get('num'))
            eps.append(ep_name + '$' + vid + ':' + str(s.get('num')))

        # 元信息回填
        year = ''
        meta = st['listMeta'].get(vid, TTL_LIST * 24)
        if meta and meta.get('_year'):
            year = _first_year(meta['_year'])
        if not year:
            year = _first_year(v.get('yearName'))
        if not year and v.get('firstSowingTime'):
            raw = str(v.get('firstSowingTime'))
            if raw.isdigit():
                n = _num(raw, 0)
                ms = n if len(raw) >= 12 else (n * 1000 if len(raw) == 10 else n)
                try:
                    y = int(time.localtime(ms / 1000.0).tm_year)
                    if y > 1900:
                        year = str(y)
                except Exception:
                    year = ''
            else:
                m = re.search(r'(19|20)\d{2}', raw)
                if m:
                    year = m.group(0)

        name = str(v.get('name') or vid)
        vod_area = '中国内地' if re.search(r'(普通话|国语)', name) else '中国香港'

        remark_parts = []
        if v.get('updateNum'):
            remark_parts.append('更新至%s集' % v.get('updateNum'))

        detail = {
            'vod_id': vid,
            'vod_name': name,
            'vod_pic': _fix_pic(v.get('coverImage') or v.get('sideImage') or v.get('downImage')),
            'vod_year': year,
            'vod_area': vod_area,
            'vod_actor': str(v.get('starring') or '').replace(',', '/'),
            'vod_director': str(v.get('director') or '').replace(',', '/'),
            'vod_remarks': '·'.join(remark_parts),
            'vod_content': str(v.get('introduction') or '').strip(),
            'vod_play_from': '埋堆堆',
            'vod_play_url': '#'.join(eps) if eps else '📖 查看说明$about',
        }
        return {'list': [detail]}

    # 首页推荐（5 分钟缓存 + 失败回退旧缓存）
    def _first_page(self, st):
        # [FIX-2026-11·6] 首页推荐加 5 分钟缓存 + 失败回退缓存，避免偶发 WAF 拦截导致首页完全为空
        cached = st['pages'].get('__home__', 5 * 60 * 1000)
        if cached:
            return cached
        lst = []
        # 首页和列表用同样的重试逻辑，不是一次失败就空
        for t in range(SCAN_PAGE_RETRY):
            try:
                lst = self._fetch_list(st, [], PAGE_ROWS, 0, '-1', '0')
            except Exception:
                lst = []
            if lst:
                break
            if t < SCAN_PAGE_RETRY - 1:
                self._sleep(SCAN_RETRY_GAP * (t + 1))
        if lst:
            st['pages'].set('__home__', lst, 32)
            return lst
        # 真的拿不到新数据时，返回旧缓存兜底（哪怕过期了也比空列表好）
        stale = st['pages'].raw('__home__')
        return stale if stale else []

    # ============================================================
    # 内核导出方法
    # ============================================================
    def init(self, extend=""):
        st = self._state_of()
        # 兼容配置里传 JSON 对象 / JSON 字符串 / "k=v,k=v" 三种形态
        if isinstance(extend, dict):
            for k, val in extend.items():
                k = str(k).strip().lower()
                val = str(val).strip()
                if not val:
                    continue
                if k == 'host':
                    st['host'] = (val if val.startswith('http') else 'https://' + val).rstrip('/')
                elif k == 'api':
                    st['api'] = (val if val.startswith('http') else 'https://' + val).rstrip('/')
            return
        e = '' if extend is None else str(extend)
        if e.strip().startswith('{'):
            try:
                obj = json.loads(e)
                if isinstance(obj, dict):
                    self.init(obj)
                    return
            except Exception:
                pass
        for kv in e.split(','):
            if '=' not in kv:
                continue
            k, val = kv.split('=', 1)
            k = k.strip().lower()
            val = val.strip()
            if not val:
                continue
            if k == 'host':
                st['host'] = (val if val.startswith('http') else 'https://' + val).rstrip('/')
            elif k == 'api':
                st['api'] = (val if val.startswith('http') else 'https://' + val).rstrip('/')

    def getName(self):
        return '埋堆堆'

    # 动态分类 + 筛选项 + 首页推荐
    def homeContent(self, filter):
        st = self._state_of()
        cls = [{'type_id': c['type_id'], 'type_name': c['type_name']} for c in ALL_CLASSES]
        out = {'class': cls, 'list': []}

        try:
            self._follow_host(st)
        except Exception:
            pass

        try:
            words = self._classify_words(st)
            if words:
                # F11: filters 必须是 {type_id: [Filter...]} 字典（5 个一级 tab 共用同一份词表）
                arr = self._build_filters(words)
                out['filters'] = {c['type_id']: [dict(f) for f in arr] for c in ALL_CLASSES}
        except Exception as e:
            self._log('homeContent filters error: %s' % e)

        try:
            first = self._first_page(st)
            out['list'] = [_clean_vod(v) for v in first]
        except Exception as e:
            self._log('homeContent list error: %s' % e)

        return out

    def homeVideoContent(self):
        st = self._state_of()
        try:
            first = self._first_page(st)
            return {'list': [_clean_vod(v) for v in first]}
        except Exception:
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        st = self._state_of()
        page = max(1, _num(pg, 1))
        tid_s = '' if tid is None else str(tid)

        if tid_s not in VALID_TIDS:
            return {'list': [], 'page': page, 'pagecount': 0, 'limit': PAGE_ROWS, 'total': 0}
        try:
            ext = _parse_extend(extend)
            if not ext:
                ext = _parse_extend(filter)

            words = self._classify_words(st)

            uuid_list = []
            for field in ['lang', 'material', 'year', 'region']:
                raw = str(ext.get(field) or '').strip()
                if not raw:
                    continue
                u = self._resolve_uuid(words, field, raw)
                if u:
                    uuid_list.append(u)

            is_vip = str(ext.get('isvip') or '-1').strip() or '-1'
            order = str(ext.get('order') or '0').strip() or '0'

            key = json.dumps(uuid_list, ensure_ascii=False) + '|' + is_vip + '|' + order
            cs = self._cat_state(st, key)
            need = page * PAGE_ROWS
            t0 = _now_ms()
            while (not cs['done']) and (len(cs['buckets'].get(tid_s) or []) < need) \
                    and (_now_ms() - t0) < CAT_TIME_BUDGET:
                self._scan_once(st, uuid_list, is_vip, order, cs)
                if not cs['done']:
                    self._sleep(SCAN_WAVE_GAP)

            cat_list = cs['buckets'].get(tid_s) or []
            total = len(cat_list)
            # 扫描未收尾时总页数未知 => 999（壳子会一直允许继续翻页）
            pagecount = max(1, (total + PAGE_ROWS - 1) // PAGE_ROWS) if cs['done'] else 999
            start = (page - 1) * PAGE_ROWS

            return {
                'list': [_clean_vod(v) for v in cat_list[start:start + PAGE_ROWS]],
                'page': page,
                'pagecount': pagecount,
                'limit': PAGE_ROWS,
                'total': total,
            }
        except Exception as e:
            self._log('categoryContent error: %s' % e)
            return {'list': [], 'page': page, 'pagecount': 1, 'limit': PAGE_ROWS, 'total': 0}

    def detailContent(self, ids):
        st = self._state_of()
        if isinstance(ids, (list, tuple)):
            raw_id = ids[0] if ids else ''
        else:
            raw_id = ids
        vid = str(raw_id or '').split(',')[0].strip()
        if not vid:
            return {'list': []}

        cached = st['detail'].get(vid, TTL_DETAIL_OK)
        if cached is not None:
            return cached

        res = {'list': []}
        try:
            res = self._fetch_detail(st, vid)
        except Exception as e:
            self._log('detailContent error: %s' % e)
            res = {'list': []}
        if res.get('list'):
            st['detail'].set(vid, res, 64)
        return res

    def searchContent(self, key, quick, pg="1"):
        st = self._state_of()
        kw = str(key or '').strip()
        page = max(1, _num(pg, 1))
        limit = SEARCH_MAX_RESULTS

        if not kw:
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': limit, 'total': 0}

        try:
            result = st['search'].get(kw, TTL_SEARCH)
            if result is None:
                kw_norm = self._normalize_name(kw)
                kw_tokens = [t.lower() for t in self._tokenize(kw)]
                kw_initials = self._initials_of(kw_tokens)

                corpus = self._search_corpus(st)
                matched = []
                for item in corpus.values():
                    title = item.get('vod_name') or ''
                    title_norm = self._normalize_name(title)
                    title_tokens = [t.lower() for t in self._tokenize(title)]
                    title_initials = self._initials_of(title_tokens)
                    score = self._match_score(kw_norm, kw_tokens, kw_initials,
                                              title_norm, title_tokens, title_initials)
                    if score == 0:
                        continue
                    score -= min(5, max(0, len(title) - len(kw)))
                    matched.append({'score': score, 'title': title, 'item': item})
                matched.sort(key=lambda m: (-m['score'], m['title']))
                result = [_clean_vod(m['item']) for m in matched[:SEARCH_MAX_RESULTS]]
                if result:
                    st['search'].set(kw, result, 64)

            total = len(result)
            pagecount = max(1, (total + limit - 1) // limit)
            start = (page - 1) * limit
            return {
                'list': result[start:start + limit],
                'page': page,
                'pagecount': pagecount,
                'limit': limit,
                'total': total,
            }
        except Exception as e:
            self._log('searchContent error: %s' % e)
            return {'list': [], 'page': page, 'pagecount': 1, 'limit': limit, 'total': 0}

    def playerContent(self, flag, id, vipFlags=None):
        st = self._state_of()
        if not id:
            return {'parse': 0, 'jx': 0, 'url': ''}
        play_key = str(id).strip()

        # 裸直链（如某些线路直接给 http 地址）：原样交给播放器
        if re.match(r'(?i)^https?://', play_key):
            return self._play_payload(st, _fix_pic(play_key))
        # 非 {vid}:{num} 键（如说明用伪线路 about）：诚实降级为空 url
        if ':' not in play_key:
            return {'parse': 0, 'jx': 0, 'url': ''}

        try:
            url = st['play'].get(play_key, TTL_PLAY)
            if not url:
                url = self._resolve_play(st, play_key)
            if url:
                return self._play_payload(st, url)
        except Exception as e:
            self._log('playerContent error: %s' % e)

        # F20 兜底：解析不到可播直链时交壳嗅探（诚实降级）
        return {
            'parse': 1,
            'jx': 1,
            'url': play_key,
            'header': {'User-Agent': UA, 'Referer': st['host'] + '/'},
        }

    # 供宿主判断是否为视频直链（可选实现，内核未调用也不影响）
    def isVideoFormat(self, url):
        return bool(re.search(r'(?i)\.(m3u8|mp4|flv|ts)(\?|$)', str(url or '')))

    def manualVideoCheck(self):
        return False


# 分类扫描状态字典的互斥锁（多线程/多请求并发时保护 st['cats']）
_CAT_LOCK = threading.RLock()

# 全库（无筛选）扫描状态 key，分类与搜索共用同一份累积进度
FULL_SCAN_KEY = json.dumps([]) + '|-1|0'


# ============================================================
# 独立运行自测（作为插件加载时不会执行）
# ============================================================
if __name__ == '__main__':
    sp = Spider()
    sp.init('')
    t0 = time.time()
    home = sp.homeContent(False)
    print('首页分类:', [c['type_name'] for c in home.get('class') or []])
    print('首页推荐:', len(home.get('list') or []), '条, 筛选项:', len(home.get('filters') or {}), '组')
    for c in home.get('class') or []:
        r = sp.categoryContent(c['type_id'], 1, False, '')
        print('分类 %-12s %3d 条 pagecount=%s' % (c['type_name'], r.get('total', 0), r.get('pagecount')))
    first = (home.get('list') or [{}])[0]
    if first.get('vod_id'):
        d = sp.detailContent([first['vod_id']])
        item = (d.get('list') or [{}])[0]
        print('详情:', item.get('vod_name'), '| 线路:', item.get('vod_play_from'))
        ep = (item.get('vod_play_url') or '').split('#')[0]
        print('首集:', ep)
        pid = ep.split('$')[-1] if '$' in ep else ''
        if pid:
            p = sp.playerContent('埋堆堆', pid, None)
            print('播放:', p.get('parse'), (p.get('url') or '')[:110])
    s = sp.searchContent(first.get('vod_name') or '新闻女王', False, '1')
    print('搜索:', len(s.get('list') or []), '条')
    print('耗时: %.1fs' % (time.time() - t0))