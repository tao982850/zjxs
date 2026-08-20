# -*- coding: utf-8 -*-
# gimyai.tw 劇迷 (MacCMS v10 + JD4K 4K线路)
# 4K链路: play页 player_data(url=JD-xxx,from=JD4K) -> play.aigm.tv/jd/api.php?url=JD-xxx -> AWS签名mp4直链(HEVC 3840x1606)
import requests
import re
import json
import base64
from urllib.parse import quote

try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def init(self, extend=""):
            pass

HOST = 'https://gimyai.tw'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
CATEGORIES = [
    {"type_id": "13", "type_name": "陸劇"},
    {"type_id": "20", "type_name": "韓劇"},
    {"type_id": "15", "type_name": "日劇"},
    {"type_id": "14", "type_name": "台劇"},
    {"type_id": "21", "type_name": "港劇"},
    {"type_id": "31", "type_name": "海外劇"},
    {"type_id": "2", "type_name": "電視劇"},
    {"type_id": "34", "type_name": "短劇"},
    {"type_id": "38", "type_name": "AI漫劇"},
    {"type_id": "4", "type_name": "動漫"},
    {"type_id": "29", "type_name": "綜藝"},
    {"type_id": "22", "type_name": "紀錄片"},
]


class Spider(Spider):
    def init(self, extend=""):
        self.headers = {
            "User-Agent": UA,
            "Referer": HOST,
            "Accept-Language": "zh-TW,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self.headers_ajax = {
            "User-Agent": UA,
            "Referer": HOST,
            "X-Requested-With": "XMLHttpRequest",
        }

    def getName(self):
        return "劇迷Gimy"

    def homeContent(self, filter):
        result = {"class": CATEGORIES, "list": []}
        try:
            r = requests.get(HOST, headers=self.headers, timeout=12)
            result["list"] = self._cards(r.text)
        except Exception:
            pass
        return result

    def homeVideoContent(self):
        try:
            r = requests.get(HOST, headers=self.headers, timeout=12)
            return {"list": self._cards(r.text)}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        result = {"list": [], "page": int(pg), "pagecount": 1, "limit": 228, "total": 0}
        url = f"{HOST}/genre/{tid}.html"
        try:
            r = requests.get(url, headers=self.headers, timeout=12)
            result["list"] = self._cards(r.text)
            result["pagecount"] = 1
            result["total"] = len(result["list"])
        except Exception:
            pass
        return result

    def detailContent(self, ids):
        result = {"list": []}
        if not ids:
            return result
        vod_id = ids[0]
        if not vod_id.startswith('/detail/'):
            vod_id = f"/detail/{vod_id}"
        url = HOST + vod_id
        if not url.endswith('.html'):
            url += '.html'
        try:
            r = requests.get(url, headers=self.headers, timeout=12)
            html = r.text
        except Exception:
            return result
        vod = {}
        vod["vod_id"] = vod_id
        m = re.search(r'<h1 class="detail__title">([^<]+)</h1>', html)
        vod["vod_name"] = m.group(1).strip() if m else ""
        pic = ""
        m = re.search(r'<img[^>]*src="(https?://[^"]+)"[^>]*alt="' + re.escape(vod["vod_name"]) + r'"', html)
        if m:
            pic = m.group(1)
        if not pic:
            m = re.search(r'class="detail__thumb[^"]*"[\s\S]{0,300}?src="(https?://[^"]+)"', html)
            if m:
                pic = m.group(1)
        vod["vod_pic"] = pic.replace('&amp;', '&')
        vod["vod_remarks"] = ""
        m = re.search(r'狀態：</span>([^<]+)<', html)
        if m:
            vod["vod_remarks"] = m.group(1).strip()
        vod["vod_year"] = ""
        m = re.search(r'(\d{4})</a>', html)
        if m:
            vod["vod_year"] = m.group(1)
        vod["vod_actor"] = ""
        m = re.search(r'主演：</span>([\s\S]{0,400}?)</div>', html)
        if m:
            vod["vod_actor"] = ",".join(re.findall(r'>([^<>]+)</a>', m.group(1))).strip(",")
        vod["vod_director"] = ""
        m = re.search(r'導演：</span>([\s\S]{0,200}?)</div>', html)
        if m:
            vod["vod_director"] = ",".join(re.findall(r'>([^<>]+)</a>', m.group(1))).strip(",")
        vod["vod_content"] = ""
        m = re.search(r'(?:簡介|剧情|剧情简介)[：:]([\s\S]{0,800}?)</(?:div|p)>', html)
        if m:
            vod["vod_content"] = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        lines = self._routes(html)
        if lines:
            vod["vod_play_from"] = '$$$'.join(n for n, s in lines)
            vod["vod_play_url"] = '$$$'.join(self._eps(html, lines))
        result["list"] = [vod]
        return result

    def searchContent(self, key, quick, pg=1):
        result = {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        q = quote(key)
        for u in [f"{HOST}/find/{q}------------.html", f"{HOST}/find/------------.html?wd={q}"]:
            try:
                r = requests.get(u, headers=self.headers, timeout=12)
                lst = self._cards(r.text)
                if lst:
                    result["list"] = lst
                    result["total"] = len(lst)
                    break
            except Exception:
                continue
        return result

    def playerContent(self, flag, id, vipFlags):
        result = {"parse": 0, "url": id}
        if not id.startswith('http'):
            play_url = HOST + id
            if not play_url.endswith('.html'):
                play_url += '.html'
            try:
                r = requests.get(play_url, headers=self.headers, timeout=12)
                pd = self._player_data(r.text)
            except Exception:
                return result
            if not pd:
                return result
            url = pd.get("url", "").replace('\\/', '/')
            encrypt = str(pd.get("encrypt", 0))
            if encrypt == "1":
                url = re.sub(r'%([0-9A-Fa-f]{2})', lambda m: chr(int(m.group(1), 16)), url)
            elif encrypt == "2":
                try:
                    url = base64.b64decode(url).decode('utf-8', errors='ignore')
                except Exception:
                    pass
            if not url:
                return result
            result["url"] = self._resolve(url)
        else:
            result["url"] = self._resolve(id)
        return result

    def _resolve(self, url):
        if url.startswith('JD-') or url.startswith('JDQM-') or url.startswith('JDHG-') or url.startswith('NS4K-') or url.startswith('NSYS-'):
            return self._api(url, 'jd')
        if url.startswith('qsvip-'):
            return self._api(url, 'qs')
        if re.search(r'v\.qq\.com|iqiyi\.com|youku\.com|bilibili\.com|mgtv\.com|sohu\.com|pptv\.com|letv\.com|xigua\.com', url):
            return self._api(url, 'lb')
        return url

    def _api(self, raw, mode):
        try:
            r = requests.get(f"https://play.aigm.tv/{mode}/api.php?url={quote(raw)}", headers=self.headers_ajax, timeout=15)
            d = r.json()
            if d.get("code") == 200 and d.get("url"):
                return d["url"]
        except Exception:
            pass
        return raw

    def _player_data(self, html):
        m = re.search(r'var\s+player_data\s*=\s*', html)
        if not m:
            return None
        i = m.end()
        depth = 0
        for j in range(i, len(html)):
            c = html[j]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[i:j + 1])
                    except Exception:
                        return None
        return None

    def _cards(self, html):
        out = []
        seen = set()
        for m in re.finditer(r'<a class="poster" href="(/detail/\d+\.html)">([\s\S]{0,900}?)</a>', html):
            path, block = m.group(1), m.group(2)
            if path in seen:
                continue
            seen.add(path)
            pic = ""
            im = re.search(r'<img[^>]*src="(https?://[^"]+)"', block)
            if im:
                pic = im.group(1).replace('&amp;', '&')
            name = ""
            nm = re.search(r'poster__title">([^<]+)<', block)
            if nm:
                name = nm.group(1).strip()
            remark = ""
            rm = re.search(r'poster__status">([^<]+)<', block)
            if rm:
                remark = rm.group(1).strip()
            if not name:
                am = re.search(r'<img[^>]*alt="([^"]+)"', block)
                if am:
                    name = am.group(1)
            if name:
                out.append({"vod_id": path, "vod_name": name, "vod_pic": pic, "vod_remarks": remark})
        return out

    def _routes(self, html):
        routes = []
        for m in re.finditer(r'route-title">([^<]+)<[\s\S]{0,120}?data-route-sid="(\d+)"', html):
            name = m.group(1).strip()
            sid = m.group(2)
            if name and sid not in [r[1] for r in routes]:
                routes.append((name, sid))
        routes.sort(key=lambda x: 0 if '4K' in x[0] else 1)
        return routes

    def _eps(self, html, routes):
        segs = {}
        for m in re.finditer(r'data-route-sid="(\d+)"([\s\S]{0,30000}?)(?=data-route-sid=|$)', html):
            segs[m.group(1)] = m.group(2)
        lines = []
        for name, sid in routes:
            seg = segs.get(sid, "")
            eps = []
            seen = set()
            for e in re.finditer(r'href="(/play/\d+-\d+-\d+\.html)"[^>]*>\s*([^<]{1,12})', seg):
                p, n = e.group(1), e.group(2).strip()
                if p in seen:
                    continue
                seen.add(p)
                eps.append(f"{n}${p}")
            if eps:
                lines.append("#".join(eps))
        return lines

    def localProxy(self, param):
        return [200, "video/MP2T", {}, param]

    def destroy(self):
        pass
