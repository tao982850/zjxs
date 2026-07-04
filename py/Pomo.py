# -*- coding: utf-8 -*-
import re, json, urllib.parse
from bs4 import BeautifulSoup
from base.spider import Spider as BaseSpider

class Spider(BaseSpider):
    def init(self, extend=""):
        self.host = "https://pomo.mom/"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
            "Referer": self.host,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

    def getName(self):
        return "Pomo4K"

    def homeContent(self, filter):
        return {
            "class": [
                {"type_id": "huayurm", "type_name": "华语热门"},
                {"type_id": "jiating", "type_name": "家庭影院"},
                {"type_id": "donghuadadiany", "type_name": "动画大电影"},
                {"type_id": "lengmenjiapian", "type_name": "冷门佳片"},
                {"type_id": "paihangbang", "type_name": "TOP250"},
                {"type_id": "sort/12", "type_name": "蓝光原盘"},
                {"type_id": "dianshiju", "type_name": "剧集"},
            ],
            "filters": {}
        }

    # 修复首页推荐空白，补充基础推荐结构
    def homeVideoContent(self):
        try:
            html = self._fetch("/")
            items = self._parse_list(html)
            return {"list": items[:12]}
        except:
            return {"list": []}

    # 统一请求封装，增加URL标准化、超时容错
    def _fetch(self, url):
        try:
            if not url.startswith("http"):
                url = urllib.parse.urljoin(self.host, url)
            rsp = self.fetch(url, headers=self.headers, timeout=10)
            if rsp and rsp.status_code == 200:
                return rsp.text
            return ""
        except Exception as e:
            return ""

    # 核心修复：过滤无效链接，严格匹配视频详情页数字ID，去重空图片/标题
    def _parse_list(self, html):
        items = []
        soup = BeautifulSoup(html, "html.parser")
        seen_vid = set()
        # 缩小范围：仅匹配内容卡片内链接，排除导航栏
        cards = soup.select("div.card a, .video-item a")
        if not cards:
            cards = soup.select('a[href]')
        for card in cards:
            href = card.get("href", "").strip()
            if not href or href.startswith("#") or href.startswith("javascript"):
                continue
            # 双重正则兼容站点两种链接格式，精准匹配数字ID
            m = re.search(r'pomo\.mom/(\d+)$', href)
            if not m:
                m = re.search(r'/(\d+)$', href)
            if not m:
                continue
            vid = m.group(1)
            if vid in seen_vid:
                continue
            seen_vid.add(vid)
            img = card.select_one("img")
            if not img:
                continue
            title = img.get("alt", "").strip()
            pic = img.get("data-src", "").strip() or img.get("src", "").strip()
            if not title or not pic:
                continue
            # 提取标签备注
            remarks = ""
            tag_el = card.select_one(".tag, .badge, .label")
            if tag_el:
                remarks = tag_el.get_text(strip=True)
            items.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks,
            })
        return items

    # 修复分页错乱、total固定9999、页码边界异常
    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg) if pg and str(pg).isdigit() else 1
            if pg < 1:
                pg = 1
            url = f"/{tid}"
            if pg > 1:
                url = f"/{tid}/page/{pg}"
            html = self._fetch(url)
            items = self._parse_list(html)
            # 自动解析最大页码
            soup = BeautifulSoup(html, "html.parser")
            pages = []
            for a in soup.select("a[href*='page/']"):
                pm = re.search(r'page/(\d+)', a.get("href", ""))
                if pm:
                    pages.append(int(pm.group(1)))
            pagecount = max(pages) if pages else 1
            limit = 24
            # 动态修正total，不再写死9999
            total = pagecount * limit
            return {
                "page": pg,
                "pagecount": pagecount,
                "limit": limit,
                "total": total,
                "list": items
            }
        except Exception as e:
            return {"page": 1, "pagecount": 1, "limit": 24, "total": 0, "list": []}

    # 详情页增强容错，字段补全，适配TVBOX标准字段
    def detailContent(self, ids):
        try:
            if isinstance(ids, list):
                ids = ids[0]
            html = self._fetch(f"/{ids}")
            soup = BeautifulSoup(html, "html.parser")
            # 片名双重兜底
            title_el = soup.select_one("h2.x-dbjs-title") or soup.select_one("title")
            title = title_el.get_text(strip=True) if title_el else f"视频{ids}"
            # 海报
            img_el = soup.select_one("img.x-dbjs-poster-img, .x-dbjs-poster img, .poster img")
            pic = img_el.get("src", "").strip() if img_el else ""
            # 简介
            desc_el = soup.select_one(".x-dbjs-card .x-dbjs-content, .x-dbjs-card p, .desc")
            desc = desc_el.get_text(strip=True) if desc_el else "暂无简介"
            year = director = actor = ""
            # 解析元数据
            meta_rows = soup.select(".meta-row, .meta-info")
            for meta_row in meta_rows:
                text = meta_row.get_text(" ", strip=True)
                if "导演" in text:
                    director = re.sub(r'导演[:：]', "", text).strip()
                elif "主演" in text or "演员" in text:
                    actor = re.sub(r'(主演|演员)[:：]', "", text).strip()
                elif "上映" in text or "年份" in text or "时间" in text:
                    ym = re.search(r'(\d{4})', text)
                    if ym:
                        year = ym.group(1)
            # 修复播放线路标识，兼容多版本TVBOX
            play_url = f"Pomo在线${ids}"
            return {
                "list": [{
                    "vod_id": ids,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_year": year,
                    "vod_director": director,
                    "vod_actor": actor,
                    "vod_content": desc,
                    "vod_play_from": "Pomo在线",
                    "vod_play_url": play_url,
                }]
            }
        except Exception as e:
            return {"list": []}

    # 重点修复：m3u8正则匹配、转义斜杠、磁力解析、请求头完善
    def playerContent(self, flag, id, vipFlags):
        try:
            vid = id.split("$")[0] if "$" in id else id
            play_page = f"/?plugin=plyr_player&gid={vid}"
            html = self._fetch(play_page)
            real_url = ""
            # 修复正则转义斜杠匹配逻辑，兼容两种转义格式 \/ 和 /
            pattern1 = r'route1Data\s*=\s*\["([^"]*?)\$(https?[\\/]+[^"]+)"\]'
            m1 = re.search(pattern1, html)
            if m1:
                raw_link = m1.group(2)
                real_url = raw_link.replace(r'\/', '/').replace(r'\\', '')
            # 兜底匹配route1Data单数组
            if not real_url:
                m2 = re.search(r'route1Data\s*=\s*\["([^"]+)"\]', html)
                if m2:
                    raw = m2.group(1)
                    split_arr = raw.split("$", 1)
                    src = split_arr[-1]
                    src = src.replace(r'\/', '/').replace(r'\\', '')
                    # 磁力链走解析API
                    if src.startswith("magnet:"):
                        api_encode = urllib.parse.quote(src)
                        api_url = f"/content/plugins/plyr_player/api.php?type=parse&url={api_encode}"
                        api_text = self._fetch(api_url)
                        if api_text:
                            api_data = json.loads(api_text)
                            if api_data.get("url"):
                                real_url = api_data["url"]
                            elif api_data.get("code") == 200 and api_data.get("data"):
                                real_url = api_data["data"]
                    elif src.startswith("http"):
                        real_url = src
            # 校验链接有效性
            if real_url and (real_url.startswith("http") or real_url.startswith("https")):
                return {
                    "parse": 0,
                    "url": real_url,
                    "header": self.headers
                }
            return {"parse": 0, "url": ""}
        except Exception as e:
            return {"parse": 0, "url": ""}

    # 修复搜索无分页、列表过滤逻辑复用
    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg) if pg.isdigit() else 1
            wd = urllib.parse.quote(key)
            search_url = f"/?s={wd}&page={pg}"
            html = self._fetch(search_url)
            items = self._parse_list(html)
            # 解析搜索分页
            soup = BeautifulSoup(html, "html.parser")
            pages = []
            for a in soup.select("a[href*='page=']"):
                pm = re.search(r'page=(\d+)', a.get("href", ""))
                if pm:
                    pages.append(int(pm.group(1)))
            pc = max(pages) if pages else 1
            return {
                "list": items,
                "page": pg,
                "pagecount": pc,
                "limit": 24
            }
        except Exception as e:
            return {"list": []}

    def localProxy(self, param=''):
        return {}

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False