# coding=utf-8
# -*- coding: utf-8 -*-
"""
埋堆堆 (www.mddcloud.com.cn) —— FongMi / TVBox 系 py 源  v3
v3 变更：分类列表改为 PC 站 tab 页 Nuxt SSR 数据源（官网 search.action 接口
        已停服返回 0 行，getTabModules 接口路径不可推导，SSR 页面为可靠来源）。
站型：Nuxt SSR + activity.mddcloud.com.cn JSON API（MD5 签名）
链路：tab 分类 -> SSR 列表(单页全量/切片分页) -> 详情(剧集表) -> 取流(m3u8)
依赖：仅标准库
"""
import json
import math
import re
import time
import hashlib
from urllib import request

from base.spider import Spider as BaseSpider

API = "https://activity.mddcloud.com.cn"
PK = "8a4af424bd714be5b2baacbe3cf5bbbe0131effeb92e99356ef1662884558f28"
UA_M = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36")
UA_PC = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HDR = {
    "Content-Type": "application/json;charset=UTF-8",
    "User-Agent": UA_M,
    "Origin": "https://m.mddcloud.com.cn",
    "Referer": "https://m.mddcloud.com.cn/",
    "Accept": "application/json, text/plain, */*",
}
SSR_BASE = "https://www.mddcloud.com.cn/tab/%s"
PAGE = 20

# PC 站可访问的 tab（tabUuid -> tabName，顺序即展示顺序）
TABS = [
    ("820fb1eaf0f411e78c9a246e967656d2", "电视剧"),
    ("ff8080816775403b01677d06c9e00d36", "综艺"),
    ("ff8080817767113f017767474a65002b", "精选"),
    ("ff80808180abdd5d0180cbbc438330d9", "VIP尊享"),
    ("ff80808177f291f801781648627c14dd", "爱回家"),
]


def _parse_nuxt(payload):
    """解析 SSR 内联的 window.__NUXT__=(function(a,b,...){return {...}}(ARGS));"""
    p = payload.strip()
    if p.endswith(";"):
        p = p[:-1]
    if not p.startswith("("):
        return None
    m = re.match(r"\(function\(([^)]*)\)\s*\{", p)
    if not m:
        return None
    params = [x.strip() for x in m.group(1).split(",") if x.strip()]
    body_start = m.end()

    # 括号深度扫描到 return 对象结束（函数体 '{' 已被正则消费，depth 从 1 起）
    depth = 1
    i = body_start
    n = len(p)
    in_str = False
    esc = False
    return_obj_end = None
    while i < n:
        c = p[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 1:
                    return_obj_end = i
                if depth == 0:
                    break
        i += 1
    if return_obj_end is None:
        return None
    body = p[body_start:return_obj_end + 1].strip()
    if body.startswith("return"):
        body = body[len("return"):].strip()
    if not body.startswith("{"):
        return None
    rest = p[return_obj_end + 1:].strip()
    if rest.startswith("}"):
        rest = rest[1:].strip()
    if rest.startswith(";"):
        rest = rest[1:].strip()
    if not rest.startswith("("):
        return None

    # 尾部实参数组结束
    depth = 0
    in_str = False
    esc = False
    args_end = None
    for j, c in enumerate(rest):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    args_end = j
                    break
    if args_end is None:
        return None
    args_str = rest[1:args_end]

    # 顶层按逗号切分实参
    parts = []
    cur = []
    depth = 0
    in_str = False
    esc = False
    for c in args_str:
        if in_str:
            cur.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
                cur.append(c)
            elif c in "[{(":
                depth += 1
                cur.append(c)
            elif c in "]})":
                depth -= 1
                cur.append(c)
            elif c == "," and depth == 0:
                parts.append("".join(cur))
                cur = []
            else:
                cur.append(c)
    if "".join(cur).strip():
        parts.append("".join(cur))
    if len(parts) != len(params):
        return None
    args = []
    for t in parts:
        ts = t.strip()
        if ts == "undefined":
            args.append(None)
        else:
            try:
                args.append(json.loads(ts))
            except Exception:
                return None

    # 词法替换：对象 key 补引号、参数引用替换、undefined -> null
    ident_re = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
    out = []
    i = 0
    in_str = False
    esc = False
    while i < len(body):
        c = body[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        mm = ident_re.match(body, i)
        if mm:
            name = mm.group(0)
            j = mm.end()
            k = j
            while k < len(body) and body[k] in " \t\r\n":
                k += 1
            if k < len(body) and body[k] == ":":
                out.append('"%s"' % name)
                i = j
                continue
            if name == "undefined":
                out.append("null")
                i = j
                continue
            if name in params:
                out.append(json.dumps(args[params.index(name)],
                                      ensure_ascii=False,
                                      separators=(",", ":")))
            else:
                out.append(name)
            i = j
            continue
        out.append(c)
        i += 1
    try:
        return json.loads("".join(out))
    except Exception:
        return None


class Spider(BaseSpider):

    _ssr_cache = {"t": 0, "v": {}}   # (tabUuid -> [items]) 缓存，5 分钟

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

    def _fetch_ssr(self, tab_uuid):
        """抓取 PC 站 tab SSR 页面，返回去重后的剧集列表；失败返回 []"""
        uri = (tab_uuid or "").strip()
        if not uri:
            return []
        now = time.time()
        if self._ssr_cache["v"].get(uri) is not None and \
                now - self._ssr_cache["t"] < 300:
            return self._ssr_cache["v"][uri]
        items = []
        try:
            req = request.Request(SSR_BASE % uri, headers={
                "User-Agent": UA_PC,
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            with request.urlopen(req, timeout=15) as r:
                html = r.read().decode("utf-8", "ignore")
            m = re.search(r"window\.__NUXT__=(.*?)</script>", html, re.S)
            if m:
                data = _parse_nuxt(m.group(1).strip())
                d0 = (data or {}).get("data", [{}])[0]
                seen = set()
                for mo in d0.get("tabModules") or []:
                    if not isinstance(mo, dict):
                        continue
                    if mo.get("moduleType") not in (1, 2):
                        continue
                    for it in mo.get("moduleData") or []:
                        if not isinstance(it, dict):
                            continue
                        vid = it.get("vodUuid") or it.get("uuid")
                        if vid and vid not in seen:
                            seen.add(vid)
                            items.append(it)
        except Exception:
            items = []
        if items:
            self._ssr_cache["v"][uri] = items
            self._ssr_cache["t"] = now
        return items

    def _mk(self, it):
        total = it.get("totalNum") or 0
        return {
            "vod_id": it.get("vodUuid") or it.get("uuid"),
            "vod_name": it.get("name") or "",
            "vod_pic": it.get("coverImage") or it.get("downImage") or "",
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
            cls = [{"type_id": u, "type_name": n} for u, n in TABS]
            videos = self.categoryContent(TABS[0][0], 1, False, {}).get("list", [])
            return {"class": cls, "filters": {}, "list": videos}
        except Exception:
            return {"class": [], "filters": {}, "list": []}

    def homeVideoContent(self):
        return {"list": self.categoryContent(TABS[0][0], 1, False, {}).get("list", [])}

    # ------------------------------------------------------------ 分类
    def categoryContent(self, tid, pg, filter=False, extend=None):
        try:
            tid = str(tid or "")
            if tid not in dict(TABS):
                return {"page": 1, "pagecount": 1, "limit": PAGE,
                        "total": 0, "list": []}
            items = self._fetch_ssr(tid)
            pg = int(pg) if str(pg).isdigit() else 1
            total = len(items)
            pagecount = max(1, int(math.ceil(total / float(PAGE))))
            pg = min(max(pg, 1), pagecount)
            start = (pg - 1) * PAGE
            lst = [self._mk(x) for x in items[start:start + PAGE]]
            return {"page": pg, "pagecount": pagecount, "limit": PAGE,
                    "total": total, "list": lst}
        except Exception:
            return {"page": 1, "pagecount": 1, "limit": PAGE, "total": 0,
                    "list": []}

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
        # 站点未开放搜索入口与可用接口
        return {"list": []}