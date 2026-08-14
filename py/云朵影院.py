# -*- coding: utf-8 -*-
# 云朵影视 - 真实 XHR 接口版
# 适配绿豆 TVBox / OK影视
# 分类接口: /api.php/web/filter/vod?type_id=1&page=1&sort=hits
# 详情接口: /api.php/web/vod/get_detail?vod_id=xxx
# 聚合线路: /api.php/web/internal/search_aggregate?vod_id=xxx

import sys
sys.path.append('..')

import json
import re
from urllib.parse import urlencode, quote
from html.parser import HTMLParser
from base.spider import Spider


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._text = []

    def handle_data(self, data):
        self._text.append(data)

    def get_text(self):
        return ''.join(self._text)


class Spider(Spider):
    def __init__(self):
        self.host = 'https://ds3xy2yunsa.xyz'
        self.classes = [
            {'type_id': '1', 'type_name': '电影'},
            {'type_id': '2', 'type_name': '剧集'},
            {'type_id': '3', 'type_name': '动漫'},
            {'type_id': '4', 'type_name': '综艺'},
        ]
        self.web_sign = 'yda81x6d9ad3c4s'
        self.x_client = '8f3d2a1c7b6e5d4c9a0b1f2e3d4c5b6a'

    def init(self, extend=''):
        try:
            if extend:
                if isinstance(extend, dict):
                    ext = extend
                else:
                    text = str(extend).strip()
                    ext = json.loads(text) if text.startswith('{') else {'site': text}
                site = ext.get('site') or ext.get('host') or ''
                if site:
                    self.host = str(site).split(',')[0].strip().rstrip('/')
                self.web_sign = ext.get('web-sign') or ext.get('web_sign') or self.web_sign
                self.x_client = ext.get('x-client') or ext.get('x_client') or self.x_client
        except Exception:
            pass
        return None

    def _ensure_ready(self):
        if not getattr(self, 'host', ''):
            self.host = 'https://ds3xy2yunsa.xyz'
        self.host = self.host.rstrip('/')

    def getName(self):
        return '云朵影视'

    def destroy(self):
        pass

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv|mkv|avi)(\?|$)', str(url or ''), re.I))

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return None

    def _headers(self, referer=''):
        self._ensure_ready()
        return {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Mobile Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': referer or (self.host + '/'),
            'web-sign': self.web_sign,
            'x-client': self.x_client,
            'x-requested-with': 'XMLHttpRequest',
        }

    def _api_get(self, path, params=None, referer=''):
        self._ensure_ready()
        params = params or {}
        qs = urlencode(params, doseq=True)
        url = self.host + path + (('?' + qs) if qs else '')
        try:
            r = self.fetch(url, headers=self._headers(referer), timeout=12)
            text = getattr(r, 'text', '') or getattr(r, 'content', b'')
            if isinstance(text, bytes):
                text = text.decode('utf-8', errors='ignore')
            if not text:
                return {}
            return json.loads(text)
        except Exception as e:
            print('云朵接口请求失败:', path, params, e)
            return {}

    def _clean_text(self, s):
        s = str(s or '')
        s = re.sub(r'<[^>]+>', ' ', s)
        s = s.replace('&nbsp;', ' ')
        return re.sub(r'\s+', ' ', s).strip()

    def _html2text(self, html):
        try:
            p = _HTMLTextExtractor()
            p.feed(str(html or ''))
            return self._clean_text(p.get_text())
        except Exception:
            return self._clean_text(html)

    def _as_list(self, data):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in ('data', 'list', 'items', 'records', 'rows', 'vod_list'):
                v = data.get(k)
                if isinstance(v, list):
                    return v
                if isinstance(v, dict):
                    vv = self._as_list(v)
                    if vv:
                        return vv
        return []

    def _vod_item(self, item):
        if not isinstance(item, dict):
            return None
        vid = item.get('vod_id') or item.get('id') or item.get('vodId')
        name = item.get('vod_name') or item.get('name') or item.get('title')
        if not vid or not name:
            return None
        area = item.get('vod_area', '')
        cls = item.get('vod_class', '')
        if isinstance(area, list):
            area = ','.join([str(x) for x in area if x])
        if isinstance(cls, list):
            cls = ','.join([str(x) for x in cls if x])
        return {
            'vod_id': str(vid),
            'vod_name': self._clean_text(name),
            'vod_pic': str(item.get('vod_pic') or item.get('pic') or item.get('cover') or ''),
            'vod_remarks': str(item.get('vod_remarks') or item.get('remarks') or item.get('vod_douban_score') or item.get('vod_year') or ''),
            'vod_year': str(item.get('vod_year') or ''),
            'type_name': self._clean_text(item.get('type_name') or cls or ''),
            'vod_area': self._clean_text(area),
        }

    def _vod_list(self, data):
        arr = self._as_list(data)
        out = []
        seen = set()
        for item in arr:
            v = self._vod_item(item)
            if not v:
                continue
            if v['vod_id'] in seen:
                continue
            seen.add(v['vod_id'])
            out.append(v)
        return out

    def homeContent(self, filter):
        # 绿豆兼容：home 不联网，避免一直加载。
        return {'class': self.classes}

    def homeVideoContent(self):
        # 用电影热门做首页推荐。
        j = self._api_get('/api.php/web/filter/vod', {
            'type_id': '1',
            'page': '1',
            'sort': 'hits'
        }, self.host + '/type/1')
        return {'list': self._vod_list(j)}

    def categoryContent(self, tid, pg, filter, extend):
        self._ensure_ready()
        page = str(pg or '1')
        sort = 'hits'
        if isinstance(extend, dict):
            sort = extend.get('sort') or extend.get('by') or sort

        # 真实 XHR 分类接口
        j = self._api_get('/api.php/web/filter/vod', {
            'type_id': str(tid),
            'page': page,
            'sort': sort
        }, self.host + '/type/' + str(tid))

        videos = self._vod_list(j)
        pagecount = 1
        total = len(videos)
        limit = 24
        if isinstance(j, dict):
            pagecount = int(j.get('pageCount') or j.get('pagecount') or (int(page) + 1 if videos else int(page)))
            total = int(j.get('total') or total)
            limit = int(j.get('limit') or limit)

        return {
            'list': videos,
            'page': int(page),
            'pagecount': pagecount,
            'limit': limit,
            'total': total
        }

    def searchContent(self, key, quick, pg='1'):
        self._ensure_ready()
        wd = str(key or '').strip()
        page = str(pg or '1')
        if not wd:
            return {'list': [], 'page': int(page)}

        # 先尝试网页搜索常见接口
        paths = [
            ('/api.php/web/search/vod', {'wd': wd, 'page': page}),
            ('/api.php/web/vod/search', {'wd': wd, 'page': page}),
            ('/api.php/web/search', {'wd': wd, 'page': page}),
            ('/api.php/web/filter/vod', {'keyword': wd, 'page': page, 'sort': 'hits'}),
        ]
        for path, params in paths:
            j = self._api_get(path, params, self.host + '/search?keyword=' + quote(wd))
            videos = self._vod_list(j)
            if videos:
                return {'list': videos, 'page': int(page)}
        return {'list': [], 'page': int(page)}

    def _first_detail(self, ids):
        vid = str(ids[0] if isinstance(ids, list) else ids)
        j = self._api_get('/api.php/web/vod/get_detail', {'vod_id': vid}, self.host + '/detail/' + vid)
        arr = self._as_list(j)
        return (arr[0] if arr else {}), j

    def _aggregate_sources(self, vid):
        # 真实详情页还会请求这个聚合接口，里面有很多站外直链 m3u8。
        paths = [
            '/api.php/web/internal/search_aggregate',
            '/api.php/web/search_aggregate',
        ]
        for path in paths:
            j = self._api_get(path, {'vod_id': str(vid)}, self.host + '/detail/' + str(vid))
            arr = self._as_list(j)
            if arr:
                return arr
        return []

    def _line_rank(self, src):
        name = str(src.get('site_name') or src.get('vod_play_from') or '').lower()
        from_code = str(src.get('vod_play_from') or '').lower()
        url = str(src.get('vod_play_url') or '')
        # 优先站外直链，其次官方需要解析的线路。
        if '.m3u8' in url:
            if '极速' in name or 'jsm3u8' in from_code:
                return 1
            if '如意' in name or 'rym3u8' in from_code:
                return 2
            if '量子' in name or 'lzm3u8' in from_code:
                return 3
            return 5
        if src.get('decode_status') == 0:
            return 10
        return 99

    def _build_sources(self, vid, detail):
        sources = []
        agg = self._aggregate_sources(vid)
        if agg:
            # 排序后只取前面可用线路，避免详情页线路过多导致 TVBox 卡顿。
            agg = sorted(agg, key=self._line_rank)
            for src in agg:
                play_from = str(src.get('site_name') or src.get('vod_play_from') or '').strip()
                play_url = str(src.get('vod_play_url') or '').strip()
                if not play_from or not play_url:
                    continue
                # 优先保留直链 m3u8/mp4 线路和少量解析线路
                if ('.m3u8' in play_url or '.mp4' in play_url or src.get('decode_status') == 0 or len(sources) < 6):
                    sources.append((play_from, play_url))
                if len(sources) >= 8:
                    break

        # 兜底使用 get_detail 里的线路；这个接口会返回 vod_play_from / vod_play_url。
        pf = str(detail.get('vod_play_from') or '')
        pu = str(detail.get('vod_play_url') or '')
        if pf and pu:
            froms = pf.split('$$$')
            urls = pu.split('$$$')
            for idx, f in enumerate(froms):
                u = urls[idx] if idx < len(urls) else ''
                if not f or not u:
                    continue
                # 如果已经有同名线路就跳过。
                if any(x[0] == f for x in sources):
                    continue
                # 只加少量兜底，避免超长。
                if len(sources) < 10:
                    sources.append((f, u))

        return sources

    def detailContent(self, ids):
        self._ensure_ready()
        if not ids:
            return {'list': []}
        vid = str(ids[0])
        detail, raw = self._first_detail([vid])

        if not detail:
            return {'list': []}

        area = detail.get('vod_area', '')
        cls = detail.get('vod_class', '')
        if isinstance(area, list):
            area = ','.join([str(x) for x in area if x])
        if isinstance(cls, list):
            cls = ','.join([str(x) for x in cls if x])

        sources = self._build_sources(vid, detail)
        vod = {
            'vod_id': vid,
            'vod_name': self._clean_text(detail.get('vod_name') or ''),
            'vod_pic': str(detail.get('vod_pic') or ''),
            'vod_remarks': str(detail.get('vod_remarks') or ''),
            'type_name': self._clean_text(detail.get('type_name') or cls or ''),
            'vod_year': str(detail.get('vod_year') or ''),
            'vod_area': self._clean_text(area),
            'vod_actor': self._clean_text(detail.get('vod_actor') or ''),
            'vod_director': self._clean_text(detail.get('vod_director') or ''),
            'vod_content': self._html2text(detail.get('vod_content') or ''),
            'vod_play_from': '$$$'.join([x[0] for x in sources]),
            'vod_play_url': '$$$'.join([x[1] for x in sources]),
        }
        return {'list': [vod]}

    def playerContent(self, flag, id, vipFlags):
        self._ensure_ready()
        url = str(id or '').strip()
        if not url:
            return {'parse': 0, 'url': ''}

        # 直链直接播放
        if url.startswith('http') and self.isVideoFormat(url):
            return {
                'parse': 0,
                'jx': 0,
                'url': url,
                'header': {
                    'User-Agent': 'Mozilla/5.0',
                    'Referer': self.host + '/'
                }
            }

        # 官方站外编码线路尝试用 decode 接口解析
        decode_candidates = [
            ('/api.php/web/decode/url', {'url': url}),
            ('/api.php/web/decode/url', {'play_url': url}),
            ('/api.php/web/decode/url', {'vod_url': url}),
        ]
        for path, params in decode_candidates:
            j = self._api_get(path, params, self.host + '/')
            data = j.get('data') if isinstance(j, dict) else None
            final_url = ''
            headers = {}
            if isinstance(data, str):
                final_url = data
            elif isinstance(data, dict):
                final_url = data.get('url') or data.get('play_url') or data.get('playUrl') or data.get('video') or ''
                headers = data.get('header') or data.get('headers') or {}
            elif isinstance(j, dict):
                final_url = j.get('url') or j.get('play_url') or ''
                headers = j.get('header') or j.get('headers') or {}

            if final_url:
                return {
                    'parse': 0 if self.isVideoFormat(final_url) else 1,
                    'jx': 0 if self.isVideoFormat(final_url) else 1,
                    'url': final_url,
                    'header': headers or {'User-Agent': 'Mozilla/5.0', 'Referer': self.host + '/'}
                }

        # 腾讯/优酷/爱奇艺等网页地址交给壳解析
        if re.search(r'(v\.qq\.com|youku\.com|iqiyi\.com|mgtv\.com|bilibili\.com)', url, re.I):
            return {'parse': 1, 'jx': 1, 'url': url}

        # 其它未知地址也交给壳解析
        return {'parse': 1, 'jx': 1, 'url': url}
