
# -*- coding: utf-8 -*-
"""Gimy 劇迷（gimytv.biz）TVBox / OK影视 Python 插件（修复版）。

原脚本"能播放内容但无数据"的根因：
    详情页的选集容器在当前站点模板里已由
        <div class="playlist-mobile playlist ..."> ... <ul id="con_playlist_7">
    改为
        <section class="playlist-mobile playlist ..."> ... <ul id="con_playlist_7">
    原脚本用 //div[contains(concat(" ",normalize-space(@class)," ")," playlist-mobile ")]
    定位播放面板，标签名不匹配，匹配结果为 0，于是 detailContent 返回的
    vod_play_from / vod_play_url 均为空字符串，TVBox 进入详情后播放列表无任何数据。

本版改动：
    1. 选集改为按 <ul id="con_playlist_<sid>"> 分组提取（正则+DOM 双重兜底），
       并提取全部线路名（NYun/BYun/.../DYun）与集数标签，按集号升序排列；
    2. 剧情简介改为 span.details-content-all（原选择器写的是 div，匹配不到）；
    3. 短剧分类 id 由 25 更正为 54（站点 vodtype/54.html）；
    4. _get 不再使用 apparent_encoding（会被误判为 ptcp154 等编码导致乱码），
       改为优先采用响应头声明的编码；
    5. playerContent 增加相对地址补全与直链判空，其余保持原逻辑。
"""

import json
import re
from urllib.parse import quote, urljoin

import requests
from lxml import etree
from base.spider import Spider


class Spider(Spider):
    def getName(self):
        return "Gimy影视"

    def init(self, extend=""):
        self.host = "https://gimytv.biz"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": self.host + "/",
        }
        self.classes = [
            {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "3", "type_name": "综艺"},
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "54", "type_name": "短剧"},
        ]
        subtypes = {
            "1": [("全部", "1"), ("动作片", "6"), ("喜剧片", "7"), ("爱情片", "8"), ("科幻片", "9"),
                  ("恐怖片", "10"), ("剧情片", "11"), ("战争片", "12"), ("动画电影", "24")],
            "2": [("全部", "2"), ("陆剧", "13"), ("韩剧", "15"), ("美剧", "16"), ("日剧", "20"),
                  ("台剧", "14"), ("海外剧", "21"), ("港剧", "22"), ("纪录片", "23"), ("短剧", "54")],
            "3": [("全部", "3")],
            "4": [("全部", "4")],
            "54": [("全部", "54")],
        }
        years = [{"n": "全部", "v": ""}] + [{"n": str(x), "v": str(x)} for x in range(2026, 2015, -1)]
        sorts = [{"n": "最新更新", "v": "time"}, {"n": "最新上架", "v": "time_add"},
                 {"n": "周人气", "v": "hits_week"}, {"n": "总人气", "v": "hits"}]
        self.filters = {
            tid: [
                {"key": "type", "name": "类型", "value": [{"n": n, "v": v} for n, v in values]},
                {"key": "year", "name": "年份", "value": years},
                {"key": "by", "name": "排序", "value": sorts},
            ]
            for tid, values in subtypes.items()
        }

    # ---------------------------------------------------------------- 基础请求

    def _get(self, url, sid=""):
        try:
            headers = dict(self.headers)
            if sid:
                headers["Cookie"] = "sid=" + str(sid)
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            # 站点统一 UTF-8。requests 在响应头未声明 charset 时会默认 ISO-8859-1，
            # 而 apparent_encoding 会被误判（实测出现过 ptcp154），会造成中文乱码。
            enc = response.encoding
            if not enc or enc.lower() in ("iso-8859-1", "ascii", "latin-1"):
                m = re.search(r'charset=["\']?([\w-]+)', response.content[:2048].decode("ascii", "ignore"))
                enc = m.group(1) if m else "utf-8"
            response.encoding = enc or "utf-8"
            return response.text
        except Exception:
            return ""

    def _fix(self, url):
        return urljoin(self.host + "/", url or "")

    # ---------------------------------------------------------------- 列表解析

    def _parse_list(self, html):
        if not html:
            return []
        tree, result, seen = etree.HTML(html), [], set()
        for node in tree.xpath('//a[contains(concat(" ",normalize-space(@class)," ")," video-pic ") and contains(@href,"/voddetail/")]'):
            match = re.search(r"/voddetail/(\d+)\.html", node.get("href", ""))
            if not match or match.group(1) in seen:
                continue
            seen.add(match.group(1))
            name = node.get("title") or "".join(node.xpath('.//img/@alt')).strip()
            pic = (node.get("data-original") or node.get("data-src") or node.get("data-lazyload")
                   or "".join(node.xpath('.//img/@data-original | .//img/@data-src | .//img/@src')))
            remark = "".join(node.xpath('.//*[contains(@class,"note")]//text()')).strip()
            result.append({"vod_id": match.group(1), "vod_name": name.strip(),
                           "vod_pic": self._fix(pic), "vod_remarks": remark})
        return result

    def _pagecount(self, tree, page):
        values = [int(x) for x in tree.xpath('//a[contains(@href,"/vodshow/")]/@href')
                  for x in re.findall(r"-(\d+)---", x)]
        return max(values + [page])

    # ---------------------------------------------------------------- 首页/分类

    def homeContent(self, filter):
        return {"class": self.classes, "list": self._parse_list(self._get(self.host + "/")),
                "filters": self.filters}

    def categoryContent(self, tid, pg, filter, extend):
        page, ext = max(1, int(pg or 1)), extend if isinstance(extend, dict) else {}
        selected = str(ext.get("type") or tid)
        year = str(ext.get("year") or "")
        by = str(ext.get("by") or "time")
        url = f"{self.host}/vodshow/{selected}--{by}------{page}---{year}.html"
        html = self._get(url)
        tree = etree.HTML(html) if html else etree.HTML("<html/>")
        videos = self._parse_list(html)
        pages = self._pagecount(tree, page)
        return {"page": page, "pagecount": pages, "limit": len(videos),
                "total": pages * max(len(videos), 1), "list": videos}

    # ---------------------------------------------------------------- 选集提取

    @staticmethod
    def _ep_label(tag, inner, num):
        """从单个选集 <a> 的标签与内容中推断集数标签。"""
        m = re.search(r'class="episode-title"[^>]*>([^<]+)<', inner)
        if m:
            return m.group(1).strip()
        m = re.search(r"第\s*\d+\s*集", inner)
        if m:
            return re.sub(r"\s+", "", m.group(0))
        m = re.search(r'title="([^"]+)"', tag)
        if m:
            tail = m.group(1).strip().split()
            if tail:
                return tail[-1]
        return ""

    @staticmethod
    def _fmt_label(label, num, total):
        m = re.match(r"^第\s*(\d+)\s*集$", label or "")
        if m:
            return "第%02d集" % int(m.group(1))
        if label:
            return label
        if total <= 1:
            return "正片"
        if num:
            return "第%02d集" % int(num)
        return "第%02d集" % total

    def _extract_playlists(self, html):
        """从详情页原文提取线路名与选集分组。

        当前模板中桌面版播放入口被 HTML 注释包裹、移动版为 <section class="playlist-mobile">，
        两类内容都在同一份 HTML 原文里，故直接按 <ul id="con_playlist_<sid>"> 分组提取，
        可一次拿到全部线路（解析树只能拿到未被注释的那部分）。
        """
        names = {}
        for m in re.finditer(r'href="#con_playlist_(\d+)"[^>]*>([^<]+)</a>', html):
            names.setdefault(m.group(1), m.group(2).strip())

        groups = {}
        for m in re.finditer(r'<ul[^>]*\bid="con_playlist_(\d+)"[^>]*>(.*?)</ul>', html, re.S):
            sid, block = m.group(1), m.group(2)
            items = []
            for a in re.finditer(r"<a\b([^>]*)>(.*?)</a>", block, re.S):
                tag, inner = a.group(1), a.group(2)
                href_m = re.search(r'href="([^"]+)"', tag)
                if not href_m or "/video/" not in href_m.group(1):
                    continue
                path = href_m.group(1).split("#", 1)[0]
                num_m = re.search(r"-(\d+)\.html", path)
                num = int(num_m.group(1)) if num_m else len(items) + 1
                items.append((num, self._ep_label(tag, inner, num), path))
            if items:
                items.sort(key=lambda x: x[0])
                groups.setdefault(sid, items)
        return names, groups

    def _dom_playlists(self, tree):
        """正则提取失效时的 DOM 兜底（兼容 <div>/<section> 两种容器）。"""
        groups, seen = {}, set()
        for panel in tree.xpath('//*[contains(@class,"playlist")]'):
            anchors = panel.xpath('.//a[contains(@href,"/video/")]')
            if not anchors:
                continue
            sid = None
            for anchor in anchors:
                m = (re.search(r"changeSid\(['\"]?(\d+)", anchor.get("onclick", ""))
                     or re.search(r"sid=(\d+)", anchor.get("href", "")))
                if m:
                    sid = m.group(1)
                    break
            if sid is None:
                m = re.search(r"con_playlist_(\d+)", panel.get("id", "") or "")
                sid = m.group(1) if m else str(len(groups) + 1)
            if sid in seen:
                continue
            seen.add(sid)
            items = []
            for anchor in anchors:
                path = anchor.get("href", "").split("#", 1)[0]
                num_m = re.search(r"-(\d+)\.html", path)
                num = int(num_m.group(1)) if num_m else len(items) + 1
                label = "".join(anchor.xpath('.//*[contains(@class,"episode-title")]//text()')).strip()
                if not label:
                    label = "".join(anchor.xpath(".//text()")).strip()
                items.append((num, label, path))
            items.sort(key=lambda x: x[0])
            groups[sid] = items
        return groups

    # ---------------------------------------------------------------- 详情

    def detailContent(self, ids):
        result = []
        for vid in ids:
            html = self._get(f"{self.host}/voddetail/{vid}.html")
            if not html:
                continue
            tree = etree.HTML(html)
            name = ("".join(tree.xpath('//h1/text()')).strip()
                    or "".join(tree.xpath('//meta[@property="og:title"]/@content')).strip()
                    or "".join(tree.xpath("//title/text()")).strip())
            pic = "".join(tree.xpath(
                '//meta[@property="og:image"]/@content | //div[contains(@class,"detail-pic")]//img/@data-original'
                ' | //div[contains(@class,"detail-pic")]//img/@src'))
            content = " ".join(
                x.strip() for x in tree.xpath('//*[contains(@class,"details-content-all")]//text()') if x.strip())

            names, groups = self._extract_playlists(html)
            if not groups:
                groups = self._dom_playlists(tree)

            sources, playlists = [], []
            order = [sid for sid in names if sid in groups] + [sid for sid in groups if sid not in names]
            for sid in order:
                items = groups.get(sid) or []
                if not items:
                    continue
                total = len(items)
                sources.append(names.get(sid) or f"线路{len(sources) + 1}")
                plays = []
                for num, label, path in items:
                    plays.append(f"{self._fmt_label(label, num, total)}${path}@@{sid}")
                playlists.append("#".join(plays))

            result.append({
                "vod_id": str(vid), "vod_name": name, "vod_pic": self._fix(pic),
                "vod_content": content,
                "vod_play_from": "$$$".join(sources),
                "vod_play_url": "$$$".join(playlists),
            })
        return {"list": result}

    # ---------------------------------------------------------------- 搜索

    def searchContent(self, key, quick, pg="1"):
        page = max(1, int(pg or 1))
        url = f"{self.host}/vodsearch/-------------.html?wd={quote(key)}&page={page}"
        html = self._get(url)
        videos = self._parse_list(html)
        pages = self._pagecount(etree.HTML(html) if html else etree.HTML("<html/>"), page)
        return {"page": page, "pagecount": pages, "list": videos}

    # ---------------------------------------------------------------- 播放

    def playerContent(self, flag, id, vipFlags):
        path, sid = (id.rsplit("@@", 1) + ["1"])[:2] if "@@" in id else (id, "1")
        url = self._fix(path)
        html = self._get(url, sid)
        marker = "var player_aaaa="
        if marker in html:
            try:
                data = json.JSONDecoder().raw_decode(html.split(marker, 1)[1])[0]
                play_url = data.get("url", "") or ""
                if play_url.startswith("//"):
                    play_url = ("https:" + play_url)
                elif play_url.startswith("/"):
                    play_url = self._fix(play_url)
                if int(data.get("encrypt", 0) or 0) == 1:
                    play_url = quote(play_url, safe=":/?&=%")
                if play_url and any(x in play_url.lower() for x in (".m3u8", ".mp4", ".flv")):
                    return {"parse": 0, "url": play_url,
                            "header": {"User-Agent": self.headers["User-Agent"], "Referer": url}}
            except Exception:
                pass
        return {"parse": 1, "url": url, "header": {**self.headers, "Cookie": "sid=" + sid}}
