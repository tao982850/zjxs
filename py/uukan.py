#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优优影视(uukan.cc) - TVBox/影视仓 Python 爬虫插件
系统: 苹果CMS V10 (Ewave模板)
网站: https://uukan.cc

==================== v2 修复内容(针对"线路播放不了") ====================
1.【核心】player_aaaa 正则容错: 兼容 "var player_aaaa = {...}" 等空格/无var/无分号写法
   旧正则 'var player_aaaa=(\{.*?\});' 要求 = 紧贴且必须以 ; 结尾,
   与苹果CMS实际输出 "var player_aaaa = {...}" 不匹配 → 永远提不到直链
   → 所有线路回退 parse=1 网页解析 → 播放失败
2. 补齐苹果CMS encrypt 解密:
   encrypt=1 → UrlEncode 解码(unquote)                      [旧代码缺失]
   encrypt=2 → Base64 解码, 自动补 '=' padding, 兼容URL-safe [旧代码遇缺补位串直接失败]
   双重编码(base64+urlencode)自动二次解码
3. 直链/解析链接自动判别:
   .m3u8/.mp4/.flv 等媒体直链 → parse=0 直接播放(带 Referer/UA/Origin 防盗链头)
   解析iframe/网页链接        → parse=1 交给 TVBox/影视仓 嗅探播放
   [旧代码一律 parse=0, 导致 M1/B1/L/T1 等解析线路全部黑屏]
4. player JSON 容错: &quot; 转义 / 单引号 / 无引号key 均可解析,
   失败时正则兜底直接提取 "url" 字段
5. 源站经 Cloudflare 频繁回 520 小错误页 → 自动重试
6. 分类修正(与站点导航实测一致): 动漫=3, 综艺=73
   [旧代码 3=综艺 / 4=动漫 与站点不符, 导致分类打不开]
7. 列表去重(首页轮播/推荐位重复), 剧集过滤"xx线路"切换链接混入
8. 搜索无结果自动切换苹果CMS标准路由 /vodsearch/ 兜底
9. 电影大类增加子分类筛选(动作/喜剧/科幻等, ID取自站点导航)
=========================================================================
"""

import re
import sys
import json
import time
import base64
import html as htmllib
import requests
from urllib.parse import urljoin, quote, unquote

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        pass


class Spider(Spider):

    # 判定媒体直链的后缀
    MEDIA_EXTS = ('.m3u8', '.mp4', '.flv', '.mkv', '.ts', '.webm',
                  '.mov', '.avi', '.wmv', '.mp3', '.m4a', '.aac')

    def __init__(self):
        self.HOST = "https://uukan.cc"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://uukan.cc/',
        }
        self.session = requests.Session()

    def getName(self):
        return "优优影视"

    def init(self, extend=""):
        return json.dumps({"host": self.HOST})

    # ------------------------------------------------------------------
    # 网络请求(带重试: 源站经CF经常间歇性520)
    # ------------------------------------------------------------------
    def _get_html(self, url, retries=2):
        full_url = urljoin(self.HOST, url) if not str(url).startswith('http') else url
        last = ''
        for i in range(retries + 1):
            try:
                resp = self.session.get(full_url, headers=self.headers, timeout=15)
                if resp.status_code == 200:
                    text = resp.text
                    last = text
                    # 有效页面判定: 有关键内容或长度足够(过滤CF 520小错误页)
                    if ('player_aaaa' in text or 'vod/detail' in text
                            or 'vodsearch' in text or len(text) > 2000):
                        return text
                    print(f'疑似异常页({len(text)}字节), 重试: {full_url}')
                else:
                    print(f'HTTP {resp.status_code}: {full_url}')
            except Exception as e:
                print(f'请求失败({i + 1}/{retries + 1}): {full_url} -> {e}')
            if i < retries:
                time.sleep(1.2)
        return last

    # ------------------------------------------------------------------
    # 列表解析(首页/分类/搜索通用)
    # ------------------------------------------------------------------
    def _parse_vod_list(self, html):
        videos = []
        seen = set()
        if not html:
            return videos

        # 主模式: Ewave卡片 <li class="col-xs-4 ...">…</li>
        li_blocks = re.findall(
            r'<li[^>]*class="[^"]*col-xs-4[^"]*"[^>]*>(.*?)</li>', html, re.DOTALL)

        def _push(vod_id, title, cover, status, actor):
            if not vod_id or vod_id in seen:
                return
            seen.add(vod_id)  # 修复: 首页轮播/推荐位重复影片去重
            videos.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": cover,
                "vod_remarks": status,
                "vod_content": actor,
            })

        for block in li_blocks:
            # 详情链接 + 标题(带title属性优先)
            a = re.search(
                r'<a[^>]*href="/vod/detail/id/(\d+)\.html"[^>]*title="([^"]+)"', block)
            if not a:
                a = re.search(
                    r'<a[^>]*href="/vod/detail/id/(\d+)\.html"[^>]*>([^<]+)</a>', block)
                if not a:
                    continue
            vod_id, title = a.group(1), a.group(2).strip()

            img = re.search(r'data-original="([^"]+)"', block) or \
                  re.search(r'<img[^>]*src="([^"]+)"', block)
            cover = img.group(1).replace('&amp;', '&') if img else ''
            if 'movie_ico' in cover:  # 站点占位图
                cover = ''

            st = re.search(r'class="[^"]*pic-text[^"]*"[^>]*>([^<]+)<', block)
            status = st.group(1).strip() if st else ''

            ac = re.search(r'class="[^"]*text-actor[^"]*"[^>]*>([^<]*)<', block)
            actor = ac.group(1).strip() if ac else ''

            _push(vod_id, title, cover, status, actor)

        # 降级模式: 非标准页面, 全局提取详情链接
        if not videos:
            for vod_id, title in re.findall(
                    r'<a[^>]*href="/vod/detail/id/(\d+)\.html"[^>]*title="([^"]+)"', html):
                _push(vod_id, title.strip(), '', '', '')

        return videos

    # ------------------------------------------------------------------
    # 首页
    # ------------------------------------------------------------------
    def homeContent(self, filter):
        result = {'class': [], 'filters': {}, 'list': []}

        # 分类ID与站点导航实测一致: 动漫=3, 综艺=73
        classes = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "连续剧"},
            {"type_id": "3", "type_name": "动漫"},
            {"type_id": "73", "type_name": "综艺"},
            {"type_id": "20", "type_name": "短剧"},
            {"type_id": "39", "type_name": "影视解说"},
        ]
        result['class'] = classes

        # 电影子分类筛选(ID取自站点导航: /vod/show/id/6.html 动作片 …)
        result['filters'] = {
            "1": [{
                "key": "tid",
                "name": "类型",
                "value": [
                    {"n": "全部", "v": ""},
                    {"n": "动作片", "v": "6"},
                    {"n": "喜剧片", "v": "7"},
                    {"n": "爱情片", "v": "8"},
                    {"n": "科幻片", "v": "9"},
                    {"n": "恐怖片", "v": "10"},
                    {"n": "剧情片", "v": "11"},
                    {"n": "战争片", "v": "12"},
                    {"n": "古装片", "v": "60"},
                    {"n": "惊悚片", "v": "59"},
                    {"n": "动画片", "v": "31"},
                    {"n": "预告片", "v": "56"},
                ],
            }],
        }

        html = self._get_html("/")
        if html:
            result['list'] = self._parse_vod_list(html)[:24]
        return result

    def homeVideoContent(self):
        return self.categoryContent("1", 1, False, {})

    # ------------------------------------------------------------------
    # 分类页
    # ------------------------------------------------------------------
    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg)
        except Exception:
            page = 1

        # 支持筛选: extend['tid'] 可切换子分类
        ext = extend or {}
        real_tid = str(ext.get('tid') or tid).strip() or str(tid)

        if page == 1:
            url = f"/vod/type/id/{real_tid}.html"
        else:
            url = f"/vod/type/id/{real_tid}/page/{page}.html"

        html = self._get_html(url)
        videos = self._parse_vod_list(html) if html else []

        pagecount, total = page, len(videos)
        if html:
            pages = re.findall(r'page/(\d+)\.html', html)
            if pages:
                pagecount = max(int(p) for p in pages)
            last = re.search(
                r'href="(?:/vod/type/id/\d+/page/|/vod/show/id/\d+/page/)(\d+)\.html"'
                r'[^>]*>\s*(?:末页|尾页|&raquo;|&gt;&gt;)', html)
            if last:
                pagecount = int(last.group(1))

        return {
            "list": videos,
            "page": page,
            "pagecount": max(pagecount, page),
            "limit": "24",
            "total": total,
        }

    # ------------------------------------------------------------------
    # 搜索(主路由失败自动切换苹果CMS标准 /vodsearch/ 路由)
    # ------------------------------------------------------------------
    def searchContent(self, key, quick, pg=1):
        try:
            page = int(pg)
        except Exception:
            page = 1

        keyword = quote(key)
        url = f"/vod/search.html?wd={keyword}"
        if page > 1:
            url += f"&page={page}"

        html = self._get_html(url)
        videos = self._parse_vod_list(html) if html else []

        if not videos:  # 兜底路由
            url2 = f"/vodsearch/-------------.html?wd={keyword}"
            if page > 1:
                url2 += f"&page={page}"
            html2 = self._get_html(url2)
            videos = self._parse_vod_list(html2) if html2 else []

        return {"list": videos, "page": page, "pagecount": page}

    # ------------------------------------------------------------------
    # 详情页
    # ------------------------------------------------------------------
    def detailContent(self, ids):
        vod_id = ids[0] if isinstance(ids, list) else ids
        url = f"/vod/detail/id/{vod_id}.html"
        html = self._get_html(url)

        if not html:
            return {"list": [{
                "vod_id": vod_id,
                "vod_name": "获取失败",
                "vod_pic": "",
                "vod_content": "详情页获取失败, 请稍后重试(源站不稳定)",
            }]}

        # 标题: h1 → og:title
        t = re.search(r'<h1[^>]*>(?:<a[^>]*>)?([^<]+)<', html)
        title = t.group(1).strip() if t else ''
        if not title:
            t = re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', html)
            title = t.group(1).strip() if t else '未知标题'

        # 封面: data-original → og:image
        c = re.search(r'data-original="([^"]+)"', html)
        cover = c.group(1).replace('&amp;', '&') if c else ''
        if not cover:
            c = re.search(r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', html)
            cover = c.group(1).replace('&amp;', '&') if c else ''

        # 简介: desc/content 容器 → meta description
        desc = ''
        for pat in (r'class="[^"]*desc[^"]*"[^>]*>(.*?)</div>',
                    r'class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
                    r'<p[^>]*style="[^"]*line-height[^"]*"[^>]*>(.*?)</p>'):
            m = re.search(pat, html, re.DOTALL)
            if m:
                desc = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                if desc:
                    break
        if not desc:
            m = re.search(r'name=["\']description["\'][^>]*content=["\']([^"\']+)["\']', html)
            if m:
                desc = m.group(1).strip()

        # ---------------- 播放源与剧集 ----------------
        play_from, play_url = [], []

        # 剧集名过滤: 排除"M1线路8/S1国内8"这类线路切换链接混入剧集列表
        # (仅用于剧集名判断, 线路名本身可含"线路"字样)
        def _is_ep_name(name):
            return not re.search(r'线路|国内|来源|切换', name)

        # 模式1: Ewave 播放源标签 <li data-target="#playlist1"><span>M1线路</span>…
        tabs = re.findall(
            r'<(?:li|a)[^>]*data-target="([^"]+)"[^>]*>(.*?)</(?:li|a)>', html, re.DOTALL)
        for target, tab_html in tabs:
            nm = re.search(r'<span[^>]*>([^<]+)</span>', tab_html) or \
                 re.search(r'>([^<]{1,20})<', tab_html)
            source_name = nm.group(1).strip() if nm else ''
            if not source_name:
                continue  # 线路名可含"线路/国内"字样, 不过滤

            pid = target.strip().lstrip('#')
            pm = re.search(
                rf'<(?:ul|div)[^>]*id="{pid}"[^>]*>(.*?)</(?:ul|div)>', html, re.DOTALL)
            if not pm:
                continue
            eps = re.findall(
                r'href="(/vod/play/id/\d+/sid/\d+/nid/\d+\.html)"[^>]*>([^<]+)</a>',
                pm.group(1))
            urls, used = [], set()
            for href, ep in eps:
                ep = ep.strip()
                if href in used or not _is_ep_name(ep):
                    continue
                used.add(href)
                urls.append(f"{ep}${href}")
            if urls:
                play_from.append(source_name)
                play_url.append("#".join(urls))

        # 模式2: 备用 —— 全页面按 sid 分组(保持出现顺序, 使用真实href)
        if not play_from:
            all_eps = re.findall(
                r'href="(/vod/play/id/\d+/sid/(\d+)/nid/\d+\.html)"[^>]*>([^<]+)</a>', html)
            sid_groups = {}
            for href, sid, ep in all_eps:
                ep = ep.strip()
                if not _is_ep_name(ep):
                    continue
                sid_groups.setdefault(sid, [])
                item = f"{ep}${href}"
                if item not in sid_groups[sid]:
                    sid_groups[sid].append(item)
            for sid, items in sid_groups.items():
                if items:
                    play_from.append(f"线路{sid}")
                    play_url.append("#".join(items))

        if not play_from:
            play_from.append("默认线路")
            play_url.append(f"播放$/vod/play/id/{vod_id}/sid/1/nid/1.html")

        return {"list": [{
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": cover,
            "vod_content": desc,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }]}

    # ------------------------------------------------------------------
    # 播放解析(核心修复)
    # ------------------------------------------------------------------
    def playerContent(self, flag, id, vipFlags):
        """解析播放: 兼容 player_aaaa/player_data/player_config, 自动解密,
        直链返回 parse=0, 解析页返回 parse=1"""
        play_url = urljoin(self.HOST, id) if str(id).startswith('/') else str(id)
        html = self._get_html(play_url)
        if not html:
            return {"parse": 1, "url": play_url, "header": self.headers}

        data = self._extract_player_json(html)
        video_url = ''
        if data:
            try:
                encrypt = int(data.get('encrypt') or 0)
            except Exception:
                encrypt = 0
            video_url = self._decode_play_url(str(data.get('url') or ''), encrypt)

        if not video_url:
            # 提不出直链 → 交 TVBox 网页嗅探
            return {"parse": 1, "url": play_url, "header": self.headers}

        # 相对路径 → 绝对
        if video_url.startswith('//'):
            video_url = 'https:' + video_url
        elif video_url.startswith('/'):
            video_url = urljoin(self.HOST, video_url)
        elif not video_url.startswith('http'):
            video_url = urljoin(play_url, video_url)

        play_headers = {
            'User-Agent': self.headers['User-Agent'],
            'Referer': play_url,
        }

        if self._is_direct_media(video_url):
            # 媒体直链 → 直接播放(补 Origin/Accept 防盗链)
            play_headers['Origin'] = self.HOST
            play_headers['Accept'] = '*/*'
            return {"parse": 0, "url": video_url, "header": play_headers}

        # 解析/iframe 链接 → 交给播放器嗅探最终媒体地址
        return {"parse": 1, "url": video_url, "header": play_headers}

    # ---------- 播放相关工具函数 ----------

    def _extract_player_json(self, html):
        """提取苹果CMS播放器变量, 多变量名 + 容错解析"""
        for name in ('player_aaaa', 'player_data', 'player_config', 'player_info'):
            # 修复: \s*=\s* 兼容 "var player_aaaa = {" 带空格写法; 结尾分号可有可无
            m = re.search(name + r'\s*=\s*(\{.*?\})', html, re.DOTALL)
            if not m:
                continue
            raw = htmllib.unescape(m.group(1)).strip().rstrip(';')
            try:
                return json.loads(raw)
            except Exception:
                fixed = raw
                # 无引号key补引号 / 单引号换双引号
                if re.search(r'[{,]\s*\w+\s*:', fixed):
                    fixed = re.sub(r'([{,]\s*)(\w+)\s*:', r'\1"\2":', fixed)
                fixed = fixed.replace("'", '"')
                try:
                    return json.loads(fixed)
                except Exception:
                    um = re.search(r'"url"\s*:\s*"([^"]*)"', fixed)
                    if um:
                        return {'url': um.group(1)}
        # 最后兜底: 全文直接找 url 字段(仅接受像链接的值)
        um = re.search(r'"url"\s*:\s*"([^"]+)"', html)
        if um and um.group(1).startswith(('http', '//', '%')):
            return {'url': um.group(1)}
        return None

    def _decode_play_url(self, url, encrypt):
        """按苹果CMS encrypt 类型解密播放地址"""
        url = (url or '').strip().strip('"\'')
        if not url:
            return ''
        try:
            if encrypt == 1:            # UrlEncode 编码
                url = unquote(url)
            elif encrypt == 2:          # Base64 编码(自动补padding + URL-safe兼容)
                u = url
                pad = '=' * (-len(u) % 4)
                try:
                    u = base64.b64decode(u + pad).decode('utf-8', 'ignore')
                except Exception:
                    u = base64.urlsafe_b64decode(u + pad).decode('utf-8', 'ignore')
                url = u
        except Exception as e:
            print(f'解密播放地址失败: {e}')
        # 双重编码兜底(base64解出后仍为urlencode形态)
        if '%3A%2F%2F' in url or url.startswith('%2F'):
            url = unquote(url)
        return url.strip()

    def _is_direct_media(self, u):
        """判定是否为可直接播放的媒体直链"""
        if not u:
            return False
        low = u.lower()
        path = low.split('?', 1)[0]
        for ext in self.MEDIA_EXTS:
            if path.endswith(ext):
                return True
        if '.m3u8?' in low or '.mp4?' in low or '.flv?' in low:
            return True
        if re.search(r'\.m3u8|\.mp4', low):  # 伪静态直链 /video/xx.m3u8/分段
            return True
        return False

    def localProxy(self, param):
        return [200, "text/plain; charset=utf-8", ""]


# ==================== 本地测试 ====================
if __name__ == '__main__':
    spider = Spider()
    spider.init()

    # ---------- 离线自测(不需要网络, 验证修复逻辑) ----------
    def self_test():
        import base64 as b64
        from urllib.parse import quote as _q
        print("=" * 56)
        print("【离线自测】播放解析修复验证")
        real_get = spider._get_html

        # 用例1: 标准 player_aaaa(带空格! 旧正则匹配不到的形态), 直链m3u8
        fix1 = ('<script>var player_aaaa = {"flag":"m3u8","encrypt":0,"trysee":0,'
                '"link":"/vod/play/id/1/sid/1/nid/1.html",'
                '"url":"https://cache.example.com/v/2026/abc/index.m3u8",'
                '"from":"m3u8","server":"no","id":"1","sid":1,"nid":1}</script>')
        # 用例2: encrypt=2, Base64缺padding, 解出的是解析页链接
        inner = 'https://jx.example.com/?url=https://v.qq.com/x/cover/abc.html'
        enc2 = b64.b64encode(inner.encode()).decode().rstrip('=')
        fix2 = ('<script>var player_aaaa = {"flag":"qq","encrypt":2,"trysee":0,'
                f'"url":"{enc2}","from":"qq","id":"2","sid":2,"nid":1}}'
                '</script>')
        # 用例3: encrypt=1, UrlEncode
        fix3 = ('<script>player_data={"flag":"youku","encrypt":1,'
                f'"url":"{_q("https://cdn.example.com/s/movie.mp4", safe="")}",'
                '"from":"youku","id":"3","sid":3,"nid":1};</script>')

        cases = [
            ('直链(m3u8, var带空格)', fix1, 0, 'index.m3u8'),
            ('encrypt=2缺padding解析页', fix2, 1, 'jx.example.com'),
            ('encrypt=1直链(mp4)',     fix3, 0, 'movie.mp4'),
        ]
        ok = 0
        for name, fix, want_parse, want_frag in cases:
            spider._get_html = lambda u, r=2, f=fix: f
            r = spider.playerContent('x', '/vod/play/id/9/sid/9/nid/9.html', [])
            hit = (r.get('parse') == want_parse) and (want_frag in r.get('url', ''))
            ok += hit
            print(f"  [{'通过' if hit else '失败'}] {name}: parse={r.get('parse')} url={r.get('url', '')[:70]}")
        spider._get_html = real_get

        # 旧正则失败复现(证明修复必要性)
        old = re.search(r'var player_aaaa=(\{.*?\});', fix1, re.DOTALL)
        print(f"  旧正则对用例1匹配结果: {old}  ({'证实旧代码提不到直链' if not old else '意外匹配'})")
        print(f"自测通过: {ok}/{len(cases)}")

    self_test()

    # ---------- 在线测试(源站不稳定时可能拉取失败) ----------
    print("\n" + "=" * 56)
    print("【在线测试】首页/分类/详情")
    try:
        home = spider.homeContent(False)
        print(f"分类数: {len(home['class'])}  影片数: {len(home['list'])}")
        if home['list']:
            print(f"示例: {home['list'][0]['vod_name']} - {home['list'][0]['vod_remarks']}")
    except Exception as e:
        print(f"首页测试失败: {e}")

    try:
        for tid, name in (("1", "电影"), ("2", "连续剧"), ("3", "动漫"), ("73", "综艺")):
            cat = spider.categoryContent(tid, 1, False, {})
            print(f"分类 {name}(ID={tid}): {len(cat['list'])} 条")
    except Exception as e:
        print(f"分类测试失败: {e}")

    try:
        if home['list']:
            d = spider.detailContent([home['list'][0]['vod_id']])['list'][0]
            print(f"详情: {d['vod_name']}  线路: {d.get('vod_play_from', '')}")
    except Exception as e:
        print(f"详情测试失败: {e}")
