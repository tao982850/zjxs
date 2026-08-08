// ================================================================
// 电影人生 爬虫 - 完整修复版
// 支持：首页、分类、搜索、详情、播放
// 适配站点：https://dyrs6.vip (及镜像)
// ================================================================
import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
    siteName: "电影人生",
    siteUrl: "https://dyrs6.vip"
};
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

const fallbackDomains = [
    "https://dyrs6.vip",
    "https://dyrs7.vip",
    "https://dyrs8.vip"
];

// ===== 分类列表（硬编码，与站点一致） =====
const classList = [
    { type_id: "dianying", type_name: "电影" },
    { type_id: "dianshiju", type_name: "电视剧" },
    { type_id: "zongyi", type_name: "综艺" },
    { type_id: "dongman", type_name: "动漫" },
    { type_id: "duanju", type_name: "短剧" }
];

// ===== 筛选器 =====
function getAreaFilter() {
    return {
        key: "area", name: "地区", value: [
            { n: "全部", v: "" }, { n: "大陆", v: "大陆" }, { n: "香港", v: "香港" },
            { n: "台湾", v: "台湾" }, { n: "美国", v: "美国" }, { n: "日本", v: "日本" },
            { n: "韩国", v: "韩国" }, { n: "英国", v: "英国" }, { n: "法国", v: "法国" },
            { n: "德国", v: "德国" }, { n: "泰国", v: "泰国" }, { n: "印度", v: "印度" },
            { n: "其他", v: "其他" }
        ]
    };
}
function getYearFilter() {
    let years = [{ n: "全部", v: "" }];
    const currentYear = new Date().getFullYear();
    for (let y = currentYear; y >= 2010; y--) years.push({ n: String(y), v: String(y) });
    return { key: "year", name: "年份", value: years };
}
function getLangFilter() {
    return {
        key: "lang", name: "语言", value: [
            { n: "全部", v: "" }, { n: "国语", v: "国语" }, { n: "粤语", v: "粤语" },
            { n: "英语", v: "英语" }, { n: "日语", v: "日语" }, { n: "韩语", v: "韩语" },
            { n: "其他", v: "其他" }
        ]
    };
}
function getTypeFilter() {
    return {
        key: "type", name: "类型", value: [
            { n: "全部", v: "" }, { n: "剧情", v: "剧情" }, { n: "喜剧", v: "喜剧" },
            { n: "动作", v: "动作" }, { n: "爱情", v: "爱情" }, { n: "科幻", v: "科幻" },
            { n: "恐怖", v: "恐怖" }, { n: "悬疑", v: "悬疑" }, { n: "犯罪", v: "犯罪" },
            { n: "动画", v: "动画" }, { n: "冒险", v: "冒险" }, { n: "奇幻", v: "奇幻" },
            { n: "战争", v: "战争" }, { n: "纪录片", v: "纪录片" }
        ]
    };
}
const commonFilters = [getAreaFilter(), getYearFilter(), getLangFilter(), getTypeFilter()];
const myFilters = {};
classList.forEach(item => { myFilters[item.type_id] = commonFilters; });

// ===== 工具函数 =====
function fixUrl(u) {
    if (!u) return '';
    if (u.startsWith('http')) return u;
    if (u.startsWith('//')) return 'https:' + u;
    if (u.startsWith('/')) return appConfig.siteUrl + u;
    return u;
}
function encodeQuery(s) {
    try { return encodeURIComponent(s); } catch(e) { return s; }
}

async function fetchUrl(url) {
    try {
        let resp = await req(url, {
            method: "GET",
            headers: {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": appConfig.siteUrl
            }
        });
        return resp.content || "";
    } catch (e) {
        console.error("[电影人生] 请求失败: " + url + " - " + e.message);
        return "";
    }
}

async function init(ext) {
    console.log("[电影人生] 初始化...");
    for (let i = 0; i < fallbackDomains.length; i++) {
        try {
            let html = await fetchUrl(fallbackDomains[i] + "/");
            if (html.length > 500 && (html.includes("wzzy") || html.includes("vod") || html.includes("电影"))) {
                appConfig.siteUrl = fallbackDomains[i];
                console.log("[电影人生] 使用域名: " + appConfig.siteUrl);
                return;
            }
        } catch(e) {}
    }
    console.warn("[电影人生] 使用默认域名: " + appConfig.siteUrl);
}

// ===== 核心解析：从 HTML 中提取影片列表 =====
function parseListHtml(html, filterYear) {
    let list = [];
    let pagecount = 1;
    let seen = {};
    if (!html) return { list, pagecount };

    try {
        let $ = cheerio.load(html);

        // 提取所有可能包含影片的 a 标签
        // 先尝试常见容器，再降级为所有带 img 和 title 的链接
        let candidates = [];

        // 1. 容器类
        let containers = $(".module-poster-item, .movie-item, .vod-item, .list-item, .video-item, .item, .poster");
        containers.each(function() {
            let $item = $(this);
            let $a = $item.is("a") ? $item : $item.find("a").first();
            let href = $a.attr("href") || "";
            if (!href) return;
            let name = $a.attr("title") || $item.find(".title, .name, .vod-name").text().trim() || $a.text().trim();
            let pic = $item.find("img").attr("data-original") || $item.find("img").attr("data-src") || $item.find("img").attr("src") || "";
            let note = $item.find(".note, .remarks, .episode, .update").text().trim() || "";
            candidates.push({ href, name, pic, note });
        });

        // 2. 特征链接（如果容器没找到）
        if (candidates.length === 0) {
            $("a[href*='/wzzy-'], a[href*='/vod-'], a[href*='/detail/']").each(function() {
                let href = $(this).attr("href");
                let name = $(this).attr("title") || $(this).text().trim();
                let pic = $(this).find("img").attr("data-original") || $(this).find("img").attr("src") || "";
                if (href && name) candidates.push({ href, name, pic, note: "" });
            });
        }

        // 3. 最宽松：所有带图片和标题的链接
        if (candidates.length === 0) {
            $("a").each(function() {
                let href = $(this).attr("href");
                if (!href) return;
                if (href.startsWith("#") || href.startsWith("javascript:") || href === "/") return;
                let name = $(this).attr("title") || $(this).text().trim();
                if (!name || name.length < 2) return;
                let hasImg = $(this).find("img").length > 0;
                let isVideoLink = href.includes(".html") || href.includes("/vod") || href.includes("/wzzy") || href.includes("/detail");
                if (hasImg && isVideoLink) {
                    let pic = $(this).find("img").attr("data-original") || $(this).find("img").attr("src") || "";
                    candidates.push({ href, name, pic, note: "" });
                }
            });
        }

        // 去重并构建列表
        candidates.forEach(item => {
            let href = item.href;
            if (!href || seen[href]) return;
            let vod_name = item.name.trim();
            if (!vod_name) return;
            let vod_pic = fixUrl(item.pic);
            let vod_remarks = filterYear ? filterYear + (item.note ? " | " + item.note : "") : item.note;
            seen[href] = true;
            list.push({ vod_id: href, vod_name, vod_pic, vod_remarks });
        });

        console.log("[电影人生] 解析到条目数: " + list.length);

        // 分页
        $("a[href*='page=']").each(function() {
            let m = $(this).attr("href").match(/page=(\d+)/);
            if (m) {
                let p = parseInt(m[1]);
                if (p > pagecount) pagecount = p;
            }
        });
        if (pagecount === 1 && list.length > 0 && $("a:contains('下一页')").length > 0) {
            pagecount = 999;
        }
    } catch (e) {
        console.error("[电影人生] 解析异常: " + e.message);
    }
    return { list, pagecount };
}

// ===== 首页 =====
async function home(filter) {
    let list = [];
    try {
        let html = await fetchUrl(appConfig.siteUrl + "/dianying.html");
        if (!html) html = await fetchUrl(appConfig.siteUrl);
        let result = parseListHtml(html);
        list = result.list.slice(0, 30);
    } catch (e) {}
    return JSON.stringify({
        class: classList,
        filters: myFilters,
        list: list
    });
}

// ===== 分类 =====
function buildCategoryUrl(tid, pg, extend) {
    extend = extend || {};
    let baseType = tid.split('-')[0];
    let subType = tid.split('-')[1] || '';
    let url = `/${baseType}.html`;
    let params = [];
    if (subType) params.push(`class=${encodeQuery(subType)}`);
    if (extend.area) params.push(`area=${encodeQuery(extend.area)}`);
    if (extend.year) params.push(`year=${extend.year}`);
    if (extend.lang) params.push(`lang=${encodeQuery(extend.lang)}`);
    if (extend.type) params.push(`type=${encodeQuery(extend.type)}`);
    if (pg && pg > 1) params.push(`page=${pg}`);
    if (params.length) url += '?' + params.join('&');
    return appConfig.siteUrl + url;
}

async function category(tid, pg, filter, extend) {
    pg = pg || 1;
    extend = extend || {};
    let result = { list: [], page: pg, pagecount: 0, limit: 20, total: 0 };
    try {
        let url = buildCategoryUrl(tid, pg, extend);
        let html = await fetchUrl(url);
        let parsed = parseListHtml(html, extend.year || "");
        result.list = parsed.list;
        result.pagecount = parsed.pagecount;
        result.total = result.pagecount * result.limit;
    } catch (e) {}
    return JSON.stringify(result);
}

// ===== 搜索 =====
async function search(wd, quick, page) {
    page = page || 1;
    let result = { list: [], page: page, pagecount: 0, limit: 20, total: 0 };
    try {
        let url = appConfig.siteUrl + "/s.html?name=" + encodeQuery(wd);
        if (page > 1) url += "&page=" + page;
        let html = await fetchUrl(url);
        let parsed = parseListHtml(html);
        result.list = parsed.list;
        result.pagecount = parsed.pagecount;
        result.total = result.pagecount * result.limit;
    } catch (e) {}
    return JSON.stringify(result);
}

// ===== 详情 =====
async function detail(id) {
    try {
        let html = await fetchUrl(appConfig.siteUrl + id);
        let $ = cheerio.load(html);

        // 基本信息
        let vod_name = $("h1").first().text().trim() || $("title").text().replace(/《|》/g, "").replace(/-.*$/, "").trim();
        let vod_pic = "";
        let hash = id.match(/\/wzzy-\d+\/([a-f0-9]+)\.html/)?.[1] || "";
        if (hash) vod_pic = `${appConfig.siteUrl}/img/id/${hash}.jpg`;
        else {
            let img = $(".module-poster img, .vod-poster img, .pic img").first();
            if (img.length) vod_pic = fixUrl(img.attr("data-original") || img.attr("src") || "");
        }

        let vod_director = "", vod_actor = "", vod_year = "", vod_area = "", vod_class = "", vod_content = "", vod_remarks = "";

        // 从 JSON-LD 提取
        $('script[type="application/ld+json"]').each(function() {
            try {
                let data = JSON.parse($(this).html());
                if (data.name) vod_name = data.name;
                if (data.year) vod_year = String(data.year);
                if (data.countryOfOrigin) vod_area = data.countryOfOrigin;
                if (data.inLanguage) vod_class = data.inLanguage;
                if (data.description) vod_content = data.description.replace(/<br \/>/g, "\n").trim();
                if (data.director && data.director.name) vod_director = data.director.name;
                if (data.actor) vod_actor = data.actor.map(a => a.name).join(',');
            } catch(e) {}
        });

        // 从详情项补充
        $(".module-info-item, .info-item").each(function() {
            let label = $(this).find(".module-info-item-title, .label").text().trim();
            let value = $(this).find(".module-info-item-content, .value").text().trim();
            if (label.includes("导演")) vod_director = value;
            else if (label.includes("主演")) vod_actor = value;
            else if (label.includes("类型")) vod_class = value;
            else if (label.includes("地区")) vod_area = value;
            else if (label.includes("年份")) vod_year = value;
            else if (label.includes("更新")) vod_remarks = value;
        });

        // 简介
        if (!vod_content) {
            vod_content = $(".module-info-introduction-content p, .vod-intro, .summary").first().text().trim();
        }

        // 播放线路
        let lines = [], playlists = [];
        let sourceNames = [];
        $(".module-tab-item, .play-source-tab").each(function() {
            let name = $(this).attr("data-dropdown-value") || $(this).find("span").text().trim();
            if (name) sourceNames.push(name);
        });

        let panelIndex = 0;
        $("[id^='panel'], .play-list, .episode-list").each(function() {
            let episodes = [];
            let epArray = [];
            $(this).find(".module-play-list-link, .episode-link, a[href*='?p=']").each(function() {
                let name = $(this).find("span").text().trim() || $(this).text().trim();
                let href = $(this).attr("href") || "";
                if (name && href) epArray.push({ name, href });
            });
            // 排序
            epArray.sort((a,b) => {
                let n1 = parseInt(a.name.match(/\d+/)?.[0] || 0);
                let n2 = parseInt(b.name.match(/\d+/)?.[0] || 0);
                return n1 - n2;
            });
            epArray.forEach(ep => episodes.push(ep.name + "$" + ep.href));
            if (episodes.length) {
                let lineName = sourceNames[panelIndex] || ("线路" + (panelIndex+1));
                lines.push(lineName);
                playlists.push(episodes);
            }
            panelIndex++;
        });

        if (lines.length === 0) {
            let episodes = [];
            $(".module-play-list-link, .episode-link, a[href*='?p=']").each(function() {
                let name = $(this).find("span").text().trim() || $(this).text().trim();
                let href = $(this).attr("href") || "";
                if (name && href) episodes.push(name + "$" + href);
            });
            if (episodes.length) {
                lines.push("默认");
                playlists.push(episodes);
            }
        }

        if (lines.length === 0) {
            lines.push("提示");
            playlists.push(["暂无播放地址$" + id]);
        }

        let vod_play_from = lines.join("$$$");
        let vod_play_url = playlists.map(eps => eps.join("#")).join("$$$");

        return JSON.stringify([{
            vod_id: id,
            vod_name,
            vod_pic,
            vod_actor,
            vod_director,
            vod_remarks,
            vod_year,
            vod_area,
            vod_content,
            vod_class,
            vod_play_from,
            vod_play_url
        }]);
    } catch (e) {
        console.error("[电影人生] 详情异常: " + e.message);
        return JSON.stringify([]);
    }
}

// ===== 播放 =====
async function play(flag, id, flags) {
    try {
        if (id.startsWith("http")) {
            return JSON.stringify({ parse: 0, header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: id });
        }
        let html = await fetchUrl(appConfig.siteUrl + id);
        // 尝试 /api/m3u8
        let m = html.match(/href="\/api\/m3u8\?origin=([^&]+)&amp;?url=([^"]+)"/);
        if (!m) m = html.match(/href="\/api\/m3u8\?origin=([^&]+)&url=([^"]+)"/);
        if (m) {
            let playUrl = `${appConfig.siteUrl}/api/m3u8?origin=${encodeURIComponent(m[1])}&url=${m[2]}`;
            return JSON.stringify({ parse: 0, header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: playUrl });
        }
        // 直链
        let urlMatch = html.match(/"url"\s*[:=]\s*"([^"]+\.(m3u8|mp4|flv)[^"]*)"/);
        if (urlMatch) {
            return JSON.stringify({ parse: 0, header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: urlMatch[1].replace(/\\/g, '') });
        }
        // iframe
        let $ = cheerio.load(html);
        let iframeSrc = $("iframe").attr("src");
        if (iframeSrc) {
            return JSON.stringify({ parse: 1, header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: fixUrl(iframeSrc) });
        }
        // 兜底
        return JSON.stringify({ parse: 1, header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: appConfig.siteUrl + id });
    } catch (e) {
        return JSON.stringify({ parse: 0, url: "" });
    }
}

export default {
    init,
    home,
    category,
    search,
    detail,
    play
};