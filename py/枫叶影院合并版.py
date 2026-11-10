# -*- coding: utf-8 -*-
import re, urllib.parse
import json
import time
from bs4 import BeautifulSoup
import requests
from base.spider import Spider as BaseSpider
import requests
import base64

# ==================== 合并后的播放地址 / 站点地址 ====================
# 站点主域名（合并三个源脚本：4k枫叶.py 的兜底域名、枫叶影院.py、枫叶影院 (1).py）
SITE_HOSTS = [
    "https://www.cd-zj.com",   # 枫叶影院.py / 4k枫叶.py 兜底域名
    "https://maihaolian.com",  # 枫叶影院 (1).py 主域名
    "https://www.cadkssb.com",  # 发布页备用域名，同为枫叶镜像
]
DEFAULT_HOST = SITE_HOSTS[0]
# 发布页：动态下发可用域名
PUBLISH_URL = "https://www.vip1949.com/"

# 播放解析接口（三个脚本中的 api_map 合并去重）
PLAY_APIS = {
    "YYNB": "https://zzrs.mfdyvip.com/player/mplayer.php",
    "JD4K": "https://fgsrg.hzqingshan.com/player/mplayer.php",
}
# 取 token 的中间页
TOKEN_PAGE = "https://fgsrg.hzqingshan.com/player/?url={}"
# 播放地址为空时的占位流
ERROR_M3U8 = "https://php.doube.eu.org/error.m3u8"
# 歌词地址
LRC_URL = "https://8877.kstore.space/jar/yy/%E4%B8%B0.txt"


class Spider(BaseSpider):
    # 缓存变量，避免频繁请求发布页
    _cache_host = ""
    _cache_time = 0
    CACHE_DURATION = 300  # 缓存5分钟

    def init(self, extend=""):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        # 优先读取缓存，没有或过期则重新获取
        now = time.time()
        if self._cache_host and now - self._cache_time < self.CACHE_DURATION:
            self.host = self._cache_host
        else:
            self.host = self.get_online_host()
            self._cache_host = self.host
            self._cache_time = now
        # 分类列表页是否可用（被 WAF/验证码拦截后置 False，本会话内改走 JSON 接口）
        self._list_html_ok = None

    def get_online_host(self):
        """已知枫叶域名为先（模板与解析一致），全部不可用时再用发布页下发域名"""
        for url in SITE_HOSTS:
            if self.check_url_online(url) and self._is_fuye(url):
                return url
        for url in self._publish_hosts():
            if url not in SITE_HOSTS and self.check_url_online(url) and self._is_fuye(url):
                return url
        return DEFAULT_HOST

    def _publish_hosts(self):
        """解析发布页 JS 里下发的域名列表（键名不带引号，且可能夹带别家站点）"""
        hosts = []
        try:
            resp = requests.get(PUBLISH_URL, headers=self.headers, timeout=15)
            resp.raise_for_status()
            match = re.search(r'const domains = (\[.*?\]);', resp.text, re.S)
            if match:
                for url in re.findall(r'url\s*:\s*["\']([^"\']+)["\']', match.group(1)):
                    url = url.strip().rstrip("/")
                    if url and url not in hosts:
                        hosts.append(url)
        except Exception as e:
            print(f"获取发布页异常: {e}")
        return hosts

    def _is_fuye(self, host):
        """校验域名确实指向枫叶站点：发布页里的域名可能挂的是模板不同的别家站"""
        try:
            html = self._fetch(host + '/')
            return bool(html) and ('枫叶' in html or 'public-list-exp' in html or '/cupfox-list/' in html)
        except Exception:
            return False

    def check_url_online(self, url, timeout=3):
        """检测网址是否可正常访问"""
        try:
            r = requests.head(url, headers=self.headers, timeout=timeout, allow_redirects=True)
            return 200 <= r.status_code < 400
        except:
            return False

    def getName(self):
        return '枫叶影院'

    def homeContent(self, filter):
        return {"class": [
            {'type_id': "/label/qq", 'type_name': "腾讯VIP精选"},
            {'type_id': "/label/bli", 'type_name': "B站VIP精选"},
            {'type_id': "/label/youku", 'type_name': "优酷VIP精选"},
            {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "3", "type_name": "综艺"},
            {"type_id": "5", "type_name": "热门短剧"},
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

    def homeVideoContent(self):
        html = self._fetch('/')
        return {"list": self._parse_video_list(html)}

    def categoryContent(self, tid, pg, filter, extend):
        # 构建筛选参数：参照歪比巴卜，直接取extend里的值，fallback到filter
        if tid.startswith('/label'):
            url = f'{tid}/page/{pg}.html'
            html = self._fetch(url)
            items = self._parse_video_list(html)
            page = int(pg)
            page_count = page if len(items) < 24 else page + 2
            return {"list": items, "page": page, "pagecount": page_count, "limit": 24, "total": page_count * 24}

        args = {}
        if extend and isinstance(extend, dict):
            for k, v in extend.items():
                if v not in (None, ''):
                    args[k] = str(v)
        if isinstance(filter, dict):
            for k, v in filter.items():
                if v not in (None, '') and k not in args:
                    args[k] = str(v)
        route_tid = args.get('class') or args.get('tid') or str(tid)
        filters = {k: args.get(k, '') for k in ('area', 'year', 'genre', 'lang', 'letter')}
        sort = args.get('sort', '')
        page = int(pg) if str(pg).isdigit() else 1

        # 1) 优先走站点 HTML 列表页（可用时站点端筛选与分页最准）
        if self._list_html_ok is not False:
            if not any(filters.values()):
                # 无筛选走正常分页：{tid}--------{page}---.html
                url = f'/cupfox-list/{route_tid}--------{page}---.html'
            else:
                # 有筛选：{tid}-{area}-{sort}-{genre}-{lang}-{letter}------{year}.html
                segs = [route_tid, filters['area'], sort, filters['genre'],
                        filters['lang'], filters['letter'], '', '', filters['year']]
                url = '/cupfox-list/' + '-'.join(segs) + '.html'
            html = self._fetch(url)
            # 拦截页特征：系统安全验证；可用页至少含列表容器或详情链接
            blocked = (not html) or ('系统安全验证' in html) or \
                      not any(k in html for k in ('public-list', '/detail/', 'page-link'))
            if not blocked:
                self._list_html_ok = True
                items = self._parse_video_list(html)
                if not items:
                    # 页面正常但没有条目，说明该筛选组合确实无结果
                    return {"list": [], "page": page, "pagecount": 0, "limit": 36, "total": 0}
                pagecount = page
                soup = BeautifulSoup(html, 'html.parser')
                for a in soup.select('a.page-link'):
                    if a.text.strip() == '尾页':
                        m = re.search(r'---(\d+)---', a.get('href', ''))
                        if m:
                            pagecount = int(m.group(1))
                        break
                return {"list": items, "page": page, "pagecount": max(pagecount, page),
                        "limit": 36, "total": 9999}
            # 被 WAF/验证码拦截（或列表页结构不可用）：本会话内改用 JSON 列表接口
            self._list_html_ok = False

        # 2) 兜底：站点 JSON 列表接口（HTML 列表页被 WAF 拦截时走这里）
        return self._ajax_category(route_tid, page)

    def _fetch_json(self, url):
        text = self._fetch(url)
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
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

    def detailContent(self, ids):
        result = {"list": []}
        vid = ids[0].split(',')[0].strip()
        try:
            html = self._fetch(f'/detail/{vid}.html')
            if not html: return result
            soup = BeautifulSoup(html, 'html.parser')
            vod_name = soup.select_one('h3.slide-info-title')
            vod_name = vod_name.text.strip() if vod_name else ''
            vod_pic = soup.select_one('img.lazy')
            vod_pic = self._fix_pic(vod_pic.get('data-src', '')) if vod_pic else ''
            vod_director = ''
            vod_actor = ''
            for el in soup.select('.slide-info'):
                text = el.get_text(' ').strip()
                if text.startswith('导演：'):
                    vod_director = text.replace('导演：', '').strip()
                elif text.startswith('演员：'):
                    vod_actor = text.replace('演员：', '').strip()
            vod_content = soup.select_one('#height_limit')
            vod_content = vod_content.get_text(' ', strip=True) if vod_content else ''
            play_from, play_url = [], []
            for tab in soup.select('.anthology-tab a.swiper-slide'):
                src_name = re.sub(r'<[^>]+>', '', str(tab)).strip() or tab.get_text(' ', strip=True).strip()
                if src_name:
                    play_from.append(src_name)
            tab_blocks = soup.select('.anthology-list-box')
            for i, block in enumerate(tab_blocks):
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
            result["list"].append({
                "vod_id": vid, "vod_name": vod_name, "vod_pic": vod_pic,
                "vod_director": vod_director, "vod_actor": vod_actor,
                "vod_content": vod_content,
                "vod_play_from": "$$$".join(valid_from),
                "vod_play_url": "$$$".join(play_url),
            })
        except:
            pass
        return result

    def searchContent(self, key, quick, pg="1"):
        try:
            decoded = urllib.parse.unquote(key)
        except:
            decoded = key
        html = self._fetch(f'/cupfox-search/{urllib.parse.quote(decoded)}----------{pg}---.html')
        items = self._parse_search_list(html)
        return {"list": items, "page": int(pg), "pagecount": 1, "limit": 36, "total": len(items)}

    def playerContent(self, flag, id, vipFlags):
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
                        response = requests.get(TOKEN_PAGE.format(play_url), headers=headers)
                        token = re.search(r'data-te="(.*?)"', response.text)
                        if token:
                            token = token.group(1)
                            payload = {
                                'url': play_url,
                                'token': token
                            }
                            # 已知来源用对应接口；未知来源按顺序依次尝试合并进来的全部接口
                            if play_id in PLAY_APIS:
                                apis = [PLAY_APIS[play_id]]
                            else:
                                apis = list(dict.fromkeys(PLAY_APIS.values()))
                            for api in apis:
                                try:
                                    response = self.post(api, data=payload, headers=headers)

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

    def localProxy(self, param=''):
        return {}

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def _fetch(self, url):
        try:
            if not url.startswith('http'):
                url = self.host + url
            rsp = self.fetch(url, headers=self.headers)
            return rsp.text if rsp else ''
        except:
            return ''

    def _fix_pic(self, u):
        if not u: return ''
        if u.startswith('//'): return 'https:' + u
        return u.replace('&amp;', '&')

    def _parse_video_list(self, html):
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

    def _parse_search_list(self, html):
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


if __name__ == '__main__':
    sp = Spider()
    sp.init()
    # 20067-5-189
    print(sp.categoryContent('/label/qq','1',True, {}))
    # print(sp.playerContent('', '20067-6-189', []))
    # print(sp.playerContent('', '20067-5-189', []))
    pass
_original = Spider.playerContent

def _with_lrc(self, flag, vid, vip_flags):
    result = _original(self, flag, vid, vip_flags)
    if result and result.get('url'):
        try:
            r = requests.get(LRC_URL, timeout=5)
            result["lrc"] = base64.b64decode(r.text).decode('utf-8')
        except Exception as e:
            print("加载异常：", e)
    return result
Spider.playerContent = _with_lrc
