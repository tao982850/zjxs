# coding: utf-8
# !/usr/bin/python
"""
58影视 / 黑猫修复20260719

适配站点：https://dfsfd.ynhongji.com/home（兼容旧入口：https://yoss.58sph5.com/home?code=youhua）
核心能力：自动解密新版线路、游客注册、解密接口响应、分类、详情、搜索、代理/直连 m3u8 播放。
"""

import base64
import hashlib
import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, unquote, urljoin, urlparse

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from base.spider import Spider


class Spider(Spider):
    # 同一 Python 进程内复用游客凭据。部分壳会反复 init Spider；如果每次都
    # 注册一个新 UUID，服务端很快返回 40005，旧代码又会把它误判为成功。
    _AUTH_CACHE = {}
    BOOT_KEY = b"58928cae68092afc"
    BOOT_IV = b"e9d732a1edcdcc0a"
    # 新版 58影视入口：dfsfd.jjfeji3.com
    DOMAIN_JS = "https://pub-77efc86e6df74acd99f2aa2227eedc2e.r2.dev/domain.js"
    DNS_DOMAIN = "yst.58yszx5.com"
    HOP_URLS = [
        "https://tt02.llshjf3.com/ys02.html",
        "https://tt02.ku93z.com/ys02.html",
        "https://tt02.job8629.com/ys02.html",
        "https://raw.githubusercontent.com/yixiujun886/viewerjs/refs/heads/main/src/domain.js",
    ]
    # 已知可用的 API 根地址（按速度排序，越靠前越优先）
    FAST_ROOTS = [
        "https://a03.llshjf3.com",
        "https://al02.llshjf3.com",
        "https://sw02.job8629.com",
    ]
    # 备用根地址（仅当快速地址全部失败时使用）
    FALLBACK_ROOTS = [
        "https://qe02.ku93z.com",
        "https://tx01.nbnsoc.com",
        "https://ss01.58yszx1.com",
        "https://al01.ilovefhy.com",
        "https://a01.58sphapi.com",
    ]
    # 浏览器已验证此 H5 入口可正常完成注册并返回影片数据。
    WEB_URL = "https://dfsfd.ynhongji.com/"
    APP_VERSION = "2.7.6"
    CHANNEL = ""
    PAGE_SIZE = 24
    # 游客注册会按设备/IP 限频。旧代码每次 init 都生成新 UUID，OK影视在刷新
    # 配置或重复创建 Spider 时会被服务端视为批量注册，最终返回 40005。
    # 使用稳定 UUID；如需更换，仍可在 ext 中传入 device_id。
    # 新版网页使用 FingerprintJS 安装标识：fpjs- + 32 位小写十六进制。
    DEFAULT_DEVICE_ID = "fpjs-0f7d8a0a17c0b8f01020a0fb8cc39cb4"
    AUTH_FILE = ".58_auth.json"

    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

    TYPE_MAP = {
        "movie": "电影",
        "tv": "电视剧",
        "cartoon": "动漫",
        "variety": "综艺",
        "short": "短剧",
    }

    def getName(self):
        return "58影视"

    def init(self, extend):
        self.extend = extend or ""
        self.roots = []
        self.root_index = 0
        self.root = "https://a03.llshjf3.com"
        self.session = requests.Session()
        self.device_id = self.DEFAULT_DEVICE_ID
        self.secret = None
        self.config = {}
        self.image_domain = ""
        self._ready = False
        self._last_connect_error = None
        self.timeout = 10
        self._quick_timeout = 5

        if isinstance(extend, str) and extend.strip():
            try:
                cfg = json.loads(extend)
                if isinstance(cfg, dict):
                    self.PAGE_SIZE = int(cfg.get("page_size") or cfg.get("pagesize") or self.PAGE_SIZE)
                    self.UA = cfg.get("ua") or cfg.get("user_agent") or self.UA
                    if cfg.get("root"):
                        self.root = str(cfg.get("root")).rstrip("/")
                        self.roots = [self.root]
                    if cfg.get("channel"):
                        self.CHANNEL = str(cfg.get("channel"))
                    if cfg.get("device_id"):
                        self.device_id = str(cfg.get("device_id"))
                    if cfg.get("secret"):
                        self.secret = str(cfg.get("secret"))
            except Exception:
                pass

        if not self.secret:
            self._load_persisted_auth()
        self._reset_session()
        if self.secret:
            # 支持把已注册凭据放在站点 ext 中，彻底避免再次调用注册接口。
            self._AUTH_CACHE[self.root.rstrip("/")] = {
                "uuid": self.device_id,
                "secret": self.secret,
            }

    def _auth_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), self.AUTH_FILE)

    def _load_persisted_auth(self):
        try:
            with open(self._auth_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("uuid") and data.get("secret"):
                # 注册接口返回的是服务端 UUID，后续请求必须使用它作为
                # X-Device-UUID；它与注册时提交的 fpjs-* 安装标识不是同一个值。
                self.device_id = str(data["uuid"])
                self.secret = str(data["secret"])
        except Exception:
            pass

    def _save_persisted_auth(self):
        try:
            path = self._auth_path()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {"uuid": self.device_id, "secret": self.secret},
                    f,
                    ensure_ascii=False,
                )
            os.replace(tmp, path)
        except Exception:
            pass

    def _forget_persisted_auth(self):
        try:
            os.remove(self._auth_path())
        except Exception:
            pass

    def isVideoFormat(self, url):
        return None

    def manualVideoCheck(self):
        return None

    def _reset_session(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.UA,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": self.WEB_URL.rstrip("/"),
            "Referer": self.WEB_URL,
            "X-Device-UUID": self.device_id,
        })

    def _aes_cbc_decrypt_b64(self, cipher_text):
        raw = base64.b64decode(str(cipher_text).strip())
        dec = AES.new(self.BOOT_KEY, AES.MODE_CBC, self.BOOT_IV).decrypt(raw)
        return unpad(dec, AES.block_size).decode("utf-8")

    def _aes_ecb_decrypt_b64_with_secret(self, cipher_text):
        key = hashlib.sha256(str(self.secret).encode("utf-8")).digest()
        raw = base64.b64decode(str(cipher_text).strip())
        dec = AES.new(key, AES.MODE_ECB).decrypt(raw)
        return unpad(dec, AES.block_size).decode("utf-8")

    def _add_root(self, roots, url):
        url = str(url or "").strip().strip('"').rstrip("/")
        if not url or not url.startswith(("http://", "https://")):
            return
        if url not in roots:
            roots.append(url)

    def _parse_root_text(self, text):
        text = str(text or "").strip()
        if not text:
            return []
        plain = text
        if "http" not in plain:
            try:
                plain = self._aes_cbc_decrypt_b64(plain)
            except Exception:
                plain = text
        roots = []
        for item in re.split(r"[,\n\r\t ]+", plain):
            self._add_root(roots, item)
        return roots

    def _load_dns_roots(self):
        roots = []
        doh_urls = [
            "https://dns.alidns.com/resolve",
            "https://sm2.doh.pub/dns-query",
            "https://223.5.5.5/resolve",
        ]

        def _fetch_doh(doh):
            try:
                r = requests.get(doh, params={"name": self.DNS_DOMAIN, "type": "16"}, headers={"User-Agent": self.UA}, timeout=self._quick_timeout)
                data = r.json()
                result = []
                for ans in data.get("Answer") or []:
                    if int(ans.get("type") or 0) != 16:
                        continue
                    val = str(ans.get("data") or "").strip().strip('"')
                    for root in self._parse_root_text(val):
                        result.append(root)
                return result
            except Exception:
                return []

        # 并发请求所有 DNS，取第一个成功的结果
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(_fetch_doh, doh): doh for doh in doh_urls}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    roots.extend(result)
                    break
        return roots

    def _load_hop_roots(self):
        roots = []

        def _fetch_hop(url):
            try:
                r = requests.get(url, headers={"User-Agent": self.UA, "Referer": self.WEB_URL}, timeout=self._quick_timeout)
                return self._parse_root_text(r.text)
            except Exception:
                return []

        # 并发请求所有跳转地址
        with ThreadPoolExecutor(max_workers=len(self.HOP_URLS)) as executor:
            futures = {executor.submit(_fetch_hop, url): url for url in self.HOP_URLS}
            for future in as_completed(futures):
                result = future.result()
                for root in result:
                    self._add_root(roots, root)
        return roots

    def _load_roots(self):
        # 如果已经加载过根地址，则直接返回
        if self.roots:
            return self.roots
        
        roots = []
        
        # 并发加载 DNS 和 HOP（两者独立，可并行）
        with ThreadPoolExecutor(max_workers=2) as executor:
            dns_future = executor.submit(self._load_dns_roots)
            hop_future = executor.submit(self._load_hop_roots)
            dns_roots = dns_future.result()
            hop_roots = hop_future.result()

        for root in dns_roots + hop_roots:
            self._add_root(roots, root)

        # domain.js 低优先级
        try:
            r = requests.get(self.DOMAIN_JS, headers={"User-Agent": self.UA, "Referer": self.WEB_URL}, timeout=self._quick_timeout)
            for root in self._parse_root_text(r.text):
                self._add_root(roots, root)
        except Exception:
            pass

        if self.root:
            self._add_root(roots, self.root)
        for root in self.FAST_ROOTS + self.FALLBACK_ROOTS:
            self._add_root(roots, root)
        
        # 已知可用地址排最前
        priority_order = {r: i for i, r in enumerate(self.FAST_ROOTS)}
        roots.sort(key=lambda x: priority_order.get(x, 99))
        
        self.roots = roots or list(self.FAST_ROOTS + self.FALLBACK_ROOTS)
        return self.roots

    def _register(self):
        if self.secret:
            return {"uuid": self.device_id, "secret": self.secret}
        cached = self._AUTH_CACHE.get(self.root.rstrip("/"))
        if isinstance(cached, dict) and cached.get("uuid") and cached.get("secret"):
            self.device_id = str(cached["uuid"])
            self.secret = str(cached["secret"])
            self.session.headers.update({"X-Device-UUID": self.device_id})
            return cached

        payload = {
            "app_version": self.APP_VERSION,
            "device_id": self.device_id,
            "model": "other",
            "os_version": "0.0.0",
            "platform": "Web",
            "source_domain": urlparse(self.WEB_URL).netloc,
            "channel": self.CHANNEL,
        }
        data = self._raw_request("POST", "/v1/client/auth/visitor/register", json=payload, skip_boot=True)
        if isinstance(data, dict):
            self.secret = data.get("secret") or self.secret
            if data.get("uuid"):
                self.device_id = data.get("uuid")
                self.session.headers.update({"X-Device-UUID": self.device_id})
        if not self.secret:
            raise RuntimeError("游客注册未返回 secret")
        self._AUTH_CACHE[self.root.rstrip("/")] = {
            "uuid": self.device_id,
            "secret": self.secret,
        }
        self._save_persisted_auth()
        return data

    def _try_connect(self, root):
        """尝试连接单个根地址，返回是否成功"""
        self._last_connect_error = None
        try:
            self.root = root.rstrip("/")
            self._reset_session()
            auth = self._register()
            if not isinstance(auth, dict) or not self.secret:
                return False
            cfg = self._raw_request("GET", "/v1/client/app/config", skip_boot=True)
            if isinstance(cfg, dict):
                self.config = cfg
                self.image_domain = str(cfg.get("image_domain") or cfg.get("imageDomain") or "").rstrip("/")
                return True
        except Exception as e:
            self._last_connect_error = e
            msg = str(e)
            # 只有明确的认证失效才丢弃凭据；网络超时不能导致重新注册。
            if "设备不存在" in msg or "401" in msg or "secret" in msg:
                self._AUTH_CACHE.pop(root.rstrip("/"), None)
                self.secret = None
                self._forget_persisted_auth()
        return False

    def _raise_if_rate_limited(self):
        err = self._last_connect_error
        if err and ("40005" in str(err) or "注册过于频繁" in str(err)):
            raise RuntimeError(
                "58影视游客注册被限频（40005）。请勿反复刷新；"
                "脚本现已使用固定设备 UUID，限频解除后只需成功注册一次。"
            )

    def _ensure(self):
        if self._ready:
            return
        
        last_err = None
        
        # ===== 极速模式：直接尝试已知可用地址，跳过预加载 =====
        # 第一轮：只试 FAST_ROOTS（通常第一个就能成功）
        for root in self.FAST_ROOTS:
            if self._try_connect(root):
                self._ready = True
                return
            last_err = self._last_connect_error or last_err
            self._raise_if_rate_limited()
        
        # 第二轮：如果快速地址全失败，才加载完整根地址列表并探测
        if not self.roots:
            self.roots = self._load_roots()

        # 并发探测，找存活地址
        alive_roots = []
        with ThreadPoolExecutor(max_workers=min(len(self.roots), 5)) as executor:
            future_to_root = {executor.submit(self._quick_probe, root): root for root in self.roots}
            for future in as_completed(future_to_root):
                if future.result():
                    alive_roots.append(future_to_root[future])
        
        roots_to_try = alive_roots if alive_roots else self.roots
        
        for idx, root in enumerate(roots_to_try):
            try:
                original_idx = self.roots.index(root) if root in self.roots else idx
                self.root_index = original_idx
                if self._try_connect(root):
                    self._ready = True
                    return
                last_err = self._last_connect_error or last_err
                self._raise_if_rate_limited()
            except Exception as e:
                last_err = e
                if "40005" in str(e) or "注册过于频繁" in str(e):
                    raise
                continue
                
        if last_err:
            raise last_err
        raise RuntimeError("58影视没有可用的 API 节点")

    def _quick_probe(self, root):
        """快速探测根地址是否可达"""
        try:
            url = root.rstrip("/") + "/v1/client/app/config"
            r = requests.get(url, headers={"User-Agent": self.UA}, timeout=self._quick_timeout)
            # 未携带游客身份时正常响应通常是 401 JSON。这里只排除网关 HTML
            # 和失效节点，真正可用性仍由 _try_connect 的注册+配置请求确认。
            return r.status_code == 200 and "<html" not in (r.text or "").lower()
        except Exception:
            return False


    def _raw_request(self, method, path, params=None, json=None, skip_boot=False):
        url = path if str(path).startswith("http") else self.root.rstrip("/") + path
        r = self.session.request(method, url, params=params, json=json, timeout=self.timeout)
        r.raise_for_status()
        text = (r.text or "").strip()
        if self.secret and text and not text.startswith("{") and not text.startswith("["):
            try:
                text = self._aes_ecb_decrypt_b64_with_secret(text)
            except Exception:
                pass
        if not text:
            return {}
        data = json_loads(text)
        if isinstance(data, dict) and "code" in data:
            try:
                code = int(data.get("code"))
            except Exception:
                code = data.get("code")
            if code == 0:
                return data.get("data")
            raise RuntimeError("接口错误 %s: %s" % (data.get("code"), data.get("msg") or data.get("message") or "未知错误"))
        if isinstance(data, str) and data.lstrip().lower().startswith(("<html", "<!doctype")):
            raise RuntimeError("接口节点返回了网关页面")
        return data

    def _request(self, method, path, params=None, json=None):
        self._ensure()
        try:
            return self._raw_request(method, path, params=params, json=json)
        except Exception as e:
            # 认证类错误不能靠立即重试解决，重复注册只会延长服务端限频。
            msg = str(e)
            if (
                "40005" in msg
                or "注册过于频繁" in msg
                or "设备不存在" in msg
                or "游客注册" in msg
            ):
                raise
            # 如果请求失败，将 _ready 设为 False，以便 _ensure 重新寻找可用根地址
            self._ready = False
            # 再次尝试确保根地址可用并重新发送请求
            self._ensure()
            # 如果第二次 _raw_request 仍然失败，则抛出异常
            return self._raw_request(method, path, params=params, json=json)

    def _join_url(self, domain, path):
        path = str(path or "").strip()
        domain = str(domain or "").strip().rstrip("/")
        if not path:
            return ""
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if domain:
            return domain + (path if path.startswith("/") else "/" + path)
        return urljoin(self.WEB_URL, path)

    def _play_headers(self, url=""):
        host = ""
        try:
            from urllib.parse import urlparse
            u = urlparse(url or self.WEB_URL)
            host = u.scheme + "://" + u.netloc + "/" if u.scheme and u.netloc else self.WEB_URL
        except Exception:
            host = self.WEB_URL
        return {
            "User-Agent": self.UA,
            "Accept": "*/*",
            "Connection": "keep-alive",
            "Referer": self.WEB_URL,
            "Origin": self.WEB_URL.rstrip("/"),
        }

    def _proxy_url(self, url, typ="m3u8"):
        url = str(url or "").strip()
        if not url:
            return ""
        try:
            return self.getProxyUrl() + "&type=" + typ + "&url=" + quote(url, safe="")
        except Exception:
            return url

    def _cover(self, vod):
        imgs = vod.get("coverImages") or vod.get("cover_images") or vod.get("screenshot_images") or []
        if isinstance(imgs, str):
            return self._join_url(self.image_domain, imgs)
        if not isinstance(imgs, list) or not imgs:
            return ""
        chosen = None
        for img in imgs:
            if isinstance(img, dict) and img.get("type") == "vertical":
                chosen = img
                break
        if chosen is None:
            chosen = imgs[0]
        url = chosen.get("url") if isinstance(chosen, dict) else str(chosen)
        return self._join_url(self.image_domain, url)

    def _names(self, value):
        if not value:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            out = []
            for x in value:
                if isinstance(x, dict):
                    out.append(str(x.get("name") or x.get("title") or ""))
                else:
                    out.append(str(x))
            return ",".join([x for x in out if x])
        if isinstance(value, dict):
            return str(value.get("name") or value.get("title") or "")
        return str(value)

    def _tag_names(self, tags):
        if not tags:
            return ""
        if isinstance(tags, list):
            return ",".join([str(x.get("name") if isinstance(x, dict) else x) for x in tags if x])
        return str(tags)

    def _vod_item(self, vod):
        vid = vod.get("id") or vod.get("video_id") or ""
        typ = vod.get("type") or ""
        remarks = vod.get("state") or vod.get("remark") or vod.get("premiumBlurb") or vod.get("premium_blurb") or ""
        if not remarks:
            ep = vod.get("episodes") or 0
            serial = vod.get("serial") or 0
            if ep:
                remarks = "全%s集" % ep if serial >= ep else "更新至%s/%s集" % (serial, ep)
        return {
            "vod_id": "%s|%s" % (vid, typ) if typ else str(vid),
            "vod_name": str(vod.get("title") or vod.get("vod_name") or "").strip(),
            "vod_pic": self._cover(vod),
            "vod_remarks": str(remarks or ""),
        }

    def _home_videos(self):
        """首页推荐列表。部分壳只调用 homeContent，不调用 homeVideoContent，所以抽成公共方法。"""
        # 优化：只发送一次请求（API 已确认使用 {"page": 1, "size": N} 格式）
        try:
            data = self._request("POST", "/v1/client/filter/video", json={"page": 1, "size": self.PAGE_SIZE})
            videos = data.get("list", []) if isinstance(data, dict) else []
            vods = [self._vod_item(x) for x in videos if isinstance(x, dict)]
            if vods:
                return vods
        except Exception:
            pass
        # 兜底：部分软件首页必须返回非空 list，否则显示"找不到数据"。
        try:
            return self.categoryContent("movie", "1", False, {}).get("list", [])
        except Exception:
            return []

    def homeContent(self, filter):
        classes = [{"type_id": k, "type_name": v} for k, v in self.TYPE_MAP.items()]
        result = {"class": classes, "list": self._home_videos()}
        if filter:
            result["filters"] = {k: [] for k in self.TYPE_MAP.keys()}
        return result

    def homeVideoContent(self):
        return {"list": self._home_videos()}

    def categoryContent(self, cid, pg, filter, ext):
        try:
            page = int(pg)
        except Exception:
            page = 1
        payload = {"page": page, "size": self.PAGE_SIZE}
        if cid and cid != "all":
            payload["type"] = cid
        if isinstance(ext, dict):
            for k, v in ext.items():
                if v not in (None, "", [], {}):
                    payload[k] = v
        data = self._request("POST", "/v1/client/filter/video", json=payload)
        total = data.get("total", 0) if isinstance(data, dict) else 0
        videos = data.get("list", []) if isinstance(data, dict) else []
        return {
            "list": [self._vod_item(x) for x in videos],
            "page": page,
            "pagecount": max(1, int((int(total or 0) + self.PAGE_SIZE - 1) / self.PAGE_SIZE)) if total else 999,
            "limit": self.PAGE_SIZE,
            "total": int(total or 999999),
        }

    def detailContent(self, ids):
        raw_id = str(ids[0]) if ids else ""
        vid = raw_id.split("|")[0]
        data = self._request("GET", "/v1/client/video/video/video_detail", params={"video_id": vid})
        if not isinstance(data, dict):
            return {"list": []}

        play_urls = []
        direct_urls = []
        eps = data.get("episode_list") or []
        if isinstance(eps, list):
            eps = sorted(eps, key=lambda x: int(x.get("episode") or 0) if isinstance(x, dict) else 0)
        for ep in eps:
            if not isinstance(ep, dict):
                continue
            sources = ep.get("sources") or []
            src = None
            for s in sources:
                if isinstance(s, dict) and s.get("play_url"):
                    src = s
                    break
            if not src:
                continue
            title = str(ep.get("title") or ("第%s集" % (ep.get("episode") or len(play_urls) + 1))).strip()
            safe_title = title.replace("#", " ").replace("$", " ")
            url = self._join_url(src.get("domain"), src.get("play_url"))
            if url:
                # 默认给 OK影视走本地代理 m3u8，避免部分 CDN 分片请求缺 Referer/UA 时低速、卡顿或断流。
                proxied = self._proxy_url(url, "m3u8")
                if proxied and proxied != url:
                    play_urls.append(safe_title + "$" + proxied)
                    direct_urls.append(safe_title + "$" + url)
                else:
                    play_urls.append(safe_title + "$" + url)

        persons = data.get("persons") or []
        actor = ""
        director = ""
        if isinstance(persons, list):
            actors, directors = [], []
            for p in persons:
                if not isinstance(p, dict):
                    continue
                name = p.get("name") or p.get("person_name") or p.get("title")
                role = str(p.get("type") or p.get("role") or "")
                if not name:
                    continue
                if "导演" in role or "director" in role.lower():
                    directors.append(str(name))
                else:
                    actors.append(str(name))
            actor = ",".join(actors)
            director = ",".join(directors)

        vod = {
            "vod_id": raw_id,
            "vod_name": str(data.get("title") or ""),
            "vod_pic": self._cover(data),
            "type_name": self.TYPE_MAP.get(str(data.get("type") or ""), str(data.get("type") or "")),
            "vod_year": str(data.get("year") or data.get("years") or ""),
            "vod_area": self._names(data.get("areas") or data.get("area")),
            "vod_lang": self._names(data.get("language")),
            "vod_actor": actor or self._names(data.get("actors")),
            "vod_director": director or self._names(data.get("director")),
            "vod_remarks": str(data.get("state") or "全%s集" % data.get("episodes") if data.get("episodes") else ""),
            "vod_content": str(data.get("content") or data.get("blurb") or data.get("premium_blurb") or ""),
            "vod_play_from": "58影视代理$$$58影视直连" if direct_urls else "58影视",
            "vod_play_url": "#".join(play_urls) + ("$$$" + "#".join(direct_urls) if direct_urls else ""),
        }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        url = str(id or "").strip()
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": self._play_headers(url),
        }

    def searchContentPage(self, key, quick, page):
        try:
            pg = int(page)
        except Exception:
            pg = 1
        keyword = str(key or "").strip()

        # 前端搜索页实际调用：GET /v1/client/search/video?keyword=...&page=...&size=...&type=...
        # type 为空时即"全部"。接口返回字段为 list、total、type_list。
        try:
            params = {"keyword": keyword, "page": pg, "size": self.PAGE_SIZE}
            data = self._request("GET", "/v1/client/search/video", params=params)
            if isinstance(data, dict):
                items = data.get("list") or []
                total = int(data.get("total") or len(items) or 0)
                return {
                    "list": [self._vod_item(x) for x in items if isinstance(x, dict)],
                    "page": pg,
                    "pagecount": max(1, int((total + self.PAGE_SIZE - 1) / self.PAGE_SIZE)) if total else 1,
                    "limit": self.PAGE_SIZE,
                    "total": total,
                }
        except Exception:
            pass

        # 兜底：若搜索接口临时异常，则从各分类最新页中做本地关键词匹配，保证 OK影视不空白崩溃。
        kw = keyword.lower()
        videos = []
        seen = set()
        for typ in self.TYPE_MAP.keys():
            try:
                data = self._request("POST", "/v1/client/filter/video", json={"page": pg, "size": self.PAGE_SIZE, "type": typ})
                items = data.get("list", []) if isinstance(data, dict) else []
                for item in items:
                    name = str(item.get("title") or "")
                    sub = self._names(item.get("subtitle"))
                    if (not kw) or kw in name.lower() or kw in sub.lower():
                        vid = item.get("id")
                        if vid in seen:
                            continue
                        seen.add(vid)
                        videos.append(self._vod_item(item))
            except Exception:
                continue
        return {"list": videos, "page": pg, "pagecount": 1 if videos else 0, "limit": self.PAGE_SIZE, "total": len(videos)}

    def searchContent(self, key, quick, pg="1"):
        return self.searchContentPage(key, quick, pg)

    def localProxy(self, params):
        try:
            typ = params.get("type") if isinstance(params, dict) else ""
            if typ == "m3u8":
                return self.proxyM3u8(params)
            if typ in ("media", "ts", "key"):
                return self.proxyMedia(params)
        except Exception as e:
            return [500, "text/plain", str(e).encode("utf-8"), {}]
        return None

    def proxyM3u8(self, params):
        url = unquote(params.get("url", ""))
        r = requests.get(url, headers=self._play_headers(url), timeout=self.timeout, allow_redirects=True)
        r.encoding = "utf-8"
        base = r.url or url
        text = r.text or ""

        def repl_uri(m):
            raw = m.group(1)
            abs_url = urljoin(base, raw)
            ptype = "m3u8" if ".m3u8" in abs_url.lower() else "media"
            return 'URI="' + self._proxy_url(abs_url, ptype) + '"'

        out = []
        for line in text.splitlines():
            s = line.strip()
            if not s:
                out.append(line)
                continue
            if s.startswith("#"):
                if "URI=" in s:
                    s = re.sub(r'URI="([^"]+)"', repl_uri, s)
                out.append(s)
                continue
            abs_url = urljoin(base, s)
            ptype = "m3u8" if ".m3u8" in abs_url.lower() else "media"
            out.append(self._proxy_url(abs_url, ptype))
        body = ("\n".join(out) + "\n").encode("utf-8")
        return [200, "application/vnd.apple.mpegurl", body, {"Access-Control-Allow-Origin": "*"}]

    def proxyMedia(self, params):
        url = unquote(params.get("url", ""))
        r = requests.get(url, headers=self._play_headers(url), timeout=self.timeout, stream=False, allow_redirects=True)
        ctype = r.headers.get("Content-Type") or "application/octet-stream"
        return [200, ctype, r.content, {"Access-Control-Allow-Origin": "*"}]


def json_loads(text):
    try:
        return json.loads(text)
    except Exception:
        return text
