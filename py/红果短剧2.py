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
        1) ping 探测已运行实例 (任何壳先起的服务直接复用)
        2) Runtime.exec 拉起独立 app_process 孤儿进程 (壳重启/回收它也存活)
        3) 进程内 DexClassLoader 加载服务线程 (兜底)
        dex 来源: 引擎内嵌于本文件, 首次运行自动释放; 亦复用已存在的释放副本。"""
        try:
            urllib.request.urlopen("http://127.0.0.1:18888/ping", timeout=2).read()
            return True
        except Exception:
            pass
        dexs = self._materialize_dex()
        # 策略2: 独立孤儿进程 (壳死亡不影响)
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
                    try:
                        urllib.request.urlopen("http://127.0.0.1:18888/ping", timeout=2).read()
                        return True
                    except Exception:
                        continue
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
                    try:
                        urllib.request.urlopen("http://127.0.0.1:18888/ping", timeout=2).read()
                        return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    def playerContent(self, flag, id, vipFlags=None):
        """播放: 免费集 SSR 直链; 锁定集走本地 SigServer (127.0.0.1:18888) 签名+流式解密。"""
        result = {
            "parse": 0,
            "playUrl": "",
            "url": "",
            "header": json.dumps({"User-Agent": self.ua}, ensure_ascii=False),
        }
        try:
            raw = str(id).split("#")[0]
            if "_" in raw:
                vid, sid = raw.split("_", 1)
            else:
                vid, sid = raw, ""
            if not sid:
                return result
            data = self._fetch_api(
                "%s/player/%s/%s" % (self.host, sid, vid), "player_(series_id)/(vid)/page")
            vpi = (data or {}).get("video_player_info") or {}
            play_url = vpi.get("main_url") or ""
            if play_url:
                result["url"] = play_url
                return result

            # 锁定集: 本地 SigServer 解密代理 (确保服务存活, 不在则自举)
            if not self._ensure_server():
                return result

            # 上游偶发返回不完整数据(videos 缺 main/key)或风控空响应，直接请求会 500，
            # 壳拿不到地址就会自动换源 -> 这里校验并阶梯式重试(最多4次)
            best = None
            for attempt in range(4):
                try:
                    r = json.loads(urllib.request.urlopen(
                        "http://127.0.0.1:18888/play?"
                        + urllib.parse.urlencode({"vid": str(vid)}),
                        timeout=30).read().decode(), strict=False)
                except Exception:
                    r = {}
                vids = r.get("videos") or []
                if not isinstance(vids, list):
                    vids = []
                # 过滤出真正带 (main, key) 的候选; key 兼容 list 形态
                cand = []
                for v in vids:
                    if not isinstance(v, dict):
                        continue
                    m = v.get("main")
                    k = v.get("key")
                    if isinstance(k, (list, tuple)):
                        k = k[0] if k else ""
                    if m and k:
                        cand.append(v)
                if cand:
                    order = ["1080p", "720p", "540p", "480p", "360p"]
                    for d in order:
                        for v in cand:
                            if v.get("def") == d:
                                best = v
                                break
                        if best:
                            break
                    if not best:
                        best = cand[0]
                    break
                if attempt < 3:
                    time.sleep(min(3.0, 0.8 * (attempt + 1)))
            if not best:
                return result

            # ★ 关键修复 ★
            # 红果锁定集的 key 是 base64 字符串, 含 '+', '/', '=' 等字符。
            # 若裸拼 query (旧实现 "&key=" + key):
            #   '+' 会被服务端按 x-www-form-urlencoded 解析成空格,
            #   '/' '=' '&' 也会破坏参数解析,
            #   SigServer 拿到的 AES 密钥错误 -> CENC 流解密失败 -> 播放器黑屏。
            # 必须对 url 与 key 同时做严格 URL 编码。
            key = best.get("key")
            if isinstance(key, (list, tuple)):
                key = key[0] if key else ""
            q = urllib.parse.urlencode([
                ("url", best.get("main") or ""),
                ("key", key or ""),
            ])
            result["url"] = "http://127.0.0.1:18888/stream?" + q
        except Exception:
            pass
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
#      本次修复仅涉及 playerContent 方法, 与该引擎无关。
#      ★ 请保留原文件中 _HG_DEX_Z 变量的完整内容不要改动 ★
#      即:
#         _HG_DEX_Z = (
#             "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