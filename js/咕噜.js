import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
    siteName: "咕噜电影",
    siteUrl: "https://www.guludyw.com"
};

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

async function init(ext) {
    console.log("初始化爬虫:", appConfig.siteName);
}

const classList = [
    { type_id: "1", type_name: "电影" },
    { type_id: "2", type_name: "电视剧" },
    { type_id: "3", type_name: "动漫" },
    { type_id: "4", type_name: "综艺" },
    { type_id: "10", type_name: "短剧" }
];

// 类型筛选
function getGenreFilter() {
    return {
        "key": "genre",
        "name": "类型",
        "value": [
            { "n": "全部", "v": "" },
            { "n": "动作", "v": "动作" },
            { "n": "喜剧", "v": "喜剧" },
            { "n": "爱情", "v": "爱情" },
            { "n": "科幻", "v": "科幻" },
            { "n": "剧情", "v": "剧情" },
            { "n": "悬疑", "v": "悬疑" },
            { "n": "惊悚", "v": "惊悚" },
            { "n": "恐怖", "v": "恐怖" },
            { "n": "犯罪", "v": "犯罪" },
            { "n": "警匪", "v": "警匪" },
            { "n": "冒险", "v": "冒险" },
            { "n": "奇幻", "v": "奇幻" },
            { "n": "武侠", "v": "武侠" },
            { "n": "枪战", "v": "枪战" },
            { "n": "动画", "v": "动画" },
            { "n": "战争", "v": "战争" },
            { "n": "经典", "v": "经典" },
            { "n": "青春", "v": "青春" },
            { "n": "文艺", "v": "文艺" }
        ]
    };
}

function getSortFilter() {
    return {
        "key": "order",
        "name": "排序",
        "value": [
            { "n": "按人气", "v": "hits" },
            { "n": "按时间", "v": "time" }
        ]
    };
}

const commonFilters = [getGenreFilter(), getSortFilter()];

const myFilters = {};
classList.forEach(item => {
    myFilters[item.type_id] = commonFilters;
});

// 构建分类URL
function buildCategoryUrl(tid, pg, extend) {
    extend = extend || {};
    pg = pg || 1;

    // 如果选了类型筛选，用 vod-type 接口
    if (extend.genre) {
        let url = appConfig.siteUrl + '/index.php/vod-type-id-' + tid +
            '-type-' + encodeURIComponent(extend.genre) +
            '-area--year--star--state--order-' + (extend.order || 'hits') + '.html';
        if (pg > 1) {
            url = url.replace('.html', '-p-' + pg + '.html');
        }
        return url;
    }

    // 普通分类分页
    let url = appConfig.siteUrl + '/index.php/vod-show-id-' + tid;
    if (extend.order === 'time') {
        url = appConfig.siteUrl + '/index.php/vod-type-id-' + tid +
            '-type--area--year--star--state--order-time.html';
        if (pg > 1) {
            url = url.replace('.html', '-p-' + pg + '.html');
        }
    } else {
        if (pg > 1) {
            url += '-p-' + pg;
        }
        url += '.html';
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

    // 重试机制
    for (let attempt = 0; attempt < 2; attempt++) {
        try {
            const resp = await req(url, {
                method: "GET",
                headers: headers
            });
            let content = resp.content || '';
            if (content && content.length > 100 && !content.includes('系统发生错误')) {
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

// 解析列表页卡片（分类页）
function parseListHtml(html) {
    const $ = cheerio.load(html);
    let list = [];
    let seen = {};

    $('.list_yy li, .stui-vodlist__item').each(function () {
        let li = $(this);
        let link = li.find('a[href*="vod-read"]').first();
        if (!link.length) return;

        let href = link.attr('href') || '';
        if (!href) return;

        let vod_id = href;
        if (vod_id.startsWith('http')) {
            vod_id = vod_id.replace(appConfig.siteUrl, '');
        }
        if (!vod_id || seen[vod_id]) return;

        let vod_name = '';
        let p = li.find('p').first();
        if (p.length) {
            vod_name = p.find('a').text().trim() || p.text().trim();
        }
        if (!vod_name) {
            vod_name = li.find('a').last().text().trim();
        }
        if (!vod_name) return;

        let vod_pic = '';
        let img = li.find('img').first();
        if (img.length) {
            vod_pic = img.attr('data-original') || img.attr('data-src') || img.attr('src') || '';
        }

        let vod_remarks = li.find('span').first().text().trim() || li.find('em').first().text().trim() || '';

        seen[vod_id] = true;
        list.push({ vod_id, vod_name, vod_pic, vod_remarks });
    });

    let pagecount = list.length > 0 ? 1 : 0;
    let maxPage = 0;
    let hasNext = false;

    $('.wap_page a, .page a').each(function () {
        let href = $(this).attr('href') || '';
        let text = $(this).text().trim();
        if (text.includes('下一页') || text.includes('»')) {
            hasNext = true;
        }
        let m = href.match(/-p-(\d+)\.html/);
        if (m) {
            let p = parseInt(m[1]);
            if (p > maxPage) maxPage = p;
        }
    });

    if (hasNext || maxPage > 0) {
        pagecount = maxPage > 0 ? maxPage + (hasNext ? 1 : 0) : 1;
    }

    return { list, pagecount };
}

// 解析搜索结果页
function parseSearchHtml(html) {
    const $ = cheerio.load(html);
    let list = [];
    let seen = {};

    $('.list_search li').each(function () {
        let li = $(this);
        let link = li.find('a[href*="vod-read"]').first();
        if (!link.length) return;

        let href = link.attr('href') || '';
        if (!href) return;

        let vod_id = href;
        if (vod_id.startsWith('http')) {
            vod_id = vod_id.replace(appConfig.siteUrl, '');
        }
        if (!vod_id || seen[vod_id]) return;

        let vod_name = li.find('.vod-intro-title').first().text().trim();
        if (!vod_name) {
            vod_name = li.find('img').attr('alt') || '';
        }
        if (!vod_name) return;

        let vod_pic = '';
        let img = li.find('img').first();
        if (img.length) {
            vod_pic = img.attr('data-original') || img.attr('data-src') || img.attr('src') || '';
        }

        let vod_remarks = li.find('.vod-intro-time').first().text().trim() || '';

        seen[vod_id] = true;
        list.push({ vod_id, vod_name, vod_pic, vod_remarks });
    });

    let pagecount = list.length > 0 ? 1 : 0;
    let maxPage = 0;
    let hasNext = false;

    $('.wap_page a, .page a').each(function () {
        let href = $(this).attr('href') || '';
        let text = $(this).text().trim();
        if (text.includes('下一页') || text === '»') {
            hasNext = true;
        }
        let m = href.match(/-p-(\d+)\.html/);
        if (m) {
            let p = parseInt(m[1]);
            if (p > maxPage) maxPage = p;
        }
    });

    if (hasNext || maxPage > 0) {
        pagecount = maxPage > 0 ? maxPage + (hasNext ? 1 : 0) : 1;
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

        let url = appConfig.siteUrl + '/index.php?s=vod-search&wd=' + encodeURIComponent(kw);
        if (page > 1) {
            url += '-p-' + page;
        }

        const html = await httpGet(url);
        const result = parseSearchHtml(html);

        return JSON.stringify(result);
    } catch (e) {
        console.error("搜索失败:", e.message);
        return JSON.stringify({ list: [], pagecount: 0 });
    }
}

async function detail(id) {
    try {
        // 统一将 ?s= 格式转换为路径格式（?s= 格式不稳定，常返回404）
        let normalizedId = id;
        let sMatch = id.match(/\?s=\/vod-read-id-(\d+)/);
        if (sMatch) {
            normalizedId = '/index.php/vod-read-id-' + sMatch[1] + '.html';
        }

        // 构造详情页URL，准备多种格式
        let detailUrls = [];
        if (normalizedId.startsWith('http')) {
            detailUrls.push(normalizedId);
        } else if (normalizedId.includes('/vod-read')) {
            detailUrls.push(appConfig.siteUrl + normalizedId);
        }

        // 提取数字ID，添加备用URL
        let idMatch = normalizedId.match(/(\d+)/);
        if (idMatch) {
            let numId = idMatch[1];
            let pathUrl = appConfig.siteUrl + '/index.php/vod-read-id-' + numId + '.html';
            if (detailUrls.indexOf(pathUrl) === -1) {
                detailUrls.push(pathUrl);
            }
        }

        // 尝试每种URL格式
        let html = '';
        for (let url of detailUrls) {
            html = await httpGet(url);
            if (html && html.length > 500 && !html.includes('系统发生错误')) {
                break;
            }
            html = '';
        }

        if (!html || html.length < 500) {
            return JSON.stringify({ list: [] });
        }

        const $ = cheerio.load(html);

        // 标题
        let vod_name = $('.nei_con h1, h1').first().text().trim();
        vod_name = vod_name.replace(/\s+/g, ' ').trim();

        // 海报
        let vod_pic = '';
        let img = $('.text_img img, .nei_con img, .pic img').first();
        if (img.length) {
            vod_pic = img.attr('data-original') || img.attr('data-src') || img.attr('src') || '';
        }

        let vod_year = '', vod_area = '', vod_class = '', vod_actor = '', vod_director = '', vod_remarks = '', vod_content = '';

        // 信息字段
        $('.text-sinfo p, .text p, .nei_con p').each(function () {
            let p = $(this);
            let text = p.text().trim();

            if (text.includes('主演') && !vod_actor) {
                let actors = [];
                p.find('a').each(function () {
                    let name = $(this).text().trim().replace(/&nbsp;/g, '').trim();
                    if (name && !name.includes('vod-search')) actors.push(name);
                });
                vod_actor = actors.join(',');
            } else if (text.includes('导演') && !vod_director) {
                let directors = [];
                p.find('a').each(function () {
                    let name = $(this).text().trim().replace(/&nbsp;/g, '').trim();
                    if (name) directors.push(name);
                });
                vod_director = directors.join(',');
            } else if (text.includes('类型') && !vod_class) {
                let types = [];
                p.find('a').each(function () {
                    let name = $(this).text().trim();
                    if (name) types.push(name);
                });
                vod_class = types.join(',');
            } else if (text.includes('地区') && !vod_area) {
                vod_area = text.replace(/地区[:：]/, '').trim();
            } else if ((text.includes('年份') || text.includes('上映')) && !vod_year) {
                let m = text.match(/(\d{4})/);
                if (m) vod_year = m[1];
            } else if (text.includes('状态') && !vod_remarks) {
                vod_remarks = text.replace(/状态[:：]/, '').trim();
            }
        });

        // 简介
        vod_content = $('.text_content li').first().text().trim();
        if (!vod_content) {
            vod_content = $('.text_content').first().text().trim();
        }

        // 播放线路
        let lines = [];
        let playlists = [];

        // 方法1: 从 .show_1 块提取（标准格式）
        $('.show_1').each(function () {
            let block = $(this);
            let lineName = block.find('h2').first().text().trim() || ('播放源' + (lines.length + 1));

            let links = block.find('a[href*="vod-play"]');
            let episodes = [];
            links.each(function () {
                let a = $(this);
                let epName = a.text().trim();
                let epHref = a.attr('href') || '';
                if (epName && epHref) {
                    if (epHref.startsWith('/')) epHref = appConfig.siteUrl + epHref;
                    episodes.push(epName + '$' + epHref);
                }
            });

            if (episodes.length > 0) {
                lines.push(lineName);
                playlists.push(episodes);
            }
        });

        // 方法2: 从 #play_online 区域提取所有 vod-play 链接
        if (lines.length === 0) {
            let episodes = [];
            $('#play_online a[href*="vod-play"]').each(function () {
                let a = $(this);
                let epName = a.text().trim();
                let epHref = a.attr('href') || '';
                if (epName && epHref) {
                    if (epHref.startsWith('/')) epHref = appConfig.siteUrl + epHref;
                    episodes.push(epName + '$' + epHref);
                }
            });
            if (episodes.length > 0) {
                lines.push('默认线路');
                playlists.push(episodes);
            }
        }

        // 方法3: 全局搜索所有 vod-play 链接
        if (lines.length === 0) {
            let episodes = [];
            $('a[href*="vod-play"]').each(function () {
                let a = $(this);
                let epName = a.text().trim();
                let epHref = a.attr('href') || '';
                if (epName && epHref && !episodes.some(e => e.includes(epHref))) {
                    if (epHref.startsWith('/')) epHref = appConfig.siteUrl + epHref;
                    episodes.push(epName + '$' + epHref);
                }
            });
            if (episodes.length > 0) {
                lines.push('默认线路');
                playlists.push(episodes);
            }
        }

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

// Base64 解码
function base64Decode(str) {
    try {
        str = str.replace(/-/g, '+').replace(/_/g, '/');
        while (str.length % 4) {
            str += '=';
        }
        let decoded = '';
        if (typeof Buffer !== 'undefined') {
            decoded = Buffer.from(str, 'base64').toString('utf-8');
        } else if (typeof atob !== 'undefined') {
            decoded = decodeURIComponent(escape(atob(str)));
        } else {
            let chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
            let lookup = {};
            for (let i = 0; i < chars.length; i++) lookup[chars[i]] = i;
            let bytes = [];
            for (let i = 0; i < str.length; i += 4) {
                let a = lookup[str[i]] || 0;
                let b = lookup[str[i + 1]] || 0;
                let c = lookup[str[i + 2]] || 0;
                let d = lookup[str[i + 3]] || 0;
                let n = (a << 18) | (b << 12) | (c << 6) | d;
                bytes.push((n >> 16) & 0xFF);
                if (str[i + 2] !== '=') bytes.push((n >> 8) & 0xFF);
                if (str[i + 3] !== '=') bytes.push(n & 0xFF);
            }
            decoded = '';
            for (let b of bytes) decoded += String.fromCharCode(b);
            decoded = decodeURIComponent(escape(decoded));
        }
        return decoded;
    } catch (e) {
        return '';
    }
}

async function play(flag, id, flags) {
    try {
        // 统一将 ?s= 格式转换为路径格式（?s= 格式不稳定，常返回404）
        let playUrl = id;
        let sMatch = id.match(/\?s=\/vod-play-id-(\d+-sid-\d+-pid-\d+)/);
        if (sMatch) {
            playUrl = '/index.php/vod-play-id-' + sMatch[1] + '.html';
        }
        if (!playUrl.startsWith('http')) {
            playUrl = appConfig.siteUrl + playUrl;
        }

        // 如果已经是直链 m3u8/mp4，直接播放
        if (playUrl.includes('.m3u8') || playUrl.includes('.mp4')) {
            return JSON.stringify({
                parse: 0,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' },
                url: playUrl
            });
        }

        const html = await httpGet(playUrl);

        // 从 iframe 中提取播放器 URL
        let iframeMatch = html.match(/<iframe[^>]*src=["']([^"']+player[^"']+)["']/i);
        if (!iframeMatch) {
            iframeMatch = html.match(/<iframe[^>]*src=["']([^"']+fengniaotv[^"']+)["']/i);
        }
        if (!iframeMatch) {
            iframeMatch = html.match(/<iframe[^>]*src=["']([^"']+)["']/i);
        }

        if (iframeMatch) {
            let iframeUrl = iframeMatch[1];
            if (iframeUrl.startsWith('//')) {
                iframeUrl = 'https:' + iframeUrl;
            }

            // 提取 mu 参数（base64 编码的真实 m3u8 地址）
            let muMatch = iframeUrl.match(/[?&]mu=([^&]+)/);
            if (muMatch) {
                let m3u8Url = base64Decode(decodeURIComponent(muMatch[1]));
                if (m3u8Url && (m3u8Url.includes('.m3u8') || m3u8Url.includes('.mp4'))) {
                    return JSON.stringify({
                        parse: 0,
                        Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' },
                        url: m3u8Url
                    });
                }
            }

            // 没有 mu 参数，交给播放器嗅探 iframe
            return JSON.stringify({
                parse: 1,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' },
                url: iframeUrl
            });
        }

        // 兜底：从 HTML 中正则匹配 m3u8/mp4 地址
        let urlMatch = html.match(/(https?:\/\/[^\s"'<>]+\.m3u8[^\s"'<>]*)/);
        if (urlMatch) {
            return JSON.stringify({
                parse: 0,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' },
                url: urlMatch[1]
            });
        }

        // 交给播放器嗅探
        return JSON.stringify({
            parse: 1,
            Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' },
            url: playUrl
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
