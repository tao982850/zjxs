# -*- coding: utf-8 -*-
"""
TVB云播 - viptv01.com（同服主域 tvyun05.com / hktvyb.cc）
MacCMS 10 + myui 模板，全站 huadong 滑动验证（与歪比巴卜同款算法）。

关键结论（已实测验证）：
1. 全站被 huadong 滑动验证保护：首次请求返回 403 挑战页并种 server_name_session，
   挑战页加载 /huadong_*.js。绕过算法：JS 提取 key/value -> stringtoHex(value) -> md5
   -> 调用 /a20be899_..._yanzheng_huadong.php 拿到会话 cookie（hash 名），此后放行。
2. 分类页 /vod/type/id/{tid}.html，分页 /vod/type/id/{tid}/page/{page}.html
   卡片：a.myui-vodlist__thumb[data-original] + span.tag(备注) + span.pic-title-bottom(片名)
3. 详情页 /vod/detail/id/{id}.html：线路 tab + <ul class="myui-vodlist__playlist">
   播放链接 /vod/play/id/{id}/sid/{sid}/nid/{nid}.html
4. 播放页 /vod/play/id/{id}/sid/{sid}/nid/{nid}.html：
   var player_data={"flag":"play","encrypt":0,"url":"https://pans4.s1-tximg.top/xxx.mp4",...}
   encrypt=0 时 url 即真实直链（腾讯云 CDN mp4/m3u8），parse=0 直接播放。
   空 url 时回退 iframe 解析地址或 WebView。
5. 搜索 /vod/search.html?wd=关键词（结果同为卡片结构）。
"""
import re
import json
import hashlib
import base64
import time
import urllib.parse
import requests
from urllib.parse import quote

try:
    from base.spider import Spider
except ImportError:
    # 本地 stub 测试时的兜底基类
    class Spider:
        def __init__(self):
            pass


class Spider(Spider):
    # ==================== 基础配置 ====================
    name = "影视云播"
    base_url = "http://www.viptv01.com"
    site_url = "http://www.viptv01.com"

    # 聚合搜索配置
    searchable = 1
    quickSearch = 1
    filterable = 1
    changeable = 1

    # 分类（MacCMS type_id）
    class_name = ["电影", "电视剧", "综艺", "动漫", "短剧", "国产剧", "港剧", "日韩剧", "欧美剧", "香港综艺"]
    class_url = ["1", "2", "3", "4", "5", "13", "14", "15", "16", "22"]
    CATEGORY_NAMES = {
        "1": "电影", "2": "电视剧", "3": "综艺", "4": "动漫", "5": "短剧",
        "13": "国产剧", "14": "港剧", "15": "日韩剧", "16": "欧美剧", "22": "香港综艺",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "http://www.viptv01.com/",
        "Connection": "keep-alive",
    }

    play_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "http://www.viptv01.com/",
        "Accept": "*/*",
    }

    def __init__(self):
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        self._cookies = ""
        self._play_cache = {}
        self._cache_ttl = 1800
        self._last_req_time = 0
        self._min_req_interval = 1.0
        self._block_until = 0
        self._verify_passed = False
        self._last_vod_id = None

        self._re_detail_title = re.compile(r'<h1>([^<]*)</h1>')
        # 播放链接 /vod/play/id/xxx/sid/x/nid/y.html
        self._re_vplay_link = re.compile(
            r'href="/vod/play/id/(\d+)/sid/(\d+)/nid/(\d+)\.html"[^>]*>([^<]*)</a>', re.DOTALL)
        self._re_name_garbage = re.compile(
            r'[\s\-_]*(?:HD|TC|TS|抢先版|枪版|DVD|BD|1080P|720P|4K|2K|高清|超清|蓝光|国语|粤语|中字|中英双字|完整版|全集|未删减版|(?:第[0-9一二三四五六七八九十]+[集季期]))\s*$',
            re.I)

    # ==================== 工具方法 ====================
    def _log(self, msg):
        print("[%s] %s" % (self.name, msg))

    def _md5(self, s):
        return hashlib.md5(s.encode('utf-8')).hexdigest()

    def _clean_vod_name(self, name):
        if not name:
            return name
        prev = name
        while True:
            cleaned = self._re_name_garbage.sub('', prev).strip()
            if cleaned == prev:
                break
            prev = cleaned
        return prev

    def _clean_html(self, text):
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    # ==================== 请求基础 ====================
    def fetch(self, url, headers=None, timeout=30):
        self._apply_req_delay()
        return self._session.get(url, headers=headers or {}, timeout=timeout)

    def post(self, url, data=None, headers=None, timeout=30):
        self._apply_req_delay()
        return self._session.post(url, data=data, headers=headers or {}, timeout=timeout)

    def _apply_req_delay(self):
        now = time.time()
        if now < self._block_until:
            wait = self._block_until - now
            self._log("频率限制冷却中，等待 %.1fs" % wait)
            time.sleep(wait)
        elapsed = now - self._last_req_time
        if 0 < elapsed < self._min_req_interval:
            time.sleep(self._min_req_interval - elapsed)
        self._last_req_time = time.time()

    # ==================== Cookie 维护 ====================
    def _extract_cookies(self, resp):
        cookie_list = []
        try:
            if hasattr(resp, 'cookies') and resp.cookies:
                for c in resp.cookies:
                    cookie_list.append("%s=%s" % (c.name, c.value))
        except Exception:
            pass
        try:
            if hasattr(resp.headers, 'get_all'):
                for c in resp.headers.get_all("Set-Cookie"):
                    cookie_list.append(c.split(";")[0])
            elif "Set-Cookie" in resp.headers:
                raw = resp.headers["Set-Cookie"]
                if isinstance(raw, list):
                    for c in raw:
                        cookie_list.append(c.split(";")[0])
                else:
                    cookie_list.append(raw.split(";")[0])
        except Exception:
            pass
        if cookie_list:
            existing = {}
            for x in self._cookies.split('; '):
                if '=' in x:
                    k, v = x.split('=', 1)
                    existing[k.strip()] = v
            for c in cookie_list:
                if '=' in c:
                    k, v = c.split('=', 1)
                    existing[k.strip()] = v
            self._cookies = "; ".join("%s=%s" % (k, v) for k, v in existing.items())

    def _fetch_cookies(self):
        try:
            h = {"User-Agent": self.headers["User-Agent"], "Accept": "text/html",
                 "Referer": self.base_url + "/"}
            resp = self.fetch(self.base_url, headers=h)
            self._extract_cookies(resp)
            if self._cookies:
                self._log("初始Cookie: %s" % self._cookies[:60])
        except Exception as e:
            self._log("初始Cookie获取失败: %s" % e)
            self._cookies = ""

    # ==================== 页面类型检测 ====================
    def _is_slide_verify_page(self, html):
        if not html:
            return False
        return '滑动验证' in html or 'huadong_' in html or 'SliderTools' in html

    def _is_challenge_page(self, html):
        if not html:
            return True
        if len(html) < 600:
            return bool(re.search(r'window\.location\.href\s*=\s*"/?(?:vod|play|detail|index)', html, re.I))
        return False

    def _is_blocked_page(self, html):
        if not html:
            return True
        if self._is_slide_verify_page(html):
            return False
        markers = ('You are being rate limited', 'Error 1015', 'cf-error-details',
                   'Access denied |', 'Banned', '您的访问过于频繁')
        return any(m in html for m in markers)

    # ==================== huadong 滑动验证绕过 ====================
    def _solve_slide_verify(self, html, ref_url):
        """提取 /huadong_*.js 的 key/value，md5(stringtoHex(value)) 后调验证接口"""
        js_match = re.search(r'src="(/huadong_[^"]+)"', html)
        if not js_match:
            self._log("未找到滑动验证JS")
            return False
        js_path = js_match.group(1)
        js_url = self.base_url + js_path if js_path.startswith("/") else js_path
        try:
            h = {"User-Agent": self.headers["User-Agent"], "Referer": ref_url, "Accept": "*/*"}
            r = self.fetch(js_url, headers=h, timeout=10)
            js_text = r.text
            key_match = re.search(r'key="([a-f0-9]+)"', js_text)
            val_match = re.search(r'value="([a-f0-9]+)"', js_text)
            if not key_match or not val_match:
                key_match = re.search(r"key\s*=\s*['\"]([a-f0-9]+)['\"]", js_text)
                val_match = re.search(r"value\s*=\s*['\"]([a-f0-9]+)['\"]", js_text)
            if not key_match or not val_match:
                self._log("未从JS提取到key/value")
                return False
            key = key_match.group(1)
            value = val_match.group(1)

            def _stringto_hex(s):
                return "".join(str(ord(c) + 1) for c in s)

            md5_val = self._md5(_stringto_hex(value))
            # type 参数优先从 JS 内联提取（服务端可能变更），提取失败用默认值
            type_match = re.search(r'type=([a-f0-9]+)', js_text)
            type_ = type_match.group(1) if type_match else "ad82060c2e67cc7e2cc47552a4fc1242"
            verify_url = (
                self.base_url + "/a20be899_96a6_40b2_88ba_32f1f75f1552_yanzheng_huadong.php"
                + "?type=" + type_ + "&key=" + key + "&value=" + md5_val
            )
            self._log("滑动验证接口: type=%s key=%s..." % (type_[:12], key[:12]))
            vh = {"User-Agent": self.headers["User-Agent"], "Accept": "*/*",
                  "Referer": ref_url, "X-Requested-With": "XMLHttpRequest"}
            resp = self.fetch(verify_url, headers=vh, timeout=10)
            self._extract_cookies(resp)
            self._log("滑动验证状态: %s body=%s" % (resp.status_code, resp.text[:60]))
            if resp.status_code == 200:
                time.sleep(2.0)
                self._verify_passed = True
                return True
            return False
        except Exception as e:
            self._log("滑动验证绕过异常: %s" % e)
            return False

    def _get(self, url, max_retry=3, timeout=15):
        h = self.headers.copy()
        try:
            for attempt in range(max_retry):
                resp = self.fetch(url, headers=h, timeout=timeout)
                self._extract_cookies(resp)
                html = resp.text
                if self._is_blocked_page(html):
                    wait = 2 + attempt * 2
                    self._block_until = time.time() + wait
                    self._log("频率限制，%ds冷却: %s" % (wait, url))
                    if attempt < max_retry - 1:
                        time.sleep(wait)
                        continue
                    return ""
                if self._is_slide_verify_page(html):
                    self._log("触发滑动验证，自动绕过: %s" % url)
                    if self._solve_slide_verify(html, url):
                        # 验证成功后重置计数，确保至少再有一次完整请求机会
                        attempt = -1
                        continue
                    else:
                        self._log("滑动验证失败")
                        if attempt < max_retry - 1:
                            time.sleep(2 + attempt)
                            continue
                    return ""
                if self._is_challenge_page(html) and attempt < max_retry - 1:
                    self._log("cookie预热页，第%d次重试: %s" % (attempt + 1, url))
                    continue
                return html
            return ""
        except Exception as e:
            self._log("请求失败: %s, %s" % (url, e))
            if not self._cookies:
                self._fetch_cookies()
                try:
                    return self.fetch(url, headers=h, timeout=timeout).text
                except Exception as e2:
                    self._log("重试失败: %s" % e2)
            return ""

    # ==================== 列表解析 ====================
    def _parse_video_list(self, html):
        videos = []
        if not html:
            return videos
        # 主 pattern: myui-vodlist__thumb 整个 a 标签块
        for m in re.finditer(
                r'<a[^>]*class="[^"]*myui-vodlist__thumb[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL):
            tag = html[m.start():m.end()]
            idm = re.search(r'href="/vod/detail/id/(\d+)\.html"', tag)
            if not idm:
                continue
            vod_id = idm.group(1)
            tm = re.search(r'title="([^"]*)"', tag)
            pm = re.search(r'data-original="([^"]+)"', tag)
            nm = re.search(r'class="[^"]*pic-title-bottom[^"]*"[^>]*>([^<]*)<', tag)
            title = (nm.group(1).strip() if nm else "") or (tm.group(1).strip() if tm else "")
            pic = pm.group(1) if pm else ""
            if pic.startswith("//"):
                pic = "https:" + pic
            videos.append({
                "vod_id": vod_id,
                "vod_name": self._clean_vod_name(title),
                "vod_pic": pic,
                "vod_remarks": "",
            })
        # 备注（tag span）按出现顺序补
        if videos:
            idx = 0
            for m in re.finditer(r'<span[^>]*class="tag"[^>]*>([^<]*)</span>', html):
                if idx < len(videos):
                    videos[idx]["vod_remarks"] = m.group(1).strip()
                    idx += 1
            return videos
        # 兜底：任意 a 详情链接
        for m in re.finditer(
                r'<a[^>]*href="/vod/detail/id/(\d+)\.html"[^>]*title="([^"]*)"[^>]*data-original="([^"]+)"[^>]*>',
                html):
            pic = m.group(3)
            if pic.startswith("//"):
                pic = "https:" + pic
            videos.append({
                "vod_id": m.group(1),
                "vod_name": self._clean_vod_name(m.group(2).strip()),
                "vod_pic": pic,
                "vod_remarks": "",
            })
        return videos

    # ==================== 播放源解析（详情页） ====================
    def _parse_play_sources(self, html, vod_id):
        """
        线路与集数：
        - 线路名：.myui-panel__tab 内 a 文本（排除排序/更多等）
        - 集数：/vod/play/id/{id}/sid/{sid}/nid/{nid}.html 按 (id,sid) 分组
        """
        _BAD = ("排序", "更多", "切换", "展开", "收起", "选择播放源", "同类型", "同主演",
                "同导演", "同年份", "同演员", "刷新", "换一换", "播放记录", "清空")
        source_names = []
        for block in re.findall(r'<div[^>]*class="[^"]*myui-panel__tab[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL):
            for m in re.finditer(r'<a[^>]*>(.*?)</a>', block, re.DOTALL):
                inner = re.sub(r'<[^>]+>', '', m.group(1))
                name = inner.strip()
                if name and name not in source_names and name not in _BAD:
                    source_names.append(name)
        # 备用：myui-panel__head 里的 h3+tab
        if not source_names:
            for block in re.findall(r'<div[^>]*class="[^"]*myui-panel__head[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL):
                for m in re.finditer(r'<a[^>]*>(.*?)</a>', block, re.DOTALL):
                    inner = re.sub(r'<[^>]+>', '', m.group(1))
                    name = inner.strip()
                    if name and name not in source_names and name not in _BAD:
                        source_names.append(name)

        # 集数按 (sid) 分组
        groups = {}
        for m in self._re_vplay_link.finditer(html):
            vid, sid, nid, name = m.groups()
            if str(vid) != str(vod_id):
                continue
            groups.setdefault(sid, []).append((int(nid), name.strip(), sid))

        if not groups:
            return []

        sorted_sids = sorted(groups.keys(), key=lambda s: (min(n[0] for n in groups[s]), s))
        # 线路名对齐：若 tab 数量不足按 "线路{n}"
        for i, sid in enumerate(sorted_sids):
            pass

        sources = []
        for i, sid in enumerate(sorted_sids):
            eps = sorted(groups[sid], key=lambda x: x[0])
            name = source_names[i] if i < len(source_names) else "线路%s" % sid
            sources.append({
                "source_name": name,
                "episodes": [
                    {"name": n, "link": "%s-%s-%s" % (vod_id, sid, nid)}
                    for nid, n, _sid in eps
                ],
            })

        # 4K/蓝光线路置顶
        def _rank(i):
            nm = sources[i]["source_name"]
            is_4k = any(k in nm for k in ("4K", "4k", "2160", "2160P", "2160p"))
            is_blu = "蓝光" in nm
            cnt = len(sources[i]["episodes"])
            no_eps = 1 if cnt == 0 else 0
            order = 0 if is_4k else (1 if is_blu else 2)
            return (no_eps, order, i)
        return [sources[i] for i in sorted(range(len(sources)), key=_rank)]

    # ==================== 播放地址解析 ====================
    def _extract_player_data(self, html):
        if not html:
            return None
        m = re.search(r'var\s+player_data\s*=\s*', html)
        if not m:
            return None
        start = m.end()
        while start < len(html) and html[start] != '{':
            start += 1
        if start >= len(html):
            return None
        depth = 1
        i = start + 1
        in_string = False
        escape = False
        while i < len(html) and depth > 0:
            c = html[i]
            if in_string:
                if escape:
                    escape = False
                elif c == '\\':
                    escape = True
                elif c == '"':
                    in_string = False
            else:
                if c == '"':
                    in_string = True
                elif c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
            i += 1
        if depth == 0:
            try:
                return json.loads(html[start:i])
            except Exception:
                pass
        return None

    def _get_play_url(self, vod_id, sid, nid):
        play_page = "%s/vod/play/id/%s/sid/%s/nid/%s.html" % (self.base_url, vod_id, sid, nid)
        cache_key = "%s-%s-%s" % (vod_id, sid, nid)
        now = time.time()
        if cache_key in self._play_cache:
            url, ts = self._play_cache[cache_key]
            if now - ts < self._cache_ttl:
                return url
        try:
            html = self._get(play_page, max_retry=2, timeout=10)
            if not html or self._is_slide_verify_page(html):
                return play_page
            pd = self._extract_player_data(html)
            if not pd:
                return play_page
            enc_url = (pd.get("url") or "").strip()
            encrypt = str(pd.get("encrypt", "0"))
            self._log("player encrypt=%s url=%s..." % (encrypt, enc_url[:50]))
            if encrypt == "1":
                enc_url = urllib.parse.unquote(enc_url)
            elif encrypt == "2":
                try:
                    enc_url = urllib.parse.unquote(base64.b64decode(enc_url).decode('utf-8'))
                except Exception:
                    pass
            if not enc_url:
                # 空 url 时尝试页面 iframe 里的解析地址（WebView 可播）
                iframe = re.search(r'<iframe[^>]*src="([^"]+)"', html)
                if iframe and 'index.php?url=' in iframe.group(1):
                    enc_url = iframe.group(1)
                else:
                    return play_page
            self._play_cache[cache_key] = (enc_url, now)
            return enc_url
        except Exception as e:
            self._log("获取播放地址异常: %s" % e)
            return play_page

    # ==================== TVBox 核心方法 ====================
    def init(self, extend=''):
        self._fetch_cookies()
        self._log("初始化完成")

    def homeContent(self, filter=False):
        result = {
            "class": [
                {"type_id": tid, "type_name": name}
                for tid, name in self.CATEGORY_NAMES.items()
            ]
        }
        if filter:
            result["filters"] = {}
            result["filter"] = {}
        return result

    def homeVideoContent(self):
        try:
            html = self._get(self.base_url)
            if not html:
                return {"list": []}
            videos = self._parse_video_list(html)
            return {"list": videos[:24]}
        except Exception as e:
            self._log("homeVideoContent异常: %s" % e)
            return {"list": []}

    def categoryContent(self, tid, pg, filter=False, content=None):
        try:
            pg = max(1, int(pg or 1))
            if str(tid) not in self.CATEGORY_NAMES:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 24, "total": 0}
            url = "%s/vod/type/id/%s.html" % (self.base_url, tid)
            if pg > 1:
                url = "%s/vod/type/id/%s/page/%d.html" % (self.base_url, tid, pg)
            self._log("分类请求: " + url)
            html = self._get(url)
            if not html:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 24, "total": 0}
            videos = self._parse_video_list(html)
            # 页数（分开匹配"尾页"和数字页码，避免组数错位）
            pagecount = 1
            m_tail = re.search(
                r'href="/vod/type/id/%s/page/(\d+)\.html"[^>]*>尾页' % tid, html)
            if m_tail:
                pagecount = int(m_tail.group(1))
            else:
                m_num = re.search(
                    r'href="/vod/type/id/%s/page/(\d+)\.html"[^>]*>\d+</a>' % tid, html)
                if m_num:
                    pagecount = int(m_num.group(1))
            # 未来上映降级
            def _sort(v):
                note = v.get('vod_remarks', '')
                if '上映' in note and not any(m in note for m in ('更新至', '已完结', 'HD', '1080P', '正片', '全', '集')):
                    return 1
                return 0
            videos = sorted(videos, key=_sort)
            return {
                "list": videos,
                "page": pg,
                "pagecount": pagecount,
                "limit": 24,
                "total": pagecount * 24,
            }
        except Exception as e:
            self._log("categoryContent异常: %s" % e)
            return {"list": [], "page": pg, "pagecount": 1, "limit": 24, "total": 0}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            try:
                pg = max(1, int(pg or 1))
            except (TypeError, ValueError):
                pg = 1
            keyword = str(key or "").strip()
            if not keyword:
                return {"page": pg, "pagecount": 1, "limit": 0, "total": 0, "list": []}
            url = "%s/vod/search.html?wd=%s" % (self.base_url, quote(keyword))
            self._log("搜索请求: %s quick=%s" % (url, quick))
            html = self._get(url)
            if not html:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 24, "total": 0}
            videos = self._parse_video_list(html)

            if not quick:
                key_lower = keyword.lower()
                def _score(v):
                    name = v.get('vod_name', '').lower()
                    if name == key_lower:
                        return 0
                    if name.startswith(key_lower):
                        return 1
                    if key_lower in name:
                        return 2
                    return 3
                videos = sorted(videos, key=_score)
            return {
                "list": videos,
                "page": pg,
                "pagecount": 9999,
                "limit": 24,
                "total": 999999,
            }
        except Exception as e:
            self._log("searchContent异常: %s" % e)
            return {"list": [], "page": pg, "pagecount": 1, "limit": 24, "total": 0}

    def detailContent(self, ids):
        try:
            vod_id = ids[0] if isinstance(ids, list) else str(ids)
            url = "%s/vod/detail/id/%s.html" % (self.base_url, vod_id)
            self._log("详情请求: " + url)
            html = self._get(url)
            if not html:
                return {"list": []}

            title = self._re_detail_title.search(html)
            vod_name = self._clean_vod_name(title.group(1).strip()) if title else "未知"

            vod_pic = ""
            for pattern in [
                r'<img[^>]*data-original="([^"]+)"[^>]*class="[^"]*myui-vodlist__thumb',
                r'<div[^>]*class="[^"]*myui-content__thumb[^"]*"[^>]*>.*?<img[^>]*data-original="([^"]+)"',
                r'<div[^>]*class="[^"]*myui-content__thumb[^"]*"[^>]*>.*?<img[^>]*src="([^"]+)"',
                r'<img[^>]*data-original="([^"]+)"',
            ]:
                pic = re.search(pattern, html, re.DOTALL)
                if pic:
                    vod_pic = pic.group(1)
                    break
            if vod_pic.startswith("//"):
                vod_pic = "https:" + vod_pic

            # 简介（可能很长，直接截断）
            vod_content = ""
            desc = re.search(
                r'简介[:：](.*?)(?:</p>|<div|<script|</div>)', html, re.DOTALL)
            if desc:
                vod_content = self._clean_html(desc.group(1))
            if not vod_content:
                desc2 = re.search(r'<p[^>]*class="myui-content__detail[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
                if desc2:
                    vod_content = self._clean_html(desc2.group(1))

            vod_actor = ""
            actor = re.search(r'主演[:：]\s*(?:</span>)?[^<]*?([^<]{3,300})', html)
            if actor:
                vod_actor = re.sub(r'\s+', ' ', actor.group(1)).strip()
            vod_director = ""
            director = re.search(r'导演[:：]\s*(?:</span>)?[^<]*?([^<]{3,100})', html)
            if director:
                vod_director = re.sub(r'\s+', ' ', director.group(1)).strip()

            vod_year = ""
            year = re.search(r'年份[:：]\s*(\d{4})', html)
            if year:
                vod_year = year.group(1)

            vod_remarks = ""
            for pat in (r'更新[:：]\s*([^<]{2,40})', r'状态[:：]\s*([^<]{2,40})'):
                m = re.search(pat, html)
                if m:
                    vod_remarks = m.group(1).strip()
                    if vod_remarks:
                        break
            if vod_remarks and '/' in vod_remarks:
                vod_remarks = vod_remarks.split('/')[0].strip()

            sources = self._parse_play_sources(html, vod_id)
            if not sources:
                self._log("未能解析到播放源")
                return {"list": []}

            from_list = []
            url_list = []
            for src in sources:
                from_list.append(src["source_name"])
                url_list.append("#".join(
                    "%s$%s" % (ep["name"], ep["link"]) for ep in src["episodes"]))

            video = {
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_year": vod_year,
                "vod_area": "",
                "vod_actor": vod_actor,
                "vod_director": vod_director,
                "vod_content": vod_content,
                "vod_remarks": vod_remarks,
                "vod_play_from": "$$$".join(from_list),
                "vod_play_url": "$$$".join(url_list),
            }
            self._log("详情解析成功: %s 线路: %s" % (vod_name, "$$$".join(from_list)))
            return {"list": [video]}
        except Exception as e:
            self._log("detailContent异常: %s" % e)
            return {"list": []}

    def playerContent(self, flag, id, vipFlags=None):
        try:
            parts = str(id).split("-")
            if len(parts) != 3:
                return {"parse": 0, "url": "", "header": ""}
            vod_id, sid, nid = parts
            play_url = self._get_play_url(vod_id, sid, nid)
            if not play_url:
                play_url = "%s/vod/play/id/%s/sid/%s/nid/%s.html" % (self.base_url, vod_id, sid, nid)
            # 直链判断
            is_direct = bool(re.search(r'\.(m3u8|mp4|flv|ts|mkv)([?#&]|$)', play_url, re.I))
            is_webview = play_url.startswith(self.base_url + "/vod/play/")
            parse_flag = 0 if (is_direct or not is_webview) else 1
            self._log("播放URL: %s... parse=%d" % (play_url[:80], parse_flag))
            if parse_flag == 0:
                return {"parse": 0, "url": play_url, "header": self.play_headers.copy()}
            return {"parse": 1, "url": play_url, "header": ""}
        except Exception as e:
            self._log("playerContent异常: %s" % e)
            return {"parse": 0, "url": "", "header": ""}

    def getName(self):
        return self.name

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        pass