# -*- coding: utf-8 -*-
import sys
import json
import re
import time
import ssl
import hmac
import hashlib
import urllib.request
import urllib.parse
from urllib.error import URLError, HTTPError

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider(object):
        def __init__(self):
            pass


class Spider(BaseSpider):
    def __init__(self):
        super(Spider, self).__init__()
        self.host = "https://lgzyz.xyz"
        self.parse_host = "https://vv00.xyz"
        self.parse_path = "/"          # 解析入口路径，可改为 "/play"
        self.demo_host = "https://yanshi.lgzyz.xyz"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Encoding": "identity"
        }
        self.ctx = ssl._create_unverified_context()
        self.brandActor = ""
        self.brandDirector = ""
        self.play_cache = {}

    def getName(self):
        return "蓝光资源"

    def init(self, extend=""):
        if extend:
            try:
                cfg = json.loads(extend) if isinstance(extend, str) else extend
                if isinstance(cfg, dict):
                    if cfg.get("host"):
                        self.host = cfg["host"].rstrip("/")
                    if cfg.get("api"):
                        self.host = cfg["api"].rstrip("/")
                    if cfg.get("parse_host"):
                        self.parse_host = cfg["parse_host"].rstrip("/")
                    if cfg.get("parse_path"):
                        self.parse_path = cfg["parse_path"]
                    if cfg.get("demo_host"):
                        self.demo_host = cfg["demo_host"].rstrip("/")
            except Exception:
                pass

    # ---------- HTTP ----------
    def _http_get(self, url, headers=None, timeout=10):
        h = dict(self.headers)
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        for _ in range(3):
            try:
                with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", "ignore")
            except Exception:
                time.sleep(0.5)
        return ""

    def _http_post_json(self, url, data_dict, headers=None, timeout=10):
        h = dict(self.headers)
        h["Content-Type"] = "application/json"
        if headers:
            h.update(headers)
        body = json.dumps(data_dict, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=h)
        for _ in range(3):
            try:
                with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", "ignore")
            except Exception:
                time.sleep(0.5)
        return ""

    @staticmethod
    def _url_add_query(url, params):
        """安全追加查询参数：自动判断用 ? 还是 &。"""
        if not params:
            return url
        sep = "&" if "?" in url else "?"
        return "%s%s%s" % (url, sep, urllib.parse.urlencode(params))

    def _format_remarks(self, brand, meta):
        brand = (brand or "").strip()
        meta = (meta or "").strip()
        if brand and meta:
            return "%s | %s" % (brand, meta)
        return brand or meta

    # ---------- 首页/分类/详情/搜索（保持不变） ----------
    def homeContent(self, filter):
        result = {"class": [], "filters": {}, "list": []}
        url = "%s/api.php/provide/vod/?ac=list" % self.host
        txt = self._http_get(url)
        if not txt:
            return result
        try:
            data = json.loads(txt)
            raw_classes = data.get("class", [])
            parent_ids = {c["type_pid"] for c in raw_classes if c.get("type_pid", 0) != 0}
            clean_classes = []
            for c in raw_classes:
                tid = c.get("type_id")
                pid = c.get("type_pid", 0)
                if tid in parent_ids and pid == 0:
                    continue
                clean_classes.append({
                    "type_id": str(tid),
                    "type_name": c.get("type_name", "")
                })
            result["class"] = clean_classes
            first_tid = clean_classes[0]["type_id"] if clean_classes else "6"
            first_page = self.categoryContent(first_tid, 1, filter, {})
            result["list"] = first_page.get("list", [])
        except Exception:
            pass
        return result

    def homeVideoContent(self):
        res = self.homeContent(False)
        return {"list": res.get("list", [])}

    def categoryContent(self, tid, pg, filter, extend):
        result = {"list": [], "page": int(pg), "pagecount": 1, "limit": 20, "total": 0}
        url = "%s/api.php/provide/vod/?ac=detail&t=%s&pg=%s" % (self.host, tid, pg)
        txt = self._http_get(url)
        if not txt:
            result["list"].append({
                "vod_id": "diag",
                "vod_name": "[诊断] 分类接口超时或为空",
                "vod_pic": "",
                "vod_remarks": "t=%s&pg=%s" % (tid, pg)
            })
            return result
        try:
            data = json.loads(txt)
            result["page"] = int(data.get("page", pg))
            result["pagecount"] = int(data.get("pagecount", 1))
            result["limit"] = int(data.get("limit", 20))
            result["total"] = int(data.get("total", 0))
            vod_list = []
            for it in data.get("list", []):
                vod_list.append({
                    "vod_id": str(it.get("vod_id", "")),
                    "vod_name": it.get("vod_name", ""),
                    "vod_pic": it.get("vod_pic", ""),
                    "vod_remarks": self._format_remarks(self.brandDirector, it.get("vod_remarks", "")),
                    "vod_year": it.get("vod_year", "")
                })
            result["list"] = vod_list
        except Exception as e:
            result["list"].append({
                "vod_id": "diag",
                "vod_name": "[诊断] 分类解析异常: %s" % e,
                "vod_pic": "",
                "vod_remarks": "t=%s" % tid
            })
        return result

    def detailContent(self, ids):
        result = {"list": []}
        id_str = ",".join(str(i) for i in ids)
        url = "%s/api.php/provide/vod/?ac=detail&ids=%s" % (self.host, id_str)
        txt = self._http_get(url)
        if not txt:
            return result
        try:
            data = json.loads(txt)
            for it in data.get("list", []):
                vod_play_from = it.get("vod_play_from", "")
                vod_play_url = it.get("vod_play_url", "")
                vod = {
                    "vod_id": str(it.get("vod_id", "")),
                    "vod_name": it.get("vod_name", ""),
                    "vod_pic": it.get("vod_pic", ""),
                    "type_name": it.get("type_name", ""),
                    "vod_year": it.get("vod_year", ""),
                    "vod_area": it.get("vod_area", ""),
                    "vod_remarks": self._format_remarks(self.brandDirector, it.get("vod_remarks", "")),
                    "vod_actor": self.brandActor if not it.get("vod_actor") else "%s / %s" % (self.brandActor, it.get("vod_actor")),
                    "vod_director": self.brandDirector if not it.get("vod_director") else "%s / %s" % (self.brandDirector, it.get("vod_director")),
                    "vod_content": it.get("vod_content", "").strip(),
                    "vod_play_from": vod_play_from,
                    "vod_play_url": vod_play_url
                }
                result["list"].append(vod)
        except Exception:
            pass
        return result

    # ---------- 核心修复：解析 ----------
    def _resolve_stream(self, target_url):
        now = time.time()
        if target_url in self.play_cache:
            cache_url, exp = self.play_cache[target_url]
            if now < exp:
                return cache_url

        demo_domain = urllib.parse.urlparse(self.demo_host).hostname or ""
        referer = "%s/" % self.demo_host.rstrip("/")
        parse_base = self.parse_host.rstrip("/")

        # 1) 打开解析入口页（修复：默认带 "/"，并支持自定义 parse_path）
        entry_path = self.parse_path or "/"
        page_url = self._url_add_query(parse_base + entry_path, {"url": target_url})
        html = self._http_get(page_url, headers={"Referer": referer}, timeout=8)
        if not html or "hishow.php" not in html:
            # 兼容根路径不带 "/" 的写法
            page_url = self._url_add_query(parse_base, {"url": target_url})
            html = self._http_get(page_url, headers={"Referer": referer}, timeout=8)
        if not html:
            return ""

        # 2) 提取 session
        sess_m = re.search(r"hishow\.php\?session=([A-Za-z0-9]+)", html)
        if not sess_m:
            return ""
        sess = sess_m.group(1)

        js_url = "%s/godoo/hishow.php?session=%s" % (parse_base, sess)
        js_txt = self._http_get(js_url, headers={"Referer": page_url}, timeout=8)
        if not js_txt:
            return ""

        sec_m = re.search(r"SECRET\s*=\s*['\"]([a-f0-9]+)['\"]", js_txt)
        if not sec_m:
            return ""
        secret = sec_m.group(1)

        rand_m = re.search(r"RANDOM_INDICATORS\s*=\s*(\[[\s\S]*?\])", js_txt)
        rand_keys = []
        if rand_m:
            try:
                rand_keys = json.loads(rand_m.group(1))
            except Exception:
                rand_keys = []

        getters = {
            "plugins": "Chrome PDF Viewer",
            "mimeTypes": 2,
            "timezone": -480,
            "language": "zh-CN",
            "hardwareConcurrency": 8,
            "deviceMemory": 8,
            "platform": "Win32",
            "audioFingerprint": "audio_placeholder",
            "fontList": "fonts_placeholder",
            "canvasNoise": "canvas_noise",
            "webglVendor": "Google Inc. (NVIDIA)"
        }
        random_data = {k: getters.get(k, "") for k in rand_keys}

        payload = {
            "sessionId": sess,
            "isTop": True,
            "isRealBrowser": True,
            "isTrusted": False,
            "deviceId": "-1827491203",
            "domain": demo_domain,   # 修复：随 demo_host 动态变化
            "randomIndicators": random_data
        }
        payload_str = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        sig = hmac.new(secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

        boom_url = "%s/godoo/boom.php" % parse_base
        self._http_post_json(boom_url, {"payload": payload, "signature": sig}, headers={
            "Referer": page_url,
            "Origin": parse_base
        }, timeout=8)

        # 3) 播放页地址（修复：绝对/相对路径兼容）
        vurl_m = re.search(r"videoUrl\s*:\s*['\"]([^'\"]+)['\"]", html)
        if not vurl_m:
            return ""
        vurl = vurl_m.group(1).strip()
        if re.match(r"^https?://", vurl):
            playback_url = vurl
        else:
            playback_url = parse_base + "/" + vurl.lstrip("/")

        pb_html = self._http_get(playback_url, headers={"Referer": page_url}, timeout=8)
        if not pb_html:
            return ""

        spec_m = re.search(r"window\.specialPlayConfig\s*=\s*(\{[\s\S]*?\})\s*;", pb_html)
        if spec_m:
            spec_txt = spec_m.group(1)
            ps_m = re.search(r"playSources\s*:\s*(\[[\s\S]*?\])\s*[,}]", spec_txt)
            play_sources = []
            if ps_m:
                try:
                    play_sources = json.loads(ps_m.group(1))
                except Exception:
                    play_sources = []

            for src in play_sources:
                mac_src = src.get("mac_play_source", "") if isinstance(src, dict) else ""
                if not mac_src:
                    continue
                # 修复：用 _url_add_query 自动处理 ? / &
                if mac_src == "dujia":
                    res_url = self._url_add_query(playback_url, {"resolve_dujia_plain": "1"})
                else:
                    res_url = self._url_add_query(playback_url, {
                        "resolve_special_plain": "1",
                        "resolve_source": mac_src
                    })

                res_txt = self._http_get(res_url, headers={
                    "Referer": playback_url,
                    "Accept": "application/json"
                }, timeout=8)
                if res_txt:
                    try:
                        res_json = json.loads(res_txt)
                        stream_url = res_json.get("url", "")
                        if not stream_url and isinstance(res_json.get("data"), dict):
                            stream_url = res_json["data"].get("url", "")
                        if stream_url and stream_url.startswith("http"):
                            self.play_cache[target_url] = (stream_url, now + 1800)
                            return stream_url
                    except Exception:
                        pass

        norm_m = re.search(r"normalPlayUrl\s*:\s*['\"]([^'\"]+)['\"]", pb_html)
        if norm_m:
            norm_url = norm_m.group(1).strip()
            if norm_url and norm_url.startswith("http"):
                self.play_cache[target_url] = (norm_url, now + 1800)
                return norm_url

        return ""

    def playerContent(self, flag, id, vipFlags):
        raw_url = (id or "").strip()
        if raw_url.startswith("http://") or raw_url.startswith("https://"):
            # 直链直接播放
            if self.isVideoFormat(raw_url):
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": raw_url,
                    "header": self.headers
                }
            # 非直链一律尝试解析（不再硬编码 lgvideo.xyz，域名换了也能工作）
            try:
                resolved = self._resolve_stream(raw_url)
                if resolved:
                    return {
                        "parse": 0,
                        "playUrl": "",
                        "url": resolved,
                        "header": {
                            "User-Agent": self.headers["User-Agent"]
                        }
                    }
            except Exception:
                pass
        return {
            "parse": 1,
            "playUrl": "",
            "url": raw_url,
            "header": self.headers
        }

    def searchContent(self, key, quick, pg="1"):
        result = {"list": [], "page": int(pg), "pagecount": 1, "limit": 20, "total": 0}
        url = "%s/api.php/provide/vod/?ac=detail&wd=%s&pg=%s" % (self.host, urllib.parse.quote(key), pg)
        txt = self._http_get(url)
        if not txt:
            return result
        try:
            data = json.loads(txt)
            result["page"] = int(data.get("page", pg))
            result["pagecount"] = int(data.get("pagecount", 1))
            result["limit"] = int(data.get("limit", 20))
            result["total"] = int(data.get("total", 0))
            vod_list = []
            for it in data.get("list", []):
                vod_list.append({
                    "vod_id": str(it.get("vod_id", "")),
                    "vod_name": it.get("vod_name", ""),
                    "vod_pic": it.get("vod_pic", ""),
                    "vod_remarks": self._format_remarks(self.brandDirector, it.get("vod_remarks", "")),
                    "vod_year": it.get("vod_year", "")
                })
            result["list"] = vod_list
        except Exception:
            pass
        return result

    def isVideoFormat(self, url):
        if not url:
            return False
        clean = url.split("?")[0].lower()
        return any(clean.endswith(ext) for ext in [".m3u8", ".mp4", ".ts"])


if __name__ == "__main__":
    spider = Spider()
    spider.init("")

    print("=== 1. 分类测试 ===")
    home = spider.homeContent(False)
    classes = home.get("class", [])
    print("分类数:", len(classes))
    for c in classes[:5]:
        print("  -", c["type_id"], c["type_name"])

    print("\n=== 2. 首页列表测试 ===")
    h_list = home.get("list", [])
    print("首页推荐条数:", len(h_list))
    if h_list:
        print("首条:", h_list[0]["vod_name"], h_list[0]["vod_id"])

    print("\n=== 3. 详情与分集测试 ===")
    detail_res = spider.detailContent(["34590"])
    d_list = detail_res.get("list", [])
    if d_list:
        vod = d_list[0]
        print("影片名称:", vod["vod_name"])
        print("线路:", vod["vod_play_from"])
        episodes = vod["vod_play_url"].split("#")
        print("分集总数:", len(episodes))
        first_ep = episodes[0].split("$")
        ep_name, ep_url = first_ep[0], first_ep[1]
        print("首集:", ep_name, ep_url)

        print("\n=== 4. 取流解析测试 ===")
        play_res = spider.playerContent(vod["vod_play_from"], ep_url, [])
        print("parse:", play_res.get("parse"))
        print("流地址:", play_res.get("url"))
        stream_url = play_res.get("url", "")
        if stream_url.startswith("http"):
            chk_req = urllib.request.Request(stream_url, headers=play_res.get("header", {}))
            with urllib.request.urlopen(chk_req, context=spider.ctx, timeout=8) as r:
                print("取流验证状态码:", r.status, "Content-Type:", r.headers.get("Content-Type"))

    print("\n=== 5. 搜索测试 ===")
    search_res = spider.searchContent("战狼", False, "1")
    s_list = search_res.get("list", [])
    print("搜索条数:", len(s_list))
    if s_list:
        print("搜索首条:", s_list[0]["vod_name"], s_list[0]["vod_id"])