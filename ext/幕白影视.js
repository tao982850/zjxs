/*
 * @File   : mubai.js
 * @Desc   : 幕白影视 TVBox JS 源 修复兼容版
 */
var MB_VERSION = "20260709-fix-req";
var HOST = "https://m2.mubai.link/";
var API = HOST + "/api";
var UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

// 固定一级分类（页面已正常显示）
var FIX_CLASSES = [
    { type_id: "1", type_name: "电影片" },
    { type_id: "2", type_name: "连续剧" },
    { type_id: "3", type_name: "综艺片" },
    { type_id: "4", type_name: "动漫片" }
];
var CLASSES = FIX_CLASSES;
var CATEGORIES = {};
var FILTERS = {};
var CAT_LOADED = false;

function log(msg) {
    try { console.log("[MB_JS] " + msg); } catch (e) {}
}
function toStr(v) { return v === undefined || v === null ? "" : String(v); }
function encode(s) { return encodeURIComponent(toStr(s)); }
function fixUrl(u) {
    u = toStr(u).trim();
    if (!u) return "";
    if (u.indexOf("//") === 0) return "https:" + u;
    if (u.charAt(0) === "/") return HOST + u;
    return /^https?:\/\//i.test(u) ? u : "";
}

// 修复：TVBox 原生 req 函数，全版本兼容，替换失效的fetch
function requestJson(url) {
    var headers = {
        "User-Agent": UA,
        "Accept": "application/json,*/*;q=0.8",
        "Referer": HOST + "/"
    };
    try {
        var res = req(url, headers);
        return JSON.parse(res.content);
    } catch (e) {
        log("接口请求失败:" + url + " 错误:" + e);
        return null;
    }
}

function loadCategories() {
    if (CAT_LOADED) return;
    var data = requestJson(API + "/index");
    if (!data || !data.code || !data.data || !data.data.content) {
        log("首页接口返回异常，仅展示基础一级分类");
        CAT_LOADED = true;
        return;
    }
    CAT_LOADED = true;
    var cats = {};
    var filters = {};
    var areasSet = {};
    var yearsSet = {};
    for (var i = 0; i < FIX_CLASSES.length; i++) {
        var pid = FIX_CLASSES[i].type_id;
        var subcats = [];
        var seenIds = {};
        var targetTab = null;
        for (var t = 0; t < data.data.content.length; t++) {
            if (toStr(data.data.content[t].nav.id) === pid) {
                targetTab = data.data.content[t];
                break;
            }
        }
        if (targetTab) {
            var allMovies = (targetTab.movies || []).concat(targetTab.hot || []);
            for (var j = 0; j < allMovies.length; j++) {
                var m = allMovies[j];
                if (m.cid && !seenIds[m.cid]) {
                    seenIds[m.cid] = 1;
                    subcats.push({ type_id: m.cid, type_name: toStr(m.cName) });
                }
                if (m.area && !areasSet[m.area]) areasSet[m.area] = 1;
                if (m.year && !yearsSet[m.year]) yearsSet[m.year] = 1;
            }
        }
        if (data.data.category && data.data.category.children) {
            var treeRoots = data.data.category.children;
            for (var k = 0; k < treeRoots.length; k++) {
                if (toStr(treeRoots[k].id) === pid && treeRoots[k].children) {
                    var childNodes = treeRoots[k].children;
                    for (var ci = 0; ci < childNodes.length; ci++) {
                        var node = childNodes[ci];
                        if (node.id && !seenIds[node.id]) {
                            seenIds[node.id] = 1;
                            subcats.push({ type_id: node.id, type_name: toStr(node.name) });
                        }
                    }
                }
            }
        }
        cats[pid] = subcats;
        var areaOpts = [{ n: "全部", v: "" }];
        Object.keys(areasSet).forEach(k => areaOpts.push({ n: k, v: k }));
        var yearOpts = [{ n: "全部", v: "" }];
        Object.keys(yearsSet).filter(y => parseInt(y) >= 2000).forEach(y => yearOpts.push({ n: y, v: y }));
        filters[pid] = [
            { key: "cate", name: "分类", value: subcats },
            { key: "area", name: "地区", value: areaOpts },
            { key: "year", name: "年份", value: yearOpts },
            {
                key: "sort", name: "排序", value: [
                    { n: "默认", v: "" },
                    { n: "热门", v: "hits" },
                    { n: "评分", v: "score" }
                ]
            }
        ];
    }
    CATEGORIES = cats;
    FILTERS = filters;
}

function formatListItem(m) {
    var vid = toStr(m.id || m.mid);
    var remark = toStr(m.remarks || m.year || "");
    return {
        vod_id: vid,
        vod_name: toStr(m.name || vid),
        vod_pic: fixUrl(m.picture || ""),
        vod_remarks: remark
    };
}

function init(ext) {
    if (typeof ext === "string" && /^https?:\/\//i.test(ext.trim())) {
        HOST = ext.trim().replace(/\/+$/, "");
        API = HOST + "/api";
    }
    CAT_LOADED = false;
    CATEGORIES = {};
    FILTERS = {};
    loadCategories();
}

function home(filter) {
    loadCategories();
    return JSON.stringify({ class: CLASSES, filters: FILTERS });
}

function homeVod() {
    var data = requestJson(API + "/index");
    var list = [];
    if (data && data.data && data.data.content) {
        data.data.content.forEach(tab => {
            var items = (tab.hot || []).concat(tab.movies || []);
            items.forEach(item => list.push(formatListItem(item)));
        });
    }
    var map = {};
    var result = [];
    list.forEach(item => {
        if (!map[item.vod_id]) {
            map[item.vod_id] = 1;
            result.push(item);
        }
    });
    return JSON.stringify({ list: result });
}

function category(tid, pg, filter, extend) {
    tid = toStr(tid || "1");
    pg = Math.max(parseInt(pg || 1), 1);
    extend = extend || {};
    var url = API + "/filmClassifySearch?Pid=" + encode(tid) + "&page=" + pg;
    if (extend.cate) url += "&Category=" + encode(extend.cate);
    if (extend.area) url += "&Area=" + encode(extend.area);
    if (extend.year) url += "&Year=" + encode(extend.year);
    if (extend.sort) url += "&Sort=" + encode(extend.sort);
    var res = requestJson(url);
    var listData = (res && res.data && res.data.list) || [];
    var pageInfo = (res && res.data && res.data.page) || {};
    var list = listData.map(formatListItem);
    return JSON.stringify({
        page: pg,
        pagecount: parseInt(pageInfo.pageCount || 1),
        limit: parseInt(pageInfo.pageSize || 24),
        total: parseInt(pageInfo.total || list.length),
        list: list
    });
}

function detail(id) {
    var mid = toStr(id);
    var data = requestJson(API + "/filmDetail?id=" + encode(mid));
    var d = (data && data.code === 0 && data.data && data.data.detail) ? data.data.detail : null;
    if (!d) return JSON.stringify({ list: [{ vod_id: mid, vod_name: mid, vod_play_from: "提示", vod_play_url: "无资源$" }] });
    var vod = {
        vod_id: mid,
        vod_name: toStr(d.name),
        vod_pic: fixUrl(d.picture),
        vod_remarks: toStr(d.remarks || d.year),
        type_name: toStr(d.cName),
        vod_year: toStr(d.year),
        vod_area: toStr(d.area),
        vod_director: toStr(d.director),
        vod_actor: toStr(d.actor),
        vod_content: toStr(d.content || d.blurb)
    };
    if (d.list && d.list.length > 0) {
        var playFrom = [];
        var playUrl = [];
        d.list.forEach(src => {
            if (!src.linkList || src.linkList.length === 0) return;
            playFrom.push(toStr(src.name || "线路"));
            var eps = [];
            src.linkList.forEach(ep => {
                var epName = toStr(ep.episode || "第" + (eps.length + 1) + "集");
                eps.push(epName + "$" + toStr(ep.link));
            });
            playUrl.push(eps.join("#"));
        });
        vod.vod_play_from = playFrom.join("$$$");
        vod.vod_play_url = playUrl.join("$$$");
    } else {
        vod.vod_play_from = "提示";
        vod.vod_play_url = "暂无播放资源$";
    }
    return JSON.stringify({ list: [vod] });
}

function play(flag, id, flags) {
    return JSON.stringify({
        parse: 0,
        url: toStr(id),
        header: { "User-Agent": UA, "Referer": HOST + "/" }
    });
}

function search(wd, quick, pg) {
    pg = Math.max(parseInt(pg || 1), 1);
    wd = toStr(wd).trim();
    if (!wd) return JSON.stringify({ list: [], page: 1, pagecount: 1, limit: 0, total: 0 });
    var res = requestJson(API + "/searchFilm?keyword=" + encode(wd));
    var listData = (res && res.data && res.data.list) || [];
    var pageInfo = (res && res.data && res.data.page) || {};
    var list = listData.map(m => ({
        vod_id: toStr(m.id),
        vod_name: toStr(m.name),
        vod_pic: fixUrl(m.picture),
        vod_remarks: toStr(m.year || "")
    }));
    return JSON.stringify({
        list: list,
        page: pg,
        pagecount: parseInt(pageInfo.pageCount || 1),
        limit: list.length,
        total: parseInt(pageInfo.total || list.length)
    });
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
