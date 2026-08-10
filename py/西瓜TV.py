# -*- coding: utf-8 -*-
"""
西瓜TV Python Spider — 兼容 FongMi/TV (T3) 与 WebHomeTV / PeekPro (T4)
站点: xiguatv 系列域名（主域名 + 多备用域名自动探测切换）

特性:
  - 多域名并发探测与自动切换（5 个备用域名，自动选最快的）
  - AES-256-CTR 接口加解密（与站点 app.js 一致）
  - 父分类 + 子分类筛选器（苹果 CMS 两层分类结构）
  - 直链 m3u8 直接播放 / 官源走 BFQ 解析（AES-CBC 解密）
  - POST 方法缓存 + 三重兜底（self.post → requests → urllib），SSL 全禁验
  - 初始化预热 POST 方法，后续请求直接走缓存方式，不用每次等超时
  - 域名失败时并发重试其他域名，用第一个成功的响应
  - 全链路短超时（8s POST / 6s GET），避免白屏转圈
"""

import sys
import json
import os
import re
import time
import uuid
import base64
import random
import threading

sys.path.append('..')

# ===== 兼容导入：FM 有基类，PeekPro 没有就自己定义 =====
try:
    from base.spider import Spider
except ImportError:
    import requests as _rq
    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:
        pass

    class Spider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            kw.pop('verify', None)
            r = _rq.get(url, headers=headers, timeout=15, verify=False, **kw)
            r.encoding = 'utf-8'
            return r

        def post(self, url, headers=None, data=None, timeout=None):
            r = _rq.post(url, headers=headers, data=data, timeout=timeout or 15, verify=False)
            r.encoding = 'utf-8'
            return r

# 尝试导入 requests（POST 兜底 / localProxy 用）
try:
    import requests as requests
except ImportError:
    requests = None

from urllib.parse import quote, unquote, urljoin


# ============================================================
# 常量配置
# ============================================================

# 实际 API 站点为以下 5 个，全部互为镜像，自动探测选最快
API_DOMAINS = [
    "https://zhu1.xiguatv.xyz",
    "https://zhu2.xiguatv.xyz",
    "https://zhu3.xiguatv.xyz",
    "https://by1.xiguatv.xyz",
    "https://by2.xiguatv.xyz",
]

# AES-256-CTR 密钥（从站点 app.js 提取，32 字节）
AES_KEY = "wK05tMq7sH2aP1cQ6eB9rV3fG4hL8nDx"

# 通用 UA
UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

# 接口路径
API_PATHS = {
    "home": "/api/home",                       # GET，不加密
    "video_detail": "/api/video/detail",        # POST，加密
    "switch_episode": "/api/video/switch-episode",  # POST，加密
    "category_list": "/api/category/list",      # POST，加密
    "search": "/api/search",                    # POST，加密
    "video_latest": "/api/video/latest",
    "video_popular": "/api/video/popular",
}

# 父分类列表
CLASSES = [
    {"type_name": "电影", "type_id": "1"},
    {"type_name": "连续剧", "type_id": "18"},
    {"type_name": "动漫", "type_id": "24"},
    {"type_name": "综艺", "type_id": "25"},
    {"type_name": "B站", "type_id": "26"},
    {"type_name": "短剧", "type_id": "62"},
]

# 子分类筛选器
FILTERS = {
    "1": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "动作片", "v": "2"},
            {"n": "喜剧片", "v": "3"},
            {"n": "爱情片", "v": "4"},
            {"n": "科幻片", "v": "5"},
            {"n": "恐怖片", "v": "6"},
            {"n": "剧情片", "v": "7"},
            {"n": "战争片", "v": "8"},
            {"n": "惊悚片", "v": "9"},
            {"n": "犯罪片", "v": "10"},
            {"n": "冒险片", "v": "11"},
            {"n": "动画片", "v": "12"},
            {"n": "悬疑片", "v": "13"},
            {"n": "武侠片", "v": "14"},
            {"n": "奇幻片", "v": "15"},
            {"n": "纪录片", "v": "16"},
            {"n": "其他片", "v": "17"},
        ]},
        {"key": "by", "name": "排序", "value": [
            {"n": "最热", "v": "hot-desc"},
            {"n": "最新", "v": "latest-desc"},
            {"n": "视频最多", "v": "most_videos-desc"},
        ]},
    ],
    "18": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "国产剧", "v": "19"},
            {"n": "港台剧", "v": "20"},
            {"n": "欧美剧", "v": "21"},
            {"n": "日韩剧", "v": "22"},
            {"n": "其他剧", "v": "23"},
            {"n": "海外剧", "v": "49"},
            {"n": "泰剧", "v": "58"},
        ]},
        {"key": "by", "name": "排序", "value": [
            {"n": "最热", "v": "hot-desc"},
            {"n": "最新", "v": "latest-desc"},
            {"n": "视频最多", "v": "most_videos-desc"},
        ]},
    ],
    "24": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "国产动漫", "v": "54"},
            {"n": "日韩动漫", "v": "55"},
            {"n": "欧美动漫", "v": "56"},
            {"n": "港台动漫", "v": "63"},
            {"n": "海外动漫", "v": "64"},
            {"n": "有声动漫", "v": "74"},
        ]},
        {"key": "by", "name": "排序", "value": [
            {"n": "最热", "v": "hot-desc"},
            {"n": "最新", "v": "latest-desc"},
            {"n": "视频最多", "v": "most_videos-desc"},
        ]},
    ],
    "25": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆综艺", "v": "50"},
            {"n": "日韩综艺", "v": "51"},
            {"n": "港台综艺", "v": "52"},
            {"n": "欧美综艺", "v": "53"},
            {"n": "演唱会", "v": "65"},
        ]},
        {"key": "by", "name": "排序", "value": [
            {"n": "最热", "v": "hot-desc"},
            {"n": "最新", "v": "latest-desc"},
            {"n": "视频最多", "v": "most_videos-desc"},
        ]},
    ],
    "26": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "番剧", "v": "27"},
            {"n": "国创", "v": "28"},
        ]},
        {"key": "by", "name": "排序", "value": [
            {"n": "最热", "v": "hot-desc"},
            {"n": "最新", "v": "latest-desc"},
        ]},
    ],
    "62": [
        {"key": "by", "name": "排序", "value": [
            {"n": "最热", "v": "hot-desc"},
            {"n": "最新", "v": "latest-desc"},
        ]},
    ],
    "75": [
        {"key": "by", "name": "排序", "value": [
            {"n": "最热", "v": "hot-desc"},
            {"n": "最新", "v": "latest-desc"},
        ]},
    ],
    "76": [
        {"key": "by", "name": "排序", "value": [
            {"n": "最热", "v": "hot-desc"},
            {"n": "最新", "v": "latest-desc"},
        ]},
    ],
}

# 父分类选"全部"时无直接内容，用第一个子分类兜底
DEFAULT_SUBTYPE = {
    "1": "2",
    "18": "19",
    "24": "54",
    "25": "50",
    "26": "27",
}


# ============================================================
# AES-256-CTR 加解密（接口通信）
# ============================================================

def _aes_ctr(key_bytes, iv_bytes, data_bytes):
    """AES-256-CTR 加解密（对称）"""
    try:
        from Crypto.Cipher import AES
        from Crypto.Util import Counter
        ctr = Counter.new(128, initial_value=int.from_bytes(iv_bytes, 'big'))
        return AES.new(key_bytes, AES.MODE_CTR, counter=ctr).encrypt(data_bytes)
    except ImportError:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(iv_bytes))
        enc = cipher.encryptor()
        return enc.update(data_bytes) + enc.finalize()


def _encrypt_body(obj):
    """加密请求体：返回 {data, iv} 均 Base64"""
    key = AES_KEY.encode('utf-8')
    iv = os.urandom(16)
    ct = _aes_ctr(key, iv, json.dumps(obj, ensure_ascii=False).encode('utf-8'))
    return {
        "data": base64.b64encode(ct).decode(),
        "iv": base64.b64encode(iv).decode(),
    }


def _decrypt_body(o):
    """解密响应体：输入 {data, iv}"""
    if not isinstance(o, dict) or 'iv' not in o or 'data' not in o:
        return o
    key = AES_KEY.encode('utf-8')
    iv = base64.b64decode(o['iv'])
    ct = base64.b64decode(o['data'])
    pt = _aes_ctr(key, iv, ct)
    return json.loads(pt.decode('utf-8', 'ignore'))


# ============================================================
# Spider 主类
# ============================================================

class Spider(Spider):

    def getName(self):
        return "西瓜TV"

    # ===== 初始化 =====
    def init(self, extend=""):
        if isinstance(extend, list):
            self.extend = ""
        else:
            self.extend = extend or ""

        self.header = {
            "User-Agent": UA,
            "Referer": "https://zhu1.xiguatv.xyz/",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        }
        self.device_id = str(uuid.uuid4())

        # 并发探测可用域名，选最快的
        self.host = API_DOMAINS[0]
        self._probe_domain()

        # 首页缓存（5 分钟）
        self._home_cache = []
        self._home_cache_time = 0

        # POST 方法缓存：记住哪种方式能用，避免每次都从头试
        # 值: "self.post" / "requests" / "urllib" / None(还没测过)
        self._post_method = None

        # 预热 POST 方法缓存（用一个轻量请求快速找出哪种方式能用）
        # 这样后续搜索/分类/详情页都能直接用缓存的方法，不用每次等超时
        self._warmup_post()

    def _warmup_post(self):
        """预热：发一个轻量 POST 请求，缓存能用的方法"""
        body = {"keyword": "a", "page": 1, "pageSize": 1}
        enc = _encrypt_body(body)
        raw = json.dumps(enc).encode('utf-8')
        headers = dict(self.header)
        headers["Content-Type"] = "application/json"
        url = self.host + API_PATHS["search"]
        # 短超时快速测试，不在乎返回内容，只在乎哪种方法能通
        self._do_post(url, raw, headers, timeout=5)

    # ===== 并发域名探测（选最快的）=====
    def _probe_domain(self):
        """并发探测所有域名，选响应最快的（最多等 5 秒）"""
        results = []
        lock = threading.Lock()

        def _test_one(domain):
            try:
                start = time.time()
                rsp = self.fetch(domain + "/api/home?lang=zh", headers=self.header, timeout=4)
                text = self._rsp_text(rsp)
                if text and len(text) > 100 and '"data"' in text:
                    elapsed = time.time() - start
                    with lock:
                        results.append((elapsed, domain))
            except Exception:
                pass

        threads = []
        for domain in API_DOMAINS:
            t = threading.Thread(target=_test_one, args=(domain,))
            t.daemon = True
            t.start()
            threads.append(t)

        # 最多等 5 秒，谁先回来谁赢
        deadline = time.time() + 5
        for t in threads:
            remaining = max(0.1, deadline - time.time())
            t.join(timeout=remaining)
            if results:
                break  # 已有结果，不等慢的了

        if results:
            results.sort()
            self.host = results[0][1]
            self.header["Referer"] = self.host + "/"
            return

        # 并发全部失败 → 顺序兜底（快速）
        for domain in API_DOMAINS:
            try:
                rsp = self.fetch(domain + "/api/home?lang=zh", headers=self.header, timeout=4)
                text = self._rsp_text(rsp)
                if text and len(text) > 100 and '"data"' in text:
                    self.host = domain
                    self.header["Referer"] = domain + "/"
                    return
            except Exception:
                continue

    # ===== 网络工具 =====
    def _rsp_text(self, rsp):
        try:
            return rsp.text
        except Exception:
            try:
                return rsp.content.decode('utf-8', 'ignore')
            except Exception:
                return ""

    def _txt(self, url, referer=None, timeout=12):
        """GET 文本，异常返回空"""
        headers = dict(self.header)
        if referer:
            headers["Referer"] = referer
        try:
            rsp = self.fetch(url, headers=headers, timeout=timeout)
            return self._rsp_text(rsp)
        except Exception:
            return ""

    def _match(self, pattern, text, flags=0):
        """正则取第一个分组"""
        m = re.search(pattern, text, flags)
        return m.group(1) if m else ""

    # ===== POST 请求（方法缓存 + 三重兜底）=====
    def _post_via_self(self, url, raw_str, headers, timeout):
        """用 FongMi Spider 内置 post（OkHttp 引擎）"""
        try:
            rsp = self.post(url, headers=headers, data=raw_str, timeout=timeout)
            t = self._rsp_text(rsp)
            return t if t and len(t) > 5 else ""
        except Exception:
            return ""

    def _post_via_requests(self, url, raw_bytes, headers, timeout):
        """用 requests 库（禁 SSL 验证）"""
        if requests is None:
            return ""
        try:
            try:
                import urllib3
                urllib3.disable_warnings()
            except Exception:
                pass
            r = requests.post(url, data=raw_bytes, headers=headers, timeout=timeout, verify=False)
            return r.text
        except Exception:
            return ""

    def _post_via_urllib(self, url, raw_bytes, headers, timeout):
        """用 urllib 标准库（禁 SSL 验证）"""
        try:
            import urllib.request
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, data=raw_bytes, headers=headers, method='POST')
            resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
            return resp.read().decode('utf-8', 'ignore')
        except Exception:
            return ""

    def _do_post(self, url, raw_bytes, headers, timeout=8):
        """
        执行 POST 请求，带方法缓存：
        第一次试三种方式找出能用的，之后直接用缓存的方式。
        """
        raw_str = raw_bytes.decode('utf-8', 'ignore')

        # 定义三种方法（按优先级排序）
        methods = [
            ("self.post", lambda: self._post_via_self(url, raw_str, headers, timeout)),
            ("requests",  lambda: self._post_via_requests(url, raw_bytes, headers, timeout)),
            ("urllib",    lambda: self._post_via_urllib(url, raw_bytes, headers, timeout)),
        ]

        # 有缓存 → 先用缓存的方法（快路径）
        if self._post_method:
            for name, fn in methods:
                if name == self._post_method:
                    text = fn()
                    if text and len(text) > 5:
                        return text
                    # 缓存的方法失效了，清掉重试全部
                    self._post_method = None
                    break

        # 无缓存或缓存失效 → 依次尝试
        for name, fn in methods:
            text = fn()
            if text and len(text) > 5:
                self._post_method = name  # 记住能用的方法
                return text

        return ""

    def _api_post(self, path, body, timeout=8):
        """POST 加密接口，返回解密后的 dict"""
        url = self.host + path
        enc = _encrypt_body(body)
        raw = json.dumps(enc).encode('utf-8')
        headers = dict(self.header)
        headers["Content-Type"] = "application/json"

        text = self._do_post(url, raw, headers, timeout)
        if not text:
            return None
        try:
            o = json.loads(text)
            return _decrypt_body(o)
        except Exception:
            return None

    def _api_post_safe(self, path, body, timeout=8):
        """
        POST 加密接口，当前域名失败时并发尝试其他域名。
        最多等 timeout+2 秒，用第一个成功的响应。
        """
        # 先用当前域名（快路径，有方法缓存时通常 2-4 秒）
        r = self._api_post(path, body, timeout)
        if r and r.get("code") == 1:
            return r

        # 当前域名失败 → 并发尝试其他域名
        result_box = [None]
        lock = threading.Lock()

        def _try_domain(domain):
            url = domain + path
            enc = _encrypt_body(body)
            raw = json.dumps(enc).encode('utf-8')
            headers = dict(self.header)
            headers["Content-Type"] = "application/json"
            text = self._do_post(url, raw, headers, timeout)
            if text:
                try:
                    o = json.loads(text)
                    rr = _decrypt_body(o)
                    if rr and rr.get("code") == 1:
                        with lock:
                            if result_box[0] is None:
                                result_box[0] = (domain, rr)
                except Exception:
                    pass

        backup_domains = [d for d in API_DOMAINS if d != self.host][:3]
        threads = []
        for domain in backup_domains:
            t = threading.Thread(target=_try_domain, args=(domain,))
            t.daemon = True
            t.start()
            threads.append(t)

        # 等第一个成功或全部超时
        deadline = time.time() + timeout + 2
        for t in threads:
            remaining = max(0.1, deadline - time.time())
            t.join(timeout=remaining)
            if result_box[0] is not None:
                break

        if result_box[0]:
            domain, rr = result_box[0]
            self.host = domain
            self.header["Referer"] = domain + "/"
            return rr

        return r

    def _api_get_home(self, timeout=6):
        """首页接口是 GET 不加密"""
        url = self.host + API_PATHS["home"] + "?lang=zh"
        try:
            text = self._txt(url, timeout=timeout)
            o = json.loads(text)
            return _decrypt_body(o)
        except Exception:
            return None

    # ===== 媒体判断 =====
    def _is_direct_media(self, url):
        url = (url or "").lower()
        return ".m3u8" in url or ".mp4" in url or ".flv" in url or ".mkv" in url

    def _is_official_source(self, url):
        """判断是否为官源（爱奇艺/优酷/腾讯等官方播放页）"""
        url = (url or "").lower()
        keys = (
            "mgtv.com", "youku.com", "iqiyi.com", "qiyi.com",
            "v.qq.com", "qq.com", "bilibili.com", "le.com",
            "sohu.com", "pptv.com", "1905.com",
        )
        return any(k in url for k in keys) and not self._is_direct_media(url)

    # ===== BFQ 官源解析（AES-CBC 解密）=====
    def _aes_cbc_decrypt_text(self, cipher_text):
        """BFQ 页面 result 变量 AES-CBC 解密"""
        try:
            from Crypto.Cipher import AES
            key = cipher_text[-32:-16].encode("utf-8")
            iv = cipher_text[-16:].encode("utf-8")
            data = base64.b64decode(cipher_text[:-32])
            raw = AES.new(key, AES.MODE_CBC, iv).decrypt(data)
            pad = raw[-1] if raw else 0
            if 0 < pad <= 16:
                raw = raw[:-pad]
            return raw.decode("utf-8", "ignore")
        except Exception:
            return ""

    def _decode_bfq_result(self, result):
        text = self._aes_cbc_decrypt_text(result or "")
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            return {}

    def _resolve_official_to_media(self, src_url):
        """用 bfq.txnp.cn 解析官源地址，返回真实 m3u8/mp4 直链"""
        if not src_url or not self._is_official_source(src_url):
            return ""
        try:
            page_url = "https://bfq.txnp.cn/player?url=" + quote(src_url, safe="")
            referer = "https://bfq.txnp.cn/excessive?url=" + quote(src_url, safe="")
            html = self._txt(page_url, referer=referer, timeout=12)
            result = self._match(r'let\s+result\s*=\s*"([^"]+)"', html, re.S)
            if not result:
                return ""
            data = self._decode_bfq_result(result)
            video = ((data.get("video_info") or {}).get("video") or {})
            media = (video.get("url") or "").replace("\\/", "/")
            if media and self._is_direct_media(media):
                return media
        except Exception:
            pass
        return ""

    # ===== 其他工具 =====
    def _pic(self, url):
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self.host + url
        return url

    def _strip_tags(self, s):
        return re.sub(r'<[^>]+>', '', s or '').strip()

    # ============================================================
    # 首页
    # ============================================================

    def homeContent(self, filter):
        return {
            "class": CLASSES,
            "filters": FILTERS,
        }

    def homeVideoContent(self):
        """首页推荐：从 /api/home 的 video_list 区块聚合，带 5 分钟缓存"""
        now = int(time.time())
        if self._home_cache and now - self._home_cache_time < 300:
            return {"list": self._home_cache[:72]}

        data = self._api_get_home()

        # 当前域名首页失败 → 并发尝试其他域名（快速）
        if not data:
            home_result = [None]
            home_lock = threading.Lock()

            def _try_home(domain):
                try:
                    url = domain + API_PATHS["home"] + "?lang=zh"
                    text = self._txt(url, timeout=5)
                    if text and len(text) > 100 and '"data"' in text:
                        o = json.loads(text)
                        d = _decrypt_body(o)
                        if d:
                            with home_lock:
                                if home_result[0] is None:
                                    home_result[0] = (domain, d)
                except Exception:
                    pass

            backup = [d for d in API_DOMAINS if d != self.host]
            threads = []
            for domain in backup:
                t = threading.Thread(target=_try_home, args=(domain,))
                t.daemon = True
                t.start()
                threads.append(t)

            deadline = time.time() + 6
            for t in threads:
                remaining = max(0.1, deadline - time.time())
                t.join(timeout=remaining)
                if home_result[0] is not None:
                    break

            if home_result[0]:
                domain, data = home_result[0]
                self.host = domain
                self.header["Referer"] = domain + "/"

        videos = []
        seen = set()
        if data and isinstance(data.get("data"), dict):
            sections = data["data"].get("sections", []) or []
            for sec in sections:
                if sec.get("type") != "video_list":
                    continue
                items = sec.get("data") or []
                if isinstance(items, list):
                    for v in items:
                        vid = v.get("id")
                        if vid and vid not in seen:
                            seen.add(vid)
                            videos.append(self._card(v))

        self._home_cache = videos[:72]
        self._home_cache_time = now
        return {"list": self._home_cache}

    def _card(self, v):
        return {
            "vod_id": str(v.get("id", "")),
            "vod_name": v.get("title", ""),
            "vod_pic": self._pic(v.get("coverUrl", "")),
            "vod_remarks": self._remarks(v),
        }

    def _remarks(self, v):
        ec = v.get("episodeCount", 0)
        if ec and ec > 1:
            return "更新至%s集" % ec
        ct = v.get("createdAt", "")
        if ct and len(ct) >= 4:
            return ct[:4]
        return "HD"

    # ============================================================
    # 分类列表
    # ============================================================

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg or 1)
            if pg < 1:
                pg = 1

            ext = {}
            if extend:
                if isinstance(extend, dict):
                    ext = extend
                elif isinstance(extend, str):
                    try:
                        ext = json.loads(extend)
                    except Exception:
                        ext = {}

            sub_type = ext.get("type", "")
            sort_by = ext.get("by", "hot-desc")

            query_type = sub_type if sub_type else tid

            if not sub_type and str(query_type) in DEFAULT_SUBTYPE:
                query_type = DEFAULT_SUBTYPE[str(query_type)]

            sort_field, sort_order = "hot", "desc"
            if "-" in sort_by:
                parts = sort_by.split("-", 1)
                sort_field, sort_order = parts[0], parts[1]

            result = self._api_category(int(query_type), pg, sort_field, sort_order)
            if result:
                return result

            return {"page": pg, "pagecount": 1, "limit": 20, "total": 0, "list": []}
        except Exception:
            return {"page": 1, "pagecount": 1, "limit": 20, "total": 0, "list": []}

    def _api_category(self, category_id, pg, sort_field="hot", sort_order="desc", page_size=20):
        body = {
            "categoryId": category_id,
            "sortBy": sort_field,
            "sortOrder": sort_order,
            "page": pg,
            "pageSize": page_size,
        }
        r = self._api_post_safe(API_PATHS["category_list"], body)
        if not r or r.get("code") != 1:
            return None
        d = r.get("data", {}) or {}
        raw_list = d.get("list", []) or []
        vods = [self._card(v) for v in raw_list]
        total = int(d.get("total", len(vods)))
        pagecount = int(total // page_size + (1 if total % page_size else 0)) if total else 1
        return {
            "list": vods,
            "page": pg,
            "pagecount": pagecount,
            "limit": page_size,
            "total": total,
        }

    # ============================================================
    # 详情页
    # ============================================================

    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        vod_id = ids[0]
        try:
            vid = int(vod_id)
        except Exception:
            vid = 0

        # 调用详情接口（带域名切换兜底）
        body = {"videoId": vid, "episodeNo": 1, "deviceId": self.device_id}
        r = self._api_post_safe(API_PATHS["video_detail"], body)
        if not r or r.get("code") != 1:
            return {"list": []}

        d = r.get("data", {}) or {}

        title = d.get("title", "")
        pic = self._pic(d.get("coverUrl", ""))
        desc = self._strip_tags(d.get("description", ""))
        year = d.get("year", "")
        area = d.get("area", "")

        # 集数列表
        episodes = d.get("episodes", []) or []
        ep_list = []
        for ep in episodes:
            ep_no = ep.get("episodeNo", 0)
            if not ep_no:
                continue
            ep_list.append("第%s集$%s_%s" % (ep_no, vid, ep_no))

        if not ep_list:
            cur = d.get("currentEpisode", {}) or {}
            ep_no = cur.get("episodeNo", 1)
            ep_list.append("第%s集$%s_%s" % (ep_no, vid, ep_no))

        vod = {
            "vod_id": str(vid),
            "vod_name": title,
            "vod_pic": pic,
            "type_name": "",
            "vod_year": year,
            "vod_area": area,
            "vod_remarks": "共%s集" % len(ep_list) if len(ep_list) > 1 else "HD",
            "vod_actor": "",
            "vod_director": "",
            "vod_content": desc[:500] if desc else "",
            "vod_play_from": "西瓜TV",
            "vod_play_url": "#".join(ep_list),
        }
        return {"list": [vod]}

    # ============================================================
    # 搜索
    # ============================================================

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1
            body = {"keyword": key, "page": page, "pageSize": 20}
            r = self._api_post_safe(API_PATHS["search"], body)
            if not r or r.get("code") != 1:
                return {"list": []}
            d = r.get("data", {}) or {}
            raw_list = d.get("list", []) or []
            vods = [self._card(v) for v in raw_list]
            return {"list": vods}
        except Exception:
            return {"list": []}

    # ============================================================
    # 播放解析
    # ============================================================

    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {"parse": 0, "playUrl": "", "url": ""}

        # id 格式: "{videoId}_{episodeNo}"
        play_url = ""
        try:
            if "_" in str(id):
                parts = str(id).rsplit("_", 1)
                vid = int(parts[0])
                ep_no = int(parts[1])
                # 调用切集接口获取真实 playUrl（带域名切换兜底）
                body = {"videoId": vid, "episodeNo": ep_no, "deviceId": self.device_id}
                r = self._api_post_safe(API_PATHS["switch_episode"], body)
                if r and r.get("code") == 1:
                    d = r.get("data", {}) or {}
                    cur = d.get("currentEpisode", {}) or {}
                    play_url = cur.get("playUrl", "") or ""
            else:
                play_url = str(id)
        except Exception:
            play_url = str(id)

        if not play_url:
            return {"parse": 0, "playUrl": "", "url": ""}

        play_url = play_url.replace("\\/", "/")

        # 1. 直链媒体（m3u8/mp4）→ 直接播放
        if self._is_direct_media(play_url):
            is_m3u8 = ".m3u8" in play_url.lower()
            return {
                "parse": 0,
                "playUrl": "",
                "url": play_url,
                "header": {
                    "User-Agent": UA,
                },
                "format": "application/x-mpegURL" if is_m3u8 else "",
                "contentType": "application/x-mpegURL" if is_m3u8 else "",
            }

        # 2. 官源（iqiyi/youku/qq 等）→ BFQ 解析出真实直链
        if self._is_official_source(play_url):
            resolved = self._resolve_official_to_media(play_url)
            if resolved and self._is_direct_media(resolved):
                is_m3u8 = ".m3u8" in resolved.lower()
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": resolved,
                    "header": {
                        "User-Agent": UA,
                        "Referer": "https://bfq.txnp.cn/",
                    },
                    "format": "application/x-mpegURL" if is_m3u8 else "",
                    "contentType": "application/x-mpegURL" if is_m3u8 else "",
                }

        # 3. 既不是直链也不是官源 → 返回原 URL 交给壳子处理
        return {
            "parse": 0,
            "playUrl": "",
            "url": play_url,
            "header": {
                "User-Agent": UA,
                "Referer": self.host + "/",
            },
        }

    # ===== 本地代理（可选）=====
    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]

    # ===== 清理 =====
    def destroy(self):
        pass

    def close(self):
        self.destroy()
