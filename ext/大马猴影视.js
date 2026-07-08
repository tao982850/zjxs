/*
 * @File   : 大马猴影视.js
 * @Author : opencode
 * @Date   : 2026-07-08
 * @Desc   : 大马猴影视 (dmhyy.com) TVBox T4(JS) 源 —— 自包含，无外部依赖
 *
 * 站点结构：
 *  - 纯前端 SPA，数据全部走 /api.php/web/ 接口，返回 JSON。
 *  - 关键：请求必须带头 `x-platform: web`，否则 get_detail 的
 *    vod_play_from / vod_play_url 会被服务端返回为空。
 *  - filter/vod 必须用 type_name(中文)过滤，否则返回全站热榜。
 *  - 播放地址两类：
 *      1) 明文直链（如 lzm3u8 线路，值形如 https://xxx/index.m3u8）——直接播放。
 *      2) 加密线路（如 vwnet-xxx / YYNB-xxx / Ace_Net-xxx）——POST protobuf 到
 *         /api.php/web/decode/url，带 SHA-256 签名，响应 protobuf 里含真实 m3u8。
 *         本源内置纯 JS 的 SHA-256 与 protobuf 编解码，在 play() 阶段实时解密。
 *  - 线路名沿用站点原始代号（站点未下发中文映射表）。
 */

var DMHYY_VERSION = "20260708-js-2";
var HOST = "https://dmhyy.com";
var API = HOST + "/api.php/web";
var UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

// 解密签名常量（来自站点前端 bundle）
var APP = {
    appId: "cde75dbd61ce274e07e8ce29",
    finger: "505a0e62069a061e07698eb4b6327d88",
    secretKey: "9b1fccddb6f8e1b385de7e6e736e050144a7f3a208130fff",
    appVersion: 1
};

var HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Referer": HOST + "/",
    "Origin": HOST,
    "x-platform": "web",          // 必带，否则详情播放地址为空
    "X-Client": "YOUR_PUBLIC_CLIENT_ID"
};

var CLASSES = [];
var FILTERS = {};
var TYPE_NAME = {};   // type_id -> type_name

function log(msg) {
    try { console.log("[DMHYY_JS " + DMHYY_VERSION + "] " + msg); } catch (e) {}
}

/* ---------------- 通用工具 ---------------- */

function toStr(v) { return v === undefined || v === null ? "" : String(v); }
function encode(s) { return encodeURIComponent(toStr(s)); }
function joinField(v) {
    if (Array.isArray(v)) return v.filter(Boolean).join(",");
    return toStr(v);
}
function isPlayableUrl(u) { return /^https?:\/\//i.test(toStr(u)); }

function requestJson(url) {
    var h = {};
    for (var k in HEADERS) h[k] = HEADERS[k];
    try {
        log("fetch " + url);
        var res = req(url, { method: "GET", headers: h, timeout: 8000 });
        var body = (typeof res === "string") ? res : (res && (res.content || res.body || res.data));
        if (typeof body === "string") {
            try { return JSON.parse(body); } catch (e) { log("json_parse_error " + e); return {}; }
        }
        return body || {};
    } catch (e) {
        log("fetch_error " + url + " " + e);
        return {};
    }
}

function textClean(s) {
    return toStr(s)
        .replace(/<[^>]+>/g, "")
        .replace(/&nbsp;/g, " ")
        .replace(/&amp;/g, "&")
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/\s+/g, " ")
        .trim();
}

function formatVod(v) {
    return {
        vod_id: v.vod_id,
        vod_name: v.vod_name,
        vod_pic: v.vod_pic,
        vod_remarks: v.vod_remarks || ""
    };
}

/* ============================================================
 *  字节 / UTF-8 / SHA-256 / protobuf  —— 纯 JS，无外部依赖
 * ============================================================ */

// 字符串 -> UTF-8 字节数组
function strToUtf8Bytes(str) {
    var bytes = [];
    for (var i = 0; i < str.length; i++) {
        var c = str.charCodeAt(i);
        if (c < 0x80) {
            bytes.push(c);
        } else if (c < 0x800) {
            bytes.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f));
        } else if (c >= 0xd800 && c <= 0xdbff) {
            // 代理对
            var c2 = str.charCodeAt(++i);
            var cp = 0x10000 + ((c & 0x3ff) << 10) + (c2 & 0x3ff);
            bytes.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 0x3f), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
        } else {
            bytes.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
        }
    }
    return bytes;
}

// UTF-8 字节数组 -> 字符串
function utf8BytesToStr(bytes) {
    var out = "";
    var i = 0, len = bytes.length;
    while (i < len) {
        var c = bytes[i++] & 0xff;
        if (c < 0x80) {
            out += String.fromCharCode(c);
        } else if (c >= 0xc0 && c < 0xe0) {
            out += String.fromCharCode(((c & 0x1f) << 6) | (bytes[i++] & 0x3f));
        } else if (c >= 0xe0 && c < 0xf0) {
            out += String.fromCharCode(((c & 0x0f) << 12) | ((bytes[i++] & 0x3f) << 6) | (bytes[i++] & 0x3f));
        } else {
            var cp = ((c & 0x07) << 18) | ((bytes[i++] & 0x3f) << 12) | ((bytes[i++] & 0x3f) << 6) | (bytes[i++] & 0x3f);
            cp -= 0x10000;
            out += String.fromCharCode(0xd800 + (cp >> 10), 0xdc00 + (cp & 0x3ff));
        }
    }
    return out;
}

// 纯 JS SHA-256，输入字节数组，输出大写 HEX
function sha256Hex(msgBytes) {
    function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }
    var H = [1779033703, 3144134277, 1013904242, 2773480762, 1359893119, 2600822924, 528734635, 1541459225];
    var K = [
        1116352408, 1899447441, 3049323471, 3921009573, 961987163, 1508970993, 2453635748, 2870763221,
        3624381080, 310598401, 607225278, 1426881987, 1925078388, 2162078206, 2614888103, 3248222580,
        3835390401, 4022224774, 264347078, 604807628, 770255983, 1249150122, 1555081692, 1996064986,
        2554220882, 2821834349, 2952996808, 3210313671, 3336571891, 3584528711, 113926993, 338241895,
        666307205, 773529912, 1294757372, 1396182291, 1695183700, 1986661051, 2177026350, 2456956037,
        2730485921, 2820302411, 3259730800, 3345764771, 3516065817, 3600352804, 4094571909, 275423344,
        430227734, 506948616, 659060556, 883997877, 958139571, 1322822218, 1537002063, 1747873779,
        1955562222, 2024104815, 2227730452, 2361852424, 2428436474, 2756734187, 3204031479, 3329325298
    ];
    var l = msgBytes.length;
    var bitLen = l * 8;
    var withOne = msgBytes.slice();
    withOne.push(0x80);
    while (withOne.length % 64 !== 56) withOne.push(0);
    // 追加 64 位长度（高32位这里按 0 处理足够，本场景数据很短）
    for (var hi = 0; hi < 4; hi++) withOne.push(0);
    withOne.push((bitLen >>> 24) & 0xff, (bitLen >>> 16) & 0xff, (bitLen >>> 8) & 0xff, bitLen & 0xff);

    var w = new Array(64);
    for (var off = 0; off < withOne.length; off += 64) {
        for (var t = 0; t < 16; t++) {
            w[t] = (withOne[off + t * 4] << 24) | (withOne[off + t * 4 + 1] << 16) |
                   (withOne[off + t * 4 + 2] << 8) | (withOne[off + t * 4 + 3]);
            w[t] >>>= 0;
        }
        for (var t2 = 16; t2 < 64; t2++) {
            var s0 = rotr(w[t2 - 15], 7) ^ rotr(w[t2 - 15], 18) ^ (w[t2 - 15] >>> 3);
            var s1 = rotr(w[t2 - 2], 17) ^ rotr(w[t2 - 2], 19) ^ (w[t2 - 2] >>> 10);
            w[t2] = (w[t2 - 16] + s0 + w[t2 - 7] + s1) >>> 0;
        }
        var a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
        for (var i2 = 0; i2 < 64; i2++) {
            var S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
            var ch = (e & f) ^ (~e & g);
            var temp1 = (h + S1 + ch + K[i2] + w[i2]) >>> 0;
            var S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
            var maj = (a & b) ^ (a & c) ^ (b & c);
            var temp2 = (S0 + maj) >>> 0;
            h = g; g = f; f = e; e = (d + temp1) >>> 0;
            d = c; c = b; b = a; a = (temp1 + temp2) >>> 0;
        }
        H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0; H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
        H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0; H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0;
    }
    var hex = "";
    for (var j = 0; j < 8; j++) {
        var hv = H[j].toString(16);
        while (hv.length < 8) hv = "0" + hv;
        hex += hv;
    }
    return hex.toUpperCase();
}

// 16 字节随机 nonce -> hex
function randomNonceHex() {
    var bytes = [];
    for (var i = 0; i < 16; i++) {
        bytes.push(Math.floor(Math.random() * 256));
    }
    // 若环境有 crypto.getRandomValues 则优先使用（更随机，但非必需）
    try {
        var g = (typeof globalThis !== "undefined") ? globalThis : this;
        if (g && g.crypto && g.crypto.getRandomValues) {
            var arr = new Uint8Array(16);
            g.crypto.getRandomValues(arr);
            bytes = Array.prototype.slice.call(arr);
        }
    } catch (e) {}
    var hex = "";
    for (var k = 0; k < bytes.length; k++) {
        var h = (bytes[k] & 0xff).toString(16);
        if (h.length < 2) h = "0" + h;
        hex += h;
    }
    return hex;
}

// protobuf varint 编码（用普通数字，本场景数值不超过 2^53）
function varintBytes(num) {
    var out = [];
    var n = num;
    while (n >= 0x80) {
        out.push((n & 0x7f) | 0x80);
        n = Math.floor(n / 128);
    }
    out.push(n & 0x7f);
    return out;
}
function pbFieldStr(fieldNo, str) {
    var b = strToUtf8Bytes(str);
    return [].concat(varintBytes((fieldNo << 3) | 2), varintBytes(b.length), b);
}
function pbFieldVarint(fieldNo, val) {
    return [].concat(varintBytes((fieldNo << 3) | 0), varintBytes(val));
}

// 构造 decode/url 的 protobuf 请求体（字节数组）
function buildDecodeReqBytes(url, vodFrom, timestamp, nonce, signature) {
    return [].concat(
        pbFieldStr(1, url),
        pbFieldStr(2, vodFrom),
        pbFieldVarint(3, timestamp),
        pbFieldStr(4, nonce),
        pbFieldStr(5, signature),
        pbFieldStr(6, APP.appId),
        pbFieldVarint(7, APP.appVersion)
    );
}

// 解析 decode/url 的 protobuf 响应，取 field 3(data)=真实地址；field 1(code) 应为 1
function parseDecodeRespBytes(bytes) {
    var i = 0, len = bytes.length;
    var result = { code: 0, msg: "", data: "" };
    function readVarint() {
        var shift = 0, val = 0;
        while (i < len) {
            var b = bytes[i++] & 0xff;
            val += (b & 0x7f) * Math.pow(2, shift);
            if ((b & 0x80) === 0) break;
            shift += 7;
        }
        return val;
    }
    while (i < len) {
        var key = readVarint();
        var fieldNo = key >>> 3;
        var wireType = key & 0x7;
        if (wireType === 0) {
            var v = readVarint();
            if (fieldNo === 1) result.code = v;
        } else if (wireType === 2) {
            var l = readVarint();
            var slice = bytes.slice(i, i + l);
            i += l;
            var s = utf8BytesToStr(slice);
            if (fieldNo === 2) result.msg = s;
            else if (fieldNo === 3) result.data = s;
        } else if (wireType === 5) { i += 4; }
        else if (wireType === 1) { i += 8; }
        else { break; }
    }
    return result;
}

/* ---------------- 解密请求 ---------------- */

// 生成签名参数
function buildSign() {
    var timestamp = Date.now();
    var nonce = randomNonceHex();
    var signStr = [
        "finger=" + APP.finger,
        "id=" + APP.appId,
        "nonce=" + nonce,
        "sk=" + APP.secretKey,
        "time=" + timestamp,
        "v=" + APP.appVersion
    ].join("&");
    var signature = sha256Hex(strToUtf8Bytes(signStr));
    return { timestamp: timestamp, nonce: nonce, signature: signature };
}

// 把字节数组编码为 latin1 字符串（用于 req 的 body 传输）
function bytesToLatin1(bytes) {
    var s = "";
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i] & 0xff);
    return s;
}

// base64 解码为字节数组（FongMi buffer:2 返回 base64 字符串）
var B64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
function base64ToBytes(b64) {
    var lookup = {};
    for (var i = 0; i < B64_CHARS.length; i++) lookup[B64_CHARS.charAt(i)] = i;
    b64 = toStr(b64).replace(/[^A-Za-z0-9+/]/g, "");
    var out = [];
    var buf = 0, bits = 0;
    for (var k = 0; k < b64.length; k++) {
        var c = lookup[b64.charAt(k)];
        if (c === undefined) continue;
        buf = (buf << 6) | c;
        bits += 6;
        if (bits >= 8) { bits -= 8; out.push((buf >> bits) & 0xff); }
    }
    return out;
}

// 把响应内容规整成字节数组。兼容多种 TVBox 分支：
//  - FongMi buffer:2 -> res.content 是 base64 字符串
//  - buffer:1        -> res.content 是有符号字节数组
//  - 其它            -> latin1 字符串
function respToBytes(res, isBase64) {
    if (res == null) return [];
    var body = (typeof res === "string") ? res : (res.content !== undefined ? res.content : (res.body || res.data || ""));
    if (Array.isArray(body)) {
        var arr = [];
        for (var a = 0; a < body.length; a++) arr.push(body[a] & 0xff);
        return arr;
    }
    if (typeof body === "string") {
        if (isBase64) {
            // 优先按 base64 解（FongMi buffer:2）
            var dec = base64ToBytes(body);
            if (dec.length) return dec;
        }
        var bytes = [];
        for (var i = 0; i < body.length; i++) bytes.push(body.charCodeAt(i) & 0xff);
        return bytes;
    }
    if (body && body.length !== undefined) {
        var out = [];
        for (var j = 0; j < body.length; j++) out.push(body[j] & 0xff);
        return out;
    }
    return [];
}

// 调 /decode/url 解密单个加密串，返回真实地址或空字符串
function decodeEncrypted(encUrl, vodFrom) {
    try {
        var sign = buildSign();
        var payload = buildDecodeReqBytes(encUrl, vodFrom, sign.timestamp, sign.nonce, sign.signature);
        var headers = {
            "Content-Type": "application/x-protobuf; charset=ISO-8859-1",
            "Accept": "application/x-protobuf",
            "x-platform": "web",
            "X-Client": "YOUR_PUBLIC_CLIENT_ID",
            "Referer": HOST + "/",
            "Origin": HOST,
            "User-Agent": UA
        };
        var bodyStr = bytesToLatin1(payload);
        log("decode try vodFrom=" + vodFrom + " payloadLen=" + payload.length + " bodyLen=" + bodyStr.length);
        var res = req(API + "/decode/url", {
            method: "POST",
            headers: headers,
            body: bodyStr,
            buffer: 2,
            timeout: 10000
        });
        var code = res && res.code !== undefined ? res.code : "?";
        var respBytes = respToBytes(res, true);
        log("decode http=" + code + " respBytes=" + respBytes.length);
        var parsed = parseDecodeRespBytes(respBytes);
        log("decode vodFrom=" + vodFrom + " pbcode=" + parsed.code + " msg=" + parsed.msg + " data=" + parsed.data.slice(0, 60));
        if (parsed.code === 1 && isPlayableUrl(parsed.data)) return parsed.data;
        return "";
    } catch (e) {
        log("decode_error " + e);
        return "";
    }
}

/* ---------------- 接口实现 ---------------- */

function init(ext) {
    if (typeof ext === "string" && /^https?:\/\//.test(ext.trim())) {
        HOST = ext.trim().replace(/\/+$/, "");
        API = HOST + "/api.php/web";
        HEADERS.Referer = HOST + "/";
        HEADERS.Origin = HOST;
    }
    CLASSES = [];
    FILTERS = {};
    TYPE_NAME = {};
    var data = requestJson(API + "/index/home");
    var d = data.data || {};
    (d.categories || []).forEach(function (c) {
        var tid = toStr(c.type_id);
        CLASSES.push({ type_id: tid, type_name: c.type_name });
        TYPE_NAME[tid] = c.type_name;
        var opts = c.filter_options || {};
        var arr = [];
        function pushFilter(key, name, values) {
            if (!values || !values.length) return;
            var vlist = [{ n: "全部", v: "" }];
            values.forEach(function (x) { vlist.push({ n: x, v: x }); });
            arr.push({ key: key, name: name, value: vlist });
        }
        pushFilter("class", "类型", opts["class"]);
        pushFilter("area", "地区", opts.area);
        pushFilter("year", "年份", opts.year);
        if (arr.length) FILTERS[tid] = arr;
    });
    log("init host=" + HOST + " classes=" + CLASSES.length);
}

function home(filter) {
    log("home");
    if (!CLASSES.length) init();
    return JSON.stringify({ class: CLASSES, filters: FILTERS });
}

function homeVod() {
    log("homeVod");
    var data = requestJson(API + "/index/home");
    var d = data.data || {};
    var list = (d.recommend || []).map(formatVod);
    return JSON.stringify({ list: list });
}

function category(tid, pg, filter, extend) {
    tid = toStr(tid || "");
    pg = parseInt(pg || 1);
    if (!pg || pg < 1) pg = 1;
    extend = extend || {};

    if (!TYPE_NAME[tid] && !CLASSES.length) init();
    var typeName = TYPE_NAME[tid] || "";

    var params = ["page=" + pg, "sort=hits"];
    if (typeName) params.push("type_name=" + encode(typeName));
    else params.push("type_id=" + encode(tid));
    if (extend["class"]) params.push("class=" + encode(extend["class"]));
    if (extend.area) params.push("area=" + encode(extend.area));
    if (extend.year) params.push("year=" + encode(extend.year));

    var data = requestJson(API + "/filter/vod?" + params.join("&"));
    var list = (data.data || []).map(formatVod);
    var page = parseInt(data.page || pg) || 1;
    var pagecount = parseInt(data.pageCount || (list.length >= (data.limit || 18) ? page + 1 : page)) || page;

    log("category tid=" + tid + " name=" + typeName + " pg=" + pg + " count=" + list.length);
    return JSON.stringify({
        page: page,
        pagecount: pagecount,
        limit: parseInt(data.limit || 24) || 24,
        total: parseInt(data.total || list.length) || list.length,
        list: list
    });
}

function detail(id) {
    var vid = toStr(id).split(",")[0];
    log("detail id=" + vid);
    var data = requestJson(API + "/vod/get_detail?vod_id=" + encode(vid));
    var arr = data.data || [];
    if (!arr.length) return JSON.stringify({ list: [] });
    var v = arr[0];

    var vod = {
        vod_id: v.vod_id,
        vod_name: v.vod_name,
        vod_pic: v.vod_pic,
        vod_remarks: v.vod_remarks || "",
        vod_year: toStr(v.vod_year),
        vod_area: joinField(v.vod_area),
        vod_lang: toStr(v.vod_lang),
        type_name: joinField(v.vod_class),
        vod_actor: joinField(v.vod_actor),
        vod_director: joinField(v.vod_director),
        vod_content: textClean(v.vod_content)
    };

    // vod_play_from ($$$分隔线路代号)，vod_play_url ($$$分隔线路，#分隔集，集名$地址)
    // 保留全部线路：明文直链原样保留；加密串（如 vwnet-xxx）编码线路代号后交给 play 解密。
    // 线路显示名优先用 vodplayer[].show（中文名，如 云播/YY蓝光/CK蓝光），回落到代号。
    var showMap = {};
    var vodplayer = data.vodplayer || [];
    for (var vp = 0; vp < vodplayer.length; vp++) {
        var pf = vodplayer[vp];
        if (pf && pf.from) showMap[pf.from] = pf.show || pf.from;
    }

    var froms = toStr(v.vod_play_from).split("$$$");
    var urls = toStr(v.vod_play_url).split("$$$");
    var playFrom = [];
    var playUrl = [];
    var usedName = {};

    for (var i = 0; i < urls.length; i++) {
        var code = froms[i] || ("线路" + (i + 1));           // 原始代号（解密用）
        var baseName = showMap[code] || code;                 // 中文显示名
        // 防止重名导致 TVBox 线路合并
        var showName = baseName;
        if (usedName[baseName]) showName = baseName + (usedName[baseName] + 1);
        usedName[baseName] = (usedName[baseName] || 0) + 1;

        var eps = urls[i].split("#");
        var kept = [];
        for (var j = 0; j < eps.length; j++) {
            var seg = eps[j];
            if (!seg) continue;
            var pos = seg.indexOf("$");
            if (pos < 0) continue;
            var title = seg.substring(0, pos).trim();
            var url = seg.substring(pos + 1).trim();
            if (!url) continue;
            if (isPlayableUrl(url)) {
                // 明文直链
                kept.push(title + "$" + url);
            } else {
                // 加密串：带上原始代号，格式 enc::code::原串，play 阶段解密
                kept.push(title + "$" + "enc::" + code + "::" + url);
            }
        }
        if (kept.length) {
            playFrom.push(showName);
            playUrl.push(kept.join("#"));
        }
    }

    if (playFrom.length) {
        vod.vod_play_from = playFrom.join("$$$");
        vod.vod_play_url = playUrl.join("$$$");
    } else {
        vod.vod_play_from = "提示";
        vod.vod_play_url = "暂无播放源$";
    }

    return JSON.stringify({ list: [vod] });
}

function play(flag, id, flags) {
    var raw = toStr(id);
    log("play flag=" + flag + " id=" + raw.slice(0, 80));

    var url = raw;
    // 加密串：enc::vodFrom::原串
    if (raw.indexOf("enc::") === 0) {
        var rest = raw.substring(5);
        var sep = rest.indexOf("::");
        var vodFrom = sep >= 0 ? rest.substring(0, sep) : (flag || "");
        var encStr = sep >= 0 ? rest.substring(sep + 2) : rest;
        var real = decodeEncrypted(encStr, vodFrom);
        if (real) {
            url = real;
        } else {
            // 解密失败兜底：交给播放器/解析
            return JSON.stringify({ parse: 1, url: encStr, header: { "User-Agent": UA, "Referer": HOST + "/" } });
        }
    }

    var header = /\.(m3u8|mp4|flv|ts)(\?|$)/i.test(url) ? { "User-Agent": UA, "Referer": HOST + "/" } : undefined;
    return JSON.stringify({ parse: 0, url: url, header: header });
}

function search(wd, quick, pg) {
    if (pg >= 2) {
        return JSON.stringify({ list: [], pagecount: 1 });
    }

    try {
        var url = API + "/search/index?wd=" + encode(wd) + "&page=1&limit=15";
        log("search url=" + url);

        // 直接用req，不用requestJson，兼容影视仓
        var h = {};
        for (var k in HEADERS) h[k] = HEADERS[k];
        var res = req(url, { method: "GET", headers: h, timeout: 8000 });
        var body = (typeof res === "string") ? res : (res && (res.content || res.body || res.data));

        if (typeof body !== "string" || !body) {
            log("search empty response");
            return JSON.stringify({ list: [], pagecount: 1 });
        }

        var data;
        try {
            data = JSON.parse(body);
        } catch (e) {
            log("search json parse error: " + e);
            return JSON.stringify({ list: [], pagecount: 1 });
        }

        var list = (data.data || []).map(formatVod);
        log("search result count=" + list.length);

        return JSON.stringify({
            list: list,
            pagecount: 1
        });
    } catch (e) {
        log("search error: " + e);
        return JSON.stringify({ list: [], pagecount: 1 });
    }
}

/* ---------------- 导出 ---------------- */

__JS_SPIDER__ = {
    init: init,
    home: home,
    homeVod: homeVod,
    category: category,
    detail: detail,
    play: play,
    search: search
};
