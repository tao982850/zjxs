# -*- coding: utf-8 -*-
"""
追剧日历 TVBox 爬虫（TMDB 数据源）
================================================
功能：
  1. 通过 TMDB API 获取「今日播出」「正在播出/即将播出」的剧集
  2. 首页按星期几分类（周一~周日），点开显示当天更新的剧
  3. 详情页展示剧集名称、海报、简介、评分、下一集播出时间
  4. 配置对话框：TMDB API Key / Access Token + 语言 + 代理

数据来源（TMDB v3，需自行申请免费 key）：
  - /tv/airing_today  ：今日播出（当天更新）
  - /tv/on_the_air    ：正在播出（含下一集播出时间）

配置读取优先级：extend 的 zhuiju 字段 > 同目录 auto-loader.tmdb.json > 文件内默认。

作者：无名之辈
交流群：Q 群 807916734
"""
import json
import time
import os
import re
import threading
import concurrent.futures
import urllib.parse
import urllib.request

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider:
        def __init__(self):
            pass


USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p/w342"
POSTER_SIZE = "w342"
WEEK_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# TMDB watch/providers 返回的 provider_name → 国内观感更友好的短名。
# 命中率高的国内平台单独映射；其他（B 站直接叫 "Bilibili" 等）按原名显示。
_PROVIDER_SHORT = {
    "Bilibili": "哔哩哔哩",
    "iQiyi": "爱奇艺",
    "Youku": "优酷视频",
    "V.QQ.com": "腾讯视频",
    "Tencent Video": "腾讯视频",
    "TencentVideo": "腾讯视频",
    "Migu Video": "咪咕",
    "Migu": "咪咕",
    "TVB Jade": "TVB",
    "WeTV": "WeTV",
    "Tudou": "土豆",
    "Sohu TV": "搜狐视频",
    "Viu": "Viu",
    "Vimeo": "Vimeo",
    "Netflix": "Netflix",
    "Disney Plus": "Disney+",
    "Disney+": "Disney+",
    "DisneyPlus": "Disney+",
    "Apple iTunes": "iTunes",
    "Max": "Max",
    "HBO Max": "Max",
    "Amazon Prime Video": "Prime",
    "Amazon Video": "Prime",
    "Apple TV+": "Apple TV+",
    "AppleTV": "Apple TV+",
    "Hulu": "Hulu",
    "Peacock": "Peacock",
    "Crunchyroll": "Crunchyroll",
    "Paramount Plus": "Paramount+",
    "Paramount+": "Paramount+",
    # 国内平台（networks 字段/JP-zh 常见名称）
    "iQiyi": "爱奇艺",
    "Tencent Video": "腾讯视频",
    "Youku": "优酷视频",
    "Mango TV": "芒果TV",
    "Sohu": "搜狐视频",
    "LeTV": "乐视",
    "Migu Video": "咪咕",
    "Migu": "咪咕",
}

# 用于从 networks 里识别"国内平台"的关键词（TMDB origin_country 可能为空/不准）。
# 统一存小写，匹配时按小写比较（TMDB 的 provider_name 大小写不统一：bilibili/Bilibili/Youku/youku）。
_CN_PLATFORM_HINTS = (
    "爱奇艺", "iqiyi", "腾讯", "tencent", "优酷", "youku", "芒果", "mango",
    "bilibili", "b站", "哔哩", "cctv", "央视", "卫视", "搜狐", "sohu",
    "咪咕", "migu", "乐视", "letv", "风行", "百视", "smg", "东方明珠",
    "金鹰", "卡酷", "炫动", "优漫", "炫佳", "cibn", "华数", "未来电视", "南方传媒",
)
# 海外主流流媒体平台：networks 里 origin_country 非 CN 也放行（如 Netflix 美剧）。
# 只放行主流平台，普通国外电视台（AMC/CBS/ABC 等）仍过滤，避免角标刷屏。
_OVERSEAS_PLATFORM_HINTS = (
    "netflix", "disney", "apple tv", "hbo", "max", "prime video",
    "paramount", "hulu", "peacock", "mubi", "crunchyroll",
)
# 平台短名映射：key 统一小写，_platform_badge/_format_providers 按 n.lower() 查找。
_PROVIDER_SHORT = {k.lower(): v for k, v in _PROVIDER_SHORT.items()}


class Spider(BaseSpider):
    def __init__(self):
        super().__init__()
        self.tmdb_key = ""
        self.tmdb_token = ""
        self.tmdb_lang = "zh-CN"
        self.tmdb_api_base = TMDB_API_BASE
        self.tmdb_img_base = TMDB_IMG_BASE
        self.img_size = POSTER_SIZE
        self.search_mode = "fuzzy"
        self._img_probe_base = None
        self._tmdb_cache = {}
        self._ota_pool = None
        self._detail_cache = {}
        self._detail_loading = False
        self._detail_lock = threading.Lock()
        self._search_cache = {}
        self._watchlist = []
        self._watchlist_loaded = False
        self._tmdb_last_error = ""
        self._tl = threading.local()
        try:
            self._tl.err = ""
        except Exception:
            pass
        self._cfg = {}
        self._dialog_refs = []
        self._edit_dialog = None

    # ================= 配置 =================
    def init(self, extend=""):
        cfg = self._load_config(extend)
        self._cfg = cfg
        self.configure(cfg)
        return ""

    def _load_config(self, extend=""):
        cfg = {}
        try:
            if extend:
                ex = json.loads(extend) if isinstance(extend, str) else extend
                if isinstance(ex, dict) and ex.get("zhuiju"):
                    cfg.update(dict(ex["zhuiju"]))
                elif isinstance(ex, dict):
                    cfg.update({k: v for k, v in ex.items()
                                if k in ("tmdb_key", "tmdb_token", "lang", "tmdb_lang",
                                         "tmdb_api_base", "tmdb_img_base", "img_size",
                                         "search_mode", "img_probe_base", "img_probe_api")})
        except Exception:
            pass
        try:
            path = self._config_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fp:
                    file_cfg = json.load(fp)
                if isinstance(file_cfg, dict):
                    cfg.setdefault("tmdb_key", file_cfg.get("tmdb_key", ""))
                    cfg.setdefault("tmdb_token", file_cfg.get("tmdb_token", ""))
                    cfg.setdefault("lang", file_cfg.get("lang", "zh-CN"))
                    cfg.setdefault("tmdb_api_base", file_cfg.get("tmdb_api_base", TMDB_API_BASE))
                    cfg.setdefault("tmdb_img_base", file_cfg.get("tmdb_img_base", TMDB_IMG_BASE))
                    cfg.setdefault("img_size", file_cfg.get("img_size", POSTER_SIZE))
                    cfg.setdefault("search_mode", file_cfg.get("search_mode", "fuzzy"))
                    cfg.setdefault("img_probe_base", file_cfg.get("img_probe_base", ""))
                    cfg.setdefault("img_probe_api", file_cfg.get("img_probe_api", ""))
        except Exception:
            pass
        return cfg

    def _config_path(self):
        here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() and __file__ else "."
        return os.path.join(here, "auto-loader.tmdb.json")

    # ================= 追看列表存储 =================
    def _watch_path(self):
        here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() and __file__ else "."
        return os.path.join(here, "auto-loader.watchlist.json")

    def _ensure_watchlist(self):
        if self._watchlist_loaded:
            return
        self._watchlist_loaded = True
        self._watchlist = []
        try:
            p = self._watch_path()
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                if isinstance(data, list):
                    self._watchlist = [x for x in data
                                       if isinstance(x, dict) and x.get("id") is not None]
        except Exception:
            pass

    def _save_watchlist(self):
        try:
            p = self._watch_path()
            with open(p, "w", encoding="utf-8") as fp:
                json.dump(self._watchlist, fp, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _watch_contains(self, tid):
        self._ensure_watchlist()
        return any(str(x.get("id")) == str(tid) for x in self._watchlist)

    def _watch_add(self, tid, name):
        self._ensure_watchlist()
        tid = str(tid)
        if not self._watch_contains(tid):
            self._watchlist.append({"id": tid, "name": str(name or "未知")})
            self._save_watchlist()

    def _watch_remove(self, tid):
        self._ensure_watchlist()
        tid = str(tid)
        before = len(self._watchlist)
        self._watchlist = [x for x in self._watchlist if str(x.get("id")) != tid]
        if len(self._watchlist) != before:
            self._save_watchlist()

    def _save_cfg(self, cfg):
        cfg = dict(cfg or {})
        cfg["tmdb_key"] = str(cfg.get("tmdb_key") or "").strip()
        cfg["tmdb_token"] = str(cfg.get("tmdb_token") or "").strip()
        cfg["lang"] = str(cfg.get("lang") or cfg.get("tmdb_lang") or "zh-CN").strip()
        cfg["tmdb_api_base"] = str(cfg.get("tmdb_api_base") or TMDB_API_BASE).strip() or TMDB_API_BASE
        cfg["tmdb_img_base"] = str(cfg.get("tmdb_img_base") or TMDB_IMG_BASE).strip() or TMDB_IMG_BASE
        cfg["img_size"] = str(cfg.get("img_size") or POSTER_SIZE).strip()
        cfg["search_mode"] = "precise" if cfg.get("search_mode") == "precise" else "fuzzy"
        path = self._config_path()
        try:
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(cfg, fp, ensure_ascii=False, indent=2)
        except Exception:
            pass
        self._cfg = cfg
        self.configure(cfg)
        return cfg

    def configure(self, cfg):
        cfg = cfg or {}
        self.tmdb_key = str(cfg.get("tmdb_key") or "").strip()
        self.tmdb_token = str(cfg.get("tmdb_token") or "").strip()
        self.tmdb_lang = str(cfg.get("lang") or cfg.get("tmdb_lang") or "zh-CN").strip()
        self.tmdb_api_base = str(cfg.get("tmdb_api_base") or TMDB_API_BASE).strip() or TMDB_API_BASE
        self.tmdb_img_base = str(cfg.get("tmdb_img_base") or TMDB_IMG_BASE).strip() or TMDB_IMG_BASE
        self.img_size = str(cfg.get("img_size") or POSTER_SIZE).strip() or POSTER_SIZE
        self.search_mode = "precise" if cfg.get("search_mode") == "precise" else "fuzzy"
        probe = str(cfg.get("img_probe_base") or "").strip()
        probe_api = str(cfg.get("img_probe_api") or "").strip().rstrip("/")
        if not probe:
            # 兜底：cfg 未携带时直接从配置文件读取（覆盖任意调用路径）
            try:
                fp = self._config_path()
                if os.path.exists(fp):
                    with open(fp, "r", encoding="utf-8") as f:
                        fc = json.load(f)
                    if isinstance(fc, dict):
                        probe = str(fc.get("img_probe_base") or "").strip()
                        probe_api = str(fc.get("img_probe_api") or "").strip().rstrip("/")
            except Exception:
                pass
        # 仅当缓存对应的 API 地址与当前配置一致时才复用，避免代理更换后失效
        if probe and probe_api and probe_api == str(self.tmdb_api_base or "").rstrip("/"):
            self._img_probe_base = probe.rstrip("/")
        else:
            self._img_probe_base = None
        self._tmdb_cache = {}
        self._ota_pool = None
        self._detail_cache = {}
        self._detail_loading = False
        self._search_cache = {}
        self._watchlist_loaded = False
        self._tmdb_last_error = ""
        return self

    def getName(self):
        return "追剧日历"

    def _last_error(self):
        """读取当前线程的最近一次 TMDB 请求错误（线程隔离，避免后台预拉污染）。"""
        tl = getattr(self, "_tl", None)
        return getattr(tl, "err", "") if tl is not None else ""

    def _diag_msg(self, fallback_err):
        """根据「API 请求失败」情况，探测图片 CDN 是否可达并返回针对性引导文案。

        区分两种场景：
          1. 图片可达，但 API 失败 -> 图片/代理代理解析正常，问题在 API 侧配置；
          2. 图片也不可达 -> 代理整体被墙或网络不通，需要更换代理/检查网络。
        """
        base_msg = "TMDB 数据加载失败"
        if fallback_err:
            base_msg = "TMDB 请求失败（{}）".format(str(fallback_err)[:40])
        if self._probe_image_ok():
            return base_msg + "。图片服务正常，请检查 API 地址 / Key / Token 配置，或更换一个可用的 API 代理。"
        return base_msg + "。图片与 API 均不可达，请检查网络或代理，并在设置中更换 API 与图片地址。"

    def _probe_image_ok(self):
        """探测图片 CDN 是否可达（供错误文案区分「图片/API」）。

        修复误报：原实现探测裸路径（如 /t/p/w92 无文件名），TMDB CDN 返回 404，
        导致「图片已正常显示却被判为不可达」。现在统一用真实存在的样本海报探测，
        并优先复用 _build_poster 已探测成功的图片域名（_img_probe_base）。
        """
        img_base = (self.tmdb_img_base or TMDB_IMG_BASE).rstrip("/")
        if not img_base:
            return True
        sample = "wwemzKWzjKYJFfCeiB57q3r4Bcm.png"  # TMDB 官方测试海报（官方与多数镜像均存在）
        bases = []
        if self._img_probe_base:
            bases.append(self._img_probe_base.rstrip("/"))
        bases.append(img_base)
        seen = set()
        for b in bases:
            key = b.rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            # 兜底：图片地址以 /t/p 结尾说明缺了尺寸段，自动补上
            if key.endswith("/t/p"):
                key += "/" + (self.img_size or POSTER_SIZE)
            try:
                if self._probe(key + "/" + sample):
                    return True
            except Exception:
                pass
        return False

    def _probe(self, url, timeout=5):
        """快速探测一个 URL 是否可达。

        语义：只要能建立连接并收到 HTTP 响应（含 4xx/5xx），即视为「网络可达」，
        避免 CDN 对 HEAD 返回 403/405 或资源级 404 造成误报；只有 DNS 失败、
        连接失败、超时等网络层异常才判为不可达。
        优先 HEAD，被拒时回退 GET（Range 只取首字节即关闭）。
        """
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT}, method="HEAD"
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return True
        except urllib.error.HTTPError:
            # HTTP 响应已到达，服务可达（如 CDN 对 HEAD 返回 405/403）
            return True
        except Exception:
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"}
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    resp.read(1)
                    return True
            except urllib.error.HTTPError:
                return True
            except Exception:
                return False

    def _probe_and_toast(self, activity, toast_class, runnable_class):
        """保存设置后后台探测 API / 图片连通性，并通过 toast 反馈诊断结果。"""
        try:
            from java import dynamic_proxy

            api_base = (self.tmdb_api_base or TMDB_API_BASE).rstrip("/")
            img_base = (self.tmdb_img_base or TMDB_IMG_BASE).rstrip("/")

            def _run():
                try:
                    api_ok = self._probe(api_base.rstrip("/") + "/3" if "/3" not in api_base else api_base)
                    img_ok = self._probe_image_ok()
                    if api_ok and img_ok:
                        msg = "✓ API 与图片服务均连通，配置正常。"
                    elif api_ok:
                        msg = "✓ API 连通；图片服务( {} )不可达，请检查图片地址。".format(img_base)
                    elif img_ok:
                        msg = "✓ 图片服务连通；API( {} )不可达，请检查 API 地址/Key/Token。".format(api_base)
                    else:
                        msg = "✗ API 与图片均不可达，请检查网络代理或在设置中更换地址。"
                    class _R(dynamic_proxy(runnable_class)):
                        def run(self):
                            try:
                                toast_class.makeText(activity, msg, toast_class.LENGTH_LONG).show()
                            except Exception:
                                pass
                    activity.runOnUiThread(_R())
                except Exception:
                    pass

            t = threading.Thread(target=_run, daemon=True)
            t.start()
        except Exception:
            pass

    # ================= TMDB 请求 =================
    def _tmdb_request(self, path, params):
        if not self.tmdb_token and not self.tmdb_key:
            return None
        # 线程本地错误记录：多线程并发(后台预拉)时互不污染
        tl = getattr(self, "_tl", None) or threading.local()
        tl.err = ""
        attempts = []
        if self.tmdb_token:
            attempts.append(("v4token", "Bearer " + self.tmdb_token))
        if self.tmdb_key:
            attempts.append(("v3key", None))
        for mode, auth in attempts:
            p = dict(params)
            headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
            if auth:
                headers["Authorization"] = auth
            else:
                p["api_key"] = self.tmdb_key
            p["language"] = self.tmdb_lang
            base = (self.tmdb_api_base or TMDB_API_BASE).rstrip("/")
            # 兜底：base 必须以 /3 结尾，否则自动补上（避免 404）
            if not base.endswith("/3"):
                base += "/3"
            url = base + path + "?" + urllib.parse.urlencode(p)
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    return json.loads(resp.read().decode("utf-8", errors="replace"))
            except Exception as exc:
                tl.err = "{}: {}".format(mode, exc)
                continue
        return None

    def _build_poster(self, item):
        item = item or {}
        poster = item.get("poster_path")
        if not poster:
            # 兜底：TMDB 里部分剧没上传正式海报，退回用横版背景图顶替，避免卡片空白
            poster = item.get("backdrop_path")
        if not poster:
            return ""
        base = (self.tmdb_img_base or TMDB_IMG_BASE).rstrip("/")
        # 兜底：图片地址以 /t/p 结尾说明缺了尺寸段，自动补上，避免404
        if base.endswith("/t/p"):
            base += "/" + self.img_size
        # 兜底：图片地址仍是官方被墙域名时，尝试从 API 代理推导同源图片地址。
        # 【优化】候选域名并行探测（并发等待，耗时≈单个探测），取第一个可用，
        # 保证返回的海报 URL 一定可加载；结果缓存并持久化，之后零等待。
        if "image.tmdb.org" in base and self.tmdb_api_base and "themoviedb.org/3" not in self.tmdb_api_base:
            if self._img_probe_base is None:
                api_base = self.tmdb_api_base.rstrip("/").replace("/3", "")
                host = api_base.split("//")[1] if "//" in api_base else api_base
                cands = ("https://image." + host + "/t/p/" + self.img_size,
                         "https://images." + host + "/t/p/" + self.img_size,
                         api_base + "/t/p/" + self.img_size)
                self._img_probe_base = self._pick_img_base(cands, poster)
            base = self._img_probe_base
        return base + poster

    def _pick_img_base(self, cands, sample_poster):
        """并行探测候选图片域名，返回第一个可用的；全部失败回退官方域名。

        三个候选同时发 HEAD 请求（超时 2s），总等待≈单候选耗时（通常 1s 内），
        远快于原版逐个串行探测（最坏 3*4s+）。探测结果会持久化到配置文件，
        下次启动直接复用，不再探测。
        """
        sample = "/" + str(sample_poster).lstrip("/")
        found = []
        lock = threading.Lock()

        def probe(cand):
            ok = False
            try:
                req = urllib.request.Request(
                    cand + sample, headers={"User-Agent": USER_AGENT}, method="HEAD"
                )
                with urllib.request.urlopen(req, timeout=2) as resp:
                    ok = resp.getcode() < 400
            except Exception:
                ok = False
            if ok:
                with lock:
                    if not found:
                        found.append(cand)

        ts = [threading.Thread(target=probe, args=(c,), daemon=True) for c in cands]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        if found:
            self._persist_img_probe(found[0])
            return found[0]
        # 全部失败：回退官方域名（原 tmdb_img_base），并持久化避免反复探测
        fallback = (self.tmdb_img_base or TMDB_IMG_BASE).rstrip("/")
        self._persist_img_probe(fallback)
        return fallback

    def _persist_img_probe(self, base_url):
        """把探测结果写入 auto-loader.tmdb.json，下次启动直接复用。"""
        try:
            p = self._config_path()
            cfg = {}
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as fp:
                    cfg = json.load(fp)
            if not isinstance(cfg, dict):
                cfg = {}
            cfg["img_probe_base"] = base_url
            cfg["img_probe_api"] = str(self.tmdb_api_base or "").rstrip("/")
            with open(p, "w", encoding="utf-8") as fp:
                json.dump(cfg, fp, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _remark_for(self, item, same_day_count=0):
        """拼接备注：评分 + 下一集播出信息（今天则显示「今天更新」）。

        统一首页列表与「我的追看」详情的备注格式；传入 same_day_count>1 时
        追加「当天N集」信息。
        """
        parts = []
        vote = item.get("vote_average")
        if vote:
            parts.append("{:.1f}分".format(float(vote)))
        nxt = item.get("next_episode_to_air") or {}
        air = nxt.get("air_date") or ""
        if air:
            today = time.strftime("%Y-%m-%d")
            s = nxt.get("season_number")
            e = nxt.get("episode_number")
            seg_detail = ""
            if s and e:
                seg_detail = " S{:02d}E{:02d}".format(s, e)
            if str(air) == today:
                seg = "今天更新" + seg_detail
            else:
                seg = "下集 {}{}".format(str(air)[5:], seg_detail)
            if same_day_count and same_day_count > 1:
                seg += " · 当天{}集".format(same_day_count)
            parts.append(seg)
        elif item.get("status") and str(item["status"]).lower() in ("ended", "canceled"):
            parts.append("已完结")
        elif item.get("first_air_date"):
            parts.append(str(item["first_air_date"])[:4])
        return " · ".join(parts)

    PLATFORM_DIAG_TID = "platform_diag"

    def _platform_diag_lines(self):
        """生成「平台诊断」弹窗文本：逐部追看剧显示 networks 原始数据与角标结果。"""
        try:
            self._ensure_watchlist()
        except Exception:
            pass
        lines = []
        for it in self._watchlist:
            tid = it.get("id")
            name = it.get("name") or "未知"
            if tid is None:
                lines.append("- {}（无 tv id）".format(name))
                lines.append("")
                continue
            try:
                data = self._tmdb_request("/tv/%s" % tid, {})
            except Exception:
                data = None
            nets = []
            first = ""
            if isinstance(data, dict):
                nets = data.get("networks") or []
                first = str(data.get("first_air_date") or "")[:4]
            names = self._providers_for(tid, data)
            badge = self._platform_badge(names, first)
            if nets:
                nets_txt = "、".join(
                    "{}[{}]".format(n.get("name"), n.get("origin_country") or "?")
                    for n in nets
                )
            else:
                nets_txt = "❌无networks数据"
            shown = badge if badge else "❌空"
            lines.append("{} (tv={})\n  networks: {}\n  角标: {} · 首播年: {}".format(
                name, tid, nets_txt, shown, first or "无"))
            lines.append("")
        # 附：实际列表渲染输出（与「我的追看」走完全相同的 _watchlist_vods）
        lines.append("━━ 实际列表渲染 vod_year ━━")
        try:
            vods = self._watchlist_vods()
            if vods:
                for v in vods:
                    lines.append("{} → {!r}".format(v.get("vod_name"), v.get("vod_year")))
            else:
                lines.append("（列表为空）")
        except Exception as exc:
            lines.append("渲染异常: {}".format(exc))
        lines.append("")
        return lines or ["追看列表为空"]

    def _show_platform_diag(self):
        """弹窗展示追看列表每部剧的平台诊断（后台收集数据，UI 线程弹窗）。"""
        try:
            from java import dynamic_proxy, jclass
            try:
                builder_class = jclass(
                    "com.google.android.material.dialog.MaterialAlertDialogBuilder"
                )
            except Exception:
                builder_class = jclass("android.app.AlertDialog$Builder")
            activity = self._current_android_activity(jclass)
            scroll_view_class = jclass("android.widget.ScrollView")
            text_view_class = jclass("android.widget.TextView")
            runnable_class = jclass("java.lang.Runnable")
        except Exception as exc:
            return {"code": 0, "msg": "平台诊断弹窗不可用（非Android环境）: {}".format(exc)}

        def _collect():
            try:
                text = "\n".join(self._platform_diag_lines())
            except Exception as exc:
                text = "诊断生成失败: {}".format(exc)

            class _Show(dynamic_proxy(runnable_class)):
                def run(self):
                    try:
                        tv = text_view_class(activity)
                        tv.setText(text)
                        tv.setTextSize(13.0)
                        tv.setPadding(28, 24, 28, 24)
                        sv = scroll_view_class(activity)
                        sv.addView(tv)
                        b = builder_class(activity)
                        b.setTitle("🔍 平台诊断")
                        b.setView(sv)
                        b.setPositiveButton("关闭", None)
                        b.show()
                    except Exception:
                        pass
            try:
                activity.runOnUiThread(_Show())
            except Exception:
                pass

        threading.Thread(target=_collect, daemon=True).start()
        return {"code": 0, "msg": "平台诊断已弹出"}

    @staticmethod
    def _platform_badge(names, fallback_year=""):
        """年份角标位展示：优先第一个平台短名（如「爱奇艺」），无平台则退回年份。

        大小写不敏感匹配：TMDB networks 的 provider_name 在不同剧里大小写不统一
        （如 bilibili / Bilibili / BILIBILI 都有），统一按小写查 _PROVIDER_SHORT。
        """
        short = []
        for n in names or []:
            s = _PROVIDER_SHORT.get(str(n).strip().lower(), n)
            if s and s not in short:
                short.append(s)
        if short:
            return short[0]
        return str(fallback_year or "")

    def _to_vod(self, item):
        item = item or {}
        name = item.get("name") or item.get("original_name") or "未知"
        tv_id = item.get("id")
        remarks = self._remark_for(item)
        # 平台信息显示在右上角年份角标位（vod_year）；无平台数据才回落年份。
        year = str(item.get("first_air_date") or "")[:4]
        badge = self._platform_badge(self._providers_for(tv_id), year)
        return {
            "vod_id": "tmdb$" + str(tv_id or ""),
            "vod_name": name,
            "vod_pic": self._build_poster(item),
            "vod_remarks": remarks,
            "vod_year": badge or year,
        }

    def _providers_for(self, tv_id, data=None):
        """取该剧在 CN 可看的平台名列表（watch/providers + networks 合并去重）。

        watch/providers 对中国市场覆盖近乎为零；TMDB 电视剧详情的 networks
        （首播平台）对国产剧反而较全（如 重器→CCTV-8/爱奇艺、藏锋→腾讯视频）。
        因此合并两者：networks 中 origin_country=CN 或命中国内平台关键词的
        平台直接采用。结果最多 4 个，带 _tmdb_cache 内存缓存避免重复请求。
        """
        names = []
        # 1) watch/providers CN 区域（作为补充，多数国产剧为空）
        if tv_id:
            try:
                key = "providers_CN_%s" % tv_id
                if key in self._tmdb_cache:
                    data_p = self._tmdb_cache.get(key) or {}
                else:
                    data_p = self._tmdb_request(
                        "/tv/%s/watch/providers" % tv_id, {}) or {}
                    self._tmdb_cache[key] = data_p or {}
                cn = (((data_p or {}).get("results") or {}).get("CN") or {})
                for bucket in ("flatrate", "free", "ads"):
                    for p in cn.get(bucket) or []:
                        nm = str(p.get("provider_name") or "").strip()
                        if nm and nm not in names:
                            names.append(nm)
                    if len(names) >= 4:
                        break
            except Exception:
                pass
        # 2) networks（国产剧首播平台 + 海外主流流媒体，数据更好）
        if isinstance(data, dict):
            for n in data.get("networks") or []:
                nm = str(n.get("name") or "").strip()
                if not nm or nm in names:
                    continue
                cc = str(n.get("origin_country") or "")
                nm_l = nm.lower()
                if (cc.upper() == "CN"
                        or any(h in nm_l for h in _CN_PLATFORM_HINTS)
                        or any(h in nm_l for h in _OVERSEAS_PLATFORM_HINTS)):
                    names.append(nm)
        return names[:4]

    @staticmethod
    def _format_providers(names):
        """把平台名列表渲染成短字符串（B站/爱奇艺/腾讯视频·优酷）。无则空串。"""
        if not names:
            return ""
        seen = []
        for n in names:
            s = _PROVIDER_SHORT.get(str(n).strip().lower(), n)
            if s and s not in seen:
                seen.append(s)
        if not seen:
            return ""
        return "📺" + "·".join(seen[:4])

    def _episode_same_day_count(self, tv_id, nxt):
        """返回在 next_episode_to_air 的播出日当天，该剧同季更新了几集。"""
        s = nxt.get("season_number")
        air = nxt.get("air_date")
        if not s or not air:
            return 1
        key = "season_%s_%s" % (tv_id, s)
        if key not in self._tmdb_cache:
            data = self._tmdb_request("/tv/%s/season/%s" % (tv_id, s), {})
            self._tmdb_cache[key] = data or {}
        eps = (self._tmdb_cache.get(key) or {}).get("episodes") or []
        cnt = sum(1 for e in eps if str(e.get("air_date") or "") == str(air))
        return cnt or 1

    def _watchlist_vods(self):
        """渲染「我的追看」列表：海报 + 名称 + 下一集信息（注明当天更新几集）。

        排序：所有剧统一按下一集播出日期排序，越早更新的越靠前
        （今天更新即为最小日期，自然排最前，往后更新的依次靠后）；
        没有下一集日期的剧（暂无安排等）统一放在最后。
        """
        self._ensure_watchlist()
        rows = []
        for it in self._watchlist:
            tid = it.get("id")
            if tid is None:
                continue
            data = self._tmdb_request("/tv/%s" % tid, {})
            if not data:
                continue
            nxt = data.get("next_episode_to_air") or {}
            air = nxt.get("air_date") or ""
            cnt = self._episode_same_day_count(tid, nxt) if air else 0
            remarks = self._remark_for(data, cnt)
            # 客户端角标位只渲染数字年份，非数字平台名会被忽略导致空白。
            # 因此：vod_year 恢复纯年份（角标不空白），平台改由副标题承担（见下）。
            year = str(data.get("first_air_date") or "")[:4]
            names = self._providers_for(tid, data)
            badge = self._platform_badge(names, year)
            # 副标题末尾带「📺平台」，保证任何客户端都能看到播出平台。
            if badge and badge != year:
                pf_txt = "📺" + badge
                remarks = (remarks + " " + pf_txt) if remarks else pf_txt
            # 诊断：把每部剧的原始数据打出来，便于用户反馈角标不显示时的排查
            try:
                nets = [(n.get("name"), n.get("origin_country"))
                        for n in (data.get("networks") or [])]
                print("[追剧日历][角标] %s tv=%s networks=%s 过滤=%s 角标=%r 首播年=%s" % (
                    data.get("name"), tid, nets, names, badge, year))
            except Exception:
                pass
            # 排序键：统一按 air_date 升序；无日期者(rank=1)放最后
            if air:
                rank, sort_air = 0, str(air)
            else:
                rank, sort_air = 1, "9999-99-99"
            rows.append((rank, sort_air, {
                "vod_id": "tmdb$" + str(tid),
                "vod_name": data.get("name") or it.get("name") or "未知",
                "vod_pic": self._build_poster(data),
                "vod_remarks": remarks or "点击查看详情",
                "vod_year": badge or year,
            }))
        rows.sort(key=lambda r: (r[0], r[1]))
        return [r[2] for r in rows]

    # ================= TVBox 接口 =================
    def homeContent(self, filter=False):
        classes = []
        vods = []
        if not (self.tmdb_key or self.tmdb_token):
            classes.append({"type_id": "tmdb_setup", "type_name": "⚠ 未配置 TMDB"})
            vods = [self._error_vod("⚠ 未配置 TMDB，请点「TMDB 设置」填入 API Key 或 Token")]
        else:
            classes.append({"type_id": "watchlist", "type_name": "❤ 我的追看"})
            classes.append({"type_id": "search_add", "type_name": "🔍 搜索添加"})
            classes.append({"type_id": "manage_watchlist", "type_name": "🗂 管理追更"})
            classes.append({"type_id": self.PLATFORM_DIAG_TID, "type_name": "🔬 平台诊断"})
            for i, w in enumerate(WEEK_ZH):
                classes.append({"type_id": "week$%d" % i, "type_name": w})
            classes.append({"type_id": "airing_today", "type_name": "🔥 今日播出"})
            classes.append({"type_id": "on_the_air", "type_name": "📺 正在热播"})
            # 推荐(默认首屏)展示「今日播出」，与「我的追看」分类区分开
            try:
                data = self._tmdb_request("/tv/airing_today", {"page": 1})
                items = (data or {}).get("results") or []
                vods = [self._to_vod(it) for it in items]
                if not vods:
                    if self._last_error():
                        vods = [self._error_vod("⚠ {}".format(self._diag_msg(self._last_error()[:60])))]
                    else:
                        vods = [self._error_vod("今日暂无播出安排")]
            except Exception as exc:
                vods = [self._error_vod("⚠ TMDB 请求异常: {}".format(str(exc)[:60]))]
        classes.append({"type_id": "tmdb_setup", "type_name": "⚙ TMDB 设置"})
        return {"class": classes, "list": vods}

    def _error_vod(self, msg):
        """生成一条可见的错误提示条目（用于请求失败/未配置时）。"""
        return {
            "vod_id": "note$" + str(abs(hash(msg))),
            "vod_name": msg,
            "vod_pic": "",
            "vod_remarks": "点击返回设置",
        }

    def categoryContent(self, tid, pg=1, filter=False, extend=""):
        pg = int(pg) if str(pg).isdigit() else 1
        tid = str(tid)
        if tid == "tmdb_setup":
            self.action("edit_tmdb")
            return {"page": 1, "pagecount": 1, "limit": 30, "total": 0, "list": []}
        if not (self.tmdb_key or self.tmdb_token):
            return {
                "page": 1, "pagecount": 1, "limit": 30, "total": 1,
                "list": [self._error_vod("⚠ 未配置 TMDB，请点底部「TMDB 设置」填入 Key")],
            }
        items = []
        if tid == "manage_watchlist":
            # 管理追更：弹窗列出所有已追看剧，点击某条即可移除
            self.action("manage_watchlist")
            return {
                "page": 1, "pagecount": 1, "limit": 30, "total": 1,
                "list": [self._error_vod("已弹出管理弹窗，点击剧名即可从追看中移除")],
            }
        elif tid == "search_add":
            # 脚本内搜索：全部在弹窗中完成（输入→搜索→海报结果→点击加入），
            # 不把海报放回分类页列表，避免点海报误跳播放。
            self.action("search_tv")
            return {
                "page": 1, "pagecount": 1, "limit": 30, "total": 1,
                "list": [self._error_vod("已弹出搜索框，输入剧名→点搜索→点海报结果即可加入追看")],
            }
        elif tid == self.PLATFORM_DIAG_TID:
            # 平台诊断：后台收集每部剧的 networks/角标数据并弹窗展示
            self._show_platform_diag()
            return {
                "page": 1, "pagecount": 1, "limit": 30, "total": 1,
                "list": [self._error_vod("已弹出平台诊断弹窗，查看各剧的平台数据")],
            }
        elif tid == "watchlist":
            # 我的追看：展示已加入的剧，并注明天更新集数
            vods = self._watchlist_vods()
            if not vods:
                return {
                    "page": 1, "pagecount": 1, "limit": 30, "total": 1,
                    "list": [self._error_vod("还没追看的剧，用顶部搜索框搜剧名加入吧")],
                }
            return {"page": 1, "pagecount": 1, "limit": 30, "total": len(vods), "list": vods}
        elif tid == "airing_today":
            data = self._tmdb_request("/tv/airing_today", {"page": pg})
            items = (data or {}).get("results") or []
            total = (data or {}).get("total_pages") or 1
        elif tid == "on_the_air":
            data = self._tmdb_request("/tv/on_the_air", {"page": pg})
            items = (data or {}).get("results") or []
            total = (data or {}).get("total_pages") or 1
        elif tid.startswith("week$"):
            # 星期分类：拉取 on_the_air 前几页，按下一集播出星期几过滤
            items = self._week_items(int(tid.split("$", 1)[1]))
            total = 1
        else:
            total = 1
        if not items:
            # 请求失败或返回空：给出可见提示，避免静默空页面
            err = self._last_error() or ""
            hint = "暂无数据"
            if err:
                hint = "⚠ {}".format(self._diag_msg(err[:60]))
            elif tid == "airing_today":
                hint = "今日暂无播出安排"
            elif tid == "on_the_air":
                hint = "暂无正在热播的剧"
            return {
                "page": 1, "pagecount": 1, "limit": 30, "total": 1,
                "list": [self._error_vod(hint)],
            }
        vods = [self._to_vod(it) for it in items]
        return {
            "page": pg, "pagecount": total, "limit": 30,
            "total": len(vods), "list": vods,
        }

    def _start_detail_prefetch(self, pool):
        """在后台线程并发预拉在播剧的所有详情并缓存（一次性完成，多星期复用）。

        只要调用过一次，`_detail_cache` 就被填满并长期持有，
        之后任意星期分类都能直接命中、秒开。
        """
        if not pool or self._detail_loading:
            return
        try:
            self._detail_lock.acquire()
            if self._detail_loading:
                return
            need = [it.get("id") for it in pool
                    if it.get("id") is not None and it.get("id") not in self._detail_cache]
            if not need:
                return
            self._detail_loading = True
        finally:
            try:
                self._detail_lock.release()
            except Exception:
                pass

        def _load_all():
            import concurrent.futures
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
                    for tid, data in ex.map(
                        lambda t: (t, self._tmdb_request("/tv/%s" % t, {})), need
                    ):
                        if data:
                            self._detail_cache[tid] = data
            finally:
                self._detail_loading = False

        t = threading.Thread(target=_load_all)
        t.daemon = True
        t.start()

    def _week_items(self, weekday):
        """返回下一集播出落在指定星期几的剧。

        on_the_air 列表本身不带 next_episode_to_air（只在详情接口返回），
        所以必须对在播剧逐个请求详情才能拿到下一集播出日期。

        策略：后台预拉所有在播剧详情并缓存；本方法在预拉的同时「流式过滤」，
        一旦当前星期攒够 30 条就提前返回（不必等全部拉完），
        其余详情继续在后台补齐，因此首次打开某星期更快、其余星期可直接秒开。
        """
        import time as _time
        pool = self._on_the_air_pool()
        self._start_detail_prefetch(pool)

        out = []
        evaluated = set()
        deadline = _time.time() + 25.0  # 兜底超时，避免极端网络下长时间阻塞
        while True:
            progressed = False
            for it in pool:
                sid = it.get("id")
                if sid is None or sid in evaluated:
                    continue
                d = self._detail_cache.get(sid)
                if not d:
                    continue
                evaluated.add(sid)
                progressed = True
                nxt = d.get("next_episode_to_air") or {}
                air = nxt.get("air_date") or ""
                if not air:
                    continue
                try:
                    wd = _time.localtime(
                        _time.mktime(_time.strptime(str(air), "%Y-%m-%d"))
                    ).tm_wday
                except Exception:
                    continue
                if wd == weekday:
                    merged = dict(it)
                    merged["next_episode_to_air"] = nxt
                    out.append(merged)
                    if len(out) >= 30:
                        return out

            # 全部详情已就绪（预拉完成），无需再等
            if not self._detail_loading:
                break
            # 超时兜底：用已就绪的结果返回
            if _time.time() > deadline:
                break
            # 本轮无新进展则稍等预拉线程填充
            if not progressed:
                _time.sleep(0.05)
            else:
                _time.sleep(0.0)

        return out

    def _on_the_air_pool(self):
        """拉取 on_the_air 列表前几页合并（按热度），返回去重后的在播剧（缓存）。"""
        if self._ota_pool is not None:
            return self._ota_pool
        import concurrent.futures
        pages = []
        for page in range(1, 5):
            key = "ota_%d" % page
            if key in self._tmdb_cache:
                pages.append((page, self._tmdb_cache[key]))
            else:
                pages.append((page, None))

        def load(pair):
            page, data = pair
            if data is not None:
                return page, data
            d = self._tmdb_request("/tv/on_the_air", {"page": page})
            if d is not None:
                self._tmdb_cache["ota_%d" % page] = d
            return page, d

        pool = []
        seen = set()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                for page, data in ex.map(load, pages):
                    if data is None:
                        continue
                    items = (data or {}).get("results") or []
                    if not items:
                        continue
                    for it in items:
                        sid = it.get("id")
                        if sid is None or sid in seen:
                            continue
                        seen.add(sid)
                        pool.append(it)
        except Exception:
            # 并发失败时回退：串行拉一次
            for page in range(1, 5):
                d = self._tmdb_cache.get("ota_%d" % page)
                if d is None:
                    d = self._tmdb_request("/tv/on_the_air", {"page": page})
                    if d is not None:
                        self._tmdb_cache["ota_%d" % page] = d
                if d is None:
                    break
                for it in (d or {}).get("results") or []:
                    sid = it.get("id")
                    if sid is None or sid in seen:
                        continue
                    seen.add(sid)
                    pool.append(it)
        self._ota_pool = pool
        return pool

    def _fetch_all_episodes(self, tv_id):
        """并行拉取该剧所有正季的分集列表，返回 {季号: [ep,...]}；失败返回 {}。"""
        import concurrent.futures as _cf
        try:
            d = self._tmdb_request("/tv/%s" % str(tv_id), {})
        except Exception:
            d = None
        if not d:
            return {}
        seasons = (d or {}).get("seasons") or []
        valid_sns = sorted({
            int(s.get("season_number"))
            for s in seasons
            if s.get("season_number") is not None and int(s.get("season_number")) > 0
        })
        if not valid_sns:
            return {}
        out = {}

        def _fetch(sn):
            try:
                dd = self._tmdb_request("/tv/%s/season/%s" % (tv_id, sn), {})
                return sn, (dd or {}).get("episodes") or []
            except Exception:
                return sn, []

        try:
            with _cf.ThreadPoolExecutor(max_workers=min(6, len(valid_sns))) as _ex:
                for _sn, _eps in list(_ex.map(_fetch, valid_sns)):
                    out[_sn] = _eps
        except Exception:
            for _sn in valid_sns:
                out[_sn] = _fetch(_sn)[1]
        return out

    def detailContent(self, ids):
        id0 = ids[0] if isinstance(ids, (list, tuple)) and ids else ""
        parts = str(id0).split("$")
        if len(parts) >= 2 and parts[0] == "tmdb":
            tv_id = parts[1]
            data = self._tmdb_request("/tv/" + str(tv_id), {})
            if not data:
                return {"list": []}
            nxt = data.get("next_episode_to_air") or {}
            remarks = []
            if data.get("first_air_date"):
                remarks.append(str(data["first_air_date"])[:4])
            if data.get("vote_average"):
                remarks.append("{:.1f}分".format(data["vote_average"]))
            if data.get("number_of_seasons"):
                remarks.append("{}季".format(data["number_of_seasons"]))
            if nxt.get("air_date"):
                s = nxt.get("season_number"); e = nxt.get("episode_number")
                today = time.strftime("%Y-%m-%d")
                if str(nxt["air_date"]) == today:
                    remarks.append("今天更新 S{:02d}E{:02d}".format(s or 0, e or 0))
                else:
                    remarks.append("下集 {} S{:02d}E{:02d}".format(str(nxt["air_date"])[5:], s or 0, e or 0))
            # ---- 剧情简介：整剧 overview（空则用 tagline），另附下一集剧情（追剧日历核心场景） ----
            overview = (data.get("overview") or "").strip()
            if not overview:
                overview = (data.get("tagline") or "").strip()
            content_lines = []
            if overview:
                content_lines.append(overview)
            nxt_overview = (nxt.get("overview") or "").strip()
            if nxt_overview and nxt_overview != overview:
                _s = nxt.get("season_number")
                _e = nxt.get("episode_number")
                _ep_label = "下一集"
                if _s is not None or _e is not None:
                    _ep_label = "下一集 S{:02d}E{:02d}".format(_s or 0, _e or 0)
                content_lines.append("")
                content_lines.append("【{}剧情】".format(_ep_label))
                content_lines.append(nxt_overview)
            # ---- 分集简介：列出每一集标题与简介，TVBox 详情页可上下滚动查看 ----
            _season_map = self._fetch_all_episodes(tv_id)
            if any(_season_map.get(sn) for sn in _season_map):
                content_lines.append("")
                content_lines.append("【分集简介】")
                for _sn in sorted(_season_map):
                    _eps = _season_map.get(_sn) or []
                    if not _eps:
                        continue
                    content_lines.append("")
                    content_lines.append("第{}季".format(_sn))
                    for _ep in _eps:
                        _eno = _ep.get("episode_number")
                        _ename = (_ep.get("name") or "").strip()
                        _eov = (_ep.get("overview") or "").strip()
                        if _eno is None:
                            continue
                        if _ename:
                            content_lines.append("E{:02d} {}".format(int(_eno), _ename))
                        else:
                            content_lines.append("E{:02d}".format(int(_eno)))
                        if _eov:
                            content_lines.append(_eov)

            if not content_lines:
                content_lines.append("暂无简介")
            vod_content = "\n".join(content_lines) + self._watch_action_hint(tv_id, data.get("name"))

            vod = {
                "vod_id": "tmdb$" + str(tv_id),
                "vod_name": data.get("name") or "未知",
                "vod_pic": self._build_poster(data),
                "vod_remarks": " · ".join(remarks),
                "vod_content": vod_content,
                "vod_play_from": "追看",
                "vod_play_url": "❤ 加入追看$watchadd$" + str(tv_id) + "$" + urllib.parse.quote(str(data.get("name") or "")),
            }
            return {"list": [vod]}
        return {"list": []}

    def _watch_action_hint(self, tv_id, name):
        if self._watch_contains(tv_id):
            return "\n\n当前已在「我的追看」中，点播放可移除。"
        return "\n\n点击「❤ 加入追看」把本剧加入我的追看；如加入错可按播放移除。"

    def searchContent(self, key, quick=False, pg="1"):
        if not (self.tmdb_key or self.tmdb_token) or not key:
            return {"list": []}
        items = self._do_search(key, pg)
        return {"list": [self._to_vod(it) for it in items]}

    def _do_search(self, key, pg="1"):
        """统一搜索入口：结果缓存 + 精确/模糊两种模式。

        缓存以「模式+关键词+页码」为键，相同查询直接命中，避免重复请求拖慢搜索；
        精确模式在 TMDB 结果内做名称完全匹配（忽略大小写），模糊模式返回全部结果。
        """
        q = str(key or "").strip()
        if not q:
            return []
        mode = self.search_mode
        ck = "%s|%s|%s" % (mode, q, pg)
        if ck not in self._search_cache:
            data = self._tmdb_request("/search/tv", {"query": q, "page": pg})
            items = (data or {}).get("results") or []
            if mode == "precise":
                low = q.lower()
                items = [it for it in items
                         if (str(it.get("name") or "").lower() == low
                             or str(it.get("original_name") or "").lower() == low)]
            self._search_cache[ck] = items
        return self._search_cache[ck]

    def playerContent(self, flag, id, vipFlags=None):
        # 处理「加入/移除追看」动作
        parts = str(id).split("$") if isinstance(id, str) else []
        if len(parts) >= 2 and parts[0] == "watchadd":
            tid = parts[1]
            name = urllib.parse.unquote(parts[2]) if len(parts) > 2 else ""
            if self._watch_contains(tid):
                self._watch_remove(tid)
                return {"parse": 0, "url": "", "header": {}, "msg": "已从「我的追看」移除"}
            self._watch_add(tid, name)
            return {"parse": 0, "url": "", "header": {}, "msg": "已加入「我的追看」"}
        # 追剧日历仅提供播出信息，无真实播放源
        return {"parse": 0, "url": "", "header": {}, "msg": "追剧日历仅提供播出信息，无播放源"}

    # ================= 配置对话框 =================
    def action(self, action):
        action = str(action)
        if action == "edit_tmdb":
            try:
                self._open_dialog()
                return {"code": 0, "msg": ""}
            except Exception as exc:
                return {"code": 0, "msg": "TMDB 设置失败: {}".format(exc)}
        if action == "search_tv":
            try:
                self._open_search_dialog()
                return {"code": 0, "msg": ""}
            except Exception as exc:
                return {"code": 0, "msg": "搜索失败: {}".format(exc)}
        if action == "manage_watchlist":
            try:
                self._open_manage_dialog()
                return {"code": 0, "msg": ""}
            except Exception as exc:
                return {"code": 0, "msg": "管理追更失败: {}".format(exc)}
        return {"code": 0, "msg": ""}

    def _open_dialog(self):
        from java import dynamic_proxy, jclass

        toast_class = jclass("android.widget.Toast")
        edit_text_class = jclass("android.widget.EditText")
        linear_layout_class = jclass("android.widget.LinearLayout")
        scroll_view_class = jclass("android.widget.ScrollView")
        text_view_class = jclass("android.widget.TextView")
        input_type = jclass("android.text.InputType")
        click_listener = jclass("android.content.DialogInterface$OnClickListener")
        view_click_listener = jclass("android.view.View$OnClickListener")
        button_class = jclass("android.widget.Button")
        runnable_class = jclass("java.lang.Runnable")
        try:
            builder_class = jclass(
                "com.google.android.material.dialog.MaterialAlertDialogBuilder"
            )
        except Exception:
            builder_class = jclass("android.app.AlertDialog$Builder")
        activity = self._current_android_activity(jclass)
        owner = self

        def _toast(msg):
            class _Runner(dynamic_proxy(runnable_class)):
                def run(self):
                    try:
                        toast_class.makeText(
                            activity, str(msg), toast_class.LENGTH_LONG
                        ).show()
                    except Exception:
                        pass
            try:
                activity.runOnUiThread(_Runner())
            except Exception:
                pass

        class ShowDialog(dynamic_proxy(runnable_class)):
            def run(self):
                try:
                    self._run_dialog()
                except Exception as exc:
                    message = "追剧日历设置对话框打开失败: {}".format(exc)
                    try:
                        toast_class.makeText(
                            activity, message, toast_class.LENGTH_LONG
                        ).show()
                    except Exception:
                        pass

            def _run_dialog(self):
                current = owner._cfg
                density = float(
                    activity.getResources().getDisplayMetrics().density
                )
                padding = int(16 * density + 0.5)
                spacing = int(10 * density + 0.5)

                def _theme_color(attr_name, fallback):
                    try:
                        attr_cls = jclass("android.R$attr")
                        attr_id = getattr(attr_cls, attr_name)
                        tv_cls = jclass("android.util.TypedValue")
                        tv = tv_cls()
                        theme = activity.getTheme()
                        if theme.resolveAttribute(attr_id, tv, True):
                            res = activity.getResources()
                            try:
                                return res.getColor(tv.resourceId, theme)
                            except Exception:
                                return res.getColor(tv.resourceId)
                    except Exception:
                        pass
                    return fallback

                def _to_color(value):
                    try:
                        v = int(value)
                    except Exception:
                        v = 0
                    if v > 0x7FFFFFFF:
                        v -= 0x100000000
                    return v

                accent = _to_color(_theme_color("colorPrimary", 0xFF3F7FCB))
                accent_dark = _to_color((accent & 0x00FFFFFF) | 0x99000000)
                text_secondary = _to_color(_theme_color("textColorSecondary", 0xFF757575))
                typeface_class = jclass("android.graphics.Typeface")
                view_class = jclass("android.view.View")
                gradient_class = jclass("android.graphics.drawable.GradientDrawable")
                dp_pr = int(density * 6 + 0.5)  # 卡片圆角
                dp_pa = int(density * 8 + 0.5)  # 内边距

                def _lum(c):
                    return (0.299 * ((c >> 16) & 255)
                            + 0.587 * ((c >> 8) & 255)
                            + 0.114 * (c & 255))

                bg_col = _to_color(_theme_color("colorBackground", 0xFF151515))
                is_dark = _lum(bg_col) < 128
                # 卡片背景、输入框背景、选中态/未选中态底色随明暗主题取值
                card_bg = _to_color(0x1AFFFFFF if is_dark else 0xFFF4F5F8)
                input_bg = _to_color(0x0DFFFFFF if is_dark else 0xFFF7F7F9)
                panel_fill = _to_color(0x18000000 if is_dark else 0x0A000000)
                unselected_pill = _to_color(0x14000000 if is_dark else 0x80FFFFFF)
                on_surface = _to_color(_theme_color("colorOnSurface", 0xFF111111 if is_dark else 0xFF202124))
                hint_color = _to_color(0x66FFFFFF if is_dark else 0x99000000)

                def rounded_bg(solid, radius, stroke=0, stroke_color=0):
                    g = gradient_class()
                    try:
                        g.setColor(solid)
                        g.setCornerRadius(float(radius))
                        if stroke and stroke_color:
                            g.setStroke(int(stroke), stroke_color)
                    except Exception:
                        pass
                    return g

                def set_bg(view, bg):
                    try:
                        view.setBackground(bg)
                    except Exception:
                        try:
                            view.setBackgroundDrawable(bg)
                        except Exception:
                            pass

                def make_card():
                    """圆角卡片容器，用于把相关设置归组。"""
                    card = linear_layout_class(activity)
                    card.setOrientation(linear_layout_class.VERTICAL)
                    card.setPadding(dp_pa, dp_pa, dp_pa, dp_pa)
                    set_bg(card, rounded_bg(card_bg, dp_pr, max(1, int(density)), accent_dark))
                    lp = linear_layout_class.LayoutParams(
                        linear_layout_class.LayoutParams.MATCH_PARENT,
                        linear_layout_class.LayoutParams.WRAP_CONTENT,
                    )
                    lp.setMargins(0, int(spacing * 0.8), 0, 0)
                    card.setLayoutParams(lp)
                    return card

                def make_label(text):
                    label = text_view_class(activity)
                    label.setText(text)
                    label.setTextColor(text_secondary)
                    label.setTextSize(12.5)
                    label.setPadding(2, int(spacing * 0.4), 2, int(spacing * 0.4))
                    return label

                def make_header(text, first=False):
                    """区块标题：左侧圆点 + 加粗标题。"""
                    row = linear_layout_class(activity)
                    row.setOrientation(linear_layout_class.HORIZONTAL)
                    row.setGravity(0x10)  # CENTER_VERTICAL
                    dot = view_class(activity)
                    dot.setLayoutParams(
                        linear_layout_class.LayoutParams(
                            int(density * 7 + 0.5), int(density * 7 + 0.5)
                        )
                    )
                    set_bg(dot, rounded_bg(accent, int(density * 3.5 + 0.5)))
                    h = text_view_class(activity)
                    h.setText(text)
                    h.setTextColor(on_surface)
                    try:
                        h.setTypeface(
                            typeface_class.defaultFromStyle(typeface_class.BOLD)
                        )
                    except Exception:
                        pass
                    h.setTextSize(15.5)
                    h.setPadding(int(density * 6), 0, 0, 0)
                    row.addView(dot)
                    row.addView(h)
                    if not first:
                        root.addView(make_title_gap())
                    root.addView(row)
                    return row

                def make_title_gap():
                    g = view_class(activity)
                    g.setLayoutParams(
                        linear_layout_class.LayoutParams(
                            linear_layout_class.LayoutParams.MATCH_PARENT,
                            int(spacing * 0.9),
                        )
                    )
                    return g

                def make_edit(hint, text="", password=False):
                    """返回 (edit, wrap)：wrap 为「输入框+右侧清空小按钮」水平容器，edit 为真正的 EditText。"""
                    wrap = linear_layout_class(activity)
                    wrap.setOrientation(linear_layout_class.HORIZONTAL)
                    wrap.setGravity(0x10)  # CENTER_VERTICAL
                    wlp = linear_layout_class.LayoutParams(
                        linear_layout_class.LayoutParams.MATCH_PARENT,
                        linear_layout_class.LayoutParams.WRAP_CONTENT,
                    )
                    wlp.setMargins(0, int(spacing * 0.35), 0, int(spacing * 0.15))
                    wrap.setLayoutParams(wlp)

                    edit = edit_text_class(activity)
                    edit.setSingleLine(True)
                    if password:
                        edit.setInputType(
                            input_type.TYPE_CLASS_TEXT
                            | input_type.TYPE_TEXT_VARIATION_PASSWORD
                        )
                    else:
                        edit.setInputType(input_type.TYPE_CLASS_TEXT)
                    edit.setHint(hint)
                    if password:
                        try:
                            edit.setHintTextColor(hint_color)
                        except Exception:
                            pass
                    edit.setText(text)
                    edit.setTextColor(on_surface)
                    edit.setTextSize(14.0)
                    elp = linear_layout_class.LayoutParams(
                        0, linear_layout_class.LayoutParams.WRAP_CONTENT, 1.0
                    )
                    elp.setMargins(0, 0, int(density * 6 + 0.5), 0)
                    edit.setLayoutParams(elp)
                    set_bg(edit, rounded_bg(input_bg, dp_pa, max(1, int(density)), accent_dark))
                    edit.setPadding(dp_pa, int(spacing * 0.8), dp_pa, int(spacing * 0.8))
                    wrap.addView(edit)

                    clear_btn = button_class(activity)
                    clear_btn.setText("清空")
                    clear_btn.setTextSize(11.0)
                    clear_btn.setAllCaps(False)
                    clear_btn.setTextColor(accent)
                    clear_btn.setPadding(int(density * 10), 0, int(density * 10), 0)
                    set_bg(clear_btn, rounded_bg(unselected_pill, dp_pa, max(1, int(density)), accent_dark))

                    class ClearClick(dynamic_proxy(view_click_listener)):
                        def onClick(self, view):
                            try:
                                edit.setText("")
                            except Exception:
                                pass
                    clear_btn.setOnClickListener(ClearClick())
                    wrap.addView(clear_btn)
                    return edit, wrap

                root = linear_layout_class(activity)
                root.setOrientation(linear_layout_class.VERTICAL)
                root.setPadding(padding, spacing, padding, padding)

                # 用 ScrollView 包裹，内容超出屏幕时可上下滚动
                scroll = scroll_view_class(activity)
                scroll.setFillViewport(True)
                scroll.addView(root)

                sub = text_view_class(activity)
                sub.setText("通过 TMDB 获取追剧日历。需填写 API Key 或 Access Token。")
                sub.setTextColor(text_secondary)
                sub.setTextSize(12.5)
                sub.setPadding(2, 0, 2, spacing)
                root.addView(sub)

                edits = {}

                # ============ 卡片 1：TMDB 鉴权 ============
                make_header("TMDB 鉴权", first=True)
                card1 = make_card()
                card1.addView(make_label("两种方式任选其一：API Key 或 Access Token"))
                tmdb_edit, tmdb_wrap = make_edit(
                    "TMDB API Key（v3，https://www.themoviedb.org 免费申请）",
                    current.get("tmdb_key", ""),
                )
                card1.addView(tmdb_wrap)
                edits["tmdb"] = tmdb_edit
                tmdb_tok_edit, tmdb_tok_wrap = make_edit(
                    "TMDB Access Token（v4，API 设置页生成，留空用上面的 Key）",
                    current.get("tmdb_token", ""),
                )
                card1.addView(tmdb_tok_wrap)
                edits["tmdb_token"] = tmdb_tok_edit
                root.addView(card1)

                # ============ 卡片 2：语言 ============
                make_header("语言")
                card2 = make_card()
                lang_edit, lang_wrap = make_edit(
                    "如 zh-CN / en-US", current.get("lang", "zh-CN")
                )
                card2.addView(lang_wrap)
                edits["lang"] = lang_edit
                root.addView(card2)

                # ---- 图片尺寸 & 搜索方式 ----
                sel = {
                    "img_size": current.get("img_size", POSTER_SIZE),
                    "search_mode": current.get("search_mode", "fuzzy"),
                }

                def make_choice_bar(options, key):
                    """横向胶囊按钮单选组；点击后高亮选中项，写入 sel[key]。"""
                    bar = linear_layout_class(activity)
                    bar.setOrientation(linear_layout_class.HORIZONTAL)
                    btns = []
                    _listeners = []

                    def refresh():
                        for _b, (_v, _l) in zip(btns, options):
                            if sel[key] == _v:
                                set_bg(_b, rounded_bg(accent, dp_pa, 0, 0))
                                _b.setTextColor(_to_color(0xFFFFFFFF))
                                try:
                                    _b.setTypeface(
                                        typeface_class.defaultFromStyle(
                                            typeface_class.BOLD
                                        )
                                    )
                                except Exception:
                                    pass
                            else:
                                set_bg(_b, rounded_bg(unselected_pill, dp_pa, max(1, int(density)), accent_dark))
                                _b.setTextColor(text_secondary)
                                try:
                                    _b.setTypeface(
                                        typeface_class.defaultFromStyle(
                                            typeface_class.NORMAL
                                        )
                                    )
                                except Exception:
                                    pass

                    for _v, _l in options:
                        _b = button_class(activity)
                        _b.setText(_l)
                        _b.setAllCaps(False)
                        _lp = linear_layout_class.LayoutParams(
                            0, linear_layout_class.LayoutParams.WRAP_CONTENT, 1.0
                        )
                        _lp.setMargins(0, 0, int(4 * density), 0)
                        _b.setLayoutParams(_lp)
                        class _OptClick(dynamic_proxy(view_click_listener)):
                            def onClick(self, view, _target=_v, _key=key):
                                sel[_key] = _target
                                refresh()
                        _l = _OptClick()
                        _listeners.append(_l)
                        _b.setOnClickListener(_l)
                        bar.addView(_b)
                        btns.append(_b)
                    refresh()
                    return bar

                # ============ 卡片 3：图片与搜索 ============
                make_header("图片与搜索")
                card3 = make_card()
                card3.addView(make_label("图片尺寸（越小加载越快，越大海报越清晰）"))
                card3.addView(make_choice_bar(
                    [("w185", "小"), ("w342", "中"), ("w500", "大"), ("original", "原图")],
                    "img_size",
                ))
                card3.addView(make_label("搜索方式（模糊返回全部相关结果，精确只匹配同名剧）"))
                card3.addView(make_choice_bar(
                    [("fuzzy", "模糊搜索"), ("precise", "精确搜索")],
                    "search_mode",
                ))
                root.addView(card3)

                # ============ 卡片 4：TMDB 代理 ============
                make_header("TMDB 代理（可选）")
                card4 = make_card()
                api_edit, api_wrap = make_edit(
                    "API 地址，留空用官方 api.themoviedb.org",
                    "" if current.get("tmdb_api_base") in (None, TMDB_API_BASE, "") else current.get("tmdb_api_base"),
                )
                card4.addView(api_wrap)
                edits["tmdb_api_base"] = api_edit
                img_edit, img_wrap = make_edit(
                    "图片地址，留空用官方 image.tmdb.org",
                    "" if current.get("tmdb_img_base") in (None, TMDB_IMG_BASE, "") else current.get("tmdb_img_base"),
                )
                card4.addView(img_wrap)
                edits["tmdb_img_base"] = img_edit
                root.addView(card4)

                bar = linear_layout_class(activity)
                bar.setOrientation(linear_layout_class.HORIZONTAL)
                bar.setPadding(0, spacing, 0, 0)
                quick_presets = [
                    ("官方", TMDB_API_BASE, TMDB_IMG_BASE),
                    ("Proxy 1", "https://api.tmdb.org/3", "https://images.tmdb.org/t/p/w342"),
                    ("Proxy 2", "https://tmdb.nastool.org/3", "https://img.nastool.org/t/p/w342"),
                ]

                def _make_quick_click(api, img, ae, ie):
                    class QL(dynamic_proxy(view_click_listener)):
                        def onClick(self, view):
                            try:
                                ae.setText(api)
                                ie.setText(img)
                                _cur_quick[0] = api
                                _cur_quick[1] = img
                                _quick_refresh()
                            except Exception:
                                pass
                    return QL()

                _quick_listeners = []
                _quick_btns = []
                # 当前生效的 API/图片地址，用于快捷按钮高亮
                _cur_quick = [
                    current.get("tmdb_api_base") or TMDB_API_BASE,
                    current.get("tmdb_img_base") or TMDB_IMG_BASE,
                ]

                def _quick_refresh():
                    for _qb, (_qn2, _qapi2, _qimg2) in zip(_quick_btns, quick_presets):
                        _active = (
                            _qapi2 == _cur_quick[0] and _qimg2 == _cur_quick[1]
                        )
                        if _active:
                            set_bg(_qb, rounded_bg(accent, dp_pa, 0, 0))
                            _qb.setTextColor(_to_color(0xFFFFFFFF))
                            try:
                                _qb.setTypeface(
                                    typeface_class.defaultFromStyle(
                                        typeface_class.BOLD
                                    )
                                )
                            except Exception:
                                pass
                        else:
                            set_bg(_qb, rounded_bg(panel_fill, dp_pa, max(1, int(density)), accent_dark))
                            _qb.setTextColor(on_surface)
                            try:
                                _qb.setTypeface(
                                    typeface_class.defaultFromStyle(
                                        typeface_class.NORMAL
                                    )
                                )
                            except Exception:
                                pass

                for _qn, _qapi, _qimg in quick_presets:
                    _qbtn = button_class(activity)
                    _qbtn.setText(_qn)
                    _qbtn.setAllCaps(False)
                    _ql = _make_quick_click(_qapi, _qimg, api_edit, img_edit)
                    _quick_listeners.append(_ql)
                    _qbtn.setOnClickListener(_ql)
                    _lp = linear_layout_class.LayoutParams(
                        0, linear_layout_class.LayoutParams.WRAP_CONTENT, 1.0
                    )
                    _lp.setMargins(0, 0, int(4 * density), 0)
                    _qbtn.setLayoutParams(_lp)
                    bar.addView(_qbtn)
                    _quick_btns.append(_qbtn)
                _quick_refresh()
                root.addView(bar)

                class CancelListener(dynamic_proxy(click_listener)):
                    def onClick(self, dlg, which):
                        try:
                            dlg.dismiss()
                        except Exception:
                            pass

                class SaveListener(dynamic_proxy(click_listener)):
                    def onClick(self, dlg, which):
                        if which != -1:
                            try:
                                dlg.dismiss()
                            except Exception:
                                pass
                            return
                        try:
                            cfg = dict(current)
                            cfg["tmdb_key"] = str(
                                edits["tmdb"].getText().toString()
                            ).strip()
                            cfg["tmdb_token"] = str(
                                edits["tmdb_token"].getText().toString()
                            ).strip()
                            cfg["lang"] = str(
                                edits["lang"].getText().toString()
                            ).strip() or "zh-CN"
                            cfg["tmdb_api_base"] = str(
                                edits["tmdb_api_base"].getText().toString()
                            ).strip()
                            cfg["tmdb_img_base"] = str(
                                edits["tmdb_img_base"].getText().toString()
                            ).strip()
                            cfg["img_size"] = sel["img_size"]
                            cfg["search_mode"] = sel["search_mode"]
                            owner._save_cfg(cfg)
                            _toast("已保存 TMDB 设置")
                            try:
                                owner._probe_and_toast(activity, toast_class, runnable_class)
                            except Exception:
                                pass
                        except Exception as exc:
                            _toast("保存失败: {}".format(exc))
                        try:
                            dlg.dismiss()
                        except Exception:
                            pass

                builder = builder_class(activity)
                builder.setTitle("⚙ 追剧日历 · TMDB 设置")
                builder.setView(scroll)
                builder.setPositiveButton("保存", SaveListener())
                builder.setNegativeButton("取消", CancelListener())
                _dlg = builder.show()
                owner._edit_dialog = _dlg
                try:
                    _win = _dlg.getWindow()
                    if _win is not None:
                        _dm = activity.getResources().getDisplayMetrics()
                        _max_w = int(430 * density + 0.5)
                        if _dm.widthPixels > _max_w:
                            _attrs = _win.getAttributes()
                            _attrs.width = _max_w
                            _win.setAttributes(_attrs)
                except Exception:
                    pass

        # 自动重试直到 Activity 就绪再弹窗，失败给 Toast 反馈（不再静默）
        self._show_dialog_after_ready(ShowDialog(), "追剧日历弹窗打开失败，请下拉刷新后重试")

    def _open_search_dialog(self):
        """脚本内搜索弹窗：输入剧名 -> 后台搜索 -> 全新弹窗展示带海报的结果，点击某条直接加入/移除追看。"""
        from java import dynamic_proxy, jclass
        import threading

        toast_class = jclass("android.widget.Toast")
        edit_text_class = jclass("android.widget.EditText")
        linear_layout_class = jclass("android.widget.LinearLayout")
        text_view_class = jclass("android.widget.TextView")
        input_type = jclass("android.text.InputType")
        click_listener = jclass("android.content.DialogInterface$OnClickListener")
        runnable_class = jclass("java.lang.Runnable")
        progress_class = jclass("android.app.ProgressDialog")
        try:
            builder_class = jclass(
                "com.google.android.material.dialog.MaterialAlertDialogBuilder"
            )
        except Exception:
            builder_class = jclass("android.app.AlertDialog$Builder")
        activity = self._current_android_activity(jclass)
        owner = self

        def _toast(msg):
            class _Runner(dynamic_proxy(runnable_class)):
                def run(self):
                    try:
                        toast_class.makeText(
                            activity, str(msg), toast_class.LENGTH_LONG
                        ).show()
                    except Exception:
                        pass
            try:
                activity.runOnUiThread(_Runner())
            except Exception:
                pass

        class ShowDialog(dynamic_proxy(runnable_class)):
            def run(self):
                try:
                    self._run_dialog()
                except Exception as exc:
                    _toast("搜索对话框打开失败: {}".format(exc))

            def _run_dialog(self):
                density = float(activity.getResources().getDisplayMetrics().density)
                spacing = int(10 * density + 0.5)
                pad = int(16 * density + 0.5)

                # ---- 共享配色/圆角工具 ----
                def _theme_color(attr_name, fallback):
                    try:
                        attr_cls = jclass("android.R$attr")
                        attr_id = getattr(attr_cls, attr_name)
                        tv_cls = jclass("android.util.TypedValue")
                        tv = tv_cls()
                        theme = activity.getTheme()
                        if theme.resolveAttribute(attr_id, tv, True):
                            res = activity.getResources()
                            try:
                                return res.getColor(tv.resourceId, theme)
                            except Exception:
                                return res.getColor(tv.resourceId)
                    except Exception:
                        pass
                    return fallback

                def _to_color(value):
                    try:
                        v = int(value)
                    except Exception:
                        v = 0
                    if v > 0x7FFFFFFF:
                        v -= 0x100000000
                    return v

                def _lum(c):
                    return (0.299 * ((c >> 16) & 255)
                            + 0.587 * ((c >> 8) & 255)
                            + 0.114 * (c & 255))

                accent = _to_color(_theme_color("colorPrimary", 0xFF3F7FCB))
                accent_dark = _to_color((accent & 0x00FFFFFF) | 0x99000000)
                text_secondary = _to_color(_theme_color("textColorSecondary", 0xFF757575))
                bg_col = _to_color(_theme_color("colorBackground", 0xFF151515))
                is_dark = _lum(bg_col) < 128
                card_bg = _to_color(0x1AFFFFFF if is_dark else 0xFFF4F5F8)
                input_bg = _to_color(0x0DFFFFFF if is_dark else 0xFFF7F7F9)
                on_surface = _to_color(_theme_color("colorOnSurface", 0xFF111111 if is_dark else 0xFF202124))
                hint_color = _to_color(0x66FFFFFF if is_dark else 0x99000000)
                gradient_class = jclass("android.graphics.drawable.GradientDrawable")
                typeface_class = jclass("android.graphics.Typeface")
                view_class = jclass("android.view.View")
                dp_pr = int(density * 6 + 0.5)
                dp_pa = int(density * 8 + 0.5)

                def rounded_bg(solid, radius, stroke=0, stroke_color=0):
                    g = gradient_class()
                    try:
                        g.setColor(solid)
                        g.setCornerRadius(float(radius))
                        if stroke and stroke_color:
                            g.setStroke(int(stroke), stroke_color)
                    except Exception:
                        pass
                    return g

                def set_bg(view, bg):
                    try:
                        view.setBackground(bg)
                    except Exception:
                        try:
                            view.setBackgroundDrawable(bg)
                        except Exception:
                            pass

                root = linear_layout_class(activity)
                root.setOrientation(linear_layout_class.VERTICAL)
                root.setPadding(pad, spacing, pad, pad)

                # 标题行：主题色圆点 + 提示
                subrow = linear_layout_class(activity)
                subrow.setOrientation(linear_layout_class.HORIZONTAL)
                dot = view_class(activity)
                dot.setLayoutParams(
                    linear_layout_class.LayoutParams(
                        int(density * 7 + 0.5), int(density * 7 + 0.5)
                    )
                )
                set_bg(dot, rounded_bg(accent, int(density * 3.5 + 0.5)))
                sub = text_view_class(activity)
                sub.setText("输入剧名（中文/英文均可），搜索后弹出带海报的结果，点击某条即可加入追看。")
                sub.setTextColor(text_secondary)
                sub.setTextSize(12.5)
                sub.setPadding(int(density * 6), 0, 0, 0)
                subrow.addView(dot)
                subrow.addView(sub)
                root.addView(subrow)

                edit = edit_text_class(activity)
                edit.setSingleLine(True)
                edit.setInputType(input_type.TYPE_CLASS_TEXT)
                edit.setHint("请输入剧名，如：三体")
                edit.setTextColor(on_surface)
                edit.setTextSize(14.0)
                try:
                    edit.setHintTextColor(hint_color)
                except Exception:
                    pass
                elp = linear_layout_class.LayoutParams(
                    linear_layout_class.LayoutParams.MATCH_PARENT,
                    linear_layout_class.LayoutParams.WRAP_CONTENT,
                )
                elp.setMargins(0, int(spacing), 0, 0)
                edit.setLayoutParams(elp)
                set_bg(edit, rounded_bg(input_bg, dp_pa, max(1, int(density)), accent_dark))
                edit.setPadding(dp_pa, int(spacing * 0.8), dp_pa, int(spacing * 0.8))
                root.addView(edit)

                class CancelListener(dynamic_proxy(click_listener)):
                    def onClick(self, dlg, which):
                        try:
                            dlg.dismiss()
                        except Exception:
                            pass

                class SearchListener(dynamic_proxy(click_listener)):
                    def onClick(self, dlg, which):
                        if which != -1:
                            try:
                                dlg.dismiss()
                            except Exception:
                                pass
                            return
                        kw = str(edit.getText().toString()).strip()
                        if not kw:
                            _toast("请输入剧名")
                            return
                        try:
                            dlg.dismiss()
                        except Exception:
                            pass

                        pd = None
                        try:
                            pd = progress_class(activity)
                            pd.setMessage("正在搜索「{}」…".format(kw))
                            pd.setCancelable(False)
                            pd.show()
                        except Exception:
                            pd = None
                            _toast("正在搜索「{}」…".format(kw))

                        def _work():
                            try:
                                results = owner._do_search(kw)
                            except Exception:
                                results = []

                            class _Done(dynamic_proxy(runnable_class)):
                                def run(self):
                                    if pd is not None:
                                        try:
                                            pd.dismiss()
                                        except Exception:
                                            pass
                                    if not results:
                                        _toast("未搜到「{}」，换个剧名试试".format(kw))
                                        return
                                    owner._open_search_result_dialog(results)
                            try:
                                activity.runOnUiThread(_Done())
                            except Exception:
                                pass

                        t = threading.Thread(target=_work)
                        t.daemon = True
                        t.start()

                builder = builder_class(activity)
                builder.setTitle("🔍 搜索剧集")
                builder.setView(root)
                builder.setPositiveButton("搜索", SearchListener())
                builder.setNegativeButton("取消", CancelListener())
                try:
                    _dlg = builder.show()
                    try:
                        _win = _dlg.getWindow()
                        if _win is not None:
                            _dm = activity.getResources().getDisplayMetrics()
                            _max_w = int(430 * density + 0.5)
                            if _dm.widthPixels > _max_w:
                                _attrs = _win.getAttributes()
                                _attrs.width = _max_w
                                _win.setAttributes(_attrs)
                    except Exception:
                        pass
                except Exception:
                    pass

        try:
            activity.runOnUiThread(ShowDialog())
        except Exception:
            pass

    def _open_search_result_dialog(self, results):
        """后台并行下载每部剧的海报，然后在弹窗内以「海报+剧名」逐行展示；点击某行加入/移除追看。"""
        from java import dynamic_proxy, jclass
        import concurrent.futures
        import threading

        toast_class = jclass("android.widget.Toast")
        bitmap_factory_class = jclass("android.graphics.BitmapFactory")
        runnable_class = jclass("java.lang.Runnable")
        activity = self._current_android_activity(jclass)
        owner = self

        def _toast(msg):
            class _Runner(dynamic_proxy(runnable_class)):
                def run(self):
                    try:
                        toast_class.makeText(
                            activity, str(msg), toast_class.LENGTH_LONG
                        ).show()
                    except Exception:
                        pass
            try:
                activity.runOnUiThread(_Runner())
            except Exception:
                pass

        def _load(it):
            """下载单部剧的海报缩略图，失败返回 None。"""
            url = owner._poster_thumb(it)
            bmp = None
            if url:
                try:
                    import urllib.request
                    req = urllib.request.Request(
                        url, headers={"User-Agent": USER_AGENT}
                    )
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        raw = resp.read()
                    if raw:
                        bmp = bitmap_factory_class.decodeByteArray(raw, 0, len(raw))
                except Exception:
                    bmp = None
            return it, bmp

        def _work():
            loaded = []
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                    loaded = list(ex.map(_load, results))
            except Exception:
                loaded = [(it, None) for it in results]

            def _done_ui():
                try:
                    owner._render_search_result_dialog(loaded, activity)
                except Exception:
                    pass

            class _Done(dynamic_proxy(runnable_class)):
                def run(self):
                    _done_ui()
            try:
                activity.runOnUiThread(_Done())
            except Exception:
                _done_ui()

        t = threading.Thread(target=_work)
        t.daemon = True
        t.start()

    def _poster_thumb(self, item):
        """构造海报缩略图地址（小尺寸，加快弹窗加载）。"""
        item = item or {}
        poster = item.get("poster_path") or item.get("backdrop_path")
        if not poster:
            return ""
        base = (self.tmdb_img_base or TMDB_IMG_BASE).rstrip("/")
        if base.endswith("/t/p"):
            base += "/w185"
        elif "/w" in base.rsplit("/", 1)[-1]:
            base = base.rsplit("/", 1)[0] + "/w185"
        return base + poster

    def _render_search_result_dialog(self, loaded, activity):
        """在弹窗内逐行渲染「海报缩略图 + 剧名 + 年份/评分」，点击某行加入/移除追看。

        整个渲染包在 try/except 里，任何异常只弹提示，绝不闪退。
        """
        try:
            self._render_search_result_dialog_impl(loaded, activity)
        except Exception as exc:
            try:
                from java import jclass
                toast_class = jclass("android.widget.Toast")
                toast_class.makeText(activity, "结果展示失败: {}".format(exc)[:80],
                                     toast_class.LENGTH_LONG).show()
            except Exception:
                pass

    def _render_search_result_dialog_impl(self, loaded, activity):
        from java import dynamic_proxy, jclass

        toast_class = jclass("android.widget.Toast")
        linear_layout_class = jclass("android.widget.LinearLayout")
        text_view_class = jclass("android.widget.TextView")
        image_view_class = jclass("android.widget.ImageView")
        scroll_view_class = jclass("android.widget.ScrollView")
        view_class = jclass("android.view.View")
        view_click_listener = jclass("android.view.View$OnClickListener")
        click_listener = jclass("android.content.DialogInterface$OnClickListener")
        runnable_class = jclass("java.lang.Runnable")
        try:
            builder_class = jclass(
                "com.google.android.material.dialog.MaterialAlertDialogBuilder"
            )
        except Exception:
            builder_class = jclass("android.app.AlertDialog$Builder")
        owner = self

        def _to_color(value):
            try:
                v = int(value)
            except Exception:
                v = 0
            if v > 0x7FFFFFFF:
                v -= 0x100000000
            return v

        def _toast(msg):
            class _Runner(dynamic_proxy(runnable_class)):
                def run(self):
                    try:
                        toast_class.makeText(
                            activity, str(msg), toast_class.LENGTH_LONG
                        ).show()
                    except Exception:
                        pass
            try:
                activity.runOnUiThread(_Runner())
            except Exception:
                pass

        density = float(activity.getResources().getDisplayMetrics().density)
        pad = int(16 * density + 0.5)
        spacing = int(10 * density + 0.5)
        dp_pr = int(density * 6 + 0.5)

        def _theme_color(attr_name, fallback):
            try:
                attr_cls = jclass("android.R$attr")
                attr_id = getattr(attr_cls, attr_name)
                tv_cls = jclass("android.util.TypedValue")
                tv = tv_cls()
                theme = activity.getTheme()
                if theme.resolveAttribute(attr_id, tv, True):
                    res = activity.getResources()
                    try:
                        return res.getColor(tv.resourceId, theme)
                    except Exception:
                        return res.getColor(tv.resourceId)
            except Exception:
                pass
            return fallback

        def _lum(c):
            return (0.299 * ((c >> 16) & 255)
                    + 0.587 * ((c >> 8) & 255)
                    + 0.114 * (c & 255))

        accent = _to_color(_theme_color("colorPrimary", 0xFF3F7FCB))
        accent_dark = _to_color((accent & 0x00FFFFFF) | 0x99000000)
        text_secondary = _to_color(_theme_color("textColorSecondary", 0xFF757575))
        bg_col = _to_color(_theme_color("colorBackground", 0xFF151515))
        is_dark = _lum(bg_col) < 128
        card_bg = _to_color(0x1AFFFFFF if is_dark else 0xFFF4F5F8)
        on_surface = _to_color(_theme_color("colorOnSurface", 0xFF111111 if is_dark else 0xFF202124))
        accent_dot = _to_color((accent & 0x00FFFFFF) | 0x3D000000)
        gradient_class = jclass("android.graphics.drawable.GradientDrawable")

        def rounded_bg(solid, radius, stroke=0, stroke_color=0):
            g = gradient_class()
            try:
                g.setColor(solid)
                g.setCornerRadius(float(radius))
                if stroke and stroke_color:
                    g.setStroke(int(stroke), stroke_color)
            except Exception:
                pass
            return g

        def set_bg(view, bg):
            try:
                view.setBackground(bg)
            except Exception:
                try:
                    view.setBackgroundDrawable(bg)
                except Exception:
                    pass

        def ripple_bg(solid, radius, stroke=0, stroke_color=0):
            """带按压涟漪的背景（API 21+），失败回退普通圆角背景。"""
            try:
                ripple_class = jclass("android.graphics.drawable.RippleDrawable")
                csl_class = jclass("android.content.res.ColorStateList")
                csl = csl_class.valueOf(
                    _to_color((accent & 0x00FFFFFF) | 0x3D000000)
                )
                return ripple_class(csl, rounded_bg(solid, radius, stroke, stroke_color), None)
            except Exception:
                return rounded_bg(solid, radius, stroke, stroke_color)

        root = linear_layout_class(activity)
        root.setOrientation(linear_layout_class.VERTICAL)
        root.setPadding(pad, spacing, pad, pad)

        for it, bmp in loaded:
            try:
                row = linear_layout_class(activity)
                row.setOrientation(linear_layout_class.HORIZONTAL)
                set_bg(row, ripple_bg(card_bg, dp_pr, max(1, int(density)), accent_dot))
                rp = linear_layout_class.LayoutParams(
                    linear_layout_class.LayoutParams.MATCH_PARENT,
                    linear_layout_class.LayoutParams.WRAP_CONTENT,
                )
                rp.setMargins(0, 0, 0, int(spacing * 0.6))
                row.setLayoutParams(rp)
                row.setPadding(int(density * 8), int(density * 6), int(density * 8), int(density * 6))

                has_img = False
                if bmp is not None:
                    try:
                        img = image_view_class(activity)
                        iw = int(60 * density + 0.5)
                        ih = int(86 * density + 0.5)
                        img.setLayoutParams(linear_layout_class.LayoutParams(iw, ih))
                        img.setImageBitmap(bmp)
                        try:
                            img.setClipToOutline(True)
                            img.setBackground(rounded_bg(_to_color(0x00000000), int(density * 4 + 0.5)))
                        except Exception:
                            pass
                        row.addView(img)
                        has_img = True
                    except Exception:
                        has_img = False

                col = linear_layout_class(activity)
                col.setOrientation(linear_layout_class.VERTICAL)
                if has_img:
                    col.setPadding(int(10 * density + 0.5), 0, 0, 0)
                name = text_view_class(activity)
                name.setText(it.get("name") or it.get("original_name") or "未知")
                name.setTextColor(on_surface)
                name.setTextSize(15.0)
                try:
                    name.setTypeface(jclass("android.graphics.Typeface")
                                     .defaultFromStyle(jclass("android.graphics.Typeface").BOLD))
                except Exception:
                    pass
                sub = text_view_class(activity)
                year = str(it.get("first_air_date") or "")[:4]
                vote = it.get("vote_average")
                sub_text = year
                if vote:
                    sub_text = (sub_text + " · " if sub_text else "") + "{:.1f}分".format(float(vote))
                if not has_img:
                    sub_text = (sub_text + " · " if sub_text else "") + "无图"
                sub.setText(sub_text or "TMDB 剧集")
                sub.setTextColor(text_secondary)
                sub.setTextSize(12.0)
                sub.setPadding(0, int(3 * density + 0.5), 0, 0)

                # 剧情简介：搜索结果自带 overview，最多显示两行，超出省略
                overview = (it.get("overview") or "").strip()
                if overview:
                    ov = text_view_class(activity)
                    ov.setText(overview)
                    ov.setTextColor(text_secondary)
                    ov.setTextSize(12.0)
                    ov.setPadding(0, int(4 * density + 0.5), 0, 0)
                    try:
                        ov.setMaxLines(2)
                        ov.setEllipsize(
                            jclass("android.text.TextUtils$TruncateAt").END
                        )
                    except Exception:
                        pass
                    col.addView(ov)

                # 按钮行：加入追看 + 查看简介（有简介才显示）
                btn_row = linear_layout_class(activity)
                btn_row.setOrientation(linear_layout_class.HORIZONTAL)
                btn_row.setGravity(0x10)  # CENTER_VERTICAL
                btn_row.setPadding(0, int(6 * density + 0.5), 0, 0)

                tag = text_view_class(activity)
                tag.setText("加入追看 →")
                tag.setTextColor(accent)
                tag.setTextSize(12.5)
                tag.setPadding(0, 0, int(12 * density + 0.5), 0)
                btn_row.addView(tag)

                view_btn = text_view_class(activity)
                view_btn.setText("查看简介")
                view_btn.setTextColor(_to_color(0xFFFFFFFF))
                view_btn.setTextSize(12.5)
                view_btn.setPadding(
                    int(10 * density + 0.5), int(3 * density + 0.5),
                    int(10 * density + 0.5), int(3 * density + 0.5),
                )
                set_bg(view_btn, rounded_bg(accent, int(density * 4 + 0.5)))

                def _show_episodes_dialog(season_map, nm_text):
                    """分集简介弹窗：按季列出每一集标题与简介，可上下滚动。"""
                    try:
                        import threading as _th
                        _content = linear_layout_class(activity)
                        _content.setOrientation(linear_layout_class.VERTICAL)
                        _content.setPadding(
                            int(16 * density + 0.5), int(12 * density + 0.5),
                            int(16 * density + 0.5), int(12 * density + 0.5),
                        )
                        if not season_map:
                            _tv0 = text_view_class(activity)
                            _tv0.setText("暂无分集简介")
                            _tv0.setTextColor(on_surface)
                            _tv0.setTextSize(14.0)
                            _content.addView(_tv0)
                        else:
                            for _sn in sorted(season_map):
                                _eps = season_map.get(_sn) or []
                                if not _eps:
                                    continue
                                _h = text_view_class(activity)
                                _h.setText("第{}季".format(_sn))
                                _h.setTextColor(accent)
                                _h.setTextSize(14.0)
                                try:
                                    _h.setTypeface(jclass("android.graphics.Typeface")
                                                   .defaultFromStyle(jclass("android.graphics.Typeface").BOLD))
                                except Exception:
                                    pass
                                _h.setPadding(0, int(8 * density + 0.5), 0, int(4 * density + 0.5))
                                _content.addView(_h)
                                for _ep in _eps:
                                    _eno = _ep.get("episode_number")
                                    _ename = (_ep.get("name") or "").strip()
                                    _eov = (_ep.get("overview") or "").strip()
                                    if _eno is None:
                                        continue
                                    _line = text_view_class(activity)
                                    _line.setText(
                                        "E{:02d} {}".format(int(_eno), _ename) if _ename else "E{:02d}".format(int(_eno)))
                                    _line.setTextColor(on_surface)
                                    _line.setTextSize(13.5)
                                    try:
                                        _line.setTypeface(jclass("android.graphics.Typeface")
                                                          .defaultFromStyle(jclass("android.graphics.Typeface").BOLD))
                                    except Exception:
                                        pass
                                    _line.setPadding(0, int(4 * density + 0.5), 0, 0)
                                    _content.addView(_line)
                                    if _eov:
                                        _tv2 = text_view_class(activity)
                                        _tv2.setText(_eov)
                                        _tv2.setTextColor(text_secondary)
                                        _tv2.setTextSize(12.5)
                                        try:
                                            _tv2.setLineSpacing(0, 1.15)
                                        except Exception:
                                            pass
                                        _tv2.setPadding(0, int(2 * density + 0.5), 0, int(6 * density + 0.5))
                                        _content.addView(_tv2)
                        _scroll2 = scroll_view_class(activity)
                        _scroll2.setFillViewport(True)
                        _scroll2.addView(_content)
                        _builder2 = builder_class(activity)
                        _builder2.setTitle((nm_text or "剧") + " · 分集简介")
                        _builder2.setView(_scroll2)

                        class _Close2(dynamic_proxy(click_listener)):
                            def onClick(self, dlg, which):
                                try:
                                    dlg.dismiss()
                                except Exception:
                                    pass
                        _builder2.setNegativeButton("关闭", _Close2())
                        _dlg3 = _builder2.show()
                        try:
                            _win3 = _dlg3.getWindow()
                            if _win3 is not None:
                                _dm3 = activity.getResources().getDisplayMetrics()
                                _max_w3 = int(430 * density + 0.5)
                                if _dm3.widthPixels > _max_w3:
                                    _attrs3 = _win3.getAttributes()
                                    _attrs3.width = _max_w3
                                    _win3.setAttributes(_attrs3)
                        except Exception:
                            pass
                    except Exception:
                        pass

                def _make_overview_click(_ov_text, _nm_text, _tid):
                    class OverviewClick(dynamic_proxy(view_click_listener)):
                        def onClick(self, view):
                            try:
                                _content = linear_layout_class(activity)
                                _content.setOrientation(linear_layout_class.VERTICAL)
                                _content.setPadding(
                                    int(16 * density + 0.5), int(12 * density + 0.5),
                                    int(16 * density + 0.5), int(12 * density + 0.5),
                                )
                                _tv = text_view_class(activity)
                                _tv.setText(_ov_text or "暂无简介")
                                _tv.setTextColor(on_surface)
                                _tv.setTextSize(14.0)
                                try:
                                    _tv.setLineSpacing(0, 1.15)
                                except Exception:
                                    pass
                                _content.addView(_tv)
                                _scroll = scroll_view_class(activity)
                                _scroll.setFillViewport(True)
                                _scroll.addView(_content)
                                _builder = builder_class(activity)
                                _builder.setTitle(_nm_text or "剧情简介")
                                _builder.setView(_scroll)

                                class _Close(dynamic_proxy(click_listener)):
                                    def onClick(self, dlg, which):
                                        try:
                                            dlg.dismiss()
                                        except Exception:
                                            pass
                                _builder.setNegativeButton("关闭", _Close())

                                class _Episodes(dynamic_proxy(click_listener)):
                                    def onClick(self, dlg, which):
                                        try:
                                            dlg.dismiss()
                                        except Exception:
                                            pass
                                        import threading as _th2
                                        _toast("正在加载分集简介…")

                                        def _work2():
                                            try:
                                                _sm = owner._fetch_all_episodes(_tid)
                                            except Exception:
                                                _sm = {}

                                            class _Done2(dynamic_proxy(runnable_class)):
                                                def run(self):
                                                    _show_episodes_dialog(_sm, _nm_text)
                                            try:
                                                activity.runOnUiThread(_Done2())
                                            except Exception:
                                                pass
                                        _t2 = _th2.Thread(target=_work2)
                                        _t2.daemon = True
                                        _t2.start()
                                _builder.setPositiveButton("分集简介", _Episodes())

                                _dlg2 = _builder.show()
                                try:
                                    _win2 = _dlg2.getWindow()
                                    if _win2 is not None:
                                        _dm2 = activity.getResources().getDisplayMetrics()
                                        _max_w2 = int(430 * density + 0.5)
                                        if _dm2.widthPixels > _max_w2:
                                            _attrs2 = _win2.getAttributes()
                                            _attrs2.width = _max_w2
                                            _win2.setAttributes(_attrs2)
                                except Exception:
                                    pass
                            except Exception:
                                pass
                    return OverviewClick()

                view_btn.setOnClickListener(_make_overview_click(overview, it.get("name") or it.get("original_name") or "", str(it.get("id") or "")))
                btn_row.addView(view_btn)

                col.addView(name)
                col.addView(sub)
                col.addView(btn_row)
                row.addView(col)

                tid = str(it.get("id") or "")
                nm = it.get("name") or it.get("original_name") or ""

                # 关键：用工厂函数把每行的 tid/nm 提前绑定为默认参数，
                # 避免所有行的点击回调共享同一个循环变量（闭包陷阱），
                # 否则点第1行会错误地添加最后一行的剧。
                def _make_click(_tid, _nm):
                    class RowClick(dynamic_proxy(view_click_listener)):
                        def onClick(self, view):
                            try:
                                if owner._watch_contains(_tid):
                                    owner._watch_remove(_tid)
                                    _toast("已从追看移除《{}》".format(_nm))
                                else:
                                    owner._watch_add(_tid, _nm)
                                    _toast("已加入追看《{}》".format(_nm))
                            except Exception as exc:
                                _toast("操作失败: {}".format(exc)[:60])
                    return RowClick()

                row.setOnClickListener(_make_click(tid, nm))

                root.addView(row)
            except Exception:
                continue

        scroll = scroll_view_class(activity)
        scroll.setFillViewport(True)
        scroll.addView(root)

        class CancelListener(dynamic_proxy(click_listener)):
            def onClick(self, dlg, which):
                try:
                    dlg.dismiss()
                except Exception:
                    pass

        builder = builder_class(activity)
        builder.setTitle("🔍 搜索结果 · V3（点击加入追看）")
        builder.setView(scroll)
        builder.setNegativeButton("关闭", CancelListener())
        try:
            _dlg = builder.show()
            try:
                _win = _dlg.getWindow()
                if _win is not None:
                    _dm = activity.getResources().getDisplayMetrics()
                    _max_w = int(430 * density + 0.5)
                    if _dm.widthPixels > _max_w:
                        _attrs = _win.getAttributes()
                        _attrs.width = _max_w
                        _win.setAttributes(_attrs)
            except Exception:
                pass
        except Exception:
            pass

    def _open_manage_dialog(self):
        """管理追更弹窗：列出所有已追看剧，点击某条即可移除。

        点某行 -> 从追看列表移除该剧并刷新弹窗；全部移除则弹提示。
        整个方法包在 try/except 里，任何异常只弹提示，绝不闪退。
        """
        try:
            self._open_manage_dialog_impl()
        except Exception as exc:
            try:
                from java import jclass
                toast_class = jclass("android.widget.Toast")
                act = self._current_android_activity(jclass)
                if act is not None:
                    toast_class.makeText(act, "管理追更失败: {}".format(exc)[:80],
                                         toast_class.LENGTH_LONG).show()
            except Exception:
                pass

    def _open_manage_dialog_impl(self):
        from java import dynamic_proxy, jclass

        toast_class = jclass("android.widget.Toast")
        linear_layout_class = jclass("android.widget.LinearLayout")
        text_view_class = jclass("android.widget.TextView")
        scroll_view_class = jclass("android.widget.ScrollView")
        view_class = jclass("android.view.View")
        view_click_listener = jclass("android.view.View$OnClickListener")
        click_listener = jclass("android.content.DialogInterface$OnClickListener")
        runnable_class = jclass("java.lang.Runnable")
        try:
            builder_class = jclass(
                "com.google.android.material.dialog.MaterialAlertDialogBuilder"
            )
        except Exception:
            builder_class = jclass("android.app.AlertDialog$Builder")
        activity = self._current_android_activity(jclass)
        owner = self
        if activity is None:
            # Activity 未就绪：自动重试整个弹窗流程（最多 5 次，间隔约 1.2s），不再静默失败
            def _retry_impl(count):
                if count >= 5:
                    return
                try:
                    handler_cls = jclass("android.os.Handler")
                    looper_cls = jclass("android.os.Looper")
                    handler = handler_cls(looper_cls.getMainLooper())

                    class _RetryAll(dynamic_proxy(runnable_class)):
                        def run(self):
                            owner._open_manage_dialog_impl(count + 1)

                    handler.postDelayed(_RetryAll(), 1200)
                except Exception:
                    import threading
                    t = threading.Timer(1.2, lambda: owner._open_manage_dialog_impl(count + 1))
                    t.daemon = True
                    t.start()
            _retry_impl(0)
            return

        def _to_color(value):
            try:
                v = int(value)
            except Exception:
                v = 0
            if v > 0x7FFFFFFF:
                v -= 0x100000000
            return v

        def _toast(msg):
            class _Runner(dynamic_proxy(runnable_class)):
                def run(self):
                    try:
                        toast_class.makeText(
                            activity, str(msg), toast_class.LENGTH_LONG
                        ).show()
                    except Exception:
                        pass
            try:
                activity.runOnUiThread(_Runner())
            except Exception:
                pass

        def _rebuild():
            """重建弹窗内容（移除某项后刷新）。"""
            try:
                _run_dialog_content()
            except Exception:
                pass

        def _run_dialog_content():
            owner._ensure_watchlist()
            density = float(activity.getResources().getDisplayMetrics().density)
            pad = int(16 * density + 0.5)
            spacing = int(10 * density + 0.5)
            dp_pr = int(density * 6 + 0.5)

            def _theme_color(attr_name, fallback):
                try:
                    attr_cls = jclass("android.R$attr")
                    attr_id = getattr(attr_cls, attr_name)
                    tv_cls = jclass("android.util.TypedValue")
                    tv = tv_cls()
                    theme = activity.getTheme()
                    if theme.resolveAttribute(attr_id, tv, True):
                        res = activity.getResources()
                        try:
                            return res.getColor(tv.resourceId, theme)
                        except Exception:
                            return res.getColor(tv.resourceId)
                except Exception:
                    pass
                return fallback

            def _lum(c):
                return (0.299 * ((c >> 16) & 255)
                        + 0.587 * ((c >> 8) & 255)
                        + 0.114 * (c & 255))

            accent = _to_color(_theme_color("colorPrimary", 0xFF3F7FCB))
            accent_dark = _to_color((accent & 0x00FFFFFF) | 0x99000000)
            text_secondary = _to_color(_theme_color("textColorSecondary", 0xFF757575))
            bg_col = _to_color(_theme_color("colorBackground", 0xFF151515))
            is_dark = _lum(bg_col) < 128
            card_bg = _to_color(0x1AFFFFFF if is_dark else 0xFFF4F5F8)
            on_surface = _to_color(_theme_color("colorOnSurface", 0xFF111111 if is_dark else 0xFF202124))
            accent_dot = _to_color((accent & 0x00FFFFFF) | 0x3D000000)
            gradient_class = jclass("android.graphics.drawable.GradientDrawable")

            def rounded_bg(solid, radius, stroke=0, stroke_color=0):
                g = gradient_class()
                try:
                    g.setColor(solid)
                    g.setCornerRadius(float(radius))
                    if stroke and stroke_color:
                        g.setStroke(int(stroke), stroke_color)
                except Exception:
                    pass
                return g

            def set_bg(view, bg):
                try:
                    view.setBackground(bg)
                except Exception:
                    try:
                        view.setBackgroundDrawable(bg)
                    except Exception:
                        pass

            def ripple_bg(solid, radius, stroke=0, stroke_color=0):
                """带按压涟漪的背景（API 21+），失败回退普通圆角背景。"""
                try:
                    ripple_class = jclass("android.graphics.drawable.RippleDrawable")
                    csl_class = jclass("android.content.res.ColorStateList")
                    csl = csl_class.valueOf(
                        _to_color((accent & 0x00FFFFFF) | 0x3D000000)
                    )
                    return ripple_class(csl, rounded_bg(solid, radius, stroke, stroke_color), None)
                except Exception:
                    return rounded_bg(solid, radius, stroke, stroke_color)

            root = linear_layout_class(activity)
            root.setOrientation(linear_layout_class.VERTICAL)
            root.setPadding(pad, spacing, pad, pad)

            if not owner._watchlist:
                tip = text_view_class(activity)
                tip.setText("还没有追看的剧。\n\n用「🔍 搜索添加」搜索并点击海报即可加入追更。")
                tip.setTextColor(text_secondary)
                tip.setTextSize(14.0)
                root.addView(tip)
            else:
                hint = text_view_class(activity)
                hint.setText("点击列表右侧 ✕，即可从追更中移除（共 {} 部）".format(len(owner._watchlist)))
                hint.setTextColor(text_secondary)
                hint.setTextSize(12.5)
                hint.setPadding(0, 0, 0, spacing)
                root.addView(hint)

                for it in owner._watchlist:
                    try:
                        tid = str(it.get("id") or "")
                        nm = it.get("name") or "未知"

                        row = linear_layout_class(activity)
                        row.setOrientation(linear_layout_class.HORIZONTAL)
                        row.setGravity(0x10)  # CENTER_VERTICAL
                        set_bg(row, ripple_bg(card_bg, dp_pr, max(1, int(density)), accent_dot))
                        rp = linear_layout_class.LayoutParams(
                            linear_layout_class.LayoutParams.MATCH_PARENT,
                            linear_layout_class.LayoutParams.WRAP_CONTENT,
                        )
                        rp.setMargins(0, 0, 0, int(spacing * 0.5))
                        row.setLayoutParams(rp)
                        row.setPadding(int(density * 10), int(density * 6), int(density * 10), int(density * 6))

                        label = text_view_class(activity)
                        label.setText(nm)
                        label.setTextColor(on_surface)
                        label.setTextSize(15.0)
                        label.setGravity(0x10)
                        label.setLayoutParams(
                            linear_layout_class.LayoutParams(
                                0, linear_layout_class.LayoutParams.WRAP_CONTENT, 1.0
                            )
                        )
                        kick = text_view_class(activity)
                        kick.setText("移除 ✕")
                        kick.setTextColor(accent)
                        kick.setTextSize(12.5)
                        kick.setPadding(int(density * 8), 0, 0, 0)
                        row.addView(label)
                        row.addView(kick)

                        def _make_remove(_tid, _nm):
                            class RowClick(dynamic_proxy(view_click_listener)):
                                def onClick(self, view):
                                    try:
                                        owner._watch_remove(_tid)
                                        _toast("已从追更移除《{}》".format(_nm))
                                        _rebuild()
                                    except Exception as exc:
                                        _toast("操作失败: {}".format(exc)[:60])
                            return RowClick()

                        row.setOnClickListener(_make_remove(tid, nm))
                        root.addView(row)
                    except Exception:
                        continue

            scroll = scroll_view_class(activity)
            scroll.setFillViewport(True)
            scroll.addView(root)

            class CancelListener(dynamic_proxy(click_listener)):
                def onClick(self, dlg, which):
                    try:
                        dlg.dismiss()
                    except Exception:
                        pass

            builder = builder_class(activity)
            builder.setTitle("🗂 管理追更")
            builder.setView(scroll)
            builder.setNegativeButton("关闭", CancelListener())
            try:
                _dlg = builder.show()
                try:
                    _win = _dlg.getWindow()
                    if _win is not None:
                        _dm = activity.getResources().getDisplayMetrics()
                        _max_w = int(430 * density + 0.5)
                        if _dm.widthPixels > _max_w:
                            _attrs = _win.getAttributes()
                            _attrs.width = _max_w
                            _win.setAttributes(_attrs)
                except Exception:
                    pass
            except Exception:
                pass

        class ShowDialog(dynamic_proxy(runnable_class)):
            def run(self):
                try:
                    _run_dialog_content()
                except Exception:
                    pass

        # 自动重试直到 Activity 就绪再弹窗，失败给 Toast 反馈（不再静默）
        self._show_dialog_after_ready(ShowDialog(), "管理追更弹窗打开失败，请下拉刷新后重试")

    def _show_dialog_after_ready(self, show_runnable, fail_msg="弹窗打开失败，请下拉刷新后重试",
                                 initial_delay=200, retry_delay=1200, max_attempts=5):
        """轮询等待 Activity 就绪（非 None、未 finishing、未 destroyed）后再弹窗。

        替代原来固定延迟 600ms 的投递方式：Activity 未就绪或弹窗时机不对时自动重试，
        重试耗尽给出可见 Toast 反馈，绝不静默失败。
        """
        from java import dynamic_proxy, jclass

        owner = self
        runnable_class = jclass("java.lang.Runnable")
        toast_class = jclass("android.widget.Toast")

        def _delayed_show(attempt):
            act = None
            try:
                act = owner._current_android_activity(jclass)
            except Exception:
                act = None
            valid = False
            if act is not None:
                try:
                    valid = not bool(act.isFinishing()) and not bool(act.isDestroyed())
                except Exception:
                    valid = True
            if valid:
                try:
                    act.runOnUiThread(show_runnable)
                    return
                except Exception:
                    pass
            if attempt + 1 >= max_attempts:
                try:
                    if act is not None:
                        toast_class.makeText(act, fail_msg, toast_class.LENGTH_LONG).show()
                except Exception:
                    pass
                return
            try:
                handler_cls = jclass("android.os.Handler")
                looper_cls = jclass("android.os.Looper")
                handler = handler_cls(looper_cls.getMainLooper())

                class _Retry(dynamic_proxy(runnable_class)):
                    def run(self):
                        _delayed_show(attempt + 1)

                handler.postDelayed(_Retry(), retry_delay)
            except Exception:
                import threading
                t = threading.Timer(retry_delay / 1000.0, lambda: _delayed_show(attempt + 1))
                t.daemon = True
                t.start()

        try:
            handler_cls = jclass("android.os.Handler")
            looper_cls = jclass("android.os.Looper")
            handler = handler_cls(looper_cls.getMainLooper())

            class _Post(dynamic_proxy(runnable_class)):
                def run(self):
                    _delayed_show(0)

            handler.postDelayed(_Post(), initial_delay)
        except Exception:
            import threading
            t = threading.Timer(initial_delay / 1000.0, lambda: _delayed_show(0))
            t.daemon = True
            t.start()

    def _current_android_activity(self, jclass):
        """反射获取当前 Android Activity（兼容 Fongmi TVBox / 本地影仓）。"""
        app_class = jclass("com.fongmi.android.tv.App")
        activity_class = jclass("android.app.Activity")
        modifier_class = jclass("java.lang.reflect.Modifier")
        app_info = app_class.getClass()
        activity_info = activity_class.getClass()

        for method in app_info.getDeclaredMethods():
            try:
                if not modifier_class.isStatic(method.getModifiers()):
                    continue
                if len(method.getParameterTypes()) != 0:
                    continue
                if not activity_info.isAssignableFrom(method.getReturnType()):
                    continue
                method.setAccessible(True)
                try:
                    activity = method.invoke(None, [])
                except Exception:
                    activity = method.invoke(None)
                if activity is not None:
                    return activity
            except Exception:
                continue
        return None