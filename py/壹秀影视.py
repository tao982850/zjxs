# -*- coding: utf-8 -*-
# QQ群:807916734
"""
============================================================
 壹秀影视 (yixiuwang.com) TVBox 爬虫
 适用：TVBox / 影视仓 / FongMi (Python Spider 规范)
============================================================
【站点特性】
  - 苹果CMS(MacCMS) + mxtheme 模板，无验证码
  - 分类为拼音别名: /vodtype/dianying/（仅最新92部，不分页）
  - 完整库 + 翻页 + 筛选走 12 段格式: /vodshow/{alias}-{area}-{by}-{class}-{lang}-{letter}-...-{pg}---{year}/
     段位: 0分类 1地区 2排序 3类型 4语言 5-6字母 8页码 11年份
  - 播放加密: encrypt=1 → url 为 percent-encoding 混淆，unquote 即得 m3u8 直链
【接口一览】
  首页:    https://yixiuwang.com/
  分类:    /vodshow/{alias}--------{pg}---/  (+筛选参数)
  详情:    /voddetail/{id}/
  播放:    /vodplay/{id}-{sid}-{nid}/
  搜索:    /vodsearch/{关键词}-------------.html
============================================================
"""
import re
import json
import time
import urllib.parse

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        def fetch(self, url, headers=None, timeout=15, **kwargs):
            import requests
            return requests.get(url, headers=headers, timeout=timeout, verify=False)

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False


class Spider(BaseSpider):
    def __init__(self):
        super().__init__()
        self.host = "https://yixiuwang.com"

        # type_id(数字) -> 拼音别名
        self.ALIAS = {
            "1": "dianying", "2": "dsj", "3": "dongman",
            "4": "zongyi", "5": "shuangwenduanju",
            "6": "tiyusaishi", "7": "4kdianying",
        }
        self.CLASSES = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "剧集"},
            {"type_id": "3", "type_name": "动漫"},
            {"type_id": "4", "type_name": "综艺"},
            {"type_id": "5", "type_name": "短剧"},
            {"type_id": "6", "type_name": "体育赛事"},
            {"type_id": "7", "type_name": "4K电影"},
        ]

        # 筛选选项（与站点 /vodshow 筛选页一致）
        self.TYPE_OPTS = ["全部"] + ["动作", "喜剧", "爱情", "科幻", "恐怖", "剧情", "战争",
            "犯罪", "悬疑", "惊悚", "动画", "奇幻", "武侠", "冒险", "历史", "纪录",
            "古装", "枪战", "经典", "青春", "运动", "文艺", "农村", "家庭",
            "网络电影", "微电影"]
        self.AREA_OPTS = ["全部"] + ["大陆", "香港", "台湾", "美国", "韩国", "日本",
            "泰国", "英国", "法国", "德国", "意大利", "西班牙", "加拿大", "印度", "其他"]
        self.LANG_OPTS = ["全部"] + ["国语", "粤语", "韩语", "日语", "英语",
            "泰语", "法语", "德语", "闽南语", "其它"]
        self.YEAR_OPTS = ["全部"] + [str(y) for y in range(2026, 2009, -1)]
        self.BY_OPTS = [("时间", "time"), ("人气", "hits"), ("评分", "score")]
        self.LETTER_OPTS = ["全部"] + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + ["0-9"]

    # ==================== 基础 ====================

    def init(self, extend=""):
        # 支持配置传 host（换域名不用改代码）
        if extend and isinstance(extend, str) and extend.startswith("http"):
            self.host = extend.rstrip("/")
        print("壹秀影视 initialized: %s" % self.host)

    def getName(self):
        return "壹秀影视"

    def getDependence(self):
        return []

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv|mkv)(\?|$)', str(url), re.I))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, param):
        return [404, "text/plain", "Not Found"]

    def liveContent(self, url):
        return {"list": []}

    def action(self, action):
        return {}

    def header(self):
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36 Edg/150.0.0.0",
            "Referer": self.host + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    def playHeader(self):
        # 播放用：带 Referer 防盗链（dytt-network CDN 校验来源）
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
            "Referer": self.host + "/",
            "Accept": "*/*",
        }

    def getHtml(self, url, headers=None):
        try:
            rsp = self.fetch(url, headers=headers or self.header(), timeout=15)
            return rsp.text
        except Exception as e:
            print("请求失败 %s: %s" % (url, e))
            return ""

    def clean(self, text):
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def build_url(self, url):
        if not url:
            return ""
        if url.startswith("http"):
            return url
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self.host + url
        return self.host + "/" + url

    # ==================== 筛选器 ====================

    def make_filters(self):
        """标准筛选器：类型/地区/语言/年份/字母/排序（12段格式消费）"""
        def opts(names):
            return [{"n": n, "v": "" if n == "全部" else n} for n in names]

        common = [
            {"key": "class", "name": "类型", "value": opts(self.TYPE_OPTS)},
            {"key": "area", "name": "地区", "value": opts(self.AREA_OPTS)},
            {"key": "lang", "name": "语言", "value": opts(self.LANG_OPTS)},
            {"key": "year", "name": "年份", "value": opts(self.YEAR_OPTS)},
            {"key": "by", "name": "排序", "value": [{"n": n, "v": v} for n, v in self.BY_OPTS]},
            {"key": "letter", "name": "字母",
             "value": [{"n": n, "v": "" if n == "全部" else n} for n in self.LETTER_OPTS]},
        ]
        return {tid: [dict(x) for x in common] for tid in self.ALIAS}

    def build_category_url(self, tid, pg, extend):
        """构建分类 URL（12 段格式）。无筛选页码在段8；带筛选时页码仍段8。
        段位: 0分类 1地区 2排序 3类型 4语言 5字母 6字母2 7空 8页码 9空 10空 11年份
        """
        alias = self.ALIAS.get(str(tid), str(tid))
        ext = extend if isinstance(extend, dict) else {}
        area = str(ext.get("area", "") or "")
        by = str(ext.get("by", "") or "")
        cls = str(ext.get("class", "") or "")
        lang = str(ext.get("lang", "") or "")
        year = str(ext.get("year", "") or "")
        letter = str(ext.get("letter", "") or "")
        pg = str(int(pg) if str(pg).isdigit() else 1)

        if area == "0-9":
            letter = "0-9"
        # 字母拆两段（0-9 拆分）
        let1, let2 = "", ""
        if letter:
            if letter == "0-9":
                let1, let2 = "0", "9"
            else:
                let1 = letter

        segs = [alias, area, by, cls, lang, let1, let2, "", pg, "", "", year]
        return self.host + "/vodshow/" + "-".join(segs) + "/"

    # ==================== 列表解析 ====================

    def parse_list(self, html):
        """解析 module-poster-item 卡片列表"""
        videos, seen = [], set()
        # 卡片块匹配（含标题/图片/角标）
        pattern = (r'<a href="(/voddetail/(\d+)/)" title="([^"]*)"'
                   r' class="module-poster-item module-item">(.*?)</a>')
        for m in re.finditer(pattern, html, re.DOTALL):
            vid = m.group(2)
            if vid in seen:
                continue
            title = self.clean(m.group(3))
            if not title:
                continue
            block = m.group(4)
            # 图片: data-original 优先，src 兜底
            pic = ""
            pm = re.search(r'data-original="([^"]+)"', block)
            if pm:
                pic = pm.group(1)
            else:
                pm = re.search(r'src="([^"]+)"', block)
                if pm:
                    pic = pm.group(1)
            # 角标
            remark = ""
            rm = re.search(r'module-item-note[^>]*>([^<]*)<', block)
            if rm:
                remark = self.clean(rm.group(1))
            seen.add(vid)
            videos.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": self.build_url(pic),
                "vod_remarks": remark,
            })
        return videos

    def parse_pagecount(self, html):
        """从页面提取最大页码（---N--- 格式均为页码链接）"""
        pages = [int(p) for p in re.findall(r'---(\d+)---', html) if p.isdigit()]
        return max(pages) if pages else 1

    # ==================== 首页 ====================

    def homeContent(self, filter=False):
        result = {
            "class": self.CLASSES,
            "filters": self.make_filters(),
            "list": [],
        }
        try:
            html = self.getHtml(self.host + "/")
            result["list"] = self.parse_list(html)[:30]
        except Exception as e:
            print("homeContent error: %s" % e)
        return result

    def homeVideoContent(self):
        try:
            html = self.getHtml(self.host + "/")
            return {"list": self.parse_list(html)[:30]}
        except Exception as e:
            print("homeVideoContent error: %s" % e)
            return {"list": []}

    # ==================== 分类 ====================

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg) if str(pg).isdigit() else 1
            url = self.build_category_url(tid, page, extend)
            html = self.getHtml(url)
            videos = self.parse_list(html)

            # 降级回退：带筛选无结果 → 无筛选 URL
            if not videos and extend:
                fallback = self.build_category_url(tid, page, {})
                if fallback != url:
                    html = self.getHtml(fallback)
                    videos = self.parse_list(html)

            pagecount = self.parse_pagecount(html)
            # 页码提取兜底：有内容且 >=40 条则认为有下一页
            if pagecount <= page and len(videos) >= 40:
                pagecount = page + 1

            return {
                "list": videos,
                "page": page,
                "pagecount": pagecount,
                "limit": 40,
                "total": pagecount * 40,
            }
        except Exception as e:
            print("categoryContent error: %s" % e)
            return {"list": [], "page": int(pg) if str(pg).isdigit() else 1,
                    "pagecount": 1, "limit": 40, "total": 0}

    # ==================== 详情 ====================

    def detailContent(self, ids):
        result = {"list": []}
        try:
            vid = str(ids[0]) if isinstance(ids, list) and ids else str(ids)
            # 兼容带路径的 id
            m = re.search(r'(\d+)', vid)
            if not m:
                return result
            vid = m.group(1)
            url = self.host + "/voddetail/%s/" % vid
            html = self.getHtml(url)
            if not html:
                return result

            vod = {
                "vod_id": vid, "vod_name": "", "vod_pic": "",
                "vod_actor": "", "vod_director": "", "vod_content": "",
                "vod_year": "", "vod_area": "", "vod_remarks": "",
                "type_name": "", "vod_play_from": "", "vod_play_url": "",
            }

            # 标题
            hm = re.search(r'<h1[^>]*>([^<]*)</h1>', html)
            if hm:
                vod["vod_name"] = self.clean(hm.group(1))
            if not vod["vod_name"]:
                tm = re.search(r'<title>([^<]*)</title>', html)
                if tm:
                    vod["vod_name"] = self.clean(tm.group(1).split("_")[0].split("-")[0])

            # 海报（详情页主图，跳过图标类）
            pm = re.search(r'<img[^>]*class="[^"]*lazy[^"]*"[^>]*(?:data-original|src)="(https?://[^"]+)"', html)
            if pm:
                pic = pm.group(1)
                if "/mxtheme/" not in pic:
                    vod["vod_pic"] = pic

            # 导演/主演/简介
            def info_item(name):
                m2 = re.search(
                    r'<span class="module-info-item-title">%s：</span>'
                    r'<div class="module-info-item-content">([\s\S]*?)</div>' % name,
                    html)
                if m2:
                    return self.clean(m2.group(1))
                return ""

            vod["vod_director"] = info_item("导演")
            vod["vod_actor"] = info_item("主演")

            cm = re.search(r'module-info-introduction-content[^>]*>([\s\S]*?)</div>', html)
            if cm:
                vod["vod_content"] = self.clean(cm.group(1))[:500]

            # 播放线路：tab 名与集数块按顺序对齐
            tabs = re.findall(r'module-tab-item tab-item[^>]*data-dropdown-value="([^"]*)"', html)
            blocks = re.findall(r'<div class="module-play-list[^"]*"[^>]*>([\s\S]*?)</div>\s*</div>', html)

            play_from, play_urls = [], []
            n = min(len(tabs), len(blocks))
            if n == 0:
                # 兜底：整个页面提取所有集数
                eps = []
                for m3 in re.finditer(
                        r'class="module-play-list-link"[^>]*href="/vodplay/(\d+)-(\d+)-(\d+)/"[^>]*>'
                        r'<span>([^<]*)</span>', html):
                    name = m3.group(4).strip()
                    eps.append("%s$%s-%s-%s" % (name, m3.group(1), m3.group(2), m3.group(3)))
                if eps:
                    play_from.append("默认")
                    play_urls.append("#".join(eps))
            else:
                for i in range(n):
                    tab_name = self.clean(tabs[i])
                    if not tab_name:
                        continue
                    eps = []
                    for m3 in re.finditer(
                            r'class="module-play-list-link"[^>]*href="/vodplay/(\d+)-(\d+)-(\d+)/"[^>]*>'
                            r'<span>([^<]*)</span>', blocks[i]):
                        name = m3.group(4).strip() or ("第%d集" % (len(eps) + 1))
                        eps.append("%s$%s-%s-%s" % (name, m3.group(1), m3.group(2), m3.group(3)))
                    if eps:
                        play_from.append(tab_name)
                        play_urls.append("#".join(eps))

            vod["vod_play_from"] = "$$$".join(play_from)
            vod["vod_play_url"] = "$$$".join(play_urls)
            result["list"] = [vod]
        except Exception as e:
            print("detailContent error: %s" % e)
            import traceback
            traceback.print_exc()
        return result

    # ==================== 搜索 ====================

    def searchContent(self, key, quick, pg="1"):
        result = {"list": [], "page": int(pg) if str(pg).isdigit() else 1}
        try:
            # 真实搜索路由（与首页"大家都在搜"一致）:
            #   /vodsearch/wd/{关键词}/   或  /vodsearch/?wd=关键词
            url = self.host + "/vodsearch/wd/%s/" % urllib.parse.quote(str(key))
            html = self.getHtml(url)
            videos, seen = [], set()
            if _HAS_BS4:
                # ===== 修复：BS4 按卡片选择器解析（旧正则被内层 module-card-item-class
                # 的 </div> 过早截断，导致搜索永远拿不到结果）=====
                soup = BeautifulSoup(html, "html.parser")
                for card in soup.select("div.module-card-item.module-item"):
                    a = card.select_one('a[href*="/voddetail/"]')
                    if not a:
                        continue
                    m = re.search(r'/voddetail/(\d+)/', a.get("href", ""))
                    if not m:
                        continue
                    vid = m.group(1)
                    if vid in seen:
                        continue
                    # 标题：.module-card-item-title strong 优先，img alt 兜底
                    strong = card.select_one(".module-card-item-title strong")
                    title = strong.get_text(strip=True) if strong else ""
                    if not title:
                        img_t = card.select_one("img")
                        title = (img_t.get("alt") or "") if img_t else ""
                    if not title:
                        continue
                    # 图片：data-original 优先，src 兜底
                    img = card.select_one("img")
                    pic = (img.get("data-original") or img.get("src") or "") if img else ""
                    # 角标
                    note = card.select_one(".module-item-note")
                    remark = note.get_text(strip=True) if note else ""
                    seen.add(vid)
                    videos.append({
                        "vod_id": vid,
                        "vod_name": title,
                        "vod_pic": self.build_url(pic),
                        "vod_remarks": remark,
                    })
            else:
                # 无 BS4 兜底：整卡匹配到 footer 边界（避开内层 div 截断）
                for m in re.finditer(
                        r'<div class="module-card-item module-item">([\s\S]*?)'
                        r'<div class="module-card-item-footer"', html):
                    block = m.group(1)
                    lm = re.search(r'href="(/voddetail/(\d+)/)"', block)
                    if not lm:
                        continue
                    vid = lm.group(2)
                    if vid in seen:
                        continue
                    tm = re.search(r'module-card-item-title[^>]*>.*?<strong>([^<]*)</strong>', block, re.DOTALL)
                    title = self.clean(tm.group(1)) if tm else ""
                    if not title:
                        tm2 = re.search(r'alt="([^"]*)"', block)
                        title = self.clean(tm2.group(1)) if tm2 else ""
                    if not title:
                        continue
                    pm = re.search(r'data-original="([^"]+)"', block)
                    pic = pm.group(1) if pm else ""
                    rm = re.search(r'module-item-note[^>]*>([^<]*)<', block)
                    remark = self.clean(rm.group(1)) if rm else ""
                    seen.add(vid)
                    videos.append({
                        "vod_id": vid,
                        "vod_name": title,
                        "vod_pic": self.build_url(pic),
                        "vod_remarks": remark,
                    })
            result["list"] = videos
            result["pagecount"] = 1
            result["limit"] = len(videos)
            result["total"] = len(videos)
        except Exception as e:
            print("searchContent error: %s" % e)
        return result

    # ==================== 播放 ====================

    def playerContent(self, flag, id, vipFlags=None):
        # header 用 JSON 字符串（兼容各 TVBox/影视仓版本，playUrl 必须为字符串）
        hd_str = json.dumps(self.playHeader(), ensure_ascii=False)
        result = {"parse": 1, "playUrl": "", "url": id, "header": hd_str}
        try:
            play_id = str(id)
            # id 形如 "399923-1-1"（短ID）或 "https://host/vodplay/399923-1-1/"（完整URL）
            # 统一提取前三个数字段
            nums = re.findall(r'\d+', play_id)
            if len(nums) < 3:
                return result
            vid, sid, nid = nums[0], nums[1], nums[2]
            url = self.host + "/vodplay/%s-%s-%s/" % (vid, sid, nid)
            html = self.getHtml(url)
            if not html:
                return result

            # 大括号计数提取 player_aaaa
            pos = html.find("player_aaaa")
            if pos == -1:
                return result
            st = html.find("{", pos)
            depth = 0
            in_str = False
            esc = False
            end = -1
            for i in range(st, len(html)):
                c = html[i]
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = not in_str
                elif not in_str:
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
            if end == -1:
                return result

            player_data = json.loads(html[st:end + 1])
            enc_url = player_data.get("url", "")
            if not enc_url:
                return result

            # encrypt=1: percent-encoding 混淆，unquote 即直链
            # 兼容 encrypt=0/2（按需扩展）
            try:
                encrypt = int(player_data.get("encrypt") or 0)
            except Exception:
                encrypt = 0
            real_url = enc_url
            if encrypt == 1:
                real_url = urllib.parse.unquote(enc_url)
            elif encrypt == 2:
                try:
                    import base64
                    real_url = urllib.parse.unquote(base64.b64decode(enc_url).decode("utf-8", "ignore"))
                except Exception:
                    real_url = urllib.parse.unquote(enc_url)
            real_url = real_url.replace("\\/", "/")
            if real_url.startswith("http") and self.isVideoFormat(real_url):
                return {"parse": 0, "playUrl": "", "url": real_url,
                        "header": hd_str}
            # 非直链（如网页源）→ 交解析器
            return {"parse": 1, "playUrl": "", "url": real_url,
                    "header": hd_str}
        except Exception as e:
            print("playerContent error: %s" % e)
            import traceback
            traceback.print_exc()
        return result


# ==================== 本地自检 ====================
if __name__ == "__main__":
    sp = Spider()
    sp.init("")
    print("=" * 56)
    print("壹秀影视 脚本自检")
    print("=" * 56)
    hc = sp.homeContent(True)
    print("[首页] 分类%d个 | 筛选键%d组 | 推荐%d条" % (
        len(hc["class"]), len(hc["filters"]), len(hc["list"])))
    if hc["list"]:
        print("  首条: %s (id=%s)" % (hc["list"][0]["vod_name"], hc["list"][0]["vod_id"]))
    cat = sp.categoryContent("1", "1", True, {})
    print("[分类-电影] %d条 | 首条: %s" % (
        len(cat["list"]), cat["list"][0]["vod_name"] if cat["list"] else "-"))
    # 筛选测试
    cat2 = sp.categoryContent("1", "1", True, {"area": "美国", "by": "time"})
    print("[分类-美国筛选] %d条" % len(cat2["list"]))
    if cat["list"]:
        v = cat["list"][0]
        d = sp.detailContent([v["vod_id"]])
        if d["list"]:
            dv = d["list"][0]
            print("[详情] 《%s》 线路=%s" % (dv["vod_name"][:20], dv["vod_play_from"][:40]))
            pu = dv["vod_play_url"]
            print("  首线路集数: %d | 示例: %s" % (len(pu.split("$$$")[0].split("#")) if pu else 0,
                                            pu.split("$$$")[0].split("#")[0] if pu else "-"))
    s = sp.searchContent("功夫女足", False, "1")
    print("[搜索] %d条 | %s" % (len(s["list"]), s["list"][0]["vod_name"] if s["list"] else "-"))
    print("=" * 56)
    print("完成")
