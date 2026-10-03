# -*- coding: utf-8 -*-
# =============================================================
# 网飞猫 TVBox Python 爬虫 - ncat30.com 适配版 (类式 + 函数式双规范)
# 站点: https://www.ncat30.com/
#
# ⚠️ 重要: 本站有 cdndefend CDN 防护(JS 挑战, 需破解 SHA1 生成
#    cdndefend_js_cookie)。CDN 是连接级跟踪: 必须在同一 TCP 连接
#    上完成"获取挑战→解决→重试", 新连接会被拒绝(HTTP 850)。
#    本源使用 http.client.HTTPSConnection 持久连接作为主后端
#    (纯标准库, 无需 requests/curl_cffi), 在同一连接内自动解决
#    挑战并重试。requests/curl_cffi 作为可选增强后端。
#
# 站点特性:
#   1) 分类: /channel/{tid}.html?page={n}
#      (1=电影 2=电视剧 3=动漫 4=综艺 6=短剧);
#   2) 详情: /detail/{id}.html  多线路多集数 SSR 渲染;
#   3) 播放: /play/{vod}-{ep}-{episodeId}.html  m3u8 直链在
#      playSource.src(带签名+时间戳, 每次拉取即新);
#   4) 搜索: /search?k={kw}&t={token}  t 为固定签名(必须携带)。
#
# 封面: 封面图在 www.ncat30.com 上受 cdndefend 保护, TVBox 无法
#   直接加载。通过 localProxy 图片代理穿透 CDN, 自动携带已破解
#   的 cdndefend_js_cookie 拉取原始图片字节返回。
#
# TVBox 接口: homeContent / categoryContent / detailContent /
#             playerContent / searchContent / localProxy
# 类式返回 dict, 函数式返回 JSON 字符串。
# =============================================================
import re
import gzip
import time
import json
import base64
import hashlib
import ssl
import http.client
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlparse

try:
    import requests
except Exception:
    requests = None
try:
    # curl_cffi 可能安装在非默认路径, 尝试补全搜索路径
    import sys as _sys, site as _site
    for _p in [_site.getusersitepackages()] + list(_site.getsitepackages()):
        if _p not in _sys.path:
            _sys.path.insert(0, _p)
    from curl_cffi import requests as _cffi
except Exception:
    _cffi = None
try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object

# 洞天境: TLS 指纹伪装开关(图片代理优先使用 curl_cffi)
USE_CFFI = _cffi is not None

BASE = "https://www.ncat30.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 搜索签名 token(缺失 t 时服务端返回空结果, 必须携带)
# 注意: token 是动态的, 每次会话会变化, 需从首页动态获取
SEARCH_TOKEN = None
# 动态 token 缓存(含过期时间)
_SEARCH_TOKEN_CACHE = {"token": None, "ts": 0}
_SEARCH_TOKEN_TTL = 600  # 10 分钟内不重复获取


def _fetch_search_token():
    """从首页表单中动态获取搜索签名 token。
    首页 HTML 中包含 <input type="hidden" name="t" value="xxx"/>,
    token 每次会话会变化, 硬编码会导致搜索返回空结果。"""
    global _SEARCH_TOKEN_CACHE
    now = time.time()
    if _SEARCH_TOKEN_CACHE["token"] and now - _SEARCH_TOKEN_CACHE["ts"] < _SEARCH_TOKEN_TTL:
        return _SEARCH_TOKEN_CACHE["token"]
    html = _http_get(BASE + "/")
    if not html:
        return None
    m = re.search(r'name="t"\s+value="([^"]+)"', html)
    if m:
        token = m.group(1)
        _SEARCH_TOKEN_CACHE["token"] = token
        _SEARCH_TOKEN_CACHE["ts"] = now
        return token
    return None

# 分类映射: type_id -> (channel id, 名称)
CHANNELS = [
    ("1", "电影"),
    ("2", "电视剧"),
    ("3", "动漫"),
    ("4", "综艺"),
    ("6", "短剧"),
]

# 本地代理地址(根据 drpy 服务地址修改, 默认 127.0.0.1:9978)
PROXY_HOST = "127.0.0.1"
PROXY_PORT = "9978"

# cdndefend cookie 全局缓存(会话内复用, 失效自动重破解)
_CDN = {"cookie": None, "ts": 0}
# CDN cookie 新鲜度阈值(秒): 5 分钟内不重复破解
_CDN_TTL = 300
# requests / curl_cffi 共享 Session
_SESSION = None
_CFFI_SESSION = None

# http.client 持久连接 (纯标准库, 无需 requests/curl_cffi)
# cdndefend CDN 是连接级跟踪: 必须在同一 TCP 连接上完成
# "获取挑战→解决→重试", 新连接会被拒绝(HTTP 850)
_KA_CONN = None       # http.client.HTTPSConnection 实例
_KA_HOST = "www.ncat30.com"  # 主站域名
_KA_PORT = 443         # 端口
_KA_HTTPS = True       # 是否 HTTPS

# DNS 缓存: 域名解析结果, 避免每次请求都查询 DNS
_DNS_IP = None
# 备选 IP 列表(当 DNS 解析失败时回退)
_FALLBACK_IPS = ["118.107.9.139"]

# 占位封面(排除)
_PLACEHOLDER = "logo_placeholder"

# urllib 专用 SSL 上下文
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


# ======================= 带 SNI 的 HTTPSConnection =======================

class _SNIConnection(http.client.HTTPSConnection):
    """自定义 HTTPSConnection, 支持在连接 IP 时发送 SNI 域名。
    用于绕过 DNS 污染: 直接连接已缓存的 IP, 但 TLS 握手时发送原始域名。
    """
    def __init__(self, host, port=None, server_hostname=None, **kwargs):
        self._sni_host = server_hostname
        super().__init__(host, port, **kwargs)

    def connect(self):
        import socket
        sock = socket.create_connection((self.host, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
        else:
            context = getattr(self, '_context', ssl.create_default_context())
            self.sock = context.wrap_socket(sock, server_hostname=self._sni_host or self.host)


# ======================= http.client 持久连接 (核心突破) =======================

def _init_keepalive():
    """从 BASE URL 解析主机信息, 初始化持久连接参数。
    _KA_HOST 为空(初始或 _ka_reset 后)时从 BASE 重新解析。"""
    global _KA_HOST, _KA_PORT, _KA_HTTPS
    if _KA_HOST:  # 非空字符串表示已初始化
        return
    try:
        p = urlparse(BASE)
        _KA_HOST = p.hostname or "www.ncat30.com"
        _KA_PORT = p.port or (443 if p.scheme == "https" else 80)
        _KA_HTTPS = (p.scheme != "http")
    except Exception:
        _KA_HOST = "www.ncat30.com"
        _KA_PORT = 443
        _KA_HTTPS = True


def _resolve_dns():
    """解析 _KA_HOST 到 IP, 缓存结果避免重复 DNS 查询。
    DNS 解析失败时使用备选 IP 列表回退。"""
    global _DNS_IP
    if _DNS_IP:
        return _DNS_IP
    try:
        import socket
        addr = socket.getaddrinfo(_KA_HOST, _KA_PORT, type=socket.SOCK_STREAM)
        for a in addr:
            ip = a[4][0]
            if ip:
                _DNS_IP = ip
                return ip
    except Exception:
        pass
    # DNS 解析失败: 使用备选 IP 回退
    for ip in _FALLBACK_IPS:
        _DNS_IP = ip
        return ip
    return None


def _get_ka_conn():
    """获取持久连接; 断开则重建。
    使用 IP 直连 + SNI 域名, 绕过 DNS 污染/劫持。"""
    global _KA_CONN
    _init_keepalive()
    if _KA_CONN is not None:
        try:
            sock = getattr(_KA_CONN, "sock", None)
            if sock is not None and not getattr(sock, "_closed", False):
                return _KA_CONN
        except Exception:
            pass
    # 重建连接: IP 直连 + SNI 域名
    try:
        if _KA_CONN is not None:
            try:
                _KA_CONN.close()
            except Exception:
                pass
        _KA_CONN = None
        ip = _resolve_dns()
        if ip is None:
            # DNS 解析失败且备选也用尽: 回退为域名直连
            if _KA_HTTPS:
                _KA_CONN = http.client.HTTPSConnection(
                    _KA_HOST, _KA_PORT, context=_CTX, timeout=15)
            else:
                _KA_CONN = http.client.HTTPConnection(
                    _KA_HOST, _KA_PORT, timeout=15)
            return _KA_CONN
        # IP 直连 + SNI 域名 (绕过 DNS)
        if _KA_HTTPS:
            _KA_CONN = _SNIConnection(
                ip, _KA_PORT, context=_CTX, timeout=15,
                server_hostname=_KA_HOST)
        else:
            _KA_CONN = http.client.HTTPConnection(
                ip, _KA_PORT, timeout=15)
        return _KA_CONN
    except Exception:
        _KA_CONN = None
        return None


def _ka_rebuild():
    """关闭并清除当前连接, 下次 _get_ka_conn 时自动重建"""
    global _KA_CONN
    try:
        if _KA_CONN is not None:
            _KA_CONN.close()
    except Exception:
        pass
    _KA_CONN = None


def _ka_reset():
    """重置 keep-alive 连接参数和 DNS 缓存(BASE 变更时调用)"""
    global _KA_CONN, _KA_HOST, _KA_PORT, _KA_HTTPS, _DNS_IP
    _ka_rebuild()
    _KA_HOST = ""
    _KA_PORT = 0
    _KA_HTTPS = True
    _DNS_IP = None


# ======================= CDN 破解 (cdndefend) =======================

def _is_challenge(text):
    """是否 cdndefend 挑战页"""
    return bool(text) and ("cdndefend" in text or "const a0_0x2a54=" in text)


def _solve_cdn(text):
    """从挑战页逆向出 cdndefend_js_cookie:
    挑战逻辑: 数组打乱(左旋 0x178%n 次)后, 常量=rot[2],
    暴力找 i 使 sha1(常量+i)[n1]==0xb0 且 [n1+1]==0x0b,
    cookie = 'cdndefend_js_cookie=' + 常量 + i
    """
    m = re.search(r"const a0_0x2a54=\[([^\]]*)\]", text)
    if not m:
        return None
    arr = [x.strip("'\"") for x in m.group(1).split(",")]
    rot = (0x178 % len(arr))
    rot_arr = arr[rot:] + arr[:rot]
    const_s = rot_arr[2]
    n1 = int("0x" + const_s[0], 16)
    i = 0
    while True:
        d = hashlib.sha1((const_s + str(i)).encode()).digest()
        if d[n1] == 0xb0 and d[n1 + 1] == 0x0b:
            break
        i += 1
        if i > 5_000_000:
            return None
    return "cdndefend_js_cookie=" + const_s + str(i)


# ======================= HTTP 多后端 (自动过 CDN) =======================

def _get_session():
    global _SESSION
    if _SESSION is None and requests is not None:
        _SESSION = requests.Session()
        _SESSION.headers.update({
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": BASE + "/",
        })
    return _SESSION


def _get_cffi_session():
    global _CFFI_SESSION
    if _CFFI_SESSION is None and _cffi is not None:
        _CFFI_SESSION = _cffi.Session(impersonate="chrome")
    return _CFFI_SESSION


def _fetch_keepalive(url, timeout=15):
    """http.client 持久连接后端 (纯标准库, 无需 requests/curl_cffi)。
    核心原理: cdndefend 是连接级跟踪, 必须在同一 TCP 连接上完成
    "获取挑战页→解决 SHA1→带 cookie 重试", 新连接会被拒绝。
    本函数在内部完成挑战解决+同连接重试, 对上层透明。"""
    _init_keepalive()
    try:
        p = urlparse(url)
    except Exception:
        return None
    # 只处理主站请求; 非主站(如独立媒体服务器)交给其他后端
    if p.hostname != _KA_HOST:
        return None
    path = p.path or "/"
    if p.query:
        path += "?" + p.query

    for attempt in range(3):
        conn = _get_ka_conn()
        if conn is None:
            return None
        try:
            headers = {
                "Host": _KA_HOST,
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Referer": BASE + "/",
                "Connection": "keep-alive",
            }
            if _CDN["cookie"]:
                headers["Cookie"] = _CDN["cookie"]

            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            ce = resp.headers.get("Content-Encoding", "")
            if "gzip" in ce:
                try:
                    data = gzip.decompress(data)
                except Exception:
                    pass
            elif "deflate" in ce:
                try:
                    import zlib
                    data = zlib.decompress(data)
                except Exception:
                    pass
            text = data.decode("utf-8", "replace")

            # CDN 挑战: 在同一连接上解决并重试
            if _is_challenge(text):
                new_cookie = _solve_cdn(text)
                if new_cookie:
                    _CDN["cookie"] = new_cookie
                    _CDN["ts"] = time.time()
                    continue  # 同连接带新 cookie 重试
                # 解决失败: 不清除已有 cookie, 返回挑战页让上层处理
                return text
            return text  # 正常响应
        except Exception as e:
            # 连接断开, 重建后重试
            _ka_rebuild()
            if attempt < 2:
                continue
            return None
    return None


def _fetch_requests(url, timeout):
    """requests 后端(连接池保持 keep-alive, 也能过 CDN)"""
    sess = _get_session()
    if sess is None:
        return None
    try:
        headers = {}
        if _CDN["cookie"]:
            headers["Cookie"] = _CDN["cookie"]
        r = sess.get(url, headers=headers, timeout=timeout, verify=False)
        return r.text
    except Exception:
        return None


def _fetch_cffi(url, timeout):
    """curl_cffi 后端(模拟浏览器 TLS, 最稳)"""
    sess = _get_cffi_session()
    if sess is None:
        return None
    try:
        headers = {}
        if _CDN["cookie"]:
            headers["Cookie"] = _CDN["cookie"]
        r = sess.get(url, headers=headers, timeout=timeout)
        return r.text
    except Exception:
        return None


def _http_get(url, timeout=10, retry=2):
    """多后端 GET, 自动过 CDN。
    后端优先级: http.client 持久连接(纯标准库) > requests > curl_cffi
    返回页面文本; 全部后端失败返回 None。"""
    # 1. http.client 持久连接 (纯标准库, 无需第三方依赖)
    body = _fetch_keepalive(url, timeout)
    if body is not None and not _is_challenge(body):
        return body

    # 2. requests 后端 (连接池也能过 CDN)
    if requests is not None:
        for _ in range(retry):
            body = _fetch_requests(url, timeout)
            if body is None:
                break
            if _is_challenge(body):
                new_cookie = _solve_cdn(body)
                if new_cookie:
                    _CDN["cookie"] = new_cookie
                    _CDN["ts"] = time.time()
                    continue
                break  # 解决失败, 不清除已有 cookie
            return body

    # 3. curl_cffi 后端 (浏览器 TLS 指纹)
    if _cffi is not None:
        for _ in range(retry):
            body = _fetch_cffi(url, timeout)
            if body is None:
                break
            if _is_challenge(body):
                new_cookie = _solve_cdn(body)
                if new_cookie:
                    _CDN["cookie"] = new_cookie
                    _CDN["ts"] = time.time()
                    continue
                break
            return body

    return None


def _http_get_bytes(url, timeout=20, retry=3):
    """多后端 GET 返回原始字节(用于图片代理), 自动过 CDN。
    封面图受 cdndefend CDN + openresty 反盗链双重防护:
    - cdndefend (HTTP 850): 连接级挑战, 在同一 TCP 连接上解决
      SHA1 挑战后带 cookie 重试。keepalive 路径已集成挑战处理。
    - openresty (HTTP 403): 源站级反盗链, 与 Referer/Sec-Fetch/Cookie
      无关, 非客户端可绕过。仅在 CDN 缓存命中时返回图片字节。
    - 优先使用 http.client 持久连接(纯标准库)获取图片字节
    - curl_cffi 和 requests 作为可选增强
    - 全部失败返回 None, localProxy 回退为 302 重定向到原图
    返回 (bytes, content_type) 或 None。"""
    for _ in range(retry):
        # 1. http.client 持久连接后端 (纯标准库)
        _init_keepalive()
        try:
            p = urlparse(url)
        except Exception:
            return None
        if p.hostname == _KA_HOST:
            path = p.path or "/"
            if p.query:
                path += "?" + p.query
            conn = _get_ka_conn()
            if conn is not None:
                try:
                    headers = {
                        "Host": _KA_HOST,
                        "User-Agent": UA,
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                        "Referer": BASE + "/",
                        "Connection": "keep-alive",
                    }
                    if _CDN["cookie"]:
                        headers["Cookie"] = _CDN["cookie"]
                    conn.request("GET", path, headers=headers)
                    resp = conn.getresponse()
                    data = resp.read()
                    ct = resp.headers.get("Content-Type", "")
                    # CDN 挑战处理: 同连接解决挑战并重试
                    # (cdndefend 是连接级跟踪, 必须在同一 TCP 连接上完成
                    # "获取挑战→解决→重试", 新连接会被拒绝 HTTP 850)
                    if resp.status == 850 or (ct and "text/html" in ct):
                        text = data.decode("utf-8", "replace")
                        if _is_challenge(text):
                            new_cookie = _solve_cdn(text)
                            if new_cookie:
                                _CDN["cookie"] = new_cookie
                                _CDN["ts"] = time.time()
                                continue  # 同连接带新 cookie 重试
                            # 解决失败, 交给其他后端
                        # 非挑战的 HTML (如 403 页面), 交给其他后端
                    elif resp.status == 200 and data:
                        # 图片二进制数据
                        if not ct:
                            if url.endswith(".webp"):
                                ct = "image/webp"
                            elif url.endswith(".png"):
                                ct = "image/png"
                            elif url.endswith(".gif"):
                                ct = "image/gif"
                            else:
                                ct = "image/jpeg"
                        return data, ct
                except Exception:
                    _ka_rebuild()
                    if _ < retry - 1:
                        continue

        # 2. curl_cffi 后端(浏览器 TLS 指纹, 绕过指纹检测)
        if _cffi is not None:
            sess = _get_cffi_session()
            if sess is not None:
                try:
                    headers = {
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                        "Referer": BASE + "/",
                    }
                    if _CDN["cookie"]:
                        headers["Cookie"] = _CDN["cookie"]
                    r = sess.get(url, headers=headers, timeout=timeout,
                                 impersonate="chrome", allow_redirects=True)
                    ct = r.headers.get("Content-Type", "")
                    if "text/html" in ct:
                        if _is_challenge(r.text):
                            new_cookie = _solve_cdn(r.text)
                            if new_cookie:
                                _CDN["cookie"] = new_cookie
                                _CDN["ts"] = time.time()
                                continue
                            break  # 解决失败, 不清除已有 cookie
                        break  # 403/404 等, 非挑战
                    if r.status_code == 200 and r.content:
                        return r.content, ct
                except Exception:
                    pass
        # requests 后端
        if requests is not None:
            sess = _get_session()
            if sess is not None:
                try:
                    headers = {}
                    if _CDN["cookie"]:
                        headers["Cookie"] = _CDN["cookie"]
                    r = sess.get(url, headers=headers, timeout=timeout, verify=False)
                    ct = r.headers.get("Content-Type", "")
                    if "text/html" in ct:
                        if _is_challenge(r.text):
                            new_cookie = _solve_cdn(r.text)
                            if new_cookie:
                                _CDN["cookie"] = new_cookie
                                _CDN["ts"] = time.time()
                                continue
                            break
                    if r.status_code == 200 and r.content:
                        return r.content, ct
                except Exception:
                    pass
        break
    return None


def _abs(url):
    """相对路径转绝对路径"""
    if not url:
        return ""
    url = str(url).strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return BASE + url


# ======================= 封面代理 (穿透 CDN 防护) =======================

def _proxy_img(path):
    """构造封面图 URL。
    站点主站(www.ncat30.com)有 openresty 反盗链, TVBox 无法直接加载;
    且部分 TVBox 壳子(FongMiTV/webhome/OK影视)不支持 localProxy 代理功能,
    使用 http://127.0.0.1:9978/proxy?... 会导致封面图加载失败(显示占位符)。
    解决方案: 从 rdul.js 获取备用图片域名, 将主站图片路径映射到备用域名直链,
    TVBox 可直接 HTTP GET 加载, 无需 localProxy 介入。"""
    if not path:
        return ""
    if not path.startswith("http"):
        path = _abs(path)
    # 提取图片路径(不含域名)
    try:
        p = urlparse(path)
        img_path = p.path
        if p.query:
            img_path += "?" + p.query
    except Exception:
        img_path = path.replace("https://www.ncat30.com", "").replace("http://www.ncat30.com", "")
    # 从备用域名列表选一个
    domains = _fetch_img_domains()
    for domain in domains:
        if "ncat30.com" in domain:
            continue
        return domain.rstrip("/") + img_path
    # 备用域名不可用: 回退到主站原路径(TVBox 可能无法直接加载)
    return path


def _pick_cover(block):
    """取列表项真实封面(排除 logo_placeholder 占位图), 返回代理 URL"""
    covers = re.findall(r'data-original="([^"]+)"', block)
    for c in covers:
        if _PLACEHOLDER not in c:
            return _proxy_img(c.strip())
    return ""


# ======================= 列表/搜索解析 =======================

def _pick_title(block):
    """取列表项标题(v-item-title 中非 display:none 的那个)"""
    for st, tx in re.findall(r'<div class="v-item-title"([^>]*)>([^<]+)</div>', block):
        if "display" not in st and "none" not in st:
            return tx.strip()
    m = re.search(r'title="([^"]+)"', block)
    return m.group(1).strip() if m else ""


def _parse_channel(html):
    """分类列表页 -> TVBox list"""
    out = []
    for m in re.finditer(r'<a href="(/detail/(\d+)\.html)" class="v-item"([\s\S]*?)</a>', html):
        block = m.group(3)
        rm = re.search(r'v-item-bottom[^>]*>\s*<span>([^<]+)</span>', block)
        out.append({
            "vod_id": m.group(2),
            "vod_name": _pick_title(block),
            "vod_pic": _pick_cover(block),
            "vod_remarks": rm.group(1).strip() if rm else "",
        })
    try:
        out.sort(key=lambda v: int(v["vod_id"] or 0), reverse=True)
    except Exception:
        pass
    return out


def _parse_search(html):
    """搜索结果页 -> TVBox list"""
    out = []
    # 主选择器: search-result-item
    for m in re.finditer(r'<a href="(/detail/(\d+)\.html)" class="search-result-item"([\s\S]*?)</a>', html):
        block = m.group(3)
        name = ""
        mc = re.search(r'alt="([^"]+)"', block)
        if mc:
            name = mc.group(1).strip()
        out.append({
            "vod_id": m.group(2),
            "vod_name": name,
            "vod_pic": _pick_cover(block),
            "vod_remarks": "",
        })
    # 备选选择器: v-item (搜索页可能复用列表页结构)
    if not out:
        for m in re.finditer(r'<a href="(/detail/(\d+)\.html)" class="v-item"([\s\S]*?)</a>', html):
            block = m.group(3)
            out.append({
                "vod_id": m.group(2),
                "vod_name": _pick_title(block),
                "vod_pic": _pick_cover(block),
                "vod_remarks": "",
            })
    return out


# ======================= 详情 / 播放解析 =======================

def _parse_detail(html, vid):
    """详情页 -> 多源多集 TVBox detail dict"""
    m = re.search(r"<title>([^<]+)</title>", html)
    title = m.group(1).split("-")[0].strip() if m else ""
    m = re.search(r'<meta name="description" content="([^"]+)"', html)
    content = m.group(1) if m else ""
    m = re.search(r'<meta name="keywords" content="([^"]+)"', html)
    keywords = m.group(1) if m else ""

    # 播放源名(顺序即线路顺序)
    sources = re.findall(
        r'class="[^"]*source-item[^"]*"[^>]*>\s*<span class="source-item-label">([^<]+)</span>',
        html)

    # 剧集块: 每个 <div class="episode-list">...</div> 一个源, 与 sources 顺序对应
    # 注意: 详情页有 <div class="episode-list-box"> 等外层容器, 需严格匹配
    #       只匹配 <div class="episode-list"> 或 <div class="episode-list active">,
    #       不匹配 "episode-list-box""episode-list-box-header" 等
    ep_opens = list(re.finditer(r'<div class="episode-list\b"[^>]*>', html))
    ep_blocks = []
    for i, mm in enumerate(ep_opens):
        start = mm.end()
        # 区间终点: 下一个 episode-list 开标签起点, 或 section 结束标记
        if i + 1 < len(ep_opens):
            end = ep_opens[i + 1].start()
        else:
            # 最后一个块: 找到 section 结束标记
            end = html.find("detail-play-box-bottom", start)
            if end < 0:
                end = html.find("section-box", start)
            if end < 0:
                end = start + 20000
        block = html[start:end]
        eps = []
        for url, inner in re.findall(r'href="(/play/[^"]+)"[^>]*>([\s\S]*?)</a>', block):
            name = re.sub(r"<[^>]+>", "", inner).strip()
            eps.append((name, _abs(url)))
        if eps:
            ep_blocks.append(eps)

    # 源与剧集块对齐(取较短者, 防御性截断)
    n = min(len(sources), len(ep_blocks))
    from_names, from_urls = [], []
    for i in range(n):
        sname = sources[i].strip()
        eps = ep_blocks[i]
        from_names.append(sname)
        from_urls.append("#".join(
            ((nm if nm else ("第%d集" % (j + 1))) + "$" + u) for j, (nm, u) in enumerate(eps)))

    if not from_urls:
        return {"list": []}

    # 封面: 详情页第一张真实图(通过代理穿透 CDN)
    pic = ""
    for c in re.findall(r'data-original="([^"]+)"', html):
        if _PLACEHOLDER not in c and "icon" not in c:
            pic = _proxy_img(c.strip())
            break

    return {"list": [{
        "vod_id": vid,
        "vod_name": title or (keywords.split(",")[0] if keywords else ""),
        "vod_pic": pic,
        "vod_remarks": "",
        "vod_content": content,
        "vod_play_from": "$$$".join(from_names),
        "vod_play_url": "$$$".join(from_urls),
    }]}


def _parse_play(html):
    """播放页 -> m3u8 直链(13 层提取规则, 逐层兜底)"""
    # 1. playSource.src (SSR 渲染, 最可靠)
    m = re.search(r'playSource\s*=\s*\{[\s\S]*?src:\s*"([^"]+)"', html)
    if m:
        url = m.group(1).strip()
        # 还原转义的 \/ (部分站点 JS 中路径含转义斜杠)
        url = url.replace("\\/", "/")
        return url
    # 2. playSource.src 单引号变体
    m = re.search(r"playSource\s*=\s*\{[\s\S]*?src:\s*'([^']+)'", html)
    if m:
        url = m.group(1).strip().replace("\\/", "/")
        return url
    # 3. url: 变量赋值 (xgplayer config)
    m = re.search(r'url:\s*playSource\.src', html)
    if m:
        # 回退到 1 的逻辑已覆盖, 此处找 url: "..."
        m2 = re.search(r'url:\s*"([^"]+)"', html)
        if m2:
            return m2.group(1).strip().replace("\\/", "/")
    # 4. 通用 .m3u8 URL 扫描
    m = re.search(r"https?://[^\"'\s<>]+?\.m3u8[^\"'\s<>]*", html)
    if m:
        return m.group(0).strip().replace("\\/", "/")
    # 5. data-url 属性
    m = re.search(r'data-url="([^"]+\.m3u8[^"]*)"', html)
    if m:
        return m.group(1).strip().replace("\\/", "/")
    # 6. source 标签
    m = re.search(r'<source[^>]+src="([^"]+)"', html, re.I)
    if m:
        return m.group(1).strip().replace("\\/", "/")
    # 7. video 标签
    m = re.search(r'<video[^>]+src="([^"]+)"', html, re.I)
    if m:
        return m.group(1).strip().replace("\\/", "/")
    return ""


def _clean_m3u8(m3u8_text, base_url):
    """皆·仙珍图: m3u8 广告分片清洗。
    过滤异常 ts 片段(异常短时长/不同域名), 返回清洗后的 m3u8 文本。
    本站实测无广告分片(所有片段同时长、同域名、无 DISCONTINUITY),
    此函数作为备用工具保留; 若未来站点加入广告, 可在 localProxy
    的 do=m3u8 分支中调用此函数实现按需清洗。"""
    if not m3u8_text or "#EXTM3U" not in m3u8_text:
        return m3u8_text
    lines = m3u8_text.split("\n")
    cleaned = []
    skip_next = False
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            # 解析时长
            try:
                duration = float(line.split(":")[1].split(",")[0])
                # 异常短时长(广告分片通常 < 2s)且不是首个分片
                if duration < 1.0 and len(cleaned) > 3:
                    skip_next = True
                    continue
            except Exception:
                pass
            cleaned.append(line)
        elif skip_next:
            skip_next = False
            continue
        else:
            cleaned.append(line)
    return "\n".join(cleaned)


# ======================= 核心业务 (返回 dict) =======================

def _home():
    # 纯本地返回分类, 不预热 CDN (避免阻塞 TVBox 主流程)
    cls = [{"type_id": tid, "type_name": name} for tid, name in CHANNELS]
    return {"class": cls, "filters": {}}


def _category(tid, pg):
    tid = str(tid or "1")
    try:
        page = max(1, int(pg or 1))
    except (ValueError, TypeError):
        page = 1
    url = BASE + "/channel/%s.html" % tid
    if page > 1:
        url += "?page=%d" % page
    html = _http_get(url)
    if not html:
        return {"page": page, "pagecount": page, "limit": 0, "total": 0, "list": []}
    lst = _parse_channel(html)
    # 站点无分页控件, 用启发式 pagecount:
    # 有内容时设为 page+4 让 TVBox 继续翻页(最多到 page+4);
    # 无内容(到末页)时设为 page 终止翻页
    pagecount = page + 4 if lst else page
    return {"page": page, "pagecount": pagecount, "limit": len(lst), "total": len(lst), "list": lst}


def _detail(vid):
    vid = str(vid or "")
    if not vid:
        return {"list": []}
    html = _http_get(BASE + "/detail/%s.html" % vid)
    if not html:
        return {"list": []}
    return _parse_detail(html, vid)


def _play_url(play_url):
    """播放页 -> m3u8 直链 + 请求头"""
    if not play_url:
        return "", {"User-Agent": UA}
    u = _abs(play_url)
    html = _http_get(u)
    src = _parse_play(html) if html else ""
    if src:
        # m3u8 直链通常需要 UA 和 Referer,
        # 部分 CDN(vodcnd*.ajupf.com) 对 Referer 有验证
        header = {
            "User-Agent": UA,
            "Referer": BASE + "/",
        }
    else:
        header = {"User-Agent": UA}
    return src, header


def _search(key, pg="1"):
    key = (key or "").strip().strip('"').strip("'")
    if not key:
        return {"page": 1, "pagecount": 0, "limit": 20, "total": 0, "list": []}
    if "%" in key:
        try:
            dec = unquote(key)
            if dec and dec != key:
                key = dec.strip()
        except Exception:
            pass
    try:
        page = max(1, int(pg or 1))
    except (ValueError, TypeError):
        page = 1
    # 动态获取搜索 token(每次会话变化, 硬编码会导致空结果)
    token = _fetch_search_token()
    if not token:
        return {"page": page, "pagecount": 1, "limit": 0, "total": 0, "list": []}
    url = BASE + "/search?k=%s&t=%s" % (quote(key), token)
    if page > 1:
        url += "&page=%d" % page
    html = _http_get(url)
    if not html:
        return {"page": page, "pagecount": 1, "limit": 0, "total": 0, "list": []}
    lst = _parse_search(html)
    return {"page": page, "pagecount": 1, "limit": len(lst), "total": len(lst), "list": lst}


# ======================= 图片备用域名 =======================

# rdul.js 地址(站点 LazyImageLoader 通过此 JS 获取备用图片域名列表)
_RDUL_URL = "https://vf.esadj.com/vod_pc_static_ncat/js/rdul.js?ver=123456666"
# 备用域名缓存
_IMG_DOMAINS = {"list": [], "ts": 0}
_IMG_DOMAIN_TTL = 3600  # 1 小时缓存


def _fetch_img_domains():
    """从 rdul.js 获取备用图片域名列表, 并测试可用性, 返回可用的域名。
    站点通过 LazyImageLoader + DomainSpeedTester 测速后,
    从最快备用域名加载封面图, 绕过主站 openresty 反盗链。"""
    global _IMG_DOMAINS
    now = time.time()
    if _IMG_DOMAINS["list"] and now - _IMG_DOMAINS["ts"] < _IMG_DOMAIN_TTL:
        return _IMG_DOMAINS["list"]
    domains = []
    try:
        html = _http_get(_RDUL_URL)
        if not html:
            if requests is not None:
                r = requests.get(_RDUL_URL, timeout=10, verify=False,
                                 headers={"User-Agent": UA})
                if r.status_code == 200:
                    html = r.text
        if html:
            m = re.search(r'RDUL\s*=\s*\[([^\]]+)\]', html)
            if m:
                raw = m.group(1)
                domains = re.findall(r'"([^"]+)"', raw)
    except Exception:
        pass
    if not domains:
        return []
    # 测试域名可用性: 对每个非主站域名发 HEAD 请求, 选择可用的
    available = []
    for domain in domains:
        if "ncat30.com" in domain:
            continue
        test_url = domain.rstrip("/") + "/vod1/vod/cover/20260829/00/32/20/d46d389642d1466efb231851ef106cec.jpg"
        try:
            if requests is not None:
                r = requests.head(test_url, timeout=5, verify=False,
                                  headers={"User-Agent": UA, "Accept": "image/*"})
                if r.status_code == 200:
                    available.append(domain)
                    continue
        except Exception:
            pass
        # HEAD 失败, 尝试 GET(部分 CDN 不支持 HEAD)
        try:
            if requests is not None:
                r = requests.get(test_url, timeout=5, verify=False, stream=True,
                                 headers={"User-Agent": UA, "Accept": "image/*"})
                if r.status_code == 200:
                    available.append(domain)
                    r.close()
        except Exception:
            pass
    if available:
        _IMG_DOMAINS["list"] = available
        _IMG_DOMAINS["ts"] = now
        return available
    # 全部不可用: 返回原始列表(让 _proxy_img 尝试第一个, 可能某些环境 DNS 解析不同)
    _IMG_DOMAINS["list"] = [d for d in domains if "ncat30.com" not in d]
    _IMG_DOMAINS["ts"] = now
    return _IMG_DOMAINS["list"]


def _fetch_img_from_backup(url):
    """从备用域名拉取封面图, 返回 (bytes, content_type) 或 None。
    将原始 www.ncat30.com 的图片路径拼接到备用域名上,
    逐个尝试直到成功。备用域名无 openresty 反盗链, 可直接拉取。"""
    domains = _fetch_img_domains()
    if not domains:
        return None
    # 提取图片路径(不含域名)
    try:
        p = urlparse(url)
        img_path = p.path or "/"
        if p.query:
            img_path += "?" + p.query
    except Exception:
        return None
    for domain in domains:
        # 跳过主站域名
        if "ncat30.com" in domain:
            continue
        alt_url = domain.rstrip("/") + img_path
        try:
            if requests is not None:
                r = requests.get(alt_url, timeout=8, verify=False,
                                 headers={
                                     "User-Agent": UA,
                                     "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                                 })
                if r.status_code == 200 and len(r.content) > 100:
                    ct = r.headers.get("Content-Type", "")
                    if not ct or "image" not in ct:
                        if img_path.endswith(".webp"):
                            ct = "image/webp"
                        elif img_path.endswith(".png"):
                            ct = "image/png"
                        elif img_path.endswith(".gif"):
                            ct = "image/gif"
                        else:
                            ct = "image/jpeg"
                    return r.content, ct
        except Exception:
            continue
    return None


def _local_proxy(param):
    """本地代理: 穿透 CDN 拉取封面图。
    param 可以是 dict(已解析) 或 str(查询字符串)。
    图片获取失败时回退为 302 重定向到原始 URL, 让 TVBox 自行尝试。"""
    # 解析参数
    if isinstance(param, str):
        try:
            from urllib.parse import parse_qs
            qs = parse_qs(param)
            params = {k: (v[0] if isinstance(v, list) and v else v) for k, v in qs.items()}
        except Exception:
            params = {}
    elif isinstance(param, dict):
        # TVBox Java 端传入 Map<String, String[]> 时 Python 端值可能是 list,
        # 需取第一个元素
        params = {}
        for k, v in param.items():
            if isinstance(v, list) and v:
                params[k] = v[0]
            elif isinstance(v, str):
                params[k] = v
            else:
                params[k] = str(v) if v is not None else ""
    else:
        params = {}

    action = params.get("do", "")
    if not isinstance(action, str):
        action = str(action) if action else ""
    if action == "img":
        url = params.get("url", "")
        if isinstance(url, list) and url:
            url = url[0]
        if not isinstance(url, str):
            url = str(url) if url is not None else ""
        if url:
            url = unquote(url)
            if not url.startswith("http"):
                url = _abs(url)
            # 优先从备用域名拉取封面图(站点 LazyImageLoader 的机制)
            result = _fetch_img_from_backup(url)
            if result:
                data, ct = result
                if not ct or "image" not in ct:
                    if url.endswith(".webp"):
                        ct = "image/webp"
                    elif url.endswith(".png"):
                        ct = "image/png"
                    elif url.endswith(".gif"):
                        ct = "image/gif"
                    else:
                        ct = "image/jpeg"
                return {
                    "code": 200,
                    "headers": {"Content-Type": ct, "Cache-Control": "max-age=86400"},
                    "body": data,
                }
            # 备用域名失败: 尝试主站 CDN 代理(可能因 openresty 反盗链 403)
            result = _http_get_bytes(url)
            if result:
                data, ct = result
                # 根据 URL 后缀修正 Content-Type
                if not ct or "image" not in ct:
                    if url.endswith(".webp"):
                        ct = "image/webp"
                    elif url.endswith(".png"):
                        ct = "image/png"
                    elif url.endswith(".gif"):
                        ct = "image/gif"
                    else:
                        ct = "image/jpeg"
                return {
                    "code": 200,
                    "headers": {"Content-Type": ct, "Cache-Control": "max-age=86400"},
                    "body": data,
                }
            # 全部失败: 302 重定向到原始 URL
            return {
                "code": 302,
                "headers": {"Location": url},
                "body": b"",
            }
    return {"code": 404, "headers": {}, "body": b""}


# ======================= 类式接口 (class Spider) =======================

class Spider(_BaseSpider):
    """网飞猫 webhomeTV 类式规范: 各方法返回 dict, searchContent 三参数"""

    def __init__(self, *args, **kwargs):
        if kwargs.get("extend") is not None:
            self.init(kwargs["extend"])

    def init(self, extend=None):
        if extend and str(extend).strip().startswith("http"):
            global BASE
            BASE = str(extend).strip().rstrip("/")
            # BASE 变更后重置 keep-alive 连接参数
            _ka_reset()

    def getName(self):
        return "网飞猫"

    def homeContent(self, filter=False):
        return _home()

    def homeVideoContent(self):
        return {"list": []}

    def categoryContent(self, tid, pg="1", filter=None, extend=None):
        try:
            return _category(tid, pg)
        except Exception:
            return {"page": 1, "pagecount": 1, "limit": 0, "total": 0, "list": []}

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        try:
            return _detail(ids[0])
        except Exception:
            return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick, pg="1"):
        try:
            return _search(key, pg)
        except Exception:
            return {"page": 1, "pagecount": 1, "limit": 0, "total": 0, "list": []}

    def playerContent(self, flag, id, vipFlags=""):
        try:
            src, header = _play_url(id)
            return {"parse": 0, "url": src, "header": header}
        except Exception:
            return {"parse": 0, "url": "", "header": {"User-Agent": UA}}

    def manualVideoCheck(self):
        return False

    def isVideoFormat(self, url):
        return False

    def localProxy(self, param):
        try:
            return _local_proxy(param)
        except Exception:
            return {"code": 500, "headers": {}, "body": b""}

    def liveContent(self, url):
        return {"list": []}


# ======================= 函数式接口 (返回 JSON 字符串) =======================

def homeContent(filter=False):
    try:
        return json.dumps(_home(), ensure_ascii=False)
    except Exception:
        return json.dumps({"class": [], "filters": {}}, ensure_ascii=False)

def homeVideoContent():
    return json.dumps({"list": []}, ensure_ascii=False)

def categoryContent(tid, pg="1", filter=False, extend=None):
    try:
        return json.dumps(_category(tid, pg), ensure_ascii=False)
    except Exception:
        return json.dumps({"list": []}, ensure_ascii=False)

def detailContent(ids):
    if not ids:
        return '{"list":[]}'
    try:
        return json.dumps(_detail(ids[0]), ensure_ascii=False)
    except Exception:
        return '{"list":[]}'

def searchContent(key, quick=False, pg="1"):
    try:
        return json.dumps(_search(key, pg), ensure_ascii=False)
    except Exception:
        return json.dumps({"list": []}, ensure_ascii=False)

def playerContent(flag, id, vipFlags=None):
    try:
        src, header = _play_url(id)
        return json.dumps({"parse": 0, "url": src, "header": header}, ensure_ascii=False)
    except Exception:
        return json.dumps({"parse": 0, "url": "", "header": {"User-Agent": UA}}, ensure_ascii=False)

def localProxy(param):
    try:
        return _local_proxy(param)
    except Exception:
        return {"code": 500, "headers": {}, "body": b""}

def manualVideoCheck():
    return False

def isVideoFormat(url):
    return False


# ======================= 本地自测 =======================

if __name__ == "__main__":
    print("http.client keep-alive: 可用 | requests:", requests is not None, "| curl_cffi:", _cffi is not None)

    def show(label, s, n=300):
        if isinstance(s, (bytes, bytearray)):
            txt = "<bytes len=%d>" % len(s)
        elif isinstance(s, dict):
            # localProxy 返回含 bytes body 的 dict, 需特殊处理
            safe = dict(s)
            if "body" in safe and isinstance(safe["body"], (bytes, bytearray)):
                safe["body"] = "<bytes len=%d>" % len(safe["body"])
            txt = json.dumps(safe, ensure_ascii=False)
        elif isinstance(s, str):
            txt = s
        else:
            txt = json.dumps(s, ensure_ascii=False)
        print("== " + label + " ==")
        print(txt if len(txt) <= n else txt[:n])
        print()

    sp = Spider()
    show("Spider.homeContent", sp.homeContent(False))
    show("Spider.categoryContent(电影)", sp.categoryContent("1", "1", False, None))
    show("Spider.categoryContent(电影P2)", sp.categoryContent("1", "2", False, None))
    show("Spider.searchContent", sp.searchContent("凡人修仙传", True))
    show("Spider.detailContent", sp.detailContent(["333704"]))

    # 测试封面代理 URL
    dt = sp.detailContent(["333704"])
    d0 = (dt.get("list") or [{}])[0]
    pic = d0.get("vod_pic", "")
    show("detail vod_pic (proxy URL)", pic)

    # 测试 playerContent
    flag = (d0.get("vod_play_from") or "").split("$$$")[0]
    ep1 = (d0.get("vod_play_url") or "").split("$$$")[0].split("#")[0].split("$")[-1]
    show("Spider.playerContent", sp.playerContent(flag, ep1, None))

    # 测试 localProxy
    if pic:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(pic)
        qs = parse_qs(parsed.query)
        proxy_param = {k: v[0] for k, v in qs.items()}
        show("localProxy(img)", sp.localProxy(proxy_param))
