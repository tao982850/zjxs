# -*- coding: utf-8 -*-
import re
import os
import json
import time
import hashlib
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter

try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = None

HOST_CANDIDATES = [
    "https://www.mddcloud.com.cn",
    "https://m.mddcloud.com.cn",
    "https://mddcloud.com.cn",
]

API_CANDIDATES = [
    "https://activity.mddcloud.com.cn",
]

PRIVATE_KEY = "8a4af424bd714be5b2baacbe3cf5bbbe0131effeb92e99356ef1662884558f28"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

BRAND_ACTOR = "蝴蝶影视"
BRAND_DIRECTOR = "蝴蝶影视"
BRAND_TG = ""

TIMEOUT_API = 8
TIMEOUT_PLAY = 6

ROWS = 12
SCAN_WORKERS = 1
SCAN_MAX_PAGES = 260
MAX_CONCURRENCY = 1
MIN_INTERVAL = 0.25
SCAN_SAVE_EVERY = 25

TTL_WORDS = 24 * 3600
TTL_CORPUS = 7200
TTL_DETAIL_OK = 600
TTL_DETAIL_EMPTY = 60
TTL_PLAY = 240
TTL_HOME = 300
TTL_HOST = 1800

CATEGORY_WAIT = 7.0
PLAY_FIELD_PRIORITY = ("tryM3u8Url", "tryUrl", "tryMp4Url")
MAX_EPISODES = 300

DISK_CACHE_DIR = ""
DISK_CACHE_TTL = 6 * 3600


def _cache_path(name):
    base = DISK_CACHE_DIR or os.path.join(tempfile.gettempdir(), "mddcloud_cache")
    try:
        if not os.path.isdir(base):
            os.makedirs(base)
    except Exception:
        return ""
    return os.path.join(base, name)


def _disk_load(name, ttl):
    p = _cache_path(name)
    if not p or not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            blob = json.load(f)
        if not isinstance(blob, dict):
            return None
        ts = float(blob.get("ts") or 0)
        if ttl and time.time() - ts > ttl:
            return None
        return blob
    except Exception:
        return None


def _disk_save(name, data):
    p = _cache_path(name)
    if not p:
        return
    try:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        pass

_SIGN_SEPARATORS = (',', ':')

_NAME_NOISE = re.compile(r'[()（）【】\[\]、，,。.·\-—~&/\\|:：!!？?"\'“”‘’\s]+')
_TOKEN_SPLIT = re.compile(r'[()\[\]{}<>《》【】「」『』、，,。.·\-—/\\|:：!?？"\'“”‘’\s]+')

CATEGORIES = ("all", "tv", "movie", "variety", "doc", "anime")

CATEGORY_NAME = {
    "all": "全部",
    "tv": "剧集",
    "movie": "电影",
    "variety": "综艺",
    "doc": "纪录片",
    "anime": "动画",
}

_ANIME_NAME_RE = re.compile(r'(动画|动漫|卡通)')


def _bucket(vod):
    mats = set(x.strip() for x in str(vod.get("_material") or "").split(",") if x.strip())
    name = str(vod.get("vod_name") or "")
    vt = vod.get("_vod_type")
    if "纪录片" in mats:
        return "doc"
    if "动漫" in mats or "动画" in mats:
        return "anime"
    if "儿童" in mats and _ANIME_NAME_RE.search(name):
        return "anime"
    if vt == 1:
        return "movie"
    if vt in (2, 6, 7):
        return "variety"
    return "tv"


def _signed_body(data):
    now = int(time.time() * 1000)
    parts = []
    for k in sorted(data.keys()):
        v = data[k]
        if isinstance(v, (dict, list)):
            parts.append("%s=%s&" % (k, json.dumps(v, ensure_ascii=False, separators=_SIGN_SEPARATORS)))
        else:
            parts.append("%s=%s&" % (k, v))
    msg = "time:%s|privateKey:%s|data:%s" % (now, PRIVATE_KEY, "".join(parts))
    return {"time": now, "sign": hashlib.md5(msg.encode("utf-8")).hexdigest(), "data": data}


class MddApi:
    def __init__(self, session, api_base=""):
        self.session = session
        self._api = (api_base or API_CANDIDATES[0]).rstrip("/")
        self.waf403 = 0
        self.last_error = ""
        self.gate = threading.Semaphore(MAX_CONCURRENCY)
        self.cooldown_until = 0.0
        self.gate_lock = threading.Lock()
        self.last_call = 0.0

    def _cool(self, seconds):
        with self.gate_lock:
            self.cooldown_until = max(self.cooldown_until, time.time() + seconds)

    def _throttle(self):
        with self.gate_lock:
            wait = self.last_call + MIN_INTERVAL - time.time()
            if wait > 0:
                time.sleep(wait)
            self.last_call = time.time()

    def post(self, path, data, timeout=TIMEOUT_API, retry=4):
        body = _signed_body(data)
        last = None
        for attempt in range(retry):
            wait = self.cooldown_until - time.time()
            if wait > 0:
                time.sleep(min(wait, 6.0))
            self._throttle()
            with self.gate:
                try:
                    r = self.session.post(
                        self._api + path,
                        json=body,
                        timeout=timeout,
                        verify=False,
                        headers={"Content-Type": "application/json;charset=UTF-8"},
                    )
                except Exception as e:
                    r = None
                    last = {"msgType": -3, "msg": "网络异常: %s" % str(e)[:100]}
                    self.last_error = last["msg"]
            if r is None:
                time.sleep(0.4 + attempt * 0.5)
                continue
            if r.status_code == 403:
                self.waf403 += 1
                last = {"msgType": 403, "msg": "被WAF拦截(403)"}
                self.last_error = last["msg"]
                self._cool(2.5 + attempt * 2.0)
                time.sleep(1.2 + attempt * 1.5)
                continue
            if r.status_code == 429:
                last = {"msgType": 429, "msg": "请求过快(429)"}
                self.last_error = last["msg"]
                self._cool(2.0)
                time.sleep(1.2 + attempt)
                continue
            if r.status_code != 200:
                last = {"msgType": r.status_code, "msg": "HTTP %d" % r.status_code}
                self.last_error = last["msg"]
                time.sleep(0.5)
                continue
            try:
                j = r.json()
            except Exception:
                last = {"msgType": -2, "msg": "响应非JSON"}
                self.last_error = last["msg"]
                time.sleep(0.4)
                continue
            if j.get("msgType") == 1001:
                last = j
                self.last_error = str(j.get("msg") or "")
                break
            if self.waf403:
                self.waf403 = 0
            return j
        return last


_Base = _BaseSpider if _BaseSpider is not None else object


class Spider(_Base):
    siteUrl = HOST_CANDIDATES[0]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": HOST_CANDIDATES[0] + "/",
            "Connection": "keep-alive",
        })
        self.session.verify = False
        adapter = HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=0, pool_block=False)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.api = MddApi(self.session)
        self.extend = ""
        self._host = HOST_CANDIDATES[0]
        self._host_time = 0.0

        self._lock = threading.RLock()
        self._words_cache = None
        self._words_time = 0.0
        self._detail_cache = {}
        self._play_cache = {}
        self._home_cache = {}
        self._meta = {}

        self._corpus = {}
        self._corpus_state = {}
        self._corpus_lock = threading.Lock()

    def init(self, extend=""):
        self.extend = extend or ""
        cfg = {}
        for kv in self.extend.split(","):
            if "=" in kv:
                k, v = kv.split("=", 1)
                cfg[k.strip().lower()] = v.strip()
        if cfg.get("host"):
            h = cfg["host"]
            if not h.startswith("http"):
                h = "https://" + h
            self._host = h.rstrip("/")
        if cfg.get("api"):
            a = cfg["api"]
            if not a.startswith("http"):
                a = "https://" + a
            self.api._api = a.rstrip("/")
        self.session.headers["Referer"] = self._host + "/"
        try:
            threading.Thread(target=self._warm, daemon=True).start()
        except Exception:
            pass
        return self

    def _warm(self):
        try:
            self._classify_words()
        except Exception:
            pass
        try:
            self._get_corpus(("", ""), wait=0.0)
        except Exception:
            pass

    def getName(self):
        return "埋堆堆"

    def host(self):
        now = time.time()
        with self._lock:
            if now - self._host_time < TTL_HOST:
                return self._host
        for h in HOST_CANDIDATES:
            try:
                r = self.session.get(h + "/", timeout=TIMEOUT_API, verify=False)
                if r.status_code == 200 and "埋堆堆" in r.text[:200000]:
                    with self._lock:
                        self._host = h
                        self._host_time = now
                    self.session.headers["Referer"] = h + "/"
                    return h
            except Exception:
                continue
        with self._lock:
            self._host_time = now
        return self._host

    @staticmethod
    def _cache_get(cache, key, ttl=None):
        item = cache.get(key)
        if not item:
            return None
        ts, val, life = item
        life = ttl if ttl is not None else life
        if life and time.time() - ts > life:
            cache.pop(key, None)
            return None
        return val

    @staticmethod
    def _cache_set(cache, key, value, ttl, max_size=256):
        if len(cache) >= max_size:
            old = sorted(cache.keys(), key=lambda k: cache[k][0])[:max(1, max_size // 4)]
            for k in old:
                cache.pop(k, None)
        cache[key] = (time.time(), value, ttl)

    @staticmethod
    def _pic(u):
        u = (u or "").strip()
        if not u:
            return ""
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http://"):
            return "https://" + u[7:]
        return u

    @staticmethod
    def _fix(u):
        u = (u or "").strip()
        if not u:
            return ""
        if u.startswith("//"):
            return "https:" + u
        return u

    @staticmethod
    def _first_year(v):
        m = re.search(r'(\d{4})', str(v or ""))
        return m.group(1) if m else ""

    def _remarks(self, v):
        parts = []
        if v.get("updateNum"):
            parts.append("更新至%s集" % v.get("updateNum"))
        if v.get("totalNum") and not v.get("updateNum"):
            parts.append("全%s集" % v.get("totalNum"))
        parts.append(BRAND_TG)
        return " · ".join(parts)

    def _to_vod(self, v):
        vid = str(v.get("uuid") or v.get("vodUuid") or "").strip()
        name = str(v.get("name") or "").strip()
        if not vid or not name:
            return None
        item = {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": self._pic(v.get("coverImage") or v.get("sideImage") or v.get("downImage")),
            "vod_remarks": self._remarks(v),
            "_material": str(v.get("materialName") or ""),
            "_year": str(v.get("yearName") or ""),
            "_vod_type": int(v.get("vodType") or 0),
            "_total_num": int(v.get("totalNum") or 0),
            "_comment": int(v.get("commentNum") or 0),
            "_is_vip": int(v.get("isVip") or 0),
            "_time": str(v.get("firstSowingTime") or ""),
        }
        item["_bucket"] = _bucket(item)
        return item

    def _classify_words(self):
        with self._lock:
            if self._words_cache is not None and time.time() - self._words_time < TTL_WORDS:
                return self._words_cache
        resp = self.api.post("/api/vod/classify/list.action", {})
        words = {}
        if resp and resp.get("msgType") == 0 and resp.get("data"):
            for field in resp["data"]:
                fc = field.get("fieldCode") or ""
                ws = []
                for w in (field.get("words") or []):
                    uuid = str(w.get("uuid") or "")
                    name = str(w.get("word") or "").strip()
                    if fc and name and name != "全部" and uuid:
                        ws.append({"word": name, "uuid": uuid})
                if fc and ws:
                    words[fc] = ws
        with self._lock:
            if words:
                self._words_cache = words
                self._words_time = time.time()
                return words
            return self._words_cache or {}

    def _resolve_uuid(self, field, raw):
        raw = str(raw or "").strip()
        if not raw:
            return ""
        words = self._classify_words().get(field, [])
        for w in words:
            if w["word"] == raw:
                return w["uuid"]
        for w in words:
            if w["uuid"] == raw:
                return raw
        return ""

    def _all_filters(self):
        words = self._classify_words()

        def mk(fc, label):
            value = [{"n": "全部", "v": ""}]
            for w in words.get(fc, []):
                value.append({"n": w["word"], "v": w["word"]})
            return {"key": fc, "name": label, "value": value}

        return [
            mk("lang", "语言"),
            mk("year", "年份"),
            mk("material", "题材"),
            mk("region", "地区"),
            {"key": "isvip", "name": "收费", "value": [
                {"n": "全部", "v": "-1"},
                {"n": "限免", "v": "0"},
                {"n": "VIP", "v": "1"},
            ]},
            {"key": "sort", "name": "排序", "value": [
                {"n": "最热", "v": "0"},
                {"n": "最新", "v": "1"},
                {"n": "好评", "v": "2"},
            ]},
        ]

    def homeContent(self, filter=False):
        classes = [{"type_id": c, "type_name": CATEGORY_NAME[c]} for c in CATEGORIES]
        result = {"class": classes}
        if filter:
            filters = self._all_filters()
            result["filters"] = {c["type_id"]: filters for c in classes}
        return result

    def homeVideoContent(self):
        cached = self._cache_get(self._home_cache, "home", TTL_HOME)
        if cached is not None:
            return {"list": cached}
        lst = self._fetch_page(0, "", "", -1)
        if lst:
            self._cache_set(self._home_cache, "home", lst, TTL_HOME)
        return {"list": lst}

    def _fetch_page(self, start_row, lang_uuid, region_uuid, isvip):
        lst, ok = self._fetch_page_checked(start_row, lang_uuid, region_uuid, isvip)
        return lst if ok else []

    def _fetch_page_checked(self, start_row, lang_uuid, region_uuid, isvip):
        uuid_list = [x for x in (lang_uuid, region_uuid) if x]
        resp = self.api.post("/api/vod/classify/word/search.action", {
            "uuidList": uuid_list,
            "rows": ROWS,
            "startRow": start_row,
            "isVip": int(isvip),
            "orderType": 0,
        })
        if not resp:
            return [], False
        if resp.get("msgType") != 0:
            return [], False
        out = []
        for v in (resp.get("data") or []):
            item = self._to_vod(v)
            if item:
                out.append(item)
        return out, True

    def _get_corpus(self, key, wait=0.0):
        now = time.time()
        with self._lock:
            hit = self._corpus.get(key)
            if hit and now - hit[0] < TTL_CORPUS and hit[1]:
                return hit[1], True, "内存缓存"

        name = self._corpus_file(key)
        disk = _disk_load(name, 0)
        if disk and disk.get("items"):
            items = disk["items"]
            ts = float(disk.get("ts") or 0)
            complete = bool(disk.get("complete"))
            with self._lock:
                self._corpus[key] = (ts, items, TTL_CORPUS)
                for it in items:
                    self._meta[it["vod_id"]] = {"_material": it.get("_material", ""),
                                                "_year": it.get("_year", ""),
                                                "_bucket": it.get("_bucket", "tv")}
            if complete and (now - ts) < TTL_CORPUS:
                return items, True, "磁盘缓存"
            self._start_scan(key, next_page=int(disk.get("next_page") or 0))
            deadline = time.time() + max(0.0, wait)
            while time.time() < deadline:
                with self._corpus_lock:
                    st = self._corpus_state.get(key) or {}
                    if st.get("done"):
                        break
                time.sleep(0.15)
            with self._corpus_lock:
                st = self._corpus_state.get(key) or {}
                fresh = list(st.get("items") or [])
                done = bool(st.get("done"))
            if len(fresh) > len(items):
                return fresh, done, "磁盘缓存(续扫)"
            return items, complete, "磁盘缓存(已满)"

        self._start_scan(key, next_page=0)
        deadline = time.time() + max(0.0, wait)
        while time.time() < deadline:
            with self._corpus_lock:
                st = self._corpus_state.get(key) or {}
                if st.get("done"):
                    break
            time.sleep(0.15)
        with self._corpus_lock:
            st = self._corpus_state.get(key) or {}
            items = list(st.get("items") or [])
            done = bool(st.get("done"))
            err = str(st.get("error") or "")
        if items and done:
            with self._lock:
                self._corpus[key] = (time.time(), items, TTL_CORPUS)
            _disk_save(name, {"ts": time.time(), "items": items,
                              "complete": not err, "next_page": 0 if not err else st.get("next_page", 0)})
        return items, done, err

    @staticmethod
    def _corpus_file(key):
        lang_uuid, region_uuid = key
        tag = (lang_uuid + "|" + region_uuid) or "all"
        return "corpus_%s.json" % hashlib.md5(tag.encode("utf-8")).hexdigest()[:12]

    def _start_scan(self, key, next_page=0):
        with self._corpus_lock:
            st = self._corpus_state.get(key)
            if st is not None and not st.get("done"):
                return
            self._corpus_state[key] = {
                "items": [], "seen": set(), "done": False, "error": "",
                "started": time.time(), "next_page": int(next_page or 0),
            }
        try:
            threading.Thread(target=self._scan_corpus, args=(key,), daemon=True).start()
        except Exception:
            with self._corpus_lock:
                self._corpus_state[key]["done"] = True
                self._corpus_state[key]["error"] = "线程创建失败"

    def _scan_corpus(self, key):
        lang_uuid, region_uuid = key
        with self._corpus_lock:
            st = self._corpus_state.get(key)
            if st is None:
                return
            items = st["items"]
            seen = st["seen"]
            page = int(st.get("next_page") or 0)

        err = ""
        fail_streak = 0
        empty_streak = 0
        last_save = page

        while page < SCAN_MAX_PAGES:
            lst, ok = self._fetch_page_checked(page * ROWS, lang_uuid, region_uuid, -1)
            if not ok:
                fail_streak += 1
                if fail_streak >= 5:
                    err = "扫描中断: 连续 %d 页请求失败(%s)" % (fail_streak, self.api.last_error or "未知")
                    break
                time.sleep(1.5 * fail_streak)
                continue
            fail_streak = 0
            if not lst:
                empty_streak += 1
                if empty_streak >= 2:
                    page += 1
                    break
                page += 1
                continue
            empty_streak = 0
            with self._corpus_lock:
                for item in lst:
                    vid = item["vod_id"]
                    if vid in seen:
                        continue
                    seen.add(vid)
                    items.append(item)
                    self._meta[vid] = {"_material": item["_material"],
                                       "_year": item["_year"],
                                       "_bucket": item["_bucket"]}
                st["next_page"] = page + 1
            page += 1
            if page - last_save >= SCAN_SAVE_EVERY:
                last_save = page
                with self._corpus_lock:
                    snap = list(items)
                if snap:
                    _disk_save(self._corpus_file(key),
                               {"ts": time.time(), "items": snap, "complete": False,
                                "next_page": page})

        with self._corpus_lock:
            st["done"] = True
            st["error"] = err
            snap = list(items)
            final_page = st.get("next_page", 0)
        if snap:
            with self._lock:
                self._corpus[key] = (time.time(), snap, TTL_CORPUS)
            _disk_save(self._corpus_file(key),
                       {"ts": time.time(), "items": snap,
                        "complete": not err and empty_streak >= 2,
                        "next_page": final_page})

    @staticmethod
    def _parse_extend(extend):
        if not extend:
            return {}
        if isinstance(extend, dict):
            return extend
        try:
            s = str(extend).strip()
            if s.startswith("{"):
                return json.loads(s)
        except Exception:
            pass
        return {}

    def _apply_filter(self, items, tid, ext):
        material = str(ext.get("material") or "").strip()
        year = str(ext.get("year") or "").strip()
        sort = str(ext.get("sort") or "0").strip()
        out = []
        for it in items:
            if tid != "all" and it.get("_bucket") != tid:
                continue
            if material:
                mats = [x.strip() for x in str(it.get("_material") or "").split(",")]
                if material not in mats:
                    continue
            if year:
                ys = str(it.get("_year") or "")
                if year not in [x.strip() for x in ys.split(",")]:
                    continue
            out.append(it)
        if sort == "1":
            out.sort(key=lambda x: self._first_year(x.get("_time")) or self._first_year(x.get("_year")) or "0000",
                     reverse=True)
        elif sort == "2":
            out.sort(key=lambda x: x.get("_comment") or 0, reverse=True)
        return out

    def _card(self, it):
        return {
            "vod_id": it["vod_id"],
            "vod_name": it["vod_name"],
            "vod_pic": it["vod_pic"],
            "vod_remarks": it["vod_remarks"],
        }

    def categoryContent(self, tid, pg, filter, extend):
        tid = str(tid or "all")
        if tid not in CATEGORIES:
            tid = "all"
        try:
            page = max(1, int(pg or 1))
        except Exception:
            page = 1
        ext = self._parse_extend(extend)
        lang_uuid = self._resolve_uuid("lang", ext.get("lang"))
        region_uuid = self._resolve_uuid("region", ext.get("region"))
        raw_vip = ext.get("isvip")
        try:
            isvip = int(str(raw_vip)) if raw_vip not in (None, "") else -1
        except Exception:
            isvip = -1

        key = (lang_uuid, region_uuid)
        items, complete, err = self._get_corpus(key, wait=CATEGORY_WAIT)

        if not items:
            fb = self._fetch_page((page - 1) * ROWS, lang_uuid, region_uuid, isvip)
            if fb:
                items = fb
                complete = True
                err = ""
            else:
                msg = err or self.api.last_error or "分类接口无返回"
                waf = "（WAF 403，请降低并发或稍后再试）" if self.api.waf403 else ""
                return {"list": [], "page": page, "pagecount": 1, "limit": ROWS, "total": 0,
                        "msg": "埋堆堆分类加载失败: %s%s" % (msg, waf)}

        pool = items
        if isvip == 0:
            pool = [x for x in pool if not self._is_vip(x)]
        elif isvip == 1:
            pool = [x for x in pool if self._is_vip(x)]

        rows = self._apply_filter(pool, tid, ext)
        total = len(rows)
        pagecount = max(1, (total + ROWS - 1) // ROWS) if total else 1
        start = (page - 1) * ROWS
        chunk = rows[start:start + ROWS]
        return {
            "list": [self._card(x) for x in chunk],
            "page": page,
            "pagecount": pagecount,
            "limit": ROWS,
            "total": total,
        }

    def _is_vip(self, it):
        return int(it.get("_is_vip") or 0) == 1

    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        if not ids:
            return {"list": []}
        vid = str(ids[0]).split(",")[0].strip()
        if not vid:
            return {"list": []}
        cached = self._cache_get(self._detail_cache, vid, None)
        if cached is not None:
            return cached
        detail = self._fetch_detail(vid)
        self._cache_set(self._detail_cache, vid, detail,
                        TTL_DETAIL_OK if detail.get("list") else TTL_DETAIL_EMPTY, 512)
        return detail

    def _fetch_detail(self, vid):
        resp = self.api.post("/api/vod/getVodInfo.action", {"vodUuid": vid, "num": 1})
        if not resp:
            return {"list": [], "msg": "详情请求失败: %s" % (self.api.last_error or "无响应")}
        if resp.get("msgType") != 0:
            return {"list": [], "msg": "详情接口返回 %s: %s" % (resp.get("msgType"), resp.get("msg"))}
        v = resp.get("data") or {}
        sl = [s for s in (v.get("vodSactionList") or []) if s.get("num") is not None]
        if not sl:
            return {"list": [], "msg": "该片无分集数据"}
        sl.sort(key=lambda s: s.get("num"))
        if len(sl) > 200:
            sl = sl[-MAX_EPISODES:]
        eps = []
        for s in sl:
            ep = str(s.get("name") or "").strip() or ("第%s集" % s.get("num"))
            ep = ep.replace("$", " ").replace("#", " ")
            eps.append("%s$%s:%s" % (ep, vid, s.get("num")))

        meta = self._meta.get(vid) or {}
        name = str(v.get("name") or vid)
        year = (self._first_year(meta.get("_year"))
                or self._first_year(v.get("yearName"))
                or self._first_year(v.get("firstSowingTime")))
        actor = str(v.get("starring") or "").replace(",", "/") or BRAND_ACTOR
        director = str(v.get("director") or "").replace(",", "/") or BRAND_DIRECTOR
        area = "中国内地" if re.search(r'(普通话|国语)', name) else "中国香港"

        return {"list": [{
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": self._pic(v.get("coverImage") or v.get("sideImage") or v.get("downImage")),
            "vod_year": year,
            "vod_area": area,
            "vod_actor": actor,
            "vod_director": director,
            "vod_remarks": self._remarks(v),
            "vod_content": str(v.get("introduction") or "").strip(),
            "vod_play_from": "埋堆堆",
            "vod_play_url": "#".join(eps),
        }]}

    def _probe(self, url):
        if not url:
            return False
        try:
            if ".m3u8" in url.lower():
                r = self.session.get(url, headers={"User-Agent": UA, "Range": "bytes=0-0"},
                                     timeout=5, verify=False, stream=True)
                code = r.status_code
                try:
                    r.close()
                except Exception:
                    pass
                return 200 <= code < 400
            r = self.session.head(url, headers={"User-Agent": UA}, timeout=5, verify=False)
            return 200 <= r.status_code < 400
        except Exception:
            return False

    def _resolve_play(self, key):
        cached = self._cache_get(self._play_cache, key, TTL_PLAY)
        if cached:
            return cached, ""
        try:
            vid, num = str(key).split(":", 1)
            resp = self.api.post("/api/vod/getTrySaction.action",
                                 {"vodUuid": vid.strip(), "num": int(num)})
        except Exception as e:
            return "", "播放参数异常: %s" % str(e)[:80]
        if not resp:
            return "", "取流接口无响应: %s" % (self.api.last_error or "未知")
        if resp.get("msgType") != 0:
            return "", "取流接口返回 %s: %s" % (resp.get("msgType"), resp.get("msg"))
        d = resp.get("data") or {}
        if not d:
            return "", "取流接口 data 为空"

        chosen = ""
        for field in PLAY_FIELD_PRIORITY:
            u = self._fix(d.get(field))
            if u and self._probe(u):
                chosen = u
                break
        if not chosen:
            for field in PLAY_FIELD_PRIORITY:
                u = self._fix(d.get(field))
                if u:
                    chosen = u
                    break
        if not chosen:
            return "", "三个播放字段全为空"
        self._cache_set(self._play_cache, key, chosen, TTL_PLAY, 512)
        return chosen, ""

    def playerContent(self, flag, id, vipFlags):
        key = str(id or "").strip()
        if not key:
            return {"parse": 0, "jx": 0, "url": ""}
        header = {"User-Agent": UA, "Referer": self._host + "/"}
        if ":" not in key:
            return {"parse": 0, "jx": 0, "url": self._fix(key), "header": header}
        url, err = self._resolve_play(key)
        if not url:
            return {"parse": 1, "jx": 1, "url": key, "header": header,
                    "msg": "埋堆堆取流失败: %s" % (err or "未知原因")}
        payload = {"parse": 0, "jx": 0, "url": url, "header": header}
        if ".m3u8" in url.lower():
            payload["format"] = "application/x-mpegURL"
        return payload

    @staticmethod
    def _norm(name):
        return _NAME_NOISE.sub("", str(name or "")).lower()

    @staticmethod
    def _tokens(name):
        t = [x for x in _TOKEN_SPLIT.split(str(name or "")) if x]
        return t or [str(name or "")]

    def _score(self, kw_norm, kw_tokens, title):
        if not kw_norm:
            return 0
        tn = self._norm(title)
        if not tn:
            return 0
        if kw_norm == tn:
            return 100
        if kw_norm in tn:
            return 80 if tn.startswith(kw_norm) else 65
        tt = self._tokens(title)
        if all(t in tt for t in kw_tokens):
            return 55
        if any(t in tt for t in kw_tokens):
            return 40
        if len(kw_norm) >= 2:
            overlap = sum(1 for c in set(kw_norm) if c in set(tn))
            if overlap >= max(2, int(len(set(kw_norm)) * 0.6)):
                return min(20, overlap * 3)
        return 0

    def searchContent(self, key, quick=False, pg="1"):
        try:
            page = max(1, int(pg or 1))
        except Exception:
            page = 1
        kw = str(key or "").strip()
        if not kw:
            return {"list": [], "page": page, "pagecount": 1, "limit": ROWS, "total": 0}
        items, complete, err = self._get_corpus(("", ""), wait=CATEGORY_WAIT)
        if not items:
            msg = err or self.api.last_error or "语料为空"
            waf = "（WAF 403）" if self.api.waf403 else ""
            return {"list": [], "page": page, "pagecount": 1, "limit": ROWS, "total": 0,
                    "msg": "埋堆堆搜索失败: %s%s" % (msg, waf)}
        kw_norm = self._norm(kw)
        kw_tokens = self._tokens(kw)
        scored = []
        for it in items:
            s = self._score(kw_norm, kw_tokens, it.get("vod_name"))
            if s > 0:
                scored.append((s, it))
        scored.sort(key=lambda x: (-x[0], -(x[1].get("_comment") or 0)))
        total = len(scored)
        pagecount = max(1, (total + ROWS - 1) // ROWS) if total else 1
        start = (page - 1) * ROWS
        chunk = [it for _, it in scored[start:start + ROWS]]
        return {
            "list": [self._card(x) for x in chunk],
            "page": page,
            "pagecount": pagecount,
            "limit": ROWS,
            "total": total,
        }


def _self_test():
    sp = Spider()
    sp.init("")
    print("=" * 60)
    print("主站:", sp.host())
    print("API :", sp.api._api)

    home = sp.homeContent(filter=True)
    print("分类数:", len(home["class"]), [(c["type_id"], c["type_name"]) for c in home["class"]])
    fk = list(home.get("filters", {}).keys())
    print("筛选器挂载分类数:", len(fk), "字段:", [f["key"] for f in home["filters"][fk[0]]] if fk else [])

    hv = sp.homeVideoContent()
    print("首页条数:", len(hv["list"]), [x["vod_name"] for x in hv["list"][:3]])

    print("-" * 60)
    for c in home["class"]:
        t0 = time.time()
        cat = sp.categoryContent(c["type_id"], 1, True, {})
        print("  %-6s total=%-5d pagecount=%-4d %5.2fs  前3=%s" % (
            c["type_name"], cat["total"], cat["pagecount"], time.time() - t0,
            [x["vod_name"] for x in cat["list"][:3]]))
        if cat.get("msg"):
            print("     !!", cat["msg"])

    print("-" * 60)
    cat = sp.categoryContent("tv", 1, True, {})
    if cat["list"]:
        vid = cat["list"][0]["vod_id"]
        t0 = time.time()
        d = sp.detailContent([vid])
        if d["list"]:
            dv = d["list"][0]
            eps = dv["vod_play_url"].split("#")
            print("详情 %.2fs: %s | %s %s | 集数 %d" % (time.time() - t0, dv["vod_name"],
                                                    dv["vod_year"], dv["vod_area"], len(eps)))
            print("  演员:", dv["vod_actor"][:40], "| 导演:", dv["vod_director"][:20])
            print("  备注:", dv["vod_remarks"])
            print("  线路:", dv["vod_play_from"])
            print("  首集:", eps[0][:70])
            t0 = time.time()
            p = sp.playerContent("", eps[0].split("$")[1], [])
            print("  取流 %.2fs parse=%s format=%s" % (time.time() - t0, p.get("parse"),
                                                   p.get("format", "")))
            print("  URL:", str(p.get("url"))[:130])
            if p.get("msg"):
                print("  !!", p["msg"])
        else:
            print("详情失败:", d.get("msg"))

    print("-" * 60)
    for kw in ("奖门人", "无穷之路", "爱回家", "使徒行者"):
        t0 = time.time()
        s = sp.searchContent(kw)
        print("搜索 %-6s -> total=%-4d %5.2fs  %s" % (
            kw, s["total"], time.time() - t0, [x["vod_name"] for x in s["list"][:3]]))
        if s.get("msg"):
            print("   !!", s["msg"])

    print("-" * 60)
    for tid, ext in (("movie", {"lang": "粤语"}), ("tv", {"year": "2024"}),
                     ("variety", {}), ("doc", {}), ("anime", {}), ("all", {"material": "警匪"})):
        cat = sp.categoryContent(tid, 1, True, ext)
        print("筛选 %-8s %-16s total=%-5d 前2=%s" % (
            tid, json.dumps(ext, ensure_ascii=False), cat["total"],
            [x["vod_name"] for x in cat["list"][:2]]))

    print("-" * 60)
    c1 = sp.categoryContent("tv", 2, True, {})
    print("翻页 tv p2:", [x["vod_name"] for x in c1["list"][:3]], "page=", c1["page"],
          "pagecount=", c1["pagecount"])


if __name__ == "__main__":
    _self_test()
