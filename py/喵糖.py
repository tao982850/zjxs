#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
喵糖cos (moyudh.mtcos.vip) Python Spider
兼容 FongMi/TVBox dr_py

站点结构: 自定义 SPA (TanStack Router + Vue/React)
API: 纯 JSON API, 无需 HTML 解析
内容类型: 写真图集 + 视频

首页分类: 4种排序 (最新/收藏/点赞/浏览)
筛选: 标签 (JK制服/白丝/Cosplay等, 从 /api/recommended-tags 动态获取)
分页: cursor 游标分页 (内存缓存, 顺序翻页)
详情: /api/albums/{id} -> 图片预览(3张) + 视频(HLS直链)
搜索: /api/albums/cursor?search={keyword}
播放: 视频 m3u8 直链(parse=0) / 图片直链(parse=0)
选集ID: {albumId}:{type}:{index}  (type=v视频, i图片)
限制: 未登录仅返回3张预览图, 完整图集需VIP
"""

import json, sys, os, time, re
from urllib.parse import quote, urlencode

# ==================== FongMi/TV 基类兼容 ====================
sys.path.append('..')
try:
    from base.spider import Spider as _BaseSpider
except ImportError:
    try:
        import requests as _rq
        class _BaseSpider:
            def fetch(self, url, headers=None, timeout=15, **kw):
                kw.pop('timeout', None)
                return _rq.get(url, headers=headers, timeout=15, **kw)
            def post(self, url, json=None, headers=None, timeout=15, **kw):
                return _rq.post(url, json=json, headers=headers, timeout=15, **kw)
    except ImportError:
        _BaseSpider = object

try:
    import requests
    from urllib3 import disable_warnings
    disable_warnings()
except ImportError:
    requests = None

try:
    from curl_cffi import requests as cffi_requests
    _HAS_CFFI = True
except ImportError:
    cffi_requests = None
    _HAS_CFFI = False

try:
    import ssl
    _HAS_SSL = True
except ImportError:
    _HAS_SSL = False


class _MockResponse:
    """http.client 降级用的模拟 Response"""
    def __init__(self, status_code, text, headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.content = text.encode('utf-8', errors='ignore') if text else b''

    def json(self):
        try:
            return json.loads(self.text)
        except Exception:
            return {}


class Spider(_BaseSpider):
    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.host = "https://moyudh.mtcos.vip"
        self.header = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 11; KB2000) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": self.host + "/",
            "Accept": "application/json, text/html, */*",
        }
        self._cursor_cache = {}   # {cache_key: [None, cursor1, cursor2, ...]}
        self._tags = None
        self._classes = None
        self._filters = None

    # ==================== init ====================
    def init(self, extend=''):
        self._build_categories()
        try:
            data = self._api_get('/api/recommended-tags')
            tags = data.get('tags', [])
            if tags:
                self._tags = tags
        except Exception:
            pass
        if not self._tags:
            self._tags = self._default_tags()

    def _build_categories(self):
        self._classes = [
            {"type_name": "最新发布", "type_id": "latest"},
            {"type_name": "热门收藏", "type_id": "collections_desc"},
            {"type_name": "热门点赞", "type_id": "likes_desc"},
            {"type_name": "热门浏览", "type_id": "views_desc"},
        ]
        self._filters = {}

    def _default_tags(self):
        return [
            {"name": "室内"}, {"name": "Cosplay"}, {"name": "黑发"}, {"name": "长发"},
            {"name": "素人"}, {"name": "丰满"}, {"name": "模特"}, {"name": "淡颜"},
            {"name": "棕发"}, {"name": "浓颜"}, {"name": "黑丝"}, {"name": "性感"},
            {"name": "足控"}, {"name": "户外"}, {"name": "卧室"}, {"name": "短发"},
            {"name": "日系"}, {"name": "腿控"}, {"name": "白丝"}, {"name": "JK制服"},
        ]

    def _get_filters(self):
        tag_values = [{"n": "全部", "v": ""}]
        for t in (self._tags or []):
            name = t.get('name', '')
            if name:
                tag_values.append({"n": name, "v": name})
        filter_list = [{"key": "tag", "name": "标签", "value": tag_values}]
        filters = {}
        for c in (self._classes or []):
            filters[c['type_id']] = filter_list
        return filters

    # ==================== HTTP 降级 (四级) ====================
    def _fetch(self, url, headers=None, timeout=15):
        h = headers or self.header
        # Level 0: curl_cffi (TLS 指纹伪装)
        if _HAS_CFFI:
            try:
                r = cffi_requests.get(url, headers=h, timeout=timeout, impersonate="chrome", verify=False)
                if r and r.status_code == 200 and len(r.text) > 50:
                    return r
            except Exception:
                pass
        # Level 1: requests
        if requests:
            try:
                r = requests.get(url, headers=h, timeout=timeout, verify=False)
                if r and r.status_code == 200:
                    return r
            except Exception:
                pass
        # Level 2: base.spider.fetch
        try:
            r = self.fetch(url, headers=h, timeout=timeout)
            if r and self._resp_text(r) and len(self._resp_text(r)) > 50:
                return r
        except Exception:
            pass
        # Level 3: http.client 兜底
        try:
            import http.client
            from urllib.parse import urlparse
            p = urlparse(url)
            conn_cls = http.client.HTTPSConnection if p.scheme == 'https' else http.client.HTTPConnection
            conn = conn_cls(p.hostname, p.port or (443 if p.scheme == 'https' else 80), timeout=timeout)
            path = p.path
            if p.query:
                path += '?' + p.query
            req_headers = dict(h)
            req_headers['Host'] = p.hostname
            conn.request("GET", path, headers=req_headers)
            resp = conn.getresponse()
            data = resp.read().decode('utf-8', errors='ignore')
            conn.close()
            return _MockResponse(resp.status, data, dict(resp.headers))
        except Exception:
            pass
        return _MockResponse(0, '')

    @staticmethod
    def _resp_text(resp):
        if resp is None:
            return ''
        if isinstance(resp, str):
            return resp
        if isinstance(resp, bytes):
            return resp.decode('utf-8', errors='ignore')
        val = getattr(resp, 'text', None)
        if val and isinstance(val, str):
            return val
        content = getattr(resp, 'content', None)
        if content:
            if isinstance(content, bytes):
                return content.decode('utf-8', errors='ignore')
            return str(content)
        try:
            return resp.read().decode('utf-8', errors='ignore')
        except Exception:
            return ''

    def _api_get(self, path, params=None):
        url = self.host + path
        if params:
            url += '?' + urlencode(params, quote_via=quote)
        text = self._resp_text(self._fetch(url, self.header))
        try:
            return json.loads(text) if text else {}
        except Exception:
            return {}

    # ==================== Cursor 游标缓存 ====================
    def _get_cursor(self, cache_key, pg):
        if cache_key not in self._cursor_cache:
            return None
        cursors = self._cursor_cache[cache_key]
        idx = pg - 1
        if 0 <= idx < len(cursors):
            return cursors[idx]
        return None

    def _set_cursor(self, cache_key, pg, next_cursor):
        if cache_key not in self._cursor_cache:
            self._cursor_cache[cache_key] = []
        cursors = self._cursor_cache[cache_key]
        while len(cursors) <= pg:
            cursors.append(None)
        cursors[pg] = next_cursor

    # ==================== 专辑解析 ====================
    def _parse_albums(self, data):
        vod_list = []
        albums = data.get('albums', [])
        for album in albums:
            vod_id = str(album.get('id', ''))
            title = album.get('title') or album.get('simpleTitle') or '未知'
            pic = album.get('coverImgUrl') or ''
            if not pic:
                actor = album.get('actor', {})
                pic = actor.get('avatarUrl') or ''
            total_imgs = album.get('totalImgs', 0)
            total_videos = album.get('totalVideos', 0)
            remarks = f"{total_imgs}P"
            if total_videos > 0:
                remarks += f" {total_videos}V"
            label = album.get('minVisibleLabel')
            if label:
                remarks = f"[{label}] {remarks}"
            vod_list.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks,
            })
        return vod_list

    # ==================== homeContent ====================
    def homeContent(self, filterable=False):
        result = {
            "class": self._classes or [],
            "filters": self._get_filters(),
        }
        try:
            data = self._api_get('/api/albums/cursor', {'limit': '20', 'sort': 'latest'})
            result["list"] = self._parse_albums(data)
        except Exception:
            result["list"] = []
        return result

    # ==================== categoryContent ====================
    def categoryContent(self, tid, pg=1, filterable=False, extend=None):
        try:
            pg = int(pg)
        except (TypeError, ValueError):
            pg = 1
        if pg < 1:
            pg = 1

        tag = ''
        if extend:
            if isinstance(extend, str):
                try:
                    extend = json.loads(extend)
                except Exception:
                    extend = {}
            if isinstance(extend, dict):
                tag = str(extend.get('tag', '') or '')

        valid_sorts = ('latest', 'collections_desc', 'likes_desc', 'views_desc', 'createdAt_desc')
        sort = tid if tid in valid_sorts else 'collections_desc'
        cache_key = f"{sort}:{tag}"

        cursor = self._get_cursor(cache_key, pg)

        params = {'limit': '20', 'sort': sort}
        if cursor:
            params['cursor'] = cursor
        if tag:
            params['tag'] = tag

        data = self._api_get('/api/albums/cursor', params)
        vod_list = self._parse_albums(data)

        next_cursor = data.get('nextCursor')
        has_more = data.get('hasMore', False)
        if next_cursor and has_more:
            self._set_cursor(cache_key, pg, next_cursor)

        pagecount = pg + 1 if has_more else pg

        return {
            "list": vod_list,
            "page": str(pg),
            "pagecount": str(pagecount),
            "limit": "20",
            "total": str(pagecount * 20),
        }

    # ==================== detailContent ====================
    def detailContent(self, ids):
        vod_id = ids[0] if isinstance(ids, list) else str(ids)
        data = self._api_get(f'/api/albums/{vod_id}')
        album = data.get('album')
        if not album:
            return {"list": []}

        title = album.get('title') or '未知'
        pic = album.get('coverImgUrl') or ''
        actor_obj = album.get('actor', {})
        actor_name = actor_obj.get('name', '')

        total_imgs = album.get('totalImgs', 0)
        total_videos = album.get('totalVideos', 0)
        views = album.get('views', 0)
        likes = album.get('likeCount', 0)
        collects = album.get('collectCount', 0)

        album_tags = album.get('albumTags', [])
        tag_names = [t.get('tag', {}).get('name', '') for t in album_tags if t.get('tag')]
        tag_str = ' '.join(tag_names[:8]) if tag_names else ''

        created = album.get('createdAt', '')
        year = created[:4] if created else ''

        remarks = f"{total_imgs}P"
        if total_videos > 0:
            remarks += f" {total_videos}V"

        content_parts = []
        content_parts.append(f"图片: {total_imgs}张")
        if total_videos > 0:
            content_parts.append(f"视频: {total_videos}个")
        content_parts.append(f"浏览: {views}")
        content_parts.append(f"点赞: {likes}")
        content_parts.append(f"收藏: {collects}")
        if actor_obj.get('description'):
            content_parts.append(f"\n{actor_obj['description']}")

        vod = {
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": pic,
            "vod_actor": actor_name,
            "vod_year": year,
            "vod_area": "",
            "vod_type": tag_str,
            "vod_remarks": remarks,
            "vod_content": ' | '.join(content_parts),
        }

        # 播放源
        play_from = []
        play_url = []

        # 视频线路
        videos_url = album.get('videosUrl') or []
        if not videos_url:
            video_media = album.get('videoMedia') or []
            videos_url = [vm.get('src', '') for vm in video_media if vm.get('src')]
        if videos_url:
            video_eps = []
            for i in range(len(videos_url)):
                video_eps.append(f"视频{i+1}${vod_id}:v:{i}")
            play_from.append("视频")
            play_url.append("#".join(video_eps))

        # 图片线路
        imgs_url = album.get('imgsUrl') or []
        if not imgs_url:
            images = album.get('images') or []
            imgs_url = [img.get('displayUrl', '') for img in images if img.get('displayUrl')]
        if imgs_url:
            img_eps = []
            for i in range(len(imgs_url)):
                img_eps.append(f"图片{i+1}${vod_id}:i:{i}")
            play_from.append("图片")
            play_url.append("#".join(img_eps))

        if play_from:
            vod["vod_play_from"] = "$$$".join(play_from)
            vod["vod_play_url"] = "$$$".join(play_url)

        return {"list": [vod]}

    # ==================== searchContent ====================
    def searchContent(self, key, quick=False, pg=1):
        if not key:
            return []
        try:
            pg = int(pg)
        except (TypeError, ValueError):
            pg = 1
        if pg < 1:
            pg = 1

        cache_key = f"search:{key}"
        cursor = self._get_cursor(cache_key, pg)

        params = {'limit': '20', 'sort': 'latest', 'search': key}
        if cursor:
            params['cursor'] = cursor

        data = self._api_get('/api/albums/cursor', params)
        vod_list = self._parse_albums(data)

        next_cursor = data.get('nextCursor')
        has_more = data.get('hasMore', False)
        if next_cursor and has_more:
            self._set_cursor(cache_key, pg, next_cursor)

        return vod_list

    # ==================== playerContent ====================
    def playerContent(self, flag, id, vipFlags=None):
        parts = str(id).split(':')
        if len(parts) < 3:
            return {"parse": 0, "url": "", "header": {}}

        album_id = parts[0]
        media_type = parts[1]
        try:
            index = int(parts[2])
        except ValueError:
            return {"parse": 0, "url": "", "header": {}}

        url = ''
        data = self._api_get(f'/api/albums/{album_id}')
        album = data.get('album', {})

        if media_type == 'v':
            videos_url = album.get('videosUrl') or []
            if not videos_url:
                video_media = album.get('videoMedia') or []
                videos_url = [vm.get('src', '') for vm in video_media if vm.get('src')]
            if 0 <= index < len(videos_url):
                url = videos_url[index]
        elif media_type == 'i':
            imgs_url = album.get('imgsUrl') or []
            if not imgs_url:
                images = album.get('images') or []
                imgs_url = [img.get('displayUrl', '') for img in images if img.get('displayUrl')]
            if 0 <= index < len(imgs_url):
                url = imgs_url[index]

        if not url:
            return {"parse": 0, "url": "", "header": {}}

        return {
            "parse": 0,
            "url": url,
            "header": {
                "User-Agent": self.header["User-Agent"],
                "Referer": self.host + "/",
            },
        }


# ==================== 模块级接口 ====================
_spider = None

def init(extend=''):
    global _spider
    if _spider is None:
        _spider = Spider()
    _spider.init(extend)
    return _spider

def homeContent(filter=False):
    if _spider is None:
        return {"class": [], "filters": {}, "list": []}
    return _spider.homeContent(filter)

def categoryContent(tid, pg, filter, extend):
    if _spider is None:
        return {"list": [], "page": "1", "pagecount": "1", "limit": "20", "total": "0"}
    return _spider.categoryContent(tid, pg, filter, extend)

def detailContent(ids):
    if _spider is None:
        return {"list": []}
    return _spider.detailContent(ids)

def searchContent(key, quick, pg):
    if _spider is None:
        return []
    return _spider.searchContent(key, quick, pg)

def playerContent(flag, id, vipFlags):
    if _spider is None:
        return {"parse": 0, "url": "", "header": {}}
    return _spider.playerContent(flag, id, vipFlags)


# ==================== CLI 测试 ====================
if __name__ == '__main__':
    print("=" * 60)
    print("喵糖cos (moyudh.mtcos.vip) TVBox 插件测试")
    print("=" * 60)

    sp = init()
    passed = 0
    failed = 0
    test_album_id = None
    test_ep_id = None

    # Test 1: homeContent
    print("\n[1/7] homeContent")
    try:
        home = sp.homeContent()
        classes = home.get('class', [])
        filters = home.get('filters', {})
        home_list = home.get('list', [])
        print(f"  分类数: {len(classes)}")
        for c in classes:
            print(f"    - {c['type_name']} ({c['type_id']})")
        first_key = list(filters.keys())[0] if filters else None
        if first_key:
            tag_count = len(filters[first_key][0]['value']) if filters[first_key] else 0
            print(f"  筛选标签数: {tag_count}")
        print(f"  首页视频数: {len(home_list)}")
        if home_list:
            print(f"  示例: {home_list[0]['vod_name'][:30]} | {home_list[0]['vod_remarks']}")
            test_album_id = home_list[0]['vod_id']
        assert len(classes) > 0, "无分类"
        assert len(home_list) > 0, "首页无视频"
        print("  PASS")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Test 2: categoryContent (page 1)
    print("\n[2/7] categoryContent (热门收藏, page 1)")
    try:
        cat = sp.categoryContent('collections_desc', 1, True, {})
        cat_list = cat.get('list', [])
        print(f"  视频数: {len(cat_list)}")
        print(f"  pagecount: {cat.get('pagecount')}")
        if cat_list:
            print(f"  示例: {cat_list[0]['vod_name'][:30]} | {cat_list[0]['vod_remarks']}")
            if not test_album_id:
                test_album_id = cat_list[0]['vod_id']
        assert len(cat_list) > 0, "分类无视频"
        print("  PASS")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Test 3: categoryContent (page 2)
    print("\n[3/7] categoryContent (热门收藏, page 2)")
    try:
        cat2 = sp.categoryContent('collections_desc', 2, True, {})
        cat2_list = cat2.get('list', [])
        print(f"  视频数: {len(cat2_list)}")
        if cat2_list:
            print(f"  示例: {cat2_list[0]['vod_name'][:30]}")
        assert len(cat2_list) > 0, "第2页无视频"
        print("  PASS")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Test 4: categoryContent with tag filter
    print("\n[4/7] categoryContent (最新, tag=Cosplay)")
    try:
        cat_tag = sp.categoryContent('latest', 1, True, '{"tag":"Cosplay"}')
        cat_tag_list = cat_tag.get('list', [])
        print(f"  视频数: {len(cat_tag_list)}")
        if cat_tag_list:
            print(f"  示例: {cat_tag_list[0]['vod_name'][:30]}")
        assert len(cat_tag_list) > 0, "标签筛选无视频"
        print("  PASS")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Test 5: detailContent
    print("\n[5/7] detailContent")
    try:
        if test_album_id:
            detail = sp.detailContent(test_album_id)
            detail_list = detail.get('list', [])
            if detail_list:
                vod = detail_list[0]
                print(f"  标题: {vod.get('vod_name', '')[:40]}")
                print(f"  演员: {vod.get('vod_actor', '')}")
                print(f"  备注: {vod.get('vod_remarks', '')}")
                print(f"  类型: {vod.get('vod_type', '')[:40]}")
                print(f"  简介: {vod.get('vod_content', '')[:80]}")
                play_from = vod.get('vod_play_from', '')
                play_url = vod.get('vod_play_url', '')
                print(f"  播放源: {play_from}")
                if play_url:
                    sources = play_url.split('$$$')
                    for i, src in enumerate(sources):
                        eps = [e for e in src.split('#') if e]
                        src_name = play_from.split('$$$')[i] if i < len(play_from.split('$$$')) else f"线路{i+1}"
                        print(f"    {src_name}: {len(eps)}集")
                    # Get first episode for player test
                    first_source = play_url.split('$$$')[0]
                    first_ep = first_source.split('#')[0]
                    if '$' in first_ep:
                        test_ep_id = first_ep.split('$')[1]
                        print(f"  测试集ID: {test_ep_id}")
                assert play_url, "无播放源"
                print("  PASS")
                passed += 1
            else:
                print("  FAIL: 无详情")
                failed += 1
        else:
            print("  FAIL: 无测试ID")
            failed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Test 6: searchContent
    print("\n[6/7] searchContent")
    try:
        search_result = sp.searchContent('森萝', False, 1)
        if isinstance(search_result, dict):
            search_list = search_result.get('list', [])
        else:
            search_list = search_result
        print(f"  搜索结果数: {len(search_list)}")
        if search_list:
            print(f"  示例: {search_list[0]['vod_name'][:30]}")
        assert len(search_list) > 0, "搜索无结果"
        print("  PASS")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Test 7: playerContent
    print("\n[7/7] playerContent")
    try:
        if test_ep_id:
            player = sp.playerContent('视频', test_ep_id, None)
            url = player.get('url', '')
            parse = player.get('parse', 0)
            header = player.get('header', {})
            print(f"  播放URL: {url[:100]}..." if len(url) > 100 else f"  播放URL: {url}")
            print(f"  parse: {parse}")
            print(f"  header keys: {list(header.keys())}")
            assert url, "无播放URL"
            print("  PASS")
            passed += 1
        else:
            print("  FAIL: 无测试集ID")
            failed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Summary
    print("\n" + "=" * 60)
    total = passed + failed
    print(f"测试结果: {passed}/{total} 通过")
    if failed:
        print(f"失败: {failed} 项")
    print("=" * 60)
