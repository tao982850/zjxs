#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
源名称：多多追剧
生成方式：AI自动生成
站点说明：基于 duoduozhuiju.com 发布页指向的 dduotv01.top 影视站
接口假设：苹果CMS标准JSON API（如实际不符请按抓包修改URL）
"""

import json
import requests
import urllib.parse
from base.spider import Spider


class SpiderCustom(Spider):
    # ==================== 基础配置 ====================
    name = "多多追剧"
    base_url = "https://dduotv01.top"
    site_url = "https://dduotv01.top"

    # ==================== 分类映射 ====================
    # 苹果CMS常见分类ID：1电影 2电视剧 3综艺 4动漫
    class_name = ["电影", "剧集", "动漫", "综艺"]
    class_url = ["1", "2", "3", "4"]

    # ==================== 请求参数 ====================
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://dduotv01.top/"
    }
    timeout = 15
    page_size = 20

    # ==================== 工具函数层 ====================

    def _get(self, url, headers=None, params=None):
        """GET请求封装（含异常捕获）"""
        try:
            resp = requests.get(
                url,
                headers=headers or self.headers,
                params=params,
                timeout=self.timeout
            )
            resp.encoding = "utf-8"
            return resp.text
        except Exception as e:
            print(f"[{self.name}] GET请求异常: {e}")
            return None

    def _fetch_json(self, url, headers=None):
        """请求并解析JSON"""
        html = self._get(url, headers)
        if not html:
            return None
        try:
            return json.loads(html)
        except Exception as e:
            print(f"[{self.name}] JSON解析异常: {e}")
            return None

    def _build_vod_item(self, raw, tid=""):
        """标准化影片条目（消除字段名差异）"""
        return {
            "vod_id": str(raw.get("vod_id", raw.get("id", ""))),
            "vod_name": raw.get("vod_name", raw.get("name", raw.get("title", ""))),
            "vod_pic": raw.get("vod_pic", raw.get("pic", raw.get("cover", ""))),
            "vod_remarks": raw.get("vod_remarks", raw.get("remarks", raw.get("update", ""))),
            "vod_year": raw.get("vod_year", raw.get("year", "")),
            "vod_area": raw.get("vod_area", raw.get("area", "")),
            "vod_actor": raw.get("vod_actor", raw.get("actor", "")),
            "vod_director": raw.get("vod_director", raw.get("director", "")),
            "vod_type": raw.get("vod_type", raw.get("type", "")),
            "vod_score": raw.get("vod_score", raw.get("score", "")),
        }

    # ==================== 核心方法实现 ====================

    def homeContent(self, filter=False):
        """首页推荐"""
        result = {"list": []}
        try:
            # 苹果CMS：获取最近24小时更新的内容作为推荐
            # 如实际接口不同，请修改此URL
            url = f"{self.base_url}/api.php/provide/vod/?ac=detail&h=24"
            data = self._fetch_json(url)
            if data and data.get("list"):
                for item in data["list"]:
                    result["list"].append(self._build_vod_item(item))
        except Exception as e:
            print(f"[{self.name}] 首页推荐异常: {e}")
        return result

    def categoryContent(self, tid, pg, filter=False, content=None):
        """分类列表"""
        result = {
            "list": [],
            "page": int(pg),
            "pagecount": 0,
            "limit": self.page_size,
            "total": 0
        }
        try:
            # 苹果CMS分类接口
            # 如实际接口不同，请修改此URL
            url = f"{self.base_url}/api.php/provide/vod/?ac=detail&t={tid}&pg={pg}"
            data = self._fetch_json(url)
            if data and data.get("list"):
                for item in data["list"]:
                    result["list"].append(self._build_vod_item(item, tid))
                result["pagecount"] = int(data.get("pagecount", 0))
                result["total"] = int(data.get("total", 0))
                result["limit"] = int(data.get("limit", self.page_size))
        except Exception as e:
            print(f"[{self.name}] 分类列表异常: {e}")
        return result

    def detailContent(self, ids):
        """影片详情"""
        result = []
        try:
            vod_id = ids if isinstance(ids, str) else ids[0] if ids else ""
            if not vod_id:
                return result

            # 苹果CMS详情接口
            # 如实际接口不同，请修改此URL
            url = f"{self.base_url}/api.php/provide/vod/?ac=detail&ids={vod_id}"
            data = self._fetch_json(url)
            if not data or not data.get("list"):
                return result

            info = data["list"][0]
            vod = {
                "vod_id": str(info.get("vod_id", vod_id)),
                "vod_name": info.get("vod_name", ""),
                "vod_pic": info.get("vod_pic", ""),
                "vod_year": info.get("vod_year", ""),
                "vod_area": info.get("vod_area", ""),
                "vod_actor": info.get("vod_actor", ""),
                "vod_director": info.get("vod_director", ""),
                "vod_type": info.get("vod_type", ""),
                "vod_remarks": info.get("vod_remarks", ""),
                "vod_content": info.get("vod_content", ""),
            }

            # ----- 解析播放线路 -----
            # 苹果CMS标准返回字段：vod_play_from 和 vod_play_url
            play_from = info.get("vod_play_from", "")
            play_url = info.get("vod_play_url", "")

            # 如果接口返回的是 $$ 分隔的线路，需要转换为 $$$ 分隔
            if play_from and "$$" in play_from and "$$$" not in play_from:
                play_from = play_from.replace("$$", "$$$")

            if play_url and "$$" in play_url and "$$$" not in play_url:
                play_url = play_url.replace("$$", "$$$")

            vod["vod_play_from"] = play_from
            vod["vod_play_url"] = play_url
            result.append(vod)

        except Exception as e:
            print(f"[{self.name}] 详情获取异常: {e}")
        return result

    def searchContent(self, key, pg, filter=False):
        """关键词搜索"""
        result = {
            "list": [],
            "page": int(pg),
            "pagecount": 0,
            "limit": self.page_size,
            "total": 0
        }
        if not key:
            return result

        try:
            # 苹果CMS搜索接口，关键词需URL编码
            # 如实际接口不同，请修改此URL
            encoded_key = urllib.parse.quote(key)
            url = f"{self.base_url}/api.php/provide/vod/?ac=detail&wd={encoded_key}&pg={pg}"
            data = self._fetch_json(url)
            if data and data.get("list"):
                for item in data["list"]:
                    result["list"].append(self._build_vod_item(item))
                result["pagecount"] = int(data.get("pagecount", 0))
                result["total"] = int(data.get("total", 0))
                result["limit"] = int(data.get("limit", self.page_size))
        except Exception as e:
            print(f"[{self.name}] 搜索异常: {e}")
        return result

    def playerContent(self, flag, id, vipFlags=None):
        """播放地址解析"""
        try:
            # 情况1：直链（m3u8/mp4）
            if ".m3u8" in id or ".mp4" in id or ".flv" in id:
                return {
                    "parse": 0,
                    "url": id,
                    "header": {"User-Agent": self.headers["User-Agent"]}
                }

            # 情况2：如果是相对路径，补全为绝对路径
            if id.startswith("/"):
                return {
                    "parse": 0,
                    "url": f"{self.base_url}{id}",
                    "header": {"User-Agent": self.headers["User-Agent"]}
                }

            # 情况3：兜底——交给解析器处理
            return {
                "parse": 1,
                "url": id,
                "header": {"User-Agent": self.headers["User-Agent"]}
            }

        except Exception as e:
            print(f"[{self.name}] 播放解析异常: {e}")
            return {"parse": 1, "url": id, "header": {}}
