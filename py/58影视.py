# -*- coding: utf-8 -*-
"""
影视源: 58影视 (www.58hu.com)
完整版：动态提取所有分类（主+子），保留筛选
"""

import re
import json
import urllib.parse
import requests
from bs4 import BeautifulSoup
from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    def init(self, extend=""):
        self.host = "https://www.58hu.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": self.host + "/",
        }
        # 动态提取所有分类（包括二级分类）
        self.categories = self._fetch_all_categories()
        # 构建筛选器（类型、地区、年份）
        self.filters = self._build_filters()

    def getName(self):
        return "58影视"

    # ---------- 提取所有分类（主+子） ----------
    def _fetch_all_categories(self):
        """从首页导航中提取所有分类链接，保留顺序"""
        html = self._fetch("/")
        if not html:
            # 兜底分类（常见主分类）
            return [
                {"type_id": "1", "type_name": "电影"},
                {"type_id": "2", "type_name": "连续剧"},
                {"type_id": "3", "type_name": "综艺"},
                {"type_id": "4", "type_name": "动漫"},
                {"type_id": "20", "type_name": "短剧"},
                {"type_id": "21", "type_name": "体育"},
            ]

        soup = BeautifulSoup(html, "html.parser")
        categories = []
        seen = set()

        # 查找导航区域（通常是最顶部的ul）
        nav_ul = soup.select_one("ul.nav, ul.navbar-nav, .nav-menu, ul:has(a[href*='/vod/show/id/'])")
        if nav_ul:
            links = nav_ul.find_all("a", href=re.compile(r"/vod/show/id/\d+"))
        else:
            links = soup.find_all("a", href=re.compile(r"/vod/show/id/\d+"))

        for a in links:
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if not text or text in ["首页", "推荐", "导航", "更多"]:
                continue
            m = re.search(r"/id/(\d+)\.html", href)
            if m:
                tid = m.group(1)
                if tid not in seen:
                    seen.add(tid)
                    categories.append({"type_id": tid, "type_name": text})

        # 如果提取到的分类太少，使用兜底
        if len(categories) < 5:
            return [
                {"type_id": "1", "type_name": "电影"},
                {"type_id": "2", "type_name": "连续剧"},
                {"type_id": "3", "type_name": "综艺"},
                {"type_id": "4", "type_name": "动漫"},
                {"type_id": "20", "type_name": "短剧"},
                {"type_id": "21", "type_name": "体育"},
            ]

        return categories

    # ---------- 构建筛选器 ----------
    def _build_filters(self):
        """类型、地区、年份筛选器"""
        type_opts = [
            {"n": "全部", "v": ""},
            {"n": "喜剧", "v": "喜剧"},
            {"n": "爱情", "v": "爱情"},
            {"n": "恐怖", "v": "恐怖"},
            {"n": "动作", "v": "动作"},
            {"n": "科幻", "v": "科幻"},
            {"n": "剧情", "v": "剧情"},
            {"n": "奇幻", "v": "奇幻"},
            {"n": "武侠", "v": "武侠"},
            {"n": "冒险", "v": "冒险"},
            {"n": "枪战", "v": "枪战"},
            {"n": "悬疑", "v": "悬疑"},
            {"n": "微电影", "v": "微电影"},
            {"n": "古装", "v": "古装"},
            {"n": "历史", "v": "历史"},
            {"n": "运动", "v": "运动"},
            {"n": "农村", "v": "农村"},
            {"n": "儿童", "v": "儿童"},
            {"n": "其他", "v": "其他"},
        ]
        area_opts = [
            {"n": "全部", "v": ""},
            {"n": "内地", "v": "内地"},
            {"n": "韩国", "v": "韩国"},
            {"n": "香港", "v": "香港"},
            {"n": "台湾", "v": "台湾"},
            {"n": "日本", "v": "日本"},
            {"n": "美国", "v": "美国"},
            {"n": "泰国", "v": "泰国"},
            {"n": "英国", "v": "英国"},
            {"n": "新加坡", "v": "新加坡"},
            {"n": "其他", "v": "其他"},
        ]
        year_opts = [{"n": "全部", "v": ""}]
        for y in range(2026, 1997, -1):
            year_opts.append({"n": str(y), "v": str(y)})

        filters = {}
        for cat in self.categories:
            tid = cat["type_id"]
            filters[tid] = [
                {"key": "type", "name": "类型", "value": type_opts},
                {"key": "area", "name": "地区", "value": area_opts},
                {"key": "year", "name": "年份", "value": year_opts},
            ]
        return filters

    # ---------- 请求封装 ----------
    def _fetch(self, url):
        try:
            if not url.startswith("http"):
                url = self.host + url
            rsp = requests.get(url, headers=self.headers, timeout=15, verify=False)
            rsp.encoding = "utf-8"
            return rsp.text
        except Exception as e:
            print(f"[58影视] 请求异常: {e}")
            return ""

    # ---------- 解析视频列表 ----------
    def _parse_video_list(self, html):
        videos = []
        if not html:
            return videos
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select("li.pic-list-hover")
        if not items:
            items = soup.select('a[href*="/vod/detail/id/"]')
        for item in items:
            if item.name == "a":
                a = item
            else:
                a = item.select_one('a.pic-img, a[href*="/vod/detail/id/"]')
                if not a:
                    continue
            href = a.get("href", "")
            m = re.search(r"/vod/detail/id/(\d+)\.html", href)
            if not m:
                continue
            vod_id = m.group(1)
            vod_name = ""
            title_el = item.select_one("h3.name a, .name a")
            if title_el:
                vod_name = title_el.get_text(strip=True)
            if not vod_name:
                vod_name = a.get("title", "").strip()
            if not vod_name:
                img = a.find("img")
                if img:
                    vod_name = img.get("alt", "").strip()
            img = a.find("img", class_="lazyload")
            if not img:
                img = a.find("img")
            vod_pic = ""
            if img:
                vod_pic = img.get("data-original") or img.get("src", "")
                if vod_pic and not vod_pic.startswith("http"):
                    if vod_pic.startswith("//"):
                        vod_pic = "https:" + vod_pic
                    elif vod_pic.startswith("/"):
                        vod_pic = self.host + vod_pic
            vod_remarks = ""
            titles_span = item.select_one("span.titles")
            if titles_span:
                vod_remarks = titles_span.get_text(strip=True)
            if not vod_remarks:
                remark = item.select_one(".public-list-prb, .remark, .pic-text")
                if remark:
                    vod_remarks = remark.get_text(strip=True)
            if vod_id and vod_name:
                videos.append({
                    "vod_id": vod_id,
                    "vod_name": vod_name,
                    "vod_pic": vod_pic,
                    "vod_remarks": vod_remarks,
                })
        return videos

    # ---------- 解析播放列表 ----------
    def _parse_playlist(self, soup):
        play_from = []
        play_url = []

        tab_ul = soup.select_one("ul.play-nav#Tab")
        if not tab_ul:
            return play_from, play_url

        for li in tab_ul.select("li"):
            a = li.select_one("a")
            if not a:
                continue
            line_name = a.get_text(strip=True)
            if not line_name:
                continue
            container_id = a.get("id", "")
            if container_id.startswith("#"):
                container_id = container_id[1:]
            if not container_id:
                href = a.get("href", "")
                m = re.search(r"#(con_playlist_\d+)", href)
                if m:
                    container_id = m.group(1)
                else:
                    continue

            ul_container = soup.find("ul", id=container_id)
            if not ul_container:
                ul_container = soup.select_one(f"ul#{container_id}")
            if not ul_container:
                continue

            ep_links = ul_container.select("a[href*='/vod/play/id/']")
            if not ep_links:
                ep_links = ul_container.find_all("a", href=re.compile(r"/vod/play/id/"))

            if not ep_links:
                continue

            ep_list = []
            for a in ep_links:
                href = a.get("href", "")
                ep_name = a.get_text(strip=True) or a.get("title", "")
                if href:
                    if not href.startswith("http"):
                        href = self.host + href
                    ep_list.append(f"{ep_name}${href}")

            if ep_list:
                play_from.append(line_name)
                play_url.append("#".join(ep_list))

        if not play_from:
            ep_links = soup.select('a[href*="/vod/play/id/"]')
            if ep_links:
                ep_list = []
                for a in ep_links:
                    href = a.get("href", "")
                    ep_name = a.get_text(strip=True) or a.get("title", "")
                    if href:
                        if not href.startswith("http"):
                            href = self.host + href
                        ep_list.append(f"{ep_name}${href}")
                if ep_list:
                    play_from.append("默认线路")
                    play_url.append("#".join(ep_list))

        return play_from, play_url

    # ---------- 核心接口 ----------
    def homeContent(self, filter):
        return {"class": self.categories, "filters": self.filters}

    def homeVideoContent(self):
        html = self._fetch("/")
        return {"list": self._parse_video_list(html)[:24]}

    def categoryContent(self, tid, pg, filter, extend):
        params = {}
        if extend and isinstance(extend, dict):
            params.update(extend)
        if filter and isinstance(filter, dict):
            params.update(filter)

        types = params.get("type", "")
        area = params.get("area", "")
        year = params.get("year", "")

        # 使用正确的分类链接格式
        url = f"/index.php/vod/show/id/{tid}.html"
        query_params = {}
        if pg and int(pg) > 1:
            query_params["page"] = pg
        if types:
            query_params["type"] = types
        if area:
            query_params["area"] = area
        if year:
            query_params["year"] = year

        if query_params:
            url += "?" + urllib.parse.urlencode(query_params)

        html = self._fetch(url)
        items = self._parse_video_list(html)

        # 获取总页数
        pagecount = 1
        if html:
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.select("a.page-link, .page a"):
                href = a.get("href", "")
                m = re.search(r"page=(\d+)", href)
                if m:
                    p = int(m.group(1))
                    if p > pagecount:
                        pagecount = p
            if pagecount == 1 and len(items) >= 20:
                pagecount = int(pg) + 5

        return {
            "list": items,
            "page": int(pg),
            "pagecount": pagecount,
            "limit": 24,
            "total": 9999,
        }

    def detailContent(self, ids):
        result = {"list": []}
        if not ids:
            return result
        vod_id = ids[0].split(",")[0].strip()
        url = f"/index.php/vod/detail/id/{vod_id}.html"
        html = self._fetch(url)
        if not html:
            return result
        soup = BeautifulSoup(html, "html.parser")

        vod_name = ""
        h1 = soup.find("h1")
        if h1:
            vod_name = h1.get_text(strip=True)
        if not vod_name:
            title_tag = soup.find("title")
            if title_tag:
                vod_name = title_tag.text.split("_")[0].strip()

        vod_pic = ""
        img = soup.select_one("img.lazyload, img[data-original]")
        if img:
            vod_pic = img.get("data-original") or img.get("data-src") or img.get("src", "")
            if vod_pic and not vod_pic.startswith("http"):
                if vod_pic.startswith("//"):
                    vod_pic = "https:" + vod_pic
                elif vod_pic.startswith("/"):
                    vod_pic = self.host + vod_pic

        vod_content = ""
        desc = soup.select_one(".vod-content, .desc, #height_limit")
        if desc:
            vod_content = desc.get_text(" ", strip=True)
        if not vod_content:
            meta_desc = soup.find("meta", {"name": "description"})
            if meta_desc:
                vod_content = meta_desc.get("content", "")

        vod_actor = ""
        actor_links = soup.select('a[href*="/vod/search/actor/"]')
        if not actor_links:
            actor_links = soup.select(".vod-actor a, .actor a")
        if actor_links:
            actors = [a.get_text(strip=True) for a in actor_links]
            vod_actor = ", ".join(actors)

        vod_director = ""
        director_links = soup.select('a[href*="/vod/search/director/"]')
        if not director_links:
            director_links = soup.select(".vod-director a, .director a")
        if director_links:
            directors = [a.get_text(strip=True) for a in director_links]
            vod_director = ", ".join(directors)

        vod_year = ""
        year_span = soup.find("span", string=re.compile(r"\d{4}"))
        if year_span:
            m = re.search(r"(\d{4})", year_span.get_text(strip=True))
            if m:
                vod_year = m.group(1)

        play_from, play_url = self._parse_playlist(soup)

        vod = {
            "vod_id": vod_id,
            "vod_name": vod_name,
            "vod_pic": vod_pic,
            "vod_actor": vod_actor,
            "vod_director": vod_director,
            "vod_year": vod_year,
            "vod_content": vod_content,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }
        result["list"].append(vod)
        return result

    def searchContent(self, key, quick, pg="1"):
        result = {"list": [], "page": int(pg), "pagecount": 0}
        if not key:
            return result
        try:
            url = f"/index.php/vod/search.html?wd={key}&page={pg}"
            html = self._fetch(url)
            if html:
                items = self._parse_video_list(html)
                result["list"] = items
                result["pagecount"] = int(pg) + 1 if len(items) >= 20 else int(pg)
                return result
        except:
            pass
        return result

    def playerContent(self, flag, id, vipFlags):
        try:
            if not id.startswith("http"):
                play_url = self.host + id
            else:
                play_url = id
            html = self._fetch(play_url)
            if not html:
                return {"parse": 1, "url": play_url, "header": {}}

            video_url = ""
            player_match = re.search(r'player_aaaa\s*=\s*(\{.*?\})', html, re.DOTALL)
            if player_match:
                try:
                    data = json.loads(player_match.group(1))
                    video_url = data.get("url", "")
                except:
                    pass

            if not video_url:
                iframe = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html)
                if iframe:
                    video_url = iframe.group(1)

            if not video_url:
                m3u8_match = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', html)
                if m3u8_match:
                    video_url = m3u8_match.group(1)

            if not video_url:
                mp4_match = re.search(r'(https?://[^\s"\']+\.mp4[^\s"\']*)', html)
                if mp4_match:
                    video_url = mp4_match.group(1)

            if video_url:
                if video_url.startswith("//"):
                    video_url = "https:" + video_url
                return {
                    "parse": 0,
                    "url": video_url,
                    "header": {"User-Agent": self.headers["User-Agent"], "Referer": self.host + "/"}
                }

            return {"parse": 1, "url": play_url, "header": {}}
        except Exception as e:
            print(f"[58影视] 播放解析异常: {e}")
            return {"parse": 1, "url": id, "header": {}}

    def localProxy(self, param=""):
        return {}

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False