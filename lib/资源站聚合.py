# -*- coding: utf-8 -*-
# 专属全网聚合 Python版
# 适配常见 Cat/TVBox Python Spider
#本地py适配  😂  

import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from base.spider import Spider


class Spider(Spider):
    sources = {
        's1': {'name': '无尽资源', 'api': 'https://api.wujinapi.me/api.php/provide/vod/'},
        's2': {'name': '无水印资源', 'api': 'https://api.wsyzy.net/api.php/provide/vod'},
        's3': {'name': '量子资源', 'api': 'https://cj.lziapi.com/api.php/provide/vod'},
        's4': {'name': '天堂资源', 'api': 'http://caiji.dyttzyapi.com/api.php/provide/vod'},
        's5': {'name': '猫眼资源', 'api': 'https://api.maoyanapi.top/api.php/provide/vod'},
        's6': {'name': '天涯资源', 'api': 'https://tyyszy.com/api.php/provide/vod'},
        's7': {'name': '淘片资源', 'api': 'https://taopianapi.com/cjapi/mc10/vod/json.html'},     
        's8': {'name': '闪电资源', 'api': 'http://sdzyapi.com/api.php/provide/vod/'},
        's9': {'name': '索尼资源', 'api': 'https://suoniapi.com/api.php/provide/vod'},
        's10': {'name': '红牛资源', 'api': 'https://www.hongniuzy2.com/api.php/provide/vod'},
        's11': {'name': '茅台资源', 'api': 'https://caiji.maotaizy.cc/api.php/provide/vod'},
        's12': {'name': '虎牙资源', 'api': 'https://www.huyaapi.com/api.php/provide/vod'},
        's13': {'name': '豆瓣资源', 'api': 'https://caiji.dbzy5.com/api.php/provide/vod/at/josn/'},
        's14': {'name': '天空资源', 'api': 'https://subocj.com/api.php/provide/vod/at/json'},
        's15': {'name': '豪华资源', 'api': 'https://hhzyapi.com/api.php/provide/vod'},
        's16': {'name': '快车资源', 'api': 'https://caiji.kuaichezy.org/api.php/provide/vod/?ac=list'},
        's17': {'name': '奇艺资源', 'api': 'https://iqiyizyapi.com/api.php/provide/vod'},
        's18': {'name': '如意资源', 'api': 'https://cj.rycjapi.com/api.php/provide/vod/?ac=list'},
        's19': {'name': '无尽资源', 'api': 'https://api.wujinapi.cc/api.php/provide/vod'},
        's20': {'name': '光速资源', 'api': 'https://api.guangsuapi.com/api.php/provide/vod'},
        's21': {'name': '云解析资源', 'api': 'https://api.yparse.com/api/json'},
        's22': {'name': '新浪资源', 'api': 'https://api.xinlangapi.com/xinlangapi.php/provide/vod'},
        's23': {'name': '极速资源', 'api': 'https://jszyapi.com/api.php/provide/vod/'},
        's24': {'name': '最大资源', 'api': 'https://api.zuidapi.com/api.php/provide/vod'},
        's25': {'name': '樱花资源', 'api': 'https://m3u8.apiyhzy.com/api.php/provide/vod'},
        's26': {'name': '红牛资源', 'api': 'https://api.niuniuzy.me/api.php/provide/vod'},
        's27': {'name': '百度资源', 'api': 'https://api.apibdzy.com/api.php/provide/vod'},
        's28': {'name': '速播资源', 'api': 'https://subocaiji.com/api.php/provide/vod'},
        's29': {'name': '金鹰资源', 'api': 'https://jyzyapi.com/provide/vod/'},
        's30': {'name': '闪电资源', 'api': 'https://sdzyapi.com/api.php/provide/vod'},
        's31': {'name': '非凡资源', 'api': 'https://cj.ffzyapi.com/api.php/provide/vod'},
        's32': {'name': '飘零资源', 'api': 'https://p2100.net/api.php/provide/vod'},
        's33': {'name': '360资源', 'api': 'https://360zy.com/api.php/seaxml/vod/'},
        's34': {'name': '魔都资源', 'api': 'https://www.mdzyapi.com/api.php/provide/vod'},
        's35': {'name': '影剧资源', 'api': 'https://caiji.maotaizy.cc/api.php/provide/vod/at/josn/'},      
    }
      # 需要过滤的关键词列表
    FILTER_KEYWORDS = ['伦理', '两性', '三级', '倫理', '淫', '福利']

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    def getName(self):
        return "影视+专属全网聚合"

    def init(self, extend=""):
        pass

    def fetch(self, url, timeout=8):
        try:
            r = requests.get(
                url,
                headers=self.headers,
                timeout=timeout,
                verify=False
            )
            return r.text
        except Exception:
            return ""

    def clean_item(self, item, source_key, source_name, is_detail=False):
        item = dict(item)

        if not is_detail:
            item["vod_id"] = f"{source_key}@@{item.get('vod_id', '')}"

        remarks = item.get("vod_remarks", "")
        item["vod_remarks"] = f"{source_name} | {remarks}"

        if item.get("vod_play_from"):
            froms = item["vod_play_from"].split("$$$")
            froms = [f"{source_name}-{x}" for x in froms]
            item["vod_play_from"] = "$$$".join(froms)

        item.pop("vod_down_from", None)
        item.pop("vod_down_url", None)

        return item

    def homeContent(self, filter):
        classes = []
        filters = {}

        def load_class(key, source):
            url = f"{source['api']}?ac=list"
            html = self.fetch(url, 4)

            try:
                data = json.loads(html)
            except:
                data = {}

            vals = [{"n": "全部(最新)", "v": ""}]

            for c in data.get("class", []):
                vals.append({
                    "n": c.get("type_name", ""),
                    "v": c.get("type_id", "")
                })

            return key, vals

        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = []

            for key, source in self.sources.items():
                classes.append({
                    "type_id": key,
                    "type_name": source["name"]
                })

                futures.append(executor.submit(load_class, key, source))

            for future in as_completed(futures):
                try:
                    key, vals = future.result()

                    filters[key] = [{
                        "key": "cateId",
                        "name": "分类",
                        "value": vals
                    }]
                except:
                    pass

        return {
            "class": classes,
            "filters": filters,
            "list": []
        }

    def categoryContent(self, tid, pg, filter, extend):
        if tid not in self.sources:
            return {"list": []}

        source = self.sources[tid]

        cate_id = ""
        if isinstance(extend, dict):
            cate_id = extend.get("cateId", "")

        url = f"{source['api']}?ac=detail&pg={pg}"

        if cate_id:
            url += f"&t={cate_id}"

        html = self.fetch(url)

        try:
            data = json.loads(html)
        except:
            data = {}

        result = []

        for item in data.get("list", []):
            result.append(
                self.clean_item(
                    item,
                    tid,
                    source["name"],
                    False
                )
            )

        return {
            "list": result,
            "page": data.get("page", pg),
            "pagecount": data.get("pagecount", 1),
            "limit": data.get("limit", 20),
            "total": data.get("total", len(result))
        }

    def detailContent(self, ids):
        if isinstance(ids, list):
            ids = ids[0]

        if "@@" not in ids:
            return {"list": []}

        source_key, real_id = ids.split("@@", 1)

        if source_key not in self.sources:
            return {"list": []}

        source = self.sources[source_key]

        url = f"{source['api']}?ac=detail&ids={real_id}"

        html = self.fetch(url)

        try:
            data = json.loads(html)
        except:
            data = {}

        result = []

        for item in data.get("list", []):
            cleaned = self.clean_item(
                item,
                source_key,
                source["name"],
                True
            )

            cleaned["vod_id"] = ids

            result.append(cleaned)

        return {"list": result}

    def search_one(self, source_key, source, keyword, pg):
        url = f"{source['api']}?ac=detail&wd={keyword}&pg={pg}"

        html = self.fetch(url, 6)

        try:
            data = json.loads(html)
        except:
            data = {}

        result = []

        for item in data.get("list", []):
            result.append(
                self.clean_item(
                    item,
                    source_key,
                    source["name"],
                    False
                )
            )

        return {
            "list": result,
            "pagecount": data.get("pagecount", 1)
        }

    def searchContent(self, key, quick=False, pg=1):
        result = []
        max_page = 1

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []

            for source_key, source in self.sources.items():
                futures.append(
                    executor.submit(
                        self.search_one,
                        source_key,
                        source,
                        key,
                        pg
                    )
                )

            for future in as_completed(futures):
                try:
                    data = future.result()

                    result.extend(data["list"])

                    if data["pagecount"] > max_page:
                        max_page = data["pagecount"]

                except:
                    pass

        return {
            "list": result,
            "page": pg,
            "pagecount": max_page,
            "limit": 40,
            "total": 9999
        }

    def playerContent(self, flag, id, vipFlags):
        return {
            "parse": 0,
            "playUrl": "",
            "url": id,
            "header": self.headers
        }

    def localProxy(self, param):
        return [200, "text/plain", "ok"]


if __name__ == "__main__":
    Spider().run()
