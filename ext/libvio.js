var LIBVIO_VERSION = "20260708-js-1354";
var HOST = "https://www.libvio.pw";
var HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": HOST + "/",
    "Accept-Encoding": "identity"
};
var CLASSES = [
    { type_id: "1", type_name: "电影" },
    { type_id: "2", type_name: "剧集" },
    { type_id: "4", type_name: "番剧" },
    { type_id: "3", type_name: "综艺" },
    { type_id: "15", type_name: "日韩" },
    { type_id: "16", type_name: "欧美" }
];
var FILTERS = {};
var CATEGORY_KEYS = {
    "1": ["电影"],
    "2": ["剧"],
    "4": ["番"],
    "3": ["民宿", "特辑", "综"],
    "15": ["日", "韩", "日剧", "韩剧"],
    "16": ["美剧", "龙", "瑞克", "剧"]
};
var AREA_COMMON = ["中国大陆", "中国香港", "中国台湾", "美国", "日本", "韩国", "英国", "法国", "泰国", "印度", "其他"];
var AREA_BY_TID = {
    "1": ["中国大陆", "中国香港", "中国台湾", "美国", "法国", "英国", "日本", "韩国", "德国", "泰国", "印度", "意大利", "西班牙", "加拿大", "其他"],
    "2": ["中国大陆", "中国台湾", "中国香港", "韩国", "日本", "美国", "泰国", "英国", "新加坡", "其他"],
    "3": ["内地", "港台", "日韩", "欧美"],
    "4": ["中国", "日本", "欧美", "其他"],
    "15": ["日本", "韩国"],
    "16": ["美国", "英国", "德国", "加拿大", "其他"]
};
var CLASS_COMMON = ["剧情", "喜剧", "爱情", "动作", "科幻", "悬疑", "犯罪", "动画", "奇幻", "冒险", "战争", "惊悚", "纪录"];
var LANG_COMMON = ["国语", "英语", "粤语", "闽南语", "韩语", "日语", "法语", "德语", "其它"];

function log(msg) {
    try { console.log("[LIBVIO_JS " + LIBVIO_VERSION + "] " + msg); } catch (e) {}
}

function init(ext) {
    if (typeof ext === "string" && /^https?:\/\//.test(ext.trim())) {
        HOST = ext.trim().replace(/\/+$/, "");
        HEADERS.Referer = HOST + "/";
    }
    FILTERS = {};
    for (var i = 0; i < CLASSES.length; i++) {
        FILTERS[CLASSES[i].type_id] = buildFilters(CLASSES[i].type_id);
    }
    log("init host=" + HOST);
}

function optionValues(values, withAll) {
    var out = withAll ? [{ n: "全部", v: "" }] : [];
    for (var i = 0; i < values.length; i++) out.push({ n: values[i], v: values[i] });
    return out;
}

function yearValues() {
    var out = [{ n: "全部", v: "" }];
    for (var y = 2026; y >= 1998; y--) {
        if (y === 2000) continue;
        out.push({ n: String(y), v: String(y) });
    }
    return out;
}

function buildFilters(tid) {
    return [
        { key: "area", name: "地区", value: optionValues(AREA_BY_TID[tid] || AREA_COMMON, true) },
        { key: "year", name: "年份", value: yearValues() },
        { key: "class", name: "剧情", value: optionValues(CLASS_COMMON, true) },
        { key: "lang", name: "语言", value: optionValues(LANG_COMMON, true) },
        { key: "sort", name: "排序", value: [{ n: "最新", v: "" }, { n: "人气", v: "hits" }, { n: "评分", v: "score" }] }
    ];
}

function requestText(url, referer) {
    var h = {};
    for (var k in HEADERS) h[k] = HEADERS[k];
    if (referer) h.Referer = referer;
    try {
        log("fetch " + url);
        var res = req(url, { method: "GET", headers: h, timeout: 5000 });
        if (typeof res === "string") return res;
        return (res && (res.content || res.body || res.data)) || "";
    } catch (e) {
        log("fetch_error " + url + " " + e);
        return "";
    }
}

function fixUrl(u) {
    if (!u) return "";
    u = String(u).trim();
    if (u.indexOf("//") === 0) return "https:" + u;
    if (u.charAt(0) === "/") return HOST + u;
    return u;
}

function cleanUrl(u) {
    return fixUrl(String(u || "").split("||")[0]);
}

function textClean(s) {
    return String(s || "")
        .replace(/<script[\s\S]*?<\/script>/g, "")
        .replace(/<style[\s\S]*?<\/style>/g, "")
        .replace(/<[^>]+>/g, "")
        .replace(/&nbsp;/g, " ")
        .replace(/&amp;/g, "&")
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/\s+/g, " ")
        .trim();
}

function attr(tag, name) {
    var r = new RegExp(name + "\\s*=\\s*([\"'])([\\s\\S]*?)\\1", "i");
    var m = r.exec(tag || "");
    return m ? m[2] : "";
}

function parseList(html) {
    var list = [];
    var seen = {};
    if (!html) return list;
    var re = /<a\b[^>]*class=["'][^"']*stui-vodlist__thumb[^"']*["'][^>]*href=["']([^"']*\/detail\/(\d+)\.html)["'][^>]*>[\s\S]*?<\/a>/g;
    var m;
    while ((m = re.exec(html)) !== null) {
        var tag = m[0];
        var id = m[2];
        if (!id || seen[id]) continue;
        seen[id] = true;
        var name = attr(tag, "title") || textClean(tag);
        var pic = attr(tag, "data-original") || attr(tag, "data-src") || attr(tag, "src");
        var remark = "";
        var rm = /<span\b[^>]*class=["'][^"']*pic-text[^"']*["'][^>]*>([\s\S]*?)<\/span>/i.exec(tag);
        if (rm) remark = textClean(rm[1]);
        list.push({ vod_id: id, vod_name: name, vod_pic: fixUrl(pic), vod_remarks: remark });
    }
    return list;
}

function pageCount(html) {
    var m = /<a>(\d+)\/(\d+)<\/a>/.exec(html || "");
    return m ? parseInt(m[2]) : 99;
}

function searchUrl(key, pg) {
    return HOST + "/search/" + encodeURIComponent(key) + "----------" + (pg || 1) + "---.html";
}

function parseExtend(extend) {
    if (!extend) return {};
    if (typeof extend === "string") {
        try { return JSON.parse(extend); } catch (e) { return {}; }
    }
    return extend;
}

function extValue(ext, key) {
    var v = ext && (ext[key] || ext[encodeURIComponent(key)]);
    return v ? String(v) : "";
}

function hasFilter(ext) {
    return !!(extValue(ext, "area") || extValue(ext, "year") || extValue(ext, "class") || extValue(ext, "genre") || extValue(ext, "lang") || extValue(ext, "sort"));
}

function showUrl(tid, pg, ext) {
    var fields = [
        String(tid),
        extValue(ext, "area"),
        extValue(ext, "sort"),
        extValue(ext, "class") || extValue(ext, "genre"),
        extValue(ext, "lang"),
        "",
        "",
        "",
        pg > 1 ? String(pg) : "",
        "",
        "",
        extValue(ext, "year")
    ];
    for (var i = 0; i < fields.length; i++) fields[i] = encodeURIComponent(fields[i]);
    return HOST + "/show/" + fields.join("-") + ".html";
}

function listByKeywords(keys, pg) {
    var list = [];
    var seen = {};
    var maxPage = 1;
    for (var i = 0; i < keys.length; i++) {
        var html = requestText(searchUrl(keys[i], pg));
        maxPage = Math.max(maxPage, pageCount(html));
        var part = parseList(html);
        for (var j = 0; j < part.length; j++) {
            var it = part[j];
            if (!seen[it.vod_id]) {
                seen[it.vod_id] = true;
                list.push(it);
            }
        }
        if (list.length >= 12 && i > 0) break;
    }
    if (list.length > 12) list = list.slice(0, 12);
    return { list: list, pagecount: maxPage };
}

function home(filter) {
    log("home filter=" + filter);
    return JSON.stringify({ class: CLASSES, filters: FILTERS });
}

function homeVod() {
    log("homeVod");
    var data = listByKeywords(["电影"], 1);
    if (data.list.length > 0) data.list[0].vod_name = data.list[0].vod_name + " " + LIBVIO_VERSION;
    return JSON.stringify({ list: data.list });
}

function category(tid, pg, filter, extend) {
    tid = String(tid || "1");
    pg = parseInt(pg || 1);
    if (!pg || pg < 1) pg = 1;
    var ext = parseExtend(extend);
    if (hasFilter(ext)) {
        var url = showUrl(tid, pg, ext);
        log("categoryShow tid=" + tid + " pg=" + pg + " url=" + url + " extend=" + JSON.stringify(ext));
        var html = requestText(url);
        var items = parseList(html);
        if (html || items.length) {
            log("categoryShowResult tid=" + tid + " count=" + items.length);
            var pc = pageCount(html);
            return JSON.stringify({
                page: pg,
                pagecount: pc,
                limit: 12,
                total: pc * 12,
                count: items.length,
                list: items
            });
        }
        log("categoryShowFallback tid=" + tid);
    }
    var keys = CATEGORY_KEYS[tid] || ["电影"];
    log("category tid=" + tid + " pg=" + pg + " keys=" + keys.join(","));
    var data = listByKeywords(keys, pg);
    log("categoryResult tid=" + tid + " count=" + data.list.length);
    return JSON.stringify({
        page: pg,
        pagecount: data.pagecount,
        limit: 12,
        total: data.pagecount * 12,
        count: data.list.length,
        list: data.list
    });
}

function firstMatch(html, re) {
    var m = re.exec(html || "");
    return m ? textClean(m[1]) : "";
}

function parseOnlinePanel(block) {
    var source = firstMatch(block, /<h3[^>]*>([\s\S]*?)<\/h3>/i) || "在线播放";
    var eps = [];
    var re = /<a\b[^>]*href=["']([^"']*\/w\/[^"']+)["'][^>]*>([\s\S]*?)<\/a>/g;
    var m;
    while ((m = re.exec(block)) !== null) {
        var name = textClean(m[2]) || "播放";
        eps.push(name + "$" + fixUrl(m[1]));
    }
    return eps.length ? { source: source, urls: eps.join("#") } : null;
}

function parseNetdiskPanel(block) {
    var source = firstMatch(block, /<h3[^>]*>([\s\S]*?)<\/h3>/i) || "网盘";
    source = source.replace(/\s+/g, "");
    var eps = [];
    var re = /<a\b[^>]*class=["'][^"']*netdisk-item[^"']*["'][^>]*href=["']([^"']+)["'][^>]*>[\s\S]*?<\/a>/g;
    var m;
    while ((m = re.exec(block)) !== null) {
        var tag = m[0];
        var nm = /<span\b[^>]*class=["'][^"']*netdisk-name[^"']*["'][^>]*>([\s\S]*?)<\/span>/i.exec(tag);
        var name = nm ? textClean(nm[1]) : "网盘";
        eps.push(name + "$" + cleanUrl(m[1]));
    }
    return eps.length ? { source: source, urls: eps.join("#") } : null;
}

function detail(id) {
    log("detail id=" + id);
    var vid = String(id || "").split(",")[0];
    var html = requestText(HOST + "/detail/" + vid + ".html");
    if (!html) return JSON.stringify({ list: [] });
    var name = firstMatch(html, /<h1\b[^>]*class=["'][^"']*title[^"']*["'][^>]*>([\s\S]*?)<\/h1>/i) || firstMatch(html, /<title>([\s\S]*?)<\/title>/i).replace(" - LIBVIO", "");
    var pic = "";
    var poster = /<img\b[^>]*id=["']js-poster-img["'][^>]*>/i.exec(html);
    if (poster) pic = attr(poster[0], "data-original") || attr(poster[0], "src");
    if (!pic) {
        var bg = /id=["']js-backdrop["'][^>]*data-src=["']([^"']+)/i.exec(html);
        if (bg) pic = bg[1];
    }
    var desc = firstMatch(html, /<span\b[^>]*class=["'][^"']*detail-content[^"']*["'][^>]*>([\s\S]*?)<\/span>/i);
    var meta = [];
    var mr = /<span\b[^>]*class=["'][^"']*meta-item[^"']*["'][^>]*>([\s\S]*?)<\/span>/g;
    var mm;
    while ((mm = mr.exec(html)) !== null) meta.push(textClean(mm[1]));
    var actor = "";
    var director = "";
    for (var i = 0; i < meta.length; i++) {
        if (meta[i].indexOf("主演：") === 0) actor = meta[i].replace("主演：", "");
        if (meta[i].indexOf("导演：") === 0) director = meta[i].replace("导演：", "");
    }
    var sources = [];
    var urls = [];
    var parts = html.split('<div class="playlist-panel');
    for (var p = 1; p < parts.length; p++) {
        var block = '<div class="playlist-panel' + parts[p];
        var panel = block.indexOf("netdisk-panel") >= 0 ? parseNetdiskPanel(block) : parseOnlinePanel(block);
        if (panel) {
            sources.push(panel.source);
            urls.push(panel.urls);
        }
    }
    if (!sources.length) {
        var play = /<div\b[^>]*class=["'][^"']*play-btn[^"']*["'][^>]*>[\s\S]*?<a\b[^>]*href=["']([^"']*\/w\/[^"']+)["'][^>]*>([\s\S]*?)<\/a>/i.exec(html);
        if (play) {
            sources.push("在线播放");
            urls.push((textClean(play[2]) || "播放") + "$" + fixUrl(play[1]));
        }
    }
    return JSON.stringify({ list: [{
        vod_id: vid,
        vod_name: name,
        vod_pic: fixUrl(pic),
        vod_actor: actor,
        vod_director: director,
        vod_content: desc,
        vod_play_from: sources.join("$$$"),
        vod_play_url: urls.join("$$$")
    }] });
}

function play(flag, id, flags) {
    var url = cleanUrl(id);
    log("play flag=" + flag + " id=" + id);
    if (url.indexOf("/w/") >= 0) {
        var html = requestText(url, url);
        var m = /var\s+player_aaaa\s*=\s*(\{[\s\S]*?\})\s*<\/script>/i.exec(html);
        if (m) {
            try {
                var data = JSON.parse(m[1]);
                var playUrl = cleanUrl(data.url || "");
                if (/^https?:\/\//.test(playUrl) && /\.(m3u8|mp4|flv)(\?|$)/i.test(playUrl)) {
                    return JSON.stringify({ parse: 0, url: playUrl, header: HEADERS });
                }
                if (/^https?:\/\/(pan|drive|www\.aliyundrive|www\.123pan|cloud)\./i.test(playUrl) || /quark|xunlei|baidu|uc\.cn|aliyundrive|123pan/i.test(playUrl)) {
                    return JSON.stringify({ parse: 0, url: playUrl, header: HEADERS });
                }
            } catch (e) {
                log("player_json_error " + e);
            }
        }
        return JSON.stringify({ parse: 1, jx: 1, url: url, header: HEADERS });
    }
    return JSON.stringify({ parse: 0, url: url, header: HEADERS });
}

function search(wd, quick, pg) {
    pg = parseInt(pg || 1);
    if (!pg || pg < 1) pg = 1;
    log("search wd=" + wd + " pg=" + pg);
    var html = requestText(searchUrl(wd || "", pg));
    var list = parseList(html);
    return JSON.stringify({ list: list, page: pg, pagecount: pageCount(html), limit: list.length });
}

__JS_SPIDER__ = {
    init: init,
    home: home,
    homeVod: homeVod,
    category: category,
    detail: detail,
    play: play,
    search: search
};
