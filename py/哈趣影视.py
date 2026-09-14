# -*- coding: utf-8 -*-
"""
影视快搜(哈趣影视) - kan.znds.com Python Spider
兼容 FongMi/TV & WebHomeTV/PeekPro 等壳子

站点特征:
1. 当贝旗下影视聚合站, 提供电影/电视剧/综艺/动漫/少儿 五大分类的聚合信息;
2. 本站不托管视频, 详情页"播放源"跳转到爱奇艺等正版平台页面, 播放采用 WebView 加载源页面;
3. URL 结构:
     /movie/ /tv/ /zongyi/ /dongman/ /shaoer/   分类(第1页)
     /{cat}/p_{page}                             分页
     /{cat}/cat_{题材}_year_{年份}_area_{地区}/   筛选(cat/year/area, all=不限)
     /v/{id}.html                                详情
     /search/?q={kw}                             搜索
4. 列表条目: class="film_box" 网格结构; 搜索条目: class="search_box clearfix";
5. 海报为 http://imgsou.dangbei.com 懒加载(带 !200/!300 缩略后缀, 已保留原图)。
"""
import re
import json
import time
import urllib.parse
import requests
from urllib.parse import quote

try:
    from base.spider import Spider as _BaseSpider
except ImportError:
    class _BaseSpider(object):
        def __init__(self, *a, **kw):
            pass


class Spider(_BaseSpider):
    # ==================== 基础配置 ====================
    name = "影视快搜"
    base_url = "https://kan.znds.com"

    # 声明本源支持壳子聚合搜索、快速搜索、筛选和换源聚合
    searchable = 1
    quickSearch = 1
    filterable = 1
    changeable = 1

    # 分类映射
    CATEGORY_NAMES = {
        "1": "电影", "2": "电视剧", "3": "综艺", "4": "动漫", "5": "少儿",
    }
    # type_id -> 分类路径
    CATEGORY_PATHS = {
        "1": "movie", "2": "tv", "3": "zongyi", "4": "dongman", "5": "shaoer",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://kan.znds.com/",
        "Connection": "keep-alive",
    }

    play_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Referer": "https://kan.znds.com/",
        "Accept": "*/*",
    }

    # 题材/地区/年份 筛选值(与站点 URL 段对应)
    CLASS_VALUES = {
        "言情": "yanqing", "剧情": "juqing", "伦理": "lunli", "喜剧": "xiju",
        "悬疑": "xuanyi", "都市": "dushi", "乡村": "xiangcun", "偶像": "ouxiang",
        "古装": "guzhuang", "军事": "junshi", "警匪": "jingfei", "历史": "lishi",
        "武侠": "wuxia", "科幻": "kehuan", "奇幻": "qihuan", "情景": "qingjing",
        "动作": "dongzuo", "神话": "shenhua", "谍战": "diezhan", "其它": "qi-ta",
    }
    AREA_VALUES = {
        "中国": "zhongguo", "中国香港": "xianggan", "韩国": "hanguo", "美国": "meiguo",
        "泰国": "taiguo", "日本": "riben", "新加坡": "xinjiapo", "其他": "qita",
    }
    YEAR_VALUES = ["2023", "2022", "2021", "2020", "2019", "2018", "2017", "2016",
                   "2015", "2014", "2013", "2012", "2011", "2010"]

    # 筛选器(分类通用: 题材/地区/年份)
    FILTERS = {}
    for _tid in CATEGORY_NAMES:
        _filters = []
        _filters.append({"key": "class", "name": "题材", "value": [{"n": "全部", "v": ""}] +
                        [{"n": k, "v": v} for k, v in CLASS_VALUES.items()]})
        _filters.append({"key": "area", "name": "地区", "value": [{"n": "全部", "v": ""}] +
                        [{"n": k, "v": v} for k, v in AREA_VALUES.items()]})
        _filters.append({"key": "year", "name": "年份", "value": [{"n": "全部", "v": ""}] +
                        [{"n": y, "v": y} for y in YEAR_VALUES]})
        FILTERS[_tid] = _filters

    def __init__(self):
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        self._last_req_time = 0
        self._min_req_interval = 0.15

    # ==================== 工具方法 ====================
    def _log(self, msg):
        print(f"[{self.name}] {msg}")

    def _apply_req_delay(self):
        now = time.time()
        elapsed = now - self._last_req_time
        if 0 < elapsed < self._min_req_interval:
            time.sleep(self._min_req_interval - elapsed)
        self._last_req_time = time.time()

    def fetch(self, url, headers=None, timeout=15):
        self._apply_req_delay()
        return self._session.get(url, headers=headers or {}, timeout=timeout)

    def _get(self, url, max_retry=3, timeout=12):
        h = self.headers.copy()
        for attempt in range(max_retry):
            try:
                resp = self.fetch(url, headers=h, timeout=timeout)
                if getattr(resp, 'status_code', 200) in (403, 429, 500, 502, 503):
                    self._log(f"HTTP {getattr(resp,'status_code','?')} 第{attempt+1}次重试: {url[:80]}")
                    if attempt < max_retry - 1:
                        time.sleep(1 + attempt)
                        continue
                    return ""
                content = resp.content
                if not content:
                    return ""
                for enc in ('utf-8', 'gb18030', 'gbk'):
                    try:
                        return content.decode(enc)
                    except (UnicodeDecodeError, LookupError):
                        continue
                return content.decode('utf-8', errors='replace')
            except Exception as e:
                self._log(f"请求失败(第{attempt+1}次): {url[:80]}, {e}")
                if attempt < max_retry - 1:
                    time.sleep(1 + attempt)
        return ""

    def _clean_vod_name(self, name):
        return name.strip() if name else name

    def _clean_vod_pic(self, pic):
        """海报: 去掉 !200/!300 缩略后缀, 保留原图"""
        if not pic:
            return ''
        pic = re.sub(r'!\d+$', '', pic)
        if pic.startswith('//'):
            pic = 'https:' + pic
        if pic.startswith('/'):
            pic = self.base_url + pic
        return pic

    def _clean_html(self, text):
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    # ==================== 列表解析 ====================

    def _parse_film_list(self, html):
        """分类页网格条目: class="film_box" """
        videos = []
        if not html:
            return videos
        pattern = re.compile(
            r'<a href="(/v/(\d+)\.html)"[^>]*>.*?'
            r'<img[^>]*src="([^"]+)"[^>]*alt="([^"]*)"[^>]*title="[^"]*">.*?'
            r'<p class="text-center">\s*([^<]*)\s*</p>.*?'
            r'<div class="sorce">\s*([^<]*)\s*</div>',
            re.S
        )
        seen = set()
        for m in pattern.finditer(html):
            vid = m.group(2)
            if not vid or vid in seen:
                continue
            seen.add(vid)
            name = (m.group(4) or m.group(5) or "").strip()
            remarks = (m.group(6) or "").strip()  # 评分
            videos.append({
                "vod_id": vid,
                "vod_name": self._clean_vod_name(name),
                "vod_pic": self._clean_vod_pic(m.group(3)),
                "vod_remarks": remarks,
            })
        return videos

    def _parse_search_list(self, html):
        """搜索页条目: class="search_box clearfix" """
        videos = []
        if not html:
            return videos
        pattern = re.compile(
            r'<div class="search_box clearfix">.*?'
            r'<a href="(/v/(\d+)\.html)"[^>]*title="[^"]*">.*?'
            r'<img[^>]*src="([^"]+)"[^>]*alt="[^"]*">.*?'
            r'<a href="/v/\d+\.html"[^>]*>([^<]*)</a>.*?'
            r'<div class="sorce_info">([^<]*)</div>',
            re.S
        )
        seen = set()
        for m in pattern.finditer(html):
            vid = m.group(2)
            if not vid or vid in seen:
                continue
            seen.add(vid)
            videos.append({
                "vod_id": vid,
                "vod_name": self._clean_vod_name(m.group(4).strip()),
                "vod_pic": self._clean_vod_pic(m.group(3)),
                "vod_remarks": (m.group(5) or "").strip(),
            })
        return videos

    # ==================== 筛选 URL 构造 ====================

    def _build_filter_url(self, path, flt):
        """构造筛选 URL: /{path}/cat_{cat}_year_{year}_area_{area}/"""
        cat = flt.get("class", "") or "all"
        year = flt.get("year", "") or "all"
        area = flt.get("area", "") or "all"
        return f"{self.base_url}/{path}/cat_{cat}_year_{year}_area_{area}/"

    # ==================== TVBox 五大核心方法 ====================

    def init(self, extend=''):
        self._log("初始化完成")

    def homeContent(self, filter=False):
        result = {
            "class": [
                {"type_id": tid, "type_name": name}
                for tid, name in self.CATEGORY_NAMES.items()
            ]
        }
        if filter:
            result["filters"] = self.FILTERS
            result["filter"] = self.FILTERS
        return result

    def homeVideoContent(self):
        try:
            # 各分类取前几条拼首页
            videos = []
            for tid in ["1", "2"]:
                path = self.CATEGORY_PATHS[tid]
                html = self._get(f"{self.base_url}/{path}/")
                if html:
                    videos.extend(self._parse_film_list(html))
            return {"list": videos[:30]}
        except Exception as e:
            self._log(f"homeVideoContent异常: {e}")
            return {"list": []}

    def categoryContent(self, tid, pg, filter=False, content=None):
        try:
            pg = int(pg) if pg else 1
            if str(tid) not in self.CATEGORY_PATHS:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 30, "total": 0}
            path = self.CATEGORY_PATHS[str(tid)]

            flt = {}
            if content:
                try:
                    flt = json.loads(content) if isinstance(content, str) else content
                except Exception:
                    flt = {}

            # 有筛选走筛选 URL, 无筛选走分类分页
            if any(flt.get(k) for k in ("class", "area", "year")):
                url = self._build_filter_url(path, flt)
                # 筛选页分页: /{path}/cat_x_year_x_area_x/p_{pg}?
                if pg > 1:
                    # 站点筛选页分页为 cat_x_year_x_area_x 后接 /p_{pg}, 但实际筛选页无分页链接时兜底返回第一页
                    pass
            else:
                if pg > 1:
                    url = f"{self.base_url}/{path}/p_{pg}"
                else:
                    url = f"{self.base_url}/{path}/"

            self._log(f"分类请求: {url}")
            html = self._get(url)
            if not html:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 30, "total": 0}

            videos = self._parse_film_list(html)

            # 分页: 取页码链接中的最大值作为总页数
            pagecount = 1
            nums = re.findall(r'<a class="num" href="/[a-z]+/p_(\d+)"', html)
            if nums:
                try:
                    pagecount = max(int(n) for n in nums)
                except (ValueError, TypeError):
                    pagecount = 1

            return {
                "list": videos,
                "page": pg,
                "pagecount": max(1, pagecount),
                "limit": 30,
                "total": max(1, pagecount) * 30
            }
        except Exception as e:
            self._log(f"categoryContent异常: {e}")
            return {"list": [], "page": pg, "pagecount": 1, "limit": 30, "total": 0}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            keyword = str(key or "").strip()
            if not keyword:
                return {"page": 1, "pagecount": 1, "limit": 0, "total": 0, "list": []}
            q = urllib.parse.quote(keyword)
            url = f"{self.base_url}/search/?q={q}"
            self._log(f"搜索请求: {url[:120]}")

            html = self._get(url, max_retry=2, timeout=10)
            if not html:
                return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}

            videos = self._parse_search_list(html)
            if not videos:
                videos = self._parse_film_list(html)

            # 相关度排序
            key_lower = keyword.lower()
            videos.sort(key=lambda v: 0 if key_lower in v.get('vod_name', '').lower() else 1)

            return {
                "list": videos[:30],
                "page": 1,
                "pagecount": 1,
                "limit": 20,
                "total": len(videos),
            }
        except Exception as e:
            self._log(f"searchContent异常: {e}")
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}

    def detailContent(self, ids):
        try:
            vod_id = ids[0] if isinstance(ids, list) else str(ids)
            url = f"{self.base_url}/v/{vod_id}.html"
            self._log(f"详情请求: {url}")
            html = self._get(url)
            if not html:
                return {"list": []}

            # 标题
            title = re.search(r'<h1[^>]*>.*?<a[^>]*>([^<]*)</a>', html, re.S)
            vod_name = title.group(1).strip() if title else "未知"
            if not vod_name:
                t2 = re.search(r'<title>([^<]*)</title>', html)
                if t2:
                    vod_name = t2.group(1).split('_')[0].strip()

            # 海报
            vod_pic = ""
            img = re.search(r'<img[^>]*src="(http[^"]+)"[^>]*>', html)
            if img:
                vod_pic = self._clean_vod_pic(img.group(1))
            if not vod_pic:
                img = re.search(r'<img[^>]*src="([^"]+)"[^>]*alt="[^"]*"', html)
                if img:
                    vod_pic = self._clean_vod_pic(img.group(1))

            # 信息: <p class='short_introduct'><strong>类型: </strong>...</p>
            vod_actor = vod_director = vod_year = vod_area = ""
            for m in re.finditer(r"<strong>([^<：:]{1,8})[：:]\s*</strong>\s*([^<]*)", html):
                label = m.group(1).strip()
                val = m.group(2).strip().lstrip(',')
                if not val:
                    continue
                if label == "导演":
                    vod_director = val
                elif label == "主演":
                    vod_actor = val
                elif label == "国家/地区":
                    vod_area = val
                elif label == "类型":
                    pass

            # 简介
            vod_content = ""
            desc = re.search(r'<meta name="description" content="([^"]*)"', html, re.I)
            if desc:
                vod_content = self._clean_html(desc.group(1))
            if not vod_content:
                intro = re.search(r"<span>简介[：:]\s*</span>\s*([^<]+)", html)
                if intro:
                    vod_content = self._clean_html(intro.group(1))

            # 年份(从简介/标题提取合理年份)
            vod_year = ""
            desc_text = vod_content + " " + vod_name
            ym = re.search(r'(20[01]\d|19[89]\d)', desc_text)
            if ym:
                vod_year = ym.group(1)
            if not vod_year:
                ym = re.search(r'year_(\d{4})', html)
                if ym:
                    vod_year = ym.group(1)

            # 播放源: <p class="online_choice"><img ... value="{url}">平台名</p> 或 online_option li
            sources = []
            seen_src = set()
            # 主源
            m = re.search(r'class="online_choice"[^>]*>.*?<img[^>]*value="([^"]+)"[^>]*>([^<]*)', html, re.S)
            if m:
                src_url = m.group(1).strip()
                src_name = m.group(2).strip() or "播放"
                if src_url and src_url not in seen_src:
                    seen_src.add(src_url)
                    sources.append({"name": src_name, "url": src_url})
            # 备选源
            for m in re.finditer(r'class="online_option">(.*?)</ul>', html, re.S):
                for em in re.finditer(r'<img[^>]*value="([^"]+)"[^>]*>([^<]*)', m.group(1)):
                    src_url = em.group(1).strip()
                    src_name = em.group(2).strip() or "播放"
                    if src_url and src_url not in seen_src:
                        seen_src.add(src_url)
                        sources.append({"name": src_name, "url": src_url})

            # 兜底: 页面内爱奇艺/腾讯/优酷等平台链接
            if not sources:
                for m in re.finditer(r'value="(https?://(?:www\.)?(?:iqiyi|v\.qq|youku|mgtv|sohu|1905|bilibili)[^"]+)"', html):
                    src_url = m.group(1).strip()
                    if src_url not in seen_src:
                        seen_src.add(src_url)
                        src_name = re.search(r'https?://(?:www\.)?([a-z]+)', src_url)
                        sources.append({"name": src_name.group(1) if src_name else "播放", "url": src_url})

            if not sources:
                self._log(f"未找到播放源: {vod_name}")
                return {"list": []}

            # 每条源作为一条线路(单集, WebView 播放)
            from_list = []
            url_list = []
            for s in sources:
                from_list.append(s["name"])
                url_list.append(f"播放${s['url']}")

            video = {
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_year": vod_year,
                "vod_area": vod_area,
                "vod_actor": vod_actor,
                "vod_director": vod_director,
                "vod_content": vod_content,
                "vod_remarks": "",
                "vod_play_from": "$$$".join(from_list),
                "vod_play_url": "$$$".join(url_list),
            }
            self._log(f"详情解析成功: {vod_name}, 源: {video['vod_play_from']}")
            return {"list": [video]}
        except Exception as e:
            self._log(f"detailContent异常: {e}")
            return {"list": []}

    def playerContent(self, flag, id, vipFlags=None):
        try:
            # 第三方平台页面: WebView 加载(部分平台网页可播, 其余壳子自行处理)
            play_url = str(id)
            if not play_url.startswith("http"):
                play_url = f"https://kan.znds.com/v/{play_url}"
            self._log(f"播放WebView: {play_url[:100]}")
            hdr = {
                "User-Agent": self.play_headers["User-Agent"],
                "Referer": "https://kan.znds.com/",
                "Accept": "*/*",
            }
            return {"parse": 1, "url": play_url, "header": json.dumps(hdr, ensure_ascii=False)}
        except Exception as e:
            self._log(f"playerContent异常: {e}")
            return {"parse": 0, "url": "", "header": ""}

    def isVideoFormat(self, url):
        if not url:
            return False
        return any(e in url.lower() for e in (".m3u8", ".mp4", ".flv", ".ts", ".mkv"))

    def getName(self):
        return self.name

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        pass

    def getDependence(self):
        return {}

    def __getattr__(self, name):
        if name.startswith('get') and name[3:4].isupper():
            method_name = name[3:]
            if hasattr(self, method_name):
                return getattr(self, method_name)
        if name.startswith('get'):
            return {}
        return None


# ==================== 模块级函数 (FongMi/TV 兼容) ====================
_spider = None


def init(extend=""):
    global _spider
    if _spider is None:
        _spider = Spider()
    _spider.init(extend)


def getName():
    return "影视快搜"


def isVideoFormat(url):
    return _spider.isVideoFormat(url) if _spider else False


def homeContent(filter):
    return _spider.homeContent(filter) if _spider else {"class": [], "list": []}


def homeVideoContent():
    return _spider.homeVideoContent() if _spider else {"list": []}


def categoryContent(tid, pg, filter, extend):
    return _spider.categoryContent(tid, pg, filter, extend) if _spider else {"list": [], "page": "1", "pagecount": "1", "limit": "30", "total": "0"}


def detailContent(ids):
    return _spider.detailContent(ids) if _spider else {"list": []}


def searchContent(key, quick, pg="1"):
    return _spider.searchContent(key, quick, pg) if _spider else {"list": []}


def playerContent(flag, id, vipFlags):
    return _spider.playerContent(flag, id, vipFlags) if _spider else {"parse": 0, "url": "", "header": {}}
