#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
兄弟影视（brovod.com）TVBox Python 源。

适配公开页面：首页、分类筛选、搜索、详情、全部播放线路和站点内置播放器。
作者水印：QQ群：807916734
"""
from __future__ import print_function

import base64
import json
import re

import requests
from bs4 import BeautifulSoup

try:
    from urllib.parse import quote, unquote, urljoin, urlparse
except ImportError:
    from urllib import quote, unquote
    from urlparse import urljoin, urlparse

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    BaseSpider = object


class Spider(BaseSpider):
    NAME = "兄弟影视"
    WATERMARK = "QQ群：807916734"
    DEFAULT_HOST = "https://www.brovod.com"
    DEFAULT_PARSER = "https://play.brovod.com/?url="
    DEFAULT_PIC = "https://www.brovod.com/img/logo.png"
    TIMEOUT = 15

    HOST_CANDIDATES = (
        "https://www.brovod.com",
        "https://www.brovods.top",
        "https://www.brovod.top",
        "https://brovod.com",
        "https://brovods.top",
    )
    DISCOVERY_PAGES = ("https://xdys.vip/",)
    CATEGORIES = (
        ("Movies", "电影"),
        ("TV", "剧集"),
        ("Shows", "综艺"),
        ("Anime", "动漫"),
        ("Snaps", "短剧"),
        ("Documentaries", "纪录片"),
    )
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 12; M2007J3SC) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    DIRECT_RE = re.compile(r"\.(?:m3u8|mp4|flv|mkv|mov|avi)(?:[?#].*)?$", re.I)

    def __init__(self):
        try:
            super(Spider, self).__init__()
        except Exception:
            pass
        self.host = self.DEFAULT_HOST
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._configured_host = ""
        self._host_ready = False
        self._parser_cache = {}

    def init(self, extend=""):
        self._configured_host = self._parse_extend_host(extend)
        if self._configured_host:
            self.host = self._configured_host
        self._host_ready = False
        self._resolve_host()

    def getName(self):
        return "{} | {}".format(self.NAME, self.WATERMARK)

    def getDependence(self):
        return ["requests", "bs4"]

    @staticmethod
    def _origin(url):
        parsed = urlparse(str(url or ""))
        if not parsed.scheme or not parsed.netloc:
            return ""
        return "{}://{}".format(parsed.scheme, parsed.netloc)

    def _parse_extend_host(self, extend):
        value = str(extend or "").strip()
        if not value:
            return ""
        try:
            data = json.loads(value)
            if isinstance(data, dict):
                value = str(data.get("host") or data.get("url") or "").strip()
        except Exception:
            pass
        return self._origin(value).rstrip("/") if value.startswith(("http://", "https://")) else ""

    @staticmethod
    def _site_page(text):
        lower = str(text or "").lower()
        return ("兄弟影视" in str(text or "") and "maccms" in lower) or "/show/movies" in lower

    @staticmethod
    def _discover_hosts(text):
        result = []
        for value in re.findall(r"https?://[A-Za-z0-9.-]+", str(text or ""), re.I):
            host = value.rstrip("/")
            if "brovod" in host.lower() and host not in result:
                result.append(host)
        for domain in re.findall(r'["\'](?:url|wapurl)["\']\s*:\s*["\']([A-Za-z0-9.-]+)', str(text or ""), re.I):
            host = "https://" + domain.strip("/")
            if "brovod" in host.lower() and host not in result:
                result.append(host)
        return result

    def _resolve_host(self, force=False):
        if self._host_ready and not force:
            return True

        candidates = []

        def add(value):
            host = self._origin(value).rstrip("/")
            if host and host not in candidates:
                candidates.append(host)

        add(self._configured_host)
        add(self.host)
        for host in self.HOST_CANDIDATES:
            add(host)

        # 防丢页只用于发现公开的新域名，不作为影视站本身使用。
        for page in self.DISCOVERY_PAGES:
            try:
                response = self.session.get(page, timeout=8, allow_redirects=True)
                for host in self._discover_hosts(response.text):
                    add(host)
            except Exception:
                continue

        index = 0
        while index < len(candidates):
            candidate = candidates[index]
            index += 1
            try:
                response = self.session.get(candidate + "/", timeout=10, allow_redirects=True)
                for host in self._discover_hosts(response.text):
                    add(host)
                if response.status_code >= 400 or not self._site_page(response.text):
                    continue
                final_host = self._origin(response.url)
                if final_host:
                    self.host = final_host.rstrip("/")
                    self._host_ready = True
                    self.session.headers.update({"Referer": self.host + "/"})
                    return True
            except Exception:
                continue

        self._host_ready = False
        return False

    def _absolute(self, value):
        value = str(value or "").strip().replace("\\/", "/")
        if not value:
            return ""
        if value.startswith("//"):
            return "https:" + value
        if value.startswith(("http://", "https://")):
            return value
        return urljoin((self.host or self.DEFAULT_HOST) + "/", value)

    def _request(self, path_or_url, retried=False):
        if not self._host_ready:
            self._resolve_host()
        raw = str(path_or_url or "")
        url = self._absolute(raw)
        if not url:
            return None
        try:
            response = self.session.get(url, timeout=self.TIMEOUT, allow_redirects=True)
            response.raise_for_status()
            final_origin = self._origin(response.url)
            if final_origin and "brovod" in final_origin.lower():
                self.host = final_origin.rstrip("/")
                self._host_ready = True
            response.encoding = response.apparent_encoding or response.encoding or "utf-8"
            return response
        except Exception as error:
            if not retried:
                parsed = urlparse(url)
                self._host_ready = False
                if self._resolve_host(force=True):
                    relative = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
                    return self._request(relative, retried=True)
            print("[{}] 请求失败: {}".format(self.NAME, error))
            return None

    def _fetch(self, path_or_url):
        response = self._request(path_or_url)
        return response.text if response is not None else ""

    @staticmethod
    def _clean(value):
        value = re.sub(r"<[^>]+>", " ", str(value or ""))
        value = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    @classmethod
    def _safe(cls, value):
        return cls._clean(value).replace("$", " ").replace("#", " ")

    def _picture(self, image):
        if image is None:
            return self._absolute("/img/logo.png") or self.DEFAULT_PIC
        pic = image.get("data-src") or image.get("data-original") or image.get("src") or ""
        if str(pic).startswith("data:"):
            pic = ""
        return self._absolute(pic) if pic else (self._absolute("/img/logo.png") or self.DEFAULT_PIC)

    def _parse_cards(self, html, limit=0):
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        videos, seen = [], set()
        for anchor in soup.select('a.public-list-exp[href*="/detail/"]'):
            href = str(anchor.get("href") or "").strip()
            match = re.search(r"(/detail/[^?#]+/)", href, re.I)
            vod_id = match.group(1) if match else ""
            if not vod_id or vod_id in seen:
                continue
            image = anchor.select_one("img")
            title = self._safe(anchor.get("title") or "")
            if not title and image is not None:
                title = self._safe(re.sub(r"封面图$", "", image.get("alt") or ""))
            parent = anchor.find_parent(class_=re.compile(r"public-list-box"))
            if not title and parent is not None:
                title_node = parent.select_one(".time-title, .thumb-txt a")
                title = self._safe(title_node.get("title") or title_node.get_text(" ", strip=True)) if title_node else ""
            if not title:
                continue
            remark_node = anchor.select_one(".public-list-prb, .public-list-prt, .public-list-prd")
            videos.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": self._picture(image),
                "vod_remarks": self._safe(remark_node.get_text(" ", strip=True) if remark_node else ""),
            })
            seen.add(vod_id)
            if limit and len(videos) >= limit:
                break
        return videos

    @staticmethod
    def _page_count(html, current, route):
        pages = [int(current or 1)]
        soup = BeautifulSoup(html or "", "html.parser")
        for anchor in soup.select("a.page-link[href]"):
            href = str(anchor.get("href") or "")
            if route == "show":
                match = re.search(r"/show/[^/]*-{8}(\d+)-{3}/", href, re.I)
            else:
                match = re.search(r"/ss/[^/]*-{10}(\d+)-{3}/", href, re.I)
            if match:
                pages.append(int(match.group(1)))
        return max(pages)

    @staticmethod
    def _filter_values():
        years = [{"n": "全部", "v": ""}]
        years.extend({"n": str(year), "v": str(year)} for year in range(2026, 2009, -1))
        return [
            {
                "key": "area", "name": "地区", "value": [
                    {"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"},
                    {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"},
                    {"n": "美国", "v": "美国"}, {"n": "韩国", "v": "韩国"},
                    {"n": "日本", "v": "日本"}, {"n": "英国", "v": "英国"},
                    {"n": "法国", "v": "法国"}, {"n": "泰国", "v": "泰国"},
                    {"n": "其他", "v": "其他"},
                ],
            },
            {
                "key": "class", "name": "类型", "value": [
                    {"n": "全部", "v": ""}, {"n": "喜剧", "v": "喜剧"},
                    {"n": "爱情", "v": "爱情"}, {"n": "动作", "v": "动作"},
                    {"n": "科幻", "v": "科幻"}, {"n": "剧情", "v": "剧情"},
                    {"n": "悬疑", "v": "悬疑"}, {"n": "犯罪", "v": "犯罪"},
                    {"n": "恐怖", "v": "恐怖"}, {"n": "动画", "v": "动画"},
                    {"n": "战争", "v": "战争"}, {"n": "纪录", "v": "纪录"},
                ],
            },
            {
                "key": "lang", "name": "语言", "value": [
                    {"n": "全部", "v": ""}, {"n": "国语", "v": "国语"},
                    {"n": "英语", "v": "英语"}, {"n": "粤语", "v": "粤语"},
                    {"n": "韩语", "v": "韩语"}, {"n": "日语", "v": "日语"},
                ],
            },
            {"key": "year", "name": "年份", "value": years},
            {
                "key": "by", "name": "排序", "value": [
                    {"n": "时间", "v": "time"}, {"n": "人气", "v": "hits"},
                    {"n": "评分", "v": "score"},
                ],
            },
        ]

    def _filters(self):
        values = self._filter_values()
        return {type_id: values for type_id, _ in self.CATEGORIES}

    def _watermark_vod(self):
        return {
            "vod_id": "__author__",
            "vod_name": "作者水印：" + self.WATERMARK,
            "vod_pic": self._absolute("/img/logo.png") or self.DEFAULT_PIC,
            "vod_remarks": self.NAME,
            "vod_content": "本接口作者水印：" + self.WATERMARK,
            "vod_play_from": "",
            "vod_play_url": "",
        }

    def homeContent(self, filter=False):
        classes = [{"type_id": key, "type_name": name} for key, name in self.CATEGORIES]
        classes.append({"type_id": "__author__", "type_name": self.WATERMARK})
        html = self._fetch("/")
        return {"class": classes, "filters": self._filters(), "list": self._parse_cards(html, 40)}

    def homeVideoContent(self):
        return {"list": self._parse_cards(self._fetch("/"), 40)}

    @staticmethod
    def _extend_dict(extend):
        if isinstance(extend, dict):
            return extend
        try:
            data = json.loads(str(extend or "{}"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            page = max(1, int(pg or 1))
        except Exception:
            page = 1
        tid = str(tid or "")
        if tid == "__author__":
            return {"list": [self._watermark_vod()], "page": 1, "pagecount": 1, "limit": 1, "total": 1}
        if tid not in [item[0] for item in self.CATEGORIES]:
            return {"list": [], "page": page, "pagecount": page, "limit": 40, "total": 0}

        options = self._extend_dict(extend)
        fields = [tid, options.get("area", ""), options.get("by", ""), options.get("class", ""),
                  options.get("lang", ""), options.get("letter", ""), "", "", str(page), "", "",
                  options.get("year", "")]
        route = "/show/{}/".format("-".join(quote(str(item), safe="") for item in fields))
        html = self._fetch(route)
        videos = self._parse_cards(html, 60)
        pagecount = self._page_count(html, page, "show")
        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": 40,
            "total": pagecount * 40,
        }

    def _detail_path(self, value):
        raw = str(value or "").strip()
        match = re.search(r"(/detail/[^?#]+/)", raw, re.I)
        if match:
            return match.group(1)
        if raw and "/" not in raw:
            return "/detail/{}/".format(raw.strip("/"))
        return ""

    def _label_value(self, soup, labels):
        for node in soup.select(".slide-info, .detail-info li"):
            strong = node.select_one("strong")
            label = self._clean(strong.get_text(" ", strip=True) if strong else "")
            if any(item in label for item in labels):
                text = self._clean(node.get_text(" ", strip=True))
                for item in labels:
                    text = re.sub(r"^{}\s*[:：]?\s*".format(re.escape(item)), "", text)
                return self._safe(text)
        return ""

    @staticmethod
    def _line_name(anchor, index):
        direct = "".join(str(item) for item in anchor.find_all(string=True, recursive=False))
        name = re.sub(r"\s+", " ", direct).strip()
        return name or "线路{}".format(index)

    def _parse_detail(self, html, vod_id):
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.select_one(".slide-info-title, h1")
        title = self._safe(title_node.get_text(" ", strip=True) if title_node else "")
        if not title:
            return None
        poster = soup.select_one(".detail-pic img")
        remarks = soup.select(".detail-info .slide-info-remarks")
        year = self._safe(remarks[0].get_text(" ", strip=True)) if len(remarks) > 0 else ""
        area = self._safe(remarks[1].get_text(" ", strip=True)) if len(remarks) > 1 else ""
        vod_type = self._safe(remarks[2].get_text(" ", strip=True)) if len(remarks) > 2 else ""
        remark = self._label_value(soup, ("备注", "状态"))
        actor = self._label_value(soup, ("演员", "主演"))
        director = self._label_value(soup, ("导演",))

        content_node = soup.select_one(".switch-box")
        content = self._safe(content_node.get_text(" ", strip=True) if content_node else "")
        content = re.sub(r"\s*[]?\s*展开\s*$", "", content).strip()
        if not content:
            meta = soup.select_one('meta[name="description"]')
            content = self._safe(meta.get("content") if meta else "")
            content = re.sub(r"^{}剧情介绍[：:]\s*".format(re.escape(title)), "", content)

        tabs = soup.select(".anthology-tab a.swiper-slide, .anthology-tab a")
        blocks = soup.select(".anthology-list-box")
        play_from, play_url = [], []
        for index, block in enumerate(blocks, 1):
            episodes = []
            for anchor in block.select('a[href*="/play/"]'):
                href = str(anchor.get("href") or "").strip()
                path_match = re.search(r"(/play/[^?#]+/)", href, re.I)
                if not path_match:
                    continue
                name = self._safe(anchor.get_text(" ", strip=True)) or "播放"
                episodes.append("{}${}".format(name, path_match.group(1)))
            if not episodes:
                continue
            line_name = self._line_name(tabs[index - 1], index) if index <= len(tabs) else "线路{}".format(index)
            play_from.append("{} | {}".format(self._safe(line_name), self.WATERMARK))
            play_url.append("#".join(episodes))

        return {
            "vod_id": vod_id,
            "vod_name": "{} | {}".format(title, self.WATERMARK),
            "vod_pic": self._picture(poster),
            "vod_year": year,
            "vod_area": area,
            "vod_type": vod_type,
            "vod_remarks": remark,
            "vod_actor": actor,
            "vod_director": director,
            "vod_content": (content + "\n" + self.WATERMARK).strip(),
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }

    def detailContent(self, ids):
        raw = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        if str(raw or "") == "__author__":
            return {"list": [self._watermark_vod()]}
        path = self._detail_path(raw)
        if not path:
            return {"list": []}
        vod = self._parse_detail(self._fetch(path), path)
        return {"list": [vod]} if vod else {"list": []}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            page = max(1, int(pg or 1))
        except Exception:
            page = 1
        keyword = str(key or "").strip()
        if not keyword:
            return {"list": [], "page": page, "pagecount": page, "limit": 10, "total": 0}
        route = "/ss/{}----------{}---/".format(quote(keyword, safe=""), page)
        html = self._fetch(route)
        videos = self._parse_cards(html, 60)
        pagecount = self._page_count(html, page, "search")
        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": 10,
            "total": pagecount * 10,
        }

    @staticmethod
    def _extract_player(html):
        soup = BeautifulSoup(html or "", "html.parser")
        decoder = json.JSONDecoder()
        for script in soup.find_all("script"):
            source = script.string or script.get_text() or ""
            if "player_aaaa" not in source:
                continue
            start = source.find("{", source.find("player_aaaa"))
            if start < 0:
                continue
            try:
                data, _ = decoder.raw_decode(source[start:])
                return data if isinstance(data, dict) else {}
            except Exception:
                continue
        return {}

    @staticmethod
    def _decode_player_url(data):
        value = str(data.get("url") or "").replace("\\/", "/")
        try:
            encrypt = int(data.get("encrypt") or 0)
        except Exception:
            encrypt = 0
        try:
            if encrypt == 1:
                return unquote(value)
            if encrypt == 2:
                decoded = base64.b64decode(value).decode("utf-8", "ignore")
                return unquote(decoded)
        except Exception:
            return value
        return value

    def _parser_base(self, source):
        source = re.sub(r"[^A-Za-z0-9_-]", "", str(source or ""))
        if not source:
            return self.DEFAULT_PARSER
        if source in self._parser_cache:
            return self._parser_cache[source]
        script = self._fetch("/static/player/{}.js".format(source))
        match = re.search(r"(https?://[^\s'\"`]+/\?url=)", script or "", re.I)
        parser = match.group(1) if match else self.DEFAULT_PARSER
        self._parser_cache[source] = parser
        return parser

    def playerContent(self, flag, id, vipFlags=None):
        raw = str(id or "").strip()
        page_url = self._absolute(raw)
        base_header = {
            "User-Agent": self.HEADERS["User-Agent"],
            "Referer": (self.host or self.DEFAULT_HOST) + "/",
        }
        if self.DIRECT_RE.search(raw):
            return {
                "parse": 0, "playUrl": "", "url": page_url,
                "header": json.dumps(base_header, ensure_ascii=False),
            }

        response = self._request(raw)
        if response is None:
            return {
                "parse": 1, "playUrl": "", "url": page_url,
                "header": json.dumps(base_header, ensure_ascii=False),
            }
        player = self._extract_player(response.text)
        play_value = self._decode_player_url(player)
        if not play_value:
            return {
                "parse": 1, "playUrl": "", "url": response.url,
                "header": json.dumps(base_header, ensure_ascii=False),
            }
        if self.DIRECT_RE.search(play_value):
            return {
                "parse": 0, "playUrl": "", "url": self._absolute(play_value),
                "header": json.dumps(base_header, ensure_ascii=False),
            }

        parser_base = self._parser_base(player.get("from"))
        next_link = self._absolute(player.get("link_next")) if player.get("link_next") else ""
        vod_data = player.get("vod_data") if isinstance(player.get("vod_data"), dict) else {}
        title = self._safe(vod_data.get("vod_name") or "兄弟影视")
        parser_url = "{}{}&next={}&title={}".format(
            parser_base,
            quote(play_value, safe=""),
            quote(next_link, safe=""),
            quote(title, safe=""),
        )
        parser_origin = self._origin(parser_url)
        parser_header = {
            "User-Agent": self.HEADERS["User-Agent"],
            "Referer": (self.host or self.DEFAULT_HOST) + "/",
            "Origin": parser_origin,
        }
        return {
            "parse": 1,
            "playUrl": "",
            "url": parser_url,
            "header": json.dumps(parser_header, ensure_ascii=False),
        }

    def isVideoFormat(self, url):
        return bool(self.DIRECT_RE.search(str(url or "")))

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return None

    def liveContent(self, url):
        return {"list": []}

    def action(self, action):
        return {}

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    spider = Spider()
    spider.init("")
    print("接口:", spider.getName(), "域名:", spider.host)
    home = spider.homeVideoContent()
    print("首页:", len(home.get("list", [])), "条")
    category = spider.categoryContent("Movies", "1", False, {})
    print("分类:", len(category.get("list", [])), "条, 共", category.get("pagecount"), "页")
    search = spider.searchContent("变形金刚", False, "1")
    print("搜索:", len(search.get("list", [])), "条")
    sample = (search.get("list") or category.get("list") or [{}])[0]
    if sample.get("vod_id"):
        detail = spider.detailContent([sample["vod_id"]])
        vod = detail.get("list", [{}])[0]
        lines = vod.get("vod_play_from", "").split("$$$") if vod.get("vod_play_from") else []
        print("详情:", vod.get("vod_name", ""), "线路:", len(lines))
        if vod.get("vod_play_url"):
            episode = vod["vod_play_url"].split("$$$")[0].split("#")[0].split("$", 1)[-1]
            print("播放:", spider.playerContent("", episode, []))
