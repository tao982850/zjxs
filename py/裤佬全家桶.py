# -*- coding: utf-8 -*-
"""
裤佬全家桶 · TVBox / 影视壳 Python 聚合站源（单文件）
把裤佬配置里的 26 个点播站合成一个 py：
  · 原本就是 Python 的站 → 运行时下载原脚本并内置调用（本地缓存，断网也能用上次的）
  · 原本是 JS / CMS / T4 的站 → 用 Python 重写
功能：
  · 每个站一个大分类，站内分类放在“分类”筛选里
  · 全站并发搜索，结果带【站名】；CMS 站片名带【国家/地区】标签
  · 多 User-Agent 轮换；去除 TG 频道/官网/关注之类的置顶跑马灯、公告条目
  · 播放：直链（m3u8/mp4…）直接播，网页地址交给壳解析
  · 屏蔽成人分类
只依赖壳自带的 base.spider（requests / pycryptodome 由各原脚本自带需求，影视壳一般都内置）
"""
import os, re, sys, json, time, types, random, base64, hashlib, tempfile, threading
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, wait

sys.path.append('..')
from base.spider import Spider as BaseSpider

SEP = '@@'
UAS = [
    'okhttp/4.12.0',
    'Mozilla/5.0 (Linux; Android 13; M2102J2SC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15',
    'Dalvik/2.1.0 (Linux; U; Android 12; SM-G9910 Build/SP1A.210812.016)',
]
PY = 'https://jsnz.pages.dev/f/'
# (key, 显示名, 类型, 地址/参数, 可搜索)
SITES = [
    ('douban', '豆瓣片单', 'douban', '', 0),
    ('naifei', '奈飞', 'naifei', '', 1),
    ('ys', '影视', 'py', PY + '9e53615c.py', 1),
    ('juhe', '聚合直播', 'py', PY + '4df9fb60.py', 0),
    ('kr', '韩国', 'py', PY + '26511242.py', 1),
    ('cj', '采集', 'py', PY + '72b7239d.py', 1),
    ('dj', '短剧', 'py', PY + '29b94aff.py', 1),
    ('dm', '动漫', 'py', PY + '7e20bdb7.py', 1),
    ('k4', '4K', 'py', PY + 'af676592.py', 1),
    ('wp', '网盘', 'py', PY + '261c1664.py', 1),
    ('pyz', 'PY', 'py', PY + 'e1aeef83.py', 1),
    ('api', 'API', 'py', PY + 'cf616b2f.py', 1),
    ('xb', '小宝影院', 'py', PY + 'e7124867.py', 1),
    ('app', 'APP', 'cms', 'http://cj.tianwe.cn/api.php/provide/vod/', 1),
    ('pk', '片库', 'pianku', 'https://4k01.pianku.online', 1),
    ('emby', 'Emby', 'emby', '', 1),
    ('iptv', 'IPTV', 'iptv', '', 0),
    ('ty', '体育', 'cms', 'https://jsnzkpg.de5.net/t4.json', 0),
    ('php', 'PHP', 't4', 'http://jiduo.3116598.xyz/PHP/pkty.php', 1),
    ('t4', 'T4', 't4', 'https://banyeomni.780420.xyz:17777/api/tvbox/source/2097848348508688384?token=banye666', 1),
    ('music', '音乐', 'py', PY + 'eded33cf.py', 1),
    ('kids', '少儿', 'tuxiaobei', '', 1),
    ('ts', '听书', 'py', PY + 'd44dd2cf.py', 1),
    ('fm', '广播', 'py', PY + 'cec31b11.py', 1),
    ('ys2', '有声', 'py', PY + 'e126d1e4.py', 1),
    ('xq', '戏曲', 'xiqu', '', 1),
]
BLOCK_WORDS = ('伦理', '三级', '写真', '两性', '擦边', '福利', '成人', '里番')
PROMO = re.compile(r'(TG频道|t\.me/|telegram|官网|关注|公众号|QQ群|微信群|请勿受骗|免费接口|置顶|公告|跑马灯)', re.I)


def region_of(area):
    a = str(area or '').split(',')[0].split('/')[0].strip()
    if not a:
        return ''
    for k, v in (('香港', '香港'), ('澳门', '香港'), ('台湾', '台湾'), ('大陆', '大陆'), ('内地', '大陆'),
                 ('中国', '大陆'), ('国产', '大陆'), ('日本', '日本'), ('韩国', '韩国'), ('泰国', '泰国'),
                 ('印度', '印度'), ('美国', '美国')):
        if k in a:
            return v
    if any(w in a for w in ('英国', '法国', '德国', '意大利', '西班牙', '加拿大', '澳大利亚', '俄罗斯', '欧美',
                            '爱尔兰', '荷兰', '比利时', '瑞典', '丹麦', '挪威', '波兰', '新西兰', '墨西哥', '巴西')):
        return '欧美'
    return '其他'


def clean_text(t):
    t = re.sub(r'<[^>]+>', '', str(t or ''))
    t = re.sub(r'&nbsp;|&amp;|&lt;|&gt;|&quot;', ' ', t)
    t = re.sub(r'(https?://\S+|www\.\S+)', '', t)
    t = re.sub(r'[^。！\n]*(QQ群|微信|公众号|电报|TG|telegram|关注|跑马灯|广告|请勿受骗)[^。！\n]*[。！]?', '', t, flags=re.I)
    return re.sub(r'[ \t]+', ' ', t).strip()


# ============================================================
#  内置子站（Python 重写）
# ============================================================
class Sub(object):
    def __init__(self, host, arg=''):
        self.h = host          # 聚合器（提供 fetch/post）
        self.arg = arg

    def get(self, url, headers=None, timeout=10):
        hd = {'User-Agent': random.choice(UAS)}
        hd.update(headers or {})
        return self.h.fetch(url, headers=hd, timeout=timeout)

    def getjson(self, url, headers=None, timeout=10):
        try:
            return self.get(url, headers, timeout).json()
        except Exception:
            return {}

    def init(self, ext=''):
        pass

    def homeContent(self, f):
        return {'class': []}

    def homeVideoContent(self):
        return {'list': []}

    def searchContent(self, key, quick, pg='1'):
        return {'list': []}

    def playerContent(self, flag, id, vip):
        return direct_or_parse(id)

    def localProxy(self, param):
        return None


def direct_or_parse(url, header=None):
    url = (url or '').strip()
    hd = header or {'User-Agent': UAS[2]}
    if re.search(r'\.(m3u8|mp4|flv|mkv|mp3|m4a|aac|ts|webm)(\?|$)', url, re.I) or re.search(r'/video/index|m3u8', url):
        return {'parse': 0, 'jx': 0, 'url': url, 'header': hd}
    return {'parse': 1, 'jx': 1, 'url': url, 'header': hd}


class CMS(Sub):
    """苹果 CMS / type1 json 接口"""
    BLOCK_TIDS = set()

    def api(self, q):
        base = self.arg
        joiner = '&' if '?' in base else '?'
        return self.getjson(base + joiner + q.lstrip('?'))

    def vod(self, v):
        reg = region_of(v.get('vod_area'))
        name = v.get('vod_name', '')
        return {'vod_id': str(v.get('vod_id', '')), 'vod_name': (f'【{reg}】' if reg else '') + name,
                'vod_pic': v.get('vod_pic', ''), 'vod_remarks': v.get('vod_remarks', '') or str(v.get('vod_year', ''))}

    def ok(self, v):
        return str(v.get('type_id', '')) not in self.BLOCK_TIDS and not any(
            w in str(v.get('type_name', '')) + str(v.get('vod_name', '')) for w in BLOCK_WORDS)

    def homeContent(self, f):
        d = self.api('ac=list')
        cls = [{'type_id': str(c['type_id']), 'type_name': c['type_name']} for c in d.get('class', [])
               if not any(w in c['type_name'] for w in BLOCK_WORDS) and str(c['type_id']) not in self.BLOCK_TIDS]
        if not cls:
            # 接口没给分类表：从最新列表里收集分类
            seen = {}
            for v in (d.get('list') or []) + self.api('ac=list&pg=2').get('list', []):
                tid, tn = str(v.get('type_id', '')), str(v.get('type_name', ''))
                if tid and tn and tid not in seen and not any(w in tn for w in BLOCK_WORDS):
                    seen[tid] = tn
            cls = [{'type_id': k, 'type_name': v} for k, v in seen.items()]
        return {'class': cls}

    def homeVideoContent(self):
        d = self.api('ac=detail&pg=1')
        return {'list': [self.vod(v) for v in d.get('list', []) if self.ok(v)]}

    def categoryContent(self, tid, pg, f, ext):
        d = self.api(f'ac=detail&t={quote(str(tid))}&pg={pg}')
        lst = [self.vod(v) for v in d.get('list', []) if self.ok(v)]
        return {'list': lst, 'page': int(pg), 'pagecount': int(d.get('pagecount') or (int(pg) + (1 if lst else 0))),
                'limit': 20, 'total': int(d.get('total') or 9999)}

    def detailContent(self, ids):
        d = self.api(f'ac=detail&ids={ids[0]}')
        if not d.get('list'):
            return {'list': []}
        v = d['list'][0]
        froms = (v.get('vod_play_from') or '').split('$$$')
        urls = (v.get('vod_play_url') or '').split('$$$')
        pairs = [(a, b.strip('#')) for a, b in zip(froms, urls) if b]
        pairs.sort(key=lambda p: 0 if 'm3u8' in p[0].lower() or '.m3u8' in p[1] else 1)
        vod = self.vod(v)
        vod.update({'type_name': v.get('type_name', ''), 'vod_year': v.get('vod_year', ''),
                    'vod_area': v.get('vod_area', ''), 'vod_actor': clean_text(v.get('vod_actor')),
                    'vod_director': clean_text(v.get('vod_director')),
                    'vod_content': clean_text(v.get('vod_content') or v.get('vod_blurb')),
                    'vod_play_from': '$$$'.join(p[0] for p in pairs), 'vod_play_url': '$$$'.join(p[1] for p in pairs)})
        return {'list': [vod]}

    def searchContent(self, key, quick, pg='1'):
        d = self.api(f'ac=detail&wd={quote(key)}&pg={pg}')
        return {'list': [self.vod(v) for v in d.get('list', []) if self.ok(v)]}


class NaiFei(CMS):
    """无尽资源（奈飞）：按地区重新分类，主接口无搜索时走备用接口"""
    MAIN = 'https://api.wsyzy.net/api.php/provide/vod/'
    SEARCH = ['https://api.wujinapi.me/api.php/provide/vod/', 'https://api.wujinapi.com/api.php/provide/vod/',
              'https://api.wujinapi.cc/api.php/provide/vod/']
    BLOCK_TIDS = {'55', '56', '57', '58', '59', '60', '61', '73'}
    MOVIE_TYPES = [('全部', '6,7,8,11,9,10'), ('动作', '6'), ('喜剧', '7'), ('爱情', '8'), ('科幻', '9'),
                   ('恐怖', '10'), ('剧情', '11'), ('战争', '12'), ('4K', '62'), ('邵氏', '70'), ('Netflix', '71')]
    REGIONS = ['全部', '大陆', '香港', '台湾', '日本', '韩国', '美国', '欧美', '泰国', '印度', '其他']
    CATS = [('电影', 'movie'), ('剧集·大陆', '13'), ('剧集·香港', '17'), ('剧集·台湾', '18'), ('剧集·韩国', '15'),
            ('剧集·日本', '16'), ('剧集·欧美', '14'), ('剧集·Netflix', '72'), ('剧集·泰国', '19'), ('剧集·海外', '23'),
            ('综艺·大陆', '25'), ('综艺·港台', '27'), ('综艺·日韩', '26'), ('综艺·欧美', '28'),
            ('动漫·大陆', '29'), ('动漫·港台', '44'), ('动漫·日韩', '30'), ('动漫·欧美', '31'), ('动漫·海外', '45'),
            ('动画片', '39'), ('短剧', '54'), ('短剧·女频', '64'), ('短剧·反转', '65'), ('短剧·古装', '66'),
            ('短剧·穿越', '67'), ('短剧·悬疑', '68'), ('短剧·都市', '69'), ('纪录片', '20'), ('体育赛事', '48'),
            ('篮球', '49'), ('足球', '50'), ('演唱会', '47'), ('影视解说', '53')]

    def __init__(self, host, arg=''):
        CMS.__init__(self, host, self.MAIN)

    def homeContent(self, f):
        return {'class': [{'type_id': v, 'type_name': n} for n, v in self.CATS],
                'filters': {'movie': [
                    {'key': 'type', 'name': '类型', 'value': [{'n': n, 'v': v} for n, v in self.MOVIE_TYPES]},
                    {'key': 'area', 'name': '地区', 'value': [{'n': r, 'v': r} for r in self.REGIONS]}]}}

    def categoryContent(self, tid, pg, f, ext):
        if tid != 'movie':
            return CMS.categoryContent(self, tid, pg, f, ext)
        pg = int(pg)
        ext = ext or {}
        ids = (ext.get('type') or self.MOVIE_TYPES[0][1]).split(',')
        area = ext.get('area') or '全部'
        raw, maxpg = [], pg
        if len(ids) == 1:
            if area == '全部':
                return CMS.categoryContent(self, ids[0], pg, f, ext)
            for ap in range((pg - 1) * 3 + 1, pg * 3 + 1):
                d = self.api(f'ac=detail&t={ids[0]}&pg={ap}')
                maxpg = max(maxpg, (int(d.get('pagecount') or 0) + 2) // 3)
                if not d.get('list'):
                    break
                raw += d['list']
        else:
            for t in ids:
                d = self.api(f'ac=detail&t={t}&pg={pg}')
                maxpg = max(maxpg, int(d.get('pagecount') or 0))
                raw += d.get('list', [])
            raw.sort(key=lambda v: str(v.get('vod_time', '')), reverse=True)
        lst = [self.vod(v) for v in raw if self.ok(v) and (area == '全部' or region_of(v.get('vod_area')) == area)]
        return {'list': lst, 'page': pg, 'pagecount': maxpg, 'limit': 20, 'total': maxpg * 20}

    def detailContent(self, ids):
        vid = ids[0]
        if vid.startswith('wj_'):
            for b in self.SEARCH:
                self.arg = b
                r = CMS.detailContent(self, [vid[3:]])
                self.arg = self.MAIN
                if r['list']:
                    r['list'][0]['vod_id'] = vid
                    return r
            return {'list': []}
        return CMS.detailContent(self, ids)

    def searchContent(self, key, quick, pg='1'):
        for b in self.SEARCH:
            d = self.getjson(f'{b}?ac=detail&wd={quote(key)}&pg={pg}')
            if d.get('list') is not None and d.get('code') == 1:
                out = []
                for v in d.get('list', []):
                    if self.ok(v):
                        x = self.vod(v)
                        x['vod_id'] = 'wj_' + x['vod_id']
                        out.append(x)
                return {'list': out}
        return {'list': []}


class T4(Sub):
    """T4 / PHP 接口"""

    def api(self, q):
        j = '&' if '?' in self.arg else '?'
        return self.getjson(self.arg + j + q, timeout=12)

    def homeContent(self, f):
        d = self.api('filter=true')
        return {'class': d.get('class', []), 'filters': d.get('filters', {})}

    def homeVideoContent(self):
        return {'list': self.api('filter=true').get('list', [])}

    def categoryContent(self, tid, pg, f, ext):
        e = base64.b64encode(json.dumps(ext or {}).encode()).decode()
        d = self.api(f'ac=detail&t={quote(str(tid))}&pg={pg}&ext={e}')
        d.setdefault('page', int(pg))
        return d

    def detailContent(self, ids):
        return self.api(f'ac=detail&ids={quote(ids[0])}')

    def searchContent(self, key, quick, pg='1'):
        return self.api(f'wd={quote(key)}&quick=false&pg={pg}')

    def playerContent(self, flag, id, vip):
        d = self.api(f'play={quote(id)}&flag={quote(flag or "")}')
        return d if d.get('url') else direct_or_parse(id)


class Pianku(Sub):
    ITEM = re.compile(r'<div class="vod-item">[\s\S]*?<a href="/voddetail/(\d+)\.html" title="(.*?)"[\s\S]*?<img src="(.*?)"[\s\S]*?<span class="remarks">(.*?)</span>')

    def u(self, p):
        return p if (p or '').startswith('http') else self.arg + ('' if (p or '').startswith('/') else '/') + (p or '')

    def items(self, html):
        return [{'vod_id': m[0], 'vod_name': m[1], 'vod_pic': self.u(m[2]), 'vod_remarks': m[3].strip()}
                for m in self.ITEM.findall(html or '')]

    def homeContent(self, f):
        cls = [{'type_id': '20', 'type_name': '电影'}, {'type_id': '37', 'type_name': '剧集'},
               {'type_id': '43', 'type_name': '动漫'}, {'type_id': '45', 'type_name': '综艺'}]
        sub = [('全部', '20'), ('动作片', '21'), ('喜剧片', '22'), ('爱情片', '23'), ('科幻片', '24'), ('恐怖片', '25'),
               ('剧情片', '26'), ('战争片', '27'), ('惊悚片', '28'), ('犯罪片', '29'), ('冒险片', '30'), ('动画片', '31'),
               ('悬疑片', '32'), ('武侠片', '33'), ('奇幻片', '34'), ('纪录片', '35'), ('其他片', '36')]
        return {'class': cls, 'filters': {'20': [{'key': 'tid', 'name': '类型', 'value': [{'n': n, 'v': v} for n, v in sub]}]}}

    def homeVideoContent(self):
        try:
            return {'list': self.items(self.get(self.arg).text)}
        except Exception:
            return {'list': []}

    def categoryContent(self, tid, pg, f, ext):
        t = (ext or {}).get('tid') or tid
        url = f'{self.arg}/vodtype/{t}.html' if str(pg) == '1' else f'{self.arg}/vodtype/{t}-{pg}.html'
        html = self.get(url).text
        m = re.search(r'尾页.*?href=".*?-(\d+)\.html"', html)
        pc = int(m.group(1)) if m else int(pg) + 1
        return {'list': self.items(html), 'page': int(pg), 'pagecount': pc, 'limit': 24, 'total': pc * 24}

    def detailContent(self, ids):
        html = self.get(f'{self.arg}/voddetail/{ids[0]}.html').text

        def g(p):
            m = re.search(p, html, re.S)
            return m.group(1).strip() if m else ''
        meta = dict((k, clean_text(v)) for k, v in re.findall(r'<(?:span|p|div)[^>]*>(导演|主演|地区|年份)[：:](.*?)</(?:span|p|div)>', html))
        froms = [x.strip() for x in re.findall(r'class="source-tab-item[^"]*"[^>]*>(.*?)</span>', html)]
        urls = []
        for pane in html.split('class="source-pane')[1:]:
            pane = pane.split('</div>')[0]
            eps = [f'{clean_text(n)}${self.u(h)}' for h, n in re.findall(r'href="(/vodplay/[^"]+)"[^>]*>(.*?)</a>', pane)]
            if eps:
                urls.append('#'.join(eps))
        if len(froms) != len(urls):
            froms = [f'线路{i + 1}' for i in range(len(urls))]
        name = clean_text(g(r'<h1[^>]*class="detail-title"[^>]*>(.*?)(?:<span|</h1>)'))
        reg = region_of(meta.get('地区'))
        return {'list': [{'vod_id': ids[0], 'vod_name': (f'【{reg}】' if reg else '') + name,
                          'vod_pic': self.u(g(r'class="detail-poster"[^>]*>[\s\S]*?<img src="(.*?)"')),
                          'vod_remarks': clean_text(g(r'class="detail-remarks"[^>]*>(.*?)</span>')),
                          'vod_year': meta.get('年份', ''), 'vod_area': meta.get('地区', ''),
                          'vod_actor': meta.get('主演', ''), 'vod_director': meta.get('导演', ''),
                          'vod_content': clean_text(g(r'class="detail-desc"[^>]*>[\s\S]*?<p>(.*?)</p>')),
                          'vod_play_from': '$$$'.join(froms), 'vod_play_url': '$$$'.join(urls)}]}

    def searchContent(self, key, quick, pg='1'):
        try:
            return {'list': self.items(self.get(f'{self.arg}/vodsearch/-------------.html?wd={quote(key)}').text)}
        except Exception:
            return {'list': []}

    def playerContent(self, flag, id, vip):
        try:
            html = self.get(self.u(id)).text
            m = re.search(r'player_aaaa\s*=\s*(\{[\s\S]*?\})\s*<', html)
            target = json.loads(m.group(1)).get('url', '') if m else ''
            if re.search(r'\.(m3u8|mp4)', target, re.I):
                return {'parse': 0, 'url': target, 'header': {'User-Agent': UAS[2]}}
            if target:
                h1 = self.get('https://svip.qlplayer.cyou/?url=' + target).text
                tk = re.search(r'apiToken\s*:\s*["\']([^"\']+)', h1)
                if tk:
                    d = self.getjson('https://svip.qlplayer.cyou/api/resolve.php?token=' + quote(tk.group(1)))
                    u = (d.get('url') or '').replace('\\', '')
                    if u:
                        return {'parse': 0, 'url': u, 'header': {'User-Agent': UAS[2]}}
        except Exception:
            pass
        return {'parse': 1, 'jx': 1, 'url': self.u(id), 'header': {'User-Agent': UAS[2]}}


class Emby(Sub):
    HOST = 'https://emby.bangumi.ca'
    TK = '8b0b16aae7e8403cb3d19969b82c3902'
    US = '80e861cbff1343bfa0bedcea78895b91'

    def j(self, path):
        sep = '&' if '?' in path else '?'
        return self.getjson(f'{self.HOST}/emby{path}{sep}X-Emby-Token={self.TK}', {'Referer': self.HOST + '/'})

    def vods(self, d):
        out = []
        for it in d.get('Items', []):
            pic = f"{self.HOST}/emby/Items/{it['Id']}/Images/Primary?maxWidth=400&tag={it['ImageTags']['Primary']}&quality=90" \
                if (it.get('ImageTags') or {}).get('Primary') else ''
            out.append({'vod_id': it['Id'], 'vod_name': it.get('Name', ''), 'vod_pic': pic,
                        'vod_remarks': str(it.get('ProductionYear') or '')})
        return out

    def homeContent(self, f):
        d = self.j(f'/Users/{self.US}/Views')
        return {'class': [{'type_id': it['Id'], 'type_name': it['Name']} for it in d.get('Items', [])
                          if '播放列表' not in it['Name'] and '相机' not in it['Name']]}

    def categoryContent(self, tid, pg, f, ext):
        s = (int(pg) - 1) * 30
        d = self.j(f'/Users/{self.US}/Items?SortBy=DateLastContentAdded%2CSortName&SortOrder=Descending&IncludeItemTypes=Movie%2CSeries'
                   f'&Recursive=true&Fields=ProductionYear&StartIndex={s}&ParentId={tid}&ImageTypeLimit=1&Limit=30')
        total = int(d.get('TotalRecordCount') or 0)
        return {'list': self.vods(d), 'page': int(pg), 'pagecount': int(pg) + 1 if int(pg) * 30 < total else int(pg),
                'limit': 30, 'total': total}

    def detailContent(self, ids):
        vid = ids[0]
        info = self.j(f'/Users/{self.US}/Items/{vid}')
        eps = []
        if not info.get('IsFolder'):
            eps.append(f"{info.get('Name', '正片').strip()}${vid}")
        elif info.get('Type') == 'Series':
            for se in self.j(f'/Shows/{vid}/Seasons?UserId={self.US}').get('Items', []):
                for ep in self.j(f'/Shows/{vid}/Episodes?SeasonId={se["Id"]}&UserId={self.US}&Limit=1000').get('Items', []):
                    eps.append(f"{se['Name'].replace('#', '-').replace('$', '|')}|{ep['Name'].replace('#', '-').replace('$', '|')}${ep['Id']}")
        else:
            for it in self.j(f'/Users/{self.US}/Items?ParentId={vid}').get('Items', []):
                eps.append(f"{it['Name'].replace('#', '-').replace('$', '|')}${it['Id']}")
        v = self.vods({'Items': [info]})[0] if info else {'vod_id': vid}
        v.update({'vod_content': clean_text(info.get('Overview', '')), 'vod_year': str(info.get('ProductionYear') or ''),
                  'type_name': ' / '.join(info.get('Genres') or []), 'vod_play_from': 'EMBY', 'vod_play_url': '#'.join(eps)})
        return {'list': [v]}

    def searchContent(self, key, quick, pg='1'):
        d = self.j(f'/Users/{self.US}/Items?SortBy=SortName&Recursive=true&IncludeItemTypes=Movie%2CSeries&SearchTerm={quote(key)}&Limit=50')
        return {'list': self.vods(d)}

    def playerContent(self, flag, id, vip):
        hd = {'User-Agent': UAS[2], 'Referer': self.HOST + '/'}
        try:
            body = json.dumps({'DeviceProfile': {'DirectPlayProfiles': [{'Container': 'mp4,m4v,mkv,hls,webm', 'Type': 'Video'}],
                                                 'TranscodingProfiles': [{'Container': 'ts', 'Type': 'Video', 'Protocol': 'hls'}]}})
            r = self.h.post(f'{self.HOST}/emby/Items/{id}/PlaybackInfo?UserId={self.US}&IsPlayback=false&AutoOpenLiveStream=false'
                            f'&MaxStreamingBitrate=7000000&X-Emby-Token={self.TK}', data=body,
                            headers=dict(hd, **{'Content-Type': 'application/json'}), timeout=12).json()
            ms = (r.get('MediaSources') or [{}])[0]
            if ms.get('DirectStreamUrl'):
                return {'parse': 0, 'url': self.HOST + '/emby' + ms['DirectStreamUrl'] if ms['DirectStreamUrl'].startswith('/videos') else self.HOST + ms['DirectStreamUrl'], 'header': hd}
            if ms.get('Protocol') == 'Http':
                return {'parse': 0, 'url': ms.get('Path'), 'header': hd}
        except Exception:
            pass
        return {'parse': 0, 'url': f'{self.HOST}/emby/videos/{id}/stream?static=true&api_key={self.TK}', 'header': hd}


class IPTV(Sub):
    SRC = [('裤佬TV', 'https://gh-proxy.org/https://raw.githubusercontent.com/pyapk/1/refs/heads/main/zby'),
           ('潇雨TV', 'https://0701.tv1288.xyz/m3u'),
           ('日后TV', 'https://jsnzkpg4.pages.dev/http://rihou.cc:555/gggg.nzk'),
           ('涛涛TV', 'https://445569.pages.dev/https://raw.githubusercontent.com/taoBox2620/taoBox2620/refs/heads/main/logo1.png'),
           ('华视TV', 'https://445569.pages.dev/https://raw.githubusercontent.com/swhtv/111/refs/heads/main/华视box华视大全swtv'),
           ('易发TV', 'https://445569.pages.dev/https://raw.githubusercontent.com/fafa002/yf2025/refs/heads/main/yiyifafa.txt'),
           ('土耳其TV', 'https://445569.pages.dev/https://raw.githubusercontent.com/nigelhayes11/temp/refs/heads/main/MAN%20NORMAL%20TV%202025.m3u'),
           ('俄罗斯TV', 'https://ilook.epg.one/5CM5SY98BF24PL/2'),
           ('全球TV', 'https://seep.eu.org/iptv-org.github.io/iptv/index.m3u')]
    PIC = 'https://mpimg.cn/view.php/1dcb211cf3b75f932fb13c6fe98a80f7.jpeg'
    cache = {}

    def parse(self, idx):
        if idx in self.cache and time.time() - self.cache[idx][0] < 1800:
            return self.cache[idx][1]
        groups = {}
        try:
            txt = self.get(self.SRC[int(idx)][1], {'User-Agent': 'okhttp/4.12.0'}, timeout=15).text
        except Exception:
            txt = ''
        if '#EXTINF' in txt:
            g, name = '默认', ''
            for line in txt.splitlines():
                line = line.strip()
                if line.startswith('#EXTINF'):
                    m = re.search(r'group-title="([^"]*)"', line)
                    g = (m.group(1) if m else '') or '默认'
                    name = line.rsplit(',', 1)[-1].strip()
                elif line and not line.startswith('#') and name:
                    groups.setdefault(g, []).append((name, line))
                    name = ''
        else:
            g = '默认'
            for line in txt.splitlines():
                line = line.strip()
                if ',#genre#' in line:
                    g = line.split(',')[0]
                elif ',' in line and '://' in line:
                    n, u = line.split(',', 1)
                    groups.setdefault(g, []).append((n.strip(), u.strip()))
        groups = {k: v for k, v in groups.items() if not PROMO.search(k)}
        self.cache[idx] = (time.time(), groups)
        return groups

    def homeContent(self, f):
        return {'class': [{'type_id': str(i), 'type_name': n} for i, (n, u) in enumerate(self.SRC)]}

    def categoryContent(self, tid, pg, f, ext):
        if str(pg) != '1':
            return {'list': [], 'page': int(pg), 'pagecount': 1}
        gs = self.parse(tid)
        return {'list': [{'vod_id': f'{tid}|{g}', 'vod_name': g, 'vod_pic': self.PIC, 'vod_remarks': f'{len(c)}个频道'}
                         for g, c in gs.items()], 'page': 1, 'pagecount': 1}

    def detailContent(self, ids):
        idx, g = ids[0].split('|', 1)
        ch = self.parse(idx).get(g, [])
        # 同名频道合并成多线路
        lines, order = {}, []
        for n, u in ch:
            for uu in u.split('#'):
                if n not in lines:
                    lines[n] = []
                    order.append(n)
                lines[n].append(uu)
        maxl = max([len(v) for v in lines.values()] or [1])
        froms, urls = [], []
        for i in range(min(maxl, 6)):
            eps = [f'{n.replace("$", "")}${lines[n][i]}' for n in order if len(lines[n]) > i]
            froms.append(f'线路{i + 1}')
            urls.append('#'.join(eps))
        return {'list': [{'vod_id': ids[0], 'vod_name': g, 'vod_pic': self.PIC, 'type_name': '直播',
                          'vod_play_from': '$$$'.join(froms), 'vod_play_url': '$$$'.join(urls)}]}

    def playerContent(self, flag, id, vip):
        return {'parse': 0, 'url': id, 'header': {'User-Agent': 'okhttp/4.12.0'}}


class Tuxiaobei(Sub):
    HOST = 'https://www.tuxiaobei.com'
    HD = {'User-Agent': UAS[3], 'Referer': 'https://www.tuxiaobei.com/'}

    def homeContent(self, f):
        return {'class': [{'type_id': '2', 'type_name': '儿歌'}, {'type_id': '3', 'type_name': '故事'},
                          {'type_id': '4', 'type_name': '国学'}, {'type_id': '25', 'type_name': '启蒙'}]}

    def categoryContent(self, tid, pg, f, ext):
        try:
            t = self.get(f'{self.HOST}/list/mip-data?typeId={tid}&page={pg}&callback=', self.HD).text.strip()
            if '(' in t:
                t = t[t.index('(') + 1:t.rindex(')')]
            items = (json.loads(t).get('data') or {}).get('items') or []
        except Exception:
            items = []
        lst = [{'vod_id': str(i['video_id']), 'vod_name': i['name'], 'vod_pic': i.get('image', ''),
                'vod_remarks': i.get('duration_string', '')} for i in items]
        return {'list': lst, 'page': int(pg), 'pagecount': int(pg) + 1 if lst else int(pg)}

    def detailContent(self, ids):
        url = f'{self.HOST}/play/{ids[0]}'
        try:
            html = self.get(url, self.HD).text
        except Exception:
            html = ''
        m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
        return {'list': [{'vod_id': ids[0], 'vod_name': clean_text(m.group(1)) if m else '兔小贝', 'type_name': '少儿',
                          'vod_play_from': '兔小贝', 'vod_play_url': f'正片${url}'}]}

    def searchContent(self, key, quick, pg='1'):
        try:
            html = self.get(f'{self.HOST}/search/index?key={quote(key)}', self.HD).text
        except Exception:
            return {'list': []}
        out = []
        for blk in re.findall(r'<div class="items"[\s\S]*?</a>', html):
            h = re.search(r'href="([^"]+)"', blk)
            n = re.search(r'class="text"[^>]*>(.*?)<', blk)
            p = re.search(r'<mip-img[^>]*src="([^"]+)"', blk)
            if h and n:
                out.append({'vod_id': h.group(1).rstrip('/').split('/')[-1], 'vod_name': clean_text(n.group(1)),
                            'vod_pic': p.group(1) if p else ''})
        return {'list': out}

    def playerContent(self, flag, id, vip):
        try:
            html = self.get(id, self.HD).text
            m = re.search(r'id="videoWrap"[\s\S]*?video-src="([^"]+)"', html)
            if m:
                return {'parse': 0, 'url': m.group(1), 'header': self.HD}
        except Exception:
            pass
        return {'parse': 1, 'url': id, 'header': self.HD}


class Xiqu(Sub):
    HOST = 'https://fly.daoran.tv'
    HD = {'User-Agent': 'okhttp/3.12.10', 'md5': 'SkvyrWqK9QHTdCT12Rhxunjx+WwMTe9y4KwgeASFDhbYabRSPskR0Q==',
          'Content-Type': 'application/json; charset=UTF-8'}
    PIC = 'https://img0.baidu.com/it/u=4079405848,3806507810&fm=253&fmt=auto&app=138&f=JPEG?w=500&h=750'
    UID = 'd4b29595b6fe764e09078a0dad7352ff'
    N = '豫剧&黄梅戏&越剧&京剧&评剧&曲剧&坠子&秦腔&河北梆子&潮剧&粤剧&沪剧&二夹弦&昆曲&河南琴书&淮剧&单弦&婺剧&越调&滇剧&扬剧&二人台&彩调&吕剧&柳琴戏&京韵大鼓&皮影戏&湘剧&琼剧&锡剧&评书&绍剧&庐剧&话剧&西河大鼓&莆仙戏&花鼓戏&川剧&相声&采茶戏&蒲剧&汉剧&闽剧&晋剧&赣剧&楚剧&曲艺晚会&其他'
    U = 'yuju&hmx&yueju&jingju&pingju&quju&hnzz&qinq&hbbz&chaoju&gddx&huju&ejx&kunqu&hnqs&huaiju&danxian&wuju&yued&dianju&yangju&ERT&caidiao&lvjv&liuqx&jydg&pyx&xj&qiongju&xiju&pingshu&shaojv&luju&huaju&xhdg&huagx&chuanju&xiang&caichaxi&pujv&hj&minju&jinju&gj&chuju&else&other'

    def p(self, path, data):
        data.update({'userId': self.UID, 'channel': 'oppo', 'item': data.get('item', 'y9'), 'nodeCode': '001000', 'project': 'lyhxcx'})
        try:
            return self.h.post(self.HOST + path, data=json.dumps(data), headers=self.HD, timeout=12).json()
        except Exception:
            return {}

    def lst(self, d):
        return [{'vod_id': it['code'], 'vod_name': it['name'], 'vod_pic': self.PIC, 'vod_remarks': clean_text(it.get('des', ''))[:20]}
                for it in ((d.get('pb') or {}).get('dataList') or [])]

    def homeContent(self, f):
        return {'class': [{'type_id': u, 'type_name': n} for n, u in zip(self.N.split('&'), self.U.split('&'))]}

    def categoryContent(self, tid, pg, f, ext):
        d = self.p('/API_ROP/search/album/screen', {'cur': int(pg), 'free': 0, 'orderby': 'hot', 'pageSize': 30,
                                                   'resType': 1, 'sect': tid, 'tagId': 0})
        pb = d.get('pb') or {}
        return {'list': self.lst(d), 'page': int(pg), 'pagecount': int(pb.get('totalPage') or pg), 'limit': 30,
                'total': int(pb.get('totalCount') or 0)}

    def detailContent(self, ids):
        d = self.p('/API_ROP/album/res/list', {'albumCode': ids[0], 'cur': 1, 'pageSize': 200})
        eps = [f"{it['name'].replace('#', ' ').replace('$', ' ')}${it['code']}" for it in ((d.get('pb') or {}).get('dataList') or [])]
        return {'list': [{'vod_id': ids[0], 'vod_name': eps[0].split('$')[0] if eps else '戏曲', 'vod_pic': self.PIC,
                          'type_name': '戏曲', 'vod_play_from': '多多专线', 'vod_play_url': '#'.join(eps)}]}

    def searchContent(self, key, quick, pg='1'):
        return {'list': self.lst(self.p('/API_ROP/search/album/list', {'cur': 1, 'free': 0, 'keyword': key, 'orderby': 'hot',
                                                                       'pageSize': 60, 'px': 2, 'sect': []}))}

    def playerContent(self, flag, id, vip):
        d = self.p('/API_ROP/play/get/playurl', {'item': 'o3', 'mask': 0, 'px': 2, 'resCode': id})
        u = ((d.get('playUrls') or {}).get('hd')) or ((d.get('playUrls') or {}).get('sd')) or ''
        return {'parse': 0, 'url': u, 'header': {'User-Agent': 'okhttp/3.12.10'}}


class Douban(Sub):
    CATS = [('热门电影', 'movie|热门'), ('最新电影', 'movie|最新'), ('豆瓣高分', 'movie|豆瓣高分'), ('冷门佳片', 'movie|冷门佳片'),
            ('华语电影', 'movie|华语'), ('欧美电影', 'movie|欧美'), ('韩国电影', 'movie|韩国'), ('日本电影', 'movie|日本'),
            ('热门剧集', 'tv|热门'), ('国产剧', 'tv|国产剧'), ('美剧', 'tv|美剧'), ('英剧', 'tv|英剧'), ('韩剧', 'tv|韩剧'),
            ('日剧', 'tv|日剧'), ('港剧', 'tv|港剧'), ('日本动画', 'tv|日本动画'), ('综艺', 'tv|综艺'), ('纪录片', 'tv|纪录片')]

    def homeContent(self, f):
        return {'class': [{'type_id': v, 'type_name': n} for n, v in self.CATS]}

    def categoryContent(self, tid, pg, f, ext):
        typ, tag = tid.split('|')
        d = self.getjson(f'https://movie.douban.com/j/search_subjects?type={typ}&tag={quote(tag)}&page_limit=30&page_start={(int(pg) - 1) * 30}',
                         {'User-Agent': UAS[2], 'Referer': 'https://movie.douban.com/'})
        lst = [{'vod_id': s['title'], 'vod_name': s['title'], 'vod_pic': s.get('cover', ''),
                'vod_remarks': f"豆瓣{s.get('rate') or '暂无'}"} for s in d.get('subjects', [])]
        return {'list': lst, 'page': int(pg), 'pagecount': int(pg) + 1 if len(lst) >= 30 else int(pg)}

    def detailContent(self, ids):
        # 豆瓣条目：自动去各影视站搜同名片，合并可播线路
        return self.h.find_play(ids[0])


BUILTIN = {'naifei': NaiFei, 'cms': CMS, 't4': T4, 'pianku': Pianku, 'emby': Emby, 'iptv': IPTV,
           'tuxiaobei': Tuxiaobei, 'xiqu': Xiqu, 'douban': Douban}


# ============================================================
#  聚合器
# ============================================================
class Spider(BaseSpider):
    def getName(self):
        return '裤佬全家桶'

    def init(self, extend=''):
        self.subs = {}
        self.home_cache = {}
        self.lock = threading.Lock()
        self.meta = {s[0]: s for s in SITES}
        self.cache_dir = os.path.join(tempfile.gettempdir(), 'kuolao_qjt')
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception:
            pass

    # ---------- 网络（多 UA 轮换） ----------
    def fetch(self, url, headers=None, timeout=10, **kw):
        hd = {'User-Agent': random.choice(UAS)}
        hd.update(headers or {})
        return BaseSpider.fetch(self, url, headers=hd, timeout=timeout, **kw)

    def post(self, url, data=None, json=None, headers=None, timeout=10, **kw):
        hd = {'User-Agent': random.choice(UAS)}
        hd.update(headers or {})
        if json is not None:
            return BaseSpider.post(self, url, json=json, headers=hd, timeout=timeout, **kw)
        return BaseSpider.post(self, url, data=data, headers=hd, timeout=timeout, **kw)

    # ---------- 子站加载 ----------
    def _py_source(self, key, url):
        path = os.path.join(self.cache_dir, key + '.py')
        fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400
        if not fresh:
            try:
                r = self.fetch(url, headers={'User-Agent': 'okhttp/4.12.0'}, timeout=25)
                txt = r.content.decode('utf-8', 'ignore')
                if 'class Spider' in txt:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(txt)
                    return txt
            except Exception:
                pass
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                return f.read()
        return ''

    def sub(self, key):
        if key in self.subs:
            return self.subs[key]
        with self.lock:
            if key in self.subs:
                return self.subs[key]
            _, name, kind, arg, _s = self.meta[key]
            obj = None
            try:
                if kind == 'py':
                    src = self._py_source(key, arg)
                    if src:
                        mod = types.ModuleType('kl_' + key)
                        mod.__file__ = os.path.join(self.cache_dir, key + '.py')
                        exec(compile(src, mod.__file__, 'exec'), mod.__dict__)
                        obj = mod.Spider()
                        try:
                            orig = obj.getProxyUrl

                            def gp(*a, _o=orig, _k=key, **k):
                                return _o(*a, **k) + '&klsite=' + _k
                            obj.getProxyUrl = gp
                        except Exception:
                            pass
                        try:
                            obj.init('')
                        except TypeError:
                            obj.init()
                else:
                    obj = BUILTIN[kind](self, arg)
                    obj.init('')
            except Exception:
                obj = None
            self.subs[key] = obj
            return obj

    def call(self, key, fn, *a):
        s = self.sub(key)
        if s is None:
            return {}
        try:
            r = getattr(s, fn)(*a)
            if isinstance(r, str):
                r = json.loads(r) if r.strip().startswith('{') else {}
            return r or {}
        except Exception:
            return {}

    # ---------- 工具 ----------
    def wrap(self, key, vods):
        out = []
        for v in vods or []:
            vid = str(v.get('vod_id', ''))
            name = str(v.get('vod_name', ''))
            if not vid or PROMO.search(name) or vid.startswith('pinned') or any(w in name for w in BLOCK_WORDS):
                continue
            x = dict(v)
            x['vod_id'] = key + SEP + vid
            out.append(x)
        return out

    def wrap_play(self, key, vod):
        urls = []
        for line in str(vod.get('vod_play_url', '')).split('$$$'):
            eps = []
            for ep in line.split('#'):
                if not ep:
                    continue
                if '$' in ep:
                    n, u = ep.split('$', 1)
                else:
                    n, u = '播放', ep
                eps.append(f'{n}${key}{SEP}{u}')
            urls.append('#'.join(eps))
        vod['vod_play_url'] = '$$$'.join(urls)
        for k in ('vod_content', 'vod_actor', 'vod_director'):
            if vod.get(k):
                vod[k] = clean_text(vod[k])
        return vod

    def site_home(self, key):
        if not (self.home_cache.get(key) or {}).get('class'):
            r = self.call(key, 'homeContent', True)
            cls = [c for c in r.get('class', []) if not PROMO.search(str(c.get('type_name', '')))
                   and not any(w in str(c.get('type_name', '')) for w in BLOCK_WORDS)]
            if cls or key not in self.home_cache:
                self.home_cache[key] = {'class': cls, 'filters': r.get('filters') or {}}
        return self.home_cache[key]

    # ---------- 首页 ----------
    def _home_file(self):
        return os.path.join(self.cache_dir, 'home.json')

    def homeContent(self, filter):
        keys = [s[0] for s in SITES]
        disk = {}
        try:
            with open(self._home_file(), encoding='utf-8') as f:
                disk = json.load(f)
        except Exception:
            pass
        pool = ThreadPoolExecutor(max_workers=10)
        futs = {pool.submit(self.site_home, k): k for k in keys}
        # 有缓存就只等 3 秒（后台继续刷新），首次最多等 12 秒
        wait(futs, timeout=3 if disk else 12)
        pool.shutdown(wait=False)
        for k, v in disk.items():
            if k not in self.home_cache or not self.home_cache[k].get('class'):
                self.home_cache.setdefault(k, v)
                if not self.home_cache[k].get('class'):
                    self.home_cache[k] = v

        def save():
            wait(list(futs), timeout=40)
            try:
                good = {k: v for k, v in self.home_cache.items() if v.get('class')}
                good.update({k: v for k, v in disk.items() if k not in good})
                with open(self._home_file(), 'w', encoding='utf-8') as f:
                    json.dump(good, f, ensure_ascii=False)
            except Exception:
                pass
        threading.Thread(target=save, daemon=True).start()
        classes, filters = [], {}
        for s in SITES:
            key, name = s[0], s[1]
            classes.append({'type_id': key, 'type_name': name})
            h = self.home_cache.get(key)
            if not h or not h['class']:
                continue
            fl = [{'key': '__c', 'name': '分类',
                   'value': [{'n': c['type_name'], 'v': str(c['type_id'])} for c in h['class']]}]
            first = str(h['class'][0]['type_id'])
            seen = {'__c'}
            for g in h['filters'].get(first, []) or []:
                if g.get('key') not in seen:
                    seen.add(g.get('key'))
                    fl.append(g)
            filters[key] = fl
        return {'class': classes, 'filters': filters}

    def homeVideoContent(self):
        out = []
        for key in ('naifei', 'app', 'pk'):
            out += self.wrap(key, self.call(key, 'homeVideoContent').get('list', []))[:12]
        return {'list': out}

    # ---------- 分类 ----------
    def categoryContent(self, tid, pg, filter, extend):
        key = tid
        extend = dict(extend or {})
        h = self.site_home(key)
        sub_tid = extend.pop('__c', None) or (str(h['class'][0]['type_id']) if h['class'] else '')
        r = self.call(key, 'categoryContent', sub_tid, str(pg), True, extend)
        lst = self.wrap(key, r.get('list', []))
        return {'list': lst, 'page': int(r.get('page') or pg), 'pagecount': int(r.get('pagecount') or (int(pg) + (1 if lst else 0))),
                'limit': int(r.get('limit') or 20), 'total': int(r.get('total') or 9999)}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        key, vid = ids[0].split(SEP, 1)
        if key == 'douban':
            r = self.call(key, 'detailContent', [vid])
            return r if r.get('list') else {'list': []}
        r = self.call(key, 'detailContent', [vid])
        lst = r.get('list') or []
        if not lst:
            return {'list': []}
        vod = dict(lst[0])
        vod['vod_id'] = ids[0]
        return {'list': [self.wrap_play(key, vod)]}

    def find_play(self, title):
        """豆瓣片名 → 去影视站搜同名，合并线路"""
        cands = ['naifei', 'app', 'pk', 'ys', 'xb', 'cj', 'k4']
        found = []

        def one(k):
            for v in self.call(k, 'searchContent', title, False, '1').get('list', [])[:10]:
                n = re.sub(r'^【[^】]*】', '', str(v.get('vod_name', ''))).strip()
                if n == title:
                    d = self.call(k, 'detailContent', [str(v['vod_id'])]).get('list') or []
                    if d and d[0].get('vod_play_url'):
                        return k, d[0]
            return None
        pool = ThreadPoolExecutor(max_workers=7)
        futs = [pool.submit(one, k) for k in cands]
        wait(futs, timeout=20)
        pool.shutdown(wait=False)
        for f in futs:
            if f.done() and f.result():
                found.append(f.result())
        if not found:
            return {'list': [{'vod_id': 'douban' + SEP + title, 'vod_name': title, 'vod_content': '各站暂未搜到可播放的同名片源，可用搜索换个片名试试',
                              'vod_play_from': '无', 'vod_play_url': f'暂无$douban{SEP}none'}]}
        base = dict(found[0][1])
        froms, urls = [], []
        for k, d in found:
            w = self.wrap_play(k, dict(d))
            for f_, u_ in zip(str(d.get('vod_play_from', '')).split('$$$'), w['vod_play_url'].split('$$$')):
                froms.append(f'{self.meta[k][1]}-{f_}')
                urls.append(u_)
        base.update({'vod_id': 'douban' + SEP + title, 'vod_name': title, 'vod_play_from': '$$$'.join(froms),
                     'vod_play_url': '$$$'.join(urls)})
        return {'list': [base]}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg='1'):
        keys = [s[0] for s in SITES if s[4]]
        res = {}

        def one(k):
            res[k] = self.wrap(k, self.call(k, 'searchContent', key, quick, str(pg)).get('list', []))[:30]
        pool = ThreadPoolExecutor(max_workers=10)
        futs = [pool.submit(one, k) for k in keys]
        wait(futs, timeout=15)
        pool.shutdown(wait=False)
        out = []
        for k in keys:
            for v in res.get(k, []):
                v['vod_name'] = f'【{self.meta[k][1]}】' + str(v.get('vod_name', ''))
                out.append(v)
        return {'list': out, 'page': int(pg), 'pagecount': int(pg) + 1 if out else int(pg)}

    def searchContentPage(self, key, quick, pg):
        return self.searchContent(key, quick, pg)

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags):
        if SEP not in id:
            return direct_or_parse(id)
        key, pid = id.split(SEP, 1)
        if key == 'douban':
            return {'parse': 0, 'url': ''}
        r = self.call(key, 'playerContent', flag, pid, vipFlags)
        if not r or not r.get('url'):
            return direct_or_parse(pid)
        if 'header' not in r:
            r['header'] = {'User-Agent': UAS[2]}
        return r

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv|mkv)(\?|$)', url or '', re.I))

    def manualVideoCheck(self):
        pass

    def localProxy(self, param):
        key = (param or {}).get('klsite')
        if key and key in self.subs and self.subs[key] is not None:
            p = dict(param)
            p.pop('klsite', None)
            try:
                return self.subs[key].localProxy(p)
            except Exception:
                return None
        for s in self.subs.values():          # 兜底：挨个试
            try:
                r = s.localProxy(param) if s else None
                if r:
                    return r
            except Exception:
                continue
        return None

    def liveContent(self, url):
        return ''

    def destroy(self):
        for s in self.subs.values():
            try:
                s.destroy()
            except Exception:
                pass
