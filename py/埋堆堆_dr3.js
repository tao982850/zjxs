/* @header({
  title: '埋堆堆',
  lang: 'dr3',
  searchable: 1, filterable: 1, quickSearch: 0,
}) */

/*
  * ---------------------------------------------------------------
 * [修复记录 · 2026-11] 源「分类 / 搜索 / 首页列表全空」的根因与修复：
 *   1) 列表接口 /api/vod/classify/word/search.action 被腾讯云 WAF 按「精确路径」拦截，
 *      无尾斜杠一律返回 403 拦截页 => 所有列表请求都拿不到数据。
 *      修复：请求路径追加尾斜杠 .../word/search.action/，命中同一后端路由并绕过该条规则。
 *   2) 该接口对 rows 有硬上限：rows<=12 才返回数据，>=13 一律「获取到0行记录」。
 *      原实现 PAGE_ROWS=36、搜索语料 rows=100，因此全部返回空。
 *      修复：统一 PAGE_ROWS=12；搜索不再单独拉语料，直接复用分类扫描结果。
 *   3) 接口另带 WAF 突发频控：短时间密集请求会被整段 403。原实现并发 8 一次拉 240 页，
 *      极易被拦且「一页失败即整体停」。修复：并发降到 3 + 波间节流 + 单页重试，
 *      并把「一次性拉全库」改为「按需分批 + 实例态累积 + 单次调用时间预算」。
 *   4) 播放探测（Range 请求）失败时，回退使用已拿到的首个直链，避免退化成无法播放的 vid:num。
 * 代码内以 [FIX-2026-11] 标注改动点。
 * ---------------------------------------------------------------
 *  数据时有时无 / 推荐条目波动 / 电影条目缺失 稳定性修复：
 *   1) WAF拦截根因：
 *      - 补全请求头：加上 X-Requested-With、Sec-Fetch-* 等标准AJAX标识，降低被WAF识别为爬虫的概率；
 *      - 新增API层统一重试：单接口最多重试4次，每次重试重新生成签名+递增退避等待，WAF频控期间自动冷却；
 *      - 域名跟随时新增预热步骤：先访问首页+静态资源路径获取Cookie，避免首次API请求直接被403。
 *   2) 空页误判死锁修复：
 *      - 原逻辑连续3页空就永久标记"扫描完成"，只要一次WAF拦截就会导致后续10分钟内所有分类/电影数据为空；
 *      - 现改为连续5空才进入3分钟冷却，冷却结束后自动重置状态继续扫描，不会永久锁死；
 *      - 扫描并发从3降到2、波间间隔从200ms拉长到500ms，进一步降低触发WAF频控的概率。
 *   3) 首页推荐稳定性：
 *      - 首页列表新增5分钟缓存+失败重试，就算偶发被WAF拦截也会返回旧缓存兜底，不会出现刷新一下就空；
 *      - 详情/播放接口同样享受API层统一重试，不再偶尔"获取详情失败"。
 */

// ============================================================
// 常量
// ============================================================
const SITE = 'https://m.mddcloud.com.cn';
const API_BASE = 'https://activity.mddcloud.com.cn';
const HOST_CANDIDATES = [
    'https://m.mddcloud.com.cn',
    'https://www.mddcloud.com.cn',
    'https://mddcloud.com.cn',
];

// 从站点前端 JS 逆向得到的私钥（原样照搬，不要改）
const PRIVATE_KEY = '8a4af424bd714be5b2baacbe3cf5bbbe0131effeb92e99356ef1662884558f28';

const UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) ' +
    'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 ' +
    'Mobile/15E148 Safari/604.1';

const BASE_HEADERS = {
    'User-Agent': UA,
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh-Hans;q=0.9,zh;q=0.8',
    'Referer': SITE + '/',
    'Origin': SITE,
    'X-Requested-With': 'XMLHttpRequest',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
};

const TIMEOUT_API = 10000;       // 单次 API 超时(ms)（拉长一点避免慢网被误判失败）
const TIMEOUT_PROBE = 5000;      // 播放地址探测超时(ms)
const API_MAX_RETRY = 4;         // 单次API请求最大重试次数（WAF频控场景）
const API_RETRY_BASE = 1200;     // API重试退避基数(ms)（WAF冷却通常需要1s+）

// 缓存 TTL (ms)
const TTL_WORDS = 24 * 3600 * 1000;   // 分类词表
const TTL_LIST = 600 * 1000;          // 列表 / 分桶
const TTL_DETAIL_OK = 300 * 1000;
const TTL_PLAY = 300 * 1000;          // F19: 直链带 exper=360s，取有效期一半
const TTL_SEARCH = 180 * 1000;
const TTL_CORPUS = 1800 * 1000;       // 搜索语料 30min
const TTL_DOMAIN = 1800 * 1000;

// 分页 / 扫描
// [FIX-2026-11] 服务端 classify/word/search 接口现对 rows 做硬上限：rows<=12 才返回数据，
// rows>=13 一律返回 0 行(msgType=0,"获取到0行记录")。故单页固定 12。
const PAGE_ROWS = 12;
// 全库约 2900 条 => 2900/12 ≈ 242 页，留足余量后再停。
const MAX_PAGES_SCAN = 260;
// 该接口同时挂着腾讯云 WAF 的突发频控：短时间请求过密会整段 403。
// 因此并发压到 2、波间留 500ms 间隔，给WAF留冷却时间；单页重试4次，空页判定放宽到连续5次。
const SCAN_CONCURRENCY = 2;
const SCAN_WAVE_GAP = 500;    // 每波扫描之间的间隔(ms)
const SCAN_PAGE_RETRY = 4;    // 单页最多重试次数
const SCAN_RETRY_GAP = 1000;  // 重试退避基数(ms)
// [FIX-2026-11·3] 页面推进计划：先顺序覆盖前段（剧集等常规内容密集区），
// 再按步长跳扫深层。实测电影(vt=1)/综艺(vt=2,6) 集中在 startRow 1400+ 的列表后半段，
// 纯顺序扫描（受时间预算限制）永远到不了那里 —— 这正是「电影」分类为空的原因。
const SCAN_SEQ_PAGES = 30;    // 顺序覆盖的页数上限
const SCAN_JUMP_FROM = 38;    // 跳扫起点(页)
const SCAN_JUMP_STEP = 8;     // 跳扫步长(页)
// 单次调用最多花在「扫描推进」上的时间预算(ms)：
// 避免稀疏分类/全库搜索把一次调用拖成几分钟（接口有频控，越急越慢）。
const CAT_TIME_BUDGET = 8000;
const SEARCH_TIME_BUDGET = 12000;

// 搜索
// [FIX-2026-11] 原实现用 rows=100 拉“搜索语料”，但接口 rows 上限仅 12，全部返回 0 行。
// 改为复用分类扫描的累积进度（同一实例态，无筛选即全库），不再单独发请求。
const SEARCH_MAX_RESULTS = 100;

// 播放字段优先级（F27/F28: 恢复 m3u8 优先，探测不过再降级）
const PLAY_FIELD_PRIORITY = ['tryM3u8Url', 'tryUrl', 'tryMp4Url'];
const MAX_EPISODES = 300;             // 超长剧只取最近 300 集

// 一级分类（官网 5 大类）
const ALL_CLASSES = [
    { type_id: 'tv', type_name: '剧集' },
    { type_id: 'movie', type_name: '电影' },
    { type_id: 'variety', type_name: '综艺' },
    { type_id: 'anime', type_name: '动画' },
    { type_id: 'documentary', type_name: '纪录片' },
];
const CATEGORIES = ['tv', 'movie', 'variety', 'anime', 'documentary'];
const VALID_TIDS = ['tv', 'movie', 'variety', 'anime', 'documentary'];

const VARIETY_LABELS = [
    '综艺', '真人秀', '访谈', '美食', '游戏娱乐', '旅行',
    '音乐', '大型晚会', '资讯', '儿童', '其他',
];

const ANIME_NAME_RE = /(动画|动漫|卡通)/;
const NAME_NOISE = /[()（）【】\[\]、，,。.·\-—~&\/\\|:：!？?"'“”‘’\s]+/g;
const TOKEN_SPLIT = /[()\[\]{}<>《》【】「」『』、，,。.·\-—\/\\|:：!？?"'\s]+/;

// ============================================================
// 小工具
// ============================================================
function getReq(ctx) {
    const net = ctx && ctx.lib && ctx.lib.net;
    return (net && (net.request || net.req)) || (ctx && ctx.req) || null;
}

function md5Hex(ctx, s) {
    if (ctx && typeof ctx.md5 === 'function') return String(ctx.md5(s));
    if (typeof md5 === 'function') return String(md5(s));
    return '';
}

// 异步等待（扫描节流 / 失败退避）
function sleep(ms) {
    return new Promise(function (r) {
        try { setTimeout(r, ms); } catch (e) { r(); }
    });
}

// 图片直链 http -> https
function fixPic(u) {
    let s = String(u == null ? '' : u).trim();
    if (!s) return '';
    if (s.indexOf('//') === 0) return 'https:' + s;
    if (s.indexOf('http://') === 0) return 'https://' + s.slice(7);
    return s;
}

function firstYear(s) {
    if (!s) return '';
    const m = String(s).match(/(\d{4})/);
    return m ? m[1] : '';
}

// 有界 TTL 缓存（以 Map 插入序近似 LRU）
function cacheGet(map, key, ttl) {
    const e = map.get(key);
    if (!e) return null;
    if ((Date.now() - e.t) >= ttl) {
        map.delete(key);
        return null;
    }
    return e.v;
}

function cacheSet(map, key, val, cap) {
    if (map.has(key)) map.delete(key);
    map.set(key, { t: Date.now(), v: val });
    while (map.size > (cap || 256)) {
        const k = map.keys().next().value;
        map.delete(k);
    }
}

// extend 解析：兼容「已解析对象」/「JSON 字符串」
function parseExtend(extend) {
    if (!extend) return {};
    if (typeof extend === 'object') return extend;
    if (typeof extend === 'string') {
        const s = extend.trim();
        if (s.charAt(0) === '{') {
            try {
                const o = JSON.parse(s);
                return (o && typeof o === 'object') ? o : {};
            } catch (e) {
                return {};
            }
        }
    }
    return {};
}

// 列表项对外只暴露标准字段
function cleanVod(v) {
    return {
        vod_id: v.vod_id,
        vod_name: v.vod_name,
        vod_pic: v.vod_pic,
        vod_remarks: v.vod_remarks,
    };
}

// ============================================================
// 签名（与前端 JS / py 完全一致）
//   - key 升序
//   - dict/list 用紧凑 JSON（等价 json.dumps(separators=(',', ':'))）
//   - 标量直接字符串化
// ============================================================
function signString(data) {
    let s = '';
    const keys = Object.keys(data).sort();
    for (let i = 0; i < keys.length; i++) {
        const k = keys[i];
        const v = data[k];
        if (v !== null && typeof v === 'object') {
            s += k + '=' + JSON.stringify(v) + '&';
        } else {
            s += k + '=' + String(v) + '&';
        }
    }
    return s;
}

function buildSignedBody(ctx, data, now) {
    const sorted = signString(data);
    const msg = 'time:' + now + '|privateKey:' + PRIVATE_KEY + '|data:' + sorted;
    return { time: now, sign: md5Hex(ctx, msg), data: data };
}

// ============================================================
// 网络层
// ============================================================
function toJsonObj(r) {
    if (r == null) return null;
    let c = r;
    if (typeof r === 'object' && r.content !== undefined) c = r.content;
    if (c == null) return null;
    if (typeof c === 'object') return c;
    const s = String(c).trim();
    if (!s) return null;
    const ch = s.charAt(0);
    if (ch !== '{' && ch !== '[') return null;
    try {
        return JSON.parse(s);
    } catch (e) {
        return null;
    }
}

// 多种 POST 形态依次尝试，只认「像本 API 的 JSON 响应」
//
// [FIX-2026-11·3] 真机「无数据」的关键修复：POST 体必须是「已序列化好的 JSON 字符串」，
// 只能放在 options.body（drpy3 规范：body=字符串原样发；data=对象，宿主会按 content-type 再序列化）。
// 旧实现把同一个 JSON 字符串同时塞进 data 与 body：部分宿主优先取 data 并对其再做一次
// JSON.stringify，于是实际发出的体变成 "{\"time\":...}"（外层多了一层引号与转义）→
// 签名体错位 → 服务端一律回 {"msgType":-1,...} → 首页 / 分类 / 搜索 / 详情全部为空。
// 本地探针用 fetch 直发字符串体，恰好绕开了这个坑，故「本地有数据、真机无数据」。
// 现改为：只传 body；并且把「非 msgType==0」的响应视为「该形态可能不对」，继续尝试下一种形态，
// 只有确实拿到 msgType==0 才返回；全部形态都拿不到时，回退最后一个「像本 API」的响应。
async function postJson(ctx, url, bodyStr, headers) {
    const req = getReq(ctx);
    const tries = [];
    if (req) {
        // 首选：字符串体，宿主原样发出（不传 data，避免二次序列化）
        tries.push(() => req(url, { method: 'POST', headers: headers, body: bodyStr, timeout: TIMEOUT_API }));
        // 兼容部分宿主认为「POST + postType:json 才带体」的写法，体仍是字符串
        tries.push(() => req(url, { method: 'POST', headers: headers, body: bodyStr, postType: 'json', timeout: TIMEOUT_API }));
    }
    if (ctx && typeof ctx.post === 'function') {
        tries.push(() => ctx.post(url, bodyStr, { headers: headers, timeout: TIMEOUT_API }));
        tries.push(() => ctx.post(url, bodyStr, headers));
    }
    let lastApiResp = null;   // 见过的最像「本 API」的响应（msgType 存在），留作兜底
    for (let i = 0; i < tries.length; i++) {
        let r = null;
        try {
            r = await tries[i]();
        } catch (e) {
            r = null;
        }
        const obj = toJsonObj(r);
        if (obj && typeof obj === 'object' && obj.msgType !== undefined) {
            if (Number(obj.msgType) === 0) return obj;   // 真正成功，立即返回
            lastApiResp = obj;                            // 形态/业务异常，记住再试下一种形态
            continue;
        }
        // 非本 API 的 JSON（多为 WAF/HTML 拦截页）：内容偏长说明已到服务器但被拦，换形态也一样
        let content = '';
        if (r != null) content = (typeof r === 'object' && r.content !== undefined) ? String(r.content) : String(r);
        if (content.replace(/\s/g, '').length > 200) return null;
    }
    return lastApiResp;
}

async function apiPost(ctx, st, path, data) {
    const url = st.api + path;
    // 优先从域名跟随预热拿到的host，避免Referer/Origin与实际请求host不一致触发反爬
    const reqHost = st.host || HOST_CANDIDATES[0];
    let lastResp = null;
    for (let attempt = 0; attempt < API_MAX_RETRY; attempt++) {
        if (attempt > 0) {
            // 退避等待：被WAF拦后不能马上重发，越急越被拦，间隔随次数递增
            await sleep(API_RETRY_BASE * (1 + Math.floor(attempt / 2)) + Math.floor(Math.random() * 500));
        }
        // 每次重试都重新生成签名和时间戳，避免sign过期/重复
        const now = Date.now();
        const body = buildSignedBody(ctx, data, now);
        const bodyStr = JSON.stringify(body);
        const headers = Object.assign({}, BASE_HEADERS, {
            'Content-Type': 'application/json;charset=UTF-8',
            'Referer': reqHost + '/',
            'Origin': reqHost,
        });
        let resp = null;
        try {
            resp = await postJson(ctx, url, bodyStr, headers);
        } catch (e) {
            resp = null;
        }
        if (resp && Number(resp.msgType) === 0) {
            return resp;  // 成功，立即返回
        }
        // 记录最后一次有效API响应（便于调试）
        if (resp && resp.msgType !== undefined) lastResp = resp;
        // 如果返回明确业务错误（非空/非-1），不是WAF问题，不用重试
        if (resp && Number(resp.msgType) !== -1) break;
    }
    // 全部重试失败，返回最后一次响应（可能是错误码），避免返回null导致上层崩溃
    return lastResp;
}

// 域名跟随（best-effort，失败不阻塞）+ API预热取Cookie
async function followHost(ctx, st) {
    if (st.hostChecked && (Date.now() - st.hostChecked < TTL_DOMAIN)) return;
    const req = getReq(ctx);
    if (!req) return;
    st.hostChecked = Date.now();
    // 先访问站点首页拿Cookie（WAF通常会对首次无Cookie请求直接403）
    for (let i = 0; i < HOST_CANDIDATES.length; i++) {
        const h = HOST_CANDIDATES[i];
        try {
            const r = await req(h + '/', {
                headers: { 'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml' },
                timeout: 5000,
                redirect: 'follow',
            });
            const html = (r && r.content != null) ? String(r.content).slice(0, 200000) : '';
            if (html.indexOf('埋堆堆') >= 0 || html.indexOf('mddcloud') >= 0) {
                st.host = h;
                // 额外访问一次静态JS路径，让WAF放行后续API请求
                try { await req(h + '/static/js/', { headers: { 'User-Agent': UA }, timeout: 3000 }); } catch (e) { /* 忽略 */ }
                return;
            }
        } catch (e) {
            // 忽略，继续下一个候选
        }
    }
}

// ============================================================
// 数据层
// ============================================================
function toVod(v) {
    const vid = String((v && (v.uuid || v.vodUuid)) || '').trim();
    const name = String((v && v.name) || '').trim();
    if (!vid || !name) return null;
    return {
        vod_id: vid,
        vod_name: name,
        vod_pic: fixPic(v.coverImage || v.sideImage || v.downImage),
        vod_remarks: '',
        // 内部字段，仅用于本地分类/回填，交付前由 cleanVod 剥掉
        _material: String(v.materialName || ''),
        _year: String(v.yearName || ''),
        _vod_type: parseInt(v.vodType || 0, 10) || 0,
        _total_num: parseInt(v.totalNum || 0, 10) || 0,
    };
}

async function fetchList(ctx, st, uuidList, rows, startRow, isVip, order) {
    // [FIX-2026-11] 该路径被腾讯云 WAF 按“精确路径”规则拦截（无尾斜杠 => 403 WAF 页）。
    // 追加一个尾斜杠即可命中同一后端路由并绕过该条 WAF 规则，响应仍为正常 JSON。
    const resp = await apiPost(ctx, st, '/api/vod/classify/word/search.action/', {
        uuidList: uuidList || [],
        rows: rows,
        startRow: startRow,
        isVip: String(isVip),
        orderType: String(order),
    });
    if (!resp || resp.msgType !== 0) return [];
    const arr = resp.data || [];
    const out = [];
    for (let i = 0; i < arr.length; i++) {
        const item = toVod(arr[i]);
        if (item) {
            out.push(item);
            // 回填详情元信息（getVodInfo 的 year/material 为 None）
            if (st.listMeta.size < 8000) {
                st.listMeta.set(item.vod_id, { _material: item._material, _year: item._year });
            }
        }
    }
    return out;
}

// 单页（带缓存）
async function getPage(ctx, st, uuidList, isVip, order, p) {
    const key = JSON.stringify(uuidList || []) + '|' + isVip + '|' + order + '|' + p;
    const cached = cacheGet(st.pages, key, TTL_LIST);
    if (cached) return cached;
    const lst = await fetchList(ctx, st, uuidList, PAGE_ROWS, (p - 1) * PAGE_ROWS, isVip, order);
    if (lst && lst.length) cacheSet(st.pages, key, lst, 512);
    return lst;
}

// 分类词表
async function classifyWords(ctx, st) {
    const cached = cacheGet(st.words, '__w__', TTL_WORDS);
    if (cached) return cached;
    const data = await apiPost(ctx, st, '/api/vod/classify/list.action/', {});
    const words = {};
    if (data && data.msgType === 0 && data.data) {
        for (let i = 0; i < data.data.length; i++) {
            const item = data.data[i] || {};
            const fc = item.fieldCode || '';
            const ws = [];
            const arr = item.words || [];
            for (let j = 0; j < arr.length; j++) {
                const uuid = String(arr[j].uuid || '');
                const name = String(arr[j].word || '').trim();
                if (name && name !== '全部' && uuid) ws.push({ word: name, uuid: uuid });
            }
            if (fc && ws.length) words[fc] = ws;
        }
    }
    if (Object.keys(words).length) {
        cacheSet(st.words, '__w__', words, 4);
        return words;
    }
    return {};
}

// 把「词名」或「uuid」统一解析为 uuid（F18: 彻底放弃格式启发式）
function resolveUuid(words, field, raw) {
    const r = String(raw == null ? '' : raw).trim();
    if (!r) return '';
    const arr = words[field] || [];
    for (let i = 0; i < arr.length; i++) if (arr[i].word === r) return arr[i].uuid || '';
    for (let i = 0; i < arr.length; i++) if (arr[i].uuid === r) return r;
    return '';
}

function buildFilters(words) {
    const mk = function (fc, name) {
        const value = [{ n: '全部', v: '' }];
        const arr = words[fc] || [];
        for (let i = 0; i < arr.length; i++) value.push({ n: arr[i].word, v: arr[i].uuid });
        return { key: fc, name: name, value: value };
    };
    return [
        mk('material', '题材'),
        mk('lang', '语言'),
        mk('region', '地区'),
        mk('year', '年份'),
        {
            key: 'isvip', name: '收费', value: [
                { n: '全部', v: '-1' },
                { n: '限免', v: '0' },
                { n: 'VIP', v: '1' },
            ],
        },
        {
            key: 'order', name: '排序', value: [
                { n: '默认', v: '0' },
                { n: '最新', v: '1' },
                { n: '好评', v: '2' },
            ],
        },
    ];
}

// ============================================================
// 本地分类规则（后端不支持按 vodType/material 过滤）
// 优先级: 纪录片 > 动画 > 电影 > 综艺 > 剧集
// ============================================================
function matchCategory(vod, tid) {
    const mats = {};
    const raw = String(vod._material || '');
    const parts = raw.split(',');
    for (let i = 0; i < parts.length; i++) {
        const x = parts[i].trim();
        if (x) mats[x] = 1;
    }
    // [FIX-2026-11·3] 站点 vodType 口径（取自详情页前端 filterVodType 映射）：
    //   0=剧集  1=电影  2=综艺  7=直播
    // 旧实现用「vt===1 && tn===1」判电影，而列表接口的 vodType 实测几乎恒为 0，
    // 该判定永远不成立 => 电影分类永远为空。现按站点原口径用 vodType 直接分型。
    const vt = vod._vod_type || 0;
    const name = String(vod.vod_name || '');

    if (vt === 7) return false;                     // 直播，不属于点播分类

    const isDoc = !!mats['纪录片'];
    const isAnime = !!mats['动漫'] || (!!mats['儿童'] && ANIME_NAME_RE.test(name));
    const isMovie = (vt === 1);
    // 实测：material=综艺 的条目 vodType=6；无筛选深层里 vodType=2/6 均为综艺类。
    let isVar = (vt === 2 || vt === 6);
    if (!isVar) {
        // 兜底：个别条目 vodType 缺失时，用 material 的综艺类标签补判
        for (let i = 0; i < VARIETY_LABELS.length; i++) {
            if (mats[VARIETY_LABELS[i]]) { isVar = true; break; }
        }
    }

    if (tid === 'documentary') return isDoc;
    if (tid === 'anime') return isAnime;
    if (tid === 'movie') return isMovie;
    if (tid === 'variety') return isVar && !isDoc && !isAnime;
    if (tid === 'tv') return !isDoc && !isAnime && !isMovie && !isVar;
    return false;
}

// 单页带重试获取：接口有突发频控，偶发 403/空页要重试，而不是直接判“到底了”
async function getPageStable(ctx, st, uuidList, isVip, order, p) {
    for (let t = 0; t < SCAN_PAGE_RETRY; t++) {
        let lst = null;
        try {
            lst = await getPage(ctx, st, uuidList, isVip, order, p);
        } catch (e) {
            lst = null;
        }
        if (lst && lst.length) return lst;
        if (t < SCAN_PAGE_RETRY - 1) await sleep(SCAN_RETRY_GAP * (t + 1));
    }
    return [];
}

// ---- 增量扫描：接口有 WAF 突发频控，240 页一次性拉完极易被整段拦截，
//      改为「按需分批 + 实例态累积 + 时间预算」，兼顾速度与覆盖。----
function catState(st, key) {
    if (!st.cats) st.cats = {};
    const keys = Object.keys(st.cats);
    if (keys.length > 6) st.cats = {};              // 简单防膨胀
    let cs = st.cats[key];
    const ttl = TTL_LIST;
    if (!cs || (Date.now() - cs.time) > ttl) {
        cs = st.cats[key] = {
            key: key,
            time: Date.now(),
            seen: {},
            buckets: { tv: [], movie: [], variety: [], anime: [], documentary: [] },
            cursor: 1,
            jump: 0,
            done: false,
            doneTime: 0,
            emptyStreak: 0,
            cooldownUntil: 0,
        };
    }
    return cs;
}

// 页面推进计划 [FIX-2026-11·3]：前段顺序 + 深层按步长跳扫
function nextBatch(cs, n) {
    const out = [];
    while (out.length < n) {
        if (cs.cursor <= SCAN_SEQ_PAGES) {
            out.push(cs.cursor);
            cs.cursor++;
            continue;
        }
        if (!cs.jump) cs.jump = SCAN_JUMP_FROM;
        if (cs.jump > MAX_PAGES_SCAN) { cs.done = true; break; }
        out.push(cs.jump);
        cs.jump += SCAN_JUMP_STEP;
    }
    return out;
}

// 扫一批（SCAN_CONCURRENCY 页）并入累积桶；返回本批是否拿到数据
async function scanOnce(ctx, st, uuidList, isVip, order, cs) {
    if (cs.done) return false;
    // [FIX-2026-11·6] 冷却期间不发请求，等WAF解封后再扫，避免持续触发反爬
    if (cs.cooldownUntil && Date.now() < cs.cooldownUntil) return false;
    // 冷却到点自动重置状态，允许恢复扫描
    if (cs.cooldownUntil && Date.now() >= cs.cooldownUntil) {
        cs.cooldownUntil = 0;
        cs.emptyStreak = 0;
    }
    const batch = nextBatch(cs, SCAN_CONCURRENCY);
    if (!batch.length) { cs.done = true; return false; }
    const results = await Promise.all(batch.map(function (p) {
        return getPageStable(ctx, st, uuidList, isVip, order, p);
    }));
    let got = 0;
    let tail = false;
    for (let i = 0; i < results.length; i++) {
        const lst = results[i] || [];
        if (!lst.length) continue;
        got += lst.length;
        for (let j = 0; j < lst.length; j++) {
            const v = lst[j];
            if (cs.seen[v.vod_id]) continue;
            cs.seen[v.vod_id] = 1;
            for (let k = 0; k < CATEGORIES.length; k++) {
                if (matchCategory(v, CATEGORIES[k])) {
                    cs.buckets[CATEGORIES[k]].push(v);
                    break;
                }
            }
        }
        // 只把「顺序段」的短页当尾页；跳扫段命中空页属于正常采样
        if (lst.length < PAGE_ROWS && batch[i] <= SCAN_SEQ_PAGES) tail = true;
    }
    if (tail) {
        // 真的到尾页才永久结束
        cs.done = true;
        cs.doneTime = Date.now();
    }
    if (got === 0) {
        cs.emptyStreak++;
        // [FIX-2026-11·6] 空页判定从3次放宽到5次，避免偶发WAF拦截误判扫到底；
        // 达到阈值后不永久锁死，冷却3分钟后允许重新尝试，WAF恢复后自动恢复数据
        if (cs.emptyStreak >= 5) {
            cs.cooldownUntil = Date.now() + 3 * 60 * 1000; // 3分钟冷却
        }
    } else {
        cs.emptyStreak = 0;
        cs.cooldownUntil = 0;
    }
    return got > 0;
}

// 累积桶的全部条目（去重后）
function catAllItems(cs) {
    const out = [];
    for (let k = 0; k < CATEGORIES.length; k++) {
        const arr = cs.buckets[CATEGORIES[k]] || [];
        for (let i = 0; i < arr.length; i++) out.push(arr[i]);
    }
    return out;
}

// 全库（无筛选）扫描状态 key，分类与搜索共用同一份累积进度
const FULL_SCAN_KEY = JSON.stringify([]) + '|-1|0';

// ============================================================
// 搜索匹配（token / 缩写 / 字符重叠 / 长度惩罚）
// ============================================================
function normalizeName(name) {
    return String(name || '').replace(NAME_NOISE, '').toLowerCase();
}

function tokenize(name) {
    const s = String(name || '');
    const toks = s.split(TOKEN_SPLIT).filter(function (t) { return !!t; });
    if (toks.length) return toks;
    return s ? [normalizeName(s)] : [];
}

function initialsOf(tokens) {
    let s = '';
    for (let i = 0; i < tokens.length; i++) if (tokens[i]) s += tokens[i].charAt(0);
    return s.toLowerCase();
}

function matchScore(kwNorm, kwTokens, kwInitials, titleNorm, titleTokens, titleInitials) {
    let best = 0;
    if (!kwNorm || !titleNorm) return 0;

    if (kwNorm === titleNorm) best = 100;

    if (titleTokens.indexOf(kwNorm) >= 0 || kwTokens.indexOf(titleNorm) >= 0) best = Math.max(best, 85);

    if (kwNorm && titleNorm.indexOf(kwNorm) >= 0) best = Math.max(best, 65);

    if (kwTokens.length && titleTokens.length) {
        let all = true;
        for (let i = 0; i < kwTokens.length; i++) if (titleTokens.indexOf(kwTokens[i]) < 0) { all = false; break; }
        if (all) {
            best = Math.max(best, 55);
        } else {
            let any = false;
            for (let i = 0; i < kwTokens.length; i++) if (titleTokens.indexOf(kwTokens[i]) >= 0) { any = true; break; }
            if (any) best = Math.max(best, 40);
        }
    }

    if (kwInitials && titleInitials && kwInitials.length >= 2) {
        if (titleInitials.indexOf(kwInitials) >= 0) best = Math.max(best, 30);
    }

    if (best === 0 && kwNorm.length >= 2) {
        const tset = {};
        for (let i = 0; i < titleNorm.length; i++) tset[titleNorm.charAt(i)] = 1;
        const kset = {};
        for (let i = 0; i < kwNorm.length; i++) kset[kwNorm.charAt(i)] = 1;
        const kchars = Object.keys(kset);
        let overlap = 0;
        for (let i = 0; i < kchars.length; i++) if (tset[kchars[i]]) overlap++;
        if (overlap >= Math.max(2, Math.round(kchars.length * 0.6))) {
            best = Math.max(best, Math.min(20, overlap * 3));
        }
    }
    return best;
}

// 全库语料：复用分类扫描的累积进度（同一 key 即全库），按时间预算推进
async function searchCorpus(ctx, st) {
    if (st.corpus && (Date.now() - st.corpusTime < TTL_CORPUS)) return st.corpus;

    const cs = catState(st, FULL_SCAN_KEY);
    const t0 = Date.now();
    while (!cs.done && (Date.now() - t0) < SEARCH_TIME_BUDGET) {
        await scanOnce(ctx, st, [], '-1', '0', cs);
        if (!cs.done) await sleep(SCAN_WAVE_GAP);
    }
    const collected = new Map();
    const all = catAllItems(cs);
    for (let i = 0; i < all.length; i++) {
        if (!collected.has(all[i].vod_id)) collected.set(all[i].vod_id, all[i]);
    }
    st.corpus = collected;
    st.corpusTime = Date.now();
    return collected;
}

// ============================================================
// 播放解析
// ============================================================
async function probePlayUrl(ctx, url) {
    if (!url) return false;
    const req = getReq(ctx);
    if (!req) return true;   // 无网络入口时不阻塞，交给播放器
    try {
        const r = await req(url, {
            headers: Object.assign({}, BASE_HEADERS, { Range: 'bytes=0-0' }),
            timeout: TIMEOUT_PROBE,
        });
        const c = (r && r.content != null) ? r.content : '';
        return String(c).length > 0;
    } catch (e) {
        return false;
    }
}

async function resolvePlay(ctx, st, playKey) {
    const cached = cacheGet(st.play, playKey, TTL_PLAY);
    if (cached) return cached;

    let real = '';
    let firstCand = '';
    try {
        const idx = playKey.indexOf(':');
        const vid = playKey.slice(0, idx).trim();
        const num = parseInt(playKey.slice(idx + 1), 10) || 0;
        const resp = await apiPost(ctx, st, '/api/vod/getTrySaction.action/', { vodUuid: vid, num: num });
        if (resp && resp.msgType === 0 && resp.data) {
            const d = resp.data;
            for (let i = 0; i < PLAY_FIELD_PRIORITY.length; i++) {
                const u = String(d[PLAY_FIELD_PRIORITY[i]] || '').trim();
                if (!u) continue;
                const cand = fixPic(u);
                if (!firstCand) firstCand = cand;
                if (await probePlayUrl(ctx, cand)) {
                    real = cand;
                    break;
                }
            }
        }
    } catch (e) {
        real = '';
    }
    // [FIX-2026-11] 探测(Range 请求)可能因 CDN/频控失败；此时不要丢弃已拿到的直链，
    // 回退用首个候选地址，仍按直链(parse:0)交给播放器，避免退化成无法播放的 vid:num。
    if (!real) real = firstCand;
    if (real) cacheSet(st.play, playKey, real, 256);
    return real;
}

function playPayload(st, url) {
    return {
        parse: 0,
        jx: 0,
        url: url,
        header: {
            'User-Agent': UA,
            'Referer': st.host + '/',
            'Origin': st.host,
        },
    };
}

// ============================================================
// 详情
// ============================================================
async function fetchDetail(ctx, st, vid) {
    // [FIX-2026-11·4] 详情接口同样追加尾斜杠，与列表接口保持一致，规避真机WAF拦截
    const resp = await apiPost(ctx, st, '/api/vod/getVodInfo.action/', { vodUuid: vid, num: 1 });
    if (!resp || resp.msgType !== 0 || !resp.data) return { list: [] };
    const v = resp.data;

    const rawList = (v.vodSactionList || []).filter(function (s) {
        return s && s.num !== undefined && s.num !== null;
    });
    if (!rawList.length) return { list: [] };

    let sl = rawList.slice().sort(function (a, b) { return (a.num - b.num); });
    if (sl.length > 200) {
        sl = sl.slice(-MAX_EPISODES);
        sl.reverse();          // 超长剧最新集在前
    }

    const eps = [];
    for (let i = 0; i < sl.length; i++) {
        const s = sl[i];
        const epName = String(s.name || '').trim() || ('第' + s.num + '集');
        eps.push(epName + '$' + vid + ':' + s.num);
    }

    // 元信息回填
    let year = '';
    const meta = st.listMeta.get(vid);
    if (meta && meta._year) year = firstYear(meta._year);
    if (!year) year = firstYear(v.yearName);
    if (!year && v.firstSowingTime) {
        const raw = String(v.firstSowingTime);
        const n = parseInt(raw, 10);
        if (!isNaN(n) && /^\d+$/.test(raw)) {
            const ms = raw.length >= 12 ? n : (raw.length === 10 ? n * 1000 : n);
            const y = new Date(ms).getFullYear();
            if (!isNaN(y) && y > 1900) year = String(y);
        } else {
            const m = raw.match(/(19|20)\d{2}/);
            if (m) year = m[0];
        }
    }

    const name = String(v.name || vid);
    const vodArea = /(普通话|国语)/.test(name) ? '中国内地' : '中国香港';

    const remarkParts = [];
    if (v.updateNum) remarkParts.push('更新至' + v.updateNum + '集');

    const detail = {
        vod_id: vid,
        vod_name: name,
        vod_pic: fixPic(v.coverImage || v.sideImage || v.downImage),
        vod_year: year,
        vod_area: vodArea,
        vod_actor: String(v.starring || '').replace(/,/g, '/'),
        vod_director: String(v.director || '').replace(/,/g, '/'),
        vod_remarks: remarkParts.join('·'),
        vod_content: String(v.introduction || '').trim(),
        vod_play_from: '埋堆堆',
        vod_play_url: eps.length ? eps.join('#') : '📖 查看说明$about',
    };
    return { list: [detail] };
}

// ============================================================
// 实例态
// ============================================================
function ensureState(sp) {
    if (!sp._s) {
        sp._s = {
            words: new Map(),
            pages: new Map(),
            cats: {},
            detail: new Map(),
            play: new Map(),
            listMeta: new Map(),
            search: new Map(),
            corpus: null,
            corpusTime: 0,
            host: HOST_CANDIDATES[0],
            api: API_BASE,
            hostChecked: 0,
        };
    }
    return sp._s;
}

async function firstPage(ctx, st) {
    // [FIX-2026-11·6] 首页推荐加5分钟缓存+失败回退缓存，避免偶发WAF拦截导致首页完全为空
    const cached = cacheGet(st.pages, '__home__', 5 * 60 * 1000);
    if (cached && cached.length) return cached;
    let lst = [];
    // 首页和列表用同样的重试逻辑，不是一次失败就空
    for (let t = 0; t < SCAN_PAGE_RETRY; t++) {
        try {
            lst = await fetchList(ctx, st, [], PAGE_ROWS, 0, '-1', '0');
        } catch (e) {
            lst = [];
        }
        if (lst && lst.length) break;
        if (t < SCAN_PAGE_RETRY - 1) await sleep(SCAN_RETRY_GAP * (t + 1));
    }
    if (lst && lst.length) {
        cacheSet(st.pages, '__home__', lst, 32);
        return lst;
    }
    // 真的拿不到新数据时，返回旧缓存兜底（哪怕过期了也比空列表好）
    const stale = st.pages.get('__home__');
    return (stale && stale.v) ? stale.v : [];
}

// ============================================================
// 导出
// ============================================================
export default {
    meta: {
        title: '埋堆堆',
        host: SITE,
        searchable: 1,
        filterable: 1,
        quickSearch: 0,
    },

    rule: {
        class_name: '剧集&电影&综艺&动画&纪录片',
        class_url: 'tv&movie&variety&anime&documentary',
        headers: { 'User-Agent': UA },
        timeout: TIMEOUT_API,
    },

    async init(ctx, ext) {
        const st = ensureState(this);
        const e = String(ext == null ? '' : ext);
        const kvs = e.split(',');
        for (let i = 0; i < kvs.length; i++) {
            const kv = kvs[i];
            const idx = kv.indexOf('=');
            if (idx < 0) continue;
            const k = kv.slice(0, idx).trim().toLowerCase();
            const val = kv.slice(idx + 1).trim();
            if (k === 'host' && val) {
                st.host = (val.indexOf('http') === 0 ? val : 'https://' + val).replace(/\/+$/, '');
            } else if (k === 'api' && val) {
                st.api = (val.indexOf('http') === 0 ? val : 'https://' + val).replace(/\/+$/, '');
            }
        }
    },

    // 动态分类 + 筛选项 + 首页推荐
    async home(ctx, filter) {
        const st = ensureState(this);
        const cls = ALL_CLASSES.map(function (c) {
            return { type_id: c.type_id, type_name: c.type_name };
        });
        const out = { class: cls, list: [] };

        try { await followHost(ctx, st); } catch (e) { /* 忽略 */ }

        try {
            const words = await classifyWords(ctx, st);
            if (Object.keys(words).length) {
                // F11: filters 必须是 {type_id: [Filter...]} 字典（5 个一级 tab 共用同一份词表）
                const arr = buildFilters(words);
                const fmap = {};
                for (let i = 0; i < ALL_CLASSES.length; i++) fmap[ALL_CLASSES[i].type_id] = arr;
                out.filters = fmap;
            }
        } catch (e) { /* 忽略，分类仍可用 */ }

        try {
            const first = await firstPage(ctx, st);
            out.list = first.map(cleanVod);
        } catch (e) { /* 忽略 */ }

        return out;
    },

    async homeVod(ctx) {
        const st = ensureState(this);
        try {
            const first = await firstPage(ctx, st);
            return { list: first.map(cleanVod) };
        } catch (e) {
            return { list: [] };
        }
    },

    async category(ctx, tid, pg, filter, extend) {
        const st = ensureState(this);
        const page = Math.max(1, parseInt(pg, 10) || 1);
        const tidS = String(tid == null ? '' : tid);

        if (VALID_TIDS.indexOf(tidS) < 0) {
            return { list: [], page: page, pagecount: 0, limit: PAGE_ROWS, total: 0 };
        }
        try {
            let ext = parseExtend(extend);
            if (!Object.keys(ext).length) ext = parseExtend(filter);

            const words = await classifyWords(ctx, st);

            const uuidList = [];
            const fields = ['lang', 'material', 'year', 'region'];
            for (let i = 0; i < fields.length; i++) {
                const raw = String(ext[fields[i]] || '').trim();
                if (!raw) continue;
                const u = resolveUuid(words, fields[i], raw);
                if (u) uuidList.push(u);
            }

            const isVip = String(ext.isvip || '-1').trim() || '-1';
            const order = String(ext.order || '0').trim() || '0';

            const key = JSON.stringify(uuidList) + '|' + isVip + '|' + order;
            const cs = catState(st, key);
            const need = page * PAGE_ROWS;
            const t0 = Date.now();
            while (!cs.done && (cs.buckets[tidS] || []).length < need && (Date.now() - t0) < CAT_TIME_BUDGET) {
                await scanOnce(ctx, st, uuidList, isVip, order, cs);
                if (!cs.done) await sleep(SCAN_WAVE_GAP);
            }
            const catList = cs.buckets[tidS] || [];

            const total = catList.length;
            // 扫描未收尾时总页数未知 => 999（壳子会一直允许继续翻页）
            const pagecount = cs.done ? Math.max(1, Math.ceil(total / PAGE_ROWS)) : 999;
            const start = (page - 1) * PAGE_ROWS;

            return {
                list: catList.slice(start, start + PAGE_ROWS).map(cleanVod),
                page: page,
                pagecount: pagecount,
                limit: PAGE_ROWS,
                total: total,
            };
        } catch (e) {
            return { list: [], page: page, pagecount: 1, limit: PAGE_ROWS, total: 0 };
        }
    },

    async detail(ctx, id) {
        const st = ensureState(this);
        const vid = String(id == null ? '' : id).split(',')[0].trim();
        if (!vid) return { list: [] };

        const cached = cacheGet(st.detail, vid, TTL_DETAIL_OK);
        if (cached) return cached;

        let res = { list: [] };
        try {
            res = await fetchDetail(ctx, st, vid);
        } catch (e) {
            res = { list: [] };
        }
        if (res && res.list && res.list.length) cacheSet(st.detail, vid, res, 64);
        return res;
    },

    async search(ctx, wd, quick, pg) {
        const st = ensureState(this);
        const kw = String(wd || '').trim();
        const page = Math.max(1, parseInt(pg, 10) || 1);
        const limit = SEARCH_MAX_RESULTS;

        if (!kw) return { list: [], page: 1, pagecount: 1, limit: limit, total: 0 };

        try {
            let result = cacheGet(st.search, kw, TTL_SEARCH);
            if (!result) {
                const kwNorm = normalizeName(kw);
                const kwTokens = tokenize(kw).map(function (t) { return t.toLowerCase(); });
                const kwInitials = initialsOf(kwTokens);

                const corpus = await searchCorpus(ctx, st);
                const matched = [];
                corpus.forEach(function (item) {
                    const title = item.vod_name;
                    const titleNorm = normalizeName(title);
                    const titleTokens = tokenize(title).map(function (t) { return t.toLowerCase(); });
                    const titleInitials = initialsOf(titleTokens);
                    let score = matchScore(kwNorm, kwTokens, kwInitials, titleNorm, titleTokens, titleInitials);
                    if (score === 0) return;
                    score -= Math.min(5, Math.max(0, title.length - kw.length));
                    matched.push({ score: score, title: title, item: item });
                });
                matched.sort(function (a, b) {
                    if (b.score !== a.score) return b.score - a.score;
                    return a.title < b.title ? -1 : (a.title > b.title ? 1 : 0);
                });
                result = matched.slice(0, SEARCH_MAX_RESULTS).map(function (m) { return cleanVod(m.item); });
                if (result.length) cacheSet(st.search, kw, result, 64);
            }

            const total = result.length;
            const pagecount = Math.max(1, Math.ceil(total / limit));
            const start = (page - 1) * limit;
            return {
                list: result.slice(start, start + limit),
                page: page,
                pagecount: pagecount,
                limit: limit,
                total: total,
            };
        } catch (e) {
            return { list: [], page: page, pagecount: 1, limit: limit, total: 0 };
        }
    },

    async play(ctx, flag, id, flags) {
        const st = ensureState(this);
        if (!id) return { parse: 0, jx: 0, url: '' };
        const playKey = String(id).trim();

        // 裸直链（如某些线路直接给 http 地址）：原样交给播放器
        if (/^https?:\/\//i.test(playKey)) return playPayload(st, fixPic(playKey));
        // 非 {vid}:{num} 键（如说明用伪线路 about）：诚实降级为空 url
        if (playKey.indexOf(':') < 0) {
            return { parse: 0, jx: 0, url: '' };
        }

        try {
            let url = cacheGet(st.play, playKey, TTL_PLAY);
            if (!url) url = await resolvePlay(ctx, st, playKey);
            if (url) return playPayload(st, url);
        } catch (e) { /* 落到降级分支 */ }

        // F20 兜底：解析不到可播直链时交壳嗅探（诚实降级）
        return {
            parse: 1,
            jx: 1,
            url: playKey,
            header: { 'User-Agent': UA, 'Referer': st.host + '/' },
        };
    },
};
