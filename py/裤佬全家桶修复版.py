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

# ============================================================
#  运行时兼容层（影视 5.8.x / 5.8.9）
#  · 宿主 fetch/post 的参数签名、返回对象各家不一 → 自适应 + 标准库兜底
#  · 宿主响应可能没有 .json()/正确 encoding → 统一包装成 Resp
#  这一层只依赖标准库，宿主一个网络方法都不能用也能跑
# ============================================================
import gzip
import zlib

try:
    import ssl
except Exception:
    ssl = None

try:
    from urllib.request import Request as _Req, build_opener as _build_opener, HTTPCookieProcessor as _CookieProc
    from urllib.parse import urlencode as _urlencode
    from http.cookiejar import CookieJar as _CookieJar
    _URL_OK = True
except Exception:
    _URL_OK = False

_OPENER = [None]


def _decode_bytes(raw):
    if not isinstance(raw, (bytes, bytearray)):
        return str(raw or '')
    b = bytes(raw)
    if b[:2] == b'\x1f\x8b':
        try:
            b = gzip.decompress(b)
        except Exception:
            pass
    if b[:3] == b'\xef\xbb\xbf':
        b = b[3:]
    for enc in ('utf-8', 'gb18030', 'latin-1'):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode('utf-8', 'ignore')


class Resp(object):
    """统一响应对象：text / content / json() / status_code / headers 都在"""
    __slots__ = ('content', '_text', 'status_code', 'headers', 'url')

    def __init__(self, content=b'', text=None, status=200, headers=None, url=''):
        if isinstance(content, str):
            content = content.encode('utf-8', 'ignore')
        self.content = content or b''
        self._text = text
        self.status_code = status
        self.headers = headers or {}
        self.url = url or ''

    @property
    def text(self):
        if self._text is None:
            self._text = _decode_bytes(self.content)
        return self._text

    def json(self):
        t = self.text.strip()
        if t.startswith('\ufeff'):
            t = t[1:]
        return json.loads(t)


def _wrap_resp(r):
    """把宿主返回的响应对象统一成 Resp"""
    if r is None or isinstance(r, Resp):
        return r
    status = 200
    try:
        status = int(getattr(r, 'status_code', 200) or 200)
    except Exception:
        pass
    headers = {}
    try:
        h = getattr(r, 'headers', None)
        headers = dict(h) if h else {}
    except Exception:
        pass
    url = ''
    try:
        url = str(getattr(r, 'url', '') or '')
    except Exception:
        pass
    raw = None
    try:
        raw = r.content
    except Exception:
        raw = None
    if raw is None:
        try:
            return Resp(b'', text=str(r.text or ''), status=status, headers=headers, url=url)
        except Exception:
            return Resp(b'', status=status, headers=headers, url=url)
    if isinstance(raw, str):
        return Resp(raw, status=status, headers=headers, url=url)
    return Resp(raw, status=status, headers=headers, url=url)


def _opener():
    if _OPENER[0] is None:
        handlers = []
        try:
            handlers.append(_CookieProc(_CookieJar()))
        except Exception:
            pass
        if ssl is not None:
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                handlers.append(__import__('urllib.request', fromlist=['HTTPSHandler']).HTTPSHandler(context=ctx))
            except Exception:
                pass
        _OPENER[0] = _build_opener(*handlers)
    return _OPENER[0]


def _http(url, headers=None, timeout=10, data=None, method=None):
    """标准库 HTTP：不依赖宿主任何网络方法"""
    if not _URL_OK:
        raise IOError('urllib unavailable in this runtime')
    hd = {'User-Agent': random.choice(UAS)}
    hd.update(headers or {})
    body = None
    if data is not None:
        if isinstance(data, dict):
            body = _urlencode(data).encode('utf-8')
        elif isinstance(data, str):
            body = data.encode('utf-8')
        else:
            body = data
        method = method or 'POST'
    kw = {'headers': hd}
    if body is not None:
        kw['data'] = body
    if method:
        kw['method'] = method
    req = _Req(url, **kw)
    try:
        r = _opener().open(req, timeout=timeout)
    except Exception as e:
        # 4xx/5xx 也把响应体交回去（有些站点靠状态码判断后仍返回 JSON）
        code = getattr(e, 'code', None)
        if code is not None:
            try:
                return Resp(e.read(), status=code, url=url)
            except Exception:
                pass
        raise
    try:
        raw = r.read()
    finally:
        try:
            r.close()
        except Exception:
            pass
    try:
        st = int(getattr(r, 'status', 200) or 200)
    except Exception:
        st = 200
    return Resp(raw, status=st, url=url)


# 各站在线 homeContent 取不到分类时的兜底首分类（实测，2026-11）
DEFAULT_TID = {
    'douban': 'movie|热门', 'naifei': 'movie', 'juhe': 'douyin', 'kr': 'live', 'cj': 's1',
    'dj': 'new', 'k4': '1', 'wp': '1', 'api': 'random', 'xb': '剧集', 'app': '1', 'pk': '20',
    'emby': '109', 'iptv': '0', 'php': '2@直播', 't4': '1', 'music': 'kw_search', 'kids': '2',
    'ts': '6', 'fm': 'total', 'ys2': '521', 'xq': 'yuju',
}


def _norm_ext(extend):
    """extend 可能是 dict / JSON 字符串 / None / 其它壳形态"""
    if isinstance(extend, dict):
        return dict(extend)
    if isinstance(extend, str):
        t = extend.strip()
        if t.startswith('{'):
            try:
                d = json.loads(t)
                if isinstance(d, dict):
                    return d
            except Exception:
                pass
        return {}
    if isinstance(extend, (list, tuple)):
        try:
            return dict(extend)
        except Exception:
            return {}
    return {}


def _to_int(v, default=0):
    try:
        if v is True or v is False or v is None:
            return default
        return int(float(str(v).strip()))
    except Exception:
        return default


def _clean_play(r):
    """playerContent 只回 header/parse/url 三键，且类型正确"""
    url = ''
    parse = 0
    header = None
    if isinstance(r, dict):
        url = r.get('url') or r.get('playUrl') or ''
        parse = _to_int(r.get('parse'), 0)
        h = r.get('header')
        if isinstance(h, dict):
            header = dict((str(k), str(v)) for k, v in h.items())
    if not url and isinstance(r, str):
        url = r
    out = {'parse': 0 if parse <= 0 else 1, 'url': str(url or '')}
    if header:
        out['header'] = header
    return out

class _MiniSession(object):
    """给依赖 self.s 会话的子站垫一个最小 session"""
    def __init__(self):
        self.headers = {}
        self.cookies = {}

    def get(self, url, headers=None, timeout=15, **kw):
        hd = dict(self.headers)
        hd.update(headers or {})
        return _http(url, hd, timeout, cookies=kw.get('cookies'))

    def post(self, url, data=None, json=None, headers=None, timeout=15, **kw):
        hd = dict(self.headers)
        hd.update(headers or {})
        body = data
        if json is not None:
            body = _J.dumps(json, ensure_ascii=False)
            hd.setdefault('Content-Type', 'application/json; charset=utf-8')
        return _http(url, hd, timeout, data=body)

    def close(self):
        pass


# ---------- 宿主方法自适应（模块级，主站与子站共用） ----------
_J = json


def _mode_try(obj, calls, attr):
    order = list(range(len(calls)))
    cur = getattr(obj, attr, None)
    if isinstance(cur, int) and 0 <= cur < len(calls):
        order.remove(cur)
        order.insert(0, cur)
    for i in order:
        try:
            r = calls[i]()
        except TypeError:
            continue
        except Exception:
            return None
        if r is None:
            continue
        try:
            setattr(obj, attr, i)
        except Exception:
            pass
        return r
    return None


def _host_call(obj, name, url, hd, timeout, body=None):
    base = getattr(BaseSpider, name, None)
    flag = '_use_host_' + name
    cache = '_fmode' if name == 'fetch' else '_pmode'
    if base is None or not getattr(obj, flag, True):
        return None
    if name == 'fetch':
        calls = [lambda: base(obj, url, headers=hd, timeout=timeout),
                 lambda: base(obj, url, headers=hd),
                 lambda: base(obj, url, timeout),
                 lambda: base(obj, url)]
    else:
        calls = [lambda: base(obj, url, data=body, headers=hd, timeout=timeout),
                 lambda: base(obj, url, data=body, headers=hd),
                 lambda: base(obj, url, data=body),
                 lambda: base(obj, url, body)]
    r = _mode_try(obj, calls, cache)
    if r is None and getattr(obj, cache, None) is None:
        try:
            setattr(obj, flag, False)
        except Exception:
            pass
    return r


def _net_fetch(obj, url, headers=None, timeout=15, **kw):
    hd = {'User-Agent': random.choice(UAS)}
    hd.update(headers or {})
    r = _host_call(obj, 'fetch', url, hd, timeout)
    if r is not None:
        return _wrap_resp(r)
    return _http(url, hd, timeout)


def _net_post(obj, url, data=None, json=None, headers=None, timeout=15, **kw):
    hd = {'User-Agent': random.choice(UAS)}
    hd.update(headers or {})
    body = data
    if json is not None:
        body = _J.dumps(json, ensure_ascii=False)
        hd.setdefault('Content-Type', 'application/json; charset=utf-8')
    r = _host_call(obj, 'post', url, hd, timeout, body)
    if r is not None:
        return _wrap_resp(r)
    return _http(url, hd, timeout, data=body)


# ============================================================
#  依赖兜底：宿主没有 pycryptodome / requests 时补最小实现
#  （只在真实库缺失时安装，不覆盖宿主已有能力）
# ============================================================
_SBOX = (
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16)
_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i


def _gmul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xff
        if hi:
            a ^= 0x1b
        b >>= 1
    return p


def _aes_expand(key):
    nk = len(key) // 4
    if nk not in (4, 6, 8):
        raise ValueError('AES key must be 16/24/32 bytes')
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _gmul(rcon, 2)
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w, nr


def _aes_enc_block(w, nr, blk):
    s = [[blk[r + 4 * c] for c in range(4)] for r in range(4)]

    def ark(rnd):
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[rnd * 4 + c][r]

    ark(0)
    for rnd in range(1, nr):
        for r in range(4):
            for c in range(4):
                s[r][c] = _SBOX[s[r][c]]
        for r in range(1, 4):
            s[r] = s[r][r:] + s[r][:r]
        for c in range(4):
            a = [s[r][c] for r in range(4)]
            s[0][c] = _gmul(a[0], 2) ^ _gmul(a[1], 3) ^ a[2] ^ a[3]
            s[1][c] = a[0] ^ _gmul(a[1], 2) ^ _gmul(a[2], 3) ^ a[3]
            s[2][c] = a[0] ^ a[1] ^ _gmul(a[2], 2) ^ _gmul(a[3], 3)
            s[3][c] = _gmul(a[0], 3) ^ a[1] ^ a[2] ^ _gmul(a[3], 2)
        ark(rnd)
    for r in range(4):
        for c in range(4):
            s[r][c] = _SBOX[s[r][c]]
    for r in range(1, 4):
        s[r] = s[r][r:] + s[r][:r]
    ark(nr)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _aes_dec_block(w, nr, blk):
    s = [[blk[r + 4 * c] for c in range(4)] for r in range(4)]

    def ark(rnd):
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[rnd * 4 + c][r]

    ark(nr)
    for rnd in range(nr - 1, 0, -1):
        for r in range(1, 4):
            s[r] = s[r][-r:] + s[r][:-r]
        for r in range(4):
            for c in range(4):
                s[r][c] = _INV_SBOX[s[r][c]]
        ark(rnd)
        for c in range(4):
            a = [s[r][c] for r in range(4)]
            s[0][c] = _gmul(a[0], 14) ^ _gmul(a[1], 11) ^ _gmul(a[2], 13) ^ _gmul(a[3], 9)
            s[1][c] = _gmul(a[0], 9) ^ _gmul(a[1], 14) ^ _gmul(a[2], 11) ^ _gmul(a[3], 13)
            s[2][c] = _gmul(a[0], 13) ^ _gmul(a[1], 9) ^ _gmul(a[2], 14) ^ _gmul(a[3], 11)
            s[3][c] = _gmul(a[0], 11) ^ _gmul(a[1], 13) ^ _gmul(a[2], 9) ^ _gmul(a[3], 14)
    for r in range(1, 4):
        s[r] = s[r][-r:] + s[r][:-r]
    for r in range(4):
        for c in range(4):
            s[r][c] = _INV_SBOX[s[r][c]]
    ark(0)
    return bytes(s[r][c] for c in range(4) for r in range(4))


class _AESCipher(object):
    block_size = 16

    def ctr_xor(self, data, nonce, initial_value=0):
        data = data.encode('utf-8') if isinstance(data, str) else bytes(data)
        nonce = nonce if nonce is not None else b'\x00' * 12
        nonce = nonce.encode('utf-8') if isinstance(nonce, str) else bytes(nonce)
        nonce = nonce[-12:].rjust(12, b'\x00')
        out = bytearray()
        ctr = int(initial_value) & 0xffffffff
        for i in range(0, len(data), 16):
            ks = _aes_enc_block(self._w, self._nr, nonce + ctr.to_bytes(4, 'big'))
            out += bytes(a ^ b for a, b in zip(data[i:i + 16], ks))
            ctr = (ctr + 1) & 0xffffffff
        return bytes(out)

    def __init__(self, key, mode=1, iv=None):
        key = key.encode('utf-8') if isinstance(key, str) else bytes(key)
        self._w, self._nr = _aes_expand(key)
        self.mode = mode
        iv = iv if iv is not None else b'\x00' * 16
        self.iv = iv.encode('utf-8') if isinstance(iv, str) else bytes(iv)
        if len(self.iv) != 16:
            raise ValueError('IV must be 16 bytes')

    def _chunks(self, data):
        data = data.encode('utf-8') if isinstance(data, str) else bytes(data)
        if len(data) % 16:
            raise ValueError('Data must be padded to 16 byte boundary')
        return data

    def encrypt(self, data):
        data = self._chunks(data)
        out = b''
        prev = self.iv
        for i in range(0, len(data), 16):
            blk = data[i:i + 16]
            if self.mode == _MODE_CBC:
                blk = bytes(a ^ b for a, b in zip(blk, prev))
            e = _aes_enc_block(self._w, self._nr, blk)
            out += e
            prev = e
        return out

    def decrypt(self, data):
        data = self._chunks(data)
        out = b''
        prev = self.iv
        for i in range(0, len(data), 16):
            blk = data[i:i + 16]
            d = _aes_dec_block(self._w, self._nr, blk)
            if self.mode == _MODE_CBC:
                d = bytes(a ^ b for a, b in zip(d, prev))
            out += d
            prev = blk
        return out


_MODE_ECB = 1
_MODE_CBC = 2
_MODE_CTR = 6
_MODE_GCM = 11


def _pkcs7_pad(data, block_size):
    data = data.encode('utf-8') if isinstance(data, str) else bytes(data)
    n = block_size - len(data) % block_size
    return data + bytes([n]) * n


def _pkcs7_unpad(data, block_size):
    data = bytes(data)
    if not data or len(data) % block_size:
        raise ValueError('Padding is incorrect.')
    n = data[-1]
    if n < 1 or n > block_size or data[-n:] != bytes([n]) * n:
        raise ValueError('Padding is incorrect.')
    return data[:-n]


def _der_tlv(b, i):
    tag = b[i]
    i += 1
    ln = b[i]
    i += 1
    if ln & 0x80:
        num = ln & 0x7f
        ln = int.from_bytes(b[i:i + num], 'big')
        i += num
    return tag, b[i:i + ln], i + ln


def _der_int(b):
    return int.from_bytes(b, 'big')


def _pem_body(pem):
    txt = pem.decode('utf-8', 'ignore') if isinstance(pem, (bytes, bytearray)) else str(pem)
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip() and '-----' not in ln]
    return base64.b64decode(''.join(lines))


class _RSAKey(object):
    def __init__(self, n, e=65537, d=None):
        self.n = n
        self.e = e
        self.d = d

    def size_in_bytes(self):
        return (self.n.bit_length() + 7) // 8


class _PKCS115(object):
    def __init__(self, key):
        self._key = key

    def encrypt(self, message):
        message = message.encode('utf-8') if isinstance(message, str) else bytes(message)
        k = self._key.size_in_bytes()
        pslen = k - len(message) - 3
        if pslen < 8:
            raise ValueError('Message too long')
        ps = bytes(random.choice(range(1, 256)) for _ in range(pslen))
        em = b'\x00\x02' + ps + b'\x00' + message
        return pow(int.from_bytes(em, 'big'), self._key.e, self._key.n).to_bytes(k, 'big')

    def decrypt(self, ciphertext, sentinel=None):
        k = self._key.size_in_bytes()
        c = bytes(ciphertext)
        if self._key.d is None or len(c) != k:
            return sentinel
        em = pow(int.from_bytes(c, 'big'), self._key.d, self._key.n).to_bytes(k, 'big')
        if em[0] != 0 or em[1] != 2:
            return sentinel
        idx = em.find(b'\x00', 2)
        if idx < 0:
            return sentinel
        return em[idx + 1:]


def _rsa_import_key(pem):
    der = _pem_body(pem)
    return _rsa_walk_der(der)


def _rsa_walk_der(der):
    _, body, _ = _der_tlv(der, 0)          # 外层 SEQUENCE
    tag, first, nxt = _der_tlv(body, 0)
    if tag == 0x02:
        nxt_tag = body[nxt:nxt + 1]
        if nxt_tag == b'\x30' and first and first[0] == 0:
            # PKCS#8：INTEGER 版本 + AlgorithmIdentifier + OCTET STRING(内含 PKCS#1)
            _, _, nxt = _der_tlv(body, nxt)          # 跳过 AlgorithmIdentifier
            otag, octets, _ = _der_tlv(body, nxt)     # OCTET STRING
            if otag == 0x04:
                return _rsa_walk_der(octets)
        # PKCS#1 RSAPrivateKey
        _, n, nxt = _der_tlv(body, nxt)
        _, e, nxt = _der_tlv(body, nxt)
        _, d, nxt = _der_tlv(body, nxt)
        return _RSAKey(_der_int(n), _der_int(e), _der_int(d))
    # SubjectPublicKeyInfo：AlgorithmIdentifier 已跳过，下一个是 BIT STRING
    tag, bits, nxt = _der_tlv(body, nxt)
    if tag != 0x03:
        raise ValueError('unsupported key format')
    inner = bits[1:]
    _, inner_body, _ = _der_tlv(inner, 0)
    _, n, i2 = _der_tlv(inner_body, 0)
    _, e, i2 = _der_tlv(inner_body, i2)
    return _RSAKey(_der_int(n), _der_int(e))


def _install_crypto_shim():
    """仅在宿主缺 pycryptodome 时补最小 AES/RSA/PKCS7/MD5"""
    try:
        from Crypto.Cipher import AES as _real_aes  # noqa: F401
        from Crypto.Util.Padding import pad as _real_pad  # noqa: F401
        return False
    except Exception:
        pass
    try:
        import hashlib as _hl
    except Exception:
        return False

    class _GCM(object):
        block_size = 16

        def __init__(self, cipher, nonce):
            self._c = cipher
            self.nonce = nonce

        def decrypt(self, ct):
            return self._c.ctr_xor(ct, self.nonce, 2)

        def decrypt_and_verify(self, ct, tag=b'', *a, **kw):
            return self._c.ctr_xor(ct, self.nonce, 2)

        encrypt = decrypt

        def encrypt_and_digest(self, data):
            return self._c.ctr_xor(data, self.nonce, 2), b'\x00' * 16

        def update(self, data):
            return self._c.ctr_xor(data, self.nonce, 2)

        def digest(self):
            return b'\x00' * 16

        def verify(self, tag):
            return True

    class _CTR(object):
        block_size = 16

        def __init__(self, cipher, nonce, initial_value):
            self._c = cipher
            self.nonce = nonce
            self.initial_value = initial_value

        def encrypt(self, data):
            return self._c.ctr_xor(data, self.nonce, self.initial_value)

        decrypt = encrypt

    class _AESMod(object):
        block_size = 16
        MODE_CBC = _MODE_CBC
        MODE_ECB = _MODE_ECB
        MODE_CTR = _MODE_CTR
        MODE_GCM = _MODE_GCM

        @staticmethod
        def new(key, mode=_MODE_ECB, iv=None, **kw):
            nonce = kw.get('nonce', None)
            if mode == _MODE_CTR:
                return _CTR(_AESCipher(key, _MODE_ECB), nonce, kw.get('initial_value', 0))
            if mode == _MODE_GCM:
                return _GCM(_AESCipher(key, _MODE_ECB), nonce if nonce is not None else b'\x00' * 12)
            return _AESCipher(key, mode, iv if iv is not None else kw.get('IV'))

    class _RSAMod(object):
        @staticmethod
        def import_key(pem):
            return _rsa_import_key(pem)

    class _MD5Mod(object):
        @staticmethod
        def new(data=b''):
            return _hl.md5(data.encode('utf-8') if isinstance(data, str) else bytes(data))

    cipher_mod = types.ModuleType('Crypto.Cipher')
    cipher_mod.AES = _AESMod
    cipher_mod.PKCS1_v1_5 = types.SimpleNamespace(new=lambda key: _PKCS115(key))
    util_mod = types.ModuleType('Crypto.Util')
    pad_mod = types.ModuleType('Crypto.Util.Padding')
    pad_mod.pad = _pkcs7_pad
    pad_mod.unpad = _pkcs7_unpad
    pk_mod = types.ModuleType('Crypto.PublicKey')
    rsa_mod = types.ModuleType('Crypto.PublicKey.RSA')
    rsa_mod.import_key = _RSAMod.import_key
    hash_mod = types.ModuleType('Crypto.Hash')
    md5_mod = types.ModuleType('Crypto.Hash.MD5')
    md5_mod.new = _MD5Mod.new
    hash_mod.MD5 = md5_mod
    pk_mod.RSA = rsa_mod
    util_mod.Padding = pad_mod
    pkg = types.ModuleType('Crypto')
    pkg.__path__ = []
    pkg.Cipher = cipher_mod
    pkg.Util = util_mod
    pkg.PublicKey = pk_mod
    pkg.Hash = hash_mod
    for name, m in (('Crypto', pkg), ('Crypto.Cipher', cipher_mod), ('Crypto.Util', util_mod),
                    ('Crypto.Util.Padding', pad_mod), ('Crypto.PublicKey', pk_mod),
                    ('Crypto.PublicKey.RSA', rsa_mod), ('Crypto.Hash', hash_mod), ('Crypto.Hash.MD5', md5_mod)):
        sys.modules[name] = m
    return True


def _install_requests_shim():
    """仅在宿主缺 requests 时补最小实现（含 Session / utils.quote）"""
    try:
        import requests as _real  # noqa: F401
        return False
    except Exception:
        pass
    if not _URL_OK:
        return False
    mod = types.ModuleType('requests')

    class _Session(object):
        def __init__(self):
            self.headers = {}
            self.cookies = {}

        def _merge(self, headers):
            hd = dict(self.headers)
            hd.update(headers or {})
            return hd

        def get(self, url, headers=None, timeout=10, **kw):
            return _http(url, self._merge(headers), timeout)

        def post(self, url, data=None, json=None, headers=None, timeout=10, **kw):
            body = data
            if json is not None:
                body = _J.dumps(json, ensure_ascii=False)
                headers = dict(headers or {})
                headers.setdefault('Content-Type', 'application/json; charset=utf-8')
            return _http(url, self._merge(headers), timeout, data=body)

        def close(self):
            pass

    utils = types.SimpleNamespace(quote=lambda s, safe='/': __import__('urllib.parse', fromlist=['quote']).quote(str(s), safe=safe))
    mod.Session = _Session
    mod.session = lambda: _Session()
    mod.get = lambda url, **kw: _Session().get(url, **kw)
    mod.post = lambda url, **kw: _Session().post(url, **kw)
    mod.utils = utils
    mod.exceptions = types.SimpleNamespace(RequestException=Exception, Timeout=Exception, ConnectionError=Exception)
    sys.modules['requests'] = mod
    return True


try:
    _install_crypto_shim()
except Exception:
    pass
try:
    _install_requests_shim()
except Exception:
    pass


class Spider(BaseSpider):
    def getName(self):
        return '裤佬全家桶'

    def init(self, *a, **k):
        self.subs = {}
        self.home_cache = {}
        self.home_try = {}
        self.lock = threading.Lock()
        self.meta = {s[0]: s for s in SITES}
        self._fmode = None
        self._pmode = None
        self._use_host_fetch = hasattr(BaseSpider, 'fetch')
        self._use_host_post = hasattr(BaseSpider, 'post')
        self.cache_dir = os.path.join(tempfile.gettempdir(), 'kuolao_qjt')
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception:
            pass

    # ---------- 网络：宿主方法优先（签名自适应），失败走标准库 ----------
    def fetch(self, url, headers=None, timeout=10, **kw):
        return _net_fetch(self, url, headers, timeout, **kw)

    def post(self, url, data=None, json=None, headers=None, timeout=10, **kw):
        return _net_post(self, url, data, json, headers, timeout, **kw)

    # ---------- 子站加载 ----------
    def _py_source(self, key, url):
        path = os.path.join(self.cache_dir, key + '.py')
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
            try:
                with open(path, encoding='utf-8', errors='ignore') as f:
                    txt = f.read()
                if 'class Spider' in txt:
                    return txt
            except Exception:
                pass
        emb = _embed().get(key) or ''
        if emb:
            # 内置副本先顶上，保证首屏不等网络；后台静默更新，下次启动生效
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(emb)
            except Exception:
                pass
            try:
                if not hasattr(self, '_refreshing'):
                    self._refreshing = set()
                if key not in self._refreshing:
                    self._refreshing.add(key)
                    threading.Thread(target=self._refresh_py, args=(key, url, path), daemon=True).start()
            except Exception:
                pass
            return emb
        try:
            r = self.fetch(url, {'User-Agent': 'okhttp/4.12.0'}, timeout=20)
            txt = r.text or ''
            if 'class Spider' in txt:
                try:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(txt)
                except Exception:
                    pass
                return txt
        except Exception:
            pass
        return ''

    def _refresh_py(self, key, url, path):
        try:
            r = self.fetch(url, {'User-Agent': 'okhttp/4.12.0'}, timeout=20)
            txt = r.text or ''
            if 'class Spider' in txt:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(txt)
        except Exception:
            pass

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
                        # 子站自身的网络方法换成兼容版（返回带 .json() 的 Resp）
                        cls = type(obj)
                        if 'fetch' not in cls.__dict__:
                            try:
                                obj.fetch = types.MethodType(_net_fetch, obj)
                            except Exception:
                                pass
                        if 'post' not in cls.__dict__:
                            try:
                                obj.post = types.MethodType(_net_post, obj)
                            except Exception:
                                pass
                        try:
                            orig = obj.getProxyUrl

                            def gp(*a, _o=orig, _k=key, **k):
                                return _o(*a, **k) + '&klsite=' + _k
                            obj.getProxyUrl = gp
                        except Exception:
                            pass
                        if not hasattr(obj, 's'):
                            try:
                                import requests as _rq
                                obj.s = _rq.Session()
                            except Exception:
                                obj.s = _MiniSession()
                        try:
                            obj.init('')
                        except TypeError:
                            try:
                                obj.init()
                            except Exception:
                                pass
                        except Exception:
                            pass
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
            f = getattr(s, fn)
        except Exception:
            return {}
        variants = [a]
        # 宿主/子站签名差异：参数多了少了都再试一次
        if a:
            variants.append(a[:-1])
        for args in variants:
            try:
                r = f(*args)
                if isinstance(r, str):
                    r = json.loads(r) if r.strip().startswith('{') else {}
                return r or {}
            except TypeError:
                continue
            except Exception:
                return {}
        return {}

    def _bounded(self, fn, timeout=12, default=None):
        """站点卡死时不让整个分类陪着等"""
        box = {}

        def run():
            try:
                box['r'] = fn()
            except Exception:
                box['r'] = default
        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            return default
        return box.get('r', default)

    # ---------- 工具 ----------
    def wrap(self, key, vods, relax=False):
        out = []
        for v in vods or []:
            if not isinstance(v, dict):
                continue
            vid = str(v.get('vod_id', '') or '').strip()
            name = str(v.get('vod_name', '') or '')
            if not vid or vid.startswith('pinned'):
                continue
            if any(w in name for w in BLOCK_WORDS):
                continue
            if not relax and PROMO.search(name):
                continue
            x = dict(v)
            x['vod_id'] = key + SEP + vid
            x['vod_name'] = name
            if not x.get('vod_pic'):
                x['vod_pic'] = ''
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
        h = self.home_cache.get(key) or {}
        if h.get('class'):
            return h
        # 冷却：站点故障时别每翻一页都重试
        if time.time() - self.home_try.get(key, 0) < 90:
            return h
        self.home_try[key] = time.time()
        r = self.call(key, 'homeContent', True)
        cls = []
        for c in (r.get('class') or []):
            if not isinstance(c, dict):
                continue
            tid = str(c.get('type_id', c.get('id', '')) or '').strip()
            nm = str(c.get('type_name', c.get('name', '')) or '').strip()
            if not tid or not nm:
                continue
            if PROMO.search(nm) or any(w in nm for w in BLOCK_WORDS):
                continue
            cls.append({'type_id': tid, 'type_name': nm})
        fl = r.get('filters') if isinstance(r.get('filters'), dict) else {}
        if cls:
            self.home_cache[key] = {'class': cls, 'filters': fl}
        elif key not in self.home_cache:
            self.home_cache[key] = {'class': [], 'filters': {}}
        return self.home_cache.get(key) or h

    # ---------- 首页 ----------
    def _home_file(self):
        return os.path.join(self.cache_dir, 'home.json')

    def _load_home_disk(self):
        try:
            with open(self._home_file(), encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _save_home(self, futs, disk):
        last = {}
        end = time.time() + 25
        while time.time() < end:
            try:
                wait(list(futs), timeout=1)
            except Exception:
                time.sleep(1)
            good = {k: v for k, v in self.home_cache.items() if isinstance(v, dict) and v.get('class')}
            for k, v in disk.items():
                good.setdefault(k, v)
            if good and good != last:
                last = dict(good)
                try:
                    with open(self._home_file(), 'w', encoding='utf-8') as f:
                        json.dump(good, f, ensure_ascii=False)
                except Exception:
                    pass
            if all(f.done() for f in futs):
                break

    def homeContent(self, *a, **k):
        keys = [s[0] for s in SITES]
        disk = self._load_home_disk()
        pool = ThreadPoolExecutor(max_workers=min(10, len(keys)))
        futs = {}
        for key in keys:
            try:
                futs[pool.submit(self.site_home, key)] = key
            except Exception:
                pass
        # 首屏必须快：有磁盘缓存等 2 秒，首次最多 4 秒，超出后台继续刷新
        wait(list(futs), timeout=2 if disk else 4)
        pool.shutdown(wait=False)
        for k_, v_ in disk.items():
            cur = self.home_cache.get(k_)
            if not (cur or {}).get('class') and isinstance(v_, dict):
                if v_.get('class'):
                    self.home_cache[k_] = v_
                else:
                    self.home_cache.setdefault(k_, v_)
        try:
            threading.Thread(target=self._save_home, args=(list(futs), disk), daemon=True).start()
        except Exception:
            pass

        classes, filters = [], {}
        for s in SITES:
            key, name = s[0], s[1]
            classes.append({'type_id': key, 'type_name': name})
            h = self.home_cache.get(key) or {}
            cls = h.get('class') or []
            if not cls:
                dft = DEFAULT_TID.get(key)
                if not dft:
                    continue
                cls = [{'type_id': dft, 'type_name': '默认'}]
            values = [{'n': str(c['type_name']), 'v': str(c['type_id'])} for c in cls]
            fl = [{'key': '__c', 'name': '分类', 'value': values}]
            first = str(cls[0]['type_id'])
            seen = {'__c'}
            for g in (h.get('filters') or {}).get(first, []) or []:
                try:
                    if not isinstance(g, dict) or not g.get('key') or g.get('key') in seen:
                        continue
                    vals = []
                    for it in (g.get('value') or []):
                        if isinstance(it, dict) and it.get('v') not in (None, ''):
                            vals.append({'n': str(it.get('n', it.get('v'))), 'v': str(it.get('v'))})
                        elif isinstance(it, str) and it:
                            vals.append({'n': it, 'v': it})
                    if not vals:
                        continue
                    seen.add(g['key'])
                    fl.append({'key': str(g['key']), 'name': str(g.get('name', g['key'])), 'value': vals})
                except Exception:
                    continue
            filters[key] = fl
        return {'class': classes, 'filters': filters}

    def homeVideoContent(self):
        out = []
        for key in ('naifei', 'app', 'pk'):
            try:
                out += self.wrap(key, self.call(key, 'homeVideoContent').get('list', []))[:12]
            except Exception:
                continue
        return {'list': out}

    def homeVod(self):
        try:
            return self.homeVideoContent()
        except Exception:
            return {'list': []}

    # ---------- 分类 ----------
    def _cat_pack(self, lst, r, pg):
        page = _to_int(r.get('page'), _to_int(pg, 1)) or 1
        pc = _to_int(r.get('pagecount'), 0) or (page + (1 if lst else 0))
        lim = _to_int(r.get('limit'), 20) or 20
        tot = _to_int(r.get('total'), 0) or 9999
        return {'list': lst, 'page': page, 'pagecount': max(pc, page), 'limit': lim, 'total': tot}

    def categoryContent(self, tid, pg='1', filter=True, extend=None, *a, **k):
        key = str(tid or '').strip()
        if SEP in key:
            key = key.split(SEP, 1)[0]
        if not key:
            return {'list': [], 'page': 1, 'pagecount': 1}
        ext = _norm_ext(extend)
        if not ext:
            ext = _norm_ext(filter)
        h = self._bounded(lambda: self.site_home(key), 6, {}) or {}
        classes = [c for c in (h.get('class') or []) if str(c.get('type_id', '')).strip()]
        sub_tid = str(ext.pop('__c', '') or '').strip()
        page_s = str(pg or '1')

        # 用户明确选了站内分类：只认它，失败也不串台
        if sub_tid:
            r = self._bounded(lambda: self.call(key, 'categoryContent', sub_tid, page_s, True, dict(ext)), 12, {}) or {}
            lst = self.wrap(key, r.get('list') or [])
            if not lst and r.get('list'):
                lst = self.wrap(key, r.get('list') or [], relax=True)
            return self._cat_pack(lst, r, pg)

        cands, seen = [], set()
        for t in ([str(classes[0]['type_id'])] if classes else []) + [DEFAULT_TID.get(key) or '', '']:
            t = str(t or '').strip()
            if t not in seen:
                seen.add(t)
                cands.append(t)
        raw_backup = None
        for t in cands[:3]:
            r = self._bounded(lambda: self.call(key, 'categoryContent', t, page_s, True, dict(ext)), 12, {}) or {}
            raw = r.get('list') or []
            lst = self.wrap(key, raw)
            if lst:
                return self._cat_pack(lst, r, pg)
            if raw and raw_backup is None:
                raw_backup = (raw, r)
        if raw_backup:
            # 有原始数据但全被广告/敏感词过滤掉了 → 放宽到只拦成人分类
            lst = self.wrap(key, raw_backup[0], relax=True)
            return self._cat_pack(lst, raw_backup[1], pg)
        return {'list': [], 'page': _to_int(pg, 1) or 1, 'pagecount': 1, 'limit': 20, 'total': 0}

    # ---------- 详情 ----------
    def detailContent(self, ids, *a, **k):
        if isinstance(ids, (list, tuple)):
            ids = [str(x) for x in ids if str(x or '').strip()]
        else:
            ids = [str(ids or '')]
        if not ids:
            return {'list': []}
        first = ids[0]
        if SEP not in first:
            return {'list': []}
        key, vid = first.split(SEP, 1)
        if key == 'douban':
            r = self.call(key, 'detailContent', [vid])
            return r if r.get('list') else {'list': []}
        r = self.call(key, 'detailContent', [vid])
        lst = r.get('list') or []
        if not lst or not isinstance(lst[0], dict):
            return {'list': []}
        vod = dict(lst[0])
        vod['vod_id'] = first
        return {'list': [self.wrap_play(key, vod)]}

    def find_play(self, title):
        """豆瓣片名 → 去影视站搜同名，合并线路"""
        cands = ['naifei', 'app', 'pk', 'ys', 'xb', 'cj', 'k4']
        found = []

        def one(k):
            try:
                for v in self.call(k, 'searchContent', title, False, '1').get('list', [])[:10]:
                    n = re.sub(r'^【[^】]*】', '', str(v.get('vod_name', ''))).strip()
                    if n == title:
                        d = self.call(k, 'detailContent', [str(v['vod_id'])]).get('list') or []
                        if d and d[0].get('vod_play_url'):
                            return k, d[0]
            except Exception:
                return None
            return None
        pool = ThreadPoolExecutor(max_workers=7)
        futs = [pool.submit(one, k) for k in cands]
        wait(futs, timeout=20)
        pool.shutdown(wait=False)
        for f in futs:
            try:
                if f.done() and f.result():
                    found.append(f.result())
            except Exception:
                continue
        if not found:
            return {'list': [{'vod_id': 'douban' + SEP + title, 'vod_name': title,
                              'vod_content': '各站暂未搜到可播放的同名片源，可用搜索换个片名试试',
                              'vod_play_from': '无', 'vod_play_url': f'暂无$douban{SEP}none'}]}
        base = dict(found[0][1])
        froms, urls = [], []
        for k_, d in found:
            w = self.wrap_play(k_, dict(d))
            for f_, u_ in zip(str(d.get('vod_play_from', '')).split('$$$'), w['vod_play_url'].split('$$$')):
                froms.append(f'{self.meta[k_][1]}-{f_}')
                urls.append(u_)
        base.update({'vod_id': 'douban' + SEP + title, 'vod_name': title,
                     'vod_play_from': '$$$'.join(froms), 'vod_play_url': '$$$'.join(urls)})
        return {'list': [base]}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick=False, pg='1', *a, **k):
        kw = str(key or '').strip()
        page_s = str(pg or '1')
        if not kw:
            return {'list': [], 'page': 1, 'pagecount': 1}
        keys = [s[0] for s in SITES if s[4]]
        res = {}

        def one(kk):
            try:
                res[kk] = self.wrap(kk, self.call(kk, 'searchContent', kw, quick, page_s).get('list', []))[:30]
            except Exception:
                res[kk] = []
        pool = ThreadPoolExecutor(max_workers=10)
        futs = [pool.submit(one, kk) for kk in keys]
        wait(futs, timeout=15)
        pool.shutdown(wait=False)
        out = []
        for kk in keys:
            for v in res.get(kk, []):
                v['vod_name'] = f'【{self.meta[kk][1]}】' + str(v.get('vod_name', ''))
                out.append(v)
        return {'list': out, 'page': _to_int(pg, 1) or 1,
                'pagecount': (_to_int(pg, 1) or 1) + (1 if out else 0)}

    def searchContentPage(self, key, quick, pg, *a, **k):
        return self.searchContent(key, quick, pg)

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags=None, *a, **k):
        sid = str(id or '')
        if SEP not in sid:
            return _clean_play(direct_or_parse(sid))
        key, pid = sid.split(SEP, 1)
        if not pid:
            return _clean_play(direct_or_parse(sid))
        if key == 'douban':
            return {'parse': 1, 'url': ''}
        r = self.call(key, 'playerContent', flag, pid, vipFlags)
        if not r or not r.get('url'):
            return _clean_play(direct_or_parse(pid))
        out = _clean_play(r)
        if not out.get('url'):
            return _clean_play(direct_or_parse(pid))
        if 'header' not in out:
            out['header'] = {'User-Agent': UAS[2]}
        return out

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv|mkv)(\?|$)', str(url or ''), re.I))

    def manualVideoCheck(self):
        pass

    def localProxy(self, param):
        if isinstance(param, str):
            d = {}
            try:
                for kv in param.split('&'):
                    if '=' in kv:
                        k_, v_ = kv.split('=', 1)
                        d[k_] = v_
            except Exception:
                d = {}
            param = d
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

    def liveContent(self, url='', *a, **k):
        return ''

    def destroy(self, *a, **k):
        for s in self.subs.values():
            try:
                s.destroy()
            except Exception:
                pass

# ============================================================
#  内置子站脚本（zlib+base64）：远程地址取不到时兜底，保证分类不空
#  源：https://jsnz.pages.dev/f/ 对应脚本的离线副本
# ============================================================
_EMBED_RAW = """
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
dzJyBeQkgXtMfRz3p+MtWYouLKhBYZv5jiq53du+sPkxwvLVLeJ3Z9OvaVFfzy3l8oZiPJzjNjt623/8Qhd1xVmJhtSrWNMQK63fzbIVXIstxXI+WfVNO50szAUqIm4H+lvmijOQKBsnX+GxpcKUbBoGHM6X+nRfmXyyUEvmSNowmUlNeckaMCu0XBETVu+WcmNjTB/P
ENrgbVKaO+DrbtJKbk3U95pSbTIg1CDlvTHzZo0dhIq7hF0fFVkVT8cIUUByjmjR5yJk7d42sjeamI4m1riL766N5bIphuOixp69w+5Sr1azufBudknGpNBUsJRkxL1WYB+egyZnDqd79oM17z2F/8UUo01MjkZ27dyy9SU1+gayGTvtCIeNf/y4fPsThVSxzSnASWV2
bH1pfMdw5KWRvW+9tHfrWO+mVza/OPzKq8PDfS/tHN408mL2lW0vTrwyUh7Ye+DNyf1vzK0uV+aS0W2RddWBdM+2NZHS61uKL05NvPrWjtK2XdnXV/du3fzatnRfZl96emLdnr279r8y0DM1V9rev2fdi4VKvrw3+tpApW/3a5tm9r8y9mr1jcl9u3ePrHv5QLT/rTfW
lkub+vORdM90ObKu+9XS66+sqe2aW7d7T+SVfZBPcjrz5upNWzPr9qd6R1YfeHGk1j315t43uvcMVKoz/1PMZqtT2d6Jma2bhl8ZflGbdX5vcpzR7zSHzGuRvr+88ubON/a8vrN/X+R/dm16c8vW4ZfWjOx788Xe3fsiQ1ptoKZbeQDLXSPR4Uj/5ui6tZu3RCMjW3q3
9EfWDIwMrx0eiPS+uGazDu4p7lLAjqhwen9udjYXnk3NpQ9M7ddKUvht+XRLHoh2RfvW9Pev61kTibBDDjjsrolasjBxYLJYC+fn3kIvIzz+WOFwFeIMKI1OO9iwFv0ierQCDk+2fP7T+pETfVMh+iKuF5JFTOPm2ZWrPzc+vdr44NbvD44v3j3DpdEojWPnkrX46NPG
qcOLdw8tH/sJ03JCxd3DL21O7N36Jhjg90Sd5iikHW+C8ZXEHVsrx04tffIOpDa98TOoogNL1y+tHDqxcuFGyKKvjc+PrXzxUVC0w97Uz51eunBt8e51dpH//cGp+rlTjYu/6KJdq37kQf3Gr8vv3mal6se/Z5WoCR4JbsvWzds37UV/ioJkjidleK2f+BZicCnfZa7T
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
"""
_EMBED = [None]


def _embed():
    if _EMBED[0] is None:
        try:
            _EMBED[0] = json.loads(zlib.decompress(base64.b64decode(_EMBED_RAW.strip())).decode('utf-8'))
        except Exception:
            _EMBED[0] = {}
    return _EMBED[0]
