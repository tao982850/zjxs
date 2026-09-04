#coding=utf-8
# TVBox Python Spider - 旺旺影视
# 站点: https://vip.wwgz.cn:5200
# 架构: MacCMS (苹果CMS), HTML 解析模式

import re
import json
import urllib.parse

try:
    from base.spider import Spider
except:
    Spider = object

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except:
    requests = None


class Spider(Spider):

    def __init__(self):
        pass

    def init(self, cfg=""):
        self.siteUrl = "https://vip.wwgz.cn:5200"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
            "Referer": self.siteUrl + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        # 初始化会话 (部分页面需要先访问首页建立会话)
        if requests:
            self._session = requests.Session()
            self._session.headers.update(self.headers)
            try:
                self._session.get(self.siteUrl + "/index.html", verify=False, timeout=10)
            except:
                pass

    def getName(self):
        return "旺旺影视"

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    # ==================== 请求封装 ====================

    def fetch(self, url, headers=None):
        """请求封装: 优先用父类(TVBox框架), 本地回退到 requests"""
        try:
            return super().fetch(url, headers=headers or self.headers)
        except:
            if requests:
                h = headers or self.headers
                if hasattr(self, '_session'):
                    resp = self._session.get(url, headers=h, timeout=15, verify=False)
                else:
                    resp = requests.get(url, headers=h, timeout=15, verify=False)
                resp.encoding = resp.apparent_encoding or 'utf-8'
                return type('R', (), {
                    'text': resp.text,
                    'content': resp.content,
                    'status_code': resp.status_code
                })()
            raise

    def _get(self, path):
        """请求站点页面, 返回 HTML 文本"""
        url = path if path.startswith('http') else self.siteUrl + path
        resp = self.fetch(url, headers=self.headers)
        text = resp.text if hasattr(resp, 'text') else str(resp)
        # 响应过短可能是会话过期, 重新初始化后重试一次
        if len(text) < 100 and requests:
            try:
                self._session = requests.Session()
                self._session.headers.update(self.headers)
                self._session.get(self.siteUrl + "/index.html", verify=False, timeout=10)
                resp = self._session.get(url, headers=self.headers, timeout=15, verify=False)
                resp.encoding = resp.apparent_encoding or 'utf-8'
                text = resp.text
            except:
                pass
        return text

    # ==================== Spider 接口 ====================

    def homeContent(self, filter):
        """首页分类与筛选"""
        classes = [
            {"type_id": 1, "type_name": "电影"},
            {"type_id": 2, "type_name": "连续剧"},
            {"type_id": 3, "type_name": "综艺"},
            {"type_id": 4, "type_name": "动漫"},
            {"type_id": 26, "type_name": "短剧"},
        ]
        filters = {}

        # 通用筛选: 地区、年份、排序
        area_filter = {
            "key": "area",
            "name": "地区",
            "value": [
                {"n": "全部", "v": ""},
                {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
                {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"},
                {"n": "韩国", "v": "韩国"}, {"n": "日本", "v": "日本"},
                {"n": "泰国", "v": "泰国"}, {"n": "英国", "v": "英国"},
                {"n": "法国", "v": "法国"}, {"n": "印度", "v": "印度"},
                {"n": "其它", "v": "其它"},
            ],
        }
        year_filter = {
            "key": "year",
            "name": "年份",
            "value": [
                {"n": "全部", "v": "0"},
                {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
                {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"},
                {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"},
                {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"},
                {"n": "2018", "v": "2018"}, {"n": "2017", "v": "2017"},
                {"n": "2016", "v": "2016"}, {"n": "2015", "v": "2015"},
                {"n": "2014", "v": "2014"}, {"n": "2013", "v": "2013"},
                {"n": "2012", "v": "2012"}, {"n": "2011", "v": "2011"},
                {"n": "2010", "v": "2010"}, {"n": "2009", "v": "2009"},
                {"n": "2008", "v": "2008"}, {"n": "2007", "v": "2007"},
                {"n": "2006", "v": "2006"}, {"n": "2005", "v": "2005"},
                {"n": "2004", "v": "2004"}, {"n": "2003", "v": "2003"},
                {"n": "2000", "v": "2000"},
            ],
        }
        sort_filter = {
            "key": "by",
            "name": "排序",
            "value": [
                {"n": "时间", "v": "time"},
                {"n": "人气", "v": "hits"},
                {"n": "评分", "v": "score"},
            ],
        }

        for cls in classes:
            tid = str(cls["type_id"])
            filter_list = [area_filter, year_filter, sort_filter]

            # 尝试动态获取子分类
            try:
                html = self._get(
                    f"/index.php?m=vod-list-id-{tid}-pg-1-order--by-time-class-0-year-0-letter--area--lang-.html"
                )
                # 解析子分类链接: vod-list-id-{X}-pg-1, X != tid
                raw_links = re.findall(
                    r'href="[^"]*vod-list-id-(\d+)-pg-1[^"]*"[^>]*>([^<]+)</a>', html
                )
                class_opts = [{"n": "全部", "v": "0"}]
                seen = {"0", tid}
                skip_names = {"首页", "下一页", "尾页", "全部类型", "全部地区",
                              "全部年代", "时间", "人气", "评分", "全部"}
                for cid, cname in raw_links:
                    cname = cname.strip()
                    if cid not in seen and cname and cname not in skip_names:
                        # 排除年份和地区等非子分类
                        if not re.match(r'^\d{4}$', cname) and cname not in area_filter["value"][1]["n"]:
                            class_opts.append({"n": cname, "v": cid})
                            seen.add(cid)
                if len(class_opts) > 1:
                    filter_list.insert(0, {
                        "key": "class",
                        "name": "类型",
                        "value": class_opts,
                    })
            except:
                pass

            filters[tid] = filter_list

        return {"class": classes, "filters": filters}

    def homeVideoContent(self):
        """首页推荐: 获取连续剧最新"""
        html = self._get(
            "/index.php?m=vod-list-id-2-pg-1-order--by-time-class-0-year-0-letter--area--lang-.html"
        )
        videos = self._parse_list_cards(html)
        return {"list": videos}

    def categoryContent(self, tid, pg, filter, extend):
        """分类列表"""
        extend = extend or {}
        pg = str(pg)

        # 如果选择了子分类, 用子分类 ID 作为 list-id
        cls = extend.get("class", "0")
        list_id = cls if cls and cls != "0" else tid

        area = extend.get("area", "")
        year = extend.get("year", "0")
        by = extend.get("by", "time")

        path = (
            f"/index.php?m=vod-list-id-{list_id}-pg-{pg}"
            f"-order--by-{by}-class-0-year-{year}-letter--area-{urllib.parse.quote(area)}-lang-.html"
        )
        html = self._get(path)
        videos = self._parse_list_cards(html)

        # 解析总页数
        page_count = 1
        pages = re.findall(r'vod-list-id-\d+-pg-(\d+)-', html)
        if pages:
            page_count = max(int(p) for p in pages)

        return {
            "list": videos,
            "page": int(pg),
            "pagecount": page_count,
            "limit": 30,
            "total": 0,
        }

    def searchContent(self, key, quick):
        """搜索"""
        path = f"/vod-search-pg-1-wd-{urllib.parse.quote(key)}.html"
        html = self._get(path)

        videos = []
        # 搜索结果结构:
        # <li><div class="pic"><a href="/vod-detail-id-XXX.html"><img data-src="URL" src="URL"><span class="sStyle">类型</span></a></div>
        #     <div class="txt"><span class="sTit">名称</span>...</div></li>
        items = re.findall(
            r'<a href="(/vod-detail-id-\d+\.html)"[^>]*>\s*<img[^>]*?(?:data-src|src)="([^"]+)"[^>]*>.*?<span class="sStyle">([^<]*)</span>.*?<span class="sTit">([^<]*)</span>',
            html, re.S
        )
        for href, img, vod_class, name in items:
            vid = re.search(r'\d+', href).group()
            videos.append({
                "vod_id": vid,
                "vod_name": name.strip(),
                "vod_pic": img,
                "vod_remarks": vod_class.strip(),
            })
        return {"list": videos, "page": 1}

    def detailContent(self, ids):
        """视频详情"""
        vod_id = ids[0] if isinstance(ids, list) else ids
        html = self._get(f"/vod-detail-id-{vod_id}.html")

        # 标题
        name = re.search(r'<h1 class="title">.*?<a[^>]*>([^<]*)</a>', html, re.S)
        name = name.group(1).strip() if name else ""

        # 图片
        pic = re.search(r'<section class="page-hd">.*?<img src="([^"]+)"', html, re.S)
        pic = pic.group(1) if pic else ""

        # 信息字段
        actor = self._extract_field(html, "主演")
        director = self._extract_field(html, "导演")
        year = self._extract_field(html, "年代")
        state = self._extract_field(html, "状态")

        # 简介
        content = re.search(r'<article class="detail-con">.*?<p>(.*?)</p>', html, re.S)
        if content:
            content = re.sub(r'<[^>]+>', '', content.group(1))
            content = content.replace('&nbsp;', ' ')
            content = re.sub(r'\s+', ' ', content).strip()
            content = re.sub(r'^简\s*介[：:]\s*', '', content)
        else:
            content = ""

        # 播放源
        play_from = []
        play_url = []

        # 解析 tab 标签 (线路①, 线路②, ...)
        tab_labels = []
        tab_match = re.search(r'<div class="hd">\s*<ul>(.*?)</ul>', html, re.S)
        if tab_match:
            tab_labels = re.findall(r'<a[^>]*>([^<]+)</a>', tab_match.group(1))

        # 解析播放列表 (每个源一个 numList div)
        play_lists = re.findall(
            r'<div id="([^"]+)" class="numList">\s*<ul>(.*?)</ul>\s*</div>', html, re.S
        )
        for i, (source_id, list_html) in enumerate(play_lists):
            source_name = tab_labels[i] if i < len(tab_labels) else source_id
            play_from.append(source_name)

            # 解析集数
            episodes = re.findall(
                r'href="(/vod-play-id-\d+-src-\d+-num-\d+\.html)"[^>]*>([^<]*)</a>', list_html
            )
            # 按 num 排序 (HTML 中是倒序的)
            def _ep_num(ep):
                m = re.search(r'num-(\d+)', ep[0])
                return int(m.group(1)) if m else 0
            episodes.sort(key=_ep_num)

            ep_list = [f"{ep_name}${ep_href}" for ep_href, ep_name in episodes]
            play_url.append("#".join(ep_list))

        vod_info = {
            "vod_id": vod_id,
            "vod_name": name,
            "vod_pic": pic,
            "vod_year": year,
            "vod_actor": actor,
            "vod_director": director,
            "vod_remarks": state,
            "vod_content": content,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }
        return {"list": [vod_info]}

    def playerContent(self, flag, id, vipFlags):
        """播放地址: 从播放页提取 mac_url"""
        html = self._get(id)

        # 提取 mac_url
        mac_url_match = re.search(r"mac_url\s*=\s*'([^']*)'", html)
        if not mac_url_match:
            return {"jx": 0, "parse": 0, "url": "", "header": ""}

        mac_url = mac_url_match.group(1)

        # 从 id 中提取 src 和 num
        src_match = re.search(r'src-(\d+)', id)
        num_match = re.search(r'num-(\d+)', id)
        src_idx = int(src_match.group(1)) - 1 if src_match else 0  # 转为 0-based
        ep_idx = int(num_match.group(1)) - 1 if num_match else 0   # 转为 0-based

        # 分割播放源 ($$$) 和集数 (#)
        play_url = ""
        sources = mac_url.split('$$$')
        if src_idx < len(sources):
            episodes = sources[src_idx].split('#')
            if ep_idx < len(episodes):
                parts = episodes[ep_idx].split('$')
                play_url = parts[1] if len(parts) >= 2 else parts[0]

        play_header = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
            "Referer": self.siteUrl + "/",
        }

        return {
            "jx": 0,
            "parse": 0,
            "url": play_url,
            "header": play_header,
        }

    # ==================== 辅助方法 ====================

    def _parse_list_cards(self, html):
        """解析分类列表页的视频卡片"""
        videos = []
        # 卡片结构:
        # <li><a href="/vod-detail-id-XXX.html" title="名称">
        #   <div class="pic"><img src="URL" data-echo="URL">
        #     <span class="sBg"></span>
        #     <span class="sBottom"><span>备注<em>评分</em></span></span>
        #     <span class="covericon">热播中</span>
        #   </div>
        #   <span class="sTit">名称</span>
        #   <span class="sDes">主演：XXX</span>
        # </a></li>
        cards = re.findall(
            r'<li><a\s+href="(/vod-detail-id-\d+\.html)"\s+title="([^"]*)"(.*?)</a></li>',
            html, re.S
        )
        for href, title, body in cards:
            # 图片 (优先 src, 回退 data-echo)
            img = re.search(r'<img[^>]*\bsrc="([^"]+)"', body)
            if not img:
                img = re.search(r'data-echo="([^"]+)"', body)

            # 备注 (更新状态 / 评分)
            remark = re.search(r'<span class="sBottom"><span>([^<]*)<em>([^<]*)</em>', body)
            if remark and remark.group(1).strip():
                remark = remark.group(1).strip()
            elif remark and remark.group(2).strip() and float(remark.group(2)) > 0:
                remark = "评分:" + remark.group(2).strip()
            else:
                ci = re.search(r'<span class="covericon">([^<]+)</span>', body)
                remark = ci.group(1).strip() if ci else ""

            vid = re.search(r'\d+', href).group()
            videos.append({
                "vod_id": vid,
                "vod_name": title.strip(),
                "vod_pic": img.group(1) if img else "",
                "vod_remarks": remark,
            })
        return videos

    def _extract_field(self, html, field_name):
        """从详情页 desc_item 提取字段值"""
        pattern = (
            r'<div class="desc_item">\s*<span>'
            + field_name + r'[：:]&nbsp;</span>(.*?)</div>'
        )
        match = re.search(pattern, html, re.S)
        if match:
            value = re.sub(r'<[^>]+>', ' ', match.group(1))
            value = value.replace('&nbsp;', ' ')
            value = re.sub(r'\s+', ' ', value).strip()
            return value
        return ""

    def localProxy(self, param):
        return [200, "text/plain", "", {}]


if __name__ == "__main__":
    """本地测试"""
    spider = Spider()
    spider.init()

    print("=== homeContent ===")
    try:
        result = spider.homeContent(True)
        print(f"  分类: {[c['type_name'] for c in result['class']]}")
        filters = result.get("filters", {})
        for k, v in list(filters.items())[:2]:
            print(f"  filter[{k}]: {[f['name'] for f in v]}")
    except Exception as e:
        import traceback; traceback.print_exc()

    print("\n=== homeVideoContent ===")
    try:
        result = spider.homeVideoContent()
        lst = result.get("list", [])
        print(f"  返回 {len(lst)} 条")
        if lst:
            print(f"  示例: {lst[0]}")
    except Exception as e:
        import traceback; traceback.print_exc()

    print("\n=== categoryContent (电影 第1页) ===")
    try:
        result = spider.categoryContent("1", "1", True, {})
        lst = result.get("list", [])
        print(f"  返回 {len(lst)} 条, pagecount={result.get('pagecount')}")
        if lst:
            print(f"  示例: {lst[0]}")
    except Exception as e:
        import traceback; traceback.print_exc()

    print("\n=== searchContent (庆余年) ===")
    try:
        result = spider.searchContent("庆余年", False)
        lst = result.get("list", [])
        print(f"  返回 {len(lst)} 条")
        for item in lst[:3]:
            print(f"  {item['vod_name']} -> {item['vod_id']}")
    except Exception as e:
        import traceback; traceback.print_exc()

    print("\n=== detailContent (连续剧) ===")
    try:
        cat = spider.categoryContent("2", "1", True, {})
        if cat["list"]:
            vid = cat["list"][0]["vod_id"]
            print(f"  vod_id: {vid}")
            result = spider.detailContent([vid])
            vod = result["list"][0]
            print(f"  名称: {vod['vod_name']}")
            print(f"  年份: {vod.get('vod_year')}")
            print(f"  演员: {vod.get('vod_actor', '')[:60]}")
            print(f"  导演: {vod.get('vod_director')}")
            print(f"  简介: {vod.get('vod_content', '')[:80]}")
            play_from = vod.get("vod_play_from", "")
            play_url = vod.get("vod_play_url", "")
            sources = play_from.split("$$$")
            print(f"  播放源: {sources}")
            for i, src in enumerate(sources):
                eps = play_url.split("$$$")[i].split("#") if i < len(play_url.split("$$$")) else []
                print(f"    {src}: {len(eps)} 集")
                if eps:
                    print(f"    第1集: {eps[0][:80]}")
    except Exception as e:
        import traceback; traceback.print_exc()

    print("\n=== playerContent ===")
    try:
        cat = spider.categoryContent("2", "1", True, {})
        if cat["list"]:
            vid = cat["list"][0]["vod_id"]
            detail = spider.detailContent([vid])
            play_url = detail["list"][0]["vod_play_url"]
            first_src = play_url.split("$$$")[0]
            first_ep = first_src.split("#")[0]
            play_id = first_ep.split("$")[1]
            print(f"  play_id: {play_id}")
            result = spider.playerContent("线路①", play_id, [])
            print(f"  url: {result.get('url', '')[:120]}")
            print(f"  jx: {result.get('jx')}, parse: {result.get('parse')}")
    except Exception as e:
        import traceback; traceback.print_exc()
