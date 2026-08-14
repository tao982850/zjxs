#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVBox 影视仓 Python 爬虫 - hqvod.com (高清点播)
适用于 webhome / TVBox / 影视仓播放器

功能:
  - 首页推荐内容
  - 分类浏览 (电影/电视剧/动漫/综艺/短剧)
  - 多维筛选 (类型/年份/地区/画质)
  - 关键词搜索
  - 详情页解析 (含多播放源)
  - 播放链接提取 (优先4K源)
"""

import re
import json
import urllib.parse
import sys
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 依赖检测 & 兼容层
# ============================================================
try:
    import requests
except ImportError:
    print("[WARN] requests 未安装, 正在安装...")
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("[WARN] beautifulsoup4 未安装, 正在安装...")
    os.system(f"{sys.executable} -m pip install beautifulsoup4 lxml -q")
    from bs4 import BeautifulSoup

# ============================================================
# PyramidStore Spider 基类兼容
# ============================================================
try:
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        def __init__(self, extend=""):
            pass


# ============================================================
# 工具函数
# ============================================================
def safe_get(url, headers=None, params=None, timeout=15, retries=3, encoding=None, referer=None):
    """安全的 HTTP GET 请求, 带重试机制"""
    _headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if headers:
        _headers.update(headers)
    if referer:
        _headers["Referer"] = referer

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=_headers, params=params,
                                timeout=timeout, allow_redirects=True)
            if encoding:
                resp.encoding = encoding
            elif resp.apparent_encoding:
                resp.encoding = resp.apparent_encoding
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt == retries - 1:
                print(f"[ERROR] 请求失败 {url}: {e}")
                return None
    return None


def safe_post(url, headers=None, data=None, json_data=None, timeout=15, retries=3):
    """安全的 HTTP POST 请求"""
    _headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if headers:
        _headers.update(headers)

    for attempt in range(retries):
        try:
            resp = requests.post(url, headers=_headers, data=data,
                                 json=json_data, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt == retries - 1:
                print(f"[ERROR] POST请求失败 {url}: {e}")
                return None
    return None


def clean_html(html_str):
    """清理 HTML 标签"""
    if not html_str:
        return ""
    return re.sub(r'<[^>]+>', '', str(html_str)).strip()


def extract_text(soup_element, selector, attr=None, default=""):
    """从 BeautifulSoup 元素中安全提取文本"""
    try:
        el = soup_element.select_one(selector)
        if el is None:
            return default
        if attr:
            return el.get(attr, default).strip()
        return el.get_text(strip=True) or default
    except Exception:
        return default


# ============================================================
# 主爬虫类
# ============================================================
class Spider(BaseSpider):
    """hqvod.com TVBox 爬虫"""

    def __init__(self, extend=""):
        super().__init__(extend)
        self.siteUrl = "https://hqvod.com"
        self.siteName = "高清点播"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": self.siteUrl,
        })

        # ---- 分类配置 ----
        self.categories = {
            "电影": "1",
            "电视剧": "2",
            "动漫": "3",
            "综艺": "4",
            "短剧": "5",
            "纪录片": "6",
        }

        # ---- 筛选器配置 ----
        self.filter_config = {
            "1": [  # 电影
                {"key": "type", "name": "类型", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "动作片", "v": "6"},
                    {"n": "喜剧片", "v": "7"},
                    {"n": "爱情片", "v": "8"},
                    {"n": "科幻片", "v": "9"},
                    {"n": "恐怖片", "v": "10"},
                    {"n": "剧情片", "v": "11"},
                    {"n": "战争片", "v": "12"},
                    {"n": "犯罪片", "v": "24"},
                    {"n": "奇幻片", "v": "25"},
                    {"n": "动画电影", "v": "26"},
                    {"n": "纪录片", "v": "27"},
                    {"n": "惊悚片", "v": "28"},
                    {"n": "冒险片", "v": "29"},
                    {"n": "悬疑片", "v": "30"},
                    {"n": "武侠片", "v": "31"},
                    {"n": "古装片", "v": "32"},
                    {"n": "历史片", "v": "33"},
                    {"n": "家庭片", "v": "34"},
                    {"n": "音乐片", "v": "35"},
                    {"n": "4K专区", "v": "4k"},
                ]},
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "中国大陆", "v": "中国大陆"},
                    {"n": "中国香港", "v": "中国香港"},
                    {"n": "中国台湾", "v": "中国台湾"},
                    {"n": "美国", "v": "美国"},
                    {"n": "韩国", "v": "韩国"},
                    {"n": "日本", "v": "日本"},
                    {"n": "英国", "v": "英国"},
                    {"n": "法国", "v": "法国"},
                    {"n": "印度", "v": "印度"},
                    {"n": "泰国", "v": "泰国"},
                    {"n": "德国", "v": "德国"},
                    {"n": "其他", "v": "其他"},
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"},
                    {"n": "2022", "v": "2022"},
                    {"n": "2021", "v": "2021"},
                    {"n": "2020", "v": "2020"},
                    {"n": "更早", "v": "2019"},
                ]},
                {"key": "sort", "name": "排序", "value": [
                    {"n": "最新", "v": "time"},
                    {"n": "最热", "v": "hits"},
                    {"n": "评分", "v": "score"},
                ]},
            ],
            "2": [  # 电视剧
                {"key": "type", "name": "类型", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "国产剧", "v": "13"},
                    {"n": "港台剧", "v": "14"},
                    {"n": "日韩剧", "v": "15"},
                    {"n": "欧美剧", "v": "16"},
                    {"n": "泰剧", "v": "36"},
                    {"n": "4K专区", "v": "4k"},
                ]},
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "中国大陆", "v": "中国大陆"},
                    {"n": "中国香港", "v": "中国香港"},
                    {"n": "中国台湾", "v": "中国台湾"},
                    {"n": "美国", "v": "美国"},
                    {"n": "韩国", "v": "韩国"},
                    {"n": "日本", "v": "日本"},
                    {"n": "英国", "v": "英国"},
                    {"n": "泰国", "v": "泰国"},
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"},
                    {"n": "2022", "v": "2022"},
                    {"n": "2021", "v": "2021"},
                    {"n": "2020", "v": "2020"},
                    {"n": "更早", "v": "2019"},
                ]},
                {"key": "sort", "name": "排序", "value": [
                    {"n": "最新", "v": "time"},
                    {"n": "最热", "v": "hits"},
                    {"n": "评分", "v": "score"},
                ]},
            ],
            "3": [  # 动漫
                {"key": "type", "name": "类型", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "国产动漫", "v": "17"},
                    {"n": "日本动漫", "v": "18"},
                    {"n": "欧美动漫", "v": "19"},
                    {"n": "4K专区", "v": "4k"},
                ]},
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "中国大陆", "v": "中国大陆"},
                    {"n": "日本", "v": "日本"},
                    {"n": "美国", "v": "美国"},
                    {"n": "韩国", "v": "韩国"},
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"},
                    {"n": "2022", "v": "2022"},
                    {"n": "更早", "v": "2021"},
                ]},
                {"key": "sort", "name": "排序", "value": [
                    {"n": "最新", "v": "time"},
                    {"n": "最热", "v": "hits"},
                ]},
            ],
            "4": [  # 综艺
                {"key": "type", "name": "类型", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "大陆综艺", "v": "20"},
                    {"n": "港台综艺", "v": "21"},
                    {"n": "日韩综艺", "v": "22"},
                    {"n": "欧美综艺", "v": "23"},
                ]},
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "中国大陆", "v": "中国大陆"},
                    {"n": "中国香港", "v": "中国香港"},
                    {"n": "韩国", "v": "韩国"},
                    {"n": "日本", "v": "日本"},
                    {"n": "美国", "v": "美国"},
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"},
                    {"n": "更早", "v": "2022"},
                ]},
                {"key": "sort", "name": "排序", "value": [
                    {"n": "最新", "v": "time"},
                    {"n": "最热", "v": "hits"},
                ]},
            ],
            "5": [  # 短剧
                {"key": "type", "name": "类型", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "都市", "v": "37"},
                    {"n": "甜宠", "v": "38"},
                    {"n": "穿越", "v": "39"},
                    {"n": "逆袭", "v": "40"},
                    {"n": "复仇", "v": "41"},
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"},
                ]},
                {"key": "sort", "name": "排序", "value": [
                    {"n": "最新", "v": "time"},
                    {"n": "最热", "v": "hits"},
                ]},
            ],
            "6": [  # 纪录片
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"},
                    {"n": "更早", "v": "2023"},
                ]},
                {"key": "sort", "name": "排序", "value": [
                    {"n": "最新", "v": "time"},
                    {"n": "最热", "v": "hits"},
                ]},
            ],
        }

    # ============================================================
    # 基础接口
    # ============================================================
    def getName(self):
        return self.siteName

    def isVideoFormat(self, url):
        """判断是否为直接视频链接"""
        if not url:
            return False
        video_exts = ['.m3u8', '.mp4', '.flv', '.ts', '.mkv', '.avi', '.rmvb', '.wmv']
        url_lower = url.lower().split('?')[0]
        return any(url_lower.endswith(ext) for ext in video_exts)

    def manualVideoCheck(self):
        return True

    def _get_soup(self, html):
        """创建 BeautifulSoup 对象"""
        return BeautifulSoup(html, 'lxml')

    # ============================================================
    # 首页
    # ============================================================
    def homeContent(self, filter):
        """
        获取首页分类和筛选配置
        返回: {class: [...], filters: {...}}
        """
        result = {}

        # 分类列表
        classes = []
        for name, tid in self.categories.items():
            classes.append({
                "type_id": tid,
                "type_name": name,
            })
        result["class"] = classes

        # 筛选器
        if filter:
            result["filters"] = self.filter_config

        return result

    def homeVideoContent(self):
        """
        获取首页推荐视频列表
        返回: {list: [{vod_id, vod_name, vod_pic, vod_remarks}, ...]}
        """
        result = {"list": []}
        videos = []

        # 请求首页
        resp = safe_get(self.siteUrl, referer=self.siteUrl)
        if not resp:
            return result

        try:
            soup = self._get_soup(resp.text)

            # 尝试多种常见选择器解析首页推荐视频
            selectors = [
                ".module-item", ".video-item", ".movie-item",
                ".vod-item", ".list-item", ".card-item",
                ".module-list .item", ".video-list li",
                ".row .col-md-3", ".row .col-lg-2",
                "a[href*='/detail/']", "a[href*='/vod/']",
            ]

            items = []
            for sel in selectors:
                items = soup.select(sel)
                if len(items) > 3:
                    break

            # 如果常规选择器没找到, 尝试提取所有带图片的链接
            if len(items) <= 3:
                items = []
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag.get('href', '')
                    if re.search(r'/detail/\d+|/vod/\d+|/play/\d+', href):
                        img = a_tag.find('img')
                        if img:
                            items.append(a_tag)

            for item in items[:30]:
                try:
                    video = self._parse_video_card(item)
                    if video and video.get("vod_id"):
                        videos.append(video)
                except Exception:
                    continue

        except Exception as e:
            print(f"[ERROR] 解析首页失败: {e}")

        result["list"] = videos
        return result

    # ============================================================
    # 分类页
    # ============================================================
    def categoryContent(self, tid, pg, filter, extend):
        """分类内容获取 - 支持多种URL格式"""
        result = {"list": [], "page": pg, "pagecount": 999, "limit": 24, "total": 9999}
        extend = extend or {}

        # 尝试多种 URL 格式
        urls = self._build_category_urls(tid, pg, extend)

        for url in urls:
            resp = safe_get(url, referer=self.siteUrl)
            if not resp:
                continue

            try:
                soup = self._get_soup(resp.text)
                videos = self._extract_video_list(soup)

                if videos:
                    pagecount = self._extract_page_count(soup)
                    if pagecount > 0:
                        result["pagecount"] = pagecount
                    result["list"] = videos
                    result["page"] = pg
                    return result
            except Exception:
                continue

        return result

    def _build_category_urls(self, tid, pg, extend):
        """构建分类页可能的URL列表"""
        urls = []
        area = extend.get("area", "")
        type_id = extend.get("type", "")
        year = extend.get("year", "")
        sort = extend.get("sort", "")

        # 4K 专区特殊处理
        if type_id == "4k":
            urls.extend([
                f"{self.siteUrl}/show/{tid}----4k---{pg}---.html",
                f"{self.siteUrl}/vod/list/4k/{tid}/{pg}",
                f"{self.siteUrl}/type/{tid}/{pg}?tag=4k",
            ])
            return urls

        # 标准格式
        urls.extend([
            # CMS 常见格式 1: /show/{tid}--{area}--{type}--{year}--{sort}--{pg}.html
            f"{self.siteUrl}/show/{tid}--{area}--{type_id}--{year}--{sort}--{pg}.html",
            # CMS 常见格式 2: /type/{tid}/{pg}.html
            f"{self.siteUrl}/type/{tid}/{pg}.html",
            # CMS 常见格式 3: /vod/list/
            f"{self.siteUrl}/vod/list/?type={tid}&page={pg}",
            # CMS 常见格式 4: /list/{tid}-{pg}.html
            f"{self.siteUrl}/list/{tid}-{pg}.html",
        ])

        return urls

    # ============================================================
    # 详情页
    # ============================================================
    def detailContent(self, ids):
        """
        获取视频详情
        ids: [视频ID]
        返回: {list: [{vod_id, vod_name, vod_pic, vod_year, vod_area,
                       vod_remarks, vod_actor, vod_director, vod_content,
                       vod_play_from, vod_play_url}]}
        """
        result = {"list": []}
        if not ids:
            return result

        video_id = ids[0]

        # 尝试多种详情页URL格式
        detail_urls = [
            f"{self.siteUrl}/detail/{video_id}",
            f"{self.siteUrl}/vod/{video_id}",
            f"{self.siteUrl}/vod/detail/{video_id}",
            f"{self.siteUrl}/video/{video_id}.html",
        ]

        for url in detail_urls:
            resp = safe_get(url, referer=self.siteUrl)
            if not resp:
                continue

            try:
                soup = self._get_soup(resp.text)
                vod = self._parse_detail_page(soup, video_id)
                if vod and vod.get("vod_name"):
                    result["list"] = [vod]
                    return result
            except Exception:
                continue

        return result

    def _parse_detail_page(self, soup, video_id):
        """解析详情页"""
        vod = {
            "vod_id": video_id,
            "vod_name": "",
            "vod_pic": "",
            "vod_year": "",
            "vod_area": "",
            "vod_remarks": "",
            "vod_actor": "",
            "vod_director": "",
            "vod_content": "",
            "vod_play_from": "",
            "vod_play_url": "",
        }

        # ---- 基本信息 ----
        # 标题
        title_selectors = [
            "h1", ".title", ".video-title", ".vod-title",
            ".detail-title", ".info-title", ".name",
        ]
        for sel in title_selectors:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                vod["vod_name"] = el.get_text(strip=True)
                break

        # 海报
        img_selectors = [
            ".pic img", ".poster img", ".thumb img",
            ".video-pic img", ".detail-pic img",
            ".module-item-pic img", "img.lazy",
        ]
        for sel in img_selectors:
            el = soup.select_one(sel)
            if el:
                vod["vod_pic"] = el.get("data-src") or el.get("src") or ""
                if vod["vod_pic"]:
                    break

        # 信息区 - 尝试提取各种元数据
        info_text = ""
        info_selectors = [
            ".info", ".detail-info", ".video-info",
            ".vod-info", ".movie-info", ".module-info",
        ]
        for sel in info_selectors:
            el = soup.select_one(sel)
            if el:
                info_text = el.get_text()
                break

        if info_text:
            # 年份
            year_match = re.search(r'年\s*份[：:]\s*(\d{4})', info_text)
            if year_match:
                vod["vod_year"] = year_match.group(1)

            # 地区
            area_match = re.search(r'地\s*[区区][：:]\s*([^\s,，、]+)', info_text)
            if area_match:
                vod["vod_area"] = area_match.group(1)

            # 导演
            director_match = re.search(r'导\s*演[：:]\s*(.+?)(?=\s*(?:主|编|年|地|状|类|简|标|\n|$))', info_text)
            if director_match:
                vod["vod_director"] = director_match.group(1).strip()[:100]

            # 主演
            actor_match = re.search(r'主\s*演[：:]\s*(.+?)(?=\s*(?:导|编|年|地|状|类|简|标|\n|$))', info_text)
            if actor_match:
                vod["vod_actor"] = actor_match.group(1).strip()[:200]

        # 简介
        desc_selectors = [
            ".desc", ".description", ".intro", ".plot",
            ".content", ".summary", ".story",
        ]
        for sel in desc_selectors:
            el = soup.select_one(sel)
            if el:
                text = clean_html(el.get_text())
                if len(text) > 10:
                    vod["vod_content"] = text[:500]
                    break

        # ---- 播放源 ----
        play_from, play_url = self._extract_play_sources(soup)
        vod["vod_play_from"] = "$$".join(play_from)
        vod["vod_play_url"] = "$$$$$".join(play_url)

        return vod

    def _extract_play_sources(self, soup):
        """从详情页提取播放源列表, 优先提取4K源"""
        play_from = []
        play_url = []

        # 查找播放源标签
        source_selectors = [
            ".source-item", ".play-from", ".from-item",
            ".tab-item", ".play-source", ".source-list li",
            ".module-tab-item", ".nav-item",
        ]

        source_tabs = []
        for sel in source_selectors:
            source_tabs = soup.select(sel)
            if source_tabs:
                break

        if source_tabs:
            for idx, tab in enumerate(source_tabs):
                source_name = tab.get_text(strip=True) or f"线路{idx + 1}"
                # 带4K标记的源优先
                is_4k = "4k" in source_name.lower() or "4K" in source_name
                if is_4k:
                    source_name = f"🔥{source_name}"

                play_from.append(source_name)

                # 获取对应的剧集列表
                episodes = self._find_episodes_for_source(soup, idx)
                if episodes:
                    play_url.append("#".join(episodes))
                else:
                    play_url.append("")
        else:
            # 没有明确的源标签, 直接提取所有剧集
            episodes = self._extract_all_episodes(soup)
            if episodes:
                play_from.append("默认线路")
                play_url.append("#".join(episodes))

        # 如果没有找到任何播放信息, 尝试通用提取
        if not play_from:
            episodes = self._extract_episodes_generic(soup)
            if episodes:
                play_from.append("默认")
                play_url.append("#".join(episodes))

        return play_from, play_url

    def _find_episodes_for_source(self, soup, source_idx):
        """查找指定源的剧集列表"""
        list_selectors = [
            f".module-play-list:nth-child({source_idx + 1})",
            f".play-list-content:nth-child({source_idx + 1})",
            f".source-content:nth-child({source_idx + 1})",
        ]

        for sel in list_selectors:
            container = soup.select_one(sel)
            if container:
                return self._extract_episodes_from_container(container)

        # 通用查找
        all_lists = soup.select(".module-play-list, .play-list-content, .episode-list")
        if source_idx < len(all_lists):
            return self._extract_episodes_from_container(all_lists[source_idx])

        return []

    def _extract_episodes_from_container(self, container):
        """从容器中提取剧集链接"""
        episodes = []
        links = container.find_all('a', href=True)
        for link in links:
            href = link.get('href', '')
            name = link.get_text(strip=True)
            if href and name:
                if re.search(r'/play/|/vod/play|\.html', href):
                    if not href.startswith('http'):
                        href = self.siteUrl + href
                    episodes.append(f"{name}${href}")
        return episodes

    def _extract_all_episodes(self, soup):
        """提取所有剧集"""
        return self._extract_episodes_from_container(soup)

    def _extract_episodes_generic(self, soup):
        """通用剧集提取"""
        episodes = []
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href', '')
            name = a_tag.get_text(strip=True)
            if re.search(r'/play/', href) and name:
                if not href.startswith('http'):
                    href = self.siteUrl + href
                episodes.append(f"{name}${href}")
        return episodes[:100]

    # ============================================================
    # 搜索
    # ============================================================
    def searchContent(self, key, quick, pg=1):
        """搜索功能"""
        return self._do_search(key, pg)

    def searchContentPage(self, key, quick, pg=1):
        """搜索分页"""
        return self._do_search(key, pg)

    def _do_search(self, key, pg=1):
        """执行搜索"""
        result = {"list": []}
        videos = []

        encoded_key = urllib.parse.quote_plus(key)
        search_urls = [
            f"{self.siteUrl}/search?wd={encoded_key}&page={pg}",
            f"{self.siteUrl}/search?keyword={encoded_key}&page={pg}",
            f"{self.siteUrl}/search/{encoded_key}/{pg}.html",
            f"{self.siteUrl}/vod/search/?wd={encoded_key}&page={pg}",
            f"{self.siteUrl}/index.php/ajax/suggest?mid=1&wd={encoded_key}",
        ]

        for url in search_urls:
            resp = safe_get(url, referer=self.siteUrl)
            if not resp:
                continue

            try:
                # 尝试 JSON 解析
                try:
                    data = resp.json()
                    if isinstance(data, dict) and "data" in data:
                        for item in data["data"]:
                            video = {
                                "vod_id": str(item.get("id", item.get("vod_id", ""))),
                                "vod_name": item.get("name", item.get("vod_name", "")),
                                "vod_pic": item.get("pic", item.get("vod_pic", "")),
                                "vod_remarks": item.get("type", item.get("vod_remarks", "")),
                            }
                            if video["vod_id"] and video["vod_name"]:
                                videos.append(video)
                        if videos:
                            result["list"] = videos
                            return result
                except (json.JSONDecodeError, ValueError):
                    pass

                # HTML 解析
                soup = self._get_soup(resp.text)
                videos = self._extract_video_list(soup)
                if videos:
                    result["list"] = videos
                    return result

            except Exception as e:
                print(f"[ERROR] 搜索解析失败: {e}")
                continue

        result["list"] = videos
        return result

    # ============================================================
    # 播放
    # ============================================================
    def playerContent(self, flag, id, vipFlags):
        """获取播放链接"""
        result = {
            "parse": 1,
            "url": id,
            "header": {
                "User-Agent": self.session.headers["User-Agent"],
                "Referer": self.siteUrl,
            }
        }

        # 如果已经是直接视频链接
        if self.isVideoFormat(id):
            result["parse"] = 0
            return result

        # 尝试从播放页提取直链
        if id.startswith("http"):
            play_url = self._extract_play_url(id)
            if play_url:
                result["parse"] = 0
                result["url"] = play_url
                return result

        return result

    def _extract_play_url(self, play_page_url):
        """从播放页提取视频直链"""
        resp = safe_get(play_page_url, referer=self.siteUrl)
        if not resp:
            return None

        html = resp.text

        patterns = [
            r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
            r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
            r'(https?://[^\s"\'<>]+\.flv[^\s"\'<>]*)',
            r'"url"\s*:\s*"(https?://[^"]+)"',
            r"'url'\s*:\s*'(https?://[^']+)'",
            r'videoUrl\s*=\s*["\']([^"\']+)["\']',
            r'player\.url\s*=\s*["\']([^"\']+)["\']',
            r'src\s*:\s*["\']([^"\']+\.(?:m3u8|mp4|flv)[^"\']*)["\']',
        ]

        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                url = match.group(1)
                if self.isVideoFormat(url):
                    return url

        return None

    # ============================================================
    # 内部解析工具
    # ============================================================
    def _parse_video_card(self, item):
        """解析视频卡片元素"""
        video = {
            "vod_id": "",
            "vod_name": "",
            "vod_pic": "",
            "vod_remarks": "",
        }

        link = None
        if item.name == 'a':
            link = item
        else:
            link = item.find('a', href=True)

        if link:
            href = link.get('href', '')
            id_match = re.search(r'/(\d+)\.html|/detail/(\d+)|/vod/(\d+)', href)
            if id_match:
                video["vod_id"] = next(g for g in id_match.groups() if g)
            elif href:
                video["vod_id"] = href.split('/')[-1].replace('.html', '')

        title_selectors = [".title", ".name", ".video-name", "h3", "h4", ".vod-name"]
        for sel in title_selectors:
            el = item.select_one(sel) if hasattr(item, 'select_one') else None
            if el and el.get_text(strip=True):
                video["vod_name"] = el.get_text(strip=True)
                break

        if not video["vod_name"] and link:
            video["vod_name"] = link.get("title", "") or link.get_text(strip=True)

        img = item.find('img') if hasattr(item, 'find') else None
        if img:
            video["vod_pic"] = img.get("data-src") or img.get("src") or img.get("data-original") or ""

        remark_selectors = [".remarks", ".tag", ".note", ".status", ".badge", ".label"]
        for sel in remark_selectors:
            el = item.select_one(sel) if hasattr(item, 'select_one') else None
            if el and el.get_text(strip=True):
                video["vod_remarks"] = el.get_text(strip=True)
                break

        return video

    def _extract_video_list(self, soup):
        """从页面提取视频列表"""
        videos = []

        container_selectors = [
            ".module-list .module-item",
            ".video-list li",
            ".movie-list li",
            ".vod-list li",
            ".list-area .item",
            ".row .col-md-3",
            ".row .col-lg-2",
            ".row .col-6",
            ".module-item",
        ]

        items = []
        for sel in container_selectors:
            items = soup.select(sel)
            if len(items) > 2:
                break

        for item in items[:30]:
            try:
                video = self._parse_video_card(item)
                if video.get("vod_id") and video.get("vod_name"):
                    videos.append(video)
            except Exception:
                continue

        return videos

    def _extract_page_count(self, soup):
        """提取总页数"""
        page_selectors = [
            ".pagination", ".page-link", ".pager",
            ".page-num", ".page_list",
        ]

        for sel in page_selectors:
            elements = soup.select(sel)
            if elements:
                max_page = 1
                for el in elements:
                    text = el.get_text()
                    nums = re.findall(r'\d+', text)
                    for n in nums:
                        try:
                            p = int(n)
                            if p > max_page and p < 10000:
                                max_page = p
                        except ValueError:
                            pass
                return max_page

        return 999


# ============================================================
# 本地调试入口
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="hqvod.com TVBox 爬虫调试工具")
    parser.add_argument("action", choices=["home", "category", "detail", "search", "player"],
                        help="调试功能")
    parser.add_argument("param", nargs="?", default="", help="参数")
    parser.add_argument("--page", type=int, default=1, help="页码")
    parser.add_argument("--filter", action="store_true", help="启用筛选")
    parser.add_argument("--type", default="", help="类型筛选")
    parser.add_argument("--area", default="", help="地区筛选")
    parser.add_argument("--year", default="", help="年份筛选")

    args = parser.parse_args()
    spider = Spider()

    if args.action == "home":
        print("=== 首页 ===")
        result = spider.homeContent(args.filter)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("\n=== 推荐视频 ===")
        videos = spider.homeVideoContent()
        for v in videos.get("list", []):
            print(f"  [{v.get('vod_id')}] {v.get('vod_name')} - {v.get('vod_remarks', '')}")

    elif args.action == "category":
        tid = args.param or "1"
        extend = {}
        if args.type:
            extend["type"] = args.type
        if args.area:
            extend["area"] = args.area
        if args.year:
            extend["year"] = args.year
        print(f"=== 分类 {tid}, 页码 {args.page} ===")
        result = spider.categoryContent(tid, args.page, args.filter, extend)
        for v in result.get("list", []):
            print(f"  [{v.get('vod_id')}] {v.get('vod_name')} - {v.get('vod_remarks', '')}")

    elif args.action == "detail":
        vid = args.param
        print(f"=== 详情 {vid} ===")
        result = spider.detailContent([vid])
        for v in result.get("list", []):
            print(f"  名称: {v.get('vod_name')}")
            print(f"  年份: {v.get('vod_year')}")
            print(f"  地区: {v.get('vod_area')}")
            print(f"  导演: {v.get('vod_director')}")
            print(f"  主演: {v.get('vod_actor')}")
            print(f"  简介: {v.get('vod_content', '')[:100]}...")
            sources = v.get("vod_play_from", "").split("$$")
            print(f"  播放源: {len(sources)} 个")
            for s in sources:
                print(f"    - {s}")

    elif args.action == "search":
        key = args.param
        print(f"=== 搜索: {key} ===")
        result = spider.searchContent(key, False, args.page)
        for v in result.get("list", []):
            print(f"  [{v.get('vod_id')}] {v.get('vod_name')} - {v.get('vod_remarks', '')}")

    elif args.action == "player":
        url = args.param
        print(f"=== 播放: {url} ===")
        result = spider.playerContent("", url, [])
        print(json.dumps(result, ensure_ascii=False, indent=2))