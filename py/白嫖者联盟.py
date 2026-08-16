# -*- coding: utf-8 -*-
#QQ群:807916734
# ====================================================================
# 白嫖者联盟 (bpz.app) TVBox Spider - 修复版 v2
# ====================================================================
# 站点架构: React SPA + 自有 API (v1) + HMAC-SHA256 签名
#
# 【修复点 vs 旧版】
#   * 所有HTTP请求改用 self.fetch (TVBox标准方法, 兼容所有版本)
#   * 海报 fmt=webp → fmt=jpeg (TVBox不支持webp)
#   * 全分类筛选器 (8分类×2维 = 16组筛选)
#   * 播放: resolve API → m3u8直链 + 多线路
#   * 集数名 01/02 两位格式
# ====================================================================
import re
import sys
import json
import time
import hmac
import hashlib
import secrets
import urllib.parse

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        def fetch(self, url, headers=None, timeout=15, **kw):
            import requests
            return requests.get(url, headers=headers, timeout=timeout, verify=False)

HOST = "https://bpz.app"
PLAYER_HOST = "https://player.baipiaozhe.com"
NAME = "白嫖者联盟"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
SIGN_SECRET = "f39d73aa7a6426203cdee1ef17b31d3b7ea8c23f4c59c62a3a8aa0f39ee5e79d"

CATEGORIES = [
    {"type_id": "movie_nowplaying", "type_name": "最新电影"},
    {"type_id": "movie_hot",        "type_name": "热门电影"},
    {"type_id": "tv_domestic",      "type_name": "国产剧"},
    {"type_id": "tv_american",      "type_name": "欧美剧"},
    {"type_id": "tv_japanese",      "type_name": "日剧"},
    {"type_id": "tv_korean",        "type_name": "韩剧"},
    {"type_id": "tv_animation",     "type_name": "动漫"},
    {"type_id": "show",             "type_name": "综艺"},
]

# 电影分类筛选
_MOVIE_FILTERS = [
    {"key": "class", "name": "类型", "value": [
        {"n": "最新电影", "v": "movie_nowplaying"},
        {"n": "热门电影", "v": "movie_hot"},
        {"n": "高分电影", "v": "movie_high_score"},
        {"n": "冷门佳片", "v": "movie_hidden_gems"},
        {"n": "即将上映", "v": "movie_upcoming"},
    ]},
    {"key": "sort", "name": "排序", "value": [
        {"n": "默认", "v": ""},
        {"n": "最新", "v": "latest"},
        {"n": "热门", "v": "hot"},
        {"n": "评分", "v": "rating"},
    ]},
]

# 电视剧分类筛选
_TV_FILTERS = [
    {"key": "class", "name": "地区", "value": [
        {"n": "国产剧", "v": "tv_domestic"},
        {"n": "欧美剧", "v": "tv_american"},
        {"n": "日剧",   "v": "tv_japanese"},
        {"n": "韩剧",   "v": "tv_korean"},
    ]},
    {"key": "sort", "name": "排序", "value": [
        {"n": "默认", "v": ""},
        {"n": "最新", "v": "latest"},
        {"n": "热门", "v": "hot"},
        {"n": "评分", "v": "rating"},
    ]},
]

FILTERS = {
    "movie_nowplaying": _MOVIE_FILTERS,
    "movie_hot":        _MOVIE_FILTERS,
    "tv_domestic":      _TV_FILTERS,
    "tv_american":      _TV_FILTERS,
    "tv_japanese":      _TV_FILTERS,
    "tv_korean":        _TV_FILTERS,
    "tv_animation": [
        {"key": "sort", "name": "排序", "value": [
            {"n": "默认", "v": ""},
            {"n": "最新", "v": "latest"},
            {"n": "热门", "v": "hot"},
        ]},
    ],
    "show": [
        {"key": "sort", "name": "排序", "value": [
            {"n": "默认", "v": ""},
            {"n": "最新", "v": "latest"},
            {"n": "热门", "v": "hot"},
        ]},
    ],
}


def _sign_headers(method, url):
    """生成站点请求签名 headers"""
    ts = str(int(time.time() * 1000))
    nonce = secrets.token_hex(16)
    parsed = urllib.parse.urlparse(url)
    path_q = parsed.path + (("?" + parsed.query) if parsed.query else "")
    msg = "%s\n%s\n%s\n%s" % (method, path_q, ts, nonce)
    sig = hmac.new(SIGN_SECRET.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "User-Agent": UA,
        "Accept": "application/json",
        "x-ai-movie-timestamp": ts,
        "x-ai-movie-nonce": nonce,
        "x-ai-movie-signature": sig,
    }


def _fmt_ep(name):
    """集数名格式化: 第1集 → 01"""
    n = str(name or "").strip().replace(" ", "")
    m = re.search(r"第?([0-9]{1,2})\s*[集话期]$", n) or re.search(r"^第([0-9]{1,2})[集话期]?$", n)
    if m:
        v = int(m.group(1))
        return "%02d" % v if 0 < v < 100 else n
    if re.match(r"^\d{1,2}$", n):
        v = int(n)
        return "%02d" % v if v > 0 else n
    return n


def _fix_poster(url):
    """修复海报URL: webp → jpeg (TVBox不支持webp)"""
    if not url:
        return ""
    if "fmt=webp" in url:
        return url.replace("fmt=webp", "fmt=jpeg")
    return url


def _card_to_vod(card):
    vod_id = card.get("id") or card.get("work_id") or ""
    return {
        "vod_id": vod_id,
        "vod_name": (card.get("title") or "")[:80],
        "vod_pic": _fix_poster(card.get("poster_url") or card.get("backdrop_url") or ""),
        "vod_remarks": (card.get("remarks") or card.get("year") or "")[:20],
    }


class Spider(BaseSpider):
    def __init__(self):
        self.siteUrl = HOST
        self.headers = {"User-Agent": UA}

    def getName(self): return NAME
    def getDependence(self): return []
    def init(self, extend=''): pass
    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv|ts|mkv)(\?|$)', str(url), re.I))
    def manualVideoCheck(self): return False
    def action(self, action): return None
    def destroy(self): pass
    def localProxy(self, param): return [200, "video/MP2T", ""]

    # ---------- HTTP请求 (使用 self.fetch, TVBox标准方法) ----------
    def _get(self, url, timeout=15):
        """带签名GET请求, 返回str"""
        try:
            r = self.fetch(url, headers=_sign_headers("GET", url), timeout=timeout)
            return r.text or ""
        except Exception:
            return ""

    def _get_json(self, url, timeout=15):
        """带签名GET请求, 返回dict"""
        txt = self._get(url, timeout)
        if not txt:
            return None
        try:
            return json.loads(txt)
        except Exception:
            return None

    def _get_player_json(self, url, timeout=15):
        """播放器API GET (不需要签名)"""
        r = None
        try:
            r = self.fetch(url, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=timeout)
            return r.json()
        except Exception:
            try:
                if r is not None:
                    txt = r.text or ""
                    if txt:
                        return json.loads(txt)
            except Exception:
                pass
            return None

    # ---------- 首页分类 ----------
    def homeContent(self, filter):
        return {
            "class": CATEGORIES,
            "filters": FILTERS if filter else {},
        }

    # ---------- 推荐页 ----------
    def homeVideoContent(self):
        d = self._get_json("%s/v1/feed/home?scope=public&mode=preview&sections=3&cards=10" % HOST)
        cards = []
        if d:
            for sec in d.get("sections", []) or []:
                for c in sec.get("cards", []) or []:
                    cards.append(c)
        return {"list": [_card_to_vod(c) for c in cards[:40]]}

    # ---------- 分类页 ----------
    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            pg = int(pg) if pg else 1
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1

        key = str(tid)
        if extend and isinstance(extend, dict):
            sub = extend.get("class") or ""
            if sub:
                key = sub

        url = "%s/v1/browse/catalog?hot_list_key=%s&page=%d&limit=20" % (
            HOST, urllib.parse.quote(key), pg)
        d = self._get_json(url)
        cards = (d or {}).get("cards", []) or []
        pag = (d or {}).get("pagination") or {}
        has_more = bool(pag.get("has_more", False)) if pag else bool(cards)
        pagecount = 9999 if has_more else pg
        return {
            "list": [_card_to_vod(c) for c in cards],
            "page": pg,
            "pagecount": pagecount,
            "limit": 20,
            "total": 999999 if has_more else pg * 20,
        }

    # ---------- 详情页 ----------
    def detailContent(self, ids):
        items = []
        for vid in ids:
            vid = str(vid or "").strip()
            d = self._get_json("%s/v1/catalog/%s" % (HOST, urllib.parse.quote(vid, safe="_-")))
            if not d:
                items.append({"vod_id": vid, "vod_name": "[解析失败]",
                              "vod_play_url": "", "vod_pic": ""})
                continue

            vod_id = d.get("id") or vid
            title = d.get("title") or ""
            desc = d.get("description") or ""
            director = ",".join(d.get("directors") or [])
            actor = ",".join(d.get("actors") or [])
            year = d.get("year") or ""
            area = d.get("area") or ""
            lang = d.get("language") or ""
            genres = ",".join(d.get("genres") or [])[:40]
            remarks = d.get("remarks") or ""
            poster = _fix_poster(d.get("poster_url") or "")

            eps = d.get("episodes") or []

            # 获取所有播放线路 (resolve 第一集 → line_options)
            line_options = []
            first_token = ""
            if eps:
                first_token = (eps[0].get("token") or "").strip()
            if first_token:
                resolve_url = "%s/v1/playback/resolve/%s" % (
                    PLAYER_HOST, urllib.parse.quote(first_token))
                rd = self._get_player_json(resolve_url)
                if rd:
                    line_options = rd.get("line_options") or []

            # 排序: 官方源(default_priority=True)放最前, 内部按 preference_weight 降序
            #       非官方源随后, 按 preference_weight 降序 (站点综合质量权重)
            line_options.sort(key=lambda x: (
                0 if x.get("default_priority") else 1,    # 官方优先
                -(x.get("preference_weight") or 0),         # 权重降序
            ))

            # 构建多线路播放列表
            # TVBox格式: vod_play_from 用 $$$ 分隔线路, vod_play_url 用 $$$ 分隔线路, # 分隔集数
            # 每集格式: ep_title$token|play_from  (| 后面带线路标识)
            if line_options:
                play_from_list = []
                play_url_list = []
                for line in line_options:
                    pf = (line.get("play_from") or "").strip()
                    if not pf:
                        continue
                    name = line.get("provider_name") or line.get("label") or pf
                    play_from_list.append(name)
                    ep_urls = []
                    for e in eps:
                        token = (e.get("token") or "").strip()
                        if not token:
                            continue
                        ep_title = _fmt_ep(e.get("title") or e.get("display_name") or "")
                        ep_urls.append("%s$%s|%s" % (ep_title, token, pf))
                    if not ep_urls:
                        ep_urls.append("正片$%s|%s" % (vod_id, pf))
                    play_url_list.append("#".join(ep_urls))
                vod_play_from = "$$$".join(play_from_list)
                vod_play_url = "$$$".join(play_url_list)
            else:
                # 兜底: 单线路 (resolve API 不可用时)
                play_urls = []
                for e in eps:
                    token = (e.get("token") or "").strip()
                    if not token:
                        continue
                    ep_title = _fmt_ep(e.get("title") or e.get("display_name") or "")
                    play_urls.append("%s$%s" % (ep_title, token))
                if not play_urls:
                    play_urls.append("正片$%s" % vod_id)
                vod_play_from = "YJ源"
                vod_play_url = "#".join(play_urls)

            items.append({
                "vod_id": vod_id,
                "vod_name": title[:80],
                "vod_pic": poster,
                "vod_year": year,
                "vod_area": area,
                "vod_lang": lang,
                "vod_type": genres,
                "vod_director": director,
                "vod_actor": actor,
                "vod_remarks": remarks[:20],
                "vod_content": desc,
                "vod_play_from": vod_play_from,
                "vod_play_url": vod_play_url,
            })
        return {"list": items}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg="1"):
        try:
            kw = urllib.parse.quote(str(key or ""))
            d = self._get_json("%s/v1/suggest?q=%s&limit=20&mode=home" % (HOST, kw))
            out = []
            for s in (d or {}).get("suggestions", []) or []:
                target = s.get("target") or {}
                vid = target.get("variant_id") or s.get("id") or ""
                label = s.get("label") or ""
                if not vid or not label:
                    continue
                if label.endswith("演的电影") or "找相关" in label:
                    continue
                out.append({
                    "vod_id": vid,
                    "vod_name": label[:80],
                    "vod_pic": "",
                    "vod_remarks": (s.get("subtitle") or "")[:20],
                })
            return {"list": out, "page": 1}
        except Exception:
            return {"list": []}

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags):
        # id 格式: token 或 token|play_from
        raw = str(id or "").strip()
        token = raw
        play_from = ""
        if "|" in raw:
            parts = raw.split("|", 1)
            token = parts[0].strip()
            play_from = parts[1].strip()

        if token:
            # 带线路参数调用 resolve (获取指定线路的直链)
            if play_from:
                resolve_url = "%s/v1/playback/resolve/%s?play_from=%s" % (
                    PLAYER_HOST, urllib.parse.quote(token),
                    urllib.parse.quote(play_from))
            else:
                resolve_url = "%s/v1/playback/resolve/%s" % (
                    PLAYER_HOST, urllib.parse.quote(token))

            d = self._get_player_json(resolve_url)
            if d and d.get("url"):
                play_url = d["url"]
                if play_url.startswith("http"):
                    url_kind = (d.get("url_kind") or "").lower()
                    # m3u8 带 Referer (第三方CDN防盗链需要)
                    # mp4/unknown 不带 Referer (官方bytedance CDN会403拦截Referer)
                    if url_kind == "m3u8" or ".m3u8" in play_url.lower():
                        hdr = {"User-Agent": UA, "Referer": HOST + "/"}
                    else:
                        hdr = {"User-Agent": UA}
                    return {
                        "parse": 0,
                        "playUrl": "",
                        "url": play_url,
                        "header": json.dumps(hdr, ensure_ascii=False),
                        "jx": "0",
                        "msg": "",
                    }

        # 兜底: yjplayer 网页播放器
        if token:
            web_url = "%s/yjplayer.html?v=20260701-switch5&url=%s" % (
                PLAYER_HOST, urllib.parse.quote(token))
        else:
            web_url = HOST + "/"
        return {
            "parse": 1,
            "playUrl": "",
            "url": web_url,
            "header": json.dumps({"User-Agent": UA}, ensure_ascii=False),
            "jx": "0",
            "msg": "",
        }


# ==================== 本地自检 ====================
if __name__ == "__main__":
    print("=" * 60)
    print("%s 脚本自检 (多线路版)" % NAME)
    print("=" * 60)
    sp = Spider()
    hc = sp.homeContent(True)
    print("[首页] 分类%d个 | 筛选%d组" % (len(hc["class"]), len(hc["filters"])))
    hv = sp.homeVideoContent()
    print("[推荐] %d条 | 首条: %s" % (len(hv["list"]), hv["list"][0]["vod_name"] if hv["list"] else "无"))
    s = sp.searchContent("庆余年", False, 1)
    print("[搜索-庆余年] %d条 | 首条: %s" % (len(s["list"]), s["list"][0]["vod_name"] if s["list"] else "无"))
    if s["list"]:
        d = sp.detailContent([s["list"][0]["vod_id"]])
        if d["list"]:
            dv = d["list"][0]
            print("[详情] %s | 年份:%s" % (dv["vod_name"][:20], dv["vod_year"]))
            pf = dv["vod_play_from"]
            lines = pf.split("$$$")
            pu = dv["vod_play_url"]
            line_urls = pu.split("$$$")
            print("  线路数: %d" % len(lines))
            for i, ln in enumerate(lines):
                eps = line_urls[i].split("#") if i < len(line_urls) else []
                print("    %d. %-15s (%d集)" % (i+1, ln, len(eps)))
            # 测试前3条线路的播放
            print()
            for i in range(min(3, len(lines))):
                ln = lines[i]
                eps = line_urls[i].split("#") if i < len(line_urls) else []
                if eps:
                    first_ep = eps[0].split("$", 1)[1] if "$" in eps[0] else ""
                    pc = sp.playerContent(ln, first_ep, [])
                    hdr = json.loads(pc["header"]) if pc["header"] else {}
                    has_ref = "Referer" in hdr
                    print("[播放-%s] parse=%s | ref=%s | %s" % (ln, pc["parse"], has_ref, pc["url"][:70]))
            # 测试最后一条线路 (官方线路)
            if len(lines) > 3:
                ln = lines[-1]
                eps = line_urls[-1].split("#") if len(line_urls) > 1 else []
                if eps:
                    first_ep = eps[0].split("$", 1)[1] if "$" in eps[0] else ""
                    pc = sp.playerContent(ln, first_ep, [])
                    hdr = json.loads(pc["header"]) if pc["header"] else {}
                    has_ref = "Referer" in hdr
                    print("[播放-%s] parse=%s | ref=%s | %s" % (ln, pc["parse"], has_ref, pc["url"][:70]))
    print("=" * 60)
