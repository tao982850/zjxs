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
            play_urls = []
            for e in eps:
                token = (e.get("token") or "").strip()
                if not token:
                    continue
                ep_title = _fmt_ep(e.get("title") or e.get("display_name") or "")
                # 注意: URL中不能含 $$$ (TVBox线路分隔符) 也不能含 # (集数分隔符)
                # token 直接作为播放URL, playerContent 收到后直接调用 resolve
                play_urls.append("%s$%s" % (ep_title, token))
            if not play_urls:
                play_urls.append("正片$%s" % vod_id)

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
                "vod_play_from": "YJ源",
                "vod_play_url": "#".join(play_urls),
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
        # id 直接就是 token (详情页已移除 $$$ 分隔符)
        token = str(id or "").strip()

        if token:
            d = self._get_player_json(
                "%s/v1/playback/resolve/%s" % (PLAYER_HOST, urllib.parse.quote(token)))
            if d and d.get("url"):
                play_url = d["url"]
                if play_url.startswith("http"):
                    return {
                        "parse": 0,
                        "playUrl": "",
                        "url": play_url,
                        "header": json.dumps({
                            "User-Agent": UA,
                            "Referer": HOST + "/",
                        }, ensure_ascii=False),
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
    print("=" * 52)
    print("%s 脚本自检 (修复版v2)" % NAME)
    print("=" * 52)
    sp = Spider()
    hc = sp.homeContent(True)
    print("[首页] 分类%d个 | 筛选%d组" % (len(hc["class"]), len(hc["filters"])))
    hv = sp.homeVideoContent()
    print("[推荐] %d条 | 首条: %s" % (len(hv["list"]), hv["list"][0]["vod_name"] if hv["list"] else "无"))
    for key, name in [("movie_nowplaying", "最新电影"), ("tv_domestic", "国产剧"),
                      ("tv_animation", "动漫"), ("show", "综艺")]:
        cat = sp.categoryContent(key, 1, False, {})
        print("[分类-%s] %d条 | 首条: %s" % (name, len(cat["list"]),
                                        cat["list"][0]["vod_name"] if cat["list"] else "无"))
    cat = sp.categoryContent("tv_domestic", 2, False, {})
    print("[分类-国产剧P2] %d条" % len(cat["list"]))
    s = sp.searchContent("战狼", False, 1)
    print("[搜索-战狼] %d条 | 首条: %s" % (len(s["list"]), s["list"][0]["vod_name"] if s["list"] else "无"))
    if s["list"]:
        d = sp.detailContent([s["list"][0]["vod_id"]])
        if d["list"]:
            dv = d["list"][0]
            print("[详情] %s | 年份:%s 导演:%s" % (dv["vod_name"][:20], dv["vod_year"], dv["vod_director"][:15]))
            print("  海报: %s" % dv["vod_pic"][:60])
            pu = dv["vod_play_url"]
            print("  线路: %s | 集数: %d" % (dv["vod_play_from"], len(pu.split("#"))))
            print("  首集: %s" % pu.split("#")[0][:60])
            pc = sp.playerContent("", pu.split("#")[0].split("$", 1)[1], [])
            print("[播放] parse=%s | %s" % (pc["parse"], pc["url"][:80]))
    print("=" * 52)
