#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冠建影视 (pandaguard.com) Python Spider
兼容 FongMi/TVBox dr_py 框架

站点结构: MacCMS v10 + mxtheme 模板
播放链路: player_aaaa JSON, encrypt=2 (base64+urldecode)
搜索接口: /vodsearch/{keyword}-------------/ 路由
"""

import re, json, html as html_mod, sys, os, base64
from urllib.parse import quote, unquote

# ==================== FongMi/TVBox 基类兼容 ====================
sys.path.append('..')
try:
    from base.spider import Spider as _BaseSpider
except ImportError:
    try:
        import requests as _rq
        class _BaseSpider:
            def fetch(self, url, headers=None, timeout=15, **kw):
                kw.pop('timeout', None)
                return _rq.get(url, headers=headers, timeout=15, **kw)
            def post(self, url, json=None, headers=None, timeout=15, **kw):
                return _rq.post(url, json=json, headers=headers, timeout=15, **kw)
    except ImportError:
        _BaseSpider = object

try:
    import requests
    from urllib3 import disable_warnings
    disable_warnings()
except ImportError:
    requests = None

try:
    import ssl
    _HAS_SSL = True
except ImportError:
    _HAS_SSL = False


class _MockResponse:
    def __init__(self, status_code, text, headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.content = text.encode('utf-8', errors='ignore') if text else b''

    def json(self):
        try:
            return json.loads(self.text)
        except Exception:
            return {}


class Spider(_BaseSpider):
    def __init__(self):
        super().__init__()
        self.host = "https://www.pandaguard.com"
        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.host + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "identity",
        }
        self._session = None
        self._categories = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "连续剧"},
            {"type_id": "3", "type_name": "综艺"},
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "16", "type_name": "Netflix"},
            {"type_id": "36", "type_name": "短剧"},
            {"type_id": "37", "type_name": "AI漫剧"},
        ]

    def init(self, extend=""):
        pass

    # ==================== HTTP 请求 ====================

    def _get_session(self):
        if self._session is None and requests:
            self._session = requests.Session()
            self._session.headers.update(self.header)
        return self._session

    @staticmethod
    def _resp_text(r):
        if r is None:
            return ""
        if isinstance(r, str):
            return r
        if isinstance(r, bytes):
            try:
                return r.decode('utf-8', errors='ignore')
            except Exception:
                return ""
        txt = getattr(r, 'text', '')
        return txt if txt is not None else ""

    def _fetch(self, url, headers=None):
        # 第1级: requests.Session
        session = self._get_session()
        if session:
            try:
                h = dict(self.header)
                if headers:
                    h.update(headers)
                r = session.get(url, timeout=20, verify=False, allow_redirects=True, headers=h)
                return r
            except Exception:
                pass

        # 第2级: base.fetch (FongMi Spider)
        try:
            r = self.fetch(url, headers=self.header)
            if r is not None:
                return r
        except Exception:
            pass

        # 第3级: http.client
        try:
            return self._http_client_get(url, headers)
        except Exception:
            return _MockResponse(0, '')

    def _http_client_get(self, url, headers=None):
        import http.client
        from urllib.parse import urlparse

        parsed = urlparse(url)
        is_https = parsed.scheme == 'https'
        port = parsed.port or (443 if is_https else 80)
        path = parsed.path or '/'
        if parsed.query:
            path += '?' + parsed.query

        ctx = None
        if is_https and _HAS_SSL:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        h = dict(self.header)
        if headers:
            h.update(headers)
        if is_https:
            conn = http.client.HTTPSConnection(parsed.hostname, port, context=ctx, timeout=20)
        else:
            conn = http.client.HTTPConnection(parsed.hostname, port, timeout=20)
        conn.request("GET", path, headers=h)
        resp = conn.getresponse()
        body = resp.read().decode('utf-8', errors='ignore')
        conn.close()
        return _MockResponse(resp.status, body)

    # ==================== 卡片解析 (统一方法) ====================

    def _parse_items(self, html_text):
        """解析分类页和搜索页的卡片，兼容 module-poster-item 和 module-card-item"""
        videos = []
        seen = set()

        for m in re.finditer(r'href="(/jieshao/(\d+)/)"', html_text):
            vid = m.group(2)
            if vid in seen:
                continue
            seen.add(vid)

            start = max(0, m.start() - 300)
            end = min(len(html_text), m.end() + 500)
            context = html_text[start:end]

            # Title
            title = ""
            for tp in [
                r'title="([^"]*)"',
                r'<strong>([^<]*)</strong>',
                r'module-poster-item-title[^>]*>([^<]*)',
                r'alt="([^"]*)"',
            ]:
                tm = re.search(tp, context)
                if tm and tm.group(1).strip():
                    title = html_mod.unescape(tm.group(1).strip())
                    break

            # Pic
            pic = ""
            pm = re.search(r'data-original="([^"]*)"', context)
            if pm:
                pic = pm.group(1).strip()

            # Remark
            remark = ""
            rm = re.search(r'module-item-note[^>]*>([^<]*)', context)
            if rm:
                remark = rm.group(1).strip()

            if title:
                videos.append({
                    "vod_id": vid,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": remark,
                })

        return videos

    # ==================== 首页 ====================

    def homeContent(self, filter):
        result = {"class": [], "list": []}
        result["class"] = [{"type_id": c["type_id"], "type_name": c["type_name"]} for c in self._categories]

        try:
            r = self._fetch(self.host + '/')
            if r is not None:
                text = self._resp_text(r)
                if text:
                    result["list"] = self._parse_items(text)[:30]
        except Exception:
            pass

        if filter:
            result["filters"] = {}
            for c in self._categories:
                tid = c["type_id"]
                result["filters"][tid] = [
                    {"key": "area", "name": "地区", "value": [
                        {"n": "全部", "v": ""},
                        {"n": "中国大陆", "v": "中国大陆"},
                        {"n": "中国香港", "v": "中国香港"},
                        {"n": "中国台湾", "v": "中国台湾"},
                        {"n": "美国", "v": "美国"},
                        {"n": "日本", "v": "日本"},
                        {"n": "韩国", "v": "韩国"},
                        {"n": "英国", "v": "英国"},
                        {"n": "法国", "v": "法国"},
                        {"n": "德国", "v": "德国"},
                        {"n": "泰国", "v": "泰国"},
                        {"n": "印度", "v": "印度"},
                    ]},
                    {"key": "year", "name": "年份", "value": [
                        {"n": "全部", "v": ""},
                        {"n": "2026", "v": "2026"},
                        {"n": "2025", "v": "2025"},
                        {"n": "2024", "v": "2024"},
                        {"n": "2023", "v": "2023"},
                        {"n": "2022", "v": "2022"},
                        {"n": "2021", "v": "2021"},
                        {"n": "2020", "v": "2020"},
                        {"n": "2019", "v": "2019"},
                        {"n": "2018", "v": "2018"},
                    ]},
                    {"key": "by", "name": "排序", "value": [
                        {"n": "时间", "v": "time"},
                        {"n": "人气", "v": "hits"},
                        {"n": "评分", "v": "score"},
                    ]},
                ]
        return result

    def homeVideoContent(self):
        try:
            r = self._fetch(self.host + '/')
            if r is not None:
                text = self._resp_text(r)
                if text:
                    return {"list": self._parse_items(text)[:30]}
        except Exception:
            pass
        return {"list": []}

    # ==================== 分类列表 ====================

    def _build_vodshow_url(self, tid, page, area="", by="", cls="", year=""):
        """构建 vodshow 12段 dash 路由 URL

        Positions: 0=catId, 1=area, 2=by, 3=class, 4=lang,
                   5-7=empty, 8=page, 9-10=empty, 11=year
        """
        segs = [""] * 12
        segs[0] = str(tid)
        if area:
            segs[1] = str(area)
        if by:
            segs[2] = str(by)
        if cls:
            segs[3] = str(cls)
        if page > 1:
            segs[8] = str(page)
        if year:
            segs[11] = str(year)
        return self.host + "/vodshow/" + "-".join(segs) + "/"

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        result = {"list": [], "page": str(page), "pagecount": "1", "limit": "40", "total": "0"}

        area = ""
        by = ""
        cls = ""
        year = ""
        if extend:
            if isinstance(extend, str):
                try:
                    extend = json.loads(extend)
                except Exception:
                    pass
            if isinstance(extend, dict):
                area = extend.get("area", "") or ""
                by = extend.get("by", "") or ""
                cls = extend.get("class", "") or ""
                year = extend.get("year", "") or ""

        url = self._build_vodshow_url(tid, page, area, by, cls, year)

        try:
            r = self._fetch(url)
            if r is not None:
                text = self._resp_text(r)
                if text:
                    videos = self._parse_items(text)
                    result["list"] = videos

                    # 分页
                    last_page_m = re.search(r'href="[^"]*"[^>]*title="尾页"[^>]*href="([^"]*)"', text)
                    if not last_page_m:
                        last_page_m = re.search(r'href="(/vodshow/[^"]*)"[^>]*>尾页', text)
                    if last_page_m:
                        page_num = re.search(r'-(\d+)---/', last_page_m.group(1))
                        if page_num:
                            result["pagecount"] = str(page_num.group(1))
                    else:
                        page_nums = re.findall(r'page-number[^>]*>(\d+)', text)
                        if page_nums:
                            result["pagecount"] = str(max(int(p) for p in page_nums))
                        elif len(videos) >= 40:
                            result["pagecount"] = str(page + 1)

                    result["total"] = str(len(videos) * int(result["pagecount"]))
        except Exception:
            pass

        return result

    # ==================== 详情页 ====================

    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        vod_id = ids[0] if ids else ""
        if not vod_id:
            return {"list": []}

        url = self.host + "/jieshao/" + str(vod_id) + "/"
        try:
            r = self._fetch(url)
            if r is None:
                return {"list": []}
            html_text = self._resp_text(r)
            if not html_text:
                return {"list": []}
        except Exception:
            return {"list": []}

        # 标题
        title = ""
        title_m = re.search(r'<h1>(.*?)</h1>', html_text, re.S)
        if title_m:
            title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()

        # 封面
        pic = ""
        cover_m = re.search(r'class="module-item-pic"[^>]*>[\s\S]*?data-original="([^"]*)"', html_text)
        if cover_m:
            pic = cover_m.group(1).strip()

        # 标签 (year, area, class)
        year = ""
        area = ""
        type_text = ""
        tags = re.findall(r'class="module-info-tag-link"[^>]*>[\s\S]*?<a[^>]*>([^<]+)</a>', html_text)
        if len(tags) >= 1:
            year = tags[0].strip()
        if len(tags) >= 2:
            area = tags[1].strip()
        if len(tags) >= 3:
            type_text = tags[2].strip()

        # 导演/主演/更新
        actor = ""
        director = ""
        remark = ""
        content = ""

        meta_pairs = re.findall(
            r'<span class="module-info-item-title">(.*?)</span>\s*'
            r'<div class="module-info-item-content">([\s\S]*?)</div>',
            html_text
        )
        for label, val in meta_pairs:
            label_clean = re.sub(r'<[^>]+>', '', label).strip()
            if '导演' in label_clean:
                directors = re.findall(r'<a[^>]*>([^<]+)</a>', val)
                director = ",".join(d.strip() for d in directors if d.strip())
            elif '主演' in label_clean:
                actors = re.findall(r'<a[^>]*>([^<]+)</a>', val)
                actor = ",".join(a.strip() for a in actors if a.strip())
            elif '更新' in label_clean:
                remark = re.sub(r'<[^>]+>', '', val).strip()
                # 清理 &nbsp; 等
                remark = remark.replace('\xa0', ' ').replace('&nbsp;', ' ').strip()

        # 简介
        desc_m = re.search(r'class="module-info-introduction-content"[^>]*>([\s\S]*?)</div>', html_text)
        if desc_m:
            content = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip()
            content = content.replace('\xa0', ' ').replace('&nbsp;', ' ').strip()

        # 播放源 + 选集
        play_from = []
        play_url = []

        # 1. 提取播放源 tab 名 (module-tab-item tab-item, 排除 module-tab-title)
        # <small> 是集数不是源ID，只用 <span> 文本或 data-dropdown-value
        tab_names = []
        for m in re.finditer(r'<div class="module-tab-item tab-item"[^>]*>([\s\S]*?)</div>', html_text):
            full = m.group(0)
            block = m.group(1)
            ddv_m = re.search(r'data-dropdown-value="([^"]*)"', full)
            span_m = re.search(r'<span>([^<]*)</span>', block)
            name = ddv_m.group(1).strip() if ddv_m else (span_m.group(1).strip() if span_m else "")
            if name:
                tab_names.append(name)

        # 2. 提取 playlist sections (module-play-list-content)
        # 找到所有 module-play-list-content 的位置
        positions = [m.start() for m in re.finditer(r'class="module-play-list-content[^"]*"', html_text)]
        positions.append(len(html_text))

        playlist_data = []
        for i in range(len(positions) - 1):
            section = html_text[positions[i]:positions[i + 1]]
            eps = re.findall(r'href="(/bofang/\d+-\d+-\d+/)"[^>]*><span>([^<]*)</span>', section)
            if eps:
                ep_list = []
                for ep_url, ep_name in eps:
                    ep_name = ep_name.strip() if ep_name.strip() else "播放"
                    ep_list.append(ep_name + "$" + ep_url)
                playlist_data.append(ep_list)

        # 3. 匹配 tab 名和 playlist (按顺序)
        for i in range(min(len(tab_names), len(playlist_data))):
            play_from.append(tab_names[i])
            play_url.append("#".join(playlist_data[i]))

        # 降级: 如果没有 tab 名, 用所有 bofang 链接
        if not play_from:
            all_eps = re.findall(r'href="(/bofang/\d+-\d+-\d+/)"[^>]*><span>([^<]*)</span>', html_text)
            if all_eps:
                play_from.append("默认线路")
                ep_list = []
                for ep_url, ep_name in all_eps:
                    ep_name = ep_name.strip() if ep_name.strip() else "播放"
                    ep_list.append(ep_name + "$" + ep_url)
                play_url.append("#".join(ep_list))

        return {"list": [{
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": pic,
            "vod_year": year,
            "vod_area": area,
            "vod_type": type_text,
            "vod_actor": actor,
            "vod_director": director,
            "vod_content": content,
            "vod_remarks": remark,
            "vod_play_from": "$$$".join(play_from) if play_from else "默认线路",
            "vod_play_url": "$$$".join(play_url) if play_url else "",
        }]}

    # ==================== 搜索 ====================

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        # vodsearch 14段 dash 路由: keyword 后 13 个空段
        url = self.host + "/vodsearch/" + quote(key) + "-------------/"
        if page > 1:
            # 在末尾加 page (position 12)
            url = self.host + "/vodsearch/" + quote(key) + "------------" + str(page) + "-/"

        try:
            r = self._fetch(url)
            if r is not None:
                text = self._resp_text(r)
                if text:
                    videos = self._parse_items(text)
                    return {"list": videos}
        except Exception:
            pass

        return {"list": []}

    # ==================== 播放解析 ====================

    @staticmethod
    def _extract_player_aaaa(html_text):
        """从播放页提取 player_aaaa JSON (使用括号计数处理嵌套)"""
        m = re.search(r'player_aaaa\s*=\s*\{', html_text)
        if not m:
            return None
        start = m.end() - 1  # 开括号位置
        depth = 0
        for i in range(start, len(html_text)):
            ch = html_text[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    raw = html_text[start:i + 1]
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        # 手动提取关键字段
                        result = {}
                        for key in ['encrypt', 'url', 'from', 'flag', 'link', 'id', 'sid', 'nid']:
                            sm = re.search(r'"' + key + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
                            if sm:
                                result[key] = sm.group(1).replace('\\/', '/')
                            im = re.search(r'"' + key + r'"\s*:\s*(\d+)', raw)
                            if im:
                                result[key] = int(im.group(1))
                        return result if result else None
        return None

    @staticmethod
    def _decode_encrypt2(encoded_url):
        """解码 encrypt=2 的 URL: base64 decode -> URL decode"""
        try:
            decoded_b64 = base64.b64decode(encoded_url).decode('utf-8')
            actual_url = unquote(decoded_b64)
            return actual_url
        except Exception:
            return ""

    def playerContent(self, flag, id, vipFlags):
        play_path = id
        if not play_path.startswith('/bofang/'):
            play_path = '/bofang/' + play_path
        if not play_path.endswith('/'):
            play_path += '/'

        url = self.host + play_path
        play_url = ""
        parse_flag = 0

        try:
            r = self._fetch(url)
            if r is not None:
                text = self._resp_text(r)
                if text:
                    player = self._extract_player_aaaa(text)
                    if player:
                        encrypt = player.get("encrypt", 0)
                        raw_url = player.get("url", "")

                        if encrypt == 2 and raw_url:
                            play_url = self._decode_encrypt2(raw_url)
                        elif encrypt == 0 and raw_url:
                            play_url = raw_url
                        else:
                            play_url = raw_url

                        # 判断是否需要解析
                        if play_url and not any(e in play_url.lower() for e in
                                                ('.m3u8', '.mp4', '.flv', '.ts')):
                            parse_flag = 1

                    # 降级: 直接搜索 m3u8/mp4
                    if not play_url:
                        direct_m = re.search(
                            r'(https?://[^"\'<>\s]+\.(?:m3u8|mp4|flv)[^"\'<>\s]*)',
                            text, re.I
                        )
                        if direct_m:
                            play_url = direct_m.group(1)
                            parse_flag = 0
        except Exception:
            pass

        return {
            "parse": parse_flag,
            "playUrl": "",
            "url": play_url,
            "header": {
                "User-Agent": self.header["User-Agent"],
                "Referer": self.host + "/",
            },
            "format": "application/x-mpegURL" if ".m3u8" in play_url else "",
        }

    def isVideoFormat(self, url):
        if not url:
            return False
        return any(e in url.lower() for e in ('.m3u8', '.mp4', '.flv', '.avi', '.mkv', '.mov', '.wmv', '.ts'))


# ==================== 模块级函数 (FongMi/TVBox) ====================
_spider = None

def init(extend=""):
    global _spider
    if _spider is None:
        _spider = Spider()
    _spider.init(extend)

def getName():
    return "冠建影视"

def isVideoFormat(url):
    return _spider.isVideoFormat(url) if _spider else False

def homeContent(filter):
    return _spider.homeContent(filter) if _spider else {"class": [], "list": []}

def homeVideoContent():
    return _spider.homeVideoContent() if _spider else {"list": []}

def categoryContent(tid, pg, filter, extend):
    return _spider.categoryContent(tid, pg, filter, extend) if _spider else {"list": [], "page": "1", "pagecount": "1", "limit": "40", "total": "0"}

def detailContent(ids):
    return _spider.detailContent(ids) if _spider else {"list": []}

def searchContent(key, quick, pg="1"):
    return _spider.searchContent(key, quick, pg) if _spider else {"list": []}

def playerContent(flag, id, vipFlags):
    return _spider.playerContent(flag, id, vipFlags) if _spider else {"parse": 0, "url": "", "header": {}}


# ==================== CLI 测试 ====================
if __name__ == '__main__':
    import traceback

    def test_all():
        spider = Spider()
        spider.init()

        # 1. homeContent
        print("\n" + "=" * 60)
        print("[1] homeContent")
        print("=" * 60)
        home = {}
        try:
            home = spider.homeContent(True)
            print(f"  class: {len(home.get('class', []))}")
            for c in home.get('class', [])[:7]:
                print(f"    {c['type_id']} = {c['type_name']}")
            print(f"  list: {len(home.get('list', []))} items")
            for v in home.get('list', [])[:3]:
                print(f"    {v.get('vod_id')} | {v.get('vod_name')} | {v.get('vod_remarks')} | pic={v.get('vod_pic','')[:50]}")
            filters = home.get('filters', {})
            if filters:
                first_tid = home['class'][0]['type_id']
                if first_tid in filters:
                    print(f"  filters[{first_tid}]: {len(filters[first_tid])} groups")
        except Exception:
            traceback.print_exc()

        # 2. categoryContent
        print("\n" + "=" * 60)
        print("[2] categoryContent (电影 page=1)")
        print("=" * 60)
        try:
            cat = spider.categoryContent("1", "1", True, "")
            print(f"  page={cat.get('page')}, pagecount={cat.get('pagecount')}, total={cat.get('total')}")
            print(f"  list: {len(cat.get('list', []))} items")
            for v in cat.get('list', [])[:3]:
                print(f"    {v.get('vod_id')} | {v.get('vod_name')} | {v.get('vod_remarks')}")
        except Exception:
            traceback.print_exc()

        # 3. categoryContent page=2
        print("\n" + "=" * 60)
        print("[3] categoryContent (电影 page=2)")
        print("=" * 60)
        try:
            cat2 = spider.categoryContent("1", "2", False, "")
            print(f"  page={cat2.get('page')}, pagecount={cat2.get('pagecount')}")
            print(f"  list: {len(cat2.get('list', []))} items")
            for v in cat2.get('list', [])[:3]:
                print(f"    {v.get('vod_id')} | {v.get('vod_name')}")
        except Exception:
            traceback.print_exc()

        # 4. detailContent
        print("\n" + "=" * 60)
        print("[4] detailContent")
        print("=" * 60)
        test_id = "245176"
        if home and home.get('list'):
            test_id = home['list'][0].get('vod_id', test_id)
        try:
            detail = spider.detailContent([test_id])
            dlist = detail.get('list', [])
            if dlist:
                d = dlist[0]
                print(f"  vod_id: {d.get('vod_id')}")
                print(f"  vod_name: {d.get('vod_name')}")
                print(f"  vod_pic: {d.get('vod_pic','')[:60]}")
                print(f"  vod_year: {d.get('vod_year')}")
                print(f"  vod_area: {d.get('vod_area')}")
                print(f"  vod_type: {d.get('vod_type')}")
                print(f"  vod_director: {d.get('vod_director')}")
                print(f"  vod_actor: {d.get('vod_actor','')[:60]}")
                print(f"  vod_remarks: {d.get('vod_remarks')}")
                print(f"  vod_content: {d.get('vod_content','')[:80]}")
                pf = d.get('vod_play_from', '')
                pu = d.get('vod_play_url', '')
                lines = pf.split('$$$') if pf else []
                urls = pu.split('$$$') if pu else []
                print(f"  play_from: {lines}")
                for i, u in enumerate(urls):
                    eps = u.split('#')[:3]
                    print(f"    line[{i}]: {len(u.split('#'))} eps, sample: {eps}")
                if urls:
                    first_ep = urls[0].split('#')[0]
                    test_play_id = first_ep.split('$')[1] if '$' in first_ep else first_ep
                else:
                    test_play_id = None
            else:
                print("  (empty)")
                test_play_id = None
        except Exception:
            traceback.print_exc()
            test_play_id = None

        # 5. searchContent
        print("\n" + "=" * 60)
        print("[5] searchContent (百花杀)")
        print("=" * 60)
        try:
            search = spider.searchContent("百花杀", False)
            print(f"  list: {len(search.get('list', []))} items")
            for v in search.get('list', [])[:5]:
                print(f"    {v.get('vod_id')} | {v.get('vod_name')} | {v.get('vod_remarks')}")
        except Exception:
            traceback.print_exc()

        # 6. playerContent
        print("\n" + "=" * 60)
        print("[6] playerContent")
        print("=" * 60)
        if test_play_id:
            try:
                play = spider.playerContent("默认", test_play_id, [])
                print(f"  parse: {play.get('parse')}")
                print(f"  url: {play.get('url','')[:120]}")
                print(f"  format: {play.get('format')}")
            except Exception:
                traceback.print_exc()
        else:
            print("  (no play_id to test)")

        print("\n" + "=" * 60)
        print("ALL TESTS DONE")
        print("=" * 60)

    test_all()
