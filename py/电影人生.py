# -*- coding: utf-8 -*-
"""
电影人生 Python Spider（dyvip5.cc / dyrs.me / dyrs.mov 多域名自动切换）
兼容 FongMi/TV (T3) 和 WebHomeTV/PeekPro (T4)

站点结构（实测 2026-08-21）：
- 自定义站点（非苹果CMS），tailwind 模板，搜索/分类/详情均静态 HTML
- 内容域名: https://dyvip5.cc（主用）
  dyrs.me / dyrs.mov 目前只提供发布页（跳转 dyrshd.net），探测时自动跳过，
  以后这两个域名上线内容站可直接生效
- 分类页: /dianying.html  /dianshiju.html  /zongyi.html  /dongman.html  /duanju.html
  分页 ?page=N（0 基），子类筛选 ?class=类型
- 详情页: /tv/{hash}-{id}.html 或 /movie/{hash}-{id}.html
  线路 tab: ?origin=线路名（如 超级线路/王者TV加速/lzm3u8/1080zyk 等）
  集数链接: /tv/{hash}/{id}.html?origin=线路&p=N （data-origin / data-title 属性）
- 播放链: 集数页 <link rel="preload" href="/api/m3u8?origin=线路&url=hash">
  该 API 直接返回 m3u8（多数线路为完整 VOD 列表；个别线路为多码率主列表，
  其 /api/m3u8?id=hash 子地址偶发 500，属源站问题）
- 搜索: /s.html?name=关键词 （卡片结构与分类页一致）
- 卡片: <a href="...html" title="标题"><img data-src="/img/id/{hash}.jpg"> + 角标(1080p等)
"""
import sys
import json
import re
import time
from urllib.parse import quote, unquote

sys.path.append('..')

try:
    from base.spider import Spider
except ImportError:
    import requests as rq

    class Spider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = rq.get(url, headers=headers, timeout=30, **kw)
            r.encoding = 'utf-8'
            return r


class Spider(Spider):

    # ===== 站点配置 =====
    # 多域名：按顺序探测，只认带内容指纹的域名（发布页自动跳过）
    DOMAINS = [
        "https://dyvip5.cc",
        "https://dyrs.me",
        "https://dyrs.mov",
    ]

    # 父分类（首页导航栏）
    CLASSES = [
        {'type_name': '电影', 'type_id': 'dianying'},
        {'type_name': '电视剧', 'type_id': 'dianshiju'},
        {'type_name': '综艺', 'type_id': 'zongyi'},
        {'type_name': '动漫', 'type_id': 'dongman'},
        {'type_name': '短剧', 'type_id': 'duanju'},
    ]

    # 子分类筛选器（始终返回，不依赖 filter 参数）
    FILTERS = {
        'dianying': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '剧情', 'v': '剧情'}, {'n': '喜剧', 'v': '喜剧'},
                {'n': '动作', 'v': '动作'}, {'n': '爱情', 'v': '爱情'},
                {'n': '惊悚', 'v': '惊悚'}, {'n': '犯罪', 'v': '犯罪'},
                {'n': '恐怖', 'v': '恐怖'}, {'n': '悬疑', 'v': '悬疑'},
                {'n': '冒险', 'v': '冒险'}, {'n': '奇幻', 'v': '奇幻'},
                {'n': '科幻', 'v': '科幻'}, {'n': '院线', 'v': '院线'},
                {'n': '家庭', 'v': '家庭'}, {'n': '历史', 'v': '历史'},
                {'n': '战争', 'v': '战争'}, {'n': '纪录片', 'v': '纪录片'},
                {'n': '古装', 'v': '古装'},
            ]},
        ],
        'dianshiju': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '剧情', 'v': '剧情'}, {'n': '喜剧', 'v': '喜剧'},
                {'n': '爱情', 'v': '爱情'}, {'n': '犯罪', 'v': '犯罪'},
                {'n': '悬疑', 'v': '悬疑'}, {'n': '家庭', 'v': '家庭'},
                {'n': '古装', 'v': '古装'}, {'n': '惊悚', 'v': '惊悚'},
                {'n': '动作', 'v': '动作'}, {'n': '奇幻', 'v': '奇幻'},
                {'n': '科幻', 'v': '科幻'}, {'n': '都市', 'v': '都市'},
                {'n': '历史', 'v': '历史'}, {'n': '战争', 'v': '战争'},
                {'n': '冒险', 'v': '冒险'}, {'n': '武侠', 'v': '武侠'},
                {'n': '恐怖', 'v': '恐怖'},
            ]},
        ],
        'zongyi': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '真人秀', 'v': '真人秀'}, {'n': '脱口秀', 'v': '脱口秀'},
                {'n': '国产综艺', 'v': '国产综艺'}, {'n': '喜剧', 'v': '喜剧'},
                {'n': '晚会', 'v': '晚会'}, {'n': '综艺', 'v': '综艺'},
                {'n': '音乐', 'v': '音乐'}, {'n': '纪录', 'v': '纪录'},
                {'n': '游戏', 'v': '游戏'}, {'n': '生活', 'v': '生活'},
                {'n': '港台综艺', 'v': '港台综艺'}, {'n': '日韩综艺', 'v': '日韩综艺'},
                {'n': '剧情', 'v': '剧情'}, {'n': '文化', 'v': '文化'},
                {'n': '相声', 'v': '相声'}, {'n': '情感', 'v': '情感'},
                {'n': '悬疑', 'v': '悬疑'},
            ]},
        ],
        'dongman': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '动画', 'v': '动画'}, {'n': '冒险', 'v': '冒险'},
                {'n': '喜剧', 'v': '喜剧'}, {'n': '奇幻', 'v': '奇幻'},
                {'n': '剧情', 'v': '剧情'}, {'n': '科幻', 'v': '科幻'},
                {'n': '动作', 'v': '动作'}, {'n': '儿童', 'v': '儿童'},
                {'n': '悬疑', 'v': '悬疑'}, {'n': '都市', 'v': '都市'},
                {'n': '家庭', 'v': '家庭'}, {'n': '国漫', 'v': '国漫'},
                {'n': '日常', 'v': '日常'}, {'n': '爱情', 'v': '爱情'},
                {'n': '玄幻', 'v': '玄幻'}, {'n': '日漫', 'v': '日漫'},
                {'n': '音乐', 'v': '音乐'},
            ]},
        ],
        'duanju': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': 'AI漫剧', 'v': 'AI漫剧'}, {'n': '短剧', 'v': '短剧'},
                {'n': '剧情', 'v': '剧情'}, {'n': '爱情', 'v': '爱情'},
                {'n': '爽文', 'v': '爽文'}, {'n': '古装', 'v': '古装'},
                {'n': '短片', 'v': '短片'}, {'n': '悬疑', 'v': '悬疑'},
                {'n': '喜剧', 'v': '喜剧'}, {'n': '奇幻', 'v': '奇幻'},
                {'n': '都市', 'v': '都市'}, {'n': '玄幻', 'v': '玄幻'},
                {'n': '犯罪', 'v': '犯罪'}, {'n': '家庭', 'v': '家庭'},
                {'n': '穿越', 'v': '穿越'}, {'n': '惊悚', 'v': '惊悚'},
                {'n': '武侠', 'v': '武侠'},
            ]},
        ],
    }

    def init(self, extend=""):
        """初始化"""
        if isinstance(extend, list):
            self.extend = ''
        else:
            self.extend = extend or ''
        self.host = ''
        self.header = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        self._probe_domain()
        self._home_cache = []
        self._home_cache_time = 0
        self._detail_cache = {}
        self._detail_cache_time = 0

    # ========== 工具方法 ==========

    def _probe_domain(self):
        """多域名探测：找到带内容指纹的可用域名"""
        for host in self.DOMAINS:
            try:
                headers = dict(self.header)
                headers['Referer'] = host + '/'
                rsp = self.fetch(host + '/dianying.html', headers=headers, timeout=15)
                try:
                    rsp.encoding = 'utf-8'
                except Exception:
                    pass
                html = rsp.text or ''
                # 内容指纹：影片卡片链接（发布页没有）
                if re.search(r'href="/(?:movie|tv)/[0-9a-f]+-\d+\.html"', html):
                    self.host = host
                    self.header['Referer'] = host + '/'
                    return
            except Exception:
                continue
        # 全部探测失败时保底用第一个，后续请求失败会重新探测
        self.host = self.DOMAINS[0]
        self.header['Referer'] = self.host + '/'

    def _txt(self, url, referer=None, timeout=30, retry_host=True):
        """带异常兜底的 HTTP 请求，返回文本；失败时重新探测域名重试一次"""
        headers = dict(self.header)
        if referer:
            headers['Referer'] = referer
        try:
            rsp = self.fetch(url, headers=headers, timeout=timeout)
            try:
                rsp.encoding = 'utf-8'
            except Exception:
                pass
            return rsp.text
        except Exception:
            if retry_host:
                # 可能是当前域名挂了，重新探测后用新域名重试
                try:
                    old_host = self.host
                    self._probe_domain()
                    if self.host != old_host:
                        new_url = re.sub(r'^https?://[^/]+', self.host, url)
                        return self._txt(new_url, referer=referer,
                                         timeout=timeout, retry_host=False)
                except Exception:
                    pass
            return ""

    def _url(self, path):
        """URL 拼接"""
        if not path:
            return ""
        if path.startswith("http"):
            return path
        return self.host + path if path.startswith("/") else self.host + "/" + path

    def _match(self, pattern, text, default=""):
        """正则匹配第一个分组"""
        m = re.search(pattern, text, re.S)
        return m.group(1).strip() if m else default

    def _strip_tags(self, html):
        """去除 HTML 标签"""
        return re.sub(r'<[^>]+>', '', html).strip()

    # ========== 卡片解析 ==========

    def _parse_cards(self, html):
        """解析影片卡片（分类页/搜索页/首页通用结构）"""
        videos = []
        if not html:
            return videos
        # 卡片: <a href="/movie|tv/hash-id.html" ... title="标题" ...> ... </a>
        for m in re.finditer(
                r'<a href="(/(?:movie|tv)/[0-9a-f]+-\d+\.html)"[^>]*title="([^"]+)"[^>]*>(.*?)</a>',
                html, re.S):
            href, title, inner = m.group(1), m.group(2).strip(), m.group(3)
            # 封面: <img data-src="...">（懒加载），退化用 og:image 同源规则 /img/id/{hash}.jpg
            pic = self._match(r'<img[^>]*data-src="([^"]+)"', inner)
            if not pic:
                hm = re.search(r'/([0-9a-f]+)-\d+\.html', href)
                if hm:
                    pic = '/img/id/%s.jpg' % hm.group(1)
            pic = self._url(pic)
            # 角标: 卡片内第一个 absolute top-2 right-2 的 div（如 1080p / 更新至XX集）
            remark = self._strip_tags(
                self._match(r'<div class="absolute top-2 right-2[^"]*">(.*?)</div>', inner))
            if not title:
                continue
            videos.append({
                'vod_id': href,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': remark,
            })
        # 去重（同一页面可能有推荐位重复）
        seen = set()
        result = []
        for v in videos:
            if v['vod_id'] not in seen:
                seen.add(v['vod_id'])
                result.append(v)
        return result

    def _parse_pagecount(self, html, cur_page):
        """从分页链接提取总页数（?page=N 或 &page=N 均为 0 基，pagecount = N+1）

        注意: 带筛选时链接形如 /dianying.html?class=剧情&page=1580，
        page 参数前面是 & 而不是 ?，两种都要匹配
        """
        pages = [int(x) for x in re.findall(r'(?:[?&]|&amp;)page=(\d+)', html or '')]
        if pages:
            return max(pages) + 1
        return cur_page

    # ========== 首页 ==========

    def homeContent(self, filter):
        """首页分类 + 筛选器（始终返回 filters）"""
        return {
            'class': self.CLASSES,
            'filters': self.FILTERS,
        }

    def homeVideoContent(self):
        """首页精选内容（带缓存）"""
        now = int(time.time())
        if self._home_cache and now - self._home_cache_time < 300:
            return {"list": self._home_cache}

        html = self._txt(self.host + '/', timeout=30)
        videos = self._parse_cards(html)
        if videos:
            self._home_cache = videos[:60]
            self._home_cache_time = now
        return {"list": self._home_cache}

    # ========== 分类 ==========

    def categoryContent(self, tid, pg, filter, extend):
        """分类列表"""
        try:
            page = int(pg) if str(pg).isdigit() else 1
        except Exception:
            page = 1
        # 站点分页为 0 基
        site_page = max(page - 1, 0)

        # extend 兼容 str / dict
        ext = extend if isinstance(extend, dict) else {}
        cls = ext.get('class', '') or ''

        url = "%s/%s.html?page=%d" % (self.host, tid, site_page)
        if cls:
            url += "&class=" + quote(cls)

        html = self._txt(url, timeout=30)
        videos = self._parse_cards(html)
        pagecount = self._parse_pagecount(html, page)

        return {
            'list': videos,
            'page': page,
            'pagecount': pagecount,
            'limit': 24,
            'total': pagecount * 24,
        }

    # ========== 详情 ==========

    def _parse_origin_tabs(self, html, detail_path):
        """从详情页提取线路 tab 名"""
        origins = []
        pat = r'href="' + re.escape(detail_path) + r'\?origin=([^"&]+)"'
        for m in re.finditer(pat, html):
            name = unquote(m.group(1)).strip()
            if name and name not in origins:
                origins.append(name)
        return origins

    def _beautify_title(self, title):
        """集名美化：源站资源标识(1080p_4.65_webrip 等)转可读画质，中文名保留"""
        t = (title or '').strip()
        if not t:
            return t
        low = t.lower()
        # 含中文的集名/备注直接保留（第01集、TC中字 等）
        if re.search(r'[\u4e00-\u9fff]', t):
            return t
        # 纯数字页码
        if re.fullmatch(r'\d+', t):
            return t
        # 资源标识类：提取画质关键词
        if re.search(r'\b4k\b|\buhd\b', low):
            return '4K'
        if '1080' in low:
            return '高清1080P'
        if '720' in low:
            return '高清720P'
        if re.search(r'\bhd\b', low):
            return 'HD'
        if re.search(r'\b(tc|ts|hdts)\b', low):
            return 'TC'
        # 其他纯英文/数字资源串统一显示"高清"
        if re.fullmatch(r'[a-z0-9_.\- ]+', low):
            return '高清'
        return t

    def _parse_episodes(self, html, hash_id):
        """从详情页提取当前线路的集数列表 [(集名, 播放URL), ...]

        兼容站点两种模板：
        A: <a ... data-title="第01集" ...>（部分剧集）
        B: <a ...><button>第01集</button></a>（部分剧集，集名在按钮文本里）
        """
        episodes = []
        pat = (r'<a href="(/(?:tv|movie)/' + re.escape(hash_id) +
               r'\.html\?origin=([^&"]+)&amp;p=(\d+))"([^>]*)>(.*?)</a>')
        for m in re.finditer(pat, html, re.S):
            path, origin_enc, p_idx, attrs, inner = m.groups()
            # 集名: data-title 优先，否则取 <a> 内按钮文本
            title = self._match(r'data-title="([^"]*)"', attrs)
            if not title:
                title = self._strip_tags(inner)
            title = (title or '').strip() or ('第%s集' % (int(p_idx) + 1))
            title = self._beautify_title(title)
            # href 中的 &amp; 需还原为 &，否则 p 参数丢失会导致所有集都播第1集
            episodes.append((int(p_idx), title, self._url(path.replace('&amp;', '&'))))
        episodes.sort(key=lambda x: x[0])
        return [(t, u) for _, t, u in episodes]

    def detailContent(self, ids):
        """详情页：线路 + 集数"""
        if isinstance(ids, str):
            ids = [ids]
        if not ids:
            return {'list': []}
        detail_path = ids[0]

        # 简单缓存（详情页多线路需要多次请求，避免频繁拉取）
        cache_key = detail_path
        now = int(time.time())
        if cache_key in self._detail_cache and now - self._detail_cache_time < 300:
            return {'list': [self._detail_cache[cache_key]]}

        html = self._txt(self._url(detail_path), timeout=30)
        if not html:
            return {'list': []}

        # 基本信息
        name = self._match(r'<h1[^>]*>([^<]*)</h1>', html) or \
               self._match(r'property="og:title" content="([^"]+)"', html)
        pic = self._match(r'property="og:image" content="([^"]+)"', html)
        desc = self._match(r'property="og:description" content="([^"]+)"', html)
        year = self._match(r'\((\d{4})\)',
                           self._match(r'property="og:title" content="([^"]+)"', html))

        # hash/id（集数链接使用 /tv/{hash}/{id}.html 斜杠形式）
        hm = re.search(r'/(?:movie|tv)/([0-9a-f]+)-(\d+)\.html', detail_path)
        hash_id = ""
        if hm:
            hash_id = "%s/%s" % (hm.group(1), hm.group(2))

        # 线路 tab
        origins = self._parse_origin_tabs(html, detail_path)
        if not origins:
            origins = ['默认线路']

        # 第一条线路的集数直接用当前页，其余线路并发拉取
        line_eps = {}

        def fetch_line(origin):
            if origin == origins[0]:
                return origin, self._parse_episodes(html, hash_id)
            page_url = self._url(detail_path) + '?origin=' + quote(origin)
            page_html = self._txt(page_url, timeout=30)
            return origin, self._parse_episodes(page_html, hash_id)

        try:
            from concurrent.futures import ThreadPoolExecutor
            pool = ThreadPoolExecutor(max_workers=4)
            for origin, eps in pool.map(fetch_line, origins):
                if eps:
                    line_eps[origin] = eps
            pool.shutdown(wait=False)
        except Exception:
            for origin in origins:
                try:
                    o, eps = fetch_line(origin)
                    if eps:
                        line_eps[o] = eps
                except Exception:
                    continue

        if not line_eps:
            return {'list': []}

        play_from = []
        play_url = []
        for origin in origins:
            eps = line_eps.get(origin)
            if not eps:
                continue
            play_from.append(origin)
            play_url.append('#'.join('%s$%s' % (t, u) for t, u in eps))

        vod = {
            'vod_id': detail_path,
            'vod_name': name,
            'vod_pic': pic,
            'vod_year': year,
            'vod_content': desc,
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url),
        }
        self._detail_cache = {cache_key: vod}
        self._detail_cache_time = now
        return {'list': [vod]}

    # ========== 搜索 ==========

    def searchContent(self, key, quick, pg="1"):
        """搜索"""
        url = self.host + '/s.html?name=' + quote(key)
        html = self._txt(url, timeout=30)
        videos = self._parse_cards(html)
        return {'list': videos, 'page': 1, 'pagecount': 1,
                'limit': 24, 'total': len(videos)}

    # ========== 播放解析 ==========

    def playerContent(self, flag, id, vipFlags):
        """播放解析：集数页 → preload 的 /api/m3u8 直链"""
        if not id:
            return {'parse': 1, 'playUrl': '', 'url': ''}

        url = id if str(id).startswith("http") else self._url(id)

        # 1. 直链检测
        if '.m3u8' in url.lower():
            return {
                'parse': 0,
                'playUrl': '',
                'url': url,
                'header': {
                    'User-Agent': self.header['User-Agent'],
                    'Referer': self.host + '/',
                },
                'format': 'application/x-mpegURL',
                'contentType': 'application/x-mpegURL',
            }

        # 2. 集数页 → preload 的 /api/m3u8 地址
        html = self._txt(url, referer=self.host + '/', timeout=30)
        if html:
            api = self._match(r'rel="preload" href="(/api/m3u8[^"]+)"', html)
            if not api:
                # 退化：页面任意位置找 api/m3u8
                api = self._match(r'["\'](/api/m3u8[^"\']+)["\']', html)
            if api:
                api = api.replace('&amp;', '&')
                media = self._url(api)
                return {
                    'parse': 0,
                    'playUrl': '',
                    'url': media,
                    'header': {
                        'User-Agent': self.header['User-Agent'],
                        'Referer': url,
                    },
                    'format': 'application/x-mpegURL',
                    'contentType': 'application/x-mpegURL',
                }

        # 3. 兜底交给壳子嗅探
        return {
            'parse': 1,
            'playUrl': '',
            'url': url,
            'header': {
                'User-Agent': self.header['User-Agent'],
                'Referer': self.host + '/',
            },
        }

    # ========== 本地代理（可选）==========

    def localProxy(self, param):
        return {}

    # ========== 清理 ==========

    def destroy(self):
        pass

    def close(self):
        """T4 WebHomeTV 清理方法"""
        self.destroy()

    def getName(self):
        return "电影人生"
