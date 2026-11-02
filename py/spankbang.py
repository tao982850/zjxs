"""
SpankBang (TV / Chaquopy) Python 點播爬蟲 - 穩定性修復版

本次修復（針對「有時加載不起來」）：
- 請求層：原 _fetch_html 單次請求、無超時、任何例外直接回傳空字串；
  遇到 Cloudflare 挑戰時只開 WebView 就立刻回傳空，該次加載必然失敗。
  改為：12 秒超時 + 瞬時錯誤重試 1 次；挑戰時開啟 WebView 後短輪詢
  （約 3 秒）等 cf_clearance Cookie 回來再自動重試 1 次，等不到就
  快速失敗。總耗時嚴格有界——v1 曾用 20 秒×3 次 + 8 秒等待，超過
  App 等待上限反而導致分類全空白，本版已修正。country Cookie 默認
  不再強制附加（v1 默認 country=US 會讓非美 IP 拿到地區空頁），
  只有 ext 明確給 country 才加；UA 取 WebView 的並緩存，保證過盾
  Cookie 與請求 UA 一致。
  v3 補充（全局代理下仍間歇失敗）：請求改為雙通道——OkHttp 失敗
  自動換 Python requests（TLS 指紋不同，CF 按指紋攔截時常一邊
  倒一邊通），整体受 26 秒牆鐘預算限制；詳情頁拉取失敗不再只回
  一句「頁面加載失敗」，而是回退一個嗅探可播條目，保住播放路徑。
  v4 補充：資料夾跳轉在 detailContent 入口也接住 playlist/ 前綴
  （有的 App 版本點 cr 連結走詳情入口，原來只有分類入口處理，
  表現為資料夾加載不出來）；播放列表解析兼容絕對連結與只有
  封面圖的卡片（標題取 img alt）；詳情/播放拉取放寬到單次
  16 秒、總預算 34 秒（詳情頁更重）。
  v5 補充（按真實詳情頁實測）：新版詳情頁已無 stream_url_*，
  流地址改在 var stream_data = {畫質: [url]} 裡，提取規則已
  切換（舊規則保留兜底）；相關播放列表改按 playlist-card
  卡片解析——舊掃法會把一張卡拆成 "Play all"/"View playlist"
  兩條垃圾重複項，現在每卡一條、真名真網址。
- 列表解析：原正則過寬且「第一個 <a> 沒圖/沒標題就整筆丟棄」，同一影片
  的縮圖連結與標題連結互相拆散，導致部分卡片時有时无。改為只認
  /<id>/video/ 真實影片路徑、按 vod_id 聚合同一影片的全部 <a> 再取
  圖/標題/時長；分頁改看頁面是否有下一頁連結，不再只靠條數猜。
- 搜尋：原 quote() 把空格轉出的 '+' 又編碼成 %2B，多詞搜尋會搜錯。
  改為逐詞編碼後以 '+' 連接（站點 /s/a+b/ 格式）。
- 詳情：封面改優先 og:image（原正則會抓到頁面第一張雜圖）；標題優先
  h1 的 title 屬性；加載失敗時回傳 msg 而不是假詳情。
- 播放：原來一律 parse=1 靠 WebView 嗅探，CF/彈窗干擾下時好時壞。
  改為先從詳情頁直提 stream_url_<畫質> 變量（m3u8 優先，其次最高
  畫質 mp4），取不到再試 data-streamkey 的 stream API，最後才回退
  嗅探。詳情頁若已提流成功，選集直接是各畫質直鏈，播放不二次解析。

保留原有功能：Recommended 映射、Related Playlists 資料夾跳轉、
Cloudflare WebView 過盾、全局容錯。
"""

import json
import re
import time
from html import unescape as html_unescape
from urllib.parse import quote, unquote, urljoin, urlsplit

from base.spider import Spider as BaseSpider


PAGE_SIZE = 20
BASE_URL = "https://spankbang.com"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

CATEGORIES = [
    {"type_id": "trending", "type_name": "Trending (熱門)"},
    {"type_id": "most_popular", "type_name": "Most Popular (最多觀看)"},
    {"type_id": "new", "type_name": "Newest (最新)"},
    {"type_id": "upcoming", "type_name": "Upcoming (即將推出)"},
]

REQUEST_TIMEOUT_SECONDS = 12
MAX_ATTEMPTS = 2


class Spider(BaseSpider):
    def init(self, extend=""):
        if isinstance(extend, dict):
            options = extend
        elif extend:
            try:
                options = json.loads(extend)
            except Exception:
                options = {}
        else:
            options = {}
        if not isinstance(options, dict):
            options = {}

        self.options = options
        self.site_url = str(options.get("web_url") or BASE_URL).rstrip("/")
        # 地區 Cookie 默認不強制附加：v1 默認塞 country=US 曾導致
        # 非美國 IP 的用戶被站點回以地區頁/空頁（分類全空白）。
        # 只有 ext 明確給了 country 才附加，例如 {"country": "US"}。
        self.country = str(options.get("country") or "").upper()
        self._ua = None
        self._web_opened = set()

    def getName(self):
        return "SpankBang"

    def homeContent(self, filter):
        return {"class": CATEGORIES}

    def homeVideoContent(self):
        res = self.categoryContent("trending", "1", False, {})
        return {"list": res.get("list", [])}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if str(pg).isdigit() else 1

        if tid.startswith("playlist/"):
            path = tid.removeprefix("playlist/").strip("/")
            url = f"{self.site_url}/{path}/{page}/" if page > 1 else f"{self.site_url}/{path}/"
        elif tid == "trending":
            url = f"{self.site_url}/trending_videos/{page}" if page > 1 else f"{self.site_url}/trending_videos"
        elif tid == "most_popular":
            url = f"{self.site_url}/most_popular/{page}" if page > 1 else f"{self.site_url}/most_popular"
        elif tid == "new":
            url = f"{self.site_url}/new_videos/{page}" if page > 1 else f"{self.site_url}/new_videos"
        else:
            url = f"{self.site_url}/{tid}/{page}" if page > 1 else f"{self.site_url}/{tid}"

        html = self._fetch_html(url)
        items = self._parse_video_list(html)

        return {
            "list": items,
            "page": page,
            "pagecount": page + 1 if self._has_next_page(html, page, len(items)) else page,
            "limit": PAGE_SIZE,
            "total": 9999,
        }

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if str(pg).isdigit() else 1
        raw_key = str(key or "").strip()

        if not raw_key:
            return {"list": [], "page": 1, "pagecount": 1, "limit": PAGE_SIZE, "total": 0}

        # 站點格式是 /s/word1+word2/：逐詞編碼再用 '+' 連接。
        # 原寫法 quote(替換後的字串) 會把 '+' 編成 %2B，多詞搜尋必錯。
        formatted_key = "+".join(quote(word) for word in raw_key.split())

        if page > 1:
            url = f"{self.site_url}/s/{formatted_key}/{page}/"
        else:
            url = f"{self.site_url}/s/{formatted_key}/"

        html = self._fetch_html(url)
        items = self._parse_video_list(html)

        return {
            "list": items,
            "page": page,
            "pagecount": page + 1 if self._has_next_page(html, page, len(items)) else page,
            "limit": PAGE_SIZE,
            "total": 9999,
        }

    def detailContent(self, ids):
        vod_id = str(ids[0] if ids else "").removeprefix("vod/")
        if not vod_id:
            return {"list": [], "msg": "無效的影片 ID"}
        if vod_id.startswith("playlist/"):
            # 相關播放列表資料夾的跳轉入口有兩種可能：有的 App 版本
            # 點 cr 連結走 categoryContent，有的走 detailContent。
            # categoryContent 那邊已處理，這裡也接住，否則走 detail
            # 入口的版本點資料夾會把 playlist 路徑當影片 ID 拉取，
            # 表現就是「資料夾加載不出來」。
            res = self.categoryContent(vod_id, "1", False, {})
            return {"list": res.get("list", [])}
        if not vod_id.startswith("http"):
            detail_url = f"{self.site_url}/{vod_id.lstrip('/')}"
        else:
            detail_url = vod_id

        html = self._fetch_html(detail_url, budget=34, timeout=16)
        if not html:
            # 詳情頁拉取失敗不要死胡同（v2 這裡直接回 msg，用戶點播放
            # 就只看到「頁面加載失敗」）。回退一個可播條目：標題從
            # URL slug 猜，播放走 playerContent 的嗅探兜底——WebView
            # 嗅探用的是瀏覽器引擎，和 OkHttp/requests 是兩條完全
            # 不同的通道，請求層失敗時它經常反而能播。
            slug = ""
            path = urlsplit(detail_url).path
            if "/video/" in path:
                slug = path.split("/video/", 1)[1].strip("/")
            guess_title = html_unescape(slug.replace("+", " ")).strip() or "SpankBang Video"
            return {"list": [{
                "vod_id": vod_id,
                "vod_name": guess_title,
                "vod_pic": "",
                "vod_type": "Adult",
                "vod_actor": "無",
                "vod_content": "詳情頁暫時拉取失敗，已切換為嗅探播放模式，可直接點擊播放。",
                "vod_play_from": "SpankBang",
                "vod_play_url": f"正片${detail_url}",
            }]}

        # 1. 標題：優先 <h1 title="...">，其次 h1 文本，再 og:title
        title = ""
        m = re.search(r'<h1[^>]*\btitle=["\']([^"\']+)["\']', html, re.S | re.I)
        if m:
            title = m.group(1)
        if not title:
            m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S | re.I)
            if m:
                title = re.sub(r'<[^>]+>', '', m.group(1))
        if not title:
            m = re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
            if m:
                title = m.group(1)
        title = html_unescape(title).strip() or "SpankBang Video"

        # 2. 封面：優先 og:image（原正則掃全頁第一張圖，常抓錯雜圖）
        pic = ""
        for pat in (
            r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
            r'name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)["\']',
            r'<video[^>]*\bposter=["\']([^"\']+)["\']',
        ):
            m = re.search(pat, html, re.I)
            if m:
                pic = m.group(1).strip()
                break
        if pic.startswith("//"):
            pic = "https:" + pic
        elif pic and not pic.startswith("http"):
            pic = urljoin(self.site_url, pic)
        pic = html_unescape(pic)

        # 3. 解析 Related Porn Playlists
        playlists = self._parse_related_playlists(html)

        # 4. 播放線路：能直提流就按畫質給選集（播放不再二次嗅探），
        #    提不到才退回「正片$詳情頁」走 playerContent 嗅探兜底。
        streams = self._extract_streams(html)
        if streams:
            def ep_label(label):
                low = label.lower()
                if low == "m3u8":
                    return "HLS"
                if low.startswith("m3u8_"):
                    return "HLS " + label.split("_", 1)[1]
                return label

            episodes = [
                f"{self._safe_label(ep_label(label))}${url}"
                for label, url in self._sort_streams(streams)
            ]
            play_url_list = ["#".join(episodes)]
        else:
            play_url_list = [f"正片${detail_url}"]

        folder_links = []
        for pl in playlists:
            rel_path = pl['url'].replace(self.site_url, "").strip('/')
            payload = json.dumps(
                {"id": f"playlist/{rel_path}", "name": pl['name'], "type_flag": "1"},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            folder_links.append(f"[a=cr:{payload}/]📂 {pl['name']}[/a]")

        content_lines = [f"【標題】{title}"]
        if playlists:
            content_lines.append(f"\n📌 相關播放列表 (點擊開啟資料夾，加载相关文件)：\n" + "  ".join(folder_links))

        item = {
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": pic,
            "vod_type": "Adult",
            "vod_actor": "  ".join(folder_links) if folder_links else "無",
            "vod_content": "\n".join(content_lines),
            "vod_play_from": "$$$".join(["SpankBang"]),
            "vod_play_url": "$$$".join(play_url_list),
        }

        return {"list": [item]}

    def _parse_related_playlists(self, html):
        """解析 Related Porn Playlists。

        新版式（2026 實測真實詳情頁）：每張卡是
        <div data-testid="playlist-card">，裡面有三個指向同一列表的
        <a>——「Play all」(用戶段帶 -0 後綴)、「View playlist」和卡片
        下方的標題連結；真名在標題連結的文字裡（或封面 img 的
        alt="X thumbnail"）。舊寫法逐個 <a> 掃描，會把一張卡拆成
        兩條名字叫 "Play all"/"View playlist" 的垃圾重複項，
        這正是「詳情推薦資料夾不對勁」的實錘。改為按卡片解析：
        每卡一條，網址取非 -0 的標題連結，名字取標題連結文字。
        找不到卡片時回退舊的逐連結掃描（老鏡像站），同樣過濾
        按鈕文字並按規範化路徑去重。
        """
        playlists = []
        if not html:
            return playlists

        seen_keys = set()

        def norm_key(path):
            return re.sub(r'/[^/]*?-\d+(?=/playlist/)', '/U', path.strip().rstrip('/'))

        card_starts = [m.start() for m in re.finditer(r'data-testid=["\']playlist-card["\']', html)]
        for idx, start in enumerate(card_starts):
            end = card_starts[idx + 1] if idx + 1 < len(card_starts) else start + 9000
            block = html[start:end]
            anchors = re.findall(
                r'<a[^>]*href=["\'](?:https?://[^/"\']+)?(/[^"\']*/playlist/[^"\']*)["\'][^>]*>(.*?)</a>',
                block, re.S | re.I,
            )
            if not anchors:
                continue
            canonical = [(h, c) for h, c in anchors if not re.search(r'/[^/]*-\d+/playlist/', h)]
            href, content = (canonical[-1] if canonical else anchors[-1])
            name = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', content)).strip()
            if name.lower() in ("play all", "view playlist"):
                name = ""
            if not name:
                am = re.search(r'<img[^>]*\balt=["\']([^"\']+?)(?:\s+thumbnail)?["\']', block, re.I)
                if am:
                    name = html_unescape(am.group(1)).strip()
            name = html_unescape(name)
            key = norm_key(href)
            if not name or len(name) < 2 or key in seen_keys:
                continue
            seen_keys.add(key)
            playlists.append({"name": name, "url": urljoin(self.site_url, href)})
            if len(playlists) >= 15:
                return playlists
        if playlists:
            return playlists

        # ---- 舊版式回退：逐連結掃描 ----
        playlist_section = re.search(r'(?:Related\s+Porn\s+Playlists|playlists)[^>]*>(.*?)(?:<section|<div class=["\']clear|$$)', html, re.S | re.I)
        search_scope = playlist_section.group(1) if playlist_section else html

        pattern = re.compile(
            r'<a[^>]*href=["\'](?:https?://[^/"\']+)?(/[^"\']*(?:/playlist/|/p/)[^"\']*)["\'][^>]*>(.*?)</a>',
            re.S | re.I
        )
        for match in pattern.finditer(search_scope):
            href, content = match.groups()
            pl_title = re.sub(r'<[^>]+>', '', content).strip()
            pl_title = re.sub(r'\s+', ' ', pl_title)
            if pl_title.lower() in ("play all", "view playlist"):
                pl_title = ""
            if not pl_title:
                am = re.search(r'<img[^>]*\balt=["\']([^"\']+)["\']', content, re.I)
                if am:
                    pl_title = html_unescape(am.group(1)).strip()

            key = norm_key(href)
            if key in seen_keys or not pl_title or len(pl_title) < 2:
                continue

            seen_keys.add(key)
            playlists.append({"name": pl_title, "url": urljoin(self.site_url, href)})

            if len(playlists) >= 15:
                break

        return playlists

    def playerContent(self, flag, id, vipFlags):
        target_url = str(id or "").strip()
        if not target_url:
            return {"parse": 0, "msg": "無效的播放地址"}
        if not target_url.startswith("http"):
            target_url = f"{self.site_url}/{target_url.lstrip('/')}"

        headers = self._get_headers(referer=target_url)

        # 詳情選集若已是直鏈（detailContent 提流成功時），直接播
        if self.isVideoFormat(target_url):
            result = {"parse": 0, "jx": 0, "url": target_url, "header": headers}
            if ".m3u8" in target_url.lower():
                result["format"] = "application/x-mpegURL"
            return result

        # 否則到詳情頁直提流地址：stream_url_* 變量 -> stream API -> 嗅探兜底
        html = self._fetch_html(target_url, budget=34, timeout=16)
        streams = self._extract_streams(html) if html else []
        if not streams and html:
            streams = self._streams_via_api(html, target_url)
        best = self._best_stream(streams)
        if best:
            result = {"parse": 0, "jx": 0, "url": best, "header": headers}
            if ".m3u8" in best.lower():
                result["format"] = "application/x-mpegURL"
            return result

        # 實在提不到才回退 WebView 嗅探（原行為）
        return {"parse": 1, "jx": 0, "url": target_url, "header": headers}

    def action(self, action):
        return {"msg": "OK"}

    def manualVideoCheck(self):
        return True

    def isVideoFormat(self, url):
        parsed = urlsplit(str(url or ""))
        path = parsed.path.lower()
        is_video = any(path.endswith(ext) for ext in [".m3u8", ".mp4", ".mpd"])
        is_not_ad = "/ad/" not in path and "popunder" not in path
        return (parsed.scheme in ("http", "https") and bool(parsed.netloc) and is_video and is_not_ad)

    def destroy(self):
        self._ua = None
        self._web_opened = set()

    @staticmethod
    def _safe_label(value):
        return str(value or '').replace('$', '＄').replace('#', '＃').strip()

    # ---------------- 流地址提取 ----------------

    def _extract_streams(self, html):
        """從詳情頁提取流地址。回傳 [(label, url), ...]

        新版式（2026 實測真實詳情頁）：頁面已沒有 stream_url_* 變量，
        改為 var stream_data = {'240p': ['...mp4'], '480p': [...],
        '720p': [], 'm3u8': ['...master.m3u8'], 'm3u8_240p': [...]}，
        空陣列表示該畫質不可用。先解這個；老鏡像站若還有
        stream_url_<畫質> = '...' 再走舊規則兜底。
        注意只認這兩處來源，不掃全頁 .mp4——頁面裡 tbv.sb-cd.com
        的 td.mp4 是預覽縮略影片，掃了會把預覽當正片。
        """
        streams = []
        seen = set()
        if not html:
            return streams

        block = re.search(r'stream_data\s*=\s*\{(.*?)\}\s*;', html, re.S)
        if block:
            for m in re.finditer(r"'([^']+)'\s*:\s*\[\s*(?:'([^']+)')?", block.group(1)):
                label, url = m.groups()
                if not url:
                    continue
                url = html_unescape(url.replace('\\/', '/')).strip()
                if not url.startswith("http") or url in seen:
                    continue
                if not any(ext in url.lower() for ext in (".m3u8", ".mp4", ".mpd")):
                    continue
                seen.add(url)
                streams.append((label.strip(), url))
            if streams:
                return streams

        for m in re.finditer(r'stream_url_([^\s=]+)\s*=\s*(["\'])((?:(?!\2).)+)\2', html):
            label, _, url = m.groups()
            url = html_unescape(url.replace('\\/', '/')).strip()
            if not url.startswith("http") or url in seen:
                continue
            if not any(ext in url.lower() for ext in (".m3u8", ".mp4", ".mpd")):
                continue
            seen.add(url)
            streams.append((label.strip(), url))
        return streams

    @staticmethod
    def _stream_rank(item):
        label, url = item
        low_label = label.lower()
        low_url = url.lower()
        if "m3u8" in low_label or ".m3u8" in low_url:
            return (2, 0)
        m = re.search(r'(\d{3,4})\s*p', low_label)
        return (1, int(m.group(1)) if m else 0)

    def _sort_streams(self, streams):
        return sorted(streams, key=self._stream_rank, reverse=True)

    def _best_stream(self, streams):
        if not streams:
            return ""
        return self._sort_streams(streams)[0][1]

    def _streams_via_api(self, html, page_url):
        """data-streamkey 兜底：POST /api/videos/stream 換取流地址表。

        宿主 OkHttp 若不支持 POST 會直接異常，這裡全包 try，失敗
        就回空列表，交回上層走嗅探兜底，不影響主流程。
        """
        m = re.search(r'data-streamkey\s*=\s*["\']([^"\']+)["\']', html or '', re.I)
        if not m:
            return []
        try:
            from com.github.catvod.net import OkHttp
            from java.util import HashMap

            if not hasattr(OkHttp, "post"):
                return []

            headers = HashMap()
            for k, v in self._get_headers(referer=page_url).items():
                headers.put(k, v)
            headers.put("X-Requested-With", "XMLHttpRequest")
            headers.put("Content-Type", "application/x-www-form-urlencoded")

            body = f"id={quote(m.group(1))}&data=0"
            api_url = f"{self.site_url}/api/videos/stream"
            response = OkHttp.post(api_url, body, headers)
            text = ""
            if response is not None:
                if isinstance(response, str):
                    text = response
                else:
                    try:
                        resp_body = response.body()
                        text = str(resp_body.string()) if resp_body is not None else ""
                    finally:
                        try:
                            response.close()
                        except Exception:
                            pass
            data = json.loads(text) if text else {}
            streams = []
            if isinstance(data, dict):
                for label, value in data.items():
                    url = value[0] if isinstance(value, list) and value else value
                    if isinstance(url, str) and url.startswith("http"):
                        streams.append((str(label), url))
            return streams
        except Exception:
            return []

    # ---------------- 網路請求與 Cloudflare 自動避盾 ----------------

    def _get_cookie(self):
        try:
            from android.webkit import CookieManager
            return str(CookieManager.getInstance().getCookie(self.site_url) or "")
        except Exception:
            return ""

    def _get_ua(self):
        if getattr(self, "_ua", None):
            return self._ua
        try:
            from com.fongmi.android.tv.ui.activity import WebActivity
            self._ua = str(WebActivity.getUserAgent() or DEFAULT_UA)
        except Exception:
            self._ua = DEFAULT_UA
        return self._ua

    def _get_headers(self, referer=None):
        headers = {
            "User-Agent": self._get_ua(),
            "Referer": referer or (self.site_url + "/"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        cookie = self._get_cookie()
        parts = [p.strip() for p in cookie.split(";") if p.strip()]
        if self.country and not any(p.startswith("country=") for p in parts):
            parts.append(f"country={self.country}")
        if parts:
            headers["Cookie"] = "; ".join(parts)
        return headers

    @staticmethod
    def _is_challenge(html):
        if not html:
            return False
        return (
            "Just a moment..." in html
            or "cf-challenge" in html
            or "challenge-running" in html
            or "Checking your browser" in html
            or ("cloudflare" in html.lower() and "ray id" in html.lower())
        )

    def _request_once(self, url, timeout=REQUEST_TIMEOUT_SECONDS):
        """單次請求，回傳 (status, html)；例外向上拋由 _fetch_html 重試。"""
        from com.github.catvod.net import OkHttp
        from java.util import HashMap
        from java.util.concurrent import TimeUnit

        headers = HashMap()
        for k, v in self._get_headers().items():
            headers.put(k, v)

        call = OkHttp.newCall(url, headers)
        try:
            call.timeout().timeout(timeout, TimeUnit.SECONDS)
        except Exception:
            pass
        response = call.execute()
        try:
            code = response.code()
            body = response.body()
            html = str(body.string()) if body is not None else ""
            return code, html
        finally:
            response.close()

    def _open_web_and_wait(self, url):
        """開啟內建 WebView 過盾，短輪詢等 Cookie 寫回（最多約 3 秒）。

        v1 在這裡等 8 秒再疊加重試，一次分類加載能拖到幾十秒，
        超過 App 等待上限後直接顯示空白——等待必須短：已過盾或
        自動過盾的情況 3 秒內 Cookie 就會回來；需要用戶手動完成
        挑戰的，等再久也沒用，快速失敗讓用戶過完盾再點一次即可。
        同一網址只開一次 WebView。
        """
        opened = getattr(self, "_web_opened", None)
        if opened is None:
            opened = self._web_opened = set()
        if url not in opened:
            opened.add(url)
            try:
                from com.fongmi.android.tv.ui.activity import WebActivity
                WebActivity.open(url)
            except Exception:
                return False
        for _ in range(3):
            time.sleep(1)
            cookie = self._get_cookie()
            if "cf_clearance" in cookie:
                return True
        return bool(self._get_cookie())

    def _request_via_requests(self, url, timeout=REQUEST_TIMEOUT_SECONDS):
        """第二通道：Python requests（OpenSSL TLS 指紋與 Java OkHttp 不同）。

        全局代理的共享出口 IP 容易被 Cloudflare 按 TLS 指紋間歇
        攔截：瀏覽器能過、OkHttp 被 403/超時，並不代表另一條 TLS
        通道也不行。用戶的其他爬蟲（51 吸瓜）用的就是 requests，
        證明其運行環境有這個庫；沒有時拋 ImportError 由上層跳過。
        回傳 (status, html)。
        """
        if getattr(self, "_requests_broken", False):
            raise ImportError("requests unavailable")
        try:
            import requests
        except Exception:
            self._requests_broken = True
            raise
        resp = requests.get(url, headers=self._get_headers(), timeout=(6, timeout))
        return resp.status_code, resp.text or ""

    def _fetch_html(self, url, budget=26, timeout=REQUEST_TIMEOUT_SECONDS):
        """頁面請求：雙通道 + 總時長預算。

        通道順序：OkHttp -> requests -> OkHttp。任一通道拿到
        正常頁面立即回傳；遇到 Cloudflare 挑戰只開一次 WebView
        短等 Cookie，之後繼續走下一個通道（Cookie 每次請求都
        重新讀取，會自動帶上新回來的 cf_clearance）。
        整體受 budget 秒牆鐘預算限制，不會再拖到 App 超時；
        404 直接放棄，不浪費預算。詳情/播放傳入更大的
        timeout/budget：詳情頁比列表頁重，12 秒整頁超時在
        共享代理下容易先被詳情頁撞上。
        """
        deadline = time.time() + budget
        challenge_tried = False
        transports = (self._request_once, self._request_via_requests, self._request_once)
        for fn in transports:
            if time.time() > deadline:
                break
            try:
                code, html = fn(url, timeout=timeout)
            except Exception:
                code, html = 0, ""

            if code == 200 and html and not self._is_challenge(html):
                return html

            if code == 404:
                return ""

            if self._is_challenge(html) or code in (403, 530):
                if not challenge_tried:
                    challenge_tried = True
                    self._open_web_and_wait(url)
                continue

            if code in (0, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524):
                time.sleep(0.8)
                continue

            # 其他狀態碼也換下一個通道再試（例如被回跳轉頁/攔截頁）
            continue
        return ""

    # ---------------- 列表解析 ----------------

    def _has_next_page(self, html, page, item_count):
        """是否有下一頁：優先看分頁區的 next 連結，其次才用條數估算。"""
        if not html:
            return item_count >= PAGE_SIZE
        if re.search(r'rel=["\']next["\']', html, re.I):
            return True
        if re.search(r'>\s*(?:Next|下一页|下一頁)\s*<', html, re.I):
            return True
        if re.search(rf'href=["\'][^"\']*/{page + 1}/?["\'?]', html):
            return True
        return item_count >= PAGE_SIZE

    def _pick_pic(self, blob):
        """從一組卡片 HTML 裡挑封面：data-src > srcset 首圖 > src。"""
        candidates = []

        def usable(u):
            u = html_unescape((u or '').strip())
            if not u or u.startswith('data:'):
                return ''
            low = u.lower()
            if any(x in low for x in ('blank', 'loading', 'placeholder', 'logo', 'sprite')):
                return ''
            if not re.search(r'\.(?:jpg|jpeg|png|webp|gif)(?:[?#]|$)', low):
                return ''
            if u.startswith('//'):
                u = 'https:' + u
            elif not u.startswith('http'):
                u = urljoin(self.site_url, u)
            return u

        for m in re.finditer(r'<img[^>]*>', blob, re.S | re.I):
            tag = m.group(0)
            for attr in ('data-src', 'data-original', 'src'):
                am = re.search(rf'\b{attr}=["\']([^"\']+)["\']', tag, re.I)
                if am:
                    pic = usable(am.group(1))
                    if pic:
                        return pic
            sm = re.search(r'\b(?:data-srcset|srcset)=["\']([^"\']+)["\']', tag, re.I)
            if sm:
                pic = usable(sm.group(1).split(',')[0].split()[0])
                if pic:
                    candidates.append(pic)
        if candidates:
            return candidates[0]
        for m in re.finditer(r'(?:data-srcset|data-src|srcset|src)=["\']([^"\']+)["\']', blob, re.I):
            pic = usable(m.group(1).split(',')[0].split()[0])
            if pic:
                return pic
        return ''

    def _pick_title(self, attrs, blob):
        m = re.search(r'\balt=["\']([^"\']+)["\']', blob, re.I)
        if m and len(html_unescape(m.group(1)).strip()) >= 2:
            return html_unescape(m.group(1))
        m = re.search(r'\btitle=["\']([^"\']+)["\']', attrs or '', re.I)
        if m and len(html_unescape(m.group(1)).strip()) >= 2:
            return html_unescape(m.group(1))
        m = re.search(r'class=["\'][^"\']*(?:title|name)[^"\']*["\'][^>]*>(.*?)</', blob, re.S | re.I)
        if m:
            text = re.sub(r'<[^>]+>', '', m.group(1))
            if len(text.strip()) >= 2:
                return html_unescape(text)
        text = re.sub(r'<[^>]+>', ' ', blob)
        text = html_unescape(re.sub(r'\s+', ' ', text)).strip()
        parts = [p.strip() for p in re.split(r'\s{2,}|\n', text) if p.strip()]
        if parts:
            longest = max(parts, key=len)
            if len(longest) >= 2:
                return longest
        return text

    def _aggregate_cards(self, html, pattern):
        """按影片路徑聚合卡片：同一影片的縮圖 <a> 與標題 <a> 合併成一筆。

        原寫法逐個 <a> 判斷，第一個 <a> 缺圖或缺標題就整筆丟棄，
        同一影片的另一半資訊再也用不上——這是「有時有、有時沒有」
        的主要來源。
        """
        groups = {}
        order = []
        for m in re.finditer(pattern, html, re.S | re.I):
            attrs, href, content = m.group('attrs'), m.group('href'), m.group('body')
            vod_id = href.split('?')[0].split('#')[0].strip('/ ')
            if not vod_id or 'javascript:' in href:
                continue
            if vod_id not in groups:
                groups[vod_id] = {'attrs': attrs, 'blobs': []}
                order.append(vod_id)
            groups[vod_id]['blobs'].append(content)
            if attrs and 'title=' in attrs and 'title=' not in groups[vod_id]['attrs']:
                groups[vod_id]['attrs'] = attrs

        items = []
        for vod_id in order:
            group = groups[vod_id]
            blob = '\n'.join(group['blobs'])
            title = self._pick_title(group['attrs'], blob)
            title = re.sub(r'\s+', ' ', title).strip()
            # 文本兜底時標題頭尾可能粘上時長（如 "05:06 Split Card..."），去掉
            title = re.sub(r'^\d{1,2}:\d{2}(?::\d{2})?\s+', '', title)
            title = re.sub(r'\s+\d{1,2}:\d{2}(?::\d{2})?$', '', title).strip()
            if not title or len(title) < 2:
                continue
            pic = self._pick_pic(blob)
            dur = re.search(r'\b(\d{1,2}:\d{2}(?::\d{2})?)\b', re.sub(r'<[^>]+>', ' ', blob))
            items.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": dur.group(1) if dur else "HD",
                "style": {"type": "rect", "ratio": 0.75},
            })
        return items

    def _parse_video_list(self, html):
        """影片卡片解析：先用嚴格的影片路徑聚合，太少再回退寬鬆規則。"""
        if not html:
            return []

        strict = (
            r'<a(?P<attrs>[^>]*)href=["\'](?P<href>/[\da-z]+/(?:video|play)/[^"\']*)["\']'
            r'[^>]*>(?P<body>.*?)</a>'
        )
        items = self._aggregate_cards(html, strict)
        if len(items) >= 3:
            return items

        loose = (
            r'<a(?P<attrs>[^>]*)href=["\'](?P<href>/[^"\']*(?:/video/|[\da-z]{4,})[^"\']*)["\']'
            r'[^>]*>(?P<body>.*?)</a>'
        )
        loose_items = self._aggregate_cards(html, loose)
        loose_items = [
            it for it in loose_items
            if '/s/' not in it['vod_id'] and '/profile/' not in it['vod_id']
        ]
        return loose_items if len(loose_items) > len(items) else items
