# -*- coding: utf-8 -*-
import json
import re
import time
import urllib.parse
import requests
from bs4 import BeautifulSoup
from base.spider import Spider

class Spider(Spider):
    def __init__(self):
        super().__init__()
        self.site_url = ""
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def getName(self):
        return "狐狸磁力"

    def init(self, extend=""):
        try:
            if isinstance(extend, str):
                ext = json.loads(extend)
            else:
                ext = extend
            
            sites = ext.get("site", [])
            for domain in sites:
                try:
                    res = requests.get(domain, headers=self.headers, timeout=5)
                    if res.status_code == 200:
                        self.site_url = domain.rstrip('/')
                        break
                except Exception:
                    continue
            
            if not self.site_url and sites:
                self.site_url = sites[0].rstrip('/')
        except Exception:
            self.site_url = "https://www.foxjun.com"

    def homeContent(self, filter):
        result = {}
        classes = [
            {"type_name": "电影", "type_id": "dianying"},
            {"type_name": "动画", "type_id": "donghua"},
            {"type_name": "美欧剧", "type_id": "meiouju"},
            {"type_name": "国产剧", "type_id": "guochanju"},
            {"type_name": "日韩剧", "type_id": "rihanju"}
        ]
        result['class'] = classes
        return result

    def categoryContent(self, tid, pg, filter, extend):
        result = {}
        url = f"{self.site_url}/channel/{tid}.html?apage1={pg}"
        videos = []
        seen_ids = set()
        
        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            media_items = soup.find_all("div", class_=re.compile(r"media")) or soup.find_all("li")
            
            for item in media_items:
                a_tag = item.find("a")
                if not a_tag or not a_tag.get("href"):
                    continue
                
                href = a_tag["href"]
                if not href.startswith("http") and not href.startswith("/"):
                    continue
                
                v_id = href if href.startswith("http") else self.site_url + href
                
                if v_id in seen_ids:
                    continue

                img_tag = item.find("img")
                cover = ""
                if img_tag:
                    cover = img_tag.get("data-src") or img_tag.get("src", "")
                
                title = re.sub(r"[《》]", "", a_tag.get_text(strip=True))
                if not cover or not title or title.isdigit() or len(title) < 2:
                    continue

                if title and v_id:
                    seen_ids.add(v_id)
                    videos.append({
                        "vod_id": v_id,
                        "vod_name": title,
                        "vod_pic": cover,
                        "vod_remarks": ""
                    })
        except Exception:
            pass

        result['list'] = videos
        result['page'] = pg
        result['pagecount'] = 9999
        result['limit'] = len(videos)
        result['total'] = 9999
        return result

    def detailContent(self, ids):
        v_id = ids[0]
        result = {}
        
        try:
            res = requests.get(v_id, headers=self.headers, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            page_text = soup.get_text()

            title_node = soup.find("h1") or soup.find("title")
            title = title_node.get_text(strip=True) if title_node else "未知"

            def extract_info(pattern):
                match = re.search(pattern, page_text)
                return match.group(1).strip() if match else ""

            play_sources = {}

            quark_urls = re.findall(r'(https?://pan\.quark\.cn/s/[a-zA-Z0-9]+(?:\?pwd=[a-zA-Z0-9]+)?)', page_text)
            if quark_urls:
                for idx, u in enumerate(quark_urls):
                    line_name = f"夸克原画#01{idx+1:02d}" if idx == 0 else f"夸克智#01{idx+1:02d}"
                    play_sources[line_name] = [f"S01E{i+1}${u}" for i in range(36)]

            baidu_urls = re.findall(r'(https?://pan\.baidu\.com/s/[a-zA-Z0-9_-]+(?:\?pwd=[a-zA-Z0-9]+)?)', page_text)
            if baidu_urls:
                for idx, u in enumerate(baidu_urls):
                    line_name = f"百度原画#01{idx+1:02d}"
                    play_sources[line_name] = [f"S01E{i+1}${u}" for i in range(36)]

            # 已屏蔽迅雷源解析
            # xunlei_urls = re.findall(r'(https?://pan\.xunlei\.com/s/[a-zA-Z0-9_-]+(?:\?pwd=[a-zA-Z0-9]+)?)', page_text)

            ali_urls = re.findall(r'(https?://(?:www\.)?alipan\.com/s/[a-zA-Z0-9]+)', page_text)
            if ali_urls:
                for idx, u in enumerate(ali_urls):
                    line_name = f"阿里原画#01{idx+1:02d}"
                    play_sources[line_name] = [f"S01E{i+1}${u}" for i in range(36)]

            if not play_sources:
                play_sources["默认线路#0101"] = [f"播放源${v_id}"]

            from_names = list(play_sources.keys())
            play_urls = ["#".join(urls) for urls in play_sources.values()]

            vod = {
                "vod_id": v_id,
                "vod_name": title,
                "vod_type": extract_info(r"类型：([^\n\r<]+)"),
                "vod_year": extract_info(r"上映日期：([^\n\r<]+)"),
                "vod_area": extract_info(r"地区：([^\n\r<]+)"),
                "vod_director": extract_info(r"导演：([^\n\r<]+)"),
                "vod_actor": extract_info(r"主演：([^\n\r<]+)"),
                "vod_content": extract_info(r"简介：([^\n\r<]+)"),
                "vod_play_from": "$$$".join(from_names),
                "vod_play_url": "$$$".join(play_urls)
            }
            result['list'] = [vod]
        except Exception:
            result['list'] = []

        return result

    def searchContent(self, key, quick, pg="1"):
        result = {}
        videos = []
        seen_ids = set()

        search_urls = [
            f"{self.site_url}/s?q={urllib.parse.quote(key)}&page={pg}",
            f"{self.site_url}/search?word={urllib.parse.quote(key)}&page={pg}",
            f"{self.site_url}/so?wd={urllib.parse.quote(key)}"
        ]

        for search_url in search_urls:
            try:
                search_headers = self.headers.copy()
                search_headers["Referer"] = self.site_url + "/"
                res = requests.get(search_url, headers=search_headers, timeout=10)
                if res.status_code != 200:
                    continue
                
                soup = BeautifulSoup(res.text, "html.parser")
                media_items = soup.find_all("div", class_=re.compile(r"media")) or soup.find_all("li")

                temp_videos = []
                for item in media_items:
                    a_tag = item.find("a")
                    if not a_tag or not a_tag.get("href"):
                        continue

                    href = a_tag["href"]
                    if not href.startswith("http") and not href.startswith("/"):
                        continue

                    v_id = href if href.startswith("http") else self.site_url + href
                    
                    if v_id in seen_ids:
                        continue

                    img_tag = item.find("img")
                    cover = ""
                    if img_tag:
                        cover = img_tag.get("data-src") or img_tag.get("src", "")
                    
                    title = a_tag.get_text(strip=True)

                    if not cover or not title or title.isdigit() or len(title) < 2:
                        continue

                    temp_videos.append({
                        "vod_id": v_id,
                        "vod_name": title,
                        "vod_pic": cover,
                        "vod_remarks": ""
                    })
                
                matched_videos = [v for v in temp_videos if key.lower() in v["vod_name"].lower()]
                if matched_videos:
                    for v in matched_videos:
                        if v["vod_id"] not in seen_ids:
                            seen_ids.add(v["vod_id"])
                            videos.append(v)
                    break
            except Exception:
                continue

        if not videos and pg == "1":
            tids = ["dianying", "donghua", "meiouju", "guochanju", "rihanju"]
            for tid in tids:
                try:
                    cat_url = f"{self.site_url}/channel/{tid}.html"
                    res = requests.get(cat_url, headers=self.headers, timeout=5)
                    if res.status_code != 200:
                        continue
                    soup = BeautifulSoup(res.text, "html.parser")
                    media_items = soup.find_all("div", class_=re.compile(r"media")) or soup.find_all("li")
                    
                    for item in media_items:
                        a_tag = item.find("a")
                        if not a_tag or not a_tag.get("href"):
                            continue
                        href = a_tag["href"]
                        if not href.startswith("http") and not href.startswith("/"):
                            continue
                        v_id = href if href.startswith("http") else self.site_url + href
                        if v_id in seen_ids:
                            continue
                        
                        img_tag = item.find("img")
                        cover = ""
                        if img_tag:
                            cover = img_tag.get("data-src") or img_tag.get("src", "")
                        
                        title = re.sub(r"[《》]", "", a_tag.get_text(strip=True))
                        if not cover or not title or title.isdigit() or len(title) < 2:
                            continue
                        
                        if key.lower() in title.lower():
                            seen_ids.add(v_id)
                            videos.append({
                                "vod_id": v_id,
                                "vod_name": title,
                                "vod_pic": cover,
                                "vod_remarks": ""
                            })
                except Exception:
                    continue

        result['list'] = videos
        return result

    def playerContent(self, flag, id, vipFlags):
        if any(pan in id for pan in ["pan.quark.cn", "pan.baidu.com", "alipan.com", "aliyundrive.com"]):
            # 增加 5 秒延迟后再触发推送
            time.sleep(5)
            return {
                "parse": 0,
                "playUrl": "",
                "url": f"push://{id}",
                "header": self.headers
            }
        return {
            "parse": 0,
            "playUrl": "",
            "url": id,
            "header": self.headers
        }
