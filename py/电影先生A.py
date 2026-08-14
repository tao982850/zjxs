# coding=utf-8
"""
目标站: 思立影视 (www.silidm.com)
站点类型: 影视资源站 (MacCMS 苹果CMS)
技术栈: PHP + MacCMS

URL 结构:
    首页: /
    分类: /type/<typeId>.html (dy/juji/dongman/zongyi)
    片库: /show/<typeId>-<area>-<by>-<class>-<lang>-<letter>----<year>-<page>.html
    详情: /video/<id>.html
    播放: /play/<id>-<line>-<episode>.html
    搜索: /search/-<keyword>------------<page>.html

分类ID (API):
    20=电影, 21=剧集, 22=动漫, 23=综艺

播放线路 (API):
    bfzym3u8=BF线路 (HTML line 1)
    ffm3u8=FF线路 (HTML line 2)
    lzm3u8=LZ线路 (HTML line 3)
    kua=夸克网盘 (HTML line 4, 非视频线路, 跳过)

MacCMS API:
    列表: /api.php/provide/vod/?ac=detail&pg=<page>&t=<typeId> (ac=list 不返回 vod_pic)
    详情: /api.php/provide/vod/?ac=detail&ids=<id>
    搜索: /api.php/provide/vod/?ac=detail&wd=<keyword>&pg=<page>
    最近: /api.php/provide/vod/?ac=detail&pg=1&h=24
    筛选: &a=<area>&c=<class>&y=<year>&s=<by>

播放机制:
    API 返回 vod_play_url 中直接包含 m3u8 直链。
    格式: 第1集$url1#第2集$url2$$$第01集$url3#...
    parse=0 直接播放 m3u8。

架构:
    1. MacCMS API 优先 (JSON 解析, 稳定可靠)
    2. HTML 解析回退 (正则解析, API 失败时使用)
"""
import re
import sys
import json
import time
import base64
import ssl
import gzip
import urllib.parse
import urllib.request

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):

    def init(self, extend=""):
        self.site_url = "https://www.silidm.com"
        self.api_url = "https://www.silidm.com/api.php/provide/vod/"
        self.default_pic = ""
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'identity',
            'Connection': 'keep-alive',
        }
        self.categories = [
            {"type_id": "20", "type_name": "电影"},
            {"type_id": "21", "type_name": "剧集"},
            {"type_id": "22", "type_name": "动漫"},
            {"type_id": "23", "type_name": "综艺"},
        ]
        # 线路名称映射 (API play_from → 显示名称)
        self.line_name_map = {
            'bfzym3u8': 'BF线路',
            'ffm3u8': 'FF线路',
            'lzm3u8': 'LZ线路',
            'kua': '夸克网盘',
        }
        # HTML 线路ID → API play_from 名称 (固定映射)
        self.html_line_map = {
            '1': 'bfzym3u8',
            '2': 'ffm3u8',
            '3': 'lzm3u8',
            '4': 'kua',
        }
        # 非视频线路 (云盘类, 跳过)
        self.skip_lines = {'kua'}

    # ==================== 基础工具 ====================

    def _fetch_with_retry(self, url, max_retries=3, referer=None, min_len=200):
        """多重 fetch 回退: self.fetch → urllib.request"""
        hdrs = dict(self.headers)
        if referer:
            hdrs['Referer'] = referer
        for i in range(max_retries):
            # 方法1: self.fetch
            try:
                resp = self.fetch(url, headers=hdrs)
                if resp:
                    text = ""
                    if hasattr(resp, 'text') and resp.text:
                        text = resp.text
                    elif hasattr(resp, 'content') and resp.content:
                        c = resp.content
                        text = c.decode('utf-8', errors='ignore') if isinstance(c, bytes) else str(c)
                    elif hasattr(resp, 'read'):
                        text = resp.read().decode('utf-8', errors='ignore')
                    if text and len(text) >= min_len:
                        return text
                    if text and i == max_retries - 1 and len(text) > 50:
                        return text
            except Exception:
                pass
            # 方法2: urllib.request
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(url, headers=hdrs)
                resp2 = urllib.request.urlopen(req, timeout=15, context=ctx)
                data = resp2.read()
                if data:
                    encoding = resp2.headers.get('Content-Encoding', '')
                    if 'gzip' in encoding:
                        try:
                            data = gzip.decompress(data)
                        except Exception:
                            pass
                    text = data.decode('utf-8', errors='ignore')
                    if text and len(text) >= min_len:
                        return text
                    if text and i == max_retries - 1 and len(text) > 50:
                        return text
            except Exception:
                pass
            if i < max_retries - 1:
                time.sleep(0.3 + i * 0.3)
        return ""

    def _fetch_json(self, url, max_retries=3):
        """获取 JSON 数据"""
        text = self._fetch_with_retry(url, max_retries=max_retries, min_len=50)
        if not text:
            return None
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

    def _fix_url(self, url):
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        if not url.startswith("http"):
            return urllib.parse.urljoin(self.site_url + "/", url)
        return url

    def _fix_pic(self, url):
        """修复图片 URL — 分级代理策略

        图床分析 (240 张图片采样):
        - picbf.com (57%): 直连正常, 无需代理
        - lzipic.com (26%): 直连正常, 无需代理
        - meituan.net (8%): 直连正常, 无需代理
        - doubanio.com (2%): 防盗链(403/418), 用百度图片下载代理
        - viptulz.com: SSL 握手失败, 用 wsrv.nl 代理
        - ryzypics.com: SSL 握手失败, 用 wsrv.nl 代理
        - dytt-img.com: SSL 握手失败, 用 wsrv.nl 代理
        - lzzyimg.com: SSL 握手失败, 用 wsrv.nl 代理
        - 其他未知图床: 用 wsrv.nl 代理兜底
        - TVBox (Android 4.0+) 原生支持 WebP, 不转换格式
        """
        if not url:
            return ""
        url = self._fix_url(url)
        # 强制 https
        if url.startswith('http://'):
            url = 'https://' + url[7:]
        # 直连正常的图床 — 不处理
        # 测试结果: picbf/lzipic/meituan/283bt 直连均正常
        direct_hosts = ('picbf.com', 'lzipic.com', 'meituan.net', '283bt.com')
        if any(h in url for h in direct_hosts):
            return url
        # doubanio.com 防盗链 → 百度图片下载代理 + 时间戳避免缓存返回空
        if 'doubanio.com' in url:
            ts = int(time.time() * 1000)
            return "https://image.baidu.com/search/down?url=" + urllib.parse.quote(url, safe='') + "&t=%d" % ts
        # 其余图床 (SSL 失败等) → wsrv.nl 图片代理
        return "https://wsrv.nl/?url=" + urllib.parse.quote(url, safe='')

    # ==================== API 数据解析 ====================

    def _api_list_to_videos(self, data):
        """将 API 列表数据转换为 TVBox 视频列表"""
        if not data or 'list' not in data:
            return []
        videos = []
        for item in data['list']:
            vid = str(item.get('vod_id', ''))
            if not vid:
                continue
            name = item.get('vod_name', '').strip()
            if not name:
                continue
            pic = self._fix_pic(item.get('vod_pic', ''))
            remark = item.get('vod_remarks', '')
            videos.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": remark
            })
        return videos

    def _api_detail_to_result(self, data, vod_id):
        """将 API 详情数据转换为 TVBox 详情结果"""
        if not data or 'list' not in data or not data['list']:
            return None
        item = data['list'][0]

        vod_name = item.get('vod_name', '')
        vod_pic = self._fix_pic(item.get('vod_pic', ''))
        vod_content = item.get('vod_content', '') or item.get('vod_blurb', '')
        vod_actor = item.get('vod_actor', '')
        vod_director = item.get('vod_director', '')
        vod_area = item.get('vod_area', '')
        vod_year = item.get('vod_year', '')
        vod_class = item.get('vod_class', '')
        vod_remarks = item.get('vod_remarks', '')

        # 解析播放线路
        play_from = item.get('vod_play_from', '')
        play_url = item.get('vod_play_url', '')

        play_from_list = []
        play_url_list = []

        if play_from and play_url:
            line_names = play_from.split('$$$')
            line_urls = play_url.split('$$$')

            for i, (lf, lu) in enumerate(zip(line_names, line_urls)):
                if not lu:
                    continue
                lf = lf.strip()
                # 跳过非视频线路 (夸克网盘等)
                if lf in self.skip_lines:
                    continue
                # 映射线路名称
                display_name = self.line_name_map.get(lf, lf or "线路%d" % (i + 1))

                eps = lu.split('#')
                ep_strs = []
                for ep in eps:
                    ep = ep.strip()
                    if not ep:
                        continue
                    if '$' in ep:
                        parts = ep.split('$', 1)
                        ep_name = parts[0].strip()
                        ep_url = parts[1].strip()
                        if ep_url and ep_name:
                            # 直接用 m3u8 URL 作为 play_id
                            ep_strs.append("%s$%s" % (ep_name, ep_url))
                    else:
                        # 没有 $ 分隔，可能是纯 URL
                        if ep.startswith('http'):
                            ep_strs.append("第%d集$%s" % (len(ep_strs) + 1, ep))

                if ep_strs:
                    play_from_list.append(display_name)
                    play_url_list.append("#".join(ep_strs))

        if not play_url_list:
            play_from_list.append("默认线路")
            play_url_list.append("暂无播放")

        vod_play_from = "$$$".join(play_from_list)
        vod_play_url = "$$$".join(play_url_list)

        return {
            "vod_id": str(vod_id),
            "vod_name": vod_name,
            "vod_pic": vod_pic,
            "vod_content": vod_content[:500] if vod_content else "",
            "vod_actor": vod_actor,
            "vod_director": vod_director,
            "vod_area": vod_area,
            "vod_year": vod_year,
            "vod_class": vod_class,
            "vod_remarks": vod_remarks,
            "vod_play_from": vod_play_from,
            "vod_play_url": vod_play_url
        }

    # ==================== HTML 解析回退 ====================

    def _parse_video_list_html(self, html):
        """正则解析视频列表 (HTML 回退)"""
        if not html:
            return []
        video_list = []
        seen = set()
        remark_re = r'(第\d+集|已完结|全集|全\d+集|HD\S*|正片|抢先版|更新到\d+|更新至\d+|更新至HD|完结|高清|HD国语\S*|HD中字\S*|TC\S*|内详)'

        for m in re.finditer(r'href="[^"]*/video/(\d+)\.html"', html):
            vid = m.group(1)
            if vid in seen:
                continue

            a_start = html.rfind('<a ', 0, m.start())
            if a_start < 0:
                a_start = html.rfind('<a\t', 0, m.start())
            if a_start < 0:
                a_start = html.rfind('<a\n', 0, m.start())
            if a_start < 0:
                continue

            a_end = html.find('</a>', m.end())
            if a_end < 0:
                a_end = html.find('</a>', m.start())
            if a_end < 0:
                continue

            a_full = html[a_start:a_end + 4]
            tag_end_pos = a_full.find('>')
            if tag_end_pos < 0:
                continue

            attrs_str = a_full[3:tag_end_pos]
            content = a_full[tag_end_pos + 1:-4]

            # 跳过图片包装链接
            if '<img' in content:
                continue

            title = ""
            title_m = re.search(r'title="([^"]*)"', attrs_str)
            if title_m:
                title = title_m.group(1).strip()
            if not title:
                title = re.sub(r'<[^>]+>', '', content).strip()
            if not title or len(title) < 1:
                continue
            if title in ('首页', '电影', '剧集', '动漫', '综艺', '推荐', '更多电影',
                         '更多剧集', '更多动漫', '更多综艺', '全部', '尾页', '更多',
                         '全部电影', '全部剧集', '全部动漫', '全部综艺'):
                continue
            # 跳过搜索链接
            if '/search/' in attrs_str:
                continue

            seen.add(vid)

            # 向前找图片
            pic = ""
            before = html[max(0, a_start - 1000):a_start]
            img_matches = list(re.finditer(r'<img\s([^>]*)>', before))
            if img_matches:
                img_attrs = img_matches[-1].group(1)
                for attr in ['data-src', 'data-original', 'src']:
                    src_m = re.search(attr + r'="([^"]*)"', img_attrs)
                    if src_m:
                        url = src_m.group(1)
                        if url and 'base64' not in url and 'load.gif' not in url and 'load.png' not in url:
                            pic = self._fix_pic(url)
                            break

            # 向后找备注
            remark = ""
            after = html[a_end + 4:a_end + 504]
            remark_m = re.search(remark_re, after)
            if remark_m:
                remark = remark_m.group(1)

            video_list.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remark
            })
            if len(video_list) >= 30:
                break

        return video_list

    def _parse_detail_html(self, html, vod_id):
        """正则解析详情页 (HTML 回退)"""
        if not html:
            return None

        # 标题
        vod_name = ""
        title_m = re.search(r'<title>([^<]*)</title>', html)
        if title_m:
            t = title_m.group(1)
            m = re.search(r'《([^》]+)》', t)
            if m:
                vod_name = m.group(1)
            else:
                vod_name = t.split('-')[0].split('_')[0].strip()
        if not vod_name:
            h1_m = re.search(r'<h1[^>]*>([^<]*)</h1>', html)
            if h1_m:
                vod_name = h1_m.group(1).strip()
        if not vod_name:
            og_m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html)
            if og_m:
                vod_name = og_m.group(1).strip()

        # 图片
        vod_pic = ""
        og_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]*)"', html)
        if og_m:
            vod_pic = og_m.group(1)
        if not vod_pic:
            img_m = re.search(r'<img[^>]*src="([^"]*doubaocdn[^"]*)"', html)
            if img_m:
                vod_pic = img_m.group(1)
        vod_pic = self._fix_pic(vod_pic)

        # 元数据
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)

        vod_director = ""
        m = re.search(r'导演[：:]\s*(.+?)(?:\s*主演|\s*上映)', text)
        if m:
            vod_director = m.group(1).strip().rstrip('/').strip()
        vod_actor = ""
        m = re.search(r'主演[：:]\s*(.+?)(?:\s*上映|\s*备注)', text)
        if m:
            vod_actor = m.group(1).strip().rstrip('/').strip()
        vod_year = ""
        m = re.search(r'上映[：:]\s*(\d{4})', text)
        if m:
            vod_year = m.group(1)
        vod_area = ""
        m = re.search(r'(?:地区|区域)[：:]\s*(.+?)(?:\s*类型|\s*上映|\s*备注|\s*剧情)', text)
        if m:
            vod_area = m.group(1).strip()
        vod_content = ""
        m = re.search(r'剧情[：:]\s*(.+?)(?:\s*展开|\s*相关|\n|$)', text)
        if m:
            vod_content = m.group(1).strip()[:300]
        vod_remarks = ""
        m = re.search(r'备注[：:]\s*(.+?)(?:\s*剧情|\s*相关|\s*展开|\s*收起|$)', text)
        if m:
            vod_remarks = m.group(1).strip()

        # 播放线路 — 从 HTML 提取线路名称
        play_from_list = []
        play_url_list = []

        # 找所有播放链接 /play/<id>-<line>-<ep>.html
        lines = {}
        line_order = []

        for m in re.finditer(r'href="[^"]*/play/%s-(\d+)-(\d+)\.html"' % vod_id, html):
            line_id = m.group(1)
            ep_num = int(m.group(2))

            a_start = html.rfind('<a ', 0, m.start())
            if a_start < 0:
                continue
            a_end = html.find('</a>', m.end())
            if a_end < 0:
                continue
            a_full = html[a_start:a_end + 4]
            tag_end_pos = a_full.find('>')
            if tag_end_pos < 0:
                continue
            content = a_full[tag_end_pos + 1:-4]
            ep_name = re.sub(r'<[^>]+>', '', content).strip() or ("第%d集" % ep_num)

            if '立即' in ep_name or '选集' in ep_name:
                continue

            if line_id not in lines:
                lines[line_id] = {'eps': []}
                line_order.append(line_id)

            existing = [e[0] for e in lines[line_id]['eps']]
            if ep_num not in existing:
                lines[line_id]['eps'].append((ep_num, ep_name))

        # 从 HTML 提取线路名称 (BF线路, LZ线路, FF线路, 夸克网盘 等)
        html_line_names = {}
        for m in re.finditer(r'(BF线路|LZ线路|FF线路|夸克网盘|默认线路|线路\d+)', html):
            # 找到线路名称后，找最近的 play 链接确定 line_id
            after_text = html[m.end():m.end() + 500]
            play_m = re.search(r'/play/%s-(\d+)-\d+\.html' % vod_id, after_text)
            if play_m:
                lid = play_m.group(1)
                if lid not in html_line_names:
                    html_line_names[lid] = m.group(1)

        for lid in line_order:
            # 跳过非视频线路 (通过 HTML 名称或 API 映射判断)
            html_name = html_line_names.get(lid, '')
            api_name = self.html_line_map.get(lid, '')
            if html_name == '夸克网盘' or api_name in self.skip_lines:
                continue
            # 优先用 HTML 提取的名称，其次用映射
            name = html_name or self.line_name_map.get(api_name, "线路%s" % lid)
            eps = sorted(lines[lid]['eps'], key=lambda x: x[0])
            ep_strs = []
            for ep_num, ep_name in eps:
                ep_strs.append("%s$%s:%s:%d" % (ep_name, vod_id, lid, ep_num))
            if ep_strs:
                play_from_list.append(name)
                play_url_list.append("#".join(ep_strs))

        if not play_url_list:
            play_from_list.append("默认线路")
            play_url_list.append("暂无播放$%s:1:1" % vod_id)

        return {
            "vod_id": str(vod_id),
            "vod_name": vod_name,
            "vod_pic": vod_pic,
            "vod_content": vod_content,
            "vod_actor": vod_actor,
            "vod_director": vod_director,
            "vod_area": vod_area,
            "vod_year": vod_year,
            "vod_class": "",
            "vod_remarks": vod_remarks,
            "vod_play_from": "$$$".join(play_from_list),
            "vod_play_url": "$$$".join(play_url_list)
        }

    # ==================== TVBox 接口 ====================

    def homeContent(self, filter):
        # 优先用 API 获取最近更新 (24小时内, 全分类)
        # 注意: ac=list 不返回 vod_pic, 必须用 ac=detail
        video_list = []
        data = self._fetch_json("%s?ac=detail&pg=1&h=24" % self.api_url)
        if data and data.get('list'):
            video_list = self._api_list_to_videos(data)

        # API 失败则用 HTML 解析
        if not video_list:
            html = self._fetch_with_retry(self.site_url + "/", min_len=500)
            if html:
                video_list = self._parse_video_list_html(html)

        # 筛选器
        filters = {}
        for tid in ['20', '21', '22', '23']:
            filters[tid] = [
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
                    {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"}, {"n": "日本", "v": "日本"},
                    {"n": "韩国", "v": "韩国"}, {"n": "英国", "v": "英国"}, {"n": "法国", "v": "法国"},
                    {"n": "德国", "v": "德国"}, {"n": "泰国", "v": "泰国"}, {"n": "印度", "v": "印度"},
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"},
                    {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"},
                ]},
                {"key": "by", "name": "排序", "value": [
                    {"n": "更新时间", "v": "time"}, {"n": "人气", "v": "hits"}, {"n": "评分", "v": "score"},
                ]},
            ]

        return {"class": self.categories, "list": video_list, "filters": filters}

    def homeVideoContent(self):
        data = self._fetch_json("%s?ac=detail&pg=1&h=24" % self.api_url)
        video_list = self._api_list_to_videos(data) if data else []
        if not video_list:
            html = self._fetch_with_retry(self.site_url + "/", min_len=500)
            if html:
                video_list = self._parse_video_list_html(html)
        return {"list": video_list}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1

        # 优先用 API (ac=detail, ac=list 不返回 vod_pic)
        params = "ac=detail&pg=%d&t=%s" % (page, tid)
        if extend:
            area = extend.get('area', '')
            by = extend.get('by', '')
            year = extend.get('year', '')
            if area:
                params += "&a=%s" % urllib.parse.quote(area)
            if by:
                params += "&s=%s" % by
            if year:
                params += "&y=%s" % year

        url = "%s?%s" % (self.api_url, params)
        data = self._fetch_json(url)
        video_list = []
        pagecount = page

        if data and data.get('list'):
            video_list = self._api_list_to_videos(data)
            pagecount = int(data.get('pagecount', 0)) or page

        # API 失败用 HTML 回退
        if not video_list:
            type_map = {'20': 'dy', '21': 'juji', '22': 'dongman', '23': 'zongyi'}
            type_str = type_map.get(tid, 'dy')
            area = extend.get('area', '') if extend else ''
            by = extend.get('by', '') if extend else ''
            year = extend.get('year', '') if extend else ''

            area_q = urllib.parse.quote(area) if area else ''
            by_q = by if by else ''
            year_q = year if year else ''

            html_url = "%s/show/%s-%s-%s--------%s-%d.html" % (
                self.site_url, type_str, area_q, by_q, year_q, page
            )
            html = self._fetch_with_retry(html_url, min_len=500)
            if html:
                video_list = self._parse_video_list_html(html)
                # 解析分页
                for m in re.finditer(r'/show/\w+-.*-(\d+)\.html', html):
                    pagecount = max(pagecount, int(m.group(1)))

        return {
            "list": video_list,
            "page": page,
            "pagecount": pagecount if pagecount > page else page + 1,
            "limit": 30,
            "total": len(video_list) * pagecount if video_list else 0
        }

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = ids[0]

        # 优先用 API (ac=detail 获取完整数据含播放线路)
        url = "%s?ac=detail&ids=%s" % (self.api_url, vod_id)
        data = self._fetch_json(url)
        if data and data.get('list'):
            result = self._api_detail_to_result(data, vod_id)
            if result:
                return {"list": [result]}

        # API 失败用 HTML 回退
        html_url = "%s/video/%s.html" % (self.site_url, vod_id)
        html = self._fetch_with_retry(html_url, min_len=500)
        if html:
            result = self._parse_detail_html(html, vod_id)
            if result:
                return {"list": [result]}

        return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1

        # 优先用 API (ac=detail, ac=list 不返回 vod_pic)
        url = "%s?ac=detail&wd=%s&pg=%d" % (self.api_url, urllib.parse.quote(key), page)
        data = self._fetch_json(url)
        if data and data.get('list'):
            video_list = self._api_list_to_videos(data)
            pagecount = int(data.get('pagecount', 1)) or 1
            return {"list": video_list, "page": page, "pagecount": pagecount}

        # HTML 回退
        html_url = "%s/search/-%s------------%d.html" % (
            self.site_url, urllib.parse.quote(key), page
        )
        html = self._fetch_with_retry(html_url, min_len=200)
        video_list = self._parse_video_list_html(html) if html else []
        return {"list": video_list, "page": page, "pagecount": 1}

    # ==================== 播放器 ====================

    def playerContent(self, flag, id, vipFlags):
        """
        播放: id 可能是直接 m3u8 URL 或 vodId:lineId:epNum 格式
        """
        # 如果 id 是直接 URL (来自 API)
        if id.startswith('http'):
            play_header = dict(self.headers)
            play_header['Referer'] = self.site_url + "/"
            if '.m3u8' in id:
                return {"parse": 0, "url": id, "header": play_header}
            return {"parse": 1, "url": id, "header": play_header}

        # 如果是 vodId:lineId:epNum 格式 (来自 HTML 回退)
        parts = id.split(":")
        if len(parts) >= 3:
            vod_id = parts[0]
            line_id = parts[1]
            ep_num = int(parts[2])

            # 用 API 获取播放 URL
            url = "%s?ac=detail&ids=%s" % (self.api_url, vod_id)
            data = self._fetch_json(url)
            if data and data.get('list'):
                item = data['list'][0]
                play_from = item.get('vod_play_from', '')
                play_url = item.get('vod_play_url', '')

                if play_from and play_url:
                    line_names = play_from.split('$$$')
                    line_urls = play_url.split('$$$')

                    # HTML line_id 是位置映射 (1=第1个线路, 2=第2个...)
                    # 也兼容固定名称映射作为回退
                    target_name = self.html_line_map.get(line_id, '')
                    line_idx = int(line_id) - 1

                    for i, (lf, lu) in enumerate(zip(line_names, line_urls)):
                        # 优先用位置匹配, 其次用名称映射
                        if i == line_idx or (target_name and lf.strip() == target_name):
                            # 跳过非视频线路
                            if lf.strip() in self.skip_lines:
                                break
                            eps = lu.split('#')
                            if ep_num <= len(eps):
                                ep = eps[ep_num - 1]
                                if '$' in ep:
                                    video_url = ep.split('$', 1)[1].strip()
                                    if video_url.startswith('http'):
                                        play_header = dict(self.headers)
                                        play_header['Referer'] = self.site_url + "/"
                                        return {"parse": 0, "url": video_url, "header": play_header}

            # HTML 回退: 获取播放页 player_aaaa
            play_url = "%s/play/%s-%s-%d.html" % (self.site_url, vod_id, line_id, ep_num)
            fb_header = dict(self.headers)
            fb_header['Referer'] = "%s/video/%s.html" % (self.site_url, vod_id)

            html = self._fetch_with_retry(play_url, max_retries=3, referer=fb_header['Referer'], min_len=500)
            if html:
                # 提取 player_aaaa
                start = html.find('player_aaaa')
                if start >= 0:
                    brace_start = html.find('{', start)
                    if brace_start >= 0:
                        depth = 0
                        in_string = False
                        escape = False
                        quote_char = None
                        for idx in range(brace_start, len(html)):
                            c = html[idx]
                            if escape:
                                escape = False
                                continue
                            if c == '\\':
                                escape = True
                                continue
                            if in_string:
                                if c == quote_char:
                                    in_string = False
                                continue
                            if c == '"' or c == "'":
                                in_string = True
                                quote_char = c
                                continue
                            if c == '{':
                                depth += 1
                            elif c == '}':
                                depth -= 1
                                if depth == 0:
                                    try:
                                        p_data = json.loads(html[brace_start:idx + 1])
                                        video_url = p_data.get("url", "")
                                        encrypt = str(p_data.get("encrypt", 0))
                                        if video_url:
                                            if encrypt == '1':
                                                video_url = urllib.parse.unquote(video_url)
                                            elif encrypt == '2':
                                                decoded = base64.b64decode(video_url).decode('utf-8')
                                                video_url = urllib.parse.unquote(decoded)
                                            if video_url.startswith('http'):
                                                play_header = dict(self.headers)
                                                play_header['Referer'] = self.site_url + "/"
                                                if '.m3u8' in video_url:
                                                    return {"parse": 0, "url": video_url, "header": play_header}
                                                return {"parse": 1, "url": video_url, "header": play_header}
                                    except (json.JSONDecodeError, ValueError):
                                        pass
                                    break

            return {"parse": 1, "url": play_url, "header": fb_header}

        # 未知格式
        return {"parse": 1, "url": id, "header": dict(self.headers)}

    def isVideoFormat(self, url):
        if not url:
            return False
        url_lower = url.lower()
        return any(ext in url_lower for ext in ['.m3u8', '.mp4', '.flv', '.mkv', '.avi'])

    def manualVideoSniff(self, url, headers=None):
        return None
