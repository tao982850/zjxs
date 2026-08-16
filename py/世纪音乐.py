"""蜜果-http://6i.pw/"""
import re
import sys
import json
import time
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from base64 import b64encode, b64decode
from urllib.parse import quote, unquote
from pyquery import PyQuery as pq
from requests import Session, adapters
from urllib3.util.retry import Retry

sys.path.append('..')
from base.spider import Spider

class Spider(Spider):
    def init(self, extend=""):
        self.host = "https://www.4c44.com"
        self.session = Session()
        adapter = adapters.HTTPAdapter(max_retries=Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504]), pool_connections=20, pool_maxsize=50)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.4c44.com/"
        }
        self.session.headers.update(self.headers)

        # 支持在 TVBox ext 中传入 host/cookie。目标站偶尔会启用一小时
        # 人机验证；用户在浏览器完成验证后，可把普通 Cookie 字符串放入
        # ext.cookie，无需改动脚本源码。
        ext_cfg = extend if isinstance(extend, dict) else {}
        if isinstance(extend, str) and extend.strip():
            try:
                parsed = json.loads(extend)
                if isinstance(parsed, dict):
                    ext_cfg = parsed
            except Exception:
                ext_cfg = {"cookie": extend.strip()} if "=" in extend else {}
        if ext_cfg.get("host"):
            self.host = str(ext_cfg["host"]).rstrip("/")
            self.headers["Referer"] = self.host + "/"
            self.session.headers.update({"Referer": self.headers["Referer"]})
        if ext_cfg.get("cookie"):
            self.session.headers.update({"Cookie": str(ext_cfg["cookie"])})

        # 世纪音乐网页面启用人机验证时使用的公开备用数据源。
        self.netease_api = "https://music.163.com"
        self.music_url_api = "https://fy-musicbox-api.mu-jie.cc"
        self.mv_detail_cache = {}
        self.mv_cache_lock = threading.Lock()
        
        # 歌词缓存
        self.lrc_cache = {}
        
        # 当前分类信息缓存
        self.current_category = {}
        
        # 分页缓存
        self.page_cache = {}
        
        # 首页推荐缓存
        self.home_recommend_cache = []

    def getName(self): 
        return "世纪音乐网·爱听音乐风格版"
    
    def isVideoFormat(self, url): 
        return bool(re.search(r'\.(m3u8|mp4|mp3|flv|wav|aac|ogg|m4a)(\?|$)', url or "", re.I))
    
    def manualVideoCheck(self): 
        return False
    
    def destroy(self): 
        self.session.close()

    # ==================== 图片处理 ====================
    def _get_image(self, url, is_singer=False, is_mv=False):
        if not url:
            return ""
        if url.startswith('//'):
            url = 'https:' + url
        elif url.startswith('/'):
            url = self.host + url
        elif not url.startswith('http'):
            url = self.host + '/' + url
        if is_singer:
            url = url.replace('param=200y200', 'param=500y500')
            url = url.replace('?param=200y200', '?param=500y500')
        if is_mv:
            url = url.replace('?imageView=1&thumbnail=800y', '?imageView=1&thumbnail=1280y720')
        return url

    # ==================== 首页分类 ====================
    def homeContent(self, filter):
        classes = [
            {"type_name": "🏠 首页推荐", "type_id": "home"},
            {"type_name": "📊 排行榜", "type_id": "rank_list"},
            {"type_name": "📀 歌单", "type_id": "playlist"},
            {"type_name": "👤 歌手", "type_id": "singer"},
            {"type_name": "🎬 MV", "type_id": "mv"}
        ]
        
        filters = {
            "singer": [
                {
                    "key": "sex",
                    "name": "👤 性别",
                    "value": [
                        {"n": "👩 女歌手", "v": "girl"},
                        {"n": "👨 男歌手", "v": "male"},
                        {"n": "🎭 乐队组合", "v": "band"}
                    ]
                },
                {
                    "key": "area",
                    "name": "🌏 地区",
                    "value": [
                        {"n": "🇨🇳 华语", "v": "huayu"},
                        {"n": "🌍 欧美", "v": "oumei"},
                        {"n": "🇰🇷 韩国", "v": "hanguo"},
                        {"n": "🇯🇵 日本", "v": "ribrn"}
                    ]
                },
                {
                    "key": "char",
                    "name": "🔤 字母",
                    "value": [{"n": "🔤 全部", "v": "index"}] + 
                             [{"n": chr(i), "v": chr(i).lower()} for i in range(65, 91)]
                }
            ],
            "mv": [
                {
                    "key": "area",
                    "name": "🌏 地区",
                    "value": [
                        {"n": "🌐 全部地区", "v": "index"},
                        {"n": "🇨🇳 内地", "v": "neidi"},
                        {"n": "🇭🇰 港台", "v": "gangtai"},
                        {"n": "🌍 欧美", "v": "oumei"},
                        {"n": "🇰🇷 韩国", "v": "hanguo"},
                        {"n": "🇯🇵 日本", "v": "riben"}
                    ]
                },
                {
                    "key": "type",
                    "name": "🎬 类型",
                    "value": [
                        {"n": "🎬 全部类型", "v": "index"},
                        {"n": "📀 官方版", "v": "guanfang"},
                        {"n": "🎤 原声", "v": "yuansheng"},
                        {"n": "🎸 现场版", "v": "xianchang"},
                        {"n": "🎮 网易出品", "v": "wangyi"}
                    ]
                },
                {
                    "key": "sort",
                    "name": "📊 排序",
                    "value": [
                        {"n": "✨ 最新", "v": "new"},
                        {"n": "🔥 最热", "v": "hot"},
                        {"n": "📈 上升最快", "v": "rise"}
                    ]
                }
            ],
            "playlist": [
                {
                    "key": "lang",
                    "name": "🌏 语种",
                    "value": [
                        {"n": "🌐 全部语种", "v": "index"},
                        {"n": "🇨🇳 华语", "v": "huayu"},
                        {"n": "🌍 欧美", "v": "oumei"},
                        {"n": "🇯🇵 日语", "v": "riyu"},
                        {"n": "🇰🇷 韩语", "v": "hanyu"},
                        {"n": "🇭🇰 粤语", "v": "yueyu"}
                    ]
                },
                {
                    "key": "style",
                    "name": "🎵 风格",
                    "value": [
                        {"n": "🎵 流行", "v": "liuxing"},
                        {"n": "🎸 摇滚", "v": "yaogun"},
                        {"n": "🎤 民谣", "v": "minyao"},
                        {"n": "⚡ 电子", "v": "dianzi"},
                        {"n": "💃 舞曲", "v": "wuqu"},
                        {"n": "🎤 说唱", "v": "shuochang"},
                        {"n": "🎹 轻音乐", "v": "qingyinle"},
                        {"n": "🎺 爵士", "v": "jueshi"},
                        {"n": "🌾 乡村", "v": "xiangcun"},
                        {"n": "🎭 R&B/Soul", "v": "soul"},
                        {"n": "🎻 古典", "v": "gudian"},
                        {"n": "🏯 古风", "v": "gufeng"}
                    ]
                }
            ]
        }
        
        return {"class": classes, "filters": filters, "list": []}

    # ==================== 首页推荐 ====================
    def homeVideoContent(self):
        try:
            doc = self.getpq("/")
            if not doc or doc.html() == "<html></html>":
                print("⚠️ 首页获取失败，重试一次...")
                time.sleep(1)
                doc = self.getpq("/")
                if not doc or doc.html() == "<html></html>":
                    return {"list": []}
            
            items = []
            seen_ids = set()
            
            # 清空缓存
            self.home_recommend_cache = []
            
            # 1. 网友在听
            for li in doc("#datalist li, .lkmusic_list li, .layui-row.lkbj li").items():
                a = li(".name a.url").eq(0)
                if not a:
                    a = li(".name a").eq(0)
                if not a:
                    a = li("a").eq(0)
                
                href = a.attr("href")
                if not href or "/mp3/" not in href:
                    continue
                
                name = a.text()
                singer = li(".singer").text()
                if not singer:
                    singer_elem = li("p a, .artist a, .author a").eq(0)
                    if singer_elem:
                        singer = singer_elem.text()
                
                pic = li(".pic img").attr("src")
                if not pic:
                    pic = li("img").attr("src")
                if not pic:
                    pic = "https://p2.music.126.net/xxx/song.jpg"
                
                full_name = f"{singer} - {name}" if singer else name
                vod_id = self._abs(href)
                
                if vod_id not in seen_ids:
                    seen_ids.add(vod_id)
                    song_id = href.split('/')[-1].replace('.html', '')
                    
                    # 构建播放URL
                    play_url = f"{self.host}/data/down.php?ac=music&id={song_id}"
                    
                    # 缓存歌曲信息
                    self.home_recommend_cache.append({
                        "vod_id": vod_id,
                        "vod_name": self._clean(full_name),
                        "vod_pic": self._get_image(pic),
                        "vod_remarks": "🎵 正在播放",
                        "song_id": song_id,
                        "singer": singer,
                        "name": name,
                        "play_url": play_url
                    })
                    
                    items.append({
                        "vod_id": vod_id,
                        "vod_name": self._clean(full_name),
                        "vod_pic": self._get_image(pic),
                        "vod_remarks": "🎵 正在播放"
                    })
            
            # 2. 新歌抢先试听
            for li in doc(".ilingkuplay_list li, .play_list li, .song_list li").items():
                a = li(".name a").eq(0)
                if not a:
                    a = li("a").eq(0)
                
                href = a.attr("href")
                if not href or "/mp3/" not in href:
                    continue
                
                name = a.text()
                vod_id = self._abs(href)
                
                if vod_id not in seen_ids:
                    seen_ids.add(vod_id)
                    song_id = href.split('/')[-1].replace('.html', '')
                    
                    # 构建播放URL
                    play_url = f"{self.host}/data/down.php?ac=music&id={song_id}"
                    
                    # 缓存歌曲信息
                    self.home_recommend_cache.append({
                        "vod_id": vod_id,
                        "vod_name": self._clean(name),
                        "vod_pic": "https://p2.music.126.net/xxx/new.jpg",
                        "vod_remarks": "✨ 新歌推荐",
                        "song_id": song_id,
                        "singer": "",
                        "name": name,
                        "play_url": play_url
                    })
                    
                    items.append({
                        "vod_id": vod_id,
                        "vod_name": self._clean(name),
                        "vod_pic": "https://p2.music.126.net/xxx/new.jpg",
                        "vod_remarks": "✨ 新歌推荐"
                    })
            
            # 3. 推荐MV
            for li in doc(".video_list li, .ilingku_list li").items():
                a = li(".name a").eq(0)
                if not a:
                    a = li("a").eq(0)
                
                href = a.attr("href")
                if not href or "/mp4/" not in href:
                    continue
                
                name = a.text()
                pic = li(".pic img").attr("src")
                vod_id = self._abs(href)
                
                if vod_id not in seen_ids:
                    seen_ids.add(vod_id)
                    mv_id = href.split('/')[-1].replace('.html', '')
                    
                    # 构建播放URL
                    play_url = f"{self.host}/data/down.php?ac=vplay&id={mv_id}&q=1080"
                    
                    # 缓存MV信息
                    self.home_recommend_cache.append({
                        "vod_id": vod_id,
                        "vod_name": self._clean(name),
                        "vod_pic": self._get_image(pic, is_mv=True) if pic else "",
                        "vod_remarks": "🎬 MV推荐",
                        "is_mv": True,
                        "mv_id": mv_id,
                        "play_url": play_url
                    })
                    
                    items.append({
                        "vod_id": vod_id,
                        "vod_name": self._clean(name),
                        "vod_pic": self._get_image(pic, is_mv=True) if pic else "",
                        "vod_remarks": "🎬 MV推荐"
                    })
            
            print(f"🏠 首页推荐: 获取到 {len(items)} 个项目，缓存 {len(self.home_recommend_cache)} 个")
            return {"list": items[:60]}
            
        except Exception as e:
            print(f"❌ 首页推荐错误: {e}")
            return {"list": []}

    # ==================== 分类列表 ====================
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        items = []
        
        if tid == "home":
            return self.homeVideoContent()
        
        elif tid == "rank_list":
            # 网易云音乐排行榜封面图片映射
            rank_pics = {
                "rise": "https://p2.music.126.net/sBqYS1rtmY6OUJ3rT_xN4A==/109951166953507139.jpg?param=500y500",
                "new": "https://p2.music.126.net/8Lh8h0tLIn3n7RzvHzY0Wg==/109951166953506369.jpg?param=500y500",
                "original": "https://p2.music.126.net/gHjcNZjLRJwPmgI0oO0c0A==/109951166953507432.jpg?param=500y500",
                "top": "https://p2.music.126.net/Dr7Wwiy-Jq7D7lgX3hZk3A==/109951166953506898.jpg?param=500y500",
                "douyin": "https://p2.music.126.net/_o_bh5iUjO5gNx0fLzlN_w==/109951166953507739.jpg?param=500y500",
                "kuaishou": "https://p2.music.126.net/SCP69gC-x7W1aX8K3fQp2g==/109951166953508058.jpg?param=500y500",
                "zwdj": "https://p2.music.126.net/AeMq1vF46KSxIJ1_Lk7DnA==/109951166953508286.jpg?param=500y500",
                "hot": "https://p2.music.126.net/xB5yPyMqnWktaRk44fUwCQ==/109951166953508516.jpg?param=500y500",
                "japan": "https://p2.music.126.net/NN7gD80fO-FC6D08ZfP6YA==/109951166953508879.jpg?param=500y500",
                "oumei": "https://p2.music.126.net/7G3bJzOtdS5T9C-OynOR6A==/109951166953509153.jpg?param=500y500",
                "korea": "https://p2.music.126.net/RZqN-nhudVw9J6A1FhxY3Q==/109951166953509535.jpg?param=500y500",
                "america": "https://p2.music.126.net/QWzC_wLjJ4vC7__6R3PUFg==/109951166953509853.jpg?param=500y500",
                "acg": "https://p2.music.126.net/Aq-YLyaG0inF8-eBY0e0rw==/109951166953510130.jpg?param=500y500",
                "acgyx": "https://p2.music.126.net/WE0C0US8Z2-6v4kQ8ey8nA==/109951166953510408.jpg?param=500y500",
                "acgdm": "https://p2.music.126.net/n3SlR1n7ZdbQOU5ADK5P4g==/109951166953510646.jpg?param=500y500",
                "omtop": "https://p2.music.126.net/sYpp9uCiY2Fim92O6QZ_Lw==/109951166953510939.jpg?param=500y500",
                "dian": "https://p2.music.126.net/BgK4mI6XKEl4SWqPp7Z4nw==/109951166953511260.jpg?param=500y500",
                "uktop": "https://p2.music.126.net/hIHhU4tVfOL8lyS-fc06WQ==/109951166953511595.jpg?param=500y500",
                "gudian": "https://p2.music.126.net/ZOH6qS52kizTxy8pyY7q2A==/109951166953511895.jpg?param=500y500",
                "raptop": "https://p2.music.126.net/f15S_YcOq6lNpJ4vKzYPPg==/109951166953512238.jpg?param=500y500",
                "dytop": "https://p2.music.126.net/5OYrUqR_HH0N7hSmX7jPBQ==/109951166953512545.jpg?param=500y500",
                "qianli": "https://p2.music.126.net/pZ_BIGjX0T5rq66lA7yS9Q==/109951166953512864.jpg?param=500y500",
                "yytop": "https://p2.music.126.net/Hg-h8E7n2qK9K_4mXm3hJQ==/109951166953513214.jpg?param=500y500",
                "ystop": "https://p2.music.126.net/jQZ5jO99pF5m9r4jBpdgXg==/109951166953513484.jpg?param=500y500",
                "xyztop": "https://p2.music.126.net/XbOH_Cbw38WcZbc0pI33Dw==/109951166953513803.jpg?param=500y500",
                "djtop": "https://p2.music.126.net/Vm4Yq0Yd8SqptpXBPoLLFg==/109951166953514101.jpg?param=500y500",
                "ktvtop": "https://p2.music.126.net/2DjhjJ-19L8vxVlnV5m4wQ==/109951166953514410.jpg?param=500y500",
                "chetop": "https://p2.music.126.net/GMF5Q6bE0VR5d_BWX8a4jQ==/109951166953514699.jpg?param=500y500",
                "aytop": "https://p2.music.126.net/T1HeE3jH9Df12FmXl6ZkOg==/109951166953515018.jpg?param=500y500",
                "sqtop": "https://p2.music.126.net/m1j7GdA6IVs7ZAlfHP_mFg==/109951166953515346.jpg?param=500y500"
            }
            
            rank_list = [
                {"id": "rise", "name": "🔥 音乐飙升榜"},
                {"id": "new", "name": "✨ 新歌排行榜"},
                {"id": "original", "name": "🎸 音乐原创榜"},
                {"id": "top", "name": "🎵 Top热歌榜"},
                {"id": "douyin", "name": "🎶 抖音热歌榜"},
                {"id": "kuaishou", "name": "📱 快手热歌榜"},
                {"id": "zwdj", "name": "💃 中文DJ榜"},
                {"id": "hot", "name": "🌐 网络热歌榜"},
                {"id": "japan", "name": "🗾 日本歌曲榜"},
                {"id": "oumei", "name": "🌍 欧美新歌榜"},
                {"id": "korea", "name": "🇰🇷 韩国音乐榜"},
                {"id": "america", "name": "🇺🇸 美国音乐榜"},
                {"id": "acg", "name": "🎮 ACG新歌榜"},
                {"id": "acgyx", "name": "🕹️ ACG游戏榜"},
                {"id": "acgdm", "name": "📺 ACG动画榜"},
                {"id": "omtop", "name": "🌎 欧美热歌榜"},
                {"id": "dian", "name": "⚡ 电子舞曲榜"},
                {"id": "uktop", "name": "🇬🇧 UK排行榜"},
                {"id": "gudian", "name": "🎻 古典音乐榜"},
                {"id": "raptop", "name": "🎤 RAP说唱榜"},
                {"id": "dytop", "name": "🔊 电音热歌榜"},
                {"id": "qianli", "name": "🚀 潜力热歌榜"},
                {"id": "yytop", "name": "🇭🇰 粤语金曲榜"},
                {"id": "ystop", "name": "🎬 影视金曲榜"},
                {"id": "xyztop", "name": "🌏 小语种热歌"},
                {"id": "djtop", "name": "🔄 串烧舞曲榜"},
                {"id": "ktvtop", "name": "🎤 KTV点唱榜"},
                {"id": "chetop", "name": "🚗 车载嗨曲榜"},
                {"id": "aytop", "name": "🌙 熬夜修仙榜"},
                {"id": "sqtop", "name": "😴 睡前放松榜"}
            ]
            
            start = (pg - 1) * 30
            end = start + 30
            page_items = rank_list[start:end]
            
            for rank in page_items:
                pic = rank_pics.get(rank['id'], "https://p2.music.126.net/xxx/rank_default.jpg?param=500y500")
                items.append({
                    "vod_id": f"rank_{rank['id']}",
                    "vod_name": rank['name'],
                    "vod_pic": pic,
                    "vod_remarks": "📊 点击播放完整榜单",
                    "style": {"type": "rect", "ratio": 1.33}
                })
            
            # 计算总页数
            total_pages = (len(rank_list) + 29) // 30
            
            return {
                "list": items,
                "page": pg,
                "pagecount": total_pages,
                "limit": 30,
                "total": len(rank_list)
            }
        
        elif tid == "playlist":
            lang = extend.get("lang", "index")
            style = extend.get("style", "")
            
            if lang != "index":
                url = f"/playlists/{lang}.html"
            elif style:
                url = f"/playlists/{style}.html"
            else:
                url = "/playlists/index.html"
            
            if pg > 1:
                url = re.sub(r'\.html$', f'/{pg}.html', url)
            
            doc = self.getpq(url)
            for li in doc(".video_list li, .ilingku_list li").items():
                a = li(".name a").eq(0)
                href = a.attr("href")
                if not href or "/playlist/" not in href:
                    continue
                name = a.text()
                pic = li(".pic img").attr("src")
                items.append({
                    "vod_id": self._abs(href),
                    "vod_name": self._clean(name),
                    "vod_pic": self._get_image(pic) if pic else "",
                    "vod_remarks": "📀 歌单",
                    "style": {"type": "rect", "ratio": 1.33}
                })
            
            # 判断是否有下一页
            has_next = bool(doc(".pages a:contains('下一页'), .pagination a:contains('下一页')"))
            
            return {
                "list": items,
                "page": pg,
                "pagecount": pg + 1 if has_next else pg,
                "limit": 30,
                "total": 9999
            }
        
        elif tid == "singer":
            sex = extend.get("sex", "girl")
            area = extend.get("area", "huayu")
            char = extend.get("char", "index")
            
            if char != "index":
                if pg > 1:
                    url = f"/singerlist/{area}/{sex}/{char}/{pg}.html"
                else:
                    url = f"/singerlist/{area}/{sex}/{char}.html"
            else:
                if pg > 1:
                    url = f"/singerlist/{area}/{sex}/index/{pg}.html"
                else:
                    url = f"/singerlist/{area}/{sex}/index.html"
            
            doc = self.getpq(url)
            items = self._parse_singer_list(doc)
            
            # 判断是否有下一页
            has_next = bool(doc(".pages a:contains('下一页'), .pagination a:contains('下一页')"))
            
            return {
                "list": items,
                "page": pg,
                "pagecount": pg + 1 if has_next else pg,
                "limit": 30,
                "total": 9999
            }
        
        elif tid == "mv":
            area = extend.get("area", "index")
            type_ = extend.get("type", "index")
            sort = extend.get("sort", "new")
            
            # 保存当前分类信息，供详情页使用
            self.current_category = {
                "area": area,
                "type": type_,
                "sort": sort,
                "page": pg
            }
            
            # 构建URL
            url = self._build_mv_url(area, type_, sort, pg)
            print(f"🎬 MV URL: {self.host}{url}")
            
            doc = self.getpq(url)
            
            mv_count = 0
            filtered_count = 0
            
            # 定义需要过滤的关键词（采访、广告、访谈等非MV内容）
            filter_keywords = [
                # 采访/访谈类
                '采访', '访谈', '专访', '见面会', '发布会', '记者会',
                '采访', '直播', '现场', '彩排', '后台',
                '综艺', '节目', 'cut', 'CUT', '片段',
                'reaction', 'Reaction', 'REACTION',
                
                # 广告/宣传类
                '广告', '宣传片', '预告', '花絮', '幕后',
                'teaser', 'Teaser', 'TEASER',
                'trailer', 'Trailer', 'TRAILER',
                'promo', 'Promo', 'PROMO',
                'behind', 'Behind', 'BEHIND',
                'making', 'Making', 'MAKING',
                
                # 粉丝拍摄类
                '饭拍', 'FANCAM', 'fancam', 'Fancam', '直拍',
                'focus', 'Focus', 'FOCUS',
                
                # 其他非MV内容
                '采访', '访问', 'talk', 'Talk', 'TALK',
                'skit', 'Skit', 'SKIT',
                'vlog', 'Vlog', 'VLOG',
                'log', 'Log', 'LOG',
                
                # 特别说明
                '采访', '采访视频', '采访片段',
                '广告拍摄', '广告花絮', '广告幕后',
                'MV拍摄花絮', 'MV幕后', 'MV making',
                
                # 可能包含广告的标题
                '特别版', '特别篇', 'SP版',
                'CM', 'CF',
            ]
            
            for li in doc(".video_list li, .play_list li, .ilingku_list li").items():
                a = li(".name a").eq(0)
                if not a:
                    a = li("a.url, a.name, a").eq(0)
                
                href = a.attr("href")
                if not href or "/mp4/" not in href:
                    continue
                
                name = a.text()
                name_original = name
                name = self._clean_song_name(name)
                
                # 检查是否包含过滤关键词
                should_filter = False
                name_lower = name.lower()
                
                for keyword in filter_keywords:
                    if keyword.lower() in name_lower:
                        should_filter = True
                        filtered_count += 1
                        print(f"🎬 过滤非MV内容: {name_original} (包含关键词: {keyword})")
                        break
                
                if should_filter:
                    continue
                
                # 获取歌手信息
                artist = ""
                artist_elem = li(".singer a, .artist a, .author a").eq(0)
                if artist_elem:
                    artist = artist_elem.text()
                else:
                    # 尝试从标题提取歌手
                    artist_match = re.search(r'^(.+?)\s*-\s*(.+)$', name)
                    if artist_match:
                        artist = artist_match.group(1).strip()
                        name = artist_match.group(2).strip()
                
                # 获取封面
                pic = li(".pic img").attr("src")
                if not pic:
                    pic = li("img").attr("src")
                
                # 获取时长
                duration = ""
                duration_elem = li(".duration, .time, .length, .timer")
                if duration_elem:
                    duration = duration_elem.text()
                
                # 获取MV ID
                mv_id = href.split('/')[-1].replace('.html', '')
                
                # 构建备注
                remarks_parts = ["🎬 MV"]
                if artist:
                    remarks_parts.append(artist)
                if duration:
                    remarks_parts.append(duration)
                
                # 构建MV对象
                mv_item = {
                    "vod_id": self._abs(href),
                    "vod_name": name,
                    "vod_pic": self._get_image(pic, is_mv=True) if pic else "https://p2.music.126.net/xxx/mv_default.jpg",
                    "vod_remarks": " · ".join(remarks_parts),
                    "vod_actor": artist,
                    "vod_content": f"🎬 MV · {artist} · {duration}" if duration else f"🎬 MV · {artist}",
                    "style": {"type": "rect", "ratio": 1.78},  # 16:9比例适合MV
                    # 添加分类信息，用于详情页构建播放列表
                    "_mv_id": mv_id,
                    "_area": area,
                    "_type": type_,
                    "_sort": sort,
                    "_artist": artist
                }
                
                items.append(mv_item)
                mv_count += 1
            
            print(f"🎬 MV分类 {area}/{type_}/{sort} 第{pg}页 获取到 {mv_count} 个MV，过滤掉 {filtered_count} 个非MV内容")
            
            # 判断是否有下一页 - 增强判断逻辑
            has_next = self._check_has_next_page(doc)
            
            # 计算总页数
            if has_next:
                # 如果有下一页，设置pagecount为当前页+1，让前端可以继续加载
                pagecount = pg + 1
            else:
                # 如果没有下一页，设置pagecount为当前页
                pagecount = pg
            
            # 获取总条数（估计值）
            total = self._estimate_total_count(doc, mv_count, pg)
            
            print(f"📊 分页信息: 当前页={pg}, 有下一页={has_next}, 总页数={pagecount}, 本页数量={mv_count}")
            
            return {
                "list": items,
                "page": pg,
                "pagecount": pagecount,
                "limit": 30,
                "total": total
            }
        
        return {
            "list": items,
            "page": pg,
            "pagecount": 999,
            "limit": 30,
            "total": 9999
        }

    def _check_has_next_page(self, doc):
        """检查是否有下一页 - 增强版"""
        # 方法1: 查找下一页链接
        next_selectors = [
            ".pages a:contains('下一页')",
            ".pagination a:contains('下一页')",
            ".page a:contains('下一页')",
            ".pages a:contains('下页')",
            ".pagination a:contains('下页')",
            ".pages .next",
            ".pagination .next",
            "a:contains('下一页')",
            "a:contains('下页')"
        ]
        
        for selector in next_selectors:
            next_link = doc(selector)
            if next_link:
                # 检查链接是否有效（不是禁用状态）
                if not next_link.has_class("disabled") and not next_link.has_class("disable"):
                    href = next_link.attr("href")
                    if href and href != "#" and href != "javascript:void(0)":
                        return True
        
        # 方法2: 检查是否有页码大于当前页
        page_numbers = []
        for a in doc(".pages a, .pagination a, .page a").items():
            text = a.text().strip()
            if text.isdigit():
                page_numbers.append(int(text))
        
        if page_numbers:
            max_page = max(page_numbers)
            current_page = self._get_current_page(doc)
            if max_page > current_page:
                return True
        
        # 方法3: 检查是否有"末页"或"最后一页"链接
        last_selectors = [
            ".pages a:contains('末页')",
            ".pagination a:contains('末页')",
            ".pages a:contains('最后')",
            ".pagination a:contains('最后')"
        ]
        
        for selector in last_selectors:
            last_link = doc(selector)
            if last_link:
                href = last_link.attr("href")
                if href and href != "#" and href != "javascript:void(0)":
                    return True
        
        return False

    def _get_current_page(self, doc):
        """获取当前页码"""
        # 方法1: 查找当前高亮的页码
        for a in doc(".pages .current, .pagination .current, .page .current, .pages .active, .pagination .active").items():
            text = a.text().strip()
            if text.isdigit():
                return int(text)
        
        # 方法2: 从所有页码中推断
        page_numbers = []
        for a in doc(".pages a, .pagination a, .page a").items():
            text = a.text().strip()
            if text.isdigit():
                page_numbers.append(int(text))
        
        if page_numbers:
            # 通常当前页是第一个或中间某个
            return page_numbers[0] if page_numbers else 1
        
        return 1

    def _estimate_total_count(self, doc, current_count, current_page):
        """估计总条数"""
        # 方法1: 从分页信息中提取
        page_info = doc(".pages, .pagination, .page").text()
        
        # 匹配"共XX条"或"共XX页"
        total_match = re.search(r'共(\d+)条', page_info)
        if total_match:
            return int(total_match.group(1))
        
        pages_match = re.search(r'共(\d+)页', page_info)
        if pages_match:
            total_pages = int(pages_match.group(1))
            return total_pages * 30  # 估计每页30条
        
        # 方法2: 从页码数量推断
        page_numbers = []
        for a in doc(".pages a, .pagination a, .page a").items():
            text = a.text().strip()
            if text.isdigit():
                page_numbers.append(int(text))
        
        if page_numbers:
            max_page = max(page_numbers)
            return max_page * 30
        
        # 方法3: 如果当前页数量少于30，可能是最后一页
        if current_count < 30:
            return (current_page - 1) * 30 + current_count
        
        # 默认返回一个大数，让前端可以继续加载
        return 9999

    def _build_mv_url(self, area, type_, sort, pg):
        """构建MV分类URL"""
        area_map = {
            "index": "index",
            "neidi": "neidi",
            "gangtai": "gangtai",
            "oumei": "oumei",
            "hanguo": "hanguo",
            "riben": "riben"
        }
        
        type_map = {
            "index": "index",
            "guanfang": "guanfang",
            "yuansheng": "yuansheng",
            "xianchang": "xianchang",
            "wangyi": "wangyi"
        }
        
        sort_map = {
            "new": "new",
            "hot": "hot",
            "rise": "rise"
        }
        
        area_val = area_map.get(area, "index")
        type_val = type_map.get(type_, "index")
        sort_val = sort_map.get(sort, "new")
        
        if pg == 1:
            if area_val == "index" and type_val == "index":
                return f"/mvlist/index/index/{sort_val}.html"
            elif area_val != "index" and type_val == "index":
                return f"/mvlist/{area_val}/index/{sort_val}.html"
            elif area_val == "index" and type_val != "index":
                return f"/mvlist/index/{type_val}/{sort_val}.html"
            else:
                return f"/mvlist/{area_val}/{type_val}/{sort_val}.html"
        else:
            if area_val == "index" and type_val == "index":
                return f"/mvlist/index/index/{sort_val}/{pg}.html"
            elif area_val != "index" and type_val == "index":
                return f"/mvlist/{area_val}/index/{sort_val}/{pg}.html"
            elif area_val == "index" and type_val != "index":
                return f"/mvlist/index/{type_val}/{sort_val}/{pg}.html"
            else:
                return f"/mvlist/{area_val}/{type_val}/{sort_val}/{pg}.html"

    # ==================== 搜索 ====================
    def searchContent(self, key, quick, pg="1"):
        url = f"/so.php?wd={quote(key)}&page={pg}"
        doc = self.getpq(url)
        items = []
        for li in doc(".play_list li, .video_list li").items():
            a = li(".name a").eq(0)
            if not (href := a.attr("href")):
                continue
            name = a.text()
            pic = li("img").attr("src") or ""
            if "/mp3/" in href:
                remarks = "🎵 歌曲"
                style = {"type": "rect", "ratio": 1.33}
            elif "/mp4/" in href:
                remarks = "🎬 MV"
                style = {"type": "rect", "ratio": 1.78}
            elif "/playlist/" in href:
                remarks = "📀 歌单"
                style = {"type": "rect", "ratio": 1.33}
            else:
                remarks = "👤 歌手"
                style = {"type": "oval", "ratio": 1}
            items.append({
                "vod_id": self._abs(href),
                "vod_name": self._clean(name),
                "vod_pic": self._get_image(pic, is_singer=(remarks=="👤 歌手"), is_mv=(remarks=="🎬 MV")) if pic else "",
                "vod_remarks": remarks,
                "style": style
            })
        
        # 判断是否有下一页
        has_next = bool(doc(".pages a:contains('下一页'), .pagination a:contains('下一页')"))
        pagecount = int(pg) + 1 if has_next else int(pg)
        
        return {
            "list": items,
            "page": int(pg),
            "pagecount": pagecount,
            "limit": 30,
            "total": 9999
        }

    # ==================== 详情页 ====================
    def detailContent(self, ids):
        url = self._abs(ids[0])
        
        # 处理排行榜
        if "rank_" in url:
            rank_type = url.replace("rank_", "").replace(self.host, "").replace("/", "")
            return self._get_rank_detail(rank_type, url)
        
        # 处理首页推荐 - 如果url在缓存中，使用缓存信息
        for cached_item in self.home_recommend_cache:
            if cached_item["vod_id"] == url:
                print(f"🏠 使用首页推荐缓存: {cached_item['vod_name']}")
                return self._get_home_recommend_detail(cached_item, url)
        
        # 处理MV
        if "/mp4/" in url:
            doc = self.getpq(url)
            return self._get_mv_detail_with_playlist(doc, url)
        
        # 处理歌曲
        if "/mp3/" in url:
            doc = self.getpq(url)
            return self._get_song_detail_with_playlist(doc, url)
        
        # 处理歌手
        if "/singer/" in url:
            doc = self.getpq(url)
            title = self._clean(doc("h1").text() or doc("title").text().split('_')[0])
            pic = doc(".singer_info .pic img").eq(0).attr("src") or doc(".pic img").eq(0).attr("src")
            if pic:
                pic = pic.replace('param=200y200', 'param=500y500')
            
            vod = {
                "vod_id": url,
                "vod_name": f"👤 {title}",
                "vod_pic": self._get_image(pic, is_singer=True) if pic else "",
                "vod_content": self._get_content(doc, url)
            }
            vod.update(self._get_singer_detail(doc, url))
            return {"list": [vod]}
        
        # 处理歌单
        if "/playlist/" in url:
            doc = self.getpq(url)
            title = self._clean(doc("h1").text() or doc("title").text().split('_')[0])
            pic = doc(".video_list .pic img").eq(0).attr("src") or doc(".pic img").eq(0).attr("src")
            
            vod = {
                "vod_id": url,
                "vod_name": f"📀 {title}",
                "vod_pic": self._get_image(pic) if pic else "",
                "vod_content": self._get_content(doc, url)
            }
            vod.update(self._get_playlist_songs(doc))
            vod["vod_play_from"] = "📀 歌单"
            return {"list": [vod]}
        
        # 默认处理
        doc = self.getpq(url)
        title = self._clean(doc("h1").text() or doc("title").text().split('_')[0])
        pic = doc(".playhimg img").eq(0).attr("src") or doc(".djpic img").eq(0).attr("src") or doc(".pic img").eq(0).attr("src")
        
        vod = {
            "vod_id": url,
            "vod_name": title,
            "vod_pic": self._get_image(pic) if pic else "",
            "vod_content": self._get_content(doc, url)
        }
        
        return {"list": [vod]}

    def _get_rank_detail(self, rank_type, url):
        """处理排行榜详情 - 使用网易云音乐的封面图片"""
        
        # 网易云音乐排行榜封面图片映射
        rank_pics = {
            "rise": "https://p2.music.126.net/sBqYS1rtmY6OUJ3rT_xN4A==/109951166953507139.jpg?param=500y500",
            "new": "https://p2.music.126.net/8Lh8h0tLIn3n7RzvHzY0Wg==/109951166953506369.jpg?param=500y500",
            "original": "https://p2.music.126.net/gHjcNZjLRJwPmgI0oO0c0A==/109951166953507432.jpg?param=500y500",
            "top": "https://p2.music.126.net/Dr7Wwiy-Jq7D7lgX3hZk3A==/109951166953506898.jpg?param=500y500",
            "douyin": "https://p2.music.126.net/_o_bh5iUjO5gNx0fLzlN_w==/109951166953507739.jpg?param=500y500",
            "kuaishou": "https://p2.music.126.net/SCP69gC-x7W1aX8K3fQp2g==/109951166953508058.jpg?param=500y500",
            "zwdj": "https://p2.music.126.net/AeMq1vF46KSxIJ1_Lk7DnA==/109951166953508286.jpg?param=500y500",
            "hot": "https://p2.music.126.net/xB5yPyMqnWktaRk44fUwCQ==/109951166953508516.jpg?param=500y500",
            "japan": "https://p2.music.126.net/NN7gD80fO-FC6D08ZfP6YA==/109951166953508879.jpg?param=500y500",
            "oumei": "https://p2.music.126.net/7G3bJzOtdS5T9C-OynOR6A==/109951166953509153.jpg?param=500y500",
            "korea": "https://p2.music.126.net/RZqN-nhudVw9J6A1FhxY3Q==/109951166953509535.jpg?param=500y500",
            "america": "https://p2.music.126.net/QWzC_wLjJ4vC7__6R3PUFg==/109951166953509853.jpg?param=500y500",
            "acg": "https://p2.music.126.net/Aq-YLyaG0inF8-eBY0e0rw==/109951166953510130.jpg?param=500y500",
            "acgyx": "https://p2.music.126.net/WE0C0US8Z2-6v4kQ8ey8nA==/109951166953510408.jpg?param=500y500",
            "acgdm": "https://p2.music.126.net/n3SlR1n7ZdbQOU5ADK5P4g==/109951166953510646.jpg?param=500y500",
            "omtop": "https://p2.music.126.net/sYpp9uCiY2Fim92O6QZ_Lw==/109951166953510939.jpg?param=500y500",
            "dian": "https://p2.music.126.net/BgK4mI6XKEl4SWqPp7Z4nw==/109951166953511260.jpg?param=500y500",
            "uktop": "https://p2.music.126.net/hIHhU4tVfOL8lyS-fc06WQ==/109951166953511595.jpg?param=500y500",
            "gudian": "https://p2.music.126.net/ZOH6qS52kizTxy8pyY7q2A==/109951166953511895.jpg?param=500y500",
            "raptop": "https://p2.music.126.net/f15S_YcOq6lNpJ4vKzYPPg==/109951166953512238.jpg?param=500y500",
            "dytop": "https://p2.music.126.net/5OYrUqR_HH0N7hSmX7jPBQ==/109951166953512545.jpg?param=500y500",
            "qianli": "https://p2.music.126.net/pZ_BIGjX0T5rq66lA7yS9Q==/109951166953512864.jpg?param=500y500",
            "yytop": "https://p2.music.126.net/Hg-h8E7n2qK9K_4mXm3hJQ==/109951166953513214.jpg?param=500y500",
            "ystop": "https://p2.music.126.net/jQZ5jO99pF5m9r4jBpdgXg==/109951166953513484.jpg?param=500y500",
            "xyztop": "https://p2.music.126.net/XbOH_Cbw38WcZbc0pI33Dw==/109951166953513803.jpg?param=500y500",
            "djtop": "https://p2.music.126.net/Vm4Yq0Yd8SqptpXBPoLLFg==/109951166953514101.jpg?param=500y500",
            "ktvtop": "https://p2.music.126.net/2DjhjJ-19L8vxVlnV5m4wQ==/109951166953514410.jpg?param=500y500",
            "chetop": "https://p2.music.126.net/GMF5Q6bE0VR5d_BWX8a4jQ==/109951166953514699.jpg?param=500y500",
            "aytop": "https://p2.music.126.net/T1HeE3jH9Df12FmXl6ZkOg==/109951166953515018.jpg?param=500y500",
            "sqtop": "https://p2.music.126.net/m1j7GdA6IVs7ZAlfHP_mFg==/109951166953515346.jpg?param=500y500"
        }
        
        # 排行榜名称映射
        rank_names = {
            "rise": "🔥 音乐飙升榜",
            "new": "✨ 新歌排行榜",
            "original": "🎸 音乐原创榜",
            "top": "🎵 Top热歌榜",
            "douyin": "🎶 抖音热歌榜",
            "kuaishou": "📱 快手热歌榜",
            "zwdj": "💃 中文DJ榜",
            "hot": "🌐 网络热歌榜",
            "japan": "🗾 日本歌曲榜",
            "oumei": "🌍 欧美新歌榜",
            "korea": "🇰🇷 韩国音乐榜",
            "america": "🇺🇸 美国音乐榜",
            "acg": "🎮 ACG新歌榜",
            "acgyx": "🕹️ ACG游戏榜",
            "acgdm": "📺 ACG动画榜",
            "omtop": "🌎 欧美热歌榜",
            "dian": "⚡ 电子舞曲榜",
            "uktop": "🇬🇧 UK排行榜",
            "gudian": "🎻 古典音乐榜",
            "raptop": "🎤 RAP说唱榜",
            "dytop": "🔊 电音热歌榜",
            "qianli": "🚀 潜力热歌榜",
            "yytop": "🇭🇰 粤语金曲榜",
            "ystop": "🎬 影视金曲榜",
            "xyztop": "🌏 小语种热歌",
            "djtop": "🔄 串烧舞曲榜",
            "ktvtop": "🎤 KTV点唱榜",
            "chetop": "🚗 车载嗨曲榜",
            "aytop": "🌙 熬夜修仙榜",
            "sqtop": "😴 睡前放松榜"
        }
        
        rank_name = rank_names.get(rank_type, f"排行榜 {rank_type}")
        rank_pic = rank_pics.get(rank_type, "https://p2.music.126.net/xxx/rank_default.jpg?param=500y500")
        
        playlist = self._get_rank_playlist(rank_type)
        
        if playlist:
            song_count = len(playlist.split('#'))
            vod = {
                "vod_id": url,
                "vod_name": rank_name,
                "vod_pic": rank_pic,
                "vod_content": f"{rank_name} · 共{song_count}首歌曲\n\n网易云音乐风格封面",
                "vod_play_from": "📊 排行榜",
                "vod_play_url": playlist
            }
        else:
            vod = {
                "vod_id": url,
                "vod_name": rank_name,
                "vod_pic": rank_pic,
                "vod_content": f"{rank_name} · 暂无歌曲\n\n网易云音乐风格封面",
                "vod_play_from": "📊 排行榜",
                "vod_play_url": f"暂无歌曲${self.e64('0@@@@' + self.host)}"
            }
        
        return {"list": [vod]}

    def _get_home_recommend_detail(self, cached_item, url):
        """处理首页推荐详情"""
        if cached_item.get("is_mv"):
            # 如果是MV，获取MV详情
            doc = self.getpq(url)
            return self._get_mv_detail_with_playlist(doc, url)
        else:
            # 如果是歌曲，创建播放列表
            song_name = cached_item.get("name", "")
            singer = cached_item.get("singer", "")
            play_url = cached_item.get("play_url", "")
            
            if not play_url:
                # 如果没有缓存的播放URL，尝试从页面获取
                doc = self.getpq(url)
                song_id = re.search(r'/mp3/([^/]+)\.html', url)
                if song_id:
                    song_id = song_id.group(1)
                    play_url = f"{self.host}/data/down.php?ac=music&id={song_id}"
            
            # 创建播放列表 - 当前歌曲优先
            display_name = f"{singer} - {song_name}" if singer else song_name
            playlist = [f"{display_name}${self.e64('0@@@@' + play_url)}"]
            
            # 获取首页推荐的其他歌曲作为播放列表
            for item in self.home_recommend_cache:
                if item.get("vod_id") != url and not item.get("is_mv"):
                    other_play_url = item.get("play_url", "")
                    other_song_name = item.get("name", "")
                    other_singer = item.get("singer", "")
                    
                    if other_play_url:
                        other_display = f"{other_singer} - {other_song_name}" if other_singer else other_song_name
                        playlist.append(f"{other_display}${self.e64('0@@@@' + other_play_url)}")
            
            # 如果不够，再获取热门歌曲
            if len(playlist) < 20:
                hot_songs = self._get_hot_song_playlist(limit=30-len(playlist))
                if hot_songs:
                    playlist.extend(hot_songs)
            
            # 去重
            unique_playlist = []
            seen_urls = set()
            for item in playlist:
                parts = item.split('$')
                if len(parts) >= 2:
                    url_part = parts[-1]
                    if url_part not in seen_urls:
                        seen_urls.add(url_part)
                        unique_playlist.append(item)
            
            play_url_str = "#".join(unique_playlist)
            
            vod = {
                "vod_id": url,
                "vod_name": f"🎵 {cached_item['vod_name']}",
                "vod_pic": cached_item["vod_pic"],
                "vod_content": f"🎵 首页推荐 · {cached_item['vod_name']}\n共{len(unique_playlist)}首歌曲循环播放",
                "vod_play_from": "🎵 首页推荐播放列表",
                "vod_play_url": play_url_str,
                "vod_actor": singer
            }
            
            return {"list": [vod]}

    def _get_hot_song_playlist(self, exclude_id=None, limit=30):
        """获取热门歌曲播放列表"""
        playlist = []
        
        # 尝试获取热门歌曲 - 使用飙升榜作为热门歌曲来源
        try:
            url = "/list/rise.html"  # 使用飙升榜
            doc = self.getpq(url)
            
            for li in doc(".play_list li").items():
                if len(playlist) >= limit:
                    break
                
                a = li(".name a").eq(0)
                if not a:
                    continue
                
                href = a.attr("href")
                if not href or "/mp3/" not in href:
                    continue
                
                if exclude_id and exclude_id in href:
                    continue
                
                name = a.text()
                name = self._clean_song_name(name)
                
                # 获取歌手信息
                artist = ""
                artist_elem = li(".singer a, .artist a").eq(0)
                if artist_elem:
                    artist = artist_elem.text()
                else:
                    artist_match = re.search(r'^(.+?)\s*-\s*', name)
                    if artist_match:
                        artist = artist_match.group(1).strip()
                        name = name.replace(artist + " - ", "")
                
                display_name = f"{artist} - {name}" if artist else name
                song_id = href.split('/')[-1].replace('.html', '')
                play_url = f"{self.host}/data/down.php?ac=music&id={song_id}"
                
                playlist.append(f"{display_name}${self.e64('0@@@@' + play_url)}")
        except Exception as e:
            print(f"❌ 获取热门歌曲失败: {e}")
        
        return playlist

    def _get_rank_playlist(self, rank_type):
        eps = []
        url = f"/list/{rank_type}.html"
        
        try:
            doc = self.getpq(url)
            for li in doc(".play_list li").items():
                a = li(".name a").eq(0)
                if not (href := a.attr("href")):
                    continue
                if "/mp3/" in href:
                    name = a.text()
                    name = self._clean_song_name(name)
                    song_id = href.split('/')[-1].replace('.html', '')
                    play_url = f"{self.host}/data/down.php?ac=music&id={song_id}"
                    eps.append(f"{name}${self.e64('0@@@@' + play_url)}")
            
            try:
                url2 = f"/list/{rank_type}/2.html"
                doc2 = self.getpq(url2)
                for li in doc2(".play_list li").items():
                    a = li(".name a").eq(0)
                    if not (href := a.attr("href")):
                        continue
                    if "/mp3/" in href:
                        name = a.text()
                        name = self._clean_song_name(name)
                        song_id = href.split('/')[-1].replace('.html', '')
                        play_url = f"{self.host}/data/down.php?ac=music&id={song_id}"
                        eps.append(f"{name}${self.e64('0@@@@' + play_url)}")
            except:
                pass
        except:
            return None
        
        return "#".join(eps) if eps else None

    # ==================== MV详情与播放列表 - 修复版（从当前MV开始按分类顺序播放） ====================
    def _get_mv_detail_with_playlist(self, doc, url):
        """获取MV详情并创建当前分类播放列表 - 从当前MV开始按分类顺序播放"""
        # 获取当前MV信息
        video_id = re.search(r'/mp4/([^/]+)\.html', url)
        video_id = video_id.group(1) if video_id else ""
        
        name = self._clean(doc("h1").text() or "当前MV")
        name = self._clean_song_name(name)
        
        # 获取歌手信息
        artist = ""
        artist_elem = doc(".play_singer .name a, .singer_info .name a, .artist a").eq(0)
        if artist_elem:
            artist = artist_elem.text()
        else:
            artist_match = re.search(r'^(.+?)\s*-\s*', name)
            if artist_match:
                artist = artist_match.group(1).strip()
                name = name.replace(artist + " - ", "")
        
        # 获取封面
        pic = doc(".video_list .pic img").eq(0).attr("src") or doc(".pic img").eq(0).attr("src") or doc(".playhimg img").eq(0).attr("src")
        
        # 获取当前MV的播放URL
        current_play_url = f"{self.host}/data/down.php?ac=vplay&id={video_id}&q=1080"
        print(f"🎬 当前MV播放URL: {current_play_url}")
        
        # 获取当前分类信息
        area = self.current_category.get("area", "index")
        type_ = self.current_category.get("type", "index")
        sort = self.current_category.get("sort", "hot")
        current_page = self.current_category.get("page", 1)
        
        print(f"🎬 当前分类: 地区={area}, 类型={type_}, 排序={sort}, 当前页={current_page}")
        
        # 定义过滤关键词（在详情页中也过滤）
        filter_keywords = [
            '采访', '访谈', '专访', '见面会', '发布会', '记者会',
            '采访', '直播', '现场', '彩排', '后台',
            '综艺', '节目', 'cut', 'CUT', '片段',
            'reaction', 'Reaction', 'REACTION',
            '广告', '宣传片', '预告', '花絮', '幕后',
            'teaser', 'Teaser', 'TEASER',
            'trailer', 'Trailer', 'TRAILER',
            'promo', 'Promo', 'PROMO',
            'behind', 'Behind', 'BEHIND',
            'making', 'Making', 'MAKING',
            '饭拍', 'FANCAM', 'fancam', 'Fancam', '直拍',
            'focus', 'Focus', 'FOCUS',
            '采访', '访问', 'talk', 'Talk', 'TALK',
            'skit', 'Skit', 'SKIT',
            'vlog', 'Vlog', 'VLOG',
            'log', 'Log', 'LOG',
            '采访视频', '采访片段',
            '广告拍摄', '广告花絮', '广告幕后',
            'MV拍摄花絮', 'MV幕后', 'MV making',
            '特别版', '特别篇', 'SP版',
            'CM', 'CF',
        ]
        
        # 获取分类页面的所有MV（多页）
        all_mvs = []
        
        # 先获取当前页及之后页面的MV（包括当前页）
        for page in range(current_page, 10):  # 最多获取10页
            if len(all_mvs) >= 150:  # 最多150个MV
                break
                
            page_url = self._build_mv_url(area, type_, sort, page)
            print(f"🎬 获取第{page}页MV: {page_url}")
            page_doc = self.getpq(page_url)
            
            if not page_doc or page_doc.html() == "<html></html>":
                break
            
            page_mvs = []
            for li in page_doc(".video_list li, .play_list li").items():
                a = li(".name a").eq(0)
                if not a:
                    continue
                
                href = a.attr("href")
                if not href or "/mp4/" not in href:
                    continue
                
                mv_name = a.text()
                mv_name_original = mv_name
                mv_name = self._clean_song_name(mv_name)
                
                # 检查是否包含过滤关键词
                should_filter = False
                mv_name_lower = mv_name.lower()
                
                for keyword in filter_keywords:
                    if keyword.lower() in mv_name_lower:
                        should_filter = True
                        print(f"🎬 过滤非MV内容（详情页）: {mv_name_original} (包含关键词: {keyword})")
                        break
                
                if should_filter:
                    continue
                
                # 获取歌手信息
                mv_artist = ""
                artist_elem = li(".singer a, .artist a").eq(0)
                if artist_elem:
                    mv_artist = artist_elem.text()
                else:
                    artist_match = re.search(r'^(.+?)\s*-\s*', mv_name)
                    if artist_match:
                        mv_artist = artist_match.group(1).strip()
                        mv_name = mv_name.replace(mv_artist + " - ", "")
                
                # 显示格式: 歌手 - 歌名 (如果有歌手)
                display_name = f"{mv_artist} - {mv_name}" if mv_artist else mv_name
                
                mv_id = href.split('/')[-1].replace('.html', '')
                play_url = f"{self.host}/data/down.php?ac=vplay&id={mv_id}&q=1080"
                
                page_mvs.append({
                    "name": display_name,
                    "play_url": play_url,
                    "href": href,
                    "id": mv_id
                })
            
            print(f"🎬 第{page}页获取到 {len(page_mvs)} 个MV（过滤后）")
            
            if page == current_page:
                # 在当前页中，找到当前MV的位置
                current_index = -1
                for i, mv in enumerate(page_mvs):
                    if mv["id"] == video_id:
                        current_index = i
                        break
                
                if current_index >= 0:
                    # 从当前MV开始，添加当前页的剩余MV
                    for mv in page_mvs[current_index:]:
                        all_mvs.append(f"{mv['name']}${self.e64('0@@@@' + mv['play_url'])}")
                    print(f"🎬 从当前页第{current_index+1}个MV开始添加")
                else:
                    # 如果没找到当前MV（可能是跨页的情况），添加所有MV
                    for mv in page_mvs:
                        all_mvs.append(f"{mv['name']}${self.e64('0@@@@' + mv['play_url'])}")
                    print(f"🎬 未找到当前MV，添加当前页所有MV")
            else:
                # 后续页面，添加所有MV
                for mv in page_mvs:
                    all_mvs.append(f"{mv['name']}${self.e64('0@@@@' + mv['play_url'])}")
            
            # 检查是否有下一页
            has_next = self._check_has_next_page(page_doc)
            if not has_next:
                print(f"🎬 第{page}页没有下一页，停止获取")
                break
        
        # 如果当前页及之后页的MV不够，再获取之前的页面（为了循环播放）
        if len(all_mvs) < 50:
            print(f"🎬 当前页及之后页MV不足（{len(all_mvs)}个），获取之前页面的MV")
            for page in range(current_page - 1, 0, -1):
                if len(all_mvs) >= 150:
                    break
                    
                page_url = self._build_mv_url(area, type_, sort, page)
                print(f"🎬 获取第{page}页MV（之前页）: {page_url}")
                page_doc = self.getpq(page_url)
                
                if not page_doc or page_doc.html() == "<html></html>":
                    continue
                
                page_mvs = []
                for li in page_doc(".video_list li, .play_list li").items():
                    a = li(".name a").eq(0)
                    if not a:
                        continue
                    
                    href = a.attr("href")
                    if not href or "/mp4/" not in href:
                        continue
                    
                    mv_name = a.text()
                    mv_name_original = mv_name
                    mv_name = self._clean_song_name(mv_name)
                    
                    # 检查是否包含过滤关键词
                    should_filter = False
                    mv_name_lower = mv_name.lower()
                    
                    for keyword in filter_keywords:
                        if keyword.lower() in mv_name_lower:
                            should_filter = True
                            print(f"🎬 过滤非MV内容（详情页-之前页）: {mv_name_original} (包含关键词: {keyword})")
                            break
                    
                    if should_filter:
                        continue
                    
                    # 获取歌手信息
                    mv_artist = ""
                    artist_elem = li(".singer a, .artist a").eq(0)
                    if artist_elem:
                        mv_artist = artist_elem.text()
                    else:
                        artist_match = re.search(r'^(.+?)\s*-\s*', mv_name)
                        if artist_match:
                            mv_artist = artist_match.group(1).strip()
                            mv_name = mv_name.replace(mv_artist + " - ", "")
                    
                    display_name = f"{mv_artist} - {mv_name}" if mv_artist else mv_name
                    
                    mv_id = href.split('/')[-1].replace('.html', '')
                    play_url = f"{self.host}/data/down.php?ac=vplay&id={mv_id}&q=1080"
                    
                    page_mvs.insert(0, {
                        "name": display_name,
                        "play_url": play_url,
                        "href": href,
                        "id": mv_id
                    })
                
                print(f"🎬 第{page}页获取到 {len(page_mvs)} 个MV（之前页-过滤后）")
                
                # 添加到all_mvs前面（保持顺序）
                temp_list = []
                for mv in page_mvs:
                    temp_list.append(f"{mv['name']}${self.e64('0@@@@' + mv['play_url'])}")
                all_mvs = temp_list + all_mvs
        
        # 去重（基于URL）
        unique_playlist = []
        seen_urls = set()
        
        # 确保当前MV在第一个位置（如果还没添加的话）
        current_mv_entry = f"{name}${self.e64('0@@@@' + current_play_url)}"
        current_url_part = self.e64('0@@@@' + current_play_url)
        seen_urls.add(current_url_part)
        unique_playlist.append(current_mv_entry)
        
        # 添加其他MV，避免重复
        for item in all_mvs:
            parts = item.split('$')
            if len(parts) >= 2:
                url_part = parts[-1]
                if url_part not in seen_urls and url_part != current_url_part:
                    seen_urls.add(url_part)
                    unique_playlist.append(item)
        
        print(f"🎬 最终播放列表: {len(unique_playlist)} 个MV（从当前MV开始，按分类顺序，已过滤非MV内容）")
        
        # 确保播放列表能自动刷新 - 设置正确的vod_play_url格式
        play_url_str = "#".join(unique_playlist)
        
        # 获取分类显示名称
        area_names = {"index": "全部", "neidi": "内地", "gangtai": "港台", "oumei": "欧美", "hanguo": "韩国", "riben": "日本"}
        type_names = {"index": "全部", "guanfang": "官方版", "yuansheng": "原声", "xianchang": "现场版", "wangyi": "网易出品"}
        sort_names = {"new": "最新", "hot": "最热", "rise": "上升最快"}
        
        area_name = area_names.get(area, area)
        type_name = type_names.get(type_, type_)
        sort_name = sort_names.get(sort, sort)
        
        vod = {
            "vod_id": url,
            "vod_name": f"🎬 {name}",
            "vod_pic": self._get_image(pic, is_mv=True) if pic else "",
            "vod_actor": artist,
            "vod_content": f"🎬 MV · {artist} · 共{len(unique_playlist)}个MV循环播放\n\n当前分类：{area_name}/{type_name}/{sort_name}",
            "vod_play_from": "🎬 MV播放列表",
            "vod_play_url": play_url_str
        }
        
        return {"list": [vod]}

    def _get_all_category_mvs(self, area, type_, sort, exclude_id=None, max_pages=3):
        """获取分类页面的所有MV（多页）"""
        playlist = []
        
        for page in range(1, max_pages + 1):
            if len(playlist) >= 50:  # 最多50个MV
                break
                
            url = self._build_mv_url(area, type_, sort, page)
            doc = self.getpq(url)
            
            page_count = 0
            for li in doc(".video_list li, .play_list li").items():
                if len(playlist) >= 50:
                    break
                
                a = li(".name a").eq(0)
                if not a:
                    continue
                
                href = a.attr("href")
                if not href or "/mp4/" not in href:
                    continue
                
                # 排除当前MV
                if exclude_id and exclude_id in href:
                    continue
                
                mv_name = a.text()
                mv_name = self._clean_song_name(mv_name)
                
                # 获取歌手信息用于显示
                artist = ""
                artist_elem = li(".singer a, .artist a").eq(0)
                if artist_elem:
                    artist = artist_elem.text()
                else:
                    artist_match = re.search(r'^(.+?)\s*-\s*', mv_name)
                    if artist_match:
                        artist = artist_match.group(1).strip()
                        mv_name = mv_name.replace(artist + " - ", "")
                
                # 显示格式: 歌手 - 歌名 (如果有歌手)
                display_name = f"{artist} - {mv_name}" if artist else mv_name
                
                mv_id = href.split('/')[-1].replace('.html', '')
                play_url = f"{self.host}/data/down.php?ac=vplay&id={mv_id}&q=1080"
                
                playlist.append(f"{display_name}${self.e64('0@@@@' + play_url)}")
                page_count += 1
            
            print(f"🎬 第{page}页获取到 {page_count} 个MV")
            
            # 检查是否有下一页
            has_next = self._check_has_next_page(doc)
            if not has_next:
                break
        
        return playlist

    def _get_singer_all_mvs(self, artist, exclude_id=None, max_pages=2):
        """获取同歌手的所有MV（多页）"""
        playlist = []
        
        # 先搜索歌手
        search_url = f"/so.php?wd={quote(artist)}&page=1"
        doc = self.getpq(search_url)
        
        # 查找歌手页面
        singer_url = None
        for a in doc("a[href*='/singer/']").items():
            if artist in a.text():
                singer_url = a.attr("href")
                break
        
        if not singer_url:
            return playlist
        
        singer_url = self._abs(singer_url)
        singer_doc = self.getpq(singer_url)
        
        # 查找MV链接
        mv_url = None
        for a in singer_doc(".ilingku_fl a, .nav a, .tag a").items():
            text = a.text()
            if '视频' in text or 'MV' in text or 'mv' in text.lower():
                mv_url = a.attr("href")
                break
        
        if not mv_url:
            return playlist
        
        mv_url = self._abs(mv_url)
        
        # 获取多页MV
        for page in range(1, max_pages + 1):
            if len(playlist) >= 30:
                break
                
            page_url = mv_url
            if page > 1:
                # 尝试构建分页URL
                page_url = re.sub(r'\.html$', f'/{page}.html', mv_url)
            
            mv_doc = self.getpq(page_url)
            
            page_count = 0
            for li in mv_doc(".video_list li, .play_list li").items():
                if len(playlist) >= 30:
                    break
                
                a = li(".name a").eq(0)
                if not a:
                    continue
                
                href = a.attr("href")
                if not href or "/mp4/" not in href:
                    continue
                
                if exclude_id and exclude_id in href:
                    continue
                
                mv_name = a.text()
                mv_name = self._clean_song_name(mv_name)
                
                # 如果歌名不含歌手，添加上
                if artist not in mv_name:
                    mv_name = f"{artist} - {mv_name}"
                
                mv_id = href.split('/')[-1].replace('.html', '')
                play_url = f"{self.host}/data/down.php?ac=vplay&id={mv_id}&q=1080"
                
                playlist.append(f"{mv_name}${self.e64('0@@@@' + play_url)}")
                page_count += 1
            
            print(f"🎬 歌手MV第{page}页获取到 {page_count} 个")
            
            # 检查是否有下一页
            has_next = self._check_has_next_page(mv_doc)
            if not has_next:
                break
        
        return playlist

    def _get_all_hot_mvs(self, exclude_id=None, max_pages=2):
        """获取热门MV（多页）"""
        playlist = []
        
        for page in range(1, max_pages + 1):
            if len(playlist) >= 40:
                break
                
            if page == 1:
                url = "/mvlist/index/index/hot.html"
            else:
                url = f"/mvlist/index/index/hot/{page}.html"
            
            doc = self.getpq(url)
            
            page_count = 0
            for li in doc(".video_list li, .play_list li").items():
                if len(playlist) >= 40:
                    break
                
                a = li(".name a").eq(0)
                if not a:
                    continue
                
                href = a.attr("href")
                if not href or "/mp4/" not in href:
                    continue
                
                if exclude_id and exclude_id in href:
                    continue
                
                mv_name = a.text()
                mv_name = self._clean_song_name(mv_name)
                
                mv_id = href.split('/')[-1].replace('.html', '')
                play_url = f"{self.host}/data/down.php?ac=vplay&id={mv_id}&q=1080"
                
                playlist.append(f"{mv_name}${self.e64('0@@@@' + play_url)}")
                page_count += 1
            
            print(f"🎬 热门MV第{page}页获取到 {page_count} 个")
            
            # 检查是否有下一页
            has_next = self._check_has_next_page(doc)
            if not has_next:
                break
        
        return playlist

    # ==================== 歌曲详情与播放列表 ====================
    def _get_song_detail_with_playlist(self, doc, url):
        """获取歌曲详情并创建播放列表"""
        song_id = re.search(r'/mp3/([^/]+)\.html', url)
        song_id = song_id.group(1) if song_id else ""
        
        name = self._clean(doc("h1").text() or "当前歌曲")
        name = self._clean_song_name(name)
        
        # 获取歌手信息
        artist = ""
        artist_elem = doc(".play_singer .name a, .singer a, .artist a").eq(0)
        if artist_elem:
            artist = artist_elem.text()
        else:
            artist_match = re.search(r'^(.+?)\s*-\s*', name)
            if artist_match:
                artist = artist_match.group(1).strip()
                name = name.replace(artist + " - ", "")
        
        # 获取封面
        pic = doc(".playhimg img, .pic img").eq(0).attr("src")
        
        # 获取当前歌曲的播放URL
        current_play_url = f"{self.host}/data/down.php?ac=music&id={song_id}"
        
        # 创建播放列表 - 当前歌曲优先
        display_name = f"{artist} - {name}" if artist else name
        playlist = [f"{display_name}${self.e64('0@@@@' + current_play_url)}"]
        
        # 尝试获取同歌手的歌曲
        if artist:
            singer_songs = self._get_singer_song_playlist(artist, exclude_id=song_id, limit=30)
            if singer_songs:
                playlist.extend(singer_songs)
                print(f"🎵 添加了 {len(singer_songs)} 个同歌手歌曲")
        
        # 如果不够，获取热门歌曲
        if len(playlist) < 20:
            hot_songs = self._get_hot_song_playlist(limit=30-len(playlist))
            if hot_songs:
                existing_urls = [item.split('$')[-1] for item in playlist]
                for song in hot_songs:
                    song_url = song.split('$')[-1]
                    if song_url not in existing_urls:
                        playlist.append(song)
                        existing_urls.append(song_url)
                print(f"🎵 添加了 {len(hot_songs)} 个热门歌曲")
        
        # 去重
        unique_playlist = []
        seen_urls = set()
        for item in playlist:
            parts = item.split('$')
            if len(parts) >= 2:
                url_part = parts[-1]
                if url_part not in seen_urls:
                    seen_urls.add(url_part)
                    unique_playlist.append(item)
        
        print(f"🎵 最终播放列表: {len(unique_playlist)} 首歌曲")
        play_url_str = "#".join(unique_playlist)
        
        vod = {
            "vod_id": url,
            "vod_name": f"🎵 {name}",
            "vod_pic": self._get_image(pic) if pic else "",
            "vod_actor": artist,
            "vod_content": f"🎵 歌曲 · {artist} · 共{len(unique_playlist)}首歌曲循环播放",
            "vod_play_from": "🎵 歌曲播放列表",
            "vod_play_url": play_url_str
        }
        
        return {"list": [vod]}

    def _get_singer_song_playlist(self, artist, exclude_id=None, limit=30):
        """获取同歌手歌曲播放列表"""
        playlist = []
        
        # 搜索歌手
        search_url = f"/so.php?wd={quote(artist)}&page=1"
        doc = self.getpq(search_url)
        
        # 查找歌手页面
        singer_url = None
        for a in doc("a[href*='/singer/']").items():
            if artist in a.text():
                singer_url = a.attr("href")
                break
        
        if singer_url:
            singer_url = self._abs(singer_url)
            singer_doc = self.getpq(singer_url)
            
            for li in singer_doc(".play_list li").items():
                if len(playlist) >= limit:
                    break
                
                a = li(".name a").eq(0)
                if not a:
                    continue
                
                href = a.attr("href")
                if not href or "/mp3/" not in href:
                    continue
                
                if exclude_id and exclude_id in href:
                    continue
                
                song_name = a.text()
                song_name = self._clean_song_name(song_name)
                
                # 如果歌名不含歌手，添加上
                if artist not in song_name:
                    song_name = f"{artist} - {song_name}"
                
                song_id = href.split('/')[-1].replace('.html', '')
                play_url = f"{self.host}/data/down.php?ac=music&id={song_id}"
                
                playlist.append(f"{song_name}${self.e64('0@@@@' + play_url)}")
        
        return playlist

    # ==================== 增强版歌词获取 - 多源获取真实歌词 ====================
    def playerContent(self, flag, id, vipFlags):
        """播放器 - 多源获取真实歌词"""
        raw = self.d64(id).split("@@@@")[-1]
        parts = raw.split("|||")
        url = parts[0].replace(r"\/", "/")

        # 显式区分视频与音乐：高清 MV 保持走视频播放器，其余分类才交给
        # 手机端音乐播放器。music_list_mode=1 只让新手机端把播放列表
        # 显示为单列列表；旧版/TV 端会忽略该附加字段。
        flag_text = str(flag or "").lower()
        url_text = str(url or "").lower()
        is_mv = (
            "/mp4/" in url_text
            or "ac=vplay" in url_text
            or "高清mv" in flag_text
            or "mv播放" in flag_text
            or "🎬" in flag_text
            or bool(re.search(r'\.(?:mp4|m3u8|flv)(?:\?|$)', url_text, re.I))
        )
        
        result = {
            "parse": 0,
            "url": url,
            "header": {
                "User-Agent": self.headers["User-Agent"],
                "Referer": self.host + "/",
                "Accept": "*/*",
                "Accept-Encoding": "identity;q=1, *;q=0",
                "Range": "bytes=0-"
            }
        }
        if not is_mv:
            result["music_player"] = 1
            result["music_list_mode"] = 1

        # 备用音乐接口返回 302，先解析最终媒体地址，兼容不自动跟随跳转的盒子。
        if self.music_url_api in url and "/meting/" in url:
            try:
                media_resp = self.session.get(url, headers={
                    "User-Agent": self.headers["User-Agent"],
                    "Referer": "https://mu-jie.cc/",
                    "Origin": "https://mu-jie.cc"
                }, allow_redirects=False, timeout=12)
                location = media_resp.headers.get("Location")
                if location:
                    result["url"] = location
                    result["header"]["Referer"] = "https://music.163.com/"
            except Exception as e:
                print(f"⚠️ 备用播放地址解析失败: {e}")
            return result

        # 新版电台节目使用 /radio/*.html，页面内 player() 的第二个参数
        # 才是真实音频 ID。这里延迟解析，避免打开电台详情时逐集请求而变慢。
        if "/radio/" in url:
            try:
                radio_doc = self.getpq(url)
                radio_html = radio_doc.html() or ""
                radio_id_match = re.search(
                    r'player\(\s*[\'\"]music[\'\"]\s*,\s*[\'\"]([^\'\"]+)',
                    radio_html,
                    re.I
                )
                if radio_id_match:
                    radio_id = radio_id_match.group(1)
                    result["url"] = f"{self.host}/data/down.php?ac=music&id={radio_id}"
            except Exception as e:
                print(f"⚠️ 电台节目解析失败: {e}")
            return result
        
        # 如果是MV，直接返回URL
        if "/mp4/" in url or "ac=vplay" in url:
            # URL已经是处理过的播放地址
            result["url"] = url
            # MV不需要歌词
            return result
        
        # 获取歌曲信息（原有歌词逻辑保持不变）
        song_id = None
        artist = ""
        song_name = ""
        
        if "ac=music" in url:
            song_id_match = re.search(r'id=([^&]+)', url)
            if song_id_match:
                song_id = song_id_match.group(1)
        elif "/mp3/" in url:
            song_id_match = re.search(r'/mp3/([^/]+)\.html', url)
            if song_id_match:
                song_id = song_id_match.group(1)
        
        if not song_id:
            return result
        
        # 检查缓存
        cache_key = f"lrc_{song_id}"
        if cache_key in self.lrc_cache:
            result["lrc"] = self.lrc_cache[cache_key]
            print(f"📦 使用缓存歌词: {song_id}")
            return result
        
        print(f"🎵 尝试获取歌词 ID: {song_id}")
        
        # 先获取歌曲信息（用于备用歌词）
        try:
            mp3_url = f"{self.host}/mp3/{song_id}.html"
            resp = self.session.get(mp3_url, headers=self.headers, timeout=3)
            
            if resp.status_code == 200:
                doc = pq(resp.text)
                title = doc("h1").text() or doc("title").text()
                
                # 清理标题
                title = re.sub(r'\s*[-|]\s*(?:MP3|免费下载|LRC|歌词|动态歌词|热门歌单|推荐音乐).*$', '', title)
                title = title.strip()
                
                # 从页面中找歌手
                singer_elem = doc(".play_singer .name a, .singer a, .artist a").eq(0)
                if singer_elem:
                    artist = singer_elem.text().strip()
                
                # 如果标题包含分隔符，尝试分割
                if ' - ' in title:
                    parts = title.split(' - ', 1)
                    if len(parts) == 2:
                        artist = parts[0].strip()
                        song_name = parts[1].strip()
                    else:
                        song_name = title
                else:
                    song_name = title
        except:
            pass
        
        # ==================== 多源歌词获取 ====================
        
        # 源1: 从世纪音乐网down.php获取
        lrc_content = self._get_lrc_from_source1(song_id)
        if lrc_content:
            result["lrc"] = lrc_content
            self.lrc_cache[cache_key] = lrc_content
            print(f"✅ 源1获取成功: {song_id}")
            return result
        
        # 源2: 从lkdown参数获取
        lrc_content = self._get_lrc_from_source2(song_id)
        if lrc_content:
            result["lrc"] = lrc_content
            self.lrc_cache[cache_key] = lrc_content
            print(f"✅ 源2获取成功: {song_id}")
            return result
        
        # 源3: 从data/lrc/获取
        lrc_content = self._get_lrc_from_source3(song_id)
        if lrc_content:
            result["lrc"] = lrc_content
            self.lrc_cache[cache_key] = lrc_content
            print(f"✅ 源3获取成功: {song_id}")
            return result
        
        # 源4: 从网易云音乐获取（需要song_id转换）
        lrc_content = self._get_lrc_from_netease(artist, song_name)
        if lrc_content:
            result["lrc"] = lrc_content
            self.lrc_cache[cache_key] = lrc_content
            print(f"✅ 源4(网易云)获取成功: {artist} - {song_name}")
            return result
        
        # 源5: 从QQ音乐获取
        lrc_content = self._get_lrc_from_qq(artist, song_name)
        if lrc_content:
            result["lrc"] = lrc_content
            self.lrc_cache[cache_key] = lrc_content
            print(f"✅ 源5(QQ音乐)获取成功: {artist} - {song_name}")
            return result
        
        # 源6: 从酷狗音乐获取
        lrc_content = self._get_lrc_from_kugou(artist, song_name)
        if lrc_content:
            result["lrc"] = lrc_content
            self.lrc_cache[cache_key] = lrc_content
            print(f"✅ 源6(酷狗)获取成功: {artist} - {song_name}")
            return result
        
        # 所有源都失败，生成备用歌词
        print(f"❌ 所有歌词源都失败，使用备用歌词: {song_id}")
        fallback_lrc = self._generate_fallback_lyrics(artist, song_name, song_id)
        result["lrc"] = fallback_lrc
        self.lrc_cache[cache_key] = fallback_lrc
        return result

    def _get_lrc_from_source1(self, song_id):
        """源1: 从down.php获取"""
        try:
            lrc_url = f"{self.host}/down.php?ac=music&lk=txt&id={song_id}"
            lrc_resp = self.session.get(lrc_url, headers=self.headers, timeout=5)
            if lrc_resp.status_code == 200:
                for encoding in ['utf-8', 'gbk', 'gb2312', 'big5']:
                    try:
                        lrc_content = lrc_resp.content.decode(encoding)
                        if re.search(r'\[\d{2}:\d{2}', lrc_content):
                            return self._filter_lrc_ads(lrc_content)
                    except:
                        continue
        except:
            pass
        return None

    def _get_lrc_from_source2(self, song_id):
        """源2: 从lkdown参数获取"""
        try:
            mp3_url = f"{self.host}/mp3/{song_id}.html"
            mp3_resp = self.session.get(mp3_url, headers=self.headers, timeout=5)
            
            if mp3_resp.status_code == 200:
                html = mp3_resp.text
                lkdown_match = re.search(r'lkdown\(\'([^\']+)\'\)', html)
                if not lkdown_match:
                    lkdown_match = re.search(r'lkdown\("([^"]+)"\)', html)
                
                if lkdown_match:
                    lrc_id = lkdown_match.group(1)
                    lrc_url = f"{self.host}/down.php?ac=music&lk=txt&id={lrc_id}"
                    lrc_resp = self.session.get(lrc_url, headers=self.headers, timeout=5)
                    
                    if lrc_resp.status_code == 200:
                        for encoding in ['utf-8', 'gbk', 'gb2312', 'big5']:
                            try:
                                lrc_content = lrc_resp.content.decode(encoding)
                                if re.search(r'\[\d{2}:\d{2}', lrc_content):
                                    return self._filter_lrc_ads(lrc_content)
                            except:
                                continue
        except:
            pass
        return None

    def _get_lrc_from_source3(self, song_id):
        """源3: 从data/lrc/获取"""
        try:
            lrc_url = f"{self.host}/data/lrc/{song_id}.lrc"
            lrc_resp = self.session.get(lrc_url, headers=self.headers, timeout=5)
            if lrc_resp.status_code == 200:
                for encoding in ['utf-8', 'gbk', 'gb2312', 'big5']:
                    try:
                        lrc_content = lrc_resp.content.decode(encoding)
                        if re.search(r'\[\d{2}:\d{2}', lrc_content):
                            return self._filter_lrc_ads(lrc_content)
                    except:
                        continue
        except:
            pass
        return None

    def _get_lrc_from_netease(self, artist, song_name):
        """源4: 从网易云音乐获取歌词"""
        if not artist or not song_name:
            return None
        
        try:
            # 搜索歌曲
            search_url = f"https://music.163.com/api/search/get/web"
            params = {
                "s": f"{artist} {song_name}",
                "type": 1,
                "offset": 0,
                "limit": 5
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://music.163.com/"
            }
            
            search_resp = self.session.get(search_url, params=params, headers=headers, timeout=5)
            if search_resp.status_code == 200:
                data = search_resp.json()
                if data['code'] == 200 and data['result']['songs']:
                    # 取第一个匹配的歌曲
                    song = data['result']['songs'][0]
                    song_id = song['id']
                    
                    # 获取歌词
                    lrc_url = f"https://music.163.com/api/song/lyric"
                    lrc_params = {
                        "id": song_id,
                        "lv": 1,
                        "kv": 1,
                        "tv": -1
                    }
                    lrc_resp = self.session.get(lrc_url, params=lrc_params, headers=headers, timeout=5)
                    
                    if lrc_resp.status_code == 200:
                        lrc_data = lrc_resp.json()
                        if 'lrc' in lrc_data and lrc_data['lrc']['lyric']:
                            lrc_content = lrc_data['lrc']['lyric']
                            if re.search(r'\[\d{2}:\d{2}', lrc_content):
                                return self._filter_lrc_ads(lrc_content)
        except:
            pass
        return None

    def _get_lrc_from_qq(self, artist, song_name):
        """源5: 从QQ音乐获取歌词"""
        if not artist or not song_name:
            return None
        
        try:
            # 搜索歌曲
            search_url = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
            params = {
                "w": f"{artist} {song_name}",
                "format": "json",
                "p": 1,
                "n": 5
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://y.qq.com/"
            }
            
            search_resp = self.session.get(search_url, params=params, headers=headers, timeout=5)
            if search_resp.status_code == 200:
                data = search_resp.json()
                if data['code'] == 0 and data['data']['song']['list']:
                    song = data['data']['song']['list'][0]
                    song_mid = song['songmid']
                    
                    # 获取歌词
                    lrc_url = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
                    lrc_params = {
                        "songmid": song_mid,
                        "format": "json"
                    }
                    lrc_headers = headers.copy()
                    lrc_headers["Referer"] = "https://y.qq.com/"
                    
                    lrc_resp = self.session.get(lrc_url, params=lrc_params, headers=lrc_headers, timeout=5)
                    if lrc_resp.status_code == 200:
                        # QQ音乐返回的是jsonp，需要提取json
                        lrc_text = lrc_resp.text
                        match = re.search(r'({.*})', lrc_text)
                        if match:
                            lrc_data = json.loads(match.group(1))
                            if 'lyric' in lrc_data and lrc_data['lyric']:
                                lrc_content = lrc_data['lyric']
                                # base64解码
                                import base64
                                lrc_content = base64.b64decode(lrc_content).decode('utf-8')
                                if re.search(r'\[\d{2}:\d{2}', lrc_content):
                                    return self._filter_lrc_ads(lrc_content)
        except:
            pass
        return None

    def _get_lrc_from_kugou(self, artist, song_name):
        """源6: 从酷狗音乐获取歌词"""
        if not artist or not song_name:
            return None
        
        try:
            # 搜索歌曲
            search_url = "http://mobilecdn.kugou.com/api/v3/search/song"
            params = {
                "format": "json",
                "keyword": f"{artist} {song_name}",
                "page": 1,
                "pagesize": 5
            }
            
            search_resp = self.session.get(search_url, params=params, timeout=5)
            if search_resp.status_code == 200:
                data = search_resp.json()
                if data['status'] == 1 and data['data']['info']:
                    song = data['data']['info'][0]
                    song_id = song['hash']
                    
                    # 获取歌词
                    lrc_url = "http://krcs.kugou.com/search"
                    lrc_params = {
                        "ver": 1,
                        "man": "yes",
                        "client": "mobi",
                        "hash": song_id,
                        "timelength": song['duration'] * 1000 if 'duration' in song else 0
                    }
                    
                    lrc_resp = self.session.get(lrc_url, params=lrc_params, timeout=5)
                    if lrc_resp.status_code == 200:
                        lrc_data = lrc_resp.json()
                        if lrc_data['status'] == 1 and 'lyrics' in lrc_data and lrc_data['lyrics'][0]['content']:
                            lrc_content = lrc_data['lyrics'][0]['content']
                            # 解码
                            import base64
                            lrc_content = base64.b64decode(lrc_content).decode('utf-8')
                            if re.search(r'\[\d{2}:\d{2}', lrc_content):
                                return self._filter_lrc_ads(lrc_content)
        except:
            pass
        return None

    def _filter_lrc_ads(self, lrc_text):
        """过滤LRC歌词中的广告内容"""
        if not lrc_text:
            return ""
        
        lines = lrc_text.splitlines()
        filtered_lines = []
        
        # 广告关键词模式
        ad_patterns = [
            r'欢迎访问.*',
            r'欢迎来到.*',
            r'本站.*',
            r'.*广告.*',
            r'QQ群.*',
            r'微信.*',
            r'.*www\..*',
            r'.*http.*',
            r'.*\.com.*',
            r'.*\.cn.*',
            r'.*\.net.*',
            r'.*音乐网.*',
            r'.*提供.*',
            r'.*下载.*',
            r'.*免费.*',
            r'.*版权.*',
            r'.*声明.*',
            r'.*邮箱.*',
            r'.*联系.*',
            r'oeecc',
            r'foxmail',
        ]
        
        for line in lines:
            line = line.rstrip()
            if not line:
                filtered_lines.append(line)
                continue
            
            # 保留时间标签行
            if re.match(r'^\[\d{2}:\d{2}', line):
                # 检查是否包含广告
                is_ad = False
                for pattern in ad_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        is_ad = True
                        break
                
                if not is_ad:
                    filtered_lines.append(line)
            else:
                # 保留元数据行
                if re.match(r'^\[(ar|ti|al|by|offset|total|length):', line, re.I):
                    filtered_lines.append(line)
                else:
                    # 非时间标签非元数据的行，保留（可能是纯文本歌词）
                    filtered_lines.append(line)
        
        return '\n'.join(filtered_lines)

    def _generate_fallback_lyrics(self, artist, song_name, song_id):
        """生成备用歌词"""
        if not song_name:
            song_name = f"歌曲 {song_id}" if song_id else "未知歌曲"
        
        # 生成带有时间轴的备用歌词
        fallback = f"[ar: {artist}]\n" if artist else ""
        fallback += f"[ti: {song_name}]\n"
        fallback += f"[by: 世纪音乐网]\n\n"
        
        # 生成3分钟左右的歌词
        for i in range(0, 36):  # 每5秒一行，共3分钟
            minutes = i // 12
            seconds = (i % 12) * 5
            time_tag = f"[{minutes:02d}:{seconds:02d}.00]"
            
            if i % 4 == 0:
                content = f"♪ {song_name} ♪"
            elif i % 4 == 1:
                content = f"♫ {artist + ' - ' if artist else ''}{song_name} ♫"
            elif i % 4 == 2:
                content = "正在播放..."
            else:
                content = "暂无歌词，请欣赏音乐"
            
            fallback += f"{time_tag} {content}\n"
        
        return fallback

    # ==================== localProxy方法 ====================
    def localProxy(self, param):
        url = unquote(param.get("url", ""))
        type_ = param.get("type")
        
        if type_ == "img":
            try:
                return [200, "image/jpeg", self.session.get(url, headers={"Referer": self.host + "/"}, timeout=5).content, {}]
            except:
                return [404, "text/plain", "Image Error", {}]
        
        elif type_ == "lrc":
            try:
                r = self.session.get(url, headers={"Referer": self.host + "/"}, timeout=5)
                lrc_content = self._filter_lrc_ads(r.text)
                return [200, "application/octet-stream", lrc_content.encode('utf-8'), {}]
            except:
                return [404, "text/plain", "LRC Error", {}]
        
        return None

    # ==================== 以下所有方法保持原样 ====================
    def _get_mv_detail(self, doc, url):
        video_id = re.search(r'/mp4/([^/]+)\.html', url)
        video_id = video_id.group(1) if video_id else ""
        
        name = self._clean(doc("h1").text() or "当前MV")
        name = self._clean_song_name(name)
        
        artist = ""
        artist_elem = doc(".play_singer .name a").eq(0)
        if artist_elem:
            artist = artist_elem.text()
        else:
            artist_match = re.search(r'^(.+?)\s*-\s*', name)
            if artist_match:
                artist = artist_match.group(1).strip()
                name = name.replace(artist + " - ", "")
        
        pic = doc(".video_list .pic img").eq(0).attr("src") or doc(".pic img").eq(0).attr("src")
        if not pic:
            pic = "https://p2.music.126.net/xxx/mv.jpg"
        
        play_urls = []
        play_url = f"{self.host}/data/down.php?ac=vplay&id={video_id}&q=1080"
        play_urls.append(f"{name}${self.e64('0@@@@' + play_url)}")
        
        if artist:
            singer_link = None
            for a in doc(".ilingku_fl a, .singer_info a, .play_singer a").items():
                text = a.text()
                href = a.attr("href")
                if href and ('视频' in text or 'MV' in text or 'mv' in text.lower() or '/singer/' in href):
                    singer_link = href
                    break
            
            if singer_link:
                singer_url = self._abs(singer_link)
                if '/singer/' in singer_url and not 'video' in singer_url:
                    singer_doc = self.getpq(singer_url)
                    for a in singer_doc(".ilingku_fl a").items():
                        if '视频' in a.text() or 'MV' in a.text():
                            mv_page = a.attr("href")
                            if mv_page:
                                singer_url = self._abs(mv_page)
                                break
                
                print(f"🎬 获取同歌手MV: {singer_url}")
                mv_doc = self.getpq(singer_url)
                
                mv_count = 0
                for li in mv_doc(".play_list li, .video_list li").items():
                    a = li(".name a").eq(0)
                    if not (href := a.attr("href")) or "/mp4/" not in href:
                        continue
                    
                    if video_id in href:
                        continue
                    
                    mv_name = a.text()
                    mv_name = self._clean_song_name(mv_name)
                    mv_id = href.split('/')[-1].replace('.html', '')
                    mv_play_url = f"{self.host}/data/down.php?ac=vplay&id={mv_id}&q=1080"
                    play_urls.append(f"{mv_name}${self.e64('0@@@@' + mv_play_url)}")
                    mv_count += 1
                    
                    if mv_count >= 19:
                        break
                
                print(f"🎬 找到同歌手MV: {mv_count} 个")
        
        return {
            "vod_play_url": "#".join(play_urls),
            "vod_pic": self._get_image(pic, is_mv=True) if pic else "",
            "vod_actor": artist
        }

    def _get_singer_mvs(self, doc, url):
        eps = []
        mv_count = 0
        
        video_urls = []
        for a in doc(".ilingku_fl a").items():
            text = a.text()
            if '视频' in text or 'MV' in text or 'mv' in text.lower():
                video_link = a.attr("href")
                if video_link:
                    video_urls.append(video_link)
        
        video_urls = list(set(video_urls))
        if video_urls:
            video_link = video_urls[0]
            video_url = self._abs(video_link)
            print(f"🎬 获取歌手MV列表: {video_url}")
            video_doc = self.getpq(video_url)
            
            for li in video_doc(".play_list li, .video_list li").items():
                a = li(".name a").eq(0)
                if not (href := a.attr("href")):
                    continue
                if "/mp4/" in href:
                    name = a.text()
                    name = self._clean_song_name(name)
                    video_id = href.split('/')[-1].replace('.html', '')
                    play_url = f"{self.host}/data/down.php?ac=vplay&id={video_id}&q=1080"
                    eps.append(f"{name}${self.e64('0@@@@' + play_url)}")
                    mv_count += 1
                    
                    if mv_count >= 50:
                        break
        
        if eps:
            print(f"🎬 歌手MV: 获取到 {mv_count} 部")
            return "#".join(eps)
        return None

    # ==================== 修复点：获取歌手的所有歌曲（跨页获取） ====================
    def _get_singer_detail(self, doc, url):
        play_from = []
        play_url = []
        
        songs = []
        song_count = 0
        
        # 获取当前页的歌曲
        for li in doc(".play_list li").items():
            a = li(".name a").eq(0)
            if not (href := a.attr("href")):
                continue
            if "/mp3/" in href:
                name = a.text()
                name = self._clean_song_name(name)
                song_id = href.split('/')[-1].replace('.html', '')
                play_url_mp3 = f"{self.host}/data/down.php?ac=music&id={song_id}"
                songs.append(f"{name}${self.e64('0@@@@' + play_url_mp3)}")
                song_count += 1
        
        # 获取歌手的所有歌曲页面（最多10页）
        base_url = url.rstrip('/')
        if not base_url.endswith('.html'):
            base_url = base_url + '/'
        
        # 查找分页信息
        pages = []
        for a in doc(".pages a, .pagination a, .page a").items():
            text = a.text().strip()
            if text.isdigit():
                pages.append(int(text))
        
        if pages:
            max_page = max(pages)
            print(f"📊 歌手歌曲共有 {max_page} 页，当前第1页，将获取剩余页面")
            
            # 从第2页开始获取
            for page in range(2, max_page + 1):
                if len(songs) >= 500:  # 最多获取500首，避免太多
                    print(f"📊 已达到500首上限，停止获取更多页面")
                    break
                    
                # 构建分页URL
                if '/singer/' in base_url:
                    # 歌手页面分页格式：singer/xxx_2.html 或 singer/xxx/2.html
                    if base_url.endswith('.html'):
                        page_url = re.sub(r'\.html$', f'_{page}.html', base_url)
                    else:
                        page_url = base_url.rstrip('/') + f'/{page}.html'
                else:
                    page_url = base_url + f'index_{page}.html'
                
                print(f"📄 获取第 {page} 页歌曲: {page_url}")
                page_doc = self.getpq(page_url)
                
                if not page_doc or page_doc.html() == "<html></html>":
                    print(f"⚠️ 第 {page} 页获取失败，跳过")
                    continue
                
                page_count = 0
                for li in page_doc(".play_list li").items():
                    if len(songs) >= 500:
                        break
                        
                    a = li(".name a").eq(0)
                    if not (href := a.attr("href")):
                        continue
                    if "/mp3/" in href:
                        name = a.text()
                        name = self._clean_song_name(name)
                        song_id = href.split('/')[-1].replace('.html', '')
                        play_url_mp3 = f"{self.host}/data/down.php?ac=music&id={song_id}"
                        songs.append(f"{name}${self.e64('0@@@@' + play_url_mp3)}")
                        song_count += 1
                        page_count += 1
                
                print(f"📄 第 {page} 页获取到 {page_count} 首歌曲")
                
                # 检查是否有下一页
                has_next = self._check_has_next_page(page_doc)
                if not has_next:
                    print(f"📄 第 {page} 页没有下一页，停止获取")
                    break
        
        if songs:
            # 将歌曲按每页100首分成多个播放列表
            page_size = 100
            total_pages = (len(songs) + page_size - 1) // page_size
            
            for page in range(total_pages):
                start = page * page_size
                end = min(start + page_size, len(songs))
                page_songs = songs[start:end]
                
                page_num = page + 1
                if total_pages == 1:
                    play_from.append(f"🎵 歌手歌曲 · {len(songs)}首")
                else:
                    play_from.append(f"🎵 歌手歌曲 {page_num}/{total_pages} · {len(page_songs)}首")
                
                play_url.append("#".join(page_songs))
                
            print(f"🎵 歌手歌曲: 总共获取到 {song_count} 首，分成 {total_pages} 页")
        
        mvs = self._get_singer_mvs(doc, url)
        if mvs:
            mv_count = len(mvs.split('#'))
            play_from.append(f"🎬 歌手MV · {mv_count}部")
            play_url.append(mvs)
            print(f"🎬 歌手MV: 获取到 {mv_count} 部")
        
        if play_from and play_url:
            return {
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url": "$$$".join(play_url)
            }
        elif songs:
            return {
                "vod_play_from": f"🎵 歌手歌曲 · {song_count}首",
                "vod_play_url": "#".join(songs)
            }
        elif mvs:
            return {
                "vod_play_from": f"🎬 歌手MV · {mv_count}部",
                "vod_play_url": mvs
            }
        else:
            return {
                "vod_play_from": "暂无内容",
                "vod_play_url": f"暂无歌曲${self.e64('0@@@@' + url)}"
            }

    def _parse_singer_list(self, doc):
        items = []
        for li in doc(".singer_list li").items():
            pic_a = li(".pic a").eq(0)
            if not pic_a:
                continue
            href = pic_a.attr("href")
            if not href:
                continue
            
            name_a = li(".name a").eq(0)
            name = name_a.text()
            img = li("img").eq(0)
            pic = img.attr("src")
            
            items.append({
                "vod_id": self._abs(href),
                "vod_name": self._clean(name),
                "vod_pic": self._get_image(pic, is_singer=True) if pic else "",
                "vod_remarks": "👤 歌手",
                "style": {"type": "oval", "ratio": 1}
            })
        
        return items

    def _get_playlist_songs(self, doc):
        eps = []
        for li in doc(".play_list li").items():
            a = li(".name a").eq(0)
            if not (href := a.attr("href")):
                continue
            if "/mp3/" in href:
                name = a.text()
                name = self._clean_song_name(name)
                song_id = href.split('/')[-1].replace('.html', '')
                play_url = f"{self.host}/data/down.php?ac=music&id={song_id}"
                eps.append(f"{name}${self.e64('0@@@@' + play_url)}")
        
        if eps:
            return {"vod_play_url": "#".join(eps)}
        return {"vod_play_url": f"暂无歌曲${self.e64('0@@@@' + self.host)}"}

    def _get_song_detail(self, doc, url):
        song_id = re.search(r'/mp3/([^/]+)\.html', url)
        song_id = song_id.group(1) if song_id else ""
        play_url = f"{self.host}/data/down.php?ac=music&id={song_id}"
        singer = doc(".play_singer .name a").text() or ""
        return {
            "vod_play_url": f"播放${self.e64('0@@@@' + play_url)}",
            "vod_actor": singer
        }

    # ==================== 2026-08 主页改版兼容 ====================
    # 网站新版移除了 play_list/video_list/singer_list 等 ul 类名。
    # 以下方法放在类的后部，用真实详情链接识别资源，覆盖上方旧实现。
    def _named_rows(self, doc, path):
        """返回新版页面中唯一的“名称链接 + 所在 li”。"""
        rows = []
        seen = set()
        selector = f'.name a[href*="{path}"]'
        for a in doc(selector).items():
            href = (a.attr("href") or "").strip()
            if not href or href in seen:
                continue
            li = a.parents("li").eq(0)
            if not li:
                continue
            seen.add(href)
            rows.append((li, a, href))
        return rows

    def _verify_page(self, doc):
        if not doc:
            return True
        title = (doc("title").text() or "").strip()
        body = (doc("body").text() or "")[:300]
        return "人机验证" in title or "安全验证" in title or "我不是人机" in body

    def _api_json(self, path, params=None, base=None):
        url = (base or self.netease_api) + path
        try:
            r = self.session.get(url, params=params or {}, headers={
                "User-Agent": self.headers["User-Agent"],
                "Referer": "https://music.163.com/",
                "Accept": "application/json,text/plain,*/*"
            }, timeout=12)
            return r.json() if r.status_code == 200 else {}
        except Exception as e:
            print(f"⚠️ 备用接口请求失败: {url} - {e}")
            return {}

    def _mv_detail_cached(self, mv_id):
        key = str(mv_id)
        with self.mv_cache_lock:
            cached = self.mv_detail_cache.get(key)
        if cached is not None:
            return cached
        data = self._api_json("/api/mv/detail", {"id": key})
        detail = data.get("data") or {}
        with self.mv_cache_lock:
            self.mv_detail_cache[key] = detail
        return detail

    def _wy_artist(self, song):
        artists = song.get("artists") or song.get("ar") or []
        return "/".join(str(x.get("name", "")) for x in artists if x.get("name"))

    def _wy_song_item(self, song, remark="🎵 歌曲", list_style=True, pic=""):
        sid = song.get("id")
        if not sid:
            return None
        artist = self._wy_artist(song)
        name = str(song.get("name") or "未知歌曲")
        album = song.get("album") or song.get("al") or {}
        cover = pic or album.get("picUrl") or album.get("blurPicUrl") or ""
        full_name = f"{artist} - {name}" if artist else name
        item = {
            "vod_id": f"wy_song_{sid}",
            "vod_name": full_name,
            "vod_pic": "" if list_style else cover,
            "vod_remarks": remark if not artist else f"{remark} · {artist}",
            "style": {"type": "list"} if list_style else {"type": "rect", "ratio": 1}
        }
        return item

    def _fallback_category(self, tid, pg, extend):
        """目标站出现验证页时自动使用公开接口，保证盒子仍有数据。"""
        pg = int(pg or 1)
        offset30 = (pg - 1) * 30
        items = []

        if tid in ("home", "new", "top"):
            playlist_id = 3779629 if tid in ("home", "new") else 3778678
            data = self._api_json("/api/playlist/detail", {"id": playlist_id})
            tracks = (data.get("result") or {}).get("tracks") or []
            start = 0 if tid == "home" else (pg - 1) * 68
            for song in tracks[start:start + (85 if tid == "home" else 68)]:
                item = self._wy_song_item(song, "🏠 首页歌曲" if tid == "home" else ("📈 新歌" if tid == "new" else "📊 热歌"), True)
                if item:
                    items.append(item)
            return {"list": items, "page": pg, "pagecount": pg + 1 if start + len(items) < len(tracks) else pg, "limit": 68, "total": len(tracks)}

        if tid == "singer":
            type_map = {"male": 1, "girl": 2, "band": 3, "index": -1}
            area_map = {"huayu": 7, "oumei": 96, "ribrn": 8, "hanguo": 16, "index": -1}
            initial = extend.get("char", "index")
            initial = -1 if initial == "index" else initial
            data = self._api_json("/api/artist/list", {
                "type": type_map.get(extend.get("sex", "girl"), 2),
                "area": area_map.get(extend.get("area", "huayu"), 7),
                "initial": initial, "offset": offset30, "limit": 30
            })
            for artist in data.get("artists") or []:
                aid = artist.get("id")
                if not aid:
                    continue
                items.append({
                    "vod_id": f"wy_artist_{aid}", "vod_name": artist.get("name") or "未知歌手",
                    "vod_pic": artist.get("picUrl") or artist.get("img1v1Url") or "",
                    "vod_remarks": "👤 歌手", "style": {"type": "oval", "ratio": 1}
                })
            more = bool(data.get("more"))
            return {"list": items, "page": pg, "pagecount": pg + 1 if more else pg, "limit": 30, "total": 9999 if more else offset30 + len(items)}

        if tid == "playlist":
            tag_names = {"index": "全部", "huayu": "华语", "oumei": "欧美", "riyu": "日语", "hanyu": "韩语", "yueyu": "粤语", "liuxing": "流行", "yaogun": "摇滚", "minyao": "民谣", "dianzi": "电子", "qingyinle": "轻音乐", "gudian": "古典", "gufeng": "古风", "yingshi": "影视原声", "ertong": "儿童", "jingdian": "经典"}
            data = self._api_json("/api/playlist/list", {"cat": tag_names.get(extend.get("tag", "index"), "全部"), "order": "hot", "offset": offset30, "limit": 30})
            for vod in data.get("playlists") or []:
                pid = vod.get("id")
                if pid:
                    items.append({"vod_id": f"wy_playlist_{pid}", "vod_name": vod.get("name") or "歌单", "vod_pic": vod.get("coverImgUrl") or "", "vod_remarks": "💎 歌单", "style": {"type": "rect", "ratio": 1.42}})
            more = bool(data.get("more"))
            return {"list": items, "page": pg, "pagecount": pg + 1 if more else pg, "limit": 30, "total": 9999 if more else offset30 + len(items)}

        if tid == "radio":
            data = self._api_json("/api/djradio/recommend/v1", {"offset": offset30, "limit": 30})
            for vod in data.get("djRadios") or []:
                rid = vod.get("id")
                if rid:
                    items.append({"vod_id": f"wy_radio_{rid}", "vod_name": vod.get("name") or "电台", "vod_pic": vod.get("picUrl") or "", "vod_remarks": "💗 电台", "style": {"type": "rect", "ratio": 1.42}})
            return {"list": items, "page": pg, "pagecount": pg + 1 if len(items) >= 30 else pg, "limit": 30, "total": 9999}

        if tid == "album":
            area_map = {"index": "ALL", "huayu": "ZH", "oumei": "EA", "hanguo": "KR", "riben": "JP"}
            data = self._api_json("/api/album/new", {"area": area_map.get(extend.get("area", "index"), "ALL"), "offset": offset30, "limit": 30})
            for vod in data.get("albums") or []:
                aid = vod.get("id")
                artist = (vod.get("artist") or {}).get("name") or ""
                if aid:
                    items.append({"vod_id": f"wy_album_{aid}", "vod_name": f"{vod.get('name') or '新碟'} - {artist}" if artist else (vod.get("name") or "新碟"), "vod_pic": vod.get("picUrl") or "", "vod_remarks": "💿 新碟", "style": {"type": "rect", "ratio": 1.42}})
            total = int(data.get("total") or 0)
            return {"list": items, "page": pg, "pagecount": pg + 1 if offset30 + len(items) < total else pg, "limit": 30, "total": total}

        if tid == "mv":
            area_map = {"index": "全部", "neidi": "内地", "gangtai": "港台", "oumei": "欧美", "hanguo": "韩国", "riben": "日本"}
            type_map = {"index": "全部", "guanfang": "官方版", "yuansheng": "原生", "xianchang": "现场版", "wangyi": "网易出品"}
            order_map = {"new": "最新", "hot": "最热", "rise": "上升最快"}
            # 多取一些并并发检查详情，过滤掉 brs 为空、点击后没有线路的资源。
            mv_offset = (pg - 1) * 45
            data = self._api_json("/api/mv/all", {"area": area_map.get(extend.get("area", "index"), "全部"), "type": type_map.get(extend.get("type", "index"), "全部"), "order": order_map.get(extend.get("sort", "new"), "最新"), "offset": mv_offset, "limit": 45})
            raw_mvs = data.get("data") or []
            details = []
            if raw_mvs:
                try:
                    with ThreadPoolExecutor(max_workers=8) as executor:
                        details = list(executor.map(lambda x: self._mv_detail_cached(x.get("id")), raw_mvs))
                except Exception as e:
                    print(f"⚠️ MV线路批量检测失败: {e}")
                    details = [{} for _ in raw_mvs]
            for vod, detail in zip(raw_mvs, details):
                mid = vod.get("id")
                brs = detail.get("brs") or {}
                if mid and brs:
                    qualities = []
                    if brs.get("480"):
                        qualities.append("标清")
                    if brs.get("240"):
                        qualities.append("流畅")
                    if not qualities:
                        qualities.append("可播放")
                    items.append({"vod_id": f"wy_mv_{mid}", "vod_name": vod.get("name") or "高清MV", "vod_pic": vod.get("cover") or "", "vod_remarks": f"🎬 {'/'.join(qualities)} · {vod.get('artistName') or ''}", "style": {"type": "rect", "ratio": 1.78}})
                    if len(items) >= 30:
                        break
            more = bool(data.get("hasMore"))
            return {"list": items, "page": pg, "pagecount": pg + 1 if more else pg, "limit": 30, "total": int(data.get("count") or 9999)}

        return {"list": [], "page": pg, "pagecount": pg, "limit": 30, "total": 0}

    def _page_result(self, items, pg, doc, limit=30):
        has_next = self._check_has_next_page(doc)
        return {
            "list": items,
            "page": int(pg),
            "pagecount": int(pg) + 1 if has_next else int(pg),
            "limit": limit,
            "total": 9999 if has_next else (int(pg) - 1) * limit + len(items)
        }

    def _song_items(self, doc, remark="🎵 歌曲"):
        """无图歌曲列表；用于首页、新歌榜和 Top 榜单。"""
        items = []
        for li, a, href in self._named_rows(doc, "/mp3/"):
            name = self._clean_song_name(a.text() or a.attr("title") or "未知歌曲")
            items.append({
                "vod_id": self._abs(href),
                "vod_name": self._clean(name),
                "vod_pic": "",
                "vod_remarks": remark,
                "style": {"type": "list"}
            })
        return items

    def _picture_items(self, doc, path, remark, style, is_singer=False, is_mv=False):
        """歌手/歌单/电台/新碟/MV 的通用有图列表。"""
        items = []
        for li, a, href in self._named_rows(doc, path):
            name = self._clean(a.text() or a.attr("title") or "未知资源")
            pic = li(".pic img").eq(0).attr("src") or li("img").eq(0).attr("src") or ""
            items.append({
                "vod_id": self._abs(href),
                "vod_name": name,
                "vod_pic": self._get_image(pic, is_singer=is_singer, is_mv=is_mv) if pic else "",
                "vod_remarks": remark,
                "style": style
            })
        return items

    def homeContent(self, filter):
        classes = [
            {"type_name": "🏠 首页", "type_id": "home"},
            {"type_name": "📈 新歌榜", "type_id": "new"},
            {"type_name": "📊 Top榜单", "type_id": "top"},
            {"type_name": "👤 歌手", "type_id": "singer"},
            {"type_name": "💎 歌单", "type_id": "playlist"},
            {"type_name": "💗 电台", "type_id": "radio"},
            {"type_name": "💿 新碟", "type_id": "album"},
            {"type_name": "🎬 高清MV", "type_id": "mv"}
        ]

        filters = {
            "singer": [
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部", "v": "index"}, {"n": "华语", "v": "huayu"},
                    {"n": "韩国", "v": "hanguo"}, {"n": "日本", "v": "ribrn"},
                    {"n": "欧美", "v": "oumei"}
                ]},
                {"key": "sex", "name": "类型", "value": [
                    {"n": "全部", "v": "index"}, {"n": "男", "v": "male"},
                    {"n": "女", "v": "girl"}, {"n": "乐队组合", "v": "band"}
                ]},
                {"key": "char", "name": "字母", "value":
                    [{"n": "全部", "v": "index"}] +
                    [{"n": chr(i), "v": chr(i).lower()} for i in range(65, 91)]}
            ],
            "playlist": [
                {"key": "tag", "name": "分类", "value": [
                    {"n": "全部", "v": "index"}, {"n": "华语", "v": "huayu"},
                    {"n": "欧美", "v": "oumei"}, {"n": "日语", "v": "riyu"},
                    {"n": "韩语", "v": "hanyu"}, {"n": "粤语", "v": "yueyu"},
                    {"n": "流行", "v": "liuxing"}, {"n": "摇滚", "v": "yaogun"},
                    {"n": "民谣", "v": "minyao"}, {"n": "电子", "v": "dianzi"},
                    {"n": "轻音乐", "v": "qingyinle"}, {"n": "古典", "v": "gudian"},
                    {"n": "古风", "v": "gufeng"}, {"n": "影视原声", "v": "yingshi"},
                    {"n": "儿童", "v": "ertong"}, {"n": "经典", "v": "jingdian"}
                ]}
            ],
            "radio": [
                {"key": "tag", "name": "分类", "value": [
                    {"n": "情感", "v": "qinggan"}, {"n": "音乐推荐", "v": "music"},
                    {"n": "有声书", "v": "sound"}, {"n": "脱口秀", "v": "talk"},
                    {"n": "创作翻唱", "v": "create"}, {"n": "电音", "v": "dianyin"},
                    {"n": "知识", "v": "zhishi"}, {"n": "二次元", "v": "erciyuan"},
                    {"n": "明星专区", "v": "star"}, {"n": "生活", "v": "shenghuo"},
                    {"n": "亲子", "v": "qinzi"}
                ]}
            ],
            "album": [
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部", "v": "index"}, {"n": "华语", "v": "huayu"},
                    {"n": "欧美", "v": "oumei"}, {"n": "韩国", "v": "hanguo"},
                    {"n": "日本", "v": "riben"}
                ]}
            ],
            "mv": [
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部", "v": "index"}, {"n": "内地", "v": "neidi"},
                    {"n": "港台", "v": "gangtai"}, {"n": "欧美", "v": "oumei"},
                    {"n": "韩国", "v": "hanguo"}, {"n": "日本", "v": "riben"}
                ]},
                {"key": "type", "name": "类型", "value": [
                    {"n": "全部", "v": "index"}, {"n": "官方版", "v": "guanfang"},
                    {"n": "原声", "v": "yuansheng"}, {"n": "现场版", "v": "xianchang"},
                    {"n": "网易出品", "v": "wangyi"}
                ]},
                {"key": "sort", "name": "排序", "value": [
                    {"n": "最新", "v": "new"}, {"n": "最热", "v": "hot"},
                    {"n": "上升最快", "v": "rise"}
                ]}
            ]
        }
        return {"class": classes, "filters": filters, "list": []}

    def homeVideoContent(self):
        doc = self.getpq("/")
        if self._verify_page(doc):
            print("⚠️ 世纪音乐首页需要验证，自动切换备用数据源")
            return self._fallback_category("home", 1, {})
        items = self._song_items(doc, "🏠 首页歌曲")

        # 首页可能混有推荐 MV，同样按用户要求使用无图列表展示。
        seen = {x["vod_id"] for x in items}
        for li, a, href in self._named_rows(doc, "/mp4/"):
            vod_id = self._abs(href)
            if vod_id in seen:
                continue
            seen.add(vod_id)
            items.append({
                "vod_id": vod_id,
                "vod_name": self._clean(a.text() or a.attr("title") or "高清MV"),
                "vod_pic": "",
                "vod_remarks": "🎬 首页MV",
                "style": {"type": "list"}
            })
        return {"list": items[:100]}

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        extend = extend or {}

        if tid == "home":
            return self.homeVideoContent()

        if tid in ("new", "top"):
            url = f"/list/{tid}.html" if pg == 1 else f"/list/{tid}/{pg}.html"
            doc = self.getpq(url)
            remark = "📈 新歌" if tid == "new" else "📊 热歌"
            items = self._song_items(doc, remark)
            if self._verify_page(doc) or not items:
                return self._fallback_category(tid, pg, extend)
            return self._page_result(items, pg, doc, 68)

        if tid == "singer":
            area = extend.get("area", "huayu")
            sex = extend.get("sex", "girl")
            char = extend.get("char", "index")
            base = f"/singerlist/{area}/{sex}/{char}"
            url = f"{base}.html" if pg == 1 else f"{base}/{pg}.html"
            doc = self.getpq(url)
            items = self._picture_items(doc, "/singer/", "👤 歌手", {"type": "oval", "ratio": 1}, is_singer=True)
            if self._verify_page(doc) or not items:
                return self._fallback_category(tid, pg, extend)
            return self._page_result(items, pg, doc, 96)

        if tid == "playlist":
            tag = extend.get("tag", "index")
            url = f"/playlists/{tag}.html" if pg == 1 else f"/playlists/{tag}/{pg}.html"
            doc = self.getpq(url)
            items = self._picture_items(doc, "/playlist/", "💎 歌单", {"type": "rect", "ratio": 1.42})
            if self._verify_page(doc) or not items:
                return self._fallback_category(tid, pg, extend)
            return self._page_result(items, pg, doc)

        if tid == "radio":
            tag = extend.get("tag", "qinggan")
            url = f"/radiolists/{tag}.html" if pg == 1 else f"/radiolists/{tag}/{pg}.html"
            doc = self.getpq(url)
            items = self._picture_items(doc, "/djradio/", "💗 电台", {"type": "rect", "ratio": 1.42})
            if self._verify_page(doc) or not items:
                return self._fallback_category(tid, pg, extend)
            return self._page_result(items, pg, doc, 50)

        if tid == "album":
            area = extend.get("area", "index")
            url = f"/albumlist/{area}.html" if pg == 1 else f"/albumlist/{area}/{pg}.html"
            doc = self.getpq(url)
            items = self._picture_items(doc, "/album/", "💿 新碟", {"type": "rect", "ratio": 1.42})
            if self._verify_page(doc) or not items:
                return self._fallback_category(tid, pg, extend)
            return self._page_result(items, pg, doc)

        if tid == "mv":
            area = extend.get("area", "index")
            type_ = extend.get("type", "index")
            sort = extend.get("sort", "new")
            self.current_category = {"area": area, "type": type_, "sort": sort, "page": pg}
            url = self._build_mv_url(area, type_, sort, pg)
            doc = self.getpq(url)
            items = self._picture_items(doc, "/mp4/", "🎬 高清MV", {"type": "rect", "ratio": 1.78}, is_mv=True)
            if self._verify_page(doc) or not items:
                return self._fallback_category(tid, pg, extend)
            return self._page_result(items, pg, doc)

        return {"list": [], "page": pg, "pagecount": pg, "limit": 30, "total": 0}

    def _playlist_from_doc(self, doc, path="/mp3/"):
        episodes = []
        for li, a, href in self._named_rows(doc, path):
            name = self._clean_song_name(a.text() or a.attr("title") or "播放")
            if path == "/mp3/":
                media_id = href.split('/')[-1].replace('.html', '')
                media_url = f"{self.host}/data/down.php?ac=music&id={media_id}"
            else:
                # 电台节目先交给 playerContent，再从节目页提取真实音频 ID。
                media_url = self._abs(href)
            episodes.append(f"{name}${self.e64('0@@@@' + media_url)}")
        return "#".join(episodes)

    def _wy_audio_url(self, song_id):
        return f"{self.music_url_api}/meting/?server=netease&type=url&id={song_id}"

    def _wy_detail(self, vod_id):
        """公开备用源详情与播放列表。"""
        m = re.match(r"wy_(song|artist|playlist|radio|album|mv)_(\d+)$", str(vod_id))
        if not m:
            return {"list": []}
        kind, media_id = m.group(1), m.group(2)
        name, pic, content, source = "世纪音乐", "", "备用公开音乐源", "音乐专线"
        play_urls = []

        if kind == "song":
            data = self._api_json("/api/song/detail/", {"ids": f"[{media_id}]"})
            songs = data.get("songs") or []
            song = songs[0] if songs else {"id": media_id, "name": "播放歌曲"}
            artist = self._wy_artist(song)
            name = f"{artist} - {song.get('name')}" if artist else (song.get("name") or "播放歌曲")
            album = song.get("album") or {}
            pic = album.get("picUrl") or album.get("blurPicUrl") or ""
            play_urls.append(f"{name}${self.e64('0@@@@' + self._wy_audio_url(media_id))}")

        elif kind == "artist":
            data = self._api_json(f"/api/artist/{media_id}")
            artist = data.get("artist") or {}
            name = artist.get("name") or "歌手歌曲"
            pic = artist.get("picUrl") or artist.get("img1v1Url") or ""
            for song in (data.get("hotSongs") or [])[:80]:
                sid = song.get("id")
                if sid:
                    play_urls.append(f"{song.get('name') or '歌曲'}${self.e64('0@@@@' + self._wy_audio_url(sid))}")
            source = "👤 歌手歌曲"

        elif kind == "playlist":
            data = self._api_json("/api/playlist/detail", {"id": media_id})
            result = data.get("result") or {}
            name = result.get("name") or "歌单歌曲"
            pic = result.get("coverImgUrl") or ""
            for song in (result.get("tracks") or [])[:100]:
                sid = song.get("id")
                if sid:
                    play_urls.append(f"{song.get('name') or '歌曲'}${self.e64('0@@@@' + self._wy_audio_url(sid))}")
            source = "💎 歌单歌曲"

        elif kind == "radio":
            data = self._api_json("/api/dj/program/byradio", {"radioId": media_id, "limit": 100, "offset": 0})
            programs = data.get("programs") or []
            if programs:
                radio = programs[0].get("radio") or {}
                name = radio.get("name") or "电台节目"
                pic = radio.get("picUrl") or programs[0].get("coverUrl") or ""
            for program in programs:
                song = program.get("mainSong") or {}
                sid = song.get("id")
                if sid:
                    play_urls.append(f"{program.get('name') or song.get('name') or '节目'}${self.e64('0@@@@' + self._wy_audio_url(sid))}")
            source = "💗 电台节目"

        elif kind == "album":
            data = self._api_json(f"/api/v1/album/{media_id}")
            album = data.get("album") or {}
            name = album.get("name") or "新碟歌曲"
            pic = album.get("picUrl") or ""
            for song in (data.get("songs") or [])[:100]:
                sid = song.get("id")
                if sid:
                    play_urls.append(f"{song.get('name') or '歌曲'}${self.e64('0@@@@' + self._wy_audio_url(sid))}")
            source = "💿 新碟歌曲"

        elif kind == "mv":
            mv = self._mv_detail_cached(media_id)
            name = mv.get("name") or "高清MV"
            pic = mv.get("cover") or ""
            brs = mv.get("brs") or {}
            routes = []
            if brs.get("480"):
                routes.append(("🎬 标清", "标清", brs["480"]))
            if brs.get("240"):
                routes.append(("🎬 流畅", "流畅", brs["240"]))
            # 少数资源只有 720/1080 或单一清晰度，仍保留最低的可播线路。
            if not routes and brs:
                quality, media_url = sorted(brs.items(), key=lambda x: int(x[0]))[0]
                routes.append((f"🎬 {quality}P", f"{quality}P", media_url))
            if routes:
                play_from = []
                play_group = []
                for route_name, episode_name, media_url in routes:
                    # Android TV 对明文 HTTP 限制较多，网易视频域名支持 HTTPS。
                    if str(media_url).startswith("http://"):
                        media_url = "https://" + str(media_url)[7:]
                    play_from.append(route_name)
                    play_group.append(f"{episode_name}${self.e64('0@@@@' + media_url)}")
                return {"list": [{
                    "vod_id": vod_id, "vod_name": name, "vod_pic": pic,
                    "vod_content": "高清MV · 标清/流畅双线路",
                    "vod_play_from": "$$$".join(play_from),
                    "vod_play_url": "$$$".join(play_group)
                }]}
            return {"list": []}

        if not play_urls:
            play_urls.append(f"暂无可用地址${self.e64('0@@@@' + self.host)}")
        return {"list": [{
            "vod_id": vod_id, "vod_name": name, "vod_pic": pic,
            "vod_content": content, "vod_play_from": source,
            "vod_play_url": "#".join(play_urls)
        }]}

    def detailContent(self, ids):
        raw_id = ids[0]
        if str(raw_id).startswith("wy_"):
            return self._wy_detail(str(raw_id))
        url = self._abs(raw_id)

        if "/mp4/" in url:
            return self._get_mv_detail_with_playlist(self.getpq(url), url)
        if "/mp3/" in url:
            return self._get_song_detail_with_playlist(self.getpq(url), url)

        doc = self.getpq(url)
        title = self._clean(doc("h1").eq(0).text() or doc("title").text().split("-")[0])
        pic = doc(".singer_info .pic img, .playhimg img, .djpic img, .pic img").eq(0).attr("src") or ""
        vod = {
            "vod_id": url,
            "vod_name": title,
            "vod_pic": self._get_image(pic, is_singer="/singer/" in url) if pic else "",
            "vod_content": self._get_content(doc, url)
        }

        if "/djradio/" in url:
            playlist = self._playlist_from_doc(doc, "/radio/")
            vod["vod_play_from"] = "💗 电台节目"
            vod["vod_play_url"] = playlist or f"暂无节目${self.e64('0@@@@' + url)}"
        elif "/radio/" in url:
            vod["vod_play_from"] = "💗 电台节目"
            vod["vod_play_url"] = f"播放${self.e64('0@@@@' + url)}"
        elif any(part in url for part in ("/singer/", "/playlist/", "/album/")):
            playlist = self._playlist_from_doc(doc, "/mp3/")
            if "/singer/" in url:
                source = "👤 歌手歌曲"
            elif "/album/" in url:
                source = "💿 新碟歌曲"
            else:
                source = "💎 歌单歌曲"
            vod["vod_play_from"] = source
            vod["vod_play_url"] = playlist or f"暂无歌曲${self.e64('0@@@@' + url)}"
        else:
            vod["vod_play_from"] = "世纪音乐"
            vod["vod_play_url"] = f"打开${self.e64('0@@@@' + url)}"
        return {"list": [vod]}

    def searchContent(self, key, quick, pg="1"):
        pg = int(pg or 1)
        doc = self.getpq(f"/so.php?wd={quote(key)}&page={pg}")
        if self._verify_page(doc):
            return self._fallback_search(key, pg)
        items = []
        seen = set()
        kinds = [
            ("/mp3/", "🎵 歌曲", {"type": "list"}, False, False),
            ("/mp4/", "🎬 MV", {"type": "rect", "ratio": 1.78}, False, True),
            ("/singer/", "👤 歌手", {"type": "oval", "ratio": 1}, True, False),
            ("/playlist/", "💎 歌单", {"type": "rect", "ratio": 1.42}, False, False),
            ("/album/", "💿 新碟", {"type": "rect", "ratio": 1.42}, False, False),
            ("/djradio/", "💗 电台", {"type": "rect", "ratio": 1.42}, False, False)
        ]
        for path, remark, style, is_singer, is_mv in kinds:
            for item in self._picture_items(doc, path, remark, style, is_singer, is_mv):
                if item["vod_id"] in seen:
                    continue
                seen.add(item["vod_id"])
                if path == "/mp3/":
                    item["vod_pic"] = ""
                    item["style"] = {"type": "list"}
                items.append(item)
        if not items:
            return self._fallback_search(key, pg)
        return self._page_result(items, pg, doc)

    def _fallback_search(self, key, pg):
        data = self._api_json("/netease/search/song/", {
            "keywords": key, "pn": int(pg), "limit": 30
        }, self.music_url_api)
        items = []
        if isinstance(data, list):
            for song in data:
                url = str(song.get("url") or "")
                sid_match = re.search(r"[?&]id=(\d+)", url)
                if not sid_match:
                    continue
                artist = song.get("artist") or ""
                name = song.get("name") or "未知歌曲"
                items.append({
                    "vod_id": f"wy_song_{sid_match.group(1)}",
                    "vod_name": f"{artist} - {name}" if artist else name,
                    "vod_pic": "", "vod_remarks": "🔍 搜索歌曲",
                    "style": {"type": "list"}
                })
        return {"list": items, "page": int(pg), "pagecount": int(pg) + 1 if len(items) >= 30 else int(pg), "limit": 30, "total": 9999 if items else 0}

    def _clean_song_name(self, name):
        if not name:
            return ""
        name = re.sub(r'\s*-\s*$', '', name)
        name = re.sub(r'^\s*-\s*', '', name)
        name = re.sub(r'\s+', ' ', name)
        return name.strip()

    def _get_content(self, doc, url):
        content = []
        if desc := doc(".singer_info .info p").text():
            content.append(desc)
        elif singer := doc(".play_singer .name a").text():
            content.append(f"歌手：{singer}")
            if album := doc('a[href*="/album/"]').text():
                content.append(f"专辑：{album}")
        return "\n".join(content) if content else "世纪音乐网"

    def _clean(self, text):
        if not text:
            return ""
        text = re.sub(r'(世纪音乐网|MP3免费下载|LRC动态歌词下载|高清MV|车载MV|夜店视频|热门榜单|全部歌曲|第\d+页|刷新|首页|免责声明|版权|非営利性|自动收录|联系邮箱|oeecc#foxmail\.com)', '', text, flags=re.I)
        return text.strip()

    def getpq(self, url):
        for i in range(3):
            try:
                full_url = self._abs(url)
                print(f"🌐 请求: {full_url}")
                
                resp = self.session.get(
                    full_url, 
                    timeout=15,
                    headers={
                        "User-Agent": self.headers["User-Agent"],
                        "Referer": self.host + "/",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
                        "Accept-Encoding": "gzip, deflate",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1"
                    }
                )
                
                resp.encoding = 'utf-8'
                if resp.status_code == 200 and resp.text:
                    print(f"✅ 请求成功: {full_url}")
                    return pq(resp.text)
                else:
                    print(f"⚠️ 请求失败: {resp.status_code}")
                    
            except Exception as e:
                print(f"⚠️ 请求异常 ({i+1}/3): {url} - {e}")
                time.sleep(1)
        
        print(f"❌ 请求最终失败: {url}")
        return pq("<html></html>")

    def _abs(self, url):
        if not url:
            return ""
        if url.startswith("http"):
            return url
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self.host + url
        return self.host + "/" + url

    def e64(self, text):
        return b64encode(text.encode("utf-8")).decode("utf-8")

    def d64(self, text):
        try:
            return b64decode(text.encode("utf-8")).decode("utf-8")
        except:
            return text
