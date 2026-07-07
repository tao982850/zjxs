import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
    siteName: "青木影院",
    siteUrl: "http://www.zhijiaku.com"
}
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36";

async function init(ext) {
    console.log("初始化爬虫:", appConfig.siteName);
}

const movieSubClass = [
    { "n": "全部", "v": "" }, { "n": "动作片", "v": "6" }, { "n": "喜剧片", "v": "7" },
    { "n": "爱情片", "v": "8" }, { "n": "科幻片", "v": "9" }, { "n": "恐怖片", "v": "10" },
    { "n": "剧情片", "v": "11" }, { "n": "战争片", "v": "12" }
];

const tvClass = [
    { "n": "全部", "v": "" }, { "n": "国产剧", "v": "国产剧" }, { "n": "港剧", "v": "港剧" },
    { "n": "欧美剧", "v": "欧美剧" }, { "n": "日剧", "v": "日剧" }, { "n": "韩剧", "v": "韩剧" },
    { "n": "台剧", "v": "台剧" }, { "n": "泰剧", "v": "泰剧" }
];

const yearFilter = [
    { "n": "全部", "v": "" }, { "n": "2026", "v": "2026" }, { "n": "2025", "v": "2025" },
    { "n": "2024", "v": "2024" }, { "n": "2023", "v": "2023" }, { "n": "2022", "v": "2022" },
    { "n": "2021", "v": "2021" }, { "n": "2020", "v": "2020" }, { "n": "2019", "v": "2019" },
    { "n": "2018", "v": "2018" }, { "n": "2017", "v": "2017" }, { "n": "2016", "v": "2016" },
    { "n": "2015", "v": "2015" }, { "n": "2014", "v": "2014" }, { "n": "2013", "v": "2013" },
    { "n": "2012", "v": "2012" }, { "n": "2011", "v": "2011" }, { "n": "2010", "v": "2010" },
    { "n": "2009", "v": "2009" }, { "n": "2008", "v": "2008" }
];

const letterFilter = [
    { "n": "全部", "v": "" }, { "n": "A", "v": "A" }, { "n": "B", "v": "B" },
    { "n": "C", "v": "C" }, { "n": "D", "v": "D" }, { "n": "E", "v": "E" },
    { "n": "F", "v": "F" }, { "n": "G", "v": "G" }, { "n": "H", "v": "H" },
    { "n": "I", "v": "I" }, { "n": "J", "v": "J" }, { "n": "K", "v": "K" },
    { "n": "L", "v": "L" }, { "n": "M", "v": "M" }, { "n": "N", "v": "N" },
    { "n": "O", "v": "O" }, { "n": "P", "v": "P" }, { "n": "Q", "v": "Q" },
    { "n": "R", "v": "R" }, { "n": "S", "v": "S" }, { "n": "T", "v": "T" },
    { "n": "U", "v": "U" }, { "n": "V", "v": "V" }, { "n": "W", "v": "W" },
    { "n": "X", "v": "X" }, { "n": "Y", "v": "Y" }, { "n": "Z", "v": "Z" },
    { "n": "0-9", "v": "0-9" }
];

const myFilters = {
    "1": [
        { "key": "class", "name": "子分类", "value": movieSubClass },
        { "key": "year", "name": "年份", "value": yearFilter },
        { "key": "letter", "name": "字母", "value": letterFilter }
    ],
    "2": [
        { "key": "class", "name": "类型", "value": tvClass },
        { "key": "year", "name": "年份", "value": yearFilter },
        { "key": "letter", "name": "字母", "value": letterFilter }
    ],
    "3": [
        { "key": "year", "name": "年份", "value": yearFilter },
        { "key": "letter", "name": "字母", "value": letterFilter }
    ],
    "4": [
        { "key": "year", "name": "年份", "value": yearFilter },
        { "key": "letter", "name": "字母", "value": letterFilter }
    ]
};

async function home(filter) {
    return JSON.stringify({
        class: [
            { type_id: "1", type_name: "电影" },
            { type_id: "2", type_name: "电视剧" },
            { type_id: "3", type_name: "综艺" },
            { type_id: "4", type_name: "动漫" }
        ],
        filters: myFilters
    });
}

function buildCategoryUrl(tid, pg, extend) {
    let subClass = extend.class || '';
    let targetId = subClass || tid;
    return `${appConfig.siteUrl}/vodshow/${targetId}--------${pg}---.html`;
}

async function category(tid, pg, filter, extend) {
    pg = pg || 1;
    extend = extend || {};

    let url = buildCategoryUrl(tid, pg, extend);

    try {
        const html = (await req(url)).content;
        const $ = cheerio.load(html);
        let list = [];

        $("ul.stui-vodlist.clearfix .stui-vodlist__thumb.lazyload").each(function (index, el) {
            let vod_id = $(el).attr("href");
            let vod_name = $(el).attr("title");
            let vod_pic = $(el).attr("data-original");
            let vod_remarks = $(el).find(".pic-text").text().trim();

            if (vod_id && vod_name) {
                list.push({ vod_id, vod_name, vod_pic, vod_remarks });
            }
        });

        let pagecount = 1;
        $("a:contains('尾页')").each(function () {
            let href = $(this).attr("href");
            if (href) {
                let m = href.match(/\/vodshow\/\d+--------(\d+)---\.html/);
                if (m) {
                    let p = parseInt(m[1]);
                    if (p > pagecount) pagecount = p;
                }
            }
        });

        if (pagecount <= 1) {
            let maxPage = 1;
            $(".stui-page a, .mac_pages a").each(function () {
                let href = $(this).attr("href");
                if (href) {
                    let m = href.match(/\/vodshow\/\d+--------(\d+)---\.html/);
                    if (m) {
                        let p = parseInt(m[1]);
                        if (p > maxPage) maxPage = p;
                    }
                }
            });
            pagecount = maxPage;
        }

        return JSON.stringify({ list, pagecount });
    } catch (e) {
        console.error("分类列表获取失败:", e.message);
        return JSON.stringify({ list: [], pagecount: 0 });
    }
}

async function search(wd, quick, page) {
    return JSON.stringify({ list: [], pagecount: 0 });
}

async function detail(id) {
    try {
        const html = (await req(appConfig.siteUrl + id)).content;
        const $ = cheerio.load(html);

        const vod_name = $('.stui-content__detail h1, .stui-content__detail .title').first().text().trim();
        const imgSrc = $('.stui-content__thumb img').attr("data-original") || '';
        const vod_pic = imgSrc ? (imgSrc.startsWith('http') ? imgSrc : appConfig.siteUrl + imgSrc) : '';

        let vod_actor = '';
        let vod_director = '';
        let vod_remarks = '';
        let vod_year = '';
        let vod_area = '';
        let vod_lang = '';

        $('.stui-content__detail p.data').each((i, el) => {
            const text = $(el).text();
            if (text.includes('主演')) {
                vod_actor = $(el).find('a').map(function () { return $(this).text().trim(); }).get().join(',');
            } else if (text.includes('导演')) {
                vod_director = $(el).find('a').map(function () { return $(this).text().trim(); }).get().join(',');
            } else if (text.includes('更新') || text.includes('状态')) {
                vod_remarks = text.replace(/.*(?:更新|状态)[：:]/g, '').trim();
            } else if (text.includes('年份')) {
                vod_year = $(el).find('a').text().trim();
            } else if (text.includes('地区')) {
                vod_area = $(el).find('a').text().trim();
            } else if (text.includes('语言')) {
                vod_lang = $(el).find('a').text().trim();
            }
        });

        const vod_content = $('.stui-content__detail .detail, .stui-content__detail .desc').text().trim();

        let rawLines = [];
        let rawPlaylists = [];

        $('.nav-tabs li a').each((i, el) => {
            const lineName = $(el).text().trim();
            if (lineName && lineName !== '全部') {
                rawLines.push(lineName);
            }
        });

        $('.stui-content__playlist').each((lineIndex, poolEl) => {
            const episodes = [];
            $(poolEl).find('a').each((episodeIndex, epEl) => {
                const name = $(epEl).text().trim();
                const href = $(epEl).attr('href') || '';
                if (name && href) {
                    episodes.push(`${name}$${href}`);
                }
            });
            rawPlaylists.push(episodes);
        });

        if (rawLines.length === 0 && rawPlaylists.length > 0) {
            for (let i = 0; i < rawPlaylists.length; i++) {
                rawLines.push(`线路${i + 1}`);
            }
        }

        let finalLines = [];
        let finalPlaylists = [];
        for (let i = 0; i < rawLines.length; i++) {
            if (rawPlaylists[i] && rawPlaylists[i].length > 0) {
                finalLines.push(rawLines[i]);
                finalPlaylists.push(rawPlaylists[i]);
            }
        }

        const { vod_play_from, vod_play_url } = buildVodPlayData(finalLines, finalPlaylists);

        const vod = {
            vod_id: id, vod_name, vod_pic, vod_actor, vod_director,
            vod_remarks, vod_year, vod_area, vod_lang, vod_content,
            vod_play_from, vod_play_url
        };

        return JSON.stringify({ list: [vod] });
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

function extractVideoUrl(html) {
    // 先定位player_aaaa变量位置，再在其范围内提取url
    let paIdx = html.indexOf('var player_aaaa=');
    if (paIdx >= 0) {
        // 找到对应的script结束标签，限制搜索范围
        let scriptEnd = html.indexOf('</script>', paIdx);
        if (scriptEnd > 0) {
            let playerContent = html.substring(paIdx, scriptEnd);
            // 在player_aaaa内容中提取第一个url字段
            let urlMatch = playerContent.match(/"url"\s*:\s*"([^"]+)"/);
            if (urlMatch) {
                // 去掉转义的反斜杠
                return urlMatch[1].replace(/\\\//g, '/');
            }
        }
    }
    return '';
}

async function play(flag, id, flags) {
    try {
        const html = (await req(`${appConfig.siteUrl}${id}`)).content;
        const url = extractVideoUrl(html);

        if (url) {
            if (url.endsWith('.m3u8') || url.endsWith('.mp4') || url.endsWith('.flv')) {
                return JSON.stringify({
                    parse: 0,
                    Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                    url: url
                });
            }
            return JSON.stringify({
                parse: 1,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: url
            });
        }

        // 备用：查找iframe
        const iframeMatch = html.match(/<iframe[^>]*src="([^"]+)"/);
        if (iframeMatch) {
            return JSON.stringify({
                parse: 1,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: iframeMatch[1]
            });
        }

        return JSON.stringify({ parse: 0, url: "" });
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
