import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
    siteName: "星火4K",
    siteUrl: "https://www.spark4k.com"
}
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36";

async function init(ext) {
    console.log("初始化爬虫:", appConfig.siteName);
}

const catConfig = {
    "动作":   { tid: "1",   clazz: "" },
    "剧情":   { tid: "100", clazz: "" },
    "科幻":   { tid: "4",   clazz: "" },
    "喜剧":   { tid: "3",   clazz: "" },
    "爱情":   { tid: "5",   clazz: "" },
    "悬疑":   { tid: "20",  clazz: "" },
    "冒险":   { tid: "21",  clazz: "" },
    "恐怖":   { tid: "22",  clazz: "" },
    "动画":   { tid: "24",  clazz: "" },
    "剧集":   { tid: "104", clazz: "" },
    "记录":   { tid: "106", clazz: "" },
    "演唱会": { tid: "105", clazz: "" }
};

function getYearFilter() {
    let years = [{ "n": "全部", "v": "" }];
    const currentYear = new Date().getFullYear();
    for (let y = currentYear; y >= currentYear - 25; y--) {
        years.push({ "n": String(y), "v": String(y) });
    }
    return { "key": "year", "name": "年份", "value": years };
}

function getAreaFilter() {
    return {
        "key": "area", "name": "地区", "value": [
            { "n": "全部", "v": "" }, { "n": "大陆", "v": "大陆" }, { "n": "香港", "v": "香港" },
            { "n": "台湾", "v": "台湾" }, { "n": "美国", "v": "美国" }, { "n": "韩国", "v": "韩国" },
            { "n": "日本", "v": "日本" }, { "n": "泰国", "v": "泰国" }, { "n": "英国", "v": "英国" },
            { "n": "法国", "v": "法国" }, { "n": "德国", "v": "德国" }, { "n": "印度", "v": "印度" },
            { "n": "其他", "v": "其他" }
        ]
    };
}

function getOrderFilter() {
    return {
        "key": "order", "name": "排序", "value": [
            { "n": "按时间", "v": "time" },
            { "n": "按人气", "v": "hits" },
            { "n": "按评分", "v": "score" }
        ]
    };
}

const commonFilters = [
    getAreaFilter(),
    getYearFilter(),
    getOrderFilter()
];

const myFilters = {};

async function home(filter) {
    const classList = [
        { type_id: "动作", type_name: "动作" },
        { type_id: "剧情", type_name: "剧情" },
        { type_id: "科幻", type_name: "科幻" },
        { type_id: "喜剧", type_name: "喜剧" },
        { type_id: "爱情", type_name: "爱情" },
        { type_id: "悬疑", type_name: "悬疑" },
        { type_id: "冒险", type_name: "冒险" },
        { type_id: "恐怖", type_name: "恐怖" },
        { type_id: "动画", type_name: "动画" },
        { type_id: "剧集", type_name: "剧集" },
        { type_id: "记录", type_name: "记录" },
        { type_id: "演唱会", type_name: "演唱会" }
    ];

    classList.forEach(item => {
        myFilters[item.type_id] = commonFilters;
    });

    return JSON.stringify({
        class: classList,
        filters: myFilters
    });
}

function buildCategoryUrl(catName, pg, extend) {
    let cfg = catConfig[catName] || { tid: "100", clazz: "" };
    let classVal = extend.class || cfg.clazz || "";
    let areaVal = extend.area || '';
    let yearVal = extend.year || '';
    let orderVal = extend.order || '';

    let parts = ['/vod/show'];
    
    if (classVal) {
        parts.push(`class/${encodeURIComponent(classVal)}`);
    }
    if (areaVal) {
        parts.push(`area/${encodeURIComponent(areaVal)}`);
    }
    if (yearVal) {
        parts.push(`year/${encodeURIComponent(yearVal)}`);
    }
    if (orderVal) {
        parts.push(`by/${encodeURIComponent(orderVal)}`);
    }
    
    parts.push(`id/${cfg.tid}`);
    
    if (pg && pg > 1) {
        parts.push(`page/${pg}`);
    }
    
    return `${appConfig.siteUrl}${parts.join('/')}.html`;
}

function fixUrl(u) {
    if (!u) return '';
    if (u.startsWith('http')) return u;
    if (u.startsWith('//')) return 'https:' + u;
    if (u.startsWith('/')) return appConfig.siteUrl + u;
    return u;
}

function parseListHtml(html) {
    const $ = cheerio.load(html);
    let list = [];
    let vodIds = {};

    $(".module-item").each(function (index, el) {
        let $a = $(this).find("a.module-item-title").first();
        let vod_id = $a.attr("href");
        if (!vod_id || vodIds[vod_id]) return;

        let vod_name = $a.attr("title") || $a.text().trim();

        let $pic = $(this).find(".module-item-pic img.lazy").first();
        let vod_pic = fixUrl($pic.attr("data-src") || $pic.attr("src") || "");

        let quality = $(this).find(".module-item-text").text().replace(/\s+/g, ' ').trim();
        let vod_remarks = quality;

        if (vod_name && vod_id && vod_name.length > 0 && vod_name.length < 100) {
            vodIds[vod_id] = true;
            list.push({ vod_id, vod_name, vod_pic, vod_remarks });
        }
    });

    let pagecount = 1;
    $("a.page-next[title='尾页']").each(function () {
        let href = $(this).attr("href");
        if (href) {
            let m = href.match(/\/page\/(\d+)\.html/);
            if (m) pagecount = parseInt(m[1]);
        }
    });

    return { list, pagecount };
}

async function category(tid, pg, filter, extend) {
    pg = pg || 1;
    extend = extend || {};

    let url = buildCategoryUrl(tid, pg, extend);

    try {
        const html = (await req(url, {
            headers: {
                "User-Agent": UA,
                "Referer": appConfig.siteUrl
            }
        })).content;
        const result = parseListHtml(html);
        
        if (result.list.length === 0 && !url.includes('index.php')) {
            let urlWithIndex = url.replace('/vod/show/', '/index.php/vod/show/');
            const html2 = (await req(urlWithIndex, {
                headers: {
                    "User-Agent": UA,
                    "Referer": appConfig.siteUrl
                }
            })).content;
            const result2 = parseListHtml(html2);
            if (result2.list.length > 0) {
                return JSON.stringify(result2);
            }
        }

        return JSON.stringify(result);
    } catch (e) {
        console.error("分类列表获取失败:", e.message);
        return JSON.stringify({ list: [], pagecount: 0 });
    }
}

async function search(wd, quick, page) {
    if (page >= 2) return JSON.stringify({ list: [], pagecount: 1 });
    try {
        const url = `${appConfig.siteUrl}/index.php/vod/search/wd/${encodeURIComponent(wd)}.html`;
        const html = (await req(url, {
            headers: {
                "User-Agent": UA,
                "Referer": appConfig.siteUrl
            }
        })).content;
        const result = parseListHtml(html);
        return JSON.stringify({ list: result.list, pagecount: 1 });
    } catch (e) {
        console.error("搜索失败:", e.message);
        return JSON.stringify({ list: [] });
    }
}

async function detail(id) {
    try {
        const html = (await req(appConfig.siteUrl + id, {
            headers: {
                "User-Agent": UA,
                "Referer": appConfig.siteUrl
            }
        })).content;
        const $ = cheerio.load(html);

        let vod_name = "";
        let vod_pic = "";
        let vod_actor = "";
        let vod_director = "";
        let vod_remarks = "";
        let vod_year = "";
        let vod_area = "";
        let vod_content = "";

        vod_name = $("h1").first().text().trim();

        let $detailPic = $(".module-info .module-item-pic img, .module-info-cover img");
        if ($detailPic.length === 0) {
            $detailPic = $(".module-item-pic img.lazy").first();
        }
        if ($detailPic.length === 0) {
            $detailPic = $("img[alt*='"+vod_name+"']").first();
        }
        if ($detailPic.length > 0) {
            vod_pic = fixUrl($detailPic.attr("data-src") || $detailPic.attr("src") || "");
        }

        $(".module-info-item, .module-info-row, .video-info p, .data, .info-item").each(function () {
            let text = $(this).text().trim();
            if (text.includes('主演') && vod_actor === '') {
                vod_actor = $(this).find('a').map(function () { return $(this).text().trim(); }).get().join(',');
                if (!vod_actor) vod_actor = text.replace(/.*?主演[：:]\s*/, '').trim();
            } else if (text.includes('导演') && vod_director === '') {
                vod_director = $(this).find('a').map(function () { return $(this).text().trim(); }).get().join(',');
                if (!vod_director) vod_director = text.replace(/.*?导演[：:]\s*/, '').trim();
            } else if (text.includes('年份') && vod_year === '') {
                vod_year = $(this).find('a').text().trim() || text.replace(/.*?年份[：:]\s*/, '').trim();
            } else if (text.includes('地区') && vod_area === '') {
                vod_area = $(this).find('a').text().trim() || text.replace(/.*?地区[：:]\s*/, '').trim();
            } else if ((text.includes('状态') || text.includes('更新')) && vod_remarks === '') {
                vod_remarks = text.replace(/.*?(状态|更新)[：:]\s*/, '').replace(/\n.*/, '').trim();
            }
        });

        let $intro = $(".module-info-introduction-content, .module-info-content, .desc, .introduction, .detail-content");
        if ($intro.length > 0) {
            vod_content = $intro.first().text().trim();
        }

        let lines = [];
        let playlists = [];

        let baiduLinks = [];
        let ed2kLinks = [];
        let magnetLinks = [];

        $("a").each(function () {
            let href = $(this).attr("href") || "";
            let text = $(this).text().trim();
            
            if (href.includes("115.com") || text.includes("网盘")) {
                let name = text.replace(/.*?\s([^\s]+)\shttps?.*/, '$1');
                if (!name || name.length > 50) {
                    name = text.substring(0, 50);
                }
                baiduLinks.push(`${name}$${href}`);
            } else if (href.startsWith("ed2k://")) {
                let name = text.replace(/ed2k:.*/, '').trim();
                if (!name || name.length > 50) {
                    name = "ED2K资源";
                }
                ed2kLinks.push(`${name}$${href}`);
            } else if (href.startsWith("magnet:")) {
                let name = text.replace(/magnet:.*/, '').trim();
                if (!name || name.length > 50) {
                    name = "磁力链接";
                }
                magnetLinks.push(`${name}$${href}`);
            }
        });

        if (baiduLinks.length > 0) {
            lines.push("115网盘");
            playlists.push(baiduLinks);
        }
        if (ed2kLinks.length > 0) {
            lines.push("ED2K");
            playlists.push(ed2kLinks);
        }
        if (magnetLinks.length > 0) {
            lines.push("磁力");
            playlists.push(magnetLinks);
        }

        if (lines.length === 0) {
            lines.push("下载链接");
            playlists.push([`请登录查看$${appConfig.siteUrl}${id}`]);
        }

        const { vod_play_from, vod_play_url } = buildVodPlayData(lines, playlists);

        return JSON.stringify({
            list: [{
                vod_id: id, vod_name, vod_pic, vod_actor, vod_director,
                vod_remarks, vod_year, vod_area, vod_content,
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

function isDirectUrl(url) {
    return url && (url.startsWith('http') && (url.includes('.m3u8') || url.includes('.mp4') || url.includes('.flv')));
}

function getPlayUrl(html) {
    const match = html.match(/var\s+player_aaaa[\s\S]*?"url"\s*:\s*"([^"]+)"/);
    if (match) {
        return match[1].replace(/\\/g, '');
    }

    const match2 = html.match(/"url"\s*:\s*"([^"]+\.(?:m3u8|mp4)[^"]*)"/);
    if (match2) {
        return match2[1].replace(/\\/g, '');
    }

    return '';
}

function getPlayIframeUrl(html) {
    const iframeMatch = html.match(/<iframe[^>]+src="([^"]+)"/);
    return iframeMatch ? iframeMatch[1] : '';
}

async function play(flag, id, flags) {
    try {
        if (id.startsWith("http")) {
            if (id.startsWith("magnet:") || id.startsWith("ed2k://")) {
                return JSON.stringify({
                    parse: 0,
                    Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                    url: id
                });
            }
            return JSON.stringify({
                parse: 1,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: id
            });
        }

        const html = (await req(`${appConfig.siteUrl}${id}`)).content;
        let url = getPlayUrl(html);

        if (url) {
            if (isDirectUrl(url)) {
                return JSON.stringify({
                    parse: 0,
                    Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                    url
                });
            }
            return JSON.stringify({
                parse: 1,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url
            });
        }

        let iframeUrl = getPlayIframeUrl(html);
        if (iframeUrl) {
            return JSON.stringify({
                parse: 1,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: fixUrl(iframeUrl)
            });
        }

        const $ = cheerio.load(html);
        let playerBox = $(".module-player-box, .player-box, #a1, #Player, .dplayer, .video-box, .MacPlayer");
        if (playerBox.length > 0) {
            let dataSrc = playerBox.attr("data-src") || playerBox.find("iframe").attr("src");
            if (dataSrc) {
                return JSON.stringify({
                    parse: 1,
                    Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                    url: fixUrl(dataSrc)
                });
            }
        }

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
