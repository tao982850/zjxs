# -*- coding: utf-8 -*-
#QQ群：807916734
# 摩羯座影视 www.mojiez.net 采集源
# Discuz! 论坛架构 + v2_moviestyle 主题
# 已内置登录Cookie，Cookie过期时自动重新登录获取
#
# 如需更换Cookie，在采集源配置中填入extend字段（Cookie字符串）

import sys
import re
import json
import time
import random
import base64
import html as html_mod
import requests
from urllib.parse import urljoin, quote

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):

    # 内置登录Cookie
    DEFAULT_COOKIE = "替换为可用的cookie"
    def init(self, extend=""):
        self.host = "https://www.mojiez.net"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.host + '/',
        }
        # 优先使用用户配置的Cookie，其次使用内置Cookie
        if extend:
            self.cookie = extend
        else:
            self.cookie = self.DEFAULT_COOKIE

        if self.cookie:
            self.headers['Cookie'] = self.cookie

        # 防止重复登录的标志
        self._relogin_attempted = False

        self.play_headers = {
            'User-Agent': self.headers['User-Agent'],
            'Referer': self.host + '/',
        }
        if self.cookie:
            self.play_headers['Cookie'] = self.cookie

        # 一级分类（fid对应Discuz论坛版块ID）
        self.classes = [
            {"type_id": "2", "type_name": "电影"},
            {"type_id": "3", "type_name": "连续剧"},
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "5", "type_name": "综艺"},
            {"type_id": "6", "type_name": "短剧"},
        ]

        # 分类筛选配置（sortid=12 为影片分类筛选器）
        # movie_nianfen=年份, movie_diqu=地区, movie_dianying/movie_juqing=类型
        self.filter_config = {
            "2": {  # 电影
                "type_key": "movie_dianying",
                "types": [["全部", ""], ["动作", "5"], ["喜剧", "6"], ["爱情", "7"],
                          ["科幻", "8"], ["奇幻", "10"], ["恐怖", "11"], ["剧情", "12"],
                          ["战争", "13"], ["悬疑", "18"], ["惊悚", "15"], ["犯罪", "16"],
                          ["冒险", "17"], ["动画", "19"], ["灾难", "20"], ["歌舞", "21"],
                          ["同性", "22"], ["网络电影", "23"]],
            },
            "3": {  # 连续剧
                "type_key": "movie_juqing",
                "types": [["全部", ""], ["国产剧", "1"], ["港台剧", "2"], ["日韩剧", "3"],
                          ["欧美剧", "4"], ["海外剧", "5"]],
            },
            "4": {  # 动漫
                "type_key": "movie_dianying",
                "types": [["全部", ""], ["日本动漫", "8"], ["国产动漫", "9"], ["欧美动漫", "10"]],
            },
            "5": {  # 综艺
                "type_key": "movie_juqing",
                "types": [["全部", ""], ["大陆综艺", "6"], ["港台综艺", "7"], ["日韩综艺", "8"],
                          ["欧美综艺", "9"]],
            },
            "6": {  # 短剧
                "type_key": "movie_juqing",
                "types": [["全部", ""]],
            },
        }
        self.area_filter = [["全部", ""], ["大陆", "1"], ["香港", "2"], ["台湾", "3"],
                            ["日本", "4"], ["韩国", "5"], ["欧美", "7"], ["英国", "8"],
                            ["泰国", "9"], ["其它", "10"]]
        self.year_filter = [["全部", ""], ["2026", "2026"], ["2025", "2025"], ["2024", "2024"],
                            ["2023", "2023"], ["2022", "2022"], ["2021", "2021"], ["2020", "2020"],
                            ["2019", "2019"], ["2018", "2018"], ["2017", "2017"], ["2016", "2016"],
                            ["2015", "2015"]]

    def getName(self):
        return "摩羯座影视"

    # ===================== 自动登录获取Cookie =====================
    # 预注册账号列表（轮流尝试，避免单一账号被禁）
    _accounts = [
        ("testuser2026", "Test2026Pass"),
        ("crawler2026x", "Clr2026Pass"),
        ("auto2026bot", "Auto2026Bot"),
    ]

    def auto_register(self):
        """自动登录/注册获取Cookie，无需用户手动配置"""
        try:
            import urllib3
            urllib3.disable_warnings()

            session = requests.Session()
            session.headers.update({
                'User-Agent': self.headers['User-Agent'],
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9',
            })
            session.verify = False

            # 1. 尝试用预注册账号登录
            for username, password in self._accounts:
                cookie_str = self._try_login(session, username, password)
                if cookie_str:
                    return cookie_str

            # 2. 登录失败，尝试注册新账号
            cookie_str = self._try_register(session)
            if cookie_str:
                return cookie_str

            return ""
        except Exception:
            return ""

    def _try_login(self, session, username, password):
        """尝试用已有账号登录"""
        try:
            # 获取登录页
            resp = session.get(self.host + "/member.php?mod=logging&action=login", timeout=15)
            html_text = resp.text

            # 提取formhash
            fh_m = re.search(r'formhash" value="([^"]*)"', html_text)
            if not fh_m:
                return ""
            formhash = fh_m.group(1)

            # 提交登录
            data = {
                'formhash': formhash,
                'referer': self.host + '/',
                'username': username,
                'password': password,
                'cookietime': '2592000',
                'loginsubmit': 'true',
            }
            resp = session.post(self.host + "/member.php?mod=logging&action=login&loginsubmit=yes",
                                data=data, timeout=15)

            # 检查登录结果
            html_text = resp.text
            if 'succeed' not in html_text and '欢迎' not in html_text and 'succeedmessage' not in html_text:
                return ""

            # 访问首页触发完整cookie设置
            session.get(self.host + "/", timeout=15)

            # 获取cookies
            cookies = session.cookies.get_dict()
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())

            # 验证cookie有效性
            if cookie_str and 'auth' in cookie_str:
                test_resp = session.get(
                    self.host + "/forum.php?mod=forumdisplay&fid=2&filter=sortid&sortid=12&searchsort=1&page=1",
                    timeout=15)
                if 'data-tid' in test_resp.text:
                    return cookie_str

            return ""
        except Exception:
            return ""

    def _try_register(self, session):
        """尝试注册新账号"""
        try:
            # 获取注册页面
            resp = session.get(self.host + "/member.php?mod=register", timeout=15)
            html_text = resp.text

            # 提取formhash
            fh_m = re.search(r'formhash" value="([^"]*)"', html_text)
            if not fh_m:
                return ""
            formhash = fh_m.group(1)

            # 提取随机字段ID（通过placeholder识别）
            username_id = re.search(r'id="([^"]*)"[^>]*placeholder="用户名"', html_text)
            password_id = re.search(r'id="([^"]*)"[^>]*placeholder="密码"', html_text)
            confirm_id = re.search(r'id="([^"]*)"[^>]*placeholder="确认密码"', html_text)
            email_id = re.search(r'id="([^"]*)"[^>]*placeholder="Email"', html_text)

            if not all([username_id, password_id, confirm_id, email_id]):
                return ""

            uid = username_id.group(1)
            pid = password_id.group(1)
            pid2 = confirm_id.group(1)
            eid = email_id.group(1)

            # 生成随机用户名
            suffix = str(int(time.time()))[-6:] + str(random.randint(100, 999))
            username = f"bot{suffix}"
            password = f"Bot{suffix}Pass"
            email = f"bot{suffix}@mail.com"

            data = {
                'regsubmit': 'yes',
                'formhash': formhash,
                'referer': self.host + '/./',
                uid: username,
                pid: password,
                pid2: password,
                eid: email,
            }

            resp = session.post(self.host + "/member.php?mod=register", data=data, timeout=15)

            # 访问首页
            session.get(self.host + "/", timeout=15)

            # 获取cookies
            cookies = session.cookies.get_dict()
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())

            # 验证
            if cookie_str and 'auth' in cookie_str:
                test_resp = session.get(
                    self.host + "/forum.php?mod=forumdisplay&fid=2&filter=sortid&sortid=12&searchsort=1&page=1",
                    timeout=15)
                if 'data-tid' in test_resp.text:
                    return cookie_str

            return ""
        except Exception:
            return ""

    def clean(self, text):
        if not text:
            return ""
        text = html_mod.unescape(str(text))
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'[\x00-\x1f\x7f]', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def fetch_page(self, url, timeout=15):
        try:
            resp = self.fetch(url, headers=self.headers, timeout=timeout)
            if hasattr(resp, 'text'):
                text = resp.text
            else:
                text = str(resp)

            # 检测是否被重定向到登录页
            if text and ('pg_logging' in text or 'member.php?mod=logging' in text[:2000]) and 'data-tid' not in text:
                # Cookie可能过期，尝试重新注册
                if not self._relogin_attempted:
                    self._relogin_attempted = True
                    new_cookie = self.auto_register()
                    if new_cookie:
                        self.cookie = new_cookie
                        self.headers['Cookie'] = new_cookie
                        if self.cookie:
                            self.play_headers['Cookie'] = new_cookie
                        # 重试请求
                        resp = self.fetch(url, headers=self.headers, timeout=timeout)
                        if hasattr(resp, 'text'):
                            text = resp.text
                        else:
                            text = str(resp)
                    # 重置标志，允许下次过期时再次尝试
                    self._relogin_attempted = False

            return text
        except Exception as e:
            try:
                self.log(f"Fetch error: {e}")
            except:
                pass
            return ""

    def normalize_pic(self, src):
        if not src:
            return ""
        if src.startswith('//'):
            return 'https:' + src
        if src.startswith('http'):
            return src
        if src.startswith('/'):
            return self.host + src
        if src.startswith('data/attachment'):
            return self.host + '/' + src
        return src

    # ===================== 筛选器 =====================
    def build_filters(self):
        filters = {}
        for item in self.classes:
            tid = item["type_id"]
            cfg = self.filter_config.get(tid, {"type_key": "", "types": [["全部", ""]]})
            filter_list = [
                {
                    "key": "class",
                    "name": "类型",
                    "value": [{"n": t[0], "v": t[1]} for t in cfg["types"]],
                },
                {
                    "key": "area",
                    "name": "地区",
                    "value": [{"n": a[0], "v": a[1]} for a in self.area_filter],
                },
                {
                    "key": "year",
                    "name": "年份",
                    "value": [{"n": y[0], "v": y[1]} for y in self.year_filter],
                },
            ]
            filters[tid] = filter_list
        return filters

    # ===================== 分类URL构建 =====================
    # Discuz! 论坛URL格式：
    # 无筛选：forum.php?mod=forumdisplay&fid={fid}&page={pg}（所有分类通用）
    # 有筛选：forum.php?mod=forumdisplay&fid={fid}&filter=sortid&sortid=12&searchsort=1
    #         &movie_nianfen={year}&movie_diqu={area}&movie_dianying={class}&page={pg}
    # 注意：sortid=12筛选器仅对部分分类有效，无筛选时用简单URL
    def build_category_url(self, tid, pg, extend):
        extend = extend or {}
        pg = int(pg) if str(pg).isdigit() else 1
        cfg = self.filter_config.get(tid, {"type_key": ""})

        # 检查是否有筛选条件
        has_class = extend.get("class") and cfg.get("type_key")
        has_area = extend.get("area")
        has_year = extend.get("year")

        if not has_class and not has_area and not has_year:
            # 无筛选：使用简单URL（所有分类通用）
            return self.host + "/forum.php?mod=forumdisplay&fid=" + str(tid) + "&page=" + str(pg)

        # 有筛选：使用sortid=12筛选器
        params = [
            "mod=forumdisplay",
            "fid=" + str(tid),
            "filter=sortid",
            "sortid=12",
            "searchsort=1",
        ]

        # 类型筛选
        if has_class:
            params.append(cfg["type_key"] + "=" + extend["class"])
        # 地区筛选
        if has_area:
            params.append("movie_diqu=" + extend["area"])
        # 年份筛选
        if has_year:
            params.append("movie_nianfen=" + extend["year"])

        params.append("page=" + str(pg))
        return self.host + "/forum.php?" + "&".join(params)

    # ===================== 解析列表页 =====================
    # 列表页结构：
    # <li>
    #   <div class="mvposter" data-tid="175190">
    #     <a href="thread-175190-1-1.html">
    #       <img src="data/attachment/forum/..." data-src="...">
    #       <div class="mvepisodes">HD</div>
    #       ...
    #     </a>
    #   </div>
    #   <div class="mvinfo">
    #     <div class="mvinfo-title"><a href="...">标题</a></div>
    #     <div class="mvinfo-atts xg1">2026 / 美国&nbsp;/ 奇幻&nbsp;恐怖&nbsp;</div>
    #   </div>
    # </li>
    def parse_list_html(self, html_text):
        videos = []
        seen = set()
        if not html_text:
            return videos

        # 匹配整个 <li> 块（包含 mvposter 和 mvinfo）
        # 使用 <li> 到 </li> 的非贪婪匹配，避免嵌套div问题
        pattern = r'<li>\s*<div class="mvposter"[^>]*data-tid="(\d+)"[^>]*>(.*?)</li>'
        for m in re.finditer(pattern, html_text, re.DOTALL):
            vid = m.group(1)
            block = m.group(2)

            if vid in seen:
                continue
            seen.add(vid)

            # 标题：mvinfo-title > a
            title = ""
            title_m = re.search(r'mvinfo-title[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
            if title_m:
                title = self.clean(title_m.group(1))

            # 备用：从链接文本获取
            if not title:
                link_m = re.search(r'thread-\d+-\d+-\d+\.html[^>]*>(.*?)</a>', block, re.DOTALL)
                if link_m:
                    title = self.clean(link_m.group(1))

            if not title:
                continue

            # 图片：data-src 或 src
            pic = ""
            pic_m = re.search(r'data-src="([^"]*)"', block, re.DOTALL)
            if pic_m:
                pic = pic_m.group(1)
            if not pic:
                pic_m = re.search(r'<img[^>]*src="([^"]*)"', block, re.DOTALL)
                if pic_m:
                    pic = pic_m.group(1)
            pic = self.normalize_pic(pic)

            # 备注：mvepisodes
            remark = ""
            ep_m = re.search(r'mvepisodes[^>]*>(.*?)</div>', block, re.DOTALL)
            if ep_m:
                remark = self.clean(ep_m.group(1))

            videos.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': remark,
            })

        # 兜底：用更宽松的匹配
        if not videos:
            pattern2 = r'data-tid="(\d+)"'
            tids = re.findall(pattern2, html_text)
            for vid in tids:
                if vid in seen:
                    continue
                # 找对应的标题
                title_m = re.search(
                    r'data-tid="' + vid + r'"[^>]*>.*?mvinfo-title[^>]*>.*?<a[^>]*>(.*?)</a>',
                    html_text, re.DOTALL)
                if title_m:
                    title = self.clean(title_m.group(1))
                    seen.add(vid)
                    videos.append({
                        'vod_id': vid,
                        'vod_name': title,
                        'vod_pic': '',
                        'vod_remarks': '',
                    })

        return videos

    # ===================== 首页 =====================
    def homeContent(self, filter):
        html_text = self.fetch_page(self.host + "/")
        result = {
            'class': self.classes,
            'filters': self.build_filters(),
            'list': [],
        }
        if html_text:
            result['list'] = self.parse_list_html(html_text)[:30]
        return result

    def homeVideoContent(self):
        html_text = self.fetch_page(self.host + "/")
        return self.parse_list_html(html_text)[:30]

    # ===================== 分类 =====================
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        url = self.build_category_url(tid, pg, extend)
        html_text = self.fetch_page(url)
        videos = self.parse_list_html(html_text)

        # 如果带筛选的URL无内容，回退到无筛选URL
        if not videos and extend:
            fallback_url = self.host + "/forum.php?mod=forumdisplay&fid=" + str(tid) + "&page=" + str(pg)
            if fallback_url != url:
                html_text = self.fetch_page(fallback_url)
                videos = self.parse_list_html(html_text)

        # 翻页：从分页链接提取最大页码
        pagecount = 1
        try:
            max_pg = pg
            pg_matches = re.findall(r'[?&]page=(\d+)', html_text)
            for p in pg_matches:
                try:
                    p = int(p)
                    if p > max_pg and p < 99999:
                        max_pg = p
                except:
                    pass
            pagecount = max(max_pg, pg)
        except:
            pass

        return {
            'list': videos,
            'page': pg,
            'pagecount': pagecount,
            'limit': 20,
            'total': pagecount * 20,
        }

    # ===================== 详情 =====================
    def detailContent(self, ids):
        vid = str(ids[0]).replace('/dsx/', '').replace('.html', '')
        vid = re.sub(r'[^0-9]', '', vid)
        if not vid:
            return {'list': []}

        url = self.host + '/thread-' + vid + '-1-1.html'
        html_text = self.fetch_page(url)

        vod = {
            'vod_id': vid,
            'vod_name': '',
            'vod_pic': '',
            'vod_content': '',
            'vod_year': '',
            'vod_area': '',
            'vod_actor': '',
            'vod_director': '',
            'vod_remarks': '',
            'vod_class': '',
            'vod_play_from': '',
            'vod_play_url': '',
        }

        if not html_text:
            return {'list': [vod]}

        # 标题：filmname span
        name_m = re.search(r'filmname[^>]*>(.*?)</span>', html_text, re.DOTALL)
        if name_m:
            vod['vod_name'] = self.clean(name_m.group(1))
        if not vod['vod_name']:
            h1_m = re.search(r'<h1[^>]*>(.*?)</h1>', html_text, re.DOTALL)
            if h1_m:
                vod['vod_name'] = self.clean(h1_m.group(1))
        if not vod['vod_name']:
            title_m = re.search(r'<title>(.*?)</title>', html_text, re.DOTALL)
            if title_m:
                vod['vod_name'] = self.clean(title_m.group(1).split('-')[0].split('_')[0].split('》')[0].strip())

        # 海报：在详情页中查找 data/attachment 图片
        pic_patterns = [
            r'movie-detailboard[^>]*>.*?<img[^>]*src="([^"]*data/attachment[^"]*)"',
            r'mvposter[^>]*>.*?<img[^>]*src="([^"]*data/attachment[^"]*)"',
            r'<img[^>]*src="([^"]*data/attachment/forum[^"]*)"',
            r'<img[^>]*src="([^"]*data/attachment/filmcover[^"]*)"',
        ]
        for pat in pic_patterns:
            pic_m = re.search(pat, html_text, re.DOTALL | re.IGNORECASE)
            if pic_m:
                vod['vod_pic'] = self.normalize_pic(pic_m.group(1))
                break

        # 年份/地区/类型：mvoption 下的 a 标签
        # <div class="mvoption"><a>2026</a><a>美国</a><a>奇幻</a>...</div>
        opt_m = re.search(r'class="mvoption"[^>]*>(.*?)</div>', html_text, re.DOTALL)
        if opt_m:
            opt_links = re.findall(r'<a[^>]*>(.*?)</a>', opt_m.group(1), re.DOTALL)
            for link in opt_links:
                val = self.clean(link)
                if not val:
                    continue
                if re.match(r'^\d{4}$', val):
                    vod['vod_year'] = val
                elif not vod['vod_area']:
                    vod['vod_area'] = val
                else:
                    vod['vod_class'] = (vod['vod_class'] + " " + val).strip() if vod['vod_class'] else val

        # 导演：id="daoyan" 的 li
        # <li id="daoyan" class="actors"><span>导演：</span><div class="introduction"><div class="textcontent"><a>导演名</a></div></div></li>
        dir_m = re.search(r'id="daoyan"[^>]*>.*?<span>导演：</span>(.*?)</li>', html_text, re.DOTALL)
        if dir_m:
            links = re.findall(r'<a[^>]*>(.*?)</a>', dir_m.group(1), re.DOTALL)
            if links:
                vod['vod_director'] = '/'.join(self.clean(l) for l in links if self.clean(l))
            else:
                vod['vod_director'] = self.clean(dir_m.group(1))

        # 主演：id="zhuyan" 的 li
        act_m = re.search(r'id="zhuyan"[^>]*>.*?<span>主演：</span>(.*?)</li>', html_text, re.DOTALL)
        if act_m:
            links = re.findall(r'<a[^>]*>(.*?)</a>', act_m.group(1), re.DOTALL)
            if links:
                vod['vod_actor'] = '/'.join(self.clean(l) for l in links if self.clean(l))
            else:
                vod['vod_actor'] = self.clean(act_m.group(1))

        # 简介：id="juqing" 的 li
        plot_m = re.search(r'id="juqing"[^>]*>.*?<span>剧情：</span>(.*?)</li>', html_text, re.DOTALL)
        if plot_m:
            vod['vod_content'] = self.clean(plot_m.group(1))[:500]

        # ===================== 播放线路 =====================
        # 结构：<ul class="video-box">
        #   <li class="video-btn" data-source="西瓜">HD中字<span class="uservip">VIP</span></li>
        #   <li class="video-btn video-item" data-source="西瓜" data-url="encrypted">HD中字</li>
        # 每条线路由 data-source 区分
        play_from = []
        play_url = []

        # 提取所有 video-btn 元素（含或不含 data-url）
        btn_pattern = r'<li class="video-btn[^"]*"[^>]*data-source="([^"]*)"[^>]*>(.*?)</li>'
        btns = re.findall(btn_pattern, html_text, re.DOTALL)

        # 按 data-source 分组
        source_dict = {}
        source_order = []
        for source, inner in btns:
            if source not in source_dict:
                source_dict[source] = []
                source_order.append(source)
            ep_name = self.clean(inner).replace('VIP', '').strip()
            if ep_name:
                source_dict[source].append(ep_name + '$' + vid + '@@' + ep_name + '@@' + source)

        for source in source_order:
            eps = source_dict[source]
            play_from.append(source)
            play_url.append('#'.join(eps))

        # 兜底：如果没有播放列表，尝试从全文提取
        if not play_from:
            all_btns = re.findall(r'<li class="video-btn[^"]*"[^>]*>(.*?)</li>', html_text, re.DOTALL)
            ep_list = []
            for inner in all_btns:
                ep_name = self.clean(inner).replace('VIP', '').strip()
                if ep_name:
                    ep_list.append(ep_name + '$' + vid + '@@' + ep_name + '@@default')
            if ep_list:
                play_from.append('默认线路')
                play_url.append('#'.join(ep_list))

        vod['vod_play_from'] = '$$$'.join(play_from)
        vod['vod_play_url'] = '$$$'.join(play_url)
        return {'list': [vod]}

    # ===================== 搜索 =====================
    # 搜索URL：search.php?mod=forum&searchsubmit=yes&srchtxt={keyword}
    # 会重定向到 xunsearch 插件：plugin.php?id=twpx_xunsearch&q=KEYWORD
    # 搜索结果结构：<div class="mv-result-inner">
    #   <a href="thread-XXX-1-1.html" class="mv-result-link">
    #     <div class="mv-result-poster"><img src="data/attachment/filmcover/..."></div>
    #     <div class="mv-result-title">标题</div>
    #   </a>
    # </div>
    def searchContent(self, key, quick, pg="1"):
        pg = int(pg) if str(pg).isdigit() else 1
        wd = self.clean(key)
        if not wd:
            return {'list': [], 'page': pg}

        enc = quote(wd)
        # 使用 xunsearch 插件URL（search.php 会重定向到此）
        url = self.host + '/plugin.php?id=twpx_xunsearch&q=' + enc + '&s=relevance&syn=yes&mod=forum&searchsubmit=yes&page=' + str(pg)
        html_text = self.fetch_page(url)
        videos = self.parse_search_html(html_text)

        pagecount = 1
        try:
            pg_matches = re.findall(r'[?&]page=(\d+)', html_text)
            for p in pg_matches:
                try:
                    p = int(p)
                    if p > pagecount and p < 99999:
                        pagecount = p
                except:
                    pass
            pagecount = max(pagecount, pg)
        except:
            pass

        return {
            'list': videos,
            'page': pg,
            'pagecount': pagecount,
            'limit': 20,
            'total': pagecount * 20,
        }

    def parse_search_html(self, html_text):
        """解析搜索结果页（mv-result-inner 结构）"""
        videos = []
        seen = set()
        if not html_text:
            return videos

        # 用 mv-result-inner 分割，每个chunk对应一个搜索结果
        # 搜索结果结构：<div class="mv-result-inner"> 含 <a href="thread-XXX-1-1.html">
        parts = re.split(r'class="mv-result-inner"', html_text)
        for part in parts[1:]:  # 跳过第一个（在第一个mv-result-inner之前的内容）
            # thread ID
            link_m = re.search(r'href="[^"]*thread-(\d+)-\d+-\d+\.html"', part, re.DOTALL)
            if not link_m:
                continue
            vid = link_m.group(1)
            if vid in seen:
                continue

            # 标题：mv-result-title（可能含<em>标签高亮关键词）
            title = ""
            title_m = re.search(r'mv-result-title[^>]*>(.*?)</div>', part, re.DOTALL)
            if title_m:
                title = self.clean(title_m.group(1))

            # 图片
            pic = ""
            pic_m = re.search(r'<img[^>]*src="([^"]*)"', part, re.DOTALL)
            if pic_m:
                pic = pic_m.group(1)
            pic = self.normalize_pic(pic)

            if not title:
                continue

            seen.add(vid)
            videos.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': '',
            })

        # 兜底：直接提取所有 thread 链接和标题
        if not videos:
            pattern2 = r'href="[^"]*thread-(\d+)-\d+-\d+\.html"[^>]*>(.*?)</a>'
            for m in re.finditer(pattern2, html_text, re.DOTALL):
                vid = m.group(1)
                if vid in seen:
                    continue
                title = self.clean(m.group(2))
                if len(title) > 2 and not title.isdigit():
                    seen.add(vid)
                    videos.append({
                        'vod_id': vid,
                        'vod_name': title,
                        'vod_pic': '',
                        'vod_remarks': '',
                    })

        return videos

    # ===================== M3U8 URL 解密 =====================
    # 站点使用字符替换+Base64加密M3U8地址
    # decryptM3u8Url 函数的 Python 实现（与JS源码完全一致）
    def decrypt_m3u8_url(self, encrypted):
        if not encrypted:
            return ""

        # 字符替换映射（Caesar密码：每个字符向后移3位）
        sub_map = {
            'x': 'a', 'y': 'b', 'z': 'c', 'a': 'd', 'b': 'e', 'c': 'f', 'd': 'g', 'e': 'h',
            'f': 'i', 'g': 'j', 'h': 'k', 'i': 'l', 'j': 'm', 'k': 'n', 'l': 'o', 'm': 'p',
            'n': 'q', 'o': 'r', 'p': 's', 'q': 't', 'r': 'u', 's': 'v', 't': 'w', 'u': 'x',
            'v': 'y', 'w': 'z', 'X': 'A', 'Y': 'B', 'Z': 'C', 'A': 'D', 'B': 'E', 'C': 'F',
            'D': 'G', 'E': 'H', 'F': 'I', 'G': 'J', 'H': 'K', 'I': 'L', 'J': 'M', 'K': 'N',
            'L': 'O', 'M': 'P', 'N': 'Q', 'O': 'R', 'P': 'S', 'Q': 'T', 'R': 'U', 'S': 'V',
            'T': 'W', 'U': 'X', 'V': 'Y', 'W': 'Z', '5': '0', '6': '1', '7': '2', '8': '3',
            '9': '4', '0': '5', '1': '6', '2': '7', '3': '8', '4': '9', '_': '/', '~': '+',
            '$': '=',
        }

        # 去掉末尾的 $$
        encrypted = re.sub(r'\$\$+$', '', encrypted)

        # 字符替换
        decoded = ""
        for ch in encrypted:
            decoded += sub_map.get(ch, ch)

        # 替换 - 为 +，_ 为 /
        decoded = decoded.replace('-', '+').replace('_', '/')

        # Base64 填充
        padding = len(decoded) % 4
        if padding and padding != 1:
            decoded += '=' * (4 - padding)

        try:
            result = base64.b64decode(decoded).decode('utf-8', errors='ignore')
            if 'http' in result and '.m3u8' in result:
                return result
        except:
            pass

        return ""

    # ===================== 播放解析 =====================
    # VIP用户的播放按钮结构：<li class="video-btn video-item" data-source="西瓜" data-url="encrypted">第01集</li>
    # 非VIP用户的播放按钮结构：<li class="video-btn" data-source="西瓜">第01集<span class="uservip">VIP</span></li>
    def playerContent(self, flag, id, vipFlags):
        try:
            # id 格式：vid@@ep_name@@source
            parts = str(id).split('@@')
            vid = parts[0] if parts else str(id)
            ep_name = parts[1] if len(parts) > 1 else ''
            source = parts[2] if len(parts) > 2 else ''

            # 请求详情页
            url = self.host + '/thread-' + vid + '-1-1.html'
            html_text = self.fetch_page(url)

            # 尝试提取 data-url（加密的M3U8地址）
            # 只有VIP用户才能看到 data-url 属性
            video_url = ''

            # 查找对应集数的 data-url
            # 结构：<li class="video-btn video-item" data-url="encrypted" data-source="西瓜">第01集</li>
            btn_pattern = r'<li class="video-btn[^"]*"[^>]*data-url="([^"]*)"[^>]*>(.*?)</li>'
            for m in re.finditer(btn_pattern, html_text, re.DOTALL):
                enc_url = m.group(1)
                ep_text = self.clean(m.group(2)).replace('VIP', '').strip()
                if ep_name and ep_text == ep_name:
                    video_url = self.decrypt_m3u8_url(enc_url)
                    if video_url:
                        break

            # 如果没找到匹配的集数，取第一个可用的
            if not video_url:
                for m in re.finditer(btn_pattern, html_text, re.DOTALL):
                    enc_url = m.group(1)
                    video_url = self.decrypt_m3u8_url(enc_url)
                    if video_url:
                        break

            # 判断是否为直链
            if video_url:
                is_direct = bool(re.match(r'.+\.(m3u8|mp4|flv)(\?.*)?$', video_url, re.IGNORECASE))
                if is_direct:
                    return {
                        'parse': 0,
                        'playUrl': '',
                        'url': video_url,
                        'header': {'User-Agent': self.headers['User-Agent'], 'Referer': self.host + '/'},
                        'Header': {'User-Agent': self.headers['User-Agent'], 'Referer': self.host + '/'},
                    }
                else:
                    return {
                        'parse': 1,
                        'playUrl': '',
                        'url': video_url,
                        'header': {'User-Agent': self.headers['User-Agent'], 'Referer': self.host + '/'},
                        'Header': {'User-Agent': self.headers['User-Agent'], 'Referer': self.host + '/'},
                    }

            # 兜底：返回详情页URL，让播放器嗅探
            return {
                'parse': 1,
                'playUrl': '',
                'url': url,
                'header': {'User-Agent': self.headers['User-Agent'], 'Referer': self.host + '/'},
                'Header': {'User-Agent': self.headers['User-Agent'], 'Referer': self.host + '/'},
            }
        except Exception as e:
            try:
                self.log(f"Play error: {e}")
            except:
                pass
            return {'parse': 0, 'url': '', 'header': self.play_headers}

    # ===================== 其他 =====================
    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def localProxy(self, param):
        pass

    def liveContent(self, url):
        pass
