# -*- coding: utf-8 -*-
# 云朵影视 TVBox spider — 修复版
# 修复点:
#  1) ext 支持 JSON: {"token": "...", "finger": "...", "sk": "..."} 便于热更新
#  2) 自动检测 USER_TOKEN 是否过期, 过期则不发送 x-user-token
#  3) playerContent 兼容 dict/JSON 返回、协议相对URL、vodFrom/from 两种参数
#  4) detailContent/categoryContent 兼容 data 为对象(dict)的返回
import json
import random
import time
import urllib.request
import urllib.parse
import ssl
import re
import hashlib

try:
    from base.spider import Spider as _Base
except Exception:
    class _Base:
        pass

FINGER = 'SF-F5F11CB15897115AE6BCFE063C288F730CA865588F572C780A3E8477D0DD3776'
SK = 'SK-sk_13oXDZ7u9j2Tk1c0cawWVFfO'
DEVICE_UUID = 'uuid-a43a3421-2704-4deb-afe4-136aed229307'
# !!! 该 token 已于 2026-09-02 22:09 过期, 请用 init(ext) 传入新 token !!!
USER_TOKEN = 'ZThkNjRlYzhlNmZmNzZkMDI1ZDhhMTVhNzA2YjFlN2YxYjQwMTA5NzBkZThiN2NlZTk0ZGYzOWU2MmQ5NzQ3Y3wxMzI5NnxmemNyeW18MTc4ODM1ODE1Ng=='

HOST = 'http://154.21.198.181:8081'
UA = 'okhttp/4.12.0'


def _token_alive(tok):
    """检测 base64 token 是否过期: 最后一段是秒级时间戳"""
    try:
        raw = __import__('base64').b64decode(tok).decode('utf-8', 'ignore')
        return int(raw.split('|')[-1]) > int(time.time()) + 60
    except Exception:
        return False


class Spider(_Base):
    _ctx = ssl._create_unverified_context()

    def init(self, ext=''):
        # ext 支持两种格式:
        #   1) 纯 token 字符串
        #   2) JSON: {"token":"...","finger":"...","sk":"..."}
        global FINGER, SK, USER_TOKEN
        try:
            ext = (ext or '').strip()
            if not ext:
                return
            if ext.startswith('{'):
                cfg = json.loads(ext)
                if cfg.get('finger'):
                    FINGER = cfg['finger']
                if cfg.get('sk'):
                    SK = cfg['sk']
                if cfg.get('token'):
                    USER_TOKEN = cfg['token']
            elif '|' not in ext and len(ext) > 20:
                USER_TOKEN = ext
        except Exception:
            pass

    def getName(self):
        return '云朵影视'

    def _hdr(self):
        t = str(int(time.time() * 1000))
        nonce = hashlib.sha256(DEVICE_UUID.encode()).hexdigest().upper()[:8] + \
            ''.join(str(random.randint(0, 9)) for _ in range(8))
        sign = hashlib.sha256((
            'finger=' + FINGER + '&id=com.tvcloud.io&nonce=' + nonce +
            '&sk=' + SK + '&time=' + t + '&v=4').encode()).hexdigest().upper()
        h = {'User-Agent': UA, 'accept': 'application/json',
             'x-aid': 'com.tvcloud.io', 'x-ave': '4',
             'x-time': t, 'x-nonc': nonce, 'x-sign': sign,
             'x-device-id': DEVICE_UUID, 'x-device-brand': 'realtek',
             'x-device-model': 'ZIDOO_X9S', 'x-client-type': 'tv',
             'x-update-id': 'embedded'}
        if _token_alive(USER_TOKEN):
            h['x-user-token'] = USER_TOKEN
        return h

    def _get(self, path):
        req = urllib.request.Request(HOST + path, headers=self._hdr())
        d = urllib.request.urlopen(req, timeout=20, context=self._ctx).read()
        return json.loads(d)

    # ---------- 首页 ----------
    def homeContent(self, filter):
        j = self._get('/api.php/app/index/home')
        d = j.get('data', {}) or {}
        if not isinstance(d, dict):
            d = {}
        cats = [{'type_id': 're', 'type_name': '推荐'}]
        for c in d.get('categories', []):
            cats.append({'type_id': str(c.get('type_id')),
                         'type_name': c.get('type_name')})
        cats.append({'type_id': 'his', 'type_name': '历史'})
        return {'class': cats}

    def _fetch_history(self):
        try:
            hdr = self._hdr()
            hdr['Content-Type'] = 'application/json; charset=UTF-8'
            body = json.dumps({'token': USER_TOKEN}).encode()
            req = urllib.request.Request(HOST + '/api.php/app/account/fetch',
                                         data=body, headers=hdr, method='POST')
            j = json.loads(urllib.request.urlopen(req, timeout=15).read())
            hist = (j.get('data') or {}).get('history')
            if not hist:
                return []
            hl = json.loads(hist) if isinstance(hist, str) else hist
            out = []
            for h in hl:
                out.append({'vod_id': str(h.get('id')),
                            'vod_name': h.get('title'),
                            'vod_pic': h.get('cover'),
                            'vod_remarks': h.get('vod_remarks', '')})
            return out
        except Exception:
            return []

    _CAT = {'1': '电影', '2': '剧集', '3': '动漫', '4': '综艺'}

    # ---------- 分类 ----------
    def categoryContent(self, tid, pg, filter, extend):
        pg = max(1, int(pg or 1))
        if tid == 're':
            try:
                j = self._get('/api.php/app/ranking/list')
            except Exception:
                return {'list': [], 'page': 1, 'total': 0, 'pagecount': 1, 'limit': 24}
            merged, seen = [], set()
            for r in (j.get('data') or {}).get('rankings', []):
                for v in r.get('videos', []):
                    vid = str(v.get('vod_id'))
                    if vid in seen:
                        continue
                    seen.add(vid)
                    merged.append({'vod_id': vid,
                                   'vod_name': v.get('vod_name'),
                                   'vod_pic': v.get('vod_pic'),
                                   'vod_remarks': v.get('vod_remarks', '')})
            try:
                j2 = self._get('/api.php/app/index/home')
                d2 = j2.get('data') or {}
                for v in (d2.get('recommend', []) if isinstance(d2, dict) else []):
                    vid = str(v.get('vod_id'))
                    if vid not in seen:
                        seen.add(vid)
                        merged.append({'vod_id': vid,
                                       'vod_name': v.get('vod_name'),
                                       'vod_pic': v.get('vod_pic'),
                                       'vod_remarks': v.get('vod_remarks', '')})
            except Exception:
                pass
            return {'list': merged, 'page': 1, 'total': len(merged),
                    'pagecount': max(1, -(-len(merged) // 24)),
                    'limit': 24}
        if tid == 'his':
            lst = self._fetch_history()
            return {'list': lst, 'page': 1, 'total': len(lst),
                    'pagecount': 1, 'limit': 24}
        cat = self._CAT.get(str(tid), '电影')
        p = ('/api.php/app/filter/vod?type_name=' + urllib.parse.quote(cat) +
             '&page=%d&limit=24&sort=hits' % pg)
        try:
            j = self._get(p)
        except Exception:
            return {'list': [], 'page': pg, 'total': 0, 'pagecount': pg, 'limit': 24}
        d = j.get('data') or []
        if isinstance(d, dict):
            d = d.get('videos', []) or d.get('list', [])
        out = [{'vod_id': str(v.get('vod_id')),
                'vod_name': v.get('vod_name'),
                'vod_pic': v.get('vod_pic'),
                'vod_remarks': v.get('vod_remarks', '')} for v in d]
        total = int(j.get('total') or len(out))
        pagecount = int(j.get('pageCount') or j.get('pagecount')
                        or max(1, -(-total // 24)))
        return {'list': out, 'page': pg, 'total': total,
                'pagecount': pagecount, 'limit': 24}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        j = self._get('/api.php/app/vod/get_detail?vod_id=' + ids[0])
        data = j.get('data')
        if isinstance(data, dict):
            v = data
        else:
            v = (data or [{}])[0]
        pf = (v.get('vod_play_from') or '').split('$$$')
        pu = (v.get('vod_play_url') or '').split('$$$')
        lines, urls = [], []
        for i, ln in enumerate(pf):
            if i >= len(pu) or not pu[i]:
                continue
            lines.append(ln)
            urls.append(pu[i])
        _ct = v.get('vod_content', '') or ''
        _ct = re.sub(r'<[^>]+>', '', _ct).strip()
        return {'list': [{'vod_id': ids[0],
                          'vod_name': v.get('vod_name'),
                          'vod_pic': v.get('vod_pic'),
                          'vod_remarks': v.get('vod_remarks', ''),
                          'vod_year': v.get('vod_year', ''),
                          'vod_area': v.get('vod_area', ''),
                          'vod_actor': v.get('vod_actor', ''),
                          'vod_director': v.get('vod_director', ''),
                          'vod_content': _ct,
                          'vod_play_from': '$$$'.join(lines),
                          'vod_play_url': '$$$'.join(urls)}]}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg=1):
        j = self._get('/api.php/app/search/index?wd=%s&page=%s' % (
            urllib.parse.quote(key), pg or 1))
        d = j.get('data') or {}
        if isinstance(d, dict):
            lst = d.get('videos', []) or d.get('list', [])
        else:
            lst = d
        out = []
        for v in lst:
            out.append({'vod_id': str(v.get('vod_id')),
                        'vod_name': v.get('vod_name'),
                        'vod_pic': v.get('vod_pic'),
                        'vod_remarks': v.get('vod_remarks', '')})
        return {'list': out, 'page': int(pg or 1)}

    # ---------- 播放 ----------
    def _extract_url(self, data):
        """从 decode 接口返回中尽量提取真实播放地址"""
        if isinstance(data, str):
            s = data.strip()
            if s.startswith('{'):
                try:
                    return self._extract_url(json.loads(s))
                except Exception:
                    return ''
            return s
        if isinstance(data, dict):
            for k in ('url', 'playUrl', 'play_url', 'video', 'src', 'data'):
                if data.get(k):
                    return self._extract_url(data[k])
        return ''

    def playerContent(self, flag, id, vipFlags):
        url = ''
        for from_key in ('vodFrom', 'from'):
            try:
                _t = int(time.time() * 1000)
                p = '/api.php/app/decode/url?url=%s&%s=%s&_t=%d' % (
                    urllib.parse.quote(id), from_key,
                    urllib.parse.quote(flag), _t)
                j = self._get(p)
                url = self._extract_url(j.get('data'))
                if url.startswith('//'):
                    url = 'http:' + url
                if url.startswith('http'):
                    break
                url = ''
            except Exception:
                url = ''
                continue
        if url:
            return {'parse': 0, 'playUrl': '', 'url': url,
                    'header': {'User-Agent': UA, 'Referer': HOST + '/'}}
        return {'parse': 0, 'playUrl': '', 'url': id,
                'header': {'User-Agent': UA}}

    def isVideoFormat(self, url):
        return True

    def isPlayable(self, url):
        return True
