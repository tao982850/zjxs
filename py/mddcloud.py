# coding=utf-8
# -*- coding: utf-8 -*-
"""
埋堆堆 H5 (m.mddcloud.com.cn) —— FongMi / TVBox 系 py 源  v2
v2 变更：改为壳标准 class Spider 结构（v1 模块级函数默影视不加载）
站型：Nuxt SSR + activity.mddcloud.com.cn JSON API（MD5 签名）
链路：分类词表 -> 列表(筛选/分页) -> 详情(剧集表) -> 取流(m3u8)
依赖：仅标准库
"""
import json
import time
import hashlib
from urllib import request

from base.spider import Spider as BaseSpider

API = "https://activity.mddcloud.com.cn"
PK = "8a4af424bd714be5b2baacbe3cf5bbbe0131effeb92e99356ef1662884558f28"
UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36")
HDR = {
    "Content-Type": "application/json;charset=UTF-8",
    "User-Agent": UA,
    "Origin": "https://m.mddcloud.com.cn",
    "Referer": "https://m.mddcloud.com.cn/",
    "Accept": "application/json, text/plain, */*",
}
PAGE = 20


class Spider(BaseSpider):

    _tbl = {"t": 0, "v": None}      # 分类词表缓存（6h，类级共享）

    # ------------------------------------------------------------ 基础
    def _sos(self, d):
        buf = []
        for k in sorted(d.keys()):
            v = d[k]
            if isinstance(v, (dict, list)):
                buf.append(k + "=" + json.dumps(v, ensure_ascii=False,
                                                separators=(',', ':')) + "&")
            else:
                buf.append(k + "=" + str(v) + "&")
        return "".join(buf)

    def _post(self, path, data):
        try:
            ts = int(time.time() * 1000)
            src = "time:%d|privateKey:%s|data:%s" % (ts, PK, self._sos(data))
            body = json.dumps({
                "time": ts,
                "sign": hashlib.md5(src.encode("utf-8")).hexdigest(),
                "data": data,
            }, ensure_ascii=False).encode("utf-8")
            req = request.Request(API + path, data=body, headers=HDR)
            with request.urlopen(req, timeout=15) as r:
                j = json.loads(r.read().decode("utf-8", "ignore"))
            return j.get("data") if j.get("msgType") == 0 else None
        except Exception:
            return None

    def _classify(self):
        if self._tbl["v"] and time.time() - self._tbl["t"] < 21600:
            return self._tbl["v"]
        d = self._post("/api/vod/classify/list.action", {})
        if isinstance(d, list) and d:
            self._tbl["v"] = d
            self._tbl["t"] = time.time()
        return self._tbl["v"] or []

    def _mk(self, it):
        total = it.get("totalNum") or 0
        return {
            "vod_id": it.get("vodUuid") or it.get("uuid"),
            "vod_name": it.get("name") or "",
            "vod_pic": it.get("downImage") or it.get("coverImage") or "",
            "vod_remarks": ("共%d集" % total) if total else "",
            "vod_year": "",
        }

    # ------------------------------------------------------------ 壳接口
    def getName(self):
        return "埋堆堆"

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, param):
        return [200, "text/plain", "ok"]

    # ------------------------------------------------------------ 首页
    def homeContent(self, filter=False):
        try:
            cls = [{"type_id": "hot", "type_name": "最热"},
                   {"type_id": "new", "type_name": "最新"},
                   {"type_id": "good", "type_name": "好评"},
                   {"type_id": "all", "type_name": "全部"}]
            for f in self._classify():
                if f.get("fieldCode") == "material":
                    for w in f.get("words") or []:
                        if w.get("uuid"):
                            cls.append({"type_id": "m:" + w["uuid"],
                                        "type_name": w.get("word") or ""})
            fl = {}
            for f in self._classify():
                code = f.get("fieldCode") or ""
                if code not in ("year", "lang", "region"):
                    continue
                vals = [{"n": "全部", "v": ""}]
                for w in f.get("words") or []:
                    if w.get("uuid"):
                        vals.append({"n": w.get("word") or "", "v": w["uuid"]})
                fl[code] = {"key": code,
                            "name": (f.get("fieldName") or code).replace("_name", ""),
                            "value": vals}
            filters = {}
            for c in cls:
                filters[c["type_id"]] = [fl["year"], fl["lang"], fl["region"]]
            videos = self.categoryContent("hot", 1, False, {}).get("list", [])
            return {"class": cls, "filters": filters, "list": videos}
        except Exception:
            return {"class": [], "filters": {}, "list": []}

    def homeVideoContent(self):
        return {"list": self.categoryContent("hot", 1, False, {}).get("list", [])}

    # ------------------------------------------------------------ 分类
    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            ext = extend or {}
            uu = []
            if isinstance(tid, str) and tid.startswith("m:") and len(tid) > 2:
                uu.append(tid[2:])
            for k in ("year", "lang", "region"):
                v = ext.get(k)
                if v and v not in uu:
                    uu.append(v)
            order = {"new": 1, "good": 2}.get(tid, 0)
            pg = int(pg) if str(pg).isdigit() else 1
            d = self._post("/api/vod/classify/word/search.action", {
                "uuidList": uu,
                "rows": PAGE,
                "startRow": (pg - 1) * PAGE,
                "isVip": -1,
                "orderType": order,
            })
            lst = [self._mk(x) for x in (d or [])
                   if x.get("vodUuid") or x.get("uuid")]
            return {"page": pg, "pagecount": 9999, "limit": PAGE,
                    "total": 999999, "list": lst}
        except Exception:
            return {"page": 1, "pagecount": 1, "limit": PAGE, "total": 0, "list": []}

    # ------------------------------------------------------------ 详情
    def detailContent(self, ids):
        try:
            vid = ids[0] if isinstance(ids, list) else ids
            vid = str(vid)
            if "|" in vid:
                vid = vid.split("|")[0]
            d = self._post("/api/vod/getVodInfo.action", {"vodUuid": vid, "num": 1})
            if not d:
                return {"list": []}
            plays = []
            for s in d.get("vodSactionList") or []:
                nm = s.get("name") or ("第%s集" % s.get("num"))
                plays.append("%s$%s|%s" % (nm, s.get("vodUuid") or vid, s.get("num")))
            if not plays:
                plays = ["正片$%s|1" % vid]
            yr = ""
            ts = d.get("firstSowingTime")
            if ts:
                try:
                    yr = time.strftime("%Y", time.localtime(int(ts) / 1000))
                except Exception:
                    yr = ""
            return {"list": [{
                "vod_id": vid,
                "vod_name": d.get("name") or "",
                "vod_pic": d.get("coverImage") or d.get("downImage") or "",
                "type_name": "综艺" if d.get("vodType") == 2 else (
                    "剧集" if d.get("vodType") == 0 else ""),
                "vod_year": yr,
                "vod_area": "",
                "vod_remarks": "共%s集" % (d.get("totalNum") or len(plays)),
                "vod_actor": d.get("starring") or "",
                "vod_director": d.get("director") or "",
                "vod_content": (d.get("introduction") or "").strip(),
                "vod_play_from": "埋堆堆",
                "vod_play_url": "#".join(plays),
            }]}
        except Exception:
            return {"list": []}

    # ------------------------------------------------------------ 播放
    def playerContent(self, flag, id, vipFlags=None):
        try:
            s = str(id)
            if "|" in s:
                vu, num = s.split("|")[0], s.split("|")[1]
            else:
                vu, num = s, "1"
            d = self._post("/api/vod/getTrySaction.action",
                           {"vodUuid": vu, "num": int(num)})
            url = ""
            if isinstance(d, dict):
                url = (d.get("tryM3u8Url") or d.get("tryUrl")
                       or d.get("tryMp4Url") or "")
            if not url:
                return {"parse": 0, "playUrl": "", "url": "", "header": ""}
            return {"parse": 0, "playUrl": "", "url": url, "header": ""}
        except Exception:
            return {"parse": 0, "playUrl": "", "url": "", "header": ""}

    # ------------------------------------------------------------ 搜索
    def searchContent(self, key, quick=False, pg=1):
        # 站点 H5 未开放搜索入口与接口
        return {"list": []}
