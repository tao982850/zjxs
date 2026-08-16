# -*- coding: utf-8 -*-
import sys
import re
import json
from urllib.parse import quote

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            import requests as rq
            kw.pop('timeout', None)
            return rq.get(url, headers=headers, timeout=15, **kw)

HOST = "https://mxvod.us"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
CATEGORIES = {"dianying": "电影", "dianshiju": "电视剧", "zongyi": "综艺", "dongman": "动漫", "duanju": "短剧", "tiyu": "体育"}

class Spider(Spider):
    def init(self, extend=""):
        pass

    def homeContent(self, filter=False):
        return {"class": [{"type_id": k, "type_name": v} for k, v in CATEGORIES.items()], "list": []}

    def homeVideoContent(self):
        return {"list": self._items(self._get(HOST + "/"))[:40]}

    def categoryContent(self, tid, pg=1, filter=False, extend=""):
        try:
            pn = max(int(str(pg)), 1)
        except:
            pn = 1
        url = f"{HOST}/vodtype/{tid}-{pn}.html" if pn > 1 else f"{HOST}/vodtype/{tid}.html"
        return {"page": pn, "pagecount": 99, "limit": 24, "total": 0, "list": self._items(self._get(url))}

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else str(ids)
        html = self._get(f"{HOST}/voddetail/{vid}.html")
        if not html:
            return {"list": []}
        d = {}
        m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        d["vod_name"] = m.group(1).strip() if m else ""
        im = re.search(r'<img[^>]*data-src="([^"]+)"', html)
        pic = im.group(1) if im else ""
        if pic.startswith("/"):
            pic = HOST + pic
        d["vod_pic"] = pic
        d["vod_year"] = ""
        d["vod_area"] = ""
        d["vod_class"] = ""
        d["vod_director"] = ""
        d["vod_actor"] = ""
        dm = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]+)"', html)
        d["vod_content"] = (dm.group(1).strip() if dm else "")[:500]
        d["vod_remarks"] = ""
        tabs = re.findall(r'class="module-tab-item tab-item" data-dropdown-value="([^"]+)"', html)
        eps = re.findall(r'/vodplay/%s-(\d+)-(\d+)\.html"[^>]*title="[^"]*">\s*<span>([^<]+)</span>' % vid, html)
        groups = {}
        for sid, nid, name in eps:
            groups.setdefault(sid, []).append((nid, name))
        froms, urls = [], []
        for idx, sid in enumerate(sorted(groups.keys(), key=int)):
            if len(froms) >= 8:
                break
            fname = tabs[int(sid) - 1] if int(sid) <= len(tabs) and tabs[int(sid) - 1] else "线路" + sid
            froms.append(fname)
            urls.append("#".join([f"{n}${vid}|{sid}|{i}" for i, n in groups[sid]]))
        if not froms:
            return {"list": []}
        d["vod_id"] = vid
        d["vod_play_from"] = "$$$".join(froms)
        d["vod_play_url"] = "$$$".join(urls)
        return {"list": [d]}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            html = self._get(f"{HOST}/vodsearch/{quote(str(key))}.html")
            return {"list": self._items(html), "page": 1}
        except:
            return {"list": []}

    def playerContent(self, flag, id, vipFlags=None):
        try:
            parts = str(id).split("|")
            if len(parts) != 3:
                return {"url": ""}
            vid, sid, nid = parts[0], parts[1], parts[2]
            html = self._get(f"{HOST}/vodplay/{vid}-{sid}-{nid}.html")
            mo = re.search(r'player_aaaa=(\{.*?\})\s*</script>', html, re.S)
            if not mo:
                return {"url": ""}
            d = json.loads(mo.group(1).replace('\\/', '/'))
            url = d.get("url", "")
            if not url:
                return {"url": ""}
            return {"parse": 0, "url": url, "header": {"User-Agent": UA, "Referer": HOST + "/"}}
        except:
            return {"url": ""}

    def localProxy(self, param):
        pass

    def _pagecount(self, html, current_page=1):
        return current_page

    def _items(self, html):
        items, seen = [], set()
        for m in re.finditer(r'<a href="(/vodplay/(\d+)-1-1\.html)"[^>]*title="([^"]+)"', html):
            vid = m.group(2)
            if vid in seen:
                continue
            seen.add(vid)
            name = m.group(3).strip()
            parts = name.split()
            if len(parts) > 1 and len(parts[0]) >= 2:
                name = parts[0]
            im = re.search(r'<img[^>]*data-src="([^"]+)"', m.group(0))
            pic = ""
            tail = html[m.end():m.end() + 400]
            im2 = re.search(r'(?:data-src|src)="([^"]+)"', tail)
            if im2:
                pic = im2.group(1)
            if pic.startswith("/"):
                pic = HOST + pic
            items.append({"vod_id": vid, "vod_name": name, "vod_pic": pic, "vod_remarks": ""})
        return items

    def _get(self, url):
        try:
            r = self.fetch(url, headers={"User-Agent": UA})
            if r is not None:
                st = getattr(r, 'status_code', 0)
                if st and st < 400:
                    return r.text if hasattr(r, 'text') else r.read().decode('utf-8', 'ignore')
        except:
            pass
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            resp = urllib.request.urlopen(req, timeout=15)
            return resp.read().decode('utf-8', 'ignore')
        except:
            return ""

    def getName(self):
        return "MXVOD"

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass
