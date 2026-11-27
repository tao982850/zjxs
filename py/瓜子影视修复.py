# -*- coding: utf-8 -*-
# ============ 瓜子影视 (apinew.uozvr.com 系) TVBox/影视 Python Spider ============
# 修复要点(2026-11-27，针对影视 5.9.0 无法播放)：
# 1) 移除 pycryptodome(Crypto) 依赖：改纯 Python AES-128-CBC + RSA PKCS#1 v1.5。
#    5.9.0 内置运行时若不带 Crypto，原版 import 阶段就会失败，整个源不可用。
# 2) 不再调用宿主 self.post/self.fetch：改用标准库 urllib 自建会话，宿主接口调整不再影响取数。
# 3) 设备注册/token 改为首次取数时懒加载，并在进程内缓存；__init__ 不再联网。
#    原版每个实例都随机新设备并注册，5.9.0 多次创建实例时容易互相顶掉 token。
# 4) playerContent 返回严格 {header(dict), parse(int), url}，不再带 playUrl/danmaku，
#    header 由 JSON 字符串改为 dict（5.9.0 按对象解析 header）。
# 5) 所有业务方法签名兼容 (*args/**kwargs)，detail/search/category 的调用差异不再抛 TypeError。
# 6) 失效域名自动标记跳过，减少无效超时。
# 兼容 Python 3.8 及以下；只依赖标准库。
import os
import sys
import re
import json
import time
import base64
import hashlib
import random
import threading
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar
import ssl

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider(object):  # 独立加载兜底
        pass

# ============ 纯 Python AES-128-CBC（已与 pycryptodome 逐字节比对一致） ============
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


# ============ 常量 ============
HOSTS = [
    'https://apinew.uozvr.com',
    'https://api.w32z7vtd.com',
    'https://api.6a7nnf7.com',
    'https://api.umygrx3.com',
    'https://api.rmedphk.com',
]
UA_API = 'Lavf/57.83.100'
AES_KEY = 'OITxa5OqAYjhswxx'
AES_IV = 'rCMNwZASNBKZ8mXV'
DEVICE_OLD_KEY = 'aLFBMWpxBrIDAD1Si/KVvm41'
SIGN_SALT = '*&zvdvdvddbfikkkumtmdwqppp?|4Y!s!2br'
PLAY_UA = 'Lavf/57.83.100'
PLAY_REFERER = 'http://WJiZxLXA2.com/'

# 站点 RSA 公钥(加密上行 keys) 与私钥参数(解密下行 keys)，纯 Python 实现所需
RSA_PUB_N = 149013070621003984547411160938499700487541859606110279972200736037159005716014895153867975040719089585023012518424553261128812943841848718995213365484965317547916226801531888527182183041430878870695925676750712685734528007530643107330999993038684915173332127622892497488948493805722501715586491687170583099593
RSA_PUB_E = 65537
RSA_PRV_N = 86835171934457883218226481603142841802382529617454170469875921992613490226620814782694491115863700040099322813171701421315131514014072867238848526091654339989912503715114842257634922876570298884299434457354597032563958533395403961772046498020341233714771737538464523984812725644118954006393119345267966014861
RSA_PRV_D = 1601900039195562519047802253050943676687679910699331554664998240521685607885386347746732986848333206409815543603225460707233989966629752605272866747712133209259986055807924788806672558787264037851384281159999683342543155756771488386452212462444351587479425262746678733929064591659478717778272985792519644957


def _i2b(x):
    if x == 0:
        return b'\x00'
    return x.to_bytes((x.bit_length() + 7) // 8, 'big')


def _rand_nonzero():
    while True:
        b = os.urandom(1)[0]
        if b:
            return b


def rsa_encrypt_text(text, n=RSA_PUB_N, e=RSA_PUB_E):
    """RSA PKCS#1 v1.5 加密，返回 base64（等价 pycryptodome PKCS1_v1_5.encrypt）。"""
    k = (n.bit_length() + 7) // 8
    msg = text.encode('utf-8') if isinstance(text, str) else text
    if len(msg) > k - 11:
        msg = msg[:k - 11]
    ps = bytes([_rand_nonzero() for _ in range(k - 3 - len(msg))])
    em = b'\x00\x02' + ps + b'\x00' + msg
    c = pow(int.from_bytes(em, 'big'), e, n)
    return base64.b64encode(_i2b(c).rjust(k, b'\x00')).decode('ascii')


def rsa_decrypt_text(b64, n=RSA_PRV_N, d=RSA_PRV_D):
    """RSA PKCS#1 v1.5 解密，入参 base64/bytes，返回 bytes。"""
    k = (n.bit_length() + 7) // 8
    if isinstance(b64, str):
        raw = base64.b64decode(b64 + '=' * (-len(b64) % 4))
    else:
        raw = b64
    c = int.from_bytes(raw, 'big')
    em = _i2b(pow(c, d, n)).rjust(k, b'\x00')
    if len(em) < 11 or em[0] != 0 or em[1] != 2:
        raise ValueError('RSA padding error')
    idx = em.find(b'\x00', 2)
    if idx < 0:
        raise ValueError('RSA delimiter missing')
    return em[idx + 1:]


class _Http(object):
    """标准库会话：不依赖宿主的 post/fetch，也不依赖 requests。"""

    def __init__(self):
        self.lock = threading.RLock()
        self.cj = http.cookiejar.CookieJar()
        self._noverify = False
        self.op = self._build()

    def _build(self):
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

    def _open(self, url, headers=None, data=None, timeout=12):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            try:
                resp = self.op.open(req, timeout=timeout)
            except Exception as e1:
                if (not self._noverify) and ('CERTIFICATE_VERIFY_FAILED' in str(e1) or isinstance(e1, ssl.SSLError)):
                    self._noverify = True
                    self.op = self._build()
                    req = urllib.request.Request(url, data=data, headers=headers or {})
                    resp = self.op.open(req, timeout=timeout)
                else:
                    raise
            return resp.getcode(), resp.read()
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b''
            return e.code, body
        except Exception:
            return 0, b''

    def post_form(self, url, headers, data, timeout=12):
        body = urllib.parse.urlencode(data).encode('utf-8')
        hd = dict(headers or {})
        hd.setdefault('Content-Type', 'application/x-www-form-urlencoded')
        with self.lock:
            return self._open(url, hd, body, timeout)

    def get(self, url, headers=None, timeout=12):
        with self.lock:
            return self._open(url, headers or {}, None, timeout)


class Spider(Spider):
    # 进程级 token 缓存：同一 Python 进程内多实例共用，避免重复注册互相顶掉 token
    _AUTH_LOCK = threading.RLock()
    _AUTH = {'token': '', 'token_id': '', 'device_id': '', 'device_key': '', 'registered': False}
    _DEAD_HOSTS = set()

    def __init__(self):
        self.name = '瓜子'
        self.hosts = list(HOSTS)
        self.host_index = 0
        self.host = self.hosts[0]
        self.AES_KEY = AES_KEY
        self.AES_IV = AES_IV
        self.DEVICE_OLD_KEY = DEVICE_OLD_KEY
        self.deviceId = ''
        self.deviceKey = ''
        self.token = ''
        self.token_id = ''
        self._http = _Http()
        self.cache = {}
        self.cache_timeout = 300
        self._last_net_error = False
        self.header = {
            'User-Agent': UA_API,
            'code': 'GZ0369',
            'lang': 'zh_cn',
            'Cache-Control': 'no-cache',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Version': '2604028',
            'PackageName': 'com.ae06aebdbb.y286327f5a.ofe849883320260517',
            'Ver': '3.0.3.2',
            'api-ver': '3.0.3.2',
        }

    # ---------- 宿主生命周期 ----------
    def getName(self):
        return self.name

    def init(self, extend=''):
        # 不在 init/__init__ 联网：token 首次取数时再申请
        try:
            if extend and isinstance(extend, str) and '{' in extend:
                j = json.loads(extend)
                h = j.get('host') or j.get('api')
                if h and str(h).startswith('http'):
                    self.hosts.insert(0, str(h).rstrip('/'))
                    self.host = self.hosts[0]
        except Exception:
            pass

    def destroy(self):
        self.cache.clear()

    # ---------- 认证 ----------
    def _device(self):
        with Spider._AUTH_LOCK:
            if not Spider._AUTH.get('device_id'):
                Spider._AUTH['device_id'] = str(864150060000000 + random.randint(0, 9999))
                Spider._AUTH['device_key'] = ''.join(random.choices('0123456789ABCDEF', k=40))
            self.deviceId = Spider._AUTH['device_id']
            self.deviceKey = Spider._AUTH['device_key']
        self.header['deviceId'] = self.deviceId

    def _apply_auth(self, result):
        token = (result or {}).get('token', '')
        if not token:
            raise Exception('认证失败，无 token 返回')
        self.token = token
        tid = (result or {}).get('app_user_id', '')
        if tid:
            self.token_id = str(tid)
        with Spider._AUTH_LOCK:
            Spider._AUTH['token'] = self.token
            Spider._AUTH['token_id'] = self.token_id
            Spider._AUTH['registered'] = True

    def _ensure_token(self, force=False):
        with Spider._AUTH_LOCK:
            if not force and Spider._AUTH.get('token') and Spider._AUTH.get('token_id'):
                self.token = Spider._AUTH['token']
                self.token_id = Spider._AUTH['token_id']
                if Spider._AUTH.get('device_id'):
                    self.deviceId = Spider._AUTH['device_id']
                    self.deviceKey = Spider._AUTH['device_key']
                    self.header['deviceId'] = self.deviceId
                return True
            self._device()
            ok = False
            for fn in (self.sign_in, self.sign_up):
                try:
                    r = fn()
                    if r and r.get('token'):
                        self._apply_auth(r)
                        ok = True
                        break
                except Exception as e:
                    print('认证步骤失败: %s' % e)
            if not ok:
                return False
            try:
                self.refresh_token()
            except Exception as e:
                print('刷新 token 失败: %s' % e)
            return bool(self.token and self.token_id)

    def sign_up(self):
        params = {'new_key': self.deviceKey, 'old_key': self.DEVICE_OLD_KEY, 'phone_type': 1, 'code': ''}
        return self._send_encrypted_request(params, '/App/Authentication/Device/signUp', is_auth=True)

    def sign_in(self):
        params = {'new_key': self.deviceKey, 'old_key': self.DEVICE_OLD_KEY}
        return self._send_encrypted_request(params, '/App/Authentication/Device/signIn', is_auth=True)

    def refresh_token(self):
        return self._send_encrypted_request({}, '/App/Authentication/Authenticator/refresh', is_auth=True)

    # ---------- 加密请求 ----------
    def _send_encrypted_request(self, data, path, is_auth=False):
        try:
            if (not is_auth) and not self._ensure_token():
                return None
            request_key = self.aes_cbc_encrypt(json.dumps(data, separators=(',', ':'), ensure_ascii=False))
            keys = rsa_encrypt_text(json.dumps({'iv': self.AES_IV, 'key': self.AES_KEY}))
            t = str(int(time.time()))
            sign_str = ('token_id=,token=%s,phone_type=1,request_key=%s,app_id=1,time=%s,keys=%s%s'
                        % (self.token, request_key, t, keys, SIGN_SALT))
            signature = hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()
            body = {
                'token': self.token,
                'token_id': '',
                'phone_type': '1',
                'time': t,
                'phone_model': 'xiaomi-25031',
                'keys': keys,
                'request_key': request_key,
                'signature': signature,
                'app_id': '1',
                'ad_version': '1',
            }
            self.header['Referer'] = self.host
            code, raw = self._http.post_form(self.host + path, self.header, body, timeout=12)
            if code == 0:
                self._last_net_error = True
                return None
            self._last_net_error = False
            if code != 200:
                print('HTTP %s [%s]' % (code, path))
                return None
            resp = json.loads(raw.decode('utf-8', 'ignore'))
            if isinstance(resp, dict) and resp.get('code') not in (None, 200):
                print('业务错误码 %s [%s]' % (resp.get('code'), path))
                return None
            section = (resp or {}).get('data') or {}
            resp_key = section.get('response_key') or ''
            resp_keys = section.get('keys') or ''
            if not resp_key or not resp_keys:
                print('响应缺少 data/keys [%s]' % path)
                return None
            info = json.loads(rsa_decrypt_text(resp_keys).decode('utf-8', 'ignore'))
            plain = self.aes_cbc_decrypt(resp_key, info.get('key') or '', info.get('iv') or '')
            return json.loads(plain)
        except Exception as e:
            print('请求失败 [%s]: %s' % (path, e))
            return None

    def get_data(self, data, path, use_cache=True):
        cache_key = '%s_%s' % (path, hash(json.dumps(data, sort_keys=True, ensure_ascii=False))) if use_cache else None
        if cache_key and cache_key in self.cache:
            cached, ts = self.cache[cache_key]
            if time.time() - ts < self.cache_timeout:
                return cached
        for attempt in range(3):
            for _ in range(len(self.hosts)):
                if self.host_index >= len(self.hosts):
                    self.host_index = 0
                self.host = self.hosts[self.host_index]
                if self.host in Spider._DEAD_HOSTS:
                    self.host_index = (self.host_index + 1) % len(self.hosts)
                    continue
                result = self._send_encrypted_request(data, path)
                if result is not None:
                    if cache_key:
                        self.cache[cache_key] = (result, time.time())
                    return result
                if self._last_net_error:
                    Spider._DEAD_HOSTS.add(self.host)
                self.host_index = (self.host_index + 1) % len(self.hosts)
            if attempt < 2:
                try:
                    self._ensure_token(force=True)
                except Exception:
                    pass
                self.host_index = 0
            else:
                break
        return None

    # ---------- 加解密 ----------
    def aes_cbc_encrypt(self, text):
        key = self.AES_KEY.encode('utf-8')
        iv = self.AES_IV.encode('utf-8')
        return aes_cbc(text.encode('utf-8'), key, iv, 1).hex().upper()

    def aes_cbc_decrypt(self, hex_text, key, iv):
        if not key or not iv:
            raise ValueError('AES key/iv missing')
        return aes_cbc(bytes.fromhex(hex_text), key.encode('utf-8'), iv.encode('utf-8'), 0).decode('utf-8', 'ignore')

    def get_md5(self, text):
        return hashlib.md5(text.encode('utf-8')).hexdigest().upper()

    # ---------- 业务接口 ----------
    def homeContent(self, filter=False, *args, **kwargs):
        classes = [
            {'type_name': '电影', 'type_id': '1'},
            {'type_name': '电视剧', 'type_id': '2'},
            {'type_name': '动漫', 'type_id': '4'},
            {'type_name': '综艺', 'type_id': '3'},
            {'type_name': '短剧', 'type_id': '64'},
        ]
        areas = [{'n': '全部', 'v': '0'}] + [{'n': x, 'v': x} for x in
                                           ['大陆', '香港', '台湾', '美国', '韩国', '日本', '英国', '法国', '泰国', '印度', '其他']]
        years = [{'n': '全部', 'v': '0'}] + [{'n': y, 'v': y} for y in [str(x) for x in range(2025, 2004, -1)]]
        sorts = [{'n': '最新', 'v': 'd_id'}, {'n': '最热', 'v': 'd_hits'}, {'n': '推荐', 'v': 'd_score'}]
        filters = {}
        for c in classes:
            filters[c['type_id']] = [
                {'key': 'area', 'name': '地区', 'value': areas},
                {'key': 'year', 'name': '年份', 'value': years},
                {'key': 'sort', 'name': '排序', 'value': sorts},
            ]
        return {'class': classes, 'filters': filters}

    def homeVideoContent(self, *args, **kwargs):
        return {'list': []}

    def categoryContent(self, tid='1', pg=1, filter=False, extend=None, *args, **kwargs):
        videos = []
        pn = self._to_int(pg) or 1
        total, pagecount = 0, 1
        try:
            ext = self._norm_extend(extend)
            body = {
                'area': ext.get('area', '0') or '0',
                'year': ext.get('year', '0') or '0',
                'pageSize': '30',
                'sort': ext.get('sort', 'd_id') or 'd_id',
                'page': str(pn),
                'tid': str(tid),
            }
            data = self.get_data(body, '/App/IndexList/indexList')
            if data and isinstance(data.get('list'), list):
                for item in data['list']:
                    videos.append(self._item_to_video(item))
            if data:
                total = self._to_int(data.get('total'))
                pagecount = self._to_int(data.get('pageCount')) or 9999
            else:
                pagecount = 1
        except Exception as e:
            print('获取分类失败: %s' % e)
        return {'list': videos, 'page': pn, 'pagecount': pagecount, 'limit': 30, 'total': total or len(videos)}

    @staticmethod
    def _norm_extend(extend):
        if isinstance(extend, dict):
            return extend
        if isinstance(extend, str) and extend.strip().startswith('{'):
            try:
                return json.loads(extend)
            except Exception:
                return {}
        return {}

    @staticmethod
    def _to_int(v):
        try:
            return int(v)
        except Exception:
            return 0

    def _item_to_video(self, item):
        cont = self._to_int(item.get('vod_continu', 0))
        remarks = '电影' if cont <= 0 else '更新至%d集' % cont
        return {
            'vod_id': '%s/%s' % (item.get('vod_id', ''), cont),
            'vod_name': item.get('vod_name', ''),
            'vod_pic': item.get('vod_pic', ''),
            'vod_remarks': remarks,
        }

    def detailContent(self, ids=None, *args, **kwargs):
        try:
            if isinstance(ids, (list, tuple)):
                raw = str(ids[0]) if ids else ''
            else:
                raw = str(ids or '')
            vod_id = raw.split('/')[0].strip()
            if not vod_id:
                return {'list': []}
            qdata = self.get_data({'token_id': self.token_id, 'vod_id': vod_id,
                                   'mobile_time': str(int(time.time())), 'token': self.token},
                                  '/App/IndexPlay/playInfo')
            jdata = self.get_data({'vurl_cloud_id': '2', 'vod_d_id': vod_id}, '/App/Resource/Vurl/show')
            if not qdata or 'vodInfo' not in qdata:
                return {'list': []}
            vod = qdata.get('vodInfo') or {}
            d = {
                'vod_id': vod_id,
                'vod_name': vod.get('vod_name', ''),
                'vod_pic': vod.get('vod_pic', ''),
                'vod_year': vod.get('vod_year', ''),
                'vod_area': vod.get('vod_area', ''),
                'vod_actor': vod.get('vod_actor', ''),
                'vod_director': vod.get('vod_director', ''),
                'vod_content': str(vod.get('vod_use_content', '') or '').strip(),
                'vod_play_from': '瓜子影视',
            }
            play_list = []
            lst = (jdata or {}).get('list') or []
            for index, item in enumerate(lst):
                plays = item.get('play') if isinstance(item, dict) else None
                if not isinstance(plays, dict):
                    continue
                names, params = [], []
                for key, value in plays.items():
                    if isinstance(value, dict) and value.get('param'):
                        names.append(str(key))
                        params.append(str(value['param']))
                if not params:
                    continue
                play_name = str(index + 1) if len(lst) != 1 else (d['vod_name'] or '1')
                play_url = '%s||%s' % (params[-1], '@'.join(names))
                play_list.append('%s$%s' % (play_name.replace('$', '').replace('#', ''), play_url))
            d['vod_play_url'] = '#'.join(play_list)
            return {'list': [d]}
        except Exception as e:
            print('获取详情失败: %s' % e)
            return {'list': []}

    def searchContent(self, key='', quick=False, pg=1, *args, **kwargs):
        videos = []
        pn = self._to_int(pg) or 1
        try:
            data = self.get_data({'keywords': str(key or ''), 'order_val': '1', 'page': str(pn)},
                                 '/App/Index/findMoreVod', use_cache=False)
            if data and isinstance(data.get('list'), list):
                for item in data['list']:
                    videos.append(self._item_to_video(item))
        except Exception as e:
            print('搜索失败: %s' % e)
        return {'list': videos, 'page': pn, 'pagecount': 9999 if videos else 1,
                'limit': 30, 'total': len(videos)}

    def playerContent(self, flag='', id='', vipFlags=None, *args, **kwargs):
        header = {'User-Agent': PLAY_UA, 'Referer': PLAY_REFERER}
        try:
            pid = str(id if id else flag or '')
            parts = pid.split('||')
            if len(parts) < 2:
                return {'header': header, 'parse': 0, 'url': ''}
            params = {}
            for pair in parts[0].split('&'):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    params[k] = v
            resolutions = [x for x in parts[1].split('@') if x]
            if resolutions:
                resolutions.sort(key=lambda x: int(x) if str(x).isdigit() else 0, reverse=True)
                params['resolution'] = resolutions[0]
            data = self.get_data(params, '/App/Resource/VurlDetail/showOne', use_cache=False)
            url = (data or {}).get('url') or ''
            if url:
                return {'header': header, 'parse': 0, 'url': url}
        except Exception as e:
            print('播放解析失败: %s' % e)
        return {'header': header, 'parse': 0, 'url': ''}

    def isVideoFormat(self, url):
        if not url:
            return False
        return any(str(url).lower().split('?')[0].endswith(fmt) for fmt in
                   ('.m3u8', '.mp4', '.avi', '.mkv', '.flv', '.ts'))

    def manualVideoCheck(self):
        return False

    def getDependence(self):
        return ''

    def localProxy(self, params=None, *args, **kwargs):
        return None

    def progressVideo(self, *args, **kwargs):
        return False

    def setVideoFlags(self, *args, **kwargs):
        return None
