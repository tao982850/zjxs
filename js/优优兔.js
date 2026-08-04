import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
    siteName: "优优兔影视",
    siteUrl: "https://app.uutu.top",
    apiBase: "https://app.uutu.top/api/v1"
};

const UA = "okhttp/4.12.0";

// APP 版本信息
const APP_HEADERS = {
    "X-App-Version-Code": "513",
    "X-App-Version-Name": "5.1.3",
    "X-App-Pkg": "com.uututv.app",
    "User-Agent": UA
};

// 设备指纹（固定值，用于获取游客 token）
const DEVICE_FP = "uutuTvBoxCrawler2026";

// 缓存的 access_token
let cachedToken = "";
let tokenExpire = 0;

async function init(ext) {
    console.log("初始化爬虫:", appConfig.siteName);
}

// ===== 一级分类 =====
const classList = [
    { type_id: "20", type_name: "电视剧" },
    { type_id: "21", type_name: "电影" },
    { type_id: "22", type_name: "动漫" },
    { type_id: "23", type_name: "综艺" },
    { type_id: "24", type_name: "少儿" },
    { type_id: "25", type_name: "纪录片" },
    { type_id: "26", type_name: "短剧" }
];

// ===== 筛选配置（从 /video/types 接口获取的真实数据）=====
const filterConfig = {
    "20": {
        classes: ["古装","爱情","战争","谍战","剧情","都市","喜剧","动作","警匪","犯罪","武侠","冒险","悬疑","惊悚","青春","经典","农村","儿童","家庭","偶像","历史","科幻","奇幻","动画","运动","其他"],
        areas: ["大陆","香港","台湾","美国","法国","英国","日本","韩国","德国","泰国","印度","意大利","西班牙","加拿大","其他"],
        langs: ["国语","英语","粤语","闽南语","韩语","日语","法语","德语","其它"],
        years: ["2026","2025","2024","2023","2022","2021","2020","2019","2018","2017","2016","2015","2014","2013","2012","2011","2010","2009","2008","2007","2006","2005","2004"]
    },
    "21": {
        classes: ["喜剧","爱情","恐怖","动作","科幻","剧情","战争","警匪","犯罪","动画","奇幻","武侠","冒险","枪战","悬疑","惊悚","经典","青春","文艺","微电影","古装","历史","运动","农村","儿童","网络电影"],
        areas: ["大陆","香港","台湾","美国","法国","英国","日本","韩国","德国","泰国","印度","意大利","西班牙","加拿大","其他"],
        langs: ["国语","英语","粤语","闽南语","韩语","日语","法语","德语","其它"],
        years: ["2026","2025","2024","2023","2022","2021","2020","2019","2018","2017","2016","2015","2014","2013","2012","2011","2010","2009","2008","2007","2006","2005","2004"]
    },
    "22": {
        classes: ["玄幻","科幻","武侠","冒险","战斗","搞笑","恋爱","魔幻","竞技","悬疑","日常","校园","真人","经典","其他"],
        areas: ["大陆","香港","台湾","美国","法国","英国","日本","韩国","德国","泰国","印度","意大利","西班牙","加拿大","其他"],
        langs: ["国语","英语","粤语","闽南语","韩语","日语","法语","德语","其它"],
        years: ["2026","2025","2024","2023","2022","2021","2020","2019","2018","2017","2016","2015","2014","2013","2012","2011","2010","2009","2008","2007","2006","2005","2004"]
    },
    "23": {
        classes: ["大陆","港台","日韩","欧美","其他"],
        areas: ["大陆","香港","台湾","美国","法国","英国","日本","韩国","德国","泰国","印度","意大利","西班牙","加拿大","其他"],
        langs: ["国语","英语","粤语","闽南语","韩语","日语","法语","德语","其它"],
        years: ["2026","2025","2024","2023","2022","2021","2020","2019","2018","2017","2016","2015","2014","2013","2012","2011","2010","2009","2008","2007","2006","2005","2004"]
    },
    "24": {
        classes: ["大陆","港台","日韩","欧美","其他"],
        areas: ["大陆","香港","台湾","美国","法国","英国","日本","韩国","德国","泰国","印度","意大利","西班牙","加拿大","其他"],
        langs: ["国语","英语","粤语","闽南语","韩语","日语","法语","德语","其它"],
        years: ["2026","2025","2024","2023","2022","2021","2020","2019","2018","2017","2016","2015","2014","2013","2012","2011","2010","2009","2008","2007","2006","2005","2004"]
    },
    "25": {
        classes: ["大陆","港台","日韩","欧美","其他"],
        areas: ["大陆","香港","台湾","美国","法国","英国","日本","韩国","德国","泰国","印度","意大利","西班牙","加拿大","其他"],
        langs: ["国语","英语","粤语","闽南语","韩语","日语","法语","德语","其它"],
        years: ["2026","2025","2024","2023","2022","2021","2020","2019","2018","2017","2016","2015","2014","2013","2012","2011","2010","2009","2008","2007","2006","2005","2004"]
    },
    "26": {
        classes: ["都市","甜宠","逆袭","虐恋","搞笑","古装","穿越","重生","其他"],
        areas: ["大陆","香港","台湾","美国","法国","英国","日本","韩国","德国","泰国","印度","意大利","西班牙","加拿大","其他"],
        langs: ["国语","英语","粤语","闽南语","韩语","日语","法语","德语","其它"],
        years: ["2026","2025","2024","2023","2022","2021","2020","2019","2018","2017","2016","2015","2014","2013","2012","2011","2010","2009","2008","2007","2006","2005","2004"]
    }
};

const SORT_FILTER = [
    { "n": "最新", "v": "time" },
    { "n": "最热", "v": "hits" },
    { "n": "评分", "v": "score" }
];

function arrToFilter(arr) {
    let r = [{ "n": "全部", "v": "" }];
    arr.forEach(v => r.push({ "n": v, "v": v }));
    return r;
}

function buildFilters(tid) {
    let cfg = filterConfig[tid] || filterConfig["20"];
    return [
        { "key": "class", "name": "类型", "value": arrToFilter(cfg.classes) },
        { "key": "area", "name": "地区", "value": arrToFilter(cfg.areas) },
        { "key": "year", "name": "年份", "value": arrToFilter(cfg.years) },
        { "key": "lang", "name": "语言", "value": arrToFilter(cfg.langs) },
        { "key": "order", "name": "排序", "value": SORT_FILTER }
    ];
}

const myFilters = {};
classList.forEach(item => {
    myFilters[item.type_id] = buildFilters(item.type_id);
});

// ===== HTTP 请求 =====
async function httpGet(url, useAuth) {
    let headers = Object.assign({}, APP_HEADERS);
    headers["Accept"] = "application/json";
    if (useAuth) {
        let token = await getAccessToken();
        if (token) {
            headers["Authorization"] = "Bearer " + token;
            headers["X-Device-Fingerprint"] = DEVICE_FP;
        }
    }

    try {
        const resp = await req(url, { method: "GET", headers: headers });
        return resp.content || '';
    } catch (e) {
        return '';
    }
}

async function httpPost(url, body) {
    let headers = Object.assign({}, APP_HEADERS);
    headers["Content-Type"] = "application/json";
    headers["Accept"] = "application/json";

    try {
        const resp = await req(url, {
            method: "POST",
            headers: headers,
            body: typeof body === 'string' ? body : JSON.stringify(body)
        });
        return resp.content || '';
    } catch (e) {
        return '';
    }
}

// ===== 获取游客 access_token（带缓存）=====
async function getAccessToken() {
    // 缓存未过期直接返回
    let now = Math.floor(Date.now() / 1000);
    if (cachedToken && now < tokenExpire - 3600) {
        return cachedToken;
    }

    try {
        const resp = await httpPost(
            appConfig.apiBase + '/auth/device-session',
            { device_fingerprint: DEVICE_FP }
        );
        const data = JSON.parse(resp);
        if (data.code === 0 && data.data && data.data.access_token) {
            cachedToken = data.data.access_token;
            // token 有效期 24 小时，提前 1 小时刷新
            tokenExpire = now + 82800;
            return cachedToken;
        }
    } catch (e) {
        console.error("获取token失败:", e.message);
    }
    return "";
}

// ===== 构建分类列表URL =====
function buildListUrl(tid, pg, extend) {
    extend = extend || {};
    pg = pg || 1;

    let params = ['type_id=' + tid, 'page=' + pg];
    if (extend.class) params.push('class=' + encodeURIComponent(extend.class));
    if (extend.area) params.push('area=' + encodeURIComponent(extend.area));
    if (extend.year) params.push('year=' + encodeURIComponent(extend.year));
    if (extend.lang) params.push('lang=' + encodeURIComponent(extend.lang));
    if (extend.order) params.push('order=' + encodeURIComponent(extend.order));

    return appConfig.apiBase + '/video/list?' + params.join('&');
}

// ===== 解析列表 JSON =====
function parseListJson(jsonStr) {
    let list = [];
    let pagecount = 1;
    try {
        const data = JSON.parse(jsonStr);
        if (data.code !== 0 || !data.data) return { list, pagecount };

        const rawList = data.data.list || [];
        const total = data.data.total || 0;
        const size = data.data.size || 20;
        pagecount = size > 0 ? Math.ceil(total / size) : 1;
        if (pagecount < 1) pagecount = 1;

        rawList.forEach(item => {
            list.push({
                vod_id: String(item.vod_id),
                vod_name: item.vod_name || '',
                vod_pic: item.vod_pic || '',
                vod_remarks: item.vod_remarks || '',
                vod_year: item.vod_year || '',
                vod_area: item.vod_area || ''
            });
        });
    } catch (e) {
        console.error("解析列表失败:", e.message);
    }
    return { list, pagecount };
}

async function home(filter) {
    let list = [];
    try {
        // 首页取电视剧最新
        const url = buildListUrl("20", 1, {});
        const resp = await httpGet(url, false);
        const result = parseListJson(resp);
        list = result.list.slice(0, 20);
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
        const url = buildListUrl(tid, pg, extend);
        const resp = await httpGet(url, false);
        const result = parseListJson(resp);

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

        const url = appConfig.apiBase + '/search?q=' + encodeURIComponent(kw) + '&page=' + page;
        const resp = await httpGet(url, false);
        const result = parseListJson(resp);

        return JSON.stringify({ list: result.list, pagecount: result.pagecount });
    } catch (e) {
        console.error("搜索失败:", e.message);
        return JSON.stringify({ list: [], pagecount: 0 });
    }
}

async function detail(id) {
    try {
        let vid = String(id || '').trim();
        if (!vid) return JSON.stringify({ list: [] });

        const url = appConfig.apiBase + '/video/' + encodeURIComponent(vid);
        const resp = await httpGet(url, false);
        const data = JSON.parse(resp);

        if (data.code !== 0 || !data.data) {
            return JSON.stringify({ list: [] });
        }

        const v = data.data;

        // 构建播放线路和选集
        let lines = [];
        let playlists = [];
        let playSources = v.play_sources || [];

        for (let src of playSources) {
            let lineName = src.name || src.from || ('线路' + (lines.length + 1));
            let from = src.from || '';
            let episodes = src.episodes || [];
            if (episodes.length === 0) continue;

            let epList = [];
            for (let i = 0; i < episodes.length; i++) {
                let ep = episodes[i];
                let epName = ep.name || ('第' + (i + 1) + '集');
                // 播放参数格式：vod_id@@from@@episode_name
                let epUrl = vid + '@@' + encodeURIComponent(from) + '@@' + encodeURIComponent(ep.name || String(i + 1));
                epList.push(epName + '$' + epUrl);
            }

            if (epList.length > 0) {
                lines.push(lineName);
                playlists.push(epList);
            }
        }

        if (lines.length === 0) {
            lines.push('默认线路');
            playlists.push(['暂无播放地址$' + vid]);
        }

        const vod_play_from = lines.join('$$$');
        const vod_play_url = playlists.map(eps => eps.join('#')).join('$$$');

        return JSON.stringify({
            list: [{
                vod_id: vid,
                vod_name: v.vod_name || '',
                vod_pic: v.vod_pic || '',
                vod_actor: v.vod_actor || '',
                vod_director: v.vod_director || '',
                vod_remarks: v.vod_remarks || '',
                vod_year: v.vod_year || '',
                vod_area: v.vod_area || '',
                vod_lang: v.vod_lang || '',
                vod_content: v.vod_content || v.vod_blurb || '',
                vod_class: v.vod_class || '',
                vod_score: v.vod_score || '',
                vod_play_from,
                vod_play_url
            }]
        });
    } catch (error) {
        console.error("解析详情异常:", error);
        return JSON.stringify({ list: [] });
    }
}

async function play(flag, id, flags) {
    try {
        let playUrl = String(id || '');

        // 解析播放参数：vod_id@@from@@episode_name
        let parts = playUrl.split('@@');
        if (parts.length < 3) {
            return JSON.stringify({ parse: 0, url: "" });
        }

        let vodId = parts[0];
        let from = decodeURIComponent(parts[1]);
        let episode = decodeURIComponent(parts[2]);

        // 调用播放接口获取真实 m3u8
        let url = appConfig.apiBase + '/play/url?vod_id=' + encodeURIComponent(vodId) +
            '&from=' + encodeURIComponent(from) +
            '&episode=' + encodeURIComponent(episode);

        const resp = await httpGet(url, true);
        const data = JSON.parse(resp);

        if (data.code === 0 && data.data && data.data.play_url) {
            let m3u8Url = data.data.play_url;
            return JSON.stringify({
                parse: 0,
                Header: {
                    "User-Agent": UA,
                    "Referer": appConfig.siteUrl + "/"
                },
                url: m3u8Url
            });
        }

        // 兜底
        return JSON.stringify({
            parse: 1,
            Header: { "User-Agent": UA },
            url: appConfig.siteUrl
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
