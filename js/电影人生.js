// ================================================================
// 电影人生 爬虫 - TVBox/影视仓 ES模块格式
// 遵循 《接口源开发指南》 数据契约 v1.0
// 站点: https://dyrs6.vip
// ================================================================
import cheerio from 'assets://js/lib/cheerio.min.js';

// ===== 站点配置 =====
const appConfig = {
    siteName: "电影人生",
    siteUrl: "https://dyrs6.vip"          // 主域名，若失效可更换
};
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

// 备用域名（自动探测）
const fallbackDomains = [
    "https://dyrs6.vip",
    "https://dyrs7.vip",
    "https://dyrs8.vip"
];

// ===== 分类映射（符合指南 class_name / class_url 结构） =====
const classList = [
    { type_id: "dianying", type_name: "电影" },
    { type_id: "dianshiju", type_name: "电视剧" },
    { type_id: "zongyi", type_name: "综艺" },
    { type_id: "dongman", type_name: "动漫" },
    { type_id: "duanju", type_name: "短剧" },
    { type_id: "dianying-剧情", type_name: "剧情片" },
    { type_id: "dianying-喜剧", type_name: "喜剧片" },
    { type_id: "dianying-动作", type_name: "动作片" },
    { type_id: "dianying-爱情", type_name: "爱情片" },
    { type_id: "dianying-惊悚", type_name: "惊悚片" },
    { type_id: "dianying-犯罪", type_name: "犯罪片" },
    { type_id: "dianying-恐怖", type_name: "恐怖片" },
    { type_id: "dianying-悬疑", type_name: "悬疑片" },
    { type_id: "dianying-冒险", type_name: "冒险片" },
    { type_id: "dianying-奇幻", type_name: "奇幻片" },
    { type_id: "dianying-科幻", type_name: "科幻片" },
    { type_id: "dianying-家庭", type_name: "家庭片" },
    { type_id: "dianying-历史", type_name: "历史片" },
    { type_id: "dianying-战争", type_name: "战争片" },
    { type_id: "dianying-纪录片", type_name: "纪录片" },
    { type_id: "dianying-古装", type_name: "古装片" },
    { type_id: "dianying-音乐", type_name: "音乐片" },
    { type_id: "dianying-动画", type_name: "动画片" }
];

// ===== 筛选器（兼容指南中的 filters 字段） =====
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
    for (let y = currentYear; y >= 2010; y--) {
        years.push({ n: String(y), v: String(y) });
    }
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
    try {
        if (typeof encodeURIComponent === 'function') return encodeURIComponent(s);
    } catch (e) {}
    return s.replace(/[^A-Za-z0-9]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase());
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
        console.error("请求失败: " + url + " - " + e.message);
        return "";
    }
}

// ===== 初始化（探测可用域名） =====
async function init(ext) {
    console.log("初始化爬虫: " + appConfig.siteName);
    for (let i = 0; i < fallbackDomains.length; i++) {
        try {
            let resp = await req(fallbackDomains[i] + "/", {
                method: "GET",
                headers: { "User-Agent": UA, "Accept": "text/html" }
            });
            let html = resp.content || "";
            if (html.length < 500) continue;
            if (html.indexOf("wzzy") !== -1 || html.indexOf("vod") !== -1 || html.indexOf("电影") !== -1) {
                appConfig.siteUrl = fallbackDomains[i];
                console.log("使用可用域名: " + appConfig.siteUrl);
                return;
            }
        } catch (e) {}
    }
    console.error("所有备用域名不可用，使用默认: " + appConfig.siteUrl);
}

// ===== 通用列表解析（返回符合指南的 list 结构） =====
function parseListHtml(html, filterYear) {
    let list = [];
    let pagecount = 1;
    let seen = {};

    try {
        let $ = cheerio.load(html);

        // 优先从常见容器提取
        let items = $(".module-poster-item, .movie-item, .vod-item, .list-item, .video-item");
        if (items.length === 0) {
            // 降级：所有包含影片特征的 a 标签
            $("a[href*='/wzzy-'], a[href*='/vod-'], a[href*='/detail/']").each(function() {
                let href = $(this).attr("href");
                let name = $(this).attr("title") || $(this).text().trim();
                if (href && name && !seen[href]) {
                    let pic = "";
                    let parent = $(this).closest('a');
                    let img = parent.find('img');
                    if (img.length) pic = img.attr("data-original") || img.attr("data-src") || img.attr("src") || "";
                    if (!pic) {
                        let container = $(this).closest("div");
                        let img2 = container.find("img");
                        if (img2.length) pic = img2.attr("data-original") || img2.attr("src") || "";
                    }
                    seen[href] = true;
                    list.push({
                        vod_id: href,
                        vod_name: name,
                        vod_pic: fixUrl(pic),
                        vod_remarks: ""
                    });
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

        // 分页提取
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
    } catch (e) {
        console.error("解析列表页失败: " + e.message);
    }

    return { list, pagecount };
}

// ===== 首页 (符合指南 homeContent) =====
async function home(filter) {
    let list = [];
    try {
        let html = await fetchUrl(appConfig.siteUrl + "/dianying.html");
        let result = parseListHtml(html);
        list = result.list.slice(0, 30);
        if (list.length === 0) {
            html = await fetchUrl(appConfig.siteUrl);
            result = parseListHtml(html);
            list = result.list.slice(0, 30);
        }
    } catch (e) {
        console.error("首页推荐获取失败: " + e.message);
    }

    return JSON.stringify({
        class: classList,
        filters: myFilters,
        list: list
    });
}

// ===== 分类 (符合指南 categoryContent, 包含分页字段) =====
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
    let result = {
        list: [],
        page: pg,
        pagecount: 0,
        limit: 20,
        total: 0
    };

    try {
        let url = buildCategoryUrl(tid, pg, extend);
        let html = await fetchUrl(url);
        let parsed = parseListHtml(html, extend.year || "");
        result.list = parsed.list;
        result.pagecount = parsed.pagecount;
        // 估算 total（若pagecount>0，按20*pagecount粗略估算）
        if (result.pagecount > 0) {
            result.total = result.pagecount * result.limit;
        } else {
            result.total = result.list.length;
        }
    } catch (e) {
        console.error("分类列表获取失败: " + e.message);
    }

    return JSON.stringify(result);
}

// ===== 搜索 (符合指南 searchContent) =====
async function search(wd, quick, page) {
    page = page || 1;
    let result = {
        list: [],
        page: page,
        pagecount: 0,
        limit: 20,
        total: 0
    };

    try {
        let url = appConfig.siteUrl + "/s.html?name=" + encodeQuery(wd);
        if (page > 1) url += "&page=" + page;
        let html = await fetchUrl(url);
        let parsed = parseListHtml(html);
        result.list = parsed.list;
        result.pagecount = parsed.pagecount;
        if (result.pagecount > 0) result.total = result.pagecount * result.limit;
        else result.total = result.list.length;
    } catch (e) {
        console.error("搜索失败: " + e.message);
    }

    return JSON.stringify(result);
}

// ===== 剧集排序辅助 =====
function sortEpisodes(arr) {
    return arr.sort(function(a, b) {
        let getNum = function(name) {
            let m = name.match(/第(\d+)[集话]/i) || name.match(/(\d+)/);
            return m ? parseInt(m[1]) : 0;
        };
        return getNum(a.name) - getNum(b.name);
    });
}

// ===== 详情 (符合指南 detailContent) =====
async function detail(id) {
    try {
        let html = await fetchUrl(appConfig.siteUrl + id);
        let $ = cheerio.load(html);

        // ----- 基础信息提取 -----
        let vod_name = "", vod_director = "", vod_actor = "", vod_year = "", vod_area = "", vod_class = "", vod_content = "", vod_pic = "", vod_remarks = "";

        // 1. JSON-LD 优先
        $('script[type="application/ld+json"]').each(function() {
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

        // 2. HTML 补充
        if (!vod_name) {
            vod_name = $("h1.title, .vod-title, .module-title").first().text().trim() ||
                       $("title").text().replace(/《|》/g, "").replace(/-.*$/, "").trim();
        }

        let $pic = $(".module-poster img, .vod-poster img, .pic img, .cover img").first();
        if ($pic.length) {
            vod_pic = fixUrl($pic.attr("data-original") || $pic.attr("data-src") || $pic.attr("src") || "");
        } else {
            let hash = id.match(/\/wzzy-\d+\/([a-f0-9]+)\.html/)?.[1] || "";
            if (hash) vod_pic = `${appConfig.siteUrl}/img/id/${hash}.jpg`;
        }

        $(".module-info-item, .info-item, .detail-item").each(function() {
            let title = $(this).find(".module-info-item-title, .label, .item-title").text().trim();
            let content = $(this).find(".module-info-item-content, .value, .item-content").text().trim();
            if (title.indexOf("导演") !== -1) {
                vod_director = $(this).find("a").map(function() { return $(this).text().trim(); }).get().join(",") || content;
            }
            if (title.indexOf("主演") !== -1) {
                vod_actor = $(this).find("a").map(function() { return $(this).text().trim(); }).get().join(",") || content;
            }
            if (title.indexOf("类型") !== -1) vod_class = content;
            if (title.indexOf("地区") !== -1) vod_area = content;
            if (title.indexOf("年份") !== -1 || title.indexOf("时间") !== -1) vod_year = content;
            if (title.indexOf("更新") !== -1) vod_remarks = content;
        });

        if (!vod_year || !vod_area) {
            $(".tag-link, .module-info-tag-link a").each(function() {
                let text = $(this).text().trim();
                if (/^\d{4}$/.test(text) && !vod_year) vod_year = text;
                if ((text.includes("大陆") || text.includes("美国") || text.includes("日本") ||
                     text.includes("韩国") || text.includes("香港") || text.includes("台湾")) && !vod_area) {
                    vod_area = text;
                }
            });
        }

        if (!vod_content) {
            let $intro = $(".module-info-introduction-content p, .vod-intro, .summary, .desc");
            if ($intro.length) vod_content = $intro.first().text().trim();
        }

        // ----- 播放线路解析 -----
        let lines = [], playlists = [];
        let sourceNames = [];
        $(".module-tab-item, .play-source-tab, .source-tab").each(function() {
            let name = $(this).attr("data-dropdown-value") || $(this).find("span").text().trim();
            if (name) sourceNames.push(name);
        });

        let panelIndex = 0;
        $("[id^='panel'], .play-list, .episode-list").each(function() {
            let episodes = [], epArray = [];
            $(this).find(".module-play-list-link, .episode-link, a[href*='?p='], a[href*='/play/']").each(function() {
                let name = $(this).find("span").text().trim() || $(this).text().trim();
                let href = $(this).attr("href") || "";
                if (name && href) epArray.push({ name, href });
            });
            if (epArray.length === 0) {
                $(this).find(".module-play-list a, .play-item a").each(function() {
                    let name = $(this).find("span").text().trim() || $(this).text().trim();
                    let href = $(this).attr("href") || "";
                    if (name && href) epArray.push({ name, href });
                });
            }
            sortEpisodes(epArray);
            epArray.forEach(ep => episodes.push(ep.name + "$" + ep.href));
            if (episodes.length > 0) {
                let lineName = sourceNames[panelIndex] || ("线路" + (panelIndex + 1));
                lines.push(lineName);
                playlists.push(episodes);
            }
            panelIndex++;
        });

        if (lines.length === 0) {
            let episodes = [], epArray = [], seenEp = {};
            $(".module-play-list-link, .episode-link, a[href*='?p=']").each(function() {
                let name = $(this).find("span").text().trim() || $(this).text().trim();
                let href = $(this).attr("href") || "";
                let key = name + "_" + href;
                if (name && href && !seenEp[key]) {
                    seenEp[key] = true;
                    epArray.push({ name, href });
                }
            });
            sortEpisodes(epArray);
            epArray.forEach(ep => episodes.push(ep.name + "$" + ep.href));
            if (episodes.length > 0) {
                lines.push("默认");
                playlists.push(episodes);
            }
        }

        if (lines.length === 0) {
            lines.push("默认");
            playlists.push(["暂无播放地址$" + id]);
        }

        let vod_play_from = lines.join("$$$");
        let vod_play_url = playlists.map(eps => eps.join("#")).join("$$$");

        // ----- 组装详情返回（列表外层） -----
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
    } catch (error) {
        console.error("详情页解析失败 [ID: " + id + "]:", error);
        return JSON.stringify([]);
    }
}

// ===== 播放 (符合指南 playerContent) =====
async function play(flag, id, flags) {
    try {
        if (id.startsWith("http")) {
            return JSON.stringify({
                parse: 0,
                header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: id
            });
        }

        let html = await fetchUrl(appConfig.siteUrl + id);

        // 1. 尝试 /api/m3u8
        let m3u8Match = html.match(/href="\/api\/m3u8\?origin=([^&]+)&amp;?url=([^"]+)"/);
        if (!m3u8Match) m3u8Match = html.match(/href="\/api\/m3u8\?origin=([^&]+)&url=([^"]+)"/);
        if (m3u8Match) {
            let playUrl = `${appConfig.siteUrl}/api/m3u8?origin=${encodeURIComponent(m3u8Match[1])}&url=${m3u8Match[2]}`;
            return JSON.stringify({ parse: 0, header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: playUrl });
        }

        // 2. 直链 m3u8/mp4
        let urlMatch = html.match(/"url"\s*[:=]\s*"([^"]+\.(m3u8|mp4|flv)[^"]*)"/);
        if (urlMatch) {
            return JSON.stringify({ parse: 0, header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: urlMatch[1].replace(/\\/g, '') });
        }

        // 3. iframe
        let $ = cheerio.load(html);
        let iframeSrc = $("iframe").attr("src");
        if (iframeSrc) {
            return JSON.stringify({ parse: 1, header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: fixUrl(iframeSrc) });
        }

        // 4. 兜底：让 TVBox 嗅探
        return JSON.stringify({ parse: 1, header: { "User-Agent": UA, "Referer": appConfig.siteUrl }, url: appConfig.siteUrl + id });
    } catch (e) {
        console.error("播放解析失败: " + e.message);
        return JSON.stringify({ parse: 0, url: "" });
    }
}

// ===== 导出模块 =====
export default {
    init,
    home,
    category,
    search,
    detail,
    play
};