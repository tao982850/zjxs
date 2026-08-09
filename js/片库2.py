# coding=utf-8
"""
目标站: 片库 (4k01.pianku.online)
站点: https://4k01.pianku.online/
海洋CMS架构
"""
import re
import sys
import json
import urllib.parse
from bs4 import BeautifulSoup
import requests

sys.path.append('..')
from base.spider import Spider

class Spider(Spider):
    def init(self, extend=""):
        self.site_url = "https://4k01.pianku.online"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': self.site_url,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        })
        self.categories = self._fetch_categories()

    def _fetch_categories(self):
        """从首页导航栏解析分类"""
        try:
            resp = self.session.get(self.site_url, timeout=10)
            if resp.status_code != 200:
                return self._default_categories()
            soup = BeautifulSoup(resp.text, 'html.parser')
            nav_links = soup.select('ul.nav-list li a')
            categories = []
            seen = set()
            for a in nav_links:
                href = a.get('href', '')
                match = re.search(r'/vodtype/(\d+)\.html', href)
                if not match:
                    continue
                tid = match.group(1)
                name = a.get_text(strip=True)
                if not name or tid in seen or name in ['首页', '留言板', '发布页', '观影导航']:
                    continue
                seen.add(tid)
                categories.append({"type_id": tid, "type_name": name})
            if categories:
                return categories
        except Exception as e:
            print(f"[片库] 获取分类失败: {e}")
        return self._default_categories()

    def _default_categories(self):
        return [
            {"type_id": "20", "type_name": "电影"},
            {"type_id": "37", "type_name": "剧集"},
            {"type_id": "43", "type_name": "动漫"},
            {"type_id": "45", "type_name": "综艺"},
            {"type_id": "47", "type_name": "B站"}
        ]

    def _fix_url(self, url):
        """补全相对路径"""
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        if not url.startswith("http"):
            return urllib.parse.urljoin(self.site_url + "/", url)
        return url

    def _parse_video_list(self, html):
        """从HTML中解析视频列表"""
        if not html:
            return []
        soup = BeautifulSoup(html, 'html.parser')
        results = []
        seen = set()
        items = soup.select('div.vod-item')
        for item in items:
            link = item.select_one('a')
            if not link:
                continue
            href = link.get('href', '')
            vod_id = re.search(r'/voddetail/(\d+)\.html', href)
            if not vod_id:
                continue
            vid = vod_id.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            title = link.get('title', '')
            if not title:
                title_elem = item.select_one('.vod-info .title')
                if title_elem:
                    title = title_elem.get_text(strip=True)
            if not title:
                continue
            pic = ''
            img = item.select_one('.vod-pic img')
            if img:
                pic = img.get('src', '') or img.get('data-original', '') or img.get('data-src', '')
            remark = ''
            remark_elem = item.select_one('.vod-pic .remarks')
            if remark_elem:
                remark = remark_elem.get_text(strip=True)
            results.append({
                "vod_id": vid,
                "vod_name": title.strip(),
                "vod_pic": self._fix_url(pic),
                "vod_remarks": remark
            })
        return results

    # ================= 首页推荐 =================
    def homeContent(self, filter):
        url = self.site_url + "/"
        resp = self.session.get(url, timeout=10)
        video_list = []
        if resp.status_code == 200:
            video_list = self._parse_video_list(resp.text)
            video_list = video_list[:30]
        return {"class": self.categories, "list": video_list, "filters": {}}

    def homeVideoContent(self):
        return self.homeContent(False)

    # ================= 分类列表 =================
    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        if page == 1:
            url = f"{self.site_url}/vodtype/{tid}.html"
        else:
            url = f"{self.site_url}/vodtype/{tid}-{page}.html"
        
        resp = self.session.get(url, timeout=10)
        if resp.status_code != 200:
            return {"list": [], "page": page, "pagecount": 1, "limit": 24, "total": 0}

        video_list = self._parse_video_list(resp.text)
        pagecount = page
        soup = BeautifulSoup(resp.text, 'html.parser')
        pagination = soup.select('.page a')
        if pagination:
            for a in pagination:
                text = a.get_text(strip=True)
                if text.isdigit():
                    pagecount = max(pagecount, int(text))
        return {
            "list": video_list,
            "page": page,
            "pagecount": pagecount,
            "limit": 24,
            "total": len(video_list) * pagecount
        }

    # ================= 详情页 =================
    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = ids[0]
        url = f"{self.site_url}/voddetail/{vod_id}.html"
        resp = self.session.get(url, timeout=10)
        if resp.status_code != 200:
            return {"list": []}

        soup = BeautifulSoup(resp.text, 'html.parser')
        title_elem = soup.select_one('.detail-title h1') or soup.select_one('h1')
        vod_name = title_elem.get_text(strip=True) if title_elem else vod_id
        vod_pic = ''
        img_elem = soup.select_one('.detail-pic img')
        if img_elem:
            vod_pic = img_elem.get('src', '') or img_elem.get('data-original', '')
            vod_pic = self._fix_url(vod_pic)
        vod_content = ''
        content_elem = soup.select_one('.detail-desc')
        if content_elem:
            vod_content = content_elem.get_text(' ', strip=True)
        vod_actor = ''
        actor_elem = soup.select_one('.detail-meta span:contains("主演")')
        if actor_elem:
            vod_actor = actor_elem.get_text(strip=True).replace('主演：', '').strip()
        vod_director = ''
        director_elem = soup.select_one('.detail-meta span:contains("导演")')
        if director_elem:
            vod_director = director_elem.get_text(strip=True).replace('导演：', '').strip()
        vod_year = ''
        year_elem = soup.select_one('.detail-meta span:contains("年份")')
        if year_elem:
            vod_year = year_elem.get_text(strip=True).replace('年份：', '').strip()

        # ===== 播放线路解析 =====
        play_from_list = []
        play_url_list = []

        source_tabs = soup.select('.source-tabs .source-tab-item')
        source_contents = soup.select('.source-content .source-pane')

        if source_tabs and source_contents:
            for idx, tab in enumerate(source_tabs):
                line_name = tab.get_text(strip=True) or f"线路{idx+1}"
                pane = source_contents[idx] if idx < len(source_contents) else None
                if not pane:
                    continue
                episodes = []
                for a in pane.select('a.play-btn-item'):
                    href = a.get('href', '')
                    if not href or 'javascript:' in href:
                        continue
                    ep_name = a.get('title', '') or a.get_text(strip=True) or f"第{len(episodes)+1}集"
                    full_url = self._fix_url(href)
                    episodes.append(f"{ep_name}${full_url}")
                if episodes:
                    play_from_list.append(line_name)
                    play_url_list.append('#'.join(episodes))
        else:
            all_links = soup.select('a[href*="/vodplay/"]')
            if all_links:
                episodes = []
                for a in all_links:
                    href = a.get('href', '')
                    ep_name = a.get('title', '') or a.get_text(strip=True) or f"第{len(episodes)+1}集"
                    full_url = self._fix_url(href)
                    episodes.append(f"{ep_name}${full_url}")
                if episodes:
                    play_from_list.append('默认线路')
                    play_url_list.append('#'.join(episodes))

        vod_play_from = '$$$'.join(play_from_list) if play_from_list else '默认源'
        vod_play_url = '$$$'.join(play_url_list) if play_url_list else f"播放${vod_id}"

        result = [{
            "vod_id": vod_id,
            "vod_name": vod_name,
            "vod_pic": vod_pic,
            "vod_content": vod_content,
            "vod_actor": vod_actor,
            "vod_director": vod_director,
            "vod_area": "",
            "vod_year": vod_year,
            "vod_play_from": vod_play_from,
            "vod_play_url": vod_play_url
        }]
        return {"list": result}

    # ================= 搜索 =================
    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        encoded_key = urllib.parse.quote(key)
        url = f"{self.site_url}/vodsearch/-------------.html?wd={encoded_key}"
        resp = self.session.get(url, timeout=10)
        if resp.status_code != 200:
            return {"list": [], "page": page, "pagecount": 1}
        video_list = self._parse_video_list(resp.text)
        return {"list": video_list, "page": page, "pagecount": 1}

    # ================= 播放解析 =================
    def playerContent(self, flag, id, vipFlags):
        """解析播放地址，提取真实的m3u8直链"""
        play_url = self._fix_url(id)
        
        # 如果已经是m3u8直链，直接返回
        if re.search(r'\.m3u8', play_url, re.I):
            return {"parse": 0, "url": play_url, "header": dict(self.session.headers)}
        
        # 如果是mp4，也直接返回（但可能是广告，后面会过滤）
        if re.search(r'\.mp4', play_url, re.I):
            return {"parse": 0, "url": play_url, "header": dict(self.session.headers)}
        
        # 获取播放页面内容
        try:
            resp = self.session.get(play_url, timeout=15)
            if resp.status_code != 200:
                return {"parse": 1, "url": play_url, "header": dict(self.session.headers)}
        except:
            return {"parse": 1, "url": play_url, "header": dict(self.session.headers)}
        
        html = resp.text
        
        # ===== 核心解析逻辑 =====
        
        # 1. 优先从 player_aaaa 中提取（海洋CMS标准）
        match = re.search(r'var\s+player_aaaa\s*=\s*({[^;]+});', html)
        if match:
            try:
                data = json.loads(match.group(1))
                if data.get('url'):
                    video_url = data['url']
                    # 如果是外站，直接返回让客户端处理
                    if any(domain in video_url for domain in ['mgtv.com', 'v.qq.com', 'iqiyi.com', 'youku.com', 'bilibili.com']):
                        return {"parse": 1, "url": video_url, "header": dict(self.session.headers)}
                    # 如果是m3u8，直接返回
                    if '.m3u8' in video_url.lower():
                        return {"parse": 0, "url": video_url, "header": dict(self.session.headers)}
            except:
                pass
        
        # 2. 从 player_bbbb 中提取
        match = re.search(r'var\s+player_bbbb\s*=\s*({[^;]+});', html)
        if match:
            try:
                data = json.loads(match.group(1))
                if data.get('url'):
                    video_url = data['url']
                    if any(domain in video_url for domain in ['mgtv.com', 'v.qq.com', 'iqiyi.com', 'youku.com', 'bilibili.com']):
                        return {"parse": 1, "url": video_url, "header": dict(self.session.headers)}
                    if '.m3u8' in video_url.lower():
                        return {"parse": 0, "url": video_url, "header": dict(self.session.headers)}
            except:
                pass
        
        # 3. 查找 iframe 中的外站地址
        iframe = re.search(r'<iframe[^>]+src="([^"]+)"', html, re.I)
        if iframe:
            iframe_url = self._fix_url(iframe.group(1))
            # 如果是外站，返回让客户端处理
            if any(domain in iframe_url for domain in ['mgtv.com', 'v.qq.com', 'iqiyi.com', 'youku.com', 'bilibili.com']):
                return {"parse": 1, "url": iframe_url, "header": dict(self.session.headers)}
            # 如果是m3u8，直接返回
            if '.m3u8' in iframe_url.lower():
                return {"parse": 0, "url": iframe_url, "header": dict(self.session.headers)}
        
        # 4. 直接匹配m3u8地址（取第一个非广告的）
        m3u8_list = re.findall(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', html, re.I)
        for m3u8_url in m3u8_list:
            # 过滤明显的广告域名
            if 'ad' not in m3u8_url.lower() and 'doubleclick' not in m3u8_url.lower():
                return {"parse": 0, "url": m3u8_url, "header": dict(self.session.headers)}
        
        # 5. 匹配mp4地址（可能是广告，但如果没有m3u8也只能返回）
        mp4_list = re.findall(r'(https?://[^\s"\']+\.mp4[^\s"\']*)', html, re.I)
        for mp4_url in mp4_list:
            if 'ad' not in mp4_url.lower() and 'doubleclick' not in mp4_url.lower():
                return {"parse": 0, "url": mp4_url, "header": dict(self.session.headers)}
        
        # 6. 如果都找不到，返回原链接让客户端处理
        return {"parse": 1, "url": play_url, "header": dict(self.session.headers)}

    def getName(self):
        return "片库"

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        self.session.close()