# -*- coding: utf-8 -*-
"""抖音“放映厅”网页搜索 TVBox 接口（蜜果-http://6i.pw/）。"""

import base64
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from urllib.parse import urlencode

import requests

sys.path.append('..')
from base.spider import Spider as BaseSpider


UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/151.0.0.0 Safari/537.36')
UA_MOBILE = ('Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) '
             'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 '
             'Mobile/15E148 Safari/604.1')

ABOGUS_ALPHABETS = (
    'Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe',
    'ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe',
)
ABOGUS_SORT_INDEX = (18,20,52,26,30,34,58,38,40,53,42,21,27,54,55,31,
    35,57,39,41,43,22,28,32,60,36,23,29,33,37,44,45,59,46,47,48,49,
    50,24,25,65,66,70,71)
ABOGUS_SORT_INDEX2 = (18,20,26,30,34,38,40,42,21,27,31,35,39,41,43,
    22,28,32,36,23,29,33,37,44,45,46,47,48,49,50,24,25,52,53,54,55,
    57,58,59,60,65,66,70,71)
CRYPTO_BIG_ARRAY = (
    121,243,55,234,103,36,47,228,30,231,106,6,115,95,78,101,250,207,198,50,
    139,227,220,105,97,143,34,28,194,215,18,100,159,160,43,8,169,217,180,120,
    247,45,90,11,27,197,46,3,84,72,5,68,62,56,221,75,144,79,73,161,
    178,81,64,187,134,117,186,118,16,241,130,71,89,147,122,129,65,40,88,150,
    110,219,199,255,181,254,48,4,195,248,208,32,116,167,69,201,17,124,125,104,
    96,83,80,127,236,108,154,126,204,15,20,135,112,158,13,1,188,164,210,237,
    222,98,212,77,253,42,170,202,26,22,29,182,251,10,173,152,58,138,54,141,
    185,33,157,31,252,132,233,235,102,196,191,223,240,148,39,123,92,82,128,109,
    57,24,38,113,209,245,2,119,153,229,189,214,230,174,232,63,52,205,86,140,
    66,175,111,171,246,133,238,193,99,60,74,91,225,51,76,37,145,211,166,151,
    213,206,0,200,244,176,218,44,184,172,49,216,93,168,53,21,183,41,67,85,
    224,155,226,242,87,177,146,70,190,12,162,19,137,114,25,165,163,192,23,59,
    9,94,179,107,35,7,142,131,239,203,149,136,61,249,14,156)


def _sm3(value):
    return hashlib.new('sm3', value).digest()


def _rc4(key, value):
    box, j = list(range(256)), 0
    for i in range(256):
        j = (j + box[i] + key[i % len(key)]) % 256
        box[i], box[j] = box[j], box[i]
    i = j = 0
    out = bytearray()
    for ch in value:
        i = (i + 1) % 256
        j = (j + box[i]) % 256
        box[i], box[j] = box[j], box[i]
        out.append(ch ^ box[(box[i] + box[j]) % 256])
    return bytes(out)


def _custom_b64(value, alphabet):
    out = []
    for pos in range(0, len(value), 3):
        block = value[pos:pos + 3]
        number = int.from_bytes(block.ljust(3, b'\0'), 'big')
        out.extend((alphabet[(number >> 18) & 63], alphabet[(number >> 12) & 63]))
        if len(block) > 1:
            out.append(alphabet[(number >> 6) & 63])
        if len(block) > 2:
            out.append(alphabet[number & 63])
    while len(out) % 4:
        out.append('=')
    return ''.join(out)


def _random_bytes(length=3):
    out = bytearray()
    rng = random.SystemRandom()
    for _ in range(length):
        rd = rng.randint(0, 0xffff)
        lo, hi = rd & 255, (rd >> 8) & 255
        out.extend(((lo & 0xaa) | 1, (lo & 0x55) | 2,
                    (hi & 0xaa) | 5, (hi & 0x55) | 0x28))
    return bytes(out)


def _transform(value):
    work, result = list(CRYPTO_BIG_ARRAY), bytearray()
    index_b, initial, e, size = work[1], 0, 0, len(CRYPTO_BIG_ARRAY)
    for i, ch in enumerate(value):
        if i == 0:
            initial = work[index_b]
            total = index_b + initial
            work[1], work[index_b] = initial, index_b
            result.append(ch ^ work[total % size])
            e = work[(i + 2) % size]
            total = (index_b + e) % size
            initial = work[total]
            work[total], work[(i + 2) % size] = work[(i + 2) % size], initial
            index_b = total
            continue
        result.append(ch ^ work[(initial + e) % size])
        e = work[(i + 2) % size]
        total = (index_b + e) % size
        initial = work[total]
        work[total], work[(i + 2) % size] = work[(i + 2) % size], initial
        index_b = total
    return bytes(result)


def _fingerprint():
    rng = random.SystemRandom()
    iw, ih = rng.randint(1024, 1920), rng.randint(768, 1080)
    values = (iw, ih, iw + rng.randint(24, 32), ih + rng.randint(75, 90),
              0, rng.choice((0, 30)), 0, 0, rng.randint(1024, 1920),
              rng.randint(768, 1080), rng.randint(1280, 1920),
              rng.randint(800, 1080), iw, ih, 24, 24, 'Win32')
    return '|'.join(str(x) for x in values)


def make_a_bogus(query, user_agent=UA):
    """用户提交 PHP 中 A-Bogus 算法的 Python 移植。"""
    start = int(time.time() * 1000)
    ph = _sm3(_sm3(query.encode('utf-8') + b'cus'))
    bh = _sm3(b'cus')
    cipher = _rc4(b'\x00\x01\x0e', user_agent.encode('utf-8'))
    uh = _sm3(_custom_b64(cipher, ABOGUS_ALPHABETS[1]).encode('ascii'))
    end = int(time.time() * 1000)
    data = {8:3, 18:44, 66:0, 69:0, 70:0, 71:0,
        20:(start >> 24)&255, 21:(start >> 16)&255, 22:(start >> 8)&255,
        23:start&255, 24:start//4294967296, 25:start//1099511627776,
        26:0,27:0,28:0,29:0,30:0,31:1,32:0,33:0,34:0,35:0,36:0,37:14,
        38:ph[21],39:ph[22],40:bh[21],41:bh[22],42:uh[23],43:uh[24],
        44:(end >> 24)&255,45:(end >> 16)&255,46:(end >> 8)&255,47:end&255,
        48:3,49:end//4294967296,50:end//1099511627776,
        51:0,52:0,53:0,54:0,55:0,56:6383,57:6383&255,
        58:(6383 >> 8)&255,59:0,60:0}
    fp = _fingerprint()
    data[64] = data[65] = len(fp)
    packed = bytearray((data.get(i, 0) & 255) for i in ABOGUS_SORT_INDEX)
    checksum = 0
    for i in ABOGUS_SORT_INDEX2:
        checksum ^= data.get(i, 0) & 255
    packed.extend(fp.encode('ascii'))
    packed.append(checksum & 255)
    return _custom_b64(_random_bytes(3) + _transform(packed), ABOGUS_ALPHABETS[0])


class DouyinBaseSpider(BaseSpider):
    HOST = 'https://www.douyin.com'
    API = HOST + '/aweme/v1/web'
    BASE_KEYWORD = '放映厅'
    TAB_INFO = {
        'general': ('/general/search/single/', 'aweme_general'),
        'video': ('/search/item/', 'aweme_video_web'),
        'user': ('/discover/search/', 'aweme_user_web'),
        'live': ('/live/search/', 'aweme_live'),
    }
    GUIDE_WORDS = ('', '入口', '电影', '电视剧', '小程序', '短剧', '抖音', '动漫',
                   '电影在线观看', '电视剧集', '电影院', '影视', '直播间',
                   '动画片', '免费电影')

    def __init__(self):
        super(DouyinBaseSpider, self).__init__()
        self.session = None
        self.ready = False
        self.cookie_supplied = False
        self.webid = str(random.SystemRandom().randint(7000000000000000000,
                                                       7999999999999999999))
        self.ms_token = self._random_token(107)
        self.item_cache = {}
        self.user_cache = {}
        self.qr_lock = threading.Lock()
        self.qr_token = ''
        self.qr_image = ''
        self.qr_bytes = b''
        self.qr_mime = 'image/png'
        self.qr_status = 'idle'
        self.qr_message = ''
        self.qr_thread = None
        self.cookie_save_file = ''

    def init(self, extend=''):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': UA,
            'Referer': self.HOST + '/search/%E6%94%BE%E6%98%A0%E5%8E%85',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        })
        ext = self._parse_ext(extend)
        cookie_source = ext.get('cookie') or ''
        cookie = self._load_cookie(cookie_source)
        save_file = ext.get('cookie_file') or ext.get('cookieFile') or ''
        if not save_file and cookie_source and not str(cookie_source).startswith(('http://', 'https://')):
            save_file = cookie_source
        self.cookie_save_file = str(save_file or '').strip()
        if cookie:
            self.cookie_supplied = True
            for part in cookie.split(';'):
                if '=' in part:
                    key, value = part.strip().split('=', 1)
                    if key:
                        self.session.cookies.set(key, value, domain='.douyin.com')

    def getName(self):
        return '抖音放映厅'

    def destroy(self):
        if self.session:
            self.session.close()

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def homeContent(self, filter):
        classes = [
            {'type_name': '综合', 'type_id': 'general'},
            {'type_name': '视频', 'type_id': 'video'},
            {'type_name': '用户', 'type_id': 'user'},
            {'type_name': '直播', 'type_id': 'live'},
        ]
        guide = [{'n': '全部' if not word else word, 'v': word}
                 for word in self.GUIDE_WORDS]
        filters = {
            'general': [{'key': 'guide', 'name': '分类', 'value': guide}],
            'video': [{'key': 'guide', 'name': '分类', 'value': guide}],
        }
        return {'class': classes, 'filters': filters}

    def homeVideoContent(self):
        return {'list': self._category('general', 1, {}).get('list', [])}

    def categoryContent(self, tid, pg, filter, extend):
        return self._category(str(tid), self._int(pg, 1), self._dict(extend))

    def detailContent(self, ids):
        raw_id = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        if raw_id.startswith('login|'):
            return self._login_detail()
        if raw_id == 'video|login_required':
            text = '抖音网页搜索当前要求登录，请在站点配置的 ext.cookie 中填写有效 Cookie，或填写 Cookie 文本文件/网址。'
            return {'list': [{'vod_id': raw_id, 'vod_name': '需要抖音登录 Cookie',
                              'vod_pic': '', 'type_name': '接口提示',
                              'vod_remarks': '未登录', 'vod_year': '',
                              'vod_area': '', 'vod_actor': '', 'vod_director': '',
                              'vod_content': text, 'vod_play_from': '',
                              'vod_play_url': ''}]}
        if raw_id == 'video|verify_required':
            text = ('Cookie 已成功登录账号，但抖音搜索接口要求浏览器 SecureSDK '
                    '运行时校验；复制 Cookie 到普通 HTTP 请求不能完成该校验。')
            return {'list': [{'vod_id': raw_id,
                              'vod_name': '抖音搜索安全验证',
                              'vod_pic': '', 'type_name': '接口提示',
                              'vod_remarks': 'verify_check', 'vod_year': '',
                              'vod_area': '', 'vod_actor': '', 'vod_director': '',
                              'vod_content': text, 'vod_play_from': '',
                              'vod_play_url': ''}]}
        if raw_id.startswith('video|'):
            aweme_id = raw_id.split('|', 1)[1]
            item = self.item_cache.get(aweme_id) or self._share_item(aweme_id)
            return self._video_detail(item, aweme_id)
        if raw_id.startswith('user|'):
            sec_uid = raw_id.split('|', 1)[1]
            return self._user_detail(sec_uid)
        if raw_id.startswith('live|'):
            payload = self._decode(raw_id.split('|', 1)[1])
            return self._live_detail(payload)
        return {'list': []}

    def searchContent(self, key, quick, pg='1'):
        return self._search_keyword(str(key or self.BASE_KEYWORD), self._int(pg, 1))

    def searchContentPage(self, key, quick, pg='1'):
        return self.searchContent(key, quick, pg)

    def playerContent(self, flag, pid, vipFlags):
        if str(pid) == 'login_qrcode':
            return {'parse':0, 'url':self._qr_proxy_url(),
                    'header':{'User-Agent':UA}}
        data = self._decode(str(pid))
        urls = data.get('urls') if isinstance(data, dict) else []
        candidates = [str(x) for x in (urls or []) if str(x).startswith('http')]
        # feed 同时下发两类地址：douyinvod 的临时签名直链和
        # www.douyin.com/aweme/v1/play 跳转地址。前者在电视端经常直接
        # 返回 403；后者会按当前请求重新签名并跳转到可播放的 CDN。
        url = next((x for x in candidates
                    if '/aweme/v1/play/?' in x), '')
        if not url:
            url = next((x for x in candidates
                        if '/aweme/v1/play/' in x), '')
        if not url:
            url = next(iter(candidates), '')
        return {'parse': 0, 'url': url,
                'header': {'User-Agent': UA, 'Referer': self.HOST + '/'}}

    def localProxy(self, param):
        params = param if isinstance(param, dict) else {}
        if params.get('type') == 'dyqr' and self.qr_bytes:
            return [200, self.qr_mime, self.qr_bytes,
                    {'Cache-Control':'no-store, no-cache, must-revalidate',
                     'Content-Length':str(len(self.qr_bytes))}]
        return [404, 'text/plain', 'not found']

    def _category(self, tab, page, ext):
        if tab not in self.TAB_INFO:
            tab = 'general'
        guide = str(ext.get('guide') or '').strip()
        keyword = self.BASE_KEYWORD + ((' ' + guide) if guide else '')
        data = self._search_api(tab, keyword, page)
        if tab == 'user':
            videos = self._parse_users(data)
        elif tab == 'live':
            videos = self._parse_lives(data)
        else:
            videos = self._parse_videos(data)
        if not videos and self._int(data.get('status_code'), 0) == 2483:
            videos = [self._login_notice(start=True)]
        if not videos and self._is_verify_check(data):
            videos = [self._verify_notice()]
        has_more = bool(data.get('has_more'))
        return {'list': videos, 'page': page,
                'pagecount': page + 1 if has_more else page,
                'limit': 20,
                'total': page * 20 + (20 if has_more else 0)}

    def _search_keyword(self, keyword, page):
        data = self._search_api('video', keyword, page)
        videos = self._parse_videos(data)
        if not videos and self._int(data.get('status_code'), 0) == 2483:
            videos = [self._login_notice(start=True)]
        if not videos and self._is_verify_check(data):
            videos = [self._verify_notice()]
        return {'list': videos, 'page': page,
                'pagecount': page + 1 if data.get('has_more') else page,
                'limit': 20, 'total': page * 20}

    def _search_api(self, tab, keyword, page):
        path, channel = self.TAB_INFO[tab]
        params = {
            'search_channel': channel, 'keyword': keyword,
            'search_source': 'normal_search' if page == 1 else 'tab_search',
            'query_correct_type': 1, 'is_filter_search': 0,
            'from_group_id': '', 'offset': (page - 1) * 20, 'count': 20,
            'need_filter_settings': 1, 'list_type': 'single',
        }
        return self._api_get(path, params, sign=True)

    def _api_get(self, path, params, sign=False):
        self._ensure_session()
        query_params = self._common_params()
        query_params.update(params or {})
        query = urlencode(query_params)
        if sign:
            try:
                query += '&a_bogus=' + make_a_bogus(query)
            except Exception:
                pass
        try:
            response = self.session.get(self.API + path + '?' + query,
                                        timeout=(5, 18))
            if response.status_code == 200 and response.text:
                return response.json()
        except Exception:
            pass
        return {}

    def _common_params(self):
        return {
            'device_platform':'webapp', 'aid':'6383',
            'channel':'channel_pc_web', 'cookie_enabled':'true',
            'screen_width':1920, 'screen_height':1080,
            'browser_language':'zh-CN', 'browser_platform':'Win32',
            'browser_name':'Chrome', 'browser_version':'151.0.0.0',
            'browser_online':'true', 'engine_name':'Blink',
            'engine_version':'151.0.0.0', 'os_name':'Windows',
            'os_version':'10', 'cpu_core_num':8, 'device_memory':8,
            'platform':'PC', 'downlink':10, 'effective_type':'4g',
            'round_trip_time':50, 'version_code':'170400',
            'version_name':'17.4.0', 'webid':self.webid,
            'update_version_code':'170400', 'pc_client_type':1,
            'pc_libra_divert':'Windows', 'support_h265':0,
            'support_dash':0, 'msToken':self.ms_token,
        }

    def _ensure_session(self):
        if self.ready:
            return
        # 登录 Cookie 中的 ttwid、ticket guard 与设备指纹是一组。
        # 重新注册匿名 ttwid 会覆盖它们，接口虽然返回 status_code=0，
        # 但结果会被降级为 search_nil_type=verify_check。
        if self.cookie_supplied or self.session.cookies.get('ttwid'):
            self.ready = True
            return
        body = {'region':'cn', 'aid':6383, 'needFid':False,
                'service':'www.douyin.com',
                'migrate_info':{'ticket':'', 'source':'node'},
                'cbUrlProtocol':'https', 'union':True}
        try:
            response = self.session.post(
                'https://ttwid.bytedance.com/ttwid/union/register/',
                json=body, timeout=(5, 10))
            callback = (response.json() or {}).get('redirect_url')
            if callback:
                self.session.get(callback, timeout=(5, 10))
        except Exception:
            pass
        self.ready = True

    def _parse_videos(self, data):
        found, seen = [], set()

        def walk(value):
            if isinstance(value, dict):
                item = value.get('aweme_info')
                if isinstance(item, dict):
                    add(item)
                if value.get('aweme_id') and isinstance(value.get('video'), dict):
                    add(value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        def add(item):
            aweme_id = str(item.get('aweme_id') or '')
            if not aweme_id or aweme_id in seen:
                return
            seen.add(aweme_id)
            self.item_cache[aweme_id] = item
            found.append(self._video_card(item))

        walk(data.get('data') or data.get('aweme_list') or [])
        return found

    def _parse_users(self, data):
        result = []
        for row in data.get('user_list') or []:
            user = row.get('user_info') if isinstance(row, dict) else None
            if not isinstance(user, dict):
                continue
            sec_uid = str(user.get('sec_uid') or '')
            if not sec_uid:
                continue
            self.user_cache[sec_uid] = user
            result.append({'vod_id':'user|' + sec_uid,
                           'vod_name':user.get('nickname') or '抖音用户',
                           'vod_pic':self._image(user.get('avatar_medium') or user.get('avatar_thumb')),
                           'vod_remarks':'粉丝 ' + self._short_num(user.get('follower_count'))})
        return result

    def _parse_lives(self, data):
        result, seen = [], set()
        rows = data.get('data') or []
        for row in rows:
            lives = row.get('lives') if isinstance(row, dict) else None
            candidates = lives if isinstance(lives, list) else [lives]
            for live in candidates:
                if not isinstance(live, dict):
                    continue
                payload = self._live_payload(live)
                room_id = str(payload.get('room_id') or payload.get('web_rid') or '')
                if not room_id or room_id in seen:
                    continue
                seen.add(room_id)
                result.append({'vod_id':'live|' + self._encode(payload),
                               'vod_name':payload.get('title') or '抖音直播',
                               'vod_pic':payload.get('cover') or '',
                               'vod_remarks':payload.get('nickname') or '直播中'})
        return result

    def _video_card(self, item):
        aweme_id = str(item.get('aweme_id') or '')
        author = item.get('author') or {}
        return {'vod_id':'video|' + aweme_id,
                'vod_name':item.get('desc') or ('抖音视频 ' + aweme_id),
                'vod_pic':self._image((item.get('video') or {}).get('cover')),
                'vod_remarks':author.get('nickname') or self._duration(item)}

    def _video_detail(self, item, aweme_id):
        if not isinstance(item, dict):
            return {'list': []}
        author = item.get('author') or {}
        urls = self._video_urls(item)
        play = '播放$' + self._encode({'urls':urls}) if urls else ''
        vod = {'vod_id':'video|' + aweme_id,
               'vod_name':item.get('desc') or ('抖音视频 ' + aweme_id),
               'vod_pic':self._image((item.get('video') or {}).get('cover')),
               'type_name':'抖音视频', 'vod_remarks':self._duration(item),
               'vod_year':'', 'vod_area':'中国大陆',
               'vod_actor':author.get('nickname') or '', 'vod_director':'',
               'vod_content':item.get('desc') or '',
               'vod_play_from':'抖音', 'vod_play_url':play}
        return {'list':[vod]}

    def _user_detail(self, sec_uid):
        user = self.user_cache.get(sec_uid) or {}
        data = self._api_get('/aweme/post/', {
            'sec_user_id':sec_uid, 'max_cursor':0, 'count':20,
            'locate_item_id':0, 'show_live_replay_strategy':1,
            'need_time_list':1, 'time_list_query':0,
        }, sign=True)
        items = data.get('aweme_list') or []
        plays = []
        for index, item in enumerate(items, 1):
            if not isinstance(item, dict):
                continue
            aweme_id = str(item.get('aweme_id') or '')
            if aweme_id:
                self.item_cache[aweme_id] = item
            urls = self._video_urls(item)
            if urls:
                name = (item.get('desc') or ('作品%d' % index)).replace('#', '＃').replace('$', '＄')
                plays.append(name[:35] + '$' + self._encode({'urls':urls}))
        vod = {'vod_id':'user|' + sec_uid,
               'vod_name':user.get('nickname') or '抖音用户',
               'vod_pic':self._image(user.get('avatar_medium') or user.get('avatar_thumb')),
               'type_name':'抖音用户',
               'vod_remarks':'粉丝 ' + self._short_num(user.get('follower_count')),
               'vod_year':'', 'vod_area':'', 'vod_actor':'', 'vod_director':'',
               'vod_content':user.get('signature') or '',
               'vod_play_from':'用户作品', 'vod_play_url':'#'.join(plays)}
        return {'list':[vod]}

    def _live_detail(self, payload):
        if not isinstance(payload, dict):
            return {'list': []}
        urls = payload.get('urls') or []
        play = '直播$' + self._encode({'urls':urls}) if urls else ''
        vod = {'vod_id':'live|' + self._encode(payload),
               'vod_name':payload.get('title') or '抖音直播',
               'vod_pic':payload.get('cover') or '', 'type_name':'直播',
               'vod_remarks':payload.get('nickname') or '直播中',
               'vod_year':'', 'vod_area':'', 'vod_actor':'', 'vod_director':'',
               'vod_content':payload.get('title') or '',
               'vod_play_from':'抖音直播', 'vod_play_url':play}
        return {'list':[vod]}

    def _live_payload(self, live):
        raw = live.get('rawdata') or live.get('raw_data') or live
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        owner = raw.get('owner') or live.get('author') or {}
        stream = raw.get('stream_url') or {}
        urls = []
        for key in ('hls_pull_url_map', 'flv_pull_url', 'flv_pull_url_map'):
            value = stream.get(key)
            if isinstance(value, dict):
                for quality in ('FULL_HD1','HD1','SD2','SD1'):
                    if value.get(quality):
                        urls.append(value[quality])
        if stream.get('hls_pull_url'):
            urls.append(stream['hls_pull_url'])
        try:
            text = stream['live_core_sdk_data']['pull_data']['stream_data']
            parsed = json.loads(text) if isinstance(text, str) else text
            for quality in (parsed.get('data') or {}).values():
                main = ((quality or {}).get('main') or {})
                urls.extend([main.get('hls'), main.get('flv')])
        except Exception:
            pass
        cover = self._image(raw.get('cover'))
        return {'room_id':str(raw.get('id_str') or raw.get('id') or ''),
                'web_rid':str(owner.get('web_rid') or ''),
                'title':raw.get('title') or '', 'nickname':owner.get('nickname') or '',
                'cover':cover, 'urls':list(dict.fromkeys(x for x in urls if x))}

    def _share_item(self, aweme_id):
        try:
            response = self.session.get('https://www.iesdouyin.com/share/video/' + aweme_id,
                                        headers={'User-Agent':UA_MOBILE}, timeout=(5, 15))
            match = re.search(r'window\._ROUTER_DATA\s*=\s*(.*?)</script>',
                              response.text, re.S)
            if match:
                data = json.loads(match.group(1).strip())
                loader = data.get('loaderData') or {}
                for value in loader.values():
                    if isinstance(value, dict):
                        items = (((value.get('videoInfoRes') or {}).get('item_list')) or [])
                        if items:
                            return items[0]
        except Exception:
            pass
        data = self._api_get('/aweme/detail/', {'aweme_id':aweme_id}, sign=True)
        return data.get('aweme_detail') or {}

    def _video_urls(self, item):
        video = item.get('video') or {}
        result = []
        rates = video.get('bit_rate') or []
        if isinstance(rates, list):
            rates = sorted(rates, key=lambda x:self._int((x or {}).get('bit_rate'), 0), reverse=True)
            for rate in rates:
                result.extend(self._urls((rate or {}).get('play_addr')))
        result.extend(self._urls(video.get('play_addr')))
        result.extend(self._urls(video.get('play_addr_265')))
        return list(dict.fromkeys(x.replace('http://', 'https://', 1)
                                  for x in result if str(x).startswith('http')))

    @staticmethod
    def _urls(value):
        if isinstance(value, dict):
            value = value.get('url_list') or value.get('urlList') or []
        if isinstance(value, str):
            return [value]
        return [str(x) for x in (value or []) if x]

    @classmethod
    def _image(cls, value):
        urls = cls._urls(value)
        return urls[0] if urls else ''

    @staticmethod
    def _duration(item):
        ms = ((item.get('video') or {}).get('duration') or 0)
        try:
            seconds = int(ms) // 1000
            return '%02d:%02d' % (seconds // 60, seconds % 60) if seconds else ''
        except Exception:
            return ''

    @staticmethod
    def _short_num(value):
        try:
            number = int(value or 0)
            if number >= 100000000:
                return ('%.1f亿' % (number / 100000000)).replace('.0亿', '亿')
            if number >= 10000:
                return ('%.1f万' % (number / 10000)).replace('.0万', '万')
            return str(number)
        except Exception:
            return '0'

    def _login_notice(self, start=False):
        if start and self.qr_status in ('idle', 'expired', 'error'):
            self._start_qr_login()
        names = {
            'loading': '正在生成抖音登录二维码，请稍后刷新',
            'waiting': '请用抖音 App 扫码登录',
            'scanned': '已扫码，请在手机上确认登录',
            'success': '扫码登录成功，请返回后重新进入分类',
            'expired': '二维码已过期，点击后返回并刷新',
            'blocked': '二维码接口触发安全验证，请改用 ext.cookie',
            'error': '二维码生成失败，点击查看说明',
        }
        name = names.get(self.qr_status, '抖音当前要求登录')
        remark = self.qr_message or ('扫码状态：' + self.qr_status)
        return {'vod_id':'login|qrcode', 'vod_name':name,
                'vod_pic':self.qr_image or self._qr_proxy_url(),
                'vod_remarks':remark}

    @staticmethod
    def _is_verify_check(data):
        info = data.get('search_nil_info') if isinstance(data, dict) else {}
        return isinstance(info, dict) and info.get('search_nil_type') == 'verify_check'

    @staticmethod
    def _verify_notice():
        return {
            'vod_id':'video|verify_required',
            'vod_name':'Cookie 已登录，但抖音要求网页安全验证',
            'vod_pic':'',
            'vod_remarks':'搜索请求被 verify_check 拦截',
        }

    def _login_detail(self):
        card = self._login_notice(start=True)
        content = (
            '请用抖音 App 扫描海报二维码并在手机端确认。确认后接口会自动接收登录 Cookie；'
            '返回上一页并刷新分类即可加载数据。若提示安全验证，说明抖音拦截了服务器的二维码请求，'
            '此时只能在 ext.cookie 中配置本人账号的有效 Cookie。'
        )
        vod = {'vod_id':'login|qrcode', 'vod_name':card['vod_name'],
               'vod_pic':card.get('vod_pic') or '', 'type_name':'扫码登录',
               'vod_remarks':card.get('vod_remarks') or '', 'vod_year':'',
               'vod_area':'', 'vod_actor':'', 'vod_director':'',
               'vod_content':content, 'vod_play_from':'扫码登录',
               'vod_play_url':'显示二维码$login_qrcode'}
        return {'list':[vod]}

    def _start_qr_login(self):
        with self.qr_lock:
            if self.qr_thread and self.qr_thread.is_alive():
                return
            self.qr_status = 'loading'
            self.qr_message = '正在请求二维码'
            self.qr_token = ''
            self.qr_image = ''
            self.qr_bytes = b''
            worker = threading.Thread(target=self._qr_login_worker,
                                      name='douyin-qr-login')
            worker.daemon = True
            self.qr_thread = worker
            worker.start()

    def _qr_login_worker(self):
        self._ensure_session()
        fingerprint = (self.session.cookies.get('s_v_web_id') or
                       ('verify_%d_%s' % (int(time.time() * 1000),
                                          self._random_token(36).replace('-', 'a').replace('_', 'b'))))
        params = {
            'service':'https://www.douyin.com', 'need_logo':'false',
            'need_short_url':'true', 'device_platform':'web_app',
            'aid':'6383', 'account_sdk_source':'sso',
            'sdk_version':'2.2.5', 'language':'zh',
            'verifyFp':fingerprint, 'fp':fingerprint,
        }
        headers = {'User-Agent':UA, 'Referer':self.HOST + '/',
                   'Accept':'application/json, text/plain, */*'}
        try:
            # 2026 网页端已迁移到 www.douyin.com/passport/web；旧的
            # sso.douyin.com/get_qrcode 会直接返回安全验证 HTML。
            response = self.session.get(
                'https://www.douyin.com/passport/web/get_qrcode/',
                params=params, headers=headers, timeout=(5, 18))
            content_type = str(response.headers.get('Content-Type') or '').lower()
            if 'json' not in content_type and not response.text.lstrip().startswith('{'):
                self.qr_status = 'blocked'
                self.qr_message = '抖音返回了人机验证页面'
                return
            result = response.json() or {}
            data = result.get('data') or {}
            if self._int(data.get('error_code'), 0):
                self.qr_status = 'blocked'
                self.qr_message = str(data.get('description') or
                                      result.get('message') or
                                      '抖音阻止了二维码请求')[:80]
                return
            token = str(data.get('token') or result.get('token') or '')
            qr_value = (data.get('qrcode') or data.get('qrcode_url') or
                        data.get('qrcode_index_url') or result.get('qrcode') or '')
            if not token or not qr_value:
                self.qr_status = 'error'
                self.qr_message = str(result.get('message') or '抖音没有返回二维码')
                return
            self.qr_token = token
            self.qr_image = self._qr_image_value(qr_value, headers)
            self.qr_status = 'waiting'
            self.qr_message = '等待扫码'
            self._poll_qr_login(params, headers)
        except Exception as error:
            self.qr_status = 'error'
            self.qr_message = ('二维码请求失败：' + str(error))[:80]

    def _poll_qr_login(self, params, headers):
        poll_params = dict(params)
        poll_params['token'] = self.qr_token
        for _ in range(90):
            if self.qr_status not in ('waiting', 'scanned'):
                return
            try:
                response = self.session.get(
                    'https://www.douyin.com/passport/web/check_qrconnect/',
                    params=poll_params, headers=headers, timeout=(5, 12))
                result = response.json() or {}
                data = result.get('data') or {}
                status = self._int(data.get('status'), -1)
                if status == 2:
                    self.qr_status = 'scanned'
                    self.qr_message = '已扫码，等待手机确认'
                elif status == 3:
                    redirect = str(data.get('redirect_url') or '')
                    if redirect:
                        self.session.get(redirect, headers=headers,
                                         allow_redirects=True, timeout=(5, 18))
                    self.cookie_supplied = True
                    self.qr_status = 'success'
                    self.qr_message = '登录成功，请刷新分类'
                    self._save_session_cookie()
                    return
                elif status == 5:
                    self.qr_status = 'expired'
                    self.qr_message = '二维码已过期'
                    return
            except Exception:
                pass
            time.sleep(2)
        self.qr_status = 'expired'
        self.qr_message = '二维码等待超时'

    def _qr_image_value(self, value, headers=None):
        text = str(value or '').strip()
        raw = b''
        mime = 'image/png'
        try:
            if text.startswith(('http://', 'https://')):
                response = self.session.get(text, headers=headers or {},
                                            timeout=(5, 15))
                if response.status_code == 200:
                    raw = response.content
                    mime = str(response.headers.get('Content-Type') or mime).split(';')[0]
            elif text.startswith('data:image/'):
                meta, payload = text.split(',', 1)
                raw = base64.b64decode(payload)
                mime = meta.split(';', 1)[0].split(':', 1)[1]
            else:
                raw = base64.b64decode(text)
                if raw.startswith(b'\xff\xd8\xff'):
                    mime = 'image/jpeg'
        except Exception:
            raw = b''
        if raw:
            self.qr_bytes = raw
            self.qr_mime = mime if mime.startswith('image/') else 'image/png'
            return self._qr_proxy_url()
        return text if text.startswith(('http://', 'https://')) else ''

    def _qr_proxy_url(self):
        if not self.qr_bytes:
            return ''
        try:
            proxy = str(self.getProxyUrl() or '')
        except Exception:
            proxy = ''
        if not proxy:
            return ''
        separator = '&' if '?' in proxy else '?'
        return '%s%stype=dyqr&t=%d' % (proxy, separator, int(time.time()))

    def _save_session_cookie(self):
        path = self.cookie_save_file
        if not path or path.startswith(('http://', 'https://')):
            return
        try:
            parent = os.path.dirname(os.path.abspath(path))
            if parent and os.path.isdir(parent):
                cookie = '; '.join('%s=%s' % item
                                   for item in self.session.cookies.get_dict().items())
                with open(path, 'w', encoding='utf-8') as handle:
                    handle.write(cookie)
        except Exception:
            pass

    @staticmethod
    def _encode(value):
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')

    @staticmethod
    def _decode(value):
        try:
            raw = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
            data = json.loads(raw.decode('utf-8'))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _random_token(length):
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
        rng = random.SystemRandom()
        return ''.join(rng.choice(alphabet) for _ in range(length))

    @staticmethod
    def _int(value, default=0):
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _dict(value):
        if isinstance(value, dict):
            return value
        getter = getattr(value, 'get', None)
        if callable(getter):
            result = {}
            for key in ('guide','sort_type','publish_time'):
                try:
                    item = getter(key)
                    if item not in (None, ''):
                        result[key] = str(item)
                except Exception:
                    pass
            return result
        try:
            data = json.loads(str(value or '{}'))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @classmethod
    def _parse_ext(cls, extend):
        if isinstance(extend, dict):
            return extend
        getter = getattr(extend, 'get', None)
        if callable(getter):
            try:
                cookie = getter('cookie')
                if cookie:
                    return {'cookie':str(cookie)}
            except Exception:
                pass
        try:
            text = str(extend or '').strip()
            if text.startswith('{'):
                data = json.loads(text)
                return data if isinstance(data, dict) else {}
            return {'cookie':text} if '=' in text else {}
        except Exception:
            return {}

    @staticmethod
    def _load_cookie(value):
        text = str(value or '').strip()
        if not text:
            return ''
        if text.startswith(('http://','https://')):
            try:
                return requests.get(text, timeout=(5, 10)).text.strip()
            except Exception:
                return ''
        if os.path.isfile(text):
            try:
                with open(text, 'r', encoding='utf-8-sig') as handle:
                    return handle.read().strip()
            except Exception:
                return ''
        return text


# ----------------------------------------------------------------------
# 抖音精选（长视频频道）
# 保留上方经过验证的请求签名、视频详情和播放工具，仅替换数据入口。
class Spider(DouyinBaseSpider):
    TAGS = (
        ('全部', '0'),
        ('公开课', '100000'),
        ('游戏', '300205'),
        ('二次元', '300206'),
        ('音乐', '300209'),
        ('影视', '300215'),
        ('美食', '300204'),
        ('知识', '300213'),
        ('小剧场', '300214'),
        ('生活vlog', '300216'),
        ('体育', '300207'),
        ('旅行', '300221'),
        ('亲子', '300217'),
        ('动物', '300220'),
        ('三农', '300219'),
        ('汽车', '300218'),
        ('美妆穿搭', '300222'),
    )

    def init(self, extend=''):
        # 精选频道无需登录 Cookie；仍兼容用户主动传入 Cookie。
        DouyinBaseSpider.init(self, extend)
        self.session.headers.update({
            'Referer': 'https://www.douyin.com/jingxuan/',
            'Origin': 'https://www.douyin.com',
        })

    def getName(self):
        return '抖音精选'

    def homeContent(self, filter):
        return {
            'class': [
                {'type_name': name, 'type_id': tag_id}
                for name, tag_id in self.TAGS
            ]
        }

    def homeVideoContent(self):
        return {'list': self._jingxuan_category('0', 1).get('list', [])}

    def categoryContent(self, tid, pg, filter, extend):
        return self._jingxuan_category(str(tid or '0'), self._int(pg, 1))

    def searchContent(self, key, quick, pg='1'):
        # 精选网页自身没有独立站内搜索数据源。
        return {'list': [], 'page': self._int(pg, 1), 'pagecount': 1,
                'limit': 20, 'total': 0}

    def searchContentPage(self, key, quick, pg='1'):
        return self.searchContent(key, quick, pg)

    def _jingxuan_category(self, tag_id, page):
        known = {item[1] for item in self.TAGS}
        if tag_id not in known:
            tag_id = '0'
        # “公开课”的 100000 只是前端标签编号，内容并不来自普通
        # channel/feed 接口。抖音网页对此分类使用独立的课程接口。
        if tag_id == '100000':
            return self._jingxuan_course(page)
        params = {
            'count': 20,
            'tag_id': '' if tag_id == '0' else tag_id,
            'Seo-Flag': 0,
            'refresh_index': max(1, page),
            'awemePcRecRawData': json.dumps(
                {'is_client': False}, separators=(',', ':')),
        }
        data = self._api_get('/channel/feed/', params, sign=True)
        videos = self._parse_videos(data)
        # 精选流偶尔混入直播卡片；没有普通 video 字段时安全忽略。
        has_more = bool(videos)
        return {
            'list': videos,
            'page': page,
            'pagecount': page + 1 if has_more else page,
            'limit': 20,
            'total': page * 20 + (20 if has_more else 0),
        }

    def _jingxuan_course(self, page):
        limit = 6
        params = {
            'tab_id': 'screen_course_page',
            'offset': max(0, page - 1) * limit,
            'size': limit,
            'tag_id_list': '[0,0,0]',
            'id_list': '',
        }
        data = self._api_get(
            '/douyin/select/tab/course/catagory/video/', params, sign=True)
        # 此接口偶尔首包返回 status_code=3，网页端同样会自动重试。
        if self._int(data.get('status_code'), -1) != 0:
            data = self._api_get(
                '/douyin/select/tab/course/catagory/video/', params, sign=True)
        items = data.get('video_items') or []
        for item in items:
            if not isinstance(item, dict):
                continue
            small = self._image(
                (item.get('chan_feed_video') or {}).get('small_card_url'))
            video = item.get('video')
            if small and isinstance(video, dict):
                video['cover'] = {'url_list': [small]}
        videos = self._parse_videos({'data': items})
        has_more = bool(data.get('has_more'))
        return {
            'list': videos,
            'page': page,
            'pagecount': page + 1 if has_more else page,
            'limit': limit,
            'total': page * limit + (limit if has_more else 0),
        }


# TVBox 加载器固定查找上方名为 Spider 的类。
