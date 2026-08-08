// ================================================================
// 电影人生 爬虫 - 动态分类发现版（自适应站点结构）
// ================================================================
import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
    siteName: "电影人生",
    siteUrl: "https://dyrs6.vip"
};
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

// 动态分类列表（init时填充）
let classList = [];
let myFilters = {};

// ===== 筛选器函数（完整保留） =====
function getAreaFilter() {
    return {
        "key": "area", "name": "地区", "value": [
            { "n": "全部", "v": "" }, { "n": "大陆", "v": "大陆" }, { "n": "香港", "v": "香港" },
            { "n": "台湾", "v": "台湾" }, { "n": "美国", "v": "美国" }, { "n": "日本", "v": "日本" },
            { "n": "韩国", "v": "韩国" }, { "n": "英国", "v": "英国" }, { "n": "法国", "v": "法国" },
            { "n": "德国", "v": "德国" }, { "n": "泰国", "v": "泰国" }, { "n": "印度", "v": "印度" },
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
            { "n": "全部", "v": "" }, { "n": "国语", "v": "国语" }, { "n": "粤语", "v": "粤语" },
            { "n": "英语", "v": "英语" }, { "n": "日语", "v": "日语" }, { "n": "韩语", "v": "韩语" },
            { "n": "其他", "v": "其他" }
        ]
    };
}
function getTypeFilter() {
    return {
        "key": "type", "name": "类型", "value": [
            { "n": "全部", "v": "" }, { "n": "剧情", "v": "剧情" }, { "n": "喜剧", "v": "喜剧" },
            { "n": "动作", "v": "动作" }, { "n": "爱情", "v": "爱情" }, { "n": "科幻", "v": "科幻" },
            { "n": "恐怖", "v": "恐怖" }, { "n": "悬疑", "v": "悬疑" }, { "n": "犯罪", "v": "犯罪" },
            { "n": "动画", "v": "动画" }, { "n": "冒险", "v": "冒险" }, { "n": "奇幻", "v": "奇幻" },
            { "n": "战争", "v": "战争" }, { "n": "纪录片", "v": "纪录片" }
        ]
    };
}
const commonFilters = [getAreaFilter(), getYearFilter(), getLangFilter(), getTypeFilter()];

// ===== 工具函数 =====
function fixUrl(u) {
    if (!u) return '';
    if (u.startsWith('http')) return u;
    if (u.startsWith('//')) return 'https:' + u;
    if (u.startsWith('/')) return appConfig.siteUrl + u;
    return u;
}

// ===== 初始化：自动发现分类 =====
async function init(ext) {
    console.log("[电影人生] 初始化，自动发现分类...");
    try {
        const resp = await req(appConfig.siteUrl, {
            method: "GET",
            headers: {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
        });
        const html = resp.content || "";
        if (!html) throw new Error("首页为空");
        const $ = cheerio.load(html);

        // 提取导航链接
        let navLinks = [];
        // 常见导航选择器（可扩充）
        const selectors = [
            ".nav a", ".menu a", ".header a", ".top-nav a",
            "ul.nav li a", ".nav-list a", ".category-nav a",
            ".nav-item a", ".nav-link a", "#nav a"
        ];
        $(selectors.join(",")).each(function() {
            let href = $(this).attr("href");
            let text = $(this).text().trim();
            if (href && text && href.startsWith('/')) {
                // 排除首页、登录、注册等
                if (href === '/' || href === '/index.html' || href.includes('login') || href.includes('register') || href.includes('#')) return;
                // 优先选择包含分类关键词的链接
                if (href.includes('dianying') || href.includes('dianshiju') || href.includes('zongyi') || href.includes('dongman') || href.includes('duanju') ||
                    href.includes('vodtype') || href.includes('category') || href.includes('list')) {
                    navLinks.push({ url: href, name: text });
                }
            }
        });

        // 如果没找到，使用硬编码回退（但尽量使用发现的）
        if (navLinks.length === 0) {
            console.warn("[电影人生] 未从导航发现分类，使用默认硬编码");
            navLinks = [
                { url: "/dianying.html", name: "电影" },
                { url: "/dianshiju.html", name: "电视剧" },
                { url: "/zongyi.html", name: "综艺" },
                { url: "/dongman.html", name: "动漫" },
                { url: "/duanju.html", name: "短剧" }
            ];
        }

        // 去重，生成 classList
        let seen = {};
        classList = [];
        navLinks.forEach(item => {
            let type_id = item.url.replace(/^\//, '').replace(/\.html$/, '').replace(/[^a-zA-Z0-9-]/g, '-');
            if (!seen[type_id]) {
                seen[type_id] = true;
                classList.push({ type_id: type_id, type_name: item.name, url: item.url });
            }
        });

        // 生成筛选器
        myFilters = {};
        classList.forEach(item => {
            myFilters[item.type_id] = commonFilters;
        });

        console.log("[电影人生] 发现分类:", classList.map(c => c.type_name + " -> " + c.url).join(", "));
    } catch (e) {
        console.error("[电影人生] init 异常:", e.message);
        // 回退硬编码
        classList = [
            { type_id: "dianying", type_name: "电影", url: "/dianying.html" },
            { type_id: "dianshiju", type_name: "电视剧", url: "/dianshiju.html" },
            { type_id: "zongyi", type_name: "综艺", url: "/zongyi.html" },
            { type_id: "dongman", type_name: "动漫", url: "/dongman.html" },
            { type_id: "duanju", type_name: "短剧", url: "/duanju.html" }
        ];
        myFilters = {};
        classList.forEach(item => {
            myFilters[item.type_id] = commonFilters;
        });
    }
}

// ===== 列表解析（只匹配 /wzzy- 链接，稳定） =====
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
    if (!classList.length) await init();
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

// ===== 分类 URL 构造（使用发现的 URL） =====
async function category(tid, pg, filter, extend) {
    if (!classList.length) await init();
    pg = pg || 1;
    extend = extend || {};
    let cat = classList.find(c => c.type_id === tid);
    if (!cat) {
        console.warn("[电影人生] 未找到分类ID:", tid);
        return JSON.stringify({ list: [], pagecount: 0, page: pg, limit: 20, total: 0 });
    }
    let baseUrl = cat.url; // 如 "/dianying.html" 或 "/vodtype/1.html"
    // 解析路径和已有查询参数
    let [path, query] = baseUrl.split('?');
    let params = new URLSearchParams(query || '');
    // 添加筛选参数（仅当有值时才加）
    if (extend.area) params.set('area', extend.area);
    if (extend.year) params.set('year', extend.year);
    if (extend.lang) params.set('lang', extend.lang);
    if (extend.type) params.set('type', extend.type);
    if (pg && pg > 1) params.set('page', pg);
    let url = path;
    let qs = params.toString();
    if (qs) url += '?' + qs;
    let fullUrl = appConfig.siteUrl + url;
    console.log("[电影人生] 分类请求:", fullUrl);

    try {
        const html = (await req(fullUrl, {
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

// ===== 搜索（原版） =====
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

// ===== 详情（原版完整） =====
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

        let vod_name = "", vod_director = "", vod_actor = "", vod_year = "", vod_area = "", vod_class = "", vod_content = "", vod_pic = "";
        let hash = id.match(/\/wzzy-\d+\/([a-f0-9]+)\.html/)?.[1] || "";
        vod_pic = hash ? `${appConfig.siteUrl}/img/id/${hash}.jpg` : "";

        $('script[type="application/ld+json"]').each(function () {
            try {
                let data = JSON.parse($(this).html());
                if (data) {
                    if (data.name) vod_name = data.name;
                    if (data.year) vod_year = String(data.year);
                    if (data.countryOfOrigin) vod_area = data.countryOfOrigin;
                    if (data.inLanguage) vod_class = data.inLanguage;
                    if (data.description) vod_content = data.description.replace(/<br \/>/g, "\n").replace(/　/g, "").trim();
                    if (data.director && data.director.name) vod_director = data.director.name;
                    if (data.actor && Array.isArray(data.actor)) {
                        vod_actor = data.actor.map(a => a.name).filter(Boolean).join(',');
                    }
                }
            } catch (e) {}
        });

        if (!vod_name) {
            vod_name = $("title").text().replace(/《|》/g, "").replace(/-.*$/, "").trim() || "";
        }
        if (!vod_actor) {
            let desc = $('meta[name="description"]').attr("content") || "";
            let actorMatch = desc.match(/主演包括([^。]+)/);
            if (actorMatch) vod_actor = actorMatch[1].trim();
        }
        if (!vod_director) {
            $("p, div, span").each(function () {
                let text = $(this).text();
                if (text.includes("导演") && !vod_director) {
                    let match = text.match(/导演[：:]\s*([^\n\r]+)/);
                    if (match) vod_director = match[1].trim().split(/[,，、\s]/)[0];
                }
            });
        }
        if (!vod_class) {
            $("a[href*='class=']").each(function () {
                let href = $(this).attr("href") || '';
                if (href.includes("class=") && !href.includes("sso")) {
                    let m = href.match(/class=([^&]+)/);
                    if (m && !vod_class) vod_class = decodeURIComponent(m[1]);
                }
            });
        }

        let vod_remarks = "";
        // 播放线路解析（原版）
        let lines = [], playlists = [];
        let originEpisodes = {};
        $("#episodeContent a[href]").each(function () {
            let href = $(this).attr("href") || "";
            let name = $(this).attr("data-title") || $(this).text().trim() || "";
            let origin = $(this).attr("data-origin") || "";
            if (href && name && origin) {
                let pMatch = href.match(/[?&]p=(\d+)/);
                let p = pMatch ? parseInt(pMatch[1]) : 0;
                if (!originEpisodes[origin]) originEpisodes[origin] = [];
                originEpisodes[origin].push({ name, href, p });
            }
        });
        let originOrder = [];
        $("[id$='Tab'][data-origin]").each(function () {
            let origin = $(this).attr("data-origin");
            if (origin && !originOrder.includes(origin)) originOrder.push(origin);
        });
        if (originOrder.length === 0) originOrder = Object.keys(originEpisodes);
        let templateOrigin = Object.keys(originEpisodes)[0];
        let templateEpisodes = templateOrigin ? originEpisodes[templateOrigin] : [];
        originOrder.forEach(origin => {
            let eps = originEpisodes[origin];
            if (!eps || eps.length === 0) {
                if (templateEpisodes.length === 0) return;
                eps = templateEpisodes.map(ep => {
                    let newHref = ep.href.replace(/origin=[^&]+/, 'origin=' + encodeURIComponent(origin));
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
                vod_id: id, vod_name, vod_pic, vod_actor, vod_director,
                vod_remarks, vod_year, vod_area, vod_content, vod_class,
                vod_play_from, vod_play_url
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

        // player_aaaa
        let playerScript = html.match(/var\s+player_aaaa\s*=\s*(\{[\s\S]+?\})\s*<\/script>/);
        if (playerScript) {
            try {
                let data = JSON.parse(playerScript[1]);
                let encrypt = data.encrypt || 0;
                let url = data.url || "";
                if (url) {
                    if (encrypt === 2) url = atob(url);
                    if (encrypt === 1) url = decodeURIComponent(url);
                    if (url.startsWith('http')) {
                        return JSON.stringify({ parse: 0, Header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url });
                    }
                }
            } catch(e) {}
        }

        // /api/m3u8
        let m3u8Match = html.match(/href="\/api\/m3u8\?origin=([^&]+)&amp;?url=([^"]+)"/) ||
                        html.match(/href="\/api\/m3u8\?origin=([^&]+)&url=([^"]+)"/);
        if (m3u8Match) {
            let playUrl = `${appConfig.siteUrl}/api/m3u8?origin=${encodeURIComponent(m3u8Match[1])}&url=${m3u8Match[2]}`;
            return JSON.stringify({ parse: 0, Header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: playUrl });
        }

        // 直链
        let urlMatch = html.match(/"url"\s*[:=]\s*"([^"]+\.(m3u8|mp4|flv)[^"]*)"/);
        if (urlMatch) {
            return JSON.stringify({ parse: 0, Header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: urlMatch[1].replace(/\\/g, '') });
        }

        // iframe
        const $ = cheerio.load(html);
        let iframeSrc = $("iframe").attr("src");
        if (iframeSrc) {
            return JSON.stringify({ parse: 1, Header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: fixUrl(iframeSrc) });
        }

        // video标签
        let videoSrc = $("video").attr("src");
        if (videoSrc) {
            return JSON.stringify({ parse: 0, Header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: fixUrl(videoSrc) });
        }

        // 兜底
        return JSON.stringify({ parse: 1, Header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: appConfig.siteUrl + id });
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