# 蜜果-http://6i.pw/
# !/usr/bin/python
import json
import sys
import uuid
import copy
sys.path.append('..')
from base.spider import Spider
from pyquery import PyQuery as pq
from concurrent.futures import ThreadPoolExecutor, as_completed


class Spider(Spider):

    def init(self, extend=""):
        self.dbody = {
            "page_params": {
                "channel_id": "",
                "filter_params": "sort=75",
                "page_type": "channel_operation",
                "page_id": "channel_list_second_page"
            }
        }
        self.body = self.dbody
        self.channel_contexts = {}
        pass

    def getName(self):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    host = 'https://v.qq.com'

    apihost = 'https://pbaccess.video.qq.com'

    # 这些频道已改用腾讯视频网页当前的 vector_layout 接口。
    new_channel_ids = {'100103', '100302', '110852', '100118'}

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5410.0 Safari/537.36',
        'origin': host,
        'referer': f'{host}/'
    }

    def homeContent(self, filter):
        cdata = {
            "电视剧": "100113",
            "电影": "100173",
            "综艺": "100109",
            "纪录片": "100105",
            "动漫": "100119",
            "少儿": "100150",
            "短剧": "110755",
            "体育": "100103",
            "宠物TV": "100302",
            "中视频": "110852",
            "音乐": "100118"
        }
        result = {}
        classes = []
        filters = {}
        for k in cdata:
            classes.append({
                'type_name': k,
                'type_id': cdata[k]
            })
        filter_classes = [item for item in classes if item['type_id'] not in self.new_channel_ids]
        with ThreadPoolExecutor(max_workers=len(filter_classes)) as executor:
            futures = [executor.submit(self.get_filter_data, item['type_id']) for item in filter_classes]
            for future in futures:
                cid, data = future.result()
                if not data.get('data', {}).get('module_list_datas'):
                    continue
                filter_dict = {}
                try:
                    items = data['data']['module_list_datas'][-1]['module_datas'][-1]['item_data_lists']['item_datas']
                    for item in items:
                        if not item.get('item_params', {}).get('index_item_key'):
                            continue
                        params = item['item_params']
                        filter_key = params['index_item_key']
                        if filter_key not in filter_dict:
                            filter_dict[filter_key] = {
                                'key': filter_key,
                                'name': params['index_name'],
                                'value': []
                            }
                        filter_dict[filter_key]['value'].append({
                            'n': params['option_name'],
                            'v': params['option_value']
                        })
                except (IndexError, KeyError):
                    continue
                filters[cid] = list(filter_dict.values())
        result['class'] = classes
        result['filters'] = filters
        return result

    def homeVideoContent(self):
        vlist = []
        data = self.gethtml(self.host)
        its = data('script')
        s = None
        for it in its.items():
            if 'window.__INITIAL_STATE__' in it.text():
                s = it.text()
                break
        if s:
            index = s.find('=')
            if index != -1:
                sd = json.loads(s[index + 1:])
                if sd.get('storeModulesData', {}).get('channelsModulesMap', {}).get('choice', {}).get('cardListData'):
                    for its in sd['storeModulesData']['channelsModulesMap']['choice']['cardListData']:
                        if its and its.get('children_list', {}).get('list', {}).get('cards'):
                            for it in its['children_list']['list']['cards']:
                                if it and it.get('params'):
                                    p = it['params']
                                    tag = json.loads(p.get('uni_imgtag', '{}') or p.get('imgtag', '{}') or '{}')
                                    id = it.get('id') or p.get('cid')
                                    name = p.get('mz_title') or p.get('title')
                                    if name and 'http' not in id:
                                        vlist.append({
                                            'vod_id': id,
                                            'vod_name': name,
                                            'vod_pic': p.get('image_url'),
                                            'vod_year': tag.get('tag_2', {}).get('text'),
                                            'vod_remarks': tag.get('tag_4', {}).get('text')
                                        })
        return {'list': vlist}

    def categoryContent(self, tid, pg, filter, extend):
        if tid in self.new_channel_ids:
            return self.newChannelContent(tid, pg)

        result = {}
        params = {
            "sort": extend.get('sort', '75'),
            "attr": extend.get('attr', '-1'),
            "itype": extend.get('itype', '-1'),
            "ipay": extend.get('ipay', '-1'),
            "iarea": extend.get('iarea', '-1'),
            "iyear": extend.get('iyear', '-1'),
            "theater": extend.get('theater', '-1'),
            "award": extend.get('award', '-1'),
            "recommend": extend.get('recommend', '-1')
        }
        if pg == '1':
            # page_params 是嵌套字典，必须深拷贝，避免不同分类共用并覆盖参数。
            self.body = copy.deepcopy(self.dbody)
        self.body['page_params']['channel_id'] = tid
        self.body['page_params']['filter_params'] = self.josn_to_params(params)
        data = self.post(
            f'{self.apihost}/trpc.universal_backend_service.page_server_rpc.PageServer/GetPageData?video_appid=1000005&vplatform=2&vversion_name=8.9.10&new_mark_label_enabled=1',
            json=self.body, headers=self.headers).json()
        ndata = data['data']
        if ndata['has_next_page']:
            result['pagecount'] = 9999
            self.body['page_context'] = ndata['next_page_context']
        else:
            result['pagecount'] = int(pg)
        vlist = []
        for its in ndata['module_list_datas'][-1]['module_datas'][-1]['item_data_lists']['item_datas']:
            id = its.get('item_params', {}).get('cid')
            if id:
                p = its['item_params']
                tag = json.loads(p.get('uni_imgtag', '{}') or p.get('imgtag', '{}') or '{}')
                name = p.get('mz_title') or p.get('title')
                pic = p.get('new_pic_hz') or p.get('new_pic_vt')
                vlist.append({
                    'vod_id': id,
                    'vod_name': name,
                    'vod_pic': pic,
                    'vod_year': tag.get('tag_2', {}).get('text'),
                    'vod_remarks': tag.get('tag_4', {}).get('text')
                })
        result['list'] = vlist
        result['page'] = pg
        result['limit'] = 90
        result['total'] = 999999
        return result

    def newChannelContent(self, tid, pg):
        """读取体育、宠物TV、中视频、音乐等新版频道页面。"""
        page = max(int(pg or 1), 1)
        if page == 1:
            page_context = None
            self.channel_contexts.pop(tid, None)
        else:
            page_context = self.channel_contexts.get(tid)
            if not page_context:
                return {'list': [], 'page': page, 'pagecount': page, 'limit': 40, 'total': 0}

        body = {
            'page_params': {
                'page_type': 'channel',
                'page_id': tid,
                'scene': 'channel',
                'new_mark_label_enabled': '1',
                'vl_to_mvl': '',
                'ad_exp_ids': '',
                'ams_cookies': '',
                'ad_trans_data': '{}',
                'skip_privacy_types': '0',
                'support_click_scan': '1'
            },
            'page_bypass_params': {
                'params': {
                    'platform_id': '2',
                    'caller_id': '3000010',
                    'data_mode': 'default',
                    'user_mode': 'default',
                    'specified_strategy': '',
                    'page_type': 'channel',
                    'page_id': tid,
                    'scene': 'channel',
                    'new_mark_label_enabled': '1'
                },
                'scene': 'channel',
                'app_version': '',
                'abtest_bypass_id': ''
            },
            'page_context': page_context
        }
        try:
            data = self.post(
                f'{self.apihost}/trpc.vector_layout.page_view.PageService/getPage?video_appid=3000010&vversion_platform=2',
                json=body, headers=self.headers
            ).json().get('data', {})
        except Exception as e:
            print(f'Error loading new channel {tid}: {e}')
            return {'list': [], 'page': page, 'pagecount': page, 'limit': 40, 'total': 0}

        next_context = data.get('page_context')
        if data.get('has_next_page') and next_context:
            self.channel_contexts[tid] = next_context
        else:
            self.channel_contexts.pop(tid, None)

        vlist = []
        seen = set()
        for module in data.get('CardList', []):
            cards = module.get('children_list', {}).get('list', {}).get('cards', [])
            for card in cards:
                params = card.get('params') or {}
                cid = params.get('cid')
                if not cid or cid in seen:
                    continue
                name = params.get('mz_title') or params.get('title') or params.get('material_video_title')
                if not name:
                    continue
                pic = (params.get('image_url_vertical') or params.get('pic_496x280') or
                       params.get('pic496x280') or params.get('pic_540x304') or
                       params.get('image_url') or params.get('pic_750x422'))
                remarks = (params.get('episode_updated') or params.get('material_video_subtitle') or
                           params.get('update_title') or params.get('rec_normal_reason') or '')
                seen.add(cid)
                vlist.append({
                    'vod_id': cid,
                    'vod_name': name,
                    'vod_pic': pic or '',
                    'vod_remarks': remarks
                })

        has_next = bool(data.get('has_next_page') and next_context)
        return {
            'list': vlist,
            'page': page,
            'pagecount': 9999 if has_next else page,
            'limit': max(len(vlist), 1),
            'total': 999999 if has_next else len(vlist)
        }

    def detailContent(self, ids):
        vbody = {
            "page_params": {
                "req_from": "web",
                "cid": ids[0],
                "vid": "",
                "lid": "",
                "page_type": "detail_operation",
                "page_id": "detail_page_introduction"
            },
            "has_cache": 1
        }

        body = {
            "page_params": {
                "req_from": "web_vsite",
                "page_id": "vsite_episode_list",
                "page_type": "detail_operation",
                "id_type": "1",
                "page_size": "",
                "cid": ids[0],
                "vid": "",
                "lid": "",
                "page_num": "",
                "page_context": "",
                "detail_page_type": "1"
            },
            "has_cache": 1
        }

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_detail = executor.submit(self.get_vdata, vbody)
            future_episodes = executor.submit(self.get_vdata, body)
            vdata = future_detail.result()
            data = future_episodes.result()

        pdata = self.process_tabs(data, body, ids)
        if not pdata:
            return self.handle_exception(None, "No pdata available")

        try:
            star_list = vdata['data']['module_list_datas'][0]['module_datas'][0]['item_data_lists']['item_datas'][
                0].get('sub_items', {}).get('star_list', {}).get('item_datas', [])
            actors = [star['item_params']['name'] for star in star_list]
            names = ['腾讯视频', '预告片']
            plist, ylist = self.process_pdata(pdata, ids)
            if not plist:
                del names[0]
            if not ylist:
                del names[1]
            vod = self.build_vod(vdata, actors, plist, ylist, names)
            return {'list': [vod]}
        except Exception as e:
            return self.handle_exception(e, "Error processing detail")

    def searchContent(self, key, quick, pg="1"):
        body = {"version": "24072901", "clientType": 1, "filterValue": "", "uuid": str(uuid.uuid4()), "retry": 0,
                "query": key, "pagenum": int(pg) - 1, "pagesize": 30, "queryFrom": 0, "searchDatakey": "",
                "transInfo": "", "isneedQc": True, "preQid": "", "adClientInfo": "",
                "extraInfo": {"isNewMarkLabel": "1", "multi_terminal_pc": "1"}}
        data = self.post(f'{self.apihost}/trpc.videosearch.mobile_search.MultiTerminalSearch/MbSearch?vplatform=2',
                         json=body, headers=self.headers).json()
        vlist = []
        for k in data['data']['areaBoxList'][-1]['itemList']:
            if k.get('doc', {}).get('id'):
                img_tag = k.get('videoInfo', {}).get('imgTag')
                if img_tag is not None and isinstance(img_tag, str):
                    try:
                        tag = json.loads(img_tag)
                    except json.JSONDecodeError as e:
                        tag = {}
                else:
                    tag = {}
                pic = k.get('videoInfo', {}).get('imgUrl')
                vlist.append({
                    'vod_id': k['doc']['id'],
                    'vod_name': k['videoInfo']['title'],
                    'vod_pic': pic,
                    'vod_year': tag.get('tag_2', {}).get('text', ''),
                    'vod_remarks': tag.get('tag_4', {}).get('text', '')
                })
        return {'list': vlist, 'page': pg}

    def playerContent(self, flag, id, vipFlags):
        ids = id.split('@')
        url = f"{self.host}/x/cover/{ids[0]}/{ids[1]}.html"
        return {
            'jx': 0,
            'parse': 1,
            'playUrl': 'https://jx.xmflv.com/?url=',
            'url': url,
            'header': {
                'User-Agent': self.headers['User-Agent'],
                'Referer': f'{self.host}/'
            }
        }
        
    def localProxy(self, param):
        pass

    def gethtml(self, url):
        rsp = self.fetch(url, headers=self.headers)
        rsp = self.cleanText(rsp.text)
        return pq(rsp)

    def get_filter_data(self, cid):
        # homeContent 会并发获取多个分类；浅拷贝会让所有线程共享 page_params。
        hbody = copy.deepcopy(self.dbody)
        hbody['page_params']['channel_id'] = cid
        data = self.post(
            f'{self.apihost}/trpc.universal_backend_service.page_server_rpc.PageServer/GetPageData?video_appid=1000005&vplatform=2&vversion_name=8.9.10&new_mark_label_enabled=1',
            json=hbody, headers=self.headers).json()
        return cid, data

    def get_vdata(self, body):
        try:
            vdata = self.post(
                f'{self.apihost}/trpc.universal_backend_service.page_server_rpc.PageServer/GetPageData?video_appid=3000010&vplatform=2&vversion_name=8.2.96',
                json=body, headers=self.headers
            ).json()
            # print(body)
            return vdata
        except Exception as e:
            print(f"Error in get_vdata: {str(e)}")
            return {'data': {'module_list_datas': []}}

    def process_pdata(self, pdata, ids):
        plist = []
        ylist = []
        for k in pdata:
            if k.get('item_id'):
                pid = f"{k['item_params']['union_title']}${ids[0]}@{k['item_id']}"
                if '预告' in k['item_params']['union_title']:
                    ylist.append(pid)
                else:
                    plist.append(pid)
        return plist, ylist

    def build_vod(self, vdata, actors, plist, ylist, names):
        d = vdata['data']['module_list_datas'][0]['module_datas'][0]['item_data_lists']['item_datas'][0]['item_params']
        urls = []
        if plist:
            urls.append('#'.join(plist))
        if ylist:
            urls.append('#'.join(ylist))
        vod = {
            'type_name': d.get('sub_genre', ''),
            'vod_name': d.get('title', ''),
            'vod_year': d.get('year', ''),
            'vod_area': d.get('area_name', ''),
            'vod_remarks': d.get('holly_online_time', '') or d.get('hotval', ''),
            'vod_actor': ','.join(actors),
            'vod_content': d.get('cover_description', ''),
            'vod_play_from': '$$$'.join(names),
            'vod_play_url': '$$$'.join(urls)
        }
        return vod

    def handle_exception(self, e, message):
        print(f"{message}: {str(e)}")
        return {'list': [{'vod_play_from': '哎呀翻车啦', 'vod_play_url': '翻车啦#555'}]}

    def process_tabs(self, data, body, ids):
        try:
            pdata = data['data']['module_list_datas'][-1]['module_datas'][-1]['item_data_lists']['item_datas']
            tabs = data['data']['module_list_datas'][-1]['module_datas'][-1]['module_params'].get('tabs')
            if tabs and len(json.loads(tabs)):
                tabs = json.loads(tabs)
                remaining_tabs = tabs[1:]
                task_queue = []
                for tab in remaining_tabs:
                    nbody = copy.deepcopy(body)
                    nbody['page_params']['page_context'] = tab['page_context']
                    task_queue.append(nbody)
                with ThreadPoolExecutor(max_workers=10) as executor:
                    future_map = {executor.submit(self.get_vdata, task): idx for idx, task in enumerate(task_queue)}
                    results = [None] * len(task_queue)
                    for future in as_completed(future_map.keys()):
                        idx = future_map[future]
                        results[idx] = future.result()
                    for result in results:
                        if result:
                            page_data = result['data']['module_list_datas'][-1]['module_datas'][-1]['item_data_lists'][
                                'item_datas']
                            pdata.extend(page_data)
            return pdata
        except Exception as e:
            print(f"Error processing episodes: {str(e)}")
            return []

    def josn_to_params(self, params, skip_empty=False):
        query = []
        for k, v in params.items():
            if skip_empty and not v:
                continue
            query.append(f"{k}={v}")
        return "&".join(query)
