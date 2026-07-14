
import hashlib
import json
import random
import re
import time
from urllib.parse import quote

try:
    import requests
except Exception:
    requests = None

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass


class Spider(BaseSpider):
    DEFAULT_HOST = "https://asd123sx23xdacsx.top"

    FINGERPRINT = (
        "SF-C3B2B41F6EFFFF9869176CF68F6790E8"
        "F07506FC88632C94B4F5F0430D5498CA"
    )
    APP_ID = "com.sunshine.tv"
    SECRET_KEY = "SK-thanks"
    APP_VERSION = "4"

    def getName(self):
        return "三秋影视"

    def init(self, extend=""):
        host = self.DEFAULT_HOST

        if isinstance(extend, dict):
            host = str(extend.get("host", host) or host)
        elif isinstance(extend, str) and extend.strip():
            text = extend.strip()
            if text.startswith("http"):
                host = text
            else:
                try:
                    obj = json.loads(text)
                    if isinstance(obj, dict):
                        host = str(obj.get("host", host) or host)
                except Exception:
                    pass

        self.host = host.rstrip("/")
        self.session = requests.Session() if requests else None
        self.timeout = 15

    def isVideoFormat(self, url):
        return bool(re.search(
            r"(?i)(m3u8|mp4|flv|avi|mov|mkv|mpd)",
            str(url or "")
        ))

    def manualVideoCheck(self):
        return False

    # -------------------- 请求与签名 --------------------

    def _check_runtime(self):
        if requests is None:
            raise RuntimeError("缺少 requests 模块")

    def _signed_headers(self):
        timestamp = str(int(time.time()))
        nonce = str(random.randint(1, 999))

        raw = (
            f"finger={self.FINGERPRINT}"
            f"&id={self.APP_ID}"
            f"&nonce={nonce}"
            f"&sk={self.SECRET_KEY}"
            f"&time={timestamp}"
            f"&v={self.APP_VERSION}"
        )
        sign = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()

        return {
            "user-agent": "okhttp/4.12.0",
            "x-ave": self.APP_VERSION,
            "x-aid": self.APP_ID,
            "x-time": timestamp,
            "x-nonc": nonce,
            "x-sign": sign,
            "x-device-id": "0b4328287a5d953e",
            "x-device-brand": "OnePlus",
            "x-device-model": "HD1900",
            "x-update-id": "73dc2ffc-8350-c022-fac9-da982c95f513"
        }

    def _get_text(self, path, headers=None):
        self._check_runtime()
        url = path if path.startswith("http") else self.host + path
        final_headers = self._signed_headers()
        if headers:
            final_headers.update(headers)

        response = self.session.get(
            url,
            headers=final_headers,
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.text

    def _get_json(self, path, headers=None):
        text = self._get_text(path, headers=headers)
        return json.loads(text)

    # -------------------- 数据转换 --------------------

    @staticmethod
    def _vod_item(item):
        if not isinstance(item, dict):
            return {}
        return {
            "vod_id": str(item.get("vod_id", "") or ""),
            "vod_name": str(item.get("vod_name", "") or ""),
            "vod_pic": str(item.get("vod_pic", "") or ""),
            "vod_remarks": str(item.get("vod_remarks", "") or "")
        }

    def _parse_vod_list(self, items):
        if not isinstance(items, list):
            return []
        return [
            self._vod_item(item)
            for item in items
            if isinstance(item, dict)
        ]

    # -------------------- 首页 --------------------

    def homeContent(self, filter):
        try:
            obj = self._get_json("/api.php/app/index/home")
            data = obj.get("data", {})
            if not isinstance(data, dict):
                data = {}

            classes = []
            for item in data.get("categories", []) or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("type_name", "") or "")
                if name:
                    classes.append({
                        "type_id": name,
                        "type_name": name
                    })

            videos = self._parse_vod_list(
                data.get("recommend", [])
            )

            return {
                "class": classes,
                "list": videos
            }
        except Exception as exc:
            return {
                "class": [],
                "list": [],
                "error": str(exc)
            }

    def homeVideoContent(self):
        try:
            obj = self._get_json("/api.php/app/index/home")
            data = obj.get("data", {})
            videos = (
                data.get("recommend", [])
                if isinstance(data, dict)
                else []
            )
            return {"list": self._parse_vod_list(videos)}
        except Exception as exc:
            return {"list": [], "error": str(exc)}

    # -------------------- 分类 --------------------

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(int(pg or 1), 1)
            path = (
                "/api.php/app/filter/vod"
                f"?type_name={quote(str(tid))}"
                f"&page={page}"
                "&sort=hits"
            )

            obj = self._get_json(path)
            videos = self._parse_vod_list(obj.get("data", []))

            return {
                "page": page,
                "pagecount": page + 1 if videos else page,
                "limit": len(videos),
                "total": 999999 if videos else 0,
                "list": videos
            }
        except Exception as exc:
            return {
                "page": int(pg or 1),
                "pagecount": int(pg or 1),
                "limit": 0,
                "total": 0,
                "list": [],
                "error": str(exc)
            }

    # -------------------- 详情 --------------------

    def detailContent(self, ids):
        try:
            vod_id = ids[0] if isinstance(ids, list) else ids
            obj = self._get_json(
                "/api.php/app/vod/get_detail"
                f"?vod_id={quote(str(vod_id))}"
            )

            data = obj.get("data", [])
            info = data[0] if isinstance(data, list) and data else {}
            if not isinstance(info, dict):
                info = {}

            video = {
                "vod_id": str(vod_id),
                "vod_name": str(info.get("vod_name", "") or ""),
                "vod_pic": str(info.get("vod_pic", "") or ""),
                "type_name": str(info.get("vod_class", "") or ""),
                "vod_remarks": str(info.get("vod_remarks", "") or ""),
                "vod_content": str(info.get("vod_content", "") or "").strip(),
                "vod_actor": str(info.get("vod_actor", "") or ""),
                "vod_director": str(info.get("vod_director", "") or "")
            }

            # 将线路内部标识替换成展示名称
            source_name_map = {}
            for item in obj.get("vodplayer", []) or []:
                if not isinstance(item, dict):
                    continue
                source_from = str(item.get("from", "") or "")
                source_show = str(item.get("show", "") or "")
                if source_from:
                    source_name_map[source_from] = source_show or source_from

            raw_froms = str(info.get("vod_play_from", "") or "").split("$$$")
            raw_urls = str(info.get("vod_play_url", "") or "").split("$$$")

            display_froms = []
            output_urls = []

            vod_name = video["vod_name"]

            for index, source_urls in enumerate(raw_urls):
                source_from = raw_froms[index] if index < len(raw_froms) else ""
                display_name = source_name_map.get(source_from, source_from)
                display_froms.append(display_name)

                episodes = []
                for episode in source_urls.split("#"):
                    if not episode or "$" not in episode:
                        continue

                    ep_name, ep_url = episode.split("$", 1)
                    digits = re.sub(r"\D+", "", ep_name)
                    vod_index = digits if digits else "1"

                    payload = "@".join([
                        ep_url,
                        source_from,
                        vod_name,
                        vod_index
                    ])
                    episodes.append(f"{ep_name}${payload}")

                output_urls.append("#".join(episodes))

            video["vod_play_from"] = "$$$".join(display_froms)
            video["vod_play_url"] = "$$$".join(output_urls)

            return {"list": [video]}
        except Exception as exc:
            return {"list": [], "error": str(exc)}

    # -------------------- 搜索 --------------------

    def searchContent(self, key, quick, pg="1"):
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick, pg="1"):
        try:
            page = max(int(pg or 1), 1)
            path = (
                "/api.php/app/search/index"
                f"?wd={quote(str(key))}"
                f"&page={page}"
                "&limit=15"
            )
            obj = self._get_json(path)
            videos = self._parse_vod_list(obj.get("data", []))

            return {
                "page": page,
                "pagecount": page + 1 if videos else page,
                "limit": len(videos),
                "total": 999999 if videos else 0,
                "list": videos
            }
        except Exception as exc:
            return {
                "page": int(pg or 1),
                "pagecount": int(pg or 1),
                "limit": 0,
                "total": 0,
                "list": [],
                "error": str(exc)
            }

    # -------------------- 播放 --------------------

    def playerContent(self, flag, id, vipFlags):
        try:
            parts = str(id or "").split("@")
            parts += [""] * (4 - len(parts))

            play_url = parts[0].strip()
            vod_from = parts[1].strip()
            vod_name = parts[2].strip()
            vod_index = parts[3].strip() or "1"

            if self.isVideoFormat(play_url):
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": play_url
                }

            token_suffix = ""

            # 原 JAR 最多重试 3 次；code=2 时解析 challenge 生成 token
            for _ in range(3):
                path = (
                    "/api.php/app/decode/url/"
                    f"?url={quote(play_url, safe='')}"
                    f"&vodFrom={quote(vod_from)}"
                    f"{token_suffix}"
                )

                text = self._get_text(path)
                if not text.strip():
                    continue

                obj = json.loads(text)
                code = int(obj.get("code", -1) or -1)

                if code == 2 and obj.get("challenge"):
                    token = self._challenge_token(
                        str(obj.get("challenge", ""))
                    )
                    if token:
                        token_suffix = "&token=" + quote(token)
                        continue

                final_url = str(obj.get("data", "") or "").strip()
                if final_url.startswith("http"):
                    return {
                        "parse": 0,
                        "playUrl": "",
                        "url": final_url
                    }

            return {
                "parse": 1,
                "playUrl": "",
                "url": play_url,
                "error": "播放链接解析失败，请更换其他源播放"
            }
        except Exception as exc:
            return {
                "parse": 1,
                "playUrl": "",
                "url": str(id or ""),
                "error": str(exc)
            }

    # -------------------- Challenge 算法 --------------------

    @staticmethod
    def _challenge_token(js_text):
        """
        对应 JAR 中 App3Q.c(String)：

        1. 从 JS 提取 _0x1 = [a,b,c,d]
        2. 对 a:b:c:d 计算 JS 风格 32 位 hash
        3. 返回 a:hex(hash):b前8位
        """
        try:
            match = re.search(
                r"_0x1\s*=\s*\[(.*?)\];",
                js_text,
                re.S
            )
            if not match:
                return ""

            values = [
                x.strip().strip("'\"")
                for x in match.group(1).split(",")
            ]
            if len(values) < 4:
                return ""

            first, second, third, fourth = values[:4]
            raw = f"{first}:{second}:{third}:{fourth}"

            value = 0
            for ch in raw:
                value = ((value << 5) - value + ord(ch)) & 0xFFFFFFFF

            token_hash = format(abs(value), "x")
            return f"{first}:{token_hash}:{second[:8]}"
        except Exception:
            return ""

    def localProxy(self, param):
        return [404, "text/plain", "Not Found"]
