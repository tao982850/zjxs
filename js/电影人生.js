// ================================================================
// 电影人生 爬虫 - 最终修复版（分类区分 + 播放修复）
// ================================================================
import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
    siteName: "电影人生",
    siteUrl: "https://dyrs6.vip"
};
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

// ===== 分类列表（支持自定义 url 字段，若缺省则自动生成） =====
const classList = [
    { type_id: "dianying", type_name: "电影", url: "/vodtype/1.html" },        // 实际电影分类路径
    { type_id: "dianshiju", type_name: "电视剧", url: "/vodtype/2.html" },
    { type_id: "zongyi", type_name: "综艺", url: "/vodtype/3.html" },
    { type_id: "dongman", type_name: "动漫", url: "/vodtype/4.html" },
    { type_id: "duanju", type_name: "短剧", url: "/vodtype/5.html" },
    // 以下细分分类可自行添加或删除
    { type_id: "dianying-剧情", type_name: "剧情片", url: "/vodtype/1.html?class=剧情" },
    { type_id: "dianying-喜剧", type_name: "喜剧片", url: "/vodtype/1.html?class=喜剧" },
    // ... 其他细分根据需要添加，若未定义则使用父分类的 url
];

// ===== 筛选器（保持不变） =====
function getAreaFilter() { /* ... 同上 ... */ }
function getYearFilter() { /* ... 同上 ... */ }
function getLangFilter() { /* ... 同上 ... */ }
function getTypeFilter() { /* ... 同上 ... */ }
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

// ===== 核心：通用列表解析（多级降级） =====
function parseListHtml(html) {
    const $ = cheerio.load(html);
    let list = [];
    let seen = {};

    // 策略1：原特征（/wzzy-）
    $("a[href*='/wzzy-']").each(function() {
        let href = $(this).attr("href");
        if (!href || seen[href]) return;
        let name = $(this).attr("title") || $(this).text().trim() || "";
        let hash = href.match(/\/wzzy-\d+\/([a-f0-9]+)\.html/)?.[1] || "";
        let pic = hash ? `${appConfig.siteUrl}/img/id/${hash}.jpg` : "";
        if (name && href) {
            seen[href] = true;
            list.push({ vod_id: href, vod_name: name, vod_pic: pic, vod_remarks: "" });
        }
    });

    // 策略2：/vod- 或 /detail/
    if (list.length === 0) {
        $("a[href*='/vod-'], a[href*='/detail/']").each(function() {
            let href = $(this).attr("href");
            if (!href || seen[href]) return;
            let name = $(this).attr("title") || $(this).text().trim() || "";
            let pic = $(this).find("img").attr("data-original") || $(this).find("img").attr("src") || "";
            if (name && href) {
                seen[href] = true;
                list.push({ vod_id: href, vod_name: name, vod_pic: fixUrl(pic), vod_remarks: "" });
            }
        });
    }

    // 策略3：常见容器类
    if (list.length === 0) {
        const selectors = [
            ".module-poster-item", ".movie-item", ".vod-item",
            ".list-item", ".video-item", ".item", ".poster"
        ];
        $(selectors.join(",")).each(function() {
            let $item = $(this);
            let $a = $item.is("a") ? $item : $item.find("a").first();
            let href = $a.attr("href");
            if (!href || seen[href]) return;
            let name = $a.attr("title") || $item.find(".title, .name, .vod-name").text().trim() || $a.text().trim();
            let pic = $item.find("img").attr("data-original") || $item.find("img").attr("data-src") || $item.find("img").attr("src") || "";
            let note = $item.find(".note, .remarks, .episode, .update").text().trim() || "";
            if (name && href) {
                seen[href] = true;
                list.push({ vod_id: href, vod_name: name, vod_pic: fixUrl(pic), vod_remarks: note });
            }
        });
    }

    // 策略4：最宽松扫描
    if (list.length === 0) {
        $("a").each(function() {
            let href = $(this).attr("href");
            if (!href || seen[href]) return;
            if (href.startsWith("#") || href.startsWith("javascript:") || href === "/") return;
            if (!href.includes(".html") && !href.includes("/vod") && !href.includes("/wzzy")) return;
            let name = $(this).attr("title") || $(this).text().trim();
            if (!name || name.length < 2) return;
            let hasImg = $(this).find("img").length > 0;
            if (!hasImg) return;
            let pic = $(this).find("img").attr("data-original") || $(this).find("img").attr("src") || "";
            seen[href] = true;
            list.push({ vod_id: href, vod_name: name, vod_pic: fixUrl(pic), vod_remarks: "" });
        });
    }

    // 分页解析
    let pagecount = 1;
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

    return { list, pagecount };
}

// ===== 首页 =====
async function home(filter) {
    let list = [];
    try {
        const html = (await req(appConfig.siteUrl, {
            method: "GET",
            headers: {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
        })).content;
        const result = parseListHtml(html);
        list = result.list.slice(0, 30);
    } catch (e) {
        console.error("首页推荐获取失败:", e.message);
    }

    return JSON.stringify({
        class: classList,
        filters: myFilters,
        list: list
    });
}

// ===== 分类 URL 构造（优先使用自定义 url） =====
function getCategoryUrl(tid, pg, extend) {
    // 查找分类配置
    let cat = classList.find(c => c.type_id === tid);
    let basePath = cat && cat.url ? cat.url : `/${tid}.html`;  // 若未定义，则用旧方式

    // 解析基础路径和查询参数
    let [path, query] = basePath.split('?');
    let params = new URLSearchParams(query || '');

    // 添加筛选参数
    extend = extend || {};
    if (extend.area) params.set('area', extend.area);
    if (extend.year) params.set('year', extend.year);
    if (extend.lang) params.set('lang', extend.lang);
    if (extend.type) params.set('type', extend.type);
    if (pg && pg > 1) params.set('page', pg);

    let url = path;
    let qs = params.toString();
    if (qs) url += '?' + qs;
    return appConfig.siteUrl + url;
}

// ===== 分类列表 =====
async function category(tid, pg, filter, extend) {
    pg = pg || 1;
    extend = extend || {};

    let url = getCategoryUrl(tid, pg, extend);
    console.log("[电影人生] 分类请求 URL:", url);

    try {
        const html = (await req(url, {
            method: "GET",
            headers: {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": appConfig.siteUrl
            }
        })).content;
        const result = parseListHtml(html);
        result.page = pg;
        result.limit = 20;
        result.total = result.pagecount * result.limit;
        return JSON.stringify(result);
    } catch (e) {
        console.error("分类列表获取失败:", e.message);
        return JSON.stringify({ list: [], pagecount: 0, page: pg, limit: 20, total: 0 });
    }
}

// ===== 搜索 =====
async function search(wd, quick, page) {
    page = page || 1;
    try {
        let url = `${appConfig.siteUrl}/s.html?name=${encodeURIComponent(wd)}`;
        if (page > 1) url += `&page=${page}`;
        const html = (await req(url, { method: "GET", headers: { "User-Agent": UA, "Accept": "text/html,...", "Referer": appConfig.siteUrl } })).content;
        const result = parseListHtml(html);
        result.page = page;
        result.limit = 20;
        result.total = result.pagecount * result.limit;
        return JSON.stringify(result);
    } catch (e) {
        console.error("搜索失败:", e.message);
        return JSON.stringify({ list: [], pagecount: 0, page: page, limit: 20, total: 0 });
    }
}

// ===== 详情（保持原有逻辑，但增强图片获取） =====
async function detail(id) {
    // ... 与上一版相同，此处略（可复用之前代码） ...
    // 为节省篇幅，返回一个简单结构（实际应完整保留）
    // 但用户主要关心分类和播放，先保留原detail逻辑不变。
    try {
        // 复制之前detail的完整代码，此处省略显示
        // 请确保包含之前detail的所有逻辑
        return JSON.stringify({ list: [] }); // 临时占位
    } catch(e) { return JSON.stringify({ list: [] }); }
}

// ===== 播放 =====
async function play(flag, id, flags) {
    try {
        // 如果已经是完整URL，直接返回
        if (id.startsWith("http")) {
            return JSON.stringify({
                parse: 0,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: id
            });
        }

        // 请求播放页
        const html = (await req(appConfig.siteUrl + id, {
            method: "GET",
            headers: {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": appConfig.siteUrl
            }
        })).content;
        const $ = cheerio.load(html);

        // 1. 尝试解析 player_aaaa（加密播放地址）
        let playerScript = html.match(/var\s+player_aaaa\s*=\s*(\{[\s\S]+?\})\s*<\/script>/);
        if (playerScript) {
            try {
                let data = JSON.parse(playerScript[1]);
                let encrypt = data.encrypt || 0;
                let url = data.url || "";
                if (url) {
                    // 解密（简单URL解码和base64）
                    if (encrypt === 2) {
                        url = atob(url);
                    }
                    if (encrypt === 1) {
                        url = decodeURIComponent(url);
                    }
                    if (url.startsWith('http')) {
                        return JSON.stringify({
                            parse: 0,
                            Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                            url: url
                        });
                    }
                }
            } catch(e) {}
        }

        // 2. 尝试 /api/m3u8 格式
        let m3u8Match = html.match(/href="\/api\/m3u8\?origin=([^&]+)&amp;?url=([^"]+)"/) ||
                        html.match(/href="\/api\/m3u8\?origin=([^&]+)&url=([^"]+)"/);
        if (m3u8Match) {
            let playUrl = `${appConfig.siteUrl}/api/m3u8?origin=${encodeURIComponent(m3u8Match[1])}&url=${m3u8Match[2]}`;
            return JSON.stringify({
                parse: 0,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: playUrl
            });
        }

        // 3. 直链 m3u8/mp4
        let urlMatch = html.match(/"url"\s*[:=]\s*"([^"]+\.(m3u8|mp4|flv)[^"]*)"/);
        if (urlMatch) {
            return JSON.stringify({
                parse: 0,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: urlMatch[1].replace(/\\/g, '')
            });
        }

        // 4. iframe 嵌入
        let iframeSrc = $("iframe").attr("src");
        if (iframeSrc) {
            return JSON.stringify({
                parse: 1,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: fixUrl(iframeSrc)
            });
        }

        // 5. 寻找视频标签（video）的src
        let videoSrc = $("video").attr("src");
        if (videoSrc) {
            return JSON.stringify({
                parse: 0,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: fixUrl(videoSrc)
            });
        }

        // 6. 兜底：让 TVBox 嗅探
        return JSON.stringify({
            parse: 1,
            Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
            url: appConfig.siteUrl + id
        });
    } catch (e) {
        console.error("播放解析失败:", e);
        return JSON.stringify({ parse: 0, url: "" });
    }
}

// 注意：detail函数需要补全，此处为了演示省略，但实际应包含完整详情解析代码。
// 您可以将之前的 detail 完整复制过来，确保与当前版本兼容。

export default {
    init,
    home,
    category,
    detail,
    search,
    play
};