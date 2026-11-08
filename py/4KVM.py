#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""@header({searchable:1, filterable:1, quickSearch:1, title:'4k影视', lang:'hipy'})"""
# ═══════════════════════════════════════════════════════════════════════════
# 4K影视（https://www.4kvms.org/）—— TVBox / 影视仓系 Python 源
#
# 【目标壳】
#   ① 影视仓 6.2.0 / TVBox 系（catvod csp 契约，PyTVBox / Pyramid 引擎）
#   ② 默影视 5.6.0（MO TV，Chaquopy + Python 3.10，FongMi bean 契约）
#   ③ Pyramid / PyramidStore 系 py 源（影视仓 py 源基类同源）
#   ✗ 海阔视界 dr_py（JS 规则）不覆盖
#
# 【依赖】零第三方依赖，只用 Python 标准库（re/json/time/urllib/inspect/sys/os）
#        无 f-string（保持与同批源一致的风格，便于老壳的解析器处理）
#
# 【兼容范围】（逐条对照壳源码 + 真机可用源写法，证据见各方法注释）
#   init            extend: str（影视仓/TVBox） / JSON 串或数组（默影视、Pyramid）
#   detailContent   ids: list（影视仓直取 ids[0]） / JSON 串 '["ch4re1yqj"]'（默影视 gson.toJson）
#   categoryContent extend: dict 或裸 typeId 串（影视仓） / JSON 串（默影视）
#   playerContent   vipFlags: list（影视仓） / JSON 串（默影视 gson.toJson）
#   localProxy 入参 dict（456movie.py 取 param.get('dddd')） / JSON 串 / query 串 / 裸 URL
#   localProxy 返回 [code:int, ctype:str, body, header:dict] 四元组（第 4 位必须 dict，
#                   chaquo getHeader() 走 asMap()）；失败位 body 是空字符串 ""，不是 b''
#   homeContent     class[] + 顶层 filters{type_id: [Filter]}；
#                   class 内绝不下发 filters（FongMi Class.filters 是 List<Filter>，
#                   发 dict 会让 Gson 抛 Expected BEGIN_ARRAY → 整页空白）
#   class 条目      只发 type_id(str) / type_name(str)
#   detail 关键字段 list[].{vod_play_from, vod_play_url, type_name, vod_tag, ...}
#   player 关键字段 parse / url / header(UA+Referer) / playUrl:"" / jx:0（不下发 flag）
#
# 【站点事实（2026-10-28 实测，写死在此处的都是抓过的真实值）】
#   · 服务端渲染 HTML（nginx + Laravel 风格路由 + Alpine.js + hls.js），非苹果 CMS
#   · 列表：/filter?classify=N&types=&years=&areas=&tags=&sort_by=&order=desc&page=P
#       —— 30 卡/页
#       classify=1 电影 / 2 电视剧 / 3 动漫 / 4 综艺（由 /filter 页 labels 邻接解析得出）
#       无筛选时总页 183（5482 条）；classify=1 时 121 页（3615 条）；classify=2 → 55 页；
#       classify=3 → 8 页；classify=4（综艺）实测 0 卡、无分页 ⇒ 本源不下发「综艺」分类
#       （站点导航本身也无综艺入口），只发 全部/电影/电视剧/动漫
#   · 筛选组（取自 /filter 页，值域即站点自己的 query id）：
#       types 30 项（剧情=1 … 短片=35）、years 79 项（2027=78 … 1921=74）、areas 44 项
#       （美国=5 … 越南=100）、tags 3 项（4k=1 / 院线=36 / TC=37）、
#       sort_by 3 项（update_time 最新上映 / hits 最受欢迎 / score 评分最高，须带 order=desc）
#       各组均可脱离 classify 单独工作（实测 types=1 → 78 页、areas=5 → 54 页、
#       years=4 → 11 页、tags=1 → 5 页），也可与 classify 组合
#       （实测 classify=1&types=1 → 13 页 / 371 条）
#   · 卡片：<div data-vod-id="chXXXX"> 内 <a href="/play/chXXXX"> + <img data-src=…>
#       + <h3>片名</h3> + 角标「全26集 / 更新至21集」；hover 块内另有
#       评分（<span class="text-green-500 font-bold">8.7</span>，实测 30 卡命中 29）
#       与年份（<span class="text-gray-400">2026</span>，30/30），故列表项带 vod_score/vod_year
#   · 详情：/play/{slug}（slug 形如 ch4re1yqj，来自 a[href="/play/…"]，不是数字 id；
#       数字 id 对 /play/ 一律 400）
#       og:title「片名 - 第N集」、og:image、meta description、
#       meta keywords「4k,片名,年份,类型…,地区…,语言…,导演」
#       详情页有结构化信息块（<div class="col-span-1 text-gray-500">标签</div> +
#       <div class="col-span-2 text-gray-300">值</div>）：又名/导演/编剧/主演/类型/
#       地区/语言/上映/片长/英文标题 ⇒ 详情元数据以它为主，keywords 仅兜底
#       评分在详情页头部 span（text-primary-400 text-xs rounded），部分剧集该位为空
#       data-classify-id（1 电影 / 2 电视剧 / 3 动漫）每部作品仅一处 ⇒ 权威分类
#       剧集锚点 a[href="/play/{epid}"][data-line][data-episode][dataid]，
#       每集各有自己的 /play/ slug（第 1 集 slug == 详情 slug，第 2 集起为独立 slug），
#       线路名来自 episodeManager(…, [{lineName:'alists', episodeCount:N}])
#       ⚠ 剧集锚点的 x-effect 属性值里含 '=>'（箭头函数），朴素 <a[^>]*> 必被截断，
#       故本文件用引号感知的标签扫描器 _iter_tags 取属性
#   · 搜索：/search?q=kw 返回 HTML 卡片（a[href="/play/…"][data-vod] + h3 + p 简介），
#       命中数在「找到 <span>N</span> 个结果」；该页无翻页控件，?page= 被站点忽略
#       （实测 page=1 与 page=2 字节数、id 集完全相同）→ 本源搜索 pagecount 恒 1
#   · 播放：直链由站点自有 wasm + hls.js 动态拼装，本文件已把该链整条复现（纯标准库）
#       GET /video/play?p={dataid}&v={slug}&q={清晰度}&s={32位签名}&t={毫秒}&k={令牌}
#         p  该集自己的 dataid —— 取自播放页剧集锚点的 dataid 属性。
#            服务端不校验 p 与 v 的配对，但配错会返回「别的集」的内容（实测
#            p=12215 v=ch4phdr82 返 200 却是另一部片），故必须逐集取自己的 dataid。
#            任一集的播放页都带全集锚点表，按 slug 查表即可（1 次取页）。
#         s  HMAC-SHA256(key=slug, msg="dataid:t:slug") 的十六进制前 32 位
#         t  毫秒时间戳，服务端按 ±45 秒左右窗口校验（实测 ±30s 通过、±60s 被拒）；
#            基准取播放页 <meta id="nb-st"> 的服务端时间，避免设备时钟偏差
#         k  base64(播放页 x-data 里的 userlink 与站点密钥逐字节异或)。
#            userlink 每次刷新页面都会变，必须同页现取现用（跨页复用会 401）。
#         q  清晰度；4K 档的请求值是 q=1（站点前端对清晰度做 '4k'===i?'1':i 的映射），
#            直接传 q=4k 会被服务端 403「4K清晰度仅支持客户端播放，Web端不支持」；
#            q=720/480 返 401「需要VIP会员」；其余值一律回落 1080。
#            实测匿名 Web 侧只能拿到 1080 档：4K 片源的 quality_urls 里确实会多出
#            一条 4K 档（bitrate=2160000），但它 locked/isvip、url 是占位 "1"，
#            要真 4K 得站点会员 + 客户端 HEVC 解码（站点 /page/4kshiplay 自述）。
#       站点密钥不写进本文件：运行时从页面公布的 wasm（<link id="wasm-cfg" data-bg=…>，
#       文件名带内容哈希，不能硬编码路径）里按 data 段结构抽取候选，再用服务端
#       返回码校验（候选不对时服务端回 401「访问令牌格式错误」）。
#       → playerContent 优先给源侧直链（parse=0 + 真 m3u8），失败才交壳（parse=1）
#
# 【未确证项 / 已知限制】（写明原因，不猜测）
#   1. 播放直链：已复现，不再交壳（见上「站点事实 · 播放」）。原先判定「纯标准库内
#      无法复现签名」的结论是错的 —— 错因是把 s 当成「自定义 IV 的 SHA-256 变体」，
#      实际它就是标准 HMAC-SHA256，且 key 是 slug 本身、msg 是 "{dataid}:{t}:{slug}"。
#      密钥仍一律运行时从站点公开 wasm 抽取，不写进本文件。
#   2. 搜索翻页：站点 HTML 搜索页忽略 ?page=（见上），故 searchContent 的 pagecount
#      恒为 1、total 取「找到 N 个结果」。/api/search?q= 的 JSON 字段更全
#      （id/classifyid/parentid/isvip/limitfree/title/cover/poster/year/description/
#      rating/tags/release_time/updatetime/vod_total/updated_episodes），
#      但它返回的是数字 id，/play/{数字} 一律 400，故只用它做「同标题元数据补全」，
#      不作为列表来源。
#   3. 评分：列表页 hover 块有评分（实测 30 卡命中 29，缺失的那张是站点本身没渲染），
#      搜索页卡片无评分（改由 /api/search 的同标题 rating 补全，仍缺则留空）；
#      详情页评分位部分剧集为空。vod_remarks 只用站点自己的角标
#      （全N集 / 更新至N集 / 更新至N/M集），vod_score 单列且取不到就留空，不编造。
#   4. 字幕：站点未提供字幕接口（/video/play 返回的 subtitle_url 恒为 ""），
#      字幕三方法按契约保留但如实返回空，不伪造。
#   5. VIP：站点自身 isvip / limitfree 恒为 0（无分级），但剧集锚点内会出现
#      vip-icon 角标（部分剧集每集都有），故本文件把带 vip-icon 的集记入
#      self._vip_ids，与壳传入的 vipFlags 合并成同一个判定集合，
#      命中即跳过直连发现直接交壳（真实分支，不是只写日志），详见 playerContent 注释。
#      已确证：VIP 集匿名请求 /video/play 返 401「请先登录并开通VIP会员」，
#      匿名侧本就没有直链，交壳是唯一正确解（壳侧带会员通道/登录态）。
#   6. 设备上已有的旧版 4KVM.py（/storage/emulated/0/电视/py/电影/）本轮未读到，
#      无法逐行对照；本文件是按上述契约与模板独立写成的。
#   7. 4K 线路：站点 4K 档只对已登录会员开放，且站点自述「4K 仅支持客户端播放」
#      （/page/4kshiplay：要会员 + 系统装 HEVC 解码）。本源据此给 4K 片源挂了一条
#      「4K线路」：选中它按 4K 档（q=1）请求，匿名侧拿不到真 4K 地址时按 fallback_q
#      回落 1080 直连（保证有画面），不是伪造 4K。要真 4K 需站点会员登录态 +
#      客户端 HEVC。详见 DEFAULT_CONFIG.quality 段与 playerContent 注释。
#
# 【相对模版（didahd_一键提示词.txt）改了什么、为什么】
#   · 模版的 endpoints 一步只给了 4 个 key，本文件按模版要求把「所有路径」都放进
#     endpoints（home/list/class_page/detail/search/search_api/video_play/movie/tv/anime），
#     铁律「禁止硬编码 API 路径」照办：代码里没有任何裸路径。
#   · 模版「步骤4 关键处理」写的是 DouZiMi.fix_pic / QianZiMi.extract_player_url /
#     JieZiMi.clean_m3u8 三个类名 —— 那是嘀嗒影视那套实现的类名，本包内没有对应源码
#     （只有实战案例 md），故本文件保留同样的三段职责、换成 4KVM 自己的实现类
#     SiYuanSi.fix_pic / SiYuanSi.extract_player_url / SiYuanSi.clean_m3u8，
#     并把 13 层播放提取规则做成配置项（player_extract.13_layers），与模版口径一致。
#   · 模版没写 localProxy 的入参形态与四元组细节，本文件按 4K电影网.py 的实测口径补齐，
#     并修掉那一版 _proxy_target 的已知缺陷：先剥前导 '?' 再 parse_qs（否则
#     "?url=…" 会取不到目标、恒 404），同时兼容无前导问号的裸 query。
#   · 模版的「__main__ 自检块」本文件保留并扩成六接口 + localProxy 四形态的回归。
#   · 模版没有给播放直链的实现方式；本文件按站点真实播放链整条复现（p/s/t/k/q 五个
#     参数 + 从公开 wasm 抽密钥），playerContent 从「一律交壳」改成「优先源侧直链
#     （parse=0 + 真 m3u8），失败才交壳（parse=1）」，修掉首版「点击播放无反应」。
#   · 新增 4K 线路：4K 片源在详情页多挂一条「4K线路」（DEFAULT_CONFIG.quality 配置
#     驱动），playerContent 按线名走 4K 档请求 + 回落，细节见两处注释。
# ═══════════════════════════════════════════════════════════════════════════

import base64
import hashlib
import hmac
import inspect
import json
import os
import re
import sys
import time
import urllib.error as _error
import urllib.parse as _parse
import urllib.request as _request

# ── 壳基类：默影视 / Pyramid 系从 base.spider 导入抽象基类；
#    精简壳里没有这个模块时退化成普通 object，保证源能实例化。────
try:  # pragma: no cover - 只在壳内环境命中
    from base.spider import Spider as _ShellSpider
except Exception:  # pragma: no cover
    class _ShellSpider(object):
        pass

# ── 壳族标识：只用于日志，不影响任何返回结构 ────────────────────────
SHELL_TVBOX = "tvbox"        # 影视仓 / TVBox（PyTVBox / Pyramid 引擎）
SHELL_MOYING = "moying"      # 默影视 5.6.0（Chaquopy）
SHELL_GENERIC = "generic"    # 通用/自测


# ── 播放直链：站点 wasm 的运行时密钥抽取（纯标准库；本文件不硬编码任何站点密钥）──
#    站点把播放签名密钥放在自己公开的 wasm 二进制里，文件名带内容哈希
#    （/static/wasm/nbmovie_wasm_bg.<hash>.wasm），故只能运行时从页面里发现地址、
#    再从字节里按结构抽出密钥候选，绝不写死。
_WASM_KEY_CACHE = {}


def _wasm_uleb(data, pos):
    """读 wasm 的 ULEB128 无符号整数，返回 (值, 新位置)。"""
    result = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if not (byte & 0x80):
            break
    return result, pos


def _wasm_skip_sleb(data, pos):
    """跳过 wasm 的 SLEB128 有符号整数（i32.const / i64.const 的立即数）。"""
    while pos < len(data):
        byte = data[pos]
        pos += 1
        if not (byte & 0x80):
            break
    return pos


def _wasm_data_segments(raw):
    """解析 wasm 二进制的 data 段（section id 11），返回各 segment 的字节内容。"""
    segments = []
    if not raw or raw[:4] != b"\x00asm":
        return segments
    pos = 8
    total = len(raw)
    while pos < total:
        section_id = raw[pos]
        pos += 1
        size, pos = _wasm_uleb(raw, pos)
        end = pos + size
        if section_id != 11:
            pos = end
            continue
        count, cursor = _wasm_uleb(raw, pos)
        for _ in range(min(count, 64)):
            flags, cursor = _wasm_uleb(raw, cursor)
            if flags != 1:
                if flags == 2:
                    _, cursor = _wasm_uleb(raw, cursor)
                while cursor < end:
                    opcode = raw[cursor]
                    cursor += 1
                    if opcode in (0x41, 0x42):
                        cursor = _wasm_skip_sleb(raw, cursor)
                    elif opcode == 0x43:
                        cursor += 4
                    elif opcode == 0x44:
                        cursor += 8
                    elif opcode == 0x23:
                        _, cursor = _wasm_uleb(raw, cursor)
                    elif opcode == 0x0B:
                        break
                    else:
                        break
            length, cursor = _wasm_uleb(raw, cursor)
            segments.append(raw[cursor:cursor + length])
            cursor += length
        break
    return segments


def _wasm_key_candidates(raw):
    """从 wasm 的 data 段里抽候选密钥串（首段开头的 printable 串排在最前）。"""
    candidates = []
    segments = _wasm_data_segments(raw)
    for index, content in enumerate(segments):
        runs = re.findall(rb"[!-~]{8,64}", content)
        for run in runs:
            try:
                text = run.decode("ascii")
            except Exception:
                continue
            if text not in candidates:
                candidates.append(text)
        if index == 0 and runs:
            try:
                lead = runs[0].decode("ascii")
            except Exception:
                lead = ""
            if lead and lead in candidates:
                candidates.remove(lead)
                candidates.insert(0, lead)
    return candidates


# ═══════════════════════════════════════════════════════════════════════════
# DEFAULT_CONFIG —— 覆盖式配置，所有可变项集中在此，改站点只改这里
# ═══════════════════════════════════════════════════════════════════════════
DEFAULT_CONFIG = {
    "name": "4k影视",
    "host": "https://www.4kvms.org",
    "backup_hosts": [],
    "headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.4kvms.org/",
    },
    # 站点所有路径集中在这里，代码里不出现裸路径
    "endpoints": {
        "home": "/",
        "class_page": "/{kind}",
        "list": "/filter",
        "detail": "/play/{vid}",
        "play": "/play/{vid}",
        "search": "/search?q={kw}",
        "search_api": "/api/search?q={kw}",
        "video_play": "/video/play",
    },
    # 分类：type_id 即站点的 classify 值；「全部」= 不带 classify
    "classes": [
        # 「全部」= /filter 不带 classify（实测 183 页 / 5482 条）
        {"type_id": "0", "type_name": "全部"},
        {"type_id": "1", "type_name": "电影"},
        {"type_id": "2", "type_name": "电视剧"},
        {"type_id": "3", "type_name": "动漫"},
    ],
    # 分类 → 站点列表页 kind 的映射（栏目页 /movie /tv /anime 与筛选页 /filter 共用 classify 语义）
    "class_kinds": {"0": "all", "1": "movie", "2": "tv", "3": "anime"},
    # 分类 → /filter 的 classify 参数（"0"=全部 → 不带 classify）
    "class_classify": {"0": "", "1": "1", "2": "2", "3": "3"},
    # 站点 data-classify-id → 中文分类名（详情页每部作品只有一个该属性，权威）
    "classify_names": {"1": "电影", "2": "电视剧", "3": "动漫", "4": "综艺"},
    # 筛选组：键名即站点 query 参数名，值为站点自己的 id
    "filters": {
        "类型": {
            "key": "types",
            "values": [
                {"n": "剧情", "v": "1"},
                {"n": "悬疑", "v": "2"},
                {"n": "恐怖", "v": "3"},
                {"n": "惊悚", "v": "4"},
                {"n": "喜剧", "v": "5"},
                {"n": "爱情", "v": "6"},
                {"n": "犯罪", "v": "9"},
                {"n": "动作", "v": "10"},
                {"n": "动画", "v": "11"},
                {"n": "奇幻", "v": "12"},
                {"n": "音乐", "v": "13"},
                {"n": "科幻", "v": "14"},
                {"n": "历史", "v": "15"},
                {"n": "战争", "v": "16"},
                {"n": "冒险", "v": "18"},
                {"n": "家庭", "v": "19"},
                {"n": "纪录", "v": "20"},
                {"n": "西部", "v": "23"},
                {"n": "电视电影", "v": "24"},
                {"n": "情色", "v": "25"},
                {"n": "真人秀", "v": "26"},
                {"n": "古装", "v": "27"},
                {"n": "传记", "v": "28"},
                {"n": "同性", "v": "29"},
                {"n": "运动", "v": "30"},
                {"n": "武侠", "v": "31"},
                {"n": "歌舞", "v": "32"},
                {"n": "纪录片", "v": "33"},
                {"n": "灾难", "v": "34"},
                {"n": "短片", "v": "35"},
            ],
        },
        "年份": {
            "key": "years",
            "values": [
                {"n": "2027", "v": "78"},
                {"n": "2026", "v": "1"},
                {"n": "2025", "v": "3"},
                {"n": "2024", "v": "4"},
                {"n": "2023", "v": "56"},
                {"n": "2022", "v": "13"},
                {"n": "2021", "v": "2"},
                {"n": "2020", "v": "6"},
                {"n": "2019", "v": "8"},
                {"n": "2018", "v": "9"},
                {"n": "2017", "v": "12"},
                {"n": "2016", "v": "11"},
                {"n": "2015", "v": "14"},
                {"n": "2014", "v": "15"},
                {"n": "2013", "v": "22"},
                {"n": "2012", "v": "10"},
                {"n": "2011", "v": "17"},
                {"n": "2010", "v": "25"},
                {"n": "2009", "v": "20"},
                {"n": "2008", "v": "23"},
                {"n": "2007", "v": "30"},
                {"n": "2006", "v": "31"},
                {"n": "2005", "v": "7"},
                {"n": "2004", "v": "24"},
                {"n": "2003", "v": "28"},
                {"n": "2002", "v": "19"},
                {"n": "2001", "v": "29"},
                {"n": "2000", "v": "43"},
                {"n": "1999", "v": "45"},
                {"n": "1998", "v": "33"},
                {"n": "1997", "v": "34"},
                {"n": "1996", "v": "37"},
                {"n": "1995", "v": "21"},
                {"n": "1994", "v": "27"},
                {"n": "1993", "v": "26"},
                {"n": "1992", "v": "35"},
                {"n": "1991", "v": "18"},
                {"n": "1990", "v": "42"},
                {"n": "1989", "v": "44"},
                {"n": "1988", "v": "60"},
                {"n": "1987", "v": "73"},
                {"n": "1986", "v": "32"},
                {"n": "1985", "v": "40"},
                {"n": "1984", "v": "63"},
                {"n": "1983", "v": "59"},
                {"n": "1982", "v": "36"},
                {"n": "1981", "v": "5"},
                {"n": "1980", "v": "39"},
                {"n": "1979", "v": "61"},
                {"n": "1978", "v": "66"},
                {"n": "1977", "v": "48"},
                {"n": "1976", "v": "38"},
                {"n": "1975", "v": "57"},
                {"n": "1974", "v": "62"},
                {"n": "1973", "v": "53"},
                {"n": "1972", "v": "54"},
                {"n": "1971", "v": "51"},
                {"n": "1969", "v": "41"},
                {"n": "1968", "v": "77"},
                {"n": "1966", "v": "76"},
                {"n": "1965", "v": "58"},
                {"n": "1964", "v": "79"},
                {"n": "1963", "v": "46"},
                {"n": "1962", "v": "65"},
                {"n": "1961", "v": "71"},
                {"n": "1960", "v": "75"},
                {"n": "1959", "v": "16"},
                {"n": "1958", "v": "67"},
                {"n": "1957", "v": "50"},
                {"n": "1956", "v": "49"},
                {"n": "1955", "v": "47"},
                {"n": "1954", "v": "68"},
                {"n": "1952", "v": "72"},
                {"n": "1949", "v": "70"},
                {"n": "1948", "v": "64"},
                {"n": "1938", "v": "52"},
                {"n": "1931", "v": "55"},
                {"n": "1925", "v": "69"},
                {"n": "1921", "v": "74"},
            ],
        },
        "地区": {
            "key": "areas",
            "values": [
                {"n": "美国", "v": "5"},
                {"n": "法国", "v": "6"},
                {"n": "中国", "v": "7"},
                {"n": "unknown", "v": "9"},
                {"n": "日本", "v": "11"},
                {"n": "韩国", "v": "12"},
                {"n": "中国香港", "v": "14"},
                {"n": "俄罗斯", "v": "16"},
                {"n": "波兰", "v": "17"},
                {"n": "德国", "v": "18"},
                {"n": "意大利", "v": "19"},
                {"n": "中国台湾", "v": "21"},
                {"n": "澳大利亚", "v": "22"},
                {"n": "西班牙", "v": "24"},
                {"n": "英国", "v": "30"},
                {"n": "加拿大", "v": "32"},
                {"n": "泰国", "v": "33"},
                {"n": "印度", "v": "34"},
                {"n": "丹麦", "v": "41"},
                {"n": "中国大陆", "v": "52"},
                {"n": "马来西亚", "v": "65"},
                {"n": "菲律宾", "v": "74"},
                {"n": "其他", "v": "78"},
                {"n": "瑞典", "v": "79"},
                {"n": "挪威", "v": "80"},
                {"n": "阿根廷", "v": "81"},
                {"n": "冰岛", "v": "82"},
                {"n": "保加利亚", "v": "83"},
                {"n": "爱尔兰", "v": "84"},
                {"n": "墨西哥", "v": "86"},
                {"n": "比利时", "v": "87"},
                {"n": "瑞士", "v": "88"},
                {"n": "克罗地亚", "v": "89"},
                {"n": "Philippines", "v": "90"},
                {"n": "马耳他", "v": "91"},
                {"n": "匈牙利", "v": "92"},
                {"n": "西德", "v": "93"},
                {"n": "新西兰", "v": "94"},
                {"n": "哥伦比亚", "v": "95"},
                {"n": "巴西", "v": "96"},
                {"n": "印度尼西亚", "v": "97"},
                {"n": "南非", "v": "98"},
                {"n": "奥地利", "v": "99"},
                {"n": "越南", "v": "100"},
            ],
        },
        "标签": {
            "key": "tags",
            "values": [
                {"n": "4k", "v": "1"},
                {"n": "院线", "v": "36"},
                {"n": "TC", "v": "37"},
            ],
        },
        "排序": {
            "key": "sort_by",
            "values": [
                {"n": "最新上映", "v": "update_time"},
                {"n": "最受欢迎", "v": "hits"},
                {"n": "评分最高", "v": "score"},
            ],
        }
    },
    "selectors": {
        "card_attr": 'data-vod-id="',
        "card_href_re": r'href="/play/([^"]+)"',
        "card_img_re": r'data-src="([^"]+)"',
        "card_title_re": r"<h3[^>]*>(.*?)</h3>",
        "card_badge_re": r'>\s*((?:全|更新至)\d+集)\s*<',  # 角标（站点角标带换行缩进）
        "card_rating_re": r'text-green-500 font-bold">\s*([\d.]+)\s*<',  # 列表卡评分（hover 块）
        "card_year_re": r'text-gray-400">\s*(\d{4})\s*<',   # 列表卡年份
        "card_desc_re": r'<p class="text-gray-400 text-xs lg:text-sm line-clamp-2[^"]*">(.*?)</p>',
        "card_tag_re": r'>\s*(4k)\s*<',                      # 列表卡右上角 4k 角标
        "search_card_re": r'class="group relative"',          # 搜索页卡片外层标记
        "search_year_re": r'absolute top-2 left-2[^>]*>\s*(\d{4})\s*<',
        "search_desc_re": r'<p class="text-xs text-gray-300 line-clamp-2">(.*?)</p>',
        "detail_pair_re": r'<div class="col-span-1 text-gray-500">([^<]*)</div>\s*'
                          r'<div class="col-span-2 text-gray-300">([^<]*)</div>',
        "detail_classify_re": r'data-classify-id="(\d+)"',
        "detail_score_re": r'text-primary-400 text-xs rounded">(.*?)</span>',
        "detail_update_re": r'更新至\s*([\d/]+\s*集)',
        "detail_h1_re": r'<h1[^>]*>(.*?)</h1>',
        "og_title_re": r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"',
        "og_image_re": r'<meta[^>]+property="og:image"[^>]+content="([^"]*)"',
        "meta_desc_re": r'<meta[^>]+name="description"[^>]+content="([^"]*)"',
        "meta_keys_re": r'<meta[^>]+name="keywords"[^>]+content="([^"]*)"',
        "search_total_re": r'找到\s*<span[^>]*>(\d+)</span>\s*个结果',
        "page_re": r'page=(\d+)',
        "episode_re": r'data-episode="(\d+)"',
        "line_re": r'data-line="(\d+)"',
    },
    # 播放直链提取：13 层规则（配置驱动，缺一层不影响其它层）
    "player_extract": {
        "13_layers": [
            r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)',
            r'sources\s*:\s*\[\s*\{[^}]*?["\']?file["\']?\s*:\s*["\']([^"\']+)',
            r'["\']?file["\']?\s*:\s*["\']([^"\']+)',
            r'["\']?src["\']?\s*:\s*["\']([^"\']+)',
            r'["\']?url["\']?\s*:\s*["\']([^"\']+)',
            r'(https?://[^"\'\s]+/hls/[^"\'\s]+\.m3u8[^"\'\s]*)',
            r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)',
            r'url\s*[:=]\s*["\']([^"\']+)["\']',
            r'play_url\s*[:=]\s*["\']([^"\']+)["\']',
            r'hls\s*[:=]\s*["\']([^"\']+)["\']',
            r'(https?:\\?/\\?/[^"\'\s]+\.m3u8[^"\'\s]*)',
            r'(//[^"\'\s]+\.m3u8[^"\'\s]*)',
        ],
    },
    "m3u8": {
        "ad_keywords": ["#EXTVLCOPT:http-referrer", "advert", "doubleclick", "adservice",
                        "umiya", "pangolin", "cdn-cgi"],
        "ad_line_patterns": [r'^#EXT-X-MEDIA.*?URI="([^"]+)"',
                            r"^#EXTINF.*?,(https?://\S+)$"],
    },
    "player": {
        "use_local_proxy": True,
        "referer_on_play": True,
        "timeout": 20,
    },
    # ── 清晰度线路（4K）────────────────────────────────────────────────
    # 站点事实（2026-11-08 实测，证据见文件头「站点事实 · 播放」）：
    #   · 4K 片源的作品，/video/play 的 quality_urls 会多出一条 4K 档
    #     （bitrate=2160000、title='4K'、locked/isvip、url 恒为占位 "1"）；
    #     非 4K 片源只有 1080p 一条。片源是不是 4K 看详情页 keywords 首字段（4k）。
    #   · 清晰度参数 q：站点前端把 4k 档映射成 q=1（'4k'===i?'1':i）；直接传 q=4k
    #     被服务端 403「4K清晰度仅支持客户端播放，Web端不支持」；q=720/480 返 401
    #     「需要VIP会员」；其余值一律回落 1080。
    #   · 因此 4K 档在匿名 Web 侧拿不到真实地址。本源据此给 4K 片源额外挂一条
    #     「4K线路」：选中它按 4K 档请求，拿到真地址就直连；拿不到按 fallback_q
    #     回落（保证有画面），再不行交壳；绝不伪造 4K 地址。
    #     要真 4K 需站点会员登录态 + 客户端 HEVC 解码（站点 /page/4kshiplay 自述）。
    "quality": {
        "default_q": "1080",                  # 普通线路请求的清晰度
        "q_4k": "1",                          # 4K 档的请求值（站点前端的映射口径）
        "bitrate_4k": 2160000,                # quality_urls 里 4K 档的 bitrate 标记
        "line_4k": "4K线路",                   # 4K 线路在播放器里的线名
        "flag_4k": ["4K线路", "4K", "4k"],     # playerContent 判定「选了 4K 线路」
        "tag_4k": ["4k", "4K"],               # 详情页 keywords 首字段=4k 视为 4K 片源
        "fallback_q": "1080",                 # 4K 档拿不到真实地址时回落的清晰度
    },
    # 本地代理：只代理站点自身与它实际使用的静态/媒体域名
    "proxy": {
        "allowed_hosts": [
            "4kvms.org",
            "4kvm.staticimgjs.org",
            "oss.douyinbit.com",
            "myoss.douyinbit.top",
            "image.tmdb.org",
            "gimg0.baidu.com",
        ],
    },
    # 网络参数
    "net": {
        "timeout": 20,
        "retry": 3,
        "delay": 1.2,
        "delay_agg": 0.35,
    },
    "search": {
        "primary": "html",
        "pagecount": 1,
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# 兼容层：文本解码 / 兜底请求
# ═══════════════════════════════════════════════════════════════════════════
def _decode_text(raw):
    """把字节流解成文本：utf-8 → gbk → gb18030 → latin-1 逐级兜底。"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        data = bytes(raw)
    else:
        data = str(raw).encode("utf-8", "ignore")
    if not data:
        return ""
    for enc in ("utf-8", "gbk", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", "ignore")


class _Resp(object):
    """标准库兜底请求的最小响应对象，字段与壳内 requests 风格响应对齐。"""

    __slots__ = ("status", "body", "headers", "url")

    def __init__(self, body=b"", status=200, headers=None, url=""):
        self.status = status
        self.body = body or b""
        self.headers = headers or {}
        self.url = url

    @property
    def content(self):
        """requests 风格别名：正文 bytes（_text() 先取 content 再取 text）。"""
        return self.body

    @property
    def status_code(self):
        """requests 风格别名：HTTP 状态码。"""
        return self.status

    def text(self):
        return _decode_text(self.body)


def _urllib_fetch(url, headers=None, timeout=20):
    """壳外兜底请求：只用标准库，含 gzip 解压。"""
    req = _request.Request(url, headers=headers or {})
    try:
        with _request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                import gzip
                body = gzip.decompress(body)
            return _Resp(body, getattr(r, "status", 200), dict(r.headers), url)
    except _error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return _Resp(body, getattr(e, "code", 0), {}, url)
    except Exception as e:
        raise e


# ═══════════════════════════════════════════════════════════════════════════
# 思源思 —— 解析助手（对应模版里的 DouZiMi / QianZiMi / JieZiMi 三段职责）
# ═══════════════════════════════════════════════════════════════════════════
class SiYuanSi(object):
    """思源思：清洗 / 图片修复 / 播放直链提取 / m3u8 广告清洗。"""

    @staticmethod
    def clean_text(raw):
        """把一段 HTML 片段洗成纯文本（去注释、去标签、反转义、压空白）。"""
        if raw is None:
            return ""
        try:
            out = str(raw)
        except Exception:
            return ""
        try:
            out = re.sub(r"<!--.*?-->", " ", out, flags=re.S)
            out = re.sub(r"<[^>]+>", " ", out)
            out = out.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            out = out.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
            # 二次转义还原后可能又出现注释/标签（如搜索卡简介里的 &lt;!-- wp:paragraph --&gt;）
            out = re.sub(r"<!--.*?-->", " ", out, flags=re.S)
            out = re.sub(r"<[^>]+>", " ", out)
            out = out.replace("\\u3000", " ").replace("　", " ")
            return re.sub(r"\s+", " ", out).strip()
        except Exception:
            return ""

    @staticmethod
    def fix_pic(url, host=""):
        """图片地址修复：解实体、补协议、补域名、滤掉占位图。"""
        u = (url or "").strip().replace("\\/", "/")
        try:
            import html as _html
            u = _html.unescape(u)
        except Exception:
            pass
        if not u or u.startswith("data:"):
            return ""
        if "placeholder" in u:
            return ""
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        base = (host or "").rstrip("/")
        if u.startswith("/"):
            return base + u
        return base + "/" + u.lstrip("./")

    @staticmethod
    def extract_player_url(html, layers=None):
        """13 层播放直链提取；取不到返回空串，交由上层回退，不伪造直链。

        layers 可以是「正则字符串列表」，也可以是「{'name','pattern'} 字典列表」。
        """
        if not html:
            return ""
        for layer in (layers or []):
            name = ""
            pattern = layer
            if isinstance(layer, dict):
                name = layer.get("name") or ""
                pattern = layer.get("pattern") or ""
            if not pattern:
                continue
            try:
                m = re.search(pattern, html, re.S | re.I)
            except Exception:
                continue
            if not m:
                continue
            try:
                url = (m.group(1) if m.groups() else m.group(0)).strip()
            except Exception:
                url = ""
            if not url:
                continue
            url = url.replace("\\/", "/").replace("\\u0026", "&")
            if url.startswith("//"):
                url = "https:" + url
            if url.startswith("http"):
                return url
        return ""

    @staticmethod
    def clean_m3u8(content, ad_keywords=None, ad_line_patterns=None):
        """清洗 m3u8：去掉含广告特征的片段行与广告关键字域名。"""
        ads = [k.lower() for k in (ad_keywords or [])]
        keep = []
        for line in (content or "").splitlines():
            low = line.lower()
            if any(k and k in low for k in ads):
                continue
            drop = False
            for pat in (ad_line_patterns or []):
                try:
                    if re.search(pat, line, re.I):
                        drop = True
                        break
                except Exception:
                    pass
            if drop:
                continue
            keep.append(line)
        return "\n".join(keep)

    @staticmethod
    def is_media(url):
        """判断是否为可直放的媒体地址。"""
        return bool(re.search(r"\.(?:m3u8|mp4|flv|mkv|avi|ts)(?:\?|#|$)", url or "", re.I))

    @staticmethod
    def split_episodes(play_url, sep="#", kv="$"):
        """把「剧集名$直链#剧集名$直链」拆成 [(剧集名, 直链)]。"""
        eps = []
        for chunk in (play_url or "").split(sep):
            chunk = (chunk or "").strip()
            if not chunk:
                continue
            if kv in chunk:
                name, _, url = chunk.partition(kv)
            else:
                name, url = "", chunk
            eps.append((name.strip(), url.strip()))
        return eps


# ═══════════════════════════════════════════════════════════════════════════
# 基类：六接口契约 + 统一取页（串行、限速、超时、退避重试）
# ═══════════════════════════════════════════════════════════════════════════
class KvmBase(_ShellSpider):
    """4k影视基类：统一取页、统一日志、壳族探测。"""

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.cfg = DEFAULT_CONFIG
        self.siteUrl = self.cfg["host"]
        self.name = self.cfg["name"]
        self.headers = dict(self.cfg["headers"])
        self.shell_kind = SHELL_GENERIC
        self.shell_why = []
        self.extend = ""
        self._vip_ids = set()

    # ───── 壳族运行时探测（只用于日志，不改返回结构）─────
    def _probe_shell(self):
        """识别承载本源的壳族。

        判据强弱：基类带 xpText/postJson → Pyramid 系；带 loadSpider/regStr →
        默影视系；基类 fetch 签名 → 两族都是 requests 风格，只算弱信号。
        真正决定入参形态的是「入参本身长什么样」，各处已就地做双形态容错。
        """
        kind = SHELL_GENERIC
        why = []
        base = _ShellSpider
        try:
            if base is not None and base is not object:
                names = set(dir(base))
                if "xpText" in names or "postJson" in names or "setExtendInfo" in names:
                    kind = SHELL_TVBOX
                    why.append("基类带 xpText/postJson/setExtendInfo（Pyramid / TVBoxOSC 系）")
                elif "loadSpider" in names or "regStr" in names:
                    kind = SHELL_MOYING
                    why.append("基类带 loadSpider/regStr 且无 xpText（WebHomeTV / 默影视 系）")
                try:
                    params = inspect.signature(base.fetch).parameters
                    if "timeout" in params or "verify" in params:
                        why.append("基类 fetch 带 timeout/verify（requests 风格 fuller）")
                    else:
                        why.append("基类 fetch 参数较少（Pyramid 系简版）")
                except Exception as e:
                    why.append("基类 fetch 签名探测失败（按通用形态处理）")
        except Exception as e:
            why.append("壳族探测异常：%s" % e)
        if getattr(self, "siteKey", None):
            why.append("源对象带 siteKey（宿主为 Python 桥接，两族都可能注入）")
        return kind, why

    # ───── 日志（分级，不静默吞异常）─────
    def log(self, msg, level="INFO"):
        try:
            print("[4k影视][%s] %s" % (level, msg))
        except Exception:
            print("[4k影视][ERROR] 日志输出失败")

    # ───── 取页 ─────
    def fetch(self, url, headers=None, timeout=None, **kwargs):
        """取回一个 HTTP 响应。

        壳基类 fetch 签名两族都是 requests 风格但参数集不同：
          · 默影视 chaquo/webhtv：fetch(url, params=, cookies=, headers=, timeout=, verify=…)
          · Pyramid 系：fetch(url, headers={}, cookies="")
        故先用 inspect 看清基类接受哪些关键字，只传它支持的；再用 TypeError
        兜底重试；最后才落到标准库（保证精简壳里也能用）。
        """
        h = dict(self.headers)
        h.update(headers or {})
        timeout = timeout or self.cfg["net"]["timeout"]
        shell_fetch = getattr(super(), "fetch", None)
        if callable(shell_fetch):
            supported = None
            try:
                sig = inspect.signature(shell_fetch)
                params = sig.parameters
                has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD
                                 for p in params.values())
                supported = None if has_var_kw else set(params.keys())
            except Exception as e:
                self.log("壳内 fetch 签名探测失败：%s" % e, "WARN")
            for extra in ({"timeout": timeout}, {}):
                call_kwargs = dict(kwargs)
                call_kwargs.update(extra)
                if supported is not None:
                    call_kwargs = {k: v for k, v in call_kwargs.items() if k in supported}
                try:
                    return shell_fetch(url, headers=h, **call_kwargs)
                except TypeError as e:
                    self.log("壳内 fetch 签名不匹配（%s），调整参数重试" % e, "WARN")
                    continue
                except NotImplementedError:
                    break
                except Exception as e:
                    self.log("壳内 fetch 失败，回退标准库：%s" % e, "WARN")
                    break
        return _urllib_fetch(url, h, timeout)

    def _text(self, resp):
        """把壳内 fetch 的返回值统一成文本（str / bytes / Response 三种都吃）。"""
        if resp is None:
            return ""
        if isinstance(resp, (bytes, bytearray)):
            return _decode_text(bytes(resp))
        if isinstance(resp, str):
            return resp
        content = getattr(resp, "content", None)
        if isinstance(content, (bytes, bytearray)):
            return _decode_text(bytes(content))
        text = getattr(resp, "text", None)
        if isinstance(text, str):
            return text
        if isinstance(text, (bytes, bytearray)):
            return _decode_text(bytes(text))
        body = getattr(resp, "body", None)
        if isinstance(body, (bytes, bytearray)):
            return _decode_text(bytes(body))
        return ""

    def _url(self, key, **kw):
        path = self.cfg["endpoints"][key].format(**kw)
        if path.startswith("http"):
            return path
        return self.siteUrl.rstrip("/") + path

    def _get(self, url, referer=None):
        """带重试与退避的取页，失败返回空串而不是抛裸异常。"""
        if not url:
            return ""
        headers = {}
        if referer:
            headers["Referer"] = referer
        retry = max(1, int(self.cfg["net"]["retry"]))
        for i in range(retry):
            try:
                resp = self.fetch(url, headers=headers)
                status = getattr(resp, "status_code", 200)
                text = self._text(resp)
                if status and status >= 400:
                    self.log("HTTP %s %s" % (status, url), "WARN")
                if text:
                    return text
            except Exception as e:
                self.log("请求第 %d 次失败 %s：%s" % (i + 1, url, e), "WARN")
            if i + 1 < retry:
                time.sleep(float(self.cfg["net"]["delay"]))
        return ""

    def _get_json(self, key, **kw):
        """取 JSON 接口；失败返回空字典，不抛异常。"""
        url = self._url(key, **kw)
        text = self._get(url, referer=self.siteUrl.rstrip("/") + "/")
        if not text:
            return {}
        try:
            obj = json.loads(text)
        except ValueError as e:
            self.log("JSON 解析失败 %s：%s" % (url, e), "WARN")
            return {}
        if isinstance(obj, dict) and "data" in obj:
            data = obj.get("data")
            return data if isinstance(data, dict) else obj
        if not isinstance(obj, dict):
            self.log("JSON 结构异常 %s：%s" % (url, type(obj).__name__), "WARN")
            return {}
        return obj

    # ───── 分页信息 ─────
    def _page_total(self, html):
        """从「共 N 页，共 M 个结果」里取真实页数与总数；取不到返回 (0, 0)。"""
        try:
            m = re.search(r"共\s*(\d+)\s*页[，,]\s*共\s*(\d+)\s*个", html or "")
            if m:
                return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
        return 0, 0

    def _page_max(self, html):
        """从分页链接里取最大的 page= 值（真实总页数的兜底来源）。"""
        try:
            pages = [int(x) for x in re.findall(r"page=(\d+)", html or "")]
            return max(pages) if pages else 0
        except Exception:
            return 0


# ═══════════════════════════════════════════════════════════════════════════
# Spider —— 六接口 + 影视仓/默影视/Pyramid 兼容层
# ═══════════════════════════════════════════════════════════════════════════
class Spider(KvmBase):
    """4k影视（4kvm.org）源。

    站点是服务端渲染的 HTML 站（不是苹果 CMS），所有数据都从 HTML 里解析：
      列表  /filter?classify=&types=&years=&areas=&tags=&sort_by=&order=desc&page=
      详情  /play/{slug}（slug 形如 ch4re1yqj，来自 a[href="/play/…"]）
      搜索  /search?q=kw（HTML，另有 /api/search?q=kw 的 JSON，只用于补元数据）
    """

    # ───── 壳契约 ─────
    def getName(self):
        # 字面量站点名（壳在首页显示这个名字）
        return "4k影视"

    def getDependence(self):
        # 零第三方依赖
        return []

    def init(self, extend=""):
        """壳初始化：extend 形态极杂，逐一兼容，任何形态都不外抛。"""
        try:
            info = extend
            if isinstance(info, str):
                raw = info.strip()
                if not raw:
                    info = {}
                elif raw.startswith("{"):
                    try:
                        info = json.loads(raw)
                    except Exception as e:
                        self.log("init extend JSON 解析失败：%s" % e, "WARN")
                        info = {}
                elif raw.startswith("http"):
                    info = {"url": raw}
                else:
                    info = {"extend": raw}
            if isinstance(info, (list, tuple)):
                info = {"extend": info[0] if info else ""}
            if not isinstance(info, dict):
                info = {}
            host = info.get("host") or info.get("url") or info.get("siteUrl")
            if host and str(host).startswith("http"):
                self.siteUrl = str(host).rstrip("/")
                self.log("init 使用外部 host：%s" % self.siteUrl)
            ext = info.get("extend") or info.get("cookie") or ""
            self.extend = ext
        except Exception as e:
            self.log("init 异常：%s" % e, "ERROR")
        try:
            kind, why = self._probe_shell()
            self.shell_kind = kind
            self.shell_why = why
            self.log("壳族判定：%s（%s）" % (kind, "；".join(why) if why else "无特征"))
        except Exception as e:
            self.log("壳族探测异常：%s" % e, "WARN")
        return None

    def isVideoFormat(self):
        # 本源不下发视频直链，壳按普通网页结果处理
        return False

    def manualVideoCheck(self):
        # 与 isVideoFormat 保持一致：本源不做人工视频校验
        return False

    def destroy(self):
        return "Destroy"

    def action(self, action):
        self.log("action=%s 未使用" % action)
        return None

    def liveContent(self, url):
        # 站点没有直播分类
        return {"list": []}

    # ───── 字幕：站点没有字幕接口（/video/play 返回的 subtitle_url 恒为空串）───
    def subtitle_init(self, config=""):
        return ""

    def subtitle_search(self, request=""):
        return ""

    def subtitle_resolve(self, request=""):
        return ""

    # ───── 内部工具 ─────
    def _play_header(self):
        """播放请求头：UA + 站点 Referer（站点按 Referer 区分来源）。"""
        header = {"User-Agent": self.headers.get("User-Agent", "")}
        if self.cfg["player"].get("referer_on_play"):
            header["Referer"] = self.siteUrl.rstrip("/") + "/"
        return header

    def _media_result(self, url, parse=0):
        """壳播放结果：六键固定形态。

        parse  —— Integer，0 直连 / 1 交回壳解析
        url    —— 裸字符串
        header —— dict（UA + Referer）
        ua     —— 备用 UA
        playUrl—— 恒为空串（它是「前缀」不是别名）
        jx     —— Integer 0
        刻意不下发 flag：一旦 flag 命中壳配置的「需解析线路」，壳会自己去解析我们
        已经交回的页面地址，反而多绕一层。
        """
        header = self._play_header()
        return {"parse": int(parse or 0), "url": url, "header": header,
                "ua": header.get("User-Agent", ""), "playUrl": "", "jx": 0}

    def _first_id(self, ids):
        """从壳传来的多种 id 形态里取详情 id。

        支持 list/tuple、dict、JSON 串 '["ch4re1yqj"]'、裸串 'ch4re1yqj'、
        逗号分隔串。绝不用 str(ids[0]) 盲取（JSON 串会被切成 '['）。
        """
        try:
            if ids is None:
                return ""
            if isinstance(ids, (list, tuple)):
                return str(ids[0]).strip() if ids else ""
            if isinstance(ids, dict):
                for key in ("id", "vod_id", "vid"):
                    value = ids.get(key)
                    if value:
                        return str(value).strip()
                return ""
            raw = str(ids).strip()
            if not raw:
                return ""
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list) and parsed:
                        return str(parsed[0]).strip()
                    return ""
                except Exception as e:
                    self.log("ids JSON 解析异常：%s" % e, "WARN")
                    return ""
            if raw.startswith("{"):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        for key in ("id", "vod_id", "vid"):
                            value = parsed.get(key)
                            if value:
                                return str(value).strip()
                    return ""
                except Exception as e:
                    self.log("ids JSON 解析异常：%s" % e, "WARN")
                    return ""
            if "," in raw:
                raw = raw.split(",")[0].strip()
            return raw
        except Exception as e:
            self.log("ids 解析异常：%s" % e, "WARN")
            return ""

    def _slug_from(self, value):
        """从 '/play/ch4re1yqj' 或 'ch4re1yqj' 里取 slug。"""
        raw = str(value or "").strip()
        if not raw:
            return ""
        if raw.startswith("http"):
            raw = raw.split("?")[0].rstrip("/")
            raw = raw.split("/")[-1]
        elif "/" in raw:
            raw = raw.rstrip("/").split("/")[-1]
        return raw.strip()

    def _quote(self, text):
        try:
            return _parse.quote(str(text or ""), safe="")
        except Exception:
            return ""

    # ───── HTML 解析：标签扫描 / 列表卡 / 搜索卡 ─────
    def _iter_tags(self, html, tag):
        """引号感知的标签扫描器：返回 [(标签原文, 标签内文), ...]。

        为什么不能用 <a[^>]*>：站点的剧集锚点带 x-effect 属性，其属性值里含
        '=>'（箭头函数），朴素的 [^>]* 会在箭头处截断，把 data-episode / dataid
        丢掉。所以这里按引号状态逐字符找真正的标签结束位。
        """
        out = []
        if not html:
            return out
        needle = "<" + tag
        pos = 0
        while True:
            i = html.find(needle, pos)
            if i < 0:
                break
            j = i + len(needle)
            if j < len(html) and html[j] not in " \t\r\n>/":
                pos = j
                continue
            k = j
            quote = ""
            while k < len(html):
                ch = html[k]
                if quote:
                    if ch == quote:
                        quote = ""
                elif ch in "\"'":
                    quote = ch
                elif ch == ">":
                    break
                k += 1
            if k >= len(html):
                break
            tagtext = html[i:k + 1]
            end = html.find("</" + tag, k)
            inner = html[k + 1:end] if end > 0 else ""
            out.append((tagtext, inner))
            pos = k + 1
        return out

    def _split_blocks(self, html, marker):
        """按固定标记把 HTML 切成块（列表卡 data-vod-id / 搜索卡 group relative）。"""
        blocks = []
        if not html:
            return blocks
        pos = 0
        while True:
            i = html.find(marker, pos)
            if i < 0:
                break
            nxt = html.find(marker, i + len(marker))
            block = html[i:nxt] if nxt > 0 else html[i:]
            blocks.append(block)
            pos = i + len(marker)
        return blocks

    def _card_fields(self, block, search=False):
        """从一块卡片里取字段（全部 fail-soft，缺就留空，绝不编造）。"""
        item = {}
        sel = self.cfg["selectors"]
        try:
            # 详情 id：一律以 a[href="/play/…"] 的 slug 为准
            href = ""
            m = re.search(sel["card_href_re"], block)
            if m:
                href = m.group(1)
            if not href:
                m = re.search(r'data-vod-id="([^"]+)"', block)
                if m:
                    href = self.cfg["endpoints"]["detail"].format(vid=m.group(1))
            if not href:
                return item
            item["vod_id"] = self._slug_from(href)
            # 片名
            m = re.search(sel["card_title_re"], block, re.S)
            if m:
                item["vod_name"] = SiYuanSi.clean_text(m.group(1))
            # 竖版海报：卡内第一张 data-src（第二张是 hover 预览的横版图）
            m = re.search(sel["card_img_re"], block)
            if m:
                item["vod_pic"] = SiYuanSi.fix_pic(m.group(1), self.siteUrl)
            # 角标：全N集 / 更新至N集
            m = re.search(sel["card_badge_re"], block)
            if m:
                item["vod_remarks"] = SiYuanSi.clean_text(m.group(1))
            if search:
                # 搜索页：年份角标 + 简介（搜索卡没有评分）
                m = re.search(sel["search_year_re"], block)
                if m:
                    item["vod_year"] = m.group(1)
                m = re.search(sel["search_desc_re"], block, re.S)
                if m:
                    item["vod_content"] = SiYuanSi.clean_text(m.group(1))
            else:
                # 列表页：hover 块里的评分 / 年份 / 简介
                m = re.search(sel["card_rating_re"], block)
                if m:
                    item["vod_score"] = m.group(1)
                m = re.search(sel["card_year_re"], block)
                if m:
                    item["vod_year"] = m.group(1)
                m = re.search(sel["card_desc_re"], block, re.S)
                if m:
                    item["vod_content"] = SiYuanSi.clean_text(m.group(1))
                m = re.search(sel["card_tag_re"], block)
                if m:
                    item["vod_tag"] = m.group(1)
            if not item.get("vod_name"):
                return {}
        except Exception as e:
            self.log("卡片解析异常：%s" % e, "WARN")
            return {}
        return item

    def _parse_list_cards(self, html):
        """列表页（/filter、/movie 等）卡片解析。"""
        items = []
        seen = set()
        for block in self._split_blocks(html, self.cfg["selectors"]["card_attr"]):
            item = self._card_fields(block, search=False)
            vid = item.get("vod_id")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            items.append(item)
        return items

    def _parse_search_cards(self, html):
        """搜索页卡片解析（搜索卡没有 data-vod-id，靠 class="group relative" 切块）。"""
        items = []
        seen = set()
        for block in self._split_blocks(html, self.cfg["selectors"]["search_card_re"]):
            item = self._card_fields(block, search=True)
            vid = item.get("vod_id")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            items.append(item)
        return items

    # ───── 详情 / 剧集 ─────
    def _parse_episodes(self, html):
        """解析剧集锚点：返回 [{line, no, slug, name, vip}, ...]。

        站点的剧集锚点形如：
          <a href="/play/ch11nhoa3" @click.prevent="…" x-show="showEpisode(1)"
             data-line="1" data-episode="2" dataid="12215" x-effect="…=>…"
             class="episode-link …">…<span x-show="!isEpisodeActive(1, 2)">2</span></a>
        x-effect 的属性值里带 '=>'，必须用引号感知的扫描器（_iter_tags）。
        每集各有自己的 /play/ slug（第 1 集 = 详情页自身 slug）。
        """
        episodes = []
        for tagtext, inner in self._iter_tags(html, "a"):
            if "data-episode=" not in tagtext:
                continue
            m = re.search(r'href="/play/([^"]+)"', tagtext)
            if not m:
                continue
            slug = m.group(1)
            line = ""
            m2 = re.search(r'data-line="(\d+)"', tagtext)
            if m2:
                line = m2.group(1)
            no = 0
            m3 = re.search(r'data-episode="(\d+)"', tagtext)
            if m3:
                no = int(m3.group(1))
            label = SiYuanSi.clean_text(inner)
            name = label
            if not name or name.isdigit():
                name = ("第%s集" % no) if no else label
            episodes.append({"line": line or "1", "no": no, "slug": slug,
                             "name": name, "vip": "vip-icon" in inner or "vip-icon" in tagtext})
        return episodes

    def _detail_meta(self, html):
        """详情页元数据：结构化信息块优先（标签/值成对），keywords 只作兜底。"""
        sel = self.cfg["selectors"]
        meta = {"pairs": {}, "keywords": [], "classify": "", "score": "",
                "update": "", "year": "", "area": "", "genre": "", "actor": "",
                "director": "", "lang": "", "alias": ""}
        try:
            for m in re.finditer(sel["detail_pair_re"], html, re.S):
                key = SiYuanSi.clean_text(m.group(1))
                val = SiYuanSi.clean_text(m.group(2))
                if key:
                    meta["pairs"][key] = val
            m = re.search(sel["meta_keys_re"], html)
            if m:
                meta["keywords"] = [x.strip() for x in SiYuanSi.clean_text(m.group(1)).split(",")
                                    if x.strip()]
            m = re.search(sel["detail_classify_re"], html)
            if m:
                meta["classify"] = m.group(1)
            m = re.search(sel["detail_score_re"], html, re.S)
            if m:
                score = SiYuanSi.clean_text(m.group(1))
                mm = re.search(r"([\d.]+)", score or "")
                if mm:
                    meta["score"] = mm.group(1)
            m = re.search(r"(更新至[^<]{0,16}?集)", html)
            if m:
                meta["update"] = SiYuanSi.clean_text(m.group(1))
            pairs = meta["pairs"]
            if "上映" in pairs:
                mm = re.search(r"(\d{4})", pairs["上映"])
                if mm:
                    meta["year"] = mm.group(1)
            if "地区" in pairs:
                meta["area"] = pairs["地区"].split(" / ")[0].strip()
            if "类型" in pairs:
                meta["genre"] = pairs["类型"].split(" / ")[0].strip()
            if "主演" in pairs:
                meta["actor"] = pairs["主演"]
            if "导演" in pairs:
                meta["director"] = pairs["导演"]
            if "语言" in pairs:
                meta["lang"] = pairs["语言"]
            if "又名" in pairs:
                meta["alias"] = pairs["又名"]
            if not meta["year"] and len(meta["keywords"]) > 2:
                mm = re.search(r"(\d{4})", meta["keywords"][2])
                if mm:
                    meta["year"] = mm.group(1)
            if not meta["area"] and len(meta["keywords"]) > 4:
                meta["area"] = meta["keywords"][4]
        except Exception as e:
            self.log("详情元数据解析异常：%s" % e, "WARN")
        return meta

    def _has_4k_source(self, tag):
        """详情页判定是否 4K 片源：站点 keywords 首字段是它的画质标记（4k）。

        非 4K 片源的 keywords 首字段为空，4K 片源为 '4k'（实测 2026-11-08）。
        取不到就返回 False —— 宁可不挂 4K 线路，也不给非 4K 片源伪造一条。
        """
        try:
            value = str(tag or "").strip().lower()
            return value in [str(x).strip().lower()
                             for x in self.cfg["quality"].get("tag_4k") or []]
        except Exception:
            return False

    def detailContent(self, ids=None):
        """详情页：ids 支持 list / JSON 串 / 裸串三种形态。"""
        try:
            slug = self._slug_from(self._first_id(ids))
            if not slug:
                return {"list": [], "vod": {}}
            url = self._url("detail", vid=slug)
            html = self._get(url, referer=self.siteUrl.rstrip("/") + "/")
            if not html:
                self.log("详情页取不到内容：%s" % url, "WARN")
                return {"list": [], "vod": {}}
            sel = self.cfg["selectors"]
            meta = self._detail_meta(html)
            name = ""
            m = re.search(sel["detail_h1_re"], html, re.S)
            if m:
                name = SiYuanSi.clean_text(m.group(1))
            if not name:
                m = re.search(sel["og_title_re"], html)
                if m:
                    name = SiYuanSi.clean_text(m.group(1)).split(" - ")[0].strip()
            pic = ""
            m = re.search(sel["og_image_re"], html)
            if m:
                pic = SiYuanSi.fix_pic(m.group(1), self.siteUrl)
            desc = ""
            m = re.search(sel["meta_desc_re"], html)
            if m:
                desc = SiYuanSi.clean_text(m.group(1))
            # 分类名：站点权威值（data-classify-id，每部作品只有一个）
            type_name = self.cfg["classify_names"].get(meta.get("classify") or "", "")
            if not type_name:
                type_name = meta.get("genre") or ""
            # 画质/类型标签：keywords 首字段（4k / 院线 / TC）
            tag = ""
            if meta.get("keywords"):
                head = meta["keywords"][0]
                if head in ("4k", "4K", "TC", "HD", "院线"):
                    tag = head
            episodes = self._parse_episodes(html)
            # 线路：站点 lineName（如 alists）是技术名，展示用「线路N」
            froms = []
            urls = []
            groups = []
            for ep in episodes:
                if ep["line"] not in [g[0] for g in groups]:
                    groups.append((ep["line"], []))
                for g in groups:
                    if g[0] == ep["line"]:
                        g[1].append(ep)
                        break
            for idx, (line, eps) in enumerate(groups):
                froms.append("线路%d" % (idx + 1))
                urls.append("#".join(["%s$%s" % (e["name"], e["slug"]) for e in eps]))
                for e in eps:
                    if e.get("vip"):
                        self._vip_ids.add(e["slug"])
            # 4K 片源额外挂一条「4K线路」（同一批剧集，只换播放线路）：
            # 选中它时 playerContent 按 4K 档请求；匿名侧拿不到真 4K 地址会回落
            # 1080 直连，不是伪造 4K。片源是否 4K 由站点 keywords 首字段判定。
            qcfg = self.cfg["quality"]
            if urls and self._has_4k_source(tag):
                froms.append(qcfg["line_4k"])
                urls.append(urls[0])
                self.log("检测到 4K 片源，追加 %s：%s" % (qcfg["line_4k"], name or slug))
            vod = {
                "vod_id": slug,
                "vod_name": name,
                "vod_pic": pic,
                "vod_content": desc,
                "vod_year": meta.get("year", ""),
                "vod_area": meta.get("area", ""),
                "vod_actor": meta.get("actor", ""),
                "vod_director": meta.get("director", ""),
                "vod_lang": meta.get("lang", ""),
                "vod_remarks": meta.get("update") or "",
                "vod_tag": tag,
                "type_name": type_name,
            }
            if meta.get("score"):
                # 详情页评分位部分剧集为空（站点本身没渲染），取不到就不下发该字段
                vod["vod_score"] = meta["score"]
            if urls:
                vod["vod_play_from"] = "$$$".join(froms)
                vod["vod_play_url"] = "$$$".join(urls)
            return {"list": [vod], "vod": vod}
        except Exception as e:
            self.log("detailContent 异常：%s" % e, "ERROR")
            return {"list": [], "vod": {}}

    # ───── 播放 ─────
    def _vip_flag_set(self, vipFlags):
        """把壳传来的 vipFlags 归一成集合（三种形态都要吃下）。

        形态：dict（键为真值）/ JSON 串（数组或对象）/ list（元素可为 str 或 dict）。
        归一后的集合用于真正的分支判断，不是只写日志。
        """
        out = set()
        try:
            if vipFlags is None:
                return out
            items = None
            if isinstance(vipFlags, dict):
                items = []
                for key, value in vipFlags.items():
                    if value:
                        items.append(key)
                        if isinstance(value, str) and value:
                            items.append(value)
            elif isinstance(vipFlags, (list, tuple)):
                items = list(vipFlags)
            else:
                raw = str(vipFlags).strip()
                if not raw:
                    return out
                if raw[0] in "[{":
                    try:
                        parsed = json.loads(raw)
                    except Exception as e:
                        self.log("vipFlags JSON 解析失败：%s" % e, "WARN")
                        return out
                    if isinstance(parsed, dict):
                        return self._vip_flag_set(parsed)
                    if isinstance(parsed, (list, tuple)):
                        items = list(parsed)
                else:
                    items = [x for x in raw.replace(";", ",").split(",") if x.strip()]
            for item in items or []:
                if isinstance(item, dict):
                    for key in ("flag", "id", "name", "vod_id"):
                        value = item.get(key)
                        if value:
                            out.add(str(value).strip())
                elif item:
                    out.add(str(item).strip())
        except Exception as e:
            self.log("vipFlags 归一异常：%s" % e, "WARN")
        return out

    # ───── 播放直链：复现站点自己的签名链（纯标准库，不用浏览器、不伪造直链）─────
    #    站点前端由 /static/wasm/nbmovie_wasm*.js + 其 bg wasm 拼装播放地址：
    #      GET /video/play?p={dataid}&v={slug}&q={清晰度}&s={签名}&t={毫秒}&k={令牌}
    #    本文件复现其中全部参数：
    #      p = 该 slug 自己的 dataid（从播放页剧集锚点的 dataid 属性取；服务端不校验
    #          p 与 v 的配对，但配错会返回别的集的内容，故必须逐集取自己的 dataid）
    #      s = HMAC-SHA256(key=slug, msg="dataid:t:slug") 的前 32 位十六进制
    #      t = 毫秒时间戳，服务端按 ±45 秒左右的窗口校验（实测 ±30s 通过、±60s 拒）
    #          基准取播放页 <meta id="nb-st"> 的服务端时间，避免设备时钟偏差
    #      k = base64(userlink 与站点密钥逐字节异或)；userlink 取自同一次播放页
    #          的 x-data（它每次刷新页面都会变，必须同页现取现用）
    #      q = 清晰度；实测只有 1080 档匿名可用（720/480 返 401「需要VIP会员」）
    #    站点密钥不写死在本文件：运行时从页面公布的 wasm 里按结构抽取，
    #    并用服务端返回码做校验（候选密钥不对时服务端回 401 令牌格式错误）。
    def _bytes_of(self, resp):
        """把壳内 fetch 的返回值统一成 bytes（wasm 是二进制，不能走 _text 的字符解码）。"""
        if resp is None:
            return b""
        if isinstance(resp, (bytes, bytearray)):
            return bytes(resp)
        for name in ("content", "body"):
            value = getattr(resp, name, None)
            if isinstance(value, (bytes, bytearray)):
                return bytes(value)
        return b""

    def _fetch_bytes(self, url, referer=None):
        """取二进制内容（wasm）。壳内 fetch 优先，失败回落标准库。"""
        if not url:
            return b""
        headers = {}
        if referer:
            headers["Referer"] = referer
        try:
            raw = self._bytes_of(self.fetch(url, headers=headers))
            if raw[:4] == b"\x00asm":
                return raw
        except Exception as e:
            self.log("wasm 取流失败（壳内）：%s" % e, "WARN")
        try:
            merged = dict(self.headers)
            merged.update(headers)
            raw = self._bytes_of(_urllib_fetch(url, merged, self.cfg["net"]["timeout"]))
            if raw[:4] == b"\x00asm":
                return raw
        except Exception as e:
            self.log("wasm 取流失败（标准库）：%s" % e, "WARN")
        return b""

    def _wasm_secret(self, html):
        """从播放页发现站点公开的 wasm 地址，运行时抽取密钥候选（不硬编码密钥）。"""
        if not html:
            return []
        url = ""
        m = re.search(r'id="wasm-cfg"[^>]*?data-bg="([^"]+)"', html)
        if not m:
            m = re.search(r'id="wasm-cfg"[^>]*?href="([^"]+)"', html)
        if m:
            url = m.group(1)
        if not url:
            return []
        if not url.startswith("http"):
            url = self.siteUrl.rstrip("/") + url
        cached = _WASM_KEY_CACHE.get(url)
        if cached:
            return cached
        raw = self._fetch_bytes(url, referer=self.siteUrl.rstrip("/") + "/")
        if not raw:
            return []
        candidates = _wasm_key_candidates(raw)
        if candidates:
            _WASM_KEY_CACHE[url] = candidates
        return candidates

    def _play_page_info(self, slug):
        """取播放页，解析四样东西：dataid、userlink、服务端时间、wasm 地址。"""
        started = time.time()
        url = self._url("play", vid=slug)
        html = self._get(url, referer=self.siteUrl.rstrip("/") + "/")
        info = {"html": html, "dataid": "", "userlink": "", "server_ms": 0,
                "started": started}
        if not html:
            return info
        pairs = {}
        for tagtext, inner in self._iter_tags(html, "a"):
            m = re.search(r'href="/play/([^"]+)"', tagtext)
            if not m:
                continue
            d = re.search(r'dataid="(\d+)"', tagtext)
            if not d:
                continue
            if m.group(1) not in pairs:
                pairs[m.group(1)] = d.group(1)
        info["dataid"] = pairs.get(slug, "")
        if not info["dataid"] and len(pairs) == 1:
            info["dataid"] = list(pairs.values())[0]
        m = re.search(r"(?<![A-Za-z0-9_])userlink\s*:\s*'([^']*)'", html)
        if m:
            info["userlink"] = m.group(1)
        m = re.search(r'id="nb-st"\s+content="(\d+)"', html)
        if m:
            info["server_ms"] = int(m.group(1))
        return info

    def _play_sign(self, dataid, timestamp, slug):
        """站点的 s 参数：HMAC-SHA256(key=slug, msg="dataid:t:slug") 的前 32 位十六进制。"""
        try:
            message = ("%s:%s:%s" % (dataid, timestamp, slug)).encode("utf-8")
            return hmac.new(slug.encode("utf-8"), message,
                            hashlib.sha256).hexdigest()[:32]
        except Exception as e:
            self.log("播放签名计算异常：%s" % e, "WARN")
            return ""

    def _play_token(self, userlink, secret):
        """站点的 k 参数：base64(userlink 与站点密钥逐字节异或)。"""
        try:
            if not userlink or userlink == "0":
                return "0"
            key = secret.encode("utf-8")
            if not key:
                return ""
            raw = bytearray()
            for index, byte in enumerate(userlink.encode("utf-8")):
                raw.append(byte ^ key[index % len(key)])
            return base64.b64encode(bytes(raw)).decode("ascii")
        except Exception as e:
            self.log("播放令牌计算异常：%s" % e, "WARN")
            return ""

    def _play_api(self, dataid, slug, timestamp, sign, token, quality=None):
        """调站点播放接口 /video/play，返回 (code, message, data)。

        quality 缺省取 DEFAULT_CONFIG.quality.default_q；4K 线路传 q_4k。
        """
        quality = str(quality or self.cfg["quality"]["default_q"])
        params = {"p": dataid, "v": slug, "q": quality, "s": sign,
                  "t": str(timestamp), "k": token}
        url = self._url("video_play") + "?" + _parse.urlencode(params)
        text = self._get(url, referer=self._url("play", vid=slug))
        if not text:
            return 0, "播放接口无响应", {}
        try:
            obj = json.loads(text)
        except ValueError as e:
            self.log("播放接口返回非 JSON：%s" % e, "WARN")
            return 0, "播放接口返回非 JSON", {}
        if not isinstance(obj, dict):
            return 0, "播放接口返回结构异常", {}
        data = obj.get("data")
        if not isinstance(data, dict):
            data = {}
        try:
            code = int(obj.get("code") or 0)
        except Exception:
            code = 0
        return code, str(obj.get("message") or ""), data

    def _play_pick_url(self, data, prefer_bitrate=0):
        """从 quality_urls 里挑一条可直连的 m3u8，返回 (url, 档位描述)。

        占位 url（4K 档匿名时恒为 "1"）与不可用档位不参与挑选；挑不到返回 ("", "")。
        prefer_bitrate 指定的档位（如 4K 的 2160000）若真的可直连，优先选它；
        否则按「未锁定档位里码率最高」挑，再退到全部档位里码率最高。
        档位描述形如 '4K/2160000'、'1080p/1080'，只用于日志，说明实际拿到了哪一档。
        """
        entries = data.get("quality_urls")
        if not isinstance(entries, list):
            return "", ""
        pool = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if not url.startswith("http"):
                continue
            try:
                bitrate = int(item.get("bitrate") or 0)
            except Exception:
                bitrate = 0
            pool.append({"item": item, "url": url, "bitrate": bitrate})
        if not pool:
            return "", ""

        def _desc(entry):
            title = str(entry["item"].get("title") or "")
            return ("%s/%s" % (title, entry["bitrate"])) if title else str(entry["bitrate"])

        if prefer_bitrate:
            try:
                want = int(prefer_bitrate)
            except Exception:
                want = 0
            for entry in pool:
                if entry["bitrate"] == want and not entry["item"].get("locked"):
                    return entry["url"], _desc(entry)
        try:
            index = int(data.get("current_quality"))
        except Exception:
            index = -1
        if 0 <= index < len(entries):
            item = entries[index]
            if isinstance(item, dict):
                url = str(item.get("url") or "")
                if url.startswith("http") and not item.get("locked"):
                    try:
                        bitrate = int(item.get("bitrate") or 0)
                    except Exception:
                        bitrate = 0
                    title = str(item.get("title") or "")
                    return url, ("%s/%s" % (title, bitrate)) if title else str(bitrate)
        free = [e for e in pool if not e["item"].get("locked")]
        best = max(free or pool, key=lambda e: e["bitrate"])
        return best["url"], _desc(best)

    def _play_direct(self, slug, quality=None, prefer_bitrate=0):
        """复现站点播放链，拿到真实 m3u8 直链；拿不到返回空串（绝不伪造直链）。

        quality      请求的清晰度（缺省 default_q；4K 线路传 q_4k）
        prefer_bitrate  优先选用的档位码率（4K 线路传 bitrate_4k），拿不到就按常规挑
        """
        info = self._play_page_info(slug)
        if not info["html"] or not info["dataid"]:
            return ""
        candidates = self._wasm_secret(info["html"])
        if not candidates:
            return ""
        want_q = str(quality or self.cfg["quality"]["default_q"])
        for secret in candidates[:6]:
            timestamp = int(time.time() * 1000)
            if info["server_ms"]:
                timestamp = info["server_ms"] + int((time.time() - info["started"]) * 1000)
            sign = self._play_sign(info["dataid"], timestamp, slug)
            token = self._play_token(info["userlink"], secret)
            if not sign or not token:
                continue
            code, message, data = self._play_api(info["dataid"], slug,
                                                 timestamp, sign, token, quality=want_q)
            if code == 200:
                url, desc = self._play_pick_url(data, prefer_bitrate=prefer_bitrate)
                if url:
                    self.log("直链命中（请求 q=%s，实取档位 %s）：%s"
                             % (want_q, desc or "?", url))
                    return url
                return ""
            if "令牌" in message or "token" in message.lower():
                continue
            break
        return ""

    def playerContent(self, flag, id, vipFlags=None):
        """播放：优先给源侧直链（复现站点自己的签名链），拿不到再交壳嗅探。

        线路（flag —— 即详情页下发的 vod_play_from 线名）：
          · 普通线路（线路1…）→ 按 quality.default_q 取直链。
          · 「4K线路」→ 按 4K 档（quality.q_4k）请求，并在 quality_urls 里优先挑
            bitrate_4k 那一档。站点实测：4K 档只对已登录会员开放，匿名 Web 侧返回的
            4K 条目 locked/isvip、url 是占位 "1"，拿不到真实地址；这时按
            quality.fallback_q 回落 1080 直连，保证有画面（日志写明实际拿到的档位）。
            要真 4K 需站点会员登录态 + 客户端 HEVC 解码（站点 /page/4kshiplay）。

        vipFlags 真实参与分支：
          · 命中（壳侧 VIP 集合或站点侧 vip-icon 标记的剧集）→ 站点对 VIP 集门禁
            （实测匿名请求返 401「请先登录并开通VIP会员」，无匿名直链），故跳过
            源侧直连，直接交壳（壳侧带会员通道/登录态）。
          · 未命中 → 走源侧直连链：拿到真实 m3u8 就直连（parse=0）；失败再交壳
            （parse=1 + 播放页 URL），保留壳嗅探这条路。
        """
        try:
            raw = "" if id is None else str(id).strip()
            if "$" in raw:
                raw = raw.rsplit("$", 1)[-1].strip()
            slug = self._slug_from(raw)
            if not slug:
                return self._media_result("", parse=1)
            play_url = self._url("play", vid=slug)
            qcfg = self.cfg["quality"]
            flag_s = str(flag or "").strip()
            want_4k = flag_s in (qcfg.get("flag_4k") or []) or flag_s == qcfg.get("line_4k")
            vip_set = self._vip_flag_set(vipFlags)
            is_vip = bool(slug in vip_set or (flag_s and flag_s in vip_set)
                          or slug in self._vip_ids)
            if is_vip:
                self.log("命中 VIP 集合，跳过源侧直连直接交壳：%s" % slug)
                return self._media_result(play_url, parse=1)
            if want_4k:
                direct = self._play_direct(slug, quality=qcfg.get("q_4k"),
                                           prefer_bitrate=qcfg.get("bitrate_4k"))
                if not direct and qcfg.get("fallback_q"):
                    self.log("4K 档未取到真实地址（站点 4K 仅对会员/客户端开放），"
                             "回落 %s：%s" % (qcfg.get("fallback_q"), slug), "WARN")
                    direct = self._play_direct(slug, quality=qcfg.get("fallback_q"))
            else:
                direct = self._play_direct(slug, quality=qcfg.get("default_q"))
            if direct and SiYuanSi.is_media(direct):
                self.log("源侧直链命中：%s" % direct)
                return self._media_result(direct, parse=0)
            self.log("源侧直链未取到，交回壳：%s" % slug)
            return self._media_result(play_url, parse=1)
        except Exception as e:
            self.log("playerContent 异常：%s" % e, "ERROR")
            return self._media_result("", parse=1)

    # ───── 本地代理 ─────
    def _proxy_target(self, param):
        """从四种入参形态里取目标地址：dict / JSON 串 / query 串（可带前导 ?）/ 裸 URL。"""
        try:
            keys = ("url", "ddd", "dddd", "target", "link")
            if isinstance(param, dict):
                for key in keys:
                    value = param.get(key)
                    if value:
                        return str(value).strip()
                return ""
            raw = str(param or "").strip()
            if not raw:
                return ""
            if raw.startswith("{"):
                try:
                    obj = json.loads(raw)
                except Exception as e:
                    self.log("localProxy JSON 解析失败：%s" % e, "WARN")
                    return ""
                if isinstance(obj, dict):
                    for key in keys:
                        value = obj.get(key)
                        if value:
                            return str(value).strip()
                return ""
            if raw.startswith("http"):
                return raw
            # query 串：必须先剥掉前导 '?'，否则 parse_qs 会把 '?' 并进键名
            if raw.startswith("?"):
                raw = raw[1:]
            try:
                qs = _parse.parse_qs(raw)
            except Exception as e:
                self.log("localProxy query 解析失败：%s" % e, "WARN")
                return ""
            for key in keys:
                value = (qs.get(key) or [""])[0]
                if value:
                    return value.strip()
            return ""
        except Exception as e:
            self.log("localProxy 入参解析失败：%s" % e, "WARN")
            return ""

    def _proxy_result(self, status, body, ctype=None):
        """统一的 localProxy 返回值：[码(int), 类型(str), 内容, 头(dict)]。

        第 4 位必须是 dict（chaquo getHeader() 走 asMap()）。
        失败时 body 是空字符串 ""，不是 b''（与《py源写作规范》13.2 一致）。
        """
        try:
            status = int(status or 200)
        except Exception:
            status = 200
        if body is None:
            body = b""
        elif isinstance(body, (bytes, bytearray)):
            body = bytes(body)
        else:
            body = str(body).encode("utf-8", "ignore")
        header = self._play_header()
        if not body:
            return [status, "text/plain", "", header]
        if not ctype:
            ctype = "application/vnd.apple.mpegurl" if b"#EXTM3U" in body[:200] else "video/MP2T"
        return [status, ctype, body, header]

    def localProxy(self, param=""):
        """本地代理：把目标地址带 Referer/UA 取回来，m3u8 顺手洗掉广告。

        入参四种形态都吃：dict / JSON 串 / query 串（带或不带前导 ?）/ 裸 URL。
        """
        try:
            url = self._proxy_target(param)
            if not url:
                return self._proxy_result(404, b"")
            host = ""
            try:
                host = (_parse.urlparse(url).hostname or "").lower()
            except Exception:
                host = ""
            allowed = self.cfg["proxy"]["allowed_hosts"]
            if host and allowed and not any(host == x or host.endswith("." + x) for x in allowed):
                self.log("localProxy 目标不在白名单：%s" % host, "WARN")
                return self._proxy_result(403, b"")
            resp = self.fetch(url, headers=self._play_header())
            status = getattr(resp, "status_code", 200) or 200
            body = getattr(resp, "content", None)
            if body is None:
                body = getattr(resp, "body", b"")
            if isinstance(body, str):
                body = body.encode("utf-8", "ignore")
            body = body or b""
            if b"#EXTM3U" in body[:200]:
                cleaned = SiYuanSi.clean_m3u8(_decode_text(body),
                                              self.cfg["m3u8"]["ad_keywords"],
                                              self.cfg["m3u8"]["ad_line_patterns"])
                body = cleaned.encode("utf-8", "ignore")
            return self._proxy_result(status, body)
        except Exception as e:
            self.log("localProxy 异常：%s" % e, "ERROR")
            return self._proxy_result(500, b"")

    # ───── 首页 ─────
    def _filter_groups(self):
        """把配置里的筛选组转成壳的 Filter 形态（多组，每组一个 key）。

        壳的 filters 是 Map<classId, List<Filter>>，一个 Filter 是一组筛选项；
        本站的筛选项分属不同 query 参数（types/years/areas/tags/sort_by），
        所以每个 class 下发多组 Filter，key 用站点参数名，name 用中文名。
        首项是「全部」（空值），壳点它等于不筛选。
        """
        groups = []
        for name, spec in self.cfg["filters"].items():
            if not isinstance(spec, dict):
                continue
            values = [{"n": "全部", "v": "", "name": "全部", "value": ""}]
            for item in spec.get("values") or []:
                if not isinstance(item, dict):
                    continue
                values.append({"n": item.get("n"), "v": item.get("v"),
                               "name": item.get("n"), "value": item.get("v")})
            groups.append({"key": spec.get("key"), "name": name,
                           "init": "", "value": values})
        return groups

    def homeContent(self, filter=False):
        """首页：class 条目只发 type_id / type_name，筛选项放顶层 filters（dict 形态）。"""
        try:
            classes = []
            for meta in self.cfg["classes"]:
                classes.append({"type_id": str(meta["type_id"]),
                                "type_name": str(meta["type_name"])})
            groups = self._filter_groups()
            flt = {}
            for meta in classes:
                flt[meta["type_id"]] = [dict(g) for g in groups]
            return {"class": classes, "filters": flt}
        except Exception as e:
            self.log("homeContent 异常：%s" % e, "ERROR")
            return {"class": []}

    def homeVideoContent(self):
        """首页推荐：解析首页卡片，按 slug 去重后取前 N 条。"""
        try:
            html = self._get(self._url("home"), referer=self.siteUrl.rstrip("/") + "/")
            if not html:
                return {"list": []}
            items = self._parse_list_cards(html)
            seen = set()
            out = []
            for item in items:
                vid = item.get("vod_id")
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                out.append(self._vod_item(item))
                if len(out) >= 40:
                    break
            return {"list": out}
        except Exception as e:
            self.log("homeVideoContent 异常：%s" % e, "ERROR")
            return {"list": []}

    def _vod_item(self, item):
        """内部卡片 → 壳的列表项（字段名取自 FongMi Vod bean）。"""
        out = {
            "vod_id": item.get("vod_id", ""),
            "vod_name": item.get("vod_name", ""),
            "vod_pic": item.get("vod_pic", ""),
            "vod_remarks": item.get("vod_remarks", ""),
        }
        for key in ("vod_year", "vod_content", "vod_area", "vod_actor",
                    "vod_director", "vod_tag", "vod_score", "type_name"):
            if item.get(key):
                out[key] = item[key]
        return out

    # ───── 分类列表 ─────
    def _classify_of(self, cate_id):
        table = self.cfg["class_classify"]
        if cate_id in table:
            return table[cate_id]
        return cate_id

    def _extend_map(self, extend):
        """把壳传来的 extend 归一成 dict（dict / JSON 串 / 裸值）。"""
        out = {}
        try:
            if isinstance(extend, dict):
                out.update(extend)
            elif isinstance(extend, (list, tuple)):
                for item in extend:
                    if isinstance(item, dict):
                        out.update(item)
            elif isinstance(extend, str):
                raw = extend.strip()
                if not raw:
                    return out
                if raw[0] in "[{":
                    try:
                        parsed = json.loads(raw)
                    except Exception as e:
                        self.log("extend JSON 解析失败：%s" % e, "WARN")
                        return out
                    if isinstance(parsed, dict):
                        out.update(parsed)
                    elif isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict):
                                out.update(item)
                else:
                    for part in raw.split(","):
                        part = part.strip()
                        if "=" in part:
                            key, _, value = part.partition("=")
                            out[key.strip()] = value.strip()
                        elif part:
                            out.setdefault("value", part)
        except Exception as e:
            self.log("extend 归一异常：%s" % e, "WARN")
        return out

    def _extend_value(self, ext, aliases):
        """按多个别名取筛选值（不同壳传的名字不一样）。"""
        for name in aliases:
            if name in ext:
                value = ext.get(name)
                if isinstance(value, (list, tuple)):
                    value = value[0] if value else ""
                value = str(value or "").strip()
                if value and value not in ("0", "全部"):
                    return value
        return ""

    def categoryContent(self, tid, pg="1", filter=False, extend=None):
        """分类列表：/filter?classify=&types=&years=&areas=&tags=&sort_by=&page=

        真实页数来自页面上的「共 N 页，共 M 个结果」；该文本在结果 ≤ 30 时不出现，
        这时回落 1（站点此时确实只有一页）。
        """
        try:
            cate_id = str(tid or "")
            try:
                page = int(pg or 1)
            except Exception:
                page = 1
            if page < 1:
                page = 1
            ext = self._extend_map(extend)
            params = []
            classify = self._classify_of(cate_id)
            if classify:
                params.append(("classify", classify))
            for name, spec in self.cfg["filters"].items():
                key = spec.get("key")
                aliases = [key, name]
                if key == "types":
                    aliases += ["类型", "type", "tid"]
                elif key == "years":
                    aliases += ["年份", "year"]
                elif key == "areas":
                    aliases += ["地区", "area", "region"]
                elif key == "tags":
                    aliases += ["标签", "tag"]
                elif key == "sort_by":
                    aliases += ["排序", "sort"]
                value = self._extend_value(ext, aliases)
                if not value:
                    continue
                params.append((key, value))
                if key == "sort_by":
                    # 站点的排序必须带 order=desc（实测 chips 就是这个形态）
                    params.append(("order", "desc"))
            params.append(("page", str(page)))
            query = _parse.urlencode(params)
            url = (self.siteUrl.rstrip("/") + "/" + self.cfg["endpoints"]["list"].lstrip("/")
                   + "?" + query)
            html = self._get(url, referer=self.siteUrl.rstrip("/") + "/" +
                             self.cfg["endpoints"]["list"].lstrip("/"))
            if not html:
                return {"list": [], "page": page, "pagecount": 1, "limit": 0, "total": 0}
            items = self._parse_list_cards(html)
            pages, total = self._page_total(html)
            if not pages:
                pages = self._page_max(html)
            if not pages:
                pages = 1
            if not total:
                total = len(items)
            return {"list": [self._vod_item(i) for i in items],
                    "page": page, "pagecount": int(pages),
                    "limit": len(items), "total": int(total)}
        except Exception as e:
            self.log("categoryContent 异常：%s" % e, "ERROR")
            return {"list": [], "page": 1, "pagecount": 1, "limit": 0, "total": 0}

    # ───── 搜索 ─────
    def _search_api_meta(self, kw):
        """用 /api/search?q= 的 JSON 补元数据（按标题匹配）。

        该接口返回的是数字 id，/play/{数字} 一律 400，所以它只用来补评分/简介，
        不作列表来源；取不到就静默跳过。
        """
        try:
            data = self._get_json("search_api", kw=self._quote(kw))
            if not data:
                return {}
            items = data.get("list") or data.get("data") or []
            if not isinstance(items, list):
                return {}
            out = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                title = SiYuanSi.clean_text(item.get("title") or item.get("name"))
                if not title:
                    continue
                out[title] = item
            return out
        except Exception as e:
            self.log("搜索 JSON 补全失败（忽略）：%s" % e, "WARN")
            return {}

    def searchContent(self, key, quick=False, pg="1"):
        """搜索：主用 HTML /search?q=（能直接拿到 /play/ 详情 id）。

        站点搜索页忽略 ?page=（实测翻页返回同一集合），所以 pagecount 恒为 1，
        总数取页面上的「找到 N 个结果」。
        """
        try:
            kw = str(key or "").strip()
            if not kw:
                return {"list": [], "page": 1, "pagecount": 1, "limit": 0, "total": 0}
            url = self._url("search", kw=self._quote(kw))
            html = self._get(url, referer=self.siteUrl.rstrip("/") + "/")
            if not html:
                return {"list": [], "page": 1, "pagecount": 1, "limit": 0, "total": 0}
            items = self._parse_search_cards(html)
            total = 0
            m = re.search(self.cfg["selectors"]["search_total_re"], html)
            if m:
                try:
                    total = int(m.group(1))
                except Exception:
                    total = 0
            if not total:
                total = len(items)
            # JSON 补全：给搜索卡补评分/年份/简介（缺了才补）
            extra = self._search_api_meta(kw) if items else {}
            out = []
            for item in items:
                name = item.get("vod_name", "")
                meta = extra.get(name)
                if isinstance(meta, dict):
                    if not item.get("vod_score") and meta.get("rating"):
                        item["vod_score"] = str(meta.get("rating"))
                    if not item.get("vod_year") and meta.get("year"):
                        item["vod_year"] = str(meta.get("year"))
                    if not item.get("vod_content") and meta.get("description"):
                        item["vod_content"] = SiYuanSi.clean_text(meta.get("description"))
                out.append(self._vod_item(item))
            return {"list": out, "page": 1, "pagecount": 1,
                    "limit": len(out), "total": int(total)}
        except Exception as e:
            self.log("searchContent 异常：%s" % e, "ERROR")
            return {"list": [], "page": 1, "pagecount": 1, "limit": 0, "total": 0}

    def searchContentPage(self, key, quick=False, pg="1"):
        """Pyramid 系的分页搜索入口，站点搜索不分页，直接委托 searchContent。"""
        return self.searchContent(key, quick, pg)


# ── 壳兼容性兜底：若壳的基类还声明了我们没实现的抽象方法，补一个最小可用实现，
#    避免「Can't instantiate abstract class」导致整个源加载失败；不覆盖已有实现。
def _patch_abstract_gaps(cls):
    try:
        missing = sorted(getattr(cls, "__abstractmethods__", frozenset()) or [])
    except Exception as e:
        print("[4k影视][WARN] 抽象方法检查失败：%s" % e)
        return
    for name in missing:
        def _stub(self, *args, _name=name, **kwargs):
            try:
                self.log("壳抽象方法 %s 未实现，返回空结果" % _name, "WARN")
            except Exception:
                pass
            if _name in ("homeContent", "homeVideoContent", "categoryContent",
                         "detailContent", "searchContent", "playerContent",
                         "liveContent"):
                return {"list": []}
            if _name == "isVideoFormat":
                return False
            if _name == "manualVideoCheck":
                return False
            return None
        _stub.__name__ = name
        setattr(cls, name, _stub)
    if missing:
        try:
            cls.__abstractmethods__ = frozenset(
                x for x in cls.__abstractmethods__ if x not in missing)
        except Exception as e:
            print("[4k影视][WARN] 抽象方法清理失败：%s" % e)
        print("[4k影视][WARN] 已为未实现的壳抽象方法补最小实现：%s" % "、".join(missing))


_patch_abstract_gaps(Spider)


if __name__ == "__main__":
    spider = Spider()
    spider.init("")
    print("=== getName ===")
    print(spider.getName())
    print("=== homeContent ===")
    home = spider.homeContent()
    print(json.dumps(home, ensure_ascii=False, indent=2)[:1200])
    print("=== categoryContent('1', '1') ===")
    cate = spider.categoryContent("1", "1", False, {})
    print(json.dumps(cate, ensure_ascii=False, indent=2)[:1200])
    print("=== searchContent ===")
    search = spider.searchContent("遮天")
    print(json.dumps(search, ensure_ascii=False, indent=2)[:1200])
    print("=== detailContent ===")
    if cate.get("list"):
        detail = spider.detailContent(cate["list"][0]["vod_id"])
        print(json.dumps(detail, ensure_ascii=False, indent=2)[:1500])
        print("=== playerContent ===")
        print(json.dumps(spider.playerContent("线路1", cate["list"][0]["vod_id"], []),
                         ensure_ascii=False, indent=2)[:600])
    print("=== playerContent 直链分支断言 ===")
    # 非 VIP：应 parse=0 给真 m3u8；VIP（壳侧 vipFlags）：应 parse=1 交回壳
    probe = spider.playerContent("线路1", "ch4rfawwq", [])
    print("非 VIP: parse=%s url=%s" % (probe.get("parse"), probe.get("url")))
    assert set(probe.keys()) == {"parse", "url", "header", "ua", "playUrl", "jx"}, \
        "playerContent 六键不齐"
    assert probe.get("playUrl") == "" and probe.get("jx") == 0, "playUrl/jx 形态不对"
    assert "flag" not in probe, "不该下发 flag"
    if probe.get("parse") == 0:
        assert str(probe.get("url", "")).startswith("http"), "直链形态不对"
        print("直链分支: OK（parse=0 + 真 m3u8）")
    else:
        print("直链分支: 未取到直链，已回落交壳（parse=1）")
    vip = spider.playerContent("线路1", "ch4rfawwq", ["ch4rfawwq"])
    assert vip.get("parse") == 1, "VIP 分支应 parse=1"
    assert str(vip.get("url", "")).endswith("/play/ch4rfawwq"), "VIP 分支 url 应是播放页"
    print("VIP 分支: OK（parse=1 + 播放页 URL）")
    print("=== 4K 线路 ===")
    fourk = spider.categoryContent("0", "1", False, {"tags": "1"})
    fourk_items = fourk.get("list") or []
    print("4K 标签条目：%d" % len(fourk_items))
    if fourk_items:
        fourk_id = fourk_items[0]["vod_id"]
        fourk_detail = spider.detailContent(fourk_id)
        fourk_from = (fourk_detail.get("vod") or {}).get("vod_play_from", "")
        print("4K 片源线路：%s" % fourk_from)
        assert "4K线路" in fourk_from, "4K 片源应挂上 4K 线路"
        fourk_play = spider.playerContent("4K线路", fourk_id, [])
        assert set(fourk_play.keys()) == {"parse", "url", "header", "ua", "playUrl", "jx"}, \
            "4K 线路 playerContent 六键不齐"
        print("4K 线路播放：parse=%s url=%s"
              % (fourk_play.get("parse"), str(fourk_play.get("url"))[:72]))
        plain_id = ""
        for item in (cate.get("list") or []):
            if item.get("vod_tag") != "4k":
                plain_id = item["vod_id"]
                break
        if plain_id:
            plain_from = (spider.detailContent(plain_id).get("vod") or {}).get("vod_play_from", "")
            print("非 4K 片源线路：%s" % plain_from)
            assert "4K线路" not in plain_from, "非 4K 片源不该挂 4K 线路"
            print("非 4K 片源不挂 4K 线路: OK")
    print("=== localProxy 四形态 ===")
    print(spider.localProxy({"url": "https://www.4kvms.org/"})[:2])
    print(spider.localProxy("?url=https://www.4kvms.org/")[:2])
    print(spider.localProxy("url=https://www.4kvms.org/")[:2])
    print(spider.localProxy("https://www.4kvms.org/")[:2])
