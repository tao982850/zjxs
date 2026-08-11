# coding=utf-8
"""
目标站: HDV.CC (https://hdv.cc/)
功能: 首页推荐、分类、搜索、详情、剧集列表、播放接口解析
适配: CatVod / TVBox Python Spider 接口风格
修复: 完整重写播放解析、支持多线路、DRM处理
"""
import re
import sys
import json
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    def init(self, extend=""):
        self.site_url = "https://hdv.cc"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.site_url + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        self.cookie_jar = {}
        self.categories = self._fetch_categories()

    # ================= 基础工具 =================
    def _abs_url(self, url):
        if not url:
            return ""
        if url.startswith("http"):
            return url
        if url.startswith("//"):
            return "https:" + url
        return urllib.parse.urljoin(self.site_url + "/", url)

    def _get_text(self, node):
        return node.get_text(" ", strip=True) if node else ""

    def _fetch_html(self, url, headers=None):
        try:
            h = dict(self.headers)
            if headers:
                h.update(headers)
            if self.cookie_jar:
                h["Cookie"] = "; ".join([f"{k}={v}" for k, v in self.cookie_jar.items()])
            resp = self.fetch(url, headers=h)
            if resp:
                if hasattr(resp, 'cookies'):
                    for k, v in resp.cookies.items():
                        self.cookie_jar[k] = v
                return resp.text
        except Exception as e:
            print(f"[HDV] 请求失败: {url} -> {e}")
        return ""

    def _request_json(self, url, data=None, params=None, referer=None):
        try:
            if params:
                query = urllib.parse.urlencode(params)
                url = url + ("&" if "?" in url else "?") + query
            
            headers = dict(self.headers)
            headers["Accept"] = "application/json, text/plain, */*"
            headers["Referer"] = referer or self.site_url + "/"
            headers["X-Requested-With"] = "XMLHttpRequest"
            
            if self.cookie_jar:
                headers["Cookie"] = "; ".join([f"{k}={v}" for k, v in self.cookie_jar.items()])
            
            body = None
            if data is not None:
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            
            req = urllib.request.Request(url, data=body, headers=headers, 
                                        method="POST" if data is not None else "GET")
            with urllib.request.urlopen(req, timeout=15) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                text = resp.read().decode(charset, errors="ignore")
                return json.loads(text)
        except Exception as e:
            print(f"[HDV] JSON请求失败: {url} -> {e}")
        return {}

    # ================= 分类 =================
    def _fetch_categories(self):
        try:
            html = self._fetch_html(self.site_url + "/")
            soup = BeautifulSoup(html, "html.parser")
            categories = []
            seen = set()
            
            nav_items = soup.select('nav a, .nav a, .menu a, a[href*="/search?category="]')
            for a in nav_items:
                href = a.get("href", "")
                if "/search?category=" in href:
                    parsed = urllib.parse.urlparse(href)
                    query = urllib.parse.parse_qs(parsed.query)
                    name = query.get("category", [""])[0]
                    name = urllib.parse.unquote(name).strip()
                    if not name:
                        name = self._get_text(a)
                    name = re.sub(r"\s+\d+\s*部?$", "", name).strip()
                    if name and name not in seen and len(name) < 30:
                        seen.add(name)
                        categories.append({"type_id": name, "type_name": name})
            
            if categories:
                return categories[:20]
        except Exception as e:
            print(f"[HDV] 获取分类失败: {e}")
        
        return [
            {"type_id": "都市", "type_name": "都市"},
            {"type_id": "逆袭", "type_name": "逆袭"},
            {"type_id": "现代", "type_name": "现代"},
            {"type_id": "打脸虐渣", "type_name": "打脸虐渣"},
            {"type_id": "总裁", "type_name": "总裁"},
            {"type_id": "剧情", "type_name": "剧情"},
            {"type_id": "都市日常", "type_name": "都市日常"},
            {"type_id": "大男主", "type_name": "大男主"},
            {"type_id": "都市脑洞", "type_name": "都市脑洞"},
            {"type_id": "玄幻脑洞", "type_name": "玄幻脑洞"},
        ]

    # ================= 列表解析 =================
    def _parse_cards(self, html):
        soup = BeautifulSoup(html or "", "html.parser")
        video_list = []
        seen = set()

        links = soup.select('a[href*="/drama/"]')
        if not links:
            links = soup.find_all('a', href=re.compile(r'/drama/\d+\.html'))

        for link in links:
            href = link.get("href", "")
            m = re.search(r"/drama/(\d+)\.html", href)
            if not m:
                continue
            vod_id = m.group(1)
            if vod_id in seen:
                continue
            seen.add(vod_id)

            card = link
            for parent in link.parents:
                if parent.name in ("article", "li", "div"):
                    cls = " ".join(parent.get("class", []))
                    if "card" in cls or "item" in cls or parent.name in ("article", "li"):
                        card = parent
                        break

            img = card.select_one("img") or link.select_one("img")
            pic = ""
            title = ""
            if img:
                pic = img.get("src", "") or img.get("data-src", "") or img.get("data-original", "")
                title = img.get("alt", "") or img.get("title", "")
                title = re.sub(r"短剧封面$", "", title).strip()
            
            if not title:
                title_node = card.select_one("h2, h3, h4, .title, .card-title, .name")
                title = self._get_text(title_node)
            if not title:
                title = link.get("title", "") or self._get_text(link)
            title = re.sub(r"\s+", " ", title).strip()
            if not title:
                continue

            pic = self._abs_url(pic)

            text = self._get_text(card)
            remark = ""
            count_match = re.search(r"(\d+)\s*集", text)
            if count_match:
                remark = count_match.group(0)

            video_list.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remark
            })
        return video_list

    def _api_search(self, params):
        data = self._request_json(self.site_url + "/api/search", params=params)
        html = data.get("html", "")
        return data, self._parse_cards(html)

    # ================= 首页 =================
    def homeContent(self, filter=False):
        html = self._fetch_html(self.site_url + "/")
        video_list = self._parse_cards(html)
        if not video_list:
            data, video_list = self._api_search({"offset": 0, "limit": 30, "sort": "latest"})
        return {"class": self.categories, "list": video_list[:30], "filters": {}}

    def homeVideoContent(self):
        return self.homeContent(False)

    # ================= 分类列表 =================
    def categoryContent(self, tid, pg, filter=False, extend={}):
        page = int(pg) if pg else 1
        limit = 24
        offset = (page - 1) * limit
        params = {
            "category": tid,
            "offset": offset,
            "limit": limit,
            "sort": "latest"
        }
        data, video_list = self._api_search(params)
        total = int(data.get("total") or 0)
        pagecount = max(1, (total + limit - 1) // limit) if total else page
        return {
            "list": video_list,
            "page": page,
            "pagecount": pagecount,
            "limit": limit,
            "total": total or len(video_list)
        }

    # ================= 详情页 =================
    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = str(ids[0]).strip()
        m = re.search(r"(\d{6,32})", vod_id)
        if m:
            vod_id = m.group(1)

        url = f"{self.site_url}/drama/{vod_id}.html"
        html = self._fetch_html(url)
        if not html:
            return {"list": []}

        soup = BeautifulSoup(html, "html.parser")
        
        title = ""
        og_title = soup.select_one('meta[property="og:title"], meta[name="twitter:title"]')
        if og_title:
            title = og_title.get("content", "").strip()
        if not title:
            h1 = soup.select_one("h1")
            title = self._get_text(h1)
        title = title or vod_id

        pic = ""
        og_img = soup.select_one('meta[property="og:image"], meta[name="twitter:image"]')
        if og_img:
            pic = og_img.get("content", "")
        if not pic:
            img = soup.select_one("img.cover, img.poster, img")
            if img:
                pic = img.get("src", "") or img.get("data-src", "")
        pic = self._abs_url(pic)

        desc = ""
        meta_desc = soup.select_one('meta[name="description"], meta[property="og:description"]')
        if meta_desc:
            desc = meta_desc.get("content", "").strip()
        if not desc:
            desc_elem = soup.select_one(".desc, .summary, .intro, .synopsis")
            if desc_elem:
                desc = self._get_text(desc_elem)

        # ===== 提取剧集 =====
        episodes = []
        
        # 方法1: 从页面提取播放列表
        ep_links = soup.select('.episode-list a, .playlist a, .episodes a, .episode a')
        if ep_links:
            for a in ep_links:
                name = self._get_text(a)
                href = a.get("href", "")
                if href:
                    if not href.startswith('http'):
                        href = self._abs_url(href)
                    episodes.append(f"{name}${href}")
        
        # 方法2: 从JavaScript提取
        if not episodes:
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string:
                    content = script.string
                    ep_match = re.search(r'episodes?\s*=\s*(\[[^\]]+\])', content, re.DOTALL)
                    if ep_match:
                        try:
                            ep_data = json.loads(ep_match.group(1))
                            for ep in ep_data:
                                name = ep.get('name', f"第{len(episodes)+1}集")
                                url = ep.get('url', '')
                                if url:
                                    episodes.append(f"{name}${url}")
                        except:
                            pass
        
        # 方法3: 生成默认剧集
        if not episodes:
            page_text = self._get_text(soup)
            count_match = re.search(r"(\d+)\s*集", page_text)
            if count_match:
                total = min(int(count_match.group(1)), 500)
                for i in range(1, total + 1):
                    play_url = f"{self.site_url}/player/{vod_id}.html"
                    if i > 1:
                        play_url += f"?episode={i}"
                    episodes.append(f"第{i}集${play_url}")
            else:
                play_url = f"{self.site_url}/player/{vod_id}.html"
                episodes.append(f"正片${play_url}")

        result = [{
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": pic,
            "vod_content": desc,
            "vod_actor": "",
            "vod_director": "",
            "vod_area": "",
            "vod_year": "",
            "vod_class": "",
            "vod_play_from": "HDV",
            "vod_play_url": "#".join(episodes)
        }]
        return {"list": result}

    # ================= 搜索 =================
    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        limit = 24
        offset = (page - 1) * limit
        params = {
            "q": key,
            "offset": offset,
            "limit": limit,
            "sort": "latest"
        }
        data, video_list = self._api_search(params)
        total = int(data.get("total") or 0)
        pagecount = max(1, (total + limit - 1) // limit) if total else page
        return {
            "list": video_list,
            "page": page,
            "pagecount": pagecount,
            "limit": limit,
            "total": total or len(video_list)
        }

    # ================= 播放解析（核心修复） =================
    def playerContent(self, flag, id, vipFlags):
        play_url = str(id or "").strip()
        if not play_url:
            return {"parse": 1, "url": ""}

        # 解析参数
        episode = 1
        drama_id = ""
        
        # 从URL提取drama_id和episode
        m = re.search(r"/player/(\d+)\.html", play_url)
        if m:
            drama_id = m.group(1)
        
        parsed = urllib.parse.urlparse(play_url)
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("episode"):
            try:
                episode = int(query.get("episode", ["1"])[0])
            except:
                pass
        
        if not drama_id:
            m = re.search(r"(\d{6,32})", play_url)
            if m:
                drama_id = m.group(1)

        if not drama_id:
            return {"parse": 1, "url": play_url, "header": self.headers}

        referer = f"{self.site_url}/player/{drama_id}.html"
        if episode > 1:
            referer += f"?episode={episode}"

        # ===== 修复：多线路播放解析 =====
        
        # 1. 先尝试从播放页提取
        html = self._fetch_html(referer)
        if html:
            # 提取iframe
            iframe_match = re.search(r'<iframe[^>]+src="([^"]+)"', html)
            if iframe_match:
                video_url = iframe_match.group(1)
                if not video_url.startswith('http'):
                    video_url = self._abs_url(video_url)
                return {
                    "parse": 0,
                    "url": video_url,
                    "header": {"Referer": referer, "User-Agent": self.headers["User-Agent"]}
                }
            
            # 提取video标签
            video_match = re.search(r'<video[^>]+src="([^"]+)"', html)
            if video_match:
                video_url = video_match.group(1)
                if not video_url.startswith('http'):
                    video_url = self._abs_url(video_url)
                return {
                    "parse": 0,
                    "url": video_url,
                    "header": {"Referer": referer, "User-Agent": self.headers["User-Agent"]}
                }
            
            # 提取m3u8链接
            m3u8_match = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', html)
            if m3u8_match:
                return {
                    "parse": 0,
                    "url": m3u8_match.group(1),
                    "header": {"Referer": referer, "User-Agent": self.headers["User-Agent"]}
                }
            
            # 提取mp4链接
            mp4_match = re.search(r'(https?://[^\s"\']+\.mp4[^\s"\']*)', html)
            if mp4_match:
                return {
                    "parse": 0,
                    "url": mp4_match.group(1),
                    "header": {"Referer": referer, "User-Agent": self.headers["User-Agent"]}
                }

        # 2. 调用API获取播放地址
        api_data = self._request_json(
            self.site_url + "/api/play",
            data={"drama_id": drama_id, "episode": episode},
            referer=referer
        )

        if api_data:
            # 检查直接返回的URL
            if api_data.get("url"):
                video_url = api_data.get("url")
                if video_url.startswith('//'):
                    video_url = 'https:' + video_url
                return {
                    "parse": 0,
                    "url": video_url,
                    "header": {"Referer": referer, "User-Agent": self.headers["User-Agent"]}
                }
            
            if api_data.get("play_url"):
                video_url = api_data.get("play_url")
                if video_url.startswith('//'):
                    video_url = 'https:' + video_url
                return {
                    "parse": 0,
                    "url": video_url,
                    "header": {"Referer": referer, "User-Agent": self.headers["User-Agent"]}
                }
            
            # 处理质量选项
            options = api_data.get("quality_options") or []
            if options:
                # 选择最高画质且可播放的
                best = None
                best_score = -1
                for opt in options:
                    score = int(opt.get("height") or 0)
                    # 优先可播放的
                    if opt.get("playable"):
                        score += 100000
                    # 优先非加密
                    if not opt.get("encrypted"):
                        score += 10000
                    if score > best_score:
                        best_score = score
                        best = opt
                
                if best and best.get("url"):
                    video_url = best.get("url")
                    if video_url.startswith('//'):
                        video_url = 'https:' + video_url
                    if not video_url.startswith('http'):
                        video_url = self._abs_url(video_url)
                    
                    result = {
                        "parse": 0,
                        "url": video_url,
                        "header": {
                            "Referer": referer,
                            "User-Agent": self.headers["User-Agent"],
                            "Origin": self.site_url
                        }
                    }
                    
                    # 处理DRM
                    if best.get("encrypted"):
                        kid = best.get("kid", "")
                        key = best.get("decryption_key", "")
                        if kid and key:
                            result["drm_type"] = "clearkey"
                            result["drm"] = {
                                "clearkey": {
                                    "keyId": kid,
                                    "key": key
                                }
                            }
                            result["note"] = "ClearKey加密，需播放器支持"
                        else:
                            # 加密但没有key，返回播放页让用户手动解析
                            result["parse"] = 1
                            result["url"] = referer
                            result["header"] = {"Referer": self.site_url, "User-Agent": self.headers["User-Agent"]}
                    else:
                        # 非加密源
                        result["parse"] = 0
                    
                    return result

        # 3. 尝试从页面JavaScript提取播放数据
        if html:
            # 查找播放器配置
            player_config = re.search(r'player\s*=\s*({[^;]+})', html, re.DOTALL)
            if player_config:
                try:
                    config = json.loads(player_config.group(1))
                    if config.get('url'):
                        return {
                            "parse": 0,
                            "url": config.get('url'),
                            "header": {"Referer": referer, "User-Agent": self.headers["User-Agent"]}
                        }
                    if config.get('src'):
                        return {
                            "parse": 0,
                            "url": config.get('src'),
                            "header": {"Referer": referer, "User-Agent": self.headers["User-Agent"]}
                        }
                except:
                    pass
            
            # 查找视频源
            video_src = re.search(r'src\s*[:=]\s*["\']([^"\']+\.(?:m3u8|mp4|flv)[^"\']*)["\']', html, re.IGNORECASE)
            if video_src:
                video_url = video_src.group(1)
                if video_url.startswith('//'):
                    video_url = 'https:' + video_url
                return {
                    "parse": 0,
                    "url": video_url,
                    "header": {"Referer": referer, "User-Agent": self.headers["User-Agent"]}
                }

        # 4. 降级：返回播放页，让TVBox内置播放器解析
        return {
            "parse": 1,
            "url": referer,
            "header": {
                "Referer": self.site_url,
                "User-Agent": self.headers["User-Agent"]
            }
        }

    # ================= 本地代理 =================
    def localProxy(self, param):
        url = param.get('url', '')
        if not url:
            return [404, {"Content-Type": "text/plain"}, b"Missing url"]
        
        try:
            import requests
            resp = requests.get(url, headers={
                'User-Agent': self.headers["User-Agent"],
                'Referer': self.site_url,
            }, timeout=15)
            
            if '.m3u8' in url.lower():
                content = resp.text
                lines = content.split('\n')
                filtered = []
                for line in lines:
                    if 'ad' in line.lower() or '广告' in line or 'union' in line.lower():
                        continue
                    filtered.append(line)
                content = '\n'.join(filtered)
                return [200, {"Content-Type": "application/vnd.apple.mpegurl"}, content.encode('utf-8')]
            
            return [200, {"Content-Type": resp.headers.get('Content-Type', 'application/octet-stream')}, resp.content]
        except Exception as e:
            return [500, {"Content-Type": "text/plain"}, str(e).encode('utf-8')]