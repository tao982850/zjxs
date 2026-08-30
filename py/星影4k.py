# -*- coding: utf-8 -*-
"""
星影 (XingYing) —— TVBox / 影视仓 爬虫源
站点: http://43.248.128.122:8080

逆向要点（供自己复盘，勿删）
================================
1. 站点形态: Nuxt3(Vue SSR) 前端 + Go API 后端，apiBase = /api
2. 播放地址是密文，但不需要本地解密——后端提供解析端点:
     POST /api/parse  {"url": <密文>, "from": <线路名>, "vod_id": <int>}
   密文是定长凭证句柄（75字节装不下416字符的明文URL），逆向无收益，直接薅端点。
3. 40110 请登录后观看 的破解: 必须带设备指纹头
     X-Device-Type: web
     X-Device-ID:   web_<10位随机base36><时间戳hex>   (前端存 localStorage: xingying_device_id)
     X-Device-Name / X-Device-Model
   device_id 客户端自造 → 换一个额度重置（游客 3 次/天/设备）。
4. 图片必须走 /api/image-proxy?url=<urlencode>（豆瓣/优酷图床直连 418）。
5. 播放直链无 Referer/UA 校验，裸请求 200，parse:0 直连。
6. 分类参数是 t=<type_id>，不是 type_id/tid/category_id（会被静默忽略返回全站）。
7. 线路: duanju=mp4直链(有真4K，分辨率跟片源走), rose=m3u8直链,
        qq/bilibili=明文平台页(转嗅探), co/zijianm3u8=死线(剔除)。

影视仓兼容性注意（空白问题排查记录）
================================
- categoryContent 里 filter=True 时【必须照常返回数据】。首次进分类页壳会传
  filter=1 拿筛选面板，若只回 filters 不回 list -> 页面全空白。
- filters 标准格式: {tid: [{key,name,value:[{n,v}]}]}，放 homeContent 返回。
- 必须实现 getName/init，init 里做懒初始化（有的壳只调 init 不走 __init__）。
- 所有接口全 try-except，任何异常都返回空结构，绝不抛出。
"""

import json
import re
import time
import random

try:
    import requests
except Exception:
    requests = None

try:
    from urllib import request as _u
    from urllib.parse import quote, urlencode
except Exception:
    try:
        import urllib2 as _u
        from urllib import quote
        from urllib import urlencode
    except Exception:
        _u = None

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass


class Spider(BaseSpider):
    HOST = 'http://43.248.128.122:8080'
    API = HOST + '/api'
    UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')

    LINE_PRIORITY = {'duanju': 0, 'rose': 1}
    LINE_BLACKLIST = {'co', 'zijianm3u8'}
    # 线路显示名(影视仓里播放源标签用中文)。注意 playerContent 收到的 flag 是显示名，
    # 需经 LINE_BACK 译回站点真实线路名，再 POST /api/parse（from 字段必须站点的英文名）。
    LINE_NAMES = {'duanju': '蓝光4K', 'rose': '超清', 'szys': '速影',
                  'qq': '腾讯视频', 'bilibili': '哔哩哔哩', 'youku': '优酷',
                  'iqiyi': '爱奇艺', 'mgtv': '芒果TV'}
    LINE_BACK = {v: k for k, v in LINE_NAMES.items()}
    # 明文线路里的已知平台页域名(需嗅探/解析)，其余明文默认按直链探测
    PLATFORM_PAGES = ('youku.com', 'v.qq.com', 'iqiyi.com', 'bilibili.com',
                      'mgtv.com', 'tv.sohu.com', 'le.com', 'douyin.com')
    AREAS = ['内地', '中国大陆', '中国', '中国香港', '中国台湾', '美国', '韩国', '日本', '泰国', '英国', '法国', '印度', '其他']
    SORTS = [('最新', 'time'), ('最热', 'hits'), ('评分', 'score')]

    def getName(self):
        return '星影'

    def getDependence(self):
        return []

    def init(self, extend=''):
        try:
            if not getattr(self, '_did', None):
                self._lazy_init()
        except Exception:
            self._lazy_init()
        return ''

    def _lazy_init(self):
        self._did = None
        self._quota = 0
        self._cat_cache = None
        self._detail_cache = {}      # 详情缓存：影视仓反复请求同一详情 + 规避 42900 限流
        self._last_vod_id = None
        self._token = None
        self._cache = {}
        self._cache_ttl = 1800
        self._alive = True
        self._alive_t = 0        # 探活时间戳缓存(60s)，站挂最多 60s 后自动恢复
        self._session = None
        try:
            if requests is not None:
                self._session = requests.Session()
                self._session.trust_env = False
        except Exception:
            self._session = None

    def __init__(self):
        self._lazy_init()

    def isVideoFormat(self, url):
        try:
            return bool(re.search(r'\.(m3u8|mp4|flv|ts)(\?|$)', url or '', re.I))
        except Exception:
            return False

    def manualVideoCheck(self):
        return False

    # ---------------- HTTP 层 ----------------
    def _device(self, force_new=False):
        if force_new or not getattr(self, '_quota', 0) or not getattr(self, '_did', None):
            rnd = ''.join(random.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(10))
            self._did = 'web_%s%s' % (rnd, format(int(time.time()), 'x'))
            self._quota = 3
        return self._did

    def _headers(self, json_body=False):
        h = {
            'User-Agent': self.UA,
            'Referer': self.HOST + '/',
            'Origin': self.HOST,
            'Accept': 'application/json, text/plain, */*',
            'X-Device-Type': 'web',
            'X-Device-ID': self._device(),
            'X-Device-Name': 'Win32',
            'X-Device-Model': 'Chrome',
        }
        if json_body:
            h['Content-Type'] = 'application/json'
        if getattr(self, '_token', None):
            h['Authorization'] = 'Bearer %s' % self._token
        return h

    def _fetch(self, url, data=None, timeout=15):
        body = None
        if data is not None:
            try:
                body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            except Exception:
                body = json.dumps(data).encode('utf-8')
        hdr = self._headers(json_body=body is not None)

        # 1) requests 优先
        if getattr(self, '_session', None) is not None:
            try:
                if body is not None:
                    r = self._session.post(url, data=body, headers=hdr, timeout=timeout)
                else:
                    r = self._session.get(url, headers=hdr, timeout=timeout)
                return r.status_code, r.text
            except Exception:
                pass

        # 2) urllib 兜底
        if _u is None:
            return 0, ''
        try:
            req = _u.Request(url, data=body, headers=hdr)
            resp = _u.urlopen(req, timeout=timeout)
            try:
                code = resp.getcode()
            except Exception:
                code = 200
            try:
                txt = resp.read().decode('utf-8', 'ignore')
            except Exception:
                txt = ''
            return code, txt
        except Exception as e:
            try:
                return e.code, e.read().decode('utf-8', 'ignore')
            except Exception:
                return 0, ''

    def _json(self, url, data=None, timeout=15):
        """带 42900 限流退避的 JSON 请求。
        站点限流实测：IP 维度约 10 次/10 秒（换 device_id 无效），等 2.5s 即恢复"""
        try:
            code, txt = self._fetch(url, data=data, timeout=timeout)
            if not txt:
                return {}
            rj = json.loads(txt)
            if rj.get('code') == 42900:
                time.sleep(2.5)
                code, txt = self._fetch(url, data=data, timeout=timeout)
                if not txt:
                    return {}
                try:
                    rj = json.loads(txt)
                except Exception:
                    return {}
            return rj
        except Exception:
            return {}

    def _check_alive(self):
        """站点探活: 结果缓存 60s，站挂后最多 60s 自动恢复。
        探活端点 /api/guest/config 无需设备头即可返回 code:0，最轻量。"""
        now = time.time()
        if self._alive_t and now - self._alive_t < 60:
            return self._alive
        try:
            code, txt = self._fetch('%s/guest/config' % self.API, timeout=8)
            ok = False
            if txt:
                try:
                    ok = json.loads(txt).get('code') == 0
                except Exception:
                    ok = code == 200 and '星影' in txt
            self._alive = ok
        except Exception:
            self._alive = False
        self._alive_t = now
        return self._alive

    # ---------------- 工具 ----------------
    def _img(self, pic):
        """图片域名分流（实测结论）:
        - cms.meilinvps.com/img.php?url=<豆瓣图> —— 站点自建中转，直连 200，别再包
        - 裸 doubanio.com —— 有防盗链(418)，须走站点 image-proxy（代理白名单放行豆瓣）
        - 腾讯qpic/B站hdslb/优酷ykimg/爱奇艺iqiyipic —— 直连全 200，不要包代理
          （站点 image-proxy 有域名白名单，hdslb/iqiyipic 等会 403 host not allowed）"""
        if not pic:
            return ''
        if 'img.php?url=' in pic:
            return pic
        if 'doubanio.com' in pic:
            return '%s/image-proxy?url=%s' % (self.API, quote(pic, safe=''))
        return pic

    def _vod(self, v):
        try:
            return {
                'vod_id': str(v.get('vod_id', '')),
                'vod_name': v.get('vod_name', '') or '',
                'vod_pic': self._img(v.get('vod_pic', '')),
                'vod_remarks': v.get('vod_remarks') or (str(v.get('vod_year')) if v.get('vod_year') else ''),
            }
        except Exception:
            return {'vod_id': '', 'vod_name': '', 'vod_pic': '', 'vod_remarks': ''}

    def _text(self, s):
        if not s:
            return ''
        try:
            s = re.sub(r'<[^>]+>', '', str(s))
            return re.sub(r'\s+', ' ', s).strip()
        except Exception:
            return ''

    def _register(self):
        if getattr(self, '_token', None):
            return self._token
        try:
            for _ in range(3):
                phone = '139' + ''.join(random.choice('0123456789') for _ in range(8))
                rj = self._json('%s/auth/register' % self.API,
                                data={'phone': phone, 'password': 'Aa123456', 'nickname': 'tvbox'})
                d = rj.get('data') or {}
                tok = (d.get('token') or {}).get('access_token')
                if tok:
                    self._token = tok
                    return tok
        except Exception:
            pass
        return None

    # ---------------- 筛选 ----------------
    def _build_filters(self):
        """全站 filters: {tid: [{key,name,value:[{n,v}]}]} —— 标准列表式"""
        filters = {}
        cats = getattr(self, '_cat_cache', None)
        if not cats:
            try:
                cats = self._json('%s/categories' % self.API).get('data') or []
                self._cat_cache = cats
            except Exception:
                cats = []
        years = [{'n': '全部', 'v': ''}]
        try:
            import datetime
            y0 = datetime.datetime.now().year
        except Exception:
            y0 = 2026
        for y in range(y0, y0 - 15, -1):
            years.append({'n': str(y), 'v': str(y)})
        common = [
            {'key': 'area', 'name': '地区',
             'value': [{'n': '全部', 'v': ''}] + [{'n': a, 'v': a} for a in self.AREAS]},
            {'key': 'year', 'name': '年份', 'value': years},
            {'key': 'sort', 'name': '排序',
             'value': [{'n': n, 'v': v} for n, v in self.SORTS]},
        ]
        for c in cats:
            try:
                tid = str(c.get('type_id'))
                if tid == '7':          # 空分类不生成筛选
                    continue
                groups = [{'key': 'class', 'name': '剧情', 'value': [{'n': '全部', 'v': ''}]}]
                ext = c.get('type_extend') or ''
                try:
                    ext = json.loads(ext) if isinstance(ext, str) else (ext or {})
                except Exception:
                    ext = {}
                for name in (ext.get('class') or []):
                    groups[0]['value'].append({'n': name, 'v': name})
                filters[tid] = groups + common
            except Exception:
                continue
        return filters

    # ---------------- 1. homeContent ----------------
    def homeContent(self, filter_=None):
        result = {'class': [], 'list': []}
        try:
            if not self._check_alive():
                return result          # 站点不可用 -> 优雅返回空，影视仓不白屏不崩
        except Exception:
            pass
        try:
            cats = getattr(self, '_cat_cache', None)
            if not cats:
                cats = self._json('%s/categories' % self.API).get('data') or []
                self._cat_cache = cats
            for c in cats:
                # 漫剧(type_id=7)数据库为空，显示空分类会被当成源坏了——剔除。
                # 若站方后续上内容，删掉这个判断即可。
                if str(c.get('type_id')) in ('7',):
                    continue
                result['class'].append({
                    'type_id': str(c.get('type_id')),
                    'type_name': c.get('type_name', '') or '',
                })
        except Exception:
            pass
        try:
            if filter_:
                result['filters'] = self._build_filters()
        except Exception:
            pass
        try:
            rank = self._json('%s/ranking?type=weekly&limit=24' % self.API)
            rl = rank.get('data') or []
            for v in rl:
                if isinstance(v, dict):
                    result['list'].append(self._vod(v))
        except Exception:
            pass
        return result

    def homeVideoContent(self):
        return {'list': []}

    # ---------------- 2. categoryContent ----------------
    def categoryContent(self, tid, pg, filter_=None, extend=None):
        # 铁律: filter=True 时也必须返回数据列表，filters 只是附加字段。
        # 影视仓首次进分类页会传 filter=1，只回面板不回数据 = 白屏。
        result = {'list': [], 'page': 1, 'pagecount': 1, 'limit': 24, 'total': 0}
        try:
            if not self._check_alive():
                return result
        except Exception:
            pass
        try:
            extend = extend or {}
            try:
                page = int(pg)
            except Exception:
                page = 1
            if page < 1:
                page = 1
            params = {'page': page, 'limit': 24}
            if tid and str(tid) not in ('0', '', 'None'):
                params['t'] = tid          # 是 t 不是 type_id！
            for k in ('class', 'area', 'year', 'lang', 'sort'):
                if extend.get(k):
                    params[k] = extend[k]
            url = '%s/videos?%s' % (self.API, urlencode(params))
            data = self._json(url).get('data') or {}
            lst = data.get('list') or []
            total = data.get('total') or 0
            pc = (int(total) + 23) // 24 if total else 1
            result['list'] = [self._vod(v) for v in lst]
            result['page'] = page
            result['pagecount'] = pc
            result['total'] = total
        except Exception:
            pass
        return result

    # ---------------- 3. detailContent ----------------
    def detailContent(self, ids):
        result = {'list': []}
        try:
            if not self._check_alive():
                return result
        except Exception:
            pass
        try:
            vid = str(ids[0])
            # 详情缓存：影视仓常重复请求同一详情；且规避 42900 限流
            hit = self._detail_cache.get(vid)
            if hit:
                result['list'] = [dict(hit)]
                return result
            d = self._json('%s/videos/%s' % (self.API, vid)).get('data') or {}
            if not d:
                return result
            try:
                self._last_vod_id = int(vid)
            except Exception:
                self._last_vod_id = None

            lines = d.get('play_list') or []
            try:
                lines = sorted(lines, key=lambda x: self.LINE_PRIORITY.get(x.get('from'), 99))
            except Exception:
                pass
            froms, urls = [], []
            for ln in lines:
                try:
                    frm = ln.get('from')
                    eps = ln.get('episodes') or []
                    if not frm or not eps:
                        continue
                    if frm in self.LINE_BLACKLIST:
                        continue
                    parts = []
                    for ep in eps:
                        name = ep.get('name') if isinstance(ep, dict) else str(ep)
                        url = ep.get('url') if isinstance(ep, dict) else str(ep)
                        if url:
                            parts.append('%s$%s' % (name, url))
                    if parts:
                        froms.append(self.LINE_NAMES.get(frm, frm))
                        urls.append('#'.join(parts))
                except Exception:
                    continue

            vod = {
                'vod_id': str(d.get('vod_id')),
                'vod_name': d.get('vod_name', '') or '',
                'vod_pic': self._img(d.get('vod_pic') or d.get('vod_pic_thumb') or ''),
                'type_name': d.get('type_name') or (d.get('vod_class') or ''),
                'vod_year': str(d.get('vod_year') or ''),
                'vod_area': d.get('vod_area') or '',
                'vod_remarks': d.get('vod_remarks') or '',
                'vod_actor': d.get('vod_actor') or '',
                'vod_director': d.get('vod_director') or '',
                'vod_content': self._text(d.get('vod_content') or d.get('vod_blurb') or ''),
                'vod_play_from': '$$$'.join(froms),
                'vod_play_url': '$$$'.join(urls),
            }
            result['list'] = [vod]
            self._detail_cache[vid] = dict(vod)
        except Exception:
            pass
        return result

    # ---------------- 4. searchContent ----------------
    def searchContent(self, key, quick=False, pg=1):
        result = {'list': []}
        try:
            if not self._check_alive():
                return result
        except Exception:
            pass
        try:
            try:
                page = int(pg)
            except Exception:
                page = 1
            if page < 1:
                page = 1
            url = '%s/search?wd=%s&page=%s&limit=24' % (self.API, quote(str(key)), page)
            data = self._json(url).get('data') or {}
            result['list'] = [self._vod(v) for v in (data.get('list') or [])]
        except Exception:
            pass
        return result

    # ---------------- 5. playerContent ----------------
    def _sniff_head(self, url):
        """拉 URL 前 32 字节判断内容类型（Range 请求，轻量）"""
        hdr = {'User-Agent': self.UA, 'Range': 'bytes=0-31'}
        try:
            if self._session is not None:
                r = self._session.get(url, headers=hdr, timeout=8)
                if r.status_code in (200, 206):
                    return r.content[:32]
        except Exception:
            pass
        try:
            if _u is not None:
                req = _u.Request(url, headers=hdr)
                resp = _u.urlopen(req, timeout=8)
                return resp.read(32)
        except Exception:
            pass
        return b''

    def _plain_type(self, url):
        """明文 URL 判直链(0)还是平台页(1)。结果缓存 1 小时。
        后缀能判就后缀判；无后缀拉 32 字节看头：
        #EXTM3U / M3U / ftyp = 直链； < 开头 = HTML 页面(嗅探)"""
        ck = ('sniff', url)
        hit = self._cache.get(ck)
        if hit and hit[1] > time.time():
            return hit[0]
        try:
            low = url.lower()
            for d in self.PLATFORM_PAGES:
                if d in low:
                    self._cache[ck] = (1, time.time() + 3600)
                    return 1
            path = low.split('?')[0]
            if path.endswith(('.m3u8', '.mp4', '.flv', '.ts', '.mpd')):
                self._cache[ck] = (0, time.time() + 3600)
                return 0
            head = self._sniff_head(url)
            if not head:
                pt = 0            # 探测失败默认直连，让播放器自己试
            elif (b'#EXTM3U' in head or head[:3] == b'M3U'
                  or b'ftyp' in head or head[:3] == b'ID3'):
                pt = 0
            elif head[:1] == b'<' or b'<html' in head.lower():
                pt = 1
            else:
                pt = 0
            self._cache[ck] = (pt, time.time() + 3600)
            return pt
        except Exception:
            return 0

    def playerContent(self, flag, id_, vipFlags=None):
        try:
            id_ = str(id_)
            # 明文地址（qq/bilibili/SZYS 等线路放的是明文链接）：不走服务端解析
            if id_.startswith('http://') or id_.startswith('https://'):
                pt = self._plain_type(id_)
                return {'parse': pt, 'playUrl': '', 'url': id_,
                        'header': {'User-Agent': self.UA}, 'message': ''}

            # 缓存（省游客额度）
            ck = (flag, id_)
            hit = self._cache.get(ck)
            if hit and hit[1] > time.time():
                return {'parse': 0, 'playUrl': '', 'url': hit[0],
                        'header': {'User-Agent': self.UA, 'Referer': ''},
                        'message': hit[2] if len(hit) > 2 else ''}

            self._device()
            real_from = self.LINE_BACK.get(flag, flag)   # 中文显示名译回站点线路名
            payload = {'url': id_, 'from': real_from}
            if getattr(self, '_last_vod_id', None):
                payload['vod_id'] = self._last_vod_id

            def _parse(did):
                h = self._headers(json_body=True)
                h['X-Device-ID'] = did
                return self._json('%s/parse' % self.API, data=payload, timeout=20)

            rj = _parse(self._did)
            self._quota -= 1
            if rj.get('code') == 40311:                    # 额度尽 -> 换设备
                rj = _parse(self._device(force_new=True))
                self._quota -= 1
            if rj.get('code') in (40110, 40311, 40310):    # 游客通道关 -> 注册兜底
                if self._register():
                    rj = _parse(self._device(force_new=True))

            if rj.get('code') != 0:
                return {'parse': 0, 'playUrl': '', 'url': '',
                        'message': rj.get('message') or '解析失败'}

            d = rj.get('data') or {}
            play_url = d.get('url') or ''
            ptype = d.get('player_type', 0)
            pname = d.get('player_name') or ''
            if play_url:
                self._cache[ck] = (play_url, time.time() + self._cache_ttl, pname)
            return {
                'parse': 0 if ptype == 0 else 1,
                'playUrl': '',
                'url': play_url,
                'header': {'User-Agent': self.UA, 'Referer': ''},
                'message': pname,
            }
        except Exception:
            return {'parse': 0, 'playUrl': '', 'url': '', 'message': '异常'}

    # ---------------- 6. localProxy ----------------
    def localProxy(self, param):
        return None


if __name__ == '__main__':
    s = Spider()
    s.init()
    # 模拟影视仓真实调用链
    hm = s.homeContent(True)
    print('分类:', [(c['type_id'], c['type_name']) for c in hm['class']])
    print('筛选面板 tid=2:', [g['name'] for g in (hm.get('filters') or {}).get('2', [])])
    print('首页推荐数:', len(hm['list']))
    cat = s.categoryContent('2', '1', True, {})
    print('分类页(filter=1)条数:', len(cat['list']), '总页:', cat['pagecount'])
    cat2 = s.categoryContent('2', '1', False, {'class': '古装', 'sort': 'hits'})
    print('分类页(筛选)条数:', len(cat2['list']))
    r = s.searchContent('庆余年')
    print('搜索:', [x['vod_name'] for x in r['list'][:3]])
    d = s.detailContent([r['list'][0]['vod_id']])['list'][0]
    print('详情:', d['vod_name'], '| 线路:', d['vod_play_from'])
    f = d['vod_play_from'].split('$$$')[0]
    u = d['vod_play_url'].split('$$$')[0].split('#')[0].split('$', 1)[1]
    pc = s.playerContent(f, u)
    print('播放: parse=%s | %s' % (pc['parse'], pc['url'][:100]))
