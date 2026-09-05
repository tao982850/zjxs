# -*- coding: utf-8 -*-
"""
糯米影视 (www.fjrenhao.com) TVBox 爬虫 —— 性能优化版

站点结构：
- 首页：/
- 分类：/type/{id}-{page}.html  第一页可用 /type/{id}.html
- 搜索：/search/-------------.html?wd={keyword} （目前被 Cloudflare 阻拦，保留接口但可能返回空）
- 详情：/voddetail/{id}.html
- 播放：/vplay/{id}/{sid}/{nid}.html

注意：该站使用 Cloudflare，必须带移动端 User-Agent 和 Referer，
      否则会被返回 403 "Just a moment..."

性能优化（实测源站 TTFB 2~6 秒，等待服务器是唯一瓶颈）：
1. 结果级 TTL 缓存：首页/分类页 5 分钟、详情页 2 分钟、播放地址 2 分钟、
   空结果仅缓存 30 秒（避免站点故障时空列表被长期缓存）
2. init 后台预热首页：TVBox 调 init 后预热线程立即抓首页，
   紧随其后的 homeContent 直接命中缓存，首屏从 3~6 秒降到 0 秒
3. 单飞（singleflight）：并发请求同一页面只发一次网络请求
4. 快速超时 + 一次重试：首次 (4s,8s)，失败后 (3s,5s) 再试一次，
   最坏 20 秒出结果，而不是原来干等 15 秒后返回空
5. 优先使用 lxml 解析器（更快更稳），环境没有时自动回退 html.parser
6. 连接池扩容 + gzip 传输（分类页 194KB 压缩后仅 25KB）
"""

import json
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()

# 线程能力检测：标准 TVBox Python 环境可用；
# 某些精简环境无 threading 时自动降级为纯缓存模式（功能不受影响）
try:
    import threading

    _Event = threading.Event
    _Thread = threading.Thread
except Exception:
    _Event = None
    _Thread = None

# 解析器自动选择：lxml 比 html.parser 快约 30% 且容错更好
_PARSER = "html.parser"
try:
    import lxml  # noqa: F401

    _PARSER = "lxml"
except Exception:
    pass

try:
    from base.spider import Spider
except ImportError:

    class Spider:
        def init(self, extend=""):
            pass


class Spider(Spider):
    # ---- 缓存配置 ----
    HOME_TTL = 300       # 首页结果缓存 5 分钟
    CATEGORY_TTL = 300   # 分类页结果缓存 5 分钟
    DETAIL_TTL = 120     # 详情页结果缓存 2 分钟
    PLAY_TTL = 120       # 播放地址缓存 2 分钟（该站 m3u8 为无 token 静态链接，可安全缓存）
    EMPTY_TTL = 30       # 空结果只缓存 30 秒，站点恢复后能尽快自愈
    CACHE_MAX = 24       # 最多缓存条目数（每条几十 KB，总量 <1MB）

    def __init__(self):
        super().__init__()
        self.home_url = "https://www.fjrenhao.com"
        self.ua = "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        self.headers = {
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Referer": self.home_url + "/",
        }
        self.timeout = (4, 8)  # (连接超时, 读取超时)
        self.session = requests.Session()
        # 连接池扩容：并发请求时复用连接，省去重复 TCP/TLS 握手
        try:
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=8, pool_maxsize=8, max_retries=0
            )
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)
        except Exception:
            pass
        # 结果缓存：key -> (过期时间戳, json字符串)
        self._cache = {}
        # 单飞表：key -> Event，标记该请求正在飞行中
        self._inflight = {}
        self._warmed = False

    def getName(self):
        return "糯米影视"

    def init(self, extend=""):
        try:
            super().init(extend)
        except Exception:
            pass
        # 后台预热首页：TVBox 调 init 后紧接着调 homeContent，
        # 预热线程可提前完成抓取，让首屏直接命中缓存
        if _Thread and not self._warmed:
            self._warmed = True
            try:
                _Thread(target=self._warmup, daemon=True).start()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 缓存与请求基础设施
    # ------------------------------------------------------------------

    def _warmup(self):
        try:
            self._cached("home", self.HOME_TTL, self._fetch_home)
        except Exception:
            pass

    def _loads(self, payload):
        try:
            return json.loads(payload)
        except Exception:
            return {"class": [], "list": []}

    def _looks_empty(self, result):
        """判断结果是否为空，空结果只做短缓存"""
        if isinstance(result, dict):
            lst = result.get("list")
            if lst is not None:
                return not lst
            return not result.get("url")
        return True

    def _cache_put(self, key, payload, ttl):
        try:
            if len(self._cache) >= self.CACHE_MAX:
                # 淘汰最早过期的条目
                oldest = min(self._cache.items(), key=lambda kv: kv[1][0])[0]
                self._cache.pop(oldest, None)
        except Exception:
            pass
        self._cache[key] = (time.time() + ttl, payload)

    def _cached(self, key, ttl, fetcher):
        """带 TTL 的结果缓存 + 单飞：并发请求同一 key 只发一次网络请求"""
        hit = self._cache.get(key)
        if hit and hit[0] > time.time():
            return self._loads(hit[1])
        ev = None
        if _Event:
            waiting = self._inflight.get(key)
            if waiting is not None:
                # 已有同 key 请求在飞行中，等它完成（最多 15 秒）
                waiting.wait(15)
                hit = self._cache.get(key)
                if hit and hit[0] > time.time():
                    return self._loads(hit[1])
                # 对方失败了，自己兜底再抓一次
            ev = _Event()
            self._inflight[key] = ev
        try:
            result = fetcher()
            if self._looks_empty(result):
                ttl = self.EMPTY_TTL
            self._cache_put(key, json.dumps(result, ensure_ascii=False), ttl)
            return result
        finally:
            if _Event and ev is not None:
                self._inflight.pop(key, None)
                ev.set()

    def _get(self, url):
        """请求页面：快速超时 + 失败重试一次 + Cloudflare 拦截重试"""
        full = url if url.startswith("http") else self.home_url + url
        last_err = ""
        for attempt in (0, 1):
            try:
                timeout = (4, 8) if attempt == 0 else (3, 5)
                r = self.session.get(
                    full, headers=self.headers, timeout=timeout, verify=False
                )
                if r.status_code == 200:
                    if r.text:
                        r.encoding = "utf-8"
                        return r.text
                    last_err = "空响应"
                elif r.status_code == 403 and "Just a moment" in r.text:
                    last_err = "Cloudflare 验证中"
                    time.sleep(0.5)  # 稍等片刻再试
                    continue
                else:
                    last_err = f"HTTP {r.status_code}"
                    break
            except Exception as e:
                last_err = str(e)
                if attempt == 0:
                    time.sleep(0.3)
        print(f"[糯米影视] 请求失败: {url} -> {last_err}", file=sys.stderr)
        return ""

    def _soup(self, html):
        return BeautifulSoup(html, _PARSER)

    # ------------------------------------------------------------------
    # 页面解析（与原版逻辑一致）
    # ------------------------------------------------------------------

    def _id_from_url(self, href):
        if not href:
            return ""
        m = re.search(r"/voddetail/(\d+)\.html", href)
        if m:
            return m.group(1)
        m = re.search(r"/vplay/(\d+)/", href)
        if m:
            return m.group(1)
        return ""

    def _parse_vodlist(self, soup):
        result = []
        for box in soup.select(".stui-vodlist__box"):
            thumb = box.select_one(".stui-vodlist__thumb")
            if not thumb or not thumb.get("href"):
                continue
            vod_id = self._id_from_url(thumb.get("href"))
            if not vod_id:
                continue
            name = thumb.get("title", "")
            if not name:
                h4 = box.select_one(".stui-vodlist__detail .title a")
                if h4:
                    name = h4.get_text(strip=True)
            pic = thumb.get("data-original", "")
            if not pic:
                img = thumb.select_one("img")
                if img:
                    pic = img.get("data-original", img.get("src", ""))
            remark = ""
            pic_text = thumb.select_one(".pic-text")
            if pic_text:
                remark = pic_text.get_text(strip=True)
                if remark == name:
                    remark = ""
            if not remark:
                detail = box.select_one(".stui-vodlist__detail")
                if detail:
                    detail_text = detail.select_one(".text")
                    if detail_text:
                        remark = detail_text.get_text(strip=True)
            if not remark:
                # 有些页面在超链接后面直接跟了状态文字
                text_node = thumb.next_sibling
                if text_node and text_node.string:
                    remark = text_node.string.strip()
            result.append({
                "vod_id": vod_id,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": remark,
            })
        return result

    # ------------------------------------------------------------------
    # TVBox 接口
    # ------------------------------------------------------------------

    def homeContent(self, filter):
        return self._cached("home", self.HOME_TTL, self._fetch_home)

    def _fetch_home(self):
        html = self._get("/")
        if not html:
            return {"class": [], "list": []}
        soup = self._soup(html)

        # 分类导航：优先从页面导航提取
        classes = []
        seen = set()
        for a in soup.select(".stui-header__menu a, header a"):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            m = re.search(r"/type/(\d+)\.html", href)
            if m and text and m.group(1) not in seen:
                seen.add(m.group(1))
                classes.append({"type_id": m.group(1), "type_name": text})

        # 补充常见子分类，便于 TVBox 快速切换
        default_classes = [
            ("1", "电影"),
            ("2", "电视剧"),
            ("3", "综艺"),
            ("4", "动漫"),
            ("6", "动作片"),
            ("7", "喜剧片"),
            ("8", "爱情片"),
            ("9", "科幻片"),
            ("10", "恐怖片"),
            ("11", "剧情片"),
            ("12", "战争片"),
            ("13", "国产剧"),
            ("14", "香港剧"),
            ("15", "韩国剧"),
            ("16", "欧美剧"),
            ("21", "日本剧"),
            ("22", "其它剧"),
            ("23", "纪录片"),
            ("24", "动画片"),
            ("25", "大陆综艺"),
            ("26", "日韩综艺"),
            ("27", "港台综艺"),
            ("28", "欧美综艺"),
            ("29", "国产动漫"),
            ("30", "日韩动漫"),
            ("31", "欧美动漫"),
            ("32", "其它动漫"),
            ("33", "网红短剧"),
        ]
        for tid, name in default_classes:
            if tid not in seen:
                seen.add(tid)
                classes.append({"type_id": tid, "type_name": name})

        # 首页列表：按板块分类组件提取
        home_list = []
        for pannel in soup.select(".stui-pannel"):
            head = pannel.select_one(".stui-pannel__head")
            if not head:
                continue
            title = head.get_text(" ", strip=True)
            # 尝试匹配板块标题与分类
            type_id = ""
            for a in head.select("a"):
                m = re.search(r"/type/(\d+)\.html", a.get("href", ""))
                if m:
                    type_id = m.group(1)
                    break
            if not type_id:
                # 通过标题映射
                if "电影" in title:
                    type_id = "1"
                elif "电视剧" in title:
                    type_id = "2"
                elif "综艺" in title:
                    type_id = "3"
                elif "动漫" in title:
                    type_id = "4"
                else:
                    continue
            # 获取板块标题，优先使用 h3.title 里的文字（不包含图标）
            section_title = ""
            h3 = pannel.select_one(".stui-pannel__head .title")
            if h3:
                section_title = h3.get_text(" ", strip=True)
                # 去掉图标文字
                section_title = section_title.replace("更多", "").strip()
            if not section_title:
                section_title = title.split()[0] if title else ""
            for item in self._parse_vodlist(pannel):
                item["type_name"] = section_title
                home_list.append(item)

        if not home_list:
            home_list = self._parse_vodlist(soup)

        return {"class": classes, "list": home_list}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        key = f"cat:{tid}:{pg}"
        return self._cached(key, self.CATEGORY_TTL, lambda: self._fetch_category(tid, pg))

    def _fetch_category(self, tid, pg):
        if pg <= 1:
            url = f"/type/{tid}.html"
        else:
            url = f"/type/{tid}-{pg}.html"
        html = self._get(url)
        if not html:
            return {"page": str(pg), "pagecount": "0", "limit": "24", "total": "0", "list": []}
        soup = self._soup(html)
        items = self._parse_vodlist(soup)

        # 该站分类页没有真正的翻页功能，各页面内容相同
        # 设为 pagecount=1 避免 TVBox 无限加载
        return {
            "page": str(pg),
            "pagecount": "1",
            "limit": str(len(items) if items else 24),
            "total": str(len(items)),
            "list": items,
        }

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = str(ids[0]).split("$")[0]
        key = f"detail:{vod_id}"
        return self._cached(key, self.DETAIL_TTL, lambda: self._fetch_detail(vod_id))

    def _fetch_detail(self, vod_id):
        html = self._get(f"/voddetail/{vod_id}.html")
        if not html:
            return {"list": []}
        soup = self._soup(html)

        # 基本信息
        name = ""
        thumb = soup.select_one(".stui-content__thumb img")
        pic = ""
        if thumb:
            pic = thumb.get("data-original", thumb.get("src", ""))
        detail = soup.select_one(".stui-content__detail")
        if detail:
            h1 = detail.select_one("h1, .title")
            if h1:
                name = h1.get_text(strip=True)

        # 元信息：站点用行内标签，格式为 <p class="data"><span class="text-muted">类型：</span><a>剧情</a>
        meta = {"类型": [], "地区": [], "年份": [], "主演": [], "导演": [], "更新": []}
        if detail:
            for data in detail.select(".data"):
                # 提取标签后面的所有文字/链接
                label = ""
                for child in data.children:
                    if child.name == "span" and "text-muted" in child.get("class", []):
                        label = child.get_text(strip=True).replace("：", "")
                    elif child.name in ("a", None):
                        if label and label in meta:
                            text = child.get_text(strip=True) if child.name == "a" else str(child).strip()
                            if text:
                                meta[label].append(text)

        # 简介：使用 id="desc" 的完整简介
        desc = ""
        desc_el = soup.select_one("#desc") or soup.select_one(".stui-content__detail .desc")
        if desc_el:
            desc = desc_el.get_text(" ", strip=True)
            # 去掉常见前缀
            desc = re.sub(r"^(简介|剧情简介|类型)：?\s*", "", desc)
            desc = desc.replace("详情", "").strip()

        # 清理名称：去掉粘连的评分
        if name:
            name = re.sub(r"\s*\d+\.\d+\s*$", "", name).strip()
        if not name:
            name = "未知标题"

        # 播放源
        sources = []
        urls = []
        for box in soup.select(".stui-pannel-box.b.playlist"):
            head = box.select_one(".stui-pannel__head")
            source_name = "默认"
            if head:
                source_name = head.get_text(strip=True)
            links = []
            for a in box.select(".stui-content__playlist li a"):
                href = a.get("href", "")
                m = re.search(r"/vplay/(\d+)/(\d+)/(\d+)\.html", href)
                if m:
                    sid = m.group(2)
                    nid = m.group(3)
                    ep_name = a.get_text(strip=True)
                    # 保存完整标识：视频ID/源序号/集号
                    links.append(f"{ep_name}${vod_id}/{sid}/{nid}")
            if links:
                sources.append(source_name)
                urls.append("#".join(links))

        if not name:
            name = "未知标题"

        return {
            "list": [{
                "vod_id": vod_id,
                "vod_name": name,
                "vod_pic": pic,
                "type_name": " ".join(meta.get("类型", [])),
                "vod_year": " ".join(meta.get("年份", [])),
                "vod_area": " ".join(meta.get("地区", [])),
                "vod_actor": " ".join(meta.get("主演", [])),
                "vod_director": " ".join(meta.get("导演", [])),
                "vod_remarks": " ".join(meta.get("更新", [])),
                "vod_content": desc,
                "vod_play_from": "$$$".join(sources) if sources else "糯米",
                "vod_play_url": "$$$".join(urls) if urls else "",
            }]
        }

    def searchContent(self, key, quick, pg="1"):
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick, pg="1"):
        pg = int(pg) if str(pg).isdigit() else 1
        # 站点搜索页被 Cloudflare 阻拦，保留代码但可能返回空
        url = f"/search/-------------.html?wd={requests.utils.quote(key)}"
        html = self._get(url)
        if not html:
            return {"page": "1", "pagecount": "0", "limit": "24", "total": "0", "list": []}
        soup = self._soup(html)
        items = self._parse_vodlist(soup)
        return {
            "page": str(pg),
            "pagecount": "1",
            "limit": "24",
            "total": str(len(items)),
            "list": items,
        }

    def playerContent(self, flag, id, vipFlags):
        # id 格式："vod_id/sid/nid"
        parts = str(id).strip().split("/")
        if len(parts) != 3:
            return {"parse": 0, "jx": 0, "url": ""}
        vod_id, sid, nid = parts
        key = f"play:{vod_id}/{sid}/{nid}"
        # 该站播放地址为无 token 的静态 m3u8 链接，短缓存可显著加速连续追剧
        return self._cached(key, self.PLAY_TTL, lambda: self._fetch_play(vod_id, sid, nid))

    def _fetch_play(self, vod_id, sid, nid):
        html = self._get(f"/vplay/{vod_id}/{sid}/{nid}.html")
        if not html:
            return {"parse": 0, "jx": 0, "url": ""}
        # 从页面中提取 player_aaaa JSON
        m = re.search(r'var player_aaaa\s*=\s*({.*?})</script>', html, re.S)
        if not m:
            return {"parse": 0, "jx": 0, "url": ""}
        try:
            player = json.loads(m.group(1))
            url = player.get("url", "")
            if url:
                # 去除可能的转义
                url = url.replace("\\/", "/")
                return {
                    "parse": 0,
                    "jx": 0,
                    "url": url,
                    "header": {
                        "User-Agent": self.ua,
                        "Referer": self.home_url + "/",
                    },
                }
        except Exception:
            pass
        return {"parse": 0, "jx": 0, "url": ""}


# 以下用于本地调试，不会影响 TVBox 加载
if __name__ == "__main__":
    sp = Spider()
    sp.init()
    time.sleep(1)  # 给预热线程一点时间（模拟 TVBox 调 init 后的间隙）

    t = time.time()
    home = sp.homeContent(False)
    print("=== home（含预热结果） 耗时 %.2fs ===" % (time.time() - t))
    print("分类数: %d, 影片数: %d" % (len(home["class"]), len(home["list"])))

    t = time.time()
    home2 = sp.homeContent(False)
    print("=== home（缓存命中） 耗时 %.3fs ===" % (time.time() - t))

    t = time.time()
    cat = sp.categoryContent("1", "1", False, {})
    print("=== category 首次 耗时 %.2fs, 影片数: %d ===" % (time.time() - t, len(cat["list"])))
    t = time.time()
    cat2 = sp.categoryContent("1", "1", False, {})
    print("=== category 缓存命中 耗时 %.3fs ===" % (time.time() - t))

    t = time.time()
    det = sp.detailContent(["161660"])
    print("=== detail 首次 耗时 %.2fs ===" % (time.time() - t))
    vod = det["list"][0] if det["list"] else {}
    print("片名:", vod.get("vod_name"), "| 播放源:", vod.get("vod_play_from", "")[:40])
    t = time.time()
    det2 = sp.detailContent(["161660"])
    print("=== detail 缓存命中 耗时 %.3fs ===" % (time.time() - t))

    # 播放测试：从详情里取第一集
    play_url = vod.get("vod_play_url", "")
    if play_url:
        first = play_url.split("#")[0].split("$")[-1]
        t = time.time()
        play = sp.playerContent("", first, [])
        print("=== player 首次 耗时 %.2fs, url: %s ===" % (time.time() - t, play.get("url", "")[:60]))
        t = time.time()
        play2 = sp.playerContent("", first, [])
        print("=== player 缓存命中 耗时 %.3fs ===" % (time.time() - t))
