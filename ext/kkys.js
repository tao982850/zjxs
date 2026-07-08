/*
 * @File   : 可可影视.js
 * @Author : opencode
 * @Date   : 2026-07-08
 * @Desc   : 可可影视 (kkys01.com) TVBox T4(JS) 源 —— 自包含，无外部依赖
 *
 * 站点特征：
 *  - 服务端渲染的非标 MacCMS（自定义模板），HTML 解析。
 *  - 有 cdndefend 防护盾：首次请求返回 HTTP 850 + 一段 SHA1 PoW 挑战 JS，
 *    算出 cdndefend_js_cookie 后带上即可放行。本源内置纯 JS SHA1 复现该 PoW。
 *      挑战算法（去混淆）：
 *        seed = 页面里的 40 位 HEX 种子；n1 = parseInt(seed[0], 16)
 *        枚举 i=0,1,2...  直到 sha1_bytes(seed + i)[n1]==0xb0 且 [n1+1]==0x0b
 *        cookie 值 = seed + i
 *  - 分类：/channel/{tid}.html?page={pg}
 *  - 详情：/detail/{id}.html  （线路 .source-item-label，集数 .episode-list/.episode-item）
 *  - 播放：/play/{id}-{sid}-{eid}.html  页面里 const playSource = { src: "https://...m3u8" } 明文直链
 *  - 搜索：/search?k={词}&t={固定token}
 */

var KKYS_VERSION = "20260708-js-3";
var HOST = "https://www.kkys01.com";
var UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";
var SEARCH_TOKEN = "qRFNl5N8XwhSO0I8cY/+ww==";   // 搜索 token 会轮换，运行时从首页刷新

var CDN_COOKIE = "";   // 过盾 cookie 值（运行时算出）
var RULE_KEY = "kkys_cdn";

var CLASSES = [
    { type_id: "1", type_name: "电影" },
    { type_id: "2", type_name: "连续剧" },
    { type_id: "3", type_name: "动漫" },
    { type_id: "4", type_name: "综艺纪录" },
    { type_id: "6", type_name: "短剧" }
];
var FILTERS = {};
var FILTER_CLASS = ["剧情", "喜剧", "动作", "爱情", "恐怖", "惊悚", "犯罪", "科幻", "悬疑", "奇幻", "冒险", "战争", "历史", "古装", "家庭", "传记", "武侠", "动画", "儿童", "职场"];
var FILTER_AREA = ["中国大陆", "中国香港", "中国台湾", "美国", "日本", "韩国", "英国", "法国", "德国", "印度", "泰国", "丹麦", "瑞典", "巴西", "加拿大", "俄罗斯", "意大利", "西班牙", "澳大利亚", "其他"];
var FILTER_LANG = ["国语", "粤语", "英语", "日语", "韩语", "法语", "其他"];
var FILTER_YEAR = ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2010_2019", "2000_2009", "1990_1999", "1980_1989", "0_1979"];

function log(msg) {
    try { console.log("[KKYS_JS " + KKYS_VERSION + "] " + msg); } catch (e) {}
}

/* ---------------- 通用工具 ---------------- */

function toStr(v) { return v === undefined || v === null ? "" : String(v); }
function encode(s) { return encodeURIComponent(toStr(s)); }
function decodeUrl(s) {
    s = toStr(s).replace(/&amp;/g, "&");
    try { return decodeURIComponent(s); } catch (e) { return s; }
}

function fixUrl(u) {
    u = toStr(u).trim();
    if (!u) return "";
    if (u.indexOf("//") === 0) return "https:" + u;
    if (u.charAt(0) === "/") return HOST + u;
    return u;
}

// 封面图独立 CDN（主站 /vod1/... 有防盗链，须走图片 CDN vres.zyxpedu.com）
var IMG_HOST = "https://vres.zyxpedu.com";
function fixPic(u) {
    u = toStr(u).trim();
    if (!u) return "";
    if (u.indexOf("//") === 0) return "https:" + u;
    if (u.charAt(0) === "/") return IMG_HOST + u;   // /vod1/... -> 图片CDN
    return u;
}

function textClean(s) {
    return toStr(s)
        .replace(/<[^>]+>/g, "")
        .replace(/&nbsp;/g, " ")
        .replace(/&amp;/g, "&")
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&#\d+;/g, "")
        .replace(/\s+/g, " ")
        .trim();
}

function attr(tag, name) {
    var r = new RegExp(name + "\\s*=\\s*([\"'])([\\s\\S]*?)\\1", "i");
    var m = r.exec(tag || "");
    return m ? m[2] : "";
}

function filterValues(values, allName) {
    var out = [{ n: allName || "全部", v: "" }];
    for (var i = 0; i < values.length; i++) {
        var name = values[i];
        if (name === "2010_2019") name = "10年代";
        else if (name === "2000_2009") name = "00年代";
        else if (name === "1990_1999") name = "90年代";
        else if (name === "1980_1989") name = "80年代";
        else if (name === "0_1979") name = "更早";
        out.push({ n: name, v: values[i] });
    }
    return out;
}

function buildFilters() {
    var ret = {};
    for (var i = 0; i < CLASSES.length; i++) {
        ret[CLASSES[i].type_id] = [
            { key: "class", name: "类型", value: filterValues(FILTER_CLASS) },
            { key: "area", name: "地区", value: filterValues(FILTER_AREA) },
            { key: "lang", name: "语言", value: filterValues(FILTER_LANG) },
            { key: "year", name: "年份", value: filterValues(FILTER_YEAR) },
            { key: "sort", name: "排序", value: [{ n: "综合", v: "1" }, { n: "最新", v: "2" }, { n: "最热", v: "3" }, { n: "评分", v: "4" }] }
        ];
    }
    return ret;
}

function parseExtend(extend) {
    if (!extend) return {};
    if (typeof extend === "string") {
        try { return JSON.parse(extend); } catch (e) { return {}; }
    }
    return extend;
}

function extValue(extend, key) {
    var v = extend && (extend[key] || extend[encodeURIComponent(key)]);
    return v ? toStr(v) : "";
}

function showUrl(tid, pg, extend) {
    var seg = [
        toStr(tid),
        extValue(extend, "class") || extValue(extend, "genre"),
        extValue(extend, "area"),
        extValue(extend, "lang"),
        extValue(extend, "year"),
        extValue(extend, "sort") || "1",
        toStr(pg)
    ];
    for (var i = 0; i < seg.length; i++) seg[i] = encode(seg[i]);
    return HOST + "/show/" + seg.join("-") + ".html";
}

function extractSearchToken(html) {
    var m = /<input\b[^>]*name=["']t["'][^>]*value=["']([^"']+)["']/i.exec(html || "");
    if (!m) m = /<input\b[^>]*value=["']([^"']+)["'][^>]*name=["']t["']/i.exec(html || "");
    if (!m) m = /\/search\?k=[^"']*?(?:&amp;|&)t=([^"'&]+)/i.exec(html || "");
    return m ? decodeUrl(m[1]) : "";
}

function getSearchToken() {
    var html = getHtml(HOST + "/");
    var token = extractSearchToken(html);
    if (token) SEARCH_TOKEN = token;
    return SEARCH_TOKEN;
}

function searchPageCount(html, pg, limit) {
    var m = /找到<span class="highlight-text">\s*(\d+)\s*<\/span>/i.exec(html || "");
    if (m) return Math.max(pg, Math.ceil(parseInt(m[1]) / limit) || pg);
    return (html || "").indexOf("page-item-next") >= 0 ? pg + 1 : pg;
}

/* ============================================================
 *  SHA1（纯 JS，字节数组输出）—— 用于 cdndefend PoW
 * ============================================================ */

function strToUtf8Bytes(str) {
    var bytes = [];
    for (var i = 0; i < str.length; i++) {
        var c = str.charCodeAt(i);
        if (c < 0x80) bytes.push(c);
        else if (c < 0x800) bytes.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f));
        else if (c >= 0xd800 && c <= 0xdbff) {
            var c2 = str.charCodeAt(++i);
            var cp = 0x10000 + ((c & 0x3ff) << 10) + (c2 & 0x3ff);
            bytes.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 0x3f), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
        } else bytes.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
    }
    return bytes;
}

// SHA1，输入字节数组，输出 20 字节数组
function sha1Bytes(msgBytes) {
    function rol(n, s) { return ((n << s) | (n >>> (32 - s))) >>> 0; }
    var h0 = 0x67452301, h1 = 0xEFCDAB89, h2 = 0x98BADCFE, h3 = 0x10325476, h4 = 0xC3D2E1F0;
    var l = msgBytes.length;
    var bitLen = l * 8;
    var withOne = msgBytes.slice();
    withOne.push(0x80);
    while (withOne.length % 64 !== 56) withOne.push(0);
    // 64 位长度（高 32 位按 0，数据长度远小于 2^32）
    withOne.push(0, 0, 0, 0);
    withOne.push((bitLen >>> 24) & 0xff, (bitLen >>> 16) & 0xff, (bitLen >>> 8) & 0xff, bitLen & 0xff);

    var w = new Array(80);
    for (var off = 0; off < withOne.length; off += 64) {
        for (var t = 0; t < 16; t++) {
            w[t] = ((withOne[off + t * 4] << 24) | (withOne[off + t * 4 + 1] << 16) |
                    (withOne[off + t * 4 + 2] << 8) | (withOne[off + t * 4 + 3])) >>> 0;
        }
        for (var t2 = 16; t2 < 80; t2++) {
            w[t2] = rol(w[t2 - 3] ^ w[t2 - 8] ^ w[t2 - 14] ^ w[t2 - 16], 1);
        }
        var a = h0, b = h1, c = h2, d = h3, e = h4;
        for (var i = 0; i < 80; i++) {
            var f, k;
            if (i < 20) { f = (b & c) | (~b & d); k = 0x5A827999; }
            else if (i < 40) { f = b ^ c ^ d; k = 0x6ED9EBA1; }
            else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8F1BBCDC; }
            else { f = b ^ c ^ d; k = 0xCA62C1D6; }
            var tmp = (rol(a, 5) + f + e + k + w[i]) >>> 0;
            e = d; d = c; c = rol(b, 30); b = a; a = tmp;
        }
        h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0; h4 = (h4 + e) >>> 0;
    }
    var out = [];
    [h0, h1, h2, h3, h4].forEach(function (h) {
        out.push((h >>> 24) & 0xff, (h >>> 16) & 0xff, (h >>> 8) & 0xff, h & 0xff);
    });
    return out;
}

// 解 cdndefend PoW：给定种子，返回 cookie 值（seed+i）
function solveChallenge(seed) {
    var n1 = parseInt(seed.charAt(0), 16);
    var i = 0;
    // 上限保护，正常几万次内命中
    while (i < 9000000) {
        var s = sha1Bytes(strToUtf8Bytes(seed + i));
        if (s[n1] === 0xb0 && s[n1 + 1] === 0x0b) return seed + i;
        i++;
    }
    return "";
}

/* ---------------- cookie 持久化 ---------------- */

function loadCookie() {
    if (CDN_COOKIE) return CDN_COOKIE;
    try {
        if (typeof local !== "undefined" && local.get) {
            var c = local.get(RULE_KEY, "cdn_cookie");
            if (c) { CDN_COOKIE = c; return c; }
        }
    } catch (e) {}
    return CDN_COOKIE;
}
function saveCookie(c) {
    CDN_COOKIE = c;
    try {
        if (typeof local !== "undefined" && local.set) local.set(RULE_KEY, "cdn_cookie", c);
    } catch (e) {}
}

/* ---------------- 请求（自动过盾） ---------------- */

function rawReq(url, cookie) {
    var headers = {
        "User-Agent": UA,
        "Referer": HOST + "/",
        "Accept": "text/html,application/xhtml+xml"
    };
    if (cookie) headers["Cookie"] = "cdndefend_js_cookie=" + cookie;
    var res = req(url, { method: "GET", headers: headers, timeout: 10000 });
    var code = (res && res.code !== undefined) ? res.code : 200;
    var body = (typeof res === "string") ? res : (res && (res.content || res.body || res.data)) || "";
    return { code: code, body: toStr(body) };
}

// 判断是否是 cdndefend 挑战页
function isChallenge(body) {
    return body.indexOf("cdndefend") >= 0 && body.indexOf("cdndefend_js_cookie=") >= 0;
}

// 从挑战页提取 40 位 HEX 种子
function extractSeed(body) {
    var m = body.match(/'([0-9A-F]{40})'/);
    return m ? m[1] : "";
}

// 带过盾的 GET，返回 HTML
function getHtml(url) {
    var cookie = loadCookie();
    var r = rawReq(url, cookie);
    // 850 或 命中挑战页 -> 解挑战重试
    if (r.code === 850 || isChallenge(r.body)) {
        var seed = extractSeed(r.body);
        if (!seed) {
            // 有时 850 的 body 需要单独取；再请求一次首页拿种子
            var r0 = rawReq(HOST + "/", "");
            seed = extractSeed(r0.body);
        }
        if (seed) {
            var newCookie = solveChallenge(seed);
            if (newCookie) {
                saveCookie(newCookie);
                log("cdndefend solved cookie=" + newCookie.slice(0, 24) + "...");
                r = rawReq(url, newCookie);
                // 若仍是挑战（cookie 过期/种子换了），再解一次
                if (r.code === 850 || isChallenge(r.body)) {
                    var seed2 = extractSeed(r.body);
                    if (seed2) {
                        var c2 = solveChallenge(seed2);
                        if (c2) { saveCookie(c2); r = rawReq(url, c2); }
                    }
                }
            }
        }
    }
    return r.body;
}

/* ---------------- 解析 ---------------- */

// 解析影片列表卡片（分类/首页 v-item 与 搜索 search-result-item 通用）
function parseList(html) {
    var list = [];
    var seen = {};
    if (!html) return list;

    // ---- 分类/首页卡片：<a href="/detail/xxx.html" class="v-item"> ... </a></div> ----
    var re = /<a\s+href="\/detail\/(\d+)\.html"\s+class="v-item">([\s\S]*?)<\/a>\s*<\/div>/g;
    var m;
    while ((m = re.exec(html)) !== null) {
        var id = m[1];
        if (seen[id]) continue;
        seen[id] = true;
        var block = m[2];

        var pic = pickCover(block);

        var remark = "";
        var rm = /class="v-item-bottom"[\s\S]*?<span>([\s\S]*?)<\/span>/.exec(block);
        if (rm) remark = textClean(rm[1]);

        var name = "";
        var titleRe = /<div class="v-item-title"([^>]*)>([\s\S]*?)<\/div>/g;
        var tm;
        while ((tm = titleRe.exec(block)) !== null) {
            if (/display:\s*none/.test(tm[1])) continue;
            var t = textClean(tm[2]);
            if (!t || /kekys|可可影视/.test(t)) continue;
            name = t; break;
        }
        if (!name) continue;

        list.push({ vod_id: id, vod_name: name, vod_pic: fixPic(pic), vod_remarks: remark });
    }
    if (list.length) return list;

    // ---- 搜索卡片：<a href="/detail/xxx.html" class="search-result-item"> ... ----
    var sre = /<a\s+href="\/detail\/(\d+)\.html"\s+class="search-result-item">([\s\S]*?)<div class="title">([\s\S]*?)<\/div>([\s\S]*?)<\/a>/g;
    var sm;
    while ((sm = sre.exec(html)) !== null) {
        var sid = sm[1];
        if (seen[sid]) continue;
        seen[sid] = true;
        var head = sm[2];
        var sname = textClean(sm[3]);
        if (!sname) continue;

        var spic = pickCover(head);
        // 备注：header 里的分类 或 tags 第一项
        var sremark = "";
        var hm = /class="search-result-item-header"[\s\S]*?<div>([\s\S]*?)<\/div>/.exec(head);
        if (hm) sremark = textClean(hm[1]);

        list.push({ vod_id: sid, vod_name: sname, vod_pic: fixPic(spic), vod_remarks: sremark });
    }
    return list;
}

// 从卡片 HTML 里挑真实封面（跳过 logo 占位图）
function pickCover(block) {
    var imgs = block.match(/data-original="([^"]+)"/g) || [];
    for (var k = 0; k < imgs.length; k++) {
        var u = imgs[k].replace(/data-original="([^"]+)"/, "$1");
        if (u.indexOf("logo_placeholder") < 0 && u.indexOf("logo.png") < 0 && u.indexOf("empty-box") < 0) return u;
    }
    return "";
}

/* ---------------- 接口实现 ---------------- */

function init(ext) {
    if (typeof ext === "string" && /^https?:\/\//.test(ext.trim())) {
        HOST = ext.trim().replace(/\/+$/, "");
    }
    FILTERS = buildFilters();
    // 预热：过一次盾
    loadCookie();
    try { getHtml(HOST + "/"); } catch (e) { log("init warm error " + e); }
    log("init host=" + HOST);
}

function home(filter) {
    log("home");
    return JSON.stringify({ class: CLASSES, filters: FILTERS });
}

function homeVod() {
    log("homeVod");
    var html = getHtml(HOST + "/");
    var list = parseList(html).slice(0, 40);
    return JSON.stringify({ list: list });
}

function category(tid, pg, filter, extend) {
    tid = toStr(tid || "1");
    pg = parseInt(pg || 1);
    if (!pg || pg < 1) pg = 1;
    extend = parseExtend(extend);

    // 可可影视格式：/show/{tid}-{类型}-{地区}-{语言}-{年份}-{排序}-{页}.html
    var url = showUrl(tid, pg, extend);
    var html = getHtml(url);
    var list = parseList(html);
    // 每页满 18 视为有下一页
    var pagecount = list.length >= 18 ? pg + 1 : pg;

    log("category tid=" + tid + " pg=" + pg + " count=" + list.length);
    return JSON.stringify({
        page: pg,
        pagecount: pagecount,
        limit: list.length || 18,
        total: pagecount * 18,
        list: list
    });
}

function detail(id) {
    var vid = toStr(id).split(",")[0].replace(/[^\d]/g, "");
    log("detail id=" + vid);
    var html = getHtml(HOST + "/detail/" + vid + ".html");
    if (!html) return JSON.stringify({ list: [] });

    // 基本信息
    var name = textClean((/<h1[^>]*>([\s\S]*?)<\/h1>/.exec(html) || [])[1] || "");
    name = name.replace(/𝕜𝕜𝕪𝕤𝟘𝟙\.𝕔𝕠𝕞/g, "").replace(/可可影视[^ ]*/g, "").trim();
    if (!name) {
        var tm = /<title>([^<]+?)-/.exec(html);
        if (tm) name = tm[1].trim();
    }
    var pic = "";
    var pm = /class="detail-pic"[\s\S]*?data-original="([^"]+)"/.exec(html) || /<img[^>]+class="[^"]*cover[^"]*"[^>]+data-original="([^"]+)"/.exec(html);
    if (pm) pic = pm[1];

    var desc = textClean((/class="[^"]*(detail-desc|content-desc|desc-text|vod-content)[^"]*"[^>]*>([\s\S]*?)<\/div>/.exec(html) || [])[2] || "");

    var vod = {
        vod_id: vid,
        vod_name: name,
        vod_pic: fixPic(pic),
        vod_content: desc
    };

    // 线路名（按顺序）
    var froms = [];
    var lm = /source-item-label">([^<]+)</g;
    var fm;
    while ((fm = lm.exec(html)) !== null) froms.push(textClean(fm[1]));

    // 集数分组：每个 <div class="episode-list"> ... </div> 对应一条线路（顺序一致）
    var playFrom = [];
    var playUrl = [];
    var listRe = /<div class="episode-list"[^>]*>([\s\S]*?)<\/div>/g;
    var lgm;
    var idx = 0;
    while ((lgm = listRe.exec(html)) !== null) {
        var block = lgm[1];
        var eps = [];
        var epRe = /<a\s+href="(\/play\/[^"]+\.html)"[^>]*>([\s\S]*?)<\/a>/g;
        var em;
        while ((em = epRe.exec(block)) !== null) {
            var epUrl = em[1];
            var epName = textClean(em[2]) || (eps.length + 1);
            eps.push(epName + "$" + epUrl);
        }
        if (eps.length) {
            var fromName = froms[idx] || ("线路" + (idx + 1));
            playFrom.push(fromName);
            playUrl.push(eps.join("#"));
        }
        idx++;
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
    var pageUrl = fixUrl(id);
    log("play flag=" + flag + " url=" + pageUrl);
    var html = getHtml(pageUrl);

    // 部分线路（如"超清1"）的 playSource 用 \uXXXX 转义混淆，先整体解码
    var decoded = html.replace(/\\u([0-9a-fA-F]{4})/g, function (mm, h) {
        return String.fromCharCode(parseInt(h, 16));
    });

    // 播放页里 playSource = { src: "https://...m3u8" }（key/值可能带引号）
    var url = "";
    var m = /playSource\s*=\s*\{[\s\S]{0,200}?['"]?src['"]?\s*:\s*"([^"]*)"/.exec(decoded);
    if (m) url = m[1];
    if (!url) {
        var m2 = /"?url"?\s*[:=]\s*"([^"]+\.(?:m3u8|mp4)[^"]*)"/i.exec(decoded);
        if (m2) url = m2[1];
    }
    if (!url) {
        var m3 = decoded.match(/https?:\/\/[^"'\s\\]+?\.m3u8[^"'\s\\]*/);
        if (m3) url = m3[0];
    }
    url = url.replace(/\\\//g, "/").trim();

    if (url && /^https?:\/\//.test(url)) {
        var header = { "User-Agent": UA, "Referer": HOST + "/" };
        return JSON.stringify({ parse: 0, url: url, header: header });
    }

    // src 为空的线路（如"4K"）为 APP 独占，网页端不下发地址 —— 返回提示占位
    log("play no url (APP-only line?) flag=" + flag);
    return JSON.stringify({ parse: 0, url: "", msg: "该线路为APP专属，暂无法播放，请换其他线路" });
}

function search(wd, quick, pg) {
    pg = parseInt(pg || 1);
    if (!pg || pg < 1) pg = 1;
    log("search wd=" + wd + " pg=" + pg);
    var token = getSearchToken();
    var url = HOST + "/search?k=" + encode(wd) + (pg > 1 ? "&page=" + pg : "") + "&t=" + encode(token);
    var html = getHtml(url);
    var list = parseList(html);
    if (!list.length && html.indexOf("search-result-info") < 0) {
        var token2 = extractSearchToken(html);
        if (token2 && token2 !== token) {
            SEARCH_TOKEN = token2;
            html = getHtml(HOST + "/search?k=" + encode(wd) + (pg > 1 ? "&page=" + pg : "") + "&t=" + encode(token2));
            list = parseList(html);
        }
    }
    var limit = 18;
    var pc = searchPageCount(html, pg, limit);
    return JSON.stringify({ list: list, page: pg, pagecount: pc, limit: limit, total: pc * limit });
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
