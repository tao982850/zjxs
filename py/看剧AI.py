# coding=utf-8
"""
目标站: 看剧AI (kanju.ai)
模板: 影视聚合搜索 / 爬虫播放
站点类型: 综合影视
核心逻辑: 调用 HMAC-SHA256 签名 JSON API，提取视频信息和 m3u8 播放链接
支持: 首页、分类、搜索、详情、播放
"""
import re
import sys
import json
import time
import hmac
import hashlib
import os
import urllib.parse

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    def init(self, extend=""):
        self.site_url = "https://kanju.ai"
        # API 签名密钥 (从前端 JS 提取)
        self.api_secret = "557d0e4ae929f438da6bd84412374e6086b8af09b3fed54bf22601d5bf8c54a0"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.site_url + "/",
            'Origin': self.site_url,
        }
        self.default_pic = "https://pic.rmb.bdstatic.com/bjh/user/default.png"
        # 分类映射: content_kind -> 中文名
        self.categories = {
            "movie": "电影",
            "series": "电视剧",
            "anime": "动漫",
            "variety": "综艺",
            "short_drama": "短剧",
        }

    # ========== 工具方法 ==========

    def _sign_headers(self, method, path_with_search):
        """生成 API 签名请求头

        签名串格式: {METHOD}\\n{pathname}{search}\\n{timestamp}\\n{nonce}
        算法: HMAC-SHA256(密钥, 签名串) -> hex
        """
        ts = str(int(time.time() * 1000))
        nonce = os.urandom(16).hex()
        msg = "{0}\n{1}\n{2}\n{3}".format(method, path_with_search, ts, nonce)
        sig = hmac.new(self.api_secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            **self.headers,
            'x-ai-movie-timestamp': ts,
            'x-ai-movie-nonce': nonce,
            'x-ai-movie-signature': sig,
        }

    def _api_get(self, path):
        """调用签名 API 并返回解析后的 JSON 字典

        path 参数应包含查询字符串，例如 /v1/browse/catalog?kind=movie&page=1
        """
        url = self.site_url + path
        headers = self._sign_headers("GET", path)
        try:
            resp = self.fetch(url, headers=headers)
            if not resp:
                return {}
            return json.loads(resp.text)
        except Exception:
            return {}

    def _parse_card(self, card):
        """将 API 卡片对象转换为 vod 字典 (列表页通用)"""
        vid = card.get("id", "") or ""
        name = card.get("title", "") or ""
        pic = card.get("poster_url", "") or ""
        remark = card.get("remarks", "") or ""
        year = card.get("year", "")
        if year:
            year = str(year)
        else:
            year = ""
        area = card.get("area", "") or ""
        genres = card.get("genres", [])
        type_name = " / ".join(genres[:3]) if genres else ""
        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic if pic else self.default_pic,
            "vod_remarks": remark,
            "vod_year": year,
            "vod_area": area,
            "vod_type": type_name,
        }

    def _calc_pagecount(self, pag, page, limit):
        """根据分页信息计算总页数"""
        total = pag.get("total", 0)
        if total and limit:
            return (total + limit - 1) // limit
        if pag.get("has_more"):
            return page + 1
        return page

    # ========== 首页 ==========

    def homeContent(self, filter):
        """获取首页内容: 分类列表 + 推荐视频"""
        categories = [{"type_id": k, "type_name": v} for k, v in self.categories.items()]

        data = self._api_get("/v1/feed/home")
        videos = []
        seen = set()
        for sec in data.get("sections", []):
            for card in sec.get("cards", []):
                vid = card.get("id", "")
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                videos.append(self._parse_card(card))

        return {"class": categories, "list": videos[:30], "filters": {}}

    def homeVideoContent(self):
        """获取首页推荐视频列表"""
        data = self._api_get("/v1/feed/home")
        videos = []
        seen = set()
        for sec in data.get("sections", []):
            for card in sec.get("cards", []):
                vid = card.get("id", "")
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                videos.append(self._parse_card(card))
        return {"list": videos[:30]}

    # ========== 分类 ==========

    def categoryContent(self, tid, pg, filter, extend):
        """获取分类列表

        tid: content_kind (movie/series/anime/variety/short_drama)
        pg:  页码
        """
        page = int(pg) if pg else 1
        limit = 30
        path = "/v1/browse/catalog?kind={0}&page={1}&limit={2}".format(tid, page, limit)
        data = self._api_get(path)

        cards = data.get("cards", [])
        videos = [self._parse_card(c) for c in cards if c.get("id")]

        pag = data.get("pagination", {})
        total = pag.get("total", 0) or len(videos)
        pagecount = self._calc_pagecount(pag, page, limit)

        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": limit,
            "total": total,
        }

    # ========== 搜索 ==========

    def searchContent(self, key, quick, pg="1"):
        """搜索内容

        key: 搜索关键词
        pg:  页码
        """
        page = int(pg) if pg else 1
        limit = 30
        encoded = urllib.parse.quote(key)
        path = "/v1/browse/catalog?q={0}&page={1}&limit={2}".format(encoded, page, limit)
        data = self._api_get(path)

        cards = data.get("cards", [])
        videos = [self._parse_card(c) for c in cards if c.get("id")]

        pag = data.get("pagination", {})
        total = pag.get("total", 0) or len(videos)
        pagecount = self._calc_pagecount(pag, page, limit)

        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": limit,
            "total": total,
        }

    # ========== 详情 ==========

    def detailContent(self, ids):
        """获取视频详情 (含播放选集)

        ids[0]: 卡片 ID (av_ 开头的长字符串)
        详情接口 /v1/catalog/{id} 返回完整信息，包括剧集列表和 m3u8 直链
        """
        if not ids:
            return {"list": []}

        vid = ids[0]
        data = self._api_get("/v1/catalog/{0}".format(vid))
        if not data or "id" not in data:
            return {"list": []}

        # 基本信息
        title = data.get("title", "") or ""
        pic = data.get("poster_url", "") or self.default_pic
        content = data.get("description", "") or ""
        actors = data.get("actors", [])
        actor = " / ".join(actors[:20]) if actors else ""
        directors = data.get("directors", [])
        director = " / ".join(directors[:10]) if directors else ""
        year = str(data.get("year", "")) if data.get("year") else ""
        area = data.get("area", "") or ""
        genres = data.get("genres", [])
        type_name = " / ".join(genres[:5]) if genres else ""

        # 播放源与选集
        play_from = []
        play_url = []

        episodes = data.get("episodes", [])
        if episodes:
            play_from.append("默认线路")
            ep_list = []
            for ep in episodes:
                ep_title = ep.get("title", "") or ""
                if not ep_title:
                    num = ep.get("number", "")
                    ep_title = "第{0}集".format(num) if num else "播放"
                urls = ep.get("urls", {}) or {}
                # 优先使用 m3u8 直链，其次 yjapi
                play_link = urls.get("yjm3u8", "") or urls.get("yjapi", "")
                if not play_link:
                    continue
                ep_list.append("{0}${1}".format(ep_title, play_link))
            if ep_list:
                play_url.append("#".join(ep_list))

        # 若详情页未包含剧集，尝试调用 episodes 接口
        if not play_from:
            ep_data = self._api_get("/v1/catalog/{0}/episodes".format(vid))
            episodes = ep_data.get("episodes", [])
            if episodes:
                play_from.append("默认线路")
                ep_list = []
                for ep in episodes:
                    ep_title = ep.get("title", "") or ""
                    if not ep_title:
                        num = ep.get("number", "")
                        ep_title = "第{0}集".format(num) if num else "播放"
                    urls = ep.get("urls", {}) or {}
                    play_link = urls.get("yjm3u8", "") or urls.get("yjapi", "")
                    if not play_link:
                        continue
                    ep_list.append("{0}${1}".format(ep_title, play_link))
                if ep_list:
                    play_url.append("#".join(ep_list))

        # 兜底
        if not play_from:
            play_from.append("默认线路")
            play_url.append("播放${0}/v1/catalog/{1}".format(self.site_url, vid))

        result = [{
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": pic,
            "vod_content": content,
            "vod_actor": actor,
            "vod_director": director,
            "vod_year": year,
            "vod_area": area,
            "vod_type": type_name,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }]
        return {"list": result}

    # ========== 播放 ==========

    def playerContent(self, flag, id, vipFlags):
        """获取播放链接

        id 格式: ep_title$m3u8_url (从 vod_play_url 拆分而来)
        m3u8 直链可直接播放，无需嗅探
        """
        play_url = id
        if "$" in id:
            play_url = id.split("$")[-1]

        play_url = play_url.strip()
        if not play_url:
            return {"parse": 1, "url": id, "header": self.headers}

        # m3u8 / mp4 直链直接返回
        if '.m3u8' in play_url or '.mp4' in play_url:
            return {
                "parse": 0,
                "url": play_url,
                "header": {
                    'User-Agent': self.headers['User-Agent'],
                    'Referer': self.site_url + "/",
                }
            }

        # yjapi 链接可能返回重定向到 m3u8，尝试解析
        if 'yjapi' in play_url:
            try:
                resp = self.fetch(play_url, headers={
                    'User-Agent': self.headers['User-Agent'],
                    'Referer': self.site_url + "/",
                })
                if resp:
                    text = resp.text
                    m = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', text)
                    if m:
                        return {
                            "parse": 0,
                            "url": m.group(1),
                            "header": {
                                'User-Agent': self.headers['User-Agent'],
                                'Referer': self.site_url + "/",
                            }
                        }
            except Exception:
                pass

        # 其他情况交给 webview 嗅探
        return {
            "parse": 1,
            "url": play_url,
            "header": self.headers
        }
