# 蜜果-http://6i.pw/
# by @6666
import sys
import time
import json
import hashlib
import uuid
import re
from urllib.parse import quote, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.append('..')
from base.spider import Spider

class Spider(Spider):

    def init(self, extend=""):
        pass

    def getName(self):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    rhost='https://www.mgtv.com'

    host='https://pianku.api.mgtv.com'

    vhost='https://pcweb.api.mgtv.com'

    mhost='https://dc.bz.mgtv.com'

    shost='https://mobileso.bz.mgtv.com'

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; ) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.61 Chrome/126.0.6478.61 Not/A)Brand/8  Safari/537.36',
        'origin': rhost,
        'referer': f'{rhost}/'
    }

    # ---------- 新增辅助方法 ----------
    def _extract_vid(self, url):
        """从播放页URL中提取视频ID（vid）"""
        if not url:
            return None
        # 匹配 /b/xxx 或 /b/xxx? 或完整链接中的vid参数
        match = re.search(r'/b/([^/?]+)', url)
        if match:
            return match.group(1)
        # 若传入的是纯vid数字，直接返回
        if url.isdigit():
            return url
        return None

    def _get_mgtv_play_url(self, vid):
        """通过官方接口获取播放地址（含签名）"""
        params = {
            'vid': vid,
            'type': 'b',
            'platform': 'pcweb',
            'allowedRC': '1',
            '_support': '10000000',
            '_t': int(time.time() * 1000)
        }
        secret = 'LMFwh1k1m@pvt#Pt'
        sign_text = secret + ''.join(f'{k}{v}' for k, v in sorted(params.items()) if v is not None) + secret
        params['sign'] = hashlib.md5(sign_text.encode('utf-8')).hexdigest().upper()
        
        try:
            resp = self.fetch(
                f'{self.vhost}/player/getSource',
                params=params,
                headers=self.headers,
                timeout=10
            )
            if resp.status_code != 200:
                print(f'官方播放接口响应异常: {resp.status_code}')
                return None
            data = resp.json()
            stream = data.get('data', {}).get('stream', [])
            if stream:
                # 取最高清晰度（通常最后一个）
                return stream[-1].get('url')
            else:
                print('官方接口返回无流地址')
                return None
        except Exception as e:
            print(f'官方播放源获取失败: {e}')
            return None

    # ---------- 原有方法，增加超时和异常保护 ----------
    def homeContent(self, filter):
        result = {}
        cateManual = {
            "电影": "3",
            "电视剧": "2",
            "综艺": "1",
            "动画": "50",
            "少儿": "10",
            "纪录片": "51",
            "教育": "115",
            "新闻": "official:191",
            "短剧": "official:1947",
            "直播": "live"
        }
        classes = []
        filters = {}
        for k in cateManual:
            classes.append({
                'type_name': k,
                'type_id': cateManual[k]
            })
        filter_classes = [item for item in classes if item['type_id'].isdigit()]
        with ThreadPoolExecutor(max_workers=len(filter_classes)) as executor:
            results = executor.map(self.getf, filter_classes)
            for id, ft in results:
                if len(ft):filters[id] = ft
        result['class'] = classes
        result['filters'] = filters
        return result

    def homeVideoContent(self):
        try:
            data=self.fetch(f'{self.mhost}/dynamic/v1/channel/index/0/0/0/1000000/0/0/17/1354?type=17&version=5.0&t={str(int(time.time()*1000))}&_support=10000000', headers=self.headers, timeout=10).json()
        except Exception as e:
            print(f'首页获取失败: {e}')
            return {'list': []}
        videoList = []
        for i in data.get('data', []):
            if i.get('DSLList') and len(i['DSLList']):
                for j in i['DSLList']:
                    if j.get('data') and j['data'].get('items') and len(j['data']['items']):
                        for k in j['data']['items']:
                            videoList.append({
                                'vod_id': k["videoId"],
                                'vod_name': k['videoName'],
                                'vod_pic': k['img'],
                                'vod_year': k.get('cornerTitle'),
                                'vod_remarks': k.get('time') or k.get('desc'),
                            })
        return {'list':videoList}

    def categoryContent(self, tid, pg, filter, extend):
        if str(tid).startswith('official:'):
            return self.officialChannelContent(str(tid).split(':', 1)[1], pg)
        if str(tid) == 'live':
            return self.liveContent(pg)
        body={
            'allowedRC': '1',
            'platform': 'pcweb',
            'channelId': tid,
            'pn': pg,
            'pc': '80',
            'hudong': '1',
            '_support': '10000000'
        }
        body.update(extend)
        try:
            data=self.fetch(f'{self.host}/rider/list/pcweb/v3', params=body, headers=self.headers, timeout=10).json()
        except Exception as e:
            print(f'分类内容获取失败: {e}')
            return {'list': [], 'page': pg, 'pagecount': 0, 'limit': 80, 'total': 0}
        videoList = []
        for i in data.get('data', {}).get('hitDocs', []):
            videoList.append({
                'vod_id': i.get("playPartId"),
                'vod_name': i.get('title'),
                'vod_pic': i.get('img'),
                'vod_year': (i.get('rightCorner',{}) or {}).get('text') or i.get('year'),
                'vod_remarks': i.get('updateInfo')
            })
        result = {}
        result['list'] = videoList
        result['page'] = pg
        result['pagecount'] = 9999
        result['limit'] = 90
        result['total'] = 999999
        return result

    def detailContent(self, ids):
        if str(ids[0]).startswith('mgtvlive@'):
            live = self.parseLiveId(ids[0])
            vod = {
                'vod_name': live['name'],
                'vod_pic': live['pic'],
                'type_name': '直播',
                'vod_play_from': '芒果TV直播',
                'vod_play_url': f"直播${ids[0]}"
            }
            return {'list': [vod]}
        try:
            vbody={'allowedRC': '1', 'vid': ids[0], 'type': 'b', '_support': '10000000'}
            vdata=self.fetch(f'{self.vhost}/video/info', params=vbody, headers=self.headers, timeout=10).json()
        except Exception as e:
            print(f'详情获取失败: {e}')
            return {'list': []}
        d=vdata.get('data', {}).get('info', {}).get('detail', {})
        vod = {
            'vod_name': vdata.get('data', {}).get('info', {}).get('title'),
            'type_name': d.get('kind'),
            'vod_year': d.get('releaseTime'),
            'vod_area': d.get('area'),
            'vod_lang': d.get('language'),
            'vod_remarks': d.get('updateInfo'),
            'vod_actor': d.get('leader'),
            'vod_director': d.get('director'),
            'vod_content': d.get('story'),
            'vod_play_from': '芒果TV',
            'vod_play_url': ''
        }
        try:
            data,pdata=self.fetch_page_data('1', ids[0],True)
            pagecount=data.get('data', {}).get('total_page') or 1
            if int(pagecount)>1:
                pages = list(range(2, pagecount+1))
                page_results = {}
                with ThreadPoolExecutor(max_workers=10) as executor:
                    future_to_page = {
                        executor.submit(self.fetch_page_data, page, ids[0]): page
                        for page in pages
                    }
                    for future in as_completed(future_to_page):
                        page = future_to_page[future]
                        try:
                            result = future.result()
                            page_results[page] = result
                        except Exception as e:
                            print(f"Error fetching page {page}: {e}")
                for page in sorted(page_results.keys()):
                    pdata.extend(page_results[page])
            vod['vod_play_url'] = '#'.join(pdata)
        except Exception as e:
            print(f'分页数据获取失败: {e}')
            vod['vod_play_url'] = ''
        return {'list':[vod]}

    def searchContent(self, key, quick, pg="1"):
        try:
            data=self.fetch(f'{self.shost}/applet/search/v1?channelCode=mobile-wxap&q={key}&pn={pg}&pc=10&_support=10000000', headers=self.headers, timeout=10).json()
        except Exception as e:
            print(f'搜索失败: {e}')
            return {'list': [], 'page': pg}
        videoList = []
        for i in data.get('data', {}).get('contents', []):
            if i.get('data') and len(i['data']):
                k = i['data'][0]
                if k.get('vid') and k.get('img'):
                    try:
                        videoList.append({
                            'vod_id': k['vid'],
                            'vod_name': k['title'],
                            'vod_pic': k['img'],
                            'vod_year': (i.get('rightTopCorner',{}) or {}).get('text') or i.get('year'),
                            'vod_remarks': '/'.join(i.get('desc',[])),
                        })
                    except Exception as e:
                        print(f'搜索条目解析失败: {e}, 数据: {k}')
        return {'list':videoList,'page':pg}

    def playerContent(self, flag, id, vipFlags):
        # 直播处理（保持不变）
        if str(id).startswith('mgtvlive@'):
            live = self.parseLiveId(id)
            did = str(uuid.uuid4())
            params = {
                'cameraId': live['camera_id'],
                'activityId': live['activity_id'],
                'platform': '4',
                'appVersion': 'imgotv-pch5-1.2.3',
                'clientKey': 'pcweb',
                'auth_mode': '1',
                'local_definition': '',
                'init_definition': '2',
                'did': did,
                'uid': '',
                'token': '',
                '_t': str(int(time.time() * 1000)),
                'deviceId': did
            }
            secret = 'LMFwh1k1m@pvt#Pt'
            sign_text = secret + ''.join(
                f'{key}{params[key]}' for key in sorted(params)
                if params[key] is not None
            ) + secret
            params['_support'] = '10000000'
            params['sign'] = hashlib.md5(sign_text.encode('utf-8')).hexdigest().upper()
            try:
                data = self.fetch(
                    'https://pwlp.bz.mgtv.com/v1/live/source',
                    params=params,
                    headers=self.headers,
                    timeout=10
                ).json()
                sources = (data.get('data') or {}).get('sources') or []
                sources = [item for item in sources if item.get('url')]
                if sources:
                    source = max(sources, key=lambda item: int(item.get('definition') or 0))
                    return {
                        'jx': 0,
                        'parse': 0,
                        'url': source['url'],
                        'header': {
                            'User-Agent': self.headers['User-Agent'],
                            'Referer': f'{self.rhost}/live/'
                        }
                    }
            except Exception as e:
                print(f'直播播放地址获取失败: {e}')
            return {'jx': 0, 'parse': 0, 'url': '', 'header': {}}

        # ----- 普通视频处理（修复核心） -----
        play_url = str(id)
        # 尝试提取vid
        vid = self._extract_vid(play_url)
        if vid:
            print(f'尝试获取官方播放地址, vid={vid}')
            src = self._get_mgtv_play_url(vid)
            if src:
                return {
                    'jx': 0,
                    'parse': 0,
                    'url': src,
                    'header': {
                        'User-Agent': self.headers['User-Agent'],
                        'Referer': f'{self.rhost}/'
                    }
                }
            else:
                print('官方源获取失败，尝试备用解析')
        else:
            print('无法从URL提取vid，尝试第三方解析')

        # 备用第三方解析（多个候选，按顺序尝试）
        if play_url.startswith('/'):
            full_url = f'{self.rhost}{play_url}'
        else:
            full_url = play_url

        # 这里返回第一个可用的解析服务，实际播放器会加载playUrl + url
        # 如果希望自动切换，可在此循环尝试每个解析并检测可用性，但会增加耗时，故仅返回一个列表
        # 为增加成功率，使用多个解析源（用户可自行替换）
        backup_parsers = [
            'https://jx.aidouer.net/?url=',
            'https://jx.parwix.com:4433/player/?url=',
            'http://jx.618g.com/?url=',
        ]
        # 返回第一个解析（若需轮换可在此逻辑扩展）
        return {
            'jx': 0,
            'parse': 1,
            'playUrl': backup_parsers[0],   # 默认使用第一个
            'url': full_url,
            'header': {
                'User-Agent': self.headers['User-Agent'],
                'Referer': f'{self.rhost}/'
            }
        }

    def localProxy(self, param):
        pass

    def getf(self, body):
        params = {
            'allowedRC': '1',
            'channelId': body['type_id'],
            'platform': 'pcweb',
            '_support': '10000000',
        }
        try:
            data = self.fetch(f'{self.host}/rider/config/channel/v1', params=params, headers=self.headers, timeout=10).json()
        except Exception as e:
            print(f'获取筛选条件失败: {e}')
            return body['type_id'], []
        ft = []
        for i in data.get('data', {}).get('listItems', []):
            try:
                value_array = [{"n": value['tagName'], "v": value['tagId']} for value in i.get('items', []) if
                               value.get('tagName')]
                ft.append({"key": i.get('eName'), "name": i.get('typeName'), "value": value_array})
            except Exception as e:
                print(f'解析筛选条件异常: {e}, 数据: {i}')
        return body['type_id'], ft

    def fetch_page_data(self, page, id, b=False):
        body = {'version': '5.5.35', 'video_id': id, 'page': page, 'size': '30',
                'platform': '4', 'src': 'mgtv', 'allowedRC': '1', '_support': '10000000'}
        try:
            data = self.fetch(f'{self.vhost}/episode/list', params=body, headers=self.headers, timeout=10).json()
        except Exception as e:
            print(f'获取剧集列表失败 page={page}: {e}')
            return [] if not b else ({'data':{'total_page':1}}, [])
        ldata = [f'{i["t3"]}${i["url"]}' for i in data.get('data', {}).get('list', [])]
        if b:
            return data, ldata
        else:
            return ldata

    def officialChannelContent(self, channel_id, pg):
        if int(pg) > 1:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 80, 'total': 0}
        url = f'{self.mhost}/dynamic/v1/channel/index/0/1.0.0/10/1000000/space/0/1/{channel_id}'
        try:
            data = self.fetch(
                url,
                params={'osType': 'windows', 'playList': '', '_support': '10000000'},
                headers=self.headers,
                timeout=10
            ).json()
        except Exception as e:
            print(f'官方频道获取失败: {e}')
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 80, 'total': 0}
        video_list = []
        seen = set()
        for module in data.get('data') or []:
            for dsl in module.get('DSLList') or []:
                for item in (dsl.get('data') or {}).get('items') or []:
                    video_id = item.get('childId') or item.get('videoId')
                    if not video_id or str(video_id) == '0' or str(video_id) in seen:
                        continue
                    seen.add(str(video_id))
                    right_corner = item.get('rightCorner') or ''
                    if isinstance(right_corner, dict):
                        right_corner = right_corner.get('text') or ''
                    video_list.append({
                        'vod_id': str(video_id),
                        'vod_name': item.get('name') or item.get('title') or item.get('videoName') or '芒果视频',
                        'vod_pic': self.normalizeImage(
                            item.get('imageV') or item.get('imageH') or item.get('imageNew') or
                            item.get('thumbImg') or item.get('img') or ''
                        ),
                        'vod_year': right_corner,
                        'vod_remarks': item.get('updateInfo') or item.get('subName') or ''
                    })
        return {
            'list': video_list,
            'page': pg,
            'pagecount': 1,
            'limit': 80,
            'total': len(video_list)
        }

    def liveContent(self, pg):
        if int(pg) > 1:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 100, 'total': 0}
        params = {
            'version': 'PCweb_1.0',
            'platform': '4',
            'media_asset_id': 'TVStationAll',
            'buss_id': '2000001',
            '_support': '10000000',
            'callback': 'livecallback'
        }
        try:
            response = self.fetch(
                'https://mpplive.api.mgtv.com/v1/epg/turnplay/getLiveAssetCategoryList',
                params=params,
                headers=self.headers,
                timeout=10
            )
        except Exception as e:
            print(f'直播列表获取失败: {e}')
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 100, 'total': 0}
        text = response.text.strip()
        if text.startswith('livecallback('):
            text = text[len('livecallback('):text.rfind(')')]
        try:
            data = json.loads(text)
        except:
            data = {}
        video_list = []
        seen = set()
        for category in ((data.get('data') or {}).get('category') or []):
            for channel in category.get('channels') or []:
                camera_id = str(channel.get('id') or '')
                if not camera_id or camera_id in seen:
                    continue
                seen.add(camera_id)
                name = channel.get('name') or channel.get('curr_program') or '芒果直播'
                pic = self.normalizeImage(channel.get('channel_image') or '')
                video_list.append({
                    'vod_id': self.makeLiveId('', camera_id, name, pic),
                    'vod_name': name,
                    'vod_pic': pic,
                    'vod_remarks': channel.get('curr_program') or '正在直播'
                })
        try:
            event_data = self.fetch(
                'https://pwlc.bz.mgtv.com/list/getCommonList',
                params={
                    'version': '6.0.0', 'platform': '4', 'listType': '4',
                    'pageNum': '1', 'pageSize': '50', '_support': '10000000'
                },
                headers=self.headers,
                timeout=10
            ).json()
            for module in event_data.get('data') or []:
                for item in module.get('moduleData') or []:
                    if str(item.get('jumpKind')) != '14':
                        continue
                    activity_id = str(item.get('activityId') or '')
                    camera_id = str(item.get('childId') or '')
                    if not activity_id or not camera_id:
                        continue
                    name = item.get('name') or '芒果活动直播'
                    pic = self.normalizeImage(item.get('imgHUrl') or item.get('imgHVUrl') or '')
                    video_list.append({
                        'vod_id': self.makeLiveId(activity_id, camera_id, name, pic),
                        'vod_name': name,
                        'vod_pic': pic,
                        'vod_remarks': item.get('subName') or item.get('rightCorner') or '活动直播'
                    })
        except Exception as error:
            print(f'Live event fetch error: {error}')
        return {
            'list': video_list,
            'page': pg,
            'pagecount': 1,
            'limit': 100,
            'total': len(video_list)
        }

    def makeLiveId(self, activity_id, camera_id, name, pic):
        return 'mgtvlive@{}@{}@{}@{}'.format(
            activity_id, camera_id, quote(str(name), safe=''), quote(str(pic), safe='')
        )

    def parseLiveId(self, live_id):
        parts = str(live_id).split('@', 4)
        return {
            'activity_id': parts[1] if len(parts) > 1 else '',
            'camera_id': parts[2] if len(parts) > 2 else '',
            'name': unquote(parts[3]) if len(parts) > 3 else '芒果直播',
            'pic': unquote(parts[4]) if len(parts) > 4 else ''
        }

    def normalizeImage(self, url):
        url = str(url or '')
        if url.startswith('//'):
            return f'https:{url}'
        if url.startswith('http://'):
            return f'https://{url[7:]}'
        return url