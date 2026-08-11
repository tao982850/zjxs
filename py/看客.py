# coding=utf-8
"""
目标站: 看客 (kk123.seesee.sbs / www.seesee.sbs)
模板: 影视聚合搜索 / MacCMS v10 爬虫
站点类型: 影视聚合 (电影/剧集/动漫/综艺/B站/Netflix)
核心逻辑: 解析首页/分类/搜索/详情/播放页 HTML，从播放页 JS 变量 player_aaaa 中提取真实播放地址
支持: 首页、分类、搜索、详情、播放
"""
import re
import sys
import json
import urllib.parse

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    def init(self, extend=""):
        # 请根据实际可用域名自行调整
        self.site_url = "https://kk123.seesee.sbs"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.site_url + "/",
        }
        self.default_pic = "https://pic.rmb.bdstatic.com/bjh/user/default.png"

    # ========== 工具方法 ==========
    def _fix_url(self, url):
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            return "https:" + url
        if not url.startswith("http"):
            return urllib.parse.urljoin(self.site_url, url)
        return url

    def _extract_vod_list(self, html):
        """从 HTML 中提取视频列表 (vod-item 卡片式)"""
        videos = []
        seen = set()

        # 匹配每个 vod-item 块
        items = re.findall(
            r'<div class="vod-item">\s*<a href="/vodplay/(\d+)-(\d+)-(\d+)\.html" title="([^"]*)">(.*?)</a>\s*</div>',
            html, re.DOTALL
        )
        for vod_id, sid, nid, title, block in items:
            if vod_id in seen:
                continue
            seen.add(vod_id)

            # 提取图片
            pic = ""
            for attr in ['src', 'data-original', 'data-src']:
                m = re.search(r'<img[^>]*' + attr + r'="([^"]*)"', block)
                if m:
                    pic = m.group(1).strip()
                    break

            # 提取备注 (remarks)
            remark = ""
            m = re.search(r'<span class="remarks">([^<]*)</span>', block)
            if m:
                remark = m.group(1).strip()

            # 提取副标题 (年份/地区)
            subtitle = ""
            m = re.search(r'<p class="subtitle">([^<]*)</p>', block)
            if m:
                subtitle = m.group(1).strip()

            videos.append({
                "vod_id": vod_id,
                "vod_name": title.strip(),
                "vod_pic": self._fix_url(pic) if pic else self.default_pic,
                "vod_remarks": remark or subtitle
            })

        return videos

    def _extract_pagination(self, html):
        """从 mac_pages 中提取分页信息"""
        page = 1
        pagecount = 1

        # 当前页
        m = re.search(r'<span class="page_link page_current">(\d+)</span>', html)
        if m:
            page = int(m.group(1))

        # 搜索分页: /vodsearch/keyword----------N---.html
        pages = re.findall(
            r'<a class="page_link" href="[^"]*----------(\d+)---\.html"',
            html
        )
        # 分类分页: /vodtype/20-N.html
        if not pages:
            pages = re.findall(
                r'<a class="page_link" href="/vodtype/\d+-(\d+)\.html"',
                html
            )

        if pages:
            pagecount = max(int(p) for p in pages)

        return page, pagecount

    # ========== 首页 ==========
    def homeContent(self, filter):
        categories = [
            {"type_id": "20", "type_name": "电影"},
            {"type_id": "37", "type_name": "剧集"},
            {"type_id": "43", "type_name": "动漫"},
            {"type_id": "45", "type_name": "综艺"},
            {"type_id": "47", "type_name": "B站"},
            {"type_id": "52", "type_name": "Netflix"},
        ]
        resp = self.fetch(self.site_url + "/", headers=self.headers)
        videos = []
        if resp:
            videos = self._extract_vod_list(resp.text)
        return {"class": categories, "list": videos[:30], "filters": {}}

    def homeVideoContent(self):
        return self.homeContent(False)

    # ========== 分类 ==========
    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        limit = 30

        if page == 1:
            url = f"{self.site_url}/vodtype/{tid}.html"
        else:
            url = f"{self.site_url}/vodtype/{tid}-{page}.html"

        resp = self.fetch(url, headers=self.headers)
        videos = []
        pagecount = page
        total = page * limit

        if resp:
            videos = self._extract_vod_list(resp.text)
            page, pagecount = self._extract_pagination(resp.text)
            if pagecount < page:
                pagecount = page
            total = pagecount * limit

        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": limit,
            "total": total
        }

    # ========== 搜索 ==========
    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        limit = 30
        encoded = urllib.parse.quote(key)

        url = f"{self.site_url}/vodsearch/{encoded}----------{page}---.html"

        resp = self.fetch(url, headers=self.headers)
        videos = []
        pagecount = page
        total = page * limit

        if resp:
            videos = self._extract_vod_list(resp.text)
            page, pagecount = self._extract_pagination(resp.text)
            if pagecount < page:
                pagecount = page
            total = pagecount * limit

        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": limit,
            "total": total
        }

    # ========== 详情 ==========
    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = ids[0]

        # 尝试获取详情页
        detail_url = f"{self.site_url}/voddetail/{vod_id}.html"
        resp = self.fetch(detail_url, headers=self.headers)
        detail_html = resp.text if resp else ""

        # 同时获取播放页（用于提取选集，且作为详情信息兜底）
        play_url = f"{self.site_url}/vodplay/{vod_id}-1-1.html"
        play_resp = self.fetch(play_url, headers=self.headers)
        play_html = play_resp.text if play_resp else ""

        # 优先使用详情页，否则使用播放页
        source_html = detail_html if detail_html else play_html
        if not source_html:
            return {"list": []}

        # 标题
        name = ""
        m = re.search(r'<h1[^>]*>([^<]*)</h1>', source_html)
        if m:
            name = m.group(1).strip()
        # 从播放页标题提取 (格式: "影片名 - 集数")
        if not name and play_html:
            m = re.search(r'<h1 class="play-title">([^<]*)</h1>', play_html)
            if m:
                name = m.group(1).split(" - ")[0].strip()

        # 海报
        pic = self.default_pic
        m = re.search(r'<img[^>]*class="[^"]*lazy[^"]*"[^>]*data-original="([^"]*)"', source_html)
        if not m:
            m = re.search(r'<div[^>]*class="vod-pic"[^>]*>.*?<img[^>]*src="([^"]*)"', source_html, re.DOTALL)
        if m:
            pic = self._fix_url(m.group(1))

        # 简介
        content = ""
        m = re.search(r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>', source_html, re.DOTALL)
        if m:
            content = re.sub(r'<[^>]+>', '', m.group(1)).strip()

        # 年份 / 地区 / 导演 / 演员 (MacCMS 常见结构)
        year = ""
        area = ""
        director = ""
        actor = ""

        for block in re.findall(r'<div[^>]*class="module-info-item"[^>]*>(.*?)</div>', source_html, re.DOTALL):
            if '导演' in block or '導演' in block:
                dirs = re.findall(r'<a[^>]*>([^<]*)</a>', block)
                director = ' / '.join([d.strip() for d in dirs if d.strip()])
            elif '主演' in block:
                acts = re.findall(r'<a[^>]*>([^<]*)</a>', block)
                actor = ' / '.join([a.strip() for a in acts if a.strip()])
            elif '年份' in block or '年代' in block:
                m = re.search(r'(\d{4})', block)
                if m:
                    year = m.group(1)
            elif '地区' in block:
                m = re.search(r'>([^<]+)</a>', block)
                if m:
                    area = m.group(1).strip()

        # 播放源与选集 (从播放页提取)
        play_from = []
        play_url = []

        if play_html:
            # 提取源名称
            source_names = re.findall(
                r'<span class="source-tab-item[^"]*" data-target="[^"]*">([^<]*)</span>',
                play_html
            )

            # 提取各 source-pane 的选集
            pane_blocks = re.findall(
                r'<div class="source-pane[^"]*" id="([^"]*)">\s*<div class="url-grid-play">(.*?)</div>\s*</div>',
                play_html, re.DOTALL
            )

            # 建立 id -> name 映射
            source_map = {}
            for idx, name in enumerate(source_names):
                source_map[f"playlist-{idx+1}"] = name.strip()

            for pane_id, pane_html in pane_blocks:
                source_name = source_map.get(pane_id, pane_id)
                episodes = []

                # 提取选集链接
                eps = re.findall(
                    r'<a href="(/vodplay/\d+-\d+-\d+\.html)" class="play-btn-item[^"]*" title="([^"]*)"',
                    pane_html
                )
                for ep_link, ep_title in eps:
                    play_link = self._fix_url(ep_link)
                    episodes.append(f"{ep_title.strip()}${play_link}")

                if episodes:
                    play_from.append(source_name)
                    play_url.append("#".join(episodes))

        # 兜底：若未提取到任何播放源，把播放页本身当作单集返回
        if not play_from:
            play_from = ["默认线路"]
            play_url = [f"播放${play_url}"]

        result = [{
            "vod_id": vod_id,
            "vod_name": name or vod_id,
            "vod_pic": pic,
            "vod_content": content,
            "vod_actor": actor,
            "vod_director": director,
            "vod_year": year,
            "vod_area": area,
            "vod_play_from": '$$$'.join(play_from),
            "vod_play_url": '$$$'.join(play_url)
        }]
        return {"list": result}

    # ========== 播放 ==========
    def playerContent(self, flag, id, vipFlags):
        play_page_url = id
        if "$" in id:
            play_page_url = id.split("$")[-1]
        play_page_url = self._fix_url(play_page_url)

        # 若已经是直链，直接返回
        if '.m3u8' in play_page_url or '.mp4' in play_page_url:
            return {
                "parse": 0,
                "url": play_page_url,
                "header": {
                    'User-Agent': self.headers['User-Agent'],
                    'Referer': self.site_url + "/",
                }
            }

        try:
            resp = self.fetch(play_page_url, headers=self.headers)
            if not resp:
                raise Exception("empty response")
            html = resp.text

            # 核心：提取 player_aaaa 并解析真实播放地址
            m = re.search(r'var\s+player_aaaa\s*=\s*({.*?});', html, re.DOTALL)
            if m:
                player_data = json.loads(m.group(1))
                real_url = player_data.get('url', '')
                from_src = player_data.get('from', '')
                encrypt = player_data.get('encrypt', 0)

                if real_url:
                    # 解码 URL (可能被转义)
                    real_url = real_url.replace('\\/', '/')
                    real_url = urllib.parse.unquote(real_url)

                    # 如果是 m3u8/mp4 直链
                    if '.m3u8' in real_url or '.mp4' in real_url:
                        return {
                            "parse": 0,
                            "url": real_url,
                            "header": {
                                'User-Agent': self.headers['User-Agent'],
                                'Referer': self.site_url + "/",
                            }
                        }

                    # 外部 iframe 嵌入 (如 bilibili, youku, iqiyi 等)
                    if real_url.startswith('http'):
                        return {
                            "parse": 1,
                            "url": real_url,
                            "header": {
                                'User-Agent': self.headers['User-Agent'],
                                'Referer': self.site_url + "/",
                            }
                        }

            # 兜底1：从页面中直接搜索 m3u8 链接
            m = re.search(r'(https?://[^\s"\']+\.m3u8)', html)
            if m:
                return {
                    "parse": 0,
                    "url": m.group(1),
                    "header": {
                        'User-Agent': self.headers['User-Agent'],
                        'Referer': self.site_url + "/",
                    }
                }

            # 兜底2：从页面中直接搜索 mp4 链接
            m = re.search(r'(https?://[^\s"\']+\.mp4)', html)
            if m:
                return {
                    "parse": 0,
                    "url": m.group(1),
                    "header": {
                        'User-Agent': self.headers['User-Agent'],
                        'Referer': self.site_url + "/",
                    }
                }

        except Exception:
            pass

        # 全部失败则交给 webview 嗅探
        return {
            "parse": 1,
            "url": play_page_url,
            "header": self.headers
        }
