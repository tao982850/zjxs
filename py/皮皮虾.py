# -*- coding: utf-8 -*-
# 本资源来源于互联网公开渠道，仅可用于个人学习及爬虫技术交流。
# 严禁将其用于任何商业用途，下载后请于 24 小时内删除，搜索结果均来自源站，本人不承担任何责任。

import re, sys, uuid
from base.spider import Spider
sys.path.append('..')


class Spider(Spider):
    host, config, local_uuid, parsing_config = '', '', '', []
    # 头部添加token认证
    headers = {
        'User-Agent': "Dart/2.19 (dart:io)",
        'Accept-Encoding': "gzip",
        'appto-local-uuid': local_uuid,
        'token': "eyJhbGciOiJIUzI1NiJ9.eyJkYXRhIjp7InVzZXJfY2hlY2siOiI4ZTEyNDE1Y2UyOGQzMGM4MWE3MDBiNWYxMDgzZTU2OCIsInVzZXJfaWQiOjM0NTYsInVzZXJfbmFtZSI6IjEwMTAxMiJ9LCJleHAiOjE4MDQ3MzkyODAuNjA4MTA4MywiaWF0IjoxNzczMjAzMjgxLCJpc3MiOiJBcHBUbyIsImp0aSI6ImZmZDMyYjk4N2VkMTg1ZjNiNGQ5Zjc5NzU2YWRjNGQ5IiwibmJmIjoxNzczMjAzMjgxLCJzdWIiOiJBcHBUbyJ9.tDhURwWVzsPy0-yXvo_d3bgsmoq9Ri5n0Y4fQsvxKy0"
    }

    def init(self, extend=''):
        try:
            host = extend.strip()
            if not host.startswith('http'):
                return {}
            if not re.match(r'^https?://[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)*(:\d+)?/?$', host):
                host_ = self.fetch(host).json()
                self.host = host_['domain']
            else:
                self.host = host.rstrip('/')
            self.local_uuid = str(uuid.uuid4())
            # 动态更新headers中的uuid（避免初始化时uuid为空）
            self.headers['appto-local-uuid'] = self.local_uuid
            response = self.fetch(f'{self.host}/apptov5/v1/config/get?p=android&__platform=android', headers=self.headers).json()
            config = response.get('data') or {}
            self.config = config
            parsing_conf = (config.get('get_parsing') or {}).get('lists') or []
            parsing_config = {}
            for i in parsing_conf:
                if len(i.get('config', [])) != 0:
                    label = []
                    for j in i['config']:
                        if j.get('type') == 'json':
                            label.append(j.get('label'))
                    if label:
                        parsing_config.update({i.get('key'): label})
            self.parsing_config = parsing_config
            return None
        except Exception as e:
            print(f'初始化异常：{e}')
            return {}

    @staticmethod
    def _fix_pic(pic):
        # mac:// 协议头替换，且对 None 做保护
        if not pic:
            return ''
        if pic.startswith('mac://'):
            pic = pic.replace('mac://', 'http://', 1)
        return pic

    def detailContent(self, ids):
        response = self.fetch(f"{self.host}/apptov5/v1/vod/getVod?id={ids[0]}", headers=self.headers).json()
        data3 = response.get('data') or {}
        videos = []
        vod_play_url = ''
        vod_play_from = ''
        for i in data3.get('vod_play_list') or []:
            play_url = ''
            player_from = (i.get('player_info') or {}).get('from', '')
            player_show = (i.get('player_info') or {}).get('show', player_from)
            for j in i.get('urls') or []:
                play_url += f"{j.get('name', '')}${player_from}@{j.get('url', '')}#"
            if not play_url:
                continue
            vod_play_from += player_show + '$$$'
            vod_play_url += play_url.rstrip('#') + '$$$'
        vod_play_url = vod_play_url.rstrip('$$$')
        vod_play_from = vod_play_from.rstrip('$$$')
        videos.append({
            'vod_id': data3.get('vod_id'),
            'vod_name': data3.get('vod_name'),
            'vod_content': data3.get('vod_content'),
            'vod_remarks': data3.get('vod_remarks'),
            'vod_director': data3.get('vod_director'),
            'vod_actor': data3.get('vod_actor'),
            'vod_year': data3.get('vod_year'),
            'vod_area': data3.get('vod_area'),
            'vod_play_from': vod_play_from,
            'vod_play_url': vod_play_url
        })
        return {'list': videos}

    def searchContent(self, key, quick, pg='1'):
        url = f"{self.host}/apptov5/v1/search/lists?wd={key}&page={pg}&type=&__platform=android"
        response = self.fetch(url, headers=self.headers).json()
        data = (response.get('data') or {}).get('data') or []
        total = (response.get('data') or {}).get('total') or 0
        for i in data:
            i['vod_pic'] = self._fix_pic(i.get('vod_pic'))
        return {'list': data, 'page': pg, 'total': total}

    def playerContent(self, flag, id, vipflags):
        default_ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1'
        parsing_config = self.parsing_config
        parts = id.split('@')
        if len(parts) != 2:
            return {'parse': 0, 'url': id, 'header': {'User-Agent': default_ua}}
        playfrom, rawurl = parts
        label_list = parsing_config.get(playfrom)
        if not label_list:
            return {'parse': 0, 'url': rawurl, 'header': {'User-Agent': default_ua}}
        result = {'parse': 1, 'url': rawurl, 'header': {'User-Agent': default_ua}}
        for label in label_list:
            payload = {
                'play_url': rawurl,
                'label': label,
                'key': playfrom
            }
            try:
                response = self.post(
                    f"{self.host}/apptov5/v1/parsing/proxy?__platform=android",
                    data=payload,
                    headers=self.headers
                ).json()
            except Exception as e:
                print(f"请求异常: {e}")
                continue
            if not isinstance(response, dict):
                continue
            if response.get('code') == 422:
                continue
            data = response.get('data')
            # 兼容 data 直接是字符串 url、或 data 为 dict 的情况
            if isinstance(data, str) and data.startswith('http'):
                result = {'parse': 0, 'url': data, 'header': {'User-Agent': default_ua}}
                break
            if not isinstance(data, dict):
                continue
            url = data.get('url')
            if not url:
                continue
            ua = data.get('UA') or data.get('UserAgent') or default_ua
            result = {
                'parse': 0,
                'url': url,
                'header': {'User-Agent': ua}
            }
            break
        return result

    def homeContent(self, filter):
        config = self.config
        if not config:
            return {}
        home_cate = config.get('get_home_cate') or []
        classes = []
        for i in home_cate:
            extend = i.get('extend', [])
            # 原来只接受 dict 类型的 extend，若为 list 会导致分类为空，这里放宽判断
            if isinstance(extend, dict) or isinstance(extend, list):
                classes.append({'type_id': i.get('cate'), 'type_name': i.get('title')})
        # 兜底：一条都没匹配到时直接使用全部分类，避免首页空白
        if not classes and home_cate:
            classes = [{'type_id': i.get('cate'), 'type_name': i.get('title')} for i in home_cate]
        return {'class': classes}

    def homeVideoContent(self):
        response = self.fetch(f'{self.host}/apptov5/v1/home/data?id=1&mold=1&__platform=android', headers=self.headers).json()
        data = response.get('data') or {}
        vod_list = []
        for i in data.get('sections') or []:
            for j in i.get('items') or []:
                vod_list.append({
                    "vod_id": j.get('vod_id'),
                    "vod_name": j.get('vod_name'),
                    "vod_pic": self._fix_pic(j.get('vod_pic')),
                    "vod_remarks": j.get('vod_remarks')
                })
        return {'list': vod_list}

    def categoryContent(self, tid, pg, filter, extend):
        extend = extend or {}
        response = self.fetch(
            f"{self.host}/apptov5/v1/vod/lists?area={extend.get('area','')}&lang={extend.get('lang','')}"
            f"&year={extend.get('year','')}&order={extend.get('sort','time')}&type_id={tid}"
            f"&type_name=&page={pg}&pageSize=21&__platform=android",
            headers=self.headers
        ).json()
        data = response.get('data') or {}
        data2 = data.get('data') or []
        for i in data2:
            i['vod_pic'] = self._fix_pic(i.get('vod_pic'))
        return {'list': data2, 'page': pg, 'total': data.get('total') or 0}

    def getName(self):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        pass
