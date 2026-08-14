#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVBox 数据源：橘子动漫 www.mgnacg.com

站点特性：
- MacCms 模板，分类/搜索页内容全部 AJAX 异步加载
- 播放地址通过 player_aaaa（encrypt=2）加密，由解析服务器 play.mknacg.top:8585 解码
- 支持多线路：云端 / 新番 / Mahoo / 存储 / CDN

可用数据源：
- 首页 / → 133 条 public-list-exp（所有类型混合）
- 排行榜 /label/rank/ → 40 条静态条目
- RSS /rss.xml → 30 条最新更新

分类策略：
- 首页推荐、连载中、已完结、排行榜 → 本地数据
- 最新更新 → RSS 解析
- 动漫/剧场版/7月新番等 → 使用首页数据（分类页为纯 AJAX，无静态内容）

播放策略（关键）：
- 直接返回 bangumi 页面 URL + parse=1
- TVBox 在设备端打开 WebView，JS 实时获取加密 token 并调用解析服务
- 比预先提取加密 URL 更可靠（避免 token 过期 / 解析服务不稳定问题）
"""

import json
import re
import requests
import sys

# TVBox 框架会注入这些模块
sys.path.append('..')
try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider:
        pass


# ==================== 分类与筛选配置 ====================

_CLASSES = [
    {'type_id': 'home',     'type_name': '首页推荐'},
    {'type_id': 'new',      'type_name': '最新更新'},
    {'type_id': 'rank',     'type_name': '排行榜'},
    {'type_id': 'serial',   'type_name': '连载中'},
    {'type_id': 'complete', 'type_name': '已完结'},
    {'type_id': 'anime',    'type_name': '动漫'},
    {'type_id': 'movie',    'type_name': '剧场版'},
    {'type_id': 'special',  'type_name': '迷之花园'},
    {'type_id': 'july',     'type_name': '7月新番'},
    {'type_id': 'jan',      'type_name': '1月新番'},
    {'type_id': 'april',    'type_name': '4月新番'},
    {'type_id': 'oct',      'type_name': '10月新番'},
    {'type_id': 'bd',       'type_name': 'BD动漫'},
]

# 首页可筛选的分类（使用 homepage 数据做客户端过滤）
_HOME_FILTERS = {
    'home': [
        {
            'key': 'status',
            'name': '状态',
            'value': [
                {'n': '全部', 'v': ''},
                {'n': '连载中', 'v': 'serial'},
                {'n': '已完结', 'v': 'complete'},
            ],
        },
        {
            'key': 'order',
            'name': '排序',
            'value': [
                {'n': '默认', 'v': ''},
                {'n': '最新', 'v': 'new'},
                {'n': '排行', 'v': 'rank'},
            ],
        },
    ],
    'anime':    [{'key': 'status', 'name': '状态', 'value': [{'n': '全部', 'v': ''}, {'n': '连载中', 'v': 'serial'}, {'n': '已完结', 'v': 'complete'}]}],
    'movie':    [{'key': 'status', 'name': '状态', 'value': [{'n': '全部', 'v': ''}, {'n': '连载中', 'v': 'serial'}, {'n': '已完结', 'v': 'complete'}]}],
    'serial':   [],
    'complete': [],
    'rank':     [],
    'new':      [],
    'july':     [],
    'jan':      [],
    'april':    [],
    'oct':      [],
    'bd':       [],
    'special':  [],
}


class Spider(BaseSpider):
    def __init__(self):
        super().__init__()
        self.host = 'https://www.mgnacg.com'
        self.header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': self.host + '/',
        }
        # 内存缓存：首页数据（同一进程内复用，避免重复抓取）
        self._home_cache = None

    def init(self, extend):
        self.extend = extend if isinstance(extend, str) else ''

    # ==================== TVBox 接口 ====================

    def homeContent(self, filter):
        return {'class': _CLASSES, 'filters': _HOME_FILTERS}

    def homeVideoContent(self):
        """首页推荐：返回前 30 条"""
        return {'list': self._get_home_items()[:30]}

    def categoryContent(self, tid, pg, filter, extend):
        """
        分类内容
        - rank / new  → 专用数据源
        - 其余分类     → 首页 133 条，按状态客户端过滤后分页
        """
        pg = max(1, int(pg or 1))

        # ---- 排行榜 ----
        if tid == 'rank':
            html = self._fetch_html('/label/rank/')
            return self._parse_rank_page(html, pg)

        # ---- 最新更新（RSS）----
        if tid == 'new':
            html = self._fetch_html('/rss.xml')
            items = self._parse_rss(html)
            return self._page_list(items, pg)

        # ---- 其余分类：使用首页数据 + 本地过滤 ----
        items = self._get_home_items()

        # 解析 extend / filter 参数
        try:
            ext = json.loads(extend) if extend and extend.strip() else {}
        except Exception:
            ext = {}

        status = ext.get('status', '')
        order  = ext.get('order', '')

        # 状态过滤
        if tid == 'serial' or status == 'serial':
            items = [v for v in items if '完结' not in v.get('vod_remarks', '')]
        elif tid == 'complete' or status == 'complete':
            items = [v for v in items if '完结' in v.get('vod_remarks', '')]

        # 排序
        if order == 'new':
            # 已是时间倒序（首页就是按更新时间排的），不需要改变
            pass
        elif order == 'rank':
            html = self._fetch_html('/label/rank/')
            rank_items = self._parse_rank_page(html, 1)['list']
            # 把排行里有的提前，其余附在后面
            rank_ids = {v['vod_id'] for v in rank_items}
            front = [v for v in items if v['vod_id'] in rank_ids]
            back  = [v for v in items if v['vod_id'] not in rank_ids]
            items = front + back

        return self._page_list(items, pg)

    def detailContent(self, ids):
        """详情页：提取封面、简介、所有线路剧集"""
        vod_id = ids[0] if isinstance(ids, list) else str(ids)
        # 标准化为 /media/ID/
        if vod_id.startswith('/media/'):
            path = vod_id.split('?')[0].rstrip('/') + '/'
        elif vod_id.isdigit():
            path = '/media/%s/' % vod_id
        else:
            digits = re.sub(r'\D', '', vod_id)
            path = '/media/%s/' % digits if digits else '/media/%s/' % vod_id

        html = self._fetch_html(path)
        if not html:
            return {'list': []}

        # 标题
        vod_name = ''
        title_m = re.search(r'<title>(.*?)</title>', html, re.S)
        if title_m:
            title = title_m.group(1).strip()
            m = re.search(r'《([^》]+)》', title)
            if m:
                vod_name = m.group(1)
            else:
                vod_name = title.split('动漫')[0].split('在线')[0].strip()
        if not vod_name:
            meta = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html)
            if meta:
                vod_name = meta.group(1).split('剧情介绍')[0].strip()

        # 封面
        vod_pic = ''
        pic_m = re.search(r'<img[^>]+alt="[^"]*海报图片"[^>]*src="([^"]+)"', html, re.S)
        if pic_m:
            vod_pic = self._wrap_pic(pic_m.group(1))
        if not vod_pic:
            pic_m = re.search(r'<img[^>]+data-src="([^"]+)"[^>]+alt="[^"]*海报图片"', html, re.S)
            if pic_m:
                vod_pic = self._wrap_pic(pic_m.group(1))
        if not vod_pic:
            pic_m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, re.S)
            if pic_m:
                vod_pic = self._wrap_pic(pic_m.group(1))

        # 简介
        content = ''
        intro_m = re.search(r'剧情介绍[：:]\s*(.*?)</div>', html, re.S)
        if intro_m:
            content = re.sub(r'<[^>]+>', ' ', intro_m.group(1)).strip()
            content = re.sub(r'\s{2,}', ' ', content)
        if not content:
            meta = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html)
            if meta:
                content = meta.group(1).split('剧情介绍：')[-1].strip()

        # 线路与剧集
        play_from = []
        play_url = []
        # 提取所有播放链接（兼容多种容器结构）
        boxes = re.findall(r'<div class="anthology-list-box[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.S)
        if not boxes:
            boxes = re.findall(r'<ul class="anthology-list-play[^"]*"[^>]*>(.*?)</ul>', html, re.S)
        line_names = []
        for m in re.finditer(r'<a class="swiper-slide"[^>]*>(.*?)</a>', html, re.S):
            txt = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if txt:
                # 去掉数字 badge
                txt = re.sub(r'\d+\s*$', '', txt).strip()
                if txt:
                    line_names.append(txt)
        for idx, box in enumerate(boxes):
            links = re.findall(r'href="(/bangumi/[^"]+)"[^>]*>([^<]+)</a>', box)
            if not links:
                continue
            name = line_names[idx] if idx < len(line_names) else f'线路{idx+1}'
            # 清理名字
            name = re.sub(r'[\s\u00a0]+', ' ', name).strip()
            if name.startswith('&nbsp;'):
                name = name.replace('&nbsp;', '').strip()
            # 若名字为空，尝试从 class 或默认
            if not name:
                name = f'线路{idx+1}'
            # 过滤已下线
            if '已下线' in name or '本地' in name:
                continue
            episodes = []
            for href, txt in links:
                txt = re.sub(r'<[^>]+>', '', txt).strip()
                episodes.append('%s$%s' % (txt, href))
            if episodes:
                play_from.append(name)
                play_url.append('#'.join(episodes))

        if not play_from:
            # 兜底：只返回页面链接
            play_from = ['橘子动漫']
            play_url = ['查看$%s' % path]

        vod = {
            'vod_id': vod_id,
            'vod_name': vod_name,
            'vod_pic': vod_pic,
            'vod_content': content,
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url),
        }
        return {'list': [vod]}

    def playerContent(self, flag, id, vipFlags):
        """
        播放内容（核心修复）

        问题根因：
          旧逻辑先 fetch bangumi 页面，提取 player_aaaa 加密 URL，再拼接
          https://play.mknacg.top:8585/xxx/?url={encrypted} 返回给 TVBox。
          但该加密 token 是一次性/有时效的 session 令牌，当 TVBox 实际播放时
          已经失效，且 8585 端口本身不稳定，导致每次都播放失败。

        修复方案：
          直接返回 bangumi 页面 URL + parse=1。
          TVBox 在用户设备上通过 WebView 实时加载该页面，
          JavaScript 会自动获取最新 token 并调用解析服务，
          完全绕开预取 token 失效的问题。
        """
        try:
            # 构造完整 bangumi URL
            if id.startswith('http'):
                play_url = id
            elif id.startswith('/'):
                play_url = self.host + id
            else:
                play_url = self.host + '/' + id

            return {
                'parse': 1,
                'url': play_url,
                'header': json.dumps({
                    'User-Agent': self.header['User-Agent'],
                    'Referer': self.host + '/',
                }),
            }
        except Exception:
            return {'parse': 1, 'url': str(id), 'header': json.dumps({'User-Agent': self.header['User-Agent']})}

    def searchContent(self, key, quick, pg=1):
        """搜索：该站需要验证码，暂不支持"""
        return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 0, 'total': 0}

    def searchContentPage(self, key, quick, pg):
        return self.searchContent(key, quick, pg)

    def isVideoFormat(self, url):
        return any(x in url for x in ['.m3u8', '.mp4', '.flv', '.avi', '.mkv'])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self._home_cache = None

    # ==================== 数据获取 ====================

    def _get_home_items(self):
        """获取首页全部 133 条数据（进程内缓存，避免重复 HTTP 请求）"""
        if self._home_cache is None:
            html = self._fetch_html('/')
            self._home_cache = self._parse_public_list(html)
        return self._home_cache

    def _fetch_html(self, path, timeout=15):
        url = path if path.startswith('http') else self.host + path
        try:
            r = requests.get(url, headers=self.header, timeout=timeout)
            text = r.text if hasattr(r, 'text') else r.content.decode('utf-8', errors='ignore')
            if r.status_code == 200:
                return text
            # 重试一次
            r = requests.get(url, headers=self.header, timeout=timeout)
            return r.text if hasattr(r, 'text') else r.content.decode('utf-8', errors='ignore')
        except Exception:
            try:
                r = requests.get(url, headers=self.header, timeout=timeout)
                return r.text if hasattr(r, 'text') else r.content.decode('utf-8', errors='ignore')
            except Exception:
                return ''

    def _wrap_pic(self, pic_url):
        if not pic_url:
            return ''
        pic_url = pic_url.strip()
        if pic_url.startswith('//'):
            return 'https:' + pic_url
        if pic_url.startswith(('http://', 'https://')):
            return pic_url
        if pic_url.startswith('/'):
            return self.host + pic_url
        return self.host + '/' + pic_url

    def _parse_public_list(self, html):
        """解析首页 / 普通列表中的 public-list-exp 条目"""
        items = []
        for m in re.finditer(
            r'<a[^>]+class="public-list-exp"[^>]+href="(/media/\d+/)"[^>]+title="([^"]+)"[^>]*>(.*?)</a>',
            html, re.S
        ):
            href = m.group(1)
            title = m.group(2).strip()
            inner = m.group(3)
            img = re.search(r'data-src="([^"]+)"', inner)
            note = re.search(r'class="public-list-prb[^"]*"[^>]*>([^<]+)', inner)
            items.append({
                'vod_id': href,
                'vod_name': title,
                'vod_pic': self._wrap_pic(img.group(1)) if img else '',
                'vod_remarks': note.group(1).strip() if note else '',
                'vod_url': href,
            })
        return items

    def _parse_rank_page(self, html, pg):
        """解析排行榜页（/label/rank/）静态条目"""
        items = []
        for m in re.finditer(
            r'class="vod-rank-vod flex-public"[^>]*href="(/media/\d+/)"[^>]*title="([^"]+)"[^>]*>(.*?)</a>',
            html, re.S
        ):
            href  = m.group(1)
            title = m.group(2).strip()
            inner = m.group(3)
            img   = re.search(r'data-src="([^"]+)"', inner)
            note  = re.search(r'class="vod-rank-state[^"]*"[^>]*>([^<]+)', inner)
            items.append({
                'vod_id':      href,
                'vod_name':    title,
                'vod_pic':     self._wrap_pic(img.group(1)) if img else '',
                'vod_remarks': note.group(1).strip() if note else '',
                'vod_url':     href,
            })
        return self._page_list(items, pg)

    def _parse_rss(self, xml):
        """解析 RSS /rss.xml 返回视频列表"""
        items = []
        for m in re.finditer(r'<item>(.*?)</item>', xml, re.S):
            block = m.group(1)
            title = re.search(r'<title><!\[CDATA\[([^\]]+)\]\]></title>|<title>([^<]+)</title>', block)
            link  = re.search(r'<link>([^<]+)</link>', block)
            img   = re.search(r'<image>([^<]+)</image>|<enclosure[^>]+url="([^"]+)"', block)
            desc  = re.search(r'<description><!\[CDATA\[([^\]]+)\]\]></description>|<description>([^<]+)</description>', block)
            if not (title and link):
                continue
            t = (title.group(1) or title.group(2) or '').strip()
            l = link.group(1).strip()
            # 转换为 /media/ID/ 格式
            vid = re.search(r'/media/(\d+)/', l)
            vod_id = f'/media/{vid.group(1)}/' if vid else l
            pic = ''
            if img:
                pic = self._wrap_pic(img.group(1) or img.group(2) or '')
            remark = ''
            if desc:
                d = (desc.group(1) or desc.group(2) or '').strip()
                remark = re.sub(r'<[^>]+>', '', d)[:20]
            items.append({
                'vod_id':      vod_id,
                'vod_name':    t,
                'vod_pic':     pic,
                'vod_remarks': remark,
                'vod_url':     vod_id,
            })
        return items

    def _page_list(self, items, pg):
        pg = int(pg or 1)
        limit = 30
        start = (pg - 1) * limit
        end = start + limit
        page_items = items[start:end]
        total = len(items)
        pagecount = (total + limit - 1) // limit
        return {
            'list': page_items,
            'page': pg,
            'pagecount': pagecount,
            'limit': len(page_items),
            'total': total,
        }



# ==================== 本地测试 ====================

if __name__ == '__main__':
    s = Spider()

    print('=== homeContent 分类列表 ===')
    hc = s.homeContent(True)
    print('分类数:', len(hc['class']))
    for c in hc['class']:
        print(' ', c['type_name'], '->', c['type_id'])
    print('筛选配置:', list(hc['filters'].keys()))

    print('\n=== homeVideoContent 首页推荐 ===')
    home = s.homeVideoContent()
    print('items:', len(home['list']))
    for it in home['list'][:3]:
        print(' ', it['vod_name'], '|', it['vod_remarks'])

    print('\n=== categoryContent: 最新更新(RSS) ===')
    cat_new = s.categoryContent('new', '1', '', '{}')
    print('items:', len(cat_new['list']), '/ total:', cat_new['total'])
    for it in cat_new['list'][:3]:
        print(' ', it['vod_name'])

    print('\n=== categoryContent: 排行榜 ===')
    cat_rank = s.categoryContent('rank', '1', '', '{}')
    print('items:', len(cat_rank['list']), '/ total:', cat_rank['total'])
    for it in cat_rank['list'][:3]:
        print(' ', it['vod_name'], '|', it['vod_remarks'])

    print('\n=== categoryContent: 连载中 ===')
    cat_serial = s.categoryContent('serial', '1', '', '{}')
    print('items:', len(cat_serial['list']), '/ total:', cat_serial['total'])
    for it in cat_serial['list'][:3]:
        print(' ', it['vod_name'], '|', it['vod_remarks'])

    print('\n=== categoryContent: 已完结 ===')
    cat_done = s.categoryContent('complete', '1', '', '{}')
    print('items:', len(cat_done['list']), '/ total:', cat_done['total'])
    for it in cat_done['list'][:3]:
        print(' ', it['vod_name'], '|', it['vod_remarks'])

    print('\n=== categoryContent: 首页推荐 p2 ===')
    cat_p2 = s.categoryContent('home', '2', '', '{}')
    print('page:', cat_p2['page'], '/', cat_p2['pagecount'], '  items:', len(cat_p2['list']))

    print('\n=== categoryContent: 首页推荐 状态=已完结 (extend filter) ===')
    cat_f = s.categoryContent('home', '1', '', '{"status":"complete"}')
    print('items:', len(cat_f['list']), '/ total:', cat_f['total'])

    print('\n=== detailContent ===')
    det = s.detailContent(['/media/1619/'])
    if det['list']:
        v = det['list'][0]
        print('title:', v['vod_name'])
        print('pic:', v['vod_pic'])
        print('from:', v['vod_play_from'])
        eps = v['vod_play_url'].split('$$$')[0]
        print('eps(line1 first 3):', eps[:120])

    print('\n=== playerContent（修复后：直接返回 bangumi URL） ===')
    for bangumi in ['/bangumi/1619-2-2/', '/bangumi/928-2-1/', '/bangumi/1619-3-5/']:
        play = s.playerContent('云端线路', bangumi, [])
        print(f'  {bangumi} -> parse={play["parse"]} url={play["url"]}')
