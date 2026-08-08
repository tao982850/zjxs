// ================================================================
// 电影人生 爬虫 - 稳定版（修复分类和播放）
// 基于原可用解析逻辑，增强分类和播放处理
// ================================================================
import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
    siteName: "电影人生",
    siteUrl: "https://dyrs6.vip"
};
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

async function init(ext) {
    console.log("初始化爬虫:", appConfig.siteName);
}

// ===== 分类列表（使用原版 type_id，对应页面名） =====
const classList = [
    { type_id: "dianying", type_name: "电影" },
    { type_id: "dianshiju", type_name: "电视剧" },
    { type_id: "zongyi", type_name: "综艺" },
    { type_id: "dongman", type_name: "动漫" },
    { type_id: "duanju", type_name: "短剧" },
    // 细分分类可以保留，但为了简化，只保留主分类，细分可在筛选器中处理
];

// ===== 筛选器（与原版相同） =====
function getAreaFilter() {
    return {
        "key": "area", "name": "地区", "value": [
            { "n": "全部", "v": "" },
            { "n": "大陆", "v": "大陆" },
            { "n": "香港", "v": "香港" },
            { "n": "台湾", "v": "台湾" },
            { "n": "美国", "v": "美国" },
            { "n": "日本", "v": "日本" },
            { "n": "韩国", "v": "韩国" },
            { "n": "英国", "v": "英国" },
            { "n": "法国", "v": "法国" },
            { "n": "德国", "v": "德国" },
            { "n": "泰国", "v": "泰国" },
            { "n": "印度", "v": "印度" },
            { "n": "其他", "v": "其他" }
        ]
    };
}

function getYearFilter() {
    let years = [{ "n": "全部", "v": "" }];
    const currentYear = new Date().getFullYear();
    for (let y = currentYear; y >= 2010; y--) {
        years.push({ "n": String(y), "v": String(y) });
    }
    return { "key": "year", "name": "年份", "value": years };
}

function getLangFilter() {
    return {
        "key": "lang", "name": "语言", "value": [
            { "n": "全部", "v": "" },
            { "n": "国语", "v": "国语" },
            { "n": "粤语", "v": "粤语" },
            { "n": "英语", "v": "英语" },
            { "n": "日语", "v": "日语" },
            { "n": "韩语", "v": "韩语" },
            { "n": "其他", "v": "其他" }
        ]
    };
}

function getTypeFilter() {
    return {
        "key": "type", "name": "类型", "value": [
            { "n": "全部", "v": "" },
            { "n": "剧情", "v": "剧情" },
            { "n": "喜剧", "v": "喜剧" },
            { "n": "动作", "v": "动作" },
            { "n": "爱情", "v": "爱情" },
            { "n": "科幻", "v": "科幻" },
            { "n": "恐怖", "v": "恐怖" },
            { "n": "悬疑", "v": "悬疑" },
            { "n": "犯罪", "v": "犯罪" },
            { "n": "动画", "v": "动画" },
            { "n": "冒险", "v": "冒险" },
            { "n": "奇幻", "v": "奇幻" },
            { "n": "战争", "v": "战争" },
            { "n": "纪录片", "v": "纪录片" }
        ]
    };
}

const commonFilters = [getAreaFilter(), getYearFilter(), getLangFilter(), getTypeFilter()];
const myFilters = {};
classList.forEach(item => {
    myFilters[item.type_id] = commonFilters;
});

// ===== 工具函数 =====
function fixUrl(u) {
    if (!u) return '';
    if (u.startsWith('http')) return u;
    if (u.startsWith('//')) return 'https:' + u;
    if (u.startsWith('/')) return appConfig.siteUrl + u;
    return u;
}

// ===== 原版列表解析（仅匹配 /wzzy- 链接，稳定可靠） =====
function parseListHtml(html) {
    const $ = cheerio.load(html);
    let list = [];
    let seen = {};

    $("a[href*='/wzzy-']").each(function () {
        let vod_id = $(this).attr("href");
        if (!vod_id || seen[vod_id]) return;
        if (!vod_id.startsWith('/wzzy-')) return;

        let vod_name = $(this).attr("title") || $(this).text().trim() || "";
        let hash = vod_id.match(/\/wzzy-\d+\/([a-f0-9]+)\.html/)?.[1] || "";
        let vod_pic = hash ? `${appConfig.siteUrl}/img/id/${hash}.jpg` : "";
        let vod_remarks = "";

        if (vod_name && vod_id) {
            seen[vod_id] = true;
            list.push({ vod_id, vod_name, vod_pic, vod_remarks });
        }
    });

    let pagecount = 1;
    $("a[href*='page=']").each(function () {
        let href = $(this).attr("href") || '';
        let m = href.match(/page=(\d+)/);
        if (m) {
            let p = parseInt(m[1]);
            if (p > pagecount) pagecount = p;
        }
    });

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

// ===== 分类 URL 构造（使用原版 /${tid}.html） =====
function buildCategoryUrl(tid, pg, extend) {
    extend = extend || {};
    let baseType = tid.split('-')[0];
    let subType = tid.split('-')[1] || '';

    if (!subType && extend.type) {
        subType = extend.type;
    }

    let url = `/${baseType}.html`;
    let params = [];
    
    if (subType) params.push(`class=${encodeURIComponent(subType)}`);
    if (extend.area) params.push(`area=${encodeURIComponent(extend.area)}`);
    if (extend.year) params.push(`year=${encodeURIComponent(extend.year)}`);
    if (extend.lang) params.push(`lang=${encodeURIComponent(extend.lang)}`);
    if (pg && pg > 1) params.push(`page=${pg}`);

    if (params.length > 0) {
        url += '?' + params.join('&');
    }

    console.log("[电影人生] 分类URL:", appConfig.siteUrl + url);
    return appConfig.siteUrl + url;
}

// ===== 分类列表 =====
async function category(tid, pg, filter, extend) {
    pg = pg || 1;
    extend = extend || {};

    let url = buildCategoryUrl(tid, pg, extend);

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
        const html = (await req(url, {
            method: "GET",
            headers: {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": appConfig.siteUrl
            }
        })).content;
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

// ===== 详情（完整恢复原版功能） =====
async function detail(id) {
    try {
        const html = (await req(appConfig.siteUrl + id, {
            method: "GET",
            headers: {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": appConfig.siteUrl
            }
        })).content;
        const $ = cheerio.load(html);

        let vod_name = "";
        let vod_director = "";
        let vod_actor = "";
        let vod_year = "";
        let vod_area = "";
        let vod_class = "";
        let vod_content = "";
        let vod_pic = "";

        let hash = id.match(/\/wzzy-\d+\/([a-f0-9]+)\.html/)?.[1] || "";
        vod_pic = hash ? `${appConfig.siteUrl}/img/id/${hash}.jpg` : "";

        $('script[type="application/ld+json"]').each(function () {
            try {
                let jsonText = $(this).html();
                if (!jsonText) return;
                let data = JSON.parse(jsonText);
                if (data && data.name) vod_name = data.name;
                if (data && data.year) vod_year = String(data.year);
                if (data && data.countryOfOrigin) vod_area = data.countryOfOrigin;
                if (data && data.inLanguage) {
                    vod_class = data.inLanguage;
                }
                if (data && data.description) {
                    vod_content = data.description.replace(/<br \/>/g, "\n").replace(/　/g, "").trim();
                }
                if (data && data.director) {
                    if (data.director.name) vod_director = data.director.name;
                }
                if (data && data.actor && Array.isArray(data.actor)) {
                    let actors = data.actor.map(a => a.name).filter(Boolean);
                    vod_actor = actors.join(',');
                }
            } catch (e) {}
        });

        if (!vod_name) {
            vod_name = $("title").text().replace(/《|》/g, "").replace(/-.*$/, "").trim() || "";
        }

        if (!vod_actor) {
            let desc = $('meta[name="description"]').attr("content") || "";
            let actorMatch = desc.match(/主演包括([^。]+)/);
            if (actorMatch) {
                vod_actor = actorMatch[1].trim();
            }
        }

        if (!vod_director) {
            $("p, div, span").each(function () {
                let text = $(this).text();
                if (text.includes("导演") && !vod_director) {
                    let match = text.match(/导演[：:]\s*([^\n\r]+)/);
                    if (match) {
                        vod_director = match[1].trim().split(/[,，、\s]/)[0];
                    }
                }
            });
        }

        if (!vod_class) {
            $("a[href*='class=']").each(function () {
                let href = $(this).attr("href") || '';
                if (href.includes("class=") && !href.includes("sso")) {
                    let m = href.match(/class=([^&]+)/);
                    if (m) {
                        if (!vod_class) vod_class = decodeURIComponent(m[1]);
                    }
                }
            });
        }

        let vod_remarks = "";

        // ===== 播放线路解析（原版） =====
        let lines = [];
        let playlists = [];

        let originEpisodes = {};

        $("#episodeContent a[href]").each(function () {
            let href = $(this).attr("href") || "";
            let name = $(this).attr("data-title") || $(this).text().trim() || "";
            let origin = $(this).attr("data-origin") || "";
            
            if (href && name && origin) {
                let pMatch = href.match(/[?&]p=(\d+)/);
                let p = pMatch ? parseInt(pMatch[1]) : 0;
                
                if (!originEpisodes[origin]) {
                    originEpisodes[origin] = [];
                }
                originEpisodes[origin].push({ name, href, p });
            }
        });

        let originOrder = [];
        $("[id$='Tab'][data-origin]").each(function () {
            let origin = $(this).attr("data-origin");
            if (origin && !originOrder.includes(origin)) {
                originOrder.push(origin);
            }
        });

        if (originOrder.length === 0) {
            originOrder = Object.keys(originEpisodes);
        }

        let templateOrigin = Object.keys(originEpisodes)[0];
        let templateEpisodes = templateOrigin ? originEpisodes[templateOrigin] : [];

        originOrder.forEach(origin => {
            let eps = originEpisodes[origin];
            
            if (!eps || eps.length === 0) {
                if (templateEpisodes.length === 0) return;
                eps = templateEpisodes.map(ep => {
                    let newHref = ep.href.replace(
                        /origin=[^&]+/,
                        'origin=' + encodeURIComponent(origin)
                    );
                    return { name: ep.name, href: newHref, p: ep.p };
                });
            }

            eps.sort((a, b) => a.p - b.p);

            let lineEpisodes = eps.map(ep => `${ep.name}$${ep.href}`);
            
            lines.push(origin);
            playlists.push(lineEpisodes);
        });

        if (lines.length === 0) {
            lines.push("默认");
            playlists.push([`暂无播放地址$${id}`]);
        }

        const { vod_play_from, vod_play_url } = buildVodPlayData(lines, playlists);

        return JSON.stringify({
            list: [{
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
            }]
        });
    } catch (error) {
        console.error(`解析详情页异常 [ID: ${id}]:`, error);
        return JSON.stringify({ list: [] });
    }
}

function buildVodPlayData(lines, playlists) {
    const processedPlaylists = playlists.map(eps => eps.join('#'));
    return {
        vod_play_from: lines.filter(Boolean).join('$$$'),
        vod_play_url: processedPlaylists.join('$$$')
    };
}

// ===== 播放（增强解密） =====
async function play(flag, id, flags) {
    try {
        if (id.startsWith("http")) {
            return JSON.stringify({
                parse: 0,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: id
            });
        }

        const html = (await req(`${appConfig.siteUrl}${id}`, {
            method: "GET",
            headers: {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": appConfig.siteUrl
            }
        })).content;

        // 1. 尝试解析 player_aaaa（加密播放地址）
        let playerScript = html.match(/var\s+player_aaaa\s*=\s*(\{[\s\S]+?\})\s*<\/script>/);
        if (playerScript) {
            try {
                let data = JSON.parse(playerScript[1]);
                let encrypt = data.encrypt || 0;
                let url = data.url || "";
                if (url) {
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

        // 4. iframe
        const $ = cheerio.load(html);
        let iframeSrc = $("iframe").attr("src");
        if (iframeSrc) {
            return JSON.stringify({
                parse: 1,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: fixUrl(iframeSrc)
            });
        }

        // 5. video标签
        let videoSrc = $("video").attr("src");
        if (videoSrc) {
            return JSON.stringify({
                parse: 0,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: fixUrl(videoSrc)
            });
        }

        // 6. 兜底
        return JSON.stringify({
            parse: 1,
            Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
            url: appConfig.siteUrl + id
        });
    } catch (e) {
        console.error("播放失败:", e);
        return JSON.stringify({ parse: 0, url: "" });
    }
}

export default {
    init,
    home,
    category,
    detail,
    search,
    play
};