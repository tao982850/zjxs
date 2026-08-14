# coding=utf-8
import json
import re
from urllib.parse import urlencode, urljoin

import requests

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass


class Spider(BaseSpider):
    """白嫖者联盟 TVBox Python 爬虫（绿豆/OK影视等通用格式）。"""

    def __init__(self):
        self.site_name = "白嫖者联盟"
        self.site_url = "https://ai.baipiaozhe.com"
        self.api_url = "https://ai.baipiaozhe.com/v1"
        self.m3u8_host = "https://zy.baipiaozhe.com/v1/playback/yjm3u8"
        self.ua = (
            "Mozilla/5.0 (Linux; Android 10; K) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Mobile Safari/537.36"
        )

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.ua,
            "Accept": "application/json",
            "Referer": self.site_url + "/"
        })

        self.classes = [
            {"type_id": "movie", "type_name": "电影"},
            {"type_id": "series", "type_name": "电视剧"},
            {"type_id": "anime", "type_name": "动漫"},
            {"type_id": "variety", "type_name": "综艺"}
        ]

    def getName(self):
        return self.site_name

    def init(self, extend=""):
        if isinstance(extend, str) and extend.strip().startswith("http"):
            self.site_url = extend.strip().rstrip("/")
            self.api_url = self.site_url + "/v1"
        elif isinstance(extend, dict):
            host = extend.get("host") or extend.get("url")
            if host:
                self.site_url = str(host).rstrip("/")
                self.api_url = self.site_url + "/v1"

    def destroy(self):
        return None

    def _get_genre_filter(self):
        return {
            "key": "genre",
            "name": "类型",
            "value": [
                {"n": "全部", "v": ""},
                {"n": "动作", "v": "动作"},
                {"n": "喜剧", "v": "喜剧"},
                {"n": "爱情", "v": "爱情"},
                {"n": "科幻", "v": "科幻"},
                {"n": "悬疑", "v": "悬疑"},
                {"n": "惊悚", "v": "惊悚"},
                {"n": "恐怖", "v": "恐怖"},
                {"n": "剧情", "v": "剧情"},
                {"n": "战争", "v": "战争"},
                {"n": "古装", "v": "古装"},
                {"n": "武侠", "v": "武侠"},
                {"n": "历史", "v": "历史"},
                {"n": "奇幻", "v": "奇幻"},
                {"n": "冒险", "v": "冒险"},
                {"n": "犯罪", "v": "犯罪"},
                {"n": "家庭", "v": "家庭"},
                {"n": "运动", "v": "运动"},
                {"n": "音乐", "v": "音乐"},
                {"n": "青春", "v": "青春"},
                {"n": "玄幻", "v": "玄幻"},
                {"n": "热血", "v": "热血"},
                {"n": "都市", "v": "都市"},
                {"n": "言情", "v": "言情"}
            ]
        }

    def _get_area_filter(self):
        return {
            "key": "area",
            "name": "地区",
            "value": [
                {"n": "全部", "v": ""},
                {"n": "中国大陆", "v": "中国大陆"},
                {"n": "美国", "v": "美国"},
                {"n": "日本", "v": "日本"},
                {"n": "韩国", "v": "韩国"},
                {"n": "中国香港", "v": "中国香港"},
                {"n": "中国台湾", "v": "中国台湾"},
                {"n": "法国", "v": "法国"},
                {"n": "印度", "v": "印度"},
                {"n": "泰国", "v": "泰国"},
                {"n": "越南", "v": "越南"}
            ]
        }

    def _get_year_filter(self):
        import datetime
        years = [{"n": "全部", "v": ""}]
        current_year = datetime.datetime.now().year
        for y in range(current_year, 2009, -1):
            years.append({"n": str(y), "v": str(y)})
        years.append({"n": "2000-2009", "v": "2000-2009"})
        years.append({"n": "更早", "v": "older"})
        return {"key": "year", "name": "年份", "value": years}

    def _get_sort_filter(self):
        return {
            "key": "sort",
            "name": "排序",
            "value": [
                {"n": "热门", "v": "hot"},
                {"n": "最新", "v": "new"}
            ]
        }

    def _common_filters(self):
        return [self._get_genre_filter(), self._get_area_filter(), 
                self._get_year_filter(), self._get_sort_filter()]

    def _filters(self):
        result = {}
        for item in self.classes:
            result[item["type_id"]] = self._common_filters()
        return result

    def _build_api_url(self, path, params=None):
        url = self.api_url + path
        if params:
            # 过滤空值并使用 urlencode 正确编码中文参数
            filtered = {k: str(v) for k, v in params.items() if v and v != "" and v is not None}
            if filtered:
                url += "?" + urlencode(filtered)
        return url

    def _api_get(self, path, params=None):
        url = self._build_api_url(path, params)
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print("API请求失败:", str(e))
            return None

    def _parse_card(self, card):
        if not card or not card.get("id"):
            return None
        return {
            "vod_id": card.get("id", ""),
            "vod_name": card.get("title") or card.get("normalized_title") or "",
            "vod_pic": card.get("poster_url") or "",
            "vod_remarks": card.get("remarks") or "",
            "vod_year": str(card.get("year")) if card.get("year") else "",
            "vod_area": card.get("area") or ""
        }

    def homeContent(self, filter=False):
        videos = []
        try:
            data = self._api_get("/feed/home")
            if data and data.get("sections"):
                seen = set()
                for section in data["sections"]:
                    if section.get("cards"):
                        for card in section["cards"]:
                            if card.get("id") not in seen:
                                seen.add(card["id"])
                                item = self._parse_card(card)
                                if item:
                                    videos.append(item)
        except Exception as e:
            print("首页获取失败:", str(e))

        return {
            "class": self.classes,
            "filters": self._filters(),
            "list": videos[:30]
        }

    def homeVideoContent(self):
        try:
            data = self._api_get("/feed/home")
            videos = []
            if data and data.get("sections"):
                seen = set()
                for section in data["sections"]:
                    if section.get("cards"):
                        for card in section["cards"]:
                            if card.get("id") not in seen:
                                seen.add(card["id"])
                                item = self._parse_card(card)
                                if item:
                                    videos.append(item)
            return {"list": videos[:30]}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        pg = int(pg or 1)
        extend = extend or {}
        
        try:
            params = {
                "kind": tid,
                "page": str(pg)
            }
            
            if extend.get("genre"):
                params["genre"] = str(extend["genre"])
            if extend.get("area"):
                params["area"] = str(extend["area"])
            if extend.get("year"):
                year_val = str(extend["year"])
                if year_val not in ["2000-2009", "older"]:
                    params["year"] = year_val
            if extend.get("sort"):
                params["sort"] = str(extend["sort"])
            
            data = self._api_get("/browse/catalog", params)
            
            videos = []
            if data and data.get("cards"):
                for card in data["cards"]:
                    item = self._parse_card(card)
                    if item:
                        # 本地过滤特殊年份范围
                        year_val = str(extend.get("year", ""))
                        if year_val == "2000-2009":
                            try:
                                y = int(item["vod_year"])
                                if y < 2000 or y > 2009:
                                    continue
                            except (ValueError, TypeError):
                                continue
                        elif year_val == "older":
                            try:
                                y = int(item["vod_year"])
                                if y >= 2000:
                                    continue
                            except (ValueError, TypeError):
                                continue
                        videos.append(item)
            
            pagecount = 1
            if data and data.get("pagination"):
                if data["pagination"].get("has_more"):
                    pagecount = data["pagination"].get("next_page") or (pg + 1)
                elif not data["pagination"].get("has_more") and len(videos) == 0:
                    pagecount = 0
                else:
                    pagecount = pg
            
            return {
                "list": videos,
                "page": pg,
                "pagecount": pagecount,
                "limit": 20,
                "total": pagecount * 20
            }
        except Exception as e:
            print("分类列表获取失败:", str(e))
            return {"list": [], "page": pg, "pagecount": 0, "limit": 20, "total": 0}

    def searchContent(self, key, quick=False, pg=1):
        pg = int(pg or 1)
        key = str(key or "").strip()
        if not key:
            return {"list": [], "page": pg, "pagecount": 0}

        try:
            # 改用 /browse/catalog 真正的搜索列表接口，支持封面图和真实分页
            params = {
                "q": key,
                "page": str(pg)
            }
            data = self._api_get("/browse/catalog", params)

            videos = []
            if data and data.get("cards"):
                for card in data["cards"]:
                    item = self._parse_card(card)
                    if item:
                        videos.append(item)

            # 解析真实分页信息
            pagination = data.get("pagination") if data else None
            has_more = pagination.get("has_more") if pagination else False
            total = pagination.get("total") if pagination else len(videos)
            limit = pagination.get("limit") if pagination else 20

            if has_more:
                pagecount = pagination.get("next_page") or (pg + 1)
            elif total == 0:
                pagecount = 0
            else:
                pagecount = pg

            return {
                "list": videos,
                "page": pg,
                "pagecount": pagecount,
                "limit": limit,
                "total": total
            }
        except Exception as e:
            print("搜索失败:", str(e))
            return {"list": [], "page": pg, "pagecount": 0, "limit": 20, "total": 0}

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else ids
        vod_id = str(raw_id).strip()
        if not vod_id:
            return {"list": []}
        
        try:
            # 如果 ID 是完整 URL，提取 variant_id
            variant_id = vod_id
            if vod_id.startswith("http"):
                match = re.search(r"/catalog/([^?]+)", vod_id)
                if match:
                    variant_id = match.group(1)
            
            data = self._api_get("/catalog/" + variant_id)
            
            if not data or not data.get("variant_id"):
                return {"list": []}
            
            vod_name = data.get("title") or ""
            vod_pic = data.get("poster_url") or ""
            vod_year = str(data.get("year")) if data.get("year") else ""
            vod_area = data.get("area") or ""
            vod_class = ",".join(data.get("genres") or [])
            vod_actor = ",".join(data.get("actors") or [])
            vod_director = ",".join(data.get("directors") or [])
            vod_remarks = data.get("remarks") or ""
            vod_content = data.get("description") or ""
            vod_lang = data.get("language") or ""
            
            lines = []
            playlists = []
            
            # 获取剧集数据
            episodes_data = data.get("episodes") if data.get("episodes") else None
            
            # 如果详情中没有剧集，尝试独立剧集接口
            if not episodes_data:
                try:
                    ep_data = self._api_get("/catalog/" + variant_id + "/episodes")
                    if ep_data and ep_data.get("episodes"):
                        episodes_data = ep_data["episodes"]
                except Exception:
                    pass
            
            if episodes_data and len(episodes_data) > 0:
                line_order = ["yjm3u8", "yjapi", "yjplayer"]
                line_name_map = {
                    "yjm3u8": "线路1",
                    "yjapi": "线路2",
                    "yjplayer": "线路3"
                }
                
                # playback_groups 中的标签作为更友好的线路名
                if data.get("playback_groups"):
                    for pg in data["playback_groups"]:
                        if pg.get("id") and pg["id"] in line_name_map and pg.get("label"):
                            line_name_map[pg["id"]] = pg["label"]
                
                # 按线路分组
                line_groups = {}
                for ep in episodes_data:
                    ep_name = ep.get("title") or ep.get("display_name") or ("第" + str(ep.get("number", 1)) + "集")
                    urls = ep.get("urls") or {}
                    for line_key in line_order:
                        url = urls.get(line_key)
                        if url:
                            if line_key not in line_groups:
                                line_groups[line_key] = []
                            line_groups[line_key].append(ep_name + "$" + url)
                
                # 输出线路
                for line_key in line_order:
                    if line_key in line_groups and line_groups[line_key]:
                        lines.append(line_name_map.get(line_key, line_key))
                        playlists.append("#".join(line_groups[line_key]))
                
                # 兜底：如果 urls 全空但有 token，构造 m3u8 直链
                if not lines:
                    fallback_eps = []
                    for i, ep in enumerate(episodes_data):
                        ep_name = ep.get("title") or ep.get("display_name") or ("第" + str(ep.get("number", i + 1)) + "集")
                        ep_token = ep.get("token") or ""
                        if ep_token:
                            m3u8_url = self.m3u8_host + "/" + ep_token + ".m3u8"
                            fallback_eps.append(ep_name + "$" + m3u8_url)
                    if fallback_eps:
                        lines.append("m3u8线路")
                        playlists.append("#".join(fallback_eps))
            
            if not lines:
                lines.append("默认")
                playlists.append(vod_id)
            
            vod_play_from = "$$$".join(lines)
            vod_play_url = "$$$".join(playlists)
            
            return {
                "list": [{
                    "vod_id": vod_id,
                    "vod_name": vod_name,
                    "vod_pic": vod_pic,
                    "vod_actor": vod_actor,
                    "vod_director": vod_director,
                    "vod_remarks": vod_remarks,
                    "vod_year": vod_year,
                    "vod_area": vod_area,
                    "vod_content": vod_content,
                    "vod_class": vod_class,
                    "vod_lang": vod_lang,
                    "vod_play_from": vod_play_from,
                    "vod_play_url": vod_play_url
                }]
            }
        except Exception as e:
            print("解析详情异常 [ID: " + vod_id + "]:", str(e))
            return {"list": []}

    def playerContent(self, flag, id, vipFlags=None):
        play_url = str(id or "")
        headers = {
            "User-Agent": self.ua,
            "Referer": self.site_url + "/"
        }
        
        try:
            # YJ API 端点：返回 JSON，需解析出真实直链
            if "/playback/yjapi/" in play_url:
                try:
                    resp = self.session.get(play_url, headers={
                        "User-Agent": self.ua,
                        "Accept": "application/json",
                        "Referer": self.site_url + "/"
                    }, timeout=15)
                    resp.raise_for_status()
                    data = resp.json()
                    if data and data.get("url"):
                        return {
                            "parse": 0,
                            "playUrl": "",
                            "url": data["url"],
                            "header": headers
                        }
                except Exception as e:
                    print("解析 yjapi 失败:", str(e))
                # 解析失败时交给播放器嗅探
                return {
                    "parse": 1,
                    "playUrl": "",
                    "url": play_url,
                    "header": headers
                }
            
            # m3u8 直链（含 302 跳转的 yjm3u8 端点）以及 mp4 直链
            if play_url.startswith("http") and ("yjm3u8" in play_url or ".m3u8" in play_url or ".mp4" in play_url):
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": play_url,
                    "header": headers
                }
            
            # 其它情况交给播放器嗅探
            return {
                "parse": 1,
                "playUrl": "",
                "url": play_url,
                "header": headers
            }
        except Exception as e:
            print("播放失败:", str(e))
            return {"parse": 0, "playUrl": "", "url": "", "header": {}}

    def localProxy(self, param):
        return [404, "text/plain", "not found"]

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(?:m3u8|mp4|flv|mkv|ts)(?:\?|$)", str(url), re.I))

    def manualVideoCheck(self):
        return False
