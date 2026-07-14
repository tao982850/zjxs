import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
    siteName: "电影港",
    siteUrl: "https://www.wagamm.com"
}
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36";
const Headers = {
    "User-Agent": UA,
    "Referer": appConfig.siteUrl + "/",
}

async function init(ext) {
    console.log("初始化爬虫:", appConfig.siteName);
}

function getYearFilter() {
    let years = [{ "n": "全部", "v": "" }];
    const currentYear = new Date().getFullYear().toString();
    for (let y = currentYear; y >= currentYear - 22; y--) {
        years.push({ "n": String(y), "v": String(y) });
    }
    return { "key": "year", "name": "年份", "value": years };
}

function getLetterFilter() {
    return {
        "key": "letter", "name": "字母", "value": [
            { "n": "全部", "v": "" },
            { "n": "A", "v": "A" }, { "n": "B", "v": "B" }, { "n": "C", "v": "C" }, { "n": "D", "v": "D" },
            { "n": "E", "v": "E" }, { "n": "F", "v": "F" }, { "n": "G", "v": "G" }, { "n": "H", "v": "H" },
            { "n": "I", "v": "I" }, { "n": "J", "v": "J" }, { "n": "K", "v": "K" }, { "n": "L", "v": "L" },
            { "n": "M", "v": "M" }, { "n": "N", "v": "N" }, { "n": "O", "v": "O" }, { "n": "P", "v": "P" },
            { "n": "Q", "v": "Q" }, { "n": "R", "v": "R" }, { "n": "S", "v": "S" }, { "n": "T", "v": "T" },
            { "n": "U", "v": "U" }, { "n": "V", "v": "V" }, { "n": "W", "v": "W" }, { "n": "X", "v": "X" },
            { "n": "Y", "v": "Y" }, { "n": "Z", "v": "Z" }, { "n": "0-9", "v": "0-9" }
        ]
    }
}

function getOrderFilter() {
    return {
        "key": "order", "name": "排序", "value": [
            { "n": "按时间", "v": "time" },
            { "n": "按人气", "v": "hit" }
        ]
    }
}

const CommonFilters = [
    {
        "key": "area", "name": "地区", "value": [
            { "n": "全部", "v": "" }, { "n": "大陆", "v": "大陆" }, { "n": "香港", "v": "香港" },
            { "n": "台湾", "v": "台湾" }, { "n": "美国", "v": "美国" }, { "n": "韩国", "v": "韩国" },
            { "n": "日本", "v": "日本" }, { "n": "泰国", "v": "泰国" }, { "n": "英国", "v": "英国" },
            { "n": "法国", "v": "法国" }, { "n": "德国", "v": "德国" }, { "n": "印度", "v": "印度" },
            { "n": "加拿大", "v": "加拿大" }, { "n": "西班牙", "v": "西班牙" }, { "n": "俄罗斯", "v": "俄罗斯" },
            { "n": "其它", "v": "其它" }
        ]
    },
    {
        "key": "lang", "name": "语言", "value": [
            { "n": "全部", "v": "" }, { "n": "国语", "v": "国语" }, { "n": "英语", "v": "英语" },
            { "n": "粤语", "v": "粤语" }, { "n": "闽南语", "v": "闽南语" }, { "n": "韩语", "v": "韩语" },
            { "n": "日语", "v": "日语" }, { "n": "其它", "v": "其它" }
        ]
    },
    getYearFilter(),
    getLetterFilter(),
    getOrderFilter()
];

const myFilters = {
    "1": [
        {
            key: "class", name: "剧情", value: [
                { "n": "全部", "v": "" }, { "n": "喜剧", "v": "喜剧" }, { "n": "爱情", "v": "爱情" },
                { "n": "恐怖", "v": "恐怖" }, { "n": "动作", "v": "动作" }, { "n": "科幻", "v": "科幻" },
                { "n": "剧情", "v": "剧情" }, { "n": "战争", "v": "战争" }, { "n": "犯罪", "v": "犯罪" },
                { "n": "动画", "v": "动画" }, { "n": "奇幻", "v": "奇幻" }, { "n": "武侠", "v": "武侠" },
                { "n": "冒险", "v": "冒险" }, { "n": "枪战", "v": "枪战" }, { "n": "悬疑", "v": "悬疑" },
                { "n": "惊悚", "v": "惊悚" }, { "n": "经典", "v": "经典" }, { "n": "青春", "v": "青春" },
                { "n": "文艺", "v": "文艺" }, { "n": "微电影", "v": "微电影" }, { "n": "古装", "v": "古装" },
                { "n": "历史", "v": "历史" }, { "n": "运动", "v": "运动" }, { "n": "农村", "v": "农村" },
                { "n": "儿童", "v": "儿童" }, { "n": "网络电影", "v": "网络电影" }
            ]
        },
        ...CommonFilters
    ],
    "2": [
        {
            key: "class", name: "剧情", value: [
                { "n": "全部", "v": "" }, { "n": "古装", "v": "古装" }, { "n": "战争", "v": "战争" },
                { "n": "青春偶像", "v": "青春偶像" }, { "n": "喜剧", "v": "喜剧" }, { "n": "家庭", "v": "家庭" },
                { "n": "犯罪", "v": "犯罪" }, { "n": "动作", "v": "动作" }, { "n": "奇幻", "v": "奇幻" },
                { "n": "剧情", "v": "剧情" }, { "n": "历史", "v": "历史" }, { "n": "经典", "v": "经典" },
                { "n": "乡村", "v": "乡村" }, { "n": "情景", "v": "情景" }, { "n": "商战", "v": "商战" },
                { "n": "网剧", "v": "网剧" }, { "n": "其他", "v": "其他" }
            ]
        },
        ...CommonFilters
    ],
    "3": [
        {
            key: "class", name: "剧情", value: [
                { "n": "全部", "v": "" }, { "n": "情感", "v": "情感" }, { "n": "科幻", "v": "科幻" },
                { "n": "热血", "v": "热血" }, { "n": "推理", "v": "推理" }, { "n": "搞笑", "v": "搞笑" },
                { "n": "冒险", "v": "冒险" }, { "n": "萝莉", "v": "萝莉" }, { "n": "校园", "v": "校园" },
                { "n": "动作", "v": "动作" }, { "n": "机战", "v": "机战" }, { "n": "运动", "v": "运动" },
                { "n": "战争", "v": "战争" }, { "n": "少年", "v": "少年" }, { "n": "少女", "v": "少女" },
                { "n": "社会", "v": "社会" }, { "n": "原创", "v": "原创" }, { "n": "亲子", "v": "亲子" },
                { "n": "益智", "v": "益智" }, { "n": "励志", "v": "励志" }, { "n": "其他", "v": "其他" }
            ]
        },
        ...CommonFilters
    ],
    "4": [
        {
            key: "class", name: "剧情", value: [
                { "n": "全部", "v": "" }, { "n": "选秀", "v": "选秀" }, { "n": "情感", "v": "情感" },
                { "n": "访谈", "v": "访谈" }, { "n": "播报", "v": "播报" }, { "n": "旅游", "v": "旅游" },
                { "n": "音乐", "v": "音乐" }, { "n": "美食", "v": "美食" }, { "n": "纪实", "v": "纪实" },
                { "n": "曲艺", "v": "曲艺" }, { "n": "生活", "v": "生活" }, { "n": "游戏互动", "v": "游戏互动" },
                { "n": "财经", "v": "财经" }, { "n": "求职", "v": "求职" }
            ]
        },
        ...CommonFilters
    ],
    "40": [
        ...CommonFilters
    ],
};

async function home(filter) {
    return JSON.stringify({
        class: [
            { type_id: "1", type_name: "电影" },
            { type_id: "2", type_name: "电视剧" },
            { type_id: "3", type_name: "动漫" },
            { type_id: "4", type_name: "综艺" }
        ],
        filters: myFilters
    });
}

async function category(tid, pg, filter, extend) {
    pg = pg || 1;
    extend = extend || {};
    let classVal = extend.class || '';
    let areaVal = extend.area || '';
    let langVal = extend.lang || '';
    let letterVal = extend.letter || '';
    let orderVal = extend.order || '';
    let yearVal = extend.year || '';

    let url = `${appConfig.siteUrl}/list/${tid}.html`;
    if (pg > 1) {
        url = `${appConfig.siteUrl}/list/${tid}_${pg}.html`;
    }

    let params = [];
    if (classVal) params.push(`class=${encodeURIComponent(classVal)}`);
    if (areaVal) params.push(`area=${encodeURIComponent(areaVal)}`);
    if (langVal) params.push(`lang=${encodeURIComponent(langVal)}`);
    if (letterVal) params.push(`letter=${encodeURIComponent(letterVal)}`);
    if (orderVal) params.push(`order=${encodeURIComponent(orderVal)}`);
    if (yearVal) params.push(`year=${encodeURIComponent(yearVal)}`);
    if (params.length > 0) {
        url += '?' + params.join('&');
    }

    try {
        const html = (await req(url)).content;
        const $ = cheerio.load(html);
        let list = [];

        $(".stui-vodlist__thumb").each(function (index, el) {
            let vod_id = $(el).attr("href");
            let vod_name = $(el).attr("title");
            if (vod_name) vod_name = vod_name.replace(/高清$|HD中字$|HD国语$|正片$|TC中字$|TC$|HD$/, '').trim();
            let vod_pic = $(el).attr("data-original");
            let vod_remarks = $(el).find(".pic-text").text().trim();

            if (vod_id) {
                list.push({
                    vod_id,
                    vod_name,
                    vod_pic,
                    vod_remarks
                });
            }
        });

        let pagecount = 1;
        const lastPageLink = $("a:contains('尾页')").attr("href");
        if (lastPageLink) {
            const parts = lastPageLink.replace('.html', '').split('_');
            for (let i = parts.length - 1; i >= 0; i--) {
                const num = parseInt(parts[i]);
                if (num > 0) {
                    pagecount = num;
                    break;
                }
            }
        }

        return JSON.stringify({
            list,
            pagecount
        });
    } catch (e) {
        console.error("分类列表获取失败:", e.message);
        return JSON.stringify({ list: [], pagecount: 0 });
    }
}

async function search(wd, quick, page) {
    if (page >= 2) {
        return JSON.stringify({ list: [], pagecount: 1 });
    }

    try {
        const url = `${appConfig.siteUrl}/index.php?m=vod-search&wd=${encodeURIComponent(wd)}`;
        const html = (await req(url)).content;
        const $ = cheerio.load(html);
        let list = [];

        $(".stui-vodlist__thumb").each(function (i, el) {
            const vod_id = $(el).attr("href") || '';
            let vod_name = $(el).attr("title") || '';
            if (vod_name) vod_name = vod_name.replace(/高清$|HD中字$|HD国语$|正片$|TC中字$|TC$|HD$/, '').trim();
            const vod_pic = $(el).attr("data-original") || '';
            const vod_remarks = $(el).find(".pic-text").text().trim();

            if (vod_id) {
                list.push({
                    vod_id,
                    vod_name,
                    vod_pic,
                    vod_remarks
                });
            }
        });

        return JSON.stringify({
            list: list,
            pagecount: 1
        });
    } catch (e) {
        console.error("搜索失败:", e.message);
        return JSON.stringify({ list: [] });
    }
}

async function detail(id) {
    try {
        const url = appConfig.siteUrl + id;
        const html = (await req(url)).content;
        const $ = cheerio.load(html);

        const vod_name = $('.stui-content__detail h1.title a').text().trim();
        const imgSrc = $('.stui-content__thumb img').attr("data-original") || '';
        const vod_pic = imgSrc ? (imgSrc.startsWith('http') ? imgSrc : appConfig.siteUrl + imgSrc) : '';

        let vod_actor = '';
        let vod_director = '';
        let vod_remarks = '';
        let vod_year = '';
        let vod_area = '';

        $('.stui-content__detail p.data').each((i, el) => {
            const text = $(el).text();
            if (text.includes('主演')) {
                vod_actor = $(el).find('a').map(function () { return $(this).text().trim(); }).get().join(',');
            } else if (text.includes('导演')) {
                vod_director = $(el).find('a').map(function () { return $(this).text().trim(); }).get().join(',');
            } else if (text.includes('状态')) {
                vod_remarks = text.replace(/状态[：:]/g, '').trim();
            } else if (text.includes('地区')) {
                vod_area = $(el).find('a').text().trim();
            } else if (text.includes('年份')) {
                vod_year = $(el).find('a').text().trim();
            }
        });

        const vod_content = $('.col-pd').text().trim();

        let rawLines = [];
        let rawPlaylists = [];

        $('.nav-tabs li a').each((i, el) => {
            const lineName = $(el).text().trim();
            if (lineName && lineName !== '全部' && lineName !== '全部资源') {
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

        if (rawLines.length === 0) {
            rawLines.push('默认线路');
        }

        let finalLines = [];
        let finalPlaylists = [];
        for (let i = 0; i < rawLines.length; i++) {
            if (rawPlaylists[i] && rawPlaylists[i].length > 0) {
                finalLines.push(rawLines[i]);
                finalPlaylists.push(rawPlaylists[i]);
            }
        }

        const { vod_play_from, vod_play_url } = buildVodPlayData(finalLines, finalPlaylists, false);

        const vod = {
            vod_id: id,
            vod_name,
            vod_pic,
            vod_actor,
            vod_director,
            vod_remarks,
            vod_year,
            vod_area,
            vod_content,
            vod_play_from,
            vod_play_url
        };

        return JSON.stringify({ list: [vod] });
    } catch (error) {
        console.error(`解析详情页异常 [ID: ${id}]:`, error);
        return JSON.stringify({ list: [] });
    }
}

function buildVodPlayData(lines, playlists, shouldReverse) {
    const processedPlaylists = playlists.map(eps => {
        if (shouldReverse) {
            eps.reverse();
        }
        return eps.join('#');
    });
    return {
        vod_play_from: lines.filter(Boolean).join('$$$'),
        vod_play_url: processedPlaylists.join('$$$')
    };
}

async function play(flag, id, flags) {
    try {
        const html = (await req(appConfig.siteUrl + id)).content;
        const $ = cheerio.load(html);

        const iframeSrc = $('iframe').attr('src');
        if (iframeSrc) {
            return JSON.stringify({
                parse: 1,
                Header: {
                    "User-Agent": UA,
                    "Referer": appConfig.siteUrl
                },
                url: iframeSrc
            });
        }

        const playerMatch = html.match(/var\s+player_aaaa[\s\S]*?"url"\s*:\s*"([^"]+)"/);
        if (playerMatch) {
            let url = playerMatch[1].replace(/\\/g, '');
            if (url.startsWith('http')) {
                return JSON.stringify({
                    parse: 0,
                    Header: {
                        "User-Agent": UA,
                        "Referer": appConfig.siteUrl
                    },
                    url: url
                });
            }
            return JSON.stringify({
                parse: 1,
                Header: {
                    "User-Agent": UA,
                    "Referer": appConfig.siteUrl
                },
                url: url
            });
        }

        return JSON.stringify({
            parse: 1,
            Header: {
                "User-Agent": UA,
                "Referer": appConfig.siteUrl
            },
            url: `${appConfig.siteUrl}${id}`
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
