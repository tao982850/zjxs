#!/usr/bin/python
# -*- coding: utf-8 -*-@猪猪
r"""
柚子视频 TVBox Spider (yznb 壳站适配版 v3 - TVBox 引擎兼容修复)
=============================================================
目标站点: https://yznb.4y5u.cc/?channel=1K7uu2Dq
Compatible: FongMi/TV (T3) + WebHomeTV / PeekPro (T4)

【v3 修复内容 - 解决 "无法加载" / 加载后空的兼容问题】
1. 不再调用引擎基类 self.fetch(): 不同 TVBox 引擎对 fetch 的参数
   (data= / method=) 与返回类型 (bytes / .text 对象) 实现不一致,
   直接依赖它会导致 ImportError 后 init 抛异常 -> 整源无法加载。
   改为内部用 urllib.request 直连 (各大引擎标准库都有 urllib)。
2. _post 统一读 bytes 再 base64 解码, 无歧义。
3. 全部对外接口 try/except 兜底, init 失败也只降级不抛错。
4. 移除引擎环境里可能不存在/不稳定的 lxml、requests 依赖。

【站点协议要点 (逆向自前端主 JS)】
* 页面是 Vue SPA 壳, 数据全走加密 POST:
      POST /api/xxx
      Content-Type: text/plain
      body = base64( iv(12) || AES-GCM密文 || tag(16) )
      响应 = base64( iv(12) || 密文 || tag(16) )
* AES-128-GCM key 硬编码在前端 JS: "0e3d2cf6f78dc8d8" (UTF-8 16字节)
* 播放地址每次实时发放 (带 token+expire), 播放时必须现取
"""
import sys
import json
import base64
import re as _re
import threading
import urllib.request
import urllib.parse
import ssl

try:
    sys.path.append('..')
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object


# =====================================================================
# 内嵌 AES-128-GCM (纯标准库, 已对拍权威实现; 教学版见 aesgcm.py)
# =====================================================================
_SBOX = (
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16)


def _xt(a):
    a <<= 1
    return (a ^ 0x11B) & 0xFF if a & 0x100 else a & 0xFF


_M2 = tuple(_xt(x) & 0xFF for x in range(256))
_M3 = tuple((x ^ _xt(x)) & 0xFF for x in range(256))


def _gm(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r & 0xFF


_M9 = tuple(_gm(x, 9) for x in range(256))
_MB = tuple(_gm(x, 0x0B) for x in range(256))
_MD = tuple(_gm(x, 0x0D) for x in range(256))
_ME = tuple(_gm(x, 0x0E) for x in range(256))


def _expand(key):
    key = list(key)
    rcon, rks = 1, [key[:]]
    for _ in range(10):
        w0, w1, w2, w3 = key[0:4], key[4:8], key[8:12], key[12:16]
        t = [_SBOX[b] for b in (w3[1:] + w3[:1])]
        t[0] ^= rcon
        rcon = _xt(rcon)
        k0 = [w0[i] ^ t[i] for i in range(4)]
        k1 = [w1[i] ^ k0[i] for i in range(4)]
        k2 = [w2[i] ^ k1[i] for i in range(4)]
        k3 = [w3[i] ^ k2[i] for i in range(4)]
        key = k0 + k1 + k2 + k3
        rks.append(key[:])
    return rks


def _sr(s):
    return [s[0], s[5], s[10], s[15], s[4], s[9], s[14], s[3],
            s[8], s[13], s[2], s[7], s[12], s[1], s[6], s[11]]


def _mc(s):
    m2, m3 = _M2, _M3
    return [m2[s[0]] ^ m3[s[1]] ^ s[2] ^ s[3], s[0] ^ m2[s[1]] ^ m3[s[2]] ^ s[3],
            s[0] ^ s[1] ^ m2[s[2]] ^ m3[s[3]], m3[s[0]] ^ s[1] ^ s[2] ^ m2[s[3]],
            m2[s[4]] ^ m3[s[5]] ^ s[6] ^ s[7], s[4] ^ m2[s[5]] ^ m3[s[6]] ^ s[7],
            s[4] ^ s[5] ^ m2[s[6]] ^ m3[s[7]], m3[s[4]] ^ s[5] ^ s[6] ^ m2[s[7]],
            m2[s[8]] ^ m3[s[9]] ^ s[10] ^ s[11], s[8] ^ m2[s[9]] ^ m3[s[10]] ^ s[11],
            s[8] ^ s[9] ^ m2[s[10]] ^ m3[s[11]], m3[s[8]] ^ s[9] ^ s[10] ^ m2[s[11]],
            m2[s[12]] ^ m3[s[13]] ^ s[14] ^ s[15], s[12] ^ m2[s[13]] ^ m3[s[14]] ^ s[15],
            s[12] ^ s[13] ^ m2[s[14]] ^ m3[s[15]], m3[s[12]] ^ s[13] ^ s[14] ^ m2[s[15]]]


def _enc(block, rks):
    s = [block[i] ^ rks[0][i] for i in range(16)]
    for rk in rks[1:10]:
        s = [_SBOX[b] for b in s]
        s = _sr(s)
        s = _mc(s)
        s = [s[i] ^ rk[i] for i in range(16)]
    s = [_SBOX[b] for b in s]
    s = _sr(s)
    return bytes([s[i] ^ rks[10][i] for i in range(16)])


# ---- AES 解密方向 (供封面 CBC 链路的解密块使用) ----
_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i


def _isr(s):
    """InvShiftRows"""
    return [s[0], s[13], s[10], s[7], s[4], s[1], s[14], s[11],
            s[8], s[5], s[2], s[15], s[12], s[9], s[6], s[3]]


def _imc(s):
    """InvMixColumns (乘 9/11/13/14 表已有: _M9/_MB/_MD/_ME)"""
    m9, mb, md, me = _M9, _MB, _MD, _ME
    return [me[s[0]] ^ mb[s[1]] ^ md[s[2]] ^ m9[s[3]], m9[s[0]] ^ me[s[1]] ^ mb[s[2]] ^ md[s[3]],
            md[s[0]] ^ m9[s[1]] ^ me[s[2]] ^ mb[s[3]], mb[s[0]] ^ md[s[1]] ^ m9[s[2]] ^ me[s[3]],
            me[s[4]] ^ mb[s[5]] ^ md[s[6]] ^ m9[s[7]], m9[s[4]] ^ me[s[5]] ^ mb[s[6]] ^ md[s[7]],
            md[s[4]] ^ m9[s[5]] ^ me[s[6]] ^ mb[s[7]], mb[s[4]] ^ md[s[5]] ^ m9[s[6]] ^ me[s[7]],
            me[s[8]] ^ mb[s[9]] ^ md[s[10]] ^ m9[s[11]], m9[s[8]] ^ me[s[9]] ^ mb[s[10]] ^ md[s[11]],
            md[s[8]] ^ m9[s[9]] ^ me[s[10]] ^ mb[s[11]], mb[s[8]] ^ md[s[9]] ^ m9[s[10]] ^ me[s[11]],
            me[s[12]] ^ mb[s[13]] ^ md[s[14]] ^ m9[s[15]], m9[s[12]] ^ me[s[13]] ^ mb[s[14]] ^ md[s[15]],
            md[s[12]] ^ m9[s[13]] ^ me[s[14]] ^ mb[s[15]], mb[s[12]] ^ md[s[13]] ^ m9[s[14]] ^ me[s[15]]]


def _dec(block, rks):
    """解密一个 16 字节块"""
    s = [block[i] ^ rks[10][i] for i in range(16)]
    for rk in rks[9:0:-1]:
        s = _isr(s)
        s = [_INV_SBOX[b] for b in s]
        s = [s[i] ^ rk[i] for i in range(16)]
        s = _imc(s)
    s = _isr(s)
    s = [_INV_SBOX[b] for b in s]
    return bytes([s[i] ^ rks[0][i] for i in range(16)])


def _cbc_decrypt(key, iv, data):
    """AES-128-CBC 解密 (纯标准库, 去 PKCS7 填充)"""
    if not data or len(data) % 16 != 0:
        return None
    rks = _expand(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        p = _dec(blk, rks)
        out += bytes(a ^ b for a, b in zip(p, prev))
        prev = blk
    pad = out[-1] if out else 0
    if 0 < pad <= 16 and all(b == pad for b in out[-pad:]):
        out = out[:-pad]
    return bytes(out)


def _gcm_mul(x, H):
    v, z = H, 0
    for i in range(127, -1, -1):
        if (x >> i) & 1:
            z ^= v
        v = (v >> 1) ^ (0xE1 << 120) if (v & 1) else (v >> 1)
    return z


def _ghash(blocks, H):
    Y = 0
    for blk in blocks:
        Y = _gcm_mul(Y ^ int.from_bytes(blk, 'big'), H)
    return Y.to_bytes(16, 'big')


def _aesgcm(key, iv, data, decrypt=True):
    """标准 AES-GCM: decrypt 处理 [ct||tag]=>明文; encrypt 返回 [ct||tag]"""
    rks = _expand(key)
    H = int.from_bytes(_enc(bytes(16), rks), 'big')
    if len(iv) == 12:
        j0 = iv + b'\x00\x00\x00\x01'
    else:
        p = iv + b'\x00' * ((16 - len(iv) % 16) % 16)
        bs2 = [p[i:i + 16] for i in range(0, len(p), 16)]
        bs2.append((0).to_bytes(8, 'big') + (8 * len(iv)).to_bytes(8, 'big'))
        j0 = _ghash(bs2, H)

    def _ctr_keystream(length):
        out, ctr = b'', j0[:12] + ((int.from_bytes(j0[12:], 'big') + 1) & 0xFFFFFFFF).to_bytes(4, 'big')
        while len(out) < length:
            out += _enc(ctr, rks)
            ctr = ctr[:12] + ((int.from_bytes(ctr[12:], 'big') + 1) & 0xFFFFFFFF).to_bytes(4, 'big')
        return out

    if decrypt:
        ct, tag = data[:-16], data[-16:]
        ks = _ctr_keystream(len(ct))
        out = bytes(a ^ b for a, b in zip(ct, ks))
        gdata = ct
    else:
        pt = data
        ks = _ctr_keystream(len(pt))
        out = bytes(a ^ b for a, b in zip(pt, ks))
        gdata = out
    blocks = []
    p = gdata + b'\x00' * ((16 - len(gdata) % 16) % 16)
    blocks += [p[i:i + 16] for i in range(0, len(p), 16)]
    blocks.append((0).to_bytes(8, 'big') + (8 * len(gdata)).to_bytes(8, 'big'))
    s = _ghash(blocks, H)
    full_tag = bytes(a ^ b for a, b in zip(s, _enc(j0, rks)))[:16]
    if decrypt:
        if full_tag != tag:
            raise ValueError('GCM auth failed')
        return out
    return out + full_tag   # ct || tag
# =====================================================================


# =====================================================================
# 封面本地解密代理 (v4 新增)
# 站点封面 .bin 是 AES-GCM 密文 / .log 是 AES-CBC 密文, TVBox 原生
# 图片加载器无法解密 -> 黑图。这里在 spider 进程内起一个 127.0.0.1
# HTTP 服务, vod_pic 指向 http://127.0.0.1:{port}/cover?u=原始URL,
# 收到请求后 Python 下载 -> 解密 -> 以真实 JPEG/PNG 字节返回, TVBox
# 把它当普通图片显示。省去 base64 内嵌导致的 3.5MB 巨型 JSON。
# =====================================================================
_COVER_GCM_KEY = bytes.fromhex('7320c9f1f84847fc51c7262af022cec4')
_COVER_GCM_IV = base64.b64decode('FYb65V0QEXdAxexI')
_COVER_CBC_KEY = bytes.fromhex('88ce35562a6f085b53a00145444c445f')
_COVER_CBC_IV = bytes.fromhex('d005d14d7ce6312ae54527a659be2c55')

_cover_port = None
_cover_cache = {}
_cover_lock = threading.Lock()


def _http_get_bytes(url, timeout=12):
    req = urllib.request.Request(url, headers={
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0.0.0 Safari/537.36'),
        'Referer': 'https://yznb.4y5u.cc/',
    })
    ctx = ssl.create_default_context() if ssl else None
    if ctx:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    rsp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
    return rsp.read()


def _decrypt_cover_bytes(raw, is_log):
    """按后缀选择解密: .log -> AES-CBC, 其他(.bin) -> AES-GCM"""
    try:
        if is_log:
            return _cbc_decrypt(_COVER_CBC_KEY, _COVER_CBC_IV, raw)
        return _aesgcm(_COVER_GCM_KEY, _COVER_GCM_IV, raw, decrypt=True)
    except Exception:
        return None


def _resolve_cover(src_url):
    """下载+解密封面, 带内存缓存; 失败返回 None"""
    if not src_url:
        return None
    if src_url in _cover_cache:
        return _cover_cache[src_url]
    try:
        raw = _http_get_bytes(src_url)
        is_log = src_url.lower().endswith('.log')
        img = _decrypt_cover_bytes(raw, is_log)
        if img and (img[:2] == b'\xff\xd8' or img[:8] == b'\x89PNG\r\n\x1a\n'):
            if len(_cover_cache) > 512:
                _cover_cache.clear()
            _cover_cache[src_url] = img
            return img
    except Exception:
        pass
    return None


def _ensure_cover_server():
    """惰性启动封面代理服务, 返回监听端口 (thread-safe)"""
    global _cover_port
    if _cover_port:
        return _cover_port
    import http.server as _hs

    class _Handler(_hs.BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query)
                u = (q.get('u') or [''])[0]
                img = _resolve_cover(u)
                if img:
                    self.send_response(200)
                    self.send_header('Content-Type',
                                     'image/jpeg' if img[:2] == b'\xff\xd8' else 'image/png')
                    self.send_header('Content-Length', str(len(img)))
                    self.send_header('Cache-Control', 'public, max-age=86400')
                    self.end_headers()
                    self.wfile.write(img)
                else:
                    self.send_response(404)
                    self.end_headers()
            except Exception:
                try:
                    self.send_response(500)
                    self.end_headers()
                except Exception:
                    pass

        def log_message(self, *a):
            pass

    with _cover_lock:
        if _cover_port:
            return _cover_port
        try:
            srv = _hs.ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
            th = threading.Thread(target=srv.serve_forever, daemon=True)
            th.start()
            _cover_port = srv.server_address[1]
        except Exception:
            _cover_port = 0
    return _cover_port or 0


def _cover_proxy_url(src_url):
    """把原始封面 URL 替换为本地代理 URL; 无法起服务时原样返回(黑图兜底)"""
    if not src_url or not str(src_url).startswith('http'):
        return src_url or ''
    port = _ensure_cover_server()
    if not port:
        return src_url
    return 'http://127.0.0.1:{}/cover?u={}'.format(port, urllib.parse.quote(src_url, safe=''))


class Spider(_BaseSpider):
    """TVBox Python 源: 柚子视频"""

    DOMAINS = [
        "https://yznb.4y5u.cc",   # 主站
        # "https://yznb.ldvv.cc", # 备用 (实测 401 需校验, 先不用)
    ]
    KEY = b"0e3d2cf6f78dc8d8"     # 前端 JS 硬编码的 AES-128-GCM key (UTF-8)
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Content-Type": "text/plain",
    }

    def getName(self):
        return "柚子视频"

    # ================= 网络层 (纯 urllib, 不依赖引擎基类 fetch) =================
    def _http_post(self, url, body_bytes, timeout=15):
        """POST 加密密文 -> 服务器原始响应 bytes"""
        import urllib.request as _ur
        req = _ur.Request(url, data=body_bytes, method='POST')
        for k, v in self.HEADERS.items():
            req.add_header(k, v)
        try:
            ctx = None
            if ssl:
                try:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                except Exception:
                    ctx = None
            rsp = _ur.urlopen(req, timeout=timeout, context=ctx)
            return rsp.read()
        except Exception:
            try:  # 部分精简环境无 ssl: 再试一次默认传输
                ctx = None
                rsp = _ur.urlopen(req, timeout=timeout, context=None)
                return rsp.read()
            except Exception:
                return b''

    def _post(self, base, path, obj):
        """加密 POST + 解密响应 -> dict; 任何异常返回 {}"""
        try:
            raw = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            iv = bytes(range(1, 13))
            blob = _aesgcm(self.KEY, iv, raw, decrypt=False)      # ct||tag
            body = base64.b64encode(iv + blob).decode()            # iv||ct||tag
            rsp = self._http_post(base + path, body.encode())
            if not rsp:
                return {}
            b = base64.b64decode(rsp)
            if len(b) < 28:
                return {}
            plain = _aesgcm(self.KEY, b[:12], b[12:], decrypt=True)
            return json.loads(plain.decode('utf-8', errors='replace'))
        except Exception:
            return {}

    # ================= 生命周期 =================
    def init(self, extend=""):
        try:
            if isinstance(extend, list):
                self.extend = ''
            else:
                self.extend = extend or ''
            self.baseUrl = self.DOMAINS[0]
            for d in self.DOMAINS:
                try:
                    if self._post(d, '/api/system/info', {}).get('code') == 0:
                        self.baseUrl = d
                        break
                except Exception:
                    continue
        except Exception:
            self.baseUrl = self.DOMAINS[0]
        self.categories = []
        try:
            self._load_categories()
        except Exception:
            pass

    # ================= 分类 =================
    def _load_categories(self):
        """
        只保留"有子分类的父分类"下的叶子分类(实测 53 个, 全部有内容)。
        无 child 的 item 是"运营位/推荐位"(如柚子推荐/最近更新), 其视频
        不走 sublist 接口, 直接加入会导致 TVBox 点击后空白。
        """
        j = self._post(self.baseUrl, '/api/system/menus', {'device': 'h5'})
        data = j.get('data') or {}
        cats = []
        for items in data.values():
            for it in items or []:
                ch = it.get('child') or []
                if ch:                       # 只取叶子分类, 跳过运营位
                    for c in ch:
                        if c.get('id'):
                            cats.append({'type_name': c.get('name'), 'type_id': str(c['id'])})
        seen, out = set(), []
        for c in cats:
            if c['type_id'] not in seen:
                seen.add(c['type_id'])
                out.append(c)
        self.categories = out

    def homeContent(self, filter):
        return {'class': self.categories}

    # ================= 列表 =================
    def _parse_items(self, data):
        lst = data.get('list') or []
        out = []
        for it in lst:
            dur = it.get('duration') or 0
            remark = '{}m'.format(dur // 60) if dur else ''
            out.append({
                'vod_id': str(it.get('id') or ''),
                'vod_name': (it.get('title') or '').strip(),
                'vod_pic': _cover_proxy_url(it.get('cover') or ''),
                'vod_remarks': remark,
            })
        return out

    def _default_typeid(self):
        for c in self.categories:
            if c['type_name'] in ('每日更新', '最近更新', '柚子推荐'):
                return c['type_id']
        return self.categories[0]['type_id'] if self.categories else '0'

    def homeVideoContent(self):
        try:
            tid = self._default_typeid()
            j = self._post(self.baseUrl, '/api/movie/sublist/v2',
                           {'typeid': int(tid), 'page': 1, 'page_size': 20})
            return {'list': self._parse_items(j.get('data') or {})}
        except Exception:
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg or 1)
            j = self._post(self.baseUrl, '/api/movie/sublist/v2',
                           {'typeid': int(tid), 'page': pg, 'page_size': 20})
            data = j.get('data') or {}
            total_page = min(int(data.get('total_page') or 1) or 1, 5000)
            return {
                'list': self._parse_items(data),
                'page': pg,
                'pagecount': total_page,
                'limit': 20,
                'total': total_page * 20,
            }
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 20, 'total': 0}

    # ================= 详情 =================
    def detailContent(self, ids):
        try:
            if isinstance(ids, list):
                ids = ids[0] if ids else ''
            vid = str(ids)
            j = self._post(self.baseUrl, '/api/movie/detail/v2', {'id': int(vid)})
            data = j.get('data') or {}
            vod = {
                'vod_id': vid,
                'vod_name': (data.get('title') or '').strip(),
                'vod_pic': _cover_proxy_url(data.get('cover') or ''),
                'vod_content': data.get('desc') or '',
                'vod_play_from': '柚子',
                'vod_play_url': '第1集${}'.format(vid),
            }
            return {'list': [vod]}
        except Exception:
            return {'list': []}

    # ================= 搜索 =================
    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg or 1)
            j = self._post(self.baseUrl, '/api/movie/search',
                           {'keywords': str(key), 'module': 1, 'page': pg, 'page_size': 20})
            data = j.get('data') or {}
            items = self._parse_items(data)
            return {
                'list': items,
                'page': pg,
                'pagecount': min(int(data.get('total_page') or 1) or 1, 5000),
                'limit': 20,
                'total': len(items) or 0,
            }
        except Exception:
            return {'list': []}

    # ================= 播放 =================
    def playerContent(self, flag, id, vipFlags):
        try:
            if not id:
                return {"parse": 1, "playUrl": "", "url": ""}
            sid = str(id)
            if sid.isdigit():
                j = self._post(self.baseUrl, '/api/movie/play', {'id': int(sid)})
                u = (j.get('data') or {}).get('play_url') or ''
                if u:
                    return {"parse": 0, "playUrl": "", "url": u,
                            "header": self.HEADERS}
                return {"parse": 1, "playUrl": "", "url": id}
            if sid.startswith('http') and _re.search(r'\.(m3u8|mp4|flv)([?#]|$)', sid, _re.I):
                return {"parse": 0, "playUrl": "", "url": sid,
                        "header": self.HEADERS}
            return {"parse": 1, "playUrl": "", "url": id}
        except Exception:
            return {"parse": 1, "playUrl": "", "url": id}

    def localProxy(self, param):
        yield [200, "video/MP2T", b"", ""]

    def destroy(self):
        pass

    def close(self):
        self.destroy()