# coding=utf-8
import json
import re
import time
from urllib.parse import urlencode, urljoin

import requests

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass


class Spider(BaseSpider):
    """白嫖者联盟 TVBox Python 爬虫（修正版）"""

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
        self.timeout = 15

        # 分类ID映射（若站点使用数字ID，请在此调整）
        self.CLASS_ID_MAP = {
            "movie": "1",    # 电影
            "series": "2",   # 电视剧
            "anime": "3",    # 动漫
            "variety": "4"   # 综艺
        }
        # 保留原分类列表（用于前端展示）
        self.classes = [
            {"type_id": "movie", "type_name": "电影"},
            {"type_id": "series", "type_name": "电视剧"},
            {"type_id": "anime", "type_name": "动漫"},
            {"type_id": "variety", "type_name": "综艺"}
        ]

        # 调试开关（输出请求URL和响应摘要）
        self.DEBUG = True

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

    # ---------- 工具方法 ----------
    def _log(self, msg):
        if self.DEBUG:
            print(f"[{self.site_name}] {msg}")

    def _build_api_url(self, path, params=None):
        url = self.api_url + path
        if params:
            filtered = {k: str(v) for k, v in params.items() if v and v != "" and v is not None}
            if filtered:
                url += "?" + urlencode(filtered)
        return url

    def _api_get(self, path, params=None, retry=2):
        """带重试的API GET请求"""
        url = self._build_api_url(path, params)
        self._log(f"请求URL: {url}")
        for attempt in range(retry):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    self._log(f"状态码异常: {resp.status_code}")
                    continue
                data = resp.json()
                self._log(f"响应摘要: {json.dumps(data, ensure_ascii=False)[:200]}...")
                return data
            except requests.exceptions.RequestException as e:
                self._log(f"请求失败 (尝试{attempt+1}/{retry}): {str(e)}")
                time.sleep(1)
            except json.JSONDecodeError as e:
                self._log(f"JSON解析失败: {str(e)}")
                break
        return None

    def _parse_card(self, card):
        """解析卡片数据为标准vod字段"""
        if not card or not card.get("id"):
            return None
        return {
            "vod_id": str(card.get("id", "")),
            "vod_name": card.get("title") or card.get("normalized_title") or "",
            "vod_pic": card.get("poster_url") or "",
            "vod_remarks": card.get("remarks") or "",
            "vod_year": str(card.get("year")) if card.get("year") else "",
            "vod_area": card.get("area") or ""
        }

    # ---------- 过滤器 ----------
    def _get_genre_filter(self):
        return {
            "key": "genre",
            "name": "类型",
            "value": [{"n": "全部", "v": ""}] + [{"n": g, "v": g} for g in
                ["动作","喜剧","爱情","科幻","悬疑","惊悚","恐怖","剧情","战争","古装","武侠","历史","奇幻","冒险","犯罪","家庭","运动","音乐","青春","玄幻","热血","都市","言情"]]
        }

    def _get_area_filter(self):
        return {
            "key": "area",
            "name": "地区",
            "value": [{"n": "全部", "v": ""}] + [{"n": a, "v": a} for a in
                ["中国大陆","美国","日本","韩国","中国香港","中国台湾","法国","印度","泰国","越南"]]
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
            "value": [{"n": "热门", "v": "hot"}, {"n": "最新", "v": "new"}]
        }

    def _common_filters(self):
        return [self._get_genre_filter(), self._get_area_filter(), self._get_year_filter(), self._get_sort_filter()]

    def _filters(self):
        result = {}
        for item in self.classes:
            result[item["type_id"]] = self._common_filters()
        return result

    # ---------- 首页 ----------
    def homeContent(self, filter=False):
        videos = []
        try:
            data = self._api_get("/feed/home")
            if data:
                # 尝试多种可能的路径
                sections = data.get("sections") or data.get("data", {}).get("sections") or []
                if not sections and data.get("list"):
                    # 有些接口直接返回list
                    for item in data["list"]:
                        card = {"id": item.get("id"), "title": item.get("title"), "poster_url": item.get("poster"), "remarks": item.get("remarks")}
                        parsed = self._parse_card(card)
                        if parsed:
                            videos.append(parsed)
                else:
                    seen = set()
                    for section in sections:
                        for card in section.get("cards", []):
                            if card.get("id") not in seen:
                                seen.add(card["id"])
                                item = self._parse_card(card)
                                if item:
                                    videos.append(item)
        except Exception as e:
            self._log(f"首页获取异常: {str(e)}")

        return {
            "class": self.classes,
            "filters": self._filters(),
            "list": videos[:30]
        }

    def homeVideoContent(self):
        # 简单复用 homeContent 逻辑
        return self.homeContent(filter=False)

    # ---------- 分类 ----------
    def categoryContent(self, tid, pg, filter=False, extend=None):
        pg = int(pg or 1)
        extend = extend or {}
        result = {"list": [], "page": pg, "pagecount": 0, "limit": 20, "total": 0}

        try:
            # 将 tid 转换为站点实际ID（如果映射存在）
            real_tid = self.CLASS_ID_MAP.get(tid, tid)
            params = {
                "kind": real_tid,
                "page": str(pg)
            }
            # 添加过滤参数
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
            if data:
                cards = data.get("cards") or data.get("data", {}).get("cards") or []
                for card in cards:
                    item = self._parse_card(card)
                    if item:
                        # 本地过滤年份范围（若API不支持）
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

                # 分页信息
                pagination = data.get("pagination") or {}
                has_more = pagination.get("has_more", False)
                next_page = pagination.get("next_page")
                if has_more and next_page:
                    result["pagecount"] = next_page
                elif has_more and not next_page:
                    result["pagecount"] = pg + 1
                else:
                    result["pagecount"] = pg
                # 尝试获取total
                result["total"] = pagination.get("total", len(videos))
            result["list"] = videos
        except Exception as e:
            self._log(f"分类列表获取异常: {str(e)}")

        return result

    # ---------- 搜索 ----------
    def searchContent(self, key, quick=False, pg=1):
        pg = int(pg or 1)
        key = str(key or "").strip()
        result = {"list": [], "page": pg, "pagecount": 0, "limit": 20, "total": 0}
        if not key:
            return result

        try:
            # 尝试两种搜索接口：/browse/catalog?q= 或 /search?wd=
            data = None
            # 优先尝试 /search（常见）
            search_data = self._api_get("/search", {"wd": key, "page": str(pg)})
            if search_data and (search_data.get("cards") or search_data.get("list")):
                data = search_data
            else:
                # 备选 /browse/catalog
                data = self._api_get("/browse/catalog", {"q": key, "page": str(pg)})

            videos = []
            if data:
                cards = data.get("cards") or data.get("list") or []
                for card in cards:
                    item = self._parse_card(card)
                    if item:
                        videos.append(item)

                pagination = data.get("pagination") or {}
                has_more = pagination.get("has_more", False)
                next_page = pagination.get("next_page")
                if has_more and next_page:
                    result["pagecount"] = next_page
                elif has_more and not next_page:
                    result["pagecount"] = pg + 1
                else:
                    result["pagecount"] = pg
                result["total"] = pagination.get("total", len(videos))
            result["list"] = videos
        except Exception as e:
            self._log(f"搜索异常: {str(e)}")

        return result

    # ---------- 详情 ----------
    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) else ids
        vod_id = str(raw_id).strip()
        result = {"list": []}
        if not vod_id:
            return result

        try:
            # 提取variant_id（若为URL）
            variant_id = vod_id
            if vod_id.startswith("http"):
                match = re.search(r"/catalog/([^?]+)", vod_id)
                if match:
                    variant_id = match.group(1)

            data = self._api_get("/catalog/" + variant_id)
            if not data or not data.get("variant_id"):
                # 尝试备用接口
                data = self._api_get("/catalog", {"id": variant_id})
                if not data:
                    return result

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
            episodes_data = data.get("episodes")
            if not episodes_data:
                # 尝试独立剧集接口
                ep_data = self._api_get("/catalog/" + variant_id + "/episodes")
                if ep_data and ep_data.get("episodes"):
                    episodes_data = ep_data["episodes"]

            if episodes_data:
                line_order = ["yjm3u8", "yjapi", "yjplayer"]
                line_name_map = {
                    "yjm3u8": "线路1",
                    "yjapi": "线路2",
                    "yjplayer": "线路3"
                }
                # 从 playback_groups 获取更友好的线路名
                if data.get("playback_groups"):
                    for pg in data["playback_groups"]:
                        if pg.get("id") in line_name_map and pg.get("label"):
                            line_name_map[pg["id"]] = pg["label"]

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

            result["list"] = [{
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
        except Exception as e:
            self._log(f"详情解析异常 [ID: {vod_id}]: {str(e)}")

        return result

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags=None):
        play_url = str(id or "")
        headers = {
            "User-Agent": self.ua,
            "Referer": self.site_url + "/"
        }

        try:
            # YJ API 端点：解析 JSON 直链
            if "/playback/yjapi/" in play_url:
                try:
                    resp = self.session.get(play_url, headers=headers, timeout=self.timeout)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data and data.get("url"):
                            return {
                                "parse": 0,
                                "playUrl": "",
                                "url": data["url"],
                                "header": headers
                            }
                except Exception as e:
                    self._log(f"解析 yjapi 失败: {str(e)}")
                # 解析失败时交给播放器嗅探
                return {
                    "parse": 1,
                    "playUrl": "",
                    "url": play_url,
                    "header": headers
                }

            # m3u8 / mp4 直链
            if play_url.startswith("http") and (".m3u8" in play_url or ".mp4" in play_url):
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": play_url,
                    "header": headers
                }

            # 其它情况默认嗅探
            return {
                "parse": 1,
                "playUrl": "",
                "url": play_url,
                "header": headers
            }
        except Exception as e:
            self._log(f"播放解析异常: {str(e)}")
            return {"parse": 0, "playUrl": "", "url": "", "header": {}}

    def localProxy(self, param):
        return [404, "text/plain", "not found"]

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(?:m3u8|mp4|flv|mkv|ts)(?:\?|$)", str(url), re.I))

    def manualVideoCheck(self):
        return False