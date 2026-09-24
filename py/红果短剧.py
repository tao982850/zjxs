# -*- coding: utf-8 -*-
from __future__ import annotations
import base64
import binascii
import bisect
import hashlib
import json
import os
import lzma
import random
import re
import struct
import tempfile
import concurrent.futures
import threading
import time
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse
import requests
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
from base.spider import Spider

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

# 官网搜索 SSR 固定约 10 条且几乎不认 page；用多关键词轮换实现“翻页”
_AI_MANJU_KEYWORDS = [
    "AI漫剧", "AI动画", "AI短剧", "AI动漫", "漫剧AI", "二次元AI", "AI漫画", "动画短剧",
]


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


def _hg_cache_clear_all() -> None:
    try:
        root = _hg_cache_dir()
        for name in os.listdir(root):
            fp = os.path.join(root, name)
            try:
                if os.path.isfile(fp):
                    os.remove(fp)
            except Exception:
                pass
    except Exception:
        pass


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

VIDEO_URL = "https://api5-normal-sinfonlineb.fqnovel.com/novel/player/multi_video_model/v1/"
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

def _json_response(response: requests.Response) -> Any:
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise HongguoPluginError("上游响应不是 JSON") from exc

def _get_html(url: str, *, attempts: int = _HTML_FETCH_ATTEMPTS) -> str:
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
                timeout=30,
            )
            response.raise_for_status()
            response.encoding = response.encoding or "utf-8"
            return response.text
        except Exception as error:  # transient proxy/DNS/read failures
            last_error = error
            if attempt + 1 < max(1, attempts):
                time.sleep(_HTML_FETCH_BACKOFF_SECONDS * (attempt + 1))
    raise HongguoPluginError(f"fetch failed: {url}") from last_error

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

def _replace_fourcc(data: bytearray, old: bytes, new: bytes) -> None:
    position = 0
    while True:
        position = data.find(old, position)
        if position < 0:
            return
        data[position : position + len(old)] = new
        position += len(new)

def _replace_sinf(data: bytearray) -> None:
    position = 0
    while True:
        position = data.find(b"sinf", position)
        if position < 0:
            return
        if position >= 4:
            size = struct.unpack(">I", data[position - 4 : position])[0]
            end = position - 4 + size
            if 8 <= size < 50_000 and end <= len(data):
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

_STREAM_PORT_RANGE = (9990, 10000)
_STREAM_CHUNK = 1 << 20
_STREAM_HEAD_PROBE = 1 << 16
_STREAM_TTL_SECONDS = 900
_STREAM_MAX_SESSIONS = 4
_STREAM_STATE: dict[str, Any] = {"port": 0, "server": None, "sessions": {}}
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


def _range_get(url: str, start: int, end: int) -> tuple[bytes, int]:
    headers = dict(MEDIA_HEADERS)
    headers["Range"] = "bytes=%d-%d" % (start, end)
    expected = end - start + 1
    last_error: Exception | None = None
    for attempt in range(_RANGE_FETCH_ATTEMPTS):
        if attempt:
            time.sleep(_RANGE_FETCH_BACKOFF_SECONDS * attempt)
        try:
            response = requests.get(url, headers=headers, timeout=60)
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


def _original_format_near(data: bytearray, entry_pos: int, default: bytes) -> bytes:
    """从 sample entry 后的 sinf/frma 读取原始四字符码（avc1/hvc1/mp4a 等）。"""
    blob = bytes(data[entry_pos : min(len(data), entry_pos + 800)])
    idx = 0
    while True:
        pos = blob.find(b"frma", idx)
        if pos < 0:
            return default
        if pos + 8 <= len(blob):
            fmt = bytes(blob[pos + 4 : pos + 8])
            if fmt not in (b"", b"\x00\x00\x00\x00", b"encv", b"enca") and all(32 <= c < 127 for c in fmt):
                return fmt
        idx = pos + 4


def _restore_cenc_codecs(data: bytearray) -> None:
    """把 encv/enca 还原为 frma 中的真实编码，避免一律改成 hvc1 导致只有声音。"""
    pos = 0
    while True:
        pos = data.find(b"encv", pos)
        if pos < 0:
            break
        data[pos : pos + 4] = _original_format_near(data, pos, b"avc1")
        pos += 4
    pos = 0
    while True:
        pos = data.find(b"enca", pos)
        if pos < 0:
            break
        data[pos : pos + 4] = _original_format_near(data, pos, b"mp4a")
        pos += 4


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


def _stream_session(video_id: str, config: Mapping[str, Any]) -> "_StreamSession":
    with _STREAM_LOCK:
        sessions = _STREAM_STATE["sessions"]
        for key in [key for key, item in sessions.items() if item.expired()]:
            sessions.pop(key, None)
        session = sessions.get(video_id)
    if session is not None:
        return session
    model = _video_model(video_id, config)
    _, item = _select_quality(_video_list_from_model(model), "1080")
    url = _media_url(item)
    spade = _spade_value(item)
    if not url or not spade:
        raise HongguoPluginError("播放模型缺少地址或密钥材料")
    key_seed = _key_seed_from_model(model)
    if key_seed:
        try:
            url = _decrypt_spade_url(url, key_seed)
        except HongguoPluginError:
            pass
    total, moov_start, moov = _fetch_moov(url)
    session = _StreamSession(url, derive_content_key(spade), total, moov_start, moov)
    with _STREAM_LOCK:
        sessions = _STREAM_STATE["sessions"]
        while len(sessions) >= _STREAM_MAX_SESSIONS:
            sessions.pop(next(iter(sessions)), None)
        sessions[video_id] = session
    return session


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
            "device_id": (query.get("did") or [""])[0],
            "install_id": (query.get("iid") or [""])[0],
        }

    def _fail(self, code: int, message: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(message)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(message)
        except OSError:
            pass

    def do_HEAD(self) -> None:  # noqa: N802 - 标准库回调命名
        self._serve(body=False)

    def do_GET(self) -> None:  # noqa: N802 - 标准库回调命名
        self._serve(body=True)

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
            )
        except Exception:
            self._fail(502, b"media session failed")
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
            return
        start, end = requested if requested else (0, session.total - 1)
        self.send_response(206 if requested else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if requested:
            self.send_header(
                "Content-Range",
                "bytes %d-%d/%d" % (start, end, session.total),
            )
        self.end_headers()
        if not body:
            return
        try:
            for block in session.iter_range(start, end):
                self.wfile.write(block)
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
        _branch_one_bytes.value = lzma.decompress(base64.b85decode(_BRANCH_ONE_B85))
    return _branch_one_bytes.value

_BRANCH_ONE_B85 = (
    '{Wp48S^xk9=GL@E0stWa761SMbT8$j;R-wN{#^houf7QIIVU7<Ew*6C3?&vQR7`VixMIZH9HyzSRN)dgt5HsOFl)*@6hSxGmq5aA'
    'QqcTJ>uEXt3ca?@+^++8<`vdWaS1a!^(@3piHN^UDea^utz&m68PwK)la*43U*mNYT~Az3vWRR9M@u9%`>|`oTuVAm{6Xbi7<B{L'
    '+9%}E{{R4tW;N$iTuuPgJ`u;tZ?qE#6f{J&gM{zloCXZoG-hquoMj#I1srY?B&~p9xgbUzb@!5*4S7ma&y#>iUoW)6rJ_BOyLIpL'
    'xODyDEOHDUy)Hr^$hEEodD$hbGrZQIEu8`Tb_H;~Z>VMWKW5~p-hONtZJoi*u&tO=m69!Z>V7E`+W`F%rB6Z`>9J*SJ%Azqgna;j'
    'pyLxZi;ycJaM~j<o%H|7!w`?YyEm7i6pMnWxuw4z`~B6UKR|wY@2gl<iXrJDd{_1*$qp;ibMN}xIL<*Gi$aI_ToO8niDZ|W6uz1!'
    '%)Ofu3qfRq1h1p__0g|vqG(?;aP76#`-*@WsTbSc98!AL83wt_4q^NHqSkY?D&ko53i_{F9n~l_{x^5C{H|fMAIX4f`wb7ERjZ3y'
    '+#;VMHu5P=Jv3&yp^-ASDTXYC%$TxN7n?j-=xsY0676yMQ)eWeYkG3JD<>_>t{HhAIxC^4(?8&VcUx=ux(qrgcIAXU5Yosc?z1$('
    'FqfP|)2$ve(&}uw;(uxdO>E6dMMn^`79eTmC_B=qkOB^y=1A8sQi<MgW~fDdW0t4{^<IjM^J?x<&Z1M)pYO&uEA!yRw?Np_Eoi{o'
    'V9dD%VA6x*g>j#h5;4}+#ILn~##Qh5V8-%l`Cgcy0u7DR!N$07Q0#BWZ9icP<a5UiL*HS#iW;QiR{)ut8&c9ibCtR^s-hvxT<B5I'
    'pZF*<3Mz685I{5Bn03e7@&D%xea0+oBiI=#Ay^38D377%<QuMZ-O*%Tv;8|=X7k@BR9~m7iE|@?x%zlQ3NE968S;+Y@OKTIO1nRQ'
    '%$PlmG26EWG&hsL(A8Kvzr*S5Ay&gwR^Qs5EP|lmJc;6eX{5+3>-W3P^XQYY)|Xa<5v$^`p|naVLW^*4x>oTf$}?2%{6bD};l{wp'
    'UXx&>{O<J~x}|>(!V18p93xBW_5+H#yeu03vRjESLXD$A9{yVQwj)I(NohO>ORrTjPEA{?DAU0dxSX!K7471{McHXwNi-H;o*fS{'
    'A^u%?y|GH!Rj#yLuLt`!o<Kf)Y(ZpN4Tz3<fO`#$DE7bF-%oqDst*3_DWg8nZiEfL0Og$<i9XRgsx?2^G>t{jYLYX|a)tAG>|ahQ'
    '(CvT4r8nG+e1c=US5#<;4qieQKmF}v#Lir5E|do?DhNZDSa32d|8J@+jja&PG#}{s>QAtW@PV$U?q=(1XE9c#V$_wg+bp&V&B)eE'
    'w|E7%&@=fW46%KQT|hx-6(^7@;GSAuQiVAKWj{$=N<Dko+Tu^~&_g4k&tWyT+RiABes%c{2GlZizn~-ml%l&HeCQ7Y89{*{FhFJ$'
    '%A0T5Ok9YTqU!Y`FOD0Vll<93GAUvEw{f##S5Na@_<&-g^C8;XNP;Jns4P4`9G&OuVy9F{ye}9pZXFBGaV{9GqWseFXXDkv-Jtr#'
    'X`v5*<V}u7WzA@LlIItpV&L%Dnu!B`Tlz^fO$|&4Ecr^f5@l|Pk*?l`Q0k`=`(J9}mTP!oxXK|5+g>iFaV|-^t;>U+e*p}pUxsGg'
    'R<;C@A<@#B?1bIdg$yI+yA6AxY23cPa12A79#Fv)!=h0N+GRs0Kg078`}Jx76kkmF2?7`fU$Lt8m3@5>LUp7)McaOF3%leJQMA(V'
    'z#j;PC$N!2YwiDp$FdZE3B6)aNBYUa(TNaoy8X~=byBHab^*nv9%*}Rf54ca_b0AXoR_G3a@6Q#ZFpU^6?~3S9&n|oyDT=y+-aSh'
    'n_@mxq0;KkI{N4=aOj0w-G;T1{5|jUk~rpYu}~n&xeXONR{x@w=wxoIjOh3^cwp6#*_zNzKwGmt%gS9r?F8cMjKT$lB|br+51yB2'
    '=wZV7fy7D{`(29#`6Q#QIa%hm)is>KD_ry#_H*-F*|Z?%Qv8Wrj@X=do{p=*x3Fz@7wS7@0b~~-n@Ufde^yLqtQCm?0O`Da6nn-j'
    'r9Pog2fjAFwY<gel`&!+$DANDLZf`IKhg4BZGPdEYX1n!8rS+gQ7lP{?{KO45vsUu2dS7*+lGbck?L*-g91mpEav%V%JY1;m@7bb'
    '!~8*@(PmIx$hM4)kQD#-N9l_sU8UpQyq;#!2cR64Gr9}3BImqV(P!p6uw?K%E^%~`2F*P-WIQ3uw-kIk4m<8@RYF5W+XhoQx`p6k'
    '+9I#{E}8>IJkyQ%q6436nF9t#Lsz;}b$hp5{_)$_DwZec8D&xJpU4!-(s}b112NIK72XtvrrGX22}y~3_iro{&MnhETA+DaK?Xi('
    'Q0J_&dFeJ5#7fK#kt7e^e@c1D7iOsd7Y$~wsRTJ#qi|^(h#yWd2}FIU8B9IG^z<X74^tO-6ur(^CZ13AW`UFbC{Pe%@)oIN45MqI'
    'PHdq9D!Kbze*P?h!OC)3qiB!l?49WS?)rHvoGtFxap`)w1=tf8AMQ5IfrG3!9*(uQp>&-907)*(j!(qXjiLbP^#}@|w33k4F~`7m'
    'K~fLbR%d?z%hl(M*M#B6)+ez&D3$JDYg5AF2vDMPEE2G;dt-P!gtE!qaJ41%TjxghS@IBUwUEIbBB|AJ4?hq}BLavJ+^|F^sE80o'
    'uLA?B96n!Yic+9jWQ6baLx|+P0BjCKJP6CmKDt5GssWs1oekHG4ifxLAKG`*ebaE=-5kobMB}Pz;R0REqN-x}q3%W$B*jB?E{A%B'
    '2MhzK1%uoumz1tpa`{9cjKqgYo(@1|z(N)PeGvIibln>rkSAlt;@TjZ46mVE-PxOR1;;0DloppysYZl<liKBRKRt?9$YPa;+3T}O'
    'tk(2rC{(dZQ`ym+rqP^|wr0OI>e6G|A!P|?bB1T7wCbzf01t(nEUGrFWjeMlraZ}~O%Xn~3S`Ij?3XhZJj44r^n=^V1+N&4lbxGo'
    '0!x)@u1Oh2G558Kzoz_xRv^@R+Sg`Cz7G*Hrru<u)3M&MHearUo8*q=Tm|q>F#dZW2&@Gr5H7wXs&LAz?4wE7`UwBTRkeMY-w&~x'
    'xYPt=bzf(89ffpeR@daZBH>+i&9AQXz8Ag>QY~)CA!cmHgH<ADaviZ)5dYJuj+}hxlHaonh`lzE$v|TZ2F?t}1iK6w3;xx3i`k5E'
    '3fT8$h)$9gl59pjn9!Wyy(CiSm)fITqjj_HC6bB*xqNUV@F%^;AJG{&N#upHz)q{2eGtJ{3Vt*~?n6mbI5?3tt&&kjlS^Jk`5AKk'
    'stC&F!}ev&(y?w&Bj#pL<xuFqZlgCPdA=?Pv0St5C9@`p^%+}>PV`CM4&WXiAA=p%;HSE^I8hyHb@HbJlKm9(B<&rvxIdWJ!Ra`W'
    'hBT1d#{e#>cz9y9sU9Z>FD5Whu?djyd$z^Ls@m~rs_#3A*V$?hFlmO6p0uz~8wP--L+&#T9-XiXKJ4AQ%8r0jK1b6h*9Wi$-*5_l'
    'O#gg!K%y%um(KnRmO)=2JlcF+X}hP7Gn{v@AW+9!+?D4&s3dzwJ?<}0CzFsHw)I`q@f#x}7%g)SCviR=d%M!Rmu0E64)p8)od~J;'
    '`uAVx3hx(ZmT&ZB5FN_#N-S9Eo!g%GuzQb%boa1Ar5RHkT*|?FDT530rxbxdzA|UYb0wSBm%7Qn@nee@gz=>xU=<{_-qSfw5uiL;'
    'Mw2t@X*I@v5gyeO;Azw^vnq!jZL<eeC#YGoyR%FFGgKx7>CTY%Y{$jEnTUhmlE>vWa&xR^daeIgtPS9t@UxM+5D(jQtQ_K#m>{iU'
    'O?L(Lsk3<&K&Ums!V4(!0{&6z@!u^0I%2ikvMuCv?M%o^RU4iL9Ul=Tq`Qq@Y|gl{oFV~Pg{3!t#0?>Pb^@f|3o+DkcL3`=U&&99'
    'n1ipU;k(6$Nz26d3+X9kD2Xa;);f=qm`iT8!@&Qu*cJ5i_@Hd;W4ON2#^@~rt|oiREpd1zc0fLvL#d((Kta6BI3vAn-V@xZV6?gw'
    'BF+>*#3Zvm$iZ0&*L4xFf>P65Fs@w&+C#wM^s41lRJlT>3OUK+H|^M(l{gmrAm#*VIo*I{)6)`Nzr6!nmw#7l;a=;Tn6ly2vS7=!'
    '4~fE_r9)9&$7RnSmaUHleEM)gsGR)UePI2Z;ewO0?U{4Hj^NSpP?ZKTS1ny~#up6i*JvMIBxfjm6!LI8GWXS)_4~GP0Tc`k@RHlb'
    '?H*yz0Ro+%R`J|{HtsE%xxbx|k*{5o_xZfD-4bteruCah1ep@1vlv6^uCy1}`{fpW42@`+Mu;V?l$yPujd?<|dg(yXnEsC)#1?($'
    'zKI!)WJ{_o-+z`%>g@GCWa}v981h|wyGx=%oNo$4GCZGs6t-$my{R~~VT)-|t0xOmFH*mG*~zgs#tB&P;ZmopQC~^2%k>{0d<p}3'
    'yiuQU#kl%qM@J@o1s$0?AI$+a`tuRJtV4h2xCDaOMA266*nM}E2{;$JcVMOTdlEtNJv@?I-2L%@2q=VCUrysWM}fF%iaD0e+pt)O'
    '8cDVSi$j093_3X&BFLbb<ehj->IwfZ|8hkc56tni&2PBSpf)>hw3C=z-?+kQb#d26(o17askq>W4Pr};0!JE#@sxOF9my2)h<;cb'
    'qT6pG$%k6+f=FhWam9}cQRXZN5wlU$%U1vcZ{jIriu^h(0M*xQrm~b4xv+A)2*h{|*OUZHRs|f|)GEKa&*g~)W2TtT@sp!Yi~Jp6'
    'wj$ze7Qh-nn-d7f*<Tva>4;;Fh?D`p1icS86F*iA9ztj-WD$>79%gsB#1FbG{_>5LsYa?X69@8s3xd{bEr<N~$Y>`6YU0#ux0)++'
    '_%@p1W~Su8mIu&SDyjn!G5Qr|8K|Nb9}JFJojQ+6p^;w+uT6lnyKtZS=3elR)`hl>nFV_s<6^h;+(3*4)YFb;uPh2sE(;xkw=o({'
    'rYtN4S@zdyB7&z_aWQZ;0%0E*48M`@aATEdR@V13+j;5YhV?niH+U<3IVS)kl|v>n;TU6E(jG84m^*Zt2HF%yZ60921r25wAoevU'
    'fmk@6FhGsIlMK1CsV8Jm4?>-}sW4nU_xov}%a{Q;0GBl>+%-!r4`9mrOw6!D_zy3Kwa6^~rCkp^A1C1|-Jv*l9M=p(toY6>j|X}F'
    '&J*W-E$Lo`K*Nd<EoHO-T}2;3saoc$h$~Cga?D2<*&5Hg46wV3^&u}eJhkX|agkeS8;CBK7iTXMl!@!z3#Xf2x*z*nF)B7N^U=Vx'
    'B1}XSW_z$tJhrx*(Dmrr(Zpe6?bMoEU}Hd$5nq02d;8BUsG-9!=<GO0R|^ib3p+0%`}yu_v~J#U1ypv5yk<wJ>O**eB~TiY`XMSO'
    'jw!2tgE@FcbNS9HRi#}gs*>CRWVgjZ+WHLslM%L{zLlX8<O*U*kHTO10bKQ!rz((U%!zunm{*;U4v`f=tki_GYSn_(WA2Q8P=Uk7'
    'YSNM`v$C{T^NR!Hx9ak32Of6EQM^virk&Mt_!gSCwpt|c<Bx7L(PQoVzQ$tp*1$Qn_;wc}g~yzw-duDWuhv`_SQ;@;W)swM@m4Vb'
    'W8AezVn#N9$eYHZ>k>UAErfG>z6II2{1c-NL1G~)I^m>#6?6%=NdcxVnD#ni3uWui)jx9C4=W~kLY|Oe*bewS|N8*!A|#x($!+mR'
    '&gaDU{A&eA&TJ~XwQ`Fl%NrdX4IS10ui2`WfEQ~bHe>|0ky9r;QeKb->WHB`kP<Z+-rb-v6%0~3m7?si`($DP(UgVNbXscA-z7T&'
    'BXqY|qYp+5s?p-tV9KAT`%Lp&5FG+vd$KsO$q>(B+bZ<Ei~zr+3)btP8>-ZV!rzOtPOZt8Tzpn97eQ+wLh9Tl!))xz{-b2}kkE)X'
    'EJG1G<A2Xjg)~Ie>3IPJPD;I6su@*;N(}z!o7+h>cAl{jEcZ2<pFrdhcbK-&I%8!iASA~9B`vDzLN3vW`c883<BT$M^gS3-#&^WI'
    'LaPGGG|E;t&g46)d;@BlL&Y*3TS~FomoxyY%V}Pk=!S-=MV^{`_4HbM-h9Yp8TC*Z1}*{l<!U)PYL@jc@=-i0{QK6{pE8y3AC#bp'
    'l9ydw1bx^a*@@o{E{{lozQxm*zb2_;&9t(7?XIcrpX$(_zxvcvGE?2(4pMG#-_Z%)u7M(X#=t?VqDUmnx$qkPx5p43&eK|G@e;E*'
    'bjQLK!U%%6Tou#CZjwn|W-T|PT}A8LCPa(L@7n%1m>lfCJ3Ne0NKDBGgit}LYoOSmsl1ef0PEllmj*@Js#r6w08Lh9+bSeom$_*!'
    '5|r6Y4Dx}JPapC_RA{VAT|+ZpKEEoA@4)`4S6pmCKGSZTTrRNRB@V7-ucDbG4nM^oJlA)h97s`h>~c&iC{2ig!d1#Ms|2EpI4<pg'
    '5{k+uapUbX&0|$96o+LU(VI+VYjGtVqIV$Uh3`7JiA?nYTAi`>VS+bD+GS(^tdl5+xK6nJ(&b5xU~owi2wxtJwuQfZM9MOwx0S&Y'
    '0M|tBN1P+_SY#BSCCwPqU4kW7U(8c0F&W4nF1xcA91f)B#zz{gL3*#w7izhnq>*o-vc{mLA5QT^YFI*ri12A+GoT(*4sD|;Di3L;'
    'ddvAmG-l-X;ZAVo5xfgM2m#Lip2TfW%kJ?d*tAJDuo;B0EcW}mr$d+~fQI<{!iGQe0|xatE}eU4w=svBpHR<fP(6WoFy&FT8NGV8'
    '(&Q+7Y;%mbwDXyAtMj{#^RRn?x;8cRw3_SKOUhQYa!+q1OWqIlj)JZrOT^1u$Bu;$Y{3nEyc7#(9Oelrup)4yx6w}}2nJRD4O|)s'
    '%rB{_+nfdK5eNdcBW`Z9BIod+IMwsclUxn(!bp2P0C7SD8_EA1q+IBikyuTHEyw!3xuIJaTvfb8c7EPcg_1Q!C~I+Tu`$dQ^{tD8'
    'gUR^F@;|pVI(>9nV9L4ct5-EG*Q2vOh7|QvY@fsu-mx4=)2$W&H%Bv*6Pkqo!X)sGUjZ*w?($clu1BKNR!cvm&l_A4!QaMjH<)|8'
    'n~62K-9(7nUGvuX);0QFvfsj__uhI8O;kdf<L3V*IPRzzDHf|ly5R+Y${!EQG?PpmLmZcy7n{u5$Ua0QuI(2yZsq;qPVdC}peq^0'
    'z<@pjzs`{sAq=EiGu9Zu+w$ZG0ss(;51f8bw)di87Zb5v+Ng67DfaSH=IO^;AYi6tkt^qUHR;7g(k?Vefu`^xoQN4#U)%-JB;8EM'
    'fQT`aG&H`LFoR8qO}2be^6`gmM;n?H_TU9O4M)BE6(zNvxy&tDQKK}R@Gy?a8rvU7vhZ$)+ei#!QQJ+GjyN1|T=)K-%FGHQA}M(+'
    '{CK+xt4R$YYgYPkZ+(JWiO4IwTumqD+v@f?=)w_CvftQMa>TFkgOHe@qOnFRSEJtXUJpu+LXnR*N4v`Q83l2{m1<!7cv4+eKzRpV'
    '2($w<QJ-5OPeQ6Sbs3`oUsgo-SIo}`aMI5R709Et|3kbwyohKtqkky8-SiNU-g&<Xqi5x&!-HhOoNw8lf3gR}HgICxVvi_#kSC9)'
    'wB!Ay+V?oB77Gr3qCQPEpF`s{=+%{~77M(Qz%mS?J$rj8RIJhq*k~4KsnvBFZi)F2=<j9bv;N`cK71xsd^U=)`imfOGvOI6yCL9t'
    'u&`eXa1#S>pvspU*&UREpagCvg(lKkm+jlKin}pFVycXE6L%w(vH&1}baI9hBwpzi>I<c3v>O466<?IPbZQ=$JR~w7xp*k*VFacd'
    'Ev$B@D+QyksU7=6>7L%@%{_50Sj9%@XzeAAOqip=#fq?ykn4q)2(|F|?HnUV5;G%>lG*m}Au;xPFQ4(+j;)-1SD^9BtFjE^O?z}w'
    'uU|!m6Hy#z2M>UblgTLeaF%`8f16wkT><Ui+TSp}e70Y3l6@Zywj0Dv=uQd*K9?KRag-yLHji0#P!`p}>fnKbEb?e@em~s>XttyK'
    ')TceKHQ-~Tnz{k+grpi-x2T;K=yM_^%S`iDEe!1{lj%g!G~tdPIc}F1V7n8}8Nk*~w27SR70RK(##!BZ^@G6-XQEb<XjCmyJeW|2'
    'XX0>9t|3(uBG74aC&5gMh<}|_L8@RrOvt1qn^KyK5@*eAErDMMa|H4mlpeX~;P@EIw^#%8$Fs3W*5yK!O*hzqcb-^@pHmxbYO?i7'
    '&%4x!c>e_}-F<nWRhBR%3=2)xzCHs^{<K7x*m|<326#w9!z`yerW1}xe5UXui?A2ej9YGoX%gTbL03dT!(E(sf>%GGS6Z3v%bqA9'
    '4&dC6(7GuQAaO7{=>r%0nX@Q*tc%Q^bME5x!^o=9e2DXGmRdV?tK*Ze`U*vd^Cc)i6G=%2lu6SA329j44pM323>Q}aW6O}TIN}PJ'
    '(Y^EKmiAHwt}ZeXj;B$)P;W3qGjf*z6K>R6{s4ufaa%$47e&d32a{7%7`^=alj<NPhZ@hrzhw;a#18X!#z3;X>ldOIo_7_`9PMfV'
    '<86~9RK11O2Dr2@VfeqJ)icEr(oVh{jrh*<GEoJ|tt|5^L>o6W7ZNCf8jo-ka?*2<v*ArvW?28ls)^>>c9zWz4|pJ^$coH__5~}='
    'Mj)2(s#paw69f{;*cw2J!qurM{7Qwa!$noN5)<Y#1iWs;q8UC~2obh<a3<t9LyEgExq<yEfT4Mm(C+LE$m6s3$VS9bKkfQ)EW0|@'
    '!lyspCdGd}*}LySa=mo}lm^U7;%hc6_b*`k*A>PTcp)EoZhP@)Myju?zy}cv6x0d0J+gd~7-ByisLI|O>X~<X^2b7+uyX?^w|Qy#'
    'cod8xtTucA9uQ#BEVOLX@^ZZJDym^TA&G^UOd-BN3&jFO%zpa1qAQBQ$2$KwYFL7gnc?1|NCtBU)c5g*+y+O?9GPn%0BPvtEY&Zk'
    'Y906LZ{vwED1*AK5pGUF)e!*f0FPgD(Ecs+F0R<)qqRk)^WcrAhga_e#QaKU7;tDMj0Qi0)yCV!K&A&}V+zYx9w#aTHoOz6Ws^NO'
    'e}@L5x^ldz@k_mQM9=dhSxYFr*K1pdF&=LR3FTQz=m0rD>HCtJRO%=b97P3M=iYoR9501E+f|zhkdjB-ml5ulYLJmy$;X})JU$+3'
    'zyNT=s|&ZPb^&RRoPE7Wytzt^5i^-iyOFQO{2n1MjAr68i#lYjQNZ>4=eooL+zpM&E4Jkv6N6AKqDj9<zDA8vb>hEF2H3f)Ehqph'
    'I$`&19~xp|KthQK>8t|DOAF0Fq&AUnTMuf6Q`n`VsVE(_4L~E!cl}FQDg=W+@HIkucI9Q2%PY>X`q)7P!lf>fPm4&yX5&a%bZKEy'
    'm}FRrxHg!l1$y9y<eVyWWULXlDoC2j#@XxmXGO+0F>Ss$ukj&~twB;p_?hAab<M?AcX8KE2>Q`}9Mgt9Y23OF3A&X_>oGi<n#;$j'
    'BEXenz0@hx%7?+1$S)@(_&&O+g8x<~E>GXT>tUe>LAG~6d7{>2=VA?$j2svmjI9LncaGVXPfjK{J9fDKJ}7Z+(7%Sy;<ZL>Z?g;K'
    '7rYq|cO>Ma^A(!fsLpc`Ov($85(=_aJTcHz>vfvj)8LIb_vkeqBjdiddaQl$Cgs@;xAk@-%pjZ7;VnIFoD7wecc47Pj<RPokEU=w'
    'k{h%I+G>S4z<AO|;h%k8`JLh<>81ELs8~#u1ku8y@4?1EzR}~D^1Xc-^Z2{`=hMlANbzs{o6#@S2T!_-b^~V`zxQ4kKB^mHF*;r*'
    '6Y@H<<CsJa#Oq9;Y*T66-+(OWBOb*~$-hGY(K7#g?h&LUPT{hU3VT6*2i0(+uiRoUs&{rWb7?y8c*ao7<8qnl%F@!3zh{8F`$Gg&'
    'b6*)k5j6>d&y(Wf(Y&q8zyyKBlvy}_Y&I{%!f#$Dgrs}F>QGh*hn2}#WNst6!Q?wz%p0W6njR>>cz6a+No<0vS!G=N!4Y^o+q-*U'
    'yD$@p!i|$I@`{X;v1fX|k5z*J{TaL8RKb)T!vpi_gd$?mOSdG)%3qc4ix46SfP;eZM#Ii((=+We!%sKq3UCXmEEi`{eY;(`rmdqV'
    '9;(y1{6niqWj$+zPeg4?MY__EReO|KGj2}I%NObBmiEKx{CB!o=SIv4ZU2KJOMhs^ZQqbs7obl9^|8){XqaNp+(039&^000Sa^h&'
    '24%u1SGd{X;_&jh|1^|z3t%L-=xP*V!u%w_`$IegUxv>39@ku+aJiCq1DyW6ayl{SLUVR268{cZ7$oh(Yh~pAabC9C3`>B^8i3jw'
    'cgyaT1*d%;V&x2?QGZSpJyN+@7O?W_)zWXN34Eoez%c<|^4mu<_KPoCRvjokm69iJ4ACJ``8J)wK6{|9dL=2{C6~&fSHc!~4x&mH'
    '_m^imaD|EzFcow!V^y|CI~T6}1`sCH{ZqL`LG|rvl7UeLtOOY@id@bc${0dnFCBGw(}}p5kA*qB*?g^Av553SNeW~CO`9#pr~P~q'
    '%2(z1>q&+-X%*JJebW#_MD4<r^+IaE>N8WZk!u)-rsr(5H2#)1>;iC;@*8I^B<*_|q=T2tOtpm+K=Fe3%P2`ymsz;GR59Gb&>srW'
    'k#lwi!x3Q1M?^Q_<cIisHUzTJY$N3z)A9V)KS%uUyAm9`?zuUXoQ8vEg0n7WrlI?l*AF8zz>enuOH=X*9c}(leKhA-qQ;462_!#*'
    'Pe?r;M_4Nwfd6-`X_Fb!6PT-;zt-+O=^Jz`-JR1V@B4I>eR+ho00s6eD;9FgSLqH1wV%@F^$gs>b_zxfvulv|;zIweZ5Vbbca$B6'
    's@#B6JERzQvsUQ5FOrX6>Ta#RVTbm@km0(utG&Ke1hcv4<CvH{mGy&ILfBTA0o8ZZ1yM{x%H^Or5jf6J?=L-8d`Ya2m=(uTGO(Da'
    '+OM)bRzW@xBd(3xkWyM7Sk5&>&zdr8=7AX+Cb8!iUv`?$Cq*}DTOxb>yY`v7Cd1^lBF*GQTHc<l`m>8cuX*^|dmbpr#7tt6J$t`2'
    'h)c&z03gs}>eWqo9~BsDzYw8VZ6t&9<r_cb_PL<iu1K~&p<x4ObUO@n)&_pV((HP8j(!4Ww}-b-@l3#jzoJ^zW)Jo46N+raSUzhe'
    'o4wrTSZg;LJ1h4I{|#Q%(7-J<6D|@$s3p&ODUo<=7_k%O=0@CARS{8;_fY&6rPJsyQsdN=7DTusc*zmfTSW#9-e%EgiE9KQAk5kw'
    'P#)s%h|B`?%7FRrlADbY5i^sEZ?Mf2zcdq{@_fYD`^h=Lb+Tf><b*ta)$~*?$wYK3e83b!e%;JNFx@0zqOzKQZvWwq$BWy6$9API'
    'VZFw%dKnNS5G{^7$afAKLlLTtPwQCM61v<iaU7i84HGLfXsmQlak5RJ43|%i0sgQ!s?GS>oB-kd;m}c>Izd7vAu#xnYZ<?hz~f&_'
    'MO+7}p@|VlWy(`;rl}eCv@HpK9@mUp=M^5uaE0Z4`=_CWa2@hJV<v*B=N%VWl=bFii>TO{a)*YzAsX^Qw(@XZj})i?G07nV$&I;u'
    '%-}gIAIQPL7P;M2&tpL#^K}aqG%oNFJ061=`7vO4x-ZAbJcX|RkE@67);I>}p(7-Ot61m>5`pjRH#8yI+EnmtUM@g1|3oI-8o7kQ'
    'XFxJ3X{~ep;*5O>;?GCGNf3Ik+hbD|lDo}<_L0>GCo1cOkABa4L!<<fmJ!BQ?Hf-8V!dr8IOEP$F}zZBcRVol^D#-;-~Eq0?l>eU'
    'DiRZy@DdfK8_H;A2RBmyBu5ZmFRm|Kh^9CX2Dc?c6B)~b(4p0LX-x-@DseT}jD`^fcOOR9jVk-wZE`NTC<l2ZQJWS7TvShg%Z(*E'
    'r{T;Db4-Z)Wjw`1c%U1gbN9^OAQQkl>?z!~Skzxz2-410{ur4^P<f)v|DZ}t_132kScw^ni-t%9k9XMrWAC*RoMY0gP2|l7wl?CI'
    'fX=R%qA=dXXCFt;2%Z3h9<+nW(5GWU%O+DyU5xND_xM+(3p4ggSuW|atHu^~y)H0&E|IuYsXqh3h}*P;fn&8WyoXi?V)la^6zOKu'
    '0vPp6HamL%z_>17CZsM5cApJR_U{*36Rh0h1qlg3`kuxmj1&4b_-W|F?OQDMg~ISMnec^>kZuYed)n)eYCT;B;t?v6o&>CS{dIJm'
    'h+srIc=rKUx*PB&ReQB1P*m=|g>X^-8n@c_m4^3iHpF~BR2j1EI74nv+CT=J`mNSK0i?*esv~zHAWK1x+Z%Yz5%)Oas!b@;O^G+P'
    'Scz$&p&^ff`xXeMo?%gXzQkm3#=HuMGK?FzmL!C?%B#M|2k{G&_vC)4OZVM28#w-UaR0hi;XXd01qr7u-w6jPmXxv^G669<bmU^g'
    'k+MH?ay-OD9|W;<mF$7y>9cdq_xA7mS@3B-o8AmW1LfQ1--jU<l8po8B(RMIo!<!Fb{Lh&1{Sgq+Uh1dOGN;4W@+k{BojfHpr&UA'
    'oO%t3YNigNl<aCMd9FH7xz7`w_R8vdsng;ID{aN*OoF$jqkTB3IEb2X4@4`kt`e3B+FVzcN>}%nDEQnRap1LS{?U~c4DpUHhY0S6'
    'A25$sj&A}-vlo!^Aj7uuHfJo4AF9&@aQcBJGxwBs1gSWVx_uERU~L*5S%AWc0x{~y*^HAe`tvS8B{lhL!;4_w)`h|Gd}2C3lNnXv'
    'D%j)-sc+g0Yqn=4?L9(NP}4E9ad&rw1)lI%AV*+j7sEtnt4A5pN*{C(Jf&<7xN1};$2>_POQ;>Il&(22NkLQ`Bou-_`OI(4!JWTL'
    'RXZircVC}Jyq>2M4z=*F(Jj?T{Zv>@X{h!2aAq<jyp7FRb2c9oI^0V46t%WfhFk;cd#qtsl+541VDLDia;TeZg(OgpD#k_6MMBC9'
    'VKMoyj--blBNw>I`O+zniuZIe{-amNawhrOslk5blTTIXyeg)+>r|=?Qr<-t!EHSMqlhJI4%Nkm3hZ_Y-<|;Im_2<>Q?cf3YCTp}'
    'xD9UFPR6GR*P6ZhzS25DiP4&TSD<oQpT!6Gs>7Ce$--6qbV_n?RF?+>$8I2x5+}Wy!@D3%z@X%J!!nS-qms$q)YOrjaNG@3F2JeI'
    'B11G89c#!QRdEil3SS2Dcnx1iDNx4pwR7xdP$NK)7b!FPocY>_k@q|ua8R;6)J3Qk0h+YL_iRENH_!Lu9RP3h3_ksx^LPNmXlY!{'
    '7y`-skrRe=0^nqUEM%ZKm{T+YFg+{ama`H$UfOu|Wo}{~Q`BSA6bB`&x3baJSvimiBd(B5ZRC?ntIf;FDi^~|FS~vN;b7}SAjEQE'
    'NTqu30xy1@Wo%8r|4vgb{Yrd0;iN5E6jIh5Rqv4W^h#gT-7@MKFZ93v`_3A;JN=uCYZaY$MbH~=2QSWKOa(W-8el4Rrqrw}0UqvW'
    'P{g<?Bt(*K@H)3PwgsJ2FAd%whMYD`#D{0sxpx!Y>0e+C5|+DNKFUJcasKKjYAptG%7uRTSR<4>lHQWJAhTvl%mRf9J|F2jA1VCT'
    'gN{3cA?R97Pqm#W3xbIEg_2nC;2x1T=Vnp5tTwP{Ju9N9BufCnfhrWLxnbVa>Nbg9{u4TMXk;+<XO)1>SDrjnN^zdI7K@#L(GW}r'
    '1$=l=ni>jyarNmc<82Z4`)X3yy%w^5i0Y*JfayxJ_Qa-04?vh6Fk8s&`+ej56KkW=49@=^@F07CsUMw7*jhgv%4+P~bl*CSz{!U>'
    '0tv<kS^Y)vpjZ06U*eTPN8;lIA4NNo?DdCQvS8?5w3-@;=+Ev%Ll7Ej!x$LO$sz?n@I4~$|0`L`SQ_;kZ5CSY<Kxa0^i9u|s|~Nw'
    '1~5HbpuddQ^Ls>0M2!hDjcBkR`HCnm|M4_Zd35d!3Jl}iy}c@|KWWRIr=Ay^i6q}#uB|s`G+6{D7!;GO>PnRIcm8C2<lYzvT>lJ%'
    'g-Qxx`=^<B{^573Eqcl#pWtT(pe$O5MQlBxkJGtydEiQN5yXoyI~4#ukHZgC6_hqaouEeiEDV^SV}&gd_|Kg2iBR}rqVapm%xvks'
    '+_d?6R;8{Ne?lt&9&8h|bep_%wskas-S03-<Dd#?cRAcX=fQi)-~%&vdi_wzuc=b0-Cn15PCxDt`9i|kR}P(Ix=cz`W-phCNH*|C'
    '$~;?wMTXi1Wr%iOGm&&`tjV30f-9zi!?Rg$!A5>w8HU%ynm-43nYiihePYn9HOx^R;5HPrpPdt^;t*iC0Of7gK}Chl1FPoEOA`_^'
    'm17c>k;23<nRV#)K<e9zZ=+#20%d|kP6k?-Sme<)C;_s546EzYujIh88D_MVwUz6H?>UIcHHbN9-H*(*c5_<;4{9T#v6(WzF3$t;'
    'EYj9-3GTeJBGZiFNKfZ5l*&M>sm0<WfGpwL!Q2|l$&f=h<<)TL9cRRh%(r#<`*CAPYAhKG_Du3T9W0QY!RxRsj@S+GJ=_sC>VdpN'
    'ME!|1EI0i7DC!}j!F=O0{r#|e;TmN9x9#V+$?D?@8kBrC7+}JyX^5r$l(6F_olq+fQsDS`-zif_4dt3f)<beuhGeLPfZo&KLAPMw'
    'M=(g;79BJhMQwx#5*JRT^S8QQv+p)GzL&Q~$>C5IDd)a9lO|(VGa#SQD6ufB>rh;QXVk#)HCD>Bs=K#9oL`T(odYss>huj7K4c1I'
    'y*S~@u!&`zXR-(oQ+u7y{IB+?57IlVH^Qpk*l7x1?*jwq2@A{)T~eLshb|zTAx>`{)%2h~vcMAj&+PCLt~!4zq7UDMO3ZwxhfGB@'
    'uWYsiL7L8yuzEOYXQt?ICri|!tliMAM+#h@$cAQ#foiQnkY?e-cVsf$aJ>5{r4R(9-Fko?JK&q6ghJ{5f+M(2<vkq0iL(e8$KZw('
    '+d%060x0%>f<piGCLK^r?LNFFyU{k&0k7}RgHx^U4*(d^kWnD*SbySY0(izxtv95wcJ)ipKUj<$3$nTvw%y7=hV%U*$>QefYLGM^'
    'T~Umh53Lk870J46*~Ox!KPnxp`iD#S33?+Kd|fdDS8d4&TD4gepnv>~(u@UL>;eZG!iMVaUqBy@YFr+BNO<I7ZmokXvvew4`hH5G'
    '`oZzpURSOpTv_ICs1AbgE`Wf1DO@q?h+k-gy5v-O_BP%pQCb^qb^$_b+afLiAy%tz@i9@W&!~hx(-SSF%@*d|Gvgc~y>a3HhMq)E'
    '-18&ss>uppRbGFzP^<W{&wIK_2*T;BI?3o7odv~EUP_#eg{Kc>Mpiu=4+^?@;m+KYjDRFo{za}^k{a<U9fkam3lZo%1v(+(w_NXp'
    '?{(sHuPZH_hRsv+fNFL*FW9~I9}$tucVNTGvgamlc2R7|Y{ol52_NKx2%v*FVMH;5OYhA?6*bUhj~*-gkG^4-A@b~K8aja1j&rg`'
    'm#+0wCifK|as_}Wj@L>Q>YyGPAK9M43FD((nusW0IT*+ly}1$@8pI+c%49aac^b+PHy0vf4s;zYuri`)+HO7=O($SHgGK3dRS!R_'
    '%tVlLnUq<~?=(hz;QUB1uYz-PLxKWg2M7b(%hVJ7$NV8KhCqc;KFuEdcZcHS^%5v6TF~?Mu6IMhHgd9(KjXk=NecW=DOiM3<tQ5o'
    'w@B<(`RDmcQ(~Lc&twS%Wznhn@XT#+xB|?X{cSx0QGj>LX6^#%xSC?oJM;`w-lm-8DNY)2jd*QOv;_C3oxj2VQYx$4u9HyCMt*02'
    '>TbVw^KT>+txMSW?gE38;peu{7aJ_#Q%Yp$rngee1j#KQm|po#ODOzV7`HwTx>NJ;z5hg_zSvdevUyE20npPlTB&@&hk^WNw;Qe5'
    '9?rlvL%>R=UeauPL_M2r!3r`F6|@5&=Gu>tPE$PPeJ=-ClQm6vYTe<!0exa-Ou%Xn?eCH==^DbO!7Cy!Ph0f^iQF&cYdj8!hEPe;'
    'lY*1z!QTsLiCu4Z@GGL+`=d>RpRm)aX`JLg+H#}d@`Dq(U|J-fo5Lme&^`s)t=@V`o_maG&Zq|AJW@T;h~R>*pEQJ&!{#3HRzo#v'
    'Q85b|&tv;Rj`J#XLXktDIwu`Fvu(>LYz|eSD(*r9X>q{0Qmny<`$-B&K!owrcmk&`P`DTd()hw;9KPkXSn}lU@+72T*+c9X!p!D='
    '$K*OP!Tq}sEX&>);@WJW3uLVyn^jj0GUq(q>++wMq7wGo1gSc5Nk6TpVG<9)^HcKJ@j)q`BCx3XqFFHGj>TThkZd0*!EYiPI?K+n'
    '^rE;EHs}@#vcp7^SOvg(YD93MwOC3jSB;(x*NRlv{hZ{5&_bsiBgNkFK8i=E-gf+Z(K$POGN<eHgH=$yFkJ|zaN5k_MRt%46gO4S'
    '<F<N#^;cT~IKdf@zcFK;G~a~25u#lX81ig1ux>5XS;%%&fAZA4J}r6bGEb6JF8OBL<11D=ql-*c0LTwkH(ZLaU%+KkthH!!Lp`96'
    '#in#0g;9i?%;TtAR9#r0I{8rj)(5EMizbJN)7~u~uMZ^-L2i?IVB3E|jp1F;)aS#nvGCry<vf3Rch`0)faSg+lp^$s4mD!59s<0#'
    '@|e)#yWSAG#hJm;EX4u*aP>svlwdad9&#wZoPW;99cjSie{SuwaOJ_XgZw`6ze^wDH(y^9itJ)CtrOIjX9L{yN2H2kV%ip^uyh22'
    'vu;BwHd$IZ-rBx^yj=t{?jXCwe-??jLwBgB*b%db9Y@}*SBj7EkRQDLR@!#mD-6sY@7^iVIW;@dl8?vS3FM@%O??6{27M%m@@L{q'
    'bJ|-yyxxY5>y{ETUoKIG34YGX_w7}E=tAk&XI<`T(DJ=vEX8SbX@r<6q4+Dw+%H)v9w+lj-{MzzKZ4fu|J%>^wo;3@KKBlmYN=!n'
    'R^G$2EPlIA2wlQU!5)NYp&hm;-pM}VJ$pj^nzg5fYnWxSxD*%zgZ~iHfX*{}-7U&o46emBoDj$b@*7`qi9q%WV3*+6qalokfCVdX'
    '#+;==oWs6^e)Nv2atQuTi#@>N%pL%GJL<PtLx$5_vX+;X#+5Kz;dCVHX4=;*71k^mLXZ6@MuH~Axo2K@u+98{e@h}w6PA1Z{A>Qc'
    '`JevS0ax!p1P9{~B|h?cLL`=GZ@)OUaL<(V^|Xfnx_>uUv<%F0#rBCV`93{2r-o&h>3i8GUjqH;I+>(+U3_5R{^}+60Na*X`#OfQ'
    '?<l<FAZ0uS9XPEt>=|&|Q}~MxI3z@Y228_}eSbC>I{fnsfzaK@q<sk}EO%#7q)l&+O+_rG0cFqN*eroM4D?lU(e9jJc&T^a1OWyT'
    '$~vt^{@-J!e3g<f(3#ZRhO3yj%*>nZHBa|<G$-e*5AtIQ`#+#w$mxl96E<3p@{e<TmNb1sw_HZenAoH%T0{RtOM0t>xD-3Ms26qF'
    ')qD=~o2rYW7^%FwH(Aw`GMUFqMAIQ78>4ITjp=^q?Y7-DZ!vd<lHt1-7}S7yE3EnT(NlWg0;<Qw)r`|ejP{bFpL`+gl?;{`Q`<is'
    '73)<5iwYB806>2UHeW4twMP2!x7EP{`i*Gb=VtdncHYhU(S%x4vA)gWO9cJ>ev_@q^s$@HuelOqzx^%2oc|<7ftbi&#?l#L`H3*1'
    'AmSV3(ov@c+bG@TE8J$gKTUdKMIyL7A!Z{&w;xBRH9YsAdm7<{z_--GVD+Hh7+GvUj!U<KVqhhEImTMKX8F8DpwD<*-_>Y3A!<%b'
    'pW?3UV(64!EP%Yls1FjvudIFch8XVZgLtr0%q~rTvP4kPv)fdAz(dq3OHLuYPmip({U$-D4y|(d{UbKzbc(jT+2Q&jO%3(}l`u|f'
    'f_-c-`b&Fnnwxo~`jTetvI)s6Onu|bxIp?N>o~S^5`aL3%Mf`Y<r^RZ15xwuRk2j&FDkt+sU7YO`H99o6H7Exc-f}-)Y-aefpr|{'
    '8g22E+sOnDBx(vL^x6EqS0lnd@oFEU-*S6HvL1~yaRaL3_V?Mh8JYev0cy3j-6a2rRBBFLEA8jAzDwrYDz!x9gH@nx5aB9o@)D}s'
    'RX^!ov~^^bi)f?21<h4Dkwth)9OvVs=jH&UupwJ59L&VYjM<66)!!>Af%KTD9;V1{EO0)x!;D-Q1kT>!s1W)P=n@Nz?`iU@pYozO'
    'VpN_br9K_$!Pp?$9&_+l_B;n@rJ(S-%-obrSw{1Fwz_!ujwm(4Rpi9rDwUlz{~cy0-v`_X0il0rImnuoBj0lCNeTFXt%s^&#i|HB'
    '!@6v7N+G|~#1riQr0u<b28$fFD+Lv%dke<?R&I+eds`3<H>!@_W%#i7J1IjkRb03f5w%O*!G%0yD9lR$>Y+7;Y7Us~<NL@TZ9;Bd'
    'Y9*16x?#^=Lr@UAO3dE;{(pJK+AT<JbZe=QVio?1)uS6Y_v%FKD@lq0#lik1hBVrkjr#Vk|7%d@8m3yeY0~M6rj|{e<DPY!kVJ`E'
    'IycP3Etdxbm+u-?f2(yOF@->8p;i#>=rQMMb;z_+*MT8HU{V_A)Qi~18YC1+>}OW6c3x+>6+7_YpazZ-K$NxsJjxeLZ~`&$zxE{!'
    'A^Ie=5~$Rt<s7tV(J!Pjuh8K>O6G;P6l5Yc<n3HnCIZoeTT@TcfVV(iWi0OsTdMPZyk}BPR~DtEl&mL_Rg=9OiF*14c5+xZuv`n-'
    'cdwgFEYPX$xM?e`yJaEpflryM_&R38Imep~7lt9@_T0#Uue42e*QXAK@@GY#?(o{pED@(G&w<lXonJ?7xR;)=1d_catqe^_1V7u7'
    'ob8zzlT0#^@FlhDHC&du84=FEp9WOI+_)*S>3%Unf7~3%0%yU<fBj9PZm}O@%<e>xJ2xEL_^JX!pN|<0|C!gh{HMijCoCr-$W@kc'
    'B+Tt<XX^vmPCnK#A9B#!MOv!CBLh}u=1NM@;*wmTHfBjg&py@arKmVd-jKxI6)gk;n7b44qwwGwMB8ZkwaHlnQ>bV5PST0NmdLIS'
    '2JmUE?0V{l1k{**-iJG2gsj~g@+y2+0PvLpYAlHD);P94gSDuV(hIYC8IxhGI)%1Qe{mjP)4mHGC7U)F$nxy>)39taxgoD&DXz$q'
    'Pb;76%2-ufniA5KYZX2rR&U|X_aRC&SR#fF-+k}c(rH0e;5W0}cPIref*yb}$9yP81_jHWq4A7&tOg@A4}66o>2B?BcyD44JgQNY'
    '+#<@RF=sHtBm!&&8y0b}Qj4LNY?k*`-?Pp$8g39{S$-{i{mp~h6A0lRYq1HkvZ-gaDA;M^GVuHGuu<($c*&}I3hok&01*7;tq6mp'
    'EOVB<fC<(kNj-2i*QtnpJPy#dtSC2{a9TqTNk}L1Ijd0I!ys341)T<e;Cx(~XO9z#f+VbYL=5MNCmtHG=fgM8?pU{YfsBAc04QF1'
    'paQNJvA<12N*iknmAAVOrd7|isR@p`vv)c$Grq7%?BLkHPM@xq-I~zd4ZHjy0_dB$q_>#Crf*BK^DQj^AV7bQHHLYNN+vc_f)w!d'
    'CioL*WE~eU+5%7LAH0a2;*sz|Y1DshF{sqDneAZI9CX?=nEwXQe>yHBD2Qp0Ghb*<dHPXF+=8TQMXK*VMJM7N%}4jzGYF-y@~{WQ'
    'z|wEQgEZLr;g`Ta`)h;UG&9mIa`r*wI$-V4&zq5`TZpV5lnAoAMn(JMTiyO6${`%o3leyFVmpu1EAJd$4tG(a<OQ>@0?#B0%&tCE'
    'UErk2-Jt|*$f}k8l-W(kD4eyQnV|-0s(oDmBz2UIi?%V6Au)ROf!?F4Pu7?6qfyDvslVqiDUF}(Q>u|;Z6h6{7e<LIalS<H1xjH0'
    'l)<%Sx8C%<kOc1WJ&qMGty68S6O!>jTh#$-XLg}5!IIiDP>)6pD6fruQPWy?R2>lvnK<3!;d)o_z?;`A3defn5W0?QT!^Eg#3o*?'
    'h*7bB2!FXn#e^51^xzfCr}EbgIo*+qT`#AWEmm<h_d1idl0n>1VvQ(^8{?qyLaZL53e)-wl_#fGC0e=>L3aot4lP7u@C>Z<ZR^p{'
    'F-!YS9+LWQIvt=K3EZiLn5F^0XWpLf54M0rP^dU;#DnwZaaM7v+z_M_sf8#y10Q9Kze!|yoNv*NNVWti-^eOml#L|=r1n=WFlPN}'
    'c;rwi^RSpkx+_!Ohd;<*Yhu_-P#bVU77h+<jeWUF4n;`LI3&YlSut?>Q2dPT#Bb=B*!*{29i!*_hm=(i>UILY)3m(Y=n*lw8-LJW'
    '@EP8kQKnNMBXo`OJkan>WAzT?kQf}r2N6H%CxiwA5khi$S)r(Uq7m@#WtEYf9^dFj78!-=nw6uw!Yl619#A@CPUb#q00d(*FkhXb'
    'N3dAvhvhl6%^QdFe>M*cpi_h9Jr>BGI&R&06Py?HUbm@X4(SHRN6At!XK@m0+k_8;(Uifw$uZ|Ew%k_i`_Q~07o3D+C4v={T)W(I'
    '-TFS++nEkJ!dzrI%_<ynq1Q!^nOdJuVb~6Nm5u2xE)gLHdtm||EaGfJbkPm*t@*lG4`a%rN+RPyk4oe9<5Kky2}ka~E;!KxC>$K='
    'j!48gUC6<5#6NCF4gM`3;Zl#(BuL)dUb6{@SnpXEqYXwJI0qs_lcP$2=%hfln%P4SU=no%QTpM`EivFGgHiYAD?70xS#(q%Jv%!0'
    'xVg;%7Ot_bq5P4IDq-12K@rql$TJ7Y{jctn5+N$^<@%vs^!rn9U<fmh+=8BhXI?`YmalNkId&f<Yy`=dPBUW|asE*Bz5LH`sN3kJ'
    'cX7E5?x$NfHxufSw>kb$^v}I8w>n<(Y+X#khf$dx<`D+(=yeAg|Jg_EOkf4nXuC{#3{+aVY4m#UY0rH*aXkE)Bxpo?jPCni=p@3?'
    'Y=Z1g%Gh5#FLMe`f9a*b`9dG&2MTf6lwdXS(P4`1sT+Gf^v2k4tGFL2Fwsu;+N<fAR=ku05>wy~Z~ugtt^Q<Bz9I)MLGl!buRJqh'
    ';Fg#9d4$4gKv<8Bw#!H;S-q`JqTV}>8Hv)4^nSpLa02aqKmx7FQh`Ilkl2aQ9QD~t`!oQGL7B4RCM)7)FCwiu-F(~3Wk5>K?v#?i'
    'PhG3`5Pq>9lz-Q!R$|2UA-8Osr@y(^0gld*bGa1e)-#GTO=sC_FxYWrb!CrdgTxAfId36?$wkqB*nNChJRIc_$P8*!edLw?NB#m_'
    'IOj9vccR(-q4#lD@gFhW*N_e44jL1z>4U>}#_0epu=tbIme!p><0%H{W3zh=3_JO-NYLtM|Kg^hL+kZ5A(O!9!&3)s{z}mWCj0w*'
    'X*6EJB1##K_3BZ(qJMV*t_?ies?qcaVQCN4grm!KxpP0Mz~9Ja=RnHwWp83l%^&>epGNRVKl&EGhQ5T%;W9#h@Td@Irmx4xYg4cb'
    'o3<)AgQVV-NerpM1ITi4BkcP13}xrm)vHFXmfh!!0*qto`#oH7kmrjI(48{SeW9@&9NUYf+rRf{@8+BvKvjXYl)7m9E}1qz^DB`%'
    '<$awn^^-bvNx$kieD3hj1b$FJUnhUK0iLk}I0?T2FMhFDB5nsH3g98?Q{`u|Rw=1Hlgqz`f6<|Hg<Caj=VkI|ccbunAPjQzj4s~J'
    'TK_Ff$BsiUD>o@#8KUw>+cJv_YsM;tz1nPIZ)`M}`F=)G+i*p7#5L&0Mne$APjX9$2!dTdJMCxN7c?@^Ry;3Pv9r~Ag1*gV8*Y4j'
    'x!(qmMI-N`y%WS)G8G@xGpy-Z;7{r{iQ`fqy}sm1z2gMy^4j+GI>IN}clTxp?BNc)N77w#@z2lK+U(O}_A*75Zpq80tV`id2wW{}'
    ';nT{5_HMwb=|3sNQ_-ZvW0^kh`lM6Mv%I8zm=M3oJ)(*NxN+9tSb9xnGh!kbSf5TybGnlsQ$VCrm+$KjSE{+OBM9@EmjqrMUx}>+'
    '-8c=@sZ{F%0eSJHn_lX-0w)wWnIOkYYo5(~+?dWQ$Xa<XC*s?WtS;g%9<&z!c2y&Li&dV9T=FnuM#6u*&;7Z~pHT_YRe#G=l3BWJ'
    'QZYFAHODnG1cud&BE}tij6O|dB?HGUYs}>MFe15G4CSPj4}nDKlN1^672=LN@o@;5HM?gD05x|XM*f7`CzG)-E>Ap|&MzLZ8-fli'
    'K`y-TgLip(HQlv7meBuimanXZlcp{K+hUsTOqJA_w;<;SRGZ}*TTR3N=rGV9TR2^ds<+61jUk#A%GJ8dg5KVR3J><2f1x2>%hM8J'
    'K2z$a^u8<D5CVCAlCfq-kIergmml>I0M(nQU-$MzFzMymW=c8pPB|2EaDbE87Xh>R5Ry@toauWkT9d`49kxd-mR<&gkO^Gtj}R!Q'
    'FEK|U3xFlqoSEjcGO8>^;;YqZqr-#PVo9*%gC3a?C51Rm-aCVe;shaTv8`=%RHysx2B%2>c_}FubRjAA+4HuNIzw<N<#n~=rD|Tt'
    '&p1X;iUji#jBUr%Dmq`J<X%~VwDYxhV_m3PX75=nl8NuYjWX5QH>N;+36@+DxQ&7y^ID|tP|ECKnIb)(**9cac`EpQvpm}wvg5?~'
    'G^O_Da@}gO8Iz2C?{Q}02C3COVAmlm+6cdN8I2sw_*xc}K{ZBc)DYlCi6Bm??QPvsOT(=@VX0|r1cF}>Up-eboNAe#G0%%<tWzwW'
    'W6dU-2(`PO)1rC;0~N~j?N&HG{Wmx1qZ_)-?iuD7ST!Lm!X0#GVw-eK{GA0%8x(K|adzWMWhLlWKq&oWQw|<?hgAa(flcdKT>UNN'
    '{j=FI9~I+j7;EBBXCN}KKOSqH(V$ZjG-c=n4g&5I9GS3~?!3d_$qd<`<?_Nw#OOgE6UXHx?7j|Rt-l;Czd|DAP+pu<0kPvfKltQ?'
    'YwK-Z$iA4a86@P5{h~4X@#G)l=cf#8`_oo<S=C|kg$*Eu^>W`T>RpC>0M$zsDDo$ajL9KV;$e)%>1Fqn1LCRKqPtS>`n{sn`3PhX'
    'mQCme6?r{%<}O?y%+v?Fmg$=aQr&iNZQ^IV^rdr{nYEAxJBJlh&=syagaFqR$ws<6<f<I(9JVFA2v+e=x$(LXCyqPMZY^S0SDMlN'
    ')xf6n$=yYpus=i)X~h~<{1C5%wp{}2?|SO51~=nD-K^Njlakp#bJrirmz2#Idb-9gNq&`Xx}jd(z5?6LrG(6*>!@D$bD@-0F?f%<'
    '!+~4!ZvIeAH%!b{@;~>!%KOF=z2~T4{AL)iQ|@z%;G+buZ=+Va^kZ?-s?~8PxxaS!?Rah{dvpI<gvNjif%;;&4j`QlTvgK>2T8UM'
    'Mxnlxx(xdoo{+kF{MiSl9ltA|JOJ_N-ocb?lsI-MuM$@+vGN-jP01CY?!dUaTL8B007-GbYvbG@v8?w7e1YSlD5DUw#V+g_Yt|5{'
    '(hTyL)S$|)N^W{=pu*lVI=$OgQFs0|EGWqpaHP&LhdgM#1n$Q_vR)4GPog05BIh?^Cl9HcQu6PyX^EGvd0|USKQGugpaW7f@r3Uc'
    '?$%(6x9G+8F*8$8E5vaR1<>#f3G^n|0W?nfq<ea1X|9(vSl_wsSFBfQe_)cV5pJG_(V;7RUS?Eqc2L#9Faa!blrV7(Q_}}QE3cN+'
    'gdHw|2)RB>UxK9sq%z~0bG>*EJ5jNB!yz}_c3_&6a6FD{D4P(c;50agU;tT7S`z9^oM)Fps(3-oL;6mu8?kTkyQH!;8|ZG?d}1Cy'
    '*&_rjdHQ6&aF2v=S<6@SZ8+;MJq~C>AHD1n)opmIyR`040!+!g^HVx;s&GV(O86#EI^u&5=j7dZ>+2aET@E!vDiCv;LXM)EuKq2#'
    'Ilf`1!FD{%uYv$QRE)Z&M`?K8_4vCeL2$8~DEgm8!Gkl~-d@BXn<0cg`Y*Jw!E&+Mg^1Q3fTUNV;43~s_|2d*y{9B!{sK$Ic7t8b'
    'ErEKcWG{%fFmmH;6OJlxe8^VhMwt|kwD3)H)O-G`PLI=b4firw*@|fy2@x8;1A&Bdx9aa8C|~FS-s)IGou*x+izxC>LRZwsR6M1='
    '^RqN5+j}|T6Any!0P{>~lTFiH(r1Y9AM<C(*(D2PXP~(usR*=^+qM*}*H%qu48FZN1Seri(nVDC8ZIwHf$uYmT*KP%WZFN(2SoDP'
    ';;``l0bA2-EY^kzd7kR<^4yt~&x)-y9(&Zr3-vEW+}h%c5ZYgJ<Es*eR_<n7WQi-9TL((jlOx!6NtBVQ#k_F6ZZ;1f>AaJaIEoMo'
    'Br{?Ht&8m3DxEwk_t2Kq;ADR;tvqEn8{*aG`qm#wwp{&=$|o%e?PSlP8>yz~J2GoU>-uUAfJbUKk%zIfgHFR^J9ld*aER6poV<j!'
    '81gH=<cdVRz_@n#<F5uEssnNV@z5@85N@r?AX64JouwW}pvs|4%*ppou?*k{OW9dAo}M%c(r|q9e4XEt<d8@6=?EnV+)?%AP|Z7u'
    '0l>O9XSjmJc3Hk2ZZUH$)ujeo@O~L5KA+|lv>7Ioa`EHzWEQd}?PkBpcqJ;}2ikhvxDfHzS>uT^6UFxuPaEFh)vMGhl_C&LngPoy'
    'S&J~2e<HmHpa)jdpBaO#efxfj7$8O&5a;EQH1UHRguZ2o{AH#N1IhBaEf&^g7N;EFth(g~NE%y};D5XnX)-IF;F`tw6n*tN_&&?L'
    'SOFsSVi{>FT$>j}A-g5g#z|mJ?sv(z_(KXMH>9SX?|YQMNjAGa3?7s<cX1XD%!m<0B)nRmcX7&F;sZa-_YaSTFhMMt*i%v#M|_Ae'
    'Av@+CWxTA8h{U-+a@YfPo1hO+`SS`MMlAxLPC3>tnPIj1+GoAf^H<VsWb*56slz53VVmp`&Wg?Fg{>5$h|3R2ZJ4v`mcy0~<IY(&'
    '?U>mzC|3$*z9OLqU@${V@*_c0o(j8Qb#AV`fShD^rc1CjyBTiKM#nIlS2ERo1~Xv7HJ6%+=B#<&Md{X&sjJ=5lAXUd@_juCQW_OB'
    'a4nZNS<vtPqQVbzf2|!DON<IQ7F+>bO*AL?R8YCVUI<%ZNQ*g)Lt6vH?DM_+M+u;qN3<K<gkEq>$Og*ftsicv4Z_AI#qI?!Mc=gd'
    '_=s8)7`jE)&`(9yeN6dOuw~nmD1Z2NcrXlFAn6nFT(5ED)Ym!)1}yg5kR;~ZOC8k4feN1CxbkK$2ROd}=_ag`O0Q4--c37|3g8VX'
    'n32v$?z9RxYtz`pqa@ar4GdFz!HUnD>vw+Fwi)&+a;C?2R#Ox}ozdO@GQ+G^L|r>MsAjNozsGbAu0w)#nUa;i%&1q7WV5sihap58'
    '=lHwZt2p^gVacaFos1w?7O<@HP_-F?6B*@eOz2~{q*X&vRUn;-ss?4w1%lMQ?!bqRin7^U6v=Mpv`fFYm1;68a*Q4G6oqn+`LC~C'
    'ETaJazDD1OwjNE0NfM&Qf2c;Q(^<nL=^!0p$HNiUgn~lucf9rsif?<DS;kc<B9Iq>1}wBwx()L&4lS?YvZav5cQ&?GyRZh7N+lEL'
    '`;-qr-m3Na=AbpNRwBKE_y_E(UhnqP-t>H!ql6cz?kGpXo^f_1l*@rG7wK>l-N6FfY1v237Qv5-Iu{#|Ew1VaGi+YIn&N+yqPb=3'
    '86}=3#P2lxdJ9lJ3HPNDm!AVwOB-gzjPT{mA)82d--w*9m^wxyVGxq70tF8cX2bhe9`_Qzh9g~pOcgUh>4|8TdpAg=Tr7x8PbD0F'
    'hF61<