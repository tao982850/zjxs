#!/usr/bin/env python3
#QQ群:807916734
# -*- coding: utf-8 -*-
"""
====================================================================
 奈飞工厂 (netflixgc.tv) 爬虫插件 - TVBox / 影视仓 / FongMi
====================================================================
【站点特性】
  - 苹果CMS (MacCMS) + dsn2 模板, utf-8
  - 列表: /index.php/ajax/data 免验证码 JSON ✅
  - 详情: /voddetail/{id}.html (anthology-tab + swiper-slide 线路)
  - 播放: /vodplay/{id}-{sid}-{nid}.html
          player_aaaa encrypt=2 → base64 → URL解码 → 真实 m3u8 ✅
  - 搜索: /vodsearch/{key}----------{page}---.html 免验证码 ✅

【encrypt=2 解密链】(已实测验证)
  url = base64.b64decode(enc_url) → urllib.parse.unquote → https://v14.wsyzym3u8.com/.../index.m3u8

【兼容性】
  - Python 2.7 / 3 双兼容
  - 仅依赖 requests
====================================================================
"""

from __future__ import print_function

import re
import json
import base64
import requests

try:
    from urllib.parse import quote, unquote
except ImportError:
    from urllib import quote, unquote

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    BaseSpider = object


def _clean_pic(pic):
    """清理图片 URL：HTML实体 + 百度代理还原 + 相对路径补全"""
    if not pic:
        return ''
    pic = pic.replace('\\/', '/').replace('&amp;', '&').strip()
    if 'baidu.com' in pic:
        m = re.search(r'src=([^&]+)', pic)
        if m:
            native = m.group(1).strip()
            if native.startswith('//'):
                native = 'https:' + native
            elif not native.startswith('http'):
                native = 'https://' + native
            return native
    if pic.startswith('//'):
        pic = 'https:' + pic
    return pic


class Spider(BaseSpider):
    """奈飞工厂 (netflixgc.tv) 爬虫"""

    HOST = "https://netflixgc.tv"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    CLASSES = [
        {"type_id": "1", "type_name": "电影"},
        {"type_id": "2", "type_name": "连续剧"},
        {"type_id": "3", "type_name": "动漫"},
        {"type_id": "23", "type_name": "综艺"},
        {"type_id": "24", "type_name": "纪录片"},
    ]

    # 详情页线路导航（swiper-slide 前 7 个是导航，跳过）
    NAV_NAMES = set(['首页', '电影', '连续剧', '纪录片', '漫剧', '综艺', '直播'])

    def __init__(self):
        try:
            super(Spider, self).__init__()
        except Exception:
            pass
        try:
            self.session = requests.Session()
            self.session.headers.update(self.HEADERS)
        except Exception:
            self.session = None

    def _get(self, url, timeout=15, headers=None):
        if not str(url).startswith('http'):
            url = self.HOST + str(url)
        h = self.HEADERS
        if headers:
            h = dict(self.HEADERS)
            h.update(headers)
        try:
            if self.session is not None:
                return self.session.get(url, headers=h, timeout=timeout)
            return requests.get(url, headers=h, timeout=timeout)
        except Exception:
            if self.session is not None:
                return self.session.get(url, headers=h)
            return requests.get(url, headers=h)

    def init(self, extend):
        pass

    def getName(self):
        return "奈飞工厂"

    def getDependence(self):
        return ["requests"]

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(m3u8|mp4|flv|mkv)(\?|$)", str(url), re.I))

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return [404, "text/plain", "Not Found"]

    def liveContent(self, url):
        return {"list": []}

    def action(self, action):
        return {}

    def destroy(self):
        pass

    # ==================== 列表 ====================
    @staticmethod
    def _ds_vod_list(tid, page, extend=None, limit=40):
        """分类列表核心接口：POST /index.php/ds_api/vod（免验证码 JSON）
        ⚠️ 修复：原 /index.php/ajax/data 接口的 tid 参数被站点忽略，
           所有分类返回同一批数据（电影/连续剧/动漫内容全一样）。
           逆向自模板 script.js 的 ajaxList.list.vod()：
           POST ds_api/vod，参数取 #dataList 的 data-* 属性，
           支持 type/class/area/year/lang/version/state/letter/time/by/page
        """
        try:
            params = {'type': str(tid), 'page': str(page)}
            if extend:
                for k in ('class', 'area', 'year', 'lang', 'letter', 'by',
                          'version', 'state', 'time', 'weekday', 'level'):
                    v = (extend.get(k) or '') if isinstance(extend, dict) else ''
                    if v:
                        params[k] = str(v)
            r = requests.post('https://netflixgc.tv/index.php/ds_api/vod',
                              data=params,
                              headers=dict(Spider.HEADERS, **{
                                  'Content-Type': 'application/x-www-form-urlencoded',
                                  'X-Requested-With': 'XMLHttpRequest',
                                  'Referer': 'https://netflixgc.tv/vodshow/%s-----------.html' % tid}),
                              timeout=12)
            d = r.json()
            if d.get('code') != 1:
                return [], 1
            lst = []
            for v in d.get('list', []):
                lst.append({
                    "vod_id": str(v.get('vod_id', '')),
                    "vod_name": v.get('vod_name', ''),
                    "vod_pic": _clean_pic(v.get('vod_pic', '')),
                    "vod_remarks": v.get('vod_remarks', ''),
                    "vod_year": str(v.get('vod_year', '')),
                    "vod_area": v.get('vod_area', ''),
                })
            return lst, int(d.get('pagecount', 1) or 1)
        except Exception:
            return [], 1

    # 筛选选项（逆向自 /vodshow/ 页筛选导航）
    FILTER_OPTS = {
        'class': ["全部", "喜剧", "爱情", "恐怖", "动作", "科幻", "剧情", "犯罪",
                  "奇幻", "悬疑", "惊悚", "家庭", "冒险", "同性", "运动", "战争", "灾难"],
        'area': ["全部", "中国", "大陆", "香港", "台湾", "美国", "韩国", "日本", "泰国",
                 "新加坡", "马来西亚", "印度", "英国", "法国", "瑞典", "瑞士", "乌克兰",
                 "加拿大", "西班牙", "俄罗斯", "其它"],
        'lang': ["全部", "中文", "粤语", "闽南语", "英语", "日语", "韩语", "法语",
                 "俄语", "德语", "泰语", "瑞典语", "印度语"],
        'letter': ["全部"] + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + ["0-9"],
    }
    FILTER_YEARS = ["全部"] + [str(y) for y in range(2026, 1989, -1)] + ["其他"]

    @staticmethod
    def _make_filters():
        """构建 TVBox 标准筛选器（6 组）"""
        def opts(names):
            return [{"n": n, "v": "" if n == "全部" else n} for n in names]

        common = [
            {"key": "class", "name": "类型", "value": opts(Spider.FILTER_OPTS['class'])},
            {"key": "area", "name": "地区", "value": opts(Spider.FILTER_OPTS['area'])},
            {"key": "year", "name": "年份", "value": opts(Spider.FILTER_YEARS)},
            {"key": "lang", "name": "语言", "value": opts(Spider.FILTER_OPTS['lang'])},
            {"key": "letter", "name": "字母", "value": opts(Spider.FILTER_OPTS['letter'])},
            {"key": "by", "name": "排序",
             "value": [{"n": n, "v": v} for n, v in [("最新", "time"), ("最热", "hits"), ("评分", "score")]]},
        ]
        return {c["type_id"]: [dict(x) for x in common] for c in Spider.CLASSES}

    @staticmethod
    def _parse_cards(html):
        """HTML 卡片解析（兜底：/vodshow/ 与 /vodsearch/ 页）
        兼容两种结构:
          ① <a href="/voddetail/1.html" title="片名">
          ② <a href="/voddetail/1.html"><h3 class="slide-info-title">片名</h3>"""
        videos, seen = [], set()
        for m in re.finditer(r'<a[^>]*href="(/voddetail/(\d+)\.html)"[^>]*>([\s\S]*?)</a>', html):
            vid = m.group(2)
            if vid in seen:
                continue
            seg = m.group(3)
            # 标题：title 属性 或 内部 h3
            name = ''
            tm = re.search(r'<a[^>]*title="([^"]*)"', m.group(0))
            if tm:
                name = tm.group(1).strip()
            if not name:
                hm = re.search(r'<h3[^>]*class="[^"]*slide-info-title[^"]*"[^>]*>([^<]*)</h3>', seg)
                if hm:
                    name = hm.group(1).strip()
            if not name:
                continue
            seen.add(vid)
            pm = re.search(r'<img[^>]*(?:data-src|data-original|src)="([^"]*)"', seg)
            pic = _clean_pic(pm.group(1)) if pm else ''
            rm = re.search(r'class="[^"]*(?:pic-text|remark|note|time)[^"]*"[^>]*>([^<]*)', seg)
            remark = rm.group(1).strip() if rm else ''
            videos.append({"vod_id": vid, "vod_name": name, "vod_pic": pic, "vod_remarks": remark})
        return videos

    # ==================== 首页 ====================
    def homeContent(self, filter=False):
        return {"class": self.CLASSES, "filters": self._make_filters()}

    def homeVideoContent(self):
        try:
            lst, _ = self._ds_vod_list('0', 1)
            if lst:
                return {"list": lst}
        except Exception:
            pass
        try:
            html = self._get('/').text
            return {"list": self._parse_cards(html)[:20]}
        except Exception:
            return {"list": []}

    # ==================== 分类 ====================
    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        tid = str(tid)
        # 主路径：ds_api/vod（支持分类 + 筛选 + 分页）
        try:
            items, pagecount = self._ds_vod_list(tid, page, extend)
            if items:
                return {"list": items, "page": page, "pagecount": pagecount,
                        "limit": 40, "total": pagecount * 40}
        except Exception:
            pass
        # 兜底：筛选后无结果 → 去掉筛选重试
        try:
            items, pagecount = self._ds_vod_list(tid, page, None)
            if items:
                return {"list": items, "page": page, "pagecount": pagecount,
                        "limit": 40, "total": pagecount * 40}
        except Exception:
            pass
        # 最后兜底：vodtype 服务端渲染页
        try:
            url = '%s/vodtype/%s.html' % (self.HOST, tid)
            html = self._get(url).text
            items = self._parse_cards(html)
            if items:
                return {"list": items, "page": page, "pagecount": 1,
                        "limit": 24, "total": 9999}
        except Exception:
            pass
        return {"list": [], "page": page, "pagecount": page, "limit": 40, "total": 0}

    # ==================== 详情 ====================
    def detailContent(self, ids):
        try:
            vid = ids[0].split(',')[0].strip() if isinstance(ids, list) else str(ids).split(',')[0]
        except Exception:
            return {"list": []}
        try:
            html = self._get('/voddetail/%s.html' % vid).text
        except Exception:
            return {"list": []}
        if not html:
            return {"list": []}

        # 标题（dsn2: <title>片名_类型 - 站名</title>，页面无 h1 时用这个）
        vod_name = ''
        mt = re.search(r'<h1[^>]*>([^<]*)</h1>', html)
        if mt:
            vod_name = mt.group(1).strip()
        if not vod_name:
            mt2 = re.search(r'<title>([^_<]*?)(?:_[^<]*)?\s*-\s*奈飞工厂', html)
            if mt2:
                vod_name = mt2.group(1).strip()

        # 海报
        pic = ''
        pm = re.search(r'<img[^>]*class="[^"]*lazyload[^"]*"[^>]*(?:data-src|src)="([^"]*)"', html)
        if not pm:
            pm = re.search(r'<img[^>]*(?:data-src|src)="(https?://[^"]*(?:upload|pic)[^"]*)"', html)
        if pm:
            pic = _clean_pic(pm.group(1))

        # 简介
        content = ''
        cm = re.search(r'id="height_limit"[^>]*>([\s\S]*?)</div>', html)
        if cm:
            content = re.sub(r'<[^>]+>', '', cm.group(1)).strip()
        if not content:
            cm2 = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', html)
            content = cm2.group(1).strip() if cm2 else ''
        content = re.sub(r'\s+', ' ', content).strip()

        # 演员/导演
        actor = director = ''
        am = re.search(r'主演[:：]?</[^>]*>([\s\S]*?)<', html)
        if am:
            actor = re.sub(r'<[^>]+>', '', am.group(1)).strip()
        dm = re.search(r'导演[:：]?</[^>]*>([\s\S]*?)<', html)
        if dm:
            director = re.sub(r'<[^>]+>', '', dm.group(1)).strip()

        # 线路名（swiper-slide，跳过导航）与选集块（anthology-list-box）一一对应
        play_from, play_url = [], []
        try:
            slides = re.findall(r'class="swiper-slide"[^>]*>([\s\S]*?)</a>', html)
            line_names = []
            for s in slides:
                txt = re.sub(r'<[^>]+>', ' ', s)
                txt = txt.replace('&nbsp;', ' ').replace('\xa0', ' ')
                txt = re.sub(r'\s+', ' ', txt).strip()
                # 去尾部集数badge（如 "蓝光-3" → "蓝光"）
                txt = re.sub(r'[-－—・·\s]*\d+$', '', txt).strip()
                if txt and txt not in self.NAV_NAMES and txt not in line_names:
                    line_names.append(txt)
            blocks = re.findall(r'class="anthology-list-box[^"]*"[^>]*>([\s\S]*?)</div>\s*</div>', html)
            for i, b in enumerate(blocks):
                eps = re.findall(r'href="(/vodplay/[^"]+\.html)"[^>]*>([^<]*)', b)
                if eps:
                    name = line_names[i] if i < len(line_names) and line_names[i] else ('线路%d' % (i + 1))
                    play_from.append(name)
                    play_url.append('#'.join('%s$%s' % (n.strip() or ('第%d集' % (j + 1)), h)
                                             for j, (h, n) in enumerate(eps)))
        except Exception:
            pass

        vod = {
            "vod_id": vid, "vod_name": vod_name, "vod_pic": pic,
            "type_name": "", "vod_year": "", "vod_area": "", "vod_remarks": "",
            "vod_actor": actor, "vod_director": director, "vod_content": content,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }
        return {"list": [vod]}

    # ==================== 搜索（免验证码） ====================
    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        try:
            url = '%s/vodsearch/%s----------%d---.html' % (self.HOST, quote(str(key)), page)
            r = self._get(url)
            html = r.text if r is not None else ''
            if html and 'mac_verify' not in html:
                items = self._parse_cards(html)
                if items:
                    return {"list": items, "page": page, "pagecount": 1,
                            "limit": len(items), "total": len(items)}
        except Exception:
            pass
        return {"list": [], "page": page, "pagecount": 1, "limit": 0, "total": 0}

    # ==================== 播放（encrypt=2 解密 + NBY 特殊线路解析器） ====================
    # 线路→解析器映射（逆向自 /static/js/playerconfig.js，实测确认）
    PARSE_API = "https://cjbfq.netflixgc.tv/player/ec.php?code=netflix&if=1&url="

    def _decrypt_url(self, enc):
        """encrypt=2 第一层：base64 → URL 解码 → 真实地址 或 NBY 加密串"""
        try:
            step1 = base64.b64decode(enc).decode('utf-8', 'ignore')
            return unquote(step1)
        except Exception:
            return ''

    def playerContent(self, flag, id, vipFlags):
        try:
            play_id = str(id)
            url = play_id if play_id.startswith('http') else self.HOST + play_id
            r = requests.get(url, headers=self.HEADERS, timeout=15)
            html = r.text
            m = re.search(r'player_aaaa=(\{.*?\})\s*</script>', html, re.S)
            if not m:
                m = re.search(r'player_aaaa=(\{.*?\})', html, re.S)
            if m:
                pd = json.loads(m.group(1).replace('\\/', '/'))
                enc_url = pd.get('url', '')
                encrypt = pd.get('encrypt', 0)
                real = ''
                if encrypt == 2:
                    real = self._decrypt_url(enc_url)          # base64 + URL解码
                elif encrypt == 0:
                    real = enc_url
                elif encrypt == 1:
                    try:
                        real = unquote(enc_url)
                    except Exception:
                        real = enc_url
                if real and self.isVideoFormat(real):
                    # 直链：parse=0 直出
                    return {"parse": 0, "url": real,
                            "header": {"User-Agent": self.HEADERS["User-Agent"],
                                       "Referer": self.HOST + "/"}}
                if real and re.match(r'^[A-Za-z0-9]+-', real) and 'AES' in real:
                    # NBY 等特殊线路：第一层解出加密串 → 交站方解析器（parse=1 + playUrl）
                    return {"parse": 1, "playUrl": self.PARSE_API, "url": real,
                            "header": {"User-Agent": self.HEADERS["User-Agent"],
                                       "Referer": self.HOST + "/"}}
                if real and real.startswith('http'):
                    return {"parse": 1, "url": real,
                            "header": {"User-Agent": self.HEADERS["User-Agent"],
                                       "Referer": self.HOST + "/"}}
            # 兜底：页面裸 m3u8
            mm = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', html)
            if mm:
                return {"parse": 0, "url": mm.group(1),
                        "header": {"User-Agent": self.HEADERS["User-Agent"],
                                   "Referer": self.HOST + "/"}}
            return {"parse": 1, "url": url, "header": self.HEADERS}
        except Exception:
            return {"parse": 1, "url": str(id), "header": self.HEADERS}


# ==================== 本地自检 ====================
if __name__ == "__main__":
    sp = Spider()
    print("=" * 56)
    print("奈飞工厂 netflixgc.tv 脚本自检 (v2 修复版)")
    print("=" * 56)
    print("[首页] 分类 %d 个 | 筛选键 %d 组" % (
        len(sp.homeContent()["class"]), len(sp.homeContent()["filters"])))
    hv = sp.homeVideoContent()
    print("[推荐] %d 条 | 首条: %s" % (len(hv["list"]), hv["list"][0]["vod_name"] if hv["list"] else "-"))
    lists = []
    for tid, tname in [("1", "电影"), ("2", "连续剧"), ("3", "动漫")]:
        cat = sp.categoryContent(tid, "1", False, {})
        lists.append(cat["list"])
        print("[分类-%s] %d 条 | 首条: %s | pagecount=%s" % (
            tname, len(cat["list"]),
            cat["list"][0]["vod_name"] if cat["list"] else "-", cat["pagecount"]))
    # 分类区分验证
    same = len(lists) == 3 and lists[0] and lists[1] and lists[0][0]['vod_id'] == lists[1][0]['vod_id']
    print("[分类区分] %s" % ("⚠️ 仍相同" if same else "✅ 各分类内容不同"))
    # 筛选验证
    cat_f = sp.categoryContent("1", "1", False, {"class": "喜剧", "area": "美国", "year": "2025"})
    print("[筛选-喜剧+美国+2025] %d 条 | 首条: %s" % (
        len(cat_f["list"]), cat_f["list"][0]["vod_name"] if cat_f["list"] else "-"))
    if lists and lists[0]:
        v = lists[0][0]
        d = sp.detailContent([v["vod_id"]])
        if d["list"]:
            dv = d["list"][0]
            print("[详情] %s" % dv["vod_name"][:30])
            pf = dv["vod_play_from"].split('$$$') if dv["vod_play_from"] else []
            pu = dv["vod_play_url"].split('$$$') if dv["vod_play_url"] else []
            print("  线路: %s" % str(pf[:6]))
            for i, u in enumerate(pu[:3]):
                print("  [%s] 集数=%d 首条=%s" % (pf[i] if i < len(pf) else '?',
                                               len(u.split('#')), u.split('#')[0][:60] if u else ''))
            if pu and pu[0]:
                first_ep = pu[0].split('#')[0].split('$')[-1]
                p = sp.playerContent("", first_ep, None)
                print("[播放] parse=%s url=%s" % (p.get("parse"), str(p.get("url"))[:70]))
    s = sp.searchContent("金特", False, "1")
    print("[搜索] %d 条 | 首条: %s" % (len(s.get("list", [])),
                                   s["list"][0]["vod_name"] if s.get("list") else "-"))
    print("=" * 56)
    print("完成")
