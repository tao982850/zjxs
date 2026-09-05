#coding=utf-8
#!/usr/bin/python
import sys
sys.path.append('..') 
from base.spider import Spider
import json
import re
import time
import hashlib
import base64
from urllib.parse import quote

host_url = 'https://zhuiying1.cc'

def cleanHtml(html):
	"""清理HTML中的script/style标签，避免简介提取到JS代码"""
	html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
	html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
	html = re.sub(r'<iframe[^>]*>.*?</iframe>', '', html, flags=re.DOTALL | re.IGNORECASE)
	return html

def extractDesc(html):
	"""多方式提取简介，过滤JS代码"""
	html = cleanHtml(html)
	candidates = []

	classes = ['detail-desc', 'desc', 'vod-content', 'stui-content__desc', 
			   'plot', 'summary', 'intro', 'synopsis', 'sketch', 'brief']
	for cls in classes:
		m = re.search(r'<div[^>]*class="[^"]*' + cls + r'[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
		if m:
			text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
			if text and len(text) > 15 and not _isJsCode(text):
				candidates.append(text)

	for kw in ['简介', '剧情', '介绍', ' Synopsis', ' Plot']:
		m = re.search(r'<p[^>]*>\s*' + kw + r'[:：]?\s*</p>\s*<p[^>]*>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
		if m:
			text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
			if text and len(text) > 15 and not _isJsCode(text):
				candidates.append(text)

	m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', html, re.IGNORECASE)
	if m:
		text = m.group(1).strip()
		if text and len(text) > 15 and not _isJsCode(text):
			candidates.append(text)

	if candidates:
		return max(candidates, key=len)
	return ""

def _isJsCode(text):
	js_patterns = ['this.', 'function(', 'var ', 'let ', 'const ', '.length', 
				   'setSelectionRange', 'getElementById', 'addEventListener',
				   'onclick', 'onload', 'document.', 'window.']
	return any(p in text for p in js_patterns)

class Spider(Spider):
	def getName(self):
		return "追影"
	def init(self,extend=""):
		print("============{0}============".format(extend))
		pass
	def isVideoFormat(self,url):
		pass
	def manualVideoCheck(self):
		pass

	def homeContent(self,filter):
		result = {}
		cateManual = {
			"电影": "dianying",
			"电视剧": "dianshiju",
			"综艺": "zongyi",
			"动漫": "dongman",
			"短剧": "duanju"
		}
		classes = []
		for k,v in cateManual.items():
			classes.append({'type_name':k, 'type_id':v})
		result['class'] = classes
		if(filter):
			result['filters'] = self.config['filter']
		return result

	def homeVideoContent(self):
		result = {}
		try:
			url = host_url + '/vodtype/dianshiju.html'
			rsp = self.fetch(url, headers=self.header)
			html = rsp.text
			videos = []
			thumb_blocks = re.findall(r'class="hero-thumb[^"]*"([^>]*)>', html, re.DOTALL)
			for block in thumb_blocks:
				title = re.search(r'data-title="([^"]*)"', block)
				detail = re.search(r'data-detail="/video/([^"]*)\.html"', block)
				bg = re.search(r'data-bg="([^"]*)"', block)
				tags = re.search(r'data-tags="([^"]*)"', block)
				if title and detail and bg:
					videos.append({
						"vod_id": detail.group(1),
						"vod_name": title.group(1),
						"vod_pic": bg.group(1),
						"vod_remarks": tags.group(1) if tags else ""
					})
			hot_pattern = r'<a[^>]*class="hotsearch_hot_item"[^>]*href="/video/([^"]*)\.html"[^>]*title="([^"]*)"[^>]*>.*?<img[^>]*src="([^"]*)"[^>]*class="hotsearch_item_img"'
			hot_items = re.findall(hot_pattern, html, re.DOTALL)
			for vid, title, pic in hot_items:
				if not any(v['vod_id'] == vid for v in videos):
					videos.append({
						"vod_id": vid,
						"vod_name": title,
						"vod_pic": pic,
						"vod_remarks": "热门"
					})
			result['list'] = videos
		except Exception as e:
			print("homeVideoContent error: " + str(e))
			result['list'] = []
		return result

	def categoryContent(self,tid,pg,filter,extend):		
		result = {}
		try:
			url = host_url + '/vodtype/' + tid
			if pg != '1':
				url += '-pg-' + pg
			url += '.html'
			rsp = self.fetch(url, headers=self.header)
			html = rsp.text
			videos = []
			thumb_blocks = re.findall(r'class="hero-thumb[^"]*"([^>]*)>', html, re.DOTALL)
			for block in thumb_blocks:
				title = re.search(r'data-title="([^"]*)"', block)
				detail = re.search(r'data-detail="/video/([^"]*)\.html"', block)
				bg = re.search(r'data-bg="([^"]*)"', block)
				tags = re.search(r'data-tags="([^"]*)"', block)
				if title and detail and bg:
					videos.append({
						"vod_id": detail.group(1),
						"vod_name": title.group(1),
						"vod_pic": bg.group(1),
						"vod_remarks": tags.group(1) if tags else ""
					})
			card_pattern = r'<a[^>]*href="/video/([a-zA-Z0-9]+)\.html"[^>]*title="([^"]*)"[^>]*>.*?<img[^>]*src="([^"]*)"'
			cards = re.findall(card_pattern, html, re.DOTALL)
			for vid, title, pic in cards:
				if not any(v['vod_id'] == vid for v in videos):
					videos.append({
						"vod_id": vid,
						"vod_name": title,
						"vod_pic": pic,
						"vod_remarks": ""
					})
			data_pattern = r'data-url="/video/([a-zA-Z0-9]+)\.html"[^>]*data-title="([^"]*)"[^>]*(?:data-bg|src)="([^"]*)"'
			data_items = re.findall(data_pattern, html, re.DOTALL)
			for vid, title, pic in data_items:
				if title and not any(v['vod_id'] == vid for v in videos):
					videos.append({
						"vod_id": vid,
						"vod_name": title,
						"vod_pic": pic,
						"vod_remarks": ""
					})
			result['list'] = videos
			result['page'] = pg
			result['pagecount'] = 9999
			result['limit'] = 30
			result['total'] = 999999
		except Exception as e:
			print("categoryContent error: " + str(e))
			result['list'] = []
			result['page'] = pg
			result['pagecount'] = 9999
			result['limit'] = 30
			result['total'] = 999999
		return result

	def detailContent(self,array):
		result = {}
		try:
			tid = array[0]
			url = host_url + '/video/' + tid + '.html'
			rsp = self.fetch(url, headers=self.header)
			html = rsp.text
			title = ""
			m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
			if m:
				title = m.group(1).strip()
			if not title:
				m = re.search(r'<title>([^<]+)</title>', html)
				if m:
					title = m.group(1).strip().split('-')[0]
			pic = ""
			m = re.search(r'<img[^>]*class="[^"]*(?:pic|poster|thumb|cover)[^"]*"[^>]*src="([^"]*)"', html)
			if m:
				pic = m.group(1)
			if not pic:
				m = re.search(r'<img[^>]*src="([^"]*)"[^>]*class="[^"]*(?:pic|poster|thumb|cover)[^"]*"', html)
				if m:
					pic = m.group(1)
			desc = extractDesc(html)
			play_from = []
			play_url = []
			# 1. 提取线路名称映射: source-tab data-target="ep-list-4" -> tab-name "NB源"
			source_map = {}
			tabs = re.findall(r'<div class="source-tab"[^>]*data-target="ep-list-(\d+)"[^>]*>.*?<span class="tab-name">(.*?)</span>', html, re.DOTALL)
			for src_id, src_name in tabs:
				source_map[src_id] = src_name.strip()
			# 2. 提取所有播放链接，按线路分组
			all_links = re.findall(r'<a[^>]*href="(/play/([a-zA-Z0-9]+)-(\d+)-(\d+)\.html)"[^>]*class="ep-item-square"[^>]*>(.*?)</a>', html, re.DOTALL)
			if not all_links:
				# fallback: 不限 class
				all_links = re.findall(r'<a[^>]*href="(/play/([a-zA-Z0-9]+)-(\d+)-(\d+)\.html)"[^>]*>(.*?)</a>', html, re.DOTALL)
			if all_links:
				sources = {}
				source_order = []
				for href, vid, src_idx, ep_idx, ep_text in all_links:
					src_name = source_map.get(src_idx, "线路" + src_idx)
					ep_text = re.sub(r'<[^>]+>', '', ep_text).strip()
					if not ep_text:
						ep_text = "第" + ep_idx + "集"
					if src_name not in sources:
						sources[src_name] = []
						source_order.append(src_name)
					sources[src_name].append(ep_text + '$' + href)
				for src_name in source_order:
					play_from.append(src_name)
					play_url.append('#'.join(sources[src_name]))
			# 3. 最终 fallback: data-play 属性
			if not play_from:
				data_plays = re.findall(r'data-play="(/play/([a-zA-Z0-9]+)-(\d+)-(\d+)\.html)"', html)
				if data_plays:
					eps = []
					for href, vid, src_idx, ep_idx in data_plays:
						eps.append("第" + ep_idx + "集$" + href)
					play_from.append("默认")
					play_url.append('#'.join(eps))
			vod = {
				"vod_id": tid,
				"vod_name": title,
				"vod_pic": pic,
				"vod_content": desc,
				"vod_play_from": '$$$'.join(play_from) if play_from else "默认",
				"vod_play_url": '$$$'.join(play_url) if play_url else ""
			}
			result['list'] = [vod]
		except Exception as e:
			print("detailContent error: " + str(e))
		return result

	def searchContent(self, key, quick, pg="1"):
		result = {}
		try:
			url = host_url + '/vod/search/wd/' + quote(key)
			rsp = self.fetch(url, headers=self.header)
			html = rsp.text
			videos = []
			
			search_items = re.findall(r'<div[^>]*class="[^"]*(?:search-item|vod-item|search-list|item-box)[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
			for item in search_items:
				vid = re.search(r'href="/video/([a-zA-Z0-9]+)\.html"', item)
				title = re.search(r'title="([^"]*)"', item)
				pic = re.search(r'src="([^"]*)"', item)
				if vid and title and pic:
					videos.append({
						"vod_id": vid.group(1),
						"vod_name": title.group(1),
						"vod_pic": pic.group(1),
						"vod_remarks": ""
					})
			result['list'] = videos
		except Exception as e:
			print("searchContent error: " + str(e))
			result['list'] = []
		return result

	def _decryptPlayPage(self, url):
		"""抓播放页并调用 /player_api.php 解密，返回 (jmurl, urltype)，失败返回 (None, None)"""
		try:
			rsp = self.fetch(url, headers=self.header)
			html = rsp.text
		except:
			html = ''
		baseKey = ''
		m = re.search(r'baseKey:\s*"([^"]*)"', html)
		if m:
			baseKey = m.group(1)
		requestUrl = ''
		m = re.search(r'requestUrl:\s*"([^"]*)"', html)
		if m:
			requestUrl = m.group(1)
		if not baseKey or not requestUrl:
			return None, None
		timestamp = str(int(time.time()))
		ua = self.header.get('User-Agent', 'Mozilla/5.0')
		token = hashlib.md5((baseKey + timestamp + ua).encode('utf-8')).hexdigest()
		api_url = host_url + '/player_api.php'
		post_data = 'url=' + quote(requestUrl) + '&timestamp=' + timestamp + '&token=' + token
		api_headers = dict(self.header)
		api_headers['Content-Type'] = 'application/x-www-form-urlencoded'
		try:
			try:
				api_rsp = self.fetch(api_url, headers=api_headers, data=post_data, method='POST')
				api_text = api_rsp.text
			except:
				import urllib.request as ur2
				req2 = ur2.Request(api_url, data=post_data.encode('utf-8'), headers=api_headers, method='POST')
				api_text = ur2.urlopen(req2, timeout=15).read().decode('utf-8')
			api_json = json.loads(api_text)
			if not api_json.get('error') and api_json.get('data'):
				# 反转字符串 -> base64解码 -> JSON解析
				rev = api_json['data'][::-1]
				decoded = base64.b64decode(rev).decode('utf-8')
				parsed = json.loads(decoded)
				return parsed.get('jmurl', ''), parsed.get('urltype', '')
		except Exception as e:
			print("decrypt error: " + str(e))
		return None, None

	def _m3u8Ok(self, jmurl):
		"""预检 m3u8 是否有真实视频分片（NB源部分视频是纯图片流，播放器无法解码）"""
		body = ''
		try:
			body = self.fetch(jmurl, headers=self.header).text
		except:
			try:
				import urllib.request as ur2
				body = ur2.urlopen(ur2.Request(jmurl, headers=self.header), timeout=8).read().decode('utf-8', 'ignore')
			except:
				return False
		segs = [l for l in body.splitlines() if l.startswith('http')]
		if not segs:
			return False
		# 抽样嗅探首尾分片：MPEG-TS 流以 0x47 开头，真图片以 0xFFD8/0x8950 开头
		import urllib.request as ur2
		ua = self.header.get('User-Agent', 'Mozilla/5.0')
		ts_count = 0
		for u in [segs[0], segs[-1]]:
			try:
				d = ur2.urlopen(ur2.Request(u, headers={'User-Agent': ua}), timeout=6).read(8)
				if d and d[0] == 0x47:
					ts_count += 1
			except:
				pass
		return ts_count >= 1

	def playerContent(self,flag,id,vipFlags):
		result = {}
		real_url = ''
		try:
			if id.startswith('http'):
				url = id
			else:
				url = host_url + id if id.startswith('/') else host_url + '/' + id
			if '.m3u8' in url or '.mp4' in url or '.flv' in url:
				result["parse"] = 0
				result["url"] = url
				result["header"] = self.header
				return result
			# 1. 解密当前线路
			real_url, _ = self._decryptPlayPage(url)
			if real_url:
				# 仅对拼接型/非标准端口源做预检，其他线路直接放行
				need_check = ('nbyjson' in real_url) or (':889' in real_url)
				if not need_check or self._m3u8Ok(real_url):
					result["parse"] = 0
					result["url"] = real_url
					result["header"] = self.header
					return result
				# 2. 当前线路是图片流，尝试同视频其他线路
				m = re.match(r'https?://[^/]+(/play/([a-zA-Z0-9]+)-(\d+)-(\d+)\.html)', url)
				if not m:
					m = re.match(r'(/play/([a-zA-Z0-9]+)-(\d+)-(\d+)\.html)', url)
				if m:
					vid, cur_src, ep = m.group(2), m.group(3), m.group(4)
					fallback_order = ['1','2','3','5','6','7','8','9']
					if cur_src in fallback_order:
						fallback_order.remove(cur_src)
					for src in fallback_order:
						alt_url = host_url + '/play/' + vid + '-' + src + '-' + ep + '.html'
						try:
							alt_real, _ = self._decryptPlayPage(alt_url)
							if alt_real and self._m3u8Ok(alt_real):
								result["parse"] = 0
								result["url"] = alt_real
								result["header"] = self.header
								return result
						except:
							continue
			# 3. fallback: 旧方式
			html = ''
			try:
				html = self.fetch(url, headers=self.header).text
			except:
				pass
			m = re.search(r'<iframe[^>]*src="([^"]*)"', html)
			if m:
				real_url = m.group(1)
				if real_url.startswith('//'):
					real_url = 'https:' + real_url
				result["parse"] = 0 if any(x in real_url for x in ['.m3u8','.mp4','.flv']) else 1
				result["url"] = real_url
			else:
				m = re.search(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html)
				if not m:
					m = re.search(r'["\'](https?://[^"\']+\.mp4[^"\']*)["\']', html)
				if m:
					result["parse"] = 0
					result["url"] = m.group(1)
				else:
					if real_url:
						result["parse"] = 0
						result["url"] = real_url
					else:
						result["parse"] = 1
						result["url"] = url
			result["header"] = self.header
		except Exception as e:
			print("playerContent error: " + str(e))
			result["parse"] = 1
			result["url"] = id
		return result

	config = {
		"player": {},
		"filter": {
			"dianying":[
				{"key":"year","name":"年份","value":[{"n":"全部","v":""},{"n":"2026","v":"2026"},{"n":"2025","v":"2025"},{"n":"2024","v":"2024"},{"n":"2023","v":"2023"},{"n":"2022","v":"2022"},{"n":"2021","v":"2021"},{"n":"2020","v":"2020"}]},
				{"key":"area","name":"地区","value":[{"n":"全部","v":""},{"n":"中国大陆","v":"中国大陆"},{"n":"美国","v":"美国"},{"n":"韩国","v":"韩国"},{"n":"日本","v":"日本"},{"n":"中国香港","v":"中国香港"}]},
				{"key":"by","name":"排序","value":[{"n":"时间","v":"time"},{"n":"人气","v":"hits"},{"n":"评分","v":"score"}]}
			],
			"dianshiju":[
				{"key":"year","name":"年份","value":[{"n":"全部","v":""},{"n":"2026","v":"2026"},{"n":"2025","v":"2025"},{"n":"2024","v":"2024"},{"n":"2023","v":"2023"},{"n":"2022","v":"2022"},{"n":"2021","v":"2021"},{"n":"2020","v":"2020"}]},
				{"key":"area","name":"地区","value":[{"n":"全部","v":""},{"n":"中国大陆","v":"中国大陆"},{"n":"美国","v":"美国"},{"n":"韩国","v":"韩国"},{"n":"日本","v":"日本"},{"n":"中国香港","v":"中国香港"}]},
				{"key":"by","name":"排序","value":[{"n":"时间","v":"time"},{"n":"人气","v":"hits"},{"n":"评分","v":"score"}]}
			],
			"zongyi":[
				{"key":"year","name":"年份","value":[{"n":"全部","v":""},{"n":"2026","v":"2026"},{"n":"2025","v":"2025"},{"n":"2024","v":"2024"},{"n":"2023","v":"2023"},{"n":"2022","v":"2022"}]},
				{"key":"area","name":"地区","value":[{"n":"全部","v":""},{"n":"中国大陆","v":"中国大陆"},{"n":"韩国","v":"韩国"},{"n":"日本","v":"日本"}]},
				{"key":"by","name":"排序","value":[{"n":"时间","v":"time"},{"n":"人气","v":"hits"},{"n":"评分","v":"score"}]}
			],
			"dongman":[
				{"key":"year","name":"年份","value":[{"n":"全部","v":""},{"n":"2026","v":"2026"},{"n":"2025","v":"2025"},{"n":"2024","v":"2024"},{"n":"2023","v":"2023"},{"n":"2022","v":"2022"}]},
				{"key":"area","name":"地区","value":[{"n":"全部","v":""},{"n":"中国大陆","v":"中国大陆"},{"n":"日本","v":"日本"},{"n":"美国","v":"美国"}]},
				{"key":"by","name":"排序","value":[{"n":"时间","v":"time"},{"n":"人气","v":"hits"},{"n":"评分","v":"score"}]}
			],
			"duanju":[
				{"key":"year","name":"年份","value":[{"n":"全部","v":""},{"n":"2026","v":"2026"},{"n":"2025","v":"2025"},{"n":"2024","v":"2024"},{"n":"2023","v":"2023"}]},
				{"key":"area","name":"地区","value":[{"n":"全部","v":""},{"n":"中国大陆","v":"中国大陆"},{"n":"韩国","v":"韩国"}]},
				{"key":"by","name":"排序","value":[{"n":"时间","v":"time"},{"n":"人气","v":"hits"},{"n":"评分","v":"score"}]}
			]
		}
	}
	header = {
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
		"Referer": "https://zhuiying1.cc/"
	}

	def localProxy(self,param):
		return [200, "video/MP2T", "", ""]
