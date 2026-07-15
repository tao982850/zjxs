# coding=utf-8
import re
import sys
import json
import time
import base64
import hashlib
import urllib.parse
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

# 假设这是从上级模块导入的基类
sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    def __init__(self):
        super().__init__()  # 确保父类初始化
        # 1. 配置常量化与私有化
        self._CONFIG = {
            'name': '瓜子',
            'host': 'https://api.w32z7vtd.com',
            'token': '1be86e8e18a9fa18b2b8d5432699dad0.ac008ed650fd087bfbecf2fda9d82e9835253ef24843e6b18fcd128b10763497bcf9d53e959f5377cde038c20ccf9d17f604c9b8bb6e61041def86729b2fc7408bd241e23c213ac57f0226ee656e2bb0a583ae0e4f3bf6c6ab6c490c9a6f0d8cdfd366aacf5d83193671a8f77cd1af1ff2e9145de92ec43ec87cf4bdc563f6e919fe32861b0e93b118ec37d8035fbb3c.59dd05c5d9a8ae726528783128218f15fe6f2c0c8145eddab112b374fcfe3d79',
            'app_id': '1',
            'phone_model': 'xiaomi-22021211rc',
            'version': '2406025',
            'package_name': 'com.uf076bf0c246.qe439f0d5e.m8aaf56b725a.ifeb647346f',
            'user_agent': 'okhttp/3.12.0',
            'timeout': 10,
            'cache_timeout': 300  # 5分钟
        }
        
        # 2. 动态构建请求头
        self.header = {
            'Cache-Control': 'no-cache',
            'Version': self._CONFIG['version'],
            'PackageName': self._CONFIG['package_name'],
            'Ver': '1.9.2',
            'Referer': self._CONFIG['host'],
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': self._CONFIG['user_agent']
        }
        
        # 3. 使用更安全的缓存结构 (例如：LRU Cache)，这里简化为字典
        self._cache = {}
        self._RSA_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIICdgIBADANBgkqhkiG9w0BAQEFAASCAmAwggJcAgEAAoGAe6hKrWLi1zQmjTT1
ozbE4QdFeJGNxubxld6GrFGximxfMsMB6BpJhpcTouAqywAFppiKetUBBbXwYsYU
1wNr648XVmPmCMCy4rY8vdliFnbMUj086DU6Z+/oXBdWU3/b1G0DN3E9wULRSwcK
ZT3wj/cCI1vsCm3gj2R5SqkA9Y0CAwEAAQKBgAJH+4CxV0/zBVcLiBCHvSANm0l7
HetybTh/j2p0Y1sTXro4ALwAaCTUeqdBjWiLSo9lNwDHFyq8zX90+gNxa7c5EqcW
V9FmlVXr8VhfBzcZo1nXeNdXFT7tQ2yah/odtdcx+vRMSGJd1t/5k5bDd9wAvYdI
DblMAg+wiKKZ5KcdAkEA1cCakEN4NexkF5tHPRrR6XOY/XHfkqXxEhMqmNbB9U34
saTJnLWIHC8IXys6Qmzz30TtzCjuOqKRRy+FMM4TdwJBAJQZFPjsGC+RqcG5UvVM
iMPhnwe/bXEehShK86yJK/g/UiKrO87h3aEu5gcJqBygTq3BBBoH2md3pr/W+hUM
WBsCQQChfhTIrdDinKi6lRxrdBnn0Ohjg2cwuqK5zzU9p/N+S9x7Ck8wUI53DKm8
jUJE8WAG7WLj/oCOWEh+ic6NIwTdAkEAj0X8nhx6AXsgCYRql1klbqtVmL8+95KZ
K7PnLWG/IfjQUy3pPGoSaZ7fdquG8bq8oyf5+dzjE/oTXcByS+6XRQJAP/5ciy1b
L3NhUhsaOVy55MHXnPjdcTX0FaLi+ybXZIfIQ2P4rb19mVq1feMbCXhz+L1rG8oa
t5lYKfpe8k83ZA==
-----END PRIVATE KEY-----"""

    # --- 基础接口方法 ---
    def getName(self):
        return self._CONFIG['name']

    def init(self, extend=''):
        pass

    def homeContent(self, filter):
        """首页配置：分类与筛选"""
        result = {}
        # 分类配置
        classes = [
            {"type_name": "电影", "type_id": "1"},
            {"type_name": "电视剧", "type_id": "2"},
            {"type_name": "动漫", "type_id": "4"},
            {"type_name": "综艺", "type_id": "3"},
            {"type_name": "短剧", "type_id": "64"}
        ]
        result['class'] = classes

        # 筛选配置 (使用字典推导式或常量更佳，此处保持动态)
        filters = {}
        areas = [("全部", "0"), ("大陆", "大陆"), ("香港", "香港"), ("台湾", "台湾"), 
                ("美国", "美国"), ("韩国", "韩国"), ("日本", "日本"), ("英国", "英国"), 
                ("法国", "法国"), ("泰国", "泰国"), ("印度", "印度"), ("其他", "其他")]
        
        years = [("全部", "0")] + [(str(year), str(year)) for year in range(2025, 2003, -1)]
        years.append(("更早", "2004"))

        sort_types = [("最新", "d_id"), ("最热", "d_hits"), ("推荐", "d_score")]

        for cate in classes:
            tid = cate['type_id']
            filters[tid] = [
                {
                    "key": "area",
                    "name": "地区",
                    "value": [{"n": n, "v": v} for n, v in areas]
                },
                {
                    "key": "year",
                    "name": "年份",
                    "value": [{"n": n, "v": v} for n, v in years]
                },
                {
                    "key": "sort",
                    "name": "排序",
                    "value": [{"n": n, "v": v} for n, v in sort_types]
                }
            ]
        result['filters'] = filters
        return result

    def homeVideoContent(self):
        """首页视频列表：暂时禁用或留空"""
        return {'list': []}

    # --- 核心业务逻辑 ---
    def categoryContent(self, tid, pg, filter, extend):
        """分类获取"""
        videos = []
        try:
            body = {
                "area": extend.get('area', '0'),
                "year": extend.get('year', '0'),
                "pageSize": "30",
                "sort": extend.get('sort', 'd_id'),
                "page": str(pg),
                "tid": tid
            }
            # 使用统一的数据获取方法
            data = self._get_api_data(body, '/App/IndexList/indexList', use_cache=True)
            if data and 'list' in data:
                for item in data['list']:
                    vod_continu = item.get('vod_continu', 0)
                    remarks = '电影' if vod_continu == 0 else f'更新至{vod_continu}集'
                    videos.append({
                        "vod_id": f"{item.get('vod_id', '')}/{vod_continu}",
                        "vod_name": item.get('vod_name', ''),
                        "vod_pic": item.get('vod_pic', ''),
                        "vod_remarks": remarks
                    })
        except Exception as e:
            self._log(f"分类获取失败: {e}")
        
        return {
            'list': videos,
            'page': int(pg),
            'pagecount': 9999,
            'limit': 30,
            'total': 999999
        }

    def detailContent(self, ids):
        """详情与播放源"""
        try:
            vod_id = ids[0].split('/')[0]
            # 并发或批量请求优化点：此处可根据API支持情况合并请求
            detail_data = self._fetch_detail(vod_id)
            play_data = self._fetch_play_list(vod_id)
            
            if not detail_data or 'vodInfo' not in detail_data:
                return {'list': []}

            vod_info = detail_data['vodInfo']
            video_detail = {
                "vod_id": vod_id,
                "vod_name": vod_info.get('vod_name', ''),
                "vod_pic": vod_info.get('vod_pic', ''),
                "vod_year": vod_info.get('vod_year', ''),
                "vod_area": vod_info.get('vod_area', ''),
                "vod_actor": vod_info.get('vod_actor', ''),
                "vod_director": vod_info.get('vod_director', ''),
                "vod_content": vod_info.get('vod_use_content', '').strip(),
                "vod_play_from": "拾光请你看瓜子"
            }

            play_urls = self._parse_play_data(play_data, vod_info)
            if play_urls:
                video_detail["vod_play_url"] = "#".join(play_urls)
            
            return {'list': [video_detail]}
        except Exception as e:
            self._log(f"详情获取失败: {e}")
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        """搜索"""
        videos = []
        try:
            body = {
                "keywords": key,
                "order_val": "1",
                "page": str(pg)
            }
            # 搜索通常不缓存
            data = self._get_api_data(body, '/App/Index/findMoreVod', use_cache=False)
            if data and 'list' in data:
                for item in data['list']:
                    vod_continu = item.get('vod_continu', 0)
                    remarks = '电影' if vod_continu == 0 else f'更新至{vod_continu}集'
                    videos.append({
                        "vod_id": f"{item.get('vod_id', '')}/{vod_continu}",
                        "vod_name": item.get('vod_name', ''),
                        "vod_pic": item.get('vod_pic', ''),
                        "vod_remarks": remarks
                    })
        except Exception as e:
            self._log(f"搜索失败: {e}")
        
        return {
            'list': videos,
            'page': int(pg),
            'pagecount': 9999,
            'limit': 30,
            'total': 999999
        }

    def playerContent(self, flag, id, vipFlags):
        """播放解析"""
        try:
            parts = id.split('||')
            if len(parts) < 2:
                return {"parse": 0, "playUrl": "", "url": ""}
                
            param_str = parts[0]
            resolutions = parts[1].split('@') if len(parts) > 1 else []

            # 解析参数
            params = dict(pair.split('=', 1) for pair in param_str.split('&') if '=' in pair)

            # 选择最高分辨率
            if resolutions:
                # 尝试按数值排序，兼容非数字情况
                resolutions.sort(key=lambda x: int(x) if x.isdigit() else 0, reverse=True)
                params['resolution'] = resolutions[0]

            # 获取真实播放地址
            data = self._get_api_data(params, '/App/Resource/VurlDetail/showOne', use_cache=False)
            if data and 'url' in data:
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": data['url'],
                    "header": json.dumps({"User-Agent": "Lavf/57.83.100"})
                }
        except Exception as e:
            self._log(f"播放解析失败: {e}")
        
        return {"parse": 0, "playUrl": "", "url": ""}

    # --- 工具方法 (加密/解密/网络) ---
    def _log(self, msg):
        """统一日志输出"""
        print(f"[{self._CONFIG['name']}]{msg}")

    def _aes_encrypt(self, text, key, iv):
        """AES加密"""
        try:
            key_bytes = key.encode('utf-8')
            iv_bytes = iv.encode('utf-8')
            cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
            encrypted = cipher.encrypt(pad(text.encode('utf-8'), AES.block_size))
            return encrypted.hex().upper()
        except Exception as e:
            self._log(f"AES加密异常: {e}")
            return ""

    def _aes_decrypt(self, text, key, iv):
        """AES解密"""
        try:
            key_bytes = key.encode('utf-8')
            iv_bytes = iv.encode('utf-8')
            cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
            encrypted_bytes = bytes.fromhex(text)
            decrypted = unpad(cipher.decrypt(encrypted_bytes), AES.block_size)
            return decrypted.decode('utf-8')
        except Exception as e:
            self._log(f"AES解密异常: {e}")
            return ""

    def _rsa_decrypt(self, encrypted_data, private_key):
        """RSA解密"""
        try:
            encrypted_bytes = base64.b64decode(encrypted_data)
            rsa_key = RSA.import_key(private_key)
            cipher = PKCS1_v1_5.new(rsa_key)
            decrypted = cipher.decrypt(encrypted_bytes, None)
            return decrypted.decode('utf-8') if decrypted else ""
        except Exception as e:
            self._log(f"RSA解密异常: {e}")
            return ""

    def _get_api_data(self, data, path, use_cache=True):
        """统一的数据请求与处理核心"""
        cache_key = f"req_{path}_{hash(str(data))}"
        
        # 1. 缓存检查
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached:
                c_time, c_data = cached
                if (time.time() - c_time) < self._CONFIG['cache_timeout']:
                    return c_data

        try:
            start_time = time.time()
            
            # 2. 构建请求体 (加密流程)
            request_key = self._aes_encrypt(json.dumps(data), 'mvXBSW7ekreItNsT', '2U3IrJL8szAKp0Fj')
            if not request_key:
                return None

            t = str(int(time.time()))
            keys_str = "Qmxi5ciWXbQzkr7o+SUNiUuQxQEf8/AVyUWY4T/BGhcXBIUz4nOyHBGf9A4KbM0iKF3yp9M7WAY0rrs5PzdTAOB45plcS2zZ0wUibcXuGJ29VVGRWKGwE9zu2vLwhfgjTaaDpXo4rby+7GxXTktzJmxvneOUdYeHi+PZsThlvPI="
            
            # 签名生成
            sign_str = f"token_id=,token={self._CONFIG['token']},phone_type=1,request_key={request_key},app_id=1,time={t},keys={keys_str}*&zvdvdvddbfikkkumtmdwqppp?|4Y!s!2br"
            signature = hashlib.md5(sign_str.encode()).hexdigest()

            body = {
                'token': self._CONFIG['token'],
                'token_id': '',
                'phone_type': '1',
                'time': t,
                'phone_model': self._CONFIG['phone_model'],
                'keys': keys_str,
                'request_key': request_key,
                'signature': signature,
                'app_id': self._CONFIG['app_id'],
                'ad_version': '1'
            }

            # 3. 发送请求
            url = f"{self._CONFIG['host']}{path}"
            response = self.post(url, headers=self.header, data=body, timeout=self._CONFIG['timeout'])
            
            if response.status_code != 200:
                self._log(f"HTTP错误: {response.status_code} - {path}")
                return None

            response_json = response.json()
            if 'data' not in response_json:
                self._log(f"响应格式错误: {path}")
                return None

            data_response = response_json['data']

            # 4. 响应解密
            # 解密 keys
            bodyki_json = self._rsa_decrypt(data_response['keys'], self._RSA_PRIVATE_KEY)
            if not bodyki_json:
                return None
            bodyki = json.loads(bodyki_json)

            # 解密 response_key
            decrypted_data = self._aes_decrypt(data_response['response_key'], bodyki['key'], bodyki['iv'])
            if not decrypted_data:
                return None

            result = json.loads(decrypted_data)
            end_time = time.time()
            self._log(f"API调用成功: {path} [{end_time - start_time:.2f}s]")

            # 5. 更新缓存
            if use_cache:
                self._cache[cache_key] = (time.time(), result)
            
            return result

        except Exception as e:
            self._log(f"API请求异常: {e} - {path}")
            return None

    # --- 辅助方法提取 ---
    def _fetch_detail(self, vod_id):
        """获取视频详情"""
        t = str(int(time.time()))
        body = {
            "token_id": "1649412",
            "vod_id": vod_id,
            "mobile_time": t,
            "token": self._CONFIG['token']
        }
        return self._get_api_data(body, '/App/IndexPlay/playInfo', use_cache=True)

    def _fetch_play_list(self, vod_id):
        """获取播放列表"""
        body = {
            "vurl_cloud_id": "2",
            "vod_d_id": vod_id
        }
        return self._get_api_data(body, '/App/Resource/Vurl/show', use_cache=True)

    def _parse_play_data(self, jdata, vod_info):
        """解析播放列表数据"""
        play_list = []
        if jdata and 'list' in jdata:
            for index, item in enumerate(jdata['list']):
                if 'play' not in item:
                    continue
                names = []
                params = []
                for key, value in item['play'].items():
                    if 'param' in value and value['param']:
                        names.append(key)
                        params.append(value['param'])
                if params:
                    play_name = vod_info.get('vod_name', '') if len(jdata['list']) == 1 else str(index + 1)
                    play_url = f"{params[-1]}||{'@'.join(names)}"
                    play_list.append(f"{play_name}${play_url}")
        return play_list

    # --- 未使用方法清理 ---
    # 移除了 isVideoFormat, manualVideoCheck, localProxy 等未使用或默认方法
    # 移除了冗余的 get_md5 方法 (直接使用 hashlib 即可)

if __name__ == '__main__':
    pass
