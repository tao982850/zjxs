# -*- coding: utf-8 -*-
import re, urllib.parse
import json
import time
from html import unescape as _html_unescape
try:
    from bs4 import BeautifulSoup
except Exception:  # 宿主未内置 bs4 时不能让整包导入失败
    BeautifulSoup = None
try:
    import requests
except Exception:  # 宿主未提供 requests 时不让整包导入失败
    requests = None
from base.spider import Spider as BaseSpider

# ==================== 合并后的播放地址 / 站点地址 ====================
# 站点主域名（合并三个源脚本：4k枫叶.py 的兜底域名、枫叶影院.py、枫叶影院 (1).py）
SITE_HOSTS = [
    "https://www.china-itrade.com",  # 茶杯狐（template/ch，默认主站）
    "https://www.cd-zj.com",   # 枫叶影院.py / 4k枫叶.py 兜底域名
    "https://maihaolian.com",  # 枫叶影院 (1).py 主域名
    "https://www.cadkssb.com",  # 发布页备用域名，同为枫叶镜像
]
DEFAULT_HOST = SITE_HOSTS[0]

# 播放解析接口（三个脚本中的 api_map 合并去重）
PLAY_APIS = {
    "YYNB": "https://zzrs.mfdyvip.com/player/mplayer.php",
    "JD4K": "https://fgsrg.hzqingshan.com/player/mplayer.php",
}
# 取 token 的中间页
TOKEN_PAGE = "https://fgsrg.hzqingshan.com/player/?url={}"
# 首页 VIP 精选栏目（/label/ 页面已被拦截，取首页栏目卡片）
VIP_LABELS = {
    "qq": "腾讯SVIP热映",
    "bli": "B站SVIP热映",
    "youku": "优酷SVIP热映",
}
# 播放地址为空时的占位流
ERROR_M3U8 = "https://php.doube.eu.org/error.m3u8"


class Spider(BaseSpider):
    # 缓存变量，避免频繁请求发布页
    _cache_host = ""
    _cache_time = 0
    CACHE_DURATION = 300  # 缓存5分钟

    def init(self, extend="", *args, **kwargs):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self._template = ''
        self._player_cfg = {}
        self._vip_host = ''

        # 配置里若直接给了站点域名，优先用它（域名被墙/被换时不必改脚本）
        self._ext_host = self._parse_ext_host(extend)

        # init 内不联网：初始化阶段发请求容易超时/抛异常，宿主会直接报「爬虫失败」，
        # 主站探测延后到第一次取数据时执行（见 _ensure_host）
        if self._ext_host:
            self.host = self._ext_host
            return
        if self._cache_host and time.time() - self._cache_time < self.CACHE_DURATION:
            self.host = self._cache_host
            return
        self.host = ''

    def _parse_ext_host(self, extend):
        """extend 支持纯域名、URL，或含 url/host/api/site 字段的 JSON"""
        if not extend:
            return ''
        if isinstance(extend, dict):
            for k in ('url', 'host', 'api', 'site'):
                v = extend.get(k)
                if isinstance(v, str) and v.strip().startswith('http'):
                    return v.strip().rstrip('/')
            return ''
        text = str(extend).strip()
        if text.startswith('http'):
            return text.split('|')[0].strip().rstrip('/')
        try:
            data = json.loads(text)
        except Exception:
            return ''
        if isinstance(data, dict):
            for k in ('url', 'host', 'api', 'site'):
                v = data.get(k)
                if isinstance(v, str) and v.strip().startswith('http'):
                    return v.strip().rstrip('/')
        return ''

    def _hosts(self):
        """候选站点：配置/当前域名优先，其后是合并进来的镜像域名"""
        hosts = []
        for h in [getattr(self, '_ext_host', ''), getattr(self, 'host', '')] + SITE_HOSTS:
            if h and h not in hosts:
                hosts.append(h)
        return hosts

    def _set_host(self, host):
        if host and host != getattr(self, 'host', ''):
            self.host = host
            self._template = ''
            self._player_cfg = {}

    def _ensure_host(self):
        """确定主站：配置域名 > 会话缓存 > 默认站；不做串行探测，避免启动超时"""
        if getattr(self, 'host', ''):
            return self.host
        host = getattr(self, '_ext_host', '') or ''
        if not host and self._cache_host and time.time() - self._cache_time < self.CACHE_DURATION:
            host = self._cache_host
        self.host = host or DEFAULT_HOST
        self._cache_host = self.host
        self._cache_time = time.time()
        return self.host

    def getName(self):
        return '茶杯狐'

    def homeContent(self, filter=True, *args, **kwargs):
        self._ensure_host()
        # 站点 /label/ 与 /cupfox-list/ 页面已被安全验证拦截，只用接口取得到的真实分类
        return {"class": [
            {"type_id": "qq", "type_name": "腾讯VIP精选"},
            {"type_id": "bli", "type_name": "B站VIP精选"},
            {"type_id": "youku", "type_name": "优酷VIP精选"},
            {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "3", "type_name": "综艺"},
            {"type_id": "5", "type_name": "热门短剧"},
            {"type_id": "20", "type_name": "纪录片"},
        ], "filters": self._build_filters()}

    def _build_filters(self):
        """站点列表页已被 WAF 拦截，分类改走 JSON 接口；接口只认 tid，
        地区/年份/剧情/语言/字母/排序 会被接口忽略，留着必然变成空白，
        因此这里只保留能真正落地的「类型」筛选。"""
        tv = [{"n": "全部", "v": "2"}, {"n": "国产剧", "v": "13"},
              {"n": "日韩剧", "v": "15"}, {"n": "海外剧", "v": "16"}]
        movie = [{"n": "全部", "v": "1"}, {"n": "动作片", "v": "6"}, {"n": "喜剧片", "v": "7"},
                 {"n": "恐怖片", "v": "8"}, {"n": "科幻片", "v": "9"}, {"n": "爱情片", "v": "10"},
                 {"n": "剧情片", "v": "11"}, {"n": "战争片", "v": "12"}, {"n": "纪录片", "v": "20"}]
        anime = [{"n": "全部", "v": "4"}, {"n": "国产动漫", "v": "25"}, {"n": "日韩动漫", "v": "26"}]
        show = [{"n": "全部", "v": "3"}, {"n": "大陆综艺", "v": "21"}, {"n": "日韩综艺", "v": "22"}]
        return {
            "2": [{"key": "class", "name": "类型", "value": tv}],
            "1": [{"key": "class", "name": "类型", "value": movie}],
            "4": [{"key": "class", "name": "类型", "value": anime}],
            "3": [{"key": "class", "name": "类型", "value": show}],
        }

    def homeVideoContent(self, *args, **kwargs):
        self._ensure_host()
        html = self._fetch('/')
        items = self._parse_video_list_ch(html) or self._parse_video_list(html)
        if not items:
            data = self._fetch_json('/index.php/ajax/data?mid=1&tid=0&page=1&limit=30')
            items = self._ajax_items(data.get('list'))
        return {"list": items}

    def homeVod(self, *args, **kwargs):
        """部分宿主用 homeVod 取首页卡片，与 homeVideoContent 等价"""
        return self.homeVideoContent()

    def categoryContent(self, tid, pg, filter, extend, *args, **kwargs):
        self._ensure_host()
        # 构建筛选参数：参照歪比巴卜，直接取extend里的值，fallback到filter
        tid = str(tid)

        args = {}
        if isinstance(extend, list):
            # 部分宿主把筛选项传成 [{"key":..,"value":..}]
            for it in extend:
                if isinstance(it, dict) and it.get('key') is not None:
                    v = it.get('value')
                    if v not in (None, ''):
                        args[str(it['key'])] = str(v)
        elif extend and isinstance(extend, dict):
            for k, v in extend.items():
                if v not in (None, ''):
                    args[k] = str(v)
        if isinstance(filter, dict):
            for k, v in filter.items():
                if v not in (None, '') and k not in args:
                    args[k] = str(v)
        route_tid = args.get('class') or args.get('tid') or str(tid)
        page = int(pg) if str(pg).isdigit() else 1
        if tid in VIP_LABELS:
            items = self._vip_list(tid)
            return {"list": items, "page": 1, "pagecount": 1 if items else 0,
                    "limit": 30, "total": len(items)}
        if not route_tid.isdigit():
            # 站点 /label/ 页面已被拦截，非分类 id 直接返回空，避免拿全站列表冒充
            return {"list": [], "page": page, "pagecount": 0, "limit": 30, "total": 0}

        # 站点 HTML 列表页（/cupfox-list/、/list/）在所有镜像上都被安全验证拦截，
        # 直接走 JSON 接口，避免每次分类都先浪费一个必然失败的请求
        return self._ajax_category(route_tid, page)

    def _vip_list(self, key):
        """VIP 精选：站点 /label/ 已被拦截，改从首页同名栏目卡片取（跨镜像找有该栏目的站）"""
        marker = VIP_LABELS.get(key)
        if not marker:
            return []
        hosts = self._hosts()
        if getattr(self, '_vip_host', '') in hosts:
            hosts = [self._vip_host] + [h for h in hosts if h != self._vip_host]
        for host in hosts:
            page = self._get_text(host + '/')
            if not page or marker not in page:
                continue
            start = page.rfind('<div', 0, page.find(marker))
            nxt = page.find('vod-list-b', page.find(marker))
            seg = page[max(start, 0):nxt if nxt > 0 else page.find(marker) + 8000]
            items = self._parse_video_list(seg)
            if items:
                # 只借该站取栏目，不切换主站；详情/播放会按域名自动回退
                self._vip_host = host
                return items
        return []

    def _fetch_json(self, path):
        """取 JSON：相对路径会跨镜像域名重试，并兼容 list/data/result 三种返回包法"""
        urls = [path] if path.startswith('http') else [h + path for h in self._hosts()]
        for url in urls:
            text = self._get_text(url)
            if not text:
                continue
            try:
                data = json.loads(text)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if isinstance(data.get('list'), list):
                self._set_host(url.split('/index.php')[0])
                return data
            for k in ('data', 'result'):
                v = data.get(k)
                if isinstance(v, dict) and isinstance(v.get('list'), list):
                    self._set_host(url.split('/index.php')[0])
                    return v
        return {}

    def _ajax_category(self, tid, page):
        """用站点 index.php/ajax/data 接口取分类列表
        （该接口未被 WAF 拦截；分页参数是 page，limit 仅接受 10/20/30）"""
        limit = 30
        params = {'mid': '1', 'tid': tid, 'page': page, 'limit': limit}
        data = self._fetch_json('/index.php/ajax/data?' + urllib.parse.urlencode(params))
        items = self._ajax_items(data.get('list'))
        if not items:
            return {"list": [], "page": page, "pagecount": 0, "limit": limit, "total": 0}
        pagecount = int(data.get('pagecount') or 1)
        return {"list": items, "page": min(page, pagecount), "pagecount": pagecount,
                "limit": limit, "total": int(data.get('total') or 0)}

    def _ajax_items(self, lst):
        items = []
        for v in lst or []:
            vid = v.get('vod_id')
            if vid in (None, ''):
                continue
            pic = v.get('vod_pic') or v.get('vod_pic_thumb') or ''
            items.append({
                "vod_id": str(vid),
                "vod_name": (v.get('vod_name') or '').strip(),
                "vod_pic": self._fix_pic(pic),
                "vod_remarks": (v.get('vod_remarks') or '').strip(),
                "vod_year": str(v.get('vod_year') or ''),
                "vod_area": str(v.get('vod_area') or ''),
                "vod_lang": str(v.get('vod_lang') or ''),
                "vod_letter": str(v.get('vod_letter') or ''),
                "vod_class": str(v.get('vod_class') or ''),
                "vod_score": str(v.get('vod_score') or ''),
                "vod_hits": str(v.get('vod_hits') or ''),
            })
        return items

    def detailContent(self, ids, *args, **kwargs):
        self._ensure_host()
        result = {"list": []}
        vid = ids[0].split(',')[0].strip()
        try:
            html = self._fetch(f'/detail/{vid}.html')
            if not html:
                return result
            best = self._best_detail(html, vid)
            if not best or not best.get('vod_play_url') or not best.get('vod_name'):
                # 站点模板会变（template/e 与 template/ch 混用），换域名取一份能解析的
                for host in self._hosts():
                    alt = self._get_text(host + f'/detail/{vid}.html')
                    if not alt:
                        continue
                    cand = self._best_detail(alt, vid)
                    if cand and cand.get('vod_play_url') and cand.get('vod_name'):
                        best = cand
                        self._set_host(host)
                        break
            if best:
                result["list"].append(best)
        except Exception as e:
            print(e)
        return result

    def _best_detail(self, html, vid):
        """按页面结构选择详情解析器，返回信息最完整的一份"""
        has_ch = 'play_list_box' in html or 'titleName' in html
        has_fuye = 'slide-info-title' in html or 'anthology-list-box' in html
        # 结构特征明确时按页面模板选解析器，避免两套解析器都给部分结果时选错
        if has_ch and not has_fuye:
            parsers = [self._detail_ch]
        elif has_fuye and not has_ch:
            parsers = [self._detail_fuye]
        else:
            parsers = [self._detail_ch, self._detail_fuye]
        best = {}
        for parser in parsers:
            try:
                cand = parser(html, vid)
            except Exception:
                cand = None
            if not cand:
                continue
            if cand.get('vod_name') and cand.get('vod_play_url'):
                return cand
            if not best or (cand.get('vod_play_url') and not best.get('vod_play_url')):
                best = cand
        return best

    def _detail_fuye(self, html, vid):
        """枫叶模板(template/e)详情解析"""
        soup = self._soup(html)
        if soup is None:
            return self._detail_fuye_re(html, vid)
        name_el = soup.select_one('h3.slide-info-title')
        vod_name = self._clean(name_el.text) if name_el else ''
        pic_el = soup.select_one('img.lazy')
        vod_pic = self._fix_pic(pic_el.get('data-src', '')) if pic_el else ''
        vod_director = ''
        vod_actor = ''
        for el in soup.select('.slide-info'):
            text = el.get_text(' ').strip()
            if text.startswith('导演：'):
                vod_director = text.replace('导演：', '').strip()
            elif text.startswith('演员：'):
                vod_actor = text.replace('演员：', '').strip()
        content_el = soup.select_one('#height_limit')
        vod_content = content_el.get_text(' ', strip=True) if content_el else ''
        play_from, play_url = [], []
        for tab in soup.select('.anthology-tab a.swiper-slide'):
            src_name = self._clean(str(tab)) or self._clean(tab.get_text(' ', strip=True))
            if src_name:
                play_from.append(src_name)
        for i, block in enumerate(soup.select('.anthology-list-box')):
            ep_list = []
            for a in block.select('li a'):
                href = a.get('href', '')
                m = re.search(r'/play/(.*?)\.html', href)
                if m:
                    ep_list.append(f'{a.text.strip()}${vid}-{m.group(1)}')
            ep_list.reverse()
            if ep_list and i < len(play_from):
                play_url.append('#'.join(ep_list))
        valid_from = [pf for i, pf in enumerate(play_from) if i < len(play_url)]
        return {
            "vod_id": vid, "vod_name": vod_name, "vod_pic": vod_pic,
            "vod_director": vod_director, "vod_actor": vod_actor,
            "vod_content": vod_content,
            "vod_play_from": "$$$".join(valid_from),
            "vod_play_url": "$$$".join(play_url),
        }

    def searchContent(self, key, quick, pg="1", *args, **kwargs):
        self._ensure_host()
        try:
            decoded = urllib.parse.unquote(key)
        except:
            decoded = key
        html = self._fetch(f'/cupfox-search/{urllib.parse.quote(decoded)}----------{pg}---.html')
        items = self._parse_search_list(html)
        return {"list": items, "page": int(pg), "pagecount": 1, "limit": 36, "total": len(items)}

    def playerContent(self, flag, id, vipFlags=None, *args, **kwargs):
        self._ensure_host()
        url = ''
        try:
            html, url = self._fetch_play_page(id)
            if html:
                m = re.search(r'player_aaaa=(.*?)</script>', html, re.S)
                if m:

                    try:
                        pd = json.loads(m.group(1))
                    except Exception as e:
                        print(e)
                        pd = {}
                    # print('pd:', pd)
                    play_url = pd.get('url')
                    play_id = pd.get('from')

                    if not play_url:
                        return {"parse": 0, "url": ERROR_M3U8,
                                "header": {'User-Agent': 'Mozilla/5.0'}}
                    if play_url.startswith('http') and (play_url.endswith('.m3u8') or play_url.endswith('.mp4')):
                        return {"parse": 0, "url": play_url, "header": {'User-Agent': 'Mozilla/5.0'}}

                    else:
                        headers = {
                            'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                            'Accept': "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                            'accept-language': "zh-CN,zh;q=0.9",
                            'cache-control': "no-cache",
                            'pragma': "no-cache",
                            'priority': "u=0, i",
                            'referer': "https://www.ht10010.com/",
                            'Content-Type': 'application/x-www-form-urlencoded',
                        }
                        # 解析接口优先取站点 playerconfig.js 里配置的地址（不同站点/线路不同）
                        parse_base = self._player_parse_url(play_id)
                        if not parse_base:
                            parse_base = TOKEN_PAGE.format('')
                        token_page = self._get_text(parse_base + play_url, headers)
                        token = re.search(r'data-te="(.*?)"', token_page)
                        m3u8 = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', token_page or '')
                        if not token and m3u8:
                            return {"parse": 0, "url": m3u8.group(0),
                                    "header": {'User-Agent': 'Mozilla/5.0'}}
                        if token:
                            token = token.group(1)
                            payload = {
                                'url': play_url,
                                'token': token
                            }
                            # 解析接口：优先同域 mplayer，其次合并进来的接口，最后全部兜底
                            apis = []
                            if '/player/?url=' in parse_base:
                                apis.append(parse_base.split('/player/?url=')[0] + '/player/mplayer.php')
                            if play_id in PLAY_APIS:
                                apis.append(PLAY_APIS[play_id])
                            apis += list(PLAY_APIS.values())
                            apis = list(dict.fromkeys(apis))
                            for api in apis:
                                try:
                                    try:
                                        response = self.post(api, data=payload, headers=headers)
                                    except TypeError:
                                        response = self.post(api, data=payload)

                                    response.raise_for_status()
                                    result = response.json()
                                    # print('result:', result)
                                    if result.get('code') == 200 and result.get('url'):
                                        return {"parse": 0, "url": result['url'], "header": {
                                            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'}}
                                except Exception as e:
                                    print(e)
        except Exception as e:
            print(e)
        return {"parse": 1, "url": url}

    def _fetch_play_page(self, id):
        """依次用当前主站与合并的镜像域名取播放页，返回 (html, url)"""
        url = ''
        hosts = [self.host] + [h for h in SITE_HOSTS if h != self.host]
        for host in hosts:
            url = id if id.startswith('http') else f'{host}/play/{id}.html'
            html = self._fetch(url)
            if html and 'player_aaaa' in html:
                return html, url
        return '', url

    def localProxy(self, param='', *args, **kwargs):
        return {}

    def isVideoFormat(self, url, *args, **kwargs):
        return False

    def manualVideoCheck(self, *args, **kwargs):
        return False

    def _get_text(self, url, headers=None):
        """单次取文本，兼容宿主 fetch 返回对象的差异"""
        try:
            try:
                rsp = self.fetch(url, headers=headers or self.headers, timeout=15)
            except TypeError:
                try:
                    rsp = self.fetch(url, headers=headers or self.headers)
                except TypeError:
                    # 个别宿主的 fetch 不接受 headers 关键字
                    rsp = self.fetch(url)
            if not rsp:
                return ''
            text = getattr(rsp, 'text', '')
            if text:
                return text
            content = getattr(rsp, 'content', b'')
            if isinstance(content, (bytes, bytearray)):
                return content.decode('utf-8', 'ignore')
            return ''
        except Exception:
            return ''

    def _fetch(self, url, headers=None):
        """取页面：相对路径会在多个镜像域名之间自动重试，并记住可用的域名"""
        if url.startswith('http'):
            return self._get_text(url, headers)
        last = ''
        for host in self._hosts():
            text = self._get_text(host + url, headers)
            if not text:
                continue
            last = last or text
            if '系统安全验证' in text:
                continue
            self._set_host(host)
            return text
        return last

    def _fix_pic(self, u):
        if not u: return ''
        u = u.replace('&amp;', '&').strip()
        if u.startswith('//'): return 'https:' + u
        if u.startswith('/'): return (getattr(self, 'host', '') or '') + u
        return u

    def _clean(self, text):
        """去标签、解 HTML 实体、去不换行空格"""
        if not text:
            return ''
        text = re.sub(r'<[^>]+>', '', str(text))
        try:
            text = _html_unescape(text)
        except Exception:
            pass
        return text.replace('\u00a0', ' ').strip()

    def _soup(self, html):
        """宿主缺 bs4 时返回 None，各解析器改用正则兜底"""
        if BeautifulSoup is None or not html:
            return None
        try:
            return BeautifulSoup(html, 'html.parser')
        except Exception:
            return None

    def _parse_video_list(self, html):
        soup = self._soup(html)
        if soup is None:
            return self._parse_video_list_re(html)
        videos, seen = [], set()
        cards = soup.select('a.public-list-exp')
        for a in cards:
            href = a.get('href', '')
            m = re.search(r'/detail/(\d+)\.html', href)
            if not m: continue
            vod_id = m.group(1)
            if vod_id in seen: continue
            seen.add(vod_id)
            span = ','.join([span.text for span in a.select('span.public-prt')])
            # print('span', span)
            vod_name = a.get('title', '') or (a.select_one('img') and a.select_one('img').get('alt', '')) or ''
            pic_el = a.select_one('img')
            vod_pic = self._fix_pic(pic_el.get('data-src', '')) if pic_el else ''
            remark_el = a.select_one('.ft2') or a.select_one('.public-list-prb')
            vod_remarks = remark_el.text.strip() if remark_el else ''
            videos.append(
                {"vod_id": vod_id, "vod_name": vod_name.strip(), "vod_pic": vod_pic, "vod_remarks": vod_remarks, "vod_year": span})
        return videos

    def _parse_video_list_ch(self, html):
        """茶杯狐模板(template/ch)列表解析"""
        soup = self._soup(html)
        if soup is None:
            return self._parse_video_list_ch_re(html)
        videos, seen = [], set()
        for item in soup.select('.movie-list-item'):
            a = item.select_one('a[href*="/detail/"]')
            if not a:
                continue
            m = re.search(r'/detail/(\d+)\.html', a.get('href', ''))
            if not m:
                continue
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            title_el = item.select_one('.movie-title')
            name = self._clean(title_el.get_text(' ', strip=True)) if title_el else self._clean(a.get('title') or '')
            remark = ''
            for el in item.select('.pic-text'):
                t = el.get_text(strip=True)
                if t:
                    remark = t
                    break
            img = item.select_one('img')
            pic = self._fix_pic((img.get('data-src') or img.get('src') or '') if img else '')
            videos.append({"vod_id": vid, "vod_name": name.strip(), "vod_pic": pic, "vod_remarks": remark})
        return videos

    def _detail_ch(self, html, vid):
        """茶杯狐模板(template/ch)详情解析"""
        if self._soup(html) is None:
            return self._detail_ch_re(html, vid)
        try:
            soup = BeautifulSoup(html, 'html.parser')
            title = soup.title.get_text(strip=True) if soup.title else ''
            m = re.search(r'《(.*?)》', title)
            vod_name = m.group(1).strip() if m else title.split('_')[0].strip()
            img = soup.select_one('img[data-src]') or soup.select_one('img')
            vod_pic = self._fix_pic((img.get('data-src') or img.get('src') or '') if img else '')
            meta = soup.select_one('meta[name="description"]')
            vod_content = (meta.get('content') or '').strip() if meta else ''
            vod_actor = ''
            m = re.search(r'主演[:：]\s*([^\s<]{2,80})', soup.get_text(' ', strip=True))
            if m:
                vod_actor = m.group(1)
            tabs = soup.select('a.titleName')
            boxes = soup.select('div.play_list_box')
            play_from, play_url = [], []
            for i, box in enumerate(boxes):
                eps = []
                for a in box.select('a[href*="/play/"]'):
                    mm = re.search(r'/play/(\d+)-(\d+)-(\d+)\.html', a.get('href', ''))
                    if not mm:
                        continue
                    name = a.get_text(strip=True) or mm.group(3)
                    eps.append(f'{name}${mm.group(1)}-{mm.group(2)}-{mm.group(3)}')
                if not eps:
                    continue
                eps.reverse()
                label = ''
                if i < len(tabs):
                    label = re.sub(r'\[\d+\]\s*$', '', tabs[i].get_text(strip=True)).strip()
                play_from.append(label or f'线路{i + 1}')
                play_url.append('#'.join(eps))
            return {
                "vod_id": vid, "vod_name": vod_name, "vod_pic": vod_pic,
                "vod_actor": vod_actor, "vod_content": vod_content,
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url),
            }
        except Exception as e:
            print(e)
        return {}

    def _player_config(self):
        """读取站点 /static/js/playerconfig.js 的线路 -> 解析接口映射"""
        cfg = getattr(self, '_player_cfg', None)
        if isinstance(cfg, dict) and cfg:
            return cfg
        cfg = {}
        text = self._get_text(self.host + '/static/js/playerconfig.js')
        if text:
            i = text.find('player_list=')
            if i >= 0:
                try:
                    obj, _ = json.JSONDecoder().raw_decode(text[i + len('player_list='):])
                    if isinstance(obj, dict):
                        cfg = obj
                except Exception:
                    cfg = {}
        self._player_cfg = cfg
        return cfg

    def _player_parse_url(self, key):
        item = self._player_config().get(key) or {}
        return str(item.get('parse') or '')

    def _parse_video_list_re(self, html):
        """无 bs4 时的枫叶列表正则解析"""
        videos, seen = [], set()
        for chunk in re.split(r'public-list-exp', html or '')[1:]:
            head = chunk[:2500]
            m = re.search(r'/detail/(\d+)\.html', head)
            if not m:
                continue
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            t = re.search(r'title="([^"]*)"', head)
            img = re.search(r'data-src="([^"]+)"', head)
            rem = re.search(r'class="[^"]*(?:public-list-prb|ft2)[^"]*"[^>]*>([^<]*)<', chunk)
            videos.append({
                "vod_id": vid,
                "vod_name": self._clean(t.group(1) if t else ''),
                "vod_pic": self._fix_pic(img.group(1) if img else ''),
                "vod_remarks": self._clean(rem.group(1) if rem else ''),
            })
        return videos

    def _parse_video_list_ch_re(self, html):
        """无 bs4 时的茶杯狐列表正则解析"""
        videos, seen = [], set()
        for chunk in re.split(r'movie-list-item', html or '')[1:]:
            head = chunk[:3000]
            m = re.search(r'/detail/(\d+)\.html', head)
            if not m:
                continue
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            t = re.search(r'movie-title[^"]*"[^>]*>([^<]*)<', head)
            img = re.search(r'data-src="([^"]+)"', head)
            rem = re.search(r'pic-text[^"]*"[^>]*>(.*?)</', head, re.S)
            remark = self._clean(rem.group(1) if rem else '')
            videos.append({
                "vod_id": vid,
                "vod_name": self._clean(t.group(1) if t else ''),
                "vod_pic": self._fix_pic(img.group(1) if img else ''),
                "vod_remarks": remark,
            })
        return videos

    def _detail_fuye_re(self, html, vid):
        """无 bs4 时的枫叶详情正则解析"""
        html = html or ''
        m = re.search(r'<h3[^>]*class="[^"]*slide-info-title[^"]*"[^>]*>(.*?)</h3>', html, re.S)
        vod_name = self._clean(m.group(1)) if m else ''
        vod_pic = ''
        im = re.search(r'<img[^>]*class="[^"]*lazy[^"]*"[^>]*>', html)
        if im:
            ds = re.search(r'data-src="([^"]+)"', im.group(0))
            vod_pic = self._fix_pic(ds.group(1)) if ds else ''
        c = re.search(r'<div[^>]*id="height_limit"[^>]*>(.*?)</div>', html, re.S)
        vod_content = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', c.group(1))).strip() if c else ''
        play_from = []
        tab = re.search(r'anthology-tab(.*?)anthology-list', html, re.S)
        if tab:
            for a in re.findall(r'<a[^>]*>(.*?)</a>', tab.group(1), re.S):
                name = self._clean(a)
                if name:
                    play_from.append(name)
        play_url = []
        for i, blk in enumerate(re.split(r'anthology-list-box', html)[1:]):
            eps = []
            for href, txt in re.findall(r'<a[^>]*href="(/play/[^"]+?)\.html"[^>]*>(.*?)</a>', blk, re.S):
                eps.append(f"{self._clean(txt)}${vid}-{href[len('/play/'):]}")
            eps.reverse()
            if eps and i < len(play_from):
                play_url.append('#'.join(eps))
        valid_from = [pf for i, pf in enumerate(play_from) if i < len(play_url)]
        return {"vod_id": vid, "vod_name": vod_name, "vod_pic": vod_pic,
                "vod_content": vod_content,
                "vod_play_from": "$$$".join(valid_from),
                "vod_play_url": "$$$".join(play_url)}

    def _detail_ch_re(self, html, vid):
        """无 bs4 时的茶杯狐详情正则解析"""
        html = html or ''
        t = re.search(r'<title>(.*?)</title>', html, re.S)
        title = self._clean(t.group(1)) if t else ''
        m = re.search(r'《(.*?)》', title)
        vod_name = m.group(1).strip() if m else title.split('_')[0].strip()
        img = re.search(r'data-src="([^"]+)"', html)
        vod_pic = self._fix_pic(img.group(1)) if img else ''
        md = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', html)
        vod_content = md.group(1).strip() if md else ''
        tabs = []
        for a in re.findall(r'<a[^>]*class="[^"]*titleName[^"]*"[^>]*>(.*?)</a>', html, re.S):
            name = self._clean(a)
            tabs.append(re.sub(r'\[\d+\]\s*$', '', name).strip())
        play_from, play_url = [], []
        for i, blk in enumerate(re.split(r'play_list_box', html)[1:]):
            eps = []
            for mm in re.finditer(r'href="/play/(\d+)-(\d+)-(\d+)\.html"[^>]*>(.*?)</a>', blk, re.S):
                name = self._clean(mm.group(4)) or mm.group(3)
                eps.append(f"{name}${mm.group(1)}-{mm.group(2)}-{mm.group(3)}")
            if not eps:
                continue
            eps.reverse()
            label = tabs[i] if i < len(tabs) else ''
            play_from.append(label or f"线路{i + 1}")
            play_url.append('#'.join(eps))
        return {"vod_id": vid, "vod_name": vod_name, "vod_pic": vod_pic,
                "vod_content": vod_content,
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url)}

    def _parse_search_list(self, html):
        if self._soup(html) is None:
            return self._parse_video_list_re(html)

        videos, seen = [], set()
        soup = BeautifulSoup(html, 'html.parser')
        cards = soup.select('a.public-list-exp')
        for a in cards:
            href = a.get('href', '')
            m = re.search(r'/detail/(\d+)\.html', href)
            if not m: continue
            vod_id = m.group(1)
            if vod_id in seen: continue
            seen.add(vod_id)
            pic_el = a.select_one('img')
            vod_pic = self._fix_pic(pic_el.get('data-src', '')) if pic_el else ''
            title_el = soup.select_one(f'a.thumb-txt[href="/detail/{vod_id}.html"]')
            if title_el:
                vod_name = title_el.text.strip()
            else:
                vod_name = a.select_one('img') and a.select_one('img').get('alt', '') or ''
            remark_el = a.select_one('.public-list-prb') or a.select_one('.ft2')
            vod_remarks = remark_el.text.strip() if remark_el else ''
            videos.append(
                {"vod_id": vod_id, "vod_name": vod_name.strip(), "vod_pic": vod_pic, "vod_remarks": vod_remarks})
        return videos
