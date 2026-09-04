
import base64
import hashlib
import json
import re
import sys
import time
from urllib.parse import parse_qs, quote, unquote, urlsplit

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

requests.packages.urllib3.disable_warnings()

try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def init(self, extend=""):
            pass


class Spider(Spider):
    def getName(self):
        return "速搜"

    def init(self, extend=""):
        try:
            super().init(extend)
        except Exception:
            pass
        self.host = "43.248.128.251"
        self.api_bases = [
            "http://43.248.128.251:24302/2233/api.php/app",
            "http://43.248.128.251:21581/2233/api.php/app",
            "http://43.248.128.251:19115/2233/api.php/app",
            "http://43.248.128.251:20882/2233/api.php/app",
            "http://43.248.128.251:2233/api.php/app",
        ]
        self.api_base_dynamic = ""
        self.jx_ports = [30213, 30785, 30499, 30462, 36122, 31617, 37763]
        self.config_ports = [32589, 15281, 35673, 18216]
        self.jx_path = "/jx/123pan/10086.php"
        self.ua_dart = "Dart/3.9 (dart:io)"
        self.ua_android = "Mozilla/5.0 (Linux; Android 16; 23046RP50C Build/BP4A.251205.006; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/150.0.7871.47 Safari/537.36"
        self.android_id = "a59aec7097c16a63"
        self.device_id = "39AF593DF90F81DF36AA82877CF1D17E"
        self.token = "f490df808e31c8e096c5f257719d3705"
        self.login_uuid = "d2a84a9a3353d670af48b16ce7318840"
        self.app_id = "com.sjz.ss"
        self.jx_m = "MnMlbQuKQHoGHf2bnlnwTW9n1omwD+7f9INCoBRJWRU="
        self.config_key = b"ahsp123456789012"
        self.jqq_key = b"opasdfghopasdfgh"
        self.pan_api = "https://api.123278.com/api/share/get"
        self.download_host = "https://download-cdn.cjjd19.com"
        self.vip_host = "https://1135-vip-download-cdn.123295.com"
        self.active_jx_url = ""
        self.active_jx_m = ""
        self.active_jqq_url = ""
        self.config_expires_at = 0
        self._token_refreshed = False
        self._login_attempted = False
        self._sniff_whitelist = []
        self._sniff_blacklist = []

        # Multi-source configs (from dy.json)
        self.wc_api = "https://www.hkybqufgh.com/api"
        self.wc_key = "cb808529bae6b6be45ecfab29a4889bc"
        self.yl_host = "https://www.xz8.cc"
        self.hs_host = "http://v.rbotv.cn/v3/home"
        self.hs_key = "7gp0bnd2sr85ydii2j32pcypscoc4w6c7g5spl"

        self.session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.4, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self._parse_extend(extend)

    # ==================== Config / Auth ====================

    def _parse_extend(self, extend):
        if not extend:
            return
        text = str(extend).strip()
        if not text:
            return
        parsed = None
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except Exception:
                pass
        elif "=" in text:
            try:
                parsed = dict(parse_qs(text).items())
                parsed = {k: v[0] if isinstance(v, list) else v for k, v in parsed.items()}
            except Exception:
                pass
        if parsed:
            if parsed.get("token"):
                self.token = str(parsed["token"])
            if parsed.get("device_id"):
                self.device_id = str(parsed["device_id"])
            if parsed.get("android_id"):
                self.android_id = str(parsed["android_id"])
            if parsed.get("login_uuid"):
                self.login_uuid = str(parsed["login_uuid"])
        elif len(text) >= 16:
            self.token = text

    def _try_login(self):
        try:
            params = {"device_id": self.device_id, "android_id": self.android_id, "app_id": self.app_id}
            headers = {"User-Agent": self.ua_dart, "Content-Type": "application/x-www-form-urlencoded"}
            for base in self._get_api_bases():
                try:
                    response = self.session.post(
                        f"{base}/login",
                        data=params, headers=headers, timeout=8, verify=False
                    )
                    root = response.json()
                    if root.get("code") in (0, 1, 200):
                        data = root.get("data") or {}
                        new_token = data.get("token") or root.get("token")
                        if new_token and new_token != self.token:
                            self.token = new_token
                            self._token_refreshed = False
                        if data.get("login_uuid"):
                            self.login_uuid = data["login_uuid"]
                        return
                except Exception:
                    continue
        except Exception:
            pass

    def _refresh_token(self):
        if self._token_refreshed:
            return False
        self._token_refreshed = True
        old_token = self.token
        self._try_login()
        if self.token != old_token:
            self.config_expires_at = 0
            return True
        return False

    def _get(self, url, headers=None, timeout=18):
        response = self.session.get(url, headers=headers or {}, timeout=timeout, verify=False)
        response.raise_for_status()
        return response.text

    def _get_api_bases(self):
        if self.api_base_dynamic:
            return [self.api_base_dynamic] + self.api_bases
        return self.api_bases

    def _fetch_api(self, path, auth=False):
        headers = {"User-Agent": self.ua_dart}
        if auth:
            headers["token"] = self.token
        last = None
        for base in self._get_api_bases():
            try:
                return self._get(f"{base}{path}", headers)
            except Exception as error:
                last = error
        raise last or RuntimeError("API request failed")

    def _fetch_api_no_auth(self, path):
        headers = {"User-Agent": self.ua_dart}
        last = None
        for base in self._get_api_bases():
            try:
                return self._get(f"{base}{path}", headers)
            except Exception as error:
                last = error
        raise last or RuntimeError("API request failed (no auth)")

    @staticmethod
    def _aes_ecb_decrypt(value, key):
        raw = base64.b64decode(value.strip())
        return unpad(AES.new(key, AES.MODE_ECB).decrypt(raw), AES.block_size).decode("utf-8")

    def _decrypt_detail(self, value):
        chars = list(value.strip())
        password = [""] * 10
        for index in range(9, -1, -1):
            position = max(len(chars) - (3 * (1 << index) + 1), 0)
            password[index] = chars.pop(position)
        key = hashlib.sha256("".join(password).encode("utf-8")).hexdigest()[:16].encode("utf-8")
        return self._aes_ecb_decrypt("".join(chars), key)

    def _decrypt_player(self, html):
        shuffled = re.search(r"const\s+shuffledBase64\s*=\s*'([^']+)'", html, re.S)
        restore = re.search(r"const\s+restoreKey\s*=\s*JSON\.parse\('([^']+)'\)", html, re.S)
        if not shuffled or not restore:
            raise ValueError("parser params missing")
        source = shuffled.group(1)
        key = json.loads(restore.group(1))
        if len(source) != len(key):
            raise ValueError("restore table length mismatch")
        result = [""] * len(source)
        for current, position in enumerate(key):
            result[position] = source[current]
        return json.loads(base64.b64decode("".join(result)).decode("utf-8"))

    def _sniff_video_url(self, html):
        urls = re.findall(r'https?://[^\s"\'<>]+', html)
        whitelist = [w.strip() for w in self._sniff_whitelist if w.strip()]
        blacklist = [b.strip() for b in self._sniff_blacklist if b.strip()]
        for url in urls:
            if whitelist and not any(wl in url for wl in whitelist):
                continue
            if any(bl in url for bl in blacklist):
                continue
            return url
        for url in urls:
            if any(ext in url.lower() for ext in [".m3u8", ".mp4", ".cjjd"]):
                return url
        return ""

    def _load_parsers(self, force=False):
        if not force and self.config_expires_at > time.time() and self.active_jx_url and self.active_jqq_url:
            return
        no_auth_headers = {
            "User-Agent": self.ua_dart,
            "Accept": "application/json; charset=utf-8",
            "Content-Type": "application/json; charset=utf-8",
        }
        auth_headers = dict(no_auth_headers)
        auth_headers["token"] = self.token
        last = None
        for headers in (no_auth_headers, auth_headers):
            for port in self.config_ports:
                try:
                    encrypted = self._get(f"http://{self.host}:{port}/dy.json", headers)
                    root = json.loads(self._aes_ecb_decrypt(encrypted, self.config_key))
                    for source in root.get("zypath", []):
                        if str(source.get("\u6e90\u7c7b\u578b", "")) == "APP":
                            url = str(source.get("\u8bf7\u6c42\u94fe\u63a5", ""))
                            if url:
                                self.api_base_dynamic = url.rstrip("/")
                                break
                    jx_url = ""
                    jx_m = ""
                    jqq_url = ""
                    for group in root.get("jxpath", []):
                        keyword = str(group.get("\u89e3\u6790\u5173\u952e\u8bcd", "")).lower()
                        for config in group.get("\u89e3\u6790\u914d\u7f6e", []):
                            api = str(config.get("jxapi", ""))
                            if "/123pan/10086.php" in api:
                                parsed = urlsplit(api)
                                current_m = parse_qs(parsed.query).get("m", [""])[0]
                                if current_m:
                                    jx_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                                    jx_m = current_m
                                self._sniff_whitelist = str(config.get("jxb", "")).split(",")
                                self._sniff_blacklist = str(config.get("jxh", "")).split(",")
                            if keyword == "jqq" or ("/jx/api-appjx.php" in api and parse_qs(urlsplit(api).query).get("t", [""])[0] == "2233"):
                                jqq_url = api
                    if jx_url:
                        self.active_jx_url = jx_url
                        self.active_jx_m = jx_m
                    if jqq_url:
                        self.active_jqq_url = jqq_url
                    if self.active_jx_url or self.active_jqq_url:
                        self.config_expires_at = time.time() + 600
                        return
                    raise ValueError("empty parser config")
                except Exception as error:
                    last = error
            if self.active_jx_url or self.active_jqq_url:
                break
        if not force and self._refresh_token():
            return self._load_parsers(True)
        if not self.active_jx_url:
            self.active_jx_url = f"http://{self.host}:{self.jx_ports[0]}{self.jx_path}"
            self.active_jx_m = self.jx_m
        if not self.active_jqq_url:
            self.active_jqq_url = f"http://{self.host}:{self.jx_ports[0]}/jx/api-appjx.php?t=2233"
        if not self._sniff_whitelist:
            self._sniff_whitelist = [".cjjd", ".mp4"]
        if not self._sniff_blacklist:
            self._sniff_blacklist = ["?auth-key", ".php", ".json", ".jpg", ".png"]
        self.config_expires_at = time.time() + 300

    # ==================== List / Home ====================

    @staticmethod
    def _video_list(items):
        result = []
        for item in items or []:
            vod_name = item.get("vod_name", "")
            vod_id = str(item.get("vod_id", ""))
            result.append({
                "vod_id": f"ss@@{quote(vod_name)}@@{vod_id}",
                "vod_name": vod_name,
                "vod_pic": item.get("vod_pic", ""),
                "vod_remarks": item.get("vod_remarks", "")
            })
        return result

    @staticmethod
    def _values(values):
        return [{"n": name, "v": value} for name, value in values]

    def _filters(self, type_id):
        types = {
            "1": ["剧情", "喜剧", "动作", "爱情", "科幻", "动画", "悬疑", "惊悚", "恐怖", "犯罪", "冒险", "奇幻", "战争", "历史", "传记", "家庭"],
            "2": ["剧情", "喜剧", "动作", "爱情", "玄幻", "科幻", "悬疑", "惊悚", "恐怖", "犯罪", "传记", "历史", "战争"],
            "3": ["真人秀", "脱口秀", "音乐", "歌舞", "喜剧", "竞技", "旅游", "美食", "纪实"],
            "4": ["动画", "动作", "冒险", "奇幻", "科幻", "校园", "恋爱", "搞笑", "热血", "悬疑", "治愈"]
        }
        areas = ["大陆", "美国", "香港", "台湾", "日本", "韩国", "英国", "法国", "德国", "意大利", "西班牙", "印度", "泰国", "俄罗斯"]
        years = [str(year) for year in range(2026, 2009, -1)] + ["2000-2009", "1990-1999", "1980-1989"]
        return [
            {"key": "class", "name": "类型", "init": "", "value": self._values([("全部", "")] + [(item, item) for item in types.get(type_id, [])])},
            {"key": "area", "name": "地区", "init": "", "value": self._values([("全部", "")] + [(item, item) for item in areas])},
            {"key": "year", "name": "年份", "init": "", "value": self._values([("全部", "")] + [(item, item) for item in years])},
            {"key": "by", "name": "排序", "init": "time", "value": self._values([("最新", "time"), ("热度", "hits"), ("评分", "score")])}
        ]

    def homeContent(self, filter):
        classes = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "3", "type_name": "综艺"}
        ]
        result = {"class": classes, "list": []}
        result["filters"] = {item["type_id"]: self._filters(item["type_id"]) for item in classes} if filter else {}
        return result

    def homeVideoContent(self):
        try:
            root = json.loads(self._fetch_api("/index_video"))
            data = root.get("list") or root.get("data") or {}
            videos = []
            for category in data.get("categories", []):
                videos.extend(self._video_list(category.get("vlist", [])))
            return {"list": videos}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg)
            path = f"/video?tid={quote(str(tid), safe='')}&pg={page}"
            for key in ("class", "area", "year", "by"):
                value = str((extend or {}).get(key, ""))
                if value:
                    path += f"&{key}={quote(value, safe='')}"
            root = json.loads(self._fetch_api(path))
            return {
                "page": root.get("page", page),
                "pagecount": root.get("pagecount", page),
                "limit": root.get("limit", 24),
                "total": root.get("total", 0),
                "list": self._video_list(root.get("list", []))
            }
        except Exception:
            return {"page": int(pg), "pagecount": int(pg), "limit": 24, "total": 0, "list": []}

    # ==================== Wencai (wc) source ====================

    def _wc_sign(self, params_str):
        ts = str(int(time.time() * 1000))
        raw = f"{params_str}&key={self.wc_key}&t={ts}"
        md5_val = hashlib.md5(raw.encode()).hexdigest()
        sign = hashlib.sha1(md5_val.encode()).hexdigest()
        return {"t": ts, "sign": sign, "User-Agent": "okhttp/4.9.3"}

    def _wc_search(self, keyword):
        try:
            params = f"keyword={keyword}&pageNum=1&pageSize=20"
            url = f"{self.wc_api}/mw-movie/anonymous/video/searchByWord?{params}"
            r = self.session.get(url, headers=self._wc_sign(params), timeout=12, verify=False)
            root = r.json()
            items = root.get("data", {}).get("result", {}).get("list", [])
            return [{
                "vod_id": f"wc@@{it.get('vodId')}",
                "vod_name": it.get("vodName", ""),
                "vod_pic": it.get("vodPic", ""),
                "vod_remarks": it.get("vodRemarks", "")
            } for it in items]
        except Exception:
            return []

    def _wc_detail(self, vid):
        try:
            params = f"id={vid}"
            url = f"{self.wc_api}/mw-movie/anonymous/video/detail?{params}"
            r = self.session.get(url, headers=self._wc_sign(params), timeout=12, verify=False)
            root = r.json()
            data = root.get("data", {})
            episodes = data.get("episodeList", [])
            ep_str = "#".join(
                f"第{i+1}集$wc@@{vid}@@{ep.get('nid')}"
                for i, ep in enumerate(episodes)
            )
            return {
                "vod_name": data.get("vodName", ""),
                "vod_pic": data.get("vodPic", ""),
                "vod_remarks": data.get("vodRemarks", ""),
                "vod_actor": data.get("vodActor", ""),
                "vod_director": data.get("vodDirector", ""),
                "vod_content": data.get("vodContent", ""),
                "vod_area": data.get("vodArea", ""),
                "vod_year": data.get("vodYear", ""),
                "play_from": "文采蓝光",
                "play_url": ep_str
            }
        except Exception:
            return None

    def _wc_play_url(self, vid, nid):
        try:
            params = f"clientType=3&id={vid}&nid={nid}"
            url = f"{self.wc_api}/mw-movie/anonymous/v2/video/episode/url?{params}"
            r = self.session.get(url, headers=self._wc_sign(params), timeout=12, verify=False)
            root = r.json()
            play_list = root.get("data", {}).get("list", [])
            if play_list:
                return play_list[0].get("url", "")
        except Exception:
            pass
        return ""

    # ==================== Yongle (yl) source ====================

    def _yl_search(self, keyword):
        try:
            url = f"{self.yl_host}/vodsearch/{quote(keyword)}-------------/"
            r = self.session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": self.yl_host}, timeout=12, verify=False)
            html = r.text
            ids = list(dict.fromkeys(re.findall(r'/voddetail/(\d+)/', html)))
            results = []
            for vid in ids:
                pos = html.find(f'/voddetail/{vid}/')
                context = html[max(0, pos - 200):pos + 600]
                name_m = re.search(r'<strong>(.*?)</strong>', context)
                name = name_m.group(1) if name_m else ""
                if name in ("\u5927\u5bb6\u90fd\u5728\u641c", "\u6211\u7684\u89c2\u5f71\u8bb0\u5f55", ""):
                    continue
                pic_m = re.search(r'data-original="([^"]*)"', context)
                pic = pic_m.group(1) if pic_m else ""
                if pic and not pic.startswith("http"):
                    pic = self.yl_host + pic
                rm = re.search(r'class="[^"]*pic-text[^"]*"[^>]*>(.*?)</span>', context)
                remarks = re.sub(r'<[^>]+>', '', rm.group(1)).strip() if rm else ""
                results.append({
                    "vod_id": f"yl@@{vid}",
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_remarks": remarks
                })
            return results
        except Exception:
            return []

    def _yl_detail(self, vid):
        try:
            url = f"{self.yl_host}/voddetail/{vid}/"
            r = self.session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12, verify=False)
            html = r.text

            title_m = re.search(r'<title>(.*?)</title>', html)
            name = title_m.group(1).split("\u8be6\u60c5")[0].strip() if title_m else vid
            pic_m = re.search(r'data-original="([^"]*)"', html)
            pic = pic_m.group(1) if pic_m else ""
            if pic and not pic.startswith("http"):
                pic = self.yl_host + pic

            play_links = re.findall(r'href="/play/(\d+)-(\d+)-(\d+)/"', html)
            lines_map = {}
            for vod_id, lid, eid in play_links:
                if lid not in lines_map:
                    lines_map[lid] = []
                if eid not in lines_map[lid]:
                    lines_map[lid].append(eid)

            tab_spans = re.findall(r'module-tab-item[^"]*"[^>]*>.*?<span>(.*?)</span>', html, re.DOTALL)
            line_names = [s.strip() for s in tab_spans if s.strip()]

            play_from = []
            play_urls = []
            for i, (lid, ep_ids) in enumerate(sorted(lines_map.items())):
                ln = line_names[i] if i < len(line_names) else f"\u6c38\u4e50\u7ebf\u8def{i+1}"
                play_from.append(ln)
                eps = "#".join(
                    f"\u7b2c{eid}\u96c6$yl@@{vid}@@{lid}@@{eid}"
                    for eid in sorted(ep_ids, key=lambda x: int(x) if x.isdigit() else 0)
                )
                play_urls.append(eps)

            return {
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": "",
                "vod_actor": "",
                "vod_director": "",
                "vod_content": "",
                "vod_area": "",
                "vod_year": "",
                "play_from": "$$$".join(play_from),
                "play_url": "$$$".join(play_urls)
            }
        except Exception:
            return None

    def _yl_play_url(self, vod_id, line_id, ep_id):
        try:
            url = f"{self.yl_host}/play/{vod_id}-{line_id}-{ep_id}/"
            r = self.session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": self.yl_host}, timeout=12, verify=False)
            html = r.text
            m = re.search(r'player_aaaa\s*=\s*(\{.*?\})\s*</script>', html, re.DOTALL)
            if not m:
                m = re.search(r'player_aaaa\s*=\s*(\{.*?\})', html, re.DOTALL)
            if m:
                pa = json.loads(m.group(1))
                return pa.get("url", "")
        except Exception:
            pass
        return ""

    # ==================== Beiyong (hs) source ====================

    def _hs_sign(self):
        ts = int(time.time())
        sign = hashlib.md5(f"{self.hs_key}{ts}".encode()).hexdigest()
        return ts, sign

    def _hs_search(self, keyword):
        try:
            ts, sign = self._hs_sign()
            r = self.session.post(
                f"{self.hs_host}/search",
                data={"sign": sign, "timestamp": ts, "keyword": keyword},
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "User-Agent": "okhttp-okgo/jeasonlzy"},
                timeout=12, verify=False
            )
            root = r.json()
            items = root.get("data", {}).get("list", [])
            return [{
                "vod_id": f"hs@@{it.get('vod_id')}",
                "vod_name": it.get("vod_name", ""),
                "vod_pic": it.get("vod_pic", ""),
                "vod_remarks": it.get("vod_remarks", "")
            } for it in items]
        except Exception:
            return []

    def _hs_detail(self, vid):
        try:
            ts, sign = self._hs_sign()
            r = self.session.post(
                f"{self.hs_host}/vod_details",
                data={"sign": sign, "timestamp": ts, "vod_id": vid},
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "User-Agent": "okhttp-okgo/jeasonlzy"},
                timeout=12, verify=False
            )
            root = r.json()
            data = root.get("data", {})
            play_list = data.get("vod_play_list", [])

            play_from = []
            play_urls = []
            for pi, pl in enumerate(play_list):
                urls = pl.get("urls", [])
                parse_urls = pl.get("parse_urls", [])
                ln = f"\u5907\u7528\u7ebf\u8def{pi+1}"
                eps = []
                for u in urls:
                    ep_name = str(u.get("name", ""))
                    ep_url = str(u.get("url", ""))
                    if ep_url.startswith("http"):
                        eps.append(f"{ep_name}${ep_url}")
                    elif parse_urls:
                        jx = parse_urls[0]
                        eps.append(f"{ep_name}$hs@@{quote(jx, safe='')}@@{quote(ep_url, safe='')}")
                    else:
                        eps.append(f"{ep_name}${ep_url}")
                if eps:
                    play_from.append(ln)
                    play_urls.append("#".join(eps))

            return {
                "vod_name": data.get("vod_name", ""),
                "vod_pic": data.get("vod_pic", ""),
                "vod_remarks": data.get("vod_remarks", ""),
                "vod_actor": data.get("vod_actor", ""),
                "vod_director": data.get("vod_director", ""),
                "vod_content": data.get("vod_content", ""),
                "vod_area": data.get("vod_area", ""),
                "vod_year": data.get("vod_year", ""),
                "play_from": "$$$".join(play_from),
                "play_url": "$$$".join(play_urls)
            }
        except Exception:
            return None

    def _hs_play_url(self, parse_url, ep_url):
        try:
            full_url = parse_url + ep_url
            r = self.session.get(full_url, headers={"User-Agent": "okhttp/3.12.0"}, timeout=12, verify=False)
            root = r.json()
            return root.get("url", "")
        except Exception:
            return ""

    # ==================== Multi-source detail ====================

    def _multi_source_detail(self, vod_name):
        """Search vod_name across all 3 backup sources and combine lines."""
        play_from = []
        play_urls = []
        meta = {"vod_name": vod_name, "vod_pic": "", "vod_remarks": "", "vod_actor": "", "vod_director": "", "vod_content": "", "vod_area": "", "vod_year": ""}

        # Wencai
        try:
            wc_results = self._wc_search(vod_name)
            if wc_results:
                wc_vid = wc_results[0]["vod_id"].split("@@")[1]
                wc_d = self._wc_detail(wc_vid)
                if wc_d and wc_d.get("play_url"):
                    play_from.append(wc_d["play_from"])
                    play_urls.append(wc_d["play_url"])
                    for k in meta:
                        if wc_d.get(k):
                            meta[k] = wc_d[k]
        except Exception:
            pass

        # Yongle
        try:
            yl_results = self._yl_search(vod_name)
            if yl_results:
                yl_vid = yl_results[0]["vod_id"].split("@@")[1]
                yl_d = self._yl_detail(yl_vid)
                if yl_d and yl_d.get("play_url"):
                    pf = yl_d["play_from"].split("$$$")
                    pu = yl_d["play_url"].split("$$$")
                    for i in range(min(len(pf), len(pu))):
                        if pu[i].strip():
                            play_from.append(pf[i])
                            play_urls.append(pu[i])
                    if not meta["vod_pic"] and yl_d.get("vod_pic"):
                        meta["vod_pic"] = yl_d["vod_pic"]
        except Exception:
            pass

        # Beiyong
        try:
            hs_results = self._hs_search(vod_name)
            if hs_results:
                hs_vid = hs_results[0]["vod_id"].split("@@")[1]
                hs_d = self._hs_detail(hs_vid)
                if hs_d and hs_d.get("play_url"):
                    pf = hs_d["play_from"].split("$$$")
                    pu = hs_d["play_url"].split("$$$")
                    for i in range(min(len(pf), len(pu))):
                        if pu[i].strip():
                            play_from.append(pf[i])
                            play_urls.append(pu[i])
                    if not meta["vod_pic"] and hs_d.get("vod_pic"):
                        meta["vod_pic"] = hs_d["vod_pic"]
                    if not meta["vod_actor"] and hs_d.get("vod_actor"):
                        meta["vod_actor"] = hs_d["vod_actor"]
                    if not meta["vod_content"] and hs_d.get("vod_content"):
                        meta["vod_content"] = hs_d["vod_content"]
        except Exception:
            pass

        if not play_urls:
            return None

        meta["vod_play_from"] = "$$$".join(play_from)
        meta["vod_play_url"] = "$$$".join(play_urls)
        meta["vod_id"] = vod_name
        return meta

    def _get_vod_name_from_list(self, vod_id):
        """Fetch list page to find vod_name by vod_id (fallback)."""
        try:
            for tid in ["1", "2", "3", "4"]:
                for pg in [1, 2]:
                    try:
                        root = json.loads(self._fetch_api(f"/video?tid={tid}&pg={pg}"))
                        for item in root.get("list", []):
                            if str(item.get("vod_id")) == str(vod_id):
                                return item.get("vod_name", "")
                    except Exception:
                        continue
        except Exception:
            pass
        return ""

    # ==================== Detail ====================

    @staticmethod
    def _mark_jqq_line(code, name, line):
        if str(code).lower() != "jqq" and "AI" not in str(name).upper():
            return line
        result = []
        for episode in str(line).split("#"):
            if "$" in episode:
                title, play_id = episode.split("$", 1)
                result.append(f"{title}$jqq@@{play_id}")
            else:
                result.append(f"jqq@@{episode}")
        return "#".join(result)

    def detailContent(self, ids):
        try:
            raw_id = str(ids[0])

            # Parse source-prefixed IDs
            if raw_id.startswith("wc@@"):
                vid = raw_id[4:]
                d = self._wc_detail(vid)
                if d:
                    vod = dict(d)
                    vod["vod_id"] = raw_id
                    vod["vod_play_from"] = vod.pop("play_from", "")
                    vod["vod_play_url"] = vod.pop("play_url", "")
                    return {"list": [vod]}
                return {"list": [{"vod_id": raw_id, "vod_name": "\u52a0\u8f7d\u5931\u8d25", "vod_play_from": "", "vod_play_url": ""}]}

            if raw_id.startswith("yl@@"):
                vid = raw_id[4:]
                d = self._yl_detail(vid)
                if d:
                    vod = dict(d)
                    vod["vod_id"] = raw_id
                    vod["vod_play_from"] = vod.pop("play_from", "")
                    vod["vod_play_url"] = vod.pop("play_url", "")
                    return {"list": [vod]}
                return {"list": [{"vod_id": raw_id, "vod_name": "\u52a0\u8f7d\u5931\u8d25", "vod_play_from": "", "vod_play_url": ""}]}

            if raw_id.startswith("hs@@"):
                vid = raw_id[4:]
                d = self._hs_detail(vid)
                if d:
                    vod = dict(d)
                    vod["vod_id"] = raw_id
                    vod["vod_play_from"] = vod.pop("play_from", "")
                    vod["vod_play_url"] = vod.pop("play_url", "")
                    return {"list": [vod]}
                return {"list": [{"vod_id": raw_id, "vod_name": "\u52a0\u8f7d\u5931\u8d25", "vod_play_from": "", "vod_play_url": ""}]}

            # 速搜 native: ss@@{name}@@{id} or plain id
            vod_name = ""
            vod_id = raw_id
            if raw_id.startswith("ss@@"):
                parts = raw_id.split("@@", 2)
                if len(parts) >= 3:
                    vod_name = unquote(parts[1])
                    vod_id = parts[2]

            # Try 速搜 native API
            path = f"/video_2345?id2345={quote(vod_id, safe='')}&username={quote(self.device_id, safe='')}"
            body = None

            for attempt_fn in (
                lambda: self._fetch_api_no_auth(path),
                lambda: self._fetch_api(path, auth=True),
            ):
                try:
                    body = attempt_fn()
                    if body and body.strip():
                        break
                except Exception:
                    body = None

            if (not body or not body.strip()) and not self._login_attempted:
                self._login_attempted = True
                self._try_login()
                try:
                    body = self._fetch_api(path, auth=True)
                except Exception:
                    body = None

            # If native API works, parse and return
            if body and body.strip():
                try:
                    root = json.loads(self._decrypt_detail(body))
                    data = root.get("data") or {}
                    if data.get("msg"):
                        body = None  # fall through to multi-source
                    else:
                        play_from = []
                        play_urls = []
                        seen = set()

                        for player in data.get("vod_url_with_player", []):
                            line = player.get("url", "")
                            if not line:
                                continue
                            code = player.get("code", "")
                            name = player.get("name") or code or "\u901f\u641c4K"
                            if name not in seen:
                                seen.add(name)
                                play_from.append(name)
                                play_urls.append(self._mark_jqq_line(code, name, line))

                        vpf = data.get("vod_play_from", "")
                        vpu = data.get("vod_play_url", "")
                        if vpu:
                            if vpf and "$$$" in vpf:
                                pf_names = str(vpf).split("$$$")
                                pf_urls = str(vpu).split("$$$")
                                for i in range(min(len(pf_names), len(pf_urls))):
                                    pn = pf_names[i].strip()
                                    pu = pf_urls[i].strip()
                                    if pu and pn and pn not in seen:
                                        seen.add(pn)
                                        play_from.append(pn)
                                        play_urls.append(pu)
                            elif "\u5907\u7528\u7ebf\u8def" not in seen:
                                seen.add("\u5907\u7528\u7ebf\u8def")
                                play_from.append("\u5907\u7528\u7ebf\u8def")
                                play_urls.append(vpu)

                        # Also fetch multi-source lines and append
                        if vod_name:
                            multi = self._multi_source_detail(vod_name)
                            if multi:
                                mf = multi.get("vod_play_from", "").split("$$$")
                                mu = multi.get("vod_play_url", "").split("$$$")
                                for i in range(min(len(mf), len(mu))):
                                    if mu[i].strip() and mf[i] not in seen:
                                        seen.add(mf[i])
                                        play_from.append(mf[i])
                                        play_urls.append(mu[i])

                        if not play_urls:
                            play_from.append("\u901f\u641c4K")
                            play_urls.append(vpu or "")

                        vod = {key: data.get(key, "") for key in [
                            "vod_id", "vod_name", "vod_pic", "vod_remarks", "vod_year", "vod_area",
                            "vod_actor", "vod_director", "vod_class"
                        ]}
                        vod["vod_id"] = raw_id
                        vod["vod_content"] = data.get("vod_content") or data.get("vod_blurb") or ""
                        vod["vod_play_from"] = "$$$".join(play_from)
                        vod["vod_play_url"] = "$$$".join(play_urls)
                        return {"list": [vod]}
                except Exception:
                    body = None

            # Native API failed: multi-source fallback
            if not vod_name:
                vod_name = self._get_vod_name_from_list(vod_id)

            if vod_name:
                multi = self._multi_source_detail(vod_name)
                if multi:
                    multi["vod_id"] = raw_id
                    return {"list": [multi]}

            return {"list": [{"vod_id": raw_id, "vod_name": "\u8be6\u60c5\u52a0\u8f7d\u5931\u8d25", "vod_play_from": "", "vod_play_url": ""}]}
        except Exception as error:
            sys.stderr.write(f"detailContent error: {error}\n")
            return {"list": []}

    # ==================== Search ====================

    def searchContent(self, key, quick, pg=1):
        try:
            page = int(pg)
            keyword = str(key)
            results = []

            # Try 速搜 native search
            try:
                path = f"/search?pg={page}&text={quote(keyword, safe='')}"
                body = None
                try:
                    body = self._fetch_api_no_auth(path)
                except Exception:
                    body = None
                if not body or not body.strip():
                    try:
                        body = self._fetch_api(path, auth=True)
                    except Exception:
                        body = None
                if body and body.strip():
                    root = json.loads(body)
                    results.extend(self._video_list(root.get("list", [])))
            except Exception:
                pass

            # If native search empty, try all 3 backup sources
            if not results:
                results.extend(self._wc_search(keyword))
                results.extend(self._yl_search(keyword))
                results.extend(self._hs_search(keyword))

            return {"page": page, "pagecount": page + 1 if results else page, "limit": 24, "total": len(results), "list": results}
        except Exception:
            return {"list": []}

    # ==================== Player ====================

    def _resolve_share(self, video_id):
        headers = {"User-Agent": self.ua_android, "X-Requested-With": self.app_id}
        candidates = []
        try:
            self._load_parsers(False)
            if self.active_jx_url and self.active_jx_m:
                candidates.append((self.active_jx_url, self.active_jx_m))
        except Exception:
            pass
        candidates.extend((f"http://{self.host}:{port}{self.jx_path}", self.jx_m) for port in self.jx_ports)
        last = None
        for base_url, current_m in candidates:
            try:
                url = f"{base_url}?t={quote(self.token, safe='')}&m={quote(current_m, safe='')}&url={quote(str(video_id), safe='')}"
                response = self._get(url, headers)
                try:
                    root = self._decrypt_player(response)
                    data = root.get("data") or {}
                    if root.get("code") == 200 and data:
                        return data
                except (ValueError, json.JSONDecodeError):
                    pass
                sniffed = self._sniff_video_url(response)
                if sniffed:
                    return {"_direct_url": sniffed, "wjjfxid": "", "wjfxurlid": ""}
                if response.lstrip().startswith("{"):
                    root = json.loads(response)
                    data = root.get("data") or {}
                    if root.get("code") == 200 and data:
                        return data
                raise ValueError("parse failed")
            except Exception as error:
                last = error
        raise last or RuntimeError("123Pan parse failed")

    def _real_video(self, video_id):
        data = self._resolve_share(video_id)
        if data.get("_direct_url"):
            direct = data["_direct_url"]
            if direct and self.download_host in direct and self.vip_host:
                direct = direct.replace(self.download_host, self.vip_host)
            return direct
        timestamp = int(time.time())
        auth_key = f"{timestamp}-{timestamp - 973591068}-{self.login_uuid}"
        params = (
            f"auth-key={quote(auth_key, safe='')}&limit=1&next=1&orderBy=share_id&orderDirection=desc&SharePwd="
            f"&ParentFileId={quote(str(data.get('wjjfxid', '')), safe='')}&shareKey={quote(str(data.get('wjfxurlid', '')), safe='')}"
            "&Page=1&event=homeListFile&operateType=4&OrderId=&superAdmin=null"
        )
        headers = {
            "User-Agent": self.ua_android, "platform": "android", "app-version": "72",
            "x-app-version": "2.4.10", "x-channel": "1002", "loginuuid": self.login_uuid,
            "devicename": "Android Device", "devicetype": "2510DRK44C", "osversion": "Android_16"
        }
        root = json.loads(self._get(f"{self.pan_api}?{params}", headers))
        info = (root.get("data") or {}).get("InfoList") or []
        if root.get("code") != 0 or not info:
            raise ValueError(root.get("message") or "123Pan empty")
        direct = info[0].get("DownloadUrl", "")
        if direct and self.download_host in direct and self.vip_host:
            direct = direct.replace(self.download_host, self.vip_host)
        direct = re.sub(r"(?i)(filename=[^&]*?)\.(jpg|jpeg|png|webp)(?=&|$)", r"\1.mp4", direct)
        if "auto_redirect=" not in direct:
            direct += ("&" if "?" in direct else "?") + "auto_redirect=1"
        if "ndcp=" not in direct:
            direct += "&ndcp=1"
        return direct

    def _jqq_request_url(self, video_id):
        self._load_parsers(False)
        parts = str(video_id).split("&")
        url = self.active_jqq_url + quote(parts[0], safe="")
        for part in parts[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                url += f"&{quote(k, safe='')}={quote(v, safe='')}"
            else:
                url += f"&{quote(part, safe='')}"
        return url

    def _resolve_jqq(self, video_id):
        last = None
        for attempt in range(2):
            try:
                if attempt:
                    self.config_expires_at = 0
                    self._load_parsers(True)
                encrypted = self._get(self._jqq_request_url(video_id), {
                    "User-Agent": self.ua_android, "Accept": "application/json, text/plain, */*"
                })
                root = json.loads(encrypted) if encrypted.lstrip().startswith("{") else json.loads(self._aes_ecb_decrypt(encrypted, self.jqq_key))
                if root.get("code") == 200 and root.get("url"):
                    return root["url"]
                raise ValueError(root.get("msg") or "AI parse failed")
            except Exception as error:
                last = error
                self.active_jqq_url = ""
        raise last or RuntimeError("AI parse failed")

    def _make_header(self, extra=None):
        header = {"User-Agent": self.ua_android}
        if extra:
            header.update(extra)
        return json.dumps(header, ensure_ascii=False)

    def playerContent(self, flag, id, vipFlags):
        try:
            ep_id = str(id)

            # Wencai line
            if ep_id.startswith("wc@@"):
                parts = ep_id.split("@@")
                if len(parts) >= 3:
                    url = self._wc_play_url(parts[1], parts[2])
                    if url:
                        return {"parse": 0, "jx": 0, "url": url, "header": self._make_header()}
                return {"parse": 1, "jx": 0, "url": "", "header": self._make_header()}

            # Yongle line
            if ep_id.startswith("yl@@"):
                parts = ep_id.split("@@")
                if len(parts) >= 4:
                    url = self._yl_play_url(parts[1], parts[2], parts[3])
                    if url:
                        return {"parse": 0, "jx": 0, "url": url, "header": self._make_header({"Referer": self.yl_host + "/"})}
                return {"parse": 1, "jx": 0, "url": "", "header": self._make_header()}

            # Beiyong line (needs parse)
            if ep_id.startswith("hs@@"):
                parts = ep_id.split("@@", 2)
                if len(parts) >= 3:
                    parse_url = unquote(parts[1])
                    ep_url = unquote(parts[2])
                    url = self._hs_play_url(parse_url, ep_url)
                    if url:
                        return {"parse": 0, "jx": 0, "url": url, "header": self._make_header()}
                return {"parse": 1, "jx": 0, "url": "", "header": self._make_header()}

            # Direct URL
            if ep_id.startswith("http"):
                return {"parse": 0, "jx": 0, "url": ep_id, "header": self._make_header()}

            # 速搜 native: jqq or 123pan
            is_jqq = ep_id.startswith("jqq@@") or "AI" in str(flag).upper() or str(flag).lower() == "jqq"
            play_id = ep_id[5:] if ep_id.startswith("jqq@@") else ep_id
            url = self._resolve_jqq(play_id) if is_jqq else self._real_video(play_id)
            if not url:
                raise ValueError("empty URL")
            play_header = {}
            if is_jqq:
                play_header["Referer"] = self.active_jqq_url or ""
            else:
                play_header["Referer"] = "https://www.123pan.com/"
            return {"parse": 0, "jx": 0, "url": url, "header": self._make_header(play_header)}
        except Exception as error:
            sys.stderr.write(f"playerContent error: {error}\n")
            raw_id = str(id)
            if raw_id.startswith("jqq@@"):
                raw_id = raw_id[5:]
            if raw_id.startswith("http"):
                return {"parse": 0, "jx": 0, "url": raw_id, "header": self._make_header()}
            return {"parse": 1, "jx": 0, "url": raw_id, "header": self._make_header(), "dr": None}
