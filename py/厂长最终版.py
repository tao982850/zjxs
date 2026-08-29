#!/usr/bin/env python3
# coding=utf-8
# !/usr/bin/python
"""
厂长资源 (4kcz.com) —— TVBox / 影视仓 Python 爬虫 (T4 py)
功能  : 首页推荐 / 分类浏览+翻页 / 搜索 / 详情选集 / 播放解析(m3u8)
依赖  : 无第三方强依赖(有 requests 用 requests, 否则回退 urllib)
修复  : 2026-08 兼容性修复版
  1. 所有核心方法增加 try/except 防崩溃
  2. 新增 searchContentPage，兼容 FongMi/OK 影视等需要分页搜索的壳子
  3. homeContent 同时返回 filter/filters 两种键名
  4. localProxy/destroy/isVideoFormat/manualVideoCheck 按 TVBox 标准接口修正
  5. detailContent 安全处理空 ids / categoryContent 安全处理 extend=None
  6. playerContent header 统一 JSON 字符串化，提升播放器兼容性
  7. homeVideoContent 独立容错，不再强依赖 categoryContent 成功
"""

import base64
import json
import re
import sys
import time
import urllib.parse

sys.path.append('..')

# ---- TVBox 运行环境提供 base.spider; 本地调试时降级为空基类 ----
try:
    from base.spider import Spider as _BaseSpider
except Exception:
    class _BaseSpider(object):
        pass

try:
    import requests
    HAS_REQUESTS = True
except Exception:
    HAS_REQUESTS = False

DEFAULT_SITE = 'https://www.4kcz.com'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


class Spider(_BaseSpider):
    # ==================== 生命周期 ====================
    def init(self, extend=""):
        """extend 可传入新域名, 站点换域名时无需改代码"""
        self.site = DEFAULT_SITE
        try:
            if extend:
                ext = extend.strip()
                if ext.startswith('{'):
                    ext = json.loads(ext).get('site', '')
                if ext.startswith('http'):
                    self.site = ext.rstrip('/')
        except Exception:
            pass

    def getName(self):
        return '厂长资源'

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|mkv|flv|avi|ts)(\?|$)', str(url), re.I))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, param):
        return None

    # ==================== 网络 ====================
    def _site(self):
        return getattr(self, 'site', DEFAULT_SITE)

    def _headers(self, ref=None):
        return {
            'User-Agent': UA,
            'Referer': ref or (self._site() + '/'),
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def _session(self):
        """复用连接省去重复 TLS 握手"""
        if not HAS_REQUESTS:
            return None
        se = getattr(self, '_se', None)
        if se is None:
            try:
                se = requests.Session()
                ad = requests.adapters.HTTPAdapter(
                    pool_connections=4, pool_maxsize=8, max_retries=0)
                se.mount('https://', ad)
                se.mount('http://', ad)
            except Exception:
                se = requests
            self._se = se
        return se

    def _get(self, url, ref=None, timeout=None, retry=3):
        """
        取网页源码; 失败退避重试, 最终失败返回空串。
        超时用 (连接, 读取) 二元组: 连接超时短(死链快速失败), 读取超时放宽。
        """
        ct, rt = timeout or (8, 25)
        for i in range(max(1, retry)):
            try:
                if HAS_REQUESTS:
                    r = self._session().get(url, headers=self._headers(ref),
                                            timeout=(ct, rt), allow_redirects=True)
                    if r.status_code >= 500:
                        raise IOError('http %d' % r.status_code)
                    return r.content.decode('utf-8', 'ignore')
                import urllib.request
                req = urllib.request.Request(url, headers=self._headers(ref))
                return urllib.request.urlopen(req, timeout=rt).read().decode('utf-8', 'ignore')
            except Exception:
                if i + 1 < max(1, retry):
                    time.sleep(0.8 * (i + 1))
        return ''

    # ==================== 工具 ====================
    @staticmethod
    def _text(html):
        """去标签取纯文本"""
        t = re.sub(r'<[^>]+>', '', html or '')
        t = t.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
        t = t.replace('\u200b', '')
        return re.sub(r'\s+', ' ', t).strip()

    def _parse_list(self, html):
        """
        列表解析。先锁定结果容器 div.bt_img 内的 ul, 避免把侧栏推荐
        当成结果。容器找不到时回退为全页扫描。
        """
        if not html:
            return []

        block = ''
        m = re.search(r'<div[^>]*class="[^"]*bt_img[^"]*"[^>]*>', html)
        if m:
            u = re.search(r'<ul[^>]*>([\s\S]*?)</ul>', html[m.end():])
            if u:
                block = u.group(1)

        items = re.findall(r'<li[^>]*>([\s\S]*?)</li>', block) if block else []
        if not items:  # 回退: 全页粗扫
            items = [html[max(0, x.start() - 320): x.end() + 560]
                     for x in re.finditer(r'/movie/(\d+)\.html', html)]

        out, seen = [], set()
        for it in items:
            im = re.search(r'/movie/(\d+)\.html', it)
            if not im:
                continue
            vid = im.group(1)
            if vid in seen:
                continue

            nm = re.search(r'class="dytit"[^>]*>\s*<a[^>]*>([^<]+)</a>', it) \
                 or re.search(r'alt="([^"]+)"', it)
            name = self._text(nm.group(1)) if nm else ''
            if not name:
                continue
            # 过滤广告条目
            if name in ('CC',):
                continue

            pm = re.search(r'data-original="([^"]+)"', it) \
                 or re.search(r'<img[^>]*src="([^"]+)"', it)
            pic = pm.group(1) if pm else ''

            # 角标优先级: 集数(jidi) > 评分(rating) > 类型标签(furk/qb) > 主演
            remark = ''
            # jidi: <div class="jidi"><span>全16集</span></div>
            rm = re.search(r'class="jidi"[^>]*>\s*<span[^>]*>([^<]+)</span>', it)
            if rm:
                remark = self._text(rm.group(1))
            if not remark:
                # rating: <div class="rating">9.3</div>
                rm = re.search(r'class="rating"[^>]*>\s*([\d.]+)\s*<', it)
                if rm:
                    remark = '评分%s' % rm.group(1).strip()
            if not remark:
                # furk: <span class="furk">韩剧</span>
                rm = re.search(r'class="furk"[^>]*>([^<]+)</span>', it)
                if rm:
                    remark = self._text(rm.group(1))
            if not remark:
                # qb: <span class="qb">1080P</span>
                rm = re.search(r'class="qb"[^>]*>([^<]+)</span>', it)
                if rm:
                    remark = self._text(rm.group(1))
            if not remark:
                rm = re.search(r'class="inzhuy"[^>]*>([^<]*)<', it)
                if rm:
                    actors = self._text(rm.group(1)).replace('主演：', '').strip()
                    if actors and actors != 'false':
                        parts = [p for p in re.split(r'[,，、\s]+', actors) if p][:2]
                        remark = ' '.join(parts) + ('…' if len(parts) < len(
                            [p for p in re.split(r'[,，、\s]+', actors) if p]) else '')
            remark = remark.rstrip('：:')

            seen.add(vid)
            out.append({'vod_id': vid, 'vod_name': name,
                        'vod_pic': pic, 'vod_remarks': remark})
        return out

    # ==================== 筛选数据 ====================
    TAGS = [
        ('剧情', 'juqing'), ('动作', 'dozuo'), ('喜剧', 'xiju'), ('爱情', 'aiqing'),
        ('科幻', 'kh'), ('悬疑', 'xuanyi'), ('惊悚', 'kingsong'), ('恐怖', 'kubu'),
        ('犯罪', 'fanzui'), ('冒险', 'maoxian'), ('奇幻', 'qihuan'), ('动画', 'dhh'),
        ('动漫', 'doman'), ('战争', 'zhanzheng'), ('历史', 'lishi'), ('古装', 'guzhuang'),
        ('武侠', 'wuxia'), ('家庭', 'jiating'), ('传记', 'chuanji'), ('灾难', 'zainan'),
        ('运动', 'yd'), ('音乐', 'yy'), ('歌舞', 'gw'), ('西部', 'xb'),
        ('儿童', 'etet'), ('同性', 'tongxing'), ('情色', 'qingse'), ('真人秀', 'zrx'),
        ('纪录片', 'jlpp'), ('短片', 'dp'),
    ]
    VIEW_CATS = [
        ('动漫', 'fjj'), ('PV预告', 'pvyugao'),
        ('4K', '4k'), ('1080P', '1080p'), ('720P', '720p'), ('HD', 'hd'),
        ('IMAX', 'imax'), ('豆瓣Top250', 'douban250'),
        ('漫威宇宙', 'manweidianyingyuzhou'),
        ('星球大战', 'xingqiudazhanxilie'), ('周星驰', 'zhouxingchi'),
        ('剧场版', 'jcb'), ('国漫', 'gmm'), ('真人版', 'zrbb'),
        ('综艺', '%e7%bb%bc%e8%89%ba'), ('纪录片', 'jlpp'),
        ('短片', '%e7%9f%ad%e7%89%87'),
        ('网盘分享', '%e7%bd%91%e7%9b%98%e5%88%86%e4%ba%ab'),
        ('TS', 'ts'), ('TC', 'tc'),
    ]
    SERIES = [
        ('电影', 'dyy'), ('电视剧', 'dianshiju'),
        ('华语电影', 'huayudianying'), ('欧美电影', 'oumeidianying'),
        ('日本电影', 'ribendianying'),
        ('韩国电影', 'hanguodianying'), ('印度电影', 'yindudianying'),
        ('加拿大电影', 'jianadadianying'), ('俄罗斯电影', 'eluosidianying'),
        ('国产剧', 'guochanju'), ('美剧', 'mj'), ('韩剧', 'hj'), ('日剧', 'rj'),
        ('海外剧', 'hwj'), ('动画', 'dohua'),
    ]

    LIBS = {
        'movie_bt_tags': ('tag', TAGS),
        'movie_bt_view_cat': ('cat', VIEW_CATS),
        'movie_bt_series': ('ser', SERIES),
    }

    # ==================== 首页 ====================
    def homeContent(self, filter=False):
        try:
            cats = [
                {'type_id': 'movie_bt', 'type_name': '最近更新'},
                {'type_id': 'movie_bt_series', 'type_name': '剧集片库'},
                {'type_id': 'movie_bt_view_cat', 'type_name': '专题片库'},
                {'type_id': 'movie_bt_tags', 'type_name': '类型片库'},
                {'type_id': 'movie_bt_series/dyy', 'type_name': '电影'},
                {'type_id': 'movie_bt_series/guochanju', 'type_name': '国产剧'},
                {'type_id': 'movie_bt_series/mj', 'type_name': '美剧'},
                {'type_id': 'movie_bt_series/hj', 'type_name': '韩剧'},
                {'type_id': 'movie_bt_series/rj', 'type_name': '日剧'},
                {'type_id': 'movie_bt_series/hwj', 'type_name': '海外剧'},
                {'type_id': 'movie_bt_view_cat/fjj', 'type_name': '动漫'},
                {'type_id': 'movie_bt_view_cat/pvyugao', 'type_name': 'PV预告'},
                {'type_id': 'dbtop250', 'type_name': '豆瓣Top250'},
                {'type_id': 'zuixindianying', 'type_name': '最新电影'},
                {'type_id': 'dongmanjuchangban', 'type_name': '剧场版'},
                {'type_id': 'huayudianying', 'type_name': '华语电影'},
                {'type_id': 'oumeidianying', 'type_name': '欧美电影'},
                {'type_id': 'hanguodianying', 'type_name': '韩国电影'},
                {'type_id': 'ribendianying', 'type_name': '日本电影'},
                {'type_id': 'yindudianying', 'type_name': '印度电影'},
                {'type_id': 'gaofenyingshi', 'type_name': '高分影视'},
            ]

            filters = {}
            for tid, (key, opts) in self.LIBS.items():
                name = {'tag': '类型', 'cat': '专题', 'ser': '分类'}[key]
                filters[tid] = [{
                    'key': key,
                    'name': name,
                    'value': [{'n': n, 'v': v} for n, v in opts],
                }]

            # 同时返回 filter/filters 两种键名，兼容不同壳子
            return {'class': cats, 'filters': filters, 'filter': filters}
        except Exception:
            return {'class': [], 'filters': {}, 'filter': {}}

    def homeVideoContent(self):
        try:
            html = self._get('%s/movie_bt' % self._site())
            vod_list = self._parse_list(html)
            return {'list': vod_list}
        except Exception:
            return {'list': []}

    # ==================== 分类列表 ====================
    def categoryContent(self, tid, pg=1, filter=False, extend=""):
        try:
            try:
                pg = int(pg)
            except Exception:
                pg = 1
            if pg < 1:
                pg = 1

            tid = str(tid).strip('/')

            if extend is None:
                extend = {}
            elif isinstance(extend, str):
                try:
                    extend = json.loads(extend) if extend.strip() else {}
                except Exception:
                    extend = {}

            if tid in self.LIBS:
                key, opts = self.LIBS[tid]
                slug = ''
                if isinstance(extend, dict):
                    slug = str(extend.get(key, '') or '').strip()
                if not slug:
                    slug = opts[0][1]
                tid = '%s/%s' % (tid, slug)

            base = '%s/%s' % (self._site(), tid)
            url = base if pg == 1 else '%s/page/%d' % (base, pg)

            vod_list = self._parse_list(self._get(url))
            # 修复: 第一页不带斜杠可能被拦截, 尝试带斜杠
            if pg == 1 and not vod_list:
                vod_list = self._parse_list(self._get(base + '/'))
            pagecount = pg if not vod_list else 9999
            return {
                'list': vod_list,
                'page': pg,
                'pagecount': pagecount,
                'limit': 90,
                'total': 999999,
            }
        except Exception:
            return {
                'list': [],
                'page': 1,
                'pagecount': 1,
                'limit': 90,
                'total': 0,
            }

    # ==================== 详情 / 选集 ====================
    def detailContent(self, ids):
        try:
            vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
            vid = str(vid).strip()
            html = self._get('%s/movie/%s.html' % (self._site(), vid))
            if not html:
                return {'list': []}

            # 标题
            m = re.search(r'<div class="moviedteail_tt"><h1>([^<]+)</h1>', html) \
                or re.search(r'<title>《([^》]+)》', html) \
                or re.search(r'<title>([^<|_]+)', html)
            name = self._text(m.group(1)) if m else ''

            # 封面
            m = re.search(r'(?:property|name)="og:image"\s+content="([^"]+)"', html) \
                or re.search(r'data-original="([^"]+)"', html)
            pic = m.group(1) if m else ''

            # 简介
            m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html)
            content = m.group(1).strip() if m else ''

            # 元信息
            info = {}
            mb = re.search(r'<ul class="moviedteail_list">([\s\S]*?)</ul>', html)
            if mb:
                for li in re.findall(r'<li>([\s\S]*?)</li>', mb.group(1)):
                    t = self._text(li)
                    if '：' in t:
                        k, v = t.split('：', 1)
                        info[k.strip()] = v.strip()

            # 选集
            episodes = []
            seen = set()
            pairs = re.findall(
                r'<a[^>]*href="[^"]*?/v_play/([A-Za-z0-9+/=_-]+)\.html"[^>]*>([\s\S]*?)</a>', html)
            used = {}
            for code, txt in pairs:
                if code in seen:
                    continue
                seen.add(code)
                label = self._text(txt)
                if not label or '立即播放' in label or '播放' == label:
                    label = self._ep_label(code, len(episodes))
                label = label.replace('#', '').replace('$', '')
                used[label] = used.get(label, 0) + 1
                if used[label] > 1:
                    label = '%s%d' % (label, used[label])
                episodes.append('%s$%s' % (label, code))

            if not episodes:
                for code in re.findall(r'/v_play/([A-Za-z0-9+/=_-]+)\.html', html):
                    if code in seen:
                        continue
                    seen.add(code)
                    episodes.append('%s$%s' % (self._ep_label(code, len(episodes)), code))

            if not episodes and (not name or name in ('404', '页面未找到') or '404' in name):
                return {'list': []}

            # 豆瓣评分
            score = info.get('豆瓣', '')
            m = re.search(r'class="dbpingfen"[^>]*>\s*([\d.]+)\s*<', html)
            if m:
                score = m.group(1)
            score = score.strip() if score else ''
            if not re.match(r'^\d+(\.\d+)?$', score or ''):
                score = ''

            # 年份
            year = info.get('年份', '').strip()
            if not re.match(r'^\d{4}$', year):
                ym = re.search(r'(19\d{2}|20\d{2})', info.get('上映', '') or year)
                year = ym.group(1) if ym else year

            # 角标
            is_multi_ep = len(episodes) > 1 and any(
                re.search(r'第?\s*\d+\s*集|^\s*\d+\s*$|EP\s*\d+', e.split('$')[0], re.I)
                for e in episodes)
            if score:
                remarks = '豆瓣 %s' % score
            elif is_multi_ep:
                remarks = '共%d集' % len(episodes)
            else:
                remarks = info.get('上映', '')

            # 简介前置关键信息
            extra = []
            if score:
                extra.append('豆瓣评分 %s' % score)
            if info.get('时长'):
                extra.append('片长 %s' % info['时长'])
            if info.get('又名'):
                extra.append('又名: %s' % info['又名'])
            if extra:
                content = '【%s】%s' % (' / '.join(extra), content)

            vod = {
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': pic,
                'vod_year': year,
                'vod_area': info.get('地区', ''),
                'vod_lang': info.get('语言', ''),
                'vod_score': score,
                'vod_douban_score': score,
                'vod_remarks': remarks,
                'vod_duration': info.get('时长', ''),
                'type_name': info.get('类型', ''),
                'vod_actor': info.get('主演', ''),
                'vod_director': info.get('导演', ''),
                'vod_writer': info.get('编剧', ''),
                'vod_content': content,
                'vod_play_from': '厂长资源',
                'vod_play_url': '#'.join(episodes),
            }
            return {'list': [vod]}
        except Exception:
            return {'list': []}

    @staticmethod
    def _ep_label(code, idx):
        """从 base64 码 mv_{id}-nm_{集数} 还原集数标签"""
        try:
            pad = code + '=' * (-len(code) % 4)
            raw = base64.b64decode(pad).decode('utf-8', 'ignore')
            m = re.search(r'nm_(\d+)', raw)
            if m:
                return '第%s集' % m.group(1)
        except Exception:
            pass
        return '第%d集' % (idx + 1)

    # ==================== 搜索 ====================
    def searchContent(self, key, quick=False, pg="1"):
        """站点搜索为分词模糊匹配且不支持翻页, 这里按相关度重排, 精确匹配置顶"""
        try:
            key = str(key).strip()
            urls = [
                '%s/nimasile?q=%s' % (self._site(), urllib.parse.quote(key)),
                '%s/boss1O1?q=%s' % (self._site(), urllib.parse.quote(key)),
                '%s/?s=%s' % (self._site(), urllib.parse.quote(key)),
            ]
            vod_list = []
            for url in urls:
                vod_list = self._parse_list(self._get(url))
                if vod_list:
                    break

            def score(v):
                n = v.get('vod_name', '')
                if n == key:
                    return 0
                if key and key in n:
                    return 1
                if n and n in key:
                    return 2
                return 3

            vod_list.sort(key=score)
            return {'list': vod_list, 'page': 1, 'pagecount': 1,
                    'limit': 90, 'total': len(vod_list)}
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 1,
                    'limit': 90, 'total': 0}

    def searchContentPage(self, key, quick, pg="1"):
        """兼容需要分页搜索接口的壳子 (FongMi/OK影视等)"""
        return self.searchContent(key, quick, pg)

    # ==================== 播放解析 ====================
    def _play_header(self, url):
        """
        按视频分片所在 CDN 决定回传给播放器的请求头。
        实测: 站点把视频分片伪装成 .jpg 托管在第三方图床/网盘,
        这些图床对 Referer 敏感 —— 带 Referer 直接 403,
        只带 User-Agent 才能正常拉流。
        """
        h = {'User-Agent': UA}
        try:
            host = urllib.parse.urlparse(url).hostname or ''
        except Exception:
            host = ''
        if any(k in host for k in ('4kcz.com',)):
            h['Referer'] = self._site() + '/'
        return h

    def _pick_m3u8(self, page, base=''):
        """从播放器页面里挖真实播放地址(二级解析)"""
        if not page:
            return ''

        patterns = [
            r'''mysvg\s*=\s*['\"]([^'\"]+)['\"]''',
            r'''var\s+(?:url|urls|vurl|videoUrl|playurl|player_aaaa)\s*=\s*['\"]([^'\"]+)['\"]''',
            r'''(?:source|src|url)\s*[:=]\s*['\"](https?://[^'\"]+?\.(?:m3u8|mp4)[^'\"]*)['\"]''',
            r'''['\"]?(?:m3u8|mp4)['\"]?\s*[:=]\s*['\"]([^'\"]+?\.(?:m3u8|mp4))['\"]''',
        ]
        for pat in patterns:
            m = re.search(pat, page, re.I)
            if m:
                raw = m.group(1)
                if not raw.startswith('http'):
                    if raw.startswith('//'):
                        raw = 'https:' + raw
                    elif base:
                        raw = urllib.parse.urljoin(base, raw)
                if self.isVideoFormat(raw):
                    return raw

        m = re.search(r'''(https?://[^\s\"'\"'<>\\]+?\.(?:m3u8|mp4)[^\s\"'\"'<>\\]*)''', page, re.I)
        if m:
            return m.group(1)

        m = re.search(r'''[\"'\"'](/[^\s\"'\"'<>]+?\.m3u8[^\s\"'\"'<>]*)[\"'\"']''', page)
        if m and base:
            return urllib.parse.urljoin(base, m.group(1))

        return ''

    def playerContent(self, flag, id, vipFlags=None):
        try:
            pid = str(id).strip()
            play_url = pid if pid.startswith('http') else \
                '%s/v_play/%s.html' % (self._site(), pid)

            result = {'parse': 0, 'playUrl': '', 'url': '',
                      'header': ''}

            html = self._get(play_url, ref=self._site() + '/')
            if not html:
                result['parse'] = 1
                result['url'] = play_url
                result['header'] = json.dumps({'User-Agent': UA})
                return result

            m = re.search(r'''<iframe[^>]*\bsrc=[\"'\"']([^\"'\"']+)[\"'\"']''', html)

            if not m:
                jump = re.search(r'''var\s+url\s*=\s*[\"'\"'](https?://[^\"'\"']*?/v_play/[^\"'\"']+)[\"'\"']''', html)
                if jump and jump.group(1) != play_url:
                    html2 = self._get(jump.group(1), ref=play_url)
                    if html2:
                        m2 = re.search(r'''<iframe[^>]*\bsrc=[\"'\"']([^\"'\"']+)[\"'\"']''', html2)
                        if m2:
                            html, play_url, m = html2, jump.group(1), m2

            if not m:
                real = self._pick_m3u8(html, play_url)
                if real:
                    result['url'] = self._safe_url(real)
                    result['header'] = json.dumps(self._play_header(real))
                    return result
                result['parse'] = 1
                result['url'] = play_url
                result['header'] = json.dumps({'User-Agent': UA})
                return result

            src = m.group(1)
            if not src.startswith('http'):
                src = urllib.parse.urljoin(play_url, src)

            mm = re.search(r'''[?&]url=([^&\"'\"']+)''', src)
            if mm:
                real = urllib.parse.unquote(mm.group(1))
                if self.isVideoFormat(real):
                    result['url'] = self._safe_url(real)
                    result['header'] = json.dumps(self._play_header(real))
                    return result

            page = self._get(src, ref=play_url)
            real = self._pick_m3u8(page, src)
            if real:
                result['url'] = self._safe_url(real)
                result['header'] = json.dumps(self._play_header(real))
                return result

            result['parse'] = 1
            result['url'] = src
            result['header'] = json.dumps({'User-Agent': UA, 'Referer': play_url})
            return result
        except Exception:
            return {
                'parse': 1,
                'playUrl': '',
                'url': str(id) if str(id).startswith('http') else '%s/v_play/%s.html' % (self._site(), str(id)),
                'header': json.dumps({'User-Agent': UA})
            }

    @staticmethod
    def _safe_url(u):
        """对中文等非 ASCII 字符做百分号编码, 保留 URL 结构符号"""
        try:
            return urllib.parse.quote(u, safe=':/?&=.#%+-_~@!$,;*()[]')
        except Exception:
            return u
