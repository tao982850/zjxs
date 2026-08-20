# -*- coding: utf-8 -*-
# 追影 - 七哥定制版
import re
import sys
import json
import time
import hashlib
import random
import base64
from urllib.parse import quote, unquote, urljoin
from pyquery import PyQuery as pq
sys.path.append('..')
from base.spider import Spider

class Spider(Spider):
    def init(self, extend=""):
        """初始化 适配配置"""
        self.host = "https://zhuiying9.cc"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 11; MI 11 Build/RKQ1.201022.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/92.0.4515.159 Mobile Safari/537.36 TVBox/1.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': self.host
        }
        self.source_map = {"1": "MD源", "2": "BF源", "3": "LZ源"}
        self.ua_list = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1'
        ]

    def getName(self):
        return "追影"

    def isVideoFormat(self, url):
        """判断是否为直接播放格式"""
        video_exts = ['.mp4', '.m3u8', '.flv', '.avi', '.mov', '.rmvb']
        return any(ext in url.lower() for ext in video_exts)

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def fix_encoding(self, text):
        """编码修复"""
        if not text:
            return ""
        try:
            if isinstance(text, bytes):
                try:
                    text = text.decode('utf-8')
                except UnicodeDecodeError:
                    text = text.decode('gbk', errors='ignore')
            if '\\u' in text:
                try:
                    text = text.encode('utf-8').decode('unicode_escape')
                except:
                    pass
            text = re.sub(r'[\x00-\x1f\x7f]', '', text).strip()
            return text
        except Exception as e:
            self.log(f"编码修复异常: {str(e)}")
            return str(text) if text else ""

    def fetch_with_encoding(self, url, **kwargs):
        """带编码处理的请求方法"""
        try:
            time.sleep(random.uniform(0.3, 0.8))
            headers = kwargs.get('headers', self.headers.copy())
            headers['User-Agent'] = random.choice(self.ua_list)
            kwargs['headers'] = headers
            response = self.fetch(url, timeout=15, allow_redirects=True, **kwargs)
            response.encoding = 'utf-8'
            if response.status_code != 200 or len(response.text) < 500:
                self.log(f"请求失败，状态码: {response.status_code}")
                raise Exception(f"页面内容无效")
            return response
        except Exception as e:
            self.log(f"请求 {url} 出错: {str(e)}")
            raise

    def getpq(self, text):
        """安全的pyquery解析"""
        try:
            return pq(text)
        except Exception as e:
            self.log(f"PyQuery 解析失败: {str(e)}")
            clean_text = re.sub(r'[^\x20-\x7e一-鿿]', '', text)
            return pq(clean_text) if clean_text else pq('')

    def homeContent(self, filter):
        """获取首页内容和分类"""
        try:
            response = self.fetch_with_encoding(self.host)
            doc = self.getpq(response.text)

            result = {}
            classes = []
            nav_items = doc('aside.sidebar a.nav-item[href*="/vodtype/"]').items()
            seen_cate = set()
            for item in nav_items:
                cate_text = self.fix_encoding(item.text().strip())
                cate_href = item.attr('href')
                if not cate_text or not cate_href:
                    continue
                # 提取分类标识
                slug = re.search(r'/vodtype/(\w+)\.html', cate_href)
                if not slug or slug.group(1) in seen_cate:
                    continue
                slug_val = slug.group(1)
                seen_cate.add(slug_val)
                classes.append({
                    'type_name': cate_text,
                    'type_id': slug_val
                })

            # 首页视频列表
            videos = []
            seen_ids = set()
            card_items = doc('a.card.js-card-item[href*="/video/"]').items()
            for card in card_items:
                vod_href = card.attr('href')
                vod_id = re.search(r'/video/(\w+)\.html', vod_href)
                if not vod_id or vod_id.group(1) in seen_ids:
                    continue
                vod_id = vod_id.group(1)
                seen_ids.add(vod_id)

                img = card.find('img')
                vod_title = self.fix_encoding(
                    img.attr('alt') or card.find('.card-title').text().strip() or ""
                )
                if not vod_title:
                    continue

                vod_pic = img.attr('src') or ""
                vod_remarks = self.fix_encoding(card.find('.card-status').text().strip())
                videos.append({
                    'vod_id': vod_id,
                    'vod_name': vod_title,
                    'vod_pic': vod_pic,
                    'vod_year': '',
                    'vod_remarks': vod_remarks
                })

            result['class'] = classes
            result['list'] = videos
            return result
        except Exception as e:
            self.log(f"获取首页内容时出错: {e}")
            return {'class': [], 'list': []}

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        """获取分类内容"""
        try:
            url = f"{self.host}/vodtype/{tid}.html"
            if int(pg) > 1:
                url = f"{self.host}/vodtype/{tid}-{pg}.html"

            response = self.fetch_with_encoding(url)
            doc = self.getpq(response.text)

            videos = []
            seen_ids = set()
            card_items = doc('a.card.js-card-item[href*="/video/"]').items()
            for card in card_items:
                vod_href = card.attr('href')
                vod_id = re.search(r'/video/(\w+)\.html', vod_href)
                if not vod_id or vod_id.group(1) in seen_ids:
                    continue
                vod_id = vod_id.group(1)
                seen_ids.add(vod_id)

                img = card.find('img')
                vod_title = self.fix_encoding(
                    img.attr('alt') or card.find('.card-title').text().strip() or ""
                )
                if not vod_title:
                    continue

                vod_pic = img.attr('src') or ""
                vod_remarks = self.fix_encoding(card.find('.card-status').text().strip())
                videos.append({
                    'vod_id': vod_id,
                    'vod_name': vod_title,
                    'vod_pic': vod_pic,
                    'vod_year': '',
                    'vod_remarks': vod_remarks
                })

            result = {
                'list': videos,
                'page': pg,
                'pagecount': 9999,
                'limit': 80,
                'total': 999999
            }
            return result
        except Exception as e:
            self.log(f"获取分类内容时出错: {e}")
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 80, 'total': 0}

    def detailContent(self, ids):
        """获取视频详情"""
        result = {"list": []}
        if not ids or len(ids) == 0:
            return result
        vod_id = ids[0]

        try:
            detail_url = f"{self.host}/video/{vod_id}.html"
            response = self.fetch_with_encoding(detail_url)
            doc = self.getpq(response.text)

            # 基本信息
            vod_info = {
                "vod_id": vod_id,
                "vod_name": self.fix_encoding(doc('h1.detail-title').text().strip()),
                "vod_pic": doc('img.detail-poster').attr('src') or "",
                "vod_year": self.fix_encoding(doc('span.detail-year').text().strip()),
                "vod_remarks": "",
                "vod_actor": "",
                "vod_director": "",
                "vod_content": self.fix_encoding(doc('#synopsisContent').text().strip()),
                "vod_play_from": "",
                "vod_play_url": ""
            }

            # 演员和导演信息
            for actor_line in doc('.actor-line').items():
                label = self.fix_encoding(actor_line.find('.label').text().strip().rstrip(':'))
                val = self.fix_encoding(actor_line.find('.val').text().strip())
                if not val:
                    continue
                if '导演' in label:
                    vod_info["vod_director"] = val
                elif '主演' in label:
                    vod_info["vod_actor"] = val

            # 评分从详情页第一个预览卡中获取
            score_elems = doc('.preview_bottom_wrap_3Q-13 .score-num')
            first_score = ''
            for elem in score_elems.items():
                first_score = elem.text().strip()
                if first_score:
                    break
            vod_info["vod_remarks"] = self.fix_encoding(first_score)

            # 播放源和集数
            all_sources_data = {}
            tab_items = doc('div.source-tab[data-target]').items()
            for tab in tab_items:
                tab_id = tab.attr('data-target')  # e.g. "ep-list-2"
                source_id = tab_id.replace('ep-list-', '')
                source_name = self.fix_encoding(tab.find('.tab-name').text().strip())
                display_name = self.source_map.get(source_id, source_name)

                # 获取对应集数列表
                episodes = []
                ep_container = doc(f'#{tab_id}')
                ep_links = ep_container.find('a.ep-item-square').items()
                for ep in ep_links:
                    ep_href = ep.attr('href')
                    ep_title = self.fix_encoding(ep.text().strip())
                    if ep_title and ep_href:
                        full_href = urljoin(self.host, ep_href)
                        episodes.append(f"{ep_title}${full_href}")

                if episodes:
                    all_sources_data[display_name] = '#'.join(episodes)

            # 按源ID顺序排列（1=MD源, 2=BF源, 3=LZ源）
            final_play_from = []
            final_play_url = []
            for src_id in sorted(all_sources_data.keys(), key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 99):
                final_play_from.append(src_id)
                final_play_url.append(all_sources_data[src_id])

            if not final_play_from:
                # 兜底：尝试从详情页获取第一个播放链接
                play_links = doc('.detail-play-right a[href^="/play/"]')
                play_link = None
                for link in play_links.items():
                    play_link = link.attr('href')
                    if play_link:
                        break
                if play_link:
                    final_play_from.append("默认源")
                    final_play_url.append(f"正片${urljoin(self.host, play_link)}")

            vod_info["vod_play_from"] = "$$$".join(final_play_from)
            vod_info["vod_play_url"] = "$$$".join(final_play_url)

            result["list"].append(vod_info)
            return result
        except Exception as e:
            self.log(f"获取视频详情时出错: {e}")
            return {'list': []}

    def searchContent(self, key, quick, pg="1"):
        """搜索功能"""
        result = {"list": [], "page": int(pg)}
        try:
            data = f"wd={quote(key)}&page={pg}"
            headers = self.headers.copy()
            headers.update({
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest'
            })
            response = self.fetch(
                f"{self.host}/index.php/vod/search",
                method='POST',
                data=data,
                headers=headers,
                timeout=15,
                allow_redirects=True
            )
            doc = self.getpq(response.text)

            videos = []
            seen_ids = set()
            card_items = doc('a.list-card-thumb[href*="/video/"], a.hotsearch_hot_item[href*="/video/"]').items()
            for card in card_items:
                vod_href = card.attr('href')
                vod_id = re.search(r'/video/(\w+)\.html', vod_href)
                if not vod_id or vod_id.group(1) in seen_ids:
                    continue
                vod_id = vod_id.group(1)
                seen_ids.add(vod_id)

                img = card.find('img')
                vod_title = self.fix_encoding(
                    card.attr('title') or
                    img.attr('alt') or
                    card.find('.list-title a').text().strip() or ""
                )
                if not vod_title:
                    continue

                vod_pic = img.attr('src') or ""
                vod_remarks = self.fix_encoding(card.find('.list-thumb-remark').text().strip())
                videos.append({
                    "vod_id": vod_id,
                    "vod_name": vod_title,
                    "vod_pic": vod_pic,
                    "vod_year": "",
                    "vod_remarks": vod_remarks
                })

            result["list"] = videos
            self.log(f"搜索 '{key}' 找到 {len(videos)} 个结果")
        except Exception as e:
            self.log(f"搜索失败: {str(e)}")
        return result

    def playerContent(self, flag, id, vipFlags):
        """播放地址解析"""
        try:
            play_page_url = urljoin(self.host, id)
            if not play_page_url.startswith(('http://', 'https://')):
                return {"parse": 1, "url": "", "header": self.headers}

            response = self.fetch_with_encoding(play_page_url)
            html_content = response.text

            # 提取 MAC_PLAY_CONFIG
            config_match = re.search(r'window\.MAC_PLAY_CONFIG\s*=\s*(\{[^;]+\});', html_content, re.DOTALL)
            if not config_match:
                self.log("未找到播放器配置 MAC_PLAY_CONFIG")
                return {"parse": 1, "url": play_page_url, "header": self.headers}

            cfg_text = config_match.group(1)
            baseKey_match = re.search(r'baseKey:\s*"([^"]+)"', cfg_text)
            requestUrl_match = re.search(r'requestUrl:\s*"([^"]+)"', cfg_text)

            if not baseKey_match or not requestUrl_match:
                self.log("无法提取 baseKey 或 requestUrl")
                return {"parse": 1, "url": play_page_url, "header": self.headers}

            baseKey = baseKey_match.group(1)
            requestUrl = requestUrl_match.group(1)

            # 构造 API 请求
            timestamp = int(time.time())
            userAgent = random.choice(self.ua_list)
            token = hashlib.md5((baseKey + str(timestamp) + userAgent).encode()).hexdigest()
            encoded_url = quote(requestUrl, safe='')

            api_response = self.fetch(
                f"{self.host}/player_api.php",
                method='POST',
                data=f"url={encoded_url}&timestamp={timestamp}&token={token}",
                headers={
                    'User-Agent': userAgent,
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Referer': play_page_url
                },
                timeout=15
            )

            api_data = json.loads(api_response.text)
            if api_data.get('error'):
                self.log(f"API 错误: {api_data.get('error')}")
                return {"parse": 1, "url": play_page_url, "header": self.headers}

            # 解密响应数据
            data_str = api_data.get('data', '')
            if not data_str:
                self.log("API 返回数据为空")
                return {"parse": 1, "url": play_page_url, "header": self.headers}

            # 反转 + base64 解码
            reversed_data = data_str[::-1]
            decoded = base64.b64decode(reversed_data).decode('utf-8', errors='ignore')
            parsed = json.loads(decoded)

            video_url = parsed.get('jmurl', '').strip()
            url_type = parsed.get('urltype', '')

            if not video_url:
                self.log("未提取到视频地址")
                return {"parse": 1, "url": play_page_url, "header": self.headers}

            self.log(f"视频地址: {video_url[:100]}")
            self.log(f"URL类型: {url_type}")

            # m3u8 类型需要特殊 header
            if url_type in ('m3u8', 'hls'):
                return {
                    "parse": 0,
                    "url": video_url,
                    "header": {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
                        "Referer": self.host + "/",
                        "Origin": self.host.rstrip('/')
                    }
                }
            else:
                return {
                    "parse": 0,
                    "url": video_url,
                    "header": {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
                        "Referer": play_page_url,
                        "Origin": self.host.rstrip('/')
                    }
                }

        except Exception as e:
            self.log(f"播放地址解析异常: {str(e)}")
            return {
                "parse": 1,
                "url": urljoin(self.host, id),
                "header": self.headers
            }

    def localProxy(self, param):
        pass
