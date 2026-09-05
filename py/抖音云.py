# -*- coding: utf-8 -*-
# 抖音云(bfzyapi.com采集源) | MacCMS采集API直解 | 2026-09-05
import sys, re, json
from urllib.parse import quote
sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            import requests
            kw.pop('timeout', None)
            r = requests.get(url, headers=headers, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r

API = 'https://bfzyapi.com/api.php/provide/vod/'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
CATEGORIES = {'26': '剧情片', '21': '动作片', '22': '喜剧片', '23': '恐怖片', '24': '科幻片', '25': '爱情片', '27': '战争片', '28': '纪录片','31': '国产剧', '32': '欧美剧', '33': '香港剧', '34': '韩国剧', '35': '台湾剧', '36': '日本剧', '37': '海外剧', '38': '泰国剧', '40': '国产动漫', '41': '日韩动漫', '42': '欧美动漫', '43': '港台动漫', '44': '海外动漫', '46': '大陆综艺', '47': '港台综艺'}
FROM = {'bfzym3u8': '抖音云'}
MED = r'\.(m3u8|mp4|flv|mp3)(\?|$)'


class Spider(Spider):
    def init(self, extend=''):
        self.base = API
        self.ua = UA
        self.types = dict(CATEGORIES)

    def _json(self, url):
        try:
            try:
                r = self.fetch(url, headers={'User-Agent': self.ua}, timeout=10000)
            except TypeError:
                r = self.fetch(url, headers={'User-Agent': self.ua})
        except Exception:
            return {}
        try:
            return json.loads(r.text if hasattr(r, 'text') else str(r))
        except Exception:
            return {}

    def _card(self, it, v):
        return {'vod_id': str(it.get('vod_id', '')), 'vod_name': (it.get('vod_name') or '')[:60],
                'vod_pic': (v or it).get('vod_pic') or '', 'vod_remarks': it.get('vod_remarks') or (v or it).get('vod_remarks') or ''}

    def _cards(self, items):
        if not items:
            return []
        ids = ','.join(str(x.get('vod_id')) for x in items)
        pm = {}
        if len(ids) < 900:
            for x in (self._json(self.base + '?ac=detail&ids=' + ids).get('list') or []):
                pm[str(x.get('vod_id'))] = x
        return [self._card(it, pm.get(str(it.get('vod_id')))) for it in items]

    def homeContent(self, filter=False):
        return {'class': [{'type_id': k, 'type_name': v} for k, v in self.types.items()], 'list': self.homeVideoContent().get('list', [])}

    def homeVideoContent(self):
        return {'list': self._cards((self._json(self.base + '?ac=list&pg=1').get('list') or []))[:18]}

    def categoryContent(self, tid, pg=1, filter=False, extend=''):
        try:
            pn = max(int(str(pg)), 1)
        except Exception:
            pn = 1
        j = self._json(self.base + '?ac=list&t=%s&pg=%d' % (str(tid).split('|')[0], pn))
        return {'page': pn, 'pagecount': int(j.get('pagecount') or 1), 'limit': int(j.get('limit') or 20), 'total': int(j.get('total') or 0), 'list': self._cards(j.get('list') or [])}

    def detailContent(self, ids, quick='1'):
        m = re.search(r'(\d+)', str(ids[0] if isinstance(ids, list) else ids or ''))
        if not m:
            return {'list': []}
        l = (self._json(self.base + '?ac=detail&ids=' + m.group(1)).get('list') or [])
        if not l:
            return {'list': []}
        v = l[0]
        froms, lines = [], []
        pf = (v.get('vod_play_from') or 'bfzym3u8').split('$$$')
        pu = (v.get('vod_play_url') or '').split('$$$')
        for i, seg in enumerate(pu[:len(pf)]):
            eps = []
            for ep in seg.split('#'):
                if '$' in ep:
                    n, u = ep.split('$', 1)
                    if re.search(MED, u, re.I) and '://' in u:
                        eps.append('%s$%s' % (n.replace('#', '-').replace('$', '|'), quote(u, safe='/?=&:%')))
            if eps:
                froms.append(FROM.get(pf[i], pf[i]))
                lines.append('#'.join(eps))
        if not froms:
            return {'list': []}
        return {'list': [{'vod_id': str(v.get('vod_id', '')), 'vod_name': v.get('vod_name') or '', 'vod_pic': v.get('vod_pic') or '',
                          'vod_year': str(v.get('vod_year') or ''), 'vod_area': v.get('vod_area') or '', 'vod_class': v.get('vod_class') or '',
                          'vod_director': v.get('vod_director') or '', 'vod_actor': v.get('vod_actor') or '',
                          'vod_content': re.sub(r'\s+', ' ', v.get('vod_content') or '').strip()[:500], 'vod_remarks': v.get('vod_remarks') or '',
                          'vod_play_from': '$$$'.join(froms), 'vod_play_url': '$$$'.join(lines)}]}

    def searchContent(self, key, quick=False, pg='1'):
        l = self._json(self.base + '?ac=detail&wd=' + quote(key)).get('list') or []
        return {'list': [self._card(x, x) for x in l], 'page': 1}

    def playerContent(self, flag, id, vipFlags=None):
        u = str(id) if id else str(flag)
        if '://' in u and re.search(MED, u, re.I):
            return {'parse': 0, 'url': u}
        return {'parse': 0, 'url': u if u.startswith('http') else ''}
