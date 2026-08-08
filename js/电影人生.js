// ================================================================
// 电影人生 爬虫 - 调试增强版
// 输出详细日志，帮助定位无数据原因
// ================================================================
import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
    siteName: "电影人生",
    siteUrl: "https://dyrs6.vip"
};
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

// 备用域名（按需添加）
const fallbackDomains = [
    "https://dyrs6.vip",
    "https://dyrs7.vip",
    "https://dyrs8.vip"
];

// ===== 分类列表 =====
const classList = [
    { type_id: "dianying", type_name: "电影" },
    { type_id: "dianshiju", type_name: "电视剧" },
    { type_id: "zongyi", type_name: "综艺" },
    { type_id: "dongman", type_name: "动漫" },
    { type_id: "duanju", type_name: "短剧" }
    // 更多细分可自行添加
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
    try { return encodeURIComponent(s); } catch(e) {}
    return s.replace(/[^A-Za-z0-9]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase());
}

async function fetchUrl(url) {
    console.log("[电影人生] 请求 URL: " + url);
    try {
        let resp = await req(url, {
            method: "GET",
            headers: {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": appConfig.siteUrl
            }
        });
        let html = resp.content || "";
        console.log("[电影人生] 响应长度: " + html.length + " 字节");
        return html;
    } catch (e) {
        console.error("[电影人生] 请求异常: " + e.message);
        return "";
    }
}

// ===== 初始化（探测可用域名） =====
async function init(ext) {
    console.log("[电影人生] 初始化开始...");
    for (let i = 0; i < fallbackDomains.length; i++) {
        try {
            let resp = await req(fallbackDomains[i] + "/", {
                method: "GET",
                headers: { "User-Agent": UA, "Accept": "text/html" }
            });
            let html = resp.content || "";
            if (html.length > 500 && (html.indexOf("wzzy") !== -1 || html.indexOf("vod") !== -1 || html.indexOf("电影") !== -1)) {
                appConfig.siteUrl = fallbackDomains[i];
                console.log("[电影人生] 使用可用域名: " + appConfig.siteUrl);
                return;
            }
        } catch(e) {}
    }
    console.warn("[电影人生] 所有备用域名不可用，使用默认: " + appConfig.siteUrl);
}

// ===== 通用列表解析（带调试输出） =====
function parseListHtml(html, filterYear) {
    let list = [];
    let pagecount = 1;
    let seen = {};
    console.log("[电影人生] 开始解析列表，HTML长度: " + html.length);

    try {
        let $ = cheerio.load(html);

        // 策略1：常见容器
        let items = $(".module-poster-item, .movie-item, .vod-item, .list-item, .video-item");
        console.log("[电影人生] 策略1 - 匹配到容器数量: " + items.length);

        if (items.length === 0) {
            // 策略2：特征链接
            let links = $("a[href*='/wzzy-'], a[href*='/vod-'], a[href*='/detail/']");
            console.log("[电影人生] 策略2 - 匹配到特征链接数量: " + links.length);
            links.each(function() {
                let href = $(this).attr("href");
                let name = $(this).attr("title") || $(this).text().trim();
                if (href && name && !seen[href]) {
                    let pic = "";
                    let img = $(this).find("img").first();
                    if (img.length) pic = img.attr("data-original") || img.attr("src") || "";
                    seen[href] = true;
                    list.push({ vod_id: href, vod_name: name, vod_pic: fixUrl(pic), vod_remarks: "" });
                }
            });
        } else {
            items.each(function() {
                let $item = $(this);
                let $a = $item.is("a") ? $item : $item.find("a").first();
                let href = $a.attr("href") || "";
                if (!href || seen[href]) return;
                let vod_name = $a.attr("title") || $item.find(".title, .name, .vod-name").text().trim() || "";
                let vod_pic = fixUrl(
                    $item.find("img").attr("data-original") ||
                    $item.find("img").attr("data-src") ||
                    $item.find("img").attr("src") || ""
                );
                let note = $item.find(".note, .remarks, .episode").text().trim() || "";
                let vod_remarks = filterYear ? filterYear + (note ? " | " + note : "") : note;
                if (vod_name && href) {
                    seen[href] = true;
                    list.push({ vod_id: href, vod_name, vod_pic, vod_remarks });
                }
            });
        }

        // 如果依然无数据，尝试最宽松的匹配（所有a标签，但过滤）
        if (list.length === 0) {
            console.log("[电影人生] 策略3 - 尝试所有a标签");
            $("a").each(function() {
                let href = $(this).attr("href");
                if (!href) return;
                if (href.startsWith("#") || href.startsWith("javascript:")) return;
                if (href === "/" || href === "/index.html") return;
                if (href.includes("login") || href.includes("register")) return;
                let name = $(this).attr("title") || $(this).text().trim();
                if (!name || name.length < 2) return;
                // 过滤掉明显非影片链接
                if (!href.includes(".html") && !href.includes("/vod") && !href.includes("/wzzy")) return;
                let pic = "";
                let img = $(this).find("img").first();
                if (img.length) pic = img.attr("data-original") || img.attr("src") || "";
                seen[href] = true;
                list.push({ vod_id: href, vod_name: name, vod_pic: fixUrl(pic), vod_remarks: "" });
            });
        }

        console.log("[电影人生] 解析到条目数: " + list.length);

        // 分页解析
        $("a[href*='page='], a[href*='-p-'], .page-link, .num-page").each(function() {
            let href = $(this).attr("href") || "";
            let m = href.match(/[?&]page=(\d+)/) || href.match(/\/page\/(\d+)/) || href.match(/-p-(\d+)/);
            if (m) {
                let p = parseInt(m[1]);
                if (p > pagecount) pagecount = p;
            }
        });
        if (pagecount === 1 && list.length > 0 && $("a:contains('下一页'), a:contains('Next'), .page-next").length > 0) {
            pagecount = 999;
        }
        console.log("[电影人生] 总页数: " + pagecount);

    } catch (e) {
        console.error("[电影人生] 解析列表异常: " + e.message);
    }

    return { list, pagecount };
}

// ===== 首页 =====
async function home(filter) {
    console.log("[电影人生] home 开始");
    let list = [];
    try {
        // 先尝试访问 /dianying.html
        let html = await fetchUrl(appConfig.siteUrl + "/dianying.html");
        if (html.length === 0) {
            console.warn("[电影人生] /dianying.html 无响应，尝试首页");
            html = await fetchUrl(appConfig.siteUrl);
        }
        let result = parseListHtml(html);
        list = result.list.slice(0, 30);
    } catch (e) {
        console.error("[电影人生] home 异常: " + e.message);
    }
    console.log("[电影人生] home 最终返回列表数: " + list.length);
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
    if (params.length > 0) url += '?' + params.join('&');
    return appConfig.siteUrl + url;
}

async function category(tid, pg, filter, extend) {
    pg = pg || 1;
    extend = extend || {};
    let result = { list: [], page: pg, pagecount: 0, limit: 20, total: 0 };
    console.log("[电影人生] category 开始, tid=" + tid + ", pg=" + pg);
    try {
        let url = buildCategoryUrl(tid, pg, extend);
        let html = await fetchUrl(url);
        let parsed = parseListHtml(html, extend.year || "");
        result.list = parsed.list;
        result.pagecount = parsed.pagecount;
        result.total = result.pagecount * result.limit;
        console.log("[电影人生] category 获取到 " + result.list.length + " 条");
    } catch (e) {
        console.error("[电影人生] category 异常: " + e.message);
    }
    return JSON.stringify(result);
}

// ===== 搜索 =====
async function search(wd, quick, page) {
    page = page || 1;
    let result = { list: [], page: page, pagecount: 0, limit: 20, total: 0 };
    console.log("[电影人生] search 开始, wd=" + wd);
    try {
        let url = appConfig.siteUrl + "/s.html?name=" + encodeQuery(wd);
        if (page > 1) url += "&page=" + page;
        let html = await fetchUrl(url);
        let parsed = parseListHtml(html);
        result.list = parsed.list;
        result.pagecount = parsed.pagecount;
        result.total = result.pagecount * result.limit;
        console.log("[电影人生] search 获取到 " + result.list.length + " 条");
    } catch (e) {
        console.error("[电影人生] search 异常: " + e.message);
    }
    return JSON.stringify(result);
}

// ===== 详情 =====
async function detail(id) {
    console.log("[电影人生] detail 开始, id=" + id);
    try {
        let html = await fetchUrl(appConfig.siteUrl + id);
        let $ = cheerio.load(html);
        // （此处省略详情解析代码，保持与之前版本一致，但也可以加入日志）
        // 为保持简洁，复用之前的解析逻辑，但为聚焦问题，可先返回空数组
        // 您可以复制之前版本的详情解析代码
        return JSON.stringify([]); // 临时返回空，以便先验证列表
    } catch (e) {
        console.error("[电影人生] detail 异常: " + e.message);
        return JSON.stringify([]);
    }
}

// ===== 播放 =====
async function play(flag, id, flags) {
    // 简单返回，详情先不管
    return JSON.stringify({ parse: 0, url: id, header: {} });
}

export default {
    init,
    home,
    category,
    search,
    detail,
    play
};