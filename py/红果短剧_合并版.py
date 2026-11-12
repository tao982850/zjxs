# -*- coding: utf-8 -*-
from __future__ import annotations
import base64
import binascii
import bisect
import hashlib
import json
import os
import random
import re
import struct
import tempfile
import concurrent.futures
import threading
import time
from collections.abc import Mapping
try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
except Exception:
    # 少数裁剪过的 Python 运行时没有 http.server：本机流服务退化为不可用，
    # 播放走上游直链兜底，首页与详情不受影响。
    class BaseHTTPRequestHandler:
        pass

    class ThreadingHTTPServer:
        def __init__(self, *args, **kwargs):
            raise OSError("http.server unavailable")
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse
try:
    import requests
except Exception:
    # 部分定制 TVBox/NewBox 的 Python 运行时没有预装 requests，顶层 import 直接抛
    # ModuleNotFoundError 会让整份插件加载失败，宿主表现为「没找到数据」。
    # 这里用标准库实现插件实际用到的 requests 子集，保持调用点不变。
    import socket
    import types
    import urllib.error
    import urllib.request

    class _ShimRequestException(Exception):
        pass

    class _ShimConnectionError(_ShimRequestException):
        pass

    class _ShimTimeout(_ShimRequestException):
        pass

    class _ShimHTTPError(_ShimRequestException):
        def __init__(self, message, response=None):
            Exception.__init__(self, message)
            self.response = response

    class _ShimResponse:
        def __init__(self, raw, status, headers, url):
            self._raw = raw
            self.status_code = int(status)
            self.headers = headers
            self.url = url
            self.encoding = None
            self._content = None

        @property
        def content(self):
            if self._content is None:
                raw = self._raw
                try:
                    body = raw.read() if raw is not None else b""
                finally:
                    self.close()
                enc = str(self.headers.get("Content-Encoding") or "").lower()
                if "gzip" in enc and body:
                    import gzip
                    try:
                        body = gzip.decompress(body)
                    except Exception:
                        pass
                elif "deflate" in enc and body:
                    import zlib
                    try:
                        body = zlib.decompress(body)
                    except Exception:
                        try:
                            body = zlib.decompress(body, -zlib.MAX_WBITS)
                        except Exception:
                            pass
                self._content = body
            return self._content

        @property
        def text(self):
            body = self.content
            enc = self.encoding
            if not enc:
                ctype = str(self.headers.get("Content-Type") or "")
                m = re.search(r"charset=([\w\-]+)", ctype, re.I)
                enc = m.group(1) if m else "utf-8"
            try:
                return body.decode(enc, "replace")
            except LookupError:
                return body.decode("utf-8", "replace")

        def json(self):
            return json.loads(self.text)

        def iter_content(self, chunk_size=8192, decode_unicode=False):
            size = int(chunk_size or 8192)
            if self._content is not None:
                body = self._content
                for i in range(0, len(body), size):
                    yield body[i:i + size]
                return
            while True:
                block = self._raw.read(size) if self._raw is not None else b""
                if not block:
                    break
                yield block

        def raise_for_status(self):
            if self.status_code >= 400:
                raise _ShimHTTPError("HTTP %s" % self.status_code, self)

        def close(self):
            raw = self._raw
            self._raw = None
            if raw is not None:
                try:
                    raw.close()
                except Exception:
                    pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def _shim_query(params):
        if not params:
            return ""
        if isinstance(params, str):
            return params
        if isinstance(params, bytes):
            return params.decode("utf-8", "replace")
        pairs = []
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, (list, tuple)):
                for x in v:
                    pairs.append((str(k), str(x)))
            else:
                pairs.append((str(k), str(v)))
        return urlencode(pairs)

    def _shim_open(method, url, params=None, data=None, json_body=None,
                   headers=None, timeout=30, **kwargs):
        query = _shim_query(params)
        if query:
            url = url + ("&" if "?" in url else "?") + query
        body = data
        hdrs = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False)
            hdrs.setdefault("Content-Type", "application/json")
        if isinstance(body, str):
            body = body.encode("utf-8")
        # 自己解压比让上游压缩更稳：urllib 不会自动还原 gzip。
        hdrs.setdefault("Accept-Encoding", "identity")
        req = urllib.request.Request(url, data=body, headers=hdrs,
                                     method=str(method).upper())
        try:
            raw = urllib.request.urlopen(req, timeout=timeout)
            status = int(getattr(raw, "status", 200) or 200)
        except urllib.error.HTTPError as err:
            raw = err
            status = int(err.code)
        except urllib.error.URLError as err:
            reason = getattr(err, "reason", err)
            if isinstance(reason, socket.timeout):
                raise _ShimTimeout(str(err))
            raise _ShimConnectionError(str(err))
        except socket.timeout as err:
            raise _ShimTimeout(str(err))
        except Exception as err:
            raise _ShimConnectionError(str(err))
        return _ShimResponse(raw, status, raw.headers, url)

    class _ShimSession:
        def __init__(self):
            self.headers = {}
            self.cookies = {}
            self.trust_env = True

        def request(self, method, url, **kwargs):
            hdrs = dict(self.headers)
            extra = kwargs.pop("headers", None)
            if extra:
                hdrs.update(extra)
            return _shim_open(method, url, headers=hdrs, **kwargs)

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

        def head(self, url, **kwargs):
            return self.request("HEAD", url, **kwargs)

        def post(self, url, **kwargs):
            return self.request("POST", url, **kwargs)

        def close(self):
            pass

    def _shim_get(url, **kwargs):
        if "json" in kwargs:
            kwargs["json_body"] = kwargs.pop("json")
        return _shim_open("GET", url, **kwargs)

    def _shim_head(url, **kwargs):
        return _shim_open("HEAD", url, **kwargs)

    def _shim_post(url, **kwargs):
        if "json" in kwargs:
            kwargs["json_body"] = kwargs.pop("json")
        return _shim_open("POST", url, **kwargs)

    _shim_requests = types.ModuleType("requests")
    _shim_requests.get = _shim_get
    _shim_requests.head = _shim_head
    _shim_requests.post = _shim_post
    _shim_requests.Session = _ShimSession
    _shim_requests.Response = _ShimResponse
    _shim_requests.RequestException = _ShimRequestException
    _shim_requests.ConnectionError = _ShimConnectionError
    _shim_requests.Timeout = _ShimTimeout
    _shim_requests.HTTPError = _ShimHTTPError
    requests = _shim_requests
try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    hashes = None
    Cipher = algorithms = modes = None
try:
    from Crypto.Cipher import AES as CryptoAES
except ImportError:
    CryptoAES = None
try:
    from base.spider import Spider as _BaseSpider
except Exception:
    try:
        import sys as _sys
        _sys.path.append("..")
        from base.spider import Spider as _BaseSpider
    except Exception:
        class _BaseSpider:
            pass

# FongMi/TVBox 的 Chaquopy 环境未必带 cryptography，多数壳只带 pycryptodome。
# 统一入口，避免调用点直接依赖某一个库。
if Cipher is not None:
    AES_BACKEND = "cryptography"
elif CryptoAES is not None:
    AES_BACKEND = "pycryptodome"
else:
    AES_BACKEND = "none"

class _PureAES128:
    """纯 Python AES-128，供无 pycryptodome/cryptography 的壳使用。"""

    _S = (
        99,124,119,123,242,107,111,197,48,1,103,43,254,215,171,118,202,130,201,125,250,89,71,240,
        173,212,162,175,156,164,114,192,183,253,147,38,54,63,247,204,52,165,229,241,113,216,49,21,
        4,199,35,195,24,150,5,154,7,18,128,226,235,39,178,117,9,131,44,26,27,110,90,160,82,59,214,
        179,41,227,47,132,83,209,0,237,32,252,177,91,106,203,190,57,74,76,88,207,208,239,170,251,67,
        77,51,133,69,249,2,127,80,60,159,168,81,163,64,143,146,157,56,245,188,182,218,33,16,255,243,
        210,205,12,19,236,95,151,68,23,196,167,126,61,100,93,25,115,96,129,79,220,34,42,144,136,70,
        238,184,20,222,94,11,219,224,50,58,10,73,6,36,92,194,211,172,98,145,149,228,121,231,200,55,
        109,141,213,78,169,108,86,244,234,101,122,174,8,186,120,37,46,28,166,180,198,232,221,116,31,
        75,189,139,138,112,62,181,102,72,3,246,14,97,53,87,185,134,193,29,158,225,248,152,17,105,
        217,142,148,155,30,135,233,206,85,40,223,140,161,137,13,191,230,66,104,65,153,45,15,176,84,
        187,22
    )
    _RCON = (0x00,0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1B,0x36)

    def __init__(self, key: bytes):
        if len(key) != 16:
            raise ValueError("AES-128 only")
        self._rk = self._expand(key)

    def _expand(self, key: bytes):
        s = self._S
        w = list(key)
        for i in range(4, 44):
            t0, t1, t2, t3 = w[-4], w[-3], w[-2], w[-1]
            if i % 4 == 0:
                t0, t1, t2, t3 = s[t1], s[t2], s[t3], s[t0]
                t0 ^= self._RCON[i // 4]
            base = (i - 4) * 4
            w.extend((w[base] ^ t0, w[base + 1] ^ t1, w[base + 2] ^ t2, w[base + 3] ^ t3))
        return w

    @staticmethod
    def _xtime(a: int) -> int:
        return ((a << 1) ^ 0x1B) & 0xFF if (a & 0x80) else ((a << 1) & 0xFF)

    def encrypt_block(self, block: bytes) -> bytes:
        s = list(block)
        rk = self._rk
        for i in range(16):
            s[i] ^= rk[i]
        for rnd in range(1, 10):
            s = [self._S[b] for b in s]
            s = [s[0], s[5], s[10], s[15], s[4], s[9], s[14], s[3],
                 s[8], s[13], s[2], s[7], s[12], s[1], s[6], s[11]]
            for c in range(4):
                i = c * 4
                a, b, c0, d = s[i], s[i + 1], s[i + 2], s[i + 3]
                t = a ^ b ^ c0 ^ d
                u = a
                a ^= t ^ self._xtime(a ^ b)
                b ^= t ^ self._xtime(b ^ c0)
                c0 ^= t ^ self._xtime(c0 ^ d)
                d ^= t ^ self._xtime(d ^ u)
                s[i], s[i + 1], s[i + 2], s[i + 3] = a, b, c0, d
            off = rnd * 16
            for i in range(16):
                s[i] ^= rk[off + i]
        s = [self._S[b] for b in s]
        s = [s[0], s[5], s[10], s[15], s[4], s[9], s[14], s[3],
             s[8], s[13], s[2], s[7], s[12], s[1], s[6], s[11]]
        for i in range(16):
            s[i] ^= rk[160 + i]
        return bytes(s)

    def decrypt_block(self, block: bytes) -> bytes:
        def mul(a, b):
            p = 0
            for _ in range(8):
                if b & 1:
                    p ^= a
                hi = a & 0x80
                a = (a << 1) & 0xFF
                if hi:
                    a ^= 0x1B
                b >>= 1
            return p

        s = list(block)
        rk = self._rk
        for i in range(16):
            s[i] ^= rk[160 + i]
        for rnd in range(9, 0, -1):
            s = [s[0], s[13], s[10], s[7], s[4], s[1], s[14], s[11],
                 s[8], s[5], s[2], s[15], s[12], s[9], s[6], s[3]]
            s = [self._SI[b] for b in s]
            off = rnd * 16
            for i in range(16):
                s[i] ^= rk[off + i]
            for c in range(4):
                i = c * 4
                a, b, c0, d = s[i], s[i + 1], s[i + 2], s[i + 3]
                s[i] = mul(a, 0x0E) ^ mul(b, 0x0B) ^ mul(c0, 0x0D) ^ mul(d, 0x09)
                s[i + 1] = mul(a, 0x09) ^ mul(b, 0x0E) ^ mul(c0, 0x0B) ^ mul(d, 0x0D)
                s[i + 2] = mul(a, 0x0D) ^ mul(b, 0x09) ^ mul(c0, 0x0E) ^ mul(d, 0x0B)
                s[i + 3] = mul(a, 0x0B) ^ mul(b, 0x0D) ^ mul(c0, 0x09) ^ mul(d, 0x0E)
        s = [s[0], s[13], s[10], s[7], s[4], s[1], s[14], s[11],
             s[8], s[5], s[2], s[15], s[12], s[9], s[6], s[3]]
        s = [self._SI[b] for b in s]
        for i in range(16):
            s[i] ^= rk[i]
        return bytes(s)



_PureAES128._SI = tuple({v: i for i, v in enumerate(_PureAES128._S)}[i] for i in range(256))


def _pure_ctr_decrypt(key: bytes, counter: bytes, data: bytes) -> bytes:
    if not data:
        return b""
    if len(counter) < 16:
        counter = counter.ljust(16, b"\0")
    else:
        counter = counter[:16]
    aes = _PureAES128(key)
    ctr = int.from_bytes(counter, "big")
    out = bytearray()
    for offset in range(0, len(data), 16):
        ks = aes.encrypt_block(ctr.to_bytes(16, "big"))
        ctr = (ctr + 1) & ((1 << 128) - 1)
        chunk = data[offset:offset + 16]
        out.extend(c ^ k for c, k in zip(chunk, ks))
    return bytes(out)


def _pure_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    if not data:
        return b""
    if len(data) % 16:
        data = data[: len(data) - (len(data) % 16)]
    aes = _PureAES128(key)
    prev = (iv[:16] if len(iv) >= 16 else iv).ljust(16, b"\0")
    out = bytearray()
    for i in range(0, len(data), 16):
        block = data[i:i + 16]
        dec = aes.decrypt_block(block)
        out.extend(d ^ p for d, p in zip(dec, prev))
        prev = block
    return bytes(out)


def _aes_ctr_decrypt(key: bytes, counter: bytes, data: bytes) -> bytes:
    if not data:
        return b""
    if AES_BACKEND == "cryptography":
        decryptor = Cipher(algorithms.AES(key), modes.CTR(counter)).decryptor()
        return decryptor.update(data) + decryptor.finalize()
    if AES_BACKEND == "pycryptodome":
        cipher = CryptoAES.new(
            key, CryptoAES.MODE_CTR, nonce=b"", initial_value=counter
        )
        return cipher.decrypt(data)
    return _pure_ctr_decrypt(key, counter, data)


def _aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    if not data:
        return b""
    if AES_BACKEND == "cryptography":
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        return decryptor.update(data) + decryptor.finalize()
    if AES_BACKEND == "pycryptodome":
        return CryptoAES.new(key, CryptoAES.MODE_CBC, iv).decrypt(data)
    return _pure_cbc_decrypt(key, iv, data)


SITE = "https://hongguoduanju.com"
EPISODE_PREFIX = "hg-episode-v1:"
# 红果每集视频模型按清晰度返回多条独立线路（360/480/540/720/1080），
# 每条带 main_url + backup_url 双 CDN 与独立加密材料。这里把清晰度作为
# TVBox 多线路暴露；内封音/视轨在解密 _rewrite_moov 时天然全部保留。
_HG_QUALITY_LINES = (
    ("2160", "原画"),
    ("1440", "蓝光"),
    ("1080", "超清"),
    ("720",  "高清"),
    ("540",  "标准"),
    ("480",  "流畅"),
    ("360",  "极速"),
)
_QUALITY_LINE_NAME_TO_Q = {
    "原画": "2160", "蓝光": "1440",
    "超清": "1080", "高清": "720", "标准": "540",
    "流畅": "480", "极速": "360", "2160": "2160", "1440": "1440",
    "1080": "1080", "720": "720",
    "540": "540", "480": "480", "360": "360",
}


def _split_episode_token(token: str) -> tuple[str, str]:
    """把 'hg-episode-v1:<q>:<vid>' 解析为 (清晰度, vid)；兼容旧格式 'hg-episode-v1:<vid>'。"""
    body = str(token or "")
    if body.startswith(EPISODE_PREFIX):
        body = body[len(EPISODE_PREFIX):]
    if ":" in body:
        head, tail = body.split(":", 1)
        if head.isdigit():
            return head, tail
    return "1080", body

# 官网搜索 SSR 固定约 10 条且几乎不认 page；用多关键词轮换实现“翻页”
# 注：AI剧/AI漫剧 这套内容类型已按需求移除（与“漫剧”分类逐字重复），故不留 AI 专用关键词。


# ---- 本机解密缓存 + 自动清理 ----
_HG_CACHE_DIR = None
_HG_CACHE_MAX_FILES = 8          # 最多保留集数
_HG_CACHE_MAX_BYTES = 400 * 1024 * 1024  # 总容量约 400MB
_HG_CACHE_MAX_AGE = 6 * 3600     # 超过 6 小时自动删


def _hg_cache_dir() -> str:
    global _HG_CACHE_DIR
    if _HG_CACHE_DIR and os.path.isdir(_HG_CACHE_DIR):
        return _HG_CACHE_DIR
    candidates = []
    # 优先 App 可写缓存目录（OK影视 / FongMi 常见路径）
    for root in (
        "/data/user/0/com.fongmi.android.oktv/cache",
        "/data/data/com.fongmi.android.oktv/cache",
        "/data/user/0/com.fongmi.android.tv/cache",
        "/data/data/com.fongmi.android.tv/cache",
        "/sdcard/Android/data/com.fongmi.android.oktv/cache",
        "/sdcard/Android/data/com.fongmi.android.tv/cache",
        "/sdcard/Download",
    ):
        candidates.append(os.path.join(root, "hg_cenc_cache"))
    try:
        candidates.append(os.path.join(tempfile.gettempdir(), "hg_cenc_cache"))
    except Exception:
        pass
    try:
        candidates.append(os.path.join(os.getcwd(), "hg_cenc_cache"))
    except Exception:
        pass
    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
            test = os.path.join(path, ".w")
            with open(test, "wb") as fh:
                fh.write(b"1")
            os.remove(test)
            _HG_CACHE_DIR = path
            return path
        except Exception:
            continue
    _HG_CACHE_DIR = tempfile.mkdtemp(prefix="hg_cenc_")
    return _HG_CACHE_DIR


def _hg_cache_path(vid: str, quality: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_-]", "", str(vid))[:40]
    q = re.sub(r"[^0-9A-Za-z]", "", str(quality or "q"))[:8]
    return os.path.join(_hg_cache_dir(), "%s_%s.mp4" % (safe, q))


def _hg_cache_list() -> list:
    root = _hg_cache_dir()
    files = []
    try:
        now = time.time()
        for name in os.listdir(root):
            if not name.endswith(".mp4"):
                continue
            fp = os.path.join(root, name)
            if not os.path.isfile(fp):
                continue
            try:
                st = os.stat(fp)
            except Exception:
                continue
            files.append({"path": fp, "size": st.st_size, "mtime": st.st_mtime, "age": now - st.st_mtime})
    except Exception:
        return []
    files.sort(key=lambda x: x["mtime"])  # 旧 -> 新
    return files


def _hg_cache_cleanup(force: bool = False) -> None:
    """按时间 + 数量 + 体积自动清理本机缓存。"""
    try:
        files = _hg_cache_list()
        if not files and not force:
            return
        # 1) 过期删除
        remain = []
        for item in files:
            if item["age"] > _HG_CACHE_MAX_AGE or item["size"] <= 0:
                try:
                    os.remove(item["path"])
                except Exception:
                    pass
            else:
                remain.append(item)
        # 2) 超量删除最旧
        total = sum(x["size"] for x in remain)
        while remain and (len(remain) > _HG_CACHE_MAX_FILES or total > _HG_CACHE_MAX_BYTES):
            old = remain.pop(0)
            try:
                os.remove(old["path"])
            except Exception:
                pass
            total -= old["size"]
        # 3) 清理残留 tmp
        root = _hg_cache_dir()
        for name in os.listdir(root):
            if name.endswith(".tmp") or name == ".w":
                try:
                    os.remove(os.path.join(root, name))
                except Exception:
                    pass
    except Exception:
        pass



def _hg_cached_ok(body: Any) -> bool:
    """旧的整集缓存可能是 bvc2（黑屏有声），吐出去之前先验一下视轨编码。"""
    try:
        if not body:
            return False
        i = bytes(body).find(b"stsd")
        if i < 0:
            return True
        return bytes(body)[i + 16 : i + 20] in _DECODABLE_ENTRIES
    except Exception:
        return True


def _hg_cache_get(vid: str, quality: str) -> bytes | None:
    _hg_cache_cleanup(False)
    path = _hg_cache_path(vid, quality)
    try:
        if os.path.isfile(path) and os.path.getsize(path) > 64:
            # 读时刷新 mtime，避免刚播又被当过期删
            try:
                os.utime(path, None)
            except Exception:
                pass
            with open(path, "rb") as fh:
                return fh.read()
    except Exception:
        return None
    return None


def _hg_cache_put(vid: str, quality: str, data: bytes) -> None:
    if not data or len(data) < 64:
        return
    path = _hg_cache_path(vid, quality)
    try:
        _hg_cache_cleanup(False)
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
        _hg_cache_cleanup(False)
    except Exception:
        try:
            if os.path.exists(path + ".tmp"):
                os.remove(path + ".tmp")
        except Exception:
            pass


def _aes_is_fast() -> bool:
    return AES_BACKEND in ("cryptography", "pycryptodome")


def _aes_is_fast() -> bool:
    return AES_BACKEND in ("cryptography", "pycryptodome")


def _http_get_bytes(url: str, headers: dict | None = None, timeout: int = 60) -> bytes:
    h = dict(headers or {})
    r = requests.get(url, headers=h, timeout=timeout)
    r.raise_for_status()
    return r.content


def _probe_content_length(url: str, headers: dict | None = None, timeout: int = 30) -> int:
    h = dict(headers or {})
    try:
        r = requests.head(url, headers=h, timeout=timeout, allow_redirects=True)
        if r.status_code < 400:
            cl = r.headers.get("Content-Length") or r.headers.get("content-length")
            if cl and str(cl).isdigit():
                return int(cl)
    except Exception:
        pass
    try:
        hh = dict(h)
        hh["Range"] = "bytes=0-0"
        r = requests.get(url, headers=hh, timeout=timeout)
        cr = r.headers.get("Content-Range") or r.headers.get("content-range") or ""
        # bytes 0-0/12345
        if "/" in cr:
            total = cr.split("/")[-1].strip()
            if total.isdigit():
                return int(total)
        cl = r.headers.get("Content-Length") or "0"
        if str(cl).isdigit() and int(cl) > 1:
            return int(cl)
    except Exception:
        pass
    return 0


def _download_range(url: str, start: int, end: int, headers: dict | None, timeout: int) -> tuple[int, bytes]:
    h = dict(headers or {})
    h["Range"] = "bytes=%d-%d" % (start, end)
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=h, timeout=timeout)
            if r.status_code not in (200, 206):
                raise RuntimeError("range http %s" % r.status_code)
            data = r.content
            if not data:
                raise RuntimeError("empty range body")
            return start, data
        except Exception as err:
            last_err = err
            try:
                time.sleep(0.25 * (attempt + 1))
            except Exception:
                pass
    raise RuntimeError("range %s-%s failed: %s" % (start, end, last_err))


def _multi_download(url: str, headers: dict | None = None, timeout: int = 90, workers: int = 4) -> bytes:
    """多分片并行下载，失败则回退整文件单线程。"""
    headers = dict(headers or {})
    total = _probe_content_length(url, headers, timeout=min(30, timeout))
    # 太小或未知长度：直接整下
    if total <= 0 or total < 2 * 1024 * 1024:
        return _http_get_bytes(url, headers, timeout=timeout)

    # 分片大小 1~2MB，线程数限制
    workers = max(2, min(int(workers or 4), 6))
    chunk = max(1 * 1024 * 1024, min(2 * 1024 * 1024, total // workers))
    ranges = []
    start = 0
    while start < total:
        end = min(total - 1, start + chunk - 1)
        ranges.append((start, end))
        start = end + 1

    parts: dict[int, bytes] = {}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [
                pool.submit(_download_range, url, s, e, headers, timeout)
                for s, e in ranges
            ]
            for fut in concurrent.futures.as_completed(futs):
                s, data = fut.result()
                parts[s] = data
    except Exception:
        # 并行失败回退
        return _http_get_bytes(url, headers, timeout=timeout)

    buf = bytearray()
    for s, e in ranges:
        piece = parts.get(s)
        if piece is None:
            return _http_get_bytes(url, headers, timeout=timeout)
        buf.extend(piece)
    if len(buf) < total * 0.95:
        # 明显不完整
        return _http_get_bytes(url, headers, timeout=timeout)
    return bytes(buf)



_MANJU_KEYWORDS = [
    "漫剧", "动漫短剧", "二次元", "漫画短剧", "国漫短剧", "日漫", "动态漫", "动画剧",
]

# ===== 官方内容类型与分类（取自官方 hongguoduanju.com 的分类路由体系，与 App 同源同 ID）=====
_HG_CONTENT_TYPES = [
    ("real-drama", "真人剧", [
        ("", "全部"), ("romance", "爱情"), ("period", "年代"), ("comeback", "逆袭"),
        ("legend", "传奇"), ("growth", "成长"), ("family", "家庭"), ("clan", "家族"),
        ("cute-kids", "萌宝"), ("suspense", "悬疑"), ("thriller", "惊悚"), ("horror", "恐怖"),
        ("supernatural", "志怪"), ("costume", "古装"), ("fantasy", "玄幻"), ("wonder", "奇幻"),
        ("urban", "都市"), ("youth", "青春"), ("comedy", "喜剧"), ("sci-fi", "科幻"),
        ("disaster", "灾难"), ("action-adventure", "动作冒险"), ("war", "战争"),
        ("variety", "综艺"), ("drama", "剧情"),
    ]),
    ("comic-drama", "漫剧", [
        ("", "全部"), ("creative", "脑洞"), ("fantasy", "玄幻"), ("drama", "剧情"),
        ("apocalypse", "末世"), ("wealthy-family", "豪门"), ("wonder", "奇幻"),
        ("sci-fi", "科幻"), ("adventure", "冒险"),
    ]),
    ("comic", "漫画", [("", "全部")]),
]
_HG_ROUTES = {k: v for k, v in ((a, b) for a, b, _ in _HG_CONTENT_TYPES)}
_HG_ALIAS = {
    "all": "real-drama", "latest": "real-drama", "hot": "real-drama",
    "male": "real-drama", "female": "real-drama", "短剧": "real-drama",
    "manju": "comic-drama", "漫剧": "comic-drama",
}

def _hg_route_of(tid):
    t = str(tid or "").strip()
    if t in _HG_ROUTES:
        return t
    return _HG_ALIAS.get(t, "real-drama")

def _hg_category_page(route, cat, page):
    """官方分类页：/category/{route}/{item}?page=N，数据在 _ROUTER_DATA。"""
    route = _hg_route_of(route)
    path = "/category/" + route
    if cat:
        path += "/" + str(cat)
    sess = requests.Session()
    sess.trust_env = False
    sess.headers.update({"User-Agent": UA, "Referer": SITE + "/"})
    r = sess.get(SITE + path, params={"page": str(max(1, int(page or 1)))}, timeout=25)
    html = r.text or ""
    m = re.search(r"(?:window\.)?_ROUTER_DATA\s*=\s*", html)
    if not m:
        raise HongguoPluginError("分类页没有路由数据")
    v, _ = json.JSONDecoder().raw_decode(html[m.end():])
    p = ((v.get("loaderData") or {}).get("category_$") or {})
    return p

VIDEO_URL = "https://api5-normal-sinfonlineb.fqnovel.com/novel/player/multi_video_model/v1/"
VIDEO_URL_ALT = "https://api5-normal-lf.fqnovel.com/novel/player/multi_video_model/v1/"
# 2026-11-11 实测情报：multi_video_model/v1/ 已停服（任何请求只回空包），
# 同主机生效的是 video_model/v1/，请求体改为顶层 video_id。两套端点并存，自动择优。
VIDEO_URL_SINGLE = "https://api5-normal-sinfonlineb.fqnovel.com/novel/player/video_model/v1/"
VIDEO_URL_SINGLE_ALT = "https://api5-normal-lf.fqnovel.com/novel/player/video_model/v1/"

UA = "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
APP_UA = "com.phoenix.read/71332 (Linux; U; Android 16; zh_CN; 25053RT47C; Build/BP2A.250605.031.A3; Cronet/TTNetVersion:04657795 2026-01-23 QuicVersion:c67e9834 2025-09-08)"
MEDIA_UA = "com.phoenix.read/71332"




_HTML_FETCH_ATTEMPTS = 3

_HTML_FETCH_BACKOFF_SECONDS = 1.5

_RANGE_FETCH_ATTEMPTS = 3

_RANGE_FETCH_BACKOFF_SECONDS = 0.8

class HongguoPluginError(RuntimeError):
    pass

def _text(value: Any) -> str:
    return str(value or "").strip()

def _first(*values: Any) -> str:
    for value in values:
        if isinstance(value, (list, tuple)):
            result = _first(*value)
        elif isinstance(value, Mapping):
            result = _first(
                value.get("url"),
                value.get("uri"),
                value.get("src"),
                value.get("download_url"),
                value.get("main_url"),
                value.get("backup_url"),
                value.get("backup_url_1"),
                value.get("play_addr"),
                value.get("url_list"),
            )
        else:
            result = _text(value)
        if result:
            return result
    return ""

def _trim_store(store: Any, cap: int = 512, max_age: float = 0.0) -> None:
    """给常驻进程用的字典裁剪：超量就丢最旧的（必要时先丢过期的）。

    影视仓里的 py 进程可能连跑几周不重启，这类"记一下 vid/剧集"的表
    如果没人裁剪，键值对会一直涨——属于典型的长稳隐患。
    dict 保序，所以 next(iter(store)) 拿到的就是最早写入的那个。
    """
    try:
        if not isinstance(store, dict):
            return
        if max_age > 0:
            cutoff = time.time() - max_age
            for key in [k for k, v in store.items() if isinstance(v, (int, float)) and v < cutoff]:
                store.pop(key, None)
        while len(store) > cap:
            try:
                store.pop(next(iter(store)))
            except StopIteration:
                break
    except Exception:
        pass

def _json_response(response: requests.Response) -> Any:
    response.raise_for_status()
    # 上游取流接口偶发 HTTP 200 + 空体（Content-Length: 0），
    # 直接 .json() 只会抛 JSONDecodeError，日志里看不出根因，这里单独点明。
    try:
        body = response.content
    except Exception:
        body = b""
    if not body:
        raise HongguoPluginError(
            "上游取流接口返回空响应（HTTP %s）" % getattr(response, "status_code", "?")
        )
    try:
        return response.json()
    except ValueError as exc:
        raise HongguoPluginError("上游响应不是 JSON") from exc

def _router_data(html: str) -> dict[str, Any]:
    match = re.search(r"(?:window\.)?_ROUTER_DATA\s*=\s*", html)
    if not match:
        raise HongguoPluginError("页面没有路由数据")
    try:
        value, _ = json.JSONDecoder().raw_decode(html[match.end() :])
    except json.JSONDecodeError as exc:
        raise HongguoPluginError("页面路由数据解析失败") from exc
    if not isinstance(value, dict):
        raise HongguoPluginError("页面路由数据格式错误")
    return value

def _media_url(item: Mapping[str, Any]) -> str:
    return _first(
        item.get("main_url"),
        item.get("backup_url"),
        item.get("backup_url_1"),
        item.get("play_addr"),
        item.get("url"),
    )

def _spade_value(item: Mapping[str, Any]) -> str:
    encrypt_info = item.get("encrypt_info")
    if not isinstance(encrypt_info, Mapping):
        encrypt_info = {}
    return _first(item.get("spade_a"), encrypt_info.get("spade_a"))

def derive_content_key(spade_b64: str) -> bytes:
    raw = _b64(spade_b64)
    if len(raw) < 3:
        raise HongguoPluginError("spade_a 太短")
    v8 = len(raw) - (raw[0] ^ raw[1] ^ raw[2]) + 47
    if v8 <= 0 or 1 + v8 > len(raw):
        v8 = len(raw) - 1
    if v8 < 33:
        raise HongguoPluginError("spade_a 长度异常")
    value = bytearray(raw[1 : 1 + v8])
    va, vb = 85, 246
    for index in range(v8):
        previous = va if index & 1 else vb
        if index & 1:
            va = value[index]
        else:
            vb = value[index]
        value[index] = (-21 - bin(index).count("1") + (previous ^ value[index])) & 0xFF
    try:
        return binascii.unhexlify(bytes(value[1:33]).decode("ascii"))
    except (ValueError, binascii.Error) as exc:
        raise HongguoPluginError("spade_a 密钥材料无效") from exc

def _find_box(data: memoryview, fourcc: bytes, start: int) -> tuple[int, int]:
    for index in range(max(4, start), len(data) - 4):
        if data[index : index + 4] != fourcc:
            continue
        size = struct.unpack(">I", data[index - 4 : index])[0]
        if size == 1 and index + 12 <= len(data):
            size = struct.unpack(">Q", data[index + 4 : index + 12])[0]
        if 8 <= size <= 5_000_000 and index - 4 + size <= len(data):
            return index - 4, size
    return -1, 0

def _box_body(data: memoryview, fourcc: bytes, start: int) -> memoryview | None:
    offset, size = _find_box(data, fourcc, start)
    return data[offset + 8 : offset + size] if offset >= 0 else None

def _parse_track(
    moov: memoryview,
    track_offset: int,
) -> tuple[list[int], list[int], list[int], list[int], int, int] | None:
    if track_offset < 0:
        return None
    stbl_offset, _ = _find_box(moov, b"stbl", track_offset + 8)
    if stbl_offset < 0:
        return None
    stsz = _box_body(moov, b"stsz", stbl_offset)
    stco = _box_body(moov, b"stco", stbl_offset)
    co64 = _box_body(moov, b"co64", stbl_offset)
    stsc = _box_body(moov, b"stsc", stbl_offset)
    saiz = _box_body(moov, b"saiz", stbl_offset)
    saio = _box_body(moov, b"saio", stbl_offset)
    if any(value is None for value in (stsz, stsc, saiz, saio)) or (
        stco is None and co64 is None
    ):
        return None
    assert stsz is not None and stsc is not None
    assert saiz is not None and saio is not None
    default_size = struct.unpack(">I", stsz[4:8])[0]
    sample_count = struct.unpack(">I", stsz[8:12])[0]
    sizes = (
        [default_size] * sample_count
        if default_size
        else [
            struct.unpack(">I", stsz[12 + index * 4 : 16 + index * 4])[0]
            for index in range(sample_count)
        ]
    )
    chunk_table = stco if stco is not None else co64
    assert chunk_table is not None
    chunk_count = struct.unpack(">I", chunk_table[4:8])[0]
    chunk_width = 4 if stco is not None else 8
    offsets = [
        int.from_bytes(
            chunk_table[
                8 + index * chunk_width : 8 + (index + 1) * chunk_width
            ],
            "big",
        )
        for index in range(chunk_count)
    ]
    entry_count = struct.unpack(">I", stsc[4:8])[0]
    entries = [
        (
            struct.unpack(">I", stsc[8 + index * 12 : 12 + index * 12])[0],
            struct.unpack(">I", stsc[12 + index * 12 : 16 + index * 12])[0],
        )
        for index in range(entry_count)
    ]
    chunk_samples = [0] * chunk_count
    for index, (first_chunk, samples_per_chunk) in enumerate(entries):
        end = entries[index + 1][0] - 1 if index + 1 < len(entries) else chunk_count
        for chunk in range(first_chunk - 1, min(end, chunk_count)):
            chunk_samples[chunk] = samples_per_chunk
    saiz_flags = int.from_bytes(saiz[1:4], "big")
    saiz_cursor = 12 if saiz_flags & 1 else 4
    if len(saiz) < saiz_cursor + 5:
        return None
    default_aux_size = saiz[saiz_cursor]
    aux_count = struct.unpack(">I", saiz[saiz_cursor + 1 : saiz_cursor + 5])[0]
    aux_sizes = (
        [default_aux_size] * aux_count
        if default_aux_size
        else [
            int(saiz[saiz_cursor + 5 + index])
            for index in range(aux_count)
            if saiz_cursor + 5 + index < len(saiz)
        ]
    )
    if len(aux_sizes) != aux_count:
        return None
    saio_flags = int.from_bytes(saio[1:4], "big")
    saio_cursor = 12 if saio_flags & 1 else 4
    offset_width = 8 if saio[0] == 1 else 4
    if len(saio) < saio_cursor + 4 + offset_width:
        return None
    entry_count = int.from_bytes(saio[saio_cursor : saio_cursor + 4], "big")
    if entry_count < 1:
        return None
    aux_offset = int.from_bytes(
        saio[saio_cursor + 4 : saio_cursor + 4 + offset_width],
        "big",
    )
    return sizes, offsets, chunk_samples, aux_sizes, aux_offset, sample_count

def _replace_sinf(data: bytearray) -> None:
    # sinf 盒的首个子盒必为 frma（CENC 规范：frma/schm/schi）。
    # 这里校验后再清零，避免把 avcC/hvcC 配置数据里恰好出现的 "sinf" 字节
    # 当成盒来清零，那样会毁掉解码器配置，表现为视轨丢失/只有声音。
    _sinf_children = (b"frma", b"schm", b"schi")
    position = 0
    while True:
        position = data.find(b"sinf", position)
        if position < 0:
            return
        if position >= 4:
            size = struct.unpack(">I", data[position - 4 : position])[0]
            end = position - 4 + size
            child = bytes(data[position + 8 : position + 12])
            if 8 <= size < 50_000 and end <= len(data) and child in _sinf_children:
                data[position : position + 4] = b"free"
                data[position + 4 : end] = b"\x00" * max(0, end - position - 4)
                position = end
                continue
        position += 4

def decrypt_mp4_cenc(data: bytes, content_key: bytes) -> bytes:
    if len(content_key) != 16:
        raise HongguoPluginError("CENC 密钥长度错误")
    result = bytearray(data)
    if len(result) < 16:
        raise HongguoPluginError("MP4 数据过短")
    moov_start, moov_size = _find_box(memoryview(result), b"moov", 0)
    if moov_start < 0 or moov_size < 8:
        raise HongguoPluginError("MP4 moov 越界")
    moov = memoryview(result)[moov_start : moov_start + moov_size]
    tracks: list[int] = []
    track_search = 0
    while True:
        track, track_size = _find_box(moov, b"trak", track_search)
        if track < 0:
            break
        tracks.append(track)
        track_search = track + max(track_size, 8)
    decrypted_samples = 0
    for track in tracks:
        parsed = _parse_track(moov, track)
        if parsed is None:
            continue
        sizes, offsets, chunk_counts, aux_sizes, aux_offset, sample_count = parsed
        aux_size = sum(max(size, 8) for size in aux_sizes)
        if not sample_count or aux_offset < 0 or aux_offset + aux_size > len(result):
            continue
        aux = result[aux_offset : aux_offset + aux_size]
        sample_index = 0
        aux_index = 0
        for chunk_index, chunk_offset in enumerate(offsets):
            current = chunk_offset
            for _ in range(chunk_counts[chunk_index]):
                if sample_index >= sample_count or sample_index >= len(sizes):
                    break
                size = sizes[sample_index]
                if current + size > len(result):
                    raise HongguoPluginError("MP4 样本越界")
                if sample_index >= len(aux_sizes):
                    raise HongguoPluginError("MP4 辅助信息数量不足")
                entry_size = max(aux_sizes[sample_index], 8)
                iv = bytes(aux[aux_index : aux_index + min(entry_size, 8)]).ljust(
                    8, b"\0"
                ) + b"\0" * 8
                result[current : current + size] = _aes_ctr_decrypt(
                    content_key, iv, bytes(result[current : current + size])
                )
                current += size
                sample_index += 1
                aux_index += entry_size
                decrypted_samples += 1
    if not decrypted_samples:
        raise HongguoPluginError("MP4 没有可解密的 CENC 样本")
    moov_buffer = bytearray(result[moov_start : moov_start + moov_size])
    _restore_cenc_codecs(moov_buffer)
    _replace_sinf(moov_buffer)
    result[moov_start : moov_start + moov_size] = moov_buffer
    return bytes(result)

MEDIA_HEADERS = {"User-Agent": MEDIA_UA, "Referer": "https://novel.snssdk.com/"}

_STREAM_PORT_RANGE = (10010, 10030)
# 每块越小，播放器拿到首字节越快：CENC 是整块解密完才吐，1MB 一块在纯 Python
# AES 下要 2~8 秒才出声（真机表现为一直转圈、进度条不动）。128KB 一块首字节不到 1 秒，
# 总吞吐不变（下游按 64KB 连续写）。
_STREAM_CHUNK = 1 << 17
_STREAM_HEAD_PROBE = 1 << 16
_STREAM_TTL_SECONDS = 900
_STREAM_MAX_SESSIONS = 4
_STREAM_INFLIGHT_WAIT = 60
# 建会话（取 video_model + 拉 moov）冷启动约 3~18s；播放器连上来时最多等这么久，
# 超过就带着已有的会话继续，别把响应头拖过播放器的读超时。
_STREAM_WARM_WAIT = 15
_STREAM_STATE: dict[str, Any] = {"port": 0, "server": None, "sessions": {}, "inflight": {}}
_STREAM_LOCK = threading.RLock()


def _toplevel_boxes(buf: bytes) -> list[tuple[int, int, bytes]]:
    boxes: list[tuple[int, int, bytes]] = []
    cursor = 0
    while cursor + 8 <= len(buf):
        size = struct.unpack(">I", buf[cursor : cursor + 4])[0]
        fourcc = bytes(buf[cursor + 4 : cursor + 8])
        if size == 1:
            if cursor + 16 > len(buf):
                break
            size = struct.unpack(">Q", buf[cursor + 8 : cursor + 16])[0]
        if size < 8:
            break
        boxes.append((cursor, size, fourcc))
        cursor += size
    return boxes


_MEDIA_TLS = threading.local()


def _media_session() -> "requests.Session":
    """拉媒体分片用的线程本地 session（keep-alive），省掉每块重新握手。"""
    ses = getattr(_MEDIA_TLS, "s", None)
    if ses is None:
        ses = requests.Session()
        ses.trust_env = False
        ses.headers.update(MEDIA_HEADERS)
        _MEDIA_TLS.s = ses
    return ses


def _range_get(url: str, start: int, end: int) -> tuple[bytes, int]:
    headers = {"Range": "bytes=%d-%d" % (start, end)}
    expected = end - start + 1
    last_error: Exception | None = None
    for attempt in range(_RANGE_FETCH_ATTEMPTS):
        if attempt:
            time.sleep(_RANGE_FETCH_BACKOFF_SECONDS * attempt)
        try:
            response = _media_session().get(url, headers=headers, timeout=60)
        except requests.RequestException as error:
            last_error = error
            continue
        if response.status_code not in (200, 206):
            last_error = HongguoPluginError(
                "媒体分片请求失败 %s" % response.status_code
            )
            continue
        body = response.content
        # 上游偶发返回短包；短于请求长度时重试，避免播放器收到截断数据。
        if not body or (response.status_code == 206 and len(body) < expected):
            last_error = HongguoPluginError(
                "媒体分片长度不足 %d/%d" % (len(body), expected)
            )
            continue
        total = 0
        content_range = response.headers.get("Content-Range") or ""
        if "/" in content_range:
            tail = content_range.rsplit("/", 1)[1].strip()
            if tail.isdigit():
                total = int(tail)
        if not total:
            length = response.headers.get("Content-Length") or ""
            total = int(length) if length.isdigit() else 0
        return body, total
    raise last_error or HongguoPluginError("媒体分片请求失败")


def _fetch_moov(url: str) -> tuple[int, int, bytes]:
    probe, total = _range_get(url, 0, _STREAM_HEAD_PROBE - 1)
    if not total:
        raise HongguoPluginError("媒体总长度未知")
    moov_start = 0
    moov_size = 0
    for offset, size, fourcc in _toplevel_boxes(probe):
        if fourcc == b"moov":
            moov_start = offset
            moov_size = size
            break
    if not moov_size:
        raise HongguoPluginError("未找到 moov 顶层盒")
    if moov_start + moov_size > total:
        raise HongguoPluginError("moov 越界")
    if moov_start + moov_size <= len(probe):
        return total, moov_start, bytes(probe[moov_start : moov_start + moov_size])
    moov, _ = _range_get(url, moov_start, moov_start + moov_size - 1)
    if len(moov) != moov_size:
        raise HongguoPluginError("moov 分片长度不符")
    return total, moov_start, moov


# 解码器配置盒 -> 真实 sample entry 四字符码。
# CENC 的 sinf/frma 缺失或无效时，这是判断真实编码最可靠的依据：
# 一律兜底 avc1 会把 HEVC(hvc1) 错标成 H.264，播放器按错编码解视轨，
# 表现为「有声音没画面 / 视轨缺失」——这正是低清晰度线路只有超清能看的原因。
_CONFIG_BOX_TO_FORMAT = (
    (b"hvcC", b"hvc1"),
    (b"hev1C", b"hev1"),
    (b"av1C", b"av01"),
    (b"vpcC", b"vp09"),
    (b"avcC", b"avc1"),
    (b"dvvC", b"dvh1"),
    (b"dvhC", b"dvh1"),
)
_AUDIO_CONFIG_BOX_TO_FORMAT = (
    (b"esds", b"mp4a"),
    (b"opusC", b"Opus"),
    (b"ac-3", b"ac-3"),
    (b"ec-3", b"ec-3"),
)


def _format_from_config_box(blob: bytes, kind: bytes) -> bytes:
    """按 sample entry 内的解码器配置盒推断真实编码，找不到返回空串。"""
    probes = _AUDIO_CONFIG_BOX_TO_FORMAT + _CONFIG_BOX_TO_FORMAT if kind == b"enca" \
        else _CONFIG_BOX_TO_FORMAT + _AUDIO_CONFIG_BOX_TO_FORMAT
    hit_pos, hit_fmt = -1, b""
    for fourcc, fmt in probes:
        pos = blob.find(fourcc)
        # 取最靠前的配置盒：sample entry 内通常只含一个，靠前者更可能是本轨的配置
        if pos >= 0 and (hit_pos < 0 or pos < hit_pos):
            hit_pos, hit_fmt = pos, fmt
    return hit_fmt


def _original_format_near(data: bytearray, entry_pos: int, default: bytes, kind: bytes = b"encv") -> bytes:
    """从 sample entry 后的 sinf/frma 读取原始四字符码（avc1/hvc1/mp4a 等）。
    frma 缺失/无效时回退到配置盒探测，而不是一律兜底 avc1。"""
    blob = bytes(data[entry_pos : min(len(data), entry_pos + 800)])
    idx = 0
    while True:
        pos = blob.find(b"frma", idx)
        if pos < 0:
            break
        if pos + 8 <= len(blob):
            fmt = bytes(blob[pos + 4 : pos + 8])
            if fmt not in (b"", b"\x00\x00\x00\x00", b"encv", b"enca") and all(32 <= c < 127 for c in fmt):
                return fmt
        idx = pos + 4
    probed = _format_from_config_box(blob, kind)
    return probed or default


def _restore_cenc_codecs(data: bytearray) -> None:
    """把 encv/enca 还原为真实编码（frma 优先，其次按 avcC/hvcC 等配置盒判定）。
    避免一律改成 avc1/hvc1 导致非对应编码的视轨解不出画面。"""
    pos = 0
    while True:
        pos = data.find(b"encv", pos)
        if pos < 0:
            break
        data[pos : pos + 4] = _original_format_near(data, pos, b"avc1", b"encv")
        pos += 4
    pos = 0
    while True:
        pos = data.find(b"enca", pos)
        if pos < 0:
            break
        data[pos : pos + 4] = _original_format_near(data, pos, b"mp4a", b"enca")
        pos += 4


def _moov_has_video_track(moov: bytes) -> bool:
    """moov 中是否存在 hdlr='vide' 的轨。用于校验某清晰度是否真的带视轨。"""
    view = memoryview(moov)
    search = 0
    found_trak = False
    while True:
        trak, trak_size = _find_box(view, b"trak", search)
        if trak < 0:
            break
        found_trak = True
        search = trak + max(trak_size, 8)
        hdlr = _box_body(view, b"hdlr", trak + 8)
        if hdlr is not None and len(hdlr) >= 12:
            if bytes(hdlr[8:12]) == b"vide":
                return True
    # 解析不出任何 trak 时不轻易判死刑，交由后续解密流程定夺
    return not found_trak


def _rewrite_moov(moov: bytes) -> bytes:
    result = bytearray(moov)
    _restore_cenc_codecs(result)
    _replace_sinf(result)
    return bytes(result)


def _sample_table(moov: bytes, moov_start: int) -> list[tuple[int, int, bytes]]:
    view = memoryview(moov)
    samples: list[tuple[int, int, bytes]] = []
    track_search = 0
    while True:
        track, track_size = _find_box(view, b"trak", track_search)
        if track < 0:
            break
        track_search = track + max(track_size, 8)
        parsed = _parse_track(view, track)
        if parsed is None:
            continue
        sizes, offsets, chunk_counts, aux_sizes, aux_offset, sample_count = parsed
        aux_length = sum(max(size, 8) for size in aux_sizes)
        aux_local = aux_offset - moov_start
        if aux_local < 0 or aux_local + aux_length > len(moov):
            raise HongguoPluginError("CENC 辅助信息不在 moov 内，无法流式解密")
        aux = moov[aux_local : aux_local + aux_length]
        sample_index = 0
        aux_index = 0
        for chunk_index, chunk_offset in enumerate(offsets):
            current = chunk_offset
            for _ in range(chunk_counts[chunk_index]):
                if sample_index >= sample_count or sample_index >= len(sizes):
                    break
                if sample_index >= len(aux_sizes):
                    raise HongguoPluginError("CENC 辅助信息数量不足")
                entry_size = max(aux_sizes[sample_index], 8)
                initial_vector = bytes(
                    aux[aux_index : aux_index + min(entry_size, 8)]
                ).ljust(8, b"\0") + b"\0" * 8
                samples.append((current, sizes[sample_index], initial_vector))
                current += sizes[sample_index]
                aux_index += entry_size
                sample_index += 1
    if not samples:
        raise HongguoPluginError("moov 中没有可解密的 CENC 样本")
    samples.sort()
    return samples



_HG_Q_TO_QTYPE = {"2160": "0", "1440": "2", "1080": "1", "720": "10", "540": "20", "480": "30", "360": "40"}
_Q_LABEL = {"2160": "原画", "1440": "蓝光", "1080": "超清", "720": "高清", "540": "标准", "480": "流畅", "360": "极速"}
_QTYPE_TO_Q = {"0": "2160", "2": "1440", "1": "1080", "10": "720", "20": "540", "30": "480", "40": "360"}
# 壳里播放器认得的标准视轨四字符码；bvc2（ByteVC2）不在其中，只出声音不出画面
_DECODABLE_ENTRIES = (b"hvc1", b"hev1", b"avc1", b"avc3")


def _hg_entry_is_bytevc2(item: Any) -> bool:
    """单个清晰度条目是不是 ByteVC2（壳解不了，会黑屏只有声音）。"""
    return isinstance(item, Mapping) and "bytevc2" in str(item.get("gear_des_key") or "")


def _hg_is_bytevc2(rows: Any) -> bool:
    try:
        return any(_hg_entry_is_bytevc2(x) for x in (rows or []))
    except Exception:
        return False


_VIDEO_FOURCCS = (b"hvc1", b"hev1", b"hvc2", b"hev2", b"avc1", b"avc3",
                  b"bvc2", b"bv2C", b"av01", b"vp09", b"encv")


def _hg_moov_fourcc(moov: bytes) -> bytes:
    """从 moov 的 stsd 里取视轨 sample entry 四字符码。

    注意 moov 里音轨、视轨各有一个 stsd，谁在前不固定（实测《反向拿捏2》第 8 集
    兜底直链的 moov 是音轨 mp4a 在前）。只认第一个 stsd 会把 hvc1 误判成 mp4a，
    于是明明能播的 hvc1 直链被验成不可播。这里按顺序找第一个「视频类」四字符码。
    """
    first = b""
    i = moov.find(b"stsd")
    pos = 0
    while i >= 0:
        j = i + 4 + 8
        cc = bytes(moov[j + 4 : j + 8])
        if not first:
            first = cc
        if cc in _VIDEO_FOURCCS:
            return cc
        pos = i + 4
        i = moov.find(b"stsd", pos)
    return first


def _hg_plain_candidates(model: Mapping[str, Any], quality: str = "1080", strict: bool = False) -> list:
    """备用接口（codec_type=1）的标准 hvc1 直链候选。

    只收非 bytevc2 且能解出地址的条目；返回 [(url, size), ...]。
    strict=True 时只认这一档自己的清晰度，绝不跨档串用（防止 1080 被换成 720）。
    """
    fb = _fallback_api_value(model.get("fallback_api") if isinstance(model, Mapping) else None)
    if not fb:
        return []
    api = re.sub(r"codec_type=\d+", "codec_type=1", fb)
    if "codec_type=" not in api:
        api = api + ("&" if "?" in api else "?") + "codec_type=1"
    j = None
    for _i in range(2):
        try:
            r = requests.get(api, headers={"User-Agent": APP_UA}, timeout=8)
            if r.status_code == 200:
                j = r.json()
                if isinstance(j, Mapping):
                    break
        except Exception:
            j = None
        try:
            time.sleep(0.3)
        except Exception:
            pass
    if not isinstance(j, Mapping):
        return []
    data = j
    for key in ("video_info", "data"):
        if isinstance(data.get(key), Mapping):
            data = data[key]
    if isinstance(data.get("data"), Mapping):
        data = data["data"]
    raw_list = data.get("video_list") or {}
    items = list(raw_list.values()) if isinstance(raw_list, Mapping) else [x for x in raw_list if isinstance(x, Mapping)]
    if not items:
        return []
    seed = _key_seed_from_model(data)
    first = _HG_Q_TO_QTYPE.get(str(quality), "1")
    if strict:
        order = [first]
    else:
        order = [first] + [q for q in ("0", "2", "1", "10", "20", "30", "40") if q != first]
    out = []
    seen = set()
    for qt in order:
        for it in items:
            if not isinstance(it, Mapping) or _hg_entry_is_bytevc2(it):
                continue
            if str(it.get("quality_type") or "") != qt:
                continue
            raw = _text(it.get("main_url"))
            pick = raw
            if seed and raw and not raw.startswith("http"):
                try:
                    pick = _decrypt_spade_url(raw, seed) or raw
                except Exception:
                    pick = raw
            if not pick.startswith("http") or pick in seen:
                continue
            seen.add(pick)
            out.append((pick, int(it.get("size") or 0)))
    return out


def _hg_entry_size(item: Any) -> int:
    """从模型条目里取字节数（video_meta.size 优先，缺了看顶层 size）。"""
    try:
        if not isinstance(item, Mapping):
            return 0
        vm = item.get("video_meta")
        if isinstance(vm, Mapping) and vm.get("size"):
            return int(vm.get("size") or 0)
        return int(item.get("size") or 0)
    except Exception:
        return 0


def _hg_plain_url_session(url: str, size: int = 0) -> Any:
    """上游本就是未加密直链时，验成标准 hvc1/avc1 且中段 206 才返回直通会话。

    站点对部分集数给的是 1:normal（没有 encrypt_info）：这类流不需要解密，
    但同样不能把 bytevc2 或加密壳丢给播放器，所以沿用同一套四字符码 + 视频轨 + 中段校验。
    """
    if not isinstance(url, str) or not url.startswith("http"):
        return None
    try:
        total, _moov_start, moov = _fetch_moov(url)
    except Exception:
        return None
    if _hg_moov_fourcc(moov) not in _DECODABLE_ENTRIES:
        return None
    if not _moov_has_video_track(moov):
        return None
    mid = max((total or size) // 2, 1024)
    try:
        head = requests.get(
            url,
            headers={"Range": "bytes=%d-%d" % (mid, mid + 1023), "User-Agent": MEDIA_UA},
            timeout=8,
        )
        if head.status_code != 206:
            return None
    except Exception:
        return None
    return _PlainSession(url, total or size)


def _hg_plain_session(model: Mapping[str, Any], quality: str = "1080", strict: bool = True) -> Any:
    """挑一条确认是标准 hvc1/avc1、且能按 Range 取中段（可 seek）的直通流。

    三条候选都验不过就返回 None，交给调用方报错重试，绝不把 bvc2 丢给播放器。
    """
    for url, size in _hg_plain_candidates(model, quality, strict)[:3]:
        sess = _hg_plain_url_session(url, size)
        if sess is not None:
            return sess
    return None


class _StreamSession:
    """按 Range 逐块拉取加密 MP4，边下边解 CENC，供本地播放器直连。"""

    def __init__(
        self,
        url: str,
        content_key: bytes,
        total: int,
        moov_start: int,
        moov: bytes,
    ) -> None:
        if len(content_key) != 16:
            raise HongguoPluginError("CENC 密钥长度错误")
        self.url = url
        self.content_key = content_key
        self.total = total
        self.moov_start = moov_start
        self.moov_plain = _rewrite_moov(moov)
        self.moov_end = moov_start + len(moov)
        self.samples = _sample_table(moov, moov_start)
        self.offsets = [item[0] for item in self.samples]
        self.created = time.time()

    def expired(self) -> bool:
        return time.time() - self.created > _STREAM_TTL_SECONDS

    def _patch(self, buffer: bytearray, base: int) -> None:
        end = base + len(buffer) - 1
        index = max(bisect.bisect_right(self.offsets, base) - 1, 0)
        while index < len(self.samples):
            offset, size, initial_vector = self.samples[index]
            index += 1
            if offset > end:
                break
            if offset + size <= base:
                continue
            first = max(offset, base)
            last = min(offset + size - 1, end)
            skip = first - offset
            counter = (
                (int.from_bytes(initial_vector, "big") + skip // 16)
                & ((1 << 128) - 1)
            ).to_bytes(16, "big")
            padding = skip % 16
            plain = _aes_ctr_decrypt(
                self.content_key,
                counter,
                b"\0" * padding + bytes(buffer[first - base : last - base + 1]),
            )
            buffer[first - base : last - base + 1] = plain[padding:]
        if base < self.moov_end and end >= self.moov_start:
            first = max(base, self.moov_start)
            last = min(end, self.moov_end - 1)
            buffer[first - base : last - base + 1] = self.moov_plain[
                first - self.moov_start : last - self.moov_start + 1
            ]

    def read_range(self, start: int, end: int) -> bytes:
        raw, _ = _range_get(self.url, start, end)
        if not raw:
            raise HongguoPluginError("媒体分片为空")
        buffer = bytearray(raw)
        self._patch(buffer, start)
        return bytes(buffer)

    def iter_range(self, start: int, end: int):
        cursor = start
        while cursor <= end:
            stop = min(cursor + _STREAM_CHUNK - 1, end)
            block = self.read_range(cursor, stop)
            yield block
            cursor += len(block)


def _fresh_device_pair() -> tuple[str, str]:
    return (
        str(random.randint(10**17, 10**18 - 1)),
        str(random.randint(10**17, 10**18 - 1)),
    )


# ---- 设备身份持久化 ----
# 重启 App 后沿用同一台「已注册设备」，服务端信任随使用累积；
# 每次都换新设备 = 永远零信任，容易撞风控限额（如只能看前几集）。
_DEVICE_FILE = "hg_device.json"


def _device_file_path() -> str:
    try:
        return os.path.join(_hg_cache_dir(), _DEVICE_FILE)
    except Exception:
        return ""


def _load_persisted_device() -> dict[str, str] | None:
    try:
        path = _device_file_path()
        if not path or not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        did = _text(data.get("device_id"))
        iid = _text(data.get("install_id"))
        if did.isdigit() and iid.isdigit() and did != "0" and iid != "0":
            return {"device_id": did, "install_id": iid}
    except Exception:
        pass
    return None


def _persist_device(pair: Mapping[str, Any]) -> None:
    try:
        did = _text(pair.get("device_id"))
        iid = _text(pair.get("install_id"))
        path = _device_file_path()
        if not (did and iid and path):
            return
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"device_id": did, "install_id": iid}, fh)
        os.replace(tmp, path)
    except Exception:
        pass


def _is_empty_model_error(err: BaseException) -> bool:
    text = str(err)
    return (
        "video_model 数据为空" in text
        or "video_model 为空" in text
        or "上游响应不是 JSON" in text
        or "返回空响应" in text
        or "播放模型没有清晰度" in text
        or "播放模型缺少地址或密钥材料" in text
    )


def _register_device_pair() -> tuple[str, str] | None:
    try:
        import uuid as _uuid
        openudid = "".join(random.choice("0123456789abcdef") for _ in range(16))
        # 版本号与播放链路（APP_UA / _video_model 参数）保持一致：
        # 同一设备注册时 73532、播放时 71332 的版本矛盾是服务端风控的明显异常点。
        header = {"display_name": "红果免费短剧", "aid": 8662, "app_version": "7.1.3.32", "version_code": 71332, "manifest_version_code": 71332, "update_version_code": 71332, "channel": "update_64", "package": "com.phoenix.read", "app_language": "zh", "os": "Android", "os_version": "16", "os_api": 36, "device_model": "25053RT47C", "device_brand": "Redmi", "device_manufacturer": "Xiaomi", "cpu_abi": "arm64-v8a", "density_dpi": 520, "display_density": "xxhdpi", "resolution": "2772x1280", "language": "zh", "timezone": 8, "access": "wifi", "openudid": openudid, "clientudid": str(_uuid.uuid4()), "cdid": str(_uuid.uuid4()), "region": "CN", "tz_name": "Asia/Shanghai", "tz_offset": 28800, "sim_region": "cn", "device_platform": "android", "not_request_sender": 0, "is_system_app": 0, "sdk_flavor": "china", "rom": "OS2.0", "rom_version": "BP2A.250605.031.A3"}
        body = json.dumps({"magic_tag": "ss_app_log", "header": header, "_gen_time": int(time.time() * 1000)}).encode("utf-8")
        qs = urlencode({"req_id": str(_uuid.uuid4()), "_rticket": int(time.time() * 1000)})
        resp = requests.post(
            "https://log.snssdk.com/service/2/device_register/?" + qs,
            data=body,
            headers={"User-Agent": APP_UA, "Accept": "application/json", "Content-Type": "application/json; charset=utf-8"},
            timeout=20,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        did = str(data.get("device_id_str") or data.get("device_id") or "")
        iid = str(data.get("install_id_str") or data.get("install_id") or "")
        if did.isdigit() and iid.isdigit() and did != "0" and iid != "0":
            return did, iid
    except Exception:
        pass
    return None


def _rotate_stream_device() -> dict[str, str]:
    registered = _register_device_pair()
    if registered is not None:
        device_id, install_id = registered
        is_registered = True
        _persist_device({"device_id": device_id, "install_id": install_id})
    else:
        device_id, install_id = _fresh_device_pair()
        is_registered = False
    pair = {"device_id": device_id, "install_id": install_id}
    with _STREAM_LOCK:
        stored = dict(pair)
        stored["registered"] = is_registered
        _STREAM_STATE["device"] = stored
    return pair


def _working_device_pair() -> dict[str, str] | None:
    with _STREAM_LOCK:
        pair = _STREAM_STATE.get("device")
    if isinstance(pair, dict) and pair.get("device_id") and pair.get("install_id"):
        return {"device_id": str(pair["device_id"]), "install_id": str(pair["install_id"])}
    # 内存没有（App 刚重启）→ 恢复本机持久化的已注册设备，沿用旧身份而不是重开新号
    persisted = _load_persisted_device()
    if persisted is not None:
        with _STREAM_LOCK:
            stored = dict(persisted)
            stored["registered"] = True
            _STREAM_STATE["device"] = stored
    return persisted


_SIGN_LOCK = threading.Lock()
_SIGN_PREF: dict[str, str | None] = {"mode": None}


def _sign_modes_ordered() -> tuple[str, str]:
    """自适应签名顺序：哪种签名最近一次成功，下次就先试哪种。
    服务端风控策略会随时间翻转（2026-11-10 实测就从只认六神翻成只认海阔），
    固定顺序意味着翻转后每次播放都白挨一次失败请求。"""
    with _SIGN_LOCK:
        pref = _SIGN_PREF["mode"]
    return ("sixgod", "hiker") if pref == "sixgod" else ("hiker", "sixgod")


def _sign_pref_mark(mode: str) -> None:
    with _SIGN_LOCK:
        _SIGN_PREF["mode"] = mode


_EP_PREF: dict[str, bool | None] = {"single": None}


def _ep_modes_ordered() -> tuple[bool, bool]:
    """端点择优：multi_video_model 与 video_model 哪个最近成功就先用哪个。
    2026-11-11：multi_ 已停服只回空包，single 生效；保留双端点自动切换，
    服务端再翻回去也能无感跟上。"""
    with _SIGN_LOCK:
        pref = _EP_PREF["single"]
    return (True, False) if pref else (False, True)


def _ep_pref_mark(single: bool) -> None:
    with _SIGN_LOCK:
        _EP_PREF["single"] = single


def _video_model_rotating(video_id: str, config: Mapping[str, Any]) -> dict[str, Any]:
    last_err: BaseException | None = None
    # 2026-11-10 18:39 真机取流实测（同一分钟里换 5 个 vid 各试 5 次、
    # 两个 host 交替、每次现场注册新设备号，全部 HTTP 200 + 空体；80 秒后再试仍空，
    # 而 5 分钟前同一个 vid 一次就回 23791 字节 JSON）证明：空体是站点侧成波出现的，
    # 不是设备号被风控、也不是某个 vid 坏了。短重试只能抓住「波刚到尾巴」这种运气，
    # 所以这里给 5 轮（每轮新设备号 + 两个 host 交替 + 逐步退避，总耗时压在 3 秒级），
    # 拿不到就快速失败，由上层挂后台继续试，别让播放器干等十几秒。
    for attempt in range(5):
        # 每一轮按「端点（multi/single）× 签名（hiker/sixgod）」组合各打一次，
        # 两组都优先上次成功的那种。兜底不只认「空体」——签名被风控或端点停服
        # 时服务端也可能回 HTTP 4xx，任何非网络层错误都继续试下一组合。
        modes = _sign_modes_ordered()
        net_err = False
        for single in _ep_modes_ordered():
            if net_err:
                break
            if single:
                endpoint = VIDEO_URL_SINGLE if attempt % 2 == 0 else VIDEO_URL_SINGLE_ALT
            else:
                endpoint = VIDEO_URL if attempt % 2 == 0 else VIDEO_URL_ALT
            for idx, sign_mode in enumerate(modes):
                try:
                    model = _video_model(video_id, config, endpoint, sign_mode, single=single)
                    _sign_pref_mark(sign_mode)
                    _ep_pref_mark(single)
                    return model
                except Exception as err:
                    last_err = err
                    if isinstance(err, (requests.ConnectionError, requests.Timeout)):
                        net_err = True
                        break  # 断网/超时与签名、端点无关，交给外层换 host 重试
                    if idx == 0:
                        print("[红果] %s sign=%s 未通过（%s），换 %s 兜底" %
                              ("video_model" if single else "multi_video_model",
                               sign_mode, str(err)[:60], modes[1]))
        try:
            time.sleep(min(0.2 * (attempt + 1), 0.6))
        except Exception:
            pass
        pair = _rotate_stream_device()
        try:
            config["device_id"] = pair["device_id"]
            config["install_id"] = pair["install_id"]
        except (TypeError, AttributeError):
            config = pair
    print("[红果] video_model 5 轮双签名均失败：%s" % str(last_err)[:120])
    raise last_err if last_err is not None else HongguoPluginError("video_model 为空")


# ===== 空体高峰期的后台重试 =====
# 2026-11-10 实测：站点空体是成波来的（18:41~18:43 连续 16 次、跨 80 秒全空），
# 在播放器那一次请求里死等救不回来。失败后挂一个后台线程按秒继续试，
# 一旦拿到非空 JSON 就把会话放进缓存，用户再点一次立刻起播。
_WARM_LOCK = threading.Lock()
_WARM_ACTIVE: set = set()
_WARM_WINDOW = 180.0
_WARM_INTERVAL = 4.0


def _warm_burst(video_id: str, config: Mapping[str, Any], quality: str) -> None:
    key = "%s|%s" % (video_id, quality)
    with _WARM_LOCK:
        if key in _WARM_ACTIVE or len(_WARM_ACTIVE) >= 2:
            return
        _WARM_ACTIVE.add(key)

    def _run() -> None:
        deadline = time.time() + _WARM_WINDOW
        try:
            while time.time() < deadline:
                time.sleep(_WARM_INTERVAL)
                try:
                    _stream_session(video_id, dict(config or {}), quality)
                except Exception:
                    continue
                return
        finally:
            with _WARM_LOCK:
                _WARM_ACTIVE.discard(key)

    try:
        threading.Thread(target=_run, daemon=True, name="hg-warm").start()
    except Exception:
        with _WARM_LOCK:
            _WARM_ACTIVE.discard(key)


def _stream_session(video_id: str, config: Mapping[str, Any], quality: str = "1080",
                    force: bool = False) -> "_StreamSession":
    quality = quality if quality in _QUALITY_LINE_NAME_TO_Q else "1080"
    cache_key = "%s|%s" % (video_id, quality)
    leader = False
    event = None
    if not force:
        with _STREAM_LOCK:
            sessions = _STREAM_STATE["sessions"]
            for key in [key for key, item in sessions.items() if item.expired()]:
                sessions.pop(key, None)
            session = sessions.get(cache_key)
        if session is not None:
            return session
        # 预热线程与播放器可能同时请求同一集；用 in-flight 事件去重，
        # 避免重复拉 video_model 与 moov（冷启动 3~18s，重复会叠加首字节延迟）。
        with _STREAM_LOCK:
            inflight = _STREAM_STATE.setdefault("inflight", {})
            event = inflight.get(cache_key)
            leader = event is None
            if leader:
                event = threading.Event()
                inflight[cache_key] = event
        if not leader:
            event.wait(_STREAM_INFLIGHT_WAIT)
            with _STREAM_LOCK:
                session = _STREAM_STATE["sessions"].get(cache_key)
            if session is not None:
                return session
    last_err = None
    try:
        # 上游偶发抖动（同一集首次 502、重试即通）——冷启动这里做短重试。
        for _attempt in range(3):
            try:
                model = _video_model_rotating(video_id, config)
                rows = _video_list_from_model(model)
                key_seed = _key_seed_from_model(model) or ""
                # 按模型里真实存在的档位排，按与用户所选档的接近程度降序，绝不跳档乱配。
                # _QTYPE_TO_Q 已覆盖 2160/1440，故 4K/2K 档也能参与排序。
                avail: list = []
                for _row in rows:
                    _q = _QTYPE_TO_Q.get(str(_row.get("quality_type") or "")) if isinstance(_row, Mapping) else None
                    if _q and _q not in avail:
                        avail.append(_q)
                if quality not in avail:
                    avail.insert(0, quality)
                _rank = {q: i for i, q in enumerate(_QUALITY_ORDER)}
                _base = _rank.get(quality, 99)
                avail.sort(key=lambda q: (0 if q == quality else 1, abs(_rank.get(q, 99) - _base)))
                wanted_order = avail
                seen_urls = set()
                reason = "媒体会话创建失败"
                probed = 0

                def _take(sess: Any, want: str) -> Any:
                    """缓存并按档位返回会话；真的降了档就在日志里说清楚。"""
                    try:
                        sess.quality = want
                    except Exception:
                        pass
                    if want != quality:
                        try:
                            print(
                                "[红果] %s 的%s档拿不到壳能解的编码，降到%s档播出"
                                % (video_id, _Q_LABEL.get(quality, quality), _Q_LABEL.get(want, want))
                            )
                        except Exception:
                            pass
                    with _STREAM_LOCK:
                        store = _STREAM_STATE["sessions"]
                        while len(store) >= _STREAM_MAX_SESSIONS:
                            store.pop(next(iter(store)), None)
                        store[cache_key] = sess
                    return sess

                for want in wanted_order:
                    # _select_quality 返回的是这一档实际命中的清晰度（可能低于所选档），
                    # 后面所有判断都要按"实际拿到的档"来走，不能按"想要的档"。
                    actual, item = _select_quality(rows, want)
                    # 这一档是 ByteVC2：只在这一档上要标准 hvc1，不跨档串
                    if _hg_entry_is_bytevc2(item):
                        plain_session = None
                        try:
                            plain_session = _hg_plain_session(model, actual, strict=True)
                        except Exception:
                            plain_session = None
                        if plain_session is not None:
                            return _take(plain_session, actual)
                        reason = "该档只有 bytevc2，同档 hvc1 也没取到 q=%s" % want
                        continue
                    # 这一档本来就是标准编码：走解密路，验不过再回同一档取直通
                    raw_url = _media_url(item)
                    spade = _spade_value(item)
                    if not raw_url:
                        reason = reason if reason != "媒体会话创建失败" else "播放模型缺少地址或密钥材料 q=%s" % want
                        continue
                    if raw_url in seen_urls:
                        continue
                    seen_urls.add(raw_url)
                    url = raw_url
                    if key_seed:
                        try:
                            url = _decrypt_spade_url(raw_url, key_seed) or raw_url
                        except HongguoPluginError:
                            url = raw_url
                    # 这一档上游没有加密材料（gear_des_key 是 1:normal、无 encrypt_info）：
                    # 本来就是未加密直链，直通转发即可，不能再当成「缺密钥」判失败
                    if not spade:
                        plain_url_session = _hg_plain_url_session(url, _hg_entry_size(item))
                        if plain_url_session is not None:
                            return _take(plain_url_session, actual)
                        reason = "该档未加密但验不过标准编码 q=%s" % want
                        continue
                    total = 0
                    moov = b""
                    moov_start = 0
                    try:
                        total, moov_start, moov = _fetch_moov(url)
                    except Exception:
                        total, moov = 0, b""
                    if total and _moov_has_video_track(moov):
                        session = _StreamSession(url, derive_content_key(spade), total, moov_start, moov)
                        # 解密后吐给播放器的视轨必须是他认得的编码，bvc2 这种一律不交
                        _sfc = _hg_moov_fourcc(session.moov_plain)
                        if not _sfc or _sfc in _DECODABLE_ENTRIES:
                            return _take(session, actual)
                        reason = "视轨编码 %s 壳解不了 q=%s" % (_sfc.decode("latin-1"), want)
                    else:
                        reason = "该清晰度没有视轨 q=%s" % want
                    probed += 1
                    plain_session = None
                    try:
                        plain_session = _hg_plain_session(model, actual, strict=True)
                    except Exception:
                        plain_session = None
                    if plain_session is not None:
                        return _take(plain_session, actual)
                    if probed >= 3:
                        break
                # 全部档位走不通：备用接口(fallback_api)直通兜底——那边低清是标准 hvc1，
                # 是壳唯一解得动的编码；此时允许跨档（strict=False），宁可降档也要能播。
                plain_session = None
                try:
                    plain_session = _hg_plain_session(model, quality, strict=False)
                except Exception:
                    plain_session = None
                if plain_session is not None:
                    return _take(plain_session, quality)
                raise HongguoPluginError(reason)
            except Exception as err:
                last_err = err
                try:
                    time.sleep(0.4 * (_attempt + 1))
                except Exception:
                    pass
        if last_err is not None:
            raise last_err
        raise HongguoPluginError("媒体会话创建失败")
    finally:
        if leader and event is not None:
            with _STREAM_LOCK:
                _STREAM_STATE.get("inflight", {}).pop(cache_key, None)
            event.set()


_RANGE_UNSATISFIABLE = "unsatisfiable"

def _parse_range(value: str, total: int) -> Any:
    """解析 Range 头。返回 (start, end)、None（忽略）或 _RANGE_UNSATISFIABLE。"""
    text = (value or "").strip().lower()
    if not text.startswith("bytes="):
        return None
    spec = text[6:].split(",")[0].strip()
    if "-" not in spec:
        return None
    left, right = spec.split("-", 1)
    if not left:
        if not right.isdigit():
            return None
        length = min(int(right), total)
        if not length:
            return _RANGE_UNSATISFIABLE
        return total - length, total - 1
    if not left.isdigit():
        return None
    start = int(left)
    end = int(right) if right.isdigit() else total - 1
    end = min(end, total - 1)
    if start >= total or start > end:
        return _RANGE_UNSATISFIABLE
    return start, end


class _PlainSession:
    """直通会话：上游是标准 hvc1 MP4（未加密），按 Range 原样转发。"""

    def __init__(self, url: str, total: int) -> None:
        self.url = url
        self.total = int(total)
        self.created = time.time()

    def expired(self) -> bool:
        return time.time() - self.created > _STREAM_TTL_SECONDS

    def iter_range(self, start: int, end: int, chunk: int = 512 * 1024):
        position = start
        while position <= end:
            stop = min(end, position + chunk - 1)
            last_error = None
            block = None
            # 轻量重试: 网络抖动就地消化, 避免升级到昂贵的整会话重建
            for attempt in range(3):
                if attempt:
                    time.sleep(0.5 * attempt)
                try:
                    response = requests.get(
                        self.url,
                        headers={
                            "Range": "bytes=%d-%d" % (position, stop),
                            "User-Agent": MEDIA_UA,
                            "Referer": "https://novel.snssdk.com/",
                        },
                        timeout=30,
                        stream=True,
                    )
                except requests.RequestException as error:
                    last_error = error
                    continue
                try:
                    if response.status_code not in (200, 206):
                        raise HongguoPluginError("直通上游返回 %s" % response.status_code)
                    block = b"".join(response.iter_content(64 * 1024))
                    expected = stop - position + 1
                    if response.status_code == 206 and len(block) < expected:
                        raise HongguoPluginError(
                            "直通分片长度不足 %d/%d" % (len(block), expected))
                    last_error = None
                    break
                except (requests.RequestException, HongguoPluginError) as error:
                    last_error = error
                    block = None
                finally:
                    response.close()
            if last_error is not None:
                raise last_error
            if block:
                yield block
            position = stop + 1



class _StreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "hg-stream"

    def log_message(self, *args: Any) -> None:
        return None

    def _params(self) -> dict[str, str]:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        video_id = (query.get("vid") or query.get("id") or [""])[0]
        if not video_id:
            video_id = parsed.path.rsplit("/", 1)[-1].split(".")[0]
        return {
            "vid": video_id if video_id.isdigit() else "",
            "quality": (query.get("q") or ["1080"])[0],
            "device_id": (query.get("did") or [""])[0],
            "install_id": (query.get("iid") or [""])[0],
        }

    def _fail(self, code: int, message: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(message)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(message)
        except OSError:
            pass

    def do_HEAD(self) -> None:  # noqa: N802 - 标准库回调命名
        self._serve(body=False)

    def do_GET(self) -> None:  # noqa: N802 - 标准库回调命名
        self._serve(body=True)

    def do_OPTIONS(self) -> None:  # noqa: N802 - 标准库回调命名
        # WebView/网页播放器(如 WebHTV)带 Range 的 fetch 会先发 CORS 预检,
        # 不回应预检请求会被浏览器直接拦截——表现为永远"正在获取播放信息"。
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")
        # Chrome Private Network Access: 公网页面访问 127.0.0.1 必须带此头
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()
        self.close_connection = True

    def _serve(self, body: bool) -> None:
        route = urlparse(self.path).path
        if not route.endswith(".mp4"):
            self._fail(404, b"not found")
            return
        params = self._params()
        if not params["vid"]:
            self._fail(400, b"missing vid")
            return
        try:
            session = _stream_session(
                params["vid"],
                {
                    "device_id": params["device_id"],
                    "install_id": params["install_id"],
                },
                params["quality"],
            )
        except Exception as exc:
            # 把真实原因回吐给壳的播放日志，避免只看到一句没头没脑的
            # media session failed 就去猜是源写错了。
            reason = str(exc or "").strip() or exc.__class__.__name__
            # 空体是成波来的：这里快速失败，同时挂后台继续试，用户过 1 分钟再点就命中缓存
            if _is_empty_model_error(exc if isinstance(exc, BaseException) else Exception(str(exc))):
                try:
                    _warm_burst(
                        params["vid"],
                        {"device_id": params["device_id"], "install_id": params["install_id"]},
                        params["quality"],
                    )
                    reason = reason + "（站点正处在空体高峰，后台已在自动重试，过 1 分钟再点一次即可）"
                except Exception:
                    pass
            self._fail(502, ("media session failed: " + reason).encode("utf-8"))
            return
        raw_range = self.headers.get("Range") or ""
        requested = _parse_range(raw_range, session.total)
        if requested is _RANGE_UNSATISFIABLE:
            self.send_response(416)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Range", "bytes */%d" % session.total)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            return
        start, end = requested if requested else (0, session.total - 1)
        self.send_response(206 if requested else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        # CORS: 网页/WebView 播放器的 fetch 需要, 原生播放器会忽略, 无副作用
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers",
                         "Content-Range, Content-Length, Accept-Ranges, Content-Type")
        self.send_header("Content-Length", str(end - start + 1))
        if requested:
            self.send_header(
                "Content-Range",
                "bytes %d-%d/%d" % (start, end, session.total),
            )
        self.end_headers()
        self.close_connection = True
        if not body:
            return
        # 断点续传式喂流: 上游分片失败(签名 URL 过期/网络抖动)时强制重建会话
        # 拿新 URL, 从已发出的字节位置继续, 播放器无感知——根治"播到一半断流"。
        position = start
        rebuilds = 0
        expected_total = session.total
        try:
            while position <= end:
                try:
                    for block in session.iter_range(position, end):
                        self.wfile.write(block)
                        position += len(block)
                except (BrokenPipeError, ConnectionResetError):
                    raise
                except Exception:
                    rebuilds += 1
                    if rebuilds > 4:
                        raise
                    try:
                        session = _stream_session(
                            params["vid"],
                            {
                                "device_id": params["device_id"],
                                "install_id": params["install_id"],
                            },
                            params["quality"],
                            force=True,
                        )
                    except Exception:
                        time.sleep(0.6)
                        continue
                    if session.total != expected_total:
                        raise HongguoPluginError("重建会话后媒体长度不一致")
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            self.close_connection = True


def _start_stream_server() -> int:
    with _STREAM_LOCK:
        if _STREAM_STATE["port"]:
            return int(_STREAM_STATE["port"])
        for port in range(_STREAM_PORT_RANGE[0], _STREAM_PORT_RANGE[1]):
            try:
                server = ThreadingHTTPServer(("127.0.0.1", port), _StreamHandler)
            except OSError:
                continue
            server.daemon_threads = True
            threading.Thread(target=server.serve_forever, daemon=True).start()
            _STREAM_STATE["port"] = port
            _STREAM_STATE["server"] = server
            return port
    return 0

def _b64(value: str) -> bytes:
    text = _text(value)
    text += "=" * (-len(text) % 4)
    try:
        return base64.b64decode(text)
    except (ValueError, binascii.Error):
        return base64.urlsafe_b64decode(text)

def _branch_one_bytes() -> bytes:
    if not hasattr(_branch_one_bytes, "value"):
        _branch_one_bytes.value = base64.b64decode(_BRANCH_ONE_RAW_B64)
    return _branch_one_bytes.value

# 这份字节原先以 lzma 压缩 + base85 存放；改为内嵌原始字节的 base64，
# 避免宿主 Python 运行时缺少 lzma 模块时整份插件导入失败。
_BRANCH_ONE_RAW_B64 = (
    "V78Qi7edsGL53bizSke+6LO++Uq43ehHSuizuPm+R91hooEEM0U31wQ3YTOBotdFhEq045jq/RHj/YSYtEoR6uBnfeQr20Iv5ELg"
    "K31nL9srL+R94ELbZ33bK+DkL2dCf7VgCTIwiaMJiX8yYLWjMDKjCWB/iTC1iHd4l7obTDeleVAllaQqeiUqpZVQeXqklXolUKUq"
    "pHlQpJWlJXp5KnG3rQ/GSvd0D/dxxq23dErGdA+tcfdKt61KxnEPdLf319rXZG14NcBWBV7O3lO/Ss6/Vt5eBUpT3krOXla/UwXD"
    "x9dtk7JytW1yw5PXx7Wyk7Vt18NyssfXspPDbbXHchlsLK5vuPTJrvQZbyxsybhvya4sGfS4bCy4bxmuyWz0yoRF89ploNnzoMra"
    "RYTZZdrZ80XKoGWERWXayvPZhKCdQV4KFectsNBIPcyt4Xo9zHrQrT1IPeGtPcw90HrhSDs2abP+afHAs/E7/mk2wGn+wLNpO/Fp"
    "Nmlp/juzwDbx+0B9cRnQc31KgpIvFCmD6y+DShSSguspFOsvkkqDKYLh5pZhIM4g4WEg4SCW5uHOIOFhluEgzuaWziDhYeHmIOj1"
    "x/XD8TGPDnGVst4l/Iwx1Yw/c+ftBT/tMXOM1QXnu5PvQ29CbWBDbbtv75NgQm9gQ++7bUKT70Jvu0Ngk216hCLNjBpsvc1seowi"
    "hL0ajL3NInpsGoQiGox6zb2EbI08iaBoJy3/baGXBDTxk10Ek200l6Fd8TRdBJdtk/GhiI0jld+kccOVcYjfI43DpN/DlSOIcaSN"
    "I6TfiJXDjXHvgK14knpXL+2UYuNCAIIC44LtQmKUAgBCAuNi7YIAlNfWqlIV6Rci1ntaKSN2Ss4pStYjWnvOdiPOKVrWSnZ7fCDH"
    "CNdbay+Khj61UyIvGbUvilM+hhkiKXWvuqg1rvwATweDQYz5IIP5AEEHTyCMQSCDBwD5jE8HjEEAgyBP+U4MPOJoF8u84stOaDwM"
    "vBdovOI8TssXDDwXaE7ivAzL4D6sodPtNDuhNODTrD477dM7oazgNO0+rO3T4KE7PjQlutRi7TQtumItJe3Uuro07bpi1CUtNLrU"
    "NO0lYrq6LYHvw8KymYxiwoyBssPvYpkr7qABDQ0rLAErKw2g7iwNWMjIHb8d2S4d2Vi/yMguHb8uHchY2R3IyB2/WB0uyNlmG5vT"
    "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"
    "witW2jV9CSL/k+BXBJFLjmAPgRV6ivPQ7tIK/PrS1vIIjHvqL+VYN4FxYjCBDYmQE0xmB+zyiNN60v4KZXAy4TBfhykK1NKO+/Lo"
    "epLEG5haX94KKO1qmAy4PgkImLxuOOkqDVofwFuWnAra3FqewgsaWJcJaOi6Lp0MOA+aWh7YwpNcPbme7ApoCCjjGEF18VVKZk/5"
    "ba2W81sFCUfcBsXxdXj2RR1R4nBhS0hWchlhQ/XliWNnLxH2mM1lc1FCTR7h8M4p8WCfZY8TtEBfEY3VzeTVGvBiV9tFenT/heua"
    "2EMOjF1B17UQ5czI1BVF51yJtd6UhZpC/4mf5RTVXclEt4ifnvqBipfdRFOgc4yrDJQD8bztWfXDe4SDWcXrebz19Kt0pAtUiAOT"
    "kAuMowNzrFSA5+1VWFgOcgSLC3SUo1OocFBY7g3ihV/lPn1j0PlbDQQjqMNwfHdULZ2hqWQ2IizVeTv942YIXV79YzgNfdPhgmEs"
    "dDzRlZkJZfh7Wz3l1ply1C2UYYQ5AIj1v24k2RA4UYnjMUjxk0u+SFbluQLa7JXDR+1LYvTYILmOFfBvBKmKxAg4lfibZUxClfPE"
    "7+thyqhNbCM2c/9quwPS+6jMEGqjUMBEO9jVdEyIotEFf1oqM/ze3Ia9qvwAasu/0/s2upZUV/vADKJkcMtKXdiEl2x+ufhtQzZF"
    "eqBYNrrWy1EHrSqtQ4GWyBCu0lsgUpAi+MzxB/zuqdfEiwrMz5OT2m5AFmxJO3WD3S/vzIZDsb5V067IqI0sEswU3VyHiQZi0ipF"
    "qI/3E+Lm+x51K6HPK+F2ox/N+uYs3nbCil39Qo5jqvdHECrRzQSKXhcR3ITOKh35oud34yXIwCSO/tWCXepuMN0g3uGAk7+cCfVt"
    "r/eBC22frbyQka9sC72An/WA/SXC1MqMJsmA1Y7CJCT+r/SdvWyTC4E+GCvd08Xdtsc90N3etyoZlpbo5alAkVZAlaqQ5lXqlZVU"
    "kqroleZBtMbdK90a0z0Zt97SKT3cx1ZC5emRlqiUt03KytUOH18Ot9Uey13LTntZ/U4VeCs5eXsVKE05/1qTteHVAF9rX10Py8ke"
    "T9a2T14f18q2yQ05e0/9KlkVeM1rl4FmKxMWK89nE4IWlWlluCaz0bPgvrJk0OOyvSW7uL7h0idnsLEXKYOWEWpnz2sXEWaXzYMq"
    "vLGwJeO60mfN+qfFA+/YpO/MAtvEp6X590DrhSO19jC39iD1hDPrQSlUnLfAdgZ5pu3Ep9n4A8/4p9kAp83G7zC3huv1QCP1hoE4"
    "g4SHm1uEh4Wbg1g6g0gqDaYIUqy/UUgKrqe8DCrFZUDP9e0D9VmGgzibg4SHg1iahzuHgYS+UKQMrisJSg+9CbWB7U6+7Q6BTba9"
    "C73MMVYXnP+0x/7MnbcXxFQz1w/Hxzyi1x+977YJTb6BDb69T4IJDbXtynqX8DM6xFWCop20/DfyJFy2TcaH0nQR6jX3ErKJaDCL"
    "6LFpEDL2NjQzarD16hGK0VyGdsUTTLYS0MRPdrWFXjGKEPZqNLPp4knqXb28A7aLtQsCUAoJjCNWDjfGjZB+jiDGkTZ+D1dUfpPG"
    "DSM2jguJUQoAjAu2jQsBCAq0U4p+jzQOk1bGISNcb6298IEc6qLWuPKn1L1oWSvZ7Y04p49o7TnbpShZSlWkX4hcW6tO+RhmiNS+"
    "KNROibxkKBr6pYzYKTlb72mIo10s8zox8DmJ8zIs81ygAQyCPOUfMAYeAOQzPgWBDAwGMeaDADwd8zgtXzCg8Yqh8TDwXogvOwQd"
    "PIEwDuYDi7XTtOiW6FKXiOnqtlDTtIOH7vjQsLZPsoLTtPtM74SGTrfT7ID7sFGXtNDotuuKtFPr6tKItZRPs/rstIfSgHf8dmS7"
    "YCEjYnW4IGcjd/w0gLqzNASsrAY0NKywrLiDC8tmMooFvg8gY2V3IP+6dP0iI7t0dGRjyg6/i2UKMwZt9takc1YMYFZscg6kY9X0"
    "mjUA9Lme5POcmLnm9/ECNE6feo+Omm1sYlWk1wz0cm70Yg1w1mymV51ubox6T4+aXMTPmAIlUrwnXgBRmL7MxNhGeJ/afxaTfNra"
    "F5+SeEdGkBTbe9uefrwkms5QxANdxr9QAM1cmCaSfJ56F0fY28RzUONVX+nMXMVX6+DNUHODc5jHhQdz9wSDh3PH9Ztzc/Rzh5uD"
    "xwXPXOFR63BUx3HM6FRTx+Nd9wfHmXNzhIOWUopJGVo4klqUGjpKkYpRU2OeUJ6OXk6JIRgtIroE5+W5LBoFIyCKklpIiTlSGpZQ"
    "kjoaipVKWbiIIQYv5hkhhK0s+WCUjfDB8fSFflGhTYVV4KEJRjJ2RIYJMqJ14VWTl/x6ttpIpVDBfaGFTvXxTVGF9qHxfMGUpEu1"
    "/pJ72nCTZGX+54k55HH/i2U6ZJFDi+KVJIqgUvkUVPLJsQJMTLHyVQIUyPk75GVmiZH8c5E4iP1ncWfmsPrIAfBNVRZFpLw1Fevp"
    "kQHghAIghvqROii/haRX3CNXOKTfhyC+KSgj3qe/OYRUkOk1vemlFEelkOkVv0U06SBWhLzdK6c7Q+yRx5xm7E2O5YhJVfHW+wx1"
    "NqMYjOYiMDelzSWEY1fqbV5cVLIn2PCOVdVL+Yrl+fJKidXnVI1v2iZUXuhdsEDYZdLOQ8z/mfJLkL+oBv2X9AckmNHL01Z/JWyA"
    "OEJk2kXnkLt/+Rarmr4Ekf9J8P6pkksE8b+YbTQkHVjhFSt1fWlreQTGPQV2ecRpPWl/g8CGRMgJJrMKgsglR7CHwJiXcqybwDgx"
    "PQVqacd9eXR+PcV5aHdpBZQyOJlwmK/DBgRMXjecdJWcBDR0XZdOBktuLU/hBQ2sBUniDUytL29trQ/gLUtOBZSeXE92BTQEBJR2"
    "NUwGXJ+uB00tD2zhSbyEI26D4vg65sSxs5cIe8xyJCu5jLCh+rNxjKC6+ColJfuijihxuLAJ55R4sM+yx4Kn/LZWy/mt+LK5KKEm"
    "j3AHuv/CdU3sIU9vykJNof/EWmTqiqJzrsRyWqCviMbqZmbGrqDrWohyok9P/UDFy269ag14savtIsRyiuquZKJb+sGs4vU83no5"
    "wPP2KiwsByrIBcbRgTlWgSnQOcZVBsrJVTrSBSrEgS84KCz3BvHCwnje9qz64T1UgsUFOsrRKZaWztBUMhsRTMEwFjqe6Mpwr/4x"
    "nIa+6YZyn74x6Pytruq8nf5xM4ScTDnqFsowwiqCEdRhOL4764Qy/L2tnnLtJV8kq/JcAc1URWIEnEr8AmyQXMcK+DcIAMT6XzeS"
    "bHr2yuGj9iUxuTBl1Ca2EZtJnKjE8Rik+PUyJqHKeeL3v2o6JkTR6IIGG11Lqqt9YH1VfgC15d/p5n+13QHpfVReLZUZfm9uw5tL"
    "Nr9c/LYhbAi1UShgoh1CUTK4ZaUubEhkCFfpLRApOm03IAu2pJ3Ja+JFBebnyeUiPVAsG13rVBF85vgDfvcW36ppV2TURsuog1aV"
    "1qFA2MHul3dmw6FncfN9j7qV0GjHMdX7IwiVIRZvO2HFrn4DCWaKbq7DRPOVcLvRj2Z9cWeVjnzR87sJMWmVItTH+8JmAkWviwhu"
    "V8DJX86E+rYTwP4SYWplRvrIV7aFXsDPwRJkYBJH/2rI+8CFts9WXsBX+s5etsmF8C51N5huEO//ZMBqR2ESEitLS/TyVKBIHlrj"
    "7pVujemgSipJVfRK81sfjJXu6eJuSqBKVUjzKvVKK6Hy9EhLVIzjHuhu71uV44xbb+mUHu6cvax+pwq8lduuh+Vkjydrr8na8GqA"
    "r7Wv2yZl5WqHj628vQqUppx/vJy9p36VrAonh9tqj+WuZYYnr49rZdvk3zJck9noWXDni5RBywi1s1hc33DpkzPYi+a1y0CzlQld"
    "WTLocdnekjPeWNiScV3ptJXnswlBi8qVtYsIs8vmQZh7oPXCkVp7Z9N24tNs/IG8FCrOW2A7g9Jm/dPigXdsoFt7kHrCmfV6mFvD"
    "9Xqgkfx3ZoFt4tPSd/zTbIDTZuNfJJUGUwQp1sMsw0GczUHC+uIyoOf69oEtw0CcQcLDzZUoJAXXU14GJV8oUgbXlQRBwsPCzUEs"
    "ncJBLM3DncNAY+YYqwvOf9qG3nfbhCbfwI/rh+NjHtHr34fehNrAdicZf+bO2wtiqiplvUv4GR3i3naHwCbb3oV2394nwYSG2hj1"
    "mnsJ2UQ022guQ7viCSZFmhk12Hr1CBJB0U5a/ht5m0X02DQIGXv0GEUIezWa2Qgu2ybjQ2m6Lwlo4ie72kK/ESuHG+NGSNuFxCgF"
    "AMYFRyq/SeOGERtb8ST1rl7eAStHEONIG7+HEL9HGodJK+PGxdoFASiFBMXGhQAEBdopU7Sslez2RpwUp3wMM0RqX1WlKtIvRK6t"
    "jhGut9Ze+ECsR7T2nO1SlLRSRuyUnK33XnVRa1z5U+p9aqdEXjIUDYMABkGe8g8YxXmcli8Y0HgOBoMY80EAnnjE0S6WeZ0YBg8A"
    "8hmfgkABgg6eQBgH89CcxHkZlnkundB4GHgvxJenwUN3fGhY28WoS1podNt1WEOn22l2wH2pxdppWnRLdEJZwWnafaZ3wKdZfXba"
    "Q2naS8R0dVuoaUraqXV1acRaVhpA3VkaAlY6kLGyO5B/XYeFZTMZxQLfkTt+O7JdsJBBAxoaVlhW3ANlh9/FMoUZfrE6XJCzkTux"
    "fpGRXTo6snnNGgD6XE/yN7Eq0msGejk2p0+9R0fNNrA2e2vSOSsGGk7MXPP7eAHNTjc3Rr2nR3orNjkH0rFqK3qxBjhrNtNJbCO8"
    "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"
    "wdNr91u45mqONZToM1bQJlaMNSQy6pfQht3O9xSOgEJr9btqW+TC068rR2ayXWu8zp/ObBK2cfEqR2pcs62/Z/Juts0Qcs2fZl6v"
    "a7C9K0e/Z15HsmmsK2y2zXMR8p7Ons5wtRHO824Rt8Sv9OVLWmoLPKPJU2aetMRL5vcRW62colE+y2dqC6/kE0v2WbXEWK3kx/dJ"
    "EreJFgA7eTK1Wwk8Z1LKa5+ivWyZ5a5b6pctBhltHppc2G6Z6Vuuv5Tl2W2aGB1eLAblWr7or5dtmZXlWpqt679sbZosXhzaBRkG"
    "GV2YHC7abdfbHiRG3ZkZm5b7SvBuGo7aHpjdRdUbJyOs0iKr8AHKJN7Vm0UZ2x4aJ94dRJnV26/SAvKpIMgjyiPz0aoAIqz21jRI"
    "JyZFBo98gRxGJk6bJVqaA6u90lEDOjiamwuWW1IBv5qr0SVa0lEBW6qZvyY7OJYLmgNam1ibCzqalwM6HSVeE6lqQF2nfrIvnoOK"
    "myVeQ2moHl0Rmi+Csp+Lp34TaRxBqV4lXl4RaVyrQh0lL4Kmip+bf7J+souDnqeaLwTtSSLZQNcBox0jPFCaLFe1cVk4r3R4jFc/"
    "mCBQLqMdjTl3WKx4tHF5jDlzrVh0tDyYoC1TVh8jHCMsm1CiVT/WkM+7rx6Da4ieT/VkJecwVlvdVyru1w56TDj5i16DTTXNuowF"
    "WXdnC1l8tP7Q5Q5ib9ops+HgduN2Km+y2eFgZFjMdc8vpZG7J8Zk5b2cCLUQPk96E22A3/e2YJv+HEQe/XLenBVVo2yATRJ6PxO1"
    "gFZybt4Hmz80Ie89XCV07S+c09UD0Ji5W7V9q2AGPbeeIqChLfgrscOB56XS3znaUopK1kPy6MAJNvmnd/bPfMGVdse1vkoAbrfg"
    "qqsorwH07F7cKaVTf1x/1OkuVazzQol9kuvFiM/Nkst44oVPiYt9gs/oRcmSodsPyNXLXjiJz5KL7XXCSK/z7H4k1VlcKdlcVImP"
    "HG4ZblnZjF+ELCFM1+qyf+guJ+Fy2LrvLkyXjrXRy1v4yGxZiVyEHy7Z7C7hQrffeiiOLNlsiV9ZFHxxSPx0Ad+W0Zb8dHhBDH9z"
    "28sjdGZxX1sjZMFzdn/bqWooAhFP5MDvtONtoGtZPXtfI9R7xmNxw/e+GrNjzzGf2pNdsxvRDwbmcYYfaLFi3v+NQS5Qg5WdTl6D"
    "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"
    "aPKUmSst8ZL5fcRWQXabJkaHF4tbZbmWZuv6L2UvW2a565b6RpsmixeHdkFmuZYv+utlW5tBRhcmh4t2dotBRpuHJhe5W2b6lusv"
    "ZfIIq7TIKnyAtsaJdwdRZvXG9bYHiVF3ZsirtIB8KgjyB4l39WZRxrar8sh8tCqACOOm5b4SvJuGibYHZndR9cbWgA6O5uaC5Yl0"
    "VMCWauavgb01DdKJSZHmDo7lguaA1pZUwK/manSJDtbmgo7m5YDmI18gh5GJ01SJlubAaq90n+aLoOzn4qmJV0Qa16pQR1dHiddE"
    "qhpQ7IugqeLn5p/XRBpHUKpXiYuf7OKg56nm5qmf7IvnoOJEiddQGqpHV8fVDyYIlMtobR5jzlwrFh0AQXuSSDbQdQgPJmjLlNXH"
    "XGPOHRYrHm0PxwjLJpRo1dVoxwgPlCbLY21cFs4rHR6THhNO/qLXYMNCFh+tP3S5mjXk8+6rx+Cd2Jt2ymw4uFlNsy5jQdbd2Lid"
    "yptsdjgMoudTPVnJOYPVVveVivu10fe9LdimPwctG2CThN7PRCQZFnPd80tpD6CVnJv3weaoR7+cN2dF1TtNyHsPVwldwu6JMVl5"
    "LydgLYTPk95EG/Zw4Hmp9HeOX4JN/umd/TPuC+d09QA0ZkBwpd1xra8SsJSikvWQPDqA2y246irKa+1Wbd8qmEHPrKcIaGgL/kpi"
    "s+QynnjhU07o9gNy9bIXHz27F3dK6dRS4rPkYnudMORin+AzelGy1+s8ux9JdRY81x91uksV67NQYp/kejHi00m4HLbuuws2W1Yi"
    "F+GHS1tKNhdV4iOHCrtLuNDttx7ypWNt9PIWPoUjSzZb4lcWS4ZbVjbjFyFLCNO1uuwfuvbWCFnwnN3fzzvteBvoWlYlXxwSP13A"
    "t9ze1wj1nvFYcKoaikDEEznM8L2vxuzYc1+0JT8dXhDD19z28gidWdx/p5PXYAhg9fbA10Rk7/anw6f2ZNfsRvT0Y6WTfwtg1JN/"
    "Y2DVCPSngK2Y4XsEnlmYgXmc4QdarKX3f2OQC9RglXB4z6JOsg0TuFR9YWbxR7tEE2BWZX3xDrFxeJdMos54l6CyzU4OcfJ/RRO4"
    "ZFVhRfO7VBFkYX5xDJWgek/Osq87Egzaryv6MSeOtcLNVKAVhb92TwDg9vorOhKsr9sPEqzbKw6u+ztij3vozRtkUD6TdDP5fTHw"
    "Ovqv2xOsDyriAlsrIGZHHN2Do8qORjG6EwerwKKmPyccRgBb42YjKsxvg0hlqjl4Jj8HqxCno8IHJxOjqqTDPgAf4iJaZytEdiZN"
    "eKNLGb2J3noJTYCWP98+iU54gQqVvxolTXRKoXtNdKIbeUu9JsDHM6xQN7iAPZXfeomCTgglvXaiT0h5G5neESwCEXuk03zHNxLu"
    "8fZ+99MQxu818rTeVIvipqXMEZgCeSwSp93yNvbTfO/FE/bzfsfT7BE2VLfipoimzdwYCla29oMxa6ggrg8G0DoYlgiEBr2oqqMh"
    "7FEe5oIARlYa9jO3gmkI36lylHhZeJ9y3Hl5l1icq5zCslXBXsxLL1LjpV7+MdNcuG5KTGIOcLhyXExuYkoMfLixRYgy6YQ+0w+V"
    "mR2M3Q5IcFy4Ym5OcAy4bl5gTkpT0y9e4v2lMhFQ4Tiy238oDtZFnctwqRHVEQ7KRHGdq+2upA4lKqHN4RCwfzjaK1GonRMO1nFF"
    "yROq1UUNcsmcpO4mog0pza2CHCTX6+UmLpuP+aLFv0pAjEGbx/u+okkvJh4kg+Tq1SSD6CXW5y4eS6BBm4+9+sZBS4z5mr/Gox4s"
    "gugl59YntHAP1m1PVOu/miJ/51ywXJhev+YgX3yz6VRzD7ZMbNcPtmxX103ocLB8X7+aXiDnX7OYIr9e5Hxz67RsD07UVYMQYHwz"
    "L+kF7pTJKwdQkseXxe4EyFMqkygB9H6cCBaoYIAw630vBRN+A8C+BpYkw8eSl8nvUAYo9CqdFHwIqgBwLuPvS1wWwha5LxCuzeH5"
    "ufsWrS3MEeLDFC7jc15K7ONzShTuX8Is4RH6FrnPLaz64rkvFM2tES7DcErgX+4XsxuSMEt9Spepv5VgHZTuzLzNqR+UlGLtAHtk"
    "IK83p3mSsEtJM3+WG+xgzam/lZYcze28laiXHmBkAK+nITd7eC8Rmu58ZAnH0oJvdKzfkO+D79Kub9x0kMQLE5ouZX3smi59CO9k"
    "xRN9AADQgg/uo+ySg2/Q3qx3E8YvfZhm7QjJHPWDvnfwRIorooIT6hguKi6KE6LqgBtG8Rz1y3S8g/XLvPOAdkQdjOLi6+ZDH4cv"
    "GiqiiusQghxFybz3d4DyyWyRSpg4D09hiM7SIXeuiSW9xlnP9b3ZTA1vkco4m0iRypgMSzhPbdu9vcYl9c1ZvdolzcX1Wb9vTcmY"
    "kDpLDDyW0933DvgiKk37tOlXHkxMTyrp+1S2HSP4ltM9DvTe0z32+t4PIJQftE0qTVf66E0eTPsoVeq3liM89tIN3PuM0SbqNzCW"
    "VEKG3c73FI6A02v1u2pb5MJXlNAmjjE26CaONZToM1bQwudq9dNbaLtqwdNr91u45tBWjDUkMuqXZypHalyzrb/ObLbNcxHynm6e"
    "znC1Ec7zvK8rR2ayXWtHZl6va7C9K/HOn85sErZxn/Juts0Qcs0rv2deR7JprK20xEvm9xFbW4kWADt5MrWiCTxnUsprn1oRt8Sv"
    "9OVLxK/kE0v2WbWeags8o8lTZgucolE+y2dqt1it5Mf3SRLlbpnpW66/lBltmixeHNoFbQYZXZgcLtqXvWyZ5a5b6pnlWr7or5dt"
    "2C0GGW0emlwG2W2aGB1eLGyV5Vqareu/J9oemN1F1Rsjr9IC8qkgyKzKI/PRqgAiGdfbHiRG3ZkeJN7Vm0UZ246blvtK8G4ayiOs"
    "0iKr8AHbGifeHUSZ1VElWpoDq73Smzs4lguaA1o6WJsLOpqXAwb21jRIJyZFWlIBv5qr0SWbj3yBHEYmTlsDOjiamwuWJtJRAVuq"
    "mb8RJV5DaageXbIvgqaKn5t/L36yi4Oep5pdHSVeE6lqQF4TaRxBqV4lm6d+si+eg4p+mi+Csp+LpyVeEWlcq0IdjLVxWTivdHgj"
    "PJigLVNWHz8cIyybUKJVAQTtSSLZQNdxjTl3WKx4tFejHSM8UJosHVc/mCBQLqO0eYw5c61YdA5WW91XKu7XdmJv2imz4eBg43Yq"
    "b7LZ4WvWkM+7rx6DZzXNuowFWXcwiJ5P9WQl5016TDj5i16DDgtZfLT+0OWAtRA+T3oTbT+AVnJu3geb7TQh7z1cJXSRZFjMdc8v"
    "paMe/XLenBVVCLsnxmTlvZxE3/e2YJv+HLVsgE0Sej8TsZ4ioKEt+CsAwZV2x7W+SgFut+CqqyivuS+c09UD0JjAUopK1kPy6Ldb"
    "tX2rYAY92sOB56XS3zl8CTb5p3f2z89CiX2S68WISInPkovtdcJcr/PsfiTVWX/07F7cKaVTkot9gs/oRcnzXH/U6S5VrInNkst4"
    "4oVPOKHbD8jVy14uIUzX6rJ/6CjsLuFCt996FI4s2WyJX1luKdlcVImPHMiXjrXRy1v4LBluWdmMX4RMJ+Fy2LrvLtlsWYlchB8u"
    "X3PbyyN0ZnFxe18j1HvGYzHD974as2PPlnxxSPx0Ad/AqWooAhFP5H/Rlvx0eEEM21sjZMFzdn8977TjbaBrWZXe/41BLlCD04+V"
    "Tv4tgFEBtmKG7xF4Zg+f2pNdsxvRTv6NgVUj0J9iBuZxhh9osf+dTl6DIYDV2gNfE5G925/GMVSC6j05yzvExuFdMok6yf8VTeCS"
    "VYXvEk2AWZX1xeFdgso2OznEFc3vUkWQhflUwuE9izrJNk3gUvWFmcUf6Oi/bk+wPqjor+hIsL5uP4k97qE3b5BBVxT+2j0BgNtI"
    "sG6vOLju7/tM0s3k98XAv+5IMGi/rujGnDjWCjdTgQF8iItona0QcBgBbI2bjaib/BysQpyOCkwcrAKLmv6cMb8NIpWp5uAcnEyM"
    "qpIO+4gLbK2AmB1xdg+OKjsaxeiU9NqJPiHlbf1qlDTRKYXuAh/PsELd4AJ++yQ64QUqVDTRiW7kLfWa9FR+6yUKOiHamTThjS5l"
    "9CR66yU0AVr+U92KmyKaNnPTelMtipuWMsjb2E/zvRdP+91PQxi/18hHYArksUicdtjP+x1Ps0fYZnpHsAhE7JFP8x3fSLjH23EK"
    "y1YFezEvhbBHeZgLAhh+p8pR4mXhfVoiEBr0oqqOWGnYz9wKpiHKceflXWJxrmEoWNnaD8asoIK4PhhA62BMTb94ifeXyvLhxhYh"
    "yqQTOSDBceGKuTngynExuYkpMftMP1RmdjB2wTHgunmBOSm/SI2XevnHTHHhuikxiTnAkrqbiDakNLe3u5I6lKiENqN2TjhYxxUl"
    "Vkc4KBPFda6FQ8D+4WivRE6oVhc1yCVzRECF48hu/6E4WBd1LsOlRniwCKKXnFufv5h4kAySq1cvgQZtPvbqGzEGbR7v+4omkAyi"
    "l1ifu3gGLTHma/4ajwhykFyvl5u4bT7mixb/KgHNrdOyPThRV6dTzT3YMrFdw/J9/Wp6gZxiev2ag3zxzT3Ysl1dN6HDfc1iivx6"
    "kfPTwj1Ytz1Rrf1qivydc8Fy0Kt0UvAhqAKiBND7cSJYoPsNAPsaWJIMXha7EyBPqUyAAcKs970UTBxLXia/QxmgDEKA8c28pBe7"
    "UyavHEBJHrgMwymBf7lfD1O4jM95KbGGR+hb5D63sOfuW7S2MEeIjM8pUbh/CbPoi+e+UDS3RsO5jL8vcVkIW+S+QLg2h+eRAbye"
    "htzs4QHskYG83pzmsIM1p/5WWnLzNqd+UFKKtUjCLiXN/FluNbfzVqJeeoDObkjCLPUpXaf+VoJ1ULozTBi/9GGatSMTL0xoupT1"
    "sfYBAEALPriPDr5Lu75x00FouvQhvJMVT7FLDr5Be7Pev0RouvORJRxLC77RsX5DvnMUJfPe3wHKGsVz1C/T8Q4yiouvmw99HKi4"
    "KE6IqgNu1C/zzgPaEXW+aKiIKq5DCCVz1A/63sETKK6ICk6oY7i8NSVjQuosMTE1vEUq42wibff2GpfUN2eX9BpnPdf3ZkUqYzIs"
    "4Ty19mqXNBfXZ/0ls0UqYeI8PIYhOkuH3LkmW47w2Es3cO+P4FtO9zjQe3/QNqk0XemjMD2ppO9T2XZO99jrez+AUDZ5MO2jVKnf"
    "8FhOd9874IupNO3Tpl95MEJbMdaQyKhfX1FCmzjG2KAKn6vVT2+h7U+v1e+qbZELmzjWUKLPWEGrBU+v3W/hmjFGm6jfwFhSChl2"
    "O99TOAKu/J55HcmmsfG+rhyZyXatxTt/OrNJ2Ma7eTrD1UY4zxyZeb2uwfauf8q72TZDyDWeqRypcc22/jqz2TbPRch73GK1kh/f"
    "J0lpRdwSv9KXL3mqLfCMJk+ZiibwnEkpr30Sv5JPLNln1S1wikb5LJ+ptdISL5nfR2xuJVoA7OTJ1LJVlmtptq7/X/ayZZa7bqlh"
    "txhktHlocrcZZHRhcrhoZZZr+aK/XrYYZLdpYnR4sZa7ZaZvuf5SZLRpsnhxaBdva5x4dxBlVmZcb3uQGHVnOG5a7ivBu2mwKo/M"
    "R6sCiHuQeFdvFmVsKI+wSouswgecaHtgdhdVb4+8SgvIp4IgmkhHBWypZv4Z2FvTIJ2YFG0+8gVyGJk46GBtLuhoXg5oSQX8aq5G"
    "l24N6OBobi5YR5VoaQ6s9kpt7uBYLmgOaJR4RaRxrQp1dXWUeE2kqgFunvrJvngOKr74yS4Oep5qeE2kcQSlepX6ab4Iyn4unkWU"
    "eA2loXp0yb4Imip+bv7R5jHmzLVi0QcQtCeJZANdXI12jPBAabL9cIywbEKJVsY15txhseLRdlz9YIJAuYwx1sZl4bzS4YzwYIK2"
    "TFl9Oyxk8dH6Q5euWUM+7756DMMgej7Vk5Wcg43bqbzJZoed1TTrMhZk3TbpMeHkL3oNO1htdV+puF/bib1pp8yGg9SyATZJ6P1M"
    "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"
    "uTWgg6O5uWC0+cgXyGFk4qIlFfCruRpdHVWipTmw2itrIh0VsKWa+WRgb02DdGJSJ/siaKr4ufn54ie7OOh5quqn+SIo+7l4uHnq"
    "J/viOajiNZHGEZTqVRVR4jWUhurRUeIVkca1KtTU1VHiNZGqBjHCgwnaMmX19cMxwrIJJVracfWDCQLlMnI12jHCA6XJG9eYc4fF"
    "ikfHWBuXhfNKh0ebx5gz14pFHUDQniSSDXRuJ/amnTIbDg42bqfyJpsd2KTHhJO/6DUOg+j5VE9WcndW06zLWJB17WC11X2l4n7u"
    "sJDFR+sPXbhmDfm8++ox+QNoJefmfbDXThPy3sNVQkH0fW8LtunPibB7YkxW3ss16tEv581ZUQZYC+HzpDfRUcsG2CSh9zMaSYbF"
    "XPf8UgQQXGl3XOurGuB2C666ivKjPRx4Xir9nXO7Vdu3CmbQDiylqGQ9JI8S6ykCGtqCv8yXYJN/emf/mfvCOV09AI11+wG4e9kL"
    "Jp/dizukdOuOnzvr3aSLjnSf3Y47pOt0i3ja6a+xmg3neK8N2rHp55p42uevsQ2a6Xivmtqx5+kNRLfh0XWXFBFE0RS3deERl0lt"
    "oDiSju87STjvbZKgO44c7Nvp40ncDRzp3Ozj2w1JHOwN6ePcSdsc6Uns4w3b3PvCROnkYWkhKv3etwVVtigqt7b9Bd4oVYrGpqvp"
    "bbw9IxHBlsIVRO7lMO/4r33TNpBvxyHrPiLKkCEib+vHyj7Maf/vft9IfkLU7IIKdAYFQoIG1ArsBXRC1AWCCgZ07Ji61o7YIhbn"
    "mI4WutjW5yKYuueO2BYi1piOIrrY59YWPkFOHIKLjBE+HIxBgk4Riz5BERyCjItOPhyLQYIRToy7Fq/D3e/A3rvDwBbdr97vuxbe"
    "w93A76+7w+8W3d6vwBBA23c3ofv0AfzFASbHdi0BAXb8JsUtxwH8LQEmdsfF3uVs8lzVQ7Te8kPlXGy01WXzajGBgzrDZTE684Fq"
    "w4PtsiovxdsDmu0vA7LFKprb7ih3AMaxHgDuAB4oxncAsRKtybc58WxxXKvuJrXYT+1cJk+rte7t2G0qbhx2KunUyrZVJtPciBHK"
    "Joi201UR3Mq2ESbTiNxVyibcttMRVYhI6RVgClP7Zkhg++kKFWZTSOlmYAr7UxVIYFPpCmYV+6RUJ2gy/WZcwjSkYJZHyrrCYMo0"
    "lqS6R8I0umCWykek0vjI2oKr03PS2tP4gshzq7Skse4msz2PtO49pCaxj7Ol9ZYqjIXaIaUq2vWMliGFpfUhKozahZZt8AdeX1JE"
    "ABc1y3Hs3Cv853Z1ar6P/Msf6DQFFcFvPh8Fb+gVND7BVVxIXXsJGO8RXQ9psDkD1UwSCkVfHog2TEWIEl8KNh5qNafJuqIONz7u"
    "ZgdHwWtgPgdr7kdmYME+7mAHR2vBZhFz0wGN78tdEQHLc43TXe8Rc10Bjcvv0xEB73ONXdPLOHXbGuvPJOg4GiR169vozzh16Brr"
    "JM/bOBrPdevo2yQ4aYkSyyNwuzgScGnLibsjOGm7EstwI4k4EiNpy7uJcNsa8scxI9fN28fXGjHyzSPbGs3HMdcj8tvHIxoxzfLX"
    "yTnynNW7mPPJnJg51fLzu8k585zVmLvyyZy7OdXz8pg5fFIanScJATkaCXydUgEnOXwBGp0JJ1JJc+z1JiJqYPv1jtM4SVio+9NY"
    "9TiOqEn79ajTOFhJjvvTSfU4qI5Y2dDyJD6FxDzZJMTQPvI8hdnQPCQ+xIXy2SSF0D488sSS1vN5PqCc1JJ5nNY+89SgktbUeT6c"
    "oPOSeaDWPtTznK3voNXb7KZCrdWm79ugQuyt70LV26bsoK3V7O/bQqCmgbuOweYM26CBwdu75o6gDIG7oMHm2wyOgcEMu+agjtug"
    "E0O7cjCh6aC7oRNyQ+kwoBPpu3KhMEOguzATculDoTbq5lm2oA/Q3L9WXBbpAHzcXAC/FlZ86dy/fFwWAOlWVvv9grIz2RFWgtn7"
    "sv0RM0W4qvCCeNpdRfDauIKqXXhVFhSXvQtUMlWXVBa9FDILVRYyl71UCxRVlwsWvTIUVEB69wCxZ/senL+HJqf39zGcJve/p4cx"
    "95y/MSan9/eHRs2EJpTnoNFGJqDNlITR50bN0SaUoOeERibnzZTRhKBlJTSgrF420mWgNiWsNNJeuZqE/LrfXki5/F6auoRI3+vI"
    "KwhykeE76wjhyHIrO5HryDsIcuGRK+sIkchyOyvhmOqBH9dpOoyYHzrq14GMaZjqjB/XOmmBmB9p6teMgTrknNdkI4alMORkpZwj"
    "1zCG5JwwZCOlhtfkZIacIzDXpZDyjaSHvtWckKTV8oeNnL6Q8pykh9W+jZCkvvKHnI3VnS3rRVbf83WdRfMtVut1350tdUVW89/r"
    "nUXfLVZ16/OpgghC9RksaalCLIL1CGkZqYJpQvUsGQipQhmC9WkILBlYVp2DZhZBGZ0WWINWQWYZWEGdgxZmVhmdZliDQVYW5T4B"
    "+y5W7YLl++0+LgGCVuU+gvsu7VYB5ftWPi6CAe1tvYL+YS/v4m3+771hguIvbb3i/mHvL4Jt/i+9YeKC79ZbQVm7IlWr1llVW7tB"
    "qyLWW6tZu1UiQdZZIlu7q0FVcqH/Z36mdMByZ3Shfv/ApnKhwGd+dKb/cmemoX7A/3QN0IBMNjwCgw1MAtA2gIM88hAlPpfCW/6p"
    "hRq7tfOlaR0I5igXwNMFHSjTCBfmBcAdCAUoF9PA5h0owAgXBebT8cp36PC5QRPeVSAocpjF4vz+nv4rm7e6hye82LRDMaDmhe6g"
    "Sy2bOeagm4VL7jktJuJH1O1kX4lH+7AAgLlm2WTEgz2ic3EBZD1xxKKDAXNkxAE9onFzg2Q9c8SiAYNxb6ZaR1Dkde5vR3WmUFru"
    "5G+m7kdQdeRab0fkplDuWnX7R75wT0jBtftwwUdPvrVI+0e1cE/BSL77cEhHT7W+wfa8O12xdnPrTiaqt5ekNv1OtzYml6r9pE4m"
    "/beXNqSq60qjYrneU9rN/Y7BggeuNRy0OemTyuQTAAA4WHDiHoNTbMpTgEzO2BqI0oXJJjtB9MJr/S2ILmHPtBYtQPnBs55rGTSS"
    "2kCXlRLfthkiM65KACowKnHkIv4myUDT65HvtOi/29kEG4Fn7YuHHp5qOrgxc88tJXCeM0hur0dJJhQ4fhwCnREdFomYEJnlsxvL"
    "P2QeRs1FQXVw+PQsNlnANdsPwN3LXjCp7HbcIV2nW/x7bdCOTT/XxOxe3CGlW3f8005/jdVsOMd71dSOPU9vwNxZ7yZddKT70z5/"
    "jW3QTMe6DY+uu6SIIMJ5b5ME3XFMSOdmH99uSOKKpritC4+4JGDfTh9P4m7gSE9iH2/Y5uZqA8WRdHzfSWBvSB/nTtrmFyZKJw9L"
    "C9k0Nl1Nb+PtUYd5x3/tm7Yp6fe+LaiyRVGJCLYUriByHwwReVs/VvaBubXtL/BGqVJ8Ow5Z9xFRhk77f/f7RvJjoi4QVDCgYxd0"
    "tNDFtj4XwaJmF1SgMygQ1LV2xBaxOMd0FNHFPre2wBI0oFZgL6AT1D13xLYQscYJcuIQXGSM8OFYDBKMcGL0HQa26H71ft/hYAwS"
    "dIpY9LV4He5+B/beHX636PZ+Bd4JiuAQZFx08rXwHu4Gfn/dANq+uwndp4fgbwkwsTsuDpYfKudio6324C8OMDm2awkuZ5Pnqh6i"
    "9YvRmQ9UGx4sCLDjNyluOQ6bV4sJHNQZLpdVeSneHtBsB/BAMb4DiHVadTepxX5q538ZkC1W0dxuaE2+zYlni5NTceOwU0mnbke5"
    "AzCO9QBwMnlarXVvx+a2rTKZ5kaMUDbhtp2OqEJUAttPV6gwm0I2QbSdrorgVkqvAFOY2jdDAptKVzCr2Ee2jTCZRuSuUko3A1PY"
    "n6pApTpBk+k34yKm0QWzVD4iFdaexhdEnluVpiEFszxS1hXGR9YWXJ2ek3XvITWJfZylBlOmsSTVPRIljXU3me15pK23VGEs1A4p"
    "gz/w+pIiAmi3q1PzfeRfPlXRrme0DCksqFmOY+de4b8oeEOvoPEJ/q0PUWHULrQsQKcpqAh+8/niQuraS8B4rypClPhSsPFgcTc7"
    "OApeA/PoekiDzRmojqs5TdYVdbhRcQc7OFoLNvOSUCj68kC0YTlYcz8yAwv2mJsOaHxf7ooIeJ9r7JpejtEgqVvfRn/GCFiea5zu"
    "eo+p29ZYfyZBx9F4rltH3ybBmOsKaFx+n46pQ9dYJ3nexklLlFgegdvFkRhJW95NhMM+vtaIkW8e2ZGAS1tO3B3B1pA/jhm5bt4+"
    "HtGIaZa/3knblViGG0nE1mg+jrkekd/Okees3sWcT+bczamel8dM0Ujg65QKOMnmxMyplp/fTeGT0ug8SQjImmOvNxFRA0vOmees"
    "xtyVT+EL0OhMOJHKr3ecxknCQt2fTqrHQXXE2iYhhvaR5ynMn8aqx3FETdqGlifxKSTmySYphPbhkSfOr0edxsFKctyG5iHxIS6U"
    "z7Sez/MB5aSWzAO19qGe55StNn3fBhVib8zjtPaZpwaVfQet3mY3FWqtZn/fFgI1bbSmzvPhBJ2XfReq3jZlB23cdQw2Z9gGDQxm"
    "2DUHddwO3Q2dkBtKhwEM3t41dwRlCJ0Y2pWDCU0H3YWZkEsfCgXcBQ0232ZwDJ1I35ULhRkCUTfPsgV9gLb+5eOyAEi34hLM3pft"
    "j5ix/rXiskgH4OPa7xeUncmOsILXxhVU7cIr5gL4tbDiS+fCVYUXxNPuKrKguOxdoJKpulyw6JWhoKr8PTQ5vb+P4bqksuilkFmo"
    "0rsHiD3b9wD8jTE5vb8/5LKQueylWqCoNLn/PT2MuedqJjShPAeNNjI5b6aMJgQ1A7UpYaWR9ioyAW2mJIw+NyuhAWX1spEu5ffS"
    "1CVE+s5qjjahBD0nNNUk5Nf99kLKR15BkIsM31lHiESW21kJX/zQUb8OZEzDRwhHllvZiVxUD/y4TtNhxPxIU79mDNTBR95BkAuP"
    "XFlUZ/y41kkLxOe8JhsxLIUhJzPkHIG5LiUkrZY/bOT0hScr5Ry5hjEklG8kPfSt5oQk9ZU/5GyshueEIRspNbwmlOckPaz2bYRs"
    "WS+y+p6v6yz6brGqW5/vFWIRrEdIy0gsmm+xWq/77hVEEKrPYElLFcoQrE9DYElsqSuymv9e7xVME6pnyUBIwLLqHDSzCMroNMMa"
    "DLKyyN9v93EJELQq6LTAGrQKMsv3Cdh3sWoXLN+38nERDGgvwArqHLQws8r3Edx3abcKKOsV9A97eRdv83/pDRMXfG/OqtraDVoV"
    "sfN/7w0TFH9p3grK2hWpWrXOEtnaXQ2qsusV9w97fxFs3lrN2q0SCbIL/T/zM6UDljszDfUD/qeTYBKAtgEc5Gk7owv1+wc2lYAG"
    "ZLLhERhsLdTYrZ0vTUsLBT7zozP9l4co8bkU3vKXQDBHuQCeLuhAAUa4KDCf7q4CQZHDLBb3QJlGuDAvAO5XvkOHzw2aiDzhxaYd"
    "igE9QChAuZgGNu/39/Rf2bzV5S90B11q2cwx2ocFAMw1yz7riSMWHQyYIwfdLFxyz2kxIx7sEZ2LCyDrmSMWDRiMIxE/om4n+0o0"
    "Iw7oEY2bGyQz1TqCIq9zfzsiN4Vy16p7hws+evKtRdo7qjOF0nInfz/yhXtCCq7dh0M6eqr1Dd4zdT+CqiPXej+qhXsKRvLd593p"
    "irWbW7cy6b+9tCFVde53DBY8cK1pMlG9vSS16XdXGhXL9Z7SXgDAwYIT9xgEurUxuVTtJ3WgzUmfVCaf4GJTngJkcsaeprVoAcoP"
    "nn2U+LbNEJlxrUCULkw22QnSXMugkdQGuvQ3SQaaXo989xde629BdAmjAlCBUYkjF1FF/93OJtgIpEFyez1KMqGYxITILJ/dWE5r"
    "Xzz08FTTOfHjEOiM6LDAw6dnsckCroGNmXtuKYHzxCHzMGouCqr7fgDuXvaCSd334g4p3brjZ6umdux5egPet+MO6Trd4md2+mus"
    "ZsM5nvb5a2yDZjqea4N2bPq5Jt7OejfpoiPd5214dN0lRQTRNMVtXXjEJVF6Evt4wzY3R857myTojmMS+3b6eBJ3Awd7Q/o4d9I2"
    "Bzo3+/h2QxJHGyiOpOP7TlIwUTp5WFrIvr/3bUGVLYpKiMjb+rGyD2Sx6Wp6G2+PokSwpXAFkftI23HIuo+IMuTMO/5r37RNOa1t"
    "f4E3SpXK2v+73zeSH3M1u6ACnUGBEKOILva5tQWmdYGgggEduxCutSO2iMU5pu65I7aFiDWmo4UutvW5CKagAbUCewGdkJATh+Ai"
    "Y4RPB2OQoFPEog/wu0W39yvw7sdikGCEE6MPxetw9zuw966F93A38PvrrjCwRfer9/vuUASHIOOik0/Q9t1N6D49BH9xgMmxXUsA"
    "jM58oNrwYFl/S4CJ3XFxADmbPFf1EK13vFpM4KDOcNn8UDkXG221t4Adv0lxy3FArMpL8faAZrvLgGyxiuZ2+4obh51KOnWbgAeK"
    "8R1ArDtr8m1OPFucRMnTaq17OzaXqrtJLfZTO9fKHYBxrAeAO22VyTQ3YoSyCaLtdFUEt7LYVLqCWcU+Egm37XREFaKyegWYwtS+"
    "GVK6GZjC/lQFUth+ukKF2RQSbYTJNCJ3lbLVCZpMvxkXKQ0pmOWRsq4wew+pSezjLK2NLpil8hGpMD6ytuDq9Jw0aay7yWzPIy32"
    "NL4g8tyqtJgyjSWp7pEwvaUKY6F2SGmKdj2jZUhhqcEbegWNT/BH/IHXlxQRQBvNchw79wr/RTpNQUXwm88HXZ2a7yP/8rl9iAqj"
    "dqFlaRdS114CxnsV10MabM5AdUQ72MHRWrCZjxGixJeCjQdTzWmyrqjDjVrBmvuRGViwz7vZwVHwGpiPhELRlweiDZPcdEDj+3JX"
    "xMDyXON013tExnPdOvo2CY7A+1xj1/RyRN22xvozCTpOHbrGOsnzNk4GSd36NvozjlxXQOPy+3TEWqLE8gjcLk4EXNpy4u4IjvGI"
    "Rkyz/PX2xEja8m4iHI6G/HHMyHXztkbzccz1iPy28bVGjHzzyPbarsQy3EgiTo48Z/Uu5nxyJ2ZOtfz8bjIce72JiBpY0uduTvW8"
    "PGYyn5RG50lCQA5fgEZnwolUDkYCX6dUwEmOzjxnNeaufHK94zROEhbqfjRWPY4jatL+SSG0D488cTZ0Uj0OqiPW/rQ8iU8hMU82"
    "NA+JD3GhfDYJMbSPPE9hNj3qNA5WkuN+9XyeDygntaQep7XPPDWoZDX7+7YQqGlrHqi1D/U8p2Q7aPU2u6lQ67tQ9bYpO2jrten7"
    "NqgQe2s1dZ4PJ+i8pK5jsDnDNmjg8PauuSMoQ2AuzIRc+lAo6DDDrjmo43ZgxNCuHExoOuhE+q5cKMwQ6G7ohNxQOgzoLmiw+TaD"
    "Y+C6eZYt6AO0ja8Vl0U6AB/3vDauoGoXXhEvH5cFQLoV936/oOxMdoTVriq8IJ52VxFg9r5sf8SMlRfAr4UVXzo3BcVl7wKVTJUl"
    "lUUvhcxC1W+Myen9/SHn5YJFrwwFVdXePUDs2b4HkMn97+lhzD2n76HJ6f19DOeFzGUv1QJFlTOhCeU5aLRRCWgzJWH0uZG/l6Yu"
    "IdJ3Lsl5M2U0IaiRCQ0oq5eNdFkmIb/utxdSrqhNCSuNtFcZc7QJJeg5oVHyCoJcZPjOOkI4stzKTuQ6R5r6NWOgDuZCJLLczkr4"
    "Onrgx3WaDiOmOuPHtU5aIKaHjvp1IGMa5vIOglx45Mo65zXZiGEpDDlZKefINYwhOamv/CFnYzUkmSHnCMx1KTl8I+mhbzUnpDwn"
    "6WG1byOkabX8YSOnLyQnDNlIqeE1Oct6kdX3fF1n0XyL1Xrdd2dQhmB9GgJLqtF3i1Xd+nxnIIJQfQZLWqpgmlA9SwZCqhCLYD1C"
    "WkaqS12R1fz3emeWVeegmUVQBqcF1qBVkFlGvpWPi2BAe/mnGdZgkJVFRk/AvotVu2C5j+C+S7tVQLl+u49LgKBV+VZQ56CFmVUG"
    "r6B/2Mu7eFv/e2+YoPhLm5bI1u5qUJV1/0tvmLjge5tWUNauSNWq9dZq1m6VSJD1VtXWbtCqiHWvuH/Y+4tgW+j/mZ8pHbBcGV2o"
    "3z+wqdyhxm7tfGlaaplpqB/wP53cNCCTDY/AYANEic+l8Ja/PJMAtA3gIE8DKPCZH53pv1yCOcoF8HRBB8o0woV5AXAHCS827VAM"
    "6OEKMMJFgfl0B/IdOnxu0ES8v6f/yuatLr8VCIocZrG4d0IBysU0sHkHoTvoUstmjnnoZuGSe06LOc8csWjAYBxZPiwAYK5Z9tHx"
    "YI/oXFwAGXFAj2jc3CAZTxyx6GDAHFn4EXU72VeiianWERR5nfubUZ0plJY7+dsc0tFTrW/wPhG5KZS7Vt3bkS/cE1Jw7f5RLdxT"
    "MJLv/lzw0ZNvLdI+qfsRVB251pvvTles3dy6PYnq7SWpTb+TAA4WnLjHIABJ/+2lDamqk9KoWK73lPa6bU76pDL5BAe/Y7DggWtN"
    "c62NyaVqP6nTm/IUIJMz9hSidGGyyU6QBkky0PR65Lu/rUULUH7w7DNaBo2kNtCl54AKjEocuYgSxLdthsiMa6XwWn8LoksYvfrv"
    "djbBRiAt++Khh6eazlk+PYtNFnANHJLb61GSCcUMH4dAZ0SHBY6Zh1FzUVDdDyZEZvnsxnIizNxzSwmcJ24DcPeyF0zq9h13SNfp"
    "Fj+7z19jGzTT8bQXd0jp1h0/u9NfYzUbzvG01rtJFx3pPnc1tWPP0xvwXhu0Y9PPNfFew6PrLikiiG7e2yRBdxyTcBvSx7mTtjnY"
    "KW7rwiMuiaK308eTuBs42EBxJB3fd5Lak9jHG7a5OdK52ce3G5I40onSycPSQvaFTVfT23h7FI2OQ9Z9RJQh371vC6psUVT6gi2F"
    "K4jcRyJt+wu8UapUbkTe1o+VfSBD3vFf+6ZtymH+3/2+kfyY0wsEFQzo2IWozx2xLUSsMXXZBRXoDAqEqK0dsUUszjF1DagV2Avo"
    "hARFdLHPrS0wHS10sa3PRTAdnDgEFxkjfIIWgwQjnBh9OLyHu4HfX3ctGIMEnSIWfTheh7vfgb13LSI4BBkXnXyC3y26vV+Bd4eB"
    "Lbpfvd93h7bvbkL36SGAWwJM7I6LA/jVYgIHdYbL5osDTI7tWgL42eS5qodovcvs+E2KW44DAnTmA9WGB8tih8q52GirveVVXoq3"
    "BzTbZTxQjO8AYt0BnlZr3duxuUwGZItVNLfbX5Nvc+LZ4iRa7gCMYz0A3FHcOOxU0qnbVN1NarGf2rlWq0ymuREjlG24bacjqhCV"
    "Tc3AFPanKpDSEG2nqyK4lU0rwBSm9s2Q0iNMphG5q5RtptIVzCr2kcD20xUqzKaQwE7QZPrNuEipdMEslY9IhWlj3U1mex5pSUjB"
    "LI+UdYVpkbUFV6fnpPGUaSxJdY+EwXtITWIfZ2ndp/EFkedWpbUtVRgLtUNK6w+8vqSIANrgaQoqgt98PtC06xktQwpLVZbj2LlX"
    "+C9qQ1QYtQstS+ve0CtofII/CurUfB/5l8/tkLr2EjDeq7gQJb4UbDyYitbcj8zAgn0OHtJgcwaqI7pOk3VFHW7UahSKvjwQbZgk"
    "wQ6O1oLNfNzNDo6C18B83KYDGt+XuyLm3ucau6aXIwLQNdZJnrdx6pbnGqe73iMCtjXWn0nQceq6AhqX36cj5p7r1tG3SXA0SOrW"
    "t9GfcTQSJZZH4HZx0kbSlncT4XAkmo9jrkfktzXg0pYTd0dwJOSPY0aum7c1diWW4UYScdJHNGKa5a+3j681YuSbR7aP5DmrdzHn"
    "k3N3c6rn5TGTOQI0OhNOpHL4MXOq5ed3kzmkNDpPEgJy+OY5qzF35ZNz2OtNRNTAkuYS+DqlAk5yNB2ncZKwUPfrk+pxUB2x9qd5"
    "SHyIC+WzobHqcRxRk/an5Ul8Col5sqFRp3Gwkhz36wqhfXjkibNJiKF95HkKs0nn83xAOaklrUCtfajnOSXzhaq3TdlBW984rX3m"
    "qUEl80Grt9lNhVrfqfN8OEHnJa3Z37eFQE1bq03ft0GF2FurHYPNGbZBA3cZds1BHbcDg9J35UJhhkAnt3fNHUEZAoOGduVgQtNB"
    "J0GDzbcZHAN3YSbk0odCQXdDJ+SG0mFAd82zbEEfoG3U+bgsANKtuH9V4QXxtLuKcK24LNIB+Lh/+wVlZ7IjrPYAfi2s+NK5ubVx"
    "BVW78Irgs/dl+yNmrAQoLnsXqGSqLBcsemUoqKou7n9PD2PuOU2pLHopZBaqLu4BYs/2PYD0ZC57qRYoqixjTE7v7w85fw9NTu/v"
    "Yzh/CU0oz0GjjZrOmymjCUGNTAn5db+9kHI1QJspCaPPjUxoQFm9bKTLSqNNKEHPCY2avTR1CZG+c/ltSlhppL3KQFcQ5CLDd9aR"
    "IpHldlbC1xEZP6510gIx1cKR5VZ2ItcRAz+u03QYMdV3EOTCI1fWkdLUrxkDdTA/dNSvAxnTMD+vyUYMS2HIOQw5R2CuS8nJOUkP"
    "q30bIeVKOUeuYQzJyRtJD32rOSHlYchGSg2vyTl95Q85G6shSavlDxs5fSFJ1ousvufrOlu+W6zq1uc7i9OE6lkyEFIF5lus1uu+"
    "O4sRhOozWNJSBeqKrOa/1ztbMgTr0xBYUoVYBOsR0jJShaw6B80sgjKwzbAGg6wsMjoE913arQLKfS2wBq2CzDI6AvZdrNoFy32C"
    "OgctzKwysK18XAQD2sv3231cAgStyvcF/cNe3sXbel96w8QF39v8VrN2q0SCrLffe8MExV/a/IKydkWqVq23xf3D3l8E23pEtnZX"
    "g6qss6q2doNWRayz/8/8TOmA5UJMQ/2A/+nkzkp8LoW3/OUh6EL9/oFN5c4BmWx4BAYboIHP/OhM/+VCNXZr50vTUgsEoG0AB3ka"
    "mMxRLoCnCzoQgBEuCsynO1A9/Vc2b3X5/aYRLswLgDtQ79Dhc4Mm4pUKUC6mgc07EHixaYdiQA9PQFDkMIvFvavdQZdaNnPMC2EB"
    "AHPNso/2A3pE4+YGyYg3C5fcc1rMQQd7ROfiAsiIj6jbyb4STcTmiEUDBuPIeuKIRQcD5sh6tY6gyOvc30zITaHcterejmrhnoKR"
    "fPeP6kyhtNzJ34584Z6Qgmv3j92PoOrItd5MkI6ean2D9+GCj558a5H24Xe6Yu3m1u15+m8vbUhVnUxz0ieVySc4aFRvL0lt+p1M"
    "RsVyvae015VtTC5V+0mdbnCw4MQ9BgEAHYMFD1xrmvuUpwCZnLGn2C1agPKDZ59pVGBU4shFlAClC5NNdoI0EDJoJLWBLj3X1/pb"
    "EF3C6IWSgabXI9/9Tb5tM0RmXCslf7ezCTYCadHcXo+STChmkDyMmouC6n7IFw89PNV0zto4BDojOixw/OaeW0rgPHFj6VlssoBr"
    "4PAhMstnN5YTMYC7l71gUrcfuENKt+742b3eTbroSPe5s7hDuk63+Nnt/hqr2XCOp52gHZt+ron32v4a26CZjqd9qR17nt6A96oe"
    "XXdJEUF0G3FbFx5xSRRNiiPp+L6T1AbeJgm645iE850+nsTdwMG+zT6+3ZDEkc6QPs6dtM3B3sQ+3rDNzZGelE4elhayL0x9W1Bl"
    "i6LS79tf4I1SpXJruprextujaGxsKVxB5D4SEY7/2jdtUw7zHLLuI6IM+Xbytn6s7AMZIv/u943kx5z2LqhAZ1AgRM1ArcBeQCck"
    "aCCoYEDHLkRd7YgtYnGOqWuhi219LoLpaO6IbSFijal7oot9bm2B6SjEIbjIGOET5Bgk6BSx6MPBwSHIuOjkExQYJBjhxOjDsTrc"
    "/Q7svWvxbNH96v2+Oww93A38/rpr4W7R7f0KvDv8fXcTuk8PAbQcYHJs1xLAX8dvUtxyHBBgEmBid1wcwN8mz1U9ROtdzlTOxUZb"
    "7S0/FhM4qDNcNq8zH6g2PFgWo/JSvD2g2S6rIFusornd/jIHYBzrAeCOcoFifAcQ6w7gfJsTzxYn0ZpuUov91M616rRa696OzWXy"
    "xmGnkk7dpuJlMs2NGKFsW2g7XRXBrWyCYTKNyF2lbBttOx1RhahswgGmMLVvhpRen65QYTaFBLYGprA/VYGUbpWuYFaxjwQ2gibT"
    "b8ZFSnUKZnmkrCtMQ0xjSap7JAymC2apfEQqTKOsLbg6PSeNj40viDy3Kq09624y2/NISxpDahL7OEvr3qnCWKgdUlpvXc9oGVJY"
    "qqKiwqhdaFlaH+D1JUUE0AZ/HMfOvcJ/UbOn5vvIv3xuV1NQEfzm84FOhl5B4xP8UfDUtZeA8V7FhZAGmzNQHdH1UPTlgWjDJKEo"
    "8aVg48FUhJqsK+pwo1ZzdnAUvAbm427mfmQGFuxzsHZwtBZs5uMOHdD4vtwVMTc81zjd9R4RsBXQuPw+HTHXPtfYNb0cEfCtsf5M"
    "go5Tt1K3vo3+jKNBrrFO8ryNU4dct46+TYKj8SixPAK3i5OWl7acuDuCIwErsQw3koiTtpK2vJsIhyMxfxwzct28rSGtESPfPLJ9"
    "fHwccz0iv63RohHTLH+9fTzPWb2LOZ+cI5lTLT+/m8yJz1mNuSufnDObUz0vj5nMuaXReZIQkMMnwNcpFXCSo5Gg0ZlwIpXDF15v"
    "IqIGljTHOI2ThIW6X+9Vj+OImrQ/jTqNg5XkuF+PVI+D6oi1P51P4lNIzJMNLQztI89TmE1CQ+JDXCifDc0I7cMjT5xNUp/nA8pJ"
    "LWk9ae0zTw0qmced58MJOi9pTWrtQz3PKZkHWr3NbirU+g76vg0qxN5abVS9bcoO2vou/r4tBGraWs0YbM6wDRq4671r7gjKEBi8"
    "Gmy+zeAYuAuwaw7quB0YzLQrBxOaDjoxOiE3lA4Duhu+KxcKMwQ6kTMhlz4UCroLnmUL+gBto27FZZEOwMf9a/BrYcWXzs0Fx2UB"
    "kG7F/csvKDuTHWG1370v2x8xYyWYCi+Ip91VhKuNK6jahVcEr3HZu0AlU2VBZdFLIbNQdUlz2Uu1QFFlIWDRK0NBVXW5DxB7tu8B"
    "pHdocnp/H8P5e/97ehhzz2lyY3J6f3/I+RtoQnkOGm3UTNpMSRh9bmQCbUIJek5o1BzeTBlNCGpkcgPK6mUjXVZCU8JKI+1VBmrI"
    "r/vthZSrSaWpS4j0ncvvgiAXGb6zjryOLLeyE7mOEIMgFx65so68iSy3sxK+jhD4cZ2mw4ipHqN+HciYhvmh+HGtkxaIqc6mfs0Y"
    "qIP5kU02YlgKQ855yjlyDWNITlZDNlJqeE3OCcg5AnNdSk5mSHroW80JKd8tf9jI6QtJWkl6WO3bCCnPK3/I2VgNSepeZPU9X9fZ"
    "st9itV733Vk0V2Q1/73e2VLdYlW3Pt9Z9CBUn8GSliqIIliPkJaRKsQmVM+SgZAqmCFYn4bAkiqU1TloZhGUgWWBNWgVZJbRadQ5"
    "aGFmlYEVhjUYZGWR0Wmw72LVLljuE+7jEiBoVb7fuO/SbhVQ7iPl4yIY0F6+b+gf9vIu3tYr3hsmKP7S5v/uH/b+ItjWK9IbJi74"
    "3ub/lLUrUrVqvRW1tRu0KmKdVZq1WyUSZL21srW7GlRlnSV/5mdKBywX+hfq9w9sKndGfOZHZ/ovFwoa6gf8Tyd3ZshkwyMw2AAN"
    "AG0DOMjTwCTicym85S8PUbFbO1+allqojnIBPF3QgWCNcGFeANyBMoByMQ1s3oFQjHBRYD7dgQKHDp8bNBGvfIIih1ks7l0F6b+y"
    "eavL7++LTTsUA3p4wg661LKZY17oWbjkntNiDrpE3U72lWgifgsAmGuWfbQP2CM6FxdARjxHLDoYMEfWE9AjGjc3SEYcRywaMBhH"
    "1jN1BEVe5/5mqmcKpeVO/nZUfgRVR671ZupuCuWuVfd2RAv3hBRcu3/kfPTkW4u0DxcL9xSM5Lt/VHT0VOsbvA+H0xVrN7duz7t6"
    "e0lq0+9komNyqdpP6nRrf3tpQ6rqZNIqlus9pb2uNBgseOBa09zvkz6pTD7BQZuDBSfuMQgAgDwFyOSMPcWmXZhsshOkgSjW34Lo"
    "EkYvvNEClB88+0xrQSOpDXTpuZZtmyEy41op8QKjEkcuogSgDDS9Hvnub5K7nU2wEUiL/njo4ammc9a+99xSAueJGzP2epRkQjGD"
    "5CHQGdFhgePHkVk+u7GciAlh1FwUVPdD5s9ikwVcA4dP3L3sBZO6/QAd0nW6xc9ux+3Y9HNNvNcGHVK6dcfP7sXXWM2Gczzt9O3Y"
    "8/QGvFdNbtJFR7rPnfXX2AbNdDzt8+i6S4oIotvwNknQHccknPf28e2GJI50btu68IhLomiK9PEk7gYO9u328YZtbo70JBxJx/ed"
    "pDZQ9HHupG0O9oZ08rC0kH1hotX0Nt4eRWPT/Ne+aZtymHfbgipbFJV+70vhCiL3kYhgt/VjZR/IEJH+Am+UKpVb25B1HxFlyLfj"
    "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"
    "JnNi5puIqIElzbHXVM/LYyZz7uZ0niQE5PBJaXQmnEjl8AVodUoFnORoJPBWY+7KJ+fMc+MkYaHu1ztO4ziiJu1PY9X78MgTZ5MU"
    "QuOgOmLtTyfV+BQS82RDy5P4EBfKZ0PzkPvI8xRmkxBD42AlOe7Xo075gHJSS1rP5/vMU4NK5nFabwuBmrZWs7/7UM9zSuaBWm+z"
    "mwq1voNWb5uyg7a+C1Vvgwqxt1abvvlwgs5LWlPnmzNsgwbuOgaaO4IyBAZv78ilD4WC7sJMmoM6bgcGM+zKwYSmg04M7cqFwgyB"
    "TqTvyA2lw4Duhk6bbzM4Bu6CBtmCPkDbqJtnWaQD8HH/WnEKqnbhFcFr41kApFtx//Jxys5kR1jt9wsL4ml3FeGqwsv2R8xYCWbv"
    "WljxpXNzAfz2LlDJVFlQXPRSyCxUXVJZnN7fH3L+xpj0ylBQVV0uWMSe7XsA6d0Dnh7G3HOa3P+c3t/HcP4emvZSLVBUWchcUJ6D"
    "Rhs1E5pTEkafG5mANuoSIn3n8ntpU0YTghqZnDeyetlIl5XQgOt+eyHlahLysNJIe5WB2pRQgp4TGjVHm8hFhu+sI68gy63sRK4j"
    "hCNfMwbqYH6kqcvtrISvI0QiXKfpMGKqB35c66QFYqozfl8HMqZhfuioyIVHrqwj7yCNGJbCkHNek45cwxiSk5VyH3I2VkOS+sqO"
    "wFyXkpMZch76VnNCyjeSHlb7NkLKc5IfNnL6QpJWy42UGl6Tc8KQWX3P13W2rBdYrdd9dxbNt9anIbCkCmUIWNWtz3cWfbfVZ7Ck"
    "pQoiCNWzZCCkCqYJ1iOkZaQKsQhZzX+vd7bUFQ6aWQRlYFl1DVoFmWV0WmC4CAa0l+9b+Q0GWVlkdJphu1i1C5b7BOy7tFsFlPsI"
    "7rgECFqV77f7DlqYWWVgBXWHvbyLt/UK+oYJir+0+b/37a4GVVlniWyGiQu+t/m/9O2KVK1abwVl7VaJBFlvrWbtBq2KWGdVbYe9"
    "vwi29Yr7+ZnSAcuF/p/6/QObyp3RhdbOl6alFmrs+gH/08mdmYbZ8AgMNkADMlwKb/nLQ5T42wAO8jQwCUD50Zn+y4UCn1wATxd0"
    "IJijXJgXAHegTCPTDsWAHp7wYlwUmE93oAAjw+cGTcQr36GvbN7q8vt7+shhFot7V4GgXEwDm3cgFKAutWzmmBe6gy6557SYg24W"
    "iwYMxpH1zBEA5pplH+3DAojOxQWQEQ/2iMbNDZIRB/SLDgbMkfXEEbeTfSWaiB9RQZHXub+Zah1CabmTvx3VmT3V+gbvwyEdQrlr"
    "1b0dkZs9IQXX7h/5wj0FI/nuH9XCPfnWIu3DBR9B1ZFrvZm6H8Xaza3b8+50XpLa9DuZqN7BiXsMAgDgYF7akKo6mfTf5XpPaa8r"
    "jYpPKpNPcNDmpAseuNY09zsGXKr2kzrd2pgBMjljT7EpTyab7ARpIEoXTa9HvvubJAMA5QfPPtNatEhqA116rmXQqMSRiygBqMBm"
    "iMy4Vkp827cguoTRC6/1ZxNsBNKi/256eKrpnLUvHthkAdfA4dOzHiWZUMwgub10RnRY4PhxCDUXBdX9kHkYls9uLCdiQmS3lMB5"
    "4sbMPS97waRuPwB3dJ1u8bPbcYe2QTMdT/v8NZRu3fGze3GHVrPhHE87/TV00ZHuc2e9m/Y8vQHvVVM7Nv1cE++1QTvukiKC6DY8"
    "uhJ0xzEJ571NnDtpm4O9IX0uPOKSKJritjyJu4GDfTt90vF9J6kNFEe8YZubIz2JfXy7IYkjnZt9PCwtZF+YKJ29jbdH0dh0Nd1H"
    "RBny7ThkoMoWRaXf+7a4gsh9JCLYUsAbpUrl1ra//VjZBzJE5G21b9qmHOYd/+8byY857f/dwYCOXYi6QFDbQsQaU/fcEYHOoECI"
    "ml1QW8TiHFPX2hGBvYBOSNCAWvvc2gLTUUQX2/pcBNPRQhdwkTHCJ8iJQzDCidGHYzFIG/j9ddfCe7jQKWLRh4MxSPsd2HvX4nW4"
    "kHHRyScogkPb+xV4d/jdovvV+313GNiiJnSfHgJo++7E7rg4gL8lwHBQZ7hsXi0m5NiuJYC/OMCreojWu5xNnqS45TggwI7fUG14"
    "sCxGZz6LjbbaW36onHh7QLNdVuWl+A4g1h3AA8XWvR2by+RptVhFc7v9ZUC2J54tTqI1+TY41gPAHeUOwE4lnbpNxY3DFvupnWvV"
    "3aSaGzFC2bbKZDqiClHZhNt2YX+qAindDEy6KoJb2QTRdmFq3wwpvQJMGpG7Stk2wmTBrGIfCWwqXaHCbAoJbD9dpt+Mi5TqBE1S"
    "+YhUmEYXzGS255GWNNbd8khZV5iGFMxwdXpOGh9ZW5JU90gYTJnGJPZxlta9h9QQeW5VWnsaX7FQO6S03lKFS4oIoA3+wOsi+M3n"
    "A52moNEypLBURbuenXuF/6JmOY5Ru9CytD5EhYLGJ/ij4A2995F/+dyuTs0vAeO9igupa0vBxoOpCFHiyAws2Odgzf02Z6A6oush"
    "DVfU4Uat5jRZywPRhklCoehoLdjMxx3s4Ch4DczH3ezg8X25K2JuOqCxa3o5IuB9rp3keRunDl1jcbrrPSJgea79mQQdp25bY3H5"
    "fTpiriugHX2bBEfjuW59G/0ZR4OkbnkEbhcnLVFieTcRDkdiJG3mekR+W6P5ODlxdwRHAi5tZuS6eVtD/jgZbiQRJ21XYqZZ/nr7"
    "eEQjRr55ZPv4WiN6F3M+OUees3peHjOZczenM+FEKocvQKNafn43mRMzp/MkISCHT0qjGnNXPjlnnrNERA0saY693lMq4CRHI4Gv"
    "JwkLdb/ecRoH1RFrfzqpHoe4UD4bmofExxE1aX8aqx6nkJgnG1qexAcryXG/HnUah0eeOJukENpHnqcwm4QY2geUk1rSej7Ph3qe"
    "UzIP1NrblB209V2oemeeGlQyj9Pam91UqPUdtHqHE3Re0po6z1sI1LS1mv19G1SIvbXa9H2cYRs0cNcx2BzUcTswmGHXLhRmCHQi"
    "fVfcEZQhMHh71w4mNB10YmhXfJvBMXAXNNgufSgUdBdmQm4oHQZ0N3RCFvQB2kbdPMsCIN2K+5ePyxBPu6sIVxVeIh2Aj/vXist2"
    "JjvCar9fUMKKL52bC+DXULULrwheG1e2P2LGSjB7X3eBSqbKguKyV4aCqupywaL0MOae0+T+95dCZqHqksqi9mzfA0jvHiCXaoGi"
    "ykLmsvT+/pDzN8bk9P4+hvP30OTyHDTaqJnQhDKaENTI5LyZ99sLKVeTkF+SMPrcyAS0mdXLRrqshAaUEvSc0Kg52oSXEOk7l99L"
    "U5VG2qsM1KaELjJ8Zx15BUFuZyV8HSESWVonLRBTnfHjbmUnch0hHFk6TYcRUz3w4y48cmUdeQdBmjFQB/MjTf06kDEN80NH/cSw"
    "FIac85psBOa6lJzMkHOw2rcRUp6T9OQaxpCcrJRz0LeaE1K+kfSk1PCanBOGbJCzsRqS1Ff+sJHTF5K0Wv7qe76us2W9yKpufb6z"
    "6LvFniUDIVUwTahqve67s2i+xT6DJS1VEEGoav57vbOlrsg+DYElVShDsB4hLSNViEWw0MwiKAPLqnMwyMoio9MMa6XdKqDcR3Df"
    "0CrILKPTAmvFql2w3Cdg39DCzCoDK6hzRTCgvXzfysclQNCqfL/dx+zlXbytV9A/TFzwvc3/pTe3SiTIems1a0xQ/KXN/703V6Rq"
    "1XorKGvs/UWwrVfcP3c1qMo6S2RrN2hVxDqramvPlA5YLvT/zA/4n07uzDTUUnjLXx6ixOfvH9hU7owu1IZHYLABGpDJj870Xy4U"
    "+Mx2vjQttVBjtwZwkKeBSQDaAni6oAPBHOWiwHy6AwUY4WXzVpff39N/wrwAuANlGuE+N2giXvkOHWIa2LwDoQDldigG9PCEF5sO"
    "s1jcuwoERallM8e80B10MNcs+2gfFgA0bm6QjDigR8k9p8UcdLNwdC4ugIx4sEed7CvRRPyIujRgMI6sZ45YdDBgjqwnjliKvM79"
    "zVTrCMpdq+7tiNwUKRjJd/+oFu5Ky5387ajOFAkpuHb/yBfuqo5c683U/Qip1jd4Hw7p6Mm3FmkfLvjo1m5u3Z53pyvShlTVyaT/"
    "9lKZfIKDNid9ktSm38lE9fbXe0p7XWlULFK1n9Tp1sbkTtxjEAAABwvwwLWmud8xWJDJGXuKTXkKKD949pnWogUljlxECUAFRtlk"
    "J0gDUbowUhvo0nMtg0YF0SWMXnitv3o98t3fJBloQ2TGtVLi2zabYCOQFv13OyjJhGIGye31uSio7ofMw6jDU03nrH3x0DOiwwLH"
    "j0OgpQTOEzdm7rkmC7gGDp+exXx2YzkREyKzXf5ALt52wonnd+LOKR36o/oAQTQA/x1t/wBtHQBB+jRLaDf1RV2jD11oD6NFN0v1"
    "N2j1S0UPXaMPaKNdRfU3S7jCGlncFvhxFsJx+NwauFkawlm43HEW+IT1kOOXHBXl2JL3tIsiFssikssWi/fYtPeStNiLyyIWy5IW"
    "Iou099g16/6G3mE75tUcPg41ALNYABxYszU+1Q4+HA7VNVgAs/9+vfvWeyKKe36KIta9//u9fvv/1op7Iop+InvW+73/mKn/RWyd"
    "2gqdqQrabP+YRf+pRZhsCp3aBJfGk7lwp5g5ZGs2k/GSoYoaK7BF1sbN1hrNxkUrirArGrCKRc3WxvrC4COSjSZrjcJrJpLg+iPg"
    "wiP6kmuNJmvCJo2SI+D6nzt9GNm86gS8OwTq2X2fGJfiZQDBk16Pk+KPXsFllwB0V0ix0XmrXHlXXKvRSHSxSFexdNFceatcV6t5"
    "0bFIdNC8dHZ5fnB2frx2cHl00HZ0vHbQeXZ+cHa8cH55dnTQnN/xrWOtu2Wt32W7Y/GcrY+v2+LfE93Cwh6KqQ9n+5R+JF0zKnB2"
    "9cFQJCpT9iJk9lBkIlMkwSokUCrBU2T2IobJPISfJNH/JMn/0Z88hoQ8yYSGn/8k0R/qQ6m577FE82Q0QnX2aT/2ZD9pdTTzQjRk"
    "QvN1P/ZpP2Rp9nVCNPPSHPWBzogkkIgckCTO9dKB9RyB0s6QiCSQHCSIzoH10q0fhPfWDCKzDB+zItaErfeEH/et1rMMIrMfIgzW"
    "94Stoan/ih6RQgORqQNCHv+hiiktJ1aaHGbvHC3vZponKVbhePYi6KILoKJ4oAvo9uEi9ngi4eigogugeAui6CL24egG/SgQ/+XH"
    "/wbH5RD96CgL5woeaOUeDeXnDR5oCgsepfh0y3KuDXKu+HINcnSly3T4y6Vycq4NcvgNrnLLdKXjtqJNGCuNgCu2gI0YouNNorZN"
    "4xiAK42Ato0rGE2i43dMXTFVwL5bwExbvlVddzFdTDF3VVvAvltMvsBVMV13pNn6HSlOqEFO2UGoKfqkHfrZHaQpQU6oQdmoTikd"
    "+qRxgDgwk25PtsbBb+fdEWzKpwcLAzqy14uyB4vXOgunAzcZ67Df/fLb/Rnb8t/rN7DrGbA339v98prAWrP2rRGTRxG2itfo6gHo"
    "EQHq17ZHind+bZrGbSJNbX5NIsZtd5qnairguHBQD3BqD1C4KqfgKmrgp7gPcFAPalBwuOAqpxueY16DhBCdhJ6dEINjG15jnl4b"
    "g52EEJ2eEISDXmMbehWGLHsqbQcqFQdte4Z6LIYVLHp7ByptBxVtKnsshnqZCSoI5xaXpBYJpJfnKpkIJWNY6V9EPDBEYzA8X1gl"
    "6VdNuT/de+REe01E5N25Vz+5TT9X3UR75ERN5HvdP7lXGxCvP5SBwC6BEC7AlK8bP68QPxuULoHALhDAgZQ/rxvYSd1v5YEhd4FJ"
    "dyHl3dhv3Ulv2OV3gSF3SSGB5W/d2OnLNUH8ElLmEsvmUvw16UHojzoNuKv2KauPKfa4OugN9xWAEf8ZSHQZFXRI/4D3EZLe96UD"
    "QfAJQd4J8AP3kqW529Iw7ZHWKcbkkJvShWR0heR0ZNKQxpuqDJYxx/SUm7HTPpjvz9Azz9Mz0O8+sZg+05ix7zPP0DPT0M/vmD6x"
    "3/ZlBxehOu2h9u06F2XfB2X2B98X7aE67fY6oRcHZd+Nshm/fvIIAvKyAgh+GY2/GbK/jX4C8ggCsgjyfr8ZjePaUKpKbLBdbNpd"
    "sEpQ46pQ2qrjSl1ssO/SQhL1s90AaxaI9ruKs1wg9Rbu1ziEJGWZ/tlnXHANXJkNcGf+ZdnLmHwIsIyUVoyYVpSwfMsI6Ch0ALi+"
    "pOC+KOCkuHToAGdfAxn8qcH2qV/2wfwDZxkDXxln/PapwfZfwan8GQNncw5XCPiVTZqVDppN+FdzCFcOCHP4mpVNmg5NlfgIV3Pg"
    "LMB4y1C9CSAhVSTGsIeGsCGGh8ZVICRxRL3eH+Hs95xCnuFtxz+Rx0KRP22enOGeQuGcbZHHP5FCP8dt4Z6cEzeBYA7HiHXHN3WI"
    "DoETYIE3YBMOdceIdTeIxw5ggRPgvekczfSUw/S9w5TN6eAc6b0c4M3D9JTDvZT0zRzp4IyNSeJBIp5TcfyvMXA5tVc5/Fe1cK9x"
    "Ma/8MXFwVzm1YEzayfQy54oyTIrn9NpgyclCvKd8/wVv/0JvBXy8yadWfxIK0LuIlvelX3zi9dw4hNVv5Vc/u6Y/1aa7V2+E5dMu"
    "cIHhElHLEi7LUeFw04GS213rZR59tB7btH1lXZLrwoy9SnFZgb9ZjL+Bcb3CSr2MSsJxv1mB7m3xivDYZp/EpMV8ieY3puakpjeJ"
    "xcR8MHhEQFzJA2DJeGADXEQwQKe/tlMvQxrDQ7/DGi+2p1NoyZEuyLSh1LTJ1KHIkWgu2o6JYflg729gjm/v+YnaYWbhAVSWgJlm"
    "gOFmmZYBZlQMPkAxLbjHALg+AMctQAwxuV7eY02O1yiOXijXTd65Y4VA+hwdQMuCQECCyx36hRw806X1uhp5rxrTr3m6pTz1NuRG"
    "BPFSRJxljGkPtElrp3yMFDO0dT28Y3TNK3ZlhO9NsHdHFnm4wrRm2HXQMmbNvO+sn7A32xVqEVX1btp+FjeuD1EYj4iAj66AiBgP"
    "N1E7rq4qdX+P5dj9jUbkgPOemLNTM6xp6GaiMSaoLpiFyVMTW044rVVwHWQ3Q0Hjkfpv0OqXih66Rs/vxJ1TOvRHu9AeRotuluoe"
    "0Ea7iupvlpbQbuqLukYfu/yBXLzthBP+Ado6AIL0afQBgmgA/jva7iVpsReXRSwshOPwuTVws0Ukly0W77FplyUtRBZp77GxJe9p"
    "F0UslnCFNbK4LfDjCeshxy85Kso1hLNwueMs8Hr99v+tFfdEqjl8HGoAZrH3/BRFrHv/9xX9RPas93v///169633RBRr1v0NvcN2"
    "zH04HKprsABmADiwZmt8qh2tNZqNi1YUYTpTFbTZ/jGLFTVWYIusjZtXNGAVi5qtjXPI1mwm4yVDMFP/i9g6tRUJLo0nc+FOMf9T"
    "izDZFDq1L8XLAIInvR4ahddMJMH1R3h3CNSz+z4xJsUfvYLLLgE+d/owsnnVCfSFwUckG03W14RNGiVHwPXAhUf0JdcaTeh47aDz"
    "7Pzg8664VqOR6GL8eO3g8uig7e144fzy7OigoHnp7PL84OzorpBio/NWubiuVvOiY5Hoka5i6aK58lbsochEpkiCVVu/y3bH4jlb"
    "gqFIVKbsRchIoFSCp8jsRf1IumZU4OzqOL/jW8dad8uFPRRTH872KR9ft8W/J7qFaMiE5ut+7NNJkv+jP3kMCezJftLqaOaFf8jS"
    "7OuEaObmyWiE6uzTfg2TeQg/SaL/PtSHUnPfY4l5kgkNP/9Jogg/7lutZxlEETkgSZzrpQMZPmZFrAlb72c/RBis7wlbWz8I760Z"
    "RGalOeoDnRFJICE5SBCdA+ul6jkCpZ0hEUns8UTC0UFFFyNTB4Q8/kMVRPFAF9Dtw0VB8RZE0UXsw8Px7EXQRRdAQlP/FT0ihQY4"
    "Wt7NNE9SrFNaTqw0Ocze6PCXS+XkXBv+DY7LIfrRUV3x5Rrk6EqX5fAbXOWW6UpK8emW5Vwb5NEN+lEg/suPys8bPNAUFjwWzhU8"
    "0Mo9GruYYu6qtoB9VmwBGzFEx5uAmbZ8q7ruYraYfIGrYrru7pi6YqqAfbfHbUWbMFYaAQFtG1cwmkTHRW2bxjEAVxpPDxYGdGSv"
    "F5yyg1BT9Ek7jYPfzrsj2JRkDxavdRZOB+MAcWAm3Z5sSLP1O1KcUIODslGdUjr0SfWzO0hTgpxQ7vzaNI3bRJr7M7blv9dvYNEj"
    "AtSvbY8U2/yaRIzb7jSOImwVr9HVA28y1mG/++W3NYG1Zu1bIybXM2Bvvrf75cY8vTYGOwkh4dQeoHBVTsEIPTshBsc2vDo9IQgH"
    "vcY2NzzHvAYJITpO1VTAceGgHh/UoOBwwVVOVNTAT3Ef4KBKxrDSv4h4YFQqDtr2DPVYLBJIL89VMhGJxmB4vrBK0jMTVBDOLS5J"
    "9CoMWfZU2g4OKtpU9lgM9QwrWPT2DlTaXyF+NihdAoH2mojIu3OvfgIhXIApXzd+XCCAAyl/Xjc2IF5/KAOBXa6acn+698iJiJrI"
    "97p/cq9zm36uuon2yNAfdRpwV+1TApPuQsq7sd8kls2l+GvSg1YfU+xxddAb05drgvglpMywk7rfygND7u+SQgLL37qxupPesMvv"
    "AkMLyenIpCGNNzIq6JD+Ae8jjMkhN6ULyehVGSxjjukpN3K3pWHaI61T7isAI/4zkOiDvBPgB+4lSyS970sHguATyuwPvi/aQ3Wf"
    "p2eg331iMULt23Uuyr4P2+11Qi8Oyr6/7csOLkJ12mKnfTDfn6FnZ6ahn98xfWJ9pjFj32eeoaG0VceVuthg5WUFEPwyGn/ZtLtg"
    "laDGVd6lhSTqZ7sBxrWhVJXYYLsaZTN+/eQRBAVkEeT9fjMaMmR/G/0E5BHRUegAcH1JwUDqLdyvcQhJGDGtKGH5lhF8UcBJcenQ"
    "AZYx+RBgGSmt1iwQ7XcVZ7m5MhvgzvzLssoy/bPPuOAarhwQ5vA1K5tSv+yD+QfOMiodNJvwr+YQNB2aKvERrubnHK4Q8CubNM++"
    "BjL4U4Pt7L+CU/kzBs4HvjLO+O1TgzyFwjnbIo9/QUKqSIxhDw2PhSJ/2jw5wyOFfo7bwj05OYU8w9uOfyLAWYDxlqF6E+OIer0/"
    "wtnvYEMMD42rQEjTeznAm4fpKY5v6hAdAifA6HuHKZvTwTmHeynpmznSwcF70zma6SmHJm4CwRyOEevqbhCPHcACJwNvwCYc6o4R"
    "koV4T/n+C97i+F9j4HJqr2WYFM/ptcGS/4XeCvh4k0/BmLST6WXOFRgbk8SDRDynX/lj4uCucmpy+K9q4V7jYiW3u9bLPPpo7ku/"
    "+MTruXElXJajwuGmAz22afvKuiTXp13gAsMlopat/iQUoHcRLX+qTXev3gjLCavfyq9+dk1g8IiAuJIHwLIYfwPjeoWVzElNbxKL"
    "ifmS8cAGuIhggIlJi/kSzW9MhRl7leKyAn/d2+IV4bHNPnsZlYTjfrMCzMIDqCwBM82Gfoc1XmxPp8Ac397zE7XDAMPNMi0DzKi0"
    "HRPD8sHe309/badehjSGaJOpQ5Ej0VzRkiNdkGlDqXmmS+t1NfJecH0AjluAGGKAgASXO/QLOTWmX/N0S3nqC4H0OTqAlgUYfIBi"
    "WnCPARy9UK6bvHPHcr28x5ocr1F431k/YW+2K8sY0x5ok9ZOac2w66BlzJrUIqrq3bT9LJtg744s8nCFbciNCOKliDjH6JpX7MoI"
    "3/kYKWZo63p4pia2nHBaq+AeXQERMR5uokVjTFBdMAuTO8huhoLGI/UwZ6dmWNPQzW9cH6IwHhEBsfsbjcgB5z13XF1V6v4ey/wD"
    "tHUABOnTnt+JO6d06I92+QO5eNsJJ+kDBNEA/He0LKHd1Bd1jT7eoNUvFT10jT2gjXYV1d8sd6E9jBbdLNUT1kOOX3JUlFkIx+Fz"
    "a+Bm4QprZHFb4MdrCGfhcsdZ4GNL3tMuilgs3EvSYi8ui1gvS1qILNLeY4pILlss3mPT+nA4VNdgAcxVc/g41ADMYtes+xt6h+2Y"
    "AHBgzdb4VDv++/XuW++JKPT67f9bK+6JK/qJ7Fnv9/7v+SmKWPf+7xJcGk/mwp1idaYqaLP9YxZgpv4XsXVqK/+nFmGyKXRq5pCt"
    "2UzGS4ZaazQbF60owq9owCoWNVsbK2qswBZZGzevCZs0So6A6zQKr5lIguuP6QuDj0g2mqyAC4/oS641mnzu9GFk86oTXoqXAQRP"
    "ej1Mij96BZddAvDuEKhn931icV2t5kXHItHmXXGtRiPRxdFdIcVG561yIl3F0kVz5a1B89LZ5fnB2dHx2kHn2fnB2/HC+eXZ0UH5"
    "8drB5dFB2wp7KKY+nO1Ttn6X7Y7Fc7Zxfse3jrXulj++bot/T3QL+5F0zajA2dXYQ5GJTJEEq5BAqQRPkdmLBUORqEzZi5B9qA+l"
    "5r7HEpIk/0d/8hgSGybzEH6SRP/zJBMafv6TRMyT0QjV2af90ZAJzdf92Kf/kKXZ1wnRzNmT/aTV0cwLQ3KQIDoH1ksickCSONdL"
    "B0pz1Ac6I5JA1HMESjtDIpK2fhDeWzOIzBB+3LdazzKIzn6IMFjfE7YzfMyKWBO23nG0vJtpnqRYRqYOCHn8hyqEpv4rekQKDae0"
    "nFhpcpi9huPZi6CLLoDY44mEo4OKLoPiLYiii9iHiOKBLqDbh4uUnzd4oCksePwbHJdD9KOjoxv0o0D8lx8snCt4oJV7NJXi0y3L"
    "uTbI0OEvl8rJuTbK4Te4yi3TlbviyzXI0ZUuA9o2rmA0iY6t2AI2YoiON47bijZhrDQCito2jWMArjTdMXXFVAH7bnYxxdxVbQH7"
    "bTH5AlfFdN0AM235VnXdxQZlozqldOiTOGUHoabok3aRZut3pDihBupnd5CmBDmhxgHiwEy6PdmeHiwM6MheL8geLF7rLJwOGwe/"
    "nXdHsClqAmvN2rdGTPZnbMt/r9/A32Ssw373y2+vZ8DefG/3yxxF2Cpeo6sH3fm1aRq3iTS2+TWJGLfdaaJHBKhf2x4pPqhBweGC"
    "q5zDqT1A4aqcgpyqqYDjwkE9qaiBn+I+wEFueI55DRJCdIx5em0MdhJCdHpCEA56jW0RenZCDI5teB1UtKnssRjqqFQctO0Z6rHo"
    "VRiy7Km0HRlWsOjtHai0ZiaoIJxbXJKUjGGlfxHxwBONwfB8YZWkWCSQXp6rZCIRNZHvdf/kXuw1EZF35179XTXl/nTvkRPnNv1c"
    "dRPtkWxAvP5QBgK7v0L8bFC6BAK4QAAHUv68bgRCuABTvm783yWFBJa/dWMFJt2FlHdjv2Endb+VB4bcdCe9YZffBYanL9cE8UtI"
    "maA/6jTgrtqnrD6m2OPqoDdJLJtL8dekBwZ5J8AP3EuWZFTQIf0D3kfdVwBG/Gcg0Uh635cOBMEn5G5Lw7RHWqcWktORSUMab6oy"
    "WMYc01NuGZNDbkoXktHOTEM/v2P6xD5Pz0C/+8RixE77YL4/Q8/7TGPGvs88Q3/blx1chOq0lNkffF+0h+q32+uEXhyUfYTat+tc"
    "lH0fCsgiyPv9ZjTKywog+GU0/jTKZvz6ySMIZMj+NvoJyCONa0OpKrHBdkJpq44rdbHBvEsLSdTPdgOyaXfBKkGNq3NlNsCd+Zdl"
    "gNRbuF/jEJKtWSDa7yrOcpRl+mefccE1LWPyIcAyUlqjo9AB4PqSgviigJPi0qEDMGJaUcLyLSPZfwWn8mcMnKR+2QfzD5xln30N"
    "ZPCnBtsPfGWc8dunBs45XCHgVzZpXTkgzOFrVjZpOjRV4iNczVQ6aDbhX80hxxH1en+Es9+ChFSRGMMeGoCzAOMtQ/UmwIYYHhpX"
    "gZByCnmGtx3/RHgKhXO2RR7/Rgr9HLeFe3IfC0X+tHlyhtTdIB47gAVOHd/UIToEToBN3ASCORwj1gbegE041B0jg/emczTTUw6m"
    "93KANw/TUw/3UtI3c6SD0PcOUzang3O+8sfEwV3l1MXxv8bA5dReMTYmiQeJeE7k8F/Vwr3GxYIxaSfTy5wrJQvxnvL9F7z+C70V"
    "8PEmn8swKZ7Ta4Ml/1Sb7l69EZbcl37xiddz41r9SShA7yJaEla/lV/97JpPu8AFhktELUpud62XefTRe2zT9pV1Sa5KuCxHhcNN"
    "B7q3xSvCY5t9ZTH+Bsb1CisKM/YqxWUF/vYyKgnH/WYFEpMW8yWa35jB4BEBcSUPgCXjgQ1wEcEAmZOa3iQWE/PQJlOHIkeiuQ39"
    "Dmu82J5On/7aTr0MaQyjJUe6INOGUmk7Joblg72/mYUHUFkCZpoBhptlWgaYUYE5vr3nJ2qHOXqhXDd5547g+gActwAxxDD4AMW0"
    "4B4D5Hp5jzU5XqMWAulzdAAtC/JMl9brauS9a0y/5umW8tQAAQkud+gXco/RNa/YlRG+ljGmPdAmrZ3akBsRxEsRcfIxUszQ1vXw"
    "N8HeHVnk4QrwvrN+wt5sV6hFVNW7aftZ05ph10HLmDVi9zcakQPOez26AiJiPNxE3rg+RGE8IgLvuLqq1P09lmHOTs2wpqGbTU1s"
    "OeG0VsF3kN0MBY1H6ovGmKC6YBYmekAb7Sqqv1k9vxN3TunQH71Bq18qeuga70J7GC26WapYQrupL+oaffkHaOsACNKn0wcIogH4"
    "72js8gdy8bYTTl6WtBBZpL3HshCOw+fWwM24l6TFXlwWsRWRXLZYvMemxpa8p10UsVgnrIccv+SoKNcQzsLljrPAwxXWyOK2wI9X"
    "9BPZs97v/arm8HGoAZjF6fXb/7dW3BPf81MUse793/z369233hNR9eFwqK7BApgA4MCarfGpdq9Z9zf0DtsxXtGAVSxqtjbqTFXQ"
    "ZvvHLLXWaDYuWlGEVtRYgS2yNm7NIVuzmYyXDCS4NJ7MhTvF/k8twmRT6NTATP0vYuvUVpgUf/QKLrsEaRReM5EE1x+8FC8DCJ70"
    "euDdIVDP7vvE+Nzpw8jmVSdfEzZplBwB1wEXHtGXXGs00xcGH5FsNFm244Xzy7Ojg8274lqNRqKLo+O1g86z84Pz47WDy6ODtoPm"
    "pbPL84Oz47pazYuORaJFuoqli+bKW6K7QoqNzlvlIYFSCZ4isxdt/S7bHYvnbLGHIhOZIglWC4YiUZmyFyH3I+maUYGzqxT2UEx9"
    "ONunfnzdFv+e6Bbj/I5vHWvdLf8hS7OvE6KZJEn+j/7kMSSjIROar/uxT7In+0mro5kXmSejEaqzT/v6UB9KzX2PJeZJJjT8/CeJ"
    "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"
    "NRnLRHT+rEN5YYygoP6sjEN0YXl5/qxhjKB0Q/9p/kHloQjCwmn+CEH/oeXlaf6hCML/QdaStrCaRA/RtwdN+dLy2fW2kLaRtoxT"
    "Hx+QtlORtoy2tpC2jFMftpFvh/US8AO/9fWH9b8SbwPw8If1A7/1bxISh/VvA/D1v9aQHCX6Y1qwsJAcWiXWY/r6kBxjWrDWJSWQ"
    "HNZj+rBaME0zIP9rvxERTTO/IDBr//9NM2u/ETAgIE0zMGv/Eb/Tzb5Q+2MGOAiAjSavuNzqz6UdwPBrQh8fpR1CwM9r8OtEEhMj"
    "JUlzc0QSSRPrJSOcVSIFaT7YIyNVItgFnD5pxd0qDshvPpSU3So+DsVvyMjdKm8+lMUODt0qxW/IlD4+Uu101t+A4eFS7YB0Pt/W"
    "1lLt34DhPnR0Uu0+39bhgM7fz013iZz9/d/PnE3OiXd338+JnP3OTU3fz86Jd/2cl5HD14el2Hx8kcPY15elh4eRw6XYfJfX15HD"
    "l6WHfNgmlDlasDcDFxeUOQNaJjewsJQ5NwMXJlqCQ66DsDeGwLN8LKRx7qE/P3wsoaSz7nFxfCzuoT+zpKR8LLPucT+hBA6TOBYC"
    "bwICDpNvOAQCFhYOkwJvAgQ4OA6TBAIWAm/GiHH0zLa3Dw+Icbf0xrbMOETHAbgAToWFRMdOATgAuCC9H0bFqPmenr0f+UYgqMXF"
    "vR+o+Z4gRtFqyLFrUjt+22/ynBvWUXR0b/JRnNvWGxtv8tZRdNucnG/y29YbdFF6d6u7/jqQ5+d3q5C7ejr+/nerOpDneru7d6t6"
    "Ov7nkCnkQwhvvwqIiORDCggpv2+Lp0vQtYKhgKlDCKm/NIg95MzMeEItoYKCzMyheOQtQkLMzC2hguR4VW1OAFUX7++64s6VCbe5"
    "vb3izrmVurcJCeLOt7m9upWV4s66twm9ub6R9payI134+JH2XZa+I7KykfYjXfi+lpaR9r4jsvhd3tfxhWpkA0BA1/EDhd5kamK4"
    "Tm6LyDrGxrhOOm5iyItKdeGo8L1mBwd14WaoSr3w8HXhvWYHSqiodeFKvfAHZmC0r64TOCb4+LSvJq5gOBMTtK84Jvhgrq60r2A4"
    "E/gmNFdK/wCNDKOjV0oM/zSNAABXSo0MozT//1dKNI0AowxZeFDiY4Zx+vp4UHHiWYZjY3hQhnH6WeLieFBZhmP6cYIkPt3PjQuw"
    "sCQ+C92Cjc/PJD6NC7CC3d0kPoKNz7ALS1TQldQVfT09VNB9lUsV1N/kYDFDNpYXF+RgljHfNkNbgBc0y3yyKqdPp7l/D6xeXk+n"
    "rLmnD39/T6cPrF6nuZzFtikyhHYYGMW2dimchDJrJ1T8JkEaSkonVBr8a0EmlTH6wDrrFQAprX4nq7K/xsatfr8nKbKrq61+sr/G"
    "KSfDhYhbbhUY1kpAPjFpR2N2dkA+YzFKR2lpQD5HY3ZKMdvmr22Mcjbf3+avNm3bcoyM5q9yNt/bbW3mr9tyjN82t3e5h5RuJume"
    "zj6y6ZGHCgrOPoeynpHp6c4+kYcKnrIdAyJ174X4398DIvh1HYXv7wMihfjfHXV1AyIdhe/f+O2afnng0zdubpp+N3nt0+Dgmn7T"
    "N27teXmafu3T4G43qv3+mhOkw9bW/f7DmqqkE/OTyQ4+KDCJiZPJMA7zKD5WzZuE6t+Nf3/Nm42EVt/q3bR2DG2fzPr6tHbMDN2f"
    "bZ1cXvltajwDP19hY5j+8pOTX2HyYz/+mJhfYf7ykz9jeggNjU8namlpCA1qjXonT5K8eysH9rZ3d7x7tiuS9ge59QrZxJfdAQH1"
    "Ct3ZuZfExPUKl90BudnZ9Qq5l8QB3fMjevB6gLB1dSN6sPDzgHp6I3qAsHXz8PAjevOAenWwh4Ql5HkH5eTkhCXl5IcHeQMElXKQ"
    "x/1UVASV/XIDx5DYRwDeob+x9vZHALHe2L+hoUcAv7H22N7eRwDYv6H2sTg3trKlb+bi4je25rI4b6WlN7Zv5uI4srI3tjhvpeLm"
    "kJgk9grQUrK4SHbgTtim6upIdqbguNhOpL90qVBZrqwEzLWiwsJjz4e6VS16oigoKLpVKC2HonrIgjoHjR8xQtOQkfY5wAktz6cn"
    "70Trr5ycpyev78/rRMMdcsbVPufHTFsX3+yec9XVWxdz30ye7OxbF55z1Uzf31sXTJ7s1XM0RRAdNEjolZVFEOgdNEg0NEUQSOiV"
    "NB0dRRA0SDSV6Od4c3gLMBYJCXhzFnjnMAsLeHMwFgnneHh4c+cwCwkW9Ggv7/33L0hIaC8v7/T3/f1oL/cvSPTv72gv9Pf9SC88"
    "N1+QjMF8y8s3X3yQPMGMLc7PHi6ZORdhhyfuAzAiOWFCUhQ2Yc5sbEJSzhRhYTY2QlJhzmxhFK9VhRde3iWH9gB8hroZvWN8H+wL"
    "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"
    "9h/xC9I0A7MCs/Yf0TTzCxsBA/LfNLP2v/YbAdM0A/KKy62OANho8j9mgDPd7Au1/LwG/1HaIQS/JvTxXNoBDMDpkzZSJYJdsV4y"
    "MkckkTTmgz3CWSVSkFKSNLdOJDExUPyGTNmt4uP85kNZ3K3igIZM6ePQrVL8Q1nsgNyt8uZtHQ5IJ9Xu8+fzbR0u1Q5IGO5DZy3V"
    "/g39DRjuI9VOZ+SceNf//czZl8jZ7/z93HR418/Z9P3snNnv3HT3/ZzIesiHfR05fFl9WXrIFzmMfc13eX0YOVyKWIrNdxk5fH1l"
    "cgN7QZkzoHszcGFCmaMFe2MILDjkOghwYaIFS5lzMx73E0rKxzLrOuse98PHEkr6M0sax8fiHuce+jPLx0IaQyBgIeAw+YYh8CZA"
    "4DCJY2Ah8IbjMEkgJkCAY+EwKfCAA4BbSHTsFG9sy/yAGHdLC+BUiEN0HIBse/tgjBhHzwSCWuzZ+5FvjJrvCdL7YVQmteMXrYYc"
    "u+8JYlTc+4GavUEXxfkmv225bb1B9yYfxUW3zbnxJm8dYR1Ft/0mz7mrp+N/frcKua8Dea53t7rr438OuXu3qqd5rrfrf7eqA0uD"
    "2JM6hJD6kPL7hkg+pIArGAq4eLoEXfargJhCPoTwR94iJMjMHIrUEipIzsyMJ3Xx/l7V5gRQKkiOJ8TM3BKb0JtbKe6se6l7m9Ar"
    "7pxb26tbmSDufJtwm9urK+5cmek7Iosfad9lO9KF7xtpbykii99lGWnvO4XvaykbaT/SJoa8aIzrpOPoTaYGdB0/UIisYyyG6+S2"
    "RjYA5H0dX6iq1At/UBduht9rdqBUF44KC39ghloXrtR2oIQKXxfeazOBb+JK+wqGCoYzgU/7auKCD+Y6QfuKY4Fjgg9G++o6T9MI"
    "MHqlxPDQyDBKc6X0DwgwyvB/pUTTMErzD3Cl1Mg4ph8njgeVZZ5lOKaPBxUnp58lPoYHZRhmGKefhQclPi3Y+AxL4rPQ3LgAK0ji"
    "0/34DLvQTeIj2AAr2P1M4tO4820zdEEOZhm5VEHdQwXdV2RjefFNDhYzXdHXs0QFXUn3wOp1+nSa+8wnq7IFeEGz6nWa+/d0+sB7"
    "+vDn9XTKmr8WZKJ0QqXBwkkog1Fsa5cSpKG0dkLFb0Noh8FZbJsiKvtrnNLqd7KzXgFQGaMPrGuccrLa6if7kiK7atzq93tmpxST"
    "BuRzNHY0ZqcE5BOTo3SUZgfkMxZWgWE9XIi45bYtx/ht/mrTKGfzvW3+2sbH+G3TZv66LfO93cZo/ipnqOApm+7sE3keeajg6ewj"
    "m+sZma7g7HMo6WaSfnuXe0jXUfj+PSCCX16I/90xIFL3+P6NXzcg0lH/3VH3PiBSiA3udpOn6dc+1z4N7qbpd5Pj1p4Hruk3fT59"
    "49au6ZcHqUo6Yd3vP6xBOmyt2u+vOTCP4pM4mQzjgwKTOD+Z7ODQ/dmmT2vHzGj1rf7XvNlI9sms301rx9D+3fhn1bxJqOkvP/nz"
    "FTaGpsYz0Mnlld8/+TOG+RXmL/bjjzn5FSY/Iml/cMe7Z7uod/KUhtCg1mBveyfJu7dydKKWpofQ0Pide0kcUK/QnXzZHZBbr5BN"
    "SRzQnV2vkHsdkJtNXK9w2ahXBws/ojcPPw+oVzeiBwtbNw+vN6IHCAcIWzc/ogevfniQR05YUk53UE5+SFhCnjdwDElFUNkvedxP"
    "NUBQKQcbah/rfQSA/Y39G2p/BBDra4/tHXoE8Bv6G2uPfQTgHYvzVip+Y2su+mYujnNjK1tWKm4ue2OL8y6OI1t6Y/tmleXKSvpL"
    "lwqEbaqOi2QH7o6L7aSOZGcKAC0lC4lJYq8nioJyqFvVoiw89kzAXCsq+BEjhCyoc9ByKKqHoluF0u1zfjzcIWdctP7K+Xx68k7+"
    "vE7EeXry+gOc0DINGWmfzeTJXr11MffuOVfNtHXxzclePfe9dcHkV830zb514TlEU4neUQRBg0GDRFNZBIHeXknTQVMEgYSDhF5J"
    "UwTRQXcOs5CAN2eBAGORcI43h7ezkGCBhzd3DpFwjreANwdj34/08o72Qn9Of9+PhPby8oJE/96P9nL/f/+CRI/28t7JE8y4fPPF"
    "BxjMt8xz8wXJACOSE3Z44j6SmXPR4vzs4eVdcvhaVXjhERZmwyYk5UzMFkZhIyQV5hPmzBYmJEVhffZqw/fBvlCb0TtmD8BnqABw"
    "nMn4LHeR2I17iKxR8cPfh4WSdInMJGugWFNkkl9zgsWU1HeJLI+owc4LS78gNNcyfmDAO1PBB1lS5JZi6r7gv5ZGoazbJpCzBcC7"
    "uk2DQ5V8MJJziG3XHT+7F3ZJ6OhJHbsX13Y/bYiVMJJDc3x8c4gwkm1DlZVDczCSfG2IFkzq9wJx9rM/dkm7F+jXHex2BJR5GjRs"
    "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"
    "1uGAdN/PTXeJnP3O38+cTc6Jd/3fz4mc/c5Nd9/Pzol3/ZxNkcPXh6XYfJeRw9jXl6WHfJHDpdh8l9eHkcOXpYd82NeUOVqwNwMX"
    "JpQ5A1omN7AXlDk3AxcmWrBDroOwN4bAgnwspHHuoT+zfCyhpLPucT98LO6hP7OkcXwss+5xP6GkDpM4FgJvAgQOk284BAIWAg6T"
    "Am8CBDgWDpMEAhYCbziIcfTMtrcPxohxt/TGtswPRMcBuABOhThEx04BOAC4hb0fRsWo+Z4gvR/5RiCoxZ69H6j5niBGxWrIsWtS"
    "O37Rb/KcG9ZRdNtv8lGc29YbdG/y1lF025wbb/Lb1ht0UZx3q7v+OpDnenerkLt6Ov7nd6s6kOd6u/53q3o6/ueQu+RDCG+/Cogp"
    "5EMKCCm/b4inS9C1gqGAi0MIqb80iD2pzMx4Qi2hguTMzKF45C1CgszMLaGC5HhCbU4AVRfv71XizpUJt7m9uuLOuZW6twm94s63"
    "ub26lQnizrq3Cb25lZH2lrIjXfi+kfZdlr4jsviR9iNd+L6WspH2viOy+F2W1/GFamQDQN7X8QOF3mRqQLhObovIOsZiuE46bmLI"
    "i8Z14ajwvWYHSnXhZqhKvfAHdeG9ZgdKqPB14Uq98AdmqLSvrhM4JvhgtK8mrmA4E/i0rzgm+GCuE7SvYDgT+CauV0r/AI0MozRX"
    "Sgz/NI0Ao1dKjQyjNP8AV0o0jQCjDP94UOJjhnH6WXhQceJZhmP6eFCGcfpZ4mN4UFmGY/px4iQ+3c+NC7CCJD4L3YKNz7AkPo0L"
    "sILdzyQ+go3PsAvdVNCV1BV9PUtU0H2VSxXUPeRgMUM2lhff5GCWMd82QxeAFzTLfLIqW0+nuX8PrF6nT6esuacPf15Ppw+sXqe5"
    "f8W2KTKEdhicxbZ2KZyEMhgnVPwmQRpKaydUGvxrQSZKMfrAOusVAJWtfiersr/GKa1+vycpsqvGrX6yv8YpJ6uFiFtuFRjWw0A+"
    "MWlHY3ZKQD5jMUpHaXZAPkdjdkoxaeavbYxyNt/b5q82bdtyjN/mr3I239ttjOav23KM3zZtd7mHlG4m6bfOPrLpkYcKns4+h7Ke"
    "kekKzj6RhwqesukDInXvhfjfHQMi+HUdhe/fAyKF+N8dde8DIh2F79/4dZp+eeDTN27tmn43ee3T4G6aftM3bu154Jp+7dPgbjd5"
    "/f6aE6TD1qr9/sOaqqQT1pPJDj4oMInzk8kwDvMoPonNm4Tq341/Vs2bjYRW3+p/tHYMbZ/M+t20dswM3Z9t+lxe+W1qPAOdX2Fj"
    "mP7ykz9fYfJjP/6Yk19h/vKTP2OYCA2NTydqaXoIDWqNeidPabx7Kwf2tneSvHu2K5L2B3f1CtnEl90BufUK3dm5l8QB9QqX3QG5"
    "2cT1CrmXxAHd2SN68HqAsHXzI3qw8POAenUjeoCwdfPweiN684B6dbDwhCXkeQfl5IeEJeXkhwd55ASVcpDH/VQDBJX9cgPHkFRH"
    "AN6hv7H22EcAsd7Yv6H2RwC/sfbY3qFHANi/ofax3je2sqVv5uI4N7bmsjhvpeI3tm/m4jiypTe2OG+l4uaymCT2CtBSspBIduBO"
    "2KbquEh2puC42E7qv3SpUFmurKTMtaLCwmPPBLpVLXqiKCiHulUoLYeieiiCOgeNHzFCyJCR9jnACS3TpyfvROuvnM+nJ6/vz+tE"
    "nB1yxtU+58fDWxff7J5z1UxbF3PfTJ7s1VsXnnPVTN/sWxdMnuzVc99FEB00SOiVNEUQ6B00SDSVRRBI6JU0HTRFEDRINJXoHXhz"
    "eAswFgnneHMWeOcwCwl4czAWCed4C3hz5zALCRZ4aC/v/fcvSPRoLy/v9Pf9SGgv9y9I9O/9aC/09/1IL+83X5CMwXzLPDdffJA8"
    "wYzLzs8eLpk5Fy2HJ+4DMCI5YUJSFDZhzmxhQlLOFGFhNmxCUmHObGEUNlWFF17eJYevAHyGuhm9Y/Yf7AvVZ682fBoVP4zduIfI"
    "z3IXCQDHmYz0C0KDGuy8sCb5NbcGijVFl8jyKFhMSX2XyEzyfVgoSSmm7nuQJUVuvDMVfC3jBwar2zQIOVsAvMq6bQL+a2kUOTTH"
    "14ZYCSNhl4R+3fGze3Ft94Oe1LF7OYfYNlTJByPJ14ZYOTQHI9k2VMk3hwgjgX7d8WOXtHsQZz9rwaR+L8euQcBGY0eZ1Px0GbqT"
    "vY8U2px9+bSzj6dBw8ZuR0CZR8BGY8euQZnHxm5HoEFDmXQZupPd/LSP9LQT2px9uY86lBfGCErnz3kY+i0lVZAPKXVY8B0qlQ9N"
    "UZOxTCTC9hrGCEo3lOfPyjhEF5YH6s/5LSVVcBiaD4PX0aHkjxQbG2nLOPVhC2mPEPQfWi6c5h+KIPwfVJ7mlC8tn11/e9DLOPVh"
    "G2kLaTsVacto+wFpC6tJ9BBtLWkfVB6KIPyf5qFVYj2mDwvJ/yvxNgBff1g/8Fv/JgF/WFGiP6YFaw3JYT2mD6tVAskxpgVrXaIP"
    "yf82AF//K3FYLwE/8Fv/dlho8orLrY4A2PMLArP2H9E0s/YbAQPy3zQLtT9mgDPd7CEE/LwG/1HaAQy/JvTxXNoDs/Yf8QvSNAPy"
    "v/YbAdM04uNQ/IZM2a2RNLFeMjJHJFKQ5oM9wlkl4oD85kNZ3K1S/IZM6ePQrfLmQ1nsgNytgl3A6ZM2UiUxMVKSNLdOJMzZ5Jx4"
    "1//9Dkjn820dLtX+DRjuQ2ct1dx0l8jZ7/z97Jx418/Z9P2cyNnv3HT3/e7zbR0OSCfVTmf9DRjuI9UzoGVyA3tBmYx9fVl6yBc5"
    "XIrNd3l9GDmjBXszcGFCmToIe2MILDjkczNwYaIFS5l8WXrIh30dOXx9WIrNdxk5+YZDIGAh4DASSjrrHvfDx+Ie+jNLGsfHiWMh"
    "8CZA4DBJIGAh8IbjMCnwJkCAY+EwMuse9xNKysdCGuce+jPLx5FvBIJa7Nn7d0tvbMv8gBgcgAvgVIhDdGFUjJrvCdL7HLsmteMX"
    "rYaBmu8JYlTc++wUgAOAW0h0R89se/tgjBgKuaun439+tx/FuW29Qfcmbx1Ft8258Sa6668Dea53t6qn438OuXu3qgN5rrfrf7e/"
    "bb1BF8X5Js+5YR1Ft/0mHIpH3iIkyMykgJDy+4ZIPgRdKxgKuHi6jCfUEipIzswEUHXx/l7V5twSKkiOJ8TMkPpLg9iTOoSE8Par"
    "gJhCPt9l6Tsiix9pnFupe5vQK+58m9urW5kg7m8pO9KF7xtp7zsii99lGWk/0oXvaykbaax7m9CbWynuXJlwm9urK+5uhqrUC39Q"
    "Fz9Q6E2mBnQd5LaIrGMshuuOCt9rdqBUF67UC39ghloX3mt2oIQKXxek4yaGvGiM61+oRjYA5H0dxPBP0wgweqVq4gqGM4FP+4pj"
    "gg/mOkH79A/QyDBKc6VE0wgwyvB/pdTIMErzD3ClCoYzgW/iSvvqOoFjgg9G+7PQLdj4DEviFSeeZTimjwdlGKefJT6GB9P93LgA"
    "K0jiI9j4DLvQTeLTuAAr2P1M4pVlOKYfJ44HJT5mGKefhQea+/fA6nX6dN1XuVRB3UMFFjNkY3nxTQ5Bs8wnq7IFePrA6nWa+/d0"
    "ypp7+vDn9XRmGfNtM3RBDl1JXdHXs0QFd7Iq+2uc0uprl8JJKINRbMVvEqShtHZCD6yzXgFQGaMn+2uccrLa6vd7kiK7atzqpcG/"
    "FmSidEKbIkNoh8FZbGrTti3H+G3+E5N2NGanBOQzFqN0lGYH5NrGKGfzvW3+ui3H+G3TZv4qZ/O93cZo/nM0ZqcUkwbkuOVWgWE9"
    "XIiCX9dR+P49ICObHnmo4OnscyjrGZmu4OxS916I/90xINJR+P6NXzcgUoj/3VH3PiATeajgKZvu7HtI6WaSfnuXP6ypSjph3e93"
    "k9c+De6m6Td949aeB67przlBOmyt2u8M4zCP4pM4mezggwKTOD+Z1z4N7naTp+mXBz5949au6TaG6S8/+fMV2Uho9a3+17zH0PbJ"
    "rN9Na5XfpsYz0Mnl5i8/+TOG+RUmP/bjjzn5FcfM0P3Zpk9rSaj+3fhn1bzQnZ17SRxQr6DWqHfylIbQt3Jgb3snybuQTXzZHZBb"
    "r5B7SRzQnV2vcNkdkJtNXK9nuyJpf3DHu9D4dKKWpofQUk5+eJBHTlgHCz8PqFc3ogcIWzcPrzeiQp53UE5+SFjZLzdwDElFUCkH"
    "edxPNUBQNw+oVwcLP6IHrwcIWzc/omsui/NWKn5jEOuN/RtqfwTwG2uP7R16BCtb+mYujnNji/NWKm4ue2P7Zi6OI1t6Y4D9G2of"
    "630E4B36G2uPfQTVoieKgnKoWwfuhG2qjotkZwqOi+2kjmQrKiw89kzAXHPQ+BEjhCyohdJyKKqHoluXCpXlykr6S2KvAC0lC4lJ"
    "MffN5MlevXXyTrT+yvl8evL6/rxOxHl68c3uOVfNtHXB5MlePfe9deE5V830zb51Z1ztc3483CFpnwOc0DINGWeBdw6zkIA3gd5B"
    "g0RTWQSBhF5J00FTBIe3AGORcI43dw6zkGCBhzcHY5FwjreAN0GDRFOJ3lEE0UGDhF5JUwTFB8kTzLh88/LyTn/fj4T2cv+CRP/e"
    "j/YFyRjMt8xz8+I+ACOSE3Z47OGSmXPR4vxCf9+P9PKO9vLef/+CRI/2vlB99mrD98HlTBEWZsMmJBXmzBZGYSMkZ6ib0TtmD8B3"
    "kQBwnMn4LPHD2I17iKxReOHlXXL4WlVFYRPmzBYmJFPB1zJ+YMA7X3NroFhTZJIsj4LFlNR3ieq+B1lS5JZi2ybgv5ZGoaxNg5Cz"
    "BcC7uswk34eFknSJIDSowc4LS7+btEeBh1cfraCqCsku0Aeo"
)

class SM3:
    def __init__(self, data=b""):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._data = bytearray(data)

    def update(self, data):
        self._data.extend(data)

    def digest(self):
        # Chaquopy/FongMi 环境未必带 cryptography；保留纯 Python SM3 回退。
        if hashes is not None and hasattr(hashes, "SM3"):
            digest = hashes.Hash(hashes.SM3())
            digest.update(bytes(self._data))
            return digest.finalize()
        data = bytes(self._data)
        bit_len = len(data) * 8
        data += b"\x80"
        data += b"\x00" * ((56 - len(data) % 64) % 64)
        data += bit_len.to_bytes(8, "big")
        iv = [0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
              0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E]
        def rol32(v, n):
            return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF
        for off in range(0, len(data), 64):
            block = data[off:off + 64]
            w = [int.from_bytes(block[i:i + 4], "big") for i in range(0, 64, 4)]
            for j in range(16, 68):
                x = w[j - 16] ^ w[j - 9] ^ rol32(w[j - 3], 15)
                w.append((x ^ rol32(x, 15) ^ rol32(x, 23) ^ rol32(w[j - 13], 7) ^ w[j - 6]) & 0xFFFFFFFF)
            w1 = [w[j] ^ w[j + 4] for j in range(64)]
            a, b, c, d, e, f, g, h = iv
            for j in range(64):
                tj = 0x79CC4519 if j < 16 else 0x7A879D8A
                ss1 = rol32((rol32(a, 12) + e + rol32(tj, j % 32)) & 0xFFFFFFFF, 7)
                ss2 = ss1 ^ rol32(a, 12)
                ff = a ^ b ^ c if j < 16 else (a & b) | (a & c) | (b & c)
                gg = e ^ f ^ g if j < 16 else (e & f) | ((~e) & g)
                tt1 = (ff + d + ss2 + w1[j]) & 0xFFFFFFFF
                tt2 = (gg + h + ss1 + w[j]) & 0xFFFFFFFF
                d, c, b, a = c, rol32(b, 9), a, tt1
                h, g, f, e = g, rol32(f, 19), e, (tt2 ^ rol32(tt2, 9) ^ rol32(tt2, 17)) & 0xFFFFFFFF
            iv = [(x ^ y) & 0xFFFFFFFF for x, y in zip(iv, (a, b, c, d, e, f, g, h))]
        return b"".join(x.to_bytes(4, "big") for x in iv)

xtime = lambda a: (((a << 1) ^ 0x1B) & 0xFF) if (a & 0x80) else (a << 1)

def rol(num, shift):
    shift %= 32
    # Perform the left rotation
    return ((num << shift) | (num >> (32 - shift))) & 0xFFFFFFFF

def rl8(x: int, k: int) -> int:
    n = 8
    s = k & (n - 1)
    return ((x << s) | (x >> (n - s))) & 0xff

def ror32(value, count):
    count %= 32
    low = value << (32 - count)
    value >>= count
    value |= low
    value &= 0xFFFFFFFF
    return value

def ror(value, count):
    count %= 64
    low = value << (64 - count)
    value >>= count
    value |= low
    value &= 0xFFFFFFFFFFFFFFFF
    return value

def get_key_hash(key, rand):
    to_hash = bytearray(68)
    to_hash[:32] = key
    to_hash[32:36] = rand.to_bytes(4, byteorder='little')
    to_hash[36:] = key

    d1 = (rand >> 16) & 0x000000ff
    d2 = (d1 << 11) | (rand >> 24)
    d2 ^= (d1 >> 5) ^ d1
    d2 = ~d2 & 0xffffffff

    return SM3(to_hash).digest(), d2.to_bytes(4, "little")

def split_blocks(message, block_size=16, require_padding=True):
    assert len(message) % block_size == 0 or not require_padding
    return [message[i:i + 16] for i in range(0, len(message), block_size)]

def add_round_key(s, k):
    for i in range(4):
        for j in range(4):
            s[i][j] ^= k[i][j]

def add_round_key_con(s, k, con):
    for i in range(4):
        for j in range(4):
            s[i][j] ^= k[i][con[j]]

def bytes2matrix(text):
    """ Converts a 16-byte array into a 4x4 matrix.  """
    return [list(text[i:i + 4]) for i in range(0, len(text), 4)]

def xor_bytes(a, b):
    """ Returns a new byte array with the elements xor'ed. """
    return bytearray(i ^ j for i, j in zip(a, b))

def matrix2bytes(matrix):
    """ Converts a 4x4 matrix into a 16-byte array.  """
    return bytearray(sum(matrix, []))

def mix_single_column(a, i):
    t = a[0][i] ^ a[1][i] ^ a[2][i] ^ a[3][i]
    u = a[0][i]
    a[0][i] ^= t ^ xtime(a[0][i] ^ a[1][i])
    a[1][i] ^= t ^ xtime(a[1][i] ^ a[2][i])
    a[2][i] ^= t ^ xtime(a[2][i] ^ a[3][i])
    a[3][i] ^= t ^ xtime(a[3][i] ^ u)

def mix_columns(s):
    for i in range(4):
        mix_single_column(s, i)

def inv_mix_columns(s):
    for i in range(0, 4):
        inv_mix_single_column(s, i)

def inv_mix_single_column(a, i):
    u = xtime(xtime(a[0][i] ^ a[2][i]))
    v = xtime(xtime(a[1][i] ^ a[3][i]))
    a[0][i] ^= u
    a[1][i] ^= v
    a[2][i] ^= u
    a[3][i] ^= v

    mix_single_column(a, i)

s_box = b''.join([
    b'\xFA\x7D\x08\x6B\x9C\x59\xB3\x4B\x04\x5F\x39\xD0\x38\x4A\x91\x99',
    b'\x00\x67\xA6\x20\x9F\xF5\x4D\x82\x73\x26\xEE\xDF\x18\x66\x83\x33',
    b'\x80\x03\x19\xFB\xD9\xFE\xAE\xAA\xA9\xB0\x52\xC6\x0B\xF3\x79\x25',
    b'\x4E\x78\xB4\x36\xAC\x5D\x1A\x27\x9E\x88\xDB\xBD\x3C\x63\xEC\x49',
    b'\x15\xC1\x30\x1F\xDC\xB8\x56\xD4\x6C\xCD\xCA\x09\x43\xC8\x35\xA3',
    b'\xEF\x1E\xF4\x96\xD2\xFC\x0E\x72\x7B\x94\x84\xD1\xEA\x45\x5A\x62',
    b'\x02\x3F\xD3\x12\x81\x34\x2B\xDD\x7E\xE6\x28\xF2\xA5\x46\x13\x01',
    b'\x3B\x21\xF6\x61\x37\x29\x2A\x0D\xED\x8C\xAF\xBF\x9D\x5C\xBB\x24',
    b'\x76\x0F\x75\xE4\x53\x89\xE1\x98\x8D\xB1\x9A\x65\x70\x4F\x54\x4C',
    b'\x58\xAB\x6E\x6F\x8B\x23\xC4\x07\x11\x0C\xBA\xCF\xA0\xA4\x8E\xD8',
    b'\x05\x3D\x14\xB2\xDA\x74\xC3\xD7\xE7\xBE\xD6\x7F\xDE\x48\x16\x3E',
    b'\x85\x90\xA1\x55\xB7\x77\x42\x22\xC9\x86\x50\x2E\x17\xF9\x64\x31',
    b'\x2C\x9B\xF1\x6D\x1C\x44\x68\xE3\xE9\xA8\x93\x97\xCB\x32\x57\xEB',
    b'\xE5\x71\x6A\xAD\xC0\xCC\xC7\xC5\xFD\x60\x1D\xA2\x2D\x47\xA7\xE2',
    b'\x51\x69\x5E\x7A\xCE\x0A\x41\xB6\x95\x8F\xF7\xB9\x87\xE0\x3A\x06',
    b'\x10\x8A\xB5\xF8\x5B\xD5\xF0\xBC\x92\xFF\x7C\x2F\xC2\xE8\x1B\x40',
    b'\xEC\x1B\xDA\xBD\xBA\x98\x91\x0C\xB2\x2B\x83\x41\x34\x67\xFB\x0A',
    b'\xD8\x76\xB5\x46\x05\x59\x61\x23\x75\x90\x87\x2A\xE3\x50\x15\x4C',
    b'\xAC\xB1\x79\xEB\xAE\xE5\x95\x47\x04\x68\xF0\x86\x3D\x51\x8B\x0F',
    b'\xCA\x8E\xE4\xB9\x4E\xF2\x12\x82\xBC\x0E\xD5\xF7\xEF\x28\x25\xCF',
    b'\x5B\x5D\xE9\x6A\x55\x02\xE1\x33\xBE\x93\xE7\xF5\xAD\x9D\x3E\x39',
    b'\x24\xA8\xE2\xFA\x17\x57\xD0\x7A\x0D\x08\x30\xD6\xB8\xA3\x8D\xFD',
    b'\x07\x9A\xC4\x1E\x6E\x22\x64\x97\xD2\x1D\xB0\xBF\x45\x66\x3F\x6C',
    b'\xDD\xDB\x27\x80\xA7\x11\xDC\xA6\xC5\x52\xF8\xC0\xB6\xC8\x5C\x00',
    b'\x73\x60\x7B\xA0\x19\x13\xAA\xC9\x35\x48\x4B\xD3\xA4\xCD\x9F\x99',
    b'\xF3\x10\x44\x40\x54\x7E\x29\xF4\x06\x1F\xA2\xAB\xA1\x2F\x3C\xF6',
    b'\xAF\x85\x62\x36\x21\x7F\x5E\xDF\x20\x1A\xB3\xB4\xE6\xFF\x72\x84',
    b'\x8F\x65\x26\x94\x5A\x77\xEA\x43\x78\xC7\x4A\xCC\x2C\x14\x6B\xC6',
    b'\xE8\x74\x53\xFC\xD4\x1C\xCE\x31\x70\x03\x18\x8C\x96\x38\x32\x89',
    b'\xF1\x3A\x5F\xD7\xF9\xA9\x69\xB7\x63\x37\x58\xC2\x3B\xC3\x71\xCB',
    b'\x9E\x92\x01\x8A\x0B\x4D\x88\x9B\xBB\x4F\x6D\x6F\xE0\xFE\xA5\x49',
    b'\xDE\x56\x16\x09\xED\x9C\xC1\x2D\xEE\x81\x7D\xD9\x7C\xD1\x2E\x42',
    b'\x5B\x4D\xC1\xA6\x5D\xEA\x44\xFD\x45\x4E\x1B\xA1\x3F\xD1\x89\xE1',
    b'\x7D\x2F\xAA\xDB\xAB\xAD\x59\xCB\xB1\xCE\x9A\x28\xC9\xE0\xF6\x70',
    b'\x39\x4A\xD7\xFF\x30\xF5\xDD\xBC\x57\x3B\x11\x8D\xB2\xEE\x00\xB6',
    b'\xE6\x1A\x5A\x7C\xF9\xDE\xC4\xCD\x2E\x80\xBB\xB9\x4C\xA5\x9F\x84',
    b'\x08\xC6\x6F\x42\x6C\xF0\x27\xE7\x8B\x3A\x9C\x51\xFB\x67\x21\x75',
    b'\x41\x31\xA7\xCA\x20\x43\x2A\xB7\xBF\xD9\x7A\xF2\xB5\xF8\x8C\x2C',
    b'\x23\x83\x4F\x8F\x60\xA0\x04\x13\x37\x14\xE3\x01\xC5\x63\x66\x5C',
    b'\x74\x81\xDF\x58\xBD\x68\x90\x3D\xD2\xB3\x34\xF4\x19\x93\x32\x29',
    b'\xD6\x49\xAE\x0D\x4B\xD8\x07\x9E\xAC\x1E\x2D\x0B\x40\xB8\x72\xBA',
    b'\x76\x10\x71\xA8\xE4\x56\x1D\x48\xFE\xE5\xC2\x47\x91\xDA\x87\x26',
    b'\x9D\x1F\x88\x6B\xC0\x98\xBE\x25\x09\x97\x33\xA3\x85\x16\x5E\x7F',
    b'\xDC\x6E\x54\xE9\xF7\xA9\xC8\xE8\xC3\x77\xD0\x82\x2B\xEC\x02\x62',
    b'\x8A\x92\x0E\x3E\xB0\x0F\x05\xF3\xF1\x96\x78\x38\x86\x36\x18\x3C',
    b'\x24\xCF\x0A\xB4\x53\xCC\x61\x65\xA4\xC7\x94\xD5\x15\x7E\x6D\xEF',
    b'\x79\x22\x35\x12\x6A\x8E\x52\x06\x55\x7B\x46\x64\x50\x95\xE2\x0C',
    b'\xED\xD3\x17\x03\xA2\x9B\x99\xEB\x1C\xFC\xAF\xD4\x73\x69\xFA\x5F',
    b'\xF7\x2C\x1E\xBF\xC8\xE1\xF3\x9F\x76\x80\x71\x48\xAA\x94\xAD\x64',
    b'\xFB\x89\xC6\x60\xC3\x32\xB3\x4D\xD2\xE0\x44\xDD\x5F\xA8\xB1\xC7',
    b'\x68\x23\x34\xC9\x6D\x12\x7F\xB7\xEB\x15\xBE\xA9\xD1\x78\x93\xA0',
    b'\x0C\x92\xA4\xD7\x47\xE3\x8A\xC2\x70\xAB\x26\x41\x9A\x79\xA7\xD8',
    b'\x14\x85\x8F\xC0\x6F\x56\xD0\x8C\x11\xB9\x2E\x3C\xE2\x9D\xCF\x0E',
    b'\xDE\x03\x5D\x46\x3E\xCD\x38\x43\x0F\x33\x5A\xD9\x1A\x65\x6C\x22',
    b'\x3B\xFC\x30\xA6\x88\xEA\x37\xA2\xB4\x8D\x8E\x51\x9C\xD6\x40\xEE',
    b'\xF9\xF8\x84\xF4\xAE\x97\xE9\xCA\x0A\x45\x67\x57\x04\x2F\x83\x5C',
    b'\xD5\xC5\xC4\x82\xB6\xA3\x91\x98\x1F\x4A\xAC\x96\x81\x6E\xCB\x1B',
    b'\x09\x08\xAF\x18\x95\x49\x7D\x54\xED\xFA\x16\x31\x3A\xDA\xB8\x66',
    b'\xF5\xA5\xF1\xFE\x10\x01\x06\x74\xCC\x63\xDF\x7C\x28\x25\xF6\xCE',
    b'\xB2\x4F\x8B\xE5\xBC\x87\x69\xBB\x86\x21\x07\x00\x36\xE7\x0B\x50',
    b'\x59\x9B\x1C\xE8\x62\x58\x19\x61\xF2\xBD\x27\x5E\xBA\x1D\xE6\x99',
    b'\x42\x3D\x0D\x2A\xB5\xDC\x5B\x29\xF0\x2D\x4C\x53\x7B\x6A\x73\x4E',
    b'\x3F\x75\xFF\x4B\xA1\x35\x17\x55\x72\x39\x20\xD3\xB0\xFD\xEF\x02',
    b'\xEC\x77\x7E\xE4\x2B\xDB\x90\xC1\x05\x9E\x7A\xD4\x52\x6B\x24\x13'])

inv_s_box = bytearray(1024)

class AES_V3():
    r_con = [[1, 0, 2, 3], [1, 3, 0, 2], [0, 1, 3, 2], [1, 0, 2, 3]]
    r_con2 = [[1, 0, 2, 3], [2, 0, 3, 1], [0, 1, 3, 2], [1, 0, 2, 3]]
    r_orders = [[0, 9, 14, 11, 4, 13, 2, 7, 8, 1, 6, 15, 12, 5, 10, 3],
                [0, 9, 14, 15, 4, 13, 2, 7, 8, 1, 6, 3, 12, 5, 10, 11],
                [0, 9, 14, 7, 4, 13, 2, 11, 8, 1, 6, 3, 12, 5, 10, 15],
                [0, 9, 14, 11, 4, 13, 2, 7, 8, 1, 6, 15, 12, 5, 10, 3]]

    def __init__(self, aes_key, khronos):
        self.word_size = khronos & 3  # khronos - (khronos & -4)
        self.aes_key = aes_key

        self.s_box = s_box[self.word_size << 8:]
        self.inv_s_box = inv_s_box[self.word_size << 8:]

        self.master_key = self._expand_key()
        self._key_matrices = bytes2matrix(self.master_key)
        self.con = self.r_con[self.word_size]
        self.con2 = self.r_con2[self.word_size]

        self.order = self.r_orders[self.word_size]

    def _expand_key(self):
        init_values = [0xca025ddc, 0x823dc546, 0xc9420583, 0xc298225f]
        init_value = init_values[self.word_size]
        mk = bytearray(init_value.to_bytes(4, "little"))
        mk = mk * 4

        mk = xor_bytes(mk, self.aes_key)
        mk += bytearray(32)

        rounds = 8

        for i in range(4, 12):
            idx = 4 * (i - 1)
            k0, k1, k2, k3 = mk[idx], mk[idx + 1], mk[idx + 2], mk[idx + 3]

            if i & 3 == 0:
                k00 = (init_value >> (rounds & 24)) ^ self.s_box[k1]
                k1 = self.s_box[k2]
                k2 = self.s_box[k3]
                k3 = self.s_box[k0]
                k0 = k00 & 0xff
            rounds += 2

            mk[idx + 4] = k0 ^ mk[idx - 12]
            mk[idx + 5] = k1 ^ mk[idx - 11]
            mk[idx + 6] = k2 ^ mk[idx - 10]
            mk[idx + 7] = k3 ^ mk[idx - 9]
        return mk

    @staticmethod
    def sum_data(data):
        key = bytearray(32)
        for i in range(31):
            idx = i * 8
            n0 = (data[idx] >> 4) & 2
            n1 = n0 | data[idx + 1] & 64
            n2 = n1 | (data[idx + 2] >> 2) & 1
            n3 = n2 | (data[idx + 3] << 3) & -128
            n4 = n3 | (data[idx + 4] >> 1) & 4
            n5 = n4 | (data[idx + 5] << 3) & 16
            n6 = n5 | (data[idx + 6] << 5) & 32
            n7 = n6 | (data[idx + 7] >> 4) & 8
            key[i] = (n7 & 0xff)

        key[31] = 1
        return key

    @staticmethod
    def mix_columns(data, key):
        data = bytearray(data)

        for i in range(31):
            kk = key[i]
            idx = i * 8
            # print(k, data[idx + 1], (data[idx + 1] & -65) | (k & 64))
            data[idx + 0] = (data[idx + 0] & -33) | ((kk << 4) & 0xff & 32)
            data[idx + 1] = (data[idx + 1] & -65) | (kk & 64)
            data[idx + 2] = (data[idx + 2] & -5) | ((kk * 4) & 4)
            data[idx + 3] = (data[idx + 3] & -17) | ((kk >> 3) & 16)
            data[idx + 4] = (data[idx + 4] & -9) | ((kk + kk) & 8)
            data[idx + 5] = (data[idx + 5] & -3) | ((kk >> 3) & 2)
            data[idx + 6] = (data[idx + 6] & -2) | ((kk >> 5) & 1)
            data[idx + 7] = (data[idx + 7] & 127) | ((kk << 4) & 0xff & -128)

        return data

    def encrypt(self, data, iv):
        plaintext = self.sum_data(data)
        blocks = []
        previous = iv
        for plaintext_block in split_blocks(plaintext):
            x = xor_bytes(plaintext_block, previous)
            block = self.encrypt_block(x)
            blocks.append(block)
            previous = block

        key = b''.join(blocks)
        # key = bytes.fromhex('a22c23b05bb4a831d31bbdbd1327c5f84991bca3e7d8df24e52f58b7ac61f2e0')
        # print("sign_key", key.hex())
        data = self.mix_columns(data, key)
        return key[-1:] + data

    def encrypt_block(self, plaintext):
        # print("b000", plaintext.hex())
        plain_state = bytes2matrix(plaintext)

        add_round_key_con(plain_state, self._key_matrices[0:4], self.con2)
        # print("b001", matrix2bytes(plain_state).hex())

        for i in range(1, 3):
            self.sub_bytes(plain_state)
            # print("b003", matrix2bytes(plain_state).hex())
            self.shift_rows(plain_state)
            # print("b004", matrix2bytes(plain_state).hex())
            if i == 1:
                self.shift_rows_con(plain_state, self.con2)
                mix_columns(plain_state)

            add_round_key_con(plain_state, self._key_matrices[i * 4:], self.con2)

        add_round_key(plain_state, self._key_matrices[4:])

        return matrix2bytes(plain_state)

    def decrypt(self, ciphertext, iv, data):
        assert len(iv) == 16

        blocks = []
        previous = iv

        for ciphertext_block in split_blocks(ciphertext):
            dc = xor_bytes(previous, self.decrypt_block(ciphertext_block))
            # dc = matrix2bytes(dcm)
            blocks.append(dc)
            previous = ciphertext_block

        key = b''.join(blocks)
        # print("sign_key", key.hex())
        data = self.mix_columns(data, key)
        return data

    def decrypt_block(self, ciphertext):
        assert len(ciphertext) == 16
        cipher_state = bytes2matrix(ciphertext)

        # print("b000", matrix2bytes(cipher_state).hex())
        add_round_key(cipher_state, self._key_matrices[4:])
        #         print("b001", matrix2bytes(cipher_state).hex())

        for i in range(2, 0, -1):
            add_round_key_con(cipher_state, self._key_matrices[i * 4:], self.con2)
            #             print("b002", i, matrix2bytes(cipher_state).hex())

            if i == 1:
                inv_mix_columns(cipher_state)
                self.shift_rows_con(cipher_state, self.con)

            self.inv_shift_rows(cipher_state)
            #             print("b004", i, matrix2bytes(cipher_state).hex())
            self.inv_sub_bytes(cipher_state)
        #             print("b005", i, matrix2bytes(cipher_state).hex())

        add_round_key_con(cipher_state, self._key_matrices[0:4], self.con2)

        return matrix2bytes(cipher_state)

    def shift_rows_con(self, s, c):
        for i in range(4):
            # c = self.con
            s[i][0], s[i][1], s[i][2], s[i][3] = s[i][c[0]], s[i][c[1]], s[i][c[2]], s[i][c[3]]

    def shift_rows(self, s):
        bs = matrix2bytes(s)
        for i in range(4):
            for j in range(4):
                s[i][j] = bs[self.order[i * 4 + j]]

    def inv_shift_rows(self, s):
        order = bytearray(16)
        for i in range(16):
            order[self.order[i]] = i

        bs = matrix2bytes(s)
        for i in range(4):
            for j in range(4):
                s[i][j] = bs[order[i * 4 + j]]

    def sub_bytes(self, s):
        for i in range(4):
            for j in range(4):
                s[i][j] = self.s_box[s[i][j]]

        s[0], s[1], s[2], s[3] = s[self.con2[0]], s[self.con2[1]], s[self.con2[2]], s[self.con2[3]]

    def inv_sub_bytes(self, s):
        for i in range(4):
            for j in range(4):
                s[i][j] = self.inv_s_box[s[i][j]]
        s[0], s[1], s[2], s[3] = s[self.con[0]], s[self.con[1]], s[self.con[2]], s[self.con[3]]

def leftCircularShift(k, bits):
    bits = bits % 32
    k = k % (2 ** 32)
    upper = (k << bits) % (2 ** 32)
    result = upper | (k >> (32 - (bits)))
    return (result)

def blockDivide(block, chunks):
    result = []
    size = len(block) // chunks
    for i in range(0, chunks):
        result.append(int.from_bytes(block[i * size:(i + 1) * size], byteorder="little"))
    return (result)

def F(X, Y, Z):
    return ((X & Y) | ((~X) & Z))

def G(X, Y, Z):
    return ((X & Z) | (Y & (~Z)))

def H(X, Y, Z):
    return (X ^ Y ^ Z)

def I(X, Y, Z):
    return (Y ^ (X | (~Z))) & 0xffffffff

def FF(a, b, c, d, M, s, t):
    result = b + leftCircularShift((a + F(b, c, d) + M + t), s)

    return (result)

def GG(a, b, c, d, M, s, t):
    result = b + leftCircularShift((a + G(b, c, d) + M + t), s)
    return (result)

def HH(a, b, c, d, M, s, t):
    result = b + leftCircularShift((a + H(b, c, d) + M + t), s)
    return (result)

def II(a, b, c, d, M, s, t):
    result = b + leftCircularShift((a + I(b, c, d) + M + t), s)
    return (result)

def sum_md5(data):
    check_sum = 0x20220420
    for i in range(12):
        if i % 2 == 0:
            temp = (check_sum >> 3) ^ check_sum
            check_sum = data[i] ^ (check_sum << 7)
        else:
            temp = (check_sum >> 5) ^ check_sum
            check_sum = data[i] | (check_sum << 11)
            check_sum ^= 0xffffffff

        check_sum ^= temp
        check_sum &= 0xffffffff

    check_sum |= 4
    check_sum ^= 0x1000000
    return check_sum

SV2 = [0xa7aefe20, 0x7149f1d6, 0x47e4ca07, 0xe9b58f67, 0x93b924de, 0xc614d0f5, 0x38afe0ef, 0xb2bbad73,
       0xe24444c3, 0x9d3aec9b, 0xdf7b37e4, 0xd8b16d40, 0xf8ac31b8, 0x76b9a90b, 0x31d833ee, 0x953fce64,
       0x353595a4, 0x4609c13b, 0x36925008, 0x8c6d0925, 0x5df5c177, 0x1cfbf52b, 0x8a4fa7f0, 0x114ca35e,
       0x8193f984, 0x7a7a8733, 0x316ab4d5, 0x3c20cfc9, 0xa6d84453, 0x3a18500c, 0x798ec47a, 0x97a76b28,
       0x66c4ff96, 0x51716443, 0xdd2fc3b, 0xb5696da7, 0xbbeb3ac5, 0x5c53d204, 0xd32608ce, 0x7279b9ec,
       0xf4188ecf, 0xf7d793db, 0x332cc491, 0xab76ae15, 0x9bebe727, 0x18a01384, 0x5be9f8a7, 0x5f90a754,
       0x39b663c0, 0x36673c83, 0x7c92f514, 0x9d7d94d7, 0xe2e8d9aa, 0x5f7e9ea9, 0x7abd4551, 0x569e05da,
       0x40a25632, 0x3df5a9a5, 0xbab37d80, 0x454286dc, 0x3f5d4e78, 0x3d7b75d, 0xb1fe4af7, 0xa5ab26a3]

def md5sum_v3(msg, count_v2, orders, count_v1, n=0):
    count = count_v2 & 0xff

    sv = [0] * 64
    for i in range(64):
        sv[i] = ror32(SV2[i], count_v1)

    start = [
        ror32(0x79e0f2fb, count),
        ror32(0xc8b52570, count),
        ror32(0xebc2f8cd, count),
        ror32(0x7c104d93, count)
    ]

    count = (count_v2 + 6) & 0xff
    end = [
        ror32(0x19be4866, count),
        ror32(0xe85986b4, count),
        ror32(0xe19b326e, count),
        ror32(0x71d1d7d4, count)
    ]
    A = start[0]  # 0x79e0f2fb
    B = start[1]  # 0xc8b52570
    C = start[2]  # 0xebc2f8cd
    D = start[3]  # 0x7c104d93

    a = A
    b = B
    c = C
    d = D
    block = msg[:64]
    M = blockDivide(block, 16)

    order1 = orders[:16]
    order2 = orders[16:32]
    order3 = orders[32:48]
    order4 = orders[48:]
    # Rounds
    a = FF(a, b, c, d, M[order1[0]], 7, sv[0])
    d = FF(d, a, b, c, M[order1[1]], 12, sv[1])  # 0xb6bc6ddb
    c = FF(c, d, a, b, M[order1[2]], 17, sv[2])  # 0xf80b15d4
    b = FF(b, c, d, a, M[order1[3]], 22, sv[3])
    a = FF(a, b, c, d, M[order1[4]], 7, sv[4])
    d = FF(d, a, b, c, M[order1[5]], 12, sv[5])
    c = FF(c, d, a, b, M[order1[6]], 17, sv[6])
    b = FF(b, c, d, a, M[order1[7]], 22, sv[7])
    a = FF(a, b, c, d, M[order1[8]], 7, sv[8])
    d = FF(d, a, b, c, M[order1[9]], 12, sv[9])
    c = FF(c, d, a, b, M[order1[10]], 17, sv[10])
    b = FF(b, c, d, a, M[order1[11]], 22, sv[11])
    a = FF(a, b, c, d, M[order1[12]], 7, sv[12])
    d = FF(d, a, b, c, M[order1[13]], 12, sv[13])
    c = FF(c, d, a, b, M[order1[14]], 17, sv[14])
    b = FF(b, c, d, a, M[order1[15]], 22, sv[15])

    a = GG(a, b, c, d, M[order2[0]], 5, sv[16])
    d = GG(d, a, b, c, M[order2[1]], 9, sv[17])
    c = GG(c, d, a, b, M[order2[2]], 14, sv[18])
    b = GG(b, c, d, a, M[order2[3]], 20, sv[19])
    a = GG(a, b, c, d, M[order2[4]], 5, sv[20])
    d = GG(d, a, b, c, M[order2[5]], 9, sv[21])
    c = GG(c, d, a, b, M[order2[6]], 14, sv[22])
    b = GG(b, c, d, a, M[order2[7]], 20, sv[23])
    a = GG(a, b, c, d, M[order2[8]], 5, sv[24])
    d = GG(d, a, b, c, M[order2[9]], 9, sv[25])
    c = GG(c, d, a, b, M[order2[10]], 14, sv[26])
    b = GG(b, c, d, a, M[order2[11]], 20, sv[27])
    a = GG(a, b, c, d, M[order2[12]], 5, sv[28])
    d = GG(d, a, b, c, M[order2[13]], 9, sv[29])
    c = GG(c, d, a, b, M[order2[14]], 14, sv[30])
    b = GG(b, c, d, a, M[order2[15]], 20, sv[31])

    a = HH(a, b, c, d, M[order3[0]], 4, sv[32])
    d = HH(d, a, b, c, M[order3[1]], 11, sv[33])
    c = HH(c, d, a, b, M[order3[2]], 16, sv[34])
    b = HH(b, c, d, a, M[order3[3]], 23, sv[35])
    a = HH(a, b, c, d, M[order3[4]], 4, sv[36])
    d = HH(d, a, b, c, M[order3[5]], 11, sv[37])
    c = HH(c, d, a, b, M[order3[6]], 16, sv[38])
    b = HH(b, c, d, a, M[order3[7]], 23, sv[39])
    a = HH(a, b, c, d, M[order3[8]], 4, sv[40])
    d = HH(d, a, b, c, M[order3[9]], 11, sv[41])
    c = HH(c, d, a, b, M[order3[10]], 16, sv[42])
    b = HH(b, c, d, a, M[order3[11]], 23, sv[43])
    a = HH(a, b, c, d, M[order3[12]], 4, sv[44])
    d = HH(d, a, b, c, M[order3[13]], 11, sv[45])
    c = HH(c, d, a, b, M[order3[14]], 16, sv[46])
    b = HH(b, c, d, a, M[order3[15]], 23, sv[47])

    a = II(a, b, c, d, M[order4[0]], 6, sv[48])
    d = II(d, a, b, c, M[order4[1]], 10, sv[49])
    c = II(c, d, a, b, M[order4[2]], 15, sv[50])
    b = II(b, c, d, a, M[order4[3]], 21, sv[51])
    a = II(a, b, c, d, M[order4[4]], 6, sv[52])
    d = II(d, a, b, c, M[order4[5]], 10, sv[53])
    c = II(c, d, a, b, M[order4[6]], 15, sv[54])
    b = II(b, c, d, a, M[order4[7]], 21, sv[55])
    a = II(a, b, c, d, M[order4[8]], 6, sv[56])
    d = II(d, a, b, c, M[order4[9]], 10, sv[57])
    c = II(c, d, a, b, M[order4[10]], 15, sv[58])
    b = II(b, c, d, a, M[order4[11]], 21, sv[59])
    a = II(a, b, c, d, M[order4[12]], 6, sv[60])
    d = II(d, a, b, c, M[order4[13]], 10, sv[61])
    c = II(c, d, a, b, M[order4[14]], 15, sv[62])
    b = II(b, c, d, a, M[order4[15]], 21, sv[63])

    A = (A + a) % (2 ** 32) ^ end[0]
    B = (B + b) % (2 ** 32) ^ end[1]
    C = (C + c) % (2 ** 32) ^ end[2]
    D = (D + d) % (2 ** 32) ^ end[3]

    result = bytearray(
        A.to_bytes(4, "little") + B.to_bytes(4, "little") + C.to_bytes(4, "little") + D.to_bytes(4, "little"))

    result += sum_md5(result).to_bytes(4, "little")
    return result

def bxor(b1, b2):
    b3 = bytearray(len(b1))
    for i in range(len(b1)):
        b3[i] = b1[i] ^ b2[i]
    return b3

def get_iv(iv, data):
    for i in range(len(data)):
        if i & 1 == 0:
            iv = (iv >> 4) ^ iv ^ (iv << 6) ^ data[i]
        else:
            iv = ~((iv >> 7) ^ iv ^ (data[i] | iv << 12))
        iv = iv & 0xffffffff
    return iv

def hash_f13(query_sm3, body_md5_bytes, ts_bytes, khronos):
    iv = get_iv(0x20230928, query_sm3)
    iv = get_iv(iv, body_md5_bytes)
    iv = get_iv(iv, ts_bytes)

    iv_v0 = ((iv & 15) * 171) >> 9
    branch = (iv & 15) - ((iv_v0 * 3) & 0xff)
    if branch == 0:
        return branch_0(iv_v0, khronos, query_sm3, body_md5_bytes, ts_bytes)
    elif branch == 1:
        return branch_1(iv_v0, khronos, query_sm3, body_md5_bytes, ts_bytes)
    elif branch == 2:
        return branch_2(iv, khronos, query_sm3, body_md5_bytes, ts_bytes)
    else:
        raise Exception("no branch: " + str(branch))

def branch_0(iv_v0, khronos, query_sm3, body_md5_bytes, ts_bytes):
    tt01 = [0xc4a78580, 0xb3c0fd39, 0xc58c5686, 0xc9aa3ba7, 0xf5a7adf2, 0x963c2ed1]
    iv_v1 = tt01[iv_v0]

    count_v1 = (iv_v1 + khronos + 1) & 0xff
    count_v2 = (iv_v1 + khronos) & 0xffffffff

    tt02 = [0xebb64faf, 0x7aadcc2, 0xcf3187bf, 0xe01138ff, 0x6d0bfcff, 0x5a30a3be, 0xb41ad638, 0x34180eb8, 0xf233eb6f,
            0xb1a584cc, 0xccc30dc7, 0x47d1db51, 0xd55653de, 0x70a84fa1, 0x57473c12, 0xf76f0288, 0x2c077f0a, 0xda0dcad0,
            0xfbb86f6c, 0xfdc4cf00, 0x688a020d, 0xe676c6a6, 0x8cd6338b, 0x1a3c8d0e, 0xcce8b06b, 0x6ad0ed0b, 0xa0522717,
            0xdc71ac83, 0x2285db71, 0xd5b4dda6, 0x736f8650, 0x6560306c, 0x617ce2a6, 0xe423417e, 0xa40e143, 0x544e4032,
            0x88dffb2a, 0x716c1ae0, 0x4c467a88, 0x5b23bb3, 0xe1d0b866, 0xbaa3dcb8, 0xae3374d3, 0xc3381a50, 0x1702f75b,
            0xfe6da368, 0xf0b4cf48, 0x4e0ffbb8, 0x72aad10d, 0x26c53a3d, 0xf2bce0f6, 0xb4557581, 0x4a257fdd, 0x8c3182a2,
            0xab0b3b86, 0x3d5dfb14, 0x4f103634, 0xd37b52d7, 0x444eff16, 0xeb0a33d1, 0x6ca86f6e, 0x284ba7, 0x8387cfa,
            0x5fb37586]

    tt03 = [0] * 64
    for i in range(0, 64):
        tt03[i] = ror32(tt02[i], count_v1) & 0xffffffff

    n0 = (count_v2 + 2) & 7

    pad = bytearray(4)
    seed = bytes([0xfa, 0x45, 0x61, 0xd7])
    for i in range(4):
        v = int.from_bytes(bytes([seed[i], seed[i]]), 'little')
        v = v >> n0
        pad[i] = v & 0xff

    count_v2 = count_v2 & 0xff
    init_value = [
        ror32(0x7aba4fc8, count_v2), ror32(0x67166507, count_v2),
        ror32(0x6403fa00, count_v2), ror32(0x340f512f, count_v2),
        ror32(984304912, count_v2), ror32(3005047866, count_v2),
        ror32(2874125293, count_v2), ror32(2152413264, count_v2)
    ]

    data = query_sm3 + body_md5_bytes + ts_bytes + pad + bytes.fromhex(' 00 00 00 00 00 00 01 a0')
    di = [0] * (len(data) // 4)
    for i in range(len(data) // 4):
        di[i] = int.from_bytes(data[i * 4:i * 4 + 4], "big")

    di0 = di[0]
    for i in range(112):
        di1, di14 = di[i + 1], di[i + 14]
        r_di1 = rol(di1, 14) ^ rol(di1, 25) ^ (di1 >> 3)
        r_di2 = rol(di14, 13) ^ rol(di14, 15) ^ (di14 >> 10)
        di0 = di0 + di[i + 9] + r_di1 + r_di2
        di.append(di0 & 0xffffffff)
        di0 = di1

    if iv_v0 == 5:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 100, 2, 0, 3, 5, 4, 6, 7, 2, 1, 5)
    elif iv_v0 == 4:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 96, 0, 5, 6, 7, 3, 1, 2, 5, 4, 4)
    elif iv_v0 == 3:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 99, 3, 6, 2, 4, 5, 1, 0, 0, 7, 6)
    elif iv_v0 == 2:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 96, 7, 6, 2, 1, 4, 0, 5, 4, 3, 5)
    elif iv_v0 == 1:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 96, 0, 6, 7, 5, 3, 2, 1, 5, 4, 4)
    elif iv_v0 == 0:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 101, 5, 7, 6, 3, 2, 1, 0, 5, 4, 3)

    ret = bytearray(32)
    for i in range(8):
        ret[i * 4:i * 4 + 4] = ((v_j[i] + init_value[i]) & 0xffffffff).to_bytes(4, 'big')

    ret = bxor(ret[:16], ret[16:])
    sum = sum_md5(ret)
    ret += sum.to_bytes(4, "little")
    return ret

def swap_v0(src, src_xor, tt2, table_f, order1, typ=None):
    da0 = [0] * 8
    ha0 = src_xor[:]
    for i in range(8):
        da0[i] = src[order1[i]] ^ src_xor[i]

    for round in range(10):
        rr_0 = r00(ha0[0], ha0[1], ha0[2], ha0[3], ha0[4], ha0[5], ha0[6], ha0[7], 0, table_f)
        rr_1 = r00(ha0[1], ha0[2], ha0[3], ha0[4], ha0[5], ha0[6], ha0[7], ha0[0], 0, table_f)
        rr_2 = r00(ha0[2], ha0[3], ha0[4], ha0[5], ha0[6], ha0[7], ha0[0], ha0[1], 0, table_f)
        rr_3 = r00(ha0[3], ha0[4], ha0[5], ha0[6], ha0[7], ha0[0], ha0[1], ha0[2], 0, table_f)
        rr_4 = r00(ha0[4], ha0[5], ha0[6], ha0[7], ha0[0], ha0[1], ha0[2], ha0[3], 0, table_f)
        rr_5 = r00(ha0[5], ha0[6], ha0[7], ha0[0], ha0[1], ha0[2], ha0[3], ha0[4], 0, table_f)
        rr_6 = r00(ha0[6], ha0[7], ha0[0], ha0[1], ha0[2], ha0[3], ha0[4], ha0[5], 0, table_f)
        rr_7 = r00(ha0[7], ha0[0], ha0[1], ha0[2], ha0[3], ha0[4], ha0[5], ha0[6], 0, table_f)
        rr_7 = rr_7 ^ tt2[round + 1]

        d0, d1, d2, d3, d4, d5, d6, d7 = da0[0], da0[1], da0[2], da0[3], da0[4], da0[5], da0[6], da0[7]

        da0[0] = r00(d0, d1, d2, d3, d4, d5, d6, d7, rr_0, table_f)
        da0[1] = r00(d1, d2, d3, d4, d5, d6, d7, d0, rr_1, table_f)  # 0xd0a489b35ba678e8
        da0[2] = r00(d2, d3, d4, d5, d6, d7, d0, d1, rr_2, table_f)  # 0x3be5b7f9cfd44654
        da0[3] = r00(d3, d4, d5, d6, d7, d0, d1, d2, rr_3, table_f)
        da0[4] = r00(d4, d5, d6, d7, d0, d1, d2, d3, rr_4, table_f)
        da0[5] = r00(d5, d6, d7, d0, d1, d2, d3, d4, rr_5, table_f)
        da0[6] = r00(d6, d7, d0, d1, d2, d3, d4, d5, rr_6, table_f)
        da0[7] = r00(d7, d0, d1, d2, d3, d4, d5, d6, rr_7, table_f)

        ha0[0], ha0[1], ha0[2], ha0[3], ha0[4], ha0[5], ha0[6], ha0[7] = rr_0, rr_1, rr_2, rr_3, rr_4, rr_5, rr_6, rr_7

    if typ is None:
        src[0] = da0[0] ^ src_xor[0] ^ src[0]
        src[1] = da0[7] ^ src_xor[1] ^ src[1]
        src[2] = da0[6] ^ src_xor[2] ^ src[2]
        src[3] = da0[5] ^ src_xor[3] ^ src[3]
        src[4] = da0[4] ^ src_xor[4] ^ src[4]
        src[5] = da0[3] ^ src_xor[5] ^ src[5]
        src[6] = da0[2] ^ src_xor[6] ^ src[6]
        src[7] = da0[1] ^ src_xor[7] ^ src[7]
    else:
        src[0] = da0[7] ^ typ[1]
        src[1] = da0[6] ^ typ[2]
        src[2] = da0[5] ^ typ[3]
        src[3] = da0[4] ^ typ[4]
        src[4] = da0[3] ^ typ[5]
        src[5] = da0[2] ^ typ[6]
        src[6] = da0[1] ^ typ[7] ^ src[7]
        src[7] = da0[0] ^ typ[0]
    return src

def branch_1(iv_v0, khronos, query_sm3, body_md5_bytes, ts_bytes):
    tt1 = [0x808a9c79, 0xf079807e, 0xbadf79c5, 0xa785d3ff, 0x82d8438c]
    iv_v1 = tt1[iv_v0]

    c_v1 = (iv_v1 + khronos) & 0xff
    c_v1 = ror(khronos, c_v1)

    orders = bytes.fromhex('''05 07 01 02 04 00 06 03 00 05 02 04 01 03 07 06
    05 07 02 04 01 06 03 00 03 00 02 04 06 07 01 05
    04 05 00 03 06 02 01 07 00 00 00 00 00 00 00 00''')

    order1 = orders[iv_v0 * 8:iv_v0 * 8 + 8]

    iv_v1 = (iv_v1 + khronos + 1) & 63
    tt1 = [0x87aeea5dab37cd6b, 0x7ff48becb4f54087, 0xb0724c06706bbd5d, 0x1fe5dfb1143e328d,
           0x1a2331d00af4f1f2, 0xcaff7131bb1e71ba, 0x33385e1042752218, 0xff01ed65d4a441fb,
           0xadb1ec8828c80e8, 0x62475d12f4e06fe7, 0xbd0b238da4fe72]

    tt2 = [0] * 11
    for i in range(0, 11):
        tt2[i] = ror(tt1[i], iv_v1)

    to_sign = bytearray(query_sm3 + body_md5_bytes + ts_bytes + bytes([0x80, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]))

    src = [0] * (len(to_sign) // 8)
    for i in range(len(to_sign) // 8):
        src[i] = int.from_bytes(to_sign[i * 8:i * 8 + 8], 'big')

    src_xor = [c_v1, c_v1, c_v1, c_v1, c_v1, c_v1, c_v1, c_v1]

    table_f = get_branch_1_table_f(iv_v0)
    swap = swap_v0(src, src_xor, tt2, table_f, order1)
    data = [0] * 8
    data[7] = 416

    src_xor = [swap[4], swap[3], swap[2], swap[1], swap[0], swap[7], swap[6], swap[5]]
    swap = swap_v0(data, src_xor, tt2, table_f, order1, swap)

    ret = bytearray(32)
    n = 0
    for i in range(7, -1, -1):
        pp = swap[i].to_bytes(8, "little")
        ret[n + 0], ret[n + 1], ret[n + 2], ret[n + 3] = pp[1], pp[3], pp[5], pp[6]
        n += 4

    for i in range(16):
        ret[i] ^= ret[i + 16]
    ret = ret[:16]
    sum = sum_md5(ret)
    ret += sum.to_bytes(4, "little")
    return ret

def r00(r0, r1, r2, r3, r4, r5, r6, r7, tt, table_f, v=0):
    x = table_f(8 * (r0 >> 56))
    r1 = (r1 >> 45) & 2040

    if tt > 0:
        x = x ^ tt
    x = x ^ table_f(r1 + 2048)

    r2 = (r2 >> 37) & 2040
    x = x ^ table_f(r2 + 4096)

    r3 = (r3 >> 29) & 2040
    x = x ^ table_f(r3 + 6144)

    r4 = (r4 >> 21) & 2040
    x = x ^ table_f(r4 + 8192)

    r5 = (r5 >> 13) & 2040
    x = x ^ table_f(r5 + 10240)

    r6 = (r6 >> 8) & 255
    x = x ^ table_f(8 * r6 + 12288)

    r7 = r7 & 255
    x = x ^ table_f(8 * r7 + 14336)

    return x

branch_2_orders = bytes.fromhex('''
    0f 07 04 00 09 08 03 0a 06 0b 05 0d 0e 01 0c 02 0f 05 08 0c 00 09 02 01 03 07 0e 06 0b 0a 0d 04 06 05 00 07 0c 00 0a 04 08 0f 01 0b 0d 09 02 0e 06 0b 02 05 04 03 08 01 01 07 0a 00 0d 0c 09 0e
    0d 07 0e 0f 0b 02 08 03 0c 05 09 01 00 04 06 0a 0d 09 02 06 0f 0b 0a 04 08 07 00 0c 05 03 01 0e 0c 09 0f 07 06 0f 03 0e 02 0d 04 05 01 0b 0a 00 0c 05 0a 09 0e 08 02 04 04 07 03 0f 01 06 0b 00
    0b 0f 04 08 02 0a 07 00 09 0d 06 01 0e 03 05 0c 0b 06 0a 05 08 02 0c 03 07 0f 0e 09 0d 00 01 04 09 06 08 0f 05 08 00 04 0a 0b 03 0d 01 02 0c 0e 09 0d 0c 06 04 07 0a 03 03 0f 00 08 01 05 02 0e
    01 00 0d 0f 09 0a 0b 0e 04 02 08 07 03 06 0c 05 01 08 0a 0c 0f 09 05 06 0b 00 03 04 02 0e 07 0d 04 08 0f 00 0c 0f 0e 0d 0a 01 06 02 07 09 05 03 04 02 05 08 0d 0b 0a 06 06 00 0e 0f 07 0c 09 03
    0a 08 04 0f 00 0b 01 06 0d 0c 07 09 03 0e 05 02 0a 07 0b 05 0f 00 02 0e 01 08 03 0d 0c 06 09 04 0d 07 0f 08 05 0f 06 04 0b 0a 0e 0c 09 00 02 03 0d 0c 02 07 04 01 0b 0e 0e 08 06 0f 09 05 00 03
    ''')

def branch_2(iv, khronos, query_sm3, body_md5_bytes, ts_bytes):
    n0 = (iv & 15 - 2) * 86
    iv_v0 = (n0 >> 15 & 0xff) + (n0 >> 8 & 0xff)

    t001 = [0x8980f29b, 0xeb549c7f, 0xb08726db, 0xd40cb5e6, 0xe8f559e4]

    n1 = t001[iv_v0]
    count_v1 = (n1 + khronos + 1) & 0xff
    count_v2 = (n1 + khronos) & 0xffffffff

    n0 = (count_v2 + 5) & 7

    pad = bytearray(8)
    seed = bytes([0x84, 0x96, 0x77, 0x9d, 0xd4, 0x15, 0x0b, 0xf8])
    for i in range(8):
        v = int.from_bytes(bytes([seed[i], seed[i]]), 'little')
        v = v >> n0
        pad[i] = v & 0xff

    data = query_sm3 + body_md5_bytes + ts_bytes + pad + bytes.fromhex('a0 01 00 00')

    idx = iv_v0 << 6
    ret = md5sum_v3(data, count_v2, branch_2_orders[idx:idx + 64], count_v1)

    return ret

def branch0_xor(data, base, di, tt03, round, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10):
    d = data[:]

    for i in range(round):
        offset = base + i
        n0 = di[offset & 127]

        n1 = ((d[x3] ^ d[x4]) & d[x1]) ^ d[x3]

        n2 = rol(d[x1], 26) ^ rol(d[x1], 21) ^ rol(d[x1], 7)
        offset = offset & 63
        n3 = tt03[offset]

        n4 = (n0 + n1 + n2 + n3 + d[x5]) & 0xffffffff

        n5 = rol(d[x2], 30) ^ rol(d[x2], 19) ^ rol(d[x2], 10)
        n6 = (d[x2] & d[x6]) | ((d[x2] | d[x6]) & d[x7])
        n7 = n5 + n6

        o = d[x9]
        d[0], d[1], d[2], d[3], d[4], d[5], d[6], d[7] = d[7], d[0], d[1], d[2], d[3], d[4], d[5], d[6]
        d[x10] = (n7 + n4) & 0xffffffff
        d[x8] = (o + n4) & 0xffffffff
    return d

branch_1_table = None

def get_branch_1_table_f(iv_v0):
    global branch_1_table
    if branch_1_table is None:
        branch_1_table = _branch_one_bytes()

    table = branch_1_table[iv_v0 << 14:]
    def table_f(x):
        return int.from_bytes(table[x:x + 8], 'little')
    return table_f

def _varint(value: int) -> bytes:
    value = int(value)
    if value < 0:
        value &= (1 << 64) - 1
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)

def _sint(value: int, bits: int) -> int:
    # 正式 protobuf 编码规则：正数不先截断到有符号范围；
    # 这对 Medusa.rand 等可能大于 2**31 的 sint32 字段很重要。
    value = int(value)
    return (value << 1) if value >= 0 else (value << 1) ^ (~0)

def _proto_field(field: int, value: Any, kind: str) -> bytes:
    if value in (None, "", b"", 0, 0.0, False):
        return b""
    if kind == "sint32":
        return _varint((field << 3) | 0) + _varint(_sint(int(value), 32))
    if kind == "sint64":
        return _varint((field << 3) | 0) + _varint(_sint(int(value), 64))
    if kind == "float":
        return _varint((field << 3) | 5) + struct.pack("<f", float(value))
    if kind == "bytes":
        raw = bytes(value)
    elif kind == "string":
        raw = str(value).encode("utf-8")
    elif kind == "message":
        raw = bytes(value)
    else:
        raise ValueError(f"unknown protobuf field kind: {kind}")
    return _varint((field << 3) | 2) + _varint(len(raw)) + raw

def _proto(fields: list[tuple[int, Any, str]]) -> bytes:
    return b"".join(_proto_field(field, value, kind) for field, value, kind in fields)

def _encode_request() -> bytes:
    return _proto([
        (1, 111, "sint32"),
        (2, 10, "sint32"),
        (3, 694367, "sint32"),
        (5, 586952199, "sint32"),
    ])

def _encode_device(device: Mapping[str, Any]) -> bytes:
    fields = [
        (1, device.get("d1"), "sint32"), (2, device.get("collect_stat"), "sint32"),
        (3, device.get("aid"), "string"), (4, device.get("device_id"), "string"),
        (5, device.get("sec_device_token"), "string"), (6, device.get("app_version"), "string"),
        (7, device.get("battery"), "sint32"), (8, device.get("battery2"), "sint32"),
        (9, device.get("battery_health"), "sint32"), (10, device.get("battery_changed"), "sint32"),
        (11, device.get("network"), "string"), (12, device.get("tz"), "string"),
        (13, device.get("lan"), "string"), (14, device.get("cpu"), "sint32"),
        (15, device.get("resolution"), "string"), (16, device.get("sdcard"), "float"),
        (17, device.get("sdcard_used"), "float"), (18, device.get("memory"), "float"),
        (19, device.get("memory2"), "float"), (20, device.get("data"), "float"),
        (21, device.get("data_used"), "float"), (22, device.get("os_version"), "string"),
        (23, device.get("brightness"), "sint32"), (24, device.get("volume"), "sint32"),
        (25, device.get("ts"), "sint64"), (26, device.get("ts2"), "sint64"),
        (27, device.get("ts3"), "sint64"), (28, device.get("ts4"), "sint64"),
        (29, device.get("usb"), "sint32"), (30, device.get("hw_version"), "string"),
        (31, device.get("brand"), "string"), (32, device.get("board"), "string"),
        (33, device.get("product_name"), "string"), (34, device.get("product_device"), "string"),
        (35, device.get("product_manufacturer"), "string"), (36, device.get("hardware"), "string"),
        (38, device.get("unknown38"), "sint32"), (40, device.get("unknown40"), "sint32"),
    ]
    return _proto(fields)

def _encode_env(env: Mapping[str, Any]) -> bytes:
    fields = [
        (1, env.get("launch_time"), "sint32"), (2, env.get("unknown2"), "sint32"),
        (3, env.get("unknown3"), "sint32"), (5, env.get("unknown5"), "sint32"),
        (6, env.get("version"), "string"), (7, env.get("pid"), "sint32"),
        (12, _encode_device(env.get("device") or {}), "message"),
        (13, _proto([
            (1, (env.get("report") or {}).get("time"), "sint64"),
            (2, (env.get("report") or {}).get("state"), "sint32"),
            (4, (env.get("report") or {}).get("code"), "sint32"),
            (5, (env.get("report") or {}).get("times"), "sint32"),
            (6, (env.get("report") or {}).get("unknown6"), "sint32"),
        ]), "message"),
        (14, env.get("app_version"), "string"),
        (15, env.get("unknown15"), "sint32"), (16, env.get("unknown16"), "sint32"),
        (18, env.get("unknown18"), "sint32"), (19, env.get("unknown19"), "sint32"),
        (20, env.get("unknown20"), "sint32"), (21, env.get("unknown21"), "sint32"),
    ]
    return _proto(fields)

def _encode_medusa(values: Mapping[str, Any]) -> bytes:
    return _proto([
        (1, values.get("magic"), "bytes"), (2, values.get("version"), "sint32"),
        (3, values.get("rand"), "sint32"), (4, values.get("ms_app_id"), "string"),
        (5, values.get("device_id"), "string"), (6, values.get("license_id"), "string"),
        (7, values.get("app_version"), "string"), (8, values.get("sdk_version_str"), "string"),
        (9, values.get("sdk_version"), "sint32"), (10, values.get("xg_seed_bytes"), "bytes"),
        (12, values.get("time"), "sint32"), (13, values.get("query_body_ts_hash"), "bytes"),
        (14, values.get("query_sm3"), "bytes"), (15, _encode_request(), "message"),
        (16, values.get("sec_device_token"), "string"), (17, values.get("time2"), "sint32"),
        (18, values.get("lanusk_hash"), "bytes"), (19, values.get("query_body_hash_sm3"), "bytes"),
        (20, values.get("psk_version"), "string"), (21, values.get("call_type"), "sint32"),
        (23, _encode_env(values.get("env") or {}), "message"),
        (24, values.get("unknown24"), "string"), (26, values.get("original"), "string"),
    ])

def _json_body_md5(data: Any, data_type: str | None = None) -> str:
    if not data:
        return ""
    if isinstance(data, str):
        raw = data.encode("utf-8")
    elif isinstance(data, bytes):
        raw = data
    elif data_type == "application/json; charset=UTF-8":
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    else:
        raw = urlencode(data).encode("utf-8")
    return hashlib.md5(raw).hexdigest().upper()

def _url_encode(value: Mapping[str, Any]) -> str:
    return urlencode(value).replace("+", "%20").replace("%2A", "*")

def _get_params_encrypturl(url: str, params: Mapping[str, Any], devices: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    result = dict(params)
    for key, value in devices.items():
        if key in result:
            result[key] = value
        elif key == "device_id" and "did" in result:
            result["did"] = value
    result["ts"] = int(time.time())
    result["_rticket"] = int(time.time() * 1000)
    return url.split("?", 1)[0] + "?" + _url_encode(result), result

def _xg_rc4(data: bytes, key: bytes) -> bytearray:
    table = list(range(256))
    j = 0
    for i in range(256):
        j = (j + table[i] + key[i % len(key)]) % 256
        table[i] = table[j]
    i = j = 0
    result = bytearray(len(data))
    for index, value in enumerate(data):
        i = (i + 1) & 0xFF
        x = table[i]
        j = (j + x) & 0xFF
        y = table[j]
        # 保持正式基线的 RC4 变体：这里只覆盖 S[i]，不交换 S[j]。
        table[i] = y
        result[index] = value ^ table[(y + y) & 0xFF]
    return result

def _reverse_bits(value: int) -> int:
    return int(f"{value:08b}"[::-1], 2)

def _encrypt_gorgon(body: Any, query: str, khronos: int, xg_rand: int, data_type: str) -> str:
    body_md5 = _json_body_md5(body, data_type).lower() if body else ""
    data = bytearray(hashlib.md5(query.encode()).digest()[:4])
    data += bytes.fromhex(body_md5)[:4] if body_md5 else b"\0\0\0\0"
    data += b"\0\0\0\0" + (67503104).to_bytes(4, "little") + khronos.to_bytes(4, "big")
    key = bytes((0x4A, 320 & 0xFF, 0x16, (xg_rand >> 8) & 0xFF, 0x47, 0x6C, 1, xg_rand & 0xFF))
    result = _xg_rc4(data, key)
    for index, value in enumerate(result):
        value = ((value >> 4) | (value << 4)) & 0xFF
        following = result[index + 1] if index + 1 < len(result) else result[0]
        result[index] = (~(_reverse_bits(following ^ value) ^ 20)) & 0xFF
    return (b"\x84\x04" + xg_rand.to_bytes(2, "little") + (320).to_bytes(2, "little") + result).hex()

def _ror64(value: int, count: int) -> int:
    count %= 64
    return ((value >> count) | (value << (64 - count))) & 0xFFFFFFFFFFFFFFFF

def _encrypt_helios(khronos: int, rand_value: int = 0) -> str:
    value = rand_value or random.randint(0, 0xFFFFFFFF)
    seed = value.to_bytes(4, "little") + b"8662"
    digest = hashlib.md5(seed).digest()
    keys = b"".join(f"{item:02x}".encode() for item in digest)
    table = [int.from_bytes(keys[:8], "little")]
    words = [int.from_bytes(keys[i:i + 8], "little") for i in range(0, 32, 8)]
    first, second = words[0], words[1]
    words = words[2:]
    for index in range(0x22):
        value2 = _ror64(second, 8)
        value2 = (value2 + first) & 0xFFFFFFFFFFFFFFFF
        value2 = (value2 ^ index) & 0xFFFFFFFFFFFFFFFF
        words.append(value2)
        value2 ^= _ror64(first, 61)
        value2 &= 0xFFFFFFFFFFFFFFFF
        table.append(value2)
        first, second = value2, words.pop(0)
    raw = (f"{khronos}-1588093228-8662").encode()
    pad = 16 - len(raw) % 16
    raw += bytes([pad]) * pad
    output = bytearray()
    for offset in range(0, len(raw), 16):
        left = int.from_bytes(raw[offset:offset + 8], "little")
        right = int.from_bytes(raw[offset + 8:offset + 16], "little")
        for index in range(0x22):
            right = (table[index] ^ (left + _ror64(right, 8))) & 0xFFFFFFFFFFFFFFFF
            left = (right ^ _ror64(left, 61)) & 0xFFFFFFFFFFFFFFFF
        output += left.to_bytes(8, "little") + right.to_bytes(8, "little")
    return base64.b64encode(value.to_bytes(4, "little") + output).decode()

def _gen_medusa_proto(url: str, url_params: Mapping[str, Any], devices: Mapping[str, Any], data: Any, khronos: int, data_type: str) -> tuple[bytes, bytes, bytes]:
    body_md5 = _json_body_md5(data, data_type).lower() if data else ""
    body_md5_bytes = bytes.fromhex(body_md5) if body_md5 else bytes(16)
    ts_bytes = khronos.to_bytes(4, "little")
    query = url.split("?", 1)[1] if "?" in url else ""
    query_sm3 = SM3(query).digest()
    query_body_hash = SM3(query.encode() + body_md5_bytes + b"none").digest()
    device_id = str(devices.get("device_id", url_params.get("device_id", url_params.get("did", ""))))
    version_name = str(devices.get("version_name", url_params.get("version_name", "7.1.3.32")))
    device_model = str(devices.get("device_model", url_params.get("device_type", "")))
    brand = str(devices.get("device_brand", url_params.get("device_brand", "")))
    sec_device_token = str(devices.get("sec_device_token") or "")
    device_sec_device_token = str(devices.get("device_sec_device_token") or "")
    proto_rand = random.randint(0, 0xFFFFFFFF)
    launch_time = random.randint(100, 120)
    process_id = random.randint(10001, 12000)
    # 这些字段是正式签名实现中的固定环境采样值，不是用户设备标识。
    report_ts = 1728388016635
    report_time = int(time.time())
    device = {
        "d1": 1, "collect_stat": 2, "aid": "8662", "device_id": device_id,
        "sec_device_token": device_sec_device_token,
        "app_version": "!noperm!", "battery": -888888, "battery2": -888888,
        "battery_health": 3, "battery_changed": -888888, "network": "!notset!",
        "tz": "Asia/Shanghai,8", "lan": "zh_CN", "cpu": 4,
        "sdcard": 255.24993896484375, "sdcard_used": 35.58599090576172,
        "memory": 3.467449188232422, "memory2": 3.467449188232422,
        "data": 255.1754913330078, "data_used": 42.17544174194336,
        "os_version": str(devices.get("os_version", url_params.get("os_version", ""))),
        "brightness": 41, "volume": 36, "ts": report_ts, "ts2": report_ts,
        "ts3": report_ts, "ts4": report_ts + 2, "usb": -1, "hw_version": device_model,
        "brand": brand, "board": device_model, "product_name": device_model,
        "product_device": str(devices.get("device_manufacturer", brand)),
        "product_manufacturer": brand, "hardware": brand, "unknown38": 31,
    }
    env = {
        "launch_time": launch_time, "unknown2": 146331399,
        "unknown3": 146331396, "unknown5": 7, "version": "v04.06.04.03-bugfix",
        "pid": process_id, "device": device,
        "report": {"time": report_time, "state": -2, "code": 200, "times": 0, "unknown6": 0},
        "app_version": version_name,
    }
    values = {
        "magic": b"\xf7\xe8_\xfa\xd7\xd7\xdc;\xd6*\xc8pW\xcfa\x18",
        "version": 3, "rand": proto_rand, "ms_app_id": "8662",
        "device_id": device_id, "license_id": "1588093228", "app_version": version_name,
        "sdk_version_str": "v04.06.04-ml-android", "sdk_version": 67503104,
        "xg_seed_bytes": (320).to_bytes(8, "little"), "time": khronos,
        "query_body_ts_hash": hash_f13(query_sm3, body_md5_bytes, ts_bytes, khronos),
        "query_sm3": query_sm3[:6], "sec_device_token": sec_device_token, "time2": khronos,
        "lanusk_hash": b"", "query_body_hash_sm3": query_body_hash, "psk_version": "none",
        "call_type": 312, "env": env,
        "unknown24": '{"cmr":16777216,"cmr2":16777216,"un_h":1879194040,"vpn":0,"kd":0,"fkd":3672518972,"pd":-1872573247,"dyn":"","do":0,"tk":true}',
    }
    return _encode_medusa(values), query_sm3, hash_f13(query_sm3, body_md5_bytes, ts_bytes, khronos)

def _xmxor_two(data: bytes, key: bytes) -> bytearray:
    encoded = bytearray(len(data))
    for index, value in enumerate(data):
        position = (index * 4) & 28
        d0, d1 = key[position], key[position + 1]
        d2 = (rl8(value, 4) + d0) ^ d1
        d2 = rl8((~d2) & 0xFF, 3)
        d2 = ((d2 + d1) & 0xFF) ^ d0
        encoded[-index - 1] = (~d2) & 0xFF
    return encoded

def _xmxor(data: bytes, key: bytes) -> bytearray:
    value = _xmxor_two(data, key)
    last_flag = value[-1] ^ value[-2]
    data0 = value[0]
    value[0] = (~last_flag + value[0]) & 0xFF
    value[1] = ((value[0] ^ value[-1] ^ 254) + value[1]) & 0xFF
    value[2] = (value[2] + ((last_flag - data0) ^ rl8(value[1], 3) ^ 2)) & 0xFF
    for index in range(len(value) - 4):
        temp = rl8(value[index + 2], 3) ^ value[index + 1] ^ (index + 3)
        value[index + 3] = (~temp + value[index + 3]) & 0xFF
    value[-1] ^= value[-2]
    value[0] = ((value[0] ^ value[1]) + sum(value[1:])) & 0xFF
    return value

def _gen_medusa(url: str, url_params: Mapping[str, Any], devices: Mapping[str, Any], data: Any, khronos: int, data_type: str) -> str:
    config_key = b"\xf1Y3vvn\xa9\x8d4\xf3\x1b\x05z\x9d[\xe4"
    config_iv = b"\x1f\xe1\t\xa4\x12R\x83\xf4\x18\xde\x9e\x05\x1a\x96\x9e\x12"
    sign_key = b"\x8e\xbd\xfa8\x06\xec\xc5\xce\xe7\x94#\xe6\x02\x9e\xd8%@\xbc\"\x18\xbb~\xae\xf7\x1c\xb6\x91\xf7\xaa\x8a\xa2\xf5"
    proto, query_sm3, body_sm3 = _gen_medusa_proto(url, url_params, devices, data, khronos, data_type)
    hash_rand = random.randint(0, 0xFFFFFFFF)
    xm_rand = random.randint(0, 0xFFFFFFFF)
    key, seed = get_key_hash(sign_key, hash_rand)
    mixed = _xmxor(proto, key)
    mixed = (320).to_bytes(8, "little") + mixed
    mixed = bytearray(mixed[::-1])
    for index in range(len(mixed)):
        mixed[index] ^= seed[~index & 3]
    hash_bytes = hash_rand.to_bytes(4, "little")
    check_bit = ((query_sm3[0] & 63) << 14) | 0x18000001 | ((body_sm3[0] & 63) << 8)
    mixed = b"\x35" + xm_rand.to_bytes(4, "little") + check_bit.to_bytes(4, "little") + mixed + hash_bytes[2:]
    mixed = AES_V3(config_key, khronos).encrypt(mixed, config_iv)
    version = bytes.fromhex("03 00 00 00 f7 e8 5f fa d7 d7 dc 3b d6 2a c8 70 57 cf 61 18")
    version_or = b"".join((int.from_bytes(version[i:i + 4], "little") ^ khronos).to_bytes(4, "little") for i in range(0, 20, 4))
    return base64.b64encode(version_or + hash_bytes[:2] + (256).to_bytes(2, "little") + mixed).decode()

def _core_sixgod(url: str, params: Mapping[str, Any], devices: Mapping[str, Any], data: Any, header: Mapping[str, Any]) -> tuple[dict[str, str], str]:
    data_type = str(header.get("content-type", header.get("Content-Type", "")))
    xg_rand = random.randint(0, 0xFFFF)
    encrypted_url, url_params = _get_params_encrypturl(url, params, devices)
    khronos = int(time.time())
    encoded_query = _url_encode(url_params)
    values = {
        "khronos": str(khronos),
        "ladon": base64.b64encode(khronos.to_bytes(4, "big")).decode(),
        "argus": base64.b64encode(khronos.to_bytes(4, "little")).decode(),
        "gorgon": _encrypt_gorgon(data, encoded_query, khronos, xg_rand, data_type),
        "helios": _encrypt_helios(khronos, 0),
        "medusa": _gen_medusa(encrypted_url, url_params, devices, data, khronos, data_type),
    }
    signs = {
        "x-ladon": values["ladon"], "x-khronos": values["khronos"],
        "x-argus": values["argus"], "x-gorgon": values["gorgon"],
        "x-helios": values["helios"], "x-medusa": values["medusa"],
    }
    if data:
        signs["x-ss-stub"] = _json_body_md5(data, data_type)
    result_headers = {str(key).lower(): str(value) for key, value in header.items()}
    result_headers.update(signs)
    if devices.get("ua"):
        result_headers["user-agent"] = str(devices["ua"])
    result_headers["x-tt-dt"] = str(devices.get("x_tt_dt", ""))
    return result_headers, encrypted_url

def _device_config(config: Mapping[str, Any]) -> dict[str, str]:
    device_id = _text(config.get("device_id"))
    install_id = _text(config.get("install_id"))
    if not device_id or not install_id:
        raise HongguoPluginError("缺少红果 device_id/install_id 配置")
    return {
        "device_id": device_id, "iid": install_id, "install_id": install_id,
        "device_brand": "Redmi", "device_model": "25053RT47C", "device_type": "25053RT47C",
        "device_manufacturer": "Xiaomi", "os_version": "16", "version_name": "7.1.3.32",
        "x_tt_dt": _text(config.get("x_tt_dt")),
        "sec_device_token": _text(config.get("sec_device_token")),
        "device_sec_device_token": _text(config.get("device_sec_device_token")),
        "ua": APP_UA,
    }

def _hiker_query(params: Mapping[str, Any]) -> str:
    """海阔视界 hgPhxQuery() 的等价实现：原样拼接，不做 URL 编码（resolution 里的 * 保留字面）。"""
    parts = []
    for key, value in params.items():
        parts.append("%s=%s" % (key, value))
    return "&".join(parts)


def _video_model(video_id: str, config: Mapping[str, Any], video_url: str | None = None,
                 sign_mode: str = "sixgod", single: bool = False) -> dict[str, Any]:
    devices = _device_config(config)
    params = {
        "iid": devices["install_id"],
        "device_id": devices["device_id"],
        "ac": "wifi",
        "channel": "update_64",
        "aid": "8662",
        "app_name": "novelread",
        "version_code": "71332",
        "version_name": "7.1.3.32",
        "device_platform": "android",
        "os": "android",
        "ssmix": "a",
        "device_type": "25053RT47C",
        "device_brand": "Redmi",
        "language": "zh",
        "os_api": "36",
        "os_version": "16",
        "manifest_version_code": "71332",
        "resolution": "1280*2772",
        "dpi": "520",
        "update_version_code": "71332",
        "host_abi": "arm64-v8a",
        "dragon_device_type": "phone",
        "pv_player": "71332",
        "compliance_status": "0",
        "need_personal_recommend": "1",
        "player_so_load": "1",
        "is_android_pad_screen": "0",
    }
    payload = {
        "biz_param": {
            "detail_page_version": 0,
            "device_level": 3,
            "disable_digg_stat": False,
            "need_all_video_definition": True,
            "need_mp4_align": False,
            "use_os_player": False,
            "use_server_dns": False,
            "video_platform": 1024,
        },
    }
    if single:
        # video_model/v1/（multi_ 停服后的现行接口）：顶层 video_id
        payload["video_id"] = video_id
    else:
        payload["mixed_video_id_map"] = {"1004": [video_id]}
    request_headers = {
        "User-Agent": APP_UA,
        "Accept": "application/json; charset=utf-8,application/x-protobuf",
        "Content-Type": "application/json; charset=UTF-8",
        "x-xs-from-web": "0",
        "x-ss-req-ticket": str(int(time.time() * 1000)),
        "x-tt-request-tag": "t=0;n=0",
        "sdk-version": "2",
        "passport-sdk-version": "50561",
        "x-vc-bdturing-sdk-version": "3.7.2.cn",
    }
    if devices.get("cookie"):
        request_headers["Cookie"] = devices["cookie"]
    endpoint = video_url or VIDEO_URL
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if sign_mode == "hiker":
        # 2026-11-10 20:11 同机同网现场：海阔视界能播、狼壳空体。逐字比对两边请求，
        # 参数、UA、body 完全一致，唯一实质差异在签名头：
        #   海阔 FQ.signHeaders(qs, body, false, 8662, 1611921764) 只产出
        #     x-ladon / x-argus / x-ss-stub / x-khronos / x-ss-req-ticket；
        #   我们走 _core_sixgod，额外塞了 x-gorgon / x-medusa / x-helios / x-tt-dt
        #     这类视频接口并不认的六神签名。本函数按海阔那套只签 ladon+argus。
        query = _hiker_query(params)
        _hiker_sig = _sig_sign_headers(
            query,
            body,
            str(devices.get("device_id") or ""),
            str(devices.get("install_id") or ""),
            8662,
            1611921764,
        )
        signed_headers = {
            "User-Agent": APP_UA,
            "Accept": "application/json; charset=utf-8,application/x-protobuf",
            "Content-Type": "application/json",
            "x-xs-from-web": "0",
            "sdk-version": "2",
        }
        signed_headers.update(_hiker_sig)
        if devices.get("cookie"):
            signed_headers["Cookie"] = str(devices["cookie"])
        signed_url = endpoint + "?" + query
    else:
        signed_headers, signed_url = _core_sixgod(
            endpoint,
            params,
            devices,
            payload,
            request_headers,
        )
    try:
        response = requests.post(
            signed_url,
            headers=signed_headers,
            data=body,
            timeout=30,
        )
    except Exception:
        raise
    response_data = _json_response(response)
    data = response_data.get("data") or {}
    if not isinstance(data, Mapping):
        raise HongguoPluginError("video_model 数据为空")
    entry: Any = data.get(video_id)
    if entry is None:
        for value in data.values():
            if isinstance(value, Mapping):
                entry = value
                break
            if isinstance(value, list) and value and isinstance(value[0], Mapping):
                entry = value[0]
                break
    if not isinstance(entry, Mapping):
        entry = data
    raw_model = entry.get("video_model") if isinstance(entry, Mapping) else None
    if raw_model is None:
        raw_model = data.get("video_model")
    if raw_model is None and ("video_list" in data or "dynamic_video_list" in data):
        raw_model = data  # video_model/v1/ 可能直接把播放模型铺在 data 顶层
    if isinstance(raw_model, str):
        try:
            raw_model = json.loads(raw_model)
        except ValueError as exc:
            raise HongguoPluginError("video_model JSON 无效") from exc
    if not isinstance(raw_model, Mapping):
        raise HongguoPluginError("video_model 为空")
    return dict(raw_model)

def _video_list_from_model(model: Mapping[str, Any]) -> Any:
    for key in ("video_list", "dynamic_video_list"):
        if model.get(key) is not None:
            return model[key]
    dynamic = model.get("dynamic_video")
    if isinstance(dynamic, Mapping):
        for key in ("dynamic_video_list", "video_list", "list"):
            if dynamic.get(key) is not None:
                return dynamic[key]
    video_info = model.get("video_info")
    if isinstance(video_info, Mapping):
        data = video_info.get("data")
        if isinstance(data, Mapping):
            return _video_list_from_model(data)
    data = model.get("data")
    if isinstance(data, Mapping):
        return _video_list_from_model(data)
    return None


_QUALITY_ORDER = ("2160", "1440", "1080", "720", "576", "540", "480", "360")

def _int(value: Any) -> int:
    match = re.search(r"\d+", _text(value))
    return int(match.group()) if match else 0

def _quality(value: Any) -> str:
    text = _text(value).lower()
    match = re.search(r"(2160|1440|1080|720|576|540|480|360)", text)
    return match.group(1) if match else "1080"

def _quality_hint(value: Any) -> str:
    """同 _quality，但识别不出时返回空串。
    不能一律兜底 '1080'：否则所有未标注清晰度的条目会合并到同一个 key 并互相覆盖，
    最终只剩最后一条，导致切任何清晰度拿到的都是同一条（甚至是没有视轨的那条）。"""
    text = _text(value).lower()
    match = re.search(r"(2160|1440|1080|720|576|540|480|360)", text)
    return match.group(1) if match else ""

def _definition_of(item: Mapping[str, Any]) -> str:
    """从一条播放模型条目里提取清晰度，尽量覆盖上游各种字段命名。"""
    if not isinstance(item, Mapping):
        return ""
    meta = item.get("video_meta")
    if not isinstance(meta, Mapping):
        meta = {}
    for value in (
        item.get("definition"),
        item.get("definition_code"),
        item.get("video_definition"),
        item.get("definition_type"),
        item.get("vheight"),
        item.get("height"),
        item.get("quality"),
        item.get("gear_name"),
        item.get("quality_name"),
        item.get("p"),
        meta.get("definition"),
        meta.get("vheight"),
        meta.get("height"),
        meta.get("quality"),
    ):
        hint = _quality_hint(value)
        if hint:
            return hint
    return ""

def _select_quality(video_list: Any, wanted: str = "1080") -> tuple[str, dict[str, Any]]:
    def rows_from(value: Any, hinted_quality: str = "") -> list[tuple[str, dict[str, Any]]]:
        if isinstance(value, list):
            result: list[tuple[str, dict[str, Any]]] = []
            for item in value:
                result.extend(rows_from(item, hinted_quality))
            return result
        if not isinstance(value, Mapping):
            return []
        if any(
            key in value
            for key in (
                "main_url",
                "backup_url",
                "backup_url_1",
                "play_addr",
                "spade_a",
                "encrypt_info",
            )
        ):
            return [(hinted_quality, dict(value))]
        result = []
        for key, item in value.items():
            if key in {"dynamic_video", "video_info", "data"} and isinstance(item, Mapping):
                result.extend(rows_from(item, hinted_quality))
                continue
            if key in {"video_list", "dynamic_video_list", "list"}:
                result.extend(rows_from(item, _quality_hint(key)))
                continue
            if isinstance(item, (Mapping, list)):
                result.extend(rows_from(item, _quality_hint(key)))
        return result

    candidates = rows_from(video_list)
    rows: dict[str, dict[str, Any]] = {}
    # 无法识别清晰度时用 idxN 兜底成唯一 key，保证每条候选都被保留（不再互相覆盖）
    for index, (hinted_quality, item) in enumerate(candidates):
        definition = _definition_of(item) or _quality_hint(hinted_quality) or ("idx%d" % index)
        # 同一清晰度出现多条（bvc2 + hvc1 ABR 变体）时，优先留下壳能解的那条，
        # 否则先到的 bvc2 会把可播的 hvc1 顶掉，表现为只有声音没有画面
        if definition not in rows or (
            _hg_entry_is_bytevc2(rows[definition]) and not _hg_entry_is_bytevc2(item)
        ):
            rows[definition] = item
    if not rows:
        raise HongguoPluginError("播放模型没有清晰度")
    requested = _quality(wanted)
    order = [requested] + [item for item in _QUALITY_ORDER if item != requested]
    for definition in order:
        if definition in rows:
            return definition, rows[definition]
    # 清晰度全部识别不出：按码率/体积降序，取质量最好的一条（而不是碰运气取最后一条）
    def _rank(key: str) -> int:
        item = rows[key]
        bitrate = _int(item.get("bitrate") or item.get("bit_rate") or 0)
        size = _int(item.get("size") or item.get("duration_ms") or 0)
        return bitrate * 1000000 + size
    definition = max(rows, key=_rank)
    return definition, rows[definition]

def _fallback_api_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return _first(
            value.get("fallback_api"),
            value.get("url"),
            value.get("api"),
            value.get("data"),
        )
    if isinstance(value, (list, tuple)):
        for item in value:
            result = _fallback_api_value(item)
            if result:
                return result
        return ""
    text = _text(value)
    if text.startswith("{"):
        try:
            decoded = json.loads(text)
        except ValueError:
            decoded = {}
        if decoded:
            return _fallback_api_value(decoded)
    return text if len(text) > 10 else ""

def _decrypt_spade_url(value: str, key_seed: bytes) -> str:
    raw = _b64(value)
    if len(raw) < 20 or raw[0] != 0xA8 or raw[2:4] != b"\x01\x00":
        raise HongguoPluginError("spade URL 头无效")
    cipher_data = raw[4 : len(raw) - (len(raw) - 4) % 16]
    if not cipher_data:
        raise HongguoPluginError("spade URL 密文为空")
    constants = bytes.fromhex(
        "4dd4c2e6b83162090e52b3c7a6733ba4"
        "1cb2462b829ab58a196b39db57177524"
        "f49baf7f08e8d68d26a72e37c1a95a2f"
        "1f05a51892aef2949732b62a38aadd58"
    )
    first = hashlib.sha512(key_seed).digest()
    second = hashlib.sha512(first + constants).digest()
    plaintext = _aes_cbc_decrypt(second[:16], second[16:32], cipher_data)
    if plaintext:
        padding = plaintext[-1]
        if 1 <= padding <= 16 and padding <= len(plaintext):
            plaintext = plaintext[:-padding]
    return plaintext.rstrip(b"\0").decode("utf-8", errors="replace")

def _key_seed_from_model(model: Mapping[str, Any]) -> bytes:
    value = _text(model.get("key_seed"))
    if value:
        return _b64(value)
    for key in ("dynamic_video", "video_info", "data"):
        nested = model.get(key)
        if isinstance(nested, Mapping):
            result = _key_seed_from_model(nested)
            if result:
                return result
    return b""
def _page(url):
    last_err = None
    for attempt in range(2):
        try:
            # 复用线程本地 session（keep-alive），省掉每次新建连接 + TLS 握手的开销
            r = _hg_session().get(
                url,
                headers={
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    "Cache-Control": "no-cache",
                },
                timeout=8,
            )
            r.raise_for_status()
            r.encoding = r.encoding or "utf-8"
            if not r.text or "_ROUTER_DATA" not in r.text:
                raise RuntimeError("empty or invalid page")
            return r.text
        except Exception as err:
            last_err = err
            if attempt == 0:
                try:
                    time.sleep(0.3)
                except Exception:
                    pass
    raise RuntimeError("page fetch failed: %s" % last_err)

def _data(url):
    html = _page(url)
    m = re.search(r"(?:window\.)?_ROUTER_DATA\s*=\s*", html)
    if not m:
        return {}
    try:
        return json.JSONDecoder().raw_decode(html[m.end():])[0]
    except (ValueError, TypeError):
        return {}

def _item(x):
    x = x or {}
    vd = x.get("video_data") if isinstance(x.get("video_data"), dict) else x
    sid = str(
        vd.get("series_id")
        or x.get("series_id")
        or x.get("keyword")
        or vd.get("keyword")
        or ""
    )
    name = str(
        vd.get("series_title")
        or vd.get("series_name")
        or x.get("series_name")
        or x.get("name")
        or "未命名"
    )
    count = vd.get("episode_cnt") or x.get("episode_cnt") or 0
    pic = str(vd.get("series_cover") or x.get("series_cover") or "")
    intro = str(vd.get("series_intro") or x.get("series_intro") or "")
    return {
        "vod_id": sid,
        "vod_name": name,
        "vod_pic": pic,
        "vod_remarks": ("全%s集" % count) if count else "",
        "vod_content": intro,
    }

def _cat_item(x):
    return _item(x)

# ===================== 分季 + 首页板块（本次改动） =====================
_HG_TAB_MAP = {
    "all": ("real-drama", u"热播短剧"),
    "human": ("real-drama", u"热播真人剧"),
    "comic": ("comic-drama", u"热播漫剧"),
}
_HG_SEASON_CACHE = {}
_HG_SEARCH_API = SITE + "/api/search/result/"
_HG_SEASON_RE = re.compile(u"第\\s*([0-9]{1,3}|[一二三四五六七八九十]{1,3})\\s*[季部]")
# 标题结尾的裸数字也当季号（如「……我终于发达了7」），数字前不能紧跟数字，避免把年份 1980 当季号
_HG_TAIL_RE = re.compile(u"(?:[\\s·\\-—_：:.、]+)?(?<![0-9])([0-9]{1,3}|[一二三四五六七八九十]{1,3})\\s*$")
# 「反向拿捏2：和闺蜜穿七零带着婆婆一起离」这类：季号贴在主标题末尾、后面接冒号副标题。
# 只看冒号前的主标题尾部，1~2 位阿拉伯数字或半/全角括号数字；数字前不能紧跟数字（防 1980、2024）
_HG_MAIN_TAIL_RE = re.compile(u"(?:[\\s·\\-—_]*)(?:[（(]\\s*([0-9]{1,2})\\s*[)）]|(?<![0-9])([0-9]{1,2}))\\s*$")
_HG_CN = u"零一二三四五六七八九十"


def _hg_cn(n):
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n <= 10:
        return _HG_CN[n]
    if n < 20:
        return u"十" + _HG_CN[n % 10]
    if n < 100:
        return _HG_CN[n // 10] + u"十" + (_HG_CN[n % 10] if n % 10 else u"")
    return str(n)


def _hg_num(t):
    t = str(t or "")
    if t.isdigit():
        return int(t)
    if t == u"十":
        return 10
    if t.startswith(u"十"):
        return 10 + (_HG_CN.index(t[1]) if len(t) > 1 and t[1] in _HG_CN else 0)
    if u"十" in t:
        a, _, b = t.partition(u"十")
        return _HG_CN.index(a) * 10 + (_HG_CN.index(b) if b and b in _HG_CN else 0)
    return _HG_CN.index(t) if t in _HG_CN else 0


def _hg_season_no(name):
    m = _HG_SEASON_RE.search(name or "")
    if m:
        return _hg_num(m.group(1))
    t = _HG_TAIL_RE.search(name or "")
    if t:
        n = _hg_num(t.group(1))
        return n if 0 < n <= 99 else 0
    # 冒号副标题写法：季号在主标题末尾（第一部没有数字，按第一季处理）
    main, sub = _hg_split_title(name)
    if sub:
        mm = _HG_MAIN_TAIL_RE.search(main)
        if mm:
            n = int(mm.group(1) or mm.group(2) or 0)
            return n if 0 < n <= 99 else 0
    return 0


def _hg_bare_style(name):
    """True 表示这部剧的季号是裸数字写法（标题里没有「第N季/部」）。"""
    return not _HG_SEASON_RE.search(name or u"")


def _hg_split_title(name):
    """按第一个冒号拆成（主标题, 副标题）；没有冒号时副标题为空串。"""
    raw = (name or u"").strip()
    for sep in (u"：", u":"):
        i = raw.find(sep)
        if 0 < i < len(raw) - 1:
            return raw[:i].strip(), raw[i + 1:].strip()
    return raw, u""


def _hg_main_style(name):
    """「主标题+季号：副标题」写法里剥掉季号的主标题；不适用时返回空串。

    只认这种形状：没有「第N季/部」、整个标题末尾没有裸数字（那是「道印入体：…7」
    的写法，季号挂在副标题后面）、冒号前的主标题 4~12 个字。这样普通带副标题的剧
    不会被拉去多探两轮。
    """
    raw = (name or u"").strip()
    main, sub = _hg_split_title(raw)
    if not sub or not (4 <= len(main) <= 12):
        return u""
    if _HG_SEASON_RE.search(raw) or _HG_TAIL_RE.search(raw):
        return u""
    mn = _HG_MAIN_TAIL_RE.sub(u"", main).strip(u"：:·-—_ 　")
    if mn == main and re.search(u"[0-9]", main[-2:]):
        # 主标题自己就以数字结尾（重生1980、2024 这类），不是季号写法
        return u""
    return mn


def _hg_probe_kws(base, n, name):
    """缺失季的探测关键词。主标题带季号的写法要按原样拼，只搜基名搜不到。"""
    mn = _hg_main_style(name)
    if mn:
        main, sub = _hg_split_title(name)
        if _HG_MAIN_TAIL_RE.search(main):
            # 手上已是第 N 部（主标题自带数字）：另一部靠基名搜索就能带出来，不必再探
            return []
        return [mn + str(n) + u"：" + sub]
    if _hg_bare_style(name):
        return [base + str(n)]
    return [base + u"第%s季" % _hg_cn(n)]


def _hg_base_name(name):
    raw = (name or u"").strip()
    b = _HG_SEASON_RE.sub(u"", raw).strip(u"：:·-—_ 　")
    if b == raw:
        # 裸数字结尾：剥掉数字再当基名，基名不足 4 个字就不剥（防「重生1980」这类误伤）
        b2 = _HG_TAIL_RE.sub(u"", raw).strip(u"：:·-—_ 　")
        if len(b2) >= 4 and b2 != raw:
            b = b2
    if len(b) < 4:
        return u""
    return b


def _hg_group_id(sd):
    si = sd.get("season_info") if isinstance(sd, dict) else None
    if isinstance(si, dict):
        g = si.get("series_group_id")
        if g:
            return str(g)
    return u""


_HG_TLS = threading.local()


def _hg_session():
    """每线程复用一条 requests 会话：keep-alive + gzip，省握手开销。"""
    ses = getattr(_HG_TLS, "ses", None)
    if ses is None:
        ses = requests.Session()
        ses.trust_env = False
        ses.headers.update({
            "User-Agent": UA,
            "Referer": SITE + "/",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        })
        _HG_TLS.ses = ses
    return ses


def _hg_fetch_sd(sid, timeout=8):
    """单次请求拉详情（不重试），失败返回 {}。"""
    try:
        r = _hg_session().get(SITE + "/detail?series_id=" + quote(str(sid), safe=u""), timeout=timeout)
        if r.status_code != 200:
            return {}
        j = _router_data(r.text)
        p = ((j.get(u"loaderData") or {}).get(u"detail_page") or {}) if isinstance(j, dict) else {}
        return p.get(u"seriesDetail") or {}
    except Exception:
        return {}


# 分季详情缓存：**只放进程内**，按用户要求不在设备本地建 json 文件。
# 原来这里落盘 hg_seasons_cache.json（6h/24h 跨进程缓存），现在改成内存表：
# 进程存活期间详情/分季仍然零请求复用，进程重启后重新拉一次，不留任何本地文件。
_HG_DISK_MEM: dict[str, Any] = {}


def _hg_slim(sd):
    """只留拼线路要用的字段，控制缓存文件体积。"""
    if not isinstance(sd, dict):
        return {}
    cele = [str(c.get("nickname") or "") for c in (sd.get("celebrities") or []) if isinstance(c, dict)]
    return {
        "series_id": str(sd.get("series_id") or ""),
        "series_name": str(sd.get("series_name") or ""),
        "series_cover": str(sd.get("series_cover") or ""),
        "series_intro": str(sd.get("series_intro") or ""),
        "episode_right_text": str(sd.get("episode_right_text") or ""),
        "episode_cnt": sd.get("episode_cnt") or 0,
        "tags": sd.get("tags") if isinstance(sd.get("tags"), list) else [],
        "celebrities": [{"nickname": n} for n in cele if n],
        "vid_list": [str(x) for x in (sd.get("vid_list") or [])],
        "season_info": sd.get("season_info") if isinstance(sd.get("season_info"), dict) else {},
    }


def _hg_disk_load():
    """取进程内分季缓存（不读本地文件）。"""
    try:
        return _HG_DISK_MEM
    except Exception:
        return {}


def _hg_disk_save(all_data):
    """只写进程内缓存：按用户要求不落盘，不生成 hg_seasons_cache.json。"""
    try:
        items = sorted(all_data.items(), key=lambda kv: kv[1].get("ts", 0), reverse=True)[:120]
        new = dict(items)
    except Exception:
        return
    _HG_DISK_MEM.clear()
    _HG_DISK_MEM.update(new)


def _hg_sd(sid):
    """单部详情：进程缓存 300s → 磁盘缓存 6h → 网络单次请求。"""
    key = u"sd:" + str(sid)
    hit = _HG_SEASON_CACHE.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    sd = _hg_fetch_sd(sid)
    if not sd:
        sd = {}
        _HG_SEASON_CACHE[key] = (time.time() - 240, sd)   # 失败短缓存 60 秒
        _trim_store(_HG_SEASON_CACHE, cap=256)
        return sd
    _HG_SEASON_CACHE[key] = (time.time(), sd)
    _trim_store(_HG_SEASON_CACHE, cap=256)
    return sd


def _hg_candidates(kw, pages=2, deadline=None):
    """站内搜索取候选 (sid, name)，只认 query 参数，看 hasMore 翻页。"""
    out = []
    seen = set()
    for pg in range(1, pages + 1):
        if deadline is not None and time.time() > deadline:
            break
        try:
            d = _search_api(kw, pg) or {}
        except Exception:
            break
        rows = d.get(u"searchList") or []
        for it in rows:
            vd = it.get(u"video_data") if isinstance(it.get(u"video_data"), dict) else it
            sid = str(vd.get(u"series_id") or it.get(u"series_id") or u"")
            if not sid.isdigit() or sid in seen:
                continue
            seen.add(sid)
            out.append((sid, str(it.get(u"name") or vd.get(u"series_title") or u"")))
            if len(out) >= 40:
                return out
        if not d.get(u"hasMore"):
            break
    return out




_HG_PRE_LOCK = threading.Lock()
_HG_PRE_RUNNING = [0]
_HG_PRE_MAX = 3


def _hg_prefetch(sids, limit=3):
    """后台预热：给刚出现的 series_id 预拉详情写缓存。绝不阻塞调用方，异常全吞。"""
    if not sids:
        return
    todo = [str(x) for x in sids if str(x).isdigit()][:limit]
    if not todo:
        return
    try:
        disk = _hg_disk_load()
    except Exception:
        disk = {}

    def _run():
        for sid in todo:
            with _HG_PRE_LOCK:
                if _HG_PRE_RUNNING[0] >= _HG_PRE_MAX:
                    return
                _HG_PRE_RUNNING[0] += 1
            try:
                c = disk.get(sid)
                if isinstance(c, dict):
                    continue
                sd = _hg_sd(sid)
                if not sd:
                    continue
                seasons = _hg_seasons(sid, sd)
                _all = _hg_disk_load()
                _pl = {"v": 3, "ts": time.time(), "self": _hg_slim(sd),
                       "seasons": [{"no": no, "sd": _hg_slim(d)} for no, d in seasons]}
                _all[sid] = _pl
                for _no, _d in seasons:
                    _xid = str(_d.get("series_id") or u"")
                    if _xid and _xid != sid:
                        _all[_xid] = _pl
                _hg_disk_save(_all)
            except Exception:
                pass
            finally:
                with _HG_PRE_LOCK:
                    _HG_PRE_RUNNING[0] -= 1

    try:
        t = threading.Thread(target=_run, name="hg-prefetch")
        t.daemon = True
        t.start()
    except Exception:
        pass


def _hg_seasons(sid, sd, budget=9.0):
    """真分季：基名搜索一页 + 缺失季定向探测；探测与拉详情同池并发，命中即收敛。"""
    ck = u"season:" + str(sid)
    hit = _HG_SEASON_CACHE.get(ck)
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    gid = _hg_group_id(sd)
    if not gid:
        return [(0, sd)]
    base = _hg_base_name(sd.get("series_name") or u"")
    if not base:
        return [(0, sd)]
    t_end = time.time() + budget
    _nm0 = sd.get("series_name") or u""
    _bare = _hg_bare_style(_nm0)
    # 「反向拿捏2：副标题」这类写法的主标题；非空才值得多探一轮
    _main_ref = _hg_main_style(_nm0)
    known = {(_hg_season_no(_nm0) or 1): str(sid)}
    extra = []
    try:
        for csid, nm in _hg_candidates(base, 1, time.time() + min(3.0, budget)):
            n = _hg_season_no(nm)
            # 同一主标题、没有季号的那一部就是第一部
            if not n and _main_ref and _hg_main_style(nm) == _main_ref:
                n = 1
            if n and n not in known:
                known[n] = csid
            elif not n:
                extra.append(csid)
    except Exception:
        pass
    found = {str(sid): sd}
    pending = {}
    probed = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for cid in list(known.values()) + extra[:1]:
            if cid != str(sid) and cid not in found and cid not in pending:
                pending[ex.submit(_hg_sd, cid)] = (u"detail", cid)
        while pending and time.time() < t_end:
            done = None
            try:
                done, _ = concurrent.futures.wait(list(pending), timeout=0.1,
                                                  return_when=concurrent.futures.FIRST_COMPLETED)
            except Exception:
                break
            for f in done:
                kind, key = pending.pop(f)
                try:
                    val = f.result(timeout=0.1)
                except Exception:
                    val = None
                if kind == u"detail":
                    if val:
                        found[key] = val
                        # 同名诱饵（标题像第 N 季但其实是别的剧）抓进来了：
                        # 释放这一季的名额，让下面的缺口探测重新去找真身
                        if str(key) != str(sid) and _hg_group_id(val) != gid:
                            for _k, _v in list(known.items()):
                                if str(_v) == str(key):
                                    known.pop(_k, None)
                else:
                    for csid, nm in (val or [])[:4]:
                        if _hg_season_no(nm) == key and csid not in found and csid not in known.values():
                            known[key] = csid
                            pending[ex.submit(_hg_sd, csid)] = (u"detail", csid)
                            break
            # 缺失季：1..max+1 里没着落的，补探测（每轮最多 4 个）
            # 已从搜索里认到季号、详情还在路上的，也算有着落，不再重复探同一季
            _ver = set(x for x in known.keys() if x)
            for _k, _d in found.items():
                if _d and (str(_k) == str(sid) or _hg_group_id(_d) == gid):
                    _ver.add(_hg_season_no(_d.get(u"series_name") or u""))
            if (len(probed) < 9 and time.time() < t_end
                    and (len(_ver) >= 2 or _hg_season_no(_nm0) > 0 or bool(_main_ref))):
                mx = max(_ver) if _ver else 1
                for n in [x for x in range(1, mx + 2) if x not in _ver and x not in probed][:4]:
                    probed.add(n)
                    for _kw in _hg_probe_kws(base, n, _nm0):
                        pending[ex.submit(_hg_candidates, _kw, 1,
                                          time.time() + 3)] = (u"probe", n)
    # 收尾补漏：诱饵被剔除后总会留下空洞，按缺的季号再定向探一次（最多 2 个）
    _have = set()
    for _x, _d in found.items():
        if _d and (str(_x) == str(sid) or _hg_group_id(_d) == gid):
            _have.add(_hg_season_no(_d.get(u"series_name") or u""))
    _mx = max(_have) if _have else 1
    _need = [x for x in range(1, _mx + 1) if x not in _have][:2]
    if _need:
        # 两个缺号并发探，不再一个搜完再搜下一个
        _cand = {}
        try:
            _kwjobs = [(kw, _n) for _n in _need for kw in _hg_probe_kws(base, _n, _nm0)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(_kwjobs))) as _ex:
                _fs = {_ex.submit(_hg_candidates, kw, 1, time.time() + 3): _n
                       for kw, _n in _kwjobs}
                for _f in list(_fs):
                    try:
                        _cand[_fs[_f]] = _f.result(timeout=4) or []
                    except Exception:
                        _cand[_fs[_f]] = []
        except Exception:
            _cand = {}
        _jobs = []
        for _n, _cl in _cand.items():
            for _cid, _nm in (_cl or [])[:3]:
                if _hg_season_no(_nm) == _n and _cid not in found:
                    _jobs.append((_n, _cid))
        if _jobs:
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(_jobs))) as _ex:
                    _fs2 = {_ex.submit(_hg_sd, _cid): _n for _n, _cid in _jobs}
                    _got = set()
                    for _f in list(_fs2):
                        _n = _fs2[_f]
                        if _n in _got:
                            continue
                        try:
                            _d = _f.result(timeout=5)
                        except Exception:
                            continue
                        if _d and _hg_group_id(_d) == gid:
                            found[str(_d.get("series_id") or "")] = _d
                            _got.add(_n)
            except Exception:
                pass
    seasons = []
    for x, d in found.items():
        if not d:
            continue
        if x != str(sid) and _hg_group_id(d) != gid:
            continue
        seasons.append((_hg_season_no(d.get(u"series_name") or u""), d))
    # 防误判：分集内容与当前剧或已收季高度重叠的（同一部的重复条目）一律剔除
    def _vset(d):
        return set(str(v) for v in (d.get("vid_list") or []))
    _self_v = _vset(sd)
    _uniq = []
    for no, d in seasons:
        v = _vset(d)
        if not v:
            continue
        _is_self = (d is sd) or (str(d.get("series_id") or u"") == str(sid))
        dup = False
        if not _is_self and _self_v:
            small = min(len(v), len(_self_v))
            if small and len(v & _self_v) >= max(1, int(small * 0.5)):
                dup = True
        if not dup:
            for _n2, _d2 in _uniq:
                v2 = _vset(_d2)
                small = min(len(v), len(v2)) if v2 else 0
                if small and len(v & v2) >= max(1, int(small * 0.5)):
                    dup = True
                    break
        if not dup:
            _uniq.append((no, d))
    seasons = _uniq
    if len(seasons) < 2:
        # 凑不出第二部同组剧就保持单线路原样，绝不凭空造季
        _HG_SEASON_CACHE[ck] = (time.time(), [(0, sd)])
        _trim_store(_HG_SEASON_CACHE, cap=256)
        return [(0, sd)]
    seasons.sort(key=lambda t: (t[0] if t[0] else 1))
    if not any((d is sd) or (str(d.get("series_id") or "") == str(sid)) for _n, d in seasons):
        seasons.insert(0, (0, sd))
    _HG_SEASON_CACHE[ck] = (time.time(), seasons)
    _trim_store(_HG_SEASON_CACHE, cap=256)
    return seasons


def _hg_cat_list(rows):
    out = []
    try:
        for x in rows:
            out.append(_cat_item(x))
    except Exception:
        pass
    try:
        _hg_prefetch([x.get("vod_id") for x in out], 6)
    except Exception:
        pass
    return out


def _hg_home_sections():
    """按首页 homeSections 分板块出卡，标题取 tab_name，取不到给兜底名。"""
    ck = u"home"
    hit = _HG_SEASON_CACHE.get(ck)
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    out = []
    seen = set()
    try:
        j = _data(SITE + u"/")
        secs = (((j.get(u"loaderData") or {}).get(u"page") or {}).get(u"homeSections")) or []
    except Exception:
        secs = []
    if isinstance(secs, list):
        for sec in secs:
            if not isinstance(sec, dict):
                continue
            tt = str(sec.get(u"tab_type") or u"")
            tid, tname = _HG_TAB_MAP.get(tt, ("real-drama", u"红果热播"))
            tn = str(sec.get(u"tab_name") or u"").strip()
            if tn and tn.lower() not in (u"null", u"none", u"undefined"):
                tname = tn
            for x in (sec.get(u"video_list") or []):
                it = _item(x)
                vid = str(it.get("vod_id") or u"")
                if not vid.isdigit() or vid in seen:
                    continue
                seen.add(vid)
                it["type_id"] = tid
                it["type_name"] = tname
                out.append(it)
    _HG_SEASON_CACHE[ck] = (time.time(), out)
    _trim_store(_HG_SEASON_CACHE, cap=256)
    return out



_HG_SEARCH_PRIMED = [False]


def _search_api(key: str, page: int = 1) -> dict:
    """官网搜索接口 /api/search/result（搜索页已改客户端渲染，SSR 无数据）。

    原来每次搜索都先抓一遍 586KB 的首页拿 ttwid，一部十季剧要搜七八次，
    白花七八个首页请求（实测每次 250~1200ms）。现在复用线程本地 session 直连搜索，
    真的返回空列表时才补一次首页 cookie 重试，且每个进程只补一次。
    """
    empty = {"searchList": [], "totalCount": 0, "totalPages": 1, "hasMore": False}
    params = {"aid": "8662", "query": str(key or ""), "page": str(max(1, int(page or 1)))}

    def _once():
        try:
            r = _hg_session().get(SITE + "/api/search/result", params=params, timeout=8,
                                  headers={"Accept": "application/json, text/plain, */*"})
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:
            return None

    data = _once()
    try:
        if not (isinstance(data, dict) and data.get("searchList")) and not _HG_SEARCH_PRIMED[0]:
            # 极少数情况下上游要 ttwid 才回数据：补一次首页再试（仅一次）
            _HG_SEARCH_PRIMED[0] = True
            try:
                _hg_session().get(SITE + "/", timeout=8)
            except Exception:
                pass
            data = _once()
    except Exception:
        data = data if isinstance(data, dict) else None
    if not isinstance(data, dict):
        return empty
    try:
        rows = data.get("searchList") or []
        if not isinstance(rows, list) or not rows:
            return empty
        try:
            total_pages = int(data.get("totalPages") or 1)
        except Exception:
            total_pages = 1
        try:
            total_count = int(data.get("totalCount") or 0)
        except Exception:
            total_count = 0
        return {
            "searchList": rows,
            "totalCount": total_count,
            "totalPages": max(1, total_pages),
            "hasMore": bool(data.get("hasMore")),
        }
    except Exception:
        return empty


def _search_loader(key: str, page: int = 1) -> dict:
    """搜索：优先官网 XHR 接口，失败退回旧 SSR 页（已多半无数据，仅兜底）。"""
    api = _search_api(key, page)
    if api.get("searchList"):
        return api
    last = {}
    for attempt in range(2):
        try:
            data = _data(SITE + "/search/" + quote(str(key), safe=""))
            loaded = (data.get("loaderData") or {}).get("search_(keyword)/page") or {}
            if loaded.get("searchList"):
                return loaded
            last = loaded or last
        except Exception:
            pass
        try:
            time.sleep(0.4 * (attempt + 1))
        except Exception:
            pass
    return last


def _search_by_keywords(keywords, page: int) -> dict:
    """多关键词轮换：第 N 页用第 N 个关键词（循环），避免搜索无法翻页。"""
    page = max(1, int(page or 1))
    kws = [k for k in (keywords or []) if k]
    if not kws:
        kws = ["短剧"]
    key = kws[(page - 1) % len(kws)]
    p = _search_loader(key)
    rows = p.get("searchList") or []
    # 去重空 id
    out = []
    seen = set()
    for x in rows:
        it = _item(x)
        vid = str(it.get("vod_id") or "")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        out.append(it)
    # 虚拟页数：关键词数；若站点有 totalCount 也参考
    total = int(p.get("totalCount") or 0)
    pagecount = max(len(kws), (total + 9) // 10 if total else len(kws))
    return {
        "page": page,
        "pagecount": max(1, pagecount),
        "limit": len(out),
        "total": total or len(out) * pagecount,
        "list": out,
    }


def _hg_search_scan(key, page=1, max_pages=8):
    """搜索兜底：官方搜索接口被风控时，扫官方分类页按标题命中（并发）。"""
    key = str(key or "").strip()
    page = max(1, int(page or 1))
    empty = {"page": page, "pagecount": 1, "limit": 0, "total": 0, "list": []}
    if not key:
        return empty
    routes = [r for r, _n, _c in _HG_CONTENT_TYPES]
    jobs = [(r, p) for r in routes for p in range(1, max_pages + 1)]

    def work(rp):
        r, p = rp
        try:
            return _hg_category_page(r, "", p).get("recommendList") or []
        except Exception:
            return []

    hits = []
    seen = set()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            for rows in ex.map(work, jobs):
                for x in rows:
                    if not isinstance(x, dict):
                        continue
                    nm = str(x.get("series_name") or x.get("series_title") or "")
                    if key and key not in nm:
                        continue
                    it = _item(x)
                    vid = str(it.get("vod_id") or "")
                    if not vid or vid in seen:
                        continue
                    seen.add(vid)
                    hits.append(it)
    except Exception:
        pass
    if not hits:
        return empty
    per = 20
    st = (page - 1) * per
    chunk = hits[st:st + per]
    return {
        "page": page,
        "pagecount": max(1, (len(hits) + per - 1) // per),
        "limit": len(chunk),
        "total": len(hits),
        "list": chunk,
    }


# =============================================================================
# x-ladon / x-argus / x-ss-stub 签名工具（视频接口 hiker 签名模式用，见 _video_signed_request）
#
# 这套算法最早在红果 App 评论接口上验证过，因此历史版本沿用旧前缀；
# 现在只服务视频接口签名，符号已统一为 _sig_。
# 红果弹幕（评论接口取数、本机 /hg_dm 路由、playerContent 挂弹幕、剧集映射）
# 已整体移除，本段只剩纯计算签名，不发请求、不缓存、不挂播放信息。
#
# ladon 是 34 轮 Feistel；argus 是 protobuf(25 字段) → Simon-64 分组 → 551 变体
# （魔数/异或/倒序）→ AES-128-CBC。下面的实现与 Hiker 版 JS 逐字节一致
# （同输入同随机数下 x-ladon / x-argus 完全相等），因此同一份签名在 TVBox 的
# Chaquopy 里也能直接用。

_SIG_AES_KEY = bytes.fromhex("d31e3718288a1027baab59f146a09a9c")
_SIG_AES_IV = bytes.fromhex("ea180a0336ed352fcd24e4d50018ae54")
_SIG_SIMON_KEY = bytes.fromhex("fc78e0a9657a0c748ce51559903ccf03510e51d3cff232d71343e88a321c5304")
_SIG_M551 = bytes.fromhex("f2f7fcfff2f7fcff")
_SIG_TAIL551 = bytes.fromhex("eafb2cfe8568519154")
_SIG_PREFIX551 = bytes.fromhex("f281")

_SIG_U32 = 0xFFFFFFFF


# ---------------------------- SM3 ----------------------------
_SIG_SM3_IV = (0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
              0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E)


def _sig_rotl32(a: int, k: int) -> int:
    k &= 31
    if not k:
        return a & _SIG_U32
    return ((a << k) | (a >> (32 - k))) & _SIG_U32


def _sig_sm3_cf(v: list, bl: bytes, off: int) -> list:
    w = [((bl[off + i * 4] << 24) | (bl[off + i * 4 + 1] << 16) |
          (bl[off + i * 4 + 2] << 8) | bl[off + i * 4 + 3]) & _SIG_U32 for i in range(16)]
    for j in range(16, 68):
        xj = (w[j - 16] ^ w[j - 9] ^ _sig_rotl32(w[j - 3], 15)) & _SIG_U32
        w.append((xj ^ _sig_rotl32(xj, 15) ^ _sig_rotl32(xj, 23) ^
                  _sig_rotl32(w[j - 13], 7) ^ w[j - 6]) & _SIG_U32)
    w1 = [(w[j] ^ w[j + 4]) & _SIG_U32 for j in range(64)]
    a, b, c, d, e, f, g, h = v
    for j in range(64):
        t = 0x79CC4519 if j < 16 else 0x7A879D8A
        ss1 = _sig_rotl32((_sig_rotl32(a, 12) + e + _sig_rotl32(t, j % 32)) & _SIG_U32, 7)
        ss2 = ss1 ^ _sig_rotl32(a, 12)
        if j < 16:
            ff = a ^ b ^ c
            gg = e ^ f ^ g
        else:
            ff = (a & b) | (a & c) | (b & c)
            gg = (e & f) | (~e & g)
        tt1 = (ff + d + ss2 + w1[j]) & _SIG_U32
        tt2 = (gg + h + ss1 + w[j]) & _SIG_U32
        d, c, b, a = c, _sig_rotl32(b, 9), a, tt1
        h, g, f, e = g, _sig_rotl32(f, 19), e, (tt2 ^ _sig_rotl32(tt2, 9) ^ _sig_rotl32(tt2, 17)) & _SIG_U32
    return [(a ^ v[0]) & _SIG_U32, (b ^ v[1]) & _SIG_U32, (c ^ v[2]) & _SIG_U32, (d ^ v[3]) & _SIG_U32,
            (e ^ v[4]) & _SIG_U32, (f ^ v[5]) & _SIG_U32, (g ^ v[6]) & _SIG_U32, (h ^ v[7]) & _SIG_U32]


def _sig_sm3(data: bytes) -> bytes:
    orig = len(data)
    msg = bytearray(data)
    msg.append(0x80)
    reserve = (orig % 64) + 1
    end = 56
    if end < reserve:
        end += 64
    msg.extend(b"\0" * (end - reserve))
    msg.extend(struct.pack(">Q", orig * 8))
    v = list(_SIG_SM3_IV)
    for i in range(len(msg) // 64):
        v = _sig_sm3_cf(v, msg, i * 64)
    return b"".join(struct.pack(">I", x) for x in v)


def _sig_sm3_prefix6(data: bytes) -> bytes:
    return _sig_sm3(data)[:6]


# -------------------- 64 位字运算（(hi, lo) 双 32 位） --------------------
def _sig_u64le(b: bytes, off: int) -> tuple:
    lo = (b[off] | b[off + 1] << 8 | b[off + 2] << 16 | b[off + 3] << 24) & _SIG_U32
    hi = (b[off + 4] | b[off + 5] << 8 | b[off + 6] << 16 | b[off + 7] << 24) & _SIG_U32
    return (hi, lo)


def _sig_u64le_write(v: tuple, out: bytearray) -> None:
    for j in range(8):
        out.append(((v[1] >> (8 * j)) if j < 4 else (v[0] >> (8 * (j - 4)))) & 0xFF)


def _sig_x64(a: tuple, b: tuple) -> tuple:
    return (a[0] ^ b[0], a[1] ^ b[1])


def _sig_add64(a: tuple, b: tuple) -> tuple:
    lo = a[1] + b[1]
    hi = a[0] + b[0] + (1 if lo > _SIG_U32 else 0)
    return (hi & _SIG_U32, lo & _SIG_U32)


def _sig_not64(a: tuple) -> tuple:
    return ((~a[0]) & _SIG_U32, (~a[1]) & _SIG_U32)


def _sig_rotl64(a: tuple, n: int) -> tuple:
    n = ((n % 64) + 64) % 64
    if n == 0:
        return (a[0], a[1])
    if n == 32:
        return (a[1], a[0])
    if n < 32:
        hi = ((a[0] << n) | (a[1] >> (32 - n))) & _SIG_U32
        lo = ((a[1] << n) | (a[0] >> (32 - n))) & _SIG_U32
    else:
        m = n - 32
        hi = ((a[1] << m) | (a[0] >> (32 - m))) & _SIG_U32
        lo = ((a[0] << m) | (a[1] >> (32 - m))) & _SIG_U32
    return (hi, lo)


def _sig_rotr64(a: tuple, n: int) -> tuple:
    return _sig_rotl64(a, (64 - (n % 64)) % 64)


_SIG_SZ_HI = 0x3DC94C3A
_SIG_SZ_LO = 0x046D678B


def _sig_simon_zbit(k: int) -> int:
    return (_SIG_SZ_LO >> k) & 1 if k < 32 else (_SIG_SZ_HI >> (k - 32)) & 1


def _sig_simon_expand(k: list) -> list:
    key = list(k)
    for i in range(4, 72):
        tmp = _sig_rotr64(key[i - 1], 3)
        tmp = _sig_x64(tmp, key[i - 3])
        tmp = _sig_x64(tmp, _sig_rotr64(tmp, 1))
        key.append(_sig_x64(_sig_x64(_sig_not64(key[i - 4]), tmp),
                           (0, (_sig_simon_zbit((i - 4) % 62) ^ 3) & _SIG_U32)))
    return key


def _sig_simon_encrypt(pt: tuple, key: list) -> tuple:
    x, x1 = pt[0], pt[1]
    for i in range(72):
        t = x1
        r1 = _sig_rotl64(x1, 1)
        r8 = _sig_rotl64(x1, 8)
        f = (r1[0] & r8[0], r1[1] & r8[1])
        x1 = _sig_x64(_sig_x64(x, f), _sig_x64(_sig_rotl64(x1, 2), key[i]))
        x = t
    return (x, x1)


# ---------------------------- AES-CBC（无填充） ----------------------------
def _sig_aes_cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    if not data:
        return b""
    if AES_BACKEND == "cryptography":
        enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return enc.update(data) + enc.finalize()
    if AES_BACKEND == "pycryptodome":
        return CryptoAES.new(key, CryptoAES.MODE_CBC, iv).encrypt(data)
    if len(data) % 16:
        data = data[:len(data) - (len(data) % 16)]
    aes = _PureAES128(key)
    prev = iv[:16].ljust(16, b"\0")
    out = bytearray()
    for i in range(0, len(data), 16):
        block = bytes(a ^ b for a, b in zip(data[i:i + 16], prev))
        enc = aes.encrypt_block(block)
        out.extend(enc)
        prev = enc
    return bytes(out)


def _sig_pkcs7(data: bytes) -> bytes:
    n = 16 - (len(data) % 16)
    return data + bytes([n]) * n


# ---------------------------- protobuf 写入 ----------------------------
class _DmPbuf:
    """最小的 protobuf 编码器：字段顺序即写入顺序（与 JS 版 Pbuf 一致）。"""

    def __init__(self) -> None:
        self._fields: list = []
        self._blobs: list = []

    def v(self, idx: int, val: int) -> "_DmPbuf":
        self._fields.append((idx, 0, int(val), 0))
        return self

    def _blob(self, idx: int, data: bytes) -> "_DmPbuf":
        self._blobs.append(data)
        self._fields.append((idx, 2, 0, len(self._blobs) - 1))
        return self

    def s(self, idx: int, text: Any) -> "_DmPbuf":
        return self._blob(idx, str(text).encode("utf-8"))

    def raw(self, idx: int, data: bytes) -> "_DmPbuf":
        return self._blob(idx, data)

    def pb(self, idx: int, sub: "_DmPbuf") -> "_DmPbuf":
        return self._blob(idx, sub.to_buf())

    def to_buf(self) -> bytes:
        out = bytearray()
        for idx, kind, val, ref in self._fields:
            _sig_varint(out, idx * 8 + (kind & 7))
            if kind == 0:
                _sig_varint(out, val)
            else:
                blob = self._blobs[ref]
                _sig_varint(out, len(blob))
                out.extend(blob)
        return bytes(out)


def _sig_varint(out: bytearray, value: int) -> None:
    value &= 0xFFFFFFFFFFFFFFFF
    while value >= 128:
        out.append((value % 128) | 128)
        value //= 128
    out.append(value % 128)


# ---------------------------- argus / ladon ----------------------------
def _sig_simon_padded(pb: bytes) -> bytes:
    key = _sig_simon_expand([_sig_u64le(_SIG_SIMON_KEY, 0), _sig_u64le(_SIG_SIMON_KEY, 8),
                            _sig_u64le(_SIG_SIMON_KEY, 16), _sig_u64le(_SIG_SIMON_KEY, 24)])
    out = bytearray()
    for i in range(len(pb) // 16):
        off = i * 16
        ct = _sig_simon_encrypt((_sig_u64le(pb, off), _sig_u64le(pb, off + 8)), key)
        _sig_u64le_write(ct[0], out)
        _sig_u64le_write(ct[1], out)
    return bytes(out)


def _sig_argus_encrypt(bean: "_DmPbuf") -> str:
    pb = _sig_pkcs7(bean.to_buf())
    un = _SIG_M551 + _sig_simon_padded(pb) + _SIG_TAIL551
    buf = bytearray(un[:8])
    for i in range(8, len(un)):
        buf.append((un[i] ^ _SIG_M551[i % 8]) & 0xFF)
    buf.reverse()
    body = _sig_pkcs7(bytes(buf) + b"ao")
    return base64.b64encode(_SIG_PREFIX551 + _sig_aes_cbc_encrypt(_SIG_AES_KEY, _SIG_AES_IV, body)).decode()


def _sig_query_param(query: str, name: str) -> str:
    text = str(query or "")
    if text.startswith("?"):
        text = text[1:]
    if "#" in text:
        text = text.split("#", 1)[0]
    for part in text.split("&"):
        if not part:
            continue
        key = part.split("=")
        if key[0] == name:
            return "=".join(key[1:]) if len(key) > 1 else ""
    return ""


def _sig_argus_sign(query: str, stub_hex: str, ts: int, aid: int, license_id: int,
                   device_id: str, install_id: str = "", rand_field: int = 0) -> str:
    if not rand_field:
        rand_field = random.randint(1, 2147483647)
    body_hash = _sig_sm3_prefix6(bytes.fromhex(stub_hex)) if stub_hex else _sig_sm3_prefix6(b"\0" * 16)
    query_hash = _sig_sm3_prefix6(query.encode("utf-8")) if query else _sig_sm3_prefix6(b"\0" * 16)
    bean = _DmPbuf()
    bean.v(1, 1077940818).v(2, 2).v(3, rand_field)
    bean.s(4, aid).s(5, device_id).s(6, license_id)
    bean.s(7, _sig_query_param(query, "version_name"))
    bean.s(8, "v04.04.05-ov-android").v(9, 134744640).raw(10, b"\0" * 8).v(11, 0)
    bean.v(12, ts * 2)
    bean.raw(13, body_hash).raw(14, query_hash)
    bean.pb(15, _DmPbuf().v(1, 1).v(2, 1).v(3, 1).v(7, 0xC792ECCC))
    bean.s(16, install_id).s(20, "none").v(21, 738)
    bean.pb(23, _DmPbuf().s(1, "NX551J").v(2, 8196).v(4, 0x80E0D800))
    bean.v(25, 2)
    return _sig_argus_encrypt(bean)


def _sig_ladon_expand(md5hex: str) -> bytearray:
    ht = bytearray(288)
    for i in range(min(32, len(md5hex))):
        ht[i] = ord(md5hex[i])

    def load(off: int) -> tuple:
        lo = (ht[off] | ht[off + 1] << 8 | ht[off + 2] << 16 | ht[off + 3] << 24) & _SIG_U32
        hi = (ht[off + 4] | ht[off + 5] << 8 | ht[off + 6] << 16 | ht[off + 7] << 24) & _SIG_U32
        return (hi, lo)

    temp = [load(0), load(8), load(16), load(24)]
    b0, b8 = temp[0], temp[1]
    temp = [temp[2], temp[3]]
    for i in range(34):
        x9 = b0
        x8 = _sig_rotr64(b8, 8)
        x8 = _sig_add64(x8, x9)
        x8 = (x8[0], x8[1] ^ i)
        temp.append(x8)
        x8 = _sig_x64(x8, _sig_rotl64(x9, 3))
        for j in range(8):
            ht[(i + 1) * 8 + j] = ((x8[1] >> (8 * j)) if j < 4 else (x8[0] >> (8 * (j - 4)))) & 0xFF
        b0 = x8
        b8 = temp.pop(0)
    return ht


def _sig_ladon_block(ht: bytearray, src: bytearray, off: int) -> bytes:
    d0 = ((src[off + 4] | src[off + 5] << 8 | src[off + 6] << 16 | src[off + 7] << 24) & _SIG_U32,
          (src[off] | src[off + 1] << 8 | src[off + 2] << 16 | src[off + 3] << 24) & _SIG_U32)
    d1 = ((src[off + 12] | src[off + 13] << 8 | src[off + 14] << 16 | src[off + 15] << 24) & _SIG_U32,
          (src[off + 8] | src[off + 9] << 8 | src[off + 10] << 16 | src[off + 11] << 24) & _SIG_U32)
    for i in range(34):
        h0 = (ht[i * 8 + 4] | ht[i * 8 + 5] << 8 | ht[i * 8 + 6] << 16 | ht[i * 8 + 7] << 24) & _SIG_U32
        h1 = (ht[i * 8] | ht[i * 8 + 1] << 8 | ht[i * 8 + 2] << 16 | ht[i * 8 + 3] << 24) & _SIG_U32
        total = _sig_add64(d0, _sig_rotr64(d1, 8))
        d1 = (h0 ^ total[0], h1 ^ total[1])
        d0 = _sig_x64(d1, _sig_rotl64(d0, 3))
    out = bytearray()
    _sig_u64le_write(d0, out)
    _sig_u64le_write(d1, out)
    return bytes(out)


def _sig_ladon_encrypt_raw(md5hex: str, data: bytes) -> bytes:
    ht = _sig_ladon_expand(md5hex)
    pad = 16 - (len(data) % 16)
    src = bytearray(data) + bytes([pad]) * pad
    out = bytearray()
    for i in range(len(src) // 16):
        out.extend(_sig_ladon_block(ht, src, i * 16))
    return bytes(out)


def _sig_ladon_encrypt(ts: int, license_id: int, aid: int, rand4: bytes) -> str:
    data = ("%d-%d-%d" % (ts, license_id, aid)).encode("utf-8")
    keygen = rand4 + str(aid).encode("utf-8")
    enc = _sig_ladon_encrypt_raw(hashlib.md5(keygen).hexdigest(), data)
    return base64.b64encode(rand4 + enc).decode()


def _sig_sign_headers(query: str, body: bytes, device_id: str, install_id: str = "",
                     aid: int = 8662, license_id: int = 1611921764) -> dict:
    ts = int(time.time())
    stub = hashlib.md5(body).hexdigest() if body else ""
    headers = {
        "x-ss-req-ticket": str(ts * 1000),
        "x-khronos": str(ts),
        "x-ladon": _sig_ladon_encrypt(ts, license_id, aid, bytes(random.getrandbits(8) for _ in range(4))),
        "x-argus": _sig_argus_sign(query, stub, ts, aid, license_id, device_id, ""),
    }
    if stub:
        headers["x-ss-stub"] = stub
    return headers


class Spider(_BaseSpider):
    def __init__(self):
        self.device_id = str(random.randint(10**17, 10**18 - 1))
        self.install_id = str(random.randint(10**17, 10**18 - 1))

    def _adopt_working_pair(self):
        pair = _working_device_pair()
        if pair is not None:
            self.device_id = pair["device_id"]
            self.install_id = pair["install_id"]

    def getName(self):
        return "红果短剧"

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return (".mp4" in u) or ("video_mp4" in u) or ("m3u8" in u) or ("mime_type=video" in u) or ("qznovelvod" in u)

    def manualVideoCheck(self):
        return False

    def getDependence(self):
        return []

    def download(self, path, url):
        return ""

    def liveContent(self, url=""):
        return {}

    def isVPAYard(self, flag):
        return False

    def action(self, action):
        return ""

    def init(self, extend=""):
        # 每次源实例使用随机合法设备标识；不依赖用户私有配置。
        try:
            _hg_cache_cleanup(False)
        except Exception:
            pass
        return None

    def destroy(self):
        try:
            _hg_cache_cleanup(False)
        except Exception:
            pass

    def homeContent(self, filter):
        """分类=官方内容类型（真人剧/漫剧/漫画），二级分类取官方分类路由。"""
        class_list = [{"type_id": k, "type_name": n} for k, n, _ in _HG_CONTENT_TYPES]
        filters = {}
        for k, _n, cats in _HG_CONTENT_TYPES:
            if len(cats) > 1:
                filters[k] = [{
                    "key": "cat",
                    "name": "分类",
                    "value": [{"n": nm, "v": v} for v, nm in cats],
                }]
        vlist = []
        try:
            vlist = _hg_home_sections()
        except Exception:
            vlist = []
        try:
            _hg_prefetch([x.get("vod_id") for x in vlist], 6)
        except Exception:
            pass
        return {"class": class_list, "filters": filters, "list": vlist}

    def homeVideoContent(self):
        """NewBox/TVBox 系宿主的首页卡片单独走这个方法取，缺它会整页空白。"""
        try:
            vlist = _hg_home_sections()
        except Exception:
            vlist = []
        return {"list": vlist}

    def homeVod(self):
        return self.homeVideoContent()

    def categoryContent(self, tid, pg, filter, extend):
        """走官方分类页 /category/{route}/{item}?page=N，标题取官方 series_name。"""
        try:
            page = max(1, int(pg))
        except (TypeError, ValueError):
            page = 1
        route = _hg_route_of(tid)
        ext = {}
        if isinstance(extend, str) and extend:
            try:
                ext = json.loads(extend)
            except Exception:
                ext = {}
        elif isinstance(extend, dict):
            ext = dict(extend)
        cat = str(ext.get("cat") or ext.get("分类") or "").strip()
        if isinstance(filter, dict):
            f2 = str(filter.get("cat") or filter.get("分类") or "").strip()
            if f2 and not cat:
                cat = f2
        if cat in ("all", "全部", "0", "all_cat"):
            cat = ""
        try:
            p = _hg_category_page(route, cat, page)
        except Exception:
            p = _hg_category_page("real-drama", cat, page)
        rows = p.get("recommendList") or []
        page_data = p.get("pagination") or {}
        return {
            "page": page,
            "pagecount": int(page_data.get("totalPages") or 1),
            "limit": len(rows),
            "total": int(page_data.get("total") or len(rows)),
            "list": _hg_cat_list(rows),
        }

    def searchContent(self, key, quick=False, pg="1"):
        try:
            page = max(1, int(pg))
        except (TypeError, ValueError):
            page = 1
        key = str(key or "").strip() or "短剧"
        # 漫剧相关搜索走关键词轮换，提升翻页体验
        if key in ("漫剧", "动漫短剧"):
            return _search_by_keywords(_MANJU_KEYWORDS, page)

        p = _search_loader(key, page)
        rows = p.get("searchList") or []
        if not rows:
            # 官方搜索风控不可用时，扫官方分类页按标题命中兜底
            scanned = _hg_search_scan(key, page)
            if scanned.get("list"):
                return scanned
        try:
            total = int(p.get("totalCount") or 0)
        except Exception:
            total = 0
        try:
            total_pages = int(p.get("totalPages") or 1)
        except Exception:
            total_pages = 1
        out = []
        seen = set()
        for x in rows:
            it = _item(x)
            vid = str(it.get("vod_id") or "")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            out.append(it)
        if not total:
            total = len(out)
        try:
            _hg_prefetch([x.get("vod_id") for x in out], 2)
        except Exception:
            pass
        return {
            "page": page,
            "pagecount": max(1, min(50, total_pages if total_pages else 1)),
            "limit": len(out),
            "total": total,
            "list": out,
        }


    def detailContent(self, ids):
        sid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        sid = sid.replace("hg-series-v1:", "")
        s = {}
        seasons = []
        # 磁盘缓存（6 小时）：同一部剧二次进入零请求
        try:
            _c = _hg_disk_load().get(sid)
            if isinstance(_c, dict) and _c.get("v") == 3 and time.time() - float(_c.get("ts") or 0) < (
                    12 * 3600 if len(_c.get("seasons") or []) > 1 else 24 * 3600):
                seasons = [(int(x.get("no") or 0), x.get("sd") or {})
                           for x in (_c.get("seasons") or []) if isinstance(x, dict)]
                for _no, _d in seasons:
                    if str(_d.get("series_id") or u"") == sid:
                        s = _d
                        break
                if not s:
                    s = _c.get("self") or {}
        except Exception:
            s = {}
            seasons = []
        if not s:
            s = _hg_sd(sid)
            try:
                seasons = _hg_seasons(sid, s)
            except Exception:
                seasons = [(0, s)]
            try:
                _all = _hg_disk_load()
                _payload = {"v": 3, "ts": time.time(), "self": _hg_slim(s),
                            "seasons": [{"no": no, "sd": _hg_slim(d)} for no, d in seasons]}
                _all[sid] = _payload
                # 同组的其它季也各存一份，从搜索直接点别的季也能零请求命中
                for _no, _d in seasons:
                    _xid = str(_d.get("series_id") or "")
                    if _xid and _xid != sid:
                        _all[_xid] = _payload
                _hg_disk_save(_all)
            except Exception:
                pass
        vids = s.get("vid_list") or []
        actors = [str(x.get("nickname")) for x in (s.get("celebrities") or []) if isinstance(x, dict) and x.get("nickname")]
        play_from = []
        play_url = []
        if len(seasons) > 1:
            # 多季：一季一条线路，画质固定超清（1080），线路名「第一季 超清」
            used = set()
            # 季号 → 线路名：按季号排位命名，没季号的按它在序列里的位次补
            seq = sorted(seasons, key=lambda t: (t[0] if t[0] else 1))
            label_of = {}
            for i, (no, d) in enumerate(seq, 1):
                label_of[id(d)] = u"第%s季" % _hg_cn(no if no else i)
            # 当前点进来的那一季排第一，壳默认选中的就是它，避免点第五季却落在第一季上
            def _is_self(d):
                if d is s:
                    return True
                return str(d.get("series_id") or u"") == str(sid)
            ordered = [x for x in seq if _is_self(x[1])] + [x for x in seq if not _is_self(x[1])]
            for no, d in ordered:
                evids = [str(v) for v in (d.get("vid_list") or []) if str(v).isdigit()]
                if not evids or tuple(evids) in used:
                    continue
                used.add(tuple(evids))
                label = (label_of.get(id(d), u"红果") + u" 超清")
                if label in play_from:
                    label = label + u"2"
                eps = "#".join(
                    "%d%s%s%s:%s" % (i + 1, "$", EPISODE_PREFIX, "1080", v)
                    for i, v in enumerate(evids)
                )
                play_from.append(label)
                play_url.append(eps)
        if not play_from:
            # 单季：沿用模板五档画质线路，原样不动
            for q, line_name in _HG_QUALITY_LINES:
                eps = "#".join(
                    "%d%s%s%s%s:%s" % (i + 1, "$", EPISODE_PREFIX, q, "", str(v))
                    for i, v in enumerate(vids)
                )
                play_from.append(line_name)
                play_url.append(eps)
        return {"list": [{"vod_id": sid, "vod_name": str(s.get("series_name") or ""), "vod_pic": str(s.get("series_cover") or ""), "vod_year": "", "vod_area": "", "vod_director": "", "vod_actor": ",".join(actors), "vod_content": str(s.get("series_intro") or ""), "vod_remarks": str(s.get("episode_right_text") or ""), "vod_play_from": "$$$".join(play_from), "vod_play_url": "$$$".join(play_url)}]}

    def playerContent(self, flag, id, vipFlags=None):
        self._adopt_working_pair()
        # 从线路名（flag，如“红果超清/红果高清”）与集 token 双路解析清晰度。
        # token 已是 'hg-episode-v1:<q>:<vid>'，flag 用于旧壳只传线路名时兜底。
        token_q, vid = _split_episode_token(id)
        line_q = "1080"
        for name_key, candidate_q in _QUALITY_LINE_NAME_TO_Q.items():
            if name_key in str(flag or ""):
                line_q = candidate_q
                break
        q = line_q if token_q == "1080" and str(flag) else token_q
        q = q if q in _QUALITY_LINE_NAME_TO_Q else "1080"
        if not str(vid).isdigit():
            return {
                "parse": 1,
                "jx": 0,
                "playUrl": "",
                "url": SITE + "/",
                "header": {"User-Agent": UA},
            }
        # 取流优先级：本机 Range 流服务 > 上游直通直链 > 壳代理。
        # 壳代理（fongmi / OK影视 的 /proxy?do=py）实测会忽略 Range：对 bytes=0-1023
        # 也回 200 + 整片 + chunked，既无 Content-Range 也无 Accept-Ranges，且必须
        # 等整片下载 + CENC 解密完成后才吐首字节（单集 12~17MB，实测 8.7s / 16.3s，
        # 超过播放器默认 8s 读超时）。首集常因缓存或重试侥幸起播，切到第二集时播放器
        # 按新 URL 重新请求即超时失败，表现为“第 1 集能放、第 2 集不能放”。
        # 本机流服务支持 206 / Content-Range / Accept-Ranges，首字节约 1s，切集稳定。
        # 会话构建（取 video_model + 拉 moov）在冷启动时约 3~18s，若等到播放器连上来
        # 才建会话，响应头会被拖延到读超时。这里先建好会话再交 URL。
        cfg = {"device_id": self.device_id or "", "install_id": self.install_id or ""}
        session = None
        try:
            session = _stream_session(vid, cfg, q)
        except Exception:
            session = None

        def _try_start_server(wait):
            # 启本机服务对直通路/中转(CENC路)是加分项而非前提；宿主环境禁止
            # bind 127.0.0.1 时 _start_stream_server 可能挂起，放线程里限时等，
            # 拿不到端口就放弃，绝不让播放器干等。
            box = {}
            def _run():
                try:
                    box["port"] = _start_stream_server()
                except Exception:
                    pass
            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(wait)
            return box.get("port", 0)

        # 直通流（上游本来就是标准 hvc1/avc1 未加密）：本机服务起不来时可以直接把
        # 上游 https 直链交给播放器，播放器自己发 Range，不会卡在“正在获取播放信息”。
        plain_url = ""
        if isinstance(session, _PlainSession):
            plain_url = session.url or ""

        port = _try_start_server(1.5 if plain_url else 3.0)
        if port:
            query = urlencode(
                {
                    "vid": vid,
                    "q": q,
                    "did": self.device_id or "",
                    "iid": self.install_id or "",
                }
            )
            result = {
                "parse": 0,
                "jx": 0,
                "playUrl": "",
                "url": "http://127.0.0.1:%d/hg.mp4?%s" % (port, query),
                "header": {"User-Agent": UA},
            }
            return result
        # 本机服务不可用（宿主禁 bind 127.0.0.1）：直通流直接交上游直链。
        if plain_url:
            return {
                "parse": 0,
                "jx": 0,
                "playUrl": "",
                "url": plain_url,
                "header": {"User-Agent": MEDIA_UA},
            }
        # 回退：壳代理（保留壳自带的 do=py，不要覆盖 do）
        proxy = ""
        try:
            if hasattr(self, "getProxyUrl"):
                proxy = (self.getProxyUrl() or "").strip()
        except Exception:
            proxy = ""
        if proxy:
            sep = "&" if "?" in proxy else "?"
            url = proxy + sep + urlencode(
                {
                    "vid": vid,
                    "q": q,
                    "hg": "cenc",
                    "did": self.device_id or "",
                    "iid": self.install_id or "",
                }
            )
            return {
                "parse": 0,
                "jx": 0,
                "playUrl": "",
                "url": url,
                "header": {
                    "User-Agent": MEDIA_UA,
                    "Referer": "https://novel.snssdk.com/",
                },
            }
        return {
            "parse": 1,
            "jx": 0,
            "playUrl": "",
            "url": SITE + "/",
            "header": {"User-Agent": UA},
        }


    def proxy(self, param):
        """部分壳调用 proxy 而不是 localProxy。"""
        return self.localProxy(param)

    def localProxy(self, param):
        """壳本地代理：优先读缓存；无原生 AES 时避免一上来就解 1080 整集导致超时失败。"""
        import traceback
        param = param or {}
        self._adopt_working_pair()
        vid = str(
            param.get("vid")
            or param.get("id")
            or param.get("mediaId")
            or ""
        ).strip()
        if not vid or not str(vid).isdigit():
            for _key, value in param.items():
                text = str(value or "").strip()
                if text.isdigit() and len(text) >= 10:
                    vid = text
                    break
        if not vid:
            return [400, "text/plain; charset=utf-8", b"missing vid"]

        try:
            cfg = {
                "device_id": str(param.get("did") or self.device_id or ""),
                "install_id": str(param.get("iid") or self.install_id or ""),
            }
            user_q = str(param.get("q") or param.get("quality") or "").strip()
            # 有原生 AES：优先 1080；纯 Python AES 很慢：先 720 保证能播，再尝试更高
            if user_q:
                order = [user_q, "1080", "720", "480", "360"]
            elif _aes_is_fast():
                order = ["1080", "720", "480", "360"]
            else:
                order = ["720", "480", "1080", "360"]
            # dedupe
            seen_q = set()
            quals = []
            for q in order:
                if q and q not in seen_q:
                    seen_q.add(q)
                    quals.append(q)

            # 缓存命中直接返回。用户指定线路清晰度(user_q)时，只认该清晰度缓存，
            # 不能回退命中其它清晰度缓存（否则请求480会拿到360内容）。
            if user_q:
                primary = [user_q]
            else:
                primary = quals
            for q in primary:
                cached = _hg_cache_get(vid, q)
                if cached and _hg_cached_ok(cached):
                    return [200, "video/mp4", cached]

            model = None
            rows = None
            for _round in range(4):
                try:
                    model = _video_model(vid, cfg)
                except Exception as err:
                    if not _is_empty_model_error(err) or _round >= 3:
                        raise
                    pair = _rotate_stream_device()
                    cfg = {"device_id": pair["device_id"], "install_id": pair["install_id"]}
                    self.device_id = pair["device_id"]
                    self.install_id = pair["install_id"]
                    continue
                rows = _video_list_from_model(model)
                if rows:
                    break
                if _round >= 3:
                    break
                pair = _rotate_stream_device()
                cfg = {"device_id": pair["device_id"], "install_id": pair["install_id"]}
                self.device_id = pair["device_id"]
                self.install_id = pair["install_id"]
            if not rows:
                return [500, "text/plain; charset=utf-8", b"empty video list"]

            last_err = None
            for wanted in quals:
                try:
                    # 再查一次该清晰度缓存（model 解析后）
                    cached = _hg_cache_get(vid, wanted)
                    if cached and _hg_cached_ok(cached):
                        return [200, "video/mp4", cached]

                    if _hg_is_bytevc2(rows):
                        # 只认这一档自己验过的标准 hvc1 直通流；encv 是加密壳，不能直接回吐
                        try:
                            plain_sess = _hg_plain_session(model, wanted, True)
                        except Exception:
                            plain_sess = None
                        if plain_sess is not None:
                            body = b""
                            try:
                                body = _multi_download(
                                    plain_sess.url,
                                    headers={"User-Agent": MEDIA_UA, "Referer": "https://novel.snssdk.com/"},
                                    timeout=150 if _aes_is_fast() else 120,
                                    workers=4,
                                )
                            except Exception as dl_err:
                                last_err = "plain download failed q=%s err=%s" % (wanted, dl_err)
                                body = b""
                            _i = body.find(b"stsd") if body else -1
                            if body and (_i < 0 or body[_i + 16 : _i + 20] in _DECODABLE_ENTRIES):
                                try:
                                    _hg_cache_put(vid, wanted, body)
                                except Exception:
                                    pass
                                return [200, "video/mp4", body]

                    _, item = _select_quality(rows, wanted)
                    url = _media_url(item)
                    spade = _spade_value(item)
                    if not url or not spade:
                        last_err = "missing url/spade q=%s" % wanted
                        continue
                    try:
                        key_seed = _key_seed_from_model(model)
                        if key_seed:
                            url = _decrypt_spade_url(url, key_seed)
                    except Exception:
                        pass

                    # 下载超时：纯 AES 环境更短，避免壳端空等后失败
                    dl_timeout = 150 if _aes_is_fast() else 90
                    media_headers = {
                        "User-Agent": MEDIA_UA,
                        "Referer": "https://novel.snssdk.com/",
                    }
                    try:
                        body = _multi_download(
                            url,
                            headers=media_headers,
                            timeout=dl_timeout,
                            workers=4 if _aes_is_fast() else 3,
                        )
                    except Exception as dl_err:
                        last_err = "download failed q=%s err=%s" % (wanted, dl_err)
                        continue
                    if not body:
                        last_err = "empty body q=%s" % wanted
                        continue

                    # 纯 AES 且体积过大时跳过超大 1080，减少必超时
                    if (not _aes_is_fast()) and wanted in ("1080", "4k") and len(body) > 45 * 1024 * 1024:
                        last_err = "skip large %s without native AES size=%s" % (wanted, len(body))
                        continue

                    plain = decrypt_mp4_cenc(body, derive_content_key(spade))
                    if len(plain) < 64 or (b"ftyp" not in plain[:64] and b"moov" not in plain[:4096]):
                        last_err = "bad mp4 after decrypt q=%s" % wanted
                        continue
                    # 视轨校验：个别清晰度解出来只有音轨，换下一个清晰度，避免播出「只有声音」的片
                    _mo, _ms = _find_box(memoryview(plain), b"moov", 0)
                    if _mo >= 0 and _ms > 8 and not _moov_has_video_track(bytes(plain[_mo : _mo + _ms])):
                        last_err = "no video track q=%s" % wanted
                        continue
                    try:
                        _hg_cache_put(vid, wanted, plain)
                    except Exception:
                        pass
                    return [200, "video/mp4", plain]
                except Exception as one_err:
                    last_err = "%s q=%s" % (one_err, wanted)
                    continue

            msg = "hg localProxy failed: %s" % last_err
            return [500, "text/plain; charset=utf-8", msg.encode("utf-8")]
        except Exception as exc:
            msg = "hg localProxy failed: %s\n%s" % (exc, traceback.format_exc())
            return [500, "text/plain; charset=utf-8", msg.encode("utf-8")]


# ================== 合并层：基础工具（text / 导入） ==================
import http.client
import ssl
import urllib.parse


def text(v):
    if v is None:
        return ""
    return str(v).strip()


# --- AES-128 (FIPS-197)，用于 ttEncrypt 的 CBC-Pkcs7

_AES_SBOX = (
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
)

_AES_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36)


def _aes_xtime(a):
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 255


def _aes_mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _aes_xtime(a)
        b >>= 1
    return r


def _aes_expand_key(key):
    w = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_AES_SBOX[x] for x in t]
            t[0] ^= _AES_RCON[i // 4 - 1]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return w


def _aes_encrypt_block(block, w):
    s = list(block)
    for c in range(4):
        for r in range(4):
            s[4 * c + r] ^= w[c][r]
    for rnd in range(1, 11):
        s = [_AES_SBOX[x] for x in s]
        old = list(s)
        for r in range(1, 4):
            for c in range(4):
                s[4 * c + r] = old[4 * ((c + r) % 4) + r]
        if rnd != 10:
            for c in range(4):
                a0, a1, a2, a3 = s[4 * c], s[4 * c + 1], s[4 * c + 2], s[4 * c + 3]
                s[4 * c] = _aes_mul(a0, 2) ^ _aes_mul(a1, 3) ^ a2 ^ a3
                s[4 * c + 1] = a0 ^ _aes_mul(a1, 2) ^ _aes_mul(a2, 3) ^ a3
                s[4 * c + 2] = a0 ^ a1 ^ _aes_mul(a2, 2) ^ _aes_mul(a3, 3)
                s[4 * c + 3] = _aes_mul(a0, 3) ^ a1 ^ a2 ^ _aes_mul(a3, 2)
        for c in range(4):
            for r in range(4):
                s[4 * c + r] ^= w[rnd * 4 + c][r]
    return bytes(s)


def _aes_cbc_encrypt_pkcs7(data, key, iv):
    data = bytes(data)
    pad = 16 - len(data) % 16
    data = data + bytes([pad]) * pad
    w = _aes_expand_key(bytes(key))
    prev = bytes(iv)
    out = bytearray()
    for i in range(0, len(data), 16):
        blk = bytes(a ^ b for a, b in zip(data[i:i + 16], prev))
        prev = _aes_encrypt_block(blk, w)
        out += prev
    return bytes(out)


# --- 備用播放源（紅果取流被網關封鎖時的兜底） ---

_BACKUP_SOURCES = (
    ("360", "https://360zy.com/api.php/provide/vod/"),
    ("liangzi", "https://cj.lziapi.com/api.php/provide/vod/"),
    ("ffzy", "https://cj.ffzyapi.com/api.php/provide/vod/"),
    ("dytt", "https://caiji.dyttzyapi.com/api.php/provide/vod/"),
)


def _backup_norm(s):
    t = re.sub(r"\s+", "", text(s))
    t = re.sub(r"[（(].*?[）)]", "", t)
    t = re.sub(r"[：:，,。！!？?·\-—_]", "", t)
    for w in ("短剧", "合集", "全集", "第.季", "第.部", "第.集"):
        t = re.sub(w, "", t)
    return t


def _precise_norm(s):
    """相關短劇用的精準歸一化：只去空白/標點/括號，保留「第X季/第X部」，避免跨季誤配。"""
    t = re.sub(r"\s+", "", text(s))
    t = re.sub(r"[（(].*?[）)]", "", t)
    t = re.sub(r"[：:，,。！!？?·\-—_、]", "", t)
    for w in ("短剧", "合集", "全集"):
        t = re.sub(w, "", t)
    return t


def _backup_aliases(name):
    out = []
    raw = text(name)
    if raw:
        out.append(raw)
    for sep in ("之", "，", "：", ":"):
        if sep in raw:
            head = text(raw.split(sep)[0])
            if len(head) >= 3:
                out.append(head)
    seen, res = set(), []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            res.append(x)
    return res


def _backup_episodes(v):
    best = []
    for line in str(v.get("vod_play_url") or "").split("$$$"):
        urls = []
        for item in line.split("#"):
            if "$" not in item:
                continue
            u = text(item.split("$", 1)[1])
            if re.match(r"^https?://", u, re.I):
                urls.append(u)
        # 條數多者優先；條數相同時優先直鏈 .m3u8（避免 /share/ 落地頁）
        if len(urls) > len(best) or (
                urls and len(urls) == len(best) and best
                and not re.search(r"\.m3u8", best[0], re.I)
                and re.search(r"\.m3u8", urls[0], re.I)):
            best = urls
    return best


def _backup_json(net, base, word):
    url = base + "?ac=videolist&wd=" + urllib.parse.quote(text(word))
    resp = net.http(url, {"method": "GET", "headers": {"User-Agent": _APP_UA},
                          "timeout": 15000})
    if resp and resp.get("error"):
        raise RuntimeError(str(resp.get("error")))
    return json.loads(str(resp.get("content") or "{}"))


def _backup_resolve(net, url):
    """部分採集站給的是 /share/ 落地頁，需從頁面裡摳出 m3u8。"""
    if re.search(r"\.m3u8(\?|$)", url, re.I):
        return url
    try:
        resp = net.http(url, {"method": "GET", "headers": {"User-Agent": _APP_UA},
                              "timeout": 15000})
        body = str(resp.get("content") or "")
    except Exception:
        return url
    if "#EXTM3U" in body[:200]:
        return url
    m = re.search(r"https?://[^\"'<>\s\\]+?\.m3u8[^\"'<>\s\\]*", body)
    if m:
        return m.group(0)
    m = re.search(r"[\"'](/[^\"'<>\s\\]+?\.m3u8[^\"'<>\s\\]*)", body)
    if m:
        return urllib.parse.urljoin(url, m.group(1))
    return url


def backup_series(net, title):
    """找同名劇並回整份分集清單（不解析落地頁），供逐集複用避免重複搜索。"""
    want = _backup_norm(title)
    best = None
    for word in _backup_aliases(title):
        key = _backup_norm(word)
        for tag, base in _BACKUP_SOURCES:
            try:
                data = _backup_json(net, base, word)
            except Exception:
                continue
            for v in (data.get("list") or []):
                if not isinstance(v, dict):
                    continue
                name = _backup_norm(v.get("vod_name"))
                if name != want and name != key:
                    continue
                eps = _backup_episodes(v)
                if not eps:
                    continue
                score = (1 if len(eps) > 1 else 0, len(eps))
                if best is None or score > best[0]:
                    best = (score, {"from": tag, "name": text(v.get("vod_name")), "eps": eps})
                # 分集源直接定案，省掉後續源的搜索
                if len(eps) > 1:
                    return {"from": tag, "name": text(v.get("vod_name")), "eps": eps}
    return best[1] if best else None


def backup_lookup(net, title, index):
    """用劇名在備用採集站找同名劇，回該集（或第一集）的直鏈。"""
    want = _backup_norm(title)
    best = None
    for word in _backup_aliases(title):
        key = _backup_norm(word)
        for tag, base in _BACKUP_SOURCES:
            try:
                data = _backup_json(net, base, word)
            except Exception:
                continue
            for v in (data.get("list") or []):
                if not isinstance(v, dict):
                    continue
                name = _backup_norm(v.get("vod_name"))
                # 必須與目標或別名完全同名，否則會把任意結果當成命中
                if name != want and name != key:
                    continue
                eps = _backup_episodes(v)
                if not eps:
                    continue
                # 分集源優於合集源（合集只能整部從頭播）
                score = (1 if len(eps) > 1 else 0, len(eps))
                if best is None or score > best[0]:
                    best = (score, tag, v, eps)
                # 命中分集源且集數夠，立即返回，省掉後續源的搜索
                if len(eps) > 1 and len(eps) >= int(index or 1):
                    url = _backup_resolve(net, eps[int(index or 1) - 1])
                    return {"url": url, "from": tag, "episodes": len(eps),
                            "name": text(v.get("vod_name"))}
    if best is None:
        return None
    _, tag, v, eps = best
    i = int(index or 1)
    url = eps[i - 1] if 0 < i <= len(eps) else eps[-1]
    url = _backup_resolve(net, url)
    return {"url": url, "from": tag, "episodes": len(eps),
            "name": text(v.get("vod_name"))}


# --- 河豚線路（4K 源的短劇/漫劇接口，純標準庫實現） ---

try:
    from Crypto.PublicKey import RSA as _HT_RSA
    from Crypto.Cipher import PKCS1_v1_5 as _HT_PKCS1
except Exception:
    _HT_RSA = _HT_PKCS1 = None

_HT_CONFIG = {
    "publicKey": "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCr8SzZhjYy+rsya1K09t8d2K50pWFoBkgUqMpKOiW+3IEVKd4eTdvg9RSOjQ82kypL6R9BnsmrS1V8s4PVDwjQbUtYhTPPC9Hz16qY7rpD6m0d2vr09/UpWQ5uOy9PR0QTrsioveZ+DIe9jc3C+zBCu/kZSY/R8stwJoiitki3gwIDAQAB",
    "mSafeCode": "V04XQZNYRWN6T0JODZFIAG5CTZB3PT0=",
    "dataIv": "OC1A06E197EF10CF3F6058CA7A803B5E",
    "pkg": "com.djlxxl.xcydzkj",
    "host": "https://az1-1456692500.cos.ap-guangzhou.myqcloud.com/az1.txt",
    "vName": "7.0.0.2",
}


class _HeTun(object):
    """河豚短劇/漫劇線路：protobuf + AES + RSA 簽名的自建實現。"""

    def __init__(self):
        self.cfg = dict(_HT_CONFIG)
        self.host = ""
        self.public_key = self.cfg["publicKey"]
        self.data_key = self.cfg["mSafeCode"]
        self.data_iv = self.cfg["dataIv"]
        self.common_key = "ed5fdsgucxumegqa"
        self.version = self.cfg["vName"]
        self.dynamic_key = ""
        self._rnd = random.Random()

    # ---- 基礎
    def _random(self, length):
        chars = "1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        n = max(0, int(length) - 1)
        return "".join(chars[self._rnd.randrange(len(chars))] for _ in range(n)) + "="

    @staticmethod
    def _varint(value):
        value = int(value)
        out = bytearray()
        while value > 0x7f:
            out.append((value & 0x7f) | 0x80)
            value >>= 7
        out.append(value)
        return bytes(out)

    @classmethod
    def _pb_int(cls, field, value):
        return cls._varint(field << 3) + cls._varint(value)

    @classmethod
    def _pb_bytes(cls, field, value):
        if isinstance(value, str):
            value = value.encode("utf-8")
        return cls._varint((field << 3) | 2) + cls._varint(len(value)) + value

    @staticmethod
    def _read_varint(data, pos):
        value, shift = 0, 0
        while pos < len(data):
            b = data[pos]
            pos += 1
            value |= (b & 0x7f) << shift
            if not b & 0x80:
                return value, pos
            shift += 7
        raise ValueError("bad varint")

    @classmethod
    def _pb_parse(cls, data):
        fields, pos = {}, 0
        while pos < len(data):
            key, pos = cls._read_varint(data, pos)
            field, wire = key >> 3, key & 7
            if wire == 0:
                value, pos = cls._read_varint(data, pos)
            elif wire == 1:
                value, pos = data[pos:pos + 8], pos + 8
            elif wire == 2:
                size, pos = cls._read_varint(data, pos)
                value, pos = data[pos:pos + size], pos + size
            elif wire == 5:
                value, pos = data[pos:pos + 4], pos + 4
            else:
                raise ValueError("bad wire type")
            fields.setdefault(field, []).append(value)
        return fields

    @staticmethod
    def _first(fields, number, default=b""):
        values = fields.get(number)
        return values[0] if values else default

    @staticmethod
    def _text(value):
        if isinstance(value, bytes):
            return value.decode("utf-8", "ignore")
        return str(value or "")

    # ---- 加密
    @staticmethod
    def _aes_schedule(key):
        # 河豚的三個 key 分別是 16/24/32 字節，需要 AES-128/192/256 通用密鑰編排
        key = str(key).encode("utf-8")
        nk = len(key) // 4
        nr = nk + 6
        w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
        rcon = 1
        for i in range(nk, 4 * (nr + 1)):
            t = list(w[i - 1])
            if i % nk == 0:
                t = t[1:] + t[:1]
                t = [_AES_SBOX[x] for x in t]
                t[0] ^= rcon
                rcon = _aes_mul(rcon, 2)
            elif nk > 6 and i % nk == 4:
                t = [_AES_SBOX[x] for x in t]
            w.append([w[i - nk][j] ^ t[j] for j in range(4)])
        return w, nr

    @staticmethod
    def _aes_block(block, w, nr):
        s = list(block)

        def add_round(r):
            for c in range(4):
                for rr in range(4):
                    s[4 * c + rr] ^= w[4 * r + c][rr]

        def shift(rows):
            old = list(rows)
            for rr in range(1, 4):
                for c in range(4):
                    rows[4 * c + rr] = old[4 * ((c + rr) % 4) + rr]

        def mix(rows):
            for c in range(4):
                a = rows[4 * c:4 * c + 4]
                rows[4 * c + 0] = _aes_mul(a[0], 2) ^ _aes_mul(a[1], 3) ^ a[2] ^ a[3]
                rows[4 * c + 1] = a[0] ^ _aes_mul(a[1], 2) ^ _aes_mul(a[2], 3) ^ a[3]
                rows[4 * c + 2] = a[0] ^ a[1] ^ _aes_mul(a[2], 2) ^ _aes_mul(a[3], 3)
                rows[4 * c + 3] = _aes_mul(a[0], 3) ^ a[1] ^ a[2] ^ _aes_mul(a[3], 2)

        add_round(0)
        for rnd in range(1, nr):
            s = [_AES_SBOX[x] for x in s]
            shift(s)
            mix(s)
            add_round(rnd)
        s = [_AES_SBOX[x] for x in s]
        shift(s)
        add_round(nr)
        return s

    @classmethod
    def _aes_ecb_b64(cls, text, key):
        data = str(text).encode("utf-8")
        pad = 16 - len(data) % 16
        data = data + bytes([pad]) * pad
        w, nr = cls._aes_schedule(key)
        out = bytearray()
        for i in range(0, len(data), 16):
            out += bytes(cls._aes_block(data[i:i + 16], w, nr))
        return base64.b64encode(bytes(out)).decode("utf-8")

    @classmethod
    def _aes_cbc_hex(cls, text, key):
        key_b = str(key).encode("utf-8")
        data = str(text).encode("utf-8")
        pad = 16 - len(data) % 16
        data = data + bytes([pad]) * pad
        w, nr = cls._aes_schedule(key)
        prev, out = key_b[:16], bytearray()
        for i in range(0, len(data), 16):
            blk = bytes(a ^ b for a, b in zip(data[i:i + 16], prev))
            prev = bytes(cls._aes_block(blk, w, nr))
            out += prev
        return bytes(out).hex()

    @staticmethod
    def _rsa_modulus(der):
        ints = []

        def walk(i, end):
            while i < end:
                tag = der[i]
                i += 1
                ln = der[i]
                i += 1
                if ln & 0x80:
                    n = ln & 0x7f
                    ln = int.from_bytes(der[i:i + n], "big")
                    i += n
                stop = i + ln
                if tag == 0x02:
                    ints.append(int.from_bytes(der[i:stop], "big"))
                elif tag == 0x30:
                    walk(i, stop)
                elif tag == 0x03 and stop > i:
                    walk(i + 1, stop)
                i = stop

        walk(0, len(der))
        return ints[0], ints[1]

    def _rsa_encrypt(self, text, key_b64):
        # 有 pycryptodome 就用它（服務端對填塞格式敏感），沒有才走純 Python
        if _HT_PKCS1 is not None:
            try:
                key = _HT_RSA.import_key(base64.b64decode(key_b64))
                return base64.b64encode(
                    _HT_PKCS1.new(key).encrypt(str(text).encode("utf-8"))).decode()
            except Exception:
                pass
        der = base64.b64decode(key_b64)
        n, e = self._rsa_modulus(der)
        msg = str(text).encode("utf-8")
        k = (n.bit_length() + 7) // 8
        ps_len = k - 3 - len(msg)
        if ps_len < 8:
            raise RuntimeError("rsa key too small")
        ps = bytes(self._rnd.randrange(1, 256) for _ in range(ps_len))
        em = b"\x00\x02" + ps + b"\x00" + msg
        return base64.b64encode(pow(int.from_bytes(em, "big"), e, n).to_bytes(k, "big")).decode()

    # ---- 請求
    def _http(self, url, body=None, headers=None, timeout=10):
        req = urllib.request.Request(url, data=body, headers=headers or {},
                                     method="POST" if body is not None else "GET")
        return urllib.request.urlopen(req, timeout=timeout).read()

    def _post(self, path, body):
        return self._http(self.host + path, body, self._headers(True))

    def _get_json(self, path):
        return json.loads(self._http(self.host + path, None, self._headers(False)).decode("utf-8", "replace"))

    def _device(self):
        uid = ("%032X" % self._rnd.getrandbits(128))
        return {
            "country": "CN", "vName": self.version, "cpuId": "MT6893Z%2FCZA", "young": 0,
            "facturer": "Xiaomi", "pkg": self.cfg["pkg"], "uuid": uid,
            "resolution": "1080x2272", "mac": "02%3A00%3A00%3A00%3A00%3A00", "abid": "397",
            "model": "M2012K11AC", "plat": "android", "udid": uid, "dpi": "440", "net": "1",
            "lang": "zh", "brand": "Xiaomi", "density": "2.75", "appName": "河豚",
            "cpu": "arm64-v8a", "chid": "10000", "carrier": "%E8%81%94%E9%80%9A",
            "_vOsCode": 30, "vOs": "11", "v": 1, "tenantId": "",
            "vApp": self.version.replace(".", ""), "device": 0, "androidID": uid.lower()[:16],
        }

    def _headers(self, protobuf=True):
        key = self.dynamic_key or self.public_key
        device = self._device()
        ts = int(time.time() * 1000)
        rnd = self._random(16)
        device["sig"] = self._rsa_encrypt(str(ts) + rnd + (device.get("vApp") or "3019"), key)
        device["random_str"] = rnd
        device["timestamp"] = ts
        sig23 = self._aes_ecb_b64(str(ts) + rnd, self.data_iv)
        device["sig2"] = sig23[:8]
        device["sig3"] = sig23[8:]
        params = self._aes_cbc_hex(json.dumps(device, ensure_ascii=False, separators=(",", ":")),
                                   self.common_key)
        ctype = "application/x-protobuf" if protobuf else "application/json; charset=utf-8"
        accept = "application/x-protobuf" if protobuf else "application/json"
        return {"User-Agent": "okhttp/3.12.1", "Accept": accept, "Content-Type": ctype,
                "publicParams": json.dumps({"paramsData": params}, separators=(",", ":"))}

    def _secure_body(self, params):
        ts = int(time.time() * 1000)
        rnd8 = self._random(8)
        fake20 = self._random(20)
        query = "&".join("%s=%s" % (k, v) for k, v in params.items()
                         if v is not None and str(v) != "")
        encrypted = rnd8 + self._aes_ecb_b64(query + str(ts), self.data_key)
        return b"".join([
            self._pb_bytes(1, encrypted[:20]), self._pb_bytes(2, encrypted[20:]),
            self._pb_bytes(3, fake20), self._pb_int(4, ts), self._pb_bytes(5, rnd8),
        ])

    def _api_data(self, raw):
        return self._first(self._pb_parse(raw), 3, b"")

    def _load_dynamic_key(self):
        ts = int(time.time() * 1000)
        rnd = self._random(16)
        sign = self._rsa_encrypt(str(ts) + rnd, self.public_key)
        body = b"".join([
            self._pb_int(1, ts), self._pb_bytes(2, sign), self._pb_bytes(3, self._random(16)),
            self._pb_bytes(4, rnd), self._pb_bytes(5, self._random(16)),
        ])
        data = self._api_data(self._post("/api/v5/find/app/zone", body))
        f = self._pb_parse(data)
        self.dynamic_key = "".join(self._text(self._first(f, n)) for n in (2, 3, 4, 5))

    def ready(self):
        if self.host:
            return True
        try:
            cfg_host = str(self.cfg.get("host", "")).rstrip("/")
            if cfg_host.endswith((".txt", ".json")):
                obj = json.loads(self._http(cfg_host).decode("utf-8", "replace"))
                self.host = str(obj.get("domain", "")).strip().rstrip("/")
            else:
                self.host = cfg_host
        except Exception:
            self.host = ""
        if not self.host:
            return False
        try:
            self._load_dynamic_key()
        except Exception:
            pass
        return True

    # ---- 業務
    def search(self, word):
        raw = self._post("/api/proto/v5/drama/search",
                         self._secure_body({"searchKeys": word, "page": "1", "pagesize": "21"}))
        page = self._pb_parse(self._api_data(raw))
        out = []
        for v in page.get(1, []):
            if not isinstance(v, (bytes, bytearray)):
                continue
            f = self._pb_parse(v)
            out.append({"vod_id": str(self._first(f, 3, 0)),
                        "vod_name": self._text(self._first(f, 5))})
        return out

    def category(self, tid, page=1, size=30):
        raw = self._post("/api/proto/v5/drama/category",
                         self._secure_body({"pagesize": str(size), "typeId1": str(tid),
                                            "page": str(page)}))
        f = self._pb_parse(self._api_data(raw))
        out = []
        for item in f.get(1, []):
            if not isinstance(item, (bytes, bytearray)):
                continue
            df = self._pb_parse(item)
            out.append((str(self._first(df, 3, 0)), self._text(self._first(df, 5))))
        return out

    def scan_name(self, want, pages=5):
        """搜索索引漏掉時，掃短劇/漫劇分類庫找同名（僅完全同名才算）。"""
        for tid in (27, 28):
            for pg in range(1, pages + 1):
                try:
                    rows = self.category(tid, pg)
                except Exception:
                    break
                if not rows:
                    break
                for sid, nm in rows:
                    if sid and _backup_norm(nm) == want:
                        return sid
        return ""

    def detail_lines(self, vod_id):
        raw = self._post("/api/proto/v5/drama/getDetail",
                         self._secure_body({"id": str(vod_id)}))
        f = self._pb_parse(self._api_data(raw))
        grouped, order = {}, []
        for item in f.get(29, []):
            if not isinstance(item, (bytes, bytearray)):
                continue
            vf = self._pb_parse(item)
            title = self._text(self._first(vf, 2)) or "播放"
            path = self._text(self._first(vf, 4))
            source = self._text(self._first(vf, 9))
            source_cn = self._text(self._first(vf, 10))
            if not path:
                continue
            quality = source_cn or source or "未知"
            name = "%s (%s)" % (quality, source) if source and quality != source else quality
            if re.search(r"(?i)\.(?:mp4|m3u8|flv|mkv|avi|ts|mov|mpd)(?:\?.*)?$", path):
                token = path
            else:
                token = base64.b64encode(json.dumps(
                    {"vodPlayFrom": source, "playUrl": path},
                    ensure_ascii=False, separators=(",", ":")).encode()).decode()
            if name not in grouped:
                grouped[name] = []
                order.append(name)
            grouped[name].append(title + "$" + token)
        return [(n, "#".join(grouped[n])) for n in order if grouped[n]]

    def play(self, token):
        if re.search(r"(?i)\.(?:mp4|m3u8|flv|mkv|avi|ts|mov|mpd)(?:\?.*)?$", str(token)):
            return {"url": token, "header": {}}
        params = json.loads(base64.b64decode(token).decode("utf-8"))
        raw = self._post("/api/proto/v5/videoUsableUrl", self._secure_body(params))
        f = self._pb_parse(self._api_data(raw))
        headers = {}
        for entry in f.get(6, []):
            ef = self._pb_parse(entry)
            k, v = self._text(self._first(ef, 1)), self._text(self._first(ef, 2))
            if k:
                headers[k] = v
        return {"url": self._text(self._first(f, 1)), "header": headers}


# --- 可可（kkys04）動漫/短劇線路 ---

_KK_HOST = "https://www.kkys04.com"
_KK_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 "
          "Mobile/15E148 Safari/604.1")


class _KK(object):
    """可可站點：cdndefend 風控用 sha1 proof-of-work 過，播放頁直接帶 m3u8。"""

    def __init__(self):
        self.host = _KK_HOST
        self._token = ""
        self._token_at = 0.0
        self._cookie = ""
        self._conn = None
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

    def _raw(self, url, cookie=""):
        """複用 HTTPS 長連接：每次新建 TLS 握手要 1~2 秒，連播時很喫虧。"""
        headers = {"User-Agent": _KK_UA, "Referer": self.host + "/",
                   "Accept-Encoding": "identity", "Connection": "keep-alive"}
        if cookie:
            headers["Cookie"] = cookie
        if url.startswith(self.host):
            path = url[len(self.host):] or "/"
        else:
            parts = urllib.parse.urlparse(url)
            path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
        for _ in range(2):
            try:
                if self._conn is None:
                    self._conn = http.client.HTTPSConnection(
                        self.host.split("//", 1)[1].split("/")[0], timeout=15,
                        context=self._ctx)
                self._conn.request("GET", path, headers=headers)
                resp = self._conn.getresponse()
                body = resp.read().decode("utf-8", "replace")
                st = resp.status
                if (resp.getheader("Connection") or "").lower() == "close":
                    self._conn.close()
                    self._conn = None
                if st in (301, 302, 303, 307, 308):
                    self._conn = None
                    break
                return st, body
            except Exception:
                if self._conn is not None:
                    try:
                        self._conn.close()
                    except Exception:
                        pass
                self._conn = None
        try:
            resp = urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=15, context=self._ctx)
            return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception:
            return 0, ""

    @staticmethod
    def _solve(page):
        m = re.search(r"'([0-9A-F]{32,64})','cdndefend_js_cookie='", page)
        if not m:
            return ""
        c = m.group(1)
        n1 = int(c[0], 16)
        idx = 0
        while idx < 2000000:
            d = hashlib.sha1((c + str(idx)).encode()).digest()
            if d[n1] == 0xb0 and d[n1 + 1] == 0x0b:
                return "cdndefend_js_cookie=%s%d" % (c, idx)
            idx += 1
        return ""

    def fetch(self, url):
        # 風控 cookie 復用，命中就不用每個請求都重解一次挑戰
        st, body = self._raw(url, self._cookie)
        if st == 850:
            ck = self._solve(body)
            if ck:
                self._cookie = ck
                st, body = self._raw(url, ck)
        return st, body

    def token(self):
        if self._token and time.time() - self._token_at < 600:
            return self._token
        _, home = self.fetch(self.host + "/")
        m = (re.search(r'name="t"[^>]*value="([^"]+)"', home)
             or re.search(r'value="([^"]+)"[^>]*name="t"', home))
        self._token = m.group(1) if m else ""
        self._token_at = time.time()
        return self._token

    def search(self, word):
        url = "%s/search?t=%s&k=%s" % (self.host, urllib.parse.quote(self.token()),
                                       urllib.parse.quote(text(word)))
        _, page = self.fetch(url)
        if "search-result-list" not in page:
            return []
        seg = page.split("search-result-list", 1)[1].split('<div class="pagenation-box', 1)[0]
        out = []
        for href, body in re.findall(
                r'<a href="([^"]+)"[^>]*class="search-result-item"[^>]*>(.*?)</a>', seg, re.S):
            kind = re.search(r'<div class="search-result-item-header">\s*<div>(.*?)</div>',
                             body, re.S)
            name = (re.search(r'<img[^>]*alt="([^"]+)"', body)
                    or re.search(r'<img[^>]*title="([^"]+)"', body)
                    or re.search(r'title="([^"]+)"', body))
            out.append({
                "url": href if href.startswith("http") else self.host + href,
                "type": re.sub(r"<[^>]+>", "", kind.group(1)).strip() if kind else "",
                "name": (name.group(1) if name else "").strip(),
            })
        return out

    def detail(self, url):
        _, page = self.fetch(url)
        best = []
        for block in re.findall(r'<div class="episode-list"[^>]*>(.*?)</div>', page, re.S):
            links = re.findall(r'href="([^"]+)"[^>]*class="episode-item"', block)
            if len(links) > len(best):
                best = links
        eps = []
        for i, href in enumerate(best):
            full = href if href.startswith("http") else self.host + href
            eps.append("第%d集$%s" % (i + 1, full))
        return eps

    def play(self, token):
        url = token if str(token).startswith("http") else self.host + str(token)
        _, page = self.fetch(url)
        m = re.search(r'const playSource\s*=\s*\{[^}]*?src:\s*"([^"]+)"', page, re.S)
        if not m:
            return ""
        return m.group(1).replace("\\/", "/")


# ================== 合并层：多源线路（河豚 / 可可 / 采集站） ==================

def _mx_base(name):
    """去掉季/部标记后的剧名主干，用于「同系列」判断。"""
    t = _precise_norm(name)
    t = re.sub(r"第[0-9一二三四五六七八九十百两]+[季部篇]", "", t)
    return t


class _MergeMixin(object):
    """附加能力：河豚、可可直接取流，采集站回退，相关短剧与缓存。"""

    # ---------- 客户端 ----------
    def _mx_ht(self):
        c = getattr(self, "_mx_ht_client", None)
        if c is None:
            c = self._mx_ht_client = _HeTun()
        return c

    def _mx_kk(self):
        c = getattr(self, "_mx_kk_client", None)
        if c is None:
            c = self._mx_kk_client = _KK()
        return c

    # ---------- 河豚 ----------
    def _mx_ht_lines(self, title, refresh=False):
        cache = getattr(self, "_mx_ht_cache", None)
        if cache is None:
            cache = self._mx_ht_cache = {}
        miss = getattr(self, "_mx_ht_miss", None)
        if miss is None:
            miss = self._mx_ht_miss = {}
        key = text(title)
        if not refresh and key in cache:
            return cache[key]
        if not refresh and key in miss and time.time() - miss[key] < 3600:
            return []
        out = []
        try:
            ht = self._mx_ht()
            if ht.ready():
                want = _backup_norm(key)
                pick = None
                for cand in (ht.search(key) or []):
                    if _backup_norm(cand.get("vod_name")) == want:
                        pick = cand
                        break
                if not pick:
                    sid = ht.scan_name(want)
                    if sid:
                        pick = {"vod_id": sid}
                if pick and pick.get("vod_id"):
                    out = [("河豚·" + n, u) for n, u in ht.detail_lines(pick["vod_id"])]
        except Exception:
            out = []
        if out:
            if len(cache) >= 64:
                cache.pop(next(iter(cache)))
            cache[key] = out
            miss.pop(key, None)
        else:
            miss[key] = time.time()
        return out

    def _mx_ht_line(self, token):
        """播放壳给的河豚集 token：base64 参数或直链。"""
        got = self._mx_ht().play(token)
        if not got.get("url"):
            return None
        return {"parse": 0, "jx": 0, "url": got["url"], "header": got.get("header") or {}}

    def _mx_ht_by_title(self, title, index=1):
        lines = self._mx_ht_lines(title)
        if not lines:
            ts = getattr(self, "_mx_ht_ts", None)
            if ts is None:
                ts = self._mx_ht_ts = {}
            k = text(title)
            if time.time() - ts.get(k, 0) > 600:
                ts[k] = time.time()
                lines = self._mx_ht_lines(title, refresh=True)
        if not lines:
            return None
        idx = int(index or 1)
        # 逐條線路試：H 檔若拿不到地址就換 P/B 檔，避免選到死線
        for _n, u in lines:
            eps = u.split("#")
            blob = eps[idx - 1] if 0 < idx <= len(eps) else eps[-1]
            got = self._mx_ht_line(blob.split("$")[-1])
            if got:
                return got
        return None

    # ---------- 可可 ----------
    def _mx_kk_lines(self, title):
        cache = getattr(self, "_mx_kk_cache", None)
        if cache is None:
            cache = self._mx_kk_cache = {}
        key = text(title)
        if key in cache:
            return cache[key]
        out = []
        try:
            kk = self._mx_kk()
            want = _precise_norm(key)
            cands = kk.search(key) or []
            if not cands:
                kk._token, kk._token_at = "", 0.0
                cands = kk.search(key) or []
            for cand in cands:
                if cand.get("type") not in ("短剧", "动漫"):
                    continue
                if _precise_norm(cand.get("name")) != want:
                    continue
                eps = kk.detail(cand["url"])
                if not eps:
                    continue
                out = [("可可·" + cand["type"], "#".join(eps))]
                break
        except Exception:
            out = []
        if out:
            if len(cache) >= 64:
                cache.pop(next(iter(cache)))
            cache[key] = out
        else:
            cache.pop(key, None)
        return out

    @staticmethod
    def _mx_sim(a, b):
        def grams(x):
            t = _precise_norm(x)
            return {t[i:i + 2] for i in range(max(0, len(t) - 1))}
        ga, gb = grams(a), grams(b)
        if not ga or not gb:
            return 0.0
        return 2.0 * len(ga & gb) / (len(ga) + len(gb))

    def _mx_kk_near(self, title, threshold=0.78):
        """一条镜像都没有时的近似兜底，命中会在线路名里标「近似」。"""
        cache = getattr(self, "_mx_kk_near_cache", None)
        if cache is None:
            cache = self._mx_kk_near_cache = {}
        key = text(title)
        if key in cache:
            return cache[key]
        out = []
        try:
            kk = self._mx_kk()
            queries = [key]
            for seg in re.split(r"[，,：:。！？!?]", key):
                seg = seg.strip()
                if len(seg) >= 5 and seg not in queries:
                    queries.append(seg)
            best = None
            for q in queries[:3]:
                for cand in (kk.search(q) or []):
                    if cand.get("type") not in ("短剧", "动漫"):
                        continue
                    sim = self._mx_sim(key, cand.get("name"))
                    if sim < threshold:
                        continue
                    if best is None or sim > best[0]:
                        best = (sim, cand)
            if best:
                cand = best[1]
                eps = kk.detail(cand["url"])
                if eps:
                    out = [("可可·%s(近似)" % cand["type"], "#".join(eps))]
        except Exception:
            out = []
        if len(cache) >= 64:
            cache.pop(next(iter(cache)))
        cache[key] = out
        return out

    def _mx_kk_line(self, token):
        cache = getattr(self, "_mx_kk_play_cache", None)
        if cache is None:
            cache = self._mx_kk_play_cache = {}
        key = text(token)
        hit = cache.get(key)
        head = {"User-Agent": _KK_UA, "Referer": _KK_HOST + "/"}
        if hit and time.time() - hit[1] < 300:
            return {"parse": 0, "jx": 0, "url": hit[0], "header": head}
        url = self._mx_kk().play(token)
        if not url:
            return None
        if len(cache) >= 256:
            cache.pop(next(iter(cache)))
        cache[key] = (url, time.time())
        return {"parse": 0, "jx": 0, "url": url, "header": head}

    def _mx_kk_by_title(self, title, index=1):
        lines = self._mx_kk_lines(title) or self._mx_kk_near(title)
        if not lines:
            return None
        eps = lines[0][1].split("#")
        if not eps:
            return None
        i = int(index or 1)
        tok = eps[i - 1].split("$")[-1] if 0 < i <= len(eps) else eps[-1].split("$")[-1]
        return self._mx_kk_line(tok)

    # ---------- 采集站 ----------
    def _mx_backup_series(self, title):
        cache = getattr(self, "_mx_backup_series_cache", None)
        if cache is None:
            cache = self._mx_backup_series_cache = {}
        miss = getattr(self, "_mx_backup_miss", None)
        if miss is None:
            miss = self._mx_backup_miss = {}
        key = text(title)
        if key in cache:
            return cache[key]
        if key in miss and time.time() - miss[key] < 3600:
            return None
        hit = backup_series(_MX_NET, key)
        if hit:
            if len(cache) >= 64:
                cache.pop(next(iter(cache)))
            cache[key] = hit
            miss.pop(key, None)
        else:
            miss[key] = time.time()
        return hit

    def _mx_backup_play(self, title, index=1):
        cache = getattr(self, "_mx_backup_cache", None)
        if cache is None:
            cache = self._mx_backup_cache = {}
        key = (text(title), int(index or 1))
        if key in cache:
            return cache[key]
        series = self._mx_backup_series(title)
        if not series:
            return None
        eps = series["eps"]
        i = int(index or 1)
        raw = eps[i - 1] if 0 < i <= len(eps) else eps[-1]
        url = _backup_resolve(_MX_NET, raw)
        hit = {"parse": 0, "jx": 0, "url": url,
               "header": {"User-Agent": _KK_UA}}
        if len(cache) >= 256:
            cache.pop(next(iter(cache)))
        cache[key] = hit
        return hit

    # ---------- 手动覆盖 ----------
    def _mx_override_play(self, vid):
        table = getattr(self, "_mx_override", None) or {}
        if not table:
            return None
        ent = (getattr(self, "_mx_vid_index", {}) or {}).get(vid) or {}
        title = text(ent.get("name"))
        if not title:
            return None
        index = int(ent.get("index") or 1)
        val = table.get(title)
        if val is None:
            want = _backup_norm(title)
            for k, v in table.items():
                if _backup_norm(k) == want:
                    val = v
                    break
        if not val:
            return None
        if isinstance(val, list):
            url = text(val[min(index, len(val)) - 1]) if val else ""
        elif isinstance(val, dict):
            url = text(val.get(str(index)) or val.get("*") or "")
        else:
            url = text(val)
        if not re.match(r"^https?://", url, re.I):
            return None
        headers = {"User-Agent": _KK_UA}
        if "bdstatic" in url or "baidu" in url:
            headers["Referer"] = "https://haokan.baidu.com/"
        return {"parse": 0, "jx": 0, "url": url, "header": headers}

    # ---------- 线路组装 ----------
    def _mx_extra_lines(self, title):
        out = list(self._mx_ht_lines(title))
        kk = self._mx_kk_lines(title)
        if not kk:
            kk = self._mx_kk_near(title)
        return out + kk

    # ---------- 相关短剧 ----------
    def _mx_rel_content(self, tid, pg):
        parts = str(tid).split("/")
        try:
            name = urllib.parse.unquote("/".join(parts[2:]))
        except Exception:
            name = "/".join(parts[2:])
        sid = parts[1] if len(parts) > 1 else ""
        try:
            page = max(1, int(pg))
        except (TypeError, ValueError):
            page = 1
        res = {"list": [], "page": page, "pagecount": 1, "limit": 1, "total": 0}
        if not name:
            res["msg"] = "暫無相關短劇"
            return res
        try:
            data = self.searchContent(name, False, "1")
        except Exception as e:
            res["msg"] = "相關短劇搜尋失敗：%s" % e
            return res
        base = _mx_base(name)
        want = _precise_norm(name)
        seen = {str(sid)}
        out = []
        for v in (data.get("list") or []):
            if not isinstance(v, dict):
                continue
            vid = text(v.get("vod_id"))
            nm = text(v.get("vod_name"))
            if not vid or vid in seen or not nm:
                continue
            if _precise_norm(nm) != want and _mx_base(nm) != base:
                continue
            seen.add(vid)
            out.append(v)
        res["list"] = out
        res["limit"] = max(len(out), 1)
        if not out:
            res["msg"] = "暫無相關短劇"
        return res


# ================== 合并层：包装注入 ==================

class _MxNet(object):
    """给采集站/可可等纯 HTTP 调用提供统一的 get 接口，复用红果壳里的 UA。"""

    def http(self, url, opts=None):
        opts = opts or {}
        headers = dict(opts.get("headers") or {})
        headers.setdefault("User-Agent", _KK_UA)
        req = urllib.request.Request(url, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=opts.get("timeout", 15))
            return {"code": resp.status, "content": resp.read().decode("utf-8", "replace"),
                    "headers": dict(resp.headers)}
        except urllib.error.HTTPError as e:
            return {"code": e.code, "content": e.read().decode("utf-8", "replace"),
                    "headers": dict(e.headers or {})}
        except Exception as e:
            return {"error": str(e), "code": 0, "content": ""}


_MX_NET = _MxNet()


def _mx_install():
    for _n in dir(_MergeMixin):
        if _n.startswith("_mx_"):
            setattr(Spider, _n, getattr(_MergeMixin, _n))

    _orig_init = Spider.init

    def init(self, extend=""):
        res = _orig_init(self, extend)
        try:
            if isinstance(extend, dict):
                q = extend
            elif isinstance(extend, str) and extend.strip().startswith("{"):
                q = json.loads(extend)
            else:
                q = {}
            ov = q.get("override")
            self._mx_override = ov if isinstance(ov, dict) else {}
        except Exception:
            self._mx_override = {}
        self._mx_vid_index = getattr(self, "_mx_vid_index", {})
        return res

    Spider.init = init

    _orig_detail = Spider.detailContent

    def detailContent(self, ids):
        data = _orig_detail(self, ids)
        try:
            lst = data.get("list") or []
            if not lst:
                return data
            one = lst[0]
            title = text(one.get("vod_name"))
            sid = text(one.get("vod_id"))
            idx_map = getattr(self, "_mx_vid_index", None)
            if idx_map is None:
                idx_map = self._mx_vid_index = {}
            for grp in str(one.get("vod_play_url") or "").split("$$$"):
                for i, ep in enumerate(grp.split("#")):
                    if "$" not in ep:
                        continue
                    tok = ep.rsplit("$", 1)[-1]
                    v = tok.rsplit(":", 1)[-1] if ":" in tok else tok
                    if text(v).isdigit():
                        idx_map[text(v)] = {"name": title, "index": i + 1, "seriesId": sid}
            if title:
                extra = self._mx_extra_lines(title)
                if extra:
                    froms = [x for x in str(one.get("vod_play_from") or "").split("$$$") if x]
                    urls = str(one.get("vod_play_url") or "").split("$$$")
                    while len(urls) < len(froms):
                        urls.append("")
                    tok_meta = getattr(self, "_mx_tok_meta", None)
                    if tok_meta is None:
                        tok_meta = self._mx_tok_meta = {}
                    for name, blob in extra:
                        if name in froms:
                            continue
                        froms.append(name)
                        urls.append(blob)
                        for _i, _ep in enumerate(str(blob).split("#")):
                            if "$" in _ep:
                                tok_meta[text(_ep.rsplit("$", 1)[-1])] = (title, _i + 1)
                    one["vod_play_from"] = "$$$".join(froms)
                    one["vod_play_url"] = "$$$".join(urls)
                if sid and "[a=cr:" not in text(one.get("vod_remarks")):
                    old = text(one.get("vod_remarks"))
                    link = "[a=cr:" + json.dumps(
                        {"id": "rel/" + sid + "/" + title, "name": "相關短劇"},
                        ensure_ascii=False) + "/]相關短劇[/a]"
                    one["vod_remarks"] = (old + " " + link) if old else link
        except Exception:
            pass
        return data

    Spider.detailContent = detailContent

    _orig_play = Spider.playerContent

    def _mx_ok(out):
        url = text((out or {}).get("url"))
        return bool(url) and (".mp4" in url or ".m3u8" in url or "/hg.mp4" in url)

    def playerContent(self, flag, id, vipFlags=None):
        f = text(flag)
        vid = text(id)
        try:
            got = self._mx_override_play(vid)
        except Exception:
            got = None
        if got:
            return got
        if "河豚" in f:
            try:
                got = self._mx_ht_line(vid)
            except Exception:
                got = None
            if not got:
                meta = (getattr(self, "_mx_tok_meta", {}) or {}).get(vid)
                if meta:
                    try:
                        got = self._mx_ht_by_title(meta[0], meta[1])
                    except Exception:
                        got = None
            if got:
                return got
            return {"parse": 0, "jx": 0, "msg": "河豚取流失敗：未取到播放地址"}
        if "可可" in f:
            try:
                got = self._mx_kk_line(vid)
            except Exception:
                got = None
            if not got:
                meta = (getattr(self, "_mx_tok_meta", {}) or {}).get(vid)
                if meta:
                    try:
                        got = self._mx_kk_by_title(meta[0], meta[1])
                    except Exception:
                        got = None
            if got:
                return got
            return {"parse": 0, "jx": 0, "msg": "可可取流失敗：未取到播放地址"}
        out = None
        try:
            out = _orig_play(self, flag, id, vipFlags)
        except Exception as e:
            out = {"parse": 0, "jx": 0, "msg": str(e)}
        if _mx_ok(out):
            return out
        ent = (getattr(self, "_mx_vid_index", {}) or {}).get(vid) or {}
        title = text(ent.get("name"))
        index = ent.get("index") or 1
        if title:
            for fn in ("_mx_backup_play", "_mx_ht_by_title", "_mx_kk_by_title"):
                try:
                    alt = getattr(self, fn)(title, index)
                except Exception:
                    alt = None
                if alt and _mx_ok(alt):
                    return alt
        base_msg = text((out or {}).get("msg"))
        return {"parse": 0, "jx": 0,
                "msg": "本劇暫無可播線路：紅果取流失敗，採集站/河豚/可可均無同名或近似劇(%s)"
                       % (base_msg or "無")}

    Spider.playerContent = playerContent

    _orig_cat = Spider.categoryContent

    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        if text(tid).startswith("rel/"):
            return self._mx_rel_content(tid, pg)
        return _orig_cat(self, tid, pg, filter, extend)

    Spider.categoryContent = categoryContent


_mx_install()


# ================== apk 版分类：找剧 / 真人剧 / 漫剧 / AI剧 + 帳號 / 歷史 ==================

_MX2_CLASS_IDS = ["find-drama", "real-drama", "comic-drama", "ai-drama"]
_MX2_CLASS_NAMES = ["找剧", "真人剧", "漫剧", "AI剧"]
_MX2_SCENES = ["default", "short_play", "comic_series", "ai_series"]
# 推荐流 tab（与 apk 版一致）：ai-drama 无对应 tab，仍走 landpage
_MX2_FEED_TABS = {"find-drama": 8, "real-drama": 38, "comic-drama": 32}
_MX2_PAGE = 18
_MX2_HISTORY_PAGE = 20
_MX2_API = "https://api5-normal-sinfonlinea.fqnovel.com"
_MX2_PANELS_RAW = _PANEL_SNAPSHOT = [["genre|全部体裁|short_play:真人剧,comic_series:漫剧,ai_series:AI剧","category_dim_theme|全部主题|cate_1021:现言,cate_1048:女性成长,cate_262:脑洞,cate_1020:奇幻,cate_1019:玄幻,cate_439:古言,cate_1038:战神,cate_246:宫斗,cate_1013:仙侠,cate_1047:权谋,cate_1180:种田,cate_1022:年代爱情,cate_303:喜剧,cate_165:悬疑,cate_297:青春,cate_1027:志怪,cate_1025:民国爱情,cate_751:灵异,cate_1235:家国情怀,cate_1136:法律,cate_1148:刑侦,cate_504:抗战,cate_1172:武侠,cate_1240:民国传奇,cate_302:动作,cate_1168:求生,cate_1092:科幻,cate_1219:恐怖,cate_1225:商战","category_dim_role|全部设定|cate_1051:打脸虐渣,cate_1207:大男主,cate_760:大女主,cate_266:马甲,cate_36:重生,cate_37:穿越,cate_19:系统,cate_265:先婚后爱,cate_862:家长里短,cate_1010:小人物,cate_475:破镜重圆,cate_20:神豪,cate_936:豪门,cate_1045:强者回归,cate_598:异能,cate_1007:传承觉醒,cate_1008:虐恋,cate_487:医生,cate_1049:强强联合,cate_1044:赘婿逆袭,cate_96:甜宠,cate_43:娱乐圈,cate_26:神医,cate_387:青梅竹马,cate_762:姐弟恋,cate_929:玄学,cate_616:追妻火葬场,cate_1293:业界精英,cate_477:一见钟情,cate_1291:福宝,cate_1287:捞偏门,cate_1042:反派主角,cate_428:萌宠,cate_1255:方言,cate_1200:双向救赎,cate_615:白月光,cate_831:灵魂互换,cate_380:病娇,cate_1191:暴富,cate_826:黑道,cate_582:丧尸,cate_375:特种兵","category_dim_epoch|全部背景|cate_757:现代,cate_1:都市,cate_11:乡村,cate_758:古代,cate_79:年代,cate_452:架空,cate_127:职场,cate_390:民国,cate_4:校园,cate_1153:宫廷,cate_1162:荒岛","sort|全部推荐|online_time:最新上架,hot_score:最高热度,hot_collect:最高收藏","gender|全部受众|1:男频,0:女频","online_time|全部时间|days_7:7天内上新,days_14:14天内上新,days_30:30天内上新,days_90:90天内上新"],["genre|全部体裁|short_play:真人剧,comic_series:漫剧,ai_series:AI剧","category_dim_theme|全部主题|cate_1051:打脸虐渣,cate_739:逆袭,cate_266:马甲,cate_1048:女性成长,cate_261:都市日常,cate_36:重生,cate_37:穿越,cate_19:系统,cate_1024:家庭伦理,cate_1040:亲情,cate_1041:奇幻脑洞,cate_1020:奇幻爱情,cate_466:闪婚,cate_1050:暗恋成真,cate_439:古风言情,cate_382:穿书,cate_475:破镜重圆,cate_1038:战神归来,cate_842:追妻,cate_3:现代言情,cate_1053:豪门恩怨,cate_598:异能,cate_1007:传承觉醒,cate_1013:玄幻仙侠,cate_1008:虐恋,cate_316:剧情,cate_1047:古风权谋,cate_1022:年代爱情,cate_1044:赘婿逆袭,cate_43:娱乐圈,cate_303:喜剧,cate_1043:无敌神医,cate_165:悬疑推理,cate_395:现言甜宠","category_dim_role|全部设定|cate_760:大女主,cate_28:萌宝,cate_1010:小人物,cate_20:神豪,cate_1045:强者回归,cate_844:真假千金,cate_1052:欢喜冤家,cate_1049:强强联合,cate_1046:天下无敌,cate_387:青梅竹马,cate_85:王妃,cate_378:女帝,cate_901:龙王,cate_84:皇后,cate_470:替身,cate_737:大叔,cate_94:团宠","category_dim_epoch|全部背景|cate_11:乡村,cate_127:职场,cate_390:民国,cate_4:校园,cate_273:历史古代,cate_308:古装","sort|全部推荐|online_time:最新上架,hot_score:最高热度,hot_collect:最高收藏","gender|全部受众|1:男频,0:女频","online_time|全部时间|days_7:7天内上新,days_14:14天内上新,days_30:30天内上新,days_90:90天内上新"],["genre|全部体裁|short_play:真人剧,comic_series:漫剧,ai_series:AI剧","category_dim_art_style|全部画风|cate_5415:3D,cate_5416:2D,cate_5417:表情包","category_dim_theme|全部主题|cate_316:剧情,cate_6:奇幻,cate_7:玄幻,cate_68:末世,cate_755:脑洞,cate_936:豪门,cate_1092:科幻,cate_1182:冒险","category_dim_role|全部设定|cate_739:逆袭,cate_756:反转,cate_37:穿越,cate_36:重生,cate_29:总裁,cate_19:系统,cate_43:娱乐圈,cate_598:异能","category_dim_epoch|全部背景|cate_11:乡村,cate_79:年代,cate_4:校园,cate_390:民国,cate_1:都市,cate_127:职场,cate_452:架空,cate_599:异界,cate_758:古代","sort|全部推荐|online_time:最新上架,hot_score:最高热度,hot_collect:最高收藏","gender|全部受众|1:男频,0:女频","creation_status|全部状态|creation_status_0:已完结,creation_status_1:连载中","online_time|全部时间|days_7:7天内上新,days_14:14天内上新,days_30:30天内上新,days_90:90天内上新"],["genre|全部体裁|short_play:真人剧,comic_series:漫剧,ai_series:AI剧","category_dim_theme|全部主题|cate_316:剧情,cate_6:奇幻,cate_7:玄幻,cate_68:末世,cate_755:脑洞,cate_936:豪门,cate_1092:科幻,cate_1182:冒险","category_dim_role|全部设定|cate_739:逆袭,cate_756:反转,cate_37:穿越,cate_36:重生,cate_29:总裁,cate_19:系统,cate_43:娱乐圈,cate_598:异能","category_dim_epoch|全部背景|cate_11:乡村,cate_79:年代,cate_4:校园,cate_390:民国,cate_1:都市,cate_127:职场,cate_452:架空,cate_599:异界,cate_758:古代","sort|全部推荐|online_time:最新上架,hot_score:最高热度,hot_collect:最高收藏","gender|全部受众|1:男频,0:女频","online_time|全部时间|days_7:7天内上新,days_14:14天内上新,days_30:30天内上新,days_90:90天内上新"]]


def _mx2_snapshot(rows):
    out = []
    for row in rows:
        P = row.split("|")
        x = P[1] if len(P) > 1 else ""
        name = x[2:] if x.startswith("全部") and len(x) > 2 else x
        value = [{"n": "全部", "v": ""}]
        for item in "|".join(P[2:]).split(","):
            c = item.find(":")
            if c > 0:
                value.append({"v": item[:c], "n": item[c + 1:]})
        out.append({"key": P[0], "name": name, "value": value})
    return out


_MX2_PANELS = [_mx2_snapshot(row) for row in _MX2_PANELS_RAW]


def _mx2_common(device_id, install_id):
    """与 apk 版公共参数保持一致，键顺序影响签名。"""
    return {
        "iid": str(install_id), "device_id": str(device_id), "ac": "wifi",
        "channel": "update_64", "aid": "8662", "app_name": "novelread",
        "version_code": "73732", "version_name": "7.3.7.32",
        "device_platform": "android", "os": "android", "ssmix": "a",
        "device_type": "25053RT47C", "device_brand": "Redmi", "language": "zh",
        "os_api": "36", "os_version": "16", "manifest_version_code": "73732",
        "resolution": "1280*2772", "dpi": "520", "update_version_code": "73732",
        "host_abi": "arm64-v8a", "dragon_device_type": "phone", "pv_player": "73732",
    }


def _mx2_num(v):
    try:
        return int(v)
    except Exception:
        return 0


class _Mx2Mixin(object):
    """apk 版分类引擎：面板来自静态快照，内容走 landpage / 推荐流。"""

    # ---------- 请求 ----------
    def _mx2_sig(self, path, params, payload=""):
        dev = _device_config({"device_id": self.device_id, "install_id": self.install_id})
        full = _mx2_common(self.device_id, self.install_id)
        full.update(params or {})
        hdr = {"Content-Type": "application/json; charset=UTF-8",
               "Accept": "application/json"}
        ck = text(getattr(self, "_mx2_cookie", ""))
        if ck:
            hdr["Cookie"] = ck
        tk = text(getattr(self, "_mx2_token", ""))
        if tk:
            hdr["X-Tt-Token"] = tk
        return _core_sixgod(_MX2_API + path, full, dev, payload, hdr)

    @staticmethod
    def _mx2_data(resp):
        """解 {code, data} 外壳；code 非 0 直接抛出，便于上层显示真实原因。"""
        if not isinstance(resp, dict):
            return {}
        code = resp.get("code")
        if code is not None and _mx2_num(code) != 0:
            raise RuntimeError("接口 code=%s %s" % (code, text(resp.get("message")) or ""))
        d = resp.get("data")
        if isinstance(d, dict):
            return d
        return resp if code is None else {}

    def _mx2_call(self, path, params, payload=None):
        headers, url = self._mx2_sig(path, params, payload if payload is not None else "")
        if payload is None:
            r = requests.get(url, headers=headers, timeout=20)
        else:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            r = requests.post(url, headers=headers, data=body, timeout=20)
        return r.json()

    # ---------- 卡片转换 ----------
    def _mx2_img(self, u):
        return text(u)

    def _mx2_vod_from_series(self, J):
        if not isinstance(J, dict):
            return None
        sid = text(J.get("series_id"))
        if not re.match(r"^\d+$", sid):
            return None
        cnt = text(J.get("episode_cnt"))
        full = ("全" + cnt + "集") if cnt and cnt != "0" else ""
        right = text(J.get("episode_right_text"))
        remarks, year = right, ""
        if right and "集" not in right:
            year, remarks = right, full
        elif not right:
            remarks = full
        out = {"vod_id": sid,
               "vod_name": text(J.get("series_name") or J.get("series_title")) or "紅果短劇",
               "vod_pic": self._mx2_img(J.get("series_cover")),
               "vod_remarks": remarks,
               "style": {"type": "rect", "ratio": 0.75}}
        if year:
            out["vod_year"] = year
        return out

    def _mx2_vod_from_card(self, h):
        if not isinstance(h, dict):
            return None
        sid = text(h.get("series_id"))
        if not re.match(r"^\d+$", sid):
            return None
        subs = " · ".join(text(t.get("content")) for t in (h.get("sub_title_list") or [])
                          if isinstance(t, dict) and text(t.get("content")))
        cnt = h.get("episode_cnt")
        full = ("全" + str(cnt) + "集") if cnt and str(cnt) != "0" else ""
        out = {"vod_id": sid, "vod_name": text(h.get("title")) or "紅果短劇",
               "vod_pic": self._mx2_img(h.get("cover")),
               "vod_remarks": full or subs,
               "style": {"type": "rect", "ratio": 0.75}}
        if subs and full:
            out["vod_year"] = subs
        return out

    @staticmethod
    def _mx2_series_ref(h):
        if not isinstance(h, dict):
            return None
        return {"series_id": h.get("series_id"), "series_name": h.get("title"),
                "series_cover": h.get("cover"), "episode_cnt": h.get("episode_cnt"),
                "episode_right_text": h.get("rec_text")}

    def _mx2_cells(self, cells):
        out = []
        for cell in (cells or []):
            if not isinstance(cell, dict):
                continue
            vd = cell.get("video_data")
            if isinstance(vd, list) and vd:
                it = self._mx2_vod_from_series(self._mx2_series_ref(vd[0]))
                if it:
                    out.append(it)
        return out

    # ---------- 菜单 ----------
    def _mx2_menu(self):
        classes = [{"type_id": "account", "type_name": "帳號"},
                   {"type_id": "history", "type_name": "歷史"},
                   {"type_id": "find-drama", "type_name": "找剧"}]
        classes += [{"type_id": n, "type_name": _MX2_CLASS_NAMES[i + 1]}
                    for i, n in enumerate(_MX2_CLASS_IDS[1:])]
        filters = {}
        for i, tid in enumerate(_MX2_CLASS_IDS):
            filters[tid] = [{"key": w["key"], "name": w["name"], "init": "",
                             "value": w["value"]}
                            for w in _MX2_PANELS[i]
                            if i == 0 or w["key"] != "genre"]
        for c in classes:
            if c["type_id"] in filters:
                c["filters"] = filters[c["type_id"]]
        return classes, filters

    # ---------- 分类内容 ----------
    def _mx2_filters_of(self, idx, ext):
        ext = ext if isinstance(ext, dict) else {}
        scene = _MX2_SCENES[idx]
        filtered = {}
        picked = False
        for w in _MX2_PANELS[idx]:
            val = text(ext.get(w["key"]))
            if w["key"] == "genre" and idx > 0:
                filtered[w["key"]] = [scene]
            elif val and any(v["v"] == val for v in w["value"]):
                filtered[w["key"]] = [val]
                picked = True
                if w["key"] == "genre":
                    scene = val
            else:
                filtered[w["key"]] = []
        return scene, filtered, picked

    def _mx2_landpage(self, scene, filtered, offset, session):
        resp = self._mx2_call("/reading/distribution/category/landpage/v1/", {},
                              {"filter_ids": "", "req_scene": scene, "offset": offset,
                               "need_selector_panel": False, "limit": 18,
                               "select_items": filtered, "session_id": session or "",
                               "req_type": "only_content",
                               "client_req_type": 3 if offset == 0 else 2})
        if isinstance(resp, dict) and isinstance(resp.get("data"), dict):
            return resp["data"]
        return resp if isinstance(resp, dict) else {}

    def _mx2_category(self, tid, pg, ext):
        page = max(1, int(pg or 1)) if str(pg or "1").isdigit() else 1
        if tid == "account":
            return self._mx2_account(page)
        if tid == "history":
            return self._mx2_history(page)
        idx = _MX2_CLASS_IDS.index(tid) if tid in _MX2_CLASS_IDS else 0
        scene, filtered, picked = self._mx2_filters_of(idx, ext)
        tab = _MX2_FEED_TABS.get(tid)
        if tab is not None and not picked:
            # 未選篩選時走官方推薦流，和 apk 版行為一致；失敗再退回 landpage
            try:
                return self._mx2_feed_page(tab, page)
            except Exception:
                pass
        key = scene + "|" + json.dumps(filtered, ensure_ascii=False, sort_keys=True)
        state = getattr(self, "_mx2_state", None)
        if state is None:
            state = self._mx2_state = {}
        st = state.get(key)
        if not st or page == 1:
            st = {"pages": {1: {"offset": 0, "session": ""}}, "end": 0}
            if len(state) >= 8:
                state.pop(next(iter(state)))
            state[key] = st
        out = []
        bc = 1
        while bc <= page:
            if st.get("end") and page > st["end"]:
                return {"list": [], "page": page, "pagecount": st["end"], "limit": 18, "total": 0}
            bs = st["pages"].get(bc)
            if bs is None:
                return {"list": [], "page": page, "pagecount": page, "limit": 18, "total": 0,
                        "msg": _MX2_CLASS_NAMES[idx] + "載入失敗"}
            data = self._mx2_landpage(scene, filtered, bs["offset"], bs["session"])
            part = [self._mx2_vod_from_card(v) for v in (data.get("video_data") or [])]
            part = [x for x in part if x]
            nxt = _mx2_num(data.get("next_offset"))
            more = (data.get("has_more") is True or data.get("has_more") == 1) and part \
                and nxt > bs["offset"]
            sess = text(data.get("session_id")) or bs["session"]
            if more:
                st["pages"][bc + 1] = {"offset": nxt, "session": sess}
            else:
                st["end"] = bc
            out = part
            bc += 1
        return {"list": out, "page": page, "pagecount": page + 1 if not st.get("end") else page,
                "limit": max(len(out), 1), "total": 0}


    # ---------- 帳號與歷史 ----------
    def _mx2_logged(self):
        return bool(text(getattr(self, "_mx2_cookie", ""))
                    or text(getattr(self, "_mx2_token", "")))

    def _mx2_account(self, page):
        ck = text(getattr(self, "_mx2_cookie", ""))
        logged = self._mx2_logged()
        if logged:
            names = [t.split("=")[0].strip() for t in ck.split(";") if t.strip()]
            who = "已載入 %d 項登入憑證" % len(names) if ck else "已載入登入 token"
        else:
            who = "目前使用訪客身分"
        rows = [
            ("login", "簡訊登入", "外掛不支援圖形驗證碼，請改用匯入 Cookie"),
            ("status", "登入狀態", who),
            ("import", "匯入 Cookie", '在 ext 填 {"cookie": "sessionid=..."} 後重新載入'),
            ("logout", "登出", "清除本次載入的登入資訊"),
        ]
        lst = [] if page > 1 else [{
            "vod_id": "account/" + a, "vod_name": b, "vod_remarks": c,
            "action": a, "style": {"type": "list"},
        } for a, b, c in rows]
        return {"list": lst, "page": page, "pagecount": 1, "limit": len(lst), "total": 4}

    def _mx2_history(self, page):
        if not self._mx2_logged():
            lst = [{
                "vod_id": "account/import", "vod_name": "登入後查看觀看歷史",
                "vod_remarks": "在 ext 設定 cookie 後重新載入", "action": "import",
                "style": {"type": "rect", "ratio": 0.75},
            }] if page == 1 else []
            return {"list": lst, "page": page, "pagecount": 1, "limit": max(len(lst), 1),
                    "total": len(lst), "msg": "未登入，暫無觀看歷史"}
        try:
            data = self._mx2_data(self._mx2_call(
                "/reading/bookapi/read_history/list/v1/",
                {"book_type": 2, "offset": (page - 1) * _MX2_HISTORY_PAGE,
                 "limit": _MX2_HISTORY_PAGE, "full_field": "true",
                 "is_first_load": "true" if page == 1 else "false"}))
        except Exception as e:
            return {"list": [], "page": page, "pagecount": page, "limit": _MX2_HISTORY_PAGE,
                    "total": 0, "msg": str(e)}
        lst = []
        for b4 in (data.get("data_list") or []):
            if not isinstance(b4, dict):
                continue
            b5 = b4.get("video_data") if isinstance(b4.get("video_data"), dict) else {}
            bid = text(b4.get("book_id_str") or b4.get("book_id") or b5.get("series_id"))
            if not re.match(r"^\d+$", bid):
                continue
            cnt = text(b4.get("episode_cnt") or b5.get("episode_cnt"))
            idx = _mx2_num(b4.get("vid_index"))
            remarks = ("看到第" + str(idx) + "集") if idx > 0 else (
                ("全" + cnt + "集") if cnt and cnt != "0" else "")
            subs = " · ".join(text(x.get("content") if isinstance(x, dict) else x)
                              for x in (b4.get("sub_title_list") or []))
            subs = " · ".join([p for p in subs.split(" · ") if p])
            item = {
                "vod_id": bid,
                "vod_name": text(b4.get("book_name") or b5.get("title")
                                 or b5.get("series_name")) or "紅果短劇",
                "vod_pic": text(b4.get("thumb_url") or b5.get("cover")
                                or b5.get("series_cover") or ""),
                "vod_remarks": remarks,
                "style": {"type": "rect", "ratio": 0.75},
            }
            if subs:
                item["vod_year"] = subs
            lst.append(item)
        more = data.get("has_more") is True or _mx2_num(data.get("has_more")) == 1
        out = {"list": lst, "page": page,
               "pagecount": page + 1 if (more and lst) else page,
               "limit": max(len(lst), 1), "total": 0}
        if page == 1 and not lst:
            out["msg"] = "暫無觀看歷史"
        return out

    # ---------- 推荐流（bookmall tab） ----------
    def _mx2_feed_first(self, tab):
        data = self._mx2_data(self._mx2_call(
            "/reading/bookapi/bookmall/tab/v2/", {"tab_type": tab, "client_req_type": 1}))
        tab_item = None
        for Y in (data.get("tab_item") or []):
            if isinstance(Y, dict) and _mx2_num(Y.get("tab_type")) == tab:
                tab_item = Y
                break
        cell = None
        for Y in ((tab_item or {}).get("cell_data") or []):
            if not isinstance(Y, dict):
                continue
            inner = Y.get("cell_data")
            if isinstance(inner, list) and any(
                    isinstance(n, dict) and isinstance(n.get("video_data"), list)
                    and n.get("video_data") for n in inner):
                cell = Y
                break
        if not cell:
            raise RuntimeError("推薦流為空")
        feed = {
            "base": {
                "cell_id": text(cell.get("cell_id_str") or cell.get("cell_id")),
                "tab_type": tab,
                "session_id": text((tab_item or {}).get("session_id")),
                "client_template": text((tab_item or {}).get("client_template")),
                "tab_version": text((tab_item or {}).get("tab_version")),
                "version_tag": text((tab_item or {}).get("version_tag")),
                "show_type": text(cell.get("show_type")),
            },
            "offsets": {},
        }
        return {"feed": feed, "list": self._mx2_cells(cell.get("cell_data")),
                "next": _mx2_num(cell.get("next_offset")), "more": True}

    def _mx2_feed_more(self, feed, offset):
        params = dict(feed["base"])
        params["offset"] = offset
        params["client_req_type"] = 2
        data = self._mx2_data(self._mx2_call(
            "/reading/bookapi/bookmall/cell/change/v1/", params))
        if text(data.get("session_id")):
            feed["base"]["session_id"] = text(data.get("session_id"))
        view = data.get("cell_view") if isinstance(data.get("cell_view"), dict) else {}
        cells = view.get("cell_data") if isinstance(view.get("cell_data"), list) \
            else data.get("cell_data")
        return {"list": self._mx2_cells(cells),
                "next": _mx2_num(data.get("next_offset")),
                "more": data.get("has_more") is True or _mx2_num(data.get("has_more")) == 1}

    def _mx2_feed_page(self, tab, page):
        st = getattr(self, "_mx2_feed_state", None)
        if st is None:
            st = self._mx2_feed_state = {}
        if page == 1:
            first = self._mx2_feed_first(tab)
            feed = first["feed"]
        else:
            feed = st.get(tab)
            if not isinstance(feed, dict):
                raise RuntimeError("推薦流需從第一頁開始")
            off = feed.get("offsets", {}).get(page)
            if off is None:
                raise RuntimeError("推薦流需從第一頁開始")
            first = self._mx2_feed_more(feed, off)
        st[tab] = feed
        items = list(first["list"])
        nxt = first["next"]
        more = bool(first.get("more", True) and items) and nxt > 0
        rounds = 0
        # 官方推薦流每塊只給 6 條（偶見 5 條），按每頁 18 條拼滿
        while more and len(items) < _MX2_PAGE and rounds < 8:
            chunk = self._mx2_feed_more(feed, nxt)
            rounds += 1
            items.extend(chunk["list"])
            more = bool(chunk["more"] and chunk["list"]) and chunk["next"] > 0
            nxt = chunk["next"]
        offsets = feed.setdefault("offsets", {})
        if more:
            offsets[page + 1] = nxt
        else:
            offsets.pop(page + 1, None)
        return {"list": items, "page": page, "pagecount": page + 1 if more else page,
                "limit": max(len(items), 1), "total": 0}


def _mx2_install():
    # 用 __dict__ 取原值：staticmethod 被 getattr 取出会退化成普通函数，
    # 挂到实例上就会被当成绑定方法，签名整体错位。
    for _n, _v in list(vars(_Mx2Mixin).items()):
        if _n.startswith("_mx2_"):
            setattr(Spider, _n, _v)

    _orig_init2 = Spider.init

    def init(self, extend=""):
        res = _orig_init2(self, extend)
        ck = tk = ""
        try:
            if isinstance(extend, dict):
                q = extend
            elif isinstance(extend, str) and extend.strip().startswith("{"):
                q = json.loads(extend)
            else:
                q = {}
            ck = text(q.get("cookie") or q.get("sessionid") or q.get("session_id"))
            tk = text(q.get("token") or q.get("x_tt_token"))
            ck = re.sub(r"^cookie\s*:\s*", "", ck, flags=re.I)
            ck = ck.replace("\r", " ").replace("\n", " ").strip()
            if ck and "=" not in ck:
                ck = "sessionid=" + ck
        except Exception:
            ck = tk = ""
        self._mx2_cookie = ck
        self._mx2_token = tk
        self._mx2_feed_state = {}
        self._mx2_state = {}
        return res

    Spider.init = init

    _orig_detail2 = Spider.detailContent

    def detailContent(self, ids):
        t = text(ids[0] if isinstance(ids, (list, tuple)) else ids)
        if t.startswith("account/") or t in ("account", "history"):
            logged = bool(text(getattr(self, "_mx2_cookie", ""))
                          or text(getattr(self, "_mx2_token", "")))
            body = ("當前狀態：%s\n\n" % ("已登入（已載入 cookie / token）"
                                          if logged else "訪客（未登入）")
                    + "外掛無法顯示圖形登入框與簡訊驗證碼，登入資訊請寫在源設定的 ext 裡：\n"
                    + '{\n  "cookie": "sessionid=你的值; uid_tt=...; sid_tt=..."\n}\n\n'
                    + "設定後重新載入源：\n"
                    + "· 「歷史」會列出觀看記錄與看到第幾集\n"
                    + "· 播放時會回報觀看進度到官方帳號\n"
                    + "· 「登出」即清除本次載入的登入資訊")
            title = "歷史" if ("history" in t) else "帳號"
            return {"list": [{"vod_id": t, "vod_name": title, "vod_pic": "",
                              "vod_content": body, "vod_play_from": "",
                              "vod_play_url": ""}]}
        return _orig_detail2(self, ids)

    Spider.detailContent = detailContent

    _orig_action = getattr(Spider, "action", None)

    def action(self, action):
        act = text(action)
        if act in ("login", "import", "status"):
            return {"msg": "外掛不支援圖形登入，請在 ext 設定 cookie / token"}
        if act == "logout":
            self._mx2_cookie = ""
            self._mx2_token = ""
            self._mx2_feed_state = {}
            self._mx2_state = {}
            return {"msg": "已登出"}
        if _orig_action:
            try:
                return _orig_action(self, action)
            except Exception:
                pass
        return {"msg": "無效的操作"}

    Spider.action = action

    _orig_home = Spider.homeContent

    def homeContent(self, filter=False):
        data = {}
        try:
            data = _orig_home(self, filter) or {}
        except Exception:
            data = {}
        try:
            classes, filters = self._mx2_menu()
            data["class"] = classes
            data["filters"] = filters
        except Exception:
            pass
        return data

    Spider.homeContent = homeContent

    _orig_cat2 = Spider.categoryContent

    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        t = text(tid)
        if t in _MX2_CLASS_IDS or t in ("account", "history"):
            try:
                return self._mx2_category(t, pg, extend)
            except Exception as e:
                return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0,
                        "msg": str(e)}
        return _orig_cat2(self, tid, pg, filter, extend)

    Spider.categoryContent = categoryContent


_mx2_install()
