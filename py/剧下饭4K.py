# -*- coding: utf-8 -*-
# =============================================================
# 剧下饭 TVBox Python 爬虫 - webhomeTV 适配版 (类式规范)
# 站点: http://manian.juxiafan.com/  (内置 8 个备用域名自动轮换)
#
# 本文件核心目标 webhomeTV 播放器 (与咕噜咕噜可搜索版同一种加载方式):
#   1) searchContent 签名改为 (self, key, quick, pg="1") 三参数,
#      否则 webhomeTV 调用时 TypeError 导致搜索彻底失败;
#   2) 所有类方法返回 dict, 不返回 json 字符串(与 webhomeTV 一致);
#   3) class Spider 尝试继承 base.spider.Spider, 失败时回退 object;
#   4) 补齐 getName / homeVideoContent / searchContentPage / localProxy / liveContent。
# 同时保留模块级函数 (函数式规范), 供部分函数式播放器使用。
#
# 签名: base64(AES-256-ECB/PKCS7(TreeMap 排序 concat)) -> datasign
#   - form 请求: concat 用 URL 编码后的值 (key=encodedValue&...)
#   - json 请求: concat 用原始值     (key=rawValue&...)
#   - 末尾拼接 timestamp (秒级); datasign 追加到请求体末尾
#
# 无第三方依赖: 内置纯 Python AES-256-ECB; 装有 pycryptodome/cryptography
# 时自动优先使用(更快), 输出完全一致。
#
# v4 修复记录 (2026-08):
#   1) 角标兜底: 列表/搜索接口 remarks 为空 -> 拉详情, 全线路逐集解析集数
#      (兼容 "第N集"/"第N话"/纯数字/"01 4K" 等形态, 排除彩蛋/花絮/导演专访名)
#      取最大值生成角标: 新剧/年份缺失 -> "更新至第X集", 老剧(year<=2024)
#      -> "全X集"; 服务端把角标错标成"更新至第1/3/4/6集"(实测实际已更
#      20-48 集) 时, 只要详情解析出的真实集数更大就自动纠偏(列表与详情页
#      均生效) -> 解决"封面显示成1集/0集"及详情页角标不准;
#   2) 缺封面兜底: videoPic 为空 -> 同名搜索借用可用封面 -> 解决"部分视频
#      没有封面图片";
#   3) 坏封面替换: 豆瓣(img*.doubanio.com 403)等必失败域名 -> 同名搜索替换
#      -> 解决"封面加载不全";
#   4) 保留直播分类(22023)+analysisUrl 直播/加密码解析;
#   5) 线路死码过滤: 占位符/文件列表为空/无 parseUrl 的内部码跳过, 播放失败
#      自动切下一条线路; 列表去重 + 服务端翻页回显校验 + pageSize=40 保底。
# =============================================================
import json
import re
import time
from base64 import b64encode
from urllib.request import Request, urlopen
from urllib.parse import quote_plus, unquote
try:
    from concurrent.futures import ThreadPoolExecutor as _TPE
except Exception:
    _TPE = None

try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object

BASE_URLS = [
    "http://manian.juxiafan.com",
    "http://195.225.24.128:6213",
    "http://jugaoqing.com",
    "http://jumianfei.com",
    "http://juyongjiu.com",
    "http://kuailezhuiju2.com",
    "http://zhuiju666.com",
    "http://194.147.100.155:7744",
]
AES_KEY = b"kZ6fT8oF6oM8eX6lF7eH2rJ3pW7gW0kC"
UA = "okhttp/4.12.0"

LIVE_TYPE_ID = 22023                 # 隐藏直播分类(服务端不下发, 手动补进分类栏)

# 服务端返回的无效占位 playerCode (测到有 "文件列表为空")
_PLACEHOLDER_PCS = ("文件列表为空", "暂无", "无", "无播放地址", "播放地址为空")

# 已确认必失败的封面域: 豆瓣防盗链 403、bwcgee 403, 命中即走同名搜索替换
_BAD_PIC_HOSTS = ("doubanio.com", "bwcgee.cn")

# 角标兜底缓存: vid -> remarks, 避免翻页时对同一部剧反复拉详情
_REMARKS_CACHE = {}

# ======================= AES-256-ECB =======================

def _build_sbox():
    sbox = [0] * 256
    p = q = 1
    while True:
        p = p ^ ((p << 1) ^ (0x1B if p & 0x80 else 0)) & 0xFF
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q ^= 0x09 if (q & 0x80) else 0
        q &= 0xFF
        xformed = q ^ ((q << 1) | (q >> 7)) & 0xFF
        xformed = (xformed ^ ((q << 2) | (q >> 6))) & 0xFF
        xformed = (xformed ^ ((q << 3) | (q >> 5))) & 0xFF
        xformed = (xformed ^ ((q << 4) | (q >> 4))) & 0xFF
        sbox[p] = xformed ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox

_SBOX = _build_sbox()
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36, 0x6C, 0xD8, 0xAB, 0x4D]

def _xtime(a):
    return ((a << 1) ^ (0x1B if a & 0x80 else 0)) & 0xFF

_COL2 = [_xtime(i) for i in range(256)]
_COL3 = [_xtime(i) ^ i for i in range(256)]

def _expand_key(key):
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        temp = list(w[i - 1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= _RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            temp = [_SBOX[b] for b in temp]
        w.append([w[i - nk][j] ^ temp[j] for j in range(4)])
    return w, nr

def _encrypt_block(block, w, nr):
    def _rk(r):
        return [x for word in w[r * 4:(r * 4) + 4] for x in word]
    s = list(block)
    rk0 = _rk(0)
    for j in range(16):
        s[j] ^= rk0[j]
    for r in range(1, nr):
        s = [_SBOX[b] for b in s]
        s = [s[0], s[5], s[10], s[15],
             s[4], s[9], s[14], s[3],
             s[8], s[13], s[2], s[7],
             s[12], s[1], s[6], s[11]]
        t = [0] * 16
        for c in range(4):
            i = c * 4
            a0, a1, a2, a3 = s[i], s[i + 1], s[i + 2], s[i + 3]
            t[i] = _COL2[a0] ^ _COL3[a1] ^ a2 ^ a3
            t[i + 1] = a0 ^ _COL2[a1] ^ _COL3[a2] ^ a3
            t[i + 2] = a0 ^ a1 ^ _COL2[a2] ^ _COL3[a3]
            t[i + 3] = _COL3[a0] ^ a1 ^ a2 ^ _COL2[a3]
        s = t
        rk = _rk(r)
        s = [s[j] ^ rk[j] for j in range(16)]
    s = [_SBOX[b] for b in s]
    s = [s[0], s[5], s[10], s[15],
         s[4], s[9], s[14], s[3],
         s[8], s[13], s[2], s[7],
         s[12], s[1], s[6], s[11]]
    rk = _rk(nr)
    s = [s[j] ^ rk[j] for j in range(16)]
    return bytes(s)

def _aes256_ecb_encrypt(plain, key):
    w, nr = _expand_key(key)
    out = bytearray()
    for i in range(0, len(plain), 16):
        out += _encrypt_block(bytes(plain[i:i + 16]), w, nr)
    return bytes(out)

def _aes_encrypt(plaintext, key=AES_KEY):
    """PKCS7 填充 + AES-256-ECB -> base64 (多后端, 输出一致)"""
    data = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
    pad = 16 - len(data) % 16
    data = data + bytes([pad]) * pad
    try:
        from Crypto.Cipher import AES
        return b64encode(AES.new(key, AES.MODE_ECB).encrypt(data)).decode()
    except Exception:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher as _C
            from cryptography.hazmat.primitives.ciphers.algorithms import AES as _AES
            from cryptography.hazmat.primitives.ciphers.modes import ECB as _ECB
            from cryptography.hazmat.backends import default_backend as _B
            enc = _C(_AES(key), _ECB(), backend=_B()).encryptor()
            return b64encode(enc.update(data) + enc.finalize()).decode()
        except Exception:
            return b64encode(_aes256_ecb_encrypt(data, key)).decode()

# ======================= HTTP / 签名 =======================

def _http(method, url, body=None, content_type=None, timeout=12):
    headers = {"User-Agent": UA}
    data = None
    if body is not None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        headers["Content-Length"] = str(len(data))
    if content_type:
        headers["Content-Type"] = content_type
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")

def _sign(concat):
    return _aes_encrypt(concat)

def _fix_host(host):
    if host is None or (isinstance(host, str) and host.strip() == ""):
        host = BASE_URLS[0]
    return str(host).rstrip("/")

def _post(host, path, body=None, content_type=None):
    urls = []
    h = _fix_host(host)
    if h not in urls:
        urls.append(h)
    for b in BASE_URLS:
        if b not in urls:
            urls.append(b)
    last = "{}"
    for u in urls:
        try:
            raw = _http("POST", u + path, body, content_type)
        except Exception:
            continue
        last = raw
        # 只接受业务成功的响应(code=200/0 或带 data), 否则继续换域名:
        # 备用域名可能返回 {"code":300,"msg":"签名错误"} 之类, 不能误判成功。
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and (obj.get("code") in (200, 0) or obj.get("data") is not None):
                return raw
        except Exception:
            pass
    return last

def _get(url, timeout=12):
    try:
        return _http("GET", url, timeout=timeout)
    except Exception:
        return "{}"

def _post_form(host, path, params):
    ts = str(int(time.time()))
    params["timestamp"] = ts
    items = sorted(params.items())
    concat = "&".join(k + "=" + quote_plus(str(v)) for k, v in items)
    ds = _sign(concat)
    form = "&".join(k + "=" + quote_plus(str(v)) for k, v in items)
    form += "&datasign=" + quote_plus(ds)
    return _post(host, path, form, "application/x-www-form-urlencoded")

def _post_json(host, path, params):
    params["timestamp"] = str(int(time.time()))
    items = sorted(params.items())
    concat = "&".join(k + "=" + str(v) for k, v in items)
    ds = _sign(concat)
    obj = dict(items)
    obj["datasign"] = ds
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return _post(host, path, body, "application/json;charset=UTF-8")

# ======================= 核心业务 (返回 dict) =======================

def _home(host):
    resp = _post(host, "/api/v1/video/classifies", None, None)
    try:
        data = json.loads(resp).get("data") or []
    except Exception:
        data = []
    cls = [{"type_id": str(c.get("id")), "type_name": c.get("name") or ""}
           for c in data if c.get("id") and c.get("name")]
    # 按 type_id 升序: 电视剧(22016) 电影(22017) 动漫(22018) 综艺(22019)
    # 短剧(22020) 少儿(22021) 纪录片(22022) AI漫剧(22024), 与 App 首页顺序一致
    cls.sort(key=lambda x: int(x["type_id"]) if str(x["type_id"]).isdigit() else 10 ** 9)
    # 服务端不下发隐藏直播分类(22023), 手动追加到分类栏末尾
    if str(LIVE_TYPE_ID) not in [str(c.get("type_id")) for c in cls]:
        cls.append({"type_id": str(LIVE_TYPE_ID), "type_name": "直播"})
    return {"class": cls, "filters": {}}

def _build_list(resp, page=1, id_desc=False):
    """解析列表响应 -> TVBox 列表 dict。
    - 按 vod_id 去重 (服务端偶发重复/多接口合并时防重复条目);
    - 服务端翻页失效检测: 请求 pg>1 但服务端回显 data.page=1(实测本接口
      page=2/3 均返回同一批数据), 说明无法真正翻页, 后续页直接返回空,
      避免影视仓翻页时每页都是同样的数据 -> "重复视频数据"。
    """
    try:
        data = json.loads(resp).get("data") or {}
    except Exception:
        data = {}
    try:
        pg = int(page) or 1
    except (ValueError, TypeError):
        pg = 1
    if pg < 1:
        pg = 1
    # 翻页失效检测: 服务端回显的 data.page != 请求页
    try:
        resp_page = int(data.get("page") or pg)
    except (ValueError, TypeError):
        resp_page = pg
    if pg > 1 and resp_page != pg:
        return {"page": pg, "pagecount": 1, "limit": 20, "total": 0, "list": []}
    lst = []
    seen_ids = set()
    for v in data.get("list") or []:
        if not v.get("id"):
            continue
        vid = str(v.get("id"))
        if vid in seen_ids:          # 去重: 同一响应内出现重复 id 时只保留第一个
            continue
        seen_ids.add(vid)
        lst.append({
            "vod_id": vid,
            "vod_name": v.get("name") or "",
            "vod_pic": v.get("videoPic") or "",
            "vod_remarks": v.get("remarks") or "",
        })
    # 本地按 id 降序: 搜索时 id 大=收录晚=越新, 最新的排在头部
    if id_desc and lst:
        try:
            lst.sort(key=lambda v: int(v.get("vod_id") or 0), reverse=True)
        except Exception:
            pass
    try:
        pagecount = int(data.get("totalPage") or 1)
    except (ValueError, TypeError):
        pagecount = 1
    if pagecount < pg:
        pagecount = pg
    return {
        "page": pg,
        "pagecount": pagecount,
        "limit": data.get("limit") or 20,
        "total": data.get("totalCount") or 0,
        "list": lst,
    }

def _category(host, tid, pg):
    page = 1
    try:
        page = int(pg or 1)
    except Exception:
        pass
    try:
        type_id = int(tid)
    except Exception:
        type_id = 0
    # ---- 直播分类 22023: 服务端不下发, 走 liveVideo 接口返回直播分组 ----
    if type_id == LIVE_TYPE_ID:
        lst = []
        try:
            r = _get(_fix_host(host) + "/api/v1/video/liveVideo")
            data = (json.loads(r).get("data") or {})
            for v in data.get("list") or []:
                if not v.get("id"):
                    continue
                lst.append({
                    "vod_id": str(v.get("id")),
                    "vod_name": v.get("name") or "",
                    "vod_pic": v.get("videoPic") or "",
                    "vod_remarks": v.get("remarks") or ("直播" if v.get("typeId") else ""),
                })
        except Exception:
            pass
        return {"page": 1, "pagecount": 1, "limit": len(lst), "total": len(lst), "list": lst}
    # 默认走 /video/index(与前面版本一致, 保留服务端原始顺序)。
    # 注意: 服务端忽略 page 参数, 必须用 pageNum 才能真正翻页(否则滑到底内容不变/跳动)。
    resp = _post_json(host, "/api/v1/video/index", {"pageNum": page, "pageSize": 40, "typeId": type_id})
    res = _build_list(resp, page, False)
    # 服务端把部分分类(如电视剧22016)降级为只返回2条(limit=2),
    # 此时自动改用 /video/search 空关键词+typeId 兜底, 拿完整列表(40条/页, 最新在前)。
    if len(res.get("list") or []) < 10:
        resp2 = _post_json(host, "/api/v1/video/search", {"keyword": "", "typeId": type_id, "pageNum": page, "pageSize": 40})
        res = _build_list(resp2, page, True)
    # 列表增强: 连载型分类(影视剧类)补角标+封面, 其余分类只补封面
    if type_id and type_id != 22017 and type_id != 22022:
        res["list"] = _enhance_list(host, res.get("list") or [], with_rm=True, with_pic=True)
    else:
        res["list"] = _enhance_list(host, res.get("list") or [], with_rm=False, with_pic=True)
    return res

def _search(host, key, pg="1"):
    key = (key or "").strip().strip('"').strip("'")
    if not key:
        return {"page": 1, "pagecount": 0, "limit": 20, "total": 0, "list": []}
    # 兼容播放器传入 URL 编码关键词 (如 %E6%96%97%E7%BD%97...)
    # 服务端 % 会当作通配符, 编码形态会搜出大量无关结果, 必须先解码回原文
    if "%" in key:
        try:
            dec = unquote(key)
            if dec and dec != key:
                key = dec.strip()
        except Exception:
            pass
    # 兼容 \uXXXX 转义形态的关键词 (如备份 \u6597\u7f57...)
    if key and "\\u" in key and all(ord(ch) < 128 for ch in key):
        try:
            dec = key.encode("ascii").decode("unicode_escape")
            if dec and dec != key:
                key = dec
        except Exception:
            pass
    try:
        page = int(pg or 1)
    except (ValueError, TypeError):
        page = 1
    if page < 1:
        page = 1
    # 翻页同样必须用 pageNum(+pageSize 保险), page 会被忽略只返回第一页
    resp = _post_json(host, "/api/v1/video/search", {"keyword": key, "pageNum": page, "pageSize": 40})
    res = _build_list(resp, page, True)
    # 搜索结果同样补角标+封面 (搜索剧时 remarks 常为空, 与分类页保持一致)
    res["list"] = _enhance_list(host, res.get("list") or [], with_rm=True, with_pic=True)
    return res


# ---------- 角标 / 封面兜底 ----------

def _pic_bad(url):
    """封面是否"缺失或必失败": 空串 / 非 http / 豆瓣等已确认 403 的域名"""
    if not url or not str(url).strip():
        return True
    u = str(url)
    if not (u.startswith("http://") or u.startswith("https://")):
        return True
    try:
        host = u.split("://", 1)[1].split("/", 1)[0].lower()
    except Exception:
        host = ""
    for bad in _BAD_PIC_HOSTS:
        if bad in host:
            return True
    return False


def _search_cover(host, name):
    """同名搜索借一个'可用'封面: 取搜索结果里第一个非坏图片 (同剧其他条目)。
    注意: 内部直接用原始搜索请求 + _build_list, 再走 _enhance_list(否则与
    _enhance_list 相互递归搜索, 死循环)。"""
    if not (name or "").strip():
        return ""
    try:
        # 只搜第一页, 找任一非坏封面即可 (不同条目图片通常是同剧海报)
        resp = _post_json(host, "/api/v1/video/search", {"keyword": str(name).strip(), "pageNum": 1, "pageSize": 12})
        lst = _build_list(resp, 1, True).get("list") or []
        for v in lst:
            p = v.get("vod_pic") or ""
            if not _pic_bad(p):
                return p
    except Exception:
        pass
    return ""


def _gen_remarks(host, vid, detail=None):
    """列表 remarks 为空或为可疑低值时, 用详情数据生成/纠偏角标:
    新剧(2025+ / 年份缺失) → "更新至第X集"; 老剧(年份明确 <=2024, 早已完结)
    → "全X集"。支持传入已拉取的 detail 数据, 避免重复请求详情。
    关键: 服务端 list/详情 remarks 经常错标"更新至第1集/第01集"(实测 652241
    实际有多条完整线路), 因此只要详情解析出的集数 best 更大, 一律用 best 纠偏;
    详情 remarks 的"已完结/全N集/HD/正片"等其它形态原样保留。"""
    key = str(vid)
    if key in _REMARKS_CACHE:
        return _REMARKS_CACHE[key]
    out = ""
    try:
        d = detail if detail else _fetch_detail(host, vid)
        if not d:
            out = ""
        else:
            y = 0
            try:
                y = int(d.get("year") or 0)
            except (ValueError, TypeError):
                y = 0
            old = (y > 0 and y <= 2024)   # 老剧早已完结 -> 标"全N集"
            # 全线路全量解析合法集数, 取最大值; 同时记最大线路的条数做兜底。
            # 注意: 线路末集常混入花絮/彩蛋/导演专访名(如 "彩蛋6"、
            # "《入戏》X导演陈畅: 年代爱情剧的尺度"), 不能只取"最大线路
            # 的末集", 必须逐集解析 "第N集"/"第N话" 或前导数字+合法后缀。
            best = 0
            maxline = 0
            for src in d.get("playerSource") or []:
                eps = src.get("episodes") or []
                if len(eps) > maxline:
                    maxline = len(eps)
                for ep in eps:
                    nm = (ep.get("episodeName") or "").strip()
                    m = re.search(r"第\s*(\d+)\s*[集话]", nm)
                    if m:
                        n = int(m.group(1))
                    else:
                        # 兼容 "01 4K" / "10 4K" / "1" 等: 前导数字 + 可选清
                        # 晰度后缀; 拒绝 "彩蛋6"、"《入戏》…" 等非正片名。
                        m2 = re.match(r"^\s*0*(\d{1,4})", nm)
                        if not m2:
                            continue
                        n = int(m2.group(1))
                        rest = nm[m2.end():].strip().lower()
                        if rest and not re.fullmatch(r"(?:4k|hd|蓝光|超清|高清|标清|1080p?|2160p?|720p?|版|集|话|完结)\s*", rest):
                            continue
                    if n > best:
                        best = n
            if best == 0 and maxline >= 2:
                # 集名全部无法解析但有可数条数: 用最大线路条数兜底(总好过空白)
                best = maxline
            mk = (("全" + str(best) + "集") if old else ("更新至第" + str(best) + "集"))
            rm = (d.get("remarks") or "").strip()
            if rm:
                # 仅对"更新至第N集/话"形态纠偏(服务端常错标低集数); 其余形态保留
                mU = re.match(r"^(?:更新至|更新到|已更新|更至|更新|连载至|连载到)\s*第?\s*(\d+)\s*[集话]", rm)
                if mU and int(mU.group(1)) < best:
                    out = mk
                else:
                    out = rm
            else:
                if best > 0:
                    out = mk
    except Exception:
        out = ""
    _REMARKS_CACHE[key] = out
    return out


def _enhance_list(host, lst, with_rm=True, with_pic=True):
    """列表增强: 缺角标补角标, 缺/坏封面补封面。
    并发 3 个 worker, 全部静默容错, 绝不让增强失败影响列表本身。"""
    if not lst:
        return lst
    if _TPE is None:           # 无线程池环境: 退化为不发请求, 保持原样
        return lst

    def work(it):
        try:
            vid = str(it.get("vod_id") or "")
            if not vid:
                return it
            if with_rm:
                rm_cur = (it.get("vod_remarks") or "").strip()
                mU = re.match(r"^(?:更新至|更新到|已更新|更至|更新|连载至|连载到)\s*第?\s*(\d+)\s*[集话]", rm_cur)
                if not rm_cur:
                    # 空角标: 详情生成
                    rm2 = _gen_remarks(host, vid)
                    if rm2:
                        it["vod_remarks"] = rm2
                elif mU and int(mU.group(1)) <= 15:
                    # 服务端列表常把角标错标成"更新至第1/3/4/6集"(实测实际已更
                    # 20-48 集): 低值"更新至第N集/话"(<=15) 过详情校验,
                    # 仅当详情解析的真实集数更大时才替换。高值(>15) 基本可信,
                    # 不再拉详情, 控制每页请求量。
                    better = _gen_remarks(host, vid)
                    if better:
                        it["vod_remarks"] = better
            if with_pic and _pic_bad(it.get("vod_pic") or ""):
                p = _search_cover(host, it.get("vod_name") or "")
                if p:
                    it["vod_pic"] = p
        except Exception:
            pass
        return it

    try:
        with _TPE(max_workers=3) as ex:
            return list(ex.map(work, lst))
    except Exception:
        return lst


def _reco(host):
    """首页推荐: 电视剧分类第一页, 失败返回空"""
    try:
        c = _category(host, "22016", "1")
        return (c or {}).get("list") or []
    except Exception:
        return []

def _fetch_detail(host, vid):
    resp = _post_form(host, "/api/v1/video/videoDetails", {"id": str(vid)})
    try:
        return json.loads(resp).get("data") or {}
    except Exception:
        return {}


def _detail(host, vid):
    data = _fetch_detail(host, vid)
    if not data:
        return {"list": []}
    sources = data.get("playerSource") or []
    from_names, from_urllists = [], []
    seen = {}
    for src in sources:
        eps = src.get("episodes") or []
        if not eps:
            continue
        name = src.get("sourceName") or "剧下饭"
        parse_url = src.get("parseUrl") or ""
        try:
            direct = int(src.get("direct") or 0)
        except (ValueError, TypeError):
            direct = 0
        # 过滤"全线都不可用"的死线路(如 co_xxx 无解析、全部为"文件列表为空"),
        # 避免给用户展示点了必失败的空线路 = "线路不全/无法播放"。
        if not any(_code_usable(ep.get("playerCode"), parse_url, direct) for ep in eps):
            continue
        if name in seen:          # 同名线路加序号区分
            seen[name] += 1
            name = name + str(seen[name])
        else:
            seen[name] = 1
        segs = []
        for i, ep in enumerate(eps, 1):
            ep_name = (ep.get("episodeName") or "") or ("第" + str(i) + "集")
            ep_name = ep_name.replace("$", "_").replace("#", "_")
            segs.append(ep_name + "$" + str(vid) + "_" + str(i))
        from_names.append(name)
        from_urllists.append("#".join(segs))
    if not from_urllists:
        return {"list": []}
    remarks = _gen_remarks(host, str(data.get("id") or vid), detail=data)
    play_from = "$$$".join(from_names)     # 多线路: 名字用 $$$ 分隔
    play_url = "$$$".join(from_urllists)   # 线路内集数用 # 分隔
    return {"list": [{
        "vod_id": str(data.get("id") or vid),
        "vod_name": data.get("name") or "",
        "vod_pic": data.get("videoPic") or "",
        "vod_actor": data.get("actor") or "",
        "vod_director": data.get("director") or "",
        "vod_remarks": remarks,
        "vod_content": data.get("content") or "",
        "vod_year": data.get("year") or "",
        "vod_area": data.get("area") or "",
        "vod_play_from": play_from,
        "vod_play_url": play_url,
    }]}


# ---------- 线路可用性判断 / 解析辅助 ----------

def _clean_flag(name):
    """清洗线路名: 去掉会破坏 TVBox 分隔符($ #)的字符, 详情渲染与播放匹配共用"""
    return str(name or "").strip().replace("$", "_").replace("#", "_")


def _code_usable(pc, parse_url, direct):
    """判断某条 playerCode 是否可以交给播放器:
    - 占位符 -> 不可用;
    - 有 parseUrl -> 交给解析(内部码/ID/网页链接均可);
    - 无 parseUrl -> 只有 http(s) 直链才可用(co_xxx 等内部码无法解析)。
    """
    pc = (pc or "").strip()
    if not pc:
        return False
    if pc in _PLACEHOLDER_PCS or "列表为空" in pc or "暂无" in pc:
        return False
    if parse_url:
        return True
    return pc.startswith("http://") or pc.startswith("https://")


def _resolve(parse_url, pc):
    """调用线路解析接口取真实播放地址, 兼容 {url} / {data:{url}} / {data:"url"}"""
    j = _get(parse_url + (pc or ""))
    try:
        d = json.loads(j)
    except Exception:
        return ""
    u = d.get("url") if isinstance(d, dict) else None
    if not u:
        sub = d.get("data") if isinstance(d, dict) else None
        if isinstance(sub, dict):
            u = sub.get("url")
        elif isinstance(sub, str):
            u = sub
    return str(u or "").strip()


def _analysis_url(host, source_code, pc):
    """调用服务端 /api/v1/player/analysisUrl 把加密 playerCode 解析成真实播放地址。
    直播(sourceCode=zhibo/difang/huya)与点播加密码(co_xxx)均由此返回秒播地址。
    返回解析成功后的 URL 字符串, 失败返回空串。"""
    if not source_code or not pc:
        return ""
    try:
        r = _post_form(host, "/api/v1/player/analysisUrl", {"from": source_code, "code": pc})
        u = (json.loads(r).get("data") or "")
        if str(u).startswith("http"):
            return str(u)
    except Exception:
        pass
    return ""


def _play(host, flag, pid):
    try:
        vid, ep = pid.rsplit("_", 1)
        ep = int(ep)
    except Exception:
        return {"parse": 0, "url": pid, "header": {"User-Agent": UA}}
    data = _fetch_detail(host, vid)
    sources = data.get("playerSource") or []
    flag_s = _clean_flag(flag)
    # 优先用户当前选中的线路(清洗后匹配), 其余线路作为备选
    ordered = [src for src in sources if _clean_flag(src.get("sourceName") or "") == flag_s]
    for src in sources:
        if src not in ordered:
            ordered.append(src)
    for src in ordered:
        eps = src.get("episodes") or []
        if not eps or ep > len(eps):
            continue
        parse_url = src.get("parseUrl") or ""
        source_code = src.get("sourceCode") or ""
        try:
            direct = int(src.get("direct") or 0)
        except (ValueError, TypeError):
            direct = 0
        header = {"User-Agent": src.get("ua") or UA}
        pc = (eps[ep - 1] or {}).get("playerCode") or ""
        if not _code_usable(pc, parse_url, direct):
            continue                     # 占位/死码 -> 换下一条线路
        if parse_url:
            # 优先走解析(腾讯/爱奇艺等 pc 是网页链接必须解析; 解析失败换线路)
            try:
                u = _resolve(parse_url, pc)
            except Exception:
                u = ""
            if u:
                return {"parse": 0, "url": u, "header": header}
            # 解析失败: 尝试服务端 analysisUrl 秒播(部分线路 pc 是内部码/网页)
            u = _analysis_url(host, source_code, pc)
            if u:
                return {"parse": 0, "url": u, "header": header}
            continue
        # 无 parseUrl 且 pc 为 http(s) 直链 -> 直接可播
        if pc.startswith("http://") or pc.startswith("https://"):
            return {"parse": 0, "url": pc, "header": header}
        # 直播/加密码: 优先走服务端 analysisUrl 秒播解析 (zb-xxx / 数字房间号 / co_xxx)
        if pc:
            u = _analysis_url(host, source_code, pc)
            if u:
                headers = dict(header)
                if source_code == "huya":
                    headers["Referer"] = "https://www.huya.com/"
                return {"parse": 0, "url": u, "header": headers}
            # 解析失败: 仍把 code 原样返回, 交由播放器自行尝试
            return {"parse": 0, "url": pc, "header": header}
    return {"parse": 0, "url": "", "header": {"User-Agent": UA}}

# ======================= 类式接口 (class Spider) =======================

class Spider(_BaseSpider):
    """webhomeTV 类式规范: 各方法返回 dict, searchContent 三参数。
    与咕噜咕噜可搜索版(样板) 结构一致。"""

    def __init__(self, *args, **kwargs):
        self._host = BASE_URLS[0]
        if kwargs.get("host"):
            self._host = _fix_host(kwargs["host"])
        if kwargs.get("extend") is not None:
            self.init(kwargs["extend"])

    def init(self, extend=None):
        if extend:
            s = str(extend).strip()
            if s.startswith("http"):
                self._host = _fix_host(s)
            elif s.startswith("base="):
                self._host = _fix_host(s[5:])

    def getName(self):
        return "剧下饭4K影视"

    def homeContent(self, filter=False):
        result = _home(self._host)
        # 去掉推荐: 只返回纯分类列表, 各分类(含电视剧)均以分类页展示
        result["list"] = []
        return result

    def homeVideoContent(self):
        # 去掉推荐: 分类页保持纯分类列表, 不再渲染"精选/推荐"卡
        return {"list": []}

    def categoryContent(self, tid, pg="1", filter=None, extend=None):
        return _category(self._host, tid, pg)

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        return _detail(self._host, ids[0])

    # ---------- 搜索 (关键: 三参数签名, 兼容 webhomeTV) ----
    def searchContent(self, key, quick, pg="1"):
        """webhomeTV 搜索入口 - key 关键词, quick 快速标记, pg 页码"""
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick, pg="1"):
        """分页搜索 - 支持真正翻页、异常兜底"""
        try:
            return _search(self._host, key, pg)
        except Exception:
            return {"page": 1, "pagecount": 1, "limit": 0, "total": 0, "list": []}

    def playerContent(self, flag, id, vipFlags=""):
        return _play(self._host, flag, id)

    def manualVideoCheck(self):
        return False

    def isVideoFormat(self, url):
        return False

    def localProxy(self, param):
        return {"list": [], "parse": 0, "url": ""}

    def liveContent(self, url):
        return {"list": []}


# ======================= 函数式接口 (模块级函数) =======================

_HOST = BASE_URLS[0]

def init(extend=None):
    global _HOST
    if extend:
        s = str(extend).strip()
        if s.startswith("http"):
            _HOST = _fix_host(s)
        elif s.startswith("base="):
            _HOST = _fix_host(s[5:])

def homeContent(filter=False):
    try:
        r = _home(_HOST)
        r["list"] = []
    except Exception:
        r = {"class": [], "filters": {}, "list": []}
    return json.dumps(r, ensure_ascii=False)

def homeVideoContent():
    return json.dumps({"list": []}, ensure_ascii=False)

def categoryContent(tid, pg="1", filter=False, extend=None):
    return json.dumps(_category(_HOST, tid, pg), ensure_ascii=False)

def detailContent(ids):
    if not ids:
        return '{"list":[]}'
    return json.dumps(_detail(_HOST, ids[0]), ensure_ascii=False)

def searchContent(key, quick=False, pg="1"):
    return json.dumps(_search(_HOST, key, pg), ensure_ascii=False)

def playerContent(flag, id, vipFlags=None):
    return json.dumps(_play(_HOST, flag, id), ensure_ascii=False)

def manualVideoCheck():
    return False

def isVideoFormat(url):
    return False


# ======================= 本地自测 =======================

if __name__ == "__main__":
    def show(label, s, n=220):
        txt = json.dumps(s, ensure_ascii=False) if not isinstance(s, str) else s
        print("== " + label + " ==")
        print(txt if len(txt) <= n else txt[:n])
        print()

    sp = Spider()
    show("Spider.homeContent", sp.homeContent(False))
    show("Spider.categoryContent", sp.categoryContent("22016", "1", False, None))
    show("Spider.categoryLive", sp.categoryContent("22023", "1", False, None))
    show("Spider.searchContent", sp.searchContent("斗罗大陆", True))
    show("Spider.detailContent", sp.detailContent(["621119"]))
    show("Spider.playerContent ep1", sp.playerContent("剧下饭", "621119_1", None))
    show("Spider.playerContent ep2", sp.playerContent("剧下饭", "621119_2", None))
    show("Spider.liveDetail", sp.detailContent(["366473"]))
    show("Spider.livePlay", sp.playerContent("直播频道", "366473_1", None))
    show("Spider.huyaPlay", sp.playerContent("虎牙直播", "370855_1", None))
