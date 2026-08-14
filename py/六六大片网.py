# -*- coding: utf-8 -*-
#QQ群:807916734
# FongMi/TVBox Python Spider - 66大片网 (www.66dpw.vip)
# 站点：苹果CMS(MacCMS) 老式路由 + nginx
# 接口：
#   分类   : /vodtype/{tid}(-{pg}).html            → HTML 解析(module-poster-item)
#   搜索   : /index.php/ajax/suggest?mid=1&wd=     → 免验证码 JSON（vodsearch 页被验证码拦截）
#   详情   : /voddetail/{id}.html                  → module-tab-item 线路 + module-play-list 集数
#   播放   : /vodplay/{id}-{sid}-{nid}.html        → player_aaaa 双重base64
#   - 极速线路(jsm3u8) : 解密即 m3u8 直链
#   - 官方线路(qq/youku/qiyi/bilibili/mgtv) : 官方页 → svip.qlplayer.cyou/?url= → apiToken
#     → api/resolve.php?token= → JSON url 直链
import re, json, base64
from urllib.parse import urljoin, quote, unquote
try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        def fetch(self, url, headers=None, timeout=15, **kwargs):
            import requests
            return requests.get(url, headers=headers, timeout=timeout, verify=False)
        def post(self, url, headers=None, data=None, timeout=15, **kwargs):
            import requests
            return requests.post(url, headers=headers, data=data, timeout=timeout, verify=False)

class Spider(BaseSpider):
    def __init__(self):
        self.host = 'https://www.66dpw.vip'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': self.host + '/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        self.classes = [
            {'type_id': '1',  'type_name': '电影'},
            {'type_id': '3',  'type_name': '剧集'},
            {'type_id': '4',  'type_name': '短剧'},
            {'type_id': '2',  'type_name': '动漫'},
            {'type_id': '5',  'type_name': '综艺'},
            {'type_id': '14', 'type_name': '电影·剧情'},
            {'type_id': '10', 'type_name': '电影·动作'},
            {'type_id': '13', 'type_name': '电影·喜剧'},
            {'type_id': '12', 'type_name': '电影·爱情'},
            {'type_id': '8',  'type_name': '电影·科幻奇幻'},
            {'type_id': '9',  'type_name': '电影·恐怖惊悚'},
            {'type_id': '11', 'type_name': '电影·战争'},
            {'type_id': '15', 'type_name': '纪录片'},
            {'type_id': '22', 'type_name': '剧集·国产'},
            {'type_id': '27', 'type_name': '剧集·欧美'},
            {'type_id': '23', 'type_name': '剧集·日剧'},
            {'type_id': '24', 'type_name': '剧集·韩剧'},
            {'type_id': '25', 'type_name': '剧集·港剧'},
            {'type_id': '26', 'type_name': '剧集·台剧'},
            {'type_id': '16', 'type_name': '动漫·国产'},
            {'type_id': '17', 'type_name': '动漫·日本'},
            {'type_id': '21', 'type_name': '动漫·欧美'},
            {'type_id': '28', 'type_name': '综艺·大陆'},
            {'type_id': '30', 'type_name': '综艺·日韩'},
            {'type_id': '29', 'type_name': '综艺·港台'},
            {'type_id': '31', 'type_name': '综艺·欧美'},
        ]
        # 官方源线路 → qlplayer 解析器
        self.PARSE_HOST = 'https://svip.qlplayer.cyou'
        self.OFFICIAL_FROM = {'qq', 'youku', 'qiyi', 'bilibili', 'mgtv'}

    def getName(self): return '66大片网'
    def getDependence(self): return []
    def init(self, extend=''): pass
    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv|mkv|ts)(\?|$)', str(url), re.I))
    def manualVideoCheck(self): return True
    def action(self, action): return None
    def destroy(self): pass
    def liveContent(self, url): return {'list': []}
    def localProxy(self, param): return [404, 'text/plain', 'Not Found']

    def log(self, msg):
        try: print('[66大片网] ' + str(msg))
        except Exception: pass

    def getHtml(self, url, referer=None):
        if not str(url).startswith('http'): url = urljoin(self.host, url)
        h = dict(self.headers)
        if referer: h['Referer'] = referer
        try:
            r = self.fetch(url, headers=h, timeout=15)
            if hasattr(r, 'content'):
                enc = getattr(r, 'encoding', None) or 'utf-8'
                return r.content.decode(enc, 'ignore')
            return getattr(r, 'text', '') or ''
        except Exception as e:
            self.log('请求失败 %s %s' % (url, e)); return ''

    def clean(self, s):
        s = str(s or '')
        s = re.sub(r'<script[\s\S]*?</script>|<style[\s\S]*?</style>', ' ', s, flags=re.I)
        s = re.sub(r'<[^>]+>', ' ', s)
        s = s.replace('\xa0', ' ').replace('&nbsp;', ' ')
        return re.sub(r'\s+', ' ', s).strip()

    def fix(self, u):
        if not u: return ''
        u = str(u).replace('\\/', '/').strip()
        if u.startswith('//'): u = 'https:' + u
        return urljoin(self.host, u)

    # ---------------- 首页 / 分类 ----------------
    def homeContent(self, filter):
        return {'class': self.classes, 'filters': self.makeFilters() if filter else {}}

    def makeFilters(self):
        years = [{'n': '全部', 'v': ''}] + [{'n': str(y), 'v': str(y)} for y in range(2026, 2004, -1)]
        areas = [{'n': '全部', 'v': ''}] + [{'n': x, 'v': x} for x in
                 ['大陆', '香港', '台湾', '美国', '韩国', '日本', '泰国', '新加坡', '马来西亚', '印度', '英国', '法国', '德国', '俄罗斯', '西班牙', '加拿大', '其它']]
        bys = [{'n': '时间', 'v': 'time'}, {'n': '人气', 'v': 'hits'}, {'n': '评分', 'v': 'score'}]
        fs = [
            {'key': 'area', 'name': '地区', 'value': areas},
            {'key': 'year', 'name': '年份', 'value': years},
            {'key': 'by', 'name': '排序', 'value': bys},
        ]
        return {c['type_id']: fs for c in self.classes}

    def extractMainList(self, txt):
        """括号配平提取 module-main 主列表容器（排除页面推荐模块）"""
        start = (txt or '').find('<div class="module-main')
        if start < 0: return txt or ''
        depth = 0; i = start
        in_tag = in_q = False; q = ''
        while i < len(txt):
            c = txt[i]
            if in_q:
                if c == q: in_q = False
            elif in_tag:
                if c in '"\'': in_q = True; q = c
                elif c == '>': in_tag = False
            else:
                if c == '<':
                    in_tag = True
                    if txt[i:i+6] == '</div>':
                        depth -= 1
                        if depth == 0:
                            return txt[start:i+6]
                        i += 5
                    elif txt[i:i+4] == '<div':
                        depth += 1; i += 3
            i += 1
        return txt or ''

    def parseList(self, txt):
        """MacCMS module-poster-item 卡片（仅主列表区域）"""
        txt = self.extractMainList(txt)
        vods, seen = [], set()
        for m in re.finditer(
                r'<a[^>]*href="(/voddetail/(\d+)\.html)"[^>]*title="([^"]*)"'
                r'[^>]*class="[^"]*module-poster-item[^"]*"[^>]*>([\s\S]*?)</a>', txt or '', re.I):
            vid = m.group(2)
            if vid in seen: continue
            seen.add(vid)
            block = m.group(4)
            pm = re.search(r'data-original="([^"]*)"', block)
            rm = re.search(r'class="[^"]*module-item-note[^"]*"[^>]*>([\s\S]*?)<', block)
            vods.append({
                'vod_id': vid,
                'vod_name': self.clean(m.group(3)),
                'vod_pic': self.fix(pm.group(1)) if pm else '',
                'vod_remarks': self.clean(rm.group(1)) if rm else '',
            })
        if not vods:  # 兜底：仅链接
            for m in re.finditer(r'href="/voddetail/(\d+)\.html"[^>]*title="([^"]*)"', txt or ''):
                vid = m.group(1)
                if vid in seen: continue
                seen.add(vid)
                vods.append({'vod_id': vid, 'vod_name': self.clean(m.group(2)),
                             'vod_pic': '', 'vod_remarks': ''})
        return vods

    # ---------------- 首页 / 分类（ajax/data 接口，30条/页，支持筛选） ----------------
    def ajaxList(self, tid, pg, limit=30, ext=None):
        ext = ext or {}
        qs = 'mid=1&tid=%s&page=%s&limit=%d' % (tid, str(pg or 1), limit)
        for k in ('area', 'year', 'lang', 'letter', 'by', 'class'):
            if ext.get(k):
                qs += '&%s=%s' % (k, quote(str(ext[k]), safe=''))
        txt = self.getHtml(self.host + '/index.php/ajax/data?' + qs)
        try:
            d = json.loads(txt)
        except Exception:
            return [], 1
        if d.get('code') != 1:
            return [], 1
        lst = []
        for v in (d.get('list') or []):
            lst.append({
                'vod_id': str(v.get('vod_id', '')),
                'vod_name': v.get('vod_name', ''),
                'vod_pic': (v.get('vod_pic') or '').replace('\\/', '/'),
                'vod_remarks': v.get('vod_remarks', ''),
            })
        return lst, int(d.get('pagecount', 1) or 1)

    def homeVideoContent(self):
        # 全站最新（tid=0），电影/剧集/动漫/综艺混合
        lst, _ = self.ajaxList('0', 1, 30)
        if not lst:
            lst = self.parseList(self.getHtml(self.host + '/vodtype/1.html'))[:30]
        return {'list': lst}

    def categoryContent(self, tid, pg, filter, extend):
        pg = str(pg or '1')
        ext = extend or {}
        # 主路径：ajax/data 接口（30条/页，翻页干净，支持筛选）
        lst, pagecount = self.ajaxList(tid, pg, 30, ext)
        if lst:
            return {'list': lst, 'page': int(pg), 'pagecount': pagecount,
                    'limit': len(lst), 'total': pagecount * 30}
        # 兜底：HTML 主列表解析
        if not ext:
            url = self.host + '/vodtype/%s.html' % tid
            if pg != '1':
                url = self.host + '/vodtype/%s-%s.html' % (tid, pg)
            vods = self.parseList(self.getHtml(url))
            return {'list': vods, 'page': int(pg), 'pagecount': 999999 if vods else int(pg),
                    'limit': len(vods), 'total': 999999 if vods else 0}
        return {'list': [], 'page': int(pg), 'pagecount': int(pg), 'limit': 0, 'total': 0}

    # ---------------- 搜索（AJAX suggest 免验证码） ----------------
    def searchContent(self, key, quick, pg='1'):
        txt = self.getHtml(self.host + '/index.php/ajax/suggest?mid=1&wd=%s&limit=30' % quote(str(key)))
        try:
            d = json.loads(txt)
        except Exception:
            return {'list': []}
        vods = []
        for v in (d.get('list') or []):
            vods.append({
                'vod_id': str(v.get('id', '')),
                'vod_name': v.get('name', ''),
                'vod_pic': (v.get('pic') or '').replace('\\/', '/'),
                'vod_remarks': '',
            })
        return {'list': vods, 'page': int(pg or 1), 'pagecount': 1, 'limit': len(vods), 'total': len(vods)}

    # ---------------- 详情 ----------------
    def detailContent(self, ids):
        url = str(ids[0])
        if re.fullmatch(r'\d+', url):
            url = self.host + '/voddetail/%s.html' % url
        txt = self.getHtml(url, self.host + '/')
        mt = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', txt, re.I)
        title = self.clean(mt.group(1)) if mt else ''
        pm = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]*)"', txt, re.I)
        pic = self.fix(pm.group(1)) if pm else ''
        cm = re.search(r'<meta[^>]*property="og:description"[^>]*content="([^"]*)"', txt, re.I)
        content = self.clean(cm.group(1)) if cm else ''
        # 线路名
        names = re.findall(r'class="[^"]*module-tab-item[^"]*"[^>]*data-dropdown-value="([^"]*)"', txt)
        # 选集块
        groups = re.findall(r'<div class="module-play-list">([\s\S]*?)</div>\s*</div>\s*</div>', txt, re.I)
        if not groups:
            groups = re.findall(r'<div class="module-play-list-content[^"]*"[^>]*>([\s\S]*?)</div>\s*</div>\s*</div>', txt, re.I)
        play_from, play_url = [], []
        for i, g in enumerate(groups):
            eps = []
            for h, n in re.findall(r'<a[^>]*href="(/vodplay/\d+-\d+-\d+\.html)"[^>]*>([\s\S]*?)</a>', g, re.I):
                item = (self.clean(n) or ('第%d集' % (len(eps) + 1))) + '$' + self.fix(h)
                if item not in eps: eps.append(item)
            if eps:
                line = names[i] if i < len(names) and names[i] else ('线路%d' % (i + 1))
                if re.search(r'网盘|云盘|下载|夸克|百度|迅雷', line, re.I):
                    continue
                play_from.append(line); play_url.append('#'.join(eps))
        if not play_url:
            eps = []
            for h, n in re.findall(r'<a[^>]*href="(/vodplay/\d+-\d+-\d+\.html)"[^>]*>([\s\S]*?)</a>', txt, re.I):
                item = (self.clean(n) or '播放') + '$' + self.fix(h)
                if item not in eps: eps.append(item)
            if eps: play_from, play_url = ['默认'], ['#'.join(eps)]
        vod = {
            'vod_id': url, 'vod_name': title, 'vod_pic': pic,
            'type_name': '', 'vod_year': '', 'vod_area': '', 'vod_remarks': '',
            'vod_actor': '', 'vod_director': '', 'vod_content': content,
            'vod_play_from': '$$$'.join(play_from), 'vod_play_url': '$$$'.join(play_url),
        }
        return {'list': [vod]}

    # ---------------- 播放 ----------------
    def decodePlayerUrl(self, raw):
        """encrypt=2：url → unquote → base64 → unquote → 真实URL"""
        if not raw: return ''
        try:
            s = base64.b64decode(unquote(str(raw))).decode('utf-8', 'ignore')
            return unquote(s)
        except Exception:
            return str(raw).replace('\\/', '/')

    def resolveOfficial(self, page_url):
        """官方源 → qlplayer 解析器 → resolve.php 换流"""
        try:
            body = self.getHtml(self.PARSE_HOST + '/?url=' + quote(page_url, safe=''), self.host + '/')
            m = re.search(r'apiToken:\s*"([^"]+)"', body) or re.search(r'apiToken["\']?\s*[:=]\s*["\']([^"\']+)', body)
            if not m: return ''
            r = self.fetch(self.PARSE_HOST + '/api/resolve.php?token=' + quote(m.group(1), safe=''),
                           headers={'User-Agent': self.headers['User-Agent'], 'Referer': self.PARSE_HOST + '/'},
                           timeout=15)
            txt = r.content.decode(getattr(r, 'encoding', None) or 'utf-8', 'ignore') if hasattr(r, 'content') else (getattr(r, 'text', '') or '')
            d = json.loads(txt)
            if d.get('code') == 200 and d.get('url'):
                return (d.get('url') or '').replace('\\/', '/')
        except Exception as e:
            self.log('官方源解析失败 %s' % e)
        return ''

    def makePlayHeader(self, url):
        h = {'User-Agent': self.headers['User-Agent']}
        if 'jisuzyv' in url or 'qlplayer' in url or 'cache.0567890' in url:
            h['Referer'] = self.host + '/'
        return h

    def playerContent(self, flag, id, vipFlags):
        if self.isVideoFormat(id):
            return {'parse': 0, 'url': id, 'header': self.makePlayHeader(id)}
        txt = self.getHtml(id, self.host + '/')
        m = re.search(r'player_aaaa\s*=\s*(\{[\s\S]*?\})\s*</script>', txt, re.I)
        if not m:
            mm = re.search(r'(https?:\\?/\\?/[^"\']+?\.(?:m3u8|mp4)[^"\']*)', txt, re.I)
            if mm:
                u = self.fix(mm.group(1))
                return {'parse': 0, 'url': u, 'header': self.makePlayHeader(u)}
            return {'parse': 1, 'url': id, 'header': self.headers}
        try:
            data = json.loads(m.group(1).replace('\\/', '/'))
        except Exception:
            return {'parse': 1, 'url': id, 'header': self.headers}
        frm = str(data.get('from', ''))
        real_url = self.decodePlayerUrl(data.get('url', ''))
        if self.isVideoFormat(real_url):
            return {'parse': 0, 'url': real_url, 'header': self.makePlayHeader(real_url)}
        if frm in self.OFFICIAL_FROM and real_url:
            u = self.resolveOfficial(real_url)
            if self.isVideoFormat(u):
                return {'parse': 0, 'url': u, 'header': self.makePlayHeader(u)}
        mm = re.search(r'(https?:\\?/\\?/[^"\']+?\.(?:m3u8|mp4)[^"\']*)', txt, re.I)
        if mm:
            u = self.fix(mm.group(1))
            return {'parse': 0, 'url': u, 'header': self.makePlayHeader(u)}
        return {'parse': 1, 'url': id, 'header': self.headers}


spider = Spider()

if __name__ == '__main__':
    print('=' * 60)
    print('66大片网 脚本自检')
    print('=' * 60)
    sp = Spider()
    hc = sp.homeContent(False)
    print('[首页] 分类 %d 个: %s' % (len(hc['class']), '、'.join(c['type_name'] for c in hc['class'])))
    hv = sp.homeVideoContent()
    print('[推荐] %d 条 | 首条: %s' % (len(hv['list']), hv['list'][0]['vod_name'] if hv['list'] else '-'))
    for tid, tname in [('1', '电影'), ('3', '剧集')]:
        cat = sp.categoryContent(tid, '1', False, {})
        print('[分类-%s] %d 条 | 首条: %s' % (tname, len(cat['list']), cat['list'][0]['vod_name'] if cat['list'] else '-'))
    s = sp.searchContent('战狼', False, '1')
    print('[搜索] %d 条 | 首条: %s' % (len(s.get('list', [])), s['list'][0]['vod_name'] if s['list'] else '-'))
    if s.get('list'):
        d = sp.detailContent([s['list'][0]['vod_id']])
        if d['list']:
            dv = d['list'][0]
            print('[详情] %s' % dv['vod_name'][:30])
            print('  线路: %s' % dv['vod_play_from'][:80])
            pu = dv['vod_play_url'].split('$$$')[0]
            print('  集数: %d 集' % len(pu.split('#')))
            first = pu.split('#')[0].split('$')[-1]
            p = sp.playerContent('', first, '')
            print('[播放] parse=%s' % p['parse'])
            print('  url: %s' % p.get('url', '')[:140])
    print('=' * 60)
