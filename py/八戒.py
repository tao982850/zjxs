# -*- coding: utf-8 -*-
"""
八戒影视 Spider（hipy / CatVod 类爬虫框架适配）
本资源来源于互联网公开渠道，仅可用于个人学习爬虫技术。
严禁将其用于任何商业用途，下载后请于 24 小时内删除，
搜索结果均来自源站，作者不承担任何责任。

使用方式：
  - 作为 CatVod / hipy 爬虫模块：由框架加载 Spider 类并调用其接口。
  - 独立运行（python bajie_spider.py）：仅执行 init() 自测，验证能否
    成功拉取 domainPath、获取 visitorInfo 的 userId/token。
"""

import sys
import json
import urllib3
import concurrent.futures
from urllib.parse import quote

try:
    import requests  # 独立运行时用 requests 实现 fetch/post
except Exception:  # pragma: no cover
    requests = None

# hipy / CatVod 框架中由 base.spider 提供 Spider 基类；
# 独立运行时 base 包可能不存在，做兼容处理。
try:
    from base.spider import Spider as _BaseSpider
except Exception:  # pragma: no cover
    class _BaseSpider:  # 占位基类，仅用于独立运行自测
        pass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.path.append("..")


def _req(self, method, url, **kw):
    """独立运行时的 requests 兜底实现，框架加载时会提供原生 fetch/post。"""
    if requests is None:
        raise RuntimeError("requests 未安装，且当前不在 hipy/CatVod 框架中运行")
    resp = requests.request(method, url, verify=False, timeout=15, **kw)
    class _R:
        pass
    r = _R()
    r.status_code = resp.status_code
    r.text = resp.text
    r.content = resp.content
    r._resp = resp
    def json():
        return resp.json()
    r.json = json
    return r

def _fetch(self, url, **kw):
    return _req(self, "GET", url, **kw)

def _post(self, url, data=None, **kw):
    headers = kw.pop("headers", None)
    return _req(self, "POST", url, data=data, headers=headers, **kw)


class Spider(_BaseSpider):
    host, userid, episode_list = "", "", []

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        # 框架会注入 fetch/post；独立运行时绑定 requests 兜底实现
        if not hasattr(self, "fetch"):
            self.fetch = _fetch.__get__(self)
        if not hasattr(self, "post"):
            self.post = _post.__get__(self)

    headers = {
        "User-Agent": "okhttp/4.12.0",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json;charset=UTF-8",
        "Cache-Control": "no-cache",
        "token": "",
        "deviceId": "",
        "client": "app",
        "deviceType": "Android",
    }

    # ---------- 框架接口 ----------
    def init(self, extend=""):
        self.headers["deviceId"] = "2d590b9842d064a1"
        # 拉取域名路径配置（支持通过 BAJIE_HOST 环境变量手动指定，跳过远程配置）
        import os
        cfg_host = os.environ.get("BAJIE_HOST", "").strip()
        if cfg_host:
            self.host = cfg_host
        else:
            resp = self.fetch(
                "http://osstexll.oss-rg-china-mainland.aliyuncs.com/domainPath.json",
                headers={
                    "User-Agent": "okhttp/4.12.0",
                    "Connection": "Keep-Alive",
                    "Accept-Encoding": "gzip",
                },
            )
            j = resp.json()
            if isinstance(j, dict) and j.get("status") in (403, 401, 400):
                raise RuntimeError(
                    "domainPath.json 被源站拒绝访问(status=%s)：%s。 "
                    "可在可访问该地址的网络环境下运行，或通过环境变量 "
                    "BAJIE_HOST=http://xxx 手动指定 host 后重试。"
                    % (j.get("status"), j.get("detail") or j.get("title"))
                )
            urls = j.get("url") if isinstance(j, dict) else None
            if not urls:
                raise RuntimeError("domainPath.json 返回结构异常，未找到 url 字段：" + str(j)[:200])
            self.host = urls[0]
        # 获取游客用户信息（userId / token）
        resp = self.fetch(f"{self.host}/api/v1/app/user/visitorInfo", headers=self.headers)
        data = resp.json()["data"]
        self.userid = data["id"]
        self.headers["token"] = data["token"]

    def homeContent(self, filter):
        resp = self.post(f"{self.host}/api/v1/app/screen/screenType", headers=self.headers)
        data = resp.json()["data"]
        classes = [{"type_id": i["id"], "type_name": i["name"]} for i in data]
        return {"class": classes}

    def homeVideoContent(self):
        resp = self.post(f"{self.host}/api/v1/app/recommend/recommendList", headers=self.headers)
        data = resp.json()["data"]
        videos = []
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_id = {
                executor.submit(
                    self.post,
                    f"{self.host}/api/v1/app/recommend/recommendSubList",
                    data=json.dumps({"condition": item["id"], "pageNum": 1, "pageSize": 6}),
                    headers=self.headers,
                ): item["id"]
                for item in data
            }
            for future in concurrent.futures.as_completed(future_to_id):
                try:
                    r = future.result().json()
                    for video in r["data"]["records"]:
                        videos.append({
                            "vod_id": video["id"],
                            "vod_name": video["name"],
                            "vod_pic": video["cover"],
                        })
                except Exception as e:  # pragma: no cover
                    print(f"Request failed for item {future_to_id[future]}: {e}")
        return {"list": videos}

    def categoryContent(self, tid, pg, filter, extend):
        payload = {
            "condition": {
                "classify": "",
                "region": "",
                "sreecnTypeEnum": "NEWEST",
                "typeId": tid,
                "year": "",
            },
            "pageNum": pg,
            "pageSize": 40,
        }
        resp = self.post(
            f"{self.host}/api/v1/app/screen/screenMovie",
            data=json.dumps(payload),
            headers=self.headers,
        )
        videos = []
        for i in resp.json()["data"]["records"]:
            videos.append({
                "vod_id": i["id"],
                "vod_name": i["name"],
                "vod_pic": i["cover"],
                "vod_remarks": i["area"],
                "vod_year": i["year"],
            })
        return {"list": videos, "page": pg}

    def searchContent(self, key, quick, pg="1"):
        payload = {"condition": {"value": key}, "pageNum": pg, "pageSize": 40}
        resp = self.post(
            f"{self.host}/api/v1/app/search/searchMovie",
            data=json.dumps(payload),
            headers=self.headers,
        )
        videos = []
        for i in resp.json()["data"]["records"]:
            videos.append({
                "vod_id": i["id"],
                "vod_name": i["name"],
                "vod_pic": i["cover"],
                "vod_remarks": i["area"],
                "vod_year": i["year"],
                "vod_area": i["area"],
                "vod_content": i["desc"],
            })
        return {"list": videos, "page": pg}

    def detailContent(self, ids):
        payload = {"id": ids[0], "source": 0, "typeId": "M17", "userId": self.userid}
        resp = self.post(
            f"{self.host}/api/v1/app/play/movieDetails",
            data=json.dumps(payload),
            headers=self.headers,
        )
        data = resp.json()["data"]
        currentplayerid = data["playerId"]

        play_urls, show = [], []
        # 真实分集
        play_url = [
            f"{ep['episode']}${ids[0]}@{currentplayerid}@{ep['id']}@episode"
            for ep in data["episodeList"]
        ]
        play_urls.append("#".join(play_url))

        # 其他播放源（虚拟分集）
        for pl in data["moviePlayerList"]:
            if pl["id"] == currentplayerid or pl.get("episodeTotal") is None:
                continue
            pu = [
                f"第{k}集${k}@{pl['id']}@{ids[0]}@virtual"
                for k in range(1, pl["episodeTotal"] + 1)
            ]
            play_urls.append("#".join(pu))
            if pl["moviePlayerName"] not in show:
                show.append(pl["moviePlayerName"])
        for pl in data["moviePlayerList"]:
            if pl["id"] == currentplayerid:
                show.insert(0, pl["moviePlayerName"]) if pl["moviePlayerName"] not in show[:1] else None
                break

        # 详情补充
        resp2 = self.post(
            f"{self.host}/api/v1/app/play/movieDesc",
            data=json.dumps({"id": ids[0], "typeId": "M17"}),
            headers=self.headers,
        )
        d2 = resp2.json()["data"]

        video = {
            "vod_id": d2["id"],
            "vod_name": d2["name"],
            "vod_pic": d2["cover"],
            "vod_content": d2["introduce"],
            "vod_year": d2["year"],
            "vod_area": d2["area"],
            "vod_remarks": "",
            "vod_score": d2["score"],
            "type_name": d2["classify"],
            "vod_director": d2["director"],
            "vod_play_from": "$$$".join(show),
            "vod_play_url": "$$$".join(play_urls),
        }
        return {"list": [video]}

    def playerContent(self, flag, id, vipflags):
        param, playerid, param2, param3 = id.split("@")
        if param3 == "virtual":
            payload = {
                "episodeIndex": str(int(param) - 1),
                "id": int(param2),
                "playerId": playerid,
                "source": 0,
                "typeId": "M16",
                "userId": self.userid,
            }
        else:
            payload = {
                "episodeId": param2,
                "id": param,
                "playerId": playerid,
                "source": 0,
                "typeId": "M16",
                "userId": self.userid,
            }
        resp = self.post(
            f"{self.host}/api/v1/app/play/movieDetails",
            data=json.dumps(payload),
            headers=self.headers,
        )
        data = resp.json()["data"]
        parse_url = data["url"]
        playerid = data["playerId"]

        resp = self.fetch(
            f"{self.host}/api/v1/app/play/analysisMovieUrl"
            f"?playerUrl={quote(parse_url, safe='')}&playerId={playerid}",
            headers=self.headers,
        )
        url = resp.json()["data"]
        return {
            "jx": "0",
            "parse": "0",
            "url": url,
            "header": {
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 "
                    "Mobile/15E148 Safari/604.1"
                )
            },
        }

    # ---------- 框架预留接口 ----------
    def getName(self):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        pass


# ---------- 独立运行自测 ----------
if __name__ == "__main__":
    sp = Spider()
    try:
        sp.init()
    except Exception as e:
        print("[init] 失败：", e)
        sys.exit(1)
    print("[init] OK")
    print("  host    =", sp.host)
    print("  userid  =", sp.userid)
    print("  token   =", (sp.headers.get("token") or "")[:24], "...")
