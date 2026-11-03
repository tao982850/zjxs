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
                    if "host" in cfg and cfg["host"]:
                        self.host = cfg["host"].rstrip("/")
                    if "api" in cfg and cfg["api"]:
                        self.host = cfg["api"].rstrip("/")
                    if "parse_host" in cfg and cfg["parse_host"]:
                        self.parse_host = cfg["parse_host"].rstrip("/")
                    if "demo_host" in cfg and cfg["demo_host"]:
                        self.demo_host = cfg["demo_host"].rstrip("/")
            except Exception:
                pass

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
        body = json.dumps(data_dict, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=h)
        for _ in range(3):
            try:
                with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", "ignore")
            except Exception:
                time.sleep(0.5)
        return ""

    def _format_remarks(self, brand, meta):
        brand = (brand or "").strip()
        meta = (meta or "").strip()
        if brand and meta:
            return "%s | %s" % (brand, meta)
        return brand or meta

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

    def _resolve_stream(self, target_url):
        now = time.time()
        if target_url in self.play_cache:
            cache_url, exp = self.play_cache[target_url]
            if now < exp:
                return cache_url

        page_url = "%s?url=%s" % (self.parse_host, urllib.parse.quote(target_url, safe=""))
        html = self._http_get(page_url, headers={"Referer": "%s/" % self.demo_host}, timeout=8)
        if not html:
            return ""

        sess_m = re.search(r"hishow\.php\?session=([a-f0-9]+)", html)
        if not sess_m:
            return ""
        sess = sess_m.group(1)

        js_url = "%s/godoo/hishow.php?session=%s" % (self.parse_host, sess)
        js_txt = self._http_get(js_url, headers={"Referer": page_url}, timeout=8)
        if not js_txt:
            return ""

        sec_m = re.search(r"var SECRET\s*=\s*['\"]([a-f0-9]+)['\"]", js_txt)
        if not sec_m:
            return ""
        secret = sec_m.group(1)

        rand_m = re.search(r"var RANDOM_INDICATORS\s*=\s*(\[[^\]]+\])", js_txt)
        rand_keys = json.loads(rand_m.group(1)) if rand_m else []

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
            "domain": "yanshi.lgzyz.xyz",
            "randomIndicators": random_data
        }
        payload_str = json.dumps(payload, separators=(",", ":"))
        sig = hmac.new(secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

        boom_url = "%s/godoo/boom.php" % self.parse_host
        boom_res = self._http_post_json(boom_url, {"payload": payload, "signature": sig}, headers={
            "Referer": page_url,
            "Origin": self.parse_host
        }, timeout=8)

        vurl_m = re.search(r'videoUrl:\s*"([^"]+)"', html)
        if not vurl_m:
            return ""
        playback_url = "%s%s" % (self.parse_host, vurl_m.group(1))

        pb_html = self._http_get(playback_url, headers={"Referer": page_url}, timeout=8)
        if not pb_html:
            return ""

        spec_m = re.search(r"window\.specialPlayConfig\s*=\s*(\{[\s\S]*?\});", pb_html)
        if spec_m:
            spec_txt = spec_m.group(1)
            ps_m = re.search(r"playSources:\s*(\[[^\]]+\])", spec_txt)
            play_sources = json.loads(ps_m.group(1)) if ps_m else []
            for src in play_sources:
                mac_src = src.get("mac_play_source", "")
                if not mac_src:
                    continue
                if mac_src == "dujia":
                    res_url = "%s&resolve_dujia_plain=1" % playback_url
                else:
                    res_url = "%s&resolve_special_plain=1&resolve_source=%s" % (playback_url, mac_src)
                res_txt = self._http_get(res_url, headers={
                    "Referer": playback_url,
                    "Accept": "application/json"
                }, timeout=8)
                if res_txt:
                    try:
                        res_json = json.loads(res_txt)
                        stream_url = res_json.get("url", "")
                        if stream_url and stream_url.startswith("http"):
                            self.play_cache[target_url] = (stream_url, now + 1800)
                            return stream_url
                    except Exception:
                        pass

        norm_m = re.search(r"normalPlayUrl:\s*['\"]([^'\"]+)['\"]", pb_html)
        if norm_m:
            norm_url = norm_m.group(1).strip()
            if norm_url and norm_url.startswith("http"):
                self.play_cache[target_url] = (norm_url, now + 1800)
                return norm_url

        return ""

    def playerContent(self, flag, id, vipFlags):
        raw_url = id
        if raw_url.startswith("http://") or raw_url.startswith("https://"):
            if "lgvideo.xyz" in raw_url:
                try:
                    resolved = self._resolve_stream(raw_url)
                    if resolved:
                        return {
                            "parse": 0,
                            "playUrl": "",
                            "url": resolved,
                            "header": {
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                            }
                        }
                except Exception:
                    pass
            elif ".m3u8" in raw_url or ".mp4" in raw_url:
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": raw_url,
                    "header": self.headers
                }
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
