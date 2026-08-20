import re, requests, json
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
from base.spider import Spider

HOST = 'https://yun2s2lxsduo22.top'
UA = 'Mozilla/5.0'
WS = 'yda81x6d9ad3c4s'
XC = '8f3d2a1c7b6e5d4c9a0b1f2e3d4c5b6a'
TS = 1787210616774
SIGN = b'EF5EE13C0FE1F3A1971B41DAD5ABEEDBB5797BB6691693DC599F5BF9663D10DA'
PLAYER = b'com.web.player.6c3b998c'
TYPES = {'1': '电影', '2': '剧集', '3': '动漫', '4': '综艺'}

class Spider(Spider):
    def init(self, extend=""):
        self.s = requests.Session()
        self.s.headers.update({'web-sign': WS, 'X-Client': XC, 'User-Agent': UA})
        self._lcache = {}
        self._lts = 0
        try:
            self.s.post(HOST + '/api.php/web/account/login', json={'username': 'admin', 'password': '123456'}, timeout=10, verify=False)
        except:
            pass

    def _probe(self, pid, vf):
        try:
            ck = self.s.cookies.get('yunduo_web_session', '')
            r = requests.post(HOST + '/api.php/web/decode/url', data=self._pb(pid, vf), headers={'Content-Type': 'application/x-protobuf', 'User-Agent': UA, 'web-sign': WS, 'X-Client': XC, 'Cookie': 'yunduo_web_session=' + ck}, timeout=8, verify=False)
            return bool(re.search(r'https?://[^\s\x00-\x1f"\']+', r.text))
        except:
            return False

    def _vint(self, n):
        b = bytearray()
        while True:
            x = n & 0x7f
            n >>= 7
            if n:
                b.append(x | 0x80)
            else:
                b.append(x)
                return bytes(b)

    def _pb(self, url, vf):
        u = url.encode()
        v = vf.encode()
        return b'\x0a' + self._vint(len(u)) + u + b'\x12' + self._vint(len(v)) + v + b'\x18' + self._vint(TS) + b'\x22\x20' + b'0' * 32 + b'\x2a\x40' + SIGN + b'\x32\x17' + PLAYER + b'\x38\x01'

    def _norm(self, v):
        if isinstance(v, list):
            return ','.join([str(x) for x in v])
        return str(v or '')

    def _items(self, lst):
        out = []
        for v in lst:
            out.append({'vod_id': v.get('vod_id'), 'vod_name': v.get('vod_name'), 'vod_pic': v.get('vod_pic', ''), 'vod_remarks': v.get('vod_remarks', '')})
        return out

    def homeContent(self, filter=False):
        r = self.s.get(HOST + '/api.php/web/index/home', timeout=15, verify=False)
        d = r.json().get('data', {})
        cats = [{'type_id': str(c['type_id']), 'type_name': c['type_name']} for c in d.get('categories', [])]
        vids = []
        for c in d.get('categories', []):
            for v in c.get('videos', [])[:6]:
                vids.append({'vod_id': v.get('vod_id'), 'vod_name': v.get('vod_name'), 'vod_pic': v.get('vod_pic', ''), 'vod_remarks': v.get('vod_remarks', '')})
        return {'class': cats, 'list': vids}

    def homeVideoContent(self):
        r = self.s.get(HOST + '/api.php/web/filter/vod?type_name=' + quote('电影') + '&page=1&sort=hits', timeout=15, verify=False)
        return {'list': self._items(r.json().get('data', []))}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        name = TYPES.get(str(tid), '电影')
        r = self.s.get(HOST + '/api.php/web/filter/vod?type_name=' + quote(name) + '&page=' + str(pg) + '&sort=hits', timeout=15, verify=False)
        return {'list': self._items(r.json().get('data', [])), 'page': int(pg), 'pagecount': 999, 'limit': 24, 'total': 99999}

    def detailContent(self, ids):
        vid = ids[0]
        r = self.s.get(HOST + '/api.php/web/vod/get_detail?vod_id=' + str(vid), timeout=15, verify=False)
        d = r.json().get('data', [])
        if not d:
            return {'list': []}
        v = d[0]
        pfs = v.get('vod_play_from', '').split('$$$')
        segs = v.get('vod_play_url', '').split('$$$')
        if len(pfs) > 1 and len(pfs) == len(segs):
            import time
            now = time.time()
            if now - self._lts > 180 or vid not in self._lcache:
                ok = {}
                with ThreadPoolExecutor(max_workers=5) as ex:
                    futs = {}
                    for i, src in enumerate(pfs):
                        pid0 = segs[i].split('#')[0].split('$')[1] if '$' in segs[i] else ''
                        if pid0:
                            futs[ex.submit(self._probe, pid0, src)] = i
                    for f in futs:
                        ok[futs[f]] = f.result()
                order = sorted(range(len(pfs)), key=lambda i: (not ok.get(i, True), i))
                self._lcache[vid] = order
                self._lts = now
            else:
                order = self._lcache[vid]
            pfs = [pfs[i] for i in order]
            segs = [segs[i] for i in order]
        return {'list': [{'vod_id': v.get('vod_id'), 'vod_name': v.get('vod_name'), 'vod_pic': v.get('vod_pic', ''), 'vod_remarks': self._norm(v.get('vod_remarks')), 'vod_year': self._norm(v.get('vod_year')), 'vod_area': self._norm(v.get('vod_area')), 'vod_director': self._norm(v.get('vod_director')), 'vod_actor': self._norm(v.get('vod_actor')), 'vod_content': re.sub(r'<[^>]+>', '', self._norm(v.get('vod_content'))), 'vod_play_from': '$$$'.join(pfs), 'vod_play_url': '$$$'.join(segs)}]}

    def searchContent(self, key, quick=False):
        r = self.s.get(HOST + '/api.php/web/search/index?wd=' + quote(key) + '&page=1&limit=15', timeout=15, verify=False)
        return {'list': self._items(r.json().get('data', []))}

    def playerContent(self, flag, id, vipFlags):
        vf = flag if flag and flag != '线路' else (id.split('-')[0] if '-' in id else flag)
        u = ''
        for _ in range(2):
            try:
                r = self.s.post(HOST + '/api.php/web/decode/url', data=self._pb(id, vf), headers={'Content-Type': 'application/x-protobuf'}, timeout=15, verify=False)
                m = re.search(r'https?://[^\s\x00-\x1f"\']+', r.text)
                u = m.group(0) if m else ''
                if u:
                    break
            except:
                break
        if not u:
            return {'parse': 0, 'url': ''}
        try:
            r2 = requests.get(u, headers={'User-Agent': UA}, timeout=10, verify=False)
            if r2.status_code == 200:
                ct = r2.headers.get('Content-Type', '')
                if 'mpegurl' in ct or 'm3u8' in ct or 'mp4' in ct or 'octet-stream' in ct or r2.text.startswith('#EXTM3U'):
                    u = r2.url
        except:
            pass
        if 'quark.cn' in u:
            return {'parse': 0, 'url': u, 'header': {'Referer': 'https://pan.quark.cn/', 'User-Agent': UA}}
        if 'mgtv.com' in u:
            return {'parse': 0, 'url': u, 'header': {'User-Agent': UA}}
        return {'parse': 0, 'url': u}

    def localProxy(self, param):
        return [200, 'text/plain', '']

    def _pagecount(self):
        return 999

    def _get(self, url):
        return self.s.get(url, timeout=15, verify=False).text
