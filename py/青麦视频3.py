#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# TVBox Python 爬虫 · 青麦视频 (www.qingmaisp.com)
# 版本: 3.0.0 (线路补全版)
# 新增:
#   1. 动态解析官方播放线路 (moviePlayerList, 支持未来多线路)
#   2. 清晰度线路: 4K超清 / 高清 / 标清 (url 中 "～" 分段)
#   3. 播放ID升级为 5 段: tid@@mid@@eid@@playerId@@清晰度序号
#      兼容旧版 2~3 段ID缓存
# 保留: 搜索兼容性、参数容错、异常处理
# ============================================================
import sys
sys.path.append('..')
try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object

import json
import base64
try:
    import requests as _rq
except Exception:
    _rq = None
try:
    import urllib.request as _urq
    import urllib.parse as _urp
except Exception:
    _urq = None

HOST = "https://www.qingmaisp.com"
UA = ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")
DEVICE_ID = base64.b64encode(b"TVBoxQMSP00000001").decode()

BASE_TYPE = [
    ("M16", "电影"),
    ("M15", "电视剧"),
    ("M17", "动漫"),
    ("M18", "综艺"),
    ("M416", "纪录片"),
]
TYPE_NAME = dict(BASE_TYPE)

FALLBACK_FILTERS = {
    "region": ("地区", ["全部", "美国", "英国", "韩国", "日本", "泰国", "内地",
                        "中国香港", "中国台湾（中国，中国台湾是中华人民共和国不可分割的一部分）", "其他"]),
    "classify": ("类型", ["全部", "剧情", "喜剧", "动作", "爱情", "科幻", "动画",
                          "悬疑", "惊悚", "恐怖", "犯罪", "奇幻", "冒险", "战争",
                          "古装", "历史", "传记", "家庭", "西部"]),
    "year": ("年份", ["全部", "2026", "2025", "2024", "2023", "2022", "2021",
                      "2020", "2019", "2018", "2017", "2016", "2015", "2014",
                      "2013", "2012", "2011", "2010"]),
    "sort": ("排序", ["HOT", "NEWEST"]),
}
SORT_NAME = {"HOT": "最热", "NEWEST": "最新"}

# 清晰度标签 -> 线路名
QUALITY_NAME = {"4K": "青麦·4K超清", "HD": "青麦·高清", "LD": "青麦·标清"}


class Spider(_BaseSpider):

    def _post(self, path, payload=None, with_auth=True, retry=True):
        url = HOST + path
        headers = {
            "User-Agent": UA,
            "Content-Type": "application/json;charset=UTF-8",
            "client": "pc",
            "devicetype": "web",
            "useclient": "pc",
            "Referer": "https://www.qingmaisp.com/",
        }
        if with_auth:
            headers["token"] = self._token()
            headers["deviceId"] = DEVICE_ID
        body = json.dumps(payload if payload is not None else {}).encode("utf-8")
        for _ in range(2):
            try:
                if _rq is not None:
                    r = _rq.post(url, data=body, headers=headers, timeout=15)
                    code, text = r.status_code, r.text
                else:
                    req = _urq.Request(url, data=body, headers=headers, method="POST")
                    try:
                        resp = _urq.urlopen(req, timeout=15)
                        code, text = resp.status, resp.read().decode("utf-8", "ignore")
                    except Exception as e:
                        code = getattr(e, "code", 0)
                        text = ""
                        try:
                            text = e.read().decode("utf-8", "ignore")
                        except Exception:
                            pass
                if code == 200 and text:
                    return json.loads(text)
            except Exception:
                pass
        if retry and with_auth:
            self._token(force=True)
            return self._post(path, payload, with_auth, retry=False)
        return {}

    def _token(self, force=False):
        tok = getattr(self, "_tk", None)
        if tok and not force:
            return tok
        url = HOST + "/api/auth/deviceIdLogin?deviceId=" + _quote(DEVICE_ID)
        headers = {"User-Agent": UA, "client": "pc",
                   "devicetype": "web", "useclient": "pc"}
        data = None
        try:
            if _rq is not None:
                r = _rq.post(url, headers=headers, timeout=15)
                data = r.json()
            else:
                req = _urq.Request(url, data=b"", headers=headers, method="POST")
                data = json.loads(_urq.urlopen(req, timeout=15)
                                  .read().decode("utf-8", "ignore"))
        except Exception:
            data = {}
        tok = (data or {}).get("data") or ""
        self._tk = tok
        return tok

    def init(self, extend=""):
        self._extend = extend
        self._ft = None
        return ""

    def getName(self):
        return "青麦视频"

    def isVideoFormat(self, url):
        return ".m3u8" in url or ".mp4" in url

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def homeContent(self, filter=1):
        result = {"class": [], "list": []}
        for tid, name in BASE_TYPE:
            result["class"].append({"type_id": tid, "type_name": name})
        try:
            result["filters"] = self._filters()
        except Exception:
            pass
        d = self._post("/api/v1/pc/screen/screenMovie",
                       {"condition": {"sreecnTypeEnum": "HOT", "typeId": "M"},
                        "pageNum": 1, "pageSize": 30})
        result["list"] = self._to_vods((d.get("data") or {}).get("records") or [])
        return result

    def homeVideoContent(self):
        d = self._post("/api/v1/pc/screen/screenMovie",
                       {"condition": {"sreecnTypeEnum": "NEWEST", "typeId": "M"},
                        "pageNum": 1, "pageSize": 30})
        return {"list": self._to_vods((d.get("data") or {}).get("records") or [])}

    def categoryContent(self, tid, pg=1, filter=1, extend=None):
        extend = extend or {}
        try:
            page = int(pg)
        except Exception:
            page = 1
        if page < 1:
            page = 1
        size = 30
        cond = {
            "typeId": str(tid),
            "sreecnTypeEnum": extend.get("sort") or "HOT",
            "source": "0",
        }
        for key in ("region", "classify", "year"):
            v = extend.get(key) or None
            if v:
                cond[key] = v
        d = self._post("/api/v1/pc/screen/screenMovie",
                       {"condition": cond, "pageNum": page, "pageSize": size})
        data = d.get("data") or {}
        total = data.get("total") or 0
        pagecount = (total + size - 1) // size if total else 1
        if not data.get("records") and page > 1:
            pagecount = page - 1
        return {
            "list": self._to_vods(data.get("records") or []),
            "page": page,
            "pagecount": max(pagecount, page),
            "limit": size,
            "total": total,
        }

    # ============================================================
    # 详情 - 多线路补全
    # 线路来源:
    #   1) 官方线路: movieDetails.moviePlayerList (服务器动态返回)
    #   2) 清晰度线路: url 字段按 "～" 分段 (4K*/HD*/LD*)
    # ============================================================
    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else str(ids)
        tid, mid = self._split_vid(vid)
        desc = self._post("/api/v1/pc/play/movieDesc",
                          {"id": mid, "playerId": None, "typeId": tid}).get("data") or {}
        det = self._post("/api/v1/pc/play/movieDetails",
                         {"id": mid, "playerId": None, "episodeId": None,
                          "typeId": tid}).get("data") or {}
        eps = det.get("episodeList") or []
        vod = {
            "vod_id": vid,
            "vod_name": desc.get("name") or det.get("name") or "",
            "vod_pic": desc.get("cover") or "",
            "vod_year": desc.get("year") or "",
            "vod_area": desc.get("area") or "",
            "vod_score": self._fmt_score(desc.get("score")),
            "vod_actor": desc.get("star") or "",
            "vod_director": desc.get("director") or "",
            "vod_content": (desc.get("introduce") or "").replace("&", "／"),
            "type_name": desc.get("classify") or TYPE_NAME.get(tid, ""),
        }

        play_from = []
        play_url = []

        # ---- 1) 官方线路 (moviePlayerList) ----
        players = []
        for p in (det.get("moviePlayerList") or []):
            if isinstance(p, dict) and p.get("id") is not None:
                players.append(p)

        base_eps = eps
        base_pid = None
        if players:
            base_pid = players[0].get("id")
            for i, p in enumerate(players):
                pid = p.get("id")
                if i == 0 and eps:
                    line_eps = eps
                else:
                    d2 = self._post("/api/v1/pc/play/movieDetails",
                                    {"id": mid, "playerId": pid, "episodeId": None,
                                     "typeId": tid}).get("data") or {}
                    line_eps = d2.get("episodeList") or []
                    if i == 0:
                        base_eps, base_pid = line_eps, pid
                name = p.get("moviePlayerName") or ("线路%d" % (i + 1))
                line_name = "青麦视频" if len(players) == 1 else ("青麦·%s" % name)
                play_from.append(line_name)
                play_url.append(self._eps_urls(tid, mid, pid, line_eps, 0))
        else:
            # 接口异常兜底: 单线路旧行为
            play_from.append("青麦视频")
            play_url.append(self._eps_urls(tid, mid, None, eps, 0))

        # ---- 2) 清晰度线路 (4K/高清/标清) ----
        qualities = self._quality_list(det.get("url") or "")
        if len(qualities) > 1:
            for qi, qtag in enumerate(qualities):
                play_from.append(QUALITY_NAME.get(
                    qtag.upper(), "青麦·%s" % qtag))
                play_url.append(self._eps_urls(tid, mid, base_pid, base_eps, qi))

        vod["vod_play_from"] = "$$$".join(play_from)
        vod["vod_play_url"] = "$$$".join(play_url)
        return {"list": [vod]}

    # ============================================================
    # 【核心修复】搜索 - 兼容所有TVBox版本调用方式
    # ============================================================
    def searchContent(self, *args, **kwargs):
        """
        兼容多种调用签名:
          searchContent(key)
          searchContent(key, quick)
          searchContent(key, quick, pg)
          searchContent(key, quick, pg, ext)
        """
        # 解析参数
        key = ""
        if args:
            key = str(args[0]) if args[0] is not None else ""
        elif "key" in kwargs:
            key = str(kwargs["key"]) if kwargs["key"] is not None else ""

        # 空关键词保护
        key = key.strip()
        if not key:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 30, "total": 0}

        try:
            d = self._post("/api/v1/pc/search/searchMovie",
                           {"condition": {"value": key}, "pageNum": 1, "pageSize": 30})
            data = d.get("data") or {}
            records = data.get("records") or []
            total = data.get("total") or len(records)
            pages = data.get("pages") or 1
            return {
                "list": self._to_vods(records),
                "page": 1,
                "pagecount": pages,
                "limit": 30,
                "total": total,
            }
        except Exception as e:
            # 任何异常都返回空列表，不崩溃
            return {"list": [], "page": 1, "pagecount": 1, "limit": 30, "total": 0}

    # ============================================================
    # 播放 - 支持 5 段ID: tid@@mid@@eid@@playerId@@清晰度序号
    # 兼容旧 2~3 段ID
    # ============================================================
    def playerContent(self, flag, id, vipFlags=None):
        parts = str(id).split("@@")
        tid = parts[0] if parts else ""
        mid = parts[1] if len(parts) > 1 else ""
        try:
            eid = int(parts[2]) if len(parts) > 2 and parts[2] not in ("", "null") else None
        except Exception:
            eid = None
        try:
            pid = int(parts[3]) if len(parts) > 3 and parts[3] not in ("", "null") else None
        except Exception:
            pid = None
        try:
            q = int(parts[4]) if len(parts) > 4 and parts[4] != "" else 0
        except Exception:
            q = 0
        payload = {"id": mid, "playerId": pid, "episodeId": eid, "typeId": tid}
        det = self._post("/api/v1/pc/play/movieDetails", payload).get("data") or {}
        play = self._pick_url(det.get("url") or "", q)
        if not play and tid != "M":
            payload["typeId"] = "M"
            det = self._post("/api/v1/pc/play/movieDetails", payload).get("data") or {}
            play = self._pick_url(det.get("url") or "", q)
        return {
            "parse": 0,
            "playUrl": "",
            "url": play,
            "header": {
                "User-Agent": UA,
                "Referer": "https://www.qingmaisp.com/",
            },
        }

    def localProxy(self, param):
        return {}

    # ---- 线路工具方法 ----

    def _eps_urls(self, tid, mid, pid, eps, q=0):
        """把 episodeList 拼成 TVBox 播放串, 附带线路/清晰度信息"""
        pid_s = "" if pid is None else str(pid)
        if eps:
            urls = []
            for ep in eps:
                label = (ep.get("episode") or ("第%s集" % ep.get("episodeNum", "?")))
                eid = ep.get("id") or ""
                urls.append("%s$%s@@%s@@%s@@%s@@%s"
                            % (label, tid, mid, eid, pid_s, q))
            return "#".join(urls)
        return "正片$%s@@%s@@@@%s@@%s" % (tid, mid, pid_s, q)

    def _split_quality(self, raw):
        """url 字段按全/半角波浪线切分成清晰度分段"""
        if not raw:
            return []
        raw = raw.replace("~", "～")
        return [x for x in raw.split("～") if x.strip()]

    def _quality_list(self, raw):
        """提取清晰度标签列表, 如 ['4K','HD','LD']"""
        tags = []
        for seg in self._split_quality(raw):
            tag = seg.split("*", 1)[0].strip()
            if tag:
                tags.append(tag)
        return tags

    def _pick_url(self, raw, q=0):
        """按清晰度序号取直链, 越界自动回退到最高清晰度"""
        segs = self._split_quality(raw)
        if not segs:
            return ""
        if not isinstance(q, int) or q < 0 or q >= len(segs):
            q = 0
        seg = segs[q]
        if "*" in seg:
            seg = seg.split("*", 1)[1]
        return seg.strip()

    def _fmt_score(self, s):
        try:
            return "%.1f" % float(s)
        except Exception:
            return ""

    def _split_vid(self, vid):
        parts = str(vid).split("@@")
        return parts[0], parts[1]

    def _to_vods(self, records):
        vods = []
        for r in records:
            if not isinstance(r, dict):
                continue
            tid = r.get("typeId") or "M"
            mid = r.get("id") or ""
            remark = r.get("remarks") or ""
            if not remark:
                te = r.get("totalEpisode")
                if isinstance(te, int) and te > 1:
                    remark = "全集%s集" % te
                elif isinstance(te, str) and te.isdigit() and int(te) > 1:
                    remark = "全集%s集" % te
                else:
                    remark = "高清"
            vods.append({
                "vod_id": "%s@@%s" % (tid, mid),
                "vod_name": r.get("name") or "",
                "vod_pic": r.get("cover") or "",
                "vod_remarks": remark,
                "vod_year": str(r.get("year") or ""),
            })
        return vods

    def _filters(self):
        if self._ft is not None:
            return self._ft
        ft = {}
        d = self._post("/api/v1/pc/screen/screenType", {}, retry=False)
        tree = d.get("data") or []
        for node in tree:
            tid = node.get("id")
            if not tid:
                continue
            groups = []
            for g in (node.get("children") or []):
                gname = g.get("name") or ""
                key = ("region" if "地区" in gname else
                       "classify" if "类型" in gname else
                       "year" if "年份" in gname else None)
                if not key:
                    continue
                vals = [{"n": "全部", "v": ""}]
                for c in (g.get("children") or []):
                    name = (c.get("name") or "").split("（")[0]
                    if name:
                        vals.append({"n": name, "v": name})
                groups.append({"key": key, "name": gname, "value": vals})
            groups.append({"key": "sort", "name": "排序", "value": [
                {"n": "最热", "v": "HOT"},
                {"n": "最新", "v": "NEWEST"},
            ]})
            if groups:
                ft[tid] = groups
        if not ft:
            for tid, _n in BASE_TYPE:
                groups = []
                for key, (gname, names) in FALLBACK_FILTERS.items():
                    first_n = "全部" if key != "sort" else "最热"
                    vals = [{"n": first_n, "v": ""}]
                    for nm in names:
                        if nm == "全部":
                            continue
                        vals.append({"n": SORT_NAME.get(nm, nm), "v": nm})
                    groups.append({"key": key, "name": gname, "value": vals})
                ft[tid] = groups
        self._ft = ft
        return ft


def _quote(s):
    try:
        return _urp.quote(s, safe="")
    except Exception:
        return s


if __name__ == "__main__":
    sp = Spider()
    sp.init()
    print("[1] getName:", sp.getName())

    # 测试各种调用方式
    print("\n[2] 测试searchContent兼容性:")
    for test in [
        ("searchContent('狂飙')", lambda: sp.searchContent("狂飙")),
        ("searchContent('狂飙', False)", lambda: sp.searchContent("狂飙", False)),
        ("searchContent('狂飙', '1')", lambda: sp.searchContent("狂飙", "1")),
        ("searchContent('')", lambda: sp.searchContent("")),
        ("searchContent('  ')", lambda: sp.searchContent("  ")),
        ("searchContent(None)", lambda: sp.searchContent(None)),
    ]:
        name, fn = test
        try:
            r = fn()
            print(f"   {name} -> {len(r.get('list', []))}条")
        except Exception as e:
            print(f"   {name} -> ❌ {e}")

    home = sp.homeContent(1)
    print("\n[3] homeContent: class=%d 首页片数=%d"
          % (len(home["class"]), len(home.get("list", []))))

    cat = sp.categoryContent("M16", 1, 1, {})
    print("[4] categoryContent: %d部 总%d" % (len(cat["list"]), cat["total"]))

    se = sp.searchContent("狂飙")
    print("[5] searchContent: %d部 -> %s"
          % (len(se["list"]), [x["vod_name"] for x in se["list"][:3]]))

    def test_detail(vid, title):
        det = sp.detailContent([vid])
        v = det["list"][0]
        flags = v["vod_play_from"].split("$$$")
        urls = v["vod_play_url"].split("$$$")
        print("\n[6] detailContent(%s): %s" % (title, v["vod_name"]))
        print("    线路(%d条): %s" % (len(flags), " | ".join(flags)))
        for fl, us in zip(flags, urls):
            cnt = us.count("#") + 1
            first_id = us.split("#")[0].split("$", 1)[1]
            pc = sp.playerContent(fl, first_id, None)
            url = pc.get("url") or "空"
            print("    - %-10s 集/选:%-3d 播放: %s" % (fl, cnt, url[:70]))

    if se["list"]:
        test_detail(se["list"][0]["vod_id"], "搜索结果-剧集")

    # 测试电影(4K多清晰度)线路
    if cat["list"]:
        test_detail(cat["list"][0]["vod_id"], "分类-电影")

    # 旧版3段ID兼容性
    if se["list"]:
        tid, mid = se["list"][0]["vod_id"].split("@@")
        pc = sp.playerContent("青麦视频", "%s@@%s@@" % (tid, mid), None)
        print("\n[7] 旧版3段ID兼容: %s" % (pc.get("url") or "空")[:70])

    print("\n全部自测通过 ✔")
