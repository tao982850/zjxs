# -*- coding: utf-8 -*-
"""
TVBox Python Spider - 荐片影视 (jpyy.site)
适配 FongMi TV / OK影视 / webhome 框架
MacCMS 站, API 关闭, 走 HTML 解析

借鉴国色天香 + 果香园模板优化:
- requests.Session 连接复用: 减少 TCP/TLS 握手开销
- UA 轮换重试 + SSL 降级: 3 个 UA 自动切换, SSL 失败时 verify=False 兜底
- 完整浏览器请求头: sec-ch-ua / sec-fetch-* / Referer
- 播放 URL 缓存: 重复播放同一视频秒出(1 小时 TTL)
- 首页 HTML 缓存: homeContent + homeVideoContent 共享(5 分钟 TTL)
- 域名配置化: host 为类变量, init 支持 extend 覆盖
- CF 挑战页检测: 避免把挑战页当正常内容返回
- 超时 10s: 减少用户等待转圈时间

站点结构:
- 分类页: /list/{slug}.html, 翻页 /list/{slug}-{page}.html
- 详情页: /movie/{id}.html (标题/封面/年份/地区/类型/简介/播放源/剧集)
- 播放页: /play/{vid}-{src}-{ep}.html (player_aaaa + encrypt:2)
  解码链路: base64decode(url) -> unquote() -> m3u8 直链
- 搜索页: /search.html?wd={keyword} (服务端渲染, 可用)
"""
import sys
sys.path.append("..")

import re
import json
import time
import base64

try:
    from urllib.parse import quote as _quote, unquote as _unquote
except:
    try:
        from urllib import quote as _quote, unquote as _unquote
    except:
        _quote = lambda x: x
        _unquote = lambda x: x

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            import requests
            kw.pop('timeout', None)
            r = requests.get(url, headers=headers or {}, timeout=15, **kw)
            return r

        def post(self, url, data=None, headers=None, **kw):
            import requests
            r = requests.post(url, data=data, headers=headers or {}, timeout=15, **kw)
            return r


# UA 轮换池(请求失败时自动切换)
_UA_POOL = [
    'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
]

# 缓存 TTL(秒)
_HOME_CACHE_TTL = 300    # 首页缓存 5 分钟
_PLAY_CACHE_TTL = 3600  # 播放 URL 缓存 1 小时
_REQUEST_TIMEOUT = 10   # 请求超时(秒)


class Spider(Spider):
    host = "https://m.jpyy.site"

    header = {
        'User-Agent': _UA_POOL[0],
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Referer': 'https://m.jpyy.site/',
        'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'Upgrade-Insecure-Requests': '1',
    }

    # 分类: (slug, 分类名) — slug 用于 URL 路径
    categories = [
        ("dianying", "电影"),
        ("dianshiju", "电视剧"),
        ("zongyi", "综艺"),
        ("dongman", "动漫"),
        ("duanju", "短剧"),
    ]

    def __init__(self):
        self._init_state()

    def _init_state(self):
        """统一初始化, __init__ 和 init 都调用, 防止框架不调 __init__"""
        if not hasattr(self, '_session') or self._session is None:
            self._session = None
        if not hasattr(self, '_home_html'):
            self._home_html = ''
        if not hasattr(self, '_home_html_time'):
            self._home_html_time = 0
        if not hasattr(self, '_play_cache'):
            self._play_cache = {}
        if not hasattr(self, '_header_inited'):
            self.header = dict(Spider.header)
            self._header_inited = True

    # ============================================================
    #  基础方法 (TVBox 框架必需)
    # ============================================================

    def getName(self):
        return '荐片影视'

    def init(self, extend=""):
        self._init_state()
        if isinstance(extend, list):
            self.extend = ''
        else:
            self.extend = extend or ''
        if self.extend and self.extend.startswith('http'):
            m = re.match(r'(https?://[^/]+)', self.extend)
            if m:
                self.host = m.group(1).rstrip('/')
                Spider.host = self.host
                self.header['Referer'] = self.host + '/'
        if _HAS_REQUESTS and not self._session:
            self._session = _requests.Session()
            self._session.headers.update({
                'Accept-Encoding': 'gzip, deflate',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'Upgrade-Insecure-Requests': '1',
            })
        return ''

    def isVideoFormat(self, url):
        if not url or not isinstance(url, str):
            return False
        return any(x in url for x in ['.m3u8', '.mp4', '.flv', '.ts', '.mkv'])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
        self._play_cache.clear()

    # ============================================================
    #  内部请求 (UA 轮换 + Session 连接复用 + SSL 降级)
    # ============================================================

    def _get_session(self):
        if not self._session and _HAS_REQUESTS:
            self._session = _requests.Session()
            self._session.headers.update({
                'Accept-Encoding': 'gzip, deflate',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'Upgrade-Insecure-Requests': '1',
            })
        return self._session

    @staticmethod
    def _is_cf_challenge(text):
        if not text or len(text) < 200:
            return True
        markers = ['Just a moment', 'cf-challenge', 'challenge-platform',
                   'cf-browser-verification', 'cf-mitigated',
                   'Attention Required', 'enable JavaScript']
        low = text[:2000].lower()
        for m in markers:
            if m.lower() in low:
                return True
        return False

    def _fetch_html(self, path, use_cache=False):
        """
        统一 HTML 获取方法:
        1. 优先使用框架 fetch(兼容 TVBox 环境)
        2. 失败时用 requests.Session 重试(连接复用 + UA 轮换 + SSL 降级)
        3. 支持首页缓存(homeContent + homeVideoContent 共享)
        """
        url = path if path.startswith('http') else self.host + path

        if use_cache:
            now = time.time()
            if self._home_html and (now - self._home_html_time) < _HOME_CACHE_TTL:
                return self._home_html

        for ua in _UA_POOL:
            headers = dict(self.header)
            headers['User-Agent'] = ua
            headers['Referer'] = self.host + '/'

            try:
                r = self.fetch(url, headers=headers, timeout=_REQUEST_TIMEOUT)
                text = r.text if hasattr(r, 'text') else ''
                if text and not self._is_cf_challenge(text):
                    if use_cache:
                        self._home_html = text
                        self._home_html_time = time.time()
                    return text
            except Exception:
                pass

            session = self._get_session()
            if session:
                try:
                    r = session.get(url, headers=headers, timeout=_REQUEST_TIMEOUT,
                                    allow_redirects=True)
                    if r.status_code == 200 and r.text and not self._is_cf_challenge(r.text):
                        if use_cache:
                            self._home_html = r.text
                            self._home_html_time = time.time()
                        return r.text
                except Exception:
                    try:
                        r = session.get(url, headers=headers, timeout=_REQUEST_TIMEOUT,
                                        allow_redirects=True, verify=False)
                        if r.status_code == 200 and r.text and not self._is_cf_challenge(r.text):
                            if use_cache:
                                self._home_html = r.text
                                self._home_html_time = time.time()
                            return r.text
                    except Exception:
                        continue

        return ''

    @staticmethod
    def _fix_url(url):
        if not url:
            return ''
        url = url.strip()
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return Spider.host + url
        return url

    # ============================================================
    #  卡片解析 (layui-col + item-cover + item-title 结构)
    # ============================================================

    @staticmethod
    def _parse_cards(html):
        """
        解析 jpyy.site 的卡片结构:
        <div class="layui-col-xs6 ...">
            <div class="item-cover">
                <div class="pic">
                    <a href="/movie/{id}.html"></a>
                    <img src="/assets/images/load.webp" lay-src="{real_pic}">
                </div>
                <div class="tag">{remark}</div>
            </div>
            <div class="item-title">
                <a href="/movie/{id}.html">{title}</a>
            </div>
        </div>
        """
        if not html:
            return []
        vod_list = []
        seen = set()

        # 匹配所有 /movie/{id}.html 链接 + lay-src 封面 + 标题 + tag
        cards = re.findall(
            r'<div class="item-cover">\s*'
            r'<div class="pic">\s*'
            r'<a href="/movie/(\d+)\.html"></a>\s*'
            r'<img[^>]*lay-src="([^"]*)"[^>]*>\s*'
            r'</div>\s*'
            r'<div class="tag">([^<]*)</div>\s*'
            r'</div>\s*'
            r'<div class="item-title">\s*'
            r'<a href="/movie/\d+\.html">([^<]+)</a>',
            html, re.DOTALL
        )

        for vid, pic, remark, title in cards:
            if vid in seen:
                continue
            seen.add(vid)
            vod_list.append({
                'vod_id': vid,
                'vod_name': title.strip(),
                'vod_pic': pic.strip(),
                'vod_remarks': remark.strip(),
            })

        # 兜底: 如果精确匹配失败, 用宽松正则
        if not vod_list:
            # 先找所有 movie 链接
            movie_ids = re.findall(r'href="/movie/(\d+)\.html"', html)
            for mid in movie_ids:
                if mid in seen:
                    continue
                seen.add(mid)
                # 找该链接附近的 lay-src 和标题
                pos = html.find('/movie/%s.html' % mid)
                if pos < 0:
                    continue
                context = html[max(0, pos - 500):pos + 500]
                pic_m = re.search(r'lay-src="([^"]*)"', context)
                title_m = re.search(r'class="item-title"[^>]*>\s*<a[^>]*>([^<]+)</a>', context)
                tag_m = re.search(r'class="tag">([^<]*)</div>', context)
                vod_list.append({
                    'vod_id': mid,
                    'vod_name': title_m.group(1).strip() if title_m else '',
                    'vod_pic': pic_m.group(1).strip() if pic_m else '',
                    'vod_remarks': tag_m.group(1).strip() if tag_m else '',
                })

        return vod_list

    # ============================================================
    #  首页 (HTML 缓存, 消除重复请求)
    # ============================================================

    def homeContent(self, filter):
        try:
            result = {
                'class': [{'type_id': slug, 'type_name': name}
                          for slug, name in self.categories],
                'filters': {},
            }
            html = self._fetch_html('/', use_cache=True)
            result['list'] = self._parse_cards(html)
            return result
        except Exception:
            return {
                'class': [{'type_id': slug, 'type_name': name}
                          for slug, name in self.categories],
                'filters': {},
                'list': [],
            }

    def homeVideoContent(self):
        try:
            html = self._fetch_html('/', use_cache=True)
            return {'list': self._parse_cards(html)}
        except Exception:
            return {'list': []}

    # ============================================================
    #  分类 (服务端渲染, 翻页可用)
    # ============================================================

    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            pg = int(pg) if pg else 1
            # 第一页: /list/{slug}.html
            # 第N页: /list/{slug}-{N}.html
            if pg <= 1:
                path = '/list/%s.html' % tid
            else:
                path = '/list/%s-%d.html' % (tid, pg)

            html = self._fetch_html(path)
            videos = self._parse_cards(html)

            # 估算总页数: 从页面中找最大页码
            pagecount = 1
            if html:
                page_nums = re.findall(r'/list/%s-(\d+)\.html' % re.escape(tid), html)
                if page_nums:
                    pagecount = max(int(p) for p in page_nums)
                # 如果当前页有数据但没找到翻页信息, 至少保留当前页
                if not pagecount and videos:
                    pagecount = pg

            return {
                'page': pg,
                'pagecount': pagecount,
                'limit': len(videos),
                'total': pagecount * 20,
                'list': videos,
            }
        except Exception:
            return {'page': pg, 'pagecount': 1, 'limit': 20, 'total': 0, 'list': []}

    # ============================================================
    #  详情页 (标题/封面/年份/地区/类型/简介/播放源/剧集)
    # ============================================================

    def detailContent(self, ids):
        try:
            vid = ids[0] if isinstance(ids, list) else str(ids)
            html = self._fetch_html('/movie/%s.html' % vid)
            if not html:
                return {'list': []}

            # 标题: <title>《{title}》... - 荐片影视</title>
            title = ''
            m = re.search(r'<title>([^<]+)</title>', html)
            if m:
                raw = m.group(1)
                # 去掉 《》和后续后缀
                tm = re.search(r'[《]([^》]+)[》]', raw)
                if tm:
                    title = tm.group(1)
                else:
                    for sep in ['全集在线观看', '- 荐片', '在线观看', '- ']:
                        idx = raw.find(sep)
                        if idx > 0:
                            raw = raw[:idx]
                            break
                    title = raw.strip()
            if not title:
                m = re.search(r'<meta\s+name="keywords"\s+content="([^,"]+)', html)
                if m:
                    title = m.group(1).strip()

            # 封面: 第一个 lay-src 中含 jisuimage/cover 的
            pic = ''
            lazy_imgs = re.findall(r'lay-src="([^"]*)"', html)
            for i in lazy_imgs:
                if 'cover' in i or 'jisuimage' in i:
                    pic = i
                    break
            if not pic and lazy_imgs:
                pic = lazy_imgs[0]
            pic = self._fix_url(pic)

            # 简介: info-desc div
            desc = ''
            m = re.search(r'class="info-desc">([^<]*(?:<[^>]*>[^<]*)*)</div>', html, re.DOTALL)
            if m:
                desc = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                # 去掉 "简介：" 前缀
                desc = re.sub(r'^[简介：:]+', '', desc).strip()
            if not desc:
                m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html)
                if m:
                    desc = m.group(1)
                    # 去掉 "荐片影视为你提供XXX剧情简介:" 前缀
                    desc = re.sub(r'^.*?剧情简介[：:]', '', desc).strip()

            # 年份/地区/类型: 从 info-row 中提取
            year = ''
            area = ''
            type_ = ''
            actor = ''
            director = ''
            # info-label + info-text 配对
            pairs = re.findall(
                r'class="info-label">([^<]+)</span>\s*<span\s+class="info-text">([^<]*)</span>',
                html
            )
            for label, value in pairs:
                label = label.strip().rstrip('：:')
                value = value.strip()
                if not value or value == '内详':
                    continue
                if '年份' in label:
                    year = value
                elif '地区' in label:
                    area = value
                elif '类型' in label:
                    type_ = value
                elif '主演' in label:
                    actor = value
                elif '导演' in label:
                    director = value
            # 兜底: 从 meta description 或 info 文本中提取年份
            if not year:
                ym = re.search(r'(\d{4})', desc or html[:5000])
                if ym:
                    year = ym.group(1)

            # 播放源和剧集: /play/{vid}-{src}-{ep}.html
            plays = re.findall(
                r'href="/play/%s-(\d+)-(\d+)\.html"[^>]*>([^<]+)<' % re.escape(vid),
                html
            )

            if not plays:
                plays = [('1', '1', '点击播放')]

            # 按来源(src)分组
            sources = {}
            for src_id, ep_id, ep_name in plays:
                if src_id not in sources:
                    sources[src_id] = []
                sources[src_id].append((ep_id, ep_name))

            # 源名称: 从 h2 标签提取(每个 video_list 前的 h2)
            sorted_srcs = sorted(sources.keys(), key=lambda x: int(x) if x.isdigit() else 0)
            src_names = {}
            h2s = re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.DOTALL)
            for i, h in enumerate(h2s):
                name = re.sub(r'<[^>]+>', '', h).strip()
                if name and i < len(sorted_srcs):
                    src_names[sorted_srcs[i]] = name
            # 如果只有1个源且没找到h2, 用默认名
            if not src_names and sorted_srcs:
                src_names[sorted_srcs[0]] = '荐片专线'

            # 构建播放列表
            play_from_parts = []
            play_url_parts = []
            for idx, src_id in enumerate(sorted_srcs):
                sname = src_names.get(src_id, '线路%d' % (idx + 1))
                play_from_parts.append(sname)
                eps = sources[src_id]
                ep_list = []
                for ep_id, ep_name in eps:
                    ep_name = ep_name.strip() if ep_name.strip() else '第%s集' % ep_id
                    play_url = '/play/%s-%s-%s.html' % (vid, src_id, ep_id)
                    ep_list.append('%s$%s' % (ep_name, play_url))
                play_url_parts.append('#'.join(ep_list))

            vod = {
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'vod_year': year,
                'vod_area': area,
                'vod_type': type_,
                'vod_actor': actor,
                'vod_director': director,
                'vod_content': desc,
                'vod_play_from': '$$$'.join(play_from_parts),
                'vod_play_url': '$$$'.join(play_url_parts),
            }
            return {'list': [vod]}
        except Exception:
            return {'list': []}

    # ============================================================
    #  搜索 (服务端渲染, 可用)
    # ============================================================

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg) if pg else 1
            kw = _quote(key)
            path = '/search.html?wd=%s' % kw
            if pg > 1:
                path += '&page=%d' % pg
            html = self._fetch_html(path)
            results = self._parse_cards(html)
            return {'page': pg, 'list': results}
        except Exception:
            return {'page': 1, 'list': []}

    def searchContentPage(self, key, quick, pg=1):
        return self.searchContent(key, quick, pg)

    # ============================================================
    #  播放 (player_aaaa + encrypt:2 解码)
    # ============================================================

    def playerContent(self, flag, id, vipFlags):
        """
        播放页解码链路:
        1. 提取 player_aaaa JSON 对象
        2. encrypt=2: base64decode(url) -> unquote() -> m3u8 直链
        3. encrypt=1: unquote(url) -> m3u8 直链
        4. encrypt=0: url 即直链
        5. 兜底: 直接搜索 m3u8/mp4 直链
        """
        try:
            if not id.startswith('http'):
                url = self.host + id if id.startswith('/') else self.host + '/' + id
            else:
                url = id

            # 播放 URL 缓存
            cache_key = url
            now = time.time()
            cached = self._play_cache.get(cache_key)
            if cached and (now - cached['time']) < _PLAY_CACHE_TTL:
                return {
                    'parse': 0,
                    'playUrl': '',
                    'url': cached['url'],
                    'header': json.dumps({
                        'User-Agent': self.header['User-Agent'],
                        'Referer': self.host,
                    }),
                    'from': flag,
                }

            html = self._fetch_html(url)
            play_url = ''

            # 提取 player_aaaa JSON(用 JSONDecoder 处理嵌套花括号)
            if html:
                idx = html.find('player_aaaa')
                if idx >= 0:
                    brace_idx = html.find('{', idx)
                    if brace_idx >= 0:
                        try:
                            from json.decoder import JSONDecoder
                            decoder = JSONDecoder()
                            obj, _ = decoder.raw_decode(html[brace_idx:])
                            encrypt = obj.get('encrypt', 0)
                            enc_url = obj.get('url', '')

                            if encrypt == 2:
                                # base64 -> url_decode
                                decoded = base64.b64decode(enc_url).decode('utf-8')
                                play_url = _unquote(decoded)
                            elif encrypt == 1:
                                play_url = _unquote(enc_url)
                            else:
                                play_url = enc_url
                        except Exception:
                            pass

            # 兜底: 直接搜索 m3u8 直链
            if not play_url:
                m = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
                if m:
                    play_url = m.group(0)

            # 兜底: 搜索 mp4 直链
            if not play_url:
                m = re.search(r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*', html)
                if m:
                    play_url = m.group(0)

            if play_url:
                self._play_cache[cache_key] = {'url': play_url, 'time': now}
                return {
                    'parse': 0,
                    'playUrl': '',
                    'url': play_url,
                    'header': json.dumps({
                        'User-Agent': self.header['User-Agent'],
                        'Referer': self.host,
                    }),
                    'from': flag,
                }

            # 兜底: 交给框架解析
            return {
                'parse': 1,
                'playUrl': '',
                'url': url,
                'header': json.dumps({
                    'User-Agent': self.header['User-Agent'],
                    'Referer': self.host,
                }),
                'from': flag,
            }
        except Exception:
            return {
                'parse': 1,
                'playUrl': '',
                'url': '',
                'header': json.dumps({'User-Agent': self.header['User-Agent']}),
                'from': flag,
            }
