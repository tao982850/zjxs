import re, sys, json, base64
from Crypto.Cipher import AES
from urllib.parse import urljoin, quote
from Crypto.Util.Padding import unpad
from base.spider import Spider

sys.path.append('..')


class Spider(Spider):
    headers = {'User-Agent': 'okhttp/4.12.0'}
    parse_headers = {'User-Agent': 'okhttp-okgo/jeasonlzy'}

    FIXED_CONFIG = {
        'host': 'http://cms.lyyytv.cn',
        'cmskey': 'wP5bvxoc3yv7FoBQENFZuAF0EUYr4LTy',
        'RawPlayUrl': 0,
        'parse_api': 'https://mk1080p.top/zzbh.php?url='
    }

    def init(self, extend=''):
        self.host = self.FIXED_CONFIG['host']
        self.cmskey = self.FIXED_CONFIG.get('cmskey', '')
        self.parse_api = self.FIXED_CONFIG.get('parse_api', '')
        self.raw_play_url = self.FIXED_CONFIG.get('RawPlayUrl', 0)

    # ---------- 解密函数保持不变 ----------
    def ldmax_decrypt(self, encrypted_base64, depth=0):
        if depth > 5:
            return None
        cleaned = re.sub(r'\s+', '', encrypted_base64)
        try:
            decoded = base64.b64decode(cleaned, validate=True).decode('utf-8', errors='ignore')
        except Exception:
            return encrypted_base64
        url = re.sub(r'\s+', '', decoded)
        if 'ldmax.cooom' not in url:
            return url
        path = re.sub(r'https?://ldmax\.cooom/', '', url)
        if len(path) < 16:
            return None
        key = path[:16][::-1].encode('utf-8')
        ciphertext_b64 = re.sub(r'\s+', '', path[16:])
        try:
            ciphertext = base64.b64decode(ciphertext_b64, validate=True)
        except Exception:
            return None
        try:
            cipher = AES.new(key, AES.MODE_CBC, key)
            decrypted = cipher.decrypt(ciphertext)
        except Exception:
            return None
        if decrypted:
            pad = decrypted[-1]
            if 0 < pad <= 16:
                decrypted = decrypted[:-pad]
        result = decrypted.decode('utf-8', errors='ignore').strip()
        if 'ldmax.cooom' in result:
            return self.ldmax_decrypt(base64.b64encode(result.encode('utf-8')).decode('utf-8'), depth + 1)
        return result

    def ldmax_parse(self, video_url):
        decrypted = self.ldmax_decrypt(video_url)
        if not decrypted or not re.match(r'^https?://', decrypted):
            return None
        try:
            parse_url = self.parse_api + quote(decrypted, safe='')
            resp = self.fetch(parse_url, headers=self.parse_headers, timeout=30).json()
        except Exception:
            return None
        if not resp or resp.get('code') != 200 or not resp.get('url'):
            return None
        final_url = self.ldmax_decrypt(resp['url'])
        if final_url and re.match(r'^https?://', final_url):
            return {'url': final_url, 'type': resp.get('type', 'video')}
        return None

    def lvdou(self, text):
        key = self.cmskey[:16].encode("utf-8")
        iv = self.cmskey[-16:].encode("utf-8")
        url_prefix = "lvdou+"
        if text.startswith(url_prefix):
            ciphertext_b64 = text[len(url_prefix):]
            try:
                cipher = AES.new(key, AES.MODE_CBC, iv)
                ct_bytes = base64.b64decode(ciphertext_b64)
                pt_bytes = cipher.decrypt(ct_bytes)
                return unpad(pt_bytes, AES.block_size).decode('utf-8')
            except Exception:
                return text
        else:
            return text

    # ---------- 修正后的 detailContent ----------
    def detailContent(self, ids):
        try:
            data = self.fetch(f"{self.host}/api.php/app/video_detail?id={ids[0]}", headers=self.headers).json()
        except Exception:
            return {'list': []}

        # 安全获取 data 字段
        vod_data = data.get('data', {})
        if not vod_data:
            return {'list': []}

        show, play_urls = [], []
        # 线路列表可能存在多个字段名
        players = vod_data.get('vod_url_with_player') or vod_data.get('vod_play_list') or []
        if not players:
            # 如果没有线路，直接返回基本信息
            return {'list': [vod_data]}

        for player in players:
            # 兼容不同的字段名
            urls_str = player.get('url') or player.get('vod_url') or ''
            name = player.get('name') or player.get('show') or '默认线路'
            if not urls_str:
                continue
            # 解密每个 URL
            decrypted_urls = []
            for part in urls_str.split('#'):
                if not part:
                    continue
                if '$' in part:
                    episode, url = part.split('$', 1)
                    # 尝试解密
                    decrypted = self.lvdou(url)
                    decrypted_urls.append(f"{episode}${decrypted}")
                else:
                    decrypted = self.lvdou(part)
                    decrypted_urls.append(decrypted)
            if decrypted_urls:
                show.append(name.strip())
                play_urls.append('#'.join(decrypted_urls))

        # 删除原始播放列表字段，替换为组装后的
        vod_data.pop('vod_url_with_player', None)
        vod_data.pop('vod_play_list', None)
        vod_data['vod_play_from'] = '$$$'.join(show)
        vod_data['vod_play_url'] = '$$$'.join(play_urls)

        return {'list': [vod_data]}

    # ---------- 修正后的 playerContent ----------
    def playerContent(self, flag, video_id, vipFlags):
        # 不再粗暴删除 %XX，改为正确解码
        try:
            video_id = quote(video_id, safe=':/?&=#')  # 重新编码，避免损坏参数
        except:
            pass

        # 检查是否是纯直链
        if self.check_paly_url(video_id):
            return {'jx': 0, 'parse': 0, 'playUrl': '', 'url': video_id, 'header': self.headers}

        # 尝试内置解析（包括 ldmax 加密或本站伪直链）
        parsed = self.ldmax_parse(video_id)
        if parsed:
            return {'jx': 0, 'parse': 0, 'playUrl': '', 'url': parsed['url'], 'header': self.headers}

        # 最后尝试外置解析
        return {'jx': 1, 'playUrl': '', 'parse': 0, 'url': video_id, 'header': self.headers}

    # ---------- 其他接口（基本不变） ----------
    def homeVideoContent(self):
        data = self.fetch(f"{self.host}/api.php/app/index_video?token=", headers=self.headers).json()
        videos = []
        for item in data['list']:
            videos.extend(item['vlist'])
        return {'list': videos}

    def homeContent(self, filter):
        data = self.fetch(f"{self.host}/api.php/app/nav?token=", headers=self.headers).json()
        keys = ["class", "area", "lang", "year", "letter", "by", "sort"]
        filters = {}
        classes = []

        for item in data['list']:
            has_non_empty_field = False
            jsontype_extend = item["type_extend"]
            classes.append({"type_name": item["type_name"], "type_id": item["type_id"]})

            for key in keys:
                if key in jsontype_extend and jsontype_extend[key].strip() != "":
                    has_non_empty_field = True
                    break

            if has_non_empty_field:
                filters[str(item["type_id"])] = []

            for dkey in jsontype_extend:
                if dkey in keys and jsontype_extend[dkey].strip() != "":
                    values = jsontype_extend[dkey].split(",")
                    value_array = []
                    for value in values:
                        if value.strip() != "":
                            value_array.append({"n": value.strip(), "v": value.strip()})
                    filters[str(item["type_id"])].append({"key": dkey, "name": dkey, "value": value_array})

        return {"class": classes, "filters": filters}

    def categoryContent(self, tid, pg, filter, extend):
        query_params = [
            f"tid={tid}",
            f"pg={pg}",
            f"limit=18"
        ]
        if extend.get('class'):
            query_params.append(f"class={extend.get('class')}")
        if extend.get('area'):
            query_params.append(f"area={extend.get('area')}")
        if extend.get('lang'):
            query_params.append(f"lang={extend.get('lang')}")
        if extend.get('year'):
            query_params.append(f"year={extend.get('year')}")

        url = f"{self.host}/api.php/app/video?" + "&".join(query_params)
        data = self.fetch(url, headers=self.headers).json()
        return data

    def searchContent(self, key, quick, pg="1"):
        data = self.fetch(f"{self.host}/api.php/app/search?text={key}&pg={pg}", headers=self.headers).json()
        videos = data['list']
        for item in data['list']:
            item.pop('type', None)
        return {'list': videos, 'page': pg}

    def raw_url(self, original_url):
        try:
            response = self.fetch(original_url, allow_redirects=False, stream=True, timeout=20)
            if 300 <= response.status_code < 400:
                redirect_location = response.headers.get('Location')
                if redirect_location:
                    return urljoin(original_url, redirect_location)
            return original_url
        except Exception:
            return original_url

    def check_paly_url(self, content):
        pattern = r"https?://.*(?:\.(?:mp4|m3u8|flv|avi|mkv|ts|mov|wmv|webm)|lyyytv\.cn/)"
        return bool(re.search(pattern, content, re.IGNORECASE))

    # ---------- 必须实现的空方法 ----------
    def getName(self): return "lyyytv"
    def localProxy(self, param): pass
    def isVideoFormat(self, url): return self.check_paly_url(url)
    def manualVideoCheck(self): return True
    def destroy(self): pass