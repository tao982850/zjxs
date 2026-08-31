#!/usr/bin/env python3
# QQ群:807916734 @ID圥忈
# -*- coding: utf-8 -*-
"""
猫头鹰影视 TVBox 爬虫（零依赖版）
================================================================
目标 App:  猫头鹰 com.xysm.stdog.mr.mh v4.0.0（qijiappapi 框架）
API:  http://103.217.190.91:2233（云端配置自动跟随换 IP）
搜索: MeiliSearch http://103.217.190.91:7700（39 万片库，key 随 initV119 下发）

协议链（全部实测打通）:
  1. getPublicKey → RSA-2048 公钥；handshake(RSA加密的128hex session_key) → session_id(24h)
  2. 业务端点：响应 data = base64(AES-CBC(key=hex(sk[:32]), iv=hex(sk[32:64]))) → JSON
  3. 播放 vodParse：url 参数 = base64(AES-CBC(key=iv="8Sq6BSwBrvwXKY6z")) → {"json":{url,m3u8}}
"""
import json
import base64
import random
import time
import re
import urllib.request
import urllib.parse
import ssl

try:
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_v1_5 as _PKCS1
    from Crypto.Cipher import AES as _PAES
except ImportError:  # TVBox 内置 python 无 pycryptodome 时走纯 Python 兜底
    from _purecrypto import RSA, PKCS1, AESCBC  # noqa

_UA = "okhttp/3.12.1"
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

CFG = {
    "host": "http://103.217.190.91:2233",
    "site": "https://maotouyinghubei.oss-cn-wuhan-lr.aliyuncs.com/mtyzx.txt",
    "device_id": "a1b2c3d4e5f67890",
    "nsKey": "8Sq6BSwBrvwXKY6z",
    "app_version": "4.0.0",
    "meili_index": "mac_vod_myy",
}


def _http(url, data=None, headers=None, timeout=20):
    hdrs = {"User-Agent": _UA, "app-platform": "android"}
    if headers:
        hdrs.update(headers)
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    else:
        req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
        return r.read().decode("utf-8", "replace")


def _hex(n):
    return "".join(random.choice("0123456789abcdef") for _ in range(n))


def _cbc_dec(key, iv, data):
    out = _PAES.new(key, _PAES.MODE_CBC, iv).decrypt(data)
    pad = out[-1]
    return out[:-pad] if 1 <= pad <= 16 else out


def _cbc_enc(key, iv, data):
    pad = 16 - len(data) % 16
    return _PAES.new(key, _PAES.MODE_CBC, iv).encrypt(data + bytes([pad]) * pad)


# ================= 客户端（会话 + 业务） =================
class _Client:
    def __init__(self, cfg):
        self.cfg = cfg
        h = cfg["host"]
        # 云端配置自动跟随（服务器换 IP）
        try:
            r = _http(cfg["site"], timeout=6)
            dom = (json.loads(r) or {}).get("domain") or ""
            if dom.startswith("http"):
                h = dom
        except Exception:
            pass
        self.host = h
        self.sk = _hex(128)
        pub = json.loads(_http(h + "/api.php/qijiappapi.index/getPublicKey"))
        pk = pub["data"]["public_key"].replace("\\/", "/")
        k = RSA.import_key(pk)
        enc = base64.b64encode(_PKCS1.new(k).encrypt(self.sk.encode())).decode()
        r = _http(h + "/api.php/qijiappapi.index/handshake", {
            "encrypted_key": enc, "device_id": cfg["device_id"],
            "timestamp": int(time.time())})
        j = json.loads(r)
        if j.get("code") != 1:
            raise Exception("handshake fail: " + str(j.get("msg")))
        self.sid = j["data"]["session_id"]
        self._k = bytes.fromhex(self.sk[:32])
        self._iv = bytes.fromhex(self.sk[32:64])
        self._ns = cfg["nsKey"].encode()
        self.expire = time.time() + 12 * 3600

    def call(self, ep, params=None):
        if time.time() > self.expire:
            raise Exception("session expired")
        r = _http(self.host + f"/api.php/qijiappapi.index/{ep}", params or {},
                  {"app-session-id": self.sid})
        j = json.loads(r)
        if j.get("code") != 1:
            return None
        d = j.get("data")
        if isinstance(d, str) and len(d) > 8:
            try:
                return json.loads(_cbc_dec(self._k, self._iv,
                                           base64.b64decode(d)).decode("utf-8", "replace"))
            except Exception:
                return None
        return d

    def ns_enc(self, plain):
        return base64.b64encode(_cbc_enc(self._ns, self._ns, plain.encode())).decode()

    def vod_parse(self, parse_key, ptype, ep_url):
        r = self.call("vodParse", {
            "url": self.ns_enc(ep_url), "parse_api": parse_key, "token": "",
            "player_parse_type": ptype, "base_api": parse_key + ep_url})
        if isinstance(r, dict):
            inner = r.get("json")
            if isinstance(inner, str):
                try:
                    return json.loads(inner)
                except Exception:
                    return r
        return r or {}


# ================= Spider =================
class Spider:
    def __init__(self):
        self.cfg = dict(CFG)
        self._cli = None
        self._init_cache = None          # initV119 结果缓存
        self._detail_cache = {}          # 详情缓存
        self._play_cache = {}            # 播放解析缓存
        self._meili_key = None
        self._types = {}                 # type_id → name
        self._filters = {}               # type_id → 筛选配置
        self._search_cache = {}          # 快搜缓存（TVBox 逐字触发）

    # ---------- 初始化 ----------
    def init(self, ext=""):
        if isinstance(ext, dict):
            self.cfg.update(ext)
        else:
            try:
                s = (ext or "").strip()
                if s:
                    if s.startswith("http"):
                        self.cfg.update(json.loads(_http(s, timeout=8)))
                    else:
                        self.cfg.update(json.loads(s))
            except Exception:
                pass
        self._warmup()

    def _client(self):
        if self._cli is None or time.time() > self._cli.expire:
            self._cli = _Client(self.cfg)
        return self._cli

    def _warmup(self):
        try:
            c = self._client()
            init = c.call("initV119", {"device_id": self.cfg["device_id"],
                                       "app_version": self.cfg["app_version"]})
            if not init:
                return
            self._init_cache = (init, time.time())
            cfg = init.get("config", {})
            self._meili_key = cfg.get("meili_master_key") or ""
            for t in init.get("type_list", []):
                tid = t.get("type_id")
                if tid in (0, None):
                    continue
                self._types[tid] = t.get("type_name", str(tid))
                # 筛选项从 type_extend 动态生成
                fs = []
                try:
                    ext = json.loads(t.get("type_extend") or "{}")
                    for key, label in (("class", "类型"), ("area", "地区"), ("year", "年份"), ("lang", "语言")):
                        raw = str(ext.get(key) or "").strip()
                        if not raw:
                            continue
                        opts = [x for x in raw.split(",") if x.strip()]
                        # 地区名超长的截断（台湾那串政治声明）
                        opts = [{"n": (o[:6] + "…") if len(o) > 8 else o, "v": o} for o in opts]
                        fs.append({"key": key, "name": label,
                                   "value": [{"n": "全部", "v": ""}] + opts})
                except Exception:
                    pass
                if fs:
                    self._filters[tid] = fs
        except Exception:
            pass
        if not self._types:
            self._types = {1: "电影", 2: "电视剧", 3: "动漫", 4: "综艺",
                           22: "短剧", 6: "纪录片", 21: "体育", 23: "直播"}

    # ---------- 首页 ----------
    def homeContent(self, filter1=1):
        classes = [{"type_id": k, "type_name": v} for k, v in self._types.items()]
        out = {"class": classes}
        if self._filters:
            out["filters"] = {str(k): v for k, v in self._filters.items()}
        return out

    # ---------- 分类列表 ----------
    def categoryContent(self, tid, pg=1, filter1=1, ext=None):
        # TVBox 内核可能传 dict 或 json 字符串
        if isinstance(ext, str):
            try:
                ext = json.loads(ext) if ext.strip() else {}
            except Exception:
                ext = {}
        ext = ext or {}
        try:
            page = int(pg)
        except (TypeError, ValueError):
            page = 1
        try:
            tid = int(tid)
        except (TypeError, ValueError):
            pass
        c = self._client()
        r = c.call("typeFilterVodList", {
            "type_id": tid, "page": page,
            "area": ext.get("area", ""), "year": ext.get("year", ""),
            "lang": ext.get("lang", ""), "class": ext.get("class", ""),
            "sort": ext.get("sort", "")})
        vods = []
        for v in (r or {}).get("recommend_list", []):
            vods.append({
                "vod_id": str(v.get("vod_id", "")),
                "vod_name": v.get("vod_name", ""),
                "vod_pic": (v.get("vod_pic") or "").replace("\\/", "/"),
                "vod_remarks": v.get("vod_remarks", ""),
            })
        more = len(vods) >= 20
        return {"list": vods, "page": page,
                "pagecount": page + 1 if more else page,
                "limit": "20", "total": (page + 30) if more else page * 20}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        vid = str(ids[0])
        # 缓存命中直接返回（换集/换线路频繁触发）
        if vid in self._detail_cache:
            return self._detail_cache[vid]
        try:
            c = self._client()
            r = c.call("vodDetail3", {"vod_id": int(vid)})
        except (TypeError, ValueError):
            return {"list": []}
        if not r:
            return {"list": []}
        vod = r.get("vod", {})
        play_froms, play_urls = [], []
        for p in r.get("vod_play_list", []):
            pi = p.get("player_info", {})
            show = pi.get("show") or p.get("from", "")
            urls = p.get("urls")
            if isinstance(urls, str):
                urls = self._parse_urls(urls)
            if not urls:
                continue
            eps = []
            for i, e in enumerate(urls):
                name = str(e.get("name", i + 1))
                u = e.get("url", "")
                # 直链直接存；密文 token 编码携带解析参数
                if u.startswith("http"):
                    tok = "D|" + u
                else:
                    tok = "P|" + base64.b64encode(json.dumps(
                        {"p": pi.get("parse", ""), "t": pi.get("player_parse_type", "1"),
                         "u": u}, ensure_ascii=False).encode()).decode()
                eps.append(name + "$" + tok)
            play_froms.append(show)
            play_urls.append("#".join(eps))
        v = {
            "vod_id": vid,
            "vod_name": vod.get("vod_name", ""),
            "vod_pic": (vod.get("vod_pic") or "").replace("\\/", "/"),
            "type_name": (vod.get("vod_class") or "").split(",")[0],
            "vod_year": vod.get("vod_year", ""),
            "vod_area": vod.get("vod_area", ""),
            "vod_actor": vod.get("vod_actor", ""),
            "vod_director": vod.get("vod_director", ""),
            "vod_content": (vod.get("vod_blurb") or "").replace("\\n", "\n"),
            "vod_remarks": vod.get("vod_remarks", ""),
            "vod_play_from": "$$$".join(play_froms),
            "vod_play_url": "$$$".join(play_urls),
        }
        ret = {"list": [v]}
        self._detail_cache[vid] = ret
        # 缓存上限
        if len(self._detail_cache) > 80:
            self._detail_cache.pop(next(iter(self._detail_cache)))
        return ret

    @staticmethod
    def _parse_urls(s):
        """服务器返回的 urls 是 Python 单引号风格字符串"""
        s = s.strip()
        try:
            return json.loads(s)
        except Exception:
            pass
        try:
            return eval(s)  # noqa: S307 受控输入
        except Exception:
            pairs = re.findall(r"'name'\s*:\s*'([^']*)'.*?'url'\s*:\s*'([^']*)'", s, re.S)
            return [{"name": n, "url": u} for n, u in pairs]

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags=None):
        # 解析缓存（同集重播/断点续看直接命中）
        ck = str(id)
        if ck in self._play_cache:
            hit = self._play_cache[ck]
            if time.time() - hit[0] < 1800:      # m3u8 链接 30 分钟缓存
                return hit[1]
            self._play_cache.pop(ck, None)
        tok = str(id)
        try:
            kind, payload = tok.split("|", 1)
        except ValueError:
            return {"url": tok, "header": {"User-Agent": _UA}}
        if kind == "D":                          # 直链
            out = {"url": payload, "header": {"User-Agent": _UA}}
        else:                                    # 需服务器解析
            try:
                info = json.loads(base64.b64decode(payload))
            except Exception:
                return {"url": "", "msg": "参数错误"}
            try:
                c = self._client()
                r = c.vod_parse(info.get("p", ""), info.get("t", "1"), info.get("u", ""))
                real = (r or {}).get("url") or ""
                real = real.replace("\\/", "/")
            except Exception:
                real = ""
            if not real:
                return {"url": "", "msg": "解析失败，请换线路"}
            out = {"url": real, "header": {"User-Agent": _UA}}
        if len(self._play_cache) > 150:
            self._play_cache.pop(next(iter(self._play_cache)))
        self._play_cache[ck] = (time.time(), out)
        return out

    # ---------- 搜索（MeiliSearch 39 万片库） ----------
    def searchContent(self, key, quick=None, pg=None):
        return self._search(key, pg)

    def searchContentPage(self, key, quick=None, pg=None):
        return self._search(key, pg)

    def _search(self, key, pg=None):
        key = str(key or "").strip()
        if not key:
            return {"list": []}
        try:
            page = int(pg) if pg not in (None, "", 0, "0") else 1
        except (TypeError, ValueError):
            page = 1
        # 快搜缓存 5 分钟（TVBox 快搜逐字符触发，同词不重查）
        ck = key + "|" + str(page)
        now = time.time()
        for k in list(self._search_cache):
            if now - self._search_cache[k][0] > 300:
                self._search_cache.pop(k, None)
        if ck in self._search_cache:
            return self._search_cache[ck][1]
        limit, offset = 20, (page - 1) * 20
        out = []
        try:
            host = self.cfg.get("meili_host") or \
                "http://" + self.cfg["host"].split("//")[-1].split(":")[0] + ":7700"
            if not host.startswith("http"):
                host = "http://" + host
            mk = self._meili_key or self._fetch_meili_key()
            if mk:
                body = json.dumps({"q": key, "limit": limit, "offset": offset}).encode()
                req = urllib.request.Request(
                    f"{host}/indexes/{self.cfg.get('meili_index', 'mac_vod_myy')}/search",
                    data=body, method="POST",
                    headers={"Content-Type": "application/json",
                             "Authorization": "Bearer " + mk,
                             "User-Agent": _UA})
                with urllib.request.urlopen(req, timeout=12, context=_SSL) as r:
                    res = json.loads(r.read().decode())
                for h in res.get("hits", []):
                    out.append({
                        "vod_id": str(h.get("vod_id", "")),
                        "vod_name": h.get("vod_name", ""),
                        "vod_pic": (h.get("vod_pic") or "").replace("\\/", "/"),
                        "vod_remarks": h.get("vod_remarks", ""),
                    })
        except Exception:
            pass
        # MeiliSearch 失败 → 分类页兜底
        if not out:
            out = self._search_fallback(key)
        ret = {"list": out[:25], "page": page,
               "pagecount": page + 1 if len(out) >= 20 else page}
        self._search_cache[ck] = (time.time(), ret)
        return ret

    def _fetch_meili_key(self):
        try:
            init = self._client().call("initV119", {
                "device_id": self.cfg["device_id"],
                "app_version": self.cfg["app_version"]})
            mk = (init or {}).get("config", {}).get("meili_master_key") or ""
            self._meili_key = mk
            return mk
        except Exception:
            return ""

    def _search_fallback(self, key):
        out = []
        key_l = key.lower()
        for tid in list(self._types.keys())[:4]:
            try:
                r = self._client().call("typeFilterVodList",
                                        {"type_id": tid, "page": 1, "area": "",
                                         "year": "", "lang": "", "class": "", "sort": ""})
                for v in (r or {}).get("recommend_list", []):
                    if key_l in (v.get("vod_name") or "").lower():
                        out.append({
                            "vod_id": str(v.get("vod_id", "")),
                            "vod_name": v.get("vod_name", ""),
                            "vod_pic": (v.get("vod_pic") or "").replace("\\/", "/"),
                            "vod_remarks": v.get("vod_remarks", ""),
                        })
            except Exception:
                continue
            if len(out) >= 20:
                break
        return out


# ================= TVBox 模块级入口（内核直调） =================
_SP = None
_SP_T = 0.0


def _ensure():
    global _SP, _SP_T
    if _SP is None or time.time() - _SP_T > 8 * 3600:
        _SP = Spider()
        _SP_T = time.time()
    return _SP


def init(ext=""):
    return _ensure().init(ext)


def homeContent(filter1=1):
    return _ensure().homeContent(filter1)


def homeVideoContent():
    return {"list": []}


def categoryContent(tid, pg=1, filter1=1, ext=None):
    return _ensure().categoryContent(tid, pg, filter1, ext)


def detailContent(ids):
    return _ensure().detailContent(ids)


def playerContent(flag, id, vipFlags=None):
    return _ensure().playerContent(flag, id, vipFlags)


def searchContent(key, quick=0, pg=None):
    return _ensure().searchContent(key, quick, pg)


def searchContentPage(key, quick=0, pg=None):
    return _ensure().searchContentPage(key, quick, pg)


# 实例方法兼容（部分内核自动实例化 Spider 类）
