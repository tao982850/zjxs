import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
    siteName: "片库4K",
    siteUrl: "https://4k01.pianku.online"
};

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

// 解析接口（播放页 iframe 中的解析器）
const PARSE_API = "https://kk123.seesee.sbs/player/?url=";

async function init(ext) {
    console.log("初始化爬虫:", appConfig.siteName);
}

// ===== 一级分类 =====
const classList = [
    { type_id: "20", type_name: "电影" },
    { type_id: "37", type_name: "剧集" },
    { type_id: "43", type_name: "动漫" },
    { type_id: "45", type_name: "综艺" }
];

// ===== 类型筛选配置 =====
// 电影：子分类独立 tid（站点实际结构）
// 剧集/动漫/综艺：使用 maccms 标准 class 参数
const genreConfig = {
    "20": {
        useTid: true,
        genres: [
            ["全部", ""], ["动作片", "21"], ["喜剧片", "22"], ["爱情片", "23"], ["科幻片", "24"],
            ["恐怖片", "25"], ["剧情片", "26"], ["战争片", "27"], ["惊悚片", "28"], ["犯罪片", "29"],
            ["冒险片", "30"], ["动画片", "31"], ["悬疑片", "32"], ["武侠片", "33"], ["奇幻片", "34"],
            ["纪录片", "35"], ["其他片", "36"]
        ]
    },
    "37": {
        useTid: false,
        genres: [
            ["全部", ""], ["国产剧", "国产剧"], ["韩剧", "韩剧"], ["美剧", "美剧"], ["日剧", "日剧"],
            ["港剧", "港剧"], ["台剧", "台剧"], ["泰剧", "泰剧"], ["海外剧", "海外剧"]
        ]
    },
    "43": {
        useTid: false,
        genres: [
            ["全部", ""], ["国产动漫", "国产动漫"], ["日本动漫", "日本动漫"], ["欧美动漫", "欧美动漫"],
            ["海外动漫", "海外动漫"]
        ]
    },
    "45": {
        useTid: false,
        genres: [
            ["全部", ""], ["大陆综艺", "大陆综艺"], ["港台综艺", "港台综艺"], ["日韩综艺", "日韩综艺"],
            ["欧美综艺", "欧美综艺"]
        ]
    }
};

// ===== 通用筛选 =====
const AREA_FILTER = [
    ["全部", ""], ["大陆", "大陆"], ["香港", "香港"], ["台湾", "台湾"], ["日本", "日本"],
    ["韩国", "韩国"], ["美国", "美国"], ["英国", "英国"], ["法国", "法国"], ["德国", "德国"],
    ["泰国", "泰国"], ["印度", "印度"], ["加拿大", "加拿大"], ["西班牙", "西班牙"],
    ["意大利", "意大利"], ["澳大利亚", "澳大利亚"], ["俄罗斯", "俄罗斯"], ["其他", "其他"]
];

const YEAR_FILTER = [
    ["全部", ""], ["2026", "2026"], ["2025", "2025"], ["2024", "2024"], ["2023", "2023"],
    ["2022", "2022"], ["2021", "2021"], ["2020", "2020"], ["2019", "2019"], ["2018", "2018"],
    ["2017", "2017"], ["2016", "2016"], ["2015", "2015"], ["2014", "2014"], ["2013", "2013"],
    ["2012", "2012"], ["2011", "2011"], ["2010", "2010"], ["更早", "2009"]
];

const LANG_FILTER = [
    ["全部", ""], ["国语", "国语"], ["粤语", "粤语"], ["英语", "英语"], ["日语", "日语"],
    ["韩语", "韩语"], ["法语", "法语"], ["德语", "德语"], ["俄语", "俄语"], ["泰语", "泰语"],
    ["西班牙语", "西班牙语"], ["意大利语", "意大利语"], ["印度语", "印度语"], ["其他", "其他"]
];

const SORT_FILTER = [
    ["最新", "time"], ["最热", "hits"], ["评分", "score"]
];

function toFilterObj(arr) {
    return arr.map(g => ({ "n": g[0], "v": g[1] }));
}

function buildFilters(tid) {
    let cfg = genreConfig[tid] || genreConfig["20"];
    return [
        { "key": "genre", "name": "类型", "value": toFilterObj(cfg.genres) },
        { "key": "area", "name": "地区", "value": toFilterObj(AREA_FILTER) },
        { "key": "year", "name": "年份", "value": toFilterObj(YEAR_FILTER) },
        { "key": "lang", "name": "语言", "value": toFilterObj(LANG_FILTER) },
        { "key": "order", "name": "排序", "value": toFilterObj(SORT_FILTER) }
    ];
}

const myFilters = {};
classList.forEach(item => {
    myFilters[item.type_id] = buildFilters(item.type_id);
});

// ===== 构建分类URL =====
function buildCategoryUrl(tid, pg, extend) {
    extend = extend || {};
    pg = pg || 1;

    let cfg = genreConfig[tid] || genreConfig["20"];
    // 实际请求的分类ID：电影选了子分类时用子分类 tid
    let realTid = tid;
    if (cfg.useTid && extend.genre) {
        realTid = extend.genre;
    }

    // 基础URL：/vodtype/{tid}-{pg}.html
    let url = appConfig.siteUrl + '/vodtype/' + realTid + '-' + pg + '.html';

    // 拼接筛选参数
    let params = [];
    if (!cfg.useTid && extend.genre) {
        params.push('class=' + encodeURIComponent(extend.genre));
    }
    if (extend.area) params.push('area=' + encodeURIComponent(extend.area));
    if (extend.year) params.push('year=' + encodeURIComponent(extend.year));
    if (extend.lang) params.push('lang=' + encodeURIComponent(extend.lang));
    if (extend.order) params.push('by=' + encodeURIComponent(extend.order));

    if (params.length > 0) {
        url += '?' + params.join('&');
    }

    return url;
}

async function httpGet(url) {
    const headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity",
        "Referer": appConfig.siteUrl + '/'
    };

    for (let attempt = 0; attempt < 2; attempt++) {
        try {
            const resp = await req(url, { method: "GET", headers: headers });
            let content = resp.content || '';
            if (content && content.length > 100) {
                return content;
            }
            if (attempt === 0) {
                await new Promise(r => setTimeout(r, 500));
            }
        } catch (e) {
            if (attempt === 0) {
                await new Promise(r => setTimeout(r, 500));
            }
        }
    }
    try {
        const resp = await req(url, { method: "GET", headers: headers });
        return resp.content || '';
    } catch (e) {
        return '';
    }
}

// ===== 解析列表页 =====
function parseListHtml(html) {
    const $ = cheerio.load(html);
    let list = [];
    let seen = {};

    $('.vod-item').each(function () {
        let item = $(this);
        let link = item.find('a').first();
        let href = link.attr('href') || '';
        if (!href) return;

        let vod_id = href;
        if (vod_id.startsWith('http')) {
            vod_id = vod_id.replace(appConfig.siteUrl, '');
        }
        vod_id = vod_id.replace(/^\/+/, '');
        if (!vod_id || seen[vod_id]) return;

        let vod_name = link.attr('title') || '';
        if (!vod_name) {
            vod_name = item.find('.title').first().text().trim();
        }
        if (!vod_name) return;

        let vod_pic = '';
        let img = item.find('img').first();
        if (img.length) {
            vod_pic = img.attr('data-src') || img.attr('data-original') || img.attr('src') || '';
            if (vod_pic && vod_pic.includes('load.gif')) {
                vod_pic = img.attr('data-src') || '';
            }
        }

        let vod_remarks = item.find('.remarks').first().text().trim() || '';

        // 副标题格式: "年份 / 地区"
        let subtitle = item.find('.subtitle').first().text().trim();
        let vod_year = '', vod_area = '';
        if (subtitle) {
            let parts = subtitle.split('/');
            if (parts.length > 0) {
                let ym = parts[0].trim().match(/(\d{4})/);
                if (ym) vod_year = ym[1];
            }
            if (parts.length > 1) {
                vod_area = parts[1].trim();
            }
        }

        seen[vod_id] = true;
        let entry = { vod_id, vod_name, vod_pic, vod_remarks };
        if (vod_year) entry.vod_year = vod_year;
        if (vod_area) entry.vod_area = vod_area;
        list.push(entry);
    });

    // 解析分页
    let pagecount = list.length > 0 ? 1 : 0;
    let maxPage = 0;
    let hasNext = false;

    $('.mac_pages a, .pagination a, .page a').each(function () {
        let href = $(this).attr('href') || '';
        let text = $(this).text().trim();
        if (text.includes('下一页') || text.includes('Next')) {
            hasNext = true;
        }
        let m = href.match(/-(\d+)\.html/) || href.match(/[?&]page=(\d+)/);
        if (m) {
            let p = parseInt(m[1]);
            if (p > maxPage) maxPage = p;
        }
    });

    $('.mac_pages .page_current, .pagination .current, .page .current').each(function () {
        let p = parseInt($(this).text().trim());
        if (p > maxPage) maxPage = p;
    });

    if (hasNext) {
        pagecount = maxPage + 1;
    } else if (maxPage > 0) {
        pagecount = maxPage;
    }

    return { list, pagecount };
}

async function home(filter) {
    let list = [];
    try {
        const html = await httpGet(appConfig.siteUrl + '/');
        const result = parseListHtml(html);
        list = result.list.slice(0, 30);
    } catch (e) {
        console.error("首页获取失败:", e.message);
    }

    return JSON.stringify({
        class: classList,
        filters: myFilters,
        list: list
    });
}

async function category(tid, pg, filter, extend) {
    pg = pg || 1;
    extend = extend || {};

    try {
        const url = buildCategoryUrl(tid, pg, extend);
        const html = await httpGet(url);
        const result = parseListHtml(html);

        return JSON.stringify({ list: result.list, pagecount: result.pagecount });
    } catch (e) {
        console.error("分类列表获取失败:", e.message);
        return JSON.stringify({ list: [], pagecount: 0 });
    }
}

async function search(wd, quick, page) {
    page = page || 1;
    try {
        let kw = String(wd || '').trim();
        if (!kw) return JSON.stringify({ list: [], pagecount: 0 });

        // maccms 标准搜索URL
        let url = appConfig.siteUrl + '/vodsearch/-------------.html?wd=' + encodeURIComponent(kw);
        if (page > 1) {
            url = appConfig.siteUrl + '/vodsearch/' + encodeURIComponent(kw) + '----------' + page + '---.html';
        }

        const html = await httpGet(url);
        const result = parseListHtml(html);

        return JSON.stringify({ list: result.list, pagecount: result.pagecount });
    } catch (e) {
        console.error("搜索失败:", e.message);
        return JSON.stringify({ list: [], pagecount: 0 });
    }
}

async function detail(id) {
    try {
        let detailUrl = id.startsWith('http') ? id : (appConfig.siteUrl + '/' + id.replace(/^\/+/, ''));
        if (!detailUrl.includes('voddetail')) {
            let idMatch = id.match(/(\d+)/);
            if (idMatch) {
                detailUrl = appConfig.siteUrl + '/voddetail/' + idMatch[1] + '.html';
            }
        }

        const html = await httpGet(detailUrl);
        const $ = cheerio.load(html);

        // 标题
        let vod_name = $('.detail-title, h1').first().text().trim();
        vod_name = vod_name.replace(/^《|》$/g, '').replace(/\s+/g, ' ').trim();

        // 海报
        let vod_pic = '';
        let img = $('.detail-poster img, .module-item-pic img').first();
        if (img.length) {
            vod_pic = img.attr('data-src') || img.attr('data-original') || img.attr('src') || '';
            if (vod_pic && !vod_pic.startsWith('http')) {
                vod_pic = appConfig.siteUrl + '/' + vod_pic.replace(/^\.?\//, '');
            }
        }

        // 元数据
        let vod_year = '', vod_area = '', vod_class = '', vod_lang = '',
            vod_director = '', vod_actor = '', vod_remarks = '', vod_content = '';

        $('.detail-meta span, .module-info-tag span, .data span').each(function () {
            let text = $(this).text().trim();
            if (text.includes('分类') || text.includes('类型')) {
                let cls = $(this).find('a').text().trim() || text.replace(/^.*?[：:]/, '').trim();
                if (cls) vod_class = cls;
            } else if (text.includes('地区')) {
                vod_area = text.replace(/^.*?[：:]/, '').trim();
            } else if (text.includes('年份') || text.includes('时间')) {
                let ym = text.match(/(\d{4})/);
                if (ym) vod_year = ym[1];
            } else if (text.includes('语言')) {
                vod_lang = text.replace(/^.*?[：:]/, '').trim();
            } else if (text.includes('导演')) {
                vod_director = $(this).find('a').text().trim() ||
                    text.replace(/^.*?[：:]/, '').trim();
            } else if (text.includes('主演') || text.includes('演员')) {
                vod_actor = $(this).find('a').text().trim() ||
                    text.replace(/^.*?[：:]/, '').trim();
            } else if (text.includes('状态') || text.includes('更新')) {
                vod_remarks = text.replace(/^.*?[：:]/, '').trim();
            }
        });

        // 备用：从其他常见结构提取导演/演员
        if (!vod_director) {
            vod_director = $('.director a, [class*=director] a').text().trim() ||
                $('.module-info-items li:contains("导演") a').text().trim();
        }
        if (!vod_actor) {
            vod_actor = $('.actor a, [class*=actor] a, .starring a').text().trim() ||
                $('.module-info-items li:contains("主演") a').text().trim();
        }

        // 简介
        vod_content = $('.detail-desc p, .module-info-introduction p, .content, .jj').first().text().trim();
        if (!vod_content) {
            vod_content = $('.detail-desc, .module-info-introduction').text().trim()
                .replace(/剧情简介/, '').trim();
        }
        if (vod_content) vod_content = vod_content.substring(0, 500);

        // 标题年份兜底
        if (!vod_year) {
            let titleYear = vod_name.match(/(\d{4})/);
            if (titleYear) vod_year = titleYear[1];
        }

        // ===== 构建播放线路和选集 =====
        let lines = [];
        let playlists = [];

        // 1. 在线播放线路
        let sourceTabs = $('.source-tab-item, .playlist-tab, .module-tab-item');
        let sourcePanes = $('.source-pane, .playlist-content, .module-list');

        // 如果有 tab 结构
        if (sourceTabs.length > 0) {
            sourceTabs.each(function (idx) {
                let tab = $(this);
                let lineName = tab.text().trim().replace(/\s+\d+$/, '').trim() || ('线路' + (idx + 1));
                let target = tab.attr('data-target') || '';

                let pane;
                if (target) {
                    pane = $('#' + target + ' .play-btn-item, #' + target + ' a[href*="vodplay"]');
                } else {
                    pane = sourcePanes.eq(idx).find('.play-btn-item, a[href*="vodplay"]');
                }

                if (pane.length === 0) return;

                let epList = [];
                pane.each(function () {
                    let ep = $(this);
                    let epName = ep.attr('title') || ep.text().trim();
                    let epUrl = ep.attr('href') || '';
                    if (!epUrl) return;
                    if (epUrl && !epUrl.startsWith('http')) {
                        epUrl = appConfig.siteUrl + '/' + epUrl.replace(/^\/+/, '');
                    }
                    if (epName && epUrl) {
                        epList.push(epName + '$' + epUrl);
                    }
                });

                if (epList.length > 0) {
                    lines.push(lineName);
                    playlists.push(epList);
                }
            });
        }

        // 兜底：直接找所有播放链接
        if (lines.length === 0) {
            let epList = [];
            $('.url-grid-play a, .play-btn-item, a[href*="vodplay"]').each(function () {
                let ep = $(this);
                let epName = ep.attr('title') || ep.text().trim();
                let epUrl = ep.attr('href') || '';
                if (!epUrl) return;
                if (epUrl && !epUrl.startsWith('http')) {
                    epUrl = appConfig.siteUrl + '/' + epUrl.replace(/^\/+/, '');
                }
                if (epName && epUrl) {
                    epList.push(epName + '$' + epUrl);
                }
            });
            if (epList.length > 0) {
                lines.push('默认线路');
                playlists.push(epList);
            }
        }

        // 2. 网盘/磁力资源线路
        let panMap = {};
        let panOrder = [];

        $('.resource-item, .pan-item, [class*=resource-]').each(function () {
            let el = $(this);
            let href = el.attr('href') || '';
            // 允许 http(s) 直链与 magnet: 磁力链接
            if (!href) return;
            if (!href.startsWith('http') && !href.startsWith('magnet:')) return;

            let badge = el.find('.resource-badge, .badge, .pan-name').text().trim();
            let note = el.find('.resource-note, .note, .title').text().trim() || '下载链接';

            // 判断资源类型（磁力优先识别，避免被网盘兜底吞掉）
            let panName = '';
            // 1) 磁力：badge 含"磁力" / class 含 magnet / href 以 magnet: 开头
            if (badge.includes('磁力') || el.hasClass('resource-magnet') ||
                el.attr('class') && (el.attr('class').includes('magnet')) ||
                href.startsWith('magnet:')) {
                panName = '磁力';
            }
            // 2) 网盘：按 badge 标识或 href 域名识别
            else if (badge.includes('夸克') || href.includes('quark')) panName = '夸克网盘';
            else if (badge.includes('百度') || href.includes('baidu')) panName = '百度网盘';
            else if (badge.includes('阿里') || href.includes('aliyundrive') || href.includes('alipan')) panName = '阿里云盘';
            else if (badge.includes('123') || href.includes('123pan')) panName = '123网盘';
            else if (badge.includes('迅雷') || href.includes('xunlei')) panName = '迅雷云盘';
            else if (badge.includes('115') || href.includes('115')) panName = '115网盘';
            else if (badge.includes('UC') || href.includes('uc.cn') || href.includes('drive.uc')) panName = 'UC网盘';
            else if (badge) panName = badge; // 直接用 badge 文本
            else panName = '网盘';

            if (!panMap[panName]) {
                panMap[panName] = [];
                panOrder.push(panName);
            }
            panMap[panName].push(note + '$' + href);
        });

        // 兜底：从 #magnet-group 容器内直接抓取磁力链接
        if (!panMap['磁力']) {
            let magnetEps = [];
            $('#magnet-group a[href^="magnet:"], a[href^="magnet:"]').each(function () {
                let el = $(this);
                let href = el.attr('href') || '';
                if (!href) return;
                let note = el.find('.resource-note, .note').text().trim() ||
                    el.attr('title') || el.text().trim() || '磁力下载';
                magnetEps.push(note + '$' + href);
            });
            if (magnetEps.length > 0) {
                panMap['磁力'] = magnetEps;
                panOrder.push('磁力');
            }
        }

        for (let panName of panOrder) {
            let eps = panMap[panName];
            if (eps && eps.length > 0) {
                lines.push(panName);
                playlists.push(eps);
            }
        }

        // 最终兜底
        if (lines.length === 0) {
            lines.push('默认线路');
            playlists.push(['暂无播放地址$' + id]);
        }

        const vod_play_from = lines.join('$$$');
        const vod_play_url = playlists.map(eps => eps.join('#')).join('$$$');

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
                vod_lang,
                vod_content,
                vod_class,
                vod_play_from,
                vod_play_url
            }]
        });
    } catch (error) {
        console.error("解析详情异常:", error);
        return JSON.stringify({ list: [] });
    }
}

// ===== 从播放页HTML提取 player_aaaa 配置 =====
function extractPlayerConfig(html) {
    // 匹配 player_aaaa={...}
    let m = html.match(/player_aaaa\s*=\s*(\{[^}]+\})/);
    if (m) {
        try {
            return JSON.parse(m[1]);
        } catch (e) {
            // 尝试修复常见JSON问题
            try {
                let fixed = m[1].replace(/'/g, '"').replace(/(\w+):/g, '"$1":');
                return JSON.parse(fixed);
            } catch (e2) {
                return null;
            }
        }
    }
    return null;
}

async function play(flag, id, flags) {
    try {
        let playUrl = id;

        // ===== 网盘/磁力/直链直接返回 =====
        if (playUrl.startsWith('magnet:') ||
            playUrl.includes('pan.quark') || playUrl.includes('baidu.com') ||
            playUrl.includes('aliyundrive') || playUrl.includes('alipan') ||
            playUrl.includes('123pan') || playUrl.includes('xunlei') ||
            playUrl.includes('115.com') || playUrl.includes('drive.uc')) {
            return JSON.stringify({
                parse: 0,
                Header: { "User-Agent": UA },
                url: playUrl
            });
        }

        // 直链 m3u8 / mp4 直接播放
        if (playUrl.includes('.m3u8') || playUrl.includes('.mp4')) {
            return JSON.stringify({
                parse: 0,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' },
                url: playUrl
            });
        }

        // ===== 播放页：提取 player_aaaa.url =====
        let playPageUrl = playUrl;
        if (!playPageUrl.startsWith('http')) {
            playPageUrl = appConfig.siteUrl + '/' + playPageUrl.replace(/^\/+/, '');
        }

        const html = await httpGet(playPageUrl);
        const playerCfg = extractPlayerConfig(html);

        if (playerCfg && playerCfg.url) {
            let realUrl = playerCfg.url;

            // 直链直接播放
            if (realUrl.includes('.m3u8') || realUrl.includes('.mp4')) {
                return JSON.stringify({
                    parse: 0,
                    Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' },
                    url: realUrl
                });
            }

            // 视频站链接：通过解析接口播放
            if (realUrl.startsWith('http')) {
                let parseUrl = PARSE_API + encodeURIComponent(realUrl);
                return JSON.stringify({
                    parse: 1,
                    Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' },
                    url: parseUrl
                });
            }
        }

        // 兜底：正则匹配页面中的 m3u8
        let m3u8Match = html.match(/(https?:\/\/[^\s"'<>]+\.m3u8[^\s"'<>]*)/);
        if (m3u8Match) {
            return JSON.stringify({
                parse: 0,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' },
                url: m3u8Match[1]
            });
        }

        // 最终兜底：交给播放器嗅探播放页
        return JSON.stringify({
            parse: 1,
            Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' },
            url: playPageUrl
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
