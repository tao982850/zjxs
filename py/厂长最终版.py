#!/usr/bin/env python3
# coding=utf-8
# !/usr/bin/python
"""
厂长资源 ( cz4k. .com) —— TVBox / 影视仓 Python 爬虫 (T4 py)
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
修复  : 2026-11 播放修复版
  1. 域名自动探测(cz4k.com 已属旧域名, 官方跳转指向 4kcz.com), 并识别 SafeLine 人机验证页
  2. playerContent 改为多级取流: 直链 -> iframe 递归 -> 真实性校验, 再回退 parse=1 嗅探
  3. 播放地址不再强制要求 m3u8/mp4 后缀(站点会把流地址伪装/转义), 改为拉取首字节校验 #EXTM3U
  4. 兼容 JSON 斜杠转义、HTML 实体、?url= 参数、base64 参数等常见播放页写法
  5. 缩短超时并限制重试, 避免壳子解析超时导致"点了没反应"
修复  : 2026-11-10 真站校准(以 www.4kcz.com 实际页面取证)
  1. /movie_bt 不带参数会命中雷池按 URL 缓存的验证页; 取页失败时自动补时间戳变体重试
  2. 静态分类只保留实测出条目的栏目(裸 movie_bt_series/view_cat/tags、zuixindianying、
     dbtop250、hanguodianying、ribendianying 实测 200 但无条目, 选中即空列表)
  3. 分类页实测为 div.bt_img>ul>li, 条目链接是绝对地址, 分页格式 /page/N
  4. 导航发现兼容绝对链接, 并把 /movie_bt/movie_bt_series/x 归一成 movie_bt_series/x
  5. 首页推荐在 /movie_bt 取不到条目时回退到分类页取
  6. 线路实测: /v_play 页面里是第三方播放器 iframe(如 plaa.py1080p.com:8181/player/py.php),
     真实直链在播放器页的 art.url / mysvg 里; 解析不出直链时把该播放器地址交给壳子嗅探,
     不再退回整站播放页; 线路主机证书不合规时降级不校验重试
  7. m3u8 回传前做真伪校验: 分片指向图片 CDN(.image/.png)的占位清单不直连,
     改为让壳子嗅探播放器页; 真实 m3u8 仍直连; m3u8 优先于 mp4
  8. 客户端版本兼容(蜂蜜/TVBox 5.8.x 分类空白): filters 只对 class 中真实存在的
     type_id 下发, 不再给裸 movie_bt_series 等无效键; class 去重并剔除空名称;
     各接口接受多余参数, 兼容新版反射调用
  9. 对齐参考脚本(4K河豚)在 5.8.7 的取流行为: 服务端探测到占位 m3u8 也照样以
     parse=0 回传(客户端用自己的 UA 常能拿到真清单), 不再降级成新版不可靠的嗅探;
     候选过滤掉广告图/图标, 探测遇图片立即放弃(原先一条广告图探测耗时 15s,
     直接吃掉取流预算, 是"新款能进详情却播不了"的直接原因); 取流总预算收紧到 7s
 10. playerContent 的 header 改为直接回传对象(与 4K河豚 一致)。FongMi 5.8.7 侧
     按 Map 反序列化 header, 回传 JSON 字符串会解析失败, 表现为能进详情但播放不出;
     同时去掉多余的 playUrl 字段, 只保留 parse/url/header
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
# 官方跳转页(czzy22.com)公告: 新地址 www.4kcz.com, 旧域名陆续失效。
# 这里按优先级探测, 命中真实列表页的域名会被缓存复用。
SITE_CANDIDATES = [
    'https://www.4kcz.com',
    'https://www.cz4k.com',
    'https://cz4k.com',
    'https://www.czzy.top',
]
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
# 视频直链后缀(仅用于快速判定, 不以后缀作为唯一依据)
VIDEO_EXT_RE = re.compile(
    r'\.(m3u8|m3u|mp4|m4v|mkv|flv|avi|ts|mov|webm)(\?|#|$)', re.I)


class Spider(_BaseSpider):
    # ==================== 生命周期 ====================
    def init(self, extend=""):
        """extend 可传入新域名, 站点换域名时无需改代码"""
        self.site = ''
        self.waf = False
        self._site_ok = False
        self._site_next = 0
        self._id2path = {}
        self._play_cache = {}
        try:
            if extend:
                ext = extend.strip()
                if ext.startswith('{'):
                    ext = json.loads(ext).get('site', '')
                if ext.startswith('http'):
                    self.site = ext.rstrip('/')
        except Exception:
            pass
        if not self.site:
            self.site = DEFAULT_SITE

    def getName(self):
        return '厂长资源'

    def isVideoFormat(self, url):
        return bool(VIDEO_EXT_RE.search(str(url)))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, param):
        return None

    # ==================== 网络 ====================
    def _site(self):
        """首次使用时探测可用域名并缓存, 规避旧域名 302 跳转页 / 被墙"""
        s = getattr(self, 'site', '') or ''
        if s and getattr(self, '_site_ok', False):
            return s
        if time.time() < getattr(self, '_site_next', 0):
            return s or DEFAULT_SITE
        if s and self._looks_like_site(s):
            self._site_ok = True
            return s
        for cand in SITE_CANDIDATES:
            if cand == s:
                continue
            if self._looks_like_site(cand):
                self.site = cand
                self._site_ok = True
                return cand
        # 全部探测失败: 缓存 5 分钟, 避免每次请求都重复探测拖慢列表加载
        self._site_next = time.time() + 300
        self.site = s or DEFAULT_SITE
        return self.site

    def _looks_like_site(self, base):
        """真实列表页一定含 /movie/xx.html 条目; 跳转页与 WAF 验证页都不含"""
        try:
            html = self._get(base + '/movie_bt', ref=base + '/',
                             retry=1, timeout=(5, 10))
            return bool(html) and bool(re.search(r'/movie/\d+\.html', html))
        except Exception:
            return False

    def _headers(self, ref=None):
        # 注意: 这里不能走 _site(), 否则 _site() 探测时会递归
        base = getattr(self, 'site', '') or DEFAULT_SITE
        return {
            'User-Agent': UA,
            'Referer': ref or (base + '/'),
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

    def _fetch(self, url, ref, ct, rt):
        """单次取页; 异常交给上层决定是否重试。
        线路播放器主机常见证书不合规, 校验失败时降级为不校验再取一次。"""
        if HAS_REQUESTS:
            se = self._session()
            try:
                r = se.get(url, headers=self._headers(ref),
                           timeout=(ct, rt), allow_redirects=True)
            except Exception as e:
                name = type(e).__name__ + str(e)
                if 'SSL' not in name and 'Certificate' not in name:
                    raise
                try:
                    import urllib3
                    urllib3.disable_warnings()
                except Exception:
                    pass
                r = se.get(url, headers=self._headers(ref), timeout=(ct, rt),
                           allow_redirects=True, verify=False)
            if r.status_code >= 500:
                raise IOError('http %d' % r.status_code)
            return r.content.decode('utf-8', 'ignore')
        import urllib.request
        req = urllib.request.Request(url, headers=self._headers(ref))
        return urllib.request.urlopen(req, timeout=rt).read().decode('utf-8', 'ignore')

    def _get(self, url, ref=None, timeout=None, retry=3):
        """
        取网页源码。雷池会按 URL 缓存人机验证页, 命中验证页时用带时间戳的
        变体再取一次(实测同一路径补 _= 参数即可绕过缓存拿到真实页面)。
        """
        ct, rt = timeout or (6, 12)
        bust = '%s%s_=%d' % (url, '&' if '?' in url else '?',
                             int(time.time() * 1000))
        for i in range(max(1, retry)):
            for u in (url, bust):
                try:
                    txt = self._fetch(u, ref, ct, rt)
                except Exception:
                    txt = ''
                if not txt:
                    continue
                if self._is_waf_page(txt):
                    self.waf = True
                    continue
                return txt
            if i + 1 < max(1, retry):
                time.sleep(0.6 * (i + 1))
        return ''

    @staticmethod
    def _is_waf_page(txt):
        """雷池 SafeLine 验证页特征"""
        if not txt:
            return False
        return ('SafeLine' in txt) or ('slg-title' in txt) or \
               ('Confirm You Are Human' in txt)

    # ==================== 工具 ====================
    @staticmethod
    def _text(html):
        """去标签取纯文本"""
        t = re.sub(r'<[^>]+>', '', html or '')
        t = t.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
        t = t.replace('\u200b', '')
        return re.sub(r'\s+', ' ', t).strip()

    def _list_chunks(self, html):
        """
        按常见列表容器切块; 容器名不认识时退化为围绕详情链接的窗口扫描,
        保证模板改版(bt_img -> module-item / stui-vodlist 等)后仍能取到条目。
        """
        for cm in re.finditer(
                r'<div[^>]*class="[^"]*(?:bt_img|module-items|module-list|stui-vodlist|'
                r'public-list|vodlist|pic-list|list-box|v_items)[^"]*"[^>]*>', html):
            tail = html[cm.end(): cm.end() + 400000]
            lis = [x.group(0) for x in re.finditer(r'<li[\s\S]*?</li>', tail)]
            if lis:
                return lis
            starts = [x.start() for x in re.finditer(
                r'<div[^>]*class="[^"]*module-item(?![-\w])[^"]*"', tail)]
            if starts:
                starts.append(min(len(tail), starts[-1] + 3000))
                return [tail[a:b] for a, b in zip(starts, starts[1:])]
        # 兑底: 每个详情链接单独成块, 块止于下一个详情链接, 避免条目串号
        pos = [x.start() for x in re.finditer(
            r'href="[^"]*?/(?:movie|voddetail|detail)/?\d+[^"]*"', html)]
        if not pos:
            return []
        bounds, last = [], 0
        for a in pos:
            st = html.rfind('<a', 0, a)
            bounds.append(max(st if st != -1 else a, last))
            last = bounds[-1]
        pos.append(len(html))
        return [html[a:b] for a, b in zip(bounds, pos[1:])]

    def _item(self, it):
        """单个列表条目: 名称按 dytit -> a[title] -> a 文本 -> alt/title 多级降级,
        任一级拿到名称都保留条目(旧版只认 dytit/alt, 缺一个就整页丢弃)。"""
        m = re.search(
            r'href="([^"]*?/(?:movie|voddetail|detail)/?(\d+)(?:\.html)?[^"]*)"', it)
        if not m:
            return None
        path, vid = m.group(1), m.group(2)
        nm = re.search(r'class="[^"]*dytit[^"]*"[^>]*>\s*<a[^>]*>([^<]+)</a>', it) \
            or re.search(r'<a[^>]*title="([^"]{2,})"', it) \
            or re.search(r'<h[1-4][^>]*>\s*<a[^>]*>([^<]{2,})</a>', it) \
            or re.search(r'<a[^>]*>\s*([^<>]{2,60})\s*</a>', it) \
            or re.search(r'alt="([^"]{2,})"', it) \
            or re.search(r'title="([^"]{2,})"', it)
        name = self._text(nm.group(1)) if nm else ''
        name = name.replace('《', '').replace('》', '').strip()
        if not name or name in ('CC', '立即播放', '播放', '详情'):
            return None

        pm = re.search(r'data-original="([^"]+)"', it) \
            or re.search(r'data-src="([^"]+)"', it) \
            or re.search(r'<img[^>]*src="([^"]+)"', it)
        pic = self._clean(pm.group(1)) if pm else ''
        if pic.startswith('//'):
            pic = 'https:' + pic

        remark = ''
        for pat, fmt in (
                (r'class="[^"]*jidi[^"]*"[^>]*>\s*<span[^>]*>([^<]+)</span>', '%s'),
                (r'class="[^"]*rating[^"]*"[^>]*>\s*([\d.]+)\s*<', '评分%s'),
                (r'class="[^"]*furk[^"]*"[^>]*>([^<]+)</span>', '%s'),
                (r'class="[^"]*qb[^"]*"[^>]*>([^<]+)</span>', '%s'),
                (r'class="[^"]*(?:module-item-text|pic-text|remarks|score|note)[^"]*"[^>]*>\s*([^<]{1,20})\s*<', '%s'),
                (r'class="[^"]*inzhuy[^"]*"[^>]*>([^<]*)<', '%s')):
            mm = re.search(pat, it)
            if mm:
                v = self._text(mm.group(1))
                if v and v != 'false':
                    remark = v if fmt == '%s' else (fmt % v)
                    break
        remark = remark.replace('主演：', '').rstrip('：:')[:20]

        paths = getattr(self, '_id2path', None)
        if not isinstance(paths, dict):
            paths = self._id2path = {}
        paths[vid] = path

        return {'vod_id': vid, 'vod_name': name, 'vod_pic': pic,
                'vod_remarks': remark}

    def _parse_list(self, html, base=''):
        """模板无关列表解析: 多容器切块 + 通用兑底 + 名称多级降级"""
        if not html:
            return []
        out, seen = [], set()
        for it in self._list_chunks(html):
            try:
                hit = self._item(it)
            except Exception:
                hit = None
            if not hit or hit['vod_id'] in seen:
                continue
            seen.add(hit['vod_id'])
            out.append(hit)
        return out

    def _nav_cats(self, html):
        """从页面导航发现真实分类; 兼容绝对链接, 并把
        /movie_bt/movie_bt_series/rj 这类重复前缀归一成 movie_bt_series/rj"""
        out, seen = [], set()
        static = set(c['type_id'] for c in self._static_cats())
        for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>([\s\S]{1,40}?)</a>',
                             html or ''):
            href = self._clean(m.group(1))
            if not href or href.startswith(('javascript:', 'mailto:', '#')):
                continue
            path = urllib.parse.urlparse(href).path if '://' in href \
                else href.split('?')[0]
            path = path.rstrip('/')
            mm = re.search(r'/(movie_bt(?:_series|_view_cat|_tags)?)'
                           r'(/[A-Za-z0-9_%]+)?$', path)
            if not mm:
                continue
            tid = (mm.group(1) + (mm.group(2) or '')).strip('/')
            name = self._text(m.group(2))
            if not name or len(name) > 8 or name in ('更多', '详情', '播放', '首页', '下载'):
                continue
            if tid in seen or tid in static:
                continue
            seen.add(tid)
            out.append({'type_id': tid, 'type_name': name})
        return out[:30]

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
    @staticmethod
    def _static_cats():
        # 只保留实测能出条目的栏目: 裸 movie_bt_series / movie_bt_view_cat /
        # movie_bt_tags 以及 zuixindianying、dbtop250、hanguodianying 等路径
        # 实测返回 200 但页面没有条目, 选它就是空列表
        return [
            {'type_id': 'movie_bt', 'type_name': '最近更新'},
            {'type_id': 'movie_bt_series/dyy', 'type_name': '电影'},
            {'type_id': 'movie_bt_series/guochanju', 'type_name': '国产剧'},
            {'type_id': 'movie_bt_series/mj', 'type_name': '美剧'},
            {'type_id': 'movie_bt_series/hj', 'type_name': '韩剧'},
            {'type_id': 'movie_bt_series/rj', 'type_name': '日剧'},
            {'type_id': 'movie_bt_series/hwj', 'type_name': '海外剧'},
            {'type_id': 'movie_bt_view_cat/fjj', 'type_name': '动漫'},
            {'type_id': 'movie_bt_view_cat/pvyugao', 'type_name': 'PV预告'},
            {'type_id': 'movie_bt_view_cat/manweidianyingyuzhou', 'type_name': '漫威宇宙'},
            {'type_id': 'movie_bt_view_cat/zhouxingchi', 'type_name': '周星驰'},
            {'type_id': 'movie_bt_tags/kh', 'type_name': '科幻'},
            {'type_id': 'movie_bt_tags/juqing', 'type_name': '剧情'},
            {'type_id': 'huayudianying', 'type_name': '华语电影'},
            {'type_id': 'oumeidianying', 'type_name': '欧美电影'},
            {'type_id': 'yindudianying', 'type_name': '印度电影'},
            {'type_id': 'gaofenyingshi', 'type_name': '高分影视'},
        ]

    def homeContent(self, filter=False, *args, **kwargs):
        try:
            cats = self._static_cats()
            # 导航自发现的真实栏目排在前, 硬编码分类作为兑底跟在后
            nav, now = [], time.time()
            cache = getattr(self, '_nav_cache', None) or (0, [])
            if cache[0] > now:
                nav = cache[1]
            else:
                nav = self._nav_cats(self._get(self._site() + '/movie_bt',
                                               retry=1, timeout=(4, 7)))
                if not nav:
                    for hub in ('movie_bt_series/dyy', 'movie_bt_series/rj'):
                        nav = self._nav_cats(self._get(
                            '%s/%s' % (self._site(), hub), retry=1, timeout=(4, 7)))
                        if nav:
                            break
                self._nav_cache = (now + 600, nav)
            if nav:
                seen = set(c['type_id'] for c in nav)
                cats = nav + [c for c in cats if c['type_id'] not in seen]
            # 去重并剔除空 id/空名称, 新版客户端遇到空条目会整片空白
            clean, used = [], set()
            for c in cats:
                tid = str(c.get('type_id', '') or '').strip()
                name = str(c.get('type_name', '') or '').strip()
                if not tid or not name or tid in used:
                    continue
                used.add(tid)
                clean.append({'type_id': tid, 'type_name': name})
            cats = clean or self._static_cats()

            # 分类面板兼容: filters 的键必须与 class 里真实存在的 type_id 对应。
            # 本脚本的分类已经是带栏目的完整 tid(如 movie_bt_series/dyy),
            # 裸键(movie_bt_series 等)在 5.8.x 这类新版客户端上会被判为无效筛选,
            # 表现为"各分类空白"。因此只对确实存在的键下发筛选, 否则给空字典。
            ids = set(c['type_id'] for c in cats)
            filters = {}
            for tid, (key, opts) in self.LIBS.items():
                if tid not in ids or not opts:
                    continue
                name = {'tag': '类型', 'cat': '专题', 'ser': '分类'}[key]
                filters[tid] = [{
                    'key': key,
                    'name': name,
                    'value': [{'n': n, 'v': v} for n, v in opts],
                }]

            return {'class': cats, 'filters': filters, 'filter': filters}
        except Exception:
            return {'class': self._static_cats(), 'filters': {}, 'filter': {}}

    def homeVideoContent(self, *args, **kwargs):
        try:
            site = self._site()
            vod_list = self._parse_list(self._get('%s/movie_bt' % site, retry=1))
            if not vod_list:
                for tid in ('movie_bt_series/dyy', 'movie_bt_series/guochanju'):
                    vod_list = self._parse_list(self._get(
                        '%s/%s' % (site, tid), retry=1, timeout=(5, 9)))
                    if vod_list:
                        break
            return {'list': vod_list}
        except Exception:
            return {'list': []}

    # ==================== 分类列表 ====================
    def categoryContent(self, tid, pg=1, filter=False, extend="", *args, **kwargs):
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
                slug = str(extend.get(key, '') if isinstance(extend, dict) else '') or opts[0][1]
                tid = '%s/%s' % (tid, slug)

            site = self._site()
            base = tid if tid.startswith('http') else '%s/%s' % (site, tid)

            # 分页格式各家不一, 逐个试到出数据为止
            if pg == 1:
                urls = [base, base + '/', base + '/index.html']
            else:
                urls = ['%s/page/%d' % (base, pg), '%s/page/%d.html' % (base, pg),
                        '%s/%d.html' % (base, pg), '%s?page=%d' % (base, pg)]

            vod_list = []
            for u in urls[:2 if pg == 1 else 3]:
                vod_list = self._parse_list(self._get(u, retry=1, timeout=(5, 9)))
                if vod_list:
                    break

            return {
                'list': vod_list,
                'page': pg,
                'pagecount': 9999 if vod_list else pg,
                'limit': 90,
                'total': 999999 if vod_list else 0,
            }
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 90, 'total': 0}

    # ==================== 详情 / 选集 ====================
    def _detail_pages(self, vid):
        """详情页候选地址: 列表里记下的真实路径优先, 再试几套常见路由"""
        if vid.startswith('http'):
            return [vid]
        site = self._site()
        urls = []
        paths = getattr(self, '_id2path', None)
        p = paths.get(vid) if isinstance(paths, dict) else None
        if p:
            urls.append(p if p.startswith('http') else site + p)
        for pat in ('/movie/%s.html', '/voddetail/%s.html', '/detail/%s.html'):
            u = site + (pat % vid)
            if u not in urls:
                urls.append(u)
        return urls

    def _episodes(self, html):
        """选集: 直接保留播放页真实路径作为 id, 不再只存 base64 码,
        这样 /v_play/、/vodplay/ 等路由变化时仍能回到正确播放页。"""
        out, seen, used = [], set(), {}
        for m in re.finditer(
                r'<a[^>]*href="([^"]*?(?:/v_play/|/vodplay/|/play/)[^"]*?\.html[^"]*)"'
                r'[^>]*>([\s\S]{0,80}?)</a>', html or ''):
            href = self._clean(m.group(1))
            path = urllib.parse.urlparse(href).path or href
            if not path or path in seen:
                continue
            seen.add(path)
            code = path.rstrip('/').rsplit('/', 1)[-1].split('.')[0]
            label = self._text(m.group(2))
            if (not label) or ('播放' in label) or len(label) > 14:
                label = self._ep_label(code, len(out))
            label = label.replace('#', '').replace('$', '').strip() or ('第%d集' % (len(out) + 1))
            used[label] = used.get(label, 0) + 1
            if used[label] > 1:
                label = '%s-%d' % (label, used[label])
            out.append('%s$%s' % (label, path))
        if not out:
            for code in re.findall(r'/(?:v_play|vodplay)/([A-Za-z0-9+/=_-]+)\.html',
                                   html or ''):
                if code in seen:
                    continue
                seen.add(code)
                out.append('%s$%s' % (self._ep_label(code, len(out)), code))
        return out

    def detailContent(self, ids, *args, **kwargs):
        try:
            vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
            vid = str(vid).strip()

            html = ''
            for u in self._detail_pages(vid)[:3]:
                page = self._get(u, retry=1, timeout=(5, 9))
                if not page:
                    continue
                if re.search(r'/v_play/|/vodplay/', page) or 'og:title' in page \
                        or 'moviedteail' in page:
                    html = page
                    break
            if not html:
                return {'list': []}

            # 标题: 详情标题块 > og:title > h1 > title
            m = re.search(r'class="[^"]*moviedteail_tt[^"]*"[^>]*>\s*<h1[^>]*>([^<]+)', html) \
                or re.search(r'property="og:title"\s+content="([^"]+)"', html) \
                or re.search(r'<h1[^>]*>([^<]{1,60})</h1>', html) \
                or re.search(r'<title>《([^》]+)》', html) \
                or re.search(r'<title>([^<|_]{1,60})', html)
            name = self._text(m.group(1)) if m else ''
            name = re.sub(r'(在线观看|高清完整版|免费观看|高清版).*$', '', name).strip()
            name = name.replace('《', '').replace('》', '').strip()

            # 封面
            m = re.search(r'(?:property|name)="og:image"\s+content="([^"]+)"', html) \
                or re.search(r'data-original="([^"]+)"', html) \
                or re.search(r'<img[^>]*src="([^"]+)"', html)
            pic = self._clean(m.group(1)) if m else ''
            if pic.startswith('//'):
                pic = 'https:' + pic
            pic = self._abs(pic, self._site()) or pic

            # 简介
            m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html) \
                or re.search(r'class="[^"]*(?:yp_context|jianjie|desc|content)[^"]*"[^>]*>([\s\S]{10,800}?)</', html)
            content = self._text(m.group(1)).strip() if m else ''

            # 元信息: 任意 li / span 里的 “键：值”, 只收白名单键, 避免抓到垃圾
            wanted = ('类型', '年份', '地区', '语言', '主演', '导演', '编剧',
                      '时长', '上映', '又名', '豆瓣', '集数', '状态', '别名', '更新时间')
            info = {}
            for li in re.findall(r'<(?:li|span|p)[^>]*>([\s\S]{0,200}?)</(?:li|span|p)>', html):
                t = self._text(li)
                if '：' not in t and ':' not in t:
                    continue
                k, v = re.split(r'[：:]', t, 1)
                k, v = k.strip(), v.strip()
                if k in wanted and v and k not in info:
                    info[k] = v

            episodes = self._episodes(html)
            if not episodes and not name:
                return {'list': []}

            score = info.get('豆瓣', '')
            m = re.search(r'class="[^"]*dbpingfen[^"]*"[^>]*>\s*([\d.]+)\s*<', html)
            if m:
                score = m.group(1)
            score = score.strip() if score else ''
            if not re.match(r'^\d+(\.\d+)?$', score or ''):
                score = ''

            year = info.get('年份', '').strip()
            if not re.match(r'^\d{4}$', year):
                ym = re.search(r'(19\d{2}|20\d{2})', info.get('上映', '') or year)
                year = ym.group(1) if ym else year

            is_multi_ep = len(episodes) > 1 and any(
                re.search(r'第?\s*\d+\s*集|^\s*\d+\s*$|EP\s*\d+', e.split('$')[0], re.I)
                for e in episodes)
            if score:
                remarks = '豆瓣 %s' % score
            elif is_multi_ep:
                remarks = '共%d集' % len(episodes)
            else:
                remarks = (info.get('状态', '') or info.get('上映', '')
                           or ('%s %s' % (info.get('类型', ''), info.get('地区', ''))).strip())

            extra = []
            if score:
                extra.append('豆瓣评分 %s' % score)
            if info.get('集数'):
                extra.append('集数 %s' % info['集数'])
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
    def searchContent(self, key, quick=False, pg="1", *args, **kwargs):
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
        按视频直链所在 CDN 决定回传给播放器的请求头。
        站点直链多走自有 CDN: 自家域需要 Referer; 第三方图床带 Referer 反而 403,
        因此只对同源/自家 CDN 补 Referer 与 Origin。
        """
        h = {'User-Agent': UA}
        try:
            host = (urllib.parse.urlparse(url).hostname or '').lower()
            site_host = (urllib.parse.urlparse(self._site()).hostname or '').lower()
        except Exception:
            host, site_host = '', ''
        own = bool(host and site_host and (
            host == site_host or host.endswith('.' + site_host) or
            site_host.endswith('.' + host)))
        if own or any(k in host for k in ('4kcz.com', 'cz4k.com', 'czzy.')):
            h['Referer'] = self._site() + '/'
            h['Origin'] = self._site()
        return h

    @staticmethod
    def _clean(raw):
        """去空白/引号/HTML 实体, 还原 JSON 转义"""
        s = str(raw or '').strip().strip('\'"\\')
        s = s.replace('&amp;', '&').replace('&#47;', '/')
        s = s.replace('\\/', '/').replace('\\u002F', '/').replace('\\u0026', '&')
        return s.strip()

    def _abs(self, raw, base=''):
        """把相对/协议相对地址补全为绝对地址"""
        s = self._clean(raw)
        if not s or s.startswith(('data:', 'javascript:', 'about:', 'blob:')):
            return ''
        if s.startswith('//'):
            return 'https:' + s
        if s.startswith('http'):
            return s
        if s.startswith('/') and base:
            return urllib.parse.urljoin(base, s)
        return ''

    def _decode_variants(self, raw):
        """url 参数可能是 urlencode 或 base64 编码, 展开成候选"""
        out = []
        s = self._clean(raw)
        try:
            u = urllib.parse.unquote(s)
            if u != s:
                out.append(u)
        except Exception:
            pass
        for cand in list(out) + [s]:
            if len(cand) < 12 or '://' in cand:
                continue
            try:
                pad = cand + '=' * (-len(cand) % 4)
                d = base64.b64decode(pad).decode('utf-8', 'ignore')
                if '://' in d or d.startswith('/'):
                    out.append(d)
            except Exception:
                pass
        return out

    def _iframes(self, page, base=''):
        out = []
        for m in re.finditer(r"""<iframe[^>]*\bsrc\s*=\s*['"]([^'"]+)['"]""",
                             page or '', re.I):
            u = self._abs(m.group(1), base)
            if u and u not in out:
                out.append(u)
        return out

    def _video_candidates(self, page, base=''):
        """
        从页面里挖播放地址候选。
        不要求地址带 .m3u8/.mp4 后缀 —— 站点会把流地址伪装成 .jpg 或不带后缀,
        这里只做候选收集, 真实性交给 _probe 校验。
        """
        if not page:
            return []
        p = page.replace('\\/', '/').replace('\\u002F', '/')
        pats = [
            r"""mysvg\s*=\s*['"]([^'"]+)['"]""",
            r"""(?:file|src|url|urls|vurl|videoUrl|playurl|play_url|videourl|m3u8|mp4)\s*[:=]\s*['"]([^'"]+)['"]""",
            r"""['"](/[^'"\s]+?\.(?:m3u8|mp4)[^'"\s]*)['"]""",
            r"""(https?://[^\s'"<>]+?\.(?:m3u8|mp4)[^\s'"<>]*)""",
        ]
        raw = []
        for pat in pats:
            raw.extend(m.group(1) for m in re.finditer(pat, p, re.I))
        for m in re.finditer(r"""[?&]url=([^&'"\s<>]+)""", p, re.I):
            raw.extend(self._decode_variants(m.group(1)))

        out, seen = [], set()
        for r in raw:
            u = self._abs(r, base)
            if not u or u in seen:
                continue
            low = u.lower().split('?')[0]
            # 广告图/图标/样式/脚本不是播放地址, 探测它们只会白白耗掉取流预算
            if low.endswith(('.js', '.css', '.ico', '.svg', '.woff', '.woff2',
                             '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')):
                continue
            seen.add(u)
            out.append(u)
        # 解析型地址(?url=...): 展开内层地址, 否则会把中继页当视频丢给播放器
        final, seen2 = [], set()
        for u in out:
            if 'url=' in u.lower():
                try:
                    inner = urllib.parse.parse_qs(
                        urllib.parse.urlparse(u).query).get('url', [''])[0]
                except Exception:
                    inner = ''
                for cand in [inner] + self._decode_variants(inner):
                    v = self._abs(cand, base)
                    if v and v not in seen2 and self.isVideoFormat(v):
                        seen2.add(v)
                        final.append(v)
                continue
            if u not in seen2:
                seen2.add(u)
                final.append(u)
        # 带标准视频后缀的优先, 伪装/无后缀的靠后
        final.sort(key=lambda x: 0 if self.isVideoFormat(x) else 1)
        return final

    def _probe(self, url, ref=None):
        """拉首字节判定是不是真流: #EXTM3U / video 类型 / ftyp"""
        try:
            if not HAS_REQUESTS:
                return False
            h = self._play_header(url)
            if ref:
                h['Referer'] = ref
            r = self._session().get(url, headers=h, timeout=(3, 4),
                                    stream=True, allow_redirects=True)
            try:
                if r.status_code >= 400:
                    return False
                ct = (r.headers.get('Content-Type') or '').lower()
                if ct.startswith('image/'):
                    return False      # 广告图/封面, 不读正文直接放弃
                if 'mpegurl' in ct:
                    return True
                chunk = b''
                for piece in r.iter_content(1024):
                    chunk = piece
                    break
                txt = chunk.decode('utf-8', 'ignore')
                if '#EXTM3U' in txt or '#EXT-X-' in txt:
                    return True
                if chunk[4:8] == b'ftyp':
                    return True
                return ct.startswith('video/')
            finally:
                try:
                    r.close()
                except Exception:
                    pass
        except Exception:
            return False

    @staticmethod
    def _path_is_hls(u):
        """只看 path 判断是否为 HLS 地址; 查询串里带 .m3u8 的中继页不算"""
        try:
            p = urllib.parse.urlparse(str(u)).path.lower()
        except Exception:
            p = str(u).lower()
        return p.endswith(('.m3u8', '.m3u'))

    def _hls_ok(self, url):
        """
        判断 m3u8 是否为真实流。站点部分线路返回的是占位清单:
        分片全部指向图片 CDN(.image/.png 等), 播放器能下载清单但解码不出画面,
        表现为"线路播放加载失败"。分片后缀/宿主异常时判为占位。
        """
        try:
            if not HAS_REQUESTS:
                return True
            r = self._session().get(url, headers=self._play_header(url),
                                    timeout=(3, 5), stream=True,
                                    allow_redirects=True)
            try:
                if r.status_code >= 400:
                    return False
                txt = ''
                for piece in r.iter_content(4096):
                    txt += piece.decode('utf-8', 'ignore')
                    if len(txt) > 30000:
                        break
                segs = [l.strip() for l in txt.splitlines()
                        if l.strip() and not l.startswith('#')]
                if not segs:
                    return False
                real = 0
                for seg in segs[:80]:
                    low = seg.lower().split('?')[0]
                    if low.endswith(('.ts', '.m4s', '.mp4', '.m4v', '.aac', '.m3u8')):
                        real += 1
                    elif low.endswith(('.image', '.jpg', '.jpeg', '.png', '.webp', '.gif')):
                        return False
                return real > 0
            finally:
                try:
                    r.close()
                except Exception:
                    pass
        except Exception:
            return True   # 探测失败不阻断播放, 按可用处理

    def _resolve(self, play_url, deadline):
        """
        多级取流: 播放页直链 -> iframe 播放器页(最多 3 页) -> 参数解码。
        优先级: m3u8(HLS) > 其他视频直链(mp4) > 首字节校验通过的地址。
        站点里 m3u8 线路是播放页内直接给出的, 不依赖第三方播放器主机;
        而 token 型线路要访问播放器主机(如 8181 端口)才产出 mp4, 该主机在部分
        网络不可达, 表现为"线路播放加载失败", 因此 m3u8 必须优先。
        服务端探测到占位清单时也照样回传该 m3u8: 客户端用自己的 UA/Cookie 请求
        往往能拿到真清单, 而降级成 parse=1 在 5.8.x 这类新版客户端上不可靠。
        """
        site = self._site()
        page = self._get(play_url, ref=site + '/', timeout=(4, 6), retry=1)
        if not page:
            return ''
        queue = [(page, play_url)]
        seen = {play_url}
        self._sniff = ''
        bad_hls, other_hit = '', ''
        budget, pages = 3, 0
        while queue and time.time() < deadline and pages < 3:
            cur, base = queue.pop(0)
            pages += 1
            if not cur:
                continue
            for u in self._video_candidates(cur, base):
                if self._path_is_hls(u):
                    if self._hls_ok(u):
                        return u          # 服务端确认是真清单, 最优
                    if not bad_hls:
                        bad_hls = u       # 占位清单留作兜底, 不据此降级嗅探
                    continue
                if self.isVideoFormat(u):
                    if not other_hit:
                        other_hit = u
                    continue
                if budget > 0 and time.time() < deadline:
                    budget -= 1
                    if self._probe(u, base) and not other_hit:
                        other_hit = u
            for src in self._iframes(cur, base):
                if src in seen:
                    continue
                seen.add(src)
                if not self._sniff:
                    self._sniff = src   # 解析不出直链时交给壳子嗅探这个播放器页
                if self._path_is_hls(src):
                    return src
                if len(seen) > 4 or time.time() >= deadline:
                    break
                nxt = self._get(src, ref=base, timeout=(4, 6), retry=1)
                if nxt:
                    queue.append((nxt, src))
        return other_hit or bad_hls

    def playerContent(self, flag, id, vipFlags=None, *args, **kwargs):
        pid = str(id or '').strip()
        try:
            site = self._site()
            raw = pid.split('$')[-1].strip()
            if pid.startswith('http'):
                play_url = pid
            elif raw.startswith('/'):
                # 新版选集 id 直接带播放页路径(/v_play/、/vodplay/ 都能用)
                play_url = site + raw
            else:
                # 兼容旧版只存 base64 码的选集
                play_url = '%s/v_play/%s.html' % (site, raw)

            cache = getattr(self, '_play_cache', None) or {}
            hit = cache.get(pid)
            if hit and hit[1] > time.time() and hit[0]:
                return {'parse': 0, 'url': hit[0],
                        'header': self._play_header(hit[0])}

            real = self._resolve(play_url, time.time() + 7.0)
            if real:
                real = self._safe_url(real)
                cache[pid] = (real, time.time() + 900)
                self._play_cache = cache
                return {'parse': 0, 'url': real,
                        'header': self._play_header(real)}

            # 兜底: 优先把线路播放器地址交给壳子嗅探(直链在它产出的 art.url 里),
            # 拿不到播放器地址时才退回整站播放页
            sniff = getattr(self, '_sniff', '') or play_url
            return {'parse': 1, 'url': sniff,
                    'header': {'User-Agent': UA, 'Referer': site + '/'}}
        except Exception:
            base = getattr(self, 'site', '') or DEFAULT_SITE
            tail = pid.split('$')[-1].strip()
            if pid.startswith('http'):
                fb = pid
            elif tail.startswith('/'):
                fb = base + tail
            else:
                fb = '%s/v_play/%s.html' % (base, tail)
            return {'parse': 1, 'url': fb,
                    'header': {'User-Agent': UA}}

    @staticmethod
    def _safe_url(u):
        """对中文等非 ASCII 字符做百分号编码, 保留 URL 结构符号"""
        try:
            return urllib.parse.quote(u, safe=':/?&=.#%+-_~@!$,;*()[]')
        except Exception:
            return u
