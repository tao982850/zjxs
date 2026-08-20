# -*- coding: utf-8 -*-
# 4kcz（厂长资源）TvBox 爬虫源
# 站点: https://www.4kcz.com  (WordPress + mibt 主题)
#
# 使用说明:
#   - 列表页 / 详情页必须携带浏览器 User-Agent + Accept-Language，否则返回 403。
#   - 该站未开放站内搜索接口（搜索表单 action 指向障眼路径 /nimasile），
#     因此 searchContent 返回空列表。
#   - 详情页解析时抓取每集播放页，提取真实 m3u8 直链(无防盗链)，
#     playerContent 直接返回 m3u8 交由内置播放器播放。
#   - 本地自测: python3 4kcz.py
import base64
import re
import sys

import requests

try:
    sys.path.append('..')
    from base.spider import Spider as _BaseSpider
except Exception:          # 本地自测/无 TvBox 环境时退化为空基类
    class _BaseSpider:     # noqa: E306
        pass


class Spider(_BaseSpider):
    """4kcz 影视爬虫源，实现 TvBox Spider 标准接口。"""

    # ---------------------------------------------------------------- 站点配置
    base = 'https://www.4kcz.com'

    # 分类: key 用于展示, value 是列表页路径
    categories = {
        '全部':   '/movie_bt',
        '电影':   '/movie_bt_series/dyy',
        '国产剧': '/movie_bt_series/guochanju',
        '美剧':   '/movie_bt_series/mj',
        '韩剧':   '/movie_bt_series/hj',
        '日剧':   '/movie_bt_series/rj',
        '海外剧': '/movie_bt_series/hwj',
        '番剧':   '/movie_bt_view_cat/fjj',
        '预告':   '/movie_bt_view_cat/pvyugao',
    }

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/132.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': base,
    }

    # ---------------------------------------------------------------- 工具方法

    def _get(self, url, timeout=15):
        """带容错的 GET 请求，返回文本；失败返回空串。"""
        try:
            resp = requests.get(url, headers=self.headers, timeout=timeout)
            if resp.status_code != 200:
                return ''
            resp.encoding = resp.apparent_encoding or 'utf-8'
            return resp.text
        except requests.RequestException as e:
            print(f'[4kcz] 请求失败 {url}: {e}')
            return ''

    @staticmethod
    def _b64(url: str) -> str:
        """URL 安全 Base64 编码（去补位 =、替换 +/ 为 -_）。"""
        raw = base64.urlsafe_b64encode(url.encode('utf-8')).decode('utf-8')
        return raw.rstrip('=')

    @staticmethod
    def _b64_decode(token: str) -> str:
        """URL 安全 Base64 解码（容忍缺失的补位 =）。"""
        try:
            pad = '=' * (-len(token) % 4)
            return base64.urlsafe_b64decode(token + pad).decode('utf-8')
        except Exception:
            return ''

    @staticmethod
    def _clean(text: str) -> str:
        """去除 HTML 标签并压缩空白。"""
        text = re.sub(r'<[^>]+>', '', text or '')
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def _parse_items(html: str):
        """
        从列表页 HTML 提取视频条目。

        条目结构(mibt 主题):
            <li>
                <a href=".../movie/N.html">            <!-- 海报, 内含备注 -->
                    <img data-original="海报图">
                    <div class="jidi"><span>更新至3集</span></div>
                </a>
                <h3 class="dytit"><a href=".../movie/N.html">标题</a></h3>
                <p class="inzhuy">主演：...</p>
            </li>

        返回列表，每项含:
            {vod_id, vod_name, vod_pic, vod_remarks, vod_actor}
        """
        items = []
        li_pattern = re.compile(r'<li[^>]*>(.*?)</li>', re.S)

        for block in li_pattern.findall(html):
            m = re.search(r'href="[^"]*/movie/(\d+)\.html"', block)
            if not m:
                continue
            vid = m.group(1)

            # 标题: 优先取 h3.dytit 内链接文本，回退到第一个 movie 链接
            name_m = re.search(
                r'<h3[^>]*class="[^"]*dytit[^"]*"[^>]*>'
                r'<a[^>]*>(.*?)</a></h3>',
                block, re.S,
            ) or re.search(
                r'<a[^>]*href="[^"]*/movie/\d+\.html"[^>]*>(.*?)</a>',
                block, re.S,
            )
            if not name_m:
                continue
            name = Spider._clean(name_m.group(1))
            if not name:
                continue

            # 备注: 海报内 jidi 区或首个短文本 span(如"更新至12集")
            remark = ''
            m2 = re.search(
                r'<div class="jidi"[^>]*>\s*<span[^>]*>([^<]+)</span>', block,
            ) or re.search(r'<span[^>]*>([^<]{1,12})</span>', block)
            if m2:
                remark = Spider._clean(m2.group(1))

            # 海报: 依次尝试常见懒加载 data 属性
            pic = ''
            for attr in ('data-original', 'data-src', 'data-thumb', 'data-bg'):
                pm = re.search(rf'{attr}="([^"]+)"', block)
                if pm:
                    pic = pm.group(1)
                    break

            # 主演(可选)
            actor = ''
            am = re.search(r'class="inzhuy"[^>]*>\s*主演[:：]?\s*([^<]*)', block)
            if am:
                actor = Spider._clean(am.group(1))

            items.append({
                'vod_id': f'{vid}@{Spider._b64(f"{Spider.base}/movie/{vid}.html")}',
                'vod_name': name,
                'vod_pic': pic,
                'vod_remarks': remark,
                'vod_actor': actor,
            })
        return items

    def _extract_m3u8(self, play_html: str) -> str:
        """
        从播放页 HTML 提取真实 m3u8 地址。

        播放页里 iframe 指向 py1080p 网页播放器，其中 url 参数即真实 m3u8：
            https://plaa.py1080p.com:8181/player/py.php?...&url=https://hlsm3.py1080p.com/.../xx.m3u8
        该 m3u8 无防盗链，可直接访问。
        """
        m = re.search(r'player/py\.php[^"\']*url=([^"\'&\s]+)', play_html)
        if not m:
            # 兜底: 直接搜 .m3u8
            m2 = re.search(r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', play_html)
            return m2.group(1) if m2 else ''
        import urllib.parse
        return urllib.parse.unquote(m.group(1))

    def _resolve_play_url(self, detail_html: str):
        """
        解析播放列表并抓取每集真实 m3u8。

        返回 TvBox 播放串: "第1集$m3u8#第2集$m3u8#..."
        若某集抓取失败，用其播放页地址兜底。
        """
        episodes = re.findall(
            r'<a[^>]*href="[^"]*/v_play/([^"]+)\.html"[^>]*>([^<]+)</a>',
            detail_html,
        )
        if not episodes:
            return ''

        from concurrent.futures import ThreadPoolExecutor

        def resolve(ep):
            token, name = ep
            play_url = f'{self.base}/v_play/{token}.html'
            m3u8 = self._extract_m3u8(self._get(play_url))
            return name, (m3u8 or play_url)

        with ThreadPoolExecutor(max_workers=8) as pool:
            resolved = list(pool.map(resolve, episodes))

        return '#'.join(f'{name}${url}' for name, url in resolved)

    def _parse_detail(self, vid: str, html: str):
        """解析详情页，返回符合 TvBox 规范的 vod 字典。"""
        vod = {
            'vod_id': f'{vid}@{self._b64(f"{self.base}/movie/{vid}.html")}',
            'vod_name': '',
            'vod_pic': '',
            'vod_year': '',
            'vod_area': '',
            'type_name': '',
            'vod_director': '',
            'vod_actor': '',
            'vod_content': '',
            'vod_play_from': '4kcz',
            'vod_play_url': '',
        }

        # 标题
        h1 = re.search(r'<h1>([^<]+)</h1>', html)
        if h1:
            vod['vod_name'] = self._clean(h1.group(1))

        # 元数据区: 类型 / 地区 / 年份 / 导演 / 主演
        for label, key in (('类型', 'type_name'), ('地区', 'vod_area'),
                           ('年份', 'vod_year'), ('导演', 'vod_director'),
                           ('主演', 'vod_actor')):
            m = re.search(
                rf'<li>[^<]*{label}[:：]\s*<[^>]*>([^<]+)</a?>', html,
            ) or re.search(
                rf'<li>[^<]*{label}[:：]\s*<span>([^<]+)</span>', html,
            )
            if m:
                vod[key] = self._clean(m.group(1))

        # 海报(详情页大图)
        pm = re.search(r'data-original="([^"]+)"', html) or \
             re.search(r'<img[^>]*src="([^"]*uploads[^"]*)"[^>]*>', html)
        if pm:
            vod['vod_pic'] = pm.group(1)

        # 简介
        cm = re.search(r'<div class="yp_context">(.*?)</div>', html, re.S)
        if cm:
            vod['vod_content'] = self._clean(cm.group(1))

        # 播放列表: 抓取每集真实 m3u8(并发), 组成 "第1集$m3u8#第2集$m3u8#..."
        vod['vod_play_url'] = self._resolve_play_url(html)

        return vod

    # ---------------------------------------------------------------- TvBox 接口

    def init(self, extend=""):
        pass

    def getName(self):
        return '4kcz厂长资源'

    def homeContent(self, filter=False):
        """分类列表：type_id 传分类中文名作为标识，type_name 用于展示。"""
        classes = [
            {'type_id': cname, 'type_name': cname}
            for cname in self.categories
        ]
        return {'class': classes, 'filters': {}}

    def homeVideoContent(self):
        """首页推荐(近日更新)视频，去重后返回前 60 条。"""
        html = self._get(self.base + '/')
        items = self._parse_items(html)
        seen, result = set(), []
        for it in items:
            if it['vod_id'] in seen:
                continue
            seen.add(it['vod_id'])
            result.append(it)
        return {'list': result[:60]}

    def categoryContent(self, tid, pg, filter=False, extend={}):
        """分类列表，分页格式 /xxx/page/N。"""
        path = self.categories.get(tid, self.categories['全部'])
        page = int(pg) if str(pg).isdigit() else 1

        url = f'{self.base}{path}'
        if page > 1:
            url += f'/page/{page}'

        items = self._parse_items(self._get(url))
        return {
            'list': items,
            'page': page,
            'pagecount': page + 1,   # 无精确总页数，按需继续加载
            'limit': 24,
            'total': page * 24 + len(items),
        }

    def detailContent(self, ids):
        """详情页，返回单条 vod。"""
        ids = ids[0].split('@')
        vid = ids[0]
        detail_url = self._b64_decode(ids[1]) if len(ids) > 1 \
            else f'{self.base}/movie/{vid}.html'
        vod = self._parse_detail(vid, self._get(detail_url))
        return {'list': [vod]}

    def searchContent(self, key, quick, pg="1"):
        """该站未开放站内搜索，返回空结果。"""
        return {'list': []}

    def playerContent(self, flag, id, vipFlags):
        """id 为真实 m3u8 地址，直接交给内置播放器播放。"""
        return {
            'parse': 0,
            'jx': 0,
            'url': id,
            'header': {
                'User-Agent': self.headers['User-Agent'],
                'Referer': self.base,
            },
        }

    def localProxy(self, param):
        """无需本地代理。"""
        return None

    def destroy(self):
        pass


if __name__ == '__main__':
    s = Spider()
    s.init()

    print('name:', s.getName())
    home = s.homeContent()
    print('class:', [c['type_name'] for c in home['class']])

    hv = s.homeVideoContent()
    print('home videos:', len(hv['list']))
    if hv['list']:
        print('  样例:', hv['list'][0]['vod_name'],
              '| 备注:', hv['list'][0]['vod_remarks'])

    cat = s.categoryContent('国产剧', '1')
    print('category videos:', len(cat['list']))
    if cat['list']:
        print('  样例:', cat['list'][0]['vod_name'])
        detail = s.detailContent([cat['list'][0]['vod_id']])
        d = detail['list'][0]
        print('  detail:', d['vod_name'], '| 年份:', d['vod_year'],
              '| 类型:', d['type_name'], '| 集数:', d['vod_play_url'].count('#') + 1)
