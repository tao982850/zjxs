# -*- coding: utf-8 -*-
# !/usr/bin/python
"""
极速追剧 (jisuzhuiju.com) —— TVBox Python 源

由 drpy-node 版《极速追剧.js》转换而来（2026-09-22 建源）

建源依据：
  · 纯 HTML 站；首页 5 个分区
  · 列表卡片：a[/detail/<id>.html] > div.vod-card > img + p.vod-title + p.vod-subtitle
  · 一级分类：/type/dianshiju.html、/type/dianying.html、/type/dongman.html、/type/zongyi.html
    **站点无分页** → 第 2 页起返回空，避免重复刷条
  · 详情 /detail/<id>.html：h1=名称、og:image=封面、meta description=简介、
    span.meta-value 依次为 主演/导演/地区/语言/年份/更新/备注
  · 播放线路：div.source-tabs>button（名称）+ div.source-panel>a.episode-btn
  · 取流：GET /api/play-url?vodId=<id>&playFrom=<from>&index=<n>
         → {"mode":"native","code":200,"url":"<m3u8>"}
  · ⚠ 直链 CDN 只认国内 IP，parse 保持 0 交给播放器，
    **不要开"服务器代理播放"**（会走海外出口 → 403/空白）
  · 搜索：/search?wd=<关键词>

自测：
  python 极速追剧.py
"""

import json
import re
import sys
import time

import requests

sys.path.append('..')
try:
    from base.spider import Spider as _BaseSpider
except Exception:
    class _BaseSpider(object):
        pass


# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
HOST = 'https://jisuzhuiju.com'
SRC = '极速追剧'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')

HEADERS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': HOST + '/',
}

# 一级分类（取自站点导航）
CLASSES = [
    {'type_id': 'dianshiju', 'type_name': '电视剧'},
    {'type_id': 'dianying', 'type_name': '电影'},
    {'type_id': 'dongman', 'type_name': '动漫'},
    {'type_id': 'zongyi', 'type_name': '综艺'},
]

# 线路键 → 站点显示名
SOURCE_NAMES = {
    'qq': '腾讯官方线路',
    'jsm3u8': '自建线路',
    'bfzym3u8': '普通线路二',
    'co': '普通线路一',
}

# 正则
_RE_CARD = re.compile(r'<a\b[^>]*href="(/detail/(\d+)\.html)"[^>]*>(.*?)</a>', re.S | re.I)
_RE_TITLE = re.compile(r'<p\b[^>]*class="[^"]*vod-title[^"]*"[^>]*>(.*?)</p>', re.S | re.I)
_RE_SUB = re.compile(r'<p\b[^>]*class="[^"]*vod-subtitle[^"]*"[^>]*>(.*?)</p>', re.S | re.I)
_RE_IMG_ALT = re.compile(r'<img\b[^>]*alt="([^"]*)"', re.S | re.I)
_RE_IMG_DATA = re.compile(r'<img\b[^>]*data-src="([^"]+)"', re.S | re.I)
_RE_IMG_SRC = re.compile(r'<img\b[^>]*src="([^"]+)"', re.S | re.I)
_RE_EP = re.compile(r'/vodplay/(\d+)-([A-Za-z0-9_]+)-(\d+)\.html')
_RE_H1 = re.compile(r'<h1\b[^>]*>(.*?)</h1>', re.S | re.I)
_RE_OG_IMAGE = re.compile(
    r'<meta\b[^>]*(?:property|name)=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', re.S | re.I)
_RE_OG_IMAGE2 = re.compile(
    r'<meta\b[^>]*content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']og:image["\']', re.S | re.I)
_RE_DESC = re.compile(
    r'<meta\b[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']', re.S | re.I)
_RE_DESC2 = re.compile(
    r'<meta\b[^>]*content=["\']([^"\']*)["\'][^>]*name=["\']description["\']', re.S | re.I)
_RE_META_VALUE = re.compile(
    r'<span\b[^>]*class="[^"]*meta-value[^"]*"[^>]*>(.*?)</span>', re.S | re.I)


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def fix_url(u):
    u = str(u if u is not None else '').strip()
    if not u:
        return ''
    if u.startswith('//'):
        return 'https:' + u
    if re.match(r'^https?://', u, re.I):
        return u
    return HOST + ('' if u.startswith('/') else '/') + u


def strip_tags(s):
    s = str(s if s is not None else '')
    s = re.sub(r'<[^>]+>', '', s)
    s = (s.replace('&nbsp;', ' ')
          .replace('&amp;', '&')
          .replace('&lt;', '<')
          .replace('&gt;', '>')
          .replace('&quot;', '"')
          .replace('&#39;', "'")
          .replace('&ldquo;', '“')
          .replace('&rdquo;', '”'))
    return re.sub(r'\s+', ' ', s).strip()


def meta_content(html, *pairs):
    """按 (属性名, 属性值) 顺序尝试多种写法取 meta content"""
    for prop, val in pairs:
        pat = (r'<meta\b[^>]*%s=["\']%s["\'][^>]*content=["\']([^"\']*)["\']'
               % (prop, re.escape(val)))
        m = re.search(pat, html, re.S | re.I)
        if m:
            return m.group(1)
        pat2 = (r'<meta\b[^>]*content=["\']([^"\']*)["\'][^>]*%s=["\']%s["\']'
                % (prop, re.escape(val)))
        m = re.search(pat2, html, re.S | re.I)
        if m:
            return m.group(1)
    return ''


# --------------------------------------------------------------------------- #
# Spider
# --------------------------------------------------------------------------- #
class Spider(_BaseSpider):

    def getName(self):
        return SRC

    def init(self, extend=''):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.extend = extend or ''

    def destroy(self):
        try:
            if getattr(self, 'session', None):
                self.session.close()
        except Exception:
            pass

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    # ------------------------------------------------------------------ #
    # 网络
    # ------------------------------------------------------------------ #
    def _sess(self):
        s = getattr(self, 'session', None)
        if s is None:
            s = requests.Session()
            s.headers.update(HEADERS)
            self.session = s
        return s

    def get_html(self, url, headers=None, retry=2):
        sess = self._sess()
        hd = dict(HEADERS)
        if headers:
            hd.update(headers)
        for i in range(retry):
            try:
                r = sess.get(url, headers=hd, timeout=15)
                txt = r.content.decode('utf-8', 'ignore') if r.content else ''
                if txt and len(txt) > 200:
                    return txt
            except Exception as e:
                print('[极速追剧] 取页失败 %s : %s' % (url, e))
            if i < retry - 1:
                time.sleep(0.3)
        return ''

    # ------------------------------------------------------------------ #
    # 列表解析（首页 / 一级 / 搜索 通用）
    # ------------------------------------------------------------------ #
    def parse_list(self, html):
        out = []
        seen = set()
        if not html:
            return out
        for m in _RE_CARD.finditer(html):
            try:
                vid = m.group(2)
                if not vid or vid in seen:
                    continue
                inner = m.group(3)

                tm = _RE_TITLE.search(inner)
                name = strip_tags(tm.group(1)) if tm else ''
                if not name:
                    am = _RE_IMG_ALT.search(inner)
                    name = strip_tags(am.group(1)) if am else ''
                    name = re.sub(r'(封面|海报)图片$', '', name)
                if not name:
                    continue

                pm = _RE_IMG_DATA.search(inner)
                if not pm:
                    pm = _RE_IMG_SRC.search(inner)
                pic = pm.group(1) if pm else ''

                sm = _RE_SUB.search(inner)
                remarks = strip_tags(sm.group(1)) if sm else ''

                seen.add(vid)
                out.append({
                    'vod_id': vid,
                    'vod_name': name,
                    'vod_pic': fix_url(pic),
                    'vod_remarks': remarks,
                })
            except Exception:
                continue
        print('[极速追剧] 列表解析：%d 条' % len(out))
        return out

    # ------------------------------------------------------------------ #
    # 首页
    # ------------------------------------------------------------------ #
    def homeContent(self, filter):
        return {'class': CLASSES, 'filters': {}}

    def homeVideoContent(self):
        html = self.get_html(HOST + '/')
        return {'list': self.parse_list(html)[:60]}

    # ------------------------------------------------------------------ #
    # 分类
    # ------------------------------------------------------------------ #
    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1

        result = {'list': [], 'page': pg, 'pagecount': 1, 'limit': 90, 'total': 0}

        # 站点没有分页控件（?page=N 无效）→ 第 2 页起直接返回空
        if pg > 1:
            return result

        if isinstance(extend, str):
            try:
                extend = json.loads(extend)
            except Exception:
                extend = {}
        extend = extend or {}

        tid2 = extend.get('class') or tid or 'dianshiju'
        html = self.get_html('%s/type/%s.html' % (HOST, tid2))
        items = self.parse_list(html)
        result['list'] = items
        result['total'] = len(items)
        return result

    # ------------------------------------------------------------------ #
    # 详情
    # ------------------------------------------------------------------ #
    def detailContent(self, array):
        vid = ''
        try:
            vid = str(array[0]) if isinstance(array, (list, tuple)) else str(array)
        except Exception:
            vid = ''
        vid = vid.strip()

        html = self.get_html('%s/detail/%s.html' % (HOST, vid))

        vod = {
            'vod_id': vid,
            'vod_name': '',
            'vod_pic': '',
            'vod_content': '',
            'vod_remarks': '',
            'vod_play_from': SRC,
            'vod_play_url': '',
        }

        try:
            m = _RE_H1.search(html)
            if m:
                vod['vod_name'] = strip_tags(m.group(1))

            pic = meta_content(html, ('property', 'og:image'), ('name', 'og:image'))
            if not pic:
                m = re.search(
                    r'<div\b[^>]*class="[^"]*detail-poster-wrapper[^"]*"[^>]*>.*?<img\b[^>]*src="([^"]+)"',
                    html, re.S | re.I)
                if m:
                    pic = m.group(1)
            vod['vod_pic'] = fix_url(pic)

            vod['vod_content'] = strip_tags(meta_content(html, ('name', 'description')))

            # 详情页顺序：主演 / 导演 / 地区 / 语言 / 年份 / 更新 / 备注
            metas = [strip_tags(x.group(1)) for x in _RE_META_VALUE.finditer(html)]
            if len(metas) > 0:
                vod['vod_actor'] = metas[0]
            if len(metas) > 1:
                vod['vod_director'] = metas[1]
            if len(metas) > 2:
                vod['vod_area'] = metas[2]
            if len(metas) > 4:
                vod['vod_year'] = metas[4]
            if len(metas) > 5 and metas[5]:
                vod['vod_remarks'] = metas[5]
            if len(metas) > 6 and metas[6]:
                vod['vod_remarks'] = metas[6]
        except Exception as e:
            print('[极速追剧] 二级字段解析异常: %s' % e)

        # -------------------- 播放线路 -------------------- #
        try:
            froms, urls = [], []

            # 线路名（button 文本）
            tabs = []
            m = re.search(
                r'<div\b[^>]*class="[^"]*source-tabs[^"]*"[^>]*>(.*?)</div>', html, re.S | re.I)
            if m:
                tabs = [strip_tags(x) for x in
                        re.findall(r'<button\b[^>]*>(.*?)</button>', m.group(1), re.S | re.I)]

            # 分集面板（按 source-panel 切段）
            parts = re.split(r'<div\b[^>]*class="[^"]*source-panel[^"]*"', html, flags=re.I)[1:]

            for i, part in enumerate(parts):
                name = tabs[i] if i < len(tabs) and tabs[i] else ('线路%d' % (i + 1))
                eps = []
                for a in re.finditer(
                        r'<a\b([^>]*class="[^"]*episode-btn[^"]*"[^>]*)>(.*?)</a>',
                        part, re.S | re.I):
                    attrs, body = a.group(1), a.group(2)
                    hm = re.search(r'href="([^"]+)"', attrs, re.I)
                    if not hm:
                        continue
                    href = hm.group(1)
                    ep = _RE_EP.search(href)
                    if not ep:
                        continue
                    text = strip_tags(body) or ('第%d集' % (len(eps) + 1))
                    eps.append('%s$%s' % (text, fix_url(href)))
                if eps:
                    froms.append(name)
                    urls.append('#'.join(eps))

            if urls:
                vod['vod_play_from'] = '$$$'.join(froms)
                vod['vod_play_url'] = '$$$'.join(urls)
            else:
                print('[极速追剧] 未解析到播放线路: %s/detail/%s.html' % (HOST, vid))
        except Exception as e:
            print('[极速追剧] 播放线路解析异常: %s' % e)

        return {'list': [vod]}

    # ------------------------------------------------------------------ #
    # 搜索
    # ------------------------------------------------------------------ #
    def searchContent(self, key, quick, pg='1'):
        kw = (key or '').strip()
        if not kw:
            return {'list': []}
        url = HOST + '/search?wd=' + requests.utils.quote(kw, safe='')
        html = self.get_html(url)
        return {'list': self.parse_list(html)[:40]}

    # ------------------------------------------------------------------ #
    # 播放
    # ------------------------------------------------------------------ #
    def playerContent(self, flag, id, vipFlags):
        raw = str(id if id is not None else '')

        # 已是直链：直接交给播放器
        if re.match(r'^https?://', raw, re.I) and '/vodplay/' not in raw:
            return {'parse': 0, 'url': raw}

        ep = _RE_EP.search(raw)
        if not ep:
            return {'parse': 1, 'url': fix_url(raw)}

        vid, pf, idx = ep.group(1), ep.group(2), ep.group(3)
        page_url = '%s/vodplay/%s-%s-%s.html' % (HOST, vid, pf, idx)
        api = ('%s/api/play-url?vodId=%s&playFrom=%s&index=%s'
               % (HOST, vid, pf, idx))

        try:
            r = self._sess().get(
                api,
                headers={
                    'User-Agent': UA,
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'zh-CN,zh;q=0.9',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Referer': page_url,
                },
                timeout=15,
            )
            txt = r.content.decode('utf-8', 'ignore') if r.content else ''
            j = json.loads(txt)
            if j and j.get('code') == 200 and j.get('url'):
                line = SOURCE_NAMES.get(pf, pf)
                print('[极速追剧] 解析到直链<%s 第%s集>: %s' % (line, idx, str(j['url'])[:80]))
                return {
                    'parse': 0,
                    'url': j['url'],
                    'header': json.dumps({
                        'User-Agent': UA,
                        'Referer': HOST + '/',
                    }),
                }
            print('[极速追剧] play-url 无地址(%s): %s' % (api, txt[:120]))
        except Exception as e:
            print('[极速追剧] play-url 异常(%s): %s' % (api, e))

        # 兜底：把播放页交给客户端嗅探
        return {'parse': 1, 'url': page_url}


# --------------------------------------------------------------------------- #
# 本地自测
# --------------------------------------------------------------------------- #
if __name__ == '__main__':
    s = Spider()
    s.init('')

    print('--- 分类 ---')
    for c in s.homeContent(False)['class']:
        print(c)

    print('--- 首页 ---')
    for v in s.homeVideoContent()['list'][:5]:
        print(v)

    print('--- 一级(dianshiju) ---')
    for v in s.categoryContent('dianshiju', 1, False, {})['list'][:5]:
        print(v)

    print('--- 搜索(交锋) ---')
    for v in s.searchContent('交锋', False, '1')['list'][:5]:
        print(v)

    print('--- 详情(578) ---')
    d = s.detailContent(['578'])['list'][0]
    print('名称:', d.get('vod_name'))
    print('封面:', d.get('vod_pic'))
    print('备注:', d.get('vod_remarks'))
    print('线路:', d.get('vod_play_from'))
    print('播放:', str(d.get('vod_play_url'))[:200])

    print('--- 播放(/vodplay/578-bfzym3u8-1.html) ---')
    print(s.playerContent('普通线路二', '/vodplay/578-bfzym3u8-1.html', 0))