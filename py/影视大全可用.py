# -*- coding: utf-8 -*-
# QQ群807916734 @Easy
"""
iwakasoccer 影视 - iwakasoccer.com
基于歪比巴卜插件结构适配，适配 MacCMS (苹果CMS) 模板站点。

站点结构:
  首页:      /
  分类列表:  /ysdqsanls/{cat_id}.html
  筛选搜索:  /ysdqsansw/{cat_id}---{area}--------{page}---.html
  详情页:    /ysdqsandt/{vod_id}.html
  播放页:    /ysdqsanpy/{vod_id}-{source_id}-{episode_id}.html
  关键词搜索: /ysdqsanss/{keyword}----------{page}---.html

播放解析:
  1. 从播放页提取 player_aaaa 字典 (MacCMS 标准)
  2. 根据 encrypt 字段解密 URL (0=明文, 1=URL编码, 2=Base64)
  3. 已是直链(m3u8/mp4)则 parse=0 直接播放
  4. 非直链则 parse=1 走壳子 WebView 解析
"""
import re
import json
import hashlib
import base64
import time
import ssl
import urllib.parse
import requests
import warnings
from urllib.parse import quote
from base.spider import Spider

# ==================== SSL 兼容适配器 ====================
# iwakasoccer.com 的 TLS 配置在某些环境（FongMi/TVBox 内置 Python）下会触发
# SSLEOFError，需要自定义 SSL 上下文绕过。
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.ssl_ import create_urllib3_context

    class _SSLAdapter(HTTPAdapter):
        """自定义 SSL 适配器，兼容旧版 TLS 配置"""
        def init_poolmanager(self, *args, **kwargs):
            ctx = create_urllib3_context()
            ctx.set_ciphers('DEFAULT@SECLEVEL=1')
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kwargs['ssl_context'] = ctx
            return super().init_poolmanager(*args, **kwargs)

    _SSL_ADAPTER_OK = True
except Exception:
    _SSL_ADAPTER_OK = False

# 抑制 SSL 警告
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# ==================== 纯Python RC4（无第三方库兜底）====================
def _rc4_crypt(data, key):
    S = list(range(256))
    j = 0
    key = key if isinstance(key, bytes) else key.encode('utf-8')
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    i = j = 0
    out = bytearray()
    for ch in (data if isinstance(data, bytes) else data.encode('utf-8')):
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        out.append(ch ^ S[(S[i] + S[j]) % 256])
    return bytes(out)

# ==================== 纯 Python AES-128-CBC（无 Crypto 时兜底）====================
def _aes_bytes2matrix(data):
    return [list(data[i:i+4]) for i in range(0, 16, 4)]

def _aes_matrix2bytes(matrix):
    return bytes(sum(matrix, []))

def _aes_split_blocks(data, block_size=16):
    return [data[i:i+block_size] for i in range(0, len(data), block_size)]

def _aes_xor_bytes(a, b):
    return bytes(i ^ j for i, j in zip(a, b))

def _aes_unpad(data):
    pad = data[-1]
    if 1 <= pad <= 16:
        return data[:-pad]
    return data

_AES_SBOX = bytes([
    0x63,0x7C,0x77,0x7B,0xF2,0x6B,0x6F,0xC5,0x30,0x01,0x67,0x2B,0xFE,0xD7,0xAB,0x76,
    0xCA,0x82,0xC9,0x7D,0xFA,0x59,0x47,0xF0,0xAD,0xD4,0xA2,0xAF,0x9C,0xA4,0x72,0xC0,
    0xB7,0xFD,0x93,0x26,0x36,0x3F,0xF7,0xCC,0x34,0xA5,0xE5,0xF1,0x71,0xD8,0x31,0x15,
    0x04,0xC7,0x23,0xC3,0x18,0x96,0x05,0x9A,0x07,0x12,0x80,0xE2,0xEB,0x27,0xB2,0x75,
    0x09,0x83,0x2C,0x1A,0x1B,0x6E,0x5A,0xA0,0x52,0x3B,0xD6,0xB3,0x29,0xE3,0x2F,0x84,
    0x53,0xD1,0x00,0xED,0x20,0xFC,0xB1,0x5B,0x6A,0xCB,0xBE,0x39,0x4A,0x4C,0x58,0xCF,
    0xD0,0xEF,0xAA,0xFB,0x43,0x4D,0x33,0x85,0x45,0xF9,0x02,0x7F,0x50,0x3C,0x9F,0xA8,
    0x51,0xA3,0x40,0x8F,0x92,0x9D,0x38,0xF5,0xBC,0xB6,0xDA,0x21,0x10,0xFF,0xF3,0xD2,
    0xCD,0x0C,0x13,0xEC,0x5F,0x97,0x44,0x17,0xC4,0xA7,0x7E,0x3D,0x64,0x5D,0x19,0x73,
    0x60,0x81,0x4F,0xDC,0x22,0x2A,0x90,0x88,0x46,0xEE,0xB8,0x14,0xDE,0x5E,0x0B,0xDB,
    0xE0,0x32,0x3A,0x0A,0x49,0x06,0x24,0x5C,0xC2,0xD3,0xAC,0x62,0x91,0x95,0xE4,0x79,
    0xE7,0xC8,0x37,0x6D,0x8D,0xD5,0x4E,0xA9,0x6C,0x56,0xF4,0xEA,0x65,0x7A,0xAE,0x08,
    0xBA,0x78,0x25,0x2E,0x1C,0xA6,0xB4,0xC6,0xE8,0xDD,0x74,0x1F,0x4B,0xBD,0x8B,0x8A,
    0x70,0x3E,0xB5,0x66,0x48,0x03,0xF6,0x0E,0x61,0x35,0x57,0xB9,0x86,0xC1,0x1D,0x9E,
    0xE1,0xF8,0x98,0x11,0x69,0xD9,0x8E,0x94,0x9B,0x1E,0x87,0xE9,0xCE,0x55,0x28,0xDF,
    0x8C,0xA1,0x89,0x0D,0xBF,0xE6,0x42,0x68,0x41,0x99,0x2D,0x0F,0xB0,0x54,0xBB,0x16,
])

_AES_INV_SBOX = bytes([
    0x52,0x09,0x6A,0xD5,0x30,0x36,0xA5,0x38,0xBF,0x40,0xA3,0x9E,0x81,0xF3,0xD7,0xFB,
    0x7C,0xE3,0x39,0x82,0x9B,0x2F,0xFF,0x87,0x34,0x8E,0x43,0x44,0xC4,0xDE,0xE9,0xCB,
    0x54,0x7B,0x94,0x32,0xA6,0xC2,0x23,0x3D,0xEE,0x4C,0x95,0x0B,0x42,0xFA,0xC3,0x4E,
    0x08,0x2E,0xA1,0x66,0x28,0xD9,0x24,0xB2,0x76,0x5B,0xA2,0x49,0x6D,0x8B,0xD1,0x25,
    0x72,0xF8,0xF6,0x64,0x86,0x68,0x98,0x16,0xD4,0xA4,0x5C,0xCC,0x5D,0x65,0xB6,0x92,
    0x6C,0x70,0x48,0x50,0xFD,0xED,0xB9,0xDA,0x5E,0x15,0x46,0x57,0xA7,0x8D,0x9D,0x84,
    0x90,0xD8,0xAB,0x00,0x8C,0xBC,0xD3,0x0A,0xF7,0xE4,0x58,0x05,0xB8,0xB3,0x45,0x06,
    0xD0,0x2C,0x1E,0x8F,0xCA,0x3F,0x0F,0x02,0xC1,0xAF,0xBD,0x03,0x01,0x13,0x8A,0x6B,
    0x3A,0x91,0x11,0x41,0x4F,0x67,0xDC,0xEA,0x97,0xF2,0xCF,0xCE,0xF0,0xB4,0xE6,0x73,
    0x96,0xAC,0x74,0x22,0xE7,0xAD,0x35,0x85,0xE2,0xF9,0x37,0xE8,0x1C,0x75,0xDF,0x6E,
    0x47,0xF1,0x1A,0x71,0x1D,0x29,0xC5,0x89,0x6F,0xB7,0x62,0x0E,0xAA,0x18,0xBE,0x1B,
    0xFC,0x56,0x3E,0x4B,0xC6,0xD2,0x79,0x20,0x9A,0xDB,0xC0,0xFE,0x78,0xCD,0x5A,0xF4,
    0x1F,0xDD,0xA8,0x33,0x88,0x07,0xC7,0x31,0xB1,0x12,0x10,0x59,0x27,0x80,0xEC,0x5F,
    0x60,0x51,0x7F,0xA9,0x19,0xB5,0x4A,0x0D,0x2D,0xE5,0x7A,0x9F,0x93,0xC9,0x9C,0xEF,
    0xA0,0xE0,0x3B,0x4D,0xAE,0x2A,0xF5,0xB0,0xC8,0xEB,0xBB,0x3C,0x83,0x53,0x99,0x61,
    0x17,0x2B,0x04,0x7E,0xBA,0x77,0xD6,0x26,0xE1,0x69,0x14,0x63,0x55,0x21,0x0C,0x7D,
])

_AES_RCON = (0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1B,0x36)

def _aes_xtime(a):
    return (((a << 1) ^ 0x1B) & 0xFF) if (a & 0x80) else (a << 1)

def _aes_mix_single_column(a):
    t = a[0] ^ a[1] ^ a[2] ^ a[3]
    u = a[0]
    a[0] ^= t ^ _aes_xtime(a[0] ^ a[1])
    a[1] ^= t ^ _aes_xtime(a[1] ^ a[2])
    a[2] ^= t ^ _aes_xtime(a[2] ^ a[3])
    a[3] ^= t ^ _aes_xtime(a[3] ^ u)

def _aes_inv_mix_columns(s):
    for i in range(4):
        u = _aes_xtime(_aes_xtime(s[i][0] ^ s[i][2]))
        v = _aes_xtime(_aes_xtime(s[i][1] ^ s[i][3]))
        s[i][0] ^= u
        s[i][1] ^= v
        s[i][2] ^= u
        s[i][3] ^= v
    _aes_mix_single_column(s[0])
    _aes_mix_single_column(s[1])
    _aes_mix_single_column(s[2])
    _aes_mix_single_column(s[3])

class _PureAES:
    def __init__(self, master_key):
        self.n_rounds = 10
        self._key_matrices = self._expand_key(master_key)

    def _expand_key(self, master_key):
        key_columns = _aes_bytes2matrix(master_key)
        i = 1
        while len(key_columns) < 44:
            word = list(key_columns[-1])
            if len(key_columns) % 4 == 0:
                word.append(word.pop(0))
                word = [_AES_SBOX[b] for b in word]
                word[0] ^= _AES_RCON[i - 1]
                i += 1
            word = _aes_xor_bytes(word, key_columns[-4])
            key_columns.append(word)
        return [key_columns[4*i:4*(i+1)] for i in range(len(key_columns) // 4)]

    def _decrypt_block(self, ciphertext):
        assert len(ciphertext) == 16
        state = _aes_bytes2matrix(ciphertext)
        self._add_round_key(state, self._key_matrices[-1])
        self._inv_shift_rows(state)
        self._inv_sub_bytes(state)
        for i in range(self.n_rounds - 1, 0, -1):
            self._add_round_key(state, self._key_matrices[i])
            _aes_inv_mix_columns(state)
            self._inv_shift_rows(state)
            self._inv_sub_bytes(state)
        self._add_round_key(state, self._key_matrices[0])
        return _aes_matrix2bytes(state)

    def _add_round_key(self, s, k):
        for i in range(4):
            for j in range(4):
                s[i][j] ^= k[i][j]

    def _inv_shift_rows(self, s):
        s[0][1], s[1][1], s[2][1], s[3][1] = s[3][1], s[0][1], s[1][1], s[2][1]
        s[0][2], s[1][2], s[2][2], s[3][2] = s[2][2], s[3][2], s[0][2], s[1][2]
        s[0][3], s[1][3], s[2][3], s[3][3] = s[1][3], s[2][3], s[3][3], s[0][3]

    def _inv_sub_bytes(self, s):
        for i in range(4):
            for j in range(4):
                s[i][j] = _AES_INV_SBOX[s[i][j]]

    def decrypt_cbc(self, ciphertext, iv):
        ciphertext = base64.b64decode(ciphertext) if isinstance(ciphertext, str) else ciphertext
        iv = iv if isinstance(iv, bytes) else iv.encode('utf-8')
        blocks = []
        previous = iv
        for block in _aes_split_blocks(ciphertext):
            blocks.append(_aes_xor_bytes(previous, self._decrypt_block(block)))
            previous = block
        return _aes_unpad(b''.join(blocks))

# 尝试导入官方加密库
try:
    from Crypto.Cipher import ARC4, AES
    from Crypto.Util.Padding import unpad
    def _rc4_crypt(data, key):
        key = key if isinstance(key, bytes) else key.encode('utf-8')
        data = data if isinstance(data, bytes) else data.encode('utf-8')
        return ARC4.new(key).decrypt(data)
    def _aes_decrypt(data, key, iv):
        cipher = AES.new(key.encode('utf-8'), AES.MODE_CBC, iv.encode('utf-8'))
        return unpad(cipher.decrypt(base64.b64decode(data)), AES.block_size).decode('utf-8')
    CRYPTO_OK = True
except ImportError:
    CRYPTO_OK = False
    def _aes_decrypt(data, key, iv):
        return _PureAES(key.encode('utf-8')).decrypt_cbc(data, iv).decode('utf-8')


class Spider(Spider):
    # ==================== 基础配置 ====================
    name = "iwakasoccer"
    base_url = "https://www.iwakasoccer.com"
    site_url = "https://www.iwakasoccer.com"

    # 聚合搜索配置
    searchable = 1
    quickSearch = 1
    filterable = 1
    changeable = 1

    # ==================== 请求头 ====================
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.iwakasoccer.com/",
        "Connection": "keep-alive",
    }

    play_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.iwakasoccer.com/",
        "Accept": "*/*",
    }

    def __init__(self):
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        # 挂载 SSL 适配器，解决 iwakasoccer.com 的 TLS 兼容问题
        if _SSL_ADAPTER_OK:
            adapter = _SSLAdapter()
            self._session.mount('https://', adapter)
            self._session.mount('http://', adapter)
        self._verify = False  # 跳过 SSL 证书验证
        self._cookies = ""
        self._play_cache = {}
        self._cache_ttl = 1800
        self._last_req_time = 0
        self._min_req_interval = 0.45
        self._block_until = 0
        self._vplay_warmed = False
        # 预编译常用正则
        # h1 内含 <a><span> 等嵌套标签，需用 DOTALL + .*? 配合 _clean_html 提取纯文本
        self._re_detail_title = re.compile(r'<h1[^>]*>(.*?)</h1>', re.DOTALL)
        # 剧集链接：直接从 <a> 标签内提取文本，不要求 <span> 包裹
        self._re_play_link = re.compile(r'<a[^>]*href="/ysdqsanpy/(\d+)-(\d+)-(\d+)\.html"[^>]*>(.*?)</a>', re.DOTALL)
        # 清洗片名后缀
        self._re_name_garbage = re.compile(
            r'[\s\-_]*(?:HD|TC|TS|抢先版|枪版|DVD|BD|1080P|720P|4K|2K|高清|超清|蓝光|国语|粤语|中字|中英双字|完整版|全集|未删减版|(?:第[0-9一二三四五六七八九十]+[集季期]))\s*$',
            re.I
        )
        # 图片 URL 匹配属性（增加了 src 支持）
        self._img_attrs = r'(?:data-original|data-src|data-lazyload-src|data-lazy-src|data-href|src)'

    # ==================== 工具方法 ====================
    def _log(self, msg):
        print(f"[{self.name}] {msg}")

    def _md5(self, s):
        return hashlib.md5(s.encode('utf-8')).hexdigest()

    def _rc4_encrypt(self, data, key):
        key_b = key.encode('utf-8') if isinstance(key, str) else key
        data_b = data.encode('utf-8') if isinstance(data, str) else data
        return base64.b64encode(_rc4_crypt(data_b, key_b)).decode('utf-8')

    def _rc4_decrypt(self, data, key):
        key_b = key.encode('utf-8') if isinstance(key, str) else key
        data_b = base64.b64decode(data)
        return _rc4_crypt(data_b, key_b).decode('utf-8')

    def _aes_decrypt(self, data, key, iv):
        return _aes_decrypt(data, key, iv)

    def _clean_html(self, text):
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _clean_vod_name(self, name):
        """清洗片名，去掉清晰度/版本/集数后缀，方便壳子聚合搜索其它源"""
        if not name:
            return name
        prev = name
        while True:
            cleaned = self._re_name_garbage.sub('', prev).strip()
            if cleaned == prev:
                break
            prev = cleaned
        return prev

    def _normalize_pic_url(self, url):
        """补全图片 URL"""
        if not url:
            return ""
        url = url.strip()
        # 去掉可能的引号
        url = url.strip('"\'')
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self.base_url + url
        # 如果是相对路径
        if url.startswith("./"):
            return self.base_url + url[1:]
        if url.startswith("../"):
            # 简单处理：去掉 ../ 
            url = re.sub(r'^\.\./', '', url)
            return self.base_url + "/" + url
        return url

    # ==================== Cookie 维护 ====================
    def _extract_cookies(self, resp):
        """从响应中提取 Set-Cookie 并追加到 self._cookies"""
        cookie_list = []
        try:
            if hasattr(resp, 'cookies') and resp.cookies:
                for c in resp.cookies:
                    cookie_list.append(f"{c.name}={c.value}")
        except Exception:
            pass
        try:
            if hasattr(resp.headers, "get_all"):
                for c in resp.headers.get_all("Set-Cookie"):
                    cookie_list.append(c.split(";")[0])
            elif "Set-Cookie" in resp.headers:
                raw = resp.headers["Set-Cookie"]
                if isinstance(raw, list):
                    for c in raw:
                        cookie_list.append(c.split(";")[0])
                else:
                    cookie_list.append(raw.split(";")[0])
        except Exception:
            pass
        if cookie_list:
            existing = {k.strip(): v for k, v in [x.split('=', 1) for x in self._cookies.split('; ') if '=' in x]}
            for c in cookie_list:
                if '=' in c:
                    k, v = c.split('=', 1)
                    existing[k.strip()] = v
            self._cookies = "; ".join(f"{k}={v}" for k, v in existing.items())

    def _fetch_cookies(self):
        try:
            h = {"User-Agent": self.headers["User-Agent"], "Accept": "text/html", "Referer": self.base_url + "/"}
            resp = self.fetch(self.base_url, headers=h)
            self._extract_cookies(resp)
            if self._cookies:
                self._log(f"Cookie获取成功: {self._cookies[:80]}")
        except Exception as e:
            self._log(f"Cookie获取失败: {e}")
            self._cookies = ""

    def _is_blocked_page(self, html):
        """检测 Cloudflare/IP 频率限制等封禁页面"""
        if not html:
            return True
        markers = (
            'You are being rate limited',
            'Error 1015',
            'cf-error-details',
            'Access denied |',
            'Cloudflare',
            'Banned',
            '您的访问过于频繁',
        )
        return any(m in html for m in markers)

    def _is_verify_page(self, html):
        """检测搜索页是否需要验证码或触发频繁操作限制"""
        if not html:
            return False
        markers = ('系统安全验证', '需要输入验证码', 'mac_verify', '频繁操作', '搜索时间间隔')
        return any(m in html for m in markers)

    def fetch(self, url, headers=None, timeout=15):
        self._apply_req_delay()
        h = headers or {}
        # 优先使用 requests（支持 Cookie/Session）
        try:
            return self._session.get(url, headers=h, timeout=timeout, verify=self._verify)
        except Exception as e:
            # SSL 或连接失败时，尝试用父类 fetch（Java HTTP 栈，SSL 兼容性更好）
            self._log(f"requests 请求失败({type(e).__name__})，尝试父类 fetch: {url}")
            try:
                parent_fetch = super().fetch
                if parent_fetch:
                    return parent_fetch(url, h)
            except Exception as e2:
                self._log(f"父类 fetch 也失败: {e2}")
            # 最终兜底：urllib
            try:
                import urllib.request as _ur
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = _ur.Request(url, headers={k: v if isinstance(v, str) else str(v) for k, v in h.items()})
                resp_data = _ur.urlopen(req, timeout=timeout, context=ctx)
                class _U:
                    def __init__(self, d, r):
                        self._data = d
                        self._resp = r
                        self.text = d.decode('utf-8', errors='replace')
                        self.status_code = r.status
                        self.headers = r.headers
                        self.cookies = []
                return _U(resp_data.read(), resp_data)
            except Exception as e3:
                self._log(f"所有 HTTP 方法均失败: {e3}")
                raise e

    def post(self, url, data=None, headers=None, timeout=15):
        self._apply_req_delay()
        h = headers or {}
        try:
            return self._session.post(url, data=data, headers=h, timeout=timeout, verify=self._verify)
        except Exception:
            try:
                return super().post(url, data, h)
            except Exception:
                raise

    def _apply_req_delay(self):
        now = time.time()
        if now < self._block_until:
            wait = self._block_until - now
            self._log(f"频率限制冷却中，等待 {wait:.1f}s")
            time.sleep(wait)
        elapsed = now - self._last_req_time
        interval = self._min_req_interval
        if 0 < elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_req_time = time.time()

    def _get(self, url, max_retry=3, timeout=10):
        """GET请求封装（依赖 Session 自动维护 Cookie，含异常捕获+重试+频率限制）"""
        h = self.headers.copy()
        html = ""
        try:
            for attempt in range(max_retry):
                resp = self.fetch(url, headers=h, timeout=timeout)
                self._extract_cookies(resp)
                html = resp.text
                if self._is_blocked_page(html):
                    wait = 2 + attempt * 2
                    self._block_until = time.time() + wait
                    self._log(f"请求被频率限制，进入 {wait}s 冷却: {url}")
                    if attempt < max_retry - 1:
                        time.sleep(wait)
                        continue
                    return ""
                return html
            return html
        except Exception as e:
            self._log(f"请求失败: {url}, {e}")
            if not self._cookies:
                self._log("尝试重新获取Cookie...")
                self._fetch_cookies()
                try:
                    return self.fetch(url, headers=h, timeout=timeout).text
                except Exception as e2:
                    self._log(f"重试失败: {e2}")
            return ""

    # ==================== 分类映射 ====================
    class_name = ["电影", "电视剧", "综艺", "动漫", "短剧", "排行榜", "今日更新"]
    class_url = ["1", "2", "3", "4", "5", "rank", "today"]
    CATEGORY_NAMES = {
        "1": "电影", "2": "电视剧", "3": "综艺", "4": "动漫",
        "5": "短剧", "rank": "排行榜", "today": "今日更新"
    }

    # ==================== 筛选器配置 ====================
    FILTERS = {
        "1": [
            {"key": "area", "name": "地区", "value": [
                {"n": "全部", "v": ""},
                {"n": "大陆", "v": "大陆"},
                {"n": "港台", "v": "港台"},
                {"n": "美国", "v": "美国"},
                {"n": "韩国", "v": "韩国"},
                {"n": "日本", "v": "日本"},
                {"n": "泰国", "v": "泰国"},
                {"n": "印度", "v": "印度"},
                {"n": "法国", "v": "法国"},
                {"n": "英国", "v": "英国"},
            ]},
            {"key": "class", "name": "剧情", "value": [
                {"n": "全部", "v": ""},
                {"n": "喜剧", "v": "喜剧"},
                {"n": "爱情", "v": "爱情"},
                {"n": "恐怖", "v": "恐怖"},
                {"n": "动作", "v": "动作"},
                {"n": "科幻", "v": "科幻"},
                {"n": "剧情", "v": "剧情"},
                {"n": "战争", "v": "战争"},
                {"n": "警匪", "v": "警匪"},
                {"n": "犯罪", "v": "犯罪"},
                {"n": "动画", "v": "动画"},
                {"n": "奇幻", "v": "奇幻"},
                {"n": "武侠", "v": "武侠"},
                {"n": "冒险", "v": "冒险"},
            ]},
            {"key": "lang", "name": "语言", "value": [
                {"n": "全部", "v": ""},
                {"n": "国语", "v": "国语"},
                {"n": "粤语", "v": "粤语"},
                {"n": "韩语", "v": "韩语"},
                {"n": "日语", "v": "日语"},
                {"n": "英语", "v": "英语"},
                {"n": "泰语", "v": "泰语"},
            ]},
            {"key": "year", "name": "年份", "value": [
                {"n": "全部", "v": ""},
                {"n": "2026", "v": "2026"},
                {"n": "2025", "v": "2025"},
                {"n": "2024", "v": "2024"},
                {"n": "2023", "v": "2023"},
                {"n": "2022", "v": "2022"},
                {"n": "2021", "v": "2021"},
                {"n": "2020", "v": "2020"},
                {"n": "2019", "v": "2019"},
                {"n": "2018", "v": "2018"},
                {"n": "2017", "v": "2017"},
                {"n": "2016", "v": "2016"},
                {"n": "2015", "v": "2015"},
                {"n": "2014", "v": "2014"},
                {"n": "2013", "v": "2013"},
                {"n": "2012", "v": "2012"},
            ]},
            {"key": "letter", "name": "字母", "value": [
                {"n": "全部", "v": ""},
                {"n": "A", "v": "A"}, {"n": "B", "v": "B"}, {"n": "C", "v": "C"},
                {"n": "D", "v": "D"}, {"n": "E", "v": "E"}, {"n": "F", "v": "F"},
                {"n": "G", "v": "G"}, {"n": "H", "v": "H"}, {"n": "I", "v": "I"},
                {"n": "J", "v": "J"}, {"n": "K", "v": "K"}, {"n": "L", "v": "L"},
                {"n": "M", "v": "M"}, {"n": "N", "v": "N"}, {"n": "O", "v": "O"},
                {"n": "P", "v": "P"}, {"n": "Q", "v": "Q"}, {"n": "R", "v": "R"},
                {"n": "S", "v": "S"}, {"n": "T", "v": "T"}, {"n": "U", "v": "U"},
                {"n": "V", "v": "V"}, {"n": "W", "v": "W"}, {"n": "X", "v": "X"},
                {"n": "Y", "v": "Y"}, {"n": "Z", "v": "Z"},
            ]},
        ],
        "2": [
            {"key": "area", "name": "地区", "value": [
                {"n": "全部", "v": ""},
                {"n": "大陆", "v": "大陆"},
                {"n": "港台", "v": "港台"},
                {"n": "美国", "v": "美国"},
                {"n": "韩国", "v": "韩国"},
                {"n": "日本", "v": "日本"},
                {"n": "泰国", "v": "泰国"},
            ]},
            {"key": "class", "name": "剧情", "value": [
                {"n": "全部", "v": ""},
                {"n": "古装", "v": "古装"},
                {"n": "爱情", "v": "爱情"},
                {"n": "悬疑", "v": "悬疑"},
                {"n": "都市", "v": "都市"},
                {"n": "家庭", "v": "家庭"},
                {"n": "剧情", "v": "剧情"},
                {"n": "历史", "v": "历史"},
                {"n": "战争", "v": "战争"},
                {"n": "犯罪", "v": "犯罪"},
                {"n": "武侠", "v": "武侠"},
            ]},
            {"key": "year", "name": "年份", "value": [
                {"n": "全部", "v": ""},
                {"n": "2026", "v": "2026"},
                {"n": "2025", "v": "2025"},
                {"n": "2024", "v": "2024"},
                {"n": "2023", "v": "2023"},
                {"n": "2022", "v": "2022"},
                {"n": "2021", "v": "2021"},
                {"n": "2020", "v": "2020"},
                {"n": "2019", "v": "2019"},
                {"n": "2018", "v": "2018"},
            ]},
        ],
        "3": [
            {"key": "area", "name": "地区", "value": [
                {"n": "全部", "v": ""},
                {"n": "大陆", "v": "大陆"},
                {"n": "港台", "v": "港台"},
                {"n": "韩国", "v": "韩国"},
                {"n": "日本", "v": "日本"},
                {"n": "美国", "v": "美国"},
            ]},
            {"key": "year", "name": "年份", "value": [
                {"n": "全部", "v": ""},
                {"n": "2026", "v": "2026"},
                {"n": "2025", "v": "2025"},
                {"n": "2024", "v": "2024"},
                {"n": "2023", "v": "2023"},
                {"n": "2022", "v": "2022"},
                {"n": "2021", "v": "2021"},
                {"n": "2020", "v": "2020"},
            ]},
        ],
        "4": [
            {"key": "area", "name": "地区", "value": [
                {"n": "全部", "v": ""},
                {"n": "大陆", "v": "大陆"},
                {"n": "日本", "v": "日本"},
                {"n": "韩国", "v": "韩国"},
                {"n": "美国", "v": "美国"},
            ]},
            {"key": "class", "name": "剧情", "value": [
                {"n": "全部", "v": ""},
                {"n": "热血", "v": "热血"},
                {"n": "冒险", "v": "冒险"},
                {"n": "科幻", "v": "科幻"},
                {"n": "搞笑", "v": "搞笑"},
                {"n": "奇幻", "v": "奇幻"},
                {"n": "恋爱", "v": "恋爱"},
                {"n": "战斗", "v": "战斗"},
                {"n": "日常", "v": "日常"},
            ]},
            {"key": "year", "name": "年份", "value": [
                {"n": "全部", "v": ""},
                {"n": "2026", "v": "2026"},
                {"n": "2025", "v": "2025"},
                {"n": "2024", "v": "2024"},
                {"n": "2023", "v": "2023"},
                {"n": "2022", "v": "2022"},
                {"n": "2021", "v": "2021"},
            ]},
        ],
        "5": [
            {"key": "class", "name": "类型", "value": [
                {"n": "全部", "v": ""},
                {"n": "女频恋爱", "v": "女频恋爱"},
                {"n": "反转爽", "v": "反转爽"},
                {"n": "脑洞悬疑", "v": "脑洞悬疑"},
                {"n": "年代穿越", "v": "年代穿越"},
                {"n": "古装仙侠", "v": "古装仙侠"},
                {"n": "现代都市", "v": "现代都市"},
            ]},
            {"key": "area", "name": "地区", "value": [
                {"n": "全部", "v": ""},
                {"n": "大陆", "v": "大陆"},
            ]},
            {"key": "year", "name": "年份", "value": [
                {"n": "全部", "v": ""},
                {"n": "2026", "v": "2026"},
                {"n": "2025", "v": "2025"},
                {"n": "2024", "v": "2024"},
            ]},
        ],
    }

    # ==================== 解析方法 ====================
    def _dedup_videos(self, videos):
        """按 vod_id 和 vod_name 双重去重，保留首次出现"""
        if not videos:
            return videos
        seen_ids = set()
        seen_names = set()
        result = []
        for v in videos:
            vid = v.get("vod_id", "")
            vname = v.get("vod_name", "").strip()
            if vid and vid in seen_ids:
                continue
            if vname and vname in seen_names:
                continue
            if vid:
                seen_ids.add(vid)
            if vname:
                seen_names.add(vname)
            result.append(v)
        return result

    def _parse_video_list(self, html):
        """通用列表解析（首页/分类页）- 适配本站 tcl-img/tc_img/tc_wz 结构"""
        videos = []
        if not html:
            return videos

        # 主匹配：本站专属结构
        # <a href="/ysdqsandt/ID.html" class="tcl-img" title="片名">
        #   <div class="tc_img img_wrapper lazyload" data-original="封面URL">
        #     <p class="tc_wz">备注</p>
        #   </div>
        # </a>
        pattern_site = (
            r'<a[^>]*href="/ysdqsandt/(\d+)\.html"[^>]*class="[^"]*tcl-img[^"]*"[^>]*title="([^"]+)"[^>]*>'
            r'.*?<div[^>]*class="[^"]*tc_img[^"]*"[^>]*data-original="([^"]+)"'
            r'.*?<p[^>]*class="[^"]*tc_wz[^"]*"[^>]*>([^<]*)</p>'
        )
        for m in re.finditer(pattern_site, html, re.DOTALL):
            vod_id   = m.group(1)
            vod_name = self._clean_vod_name(m.group(2).strip())
            vod_pic  = self._normalize_pic_url(m.group(3).strip())
            vod_note = m.group(4).strip()
            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": vod_note,
            })

        if videos:
            return self._dedup_videos(videos)

        # 兜底匹配0.5：本站另一种结构（无 tcl-img class，但有 img_wrapper + data-original）
        # <a href="/ysdqsandt/ID.html" title="片名">
        #   <div class="img_wrapper lazyload" data-original="封面URL"></div>
        #   <p class="name">片名</p>
        # </a>
        pattern_site2 = (
            r'<a[^>]*href="/ysdqsandt/(\d+)\.html"[^>]*title="([^"]+)"[^>]*>'
            r'\s*<div[^>]*class="[^"]*img_wrapper[^"]*lazyload[^"]*"[^>]*data-original="([^"]+)"'
        )
        for m in re.finditer(pattern_site2, html, re.DOTALL):
            vod_id   = m.group(1)
            vod_name = self._clean_vod_name(m.group(2).strip())
            vod_pic  = self._normalize_pic_url(m.group(3).strip())
            # 在该块附近找备注
            block_end = min(m.end() + 500, len(html))
            block = html[m.start():block_end]
            note_m = re.search(r'<p[^>]*class="[^"]*tc_wz[^"]*"[^>]*>([^<]*)</p>', block)
            vod_note = note_m.group(1).strip() if note_m else ""
            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": vod_note,
            })

        if videos:
            return videos

        # 通用匹配：从任意标签（img 或 div）提取 data-original 封面
        # 主匹配：module-poster-item 结构
        pattern = (
            r'<a[^>]*href="/ysdqsandt/(\d+\.html)"[^>]*class="[^"]*module-poster-item[^"]*"[^>]*>'
            r'.*?<div[^>]*class="[^"]*module-item-note[^"]*"[^>]*>([^<]*)</div>'
            r'.*?<(?:img|div)[^>]*' + self._img_attrs + r'="([^"]+)"[^>]*>'
            r'.*?<div[^>]*class="[^"]*module-poster-item-title[^"]*"[^>]*>([^<]*)</div>'
        )
        for m in re.finditer(pattern, html, re.DOTALL):
            vod_id   = m.group(1).replace(".html", "")
            vod_note = m.group(2).strip()
            vod_pic  = self._normalize_pic_url(m.group(3).strip())
            vod_name = self._clean_vod_name(m.group(4).strip())
            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": vod_note,
            })

        if videos:
            return self._dedup_videos(videos)

        # 兜底匹配1：通用 module-item 结构（宽松 class 匹配，兼容 img/div 封面）
        pattern2 = (
            r'<a[^>]*href="/ysdqsandt/(\d+\.html)"[^>]*>'
            r'.*?<(?:img|div)[^>]*' + self._img_attrs + r'="([^"]+)"[^>]*>'
            r'.*?<div[^>]*class="[^"]*module-item-note[^"]*"[^>]*>([^<]*)</div>'
            r'.*?<div[^>]*class="[^"]*(?:title|name)[^"]*"[^>]*>([^<]*)</div>'
        )
        for m in re.finditer(pattern2, html, re.DOTALL):
            vod_id   = m.group(1).replace(".html", "")
            vod_pic  = self._normalize_pic_url(m.group(2).strip())
            vod_note = m.group(3).strip()
            vod_name = self._clean_vod_name(m.group(4).strip())
            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": vod_note,
            })

        if videos:
            return self._dedup_videos(videos)

        # 兜底匹配1.5：先找链接块，再在块内找图片和标题（不限 class）
        for m in re.finditer(r'<a[^>]*href="/ysdqsandt/(\d+)\.html"[^>]*>', html):
            vod_id = m.group(1)
            block_start = m.start()
            block_end = min(block_start + 2000, len(html))
            block = html[block_start:block_end]
            # 提取图片（兼容 <div data-original> 和 <img src>）
            img_m = re.search(r'<(?:img|div)[^>]*' + self._img_attrs + r'="([^"]+)"', block)
            vod_pic = self._normalize_pic_url(img_m.group(1).strip()) if img_m else ""
            # 提取备注
            note_m = re.search(r'<div[^>]*class="[^"]*note[^"]*"[^>]*>([^<]*)</div>', block)
            vod_note = note_m.group(1).strip() if note_m else ""
            # 提取标题
            title_m = re.search(r'<(?:div|span|a)[^>]*class="[^"]*(?:title|name)[^"]*"[^>]*>([^<]*)</(?:div|span|a)>', block)
            if not title_m:
                title_m = re.search(r'href="/ysdqsandt/' + vod_id + r'\.html"[^>]*>([^<]+)</a>', block)
            vod_name = self._clean_vod_name(title_m.group(1).strip()) if title_m else ""
            if vod_name and vod_id:
                videos.append({
                    "vod_id": vod_id,
                    "vod_name": vod_name,
                    "vod_pic": vod_pic,
                    "vod_remarks": vod_note,
                })

        if videos:
            # 去重
            seen = set()
            unique = []
            for v in videos:
                if v["vod_id"] not in seen:
                    seen.add(v["vod_id"])
                    unique.append(v)
            return self._dedup_videos(unique)

        # 兜底匹配2：无 class 的简单链接+标题结构
        pattern3 = (
            r'<a[^>]*href="/ysdqsandt/(\d+)\.html"[^>]*>'
            r'.*?<(?:img|div)[^>]*' + self._img_attrs + r'="([^"]+)"[^>]*>'
            r'.*?<a[^>]*href="/ysdqsandt/\1\.html"[^>]*>([^<]*)</a>'
        )
        for m in re.finditer(pattern3, html, re.DOTALL):
            vod_id   = m.group(1)
            vod_pic  = self._normalize_pic_url(m.group(2).strip())
            vod_name = self._clean_vod_name(m.group(3).strip())
            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": "",
            })

        # 兜底匹配3：最简单的通用链接提取
        if not videos:
            seen = set()
            for m in re.finditer(r'<a[^>]*href="/ysdqsandt/(\d+)\.html"[^>]*>([^<]+)</a>', html):
                vod_id = m.group(1)
                if vod_id in seen:
                    continue
                seen.add(vod_id)
                vod_name = self._clean_vod_name(m.group(2).strip())
                if not vod_name:
                    continue
                # 尝试在该链接附近找图片（兼容 div data-original 和 img src）
                nearby = html[max(0, m.start()-300):m.end()+300]
                img_m = re.search(r'<(?:img|div)[^>]*' + self._img_attrs + r'="([^"]+)"', nearby)
                vod_pic = self._normalize_pic_url(img_m.group(1).strip()) if img_m else ""
                videos.append({
                    "vod_id": vod_id,
                    "vod_name": vod_name,
                    "vod_pic": vod_pic,
                    "vod_remarks": "",
                })

        return self._dedup_videos(videos)

    def _parse_search_list(self, html):
        """搜索页专用解析（优先本站 tcl-img 结构，兜底 module-card-item）"""
        videos = []
        if not html:
            return videos

        # 主匹配：本站结构（与列表页一致）
        pattern_site = (
            r'<a[^>]*href="/ysdqsandt/(\d+)\.html"[^>]*class="[^"]*tcl-img[^"]*"[^>]*title="([^"]+)"[^>]*>'
            r'.*?<div[^>]*class="[^"]*tc_img[^"]*"[^>]*data-original="([^"]+)"'
            r'.*?<p[^>]*class="[^"]*tc_wz[^"]*"[^>]*>([^<]*)</p>'
        )
        for m in re.finditer(pattern_site, html, re.DOTALL):
            vod_id   = m.group(1)
            vod_name = self._clean_vod_name(m.group(2).strip())
            vod_pic  = self._normalize_pic_url(m.group(3).strip())
            vod_note = m.group(4).strip()
            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": vod_note,
            })

        if videos:
            return self._dedup_videos(videos)

        # 兜底：module-card-item 结构（标准 MacCMS）
        for m in re.finditer(r'<div[^>]*class="(?:[^"]*\s)?module-card-item(?:\s[^"]*)?"[^>]*>', html):
            start = m.start()
            depth = 0
            i = start
            while i < len(html):
                if html[i:i+5] == '<div ':
                    depth += 1
                    i += 5
                elif html[i:i+6] == '</div>':
                    depth -= 1
                    i += 6
                    if depth == 0:
                        break
                else:
                    i += 1
            block = html[start:i]

            link = re.search(r'<a[^>]*href="/ysdqsandt/(\d+)\.html"[^>]*class="[^"]*module-card-item-poster[^"]*"', block)
            if not link:
                link = re.search(r'<a[^>]*href="/ysdqsandt/(\d+)\.html"', block)
            if not link:
                continue
            vod_id = link.group(1)

            title = re.search(r'<div[^>]*class="[^"]*module-card-item-title[^"]*"[^>]*>.*?<strong>([^<]*)</strong>', block, re.DOTALL)
            if not title:
                title = re.search(r'<a[^>]*href="/ysdqsandt/\d+\.html"[^>]*>([^<]*)</a>', block)
            vod_name = self._clean_vod_name(title.group(1).strip()) if title else "未知"

            pic = re.search(r'<(?:img|div)[^>]*(?:data-original|data-src|data-lazy-src|src)="([^"]+)"', block)
            vod_pic = self._normalize_pic_url(pic.group(1)) if pic else ""

            note = re.search(r'<div[^>]*class="[^"]*module-item-note[^"]*"[^>]*>([^<]*)</div>', block)
            vod_remarks = note.group(1).strip() if note else ""

            video = {
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": vod_remarks,
            }
            # 搜索页聚合匹配时，年份/地区/类型有助于壳子提高相似度准确率
            info_text = re.sub(r'<[^>]+>', ' ', block)
            year = re.search(r'年份[:：\s]+(\d{4})', info_text)
            if year:
                video["vod_year"] = year.group(1)
            area = re.search(r'地区[:：\s]+([^\s]+)', info_text)
            if area:
                video["vod_area"] = area.group(1).strip()
            ctype = re.search(r'类型[:：\s]+([^\s]+)', info_text)
            if ctype:
                video["vod_type"] = ctype.group(1).strip()

            videos.append(video)

        # 兜底：如果 module-card-item 结构无结果，用通用列表解析
        if not videos:
            videos = self._parse_video_list(html)

        return self._dedup_videos(videos)

    def _parse_rank_list(self, html):
        """从首页提取人气排行榜数据"""
        videos = []
        if not html:
            return videos
        seen = set()

        # 方式0: 本站 tcl-img 结构（优先）
        pattern_site = (
            r'<a[^>]*href="/ysdqsandt/(\d+)\.html"[^>]*class="[^"]*tcl-img[^"]*"[^>]*title="([^"]+)"[^>]*>'
            r'.*?<div[^>]*class="[^"]*tc_img[^"]*"[^>]*data-original="([^"]+)"'
            r'.*?<p[^>]*class="[^"]*tc_wz[^"]*"[^>]*>([^<]*)</p>'
        )
        for m in re.finditer(pattern_site, html, re.DOTALL):
            vod_id = m.group(1)
            if vod_id in seen:
                continue
            seen.add(vod_id)
            videos.append({
                "vod_id": vod_id,
                "vod_name": self._clean_vod_name(m.group(2).strip()),
                "vod_pic": self._normalize_pic_url(m.group(3).strip()),
                "vod_remarks": m.group(4).strip() or "排行",
            })

        if videos:
            return self._dedup_videos(videos)

        # 方式1: 匹配排行项
        for m in re.finditer(r'\*?\d+\*?\d*℃?\s*\[([^\]]+)\]\(https?://www\.iwakasoccer\.com/ysdqsandt/(\d+)\.html\)', html):
            vod_name = m.group(1).strip()
            vod_id = m.group(2)
            if vod_id in seen:
                continue
            seen.add(vod_id)
            # 尝试找图片（兼容 div data-original）
            nearby = html[max(0, m.start()-300):m.end()+300]
            img_m = re.search(r'<(?:img|div)[^>]*' + self._img_attrs + r'="([^"]+)"', nearby)
            vod_pic = self._normalize_pic_url(img_m.group(1)) if img_m else ""
            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": "排行榜",
            })

        # 方式2: 从 HTML 提取排行榜区域内的链接
        if not videos:
            rank_block = re.search(r'(排行|人气|热门).*?</div>\s*(<div[^>]*class="[^"]*module[^"]*"[^>]*>.*?</div>\s*</div>)', html, re.DOTALL)
            if rank_block:
                block = rank_block.group(2)
            else:
                block = html

            for m in re.finditer(r'<a[^>]*href="/ysdqsandt/(\d+)\.html"[^>]*>([^<]+)</a>', block):
                vod_id = m.group(1)
                vod_name = m.group(2).strip()
                if vod_id in seen or not vod_name or len(vod_name) > 50:
                    continue
                seen.add(vod_id)
                nearby = html[max(0, m.start()-500):m.end()+500]
                pic_m = re.search(r'<(?:img|div)[^>]*' + self._img_attrs + r'="([^"]+)"', nearby)
                vod_pic = self._normalize_pic_url(pic_m.group(1)) if pic_m else ""
                videos.append({
                    "vod_id": vod_id,
                    "vod_name": vod_name,
                    "vod_pic": vod_pic,
                    "vod_remarks": "排行",
                })

        return self._dedup_videos(videos)

    def _parse_today_list(self, html):
        """从首页提取今日更新/推荐内容"""
        videos = []
        if not html:
            return videos
        seen = set()

        # 方式0: 本站 tcl-img 结构（优先）
        pattern_site = (
            r'<a[^>]*href="/ysdqsandt/(\d+)\.html"[^>]*class="[^"]*tcl-img[^"]*"[^>]*title="([^"]+)"[^>]*>'
            r'.*?<div[^>]*class="[^"]*tc_img[^"]*"[^>]*data-original="([^"]+)"'
            r'.*?<p[^>]*class="[^"]*tc_wz[^"]*"[^>]*>([^<]*)</p>'
        )
        for m in re.finditer(pattern_site, html, re.DOTALL):
            vod_id = m.group(1)
            if vod_id in seen:
                continue
            seen.add(vod_id)
            videos.append({
                "vod_id": vod_id,
                "vod_name": self._clean_vod_name(m.group(2).strip()),
                "vod_pic": self._normalize_pic_url(m.group(3).strip()),
                "vod_remarks": m.group(4).strip() or "今日",
            })

        if videos:
            return self._dedup_videos(videos)

        # 方式1: 通用链接 + 附近图片
        for m in re.finditer(r'<a[^>]*href="/ysdqsandt/(\d+)\.html"[^>]*>([^<]+)</a>', html):
            vod_id = m.group(1)
            vod_name = m.group(2).strip()
            if vod_id in seen or not vod_name or len(vod_name) > 50:
                continue
            seen.add(vod_id)
            nearby = html[max(0, m.start()-500):m.end()+500]
            pic_m = re.search(r'<(?:img|div)[^>]*' + self._img_attrs + r'="([^"]+)"', nearby)
            vod_pic = self._normalize_pic_url(pic_m.group(1)) if pic_m else ""
            note_m = re.search(r'<p[^>]*class="[^"]*tc_wz[^"]*"[^>]*>([^<]*)</p>', nearby)
            if not note_m:
                note_m = re.search(r'<div[^>]*class="[^"]*note[^"]*"[^>]*>([^<]*)</div>', nearby)
            vod_note = note_m.group(1).strip() if note_m else "今日"
            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": vod_note,
            })
        return self._dedup_videos(videos)

    def _parse_play_sources(self, html, vod_id):
        """解析播放线路与集数"""
        sources = []
        if not html:
            return sources

        # 1. 提取线路名称
        _BAD_NAMES = ("排序", "更多", "切换", "展开", "收起", "选择播放源", "播放源", "线路")
        source_names = []
        for m in re.finditer(r'<div[^>]*class="[^"]*tab-item[^"]*"[^>]*data-dropdown-value="([^"]+)"', html):
            name = m.group(1).strip()
            if name and name not in source_names and name not in _BAD_NAMES:
                source_names.append(name)
        if not source_names:
            for m in re.finditer(r'<div[^>]*class="[^"]*tab-item[^"]*"[^>]*>.*?<span[^>]*>([^<]*)</span>', html, re.DOTALL):
                name = m.group(1).strip()
                if name and name not in source_names and name not in _BAD_NAMES:
                    source_names.append(name)
        if not source_names:
            for m in re.finditer(r'<span[^>]*class="[^"]*module-tab-value[^"]*"[^>]*>([^<]*)</span>', html):
                name = m.group(1).strip()
                if name and name not in source_names and name not in _BAD_NAMES:
                    source_names.append(name)
        if not source_names:
            for m in re.finditer(r'<(?:div|span|a)[^>]*>([^<]*(?:在线|线路|播放源|源\d))[^<]*</(?:div|span|a)>', html):
                name = m.group(1).strip()
                if name and name not in source_names and name not in _BAD_NAMES:
                    source_names.append(name)

        # 2. 提取播放列表块
        list_blocks = []
        for pattern in [
            r'<div[^>]*class="[^"]*module-list[^"]*tab-list[^"]*"[^>]*>',
            r'<div[^>]*class="[^"]*module-play-list[^"]*"[^>]*>',
            r'<div[^>]*class="[^"]*(?:play-list|episode-list|video-list)[^"]*"[^>]*>',
            r'<div[^>]*class="[^"]*tab-list[^"]*"[^>]*>',
        ]:
            for m in re.finditer(pattern, html):
                start = m.start()
                depth = 0
                i = start
                while i < len(html):
                    if html[i:i+5] == '<div ':
                        depth += 1
                        i += 5
                    elif html[i:i+6] == '</div>':
                        depth -= 1
                        i += 6
                        if depth == 0:
                            break
                    else:
                        i += 1
                block = html[start:i]
                if '/ysdqsanpy/' in block:
                    list_blocks.append(block)
            if list_blocks:
                break

        # 3. 对齐名称与块数量
        if len(source_names) > len(list_blocks):
            source_names = source_names[:len(list_blocks)]
        while len(source_names) < len(list_blocks):
            source_names.append(f"线路{len(source_names)+1}")

        # 4. 解析每个块的集数
        for idx, block in enumerate(list_blocks):
            eps = []
            for m in self._re_play_link.finditer(block):
                id_, sid, nid, raw_name = m.groups()
                name = self._clean_html(raw_name).strip()
                if not name:
                    name = f"第{nid}集"
                eps.append({"name": name, "link": f"{id_}-{sid}-{nid}"})
            if eps:
                sources.append({
                    "source_name": source_names[idx] if idx < len(source_names) else f"线路{idx+1}",
                    "episodes": eps
                })

        # 5. 兜底：按 sid 分组
        if not sources:
            all_eps = []
            for m in self._re_play_link.finditer(html):
                id_, sid, nid, raw_name = m.groups()
                name = self._clean_html(raw_name).strip()
                if not name:
                    name = f"第{nid}集"
                if '温馨提示' in name or '提示' in name or '注意' in name:
                    continue
                all_eps.append({"name": name, "link": f"{id_}-{sid}-{nid}", "sid": sid})

            sid_groups = {}
            for ep in all_eps:
                sid = ep["sid"]
                if sid not in sid_groups:
                    sid_groups[sid] = []
                sid_groups[sid].append({"name": ep["name"], "link": ep["link"]})

            for sid in sorted(sid_groups.keys(), key=lambda x: int(x) if x.isdigit() else 999):
                eps = sid_groups[sid]
                seen_links = set()
                unique_eps = []
                for ep in eps:
                    if ep["link"] not in seen_links:
                        seen_links.add(ep["link"])
                        unique_eps.append(ep)
                if unique_eps:
                    name_idx = int(sid) - 1 if sid.isdigit() and int(sid) <= len(source_names) else None
                    sname = source_names[name_idx] if name_idx is not None and name_idx >= 0 else f"线路{sid}"
                    sources.append({"source_name": sname, "episodes": unique_eps})

        # 6. 最终兜底
        if not sources:
            eps = []
            for m in self._re_play_link.finditer(html):
                id_, sid, nid, raw_name = m.groups()
                name = self._clean_html(raw_name).strip()
                if '温馨提示' in name or '提示' in name or '注意' in name:
                    continue
                if not name:
                    name = f"第{nid}集"
                link = f"{id_}-{sid}-{nid}"
                if link not in [e["link"] for e in eps]:
                    eps.append({"name": name, "link": link})
            if eps:
                sources.append({"source_name": "默认", "episodes": eps})

        # 7. 4K/蓝光线路置顶
        if sources:
            def _rank(i):
                name = sources[i]["source_name"]
                is_4k = any(k in name for k in ("4K", "4k", "2160", "2160P", "2160p"))
                is_bluray = "蓝光" in name
                cnt = len(sources[i]["episodes"])
                no_eps = 1 if cnt == 0 else 0
                order = 0 if is_4k else (1 if is_bluray else 2)
                return (no_eps, order, i)
            sources = [sources[i] for i in sorted(range(len(sources)), key=_rank)]

        return sources

    # ==================== 播放地址解析 ====================
    def _extract_player_aaaa(self, html):
        """从播放页 HTML 中提取 player_aaaa 字典"""
        if not html:
            return None
        m = re.search(r'var\s+player_aaaa\s*=\s*(\{.*?\})\s*(?:</script>|;)', html, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception as e:
                self._log(f"player_aaaa JSON解析失败: {e}")
        # 兜底：手动花括号匹配
        m = re.search(r'var\s+player_aaaa\s*=\s*\{', html)
        if m:
            start = m.end() - 1
            depth = 1
            i = start + 1
            while i < len(html) and depth > 0:
                if html[i] == '{':
                    depth += 1
                elif html[i] == '}':
                    depth -= 1
                i += 1
            if depth == 0:
                try:
                    return json.loads(html[start:i])
                except Exception as e:
                    self._log(f"player_aaaa花括号解析失败: {e}")
        return None

    def _get_play_url(self, vod_id, sid, nid):
        play_page = f"{self.base_url}/ysdqsanpy/{vod_id}-{sid}-{nid}.html"
        cache_key = f"{vod_id}-{sid}-{nid}"
        now = time.time()
        if cache_key in self._play_cache:
            url, ts = self._play_cache[cache_key]
            if now - ts < self._cache_ttl:
                self._log(f"播放地址缓存命中: {cache_key}")
                return url

        try:
            html = self._get(play_page, max_retry=3, timeout=8)
            if not html:
                self._log(f"播放页无响应, 使用 WebView 兜底: {play_page}")
                return play_page

            player_data = self._extract_player_aaaa(html)
            if not player_data:
                self._log("未能提取到player_aaaa, 使用 WebView 兜底")
                return play_page

            enc_url = player_data.get("url", "")
            encrypt = str(player_data.get("encrypt", "0"))
            self._log(f"player_aaaa encrypt={encrypt}, url={enc_url[:50]}...")

            if encrypt == "1":
                try:
                    enc_url = urllib.parse.unquote(enc_url)
                except Exception:
                    pass
            elif encrypt == "2":
                try:
                    enc_url = urllib.parse.unquote(base64.b64decode(enc_url).decode('utf-8'))
                except Exception:
                    pass

            if not enc_url:
                return play_page

            if re.search(r'\.(m3u8|mp4|flv|ts|mkv)(\?|#|$)', enc_url, re.I):
                self._log(f"player_aaaa已是直链: {enc_url[:80]}")
                self._play_cache[cache_key] = (enc_url, now)
                return enc_url

            parse_api = player_data.get("api", "") or player_data.get("server", "")
            if parse_api and enc_url:
                try:
                    api_url = f"{parse_api}?url={urllib.parse.quote(enc_url)}"
                    api_headers = {
                        "User-Agent": self.play_headers["User-Agent"],
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "Referer": self.base_url + "/",
                        "X-Requested-With": "XMLHttpRequest",
                    }
                    resp = self.fetch(api_url, headers=api_headers, timeout=8)
                    try:
                        result = json.loads(resp.text)
                        if str(result.get("code")) == "200" or str(result.get("code")) == "1":
                            durl = result.get("url", "")
                            if durl and re.search(r'\.(m3u8|mp4|flv|ts|mkv)(\?|#|$)', durl, re.I):
                                self._log(f"API解析直链成功: {durl[:80]}")
                                self._play_cache[cache_key] = (durl, now)
                                return durl
                    except Exception:
                        pass
                except Exception as e:
                    self._log(f"API解析异常: {e}")

            self._log(f"非直链, 使用 WebView 兜底: {play_page}")
            self._play_cache[cache_key] = (play_page, now)
            return play_page

        except Exception as e:
            self._log(f"获取播放地址异常: {e}")
            return play_page

    # ==================== TVBox五大核心方法 ====================
    def init(self, extend=''):
        self._fetch_cookies()
        self._log("初始化完成")

    def homeContent(self, filter=False):
        result = {
            "class": [
                {"type_id": self.class_url[i], "type_name": self.class_name[i]}
                for i in range(len(self.class_url))
            ]
        }
        if filter:
            result["filters"] = self.FILTERS
            result["filter"] = self.FILTERS
        return result

    def homeVideoContent(self):
        try:
            html = self._get(self.base_url)
            if not html:
                html = self._get(f"{self.base_url}/ysdqsanls/1.html")
            if not html:
                return {"list": []}
            block = re.search(r'<div class="module">.*?<h2[^>]*class="[^"]*module-title[^"]*"[^>]*>.*?</div>(.*?)</div>\s*<div class="module">', html, re.DOTALL)
            if not block:
                block = re.search(r'<div class="module">(.*?)</div>\s*<div class="module">', html, re.DOTALL)
            if not block:
                videos = self._parse_video_list(html)
                if videos:
                    return {"list": videos[:20]}
                return {"list": []}
            videos = self._parse_video_list(block.group(1))
            if not videos:
                videos = self._parse_video_list(html)
            return {"list": videos[:20]}
        except Exception as e:
            self._log(f"homeVideoContent异常: {e}")
            return {"list": []}

    def _quote_filter_value(self, v):
        if not v:
            return ""
        try:
            return quote(urllib.parse.unquote(str(v)))
        except Exception:
            return quote(str(v))

    def _build_show_url(self, tid, pg, flt):
        area = self._quote_filter_value(flt.get("area", ""))
        class_ = self._quote_filter_value(flt.get("class", ""))
        lang = self._quote_filter_value(flt.get("lang", ""))
        letter = self._quote_filter_value(flt.get("letter", ""))
        year = self._quote_filter_value(flt.get("year", ""))
        # URL 格式: /ysdqsansw/{tid}-{area}--{class}-{lang}-{letter}--{sort}-{page}---{year}.html
        # 实测本站页码在第 8 段（tid 后第 8 个分隔），尾页链接如:
        # /ysdqsansw/1--------5337---.html
        parts = [
            str(tid), area, "", class_, lang, letter, "", "",
            str(pg) if pg > 1 else "", "", "", year
        ]
        return f"{self.base_url}/ysdqsansw/{'-'.join(parts)}.html"

    def categoryContent(self, tid, pg, filter=False, content=None):
        try:
            pg = int(pg)
            tid_str = str(tid)
            if tid_str not in self.CATEGORY_NAMES:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}

            flt = {}
            if content:
                try:
                    flt = json.loads(content) if isinstance(content, str) else content
                except Exception:
                    flt = {}

            if tid_str == "rank":
                url = self.base_url
                self._log(f"排行榜请求: {url}")
                html = self._get(url)
                if not html:
                    return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
                videos = self._parse_rank_list(html)
                return {
                    "list": videos[:30],
                    "page": 1,
                    "pagecount": 1,
                    "limit": 30,
                    "total": len(videos)
                }

            if tid_str == "today":
                url = self.base_url
                self._log(f"今日更新请求: {url}")
                html = self._get(url)
                if not html:
                    return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
                videos = self._parse_today_list(html)
                return {
                    "list": videos[:30],
                    "page": 1,
                    "pagecount": 1,
                    "limit": 30,
                    "total": len(videos)
                }

            url = self._build_show_url(tid_str, pg, flt)
            self._log(f"分类请求: {url}")
            html = self._get(url)
            if not html:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}
            videos = self._parse_video_list(html)

            # 检测总页数：本站尾页链接格式 /ysdqsansw/1--------5337---.html
            last = re.search(r'<a[^>]*href="/ysdqsansw/\d+(?:-[^"]*?)-?(\d+)---\.html"[^>]*>尾页</a>', html)
            if not last:
                last = re.search(r'<a[^>]*href="[^"]*(?:ysdqsansw)/\d+[^"]*?(\d+)---\.html"[^>]*>(?:尾页|末页)', html, re.I)
            if not last:
                last = re.search(r'<a[^>]*href="/ysdqsanls/\d+-(\d+)\.html"[^>]*>尾页</a>', html)
            if not last:
                last = re.search(r'<a[^>]*href="[^"]*(?:ysdqsansw|ysdqsanls)/\d+[^"]*(\d+)[^"]*\.html"[^>]*>(?:尾页|末页|最后)', html, re.I)
            pagecount = int(last.group(1)) if last else 1
            return {
                "list": videos,
                "page": pg,
                "pagecount": pagecount,
                "limit": 20,
                "total": pagecount * 20
            }
        except Exception as e:
            self._log(f"categoryContent异常: {e}")
            return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            pg = max(1, int(pg or 1))
        except (TypeError, ValueError):
            pg = 1
        keyword = str(key or "").strip()
        if not keyword:
            return {"page": pg, "pagecount": 1, "limit": 0, "total": 0, "list": []}
        is_quick = bool(quick)
        encoded_key = quote(keyword)
        url = f"{self.base_url}/ysdqsanss/{encoded_key}----------{pg}---.html"
        self._log(f"搜索请求: {url}, quick={is_quick}")

        try:
            html = ""
            for attempt in range(3):
                html = self._get(url)
                if self._is_verify_page(html):
                    self._log(f"搜索页触发安全验证，重试中 (第{attempt+1}次)...")
                    time.sleep(2)
                    html = self._get(url)
                if html and not self._is_verify_page(html):
                    break
                time.sleep(1)

            if not html or self._is_verify_page(html):
                return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}

            videos = self._parse_search_list(html)
            if not videos:
                videos = self._parse_video_list(html)

            last = re.search(r'<a[^>]*href="/ysdqsanss/[^"]*----------(\d+)---\.html"[^>]*>尾页</a>', html)
            pagecount = int(last.group(1)) if last else 1

            if not is_quick:
                key_lower = keyword.lower()
                def _sort_score(v):
                    name = v.get('vod_name', '').lower()
                    if name == key_lower:
                        return 0
                    if name.startswith(key_lower):
                        return 1
                    if key_lower in name:
                        return 2
                    return 3
                videos = sorted(videos, key=_sort_score)

            return {
                "list": videos,
                "page": pg,
                "pagecount": pagecount if pagecount > 0 else 1,
                "limit": 20,
                "total": pagecount * 20 if pagecount > 0 else len(videos)
            }
        except Exception as e:
            self._log(f"搜索Content异常: {e}")
            return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}

    def detailContent(self, ids):
        try:
            vod_id = ids[0] if isinstance(ids, list) else str(ids)
            url = f"{self.base_url}/ysdqsandt/{vod_id}.html"
            self._log(f"详情请求: {url}")
            html = self._get(url)
            if not html:
                return {"list": []}

            title = self._re_detail_title.search(html)
            if title:
                vod_name = self._clean_vod_name(self._clean_html(title.group(1)).strip())
                if not vod_name:
                    # h1 内 <a title="片名"> 兜底
                    a_title = re.search(r'<h1[^>]*>.*?<a[^>]*title="([^"]+)"', html, re.DOTALL)
                    vod_name = self._clean_vod_name(a_title.group(1).strip()) if a_title else "未知"
            else:
                # 无 h1 时从 <a class="tcl-img" title="片名"> 兜底
                a_title = re.search(r'<a[^>]*class="[^"]*tcl-img[^"]*"[^>]*title="([^"]+)"', html)
                vod_name = self._clean_vod_name(a_title.group(1).strip()) if a_title else "未知"

            # 封面图：多种属性和位置尝试（增强版）
            vod_pic = ""
            for pattern in [
                # 本站专属：详情页左侧封面 <div class="leftimg"><div class="img_wrapper lazyload" data-original="...">
                r'<div[^>]*class="[^"]*leftimg[^"]*"[^>]*>.*?data-original="([^"]+)"',
                # 本站专属：通用 img_wrapper lazyload + data-original（<div> 标签，非 <img>）
                r'<div[^>]*class="[^"]*img_wrapper[^"]*lazyload[^"]*"[^>]*data-original="([^"]+)"',
                r'<div[^>]*class="[^"]*lazyload[^"]*"[^>]*data-original="([^"]+)"',
                # 通用 div + data-original（优先匹配图片 URL）
                r'<div[^>]*data-original="([^"]+\.(?:jpg|jpeg|png|webp))"',
                # 标准 MacCMS 兼容
                r'<div[^>]*class="[^"]*module-item-pic[^"]*"[^>]*>.*?<img[^>]*data-original="([^"]+)"',
                r'<div[^>]*class="[^"]*module-item-pic[^"]*"[^>]*>.*?<img[^>]*data-src="([^"]+)"',
                r'<div[^>]*class="[^"]*module-item-pic[^"]*"[^>]*>.*?<img[^>]*src="([^"]+)"',
                r'<div[^>]*class="[^"]*(?:item-pic|poster|cover)[^"]*"[^>]*>.*?<(?:img|div)[^>]*(?:data-original|data-src|src)="([^"]+)"',
                r'<img[^>]*class="[^"]*(?:cover|poster|lazy)[^"]*"[^>]*(?:data-original|data-src)="([^"]+)"',
                r'<img[^>]*(?:data-original|data-src)="([^"]+)"[^>]*class="[^"]*(?:cover|poster|lazy)[^"]*"',
                r'<img[^>]*class="[^"]*lazy[^"]*"[^>]*src="([^"]+)"',
                r'<img[^>]*class="[^"]*cover[^"]*"[^>]*src="([^"]+)"',
                r'<img[^>]*class="[^"]*poster[^"]*"[^>]*src="([^"]+)"',
                r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"',
                r'<link[^>]*rel="image_src"[^>]*href="([^"]+)"',
                r'<img[^>]*src="(https?://[^"]+\.(?:jpg|jpeg|png|webp))"[^>]*width="\d+"[^>]*height="\d+"',
                # 通用：找任意图片 URL（优先大图）
                r'<img[^>]*(?:data-original|data-src)="(https?://[^"]+(?:\.(?:jpg|jpeg|png|webp)))"',
                r'<img[^>]*src="(https?://[^"]+\.(?:jpg|jpeg|png|webp))"',
            ]:
                pic = re.search(pattern, html, re.DOTALL)
                if pic:
                    vod_pic = pic.group(1)
                    if vod_pic and not vod_pic.startswith('data:'):  # 排除 base64 图
                        break
                    vod_pic = ""
            
            # 如果还没有，从页面任意图片中选一张（排除小图标和 base64）
            if not vod_pic:
                all_imgs = re.findall(r'<img[^>]*src="([^"]+\.(?:jpg|jpeg|png|webp))"', html, re.I)
                for img in all_imgs:
                    if 'logo' not in img.lower() and 'icon' not in img.lower() and not img.startswith('data:'):
                        vod_pic = img
                        break

            vod_pic = self._normalize_pic_url(vod_pic)

            # 简介
            desc = re.search(r'<div[^>]*class="[^"]*(?:introduction|content|desc|summary)[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
            vod_content = self._clean_html(desc.group(1)) if desc else ""

            # 演员
            vod_actor = ""
            for pat in [
                r'主演：</span>.*?<div[^>]*class="[^"]*module-info-item-content[^"]*"[^>]*>(.*?)</div>',
                r'主演[：:]\s*</span>.*?<[^>]*>(.*?)</',
                r'<span[^>]*>主演[：:]?</span>.*?<[^>]*[^>]*>(.*?)</',
                r'主演[：:]\s*(.*?)(?:<|假设|$)',
            ]:
                m = re.search(pat, html, re.DOTALL)
                if m:
                    vod_actor = self._clean_html(m.group(1)).strip()
                    if vod_actor and '主演' not in vod_actor:
                        break
                    vod_actor = ""

            # 导演
            vod_director = ""
            for pat in [
                r'导演：</span>.*?<div[^>]*class="[^"]*module-info-item-content[^"]*"[^>]*>(.*?)</div>',
                r'导演[：:]\s*</span>.*?<[^>]*>(.*?)</',
                r'<span[^>]*>导演[：:]?</span>.*?<[^>]*[^>]*>(.*?)</',
                r'导演[：:]\s*(.*?)(?:<|$)',
            ]:
                m = re.search(pat, html, re.DOTALL)
                if m:
                    vod_director = self._clean_html(m.group(1)).strip()
                    if vod_director and '导演' not in vod_director:
                        break
                    vod_director = ""

            # 年份
            vod_year = ""
            for pat in [
                r'<a[^>]*title="(\d{4})"',
                r'年份[：:]\s*(\d{4})',
                r'(\d{4})年',
                r'>.*?年份.*?(\d{4})',
            ]:
                m = re.search(pat, html, re.DOTALL)
                if m:
                    vod_year = m.group(1)
                    break

            # 地区
            vod_area = ""
            for pat in [
                r'地区[：:]\s*(.*?)(?:<|$)',
                r'>.*?地区.*?>([^<]+)',
            ]:
                m = re.search(pat, html, re.DOTALL)
                if m:
                    vod_area = self._clean_html(m.group(1)).strip()
                    if vod_area:
                        break

            # 类型
            vod_type = ""
            for pat in [
                r'类型[：:]\s*(.*?)(?:<|$)',
                r'>.*?类型.*?>([^<]+)',
            ]:
                m = re.search(pat, html, re.DOTALL)
                if m:
                    vod_type = self._clean_html(m.group(1)).strip()
                    if vod_type:
                        break

            # 状态/备注
            vod_remarks = ""
            for pat in [
                r'<span[^>]*class="[^"]*module-info-item-title[^"]*">集数：</span>.*?<div[^>]*class="[^"]*module-info-item-content[^"]*"[^>]*>(.*?)</div>',
                r'<span[^>]*class="[^"]*module-info-item-title[^"]*">更新：</span>.*?<p[^>]*class="[^"]*module-info-item-content[^"]*"[^>]*>(.*?)</p>',
                r'<span[^>]*class="[^"]*module-info-item-title[^"]*">状态：</span>.*?<div[^>]*class="[^"]*module-info-item-content[^"]*"[^>]*>(.*?)</div>',
                r'状态[：:]\s*(.*?)(?:<|$)',
                r'更新[：:]\s*(.*?)(?:<|$)',
            ]:
                m = re.search(pat, html, re.DOTALL)
                if m:
                    vod_remarks = self._clean_html(m.group(1)).strip()
                    if vod_remarks:
                        break

            sources = self._parse_play_sources(html, vod_id)
            if not sources:
                self._log("未能解析到播放源")
                return {"list": []}

            from_list = []
            url_list = []
            for src in sources:
                from_list.append(src["source_name"])
                eps_str = "#".join([f"{ep['name']}${ep['link']}" for ep in src["episodes"]])
                url_list.append(eps_str)

            vod_play_from = "$$$".join(from_list)
            vod_play_url = "$$$".join(url_list)

            video = {
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_year": vod_year,
                "vod_area": vod_area,
                "vod_type": vod_type,
                "vod_actor": vod_actor,
                "vod_director": vod_director,
                "vod_content": vod_content,
                "vod_remarks": vod_remarks,
                "vod_play_from": vod_play_from,
                "vod_play_url": vod_play_url,
            }
            self._log(f"详情解析成功: {vod_name}, 封面: {vod_pic[:80] if vod_pic else '无'}")
            return {"list": [video]}
        except Exception as e:
            self._log(f"detailContent异常: {e}")
            return {"list": []}

    def playerContent(self, flag, id, vipFlags=None):
        try:
            parts = str(id).split("-")
            if len(parts) != 3:
                return {"parse": 0, "url": "", "header": ""}
            vod_id, sid, nid = parts
            play_page = f"{self.base_url}/ysdqsanpy/{vod_id}-{sid}-{nid}.html"
            play_url = self._get_play_url(vod_id, sid, nid)

            if not play_url:
                play_url = play_page

            is_direct = bool(re.search(r'\.(m3u8|mp4|flv|ts|mkv)([?#&]|$)', play_url, re.I))
            is_parse_page = play_url.startswith(play_page)
            parse_flag = 0 if (is_direct or not is_parse_page) else 1
            self._log(f"播放URL: {play_url[:80]}..., parse={parse_flag}")

            if parse_flag == 0:
                return {"parse": 0, "url": play_url, "header": self.play_headers.copy()}
            else:
                return {"parse": 1, "url": play_url, "header": ""}
        except Exception as e:
            self._log(f"playerContent异常: {e}")
            return {"parse": 0, "url": "", "header": ""}

    def getName(self):
        return self.name

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        pass