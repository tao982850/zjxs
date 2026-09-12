#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVBox Python Spider - 红果短剧 (HongGuo) 纯py版 (默影视/瓜子结构兼容)
Site: https://hongguoduanju.com

播放链路:
  免费集  SSR /player/<sid>/<vid> 直链 MP4 (支持Range)
  锁定集  本地 SigServer (127.0.0.1:18888): /play 取清晰度+密钥 -> /stream CENC流式解密
          服务恢复: bash /tmp/sigsrv/start.sh

默影视(Chaquopy)兼容要点 (参照瓜子影视.py 结构):
  - from base.spider import Spider 基类继承 (壳提供 log/post/postjson 等工具方法)
  - __init__ 完成全部状态初始化 (壳只调用一次 init)
  - 必须实现 getDependence / download (壳启动时探测, 缺失直接 AttributeError 导致首页空白)
  - 纯urllib标准库, 方法返回dict
"""

import json
import ssl
import sys
import socket
import threading
import time
import http.client
import urllib.parse
import urllib.request

try:
    if '..' not in sys.path:
        sys.path.append('..')
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object


class Spider(_BaseSpider):

    def __init__(self):
        self.name = "红果短剧"
        self.host = "https://hongguoduanju.com"
        self.ua = "Mozilla/5.0 (Linux; Android 12; TV) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        self.headers = {
            "User-Agent": self.ua,
            "Referer": self.host,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self.timeout = 12
        # 榜单页对搜索引擎爬虫 UA 返回 SSR 全量数据 (普通 UA 只给空壳做前端水合)
        self._BOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE
        # 16 主分类 + 1 专区分类 (topic facet 查询串, 网站真实体系)
        self.categories = [
            {"type_name": "漫剧", "type_id": "comic"},
            {"type_name": "AI剧", "type_id": "ai"},
            {"type_name": "真人短剧", "type_id": "human"},
            {"type_name": "现言", "type_id": "topic=cate_1021"},
            {"type_name": "女性成长", "type_id": "topic=cate_1048"},
            {"type_name": "脑洞", "type_id": "topic=cate_262"},
            {"type_name": "奇幻", "type_id": "topic=cate_1020"},
            {"type_name": "玄幻", "type_id": "topic=cate_1019"},
            {"type_name": "古言", "type_id": "topic=cate_439"},
            {"type_name": "战神", "type_id": "topic=cate_1038"},
            {"type_name": "宫斗", "type_id": "topic=cate_246"},
            {"type_name": "仙侠", "type_id": "topic=cate_1013"},
            {"type_name": "权谋", "type_id": "topic=cate_1047"},
            {"type_name": "种田", "type_id": "topic=cate_1180"},
            {"type_name": "年代爱情", "type_id": "topic=cate_1022"},
            {"type_name": "悬疑", "type_id": "topic=cate_165"},
            {"type_name": "喜剧", "type_id": "topic=cate_303"},
            {"type_name": "男频", "type_id": "gender=1"},
            {"type_name": "女频", "type_id": "gender=0"},
        ]
        # 5 组筛选器 (DEX selectorList 提取)
        self._build_filters()
        self._home_cache = None
        self._home_cache_ttl = 600
        # keep-alive 连接池 (按线程隔离, 兼容并行补详情)
        self._conn_tls = threading.local()

    # ==================== 壳协议接口 ====================

    def getName(self):
        return self.name

    def init(self, cfg=""):
        pass

    def getDependence(self):
        # 默影视壳启动时 callAttr 探测, 返回空依赖表
        return {}

    def download(self, path, url):
        # 依赖下载协议: callAttr("download", 本地目标路径, 远程URL)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self.ua})
            data = urllib.request.urlopen(req, timeout=30, context=self._ctx).read()
            with open(path, "wb") as f:
                f.write(data)
        except Exception:
            pass
        return ""

    def isVPAYard(self, flag):
        return False

    def localProxy(self, url):
        return ""

    def liveContent(self):
        return {}

    # ==================== 筛选器 ====================

    def _build_filters(self):
        self.filters = {}
        for cat in self.categories:
            tid = cat["type_id"]
            if tid in ("comic", "ai", "human"):
                continue  # 专区榜单无 facets, 不提供筛选器 (避免无效筛选UI)
            self.filters[tid] = [
                {"key": "gender", "name": "频道", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "男频", "v": "1"},
                    {"n": "女频", "v": "0"},
                ]},
                {"key": "sort_type", "name": "排序", "value": [
                    {"n": "默认", "v": ""},
                    {"n": "最热", "v": "1"},
                    {"n": "最新", "v": "2"},
                ]},
                {"key": "topic", "name": "主题", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "现言", "v": "cate_1021"},
                    {"n": "女性成长", "v": "cate_1048"},
                    {"n": "脑洞", "v": "cate_262"},
                    {"n": "奇幻", "v": "cate_1020"},
                    {"n": "玄幻", "v": "cate_1019"},
                    {"n": "古言", "v": "cate_439"},
                    {"n": "战神", "v": "cate_1038"},
                    {"n": "宫斗", "v": "cate_246"},
                    {"n": "仙侠", "v": "cate_1013"},
                    {"n": "权谋", "v": "cate_1047"},
                    {"n": "种田", "v": "cate_1180"},
                    {"n": "年代爱情", "v": "cate_1022"},
                    {"n": "悬疑", "v": "cate_165"},
                    {"n": "喜剧", "v": "cate_303"},
                    {"n": "青春", "v": "cate_297"},
                    {"n": "志怪", "v": "cate_1027"},
                    {"n": "民国爱情", "v": "cate_1025"},
                    {"n": "灵异", "v": "cate_751"},
                    {"n": "家国情怀", "v": "cate_1235"},
                    {"n": "法律", "v": "cate_1136"},
                    {"n": "刑侦", "v": "cate_1148"},
                    {"n": "抗战", "v": "cate_504"},
                    {"n": "武侠", "v": "cate_1172"},
                    {"n": "民国传奇", "v": "cate_1240"},
                    {"n": "求生", "v": "cate_1168"},
                    {"n": "动作", "v": "cate_302"},
                    {"n": "科幻", "v": "cate_1092"},
                    {"n": "恐怖", "v": "cate_1219"},
                    {"n": "商战", "v": "cate_1225"},
                ]},
                {"key": "background", "name": "背景", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "现代", "v": "cate_757"},
                    {"n": "都市", "v": "cate_1"},
                    {"n": "古代", "v": "cate_758"},
                    {"n": "乡村", "v": "cate_11"},
                    {"n": "年代", "v": "cate_79"},
                    {"n": "架空", "v": "cate_452"},
                    {"n": "职场", "v": "cate_127"},
                    {"n": "民国", "v": "cate_390"},
                    {"n": "校园", "v": "cate_4"},
                    {"n": "宫廷", "v": "cate_1153"},
                    {"n": "荒岛", "v": "cate_1162"},
                ]},
                {"key": "setting", "name": "设定", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "打脸虐渣", "v": "cate_1051"},
                    {"n": "大男主", "v": "cate_1207"},
                    {"n": "大女主", "v": "cate_760"},
                    {"n": "马甲", "v": "cate_266"},
                    {"n": "重生", "v": "cate_36"},
                    {"n": "穿越", "v": "cate_37"},
                    {"n": "系统", "v": "cate_19"},
                    {"n": "先婚后爱", "v": "cate_265"},
                    {"n": "家长里短", "v": "cate_862"},
                    {"n": "小人物", "v": "cate_1010"},
                    {"n": "破镜重圆", "v": "cate_475"},
                    {"n": "神豪", "v": "cate_20"},
                    {"n": "豪门", "v": "cate_936"},
                    {"n": "强者回归", "v": "cate_1045"},
                    {"n": "异能", "v": "cate_598"},
                    {"n": "虐恋", "v": "cate_1008"},
                    {"n": "传承觉醒", "v": "cate_1007"},
                    {"n": "医生", "v": "cate_487"},
                    {"n": "强强联合", "v": "cate_1049"},
                    {"n": "赘婿逆袭", "v": "cate_1044"},
                    {"n": "甜宠", "v": "cate_96"},
                    {"n": "娱乐圈", "v": "cate_43"},
                    {"n": "神医", "v": "cate_26"},
                    {"n": "青梅竹马", "v": "cate_387"},
                    {"n": "姐弟恋", "v": "cate_762"},
                    {"n": "玄学", "v": "cate_929"},
                ]},
                {"key": "time", "name": "时间", "value": [
                    {"n": "全部", "v": ""},
                    {"n": "7天内上新", "v": "1"},
                    {"n": "14天内上新", "v": "2"},
                    {"n": "30天内上新", "v": "3"},
                    {"n": "90天内上新", "v": "4"},
                ]},
            ]

    # ==================== 内部工具 ====================

    def _fetch(self, url, retry=1):
        last_err = None
        for _ in range(retry + 1):
            try:
                # keep-alive 连接复用: 免去每次请求的 TCP+TLS 握手 (每次省 0.3~0.4s)
                conn = None
                if hasattr(self, "_conn_tls"):
                    conn = getattr(self._conn_tls, "conn", None)
                reused = False
                if conn is None:
                    conn = http.client.HTTPSConnection(
                        "hongguoduanju.com", timeout=self.timeout, context=self._ctx)
                    self._conn_tls.conn = conn
                else:
                    reused = True
                parsed = urllib.parse.urlsplit(url)
                path_q = parsed.path or "/"
                if parsed.query:
                    path_q += "?" + parsed.query
                conn.request("GET", path_q, headers=self.headers)
                resp = conn.getresponse()
                raw = resp.read()
                charset = resp.headers.get("charset") or "utf-8"
                out = raw.decode(charset, errors="replace")
                if reused:
                    self._stat_hits = getattr(self, "_stat_hits", 0) + 1
                else:
                    self._stat_miss = getattr(self, "_stat_miss", 0) + 1
                return out
            except Exception as e:
                last_err = e
                # 连接可能已被服务端关闭: 丢弃并重建
                try:
                    if conn is not None:
                        conn.close()
                except Exception:
                    pass
                if hasattr(self, "_conn_tls"):
                    self._conn_tls.conn = None
        return None

    def _fetch_api(self, url, loader, retry=1):
        """新 API 模式: 在 URL 上追加 __loader 和 __ssrDirect=true, 服务端直接返回 JSON"""
        sep = "&" if "?" in url else "?"
        url = "%s%s__loader=%s&__ssrDirect=true" % (url, sep, loader)
        html = self._fetch(url, retry)
        if not html:
            return None
        try:
            return json.loads(html)
        except (json.JSONDecodeError, ValueError):
            return None

    def _fetch_json(self, url, retry=1):
        """旧接口兼容: 直接请求并解析 JSON (用于搜索建议 API)"""
        html = self._fetch(url, retry)
        if not html:
            return None
        try:
            return json.loads(html)
        except (json.JSONDecodeError, ValueError):
            return None

    def _parse_video(self, item):
        if not isinstance(item, dict):
            return {}
        vid = str(item.get("series_id", ""))
        name = item.get("series_name") or item.get("series_title") or ""
        cover = item.get("series_cover", "")
        intro = item.get("series_intro", "")
        episode_cnt = item.get("episode_cnt", 0)
        episode_text = item.get("episode_right_text", "")
        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": cover,
            "vod_remarks": episode_text or ("全%s集" % episode_cnt if episode_cnt else ""),
            "vod_content": intro,
            "vod_tag": "",
        }

    def _fetch_rank_list(self, rank_key, page):
        """榜单数据: 新 API 下 rank 页面 loader 返回 204 (CSR 重定向后不可用),
        改用首页专区兜底 (tab_type 匹配)。"""
        return []

    def _parse_rank_item(self, x):
        """榜单条目 -> 壳视频卡片 (保留兼容, 新 API 下不直接使用)"""
        def _s(v):
            if isinstance(v, (list, tuple)):
                return " ".join(str(t) for t in v if t)
            return str(v) if v else ""
        vid = str(x.get("seriesId") or x.get("series_id") or "")
        return {
            "vod_id": vid,
            "vod_name": _s(x.get("title") or x.get("series_name") or x.get("series_title")),
            "vod_pic": _s(x.get("cover") or x.get("series_cover")),
            "vod_remarks": " ".join(t for t in [_s(x.get("statusTags")), _s(x.get("scoreText"))] if t),
            "vod_content": _s(x.get("description") or x.get("series_intro")),
            "vod_tag": "",
        }

    def _get_home_data(self):
        now = time.time()
        if self._home_cache and now - self._home_cache[0] < self._home_cache_ttl:
            return self._home_cache[1]
        data = self._fetch_api(self.host, "page")
        if data:
            self._home_cache = (now, data)
        return data

    def _home_sections(self):
        data = self._get_home_data() or {}
        return data.get("homeSections", []) or []

    def _home_recommend(self):
        """首页混合推荐: 按 vod_id 去重, 防止同一海报重复刷屏"""
        sections = self._home_sections()
        mixed = []
        seen = set()
        for i in range(10):
            for section in sections:
                videos = section.get("video_list", []) or []
                if i < len(videos):
                    vod = self._parse_video(videos[i])
                    vid = vod.get("vod_id", "")
                    if not vid or vid in seen:
                        continue
                    seen.add(vid)
                    mixed.append(vod)
                    if len(mixed) >= 24:
                        return mixed
        return mixed

    # ==================== 标准接口 ====================

    def homeContent(self, filter=True):
        result = {
            "class": [{"type_name": c["type_name"], "type_id": c["type_id"]} for c in self.categories],
            "filters": self.filters if filter else {},
            "list": [],
        }
        try:
            sections = self._home_sections()
            if sections:
                result["list"] = self._home_recommend()
        except Exception as e:
            print("获取首页失败: %s" % e)
        return result

    def homeVideoContent(self):
        try:
            return {"list": self._home_recommend()}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg=1, filter=1, extend=None):
        try:
            page = int(pg) if pg else 1
        except (TypeError, ValueError):
            page = 1
        # 专区分类 (comic=漫剧 / ai=AI剧 / human=真人短剧):
        # 官网 rank 页面 (/hot-real-drama 等) 已全部下线 (404 Not Found),
        # category API 的 tab_type 参数被忽略 (返回默认列表, 非专区数据),
        # 唯一可用数据源: 首页 __loader=page&__ssrDirect=true 返回的 homeSections
        # 每个专区仅 9 条, 无翻页能力。
        if str(tid) in ("comic", "ai", "human"):
            rank_key = str(tid)
            result = {"list": [], "page": 1, "pagecount": 1, "limit": 9, "total": 0}
            if page <= 1:
                try:
                    for sec in self._home_sections():
                        if str(sec.get("tab_type", "")) == rank_key:
                            videos = sec.get("video_list", []) or []
                            result["list"] = [self._parse_video(v) for v in videos if isinstance(v, dict)]
                            result["total"] = len(result["list"])
                            break
                except Exception:
                    pass
            return result
        # tid 直接是查询串 (如 "topic=cate_439" / "gender=1"), 不覆盖同 key 筛选器
        url = "%s/category?%s" % (self.host, str(tid))
        if isinstance(extend, dict):
            for key in ["gender", "sort_type", "topic", "background",
                        "setting", "time"]:
                val = str(extend.get(key) or "")
                if val:
                    url += "&%s=%s" % (key, urllib.parse.quote(val))
        if page >= 2:
            url += "&page=%d" % page
        result = {"list": [], "page": page, "pagecount": 1, "limit": 24, "total": 0}
        data = self._fetch_api(url, "category_page")
        if not data:
            return result
        recommend_list = data.get("recommendList", []) or []
        pagination = data.get("pagination", {}) or {}
        result["list"] = [self._parse_video(v) for v in recommend_list if isinstance(v, dict)]
        result["page"] = pagination.get("pageNum", page)
        result["pagecount"] = pagination.get("totalPages", 1)
        result["limit"] = pagination.get("pageSize", 24)
        result["total"] = pagination.get("total", 0)
        return result

    def detailContent(self, ids):
        result = {"list": []}
        try:
            ids_list = ids if isinstance(ids, list) else [ids]
            series_id = str(ids_list[0]) if ids_list else ""
            if not series_id:
                return result
            data = self._fetch_api(
                "%s/detail?series_id=%s" % (self.host, series_id), "detail_page")
            sd = (data or {}).get("seriesDetail", {}) or {}
            if not sd:
                return result
            vid_list = sd.get("vid_list", []) or []
            try:
                accessible = int(sd.get("accessible_episode_cnt") or 0)
            except (TypeError, ValueError):
                accessible = 0
            if accessible <= 0:
                accessible = len(vid_list)
            actor_parts = []
            for c in sd.get("celebrities", []) or []:
                nick = c.get("nickname", "")
                sub = c.get("sub_title", "")
                actor_parts.append("%s(%s)" % (nick, sub) if sub else nick)
            play_urls = []
            for i, vid in enumerate(vid_list):
                ep = i + 1
                label = "%d" % ep if ep <= accessible else "%d[锁]" % ep
                play_urls.append("%s$%s_%s" % (label, vid, series_id))
            detail = {
                "vod_id": str(sd.get("series_id", "")),
                "vod_name": sd.get("series_name") or sd.get("series_title", ""),
                "vod_pic": sd.get("series_cover", ""),
                "vod_content": sd.get("series_intro", ""),
                "vod_remarks": sd.get("episode_right_text", ""),
                "vod_year": "",
                "vod_area": "",
                "vod_actor": ", ".join(actor_parts),
                "vod_tag": " ".join(sd.get("tags", []) or []),
                "vod_play_from": "红果短剧",
                "vod_play_url": "#".join(play_urls),
            }
            related = [self._parse_video(v) for v in ((data or {}).get("videoList", []) or [])[:10]]
            return {"list": [detail] + related}
        except Exception:
            return result

    def searchContent(self, key, quick=False, pg=1):
        try:
            page = int(pg) if pg else 1
        except (TypeError, ValueError):
            page = 1
        result = {"list": [], "page": page, "pagecount": 1, "limit": "20", "total": 0}
        if page > 1:
            return result
        try:
            url = "%s/incent_resource/suggestion?app_id=8662&web_id=1234567890123456789&query=%s&count=20" % (
                self.host, urllib.parse.quote(key))
            data = json.loads(self._fetch(url) or "{}")
            # 先分流: 直接条目 vs 纯数字ID候选(需补详情)
            entries = []
            pend = []
            for sug in data.get("suggest_list", []) or []:
                vd = sug.get("video_data") or {}
                sid = str(vd.get("series_id") or "")
                name = vd.get("series_title") or sug.get("name") or ""
                cover = vd.get("series_cover") or ""
                intro = vd.get("series_intro") or ""
                remark = vd.get("episode_right_text") or ""
                kw = str(sug.get("keyword") or "")
                # 无 video_data 但 keyword 是纯数字(剧集ID): 拉详情补海报/简介
                if not vd and name and kw.isdigit() and len(kw) >= 10:
                    if not quick and len(pend) < 6:
                        pend.append({"kw": kw, "name": name, "cover": cover,
                                     "intro": intro, "remark": remark, "sd": None})
                    # quick 模式或候选已满: 丢弃 (与旧逻辑一致, 只是更快)
                    continue
                if not sid:
                    continue
                entries.append({"sid": sid, "name": name, "cover": cover,
                                "intro": intro, "remark": remark})
            # 并行补详情 (旧串行 6 次最坏 ~5s, 4 线程 ~1s; 带缓存: 重复搜索免请求)
            if pend:
                cache = getattr(self, "_detail_cache", None)
                if cache is None:
                    cache = self._detail_cache = {}
                now = time.time()
                for e in pend:  # 先吃缓存
                    hit = cache.get(e["kw"])
                    if hit and now - hit[0] < 1800:
                        e["sd"] = hit[1]
                todo = [e for e in pend if e["sd"] is None]
                if todo:
                    try:
                        from concurrent.futures import ThreadPoolExecutor
                    except ImportError:
                        ThreadPoolExecutor = None
                    if ThreadPoolExecutor is not None:
                        def _fetch_sd(e):
                            try:
                                d = self._fetch_api(
                                    "%s/detail?series_id=%s" % (self.host, e["kw"]), "detail_page")
                                return (d or {}).get("seriesDetail") or {}
                            except Exception:
                                return {}
                        with ThreadPoolExecutor(max_workers=4) as ex:
                            for e, sd in zip(todo, ex.map(_fetch_sd, todo)):
                                e["sd"] = sd
                                if sd:
                                    cache[e["kw"]] = (time.time(), sd)
                        if len(cache) > 200:
                            cache.clear()
                    else:
                        for e in todo:  # 无线程库时退回串行
                            d = None
                            try:
                                d = self._fetch_api("%s/detail?series_id=%s" % (self.host, e["kw"]), "detail_page")
                            except Exception:
                                pass
                            e["sd"] = (d or {}).get("seriesDetail") or {}
                            if e["sd"]:
                                cache[e["kw"]] = (time.time(), e["sd"])
            # 合并结果 (保持原始顺序, 统一去重; 只保留真实剧集ID,
            # 热搜词/聚合词一律丢弃, 避免点进去播不了的无关条目)
            items = []
            seen = set()
            for e in entries:
                sid = e["sid"]
                name, cover = e["name"], e["cover"]
                intro, remark = e["intro"], e["remark"]
                if sid in seen:
                    continue
                seen.add(sid)
                items.append({
                    "vod_id": sid,
                    "vod_name": name,
                    "vod_pic": cover,
                    "vod_remarks": remark,
                    "vod_content": intro,
                    "vod_tag": "",
                })
            for e in pend:
                sd = e.get("sd") or {}
                if not sd:
                    continue
                sid = e["kw"]
                if sid in seen:
                    continue
                seen.add(sid)
                items.append({
                    "vod_id": sid,
                    "vod_name": sd.get("series_name") or sd.get("series_title") or e["name"],
                    "vod_pic": sd.get("series_cover") or e["cover"],
                    "vod_remarks": sd.get("episode_right_text") or e["remark"],
                    "vod_content": sd.get("series_intro") or e["intro"],
                    "vod_tag": "",
                })
            result["list"] = items
            result["total"] = len(items)
            return result
        except Exception:
            pass
        # 兜底: 新 API 搜索页
        try:
            url = "%s/search?keyword=%s" % (self.host, urllib.parse.quote(key))
            data = self._fetch_api(url, "search_page")
            search_list = (data or {}).get("searchList", []) or []
            videos = [self._parse_video(v) for v in search_list if isinstance(v, dict)]
            if videos:
                result["list"] = videos
                result["total"] = len(videos)
        except Exception:
            pass
        return result

    # ==================== SigServer (锁定集解密) ====================

    def _port_open(self, host="127.0.0.1", port=18888, timeout=2.0):
        """TCP 端口探测: 只要端口在监听即认为 SigServer 存活。
        不依赖具体的 HTTP 端点 (原 urlopen('.../ping') 若路径不对会抛 HTTPError
        被误判为服务不在, 进而 pkill 掉正在运行的服务 -> 播放失败)。"""
        try:
            s = socket.create_connection((host, port), timeout=timeout)
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            s.close()
            return True
        except Exception:
            return False

    def _materialize_dex(self):
        """确保引擎 dex 存在: 内嵌数据首次自动释放 (无需任何外部文件)。
        返回按优先级排序的候选路径。"""
        import os as _os
        cands = ["/sdcard/hgsig/classes.dex", "/data/local/tmp/hgsrv/classes.dex"]
        for c in cands:
            try:
                if _os.path.exists(c) and _os.path.getsize(c) > 1000000:
                    return cands
            except Exception:
                pass
        blob = None
        g = globals()
        if "_HG_DEX_Z" in g:
            try:
                import zlib, base64
                blob = zlib.decompress(base64.b64decode(g["_HG_DEX_Z"]))
            except Exception:
                blob = None
        if blob:
            # 1) sdcard 共享位置 (同机所有壳可复用)
            try:
                _os.makedirs("/sdcard/hgsig", exist_ok=True)
                with open("/sdcard/hgsig/classes.dex", "wb") as f:
                    f.write(blob)
                return cands
            except Exception:
                pass
            # 2) 应用私有目录 (无存储权限时的兜底, Chaquopy home)
            try:
                home = _os.path.expanduser("~") or "/data/user/0"
                d = _os.path.join(home, "hgsrv")
                _os.makedirs(d, exist_ok=True)
                p = _os.path.join(d, "classes.dex")
                with open(p, "wb") as f:
                    f.write(blob)
                cands.insert(0, p)
            except Exception:
                pass
        return cands

    def _ensure_server(self):
        """确保本地 SigServer 运行。策略:
        1) TCP 端口探测已运行实例 (任何壳先起的服务直接复用, 不 ping 具体路径)
        2) Runtime.exec 拉起独立 app_process 孤儿进程 (壳重启/回收它也存活)
        3) 进程内 DexClassLoader 加载服务线程 (兜底)
        dex 来源: 引擎内嵌于本文件, 首次运行自动释放; 亦复用已存在的释放副本。"""
        # 策略1: 端口探测 (关键修复: 用 TCP 而非 urlopen(.../ping))
        if self._port_open():
            return True

        dexs = self._materialize_dex()

        # 策略2: 独立孤儿进程
        # 启动前先清掉可能存在的僵尸实例(端口被占但不服务的进程);
        # 若绑定失败(如 TIME_WAIT 占端口), 自动重试最多3轮(间隔20秒, 覆盖~60秒窗口)
        for dex in dexs[:1]:
            try:
                from java.lang import Runtime
                cmd = (
                    "pkill -f '^/system/bin/app_process / HgServer' 2>/dev/null; "
                    "CLASSPATH=%s setsid /system/bin/app_process / HgServer "
                    "</dev/null >/dev/null 2>&1 & "
                    "sleep 3; "
                    "for i in 1 2 3; do "
                    "if netstat -tln 2>/dev/null | grep -q 18888; then break; fi; "
                    "pkill -f '^/system/bin/app_process / HgServer' 2>/dev/null; "
                    "sleep 20; "
                    "CLASSPATH=%s setsid /system/bin/app_process / HgServer "
                    "</dev/null >/dev/null 2>&1 & done"
                ) % (dex, dex)
                Runtime.getRuntime().exec(["/system/bin/sh", "-c", cmd])
                for _ in range(8):
                    time.sleep(1)
                    if self._port_open():
                        return True
            except Exception:
                continue

        # 策略3: 进程内加载 (服务线程随本壳进程存活)
        for dex in dexs:
            try:
                from java.lang import ClassLoader
                from dalvik.system import DexClassLoader
                dcl = DexClassLoader(dex, None, None, ClassLoader.getSystemClassLoader())
                obj = dcl.loadClass("HgServer").newInstance()
                obj.ensureStarted(18888)
                for _ in range(5):
                    time.sleep(1)
                    if self._port_open():
                        return True
            except Exception:
                continue
        return False

    def _sig_play(self, vid):
        """请求 SigServer /play 获取视频信息 (GET, 参数 URL 编码)。"""
        try:
            url = "http://127.0.0.1:18888/play?" + urllib.parse.urlencode({"vid": str(vid)})
            raw = urllib.request.urlopen(url, timeout=30).read()
            return json.loads(raw.decode("utf-8", "replace"), strict=False)
        except Exception:
            return {}

    def _extract_videos(self, r):
        """兼容多种 SigServer /play 响应结构, 提取所有含 main 的清晰度条目。
        兼容:
          顶层 {videos|video_list|list: [...]}
          嵌套 {data|result: {videos|video_list|list: [...]}}
          item 主字段: main | url | play_url | src | main_url
          item 密钥字段: key | aes_key | secret | k
        """
        if not isinstance(r, dict):
            return []
        vids = None
        for k in ("videos", "video_list", "list"):
            v = r.get(k)
            if isinstance(v, list):
                vids = v
                break
        if vids is None:
            for dk in ("data", "result"):
                d = r.get(dk)
                if isinstance(d, dict):
                    for k in ("videos", "video_list", "list"):
                        v = d.get(k)
                        if isinstance(v, list):
                            vids = v
                            break
                    if vids is not None:
                        break
        if not isinstance(vids, list):
            return []
        out = []
        for item in vids:
            if not isinstance(item, dict):
                continue
            main = ""
            for mk in ("main", "url", "play_url", "src", "main_url"):
                v = item.get(mk)
                if v:
                    main = v
                    break
            if not main:
                continue
            key = ""
            for kk in ("key", "aes_key", "secret", "k"):
                v = item.get(kk)
                if isinstance(v, (list, tuple)):
                    v = v[0] if v else ""
                if v:
                    key = v
                    break
            defv = item.get("def") or item.get("quality") or item.get("name") or ""
            out.append({"main": main, "key": key, "def": defv})
        return out

    def _pick_best_video(self, cand):
        """按清晰度优先级选择: 1080p > 720p > 540p > 480p > 360p, 优先选带 key 的。"""
        if not cand:
            return None
        order = ["1080p", "720p", "540p", "480p", "360p"]
        for d in order:
            for v in cand:
                if v.get("def") == d and v.get("key"):
                    return v
        for d in order:
            for v in cand:
                if v.get("def") == d:
                    return v
        for v in cand:
            if v.get("key"):
                return v
        return cand[0]

    def _sig_stream_url(self, item):
        """根据 SigServer /play 返回的单条视频信息构造最终播放地址。
        兼容 4 种形态:
          1) main 已是本地相对路径 ("/stream?token=xxx")  -> 拼 127.0.0.1:18888 前缀
          2) main 已是本地绝对地址 ("http://127.0.0.1:18888/...") -> 原样返回
          3) main 是远程地址, 有 key -> 拼 /stream?url=...&key=...
          4) main 是远程地址, 无 key -> 原样返回
        """
        main = item.get("main") or ""
        key = item.get("key")
        if isinstance(key, (list, tuple)):
            key = key[0] if key else ""
        key = str(key or "")
        if not main:
            return ""

        # 形态1: 相对路径
        if main.startswith("/"):
            return "http://127.0.0.1:18888" + main
        # 形态2: 本地绝对地址
        if main.startswith("http://127.0.0.1:18888/") or main.startswith("http://localhost:18888/"):
            return main
        # 形态3: 远程地址 + key
        if key:
            # url 参数: 保留 URL 结构字符 (:/?&=%#), 避免 SigServer 二次解析出错
            # key 参数: 完整编码。base64 里的 '+ / =' 必须转义,
            #           否则 '+' 被服务端按 x-www-form-urlencoded 解成空格,
            #           AES 密钥错误 -> CENC 流解密失败 -> 播放器黑屏。
            url_q = urllib.parse.quote(main, safe=":/?&=%#")
            key_q = urllib.parse.quote(key, safe="")
            return "http://127.0.0.1:18888/stream?url=%s&key=%s" % (url_q, key_q)
        # 形态4: 远程地址无 key
        return main

    def playerContent(self, flag, id, vipFlags=None):
        """播放: 免费集 SSR 直链; 锁定集走本地 SigServer (127.0.0.1:18888) 签名+流式解密。"""
        result = {
            "parse": 0,
            "playUrl": "",
            "url": "",
            "header": json.dumps({"User-Agent": self.ua}, ensure_ascii=False),
        }
        raw = str(id).split("#")[0]
        if "_" in raw:
            vid, sid = raw.split("_", 1)
        else:
            vid, sid = raw, ""
        if not sid:
            return result

        # 1) 免费集: SSR /player 直链
        try:
            data = self._fetch_api(
                "%s/player/%s/%s" % (self.host, sid, vid), "player_(series_id)/(vid)/page")
            play_url = ((data or {}).get("video_player_info") or {}).get("main_url") or ""
            if play_url:
                result["url"] = play_url
                result["playUrl"] = play_url
                return result
        except Exception:
            pass

        # 2) 锁定集: 走本地 SigServer
        if not self._ensure_server():
            return result

        # 阶梯式重试: 上游偶发返回不完整数据(videos 缺 main/key)或风控空响应
        best = None
        for attempt in range(4):
            r = self._sig_play(vid)
            cand = self._extract_videos(r)
            if cand:
                best = self._pick_best_video(cand)
                if best:
                    break
            if attempt < 3:
                time.sleep(min(3.0, 0.8 * (attempt + 1)))
        if not best:
            return result

        stream_url = self._sig_stream_url(best)
        if not stream_url:
            return result
        result["url"] = stream_url
        result["playUrl"] = stream_url
        return result

    # ==================== get 前缀别名 ====================

    def getHomeContent(self, filter=True):
        return self.homeContent(filter)

    def getHomeVideoContent(self):
        return self.homeVideoContent()

    def getCategoryContent(self, tid, pg=1, filter=1, extend=None):
        return self.categoryContent(tid, pg, filter, extend)

    def getDetailContent(self, array):
        return self.detailContent(array)

    def getSearchContent(self, key, quick=False, pg=1):
        return self.searchContent(key, quick, pg)

    def getPlayerContent(self, flag, id, vipFlags=None):
        return self.playerContent(flag, id, vipFlags)


# ============================================================================
# 内嵌解密引擎 (zlib + base64 压缩的 classes.dex, 首次运行自动释放到磁盘)
# ----------------------------------------------------------------------------
# 说明: 该 _HG_DEX_Z 变量为超长 base64 字符串字面量 (数百 KB)。
#      本次修复仅涉及 SigServer 探测与播放地址拼接逻辑, 与该引擎无关。
#      ★ 请保留原文件中 _HG_DEX_Z 变量的完整内容不要改动 ★
#
#       原文即:
#         _HG_DEX_Z = (
#             "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