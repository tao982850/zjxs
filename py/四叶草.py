# -*- coding: utf-8 -*-
# 刁民制作，禁止用于商业用途
# TVBox / 影视仓 / OK影视 Python 标准爬虫
# 四叶草秒播 (AppQi / qijiappapi 接口)
# 接口响应数据使用 AES-CBC 加密，key 和 iv 均为 8eeObuwrmS3lRDEs
# 请求 body 为明文 JSON，Content-Type 必须为 application/json
import sys
import re
import json
import base64
import time
from urllib.parse import quote

sys.path.append('..')
try:
    from base.spider import Spider
except Exception:
    class Spider(object):
        pass

# AES 支持：优先 pycryptodome，其次 Cryptodome
_AES = None
try:
    from Crypto.Cipher import AES as _AES
except Exception:
    try:
        from Cryptodome.Cipher import AES as _AES
    except Exception:
        _AES = None


class Spider(Spider):
    def getName(self):
        return '四叶草秒播'

    def init(self, extend=''):
        self._init_cache = None
        self._site_url = ''
        self._data_key = '8eeObuwrmS3lRDEs'
        self._data_iv = '8eeObuwrmS3lRDEs'
        self._ua = 'okhttp/3.10.0'
        self._default_classes = [
            {'type_name': '全部', 'type_id': '0'},
            {'type_name': '剧集', 'type_id': '20'},
            {'type_name': '电影', 'type_id': '21'},
            {'type_name': '综艺', 'type_id': '22'},
            {'type_name': '动漫', 'type_id': '23'},
            {'type_name': '少儿', 'type_id': '24'},
        ]
        # 解析 extend 配置
        cfg = {}
        try:
            if isinstance(extend, dict):
                cfg = extend
            elif isinstance(extend, str) and extend.strip():
                cfg = json.loads(extend)
        except Exception:
            pass
        self._data_key = cfg.get('dataKey', self._data_key)
        self._data_iv = cfg.get('dataIv', self._data_iv)
        self._ua = cfg.get('ua', self._ua)
        # 从 kkk.txt 获取真实 API 地址
        site_txt_url = cfg.get('site', '')
        if site_txt_url:
            try:
                resp = self._http_get(site_txt_url)
                self._site_url = (resp or '').strip().rstrip('/')
            except Exception:
                pass
        if not self._site_url:
            self._site_url = 'http://43.254.106.169:7777'

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    # ========== TVBox 标准接口 ==========

    def homeContent(self, filter):
        classes = list(self._default_classes)
        filters_map = {}
        try:
            init_data = self._get_init()
            type_list = init_data.get('type_list') or []
            if type_list:
                classes = []
                for t in type_list:
                    name = t.get('type_name') or ''
                    tid = str(t.get('type_id') if t.get('type_id') is not None else '')
                    # 过滤不需要的分类
                    if name in ('伦理', '福利', '小影院', '直播'):
                        continue
                    classes.append({'type_name': name, 'type_id': tid})
                    ftl = t.get('filter_type_list') or []
                    filters = self._build_filters(ftl)
                    if filters:
                        filters_map[tid] = filters
        except Exception:
            pass
        result = {'class': classes}
        if filter:
            result['filters'] = filters_map
        return result

    def homeVideoContent(self):
        vods = []
        try:
            init_data = self._get_init()
            # 优先用 banner_list，其次 recommend_list
            rec = init_data.get('banner_list') or init_data.get('recommend_list') or []
            vods = self._parse_vod_list(rec)
        except Exception:
            pass
        return {'list': vods[:30]}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        vods = []
        pagecount = pg + 1
        try:
            body = {'type_id': str(tid), 'page': str(pg)}
            if isinstance(extend, dict):
                for k in ('class', 'lang', 'area', 'year'):
                    v = extend.get(k)
                    if v:
                        body[k] = v
                by = extend.get('by')
                if by:
                    body['sort'] = by
            path = '/qijiappapi.index/typeFilterVodList?page=%d' % pg
            data = self._api_post(path, json.dumps(body, ensure_ascii=False))
            rec = data.get('recommend_list') or []
            vods = self._parse_vod_list(rec)
            # 推测分页：每页30条，不足30说明到底了
            pagecount = pg + 1 if len(rec) >= 30 else pg
        except Exception:
            pass
        return {
            'page': pg,
            'pagecount': pagecount,
            'limit': 30,
            'total': pagecount * 30,
            'list': vods,
        }

    def detailContent(self, ids):
        vod_id = ids[0]
        vod = {
            'vod_id': vod_id,
            'vod_name': vod_id,
            'vod_pic': '',
            'type_name': '',
            'vod_year': '',
            'vod_area': '',
            'vod_remarks': '',
            'vod_actor': '',
            'vod_director': '',
            'vod_content': '',
            'vod_play_from': '',
            'vod_play_url': '',
        }
        try:
            body = json.dumps({'vod_id': int(vod_id)}, ensure_ascii=False)
            data = self._api_post('/qijiappapi.index/vodDetail', body)
            v = data.get('vod') or {}
            vod['vod_name'] = v.get('vod_name') or vod_id
            vod['vod_pic'] = v.get('vod_pic') or ''
            vod['type_name'] = v.get('vod_class') or ''
            vod['vod_year'] = v.get('vod_year') or ''
            vod['vod_area'] = v.get('vod_area') or ''
            vod['vod_remarks'] = v.get('vod_remarks') or ''
            vod['vod_actor'] = v.get('vod_actor') or ''
            vod['vod_director'] = v.get('vod_director') or ''
            vod['vod_content'] = v.get('vod_content') or v.get('vod_blurb') or ''
            # 解析播放列表
            play_list = data.get('vod_play_list') or []
            play_from = []
            play_url = []
            for p in play_list:
                pi = p.get('player_info') or {}
                show = pi.get('show') or '线路'
                urls = p.get('urls') or []
                items = []
                for u in urls:
                    name = u.get('name') or ''
                    # play_id 格式: url|from|parse_api_url
                    play_url_val = u.get('url') or ''
                    play_from_val = u.get('from') or ''
                    parse_api_url = u.get('parse_api_url') or ''
                    play_id = '%s|%s|%s' % (play_url_val, play_from_val, parse_api_url)
                    items.append('%s$%s' % (name, play_id))
                if items:
                    play_from.append(show)
                    play_url.append('#'.join(items))
            vod['vod_play_from'] = '$$$'.join(play_from) if play_from else '四叶草'
            vod['vod_play_url'] = '$$$'.join(play_url) if play_url else '无数据$'
        except Exception:
            pass
        return {'list': [vod]}

    def searchContent(self, key, quick, pg='1'):
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick, pg):
        pg = int(pg or 1)
        vods = []
        try:
            body = json.dumps({'type_id': 0, 'keywords': key, 'page': pg}, ensure_ascii=False)
            data = self._api_post('/qijiappapi.index/searchList', body)
            search_list = data.get('search_list') or []
            vods = self._parse_vod_list(search_list)
        except Exception:
            pass
        return {'list': vods}

    def playerContent(self, flag, id, vipFlags):
        play_url = ''
        parse_flag = 0
        try:
            # id 格式: url|from|parse_api_url
            parts = str(id).split('|')
            raw_url = parts[0] if parts else ''
            from_tag = parts[1] if len(parts) > 1 else ''
            # 外部站点链接（爱奇艺、腾讯等）交给播放器嗅探
            if raw_url.startswith('http') and not raw_url.startswith(self._site_url):
                play_url = raw_url
                parse_flag = 1
            else:
                # 通过 vodParse 接口解析
                play_url = self._vod_parse(raw_url)
                parse_flag = 0
        except Exception:
            pass
        result = {
            'parse': parse_flag,
            'playUrl': '',
            'url': play_url,
            'header': {
                'User-Agent': self._ua,
            },
        }
        return result

    def localProxy(self, params):
        return [404, 'text/plain', '']

    # ========== 内部方法 ==========

    def _get_init(self):
        if self._init_cache is not None:
            return self._init_cache
        try:
            data = self._api_post('/qijiappapi.index/initV119', '{}')
            self._init_cache = data
            return data
        except Exception:
            return {}

    def _api_post(self, path, body=''):
        url = self._site_url + '/api.php' + path
        ts = str(int(time.time()))
        headers = {
            'User-Agent': self._ua,
            'Content-Type': 'application/json',
            'app-api-verify-time': ts,
            'app-ui-mode': 'light',
        }
        resp_text = self._http_post(url, body, headers)
        if not resp_text:
            return {}
        j = json.loads(resp_text)
        data_b64 = j.get('data') or ''
        if not data_b64:
            return {}
        dec = self._aes_decrypt(data_b64)
        if not dec:
            return {}
        return json.loads(dec)

    def _vod_parse(self, play_url_raw):
        url = self._site_url + '/api.php/qijiappapi.index/vodParse'
        ts = str(int(time.time()))
        headers = {
            'User-Agent': self._ua,
            'Content-Type': 'application/json',
            'Connection': 'Keep-Alive',
            'app-api-verify-time': ts,
            'app-ui-mode': 'light',
        }
        body = json.dumps({'url': play_url_raw}, ensure_ascii=False)
        resp_text = self._http_post(url, body, headers)
        if not resp_text:
            return ''
        j = json.loads(resp_text)
        data_b64 = j.get('data') or ''
        if not data_b64:
            return ''
        dec = self._aes_decrypt(data_b64)
        if not dec:
            return ''
        data = json.loads(dec)
        # vodParse 响应结构: {"json": "{\"code\":200,\"url\":\"http://...\"}"}
        json_str = data.get('json') or ''
        if json_str:
            try:
                inner = json.loads(json_str)
                return inner.get('url') or ''
            except Exception:
                pass
        return data.get('url') or ''

    def _aes_encrypt(self, plaintext):
        if _AES is None:
            return ''
        key = self._data_key.encode('utf-8')
        iv = self._data_iv.encode('utf-8')
        cipher = _AES.new(key, _AES.MODE_CBC, iv)
        raw = plaintext.encode('utf-8')
        pad_len = 16 - (len(raw) % 16)
        raw += bytes([pad_len]) * pad_len
        encrypted = cipher.encrypt(raw)
        return base64.b64encode(encrypted).decode('utf-8')

    def _aes_decrypt(self, data_b64):
        if _AES is None:
            return ''
        key = self._data_key.encode('utf-8')
        iv = self._data_iv.encode('utf-8')
        cipher = _AES.new(key, _AES.MODE_CBC, iv)
        raw = base64.b64decode(data_b64)
        decrypted = cipher.decrypt(raw)
        pad_len = decrypted[-1]
        if isinstance(pad_len, int) and 1 <= pad_len <= 16:
            decrypted = decrypted[:-pad_len]
        return decrypted.decode('utf-8', errors='replace')

    def _http_get(self, url):
        headers = {'User-Agent': self._ua}
        # 优先使用 Spider.fetch
        try:
            rsp = super().fetch(url, headers=headers)
            if rsp is not None:
                text = self._resp_text(rsp)
                if text and text != 'None':
                    return text
        except Exception:
            pass
        # 回退 urllib
        try:
            from urllib.request import Request, urlopen
            req = Request(url, headers=headers)
            with urlopen(req, timeout=10) as r:
                return self._to_text(r.read())
        except Exception:
            return ''

    def _http_post(self, url, data, headers=None):
        if headers is None:
            headers = {}
        if 'User-Agent' not in headers:
            headers['User-Agent'] = self._ua
        body = data.encode('utf-8') if isinstance(data, str) else data
        # 优先使用 Spider.post
        try:
            rsp = super().post(url, headers=headers, data=body)
            if rsp is not None:
                text = self._resp_text(rsp)
                if text and text != 'None':
                    return text
        except Exception:
            pass
        # 回退 urllib
        try:
            from urllib.request import Request, urlopen
            req = Request(url, data=body, headers=headers, method='POST')
            with urlopen(req, timeout=15) as r:
                return self._to_text(r.read())
        except Exception:
            return ''

    def _resp_text(self, rsp):
        try:
            return self._to_text(rsp.content)
        except Exception:
            try:
                return self._to_text(rsp.text)
            except Exception:
                return str(rsp)

    @staticmethod
    def _to_text(raw):
        if isinstance(raw, bytes):
            for enc in ('utf-8', 'gbk', 'latin-1'):
                try:
                    return raw.decode(enc)
                except Exception:
                    continue
            return raw.decode('utf-8', errors='replace')
        return str(raw)

    def _parse_vod_list(self, items):
        vods = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            vods.append({
                'vod_id': str(item.get('vod_id') or ''),
                'vod_name': item.get('vod_name') or '',
                'vod_pic': item.get('vod_pic') or '',
                'vod_remarks': item.get('vod_remarks') or '',
            })
        return vods

    def _build_filters(self, ftl):
        filters = []
        for f in ftl or []:
            name = f.get('name') or ''
            if name not in ('class', 'area', 'lang', 'year', 'sort'):
                continue
            items = f.get('list') or []
            values = []
            for i, v in enumerate(items):
                if not isinstance(v, str):
                    v = str(v)
                val = '' if (i == 0 and v in ('全部', '所有')) else v
                values.append({'n': v, 'v': val})
            if values:
                key = 'by' if name == 'sort' else name
                display = {'class': '分类', 'area': '地区', 'lang': '语言', 'year': '年份', 'sort': '排序'}.get(name, name)
                filters.append({'key': key, 'name': display, 'value': values})
        return filters
